"""冻结授权集合的 Stage C full-rebuild audit/prepare 与受 gate 提交入口。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from joblib import Parallel, delayed


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from c_source_rebuild import (
    SOURCE_REBUILD_SCHEMA_VERSION,
    apply_prepared_source_rebuilds,
    prepare_stage_c_source_rebuild,
)
from c_source_repair import verify_audit_inputs_unchanged
from io_utils import sha256_file, write_jsonl
from parallel import parse_pdb_id_filter_text
from reports import resolve_run_id, write_report


def main() -> None:
    """执行 run-scoped full-rebuild audit/prepare，或在联合 gate 后提交四件套。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pdb_ids_file", type=Path, required=True)
    parser.add_argument("--ids_sha256", required=True)
    parser.add_argument("--expected_count", type=int, required=True)
    parser.add_argument("--dirty_ids_file", type=Path, required=True)
    parser.add_argument("--dirty_ids_sha256", required=True)
    parser.add_argument("--dirty_expected_count", type=int, required=True)
    parser.add_argument("--repair_run_id", required=True)
    parser.add_argument("--mode", choices=("audit", "apply"), required=True)
    parser.add_argument("--n_jobs", type=int, required=True)
    parser.add_argument("--expected_added", type=int, required=True)
    parser.add_argument("--expected_removed", type=int, required=True)
    parser.add_argument("--expected_reassigned", type=int, required=True)
    parser.add_argument("--preapply_gate_summary", type=Path)
    parser.add_argument("--preapply_gate_sha256")
    args = parser.parse_args()
    args.repair_run_id = resolve_run_id(args.repair_run_id)

    pdb_ids, ids_hash = _frozen_pdb_ids(
        args.pdb_ids_file,
        args.ids_sha256,
        args.expected_count,
    )
    dirty_ids, dirty_hash = _frozen_pdb_ids(
        args.dirty_ids_file,
        args.dirty_ids_sha256,
        args.dirty_expected_count,
    )
    outside = sorted(set(pdb_ids).difference(dirty_ids))
    if outside:
        raise RuntimeError(f"authorized rebuild IDs outside dirty set: {outside}")

    evidence_dir = (
        args.root / "reports" / "runs" / args.repair_run_id / "stage_c_source_rebuild"
    )
    audit_path = evidence_dir / "audit.records.jsonl"
    manifest_path = evidence_dir / "primary_key_migration.records.jsonl"
    summary_path = evidence_dir / "audit.summary.json"
    if args.mode == "audit":
        prepared = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
            delayed(_prepare_one)(args.root, evidence_dir, pdb_id) for pdb_id in pdb_ids
        )
        records = [item[0] for item in prepared]
        migration_rows = [row for item in prepared for row in item[1]]
        write_jsonl(audit_path, records)
        write_jsonl(manifest_path, migration_rows)
        classification_counts = Counter(
            str(record["classification"]) for record in records
        )
        migration_counts = Counter(str(row["status"]) for row in migration_rows)
        expected_migration = {
            "added": args.expected_added,
            "removed": args.expected_removed,
            "reassigned": args.expected_reassigned,
        }
        migration_matches = all(
            migration_counts.get(key, 0) == value
            for key, value in expected_migration.items()
        )
        success = (
            classification_counts.get("failed", 0) == 0
            and classification_counts.get("full_rebuild_ready", 0) == len(pdb_ids)
            and migration_matches
        )
        summary = {
            "status": "success" if success else "failed",
            "schema_version": SOURCE_REBUILD_SCHEMA_VERSION,
            "mode": "audit",
            "repair_run_id": args.repair_run_id,
            "authorized_ids_path": str(args.pdb_ids_file),
            "authorized_ids_sha256": ids_hash,
            "authorized_count": len(pdb_ids),
            "dirty_ids_path": str(args.dirty_ids_file),
            "dirty_ids_sha256": dirty_hash,
            "dirty_count": len(dirty_ids),
            "classification_counts": dict(sorted(classification_counts.items())),
            "migration_counts": dict(sorted(migration_counts.items())),
            "expected_migration_counts": expected_migration,
            "audit_records_sha256": sha256_file(audit_path),
            "migration_manifest_sha256": sha256_file(manifest_path),
            "implementation_files": _implementation_hashes(),
            "policy": (
                "run-scoped authorization only; manifest is diagnostic evidence and is not "
                "a Stage C artifact, training field, stable accession, or future rebuild policy"
            ),
        }
        write_report(summary_path, summary)
        if not success:
            raise RuntimeError(
                "full rebuild audit blocked: "
                f"classifications={dict(classification_counts)}, "
                f"migration={dict(migration_counts)}"
            )
        return

    summary, records = _load_success_audit(
        summary_path,
        audit_path,
        manifest_path,
        ids_hash,
        pdb_ids,
        {
            "added": args.expected_added,
            "removed": args.expected_removed,
            "reassigned": args.expected_reassigned,
        },
    )
    _verify_preapply_gate(args, summary, records, dirty_ids)
    results = apply_prepared_source_rebuilds(args.root, evidence_dir, records)
    apply_path = evidence_dir / "apply.records.jsonl"
    write_jsonl(apply_path, results)
    actions = Counter(str(item["action"]) for item in results)
    write_report(
        evidence_dir / "apply.summary.json",
        {
            "status": "success",
            "schema_version": SOURCE_REBUILD_SCHEMA_VERSION,
            "mode": "apply",
            "repair_run_id": args.repair_run_id,
            "authorized_ids_sha256": ids_hash,
            "n_records": len(results),
            "actions": dict(sorted(actions.items())),
            "audit_summary_sha256": sha256_file(summary_path),
            "preapply_gate_sha256": args.preapply_gate_sha256.lower(),
            "apply_records_sha256": sha256_file(apply_path),
        },
    )


