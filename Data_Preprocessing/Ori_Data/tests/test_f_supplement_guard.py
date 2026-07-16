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

import f_supplement_guard as guard_module
from f_supplement_guard import (
    COLLISION_GUARD_EXIT_CODE,
    latest_formal_completed_tasks,
    supervise_f_supplement,
    validate_supplement_guard_contract,
    validate_supplement_stop_marker,
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


def _launcher_command() -> list[str]:
    """返回与生产 CLI 相同的 POSIX 启动屏障入口。"""
    script = Path(__file__).resolve().parents[1] / "scripts" / "f_supplement_guard.py"
    return [sys.executable, str(script)]


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
        child_pgid_path=tmp_path / "child-preflight.pgid",
        poll_seconds=0.01,
        termination_grace_seconds=0.1,
        launcher_command=_launcher_command(),
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
        child_pgid_path=tmp_path / "child-runtime.pgid",
        poll_seconds=0.05,
        termination_grace_seconds=1.0,
        launcher_command=_launcher_command(),
    )
    updater.join(timeout=1.0)
    assert exit_code == COLLISION_GUARD_EXIT_CODE
    record = json.loads(marker.read_text(encoding="utf-8"))
    assert record["formal_completed_tasks"] == 17386
    assert record["process_started"] is True


def test_stop_marker_validator_accepts_only_the_bound_collision_record(tmp_path: Path) -> None:
    """合法 marker 可复核；run、阈值或字段集合漂移时都必须拒绝。"""
    plan_path, ids_path, formal_log, plan = _guard_fixture(tmp_path)
    formal_log.write_text("Done 17386 tasks\n", encoding="utf-8")
    marker = tmp_path / "guard" / "stop.json"
    assert supervise_f_supplement(
        [sys.executable, "-c", "raise SystemExit(99)"],
        plan=plan,
        plan_path=plan_path,
        ids_path=ids_path,
        formal_log_path=formal_log,
        stop_marker_path=marker,
        child_pgid_path=tmp_path / "child-validator.pgid",
        poll_seconds=0.01,
        termination_grace_seconds=0.1,
        launcher_command=_launcher_command(),
    ) == COLLISION_GUARD_EXIT_CODE
    validated = validate_supplement_stop_marker(
        marker,
        plan=plan,
        plan_path=plan_path,
        ids_path=ids_path,
        formal_log_path=formal_log,
    )
    assert validated["supplement_run_id"] == "formal_fsupp96_v1"

    original = json.loads(marker.read_text(encoding="utf-8"))
    for field, bad_value, error in (
        ("supplement_run_id", "wrong_run", "identity drift"),
        ("formal_completed_tasks", 17385, "before the collision threshold"),
        ("unexpected", True, "field drift"),
    ):
        tampered = dict(original)
        tampered[field] = bad_value
        marker.write_text(json.dumps(tampered), encoding="utf-8")
        with pytest.raises((RuntimeError, ValueError), match=error):
            validate_supplement_stop_marker(
                marker,
                plan=plan,
                plan_path=plan_path,
                ids_path=ids_path,
                formal_log_path=formal_log,
            )


def test_child_exit_75_cannot_masquerade_as_collision_guard(tmp_path: Path) -> None:
    """工作负载自行退出 75 时没有 marker，supervisor 必须报安全错误。"""
    plan_path, ids_path, formal_log, plan = _guard_fixture(tmp_path)
    marker = tmp_path / "guard" / "child-75.json"
    child_pgid = tmp_path / "child-75.pgid"
    with pytest.raises(RuntimeError, match="reserved collision-guard exit code 75"):
        supervise_f_supplement(
            [sys.executable, "-c", "raise SystemExit(75)"],
            plan=plan,
            plan_path=plan_path,
            ids_path=ids_path,
            formal_log_path=formal_log,
            stop_marker_path=marker,
            child_pgid_path=child_pgid,
            poll_seconds=0.01,
            termination_grace_seconds=0.5,
            launcher_command=_launcher_command(),
        )
    assert not marker.exists()
    assert not child_pgid.exists()


