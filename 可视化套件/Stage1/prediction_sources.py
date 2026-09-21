"""把 Pocket Plus 与 Emap2lig 的预测候选归一化为同一可视化契约.

本模块只读取既有 Stage1 产物，不修改候选集合、正式入选状态或评估分数。
``load_predictions`` 是唯一公开读取入口；两种盘上格式的差异被限制在内部读取函数中。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class PredictionCandidate:
    """一个可直接转换为 PyMOL 体素对象的归一化预测候选.

    属性:
        source_blob_index: int, 源产物中的稳定 blob 编号.
        source_probability_mean: float, 源 blob 内体素概率均值.
        evaluation_score: float, 当前评估模式保存的 basic、Gaussian 或官方分数.
        candidate_selected: bool, 正式评估冻结的入选状态.
        voxel_index_global_zyx: int64, (N_voxel, 3), 全图 ZYX 体素索引.
        source_order: int, 候选在 evaluation 文件中的零基位置，用于稳定排序的同分决胜.
    """

    source_blob_index: int
    source_probability_mean: float
    evaluation_score: float
    candidate_selected: bool
    voxel_index_global_zyx: np.ndarray
    source_order: int


@dataclass(frozen=True)
class PredictionCollection:
    """一个评估模式的已排序候选及截断事实.

    属性:
        candidates: tuple[PredictionCandidate, ...], 按可视化 rank 排列的候选.
        source_candidate_count: int, 截断前 evaluation 候选总数.
        loaded_candidate_count: int, 实际写入会话的候选数.
        effective_rank_by: str, 当前模式实际使用的排序分数字段.
    """

    candidates: tuple[PredictionCandidate, ...]
    source_candidate_count: int
    loaded_candidate_count: int
    effective_rank_by: str


def _require_arrays(arrays: Any, names: Sequence[str], path: Path) -> None:
    """拒绝缺少归一化所需字段的 NPZ 文件."""
    missing = [name for name in names if name not in arrays.files]
    if missing:
        raise KeyError(f"{path} is missing required arrays: {', '.join(missing)}")


def _candidate_voxels(
    blob_index: int,
    blob_positions: Mapping[int, int],
    voxel_offsets: np.ndarray,
    voxel_index_global_zyx: np.ndarray,
    blobs_path: Path,
) -> np.ndarray:
    """按稳定 blob 编号提取一个候选的全图 ZYX 体素索引.

    ``blob_positions`` 把稳定源编号映射到 ``voxel_offsets`` 的候选轴位置；返回数组是
    ``int64 (N_voxel, 3)``，三列顺序固定为 Z、Y、X。
    """
    if blob_index not in blob_positions:
        raise KeyError(f"evaluation references missing source_blob_index={blob_index}")
    position = blob_positions[blob_index]
    start = int(voxel_offsets[position])
    stop = int(voxel_offsets[position + 1])
    if not 0 <= start <= stop <= len(voxel_index_global_zyx):
        raise ValueError(f"invalid voxel_offsets in {blobs_path}")
    return np.asarray(voxel_index_global_zyx[start:stop], dtype=np.int64)


def _read_pocket_plus(
    mode: Mapping[str, Any], pdb_id: str
) -> list[PredictionCandidate]:
    """读取 Pocket Plus 的公共 ``blobs + evaluation`` 候选契约.

    ``mode`` 明确提供 artifact 根、producer、split、F-alpha 和 evaluation 名；本函数不
    根据模型名猜测路径。返回列表保持 evaluation 候选轴顺序，尚未执行可视化排序。
    """
    artifact_root = Path(mode["artifact_root"])
    producer = str(mode["producer"])
    split = str(mode["split"])
    alpha = float(mode["alpha"])
    if not math.isfinite(alpha) or alpha <= 0.0:
        raise ValueError(f"mode {mode['id']} alpha must be finite and positive")
    alpha_tag = format(alpha, ".15g").replace(".", "p")
    pdb_root = artifact_root / producer / split / pdb_id
    blobs_path = pdb_root / "blobs" / f"F{alpha_tag}_blobs.npz"
    evaluation_path = pdb_root / "evaluation" / f"{mode['evaluation_name']}.npz"

    with np.load(blobs_path, allow_pickle=False) as blobs:
        _require_arrays(
            blobs,
            (
                "blob_index",
                "source_probability_mean",
                "voxel_offsets",
                "voxel_index_global_zyx",
            ),
            blobs_path,
        )
        # int32, (N_blob,), blobs 候选轴上的稳定标识.
        blob_indices = np.asarray(blobs["blob_index"])
        # float32, (N_blob,), 与 blob_indices 逐候选对齐的源概率均值.
        probability_means = np.asarray(blobs["source_probability_mean"])
        # int64, (N_blob + 1,), 切分串接体素索引的半开区间边界.
        voxel_offsets = np.asarray(blobs["voxel_offsets"])
        # int32, (N_blob_voxel, 3), 所有源 blob 串接后的全图 ZYX 索引.
        voxel_indices = np.asarray(blobs["voxel_index_global_zyx"])
    if probability_means.shape != blob_indices.shape:
        raise ValueError(f"blob probability shape mismatch: {blobs_path}")
    if voxel_offsets.shape != (len(blob_indices) + 1,):
        raise ValueError(f"voxel_offsets length mismatch: {blobs_path}")

    with np.load(evaluation_path, allow_pickle=False) as evaluation:
        _require_arrays(
            evaluation,
            ("source_blob_index", "candidate_score", "candidate_selected"),
            evaluation_path,
        )
        # int32, (N_candidate,), evaluation 候选轴对应的稳定源 blob 编号.
        source_blob_indices = np.asarray(evaluation["source_blob_index"])
        # float32, (N_candidate,), 当前 basic 或 Gaussian 评估分数.
        evaluation_scores = np.asarray(evaluation["candidate_score"])
        # bool, (N_candidate,), 正式评估冻结的入选状态.
        selected = np.asarray(evaluation["candidate_selected"], dtype=bool)
    if not (source_blob_indices.shape == evaluation_scores.shape == selected.shape):
        raise ValueError(
            f"candidate arrays must have identical shapes: {evaluation_path}"
        )

    blob_positions = {
        int(blob_index): position for position, blob_index in enumerate(blob_indices)
    }
    candidates: list[PredictionCandidate] = []
    for source_order, (blob_index_value, score_value, selected_value) in enumerate(
        zip(source_blob_indices, evaluation_scores, selected, strict=True)
    ):
        blob_index = int(blob_index_value)
        position = blob_positions.get(blob_index)
        if position is None:
            raise KeyError(
                f"{evaluation_path} references missing source_blob_index={blob_index}"
            )
        candidates.append(
            PredictionCandidate(
                source_blob_index=blob_index,
                source_probability_mean=float(probability_means[position]),
                evaluation_score=float(score_value),
                candidate_selected=bool(selected_value),
                voxel_index_global_zyx=_candidate_voxels(
                    blob_index,
                    blob_positions,
                    voxel_offsets,
                    voxel_indices,
                    blobs_path,
                ),
                source_order=source_order,
            )
        )
    return candidates


def _read_emap2lig(mode: Mapping[str, Any], pdb_id: str) -> list[PredictionCandidate]:
    """读取 Emap2lig 的 ``official_blobs + per_pdb evaluation`` 候选契约.

    ``mode`` 只需提供 official Find-Li 结果根。返回列表保持逐 PDB evaluation 候选轴
    顺序，Top 100 或 ``all`` 的选择在公共入口完成。
    """
    result_root = Path(mode["result_root"])
    blobs_path = result_root / "mapped" / pdb_id / "official_blobs.npz"
    evaluation_path = result_root / "evaluation" / "per_pdb" / f"{pdb_id}.npz"
    with np.load(blobs_path, allow_pickle=False) as blobs:
        _require_arrays(
            blobs,
            (
                "source_blob_index",
                "source_probability_mean",
                "voxel_offsets",
                "voxel_index_global_zyx",
            ),
            blobs_path,
        )
        # int32, (N_blob,), 官方候选轴上的稳定 blob 编号.
        blob_indices = np.asarray(blobs["source_blob_index"])
        # float32, (N_blob,), 与 blob_indices 对齐的官方源概率均值.
        probability_means = np.asarray(blobs["source_probability_mean"])
        # int64, (N_blob + 1,), 切分官方串接体素索引的半开区间边界.
        voxel_offsets = np.asarray(blobs["voxel_offsets"])
        # int32, (N_blob_voxel, 3), 所有官方候选串接后的全图 ZYX 索引.
        voxel_indices = np.asarray(blobs["voxel_index_global_zyx"])
    if probability_means.shape != blob_indices.shape:
        raise ValueError(f"blob probability shape mismatch: {blobs_path}")
    if voxel_offsets.shape != (len(blob_indices) + 1,):
        raise ValueError(f"voxel_offsets length mismatch: {blobs_path}")

    with np.load(evaluation_path, allow_pickle=False) as evaluation:
        _require_arrays(
            evaluation,
            ("source_blob_index", "candidate_score", "candidate_selected"),
            evaluation_path,
        )
        # int32, (N_candidate,), 官方逐 PDB 评估候选轴的源 blob 编号.
        source_blob_indices = np.asarray(evaluation["source_blob_index"])
        # float32, (N_candidate,), Emap2lig 官方 Find-Li 分数.
        evaluation_scores = np.asarray(evaluation["candidate_score"])
        # bool, (N_candidate,), Emap2lig 正式评估保存的入选状态.
        selected = np.asarray(evaluation["candidate_selected"], dtype=bool)
    if not (source_blob_indices.shape == evaluation_scores.shape == selected.shape):
        raise ValueError(
            f"candidate arrays must have identical shapes: {evaluation_path}"
        )

    blob_positions = {
        int(blob_index): position for position, blob_index in enumerate(blob_indices)
    }
    candidates: list[PredictionCandidate] = []
    for source_order, (blob_index_value, score_value, selected_value) in enumerate(
        zip(source_blob_indices, evaluation_scores, selected, strict=True)
    ):
        blob_index = int(blob_index_value)
        position = blob_positions.get(blob_index)
        if position is None:
            raise KeyError(
                f"{evaluation_path} references missing source_blob_index={blob_index}"
            )
        candidates.append(
            PredictionCandidate(
                source_blob_index=blob_index,
                source_probability_mean=float(probability_means[position]),
                evaluation_score=float(score_value),
                candidate_selected=bool(selected_value),
                voxel_index_global_zyx=_candidate_voxels(
                    blob_index,
                    blob_positions,
                    voxel_offsets,
                    voxel_indices,
                    blobs_path,
                ),
                source_order=source_order,
            )
        )
    return candidates


# ================================================================================================


def load_predictions(
    mode: Mapping[str, Any],
    pdb_id: str,
    *,
    rank_by: str = "probability_mean",
    emap_limit: int | None = 100,
) -> PredictionCollection:
    """读取、稳定排序并按模式规则截断一个 PDB 的预测候选.

    输入参数:
        - mode: Mapping, profile 中的一项模式配置; ``contract`` 必须是 ``pocket_plus`` 或 ``emap2lig``.
        - pdb_id: str, 小写 PDB 编号.
        - rank_by: str, ``probability_mean`` 或 ``gaussian``. Gaussian 只对 ``gaussian_rank=true`` 的模式生效.
        - emap_limit: int | None, Emap2lig 最多写入的候选数; ``None`` 表示全部候选.

    返回值:
        - collection: PredictionCollection, 保留正式候选属性并仅改变可视化 rank 的归一化候选集合.
    """
    if rank_by not in {"probability_mean", "gaussian"}:
        raise ValueError("rank_by must be probability_mean or gaussian")
    contract = str(mode["contract"])
    if contract == "pocket_plus":
        candidates = _read_pocket_plus(mode, pdb_id)
    elif contract == "emap2lig":
        candidates = _read_emap2lig(mode, pdb_id)
    else:
        raise ValueError(f"unsupported prediction contract: {contract}")

    # use_gaussian 只由调用者开关和 profile 显式能力共同决定；模型名不参与判断.
    use_gaussian = rank_by == "gaussian" and bool(mode.get("gaussian_rank", False))
    effective_rank_by = "gaussian" if use_gaussian else "probability_mean"
    # 长度 N_candidate 的新列表；Python 排序稳定，source_order 显式固定同分时的 evaluation 顺序.
    ranked = sorted(
        candidates,
        key=lambda candidate: (
            -(
                candidate.evaluation_score
                if use_gaussian
                else candidate.source_probability_mean
            ),
            candidate.source_order,
        ),
    )
    # source_count 是 evaluation 候选总数；只有 Emap2lig 会在记录该值后执行可视化截断.
    source_count = len(ranked)
    if contract == "emap2lig" and emap_limit is not None:
        if emap_limit <= 0:
            raise ValueError("emap_limit must be positive or None")
        ranked = ranked[:emap_limit]
    return PredictionCollection(
        candidates=tuple(ranked),
        source_candidate_count=source_count,
        loaded_candidate_count=len(ranked),
        effective_rank_by=effective_rank_by,
    )
