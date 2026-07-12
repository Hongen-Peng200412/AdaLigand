"""Pocket Plus 祖传 MRC 重采样契约的只读 header 审计。

本模块只读取 MRC header，不读取或改写密度体素。计算规则逐项复现
``make_cubic``、``normalize_voxel_size`` 与 ``rescale_real`` 的 shape 判定，
用于在正式 Stage E 前定位混合轴相等导致的整体跳过风险。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Sequence
from uuid import uuid4

from joblib import Parallel, delayed
import mrcfile
import numpy as np


MRC_CONTRACT_AUDIT_SCHEMA_VERSION = 1
MIXED_EQUALITY_RISK = "mixed_equality_rescale_skip"
EFFECTIVE_CLOSURE_RISK = "effective_physical_closure_mismatch"
INTENDED_CLOSURE_RISK = "intended_physical_closure_mismatch"
HEADER_READ_RISK = "header_read_failed"


@dataclass(frozen=True)
class EmdbAuditInput:
    """
    一张唯一 EMDB 主图的审计输入。

    输入参数:
        - emdb_id: str, 大写且带 ``EMD-`` 前缀的 EMDB id
        - pair_count: int, ``pair_list`` 中引用该 EMDB 的 PDB 样本数
    """

    emdb_id: str
    pair_count: int


@dataclass(frozen=True)
class ResampleGeometry:
    """
    由 header 推导的祖传重采样 shape、voxel 与闭合关系。

    输入参数:
        - input_shape_zyx: tuple[int, int, int], 轴排列后的原始 ZYX shape
        - even_input_shape_zyx: tuple[int, int, int], ``make_cubic`` 后的 ZYX shape
        - intended_output_shape_zyx: tuple[int, int, int], ``normalize_voxel_size`` 计划的偶数 ZYX shape
        - effective_output_shape_zyx: tuple[int, int, int], 祖传 ``np.all`` 条件实际会返回的 ZYX shape
        - input_voxel_size_xyz: tuple[float, float, float], header 的 XYZ voxel Å
        - actual_voxel_size_xyz: tuple[float, float, float], 祖传函数声明的实际 XYZ voxel Å
        - target_voxel_size: float, 本次审计使用的目标 voxel Å
        - axis_relation: str, ``all_equal``、``all_diff`` 或 ``mixed_equality``
        - ancestor_rescale_executed: bool, 祖传 ``np.all(out != in)`` 是否进入 Fourier 重采样
        - mixed_equality_risk: bool, 是否同时存在相等轴和变化轴
        - normal_rescale_amplitude_ratio: float, 正常重采样时 ``prod(even_in) / prod(out)``
        - intended_physical_closure: bool, 计划输出与 padded 输入的物理长度是否闭合
        - intended_closure_max_abs_angstrom: float, 上述闭合的最大轴绝对误差 Å
        - effective_physical_closure: bool, 祖传实际返回 shape 配合声明 voxel 后是否闭合
        - effective_closure_max_abs_angstrom: float, 上述闭合的最大轴绝对误差 Å
    """

    input_shape_zyx: tuple[int, int, int]
    even_input_shape_zyx: tuple[int, int, int]
    intended_output_shape_zyx: tuple[int, int, int]
    effective_output_shape_zyx: tuple[int, int, int]
    input_voxel_size_xyz: tuple[float, float, float]
    actual_voxel_size_xyz: tuple[float, float, float]
    target_voxel_size: float
    axis_relation: str
    ancestor_rescale_executed: bool
    mixed_equality_risk: bool
    normal_rescale_amplitude_ratio: float
    intended_physical_closure: bool
    intended_closure_max_abs_angstrom: float
    effective_physical_closure: bool
    effective_closure_max_abs_angstrom: float


def canonical_shape_zyx(
    storage_shape_zyx: Sequence[int],
    mapc: int,
    mapr: int,
    maps: int,
) -> tuple[int, int, int]:
    """
    按 MRC ``mapc/mapr/maps`` 把存储 shape 换算为 Pocket 网格的 ZYX shape。

    输入参数:
        - storage_shape_zyx: Sequence[int], 长度 3，header ``nz, ny, nx``
        - mapc: int, column 对应的物理轴编号，X/Y/Z 分别为 1/2/3
        - mapr: int, row 对应的物理轴编号
        - maps: int, section 对应的物理轴编号

    输出:
        - canonical_shape: tuple[int, int, int], 长度 3，标准 ZYX shape
    """
    shape = np.asarray(storage_shape_zyx, dtype=np.int64)
    if shape.shape != (3,) or np.any(shape <= 0):
        raise ValueError(f"invalid storage shape: {shape.tolist()}")
    axis_order = (int(mapc), int(mapr), int(maps))
    if set(axis_order) != {1, 2, 3}:
        raise ValueError(f"mapc/mapr/maps must be a permutation of 1,2,3: {axis_order}")

    # storage C/R/S 的长度依次为 nx/ny/nz，再按 header 映射到物理 XYZ。
    storage_shape_crs = shape[::-1]
    shape_xyz = np.zeros(3, dtype=np.int64)
    for physical_axis, axis_size in zip(axis_order, storage_shape_crs, strict=True):
        shape_xyz[physical_axis - 1] = axis_size
    return tuple(int(value) for value in shape_xyz[::-1])


def analyze_resample_geometry(
    input_shape_zyx: Sequence[int],
    input_voxel_size_xyz: Sequence[float],
    target_voxel_size: float,
) -> ResampleGeometry:
    """
    仅用 shape/voxel 复现祖传偶数 padding、目标 shape 与重采样条件。

    输入参数:
        - input_shape_zyx: Sequence[int], 长度 3，轴排列后的原始 ZYX shape
        - input_voxel_size_xyz: Sequence[float], 长度 3，header XYZ voxel Å
        - target_voxel_size: float, 正有限目标 voxel Å；正式审计建议显式传 1.0

    输出:
        - geometry: ResampleGeometry, 不读取体素即可得到的完整 shape/voxel 契约
    """
    input_shape = np.asarray(input_shape_zyx, dtype=np.int64)
    input_voxel = np.asarray(input_voxel_size_xyz, dtype=np.float64)
    if input_shape.shape != (3,) or np.any(input_shape <= 0):
        raise ValueError(f"invalid input shape: {input_shape.tolist()}")
    if input_voxel.shape != (3,) or not np.isfinite(input_voxel).all() or np.any(input_voxel <= 0):
        raise ValueError(f"invalid input voxel size: {input_voxel.tolist()}")
    if not math.isfinite(target_voxel_size) or target_voxel_size <= 0:
        raise ValueError("target_voxel_size must be a positive finite number")

    # 与 Pocket ``make_cubic`` 一致：只把奇数轴在高端补成偶数。
    even_shape_zyx = input_shape + input_shape % 2
    even_shape_xyz = even_shape_zyx[::-1]
    intended_out_xyz = np.ceil(
        even_shape_xyz * input_voxel / float(target_voxel_size)
    ).astype(np.int64)

    # 与 Pocket ``normalize_voxel_size`` 一致：奇数候选在相邻两个偶数中取 voxel 更接近目标者；
    # 严格小于意味着等距时选择 h-1。
    for axis_index, candidate in enumerate(intended_out_xyz):
        h = int(candidate)
        if h % 2 == 0:
            continue
        physical_length = input_voxel[axis_index] * even_shape_xyz[axis_index]
        voxel_plus = physical_length / (h + 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            voxel_minus = float(np.divide(physical_length, h - 1))
        intended_out_xyz[axis_index] = (
            h + 1
            if abs(voxel_plus - target_voxel_size) < abs(voxel_minus - target_voxel_size)
            else h - 1
        )

    actual_voxel_xyz = input_voxel * even_shape_xyz / intended_out_xyz
    intended_out_zyx = intended_out_xyz[::-1]
    equal_axes = intended_out_zyx == even_shape_zyx
    changed_axes = ~equal_axes
    mixed_equality = bool(np.any(equal_axes) and np.any(changed_axes))
    ancestor_rescale_executed = bool(np.all(changed_axes))
    if np.all(equal_axes):
        axis_relation = "all_equal"
    elif ancestor_rescale_executed:
        axis_relation = "all_diff"
    else:
        axis_relation = "mixed_equality"

    # ``rescale_real`` 只有三个轴全部变化时才返回 intended shape；混合轴会整体跳过。
    effective_out_zyx = intended_out_zyx if ancestor_rescale_executed else even_shape_zyx
    input_length_xyz = even_shape_xyz * input_voxel
    intended_length_xyz = intended_out_xyz * actual_voxel_xyz
    effective_length_xyz = effective_out_zyx[::-1] * actual_voxel_xyz
    intended_abs_error = np.abs(intended_length_xyz - input_length_xyz)
    effective_abs_error = np.abs(effective_length_xyz - input_length_xyz)
    intended_closure = bool(
        np.allclose(intended_length_xyz, input_length_xyz, rtol=1e-12, atol=1e-9)
    )
    effective_closure = bool(
        np.allclose(effective_length_xyz, input_length_xyz, rtol=1e-12, atol=1e-9)
    )
    amplitude_ratio = float(
        math.prod(int(value) for value in even_shape_zyx)
        / math.prod(int(value) for value in intended_out_zyx)
    )

    return ResampleGeometry(
        input_shape_zyx=tuple(int(value) for value in input_shape),
        even_input_shape_zyx=tuple(int(value) for value in even_shape_zyx),
        intended_output_shape_zyx=tuple(int(value) for value in intended_out_zyx),
        effective_output_shape_zyx=tuple(int(value) for value in effective_out_zyx),
        input_voxel_size_xyz=tuple(float(value) for value in input_voxel),
        actual_voxel_size_xyz=tuple(float(value) for value in actual_voxel_xyz),
        target_voxel_size=float(target_voxel_size),
        axis_relation=axis_relation,
        ancestor_rescale_executed=ancestor_rescale_executed,
        mixed_equality_risk=mixed_equality,
        normal_rescale_amplitude_ratio=amplitude_ratio,
        intended_physical_closure=intended_closure,
        intended_closure_max_abs_angstrom=float(np.max(intended_abs_error)),
        effective_physical_closure=effective_closure,
        effective_closure_max_abs_angstrom=float(np.max(effective_abs_error)),
    )


def collect_unique_emdb_inputs(pair_records: list[dict[str, Any]]) -> list[EmdbAuditInput]:
    """
    从 ``pair_list`` 聚合唯一 EMDB，并保留每张图被多少 PDB 引用。

    输入参数:
        - pair_records: list[dict[str, Any]], 每项至少含 ``emdb_id``

    输出:
        - inputs: list[EmdbAuditInput], 按 EMDB 数字再按原字符串稳定排序
    """
    counts: Counter[str] = Counter()
    for row_index, record in enumerate(pair_records):
        emdb_id = str(record.get("emdb_id", "")).upper()
        if not emdb_id.startswith("EMD-") or not emdb_id[4:].isdigit():
            raise ValueError(f"invalid emdb_id at pair_list row {row_index}: {emdb_id!r}")
        counts[emdb_id] += 1
    return [
        EmdbAuditInput(emdb_id=emdb_id, pair_count=counts[emdb_id])
        for emdb_id in sorted(counts, key=lambda item: (int(item[4:]), item))
    ]


def shard_emdb_inputs(
    inputs: Sequence[EmdbAuditInput],
    part_id: int,
    total_parts: int,
) -> list[EmdbAuditInput]:
    """
    按稳定下标取模切分唯一 EMDB，供 Slurm array 并行审计。

    输入参数:
        - inputs: Sequence[EmdbAuditInput], 已稳定排序的唯一 EMDB
        - part_id: int, 当前分片编号，从 0 开始
        - total_parts: int, 分片总数

    输出:
        - shard: list[EmdbAuditInput], 当前分片的互斥子集
    """
    if total_parts <= 0 or part_id < 0 or part_id >= total_parts:
        raise ValueError("part_id must be in [0, total_parts)")
    return [item for index, item in enumerate(inputs) if index % total_parts == part_id]


def audit_mrc_header(
    map_path: Path,
    emdb_input: EmdbAuditInput,
    target_voxel_size: float,
) -> dict[str, Any]:
    """
    只读一张 ``.map.gz`` 的 header 并生成完整契约记录。

    输入参数:
        - map_path: Path, 原始 EMDB ``.map.gz`` 路径
        - emdb_input: EmdbAuditInput, 唯一 EMDB id 与引用计数
        - target_voxel_size: float, 正有限目标 voxel Å

    输出:
        - record: dict[str, Any], 含 raw header、标准 shape、祖传几何与风险代码
    """
    with mrcfile.open(str(map_path), mode="r", header_only=True) as handle:
        header = handle.header
        storage_shape_zyx = (
            int(header.nz),
            int(header.ny),
            int(header.nx),
        )
        mapc = int(header.mapc)
        mapr = int(header.mapr)
        maps = int(header.maps)
        voxel_size_xyz = (
            float(handle.voxel_size.x),
            float(handle.voxel_size.y),
            float(handle.voxel_size.z),
        )
        header_snapshot = {
            "storage_shape_zyx": list(storage_shape_zyx),
            "mapc_mapr_maps": [mapc, mapr, maps],
            "mx_my_mz": [int(header.mx), int(header.my), int(header.mz)],
            "cella_xyz": [
                float(header.cella.x),
                float(header.cella.y),
                float(header.cella.z),
            ],
            "voxel_size_xyz": list(voxel_size_xyz),
            "nstart_crs": [
                int(header.nxstart),
                int(header.nystart),
                int(header.nzstart),
            ],
            "origin_xyz": [
                float(header.origin.x),
                float(header.origin.y),
                float(header.origin.z),
            ],
        }

    header_float_values = [
        *header_snapshot["cella_xyz"],
        *header_snapshot["voxel_size_xyz"],
        *header_snapshot["origin_xyz"],
    ]
    if not np.isfinite(np.asarray(header_float_values, dtype=np.float64)).all():
        raise ValueError("MRC header contains non-finite geometry values")

    input_shape_zyx = canonical_shape_zyx(storage_shape_zyx, mapc, mapr, maps)
    geometry = analyze_resample_geometry(
        input_shape_zyx,
        voxel_size_xyz,
        target_voxel_size,
    )
    risk_codes: list[str] = []
    if geometry.mixed_equality_risk:
        risk_codes.append(MIXED_EQUALITY_RISK)
    if not geometry.intended_physical_closure:
        risk_codes.append(INTENDED_CLOSURE_RISK)
    if not geometry.effective_physical_closure:
        risk_codes.append(EFFECTIVE_CLOSURE_RISK)

    return {
        "schema_version": MRC_CONTRACT_AUDIT_SCHEMA_VERSION,
        "status": "audited",
        "emdb_id": emdb_input.emdb_id,
        "pair_count": emdb_input.pair_count,
        "map_path": str(map_path),
        "map_size_bytes": map_path.stat().st_size,
        "header": header_snapshot,
        "geometry": asdict(geometry),
        "risk_codes": risk_codes,
    }


def audit_mrc_header_safe(
    map_path: Path,
    emdb_input: EmdbAuditInput,
    target_voxel_size: float,
) -> dict[str, Any]:
    """
    把单图 header 异常转换为风险记录，保证并行审计收集完整失败集合。

    输入参数:
        - map_path: Path, 原始 EMDB ``.map.gz`` 路径
        - emdb_input: EmdbAuditInput, 唯一 EMDB id 与引用计数
        - target_voxel_size: float, 正有限目标 voxel Å

    输出:
        - record: dict[str, Any], 成功时为完整审计记录，失败时含异常类型与文本
    """
    try:
        return audit_mrc_header(map_path, emdb_input, target_voxel_size)
    except Exception as exc:
        return {
            "schema_version": MRC_CONTRACT_AUDIT_SCHEMA_VERSION,
            "status": "header_failed",
            "emdb_id": emdb_input.emdb_id,
            "pair_count": emdb_input.pair_count,
            "map_path": str(map_path),
            "risk_codes": [HEADER_READ_RISK],
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def read_pair_list(pair_list_path: Path) -> tuple[list[dict[str, Any]], str]:
    """
    一次读取并冻结 UTF-8 ``pair_list.jsonl``。

    输入参数:
        - pair_list_path: Path, 每行一个 JSON 对象的样本清单

    输出:
        - records: list[dict[str, Any]], 保持输入行序的对象
        - sha256: str, 原始文件字节 SHA-256
    """
    payload = pair_list_path.read_bytes()
    records = [
        json.loads(line)
        for raw_line in payload.decode("utf-8").splitlines()
        if (line := raw_line.strip())
    ]
    return records, hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    """
    流式计算文件 SHA-256，避免为冻结实现而一次加载大文件。

    输入参数:
        - path: Path, 待哈希文件

    输出:
        - digest: str, 64 位小写十六进制 SHA-256
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def implementation_manifest(paths: dict[str, Path]) -> dict[str, Any]:
    """
    冻结本次审计代码与祖传快照的逐文件及组合哈希。

    输入参数:
        - paths: dict[str, Path], 稳定逻辑名到实际文件路径的映射

    输出:
        - manifest: dict[str, Any], 含 ``files`` 逐文件哈希和 ``sha256`` 组合哈希
    """
    files = {
        logical_name: {
            "path": str(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for logical_name, path in sorted(paths.items())
    }
    stable_projection = {
        logical_name: {
            "sha256": item["sha256"],
            "size_bytes": item["size_bytes"],
        }
        for logical_name, item in files.items()
    }
    payload = _canonical_json_bytes(stable_projection)
    return {"files": files, "sha256": hashlib.sha256(payload).hexdigest()}


def execute_header_audit(
    root: Path,
    pair_list_path: Path,
    run_id: str,
    target_voxel_size: float,
    part_id: int,
    total_parts: int,
    n_jobs: int,
    implementation: dict[str, Any],
    dependency_versions: dict[str, str],
) -> tuple[Path, Path, dict[str, Any]]:
    """
    并行执行唯一 EMDB header 审计，并原子写 run-scoped 风险与汇总。

    输入参数:
        - root: Path, 数据根，原始图位于 ``raw/emdb_maps``
        - pair_list_path: Path, 本轮冻结的 ``pair_list.jsonl``
        - run_id: str, 已由 CLI 验证的单级运行标识
        - target_voxel_size: float, 正有限目标 voxel Å
        - part_id: int, 当前分片编号，从 0 开始
        - total_parts: int, 分片总数
        - n_jobs: int, 当前分片的 joblib 进程数，必须为正
        - implementation: dict[str, Any], ``implementation_manifest`` 的返回值
        - dependency_versions: dict[str, str], Python/Numpy/mrcfile/joblib 版本

    输出:
        - summary_path: Path, 原子落盘的分片 summary JSON
        - risks_path: Path, 原子落盘的分片风险 JSONL
        - summary: dict[str, Any], 与 summary 文件一致的对象
    """
    if n_jobs <= 0:
        raise ValueError("n_jobs must be positive")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
        raise ValueError("run_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    if not math.isfinite(target_voxel_size) or target_voxel_size <= 0:
        raise ValueError("target_voxel_size must be a positive finite number")
    pair_records, pair_list_sha256 = read_pair_list(pair_list_path)
    all_inputs = collect_unique_emdb_inputs(pair_records)
    if not all_inputs:
        raise ValueError("pair_list must contain at least one EMDB record")
    selected_inputs = shard_emdb_inputs(all_inputs, part_id, total_parts)
    map_dir = root / "raw" / "emdb_maps"
    records = Parallel(n_jobs=n_jobs, backend="loky", verbose=10)(
        delayed(audit_mrc_header_safe)(
            map_dir / f"emd_{item.emdb_id[4:]}.map.gz",
            item,
            target_voxel_size,
        )
        for item in selected_inputs
    )
    for record in records:
        record["run_id"] = run_id
        record["part_id"] = part_id
        record["total_parts"] = total_parts
    records = sorted(records, key=lambda item: str(item["emdb_id"]))
    risks = [record for record in records if record["risk_codes"]]

    report_dir = root / "reports" / "runs" / run_id / "mrc_contract_audit"
    suffix = f"part_{part_id:04d}_of_{total_parts:04d}"
    risks_path = report_dir / f"risks.{suffix}.jsonl"
    summary_path = report_dir / f"summary.{suffix}.json"
    _atomic_write_jsonl(risks_path, risks)

    status_counts = Counter(str(record["status"]) for record in records)
    relation_counts = Counter(
        str(record["geometry"]["axis_relation"])
        for record in records
        if record["status"] == "audited"
    )
    risk_code_counts = Counter(
        str(risk_code)
        for record in risks
        for risk_code in record["risk_codes"]
    )
    header_projection = [
        {
            "emdb_id": record["emdb_id"],
            "map_size_bytes": record["map_size_bytes"],
            "header": record["header"],
        }
        for record in records
        if record["status"] == "audited"
    ]
    selected_id_payload = "".join(
        f"{item.emdb_id}\t{item.pair_count}\n" for item in selected_inputs
    ).encode("utf-8")
    summary = {
        "schema_version": MRC_CONTRACT_AUDIT_SCHEMA_VERSION,
        "status": "completed_with_risks" if risks else "completed_without_risks",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "root": str(root),
        "pair_list_path": str(pair_list_path),
        "pair_list_sha256": pair_list_sha256,
        "pair_list_row_count": len(pair_records),
        "unique_emdb_count": len(all_inputs),
        "selected_emdb_count": len(selected_inputs),
        "selected_emdb_manifest_sha256": hashlib.sha256(selected_id_payload).hexdigest(),
        "part_id": part_id,
        "total_parts": total_parts,
        "n_jobs": n_jobs,
        "target_voxel_size": float(target_voxel_size),
        "status_counts": dict(sorted(status_counts.items())),
        "axis_relation_counts": dict(sorted(relation_counts.items())),
        "risk_record_count": len(risks),
        "risk_code_counts": dict(sorted(risk_code_counts.items())),
        "risk_jsonl_path": str(risks_path),
        "risk_jsonl_sha256": sha256_file(risks_path),
        "audited_header_projection_sha256": hashlib.sha256(
            _canonical_json_bytes(header_projection)
        ).hexdigest(),
        "implementation": implementation,
        "dependency_versions": dict(sorted(dependency_versions.items())),
        "read_contract": "mrcfile.open(mode='r', header_only=True); no density voxel read",
        "write_contract": "only run-scoped summary JSON and risk JSONL are atomically replaced",
    }
    _atomic_write_json(summary_path, summary)
    return summary_path, risks_path, summary


def _canonical_json_bytes(value: Any) -> bytes:
    """
    把可 JSON 序列化对象编码为稳定 UTF-8 字节，供 provenance 哈希。

    输入参数:
        - value: Any, 不含 NaN/Infinity 的 JSON 可序列化对象

    输出:
        - payload: bytes, key 排序且无非必要空白的 UTF-8 JSON
    """
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """
    在目标同目录完整写临时 JSON 后用 ``os.replace`` 原子替换。

    输入参数:
        - path: Path, 最终 JSON 报告路径
        - value: dict[str, Any], 不含 NaN/Infinity 的报告对象

    输出:
        - None: 目标路径只暴露完整 JSON
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}")
    temporary.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _atomic_write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """
    在目标同目录完整写临时 JSONL 后用 ``os.replace`` 原子替换。

    输入参数:
        - path: Path, 最终 JSONL 风险报告路径
        - records: list[dict[str, Any]], 已稳定排序且不含 NaN/Infinity 的风险记录

    输出:
        - None: 目标路径只暴露完整 JSONL，空风险集合写为空文件
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            )
    os.replace(temporary, path)
