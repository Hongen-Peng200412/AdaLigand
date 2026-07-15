#!/usr/bin/env python3
"""生成或执行 Stage F scratch 回收前的受检进程探针。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from io_utils import sha256_file
from stage_f_process_audit import capture_process_audit, probe_payload


def _job(value: str) -> tuple[int, str]:
    """解析 ``JOB_ID:NODE`` 参数。"""
    job_id, separator, node = value.partition(":")
    if not separator or not job_id.isdigit() or not node:
        raise argparse.ArgumentTypeError("job must use JOB_ID:NODE")
    return int(job_id), node


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