def _prepare_one(
    root: Path,
    evidence_dir: Path,
    pdb_id: str,
) -> tuple[dict, list[dict]]:
    """把单 PDB prepare 异常转成 failed record；canonical Stage C 始终零写入。"""
    try:
        return prepare_stage_c_source_rebuild(root, pdb_id, evidence_dir)
    except Exception as exc:
        return ({
            "pdb_id": pdb_id,
            "classification": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "schema_version": SOURCE_REBUILD_SCHEMA_VERSION,
        }, [])


def _frozen_pdb_ids(
    path: Path,
    expected_hash: str,
    expected_count: int,
) -> tuple[list[str], str]:
    """从同一份已哈希字节解析 PDB IDs，并验证数量。"""
    payload = path.read_bytes()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != expected_hash.lower():
        raise RuntimeError(f"PDB ids sha256 {actual_hash} != expected {expected_hash}")
    pdb_ids = sorted(
        parse_pdb_id_filter_text(payload.decode("utf-8"), source=str(path))
    )
    if len(pdb_ids) != expected_count:
        raise RuntimeError(f"PDB ids count {len(pdb_ids)} != expected {expected_count}")
    return pdb_ids, actual_hash


def _load_success_audit(
    summary_path: Path,
    audit_path: Path,
    manifest_path: Path,
    ids_hash: str,
    expected_ids: list[str],
    expected_migration_counts: dict[str, int],
) -> tuple[dict, list[dict]]:
    """从同一份已哈希字节加载成功 audit，并复核实现与 migration manifest。"""
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    audit_payload = audit_path.read_bytes()
    manifest_payload = manifest_path.read_bytes()
    if summary.get("status") != "success":
        raise RuntimeError("refusing apply from a non-success full rebuild audit")
    if summary.get("authorized_ids_sha256") != ids_hash:
        raise RuntimeError("full rebuild audit IDs hash mismatch")
    if summary.get("authorized_count") != len(expected_ids):
        raise RuntimeError("full rebuild audit count mismatch")
    if summary.get("expected_migration_counts") != expected_migration_counts:
        raise RuntimeError("full rebuild apply migration expectations differ from audit")
    if hashlib.sha256(audit_payload).hexdigest() != summary.get("audit_records_sha256"):
        raise RuntimeError("full rebuild audit records hash mismatch")
    if hashlib.sha256(manifest_payload).hexdigest() != summary.get(
        "migration_manifest_sha256"
    ):
        raise RuntimeError("primary-key migration manifest hash mismatch")
    if summary.get("implementation_files") != _implementation_hashes():
        raise RuntimeError("full rebuild implementation changed after audit")
    records = _read_jsonl_bytes(audit_payload, audit_path)
    if len(records) != len(expected_ids):
        raise RuntimeError("full rebuild audit record count mismatch")
    record_ids = [str(record["pdb_id"]) for record in records]
    if len(record_ids) != len(set(record_ids)) or set(record_ids) != set(expected_ids):
        raise RuntimeError("full rebuild audit record IDs do not match authorized IDs")
    return summary, records


