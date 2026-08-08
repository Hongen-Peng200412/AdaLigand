"""在 A–G 原始环境中把 CCD 键型审计为版本中立 JSON。"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
import json
import os
from pathlib import Path
import pickle
import tempfile
from typing import Any

from pocketxmol_compat.selection import load_selections, parse_split_specification


AUDIT_SCHEMA = "adaligand.pocketxmol.source_chemistry_audit"
AUDIT_SCHEMA_VERSION = 1
SUPPORTED_BOND_TYPE_NAMES = frozenset({"SINGLE", "DOUBLE", "TRIPLE", "AROMATIC"})


@dataclass(frozen=True)
class CcdAuditRecord:
    """一个 CCD 模板的可移植键型审计结果。"""

    ccd_id: str
    bond_type_names: tuple[str, ...]
    supported: bool
    error: str | None


def build_parser() -> argparse.ArgumentParser:
    """构造只读取清单、occurrence 与 CCD pickle 的审计命令行。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-c-root", type=Path, required=True)
    parser.add_argument(
        "--split",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="可重复传入 train/validation/calibration 的 JSON 或 JSONL 冻结清单。",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """审计清单实际涉及的 CCD，并原子写入不含内容哈希的 JSON。"""

    args = build_parser().parse_args(argv)
    payload = build_ccd_audit(args.stage_c_root, args.split)
    _atomic_write_json(args.output, payload)
    return 0


def build_ccd_audit(stage_c_root: Path, split_specifications: list[str]) -> dict[str, Any]:
    """返回清单实际涉及 CCD 的键型审计；重复 component 只审计一次。"""

    selections = load_selections(split_specifications, stage_c_root)
    ccd_ids = _collect_selected_ccd_ids(stage_c_root, selections)
    records = [_audit_ccd_pickle(stage_c_root, ccd_id) for ccd_id in ccd_ids]
    return {
        "schema": AUDIT_SCHEMA,
        "schema_version": AUDIT_SCHEMA_VERSION,
        "allowed_bond_type_names": sorted(SUPPORTED_BOND_TYPE_NAMES),
        "source_stage_c_root": str(stage_c_root.resolve()),
        "selection_manifests": [
            {"split": split, "path": str(path.resolve())}
            for split, path in map(parse_split_specification, split_specifications)
        ],
        "selected_instance_count": len(selections),
        "ccd_count": len(records),
        "ccd_records": [
            {
                "ccd_id": record.ccd_id,
                "bond_type_names": list(record.bond_type_names),
                "supported": record.supported,
                "error": record.error,
            }
            for record in records
        ],
    }


@lru_cache(maxsize=None)
def load_ccd_audit(path: Path) -> dict[str, CcdAuditRecord]:
    """读取并校验审计 JSON；本函数不会打开任何 CCD pickle。"""

    with path.open("r", encoding="utf-8") as stream:
        payload = json.load(stream)
    if payload.get("schema") != AUDIT_SCHEMA:
        raise ValueError(f"unsupported CCD audit schema: {payload.get('schema')!r}")
    if payload.get("schema_version") != AUDIT_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported CCD audit schema version: {payload.get('schema_version')!r}"
        )
    raw_records = payload.get("ccd_records")
    if not isinstance(raw_records, list):
        raise ValueError("CCD audit ccd_records must be a list")

    records: dict[str, CcdAuditRecord] = {}
    for raw in raw_records:
        if not isinstance(raw, dict):
            raise ValueError("each CCD audit record must be an object")
        ccd_id = str(raw.get("ccd_id", "")).upper()
        raw_names = raw.get("bond_type_names")
        supported = raw.get("supported")
        error = raw.get("error")
        if not ccd_id or not isinstance(raw_names, list) or not all(
            isinstance(name, str) for name in raw_names
        ):
            raise ValueError(f"invalid CCD audit record identity or bond names: {raw!r}")
        if type(supported) is not bool or (error is not None and not isinstance(error, str)):
            raise ValueError(f"invalid CCD audit status: {ccd_id}")
        if ccd_id in records:
            raise ValueError(f"duplicate CCD audit record: {ccd_id}")
        records[ccd_id] = CcdAuditRecord(
            ccd_id=ccd_id,
            bond_type_names=tuple(sorted({name.upper() for name in raw_names})),
            supported=supported,
            error=error,
        )
    return records


