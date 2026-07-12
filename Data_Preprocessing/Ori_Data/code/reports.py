"""失败记录、run-scoped stage 状态与样本报告。

- sharded_report_path：分片运行时把报告写成 `reports/{name}.part_0000_of_0006.jsonl`，避免多 array 任务互相覆盖。
- record_failure / write_report：并发安全地追加失败 JSONL（经 append_jsonl 文件锁）、原子写单样本 JSON 报告。
- stage_report_path / write_stage_results：每次运行独立记录 success/skipped/known_failed/unknown_failed，
  release gate 只消费明确 ``run_id``，不会混入历史失败。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
import os
from pathlib import Path
from typing import Any

import json
import re
from uuid import uuid4

from failures import ExternalToolError, KnownSampleFailure
from io_utils import append_jsonl, atomic_replace, write_jsonl


class StageStatus(str, Enum):
    """每个样本在一次 stage 运行中的互斥终态。"""

    SUCCESS = "success"
    SKIPPED = "skipped"
    KNOWN_FAILED = "known_failed"
    UNKNOWN_FAILED = "unknown_failed"


def resolve_run_id(explicit_run_id: str | None) -> str:
    """
    解析安全的 run id；正式 Slurm DAG 应显式传同一个值。

    输入参数:
        - explicit_run_id: str | None, CLI 的 ``--run_id``；为空时先读 ``ADALIGAND_RUN_ID``

    输出:
        - run_id: str, 可作为单级目录名的稳定标识
    """
    candidate = explicit_run_id or os.environ.get("ADALIGAND_RUN_ID")
    if candidate is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        candidate = f"manual_{timestamp}_{os.getpid()}_{uuid4().hex[:8]}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", candidate):
        raise ValueError("run_id must match [A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
    return candidate


def stage_report_path(
    root: Path,
    run_id: str,
    stage: str,
    part_id: int,
    total_parts: int,
) -> Path:
    """
    构造一次运行、一个 stage、一个 array 分片的状态清单路径。

    输出位于 ``reports/runs/{run_id}/{stage}/status.part_XXXX_of_YYYY.jsonl``。
    """
    safe_run_id = resolve_run_id(run_id)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", stage):
        raise ValueError("stage must be a lowercase identifier")
    if total_parts <= 0 or part_id < 0 or part_id >= total_parts:
        raise ValueError("invalid part_id/total_parts")
    return (
        root
        / "reports"
        / "runs"
        / safe_run_id
        / stage
        / f"status.part_{part_id:04d}_of_{total_parts:04d}.jsonl"
    )


def stage_result(
    pdb_id: str,
    stage: str,
    status: StageStatus | str,
    **extra: Any,
) -> dict[str, Any]:
    """构造一条可机器聚合的 stage 终态记录。"""
    normalized_status = StageStatus(status)
    record: dict[str, Any] = {
        "pdb_id": pdb_id.lower(),
        "stage": stage,
        "status": normalized_status.value,
    }
    record.update(extra)
    return record


def failure_stage_result(pdb_id: str, stage: str, exc: Exception) -> dict[str, Any]:
    """
    把异常严格分为已声明样本失败或阻塞 release 的未知失败。

    普通异常不会按字符串猜类型，也不会被静默降级为 known failure。
    """
    if isinstance(exc, KnownSampleFailure):
        return stage_result(
            pdb_id,
            stage,
            StageStatus.KNOWN_FAILED,
            reason=exc.code.value,
            error=exc.detail,
        )
    if isinstance(exc, ExternalToolError):
        return stage_result(
            pdb_id,
            stage,
            StageStatus.UNKNOWN_FAILED,
            reason=exc.code.value,
            error=exc.detail,
            error_type=type(exc).__name__,
        )
    return stage_result(
        pdb_id,
        stage,
        StageStatus.UNKNOWN_FAILED,
        reason=type(exc).__name__,
        error=str(exc),
    )


def write_stage_results(path: Path, records: list[dict[str, Any]]) -> None:
    """按 PDB 排序并原子写一次运行的分片终态，避免追加式历史污染。"""
    ordered = sorted(records, key=lambda item: (str(item["pdb_id"]), str(item["stage"])))
    write_jsonl(path, ordered)


def sharded_report_path(root: Path, filename: str, part_id: int, total_parts: int) -> Path:
    """
    构造支持 SLURM array 并发运行的报告路径。

    输入参数:
        - root: Path, Stage root
        - filename: str, 单任务模式下的报告文件名
        - part_id: int, 当前分片编号
        - total_parts: int, 分片总数

    输出:
        - path: Path, 单任务模式返回原文件名; 多分片模式返回带 part 后缀的文件名
    """
    if total_parts <= 1:
        return root / "reports" / filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    return root / "reports" / f"{stem}.part_{part_id:04d}_of_{total_parts:04d}{suffix}"


def record_failure(path: Path, pdb_id: str, stage: str, error: str, **extra: Any) -> None:
    """
    追加一条失败记录。

    输入参数:
        - path: Path, 失败 JSONL 文件路径
        - pdb_id: str, 小写 PDB id
        - stage: str, 失败阶段或资源名称
        - error: str, 错误摘要
        - extra: dict[str, Any], 附加上下文字段

    输出:
        - None: 记录追加完成
    """
    record = {"pdb_id": pdb_id, "stage": stage, "error": error}
    record.update(extra)
    append_jsonl(path, record)


def write_report(path: Path, report: dict[str, Any]) -> None:
    """
    写入单样本 JSON 报告。

    输入参数:
        - path: Path, 输出 JSON 路径
        - report: dict[str, Any], 样本级解析报告

    输出:
        - None: 报告写入完成
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    atomic_replace(tmp_path, path)
