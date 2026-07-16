# 学习导航：功能分区=运维迁移与质量门；生命周期=可复用的 Stage E3 schema 修复入口。
# 主要输入：冻结的旧 Stage E 状态、目标 ID 清单和当前 ligand-area 生产函数。
# 主要输出：独立 stage_e3_repair 四终态与只读验收 release summary。
# 关键边界：只迁移旧 Stage E 合格集合；不覆盖旧状态、de_release 或 exclusion。
"""Stage E3 ligand-area 的冻结目标迁移与只读 release gate。"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from joblib import Parallel, delayed

from contracts import CArtifactState, inspect_stage_c, load_npz_arrays
from density import (
    LIGAND_AREA_SCHEMA_VERSION,
    LIGAND_AREA_STORAGE_ENCODING,
    build_ligand_area,
    experimental_density_identity,
    ligand_area_errors,
)
from filtering import load_stage_statuses
from io_utils import (
    atomic_replace,
    read_jsonl,
    safe_object_filename,
    sha256_file,
    sha256_manifest,
    sha256_named_values,
)
from parallel import shard_items
from qc import density_artifact_errors
from reports import (
    StageStatus,
    failure_stage_result,
    resolve_run_id,
    stage_report_path,
    stage_result,
    write_report,
    write_stage_results,
)


E3_REPAIR_MANIFEST_SCHEMA_VERSION = 2
E3_REPAIR_STAGE = "stage_e3_repair"
E3_REPAIR_RELEASE = "stage_e3_repair_release"
E3_REPAIR_FREEZE = "stage_e3_freeze"
SOURCE_STAGE = "stage_e"
TARGET_POLICY = "stage_e_success_or_skipped_only"
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_STATUS_NAME_PATTERN = re.compile(r"status\.part_(\d{4})_of_(\d{4})\.jsonl")
_MANIFEST_FIELDS = {
    "schema_version",
    "source_run_id",
    "repair_run_id",
    "source_stage",
    "pair_list_path",
    "pair_list_sha256",
    "source_stage_status_paths",
    "source_stage_status_sha256",
    "source_stage_status_count",
    "de_release_path",
    "de_release_sha256",
    "exclusion_path",
    "exclusion_sha256",
    "target_ids_path",
    "target_ids_sha256",
    "target_manifest_path",
    "target_count",
    "target_policy",
}


@dataclass(frozen=True)
class E3RepairSnapshot:
    """已通过磁盘身份与旧 Stage E 合格集合交叉验证的迁移快照。"""

    source_run_id: str
    repair_run_id: str
    target_ids: tuple[str, ...]
    target_manifest_sha256: str
    target_ids_sha256: str
    pair_list_sha256: str
    source_stage_status_sha256: str
    source_stage_status_count: int
    de_release_sha256: str
    exclusion_sha256: str

    def evidence_fields(self) -> dict[str, Any]:
        """返回每条迁移状态必须携带的不可变输入身份字段。"""
        return {
            "source_run_id": self.source_run_id,
            "target_manifest_sha256": self.target_manifest_sha256,
            "target_ids_sha256": self.target_ids_sha256,
            "pair_list_sha256": self.pair_list_sha256,
            "source_stage_status_sha256": self.source_stage_status_sha256,
            "source_stage_status_count": self.source_stage_status_count,
            "de_release_sha256": self.de_release_sha256,
            "exclusion_sha256": self.exclusion_sha256,
            "target_count": len(self.target_ids),
            "target_policy": TARGET_POLICY,
        }


def prepare_repair_snapshot(
    root: Path,
    *,
    source_run_id: str,
    repair_run_id: str,
    target_ids_file: Path,
    target_manifest: Path,
    expected_source_stage_status_sha256: str,
    expected_de_release_sha256: str,
    expected_exclusion_sha256: str,
    expected_pair_list_sha256: str,
) -> dict[str, Any]:
    """从用户冻结的旧 Stage E 证据原子发布 repair 目标与 manifest。

    输入参数:
        - root: Path, AdaLigand 数据根
        - source_run_id/repair_run_id: str, 已完成正式 run 与独立迁移 run
        - target_ids_file/target_manifest: Path, 必须位于数据根内的两个冻结输出
        - expected_*_sha256: str, 用户或控制面预先冻结的四份旧证据摘要

    输出:
        - report: dict, 目标数量、目标/manifest SHA 与所有旧证据身份

    说明:
        manifest 是双文件提交标记，始终最后替换。异常时不会发布半份 manifest；
        重复运行只接受目标文件逐字节一致且 manifest 语义一致。
    """
    normalized_source_run_id = resolve_run_id(source_run_id)
    normalized_repair_run_id = resolve_run_id(repair_run_id)
    if normalized_repair_run_id == normalized_source_run_id:
        raise RuntimeError("E3 repair_run_id must be isolated from the source Stage E run_id")
    expected_freeze_dir = (
        root / "reports" / "runs" / normalized_repair_run_id / E3_REPAIR_FREEZE
    )
    _require_exact_output_path(
        target_ids_file,
        expected_freeze_dir / "target_ids.txt",
        label="target_ids_file",
    )
    _require_exact_output_path(
        target_manifest,
        expected_freeze_dir / "target_manifest.json",
        label="target_manifest",
    )
    expected_status_sha = _normalize_sha256(
        expected_source_stage_status_sha256,
        field="expected_source_stage_status_sha256",
    )
    expected_release_sha = _normalize_sha256(
        expected_de_release_sha256,
        field="expected_de_release_sha256",
    )
    expected_exclusions_sha = _normalize_sha256(
        expected_exclusion_sha256,
        field="expected_exclusion_sha256",
    )
    expected_pair_sha = _normalize_sha256(
        expected_pair_list_sha256,
        field="expected_pair_list_sha256",
    )
    evidence = _source_evidence_paths(root, normalized_source_run_id)
    _require_sha256(evidence["pair_list"], expected_pair_sha, label="pair_list")
    _require_sha256(evidence["de_release"], expected_release_sha, label="de_release")
    _require_sha256(evidence["exclusion"], expected_exclusions_sha, label="exclusion")

    pair_records = read_jsonl(evidence["pair_list"])
    pair_ids = [str(record.get("pdb_id", "")).lower() for record in pair_records]
    _validate_pdb_ids(pair_ids, source=str(evidence["pair_list"]), reject_duplicates=True)
    before_status_sha = _stage_status_snapshot_sha256(root, evidence["status_paths"])
    statuses, loaded_paths = load_stage_statuses(
        root,
        normalized_source_run_id,
        SOURCE_STAGE,
        set(pair_ids),
    )
    after_status_sha = _stage_status_snapshot_sha256(root, loaded_paths)
    if before_status_sha != after_status_sha:
        raise RuntimeError("source Stage E status changed while preparing E3 targets")
    if after_status_sha != expected_status_sha:
        raise RuntimeError(
            "source Stage E status identity drift: "
            f"actual={after_status_sha}, expected={expected_status_sha}"
        )
    target_ids = sorted(
        pdb_id
        for pdb_id, record in statuses.items()
        if record["status"] in {StageStatus.SUCCESS.value, StageStatus.SKIPPED.value}
    )
    if not target_ids:
        raise RuntimeError("source Stage E has no success/skipped targets for E3 repair")
    target_payload = "".join(f"{pdb_id}\n" for pdb_id in target_ids).encode("utf-8")
    target_ids_sha = _sha256_bytes(target_payload)
    manifest = {
        "schema_version": E3_REPAIR_MANIFEST_SCHEMA_VERSION,
        "source_run_id": normalized_source_run_id,
        "repair_run_id": normalized_repair_run_id,
        "source_stage": SOURCE_STAGE,
        "pair_list_path": _relative_path_identity(root, evidence["pair_list"]),
        "pair_list_sha256": expected_pair_sha,
        "source_stage_status_paths": [
            _relative_path_identity(root, path) for path in loaded_paths
        ],
        "source_stage_status_sha256": expected_status_sha,
        "source_stage_status_count": len(statuses),
        "de_release_path": _relative_path_identity(root, evidence["de_release"]),
        "de_release_sha256": expected_release_sha,
        "exclusion_path": _relative_path_identity(root, evidence["exclusion"]),
        "exclusion_sha256": expected_exclusions_sha,
        "target_ids_path": _relative_path_identity(root, target_ids_file),
        "target_ids_sha256": target_ids_sha,
        "target_manifest_path": _relative_path_identity(root, target_manifest),
        "target_count": len(target_ids),
        "target_policy": TARGET_POLICY,
    }
    manifest_payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    _publish_frozen_pair(
        target_ids_file=target_ids_file,
        target_ids_payload=target_payload,
        target_manifest=target_manifest,
        target_manifest_payload=manifest_payload,
        manifest=manifest,
    )
    return {
        "status": "frozen",
        "target_count": len(target_ids),
        "target_ids_sha256": target_ids_sha,
        "target_manifest_sha256": sha256_file(target_manifest),
        **manifest,
    }


def load_repair_snapshot(
    root: Path,
    *,
    repair_run_id: str,
    target_ids_file: Path,
    target_manifest: Path,
    expected_target_manifest_sha256: str,
) -> E3RepairSnapshot:
    """读取并验证 E3 迁移的冻结目标、pair 宇宙和旧 Stage E 状态。

    输入参数:
        - root: Path, AdaLigand 数据根
        - repair_run_id: str, 独立迁移 run id；不得等于旧正式 Stage E run id
        - target_ids_file: Path, 一行一个 PDB id 的冻结目标清单
        - target_manifest: Path, 绑定清单、pair_list 与旧 Stage E 状态身份的 JSON
        - expected_target_manifest_sha256: str, 控制面预先冻结的 manifest SHA-256

    输出:
        - snapshot: E3RepairSnapshot, 目标恰为旧 Stage E success/skipped 集合的只读快照
    """
    expected_manifest_sha = _normalize_sha256(
        expected_target_manifest_sha256,
        field="expected_target_manifest_sha256",
    )
    actual_manifest_sha = sha256_file(target_manifest)
    if actual_manifest_sha != expected_manifest_sha:
        raise RuntimeError(
            "E3 target manifest identity drift: "
            f"actual={actual_manifest_sha}, expected={expected_manifest_sha}"
        )
    manifest = json.loads(target_manifest.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("E3 target manifest must be a JSON object")
    missing = sorted(_MANIFEST_FIELDS.difference(manifest))
    extra = sorted(set(manifest).difference(_MANIFEST_FIELDS))
    if missing or extra:
        raise ValueError(f"E3 target manifest fields disagree: missing={missing}, extra={extra}")
    if manifest["schema_version"] != E3_REPAIR_MANIFEST_SCHEMA_VERSION:
        raise ValueError(
            f"E3 target manifest schema_version must be {E3_REPAIR_MANIFEST_SCHEMA_VERSION}"
        )
    if manifest["source_stage"] != SOURCE_STAGE:
        raise ValueError(f"E3 source_stage must be {SOURCE_STAGE}")
    if manifest["target_policy"] != TARGET_POLICY:
        raise ValueError(f"E3 target_policy must be {TARGET_POLICY}")

    source_run_id = resolve_run_id(str(manifest["source_run_id"]))
    normalized_repair_run_id = resolve_run_id(repair_run_id)
    if normalized_repair_run_id == source_run_id:
        raise RuntimeError("E3 repair_run_id must be isolated from the source Stage E run_id")
    manifest_repair_run_id = resolve_run_id(str(manifest["repair_run_id"]))
    if manifest_repair_run_id != normalized_repair_run_id:
        raise RuntimeError(
            "E3 target manifest repair_run_id drift: "
            f"actual={normalized_repair_run_id}, expected={manifest_repair_run_id}"
        )
    expected_freeze_dir = (
        root / "reports" / "runs" / normalized_repair_run_id / E3_REPAIR_FREEZE
    )
    _require_exact_output_path(
        target_ids_file,
        expected_freeze_dir / "target_ids.txt",
        label="target_ids_file",
    )
    _require_exact_output_path(
        target_manifest,
        expected_freeze_dir / "target_manifest.json",
        label="target_manifest",
    )

    evidence = _source_evidence_paths(root, source_run_id)
    _require_manifest_path(manifest, "pair_list_path", root, evidence["pair_list"])
    _require_manifest_path(manifest, "de_release_path", root, evidence["de_release"])
    _require_manifest_path(manifest, "exclusion_path", root, evidence["exclusion"])
    _require_manifest_path(manifest, "target_ids_path", root, target_ids_file)
    _require_manifest_path(manifest, "target_manifest_path", root, target_manifest)
    actual_status_path_ids = [
        _relative_path_identity(root, path) for path in evidence["status_paths"]
    ]
    declared_status_path_ids = manifest["source_stage_status_paths"]
    if (
        not isinstance(declared_status_path_ids, list)
        or not declared_status_path_ids
        or any(not isinstance(path_id, str) or not path_id for path_id in declared_status_path_ids)
        or len(set(declared_status_path_ids)) != len(declared_status_path_ids)
    ):
        raise ValueError("source_stage_status_paths must be a non-empty unique string list")
    if declared_status_path_ids != actual_status_path_ids:
        raise RuntimeError(
            "source Stage E status path identity drift: "
            f"actual={actual_status_path_ids}, expected={declared_status_path_ids}"
        )

    pair_path = evidence["pair_list"]
    expected_pair_sha = _manifest_sha256(manifest, "pair_list_sha256")
    actual_pair_sha = sha256_file(pair_path)
    if actual_pair_sha != expected_pair_sha:
        raise RuntimeError(
            f"E3 pair_list identity drift: actual={actual_pair_sha}, expected={expected_pair_sha}"
        )
    pair_records = read_jsonl(pair_path)
    pair_ids = [str(record.get("pdb_id", "")).lower() for record in pair_records]
    _validate_pdb_ids(pair_ids, source=str(pair_path), reject_duplicates=True)

    expected_ids_sha = _manifest_sha256(manifest, "target_ids_sha256")
    actual_ids_sha = sha256_file(target_ids_file)
    if actual_ids_sha != expected_ids_sha:
        raise RuntimeError(
            f"E3 target IDs identity drift: actual={actual_ids_sha}, expected={expected_ids_sha}"
        )
    target_ids = _read_frozen_ids(target_ids_file)
    expected_target_count = _manifest_positive_int(manifest, "target_count")
    if len(target_ids) != expected_target_count:
        raise RuntimeError(
            f"E3 target count drift: actual={len(target_ids)}, expected={expected_target_count}"
        )
    outside_pair = sorted(set(target_ids).difference(pair_ids))
    if outside_pair:
        raise RuntimeError(f"E3 target IDs outside pair_list: {outside_pair[:20]}")

    expected_release_sha = _manifest_sha256(manifest, "de_release_sha256")
    actual_release_sha = sha256_file(evidence["de_release"])
    if actual_release_sha != expected_release_sha:
        raise RuntimeError(
            "source de_release identity drift: "
            f"actual={actual_release_sha}, expected={expected_release_sha}"
        )
    expected_exclusion_sha = _manifest_sha256(manifest, "exclusion_sha256")
    actual_exclusion_sha = sha256_file(evidence["exclusion"])
    if actual_exclusion_sha != expected_exclusion_sha:
        raise RuntimeError(
            "source exclusion identity drift: "
            f"actual={actual_exclusion_sha}, expected={expected_exclusion_sha}"
        )

    status_paths = evidence["status_paths"]
    before_status_sha = _stage_status_snapshot_sha256(root, status_paths)
    statuses, loaded_paths = load_stage_statuses(root, source_run_id, SOURCE_STAGE, set(pair_ids))
    after_status_sha = _stage_status_snapshot_sha256(root, loaded_paths)
    if before_status_sha != after_status_sha:
        raise RuntimeError("source Stage E status changed while freezing E3 targets")
    expected_status_sha = _manifest_sha256(manifest, "source_stage_status_sha256")
    if after_status_sha != expected_status_sha:
        raise RuntimeError(
            "source Stage E status identity drift: "
            f"actual={after_status_sha}, expected={expected_status_sha}"
        )
    expected_status_count = _manifest_positive_int(manifest, "source_stage_status_count")
    if len(statuses) != expected_status_count:
        raise RuntimeError(
            "source Stage E status count drift: "
            f"actual={len(statuses)}, expected={expected_status_count}"
        )
    eligible_ids = {
        pdb_id
        for pdb_id, record in statuses.items()
        if record["status"] in {StageStatus.SUCCESS.value, StageStatus.SKIPPED.value}
    }
    if set(target_ids) != eligible_ids:
        missing_targets = sorted(eligible_ids.difference(target_ids))
        revived_failures = sorted(set(target_ids).difference(eligible_ids))
        raise RuntimeError(
            "E3 target set is not exactly the old Stage E eligible set: "
            f"missing={missing_targets[:20]}, revived={revived_failures[:20]}"
        )

    return E3RepairSnapshot(
        source_run_id=source_run_id,
        repair_run_id=normalized_repair_run_id,
        target_ids=tuple(sorted(target_ids)),
        target_manifest_sha256=actual_manifest_sha,
        target_ids_sha256=actual_ids_sha,
        pair_list_sha256=actual_pair_sha,
        source_stage_status_sha256=after_status_sha,
        source_stage_status_count=len(statuses),
        de_release_sha256=actual_release_sha,
        exclusion_sha256=actual_exclusion_sha,
    )


def run_repair_shard(
    root: Path,
    *,
    repair_run_id: str,
    target_ids_file: Path,
    target_manifest: Path,
    expected_target_manifest_sha256: str,
    part_id: int,
    total_parts: int,
    n_jobs: int,
) -> dict[str, Any]:
    """按互斥分片重建旧 schema E3，并写独立 run-scoped 四终态。"""
    snapshot = load_repair_snapshot(
        root,
        repair_run_id=repair_run_id,
        target_ids_file=target_ids_file,
        target_manifest=target_manifest,
        expected_target_manifest_sha256=expected_target_manifest_sha256,
    )
    if total_parts <= 0 or part_id < 0 or part_id >= total_parts:
        raise ValueError("invalid E3 repair part_id/total_parts")
    if total_parts > len(snapshot.target_ids):
        raise ValueError("E3 repair total_parts cannot exceed target count")
    if n_jobs == 0:
        raise ValueError("E3 repair n_jobs cannot be zero")
    shard = shard_items(snapshot.target_ids, part_id, total_parts)
    report_path = stage_report_path(
        root,
        snapshot.repair_run_id,
        E3_REPAIR_STAGE,
        part_id,
        total_parts,
    )
    _ensure_partition_contract(root, snapshot, total_parts=total_parts)
    _ensure_repair_namespace_compatible(
        root,
        snapshot,
        part_id=part_id,
        total_parts=total_parts,
        expected_shard=shard,
    )
    if report_path.exists():
        records = _validate_completed_shard(
            report_path,
            snapshot,
            part_id=part_id,
            total_parts=total_parts,
            expected_shard=shard,
        )
        return _shard_summary(snapshot, part_id, total_parts, records)
    claim_path = report_path.with_name(
        f"claim.part_{part_id:04d}_of_{total_parts:04d}.json"
    )
    try:
        _create_exclusive_json(
            claim_path,
            {
                "schema_version": 1,
                "run_id": snapshot.repair_run_id,
                "stage": E3_REPAIR_STAGE,
                "part_id": part_id,
                "total_parts": total_parts,
                "shard_count": len(shard),
                "shard_ids_sha256": sha256_named_values({"pdb_ids": shard}),
                **snapshot.evidence_fields(),
            },
        )
    except FileExistsError as exc:
        if report_path.exists():
            records = _validate_completed_shard(
                report_path,
                snapshot,
                part_id=part_id,
                total_parts=total_parts,
                expected_shard=shard,
            )
            return _shard_summary(snapshot, part_id, total_parts, records)
        raise RuntimeError(
            f"E3 repair shard claim exists without complete status: {claim_path}; "
            "stale claims require process-evidence review before manual removal"
        ) from exc
    results = Parallel(n_jobs=n_jobs, backend="loky", verbose=10)(
        delayed(_repair_one)(root, pdb_id, snapshot, part_id, total_parts)
        for pdb_id in shard
    )
    write_stage_results(report_path, results)
    return _shard_summary(snapshot, part_id, total_parts, results)


def _shard_summary(
    snapshot: E3RepairSnapshot,
    part_id: int,
    total_parts: int,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """为新完成或已完成的合法分片返回相同幂等摘要。"""
    return {
        "status": "completed",
        "run_id": snapshot.repair_run_id,
        "stage": E3_REPAIR_STAGE,
        "part_id": part_id,
        "total_parts": total_parts,
        "n_records": len(records),
        "status_counts": dict(sorted(Counter(item["status"] for item in records).items())),
        **snapshot.evidence_fields(),
    }


def gate_repair(
    root: Path,
    *,
    repair_run_id: str,
    target_ids_file: Path,
    target_manifest: Path,
    expected_target_manifest_sha256: str,
    n_jobs: int,
) -> dict[str, Any]:
    """只读验收全部 E3 v3 artifact，并原子写独立 release summary。"""
    snapshot = load_repair_snapshot(
        root,
        repair_run_id=repair_run_id,
        target_ids_file=target_ids_file,
        target_manifest=target_manifest,
        expected_target_manifest_sha256=expected_target_manifest_sha256,
    )
    if n_jobs == 0:
        raise ValueError("E3 repair gate n_jobs cannot be zero")
    expected_ids = set(snapshot.target_ids)
    before_status_paths = sorted(
        (root / "reports" / "runs" / snapshot.repair_run_id / E3_REPAIR_STAGE).glob(
            "status.part_*_of_*.jsonl"
        )
    )
    before_status_sha = _stage_status_snapshot_sha256(root, before_status_paths)
    statuses, status_paths = load_stage_statuses(
        root,
        snapshot.repair_run_id,
        E3_REPAIR_STAGE,
        expected_ids,
    )
    _validate_complete_partition_set(snapshot, statuses, status_paths)
    expected_evidence = snapshot.evidence_fields()
    for pdb_id, record in statuses.items():
        if record["status"] not in {StageStatus.SUCCESS.value, StageStatus.SKIPPED.value}:
            raise RuntimeError(f"E3 repair gate rejects non-success status for {pdb_id}")
        mismatched = [
            field
            for field, expected in expected_evidence.items()
            if record.get(field) != expected
        ]
        if mismatched:
            raise RuntimeError(f"E3 repair status provenance mismatch for {pdb_id}: {mismatched}")

    validations = Parallel(n_jobs=n_jobs, backend="loky", verbose=10)(
        delayed(_validate_one_artifact)(root, pdb_id) for pdb_id in snapshot.target_ids
    )
    failed = [record for record in validations if record["errors"]]
    if failed:
        raise RuntimeError(f"E3 repair artifact validation failed: {failed[:20]}")
    fresh_status_paths = sorted(
        (root / "reports" / "runs" / snapshot.repair_run_id / E3_REPAIR_STAGE).glob(
            "status.part_*_of_*.jsonl"
        )
    )
    if fresh_status_paths != before_status_paths:
        raise RuntimeError("E3 repair status path set changed during release audit")
    after_status_sha = _stage_status_snapshot_sha256(root, fresh_status_paths)
    if before_status_sha != after_status_sha:
        raise RuntimeError("E3 repair status content changed during release audit")

    status_counts = Counter(record["status"] for record in statuses.values())
    summary = {
        "schema_version": 1,
        "status": "success",
        "run_id": snapshot.repair_run_id,
        "stage": E3_REPAIR_STAGE,
        "source_run_id": snapshot.source_run_id,
        "n_target_pdb": len(snapshot.target_ids),
        "n_validated_artifacts": len(validations),
        "status_counts": dict(sorted(status_counts.items())),
        "repair_status_sha256": after_status_sha,
        "artifact_schema_version": LIGAND_AREA_SCHEMA_VERSION,
        "storage_encoding": LIGAND_AREA_STORAGE_ENCODING,
        "policy": "target all covered; success/skipped only; schema/source/geometry/ZIP_DEFLATED valid",
        **snapshot.evidence_fields(),
    }
    release_path = (
        root
        / "reports"
        / "runs"
        / snapshot.repair_run_id
        / E3_REPAIR_RELEASE
        / "summary.json"
    )
    _write_immutable_report(release_path, summary)
    return summary


def validate_ligand_area_artifact(root: Path, pdb_id: str) -> list[str]:
    """按当前生产方的 source identity 和 validator 只读检查一份 E3 artifact。"""
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

    parse_dir = root / "parse" / normalized_id
    occurrence_path = parse_dir / "occurrences.jsonl"
    coords_path = parse_dir / "ligand_coords.npz"
    candidate_ids = [int(occurrence["candidate_id"]) for occurrence in occurrences]
    object_paths = [
        root
        / "ligand_objects"
        / f"{safe_object_filename(str(occurrence['object_key']))}.npz"
        for occurrence in occurrences
    ]
    try:
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
        artifact_path = root / "density" / normalized_id / "ligand_area.npz"
        arrays = load_npz_arrays(artifact_path, allow_pickle=False)
    except (OSError, ValueError, KeyError) as exc:
        return [f"ligand_area:unreadable:{type(exc).__name__}"]
    return ligand_area_errors(
        arrays,
        grid_shape_zyx=tuple(int(value) for value in exp["grid"].shape[1:]),
        voxel_size_xyz=exp["voxel_size"],
        origin_xyz=exp["origin"],
        candidate_ids=candidate_ids,
        source_manifest_sha256=source_manifest,
        artifact_path=artifact_path,
    )


def _repair_one(
    root: Path,
    pdb_id: str,
    snapshot: E3RepairSnapshot,
    part_id: int,
    total_parts: int,
) -> dict[str, Any]:
    """迁移一个 PDB，并把任何漂移转换为当前 repair run 的互斥终态。"""
    common = {
        **snapshot.evidence_fields(),
        "part_id": part_id,
        "total_parts": total_parts,
    }
    try:
        result = build_ligand_area(root, pdb_id, overwrite=False)
        build_status = str(result.get("status"))
        if build_status not in {"success", "skipped"}:
            raise RuntimeError(f"unexpected build_ligand_area status: {build_status!r}")
        status = StageStatus.SUCCESS if build_status == "success" else StageStatus.SKIPPED
        return stage_result(
            pdb_id,
            E3_REPAIR_STAGE,
            status,
            build_status=build_status,
            artifact=result.get("artifact"),
            **common,
        )
    except Exception as exc:
        record = failure_stage_result(pdb_id, E3_REPAIR_STAGE, exc)
        record.update(common)
        return record


def _validate_one_artifact(root: Path, pdb_id: str) -> dict[str, Any]:
    """返回一个可由 gate 聚合的只读 artifact 验证结果。"""
    try:
        errors = validate_ligand_area_artifact(root, pdb_id)
    except Exception as exc:
        errors = [f"validator_exception:{type(exc).__name__}:{exc}"]
    return {"pdb_id": pdb_id, "errors": errors}


def _ensure_repair_namespace_compatible(
    root: Path,
    snapshot: E3RepairSnapshot,
    *,
    part_id: int,
    total_parts: int,
    expected_shard: list[str],
) -> None:
    """拒绝用不同 manifest、分片数或 ID 集覆盖已有 repair 状态。"""
    stage_dir = root / "reports" / "runs" / snapshot.repair_run_id / E3_REPAIR_STAGE
    expected_evidence = snapshot.evidence_fields()
    for path in sorted(stage_dir.glob("status.part_*_of_*.jsonl")):
        records = read_jsonl(path)
        if not records:
            raise RuntimeError(f"existing E3 repair status is empty: {path}")
        for record in records:
            if any(record.get(field) != value for field, value in expected_evidence.items()):
                raise RuntimeError(f"existing E3 repair status uses a different snapshot: {path}")
            if int(record.get("total_parts", -1)) != total_parts:
                raise RuntimeError(f"existing E3 repair status uses a different partition count: {path}")
        match = _STATUS_NAME_PATTERN.fullmatch(path.name)
        if match is None:
            raise RuntimeError(f"invalid E3 repair status filename: {path}")
        existing_part = int(match.group(1))
        declared_total = int(match.group(2))
        if declared_total != total_parts:
            raise RuntimeError(f"E3 repair status filename partition drift: {path}")
        expected_ids = set(shard_items(snapshot.target_ids, existing_part, total_parts))
        actual_ids = {str(record["pdb_id"]).lower() for record in records}
        if actual_ids != expected_ids:
            raise RuntimeError(f"existing E3 repair shard IDs drifted: {path}")
    if set(expected_shard) != set(shard_items(snapshot.target_ids, part_id, total_parts)):
        raise RuntimeError("internal E3 repair shard identity mismatch")


def _ensure_partition_contract(
    root: Path,
    snapshot: E3RepairSnapshot,
    *,
    total_parts: int,
) -> None:
    """首次原子冻结全局分片方案，阻止不同 total_parts 并发覆盖同一 PDB。"""
    stage_dir = root / "reports" / "runs" / snapshot.repair_run_id / E3_REPAIR_STAGE
    contract_path = stage_dir / "partition_contract.json"
    claim_path = stage_dir / "partition_contract.claim.json"
    shards = []
    for part_id in range(total_parts):
        shard = shard_items(snapshot.target_ids, part_id, total_parts)
        shards.append(
            {
                "part_id": part_id,
                "count": len(shard),
                "ids_sha256": sha256_named_values({"pdb_ids": shard}),
            }
        )
    contract = {
        "schema_version": 1,
        "run_id": snapshot.repair_run_id,
        "stage": E3_REPAIR_STAGE,
        "partition_policy": "parallel.shard_items_modulo_v1",
        "total_parts": total_parts,
        "shards": shards,
        **snapshot.evidence_fields(),
    }
    if contract_path.exists():
        _validate_partition_contract(contract_path, contract)
        return
    try:
        _create_exclusive_json(
            claim_path,
            {
                "schema_version": 1,
                "target": contract_path.name,
                "contract_sha256": sha256_named_values(contract),
            },
        )
    except FileExistsError as exc:
        if contract_path.exists():
            _validate_partition_contract(contract_path, contract)
            return
        raise RuntimeError(
            f"E3 partition contract claim exists without contract: {claim_path}; "
            "stale claims require process-evidence review before manual removal"
        ) from exc
    write_report(contract_path, contract)


def _validate_partition_contract(path: Path, expected: dict[str, Any]) -> None:
    """只接受与首次冻结分片方案语义完全相同的 namespace。"""
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"E3 partition contract is unreadable: {path}") from exc
    if actual != expected:
        raise RuntimeError(f"E3 partition contract drift: {path}")


def _validate_completed_shard(
    path: Path,
    snapshot: E3RepairSnapshot,
    *,
    part_id: int,
    total_parts: int,
    expected_shard: list[str],
) -> list[dict[str, Any]]:
    """验证已有完整 status 后幂等返回，绝不重复执行同一分片。"""
    records = read_jsonl(path)
    if not records:
        raise RuntimeError(f"existing E3 repair status is empty: {path}")
    expected_evidence = snapshot.evidence_fields()
    actual_ids = [str(record.get("pdb_id", "")).lower() for record in records]
    _validate_pdb_ids(actual_ids, source=str(path), reject_duplicates=True)
    if set(actual_ids) != set(expected_shard) or len(actual_ids) != len(expected_shard):
        raise RuntimeError(f"existing E3 repair shard IDs drifted: {path}")
    for record in records:
        if record.get("stage") != E3_REPAIR_STAGE:
            raise RuntimeError(f"existing E3 repair status stage drifted: {path}")
        if int(record.get("part_id", -1)) != part_id:
            raise RuntimeError(f"existing E3 repair status part_id drifted: {path}")
        if int(record.get("total_parts", -1)) != total_parts:
            raise RuntimeError(f"existing E3 repair status total_parts drifted: {path}")
        mismatched = [
            field
            for field, expected in expected_evidence.items()
            if record.get(field) != expected
        ]
        if mismatched:
            raise RuntimeError(
                f"existing E3 repair status uses a different snapshot: {path}: {mismatched}"
            )
    return records


def _validate_complete_partition_set(
    snapshot: E3RepairSnapshot,
    statuses: dict[str, dict[str, Any]],
    status_paths: list[Path],
) -> None:
    """验证 repair 状态由一套完整、无混用的 part 编号组成。"""
    totals = {int(record.get("total_parts", -1)) for record in statuses.values()}
    if len(totals) != 1:
        raise RuntimeError(f"E3 repair status mixes total_parts: {sorted(totals)}")
    total_parts = totals.pop()
    if total_parts <= 0:
        raise RuntimeError("E3 repair status has invalid total_parts")
    expected_names = {
        f"status.part_{part_id:04d}_of_{total_parts:04d}.jsonl"
        for part_id in range(total_parts)
    }
    actual_names = {path.name for path in status_paths}
    if actual_names != expected_names:
        raise RuntimeError(
            f"E3 repair status partition files disagree: missing={sorted(expected_names-actual_names)}, "
            f"extra={sorted(actual_names-expected_names)}"
        )
    for path in status_paths:
        match = _STATUS_NAME_PATTERN.fullmatch(path.name)
        if match is None:
            raise RuntimeError(f"invalid E3 repair status filename: {path}")
        part_id = int(match.group(1))
        declared_total = int(match.group(2))
        if declared_total != total_parts:
            raise RuntimeError(f"E3 repair status filename partition drift: {path}")
        expected_shard = shard_items(snapshot.target_ids, part_id, total_parts)
        _validate_completed_shard(
            path,
            snapshot,
            part_id=part_id,
            total_parts=total_parts,
            expected_shard=expected_shard,
        )


def _source_evidence_paths(root: Path, source_run_id: str) -> dict[str, Any]:
    """返回旧 Stage E 四类冻结证据的唯一规范路径。"""
    run_dir = root / "reports" / "runs" / source_run_id
    return {
        "pair_list": root / "raw" / "pair_list.jsonl",
        "status_paths": sorted(
            (run_dir / SOURCE_STAGE).glob("status.part_*_of_*.jsonl")
        ),
        "de_release": run_dir / "de_release" / "summary.json",
        "exclusion": run_dir / "exclusions.jsonl",
    }


def _publish_frozen_pair(
    *,
    target_ids_file: Path,
    target_ids_payload: bytes,
    target_manifest: Path,
    target_manifest_payload: bytes,
    manifest: dict[str, Any],
) -> None:
    """以 manifest-last 提交语义发布目标清单和冻结 manifest。"""
    if target_ids_file.resolve(strict=False) == target_manifest.resolve(strict=False):
        raise ValueError("E3 target IDs and manifest paths must be different")
    ids_exists = target_ids_file.exists()
    manifest_exists = target_manifest.exists()
    if ids_exists or manifest_exists:
        if not (ids_exists and manifest_exists):
            raise RuntimeError("incomplete existing E3 freeze outputs; refusing implicit repair")
        if target_ids_file.read_bytes() != target_ids_payload:
            raise RuntimeError("existing E3 target IDs differ byte-for-byte")
        try:
            existing_manifest = json.loads(target_manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError("existing E3 target manifest is unreadable") from exc
        if existing_manifest != manifest:
            raise RuntimeError("existing E3 target manifest differs semantically")
        return

    target_ids_file.parent.mkdir(parents=True, exist_ok=True)
    target_manifest.parent.mkdir(parents=True, exist_ok=True)
    nonce = f"{os.getpid()}.{uuid4().hex}"
    ids_tmp = target_ids_file.with_name(f".{target_ids_file.name}.tmp.{nonce}")
    manifest_tmp = target_manifest.with_name(f".{target_manifest.name}.tmp.{nonce}")
    ids_published = False
    try:
        _write_synced_bytes(ids_tmp, target_ids_payload)
        _write_synced_bytes(manifest_tmp, target_manifest_payload)
        if ids_tmp.read_bytes() != target_ids_payload:
            raise RuntimeError("temporary E3 target IDs failed read-back")
        if json.loads(manifest_tmp.read_text(encoding="utf-8")) != manifest:
            raise RuntimeError("temporary E3 target manifest failed semantic read-back")
        if target_ids_file.exists() or target_manifest.exists():
            raise RuntimeError("E3 freeze output appeared concurrently")
        atomic_replace(ids_tmp, target_ids_file)
        ids_published = True
        atomic_replace(manifest_tmp, target_manifest)
    except Exception:
        if ids_published and not target_manifest.exists():
            target_ids_file.unlink(missing_ok=True)
        raise
    finally:
        ids_tmp.unlink(missing_ok=True)
        manifest_tmp.unlink(missing_ok=True)


def _write_synced_bytes(path: Path, payload: bytes) -> None:
    """完整写入并 fsync 一份当前调用独占的临时文件。"""
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _create_exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    """以 O_EXCL 创建不可抢占 claim；失败不会遗留当前调用的半写文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


