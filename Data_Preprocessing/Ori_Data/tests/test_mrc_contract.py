"""Pocket Plus MRC 祖传函数与 AdaLigand 薄适配层的契约测试。"""

from __future__ import annotations

import gzip
import itertools
import shutil
import sys
from pathlib import Path

import mrcfile
import numpy as np
import pytest

CODE_DIR = Path(__file__).resolve().parents[1] / "code"

from adaligand_preprocessing.geometry.mrc import (
    POCKET_RESAMPLE_MIXED_COMPAT,
    MapGrid,
    canonicalization_info,
    grid_world_bounds,
    load_map,
    make_canonical_grid,
    write_canonical_mrc,
)
from adaligand_preprocessing.geometry.legacy.mrc_pocket import load_map as pocket_load_map
from adaligand_preprocessing.geometry.legacy.mrc_pocket import make_model_grid as pocket_make_model_grid


def _write_axis_fixture(
    path: Path,
    physical_grid: np.ndarray,
    axis_mapping: tuple[int, int, int],
    voxel_size: np.ndarray,
    header_origin_index: np.ndarray,
    physical_nstart: np.ndarray,
) -> None:
    """按任意合法 mapc/mapr/maps 写一个已知物理 ZYX 内容的 MRC。"""
    mapc, mapr, maps = axis_mapping
    # raw data 三轴为 section/row/column；physical 轴编号 0/1/2 表示 X/Y/Z。
    data_axis_to_physical = [maps - 1, mapr - 1, mapc - 1]
    physical_to_zyx_axis = {0: 2, 1: 1, 2: 0}
    raw_axes = tuple(physical_to_zyx_axis[axis] for axis in data_axis_to_physical)
    raw_data = np.transpose(physical_grid, raw_axes).astype(np.float32)

    with mrcfile.new(str(path), overwrite=True) as handle:
        handle.set_data(raw_data)
        handle.header.mapc = mapc
        handle.header.mapr = mapr
        handle.header.maps = maps
        handle.header.mx = physical_grid.shape[2]
        handle.header.my = physical_grid.shape[1]
        handle.header.mz = physical_grid.shape[0]
        handle.header.cella.x = float(physical_grid.shape[2] * voxel_size[0])
        handle.header.cella.y = float(physical_grid.shape[1] * voxel_size[1])
        handle.header.cella.z = float(physical_grid.shape[0] * voxel_size[2])
        handle.header.nxstart = int(physical_nstart[mapc - 1])
        handle.header.nystart = int(physical_nstart[mapr - 1])
        handle.header.nzstart = int(physical_nstart[maps - 1])
        handle.header.origin.x = float(header_origin_index[0])
        handle.header.origin.y = float(header_origin_index[1])
        handle.header.origin.z = float(header_origin_index[2])
        handle.update_header_stats()


@pytest.mark.parametrize("axis_mapping", list(itertools.permutations((1, 2, 3))))
def test_load_map_supports_all_axis_permutations(tmp_path, axis_mapping):
    """六种轴排列下，适配层输出都必须逐项等于 Pocket Plus 祖传函数。"""
    physical_grid = np.arange(2 * 3 * 4, dtype=np.float32).reshape(2, 3, 4)
    voxel_size = np.asarray([1.5, 2.0, 2.5], dtype=np.float32)
    # 祖传 native-map 输入契约把 header.origin 与 nstart 一起作为体素坐标再乘 voxel。
    header_origin_index = np.asarray([10.0, 20.0, 30.0], dtype=np.float32)
    physical_nstart = np.asarray([4, 5, 6], dtype=np.int32)
    path = tmp_path / f"axis_{''.join(map(str, axis_mapping))}.mrc"
    _write_axis_fixture(
        path,
        physical_grid,
        axis_mapping,
        voxel_size,
        header_origin_index,
        physical_nstart,
    )

    loaded = load_map(path)
    legacy_grid, legacy_voxel, legacy_origin = pocket_load_map(str(path))

    np.testing.assert_array_equal(loaded.grid, np.asarray(legacy_grid, dtype=np.float32))
    np.testing.assert_array_equal(loaded.grid, physical_grid)
    np.testing.assert_allclose(loaded.voxel_size, legacy_voxel, rtol=0, atol=1e-6)
    np.testing.assert_allclose(loaded.origin, legacy_origin, rtol=0, atol=1e-6)
    np.testing.assert_allclose(
        loaded.origin,
        (header_origin_index + physical_nstart) * voxel_size,
        rtol=0,
        atol=1e-6,
    )


