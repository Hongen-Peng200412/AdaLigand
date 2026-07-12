"""Run-scoped Stage C full-rebuild 主键审计与事务恢复测试。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import c_source_rebuild
from c_source_rebuild import (
    SourceRebuildError,
    apply_prepared_source_rebuilds,
    build_primary_key_migration,
    canonical_stage_c_paths,
    prepare_stage_c_source_rebuild,
    staged_artifact_paths,
)
from io_utils import atomic_save_npz, sha256_file, write_jsonl
from parse import StageCSourceView
from reports import write_report


def _occurrence(candidate_id: int, chain: str) -> dict:
    """构造 locator 唯一、科学语义相同但 candidate_id 可重排的 occurrence。"""
    return {
        "pdb_id": "1abc",
        "candidate_id": candidate_id,
        "components": [{
            "auth_asym_id": chain,
            "auth_seq_id": 1,
            "ccd_id": "LIG",
            "icode": "",
            "index": 1,
            "label_asym_id": chain,
            "label_seq_id": 1,
        }],
        "inter_bonds": [],
        "is_covalent": False,
        "kind": "CCD",
        "n_heavy_atoms": 1,
        "object_key": "CCD:LIG",
        "polymer_length": 1,
        "type_tag": "small_molecule",
    }


def _coords(values_by_candidate: dict[int, float]) -> dict[str, np.ndarray]:
    """按 candidate_id 构造单原子 coords/present/centroid 数组。"""
    arrays: dict[str, np.ndarray] = {}
    for candidate_id, value in values_by_candidate.items():
        coordinate = np.asarray([[value, 0.0, 0.0]], dtype=np.float32)
        arrays[f"coords_{candidate_id}"] = coordinate
        arrays[f"present_{candidate_id}"] = np.asarray([True], dtype=bool)
        arrays[f"centroid_atom_{candidate_id}"] = coordinate[0].copy()
    return arrays


def test_primary_key_manifest_accepts_addition_and_reassignment():
    """匹配 occurrence 坐标逐位不变时允许新增与 snapshot 内 candidate_id 重排。"""
    old = [_occurrence(0, "A"), _occurrence(1, "B")]
    current = [_occurrence(0, "B"), _occurrence(1, "A"), _occurrence(2, "C")]

    rows, counts = build_primary_key_migration(
        "1abc",
        old,
        _coords({0: 1.0, 1: 2.0}),
        current,
        _coords({0: 2.0, 1: 1.0, 2: 3.0}),
    )

    assert counts == {"unchanged": 0, "reassigned": 2, "added": 1, "removed": 0}
    assert {row["status"] for row in rows} == {"reassigned", "added"}
    assert all("stable_occurrence_id" not in row for row in rows)


def test_primary_key_manifest_rejects_matched_coordinate_drift():
    """locator 相同但 coords/present/centroid 任一变化都必须阻断 full rebuild。"""
    old = [_occurrence(0, "A")]
    current = [_occurrence(0, "A")]

    with pytest.raises(SourceRebuildError, match="coords changed"):
        build_primary_key_migration(
            "1abc",
            old,
            _coords({0: 1.0}),
            current,
            _coords({0: 9.0}),
        )


def test_full_rebuild_transaction_is_idempotent(monkeypatch, tmp_path):
    """四件套先完整 backup，再提交；重复 apply 只验证 receipt，不重复改变结果。"""
    root, evidence, record = _transaction_fixture(tmp_path)
    monkeypatch.setattr(
        "c_source_rebuild.verify_audit_inputs_unchanged",
        lambda *_args, **_kwargs: None,
    )

    first = apply_prepared_source_rebuilds(root, evidence, [record])
    second = apply_prepared_source_rebuilds(root, evidence, [record])

    assert first[0]["action"] == "committed"
    assert second[0]["action"] == "already_committed"
    assert _hashes(canonical_stage_c_paths(root, "1abc")) == record[
        "staged_artifact_sha256"
    ]


def test_prepare_full_rebuild_stages_evidence_without_canonical_write(
    monkeypatch,
    tmp_path,
):
    """专用 audit/prepare 只写 run-scoped staging，并产出主键迁移计数。"""
    root = tmp_path / "root"
    evidence = root / "reports" / "runs" / "repair" / "stage_c_source_rebuild"
    canonical = canonical_stage_c_paths(root, "1abc")
    old_occurrences = [_occurrence(0, "A")]
    write_jsonl(canonical["occurrences"], old_occurrences)
    atomic_save_npz(canonical["ligand_coords"], **_coords({0: 1.0}))
    receptor = _receptor_arrays()
    receptor["custom_provenance"] = np.asarray("keep-me")
    atomic_save_npz(canonical["receptor"], **receptor)
    write_report(
        canonical["report"],
        {"pdb_id": "1abc", "status": "ok", "failed_occurrences": [{"candidate_id": 1}]},
    )
    descriptor = root / "ligand_descriptors" / "CCD_LIG.npz"
    atomic_save_npz(descriptor, marker=np.asarray(1, dtype=np.int8))

    current_occurrences = [_occurrence(0, "A"), _occurrence(1, "B")]
    current_coords = _coords({0: 1.0, 1: 2.0})
    view = StageCSourceView(
        occurrences=current_occurrences,
        ligand_coords=current_coords,
        receptor_atoms=[],
        receptor_base={key: receptor[key] for key in (
            "coords", "element", "res_type", "is_backbone", "atom_name", "res_index", "chain_index"
        )},
        struct_conns=[],
        ccd_ids=(),
        object_keys=("CCD:LIG",),
        report={"pdb_id": "1abc", "status": "ok", "failed_occurrences": []},
    )
    base_audit = {
        "pdb_id": "1abc",
        "classification": "blocked",
        "reasons": [
            "failed_occurrences_changed",
            "ligand_coords_keys_changed",
            "occurrences_changed",
        ],
        "receptor_mismatch_reasons": [],
        "receptor_derived_mismatch_reasons": [],
    }
    monkeypatch.setattr("c_source_rebuild.audit_stage_c_source", lambda *_args: base_audit)
    monkeypatch.setattr(
        "c_source_rebuild.build_stage_c_source_view",
        lambda *_args, **_kwargs: view,
    )
    monkeypatch.setattr(
        "c_source_rebuild.build_receptor_arrays",
        lambda *_args, **_kwargs: {
            key: value
            for key, value in receptor.items()
            if key != "custom_provenance"
        },
    )
    monkeypatch.setattr(
        "c_source_rebuild.validate_stage_c_payload",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "c_source_rebuild.verify_audit_inputs_unchanged",
        lambda *_args, **_kwargs: None,
    )
    before_hashes = _hashes(canonical)

    record, rows = prepare_stage_c_source_rebuild(root, "1abc", evidence)

    assert record["classification"] == "full_rebuild_ready"
    assert record["migration_counts"] == {
        "unchanged": 1,
        "reassigned": 0,
        "added": 1,
        "removed": 0,
    }
    assert {row["status"] for row in rows} == {"unchanged", "added"}
    assert _hashes(canonical) == before_hashes
    assert all(path.is_file() for path in staged_artifact_paths(evidence, "1abc").values())
    assert record["staged_artifact_sha256"]["receptor"] == record[
        "before_artifact_sha256"
    ]["receptor"]
    with np.load(staged_artifact_paths(evidence, "1abc")["receptor"]) as staged_receptor:
        assert staged_receptor["custom_provenance"].item() == "keep-me"


def test_full_rebuild_commit_failure_rolls_back_all_four_files(
    monkeypatch,
    tmp_path,
):
    """提交中途异常必须用完整 before backup 恢复，不能留下 mixed 四件套。"""
    root, evidence, record = _transaction_fixture(tmp_path)
    monkeypatch.setattr(
        "c_source_rebuild.verify_audit_inputs_unchanged",
        lambda *_args, **_kwargs: None,
    )
    original_copy = c_source_rebuild._atomic_copy
    failed_once = False

    def _fail_second_stage_copy(source: Path, target: Path):
        nonlocal failed_once
        if "staging" in source.parts and target.name == "ligand_coords.npz" and not failed_once:
            failed_once = True
            raise OSError("injected commit failure")
        original_copy(source, target)

    monkeypatch.setattr("c_source_rebuild._atomic_copy", _fail_second_stage_copy)

    with pytest.raises(OSError, match="injected commit failure"):
        apply_prepared_source_rebuilds(root, evidence, [record])

    assert _hashes(canonical_stage_c_paths(root, "1abc")) == record[
        "before_artifact_sha256"
    ]
    transaction = json.loads(
        (evidence / "transactions" / "1abc.json").read_text(encoding="utf-8")
    )
    assert transaction["state"] == "rolled_back"


def test_full_rebuild_recovers_after_files_promoted_before_receipt(
    monkeypatch,
    tmp_path,
):
    """kill 发生在四文件全 after、receipt 仍 committing 时可只补 durable receipt。"""
    root, evidence, record = _transaction_fixture(tmp_path)
    monkeypatch.setattr(
        "c_source_rebuild.verify_audit_inputs_unchanged",
        lambda *_args, **_kwargs: None,
    )
    c_source_rebuild._ensure_before_backup(root, evidence, record)
    c_source_rebuild._write_transaction(evidence, record, "committing")
    canonical = canonical_stage_c_paths(root, "1abc")
    stage = staged_artifact_paths(evidence, "1abc")
    for key in canonical:
        c_source_rebuild._atomic_copy(stage[key], canonical[key])

    results = apply_prepared_source_rebuilds(root, evidence, [record])

    assert results[0]["action"] == "committed_after_receipt_recovery"
    transaction = json.loads(
        (evidence / "transactions" / "1abc.json").read_text(encoding="utf-8")
    )
    assert transaction["state"] == "committed"


def _transaction_fixture(tmp_path: Path) -> tuple[Path, Path, dict]:
    """构造无需解析真实 mmCIF 的 canonical/staging/record 事务 fixture。"""
    root = tmp_path / "root"
    evidence = root / "reports" / "runs" / "repair" / "stage_c_source_rebuild"
    canonical = canonical_stage_c_paths(root, "1abc")
    stage = staged_artifact_paths(evidence, "1abc")
    for index, path in enumerate(canonical.values()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"before-{index}".encode("ascii"))
    for index, path in enumerate(stage.values()):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"after-{index}".encode("ascii"))
    mmcif = root / "raw" / "rcsb_mmcif" / "1abc.cif"
    mmcif.parent.mkdir(parents=True)
    mmcif.write_text("data_1abc\n", encoding="utf-8")
    empty_manifest_hash = hashlib.sha256(b"{}").hexdigest()
    record = {
        "pdb_id": "1abc",
        "classification": "full_rebuild_ready",
        "base_audit": {
            "pdb_id": "1abc",
            "mmcif_sha256": sha256_file(mmcif),
            "dependency_files": {},
        },
        "before_artifact_sha256": _hashes(canonical),
        "staged_artifact_sha256": _hashes(stage),
        "descriptor_files": {},
        "descriptor_manifest_sha256": empty_manifest_hash,
    }
    return root, evidence, record


def _hashes(paths: dict[str, Path]) -> dict[str, str]:
    """计算测试四件套逐文件哈希。"""
    return {key: sha256_file(path) for key, path in paths.items()}


def _receptor_arrays() -> dict[str, np.ndarray]:
    """构造新版 Stage C 所需的完整单原子 receptor 数组。"""
    return {
        "coords": np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32),
        "element": np.asarray([6], dtype=np.uint8),
        "res_type": np.asarray([0], dtype=np.uint8),
        "is_backbone": np.asarray([True], dtype=bool),
        "atom_name": np.asarray([b"CA"], dtype="S4"),
        "res_index": np.asarray([0], dtype=np.int32),
        "chain_index": np.asarray([0], dtype=np.int32),
        "bond_index": np.empty((2, 0), dtype=np.int32),
        "bond_type": np.empty((0,), dtype=np.uint8),
        "feat": np.zeros((1, 49), dtype=np.float32),
    }
