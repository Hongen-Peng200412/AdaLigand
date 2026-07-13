# 学习导航：功能分区=入口/导航层；生命周期=正式主路径的 data guard。
# 实际逻辑：读取冻结 pair_list 并调用 contracts/qc 的完整性检查。
# 输入/输出：既有 raw/pair_list.jsonl → guard 报告/退出码，不重新枚举样本。
# 关键边界：这是数据守护，不是独立科学阶段；失败时阻止后续阶段复用错误宇宙。
"""Stage A 冻结样本宇宙 guard：验证并复用既有 pair_list，不访问网络。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from io_utils import read_jsonl, sha256_file
from reports import resolve_run_id, write_report


def main() -> None:
    """验证 PDB 主键、必需字段、冻结数量和可选 SHA-256，并写 run-scoped guard。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected_count", type=int, required=True)
    parser.add_argument("--expected_sha256")
    parser.add_argument("--run_id")
    args = parser.parse_args()

    run_id = resolve_run_id(args.run_id)
    pair_path = args.root / "raw" / "pair_list.jsonl"
    records = read_jsonl(pair_path)
    pdb_ids = []
    for index, record in enumerate(records):
        missing = {"pdb_id", "emdb_id", "resolution", "resolution_info"}.difference(record)
        if missing:
            raise RuntimeError(f"pair_list row {index} misses {sorted(missing)}")
        pdb_id = str(record["pdb_id"]).lower()
        emdb_id = str(record["emdb_id"]).upper()
        if len(pdb_id) != 4 or not emdb_id.startswith("EMD-"):
            raise RuntimeError(f"invalid pair_list key at row {index}: {pdb_id}/{emdb_id}")
        pdb_ids.append(pdb_id)
    if len(records) != args.expected_count:
        raise RuntimeError(f"pair_list count {len(records)} != expected {args.expected_count}")
    if len(pdb_ids) != len(set(pdb_ids)):
        raise RuntimeError("pair_list contains duplicate PDB ids")
    digest = sha256_file(pair_path)
    if args.expected_sha256 is not None and digest != args.expected_sha256.lower():
        raise RuntimeError(f"pair_list sha256 {digest} != expected {args.expected_sha256.lower()}")
    report = {
        "status": "success",
        "run_id": run_id,
        "pair_list": str(pair_path),
        "count": len(records),
        "sha256": digest,
        "expected_count": args.expected_count,
        "expected_sha256": args.expected_sha256,
        "mode": "frozen_snapshot_reuse_no_network",
    }
    write_report(args.root / "reports" / "runs" / run_id / "stage_a" / "guard.json", report)


if __name__ == "__main__":
    main()
