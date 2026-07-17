# 学习导航：功能分区=run-scoped 运维迁移；生命周期=仅服务 2026-07-17 正式 Stage F signal-11 收口。
# 主要输入：正式 Stage F 五条排除视图、补算 v1 六条 unknown、两轮只读 shadow 验收证据。
# 主要输出：正式 run 的 11 条 Stage F 加法视图，以及 v1/v2 补算 run 各自合法的六条排除清单。
# 关键边界：不写质量三件套、不改共享 Stage E manifest、不把 signal 11 伪装为 timeout 或 success。
"""为当前正式 run 原子登记六个祖传 Chimera ALL signal-11 排除项。"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Callable
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))

from exclusions import exclusion_status_fields, load_run_exclusions
from filtering import load_stage_statuses
from io_utils import sha256_file
from reports import StageStatus
from stage_f_process_audit import PROCESS_AUDIT_SCHEMA_VERSION, implementation_identity


SIGNAL11_IDS = ("9bw7", "9c1k", "9dgr", "9fkb", "9mxv", "9nw3")


@dataclass(frozen=True)
class Signal11TransitionContract:
    """冻结一次 run-only 迁移所需的 run 身份与只读证据身份。"""

    formal_run_id: str
    supplement_run_ids: tuple[str, str]
    authorization: str
    exclusion_cap: int
    expected_base_sha256: str
    expected_formal_before_sha256: str
    status_before_relative_path: str
    expected_status_before_sha256: str
    n_jobs1_acceptance_relative_path: str
    expected_n_jobs1_acceptance_sha256: str
    all_only_acceptance_relative_path: str
    expected_all_only_acceptance_sha256: str
    supplement_ids_relative_paths: tuple[str, str]
    expected_supplement_ids_sha256: tuple[str, str]
    expected_supplement_counts: tuple[int, int]


DEFAULT_CONTRACT = Signal11TransitionContract(
    formal_run_id="adaligand_ag_20260711T154658",
    supplement_run_ids=(
        "adaligand_ag_20260711T154658_fsupp96_v1",
        "adaligand_ag_20260711T154658_fsupp96_v2",
    ),
    authorization=(
        "user_explicit_2026-07-17_exclude_six_chimera_full_grid_cc_signal11_"
        "and_raise_current_run_cap_to_30"
    ),
    exclusion_cap=30,
    expected_base_sha256=(
        "380844d0b908b08707fada689f64b2fa4cc519f4771df92dec8b5bf0b2cd325f"
    ),
    expected_formal_before_sha256=(
        "3b10abb5cc69bca0689cb89cdb6e0bde21620504c11479edcbfb51c83ec68ee8"
    ),
    status_before_relative_path=(
        "reports/runs/adaligand_ag_20260711T154658_fsupp96_v1/"
        "stage_f/status.part_0000_of_0001.jsonl"
    ),
    expected_status_before_sha256=(
        "7938aea615c19029265587d556622c8f2d6aea5acff59a94baa85813698496b6"
    ),
    n_jobs1_acceptance_relative_path=(
        "reports/runs/adaligand_ag_20260711T154658/"
        "stage_f_cc_sigsegv_shadow_20260717_v1/shadow_acceptance.json"
    ),
    expected_n_jobs1_acceptance_sha256=(
        "67cc083c94efbb72648db07e5d62ec8fee195bbf3a3dc59eecb5dcbf0ed868b2"
    ),
    all_only_acceptance_relative_path=(
        "reports/runs/adaligand_ag_20260711T154658/"
        "stage_f_cc_all_fresh_process_shadow_20260717_v2/acceptance.json"
    ),
    expected_all_only_acceptance_sha256=(
        "e0bef08c6a4da804d0173ccc920e3e58316912ee4fea303bf9045ad4f50032e9"
    ),
    supplement_ids_relative_paths=(
        (
            "reports/runs/adaligand_ag_20260711T154658/"
            "stage_f_tail_supplement_20260715_v1/pdb_ids.txt"
        ),
        (
            "reports/runs/adaligand_ag_20260711T154658_fsupp96_v2/"
            "stage_f_tail_supplement_20260716_v2/pdb_ids.txt"
        ),
    ),
    expected_supplement_ids_sha256=(
        "acacde79c2a5a8727949cdc0a986930aa8404419a8edaabfb264f4f05dacea80",
        "7f427993c3a2e8c2e147e8c40b9b83423b932e2275066ccd010efbbf79617c6c",
    ),
    expected_supplement_counts=(2990, 5984),
)


SchedulerStateQuery = Callable[[int], str]


def apply_or_validate_signal11_transition(
    root: Path,
    *,
    mode: str,
    contract: Signal11TransitionContract = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    """
    应用或复核本轮 signal-11 排除迁移。

    ``apply`` 只在全部旧身份与 0/3 三件套前置条件通过后原子写入；``validate``
    要求迁移账本和三个 run 的 manifest 已逐字节闭合。两种模式都不会创建或修改
    ``quality``、``quality_atoms`` 下的任何文件。
    """
    if mode not in {"apply", "validate"}:
        raise ValueError(f"unsupported signal-11 transition mode: {mode}")
    root = root.resolve()
    formal_run_dir = root / "reports" / "runs" / contract.formal_run_id
    evidence_dir = formal_run_dir / "stage_f_signal11_exclusion_20260717_v1"
    base_manifest = formal_run_dir / "exclusions.jsonl"
    formal_manifest = formal_run_dir / "exclusions.stage_f.jsonl"
    status_source = root / contract.status_before_relative_path
    n_jobs1_acceptance = root / contract.n_jobs1_acceptance_relative_path
    all_only_acceptance = root / contract.all_only_acceptance_relative_path
    status_evidence = evidence_dir / "supplement_v1_status.before.jsonl"
    formal_before_evidence = evidence_dir / "formal_stage_f.before.jsonl"

    _require_sha(base_manifest, contract.expected_base_sha256, "formal base manifest")
    _require_sha(
        n_jobs1_acceptance,
        contract.expected_n_jobs1_acceptance_sha256,
        "n_jobs=1 shadow acceptance",
    )
    _require_sha(
        all_only_acceptance,
        contract.expected_all_only_acceptance_sha256,
        "fresh ALL-only acceptance",
    )
    before_bytes = _resolve_before_bytes(
        formal_manifest,
        formal_before_evidence,
        expected_sha256=contract.expected_formal_before_sha256,
    )
    status_before_bytes = _resolve_before_bytes(
        status_source,
        status_evidence,
        expected_sha256=contract.expected_status_before_sha256,
    )
    _validate_signal11_status(status_before_bytes)
    trio_snapshot = _require_zero_public_trios(root)

    base_records = _records_by_id(base_manifest.read_bytes())
    before_records = _records_by_id(before_bytes)
    if set(base_records) != {"8ckb", "8glv", "9e5c", "9fqr"}:
        raise RuntimeError(f"formal base exclusion IDs drifted: {sorted(base_records)}")
    if set(before_records) != {*base_records, "6kgx"}:
        raise RuntimeError(
            f"formal Stage F pre-transition IDs drifted: {sorted(before_records)}"
        )
    for pdb_id, record in base_records.items():
        if before_records.get(pdb_id) != record:
            raise RuntimeError(f"formal Stage F view changed base record: {pdb_id}")

    formal_records = dict(before_records)
    for pdb_id in SIGNAL11_IDS:
        formal_records[pdb_id] = _signal11_record(
            pdb_id,
            run_id=contract.formal_run_id,
            root=root,
            contract=contract,
        )
    if len(formal_records) != 11 or len(formal_records) > contract.exclusion_cap:
        raise RuntimeError("formal Stage F exclusion count violates the authorized run cap")

    formal_after_bytes = _encode_jsonl(formal_records)
    supplement_payloads = {
        run_id: _encode_jsonl(
            {
                pdb_id: _signal11_record(
                    pdb_id,
                    run_id=run_id,
                    root=root,
                    contract=contract,
                )
                for pdb_id in SIGNAL11_IDS
            }
        )
        for run_id in contract.supplement_run_ids
    }
    formal_after_path = evidence_dir / "formal_stage_f.after.jsonl"
    supplement_after_paths = {
        run_id: evidence_dir / f"{run_id}.exclusions.after.jsonl"
        for run_id in contract.supplement_run_ids
    }

    if mode == "apply":
        _write_immutable(formal_before_evidence, before_bytes)
        _write_immutable(status_evidence, status_before_bytes)
        _write_immutable(formal_after_path, formal_after_bytes)
        for run_id, payload in supplement_payloads.items():
            _write_immutable(supplement_after_paths[run_id], payload)
        _replace_if_before_or_equal(
            formal_manifest,
            formal_after_bytes,
            allowed_before_sha256=contract.expected_formal_before_sha256,
        )
        for run_id, payload in supplement_payloads.items():
            run_dir = root / "reports" / "runs" / run_id
            stage_f_view = run_dir / "exclusions.stage_f.jsonl"
            if stage_f_view.exists() or stage_f_view.is_symlink():
                raise RuntimeError(
                    f"supplement run must not introduce a Stage F overlay: {stage_f_view}"
                )
            _replace_if_absent_or_equal(run_dir / "exclusions.jsonl", payload)
    else:
        _require_bytes(formal_before_evidence, before_bytes, "formal before evidence")
        _require_bytes(status_evidence, status_before_bytes, "status before evidence")
        _require_bytes(formal_after_path, formal_after_bytes, "formal after evidence")
        _require_bytes(formal_manifest, formal_after_bytes, "formal Stage F manifest")
        for run_id, payload in supplement_payloads.items():
            _require_bytes(
                supplement_after_paths[run_id],
                payload,
                f"{run_id} after evidence",
            )
            _require_bytes(
                root / "reports" / "runs" / run_id / "exclusions.jsonl",
                payload,
                f"{run_id} exclusion manifest",
            )

    formal_loaded, formal_sha = load_run_exclusions(
        root, contract.formal_run_id, "stage_f"
    )
    if set(formal_loaded) != set(formal_records):
        raise RuntimeError("formal Stage F loader does not expose exactly 11 exclusions")
    supplement_sha: dict[str, str] = {}
    for run_id in contract.supplement_run_ids:
        loaded, digest = load_run_exclusions(root, run_id, "stage_f")
        if set(loaded) != set(SIGNAL11_IDS) or digest is None:
            raise RuntimeError(f"supplement exclusion loader mismatch: {run_id}")
        supplement_sha[run_id] = digest

    summary = {
        "schema_version": 1,
        "status": "success",
        "event": "stage_f_signal11_run_policy_exclusion_transition",
        "decision_scope": "current_run_only",
        "scientific_contract_changed": False,
        "formal_run_id": contract.formal_run_id,
        "supplement_run_ids": list(contract.supplement_run_ids),
        "authorization": contract.authorization,
        "authorized_exclusion_cap": contract.exclusion_cap,
        "base_manifest_path": str(base_manifest),
        "base_manifest_sha256": contract.expected_base_sha256,
        "formal_before_sha256": contract.expected_formal_before_sha256,
        "supplement_plan_exclusion_snapshot_sha256": (
            contract.expected_formal_before_sha256
        ),
        "supplement_plan_overlay": (
            "the five-entry Stage F SHA remains immutable historical plan evidence; "
            "the six signal-11 decisions are a post-plan run-scoped overlay"
        ),
        "formal_after_sha256": formal_sha,
        "formal_exclusion_ids": sorted(formal_records),
        "added_exclusion_ids": list(SIGNAL11_IDS),
        "supplement_manifest_sha256": supplement_sha,
        "status_before_sha256": contract.expected_status_before_sha256,
        "n_jobs1_acceptance_sha256": contract.expected_n_jobs1_acceptance_sha256,
        "all_only_acceptance_sha256": contract.expected_all_only_acceptance_sha256,
        "public_quality_trios": trio_snapshot,
        "policy": (
            "write real known_failed:run_policy_excluded with exclusion_reason="
            "chimera_full_grid_cc_signal11; never create placeholder quality artifacts"
        ),
    }
    summary_bytes = _encode_json(summary)
    summary_path = evidence_dir / "summary.json"
    if mode == "apply":
        _write_immutable(summary_path, summary_bytes)
    else:
        _require_bytes(summary_path, summary_bytes, "transition summary")
    return summary


def validate_formal_signal11_readiness(
    root: Path,
    *,
    expected_supplement_run_cmd_sha256: str,
    contract: Signal11TransitionContract = DEFAULT_CONTRACT,
    lock_root: Path = Path("/home/penghongen"),
    scheduler_state_query: SchedulerStateQuery | None = None,
) -> dict[str, Any]:
    """
    在正式 Stage F 启动前验证补算 v1 已闭合，且 v2 已闭合或仍由受信进程运行。

    输入参数:
        - root: Path, 服务器数据根目录
        - expected_supplement_run_cmd_sha256: str, 当前 job 318350 ``run_cmd`` 的受信 SHA-256
        - contract: Signal11TransitionContract, 本次 run-only 决策的冻结身份
        - lock_root: Path, Slurm 四锁与 ``run_cmd`` 所在目录
        - scheduler_state_query: Callable[[int], str] | None, 测试可注入的 Slurm 状态查询器

    输出:
        - summary: dict[str, Any], 包含:
            - ``status``: str, 固定为 ``success``
            - ``supplement_v1``: dict, v1 全覆盖状态与 release 身份
            - ``supplement_v2``: dict, v2 完整 release 或受信活动进程身份
    """
    if re.fullmatch(r"[0-9a-f]{64}", expected_supplement_run_cmd_sha256) is None:
        raise ValueError("expected supplement run_cmd SHA-256 must be lowercase hex")
    apply_or_validate_signal11_transition(root, mode="validate", contract=contract)
    v1 = _validate_supplement_release(root, contract, supplement_index=0)

    v2_run_id = contract.supplement_run_ids[1]
    v2_release = (
        root
        / "reports"
        / "runs"
        / v2_run_id
        / "f_supplement_release"
        / "summary.json"
    )
    if v2_release.exists() or v2_release.is_symlink():
        v2 = _validate_supplement_release(root, contract, supplement_index=1)
        v2["readiness_mode"] = "release_complete"
    else:
        child_pgid_path = lock_root / "child_pgid_318350"
        if child_pgid_path.is_symlink() or not child_pgid_path.is_file():
            raise RuntimeError("v2 is not released and child_pgid_318350 is not regular")
        child_pgid_text = child_pgid_path.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[1-9][0-9]*", child_pgid_text) is None:
            raise RuntimeError("v2 child PGID must be one positive integer")
        run_cmd_path = lock_root / "run_cmd_318350.sh"
        _require_sha(
            run_cmd_path,
            expected_supplement_run_cmd_sha256,
            "active supplement run_cmd",
        )
        query = scheduler_state_query or _query_slurm_job_state
        scheduler_state = query(318350)
        if scheduler_state != "RUNNING":
            raise RuntimeError(
                f"v2 supplement is not a trusted active RUNNING job: {scheduler_state!r}"
            )
        v2 = {
            "status": "success",
            "run_id": v2_run_id,
            "readiness_mode": "trusted_active_process",
            "job_id": 318350,
            "scheduler_state": scheduler_state,
            "child_pgid": int(child_pgid_text),
            "run_cmd_path": str(run_cmd_path),
            "run_cmd_sha256": expected_supplement_run_cmd_sha256,
        }
    return {
        "schema_version": 1,
        "status": "success",
        "event": "formal_stage_f_signal11_readiness",
        "formal_run_id": contract.formal_run_id,
        "supplement_v1": v1,
        "supplement_v2": v2,
    }


def validate_signal11_apply_preconditions(
    process_audit_path: Path,
    *,
    expected_process_audit_sha256: str,
    lock_root: Path,
    now: datetime | None = None,
    max_age_seconds: float = 900.0,
) -> dict[str, Any]:
    """
    绑定 apply 前的跨节点零进程快照与两组精确 try/after 锁。

    输入参数:
        - process_audit_path: Path, canonical process-audit ``capture`` 生成的 JSON
        - expected_process_audit_sha256: str, 本次快照的受信 SHA-256
        - lock_root: Path, job 316116/318350 精确锁所在目录
        - now: datetime | None, 测试注入的当前 UTC 时间；生产环境省略
        - max_age_seconds: float, 快照允许的最大年龄

    输出:
        - summary: dict[str, Any], 包含审计身份、年龄和当前锁快照
    """
    if re.fullmatch(r"[0-9a-f]{64}", expected_process_audit_sha256) is None:
        raise ValueError("expected process-audit SHA-256 must be lowercase hex")
    _require_sha(process_audit_path, expected_process_audit_sha256, "process audit")
    audit = json.loads(process_audit_path.read_text(encoding="utf-8"))
    if not isinstance(audit, dict):
        raise RuntimeError("process audit must be one JSON object")
    expected_jobs = [316116, 318350]
    expected_nodes = {"316116": "cnode04", "318350": "cnode01"}
    process_audit_script = Path(__file__).resolve().with_name("stage_f_process_audit.py")
    expected_implementation = implementation_identity(process_audit_script)
    if (
        audit.get("schema_version") != PROCESS_AUDIT_SCHEMA_VERSION
        or audit.get("status") != "success"
        or audit.get("job_ids") != expected_jobs
        or audit.get("job_nodes") != expected_nodes
        or str(audit.get("controller_node", "")).split(".", 1)[0].lower() != "master"
        or any(
            audit.get(field) != value
            for field, value in expected_implementation.items()
        )
    ):
        raise RuntimeError("process audit identity/status does not match the frozen jobs")
    for field in (
        "active_stage_f_processes",
        "active_inventory_or_cleanup_processes",
        "active_opaque_stdin_python_processes",
        "scan_error_count",
        "scheduler_exit_code",
    ):
        if type(audit.get(field)) is not int or audit[field] != 0:
            raise RuntimeError(f"process audit is not quiescent: {field}={audit.get(field)!r}")
    job_checks = audit.get("job_checks")
    if not isinstance(job_checks, dict) or set(job_checks) != {"316116", "318350"}:
        raise RuntimeError("process audit must contain the two exact job checks")
    controller_check = audit.get("controller_check")
    checks = [controller_check, *job_checks.values()]
    if len(checks) != 3 or any(not isinstance(check, dict) for check in checks):
        raise RuntimeError("process audit must contain controller plus two job checks")
    for check in checks:
        if (
            check.get("probe_exit_code") != 0
            or check.get("scan_error_count") != 0
            or check.get("probe_stderr") != ""
            or check.get("active_stage_f_processes") != 0
            or check.get("active_inventory_or_cleanup_processes") != 0
            or check.get("active_opaque_stdin_python_processes") != 0
        ):
            raise RuntimeError(f"process audit contains a non-quiescent probe: {check}")
    if (
        controller_check.get("node") != "master"
        or controller_check.get("reported_node") != "master"
        or controller_check.get("job_id") is not None
    ):
        raise RuntimeError("process audit controller probe identity drifted")
    for job_id, node in expected_nodes.items():
        check = job_checks[job_id]
        if (
            check.get("job_id") != int(job_id)
            or check.get("node") != node
            or check.get("reported_node") != node
        ):
            raise RuntimeError(f"process audit job probe identity drifted: {job_id}")
    captured_at_raw = audit.get("captured_at")
    if not isinstance(captured_at_raw, str):
        raise RuntimeError("process audit lacks captured_at")
    try:
        captured_at = datetime.fromisoformat(captured_at_raw)
    except ValueError as exc:
        raise RuntimeError("process audit captured_at is not ISO-8601") from exc
    if captured_at.tzinfo is None:
        raise RuntimeError("process audit captured_at must be timezone-aware")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_seconds = (current - captured_at.astimezone(timezone.utc)).total_seconds()
    if age_seconds < -30 or age_seconds > max_age_seconds:
        raise RuntimeError(f"process audit freshness window failed: age={age_seconds:.3f}s")

    lock_snapshot: dict[str, dict[str, str]] = {}
    for job_id in expected_jobs:
        lock_snapshot[str(job_id)] = {}
        for kind in ("after", "try"):
            path = lock_root / f"{kind}_lock_{job_id}"
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"required {kind} lock is not regular: {path}")
            lock_snapshot[str(job_id)][kind] = "regular"
        for kind in ("kill", "pre"):
            path = lock_root / f"{kind}_lock_{job_id}"
            if path.exists() or path.is_symlink():
                raise RuntimeError(f"forbidden {kind} lock exists: {path}")
            lock_snapshot[str(job_id)][kind] = "absent"
        child_pgid_path = lock_root / f"child_pgid_{job_id}"
        if child_pgid_path.exists() or child_pgid_path.is_symlink():
            raise RuntimeError(f"child PGID registration must be absent: {child_pgid_path}")
        lock_snapshot[str(job_id)]["child_pgid"] = "absent"
    return {
        "schema_version": 1,
        "status": "success",
        "process_audit_path": str(process_audit_path),
        "process_audit_sha256": expected_process_audit_sha256,
        "process_audit_captured_at": captured_at_raw,
        "process_audit_age_seconds": age_seconds,
        "lock_snapshot": lock_snapshot,
    }


def _validate_supplement_release(
    root: Path,
    contract: Signal11TransitionContract,
    *,
    supplement_index: int,
) -> dict[str, Any]:
    """验证一轮 supplement 的冻结 IDs、唯一终态、六条 provenance 与 release。"""
    run_id = contract.supplement_run_ids[supplement_index]
    ids_path = root / contract.supplement_ids_relative_paths[supplement_index]
    expected_ids_sha = contract.expected_supplement_ids_sha256[supplement_index]
    expected_count = contract.expected_supplement_counts[supplement_index]
    _require_sha(ids_path, expected_ids_sha, f"{run_id} frozen IDs")
    ids = [line.strip().lower() for line in ids_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if (
        len(ids) != expected_count
        or len(ids) != len(set(ids))
        or any(re.fullmatch(r"[0-9a-z]{4}", pdb_id) is None for pdb_id in ids)
        or not set(SIGNAL11_IDS).issubset(ids)
    ):
        raise RuntimeError(f"{run_id} frozen IDs are not the expected unique universe")
    expected_ids = set(ids)
    statuses, status_paths = load_stage_statuses(root, run_id, "stage_f", expected_ids)
    known_ids = {
        pdb_id
        for pdb_id, record in statuses.items()
        if record["status"] == StageStatus.KNOWN_FAILED.value
    }
    if known_ids != set(SIGNAL11_IDS):
        raise RuntimeError(f"{run_id} known IDs mismatch: {sorted(known_ids)}")
    if any(
        record["status"] not in {StageStatus.SUCCESS.value, StageStatus.SKIPPED.value}
        for pdb_id, record in statuses.items()
        if pdb_id not in SIGNAL11_IDS
    ):
        raise RuntimeError(f"{run_id} contains a nonterminal/noneligible status")
    exclusions, manifest_sha = load_run_exclusions(root, run_id, "stage_f")
    if set(exclusions) != set(SIGNAL11_IDS) or manifest_sha is None:
        raise RuntimeError(f"{run_id} must load exactly six signal-11 exclusions")
    for pdb_id in SIGNAL11_IDS:
        expected_fields = exclusion_status_fields(
            exclusions[pdb_id],
            manifest_sha256=manifest_sha,
        )
        record = statuses[pdb_id]
        if (
            record.get("status") != StageStatus.KNOWN_FAILED.value
            or expected_fields["exclusion_reason"] != "chimera_full_grid_cc_signal11"
            or any(record.get(field) != value for field, value in expected_fields.items())
        ):
            raise RuntimeError(f"{run_id} exclusion status provenance mismatch: {pdb_id}")

    release_path = (
        root / "reports" / "runs" / run_id / "f_supplement_release" / "summary.json"
    )
    if release_path.is_symlink() or not release_path.is_file():
        raise RuntimeError(f"{run_id} release summary is missing or not regular")
    release = json.loads(release_path.read_text(encoding="utf-8"))
    status_counts = dict(sorted(Counter(row["status"] for row in statuses.values()).items()))
    if (
        not isinstance(release, dict)
        or release.get("status") != "success"
        or release.get("run_id") != run_id
        or release.get("gate_name") != "f_supplement_release"
        or release.get("stages") != ["stage_f"]
        or release.get("n_expected_pdb") != expected_count
        or release.get("status_counts") != {"stage_f": status_counts}
        or release.get("known_failure_reasons")
        != {"stage_f:run_policy_excluded": len(SIGNAL11_IDS)}
        or release.get("exclusion_manifest_sha256") != {"stage_f": manifest_sha}
    ):
        raise RuntimeError(f"{run_id} release summary disagrees with statuses/manifests")
    return {
        "status": "success",
        "run_id": run_id,
        "n_expected_pdb": expected_count,
        "n_signal11_known": len(SIGNAL11_IDS),
        "ids_path": str(ids_path),
        "ids_sha256": expected_ids_sha,
        "status_paths": [str(path) for path in status_paths],
        "status_sha256": {str(path): sha256_file(path) for path in status_paths},
        "release_path": str(release_path),
        "release_sha256": sha256_file(release_path),
        "exclusion_manifest_sha256": manifest_sha,
    }


def _query_slurm_job_state(job_id: int) -> str:
    """查询一个既有 Slurm job 的唯一当前状态，供 formal readiness 使用。"""
    completed = subprocess.run(
        ["squeue", "-h", "-j", str(job_id), "-o", "%T"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    states = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if completed.returncode != 0 or completed.stderr or len(states) != 1:
        raise RuntimeError(
            f"failed to obtain one scheduler state for job {job_id}: "
            f"exit={completed.returncode} states={states} stderr={completed.stderr!r}"
        )
    return states[0]


def _signal11_record(
    pdb_id: str,
    *,
    run_id: str,
    root: Path,
    contract: Signal11TransitionContract,
) -> dict[str, Any]:
    """构造一个不含 timeout/success 伪语义的 Stage F-only 决策。"""
    formal_evidence_dir = (
        root
        / "reports"
        / "runs"
        / contract.formal_run_id
        / "stage_f_signal11_exclusion_20260717_v1"
    )
    evidence = {
        "stage": "stage_f",
        "failure_mode": "external_tool_signal_11",
        "legacy_operation": (
            "FitMap.map_overlap_and_correlation(experimental_map,simulated_map,False)"
        ),
        "supplement_v1_status_before_path": str(
            formal_evidence_dir / "supplement_v1_status.before.jsonl"
        ),
        "supplement_v1_status_before_sha256": contract.expected_status_before_sha256,
        "n_jobs1_shadow_acceptance_path": str(
            root / contract.n_jobs1_acceptance_relative_path
        ),
        "n_jobs1_shadow_acceptance_sha256": (
            contract.expected_n_jobs1_acceptance_sha256
        ),
        "fresh_all_only_acceptance_path": str(
            root / contract.all_only_acceptance_relative_path
        ),
        "fresh_all_only_acceptance_sha256": (
            contract.expected_all_only_acceptance_sha256
        ),
        "fresh_all_only_reproduced_pdb_id": "9fkb",
        "public_quality_trio_complete": False,
        "public_quality_artifacts_created_by_decision": False,
    }
    if run_id == contract.formal_run_id:
        evidence["authorized_exclusion_cap"] = contract.exclusion_cap
    else:
        evidence.update(
            source_formal_run_id=contract.formal_run_id,
            formal_run_authorized_exclusion_cap=contract.exclusion_cap,
            supplement_manifest_role="propagate_formal_run_decision_for_real_rerun_gate",
        )
    return {
        "schema_version": 1,
        "pdb_id": pdb_id,
        "run_id": run_id,
        "stages": ["stage_f"],
        "reason": "chimera_full_grid_cc_signal11",
        "detail": (
            f"{pdb_id} reproducibly exited by signal 11 in the legacy UCSF Chimera "
            "full-grid ALL correlation path; the user authorized a current-run-only "
            "exclusion without placeholder quality artifacts"
        ),
        "authorization": contract.authorization,
        "decision_scope": "current_run_only",
        "downstream_policy": "exclude_from_training_and_inference",
        "evidence": evidence,
    }


def _resolve_before_bytes(
    live_path: Path,
    evidence_path: Path,
    *,
    expected_sha256: str,
) -> bytes:
    """首次从 live 路径取旧字节；迁移后只允许复用冻结的 before 证据。"""
    for path in (live_path, evidence_path):
        if path.is_symlink() or not path.is_file():
            continue
        payload = path.read_bytes()
        if _sha256_bytes(payload) == expected_sha256:
            return payload
    raise RuntimeError(
        f"missing immutable pre-transition bytes with SHA-256 {expected_sha256}"
    )


def _validate_signal11_status(payload: bytes) -> None:
    """要求旧补算状态恰有六条真实 ExternalToolError/-11 unknown。"""
    rows = _records_by_id(payload)
    unknown = {
        pdb_id
        for pdb_id, row in rows.items()
        if row.get("status") == "unknown_failed"
    }
    if unknown != set(SIGNAL11_IDS):
        raise RuntimeError(f"unexpected supplement unknown IDs: {sorted(unknown)}")
    for pdb_id in SIGNAL11_IDS:
        row = rows[pdb_id]
        if (
            row.get("stage") != "stage_f"
            or row.get("reason") != "nonzero_exit"
            or row.get("error_type") != "ExternalToolError"
            or "external tool returned -11" not in str(row.get("error", ""))
        ):
            raise RuntimeError(f"supplement signal-11 evidence drift: {pdb_id}")


def _require_zero_public_trios(root: Path) -> dict[str, dict[str, bool]]:
    """确认六例仍为 0/3；本函数和整个迁移都不会创建这些路径。"""
    snapshot: dict[str, dict[str, bool]] = {}
    for pdb_id in SIGNAL11_IDS:
        paths = {
            f"quality/{pdb_id}.jsonl": root / "quality" / f"{pdb_id}.jsonl",
            f"quality/{pdb_id}.provenance.json": (
                root / "quality" / f"{pdb_id}.provenance.json"
            ),
            f"quality_atoms/{pdb_id}.npz": (
                root / "quality_atoms" / f"{pdb_id}.npz"
            ),
        }
        snapshot[pdb_id] = {}
        for name, path in paths.items():
            exists = path.exists() or path.is_symlink()
            snapshot[pdb_id][name] = exists
            if exists:
                raise RuntimeError(
                    f"signal-11 exclusion refuses an existing public quality artifact: {path}"
                )
    return snapshot


def _records_by_id(payload: bytes) -> dict[str, dict[str, Any]]:
    """读取 JSONL 字节并按唯一小写 PDB ID 建索引。"""
    records: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(payload.decode("utf-8").splitlines()):
        if not line.strip():
            continue
        record = json.loads(line)
        pdb_id = str(record.get("pdb_id", "")).lower()
        if not pdb_id or pdb_id in records:
            raise RuntimeError(f"duplicate or empty PDB ID at JSONL row {index}")
        records[pdb_id] = record
    if not records:
        raise RuntimeError("JSONL evidence must not be empty")
    return records


def _encode_jsonl(records: dict[str, dict[str, Any]]) -> bytes:
    """按 PDB ID 排序并用稳定紧凑格式编码 manifest。"""
    return b"".join(
        (
            json.dumps(
                records[pdb_id],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        for pdb_id in sorted(records)
    )


def _encode_json(value: dict[str, Any]) -> bytes:
    """编码稳定、面向人工审计的 JSON。"""
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    """计算内存字节的 SHA-256。"""
    return hashlib.sha256(payload).hexdigest()


def _require_sha(path: Path, expected: str, label: str) -> None:
    """要求只读证据为普通文件且内容身份匹配。"""
    if path.is_symlink() or not path.is_file() or sha256_file(path) != expected:
        raise RuntimeError(f"{label} SHA-256 drift: {path}")


def _write_immutable(path: Path, payload: bytes) -> None:
    """首次同目录原子写入；重放只接受逐字节相同内容。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        _require_bytes(path, payload, "immutable evidence")
        return
    _atomic_write(path, payload)


