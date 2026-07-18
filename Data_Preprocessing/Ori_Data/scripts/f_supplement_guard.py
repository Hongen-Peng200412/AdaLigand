"""执行带正式进度碰撞守卫的 Stage F 独立远尾补算命令。"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from f_supplement_guard import (
    COLLISION_GUARD_EXIT_CODE,
    FORMAL_HOLD_GUARD_EXIT_CODE,
    FormalHoldViolation,
    FormalHoldMonitor,
    reap_registered_process_group,
    supervise_f_supplement,
    validate_formal_hold_stop_marker,
    validate_supplement_guard_contract,
    validate_supplement_stop_marker,
    write_formal_hold_stop_marker,
)
from stage_f_process_audit import implementation_identity


def _contract_parser(*, include_command: bool) -> argparse.ArgumentParser:
    """构造运行与 marker 复核共用的冻结契约参数。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ids", type=Path, required=True)
    parser.add_argument("--formal_run_id", required=True)
    parser.add_argument("--supplement_run_id", required=True)
    parser.add_argument("--formal_job_id", type=int, required=True)
    parser.add_argument("--formal_log", type=Path, required=True)
    parser.add_argument("--stop_marker", type=Path, required=True)
    parser.add_argument("--n_jobs", type=int, required=True)
    parser.add_argument("--formal_hold_node")
    parser.add_argument(
        "--formal_hold_lock_root",
        type=Path,
        default=Path("/home/penghongen"),
    )
    parser.add_argument("--formal_hold_probe_timeout_seconds", type=float, default=120.0)
    parser.add_argument("--poll_seconds", type=float, default=300.0)
    if include_command:
        parser.add_argument("--child_pgid_file", type=Path, required=True)
        parser.add_argument("--termination_grace_seconds", type=float, default=60.0)
        parser.add_argument("command", nargs=argparse.REMAINDER)
    return parser


def _validated_plan(args: argparse.Namespace) -> dict:
    """按 CLI 参数加载并验证冻结补算计划。"""
    return validate_supplement_guard_contract(
        args.plan,
        args.ids,
        formal_run_id=args.formal_run_id,
        supplement_run_id=args.supplement_run_id,
        formal_job_id=args.formal_job_id,
        formal_log_path=args.formal_log,
        n_jobs=args.n_jobs,
    )


def _formal_hold_monitor(
    args: argparse.Namespace,
    plan: dict,
) -> FormalHoldMonitor | None:
    """仅在显式给出节点时构造跨 allocation 的 formal-held 守卫。"""
    if args.formal_hold_node is None:
        return None
    if int(plan["formal_job_id"]) != args.formal_job_id:
        raise RuntimeError("formal-held Job ID differs from the validated plan")
    probe_script = Path(__file__).resolve().with_name("stage_f_process_audit.py")
    identity = implementation_identity(probe_script)
    probe_argv = [
        "srun",
        "--overlap",
        f"--jobid={args.formal_job_id}",
        "--nodes=1",
        "--ntasks=1",
        "--cpus-per-task=1",
        f"--nodelist={args.formal_hold_node}",
        str(Path(sys.executable).resolve()),
        str(probe_script),
        "probe",
    ]
    return FormalHoldMonitor(
        formal_job_id=args.formal_job_id,
        formal_node=args.formal_hold_node,
        lock_root=args.formal_hold_lock_root,
        probe_argv=probe_argv,
        expected_probe_contract=identity["probe_contract"],
        expected_probe_script_sha256=identity["probe_script_sha256"],
        expected_probe_module_sha256=identity["probe_module_sha256"],
        probe_timeout_seconds=args.formal_hold_probe_timeout_seconds,
    )