def test_startup_failure_after_registration_preserves_pgid_for_outer_reaper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """启动表达式未返回但已登记时，不能因 process 仍为 None 而误删兜底证据。"""
    plan_path, ids_path, formal_log, plan = _guard_fixture(tmp_path)
    child_pgid = tmp_path / "startup-failure.pgid"

    def _fail_after_registration(
        _command: list[str],
        *,
        child_pgid_path: Path,
        launcher_command: list[str] | None,
        child_signal_mask: set[signal.Signals] | None,
        termination_grace_seconds: float,
    ) -> subprocess.Popen:
        del launcher_command, child_signal_mask, termination_grace_seconds
        child_pgid_path.write_text("999999\n", encoding="ascii")
        raise RuntimeError("synthetic startup failure after registration")

    monkeypatch.setattr(guard_module, "_start_registered_process", _fail_after_registration)
    with pytest.raises(RuntimeError, match="synthetic startup failure"):
        supervise_f_supplement(
            [sys.executable, "-c", "raise SystemExit(0)"],
            plan=plan,
            plan_path=plan_path,
            ids_path=ids_path,
            formal_log_path=formal_log,
            stop_marker_path=tmp_path / "guard" / "startup-failure.json",
            child_pgid_path=child_pgid,
            poll_seconds=0.01,
            termination_grace_seconds=0.1,
            launcher_command=_launcher_command(),
        )
    assert child_pgid.read_text(encoding="ascii") == "999999\n"


def test_posix_startup_uses_pipe_barrier_without_preexec_fn() -> None:
    """启动屏障必须使用继承 pipe，不得重新引入多线程不安全的 preexec_fn。"""
    code = (CODE_ROOT / "f_supplement_guard.py").read_text(encoding="utf-8")
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "f_supplement_guard.py"
    ).read_text(encoding="utf-8")
    assert "os.pipe()" in code
    assert "pass_fds=(barrier_read_fd,)" in code
    assert "_write_child_pgid(child_pgid_path, process.pid)" in code
    assert 'os.write(barrier_release_fd, b"R")' in code
    assert code.rindex("_write_child_pgid(child_pgid_path, process.pid)") < code.rindex(
        'os.write(barrier_release_fd, b"R")'
    )
    assert "signal.pthread_sigmask(signal.SIG_BLOCK" in code
    assert "signal.pthread_sigmask(signal.SIG_SETMASK" in script
    assert "preexec_fn" not in code


@pytest.mark.skipif(sys.platform != "linux", reason="Linux leader waitpid contract")
def test_default_term_leader_is_reaped_before_group_liveness_check() -> None:
    """直属 leader 按默认 TERM 退出时，必须先 waitpid，不能把 zombie 误判为活组。"""
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        start_new_session=True,
    )
    try:
        guard_module._terminate_process_group(process, grace_seconds=1.0)
        assert process.poll() == -signal.SIGTERM
        with pytest.raises(ProcessLookupError):
            os.killpg(process.pid, 0)
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5.0)


