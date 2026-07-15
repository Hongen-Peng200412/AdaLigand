"""Stage F 远尾补算计划：冻结互斥子集、输入身份与资源边界。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from exclusions import load_run_exclusions
from filtering import load_stage_statuses
from io_utils import atomic_replace, read_jsonl, sha256_file
from reports import StageStatus, resolve_run_id


_ELIGIBLE_UPSTREAM_STATUSES = {
    StageStatus.SUCCESS.value,
    StageStatus.SKIPPED.value,
}


def create_f_supplement_plan(
    root: Path,
    *,
    formal_run_id: str,
    supplement_run_id: str,
    evidence_dir: Path,
    tail_count: int,
    formal_completed_upper_bound: int,
    minimum_initial_gap: int,
    collision_guard_tasks: int,
    expected_pair_list_sha256: str,
    expected_exclusions_sha256: str,
    formal_job_id: int,
) -> dict[str, Any]:
    """
    冻结一个与正在运行的正式 Stage F 相隔足够远的尾部补算子集。

    输入参数:
        - root: Path，服务器 Ori_Data 数据根
        - formal_run_id/supplement_run_id: str，正式 run 与独立补算 run 身份
        - evidence_dir: Path，本轮只写一次的计划证据目录
        - tail_count: int，从 ``pair_list`` 末尾取出的原始位置数
        - formal_completed_upper_bound: int，计划时正式 joblib 已完成任务数的保守上界
        - minimum_initial_gap: int，正式进度与补算尾段起点之间的最小安全间隔
        - collision_guard_tasks: int，正式进度距尾段起点达到该值时应停止未完成补算
        - expected_pair_list_sha256/expected_exclusions_sha256: str，冻结输入身份
        - formal_job_id: int，正在运行且不得修改的正式 Slurm Job ID

    输出:
        - summary: dict，包含冻结 ID、哈希、位置、安全间隔、资源和产物计数

    该函数只创建 run-scoped 计划证据，不写正式 Stage F 状态，也不改变科学契约。
    """
    root = root.resolve()
    evidence_dir = evidence_dir.resolve()
    formal_run_id = resolve_run_id(formal_run_id)
    supplement_run_id = resolve_run_id(supplement_run_id)
    if formal_run_id == supplement_run_id:
        raise ValueError("supplement run_id must differ from the formal run_id")
    if tail_count <= 0:
        raise ValueError("tail_count must be positive")
    if formal_completed_upper_bound < 0:
        raise ValueError("formal_completed_upper_bound cannot be negative")
    if minimum_initial_gap <= 0 or collision_guard_tasks <= 0:
        raise ValueError("safety gaps must be positive")
    if minimum_initial_gap <= collision_guard_tasks:
        raise ValueError("minimum_initial_gap must exceed collision_guard_tasks")

    pair_list_path = root / "raw" / "pair_list.jsonl"
    _require_regular_file(pair_list_path, "pair_list")
    pair_list_sha256 = sha256_file(pair_list_path)
    if pair_list_sha256 != expected_pair_list_sha256:
        raise RuntimeError(
            "pair_list identity drift: "
            f"expected={expected_pair_list_sha256}, actual={pair_list_sha256}"
        )
    pair_records = read_jsonl(pair_list_path)
    pdb_ids = [str(record.get("pdb_id", "")).lower() for record in pair_records]
    if not pdb_ids or any(not pdb_id for pdb_id in pdb_ids):
        raise ValueError("pair_list contains an empty PDB id")
    if len(pdb_ids) != len(set(pdb_ids)):
        raise ValueError("pair_list contains duplicate PDB ids")
    if tail_count >= len(pdb_ids):
        raise ValueError("tail_count must be smaller than the pair_list universe")

    formal_run_dir = root / "reports" / "runs" / formal_run_id
    if (formal_run_dir / "f_release" / "summary.json").exists():
        raise RuntimeError("formal Stage F is already released; supplement is no longer needed")
    supplement_run_dir = root / "reports" / "runs" / supplement_run_id
    existing_supplement_statuses = list(
        (supplement_run_dir / "stage_f").glob("status.part_*_of_*.jsonl")
    )
    if existing_supplement_statuses:
        raise RuntimeError("supplement run_id already has Stage F status files")

    exclusions, exclusions_sha256 = load_run_exclusions(
        root,
        formal_run_id,
        "stage_f",
    )
    if exclusions_sha256 != expected_exclusions_sha256:
        raise RuntimeError(
            "formal Stage F exclusion identity drift: "
            f"expected={expected_exclusions_sha256}, actual={exclusions_sha256}"
        )
    unknown_exclusions = sorted(set(exclusions).difference(pdb_ids))
    if unknown_exclusions:
        raise RuntimeError(f"formal exclusions are outside pair_list: {unknown_exclusions}")

    stage_e_statuses, stage_e_paths = load_stage_statuses(
        root,
        formal_run_id,
        "stage_e",
        set(pdb_ids),
    )
    tail_start_index = len(pdb_ids) - tail_count
    initial_gap = tail_start_index - formal_completed_upper_bound
    if initial_gap < minimum_initial_gap:
        raise RuntimeError(
            "formal Stage F is too close to the requested supplement tail: "
            f"gap={initial_gap}, minimum={minimum_initial_gap}"
        )
    collision_stop_completed_tasks = tail_start_index - collision_guard_tasks
    if collision_stop_completed_tasks <= formal_completed_upper_bound:
        raise RuntimeError("collision stop threshold is already reached")

    raw_tail_ids = pdb_ids[tail_start_index:]
    selected_ids = [
        pdb_id
        for pdb_id in raw_tail_ids
        if pdb_id not in exclusions
        and stage_e_statuses[pdb_id]["status"] in _ELIGIBLE_UPSTREAM_STATUSES
    ]
    if not selected_ids:
        raise RuntimeError("supplement tail contains no Stage E eligible PDB ids")

    trio_counts = {"complete": 0, "partial": 0, "missing": 0}
    for pdb_id in selected_ids:
        trio_paths = (
            root / "quality" / f"{pdb_id}.jsonl",
            root / "quality" / f"{pdb_id}.provenance.json",
            root / "quality_atoms" / f"{pdb_id}.npz",
        )
        existing_count = sum(path.is_file() and not path.is_symlink() for path in trio_paths)
        if existing_count == len(trio_paths):
            trio_counts["complete"] += 1
        elif existing_count:
            trio_counts["partial"] += 1
        else:
            trio_counts["missing"] += 1

    ids_path = evidence_dir / "pdb_ids.txt"
    ids_payload = "".join(f"{pdb_id}\n" for pdb_id in selected_ids).encode("utf-8")
    _write_immutable(ids_path, ids_payload)
    ids_sha256 = sha256_file(ids_path)
    summary_path = evidence_dir / "plan.json"
    summary: dict[str, Any] = {
        "schema_version": 1,
        "event": "stage_f_remote_tail_supplement_plan",
        "decision_scope": "current_run_only",
        "scientific_contract_changed": False,
        "formal_run_id": formal_run_id,
        "supplement_run_id": supplement_run_id,
        "formal_job_id": formal_job_id,
        "pair_list_path": str(pair_list_path),
        "pair_list_sha256": pair_list_sha256,
        "universe_count": len(pdb_ids),
        "stage_e_status_paths": [str(path) for path in stage_e_paths],
        "stage_f_exclusion_ids": sorted(exclusions),
        "stage_f_exclusions_sha256": exclusions_sha256,
        "tail_start_index_zero_based": tail_start_index,
        "tail_end_index_exclusive": len(pdb_ids),
        "tail_requested_count": tail_count,
        "tail_selected_count": len(selected_ids),
        "tail_removed_exclusion_count": sum(
            pdb_id in exclusions for pdb_id in raw_tail_ids
        ),
        "tail_removed_stage_e_ineligible_count": sum(
            stage_e_statuses[pdb_id]["status"] not in _ELIGIBLE_UPSTREAM_STATUSES
            for pdb_id in raw_tail_ids
            if pdb_id not in exclusions
        ),
        "formal_completed_upper_bound_at_plan": formal_completed_upper_bound,
        "initial_task_gap": initial_gap,
        "minimum_initial_task_gap": minimum_initial_gap,
        "collision_guard_tasks": collision_guard_tasks,
        "collision_stop_completed_tasks": collision_stop_completed_tasks,
        "pdb_ids_path": str(ids_path),
        "pdb_ids_sha256": ids_sha256,
        "quality_trio_counts_at_plan": trio_counts,
        "resource_contract": {
            "formal_cpu": 96,
            "supplement_cpu": 96,
            "main_cpu_total": 192,
            "reserve_cpu": 48,
            "supplement_outer_n_jobs": 12,
            "mapq_np_per_pdb": 8,
        },
        "authorization": (
            "user_explicit_2026-07-15_main_cpu_192_plus_48_test_or_backup"
        ),
        "writer_boundary": (
            "supplement writes common quality trio and its independent run status only; "
            "formal job remains the sole formal status/release writer"
        ),
    }
    summary_payload = (
        json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    _write_immutable(summary_path, summary_payload)
    return summary


def _require_regular_file(path: Path, label: str) -> None:
    """要求输入是非符号链接普通文件，避免计划身份被运行中替换。"""
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} must be a regular non-symlink file: {path}")


def _write_immutable(path: Path, payload: bytes) -> None:
    """首次原子写入；已存在时只接受逐字节相同内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        _require_regular_file(path, "immutable evidence")
        if path.read_bytes() != payload:
            raise RuntimeError(f"immutable evidence drift: {path}")
        return
    temporary = path.with_name(f"{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        raise RuntimeError(f"stale evidence temporary file: {temporary}")
    temporary.write_bytes(payload)
    atomic_replace(temporary, path)
