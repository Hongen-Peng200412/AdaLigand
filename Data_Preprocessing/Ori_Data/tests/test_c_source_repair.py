"""Stage C source-dirty 两阶段 audit/apply 契约测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"

from adaligand_preprocessing.ops.stage_c_repair import (
    SourceRepairError,
    _atom_name_derived_delta_reasons,
    apply_receptor_source_repair,
    audit_stage_c_source,
    verify_audit_inputs_unchanged,
)
from adaligand_preprocessing.utils.io import atomic_save_npz, read_jsonl, sha256_file, write_jsonl
from adaligand_preprocessing.stages.stage_c.pipeline import StageCSourceView
from adaligand_preprocessing.artifacts.reports import write_report


def _base_arrays(atom_name: bytes) -> dict[str, np.ndarray]:
    """构造一个单受体原子的七项基础数组。"""
    return {
        "coords": np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32),
        "element": np.asarray([6], dtype=np.uint8),
        "res_type": np.asarray([0], dtype=np.uint8),
        "is_backbone": np.asarray([True], dtype=bool),
        "atom_name": np.asarray([atom_name], dtype="S4"),
        "res_index": np.asarray([0], dtype=np.int32),
        "chain_index": np.asarray([0], dtype=np.int32),
    }


def _write_fixture(root: Path) -> tuple[list[dict], dict[str, np.ndarray]]:
    """写入 audit 所需的旧 C 四件套与诊断报告。"""
    occurrences = [{"pdb_id": "1abc", "candidate_id": 0, "object_key": "CCD:LIG"}]
    ligand_coords = {
        "coords_0": np.asarray([[1.0, 2.0, 3.0]], dtype=np.float32),
        "present_0": np.asarray([True], dtype=bool),
    }
    parse_dir = root / "parse" / "1abc"
    write_jsonl(parse_dir / "occurrences.jsonl", occurrences)
    atomic_save_npz(
        parse_dir / "ligand_coords.npz",
        **ligand_coords,
        centroid_atom_0=np.asarray([1.0, 2.0, 3.0], dtype=np.float32),
    )
    receptor = _base_arrays(b"CA")
    receptor.update({
        "bond_index": np.empty((2, 0), dtype=np.int32),
        "bond_type": np.empty((0,), dtype=np.uint8),
        "feat": np.zeros((1, 49), dtype=np.float32),
        "custom_provenance": np.asarray("keep-me"),
    })
    atomic_save_npz(parse_dir / "receptor_tokens.npz", **receptor)
    (root / "raw" / "rcsb_mmcif").mkdir(parents=True, exist_ok=True)
    (root / "raw" / "rcsb_mmcif" / "1abc.cif").write_text("data_1abc\n", encoding="utf-8")
    write_report(
        root / "reports" / "1abc.json",
        {"pdb_id": "1abc", "failed_occurrences": [], "counts": {}},
    )
    atomic_save_npz(
        root / "ligand_objects" / "CCD_LIG.npz",
        marker=np.asarray(1, dtype=np.int8),
    )
    return occurrences, ligand_coords


def _source_view(
    occurrences: list[dict],
    ligand_coords: dict[str, np.ndarray],
    atom_name: bytes,
) -> StageCSourceView:
    """构造 monkeypatch 后的当前 mmCIF dry-build 视图。"""
    return StageCSourceView(
        occurrences=occurrences,
        ligand_coords={
            **ligand_coords,
            "centroid_atom_0": np.asarray([1.0, 2.0, 3.0], dtype=np.float32),
        },
        receptor_atoms=[{
            "label_atom_id": atom_name.decode("ascii"),
            "label_asym_id": "A",
            "label_comp_id": "F86",
            "label_seq_id": "1",
            "auth_seq_id": "1",
            "icode": "",
        }],
        receptor_base=_base_arrays(atom_name),
        struct_conns=[],
        ccd_ids=(),
        object_keys=("CCD:LIG",),
        report={"failed_occurrences": [], "counts": {}},
    )


def _patch_receptor_builder(
    monkeypatch,
    view: StageCSourceView,
    *,
    feat_value: float = 0.0,
) -> dict[str, np.ndarray]:
    """隔离单元测试中的 CCD 解析，同时保留完整 receptor 派生契约。"""
    rebuilt = dict(view.receptor_base)
    rebuilt.update({
        "bond_index": np.empty((2, 0), dtype=np.int32),
        "bond_type": np.empty((0,), dtype=np.uint8),
        "feat": np.full((1, 49), feat_value, dtype=np.float32),
    })
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_repair.build_receptor_arrays",
        lambda *_args, **_kwargs: rebuilt,
    )
    return rebuilt


def test_atom_name_only_audit_and_apply_preserve_ligand_side(monkeypatch, tmp_path):
    """严格 atom-name-only 样本只原子替换 receptor，配体侧哈希保持不变。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    view = _source_view(occurrences, ligand_coords, b"CB")
    monkeypatch.setattr("adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view", lambda *_args, **_kwargs: view)
    _patch_receptor_builder(monkeypatch, view)
    occurrence_path = tmp_path / "parse" / "1abc" / "occurrences.jsonl"
    coords_path = tmp_path / "parse" / "1abc" / "ligand_coords.npz"
    occurrence_hash = sha256_file(occurrence_path)
    coords_hash = sha256_file(coords_path)

    record = audit_stage_c_source(tmp_path, "1abc")
    result = apply_receptor_source_repair(tmp_path, record)

    assert record["classification"] == "atom_name_only"
    assert record["atom_name_diff_count"] == 1
    assert result["action"] == "repaired"
    assert sha256_file(occurrence_path) == occurrence_hash
    assert sha256_file(coords_path) == coords_hash
    with np.load(tmp_path / "parse" / "1abc" / "receptor_tokens.npz") as saved:
        assert saved["atom_name"].item() == b"CB"
        assert saved["custom_provenance"].item() == "keep-me"
        np.testing.assert_array_equal(saved["feat"], 0.0)


