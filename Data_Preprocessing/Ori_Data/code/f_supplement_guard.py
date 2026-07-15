"""Stage F 远尾补算运行时守卫：绑定计划身份并在正式任务接近时停止。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
from typing import Any, Sequence

from io_utils import atomic_replace, sha256_file
from reports import resolve_run_id


COLLISION_GUARD_EXIT_CODE = 75
_DONE_PATTERN = re.compile(rb"Done\s+(\d+)\s+tasks")


class _SupervisorSignal(Exception):
    """把外层 TERM/INT 转为可执行 finally 清理的内部控制流。"""

    def __init__(self, signum: int):
        super().__init__(f"supplement supervisor received signal {signum}")
        self.signum = signum


def validate_supplement_guard_contract(
    plan_path: Path,
    ids_path: Path,
    *,
    formal_run_id: str,
    supplement_run_id: str,
    formal_job_id: int,
    formal_log_path: Path,
    n_jobs: int,
) -> dict[str, Any]:
    """交叉验证计划、冻结 ID 与实际运行环境，返回规范化计划。"""
    _require_regular_file(plan_path, "supplement plan")
    _require_regular_file(ids_path, "supplement PDB id list")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise ValueError("unsupported supplement plan schema")
    if plan.get("event") != "stage_f_remote_tail_supplement_plan":
        raise ValueError("unexpected supplement plan event")
    expected_values = {
        "formal_run_id": resolve_run_id(formal_run_id),
        "supplement_run_id": resolve_run_id(supplement_run_id),
        "formal_job_id": formal_job_id,
        "pdb_ids_sha256": sha256_file(ids_path),
    }
    drift = {
        field: {"expected": expected, "actual": plan.get(field)}
        for field, expected in expected_values.items()
        if plan.get(field) != expected
    }
    if drift:
        raise RuntimeError(f"supplement plan identity drift: {drift}")
    if Path(str(plan.get("pdb_ids_path", ""))).resolve() != ids_path.resolve():
        raise RuntimeError("supplement plan points to a different PDB id file")
    formal_log_path = formal_log_path.resolve()
    _require_regular_file(formal_log_path, "formal Stage F stderr log")
    if Path(str(plan.get("formal_log_path", ""))).resolve() != formal_log_path:
        raise RuntimeError("supplement plan points to a different formal Stage F log")
    formal_log_stat = formal_log_path.stat()
    if plan.get("formal_log_device") != formal_log_stat.st_dev:
        raise RuntimeError("formal Stage F log device identity drift")
    if plan.get("formal_log_inode") != formal_log_stat.st_ino:
        raise RuntimeError("formal Stage F log inode identity drift")
    observed_at_plan = plan.get("formal_completed_observed_at_plan")
    if not isinstance(observed_at_plan, int) or observed_at_plan <= 0:
        raise ValueError("formal progress observed at plan time must be positive")
    current_observed = latest_formal_completed_tasks(formal_log_path)
    if current_observed <= 0:
        raise RuntimeError("formal Stage F log lost its current joblib progress")

    expected_resource_contract = {
        "formal_cpu": 96,
        "supplement_cpu": 96,
        "main_cpu_total": 192,
        "reserve_cpu": 48,
        "supplement_outer_n_jobs": 12,
        "mapq_np_per_pdb": 8,
    }
    if plan.get("resource_contract") != expected_resource_contract:
        raise RuntimeError("supplement resource contract drift")
    if n_jobs != expected_resource_contract["supplement_outer_n_jobs"]:
        raise RuntimeError("supplement n_jobs must remain 12 for CPU96/MapQ np=8")

    tail_start = plan.get("tail_start_index_zero_based")
    stop_at = plan.get("collision_stop_completed_tasks")
    guard_tasks = plan.get("collision_guard_tasks")
    if not all(isinstance(value, int) for value in (tail_start, stop_at, guard_tasks)):
        raise ValueError("supplement collision fields must be integers")
    if stop_at <= 0 or guard_tasks <= 0 or tail_start - stop_at != guard_tasks:
        raise ValueError("supplement collision threshold is inconsistent")
    return plan


def latest_formal_completed_tasks(
    log_path: Path,
    *,
    tail_bytes: int = 8 * 1024 * 1024,
) -> int:
    """
    读取正式 F 日志最后一个 joblib ``Done N tasks``，忽略旧 attempt 的更大历史值。

    日志采用追加模式；正式作业在 try-lock 恢复后计数会从零开始，因此必须取最后一条，
    不能对整份日志求最大值。
    """
    _require_regular_file(log_path, "formal Stage F stderr log")
    with log_path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - tail_bytes))
        payload = handle.read()
    matches = _DONE_PATTERN.findall(payload)
    return int(matches[-1]) if matches else 0


def supervise_f_supplement(
    command: Sequence[str],
    *,
    plan: dict[str, Any],
    plan_path: Path,
    ids_path: Path,
    formal_log_path: Path,
    stop_marker_path: Path,
    poll_seconds: float,
    termination_grace_seconds: float,
) -> int:
    """运行补算命令，并在正式进度达到冻结阈值时终止整个补算进程组。"""
    if not command:
        raise ValueError("supplement command cannot be empty")
    if poll_seconds <= 0 or termination_grace_seconds <= 0:
        raise ValueError("guard timing values must be positive")
    _require_regular_file(formal_log_path, "formal Stage F stderr log")
    if stop_marker_path.exists() or stop_marker_path.is_symlink():
        raise RuntimeError(f"supplement guard marker already exists: {stop_marker_path}")

    stop_at = int(plan["collision_stop_completed_tasks"])
    current_done = latest_formal_completed_tasks(formal_log_path)
    if current_done >= stop_at:
        _write_stop_marker(
            stop_marker_path,
            plan=plan,
            plan_path=plan_path,
            ids_path=ids_path,
            formal_log_path=formal_log_path,
            completed_tasks=current_done,
            process_started=False,
        )
        return COLLISION_GUARD_EXIT_CODE

    process = subprocess.Popen(list(command), start_new_session=True)
    previous_handlers: dict[signal.Signals, Any] = {}

    def _raise_supervisor_signal(signum: int, _frame: Any) -> None:
        raise _SupervisorSignal(signum)

    try:
        for current_signal in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[current_signal] = signal.getsignal(current_signal)
            signal.signal(current_signal, _raise_supervisor_signal)
        while True:
            try:
                return process.wait(timeout=poll_seconds)
            except subprocess.TimeoutExpired:
                current_done = latest_formal_completed_tasks(formal_log_path)
                if current_done < stop_at:
                    continue
                _terminate_process_group(process, grace_seconds=termination_grace_seconds)
                _write_stop_marker(
                    stop_marker_path,
                    plan=plan,
                    plan_path=plan_path,
                    ids_path=ids_path,
                    formal_log_path=formal_log_path,
                    completed_tasks=current_done,
                    process_started=True,
                )
                return COLLISION_GUARD_EXIT_CODE
    except _SupervisorSignal as exc:
        _terminate_process_group(process, grace_seconds=termination_grace_seconds)
        return 128 + exc.signum
    except BaseException:
        _terminate_process_group(process, grace_seconds=termination_grace_seconds)
        raise
    finally:
        for current_signal, previous_handler in previous_handlers.items():
            signal.signal(current_signal, previous_handler)


def _terminate_process_group(process: subprocess.Popen[Any], *, grace_seconds: float) -> None:
    """先 TERM、后 KILL 补算独立进程组，避免遗留 Loky/Chimera/MapQ 子进程。"""
    if process.poll() is not None:
        return
    if os.name != "posix":
        process.terminate()
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name != "posix":
        process.kill()
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait()


def _write_stop_marker(
    path: Path,
    *,
    plan: dict[str, Any],
    plan_path: Path,
    ids_path: Path,
    formal_log_path: Path,
    completed_tasks: int,
    process_started: bool,
) -> None:
    """原子记录守卫停止事实；该证据不伪造补算成功或正式 Stage F 状态。"""
    payload = {
        "schema_version": 1,
        "event": "stage_f_supplement_collision_guard_stop",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "formal_run_id": plan["formal_run_id"],
        "supplement_run_id": plan["supplement_run_id"],
        "formal_job_id": plan["formal_job_id"],
        "formal_completed_tasks": completed_tasks,
        "collision_stop_completed_tasks": plan["collision_stop_completed_tasks"],
        "collision_guard_tasks": plan["collision_guard_tasks"],
        "process_started": process_started,
        "plan_path": str(plan_path),
        "plan_sha256": sha256_file(plan_path),
        "pdb_ids_path": str(ids_path),
        "pdb_ids_sha256": sha256_file(ids_path),
        "formal_log_path": str(formal_log_path),
        "result": "supplement_stopped_without_formal_status_or_release_mutation",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    atomic_replace(temporary, path)


def _require_regular_file(path: Path, label: str) -> None:
    """拒绝缺失文件、目录和符号链接。"""
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} must be a regular non-symlink file: {path}")
