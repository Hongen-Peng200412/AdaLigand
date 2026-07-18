"""Stage F 远尾补算运行时守卫：绑定计划身份并在正式任务接近时停止。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import stat as stat_module
import subprocess
import time
from typing import Any, Callable, Sequence

from io_utils import atomic_replace, sha256_file
from reports import resolve_run_id


COLLISION_GUARD_EXIT_CODE = 75
FORMAL_HOLD_GUARD_EXIT_CODE = 76
_DONE_PATTERN = re.compile(rb"Done\s+(\d+)\s+tasks")
_STOP_MARKER_FIELDS = frozenset(
    {
        "schema_version",
        "event",
        "recorded_at",
        "formal_run_id",
        "supplement_run_id",
        "formal_job_id",
        "formal_completed_tasks",
        "collision_stop_completed_tasks",
        "collision_guard_tasks",
        "process_started",
        "plan_path",
        "plan_sha256",
        "pdb_ids_path",
        "pdb_ids_sha256",
        "formal_log_path",
        "result",
    }
)
_FORMAL_HOLD_STOP_MARKER_FIELDS = frozenset(
    {
        "schema_version",
        "event",
        "recorded_at",
        "formal_run_id",
        "supplement_run_id",
        "formal_job_id",
        "process_started",
        "plan_path",
        "plan_sha256",
        "pdb_ids_path",
        "pdb_ids_sha256",
        "formal_log_path",
        "formal_hold_contract",
        "last_successful_hold_check",
        "violation",
        "result",
    }
)
_FORMAL_HOLD_SNAPSHOT_FIELDS = frozenset(
    {
        "schema_version",
        "event",
        "checked_at",
        "formal_job_id",
        "formal_node",
        "lock_state_before",
        "lock_state_after",
        "probe_argv",
        "probe_outcome",
        "probe_exit_code",
        "probe_stdout",
        "probe_stderr",
        "probe_payload",
        "blockers",
        "status",
    }
)


class _SupervisorSignal(Exception):
    """把外层 TERM/INT 转为可执行 finally 清理的内部控制流。"""

    def __init__(self, signum: int):
        super().__init__(f"supplement supervisor received signal {signum}")
        self.signum = signum


class FormalHoldViolation(RuntimeError):
    """表示正式 Stage F 的冻结锁或零 writer 条件已经漂移。"""

    def __init__(self, snapshot: dict[str, Any]):
        blockers = snapshot.get("blockers", [])
        super().__init__(f"formal Stage F hold drift: {blockers}")
        self.snapshot = snapshot


class FormalHoldMonitor:
    """持续核验正式 allocation 处于 after+try 冻结且没有 Stage F writer。"""

    def __init__(
        self,
        *,
        formal_job_id: int,
        formal_node: str,
        lock_root: Path,
        probe_argv: Sequence[str],
        expected_probe_contract: str,
        expected_probe_script_sha256: str,
        expected_probe_module_sha256: str,
        probe_timeout_seconds: float = 120.0,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        """
        冻结 formal-held 守卫身份。

        Args:
            formal_job_id: 被 hold 的正式 Slurm Job ID。
            formal_node: 正式 allocation 所在节点短名。
            lock_root: 精确锁目录；只读取本 Job 的五个路径。
            probe_argv: 进入正式 allocation 执行 canonical process probe 的 argv。
            expected_probe_contract: process probe 契约标识。
            expected_probe_script_sha256: canonical probe 入口 SHA-256。
            expected_probe_module_sha256: canonical probe 模块 SHA-256。
            probe_timeout_seconds: 单次只读 probe 超时秒数。
            command_runner: 测试可替换的只读命令执行器。
        """
        if formal_job_id <= 0 or not formal_node:
            raise ValueError("formal hold requires a positive job ID and a node")
        if not probe_argv or probe_timeout_seconds <= 0:
            raise ValueError("formal hold probe command and timeout must be positive")
        for digest in (expected_probe_script_sha256, expected_probe_module_sha256):
            if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("formal hold probe SHA-256 must be lowercase hexadecimal")
        self.formal_job_id = int(formal_job_id)
        self.formal_node = formal_node
        self.lock_root = lock_root.resolve()
        self.probe_argv = tuple(str(value) for value in probe_argv)
        self.expected_probe_contract = expected_probe_contract
        self.expected_probe_script_sha256 = expected_probe_script_sha256
        self.expected_probe_module_sha256 = expected_probe_module_sha256
        self.probe_timeout_seconds = float(probe_timeout_seconds)
        self._command_runner = command_runner
        self._baseline_lock_snapshot: dict[str, Any] | None = None

    def identity(self) -> dict[str, Any]:
        """返回 stop marker 可逐字段复核的 formal-held 身份。"""
        return {
            "schema_version": 1,
            "formal_job_id": self.formal_job_id,
            "formal_node": self.formal_node,
            "lock_root": str(self.lock_root),
            "probe_argv": list(self.probe_argv),
            "probe_contract": self.expected_probe_contract,
            "probe_script_sha256": self.expected_probe_script_sha256,
            "probe_module_sha256": self.expected_probe_module_sha256,
        }

    def check(self) -> dict[str, Any]:
        """在 probe 前后各读一次精确锁，并要求正式 allocation 零 writer。"""
        checked_at = datetime.now(timezone.utc).isoformat()
        lock_state_before = _formal_hold_lock_snapshot(
            self.lock_root,
            self.formal_job_id,
        )
        blockers = _formal_hold_lock_blockers(lock_state_before)
        if (
            self._baseline_lock_snapshot is not None
            and lock_state_before != self._baseline_lock_snapshot
        ):
            blockers.append("formal_hold_lock_identity_drift_before_probe")
        probe_exit_code = 126
        probe_stdout = ""
        probe_stderr = ""
        probe_payload: dict[str, Any] = {}
        probe_outcome = "launch_failed"
        try:
            completed = self._command_runner(
                list(self.probe_argv),
                text=True,
                capture_output=True,
                check=False,
                timeout=self.probe_timeout_seconds,
            )
            probe_exit_code = int(completed.returncode)
            probe_stdout = completed.stdout
            probe_stderr = completed.stderr
            probe_outcome = "completed"
        except subprocess.TimeoutExpired as exc:
            probe_exit_code = 124
            probe_stdout = _timeout_text(exc.stdout)
            probe_stderr = _timeout_text(exc.stderr)
            probe_outcome = "timeout"
            blockers.append("formal_process_probe_timeout")
        except OSError as exc:
            probe_stderr = f"{type(exc).__name__}: {exc}"
            blockers.append("formal_process_probe_launch_failed")

        try:
            parsed = json.loads(probe_stdout)
            if isinstance(parsed, dict):
                probe_payload = parsed
            else:
                blockers.append("formal_process_probe_not_object")
        except json.JSONDecodeError:
            blockers.append("formal_process_probe_invalid_json")

        lock_state_after = _formal_hold_lock_snapshot(
            self.lock_root,
            self.formal_job_id,
        )
        blockers.extend(_formal_hold_lock_blockers(lock_state_after))
        if lock_state_before != lock_state_after:
            blockers.append("formal_hold_lock_changed_during_probe")
        if (
            self._baseline_lock_snapshot is not None
            and lock_state_after != self._baseline_lock_snapshot
        ):
            blockers.append("formal_hold_lock_identity_drift_after_probe")

        expected_probe_fields = {
            "node": self.formal_node,
            "probe_contract": self.expected_probe_contract,
            "probe_script_sha256": self.expected_probe_script_sha256,
            "probe_module_sha256": self.expected_probe_module_sha256,
            "active_stage_f_processes": 0,
            "active_inventory_or_cleanup_processes": 0,
            "active_opaque_stdin_python_processes": 0,
            "scan_error_count": 0,
        }
        if probe_exit_code != 0:
            blockers.append(f"formal_process_probe_exit_{probe_exit_code}")
        if probe_stderr:
            blockers.append("formal_process_probe_stderr_nonempty")
        for field, expected in expected_probe_fields.items():
            actual = probe_payload.get(field)
            if field == "node" and isinstance(actual, str):
                actual = actual.split(".", 1)[0].lower()
                expected = str(expected).split(".", 1)[0].lower()
            if actual != expected:
                blockers.append(f"formal_process_probe_{field}_drift")

        snapshot = {
            "schema_version": 1,
            "event": "stage_f_formal_hold_check",
            "checked_at": checked_at,
            "formal_job_id": self.formal_job_id,
            "formal_node": self.formal_node,
            "lock_state_before": lock_state_before,
            "lock_state_after": lock_state_after,
            "probe_argv": list(self.probe_argv),
            "probe_outcome": probe_outcome,
            "probe_exit_code": probe_exit_code,
            "probe_stdout": probe_stdout,
            "probe_stderr": probe_stderr,
            "probe_payload": probe_payload,
            "blockers": sorted(set(blockers)),
            "status": "success" if not blockers else "blocked",
        }
        blockers = _formal_hold_snapshot_expected_blockers(
            snapshot,
            monitor=self,
            baseline_lock_snapshot=self._baseline_lock_snapshot,
        )
        snapshot["blockers"] = blockers
        snapshot["status"] = "success" if not blockers else "blocked"
        if blockers:
            raise FormalHoldViolation(snapshot)
        if self._baseline_lock_snapshot is None:
            self._baseline_lock_snapshot = lock_state_after
        return snapshot


def _formal_hold_snapshot_expected_blockers(
    snapshot: dict[str, Any],
    *,
    monitor: FormalHoldMonitor,
    baseline_lock_snapshot: dict[str, Any] | None,
) -> list[str]:
    """仅由快照正文重算 formal-held 阻断原因，供生产与 marker 复核共用。"""
    before = snapshot["lock_state_before"]
    after = snapshot["lock_state_after"]
    blockers = [
        *_formal_hold_lock_blockers(before),
        *_formal_hold_lock_blockers(after),
    ]
    if before != after:
        blockers.append("formal_hold_lock_changed_during_probe")
    if baseline_lock_snapshot is not None and before != baseline_lock_snapshot:
        blockers.append("formal_hold_lock_identity_drift_before_probe")
    if baseline_lock_snapshot is not None and after != baseline_lock_snapshot:
        blockers.append("formal_hold_lock_identity_drift_after_probe")

    outcome = snapshot["probe_outcome"]
    if outcome == "timeout":
        blockers.append("formal_process_probe_timeout")
    elif outcome == "launch_failed":
        blockers.append("formal_process_probe_launch_failed")
    elif outcome != "completed":
        blockers.append("formal_process_probe_outcome_drift")
    try:
        parsed = json.loads(snapshot["probe_stdout"])
    except json.JSONDecodeError:
        parsed = None
        blockers.append("formal_process_probe_invalid_json")
    if parsed is not None and not isinstance(parsed, dict):
        blockers.append("formal_process_probe_not_object")
    if parsed != snapshot["probe_payload"]:
        blockers.append("formal_process_probe_payload_drift")
    if snapshot["probe_exit_code"] != 0:
        blockers.append(f"formal_process_probe_exit_{snapshot['probe_exit_code']}")
    if snapshot["probe_stderr"]:
        blockers.append("formal_process_probe_stderr_nonempty")

    expected_probe_fields = {
        "node": monitor.formal_node,
        "probe_contract": monitor.expected_probe_contract,
        "probe_script_sha256": monitor.expected_probe_script_sha256,
        "probe_module_sha256": monitor.expected_probe_module_sha256,
        "active_stage_f_processes": 0,
        "active_inventory_or_cleanup_processes": 0,
        "active_opaque_stdin_python_processes": 0,
        "scan_error_count": 0,
    }
    payload = snapshot["probe_payload"]
    for field, expected in expected_probe_fields.items():
        actual = payload.get(field) if isinstance(payload, dict) else None
        if field == "node" and isinstance(actual, str):
            actual = actual.split(".", 1)[0].lower()
            expected = str(expected).split(".", 1)[0].lower()
        if actual != expected:
            blockers.append(f"formal_process_probe_{field}_drift")
    return sorted(set(blockers))


def _validate_formal_hold_lock_snapshot(snapshot: Any) -> None:
    """验证五个精确路径的状态、inode 元数据与小锁内容哈希。"""
    expected_names = {"after", "try", "kill", "pre", "child_pgid"}
    if not isinstance(snapshot, dict) or set(snapshot) != expected_names:
        raise ValueError("formal-held lock snapshot field drift")
    for name, row in snapshot.items():
        if not isinstance(row, dict) or "state" not in row:
            raise ValueError(f"formal-held lock row is invalid: {name}")
        state = row["state"]
        if state == "regular":
            expected = {"state", "device", "inode", "size", "mtime_ns", "sha256"}
            if set(row) != expected:
                raise ValueError(f"formal-held regular lock metadata drift: {name}")
            if (
                any(type(row[field]) is not int or row[field] < 0 for field in (
                    "device",
                    "inode",
                    "size",
                    "mtime_ns",
                ))
                or re.fullmatch(r"[0-9a-f]{64}", str(row["sha256"])) is None
            ):
                raise ValueError(f"formal-held regular lock identity is invalid: {name}")
        elif state in {
            "absent",
            "unexpected_symlink",
            "unexpected_nonfile",
            "unexpected_scan_error",
            "unexpected_identity_race",
        }:
            if set(row) != {"state"}:
                raise ValueError(f"formal-held nonregular lock metadata drift: {name}")
        else:
            raise ValueError(f"formal-held lock state is unsupported: {name}={state}")


def _validate_formal_hold_snapshot(
    snapshot: Any,
    *,
    monitor: FormalHoldMonitor,
    expected_status: str,
    baseline_lock_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    """逐字段复核 marker 内嵌的锁、probe 原文、解析正文与阻断原因。"""
    if not isinstance(snapshot, dict) or set(snapshot) != _FORMAL_HOLD_SNAPSHOT_FIELDS:
        raise ValueError("formal-held snapshot field drift")
    expected_identity = {
        "schema_version": 1,
        "event": "stage_f_formal_hold_check",
        "formal_job_id": monitor.formal_job_id,
        "formal_node": monitor.formal_node,
        "probe_argv": list(monitor.probe_argv),
    }
    drift = {
        field: {"expected": expected, "actual": snapshot.get(field)}
        for field, expected in expected_identity.items()
        if snapshot.get(field) != expected
    }
    if drift:
        raise RuntimeError(f"formal-held snapshot identity drift: {drift}")
    checked_at = snapshot["checked_at"]
    if not isinstance(checked_at, str):
        raise ValueError("formal-held snapshot checked_at must be ISO-8601")
    try:
        checked_time = datetime.fromisoformat(checked_at)
    except ValueError as exc:
        raise ValueError("formal-held snapshot checked_at is invalid") from exc
    if checked_time.tzinfo is None:
        raise ValueError("formal-held snapshot checked_at needs a timezone")
    for name in ("lock_state_before", "lock_state_after"):
        _validate_formal_hold_lock_snapshot(snapshot[name])
    if type(snapshot["probe_exit_code"]) is not int:
        raise ValueError("formal-held probe exit code must be an integer")
    if not all(isinstance(snapshot[name], str) for name in (
        "probe_outcome",
        "probe_stdout",
        "probe_stderr",
    )):
        raise ValueError("formal-held probe text fields are invalid")
    expected_blockers = _formal_hold_snapshot_expected_blockers(
        snapshot,
        monitor=monitor,
        baseline_lock_snapshot=baseline_lock_snapshot,
    )
    if snapshot["blockers"] != expected_blockers:
        raise RuntimeError("formal-held snapshot blocker recomputation drift")
    expected_from_blockers = "blocked" if expected_blockers else "success"
    if snapshot["status"] != expected_status or expected_status != expected_from_blockers:
        raise RuntimeError("formal-held snapshot status drift")
    return snapshot


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


def validate_supplement_stop_marker(
    marker_path: Path,
    *,
    plan: dict[str, Any],
    plan_path: Path,
    ids_path: Path,
    formal_log_path: Path,
) -> dict[str, Any]:
    """验证退出码 75 对应的停止证据与当前冻结输入逐字段绑定。"""
    _require_regular_file(plan_path, "supplement plan")
    _require_regular_file(ids_path, "supplement PDB id list")
    _require_regular_file(formal_log_path, "formal Stage F stderr log")
    _require_regular_file(marker_path, "supplement collision stop marker")
    if Path(str(plan.get("pdb_ids_path", ""))).resolve() != ids_path.resolve():
        raise RuntimeError("supplement plan PDB id path drift during marker validation")
    if plan.get("pdb_ids_sha256") != sha256_file(ids_path):
        raise RuntimeError("supplement plan PDB id hash drift during marker validation")
    if Path(str(plan.get("formal_log_path", ""))).resolve() != formal_log_path.resolve():
        raise RuntimeError("supplement plan formal log path drift during marker validation")
    formal_log_stat = formal_log_path.stat()
    if (
        plan.get("formal_log_device") != formal_log_stat.st_dev
        or plan.get("formal_log_inode") != formal_log_stat.st_ino
    ):
        raise RuntimeError("supplement plan formal log identity drift during marker validation")
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("supplement collision stop marker must be a JSON object")
    if set(payload) != _STOP_MARKER_FIELDS:
        missing = sorted(_STOP_MARKER_FIELDS - set(payload))
        extra = sorted(set(payload) - _STOP_MARKER_FIELDS)
        raise ValueError(f"supplement stop marker field drift: missing={missing}, extra={extra}")

    expected_scalars = {
        "schema_version": 1,
        "event": "stage_f_supplement_collision_guard_stop",
        "formal_run_id": plan["formal_run_id"],
        "supplement_run_id": plan["supplement_run_id"],
        "formal_job_id": plan["formal_job_id"],
        "collision_stop_completed_tasks": plan["collision_stop_completed_tasks"],
        "collision_guard_tasks": plan["collision_guard_tasks"],
        "plan_sha256": sha256_file(plan_path),
        "pdb_ids_sha256": sha256_file(ids_path),
        "result": "supplement_stopped_without_formal_status_or_release_mutation",
    }
    drift = {
        field: {"expected": expected, "actual": payload.get(field)}
        for field, expected in expected_scalars.items()
        if payload.get(field) != expected
    }
    if drift:
        raise RuntimeError(f"supplement stop marker identity drift: {drift}")

    expected_paths = {
        "plan_path": plan_path.resolve(),
        "pdb_ids_path": ids_path.resolve(),
        "formal_log_path": formal_log_path.resolve(),
    }
    for field, expected_path in expected_paths.items():
        if Path(str(payload[field])).resolve() != expected_path:
            raise RuntimeError(f"supplement stop marker {field} drift")

    completed_tasks = payload["formal_completed_tasks"]
    if type(completed_tasks) is not int:
        raise ValueError("supplement stop marker formal_completed_tasks must be an integer")
    if completed_tasks < int(plan["collision_stop_completed_tasks"]):
        raise RuntimeError("supplement stop marker was written before the collision threshold")
    if type(payload["process_started"]) is not bool:
        raise ValueError("supplement stop marker process_started must be a boolean")

    recorded_at = payload["recorded_at"]
    if not isinstance(recorded_at, str):
        raise ValueError("supplement stop marker recorded_at must be an ISO-8601 string")
    try:
        recorded_time = datetime.fromisoformat(recorded_at)
    except ValueError as exc:
        raise ValueError("supplement stop marker recorded_at is not valid ISO-8601") from exc
    if recorded_time.tzinfo is None:
        raise ValueError("supplement stop marker recorded_at must include a timezone")
    return payload


def validate_formal_hold_stop_marker(
    marker_path: Path,
    *,
    plan: dict[str, Any],
    plan_path: Path,
    ids_path: Path,
    formal_log_path: Path,
    monitor: FormalHoldMonitor,
) -> dict[str, Any]:
    """复核 formal-held 漂移 marker，不把历史 Done 阈值当成停止依据。"""
    _require_regular_file(plan_path, "supplement plan")
    _require_regular_file(ids_path, "supplement PDB id list")
    _require_regular_file(formal_log_path, "formal Stage F stderr log")
    _require_regular_file(marker_path, "supplement formal-hold stop marker")
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("supplement formal-hold stop marker must be a JSON object")
    if set(payload) != _FORMAL_HOLD_STOP_MARKER_FIELDS:
        missing = sorted(_FORMAL_HOLD_STOP_MARKER_FIELDS - set(payload))
        extra = sorted(set(payload) - _FORMAL_HOLD_STOP_MARKER_FIELDS)
        raise ValueError(
            f"supplement formal-hold marker field drift: missing={missing}, extra={extra}"
        )
    expected_scalars = {
        "schema_version": 2,
        "event": "stage_f_supplement_formal_hold_guard_stop",
        "formal_run_id": plan["formal_run_id"],
        "supplement_run_id": plan["supplement_run_id"],
        "formal_job_id": plan["formal_job_id"],
        "plan_sha256": sha256_file(plan_path),
        "pdb_ids_sha256": sha256_file(ids_path),
        "formal_hold_contract": monitor.identity(),
        "result": "supplement_stopped_after_formal_hold_drift",
    }
    drift = {
        field: {"expected": expected, "actual": payload.get(field)}
        for field, expected in expected_scalars.items()
        if payload.get(field) != expected
    }
    if drift:
        raise RuntimeError(f"supplement formal-hold marker identity drift: {drift}")
    expected_paths = {
        "plan_path": plan_path.resolve(),
        "pdb_ids_path": ids_path.resolve(),
        "formal_log_path": formal_log_path.resolve(),
    }
    for field, expected_path in expected_paths.items():
        if Path(str(payload[field])).resolve() != expected_path:
            raise RuntimeError(f"supplement formal-hold marker {field} drift")
    if type(payload["process_started"]) is not bool:
        raise ValueError("supplement formal-hold marker process_started must be boolean")
    last_success = payload["last_successful_hold_check"]
    baseline_lock_snapshot = None
    if last_success is not None:
        validated_success = _validate_formal_hold_snapshot(
            last_success,
            monitor=monitor,
            expected_status="success",
            baseline_lock_snapshot=None,
        )
        baseline_lock_snapshot = validated_success["lock_state_after"]
    _validate_formal_hold_snapshot(
        payload["violation"],
        monitor=monitor,
        expected_status="blocked",
        baseline_lock_snapshot=baseline_lock_snapshot,
    )
    recorded_at = payload["recorded_at"]
    if not isinstance(recorded_at, str):
        raise ValueError("supplement formal-hold marker recorded_at must be ISO-8601")
    try:
        recorded_time = datetime.fromisoformat(recorded_at)
    except ValueError as exc:
        raise ValueError(
            "supplement formal-hold marker recorded_at is not valid ISO-8601"
        ) from exc
    if recorded_time.tzinfo is None:
        raise ValueError("supplement formal-hold marker recorded_at needs a timezone")
    return payload


def supervise_f_supplement(
    command: Sequence[str],
    *,
    plan: dict[str, Any],
    plan_path: Path,
    ids_path: Path,
    formal_log_path: Path,
    stop_marker_path: Path,
    child_pgid_path: Path,
    poll_seconds: float,
    termination_grace_seconds: float,
    launcher_command: Sequence[str] | None = None,
    formal_hold_monitor: FormalHoldMonitor | None = None,
) -> int:
    """运行补算；默认看进度阈值，显式 formal-held 模式改看锁与零 writer。"""
    if not command:
        raise ValueError("supplement command cannot be empty")
    if poll_seconds <= 0 or termination_grace_seconds <= 0:
        raise ValueError("guard timing values must be positive")
    _require_regular_file(formal_log_path, "formal Stage F stderr log")
    if stop_marker_path.exists() or stop_marker_path.is_symlink():
        raise RuntimeError(f"supplement guard marker already exists: {stop_marker_path}")
    if child_pgid_path.exists() or child_pgid_path.is_symlink():
        raise RuntimeError(f"supplement child PGID file already exists: {child_pgid_path}")

    stop_at = int(plan["collision_stop_completed_tasks"])
    last_successful_hold_check: dict[str, Any] | None = None
    if formal_hold_monitor is None:
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
    else:
        if formal_hold_monitor.formal_job_id != int(plan["formal_job_id"]):
            raise RuntimeError("formal-held monitor Job ID differs from supplement plan")
        try:
            last_successful_hold_check = formal_hold_monitor.check()
        except FormalHoldViolation as exc:
            write_formal_hold_stop_marker(
                stop_marker_path,
                plan=plan,
                plan_path=plan_path,
                ids_path=ids_path,
                formal_log_path=formal_log_path,
                monitor=formal_hold_monitor,
                process_started=False,
                last_successful_hold_check=None,
                violation=exc.snapshot,
            )
            return FORMAL_HOLD_GUARD_EXIT_CODE

    previous_handlers: dict[signal.Signals, Any] = {}
    process: subprocess.Popen[Any] | None = None
    handled_signals = (signal.SIGTERM, signal.SIGINT)

    def _raise_supervisor_signal(signum: int, _frame: Any) -> None:
        raise _SupervisorSignal(signum)

    try:
        for current_signal in handled_signals:
            previous_handlers[current_signal] = signal.getsignal(current_signal)
            signal.signal(current_signal, _raise_supervisor_signal)

        # POSIX 上先屏蔽 TERM/INT；只有 PGID 登记与启动令牌都完成后才恢复信号。
        # 这样 pending signal 一经解除就会进入统一清理路径，不会留下未登记的工作负载。
        previous_mask: set[signal.Signals] | None = None
        if os.name == "posix":
            previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, handled_signals)
        try:
            try:
                startup_options: dict[str, Any] = {}
                if formal_hold_monitor is not None:
                    startup_options["before_release_check"] = formal_hold_monitor.check
                process = _start_registered_process(
                    command,
                    child_pgid_path=child_pgid_path,
                    launcher_command=launcher_command,
                    child_signal_mask=previous_mask,
                    termination_grace_seconds=termination_grace_seconds,
                    **startup_options,
                )
            except FormalHoldViolation as exc:
                write_formal_hold_stop_marker(
                    stop_marker_path,
                    plan=plan,
                    plan_path=plan_path,
                    ids_path=ids_path,
                    formal_log_path=formal_log_path,
                    monitor=formal_hold_monitor,
                    process_started=False,
                    last_successful_hold_check=last_successful_hold_check,
                    violation=exc.snapshot,
                )
                return FORMAL_HOLD_GUARD_EXIT_CODE
        finally:
            if previous_mask is not None:
                signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

        while True:
            try:
                child_exit = process.wait(timeout=poll_seconds)
                if child_exit == COLLISION_GUARD_EXIT_CODE:
                    raise RuntimeError(
                        "supplement child returned reserved collision-guard exit code 75"
                    )
                if child_exit == FORMAL_HOLD_GUARD_EXIT_CODE:
                    raise RuntimeError(
                        "supplement child returned reserved formal-hold exit code 76"
                    )
                if child_exit == 0 and formal_hold_monitor is not None:
                    try:
                        last_successful_hold_check = formal_hold_monitor.check()
                    except FormalHoldViolation as exc:
                        write_formal_hold_stop_marker(
                            stop_marker_path,
                            plan=plan,
                            plan_path=plan_path,
                            ids_path=ids_path,
                            formal_log_path=formal_log_path,
                            monitor=formal_hold_monitor,
                            process_started=True,
                            last_successful_hold_check=last_successful_hold_check,
                            violation=exc.snapshot,
                        )
                        return FORMAL_HOLD_GUARD_EXIT_CODE
                return child_exit
            except subprocess.TimeoutExpired:
                if formal_hold_monitor is not None:
                    try:
                        last_successful_hold_check = formal_hold_monitor.check()
                    except FormalHoldViolation as exc:
                        _terminate_process_group(
                            process,
                            grace_seconds=termination_grace_seconds,
                        )
                        write_formal_hold_stop_marker(
                            stop_marker_path,
                            plan=plan,
                            plan_path=plan_path,
                            ids_path=ids_path,
                            formal_log_path=formal_log_path,
                            monitor=formal_hold_monitor,
                            process_started=True,
                            last_successful_hold_check=last_successful_hold_check,
                            violation=exc.snapshot,
                        )
                        return FORMAL_HOLD_GUARD_EXIT_CODE
                    continue
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
        return 128 + exc.signum
    finally:
        cleanup_succeeded = False
        try:
            if process is not None:
                _terminate_process_group(process, grace_seconds=termination_grace_seconds)
                cleanup_succeeded = True
            else:
                # 启动器若在登记后抛错，调用表达式尚未完成赋值；此时必须保留登记给外层兜底。
                cleanup_succeeded = not child_pgid_path.exists()
        finally:
            for current_signal, previous_handler in previous_handlers.items():
                signal.signal(current_signal, previous_handler)
            # 只有确认整个独立进程组消失后才能撤销登记；失败时保留给 helper/core 兜底。
            if cleanup_succeeded:
                child_pgid_path.unlink(missing_ok=True)


def _start_registered_process(
    command: Sequence[str],
    *,
    child_pgid_path: Path,
    launcher_command: Sequence[str] | None,
    child_signal_mask: set[signal.Signals] | None,
    termination_grace_seconds: float,
    before_release_check: Callable[[], Any] | None = None,
) -> subprocess.Popen[Any]:
    """启动独立进程组，并保证真实工作负载晚于 PGID 原子登记。"""
    if os.name != "posix":
        if before_release_check is not None:
            before_release_check()
        process = subprocess.Popen(list(command), start_new_session=True)
        try:
            _write_child_pgid(child_pgid_path, process.pid)
        except BaseException:
            _terminate_process_group(process, grace_seconds=termination_grace_seconds)
            raise
        return process

    if not launcher_command:
        raise ValueError("POSIX supplement supervision requires a startup-barrier launcher")
    restored_signal_mask = ",".join(
        str(int(current_signal)) for current_signal in sorted(child_signal_mask or set())
    )
    barrier_read_fd, barrier_release_fd = os.pipe()
    process: subprocess.Popen[Any] | None = None
    try:
        launcher_argv = [
            *launcher_command,
            "_launch_after_barrier",
            "--barrier-fd",
            str(barrier_read_fd),
            "--restore-signal-mask",
            restored_signal_mask,
            "--",
            *command,
        ]
        process = subprocess.Popen(
            launcher_argv,
            start_new_session=True,
            pass_fds=(barrier_read_fd,),
        )
        os.close(barrier_read_fd)
        barrier_read_fd = -1
        _write_child_pgid(child_pgid_path, process.pid)
        if before_release_check is not None:
            before_release_check()
        if os.write(barrier_release_fd, b"R") != 1:
            raise RuntimeError("failed to release supplement startup barrier")
        os.close(barrier_release_fd)
        barrier_release_fd = -1
        return process
    except BaseException:
        for descriptor in (barrier_read_fd, barrier_release_fd):
            if descriptor >= 0:
                os.close(descriptor)
        if process is not None:
            _terminate_process_group(process, grace_seconds=termination_grace_seconds)
        raise


def _terminate_process_group(process: subprocess.Popen[Any], *, grace_seconds: float) -> None:
    """无论 leader 是否已退出，先 TERM、后 KILL 整个补算独立进程组。"""
    if os.name != "posix":
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return

    _terminate_posix_process_group(
        process.pid,
        grace_seconds=grace_seconds,
        direct_process=process,
    )
    if process.poll() is None:
        process.wait(timeout=grace_seconds)


def reap_registered_process_group(
    child_pgid_path: Path,
    *,
    expected_child_pgid_path: Path,
    grace_seconds: float,
) -> int:
    """受检回收登记进程组；仅在整组消失后删除精确 PGID 文件。"""
    if os.name != "posix":
        raise RuntimeError("registered process-group reaping is supported only on POSIX")
    if grace_seconds <= 0:
        raise ValueError("registered process-group grace period must be positive")
    if child_pgid_path.resolve() != expected_child_pgid_path.resolve():
        raise RuntimeError("registered child PGID path differs from the expected exact path")
    process_group_id = _read_registered_process_group(child_pgid_path)
    if process_group_id == os.getpgrp():
        raise RuntimeError("refusing to reap the current process group")

    _terminate_posix_process_group(process_group_id, grace_seconds=grace_seconds)
    # 防止回收期间目录项被替换；不匹配时保留文件并交由人工审计。
    if _read_registered_process_group(child_pgid_path) != process_group_id:
        raise RuntimeError("registered child PGID changed during reaping")
    child_pgid_path.unlink()
    return process_group_id


def _terminate_posix_process_group(
    process_group_id: int,
    *,
    grace_seconds: float,
    direct_process: subprocess.Popen[Any] | None = None,
) -> None:
    """按 PGID 而不是 leader 存活状态回收整个 POSIX 进程组。"""
    if process_group_id <= 1:
        raise ValueError("unsafe supplement child process group id")
    if direct_process is not None:
        direct_process.poll()
    if not _process_group_is_alive(process_group_id):
        return
    _signal_process_group(process_group_id, signal.SIGTERM)
    if _wait_for_process_group_exit(
        process_group_id,
        timeout_seconds=grace_seconds,
        direct_process=direct_process,
    ):
        return
    _signal_process_group(process_group_id, signal.SIGKILL)
    if not _wait_for_process_group_exit(
        process_group_id,
        timeout_seconds=grace_seconds,
        direct_process=direct_process,
    ):
        raise RuntimeError(f"supplement process group {process_group_id} survived SIGKILL")


def _signal_process_group(process_group_id: int, current_signal: signal.Signals) -> None:
    """向精确进程组发信号；组已自然消失视为成功。"""
    try:
        os.killpg(process_group_id, current_signal)
    except ProcessLookupError:
        return


def _process_group_is_alive(process_group_id: int) -> bool:
    """使用 killpg(0) 判断 leader 已退出后仍可能存活的组成员。"""
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for_process_group_exit(
    process_group_id: int,
    *,
    timeout_seconds: float,
    direct_process: subprocess.Popen[Any] | None = None,
) -> bool:
    """每轮先回收直属 leader，再短间隔等待进程组消失。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        # Popen.poll() 内部使用 waitpid(WNOHANG)。若不先回收已退出 leader，
        # killpg(0) 会持续看见 zombie 所属 PGID，并把正常 TERM 误判成卡死。
        if direct_process is not None:
            direct_process.poll()
        if not _process_group_is_alive(process_group_id):
            return True
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    if direct_process is not None:
        direct_process.poll()
    return not _process_group_is_alive(process_group_id)


