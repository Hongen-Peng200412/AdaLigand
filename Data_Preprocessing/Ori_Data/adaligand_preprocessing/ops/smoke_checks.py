# 小规模真实工具验证的判定函数。
# 主要输入：小型合成数组、真实工具输出摘要和几何元数据。
# 主要输出：快速通过/失败断言，不写正式全量产物。
# 关键边界：smoke 只能证明局部契约，不能替代全量阶段 gate 或科学分布审计。
"""真实工具 smoke 的小型纯函数检查。"""

from __future__ import annotations

from typing import Any

import numpy as np


NEGATIVE_CC_FIELDS = ("cc_all", "cc_all_about_mean")


def shift_grid_x_no_wrap(grid_zyx: np.ndarray, shift_voxels: int) -> np.ndarray:
    """把三维网格沿 +X 平移固定体素数，越界部分置零且禁止环绕。"""
    grid = np.asarray(grid_zyx)
    shift = int(shift_voxels)
    if grid.ndim != 3 or shift <= 0 or shift >= grid.shape[2]:
        raise ValueError("grid must be 3D and 0 < shift_voxels < X size")
    shifted = np.zeros_like(grid)
    shifted[:, :, shift:] = grid[:, :, :-shift]
    return shifted


def negative_cc_errors(
    matched: dict[str, Any],
    shifted: dict[str, Any],
    *,
    minimum_drop: float,
) -> list[str]:
    """要求错位图的两个无 contour CC 都比正确配对至少下降指定幅度。"""
    drop = float(minimum_drop)
    if not np.isfinite(drop) or drop <= 0:
        raise ValueError("minimum_drop must be positive and finite")
    errors: list[str] = []
    for field in NEGATIVE_CC_FIELDS:
        try:
            matched_value = float(matched[field])
            shifted_value = float(shifted[field])
        except (KeyError, TypeError, ValueError):
            errors.append(f"negative_cc:{field}:missing")
            continue
        if not np.isfinite(matched_value) or not np.isfinite(shifted_value):
            errors.append(f"negative_cc:{field}:nonfinite")
        elif matched_value - shifted_value < drop:
            errors.append(f"negative_cc:{field}:drop_too_small")
    return errors
