"""共享密度与 CC 契约的回归测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from qc import (
    cc_value_errors,
    density_artifact_errors,
    density_pair_errors,
    model_map_frame_errors,
)


def _valid_density(shape: tuple[int, int, int] = (5, 6, 7)) -> dict[str, np.ndarray]:
    """构造有三维体积内容的 canonical 密度 artifact。"""
    volume = np.zeros(shape, dtype=np.float32)
    volume[1:4, 1:5, 2:6] = np.arange(3 * 4 * 4, dtype=np.float32).reshape(3, 4, 4) + 1
    return {
        "grid": volume[None],
        "voxel_size": np.ones((3,), dtype=np.float32),
        "origin": np.asarray([-2.0, 4.0, 10.0], dtype=np.float32),
    }


def test_density_artifact_accepts_strict_3d_content() -> None:
    """合法 canonical artifact 应通过所有基础检查。"""
    assert density_artifact_errors(_valid_density(), require_unit_voxel=True) == []


def test_density_artifact_rejects_single_plane() -> None:
    """只有一个 Z 切片含内容的伪三维图必须被拒绝。"""
    arrays = _valid_density()
    arrays["grid"][:] = 0
    arrays["grid"][0, 2, 1:5, 2:6] = 1
    errors = density_artifact_errors(arrays, require_unit_voxel=True)
    assert "density_content:single_z_slice" in errors


def test_density_artifact_optional_unit_guard_remains_available() -> None:
    """通用 QC 仍保留严格 unit 分支，但正式 Pocket canonical 路径不启用它。"""
    arrays = _valid_density()
    arrays["grid"][:] = 2
    arrays["voxel_size"][0] = 1.5
    errors = density_artifact_errors(arrays, require_unit_voxel=True)
    assert "density_content:no_variance" in errors
    assert "density_geometry:not_unit_voxel" in errors


def test_density_pair_accepts_matching_pocket_actual_voxel() -> None:
    """实验图和模拟图使用相同的非单位实际 voxel 时应通过，任一轴漂移仍失败。"""
    exp = _valid_density()
    sim = _valid_density()
    actual_voxel = np.asarray([0.997, 1.001, 0.999], dtype=np.float32)
    exp["voxel_size"] = actual_voxel.copy()
    sim["voxel_size"] = actual_voxel.copy()
    receptor = np.asarray([[0.0, 6.0, 12.0], [1.0, 7.0, 13.0]], dtype=np.float32)

    assert density_pair_errors(exp, sim, receptor) == []
    sim["voxel_size"][0] = np.float32(0.996)
    assert "density_pair:voxel_mismatch" in density_pair_errors(exp, sim, receptor)


def test_density_pair_checks_geometry_and_receptor_intersection() -> None:
    """图对必须同 shape/origin/voxel，且受体包围盒与网格相交。"""
    exp = _valid_density()
    sim = _valid_density()
    receptor = np.asarray([[0.0, 6.0, 12.0], [1.0, 7.0, 13.0]], dtype=np.float32)
    assert density_pair_errors(exp, sim, receptor) == []

    sim["origin"] = sim["origin"] + np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
    outside = np.asarray([[100.0, 100.0, 100.0]], dtype=np.float32)
    errors = density_pair_errors(exp, sim, outside)
    assert "density_pair:origin_mismatch" in errors
    assert "density_pair:receptor_outside_grid" in errors


def test_model_map_frame_preflight_is_xyz_zyx_aware_and_fail_closed() -> None:
    """前置包围盒只把合法且完全分离的输入标成 frame mismatch。"""
    exp = _valid_density()
    exp["origin"] = np.asarray([10.0, 20.0, 30.0], dtype=np.float32)
    exp["voxel_size"] = np.asarray([2.0, 3.0, 4.0], dtype=np.float32)

    # Pocket corner-origin 的物理 BOX 上界为 origin+shape_xyz*voxel=(24,38,50)。
    # 旧 ``origin+(shape-1)*voxel`` 会把这个仍在最后一个体素内的点误判为分离。
    touching = np.asarray([[23.9, 37.9, 49.9]], dtype=np.float32)
    assert model_map_frame_errors(exp, touching) == []
    for outside in (
        np.asarray([[24.1, 25.0, 35.0]], dtype=np.float32),
        np.asarray([[15.0, 38.1, 35.0]], dtype=np.float32),
        np.asarray([[15.0, 25.0, 50.1]], dtype=np.float32),
    ):
        assert model_map_frame_errors(exp, outside) == [
            "density_pair:receptor_outside_grid"
        ]

    invalid = np.asarray([[np.nan, 25.0, 35.0]], dtype=np.float32)
    assert model_map_frame_errors(exp, invalid) == [
        "density_pair:receptor_empty_or_nonfinite"
    ]
    assert "density_pair:receptor_outside_grid" not in model_map_frame_errors(exp, invalid)


def test_density_pair_rejects_shape_mismatch() -> None:
    """即使两图各自有效，空间 shape 不同也必须失败。"""
    exp = _valid_density((5, 6, 7))
    sim = _valid_density((5, 6, 8))
    receptor = np.asarray([[0.0, 6.0, 12.0]], dtype=np.float32)
    assert "density_pair:shape_mismatch" in density_pair_errors(exp, sim, receptor)


def test_cc_values_enforce_four_raw_quantities_and_contour_null_semantics() -> None:
    """缺 contour 只允许对应两项为空，all-mask 两项仍须有效。"""
    missing_contour = {
        "cc_contour": None,
        "cc_contour_about_mean": None,
        "cc_all": 0.4,
        "cc_all_about_mean": -0.1,
    }
    assert cc_value_errors(missing_contour, contour_available=False) == []
    assert "cc_unexpected_null:cc_contour" in cc_value_errors(
        missing_contour,
        contour_available=True,
    )

    invalid = dict(missing_contour)
    invalid["cc_all"] = 1.2
    assert "cc_out_of_range:cc_all" in cc_value_errors(invalid, contour_available=False)
