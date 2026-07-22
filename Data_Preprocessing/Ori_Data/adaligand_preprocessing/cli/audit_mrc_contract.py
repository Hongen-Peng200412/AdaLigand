# MRC 文件契约审计命令入口。
# 实际逻辑：调用 code/mrc_contract_audit.py 与 code/mrc.py 读取 header 并比较几何字段。
# 输入/输出：EMDB MRC 集合 → 只读 audit 报告；不写正式 Stage E/F 产物。
# 关键边界：验证 origin/nstart/voxel/axis/shape 闭合，不修改冻结的 mrc_pocket_legacy.py。
"""只读并行审计全量 EMDB header 的 Pocket Plus 祖传重采样契约。"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform



from adaligand_preprocessing.ops.mrc_contract import execute_header_audit, implementation_manifest


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """
    读取唯一 EMDB 的 ``.map.gz`` header，原子写 run-scoped summary 与风险 JSONL。

    输出:
        - None: 仅写 ``root/reports/runs/{run_id}/mrc_contract_audit`` 下的审计证据
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pair_list", type=Path, required=True)
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--target_voxel_size", type=float, default=1.0)
    parser.add_argument("--part_id", type=int, default=0)
    parser.add_argument("--total_parts", type=int, default=1)
    parser.add_argument("--n_jobs", type=int, required=True)
    args = parser.parse_args()

    implementation = implementation_manifest(
        {
            "adaligand_preprocessing/ops/mrc_contract.py": PACKAGE_ROOT / "ops" / "mrc_contract.py",
            "adaligand_preprocessing/geometry/legacy/mrc_pocket.py": PACKAGE_ROOT / "geometry" / "legacy" / "mrc_pocket.py",
            "adaligand_preprocessing/geometry/legacy/mrc_pocket.source.json": PACKAGE_ROOT / "geometry" / "legacy" / "mrc_pocket.source.json",
            "adaligand_preprocessing/cli/audit_mrc_contract.py": Path(__file__).resolve(),
        }
    )
    dependency_versions = {
        "python": platform.python_version(),
        "numpy": importlib.metadata.version("numpy"),
        "mrcfile": importlib.metadata.version("mrcfile"),
        "joblib": importlib.metadata.version("joblib"),
    }
    summary_path, risks_path, summary = execute_header_audit(
        root=args.root,
        pair_list_path=args.pair_list,
        run_id=args.run_id,
        target_voxel_size=args.target_voxel_size,
        part_id=args.part_id,
        total_parts=args.total_parts,
        n_jobs=args.n_jobs,
        implementation=implementation,
        dependency_versions=dependency_versions,
    )
    print(
        json.dumps(
            {
                "status": summary["status"],
                "summary_path": str(summary_path),
                "risks_path": str(risks_path),
                "selected_emdb_count": summary["selected_emdb_count"],
                "risk_record_count": summary["risk_record_count"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
