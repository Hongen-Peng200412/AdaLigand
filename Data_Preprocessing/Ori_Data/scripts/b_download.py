# 学习导航：功能分区=入口/导航层；生命周期=正式主路径 Stage B。
# 实际逻辑：调用 code/parallel.py、code/download.py、code/reports.py。
# 输入/输出：A pair_list + 分片参数 → mmCIF/map 原始文件、下载状态与失败记录。
# 关键边界：并发由 sbatch/array 环境决定；入口只传播范围、配置和退出码。
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

from download import (
    download_one_pair,
    resource_path_is_reusable,
    resource_targets,
)
from io_utils import read_jsonl, write_jsonl
from parallel import shard_items
from reports import (
    resolve_run_id,
    sharded_report_path,
    stage_report_path,
    stage_result,
    write_stage_results,
)


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
    parser.add_argument("--run_id")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    run_id = resolve_run_id(args.run_id)
    records = read_jsonl(args.root / "raw" / "pair_list.jsonl")
    records = shard_items(records, args.part_id, args.total_parts)
    resources = {item.strip() for item in args.resources.split(",") if item.strip()}
    invalid_resources = resources.difference({"mmcif", "meta", "map"})
    if not resources or invalid_resources:
        raise ValueError(f"resources must be a non-empty subset of mmcif,meta,map: {invalid_resources}")
    results = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(download_one_pair)(args.root, record, args.overwrite, resources) for record in records
    )
    stage_records = []
    final_legacy_failures = []
    for record, result in zip(records, results, strict=True):
        final_failures = []
        for resource in sorted(resources):
            path = resource_targets(args.root, record)[resource]
            if not resource_path_is_reusable(path, resource):
                attempted_error = next(
                    (
                        item["error"]
                        for item in result["failures"]
                        if item["resource"] == resource
                    ),
                    "final artifact is missing or invalid",
                )
                final_failures.append(
                    {"resource": resource, "path": str(path), "error": attempted_error}
                )
        pdb_id = str(record["pdb_id"]).lower()
        if final_failures:
            for failure in final_failures:
                final_legacy_failures.append(
                    {
                        "pdb_id": pdb_id,
                        "emdb_id": str(record["emdb_id"]).upper(),
                        **failure,
                    }
                )
            stage_records.append(
                stage_result(
                    pdb_id,
                    "stage_b",
                    "known_failed",
                    reason="download_failed",
                    failures=final_failures,
                    resources=result["resources"],
                )
            )
        else:
            status = "success" if "downloaded" in result["resources"].values() else "skipped"
            stage_records.append(
                stage_result(pdb_id, "stage_b", status, resources=result["resources"])
            )
    write_jsonl(
        sharded_report_path(args.root, "_failed_download.jsonl", args.part_id, args.total_parts),
        final_legacy_failures,
    )
    write_stage_results(
        stage_report_path(args.root, run_id, "stage_b", args.part_id, args.total_parts),
        stage_records,
    )


if __name__ == "__main__":
    main()
