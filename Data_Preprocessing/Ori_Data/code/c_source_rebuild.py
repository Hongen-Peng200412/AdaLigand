"""经单次授权的 Stage C ligand-side source rebuild 审计与可恢复提交。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any

import numpy as np

from c_source_repair import (
    SourceRepairError,
    audit_stage_c_source,
    verify_audit_inputs_unchanged,
)
from contracts import (
    compare_receptor_base_arrays,
    load_npz_arrays,
    validate_stage_c_payload,
)
from io_utils import (
    atomic_replace,
    atomic_save_npz,
    file_lock,
    read_jsonl,
    safe_object_filename,
    sha256_file,
    write_jsonl,
)
from parse import build_stage_c_source_view
from receptor import build_receptor_arrays
from reports import write_report


SOURCE_REBUILD_SCHEMA_VERSION = 1
_AUTHORIZED_LIGAND_DRIFT_REASONS = frozenset({
    "occurrences_changed",
    "ligand_coords_keys_changed",
    "failed_occurrences_changed",
})
_ARTIFACT_FILENAMES = {
    "occurrences": "occurrences.jsonl",
    "ligand_coords": "ligand_coords.npz",
    "receptor": "receptor_tokens.npz",
    "report": "report.json",
}
_RECEPTOR_KEYS = (
    "coords",
    "element",
    "res_type",
    "is_backbone",
    "atom_name",
    "res_index",
    "chain_index",
    "bond_index",
    "bond_type",
    "feat",
)


class SourceRebuildError(RuntimeError):
    """专用 full-rebuild audit、stage 或 transaction 不满足冻结契约时抛出。"""


def prepare_stage_c_source_rebuild(
    root: Path,
    pdb_id: str,
    evidence_dir: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    审计一个已授权 PDB，并把当前 source 的完整 Stage C 四件套写入证据区。

    输入参数:
        - root: Path, Stage root
        - pdb_id: str, 已由外层冻结 ID 文件授权的 PDB id
        - evidence_dir: Path, 当前 repair run 的 `stage_c_source_rebuild` 目录

    输出:
        - result: tuple[dict,list[dict]], 包含:
            - record: dict[str,Any], 输入/依赖、before/after artifact 哈希与迁移计数
            - migration_rows: list[dict[str,Any]], run-scoped before/after 主键审计行
    """
    normalized_id = pdb_id.lower()
    base_audit = audit_stage_c_source(root, normalized_id)
    _validate_authorized_base_audit(base_audit)

    canonical_paths = canonical_stage_c_paths(root, normalized_id)
    old_occurrences = read_jsonl(canonical_paths["occurrences"])
    old_coords = load_npz_arrays(canonical_paths["ligand_coords"], allow_pickle=False)
    old_receptor = load_npz_arrays(canonical_paths["receptor"], allow_pickle=False)
    view = build_stage_c_source_view(root, normalized_id, materialize_objects=False)
    current_receptor = build_receptor_arrays(
        view.receptor_atoms,
        view.struct_conns,
        root / "raw" / "ccd_cache",
        allow_ccd_fetch=False,
    )
    _validate_receptor_unchanged(old_receptor, current_receptor, normalized_id)
    validation = validate_stage_c_payload(
        root,
        view.occurrences,
        view.ligand_coords,
        current_receptor,
    )
    if validation:
        raise SourceRebuildError(
            f"staged Stage C payload is invalid for {normalized_id}: {validation}"
        )
    if view.report.get("status") != "ok":
        raise SourceRebuildError(
            f"current Stage C report is not ok for {normalized_id}: {view.report.get('status')}"
        )

    descriptor_files = _descriptor_dependency_hashes(root, view.occurrences)
    migration_rows, migration_counts = build_primary_key_migration(
        normalized_id,
        old_occurrences,
        old_coords,
        view.occurrences,
        view.ligand_coords,
    )
    stage_paths = staged_artifact_paths(evidence_dir, normalized_id)
    write_jsonl(stage_paths["occurrences"], view.occurrences)
    atomic_save_npz(stage_paths["ligand_coords"], **view.ligand_coords)
    # 本轮专用迁移严格为 ligand-side-only：受体十个契约数组验证一致后，
    # 逐字节保留 canonical receptor，避免重序列化或丢失额外 provenance/future key。
    _atomic_copy(canonical_paths["receptor"], stage_paths["receptor"])
    write_report(stage_paths["report"], view.report)
    stage_hashes = _artifact_hashes(stage_paths)
    if stage_hashes["receptor"] != sha256_file(canonical_paths["receptor"]):
        raise SourceRebuildError(
            f"full rebuild receptor bytes changed for {normalized_id}"
        )
    _verify_staged_payload(root, stage_paths, view.occurrences)

    # prepare 的最后一步重新核对 canonical 输入与依赖；此后 summary 会冻结 stage 哈希。
    verify_audit_inputs_unchanged(root, base_audit)
    _verify_named_dependencies(root, descriptor_files)
    record = {
        "pdb_id": normalized_id,
        "classification": "full_rebuild_ready",
        "base_audit": base_audit,
        "before_artifact_sha256": _artifact_hashes(canonical_paths),
        "staged_artifact_sha256": stage_hashes,
        "descriptor_files": descriptor_files,
        "descriptor_manifest_sha256": _named_hash_manifest(descriptor_files),
        "migration_counts": migration_counts,
        "n_old_occurrences": len(old_occurrences),
        "n_current_occurrences": len(view.occurrences),
        "schema_version": SOURCE_REBUILD_SCHEMA_VERSION,
    }
    return record, migration_rows