def _replace_if_before_or_equal(
    path: Path,
    payload: bytes,
    *,
    allowed_before_sha256: str,
) -> None:
    """仅允许从冻结旧身份迁移，或接受已完成的幂等重放。"""
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"manifest must be a regular file: {path}")
    current = path.read_bytes()
    if current == payload:
        return
    if _sha256_bytes(current) != allowed_before_sha256:
        raise RuntimeError(f"manifest drift before signal-11 transition: {path}")
    _atomic_write(path, payload)


def _replace_if_absent_or_equal(path: Path, payload: bytes) -> None:
    """补算 run 只允许首次创建自己的 manifest，或逐字节幂等重放。"""
    if path.exists() or path.is_symlink():
        _require_bytes(path, payload, "supplement exclusion manifest")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, payload)


def _require_bytes(path: Path, expected: bytes, label: str) -> None:
    """要求普通文件逐字节等于冻结内容。"""
    if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
        raise RuntimeError(f"{label} drift: {path}")


def _atomic_write(path: Path, payload: bytes) -> None:
    """在目标目录内写当前进程独占临时文件，再原子替换目标。"""
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}.{uuid4().hex}")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    """解析窄入口参数并输出确定性迁移摘要。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("apply", "validate", "readiness"),
        required=True,
    )
    parser.add_argument("--process_audit", type=Path)
    parser.add_argument("--process_audit_sha256")
    parser.add_argument("--lock_root", type=Path, default=Path("/home/penghongen"))
    parser.add_argument("--expected_supplement_run_cmd_sha256")
    args = parser.parse_args()
    if args.mode == "apply":
        if args.process_audit is None or args.process_audit_sha256 is None:
            parser.error("apply requires --process_audit and --process_audit_sha256")
        preconditions = validate_signal11_apply_preconditions(
            args.process_audit,
            expected_process_audit_sha256=args.process_audit_sha256,
            lock_root=args.lock_root,
        )
        transition = apply_or_validate_signal11_transition(args.root, mode="apply")
        evidence_path = (
            args.root
            / "reports"
            / "runs"
            / DEFAULT_CONTRACT.formal_run_id
            / "stage_f_signal11_exclusion_20260717_v1"
            / "apply_preconditions.json"
        )
        _write_immutable(
            evidence_path,
            _encode_json(
                {
                    **preconditions,
                    "transition_summary_sha256": _sha256_bytes(_encode_json(transition)),
                }
            ),
        )
        summary = {
            "status": "success",
            "transition": transition,
            "apply_preconditions": preconditions,
            "apply_preconditions_path": str(evidence_path),
            "apply_preconditions_sha256": sha256_file(evidence_path),
        }
    elif args.mode == "readiness":
        if args.expected_supplement_run_cmd_sha256 is None:
            parser.error(
                "readiness requires --expected_supplement_run_cmd_sha256"
            )
        summary = validate_formal_signal11_readiness(
            args.root,
            expected_supplement_run_cmd_sha256=(
                args.expected_supplement_run_cmd_sha256
            ),
            lock_root=args.lock_root,
        )
    else:
        summary = apply_or_validate_signal11_transition(args.root, mode="validate")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
