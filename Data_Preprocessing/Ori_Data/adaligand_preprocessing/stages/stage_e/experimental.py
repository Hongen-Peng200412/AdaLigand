"""生成并验证实验密度图及其推荐等高线。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from adaligand_preprocessing.artifacts.failures import KnownFailureCode, KnownSampleFailure
from adaligand_preprocessing.artifacts.validation import density_artifact_errors
from adaligand_preprocessing.geometry.mrc import (
    POCKET_MRC_ALGORITHM,
    POCKET_MRC_ANCESTOR_SHA256,
    POCKET_MRC_VENDOR_SHA256,
    POCKET_RESAMPLE_ALL_DIFF,
    POCKET_RESAMPLE_ALL_EQUAL,
    POCKET_RESAMPLE_MIXED_COMPAT,
    canonicalization_info,
    load_map,
    make_canonical_grid,
)
from adaligand_preprocessing.stages.stage_c.contracts import load_npz_arrays
from adaligand_preprocessing.stages.stage_e.common import (
    EXP_SCHEMA_VERSION,
    MRC_SOURCE_ORIGIN_MODE,
    MRC_TARGET_VOXEL_SIZE,
    extract_recommended_contour,
)
from adaligand_preprocessing.utils.hashing import sha256_file, sha256_named_values
from adaligand_preprocessing.utils.io import atomic_save_npz

def experimental_density_errors(
    arrays: dict[str, np.ndarray],
    *,
    source_map_size: int,
    source_map_mtime_ns: int,
    source_meta_size: int,
    source_meta_mtime_ns: int,
) -> list[str]:
    """验证 E1 artifact，包括 contour null 编码和快速输入 provenance。"""
    errors = density_artifact_errors(arrays, require_unit_voxel=False)
    required = {
        "contour",
        "contour_native",
        "contour_canonical",
        "contour_scale_to_canonical",
        "contour_present",
        "contour_status",
        "contour_path",
        "contour_source",
        "schema_version",
        "source_map_sha256",
        "source_meta_sha256",
        "source_map_size",
        "source_map_mtime_ns",
        "source_meta_size",
        "source_meta_mtime_ns",
        "target_voxel_size",
        "mrc_algorithm",
        "mrc_ancestor_sha256",
        "mrc_vendor_sha256",
        "source_origin_mode",
        "native_shape_zyx",
        "even_input_shape_zyx",
        "canonical_shape_zyx",
        "resample_mode",
    }
    for key in sorted(required.difference(arrays)):
        errors.append(f"exp_missing:{key}")
    if required.difference(arrays):
        return errors

    contour = np.asarray(arrays["contour"])
    contour_native = np.asarray(arrays["contour_native"])
    contour_canonical = np.asarray(arrays["contour_canonical"])
    contour_scale = np.asarray(arrays["contour_scale_to_canonical"])
    present = np.asarray(arrays["contour_present"])
    if contour.dtype != np.float32 or contour.shape != ():
        errors.append("exp_contract:contour")
    if contour_native.dtype != np.float32 or contour_native.shape != ():
        errors.append("exp_contract:contour_native")
    elif contour.shape == () and not np.array_equal(contour, contour_native, equal_nan=True):
        errors.append("exp_value:contour_native_alias")
    if contour_canonical.dtype != np.float32 or contour_canonical.shape != ():
        errors.append("exp_contract:contour_canonical")
    if (
        contour_scale.dtype != np.float64
        or contour_scale.shape != ()
        or not np.isfinite(float(contour_scale))
        or float(contour_scale) <= 0
    ):
        errors.append("exp_contract:contour_scale_to_canonical")
    if present.dtype != np.dtype(bool) or present.shape != ():
        errors.append("exp_contract:contour_present")
    elif bool(present):
        if contour.shape != () or not np.isfinite(float(contour)):
            errors.append("exp_value:present_contour")
        if contour_native.shape != () or not np.isfinite(float(contour_native)):
            errors.append("exp_value:present_contour_native")
        if contour_canonical.shape != () or not np.isfinite(float(contour_canonical)):
            errors.append("exp_value:present_contour_canonical")
        if (
            contour_native.shape == ()
            and contour_canonical.shape == ()
            and contour_scale.shape == ()
            and np.isfinite(float(contour_native))
            and np.isfinite(float(contour_scale))
        ):
            expected_canonical = np.float32(float(contour_native) * float(contour_scale))
            if not np.array_equal(contour_canonical, np.asarray(expected_canonical)):
                errors.append("exp_value:contour_canonical_scale")
        if str(np.asarray(arrays["contour_status"]).item()) != "ok":
            errors.append("exp_value:contour_status")
    else:
        for key, value in (
            ("contour", contour),
            ("contour_native", contour_native),
            ("contour_canonical", contour_canonical),
        ):
            if value.shape == () and not np.isnan(float(value)):
                errors.append(f"exp_value:missing_{key}_not_nan")
    schema = np.asarray(arrays["schema_version"])
    if schema.shape != () or int(schema) != EXP_SCHEMA_VERSION:
        errors.append("exp_contract:schema_version")
    target_voxel = np.asarray(arrays["target_voxel_size"])
    if (
        target_voxel.dtype != np.float32
        or target_voxel.shape != ()
        or not np.isclose(float(target_voxel), MRC_TARGET_VOXEL_SIZE, rtol=0, atol=1e-6)
    ):
        errors.append("exp_contract:target_voxel_size")
    expected_text = {
        "mrc_algorithm": POCKET_MRC_ALGORITHM,
        "mrc_ancestor_sha256": POCKET_MRC_ANCESTOR_SHA256,
        "mrc_vendor_sha256": POCKET_MRC_VENDOR_SHA256,
        "source_origin_mode": MRC_SOURCE_ORIGIN_MODE,
    }
    for key, expected in expected_text.items():
        if str(np.asarray(arrays[key]).item()) != expected:
            errors.append(f"exp_contract:{key}")
    if str(np.asarray(arrays["resample_mode"]).item()) not in {
        POCKET_RESAMPLE_ALL_EQUAL,
        POCKET_RESAMPLE_ALL_DIFF,
        POCKET_RESAMPLE_MIXED_COMPAT,
    }:
        errors.append("exp_contract:resample_mode")
    native_shape = np.asarray(arrays["native_shape_zyx"])
    even_input_shape = np.asarray(arrays["even_input_shape_zyx"])
    canonical_shape = np.asarray(arrays["canonical_shape_zyx"])
    for key, value in (
        ("native_shape_zyx", native_shape),
        ("even_input_shape_zyx", even_input_shape),
        ("canonical_shape_zyx", canonical_shape),
    ):
        if value.dtype != np.int64 or value.shape != (3,) or np.any(value <= 0):
            errors.append(f"exp_contract:{key}")
    if (
        native_shape.dtype == np.int64
        and native_shape.shape == (3,)
        and canonical_shape.dtype == np.int64
        and canonical_shape.shape == (3,)
        and np.all(native_shape > 0)
        and np.all(canonical_shape > 0)
        and contour_scale.shape == ()
        and np.isfinite(float(contour_scale))
    ):
        try:
            info = canonicalization_info(tuple(native_shape), tuple(canonical_shape))
        except ValueError:
            errors.append("exp_contract:canonicalization_info")
        else:
            if not np.array_equal(even_input_shape, np.asarray(info.even_input_shape_zyx)):
                errors.append("exp_value:even_input_shape_zyx")
            if not np.array_equal(canonical_shape, np.asarray(arrays["grid"]).shape[1:]):
                errors.append("exp_value:canonical_shape_zyx")
            if str(np.asarray(arrays["resample_mode"]).item()) != info.resample_mode:
                errors.append("exp_value:resample_mode")
            if not np.isclose(
                float(contour_scale),
                info.contour_scale_to_canonical,
                rtol=0,
                atol=1e-12,
            ):
                errors.append("exp_value:contour_scale_to_canonical")

    expected_stats = {
        "source_map_size": source_map_size,
        "source_map_mtime_ns": source_map_mtime_ns,
        "source_meta_size": source_meta_size,
        "source_meta_mtime_ns": source_meta_mtime_ns,
    }
    for key, expected in expected_stats.items():
        value = np.asarray(arrays[key])
        if value.shape != () or int(value) != expected:
            errors.append(f"exp_provenance:{key}")
    for key in ("source_map_sha256", "source_meta_sha256"):
        value = str(np.asarray(arrays[key]).item())
        if len(value) != 64:
            errors.append(f"exp_provenance:{key}")
    return errors


def build_experimental_density(
    root: Path,
    record: dict[str, Any],
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """幂等生成一个 PDB 的目标 1 Å、实际 voxel 随 artifact 落盘的实验图。"""
    pdb_id = str(record["pdb_id"]).lower()
    emdb_id = str(record["emdb_id"]).upper()
    map_path = root / "raw" / "emdb_maps" / f"emd_{emdb_id.replace('EMD-', '')}.map.gz"
    meta_path = root / "reports" / "meta" / f"{pdb_id}.meta.json"
    if not map_path.exists():
        raise KnownSampleFailure(KnownFailureCode.MISSING_MAP, str(map_path))
    if not meta_path.exists():
        raise KnownSampleFailure(KnownFailureCode.MISSING_META, str(meta_path))
    map_stat = map_path.stat()
    meta_stat = meta_path.stat()
    output_path = root / "density" / pdb_id / "exp.npz"

    if output_path.exists() and not overwrite:
        try:
            existing = load_npz_arrays(output_path, allow_pickle=False)
            errors = experimental_density_errors(
                existing,
                source_map_size=map_stat.st_size,
                source_map_mtime_ns=map_stat.st_mtime_ns,
                source_meta_size=meta_stat.st_size,
                source_meta_mtime_ns=meta_stat.st_mtime_ns,
            )
        except (OSError, ValueError, KeyError):
            errors = ["exp_unreadable"]
        if not errors:
            return {
                "status": "skipped",
                "artifact": str(output_path.relative_to(root)),
                "shape_zyx": list(existing["grid"].shape[1:]),
                "contour_status": str(existing["contour_status"].item()),
                "resample_mode": str(existing["resample_mode"].item()),
                "contour_scale_to_canonical": float(existing["contour_scale_to_canonical"]),
            }

    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("EMDB metadata root must be an object")
    contour = extract_recommended_contour(metadata)
    native = load_map(map_path, multiply_global_origin=True)
    canonical = make_canonical_grid(
        native,
        target_voxel_size=MRC_TARGET_VOXEL_SIZE,
    )
    canonical_info = canonicalization_info(native.grid.shape, canonical.grid.shape)
    contour_native = np.asarray(
        np.nan if contour.value is None else contour.value,
        dtype=np.float32,
    )
    contour_canonical = np.asarray(
        np.nan
        if contour.value is None
        else np.float32(float(contour_native) * canonical_info.contour_scale_to_canonical),
        dtype=np.float32,
    )
    arrays = {
        "grid": canonical.grid[None].astype(np.float32, copy=False),
        "voxel_size": canonical.voxel_size.astype(np.float32, copy=False),
        "origin": canonical.origin.astype(np.float32, copy=False),
        "contour": contour_native.copy(),
        "contour_native": contour_native,
        "contour_canonical": contour_canonical,
        "contour_scale_to_canonical": np.asarray(
            canonical_info.contour_scale_to_canonical,
            dtype=np.float64,
        ),
        "contour_present": np.asarray(contour.value is not None, dtype=bool),
        "contour_status": np.asarray(contour.status),
        "contour_path": np.asarray(contour.path),
        "contour_source": np.asarray(contour.source or ""),
        "schema_version": np.asarray(EXP_SCHEMA_VERSION, dtype=np.uint16),
        "source_map_sha256": np.asarray(sha256_file(map_path)),
        "source_meta_sha256": np.asarray(sha256_file(meta_path)),
        "source_map_size": np.asarray(map_stat.st_size, dtype=np.int64),
        "source_map_mtime_ns": np.asarray(map_stat.st_mtime_ns, dtype=np.int64),
        "source_meta_size": np.asarray(meta_stat.st_size, dtype=np.int64),
        "source_meta_mtime_ns": np.asarray(meta_stat.st_mtime_ns, dtype=np.int64),
        "target_voxel_size": np.asarray(MRC_TARGET_VOXEL_SIZE, dtype=np.float32),
        "mrc_algorithm": np.asarray(POCKET_MRC_ALGORITHM),
        "mrc_ancestor_sha256": np.asarray(POCKET_MRC_ANCESTOR_SHA256),
        "mrc_vendor_sha256": np.asarray(POCKET_MRC_VENDOR_SHA256),
        "source_origin_mode": np.asarray(MRC_SOURCE_ORIGIN_MODE),
        "native_shape_zyx": np.asarray(canonical_info.input_shape_zyx, dtype=np.int64),
        "even_input_shape_zyx": np.asarray(
            canonical_info.even_input_shape_zyx,
            dtype=np.int64,
        ),
        "canonical_shape_zyx": np.asarray(canonical_info.output_shape_zyx, dtype=np.int64),
        "resample_mode": np.asarray(canonical_info.resample_mode),
    }
    errors = experimental_density_errors(
        arrays,
        source_map_size=map_stat.st_size,
        source_map_mtime_ns=map_stat.st_mtime_ns,
        source_meta_size=meta_stat.st_size,
        source_meta_mtime_ns=meta_stat.st_mtime_ns,
    )
    if errors:
        raise RuntimeError(f"Stage E1 contract failed for {pdb_id}: {errors}")
    atomic_save_npz(output_path, **arrays)
    return {
        "status": "success",
        "artifact": str(output_path.relative_to(root)),
        "shape_zyx": list(canonical.grid.shape),
        "contour_status": contour.status,
        "resample_mode": canonical_info.resample_mode,
        "contour_scale_to_canonical": canonical_info.contour_scale_to_canonical,
    }


def experimental_density_identity(arrays: dict[str, np.ndarray]) -> str:
    """
    用 E1 原始输入摘要、canonical 几何和算法版本构造稳定 identity。

    调用方已读取并执行密度内容 QC，因此 E2/E3/F 不必再顺序扫描一次大型 ``exp.npz``。
    """
    return sha256_named_values(
        {
            "schema_version": int(np.asarray(arrays["schema_version"])),
            "shape_zyx": [int(value) for value in np.asarray(arrays["grid"]).shape[1:]],
            "voxel_size_xyz": [float(value) for value in np.asarray(arrays["voxel_size"])],
            "origin_xyz": [float(value) for value in np.asarray(arrays["origin"])],
            "target_voxel_size": float(np.asarray(arrays["target_voxel_size"])),
            "native_shape_zyx": [int(value) for value in np.asarray(arrays["native_shape_zyx"])],
            "even_input_shape_zyx": [
                int(value) for value in np.asarray(arrays["even_input_shape_zyx"])
            ],
            "resample_mode": str(np.asarray(arrays["resample_mode"]).item()),
            "contour_scale_to_canonical": float(
                np.asarray(arrays["contour_scale_to_canonical"])
            ),
            "contour_native": (
                float(np.asarray(arrays["contour_native"]))
                if bool(np.asarray(arrays["contour_present"]))
                else None
            ),
            "contour_canonical": (
                float(np.asarray(arrays["contour_canonical"]))
                if bool(np.asarray(arrays["contour_present"]))
                else None
            ),
            "source_map_sha256": str(np.asarray(arrays["source_map_sha256"]).item()),
            "source_meta_sha256": str(np.asarray(arrays["source_meta_sha256"]).item()),
            "algorithm": str(np.asarray(arrays["mrc_algorithm"]).item()),
            "mrc_vendor_sha256": str(np.asarray(arrays["mrc_vendor_sha256"]).item()),
        }
    )
