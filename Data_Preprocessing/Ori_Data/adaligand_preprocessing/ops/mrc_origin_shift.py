# 扫描并合并 MRC 重采样前后的 origin 位移审计。
# 主要输入：pair_list、正式 Stage E 终态与 EMDB MRC header。
# 主要输出：Pocket make_cubic shift 轴序影响的分片证据、受影响 PDB/EMDB 清单及 SHA-256。
# 关键边界：不读密度体素，不修改祖传实现，不改写 Stage E/F/G 产物或历史状态。
"""Pocket Plus ``make_cubic`` origin shift 轴序的只读影响审计。

Pocket 祖传 ``make_cubic`` 从 ZYX 数组 shape 返回 ZYX padding shift，
``make_model_grid`` 则把它直接与 XYZ voxel/origin 相乘。本模块只计算该
轴序事实的影响范围；它不给出科学修复，也不代替用户批准。
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Sequence
from uuid import uuid4

from joblib import Parallel, delayed
import mrcfile
import numpy as np

from adaligand_preprocessing.ops.mrc_contract import canonical_shape_zyx, read_pair_list, sha256_file


ORIGIN_SHIFT_AUDIT_SCHEMA_VERSION = 1
ORIGIN_SHIFT_AXIS_ORDER_RISK = "make_cubic_shift_zyx_used_as_xyz"
HEADER_READ_RISK = "header_read_failed"
ELIGIBLE_STAGE_E_STATUSES = frozenset({"success", "skipped"})
VALID_STAGE_STATUSES = frozenset(
    {"success", "skipped", "known_failed", "unknown_failed"}
)
REPORT_STAGE = "mrc_origin_shift_audit"


def analyze_origin_shift_axis_order(
    input_shape_zyx: Sequence[int],
    voxel_size_xyz: Sequence[float],
    loaded_origin_xyz: Sequence[float] = (0.0, 0.0, 0.0),
) -> dict[str, Any]:
    """计算祖传 ZYX shift 直接乘 XYZ 几何量的精确影响。

    输入参数:
        - input_shape_zyx: Sequence[int], ``load_map`` 轴重排后的 ZYX shape
        - voxel_size_xyz: Sequence[float], XYZ 每轴体素大小，单位 Å
        - loaded_origin_xyz: Sequence[float], ``load_map`` 返回的 XYZ origin，单位 Å

    输出:
        - geometry: dict, 祖传 shift、轴一致 shift、两种 origin 及误差

    ``make_cubic`` 对奇数轴补一格，并把旧数组放到新数组的中心，
    因此其返回的低端
    shift 严格等于 ``shape_zyx % 2``。受影响条件不是模糊的
    “奇偶问题”，而是 ZYX shift 的 Z 分量与 X 分量不同。
    """
    shape = np.asarray(input_shape_zyx, dtype=np.int64)
    voxel = np.asarray(voxel_size_xyz, dtype=np.float64)
    origin = np.asarray(loaded_origin_xyz, dtype=np.float64)
    if shape.shape != (3,) or np.any(shape <= 0):
        raise ValueError(f"invalid input shape ZYX: {shape.tolist()}")
    if voxel.shape != (3,) or not np.isfinite(voxel).all() or np.any(voxel <= 0):
        raise ValueError(f"invalid voxel size XYZ: {voxel.tolist()}")
    if origin.shape != (3,) or not np.isfinite(origin).all():
        raise ValueError(f"invalid loaded origin XYZ: {origin.tolist()}")

    shift_zyx = shape % 2
    shift_xyz = shift_zyx[::-1]
    ancestor_delta_xyz = -shift_zyx * voxel
    axis_consistent_delta_xyz = -shift_xyz * voxel
    ancestor_origin_xyz = origin + ancestor_delta_xyz
    axis_consistent_origin_xyz = origin + axis_consistent_delta_xyz
    error_xyz = ancestor_origin_xyz - axis_consistent_origin_xyz
    affected = bool(shift_zyx[0] != shift_zyx[2])
    return {
        "input_shape_zyx": [int(value) for value in shape],
        "voxel_size_xyz": [float(value) for value in voxel],
        "loaded_origin_xyz": [float(value) for value in origin],
        "make_cubic_shift_zyx": [int(value) for value in shift_zyx],
        "axis_consistent_shift_xyz": [int(value) for value in shift_xyz],
        "ancestor_origin_delta_xyz": [float(value) for value in ancestor_delta_xyz],
        "axis_consistent_origin_delta_xyz": [
            float(value) for value in axis_consistent_delta_xyz
        ],
        "ancestor_origin_xyz": [float(value) for value in ancestor_origin_xyz],
        "axis_consistent_origin_xyz": [
            float(value) for value in axis_consistent_origin_xyz
        ],
        "ancestor_minus_axis_consistent_origin_xyz": [
            float(value) for value in error_xyz
        ],
        "origin_error_l2_angstrom": float(np.linalg.norm(error_xyz)),
        "affected": affected,
        "affected_predicate": "make_cubic_shift_zyx[0] != make_cubic_shift_zyx[2]",
    }


def build_pair_index(
    pair_records: Sequence[dict[str, Any]],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """构建唯一 PDB→EMDB 及 EMDB→PDB 索引。"""
    pdb_to_emdb: dict[str, str] = {}
    emdb_to_pdbs: dict[str, list[str]] = {}
    for row_index, record in enumerate(pair_records):
        pdb_id = str(record.get("pdb_id", "")).lower()
        emdb_id = str(record.get("emdb_id", "")).upper()
        if not re.fullmatch(r"[0-9a-z]{4}", pdb_id):
            raise ValueError(f"invalid pdb_id at pair_list row {row_index}: {pdb_id!r}")
        if not re.fullmatch(r"EMD-[0-9]+", emdb_id):
            raise ValueError(f"invalid emdb_id at pair_list row {row_index}: {emdb_id!r}")
        if pdb_id in pdb_to_emdb:
            raise ValueError(f"duplicate PDB in pair_list: {pdb_id}")
        pdb_to_emdb[pdb_id] = emdb_id
        emdb_to_pdbs.setdefault(emdb_id, []).append(pdb_id)
    for pdb_ids in emdb_to_pdbs.values():
        pdb_ids.sort()
    return emdb_to_pdbs, pdb_to_emdb


def load_stage_e_statuses(
    stage_e_dir: Path,
    expected_pdb_ids: set[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """读取并冻结正式 Stage E 的互斥终态。"""
    paths = sorted(stage_e_dir.glob("status.part_*_of_*.jsonl"))
    if not paths:
        raise RuntimeError(f"no Stage E status files under {stage_e_dir}")
    records: dict[str, dict[str, Any]] = {}
    files: list[dict[str, Any]] = []
    for path in paths:
        count = 0
        with path.open("r", encoding="utf-8") as handle:
            for line_number, raw_line in enumerate(handle, start=1):
                line = raw_line.strip()
                if not line:
                    continue
                record = json.loads(line)
                pdb_id = str(record.get("pdb_id", "")).lower()
                status = str(record.get("status", ""))
                if record.get("stage") != "stage_e":
                    raise RuntimeError(f"wrong stage in {path}:{line_number}")
                if status not in VALID_STAGE_STATUSES:
                    raise RuntimeError(
                        f"invalid Stage E status in {path}:{line_number}: {status!r}"
                    )
                if not pdb_id or pdb_id in records:
                    raise RuntimeError(f"duplicate/empty Stage E PDB status: {pdb_id!r}")
                records[pdb_id] = record
                count += 1
        files.append(
            {
                "name": path.name,
                "sha256": sha256_file(path),
                "record_count": count,
            }
        )
    actual = set(records)
    if actual != expected_pdb_ids:
        missing = sorted(expected_pdb_ids - actual)
        extra = sorted(actual - expected_pdb_ids)
        raise RuntimeError(
            f"Stage E status universe drift: missing={missing[:20]}, extra={extra[:20]}"
        )
    projection = {"files": files, "record_count": len(records)}
    projection["sha256"] = hashlib.sha256(_canonical_json_bytes(projection)).hexdigest()
    return records, projection


def pocket_loaded_origin_from_header(
    origin_xyz: Sequence[float],
    nstart_crs: Sequence[int],
    mapc_mapr_maps: Sequence[int],
    voxel_size_xyz: Sequence[float],
) -> list[float]:
    """严格复现祖传 ``load_map(..., multiply_global_origin=True)`` origin。"""
    origin = np.asarray(origin_xyz, dtype=np.float64)
    nstart = np.asarray(nstart_crs, dtype=np.float64)
    axes = np.asarray(mapc_mapr_maps, dtype=np.int64)
    voxel = np.asarray(voxel_size_xyz, dtype=np.float64)
    if origin.shape != (3,) or nstart.shape != (3,) or axes.shape != (3,):
        raise ValueError("origin, nstart and map axes must each have length 3")
    if voxel.shape != (3,) or not np.isfinite(voxel).all() or np.any(voxel <= 0):
        raise ValueError("voxel size must contain three positive finite values")
    if set(int(value) for value in axes) != {1, 2, 3}:
        raise ValueError(f"invalid mapc/mapr/maps: {axes.tolist()}")
    start_xyz = np.zeros(3, dtype=np.float64)
    for physical_axis, start in zip(axes, nstart, strict=True):
        start_xyz[int(physical_axis) - 1] = start
    return [float(value) for value in (origin + start_xyz) * voxel]


def audit_one_header(
    map_path: Path,
    emdb_id: str,
    pdb_ids: Sequence[str],
    stage_e_statuses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """只读一张 MRC header，计算 shift 轴序风险并关联 Stage E。"""
    with mrcfile.open(str(map_path), mode="r", header_only=True) as handle:
        header = handle.header
        storage_shape_zyx = (int(header.nz), int(header.ny), int(header.nx))
        axes = (int(header.mapc), int(header.mapr), int(header.maps))
        voxel_xyz = (
            float(handle.voxel_size.x),
            float(handle.voxel_size.y),
            float(handle.voxel_size.z),
        )
        origin_xyz = (
            float(header.origin.x),
            float(header.origin.y),
            float(header.origin.z),
        )
        nstart_crs = (
            int(header.nxstart),
            int(header.nystart),
            int(header.nzstart),
        )
    input_shape_zyx = canonical_shape_zyx(
        storage_shape_zyx,
        axes[0],
        axes[1],
        axes[2],
    )
    loaded_origin_xyz = pocket_loaded_origin_from_header(
        origin_xyz,
        nstart_crs,
        axes,
        voxel_xyz,
    )
    geometry = analyze_origin_shift_axis_order(
        input_shape_zyx,
        voxel_xyz,
        loaded_origin_xyz,
    )
    status_join = [_stage_e_projection(pdb_id, stage_e_statuses[pdb_id]) for pdb_id in pdb_ids]
    return {
        "schema_version": ORIGIN_SHIFT_AUDIT_SCHEMA_VERSION,
        "status": "audited",
        "emdb_id": emdb_id,
        "pdb_count": len(pdb_ids),
        "pdb_ids": list(pdb_ids),
        "stage_e": status_join,
        "stage_e_status_counts": dict(
            sorted(Counter(item["status"] for item in status_join).items())
        ),
        "map_path": str(map_path),
        "map_size_bytes": map_path.stat().st_size,
        "header": {
            "storage_shape_zyx": list(storage_shape_zyx),
            "mapc_mapr_maps": list(axes),
            "voxel_size_xyz": list(voxel_xyz),
            "origin_xyz": list(origin_xyz),
            "nstart_crs": list(nstart_crs),
        },
        "geometry": geometry,
        "risk_codes": [ORIGIN_SHIFT_AXIS_ORDER_RISK] if geometry["affected"] else [],
    }


def audit_one_header_safe(
    map_path: Path,
    emdb_id: str,
    pdb_ids: Sequence[str],
    stage_e_statuses: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """把单图 header 失败转为显式不完整记录。"""
    try:
        return audit_one_header(map_path, emdb_id, pdb_ids, stage_e_statuses)
    except Exception as exc:
        return {
            "schema_version": ORIGIN_SHIFT_AUDIT_SCHEMA_VERSION,
            "status": "header_failed",
            "emdb_id": emdb_id,
            "pdb_count": len(pdb_ids),
            "pdb_ids": list(pdb_ids),
            "stage_e": [
                _stage_e_projection(pdb_id, stage_e_statuses[pdb_id]) for pdb_id in pdb_ids
            ],
            "map_path": str(map_path),
            "risk_codes": [HEADER_READ_RISK],
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def execute_origin_shift_shard(
    root: Path,
    pair_list_path: Path,
    source_run_id: str,
    audit_run_id: str,
    expected_stage_e_status_sha256: str,
    part_id: int,
    total_parts: int,
    n_jobs: int,
    implementation: dict[str, Any],
    dependency_versions: dict[str, str],
) -> tuple[Path, Path, dict[str, Any]]:
    """执行一个互斥分片，只写审计 run 下的风险和 summary。"""
    _validate_run_id(source_run_id, "source_run_id")
    _validate_run_and_partition(audit_run_id, part_id, total_parts, n_jobs)
    pair_records, pair_list_sha256 = read_pair_list(pair_list_path)
    emdb_to_pdbs, pdb_to_emdb = build_pair_index(pair_records)
    if not emdb_to_pdbs:
        raise ValueError("pair_list must not be empty")
    stage_e_dir = root / "reports" / "runs" / source_run_id / "stage_e"
    stage_e_statuses, status_manifest = load_stage_e_statuses(
        stage_e_dir,
        set(pdb_to_emdb),
    )
    _validate_expected_stage_e_status_sha256(
        status_manifest,
        expected_stage_e_status_sha256,
    )
    all_emdb_ids = sorted(emdb_to_pdbs, key=_emdb_sort_key)
    selected_emdb_ids = [
        emdb_id
        for index, emdb_id in enumerate(all_emdb_ids)
        if index % total_parts == part_id
    ]
    selected_manifest_sha256 = _selected_manifest_sha256(
        selected_emdb_ids,
        emdb_to_pdbs,
    )
    map_dir = root / "raw" / "emdb_maps"
    records = Parallel(n_jobs=n_jobs, backend="loky", verbose=10)(
        delayed(audit_one_header_safe)(
            map_dir / f"emd_{emdb_id[4:]}.map.gz",
            emdb_id,
            emdb_to_pdbs[emdb_id],
            stage_e_statuses,
        )
        for emdb_id in selected_emdb_ids
    )
    for record in records:
        record.update(
            {
                "audit_run_id": audit_run_id,
                "source_run_id": source_run_id,
                "part_id": part_id,
                "total_parts": total_parts,
            }
        )
    records.sort(key=lambda record: _emdb_sort_key(str(record["emdb_id"])))
    observed_emdb_ids = [str(record["emdb_id"]) for record in records]
    if observed_emdb_ids != selected_emdb_ids:
        raise RuntimeError(
            "observed EMDB IDs do not exactly match the planned audit shard"
        )
    observed_manifest_sha256 = _selected_manifest_sha256(
        observed_emdb_ids,
        emdb_to_pdbs,
    )
    risks = [record for record in records if record["risk_codes"]]

    report_dir = root / "reports" / "runs" / audit_run_id / REPORT_STAGE
    suffix = f"part_{part_id:04d}_of_{total_parts:04d}"
    risk_path = report_dir / f"risks.{suffix}.jsonl"
    summary_path = report_dir / f"summary.{suffix}.json"
    _atomic_write_jsonl(risk_path, risks)

    affected = [
        record
        for record in records
        if record["status"] == "audited" and record["geometry"]["affected"]
    ]
    affected_stage_statuses = Counter(
        item["status"] for record in affected for item in record["stage_e"]
    )
    status_counts = Counter(str(record["status"]) for record in records)
    failed_eligible_pdbs = sorted(
        item["pdb_id"]
        for record in records
        if record["status"] == "header_failed"
        for item in record["stage_e"]
        if item["eligible"]
    )
    summary = {
        "schema_version": ORIGIN_SHIFT_AUDIT_SCHEMA_VERSION,
        "status": (
            "incomplete_header_failures"
            if status_counts.get("header_failed", 0)
            else "completed"
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_run_id": source_run_id,
        "audit_run_id": audit_run_id,
        "part_id": part_id,
        "total_parts": total_parts,
        "n_jobs": n_jobs,
        "pair_list_path": str(pair_list_path),
        "pair_list_sha256": pair_list_sha256,
        "pair_list_row_count": len(pair_records),
        "unique_emdb_count": len(all_emdb_ids),
        "selected_emdb_count": len(selected_emdb_ids),
        "selected_pdb_count": sum(
            len(emdb_to_pdbs[emdb_id]) for emdb_id in selected_emdb_ids
        ),
        "selected_manifest_sha256": selected_manifest_sha256,
        "observed_emdb_count": len(observed_emdb_ids),
        "observed_manifest_sha256": observed_manifest_sha256,
        "status_counts": dict(sorted(status_counts.items())),
        "affected_emdb_count": len(affected),
        "affected_pdb_count": sum(record["pdb_count"] for record in affected),
        "affected_stage_e_status_counts": dict(sorted(affected_stage_statuses.items())),
        "risk_record_count": len(risks),
        "risk_jsonl_path": str(risk_path),
        "risk_jsonl_sha256": sha256_file(risk_path),
        "stage_e_status_manifest": status_manifest,
        "expected_stage_e_status_sha256": expected_stage_e_status_sha256,
        "header_failed_stage_e_eligible_pdb_count": len(failed_eligible_pdbs),
        "header_failed_stage_e_eligible_pdb_ids": failed_eligible_pdbs,
        "implementation": implementation,
        "dependency_versions": dict(sorted(dependency_versions.items())),
        "read_contract": "MRC header only; no density voxel or Stage E artifact read",
        "write_contract": "audit run only; no production artifact/status mutation",
    }
    _atomic_write_json(summary_path, summary)
    return summary_path, risk_path, summary


def finalize_origin_shift_audit(
    root: Path,
    pair_list_path: Path,
    source_run_id: str,
    audit_run_id: str,
    total_parts: int,
    expected_stage_e_status_sha256: str,
    implementation: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    """合并全部分片，生成排序受影响清单和 Stage E 连接证据。"""
    _validate_run_id(source_run_id, "source_run_id")
    _validate_run_id(audit_run_id, "audit_run_id")
    if total_parts <= 0:
        raise ValueError("total_parts must be positive")
    pair_records, pair_list_sha256 = read_pair_list(pair_list_path)
    emdb_to_pdbs, pdb_to_emdb = build_pair_index(pair_records)
    stage_e_dir = root / "reports" / "runs" / source_run_id / "stage_e"
    stage_e_statuses, status_manifest = load_stage_e_statuses(
        stage_e_dir,
        set(pdb_to_emdb),
    )
    _validate_expected_stage_e_status_sha256(
        status_manifest,
        expected_stage_e_status_sha256,
    )
    all_emdb_ids = sorted(emdb_to_pdbs, key=_emdb_sort_key)
    report_dir = root / "reports" / "runs" / audit_run_id / REPORT_STAGE
    summaries: list[dict[str, Any]] = []
    risks: list[dict[str, Any]] = []
    implementation_sha256: str | None = None
    dependency_versions: dict[str, str] | None = None
    for part_id in range(total_parts):
        suffix = f"part_{part_id:04d}_of_{total_parts:04d}"
        summary_path = report_dir / f"summary.{suffix}.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        selected = [
            emdb_id
            for index, emdb_id in enumerate(all_emdb_ids)
            if index % total_parts == part_id
        ]
        _validate_shard_summary(
            summary,
            part_id=part_id,
            total_parts=total_parts,
            pair_list_sha256=pair_list_sha256,
            status_manifest_sha256=str(status_manifest["sha256"]),
            expected_stage_e_status_sha256=expected_stage_e_status_sha256,
            selected_manifest_sha256=_selected_manifest_sha256(selected, emdb_to_pdbs),
            selected_emdb_count=len(selected),
        )
        current_implementation = str(summary["implementation"]["sha256"])
        if implementation_sha256 is None:
            implementation_sha256 = current_implementation
        elif current_implementation != implementation_sha256:
            raise RuntimeError("audit implementation changed between shards")
        current_dependencies = dict(summary["dependency_versions"])
        if dependency_versions is None:
            dependency_versions = current_dependencies
        elif current_dependencies != dependency_versions:
            raise RuntimeError("audit dependency versions changed between shards")
        risk_path = report_dir / f"risks.{suffix}.jsonl"
        if sha256_file(risk_path) != summary["risk_jsonl_sha256"]:
            raise RuntimeError(f"risk JSONL SHA drifted: {risk_path}")
        part_risks = _read_jsonl(risk_path)
        if len(part_risks) != int(summary["risk_record_count"]):
            raise RuntimeError(f"risk record count drifted: {risk_path}")
        if any(int(record.get("part_id", -1)) != part_id for record in part_risks):
            raise RuntimeError(f"risk record partition drifted: {risk_path}")
        _validate_part_risk_records(
            part_risks,
            selected_emdb_ids=set(selected),
            emdb_to_pdbs=emdb_to_pdbs,
            stage_e_statuses=stage_e_statuses,
            source_run_id=source_run_id,
            audit_run_id=audit_run_id,
            part_id=part_id,
            total_parts=total_parts,
        )
        summaries.append(summary)
        risks.extend(part_risks)

    if implementation_sha256 != implementation.get("sha256"):
        raise RuntimeError("finalizer implementation differs from scan implementation")

    risk_emdb_ids = [str(record["emdb_id"]) for record in risks]
    if len(risk_emdb_ids) != len(set(risk_emdb_ids)):
        raise RuntimeError("duplicate EMDB risk across audit shards")
    header_failures = [record for record in risks if record["status"] == "header_failed"]
    header_failure_eligible_pdb_ids = sorted(
        item["pdb_id"]
        for record in header_failures
        for item in record["stage_e"]
        if item["eligible"]
    )
    affected = sorted(
        (
            record
            for record in risks
            if record["status"] == "audited" and record["geometry"]["affected"]
        ),
        key=lambda record: _emdb_sort_key(str(record["emdb_id"])),
    )
    affected_emdb_ids = [str(record["emdb_id"]) for record in affected]
    affected_pairs: list[dict[str, Any]] = []
    for record in affected:
        geometry = record["geometry"]
        for pdb_id in record["pdb_ids"]:
            status = stage_e_statuses[str(pdb_id)]
            affected_pairs.append(
                {
                    "pdb_id": str(pdb_id),
                    "emdb_id": str(record["emdb_id"]),
                    "stage_e_status": str(status["status"]),
                    "stage_e_reason": status.get("reason"),
                    "stage_e_error": status.get("error"),
                    "stage_e_eligible": status["status"] in ELIGIBLE_STAGE_E_STATUSES,
                    "input_shape_zyx": geometry["input_shape_zyx"],
                    "voxel_size_xyz": geometry["voxel_size_xyz"],
                    "make_cubic_shift_zyx": geometry["make_cubic_shift_zyx"],
                    "axis_consistent_shift_xyz": geometry["axis_consistent_shift_xyz"],
                    "ancestor_minus_axis_consistent_origin_xyz": geometry[
                        "ancestor_minus_axis_consistent_origin_xyz"
                    ],
                    "origin_error_l2_angstrom": geometry["origin_error_l2_angstrom"],
                }
            )
    affected_pairs.sort(key=lambda item: (str(item["pdb_id"]), str(item["emdb_id"])))
    affected_pdb_ids = [str(item["pdb_id"]) for item in affected_pairs]
    eligible_pdb_ids = [
        str(item["pdb_id"]) for item in affected_pairs if item["stage_e_eligible"]
    ]
    affected_emdb_path = report_dir / "affected_emdb_ids.txt"
    affected_pdb_path = report_dir / "affected_pdb_ids.all.txt"
    eligible_pdb_path = report_dir / "affected_pdb_ids.stage_e_eligible.txt"
    affected_pairs_path = report_dir / "affected_pairs.stage_e_join.jsonl"
    header_failure_eligible_path = (
        report_dir / "header_failed_pdb_ids.stage_e_eligible.txt"
    )
    _atomic_write_lines(affected_emdb_path, affected_emdb_ids)
    _atomic_write_lines(affected_pdb_path, affected_pdb_ids)
    _atomic_write_lines(eligible_pdb_path, eligible_pdb_ids)
    _atomic_write_jsonl(affected_pairs_path, affected_pairs)
    _atomic_write_lines(header_failure_eligible_path, header_failure_eligible_pdb_ids)

    stage_status_counts = Counter(item["stage_e_status"] for item in affected_pairs)
    total_status_counts: Counter[str] = Counter()
    for summary in summaries:
        total_status_counts.update(summary["status_counts"])
    final_summary = {
        "schema_version": ORIGIN_SHIFT_AUDIT_SCHEMA_VERSION,
        "status": (
            "incomplete_header_failures"
            if header_failures
            else "completed_axis_order_risk_candidates"
            if affected
            else "completed_no_impact"
        ),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_run_id": source_run_id,
        "audit_run_id": audit_run_id,
        "total_parts": total_parts,
        "pair_list_path": str(pair_list_path),
        "pair_list_sha256": pair_list_sha256,
        "pair_list_row_count": len(pair_records),
        "unique_emdb_count": len(all_emdb_ids),
        "status_counts": dict(sorted(total_status_counts.items())),
        "header_failure_count": len(header_failures),
        "header_failure_emdb_ids": sorted(
            (str(record["emdb_id"]) for record in header_failures),
            key=_emdb_sort_key,
        ),
        "header_failure_stage_e_eligible_pdb_count": len(
            header_failure_eligible_pdb_ids
        ),
        "header_failure_stage_e_eligible_pdb_ids": header_failure_eligible_pdb_ids,
        "header_failure_stage_e_eligible_pdb_ids_file": _file_identity(
            header_failure_eligible_path
        ),
        "affected_emdb_count": len(affected_emdb_ids),
        "affected_emdb_fraction": len(affected_emdb_ids) / len(all_emdb_ids),
        "affected_pdb_count": len(affected_pdb_ids),
        "affected_pdb_fraction": len(affected_pdb_ids) / len(pair_records),
        "affected_stage_e_eligible_pdb_count": len(eligible_pdb_ids),
        "affected_stage_e_status_counts": dict(sorted(stage_status_counts.items())),
        "affected_emdb_ids": _file_identity(affected_emdb_path),
        "affected_pdb_ids_all": _file_identity(affected_pdb_path),
        "affected_pdb_ids_stage_e_eligible": _file_identity(eligible_pdb_path),
        "affected_pairs_stage_e_join": _file_identity(affected_pairs_path),
        "stage_e_status_manifest": status_manifest,
        "expected_stage_e_status_sha256": expected_stage_e_status_sha256,
        "implementation_sha256": implementation_sha256,
        "implementation": implementation,
        "dependency_versions": dependency_versions,
        "predicate": "make_cubic_shift_zyx[0] != make_cubic_shift_zyx[2]",
        "interpretation": (
            "header-derived axis-order risk hypothesis; not a verdict that the Pocket "
            "implementation or existing scientific products are defective"
        ),
        "decision_boundary": (
            "read-only impact evidence; any production correction requires explicit user approval"
        ),
    }
    final_summary_path = report_dir / "final_summary.json"
    _atomic_write_json(final_summary_path, final_summary)
    return final_summary_path, final_summary


def _stage_e_projection(pdb_id: str, record: dict[str, Any]) -> dict[str, Any]:
    """仅保留影响连接所需的 Stage E 终态字段。"""
    return {
        "pdb_id": pdb_id,
        "status": str(record["status"]),
        "reason": record.get("reason"),
        "error": record.get("error"),
        "eligible": record["status"] in ELIGIBLE_STAGE_E_STATUSES,
    }


def _selected_manifest_sha256(
    emdb_ids: Sequence[str],
    emdb_to_pdbs: dict[str, list[str]],
) -> str:
    """哈希一个分片的 EMDB 及其 PDB 引用关系。"""
    rows = [{"emdb_id": emdb_id, "pdb_ids": emdb_to_pdbs[emdb_id]} for emdb_id in emdb_ids]
    return hashlib.sha256(_canonical_json_bytes(rows)).hexdigest()


def _validate_run_and_partition(
    run_id: str,
    part_id: int,
    total_parts: int,
    n_jobs: int,
) -> None:
    """验证审计 run id 和分片参数。"""
    _validate_run_id(run_id, "audit_run_id")
    if total_parts <= 0 or part_id < 0 or part_id >= total_parts:
        raise ValueError("part_id must be in [0, total_parts)")
    if n_jobs <= 0:
        raise ValueError("n_jobs must be positive")


def _validate_shard_summary(
    summary: dict[str, Any],
    *,
    part_id: int,
    total_parts: int,
    pair_list_sha256: str,
    status_manifest_sha256: str,
    expected_stage_e_status_sha256: str,
    selected_manifest_sha256: str,
    selected_emdb_count: int,
) -> None:
    """拒绝合并任何输入、状态或分片身份漂移。"""
    expected = {
        "schema_version": ORIGIN_SHIFT_AUDIT_SCHEMA_VERSION,
        "part_id": part_id,
        "total_parts": total_parts,
        "pair_list_sha256": pair_list_sha256,
        "selected_manifest_sha256": selected_manifest_sha256,
        "selected_emdb_count": selected_emdb_count,
        "observed_emdb_count": selected_emdb_count,
        "observed_manifest_sha256": selected_manifest_sha256,
    }
    for field, value in expected.items():
        if summary.get(field) != value:
            raise RuntimeError(f"audit shard summary drifted at {field}: part {part_id}")
    if summary.get("stage_e_status_manifest", {}).get("sha256") != status_manifest_sha256:
        raise RuntimeError(f"Stage E status manifest drifted in part {part_id}")
    if summary.get("expected_stage_e_status_sha256") != expected_stage_e_status_sha256:
        raise RuntimeError(f"expected Stage E status SHA drifted in part {part_id}")
    status_counts = summary.get("status_counts", {})
    if not isinstance(status_counts, dict):
        raise RuntimeError(f"invalid status_counts in part {part_id}")
    try:
        observed_status_count = sum(int(value) for value in status_counts.values())
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid status_counts in part {part_id}") from exc
    if observed_status_count != selected_emdb_count:
        raise RuntimeError(f"status count coverage drifted in part {part_id}")


def _validate_run_id(run_id: str, field_name: str) -> None:
    """使 run id 只能形成一级受控目录名。"""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
        raise ValueError(f"{field_name} has an invalid format")


def _validate_expected_stage_e_status_sha256(
    status_manifest: dict[str, Any],
    expected_sha256: str,
) -> None:
    """把审计精确绑定到正式单文件 Stage E 历史证据。"""
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("expected_stage_e_status_sha256 must be a lowercase SHA-256")
    files = status_manifest["files"]
    if len(files) != 1:
        raise RuntimeError(
            "formal Stage E status SHA binding requires exactly one status file"
        )
    if files[0]["sha256"] != expected_sha256:
        raise RuntimeError(
            "formal Stage E status file SHA does not match the frozen expectation"
        )


def _validate_part_risk_records(
    records: Sequence[dict[str, Any]],
    *,
    selected_emdb_ids: set[str],
    emdb_to_pdbs: dict[str, list[str]],
    stage_e_statuses: dict[str, dict[str, Any]],
    source_run_id: str,
    audit_run_id: str,
    part_id: int,
    total_parts: int,
) -> None:
    """逐条验证 risk 与当前 pair_list、Stage E 及分片身份一致。"""
    for record in records:
        emdb_id = str(record.get("emdb_id", ""))
        if emdb_id not in selected_emdb_ids:
            raise RuntimeError(f"risk EMDB is outside part {part_id}: {emdb_id}")
        if record.get("source_run_id") != source_run_id:
            raise RuntimeError(f"risk source run drifted: {emdb_id}")
        if record.get("audit_run_id") != audit_run_id:
            raise RuntimeError(f"risk audit run drifted: {emdb_id}")
        if int(record.get("part_id", -1)) != part_id:
            raise RuntimeError(f"risk part id drifted: {emdb_id}")
        if int(record.get("total_parts", -1)) != total_parts:
            raise RuntimeError(f"risk total parts drifted: {emdb_id}")
        expected_pdb_ids = emdb_to_pdbs[emdb_id]
        if record.get("pdb_ids") != expected_pdb_ids:
            raise RuntimeError(f"risk PDB membership drifted: {emdb_id}")
        expected_stage_e = [
            _stage_e_projection(pdb_id, stage_e_statuses[pdb_id])
            for pdb_id in expected_pdb_ids
        ]
        if record.get("stage_e") != expected_stage_e:
            raise RuntimeError(f"risk Stage E join drifted: {emdb_id}")
        if record.get("status") == "audited":
            if record.get("risk_codes") != [ORIGIN_SHIFT_AXIS_ORDER_RISK]:
                raise RuntimeError(f"audited risk code drifted: {emdb_id}")
            if not bool(record.get("geometry", {}).get("affected")):
                raise RuntimeError(f"audited risk lost affected predicate: {emdb_id}")
        elif record.get("status") == "header_failed":
            if record.get("risk_codes") != [HEADER_READ_RISK]:
                raise RuntimeError(f"header failure risk code drifted: {emdb_id}")
        else:
            raise RuntimeError(f"invalid risk status: {emdb_id}")


def _emdb_sort_key(emdb_id: str) -> tuple[int, str]:
    """按 EMDB 数字 id 和原字符串稳定排序。"""
    return int(emdb_id[4:]), emdb_id


def _file_identity(path: Path) -> dict[str, Any]:
    """返回审计输出的路径、大小与 SHA-256。"""
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 UTF-8 JSONL，忽略空行。"""
    return [
        json.loads(line)
        for raw_line in path.read_text(encoding="utf-8").splitlines()
        if (line := raw_line.strip())
    ]


def _canonical_json_bytes(value: Any) -> bytes:
    """把 JSON 对象编码为稳定 UTF-8 字节。"""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_write_lines(path: Path, values: Sequence[str]) -> None:
    """原子写排序后的单列文本清单。"""
    payload = "".join(f"{value}\n" for value in values).encode("utf-8")
    _atomic_write_bytes(path, payload)


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """原子写缩进 JSON。"""
    payload = (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_write_bytes(path, payload)


def _atomic_write_jsonl(path: Path, records: Sequence[dict[str, Any]]) -> None:
    """原子写 JSONL；空集合仍写空文件。"""
    payload = b"".join(_canonical_json_bytes(record) + b"\n" for record in records)
    _atomic_write_bytes(path, payload)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    """在目标同目录写完整临时文件后原子替换。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
