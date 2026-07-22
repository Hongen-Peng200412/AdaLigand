# Stage A 命令入口：枚举 PDB–EMDB 配对并写入清单。
# 实际逻辑：调用 Stage A 样本检索和产物报告模块访问 RCSB/EMDB 并落盘摘要。
# 输入/输出：查询配置 → raw/pair_list.jsonl、reports/resolution_summary.json。
# 关键边界：A 是全局一次性枚举；它导航核心逻辑，不是第四类科学实现。
"""Stage A 入口：枚举样本宇宙，写 pair_list + 分辨率统计。

查 RCSB 列出"EM + 有 EMDB + 含配体"的全部 PDB，对每条定主 EMDB 与分辨率，
写 `raw/pair_list.jsonl` 与 `reports/resolution_summary.json`。
注意：A 是全局单次、串行的（不分片、不并行）；--part_id/--n_jobs 不参与处理，集群里单独跑一次即可。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


from adaligand_preprocessing.utils.io import write_jsonl
from adaligand_preprocessing.stages.stage_a import (
    build_pair_records,
    build_resolution_summary,
    format_resolution_summary,
    search_em_ligand_entries,
)


def main() -> None:
    """
    执行 Stage A 枚举。

    输出:
        - None: 写入 `root/raw/pair_list.jsonl` 和 `root/reports/resolution_summary.json`
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--part_id", type=int, default=0)
    parser.add_argument("--total_parts", type=int, default=1)
    parser.add_argument("--n_jobs", type=int, default=1)
    args = parser.parse_args()

    output_path = args.root / "raw" / "pair_list.jsonl"
    if output_path.exists() and not args.overwrite:
        return

    pdb_ids = search_em_ligand_entries()
    records = build_pair_records(pdb_ids, args.limit)
    write_jsonl(output_path, records)

    summary = build_resolution_summary(records)
    summary_path = args.root / "reports" / "resolution_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    print(format_resolution_summary(summary))


if __name__ == "__main__":
    main()
