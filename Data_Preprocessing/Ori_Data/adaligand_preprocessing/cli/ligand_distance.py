"""批量生成 `ligand_dist.npz`，支持 Slurm array 分片和 loky 并行。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from joblib import Parallel, delayed

from adaligand_preprocessing.artifacts.reports import (
    ensure_filtered_stage_run_is_isolated,
    failure_stage_result,
    resolve_run_id,
    stage_report_path,
    stage_result,
    write_stage_results,
)
from adaligand_preprocessing.execution.parallel import (
    filter_pair_records,
    read_pdb_id_filter,
    shard_items,
)
from adaligand_preprocessing.labels.ligand_distance import build_ligand_distance
from adaligand_preprocessing.utils.io import read_jsonl


REPORT_NAME = "ligand_distance"


def main() -> None:
    """为显式 PDB 清单或完整 pair list 生成距离标签和分片状态。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--part_id", type=int, default=0)
    parser.add_argument("--total_parts", type=int, default=1)
    parser.add_argument("--n_jobs", type=int, default=1)
    parser.add_argument("--run_id")
    parser.add_argument("--pdb_ids_file", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.n_jobs <= 0:
        raise ValueError("n_jobs must be positive")

    run_id = resolve_run_id(args.run_id)
    ensure_filtered_stage_run_is_isolated(
        args.root,
        run_id,
        REPORT_NAME,
        args.pdb_ids_file,
    )
    records = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    records = filter_pair_records(records, read_pdb_id_filter(args.pdb_ids_file))
    records = shard_items(records, args.part_id, args.total_parts)

    def _process(record: dict) -> dict:
        pdb_id = str(record["pdb_id"]).lower()
        try:
            result = build_ligand_distance(
                args.root,
                pdb_id,
                overwrite=args.overwrite,
            )
            return stage_result(pdb_id, REPORT_NAME, result.pop("status"), **result)
        except Exception as exc:
            return failure_stage_result(pdb_id, REPORT_NAME, exc)

    results = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(_process)(record) for record in records
    )
    write_stage_results(
        stage_report_path(
            args.root,
            run_id,
            REPORT_NAME,
            args.part_id,
            args.total_parts,
        ),
        results,
    )
    summary = {
        "part_id": args.part_id,
        "total_parts": args.total_parts,
        "success": sum(result["status"] == "success" for result in results),
        "skipped": sum(result["status"] == "skipped" for result in results),
        "failed": sum(result["status"].endswith("failed") for result in results),
        "without_present_ligand_atoms": sum(
            result.get("n_present_ligand_atoms") == 0 for result in results
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
