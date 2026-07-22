"""生成并验证与实验图对齐的模拟密度图。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import numpy as np

from adaligand_preprocessing.artifacts.failures import KnownFailureCode, KnownSampleFailure
from adaligand_preprocessing.artifacts.validation import (
    density_artifact_errors,
    density_pair_errors,
)
from adaligand_preprocessing.external_tools.model_cif import write_normalized_model_cif
from adaligand_preprocessing.geometry.mrc import (
    MapGrid,
    load_map,
    write_canonical_mrc,
)
from adaligand_preprocessing.stages.stage_c.contracts import (
    CArtifactState,
    inspect_stage_c,
    load_npz_arrays,
)
from adaligand_preprocessing.stages.stage_e.common import (
    MRC_GENERATED_ORIGIN_MODE,
    SIM_SCHEMA_VERSION,
    ensure_model_map_frame_compatible,
)
from adaligand_preprocessing.stages.stage_e.experimental import experimental_density_identity
from adaligand_preprocessing.utils.hashing import sha256_file, sha256_named_values
from adaligand_preprocessing.utils.io import atomic_save_npz

if TYPE_CHECKING:
    from adaligand_preprocessing.external_tools.chimera import ChimeraRunner

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
