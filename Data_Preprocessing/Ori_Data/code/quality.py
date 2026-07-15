# 学习导航：功能分区=核心科学逻辑；生命周期=正式主路径 Stage F。
# 主要输入：实验图、模拟图、ATOM-only/ATOM+HETATM 模型、配体与受体坐标。
# 主要输出：四种 CC、配体逐原子 Q、6 Å occurrence 口袋逐原子 Q、provenance 与终态。
# 关键边界：CC 由 Chimera、Q 由 MapQ 计算；AdaLigand 负责身份对齐、shape/坐标 QC 和空口袋 null/status。
"""Stage F：全模型四种 CC、MapQ 原子严格投影与 occurrence 质量聚合。"""

from __future__ import annotations

import gzip
import json
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import gemmi
import numpy as np
from scipy.spatial import cKDTree

from chimera import ChimeraRunner
from contracts import CArtifactState, inspect_stage_c, load_npz_arrays
from density import ensure_model_map_frame_compatible, experimental_density_identity
from failures import ExternalToolError, KnownFailureCode, KnownSampleFailure, ToolFailureCode
from io_utils import (
    atomic_save_npz,
    read_jsonl,
    safe_object_filename,
    sha256_file,
    sha256_manifest,
    sha256_named_values,
    write_jsonl,
)
from mapq import (
    MAPQ_COMMIT,
    MAPQ_CIF_OPENMODELS_PATCH,
    MAPQ_NP,
    MAPQ_PACKAGE_NAME,
    MAPQ_SIGMA,
    MAPQ_ZIP_SHA256,
    MapQRunner,
)
from model_cif import write_normalized_model_cif
from mrc import (
    POCKET_RESAMPLE_ALL_DIFF,
    POCKET_RESAMPLE_ALL_EQUAL,
    POCKET_RESAMPLE_MIXED_COMPAT,
    MapGrid,
    load_map,
    write_canonical_mrc,
)
from parse import category_rows, clean_value, selected_raw_atom_rows
from qc import cc_value_errors, density_artifact_errors, density_pair_errors
from reports import write_report


QUALITY_SCHEMA_VERSION = 3
FULL_MODEL_SELECTION = "first_model_stage_c_altloc_heavy_ATOM_and_HETATM"
POCKET_RADIUS_ANGSTROM = 6.0
POCKET_DEFINITION = (
    "first_model_stage_c_altloc_heavy_group_PDB_ATOM_"
    "within_radius_of_any_present_ligand_atom"
)
CC_SEMANTICS = {
    "cc_contour": "实验图高于映射到 Pocket canonical 幅值空间的 recommended contour，不减均值",
    "cc_contour_about_mean": "同一 canonical contour mask 内两图分别减各自均值",
    "cc_all": "Chimera aboveThreshold=false，即实验图非零 grid mask 上，不减均值",
    "cc_all_about_mean": "同一实验图非零 mask 内两图分别减各自均值",
}
CONTOUR_SCALE_METHOD = "prod(even_input_shape_zyx)/prod(actual_output_shape_zyx)"
_QUALITY_TRANSIENT_SUFFIXES = frozenset({".cif", ".map", ".mrc"})
_QUALITY_ATOMIC_TEMP_MARKERS = (".cif.tmp.", ".map.tmp.", ".mrc.tmp.")


def _is_quality_attempt_transient(path: Path) -> bool:
    """判断文件是否为 Stage F attempt 内不应长期保留的大型中间体。"""
    name = path.name.lower()
    return path.suffix.lower() in _QUALITY_TRANSIENT_SUFFIXES or any(
        marker in name for marker in _QUALITY_ATOMIC_TEMP_MARKERS
    )


def _cleanup_quality_attempt_transients(attempt_dir: Path) -> list[str]:
    """
    仅清理一个精确 Stage F attempt 内的大型 MRC/MAP/CIF 中间体。

    返回值是已删除文件相对 attempt 的有序路径；小型日志、脚本和目录原样保留。
    任一路径越界或删除失败都会显式抛错，禁止静默扩大清理范围。
    """
    attempt_root = attempt_dir.resolve(strict=False)
    removed: list[str] = []
    failures: list[str] = []
    for path in sorted(attempt_dir.rglob("*"), key=lambda item: item.as_posix()):
        if not (path.is_file() or path.is_symlink()) or not _is_quality_attempt_transient(path):
            continue
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(attempt_root):
            failures.append(f"out_of_scope:{path}")
            continue
        try:
            relative = path.relative_to(attempt_dir).as_posix()
            path.unlink(missing_ok=True)
            removed.append(relative)
        except OSError as exc:
            failures.append(f"unlink_failed:{path}:{type(exc).__name__}:{exc}")
    if failures:
        evidence_path = attempt_dir / "cleanup_errors.json"
        try:
            write_report(
                evidence_path,
                {
                    "schema_version": 1,
                    "attempt_dir": str(attempt_dir),
                    "failures": failures,
                },
            )
        except OSError:
            pass
        raise RuntimeError(f"Stage F scratch cleanup failed: {failures}")
    return removed


@contextmanager
def _quality_attempt_scope(attempt_dir: Path) -> Iterator[None]:
    """为一个精确 attempt 提供成功与异常路径一致的大文件清理边界。"""
    primary_error: BaseException | None = None
    try:
        yield
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        try:
            _cleanup_quality_attempt_transients(attempt_dir)
        except Exception as cleanup_error:
            if primary_error is not None:
                raise RuntimeError(
                    "Stage F attempt failed and scratch cleanup also failed: "
                    f"{type(primary_error).__name__}: {primary_error}; "
                    f"cleanup={type(cleanup_error).__name__}: {cleanup_error}"
                ) from primary_error
            raise


