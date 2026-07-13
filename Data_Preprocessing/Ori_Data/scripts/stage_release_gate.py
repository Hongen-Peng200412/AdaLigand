# 学习导航：功能分区=数据契约与质量验证；生命周期=正式主路径跨阶段 gate 入口。
# 实际逻辑：调用 code/contracts.py、failures.py、reports.py 汇总阶段终态。
# 输入/输出：run-scoped 状态、产物索引与期约 → gate summary、release marker、退出码。
# 关键边界：known 可按契约排除；unknown、重复、静默缺失和 schema 漂移不得放行下游。
"""通用 run-scoped stage gate：允许 known failure，阻塞 unknown/重复/静默缺失。"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from filtering import load_stage_statuses
from io_utils import read_jsonl
from parallel import read_pdb_id_filter
from reports import StageStatus, resolve_run_id, write_report


def main() -> None:
    """检查逗号分隔 stage 的目标 PDB 全覆盖，并写 gate summary。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--stages", required=True)
    parser.add_argument("--gate_name", required=True)
    parser.add_argument("--pdb_ids_file", type=Path)
    parser.add_argument(
        "--require_success",
        action="store_true",
        help="smoke gate 专用：把任何 known_failed 也视为 gate 失败",
    )
    args = parser.parse_args()
    run_id = resolve_run_id(args.run_id)
    stages = [item.strip() for item in args.stages.split(",") if item.strip()]
    if not stages:
        raise ValueError("--stages cannot be empty")
    pairs = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    requested = read_pdb_id_filter(args.pdb_ids_file)
    expected = {
        str(record["pdb_id"]).lower()
        for record in pairs
        if requested is None or str(record["pdb_id"]).lower() in requested
    }
    if requested is not None and expected != requested:
        raise RuntimeError(f"PDB filter mismatch: missing={sorted(requested.difference(expected))}")
    status_counts: dict[str, dict[str, int]] = {}
    known_reason_counts: Counter[str] = Counter()
    for stage in stages:
        statuses, _ = load_stage_statuses(args.root, run_id, stage, expected)
        status_counts[stage] = dict(sorted(Counter(item["status"] for item in statuses.values()).items()))
        for record in statuses.values():
            if record["status"] == StageStatus.KNOWN_FAILED.value:
                known_reason_counts[f"{stage}:{record.get('reason', 'known_failed')}"] += 1
    if args.require_success and known_reason_counts:
        raise RuntimeError(
            "strict smoke gate rejects known failures: "
            f"{dict(sorted(known_reason_counts.items()))}"
        )
    write_report(
        args.root / "reports" / "runs" / run_id / args.gate_name / "summary.json",
        {
            "status": "success",
            "run_id": run_id,
            "gate_name": args.gate_name,
            "stages": stages,
            "n_expected_pdb": len(expected),
            "status_counts": status_counts,
            "known_failure_reasons": dict(sorted(known_reason_counts.items())),
            "policy": (
                "success/skipped only; known/unknown/duplicate/silent missing blocks"
                if args.require_success
                else "known_failed continues explicitly; unknown/duplicate/silent missing blocks"
            ),
        },
    )


if __name__ == "__main__":
    main()