def _launch_after_barrier(arguments: list[str]) -> None:
    """隐藏启动器：等待父进程登记 PGID 后，以同一 PID 执行真实工作负载。"""
    if os.name != "posix":
        raise RuntimeError("startup-barrier launcher is supported only on POSIX")
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--barrier-fd", type=int, required=True)
    parser.add_argument("--restore-signal-mask", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(arguments)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        raise ValueError("startup-barrier launcher requires a workload command")
    try:
        release_token = os.read(args.barrier_fd, 1)
    finally:
        os.close(args.barrier_fd)
    if release_token != b"R":
        raise RuntimeError("supplement startup barrier closed without a release token")
    restored_signal_mask = {
        signal.Signals(int(signum))
        for signum in args.restore_signal_mask.split(",")
        if signum
    }
    signal.pthread_sigmask(signal.SIG_SETMASK, restored_signal_mask)
    os.execvp(command[0], command)


def _validate_marker(arguments: list[str]) -> None:
    """为 shell caller 独立复核退出码 75 的结构化证据。"""
    args = _contract_parser(include_command=False).parse_args(arguments)
    plan = _validated_plan(args)
    monitor = _formal_hold_monitor(args, plan)
    if monitor is None:
        validate_supplement_stop_marker(
            args.stop_marker,
            plan=plan,
            plan_path=args.plan,
            ids_path=args.ids,
            formal_log_path=args.formal_log,
        )
    else:
        validate_formal_hold_stop_marker(
            args.stop_marker,
            plan=plan,
            plan_path=args.plan,
            ids_path=args.ids,
            formal_log_path=args.formal_log,
            monitor=monitor,
        )


def _reap_child_group(arguments: list[str]) -> None:
    """回收 guard 异常退出后遗留的精确独立进程组。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--child_pgid_file", type=Path, required=True)
    parser.add_argument("--expected_child_pgid_file", type=Path, required=True)
    parser.add_argument("--termination_grace_seconds", type=float, default=60.0)
    args = parser.parse_args(arguments)
    reap_registered_process_group(
        args.child_pgid_file,
        expected_child_pgid_path=args.expected_child_pgid_file,
        grace_seconds=args.termination_grace_seconds,
    )


def _check_formal_hold(arguments: list[str]) -> None:
    """在 release gate 前重新核验 formal hold；漂移时留下独立 marker。"""
    args = _contract_parser(include_command=False).parse_args(arguments)
    plan = _validated_plan(args)
    monitor = _formal_hold_monitor(args, plan)
    if monitor is None:
        raise RuntimeError("check-formal-hold requires --formal_hold_node")
    try:
        snapshot = monitor.check()
    except FormalHoldViolation as exc:
        write_formal_hold_stop_marker(
            args.stop_marker,
            plan=plan,
            plan_path=args.plan,
            ids_path=args.ids,
            formal_log_path=args.formal_log,
            monitor=monitor,
            process_started=True,
            last_successful_hold_check=None,
            violation=exc.snapshot,
        )
        validate_formal_hold_stop_marker(
            args.stop_marker,
            plan=plan,
            plan_path=args.plan,
            ids_path=args.ids,
            formal_log_path=args.formal_log,
            monitor=monitor,
        )
        raise SystemExit(FORMAL_HOLD_GUARD_EXIT_CODE)
    print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))


def main(arguments: list[str] | None = None) -> None:
    """校验冻结计划，监督补算子进程，并返回受保护的运行结果。"""
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    if arguments[:1] == ["_launch_after_barrier"]:
        _launch_after_barrier(arguments[1:])
        return
    if arguments[:1] == ["validate-marker"]:
        _validate_marker(arguments[1:])
        return
    if arguments[:1] == ["reap-child-group"]:
        _reap_child_group(arguments[1:])
        return
    if arguments[:1] == ["check-formal-hold"]:
        _check_formal_hold(arguments[1:])
        return

    parser = _contract_parser(include_command=True)
    args = parser.parse_args(arguments)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    plan = _validated_plan(args)
    monitor = _formal_hold_monitor(args, plan)
    exit_code = supervise_f_supplement(
        command,
        plan=plan,
        plan_path=args.plan,
        ids_path=args.ids,
        formal_log_path=args.formal_log,
        stop_marker_path=args.stop_marker,
        child_pgid_path=args.child_pgid_file,
        poll_seconds=args.poll_seconds,
        termination_grace_seconds=args.termination_grace_seconds,
        launcher_command=[sys.executable, str(Path(__file__).resolve())],
        formal_hold_monitor=monitor,
    )
    if exit_code in {COLLISION_GUARD_EXIT_CODE, FORMAL_HOLD_GUARD_EXIT_CODE}:
        if monitor is None:
            validate_supplement_stop_marker(
                args.stop_marker,
                plan=plan,
                plan_path=args.plan,
                ids_path=args.ids,
                formal_log_path=args.formal_log,
            )
        else:
            validate_formal_hold_stop_marker(
                args.stop_marker,
                plan=plan,
                plan_path=args.plan,
                ids_path=args.ids,
                formal_log_path=args.formal_log,
                monitor=monitor,
            )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