def test_load_map_reads_gzip_without_manual_decompression(tmp_path):
    """Stage B 的 `.map.gz` 应可由同一 loader 直接读取。"""
    physical_grid = np.arange(24, dtype=np.float32).reshape(2, 3, 4)
    source = tmp_path / "source.map"
    compressed = tmp_path / "source.map.gz"
    _write_axis_fixture(
        source,
        physical_grid,
        (1, 2, 3),
        np.ones((3,), dtype=np.float32),
        np.zeros((3,), dtype=np.float32),
        np.zeros((3,), dtype=np.int32),
    )
    with source.open("rb") as input_handle, gzip.open(compressed, "wb") as output_handle:
        shutil.copyfileobj(input_handle, output_handle)

    loaded = load_map(compressed)

    np.testing.assert_array_equal(loaded.grid, physical_grid)
    assert loaded.grid.dtype == np.float32
    assert loaded.grid.flags.owndata


def test_canonical_adapter_matches_pocket_and_keeps_actual_voxel():
    """canonical 输出逐项跟随祖传实现，并落盘由偶数 shape 决定的实际 voxel。"""
    source = MapGrid(
        grid=np.full((3, 4, 5), 7.25, dtype=np.float32),
        voxel_size=np.asarray([1.2, 1.5, 2.0], dtype=np.float32),
        origin=np.asarray([3.0, 4.0, 5.0], dtype=np.float32),
    )

    canonical = make_canonical_grid(source, target_voxel_size=1.0)
    legacy_grid, legacy_voxel, legacy_origin = pocket_make_model_grid(
        source.grid,
        source.voxel_size,
        source.origin,
        target_voxel_size=1.0,
    )

    assert canonical.grid.shape == (8, 6, 8)
    assert all(size % 2 == 0 for size in canonical.grid.shape)
    np.testing.assert_allclose(canonical.grid, np.asarray(legacy_grid, dtype=np.float32), rtol=0, atol=1e-6)
    np.testing.assert_allclose(canonical.voxel_size, legacy_voxel, rtol=0, atol=1e-6)
    np.testing.assert_allclose(canonical.origin, legacy_origin, rtol=0, atol=1e-6)
    np.testing.assert_allclose(canonical.voxel_size, [0.9, 1.0, 1.0], rtol=0, atol=1e-6)
    np.testing.assert_allclose(canonical.origin, [1.8, 4.0, 3.0], rtol=0, atol=1e-6)
    info = canonicalization_info(source.grid.shape, canonical.grid.shape)
    assert info.contour_scale_to_canonical == pytest.approx(0.25)


def test_canonical_adapter_uses_one_line_mixed_axis_compatibility():
    """祖传 mixed-axis 缺口只由薄适配 np.any 分支修复，网格和物理长度必须闭合。"""
    source = MapGrid(
        grid=np.ones((4, 6, 8), dtype=np.float32),
        voxel_size=np.asarray([1.0, 2.0, 2.0], dtype=np.float32),
        origin=np.zeros((3,), dtype=np.float32),
    )

    canonical = make_canonical_grid(source, target_voxel_size=1.0)

    assert canonical.grid.shape == (8, 12, 8)
    np.testing.assert_allclose(canonical.voxel_size, [1.0, 1.0, 1.0], rtol=0, atol=1e-6)
    np.testing.assert_allclose(canonical.grid, 0.25, rtol=0, atol=1e-6)
    info = canonicalization_info(source.grid.shape, canonical.grid.shape)
    assert info.resample_mode == POCKET_RESAMPLE_MIXED_COMPAT
    assert info.contour_scale_to_canonical == pytest.approx(0.25)


