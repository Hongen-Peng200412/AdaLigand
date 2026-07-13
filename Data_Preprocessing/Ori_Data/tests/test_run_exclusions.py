"""run-scoped E/F 排除清单的 schema、身份和状态传播测试。"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


CODE_ROOT = Path(__file__).resolve().parents[1] / "code"
sys.path.insert(0, str(CODE_ROOT))

from exclusions import exclusion_status_fields, load_run_exclusions
from failures import KnownFailureCode
from io_utils import sha256_file


def _record() -> dict:
    """返回覆盖 Stage E/F 的最小合法 run-only 排除决策。"""
    return {
        "schema_version": 1,
        "pdb_id": "8ckb",
        "run_id": "formal",
        "stages": ["stage_e", "stage_f"],
        "reason": "user_authorized_resource_outlier",
        "detail": "standard Chimera molmap timed out without sim.mrc",
        "authorization": "user_explicit_2026-07-13",
        "decision_scope": "current_run_only",
        "downstream_policy": "exclude_from_training_and_inference",
        "evidence": {
            "standard_chimera_timeout_seconds": 21600.0,
            "sim_mrc_created": False,
        },
    }


def _write_manifest(root: Path, run_id: str, records: list[dict]) -> Path:
    """写测试专用 JSONL；生产代码仍只读该 manifest。"""
    path = root / "reports" / "runs" / run_id / "exclusions.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return path


def test_missing_manifest_means_no_run_exclusions(tmp_path: Path) -> None:
    """清单不存在时不产生任何隐式排除。"""
    exclusions, digest = load_run_exclusions(tmp_path, "formal", "stage_e")
    assert exclusions == {}
    assert digest is None


def test_valid_manifest_propagates_identity_and_policy(tmp_path: Path) -> None:
    """同一 run 决策在 E/F 都保留完整授权、证据和文件身份。"""
    manifest = _write_manifest(tmp_path, "formal", [_record()])
    for stage in ("stage_e", "stage_f"):
        exclusions, digest = load_run_exclusions(tmp_path, "formal", stage)
        assert set(exclusions) == {"8ckb"}
        assert digest == sha256_file(manifest)
        fields = exclusion_status_fields(exclusions["8ckb"], manifest_sha256=digest)
        assert fields["reason"] == KnownFailureCode.RUN_POLICY_EXCLUDED.value
        assert fields["exclusion_reason"] == "user_authorized_resource_outlier"
        assert fields["exclusion_run_id"] == "formal"
        assert fields["exclusion_downstream_policy"] == "exclude_from_training_and_inference"
        assert fields["exclusion_evidence"]["sim_mrc_created"] is False
        assert fields["exclusion_manifest_sha256"] == digest


@pytest.mark.parametrize(
    "mutator",
    [
        lambda record: record.update(decision_scope="all_future_runs"),
        lambda record: record.update(downstream_policy="keep"),
        lambda record: record.update(evidence={}),
        lambda record: record.update(stages=["stage_g"]),
        lambda record: record.update(run_id="another_run"),
        lambda record: record.update(unexpected=True),
    ],
)
def test_invalid_policy_fields_fail_fast(tmp_path: Path, mutator) -> None:
    """授权范围、下游策略、证据或 stage 漂移均不能被默认值兜底。"""
    record = _record()
    mutator(record)
    _write_manifest(tmp_path, "formal", [record])
    with pytest.raises(ValueError):
        load_run_exclusions(tmp_path, "formal", "stage_e")


def test_duplicate_pdb_id_is_rejected(tmp_path: Path) -> None:
    """同一 PDB 只能有一条 run-scoped 决策，避免授权互相覆盖。"""
    _write_manifest(tmp_path, "formal", [_record(), _record()])
    with pytest.raises(ValueError, match="duplicate"):
        load_run_exclusions(tmp_path, "formal", "stage_e")