def source_chemistry_reasons(
    components: object,
    ccd_audit_path: Path,
) -> tuple[str, ...]:
    """把审计记录转换为稳定过滤原因，不反序列化原始 CCD。"""

    if not isinstance(components, list) or not components:
        return ("source_chemistry_unverifiable",)
    ccd_ids: list[str] = []
    for component in components:
        if not isinstance(component, dict):
            return ("source_chemistry_unverifiable",)
        ccd_id = component.get("ccd_id")
        if not isinstance(ccd_id, str) or not ccd_id.strip():
            return ("source_chemistry_unverifiable",)
        ccd_ids.append(ccd_id.upper())

    records = load_ccd_audit(ccd_audit_path.resolve())
    reasons: list[str] = []
    for ccd_id in dict.fromkeys(ccd_ids):
        record = records.get(ccd_id)
        if record is None or record.error is not None:
            reasons.append("source_chemistry_unverifiable")
        elif not record.supported or not set(record.bond_type_names).issubset(
            SUPPORTED_BOND_TYPE_NAMES
        ):
            reasons.append("unsupported_bond_type")
    return tuple(dict.fromkeys(reasons))


def _collect_selected_ccd_ids(
    stage_c_root: Path,
    selections: list[dict[str, Any]],
) -> list[str]:
    """从选中 occurrence 收集唯一 CCD id，不扫描未选实例。"""

    selected_by_pdb: dict[str, set[int]] = {}
    for row in selections:
        selected_by_pdb.setdefault(str(row["pdb_id"]).lower(), set()).add(
            int(row["candidate_id"])
        )

    ccd_ids: set[str] = set()
    for pdb_id, candidate_ids in sorted(selected_by_pdb.items()):
        path = stage_c_root / "parse" / pdb_id / "occurrences.jsonl"
        with path.open("r", encoding="utf-8") as stream:
            occurrences = [json.loads(line) for line in stream if line.strip()]
        for candidate_id in sorted(candidate_ids):
            matches = [
                row for row in occurrences if int(row.get("candidate_id", -1)) == candidate_id
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"expected exactly one occurrence for {pdb_id}:{candidate_id}, "
                    f"got {len(matches)}"
                )
            components = matches[0].get("components", [])
            if not isinstance(components, list):
                continue
            for component in components:
                if not isinstance(component, dict):
                    continue
                ccd_id = component.get("ccd_id")
                if isinstance(ccd_id, str) and ccd_id.strip():
                    ccd_ids.add(ccd_id.upper())
    return sorted(ccd_ids)


def _audit_ccd_pickle(stage_c_root: Path, ccd_id: str) -> CcdAuditRecord:
    """在产生 CCD pickle 的 A–G 环境中读取一次实际 RDKit 键型名称。"""

    path = stage_c_root / "raw" / "ccd_cache" / f"{ccd_id}.pkl"
    try:
        with path.open("rb") as stream:
            mol = pickle.load(stream)
        names = tuple(
            sorted(
                {
                    str(bond.GetBondType().name).upper()
                    for bond in mol.GetBonds()
                }
            )
        )
    except Exception as exc:
        return CcdAuditRecord(
            ccd_id=ccd_id,
            bond_type_names=(),
            supported=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    return CcdAuditRecord(
        ccd_id=ccd_id,
        bond_type_names=names,
        supported=set(names).issubset(SUPPORTED_BOND_TYPE_NAMES),
        error=None,
    )


def _atomic_write_json(path: Path, payload: Any) -> None:
    """仅用标准库原子写入 UTF-8 JSON。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
