"""失败记录与样本报告（支持 SLURM array 并发）。

- sharded_report_path：分片运行时把报告写成 `reports/{name}.part_0000_of_0006.jsonl`，避免多 array 任务互相覆盖。
- record_failure / write_report：并发安全地追加失败 JSONL（经 append_jsonl 文件锁）、原子写单样本 JSON 报告。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import json
import os

from io_utils import append_jsonl


def sharded_report_path(root: Path, filename: str, part_id: int, total_parts: int) -> Path:
    """
    构造支持 SLURM array 并发运行的报告路径。

    输入参数:
        - root: Path, Stage root
        - filename: str, 单任务模式下的报告文件名
        - part_id: int, 当前分片编号
        - total_parts: int, 分片总数

    输出:
        - path: Path, 单任务模式返回原文件名; 多分片模式返回带 part 后缀的文件名
    """
    if total_parts <= 1:
        return root / "reports" / filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    return root / "reports" / f"{stem}.part_{part_id:04d}_of_{total_parts:04d}{suffix}"


def record_failure(path: Path, pdb_id: str, stage: str, error: str, **extra: Any) -> None:
    """
    追加一条失败记录。

    输入参数:
        - path: Path, 失败 JSONL 文件路径
        - pdb_id: str, 小写 PDB id
        - stage: str, 失败阶段或资源名称
        - error: str, 错误摘要
        - extra: dict[str, Any], 附加上下文字段

    输出:
        - None: 记录追加完成
    """
    record = {"pdb_id": pdb_id, "stage": stage, "error": error}
    record.update(extra)
    append_jsonl(path, record)


def write_report(path: Path, report: dict[str, Any]) -> None:
    """
    写入单样本 JSON 报告。

    输入参数:
        - path: Path, 输出 JSON 路径
        - report: dict[str, Any], 样本级解析报告

    输出:
        - None: 报告写入完成
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
