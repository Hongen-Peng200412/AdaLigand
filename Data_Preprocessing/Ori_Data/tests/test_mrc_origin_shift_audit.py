"""Pocket ``make_cubic`` origin shift 轴序影响的独立只读审计测试。"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
import sys

import mrcfile
import numpy as np
import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from io_utils import sha256_file, write_jsonl
from mrc_origin_shift_audit import (
    ORIGIN_SHIFT_AXIS_ORDER_RISK,
    analyze_origin_shift_axis_order,
    audit_one_header,
    execute_origin_shift_shard,
    finalize_origin_shift_audit,
    load_stage_e_statuses,
    pocket_loaded_origin_from_header,
)
from mrc_contract_audit import canonical_shape_zyx
from reports import stage_result


def test_exact_predicate_comes_from_zyx_to_xyz_shift_mismatch() -> None:
    """Z/X shift 不同才受影响；Y 轴奇偶不能单独触发风险。"""
    affected = analyze_origin_shift_axis_order(
        (5, 7, 8),
        (1.25, 1.5, 2.0),
        (10.0, 20.0, 30.0),
    )
    assert affected["make_cubic_shift_zyx"] == [1, 1, 0]
    assert affected["axis_consistent_shift_xyz"] == [0, 1, 1]
    assert affected["affected"] is True
    assert affected["ancestor_minus_axis_consistent_origin_xyz"] == pytest.approx(
        [-1.25, 0.0, 2.0]
    )

    y_only = analyze_origin_shift_axis_order((8, 7, 6), (1.0, 2.0, 3.0))
    both_xz = analyze_origin_shift_axis_order((5, 8, 7), (1.0, 2.0, 3.0))
    assert y_only["affected"] is False
    assert both_xz["affected"] is False
    assert both_xz["ancestor_minus_axis_consistent_origin_xyz"] == [0.0, 0.0, 0.0]


def test_7nll_header_shape_is_unambiguously_affected() -> None:
    """7nll/EMD-12465 记录的 ZYX shape 给出严格非零轴序误差。"""
    geometry = analyze_origin_shift_axis_order(
        (101, 55, 88),
        (1.01, 1.01, 1.01),
        (-10.0, -20.0, -30.0),
    )
    assert geometry["make_cubic_shift_zyx"] == [1, 1, 0]
    assert geometry["axis_consistent_shift_xyz"] == [0, 1, 1]
    assert geometry["affected"] is True
    assert geometry["ancestor_minus_axis_consistent_origin_xyz"] == pytest.approx(
        [-1.01, 0.0, 1.01]
    )


def test_7nll_real_header_snapshot_reconstructs_canonical_shape_and_origin() -> None:
    """2026-07-16 只读取证的 EMD-12465 header 经祖传轴排列后仍命中风险。"""
    canonical_shape = canonical_shape_zyx((88, 55, 101), 3, 2, 1)
    loaded_origin = pocket_loaded_origin_from_header(
        origin_xyz=(0.0, 0.0, 0.0),
        nstart_crs=(248, 279, 258),
        mapc_mapr_maps=(3, 2, 1),
        voxel_size_xyz=(1.0099999904632568,) * 3,
    )
    geometry = analyze_origin_shift_axis_order(
        canonical_shape,
        (1.0099999904632568,) * 3,
        loaded_origin,
    )
    assert canonical_shape == (101, 55, 88)
    assert loaded_origin == pytest.approx([260.58, 281.79, 250.48], abs=1e-4)
    assert geometry["affected"] is True
    assert geometry["ancestor_minus_axis_consistent_origin_xyz"] == pytest.approx(
        [-1.0099999904632568, 0.0, 1.0099999904632568]
    )


def test_pocket_loaded_origin_reproduces_axis_reordered_nstart() -> None:
    """header origin/nstart 组合严格复现 Pocket ``load_map`` 的当前语义。"""
    loaded = pocket_loaded_origin_from_header(
        origin_xyz=(2.0, 3.0, 4.0),
        nstart_crs=(10, 20, 30),
        mapc_mapr_maps=(2, 3, 1),
        voxel_size_xyz=(1.0, 2.0, 3.0),
    )
    # C→Y, R→Z, S→X，因此 start XYZ=(30,10,20)。
    assert loaded == pytest.approx([32.0, 26.0, 72.0])


def test_header_audit_is_read_only_and_joins_stage_e(tmp_path: Path) -> None:
    """单图审计只读 header，并保留所有引用 PDB 的 Stage E 终态。"""
    map_path = _write_gzip_map(
        tmp_path / "emd_2.map.gz",
        shape_zyx=(5, 4, 6),
        voxel_xyz=(1.0, 2.0, 3.0),
        origin_xyz=(2.0, 3.0, 4.0),
        nstart_crs=(10, 20, 30),
    )
    before_sha = sha256_file(map_path)
    statuses = {
        "1aaa": stage_result("1aaa", "stage_e", "success"),
        "1bbb": stage_result(
            "1bbb", "stage_e", "known_failed", reason="fixture"
        ),
    }
    record = audit_one_header(map_path, "EMD-2", ["1aaa", "1bbb"], statuses)

    assert record["risk_codes"] == [ORIGIN_SHIFT_AXIS_ORDER_RISK]
    assert record["geometry"]["loaded_origin_xyz"] == pytest.approx(
        [12.0, 46.0, 102.0]
    )
    assert record["stage_e_status_counts"] == {"known_failed": 1, "success": 1}
    assert record["stage_e"][0]["eligible"] is True
    assert record["stage_e"][1]["eligible"] is False
    assert sha256_file(map_path) == before_sha


def test_sharded_audit_finalizes_sorted_lists_and_frozen_stage_e_join(
    tmp_path: Path,
) -> None:
    """两分片合并后输出数字排序 EMDB、字典序 PDB 及各自 SHA。"""
    root = tmp_path / "dataset"
    map_dir = root / "raw" / "emdb_maps"
    map_dir.mkdir(parents=True)
    affected_map = _write_gzip_map(
        map_dir / "emd_2.map.gz",
        shape_zyx=(5, 4, 6),
    )
    unaffected_map = _write_gzip_map(
        map_dir / "emd_10.map.gz",
        shape_zyx=(5, 4, 7),
    )
    map_hashes_before = {
        path.name: sha256_file(path) for path in (affected_map, unaffected_map)
    }
    pair_list = root / "raw" / "pair_list.jsonl"
    write_jsonl(
        pair_list,
        [
            {"pdb_id": "1bbc", "emdb_id": "EMD-2"},
            {"pdb_id": "1aaa", "emdb_id": "EMD-10"},
            {"pdb_id": "1bbb", "emdb_id": "EMD-2"},
        ],
    )
    stage_dir = root / "reports" / "runs" / "formal" / "stage_e"
    write_jsonl(
        stage_dir / "status.part_0000_of_0001.jsonl",
        [
            stage_result("1aaa", "stage_e", "success"),
            stage_result("1bbb", "stage_e", "skipped"),
            stage_result(
                "1bbc",
                "stage_e",
                "known_failed",
                reason="fixture_known",
            )
        ],
    )
    stage_e_status_sha256 = sha256_file(
        stage_dir / "status.part_0000_of_0001.jsonl"
    )
    implementation = {
        "files": {"fixture": {"sha256": "a" * 64, "size_bytes": 1}},
        "sha256": "b" * 64,
    }
    for part_id in range(2):
        execute_origin_shift_shard(
            root=root,
            pair_list_path=pair_list,
            source_run_id="formal",
            audit_run_id="origin_audit",
            expected_stage_e_status_sha256=stage_e_status_sha256,
            part_id=part_id,
            total_parts=2,
            n_jobs=1,
            implementation=implementation,
            dependency_versions={"python": "test"},
        )

    summary_path, summary = finalize_origin_shift_audit(
        root=root,
        pair_list_path=pair_list,
        source_run_id="formal",
        audit_run_id="origin_audit",
        total_parts=2,
        expected_stage_e_status_sha256=stage_e_status_sha256,
        implementation=implementation,
    )
    report_dir = summary_path.parent
    assert summary["status"] == "completed_axis_order_risk_candidates"
    assert summary["affected_emdb_count"] == 1
    assert summary["affected_pdb_count"] == 2
    assert summary["affected_stage_e_eligible_pdb_count"] == 1
    assert (report_dir / "affected_emdb_ids.txt").read_text(encoding="utf-8") == (
        "EMD-2\n"
    )
    assert (report_dir / "affected_pdb_ids.all.txt").read_text(encoding="utf-8") == (
        "1bbb\n1bbc\n"
    )
    assert (
        report_dir / "affected_pdb_ids.stage_e_eligible.txt"
    ).read_text(encoding="utf-8") == "1bbb\n"
    joined = _read_jsonl(report_dir / "affected_pairs.stage_e_join.jsonl")
    assert [record["pdb_id"] for record in joined] == ["1bbb", "1bbc"]
    assert [record["stage_e_status"] for record in joined] == [
        "skipped",
        "known_failed",
    ]
    for key in (
        "affected_emdb_ids",
        "affected_pdb_ids_all",
        "affected_pdb_ids_stage_e_eligible",
        "affected_pairs_stage_e_join",
    ):
        identity = summary[key]
        assert identity["sha256"] == sha256_file(Path(identity["path"]))
    assert {
        path.name: sha256_file(path) for path in (affected_map, unaffected_map)
    } == map_hashes_before

    part_zero_summary = report_dir / "summary.part_0000_of_0002.json"
    original_part_zero = part_zero_summary.read_bytes()
    tampered = json.loads(original_part_zero.decode("utf-8"))
    tampered["observed_emdb_count"] = 0
    part_zero_summary.write_text(
        json.dumps(tampered, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="observed_emdb_count"):
        finalize_origin_shift_audit(
            root=root,
            pair_list_path=pair_list,
            source_run_id="formal",
            audit_run_id="origin_audit",
            total_parts=2,
            expected_stage_e_status_sha256=stage_e_status_sha256,
            implementation=implementation,
        )
    part_zero_summary.write_bytes(original_part_zero)

    part_one_summary = report_dir / "summary.part_0001_of_0002.json"
    original_part_one = part_one_summary.read_bytes()
    dependency_drift = json.loads(original_part_one.decode("utf-8"))
    dependency_drift["dependency_versions"] = {"python": "different"}
    part_one_summary.write_text(
        json.dumps(dependency_drift, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="dependency versions changed"):
        finalize_origin_shift_audit(
            root=root,
            pair_list_path=pair_list,
            source_run_id="formal",
            audit_run_id="origin_audit",
            total_parts=2,
            expected_stage_e_status_sha256=stage_e_status_sha256,
            implementation=implementation,
        )
    part_one_summary.write_bytes(original_part_one)


def test_stage_e_join_rejects_silent_missing_status(tmp_path: Path) -> None:
    """Stage E 缺样不得被只读影响审计静默跳过。"""
    stage_dir = tmp_path / "stage_e"
    write_jsonl(
        stage_dir / "status.part_0000_of_0001.jsonl",
        [stage_result("1aaa", "stage_e", "success")],
    )
    with pytest.raises(RuntimeError, match="universe drift"):
        load_stage_e_statuses(stage_dir, {"1aaa", "1bbb"})


def test_header_failure_lists_stage_e_eligible_gap(tmp_path: Path) -> None:
    """header 失败必须显式列出关联的 Stage E 合格 PDB，不得宣称全覆盖。"""
    root = tmp_path / "dataset"
    pair_list = root / "raw" / "pair_list.jsonl"
    write_jsonl(pair_list, [{"pdb_id": "1aaa", "emdb_id": "EMD-99"}])
    status_path = (
        root
        / "reports"
        / "runs"
        / "formal"
        / "stage_e"
        / "status.part_0000_of_0001.jsonl"
    )
    write_jsonl(status_path, [stage_result("1aaa", "stage_e", "success")])
    implementation = {"files": {}, "sha256": "b" * 64}
    execute_origin_shift_shard(
        root=root,
        pair_list_path=pair_list,
        source_run_id="formal",
        audit_run_id="origin_audit",
        expected_stage_e_status_sha256=sha256_file(status_path),
        part_id=0,
        total_parts=1,
        n_jobs=1,
        implementation=implementation,
        dependency_versions={"python": "test"},
    )
    summary_path, summary = finalize_origin_shift_audit(
        root=root,
        pair_list_path=pair_list,
        source_run_id="formal",
        audit_run_id="origin_audit",
        total_parts=1,
        expected_stage_e_status_sha256=sha256_file(status_path),
        implementation=implementation,
    )
    assert summary["status"] == "incomplete_header_failures"
    assert summary["header_failure_stage_e_eligible_pdb_count"] == 1
    assert summary["header_failure_stage_e_eligible_pdb_ids"] == ["1aaa"]
    gap_file = summary_path.parent / "header_failed_pdb_ids.stage_e_eligible.txt"
    assert gap_file.read_text(encoding="utf-8") == "1aaa\n"
    assert summary["header_failure_stage_e_eligible_pdb_ids_file"][
        "sha256"
    ] == sha256_file(gap_file)


def _write_gzip_map(
    target: Path,
    *,
    shape_zyx: tuple[int, int, int],
    voxel_xyz: tuple[float, float, float] = (1.0, 1.0, 1.0),
    origin_xyz: tuple[float, float, float] = (0.0, 0.0, 0.0),
    nstart_crs: tuple[int, int, int] = (0, 0, 0),
) -> Path:
    """写一张小型真实 MRC.gz fixture。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    plain = target.with_suffix("")
    with mrcfile.new(str(plain), overwrite=True) as handle:
        handle.set_data(np.zeros(shape_zyx, dtype=np.float32))
        handle.voxel_size = voxel_xyz
        handle.header.origin = origin_xyz
        handle.header.nxstart = nstart_crs[0]
        handle.header.nystart = nstart_crs[1]
        handle.header.nzstart = nstart_crs[2]
    with plain.open("rb") as source, target.open("wb") as raw_target:
        with gzip.GzipFile(fileobj=raw_target, mode="wb", mtime=0) as compressed:
            compressed.write(source.read())
    plain.unlink()
    return target


def _read_jsonl(path: Path) -> list[dict]:
    """读取测试生成的 JSONL。"""
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