def _read_registered_process_group(path: Path) -> int:
    """读取普通非链接 PGID 文件，并拒绝额外字段与危险值。"""
    _require_regular_file(path, "supplement child PGID registration")
    raw_value = path.read_text(encoding="ascii")
    if not re.fullmatch(r"[0-9]+\n?", raw_value):
        raise ValueError("supplement child PGID registration must contain one integer")
    process_group_id = int(raw_value)
    if process_group_id <= 1:
        raise ValueError("unsafe supplement child process group id")
    return process_group_id


def _formal_hold_lock_snapshot(lock_root: Path, formal_job_id: int) -> dict[str, Any]:
    """只读取正式 Job 的 after/try/kill/pre/child_pgid 五个精确路径。"""
    paths = {
        "after": lock_root / f"after_lock_{formal_job_id}",
        "try": lock_root / f"try_lock_{formal_job_id}",
        "kill": lock_root / f"kill_lock_{formal_job_id}",
        "pre": lock_root / f"pre_lock_{formal_job_id}",
        "child_pgid": lock_root / f"child_pgid_{formal_job_id}",
    }
    states: dict[str, Any] = {}
    for name, path in paths.items():
        try:
            stat_before = path.lstat()
        except FileNotFoundError:
            states[name] = {"state": "absent"}
            continue
        except OSError:
            states[name] = {"state": "unexpected_scan_error"}
            continue
        if stat_module.S_ISLNK(stat_before.st_mode):
            states[name] = {"state": "unexpected_symlink"}
            continue
        if not stat_module.S_ISREG(stat_before.st_mode):
            states[name] = {"state": "unexpected_nonfile"}
            continue
        try:
            digest = sha256_file(path)
            stat_after = path.lstat()
        except OSError:
            states[name] = {"state": "unexpected_scan_error"}
            continue
        identity_before = (
            stat_before.st_dev,
            stat_before.st_ino,
            stat_before.st_size,
            stat_before.st_mtime_ns,
        )
        identity_after = (
            stat_after.st_dev,
            stat_after.st_ino,
            stat_after.st_size,
            stat_after.st_mtime_ns,
        )
        if identity_before != identity_after:
            states[name] = {"state": "unexpected_identity_race"}
            continue
        states[name] = {
            "state": "regular",
            "device": stat_after.st_dev,
            "inode": stat_after.st_ino,
            "size": stat_after.st_size,
            "mtime_ns": stat_after.st_mtime_ns,
            "sha256": digest,
        }
    return states


