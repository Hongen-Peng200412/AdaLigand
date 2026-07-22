# Stage C 来源修复的 audit/apply 命令入口。
# 实际逻辑：调用 code/c_source_repair.py，先只读分类，再按授权执行受检迁移。
# 输入/输出：source-dirty 快照 + 既有 C 产物 → exact/atom-name-only/blocked/failed 证据。
# 关键边界：audit 与 apply 分离；没有授权或 gate 时只读，不得默默刷新 C。
"""Stage C source-dirty 集合的两阶段 audit/apply CLI。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from joblib import Parallel, delayed



from adaligand_preprocessing.ops.stage_c_repair import (
    SOURCE_AUDIT_SCHEMA_VERSION,
    apply_receptor_source_repair,
    audit_stage_c_source,
    verify_audit_inputs_unchanged,
)
from adaligand_preprocessing.utils.io import sha256_file, write_jsonl
from adaligand_preprocessing.execution.parallel import parse_pdb_id_filter_text
from adaligand_preprocessing.artifacts.reports import resolve_run_id, write_report


def main() -> None:
    """执行全 dirty-set 只读 audit，或在全局 preflight 后应用 receptor-only repair。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--pdb_ids_file", type=Path, required=True)
    parser.add_argument("--ids_sha256", required=True)
    parser.add_argument("--expected_count", type=int, required=True)
    parser.add_argument("--repair_run_id", required=True)
    parser.add_argument("--mode", choices=("audit", "apply"), required=True)
    parser.add_argument("--n_jobs", type=int, required=True)
    parser.add_argument("--delegated_rebuild_summary", type=Path)
    parser.add_argument("--delegated_rebuild_summary_sha256")
    parser.add_argument("--delegated_rebuild_apply_summary", type=Path)
    parser.add_argument("--delegated_rebuild_apply_sha256")
    parser.add_argument("--require_all_exact", action="store_true")
    args = parser.parse_args()
    args.repair_run_id = resolve_run_id(args.repair_run_id)
    if args.mode == "apply" and args.require_all_exact:
        raise ValueError("--require_all_exact is only valid in audit mode")

    ids_bytes = args.pdb_ids_file.read_bytes()
    actual_hash = hashlib.sha256(ids_bytes).hexdigest()
    if actual_hash != args.ids_sha256.lower():
        raise RuntimeError(f"dirty ids sha256 {actual_hash} != expected {args.ids_sha256}")
    pdb_ids = sorted(
        parse_pdb_id_filter_text(
            ids_bytes.decode("utf-8"),
            source=str(args.pdb_ids_file),
        )
    )
    if len(pdb_ids) != args.expected_count:
        raise RuntimeError(f"dirty ids count {len(pdb_ids)} != expected {args.expected_count}")

    report_dir = (
        args.root / "reports" / "runs" / args.repair_run_id / "stage_c_source_repair"
    )
    audit_path = report_dir / "audit.records.jsonl"
    delegated_records, delegated_summary_hash = _load_delegated_rebuild_audit(args)
    if not set(delegated_records).issubset(pdb_ids):
        outside = sorted(set(delegated_records).difference(pdb_ids))
        raise RuntimeError(f"delegated rebuild IDs outside dirty set: {outside}")
    if args.mode == "audit":
        records = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
            delayed(_audit_one)(args.root, pdb_id, delegated_records.get(pdb_id))
            for pdb_id in pdb_ids
        )
        write_jsonl(audit_path, records)
        audit_bytes = audit_path.read_bytes()
        counts = Counter(str(record["classification"]) for record in records)
        summary = _summary(
            args,
            counts,
            len(records),
            audit_records_sha256=hashlib.sha256(audit_bytes).hexdigest(),
            implementation_files=_implementation_hashes(),
            delegated_rebuild_summary_sha256=delegated_summary_hash,
            delegated_rebuild_count=len(delegated_records),
        )
        if args.require_all_exact:
            summary["require_all_exact"] = True
            if counts != Counter({"exact": len(records)}):
                summary["status"] = "failed"
        write_report(report_dir / "audit.summary.json", summary)
        if args.require_all_exact and counts != Counter({"exact": len(records)}):
            raise RuntimeError(
                f"source audit is not all exact: {dict(sorted(counts.items()))}"
            )
        if counts.get("blocked", 0) or counts.get("failed", 0):
            raise RuntimeError(f"source audit blocked: {dict(sorted(counts.items()))}")
        return

    audit_summary_path = report_dir / "audit.summary.json"
    audit_summary = json.loads(audit_summary_path.read_text(encoding="utf-8"))
    audit_bytes = audit_path.read_bytes()
    actual_audit_hash = hashlib.sha256(audit_bytes).hexdigest()
    if audit_summary.get("audit_records_sha256") != actual_audit_hash:
        raise RuntimeError("audit records hash does not match frozen audit summary")
    if audit_summary.get("dirty_ids_sha256") != args.ids_sha256.lower():
        raise RuntimeError("audit summary dirty ids hash does not match apply request")
    if audit_summary.get("n_records") != args.expected_count:
        raise RuntimeError("audit summary record count does not match apply request")
    if audit_summary.get("status") != "success":
        raise RuntimeError("refusing apply from a non-success audit summary")
    current_implementation = _implementation_hashes()
    if audit_summary.get("implementation_files") != current_implementation:
        raise RuntimeError("repair implementation changed between audit and apply")
    records = _read_jsonl_bytes(audit_bytes, audit_path)
    if len(records) != args.expected_count:
        raise RuntimeError(
            f"audit record count {len(records)} != expected {args.expected_count}"
        )
    record_by_id = {str(record["pdb_id"]): record for record in records}
    if set(record_by_id) != set(pdb_ids):
        raise RuntimeError("audit record IDs do not match frozen dirty set")
    allowed_classifications = {
        "exact",
        "atom_name_only",
        "delegated_full_rebuild_ready",
    }
    blocked = [
        record
        for record in records
        if record["classification"] not in allowed_classifications
    ]
    if blocked:
        raise RuntimeError(f"refusing apply with {len(blocked)} blocked audit records")

    delegated = [
        record
        for record in records
        if record["classification"] == "delegated_full_rebuild_ready"
    ]
    if delegated:
        _verify_delegated_rebuild_apply(args, audit_summary, len(delegated))
        # 专用四件套提交完成后，14 个 delegated 样本必须全部变为 generic exact；
        # 这一步仍在任何 receptor-only 写入之前执行。
        delegated_results = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
            delayed(_verify_delegated_after_apply)(args.root, record)
            for record in delegated
        )
    else:
        delegated_results = []
    generic_records = [
        record
        for record in records
        if record["classification"] in {"exact", "atom_name_only"}
    ]

    # 全量 TOCTOU preflight 必须在第一份 receptor 写入前完成。
    Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(verify_audit_inputs_unchanged)(args.root, record)
        for record in generic_records
    )
    generic_results = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(_apply_one)(args.root, record) for record in generic_records
    )
    results = sorted(
        [*delegated_results, *generic_results],
        key=lambda item: str(item["pdb_id"]),
    )
    write_jsonl(report_dir / "apply.records.jsonl", results)
    counts = Counter(str(record["action"]) for record in results)
    summary = _summary(
        args,
        counts,
        len(results),
        audit_records_sha256=actual_audit_hash,
    )
    write_report(report_dir / "apply.summary.json", summary)
    if counts.get("failed", 0):
        raise RuntimeError(f"source apply failed: {dict(sorted(counts.items()))}")


