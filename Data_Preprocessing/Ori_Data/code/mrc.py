# 学习导航：功能分区=外部工具与格式适配；生命周期=正式主路径 Stage E/F 基础设施。
# 主要输入：MRC/map header、ZYX 数组、XYZ origin/voxel 与 Pocket Plus 原语参数。
# 主要输出：MapGrid、重采样网格、MRC 文件和可回归的坐标元数据。
# 关键边界：祖传六函数保持冻结；本层只做薄适配，数组轴 ZYX、世界坐标 XYZ Å 必须显式记录。
"""Pocket Plus 祖传 MRC 原语的 AdaLigand 薄适配层。

``mrc_pocket_legacy.py`` 原样保存六个 Pocket Plus 函数；本模块保持普通样本的祖传
数值路径，只负责 ``Path``/``MapGrid`` 接口、AdaLigand ``float32`` artifact dtype、
原子 MRC 写出，以及全量 header 审计确认的两个 mixed-axis 样本兼容分支。
完整祖先哈希、零函数差异证据和兼容边界见 ``mrc_pocket_legacy.source.json`` 与代码 README。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import mrcfile
import numpy as np

from io_utils import atomic_replace
from mrc_pocket_legacy import load_map as _pocket_load_map
from mrc_pocket_legacy import make_model_grid as _pocket_make_model_grid
from mrc_pocket_legacy import rescale_fourier as _pocket_rescale_fourier


POCKET_MRC_ANCESTOR_SHA256 = "d8e543e4c6763a44cde3d350434c51506d794ecf1c2143db2ce304419bc06ca8"
POCKET_MRC_VENDOR_SHA256 = "acf74c256e6d88f9e40e972c0d86d35262aa9ac6ac790346adbd54e3109e8a45"
POCKET_MRC_ALGORITHM = (
    "pocket_plus_mrc_tools_load_map_make_model_grid_v1:"
    f"ancestor_sha256={POCKET_MRC_ANCESTOR_SHA256}"
)
POCKET_RESAMPLE_ALL_EQUAL = "pocket_plus_all_equal_no_rescale"
POCKET_RESAMPLE_ALL_DIFF = "pocket_plus_all_diff_exact"
POCKET_RESAMPLE_MIXED_COMPAT = "pocket_plus_mixed_axis_np_any_compat"


@dataclass(frozen=True)
class MapGrid:
    """
    统一轴序的密度图及世界坐标元数据。

    输入参数:
        - grid: np.ndarray, (Z,Y,X), float32, 密度值
        - voxel_size: np.ndarray, (3,), float32, XYZ 每体素 Å
        - origin: np.ndarray, (3,), float32, 网格下角点的世界 XYZ 坐标 Å；
          `grid[0,0,0]` 的体素中心为 `origin + 0.5 * voxel_size`
    """

    grid: np.ndarray
    voxel_size: np.ndarray
    origin: np.ndarray


@dataclass(frozen=True)
class CanonicalizationInfo:
    """祖传 canonicalization 的 shape 关系、执行模式和密度幅值比例。"""

    input_shape_zyx: tuple[int, int, int]
    even_input_shape_zyx: tuple[int, int, int]
    output_shape_zyx: tuple[int, int, int]
    resample_mode: str
    contour_scale_to_canonical: float


def canonicalization_info(
    input_shape_zyx: tuple[int, int, int],
    output_shape_zyx: tuple[int, int, int],
) -> CanonicalizationInfo:
    """
    根据实际输入/输出 shape 返回祖传 resample 模式和 native→canonical 幅值比例。

    odd 输入先按祖传 ``make_cubic`` 补偶。正常 Fourier 分支不缩放频域系数，因此
    canonical 密度相对 native/padded 密度的全局比例为 ``prod(even_input)/prod(output)``。
    """
    input_shape = np.asarray(input_shape_zyx, dtype=np.int64)
    output_shape = np.asarray(output_shape_zyx, dtype=np.int64)
    if (
        input_shape.shape != (3,)
        or output_shape.shape != (3,)
        or np.any(input_shape <= 0)
        or np.any(output_shape <= 0)
        or np.any(output_shape % 2 != 0)
    ):
        raise ValueError("canonicalization shapes must be positive 3D and output must be even")
    even_input_shape = input_shape + input_shape % 2
    equal_axes = output_shape == even_input_shape
    if np.all(equal_axes):
        mode = POCKET_RESAMPLE_ALL_EQUAL
    elif np.all(~equal_axes):
        mode = POCKET_RESAMPLE_ALL_DIFF
    else:
        mode = POCKET_RESAMPLE_MIXED_COMPAT
    scale = float(
        np.prod(even_input_shape, dtype=np.float64)
        / np.prod(output_shape, dtype=np.float64)
    )
    return CanonicalizationInfo(
        input_shape_zyx=tuple(int(value) for value in input_shape),
        even_input_shape_zyx=tuple(int(value) for value in even_input_shape),
        output_shape_zyx=tuple(int(value) for value in output_shape),
        resample_mode=mode,
        contour_scale_to_canonical=scale,
    )


def _rescale_real_mixed_axis_compat(box: np.ndarray, out_sz: np.ndarray) -> np.ndarray:
    """
    只处理祖传 ``rescale_real`` 的 mixed-axis 条件缺口。

    函数体与祖传实现相同，唯一行为差异是条件由 ``np.all`` 改为 ``np.any``；
    Fourier 变换与 ``rescale_fourier`` 仍直接调用祖传原语。
    """
    assert np.all(np.array(box.shape) % 2 == 0) and np.all(np.array(out_sz) % 2 == 0)
    if np.any(out_sz != box.shape):
        fourier = np.fft.rfftn(box)
        fourier = _pocket_rescale_fourier(fourier, out_sz)
        box = np.fft.irfftn(fourier)
    return box


def load_map(path: Path, *, multiply_global_origin: bool = True) -> MapGrid:
    """
    通过 Pocket Plus 祖传 ``load_map`` 读取 MRC/CCP4（含 ``.gz``）。

    输入参数:
        - path: Path, `.mrc/.map` 或其 gzip 文件
        - multiply_global_origin: bool, 原样透传祖传参数；native EMDB 图使用 True，
          AdaLigand/Chimera 写出的 Å 级 header.origin 图使用 False

    输出:
        - map_grid: MapGrid, float32 ZYX 数组、XYZ voxel 和 XYZ origin

    适配差异:
        - ``Path`` 转为祖传函数需要的字符串路径；祖传 ``multiply_global_origin`` 显式暴露；
        - 关闭祖传函数内部 MRC handle 后，把网格实体化为 AdaLigand 要求的 float32；
        - 对三维 shape、有限正 voxel 与有限 origin 做接口级验收，不改祖传数值。
    """
    grid, voxel_size, origin = _pocket_load_map(
        str(path),
        multiply_global_origin=multiply_global_origin,
    )
    grid = np.asarray(grid, dtype=np.float32).copy()
    voxel_size = np.asarray(voxel_size, dtype=np.float32).copy()
    origin = np.asarray(origin, dtype=np.float32).copy()
    if grid.ndim != 3:
        raise ValueError(f"MRC data must be 3D, got shape {grid.shape}")
    if voxel_size.shape != (3,) or not np.isfinite(voxel_size).all() or np.any(voxel_size <= 0):
        raise ValueError(f"invalid MRC voxel size: {voxel_size.tolist()}")
    if origin.shape != (3,) or not np.isfinite(origin).all():
        raise ValueError(f"invalid MRC origin: {origin.tolist()}")
    return MapGrid(grid=grid, voxel_size=voxel_size, origin=origin)


def make_canonical_grid(map_grid: MapGrid, target_voxel_size: float) -> MapGrid:
    """
    通过 Pocket Plus 祖传 ``make_model_grid`` 生成目标约 1 Å 的 canonical grid。

    输入参数:
        - map_grid: MapGrid, 输入 ZYX 密度和 XYZ 几何
        - target_voxel_size: float, 目标体素 Å；正式值显式传 1.0

    输出:
        - canonical: MapGrid, float32 ZYX 密度、祖传函数返回的实际 XYZ voxel/origin

    说明:
        输出 shape、偶数网格、Fourier 重采样、实际 voxel 和 padding 后 origin 全部由祖传函数
        决定。本适配层检查目标值和“偶数输入物理长度 == 输出物理长度”，防止祖传实现的
        mixed-axis 尺寸分支被 AdaLigand 静默消费；并把输出 dtype 统一为 artifact 所需的 float32。
    """
    if not np.isfinite(target_voxel_size) or target_voxel_size <= 0:
        raise ValueError("target_voxel_size must be a positive finite number")
    source_grid = np.asarray(map_grid.grid)
    source_voxel = np.asarray(map_grid.voxel_size, dtype=np.float64)
    source_origin = np.asarray(map_grid.origin, dtype=np.float64)
    if source_grid.ndim != 3:
        raise ValueError(f"MRC data must be 3D, got shape {source_grid.shape}")
    if source_voxel.shape != (3,) or not np.isfinite(source_voxel).all() or np.any(source_voxel <= 0):
        raise ValueError(f"invalid MRC voxel size: {source_voxel.tolist()}")
    if source_origin.shape != (3,) or not np.isfinite(source_origin).all():
        raise ValueError(f"invalid MRC origin: {source_origin.tolist()}")
    grid, voxel_size, origin = _pocket_make_model_grid(
        source_grid,
        source_voxel,
        source_origin,
        target_voxel_size=float(target_voxel_size),
    )
    output_grid = np.asarray(grid)
    output_voxel = np.asarray(voxel_size, dtype=np.float64)
    even_input_shape_zyx = np.asarray(source_grid.shape, dtype=np.int64)
    even_input_shape_zyx += even_input_shape_zyx % 2
    input_extent_xyz = even_input_shape_zyx[::-1].astype(np.float64) * source_voxel
    output_extent_xyz = np.asarray(output_grid.shape[::-1], dtype=np.float64) * output_voxel
    if not np.allclose(input_extent_xyz, output_extent_xyz, rtol=1e-6, atol=1e-5):
        intended_shape_xyz_float = input_extent_xyz / output_voxel
        intended_shape_xyz = np.rint(intended_shape_xyz_float).astype(np.int64)
        intended_shape_zyx = intended_shape_xyz[::-1]
        intended_is_integral = np.allclose(
            intended_shape_xyz_float,
            intended_shape_xyz,
            rtol=0,
            atol=1e-6,
        )
        relation = intended_shape_zyx == even_input_shape_zyx
        if (
            not intended_is_integral
            or np.any(intended_shape_zyx <= 0)
            or np.any(intended_shape_zyx % 2 != 0)
            or not (np.any(relation) and np.any(~relation))
        ):
            raise ValueError(
                "Pocket Plus make_model_grid returned a non-closing shape/voxel pair outside "
                "the audited mixed-axis compatibility boundary"
            )
        # 祖传 mixed-axis 路径已返回补偶但未重采样的 grid；直接复用可避免大型数组二次分配。
        output_grid = _rescale_real_mixed_axis_compat(output_grid, intended_shape_zyx)
        output_extent_xyz = np.asarray(output_grid.shape[::-1], dtype=np.float64) * output_voxel
        if not np.allclose(input_extent_xyz, output_extent_xyz, rtol=1e-6, atol=1e-5):
            raise ValueError("mixed-axis compatibility resample did not restore physical closure")
    return MapGrid(
        grid=np.asarray(output_grid, dtype=np.float32),
        voxel_size=np.asarray(output_voxel, dtype=np.float32),
        origin=np.asarray(origin, dtype=np.float32),
    )


def write_canonical_mrc(path: Path, map_grid: MapGrid) -> None:
    """
    原子写标准轴序 canonical MRC，供 Chimera `onGrid` 使用。

    输入参数:
        - path: Path, 输出 `.mrc` 路径
        - map_grid: MapGrid, ZYX float 密度、XYZ voxel/origin

    输出:
        - None: 写出 mapc/mapr/maps=1/2/3、nstart=0、origin=canonical world XYZ
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f"{path.stem}.tmp.{os.getpid()}.mrc")
    grid = np.asarray(map_grid.grid, dtype=np.float32)
    with mrcfile.new(str(tmp_path), overwrite=True) as handle:
        handle.set_data(grid)
        handle.voxel_size = tuple(float(value) for value in map_grid.voxel_size)
        handle.header.mapc = 1
        handle.header.mapr = 2
        handle.header.maps = 3
        handle.header.nxstart = 0
        handle.header.nystart = 0
        handle.header.nzstart = 0
        handle.header.origin.x = float(map_grid.origin[0])
        handle.header.origin.y = float(map_grid.origin[1])
        handle.header.origin.z = float(map_grid.origin[2])
        handle.update_header_stats()
        handle.flush()
    atomic_replace(tmp_path, path)


def grid_world_bounds(map_grid: MapGrid) -> tuple[np.ndarray, np.ndarray]:
    """
    返回 canonical grid 体素中心覆盖的世界 XYZ 最小/最大坐标。

    输入参数:
        - map_grid: MapGrid, ZYX grid 与 XYZ 几何

    输出:
        - lower: np.ndarray, (3,), float32, 第一个体素中心 XYZ
        - upper: np.ndarray, (3,), float32, 最后一个体素中心 XYZ
    """
    shape_xyz = np.asarray(map_grid.grid.shape[::-1], dtype=np.float32)
    lower = np.asarray(map_grid.origin, dtype=np.float32)
    upper = lower + (shape_xyz - 1.0) * np.asarray(map_grid.voxel_size, dtype=np.float32)
    return lower, upper
