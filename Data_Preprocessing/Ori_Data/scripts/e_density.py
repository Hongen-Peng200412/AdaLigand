"""Stage E CLI：顺序执行 E1/E2/E3，并写 run-scoped 单样本终态。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from joblib import Parallel, delayed

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from chimera import ChimeraRunner
from density import build_experimental_density, build_ligand_area, build_simulated_density
from io_utils import read_jsonl
from parallel import filter_pair_records, read_pdb_id_filter, shard_items
from reports import (
    failure_stage_result,
    resolve_run_id,
    stage_report_path,
    stage_result,
    write_stage_results,
)


STAGE_NAME = "stage_e"


def main() -> None:
    """执行 E1→E2→E3；单样本失败隔离，未知失败留给 release gate 阻塞。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--chimera", type=Path, required=True)
    parser.add_argument("--scratch_root", type=Path)
    parser.add_argument("--part_id", type=int, default=0)
    parser.add_argument("--total_parts", type=int, default=1)
    parser.add_argument("--n_jobs", type=int, default=1)
    parser.add_argument("--timeout_seconds", type=float, default=3600.0)
    parser.add_argument("--run_id")
    parser.add_argument("--pdb_ids_file", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    run_id = resolve_run_id(args.run_id)
    scratch_root = args.scratch_root or (args.root / "scratch")
    probe_runner = ChimeraRunner([str(args.chimera)], timeout_seconds=args.timeout_seconds)
    chimera_version = probe_runner.probe(scratch_root / run_id / "stage_e" / "_probe")
    records = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    records = filter_pair_records(records, read_pdb_id_filter(args.pdb_ids_file))
    records = shard_items(records, args.part_id, args.total_parts)

    def _process(record: dict) -> dict:
        pdb_id = str(record["pdb_id"]).lower()
        try:
            runner = ChimeraRunner([str(args.chimera)], timeout_seconds=args.timeout_seconds)
            e1 = build_experimental_density(args.root, record, overwrite=args.overwrite)
            e2 = build_simulated_density(
                args.root,
                record,
                runner=runner,
                chimera_version=chimera_version,
                run_id=run_id,
                scratch_root=scratch_root,
                overwrite=args.overwrite,
            )
            e3 = build_ligand_area(args.root, pdb_id, overwrite=args.overwrite)
            substeps = {"e1": e1["status"], "e2": e2["status"], "e3": e3["status"]}
            status = "skipped" if set(substeps.values()) == {"skipped"} else "success"
            return stage_result(pdb_id, STAGE_NAME, status, substeps=substeps)
        except Exception as exc:
            return failure_stage_result(pdb_id, STAGE_NAME, exc)

    results = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(_process)(record) for record in records
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