def test_incomplete_old_receptor_atom_name_only_audit_and_apply(
    monkeypatch,
    tmp_path,
):
    """旧派生数组不完整时，允许 atom-name-only 迁移补齐并替换全部派生数组。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    receptor_path = tmp_path / "parse" / "1abc" / "receptor_tokens.npz"
    with np.load(receptor_path, allow_pickle=False) as data:
        incomplete = {key: data[key].copy() for key in data.files}
    incomplete.pop("bond_type")
    incomplete["feat"] = np.full((1, 49), 7.0, dtype=np.float32)
    atomic_save_npz(receptor_path, **incomplete)

    view = _source_view(occurrences, ligand_coords, b"CB")
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view",
        lambda *_args, **_kwargs: view,
    )
    rebuilt = _patch_receptor_builder(monkeypatch, view, feat_value=2.0)

    record = audit_stage_c_source(tmp_path, "1abc")
    result = apply_receptor_source_repair(tmp_path, record)

    assert record["classification"] == "atom_name_only"
    assert record["reasons"] == []
    assert record["receptor_derived_delta_reasons"] == []
    assert result["action"] == "repaired"
    with np.load(receptor_path, allow_pickle=False) as saved:
        assert saved["atom_name"].item() == b"CB"
        assert saved["custom_provenance"].item() == "keep-me"
        for key in ("bond_index", "bond_type", "feat"):
            np.testing.assert_array_equal(saved[key], rebuilt[key])


def test_incomplete_old_receptor_does_not_excuse_ligand_drift(
    monkeypatch,
    tmp_path,
):
    """旧派生数组不完整不能放行 occurrence 漂移。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    receptor_path = tmp_path / "parse" / "1abc" / "receptor_tokens.npz"
    with np.load(receptor_path, allow_pickle=False) as data:
        incomplete = {key: data[key].copy() for key in data.files}
    incomplete.pop("feat")
    atomic_save_npz(receptor_path, **incomplete)

    changed_occurrences = occurrences + [
        {"pdb_id": "1abc", "candidate_id": 1, "object_key": "CCD:NEW"}
    ]
    view = _source_view(changed_occurrences, ligand_coords, b"CB")
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view",
        lambda *_args, **_kwargs: view,
    )
    _patch_receptor_builder(monkeypatch, view)

    record = audit_stage_c_source(tmp_path, "1abc")

    assert record["classification"] == "blocked"
    assert "occurrences_changed" in record["reasons"]


