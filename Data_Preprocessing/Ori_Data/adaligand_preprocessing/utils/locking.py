"""提供 Linux 与 Windows 都可用的进程级文件锁。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Iterator


@contextmanager
def locked_file(handle: IO[Any]) -> Iterator[None]:
    """在上下文期间对已经打开的文件持有进程级独占锁。"""
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
    """对稳定的锁文件持有跨进程独占锁。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        with locked_file(handle):
            yield

