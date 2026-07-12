"""A–G 产物契约与 schema-aware 完成判据。

当前先实现 Stage C 的 `COMPLETE / UPGRADE / REBUILD` 状态机。它把“文件路径存在”与
“文件满足当前契约”分开：旧三件套内部一致但缺新字段时进入 `UPGRADE`；旧核心件缺失、
损坏或跨文件行序不一致时才进入 `REBUILD`。后续 D–G validator 也统一放在本模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from constants import RECEPTOR_BOND_TYPE_TO_ID
from io_utils import read_jsonl, safe_object_filename
from ligand_descriptors import ligand_descriptor_is_valid


RECEPTOR_BASE_DTYPES = {
    "coords": np.dtype(np.float32),
    "element": np.dtype(np.uint8),
    "res_type": np.dtype(np.uint8),
    "is_backbone": np.dtype(bool),
    "atom_name": np.dtype("S4"),
    "res_index": np.dtype(np.int32),
    "chain_index": np.dtype(np.int32),
}


class CArtifactState(str, Enum):
    """Stage C 单样本相对当前契约的三态判定。"""

    COMPLETE = "complete"
    UPGRADE = "upgrade"
    REBUILD = "rebuild"


@dataclass(frozen=True)
class CInspection:
    """
    Stage C 单样本契约检查结果。

    输入参数:
        - state: CArtifactState, COMPLETE/UPGRADE/REBUILD
        - reasons: tuple[str,...], 使状态不完整的稳定诊断信息
        - occurrences: tuple[dict[str,Any],...], 成功读取的 occurrence；核心损坏时为空
    """

    state: CArtifactState
    reasons: tuple[str, ...]
    occurrences: tuple[dict[str, Any], ...]


def inspect_stage_c(root: Path, pdb_id: str) -> CInspection:
    """
    检查一个 PDB 的 Stage C 产物应跳过、增量升级还是完整重建。

    输入参数:
        - root: Path, Stage root
        - pdb_id: str, PDB id，大小写不敏感

    输出:
        - inspection: CInspection, 包含状态、原因和已验证 occurrence
    """
    normalized_id = pdb_id.lower()
    parse_dir = root / "parse" / normalized_id
    occurrence_path = parse_dir / "occurrences.jsonl"
    receptor_path = parse_dir / "receptor_tokens.npz"
    coords_path = parse_dir / "ligand_coords.npz"
    missing_paths = [
        str(path.relative_to(root))
        for path in (occurrence_path, receptor_path, coords_path)
        if not path.exists()
    ]
    if missing_paths:
        return CInspection(
            CArtifactState.REBUILD,
            tuple(f"missing_core:{path}" for path in missing_paths),
            (),
        )

    try:
        occurrences = read_jsonl(occurrence_path)
        coords_arrays = _load_npz_arrays(coords_path, allow_pickle=False)
        receptor_arrays = _load_npz_arrays(receptor_path, allow_pickle=False)
    except (OSError, ValueError, KeyError) as exc:
        return CInspection(CArtifactState.REBUILD, (f"unreadable_core:{exc}",), ())

    occurrence_reasons = _validate_occurrences(occurrences)
    if occurrence_reasons:
        return CInspection(CArtifactState.REBUILD, tuple(occurrence_reasons), ())

    core_reasons = []
    core_reasons.extend(_validate_ligand_coords_core(root, occurrences, coords_arrays))
    core_reasons.extend(validate_receptor_arrays(receptor_arrays, require_new=False))
    if core_reasons:
        return CInspection(CArtifactState.REBUILD, tuple(core_reasons), ())

    upgrade_reasons = []
    upgrade_reasons.extend(_validate_ligand_centroids(occurrences, coords_arrays))
    upgrade_reasons.extend(validate_receptor_arrays(receptor_arrays, require_new=True))
    checked_objects: set[str] = set()
    for occurrence in occurrences:
        object_key = str(occurrence["object_key"])
        if object_key in checked_objects:
            continue
        checked_objects.add(object_key)
        descriptor_path = root / "ligand_descriptors" / f"{safe_object_filename(object_key)}.npz"
        if not ligand_descriptor_is_valid(descriptor_path):
            upgrade_reasons.append(f"descriptor_invalid:{object_key}")

    state = CArtifactState.UPGRADE if upgrade_reasons else CArtifactState.COMPLETE
    return CInspection(state, tuple(upgrade_reasons), tuple(occurrences))


def validate_receptor_arrays(
    arrays: dict[str, np.ndarray],
    require_new: bool,
) -> list[str]:
    """
    验证 receptor_tokens 的旧基础数组以及可选的新契约数组。

    输入参数:
        - arrays: dict[str,np.ndarray], 从 receptor_tokens 复制出的数组
        - require_new: bool, True 时还要求 bond_index/bond_type/feat

    输出:
        - reasons: list[str], 空列表表示通过；每项是稳定诊断码
    """
    reasons: list[str] = []
    missing_base = set(RECEPTOR_BASE_DTYPES).difference(arrays)
    if missing_base:
        return [f"receptor_missing:{key}" for key in sorted(missing_base)]

    n_atoms = arrays["coords"].shape[0] if arrays["coords"].ndim == 2 else -1
    if arrays["coords"].ndim != 2 or arrays["coords"].shape[1:] != (3,):
        reasons.append("receptor_shape:coords")
    for key, dtype in RECEPTOR_BASE_DTYPES.items():
        if arrays[key].dtype != dtype:
            reasons.append(f"receptor_dtype:{key}")
    for key in ("element", "res_type", "is_backbone", "atom_name", "res_index", "chain_index"):
        if arrays[key].ndim != 1 or len(arrays[key]) != n_atoms:
            reasons.append(f"receptor_shape:{key}")
    if not np.isfinite(arrays["coords"]).all():
        reasons.append("receptor_nonfinite:coords")

    if not require_new:
        return reasons
    for key in ("bond_index", "bond_type", "feat"):
        if key not in arrays:
            reasons.append(f"receptor_missing:{key}")
    if reasons:
        return reasons

    bond_index = arrays["bond_index"]
    bond_type = arrays["bond_type"]
    feat = arrays["feat"]
    if bond_index.dtype != np.int32 or bond_index.ndim != 2 or bond_index.shape[0] != 2:
        reasons.append("receptor_contract:bond_index")
    if bond_type.dtype != np.uint8 or bond_type.ndim != 1:
        reasons.append("receptor_contract:bond_type")
    if bond_index.ndim == 2 and bond_index.shape[0] == 2 and len(bond_type) != bond_index.shape[1]:
        reasons.append("receptor_contract:bond_count")
    if bond_index.size and (bond_index.min() < 0 or bond_index.max() >= n_atoms):
        reasons.append("receptor_contract:bond_range")
    if bond_type.size and bond_type.max() > max(RECEPTOR_BOND_TYPE_TO_ID.values()):
        reasons.append("receptor_contract:bond_type_range")
    if feat.dtype != np.float32 or feat.shape != (n_atoms, 49):
        reasons.append("receptor_contract:feat")
    elif not np.isfinite(feat).all():
        reasons.append("receptor_nonfinite:feat")
    return reasons


def compare_receptor_base_arrays(
    old_arrays: dict[str, np.ndarray],
    rebuilt_arrays: dict[str, np.ndarray],
) -> list[str]:
    """
    比较升级前后旧 7 个基础数组，防止增量迁移静默改变行序或数值。

    输入参数:
        - old_arrays: dict[str,np.ndarray], 服务器旧 receptor_tokens 数组
        - rebuilt_arrays: dict[str,np.ndarray], 当前 mmCIF 重新解析得到的数组

    输出:
        - reasons: list[str], 空列表表示逐项完全一致（浮点 NaN 也按相同位置处理）
    """
    reasons = []
    for key in RECEPTOR_BASE_DTYPES:
        if key not in old_arrays or key not in rebuilt_arrays:
            reasons.append(f"receptor_base_missing:{key}")
            continue
        if np.issubdtype(old_arrays[key].dtype, np.floating):
            unchanged = np.array_equal(old_arrays[key], rebuilt_arrays[key], equal_nan=True)
        else:
            unchanged = np.array_equal(old_arrays[key], rebuilt_arrays[key])
        if not unchanged:
            reasons.append(f"receptor_base_changed:{key}")
    return reasons


def load_npz_arrays(path: Path, allow_pickle: bool) -> dict[str, np.ndarray]:
    """
    读取 NPZ 并复制数组，使文件句柄在返回前关闭。

    输入参数:
        - path: Path, NPZ 路径
        - allow_pickle: bool, 是否允许对象数组

    输出:
        - arrays: dict[str,np.ndarray], 与文件 key 一一对应的内存副本
    """
    return _load_npz_arrays(path, allow_pickle)


def validate_stage_c_payload(
    root: Path,
    occurrences: list[dict[str, Any]],
    ligand_coords: dict[str, np.ndarray],
    receptor: dict[str, np.ndarray],
) -> list[str]:
    """
    在不写正式路径的前提下验证一套内存 Stage C 三件套。

    输入参数:
        - root: Path, Stage root，用于定位去重 `LigandObject`
        - occurrences: list[dict[str,Any]], 当前 PDB 的 occurrence 记录
        - ligand_coords: dict[str,np.ndarray], `ligand_coords.npz` 的全部数组
        - receptor: dict[str,np.ndarray], `receptor_tokens.npz` 的全部数组

    输出:
        - reasons: list[str], 空列表表示 occurrence 主键、配体坐标/质心与新版
          receptor schema 全部满足当前 Stage C 契约
    """
    reasons = _validate_occurrences(occurrences)
    reasons.extend(_validate_ligand_coords_core(root, occurrences, ligand_coords))
    reasons.extend(_validate_ligand_centroids(occurrences, ligand_coords))
    reasons.extend(validate_receptor_arrays(receptor, require_new=True))
    return reasons


def _load_npz_arrays(path: Path, allow_pickle: bool) -> dict[str, np.ndarray]:
    """实现 `load_npz_arrays` 的文件句柄作用域。"""
    with np.load(path, allow_pickle=allow_pickle) as data:
        return {key: data[key].copy() for key in data.files}


def _validate_occurrences(occurrences: list[dict[str, Any]]) -> list[str]:
    """验证 occurrence 主键和必需字段。"""
    reasons = []
    candidate_ids = []
    for index, occurrence in enumerate(occurrences):
        for key in ("pdb_id", "candidate_id", "object_key", "components"):
            if key not in occurrence:
                reasons.append(f"occurrence_missing:{index}:{key}")
        if "candidate_id" in occurrence:
            candidate_ids.append(occurrence["candidate_id"])
    if any(not isinstance(candidate_id, int) or candidate_id < 0 for candidate_id in candidate_ids):
        reasons.append("occurrence_invalid:candidate_id")
    if len(candidate_ids) != len(set(candidate_ids)):
        reasons.append("occurrence_duplicate:candidate_id")
    return reasons


def _validate_ligand_coords_core(
    root: Path,
    occurrences: list[dict[str, Any]],
    coords_arrays: dict[str, np.ndarray],
) -> list[str]:
    """验证 coords/present 与对应 LigandObject 行数、dtype 和 NaN 语义。"""
    reasons = []
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        coords_key = f"coords_{candidate_id}"
        present_key = f"present_{candidate_id}"
        if coords_key not in coords_arrays or present_key not in coords_arrays:
            reasons.append(f"ligand_coords_missing:{candidate_id}")
            continue
        coords = coords_arrays[coords_key]
        present = coords_arrays[present_key]
        object_path = root / "ligand_objects" / f"{safe_object_filename(str(occurrence['object_key']))}.npz"
        try:
            with np.load(object_path, allow_pickle=True) as ligand_object:
                n_object_atoms = len(ligand_object["atoms"])
        except (OSError, ValueError, KeyError) as exc:
            reasons.append(f"ligand_object_invalid:{occurrence['object_key']}:{exc}")
            continue
        if coords.dtype != np.float32 or coords.shape != (n_object_atoms, 3):
            reasons.append(f"ligand_coords_contract:{candidate_id}:coords")
        if present.dtype != np.dtype(bool) or present.shape != (n_object_atoms,):
            reasons.append(f"ligand_coords_contract:{candidate_id}:present")
            continue
        if coords.shape == (n_object_atoms, 3):
            if not np.isfinite(coords[present]).all():
                reasons.append(f"ligand_coords_nonfinite_present:{candidate_id}")
            if not np.isnan(coords[~present]).all():
                reasons.append(f"ligand_coords_missing_not_nan:{candidate_id}")
    return reasons


def _validate_ligand_centroids(
    occurrences: list[dict[str, Any]],
    coords_arrays: dict[str, np.ndarray],
) -> list[str]:
    """验证每个 occurrence 的 centroid_atom key、dtype、shape 和派生值。"""
    reasons = []
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        centroid_key = f"centroid_atom_{candidate_id}"
        if centroid_key not in coords_arrays:
            reasons.append(f"ligand_centroid_missing:{candidate_id}")
            continue
        centroid = coords_arrays[centroid_key]
        coords = coords_arrays[f"coords_{candidate_id}"]
        present = coords_arrays[f"present_{candidate_id}"]
        if centroid.dtype != np.float32 or centroid.shape != (3,):
            reasons.append(f"ligand_centroid_contract:{candidate_id}")
            continue
        if not present.any():
            reasons.append(f"ligand_centroid_no_present:{candidate_id}")
            continue
        expected = coords[present].mean(axis=0, dtype=np.float64).astype(np.float32)
        if not np.allclose(centroid, expected, rtol=0, atol=1e-5):
            reasons.append(f"ligand_centroid_value:{candidate_id}")
    return reasons