@pytest.mark.skipif(os.name != "posix", reason="POSIX orphan process-group contract")
def test_nonzero_leader_exit_reaps_surviving_grandchild(tmp_path: Path) -> None:
    """leader 非零退出后，supervisor 仍须按 PGID 回收存活孙进程。"""
    plan_path, ids_path, formal_log, plan = _guard_fixture(tmp_path)
    child_tree_path = tmp_path / "nonzero-child-tree.json"
    child_pgid_path = tmp_path / "nonzero-child.pgid"
    child_code = (
        "import json,os,subprocess,sys; from pathlib import Path; "
        "grand=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"Path({str(child_tree_path)!r}).write_text(json.dumps({{"
        "'child':os.getpid(),'grand':grand.pid})); "
        "raise SystemExit(7)"
    )
    exit_code = supervise_f_supplement(
        [sys.executable, "-c", child_code],
        plan=plan,
        plan_path=plan_path,
        ids_path=ids_path,
        formal_log_path=formal_log,
        stop_marker_path=tmp_path / "guard" / "nonzero-stop.json",
        child_pgid_path=child_pgid_path,
        poll_seconds=0.05,
        termination_grace_seconds=2.0,
        launcher_command=_launcher_command(),
    )
    assert exit_code == 7
    tree = json.loads(child_tree_path.read_text(encoding="utf-8"))
    assert not _pid_is_running(tree["grand"])
    assert not child_pgid_path.exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX SIGKILL recovery contract")
def test_verified_reaper_cleans_group_after_supervisor_sigkill(tmp_path: Path) -> None:
    """guard 自身被 KILL 后，受检 CLI 仍可用登记 PGID 回收整棵子树。"""
    plan_path, ids_path, formal_log, _plan = _guard_fixture(tmp_path)
    child_tree_path = tmp_path / "killed-guard-tree.json"
    child_pgid_path = tmp_path / "killed-guard.pgid"
    marker = tmp_path / "guard" / "killed-guard-stop.json"
    script = Path(__file__).resolve().parents[1] / "scripts" / "f_supplement_guard.py"
    child_code = (
        "import json,os,subprocess,sys,time; from pathlib import Path; "
        "grand=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"Path({str(child_tree_path)!r}).write_text(json.dumps({{"
        "'child':os.getpid(),'grand':grand.pid})); time.sleep(30)"
    )
    supervisor = subprocess.Popen(
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
            "--child_pgid_file",
            str(child_pgid_path),
            "--n_jobs",
            "12",
            "--poll_seconds",
            "1",
            "--termination_grace_seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            child_code,
        ]
    )
    tree: dict[str, int] | None = None
    try:
        registered_pgid = _wait_for_int_file(child_pgid_path)
        tree = _wait_for_json_file(child_tree_path)
        assert registered_pgid == tree["child"]
        os.kill(supervisor.pid, signal.SIGKILL)
        supervisor.wait(timeout=5.0)
        assert _pid_is_running(tree["grand"])

        reaper = subprocess.run(
            [
                sys.executable,
                str(script),
                "reap-child-group",
                "--child_pgid_file",
                str(child_pgid_path),
                "--expected_child_pgid_file",
                str(child_pgid_path),
                "--termination_grace_seconds",
                "2",
            ],
            check=False,
            timeout=10,
        )
        assert reaper.returncode == 0
        assert not child_pgid_path.exists()
        assert not _pid_is_running(tree["child"])
        assert not _pid_is_running(tree["grand"])
    finally:
        if tree is not None:
            try:
                os.killpg(tree["child"], signal.SIGKILL)
            except ProcessLookupError:
                pass
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=5.0)
        child_pgid_path.unlink(missing_ok=True)


@pytest.mark.skipif(os.name != "posix", reason="POSIX startup-barrier contract")
def test_workload_exec_observes_atomic_child_pgid_registration(tmp_path: Path) -> None:
    """真实工作负载一开始就必须看见已登记且等于自身 PID 的 PGID。"""
    plan_path, ids_path, formal_log, _plan = _guard_fixture(tmp_path)
    marker = tmp_path / "guard" / "startup.json"
    child_pgid = tmp_path / "startup.pgid"
    observation = tmp_path / "startup-observation.json"
    script = Path(__file__).resolve().parents[1] / "scripts" / "f_supplement_guard.py"
    child_code = (
        "import json,os,signal; from pathlib import Path; "
        f"p=Path({str(child_pgid)!r}); "
        f"Path({str(observation)!r}).write_text(json.dumps({{"
        "'exists':p.exists(),'registered':int(p.read_text()) if p.exists() else None,"
        "'pid':os.getpid(),'blocked':[int(s) for s in "
        "signal.pthread_sigmask(signal.SIG_BLOCK,set())]}))"
    )
    process = subprocess.run(
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
            "--child_pgid_file",
            str(child_pgid),
            "--n_jobs",
            "12",
            "--poll_seconds",
            "0.05",
            "--termination_grace_seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            child_code,
        ],
        check=False,
        timeout=5,
    )
    assert process.returncode == 0
    record = json.loads(observation.read_text(encoding="utf-8"))
    assert record["exists"] is True
    assert record["registered"] == record["pid"]
    assert int(signal.SIGTERM) not in record["blocked"]
    assert int(signal.SIGINT) not in record["blocked"]
    assert not child_pgid.exists()


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
            "--child_pgid_file",
            str(tmp_path / "child-signal.pgid"),
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
    child_pid = _wait_for_int_file(child_pid_path)
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


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group kill contract")
def test_registered_child_group_does_not_survive_real_outer_sigkill(tmp_path: Path) -> None:
    """模拟 core 的真实顺序：先 KILL 登记子组，再 KILL 外层组，不能留下孙进程。"""
    plan_path, ids_path, formal_log, _plan = _guard_fixture(tmp_path)
    child_tree_path = tmp_path / "child-tree.json"
    child_pgid_path = tmp_path / "child-kill.pgid"
    marker = tmp_path / "guard" / "outer-kill.json"
    script = Path(__file__).resolve().parents[1] / "scripts" / "f_supplement_guard.py"
    child_code = (
        "import json,os,subprocess,sys,time; from pathlib import Path; "
        "grand=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"Path({str(child_tree_path)!r}).write_text(json.dumps({{'child':os.getpid(),'grand':grand.pid}})); "
        "time.sleep(30)"
    )
    supervisor = subprocess.Popen(
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
            "--child_pgid_file",
            str(child_pgid_path),
            "--n_jobs",
            "12",
            "--poll_seconds",
            "1",
            "--termination_grace_seconds",
            "1",
            "--",
            sys.executable,
            "-c",
            child_code,
        ],
        start_new_session=True,
    )
    try:
        child_pgid = _wait_for_int_file(child_pgid_path)
        tree = _wait_for_json_file(child_tree_path)
        assert child_pgid == tree["child"]
        assert os.getpgid(tree["grand"]) == child_pgid

        # 与 opt-in core 的 KillWatcher 顺序一致，不能只杀外层 supervisor。
        os.killpg(child_pgid, signal.SIGKILL)
        try:
            os.killpg(supervisor.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        supervisor.wait(timeout=5.0)
        for process_id in (tree["child"], tree["grand"]):
            deadline = time.monotonic() + 5.0
            while _pid_is_running(process_id) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not _pid_is_running(process_id)
    finally:
        for process_group in (
            int(child_pgid_path.read_text(encoding="ascii"))
            if child_pgid_path.exists()
            else None,
            supervisor.pid,
        ):
            if process_group is None:
                continue
            try:
                os.killpg(process_group, signal.SIGKILL)
            except ProcessLookupError:
                pass
        child_pgid_path.unlink(missing_ok=True)


def _pid_is_running(process_id: int) -> bool:
    """把 Linux zombie 视为已停止，避免等待已被 KILL 但尚待回收的进程。"""
    stat_path = Path("/proc") / str(process_id) / "stat"
    if not stat_path.exists():
        return False
    fields = stat_path.read_text(encoding="ascii").split()
    return len(fields) > 2 and fields[2] != "Z"


def _wait_for_int_file(path: Path, timeout_seconds: float = 5.0) -> int:
    """等待另一个进程完成短文本原子量的写入，而不是只等待目录项出现。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            return int(path.read_text(encoding="ascii").strip())
        except (FileNotFoundError, ValueError):
            time.sleep(0.05)
    pytest.fail(f"timed out waiting for integer file: {path}")


def _wait_for_json_file(path: Path, timeout_seconds: float = 5.0) -> dict:
    """等待另一个进程写出可完整解析的 JSON。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(0.05)
            continue
        if isinstance(value, dict):
            return value
        pytest.fail(f"expected JSON object in {path}")
    pytest.fail(f"timed out waiting for JSON file: {path}")
