"""Stage E3 迁移 CLI 的批处理退出码契约。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "e3_repair.py"


def _load_cli_module():
    """按文件路径加载 CLI，避免与 code/e3_repair.py 同名模块混淆。"""
    spec = importlib.util.spec_from_file_location("e3_repair_cli_for_test", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ({"success": 10}, False),
        ({"skipped": 4, "success": 6}, False),
        ({"known_failed": 1, "success": 9}, True),
        ({"unknown_failed": 1}, True),
        ({}, False),
    ],
)
def test_run_summary_detects_non_release_status(
    counts: dict[str, int],
    expected: bool,
) -> None:
    """只有 success/skipped 可令 array task 以零退出。"""
    cli = _load_cli_module()
    assert cli._has_non_release_status({"status_counts": counts}) is expected


def test_run_summary_fails_closed_without_status_counts() -> None:
    """缺少结构化计数时 fail closed，不能凭 Python 调用成功放行。"""
    cli = _load_cli_module()
    assert cli._has_non_release_status({}) is True
