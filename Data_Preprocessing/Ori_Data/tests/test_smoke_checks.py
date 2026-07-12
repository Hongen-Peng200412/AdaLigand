"""真实 smoke 纯函数的确定性回归。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from smoke_checks import negative_cc_errors, shift_grid_x_no_wrap


def test_shift_grid_x_has_zero_fill_and_no_wrap() -> None:
    """+X 平移只能右移并补零，左侧值不得从右边环绕回来。"""
    grid = np.arange(2 * 3 * 5, dtype=np.float32).reshape(2, 3, 5)
    shifted = shift_grid_x_no_wrap(grid, 2)
    np.testing.assert_array_equal(shifted[:, :, :2], 0)
    np.testing.assert_array_equal(shifted[:, :, 2:], grid[:, :, :-2])
    assert shifted.dtype == grid.dtype


def test_negative_cc_requires_both_unmasked_metrics_to_drop() -> None:
    """all 与 all-about-mean 任一未显著下降都必须让负对照失败。"""
    matched = {"cc_all": 0.8, "cc_all_about_mean": 0.7}
    shifted = {"cc_all": 0.6, "cc_all_about_mean": 0.55}
    assert negative_cc_errors(matched, shifted, minimum_drop=0.05) == []
    shifted["cc_all_about_mean"] = 0.68
    assert negative_cc_errors(matched, shifted, minimum_drop=0.05) == [
        "negative_cc:cc_all_about_mean:drop_too_small"
    ]