def _contour_provenance_from_exp(exp_arrays: dict[str, np.ndarray]) -> dict[str, Any]:
    """
    从已完成的 E1 artifact 构造并校验 F 使用的 contour provenance。

    输入参数:
        - exp_arrays: dict[str, np.ndarray], E1 ``exp.npz`` 的完整数组映射

    输出:
        - contour: dict[str, Any], 包含:
            - ``value``: float 或 None, Chimera 实际消费的 canonical contour
            - ``value_space``: str, 固定为 Pocket canonical 密度幅值空间
            - ``native_value``: float 或 None, EMDB metadata 原始 contour
            - ``canonical_value``: float 或 None, 映射后的 contour
            - ``scale_to_canonical``: float, native→canonical 全局幅值比例
            - ``scale_method``: str, 比例公式
            - ``resample_mode``: str, E1 实际重采样模式
            - ``status/path/source``: str, E1 contour 元数据
    """
    present = bool(np.asarray(exp_arrays["contour_present"]))
    status = str(np.asarray(exp_arrays["contour_status"]).item())
    scale = float(np.asarray(exp_arrays["contour_scale_to_canonical"]))
    resample_mode = str(np.asarray(exp_arrays["resample_mode"]).item())
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("E1 contour scale must be finite and positive")
    if resample_mode not in {
        POCKET_RESAMPLE_ALL_EQUAL,
        POCKET_RESAMPLE_ALL_DIFF,
        POCKET_RESAMPLE_MIXED_COMPAT,
    }:
        raise ValueError(f"unsupported E1 resample mode: {resample_mode}")

    native_value: float | None = None
    canonical_value: float | None = None
    if present:
        native_value = float(np.asarray(exp_arrays["contour_native"]))
        canonical_value = float(np.asarray(exp_arrays["contour_canonical"]))
        expected_canonical = float(np.float32(native_value * scale))
        if (
            status != "ok"
            or not np.isfinite(native_value)
            or not np.isfinite(canonical_value)
            or canonical_value != expected_canonical
        ):
            raise ValueError("E1 contour mapping is inconsistent")
    else:
        missing_values = [
            float(np.asarray(exp_arrays[key]))
            for key in ("contour", "contour_native", "contour_canonical")
        ]
        if status == "ok" or not all(np.isnan(value) for value in missing_values):
            raise ValueError("E1 missing contour must use non-ok status and three NaN values")

    return {
        "value": canonical_value,
        "value_space": "canonical_pocket_resampled_density",
        "native_value": native_value,
        "canonical_value": canonical_value,
        "scale_to_canonical": scale,
        "scale_method": CONTOUR_SCALE_METHOD,
        "resample_mode": resample_mode,
        "status": status,
        "path": str(np.asarray(exp_arrays["contour_path"]).item()),
        "source": str(np.asarray(exp_arrays["contour_source"]).item()),
    }