def _verify_preapply_gate(
    args: argparse.Namespace,
    rebuild_summary: dict,
    rebuild_records: list[dict],
    dirty_ids: list[str],
) -> None:
    """复核 2,156 联合 gate，并在首个 canonical 写入前对其余样本做 live CAS。"""
    if args.preapply_gate_summary is None or args.preapply_gate_sha256 is None:
        raise RuntimeError("apply requires frozen --preapply_gate_summary and SHA-256")
    payload = args.preapply_gate_summary.read_bytes()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != args.preapply_gate_sha256.lower():
        raise RuntimeError("preapply gate summary hash mismatch")
    gate = json.loads(payload)
    if gate.get("status") != "success":
        raise RuntimeError("preapply gate is not successful")
    if gate.get("repair_run_id") != args.repair_run_id:
        raise RuntimeError("preapply gate repair run mismatch")
    if gate.get("dirty_ids_sha256") != args.dirty_ids_sha256.lower():
        raise RuntimeError("preapply gate dirty-set hash mismatch")
    if gate.get("n_records") != len(dirty_ids):
        raise RuntimeError("preapply gate dirty-set count mismatch")
    counts = gate.get("counts", {})
    if sum(int(value) for value in counts.values()) != len(dirty_ids):
        raise RuntimeError("preapply gate counts do not sum to dirty-set size")
    if counts.get("blocked", 0) or counts.get("failed", 0):
        raise RuntimeError("preapply gate still contains blocked/failed records")
    if counts.get("delegated_full_rebuild_ready", 0) != len(rebuild_records):
        raise RuntimeError("preapply gate delegated count mismatch")
    if gate.get("delegated_rebuild_count") != len(rebuild_records):
        raise RuntimeError("preapply gate delegated summary count mismatch")
    rebuild_summary_hash = sha256_file(
        args.root
        / "reports"
        / "runs"
        / args.repair_run_id
        / "stage_c_source_rebuild"
        / "audit.summary.json"
    )
    if gate.get("delegated_rebuild_summary_sha256") != rebuild_summary_hash:
        raise RuntimeError("preapply gate does not reference this rebuild audit")
    if rebuild_summary.get("dirty_ids_sha256") != args.dirty_ids_sha256.lower():
        raise RuntimeError("full rebuild audit dirty-set hash mismatch")
    if gate.get("implementation_files") != _generic_repair_implementation_hashes():
        raise RuntimeError("generic repair implementation changed after preapply gate")

    gate_records_path = args.preapply_gate_summary.with_name("audit.records.jsonl")
    gate_records_payload = gate_records_path.read_bytes()
    if hashlib.sha256(gate_records_payload).hexdigest() != gate.get(
        "audit_records_sha256"
    ):
        raise RuntimeError("preapply gate audit records hash mismatch")
    gate_records = _read_jsonl_bytes(gate_records_payload, gate_records_path)
    gate_ids = [str(record["pdb_id"]) for record in gate_records]
    if len(gate_ids) != len(set(gate_ids)) or set(gate_ids) != set(dirty_ids):
        raise RuntimeError("preapply gate audit record IDs do not match dirty set")
    rebuild_by_id = {str(record["pdb_id"]): record for record in rebuild_records}
    generic_records = []
    for record in gate_records:
        pdb_id = str(record["pdb_id"])
        if pdb_id in rebuild_by_id:
            if record.get("classification") != "delegated_full_rebuild_ready":
                raise RuntimeError(f"authorized rebuild is not delegated in gate: {pdb_id}")
            if record.get("delegated_rebuild_record_sha256") != _json_sha256(
                rebuild_by_id[pdb_id]
            ):
                raise RuntimeError(f"delegated rebuild record hash mismatch: {pdb_id}")
        else:
            if record.get("classification") not in {"exact", "atom_name_only"}:
                raise RuntimeError(f"unresolved generic record in preapply gate: {pdb_id}")
            generic_records.append(record)
    Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(verify_audit_inputs_unchanged)(args.root, record)
        for record in generic_records
    )


def _read_jsonl_bytes(payload: bytes, source: Path) -> list[dict]:
    """从同一份已哈希 JSONL 字节解析对象列表。"""
    records = []
    for line_number, line in enumerate(payload.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row must be an object: {source}:{line_number}")
        records.append(value)
    return records


def _implementation_hashes() -> dict[str, str]:
    """冻结 audit/apply 之间的代码实现，禁止中途 safe sync 漂移。"""
    project_root = Path(__file__).resolve().parents[1]
    paths = sorted((project_root / "code").glob("*.py")) + [Path(__file__).resolve()]
    return {
        path.relative_to(project_root).as_posix(): sha256_file(path)
        for path in paths
    }


def _generic_repair_implementation_hashes() -> dict[str, str]:
    """按 generic source-repair CLI 的口径重算联合 gate 实现哈希。"""
    project_root = Path(__file__).resolve().parents[1]
    repair_script = project_root / "scripts" / "c_source_repair.py"
    paths = sorted((project_root / "code").glob("*.py")) + [repair_script]
    return {
        path.relative_to(project_root).as_posix(): sha256_file(path)
        for path in paths
    }


def _json_sha256(value: object) -> str:
    """对 delegated rebuild record 计算排序、无空白 SHA-256。"""
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":
    main()
