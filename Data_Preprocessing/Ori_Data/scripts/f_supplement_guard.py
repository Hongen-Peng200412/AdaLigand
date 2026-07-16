"""执行带正式进度碰撞守卫的 Stage F 独立远尾补算命令。"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from f_supplement_guard import (
    COLLISION_GUARD_EXIT_CODE,
    reap_registered_process_group,
    supervise_f_supplement,
    validate_supplement_guard_contract,
    validate_supplement_stop_marker,
)


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
    if include_command:
        parser.add_argument("--child_pgid_file", type=Path, required=True)
        parser.add_argument("--poll_seconds", type=float, default=300.0)
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
    validate_supplement_stop_marker(
        args.stop_marker,
        plan=plan,
        plan_path=args.plan,
        ids_path=args.ids,
        formal_log_path=args.formal_log,
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

    parser = _contract_parser(include_command=True)
    args = parser.parse_args(arguments)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    plan = _validated_plan(args)
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
    )
    if exit_code == COLLISION_GUARD_EXIT_CODE:
        validate_supplement_stop_marker(
            args.stop_marker,
            plan=plan,
            plan_path=args.plan,
            ids_path=args.ids,
            formal_log_path=args.formal_log,
        )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
