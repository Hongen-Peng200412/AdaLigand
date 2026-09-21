"""为 test_0 生成七种 Stage1 评估模式共享的 PyMOL 合并会话."""

from __future__ import annotations

import argparse
import json
import os
import pickle
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

import pymol
from chempy.models import Indexed
from pymol import cmd

from build_session import (
    load_density,
    load_ground_truth,
    load_receptor,
    new_atom,
)
from prediction_sources import PredictionCollection, load_predictions


_DEFAULT_PROFILE = (
    Path(__file__).resolve().parent / "profiles" / "stage1_7mode_pcv2_test0.json"
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """解析单 PDB 或完整清单的七模式会话生成参数."""
    parser = argparse.ArgumentParser(
        description="Build combined seven-mode Stage1 PyMOL sessions."
    )
    parser.add_argument("--profile", type=Path, default=_DEFAULT_PROFILE)
    pdb_source = parser.add_mutually_exclusive_group(required=True)
    pdb_source.add_argument("--pdb-id")
    pdb_source.add_argument("--pdb-list", type=Path)
    parser.add_argument(
        "--rank-by",
        choices=("probability_mean", "gaussian"),
        default="probability_mean",
    )
    parser.add_argument("--emap-limit", default="100")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--output-root", type=Path)
    return parser.parse_args(argv)


def _safe_name(value: str) -> str:
    """把 profile 中的稳定模式标识约束为 PyMOL 对象名前缀."""
    normalized = "".join(
        character if character.isalnum() else "_" for character in value
    )
    return normalized.strip("_")


def _load_profile(path: Path) -> dict[str, Any]:
    """读取自包含的七模式路径与显示配置."""
    with path.open("r", encoding="utf-8") as handle:
        profile = json.load(handle)
    required = {"data_root", "receptor_roots", "output_root", "modes"}
    missing = sorted(required.difference(profile))
    if missing:
        raise KeyError(f"{path} is missing profile fields: {', '.join(missing)}")
    if len(profile["modes"]) != 7:
        raise ValueError(f"{path} must define exactly seven modes")
    return profile


def _parse_emap_limit(value: str) -> int | None:
    """把命令行的 ``100|all`` 转为归一化截断值."""
    if value == "all":
        return None
    limit = int(value)
    if limit <= 0:
        raise ValueError("--emap-limit must be a positive integer or all")
    return limit


def _prediction_object_name(
    mode_id: str, rank: int, source_blob_index: int, selected: bool
) -> str:
    """生成含模式前缀、rank、源编号和正式入选状态的稳定对象名."""
    state = "selected" if selected else "unselected"
    return f"{_safe_name(mode_id)}_r{rank:04d}_b{source_blob_index:06d}_{state}"


def _load_prediction_group(
    mode: Mapping[str, Any],
    collection: PredictionCollection,
    origin_center_xyz: np.ndarray,
    voxel_size_xyz: np.ndarray,
) -> list[str]:
    """把一个归一化候选集合写入独立的单层预测组.

    输入数组:
        - origin_center_xyz: float64, (3,), 密度首个体素中心的世界 XYZ 坐标.
        - voxel_size_xyz: float64, (3,), 密度网格沿 XYZ 三轴的体素间距.

    PyMOL 副作用:
        - 每个候选写为一个无键体素伪原子对象；未入选候选默认隐藏.
        - profile 的 ``group`` 直接包含当前模式全部候选，不建立嵌套预测组.
    """
    mode_id = str(mode["id"])
    group_name = str(mode["group"])
    # 标量, 伪原子球半径; 取最窄体素边长的一半以表示单个体素中心.
    sphere_radius = 0.5 * float(np.min(voxel_size_xyz))
    object_names: list[str] = []
    for rank, candidate in enumerate(collection.candidates, start=1):
        # int64, (N_voxel, 3), 当前候选由 ZYX 换轴后的全图 XYZ 体素索引.
        voxel_xyz = candidate.voxel_index_global_zyx[:, ::-1]
        # float64, (N_voxel, 3), 当前候选全部体素中心的世界 XYZ 坐标，单位 Å.
        centers_xyz = origin_center_xyz + voxel_xyz * voxel_size_xyz
        model = Indexed()
        for center_xyz in centers_xyz:
            atom = new_atom(
                coord_xyz=center_xyz,
                symbol="C",
                name="V",
                residue_name="BLB",
                residue_id=str(rank),
                chain_id="P",
                formal_charge=0,
                insertion_code="",
            )
            atom.b = candidate.source_probability_mean
            atom.q = 1.0 if candidate.candidate_selected else 0.0
            atom.vdw = sphere_radius
            model.atom.append(atom)
        object_name = _prediction_object_name(
            mode_id,
            rank,
            candidate.source_blob_index,
            candidate.candidate_selected,
        )
        cmd.load_model(model, object_name)
        cmd.show("spheres", object_name)
        cmd.set("sphere_scale", 1.0, object_name)
        cmd.set_title(
            object_name,
            1,
            (
                f"mode={mode_id}; rank={rank}; "
                f"rank_by={collection.effective_rank_by}; "
                f"source_blob_index={candidate.source_blob_index}; "
                f"source_probability_mean={candidate.source_probability_mean:.9g}; "
                f"evaluation_score={candidate.evaluation_score:.9g}; "
                f"candidate_selected={candidate.candidate_selected}"
            ),
        )
        if not candidate.candidate_selected:
            cmd.disable(object_name)
        object_names.append(object_name)
    cmd.group(group_name, " ".join(object_names))
    return object_names


def _store_scenes(modes: Sequence[Mapping[str, Any]]) -> None:
    """保存七个命名 scene, 再恢复会话首次打开时的默认显示.

    ``modes[*].group`` 和 ``modes[*].scene`` 分别指定预测组与 scene 名;
    ``modes[*].receptor`` 决定 scene 显示真实受体、CryoAtom2 受体或无受体.
    保存后隐藏所有预测组、CryoAtom2 受体和密度 map, 显示真实受体
    与全部密度 mesh; 密度对象前缀同时兼容单 map 和分块命名.
    """
    prediction_groups = [str(mode["group"]) for mode in modes]
    for mode in modes:
        for group_name in prediction_groups:
            cmd.disable(group_name)
        cmd.disable("receptor_real")
        cmd.disable("receptor_cryoatom2")
        receptor = str(mode["receptor"])
        if receptor == "real":
            cmd.enable("receptor_real")
        elif receptor == "cryoatom2":
            cmd.enable("receptor_cryoatom2")
        elif receptor != "none":
            raise ValueError(f"unsupported receptor source: {receptor}")
        cmd.enable(str(mode["group"]))
        cmd.scene(str(mode["scene"]), "store", animate=0)

    for group_name in prediction_groups:
        cmd.disable(group_name)
    cmd.enable("receptor_real")
    cmd.disable("receptor_cryoatom2")
    for object_name in cmd.get_names("objects"):
        if object_name.startswith("density_exp_mesh"):
            cmd.enable(object_name)
        elif object_name.startswith("density_exp_map"):
            cmd.disable(object_name)


def _atomic_save_session(output_path: Path) -> None:
    """使用 pickle protocol 4 保存压缩二进制会话并原子发布 ``.pse``.

    PyMOL 3.1 默认的 protocol 1 无法序列化超过 4 GiB 的已压缩会话字节串;
    protocol 4 不改变 ``cmd.get_session()`` 产生的会话内容, PyMOL 的加载器可直接解码.
    函数会把当前 PyMOL 会话的 ``session_file`` 更新为最终 ``output_path``, 不恢复旧值.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_name(
        f".{output_path.stem}.tmp-{os.getpid()}{output_path.suffix}"
    )
    try:
        cmd.set("session_file", str(output_path).replace("\\", "/"), quiet=1)
        session = cmd.get_session("", partial=0, quiet=1)
        with temporary_path.open("wb") as handle:
            pickle.dump(session, handle, protocol=4)
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)


# ================================================================================================


def build_comparison_session(
    profile: Mapping[str, Any],
    pdb_id: str,
    output_path: Path,
    *,
    rank_by: str = "probability_mean",
    emap_limit: int | None = 100,
) -> dict[str, Any]:
    """生成一个共享密度和 GT 的七模式合并会话.

    返回值:
        - record: dict, 当前 PDB 的会话路径、字节数及七种模式的候选总数、装入数和排序字段.
    """
    normalized_pdb_id = pdb_id.lower()
    data_root = Path(profile["data_root"])
    receptor_roots = profile["receptor_roots"]
    modes = list(profile["modes"])

    pymol.finish_launching(["pymol", "-cq"])
    cmd.reinitialize()
    cmd.set("retain_order", 1)
    cmd.set("pse_binary_dump", 1)
    cmd.set("session_compression", 1)
    origin_center_xyz, voxel_size_xyz, _contour = load_density(
        data_root, normalized_pdb_id
    )
    load_receptor(
        Path(receptor_roots["real"]),
        normalized_pdb_id,
        object_name="receptor_real",
        group_name="receptors",
    )
    load_receptor(
        Path(receptor_roots["cryoatom2"]),
        normalized_pdb_id,
        object_name="receptor_cryoatom2",
        group_name="receptors",
    )
    load_ground_truth(data_root, normalized_pdb_id)

    mode_records: list[dict[str, Any]] = []
    for mode in modes:
        collection = load_predictions(
            mode,
            normalized_pdb_id,
            rank_by=rank_by,
            emap_limit=emap_limit,
        )
        object_names = _load_prediction_group(
            mode, collection, origin_center_xyz, voxel_size_xyz
        )
        mode_records.append(
            {
                "id": mode["id"],
                "group": mode["group"],
                "scene": mode["scene"],
                "effective_rank_by": collection.effective_rank_by,
                "source_candidate_count": collection.source_candidate_count,
                "loaded_candidate_count": collection.loaded_candidate_count,
                "selected_candidate_count": sum(
                    candidate.candidate_selected for candidate in collection.candidates
                ),
                "object_count": len(object_names),
            }
        )

    cmd.orient("receptor_real or ground_truth")
    _store_scenes(modes)
    _atomic_save_session(output_path)
    return {
        "pdb_id": normalized_pdb_id,
        "session": str(output_path),
        "session_bytes": output_path.stat().st_size,
        "rank_by": rank_by,
        "emap_limit": "all" if emap_limit is None else emap_limit,
        "modes": mode_records,
    }


def _read_pdb_ids(args: argparse.Namespace) -> list[str]:
    """从单个编号或 JSON 清单读取保序、去重后的 PDB 编号."""
    if args.pdb_id is not None:
        raw_ids = [args.pdb_id]
    else:
        with args.pdb_list.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        raw_ids = payload if isinstance(payload, list) else payload["pdb_ids"]
    pdb_ids: list[str] = []
    seen: set[str] = set()
    for value in raw_ids:
        pdb_id = str(value).lower()
        if pdb_id not in seen:
            pdb_ids.append(pdb_id)
            seen.add(pdb_id)
    return pdb_ids


def _read_existing_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """读取可续跑清单；不存在时返回空映射."""
    if not path.is_file():
        return {}
    records: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[str(record["pdb_id"])] = record
    return records


def _atomic_write_text(path: Path, text: str) -> None:
    """在同目录写临时文本后原子发布 JSON 或 JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary_path.write_text(text, encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _worker(task: tuple[dict[str, Any], str, str, str, int | None]) -> dict[str, Any]:
    """在独立进程中生成一个 PDB 会话，隔离 PyMOL 全局状态."""
    profile, pdb_id, output_root_text, rank_by, emap_limit = task
    output_path = Path(output_root_text) / "sessions" / f"{pdb_id}.pse"
    return build_comparison_session(
        profile,
        pdb_id,
        output_path,
        rank_by=rank_by,
        emap_limit=emap_limit,
    )


def run_batch(args: argparse.Namespace) -> dict[str, Any]:
    """并发生成清单中的会话，并原子更新运行清单与汇总."""
    if args.workers <= 0:
        raise ValueError("--workers must be positive")
    profile = _load_profile(args.profile.resolve())
    pdb_ids = _read_pdb_ids(args)
    emap_limit = _parse_emap_limit(args.emap_limit)
    output_root = (
        args.output_root.resolve()
        if args.output_root is not None
        else Path(profile["output_root"])
    )
    sessions_dir = output_root / "sessions"
    manifest_path = output_root / "manifest.jsonl"
    existing = _read_existing_manifest(manifest_path)
    records: dict[str, dict[str, Any]] = {}
    pending: list[str] = []
    for pdb_id in pdb_ids:
        output_path = sessions_dir / f"{pdb_id}.pse"
        record = existing.get(pdb_id)
        expected_limit = "all" if emap_limit is None else emap_limit
        reusable = (
            record is not None
            and output_path.is_file()
            and record.get("rank_by") == args.rank_by
            and record.get("emap_limit") == expected_limit
        )
        if reusable:
            records[pdb_id] = record
        else:
            pending.append(pdb_id)

    tasks = [
        (profile, pdb_id, str(output_root), args.rank_by, emap_limit)
        for pdb_id in pending
    ]
    if tasks:
        with ProcessPoolExecutor(
            max_workers=min(args.workers, len(tasks)), max_tasks_per_child=1
        ) as executor:
            futures = {executor.submit(_worker, task): task[1] for task in tasks}
            failures: list[tuple[str, Exception]] = []
            for future in as_completed(futures):
                pdb_id = futures[future]
                try:
                    record = future.result()
                except (
                    Exception
                ) as error:  # noqa: BLE001 - 汇总全部独立 PDB 的失败后统一退出.
                    failures.append((pdb_id, error))
                    continue
                records[str(record["pdb_id"])] = record
                partial_records = [records[item] for item in pdb_ids if item in records]
                _atomic_write_text(
                    manifest_path,
                    "".join(
                        json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n"
                        for item in partial_records
                    ),
                )
        if failures:
            detail = "; ".join(
                f"{pdb_id}: {type(error).__name__}: {error}"
                for pdb_id, error in failures
            )
            raise RuntimeError(f"session generation failed: {detail}")

    ordered_records = [records[pdb_id] for pdb_id in pdb_ids]
    _atomic_write_text(
        manifest_path,
        "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            for record in ordered_records
        ),
    )
    summary = {
        "profile": str(args.profile.resolve()),
        "output_root": str(output_root),
        "rank_by": args.rank_by,
        "emap_limit": "all" if emap_limit is None else emap_limit,
        "requested_pdb_count": len(pdb_ids),
        "created_pdb_count": len(pending),
        "reused_pdb_count": len(pdb_ids) - len(pending),
        "successful_pdb_count": len(ordered_records),
        "workers": args.workers,
    }
    _atomic_write_text(
        output_root / "run_summary.json",
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """执行七模式合并会话的单样本或批量入口."""
    args = parse_args(argv)
    summary = run_batch(args)
    print(
        "[stage1_pymol_7mode] "
        f"success={summary['successful_pdb_count']} "
        f"created={summary['created_pdb_count']} "
        f"reused={summary['reused_pdb_count']} "
        f"output={summary['output_root']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
