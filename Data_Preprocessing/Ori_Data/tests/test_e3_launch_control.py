"""E3 启动控制面的全局 writer、Slurm 身份、漂移与受检释放测试。"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import threading
from pathlib import Path

import pytest


CODE_ROOT = Path(__file__).resolve().parents[1] / "code"
sys.path.insert(0, str(CODE_ROOT))

import e3_launch_control
from io_utils import sha256_file


GIT_COMMIT = "1" * 40


def _prepare_fixture(
    tmp_path: Path,
    *,
    repair_run_id: str = "formal_e3_v3",
    bind_extra_evidence: bool = False,
) -> dict[str, object]:
    """建立最小冻结目标、实现文件和独占 launch control。"""
    project_root = tmp_path / "project"
    root = tmp_path / "data"
    project_root.mkdir()
    root.mkdir()
    implementation = project_root / "code" / "e3_repair.py"
    implementation.parent.mkdir()
    implementation.write_text("VALUE = 1\n", encoding="utf-8")
    freeze_dir = root / "reports" / "runs" / repair_run_id / "stage_e3_freeze"
    freeze_dir.mkdir(parents=True)
    target_ids = freeze_dir / "target_ids.txt"
    target_ids.write_text("1abc\n2def\n", encoding="utf-8")
    target_manifest = freeze_dir / "target_manifest.json"
    target_manifest.write_text(
        json.dumps(
            {
                "repair_run_id": repair_run_id,
                "target_ids_sha256": sha256_file(target_ids),
                "target_count": 2,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    audit_summary = root / "reports" / "origin_audit" / "summary.json"
    eligible_list = root / "reports" / "origin_audit" / "eligible.txt"
    extra_evidence: dict[str, object] = {}
    if bind_extra_evidence:
        audit_summary.parent.mkdir(parents=True)
        audit_summary.write_text('{"status":"record_only"}\n', encoding="utf-8")
        eligible_list.write_text("1abc\n", encoding="utf-8")
        extra_evidence = {
            "origin_risk_audit": {
                "policy": "record_only_keep_ancestral_no_exclusion",
                "files": {
                    "summary": {
                        "path": audit_summary.relative_to(root).as_posix(),
                        "sha256": sha256_file(audit_summary),
                    },
                    "eligible_list": {
                        "path": eligible_list.relative_to(root).as_posix(),
                        "sha256": sha256_file(eligible_list),
                    },
                },
            }
        }
    environment = {"ADALIGAND_E3_CONTRACT": "pocket-plus-v3"}
    frozen_target_bytes = target_manifest.read_bytes()
    e3_launch_control.prepare_launch_control(
        root,
        project_root,
        repair_run_id=repair_run_id,
        target_manifest=target_manifest,
        expected_target_manifest_sha256=sha256_file(target_manifest),
        git_commit=GIT_COMMIT,
        implementation_files=[implementation],
        required_environment=environment,
        extra_evidence=extra_evidence,
        python_executable=sys.executable,
        python_version=platform.python_version(),
    )
    assert target_manifest.read_bytes() == frozen_target_bytes
    return {
        "root": root,
        "project_root": project_root,
        "repair_run_id": repair_run_id,
        "implementation": implementation,
        "target_manifest": target_manifest,
        "target_manifest_sha256": sha256_file(target_manifest),
        "environment": environment,
        "audit_summary": audit_summary,
        "eligible_list": eligible_list,
        "extra_evidence": extra_evidence,
    }


def _authorize_worker_and_gate(fixture: dict[str, object]) -> None:
    e3_launch_control.authorize_slurm_identity(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        role="worker",
        array_job_id="42001",
        array_task_ids=[0, 1, 2, 3],
    )
    e3_launch_control.authorize_slurm_identity(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        role="gate",
        job_id="42002",
    )
    e3_launch_control.seal_slurm_authorizations(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
    )


def _runtime_env(fixture: dict[str, object], **slurm: str) -> dict[str, str]:
    return {**fixture["environment"], **slurm}


def _write_gate_summary(fixture: dict[str, object], *, status: str = "success") -> Path:
    path = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_repair_release"
        / "summary.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "status": status,
                "run_id": fixture["repair_run_id"],
                "stage": "stage_e3_repair",
                "target_manifest_sha256": fixture["target_manifest_sha256"],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_scheduler_snapshot(
    fixture: dict[str, object],
    *,
    active_output: str = "",
) -> Path:
    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            returncode=0,
            stdout=active_output,
            stderr="",
        )

    payload = e3_launch_control.capture_scheduler_snapshot(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        runner=runner,
    )
    path = fixture["root"] / "controller" / "scheduler_snapshot.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_prepare_binds_owner_and_blocks_another_repair_run(tmp_path: Path) -> None:
    fixture = _prepare_fixture(tmp_path)
    lock_owner = (
        fixture["root"]
        / "reports"
        / "runs"
        / "_locks"
        / "stage_e3_writer.lock"
        / "owner.json"
    )
    owner = json.loads(lock_owner.read_text(encoding="utf-8"))
    assert owner["repair_run_id"] == fixture["repair_run_id"]
    assert owner["target_manifest_sha256"] == fixture["target_manifest_sha256"]
    assert owner["git_commit"] == GIT_COMMIT
    assert len(owner["implementation_bundle_sha256"]) == 64

    # 完全相同的 prepare 可以幂等重放，不能改写证据。
    before = lock_owner.read_bytes()
    e3_launch_control.prepare_launch_control(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        target_manifest=fixture["target_manifest"],
        expected_target_manifest_sha256=fixture["target_manifest_sha256"],
        git_commit=GIT_COMMIT,
        implementation_files=[fixture["implementation"]],
        required_environment=fixture["environment"],
        extra_evidence=fixture["extra_evidence"],
        python_executable=sys.executable,
        python_version=platform.python_version(),
    )
    assert lock_owner.read_bytes() == before

    other_run = "other_e3_v3"
    other_freeze = fixture["root"] / "reports" / "runs" / other_run / "stage_e3_freeze"
    other_freeze.mkdir(parents=True)
    other_target = other_freeze / "target_manifest.json"
    other_target.write_text(
        json.dumps(
            {
                "repair_run_id": other_run,
                "target_ids_sha256": "a" * 64,
                "target_count": 1,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="another E3 writer"):
        e3_launch_control.prepare_launch_control(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=other_run,
            target_manifest=other_target,
            expected_target_manifest_sha256=sha256_file(other_target),
            git_commit="2" * 40,
            implementation_files=[fixture["implementation"]],
            required_environment=fixture["environment"],
            extra_evidence={},
            python_executable=sys.executable,
            python_version=platform.python_version(),
        )


def test_worker_requires_exact_array_or_single_job_identity(tmp_path: Path) -> None:
    fixture = _prepare_fixture(tmp_path)
    _authorize_worker_and_gate(fixture)
    result = e3_launch_control.verify_slurm_worker(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        role="worker",
        environ=_runtime_env(
            fixture,
            SLURM_JOB_ID="42001_2",
            SLURM_ARRAY_JOB_ID="42001",
            SLURM_ARRAY_TASK_ID="2",
        ),
        python_executable=sys.executable,
        python_version=platform.python_version(),
    )
    assert result["authorization_id"] == "worker-array-42001"

    with pytest.raises(RuntimeError, match="not authorized exactly once"):
        e3_launch_control.verify_slurm_worker(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=fixture["repair_run_id"],
            role="worker",
            environ=_runtime_env(
                fixture,
                SLURM_JOB_ID="42001_8",
                SLURM_ARRAY_JOB_ID="42001",
                SLURM_ARRAY_TASK_ID="8",
            ),
            python_executable=sys.executable,
            python_version=platform.python_version(),
        )

    gate = e3_launch_control.verify_slurm_worker(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        role="gate",
        environ=_runtime_env(fixture, SLURM_JOB_ID="42002"),
        python_executable=sys.executable,
        python_version=platform.python_version(),
    )
    assert gate["authorization_id"] == "gate-job-42002"


def test_worker_blocks_target_implementation_python_and_environment_drift(
    tmp_path: Path,
) -> None:
    fixture = _prepare_fixture(tmp_path)
    e3_launch_control.authorize_slurm_identity(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        role="worker",
        job_id="43001",
    )
    e3_launch_control.authorize_slurm_identity(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        role="gate",
        job_id="43002",
    )
    e3_launch_control.seal_slurm_authorizations(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
    )
    base = _runtime_env(fixture, SLURM_JOB_ID="43001")

    bad_env = dict(base)
    bad_env["ADALIGAND_E3_CONTRACT"] = "drifted"
    with pytest.raises(RuntimeError, match="required environment drift"):
        e3_launch_control.verify_slurm_worker(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=fixture["repair_run_id"],
            role="worker",
            environ=bad_env,
            python_executable=sys.executable,
            python_version=platform.python_version(),
        )
    with pytest.raises(RuntimeError, match="Python version identity drift"):
        e3_launch_control.verify_slurm_worker(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=fixture["repair_run_id"],
            role="worker",
            environ=base,
            python_executable=sys.executable,
            python_version="0.0.0",
        )

    fixture["implementation"].write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="implementation file drift"):
        e3_launch_control.verify_slurm_worker(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=fixture["repair_run_id"],
            role="worker",
            environ=base,
            python_executable=sys.executable,
            python_version=platform.python_version(),
        )


def test_worker_revalidates_generic_record_only_evidence(tmp_path: Path) -> None:
    fixture = _prepare_fixture(tmp_path, bind_extra_evidence=True)
    e3_launch_control.authorize_slurm_identity(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        role="worker",
        job_id="43501",
    )
    e3_launch_control.authorize_slurm_identity(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        role="gate",
        job_id="43502",
    )
    e3_launch_control.seal_slurm_authorizations(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
    )
    launch_path = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_launch"
        / "launch_manifest.json"
    )
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
    evidence = launch["extra_evidence"]["origin_risk_audit"]
    assert evidence["policy"] == "record_only_keep_ancestral_no_exclusion"
    assert set(evidence["files"]) == {"eligible_list", "summary"}

    fixture["eligible_list"].write_text("1abc\n2def\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="extra evidence"):
        e3_launch_control.verify_slurm_worker(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=fixture["repair_run_id"],
            role="worker",
            environ=_runtime_env(fixture, SLURM_JOB_ID="43501"),
            python_executable=sys.executable,
            python_version=platform.python_version(),
        )


def test_concurrent_authorization_append_has_no_lost_updates(tmp_path: Path) -> None:
    fixture = _prepare_fixture(tmp_path)
    errors: list[Exception] = []

    def append(index: int) -> None:
        try:
            e3_launch_control.authorize_slurm_identity(
                fixture["root"],
                fixture["project_root"],
                repair_run_id=fixture["repair_run_id"],
                role="worker",
                job_id=str(44000 + index),
            )
        except Exception as exc:  # pragma: no cover - 失败时由主线程显式断言
            errors.append(exc)

    threads = [threading.Thread(target=append, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    allowed = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_launch"
        / "allowed_jobs"
    )
    assert sorted(path.name for path in allowed.glob("*.json")) == [
        f"worker-job-{44000 + index}.json" for index in range(8)
    ]
    e3_launch_control.authorize_slurm_identity(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        role="gate",
        job_id="44999",
    )
    e3_launch_control.seal_slurm_authorizations(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
    )
    with pytest.raises(RuntimeError, match="already sealed"):
        e3_launch_control.authorize_slurm_identity(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=fixture["repair_run_id"],
            role="worker",
            job_id="45000",
        )


def test_release_requires_success_gate_complete_terminal_snapshot(
    tmp_path: Path,
) -> None:
    fixture = _prepare_fixture(tmp_path)
    _authorize_worker_and_gate(fixture)
    gate_path = _write_gate_summary(fixture)
    with pytest.raises(RuntimeError, match="still active"):
        _write_scheduler_snapshot(
            fixture,
            active_output="42001|2|42001_2|RUNNING\n",
        )

    terminal_snapshot = _write_scheduler_snapshot(fixture)
    release = e3_launch_control.release_launch_control(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        scheduler_snapshot=terminal_snapshot,
        expected_gate_summary_sha256=sha256_file(gate_path),
    )
    assert release["status"] == "released"
    lock = fixture["root"] / "reports" / "runs" / "_locks" / "stage_e3_writer.lock"
    assert not lock.exists()
    release_path = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_launch"
        / "launch_release.json"
    )
    assert release_path.exists()
    replay = e3_launch_control.release_launch_control(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        scheduler_snapshot=terminal_snapshot,
        expected_gate_summary_sha256=sha256_file(gate_path),
    )
    assert replay == release

    other_snapshot = fixture["root"] / "controller" / "other_snapshot.json"
    other_snapshot.write_text(
        terminal_snapshot.read_text(encoding="utf-8") + " ", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="replayed evidence"):
        e3_launch_control.release_launch_control(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=fixture["repair_run_id"],
            scheduler_snapshot=other_snapshot,
            expected_gate_summary_sha256=sha256_file(gate_path),
        )


def test_release_does_not_remove_lock_with_unexpected_entries(tmp_path: Path) -> None:
    fixture = _prepare_fixture(tmp_path)
    _authorize_worker_and_gate(fixture)
    gate_path = _write_gate_summary(fixture)
    snapshot = _write_scheduler_snapshot(fixture)
    lock = fixture["root"] / "reports" / "runs" / "_locks" / "stage_e3_writer.lock"
    sentinel = lock / "foreign-evidence.txt"
    sentinel.write_text("keep\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected entries"):
        e3_launch_control.release_launch_control(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=fixture["repair_run_id"],
            scheduler_snapshot=snapshot,
            expected_gate_summary_sha256=sha256_file(gate_path),
        )
    assert sentinel.read_text(encoding="utf-8") == "keep\n"
    assert (lock / "owner.json").exists()
    assert not (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_launch"
        / "launch_release.json"
    ).exists()


def test_release_intent_recovers_if_interrupted_before_lock_removal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _prepare_fixture(tmp_path)
    _authorize_worker_and_gate(fixture)
    gate_path = _write_gate_summary(fixture)
    snapshot = _write_scheduler_snapshot(fixture)
    original_remove = e3_launch_control._remove_exact_global_lock

    def interrupt_after_intent(*_: object, **__: object) -> None:
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(
        e3_launch_control, "_remove_exact_global_lock", interrupt_after_intent
    )
    with pytest.raises(RuntimeError, match="simulated interruption"):
        e3_launch_control.release_launch_control(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=fixture["repair_run_id"],
            scheduler_snapshot=snapshot,
            expected_gate_summary_sha256=sha256_file(gate_path),
        )
    launch_dir = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_launch"
    )
    assert (
        json.loads(
            (launch_dir / "launch_release_intent.json").read_text(encoding="utf-8")
        )["status"]
        == "release_intent"
    )
    assert not (launch_dir / "launch_release.json").exists()
    assert (
        fixture["root"] / "reports" / "runs" / "_locks" / "stage_e3_writer.lock"
    ).exists()

    monkeypatch.setattr(e3_launch_control, "_remove_exact_global_lock", original_remove)
    release = e3_launch_control.release_launch_control(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        scheduler_snapshot=snapshot,
        expected_gate_summary_sha256=sha256_file(gate_path),
    )
    assert release["status"] == "released"
    assert release["release_intent_sha256"] == sha256_file(
        launch_dir / "launch_release_intent.json"
    )


def test_release_intent_recovers_after_lock_removed_before_final_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _prepare_fixture(tmp_path)
    _authorize_worker_and_gate(fixture)
    gate_path = _write_gate_summary(fixture)
    snapshot = _write_scheduler_snapshot(fixture)
    original_commit = e3_launch_control._commit_release_from_intent

    def interrupt_before_final(*_: object, **__: object) -> dict[str, object]:
        raise RuntimeError("simulated final-marker interruption")

    monkeypatch.setattr(
        e3_launch_control, "_commit_release_from_intent", interrupt_before_final
    )
    with pytest.raises(RuntimeError, match="final-marker interruption"):
        e3_launch_control.release_launch_control(
            fixture["root"],
            fixture["project_root"],
            repair_run_id=fixture["repair_run_id"],
            scheduler_snapshot=snapshot,
            expected_gate_summary_sha256=sha256_file(gate_path),
        )
    lock = fixture["root"] / "reports" / "runs" / "_locks" / "stage_e3_writer.lock"
    launch_dir = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_launch"
    )
    assert not lock.exists()
    assert (launch_dir / "launch_release_intent.json").exists()
    assert not (launch_dir / "launch_release.json").exists()

    monkeypatch.setattr(
        e3_launch_control, "_commit_release_from_intent", original_commit
    )
    release = e3_launch_control.release_launch_control(
        fixture["root"],
        fixture["project_root"],
        repair_run_id=fixture["repair_run_id"],
        scheduler_snapshot=snapshot,
        expected_gate_summary_sha256=sha256_file(gate_path),
    )
    assert release["status"] == "released"


def test_control_plane_does_not_import_scientific_or_external_tool_modules() -> None:
    source = Path(e3_launch_control.__file__).read_text(encoding="utf-8")
    forbidden = ("import density", "import chimera", "import mapq", "from density")
    assert all(token not in source.lower() for token in forbidden)
