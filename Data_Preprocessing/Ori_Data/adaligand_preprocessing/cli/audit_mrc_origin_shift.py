# MRC origin 位移审计命令入口。
# 实际逻辑：分片扫描 MRC header，或合并分片为受影响 PDB/EMDB 清单。
# 输入/输出：pair_list+Stage E 状态+MRC header → 独立 audit run 证据。
# 关键边界：不读密度体素，不写 Stage E/F/G，不修改 Pocket 祖传代码。
"""Pocket ``make_cubic`` origin shift 轴序的分片只读审计入口。"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform



from adaligand_preprocessing.ops.mrc_contract import implementation_manifest
from adaligand_preprocessing.ops.mrc_origin_shift import (
    execute_origin_shift_shard,
    finalize_origin_shift_audit,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """执行分片 header 审计或严格合并全部分片。"""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan")
    _add_common_arguments(scan)
    scan.add_argument("--part_id", type=int, required=True)
    scan.add_argument("--n_jobs", type=int, required=True)

    finalize = subparsers.add_parser("finalize")
    _add_common_arguments(finalize)
    args = parser.parse_args()

    implementation = implementation_manifest(
        {
            "adaligand_preprocessing/ops/mrc_origin_shift.py": PACKAGE_ROOT / "ops" / "mrc_origin_shift.py",
            "adaligand_preprocessing/ops/mrc_contract.py": PACKAGE_ROOT / "ops" / "mrc_contract.py",
            "adaligand_preprocessing/geometry/legacy/mrc_pocket.py": PACKAGE_ROOT / "geometry" / "legacy" / "mrc_pocket.py",
            "adaligand_preprocessing/geometry/legacy/mrc_pocket.source.json": PACKAGE_ROOT / "geometry" / "legacy" / "mrc_pocket.source.json",
            "adaligand_preprocessing/cli/audit_mrc_origin_shift.py": Path(__file__).resolve(),
        }
    )
    if args.command == "scan":
        dependencies = {
            "python": platform.python_version(),
            "numpy": importlib.metadata.version("numpy"),
            "mrcfile": importlib.metadata.version("mrcfile"),
            "joblib": importlib.metadata.version("joblib"),
        }
        summary_path, risk_path, summary = execute_origin_shift_shard(
            root=args.root,
            pair_list_path=args.pair_list,
            source_run_id=args.source_run_id,
            audit_run_id=args.audit_run_id,
            expected_stage_e_status_sha256=args.expected_stage_e_status_sha256,
            part_id=args.part_id,
            total_parts=args.total_parts,
            n_jobs=args.n_jobs,
            implementation=implementation,
            dependency_versions=dependencies,
        )
        output = {
            "status": summary["status"],
            "summary_path": str(summary_path),
            "risk_path": str(risk_path),
            "selected_emdb_count": summary["selected_emdb_count"],
            "affected_emdb_count": summary["affected_emdb_count"],
        }
    else:
        summary_path, summary = finalize_origin_shift_audit(
            root=args.root,
            pair_list_path=args.pair_list,
            source_run_id=args.source_run_id,
            audit_run_id=args.audit_run_id,
            total_parts=args.total_parts,
            expected_stage_e_status_sha256=args.expected_stage_e_status_sha256,
            implementation=implementation,
        )
        output = {
            "status": summary["status"],
            "summary_path": str(summary_path),
            "affected_emdb_count": summary["affected_emdb_count"],
            "affected_pdb_count": summary["affected_pdb_count"],
            "affected_stage_e_eligible_pdb_count": summary[
                "affected_stage_e_eligible_pdb_count"
            ],
        }
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """添加扫描与合并共用的冻结输入。"""
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pair_list", type=Path, required=True)
    parser.add_argument("--source_run_id", required=True)
    parser.add_argument("--audit_run_id", required=True)
    parser.add_argument("--total_parts", type=int, required=True)
    parser.add_argument("--expected_stage_e_status_sha256", required=True)


if __name__ == "__main__":
    main()
