"""Pocket Plus 祖传 MRC header 审计的纯函数与只读集成测试。"""

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

from mrc_contract_audit import (
    EFFECTIVE_CLOSURE_RISK,
    MIXED_EQUALITY_RISK,
    EmdbAuditInput,
    analyze_resample_geometry,
    audit_mrc_header,
    canonical_shape_zyx,
    collect_unique_emdb_inputs,
    execute_header_audit,
    numeric_distribution,
    shard_emdb_inputs,
)


def test_numeric_distribution_is_json_safe_and_counts_scale_direction() -> None:
    """contour scale 分布必须保留相对 1 的方向，并让空输入只产生 null。"""
    summary = numeric_distribution([0.25, 0.5, 1.0, 2.0])
    assert summary["count"] == 4
    assert summary["less_than_one_count"] == 2
    assert summary["equal_to_one_count"] == 1
    assert summary["greater_than_one_count"] == 1
    assert summary["min"] == 0.25
    assert summary["median"] == 0.75
    assert summary["max"] == 2.0

    empty = numeric_distribution([])
    assert empty["count"] == 0
    assert empty["median"] is None


def test_all_equal_geometry_keeps_shape_and_unit_ratio() -> None:
    """三个轴均不变化时不调用 rescale，shape、voxel 和幅值比例均保持不变。"""
    geometry = analyze_resample_geometry((10, 12, 14), (1.0, 1.0, 1.0), 1.0)

    assert geometry.axis_relation == "all_equal"
    assert geometry.ancestor_rescale_executed is False
    assert geometry.mixed_equality_risk is False
    assert geometry.even_input_shape_zyx == (10, 12, 14)
    assert geometry.intended_output_shape_zyx == (10, 12, 14)
    assert geometry.effective_output_shape_zyx == (10, 12, 14)
    assert geometry.normal_rescale_amplitude_ratio == 1.0
    assert geometry.intended_physical_closure is True
    assert geometry.effective_physical_closure is True


def test_all_diff_geometry_rescales_and_reports_volume_ratio() -> None:
    """三个轴均变化时进入正常 Fourier 路径，并报告 ``prod(in)/prod(out)``。"""
    geometry = analyze_resample_geometry((10, 12, 14), (2.0, 2.0, 2.0), 1.0)

    assert geometry.axis_relation == "all_diff"
    assert geometry.ancestor_rescale_executed is True
    assert geometry.intended_output_shape_zyx == (20, 24, 28)
    assert geometry.effective_output_shape_zyx == (20, 24, 28)
    assert geometry.actual_voxel_size_xyz == pytest.approx((1.0, 1.0, 1.0))
    assert geometry.normal_rescale_amplitude_ratio == pytest.approx(1.0 / 8.0)
    assert geometry.intended_physical_closure is True
    assert geometry.effective_physical_closure is True


def test_mixed_equality_identifies_whole_rescale_skip_and_broken_effective_closure() -> None:
    """任一轴相等且任一轴变化时，祖传 ``np.all`` 条件会整体跳过。"""
    geometry = analyze_resample_geometry((10, 12, 14), (1.0, 2.0, 1.0), 1.0)

    assert geometry.axis_relation == "mixed_equality"
    assert geometry.ancestor_rescale_executed is False
    assert geometry.mixed_equality_risk is True
    assert geometry.intended_output_shape_zyx == (10, 24, 14)
    assert geometry.effective_output_shape_zyx == (10, 12, 14)
    assert geometry.normal_rescale_amplitude_ratio == pytest.approx(0.5)
    assert geometry.intended_physical_closure is True
    assert geometry.effective_physical_closure is False
    assert geometry.effective_closure_max_abs_angstrom == pytest.approx(12.0)


@pytest.mark.parametrize(
    ("mapc", "mapr", "maps"),
    [
        (1, 2, 3),
        (1, 3, 2),
        (2, 1, 3),
        (2, 3, 1),
        (3, 1, 2),
        (3, 2, 1),
    ],
)
def test_canonical_shape_supports_all_six_axis_permutations(
    mapc: int,
    mapr: int,
    maps: int,
) -> None:
    """六种合法 C/R/S 排列都恢复同一个物理 ZYX shape。"""
    shape_xyz = np.asarray((11, 22, 33), dtype=np.int64)
    storage_c = int(shape_xyz[mapc - 1])
    storage_r = int(shape_xyz[mapr - 1])
    storage_s = int(shape_xyz[maps - 1])

    assert canonical_shape_zyx(
        (storage_s, storage_r, storage_c),
        mapc,
        mapr,
        maps,
    ) == (33, 22, 11)


def test_odd_input_shape_is_padded_before_output_and_ratio_calculation() -> None:
    """幅值比例使用 ``make_cubic`` 后的偶数输入，而非原始奇数 shape。"""
    geometry = analyze_resample_geometry((9, 11, 13), (2.0, 2.0, 2.0), 1.0)

    assert geometry.even_input_shape_zyx == (10, 12, 14)
    assert geometry.intended_output_shape_zyx == (20, 24, 28)
    assert geometry.normal_rescale_amplitude_ratio == pytest.approx(1.0 / 8.0)


