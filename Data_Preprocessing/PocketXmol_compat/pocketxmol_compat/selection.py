"""读取 Stage3 冻结实例清单；本模块只依赖 Python 标准库。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_selections(
    specifications: list[str],
    stage_c_root: Path | None = None,
) -> list[dict[str, Any]]:
    """读取 ``NAME=PATH`` 清单，并保留实例身份与既有数据划分。

    正式 Stage1 数据划分是 PDB 级清单，因此条目可以只含 ``pdb_id``。此时
    本函数从该 PDB 的 ``occurrences.jsonl`` 展开全部 ``candidate_id``。显式
    含 ``candidate_id`` 的实例级清单保留给校准与 smoke 使用。
    """

    output: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for specification in specifications:
        split, path = parse_split_specification(specification)
        rows = _read_manifest(path)
        for row in rows:
            pdb_id = str(row["pdb_id"]).lower()
            candidate_ids = _candidate_ids_for_row(row, pdb_id, stage_c_root)
            for candidate_id in candidate_ids:
                key = (pdb_id, candidate_id)
                if key in seen:
                    raise ValueError(
                        f"duplicate or cross-split instance: {key[0]}:{key[1]}"
                    )
                seen.add(key)
                output.append(
                    {"pdb_id": key[0], "candidate_id": key[1], "split": split}
                )
    return output


def _candidate_ids_for_row(
    row: dict[str, Any],
    pdb_id: str,
    stage_c_root: Path | None,
) -> list[int]:
    """返回一个显式实例，或把一个正式 PDB 条目展开为全部 occurrence。"""

    if "candidate_id" in row:
        return [int(row["candidate_id"])]
    if stage_c_root is None:
        raise ValueError(
            f"PDB-level split row requires stage_c_root for occurrence expansion: {pdb_id}"
        )
    path = stage_c_root / "parse" / pdb_id / "occurrences.jsonl"
    with path.open("r", encoding="utf-8") as stream:
        occurrences = [json.loads(line) for line in stream if line.strip()]
    candidate_ids = [int(occurrence["candidate_id"]) for occurrence in occurrences]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise ValueError(f"duplicate candidate_id in occurrences: {pdb_id}")
    return candidate_ids


def parse_split_specification(specification: str) -> tuple[str, Path]:
    """拆分一个 ``NAME=PATH`` 参数，并校验允许的数据划分名称。"""

    if "=" not in specification:
        raise ValueError(f"invalid --split value: {specification!r}")
    split, raw_path = specification.split("=", 1)
    if split not in {"train", "validation", "calibration"}:
        raise ValueError(f"unsupported split: {split!r}")
    return split, Path(raw_path)


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    """读取 JSON 列表或非空 JSONL 记录。"""

    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as stream:
            rows = [json.loads(line) for line in stream if line.strip()]
    else:
        with path.open("r", encoding="utf-8") as stream:
            rows = json.load(stream)
        if not isinstance(rows, list):
            raise ValueError(f"split JSON must contain a list: {path}")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"split manifest must contain JSON objects: {path}")
    return rows
