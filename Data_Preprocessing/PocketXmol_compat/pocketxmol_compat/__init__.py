"""AdaLigand A–G 到 PocketXMol docking 原生数据契约的离线适配层。"""

from __future__ import annotations

from typing import Any

__all__ = ["AdaptRequest", "AdaptResult", "adapt_occurrence"]


def __getattr__(name: str) -> Any:
    """惰性导出完整适配器，避免 CCD 审计入口提前加载模型依赖。"""

    if name in __all__:
        from pocketxmol_compat.adapter import adapt_occurrence
        from pocketxmol_compat.records import AdaptRequest, AdaptResult

        exports = {
            "AdaptRequest": AdaptRequest,
            "AdaptResult": AdaptResult,
            "adapt_occurrence": adapt_occurrence,
        }
        return exports[name]
    raise AttributeError(name)
