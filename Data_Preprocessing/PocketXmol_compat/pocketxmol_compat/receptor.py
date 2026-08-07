"""按官方 10 Å 训练定义构造 strict 与 extended 两套受体产物。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import gemmi
import numpy as np
from rdkit import Chem

from pocketxmol_compat.constants import (
    AA_TO_INDEX,
    AMINO_ACIDS,
    BACKBONE_ATOM_NAMES,
    NUCLEIC_COMPONENTS,
    POCKET_ATOMIC_NUMBERS,
    STRICT_RECEPTOR_REASONS,
)


@dataclass(frozen=True)
class ReceptorProducts:
    """同一几何口袋的严格 PocketXMol 产物和 A–G 扩展产物。"""

    strict_reasons: tuple[str, ...]
    strict_arrays: dict[str, np.ndarray] | None
    strict_metadata: dict[str, Any] | None
    extended_arrays: dict[str, np.ndarray] | None
    selected_residue_count: int


def build_receptor_products(
    stage_c_root: Path,
    pdb_id: str,
    ligand_coords: np.ndarray,
) -> ReceptorProducts:
    """回读原始 mmCIF，在全部 polymer 残基上执行严格小于 10 Å 的质量中心选择。"""

    from adaligand_preprocessing.stages.stage_c.contracts import compare_receptor_base_arrays
    from adaligand_preprocessing.stages.stage_c.pipeline import (
        category_rows,
        optional_category_rows,
        residue_key,
        selected_atom_rows,
        split_candidate_atoms,
    )
    from adaligand_preprocessing.stages.stage_c.receptor import build_receptor_base_arrays

    cif_path = stage_c_root / "raw" / "rcsb_mmcif" / f"{pdb_id.lower()}.cif"
    block = gemmi.cif.read(str(cif_path)).sole_block()
    all_atoms = selected_atom_rows(category_rows(block, "_atom_site."))
    entity_rows = category_rows(block, "_entity.")
    entity_types = {str(row["id"]): str(row["type"]).lower() for row in entity_rows}
    _, receptor_atoms = split_candidate_atoms(all_atoms, entity_types)

    receptor_path = stage_c_root / "parse" / pdb_id.lower() / "receptor_tokens.npz"
    with np.load(receptor_path, allow_pickle=False) as archive:
        stored = {key: np.array(archive[key], copy=True) for key in archive.files}
    rebuilt = build_receptor_base_arrays(receptor_atoms)
    alignment_reasons = compare_receptor_base_arrays(stored, rebuilt)
    if alignment_reasons:
        raise ValueError("raw mmCIF and receptor_tokens are not aligned: " + ",".join(alignment_reasons))

    residue_to_indices: dict[tuple[str, str, str, str], list[int]] = {}
    for atom_index, atom in enumerate(receptor_atoms):
        residue_to_indices.setdefault(residue_key(atom), []).append(atom_index)
    selected_residues = _select_residues(receptor_atoms, residue_to_indices, ligand_coords)
    if not selected_residues:
        return ReceptorProducts(
            ("empty_official_protein_pocket",), None, None, None, 0
        )

    chem_comp_rows = optional_category_rows(block, "_chem_comp.")
    chem_comp = {str(row.get("id", "")).upper(): row for row in chem_comp_rows}
    entity_poly = {
        str(row.get("entity_id", "")): str(row.get("type", "")).lower()
        for row in optional_category_rows(block, "_entity_poly.")
    }

    classifications: list[str] = []
    for key in selected_residues:
        atom = receptor_atoms[residue_to_indices[key][0]]
        classifications.append(_classify_residue(atom, chem_comp, entity_poly))
    strict_reasons = [
        STRICT_RECEPTOR_REASONS[kind]
        for kind in ("nucleic", "modified", "nonstandard")
        if kind in classifications
    ]
    standard_residues = sum(kind == "standard" for kind in classifications)
    if standard_residues == 0:
        strict_reasons.append("empty_official_protein_pocket")

    selected_indices = np.asarray(
        [index for key in selected_residues for index in residue_to_indices[key]], dtype=np.int64
    )
    extended = _slice_extended(stored, selected_indices)
    if strict_reasons:
        return ReceptorProducts(
            tuple(strict_reasons), None, None, extended, len(selected_residues)
        )

    strict_atoms = [receptor_atoms[index] for index in selected_indices]
    try:
        strict_arrays, strict_metadata = _strict_native_fields(strict_atoms)
    except ValueError as exc:
        if str(exc) != "unsupported_receptor_element":
            raise
        return ReceptorProducts(
            ("unsupported_receptor_element",), None, None, extended, len(selected_residues)
        )
    return ReceptorProducts((), strict_arrays, strict_metadata, extended, len(selected_residues))


def _select_residues(
    receptor_atoms: list[dict[str, Any]],
    residue_to_indices: dict[tuple[str, str, str, str], list[int]],
    ligand_coords: np.ndarray,
) -> list[tuple[str, str, str, str]]:
    """选择质量中心到任一真实配体重原子严格小于 10 Å 的完整残基。"""

    periodic_table = Chem.GetPeriodicTable()
    selected: list[tuple[str, str, str, str]] = []
    ligand = np.asarray(ligand_coords, dtype=np.float64)
    for key, indices in residue_to_indices.items():
        coords = np.asarray(
            [[receptor_atoms[index][axis] for axis in ("x", "y", "z")] for index in indices],
            dtype=np.float64,
        )
        masses = np.asarray(
            [
                periodic_table.GetAtomicWeight(
                    periodic_table.GetAtomicNumber(receptor_atoms[index]["element"].title())
                )
                for index in indices
            ],
            dtype=np.float64,
        )
        center = np.sum(coords * masses[:, None], axis=0) / masses.sum()
        if np.linalg.norm(ligand - center[None], axis=1).min() < 10.0:
            selected.append(key)
    return selected


def _classify_residue(
    atom: dict[str, Any],
    chem_comp: dict[str, dict[str, str]],
    entity_poly: dict[str, str],
) -> str:
    """在删除任何原子前，按 raw polymer 身份分类受体残基。"""

    name = str(atom["label_comp_id"]).upper()
    polymer_type = entity_poly.get(str(atom["label_entity_id"]), "")
    component = chem_comp.get(name, {})
    component_type = str(component.get("type", "")).lower()
    if (
        name in NUCLEIC_COMPONENTS
        or "ribonucleotide" in polymer_type
        or "polyribonucleotide" in polymer_type
        or "rna" in component_type
        or "dna" in component_type
    ):
        return "nucleic"
    if name in AMINO_ACIDS:
        return "standard"
    parent = str(component.get("mon_nstd_parent_comp_id", "")).upper()
    if parent in AMINO_ACIDS or "peptide" in component_type:
        return "modified"
    return "nonstandard"


def _strict_native_fields(
    atoms: list[dict[str, Any]],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """生成 FeaturizePocket 的原始字段，并额外保存25维审计副本。"""

    periodic_table = Chem.GetPeriodicTable()
    element = np.asarray(
        [periodic_table.GetAtomicNumber(atom["element"].title()) for atom in atoms],
        dtype=np.int64,
    )
    if not np.isin(element, np.asarray(POCKET_ATOMIC_NUMBERS)).all():
        raise ValueError("unsupported_receptor_element")
    residue_type = np.asarray(
        [AA_TO_INDEX[str(atom["label_comp_id"]).upper()] for atom in atoms], dtype=np.int64
    )
    is_backbone = np.asarray(
        [str(atom["label_atom_id"]) in BACKBONE_ATOM_NAMES for atom in atoms], dtype=bool
    )
    feature = np.zeros((len(atoms), 25), dtype=np.float32)
    element_index = {atomic_number: index for index, atomic_number in enumerate(POCKET_ATOMIC_NUMBERS)}
    for index, atomic_number in enumerate(element):
        feature[index, element_index[int(atomic_number)]] = 1.0
        feature[index, 4 + int(residue_type[index])] = 1.0
        feature[index, 24] = float(is_backbone[index])
    arrays = {
        "pocket_element": element,
        "pocket_pos": np.asarray(
            [[atom[axis] for axis in ("x", "y", "z")] for atom in atoms], dtype=np.float32
        ),
        "pocket_is_backbone": is_backbone,
        "pocket_atom_to_aa_type": residue_type,
        "pocket_atom_feature_audit": feature,
    }
    metadata = {"pocket_atom_name": [str(atom["label_atom_id"]) for atom in atoms]}
    return arrays, metadata


def _slice_extended(stored: dict[str, np.ndarray], selected_indices: np.ndarray) -> dict[str, np.ndarray]:
    """从完整受体切片49维特征，并把口袋内部化学键重编号。"""

    arrays = {
        key: np.asarray(stored[key][selected_indices])
        for key in ("coords", "element", "res_type", "is_backbone", "atom_name", "res_index", "chain_index", "feat")
    }
    old_to_new = np.full(len(stored["coords"]), -1, dtype=np.int64)
    old_to_new[selected_indices] = np.arange(len(selected_indices), dtype=np.int64)
    bond_index = np.asarray(stored["bond_index"], dtype=np.int64)
    keep = np.isin(bond_index[0], selected_indices) & np.isin(bond_index[1], selected_indices)
    arrays["bond_index"] = old_to_new[bond_index[:, keep]].astype(np.int32, copy=False)
    arrays["bond_type"] = np.asarray(stored["bond_type"][keep], dtype=np.uint8)
    return arrays
