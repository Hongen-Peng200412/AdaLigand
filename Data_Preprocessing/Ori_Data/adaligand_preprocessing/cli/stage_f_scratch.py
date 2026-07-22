#!/usr/bin/env python3
"""审计或清理已经停止写入的 Stage F scratch 文件。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


from adaligand_preprocessing.ops.stage_f_scratch import apply_scratch_cleanup, build_scratch_audit


def main() -> None:
    """解析显式 run/job 边界；audit 不删除，apply 必须绑定 manifest SHA。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("audit", "apply"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report_dir", type=Path, required=True)
    parser.add_argument("--run_id", action="append", required=True)
    parser.add_argument("--job_id", action="append", type=int, required=True)
    parser.add_argument("--lock_root", type=Path, default=Path("/home/penghongen"))
    parser.add_argument("--process_audit", type=Path, required=True)
    parser.add_argument("--expected_process_audit_sha256", required=True)
    parser.add_argument("--expected_audit_bundle_sha256")
    args = parser.parse_args()
    common = {
        "root": args.root,
        "report_dir": args.report_dir,
        "run_ids": set(args.run_id),
        "lock_root": args.lock_root,
        "job_ids": args.job_id,
        "process_audit_path": args.process_audit,
        "expected_process_audit_sha256": args.expected_process_audit_sha256,
    }
    if args.mode == "audit":
        if args.expected_audit_bundle_sha256 is not None:
            parser.error("audit mode does not accept --expected_audit_bundle_sha256")
        summary = build_scratch_audit(**common)
    else:
        if args.expected_audit_bundle_sha256 is None:
            parser.error("apply mode requires --expected_audit_bundle_sha256")
        summary = apply_scratch_cleanup(
            **common,
            expected_audit_bundle_sha256=args.expected_audit_bundle_sha256,
        )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
