# 学习导航：功能分区=调度、资源与恢复控制；生命周期=正式主路径共享基础设施。
# 主要输入：JSON/JSONL/文本路径、内容和锁/原子替换参数。
# 主要输出：原子落盘文件、追加报告、文件锁与一致性读取。
# 关键边界：先写临时文件再替换；并发状态文件不能靠非原子覆盖更新。
"""文件读写工具（原子写 + 并发安全）。

供 A–C 三步共用的落盘原语：
- atomic_save_npz：不压缩 `np.savez` + 临时文件原子替换（读快、抗中断）。
- read_jsonl / write_jsonl：UTF-8 JSONL 读 / 原子写。
- append_jsonl：带文件锁（Linux fcntl / Windows msvcrt）的并发安全追加，供多 array 任务同写失败报告。
- safe_object_filename：object_key → 可落盘文件名（转义 `:`、`/` 等）。
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from typing import IO, Any

import numpy as np


def sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    """
    流式计算文件 SHA-256，用于派生产物的输入 provenance。

    输入参数:
        - path: Path, 要读取的文件
        - block_size: int, 单次读取字节数，默认 1 MiB

    输出:
        - digest: str, 64 位小写十六进制摘要
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_manifest(paths: list[Path], *, base: Path | None = None) -> str:
    """
    对一组文件的稳定名称和内容摘要再做 SHA-256。

    输入参数:
        - paths: list[Path], 输入文件；调用方负责限定在当前样本范围
        - base: Path | None, 提供时把名称写成相对路径，便于跨机器复现

    输出:
        - digest: str, 与输入顺序无关的 manifest 摘要
    """
    manifest = hashlib.sha256()
    named_paths = []
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
    """
    对可 JSON 序列化的命名值做稳定 SHA-256，用于组合大文件已有摘要与小文件 manifest。

    字典按 key 排序、无空白编码；调用方不得传 NaN/Infinity。
    """
    payload = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


@contextmanager
def _locked_file(handle: IO[Any]) -> Iterator[None]:
    """
    对已打开文件施加进程级独占锁。

    输入参数:
        - handle: IO[Any], 已打开的文本或二进制文件句柄

    输出:
        - None: 上下文退出时释放文件锁
    """
    if os.name == "nt":
        import msvcrt

        handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            handle.seek(0, os.SEEK_END)
            yield
        finally:
            handle.flush()
            # Windows 的 msvcrt 从“当前位置”解锁；写入后必须回到原加锁位置。
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.flush()
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """
    对一个稳定 lock 文件施加跨进程独占锁。

    输入参数:
        - path: Path, lock 文件路径；调用方应按 artifact key 构造唯一名称

    输出:
        - None: 上下文持有独占锁，退出时释放；空 lock 文件可保留供后续复用
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        with _locked_file(handle):
            yield


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
        with _locked_file(handle):
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
