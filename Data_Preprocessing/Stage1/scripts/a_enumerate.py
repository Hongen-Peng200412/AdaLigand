"""Stage A: 枚举 PDB/EMDB pair_list。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaligand_stage1.io_utils import write_jsonl
from adaligand_stage1.rcsb import build_pair_records, search_em_ligand_entries


def main() -> None:
    """
    执行 Stage A 枚举。

    输出:
        - None: 在 `root/raw/pair_list.jsonl` 写入枚举结果
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
    # Stage A 查询本身是全局查询; 分片留给 B/C 处理, 这里不切分 pair_list。
    records = build_pair_records(pdb_ids, args.limit)
    write_jsonl(output_path, records)


if __name__ == "__main__":
    main()
