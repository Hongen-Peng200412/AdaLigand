# 学习导航：功能分区=调度、资源与恢复控制；生命周期=一次正式 run 的长尾截止审计。
# 主要输入：predecision/posttermination 证据、既有 exclusions.jsonl 与显式用户授权。
# 主要输出：不可变 before/after manifest、原子更新的 live manifest 与 cutoff summary。
# 关键边界：只追加 run-scoped 排除，不改通用 known-failure 分类，不手写 Stage E/F 状态。
"""把用户授权的 Stage E 长尾截止转换为可审计的 run-scoped exclusion manifest。"""

from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from exclusions import load_run_exclusions
from io_utils import atomic_replace, read_jsonl, sha256_file


CUTOFF_SCHEMA_VERSION = 1
CUTOFF_EVIDENCE_DIRNAME = "stage_e_long_tail_cutoff_20260713T195419"
CUTOFF_REASON = "user_authorized_stage_e_long_tail_cutoff"
CUTOFF_STAGES = ["stage_e", "stage_f"]


def apply_stage_e_long_tail_cutoff(
    root: Path,
    run_id: str,
    *,
    evidence_dir: Path,
    expected_predecision_sha256: str,
    expected_posttermination_sha256: str,
    expected_before_manifest_sha256: str,
    expected_existing_ids: set[str],
    expected_supplement_job_id: int,
    expected_authorization: str,
) -> dict[str, Any]:
    """
    追加截止时仍未完成的 PDB，并冻结本次 run 的 before/after 审计链。

    输入参数:
        - root: Path，AdaLigand 数据根
        - run_id: str，唯一正式 run id
        - evidence_dir: Path，已由截止现场取证创建的目录
        - expected_*: 显式冻结的证据 SHA、既有排除集合、Job ID 与用户授权

    输出:
        - summary: dict，本次追加的稳定摘要；重复调用只验证并返回同一结果

    说明:
        本函数不推断哪些失败应成为通用 known failure。它只消费已经结束的截止证据，
        追加 ``current_run_only`` 决策，并让正式 E/F 入口按既有公共适配层写终态。
    """
    predecision_path = evidence_dir / "predecision.json"
    posttermination_path = evidence_dir / "posttermination.json"
    live_manifest = root / "reports" / "runs" / run_id / "exclusions.jsonl"
    before_path = evidence_dir / "exclusions.before.jsonl"
    after_path = evidence_dir / "exclusions.after.jsonl"
    summary_path = evidence_dir / "summary.json"

    _require_sha256(predecision_path, expected_predecision_sha256)
    _require_sha256(posttermination_path, expected_posttermination_sha256)
    _require_regular_file(live_manifest)
    predecision = _read_object(predecision_path)
    posttermination = _read_object(posttermination_path)
    _validate_cutoff_evidence(
        predecision,
        posttermination,
        run_id=run_id,
        expected_predecision_sha256=expected_predecision_sha256,
        expected_job_id=expected_supplement_job_id,
        expected_authorization=expected_authorization,
    )

    existing_by_id, live_sha256 = load_run_exclusions(root, run_id, "stage_e")
    if live_sha256 not in {expected_before_manifest_sha256, _existing_after_sha(after_path)}:
        raise RuntimeError("live exclusion manifest is neither the frozen before nor audited after state")
    if set(existing_by_id) not in (expected_existing_ids, expected_existing_ids | set(predecision["deadline_excluded_ids"])):
        raise RuntimeError(f"unexpected live exclusion IDs: {sorted(existing_by_id)}")

    if before_path.exists():
        _require_sha256(before_path, expected_before_manifest_sha256)
    else:
        if live_sha256 != expected_before_manifest_sha256:
            raise RuntimeError("cannot create before snapshot from a post-transition live manifest")
        _write_immutable(before_path, live_manifest.read_bytes())

    base_records = {
        str(record["pdb_id"]).lower(): record
        for record in read_jsonl(before_path)
    }
    added_records = _build_cutoff_records(
        predecision,
        posttermination,
        run_id=run_id,
        predecision_path=predecision_path,
        predecision_sha256=expected_predecision_sha256,
        posttermination_path=posttermination_path,
        posttermination_sha256=expected_posttermination_sha256,
    )
    final_by_id = {**base_records, **added_records}
    after_bytes = _encode_jsonl(final_by_id[pdb_id] for pdb_id in sorted(final_by_id))
    after_sha256 = _sha256_bytes(after_bytes)
    _write_immutable(after_path, after_bytes)

    current_sha256 = sha256_file(live_manifest)
    if current_sha256 == expected_before_manifest_sha256:
        _atomic_write(live_manifest, after_bytes)
    elif current_sha256 != after_sha256:
        raise RuntimeError("live exclusion manifest changed outside the audited cutoff transition")

    for stage in CUTOFF_STAGES:
        exclusions, digest = load_run_exclusions(root, run_id, stage)
        if set(exclusions) != set(final_by_id) or digest != after_sha256:
            raise RuntimeError(f"post-cutoff {stage} exclusion verification failed")

    summary = {
        "schema_version": CUTOFF_SCHEMA_VERSION,
        "status": "success",
        "event": "stage_e_user_authorized_long_tail_cutoff_release",
        "run_id": run_id,
        "authorization": expected_authorization,
        "decision_scope": "current_run_only",
        "supplement_job_id": expected_supplement_job_id,
        "deadline": predecision["deadline"],
        "predecision_path": str(predecision_path),
        "predecision_sha256": expected_predecision_sha256,
        "posttermination_path": str(posttermination_path),
        "posttermination_sha256": expected_posttermination_sha256,
        "before_manifest_path": str(before_path),
        "before_manifest_sha256": expected_before_manifest_sha256,
        "after_manifest_path": str(after_path),
        "after_manifest_sha256": after_sha256,
        "existing_exclusion_ids": sorted(expected_existing_ids),
        "candidate_completed_ids": list(predecision["candidate_completed_ids"]),
        "added_exclusion_ids": sorted(added_records),
        "final_exclusion_ids": sorted(final_by_id),
        "policy": "run-only E/F exclusion; formal Stage E revalidates all non-excluded artifacts",
    }
    summary_bytes = _encode_json(summary)
    _write_immutable(summary_path, summary_bytes)
    if _read_object(summary_path) != summary:
        raise RuntimeError("cutoff summary verification failed")
    return summary


