"""Stage F 远尾补算计划的身份、安全间隔和不可变证据测试。"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


CODE_ROOT = Path(__file__).resolve().parents[1] / "code"
sys.path.insert(0, str(CODE_ROOT))

from f_supplement import create_f_supplement_plan
from io_utils import sha256_file, write_jsonl
from reports import stage_result


def _prepare_root(tmp_path: Path) -> tuple[Path, str, str, Path]:
    """创建八个 PDB 的最小正式 E 状态和一个 F-only 排除项。"""
    root = tmp_path / "root"
    formal_run_id = "formal"
    records = [{"pdb_id": f"1a{index:02d}"} for index in range(8)]
    pair_list = root / "raw" / "pair_list.jsonl"
    write_jsonl(pair_list, records)
    stage_e_path = (
        root
        / "reports"
        / "runs"
        / formal_run_id
        / "stage_e"
        / "status.part_0000_of_0001.jsonl"
    )
    statuses = [stage_result(record["pdb_id"], "stage_e", "skipped") for record in records]
    statuses[-2] = stage_result(records[-2]["pdb_id"], "stage_e", "known_failed")
    write_jsonl(stage_e_path, statuses)

    base_record = {
        "schema_version": 1,
        "pdb_id": records[0]["pdb_id"],
        "run_id": formal_run_id,
        "stages": ["stage_e", "stage_f"],
        "reason": "user_authorized_resource_outlier",
        "detail": "test fixture",
        "authorization": "user_explicit_test",
        "decision_scope": "current_run_only",
        "downstream_policy": "exclude_from_training_and_inference",
        "evidence": {"fixture": True},
    }
    f_only_record = {
        **base_record,
        "pdb_id": records[-1]["pdb_id"],
        "stages": ["stage_f"],
        "reason": "user_authorized_stage_f_timeout",
    }
    run_dir = root / "reports" / "runs" / formal_run_id
    write_jsonl(run_dir / "exclusions.jsonl", [base_record])
    stage_f_manifest = run_dir / "exclusions.stage_f.jsonl"
    write_jsonl(stage_f_manifest, [base_record, f_only_record])
    formal_log = tmp_path / "adaligand_f_316116.err"
    formal_log.write_text("Done 1 tasks\n", encoding="utf-8")
    return root, sha256_file(pair_list), sha256_file(stage_f_manifest), formal_log


def _create_plan(
    root: Path,
    pair_sha: str,
    exclusion_sha: str,
    formal_log: Path,
) -> dict:
    """使用固定参数创建一个四位置尾段计划。"""
    return create_f_supplement_plan(
        root,
        formal_run_id="formal",
        supplement_run_id="formal_fsupp96_v1",
        evidence_dir=root / "reports" / "runs" / "formal" / "supplement_evidence",
        formal_log_path=formal_log,
        tail_count=4,
        formal_completed_upper_bound=1,
        minimum_initial_gap=2,
        collision_guard_tasks=1,
        expected_pair_list_sha256=pair_sha,
        expected_exclusions_sha256=exclusion_sha,
        formal_job_id=316116,
    )


def test_plan_selects_only_eligible_nonexcluded_tail_and_is_idempotent(
    tmp_path: Path,
) -> None:
    """尾段只保留 E 合格且未排除样本，并按字节幂等冻结。"""
    root, pair_sha, exclusion_sha, formal_log = _prepare_root(tmp_path)
    complete_id = "1a04"
    for path in (
        root / "quality" / f"{complete_id}.jsonl",
        root / "quality" / f"{complete_id}.provenance.json",
        root / "quality_atoms" / f"{complete_id}.npz",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    partial_path = root / "quality" / "1a05.jsonl"
    partial_path.parent.mkdir(parents=True, exist_ok=True)
    partial_path.write_bytes(b"fixture")

    summary = _create_plan(root, pair_sha, exclusion_sha, formal_log)
    ids_path = Path(summary["pdb_ids_path"])
    assert ids_path.read_text(encoding="utf-8").splitlines() == ["1a04", "1a05"]
    assert summary["tail_start_index_zero_based"] == 4
    assert summary["initial_task_gap"] == 3
    assert summary["collision_stop_completed_tasks"] == 3
    assert summary["formal_completed_observed_at_plan"] == 1
    assert summary["formal_log_path"] == str(formal_log.resolve())
    assert summary["tail_removed_stage_e_ineligible_count"] == 1
    assert summary["tail_removed_exclusion_count"] == 1
    assert summary["quality_trio_counts_at_plan"] == {
        "complete": 1,
        "partial": 1,
        "missing": 0,
    }
    assert summary["resource_contract"]["main_cpu_total"] == 192
    assert summary["resource_contract"]["reserve_cpu"] == 48

    repeated = _create_plan(root, pair_sha, exclusion_sha, formal_log)
    assert repeated == summary
    assert sha256_file(ids_path) == summary["pdb_ids_sha256"]


def test_plan_rejects_insufficient_gap_and_input_drift(tmp_path: Path) -> None:
    """正式进度过近或 pair_list 身份漂移时必须阻断补算。"""
    root, pair_sha, exclusion_sha, formal_log = _prepare_root(tmp_path)
    with pytest.raises(RuntimeError, match="too close"):
        create_f_supplement_plan(
            root,
            formal_run_id="formal",
            supplement_run_id="formal_fsupp96_v1",
            evidence_dir=root / "evidence",
            formal_log_path=formal_log,
            tail_count=4,
            formal_completed_upper_bound=3,
            minimum_initial_gap=2,
            collision_guard_tasks=1,
            expected_pair_list_sha256=pair_sha,
            expected_exclusions_sha256=exclusion_sha,
            formal_job_id=316116,
        )
    with pytest.raises(RuntimeError, match="pair_list identity drift"):
        create_f_supplement_plan(
            root,
            formal_run_id="formal",
            supplement_run_id="formal_fsupp96_v2",
            evidence_dir=root / "evidence2",
            formal_log_path=formal_log,
            tail_count=4,
            formal_completed_upper_bound=1,
            minimum_initial_gap=2,
            collision_guard_tasks=1,
            expected_pair_list_sha256="0" * 64,
            expected_exclusions_sha256=exclusion_sha,
            formal_job_id=316116,
        )


def test_plan_rejects_mutated_immutable_evidence(tmp_path: Path) -> None:
    """已有冻结 ID 被改写后不得被静默覆盖。"""
    root, pair_sha, exclusion_sha, formal_log = _prepare_root(tmp_path)
    summary = _create_plan(root, pair_sha, exclusion_sha, formal_log)
    ids_path = Path(summary["pdb_ids_path"])
    ids_path.write_text("1a04\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="immutable evidence drift"):
        _create_plan(root, pair_sha, exclusion_sha, formal_log)


def test_plan_json_is_self_contained(tmp_path: Path) -> None:
    """冻结 JSON 应可由无上下文审计者独立读取关键边界。"""
    root, pair_sha, exclusion_sha, formal_log = _prepare_root(tmp_path)
    summary = _create_plan(root, pair_sha, exclusion_sha, formal_log)
    saved = json.loads(
        (root / "reports" / "runs" / "formal" / "supplement_evidence" / "plan.json")
        .read_text(encoding="utf-8")
    )
    assert saved == summary
    assert saved["formal_job_id"] == 316116
    assert saved["writer_boundary"].startswith("supplement writes common quality trio")
