"""Stage E 长尾截止的证据链、manifest 追加与幂等测试。"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


CODE_ROOT = Path(__file__).resolve().parents[1] / "code"
sys.path.insert(0, str(CODE_ROOT))

from io_utils import sha256_file
from long_tail_cutoff import apply_stage_e_long_tail_cutoff


def test_cutoff_appends_only_unfinished_ids_and_is_idempotent(tmp_path: Path) -> None:
    """已完成子集保留给正式 E 复核，未完成子集才追加为 run-only 排除。"""
    run_id = "formal"
    evidence_dir, pre_sha, post_sha = _write_evidence(tmp_path, run_id)
    manifest = _write_initial_manifest(tmp_path, run_id)
    before_sha = sha256_file(manifest)

    first = apply_stage_e_long_tail_cutoff(
        tmp_path,
        run_id,
        evidence_dir=evidence_dir,
        expected_predecision_sha256=pre_sha,
        expected_posttermination_sha256=post_sha,
        expected_before_manifest_sha256=before_sha,
        expected_existing_ids={"8ckb"},
        expected_supplement_job_id=316415,
        expected_authorization="user_explicit_2026-07-13_four_hour_long_tail_cutoff",
    )
    # 模拟 live manifest 已替换、但 summary 尚未落盘时进程中断。
    (evidence_dir / "summary.json").unlink()
    second = apply_stage_e_long_tail_cutoff(
        tmp_path,
        run_id,
        evidence_dir=evidence_dir,
        expected_predecision_sha256=pre_sha,
        expected_posttermination_sha256=post_sha,
        expected_before_manifest_sha256=before_sha,
        expected_existing_ids={"8ckb"},
        expected_supplement_job_id=316415,
        expected_authorization="user_explicit_2026-07-13_four_hour_long_tail_cutoff",
    )
    third = apply_stage_e_long_tail_cutoff(
        tmp_path,
        run_id,
        evidence_dir=evidence_dir,
        expected_predecision_sha256=pre_sha,
        expected_posttermination_sha256=post_sha,
        expected_before_manifest_sha256=before_sha,
        expected_existing_ids={"8ckb"},
        expected_supplement_job_id=316415,
        expected_authorization="user_explicit_2026-07-13_four_hour_long_tail_cutoff",
    )

    assert first == second == third
    assert first["candidate_completed_ids"] == ["8j07", "9dp7", "9qwt"]
    assert first["added_exclusion_ids"] == ["8glv", "9e5c", "9fqr"]
    records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    assert [record["pdb_id"] for record in records] == ["8ckb", "8glv", "9e5c", "9fqr"]
    for record in records[1:]:
        assert record["reason"] == "user_authorized_stage_e_long_tail_cutoff"
        assert record["decision_scope"] == "current_run_only"
        assert record["downstream_policy"] == "exclude_from_training_and_inference"
        assert record["evidence"]["complete_artifact_trio"] is False
    assert sha256_file(evidence_dir / "exclusions.before.jsonl") == before_sha
    assert sha256_file(evidence_dir / "exclusions.after.jsonl") == first["after_manifest_sha256"]


@pytest.mark.parametrize(
    "mutation, message",
    [
        (lambda pre, post: pre.update(observed_at="2026-07-13T19:00:00+08:00"), "predates"),
        (lambda pre, post: pre.update(candidate_completed_ids=["8j07", "8glv"]), "partition"),
        (lambda pre, post: post.update(process_audit="three_remaining"), "zero remaining"),
        (lambda pre, post: post.update(authorization="another_authorization"), "authorization"),
    ],
)
def test_cutoff_rejects_evidence_drift(tmp_path: Path, mutation, message: str) -> None:
    """截止前执行、分区漂移、残留进程或授权漂移都必须 fail-fast。"""
    run_id = "formal"
    evidence_dir, _, _ = _write_evidence(tmp_path, run_id, mutation=mutation)
    pre_path = evidence_dir / "predecision.json"
    post_path = evidence_dir / "posttermination.json"
    manifest = _write_initial_manifest(tmp_path, run_id)
    with pytest.raises(RuntimeError, match=message):
        apply_stage_e_long_tail_cutoff(
            tmp_path,
            run_id,
            evidence_dir=evidence_dir,
            expected_predecision_sha256=sha256_file(pre_path),
            expected_posttermination_sha256=sha256_file(post_path),
            expected_before_manifest_sha256=sha256_file(manifest),
            expected_existing_ids={"8ckb"},
            expected_supplement_job_id=316415,
            expected_authorization="user_explicit_2026-07-13_four_hour_long_tail_cutoff",
        )


def _write_initial_manifest(root: Path, run_id: str) -> Path:
    """写入截止前仅含 8ckb 的合法 manifest。"""
    path = root / "reports" / "runs" / run_id / "exclusions.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "pdb_id": "8ckb",
        "run_id": run_id,
        "stages": ["stage_e", "stage_f"],
        "reason": "user_authorized_resource_outlier",
        "detail": "8ckb exceeded the accepted resource envelope",
        "authorization": "user_explicit_2026-07-13",
        "decision_scope": "current_run_only",
        "downstream_policy": "exclude_from_training_and_inference",
        "evidence": {"complete_artifact_trio": False},
    }
    path.write_text(
        json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def _write_evidence(root: Path, run_id: str, mutation=None) -> tuple[Path, str, str]:
    """构造三完成、三截止排除的最小前后证据。"""
    evidence_dir = root / "reports" / "runs" / run_id / "stage_e_long_tail_cutoff_20260713T195419"
    evidence_dir.mkdir(parents=True)
    frozen_ids = ["8glv", "8j07", "9dp7", "9e5c", "9fqr", "9qwt"]
    completed = ["8j07", "9dp7", "9qwt"]
    excluded = ["8glv", "9e5c", "9fqr"]
    artifact_state = {}
    for pdb_id in frozen_ids:
        complete = pdb_id in completed
        artifact_state[pdb_id] = {
            "public": {
                "exp.npz": {"exists": True, "size_bytes": 1},
                "sim.npz": {"exists": complete, "size_bytes": 1 if complete else 0},
                "ligand_area.npz": {"exists": complete, "size_bytes": 1 if complete else 0},
            }
        }
    pre = {
        "schema_version": 1,
        "event": "stage_e_user_authorized_long_tail_cutoff_predecision",
        "observed_at": "2026-07-13T19:57:41+08:00",
        "deadline": "2026-07-13T19:54:19+08:00",
        "authorization": "user_explicit_2026-07-13_four_hour_long_tail_cutoff",
        "decision_scope": "current_run_only",
        "formal_run_id": run_id,
        "supplement_run_id": "supplement",
        "supplement_job_id": 316415,
        "configured_timeout_seconds": 21600,
        "frozen_ids": frozen_ids,
        "candidate_completed_ids": completed,
        "deadline_excluded_ids": excluded,
        "artifact_state": artifact_state,
    }
    pre_path = evidence_dir / "predecision.json"
    pre_path.write_text(json.dumps(pre), encoding="utf-8")
    post = {
        "schema_version": 1,
        "event": "stage_e_user_authorized_long_tail_cutoff_posttermination",
        "observed_at": "2026-07-13T20:08:00+08:00",
        "deadline": pre["deadline"],
        "authorization": pre["authorization"],
        "decision_scope": "current_run_only",
        "formal_run_id": run_id,
        "supplement_run_id": "supplement",
        "supplement_job_id": 316415,
        "predecision_sha256": sha256_file(pre_path),
        "candidate_completed_ids": completed,
        "deadline_excluded_ids": excluded,
        "process_audit": "zero_remaining;srun_exit=0",
        "termination": "exact kill_lock_316415 plus orphan process verification",
    }
    if mutation is not None:
        mutation(pre, post)
        pre_path.write_text(json.dumps(pre), encoding="utf-8")
        post["predecision_sha256"] = sha256_file(pre_path)
    post_path = evidence_dir / "posttermination.json"
    post_path.write_text(json.dumps(post), encoding="utf-8")
    return evidence_dir, sha256_file(pre_path), sha256_file(post_path)
