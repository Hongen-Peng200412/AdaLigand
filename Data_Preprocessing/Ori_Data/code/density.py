"""Stage E 的实验图、recommended contour 与稀疏 ligand-area 纯逻辑。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from rdkit import Chem

from chimera import ChimeraRunner
from contracts import CArtifactState, inspect_stage_c, load_npz_arrays
from failures import KnownFailureCode, KnownSampleFailure
from io_utils import (
    atomic_save_npz,
    safe_object_filename,
    sha256_file,
    sha256_manifest,
    sha256_named_values,
)
from model_cif import write_normalized_model_cif
from mrc import (
    POCKET_MRC_ALGORITHM,
    POCKET_MRC_ANCESTOR_SHA256,
    POCKET_MRC_VENDOR_SHA256,
    POCKET_RESAMPLE_ALL_DIFF,
    POCKET_RESAMPLE_ALL_EQUAL,
    POCKET_RESAMPLE_MIXED_COMPAT,
    MapGrid,
    canonicalization_info,
    load_map,
    make_canonical_grid,
    write_canonical_mrc,
)
from qc import (
    MODEL_MAP_FRAME_ATOL_ANGSTROM,
    density_artifact_errors,
    density_pair_errors,
    model_map_frame_errors,
)


EXP_SCHEMA_VERSION = 2
LIGAND_AREA_SCHEMA_VERSION = 2
SIM_SCHEMA_VERSION = 2
MRC_TARGET_VOXEL_SIZE = 1.0
MRC_SOURCE_ORIGIN_MODE = "pocket_plus_multiply_global_origin_true"
MRC_GENERATED_ORIGIN_MODE = "header_origin_angstrom_nstart_zero"
VDW_RADIUS_OVERRIDES = {
    6: 1.70,   # C
    7: 1.55,   # N
    8: 1.52,   # O
    15: 1.80,  # P
    16: 1.80,  # S
}
VDW_RADIUS_SOURCE = "plan_locked_C_N_O_P_S;RDKit_PeriodicTable_GetRvdw_fallback"
_PERIODIC_TABLE = Chem.GetPeriodicTable()


def ensure_model_map_frame_compatible(
    pdb_id: str,
    map_arrays: dict[str, np.ndarray],
    model_coords: np.ndarray,
) -> None:
    """
    在外部工具运行前对 E/F 共享的 model-map 世界坐标契约分类。

    输入参数:
        - pdb_id: str, 小写 PDB id，用于稳定失败详情
        - map_arrays: dict[str,np.ndarray], E1 canonical 密度图数组，``grid`` 为 ``(1,Z,Y,X)``
        - model_coords: np.ndarray, ``(N,3) float32``，Stage C polymer receptor token 世界 XYZ 坐标

    输出:
        - None: 包围盒相交时正常返回

    异常:
        - KnownSampleFailure: 仅当合法输入的两个包围盒完全分离，失败码为 ``model_map_frame_mismatch``
        - RuntimeError: 坐标或网格本身不满足契约，不得降级为 known failure
    """
    frame_errors = model_map_frame_errors(map_arrays, model_coords)
    if not frame_errors:
        return
    if frame_errors != ["density_pair:receptor_outside_grid"]:
        raise RuntimeError(f"model-map frame input contract failed for {pdb_id}: {frame_errors}")

    grid = np.asarray(map_arrays["grid"])
    voxel = np.asarray(map_arrays["voxel_size"], dtype=np.float64)
    map_lower = np.asarray(map_arrays["origin"], dtype=np.float64)
    map_upper = map_lower + (np.asarray(grid.shape[:0:-1], dtype=np.float64) - 1.0) * voxel
    coords = np.asarray(model_coords, dtype=np.float64)
    detail = {
        "atol_angstrom": MODEL_MAP_FRAME_ATOL_ANGSTROM,
        "grid_shape_order": "ZYX",
        "map_lower_xyz": map_lower.tolist(),
        "map_upper_xyz": map_upper.tolist(),
        "model_lower_xyz": coords.min(axis=0).tolist(),
        "model_upper_xyz": coords.max(axis=0).tolist(),
        "pdb_id": pdb_id.lower(),
        "policy": "no_transform_or_fitmap",
        "world_axis_order": "XYZ",
    }
    raise KnownSampleFailure(
        KnownFailureCode.MODEL_MAP_FRAME_MISMATCH,
        json.dumps(detail, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )


@dataclass(frozen=True)
class ContourInfo:
    """EMDB 主图 recommended contour 的值和可审计来源。"""

    value: float | None
    status: str
    path: str
    source: str | None


def extract_recommended_contour(metadata: dict[str, Any]) -> ContourInfo:
    """
    只从 EMDB 主图路径选择唯一 ``primary=true`` 的有限 contour level。

    输入参数:
        - metadata: dict, Stage B 保存的 EMDB ``/entry/{id}`` 原始 JSON

    输出:
        - info: ContourInfo, 缺失/歧义时 ``value=None``，并保留稳定 status

    不递归搜索 ``interpretation.additional_map_list``，防止把附加图 contour 误当主图。
    ``source`` 可缺失；它不影响有效 level。
    """
    map_section = metadata.get("map")
    if not isinstance(map_section, dict):
        return ContourInfo(None, "missing_map_section", "map", None)
    contour_list = map_section.get("contour_list")
    if not isinstance(contour_list, dict) or "contour" not in contour_list:
        return ContourInfo(None, "missing_contour_list", "map.contour_list.contour", None)
    raw_contours = contour_list["contour"]
    if isinstance(raw_contours, dict):
        contours = [raw_contours]
    elif isinstance(raw_contours, list):
        contours = raw_contours
    else:
        return ContourInfo(None, "invalid_contour_container", "map.contour_list.contour", None)

    primary = [
        (index, item)
        for index, item in enumerate(contours)
        if isinstance(item, dict) and _metadata_bool(item.get("primary"))
    ]
    if len(primary) == 0:
        return ContourInfo(None, "missing_primary_contour", "map.contour_list.contour", None)
    if len(primary) > 1:
        return ContourInfo(None, "ambiguous_primary_contour", "map.contour_list.contour", None)
    index, item = primary[0]
    path = f"map.contour_list.contour[{index}].level"
    try:
        level = float(item.get("level"))
    except (TypeError, ValueError):
        return ContourInfo(None, "invalid_primary_level", path, _optional_text(item.get("source")))
    if not np.isfinite(level):
        return ContourInfo(None, "nonfinite_primary_level", path, _optional_text(item.get("source")))
    return ContourInfo(level, "ok", path, _optional_text(item.get("source")))


def vdw_radius(atomic_number: int) -> float:
    """
    返回逐元素范德华半径 Å。

    C/N/O/P/S 使用计划锁定值；其他有效元素调用 RDKit 周期表，不使用单一默认常数。
    """
    if atomic_number in VDW_RADIUS_OVERRIDES:
        return VDW_RADIUS_OVERRIDES[atomic_number]
    if atomic_number <= 0 or atomic_number > 118:
        raise ValueError(f"unsupported atomic number for vdW radius: {atomic_number}")
    radius = float(_PERIODIC_TABLE.GetRvdw(int(atomic_number)))
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError(f"RDKit has no valid vdW radius for atomic number {atomic_number}")
    return radius


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


def simulated_density_errors(
    arrays: dict[str, np.ndarray],
    *,
    exp_arrays: dict[str, np.ndarray],
    receptor_coords: np.ndarray,
    resolution: float,
    source_exp_size: int,
    source_exp_mtime_ns: int,
    source_cif_size: int,
    source_cif_mtime_ns: int,
) -> list[str]:
    """验证 E2 同网格内容、严格 receptor-only provenance 与输入快速指纹。"""
    errors = density_pair_errors(exp_arrays, arrays, receptor_coords)
    required = {
        "schema_version",
        "resolution",
        "chimera_version",
        "source_exp_identity_sha256",
        "source_cif_sha256",
        "normalized_model_sha256",
        "chimera_script_sha256",
        "source_exp_size",
        "source_exp_mtime_ns",
        "source_cif_size",
        "source_cif_mtime_ns",
        "strict_hetatm_removed",
        "model_selection",
        "generated_mrc_origin_mode",
    }
    for key in sorted(required.difference(arrays)):
        errors.append(f"sim_missing:{key}")
    if required.difference(arrays):
        return errors
    schema = np.asarray(arrays["schema_version"])
    if schema.shape != () or int(schema) != SIM_SCHEMA_VERSION:
        errors.append("sim_contract:schema_version")
    stored_resolution = np.asarray(arrays["resolution"])
    if stored_resolution.dtype != np.float32 or stored_resolution.shape != () or not np.isclose(
        float(stored_resolution),
        resolution,
        rtol=0,
        atol=1e-6,
    ):
        errors.append("sim_provenance:resolution")
    strict_removed = np.asarray(arrays["strict_hetatm_removed"])
    if strict_removed.dtype != np.dtype(bool) or strict_removed.shape != () or not bool(strict_removed):
        errors.append("sim_contract:strict_hetatm_removed")
    if str(np.asarray(arrays["model_selection"]).item()) != (
        "first_model_stage_c_altloc_heavy_group_PDB_ATOM"
    ):
        errors.append("sim_contract:model_selection")
    if str(np.asarray(arrays["generated_mrc_origin_mode"]).item()) != MRC_GENERATED_ORIGIN_MODE:
        errors.append("sim_contract:generated_mrc_origin_mode")
    expected_stats = {
        "source_exp_size": source_exp_size,
        "source_exp_mtime_ns": source_exp_mtime_ns,
        "source_cif_size": source_cif_size,
        "source_cif_mtime_ns": source_cif_mtime_ns,
    }
    for key, expected in expected_stats.items():
        value = np.asarray(arrays[key])
        if value.shape != () or int(value) != expected:
            errors.append(f"sim_provenance:{key}")
    for key in (
        "source_exp_identity_sha256",
        "source_cif_sha256",
        "normalized_model_sha256",
        "chimera_script_sha256",
    ):
        if len(str(np.asarray(arrays[key]).item())) != 64:
            errors.append(f"sim_provenance:{key}")
    try:
        expected_exp_identity = experimental_density_identity(exp_arrays)
    except (KeyError, TypeError, ValueError):
        errors.append("sim_provenance:source_exp_identity_unverifiable")
    else:
        stored_exp_identity = str(np.asarray(arrays["source_exp_identity_sha256"]).item())
        if stored_exp_identity != expected_exp_identity:
            errors.append("sim_provenance:source_exp_identity_mismatch")
    if not str(np.asarray(arrays["chimera_version"]).item()).strip():
        errors.append("sim_provenance:chimera_version")
    return errors


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


def build_simulated_density(
    root: Path,
    record: dict[str, Any],
    *,
    runner: ChimeraRunner,
    chimera_version: str,
    run_id: str,
    scratch_root: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    用严格 ATOM-only 标准模型和 Chimera ``molmap onGrid`` 幂等生成 E2。

    成功提升 ``sim.npz`` 后删除本次 scratch 中两个大型 MRC，仅保留标准模型、脚本和日志。
    """
    pdb_id = str(record["pdb_id"]).lower()
    resolution_value = record.get("resolution")
    try:
        resolution = float(resolution_value)
    except (TypeError, ValueError) as exc:
        raise KnownSampleFailure(
            KnownFailureCode.MISSING_RESOLUTION,
            f"pair_list resolution is missing for {pdb_id}",
        ) from exc
    if not np.isfinite(resolution) or resolution <= 0:
        raise KnownSampleFailure(
            KnownFailureCode.MISSING_RESOLUTION,
            f"pair_list resolution is invalid for {pdb_id}: {resolution_value!r}",
        )

    inspection = inspect_stage_c(root, pdb_id)
    if inspection.state is not CArtifactState.COMPLETE:
        raise RuntimeError(
            f"Stage C is not release-ready for {pdb_id}: "
            f"{inspection.state.value}: {inspection.reasons}"
        )
    exp_path = root / "density" / pdb_id / "exp.npz"
    cif_path = root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif"
    if not cif_path.exists():
        raise RuntimeError(f"source mmCIF is missing after Stage B gate: {cif_path}")
    exp = load_npz_arrays(exp_path, allow_pickle=False)
    exp_errors = density_artifact_errors(exp, require_unit_voxel=False)
    if exp_errors:
        raise RuntimeError(f"Stage E1 is not valid for {pdb_id}: {exp_errors}")
    receptor_path = root / "parse" / pdb_id / "receptor_tokens.npz"
    receptor = load_npz_arrays(receptor_path, allow_pickle=False)["coords"]
    ensure_model_map_frame_compatible(pdb_id, exp, receptor)
    exp_stat = exp_path.stat()
    cif_stat = cif_path.stat()
    output_path = root / "density" / pdb_id / "sim.npz"
    if output_path.exists() and not overwrite:
        try:
            existing = load_npz_arrays(output_path, allow_pickle=False)
            errors = simulated_density_errors(
                existing,
                exp_arrays=exp,
                receptor_coords=receptor,
                resolution=resolution,
                source_exp_size=exp_stat.st_size,
                source_exp_mtime_ns=exp_stat.st_mtime_ns,
                source_cif_size=cif_stat.st_size,
                source_cif_mtime_ns=cif_stat.st_mtime_ns,
            )
        except (OSError, ValueError, KeyError):
            errors = ["sim_unreadable"]
        if not errors:
            return {
                "status": "skipped",
                "artifact": str(output_path.relative_to(root)),
                "shape_zyx": list(existing["grid"].shape[1:]),
            }

    attempt_id = uuid4().hex
    scratch_dir = scratch_root / run_id / "stage_e" / pdb_id / attempt_id
    scratch_dir.mkdir(parents=True, exist_ok=False)
    normalized_model_path = scratch_dir / "receptor_atom_only.cif"
    model_stats = write_normalized_model_cif(cif_path, normalized_model_path, atom_only=True)
    canonical_mrc_path = scratch_dir / "canonical_exp.mrc"
    write_canonical_mrc(
        canonical_mrc_path,
        MapGrid(
            grid=exp["grid"][0],
            voxel_size=exp["voxel_size"],
            origin=exp["origin"],
        ),
    )
    simulated_mrc_path = scratch_dir / "sim.mrc"
    tool_result = runner.molmap_on_grid(
        normalized_model_path,
        canonical_mrc_path,
        simulated_mrc_path,
        resolution=resolution,
        scratch_dir=scratch_dir,
    )
    simulated = load_map(simulated_mrc_path, multiply_global_origin=False)
    arrays = {
        "grid": simulated.grid[None].astype(np.float32, copy=False),
        "voxel_size": simulated.voxel_size.astype(np.float32, copy=False),
        "origin": simulated.origin.astype(np.float32, copy=False),
        "schema_version": np.asarray(SIM_SCHEMA_VERSION, dtype=np.uint16),
        "resolution": np.asarray(resolution, dtype=np.float32),
        "resolution_info_json": np.asarray(
            json.dumps(record.get("resolution_info", {}), ensure_ascii=False, sort_keys=True)
        ),
        "chimera_version": np.asarray(chimera_version),
        "source_exp_identity_sha256": np.asarray(experimental_density_identity(exp)),
        "source_cif_sha256": np.asarray(sha256_file(cif_path)),
        "normalized_model_sha256": np.asarray(sha256_file(normalized_model_path)),
        "chimera_script_sha256": np.asarray(sha256_file(scratch_dir / "molmap.py")),
        "source_exp_size": np.asarray(exp_stat.st_size, dtype=np.int64),
        "source_exp_mtime_ns": np.asarray(exp_stat.st_mtime_ns, dtype=np.int64),
        "source_cif_size": np.asarray(cif_stat.st_size, dtype=np.int64),
        "source_cif_mtime_ns": np.asarray(cif_stat.st_mtime_ns, dtype=np.int64),
        "strict_hetatm_removed": np.asarray(True, dtype=bool),
        "model_selection": np.asarray("first_model_stage_c_altloc_heavy_group_PDB_ATOM"),
        "generated_mrc_origin_mode": np.asarray(MRC_GENERATED_ORIGIN_MODE),
        "normalized_model_n_atoms": np.asarray(model_stats["n_atoms"], dtype=np.int32),
        "tool_elapsed_seconds": np.asarray(tool_result.elapsed_seconds, dtype=np.float32),
        "tool_stdout": np.asarray(str(tool_result.stdout_path.relative_to(scratch_root))),
        "tool_stderr": np.asarray(str(tool_result.stderr_path.relative_to(scratch_root))),
    }
    errors = simulated_density_errors(
        arrays,
        exp_arrays=exp,
        receptor_coords=receptor,
        resolution=resolution,
        source_exp_size=exp_stat.st_size,
        source_exp_mtime_ns=exp_stat.st_mtime_ns,
        source_cif_size=cif_stat.st_size,
        source_cif_mtime_ns=cif_stat.st_mtime_ns,
    )
    if errors:
        raise RuntimeError(f"Stage E2 contract failed for {pdb_id}: {errors}")
    atomic_save_npz(output_path, **arrays)
    # 仅删除本次 attempt 内由本函数创建、且正式 artifact 已原子提升的大文件。
    canonical_mrc_path.unlink(missing_ok=True)
    simulated_mrc_path.unlink(missing_ok=True)
    return {
        "status": "success",
        "artifact": str(output_path.relative_to(root)),
        "shape_zyx": list(simulated.grid.shape),
        "scratch": str(scratch_dir.relative_to(scratch_root)),
    }


