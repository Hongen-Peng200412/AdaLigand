"""六个祖传 Chimera ALL signal-11 样本的 run-scoped 迁移与恢复测试。"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import subprocess
import sys

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CODE_ROOT = PROJECT_ROOT / "code"
SCRIPTS_ROOT = PROJECT_ROOT / "scripts"
SBATCH_ROOT = PROJECT_ROOT / "sbatch"
sys.path.insert(0, str(CODE_ROOT))
sys.path.insert(0, str(SCRIPTS_ROOT))

from exclusions import exclusion_status_fields, load_run_exclusions
import f_signal11_exclusion_transition as transition_module
from f_signal11_exclusion_transition import (
    DEFAULT_CONTRACT,
    DEFAULT_EXTENDED_CONTRACT,
    PHASE2_ALL_EXCLUSION_IDS,
    PHASE2_ATTEMPT_IDS,
    PHASE2_IDS,
    PHASE2_MOLMAP_TIMEOUT_DETAILS,
    PHASE2_MOLMAP_TIMEOUT_IDS,
    PHASE2_SIGNAL11_IDS,
    SIGNAL11_IDS,
    ExtendedExclusionTransitionContract,
    Signal11TransitionContract,
    apply_or_validate_extended_exclusion_transition,
    apply_signal11_transition_with_preconditions,
    apply_or_validate_signal11_transition,
    validate_formal_extended_readiness,
    validate_formal_signal11_readiness,
    validate_signal11_apply_preconditions,
)
from filtering import run_stage_g
from io_utils import read_jsonl, sha256_file, write_jsonl
from reports import stage_report_path, stage_result, write_report, write_stage_results
from stage_f_process_audit import implementation_identity


def _record(pdb_id: str, *, run_id: str = "formal") -> dict:
    """创建一个可被正式 loader 验证的最小 run-only 记录。"""
    return {
        "schema_version": 1,
        "pdb_id": pdb_id,
        "run_id": run_id,
        "stages": ["stage_e", "stage_f"],
        "reason": "existing_decision",
        "detail": f"existing fixture {pdb_id}",
        "authorization": "user_explicit_fixture",
        "decision_scope": "current_run_only",
        "downstream_policy": "exclude_from_training_and_inference",
        "evidence": {"fixture": True},
    }


def _prepare_root(tmp_path: Path) -> tuple[Path, Signal11TransitionContract]:
    """建立 base4、Stage F五条、六条-11状态及两轮 shadow 证据。"""
    root = tmp_path / "root"
    formal_dir = root / "reports" / "runs" / "formal"
    base_records = [_record(pdb_id) for pdb_id in ("8ckb", "8glv", "9e5c", "9fqr")]
    stage_f_records = [
        *base_records,
        {
            **_record("6kgx"),
            "stages": ["stage_f"],
            "reason": "existing_stage_f_long_tail",
        },
    ]
    base_path = formal_dir / "exclusions.jsonl"
    stage_f_path = formal_dir / "exclusions.stage_f.jsonl"
    write_jsonl(base_path, base_records)
    write_jsonl(stage_f_path, stage_f_records)

    status_path = root / "reports" / "runs" / "supp1" / "stage_f" / "status.jsonl"
    write_jsonl(
        status_path,
        [
            {
                "pdb_id": pdb_id,
                "stage": "stage_f",
                "status": "unknown_failed",
                "reason": "nonzero_exit",
                "error_type": "ExternalToolError",
                "error": f"external tool returned -11; fixture={pdb_id}",
            }
            for pdb_id in SIGNAL11_IDS
        ],
    )
    n_jobs1 = formal_dir / "shadow_n_jobs1" / "acceptance.json"
    all_only = formal_dir / "shadow_all_only" / "acceptance.json"
    n_jobs1.parent.mkdir(parents=True)
    all_only.parent.mkdir(parents=True)
    n_jobs1.write_text('{"status":"ACCEPTED","six_of_six":true}\n', encoding="utf-8")
    all_only.write_text('{"status":"ACCEPTED","pdb_id":"9fkb"}\n', encoding="utf-8")
    supplement_ids_paths = (
        root / "reports" / "runs" / "supp1" / "frozen_ids.txt",
        root / "reports" / "runs" / "supp2" / "frozen_ids.txt",
    )
    for path in supplement_ids_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(f"{pdb_id}\n" for pdb_id in SIGNAL11_IDS),
            encoding="utf-8",
        )

    contract = Signal11TransitionContract(
        formal_run_id="formal",
        supplement_run_ids=("supp1", "supp2"),
        authorization="user_explicit_fixture_signal11_cap30",
        exclusion_cap=30,
        expected_base_sha256=sha256_file(base_path),
        expected_formal_before_sha256=sha256_file(stage_f_path),
        status_before_relative_path=str(status_path.relative_to(root)),
        expected_status_before_sha256=sha256_file(status_path),
        n_jobs1_acceptance_relative_path=str(n_jobs1.relative_to(root)),
        expected_n_jobs1_acceptance_sha256=sha256_file(n_jobs1),
        all_only_acceptance_relative_path=str(all_only.relative_to(root)),
        expected_all_only_acceptance_sha256=sha256_file(all_only),
        supplement_ids_relative_paths=tuple(
            str(path.relative_to(root)) for path in supplement_ids_paths
        ),
        expected_supplement_ids_sha256=tuple(
            sha256_file(path) for path in supplement_ids_paths
        ),
        expected_supplement_counts=(len(SIGNAL11_IDS), len(SIGNAL11_IDS)),
    )
    return root, contract


def _prepare_phase2_root(
    tmp_path: Path,
) -> tuple[Path, ExtendedExclusionTransitionContract]:
    """从已闭合旧六条迁移构造 formal11、v1旧六、v2旧六和八条 unknown。"""
    root, phase1 = _prepare_root(tmp_path)
    v2_ids_path = root / phase1.supplement_ids_relative_paths[1]
    v2_ids_path.write_text(
        "".join(f"{pdb_id}\n" for pdb_id in PHASE2_ALL_EXCLUSION_IDS),
        encoding="utf-8",
    )
    phase1 = Signal11TransitionContract(
        **{
            **phase1.__dict__,
            "expected_supplement_ids_sha256": (
                phase1.expected_supplement_ids_sha256[0],
                sha256_file(v2_ids_path),
            ),
            "expected_supplement_counts": (
                phase1.expected_supplement_counts[0],
                len(PHASE2_ALL_EXCLUSION_IDS),
            ),
        }
    )
    apply_or_validate_signal11_transition(root, mode="apply", contract=phase1)

    v2_run_id = phase1.supplement_run_ids[1]
    status_path = stage_report_path(root, v2_run_id, "stage_f", 0, 1)
    attempt_ids = dict(PHASE2_ATTEMPT_IDS)
    status_rows = [
        {
            "pdb_id": pdb_id,
            "stage": "stage_f",
            "status": "known_failed",
            "reason": "run_policy_excluded",
        }
        for pdb_id in SIGNAL11_IDS
    ]
    status_rows.extend(
        {
            "pdb_id": pdb_id,
            "stage": "stage_f",
            "status": "unknown_failed",
            "reason": "nonzero_exit",
            "error_type": "ExternalToolError",
            "error": (
                "external tool returned -11; stdout=/scratch/stage_f/"
                f"{pdb_id}/{attempt_ids[pdb_id]}/correlation.stdout.log; "
                "stderr=/scratch/stage_f/"
                f"{pdb_id}/{attempt_ids[pdb_id]}/correlation.stderr.log"
            ),
        }
        for pdb_id in PHASE2_SIGNAL11_IDS
    )
    status_rows.extend(
        {
            "pdb_id": pdb_id,
            "stage": "stage_f",
            "status": "unknown_failed",
            "reason": "timeout",
            "error_type": "ExternalToolError",
            "error": "external tool timed out after 3600.0s",
        }
        for pdb_id in PHASE2_MOLMAP_TIMEOUT_IDS
    )
    write_stage_results(status_path, status_rows)
    status_lines = status_path.read_bytes().splitlines(keepends=True)
    status_line_by_id = {
        str(json.loads(raw_line).get("pdb_id", "")).lower(): (line_number, raw_line)
        for line_number, raw_line in enumerate(status_lines, start=1)
    }
    evidence_identities = []
    for pdb_id in PHASE2_IDS:
        attempt_dir = (
            root
            / "scratch"
            / v2_run_id
            / "stage_f"
            / pdb_id
            / attempt_ids[pdb_id]
        )
        attempt_dir.mkdir(parents=True)
        prefix = "correlation" if pdb_id in PHASE2_SIGNAL11_IDS else "molmap"
        stdout_path = attempt_dir / f"{prefix}.stdout.log"
        stderr_path = attempt_dir / f"{prefix}.stderr.log"
        stdout_path.write_text(f"fixture stdout {pdb_id}\n", encoding="utf-8")
        stderr_path.write_text(f"fixture stderr {pdb_id}\n", encoding="utf-8")
        line_number, raw_line = status_line_by_id[pdb_id]
        evidence_identities.append(
            (
                pdb_id,
                line_number,
                hashlib.sha256(raw_line).hexdigest(),
                (stdout_path.relative_to(root)).as_posix(),
                sha256_file(stdout_path),
                (stderr_path.relative_to(root)).as_posix(),
                sha256_file(stderr_path),
            )
        )

    formal_manifest = (
        root / "reports" / "runs" / phase1.formal_run_id / "exclusions.stage_f.jsonl"
    )
    v1_manifest = (
        root
        / "reports"
        / "runs"
        / phase1.supplement_run_ids[0]
        / "exclusions.jsonl"
    )
    v2_manifest = (
        root
        / "reports"
        / "runs"
        / phase1.supplement_run_ids[1]
        / "exclusions.jsonl"
    )
    contract = ExtendedExclusionTransitionContract(
        phase1_contract=phase1,
        authorization="user_explicit_fixture_phase2_cap100",
        exclusion_cap=100,
        expected_formal_before_sha256=sha256_file(formal_manifest),
        expected_supplement_v1_sha256=sha256_file(v1_manifest),
        expected_supplement_v2_before_sha256=sha256_file(v2_manifest),
        status_before_relative_path=str(status_path.relative_to(root)),
        expected_status_before_sha256=sha256_file(status_path),
        timeout_details=PHASE2_MOLMAP_TIMEOUT_DETAILS,
        evidence_identities=tuple(evidence_identities),
    )
    return root, contract


def _write_supplement_release_for_ids(
    root: Path,
    contract: Signal11TransitionContract,
    supplement_index: int,
    expected_exclusion_ids: tuple[str, ...],
) -> None:
    """写入与指定 manifest 精确绑定的最小 supplement release 测试夹具。"""
    run_id = contract.supplement_run_ids[supplement_index]
    exclusions, digest = load_run_exclusions(root, run_id, "stage_f")
    assert digest is not None and set(exclusions) == set(expected_exclusion_ids)
    statuses = [
        stage_result(
            pdb_id,
            "stage_f",
            "known_failed",
            **exclusion_status_fields(exclusions[pdb_id], manifest_sha256=digest),
        )
        for pdb_id in expected_exclusion_ids
    ]
    write_stage_results(stage_report_path(root, run_id, "stage_f", 0, 1), statuses)
    write_report(
        root / "reports" / "runs" / run_id / "f_supplement_release" / "summary.json",
        {
            "status": "success",
            "run_id": run_id,
            "gate_name": "f_supplement_release",
            "stages": ["stage_f"],
            "n_expected_pdb": len(expected_exclusion_ids),
            "status_counts": {
                "stage_f": {"known_failed": len(expected_exclusion_ids)}
            },
            "known_failure_reasons": {
                "stage_f:run_policy_excluded": len(expected_exclusion_ids)
            },
            "exclusion_manifest_sha256": {"stage_f": digest},
        },
    )


def _write_supplement_release(
    root: Path,
    contract: Signal11TransitionContract,
    supplement_index: int,
) -> list[dict]:
    """写一轮完整的六条 manifest-bound known 状态及其 release summary。"""
    run_id = contract.supplement_run_ids[supplement_index]
    exclusions, digest = load_run_exclusions(root, run_id, "stage_f")
    assert digest is not None
    statuses = [
        stage_result(
            pdb_id,
            "stage_f",
            "known_failed",
            **exclusion_status_fields(exclusions[pdb_id], manifest_sha256=digest),
        )
        for pdb_id in SIGNAL11_IDS
    ]
    status_path = stage_report_path(root, run_id, "stage_f", 0, 1)
    write_stage_results(status_path, statuses)
    write_report(
        root / "reports" / "runs" / run_id / "f_supplement_release" / "summary.json",
        {
            "status": "success",
            "run_id": run_id,
            "gate_name": "f_supplement_release",
            "stages": ["stage_f"],
            "n_expected_pdb": len(SIGNAL11_IDS),
            "status_counts": {"stage_f": {"known_failed": len(SIGNAL11_IDS)}},
            "known_failure_reasons": {
                "stage_f:run_policy_excluded": len(SIGNAL11_IDS)
            },
            "exclusion_manifest_sha256": {"stage_f": digest},
            "policy": "known_failed continues explicitly",
        },
    )
    return statuses


def _process_audit_payload(captured_at: datetime) -> dict:
    """构造与 canonical schema v3 同形的最小零进程审计测试夹具。"""
    def check(node: str, job_id: int | None) -> dict:
        """构造一个零进程、零 stderr 的 controller/allocation probe。"""
        return {
            "scope": "controller" if job_id is None else "allocation",
            "job_id": job_id,
            "node": node,
            "reported_node": node,
            "active_stage_f_processes": 0,
            "active_inventory_or_cleanup_processes": 0,
            "active_opaque_stdin_python_processes": 0,
            "scan_error_count": 0,
            "probe_exit_code": 0,
            "probe_stderr": "",
        }

    return {
        "schema_version": 3,
        "status": "success",
        "captured_at": captured_at.isoformat(),
        "job_ids": [316116, 318350],
        "job_nodes": {"316116": "cnode04", "318350": "cnode01"},
        "controller_node": "master",
        **implementation_identity(SCRIPTS_ROOT / "stage_f_process_audit.py"),
        "active_stage_f_processes": 0,
        "active_inventory_or_cleanup_processes": 0,
        "active_opaque_stdin_python_processes": 0,
        "observed_opaque_stdin_python_processes": 0,
        "authorized_controller_opaque_specs": [],
        "authorized_controller_opaque_processes": [],
        "blocking_controller_opaque_processes": [],
        "scan_error_count": 0,
        "scheduler_exit_code": 0,
        "controller_check": check("master", None),
        "job_checks": {
            "316116": check("cnode04", 316116),
            "318350": check("cnode01", 318350),
        },
    }


def test_production_contract_freezes_real_supplement_universes() -> None:
    """生产 readiness 始终绑定 v1=2990、v2=5984 及两份冻结 IDs 身份。"""
    assert DEFAULT_CONTRACT.expected_supplement_counts == (2990, 5984)
    assert DEFAULT_CONTRACT.expected_supplement_ids_sha256 == (
        "acacde79c2a5a8727949cdc0a986930aa8404419a8edaabfb264f4f05dacea80",
        "7f427993c3a2e8c2e147e8c40b9b83423b932e2275066ccd010efbbf79617c6c",
    )
    assert all(
        path.endswith("pdb_ids.txt")
        for path in DEFAULT_CONTRACT.supplement_ids_relative_paths
    )


def test_extended_production_contract_keeps_phase1_bytes_and_freezes_v2_status() -> None:
    """生产 Phase-2 契约只扩展 formal/v2，仍精确冻结 base4、v1旧六与 v2 状态。"""
    assert SIGNAL11_IDS == ("9bw7", "9c1k", "9dgr", "9fkb", "9mxv", "9nw3")
    assert DEFAULT_EXTENDED_CONTRACT.expected_supplement_v1_sha256 == (
        "6f3a0a880e6e38768e1e096b2bcb776087372be56987b4a930c88306b5527f35"
    )
    assert DEFAULT_EXTENDED_CONTRACT.expected_formal_before_sha256 == (
        "10c5d923779645a6eeeeb5d277722e6f487593557c095cfcdef641553613c8ac"
    )
    assert DEFAULT_EXTENDED_CONTRACT.expected_supplement_v2_before_sha256 == (
        "43da55a71885730458cab546f6eb96e38722b726445eaf3613873f23e74b7d40"
    )
    assert DEFAULT_EXTENDED_CONTRACT.expected_status_before_sha256 == (
        "3231dfe56403444c37ac962835c7ced2b97b13eb49cde5a934ad74b2330bb23e"
    )
    assert DEFAULT_EXTENDED_CONTRACT.exclusion_cap == 100
    assert DEFAULT_CONTRACT.exclusion_cap == 30
    assert len(PHASE2_IDS) == 8
    assert len(PHASE2_ALL_EXCLUSION_IDS) == 14
    assert all(
        re.fullmatch(r"[0-9a-f]{32}", attempt_id)
        for _pdb_id, attempt_id in PHASE2_ATTEMPT_IDS
    )
    assert {item[0] for item in DEFAULT_EXTENDED_CONTRACT.evidence_identities} == set(
        PHASE2_IDS
    )
    attempt_ids = dict(PHASE2_ATTEMPT_IDS)
    assert all(
        f"/{attempt_ids[item[0]]}/" in item[3]
        and f"/{attempt_ids[item[0]]}/" in item[5]
        for item in DEFAULT_EXTENDED_CONTRACT.evidence_identities
    )
    assert all(item[1] > 0 for item in DEFAULT_EXTENDED_CONTRACT.evidence_identities)
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", digest)
        for item in DEFAULT_EXTENDED_CONTRACT.evidence_identities
        for digest in (item[2], item[4], item[6])
    )


def test_extended_transition_changes_only_formal_and_v2_with_true_failure_classes(
    tmp_path: Path,
) -> None:
    """Phase-2 保留 base/v1 字节及旧记录，仅把正式和 v2 扩展为19/14条。"""
    root, contract = _prepare_phase2_root(tmp_path)
    phase1 = contract.phase1_contract
    base_path = root / "reports" / "runs" / phase1.formal_run_id / "exclusions.jsonl"
    formal_path = base_path.with_name("exclusions.stage_f.jsonl")
    v1_path = (
        root / "reports" / "runs" / phase1.supplement_run_ids[0] / "exclusions.jsonl"
    )
    v2_path = (
        root / "reports" / "runs" / phase1.supplement_run_ids[1] / "exclusions.jsonl"
    )
    base_before = base_path.read_bytes()
    v1_before = v1_path.read_bytes()
    formal_before = {row["pdb_id"]: row for row in read_jsonl(formal_path)}
    v2_before = {row["pdb_id"]: row for row in read_jsonl(v2_path)}

    summary = apply_or_validate_extended_exclusion_transition(
        root,
        mode="apply",
        contract=contract,
    )
    assert base_path.read_bytes() == base_before
    assert v1_path.read_bytes() == v1_before
    formal_after = {row["pdb_id"]: row for row in read_jsonl(formal_path)}
    v2_after = {row["pdb_id"]: row for row in read_jsonl(v2_path)}
    assert len(formal_after) == 19
    assert len(v2_after) == 14
    assert all(formal_after[pdb_id] == row for pdb_id, row in formal_before.items())
    assert all(v2_after[pdb_id] == row for pdb_id, row in v2_before.items())
    for pdb_id in PHASE2_SIGNAL11_IDS:
        assert formal_after[pdb_id]["reason"] == "chimera_full_grid_cc_signal11"
        assert formal_after[pdb_id]["evidence"]["failure_mode"] == "external_tool_signal_11"
    timeout_details = dict(PHASE2_MOLMAP_TIMEOUT_DETAILS)
    for pdb_id in PHASE2_MOLMAP_TIMEOUT_IDS:
        record = formal_after[pdb_id]
        assert record["reason"] == "chimera_molmap_timeout_3600s"
        assert record["evidence"]["failure_mode"] == "external_tool_timeout"
        assert record["evidence"]["timeout_seconds"] == 3600.0
        assert record["evidence"]["diagnostic_detail"] == timeout_details[pdb_id]
    assert summary["authorized_exclusion_cap"] == 100
    assert summary["added_signal11_ids"] == list(PHASE2_SIGNAL11_IDS)
    assert summary["added_molmap_timeout_ids"] == list(PHASE2_MOLMAP_TIMEOUT_IDS)
    assert apply_or_validate_extended_exclusion_transition(
        root,
        mode="validate",
        contract=contract,
    ) == summary
    for pdb_id in PHASE2_IDS:
        assert not (root / "quality" / f"{pdb_id}.jsonl").exists()
        assert not (root / "quality" / f"{pdb_id}.provenance.json").exists()
        assert not (root / "quality_atoms" / f"{pdb_id}.npz").exists()


def test_extended_transition_replays_after_second_target_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """第二目标替换中断时保留可解释半提交，并能从 journal 幂等闭合。"""
    root, contract = _prepare_phase2_root(tmp_path)
    phase1 = contract.phase1_contract
    formal_path = (
        root / "reports" / "runs" / phase1.formal_run_id / "exclusions.stage_f.jsonl"
    )
    v1_path = (
        root / "reports" / "runs" / phase1.supplement_run_ids[0] / "exclusions.jsonl"
    )
    v2_path = (
        root / "reports" / "runs" / phase1.supplement_run_ids[1] / "exclusions.jsonl"
    )
    v1_before = v1_path.read_bytes()
    original_replace = transition_module.os.replace
    failed = False

    def fail_once(source: str | Path, destination: str | Path) -> None:
        """只在补算 v2 live target 的首次提交处模拟进程中断。"""
        nonlocal failed
        if Path(destination) == v2_path and not failed:
            failed = True
            raise OSError("fixture interrupted second live replacement")
        original_replace(source, destination)

    monkeypatch.setattr(transition_module.os, "replace", fail_once)
    with pytest.raises(OSError, match="interrupted second live replacement"):
        apply_or_validate_extended_exclusion_transition(
            root,
            mode="apply",
            contract=contract,
        )
    assert len(read_jsonl(formal_path)) == 19
    assert len(read_jsonl(v2_path)) == 6
    assert v1_path.read_bytes() == v1_before
    assert not list(formal_path.parent.glob("*.tmp.*"))
    assert not list(v2_path.parent.glob("*.tmp.*"))

    monkeypatch.setattr(transition_module.os, "replace", original_replace)
    apply_or_validate_extended_exclusion_transition(
        root,
        mode="apply",
        contract=contract,
    )
    assert len(read_jsonl(formal_path)) == 19
    assert len(read_jsonl(v2_path)) == 14
    assert v1_path.read_bytes() == v1_before


def test_extended_validate_uses_frozen_status_after_live_rerun_overwrites_status(
    tmp_path: Path,
) -> None:
    """补算重跑覆盖 live status 后，validate 必须回退到迁移时冻结的旧八例证据。"""
    root, contract = _prepare_phase2_root(tmp_path)
    expected = apply_or_validate_extended_exclusion_transition(
        root,
        mode="apply",
        contract=contract,
    )
    live_status = root / contract.status_before_relative_path
    write_stage_results(
        live_status,
        [
            {
                "pdb_id": "1abc",
                "stage": "stage_f",
                "status": "success",
                "reason": "complete",
            }
        ],
    )
    assert sha256_file(live_status) != contract.expected_status_before_sha256
    for item in contract.evidence_identities:
        (root / item[3]).unlink()
        (root / item[5]).unlink()
    assert apply_or_validate_extended_exclusion_transition(
        root,
        mode="validate",
        contract=contract,
    ) == expected


def test_extended_transition_rejects_status_or_public_artifact_before_live_write(
    tmp_path: Path,
) -> None:
    """错误分类或任一公开产物均必须在 formal/v2 首次替换前 fail closed。"""
    root, contract = _prepare_phase2_root(tmp_path)
    phase1 = contract.phase1_contract
    formal_path = (
        root / "reports" / "runs" / phase1.formal_run_id / "exclusions.stage_f.jsonl"
    )
    v2_path = (
        root / "reports" / "runs" / phase1.supplement_run_ids[1] / "exclusions.jsonl"
    )
    before = (formal_path.read_bytes(), v2_path.read_bytes())
    artifact = root / "quality" / "7yiu.jsonl"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("real artifact\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="existing public quality artifact"):
        apply_or_validate_extended_exclusion_transition(
            root,
            mode="apply",
            contract=contract,
        )
    assert (formal_path.read_bytes(), v2_path.read_bytes()) == before
    assert artifact.read_text(encoding="utf-8") == "real artifact\n"


def test_extended_transition_rejects_small_log_content_drift_before_live_write(
    tmp_path: Path,
) -> None:
    """八例任一受检 stdout/stderr 内容漂移时，不得写 formal 或 supplement v2。"""
    root, contract = _prepare_phase2_root(tmp_path)
    phase1 = contract.phase1_contract
    formal_path = (
        root / "reports" / "runs" / phase1.formal_run_id / "exclusions.stage_f.jsonl"
    )
    v2_path = (
        root / "reports" / "runs" / phase1.supplement_run_ids[1] / "exclusions.jsonl"
    )
    before = (formal_path.read_bytes(), v2_path.read_bytes())
    first_stdout = root / contract.evidence_identities[0][3]
    first_stdout.write_text("drifted evidence\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="missing immutable pre-transition bytes"):
        apply_or_validate_extended_exclusion_transition(
            root,
            mode="apply",
            contract=contract,
        )
    assert (formal_path.read_bytes(), v2_path.read_bytes()) == before


def test_extended_readiness_requires_v1_old_six_and_v2_new_fourteen_releases(
    tmp_path: Path,
) -> None:
    """正式恢复门分别验证 v1 旧六条与 v2 新十四条真实 manifest-bound release。"""
    root, contract = _prepare_phase2_root(tmp_path)
    apply_or_validate_extended_exclusion_transition(
        root,
        mode="apply",
        contract=contract,
    )
    phase1 = contract.phase1_contract
    _write_supplement_release_for_ids(root, phase1, 0, SIGNAL11_IDS)
    _write_supplement_release_for_ids(
        root,
        phase1,
        1,
        PHASE2_ALL_EXCLUSION_IDS,
    )
    readiness = validate_formal_extended_readiness(root, contract=contract)
    assert readiness["supplement_v1"]["n_run_policy_known"] == 6
    assert readiness["supplement_v2"]["n_run_policy_known"] == 14

    v2_status = stage_report_path(root, phase1.supplement_run_ids[1], "stage_f", 0, 1)
    rows = read_jsonl(v2_status)
    rows[0]["exclusion_reason"] = "timeout"
    write_stage_results(v2_status, rows)
    with pytest.raises(RuntimeError, match="provenance mismatch"):
        validate_formal_extended_readiness(root, contract=contract)


def test_transition_preserves_base_and_creates_three_legal_manifests(
    tmp_path: Path,
) -> None:
    """正式视图为原5+新增6，两个补算 run 各自获得六条合法 F-only 记录。"""
    root, contract = _prepare_root(tmp_path)
    base_path = root / "reports" / "runs" / "formal" / "exclusions.jsonl"
    formal_path = root / "reports" / "runs" / "formal" / "exclusions.stage_f.jsonl"
    base_before = base_path.read_bytes()
    original_five = {
        row["pdb_id"]: row for row in read_jsonl(formal_path)
    }

    summary = apply_or_validate_signal11_transition(
        root, mode="apply", contract=contract
    )
    assert base_path.read_bytes() == base_before
    formal_records = {row["pdb_id"]: row for row in read_jsonl(formal_path)}
    assert len(formal_records) == 11
    assert set(formal_records) == {*original_five, *SIGNAL11_IDS}
    for pdb_id, record in original_five.items():
        assert formal_records[pdb_id] == record
    for pdb_id in SIGNAL11_IDS:
        record = formal_records[pdb_id]
        assert record["reason"] == "chimera_full_grid_cc_signal11"
        assert record["stages"] == ["stage_f"]
        assert record["evidence"]["failure_mode"] == "external_tool_signal_11"
        assert record["evidence"]["public_quality_artifacts_created_by_decision"] is False
        assert record["evidence"]["authorized_exclusion_cap"] == 30
        assert record["downstream_policy"] == "exclude_from_training_and_inference"

    for run_id in contract.supplement_run_ids:
        manifest = root / "reports" / "runs" / run_id / "exclusions.jsonl"
        assert manifest.is_file() and not manifest.is_symlink()
        assert not (manifest.parent / "exclusions.stage_f.jsonl").exists()
        loaded, digest = load_run_exclusions(root, run_id, "stage_f")
        assert set(loaded) == set(SIGNAL11_IDS)
        assert digest == sha256_file(manifest)
        assert {row["run_id"] for row in read_jsonl(manifest)} == {run_id}
        for row in read_jsonl(manifest):
            assert "authorized_exclusion_cap" not in row["evidence"]
            assert row["evidence"]["formal_run_authorized_exclusion_cap"] == 30

    assert summary["formal_exclusion_ids"] == sorted(formal_records)
    assert summary["authorized_exclusion_cap"] == 30
    assert summary["supplement_plan_exclusion_snapshot_sha256"] == (
        contract.expected_formal_before_sha256
    )
    assert "post-plan run-scoped overlay" in summary["supplement_plan_overlay"]
    first_hashes = {
        path: sha256_file(path)
        for path in (
            formal_path,
            *(root / "reports" / "runs" / run_id / "exclusions.jsonl"
              for run_id in contract.supplement_run_ids),
        )
    }
    repeated = apply_or_validate_signal11_transition(
        root, mode="apply", contract=contract
    )
    validated = apply_or_validate_signal11_transition(
        root, mode="validate", contract=contract
    )
    assert repeated == validated == summary
    assert {path: sha256_file(path) for path in first_hashes} == first_hashes


def test_transition_keeps_all_six_public_quality_trios_at_zero_of_three(
    tmp_path: Path,
) -> None:
    """迁移只写 manifest/账本，六例 canonical 质量三件套始终保持 0/3。"""
    root, contract = _prepare_root(tmp_path)
    apply_or_validate_signal11_transition(root, mode="apply", contract=contract)
    for pdb_id in SIGNAL11_IDS:
        paths = (
            root / "quality" / f"{pdb_id}.jsonl",
            root / "quality" / f"{pdb_id}.provenance.json",
            root / "quality_atoms" / f"{pdb_id}.npz",
        )
        assert [path.exists() or path.is_symlink() for path in paths] == [False] * 3


def test_transition_rejects_non_signal11_status_before_any_manifest_write(
    tmp_path: Path,
) -> None:
    """旧 unknown 不是 ExternalToolError/-11 时不得降级为 run-only known。"""
    root, contract = _prepare_root(tmp_path)
    status_path = root / contract.status_before_relative_path
    rows = read_jsonl(status_path)
    rows[0]["error"] = "external tool timed out"
    write_jsonl(status_path, rows)
    drift_contract = Signal11TransitionContract(
        **{
            **contract.__dict__,
            "expected_status_before_sha256": sha256_file(status_path),
        }
    )
    formal_path = root / "reports" / "runs" / "formal" / "exclusions.stage_f.jsonl"
    formal_before = formal_path.read_bytes()
    with pytest.raises(RuntimeError, match="signal-11 evidence drift"):
        apply_or_validate_signal11_transition(root, mode="apply", contract=drift_contract)
    assert formal_path.read_bytes() == formal_before
    assert not (root / "reports" / "runs" / "supp1" / "exclusions.jsonl").exists()


def test_transition_rejects_existing_quality_artifact_without_side_effects(
    tmp_path: Path,
) -> None:
    """任一六例已有公开产物时停止迁移，不覆盖成功或部分产物。"""
    root, contract = _prepare_root(tmp_path)
    artifact = root / "quality" / "9fkb.jsonl"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("real artifact\n", encoding="utf-8")
    formal_path = root / "reports" / "runs" / "formal" / "exclusions.stage_f.jsonl"
    formal_before = formal_path.read_bytes()
    with pytest.raises(RuntimeError, match="existing public quality artifact"):
        apply_or_validate_signal11_transition(root, mode="apply", contract=contract)
    assert artifact.read_text(encoding="utf-8") == "real artifact\n"
    assert formal_path.read_bytes() == formal_before


@pytest.mark.parametrize("supp2_conflict", ["symlink", "drift", "overlay"])
def test_transition_preflights_all_targets_before_first_live_replace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    supp2_conflict: str,
) -> None:
    """supp2 任一可预见冲突都必须在 formal/supp1 首次写入前阻断。"""
    root, contract = _prepare_root(tmp_path)
    formal_path = root / "reports" / "runs" / "formal" / "exclusions.stage_f.jsonl"
    supp1_path = root / "reports" / "runs" / "supp1" / "exclusions.jsonl"
    supp2_dir = root / "reports" / "runs" / "supp2"
    supp2_path = supp2_dir / "exclusions.jsonl"
    formal_before = formal_path.read_bytes()
    if supp2_conflict == "symlink":
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda path: path == supp2_path or original_is_symlink(path),
        )
        expected_error = "must not be a symlink"
    elif supp2_conflict == "drift":
        supp2_path.write_text('{"drift":true}\n', encoding="utf-8")
        expected_error = "live manifest drift"
    else:
        (supp2_dir / "exclusions.stage_f.jsonl").write_text(
            '{"overlay":true}\n',
            encoding="utf-8",
        )
        expected_error = "must not introduce a Stage F overlay"

    with pytest.raises(RuntimeError, match=expected_error):
        apply_or_validate_signal11_transition(root, mode="apply", contract=contract)
    assert formal_path.read_bytes() == formal_before
    assert not (supp1_path.exists() or supp1_path.is_symlink())
    evidence_dir = (
        root
        / "reports"
        / "runs"
        / "formal"
        / "stage_f_signal11_exclusion_20260717_v1"
    )
    assert not evidence_dir.exists()


def test_supplement_gate_accepts_only_real_manifest_bound_known_statuses(
    tmp_path: Path,
) -> None:
    """补算必须真实重跑为 manifest-bound known，不能通过 gate 豁免 unknown。"""
    root, contract = _prepare_root(tmp_path)
    apply_or_validate_signal11_transition(root, mode="apply", contract=contract)
    write_jsonl(
        root / "raw" / "pair_list.jsonl",
        [{"pdb_id": pdb_id} for pdb_id in SIGNAL11_IDS],
    )
    ids_file = root / "ids.txt"
    ids_file.write_text("".join(f"{pdb_id}\n" for pdb_id in SIGNAL11_IDS), encoding="utf-8")
    exclusions, digest = load_run_exclusions(root, "supp1", "stage_f")
    assert digest is not None
    statuses = [
        stage_result(
            pdb_id,
            "stage_f",
            "known_failed",
            **exclusion_status_fields(exclusions[pdb_id], manifest_sha256=digest),
        )
        for pdb_id in SIGNAL11_IDS
    ]
    for status in statuses:
        assert status["reason"] == "run_policy_excluded"
        assert status["exclusion_reason"] == "chimera_full_grid_cc_signal11"
    write_stage_results(stage_report_path(root, "supp1", "stage_f", 0, 1), statuses)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_ROOT / "stage_release_gate.py"),
            "--root",
            str(root),
            "--run_id",
            "supp1",
            "--stages",
            "stage_f",
            "--gate_name",
            "f_supplement_release",
            "--pdb_ids_file",
            str(ids_file),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    gate = json.loads(
        (root / "reports" / "runs" / "supp1" / "f_supplement_release" / "summary.json")
        .read_text(encoding="utf-8")
    )
    assert gate["known_failure_reasons"] == {"stage_f:run_policy_excluded": 6}


def test_formal_readiness_accepts_v1_release_and_trusted_active_v2(
    tmp_path: Path,
) -> None:
    """正式 F 可在 v1 完整 release 且 v2 由受信 job/PGID/run_cmd 运行时启动。"""
    root, contract = _prepare_root(tmp_path)
    apply_or_validate_signal11_transition(root, mode="apply", contract=contract)
    _write_supplement_release(root, contract, 0)
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    run_cmd = lock_root / "run_cmd_318350.sh"
    run_cmd.write_text("#!/usr/bin/env bash\necho trusted\n", encoding="utf-8")
    (lock_root / "child_pgid_318350").write_text("4567\n", encoding="utf-8")

    summary = validate_formal_signal11_readiness(
        root,
        expected_supplement_run_cmd_sha256=sha256_file(run_cmd),
        contract=contract,
        lock_root=lock_root,
        scheduler_state_query=lambda job_id: "RUNNING" if job_id == 318350 else "",
    )
    assert summary["supplement_v1"]["n_expected_pdb"] == len(SIGNAL11_IDS)
    assert summary["supplement_v2"]["readiness_mode"] == "trusted_active_process"
    assert summary["supplement_v2"]["child_pgid"] == 4567


def test_formal_readiness_accepts_two_releases_and_rejects_status_drift(
    tmp_path: Path,
) -> None:
    """两轮 release 均闭合时无需活动进程；任一六条 provenance 漂移仍 fail-closed。"""
    root, contract = _prepare_root(tmp_path)
    apply_or_validate_signal11_transition(root, mode="apply", contract=contract)
    _write_supplement_release(root, contract, 0)
    _write_supplement_release(root, contract, 1)
    summary = validate_formal_signal11_readiness(
        root,
        expected_supplement_run_cmd_sha256="a" * 64,
        contract=contract,
        lock_root=tmp_path / "unused-locks",
    )
    assert summary["supplement_v2"]["readiness_mode"] == "release_complete"

    status_path = stage_report_path(root, "supp1", "stage_f", 0, 1)
    rows = read_jsonl(status_path)
    rows[0]["exclusion_reason"] = "timeout"
    write_stage_results(status_path, rows)
    with pytest.raises(RuntimeError, match="provenance mismatch"):
        validate_formal_signal11_readiness(
            root,
            expected_supplement_run_cmd_sha256="a" * 64,
            contract=contract,
            lock_root=tmp_path / "unused-locks",
        )


def test_apply_preconditions_bind_fresh_zero_process_audit_and_exact_locks(
    tmp_path: Path,
) -> None:
    """apply 只接受 fresh 零进程快照及两组 after+try，且禁止 kill/pre/child。"""
    captured_at = datetime.now(timezone.utc)
    audit_path = tmp_path / "process_audit.json"
    audit_path.write_text(
        json.dumps(_process_audit_payload(captured_at)),
        encoding="utf-8",
    )
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    for job_id in (316116, 318350):
        for kind in ("after", "try"):
            (lock_root / f"{kind}_lock_{job_id}").write_text("held\n", encoding="utf-8")
    summary = validate_signal11_apply_preconditions(
        audit_path,
        expected_process_audit_sha256=sha256_file(audit_path),
        lock_root=lock_root,
        now=captured_at + timedelta(seconds=60),
    )
    assert summary["status"] == "success"
    assert summary["lock_snapshot"]["316116"] == {
        "after": "regular",
        "try": "regular",
        "kill": "absent",
        "pre": "absent",
        "child_pgid": "absent",
    }

    (lock_root / "kill_lock_318350").write_text("stop\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="forbidden kill lock"):
        validate_signal11_apply_preconditions(
            audit_path,
            expected_process_audit_sha256=sha256_file(audit_path),
            lock_root=lock_root,
            now=captured_at + timedelta(seconds=60),
        )


def test_apply_preconditions_reject_stale_or_active_process_audit(
    tmp_path: Path,
) -> None:
    """即使 SHA 正确，过期或含活动 F 进程的审计也不能授权 manifest apply。"""
    captured_at = datetime.now(timezone.utc)
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    for job_id in (316116, 318350):
        for kind in ("after", "try"):
            (lock_root / f"{kind}_lock_{job_id}").write_text("held\n", encoding="utf-8")
    stale_path = tmp_path / "stale.json"
    stale_path.write_text(json.dumps(_process_audit_payload(captured_at)), encoding="utf-8")
    with pytest.raises(RuntimeError, match="freshness window"):
        validate_signal11_apply_preconditions(
            stale_path,
            expected_process_audit_sha256=sha256_file(stale_path),
            lock_root=lock_root,
            now=captured_at + timedelta(seconds=901),
        )

    active = _process_audit_payload(captured_at)
    active["active_stage_f_processes"] = 1
    active_path = tmp_path / "active.json"
    active_path.write_text(json.dumps(active), encoding="utf-8")
    with pytest.raises(RuntimeError, match="not quiescent"):
        validate_signal11_apply_preconditions(
            active_path,
            expected_process_audit_sha256=sha256_file(active_path),
            lock_root=lock_root,
            now=captured_at + timedelta(seconds=60),
        )


def test_apply_preconditions_allow_authorized_controller_opaque_but_reject_blocking(
    tmp_path: Path,
) -> None:
    """schema v3 只按顶层 blocking opaque 判定，不误伤精确授权的 controller 扫描。"""
    captured_at = datetime.now(timezone.utc)
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    for job_id in (316116, 318350):
        for kind in ("after", "try"):
            (lock_root / f"{kind}_lock_{job_id}").write_text("held\n", encoding="utf-8")
    authorized = _process_audit_payload(captured_at)
    authorized["observed_opaque_stdin_python_processes"] = 1
    authorized["controller_check"]["active_opaque_stdin_python_processes"] = 1
    authorized["authorized_controller_opaque_specs"] = [{"pid": 54412}]
    authorized["authorized_controller_opaque_processes"] = [{"pid": 54412}]
    authorized_path = tmp_path / "authorized.json"
    authorized_path.write_text(json.dumps(authorized), encoding="utf-8")
    summary = validate_signal11_apply_preconditions(
        authorized_path,
        expected_process_audit_sha256=sha256_file(authorized_path),
        lock_root=lock_root,
        now=captured_at + timedelta(seconds=60),
    )
    assert summary["status"] == "success"

    blocking = dict(authorized)
    blocking["blocking_controller_opaque_processes"] = [{"pid": 60001}]
    blocking_path = tmp_path / "blocking.json"
    blocking_path.write_text(json.dumps(blocking), encoding="utf-8")
    with pytest.raises(RuntimeError, match="blocking controller opaque"):
        validate_signal11_apply_preconditions(
            blocking_path,
            expected_process_audit_sha256=sha256_file(blocking_path),
            lock_root=lock_root,
            now=captured_at + timedelta(seconds=60),
        )


def test_apply_replays_with_same_or_fresh_process_audit_without_manifest_drift(
    tmp_path: Path,
) -> None:
    """首次 live commit 后，同 audit 与 fresh audit 都能幂等重放且不改变三份 manifest。"""
    root, contract = _prepare_root(tmp_path)
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    for job_id in (316116, 318350):
        for kind in ("after", "try"):
            (lock_root / f"{kind}_lock_{job_id}").write_text("held\n", encoding="utf-8")
    captured_at = datetime.now(timezone.utc)
    audit1_path = tmp_path / "audit1.json"
    audit1_path.write_text(
        json.dumps(_process_audit_payload(captured_at)),
        encoding="utf-8",
    )
    audit1_sha = sha256_file(audit1_path)
    first = apply_signal11_transition_with_preconditions(
        root,
        process_audit_path=audit1_path,
        expected_process_audit_sha256=audit1_sha,
        lock_root=lock_root,
        contract=contract,
        now=captured_at + timedelta(seconds=30),
    )
    manifest_paths = [
        root / "reports" / "runs" / "formal" / "exclusions.stage_f.jsonl",
        root / "reports" / "runs" / "supp1" / "exclusions.jsonl",
        root / "reports" / "runs" / "supp2" / "exclusions.jsonl",
    ]
    manifest_bytes = {path: path.read_bytes() for path in manifest_paths}
    evidence_path = Path(first["apply_preconditions_path"])
    evidence_bytes = evidence_path.read_bytes()

    replay = apply_signal11_transition_with_preconditions(
        root,
        process_audit_path=audit1_path,
        expected_process_audit_sha256=audit1_sha,
        lock_root=lock_root,
        contract=contract,
        now=captured_at + timedelta(seconds=120),
    )
    assert replay["apply_preconditions_path"] == str(evidence_path)
    assert evidence_path.read_bytes() == evidence_bytes
    assert {path: path.read_bytes() for path in manifest_paths} == manifest_bytes

    fresh_captured_at = captured_at + timedelta(seconds=180)
    audit2_path = tmp_path / "audit2.json"
    audit2_path.write_text(
        json.dumps(_process_audit_payload(fresh_captured_at)),
        encoding="utf-8",
    )
    audit2_sha = sha256_file(audit2_path)
    fresh = apply_signal11_transition_with_preconditions(
        root,
        process_audit_path=audit2_path,
        expected_process_audit_sha256=audit2_sha,
        lock_root=lock_root,
        contract=contract,
        now=fresh_captured_at + timedelta(seconds=30),
    )
    assert fresh["apply_preconditions_path"] != str(evidence_path)
    assert Path(fresh["apply_preconditions_path"]).is_file()
    assert {path: path.read_bytes() for path in manifest_paths} == manifest_bytes


def test_apply_rejects_short_audit_prefix_collision_before_live_commit(
    tmp_path: Path,
) -> None:
    """短摘要前缀碰撞必须保留旧证据，并在三份 live manifest 变化前失败。"""
    root, contract = _prepare_root(tmp_path)
    lock_root = tmp_path / "locks"
    lock_root.mkdir()
    for job_id in (316116, 318350):
        for kind in ("after", "try"):
            (lock_root / f"{kind}_lock_{job_id}").write_text("held\n", encoding="utf-8")
    captured_at = datetime.now(timezone.utc)
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(
        json.dumps(_process_audit_payload(captured_at)),
        encoding="utf-8",
    )
    audit_sha = sha256_file(audit_path)
    evidence_path = (
        root
        / "reports"
        / "runs"
        / contract.formal_run_id
        / "stage_f_signal11_exclusion_20260717_v1"
        / f"apply.{audit_sha[:16]}.json"
    )
    colliding_sha = (
        audit_sha[:16]
        + ("0" if audit_sha[16] != "0" else "1")
        + audit_sha[17:]
    )
    collision_payload = {
        "schema_version": 1,
        "status": "success",
        "event": "stage_f_signal11_apply_preconditions",
        "process_audit_sha256": colliding_sha,
        "process_audit_captured_at": captured_at.isoformat(),
        "lock_snapshot": {},
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(collision_payload), encoding="utf-8")
    evidence_before = evidence_path.read_bytes()
    manifest_paths = [
        root / "reports" / "runs" / "formal" / "exclusions.stage_f.jsonl",
        root / "reports" / "runs" / "supp1" / "exclusions.jsonl",
        root / "reports" / "runs" / "supp2" / "exclusions.jsonl",
    ]
    manifest_before = {
        path: path.read_bytes() if path.exists() else None
        for path in manifest_paths
    }

    with pytest.raises(
        RuntimeError,
        match="process-audit-bound apply preconditions drift",
    ):
        apply_signal11_transition_with_preconditions(
            root,
            process_audit_path=audit_path,
            expected_process_audit_sha256=audit_sha,
            lock_root=lock_root,
            contract=contract,
            now=captured_at + timedelta(seconds=30),
        )

    assert evidence_path.read_bytes() == evidence_before
    assert {
        path: path.read_bytes() if path.exists() else None
        for path in manifest_paths
    } == manifest_before


def test_formal_release_and_g_analyze_naturally_exclude_signal11_without_quality(
    tmp_path: Path,
) -> None:
    """正式 F release 接受11条真实 known；G analyze 不读取六例缺失的质量三件套。"""
    root, contract = _prepare_root(tmp_path)
    apply_or_validate_signal11_transition(root, mode="apply", contract=contract)
    formal_exclusions_f, formal_f_sha = load_run_exclusions(root, "formal", "stage_f")
    formal_exclusions_e, formal_e_sha = load_run_exclusions(root, "formal", "stage_e")
    assert formal_f_sha is not None and formal_e_sha is not None
    eligible_id = "1aaa"
    universe = sorted({*formal_exclusions_f, eligible_id})
    write_jsonl(
        root / "raw" / "pair_list.jsonl",
        [{"pdb_id": pdb_id, "emdb_id": f"EMD-{pdb_id}"} for pdb_id in universe],
    )
    write_stage_results(
        stage_report_path(root, "formal", "stage_d", 0, 1),
        [stage_result(pdb_id, "stage_d", "success") for pdb_id in universe],
    )
    stage_e_rows = []
    stage_f_rows = []
    for pdb_id in universe:
        if pdb_id in formal_exclusions_e:
            stage_e_rows.append(
                stage_result(
                    pdb_id,
                    "stage_e",
                    "known_failed",
                    **exclusion_status_fields(
                        formal_exclusions_e[pdb_id],
                        manifest_sha256=formal_e_sha,
                    ),
                )
            )
        else:
            stage_e_rows.append(stage_result(pdb_id, "stage_e", "success"))
        if pdb_id in formal_exclusions_f:
            stage_f_rows.append(
                stage_result(
                    pdb_id,
                    "stage_f",
                    "known_failed",
                    **exclusion_status_fields(
                        formal_exclusions_f[pdb_id],
                        manifest_sha256=formal_f_sha,
                    ),
                )
            )
        else:
            stage_f_rows.append(stage_result(pdb_id, "stage_f", "success"))
    write_stage_results(
        stage_report_path(root, "formal", "stage_e", 0, 1),
        stage_e_rows,
    )
    write_stage_results(
        stage_report_path(root, "formal", "stage_f", 0, 1),
        stage_f_rows,
    )
    write_jsonl(
        root / "parse" / eligible_id / "occurrences.jsonl",
        [{"candidate_id": 7, "type_tag": "small_molecule"}],
    )
    write_jsonl(
        root / "quality" / f"{eligible_id}.jsonl",
        [
            {
                "pdb_id": eligible_id,
                "candidate_id": 7,
                "q_score": 0.8,
                "q_score_median": 0.81,
                "q_score_min": 0.7,
                "n_valid": 9,
                "n_present": 9,
                "pocket_q_score": 0.75,
                "pocket_q_score_median": 0.76,
                "pocket_q_score_min": 0.65,
                "pocket_n_valid": 12,
                "pocket_n_atoms": 12,
                "pocket_status": "ok",
                "pocket_radius_angstrom": 6.0,
                "map_resolution": 2.8,
                "contour_status": "missing_primary_contour",
                "cc_contour": None,
                "cc_contour_about_mean": None,
                "cc_all": 0.5,
                "cc_all_about_mean": 0.4,
            }
        ],
    )
    (root / "quality" / f"{eligible_id}.provenance.json").write_text(
        "{}\n",
        encoding="utf-8",
    )

    gate_result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_ROOT / "stage_release_gate.py"),
            "--root",
            str(root),
            "--run_id",
            "formal",
            "--stages",
            "stage_f",
            "--gate_name",
            "f_release",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert gate_result.returncode == 0, gate_result.stderr
    f_release = json.loads(
        (root / "reports" / "runs" / "formal" / "f_release" / "summary.json")
        .read_text(encoding="utf-8")
    )
    assert f_release["status_counts"] == {
        "stage_f": {"known_failed": 11, "success": 1}
    }
    assert f_release["known_failure_reasons"] == {
        "stage_f:run_policy_excluded": 11
    }

    result = run_stage_g(root, "formal", mode="analyze")
    assert result["status"] == "analysis_complete_filter_pending"
    pending = read_jsonl(
        root
        / "reports"
        / "runs"
        / "formal"
        / "stage_g_analysis"
        / "candidates.pending.jsonl"
    )
    assert [(row["pdb_id"], row["candidate_id"]) for row in pending] == [
        (eligible_id, 7)
    ]
    distribution = json.loads(
        (
            root
            / "reports"
            / "runs"
            / "formal"
            / "stage_g_analysis"
            / "quality_distribution.json"
        ).read_text(encoding="utf-8")
    )
    assert distribution["n_known_failed_pdb"] == 11
    assert distribution["known_failure_reasons"] == {
        "stage_e:run_policy_excluded": 4,
        "stage_f:run_policy_excluded": 11,
    }
    for pdb_id in SIGNAL11_IDS:
        assert not (root / "quality" / f"{pdb_id}.jsonl").exists()
        assert not (root / "quality" / f"{pdb_id}.provenance.json").exists()
        assert not (root / "quality_atoms" / f"{pdb_id}.npz").exists()


def test_signal11_resume_scripts_validate_then_run_real_stage_f() -> None:
    """补算先验证迁移；正式入口再验证 supplement readiness 后保持 F12+gate。"""
    supplement = (SBATCH_ROOT / "resume_f_supplement_318350_signal11_v1.sh").read_text(
        encoding="utf-8"
    )
    formal = (SBATCH_ROOT / "resume_f_316116_signal11_v1.sh").read_text(
        encoding="utf-8"
    )
    transition_sha = sha256_file(
        SCRIPTS_ROOT / "f_signal11_exclusion_transition.py"
    )
    assert 'expected_job_id="318350"' in supplement
    assert "--mode validate-extended" in supplement
    assert "resume_f_supplement_318350_accel_v2.sh" not in supplement
    assert "_f_supplement_stage.sh" not in supplement
    assert "run_adaligand_f_supplement_stage" not in supplement
    assert "scripts/f_supplement_guard.py" in supplement
    assert "--formal_hold_node" in supplement
    assert 'expected_formal_node="cnode04"' in supplement
    assert "check-formal-hold" in supplement
    assert "--poll_seconds 10" in supplement
    assert "--formal_hold_probe_timeout_seconds 30" in supplement
    assert "stop.formal_hold.${guard_attempt_id}.json" in supplement
    assert "stop.formal_hold.pre_gate.${guard_attempt_id}.json" in supplement
    assert 'if [[ "${v2_exit}" -eq 76 ]]' in supplement
    assert "exit 76" in supplement
    assert "v2 collision guard stopped cleanly" not in supplement
    assert '"${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}"' in supplement
    assert '"${ADALIGAND_RUN_ID}" \\' not in supplement
    assert '"${F_N_JOBS:-12}" != "12"' in supplement
    assert '"${SLURM_CPUS_PER_TASK:-}" != "96"' in supplement
    assert DEFAULT_CONTRACT.expected_supplement_ids_sha256[1] in supplement
    assert "116084c321c60d8802780457d2cbad86dbb058e2001f7b7f5c3e820111f464fc" in supplement
    assert 'expected_formal_run_id="adaligand_ag_20260711T154658"' in supplement
    assert 'expected_formal_job_id="316116"' in supplement
    assert 'expected_formal_log="/storage/penghongen/AdaLigand/Ori_Data/logs/f/adaligand_f_316116.err"' in supplement
    assert "stage_f_tail_supplement_20260716_v2/pdb_ids.txt" in supplement
    assert "stage_f_tail_supplement_20260716_v2/plan.json" in supplement
    assert supplement.count("stage_release_gate.py") == 1
    assert "--gate_name f_supplement_release" in supplement
    pinned_guard_files = {
        "expected_supplement_guard_script_sha256": SCRIPTS_ROOT / "f_supplement_guard.py",
        "expected_supplement_guard_module_sha256": CODE_ROOT / "f_supplement_guard.py",
        "expected_process_probe_script_sha256": SCRIPTS_ROOT / "stage_f_process_audit.py",
        "expected_process_probe_module_sha256": CODE_ROOT / "stage_f_process_audit.py",
    }
    for variable, path in pinned_guard_files.items():
        match = re.search(
            rf'readonly {variable}="([0-9a-f]{{64}})"',
            supplement,
        )
        assert match is not None
        assert match.group(1) == sha256_file(path)
    assert 'formal_job_id="316116"' in formal
    assert '"${F_N_JOBS:-12}" != "12"' in formal
    assert '"${SLURM_CPUS_PER_TASK:-}" != "96"' in formal
    assert "ADALIGAND_SIGNAL11_SUPPLEMENT_RUN_CMD_SHA256" not in formal
    assert "--mode readiness-extended" in formal
    assert "--expected_supplement_run_cmd_sha256" not in formal
    assert formal.count('scripts/f_quality.py') == 1
    assert "--n_jobs \"${F_N_JOBS:-12}\"" in formal
    assert "--overwrite" not in formal
    assert "--stages stage_f" in formal
    assert "--gate_name f_release" in formal
    for script in (supplement, formal):
        assert "try_lock_" in script and "kill_lock_" in script
        assert "f_signal11_exclusion_transition.py" in script
        assert "expected_transition_sha256" in script
        assert "signal-11 transition SHA-256 drift" in script
        match = re.search(
            r'readonly expected_transition_sha256="([0-9a-f]{64})"',
            script,
        )
        assert match is not None
        assert match.group(1) == transition_sha
