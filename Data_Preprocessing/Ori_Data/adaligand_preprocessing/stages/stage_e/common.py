"""Stage E 共用的坐标系、等高线与范德华半径规则。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
from rdkit import Chem

from adaligand_preprocessing.artifacts.failures import KnownFailureCode, KnownSampleFailure
from adaligand_preprocessing.artifacts.validation import (
    MODEL_MAP_FRAME_ATOL_ANGSTROM,
    density_grid_physical_bounds,
    model_map_frame_errors,
)

EXP_SCHEMA_VERSION = 2
LIGAND_AREA_SCHEMA_VERSION = 3
SIM_SCHEMA_VERSION = 2
MRC_TARGET_VOXEL_SIZE = 1.0
MRC_SOURCE_ORIGIN_MODE = "pocket_plus_multiply_global_origin_true"
MRC_GENERATED_ORIGIN_MODE = "header_origin_angstrom_nstart_zero"
VDW_RADIUS_OVERRIDES = {
    6: 1.70,   # C
    7: 1.55,   # N
    8: 1.52,   # O
    15: 1.80,  # P
    16: 1.80,  # S
}
VDW_RADIUS_SOURCE = "plan_locked_C_N_O_P_S;RDKit_PeriodicTable_GetRvdw_fallback"
LIGAND_AREA_ORIGIN_SEMANTICS = "pocket_plus_corner"
LIGAND_AREA_VOXEL_CENTER_OFFSET_XYZ = (0.5, 0.5, 0.5)
LIGAND_AREA_VOXEL_CENTER_FORMULA = (
    "origin_xyz+(index_xyz+0.5)*voxel_size_xyz"
)
LIGAND_AREA_VOXEL_CENTER_DTYPE = "float32_after_pocket_plus_expression"
LIGAND_AREA_DISTANCE_PREDICATE = (
    "sum((center_f32-atom_f32)^2)_float64<=vdw_radius^2+1e-8"
)
LIGAND_AREA_STORAGE_ENCODING = "numpy_savez_compressed_zip_deflated"
_PERIODIC_TABLE = Chem.GetPeriodicTable()


def ensure_model_map_frame_compatible(
    pdb_id: str,
    map_arrays: dict[str, np.ndarray],
    model_coords: np.ndarray,
) -> None:
    """
    在外部工具运行前对 E/F 共享的 model-map 世界坐标契约分类。

    输入参数:
        - pdb_id: str, 小写 PDB id，用于稳定失败详情
        - map_arrays: dict[str,np.ndarray], E1 canonical 密度图数组，``grid`` 为 ``(1,Z,Y,X)``
        - model_coords: np.ndarray, ``(N,3) float32``，Stage C polymer receptor token 世界 XYZ 坐标

    输出:
        - None: 包围盒相交时正常返回

    异常:
        - KnownSampleFailure: 仅当合法输入的两个包围盒完全分离，失败码为 ``model_map_frame_mismatch``
        - RuntimeError: 坐标或网格本身不满足契约，不得降级为 known failure
    """
    frame_errors = model_map_frame_errors(map_arrays, model_coords)
    if not frame_errors:
        return
    if frame_errors != ["density_pair:receptor_outside_grid"]:
        raise RuntimeError(f"model-map frame input contract failed for {pdb_id}: {frame_errors}")

    map_lower, map_upper = density_grid_physical_bounds(map_arrays)
    coords = np.asarray(model_coords, dtype=np.float64)
    detail = {
        "atol_angstrom": MODEL_MAP_FRAME_ATOL_ANGSTROM,
        "grid_shape_order": "ZYX",
        "map_lower_xyz": map_lower.tolist(),
        "map_upper_xyz": map_upper.tolist(),
        "model_lower_xyz": coords.min(axis=0).tolist(),
        "model_upper_xyz": coords.max(axis=0).tolist(),
        "pdb_id": pdb_id.lower(),
        "policy": "no_transform_or_fitmap",
        "world_axis_order": "XYZ",
    }
    raise KnownSampleFailure(
        KnownFailureCode.MODEL_MAP_FRAME_MISMATCH,
        json.dumps(detail, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


@dataclass(frozen=True)
class ContourInfo:
    """EMDB 主图 recommended contour 的值和可审计来源。"""

    value: float | None
    status: str
    path: str
    source: str | None


@dataclass(frozen=True)
class LigandAreaSource:
    """E3 生产与只读验收共用的 Stage C 原子输入及来源身份。"""

    candidate_ids: tuple[int, ...]
    coords_by_candidate: dict[int, np.ndarray]
    atomic_numbers_by_candidate: dict[int, np.ndarray]
    source_manifest_sha256: str


def extract_recommended_contour(metadata: dict[str, Any]) -> ContourInfo:
    """
    只从 EMDB 主图路径选择唯一 ``primary=true`` 的有限 contour level。

    输入参数:
        - metadata: dict, Stage B 保存的 EMDB ``/entry/{id}`` 原始 JSON

    输出:
        - info: ContourInfo, 缺失/歧义时 ``value=None``，并保留稳定 status

    不递归搜索 ``interpretation.additional_map_list``，防止把附加图 contour 误当主图。
    ``source`` 可缺失；它不影响有效 level。
    """
    map_section = metadata.get("map")
    if not isinstance(map_section, dict):
        return ContourInfo(None, "missing_map_section", "map", None)
    contour_list = map_section.get("contour_list")
    if not isinstance(contour_list, dict) or "contour" not in contour_list:
        return ContourInfo(None, "missing_contour_list", "map.contour_list.contour", None)
    raw_contours = contour_list["contour"]
    if isinstance(raw_contours, dict):
        contours = [raw_contours]
    elif isinstance(raw_contours, list):
        contours = raw_contours
    else:
        return ContourInfo(None, "invalid_contour_container", "map.contour_list.contour", None)

    primary = [
        (index, item)
        for index, item in enumerate(contours)
        if isinstance(item, dict) and _metadata_bool(item.get("primary"))
    ]
    if len(primary) == 0:
        return ContourInfo(None, "missing_primary_contour", "map.contour_list.contour", None)
    if len(primary) > 1:
        return ContourInfo(None, "ambiguous_primary_contour", "map.contour_list.contour", None)
    index, item = primary[0]
    path = f"map.contour_list.contour[{index}].level"
    try:
        level = float(item.get("level"))
    except (TypeError, ValueError):
        return ContourInfo(None, "invalid_primary_level", path, _optional_text(item.get("source")))
    if not np.isfinite(level):
        return ContourInfo(None, "nonfinite_primary_level", path, _optional_text(item.get("source")))
    return ContourInfo(level, "ok", path, _optional_text(item.get("source")))


def vdw_radius(atomic_number: int) -> float:
    """
    返回逐元素范德华半径 Å。

    C/N/O/P/S 使用计划锁定值；其他有效元素调用 RDKit 周期表，不使用单一默认常数。
    """
    if atomic_number in VDW_RADIUS_OVERRIDES:
        return VDW_RADIUS_OVERRIDES[atomic_number]
    if atomic_number <= 0 or atomic_number > 118:
        raise ValueError(f"unsupported atomic number for vdW radius: {atomic_number}")
    radius = float(_PERIODIC_TABLE.GetRvdw(int(atomic_number)))
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError(f"RDKit has no valid vdW radius for atomic number {atomic_number}")
    return radius

def _metadata_bool(value: Any) -> bool:
    """严格解析 EMDB metadata 的布尔表示。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value) == 1
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def _optional_text(value: Any) -> str | None:
    """把 metadata 可选文本规范为 ``str | None``。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None