def _sha256_bytes(payload: bytes) -> str:
    """计算内存中确定性冻结载荷的 SHA-256。"""
    return hashlib.sha256(payload).hexdigest()


def _relative_path_identity(root: Path, path: Path) -> str:
    """把证据路径冻结为数据根内 POSIX 风格相对身份。"""
    root_resolved = root.resolve(strict=True)
    path_resolved = path.resolve(strict=False)
    try:
        relative = path_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"E3 evidence/output path must stay under root: {path}") from exc
    return str(relative).replace("\\", "/")


def _require_exact_output_path(path: Path, expected: Path, *, label: str) -> None:
    """强制冻结输出位于独立 repair run 的固定目录，避免污染旧正式 run。"""
    actual_resolved = path.resolve(strict=False)
    expected_resolved = expected.resolve(strict=False)
    if actual_resolved != expected_resolved:
        raise ValueError(
            f"{label} must use the isolated E3 freeze path: {expected_resolved}"
        )


def _require_manifest_path(
    manifest: dict[str, Any],
    field: str,
    root: Path,
    actual_path: Path,
) -> None:
    """验证 manifest 中一条相对路径身份指向当前规范路径。"""
    declared = manifest[field]
    if not isinstance(declared, str) or not declared:
        raise ValueError(f"{field} must be a non-empty relative path")
    actual = _relative_path_identity(root, actual_path)
    if declared != actual:
        raise RuntimeError(f"{field} identity drift: actual={actual}, expected={declared}")