def test_unique_emdb_collection_counts_reused_maps() -> None:
    """多个 PDB 引用同一 EMDB 时只审计一次，并保留引用数。"""
    inputs = collect_unique_emdb_inputs(
        [
            {"pdb_id": "1abc", "emdb_id": "EMD-43"},
            {"pdb_id": "2abc", "emdb_id": "emd-43"},
            {"pdb_id": "3abc", "emdb_id": "EMD-100"},
        ]
    )

    assert inputs == [
        EmdbAuditInput(emdb_id="EMD-43", pair_count=2),
        EmdbAuditInput(emdb_id="EMD-100", pair_count=1),
    ]


def test_sharding_is_disjoint_and_reconstructs_stable_input_order() -> None:
    """取模分片互不重叠，按原下标交错即可重建稳定唯一 EMDB 清单。"""
    inputs = [EmdbAuditInput(emdb_id=f"EMD-{index}", pair_count=1) for index in range(7)]
    shards = [shard_emdb_inputs(inputs, part_id, 3) for part_id in range(3)]

    flattened_ids = [item.emdb_id for shard in shards for item in shard]
    assert len(flattened_ids) == len(set(flattened_ids)) == len(inputs)
    assert shards[0] == [inputs[0], inputs[3], inputs[6]]
    assert shards[1] == [inputs[1], inputs[4]]
    assert shards[2] == [inputs[2], inputs[5]]


def test_header_only_audit_reads_gzip_and_reports_mixed_risk(tmp_path: Path) -> None:
    """真实 ``.map.gz`` 仅靠 header 即可得到轴排列与 mixed-equality 风险。"""
    plain_path = tmp_path / "source.map"
    gzip_path = tmp_path / "emd_43.map.gz"
    # np.ndarray, (S,R,C)=(6,8,10)，mapc/mapr/maps=(2,3,1) 后物理 ZYX=(8,10,6)。
    grid = np.zeros((6, 8, 10), dtype=np.float32)
    with mrcfile.new(str(plain_path), overwrite=True) as handle:
        handle.set_data(grid)
        handle.header.mapc = 2
        handle.header.mapr = 3
        handle.header.maps = 1
        handle.voxel_size = (1.0, 2.0, 1.0)
    with plain_path.open("rb") as source, gzip_path.open("wb") as raw_target:
        with gzip.GzipFile(fileobj=raw_target, mode="wb", mtime=0) as target:
            target.write(source.read())

    record = audit_mrc_header(
        gzip_path,
        EmdbAuditInput(emdb_id="EMD-43", pair_count=2),
        1.0,
    )

    assert record["header"]["storage_shape_zyx"] == [6, 8, 10]
    assert record["geometry"]["input_shape_zyx"] == (8, 10, 6)
    assert record["geometry"]["axis_relation"] == "mixed_equality"
    assert record["risk_codes"] == [MIXED_EQUALITY_RISK, EFFECTIVE_CLOSURE_RISK]


def test_execute_audit_atomically_writes_frozen_summary_and_risks(tmp_path: Path) -> None:
    """端到端小样本同时冻结 pair_list、实现 manifest、header 投影和风险文件哈希。"""
    root = tmp_path / "dataset"
    map_dir = root / "raw" / "emdb_maps"
    map_dir.mkdir(parents=True)
    plain_path = tmp_path / "source.map"
    gzip_path = map_dir / "emd_43.map.gz"
    with mrcfile.new(str(plain_path), overwrite=True) as handle:
        handle.set_data(np.zeros((10, 12, 14), dtype=np.float32))
        handle.voxel_size = (1.0, 2.0, 1.0)
    with plain_path.open("rb") as source, gzip_path.open("wb") as raw_target:
        with gzip.GzipFile(fileobj=raw_target, mode="wb", mtime=0) as target:
            target.write(source.read())

    pair_list = root / "raw" / "pair_list.jsonl"
    pair_list.write_text(
        json.dumps({"pdb_id": "1abc", "emdb_id": "EMD-43"}) + "\n",
        encoding="utf-8",
    )
    implementation = {
        "files": {"test": {"sha256": "a" * 64, "size_bytes": 1}},
        "sha256": "b" * 64,
    }
    summary_path, risks_path, summary = execute_header_audit(
        root=root,
        pair_list_path=pair_list,
        run_id="unit_audit",
        target_voxel_size=1.0,
        part_id=0,
        total_parts=1,
        n_jobs=2,
        implementation=implementation,
        dependency_versions={"python": "test"},
    )

    assert summary_path.is_file()
    assert risks_path.is_file()
    assert summary["status"] == "completed_with_risks"
    assert summary["pair_list_sha256"] == _sha256(pair_list)
    assert summary["implementation"] == implementation
    assert summary["selected_emdb_count"] == 1
    assert summary["risk_record_count"] == 1
    assert summary["risk_code_counts"][MIXED_EQUALITY_RISK] == 1
    assert summary["canonical_contour_scale_distribution"]["count"] == 0
    assert len(summary["audited_header_projection_sha256"]) == 64
    assert summary["risk_jsonl_sha256"] == _sha256(risks_path)
    risk = json.loads(risks_path.read_text(encoding="utf-8").strip())
    assert risk["emdb_id"] == "EMD-43"


def _sha256(path: Path) -> str:
    """
    返回测试文件的 SHA-256。

    输入参数:
        - path: Path, 测试生成的输入或报告文件

    输出:
        - digest: str, 64 位小写十六进制 SHA-256
    """
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
