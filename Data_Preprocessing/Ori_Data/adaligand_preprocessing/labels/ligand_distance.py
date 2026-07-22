"""生成并验证与实验密度网格对齐的配体最近距离。

主要入口 `build_ligand_distance()` 读取一个 PDB 的 `exp.npz`、
`occurrences.jsonl` 和 `ligand_coords.npz`，写出
`density/{pdb_id}/ligand_dist.npz`。文件保存原始欧氏距离，训练时使用的
反距离变换不写入本产物。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from adaligand_preprocessing.artifacts.validation import density_artifact_errors
from adaligand_preprocessing.geometry.legacy.voxel_centers import (
    _build_voxel_center_coords_xyz as _pocket_build_voxel_center_coords_xyz,
)
from adaligand_preprocessing.utils.hashing import sha256_file
from adaligand_preprocessing.utils.io import atomic_save_npz


LIGAND_DISTANCE_SCHEMA_VERSION = 1
LIGAND_DISTANCE_UNIT = "angstrom"
LIGAND_DISTANCE_ORIGIN_SEMANTICS = "pocket_plus_corner"
LIGAND_DISTANCE_VOXEL_CENTER_OFFSET_XYZ = (0.5, 0.5, 0.5)
LIGAND_DISTANCE_VOXEL_CENTER_FORMULA = (
    "origin_xyz+(index_xyz+0.5)*voxel_size_xyz"
)
_MAX_QUERY_POINTS = 1_000_000


@dataclass(frozen=True)
class LigandDistanceSource:
    """一次距离计算需要的配体坐标和三个独立来源摘要。

    字段:
        - coords_xyz: float32, `(N,3)`，全部成功配体实例中实际存在的重原子
          世界坐标；最后一维按 XYZ 排列，单位 Å。
        - source_exp_identity_sha256: 实验密度空间定义与生成身份摘要。
        - source_occurrences_sha256: `occurrences.jsonl` 文件摘要。
        - source_ligand_coords_sha256: `ligand_coords.npz` 文件摘要。
    """

    coords_xyz: np.ndarray
    source_exp_identity_sha256: str
    source_occurrences_sha256: str
    source_ligand_coords_sha256: str


def _load_npz_arrays(path: Path) -> dict[str, np.ndarray]:
    """无 pickle 读取一份 NPZ，并在关闭文件前复制全部数组。"""
    with np.load(path, allow_pickle=False) as handle:
        return {key: handle[key].copy() for key in handle.files}


def _inspect_stage_c(root: Path, pdb_id: str):
    """延迟导入 Stage C 契约，使纯距离计算不要求 RDKit。"""
    from adaligand_preprocessing.stages.stage_c.contracts import inspect_stage_c

    return inspect_stage_c(root, pdb_id)


def _experimental_density_identity(arrays: dict[str, np.ndarray]) -> str:
    """延迟调用实验密度身份函数，使纯距离计算保持轻依赖。"""
    from adaligand_preprocessing.stages.stage_e.experimental import (
        experimental_density_identity,
    )

    return experimental_density_identity(arrays)


def _voxel_center_axes_xyz(
    grid_shape_zyx: tuple[int, int, int],
    origin_xyz: np.ndarray,
    voxel_size_xyz: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """用 Pocket Plus 的冻结公式生成 X、Y、Z 三条体素中心坐标轴。"""
    depth, height, width = grid_shape_zyx
    center_x = _pocket_build_voxel_center_coords_xyz(
        (1, 1, width), origin_xyz, voxel_size_xyz
    )[:, 0]
    center_y = _pocket_build_voxel_center_coords_xyz(
        (1, height, 1), origin_xyz, voxel_size_xyz
    )[:, 1]
    center_z = _pocket_build_voxel_center_coords_xyz(
        (depth, 1, 1), origin_xyz, voxel_size_xyz
    )[:, 2]
    return center_x, center_y, center_z


def build_ligand_distance_array(
    grid_shape_zyx: tuple[int, int, int],
    voxel_size_xyz: np.ndarray,
    origin_xyz: np.ndarray,
    ligand_coords_xyz: np.ndarray,
) -> np.ndarray:
    """计算每个实验密度体素中心到最近实际配体重原子的距离。

    输入参数:
        - grid_shape_zyx: 三个正整数，依次是密度网格的 Z、Y、X 长度。
        - voxel_size_xyz: float32, `(3,)`，XYZ 三轴体素尺寸，单位 Å。
        - origin_xyz: float32, `(3,)`，网格物理边界下角点，单位 Å。
        - ligand_coords_xyz: float32, `(N,3)`，实际存在的配体重原子世界坐标。

    返回:
        - distance: float16, `(1,Z,Y,X)`。`N=0` 时全部为正无穷；否则每个
          数值是对应体素中心到最近配体原子的欧氏距离，单位 Å。
    """
    shape = tuple(int(value) for value in grid_shape_zyx)
    if len(shape) != 3 or any(value <= 1 for value in shape):
        raise ValueError("grid_shape_zyx must contain three dimensions > 1")
    voxel = np.asarray(voxel_size_xyz, dtype=np.float32)
    origin = np.asarray(origin_xyz, dtype=np.float32)
    coords = np.asarray(ligand_coords_xyz, dtype=np.float32)
    if (
        voxel.shape != (3,)
        or origin.shape != (3,)
        or not np.isfinite(voxel).all()
        or not np.isfinite(origin).all()
        or np.any(voxel <= 0)
    ):
        raise ValueError("voxel_size_xyz/origin_xyz must be valid XYZ vectors")
    if coords.ndim != 2 or coords.shape[1:] != (3,) or not np.isfinite(coords).all():
        raise ValueError("ligand_coords_xyz must be a finite (N,3) array")
    if len(coords) == 0:
        return np.full((1, *shape), np.inf, dtype=np.float16)

    center_x, center_y, center_z = _voxel_center_axes_xyz(shape, origin, voxel)
    xy_x, xy_y = np.meshgrid(center_x, center_y, indexing="xy")
    # (Y*X,2)，一个 Z 切片内每个体素中心的世界 X/Y 坐标。
    xy = np.column_stack((xy_x.reshape(-1), xy_y.reshape(-1))).astype(
        np.float64,
        copy=False,
    )
    points_per_z = shape[1] * shape[2]
    z_per_chunk = max(1, _MAX_QUERY_POINTS // points_per_z)
    distance = np.empty(shape, dtype=np.float16)
    tree = cKDTree(coords.astype(np.float64, copy=False))
    max_float16 = float(np.finfo(np.float16).max)

    for z_start in range(0, shape[0], z_per_chunk):
        z_stop = min(shape[0], z_start + z_per_chunk)
        chunk_depth = z_stop - z_start
        # (chunk_depth*Y*X,3)，当前连续 Z 切片的全部体素中心世界坐标。
        query_points = np.empty((chunk_depth * points_per_z, 3), dtype=np.float64)
        query_points[:, :2] = np.tile(xy, (chunk_depth, 1))
        query_points[:, 2] = np.repeat(
            center_z[z_start:z_stop].astype(np.float64, copy=False),
            points_per_z,
        )
        chunk_distance = tree.query(query_points, k=1, workers=1)[0]
        if not np.isfinite(chunk_distance).all() or float(chunk_distance.max()) > max_float16:
            raise ValueError("ligand distance cannot be represented as finite float16")
        distance[z_start:z_stop] = chunk_distance.reshape(
            chunk_depth,
            shape[1],
            shape[2],
        ).astype(np.float16)
    return distance[None]


def load_ligand_distance_source(
    root: Path,
    pdb_id: str,
    occurrences: list[dict[str, Any]],
    exp_arrays: dict[str, np.ndarray],
) -> LigandDistanceSource:
    """读取全部成功配体实例的实际原子坐标并计算来源摘要。"""
    normalized_id = pdb_id.lower()
    parse_dir = root / "parse" / normalized_id
    occurrences_path = parse_dir / "occurrences.jsonl"
    coords_path = parse_dir / "ligand_coords.npz"
    coords_arrays = _load_npz_arrays(coords_path)

    present_coords: list[np.ndarray] = []
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        coords = np.asarray(coords_arrays[f"coords_{candidate_id}"])
        present = np.asarray(coords_arrays[f"present_{candidate_id}"])
        if (
            coords.dtype != np.float32
            or coords.ndim != 2
            or coords.shape[1:] != (3,)
            or not np.isfinite(coords).all()
        ):
            raise ValueError(f"candidate {candidate_id} coords must be finite float32 (N,3)")
        if present.dtype != np.dtype(bool) or present.shape != (len(coords),):
            raise ValueError(f"candidate {candidate_id} present mask does not align")
        if np.any(present):
            present_coords.append(coords[present])

    coords_xyz = (
        np.concatenate(present_coords, axis=0).astype(np.float32, copy=False)
        if present_coords
        else np.empty((0, 3), dtype=np.float32)
    )
    return LigandDistanceSource(
        coords_xyz=coords_xyz,
        source_exp_identity_sha256=_experimental_density_identity(exp_arrays),
        source_occurrences_sha256=sha256_file(occurrences_path),
        source_ligand_coords_sha256=sha256_file(coords_path),
    )


def ligand_distance_artifact_arrays(
    distance: np.ndarray,
    *,
    grid_shape_zyx: tuple[int, int, int],
    voxel_size_xyz: np.ndarray,
    origin_xyz: np.ndarray,
    source_exp_identity_sha256: str,
    source_occurrences_sha256: str,
    source_ligand_coords_sha256: str,
) -> dict[str, np.ndarray]:
    """把距离数值、空间定义和来源摘要组装为稳定 NPZ 字段。"""
    return {
        "distance": np.asarray(distance),
        "schema_version": np.asarray(LIGAND_DISTANCE_SCHEMA_VERSION, dtype=np.uint16),
        "source_exp_identity_sha256": np.asarray(source_exp_identity_sha256),
        "source_occurrences_sha256": np.asarray(source_occurrences_sha256),
        "source_ligand_coords_sha256": np.asarray(source_ligand_coords_sha256),
        "grid_shape_zyx": np.asarray(grid_shape_zyx, dtype=np.int64),
        "voxel_size_xyz": np.asarray(voxel_size_xyz, dtype=np.float32),
        "origin_xyz": np.asarray(origin_xyz, dtype=np.float32),
        "origin_semantics": np.asarray(LIGAND_DISTANCE_ORIGIN_SEMANTICS),
        "voxel_center_offset_xyz": np.asarray(
            LIGAND_DISTANCE_VOXEL_CENTER_OFFSET_XYZ,
            dtype=np.float32,
        ),
        "voxel_center_formula": np.asarray(LIGAND_DISTANCE_VOXEL_CENTER_FORMULA),
        "distance_unit": np.asarray(LIGAND_DISTANCE_UNIT),
    }


def ligand_distance_errors(
    arrays: dict[str, np.ndarray],
    *,
    grid_shape_zyx: tuple[int, int, int],
    voxel_size_xyz: np.ndarray,
    origin_xyz: np.ndarray,
    source_exp_identity_sha256: str,
    source_occurrences_sha256: str,
    source_ligand_coords_sha256: str,
    expected_distance: np.ndarray | None = None,
) -> list[str]:
    """验证 `ligand_dist.npz` 的字段、空间、来源和距离值语义。"""
    required = {
        "distance",
        "schema_version",
        "source_exp_identity_sha256",
        "source_occurrences_sha256",
        "source_ligand_coords_sha256",
        "grid_shape_zyx",
        "voxel_size_xyz",
        "origin_xyz",
        "origin_semantics",
        "voxel_center_offset_xyz",
        "voxel_center_formula",
        "distance_unit",
    }
    errors = [f"ligand_distance_missing:{key}" for key in sorted(required.difference(arrays))]
    unexpected = sorted(set(arrays).difference(required))
    if unexpected:
        errors.append("ligand_distance_contract:unexpected_keys:" + ",".join(unexpected))

    shape = tuple(int(value) for value in grid_shape_zyx)
    if "distance" in arrays:
        distance = np.asarray(arrays["distance"])
        if distance.dtype != np.float16 or distance.shape != (1, *shape):
            errors.append("ligand_distance_contract:distance")
        else:
            finite = np.isfinite(distance)
            positive_infinity = np.isposinf(distance)
            if np.isnan(distance).any() or np.isneginf(distance).any() or np.any(distance[finite] < 0):
                errors.append("ligand_distance_value:invalid")
            if np.any(finite) and np.any(positive_infinity):
                errors.append("ligand_distance_value:mixed_finite_and_infinite")
            if not np.all(finite | positive_infinity):
                errors.append("ligand_distance_value:invalid_nonfinite")
            if expected_distance is not None and not np.array_equal(
                distance,
                np.asarray(expected_distance),
            ):
                errors.append("ligand_distance_source_mismatch:distance")

    if "schema_version" in arrays:
        value = np.asarray(arrays["schema_version"])
        if value.dtype != np.uint16 or value.shape != () or int(value) != LIGAND_DISTANCE_SCHEMA_VERSION:
            errors.append("ligand_distance_contract:schema_version")

    expected_sources = {
        "source_exp_identity_sha256": source_exp_identity_sha256,
        "source_occurrences_sha256": source_occurrences_sha256,
        "source_ligand_coords_sha256": source_ligand_coords_sha256,
    }
    for key, expected in expected_sources.items():
        if key not in arrays:
            continue
        value = np.asarray(arrays[key])
        actual = str(value.item()) if value.shape == () else ""
        if value.shape != () or len(actual) != 64 or actual != expected:
            errors.append(f"ligand_distance_provenance:{key}")

    expected_vectors = {
        "grid_shape_zyx": np.asarray(shape, dtype=np.int64),
        "voxel_size_xyz": np.asarray(voxel_size_xyz, dtype=np.float32),
        "origin_xyz": np.asarray(origin_xyz, dtype=np.float32),
        "voxel_center_offset_xyz": np.asarray(
            LIGAND_DISTANCE_VOXEL_CENTER_OFFSET_XYZ,
            dtype=np.float32,
        ),
    }
    for key, expected in expected_vectors.items():
        if key not in arrays:
            continue
        actual = np.asarray(arrays[key])
        if actual.dtype != expected.dtype or not np.array_equal(actual, expected):
            errors.append(f"ligand_distance_contract:{key}")

    expected_text = {
        "origin_semantics": LIGAND_DISTANCE_ORIGIN_SEMANTICS,
        "voxel_center_formula": LIGAND_DISTANCE_VOXEL_CENTER_FORMULA,
        "distance_unit": LIGAND_DISTANCE_UNIT,
    }
    for key, expected in expected_text.items():
        if key not in arrays:
            continue
        value = np.asarray(arrays[key])
        if value.shape != () or str(value.item()) != expected:
            errors.append(f"ligand_distance_contract:{key}")
    return errors


def _load_inputs(
    root: Path,
    pdb_id: str,
) -> tuple[dict[str, np.ndarray], LigandDistanceSource]:
    """读取并验证一个 PDB 的实验密度与配体坐标来源。"""
    normalized_id = pdb_id.lower()
    inspection = _inspect_stage_c(root, normalized_id)
    if str(inspection.state.value) != "complete":
        raise RuntimeError(
            f"Stage C is not release-ready for {normalized_id}: "
            f"{inspection.state.value}: {inspection.reasons}"
        )
    exp = _load_npz_arrays(root / "density" / normalized_id / "exp.npz")
    exp_errors = density_artifact_errors(exp, require_unit_voxel=False)
    if exp_errors:
        raise RuntimeError(f"Stage E1 is not valid for {normalized_id}: {exp_errors}")
    source = load_ligand_distance_source(
        root,
        normalized_id,
        list(inspection.occurrences),
        exp,
    )
    return exp, source


def validate_ligand_distance_artifact(root: Path, pdb_id: str) -> list[str]:
    """按当前实验密度和配体来源只读核验一份距离文件。"""
    normalized_id = pdb_id.lower()
    try:
        exp, source = _load_inputs(root, normalized_id)
        arrays = _load_npz_arrays(root / "density" / normalized_id / "ligand_dist.npz")
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        return [f"ligand_distance:unreadable:{type(exc).__name__}:{exc}"]
    shape = tuple(int(value) for value in exp["grid"].shape[1:])
    return ligand_distance_errors(
        arrays,
        grid_shape_zyx=shape,
        voxel_size_xyz=exp["voxel_size"],
        origin_xyz=exp["origin"],
        source_exp_identity_sha256=source.source_exp_identity_sha256,
        source_occurrences_sha256=source.source_occurrences_sha256,
        source_ligand_coords_sha256=source.source_ligand_coords_sha256,
    )


def build_ligand_distance(
    root: Path,
    pdb_id: str,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """幂等生成一个 PDB 的 `density/{pdb_id}/ligand_dist.npz`。"""
    normalized_id = pdb_id.lower()
    exp, source = _load_inputs(root, normalized_id)
    shape = tuple(int(value) for value in exp["grid"].shape[1:])
    output_path = root / "density" / normalized_id / "ligand_dist.npz"
    validation_kwargs = {
        "grid_shape_zyx": shape,
        "voxel_size_xyz": exp["voxel_size"],
        "origin_xyz": exp["origin"],
        "source_exp_identity_sha256": source.source_exp_identity_sha256,
        "source_occurrences_sha256": source.source_occurrences_sha256,
        "source_ligand_coords_sha256": source.source_ligand_coords_sha256,
    }
    if output_path.exists() and not overwrite:
        try:
            existing = _load_npz_arrays(output_path)
            errors = ligand_distance_errors(existing, **validation_kwargs)
        except (OSError, ValueError, KeyError):
            errors = ["ligand_distance_unreadable"]
        if not errors:
            return {
                "status": "skipped",
                "artifact": str(output_path.relative_to(root)),
                "n_present_ligand_atoms": len(source.coords_xyz),
                "n_voxels": int(np.prod(shape)),
            }

    distance = build_ligand_distance_array(
        shape,
        exp["voxel_size"],
        exp["origin"],
        source.coords_xyz,
    )
    arrays = ligand_distance_artifact_arrays(distance, **validation_kwargs)
    errors = ligand_distance_errors(
        arrays,
        expected_distance=distance,
        **validation_kwargs,
    )
    if errors:
        raise RuntimeError(f"ligand distance contract failed for {normalized_id}: {errors}")
    atomic_save_npz(output_path, **arrays)
    written = _load_npz_arrays(output_path)
    written_errors = ligand_distance_errors(
        written,
        expected_distance=distance,
        **validation_kwargs,
    )
    if written_errors:
        raise RuntimeError(
            f"written ligand distance failed for {normalized_id}: {written_errors}"
        )
    return {
        "status": "success",
        "artifact": str(output_path.relative_to(root)),
        "n_present_ligand_atoms": len(source.coords_xyz),
        "n_voxels": int(np.prod(shape)),
    }
