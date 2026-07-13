# 学习导航：功能分区=入口/导航层；生命周期=正式主路径 Stage C。
# 实际逻辑：调用 code/parse.py、receptor.py、ligand_object.py、reports.py。
# 输入/输出：B 的 mmCIF + CCD/descriptor → occurrence、receptor token、LigandObject 与状态。
# 关键边界：入口设置分片/并发；真实 XYZ Å、(N,3)/(M,3) 数组和身份映射由 code 模块定义。
"""Stage C 入口：分片 + joblib 并行解析每个 PDB。

读 pair_list，按 --part_id/--total_parts 取本分片，用 joblib-loky(--n_jobs) 并行调用 parse_one_pdb，
产出 occurrences.jsonl / ligand_coords.npz / receptor_tokens.npz / 去重 ligand_objects 与分片失败报告。配合 SLURM array。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from joblib import Parallel, delayed

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from io_utils import read_jsonl
from contracts import CArtifactState, inspect_stage_c
from parallel import filter_pair_records, read_pdb_id_filter, shard_items
from parse import parse_one_pdb
from reports import (
    ensure_filtered_stage_run_is_isolated,
    failure_stage_result,
    resolve_run_id,
    stage_report_path,
    stage_result,
    write_stage_results,
)


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
    parser.add_argument("--run_id")
    parser.add_argument("--pdb_ids_file", type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    run_id = resolve_run_id(args.run_id)
    ensure_filtered_run_is_isolated(
        args.root,
        run_id,
        args.pdb_ids_file,
    )
    records = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    records = filter_pair_records(records, read_pdb_id_filter(args.pdb_ids_file))
    pdb_ids = [str(record["pdb_id"]).lower() for record in records]
    pdb_ids = shard_items(pdb_ids, args.part_id, args.total_parts)

    def _process(pdb_id: str) -> dict:
        try:
            result = parse_one_pdb(args.root, pdb_id, args.overwrite)
            inspection = inspect_stage_c(args.root, pdb_id)
            if inspection.state is not CArtifactState.COMPLETE:
                raise RuntimeError(
                    f"Stage C did not reach COMPLETE: {inspection.state.value}: {inspection.reasons}"
                )
            raw_status = str(result.get("status", "ok"))
            status = "skipped" if raw_status == "skipped" else "success"
            return stage_result(pdb_id, "stage_c", status, action=raw_status)
        except Exception as exc:
            return failure_stage_result(pdb_id, "stage_c", exc)

    results = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(_process)(pdb_id) for pdb_id in pdb_ids
    )
    write_stage_results(
        stage_report_path(args.root, run_id, "stage_c", args.part_id, args.total_parts),
        results,
    )


def ensure_filtered_run_is_isolated(
    root: Path,
    run_id: str,
    pdb_ids_file: Path | None,
) -> None:
    """
    防止 filtered Stage C 覆盖正式全量 run 的状态证据。

    输入参数:
        - root: Path, Stage root
        - run_id: str, 本次状态目录名
        - pdb_ids_file: Path | None, 非空表示只处理子集
    输出:
        - None: run id 没有正式 A guard 且整个 C 状态目录尚为空

    filtered smoke/repair 必须使用独立的新 run id。正式 A guard 是全量 run 的稳定标记；
    已存在的目标 C 状态也不得被子集结果覆盖。
    """
    ensure_filtered_stage_run_is_isolated(root, run_id, "stage_c", pdb_ids_file)


if __name__ == "__main__":
    main()
