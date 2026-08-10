"""在现有 ``ligand_area.npz`` 中追加六个配体类别体素掩码。

本入口只合并文件内已有的 ``mask_{candidate_id}`` 稀疏 ZYX 索引，不重新计算
配体几何。每个新增字段都是 ``bool (1,D,H,W)``；旧字段原样写回。六个字段已经
全部存在时跳过，只有部分字段存在时也不改文件，只把状态打印到普通运行日志。
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from uuid import uuid4

import numpy as np


TYPE_MASK_KEY_BY_TAG = {
    "ion": "ion_mask",
    "nucleotide_like": "nucleotide_like_mask",
    "peptide_like": "peptide_like_mask",
    "small_molecule": "small_molecule_mask",
    "sugar": "sugar_mask",
    "other": "other_mask",
}
TYPE_MASK_KEYS = tuple(TYPE_MASK_KEY_BY_TAG.values())


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    """读取每行一个 JSON 对象的 UTF-8 文件。"""

    records: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def _build_type_masks(
    arrays: dict[str, np.ndarray],
    occurrences: list[dict[str, object]],
) -> dict[str, np.ndarray]:
    """按 occurrence 的 ``type_tag`` 合并已有稀疏掩码。"""

    union_mask = np.asarray(arrays["union_mask"])
    if (
        union_mask.dtype != np.dtype(bool)
        or union_mask.ndim != 4
        or union_mask.shape[0] != 1
    ):
        raise ValueError("union_mask 必须是 bool (1,D,H,W)")

    grid_shape_zyx = np.asarray(union_mask.shape[1:], dtype=np.int64)
    type_masks = {key: np.zeros(union_mask.shape, dtype=bool) for key in TYPE_MASK_KEYS}
    seen_candidate_ids: set[int] = set()
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        if candidate_id in seen_candidate_ids:
            raise ValueError(f"candidate_id 重复: {candidate_id}")
        seen_candidate_ids.add(candidate_id)

        type_tag = str(occurrence["type_tag"])
        if type_tag not in TYPE_MASK_KEY_BY_TAG:
            raise ValueError(f"未知 type_tag: {type_tag}")
        sparse_key = f"mask_{candidate_id}"
        if sparse_key not in arrays:
            raise KeyError(f"缺少 {sparse_key}")
        indices = np.asarray(arrays[sparse_key])
        if indices.dtype != np.int32 or indices.ndim != 2 or indices.shape[1:] != (3,):
            raise ValueError(f"{sparse_key} 必须是 int32 (K,3)")
        if np.any(indices < 0) or np.any(indices >= grid_shape_zyx):
            raise ValueError(f"{sparse_key} 含越界 ZYX 索引")

        target = type_masks[TYPE_MASK_KEY_BY_TAG[type_tag]]
        target[0, indices[:, 0], indices[:, 1], indices[:, 2]] = True
    return type_masks


def _atomic_replace_ligand_area(
    path: Path,
    arrays: dict[str, np.ndarray],
) -> None:
    """压缩写入同目录临时文件，重读新增字段后原子替换正式文件。"""

    temporary_path = path.with_name(f".{path.name}.tmp.{os.getpid()}.{uuid4().hex}.npz")
    try:
        np.savez_compressed(temporary_path, **arrays)
        with np.load(temporary_path, allow_pickle=False) as written:
            if set(written.files) != set(arrays):
                raise RuntimeError("写后字段集合不一致")
            expected_shape = np.asarray(arrays["union_mask"]).shape
            for key in TYPE_MASK_KEYS:
                value = np.asarray(written[key])
                if value.dtype != np.dtype(bool) or value.shape != expected_shape:
                    raise RuntimeError(f"写后字段不合法: {key}")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def upgrade_one(root: Path, pdb_id: str) -> tuple[str, str, str]:
    """升级一个 PDB，返回 ``(pdb_id, status, detail)`` 供主进程打印。"""

    normalized_id = pdb_id.lower()
    ligand_area_path = root / "density" / normalized_id / "ligand_area.npz"
    occurrence_path = root / "parse" / normalized_id / "occurrences.jsonl"
    try:
        if not ligand_area_path.is_file():
            return normalized_id, "failed", "ligand_area.npz 不存在"
        with np.load(ligand_area_path, allow_pickle=False) as archive:
            arrays = {key: archive[key] for key in archive.files}

        present_keys = set(TYPE_MASK_KEYS).intersection(arrays)
        if len(present_keys) == len(TYPE_MASK_KEYS):
            return normalized_id, "already_complete", "六个类别掩码已经存在"
        if present_keys:
            return (
                normalized_id,
                "partial_existing_masks",
                "已存在字段=" + ",".join(sorted(present_keys)),
            )

        occurrences = _read_jsonl(occurrence_path)
        arrays.update(_build_type_masks(arrays, occurrences))
        _atomic_replace_ligand_area(ligand_area_path, arrays)
        return normalized_id, "success", "六个类别掩码已追加"
    except Exception as exc:  # 单个样本失败不能中断其余 PDB。
        detail = str(exc).replace("\n", " ")
        return normalized_id, "failed", f"{type(exc).__name__}: {detail}"


def _load_sample_ids(root: Path, sample_scope: str, all_valid_path: Path) -> list[str]:
    """根据显式范围读取待处理 PDB。"""

    if sample_scope == "all_existing":
        density_root = root / "density"
        return sorted(
            {
                path.parent.name.lower()
                for path in density_root.glob("*/ligand_area.npz")
                if path.is_file()
            }
        )

    with all_valid_path.open("r", encoding="utf-8") as handle:
        values = json.load(handle)
    if not isinstance(values, list):
        raise ValueError("all_valid.json 顶层必须是 PDB 字符串数组")
    return sorted({str(value).lower() for value in values})


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, required=True, help="AdaLigand Ori_Data 根目录"
    )
    parser.add_argument(
        "--sample-scope",
        choices=("all_valid", "all_existing"),
        required=True,
        help="处理 all_valid.json 内样本，或处理所有现存 ligand_area.npz",
    )
    parser.add_argument(
        "--all-valid",
        type=Path,
        required=True,
        help="all_valid.json 路径；all_existing 模式不会读取其内容",
    )
    parser.add_argument("--workers", type=int, default=1, help="并行 PDB 数")
    return parser.parse_args()


def main() -> None:
    """解析范围并升级全部目标 PDB；逐样本问题只进入标准输出日志。"""

    args = _parse_args()
    if args.workers < 1:
        raise ValueError("--workers 必须为正整数")
    pdb_ids = _load_sample_ids(args.root, args.sample_scope, args.all_valid)
    print(
        "[ligand-area-upgrade] "
        f"scope={args.sample_scope} discovered={len(pdb_ids)} workers={args.workers}",
        flush=True,
    )

    counts: Counter[str] = Counter()
    if args.workers == 1:
        results = (upgrade_one(args.root, pdb_id) for pdb_id in pdb_ids)
        for pdb_id, status, detail in results:
            counts[status] += 1
            print(
                f"[ligand-area-upgrade] pdb_id={pdb_id} status={status} detail={detail}",
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(upgrade_one, args.root, pdb_id): pdb_id
                for pdb_id in pdb_ids
            }
            for future in as_completed(futures):
                pdb_id = futures[future]
                try:
                    _, status, detail = future.result()
                except Exception as exc:
                    status = "failed"
                    detail = (
                        f"worker {type(exc).__name__}: {str(exc).replace(chr(10), ' ')}"
                    )
                counts[status] += 1
                print(
                    f"[ligand-area-upgrade] pdb_id={pdb_id} status={status} detail={detail}",
                    flush=True,
                )

    summary = " ".join(f"{key}={counts[key]}" for key in sorted(counts))
    print(f"[ligand-area-upgrade] complete total={len(pdb_ids)} {summary}", flush=True)


if __name__ == "__main__":
    main()
