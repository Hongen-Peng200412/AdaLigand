"""单 occurrence 的端到端离线适配。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from rdkit import Chem

from pocketxmol_compat.constants import POCKETXMOL_COMMIT
from pocketxmol_compat.io import atomic_save_npz, atomic_write_json, read_jsonl
from pocketxmol_compat.ligand import (
    ligand_native_arrays,
    ligand_to_rdkit,
    load_and_audit_ligand,
    peptide_native_fields,
)
from pocketxmol_compat.official_motion import get_official_torsional_info, split_torsional_info
from pocketxmol_compat.receptor import build_receptor_products
from pocketxmol_compat.records import AdaptRequest, AdaptResult


ADAPT_RECORD_SCHEMA_VERSION = 2


def adapt_occurrence(request: AdaptRequest) -> AdaptResult:
    """适配一个 `(pdb_id, candidate_id)`，并在最后写完成标记。"""

    pdb_id = request.pdb_id.lower()
    cached = _load_cached_result(request, pdb_id)
    if cached is not None:
        return cached
    parse_dir = request.stage_c_root / "parse" / pdb_id
    occurrences = read_jsonl(parse_dir / "occurrences.jsonl")
    matches = [row for row in occurrences if int(row["candidate_id"]) == request.candidate_id]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one occurrence for {pdb_id}:{request.candidate_id}, got {len(matches)}"
        )
    occurrence = matches[0]
    with np.load(parse_dir / "ligand_coords.npz", allow_pickle=False) as coords_archive:
        ligand = load_and_audit_ligand(
            request.stage_c_root,
            occurrence,
            coords_archive,
            request.ccd_audit_path,
        )

    common = {
        "pdb_id": pdb_id,
        "candidate_id": request.candidate_id,
        "split": request.split,
        "object_key": str(occurrence["object_key"]),
        "type_tag": str(occurrence["type_tag"]),
    }
    if ligand.reasons:
        return _finish_result(request, AdaptResult(
            **common,
            pocketxmol_eligible=False,
            extended_contract_eligible=False,
            active_for_stage3=False,
            reasons=ligand.reasons,
        ))

    native_arrays = ligand_native_arrays(ligand)
    mol = ligand_to_rdkit(ligand)
    try:
        torsion = get_official_torsional_info(
            request.pocketxmol_root,
            mol,
            native_arrays["bond_index"],
            f"{pdb_id}_{request.candidate_id}",
        )
    except Exception:
        return _finish_result(request, AdaptResult(
            **common,
            pocketxmol_eligible=False,
            extended_contract_eligible=False,
            active_for_stage3=False,
            reasons=("official_motion_preprocess_failed",),
        ))
    torsion_arrays, torsion_metadata = split_torsional_info(torsion)
    native_arrays.update(torsion_arrays)

    receptor = build_receptor_products(request.stage_c_root, pdb_id, ligand.coords)
    instance_name = f"{pdb_id}_{request.candidate_id}"
    native_relative: str | None = None
    extended_relative: str | None = None

    extended_eligible = receptor.extended_arrays is not None
    if extended_eligible:
        extended_dir = request.output_root / "adaligand_extended" / request.split / instance_name
        atomic_save_npz(extended_dir / "receptor.npz", receptor.extended_arrays)
        atomic_write_json(
            extended_dir / "source.json",
            _source_metadata(request, occurrence, active_for_stage3=False),
        )
        atomic_write_json(extended_dir / "complete.json", {"complete": True})
        extended_relative = str(extended_dir.relative_to(request.output_root)).replace("\\", "/")

    strict_eligible = not receptor.strict_reasons and receptor.strict_arrays is not None
    if strict_eligible:
        native_arrays.update(receptor.strict_arrays)
        native_metadata: dict[str, Any] = {
            **torsion_metadata,
            **(receptor.strict_metadata or {}),
            "data_id": instance_name,
            "pdbid": pdb_id,
            "smiles": ligand.smiles,
            "num_atoms": int(len(ligand.atoms)),
            "num_bonds": int(len(ligand.bonds)),
            "num_confs": 1,
            "i_conf_list": [0],
            "is_peptide_expected_from_official_featurizer": 0,
            "motion_runtime_fields": [
                "tor_bonds_anno", "twisted_nodes_anno", "dihedral_pairs_anno"
            ],
        }
        if str(occurrence["type_tag"]) == "peptide_like":
            peptide_arrays, peptide_metadata = peptide_native_fields(ligand)
            native_arrays.update(peptide_arrays)
            native_metadata.update(peptide_metadata)

        native_dir = request.output_root / "pocketxmol_native" / request.split / instance_name
        atomic_save_npz(native_dir / "arrays.npz", native_arrays)
        atomic_write_json(native_dir / "metadata.json", native_metadata)
        atomic_write_json(
            native_dir / "source.json",
            _source_metadata(request, occurrence, active_for_stage3=True),
        )
        # SDF 仅用于化学图/官方 raw 入口对照；Builder 正式 Dataset 读取上面的原生字段。
        native_dir.mkdir(parents=True, exist_ok=True)
        Chem.MolToMolFile(mol, str(native_dir / "ligand_reference.sdf"))
        atomic_write_json(native_dir / "complete.json", {"complete": True})
        native_relative = str(native_dir.relative_to(request.output_root)).replace("\\", "/")

    reasons = tuple(receptor.strict_reasons)
    return _finish_result(request, AdaptResult(
        **common,
        pocketxmol_eligible=strict_eligible,
        extended_contract_eligible=extended_eligible,
        active_for_stage3=strict_eligible,
        reasons=reasons,
        native_path=native_relative,
        extended_path=extended_relative,
    ))


def _result_path(request: AdaptRequest, pdb_id: str) -> Path:
    """返回单实例缓存记录路径。"""

    return (
        request.output_root
        / "records"
        / request.split
        / f"{pdb_id}_{request.candidate_id}.json"
    )


def _load_cached_result(request: AdaptRequest, pdb_id: str) -> AdaptResult | None:
    """在未要求覆盖时复用已完成记录，并核对记录声称的目录完成标记。"""

    if request.overwrite:
        return None
    path = _result_path(request, pdb_id)
    if not path.is_file():
        return None
    import json

    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.pop("record_schema_version", None) != ADAPT_RECORD_SCHEMA_VERSION:
        return None
    payload["reasons"] = tuple(payload.get("reasons", []))
    result = AdaptResult(**payload)
    for eligible, relative in (
        (result.pocketxmol_eligible, result.native_path),
        (result.extended_contract_eligible, result.extended_path),
    ):
        if eligible and (
            relative is None
            or not (request.output_root / relative / "complete.json").is_file()
        ):
            raise ValueError(f"cached result points to an incomplete directory: {path}")
    return result


def _finish_result(request: AdaptRequest, result: AdaptResult) -> AdaptResult:
    """把单实例结果作为缓存的最后一步原子写入。"""

    atomic_write_json(
        _result_path(request, result.pdb_id),
        {"record_schema_version": ADAPT_RECORD_SCHEMA_VERSION, **result.to_json()},
    )
    return result


def _source_metadata(
    request: AdaptRequest,
    occurrence: dict[str, Any],
    *,
    active_for_stage3: bool,
) -> dict[str, Any]:
    """记录可读来源身份；正式代码不计算或保存内容哈希。"""

    return {
        "source_stage_c_root": str(request.stage_c_root.resolve()),
        "source_chemistry_audit": str(request.ccd_audit_path.resolve()),
        "source_split": request.split,
        "pdb_id": request.pdb_id.lower(),
        "candidate_id": request.candidate_id,
        "object_key": str(occurrence["object_key"]),
        "type_tag": str(occurrence["type_tag"]),
        "pocketxmol_commit": POCKETXMOL_COMMIT,
        "active_for_stage3": active_for_stage3,
    }
