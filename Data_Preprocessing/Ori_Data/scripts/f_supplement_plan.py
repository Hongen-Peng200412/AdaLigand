"""冻结 Stage F 独立远尾补算的 PDB 清单与审计证据。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from f_supplement import create_f_supplement_plan


def main() -> None:
    """解析外部控制面参数并创建不可变的补算计划。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--formal_run_id", required=True)
    parser.add_argument("--supplement_run_id", required=True)
    parser.add_argument("--evidence_dir", type=Path, required=True)
    parser.add_argument("--formal_log", type=Path, required=True)
    parser.add_argument("--tail_count", type=int, required=True)
    parser.add_argument("--formal_completed_upper_bound", type=int, required=True)
    parser.add_argument("--minimum_initial_gap", type=int, required=True)
    parser.add_argument("--collision_guard_tasks", type=int, required=True)
    parser.add_argument("--expected_pair_list_sha256", required=True)
    parser.add_argument("--expected_exclusions_sha256", required=True)
    parser.add_argument("--formal_job_id", type=int, required=True)
    args = parser.parse_args()

    summary = create_f_supplement_plan(
        args.root,
        formal_run_id=args.formal_run_id,
        supplement_run_id=args.supplement_run_id,
        evidence_dir=args.evidence_dir,
        formal_log_path=args.formal_log,
        tail_count=args.tail_count,
        formal_completed_upper_bound=args.formal_completed_upper_bound,
        minimum_initial_gap=args.minimum_initial_gap,
        collision_guard_tasks=args.collision_guard_tasks,
        expected_pair_list_sha256=args.expected_pair_list_sha256,
        expected_exclusions_sha256=args.expected_exclusions_sha256,
        formal_job_id=args.formal_job_id,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