def _formal_hold_lock_blockers(states: dict[str, Any]) -> list[str]:
    """把 formal-held 锁快照转换为稳定、可审计的阻断原因。"""
    expected = {
        "after": "regular",
        "try": "regular",
        "kill": "absent",
        "pre": "absent",
        "child_pgid": "absent",
    }
    return [
        f"formal_{name}_{states.get(name, {}).get('state', 'missing')}_expected_{wanted}"
        for name, wanted in expected.items()
        if states.get(name, {}).get("state") != wanted
    ]


def _timeout_text(value: str | bytes | None) -> str:
    """规范化 ``TimeoutExpired`` 携带的可选文本。"""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def write_formal_hold_stop_marker(
    path: Path,
    *,
    plan: dict[str, Any],
    plan_path: Path,
    ids_path: Path,
    formal_log_path: Path,
    monitor: FormalHoldMonitor,
    process_started: bool,
    last_successful_hold_check: dict[str, Any] | None,
    violation: dict[str, Any],
) -> None:
    """原子记录 formal-held 漂移，不伪造补算 release 或正式 Stage F 状态。"""
    payload = {
        "schema_version": 2,
        "event": "stage_f_supplement_formal_hold_guard_stop",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "formal_run_id": plan["formal_run_id"],
        "supplement_run_id": plan["supplement_run_id"],
        "formal_job_id": plan["formal_job_id"],
        "process_started": process_started,
        "plan_path": str(plan_path.resolve()),
        "plan_sha256": sha256_file(plan_path),
        "pdb_ids_path": str(ids_path.resolve()),
        "pdb_ids_sha256": sha256_file(ids_path),
        "formal_log_path": str(formal_log_path.resolve()),
        "formal_hold_contract": monitor.identity(),
        "last_successful_hold_check": last_successful_hold_check,
        "violation": violation,
        "result": "supplement_stopped_after_formal_hold_drift",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    atomic_replace(temporary, path)


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
        "plan_path": str(plan_path.resolve()),
        "plan_sha256": sha256_file(plan_path),
        "pdb_ids_path": str(ids_path.resolve()),
        "pdb_ids_sha256": sha256_file(ids_path),
        "formal_log_path": str(formal_log_path.resolve()),
        "result": "supplement_stopped_without_formal_status_or_release_mutation",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    atomic_replace(temporary, path)


def _write_child_pgid(path: Path, process_group_id: int) -> None:
    """为 opt-in core 原子登记独立补算进程组，供真实 kill-lock 先行收割。"""
    if process_group_id <= 1:
        raise ValueError("unsafe supplement child process group id")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    temporary.write_text(f"{process_group_id}\n", encoding="ascii")
    temporary.chmod(0o600)
    atomic_replace(temporary, path)


def _require_regular_file(path: Path, label: str) -> None:
    """拒绝缺失文件、目录和符号链接。"""
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} must be a regular non-symlink file: {path}")
