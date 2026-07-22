"""生成并验证与实验密度网格对齐的稀疏配体区域。"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import numpy as np

from adaligand_preprocessing.artifacts.failures import KnownFailureCode, KnownSampleFailure
from adaligand_preprocessing.artifacts.validation import density_artifact_errors
from adaligand_preprocessing.geometry.legacy.voxel_centers import (
    _build_voxel_center_coords_xyz as _pocket_build_voxel_center_coords_xyz,
)
from adaligand_preprocessing.stages.stage_c.contracts import (
    CArtifactState,
    inspect_stage_c,
    load_npz_arrays,
)
from adaligand_preprocessing.stages.stage_e.common import (
    LIGAND_AREA_DISTANCE_PREDICATE,
    LIGAND_AREA_ORIGIN_SEMANTICS,
    LIGAND_AREA_SCHEMA_VERSION,
    LIGAND_AREA_STORAGE_ENCODING,
    LIGAND_AREA_VOXEL_CENTER_DTYPE,
    LIGAND_AREA_VOXEL_CENTER_FORMULA,
    LIGAND_AREA_VOXEL_CENTER_OFFSET_XYZ,
    VDW_RADIUS_SOURCE,
    LigandAreaSource,
    vdw_radius,
)
from adaligand_preprocessing.stages.stage_e.experimental import experimental_density_identity
from adaligand_preprocessing.utils.hashing import sha256_manifest, sha256_named_values
from adaligand_preprocessing.utils.io import (
    atomic_save_npz_compressed,
    safe_object_filename,
)

def _pocket_voxel_center_axes_xyz(
    grid_shape_zyx: tuple[int, int, int],
    origin_xyz: np.ndarray,
    voxel_size_xyz: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """直接用祖传整图函数的退化网格生成 X/Y/Z 单轴中心。"""
    depth, height, width = tuple(int(value) for value in grid_shape_zyx)
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


def load_ligand_area_source(
    root: Path,
    pdb_id: str,
    occurrences: list[dict[str, Any]],
    exp_arrays: dict[str, np.ndarray],
) -> LigandAreaSource:
    """
    从当前 Stage C 产物读取 E3 生产与 release audit 共用的原子输入。

    输入参数:
        - root: Path, Ori_Data 数据根目录
        - pdb_id: str, PDB id，大小写均可
        - occurrences: list[dict[str,Any]], 当前 Stage C 已验收 occurrence 记录
        - exp_arrays: dict[str,np.ndarray], 当前 E1 artifact 数组

    输出:
        - source: LigandAreaSource，包含 occurrence 顺序的 candidate id、各 occurrence
          present 原子的 ``(N,3) float32`` 世界 XYZ Å 坐标、``(N,)`` 原子序数和
          绑定 E1/Stage C/LigandObject 的来源 manifest SHA-256
    """
    normalized_id = pdb_id.lower()
    parse_dir = root / "parse" / normalized_id
    occurrence_path = parse_dir / "occurrences.jsonl"
    coords_path = parse_dir / "ligand_coords.npz"
    coords_arrays = load_npz_arrays(coords_path, allow_pickle=False)
    coords_by_candidate: dict[int, np.ndarray] = {}
    atomic_numbers_by_candidate: dict[int, np.ndarray] = {}
    object_paths: list[Path] = []
    candidate_ids: list[int] = []
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        candidate_ids.append(candidate_id)
        coords = coords_arrays[f"coords_{candidate_id}"]
        present = coords_arrays[f"present_{candidate_id}"]
        object_path = (
            root
            / "ligand_objects"
            / f"{safe_object_filename(str(occurrence['object_key']))}.npz"
        )
        object_paths.append(object_path)
        with np.load(object_path, allow_pickle=True) as ligand_object:
            atomic_numbers = ligand_object["atoms"]["element"].astype(np.int16, copy=True)
        if len(atomic_numbers) != len(coords):
            raise RuntimeError(f"LigandObject row mismatch for candidate {candidate_id}")
        coords_by_candidate[candidate_id] = coords[present]
        atomic_numbers_by_candidate[candidate_id] = atomic_numbers[present]

    small_source_manifest = sha256_manifest(
        [occurrence_path, coords_path, *sorted(set(object_paths))],
        base=root,
    )
    source_manifest = sha256_named_values(
        {
            "exp_identity_sha256": experimental_density_identity(exp_arrays),
            "small_source_manifest_sha256": small_source_manifest,
        }
    )
    return LigandAreaSource(
        candidate_ids=tuple(candidate_ids),
        coords_by_candidate=coords_by_candidate,
        atomic_numbers_by_candidate=atomic_numbers_by_candidate,
        source_manifest_sha256=source_manifest,
    )


def build_ligand_area_arrays(
    grid_shape_zyx: tuple[int, int, int],
    voxel_size_xyz: np.ndarray,
    origin_xyz: np.ndarray,
    ligand_coords_by_candidate: dict[int, np.ndarray],
    atomic_numbers_by_candidate: dict[int, np.ndarray],
) -> dict[str, np.ndarray]:
    """
    用逐原子局部 voxel-center stencil 生成稀疏 occurrence mask 和全局 union。

    ``mask_{cid}`` 是唯一、字典序排序的 ``(K,3) int32`` ZYX 索引；
    ``centroid_voxel_{cid}`` 虽沿用既定字段名，数值是 mask 体素中心的世界 XYZ Å。

    ``origin_xyz`` 采用 Pocket Plus 的网格下角点语义，因此索引 ``(x,y,z)``
    对应的体素中心必须是 ``origin + (index + 0.5) * voxel``。Stage C 原子坐标
    与体素中心都遵循 Pocket 的 float32 数值行为，再以 float64 累加 distance²；
    最终判据仍是既有 ``distance² <= radius² + 1e-8``，半径语义不变。
    """
    shape = tuple(int(value) for value in grid_shape_zyx)
    if len(shape) != 3 or any(value <= 1 for value in shape):
        raise ValueError("grid_shape_zyx must contain three dimensions > 1")
    voxel_f32 = np.asarray(voxel_size_xyz, dtype=np.float32)
    origin_f32 = np.asarray(origin_xyz, dtype=np.float32)
    if (
        voxel_f32.shape != (3,)
        or origin_f32.shape != (3,)
        or not np.isfinite(voxel_f32).all()
        or not np.isfinite(origin_f32).all()
        or np.any(voxel_f32 <= 0)
    ):
        raise ValueError("voxel_size_xyz/origin_xyz must be valid XYZ vectors")
    if set(ligand_coords_by_candidate) != set(atomic_numbers_by_candidate):
        raise ValueError("coordinate and element candidate ids differ")

    union_flat = np.zeros((int(np.prod(shape)),), dtype=bool)
    arrays: dict[str, np.ndarray] = {}
    axis_centers_f32 = _pocket_voxel_center_axes_xyz(
        shape,
        origin_f32,
        voxel_f32,
    )
    axis_centers = tuple(values.astype(np.float64) for values in axis_centers_f32)
    for candidate_id in sorted(ligand_coords_by_candidate):
        coords_f32 = np.asarray(ligand_coords_by_candidate[candidate_id], dtype=np.float32)
        coords = coords_f32.astype(np.float64)
        atomic_numbers = np.asarray(atomic_numbers_by_candidate[candidate_id])
        if coords.ndim != 2 or coords.shape[1:] != (3,) or not np.isfinite(coords).all():
            raise ValueError(f"candidate {candidate_id} coords must be finite (M,3)")
        if atomic_numbers.ndim != 1 or len(atomic_numbers) != len(coords):
            raise ValueError(f"candidate {candidate_id} atomic numbers do not align")

        chunks: list[np.ndarray] = []
        for coord, atomic_number in zip(coords, atomic_numbers, strict=True):
            radius = vdw_radius(int(atomic_number))
            # float, Å；与最终 ``distance² <= radius² + 1e-8`` 完全一致。
            effective_radius = float(np.sqrt(radius * radius + 1e-8))
            # 不再推导 bbox 或近似索引范围：直接在祖传函数实际生成的
            # float32 体素中心上做逐轴必要条件筛选，再由下方球内谓词定案。
            x_indices = np.flatnonzero(
                np.abs(axis_centers[0] - coord[0]) <= effective_radius
            ).astype(np.int64, copy=False)
            y_indices = np.flatnonzero(
                np.abs(axis_centers[1] - coord[1]) <= effective_radius
            ).astype(np.int64, copy=False)
            z_indices = np.flatnonzero(
                np.abs(axis_centers[2] - coord[2]) <= effective_radius
            ).astype(np.int64, copy=False)
            if not len(x_indices) or not len(y_indices) or not len(z_indices):
                continue
            center_x = axis_centers_f32[0][x_indices]
            center_y = axis_centers_f32[1][y_indices]
            center_z = axis_centers_f32[2][z_indices]
            dx2 = (center_x.astype(np.float64) - coord[0]) ** 2
            dy2 = (center_y.astype(np.float64) - coord[1]) ** 2
            dz2 = (center_z.astype(np.float64) - coord[2]) ** 2
            local = (
                dz2[:, None, None]
                + dy2[None, :, None]
                + dx2[None, None, :]
                <= radius * radius + 1e-8
            )
            local_z, local_y, local_x = np.nonzero(local)
            if len(local_z) == 0:
                continue
            linear = np.ravel_multi_index(
                (
                    z_indices[local_z],
                    y_indices[local_y],
                    x_indices[local_x],
                ),
                shape,
            )
            chunks.append(linear.astype(np.int64, copy=False))
        if not chunks:
            raise KnownSampleFailure(
                KnownFailureCode.NO_PRESENT_LIGAND_ATOMS,
                f"candidate {candidate_id} has no ligand-area voxel inside canonical grid",
            )
        linear_indices = np.unique(np.concatenate(chunks))
        z_index, y_index, x_index = np.unravel_index(linear_indices, shape)
        mask_indices = np.column_stack((z_index, y_index, x_index)).astype(np.int32)
        centroid_xyz = np.asarray(
            [
                axis_centers_f32[0][x_index].astype(np.float64).mean(),
                axis_centers_f32[1][y_index].astype(np.float64).mean(),
                axis_centers_f32[2][z_index].astype(np.float64).mean(),
            ],
            dtype=np.float64,
        )
        arrays[f"mask_{candidate_id}"] = mask_indices
        arrays[f"centroid_voxel_{candidate_id}"] = centroid_xyz.astype(np.float32)
        union_flat[linear_indices] = True
    arrays["union_mask"] = union_flat.reshape(shape)[None]
    return arrays


def _ligand_area_zip_errors(
    artifact_path: Path,
    array_keys: set[str],
) -> list[str]:
    """验证 E3 文件的 ZIP 成员集合与真实 DEFLATED 编码。"""
    try:
        with zipfile.ZipFile(artifact_path, "r") as archive:
            members = [member for member in archive.infolist() if not member.is_dir()]
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return ["ligand_area_storage:invalid_zip"]

    errors: list[str] = []
    expected_names = {f"{key}.npy" for key in array_keys}
    actual_names = {member.filename for member in members}
    if actual_names != expected_names or len(actual_names) != len(members):
        errors.append("ligand_area_storage:member_set")
    if any(member.compress_type != zipfile.ZIP_DEFLATED for member in members):
        errors.append("ligand_area_storage:not_zip_deflated")
    return errors


def ligand_area_errors(
    arrays: dict[str, np.ndarray],
    *,
    grid_shape_zyx: tuple[int, int, int],
    voxel_size_xyz: np.ndarray,
    origin_xyz: np.ndarray,
    candidate_ids: list[int],
    source_manifest_sha256: str,
    expected_source_arrays: dict[str, np.ndarray] | None = None,
    artifact_path: Path | None = None,
) -> list[str]:
    """
    验证 E3 v3 自描述契约，并可按当前 Stage C 原子重建结果验证科学内容。

    ``expected_source_arrays`` 必须来自 ``build_ligand_area_arrays``，只比较
    ``union_mask``、各 ``mask_{cid}`` 与 ``centroid_voxel_{cid}``；本函数不实现
    第二套几何或半径公式。未传入时仅执行通用 schema/内部自洽验证。
    """
    errors: list[str] = []
    shape = tuple(int(value) for value in grid_shape_zyx)
    origin_f32 = np.asarray(origin_xyz, dtype=np.float32)
    voxel_f32 = np.asarray(voxel_size_xyz, dtype=np.float32)
    axis_centers_f32 = _pocket_voxel_center_axes_xyz(
        shape,
        origin_f32,
        voxel_f32,
    )

    required_keys = {
        "union_mask",
        "schema_version",
        "source_manifest_sha256",
        "centroid_coordinate_system",
        "mask_index_order",
        "vdw_radius_source",
        "grid_shape_zyx",
        "voxel_size_xyz",
        "origin_xyz",
        "origin_semantics",
        "voxel_center_offset_xyz",
        "voxel_center_formula",
        "voxel_center_dtype",
        "distance_predicate",
        "storage_encoding",
    }
    for key in sorted(required_keys.difference(arrays)):
        errors.append(f"ligand_area_missing:{key}")

    if "schema_version" in arrays:
        schema = np.asarray(arrays["schema_version"])
        if (
            schema.dtype != np.uint16
            or schema.shape != ()
            or int(schema) != LIGAND_AREA_SCHEMA_VERSION
        ):
            errors.append("ligand_area_contract:schema_version")
    if "source_manifest_sha256" in arrays:
        source_manifest = np.asarray(arrays["source_manifest_sha256"])
        stored_source_manifest = (
            str(source_manifest.item()) if source_manifest.shape == () else ""
        )
        if (
            source_manifest.shape != ()
            or len(stored_source_manifest) != 64
            or stored_source_manifest != source_manifest_sha256
        ):
            errors.append("ligand_area_provenance:source_manifest")

    expected_text = {
        "centroid_coordinate_system": "world_xyz_angstrom",
        "mask_index_order": "zyx",
        "vdw_radius_source": VDW_RADIUS_SOURCE,
        "origin_semantics": LIGAND_AREA_ORIGIN_SEMANTICS,
        "voxel_center_formula": LIGAND_AREA_VOXEL_CENTER_FORMULA,
        "voxel_center_dtype": LIGAND_AREA_VOXEL_CENTER_DTYPE,
        "distance_predicate": LIGAND_AREA_DISTANCE_PREDICATE,
        "storage_encoding": LIGAND_AREA_STORAGE_ENCODING,
    }
    for key, expected in expected_text.items():
        if key not in arrays:
            continue
        value = np.asarray(arrays[key])
        if value.shape != () or str(value.item()) != expected:
            errors.append(f"ligand_area_contract:{key}")

    expected_vectors = {
        "grid_shape_zyx": np.asarray(shape, dtype=np.int64),
        "voxel_size_xyz": voxel_f32,
        "origin_xyz": origin_f32,
        "voxel_center_offset_xyz": np.asarray(
            LIGAND_AREA_VOXEL_CENTER_OFFSET_XYZ,
            dtype=np.float32,
        ),
    }
    for key, expected in expected_vectors.items():
        if key not in arrays:
            continue
        value = np.asarray(arrays[key])
        if value.dtype != expected.dtype or not np.array_equal(value, expected):
            errors.append(f"ligand_area_contract:{key}")

    expected_candidate_ids = {int(candidate_id) for candidate_id in candidate_ids}
    if len(expected_candidate_ids) != len(candidate_ids):
        errors.append("ligand_area_contract:duplicate_candidate_ids")
    dynamic_keys = {
        key
        for candidate_id in expected_candidate_ids
        for key in (
            f"mask_{candidate_id}",
            f"centroid_voxel_{candidate_id}",
        )
    }
    unexpected_keys = set(arrays).difference(required_keys | dynamic_keys)
    if unexpected_keys:
        errors.append(
            "ligand_area_contract:unexpected_keys:"
            + ",".join(sorted(unexpected_keys))
        )

    union = arrays.get("union_mask")
    union_valid = (
        union is not None
        and np.asarray(union).dtype == np.dtype(bool)
        and np.asarray(union).shape == (1, *shape)
    )
    if not union_valid:
        errors.append("ligand_area_contract:union_mask")
    reconstructed = np.zeros(shape, dtype=bool)
    for candidate_id in candidate_ids:
        mask_key = f"mask_{candidate_id}"
        centroid_key = f"centroid_voxel_{candidate_id}"
        if mask_key not in arrays or centroid_key not in arrays:
            errors.append(f"ligand_area_missing:{candidate_id}")
            continue
        indices = np.asarray(arrays[mask_key])
        centroid = np.asarray(arrays[centroid_key])
        if (
            indices.dtype != np.int32
            or indices.ndim != 2
            or indices.shape[1:] != (3,)
            or len(indices) == 0
        ):
            errors.append(f"ligand_area_contract:mask:{candidate_id}")
            continue
        if np.any(indices < 0) or np.any(indices >= np.asarray(shape, dtype=np.int32)):
            errors.append(f"ligand_area_value:mask_range:{candidate_id}")
            continue
        linear = np.ravel_multi_index(indices.T, shape)
        if len(np.unique(linear)) != len(linear) or np.any(np.diff(linear) <= 0):
            errors.append(f"ligand_area_value:mask_order:{candidate_id}")
        reconstructed[tuple(indices.T)] = True
        expected_centroid = np.asarray(
            [
                axis_centers_f32[0][indices[:, 2]].astype(np.float64).mean(),
                axis_centers_f32[1][indices[:, 1]].astype(np.float64).mean(),
                axis_centers_f32[2][indices[:, 0]].astype(np.float64).mean(),
            ],
            dtype=np.float64,
        )
        expected_centroid_f32 = expected_centroid.astype(np.float32)
        if (
            centroid.dtype != np.float32
            or centroid.shape != (3,)
            or not np.array_equal(centroid, expected_centroid_f32)
        ):
            errors.append(f"ligand_area_value:centroid:{candidate_id}")
    if union_valid and not np.array_equal(np.asarray(union)[0], reconstructed):
        errors.append("ligand_area_value:union")
    if expected_source_arrays is not None:
        source_keys = [
            "union_mask",
            *[
                key
                for candidate_id in candidate_ids
                for key in (
                    f"mask_{candidate_id}",
                    f"centroid_voxel_{candidate_id}",
                )
            ],
        ]
        for key in source_keys:
            actual = arrays.get(key)
            expected = expected_source_arrays.get(key)
            if (
                actual is None
                or expected is None
                or np.asarray(actual).dtype != np.asarray(expected).dtype
                or not np.array_equal(np.asarray(actual), np.asarray(expected))
            ):
                errors.append(f"ligand_area_source_mismatch:{key}")
    if artifact_path is not None:
        errors.extend(_ligand_area_zip_errors(artifact_path, set(arrays)))
    return errors


def validate_ligand_area_artifact(root: Path, pdb_id: str) -> list[str]:
    """按当前 Stage C 来源与 Stage E 契约只读核验一份 `ligand_area.npz`。"""
    normalized_id = pdb_id.lower()
    inspection = inspect_stage_c(root, normalized_id)
    if inspection.state is not CArtifactState.COMPLETE:
        return [f"stage_c:{inspection.state.value}:{','.join(inspection.reasons)}"]
    occurrences = list(inspection.occurrences)
    if not occurrences:
        return ["stage_c:no_occurrences"]

    exp_path = root / "density" / normalized_id / "exp.npz"
    try:
        exp = load_npz_arrays(exp_path, allow_pickle=False)
    except (OSError, ValueError, KeyError) as exc:
        return [f"exp:unreadable:{type(exc).__name__}"]
    exp_errors = density_artifact_errors(exp, require_unit_voxel=False)
    if exp_errors:
        return [f"exp:{error}" for error in exp_errors]

    try:
        source = load_ligand_area_source(root, normalized_id, occurrences, exp)
        expected_source_arrays = build_ligand_area_arrays(
            tuple(int(value) for value in exp["grid"].shape[1:]),
            exp["voxel_size"],
            exp["origin"],
            source.coords_by_candidate,
            source.atomic_numbers_by_candidate,
        )
        artifact_path = root / "density" / normalized_id / "ligand_area.npz"
        arrays = load_npz_arrays(artifact_path, allow_pickle=False)
    except KnownSampleFailure as exc:
        return [f"ligand_area_source_rebuild:{exc.code.value}"]
    except (OSError, ValueError, KeyError) as exc:
        return [f"ligand_area:unreadable:{type(exc).__name__}"]

    return ligand_area_errors(
        arrays,
        grid_shape_zyx=tuple(int(value) for value in exp["grid"].shape[1:]),
        voxel_size_xyz=exp["voxel_size"],
        origin_xyz=exp["origin"],
        candidate_ids=list(source.candidate_ids),
        source_manifest_sha256=source.source_manifest_sha256,
        expected_source_arrays=expected_source_arrays,
        artifact_path=artifact_path,
    )


def build_ligand_area(
    root: Path,
    pdb_id: str,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """从 E1 与已验收 C 产物幂等生成一个 PDB 的 E3 artifact。"""
    normalized_id = pdb_id.lower()
    inspection = inspect_stage_c(root, normalized_id)
    if inspection.state is not CArtifactState.COMPLETE:
        raise RuntimeError(
            f"Stage C is not release-ready for {normalized_id}: "
            f"{inspection.state.value}: {inspection.reasons}"
        )
    occurrences = list(inspection.occurrences)
    if not occurrences:
        raise KnownSampleFailure(KnownFailureCode.NO_OCCURRENCES, "no eligible occurrence")
    exp_path = root / "density" / normalized_id / "exp.npz"
    exp = load_npz_arrays(exp_path, allow_pickle=False)
    exp_errors = density_artifact_errors(exp, require_unit_voxel=False)
    if exp_errors:
        raise RuntimeError(f"Stage E1 is not valid for {normalized_id}: {exp_errors}")

    source = load_ligand_area_source(root, normalized_id, occurrences, exp)
    output_path = root / "density" / normalized_id / "ligand_area.npz"
    shape = tuple(int(value) for value in exp["grid"].shape[1:])
    expected_source_arrays = build_ligand_area_arrays(
        shape,
        exp["voxel_size"],
        exp["origin"],
        source.coords_by_candidate,
        source.atomic_numbers_by_candidate,
    )
    validation_kwargs = {
        "grid_shape_zyx": shape,
        "voxel_size_xyz": exp["voxel_size"],
        "origin_xyz": exp["origin"],
        "candidate_ids": list(source.candidate_ids),
        "source_manifest_sha256": source.source_manifest_sha256,
        "expected_source_arrays": expected_source_arrays,
    }
    if output_path.exists() and not overwrite:
        try:
            existing = load_npz_arrays(output_path, allow_pickle=False)
            errors = ligand_area_errors(
                existing,
                artifact_path=output_path,
                **validation_kwargs,
            )
        except (OSError, ValueError, KeyError):
            errors = ["ligand_area_unreadable"]
        if not errors:
            return {
                "status": "skipped",
                "artifact": str(output_path.relative_to(root)),
                "n_occurrences": len(source.candidate_ids),
            }

    arrays = dict(expected_source_arrays)
    arrays.update(
        {
            "schema_version": np.asarray(LIGAND_AREA_SCHEMA_VERSION, dtype=np.uint16),
            "source_manifest_sha256": np.asarray(source.source_manifest_sha256),
            "centroid_coordinate_system": np.asarray("world_xyz_angstrom"),
            "mask_index_order": np.asarray("zyx"),
            "vdw_radius_source": np.asarray(VDW_RADIUS_SOURCE),
            "grid_shape_zyx": np.asarray(shape, dtype=np.int64),
            "voxel_size_xyz": np.asarray(exp["voxel_size"], dtype=np.float32),
            "origin_xyz": np.asarray(exp["origin"], dtype=np.float32),
            "origin_semantics": np.asarray(LIGAND_AREA_ORIGIN_SEMANTICS),
            "voxel_center_offset_xyz": np.asarray(
                LIGAND_AREA_VOXEL_CENTER_OFFSET_XYZ,
                dtype=np.float32,
            ),
            "voxel_center_formula": np.asarray(LIGAND_AREA_VOXEL_CENTER_FORMULA),
            "voxel_center_dtype": np.asarray(LIGAND_AREA_VOXEL_CENTER_DTYPE),
            "distance_predicate": np.asarray(LIGAND_AREA_DISTANCE_PREDICATE),
            "storage_encoding": np.asarray(LIGAND_AREA_STORAGE_ENCODING),
        }
    )
    errors = ligand_area_errors(arrays, **validation_kwargs)
    if errors:
        raise RuntimeError(f"Stage E3 contract failed for {normalized_id}: {errors}")

    def _validate_temporary_artifact(tmp_path: Path) -> None:
        """在原子替换前重读压缩临时文件并执行完整 E3 validator。"""
        written = load_npz_arrays(tmp_path, allow_pickle=False)
        written_errors = ligand_area_errors(
            written,
            artifact_path=tmp_path,
            **validation_kwargs,
        )
        if written_errors:
            raise RuntimeError(
                f"Stage E3 written artifact failed for {normalized_id}: "
                f"{written_errors}"
            )

    atomic_save_npz_compressed(
        output_path,
        validator=_validate_temporary_artifact,
        **arrays,
    )
    return {
        "status": "success",
        "artifact": str(output_path.relative_to(root)),
        "n_occurrences": len(source.candidate_ids),
        "n_union_voxels": int(np.count_nonzero(arrays["union_mask"])),
    }

