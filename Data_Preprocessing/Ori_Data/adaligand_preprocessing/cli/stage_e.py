# Stage E 命令入口：生成密度与配体区域产物。
# 实际逻辑：调用 Stage E 三类产物、MRC 几何、Chimera、模型 CIF 和产物验证模块。
# 输入/输出：实验 MRC + C/D 结构标签 → E1/E2/E3 网格、ligand-area 与状态。
# 关键边界：E2 ATOM-only、E3 标签网格和 frame guard 由实际模块负责；入口只编排顺序与退出码。
"""Stage E CLI：顺序执行 E1/E2/E3，并写 run-scoped 单样本终态。"""

from __future__ import annotations

import argparse
from pathlib import Path

from joblib import Parallel, delayed


from adaligand_preprocessing.external_tools.chimera import ChimeraRunner
from adaligand_preprocessing.stages.stage_e import build_experimental_density, build_ligand_area, build_simulated_density
from adaligand_preprocessing.execution.exclusions import exclusion_status_fields, load_run_exclusions
from adaligand_preprocessing.utils.io import read_jsonl
from adaligand_preprocessing.execution.parallel import filter_pair_records, read_pdb_id_filter, shard_items
from adaligand_preprocessing.artifacts.reports import (
    ensure_filtered_stage_run_is_isolated,
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
    ensure_filtered_stage_run_is_isolated(
        args.root,
        run_id,
        STAGE_NAME,
        args.pdb_ids_file,
    )
    scratch_root = args.scratch_root or (args.root / "scratch")
    probe_runner = ChimeraRunner([str(args.chimera)], timeout_seconds=args.timeout_seconds)
    chimera_version = probe_runner.probe(scratch_root / run_id / "stage_e" / "_probe")
    records = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    exclusions, exclusions_sha256 = load_run_exclusions(args.root, run_id, STAGE_NAME)
    universe_ids = {str(record["pdb_id"]).lower() for record in records}
    unknown_exclusions = sorted(set(exclusions).difference(universe_ids))
    if unknown_exclusions:
        raise ValueError(f"run exclusions reference PDB IDs outside pair_list: {unknown_exclusions}")
    records = filter_pair_records(records, read_pdb_id_filter(args.pdb_ids_file))
    records = shard_items(records, args.part_id, args.total_parts)

    def _process(record: dict) -> dict:
        pdb_id = str(record["pdb_id"]).lower()
        exclusion = exclusions.get(pdb_id)
        if exclusion is not None:
            if exclusions_sha256 is None:
                raise RuntimeError("run exclusion manifest identity is missing")
            return stage_result(
                pdb_id,
                STAGE_NAME,
                "known_failed",
                **exclusion_status_fields(
                    exclusion,
                    manifest_sha256=exclusions_sha256,
                ),
            )
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
