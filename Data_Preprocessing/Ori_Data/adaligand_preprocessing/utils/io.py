# JSON、JSONL 与 NPZ 的原子读写。
# 主要输入：JSON/JSONL/文本路径、内容和锁/原子替换参数。
# 主要输出：原子落盘文件、追加报告与一致性读取。
# 关键边界：先写临时文件再替换；并发状态文件不能靠非原子覆盖更新。
"""文件读写工具（原子写 + 并发安全）。

供 A–G 共用的落盘原语：
- atomic_save_npz：不压缩 `np.savez` + 临时文件原子替换（读快、抗中断）。
- atomic_save_npz_compressed：仅供明确要求压缩的窄用途产物；写后重读验证再替换，
  不改变 `atomic_save_npz` 的全局不压缩默认值。
- read_jsonl / write_jsonl：UTF-8 JSONL 读 / 原子写。
- append_jsonl：带文件锁（Linux fcntl / Windows msvcrt）的并发安全追加，供多 array 任务同写失败报告。
- safe_object_filename：object_key → 可落盘文件名（转义 `:`、`/` 等）。
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import numpy as np

from adaligand_preprocessing.utils.hashing import (  # 保留既有公开导入路径
    sha256_file,
    sha256_manifest,
    sha256_named_values,
)
from adaligand_preprocessing.utils.locking import file_lock, locked_file


def atomic_save_npz(path: Path, **arrays: Any) -> None:
    """
    以原子写方式保存不压缩 npz 文件。

    输入参数:
        - path: Path, 输出 `.npz` 文件路径
        - arrays: dict[str, Any], 每个 key 对应一个要写入 npz 的数组或对象

    输出:
        - None: 写入完成后目标路径存在; 保存格式为 `np.savez`, 不是压缩格式
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    np.savez(str(tmp_path), **arrays)
    written_path = tmp_path
    if tmp_path.suffix != ".npz":
        written_path = Path(str(tmp_path) + ".npz")
    atomic_replace(written_path, path)


def atomic_save_npz_compressed(
    path: Path,
    *,
    validator: Callable[[Path], None],
    **arrays: Any,
) -> None:
    """以压缩 NPZ 原子写入一个窄用途产物，并在替换前验证临时文件。

    输入参数:
        - path: Path, 最终 ``.npz`` 路径
        - validator: Callable[[Path],None], 接收同目录临时文件；必须完整读取并在非法时抛异常
        - arrays: dict[str,Any], 传给 ``np.savez_compressed`` 的数组

    输出:
        - None: 临时文件通过验证后，使用现有原子替换原语覆盖正式路径

    说明:
        该函数不会改变 ``atomic_save_npz`` 的全局不压缩契约。临时文件名同时包含
        PID 与 UUID，因此同一进程的并发 worker 也互不复用；任何写入、验证或替换
        异常都只清理本次调用创建的临时文件，既有正式文件保持不变。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(
        f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}.npz"
    )
    try:
        np.savez_compressed(tmp_path, **arrays)
        validator(tmp_path)
        atomic_replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """
    读取 UTF-8 JSONL 文件。

    输入参数:
        - path: Path, 每行一个 JSON 对象的文件路径

    输出:
        - records: list[dict[str, Any]], 按文件行序返回的对象列表
    """
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """
    原子写 UTF-8 JSONL 文件。

    输入参数:
        - path: Path, 输出文件路径
        - records: list[dict[str, Any]], 要逐行写入的 JSON 对象

    输出:
        - None: 写入完成后目标路径存在
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    atomic_replace(tmp_path, path)


def atomic_replace(source: Path, target: Path) -> None:
    """
    原子替换目标文件，并容忍 Windows 杀毒/索引器造成的短暂句柄占用。

    输入参数:
        - source: Path, 已完整写完的同文件系统临时文件
        - target: Path, 最终产物路径

    输出:
        - None: 替换成功；非 Windows 或持续权限错误仍直接/最终抛出原异常
    """
    attempts = 20 if os.name == "nt" else 1
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(0.05)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """
    追加一行 UTF-8 JSONL 记录，并用文件锁保护并发写入。

    输入参数:
        - path: Path, 目标 JSONL 文件路径
        - record: dict[str, Any], 要追加的一条记录

    输出:
        - None: 记录追加完成
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        with locked_file(handle):
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def safe_object_filename(object_key: str) -> str:
    """
    将 object_key 转为可落盘文件名。

    输入参数:
        - object_key: str, 形如 `CCD:NAG` 或 `BRANCHED:NAG-NAG:abcdef` 的对象键

    输出:
        - filename: str, 不含路径分隔符的文件名主体
    """
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", object_key)
