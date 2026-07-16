"""E3 迁移独占 writer、Slurm 授权、worker 校验与受检释放入口。"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from e3_launch_control import (  # noqa: E402
    authorize_slurm_identity,
    capture_scheduler_snapshot,
    prepare_launch_control,
    release_launch_control,
    seal_slurm_authorizations,
    verify_slurm_worker,
)


def main() -> None:
    """解析子命令；所有写操作都由控制面模块执行原子身份校验。"""
    parser = argparse.ArgumentParser(description="E3 repair launch control")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare", help="freeze launch manifest and acquire writer lock"
    )
    _add_roots_and_run(prepare)
    prepare.add_argument("--target_manifest", type=Path, required=True)
    prepare.add_argument("--expected_target_manifest_sha256", required=True)
    prepare.add_argument("--git_commit", required=True)
    prepare.add_argument(
        "--implementation_file", type=Path, action="append", required=True
    )
    prepare.add_argument(
        "--required_env",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="stable environment value that every worker must reproduce",
    )
    prepare.add_argument(
        "--extra_evidence_json",
        type=Path,
        help="generic read-only evidence map; file paths are relative to --root",
    )

    authorize = subparsers.add_parser(
        "authorize", help="append one held Slurm identity"
    )
    _add_roots_and_run(authorize)
    authorize.add_argument("--role", choices=("worker", "gate"), required=True)
    identity = authorize.add_mutually_exclusive_group(required=True)
    identity.add_argument("--job_id")
    identity.add_argument("--array_job_id")
    authorize.add_argument(
        "--array_tasks",
        help="comma-separated ids/ranges, for example 0-47 or 0,2,4-9",
    )

    seal = subparsers.add_parser(
        "seal-authorizations", help="atomically close the allowed Slurm identity set"
    )
    _add_roots_and_run(seal)

    verify = subparsers.add_parser(
        "verify", help="verify current Slurm worker before writing"
    )
    _add_roots_and_run(verify)
    verify.add_argument("--role", choices=("worker", "gate"), required=True)

    snapshot = subparsers.add_parser(
        "scheduler-snapshot",
        help="query squeue and write a terminal authorization snapshot",
    )
    _add_roots_and_run(snapshot)
    snapshot.add_argument("--output", type=Path, required=True)

    release = subparsers.add_parser(
        "release", help="release writer lock after gate and scheduler audit"
    )
    _add_roots_and_run(release)
    release.add_argument("--scheduler_snapshot", type=Path, required=True)
    release.add_argument("--expected_gate_summary_sha256", required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare_launch_control(
            args.root,
            args.project_root,
            repair_run_id=args.repair_run_id,
            target_manifest=args.target_manifest,
            expected_target_manifest_sha256=args.expected_target_manifest_sha256,
            git_commit=args.git_commit,
            implementation_files=args.implementation_file,
            required_environment=_parse_required_environment(args.required_env),
            extra_evidence=_read_extra_evidence(args.extra_evidence_json),
            python_executable=sys.executable,
            python_version=platform.python_version(),
        )
    elif args.command == "authorize":
        result = authorize_slurm_identity(
            args.root,
            args.project_root,
            repair_run_id=args.repair_run_id,
            role=args.role,
            job_id=args.job_id,
            array_job_id=args.array_job_id,
            array_task_ids=_parse_task_ids(args.array_tasks),
        )
    elif args.command == "verify":
        result = verify_slurm_worker(
            args.root,
            args.project_root,
            repair_run_id=args.repair_run_id,
            role=args.role,
            environ=os.environ,
            python_executable=sys.executable,
            python_version=platform.python_version(),
        )
    elif args.command == "seal-authorizations":
        result = seal_slurm_authorizations(
            args.root,
            args.project_root,
            repair_run_id=args.repair_run_id,
        )
    elif args.command == "scheduler-snapshot":
        result = capture_scheduler_snapshot(
            args.root,
            args.project_root,
            repair_run_id=args.repair_run_id,
        )
        _write_controller_snapshot(args.output, result)
    else:
        result = release_launch_control(
            args.root,
            args.project_root,
            repair_run_id=args.repair_run_id,
            scheduler_snapshot=args.scheduler_snapshot,
            expected_gate_summary_sha256=args.expected_gate_summary_sha256,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


def _add_roots_and_run(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--project_root", type=Path, required=True)
    parser.add_argument("--repair_run_id", required=True)


def _parse_required_environment(items: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--required_env must use KEY=VALUE: {item}")
        key, value = item.split("=", 1)
        if key in values:
            raise ValueError(f"duplicate --required_env key: {key}")
        values[key] = value
    return values


def _parse_task_ids(value: str | None) -> list[int]:
    if value is None:
        return []
    tasks: set[int] = set()
    for fragment in value.split(","):
        token = fragment.strip()
        if not token:
            raise ValueError("--array_tasks contains an empty fragment")
        if "-" not in token:
            tasks.add(int(token))
            continue
        start_text, end_text = token.split("-", 1)
        start = int(start_text)
        end = int(end_text)
        if start < 0 or end < start:
            raise ValueError(f"invalid --array_tasks range: {token}")
        tasks.update(range(start, end + 1))
    return sorted(tasks)


def _read_extra_evidence(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("--extra_evidence_json must contain a JSON object")
    return payload


def _write_controller_snapshot(path: Path, payload: dict[str, object]) -> None:
    """在控制器明确指定的路径原子写快照；已有不同内容一律拒绝。"""
    serialized = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != payload:
            raise RuntimeError(f"scheduler snapshot already exists with drift: {path}")
        return
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    main()
