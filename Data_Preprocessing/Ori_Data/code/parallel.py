"""任务分片工具（配合 SLURM array）。

shard_items：按 `part_id / total_parts`（= SLURM array 口径）把任务列表切成互不重叠的分片，
让每个 array 任务只处理 1/total_parts 的样本；分片内的多核并行由各脚本用 joblib-loky 完成。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def shard_items(items: Sequence[T], part_id: int, total_parts: int) -> list[T]:
    """
    按 SLURM array 口径切分任务列表。

    输入参数:
        - items: Sequence[T], 全量任务列表
        - part_id: int, 当前分片编号, 从 0 开始
        - total_parts: int, 分片总数

    输出:
        - shard: list[T], 属于当前分片的任务
    """
    if total_parts <= 0:
        raise ValueError("total_parts must be positive")
    if part_id < 0 or part_id >= total_parts:
        raise ValueError("part_id must be in [0, total_parts)")
    return [item for idx, item in enumerate(items) if idx % total_parts == part_id]