def test_mixed_axis_compatibility_reuses_ancestor_odd_padding():
    """奇数输入必须复用祖传补偶结果，再只补 mixed-axis 重采样。"""
    source = MapGrid(
        grid=np.ones((5, 6, 7), dtype=np.float32),
        voxel_size=np.asarray([1.0, 2.0, 1.0], dtype=np.float32),
        origin=np.asarray([3.0, 4.0, 5.0], dtype=np.float32),
    )

    canonical = make_canonical_grid(source, target_voxel_size=1.0)
    legacy_grid, legacy_voxel, legacy_origin = pocket_make_model_grid(
        source.grid,
        source.voxel_size,
        source.origin,
        target_voxel_size=1.0,
    )

    assert canonical.grid.shape == (6, 12, 8)
    assert np.asarray(legacy_grid).shape == (6, 6, 8)
    assert np.isfinite(canonical.grid).all()
    np.testing.assert_allclose(canonical.voxel_size, legacy_voxel, rtol=0, atol=1e-6)
    np.testing.assert_allclose(canonical.origin, legacy_origin, rtol=0, atol=1e-6)
    info = canonicalization_info(source.grid.shape, canonical.grid.shape)
    assert info.resample_mode == POCKET_RESAMPLE_MIXED_COMPAT
    assert info.even_input_shape_zyx == (6, 6, 8)
    assert info.contour_scale_to_canonical == pytest.approx(0.5)


def test_native_contour_scaled_to_canonical_preserves_threshold_mask():
    """native contour 乘祖传幅值比例后，必须等价于在幅值恢复图上使用原阈值。"""
    rng = np.random.default_rng(20260712)
    source = MapGrid(
        grid=rng.normal(size=(4, 6, 8)).astype(np.float32),
        voxel_size=np.full((3,), 1.5, dtype=np.float32),
        origin=np.zeros((3,), dtype=np.float32),
    )
    canonical = make_canonical_grid(source, target_voxel_size=1.0)
    info = canonicalization_info(source.grid.shape, canonical.grid.shape)
    amplitude_restored = canonical.grid.astype(np.float64) / info.contour_scale_to_canonical
    ordered = np.sort(amplitude_restored.ravel())
    middle = len(ordered) // 2
    native_contour = float((ordered[middle - 1] + ordered[middle]) / 2.0)

    canonical_mask = canonical.grid > native_contour * info.contour_scale_to_canonical
    restored_mask = amplitude_restored > native_contour
    np.testing.assert_array_equal(canonical_mask, restored_mask)


def test_canonical_mrc_roundtrip_has_standard_header(tmp_path):
    """Ada/Chimera 的 Å-origin 模式必须在非单位 voxel 下无损读回几何。"""
    map_grid = MapGrid(
        grid=np.arange(60, dtype=np.float32).reshape(3, 4, 5),
        voxel_size=np.asarray([0.9, 1.0, 1.1], dtype=np.float32),
        origin=np.asarray([-2.5, 4.0, 9.5], dtype=np.float32),
    )
    path = tmp_path / "canonical.mrc"

    write_canonical_mrc(path, map_grid)
    loaded = load_map(path, multiply_global_origin=False)
    legacy_grid, legacy_voxel, legacy_origin = pocket_load_map(
        str(path),
        multiply_global_origin=False,
    )
    with mrcfile.open(str(path), mode="r") as handle:
        assert (int(handle.header.mapc), int(handle.header.mapr), int(handle.header.maps)) == (1, 2, 3)
        assert (int(handle.header.nxstart), int(handle.header.nystart), int(handle.header.nzstart)) == (0, 0, 0)
        np.testing.assert_allclose(
            [handle.header.origin.x, handle.header.origin.y, handle.header.origin.z],
            map_grid.origin,
            rtol=0,
            atol=1e-6,
        )

    np.testing.assert_array_equal(loaded.grid, map_grid.grid)
    np.testing.assert_array_equal(loaded.voxel_size, map_grid.voxel_size)
    np.testing.assert_array_equal(loaded.origin, map_grid.origin)
    np.testing.assert_array_equal(loaded.grid, np.asarray(legacy_grid, dtype=np.float32))
    np.testing.assert_allclose(loaded.voxel_size, legacy_voxel, rtol=0, atol=1e-6)
    np.testing.assert_allclose(loaded.origin, legacy_origin, rtol=0, atol=1e-6)


def test_grid_world_bounds_use_xyz_shape_order():
    """ZYX shape 必须反转后才能和 XYZ voxel/origin 计算世界边界。"""
    map_grid = MapGrid(
        grid=np.zeros((2, 3, 4), dtype=np.float32),
        voxel_size=np.asarray([1.0, 2.0, 3.0], dtype=np.float32),
        origin=np.asarray([10.0, 20.0, 30.0], dtype=np.float32),
    )

    lower, upper = grid_world_bounds(map_grid)

    np.testing.assert_array_equal(lower, [10.0, 20.0, 30.0])
    np.testing.assert_array_equal(upper, [13.0, 24.0, 33.0])