def test_incomplete_old_receptor_does_not_excuse_non_atom_base_drift(
    monkeypatch,
    tmp_path,
):
    """旧派生数组不完整不能放行 atom_name 之外的 receptor base 漂移。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    receptor_path = tmp_path / "parse" / "1abc" / "receptor_tokens.npz"
    with np.load(receptor_path, allow_pickle=False) as data:
        incomplete = {key: data[key].copy() for key in data.files}
    incomplete.pop("bond_index")
    atomic_save_npz(receptor_path, **incomplete)

    view = _source_view(occurrences, ligand_coords, b"CB")
    view.receptor_base["coords"][0, 0] = 1.0
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view",
        lambda *_args, **_kwargs: view,
    )
    _patch_receptor_builder(monkeypatch, view)

    record = audit_stage_c_source(tmp_path, "1abc")

    assert record["classification"] == "blocked"
    assert "receptor_base_changed:coords" in record["receptor_mismatch_reasons"]
    assert "receptor_base_changed:coords" in record["reasons"]


def test_exact_audit_ignores_derived_centroid_arrays(monkeypatch, tmp_path):
    """source audit 只比较配体核心 coords/present，不把派生质心误判为 key 漂移。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    view = _source_view(occurrences, ligand_coords, b"CA")
    monkeypatch.setattr("adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view", lambda *_args, **_kwargs: view)
    _patch_receptor_builder(monkeypatch, view)

    record = audit_stage_c_source(tmp_path, "1abc")

    assert record["classification"] == "exact"
    assert record["reasons"] == []


def test_exact_base_with_stale_receptor_derived_arrays_is_blocked(
    monkeypatch,
    tmp_path,
):
    """base 完全一致时，旧 bond/feat 仍须与当前 source 重建结果逐位一致。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    view = _source_view(occurrences, ligand_coords, b"CA")
    monkeypatch.setattr("adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view", lambda *_args, **_kwargs: view)
    _patch_receptor_builder(monkeypatch, view, feat_value=1.0)

    record = audit_stage_c_source(tmp_path, "1abc")

    assert record["classification"] == "blocked"
    assert record["receptor_mismatch_reasons"] == []
    assert record["receptor_derived_mismatch_reasons"] == [
        "receptor_derived_changed:feat"
    ]


def test_ligand_occurrence_drift_is_blocked_without_receptor_write(monkeypatch, tmp_path):
    """当前 mmCIF 若改变配体 occurrence，audit 必须 blocked 且 receptor 零写入。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    changed = occurrences + [{"pdb_id": "1abc", "candidate_id": 1, "object_key": "CCD:NEW"}]
    view = _source_view(changed, ligand_coords, b"CB")
    monkeypatch.setattr("adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view", lambda *_args, **_kwargs: view)
    _patch_receptor_builder(monkeypatch, view)
    receptor_path = tmp_path / "parse" / "1abc" / "receptor_tokens.npz"
    before = sha256_file(receptor_path)

    record = audit_stage_c_source(tmp_path, "1abc")

    assert record["classification"] == "blocked"
    assert "occurrences_changed" in record["reasons"]
    assert sha256_file(receptor_path) == before


