# Stage G 命令入口：分析质量分布或显式执行过滤。
# 实际逻辑：调用 code/filtering.py 生成分布分析或按显式配置过滤。
# 输入/输出：F 质量记录 + 配置 → analyze 报告或 keep_list；唯一过滤配置 schema 为 v2。
# 关键边界：不猜阈值；CC、配体 Q、口袋 Q 的阈值需由用户后续确定。
"""Stage G CLI：先分析分布，获得显式配置后再生成正式 keep_list。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


from adaligand_preprocessing.stages.stage_g import run_stage_g
from adaligand_preprocessing.artifacts.reports import resolve_run_id


def main() -> None:
    """执行 run-scoped release gate 与 analyze/filter 模式。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--mode", choices=("analyze", "filter"), required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--controlled_failure_waiver", type=Path)
    parser.add_argument("--controlled_failure_waiver_sha256")
    args = parser.parse_args()
    run_id = resolve_run_id(args.run_id)
    result = run_stage_g(
        args.root,
        run_id,
        mode=args.mode,
        config_path=args.config,
        controlled_failure_waiver_path=args.controlled_failure_waiver,
        controlled_failure_waiver_sha256=args.controlled_failure_waiver_sha256,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
