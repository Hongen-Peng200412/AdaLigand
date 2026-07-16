# 学习导航：功能分区=入口/导航层；生命周期=可复用 Stage E3 schema 迁移与 gate。
# 实际逻辑：调用 code/e3_repair.py，生产逻辑仍只在 density.build_ligand_area。
# 输入/输出：冻结目标 manifest + ID 清单 → 独立迁移状态或 release summary。
# 关键边界：不导入 Chimera/MapQ；不覆盖旧 Stage E 状态、release 或 exclusion。
"""Stage E3 ligand-area 修复与独立验收 CLI。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from e3_repair import gate_repair, prepare_repair_snapshot, run_repair_shard


def main() -> None:
    """冻结旧证据，或执行一个迁移分片/全量只读 gate。"""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)
    prepare_parser = subparsers.add_parser("prepare")
    run_parser = subparsers.add_parser("run")
    gate_parser = subparsers.add_parser("gate")
    prepare_parser.add_argument("--root", type=Path, required=True)
    prepare_parser.add_argument("--source_run_id", required=True)
    prepare_parser.add_argument("--repair_run_id", required=True)
    prepare_parser.add_argument("--target_ids_file", type=Path, required=True)
    prepare_parser.add_argument("--target_manifest", type=Path, required=True)
    prepare_parser.add_argument("--source_stage_status_sha256", required=True)
    prepare_parser.add_argument("--de_release_sha256", required=True)
    prepare_parser.add_argument("--exclusion_sha256", required=True)
    prepare_parser.add_argument("--pair_list_sha256", required=True)
    for subparser in (run_parser, gate_parser):
        subparser.add_argument("--root", type=Path, required=True)
        subparser.add_argument("--repair_run_id", required=True)
        subparser.add_argument("--target_ids_file", type=Path, required=True)
        subparser.add_argument("--target_manifest", type=Path, required=True)
        subparser.add_argument("--target_manifest_sha256", required=True)
        subparser.add_argument("--n_jobs", type=int, required=True)
    run_parser.add_argument("--part_id", type=int, default=0)
    run_parser.add_argument("--total_parts", type=int, default=1)
    args = parser.parse_args()

    if args.mode == "prepare":
        result = prepare_repair_snapshot(
            args.root,
            source_run_id=args.source_run_id,
            repair_run_id=args.repair_run_id,
            target_ids_file=args.target_ids_file,
            target_manifest=args.target_manifest,
            expected_source_stage_status_sha256=args.source_stage_status_sha256,
            expected_de_release_sha256=args.de_release_sha256,
            expected_exclusion_sha256=args.exclusion_sha256,
            expected_pair_list_sha256=args.pair_list_sha256,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return

    common = {
        "root": args.root,
        "repair_run_id": args.repair_run_id,
        "target_ids_file": args.target_ids_file,
        "target_manifest": args.target_manifest,
        "expected_target_manifest_sha256": args.target_manifest_sha256,
        "n_jobs": args.n_jobs,
    }
    if args.mode == "run":
        result = run_repair_shard(
            **common,
            part_id=args.part_id,
            total_parts=args.total_parts,
        )
    else:
        result = gate_repair(**common)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if args.mode == "run" and _has_non_release_status(result):
        raise SystemExit(1)


def _has_non_release_status(summary: dict[str, object]) -> bool:
    """判断分片是否含 release 不接受的终态，供 Slurm 正确传播失败。"""
    raw_counts = summary.get("status_counts")
    if not isinstance(raw_counts, dict):
        return True
    accepted = {"success", "skipped"}
    return any(
        status not in accepted and isinstance(count, int) and count > 0
        for status, count in raw_counts.items()
    )


if __name__ == "__main__":
    main()
