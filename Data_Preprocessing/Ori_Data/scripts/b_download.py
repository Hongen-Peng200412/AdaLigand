"""Stage B 入口：分片 + joblib 并行下载原始件。

读 pair_list，按 --part_id/--total_parts 取本分片，再用 joblib-loky(--n_jobs) 并行下载
每个样本的 mmCIF/map/meta（--resources 控制），失败汇总到分片报告。配合 SLURM array 横向扩展。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from joblib import Parallel, delayed

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from download import download_one_pair, write_failed_downloads
from io_utils import read_jsonl
from parallel import shard_items


def main() -> None:
    """
    执行 Stage B 下载。

    输出:
        - None: 在 `root/raw` 下写入下载产物和失败报告
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--part_id", type=int, default=0)
    parser.add_argument("--total_parts", type=int, default=1)
    parser.add_argument("--n_jobs", type=int, default=1)
    parser.add_argument("--resources", default="mmcif,meta,map")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    records = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    records = shard_items(records, args.part_id, args.total_parts)
    resources = {item.strip() for item in args.resources.split(",") if item.strip()}
    results = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(download_one_pair)(args.root, record, args.overwrite, resources) for record in records
    )
    write_failed_downloads(args.root, results, args.part_id, args.total_parts)


if __name__ == "__main__":
    main()
