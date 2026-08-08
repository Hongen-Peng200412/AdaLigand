"""不使用内容哈希的原子写入和 PocketXMol 原生字段磁盘封装。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

import numpy as np


def atomic_save_npz(path: Path, arrays: dict[str, np.ndarray]) -> None:
    """原子保存数值数组；正式产物身份不依赖内容哈希。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        with temporary.open("wb") as stream:
            np.savez(stream, **arrays)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, payload: Any) -> None:
    """以 UTF-8 和稳定键顺序原子写入 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """原子写入 JSONL，调用方负责先确定稳定顺序。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取非空 JSONL 记录。"""

    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]
