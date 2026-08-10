"""初始化 ``all_valid.json`` 与 ``info.json``。

``all_valid.json`` 只取现有 split 文件的并集。``info.json`` 覆盖
``raw/pair_list.jsonl`` 中的全部 PDB，并合并历史问题与当前产物扫描结果。
NPZ 扫描只读取 ZIP 中央目录，不解压数组数据。
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath


AUXILIARY_LABEL_PDB_IDS = ("5y6p", "7n6g", "7z8g", "9hhl", "9v7i")

ARTIFACTS = (
    ("parse/{pdb_id}/occurrences.jsonl", "jsonl", ()),
    ("parse/{pdb_id}/ligand_coords.npz", "npz", ()),
    (
        "parse/{pdb_id}/receptor_tokens.npz",
        "npz",
        ("coords", "feat", "bond_index", "bond_type"),
    ),
    (
        "labels/{pdb_id}/atom_labels.npz",
        "npz",
        ("binding_atom", "instance_id", "nearest_dist"),
    ),
    ("density/{pdb_id}/exp.npz", "npz", ("grid", "voxel_size", "origin")),
    ("density/{pdb_id}/sim.npz", "npz", ("grid", "voxel_size", "origin")),
    (
        "density/{pdb_id}/ligand_area.npz",
        "npz",
        ("union_mask", "schema_version"),
    ),
    (
        "density/{pdb_id}/ligand_dist.npz",
        "npz",
        ("distance", "schema_version"),
    ),
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-root",
        required=True,
        type=Path,
        help="AdaLigand Ori_Data 根目录，内含 raw、parse、labels 和 density。",
    )
    parser.add_argument(
        "--catalog-root",
        required=True,
        type=Path,
        help="现有 split 目录所在位置，也是两个 JSON 清单的写出目录。",
    )
    parser.add_argument(
        "--reasons",
        required=True,
        type=Path,
        help="按 PDB 保存已恢复历史问题的 JSON 文件。",
    )
    return parser.parse_args()


def _normalize_pdb_id(value: object, source: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source} 中存在空或非字符串 pdb_id")
    return value.strip().lower()


def _read_pair_pdb_ids(path: Path) -> list[str]:
    pdb_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict) or "pdb_id" not in record:
                raise ValueError(f"{path}:{line_number} 必须是含 pdb_id 的 JSON 对象")
            pdb_ids.add(_normalize_pdb_id(record["pdb_id"], f"{path}:{line_number}"))
    if not pdb_ids:
        raise ValueError(f"{path} 没有 PDB 记录")
    return sorted(pdb_ids)


def _iter_split_items(document: object, path: Path) -> Iterable[object]:
    if isinstance(document, list):
        return document
    if isinstance(document, dict):
        for key in ("entries", "pairs", "items", "pdb_ids"):
            value = document.get(key)
            if isinstance(value, list):
                return value
    raise ValueError(f"{path} 必须是数组，或含 entries/pairs/items/pdb_ids 数组的对象")


def _read_split_union(split_dir: Path) -> list[str]:
    split_paths = sorted(split_dir.glob("*.json"))
    if not split_paths:
        raise ValueError(f"{split_dir} 中没有 split JSON 文件")

    pdb_ids: set[str] = set()
    for path in split_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        for item in _iter_split_items(document, path):
            value = item.get("pdb_id") if isinstance(item, dict) else item
            pdb_ids.add(_normalize_pdb_id(value, str(path)))
    return sorted(pdb_ids)


def _validate_issue(issue: object, source: str) -> dict[str, str]:
    if not isinstance(issue, dict):
        raise ValueError(f"{source} 的问题记录必须是 JSON 对象")
    required = ("action", "reason", "detail")
    if any(not isinstance(issue.get(key), str) or not issue[key] for key in required):
        raise ValueError(f"{source} 的问题记录必须含非空 action/reason/detail")
    unknown = set(issue) - {"action", "reason", "detail", "evidence"}
    if unknown:
        raise ValueError(f"{source} 的问题记录含未知字段: {sorted(unknown)}")
    if "evidence" in issue and (
        not isinstance(issue["evidence"], str) or not issue["evidence"]
    ):
        raise ValueError(f"{source} 的 evidence 必须是非空字符串")
    return {
        key: issue[key]
        for key in ("action", "reason", "detail", "evidence")
        if key in issue
    }


def _read_historical_reasons(
    path: Path, pair_ids: set[str]
) -> dict[str, list[dict[str, str]]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} 必须是以 pdb_id 为键的 JSON 对象")

    result: dict[str, list[dict[str, str]]] = {}
    for raw_pdb_id, issues in document.items():
        pdb_id = _normalize_pdb_id(raw_pdb_id, str(path))
        if pdb_id not in pair_ids:
            raise ValueError(f"{path} 中的 {pdb_id} 不在 raw/pair_list.jsonl")
        if not isinstance(issues, list):
            raise ValueError(f"{path} 中 {pdb_id} 的值必须是问题数组")
        result[pdb_id] = [
            _validate_issue(issue, f"{path}:{pdb_id}") for issue in issues
        ]
    return result


def _issue_key(issue: dict[str, str]) -> tuple[str, str, str, str | None]:
    return (
        issue["action"],
        issue["reason"],
        issue["detail"],
        issue.get("evidence"),
    )


def _append_unique(target: list[dict[str, str]], issue: dict[str, str]) -> None:
    key = _issue_key(issue)
    if all(_issue_key(existing) != key for existing in target):
        target.append(issue)


def _rename_auxiliary_receptor_tokens(data_root: Path) -> None:
    for pdb_id in AUXILIARY_LABEL_PDB_IDS:
        parse_dir = data_root / "parse" / pdb_id
        source = parse_dir / "receptor_tokens.npz"
        target = parse_dir / "receptor_tokens_old.npz"
        if source.exists() and not target.exists():
            os.replace(source, target)
            print(f"[rename] {source} -> {target}")
        elif not source.exists() and target.exists():
            print(f"[rename-already-done] {target}")
        elif source.exists() and target.exists():
            print(
                f"[rename-conflict] source 和 target 均存在，未覆盖: {source}, {target}"
            )
        else:
            print(f"[rename-source-missing] {source}")


def _scan_jsonl(path: Path) -> None:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"第 {line_number} 行不是 JSON 对象")


def _npz_field_names(path: Path) -> set[str]:
    """仅读取 NPZ 的 ZIP 目录，绝不读取或解压任何 NPY 数组。"""

    with zipfile.ZipFile(path, mode="r") as archive:
        members = [item.filename for item in archive.infolist() if not item.is_dir()]
    invalid = [name for name in members if not name.endswith(".npy")]
    if invalid:
        raise ValueError(f"NPZ 含非 NPY 成员: {invalid}")
    return {PurePosixPath(name).name[:-4] for name in members}


def _artifact_issue(relative_path: str, reason: str, detail: str) -> dict[str, str]:
    return {
        "action": "artifact_inventory_scan",
        "reason": reason,
        "detail": detail,
        "evidence": relative_path,
    }


def _scan_artifact(
    data_root: Path,
    pdb_id: str,
    path_template: str,
    kind: str,
    required_fields: tuple[str, ...],
) -> dict[str, str] | None:
    relative_path = path_template.format(pdb_id=pdb_id)
    path = data_root / relative_path
    if not path.is_file():
        return _artifact_issue(
            relative_path,
            "artifact_missing",
            f"当前扫描未找到 {relative_path}。",
        )
    try:
        if kind == "jsonl":
            _scan_jsonl(path)
            return None
        fields = _npz_field_names(path)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
        ValueError,
    ) as error:
        return _artifact_issue(
            relative_path,
            "artifact_unreadable",
            f"当前扫描无法读取 {relative_path}：{type(error).__name__}: {error}",
        )

    missing = sorted(set(required_fields) - fields)
    if missing:
        return _artifact_issue(
            relative_path,
            "artifact_missing_fields",
            f"当前扫描发现 {relative_path} 缺少字段：{', '.join(missing)}。",
        )
    return None


def _atomic_write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(document, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> None:
    args = _parse_args()
    pair_path = args.data_root / "raw" / "pair_list.jsonl"
    split_dir = args.catalog_root / "split"
    pair_pdb_ids = _read_pair_pdb_ids(pair_path)
    pair_id_set = set(pair_pdb_ids)
    split_pdb_ids = _read_split_union(split_dir)
    unknown_split_ids = sorted(set(split_pdb_ids) - pair_id_set)
    if unknown_split_ids:
        raise ValueError(
            "split 中存在 raw/pair_list.jsonl 未登记的 pdb_id: "
            + ", ".join(unknown_split_ids)
        )

    historical = _read_historical_reasons(args.reasons, pair_id_set)
    _rename_auxiliary_receptor_tokens(args.data_root)

    info: dict[str, list[dict[str, str]]] = {pdb_id: [] for pdb_id in pair_pdb_ids}
    for pdb_id, issues in historical.items():
        for issue in issues:
            _append_unique(info[pdb_id], issue)

    scan_issue_count = 0
    for pdb_id in pair_pdb_ids:
        for path_template, kind, required_fields in ARTIFACTS:
            issue = _scan_artifact(
                args.data_root,
                pdb_id,
                path_template,
                kind,
                required_fields,
            )
            if issue is not None:
                _append_unique(info[pdb_id], issue)
                scan_issue_count += 1

    split_id_set = set(split_pdb_ids)
    unknown_issue_count = 0
    for pdb_id in pair_pdb_ids:
        if pdb_id not in split_id_set and pdb_id not in historical:
            _append_unique(
                info[pdb_id],
                {
                    "action": "split_membership",
                    "reason": "unknown_issue",
                    "detail": (
                        "该 PDB 不在 stage1_preparation_box_pool_2/split 的现有划分并集中，"
                        "当前本地历史证据没有恢复出更具体原因。"
                    ),
                    "evidence": "stage1_preparation_box_pool_2/split/*.json",
                },
            )
            unknown_issue_count += 1

    all_valid_path = args.catalog_root / "all_valid.json"
    info_path = args.catalog_root / "info.json"
    _atomic_write_json(all_valid_path, split_pdb_ids)
    _atomic_write_json(info_path, info)

    affected_pdb_count = sum(bool(issues) for issues in info.values())
    print(f"[done] pair_list PDB 数: {len(pair_pdb_ids)}")
    print(f"[done] split 并集 PDB 数: {len(split_pdb_ids)}")
    print(f"[done] 历史问题 PDB 数: {len(historical)}")
    print(f"[done] 当前扫描问题记录数: {scan_issue_count}")
    print(f"[done] unknown_issue PDB 数: {unknown_issue_count}")
    print(f"[done] info.json 非空问题列表 PDB 数: {affected_pdb_count}")
    print(f"[write] {all_valid_path}")
    print(f"[write] {info_path}")


if __name__ == "__main__":
    main()