def _validate_cutoff_evidence(
    predecision: dict[str, Any],
    posttermination: dict[str, Any],
    *,
    run_id: str,
    expected_predecision_sha256: str,
    expected_job_id: int,
    expected_authorization: str,
) -> None:
    """验证截止前后证据的身份、时间、分区与进程终止闭环。"""
    if predecision.get("schema_version") != CUTOFF_SCHEMA_VERSION:
        raise RuntimeError("unsupported predecision schema")
    if posttermination.get("schema_version") != CUTOFF_SCHEMA_VERSION:
        raise RuntimeError("unsupported posttermination schema")
    if predecision.get("event") != "stage_e_user_authorized_long_tail_cutoff_predecision":
        raise RuntimeError("unexpected predecision event")
    if posttermination.get("event") != "stage_e_user_authorized_long_tail_cutoff_posttermination":
        raise RuntimeError("unexpected posttermination event")
    for record in (predecision, posttermination):
        if record.get("formal_run_id") != run_id:
            raise RuntimeError("cutoff evidence belongs to another run")
        if record.get("supplement_job_id") != expected_job_id:
            raise RuntimeError("cutoff evidence belongs to another supplement job")
        if record.get("authorization") != expected_authorization:
            raise RuntimeError("cutoff authorization mismatch")
        if record.get("decision_scope") != "current_run_only":
            raise RuntimeError("cutoff evidence is not run-scoped")
    if posttermination.get("predecision_sha256") != expected_predecision_sha256:
        raise RuntimeError("posttermination does not bind the frozen predecision")
    if posttermination.get("deadline") != predecision.get("deadline"):
        raise RuntimeError("cutoff deadline drift")
    if posttermination.get("candidate_completed_ids") != predecision.get("candidate_completed_ids"):
        raise RuntimeError("completed partition drift")
    if posttermination.get("deadline_excluded_ids") != predecision.get("deadline_excluded_ids"):
        raise RuntimeError("excluded partition drift")

    frozen_ids = _validate_pdb_ids(predecision.get("frozen_ids"), "frozen_ids")
    completed_ids = _validate_pdb_ids(predecision.get("candidate_completed_ids"), "candidate_completed_ids")
    excluded_ids = _validate_pdb_ids(predecision.get("deadline_excluded_ids"), "deadline_excluded_ids")
    if not excluded_ids:
        raise RuntimeError("cutoff release requires at least one deadline exclusion")
    if completed_ids & excluded_ids or completed_ids | excluded_ids != frozen_ids:
        raise RuntimeError("cutoff completed/excluded partition is not exact")
    observed_at = datetime.fromisoformat(str(predecision["observed_at"]))
    deadline = datetime.fromisoformat(str(predecision["deadline"]))
    if observed_at < deadline:
        raise RuntimeError("cutoff predecision predates the authorized deadline")
    if not str(posttermination.get("process_audit", "")).startswith("zero_remaining"):
        raise RuntimeError("posttermination does not prove zero remaining processes")
    if "exact kill_lock_316415" not in str(posttermination.get("termination", "")):
        raise RuntimeError("posttermination does not record the exact lock transition")


