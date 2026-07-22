# Stage D 的原子结合标签计算与落盘。
# 主要输入：Stage C 的 receptor_tokens 与 occurrence ligand 坐标（XYZ Å）。
# 主要输出：受体原子标签及分片级 Stage D 终态/报告。
# 关键边界：以 4 Å 最近配体重原子距离定义标签，数组通常按受体原子排列。
"""Stage D：从受体和 occurrence 真值坐标生成原子级结合标签。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from adaligand_preprocessing.stages.stage_c.contracts import CArtifactState, inspect_stage_c, load_npz_arrays
from adaligand_preprocessing.artifacts.failures import KnownFailureCode, KnownSampleFailure
from adaligand_preprocessing.utils.io import atomic_save_npz, read_jsonl, sha256_file


ATOM_LABEL_SCHEMA_VERSION = 1


def compute_atom_labels(
    receptor_coords: np.ndarray,
    ligand_coords_by_candidate: Mapping[int, np.ndarray],
    binding_threshold: float,
) -> dict[str, np.ndarray]:
    """
    计算最近配体距离、4 Å 结合标签和独占 occurrence id。

    输入参数:
        - receptor_coords: np.ndarray, ``(N,3) float32`` 受体世界坐标 XYZ
        - ligand_coords_by_candidate: Mapping[int,np.ndarray], 每个 candidate 的 present 坐标
        - binding_threshold: float, Å；正式默认 4.0

    输出:
        - arrays: dict[str,np.ndarray], ``binding_atom/instance_id/nearest_dist``

    说明:
        多个 ligand 原子到同一受体原子等距时，先按 candidate_id、再按拼接行号稳定决胜。
        ``instance_id`` 只对 binding atom 有值，背景固定为 ``-1``。
    """
    receptor = np.asarray(receptor_coords)
    if receptor.dtype != np.float32 or receptor.ndim != 2 or receptor.shape[1:] != (3,):
        raise ValueError("receptor_coords must be (N,3) float32")
    if len(receptor) == 0 or not np.isfinite(receptor).all():
        raise ValueError("receptor_coords must be non-empty and finite")
    if not np.isfinite(binding_threshold) or binding_threshold <= 0:
        raise ValueError("binding_threshold must be positive and finite")

    coord_parts: list[np.ndarray] = []
    candidate_parts: list[np.ndarray] = []
    for candidate_id in sorted(ligand_coords_by_candidate):
        if not isinstance(candidate_id, int) or candidate_id < 0:
            raise ValueError("candidate_id must be a non-negative int")
        coords = np.asarray(ligand_coords_by_candidate[candidate_id])
        if coords.ndim != 2 or coords.shape[1:] != (3,) or not np.isfinite(coords).all():
            raise ValueError(f"candidate {candidate_id} coords must be finite (M,3)")
        if len(coords) == 0:
            continue
        coord_parts.append(coords.astype(np.float64, copy=False))
        candidate_parts.append(np.full((len(coords),), candidate_id, dtype=np.int32))
    if not coord_parts:
        raise KnownSampleFailure(
            KnownFailureCode.NO_PRESENT_LIGAND_ATOMS,
            "Stage C has no present ligand atom coordinates",
        )

    ligand_coords = np.concatenate(coord_parts, axis=0)
    ligand_candidate_ids = np.concatenate(candidate_parts, axis=0)
    tree = cKDTree(ligand_coords)
    receptor64 = receptor.astype(np.float64, copy=False)
    if len(ligand_coords) == 1:
        nearest_distance, nearest_index = tree.query(receptor64, k=1)
        nearest_distance = np.asarray(nearest_distance, dtype=np.float64)
        nearest_index = np.asarray(nearest_index, dtype=np.int64)
    else:
        two_distances, two_indices = tree.query(receptor64, k=2)
        nearest_distance = np.asarray(two_distances[:, 0], dtype=np.float64)
        nearest_index = np.asarray(two_indices[:, 0], dtype=np.int64)
        tie_rows = np.flatnonzero(
            np.isclose(two_distances[:, 0], two_distances[:, 1], rtol=0, atol=1e-7)
        )
        for row in tie_rows:
            radius = np.nextafter(float(two_distances[row, 0]) + 1e-7, np.inf)
            candidates = np.asarray(tree.query_ball_point(receptor64[row], radius), dtype=np.int64)
            distances = np.linalg.norm(ligand_coords[candidates] - receptor64[row], axis=1)
            minimum = float(distances.min())
            tied = candidates[np.isclose(distances, minimum, rtol=0, atol=1e-7)]
            chosen = min(tied.tolist(), key=lambda index: (int(ligand_candidate_ids[index]), index))
            nearest_index[row] = chosen
            nearest_distance[row] = np.linalg.norm(ligand_coords[chosen] - receptor64[row])

    threshold32 = np.float32(binding_threshold)
    nearest_dist = nearest_distance.astype(np.float32)
    binding_atom = nearest_dist <= threshold32
    instance_id = np.full((len(receptor),), -1, dtype=np.int32)
    instance_id[binding_atom] = ligand_candidate_ids[nearest_index[binding_atom]]
    return {
        "binding_atom": binding_atom.astype(bool, copy=False),
        "instance_id": instance_id,
        "nearest_dist": nearest_dist,
    }


def atom_label_errors(
    arrays: Mapping[str, np.ndarray],
    *,
    n_receptor_atoms: int,
    candidate_ids: set[int],
    binding_threshold: float,
    source_receptor_sha256: str,
    source_ligand_coords_sha256: str,
) -> list[str]:
    """验证 Stage D artifact 的 schema、数值关系和输入 provenance。"""
    required = {
        "binding_atom",
        "instance_id",
        "nearest_dist",
        "binding_threshold",
        "schema_version",
        "source_receptor_sha256",
        "source_ligand_coords_sha256",
    }
    missing = required.difference(arrays)
    if missing:
        return [f"atom_labels_missing:{key}" for key in sorted(missing)]

    errors: list[str] = []
    binding = np.asarray(arrays["binding_atom"])
    instance = np.asarray(arrays["instance_id"])
    distance = np.asarray(arrays["nearest_dist"])
    if binding.dtype != np.dtype(bool) or binding.shape != (n_receptor_atoms,):
        errors.append("atom_labels_contract:binding_atom")
    if instance.dtype != np.int32 or instance.shape != (n_receptor_atoms,):
        errors.append("atom_labels_contract:instance_id")
    if distance.dtype != np.float32 or distance.shape != (n_receptor_atoms,):
        errors.append("atom_labels_contract:nearest_dist")
    elif not np.isfinite(distance).all() or np.any(distance < 0):
        errors.append("atom_labels_value:nearest_dist")

    stored_threshold = np.asarray(arrays["binding_threshold"])
    if stored_threshold.dtype != np.float32 or stored_threshold.shape != () or not np.isclose(
        float(stored_threshold),
        binding_threshold,
        rtol=0,
        atol=1e-6,
    ):
        errors.append("atom_labels_provenance:binding_threshold")
    schema_version = np.asarray(arrays["schema_version"])
    if schema_version.shape != () or int(schema_version) != ATOM_LABEL_SCHEMA_VERSION:
        errors.append("atom_labels_contract:schema_version")
    if str(np.asarray(arrays["source_receptor_sha256"]).item()) != source_receptor_sha256:
        errors.append("atom_labels_provenance:receptor")
    if str(np.asarray(arrays["source_ligand_coords_sha256"]).item()) != source_ligand_coords_sha256:
        errors.append("atom_labels_provenance:ligand_coords")

    if not errors or all("provenance" in error or "schema_version" in error for error in errors):
        if binding.shape == instance.shape == distance.shape == (n_receptor_atoms,):
            expected_binding = distance <= np.float32(binding_threshold)
            if not np.array_equal(binding, expected_binding):
                errors.append("atom_labels_value:binding_threshold_relation")
            if np.any(instance[~binding] != -1):
                errors.append("atom_labels_value:background_instance")
            if np.any(instance[binding] < 0) or any(
                int(value) not in candidate_ids for value in np.unique(instance[binding])
            ):
                errors.append("atom_labels_value:binding_instance")
    return errors


def build_atom_labels(
    root: Path,
    pdb_id: str,
    *,
    binding_threshold: float = 4.0,
    overwrite: bool = False,
) -> dict[str, Any]:
    """
    读取已验收 Stage C 产物并幂等生成一个 PDB 的 Stage D 标签。

    返回字典只含状态与统计；run-scoped 报告由 CLI 编排层统一落盘。
    """
    normalized_id = pdb_id.lower()
    inspection = inspect_stage_c(root, normalized_id)
    if inspection.state is not CArtifactState.COMPLETE:
        raise RuntimeError(
            f"Stage C is not release-ready for {normalized_id}: "
            f"{inspection.state.value}: {inspection.reasons}"
        )
    occurrences = list(inspection.occurrences)
    if not occurrences:
        raise KnownSampleFailure(
            KnownFailureCode.NO_OCCURRENCES,
            "Stage C produced no eligible ligand occurrence",
        )

    parse_dir = root / "parse" / normalized_id
    receptor_path = parse_dir / "receptor_tokens.npz"
    ligand_coords_path = parse_dir / "ligand_coords.npz"
    receptor_arrays = load_npz_arrays(receptor_path, allow_pickle=False)
    coords_arrays = load_npz_arrays(ligand_coords_path, allow_pickle=False)
    receptor_coords = receptor_arrays["coords"]
    ligand_coords_by_candidate: dict[int, np.ndarray] = {}
    candidate_ids: set[int] = set()
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        candidate_ids.add(candidate_id)
        coords = coords_arrays[f"coords_{candidate_id}"]
        present = coords_arrays[f"present_{candidate_id}"]
        ligand_coords_by_candidate[candidate_id] = coords[present]

    receptor_hash = sha256_file(receptor_path)
    ligand_coords_hash = sha256_file(ligand_coords_path)
    output_path = root / "labels" / normalized_id / "atom_labels.npz"
    if output_path.exists() and not overwrite:
        try:
            existing = load_npz_arrays(output_path, allow_pickle=False)
            errors = atom_label_errors(
                existing,
                n_receptor_atoms=len(receptor_coords),
                candidate_ids=candidate_ids,
                binding_threshold=binding_threshold,
                source_receptor_sha256=receptor_hash,
                source_ligand_coords_sha256=ligand_coords_hash,
            )
        except (OSError, ValueError, KeyError):
            errors = ["atom_labels_unreadable"]
        if not errors:
            return {
                "status": "skipped",
                "artifact": str(output_path.relative_to(root)),
                "n_receptor_atoms": len(receptor_coords),
            }

    arrays = compute_atom_labels(receptor_coords, ligand_coords_by_candidate, binding_threshold)
    arrays.update(
        {
            "binding_threshold": np.asarray(binding_threshold, dtype=np.float32),
            "schema_version": np.asarray(ATOM_LABEL_SCHEMA_VERSION, dtype=np.uint16),
            "source_receptor_sha256": np.asarray(receptor_hash),
            "source_ligand_coords_sha256": np.asarray(ligand_coords_hash),
        }
    )
    errors = atom_label_errors(
        arrays,
        n_receptor_atoms=len(receptor_coords),
        candidate_ids=candidate_ids,
        binding_threshold=binding_threshold,
        source_receptor_sha256=receptor_hash,
        source_ligand_coords_sha256=ligand_coords_hash,
    )
    if errors:
        raise RuntimeError(f"Stage D contract failed for {normalized_id}: {errors}")
    atomic_save_npz(output_path, **arrays)
    return {
        "status": "success",
        "artifact": str(output_path.relative_to(root)),
        "n_receptor_atoms": len(receptor_coords),
        "n_binding_atoms": int(np.count_nonzero(arrays["binding_atom"])),
    }
