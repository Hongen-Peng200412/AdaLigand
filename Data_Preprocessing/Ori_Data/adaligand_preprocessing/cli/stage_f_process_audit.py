#!/usr/bin/env python3
"""生成或校验 Stage F scratch 回收前的进程证据。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


from adaligand_preprocessing.utils.io import sha256_file
from adaligand_preprocessing.ops.stage_f_processes import capture_process_audit, probe_payload


def _job(value: str) -> tuple[int, str]:
    """解析 ``JOB_ID:NODE`` 参数。"""
    job_id, separator, node = value.partition(":")
    if not separator or not job_id.isdigit() or not node:
        raise argparse.ArgumentTypeError("job must use JOB_ID:NODE")
    return int(job_id), node


def _opaque_process(value: str) -> dict[str, object]:
    """解析 ``NODE:PID:PPID:START_TICKS:ARGV_SHA256`` 精确进程指纹。"""
    parts = value.split(":")
    if len(parts) != 5:
        raise argparse.ArgumentTypeError(
            "opaque process must use NODE:PID:PPID:START_TICKS:ARGV_SHA256"
        )
    node, pid, ppid, start_time_ticks, argv_sha256 = parts
    if (
        not node
        or not pid.isdigit()
        or not ppid.isdigit()
        or not start_time_ticks.isdigit()
        or len(argv_sha256) != 64
        or any(character not in "0123456789abcdefABCDEF" for character in argv_sha256)
    ):
        raise argparse.ArgumentTypeError("invalid opaque process fingerprint")
    return {
        "node": node,
        "pid": int(pid),
        "ppid": int(ppid),
        "start_time_ticks": int(start_time_ticks),
        "argv_sha256": argv_sha256.lower(),
    }


def main() -> None:
    """执行当前节点 probe，或在登录节点汇总 controller/compute 证据。"""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    subparsers.add_parser("probe")
    capture = subparsers.add_parser("capture")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--job", action="append", type=_job, required=True)
    capture.add_argument("--lock_root", type=Path, default=Path("/home/penghongen"))
    capture.add_argument("--controller_node", required=True)
    capture.add_argument(
        "--allow_controller_opaque",
        action="append",
        type=_opaque_process,
        default=[],
        help="只对 controller 上一次性、精确指纹匹配的 opaque Python 取消阻断",
    )
    args = parser.parse_args()
    script_path = Path(__file__).resolve()
    if args.mode == "probe":
        print(json.dumps(probe_payload(script_path), ensure_ascii=False, sort_keys=True))
        return
    audit = capture_process_audit(
        args.output,
        jobs=args.job,
        script_path=script_path,
        lock_root=args.lock_root,
        expected_controller_node=args.controller_node,
        authorized_controller_opaque_specs=args.allow_controller_opaque,
    )
    print(
        json.dumps(
            {
                "status": audit["status"],
                "output": str(args.output),
                "sha256": sha256_file(args.output),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    if audit["status"] != "success":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