def test_apply_rejects_toctou_after_audit(monkeypatch, tmp_path):
    """audit 后任一配体输入变化都必须在全局 preflight 阶段阻断。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    view = _source_view(occurrences, ligand_coords, b"CB")
    monkeypatch.setattr("adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view", lambda *_args, **_kwargs: view)
    _patch_receptor_builder(monkeypatch, view)
    record = audit_stage_c_source(tmp_path, "1abc")
    write_jsonl(
        tmp_path / "parse" / "1abc" / "occurrences.jsonl",
        occurrences + [{"pdb_id": "1abc", "candidate_id": 9, "object_key": "CCD:X"}],
    )

    with pytest.raises(SourceRepairError, match="occurrences_sha256"):
        verify_audit_inputs_unchanged(tmp_path, record)


def test_audit_freezes_report_and_dependency_closure(monkeypatch, tmp_path):
    """分类读取的 report、LigandObject 等间接依赖也必须纳入 TOCTOU 复核。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    view = _source_view(occurrences, ligand_coords, b"CA")
    monkeypatch.setattr("adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view", lambda *_args, **_kwargs: view)
    _patch_receptor_builder(monkeypatch, view)
    record = audit_stage_c_source(tmp_path, "1abc")

    write_report(
        tmp_path / "reports" / "1abc.json",
        {"pdb_id": "1abc", "failed_occurrences": [{"candidate_id": 9}]},
    )
    with pytest.raises(SourceRepairError, match="report_sha256"):
        verify_audit_inputs_unchanged(tmp_path, record)

    write_report(
        tmp_path / "reports" / "1abc.json",
        {"pdb_id": "1abc", "failed_occurrences": [], "counts": {}},
    )
    atomic_save_npz(
        tmp_path / "ligand_objects" / "CCD_LIG.npz",
        marker=np.asarray(2, dtype=np.int8),
    )
    with pytest.raises(SourceRepairError, match="dependency_changed"):
        verify_audit_inputs_unchanged(tmp_path, record)


def test_atom_name_audit_scopes_strict_coverage_to_changed_residue(
    monkeypatch,
    tmp_path,
):
    """source audit 只把实际改名 residue 交给严格 CCD coverage。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    view = _source_view(occurrences, ligand_coords, b"CB")
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view",
        lambda *_args, **_kwargs: view,
    )
    rebuilt = dict(view.receptor_base)
    rebuilt.update({
        "bond_index": np.empty((2, 0), dtype=np.int32),
        "bond_type": np.empty((0,), dtype=np.uint8),
        "feat": np.zeros((1, 49), dtype=np.float32),
    })
    captured: list[frozenset[tuple[str, str, str, str]]] = []

    def _capture_builder(*_args, **kwargs):
        captured.append(kwargs["required_atom_name_coverage_residues"])
        return rebuilt

    monkeypatch.setattr("adaligand_preprocessing.ops.stage_c_repair.build_receptor_arrays", _capture_builder)

    record = audit_stage_c_source(tmp_path, "1abc")

    assert record["classification"] == "atom_name_only"
    assert captured == [frozenset({("A", "F86", "1", "")})]


def test_atom_name_only_audit_blocks_global_feature_drift(monkeypatch, tmp_path):
    """atom name 改变不允许顺带重写由未变 coords/element/residue 派生的全图 feat。"""
    occurrences, ligand_coords = _write_fixture(tmp_path)
    view = _source_view(occurrences, ligand_coords, b"CB")
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_repair.build_stage_c_source_view",
        lambda *_args, **_kwargs: view,
    )
    _patch_receptor_builder(monkeypatch, view, feat_value=1.0)

    record = audit_stage_c_source(tmp_path, "1abc")

    assert record["classification"] == "blocked"
    assert "receptor_derived_delta:feat_changed" in record["reasons"]


def test_atom_name_only_delta_blocks_unrelated_bond_change():
    """改名 residue 之外的受体子图 bond 差异必须阻断整份 bond 表替换。"""
    old = {
        "feat": np.zeros((3, 49), dtype=np.float32),
        "bond_index": np.asarray([[0, 1], [1, 2]], dtype=np.int32),
        "bond_type": np.asarray([0, 0], dtype=np.uint8),
    }
    rebuilt = {
        "feat": old["feat"].copy(),
        "bond_index": np.asarray([[0], [1]], dtype=np.int32),
        "bond_type": np.asarray([0], dtype=np.uint8),
    }

    reasons = _atom_name_derived_delta_reasons(old, rebuilt, frozenset({0}))

    assert len(reasons) == 1
    assert reasons[0].startswith(
        "receptor_derived_delta:unchanged_subgraph_bond_changed"
    )
