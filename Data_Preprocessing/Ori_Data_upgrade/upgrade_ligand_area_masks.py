"""按 Slurm 数组分片升级现有 ``ligand_area.npz`` 的配体类别体素掩码。

主要入口是 ``main``。程序先按 ``--sample-scope`` 得到排序、去重的全局 PDB
清单，再用 ``global_pdb_ids[shard_index::num_shards]`` 选择当前数组任务负责的
互斥子集。``--array 0-11`` 因而产生 12 个分片，每个 PDB 只会进入一个分片。

每个 PDB 读取 ``parse/{pdb_id}/occurrences.jsonl`` 的 ``candidate_id`` 与
``type_tag``，并合并 ``density/{pdb_id}/ligand_area.npz`` 中相应的
``mask_{candidate_id}`` 稀疏 ZYX 索引。程序把六个 ``bool (1,D,H,W)`` 类别掩码
追加到原 NPZ；D、H、W 分别是 Z、Y、X 轴体素数。其他字段原样写回，程序不重新
计算配体几何，也不更新 ``info.json``。

六个类别字段全部存在时状态为 ``already_complete``；只存在一部分时状态为
``partial_existing_masks`` 且不修改文件；单个 PDB 的异常记为 ``failed`` 并继续
处理当前分片。所有逐样本状态和分片汇总只打印到普通运行日志。
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


# occurrences.jsonl::type_tag 到 ligand_area.npz 新增字段的固定映射。
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
    """读取一个 PDB 的 occurrence 清单。

    参数：
    - ``path``：``parse/{pdb_id}/occurrences.jsonl``；每个非空物理行必须是一个 JSON 对象。

    返回：
    - ``records``：按文件顺序排列的 occurrence 字典；掩码升级至少读取每项的 ``candidate_id`` 整数和 ``type_tag`` 字符串。
    """

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
    """把 occurrence 级稀疏体素索引合并成六个类别级稠密掩码。

    参数：
    - ``arrays``：一个 ``ligand_area.npz`` 的全部字段；``union_mask`` 为 ``bool (1,D,H,W)``，每个 ``mask_{candidate_id}`` 为 ``int32 (K,3)`` 稀疏 ZYX 索引。
    - ``occurrences``：与 ``mask_{candidate_id}`` 对齐的 occurrence 字典列表；同一 ``candidate_id`` 只允许出现一次。

    返回：
    - ``type_masks``：键为六个类别字段名；每个值为 ``bool (1,D,H,W)``，True 表示该体素属于对应 ``type_tag`` 的至少一个配体区域。

    不同类别的掩码彼此独立，因此同一体素可以在多个返回数组中同时为 True。
    """

    # bool (1,D,H,W)，第一维是既有单通道维度，后三维依次是 Z、Y、X。
    union_mask = np.asarray(arrays["union_mask"])
    if (
        union_mask.dtype != np.dtype(bool)
        or union_mask.ndim != 4
        or union_mask.shape[0] != 1
    ):
        raise ValueError("union_mask 必须是 bool (1,D,H,W)")

    # int64 (3,)，用于同时检查每个稀疏 ZYX 索引的下界和上界。
    grid_shape_zyx = np.asarray(union_mask.shape[1:], dtype=np.int64)
    # 每个值均为 bool (1,D,H,W)；空类别保留为全 False。
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
        # int32 (K,3)，每一项依次指向类别稠密掩码的 Z、Y、X 维度。
        indices = np.asarray(arrays[sparse_key])
        if indices.dtype != np.int32 or indices.ndim != 2 or indices.shape[1:] != (3,):
            raise ValueError(f"{sparse_key} 必须是 int32 (K,3)")
        if np.any(indices < 0) or np.any(indices >= grid_shape_zyx):
            raise ValueError(f"{sparse_key} 含越界 ZYX 索引")

        # bool (1,D,H,W)，只把当前 occurrence 覆盖的体素并入所属类别。
        target = type_masks[TYPE_MASK_KEY_BY_TAG[type_tag]]
        target[0, indices[:, 0], indices[:, 1], indices[:, 2]] = True
    return type_masks


def _atomic_replace_ligand_area(
    path: Path,
    arrays: dict[str, np.ndarray],
) -> None:
    """用同目录临时 NPZ 原子替换一个 ``ligand_area.npz``。

    参数：
    - ``path``：正式 ``density/{pdb_id}/ligand_area.npz`` 路径。
    - ``arrays``：待写出的全部旧字段和六个新增类别掩码；旧字段名称、数据类型、形状和值不在本函数中改写。

    副作用：先用 ZIP DEFLATED 压缩写入同目录临时文件，重读并确认字段集合及六个掩码的 ``bool (1,D,H,W)`` 契约，再通过 ``os.replace`` 替换正式文件。失败时删除本次临时文件，不创建发布状态或修改 ``info.json``。
    """

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
    """升级一个 PDB，并返回供主进程打印的普通日志状态。

    参数：
    - ``root``：AdaLigand ``Ori_Data`` 根目录。
    - ``pdb_id``：待处理的 PDB 标识；读取前转换为小写。

    返回：
    - ``pdb_id``：规范化后的小写 PDB 标识。
    - ``status``：``success``、``already_complete``、``partial_existing_masks`` 或 ``failed``。
    - ``detail``：本次状态的具体原因；只进入标准输出日志。

    只有六个类别字段全部不存在时才写文件。六个字段全部存在或部分存在时均不写文件；单个 PDB 的读取、契约或写入异常转换为 ``failed``，不会中断同一分片中的其他 PDB。
    """

    normalized_id = pdb_id.lower()
    ligand_area_path = root / "density" / normalized_id / "ligand_area.npz"
    occurrence_path = root / "parse" / normalized_id / "occurrences.jsonl"
    try:
        if not ligand_area_path.is_file():
            return normalized_id, "failed", "ligand_area.npz 不存在"
        with np.load(ligand_area_path, allow_pickle=False) as archive:
            arrays = {key: archive[key] for key in archive.files}

        # 六字段的存在组合决定重跑行为；已有完整字段绝不重复覆盖。
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
    """读取尚未分片的全局 PDB 清单。

    参数：
    - ``root``：AdaLigand ``Ori_Data`` 根目录。
    - ``sample_scope``：``all_existing`` 枚举现存 ``density/*/ligand_area.npz``；``all_valid`` 读取指定 JSON 清单。
    - ``all_valid_path``：``all_valid.json`` 路径；仅 ``all_valid`` 模式读取。

    返回：
    - ``pdb_ids``：排序、去重且转换为小写的 PDB 标识列表；此时仍包含全部数组任务共同面对的样本。
    """

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


def _select_shard(
    pdb_ids: list[str],
    shard_index: int,
    num_shards: int,
) -> list[str]:
    """从全局 PDB 清单选择当前 Slurm 数组任务负责的互斥分片。

    参数：
    - ``pdb_ids``：排序、去重后的全局 PDB 标识列表。
    - ``shard_index``：当前数组任务的零基编号；``--array 0-11`` 时取值为 0 至 11。
    - ``num_shards``：数组任务总数；``--array 0-11`` 时为 12。

    返回：
    - ``shard_pdb_ids``：``pdb_ids[shard_index::num_shards]`` 的新列表；12 个连续零基分片两两不重叠，其并集严格等于全局清单。

    采用交错切片而不是连续区间，使按 PDB 字典序相邻的样本分散到不同任务；这里只平衡 PDB 数量，不读取密度尺寸或创建特殊样本队列。
    """

    if num_shards < 1:
        raise ValueError("--num-shards 必须为正整数")
    if shard_index < 0 or shard_index >= num_shards:
        raise ValueError("--shard-index 必须位于 [0, --num-shards) 范围内")
    return pdb_ids[shard_index::num_shards]


def _parse_args() -> argparse.Namespace:
    """解析数据根、样本范围、数组分片和分片内进程数。"""

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
    parser.add_argument(
        "--shard-index",
        type=int,
        required=True,
        help="当前 Slurm 数组任务的零基编号",
    )
    parser.add_argument(
        "--num-shards",
        type=int,
        required=True,
        help="Slurm 数组任务总数",
    )
    return parser.parse_args()


def main() -> None:
    """选择当前数组分片并升级其中全部 PDB。

    主进程先加载全局 PDB 清单，再按 ``shard_index`` 和 ``num_shards`` 选择互斥子集。当前分片内部最多启动 ``workers`` 个进程；每个提交给进程池的任务只处理一个 PDB，主进程统一打印逐样本状态和当前分片汇总。逐样本失败不会改变进程最终退出码。
    """

    args = _parse_args()
    if args.workers < 1:
        raise ValueError("--workers 必须为正整数")
    # 全局清单在每个数组任务中独立重建；排序与去重保证所有任务得到相同顺序。
    all_pdb_ids = _load_sample_ids(args.root, args.sample_scope, args.all_valid)
    # 当前列表只含本数组任务负责的 PDB；不同 shard_index 不会写同一个 NPZ。
    pdb_ids = _select_shard(all_pdb_ids, args.shard_index, args.num_shards)
    print(
        "[ligand-area-upgrade] "
        f"scope={args.sample_scope} discovered={len(all_pdb_ids)} "
        f"shard_index={args.shard_index} num_shards={args.num_shards} "
        f"selected={len(pdb_ids)} workers={args.workers}",
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
    print(
        "[ligand-area-upgrade] complete "
        f"shard_index={args.shard_index} num_shards={args.num_shards} "
        f"total={len(pdb_ids)} {summary}",
        flush=True,
    )


if __name__ == "__main__":
    main()
