"""适配请求、结果和磁盘清单记录。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AdaptRequest:
    """一个 A–G occurrence 的适配请求。"""

    stage_c_root: Path
    output_root: Path
    pocketxmol_root: Path
    pdb_id: str
    candidate_id: int
    split: str
    overwrite: bool = False


@dataclass(frozen=True)
class AdaptResult:
    """一个 occurrence 的两套资格状态和稳定过滤原因。"""

    pdb_id: str
    candidate_id: int
    split: str
    object_key: str
    type_tag: str
    pocketxmol_eligible: bool
    extended_contract_eligible: bool
    active_for_stage3: bool
    reasons: tuple[str, ...]
    native_path: str | None = None
    extended_path: str | None = None

    def to_json(self) -> dict[str, Any]:
        """返回可以直接写入 JSONL 的记录。"""

        payload = asdict(self)
        payload["reasons"] = list(self.reasons)
        return payload