def _build_cutoff_records(
    predecision: dict[str, Any],
    posttermination: dict[str, Any],
    *,
    run_id: str,
    predecision_path: Path,
    predecision_sha256: str,
    posttermination_path: Path,
    posttermination_sha256: str,
) -> dict[str, dict[str, Any]]:
    """为实际未完成子集构造公共 exclusion schema v1 记录。"""
    records: dict[str, dict[str, Any]] = {}
    for pdb_id in sorted(predecision["deadline_excluded_ids"]):
        public_state = predecision["artifact_state"][pdb_id]["public"]
        if public_state["sim.npz"]["exists"] or public_state["ligand_area.npz"]["exists"]:
            raise RuntimeError(f"deadline-excluded sample already had a complete promoted artifact: {pdb_id}")
        evidence = {
            "deadline": predecision["deadline"],
            "observed_at": predecision["observed_at"],
            "supplement_job_id": predecision["supplement_job_id"],
            "supplement_run_id": predecision["supplement_run_id"],
            "configured_timeout_seconds": predecision["configured_timeout_seconds"],
            "public_artifacts_at_cutoff": public_state,
            "complete_artifact_trio": False,
            "termination": posttermination["termination"],
            "predecision_path": str(predecision_path),
            "predecision_sha256": predecision_sha256,
            "posttermination_path": str(posttermination_path),
            "posttermination_sha256": posttermination_sha256,
        }
        records[pdb_id] = {
            "schema_version": 1,
            "pdb_id": pdb_id,
            "run_id": run_id,
            "stages": list(CUTOFF_STAGES),
            "reason": CUTOFF_REASON,
            "detail": (
                f"At the authorized Stage E deadline {predecision['deadline']}, {pdb_id} "
                "still lacked the complete promoted sim.npz/ligand_area.npz artifact trio; "
                "the user authorized a current-run-only long-tail cutoff."
            ),
            "authorization": predecision["authorization"],
            "decision_scope": "current_run_only",
            "downstream_policy": "exclude_from_training_and_inference",
            "evidence": evidence,
        }
    return records


def _validate_pdb_ids(value: Any, field: str) -> set[str]:
    """读取有序唯一 PDB ID 列表，并拒绝任何隐式字符串转换。"""
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"{field} must be a non-empty list")
    if any(not isinstance(item, str) or not re.fullmatch(r"[0-9a-z]{4}", item) for item in value):
        raise RuntimeError(f"{field} contains an invalid PDB ID")
    if len(value) != len(set(value)):
        raise RuntimeError(f"{field} contains duplicates")
    return set(value)


def _existing_after_sha(path: Path) -> str:
    """返回已存在 after manifest 的 SHA；尚未生成时返回空字符串。"""
    if not path.exists():
        return ""
    _require_regular_file(path)
    return sha256_file(path)


def _read_object(path: Path) -> dict[str, Any]:
    """读取普通 JSON 文件并要求顶层对象。"""
    _require_regular_file(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _require_regular_file(path: Path) -> None:
    """拒绝缺失、目录和 symlink 证据。"""
    if not path.is_file() or path.is_symlink():
        raise RuntimeError(f"expected regular non-symlink file: {path}")


def _require_sha256(path: Path, expected: str) -> None:
    """验证证据文件的冻结 SHA-256。"""
    _require_regular_file(path)
    if sha256_file(path) != expected:
        raise RuntimeError(f"SHA-256 mismatch: {path}")


def _encode_jsonl(records: Any) -> bytes:
    """按稳定键序编码 JSONL。"""
    return b"".join(
        (
            json.dumps(
                record,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        for record in records
    )


def _encode_json(record: dict[str, Any]) -> bytes:
    """按稳定格式编码单个 JSON 对象。"""
    return (json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    """计算内存中小型审计文件的 SHA-256。"""
    import hashlib

    return hashlib.sha256(payload).hexdigest()


def _write_immutable(path: Path, payload: bytes) -> None:
    """首次原子写入；重复执行只接受逐字节一致内容。"""
    if path.exists():
        _require_regular_file(path)
        if path.read_bytes() != payload:
            raise RuntimeError(f"immutable audit file drift: {path}")
        return
    _atomic_write(path, payload)


def _atomic_write(path: Path, payload: bytes) -> None:
    """在同目录写普通临时文件后原子替换目标。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid4().hex}")
    temporary.write_bytes(payload)
    os.chmod(temporary, 0o644)
    atomic_replace(temporary, path)