def project_occurrence_qscores(
    occurrences: list[dict[str, Any]],
    coords_arrays: dict[str, np.ndarray],
    ligand_objects: dict[str, dict[str, np.ndarray]],
    selected_atom_rows: list[dict[str, str]],
    q_by_atom_site_id: dict[str, float],
) -> dict[str, np.ndarray]:
    """
    将 MapQ 全模型原子值严格投影到每个 LigandObject 行序。

    输入参数:
        - occurrences: list[dict], Stage C occurrence 记录
        - coords_arrays: dict, ``coords_{cid}/present_{cid}``
        - ligand_objects: dict, object_key 到 ``atoms/atom_names``
        - selected_atom_rows: list[dict], 与 MapQ 输入相同的首 model/altloc 重原子行
        - q_by_atom_site_id: dict[str,float], 已由 MapQ adapter 验证的全模型 Q

    输出:
        - arrays: dict[str,np.ndarray], 每项 ``qscore_{cid} (M,) float32``；present=False 为 NaN

    映射主键依次使用 component residue 身份、``atoms.residue_id``、``atom_names``，最终落到
    原始 ``atom_site.id``。禁止按输出行序、残基遍历顺序、坐标最近邻或图同构猜测。
    """
    output: dict[str, np.ndarray] = {}
    globally_used_atom_ids: set[str] = set()
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        object_key = str(occurrence["object_key"])
        ligand_object = ligand_objects[object_key]
        atoms = ligand_object["atoms"]
        atom_names = [str(value) for value in ligand_object["atom_names"].tolist()]
        coords = coords_arrays[f"coords_{candidate_id}"]
        present = coords_arrays[f"present_{candidate_id}"]
        if len(atoms) != len(atom_names) or len(coords) != len(atoms) or len(present) != len(atoms):
            raise ExternalToolError(
                ToolFailureCode.ATOM_MAPPING,
                f"LigandObject/coords row mismatch for candidate {candidate_id}",
            )
        components = {int(item["index"]): item for item in occurrence["components"]}
        q_scores = np.full((len(atoms),), np.nan, dtype=np.float32)
        used_in_occurrence: set[str] = set()
        for atom_index, (atom, atom_name) in enumerate(zip(atoms, atom_names, strict=True)):
            if not bool(present[atom_index]):
                continue
            residue_index = int(atom["residue_id"])
            if residue_index not in components:
                raise ExternalToolError(
                    ToolFailureCode.ATOM_MAPPING,
                    f"candidate {candidate_id} has no component index {residue_index}",
                )
            component = components[residue_index]
            matching_rows = [
                row
                for row in selected_atom_rows
                if _row_matches_component(row, component)
                and clean_value(row.get("label_atom_id", "")) == atom_name
            ]
            if len(matching_rows) != 1:
                raise ExternalToolError(
                    ToolFailureCode.ATOM_MAPPING,
                    f"candidate {candidate_id} atom {residue_index}:{atom_name} maps to "
                    f"{len(matching_rows)} atom_site rows",
                )
            row = matching_rows[0]
            atom_site_id = clean_value(row.get("id", ""))
            if atom_site_id in used_in_occurrence or atom_site_id in globally_used_atom_ids:
                raise ExternalToolError(
                    ToolFailureCode.ATOM_MAPPING,
                    f"atom_site.id {atom_site_id} maps to multiple LigandObject slots",
                )
            try:
                row_coord = np.asarray(
                    [float(row["Cartn_x"]), float(row["Cartn_y"]), float(row["Cartn_z"])],
                    dtype=np.float32,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ExternalToolError(
                    ToolFailureCode.ATOM_MAPPING,
                    f"invalid coordinate for atom_site.id {atom_site_id}",
                ) from exc
            if not np.allclose(row_coord, coords[atom_index], rtol=0, atol=1e-4):
                raise ExternalToolError(
                    ToolFailureCode.ATOM_MAPPING,
                    f"Stage C coordinate disagrees with atom_site.id {atom_site_id}",
                )
            if atom_site_id not in q_by_atom_site_id:
                raise ExternalToolError(
                    ToolFailureCode.ATOM_MAPPING,
                    f"MapQ has no value for atom_site.id {atom_site_id}",
                )
            q_scores[atom_index] = np.float32(q_by_atom_site_id[atom_site_id])
            used_in_occurrence.add(atom_site_id)
            globally_used_atom_ids.add(atom_site_id)
        if int(np.count_nonzero(np.isfinite(q_scores))) != int(np.count_nonzero(present)):
            raise ExternalToolError(
                ToolFailureCode.ATOM_MAPPING,
                f"candidate {candidate_id} n_valid != n_present",
            )
        output[f"qscore_{candidate_id}"] = q_scores
    return output


def occurrence_pocket_atom_site_ids(
    occurrences: list[dict[str, Any]],
    coords_arrays: dict[str, np.ndarray],
    selected_atom_rows: list[dict[str, str]],
    *,
    radius_angstrom: float = POCKET_RADIUS_ANGSTROM,
) -> dict[int, np.ndarray]:
    """
    为每个 occurrence 选择固定包络内的受体重原子 ``atom_site.id``。

    口袋定义为：首 model、Stage C 规范 altloc、``group_PDB=ATOM`` 的重原子中，
    到该 occurrence 任一 ``present=True`` 配体重原子的距离不超过 ``radius_angstrom``。
    返回 id 按数值升序排列，不依赖 KD-tree 的内部遍历顺序。
    """
    if not np.isfinite(radius_angstrom) or radius_angstrom <= 0:
        raise ValueError("pocket radius must be a positive finite number")
    receptor_rows = [
        row
        for row in selected_atom_rows
        if clean_value(row.get("group_PDB", "")).upper() == "ATOM"
    ]
    if not receptor_rows:
        raise KnownSampleFailure(
            KnownFailureCode.NO_POCKET_RECEPTOR_ATOMS,
            "selected full model contains no group_PDB=ATOM receptor heavy atoms",
        )
    try:
        receptor_ids = np.asarray([int(clean_value(row["id"])) for row in receptor_rows], dtype=np.int64)
        receptor_coords = np.asarray(
            [
                [float(row["Cartn_x"]), float(row["Cartn_y"]), float(row["Cartn_z"])]
                for row in receptor_rows
            ],
            dtype=np.float64,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ExternalToolError(
            ToolFailureCode.ATOM_MAPPING,
            "receptor atom_site identity/coordinates are invalid",
        ) from exc
    if len(np.unique(receptor_ids)) != len(receptor_ids) or not np.isfinite(receptor_coords).all():
        raise ExternalToolError(
            ToolFailureCode.ATOM_MAPPING,
            "receptor atom_site ids are duplicated or coordinates are non-finite",
        )

    receptor_tree = cKDTree(receptor_coords)
    pocket_ids: dict[int, np.ndarray] = {}
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        ligand_coords = np.asarray(coords_arrays[f"coords_{candidate_id}"], dtype=np.float64)
        present = np.asarray(coords_arrays[f"present_{candidate_id}"])
        present_coords = ligand_coords[present]
        if len(present_coords) == 0:
            raise KnownSampleFailure(
                KnownFailureCode.NO_PRESENT_LIGAND_ATOMS,
                f"candidate {candidate_id} has no present ligand heavy atom",
            )
        neighborhoods = receptor_tree.query_ball_point(present_coords, r=float(radius_angstrom))
        nonempty = [np.asarray(indices, dtype=np.int64) for indices in neighborhoods if indices]
        if nonempty:
            selected_indices = np.unique(np.concatenate(nonempty))
            pocket_ids[candidate_id] = np.sort(receptor_ids[selected_indices]).astype(
                np.int64,
                copy=False,
            )
        else:
            # 空包络是 occurrence 级可观测结果，不应连带淘汰同一 PDB 的其他 occurrence。
            pocket_ids[candidate_id] = np.empty((0,), dtype=np.int64)
    return pocket_ids


def compute_occurrence_pocket_qscores(
    occurrences: list[dict[str, Any]],
    coords_arrays: dict[str, np.ndarray],
    selected_atom_rows: list[dict[str, str]],
    q_by_atom_site_id: dict[str, float],
    *,
    radius_angstrom: float = POCKET_RADIUS_ANGSTROM,
) -> dict[str, np.ndarray]:
    """选择 occurrence 口袋并保存有序原子 id 与对应 MapQ 原始 Q 值。"""
    ids_by_candidate = occurrence_pocket_atom_site_ids(
        occurrences,
        coords_arrays,
        selected_atom_rows,
        radius_angstrom=radius_angstrom,
    )
    arrays: dict[str, np.ndarray] = {}
    for candidate_id, atom_site_ids in ids_by_candidate.items():
        try:
            q_scores = np.asarray(
                [q_by_atom_site_id[str(int(atom_id))] for atom_id in atom_site_ids],
                dtype=np.float32,
            )
        except KeyError as exc:
            raise ExternalToolError(
                ToolFailureCode.ATOM_MAPPING,
                f"MapQ has no pocket value for atom_site.id {exc.args[0]}",
            ) from exc
        if not np.isfinite(q_scores).all() or np.any(q_scores < -1.0 - 1e-6) or np.any(
            q_scores > 1.0 + 1e-6
        ):
            raise ExternalToolError(
                ToolFailureCode.ATOM_MAPPING,
                f"candidate {candidate_id} pocket contains invalid Q-score values",
            )
        arrays[f"pocket_atom_site_id_{candidate_id}"] = atom_site_ids
        arrays[f"pocket_qscore_{candidate_id}"] = q_scores
    return arrays


def build_quality_records(
    pdb_id: str,
    occurrences: list[dict[str, Any]],
    coords_arrays: dict[str, np.ndarray],
    qscore_arrays: dict[str, np.ndarray],
    *,
    resolution: float,
    cc_values: dict[str, float | None],
    contour_status: str,
) -> list[dict[str, Any]]:
    """聚合配体与 6 Å 受体口袋 Q 的原始统计，并重复全局四 CC。"""
    records: list[dict[str, Any]] = []
    for occurrence in sorted(occurrences, key=lambda item: int(item["candidate_id"])):
        candidate_id = int(occurrence["candidate_id"])
        present = coords_arrays[f"present_{candidate_id}"]
        q_scores = qscore_arrays[f"qscore_{candidate_id}"]
        pocket_q_scores = qscore_arrays[f"pocket_qscore_{candidate_id}"]
        pocket_atom_ids = qscore_arrays[f"pocket_atom_site_id_{candidate_id}"]
        valid = q_scores[np.isfinite(q_scores)]
        pocket_valid = pocket_q_scores[np.isfinite(pocket_q_scores)]
        n_present = int(np.count_nonzero(present))
        if len(valid) != n_present or n_present == 0:
            raise ExternalToolError(
                ToolFailureCode.ATOM_MAPPING,
                f"candidate {candidate_id} has incomplete valid Q-score values",
            )
        if len(pocket_valid) != len(pocket_atom_ids):
            raise ExternalToolError(
                ToolFailureCode.ATOM_MAPPING,
                f"candidate {candidate_id} has incomplete pocket Q-score values",
            )
        pocket_available = len(pocket_atom_ids) > 0
        record: dict[str, Any] = {
            "pdb_id": pdb_id.lower(),
            "candidate_id": candidate_id,
            "q_score": float(np.mean(valid, dtype=np.float64)),
            "q_score_median": float(np.median(valid)),
            "q_score_min": float(np.min(valid)),
            "n_valid": int(len(valid)),
            "n_present": n_present,
            "pocket_q_score": (
                float(np.mean(pocket_valid, dtype=np.float64)) if pocket_available else None
            ),
            "pocket_q_score_median": float(np.median(pocket_valid)) if pocket_available else None,
            "pocket_q_score_min": float(np.min(pocket_valid)) if pocket_available else None,
            "pocket_n_valid": int(len(pocket_valid)),
            "pocket_n_atoms": int(len(pocket_atom_ids)),
            "pocket_status": "ok" if pocket_available else "no_receptor_atoms_within_radius",
            "pocket_radius_angstrom": float(POCKET_RADIUS_ANGSTROM),
            "map_resolution": float(resolution),
            "livq": None,
            "contour_status": contour_status,
        }
        record.update(cc_values)
        records.append(record)
    return records


def quality_artifact_errors(
    occurrences: list[dict[str, Any]],
    coords_arrays: dict[str, np.ndarray],
    ligand_objects: dict[str, dict[str, np.ndarray]],
    selected_atom_rows: list[dict[str, str]],
    qscore_arrays: dict[str, np.ndarray],
    quality_records: list[dict[str, Any]],
    *,
    resolution: float,
    contour_status: str,
    source_manifest_sha256: str,
) -> list[str]:
    """验证 F 两个正式产物的配体/口袋行序、聚合、provenance 和四 CC。"""
    errors: list[str] = []
    if str(np.asarray(qscore_arrays.get("source_manifest_sha256", "")).item()) != source_manifest_sha256:
        errors.append("quality_provenance:source_manifest")
    schema = np.asarray(qscore_arrays.get("schema_version", -1))
    if schema.shape != () or int(schema) != QUALITY_SCHEMA_VERSION:
        errors.append("quality_contract:schema_version")
    if str(np.asarray(qscore_arrays.get("mapping_method", "")).item()) != (
        "atom_site.id+full_identity+component_index+atom_name"
    ):
        errors.append("quality_contract:mapping_method")
    sigma = np.asarray(qscore_arrays.get("mapq_sigma", np.nan))
    if sigma.dtype != np.float32 or sigma.shape != () or not np.isclose(
        float(sigma),
        MAPQ_SIGMA,
        rtol=0,
        atol=1e-6,
    ):
        errors.append("quality_contract:mapq_sigma")
    mapq_np = np.asarray(qscore_arrays.get("mapq_np", -1))
    if mapq_np.dtype != np.int16 or mapq_np.shape != () or int(mapq_np) != MAPQ_NP:
        errors.append("quality_contract:mapq_np")
    pocket_radius = np.asarray(qscore_arrays.get("pocket_radius_angstrom", np.nan))
    if pocket_radius.dtype != np.float32 or pocket_radius.shape != () or not np.isclose(
        float(pocket_radius),
        POCKET_RADIUS_ANGSTROM,
        rtol=0,
        atol=1e-6,
    ):
        errors.append("quality_contract:pocket_radius")
    if str(np.asarray(qscore_arrays.get("pocket_definition", "")).item()) != POCKET_DEFINITION:
        errors.append("quality_contract:pocket_definition")
    records_by_id = {int(record["candidate_id"]): record for record in quality_records}
    expected_ids = {int(item["candidate_id"]) for item in occurrences}
    if set(records_by_id) != expected_ids or len(records_by_id) != len(quality_records):
        errors.append("quality_contract:candidate_ids")
        return errors
    expected_pocket_ids = occurrence_pocket_atom_site_ids(
        occurrences,
        coords_arrays,
        selected_atom_rows,
    )
    for occurrence in occurrences:
        candidate_id = int(occurrence["candidate_id"])
        object_key = str(occurrence["object_key"])
        n_atoms = len(ligand_objects[object_key]["atoms"])
        key = f"qscore_{candidate_id}"
        if key not in qscore_arrays:
            errors.append(f"quality_missing:{key}")
            continue
        q_scores = qscore_arrays[key]
        present = coords_arrays[f"present_{candidate_id}"]
        if q_scores.dtype != np.float32 or q_scores.shape != (n_atoms,):
            errors.append(f"quality_contract:{key}")
            continue
        if not np.isnan(q_scores[~present]).all():
            errors.append(f"quality_value:missing_not_nan:{candidate_id}")
        if not np.isfinite(q_scores[present]).all():
            errors.append(f"quality_value:present_nonfinite:{candidate_id}")
            continue
        if np.any(q_scores[present] < -1.0 - 1e-6) or np.any(q_scores[present] > 1.0 + 1e-6):
            errors.append(f"quality_value:present_out_of_range:{candidate_id}")
            continue
        pocket_id_key = f"pocket_atom_site_id_{candidate_id}"
        pocket_q_key = f"pocket_qscore_{candidate_id}"
        if pocket_id_key not in qscore_arrays or pocket_q_key not in qscore_arrays:
            errors.append(f"quality_missing:pocket:{candidate_id}")
            continue
        pocket_atom_ids = np.asarray(qscore_arrays[pocket_id_key])
        pocket_q_scores = np.asarray(qscore_arrays[pocket_q_key])
        if pocket_atom_ids.dtype != np.int64 or pocket_atom_ids.ndim != 1:
            errors.append(f"quality_contract:{pocket_id_key}")
            continue
        if not np.array_equal(pocket_atom_ids, expected_pocket_ids[candidate_id]):
            errors.append(f"quality_value:pocket_ids:{candidate_id}")
        if pocket_q_scores.dtype != np.float32 or pocket_q_scores.shape != pocket_atom_ids.shape:
            errors.append(f"quality_contract:{pocket_q_key}")
            continue
        if not np.isfinite(pocket_q_scores).all():
            errors.append(f"quality_value:pocket_nonfinite:{candidate_id}")
            continue
        if np.any(pocket_q_scores < -1.0 - 1e-6) or np.any(pocket_q_scores > 1.0 + 1e-6):
            errors.append(f"quality_value:pocket_out_of_range:{candidate_id}")
            continue
        record = records_by_id[candidate_id]
        valid = q_scores[present]
        expected: dict[str, float | None] = {
            "q_score": float(np.mean(valid, dtype=np.float64)),
            "q_score_median": float(np.median(valid)),
            "q_score_min": float(np.min(valid)),
            "pocket_q_score": (
                float(np.mean(pocket_q_scores, dtype=np.float64)) if len(pocket_q_scores) else None
            ),
            "pocket_q_score_median": (
                float(np.median(pocket_q_scores)) if len(pocket_q_scores) else None
            ),
            "pocket_q_score_min": float(np.min(pocket_q_scores)) if len(pocket_q_scores) else None,
        }
        for field, value in expected.items():
            if value is None:
                unchanged = record.get(field) is None
            else:
                try:
                    unchanged = np.isclose(float(record[field]), value, rtol=0, atol=1e-6)
                except (KeyError, TypeError, ValueError):
                    unchanged = False
            if not unchanged:
                errors.append(f"quality_value:{field}:{candidate_id}")
        if int(record.get("n_valid", -1)) != len(valid) or int(record.get("n_present", -1)) != len(valid):
            errors.append(f"quality_value:counts:{candidate_id}")
        if int(record.get("pocket_n_valid", -1)) != len(pocket_q_scores) or int(
            record.get("pocket_n_atoms", -1)
        ) != len(pocket_atom_ids):
            errors.append(f"quality_value:pocket_counts:{candidate_id}")
        expected_pocket_status = "ok" if len(pocket_atom_ids) else "no_receptor_atoms_within_radius"
        if record.get("pocket_status") != expected_pocket_status:
            errors.append(f"quality_value:pocket_status:{candidate_id}")
        if not np.isclose(
            float(record.get("pocket_radius_angstrom", np.nan)),
            POCKET_RADIUS_ANGSTROM,
            rtol=0,
            atol=1e-6,
        ):
            errors.append(f"quality_value:pocket_radius:{candidate_id}")
        if not np.isclose(float(record.get("map_resolution", np.nan)), resolution, rtol=0, atol=1e-6):
            errors.append(f"quality_value:resolution:{candidate_id}")
    if quality_records:
        if any(record.get("contour_status") != contour_status for record in quality_records):
            errors.append("quality_value:contour_status")
        cc_values = {key: quality_records[0].get(key) for key in CC_SEMANTICS}
        contour_available = contour_status == "ok"
        errors.extend(cc_value_errors(cc_values, contour_available=contour_available))
        for record in quality_records[1:]:
            if any(record.get(key) != quality_records[0].get(key) for key in CC_SEMANTICS):
                errors.append("quality_value:global_cc_inconsistent")
                break
    return errors


def quality_provenance_errors(
    provenance: dict[str, Any],
    *,
    pdb_id: str,
    source_manifest_sha256: str,
    expected_contour: dict[str, Any],
    chimera_version: str,
    mapq_cmd_sha256: str,
) -> list[str]:
    """验证 Stage F provenance 与当前固定工具、口袋和输入契约一致。"""
    errors: list[str] = []
    expected_scalars = {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "pdb_id": pdb_id,
        "source_manifest_sha256": source_manifest_sha256,
        "full_model_selection": FULL_MODEL_SELECTION,
        "chimera_version": chimera_version,
    }
    for key, expected in expected_scalars.items():
        if provenance.get(key) != expected:
            errors.append(f"quality_provenance:{key}")
    if provenance.get("cc_semantics") != CC_SEMANTICS:
        errors.append("quality_provenance:cc_semantics")
    contour = provenance.get("contour")
    if not isinstance(contour, dict):
        errors.append("quality_provenance:contour")
    elif contour != expected_contour:
        errors.append("quality_provenance:contour_mapping")
    pocket = provenance.get("pocket_qscore")
    if not isinstance(pocket, dict):
        errors.append("quality_provenance:pocket_qscore")
    else:
        if pocket.get("definition") != POCKET_DEFINITION:
            errors.append("quality_provenance:pocket_definition")
        try:
            radius_matches = np.isclose(
                float(pocket.get("radius_angstrom")),
                POCKET_RADIUS_ANGSTROM,
                rtol=0,
                atol=1e-6,
            )
        except (TypeError, ValueError):
            radius_matches = False
        if not radius_matches:
            errors.append("quality_provenance:pocket_radius")
    mapq = provenance.get("mapq")
    if not isinstance(mapq, dict):
        errors.append("quality_provenance:mapq")
    else:
        expected_mapq = {
            "package": MAPQ_PACKAGE_NAME,
            "commit": MAPQ_COMMIT,
            "zip_sha256": MAPQ_ZIP_SHA256,
            "mapq_cmd_sha256": mapq_cmd_sha256,
            "adapter_patch": MAPQ_CIF_OPENMODELS_PATCH,
            "sigma": MAPQ_SIGMA,
            "np": MAPQ_NP,
        }
        for key, expected in expected_mapq.items():
            if mapq.get(key) != expected:
                errors.append(f"quality_provenance:mapq_{key}")
    return errors


def build_quality(
    root: Path,
    record: dict[str, Any],
    *,
    chimera_runner: ChimeraRunner,
    mapq_runner: MapQRunner,
    chimera_version: str,
    run_id: str,
    scratch_root: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    """端到端幂等生成四 CC、逐配体原子 Q 与 6 Å 受体口袋 Q。"""
    pdb_id = str(record["pdb_id"]).lower()
    try:
        resolution = float(record.get("resolution"))
    except (TypeError, ValueError) as exc:
        raise KnownSampleFailure(KnownFailureCode.MISSING_RESOLUTION, pdb_id) from exc
    if not np.isfinite(resolution) or resolution <= 0:
        raise KnownSampleFailure(KnownFailureCode.MISSING_RESOLUTION, pdb_id)
    inspection = inspect_stage_c(root, pdb_id)
    if inspection.state is not CArtifactState.COMPLETE:
        raise RuntimeError(
            f"Stage C is not release-ready for {pdb_id}: "
            f"{inspection.state.value}: {inspection.reasons}"
        )
    occurrences = list(inspection.occurrences)
    if not occurrences:
        raise KnownSampleFailure(KnownFailureCode.NO_OCCURRENCES, pdb_id)

    parse_dir = root / "parse" / pdb_id
    occurrence_path = parse_dir / "occurrences.jsonl"
    coords_path = parse_dir / "ligand_coords.npz"
    receptor_path = parse_dir / "receptor_tokens.npz"
    exp_path = root / "density" / pdb_id / "exp.npz"
    cif_path = root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif"
    emdb_id = str(record["emdb_id"]).upper()
    native_gz_path = root / "raw" / "emdb_maps" / f"emd_{emdb_id.replace('EMD-', '')}.map.gz"
    if not native_gz_path.exists():
        raise KnownSampleFailure(KnownFailureCode.MISSING_MAP, str(native_gz_path))
    exp = load_npz_arrays(exp_path, allow_pickle=False)
    exp_stat = exp_path.stat()
    exp_errors = density_artifact_errors(exp, require_unit_voxel=False)
    if exp_errors:
        raise RuntimeError(f"Stage E1 is not valid for {pdb_id}: {exp_errors}")
    contour_provenance = _contour_provenance_from_exp(exp)
    native_map_stat = native_gz_path.stat()
    exp_source_stat = (
        int(np.asarray(exp["source_map_size"])),
        int(np.asarray(exp["source_map_mtime_ns"])),
    )
    if exp_source_stat != (native_map_stat.st_size, native_map_stat.st_mtime_ns):
        raise RuntimeError(
            f"Stage E1 is stale for {pdb_id}: native map size/mtime changed after canonicalization"
        )
    coords_arrays = load_npz_arrays(coords_path, allow_pickle=False)
    receptor_coords = load_npz_arrays(receptor_path, allow_pickle=False)["coords"]
    ensure_model_map_frame_compatible(pdb_id, exp, receptor_coords)
    selected_rows = selected_raw_atom_rows(
        category_rows(gemmi.cif.read(str(cif_path)).sole_block(), "_atom_site.")
    )
    ligand_objects: dict[str, dict[str, np.ndarray]] = {}
    object_paths: list[Path] = []
    for occurrence in occurrences:
        object_key = str(occurrence["object_key"])
        if object_key in ligand_objects:
            continue
        object_path = root / "ligand_objects" / f"{safe_object_filename(object_key)}.npz"
        object_paths.append(object_path)
        ligand_objects[object_key] = load_npz_arrays(object_path, allow_pickle=True)
    small_source_manifest = sha256_manifest(
        [
            occurrence_path,
            coords_path,
            receptor_path,
            cif_path,
            *object_paths,
        ],
        base=root,
    )
    source_manifest = sha256_named_values(
        {
            "exp_identity_sha256": experimental_density_identity(exp),
            "exp_file_size": exp_stat.st_size,
            "exp_file_mtime_ns": exp_stat.st_mtime_ns,
            "native_map_sha256": str(np.asarray(exp["source_map_sha256"]).item()),
            "small_source_manifest_sha256": small_source_manifest,
        }
    )
    mapq_cmd_sha256 = sha256_file(mapq_runner.mapq_cmd_path)
    atoms_output_path = root / "quality_atoms" / f"{pdb_id}.npz"
    quality_output_path = root / "quality" / f"{pdb_id}.jsonl"
    provenance_path = root / "quality" / f"{pdb_id}.provenance.json"
    if atoms_output_path.exists() and quality_output_path.exists() and provenance_path.exists() and not overwrite:
        try:
            existing_atoms = load_npz_arrays(atoms_output_path, allow_pickle=False)
            existing_records = read_jsonl(quality_output_path)
            existing_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            if not isinstance(existing_provenance, dict):
                raise ValueError("quality provenance root is not an object")
            errors = quality_artifact_errors(
                occurrences,
                coords_arrays,
                ligand_objects,
                selected_rows,
                existing_atoms,
                existing_records,
                resolution=resolution,
                contour_status=str(exp["contour_status"].item()),
                source_manifest_sha256=source_manifest,
            )
            errors.extend(
                quality_provenance_errors(
                    existing_provenance,
                    pdb_id=pdb_id,
                    source_manifest_sha256=source_manifest,
                    expected_contour=contour_provenance,
                    chimera_version=chimera_version,
                    mapq_cmd_sha256=mapq_cmd_sha256,
                )
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            errors = ["quality_unreadable"]
        if not errors:
            return {
                "status": "skipped",
                "quality": str(quality_output_path.relative_to(root)),
                "quality_atoms": str(atoms_output_path.relative_to(root)),
                "n_occurrences": len(occurrences),
            }

    attempt_id = uuid4().hex
    scratch_dir = scratch_root / run_id / "stage_f" / pdb_id / attempt_id
    scratch_dir.mkdir(parents=True, exist_ok=False)
    with _quality_attempt_scope(scratch_dir):
        full_model_path = scratch_dir / "full_model.cif"
        model_stats = write_normalized_model_cif(cif_path, full_model_path, atom_only=False)
        canonical_mrc_path = scratch_dir / "canonical_exp.mrc"
        write_canonical_mrc(
            canonical_mrc_path,
            MapGrid(exp["grid"][0], exp["voxel_size"], exp["origin"]),
        )
        full_sim_path = scratch_dir / "full_model_sim.mrc"
        molmap_result = chimera_runner.molmap_on_grid(
            full_model_path,
            canonical_mrc_path,
            full_sim_path,
            resolution=resolution,
            scratch_dir=scratch_dir,
        )
        full_sim = load_map(full_sim_path, multiply_global_origin=False)
        full_sim_arrays = {
            "grid": full_sim.grid[None],
            "voxel_size": full_sim.voxel_size,
            "origin": full_sim.origin,
        }
        geometry_errors = density_pair_errors(exp, full_sim_arrays, receptor_coords)
        if geometry_errors:
            raise ExternalToolError(ToolFailureCode.GEOMETRY_QC, str(geometry_errors))
        contour = float(exp["contour_canonical"]) if bool(exp["contour_present"]) else None
        cc_values, cc_result = chimera_runner.measure_correlations(
            canonical_mrc_path,
            full_sim_path,
            contour=contour,
            scratch_dir=scratch_dir,
        )

        native_mrc_path = scratch_dir / "native.mrc"
        with gzip.open(native_gz_path, "rb") as source, native_mrc_path.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        load_map(native_mrc_path, multiply_global_origin=True)
        mapq_result = mapq_runner.run(
            native_mrc_path,
            full_model_path,
            resolution=resolution,
            scratch_dir=scratch_dir,
        )
        qscore_arrays = project_occurrence_qscores(
            occurrences,
            coords_arrays,
            ligand_objects,
            selected_rows,
            mapq_result.q_by_atom_site_id,
        )
        qscore_arrays.update(
            compute_occurrence_pocket_qscores(
                occurrences,
                coords_arrays,
                selected_rows,
                mapq_result.q_by_atom_site_id,
            )
        )
        qscore_arrays.update(
            {
                "schema_version": np.asarray(QUALITY_SCHEMA_VERSION, dtype=np.uint16),
                "source_manifest_sha256": np.asarray(source_manifest),
                "mapping_method": np.asarray(
                    "atom_site.id+full_identity+component_index+atom_name"
                ),
                "mapq_sigma": np.asarray(MAPQ_SIGMA, dtype=np.float32),
                "mapq_np": np.asarray(MAPQ_NP, dtype=np.int16),
                "pocket_radius_angstrom": np.asarray(POCKET_RADIUS_ANGSTROM, dtype=np.float32),
                "pocket_definition": np.asarray(POCKET_DEFINITION),
            }
        )
        quality_records = build_quality_records(
            pdb_id,
            occurrences,
            coords_arrays,
            qscore_arrays,
            resolution=resolution,
            cc_values=cc_values,
            contour_status=str(exp["contour_status"].item()),
        )
        errors = quality_artifact_errors(
            occurrences,
            coords_arrays,
            ligand_objects,
            selected_rows,
            qscore_arrays,
            quality_records,
            resolution=resolution,
            contour_status=str(exp["contour_status"].item()),
            source_manifest_sha256=source_manifest,
        )
        if errors:
            raise RuntimeError(f"Stage F contract failed for {pdb_id}: {errors}")

        provenance = {
            "schema_version": QUALITY_SCHEMA_VERSION,
            "pdb_id": pdb_id,
            "source_manifest_sha256": source_manifest,
            "full_model_selection": FULL_MODEL_SELECTION,
            "normalized_model_n_atoms": model_stats["n_atoms"],
            "pocket_qscore": {
                "definition": POCKET_DEFINITION,
                "radius_angstrom": POCKET_RADIUS_ANGSTROM,
                "atom_group": "group_PDB=ATOM heavy atoms",
                "envelope": "distance to any present ligand heavy atom <= radius",
                "raw_arrays": "pocket_atom_site_id_{cid} + pocket_qscore_{cid}",
            },
            "cc_semantics": CC_SEMANTICS,
            "cc_values": cc_values,
            "contour": contour_provenance,
            "chimera_version": chimera_version,
            "mapq": {
                "package": MAPQ_PACKAGE_NAME,
                "commit": MAPQ_COMMIT,
                "zip_sha256": MAPQ_ZIP_SHA256,
                "mapq_cmd_sha256": mapq_cmd_sha256,
                "adapter_patch": mapq_result.adapter_patch,
                "cli_banner": mapq_result.cli_banner,
                "sigma": MAPQ_SIGMA,
                "np": MAPQ_NP,
            },
            "logs": {
                "molmap_stdout": str(molmap_result.stdout_path.relative_to(scratch_root)),
                "molmap_stderr": str(molmap_result.stderr_path.relative_to(scratch_root)),
                "cc_stdout": str(cc_result.stdout_path.relative_to(scratch_root)),
                "cc_stderr": str(cc_result.stderr_path.relative_to(scratch_root)),
                "mapq_stdout": str(mapq_result.tool_result.stdout_path.relative_to(scratch_root)),
                "mapq_stderr": str(mapq_result.tool_result.stderr_path.relative_to(scratch_root)),
            },
            "scratch": str(scratch_dir.relative_to(scratch_root)),
        }
        provenance_errors = quality_provenance_errors(
            provenance,
            pdb_id=pdb_id,
            source_manifest_sha256=source_manifest,
            expected_contour=contour_provenance,
            chimera_version=chimera_version,
            mapq_cmd_sha256=mapq_cmd_sha256,
        )
        if provenance_errors:
            raise RuntimeError(f"Stage F provenance failed for {pdb_id}: {provenance_errors}")
        atomic_save_npz(atoms_output_path, **qscore_arrays)
        write_jsonl(quality_output_path, quality_records)
        write_report(provenance_path, provenance)

        return {
            "status": "success",
            "quality": str(quality_output_path.relative_to(root)),
            "quality_atoms": str(atoms_output_path.relative_to(root)),
            "n_occurrences": len(occurrences),
            "scratch": str(scratch_dir.relative_to(scratch_root)),
        }


def _row_matches_component(row: dict[str, str], component: dict[str, Any]) -> bool:
    """用 label/auth 双身份判断 atom_site 行是否属于 occurrence component。"""
    if clean_value(row.get("label_asym_id", "")) != str(component.get("label_asym_id", "")):
        return False
    if clean_value(row.get("label_comp_id", "")).upper() != str(component.get("ccd_id", "")).upper():
        return False
    if clean_value(row.get("pdbx_PDB_ins_code", "")) != str(component.get("icode", "") or ""):
        return False
    auth_asym = str(component.get("auth_asym_id", "") or "")
    if auth_asym and clean_value(row.get("auth_asym_id", "")) != auth_asym:
        return False
    auth_seq = component.get("auth_seq_id")
    if auth_seq not in (None, "") and clean_value(row.get("auth_seq_id", "")) != str(auth_seq):
        return False
    row_label_seq = clean_value(row.get("label_seq_id", ""))
    component_label_seq = component.get("label_seq_id")
    if row_label_seq and component_label_seq is not None and row_label_seq != str(component_label_seq):
        return False
    return True
