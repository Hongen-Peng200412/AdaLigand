"""提供 held-out 去冗余的四个显式命令行步骤."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from held_out_pipeline.catalog import finalize_catalog, run_catalog_shard
from held_out_pipeline.redundancy import run_mmseqs_shard
from held_out_pipeline.selection import finalize_identity_views


def _build_parser() -> argparse.ArgumentParser:
    """构建四个子命令及其显式参数, 不保存运行环境默认路径."""

    parser = argparse.ArgumentParser(description="AdaLigand held-out 序列去冗余与测试集构建.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    catalog_shard = subparsers.add_parser("catalog-shard", help="解析一个完整 PDB 分片.")
    catalog_shard.add_argument("--data-root", type=Path, required=True)
    catalog_shard.add_argument("--pair-list", type=Path, required=True)
    catalog_shard.add_argument("--held-out-split", type=Path, required=True)
    catalog_shard.add_argument("--pdb-audit", type=Path, required=True)
    catalog_shard.add_argument("--output-root", type=Path, required=True)
    catalog_shard.add_argument("--shard-index", type=int, required=True)
    catalog_shard.add_argument("--shard-count", type=int, required=True)
    catalog_shard.add_argument("--workers", type=int, required=True)

    catalog_finalize = subparsers.add_parser(
        "catalog-finalize", help="合并序列目录, 生成 FASTA 并运行官方 smoke."
    )
    catalog_finalize.add_argument("--output-root", type=Path, required=True)
    catalog_finalize.add_argument("--pair-list", type=Path, required=True)
    catalog_finalize.add_argument("--train-pdb", type=Path, required=True)
    catalog_finalize.add_argument("--validation-pdb", type=Path, required=True)
    catalog_finalize.add_argument("--calibration-pdb", type=Path, required=True)
    catalog_finalize.add_argument("--held-out-pdb", type=Path, required=True)
    catalog_finalize.add_argument("--shard-count", type=int, required=True)
    catalog_finalize.add_argument("--alignment-shard-count", type=int, required=True)
    catalog_finalize.add_argument("--official-smoke-count", type=int, required=True)
    catalog_finalize.add_argument("--official-timeout-seconds", type=float, required=True)

    mmseqs_shard = subparsers.add_parser("mmseqs-shard", help="运行一个 MMseqs2 query 分片.")
    mmseqs_shard.add_argument("--mmseqs-binary", type=Path, required=True)
    mmseqs_shard.add_argument("--output-root", type=Path, required=True)
    mmseqs_shard.add_argument("--shard-index", type=int, required=True)
    mmseqs_shard.add_argument("--threads", type=int, required=True)

    finalize = subparsers.add_parser("finalize", help="生成 PDB 关系, 身份证和测试视图.")
    finalize.add_argument("--output-root", type=Path, required=True)
    finalize.add_argument("--train-pdb", type=Path, required=True)
    finalize.add_argument("--validation-pdb", type=Path, required=True)
    finalize.add_argument("--calibration-pdb", type=Path, required=True)
    finalize.add_argument("--held-out-pdb", type=Path, required=True)
    finalize.add_argument("--alignment-shard-count", type=int, required=True)
    finalize.add_argument("--pdb-coverage-mode", choices=("or", "and"), required=True)
    finalize.add_argument("--pdb-coverage-threshold", type=float, required=True)
    finalize.add_argument("--seed", type=int, required=True)
    finalize.add_argument("--test-0-size", type=int, required=True)
    return parser


# ================================================================================================


def main() -> None:
    """解析一个显式子命令并打印该步骤的 JSON summary."""

    arguments = _build_parser().parse_args()
    if arguments.command == "catalog-shard":
        summary = run_catalog_shard(
            arguments.data_root,
            arguments.pair_list,
            arguments.held_out_split,
            arguments.pdb_audit,
            arguments.output_root,
            arguments.shard_index,
            arguments.shard_count,
            arguments.workers,
        )
    elif arguments.command == "catalog-finalize":
        summary = finalize_catalog(
            arguments.output_root,
            arguments.pair_list,
            arguments.train_pdb,
            arguments.validation_pdb,
            arguments.calibration_pdb,
            arguments.held_out_pdb,
            arguments.shard_count,
            arguments.alignment_shard_count,
            arguments.official_smoke_count,
            arguments.official_timeout_seconds,
        )
    elif arguments.command == "mmseqs-shard":
        summary = run_mmseqs_shard(
            arguments.mmseqs_binary,
            arguments.output_root,
            arguments.shard_index,
            arguments.threads,
        )
    else:
        summary = finalize_identity_views(
            arguments.output_root,
            arguments.train_pdb,
            arguments.validation_pdb,
            arguments.calibration_pdb,
            arguments.held_out_pdb,
            arguments.alignment_shard_count,
            arguments.pdb_coverage_mode,
            arguments.pdb_coverage_threshold,
            arguments.seed,
            arguments.test_0_size,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
