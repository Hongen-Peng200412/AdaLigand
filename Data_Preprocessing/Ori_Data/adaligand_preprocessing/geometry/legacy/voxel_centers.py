"""Pocket Plus 的体素中心原语快照。

本模块仅隔离复制祖传实现，便于 E3 直接消费同一套数值行为。函数体保持原样；
来源文件与函数哈希记录在同目录的 ``voxel_gt_pocket_legacy.source.json`` 中。
"""

import numpy as np


def _build_voxel_center_coords_xyz(
    grid_shape_zyx: tuple[int, int, int],
    origin_xyz: np.ndarray,
    voxel_size_xyz: np.ndarray,
) -> np.ndarray:
    """
    构造整图每个体素中心的世界坐标。

    输入参数:
        - grid_shape_zyx: tuple[int,int,int], 整图形状(D,H,W)
        - origin_xyz: np.ndarray, (3,), 密度图世界坐标原点(x,y,z)
        - voxel_size_xyz: np.ndarray, (3,), 体素大小(x,y,z)

    输出:
        - coords_xyz: np.ndarray, (D*H*W, 3), 每个体素中心的世界坐标(x,y,z)
    """
    depth, height, width = tuple(int(v) for v in grid_shape_zyx)
    # np.ndarray, (D,H,W), int64, 三个空间轴的体素索引网格
    z_idx, y_idx, x_idx = np.mgrid[0:depth, 0:height, 0:width]
    # np.ndarray, (D*H*W, 3), float32, 体素中心世界坐标(x,y,z)
    coords_xyz = np.stack(
        [
            x_idx.ravel() * voxel_size_xyz[0] + origin_xyz[0] + voxel_size_xyz[0] * 0.5,
            y_idx.ravel() * voxel_size_xyz[1] + origin_xyz[1] + voxel_size_xyz[1] * 0.5,
            z_idx.ravel() * voxel_size_xyz[2] + origin_xyz[2] + voxel_size_xyz[2] * 0.5,
        ],
        axis=1,
    ).astype(np.float32)
    return coords_xyz