def _require_sha256(path: Path, expected: str, *, label: str) -> str:
    """验证磁盘证据仍等于控制面冻结的 SHA-256。"""
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"{label} identity drift: actual={actual}, expected={expected}")
    return actual


def _read_frozen_ids(path: Path) -> list[str]:
    """按原行序读取目标 ID，并显式拒绝重复而不是静默去重。"""
    ids = [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    _validate_pdb_ids(ids, source=str(path), reject_duplicates=True)
    if not ids:
        raise ValueError(f"E3 target ID file is empty: {path}")
    return ids


def _validate_pdb_ids(ids: list[str], *, source: str, reject_duplicates: bool) -> None:
    """验证四字符字母数字 PDB id，并按调用方要求拒绝重复。"""
    invalid = sorted({pdb_id for pdb_id in ids if not re.fullmatch(r"[0-9a-z]{4}", pdb_id)})
    if invalid:
        raise ValueError(f"invalid PDB IDs in {source}: {invalid[:20]}")
    if reject_duplicates:
        duplicates = sorted(pdb_id for pdb_id, count in Counter(ids).items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate PDB IDs in {source}: {duplicates[:20]}")


def _stage_status_snapshot_sha256(root: Path, paths: list[Path]) -> str:
    """单分片保留文件 SHA，多分片使用相对路径到文件 SHA 的确定性组合。"""
    if not paths:
        raise RuntimeError("no source stage status files for E3 repair")
    if len(paths) == 1:
        return sha256_file(paths[0])
    return sha256_named_values(
        {
            str(path.relative_to(root)).replace("\\", "/"): sha256_file(path)
            for path in paths
        }
    )


def _normalize_sha256(value: Any, *, field: str) -> str:
    """把外部 SHA-256 规范为小写，并拒绝非 64 位十六进制。"""
    normalized = str(value).lower()
    if _SHA256_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field} must be a lowercase-compatible SHA-256")
    return normalized


def _manifest_sha256(manifest: dict[str, Any], field: str) -> str:
    """读取 manifest 内一个必需的 SHA-256 字段。"""
    return _normalize_sha256(manifest[field], field=field)


def _manifest_positive_int(manifest: dict[str, Any], field: str) -> int:
    """读取 manifest 内一个严格正整数计数字段。"""
    value = manifest[field]
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _write_immutable_report(path: Path, report: dict[str, Any]) -> None:
    """以独占 claim 串行化 release；重复运行只接受语义完全相同。"""
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != report:
            raise RuntimeError(f"immutable E3 release summary drift: {path}")
        return
    claim_path = path.with_name(f"{path.name}.claim.json")
    try:
        _create_exclusive_json(
            claim_path,
            {
                "schema_version": 1,
                "target": path.name,
                "report_sha256": sha256_named_values(report),
            },
        )
    except FileExistsError as exc:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != report:
                raise RuntimeError(f"immutable E3 release summary drift: {path}")
            return
        raise RuntimeError(
            f"E3 release claim exists without summary: {claim_path}; "
            "stale claims require process-evidence review before manual removal"
        ) from exc
    write_report(path, report)
