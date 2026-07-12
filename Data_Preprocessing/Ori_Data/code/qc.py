"""A–G 流水线共用的数值与空间契约检查。

本模块只做纯检查，不写报告、不决定样本是否继续。调用方把稳定诊断码归类为
``known_failed`` 或 ``unknown_failed``，从而把失败策略集中在 stage 编排层。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np


DENSITY_KEYS = ("grid", "voxel_size", "origin")
CC_KEYS = (
    "cc_contour",
    "cc_contour_about_mean",
    "cc_all",
    "cc_all_about_mean",
)
_AXIS_NAMES = ("z", "y", "x")


def density_artifact_errors(
    arrays: Mapping[str, np.ndarray],
    *,
    require_unit_voxel: bool,
) -> list[str]:
    """
    验证一个落盘密度 NPZ 的 dtype、几何和严格三维内容。

    输入参数:
        - arrays: Mapping[str,np.ndarray], 至少含 ``grid/voxel_size/origin``
        - require_unit_voxel: bool, 是否要求三轴 voxel 精确为 1 Å（容差 ``1e-5``）

    输出:
        - errors: list[str], 空列表表示通过；诊断码稳定，可直接写入运行报告

    说明:
        ``grid`` 必须是 ``(1,Z,Y,X) float32``。除有限、非零和有方差外，每个空间轴
        至少要有两个包含实质密度的切片，从而拦截只有单平面的伪三维产物。
    """
    missing = [key for key in DENSITY_KEYS if key not in arrays]
    if missing:
        return [f"density_missing:{key}" for key in missing]

    errors: list[str] = []
    grid = np.asarray(arrays["grid"])
    voxel_size = np.asarray(arrays["voxel_size"])
    origin = np.asarray(arrays["origin"])

    if grid.dtype != np.float32:
        errors.append("density_dtype:grid")
    if grid.ndim != 4 or grid.shape[0] != 1 or any(size <= 1 for size in grid.shape[1:]):
        errors.append("density_shape:grid")
    if voxel_size.dtype != np.float32 or voxel_size.shape != (3,):
        errors.append("density_contract:voxel_size")
    elif not np.isfinite(voxel_size).all() or np.any(voxel_size <= 0):
        errors.append("density_geometry:voxel_size")
    elif require_unit_voxel and not np.allclose(
        voxel_size,
        np.ones((3,), dtype=np.float32),
        rtol=0,
        atol=1e-5,
    ):
        errors.append("density_geometry:not_unit_voxel")
    if origin.dtype != np.float32 or origin.shape != (3,):
        errors.append("density_contract:origin")
    elif not np.isfinite(origin).all():
        errors.append("density_geometry:origin")

    if grid.ndim != 4 or grid.shape[0] != 1:
        return errors
    volume = grid[0]
    if not np.isfinite(volume).all():
        errors.append("density_content:nonfinite")
        return errors
    max_abs = float(np.max(np.abs(volume), initial=0.0))
    if max_abs == 0.0:
        errors.append("density_content:all_zero")
        return errors
    if float(np.var(volume, dtype=np.float64)) == 0.0:
        errors.append("density_content:no_variance")
        return errors

    active = np.abs(volume) > max(max_abs * 1e-6, np.finfo(np.float32).tiny)
    for axis, axis_name in enumerate(_AXIS_NAMES):
        reduce_axes = tuple(index for index in range(3) if index != axis)
        active_slices = np.any(active, axis=reduce_axes)
        if int(np.count_nonzero(active_slices)) < 2:
            errors.append(f"density_content:single_{axis_name}_slice")
    return errors


def density_pair_errors(
    exp_arrays: Mapping[str, np.ndarray],
    sim_arrays: Mapping[str, np.ndarray],
    receptor_coords: np.ndarray,
) -> list[str]:
    """
    验证实验图、模拟图同网格，并检查受体包围盒与网格相交。

    输入参数:
        - exp_arrays: Mapping[str,np.ndarray], canonical 实验图 NPZ
        - sim_arrays: Mapping[str,np.ndarray], receptor-only 模拟图 NPZ
        - receptor_coords: np.ndarray, ``(N,3)`` 世界坐标 XYZ，单位 Å

    输出:
        - errors: list[str], 带 ``exp:``/``sim:`` 前缀的内容错误和跨图几何错误
    """
    # Pocket Plus 以目标体素选择偶数网格，并把由物理长度决定的实际 voxel 落盘。
    errors = [f"exp:{error}" for error in density_artifact_errors(exp_arrays, require_unit_voxel=False)]
    errors.extend(
        f"sim:{error}" for error in density_artifact_errors(sim_arrays, require_unit_voxel=False)
    )
    if any(key not in exp_arrays or key not in sim_arrays for key in DENSITY_KEYS):
        return errors

    exp_grid = np.asarray(exp_arrays["grid"])
    sim_grid = np.asarray(sim_arrays["grid"])
    if exp_grid.shape != sim_grid.shape:
        errors.append("density_pair:shape_mismatch")
    if not np.allclose(
        np.asarray(exp_arrays["voxel_size"]),
        np.asarray(sim_arrays["voxel_size"]),
        rtol=0,
        atol=1e-5,
    ):
        errors.append("density_pair:voxel_mismatch")
    if not np.allclose(
        np.asarray(exp_arrays["origin"]),
        np.asarray(sim_arrays["origin"]),
        rtol=0,
        atol=1e-5,
    ):
        errors.append("density_pair:origin_mismatch")

    coords = np.asarray(receptor_coords)
    if coords.dtype != np.float32 or coords.ndim != 2 or coords.shape[1:] != (3,):
        errors.append("density_pair:receptor_contract")
        return errors
    if len(coords) == 0 or not np.isfinite(coords).all():
        errors.append("density_pair:receptor_empty_or_nonfinite")
        return errors
    if exp_grid.ndim != 4 or exp_grid.shape[0] != 1:
        return errors

    grid_lower = np.asarray(exp_arrays["origin"], dtype=np.float64)
    shape_xyz = np.asarray(exp_grid.shape[:0:-1], dtype=np.float64)
    grid_upper = grid_lower + (shape_xyz - 1.0) * np.asarray(
        exp_arrays["voxel_size"],
        dtype=np.float64,
    )
    receptor_lower = coords.min(axis=0).astype(np.float64)
    receptor_upper = coords.max(axis=0).astype(np.float64)
    intersects = np.all(receptor_lower <= grid_upper + 1e-5) and np.all(
        receptor_upper >= grid_lower - 1e-5
    )
    if not intersects:
        errors.append("density_pair:receptor_outside_grid")
    return errors


def cc_value_errors(values: Mapping[str, Any], *, contour_available: bool) -> list[str]:
    """
    验证 Chimera 四个全局 map-model CC 原始量的空值与数值范围。

    输入参数:
        - values: Mapping[str,Any], 四个 ``CC_KEYS`` 值
        - contour_available: bool, 是否存在可审计的 EMDB recommended contour

    输出:
        - errors: list[str], 空列表表示契约通过

    说明:
        contour 缺失时，只有 ``cc_contour`` 和 ``cc_contour_about_mean`` 必须为 ``None``；
        ``cc_all`` 两项仍必须是有限的 ``[-1,1]`` 数值。contour 存在时四项都必须有效。
    """
    errors: list[str] = []
    for key in CC_KEYS:
        if key not in values:
            errors.append(f"cc_missing:{key}")
            continue
        value = values[key]
        is_contour_value = key.startswith("cc_contour")
        if not contour_available and is_contour_value:
            if value is not None:
                errors.append(f"cc_expected_null:{key}")
            continue
        if value is None:
            errors.append(f"cc_unexpected_null:{key}")
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            errors.append(f"cc_not_numeric:{key}")
            continue
        if not np.isfinite(number):
            errors.append(f"cc_nonfinite:{key}")
        elif number < -1.0 - 1e-6 or number > 1.0 + 1e-6:
            errors.append(f"cc_out_of_range:{key}")
    return errors
