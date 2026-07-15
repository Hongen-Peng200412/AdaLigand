"""Stage F 补算计划绑定、正式进度解析和碰撞停止测试。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest


CODE_ROOT = Path(__file__).resolve().parents[1] / "code"
sys.path.insert(0, str(CODE_ROOT))

from f_supplement_guard import (
    COLLISION_GUARD_EXIT_CODE,
    latest_formal_completed_tasks,
    supervise_f_supplement,
    validate_supplement_guard_contract,
)
from io_utils import sha256_file


def _guard_fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict]:
    """创建彼此绑定的最小计划和 ID 文件。"""
    ids_path = (tmp_path / "pdb_ids.txt").resolve()
    ids_path.write_text("1abc\n2def\n", encoding="utf-8")
    formal_log = (tmp_path / "adaligand_f_316116.err").resolve()
    formal_log.write_text("Done 6026 tasks\n", encoding="utf-8")
    formal_log_stat = formal_log.stat()
    plan = {
        "schema_version": 1,
        "event": "stage_f_remote_tail_supplement_plan",
        "formal_run_id": "formal",
        "supplement_run_id": "formal_fsupp96_v1",
        "formal_job_id": 316116,
        "formal_log_path": str(formal_log),
        "formal_log_device": formal_log_stat.st_dev,
        "formal_log_inode": formal_log_stat.st_ino,
        "formal_completed_observed_at_plan": 6026,
        "pdb_ids_path": str(ids_path),
        "pdb_ids_sha256": sha256_file(ids_path),
        "tail_start_index_zero_based": 19386,
        "collision_stop_completed_tasks": 17386,
        "collision_guard_tasks": 2000,
        "resource_contract": {
            "formal_cpu": 96,
            "supplement_cpu": 96,
            "main_cpu_total": 192,
            "reserve_cpu": 48,
            "supplement_outer_n_jobs": 12,
            "mapq_np_per_pdb": 8,
        },
    }
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    return plan_path, ids_path, formal_log, plan


def test_guard_contract_binds_plan_ids_runs_and_resources(tmp_path: Path) -> None:
    """计划必须与 ID、run、Job ID 和 F12×np8 资源逐字段一致。"""
    plan_path, ids_path, formal_log, expected = _guard_fixture(tmp_path)
    actual = validate_supplement_guard_contract(
        plan_path,
        ids_path,
        formal_run_id="formal",
        supplement_run_id="formal_fsupp96_v1",
        formal_job_id=316116,
        formal_log_path=formal_log,
        n_jobs=12,
    )
    assert actual == expected

    with pytest.raises(RuntimeError, match="identity drift"):
        validate_supplement_guard_contract(
            plan_path,
            ids_path,
            formal_run_id="formal",
            supplement_run_id="another_run",
            formal_job_id=316116,
            formal_log_path=formal_log,
            n_jobs=12,
        )
    with pytest.raises(RuntimeError, match="n_jobs"):
        validate_supplement_guard_contract(
            plan_path,
            ids_path,
            formal_run_id="formal",
            supplement_run_id="formal_fsupp96_v1",
            formal_job_id=316116,
            formal_log_path=formal_log,
            n_jobs=16,
        )

    another_log = tmp_path / "another.err"
    another_log.write_text("Done 6026 tasks\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="different formal Stage F log"):
        validate_supplement_guard_contract(
            plan_path,
            ids_path,
            formal_run_id="formal",
            supplement_run_id="formal_fsupp96_v1",
            formal_job_id=316116,
            formal_log_path=another_log,
            n_jobs=12,
        )

    formal_log.write_text("no joblib progress\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="lost its current joblib progress"):
        validate_supplement_guard_contract(
            plan_path,
            ids_path,
            formal_run_id="formal",
            supplement_run_id="formal_fsupp96_v1",
            formal_job_id=316116,
            formal_log_path=formal_log,
            n_jobs=12,
        )


def test_latest_progress_uses_last_attempt_instead_of_historical_max(tmp_path: Path) -> None:
    """恢复日志中旧 attempt 的 22363 不能覆盖当前 attempt 的 6026。"""
    log_path = tmp_path / "formal.err"
    log_path.write_text(
        "[Parallel(n_jobs=12)]: Done 22363 tasks\n"
        "[Attempt] retry\n"
        "[Parallel(n_jobs=12)]: Done 6026 tasks\n",
        encoding="utf-8",
    )
    assert latest_formal_completed_tasks(log_path) == 6026


def test_preflight_guard_stops_without_launching_command(tmp_path: Path) -> None:
    """正式进度已到阈值时不启动补算，并留下明确停止证据。"""
    plan_path, ids_path, log_path, plan = _guard_fixture(tmp_path)
    log_path.write_text("Done 17386 tasks\n", encoding="utf-8")
    marker = tmp_path / "guard" / "stop.json"
    exit_code = supervise_f_supplement(
        [sys.executable, "-c", "raise SystemExit(99)"],
        plan=plan,
        plan_path=plan_path,
        ids_path=ids_path,
        formal_log_path=log_path,
        stop_marker_path=marker,
        poll_seconds=0.01,
        termination_grace_seconds=0.1,
    )
    assert exit_code == COLLISION_GUARD_EXIT_CODE
    record = json.loads(marker.read_text(encoding="utf-8"))
    assert record["formal_completed_tasks"] == 17386
    assert record["process_started"] is False
    assert record["result"].startswith("supplement_stopped")


def test_runtime_guard_terminates_active_supplement(tmp_path: Path) -> None:
    """补算启动后正式进度跨阈值时，守卫应终止子进程并记录运行中停止。"""
    plan_path, ids_path, log_path, plan = _guard_fixture(tmp_path)
    marker = tmp_path / "guard" / "runtime-stop.json"

    def _advance_formal_progress() -> None:
        time.sleep(0.1)
        log_path.write_text("Done 17386 tasks\n", encoding="utf-8")

    updater = threading.Thread(target=_advance_formal_progress)
    updater.start()
    exit_code = supervise_f_supplement(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        plan=plan,
        plan_path=plan_path,
        ids_path=ids_path,
        formal_log_path=log_path,
        stop_marker_path=marker,
        poll_seconds=0.05,
        termination_grace_seconds=1.0,
    )
    updater.join(timeout=1.0)
    assert exit_code == COLLISION_GUARD_EXIT_CODE
    record = json.loads(marker.read_text(encoding="utf-8"))
    assert record["formal_completed_tasks"] == 17386
    assert record["process_started"] is True


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group signal contract")
def test_supervisor_sigterm_cleans_independent_child_session(tmp_path: Path) -> None:
    """外层 kill-lock 对 supervisor 发 TERM 时，独立子 session 也必须退出。"""
    plan_path, ids_path, formal_log, _plan = _guard_fixture(tmp_path)
    child_pid_path = tmp_path / "child.pid"
    marker = tmp_path / "guard" / "signal-stop.json"
    script = Path(__file__).resolve().parents[1] / "scripts" / "f_supplement_guard.py"
    child_code = (
        "import os,time; from pathlib import Path; "
        f"Path({str(child_pid_path)!r}).write_text(str(os.getpid())); "
        "time.sleep(30)"
    )
    process = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--plan",
            str(plan_path),
            "--ids",
            str(ids_path),
            "--formal_run_id",
            "formal",
            "--supplement_run_id",
            "formal_fsupp96_v1",
            "--formal_job_id",
            "316116",
            "--formal_log",
            str(formal_log),
            "--stop_marker",
            str(marker),
            "--n_jobs",
            "12",
            "--poll_seconds",
            "0.1",
            "--termination_grace_seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            child_code,
        ]
    )
    deadline = time.monotonic() + 5.0
    while not child_pid_path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert child_pid_path.exists()
    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    os.kill(process.pid, signal.SIGTERM)
    assert process.wait(timeout=5.0) == 128 + signal.SIGTERM

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("supplement child process survived supervisor SIGTERM")
