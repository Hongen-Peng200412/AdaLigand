# 学习导航：功能分区=数据契约与质量验证；生命周期=正式主路径 ABC gate。
# 实际逻辑：汇总 A/B/C run-scoped 状态，调用 contracts/reports/failures 判定释放。
# 输入/输出：A–C 状态与产物 → gate summary、退出码和 release marker。
# 关键边界：显式 download_failed 可 known；unknown、静默缺失、C 漂移必须阻塞 D–G。
"""A–C 硬 release gate：允许显式 B known failure，阻塞未知/静默缺失/C 漂移。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from contracts import CArtifactState, inspect_stage_c
from filtering import load_stage_statuses
from io_utils import read_jsonl
from reports import StageStatus, resolve_run_id, stage_report_path, stage_result, write_report, write_stage_results


def main() -> None:
    """验证 A guard、B/C 本轮状态和 C 当前 schema；通过后 job 以 0 退出。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run_id", required=True)
    args = parser.parse_args()
    run_id = resolve_run_id(args.run_id)
    guard_path = args.root / "reports" / "runs" / run_id / "stage_a" / "guard.json"
    if not guard_path.exists():
        raise RuntimeError(f"Stage A guard is missing: {guard_path}")
    guard = json.loads(guard_path.read_text(encoding="utf-8"))
    if guard.get("status") != "success":
        raise RuntimeError(f"Stage A guard failed: {guard}")
    pairs = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    expected = {str(item["pdb_id"]).lower() for item in pairs}
    b_status, _ = load_stage_statuses(args.root, run_id, "stage_b", expected)
    c_status, _ = load_stage_statuses(args.root, run_id, "stage_c", expected)

    gate_records = []
    b_known_reasons = Counter()
    for pdb_id in sorted(expected):
        inspection = inspect_stage_c(args.root, pdb_id)
        if inspection.state is not CArtifactState.COMPLETE:
            raise RuntimeError(
                f"Stage C schema drift for {pdb_id}: {inspection.state.value}: {inspection.reasons}"
            )
        if c_status[pdb_id]["status"] not in {
            StageStatus.SUCCESS.value,
            StageStatus.SKIPPED.value,
        }:
            raise RuntimeError(f"Stage C is not successful for {pdb_id}: {c_status[pdb_id]}")
        if b_status[pdb_id]["status"] == StageStatus.KNOWN_FAILED.value:
            reason = str(b_status[pdb_id].get("reason", "download_failed"))
            b_known_reasons[reason] += 1
            gate_records.append(
                stage_result(pdb_id, "stage_abc_gate", StageStatus.KNOWN_FAILED, reason=reason)
            )
        else:
            gate_records.append(stage_result(pdb_id, "stage_abc_gate", StageStatus.SUCCESS))
    summary = {
        "status": "success",
        "run_id": run_id,
        "n_samples": len(expected),
        "n_release_ready_c": len(expected),
        "n_b_known_failed": sum(b_known_reasons.values()),
        "b_known_failure_reasons": dict(sorted(b_known_reasons.items())),
        "policy": "known B failures continue explicitly; unknown/silent/C contract failures block",
    }
    write_report(
        args.root / "reports" / "runs" / run_id / "stage_abc_gate" / "summary.json",
        summary,
    )
    write_stage_results(
        stage_report_path(args.root, run_id, "stage_abc_gate", 0, 1),
        gate_records,
    )


if __name__ == "__main__":
    main()
