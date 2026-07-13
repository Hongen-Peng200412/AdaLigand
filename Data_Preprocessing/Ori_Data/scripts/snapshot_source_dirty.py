# 学习导航：功能分区=数据契约与质量验证；生命周期=一次性审计/运维入口。
# 实际逻辑：扫描原始 mmCIF mtime/哈希并生成 source-dirty 快照。
# 输入/输出：明确时间窗口与原始数据根 → 可复核 PDB 清单及 SHA 摘要。
# 关键边界：快照是审计证据，不是自动授权；不能凭快照直接刷新正式 Stage C。
"""按明确 mtime 窗口冻结本轮被 Stage B 刷新的 mmCIF PDB 清单。"""

from __future__ import annotations

import argparse
from datetime import datetime
import os
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from io_utils import atomic_replace, read_jsonl, sha256_file
from reports import write_report


def main() -> None:
    """冻结 source-dirty ID，校验数量/样本宇宙并写可追溯 summary。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mtime_after", required=True)
    parser.add_argument("--mtime_at_or_before", required=True)
    parser.add_argument("--expected_count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    start = _aware_timestamp(args.mtime_after)
    end = _aware_timestamp(args.mtime_at_or_before)
    if start >= end:
        raise ValueError("mtime_after must be earlier than mtime_at_or_before")
    pdb_ids = select_source_dirty_ids(args.root, start, end)
    if len(pdb_ids) != args.expected_count:
        raise RuntimeError(
            f"source-dirty count {len(pdb_ids)} != expected {args.expected_count}"
        )
    universe = {
        str(record["pdb_id"]).lower()
        for record in read_jsonl(args.root / "raw" / "pair_list.jsonl")
    }
    outside = sorted(set(pdb_ids).difference(universe))
    if outside:
        raise RuntimeError(f"source-dirty IDs outside pair_list: {outside[:20]}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = args.output.with_name(f"{args.output.name}.tmp.{os.getpid()}")
    tmp_path.write_text("".join(f"{pdb_id}\n" for pdb_id in pdb_ids), encoding="utf-8")
    atomic_replace(tmp_path, args.output)
    write_report(
        args.summary,
        {
            "status": "success",
            "schema_version": 1,
            "selection": "mtime_after < st_mtime <= mtime_at_or_before",
            "mtime_after": args.mtime_after,
            "mtime_at_or_before": args.mtime_at_or_before,
            "n_pdb_ids": len(pdb_ids),
            "ids_sha256": sha256_file(args.output),
            "ids_path": str(args.output),
        },
    )


def _aware_timestamp(value: str) -> float:
    """把带 UTC offset 的 ISO-8601 时间转为 POSIX 秒，拒绝依赖服务器本地时区。"""
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("mtime bounds must include an explicit UTC offset")
    return parsed.timestamp()


def select_source_dirty_ids(root: Path, start: float, end: float) -> list[str]:
    """
    按严格的 ``start < st_mtime <= end`` 规则列出被刷新 mmCIF。

    输入参数:
        - root: Path, Stage root
        - start: float, 不含下界的 POSIX 秒
        - end: float, 包含上界的 POSIX 秒

    输出:
        - pdb_ids: list[str], 排序且小写的 PDB id
    """
    mmcif_dir = root / "raw" / "rcsb_mmcif"
    return sorted(
        path.stem.lower()
        for path in mmcif_dir.glob("*.cif")
        if start < path.stat().st_mtime <= end
    )


if __name__ == "__main__":
    main()
