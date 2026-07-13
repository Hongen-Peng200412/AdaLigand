#!/usr/bin/env python3
"""把已冻结的 Stage E 长尾截止证据追加到正式 run exclusion manifest。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from long_tail_cutoff import apply_stage_e_long_tail_cutoff


def main() -> None:
    """解析全部显式身份参数，执行一次可幂等验证的 run-scoped 迁移。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--evidence_dir", type=Path, required=True)
    parser.add_argument("--predecision_sha256", required=True)
    parser.add_argument("--posttermination_sha256", required=True)
    parser.add_argument("--before_manifest_sha256", required=True)
    parser.add_argument("--expected_existing_pdb_id", action="append", required=True)
    parser.add_argument("--supplement_job_id", type=int, required=True)
    parser.add_argument("--authorization", required=True)
    args = parser.parse_args()
    summary = apply_stage_e_long_tail_cutoff(
        args.root,
        args.run_id,
        evidence_dir=args.evidence_dir,
        expected_predecision_sha256=args.predecision_sha256,
        expected_posttermination_sha256=args.posttermination_sha256,
        expected_before_manifest_sha256=args.before_manifest_sha256,
        expected_existing_ids={item.lower() for item in args.expected_existing_pdb_id},
        expected_supplement_job_id=args.supplement_job_id,
        expected_authorization=args.authorization,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
