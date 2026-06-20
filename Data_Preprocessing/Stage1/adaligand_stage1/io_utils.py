"""文件读写工具。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np


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
    os.replace(written_path, path)


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
    os.replace(tmp_path, path)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    """
    追加一行 UTF-8 JSONL 记录。

    输入参数:
        - path: Path, 目标 JSONL 文件路径
        - record: dict[str, Any], 要追加的一条记录

    输出:
        - None: 记录追加完成
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
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

