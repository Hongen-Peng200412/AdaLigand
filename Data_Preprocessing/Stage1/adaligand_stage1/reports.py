"""失败记录与样本报告工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import json
import os

from .io_utils import append_jsonl


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
