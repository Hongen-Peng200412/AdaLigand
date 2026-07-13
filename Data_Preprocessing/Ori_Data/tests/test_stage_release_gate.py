"""通用 release gate 的 full-run 与 strict-smoke 策略测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "code"))

from io_utils import read_jsonl, write_jsonl
from exclusions import exclusion_status_fields, load_run_exclusions
from reports import stage_report_path, stage_result, write_stage_results


def test_strict_smoke_gate_rejects_known_failure_but_full_gate_allows_it(tmp_path: Path) -> None:
    """真实 smoke 必须实际成功；正式全量 gate 才允许已解释的样本不适用。"""
    write_jsonl(
        tmp_path / "raw" / "pair_list.jsonl",
        [{"pdb_id": "1aaa", "emdb_id": "EMD-1"}],
    )
    write_stage_results(
        stage_report_path(tmp_path, "run1", "stage_f", 0, 1),
        [stage_result("1aaa", "stage_f", "known_failed", reason="missing_map")],
    )
    base_command = [
        sys.executable,
        str(CODE_ROOT / "scripts" / "stage_release_gate.py"),
        "--root",
        str(tmp_path),
        "--run_id",
        "run1",
        "--stages",
        "stage_f",
    ]
    full = subprocess.run(
        [*base_command, "--gate_name", "full_gate"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert full.returncode == 0, full.stderr

    smoke = subprocess.run(
        [*base_command, "--gate_name", "smoke_gate", "--require_success"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert smoke.returncode != 0
    assert "strict smoke gate rejects known failures" in smoke.stderr


def test_gate_binds_run_exclusion_manifest_to_status_provenance(tmp_path: Path) -> None:
    """gate 只放行与当前 manifest 的 run、SHA、授权和证据完全一致的排除状态。"""
    write_jsonl(
        tmp_path / "raw" / "pair_list.jsonl",
        [{"pdb_id": "8ckb", "emdb_id": "EMD-1"}],
    )
    exclusion = {
        "schema_version": 1,
        "pdb_id": "8ckb",
        "run_id": "run1",
        "stages": ["stage_e", "stage_f"],
        "reason": "user_authorized_resource_outlier",
        "detail": "standard Chimera timed out without sim.mrc",
        "authorization": "user_explicit_2026-07-13",
        "decision_scope": "current_run_only",
        "downstream_policy": "exclude_from_training_and_inference",
        "evidence": {"timeout_seconds": 21600.0, "sim_mrc_created": False},
    }
    manifest = tmp_path / "reports" / "runs" / "run1" / "exclusions.jsonl"
    write_jsonl(manifest, [exclusion])
    exclusions, digest = load_run_exclusions(tmp_path, "run1", "stage_e")
    assert digest is not None
    write_stage_results(
        stage_report_path(tmp_path, "run1", "stage_e", 0, 1),
        [
            stage_result(
                "8ckb",
                "stage_e",
                "known_failed",
                **exclusion_status_fields(exclusions["8ckb"], manifest_sha256=digest),
            )
        ],
    )
    command = [
        sys.executable,
        str(CODE_ROOT / "scripts" / "stage_release_gate.py"),
        "--root",
        str(tmp_path),
        "--run_id",
        "run1",
        "--stages",
        "stage_e",
        "--gate_name",
        "gate",
    ]
    passed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert passed.returncode == 0, passed.stderr

    status_path = stage_report_path(tmp_path, "run1", "stage_e", 0, 1)
    original_status = read_jsonl(status_path)[0]
    for field in ("error", "exclusion_decision_scope", "exclusion_downstream_policy"):
        tampered_status = dict(original_status)
        tampered_status[field] = "tampered_status_provenance"
        write_stage_results(status_path, [tampered_status])
        blocked_status = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        assert blocked_status.returncode != 0
        assert "exclusion provenance mismatch" in blocked_status.stderr
    write_stage_results(status_path, [original_status])

    exclusion["authorization"] = "tampered_after_status"
    write_jsonl(manifest, [exclusion])
    blocked = subprocess.run(command, capture_output=True, text=True, check=False)
    assert blocked.returncode != 0
    assert "exclusion provenance mismatch" in blocked.stderr


def test_gate_rejects_policy_excluded_status_without_manifest(tmp_path: Path) -> None:
    """不能只手写 known reason 而省略 run-scoped 授权清单。"""
    write_jsonl(
        tmp_path / "raw" / "pair_list.jsonl",
        [{"pdb_id": "8ckb", "emdb_id": "EMD-1"}],
    )
    write_stage_results(
        stage_report_path(tmp_path, "run1", "stage_f", 0, 1),
        [stage_result("8ckb", "stage_f", "known_failed", reason="run_policy_excluded")],
    )
    command = [
        sys.executable,
        str(CODE_ROOT / "scripts" / "stage_release_gate.py"),
        "--root",
        str(tmp_path),
        "--run_id",
        "run1",
        "--stages",
        "stage_f",
        "--gate_name",
        "gate",
    ]
    blocked = subprocess.run(command, capture_output=True, text=True, check=False)
    assert blocked.returncode != 0
    assert "run exclusion status mismatch" in blocked.stderr
