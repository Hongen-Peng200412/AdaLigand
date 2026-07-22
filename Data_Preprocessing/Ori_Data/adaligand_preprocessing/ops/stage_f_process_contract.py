# 供回收和受控失败门禁共用的 Stage F 进程证据契约。
# 主要输入：canonical process-audit JSON、预期 SHA、精确 Job ID 与可选新鲜度上限。
# 主要输出：经过结构、实现身份、节点、调度快照和零进程证明验证的 audit 对象。
# 关键边界：本模块不导入 quality/Chimera/MapQ，也不执行进程扫描或修改锁。
"""Stage F canonical 零 writer 进程审计的轻量共用验证器。"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shlex
from typing import Any, Iterable

from adaligand_preprocessing.ops.stage_f_processes import (
    PROCESS_AUDIT_SCHEMA_VERSION,
    PROCESS_PROBE_CONTRACT,
    PROCESS_PROBE_SCHEMA_VERSION,
    implementation_identity,
    normalize_opaque_process_specs,
    partition_authorized_opaque_processes,
    validate_opaque_process_rows,
)


def validate_process_audit(
    process_audit_path: Path,
    expected_sha256: str,
    job_ids: list[int],
    *,
    max_age_seconds: float | None = 900,
) -> dict[str, Any]:
    """
    验证登录节点和各 allocation 的 canonical 零 writer 证据。

    ``max_age_seconds=None`` 只关闭时间新鲜度门，仍完整验证 schema、代码身份、
    scheduler snapshot、probe 命令/输出和零进程分区。该模式仅供已经绑定成功
    ``f_release`` 的后续 G 重验历史证据。
    """
    if not process_audit_path.is_file() or process_audit_path.is_symlink():
        raise RuntimeError(f"process audit must be a regular file: {process_audit_path}")
    payload = process_audit_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError("process audit SHA-256 mismatch")
    try:
        audit = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("process audit must be valid UTF-8 JSON") from exc
    if not isinstance(audit, dict):
        raise RuntimeError("process audit must be a JSON object")
    job_checks = audit.get("job_checks")
    controller_check = audit.get("controller_check")
    scheduler_snapshot = audit.get("scheduler_snapshot")
    try:
        capture_started_at = _parse_aware_time(
            audit.get("capture_started_at"),
            label="capture_started_at",
        )
        captured_at = _parse_aware_time(audit.get("captured_at"), label="captured_at")
        age_seconds = (datetime.now(timezone.utc) - capture_started_at).total_seconds()
    except RuntimeError:
        capture_started_at = captured_at = datetime.min.replace(tzinfo=timezone.utc)
        age_seconds = float("inf")
    try:
        authorized_specs = normalize_opaque_process_specs(
            audit.get("authorized_controller_opaque_specs", [])
        )
    except (TypeError, ValueError):
        authorized_specs = [{"invalid": True}]
    if (
        audit.get("schema_version") != PROCESS_AUDIT_SCHEMA_VERSION
        or audit.get("status") != "success"
        or (
            max_age_seconds is not None
            and not -60 <= age_seconds <= max_age_seconds
        )
        or sorted(int(item) for item in audit.get("job_ids", [])) != sorted(job_ids)
        or int(audit.get("active_stage_f_processes", -1)) != 0
        or int(audit.get("active_inventory_or_cleanup_processes", -1)) != 0
        or int(audit.get("active_opaque_stdin_python_processes", -1)) != 0
        or int(audit.get("scan_error_count", -1)) != 0
        or not isinstance(job_checks, dict)
        or not isinstance(controller_check, dict)
        or not isinstance(audit.get("controller_node"), str)
        or not audit["controller_node"]
        or set(job_checks) != {str(job_id) for job_id in job_ids}
        or not isinstance(audit.get("job_nodes"), dict)
        or set(audit["job_nodes"]) != {str(job_id) for job_id in job_ids}
        or audit.get("scheduler_exit_code") != 0
        or not isinstance(scheduler_snapshot, str)
        or _sha256_text(scheduler_snapshot) != audit.get("scheduler_snapshot_sha256")
    ):
        raise RuntimeError(f"process audit does not prove a stopped writer set: {audit}")
    if audit["controller_node"].split(".", 1)[0].lower() in {
        str(node).split(".", 1)[0].lower() for node in audit["job_nodes"].values()
    }:
        raise RuntimeError("process audit controller overlaps an allocation node")
    expected_identity = _expected_process_probe_identity()
    if any(audit.get(key) != value for key, value in expected_identity.items()):
        raise RuntimeError("process audit implementation identity mismatch")
    controller_node = audit["controller_node"]
    controller_partition = _validate_zero_process_check(
        controller_check,
        label="controller",
        expected_node=controller_node,
        expected_scope="controller",
        expected_identity=expected_identity,
        authorized_opaque_specs=authorized_specs,
    )
    check_times = [
        (
            _parse_aware_time(controller_check["started_at"], label="controller started_at"),
            _parse_aware_time(controller_check["completed_at"], label="controller completed_at"),
        )
    ]
    job_partitions: list[dict[str, list[dict[str, Any]]]] = []
    for job_id in job_ids:
        check = job_checks.get(str(job_id))
        expected_node = audit["job_nodes"].get(str(job_id))
        job_partition = _validate_zero_process_check(
            check,
            label=f"job {job_id}",
            expected_node=expected_node,
            expected_scope="allocation",
            expected_identity=expected_identity,
            expected_job_id=job_id,
        )
        job_partitions.append(job_partition)
        check_times.append(
            (
                _parse_aware_time(check["started_at"], label=f"job {job_id} started_at"),
                _parse_aware_time(check["completed_at"], label=f"job {job_id} completed_at"),
            )
        )
    observed_rows = [
        *controller_partition["observed"],
        *(row for partition in job_partitions for row in partition["observed"]),
    ]
    if (
        audit.get("observed_opaque_stdin_python_processes") != len(observed_rows)
        or audit.get("authorized_controller_opaque_processes")
        != controller_partition["authorized"]
        or audit.get("blocking_controller_opaque_processes")
        != controller_partition["blocking"]
        or audit.get("authorized_controller_opaque_specs") != authorized_specs
    ):
        raise RuntimeError("process audit opaque exception partition mismatch")
    if (
        capture_started_at > min(start for start, _end in check_times)
        or max(end for _start, end in check_times) > captured_at
        or captured_at < capture_started_at
    ):
        raise RuntimeError("process audit capture window is inconsistent")
    return audit


def _expected_process_probe_identity() -> dict[str, str]:
    """返回当前 checkout 中受信 probe 入口和模块的内容身份。"""
    script_path = Path(__file__).resolve().parents[1] / "cli" / "stage_f_process_audit.py"
    if not script_path.is_file() or script_path.is_symlink():
        raise RuntimeError(f"process probe script must be a regular file: {script_path}")
    return implementation_identity(script_path)


def _parse_aware_time(value: Any, *, label: str) -> datetime:
    """解析必须携带时区的证据时间。"""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid process audit timestamp for {label}: {value}") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"process audit timestamp lacks timezone for {label}: {value}")
    return parsed.astimezone(timezone.utc)


def _validate_zero_process_check(
    check: Any,
    *,
    label: str,
    expected_node: str,
    expected_scope: str,
    expected_identity: dict[str, str],
    expected_job_id: int | None = None,
    authorized_opaque_specs: Iterable[dict[str, Any]] = (),
) -> dict[str, list[dict[str, Any]]]:
    """闭合验证一个节点；只允许 controller 上精确指纹匹配的 opaque 例外。"""
    if not isinstance(check, dict):
        raise RuntimeError(f"invalid process audit check for {label}: {check}")
    command = check.get("probe_command")
    output = check.get("probe_output")
    stderr = check.get("probe_stderr")
    probe_argv = check.get("probe_argv")
    try:
        probe = json.loads(output) if isinstance(output, str) else None
    except json.JSONDecodeError:
        probe = None
    expected_script = (
        Path(__file__).resolve().parents[1] / "cli" / "stage_f_process_audit.py"
    ).resolve()
    try:
        started_at = _parse_aware_time(check.get("started_at"), label=f"{label} started_at")
        completed_at = _parse_aware_time(check.get("completed_at"), label=f"{label} completed_at")
    except RuntimeError:
        started_at = completed_at = datetime.min.replace(tzinfo=timezone.utc)
    identity_matches = all(
        check.get(key) == expected_identity[key]
        and isinstance(probe, dict)
        and probe.get(key) == expected_identity[key]
        for key in ("probe_contract", "probe_script_sha256", "probe_module_sha256")
    )
    argv_shape_matches = (
        isinstance(probe_argv, list)
        and all(isinstance(item, str) and item for item in probe_argv)
        and (
            (expected_scope == "controller" and len(probe_argv) == 3)
            or (
                expected_scope == "allocation"
                and len(probe_argv) == 10
                and probe_argv[0] == "srun"
            )
        )
        and Path(probe_argv[-3]).name.lower().startswith("python")
        and Path(probe_argv[-2]).resolve() == expected_script
        and probe_argv[-1] == "probe"
    )
    opaque_rows = probe.get("opaque_stdin_python_processes") if isinstance(probe, dict) else None
    try:
        validated_opaque_rows = validate_opaque_process_rows(
            opaque_rows if isinstance(opaque_rows, list) else []
        )
        authorized_rows, blocking_rows = partition_authorized_opaque_processes(
            validated_opaque_rows,
            authorized_opaque_specs,
            node=expected_node,
        )
    except (TypeError, ValueError):
        authorized_rows = []
        blocking_rows = [{"error": "invalid_opaque_partition"}]
    opaque_count = len(opaque_rows) if isinstance(opaque_rows, list) else -1
    zero_count_fields = ("active_stage_f_processes", "active_inventory_or_cleanup_processes")
    zero_process_lists = ("stage_f_processes", "inventory_or_cleanup_processes")
    allocation_markers = ("srun", f"--jobid={expected_job_id}", f"--nodelist={expected_node}")
    valid = (
        isinstance(expected_node, str)
        and bool(expected_node)
        and check.get("scope") == expected_scope
        and check.get("job_id") == expected_job_id
        and check.get("node") == expected_node
        and check.get("reported_node") == expected_node
        and check.get("probe_exit_code") == 0
        and started_at <= completed_at
        and argv_shape_matches
        and isinstance(command, str)
        and bool(command.strip())
        and command == shlex.join(probe_argv)
        and "stage_f_process_audit.py" in command
        and "probe" in command
        and (
            expected_scope != "allocation"
            or all(marker in probe_argv for marker in allocation_markers)
        )
        and isinstance(output, str)
        and isinstance(stderr, str)
        and stderr == ""
        and _sha256_text(command) == check.get("probe_command_sha256")
        and _sha256_text(output) == check.get("probe_output_sha256")
        and _sha256_text(stderr) == check.get("probe_stderr_sha256")
        and isinstance(probe, dict)
        and probe.get("schema_version") == PROCESS_PROBE_SCHEMA_VERSION
        and probe.get("probe_contract") == PROCESS_PROBE_CONTRACT
        and probe.get("node") == expected_node
        and type(probe.get("uid")) is int
        and int(probe["uid"]) >= 0
        and identity_matches
        and all(check.get(field) == 0 and probe.get(field) == 0 for field in zero_count_fields)
        and all(isinstance(probe.get(field), list) and not probe[field] for field in zero_process_lists)
        and check.get("active_opaque_stdin_python_processes") == opaque_count
        and probe.get("active_opaque_stdin_python_processes") == opaque_count
        and not blocking_rows
        and check.get("scan_error_count") == 0
        and probe.get("scan_error_count") == 0
        and isinstance(probe.get("scan_errors"), list)
        and not probe["scan_errors"]
    )
    if not valid:
        raise RuntimeError(f"invalid process audit check for {label}: {check}")
    return {
        "observed": opaque_rows,
        "authorized": authorized_rows,
        "blocking": blocking_rows,
    }


def _sha256_text(value: str) -> str:
    """按 UTF-8 计算命令或输出正文 SHA-256。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
