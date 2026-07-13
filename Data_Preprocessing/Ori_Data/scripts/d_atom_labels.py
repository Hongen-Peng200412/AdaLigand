# 学习导航：功能分区=入口/导航层；生命周期=正式主路径 Stage D。
# 实际逻辑：调用 code/atom_labels.py、parallel.py、reports.py。
# 输入/输出：C receptor/ligand 坐标 → 标签数组、样本终态和 Stage D 汇总。
# 关键边界：入口不定义 4 Å 科学规则，只传递分片、并发和 run-scoped 路径。
"""Stage D CLI：分片并行生成原子级标签与 run-scoped 终态清单。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from joblib import Parallel, delayed

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from atom_labels import build_atom_labels
from io_utils import read_jsonl
from parallel import filter_pair_records, read_pdb_id_filter, shard_items
from reports import (
    failure_stage_result,
    resolve_run_id,
    stage_report_path,
    stage_result,
    write_stage_results,
)


STAGE_NAME = "stage_d"


def main() -> None:
    """执行 Stage D；单样本失败不会中断同分片，其类别进入本轮状态清单。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--part_id", type=int, default=0)
    parser.add_argument("--total_parts", type=int, default=1)
    parser.add_argument("--n_jobs", type=int, default=1)
    parser.add_argument("--binding_threshold", type=float, default=4.0)
    parser.add_argument("--run_id")
    parser.add_argument("--pdb_ids_file", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    run_id = resolve_run_id(args.run_id)
    records = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    records = filter_pair_records(records, read_pdb_id_filter(args.pdb_ids_file))
    pdb_ids = [str(record["pdb_id"]).lower() for record in records]
    pdb_ids = shard_items(pdb_ids, args.part_id, args.total_parts)

    def _process(pdb_id: str) -> dict:
        try:
            result = build_atom_labels(
                args.root,
                pdb_id,
                binding_threshold=args.binding_threshold,
                overwrite=args.overwrite,
            )
            status = result.pop("status")
            return stage_result(pdb_id, STAGE_NAME, status, **result)
        except Exception as exc:
            return failure_stage_result(pdb_id, STAGE_NAME, exc)

    results = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(_process)(pdb_id) for pdb_id in pdb_ids
    )
    report_path = stage_report_path(
        args.root,
        run_id,
        STAGE_NAME,
        args.part_id,
        args.total_parts,
    )
    write_stage_results(report_path, results)


if __name__ == "__main__":
    main()
