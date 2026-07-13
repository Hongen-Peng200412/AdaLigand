# 学习导航：功能分区=调度、资源与恢复控制；生命周期=正式主路径共享基础设施。
# 主要输入：样本总数、part_id/n_parts 或 SLURM array 环境变量。
# 主要输出：确定性样本索引区间与并行任务元数据。
# 关键边界：分片只决定处理范围，不改变样本科学契约；B 的单节点单 task 由 sbatch 约束。
"""任务分片工具（配合 SLURM array）。

shard_items：按 `part_id / total_parts`（= SLURM array 口径）把任务列表切成互不重叠的分片，
让每个 array 任务只处理 1/total_parts 的样本；分片内的多核并行由各脚本用 joblib-loky 完成。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
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


def read_pdb_id_filter(path: Path | None) -> set[str] | None:
    """
    读取可选的一行一个 PDB id 的 smoke/repair 子集文件。

    输入参数:
        - path: Path | None, None 表示全量；文件允许空行和 ``#`` 注释

    输出:
        - pdb_ids: set[str] | None, 小写且非空；重复行自动去重
    """
    if path is None:
        return None
    return parse_pdb_id_filter_text(
        path.read_text(encoding="utf-8"),
        source=str(path),
    )


def parse_pdb_id_filter_text(text: str, *, source: str) -> set[str]:
    """
    从同一份已冻结文本解析 PDB id 子集。

    输入参数:
        - text: str, 一行一个 PDB id，可含空行和 `#` 注释
        - source: str, 用于错误信息的来源标识

    输出:
        - pdb_ids: set[str], 小写且非空，重复行自动去重
    """
    pdb_ids = {
        line.strip().lower()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if not pdb_ids:
        raise ValueError(f"PDB id filter is empty: {source}")
    invalid = sorted(
        pdb_id
        for pdb_id in pdb_ids
        if len(pdb_id) != 4 or not pdb_id.isalnum()
    )
    if invalid:
        raise ValueError(f"invalid PDB ids in filter: {invalid}")
    return pdb_ids


def filter_pair_records(
    records: list[dict],
    pdb_ids: set[str] | None,
) -> list[dict]:
    """按显式 PDB 集合保留 pair record，并拒绝请求不存在或重复的主键。"""
    record_ids = [str(record["pdb_id"]).lower() for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("pair records contain duplicate PDB ids")
    if pdb_ids is None:
        return records
    missing = sorted(pdb_ids.difference(record_ids))
    if missing:
        raise ValueError(f"PDB id filter contains ids absent from pair_list: {missing}")
    return [record for record in records if str(record["pdb_id"]).lower() in pdb_ids]