def build_ligand_area_arrays(
    grid_shape_zyx: tuple[int, int, int],
    voxel_size_xyz: np.ndarray,
    origin_xyz: np.ndarray,
    ligand_coords_by_candidate: dict[int, np.ndarray],
    atomic_numbers_by_candidate: dict[int, np.ndarray],
) -> dict[str, np.ndarray]:
    """
    用逐原子局部 voxel stencil 生成稀疏 occurrence mask 和全局 union。

    ``mask_{cid}`` 是唯一、字典序排序的 ``(K,3) int32`` ZYX 索引；
    ``centroid_voxel_{cid}`` 虽沿用既定字段名，数值是 mask 体素中心的世界 XYZ Å。
    """
    shape = tuple(int(value) for value in grid_shape_zyx)
    if len(shape) != 3 or any(value <= 1 for value in shape):
        raise ValueError("grid_shape_zyx must contain three dimensions > 1")
    voxel = np.asarray(voxel_size_xyz, dtype=np.float64)
    origin = np.asarray(origin_xyz, dtype=np.float64)
    if voxel.shape != (3,) or origin.shape != (3,) or np.any(voxel <= 0):
        raise ValueError("voxel_size_xyz/origin_xyz must be valid XYZ vectors")
    if set(ligand_coords_by_candidate) != set(atomic_numbers_by_candidate):
        raise ValueError("coordinate and element candidate ids differ")

    union_flat = np.zeros((int(np.prod(shape)),), dtype=bool)
    arrays: dict[str, np.ndarray] = {}
    for candidate_id in sorted(ligand_coords_by_candidate):
        coords = np.asarray(ligand_coords_by_candidate[candidate_id], dtype=np.float64)
        atomic_numbers = np.asarray(atomic_numbers_by_candidate[candidate_id])
        if coords.ndim != 2 or coords.shape[1:] != (3,) or not np.isfinite(coords).all():
            raise ValueError(f"candidate {candidate_id} coords must be finite (M,3)")
        if atomic_numbers.ndim != 1 or len(atomic_numbers) != len(coords):
            raise ValueError(f"candidate {candidate_id} atomic numbers do not align")

        chunks: list[np.ndarray] = []
        for coord, atomic_number in zip(coords, atomic_numbers, strict=True):
            radius = vdw_radius(int(atomic_number))
            lower_xyz = np.floor((coord - radius - origin) / voxel).astype(np.int64)
            upper_xyz = np.ceil((coord + radius - origin) / voxel).astype(np.int64)
            lower_xyz = np.maximum(lower_xyz, 0)
            upper_xyz = np.minimum(upper_xyz, np.asarray(shape[::-1]) - 1)
            if np.any(lower_xyz > upper_xyz):
                continue
            x_indices = np.arange(lower_xyz[0], upper_xyz[0] + 1, dtype=np.int64)
            y_indices = np.arange(lower_xyz[1], upper_xyz[1] + 1, dtype=np.int64)
            z_indices = np.arange(lower_xyz[2], upper_xyz[2] + 1, dtype=np.int64)
            dx2 = (origin[0] + x_indices * voxel[0] - coord[0]) ** 2
            dy2 = (origin[1] + y_indices * voxel[1] - coord[1]) ** 2
            dz2 = (origin[2] + z_indices * voxel[2] - coord[2]) ** 2
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
        centroid_xyz = origin + np.asarray(
            [x_index.mean(), y_index.mean(), z_index.mean()],
            dtype=np.float64,
        ) * voxel
        arrays[f"mask_{candidate_id}"] = mask_indices
        arrays[f"centroid_voxel_{candidate_id}"] = centroid_xyz.astype(np.float32)
        union_flat[linear_indices] = True
    arrays["union_mask"] = union_flat.reshape(shape)[None]
    return arrays