def _audit_one(root: Path, pdb_id: str, delegated_record: dict | None) -> dict:
    """把单样本 audit 异常转成完整 failed record，避免并行任务提前丢失证据。"""
    try:
        record = audit_stage_c_source(root, pdb_id)
        if delegated_record is None:
            return record
        base_audit = delegated_record.get("base_audit")
        if record != base_audit:
            raise RuntimeError(f"delegated rebuild base audit changed for {pdb_id}")
        decorated = dict(record)
        decorated["delegated_base_classification"] = record["classification"]
        decorated["delegated_base_reasons"] = record["reasons"]
        decorated["classification"] = "delegated_full_rebuild_ready"
        decorated["reasons"] = []
        decorated["delegated_rebuild_record_sha256"] = _json_sha256(delegated_record)
        return decorated
    except Exception as exc:
        return {
            "pdb_id": pdb_id,
            "classification": "failed",
            "reasons": [type(exc).__name__],
            "error": str(exc),
            "schema_version": SOURCE_AUDIT_SCHEMA_VERSION,
        }


def _apply_one(root: Path, record: dict) -> dict:
    """把单样本 apply 异常转成结果记录；重试应从整轮 audit 重新开始。"""
    try:
        return apply_receptor_source_repair(root, record)
    except Exception as exc:
        return {
            "pdb_id": str(record["pdb_id"]),
            "action": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _summary(
    args: argparse.Namespace,
    counts: Counter[str],
    n_records: int,
    **extra: object,
) -> dict:
    """构造 audit/apply 的 run-scoped summary。"""
    return {
        "status": (
            "success"
            if not counts.get("blocked", 0) and not counts.get("failed", 0)
            else "failed"
        ),
        "schema_version": SOURCE_AUDIT_SCHEMA_VERSION,
        "mode": args.mode,
        "repair_run_id": args.repair_run_id,
        "dirty_ids_path": str(args.pdb_ids_file),
        "dirty_ids_sha256": args.ids_sha256.lower(),
        "n_records": n_records,
        "counts": dict(sorted(counts.items())),
        "policy": (
            "before any canonical write, every dirty sample must be exact, "
            "atom_name_only, or explicitly delegated_full_rebuild_ready from one frozen "
            "run-scoped audit; generic apply changes receptor_tokens only and rechecks hashes"
        ),
        **extra,
    }


def _read_jsonl_bytes(payload: bytes, source: Path) -> list[dict]:
    """从同一份已哈希字节解析 JSONL，消除 hash→另读文件的窗口。"""
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
    """冻结 audit/apply 之间的本项目 Python 实现，禁止中途 safe sync 漂移。"""
    project_root = Path(__file__).resolve().parents[2]
    paths = sorted((project_root / "adaligand_preprocessing").rglob("*.py"))
    return {
        path.relative_to(project_root).as_posix(): sha256_file(path)
        for path in paths
    }


def _load_delegated_rebuild_audit(
    args: argparse.Namespace,
) -> tuple[dict[str, dict], str | None]:
    """加载并冻结专用 full-rebuild audit；未配置时返回空映射。"""
    path = args.delegated_rebuild_summary
    expected_hash = args.delegated_rebuild_summary_sha256
    if path is None and expected_hash is None:
        return {}, None
    if path is None or expected_hash is None:
        raise RuntimeError("delegated rebuild audit requires summary path and SHA-256")
    payload = path.read_bytes()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != expected_hash.lower():
        raise RuntimeError("delegated rebuild audit summary hash mismatch")
    summary = json.loads(payload)
    if summary.get("status") != "success":
        raise RuntimeError("delegated rebuild audit is not successful")
    if summary.get("implementation_files") != _rebuild_implementation_hashes():
        raise RuntimeError("delegated rebuild implementation changed after audit")
    records_path = path.with_name("audit.records.jsonl")
    records_payload = records_path.read_bytes()
    if hashlib.sha256(records_payload).hexdigest() != summary.get("audit_records_sha256"):
        raise RuntimeError("delegated rebuild records hash mismatch")
    records = _read_jsonl_bytes(records_payload, records_path)
    by_id = {str(record["pdb_id"]): record for record in records}
    if len(by_id) != summary.get("authorized_count"):
        raise RuntimeError("delegated rebuild record IDs/count mismatch")
    if any(record.get("classification") != "full_rebuild_ready" for record in records):
        raise RuntimeError("delegated rebuild contains non-ready record")
    return by_id, actual_hash


def _verify_delegated_rebuild_apply(
    args: argparse.Namespace,
    audit_summary: dict,
    expected_count: int,
) -> None:
    """验证专用四件套 apply 已完整提交，且对应同一份 pre-apply audit。"""
    path = args.delegated_rebuild_apply_summary
    expected_hash = args.delegated_rebuild_apply_sha256
    if path is None or expected_hash is None:
        raise RuntimeError("delegated records require rebuild apply summary and SHA-256")
    payload = path.read_bytes()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != expected_hash.lower():
        raise RuntimeError("delegated rebuild apply summary hash mismatch")
    summary = json.loads(payload)
    if summary.get("status") != "success" or summary.get("n_records") != expected_count:
        raise RuntimeError("delegated rebuild apply is incomplete")
    if summary.get("repair_run_id") != args.repair_run_id:
        raise RuntimeError("delegated rebuild apply run mismatch")
    audit_summary_path = args.delegated_rebuild_summary
    rebuild_audit = json.loads(audit_summary_path.read_text(encoding="utf-8"))
    if summary.get("audit_summary_sha256") != sha256_file(audit_summary_path):
        raise RuntimeError("delegated rebuild apply references another audit")
    if summary.get("authorized_ids_sha256") != rebuild_audit.get(
        "authorized_ids_sha256"
    ):
        raise RuntimeError("delegated rebuild apply authorized IDs mismatch")
    apply_records_path = path.with_name("apply.records.jsonl")
    apply_records_payload = apply_records_path.read_bytes()
    if hashlib.sha256(apply_records_payload).hexdigest() != summary.get(
        "apply_records_sha256"
    ):
        raise RuntimeError("delegated rebuild apply records hash mismatch")
    apply_records = _read_jsonl_bytes(apply_records_payload, apply_records_path)
    apply_ids = [str(record["pdb_id"]) for record in apply_records]
    rebuild_records_path = audit_summary_path.with_name("audit.records.jsonl")
    rebuild_records = _read_jsonl_bytes(
        rebuild_records_path.read_bytes(),
        rebuild_records_path,
    )
    rebuild_ids = {str(record["pdb_id"]) for record in rebuild_records}
    allowed_actions = {
        "committed",
        "already_committed",
        "committed_after_receipt_recovery",
    }
    if (
        len(apply_ids) != len(set(apply_ids))
        or set(apply_ids) != rebuild_ids
        or any(record.get("action") not in allowed_actions for record in apply_records)
    ):
        raise RuntimeError("delegated rebuild apply records IDs/actions mismatch")
    if audit_summary.get("delegated_rebuild_summary_sha256") != sha256_file(
        audit_summary_path
    ):
        raise RuntimeError("generic audit references another delegated rebuild")
    generic_audit_path = (
        args.root
        / "reports"
        / "runs"
        / args.repair_run_id
        / "stage_c_source_repair"
        / "audit.summary.json"
    )
    if summary.get("preapply_gate_sha256") != sha256_file(generic_audit_path):
        raise RuntimeError("delegated rebuild apply references another preapply gate")


def _verify_delegated_after_apply(root: Path, record: dict) -> dict:
    """专用 apply 后要求 delegated PDB 已成为 generic exact，再允许 receptor-only commit。"""
    fresh = audit_stage_c_source(root, str(record["pdb_id"]))
    if fresh.get("classification") != "exact":
        raise RuntimeError(
            f"delegated rebuild did not become exact for {record['pdb_id']}: "
            f"{fresh.get('classification')}"
        )
    return {
        "pdb_id": str(record["pdb_id"]),
        "action": "delegated_rebuild_verified",
        "receptor_before_sha256": fresh["receptor_before_sha256"],
        "receptor_after_sha256": fresh["receptor_before_sha256"],
        "atom_name_diff_count": 0,
    }


def _rebuild_implementation_hashes() -> dict[str, str]:
    """按专用 rebuild CLI 的口径重算实现哈希。"""
    project_root = Path(__file__).resolve().parents[2]
    paths = sorted((project_root / "adaligand_preprocessing").rglob("*.py"))
    return {
        path.relative_to(project_root).as_posix(): sha256_file(path)
        for path in paths
    }


def _json_sha256(value: object) -> str:
    """对单条 delegated rebuild record 计算排序、无空白 SHA-256。"""
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
