"""读取 Stage3 冻结实例清单；本模块只依赖 Python 标准库。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_selections(specifications: list[str]) -> list[dict[str, Any]]:
    """读取 ``NAME=PATH`` 清单，并保留实例身份与既有数据划分。"""

    output: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for specification in specifications:
        split, path = parse_split_specification(specification)
        rows = _read_manifest(path)
        for row in rows:
            key = (str(row["pdb_id"]).lower(), int(row["candidate_id"]))
            if key in seen:
                raise ValueError(f"duplicate or cross-split instance: {key[0]}:{key[1]}")
            seen.add(key)
            output.append({"pdb_id": key[0], "candidate_id": key[1], "split": split})
    return output


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
