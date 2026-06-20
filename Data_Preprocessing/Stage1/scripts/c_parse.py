"""Stage C: 解析 mmCIF 到 occurrence、受体 token 与 GT 坐标。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from joblib import Parallel, delayed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adaligand_stage1.io_utils import read_jsonl
from adaligand_stage1.parallel import shard_items
from adaligand_stage1.parse import parse_one_pdb
from adaligand_stage1.reports import record_failure


def main() -> None:
    """
    执行 Stage C 解析。

    输出:
        - None: 在 `root/parse`、`root/ligand_objects`、`root/reports` 写入产物
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--part_id", type=int, default=0)
    parser.add_argument("--total_parts", type=int, default=1)
    parser.add_argument("--n_jobs", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    records = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    pdb_ids = [str(record["pdb_id"]).lower() for record in records]
    pdb_ids = shard_items(pdb_ids, args.part_id, args.total_parts)

    def _process(pdb_id: str) -> dict:
        try:
            return parse_one_pdb(args.root, pdb_id, args.overwrite)
        except Exception as exc:
            record_failure(args.root / "reports" / "_failed_parse.jsonl", pdb_id, "parse_failed", str(exc))
            return {"pdb_id": pdb_id, "status": "failed", "error": str(exc)}

    Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(_process)(pdb_id) for pdb_id in pdb_ids
    )


if __name__ == "__main__":
    main()
