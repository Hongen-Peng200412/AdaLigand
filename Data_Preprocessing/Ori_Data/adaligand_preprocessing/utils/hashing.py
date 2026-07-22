"""计算文件、文件集合与命名值的稳定 SHA-256。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    """流式计算文件 SHA-256；默认每次读取 1 MiB。"""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_manifest(paths: list[Path], *, base: Path | None = None) -> str:
    """按稳定文件名排序，对名称和各文件摘要再次计算 SHA-256。"""
    manifest = hashlib.sha256()
    named_paths: list[tuple[str, Path]] = []
    for path in paths:
        name = str(path.relative_to(base)) if base is not None else path.name
        named_paths.append((name.replace("\\", "/"), path))
    for name, path in sorted(named_paths):
        manifest.update(name.encode("utf-8"))
        manifest.update(b"\0")
        manifest.update(sha256_file(path).encode("ascii"))
        manifest.update(b"\n")
    return manifest.hexdigest()


def sha256_named_values(values: dict[str, Any]) -> str:
    """对不含 NaN 或 Infinity 的命名值计算稳定 JSON SHA-256。"""
    payload = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

