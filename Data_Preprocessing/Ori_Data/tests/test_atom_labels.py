"""Stage D 原子标签与运行失败分类测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from atom_labels import ATOM_LABEL_SCHEMA_VERSION, atom_label_errors, compute_atom_labels
from failures import KnownFailureCode, KnownSampleFailure
from parallel import filter_pair_records, read_pdb_id_filter
from reports import StageStatus, failure_stage_result, resolve_run_id, stage_report_path


def test_compute_atom_labels_shapes_threshold_and_background() -> None:
    """最近距离、4 Å 标签和背景 ``-1`` 必须使用同一阈值关系。"""
    receptor = np.asarray([[0, 0, 0], [5, 0, 0], [20, 0, 0]], dtype=np.float32)
    ligands = {
        3: np.asarray([[1, 0, 0]], dtype=np.float32),
        8: np.asarray([[9, 0, 0]], dtype=np.float32),
    }
    arrays = compute_atom_labels(receptor, ligands, 4.0)
    np.testing.assert_allclose(arrays["nearest_dist"], [1.0, 4.0, 11.0])
    np.testing.assert_array_equal(arrays["binding_atom"], [True, True, False])
    np.testing.assert_array_equal(arrays["instance_id"], [3, 3, -1])
    assert arrays["binding_atom"].dtype == np.dtype(bool)
    assert arrays["instance_id"].dtype == np.int32
    assert arrays["nearest_dist"].dtype == np.float32


def test_compute_atom_labels_resolves_exact_tie_by_candidate_id() -> None:
    """等距 occurrence 不依赖 KD-tree 内部顺序，较小 candidate_id 获胜。"""
    receptor = np.asarray([[0, 0, 0]], dtype=np.float32)
    ligands = {
        9: np.asarray([[1, 0, 0]], dtype=np.float32),
        2: np.asarray([[-1, 0, 0]], dtype=np.float32),
    }
    arrays = compute_atom_labels(receptor, ligands, 4.0)
    assert arrays["instance_id"].tolist() == [2]


def test_compute_atom_labels_classifies_no_present_atoms() -> None:
    """无 present ligand atom 是明确样本失败，不是程序未知错误。"""
    receptor = np.asarray([[0, 0, 0]], dtype=np.float32)
    try:
        compute_atom_labels(receptor, {0: np.empty((0, 3), dtype=np.float32)}, 4.0)
    except KnownSampleFailure as exc:
        assert exc.code is KnownFailureCode.NO_PRESENT_LIGAND_ATOMS
    else:
        raise AssertionError("expected KnownSampleFailure")


def test_atom_label_validator_checks_provenance_and_relations() -> None:
    """artifact 完成判据必须包含阈值、输入 hash 和值间关系。"""
    arrays = {
        "binding_atom": np.asarray([True, False]),
        "instance_id": np.asarray([4, -1], dtype=np.int32),
        "nearest_dist": np.asarray([2.0, 5.0], dtype=np.float32),
        "binding_threshold": np.asarray(4.0, dtype=np.float32),
        "schema_version": np.asarray(ATOM_LABEL_SCHEMA_VERSION, dtype=np.uint16),
        "source_receptor_sha256": np.asarray("a" * 64),
        "source_ligand_coords_sha256": np.asarray("b" * 64),
    }
    assert atom_label_errors(
        arrays,
        n_receptor_atoms=2,
        candidate_ids={4},
        binding_threshold=4.0,
        source_receptor_sha256="a" * 64,
        source_ligand_coords_sha256="b" * 64,
    ) == []
    arrays["instance_id"][1] = 4
    errors = atom_label_errors(
        arrays,
        n_receptor_atoms=2,
        candidate_ids={4},
        binding_threshold=4.0,
        source_receptor_sha256="a" * 64,
        source_ligand_coords_sha256="b" * 64,
    )
    assert "atom_labels_value:background_instance" in errors


def test_run_scoped_report_path_and_failure_classification(tmp_path: Path) -> None:
    """本轮状态文件路径隔离历史，普通异常保持 unknown_failed。"""
    assert resolve_run_id("run_20260710") == "run_20260710"
    path = stage_report_path(tmp_path, "run_20260710", "stage_d", 2, 5)
    assert path == (
        tmp_path
        / "reports"
        / "runs"
        / "run_20260710"
        / "stage_d"
        / "status.part_0002_of_0005.jsonl"
    )
    known = failure_stage_result(
        "7ABC",
        "stage_d",
        KnownSampleFailure(KnownFailureCode.NO_OCCURRENCES, "none"),
    )
    unknown = failure_stage_result("7ABC", "stage_d", ValueError("bug"))
    assert known["status"] == StageStatus.KNOWN_FAILED.value
    assert known["reason"] == KnownFailureCode.NO_OCCURRENCES.value
    assert unknown["status"] == StageStatus.UNKNOWN_FAILED.value


def test_pdb_id_filter_is_explicit_stable_and_rejects_missing_ids(tmp_path: Path) -> None:
    """真实 smoke/repair 只能处理显式子集，不能静默忽略不存在的 id。"""
    path = tmp_path / "ids.txt"
    path.write_text("# smoke\n2BBB\n\n1aaa\n2bbb\n", encoding="utf-8")
    ids = read_pdb_id_filter(path)
    records = [{"pdb_id": "1aaa"}, {"pdb_id": "2bbb"}, {"pdb_id": "3ccc"}]
    assert ids == {"1aaa", "2bbb"}
    assert [item["pdb_id"] for item in filter_pair_records(records, ids)] == ["1aaa", "2bbb"]
    try:
        filter_pair_records(records, {"9zzz"})
    except ValueError as exc:
        assert "absent from pair_list" in str(exc)
    else:
        raise AssertionError("missing id must fail")
