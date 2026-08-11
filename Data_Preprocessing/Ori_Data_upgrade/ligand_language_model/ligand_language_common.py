"""提供配体语言模型升级入口共享的样本选择、分片和原子写入能力。

主要入口是 :func:`load_sample_ids`、:func:`select_shard`、
:func:`atomic_write_jsonl`、:func:`atomic_write_json` 和
:func:`atomic_save_npz`。这些函数不决定配体化学含义或模型行为，只保证 CPU
准备、GPU 推理和汇总入口使用同一套 PDB 范围、Slurm 数组分片和文件完成语义。

正式产物由调用者提供的 ``output_root`` 决定。本模块自身不创建发布状态，不修改
``all_valid.json`` 或 ``info.json``，也不自动启动后续任务。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Iterable
from uuid import uuid4

import numpy as np


def utc_now() -> str:
    """返回带 UTC 时区的 ISO 8601 时间字符串，供分片报告记录运行时间。"""

    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, object]]:
    """读取 UTF-8 JSONL 文件。

    参数：
    - ``path``：每个非空物理行都是一个 JSON 对象的文件。

    返回：
    - ``records``：按文件顺序排列的字典列表；空文件返回空列表。
    """

    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} 必须是 JSON 对象")
            records.append(value)
    return records


def _temporary_path(path: Path) -> Path:
    """为同目录原子替换构造不会与其他进程重名的临时路径。"""

    return path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}")


def atomic_write_jsonl(path: Path, records: Iterable[dict[str, object]]) -> None:
    """原子写入一个 JSONL 文件。

    参数：
    - ``path``：正式目标文件；其父目录会在写入前创建。
    - ``records``：按目标顺序写出的 JSON 对象；每个对象占一个物理行。

    副作用：先在目标目录写入临时文件，再用 ``os.replace`` 建立完成标志；异常时不留下正式半文件。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_path(path)
    try:
        with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: dict[str, object]) -> None:
    """原子写入带缩进的 UTF-8 JSON 对象。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = _temporary_path(path)
    try:
        temporary_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_save_npz(path: Path, **arrays: np.ndarray) -> None:
    """原子写入压缩 NPZ。

    参数：
    - ``path``：正式 ``candidate_{candidate_id}.npz`` 路径。
    - ``arrays``：模型身份、occurrence 身份、实际输入 SMILES 和 ``float32 (768,)`` 分子向量。
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}.npz")
    try:
        np.savez_compressed(temporary_path, **arrays)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_sample_ids(
    data_root: Path,
    sample_scope: str,
    all_valid_path: Path,
) -> list[str]:
    """读取尚未分片的全局 PDB 清单。

    参数：
    - ``data_root``：AdaLigand ``Ori_Data`` 根目录，包含 ``parse/{pdb_id}/occurrences.jsonl``。
    - ``sample_scope``：``all_existing`` 枚举现存 occurrence 文件；``all_valid`` 读取 ``all_valid_path``。
    - ``all_valid_path``：只缩小样本清单；``all_existing`` 模式不会读取其内容。

    返回：
    - ``pdb_ids``：排序、去重并转换为小写的全局 PDB 标识列表。
    """

    if sample_scope == "all_existing":
        parse_root = data_root / "parse"
        return sorted(
            {
                path.parent.name.lower()
                for path in parse_root.glob("*/occurrences.jsonl")
                if path.is_file()
            }
        )
    if sample_scope != "all_valid":
        raise ValueError("sample_scope 必须是 all_valid 或 all_existing")

    values = json.loads(all_valid_path.read_text(encoding="utf-8"))
    if not isinstance(values, list):
        raise ValueError("all_valid.json 顶层必须是 PDB 字符串数组")
    return sorted(
        {str(value).strip().lower() for value in values if str(value).strip()}
    )


def select_shard(
    pdb_ids: list[str],
    shard_index: int,
    num_shards: int,
) -> list[str]:
    """选择零基连续 Slurm 数组中的一个交错 PDB 分片。

    参数：
    - ``pdb_ids``：排序、去重后的全局 PDB 标识列表。
    - ``shard_index``：当前数组任务编号，必须位于 ``[0, num_shards)``。
    - ``num_shards``：数组任务总数，必须为正整数。

    返回：
    - ``shard_pdb_ids``：``pdb_ids[shard_index::num_shards]``；不同任务的列表两两不重叠且并集等于全局列表。
    """

    if num_shards < 1:
        raise ValueError("num_shards 必须为正整数")
    if shard_index < 0 or shard_index >= num_shards:
        raise ValueError("shard_index 必须位于 [0, num_shards) 范围内")
    return pdb_ids[shard_index::num_shards]


def shard_report_path(stage_root: Path, shard_index: int, num_shards: int) -> Path:
    """返回当前阶段的互斥分片报告路径。"""

    return stage_root / "reports" / f"shard_{shard_index:03d}_of_{num_shards:03d}.json"


def clean_exception(error: BaseException) -> str:
    """把异常压缩成适合 JSONL 和普通日志的单行文字。"""

    detail = str(error).replace("\r", " ").replace("\n", " ").strip()
    return f"{type(error).__name__}: {detail}"


def dependency_versions(distributions: Iterable[str]) -> dict[str, str | None]:
    """读取分片报告所需的 Python distribution 版本，不把缺失依赖当作样本状态。"""

    versions: dict[str, str | None] = {}
    for distribution in distributions:
        try:
            versions[distribution] = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions
