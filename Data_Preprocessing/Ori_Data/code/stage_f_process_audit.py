"""生成 Stage F scratch 回收前的跨节点零进程证据。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from io_utils import sha256_file
from reports import write_report


PROCESS_AUDIT_SCHEMA_VERSION = 2
PROCESS_PROBE_SCHEMA_VERSION = 1
PROCESS_PROBE_CONTRACT = "adaligand_stage_f_process_probe_v1"
_PYTHON_EXECUTABLE = re.compile(r"^python(?:\d+(?:\.\d+)*)?(?:\.exe)?$")
_STAGE_F_TOKENS = (
    "f_quality.py",
    "popen_loky",
    "loky.backend",
    "lokyprocess",
    "/chimera",
    "chimera ",
    "mapq_cmd.py",
    "mapq_v2",
)
_RECOVERY_TOKENS = (
    "stage_f_scratch_recovery.py",
    "stage_f_scratch_recovery_20260716",
    "adaligand_stage_f_inventory",
    ".adaligand_stage_f_inventory",
    "stage_f_process_audit.py",
    "_cleanup_quality_attempt_transients",
)


def is_opaque_stdin_python(argv: list[str]) -> bool:
    """判断 Python 是否从 stdin 读取无法由 ``/proc`` 还原的正文。"""
    if not argv:
        return False
    executable = Path(argv[0]).name.lower()
    if _PYTHON_EXECUTABLE.fullmatch(executable) is None:
        return False
    arguments = argv[1:]
    if not arguments:
        return True
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "-":
            return True
        if argument == "--":
            return index + 1 < len(arguments) and arguments[index + 1] == "-"
        if argument in {"-c", "-m"} or (len(argument) > 2 and argument[:2] in {"-c", "-m"}):
            return False
        if argument in {"-W", "-X"}:
            index += 2
            continue
        if argument.startswith("-"):
            index += 1
            continue
        return False
    return True


def _read_process_argv(proc_dir: Path) -> list[str]:
    """读取一个 proc 目录的 NUL 分隔 argv；内核线程与已退出进程返回空列表。"""
    payload = (proc_dir / "cmdline").read_bytes()
    return [part.decode("utf-8", errors="replace") for part in payload.split(b"\0") if part]


def _read_process_ppid(proc_dir: Path) -> int:
    """从 Linux ``/proc/<pid>/stat`` 读取父 PID。"""
    text = (proc_dir / "stat").read_text(encoding="utf-8")
    tail = text[text.rfind(")") + 2 :].split()
    return int(tail[1])


def _read_process_uid(proc_dir: Path) -> int:
    """从 ``status`` 的 real UID 判断进程归属。"""
    for line in (proc_dir / "status").read_text(encoding="utf-8").splitlines():
        if line.startswith("Uid:"):
            return int(line.split()[1])
    raise RuntimeError(f"process status lacks Uid: {proc_dir}")


def _ancestor_pids(proc_root: Path, self_pid: int) -> set[int]:
    """返回探针自身及同一节点可见的祖先 PID，避免把探针链误报为活动任务。"""
    excluded: set[int] = set()
    pid = self_pid
    while pid > 1 and pid not in excluded:
        excluded.add(pid)
        try:
            pid = _read_process_ppid(proc_root / str(pid))
        except (FileNotFoundError, PermissionError, RuntimeError, ValueError, IndexError):
            break
    return excluded


def scan_owned_processes(
    *,
    proc_root: Path = Path("/proc"),
    uid: int | None = None,
    self_pid: int | None = None,
    node: str | None = None,
) -> dict[str, Any]:
    """扫描当前节点同一用户的 Stage F、回收器与不透明 stdin Python 进程。"""
    owner_uid = os.getuid() if uid is None else int(uid)
    probe_pid = os.getpid() if self_pid is None else int(self_pid)
    excluded = _ancestor_pids(proc_root, probe_pid)
    trust_proc_directory_uid = proc_root == Path("/proc")
    stage_rows: list[dict[str, Any]] = []
    recovery_rows: list[dict[str, Any]] = []
    opaque_rows: list[dict[str, Any]] = []
    scan_errors: list[dict[str, Any]] = []
    for proc_dir in sorted(
        (path for path in proc_root.iterdir() if path.name.isdigit()),
        key=lambda path: int(path.name),
    ):
        pid = int(proc_dir.name)
        if pid in excluded:
            continue
        if trust_proc_directory_uid:
            try:
                if proc_dir.stat().st_uid != owner_uid:
                    continue
            except (FileNotFoundError, ProcessLookupError):
                continue
            except (PermissionError, OSError) as exc:
                scan_errors.append(
                    {"pid": pid, "error_type": type(exc).__name__, "error": str(exc)}
                )
                continue
        try:
            process_uid = _read_process_uid(proc_dir)
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (PermissionError, RuntimeError, ValueError, OSError) as exc:
            scan_errors.append({"pid": pid, "error_type": type(exc).__name__, "error": str(exc)})
            continue
        if process_uid != owner_uid:
            continue
        try:
            argv = _read_process_argv(proc_dir)
        except (FileNotFoundError, ProcessLookupError):
            continue
        except (PermissionError, RuntimeError, ValueError, OSError) as exc:
            scan_errors.append({"pid": pid, "error_type": type(exc).__name__, "error": str(exc)})
            continue
        if not argv:
            continue
        command = " ".join(argv)
        lower = command.lower()
        try:
            ppid = _read_process_ppid(proc_dir)
        except (FileNotFoundError, PermissionError, RuntimeError, ValueError, IndexError):
            ppid = None
        row = {"pid": pid, "ppid": ppid, "argv": argv, "command": command}
        if any(token in lower for token in _STAGE_F_TOKENS):
            stage_rows.append(row)
        if any(token in lower for token in _RECOVERY_TOKENS):
            recovery_rows.append(row)
        if is_opaque_stdin_python(argv):
            opaque_rows.append(row)
    return {
        "schema_version": PROCESS_PROBE_SCHEMA_VERSION,
        "probe_contract": PROCESS_PROBE_CONTRACT,
        "node": node or socket.gethostname(),
        "uid": owner_uid,
        "active_stage_f_processes": len(stage_rows),
        "active_inventory_or_cleanup_processes": len(recovery_rows),
        "active_opaque_stdin_python_processes": len(opaque_rows),
        "scan_error_count": len(scan_errors),
        "stage_f_processes": stage_rows,
        "inventory_or_cleanup_processes": recovery_rows,
        "opaque_stdin_python_processes": opaque_rows,
        "scan_errors": scan_errors,
    }


def implementation_identity(script_path: Path) -> dict[str, str]:
    """返回探针薄入口与本模块的内容哈希，供证据和远端代码复核。"""
    return {
        "probe_contract": PROCESS_PROBE_CONTRACT,
        "probe_script_sha256": sha256_file(script_path),
        "probe_module_sha256": sha256_file(Path(__file__).resolve()),
    }


def probe_payload(script_path: Path) -> dict[str, Any]:
    """生成当前节点的自包含探针正文。"""
    return {**scan_owned_processes(), **implementation_identity(script_path)}


def _sha256_text(value: str) -> str:
    """按 UTF-8 计算命令或输出正文摘要。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _run_text(argv: list[str], *, timeout_seconds: float = 120.0) -> tuple[int, str, str]:
    """运行受检命令并返回退出码、stdout、stderr。"""
    try:
        completed = subprocess.run(
            argv,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else exc.stdout
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr
        return 124, stdout or "", (stderr or "") + f"\nprobe_timeout_seconds={timeout_seconds}\n"
    return int(completed.returncode), completed.stdout, completed.stderr


def _build_process_check(
    argv: list[str],
    expected_node: str,
    *,
    scope: str,
    job_id: int | None = None,
) -> dict[str, Any]:
    """运行一次固定 probe 子命令并冻结命令、输出与解析计数。"""
    started_at = datetime.now(timezone.utc).isoformat()
    exit_code, stdout, stderr = _run_text(argv)
    completed_at = datetime.now(timezone.utc).isoformat()
    command = shlex.join(argv)
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    def count(name: str) -> int:
        """把格式异常的计数稳定降级为 blocked 证据。"""
        value = payload.get(name)
        return value if type(value) is int else -1

    return {
        "scope": scope,
        "job_id": job_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "node": expected_node,
        "reported_node": payload.get("node"),
        "active_stage_f_processes": count("active_stage_f_processes"),
        "active_inventory_or_cleanup_processes": count(
            "active_inventory_or_cleanup_processes"
        ),
        "active_opaque_stdin_python_processes": count(
            "active_opaque_stdin_python_processes"
        ),
        "scan_error_count": count("scan_error_count"),
        "probe_contract": payload.get("probe_contract"),
        "probe_script_sha256": payload.get("probe_script_sha256"),
        "probe_module_sha256": payload.get("probe_module_sha256"),
        "probe_exit_code": exit_code,
        "probe_argv": argv,
        "probe_command": command,
        "probe_command_sha256": _sha256_text(command),
        "probe_output": stdout,
        "probe_output_sha256": _sha256_text(stdout),
        "probe_stderr": stderr,
        "probe_stderr_sha256": _sha256_text(stderr),
    }


def _scheduler_command(job_ids: list[int], lock_root: Path) -> str:
    """构造同时包含 Slurm 状态与精确四锁的只读快照命令。"""
    joined = ",".join(str(job_id) for job_id in job_ids)
    jobs = " ".join(str(job_id) for job_id in job_ids)
    quoted_lock_root = shlex.quote(str(lock_root))
    return "\n".join(
        [
            "set -o pipefail",
            'printf \'captured_scheduler_at=%s\\n\' "$(date --iso-8601=seconds)"',
            f"squeue -j {joined} -o '%i|%T|%N|%C|%M|%R'",
            f"sacct -j {joined} --format=JobIDRaw,State,ExitCode,NodeList,Elapsed -n -P",
            f"for job in {jobs}; do",
            '  printf \'job=%s\' "$job"',
            "  for kind in after try kill pre; do",
            f'    path={quoted_lock_root}"/${{kind}}_lock_${{job}}"',
            '    if test -f "$path" && test ! -L "$path"; then',
            '      printf \'|%s=regular\' "$kind"',
            '    elif test -e "$path" || test -L "$path"; then',
            '      printf \'|%s=unexpected\' "$kind"',
            "    else",
            '      printf \'|%s=absent\' "$kind"',
            "    fi",
            "  done",
            "  echo",
            "done",
        ]
    )


def capture_process_audit(
    output_path: Path,
    *,
    jobs: Iterable[tuple[int, str]],
    script_path: Path,
    lock_root: Path,
    expected_controller_node: str,
) -> dict[str, Any]:
    """从登录节点和每个保留 allocation 生成一次原子 process-audit 证据。"""
    job_rows = sorted((int(job_id), str(node)) for job_id, node in jobs)
    if not job_rows or len({job_id for job_id, _node in job_rows}) != len(job_rows):
        raise ValueError("jobs must be a non-empty set of unique job IDs")
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError(f"process audit output already exists: {output_path}")
    controller_node = socket.gethostname()
    if (
        not expected_controller_node
        or controller_node.split(".", 1)[0].lower()
        != expected_controller_node.split(".", 1)[0].lower()
    ):
        raise RuntimeError(
            "process audit must run on the expected controller: "
            f"actual={controller_node} expected={expected_controller_node}"
        )
    if any(
        node.split(".", 1)[0].lower() == controller_node.split(".", 1)[0].lower()
        for _job_id, node in job_rows
    ):
        raise RuntimeError("controller node must not also be an allocation node")
    capture_started_at = datetime.now(timezone.utc).isoformat()
    identity = implementation_identity(script_path)
    python = str(Path(sys.executable).resolve())
    script = str(script_path.resolve())
    job_checks: dict[str, dict[str, Any]] = {}
    for job_id, node in job_rows:
        argv = [
            "srun",
            "--overlap",
            f"--jobid={job_id}",
            "--nodes=1",
            "--ntasks=1",
            "--cpus-per-task=1",
            f"--nodelist={node}",
            python,
            script,
            "probe",
        ]
        job_checks[str(job_id)] = _build_process_check(
            argv,
            node,
            scope="allocation",
            job_id=job_id,
        )
    scheduler_command = _scheduler_command([job_id for job_id, _node in job_rows], lock_root)
    scheduler_exit, scheduler_stdout, scheduler_stderr = _run_text(["bash", "-lc", scheduler_command])
    # scheduler 快照后最后检查登录节点，最大限度缩短 controller 证据到落盘的时间窗。
    controller_check = _build_process_check(
        [python, script, "probe"],
        controller_node,
        scope="controller",
    )
    checks = [controller_check, *job_checks.values()]
    stage_count = sum(int(check["active_stage_f_processes"]) for check in checks)
    recovery_count = sum(int(check["active_inventory_or_cleanup_processes"]) for check in checks)
    opaque_count = sum(int(check["active_opaque_stdin_python_processes"]) for check in checks)
    scan_error_count = sum(int(check["scan_error_count"]) for check in checks)
    all_checks_ok = all(
        int(check["probe_exit_code"]) == 0
        and check.get("reported_node") == check.get("node")
        and check.get("probe_contract") == identity["probe_contract"]
        and check.get("probe_script_sha256") == identity["probe_script_sha256"]
        and check.get("probe_module_sha256") == identity["probe_module_sha256"]
        and int(check.get("scan_error_count", -1)) == 0
        and check.get("probe_stderr") == ""
        for check in checks
    )
    snapshot = (
        f"$ {scheduler_command}\n\n[stdout]\n{scheduler_stdout}"
        f"\n[stderr]\n{scheduler_stderr}"
    )
    audit = {
        "schema_version": PROCESS_AUDIT_SCHEMA_VERSION,
        "status": "success"
        if all_checks_ok
        and scheduler_exit == 0
        and stage_count == recovery_count == opaque_count == scan_error_count == 0
        else "blocked",
        "captured_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "capture_started_at": capture_started_at,
        "job_ids": [job_id for job_id, _node in job_rows],
        "job_nodes": {str(job_id): node for job_id, node in job_rows},
        "controller_node": controller_node,
        **identity,
        "active_stage_f_processes": stage_count,
        "active_inventory_or_cleanup_processes": recovery_count,
        "active_opaque_stdin_python_processes": opaque_count,
        "scan_error_count": scan_error_count,
        "scheduler_exit_code": scheduler_exit,
        "scheduler_snapshot": snapshot,
        "scheduler_snapshot_sha256": _sha256_text(snapshot),
        "controller_check": controller_check,
        "job_checks": job_checks,
    }
    write_report(output_path, audit)
    return audit
