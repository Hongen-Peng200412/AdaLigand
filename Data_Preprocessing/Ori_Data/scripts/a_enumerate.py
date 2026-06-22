"""Stage A: 枚举 PDB/EMDB pair_list 记录。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from io_utils import write_jsonl
from rcsb import (
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
