"""执行带正式进度碰撞守卫的 Stage F 独立远尾补算命令。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from f_supplement_guard import (
    supervise_f_supplement,
    validate_supplement_guard_contract,
)


def main() -> None:
    """校验冻结计划，监督补算子进程，并原样返回成功/失败/守卫停止码。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--ids", type=Path, required=True)
    parser.add_argument("--formal_run_id", required=True)
    parser.add_argument("--supplement_run_id", required=True)
    parser.add_argument("--formal_job_id", type=int, required=True)
    parser.add_argument("--formal_log", type=Path, required=True)
    parser.add_argument("--stop_marker", type=Path, required=True)
    parser.add_argument("--n_jobs", type=int, required=True)
    parser.add_argument("--poll_seconds", type=float, default=300.0)
    parser.add_argument("--termination_grace_seconds", type=float, default=60.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command

    plan = validate_supplement_guard_contract(
        args.plan,
        args.ids,
        formal_run_id=args.formal_run_id,
        supplement_run_id=args.supplement_run_id,
        formal_job_id=args.formal_job_id,
        n_jobs=args.n_jobs,
    )
    raise SystemExit(
        supervise_f_supplement(
            command,
            plan=plan,
            plan_path=args.plan,
            ids_path=args.ids,
            formal_log_path=args.formal_log,
            stop_marker_path=args.stop_marker,
            poll_seconds=args.poll_seconds,
            termination_grace_seconds=args.termination_grace_seconds,
        )
    )


if __name__ == "__main__":
    main()
