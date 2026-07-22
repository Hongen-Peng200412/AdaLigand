# Stage F 命令入口：生成 CC、配体 Q 与口袋 Q。
# 实际逻辑：调用 Stage F 质量产物、Chimera、MapQ、模型 CIF 和产物验证模块。
# 输入/输出：E 图/网格 + C/D 结构 → 四 CC、配体 Q、6 Å occurrence 口袋 Q 与 F 状态。
# 关键边界：入口不计算 CC/Q；它编排外部工具、身份映射、并发和 run-scoped 终态。
"""Stage F CLI：Chimera 四 CC + MapQ 逐原子 Q + run-scoped 状态。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from joblib import Parallel, delayed


from adaligand_preprocessing.external_tools.chimera import ChimeraRunner
from adaligand_preprocessing.execution.exclusions import exclusion_status_fields, load_run_exclusions
from adaligand_preprocessing.utils.io import read_jsonl, sha256_file
from adaligand_preprocessing.external_tools.mapq import MAPQ_ZIP_SHA256, MapQRunner
from adaligand_preprocessing.execution.parallel import filter_pair_records, read_pdb_id_filter, shard_items
from adaligand_preprocessing.stages.stage_f import build_quality
from adaligand_preprocessing.artifacts.reports import (
    failure_stage_result,
    resolve_run_id,
    stage_report_path,
    stage_result,
    write_stage_results,
)


STAGE_NAME = "stage_f"


def main() -> None:
    """执行 Stage F；全局工具配置先 fail-fast，单样本未知输出失败进入本轮清单。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--chimera", type=Path, required=True)
    parser.add_argument("--chimera_root", type=Path, required=True)
    parser.add_argument("--mapq_python", type=Path, default=Path(sys.executable))
    parser.add_argument("--mapq_cmd", type=Path, required=True)
    parser.add_argument("--mapq_zip", type=Path, required=True)
    parser.add_argument("--scratch_root", type=Path)
    parser.add_argument("--part_id", type=int, default=0)
    parser.add_argument("--total_parts", type=int, default=1)
    parser.add_argument("--n_jobs", type=int, default=1)
    parser.add_argument("--chimera_timeout_seconds", type=float, default=3600.0)
    parser.add_argument("--mapq_timeout_seconds", type=float, default=7200.0)
    parser.add_argument("--run_id")
    parser.add_argument("--pdb_ids_file", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if sha256_file(args.mapq_zip) != MAPQ_ZIP_SHA256:
        raise RuntimeError("MapQ zip checksum does not match pinned mapq_v2.9.7 package")
    run_id = resolve_run_id(args.run_id)
    scratch_root = args.scratch_root or (args.root / "scratch")
    probe_runner = ChimeraRunner([str(args.chimera)], timeout_seconds=args.chimera_timeout_seconds)
    chimera_version = probe_runner.probe(scratch_root / run_id / "stage_f" / "_probe")
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
            chimera_runner = ChimeraRunner(
                [str(args.chimera)],
                timeout_seconds=args.chimera_timeout_seconds,
            )
            mapq_runner = MapQRunner(
                [str(args.mapq_python)],
                args.mapq_cmd,
                args.chimera_root,
                timeout_seconds=args.mapq_timeout_seconds,
            )
            result = build_quality(
                args.root,
                record,
                chimera_runner=chimera_runner,
                mapq_runner=mapq_runner,
                chimera_version=chimera_version,
                run_id=run_id,
                scratch_root=scratch_root,
                overwrite=args.overwrite,
            )
            status = result.pop("status")
            return stage_result(pdb_id, STAGE_NAME, status, **result)
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