def ligand_area_errors(
    arrays: dict[str, np.ndarray],
    *,
    grid_shape_zyx: tuple[int, int, int],
    voxel_size_xyz: np.ndarray,
    origin_xyz: np.ndarray,
    candidate_ids: list[int],
) -> list[str]:
    """验证 E3 稀疏 mask、世界质心和 union 的精确一致性。"""
    errors: list[str] = []
    shape = tuple(int(value) for value in grid_shape_zyx)
    union = arrays.get("union_mask")
    if union is None or union.dtype != np.dtype(bool) or union.shape != (1, *shape):
        return ["ligand_area_contract:union_mask"]
    reconstructed = np.zeros(shape, dtype=bool)
    origin = np.asarray(origin_xyz, dtype=np.float64)
    voxel = np.asarray(voxel_size_xyz, dtype=np.float64)
    for candidate_id in candidate_ids:
        mask_key = f"mask_{candidate_id}"
        centroid_key = f"centroid_voxel_{candidate_id}"
        if mask_key not in arrays or centroid_key not in arrays:
            errors.append(f"ligand_area_missing:{candidate_id}")
            continue
        indices = np.asarray(arrays[mask_key])
        centroid = np.asarray(arrays[centroid_key])
        if indices.dtype != np.int32 or indices.ndim != 2 or indices.shape[1:] != (3,) or len(indices) == 0:
            errors.append(f"ligand_area_contract:mask:{candidate_id}")
            continue
        if np.any(indices < 0) or np.any(indices >= np.asarray(shape, dtype=np.int32)):
            errors.append(f"ligand_area_value:mask_range:{candidate_id}")
            continue
        linear = np.ravel_multi_index(indices.T, shape)
        if len(np.unique(linear)) != len(linear) or np.any(np.diff(linear) <= 0):
            errors.append(f"ligand_area_value:mask_order:{candidate_id}")
        reconstructed[tuple(indices.T)] = True
        expected_centroid = origin + np.asarray(
            [indices[:, 2].mean(), indices[:, 1].mean(), indices[:, 0].mean()]
        ) * voxel
        expected_centroid_f32 = expected_centroid.astype(np.float32)
        if (
            centroid.dtype != np.float32
            or centroid.shape != (3,)
            or not np.array_equal(centroid, expected_centroid_f32)
        ):
            errors.append(f"ligand_area_value:centroid:{candidate_id}")
    if not np.array_equal(union[0], reconstructed):
        errors.append("ligand_area_value:union")
    return errors


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

    parse_dir = root / "parse" / normalized_id
    occurrence_path = parse_dir / "occurrences.jsonl"
    coords_path = parse_dir / "ligand_coords.npz"
    coords_arrays = load_npz_arrays(coords_path, allow_pickle=False)
    coords_by_candidate: dict[int, np.ndarray] = {}
    elements_by_candidate: dict[int, np.ndarray] = {}
    object_paths: list[Path] = []
    candidate_ids: list[int] = []
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        candidate_ids.append(candidate_id)
        coords = coords_arrays[f"coords_{candidate_id}"]
        present = coords_arrays[f"present_{candidate_id}"]
        object_path = root / "ligand_objects" / f"{safe_object_filename(str(occurrence['object_key']))}.npz"
        object_paths.append(object_path)
        with np.load(object_path, allow_pickle=True) as ligand_object:
            atomic_numbers = ligand_object["atoms"]["element"].astype(np.int16, copy=True)
        if len(atomic_numbers) != len(coords):
            raise RuntimeError(f"LigandObject row mismatch for candidate {candidate_id}")
        coords_by_candidate[candidate_id] = coords[present]
        elements_by_candidate[candidate_id] = atomic_numbers[present]

    small_source_manifest = sha256_manifest(
        [occurrence_path, coords_path, *sorted(set(object_paths))],
        base=root,
    )
    source_manifest = sha256_named_values(
        {
            "exp_identity_sha256": experimental_density_identity(exp),
            "small_source_manifest_sha256": small_source_manifest,
        }
    )
    output_path = root / "density" / normalized_id / "ligand_area.npz"
    if output_path.exists() and not overwrite:
        try:
            existing = load_npz_arrays(output_path, allow_pickle=False)
            errors = ligand_area_errors(
                existing,
                grid_shape_zyx=tuple(int(value) for value in exp["grid"].shape[1:]),
                voxel_size_xyz=exp["voxel_size"],
                origin_xyz=exp["origin"],
                candidate_ids=candidate_ids,
            )
            if str(existing["source_manifest_sha256"].item()) != source_manifest:
                errors.append("ligand_area_provenance:source_manifest")
            if int(existing["schema_version"]) != LIGAND_AREA_SCHEMA_VERSION:
                errors.append("ligand_area_contract:schema_version")
        except (OSError, ValueError, KeyError):
            errors = ["ligand_area_unreadable"]
        if not errors:
            return {
                "status": "skipped",
                "artifact": str(output_path.relative_to(root)),
                "n_occurrences": len(candidate_ids),
            }

    arrays = build_ligand_area_arrays(
        tuple(int(value) for value in exp["grid"].shape[1:]),
        exp["voxel_size"],
        exp["origin"],
        coords_by_candidate,
        elements_by_candidate,
    )
    arrays.update(
        {
            "schema_version": np.asarray(LIGAND_AREA_SCHEMA_VERSION, dtype=np.uint16),
            "source_manifest_sha256": np.asarray(source_manifest),
            "centroid_coordinate_system": np.asarray("world_xyz_angstrom"),
            "mask_index_order": np.asarray("zyx"),
            "vdw_radius_source": np.asarray(VDW_RADIUS_SOURCE),
        }
    )
    errors = ligand_area_errors(
        arrays,
        grid_shape_zyx=tuple(int(value) for value in exp["grid"].shape[1:]),
        voxel_size_xyz=exp["voxel_size"],
        origin_xyz=exp["origin"],
        candidate_ids=candidate_ids,
    )
    if errors:
        raise RuntimeError(f"Stage E3 contract failed for {normalized_id}: {errors}")
    atomic_save_npz(output_path, **arrays)
    return {
        "status": "success",
        "artifact": str(output_path.relative_to(root)),
        "n_occurrences": len(candidate_ids),
        "n_union_voxels": int(np.count_nonzero(arrays["union_mask"])),
    }


def _metadata_bool(value: Any) -> bool:
    """严格解析 EMDB metadata 的布尔表示。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value) == 1
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


def _optional_text(value: Any) -> str | None:
    """把 metadata 可选文本规范为 ``str | None``。"""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