def build_primary_key_migration(
    pdb_id: str,
    old_occurrences: list[dict[str, Any]],
    old_coords: dict[str, np.ndarray],
    current_occurrences: list[dict[str, Any]],
    current_coords: dict[str, np.ndarray],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """
    构造本次 source snapshot 的 occurrence before/after 主键迁移证据。

    输入参数:
        - pdb_id: str, 小写 PDB id
        - old_occurrences: list[dict[str,Any]], 迁移前 occurrence
        - old_coords: dict[str,np.ndarray], 迁移前 ligand coords/present/centroid 数组
        - current_occurrences: list[dict[str,Any]], 当前 source dry-build occurrence
        - current_coords: dict[str,np.ndarray], 当前 source ligand coords/present/centroid 数组

    输出:
        - result: tuple[list[dict],dict[str,int]], 包含:
            - rows: list[dict], 按 locator SHA 排序的 unchanged/reassigned/added/removed 行
            - counts: dict[str,int], 四种迁移状态的精确计数
    """
    old_by_locator = _occurrences_by_locator(old_occurrences, "old")
    current_by_locator = _occurrences_by_locator(current_occurrences, "current")
    rows: list[dict[str, Any]] = []
    counts = {"unchanged": 0, "reassigned": 0, "added": 0, "removed": 0}
    for locator_sha256 in sorted(set(old_by_locator) | set(current_by_locator)):
        old_item = old_by_locator.get(locator_sha256)
        current_item = current_by_locator.get(locator_sha256)
        if old_item is None:
            status = "added"
        elif current_item is None:
            status = "removed"
        else:
            if _semantic_payload(old_item) != _semantic_payload(current_item):
                raise SourceRebuildError(
                    f"matched occurrence semantics changed for {pdb_id}:{locator_sha256}"
                )
            old_id = int(old_item["candidate_id"])
            current_id = int(current_item["candidate_id"])
            _require_matched_arrays_equal(
                pdb_id,
                locator_sha256,
                old_coords,
                old_id,
                current_coords,
                current_id,
            )
            status = "unchanged" if old_id == current_id else "reassigned"
        counts[status] += 1
        reference = current_item if current_item is not None else old_item
        rows.append({
            "pdb_id": pdb_id,
            "status": status,
            "locator_sha256": locator_sha256,
            "components": reference.get("components", []),
            "inter_bonds": reference.get("inter_bonds", []),
            "object_key": reference.get("object_key"),
            "old_candidate_id": None if old_item is None else int(old_item["candidate_id"]),
            "new_candidate_id": (
                None if current_item is None else int(current_item["candidate_id"])
            ),
            "semantic_sha256": _json_sha256(_semantic_payload(reference)),
            "old_coords_sha256": _candidate_array_hash(old_coords, old_item, "coords"),
            "new_coords_sha256": _candidate_array_hash(
                current_coords,
                current_item,
                "coords",
            ),
            "old_present_sha256": _candidate_array_hash(old_coords, old_item, "present"),
            "new_present_sha256": _candidate_array_hash(
                current_coords,
                current_item,
                "present",
            ),
            "schema_version": SOURCE_REBUILD_SCHEMA_VERSION,
        })
    return rows, counts


def apply_prepared_source_rebuilds(
    root: Path,
    evidence_dir: Path,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    对全部 prepared PDB 做二次全局 CAS，再逐 PDB 可恢复地提交四件套。

    输入参数:
        - root: Path, Stage root
        - evidence_dir: Path, 已冻结 audit/staging/backup/transaction 的证据目录
        - records: list[dict[str,Any]], 同一份成功 audit summary 对应的全部记录

    输出:
        - results: list[dict[str,Any]], 每个 PDB 的 committed/already_committed 结果
    """
    ordered = sorted(records, key=lambda item: str(item["pdb_id"]))
    for record in ordered:
        _verify_prepared_record(root, evidence_dir, record)
    for record in ordered:
        _ensure_before_backup(root, evidence_dir, record)
    # 所有 backup 完成后再做第二次全局 source/dependency CAS，随后才允许首个 commit。
    for record in ordered:
        _verify_external_inputs(root, record)
        _validate_recoverable_state(root, evidence_dir, record)

    results = []
    for record in ordered:
        results.append(_commit_one_rebuild(root, evidence_dir, record))
    return results


def canonical_stage_c_paths(root: Path, pdb_id: str) -> dict[str, Path]:
    """返回 full rebuild 管理的 canonical Stage C 四件套路径。"""
    parse_dir = root / "parse" / pdb_id
    return {
        "occurrences": parse_dir / "occurrences.jsonl",
        "ligand_coords": parse_dir / "ligand_coords.npz",
        "receptor": parse_dir / "receptor_tokens.npz",
        "report": root / "reports" / f"{pdb_id}.json",
    }


def staged_artifact_paths(evidence_dir: Path, pdb_id: str) -> dict[str, Path]:
    """返回 run-scoped staging 中的四件套路径。"""
    base = evidence_dir / "staging" / pdb_id
    return {key: base / name for key, name in _ARTIFACT_FILENAMES.items()}


def _validate_authorized_base_audit(record: dict[str, Any]) -> None:
    """只接受已知的 ligand-side 三类漂移，拒绝把专用路径扩张为通用 rebuild。"""
    if record.get("classification") != "blocked":
        raise SourceRebuildError(
            f"authorized full rebuild expected blocked base audit for {record.get('pdb_id')}"
        )
    reasons = set(record.get("reasons", []))
    if reasons != _AUTHORIZED_LIGAND_DRIFT_REASONS:
        raise SourceRebuildError(
            f"unexpected full rebuild reasons for {record.get('pdb_id')}: {sorted(reasons)}"
        )
    if record.get("receptor_mismatch_reasons"):
        raise SourceRebuildError(
            f"full rebuild would change receptor base for {record.get('pdb_id')}"
        )
    if record.get("receptor_derived_mismatch_reasons"):
        raise SourceRebuildError(
            f"full rebuild would change receptor derived arrays for {record.get('pdb_id')}"
        )


def _validate_receptor_unchanged(
    old_receptor: dict[str, np.ndarray],
    current_receptor: dict[str, np.ndarray],
    pdb_id: str,
) -> None:
    """完整 C rebuild 只允许 ligand-side 变化，receptor 十个当前契约数组必须逐位不变。"""
    base_mismatch = compare_receptor_base_arrays(old_receptor, current_receptor)
    changed = list(base_mismatch)
    for key in _RECEPTOR_KEYS[7:]:
        if key not in old_receptor or key not in current_receptor:
            changed.append(f"receptor_missing:{key}")
        elif not _arrays_equal(old_receptor[key], current_receptor[key]):
            changed.append(f"receptor_changed:{key}")
    if changed:
        raise SourceRebuildError(f"full rebuild receptor drift for {pdb_id}: {changed}")


def _occurrences_by_locator(
    occurrences: list[dict[str, Any]],
    side: str,
) -> dict[str, dict[str, Any]]:
    """按仅用于本次审计的 residue/inter-bond locator 建立唯一 occurrence 映射。"""
    result: dict[str, dict[str, Any]] = {}
    for occurrence in occurrences:
        locator = {
            "pdb_id": str(occurrence.get("pdb_id", "")).lower(),
            "components": occurrence.get("components", []),
            "inter_bonds": occurrence.get("inter_bonds", []),
        }
        digest = _json_sha256(locator)
        if digest in result:
            raise SourceRebuildError(
                f"{side} occurrence locator collision: {locator['pdb_id']}:{digest}"
            )
        result[digest] = occurrence
    return result


def _semantic_payload(occurrence: dict[str, Any]) -> dict[str, Any]:
    """返回去掉 snapshot 派生 `candidate_id` 后的完整 occurrence 科学语义。"""
    return {key: value for key, value in occurrence.items() if key != "candidate_id"}


def _require_matched_arrays_equal(
    pdb_id: str,
    locator_sha256: str,
    old_arrays: dict[str, np.ndarray],
    old_candidate_id: int,
    current_arrays: dict[str, np.ndarray],
    current_candidate_id: int,
) -> None:
    """要求匹配 occurrence 的 coords/present/centroid 在主键迁移前后逐位相同。"""
    for prefix in ("coords", "present", "centroid_atom"):
        old_key = f"{prefix}_{old_candidate_id}"
        current_key = f"{prefix}_{current_candidate_id}"
        if old_key not in old_arrays or current_key not in current_arrays:
            raise SourceRebuildError(
                f"matched occurrence array missing for {pdb_id}:{locator_sha256}:{prefix}"
            )
        if _array_sha256(old_arrays[old_key]) != _array_sha256(
            current_arrays[current_key]
        ):
            raise SourceRebuildError(
                f"matched occurrence {prefix} changed for {pdb_id}:{locator_sha256}"
            )


def _candidate_array_hash(
    arrays: dict[str, np.ndarray],
    occurrence: dict[str, Any] | None,
    prefix: str,
) -> str | None:
    """返回 occurrence 对应 coords/present 数组的 dtype/shape/value 稳定哈希。"""
    if occurrence is None:
        return None
    key = f"{prefix}_{int(occurrence['candidate_id'])}"
    return _array_sha256(arrays[key])


def _descriptor_dependency_hashes(
    root: Path,
    occurrences: list[dict[str, Any]],
) -> dict[str, str]:
    """冻结当前成功 occurrence 引用的去重 ligand descriptor。"""
    paths = {
        root / "ligand_descriptors" / f"{safe_object_filename(str(item['object_key']))}.npz"
        for item in occurrences
    }
    missing = sorted(str(path) for path in paths if not path.is_file())
    if missing:
        raise SourceRebuildError(f"full rebuild descriptor dependency missing: {missing[:10]}")
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(paths, key=lambda item: item.as_posix())
    }


def _verify_staged_payload(
    root: Path,
    stage_paths: dict[str, Path],
    expected_occurrences: list[dict[str, Any]],
) -> None:
    """从 staging 文件重新读取并验证四件套，避免只验证写入前内存对象。"""
    occurrences = read_jsonl(stage_paths["occurrences"])
    coords = load_npz_arrays(stage_paths["ligand_coords"], allow_pickle=False)
    receptor = load_npz_arrays(stage_paths["receptor"], allow_pickle=False)
    report = json.loads(stage_paths["report"].read_text(encoding="utf-8"))
    if occurrences != expected_occurrences:
        raise SourceRebuildError("staged occurrences differ from prepared source view")
    validation = validate_stage_c_payload(root, occurrences, coords, receptor)
    if validation:
        raise SourceRebuildError(f"staged Stage C files failed validation: {validation}")
    if report.get("status") != "ok" or report.get("pdb_id") != occurrences[0].get("pdb_id"):
        raise SourceRebuildError("staged Stage C report identity/status mismatch")


def _verify_prepared_record(
    root: Path,
    evidence_dir: Path,
    record: dict[str, Any],
) -> None:
    """在 apply 前验证 record、staging、外部依赖与 canonical 可恢复状态。"""
    if record.get("classification") != "full_rebuild_ready":
        raise SourceRebuildError(f"record is not rebuild-ready: {record.get('pdb_id')}")
    pdb_id = str(record["pdb_id"])
    stage_paths = staged_artifact_paths(evidence_dir, pdb_id)
    if _artifact_hashes(stage_paths) != record.get("staged_artifact_sha256"):
        raise SourceRebuildError(f"staged artifacts changed for {pdb_id}")
    _verify_external_inputs(root, record)
    state = _canonical_state(root, record)
    if state == "before":
        verify_audit_inputs_unchanged(root, record["base_audit"])
    elif state == "after":
        transaction = _read_transaction(evidence_dir, pdb_id)
        if transaction.get("state") not in {"committing", "committed"}:
            raise SourceRebuildError(f"unreceipted after-state for {pdb_id}")
    elif state != "mixed":
        raise SourceRebuildError(f"unknown canonical artifact state for {pdb_id}: {state}")


def _verify_external_inputs(root: Path, record: dict[str, Any]) -> None:
    """复核 mmCIF、CCD/LigandObject 与 descriptor；不把可迁移四件套误当外部输入。"""
    base = record["base_audit"]
    mmcif_path = root / "raw" / "rcsb_mmcif" / f"{record['pdb_id']}.cif"
    changed = []
    if sha256_file(mmcif_path) != base.get("mmcif_sha256"):
        changed.append("mmcif_sha256")
    changed.extend(_changed_named_dependencies(root, base["dependency_files"]))
    changed.extend(_changed_named_dependencies(root, record["descriptor_files"]))
    if _named_hash_manifest(record["descriptor_files"]) != record.get(
        "descriptor_manifest_sha256"
    ):
        changed.append("descriptor_manifest_sha256")
    if changed:
        raise SourceRebuildError(
            f"full rebuild external inputs changed for {record['pdb_id']}: "
            f"{sorted(set(changed))}"
        )


def _ensure_before_backup(
    root: Path,
    evidence_dir: Path,
    record: dict[str, Any],
) -> None:
    """在任何 canonical commit 前为一个 PDB 创建并验证完整 before 四件套。"""
    pdb_id = str(record["pdb_id"])
    backup_paths = _backup_artifact_paths(evidence_dir, pdb_id)
    if all(path.is_file() for path in backup_paths.values()):
        if _artifact_hashes(backup_paths) != record["before_artifact_sha256"]:
            raise SourceRebuildError(f"before backup changed for {pdb_id}")
        return
    if _canonical_state(root, record) != "before":
        raise SourceRebuildError(f"cannot create backup outside before-state for {pdb_id}")
    canonical = canonical_stage_c_paths(root, pdb_id)
    for key in _ARTIFACT_FILENAMES:
        if backup_paths[key].is_file():
            if sha256_file(backup_paths[key]) != record["before_artifact_sha256"][key]:
                raise SourceRebuildError(f"partial before backup changed for {pdb_id}:{key}")
            continue
        _atomic_copy(canonical[key], backup_paths[key])
    if _artifact_hashes(backup_paths) != record["before_artifact_sha256"]:
        raise SourceRebuildError(f"before backup verification failed for {pdb_id}")


def _validate_recoverable_state(
    root: Path,
    evidence_dir: Path,
    record: dict[str, Any],
) -> None:
    """第二次全局 CAS 只接受 before、已收据 after 或有 committing journal 的 mixed。"""
    pdb_id = str(record["pdb_id"])
    state = _canonical_state(root, record)
    transaction = _read_transaction(evidence_dir, pdb_id)
    if state == "before":
        return
    if state == "after" and transaction.get("state") in {"committing", "committed"}:
        return
    if state == "mixed" and transaction.get("state") == "committing":
        return
    raise SourceRebuildError(
        f"canonical state is not recoverable for {pdb_id}: {state}/{transaction.get('state')}"
    )


def _commit_one_rebuild(
    root: Path,
    evidence_dir: Path,
    record: dict[str, Any],
) -> dict[str, Any]:
    """在单 PDB 锁内恢复可能的中断状态，并提交已冻结 staging 四件套。"""
    pdb_id = str(record["pdb_id"])
    lock_path = root / "reports" / "locks" / "stage_c_source_rebuild" / f"{pdb_id}.lock"
    with file_lock(lock_path):
        state = _canonical_state(root, record)
        transaction = _read_transaction(evidence_dir, pdb_id)
        if state == "after" and transaction.get("state") == "committed":
            return {
                "pdb_id": pdb_id,
                "action": "already_committed",
                "after_artifact_sha256": record["staged_artifact_sha256"],
            }
        if state == "after" and transaction.get("state") == "committing":
            _write_transaction(evidence_dir, record, "committed")
            return {
                "pdb_id": pdb_id,
                "action": "committed_after_receipt_recovery",
                "after_artifact_sha256": record["staged_artifact_sha256"],
            }
        if state == "mixed" and transaction.get("state") == "committing":
            _restore_before(root, evidence_dir, record)
            state = "before"
        if state != "before":
            raise SourceRebuildError(f"refusing commit from {state} state for {pdb_id}")

        _verify_external_inputs(root, record)
        _write_transaction(evidence_dir, record, "committing")
        try:
            canonical = canonical_stage_c_paths(root, pdb_id)
            stage = staged_artifact_paths(evidence_dir, pdb_id)
            for key in _ARTIFACT_FILENAMES:
                _atomic_copy(stage[key], canonical[key])
            if _canonical_state(root, record) != "after":
                raise SourceRebuildError(f"after artifact verification failed for {pdb_id}")
        except BaseException:
            _restore_before(root, evidence_dir, record)
            _write_transaction(evidence_dir, record, "rolled_back")
            raise
        _write_transaction(evidence_dir, record, "committed")
        return {
            "pdb_id": pdb_id,
            "action": "committed",
            "after_artifact_sha256": record["staged_artifact_sha256"],
        }


def _restore_before(root: Path, evidence_dir: Path, record: dict[str, Any]) -> None:
    """从已验证 backup 原子恢复一个 PDB 的完整 before 四件套。"""
    pdb_id = str(record["pdb_id"])
    canonical = canonical_stage_c_paths(root, pdb_id)
    backup = _backup_artifact_paths(evidence_dir, pdb_id)
    if _artifact_hashes(backup) != record["before_artifact_sha256"]:
        raise SourceRebuildError(f"cannot restore invalid before backup for {pdb_id}")
    for key in _ARTIFACT_FILENAMES:
        _atomic_copy(backup[key], canonical[key])
    if _canonical_state(root, record) != "before":
        raise SourceRebuildError(f"before restore verification failed for {pdb_id}")


def _canonical_state(root: Path, record: dict[str, Any]) -> str:
    """把 canonical 四件套归类为全 before、全 after、mixed 或 unknown。"""
    current = _artifact_hashes(canonical_stage_c_paths(root, str(record["pdb_id"])))
    before = record["before_artifact_sha256"]
    after = record["staged_artifact_sha256"]
    if current == before:
        return "before"
    if current == after:
        return "after"
    per_file_known = all(current[key] in {before[key], after[key]} for key in current)
    return "mixed" if per_file_known else "unknown"


def _backup_artifact_paths(evidence_dir: Path, pdb_id: str) -> dict[str, Path]:
    """返回 run-scoped before backup 四件套路径。"""
    base = evidence_dir / "backups" / pdb_id
    return {key: base / name for key, name in _ARTIFACT_FILENAMES.items()}


def _transaction_path(evidence_dir: Path, pdb_id: str) -> Path:
    """返回单 PDB durable transaction receipt 路径。"""
    return evidence_dir / "transactions" / f"{pdb_id}.json"


def _read_transaction(evidence_dir: Path, pdb_id: str) -> dict[str, Any]:
    """读取 transaction receipt；首次提交前返回显式 absent 状态。"""
    path = _transaction_path(evidence_dir, pdb_id)
    if not path.is_file():
        return {"pdb_id": pdb_id, "state": "absent"}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_transaction(
    evidence_dir: Path,
    record: dict[str, Any],
    state: str,
) -> None:
    """原子写 durable transaction 状态与 before/after 哈希。"""
    write_report(
        _transaction_path(evidence_dir, str(record["pdb_id"])),
        {
            "pdb_id": record["pdb_id"],
            "state": state,
            "before_artifact_sha256": record["before_artifact_sha256"],
            "after_artifact_sha256": record["staged_artifact_sha256"],
            "schema_version": SOURCE_REBUILD_SCHEMA_VERSION,
        },
    )


def _artifact_hashes(paths: dict[str, Path]) -> dict[str, str]:
    """计算四件套每个文件的 SHA-256，并拒绝缺失文件。"""
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise SourceRebuildError(f"Stage C artifact files are missing: {missing}")
    return {key: sha256_file(path) for key, path in paths.items()}


def _atomic_copy(source: Path, target: Path) -> None:
    """把已完成文件复制到目标同目录临时文件，再原子替换。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.copy.{os.getpid()}")
    shutil.copyfile(source, temporary)
    atomic_replace(temporary, target)


def _verify_named_dependencies(root: Path, files: dict[str, str]) -> None:
    """要求命名依赖全部位于 root 内且内容哈希未变。"""
    changed = _changed_named_dependencies(root, files)
    if changed:
        raise SourceRebuildError(f"named dependencies changed: {changed}")


def _changed_named_dependencies(root: Path, files: dict[str, str]) -> list[str]:
    """返回缺失、越界或内容变化的相对依赖路径诊断键。"""
    root_resolved = root.resolve()
    changed = []
    for relative, expected_hash in files.items():
        path = (root / relative).resolve()
        try:
            path.relative_to(root_resolved)
        except ValueError:
            changed.append(f"dependency_outside_root:{relative}")
            continue
        if not path.is_file():
            changed.append(f"dependency_missing:{relative}")
        elif sha256_file(path) != expected_hash:
            changed.append(f"dependency_changed:{relative}")
    return changed


def _named_hash_manifest(files: dict[str, str]) -> str:
    """对相对路径到内容哈希映射计算稳定 SHA-256。"""
    return _json_sha256(files)


def _array_sha256(array: np.ndarray) -> str:
    """对数组 dtype、shape 与 C-order 原始字节计算稳定 SHA-256。"""
    digest = hashlib.sha256()
    digest.update(array.dtype.str.encode("ascii"))
    digest.update(b"\0")
    digest.update(json.dumps(array.shape, separators=(",", ":")).encode("ascii"))
    digest.update(b"\0")
    digest.update(np.ascontiguousarray(array).tobytes())
    return digest.hexdigest()


def _json_sha256(value: Any) -> str:
    """对不含 NaN 的 JSON 值计算排序、无空白的 UTF-8 SHA-256。"""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _arrays_equal(left: np.ndarray, right: np.ndarray) -> bool:
    """按 dtype/shape/value 比较数组，浮点 NaN 只在同位置时视为相等。"""
    if left.dtype != right.dtype or left.shape != right.shape:
        return False
    if np.issubdtype(left.dtype, np.floating):
        return bool(np.array_equal(left, right, equal_nan=True))
    return bool(np.array_equal(left, right))
