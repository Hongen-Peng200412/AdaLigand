
"""AdaLigand sbatch 资源参数与动态 run_cmd 契约测试。"""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SBATCH_ROOT = PROJECT_ROOT / "sbatch"


def test_job_core_reuses_a_valid_preloaded_run_cmd() -> None:
    """专用 core 必须复用普通文件，并在首次及每次重试前重新校验。"""
    core = (SBATCH_ROOT / "_adaligand_job_core.sh").read_text(encoding="utf-8")

    assert 'elif [ -f "${RUN_CMD_FILE}" ]; then' in core
    assert "[RunCmd] reusing preloaded file" in core
    assert 'write_adaligand_run_cmd "${RUN_CMD_FILE}"' in core
    validation_start = core.index("validate_run_cmd()")
    validation_end = core.index("\n}\n", validation_start)
    validation_body = core[validation_start:validation_end]
    assert '[ -L "${RUN_CMD_FILE}" ]' in validation_body
    assert 'bash -n "${RUN_CMD_FILE}"' in validation_body
    assert 'sha256sum "${RUN_CMD_FILE}"' in validation_body
    retry_loop = core.index("while true; do")
    retry_validation = core.index("    validate_run_cmd", retry_loop)
    command_start = core.index("    setsid stdbuf", retry_loop)
    assert retry_loop < retry_validation < command_start


def test_full_pipeline_resource_defaults_match_cpu96_contract() -> None:
    """未来完整提交默认使用 D64/E24、F12，并保留 G 的单 CPU analyze。"""
    de_script = (SBATCH_ROOT / "de_full.sbatch").read_text(encoding="utf-8")
    f_script = (SBATCH_ROOT / "f_full.sbatch").read_text(encoding="utf-8")
    g_script = (SBATCH_ROOT / "g_analyze.sbatch").read_text(encoding="utf-8")
    submit_script = (SBATCH_ROOT / "submit_full_pipeline.sh").read_text(encoding="utf-8")

    assert '${D_N_JOBS:-64}' in de_script
    assert '${E_N_JOBS:-24}' in de_script
    assert '${E_TIMEOUT_SECONDS:-3600}' in de_script
    assert '${F_N_JOBS:-12}' in f_script
    assert "#SBATCH --cpus-per-task=1" in g_script
    assert "D_N_JOBS=64,E_N_JOBS=24" in submit_script
    assert "F_N_JOBS=12" in submit_script


def _bash_executable() -> Path | None:
    """定位 Linux、MSYS2 或 Git for Windows 的 Bash。"""
    discovered = shutil.which("bash")
    candidates = [
        Path(discovered) if discovered else None,
        Path("C:/msys64/usr/bin/bash.exe"),
        Path("C:/Program Files/Git/bin/bash.exe"),
    ]
    return next((path for path in candidates if path is not None and path.is_file()), None)


def _bash_path(path: Path) -> str:
    """把 Windows 路径转换为 MSYS Bash 可直接消费的形式。"""
    resolved = path.resolve()
    if os.name != "nt":
        return str(resolved)
    drive = resolved.drive.rstrip(":").lower()
    tail = resolved.as_posix()[3:]
    return f"/{drive}/{tail}"


def _prepare_job_core_process_tree(
    tmp_path: Path,
    *,
    job_offset: int,
    wait_for_child: bool,
    ignore_term: bool,
) -> tuple[Path, Path, Path, dict[str, str], int]:
    """构造仅重绑定固定路径的 core 与真实独立 child/grandchild 进程树。"""
    fake_home = (tmp_path / "home").resolve()
    fake_code_root = (tmp_path / "code").resolve()
    fake_data_root = (tmp_path / "data").resolve()
    for directory in (fake_home, fake_code_root, fake_data_root):
        directory.mkdir(parents=True)

    job_id = 800_000_000 + (os.getpid() % 10_000_000) * 10 + job_offset
    child_pgid_path = fake_home / f"child_pgid_{job_id}"
    tree_path = tmp_path / f"process-tree-{job_offset}.json"
    grand_ready_path = tmp_path / f"grand-ready-{job_offset}"

    grand_lines = ["import signal, time", "from pathlib import Path"]
    if ignore_term:
        grand_lines.append("signal.signal(signal.SIGTERM, signal.SIG_IGN)")
    grand_lines.extend(
        [
            f"Path({str(grand_ready_path)!r}).write_text('ready', encoding='ascii')",
            "time.sleep(60)",
        ]
    )
    grand_code = "\n".join(grand_lines)
    child_lines = [
        "import json, os, signal, subprocess, sys, time",
        "from pathlib import Path",
    ]
    if ignore_term:
        child_lines.append("signal.signal(signal.SIGTERM, signal.SIG_IGN)")
    child_lines.extend(
        [
            f"grand = subprocess.Popen([sys.executable, '-c', {grand_code!r}])",
            f"ready = Path({str(grand_ready_path)!r})",
            "deadline = time.monotonic() + 5.0",
            "while not ready.exists():",
            "    if time.monotonic() >= deadline:",
            "        raise RuntimeError('grandchild readiness timeout')",
            "    time.sleep(0.01)",
            (
                f"Path({str(tree_path)!r}).write_text(json.dumps({{"
                "'child': os.getpid(), 'grand': grand.pid}), encoding='utf-8')"
            ),
            "time.sleep(60)",
        ]
    )
    child_code = "\n".join(child_lines)

    run_cmd_path = fake_home / f"run_cmd_{job_id}.sh"
    run_tail = 'wait "$child"\nexit $?' if wait_for_child else "exit 7"
    # 独立组 leader 自己先登记 PGID 再 exec 工作负载；即使外层 Bash 同时中断，
    # 测试 finally 仍能取得精确身份并定界回收，不依赖较晚形成的 tree JSON。
    child_launcher = (
        f"printf '%s\\n' \"$$\" > {shlex.quote(str(child_pgid_path))}; "
        f"exec {shlex.quote(sys.executable)} -c {shlex.quote(child_code)}"
    )
    registration_wait = (
        f"    if [ -s {shlex.quote(str(child_pgid_path))} ] "
        f"&& [ -s {shlex.quote(str(tree_path))} ]; then break; fi\n"
    )
    run_cmd_path.write_text(
        "".join(
            [
                "#!/usr/bin/env bash\n",
                "set -u\n",
                f"setsid bash -c {shlex.quote(child_launcher)} &\n",
                "child=$!\n",
                "for ((attempt=0; attempt<500; attempt++)); do\n",
                registration_wait,
                "    sleep 0.01\n",
                "done\n",
                (
                    f"if [ \"$(cat {shlex.quote(str(child_pgid_path))} 2>/dev/null)\" "
                    "!= \"$child\" ]; then exit 69; fi\n"
                ),
                f"if [ ! -s {shlex.quote(str(tree_path))} ]; then exit 68; fi\n",
                f"{run_tail}\n",
            ]
        ),
        encoding="utf-8",
    )

    core_text = (SBATCH_ROOT / "_adaligand_job_core.sh").read_text(encoding="utf-8")
    replacements = (
        (
            "/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data",
            str(fake_code_root),
        ),
        ("/storage/penghongen/AdaLigand/Ori_Data", str(fake_data_root)),
        (
            "/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python",
            sys.executable,
        ),
        ("/home/penghongen", str(fake_home)),
    )
    for original, replacement in replacements:
        core_text = core_text.replace(original, replacement)
    core_path = tmp_path / f"job-core-{job_offset}.sh"
    core_path.write_text(core_text, encoding="utf-8")
    core_path.chmod(0o700)

    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(fake_home),
            "SLURM_JOB_ID": str(job_id),
            "SLURM_CPUS_PER_TASK": "96",
            "ADALIGAND_RUN_ID": f"core_process_tree_{job_offset}",
            "ADALIGAND_HOLD_ON_FAILURE": "0",
            "ADALIGAND_EXTRA_KILL_PGID_FILE": str(child_pgid_path),
        }
    )
    return core_path, tree_path, child_pgid_path, environment, job_id


def _wait_for_process_tree(path: Path, timeout_seconds: float = 10.0) -> dict[str, int]:
    """等待 child/grandchild 身份文件完成原子量级写入。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return {"child": int(payload["child"]), "grand": int(payload["grand"])}
        except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            time.sleep(0.05)
    pytest.fail(f"timed out waiting for process tree: {path}")


def _read_strict_child_pgid(path: Path) -> int | None:
    """只接受精确普通文件中的单个正整数 PGID；文件尚未出现时返回 None。"""
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise AssertionError(f"invalid child PGID file type: {path}")
    raw_value = path.read_text(encoding="ascii")
    if not re.fullmatch(r"[0-9]+\n?", raw_value):
        raise AssertionError(f"invalid child PGID payload: {raw_value!r}")
    return int(raw_value)


def _try_read_process_tree(path: Path) -> dict[str, int] | None:
    """读取完整 tree JSON；并发写入尚未闭合时返回 None。"""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {"child": int(payload["child"]), "grand": int(payload["grand"])}
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _resolve_child_group_for_cleanup(
    child_pgid_path: Path,
    tree_path: Path,
    tree: dict[str, int] | None,
    *,
    timeout_seconds: float = 3.0,
) -> int | None:
    """优先等待精确 PGID 登记；仅在登记不可用时回退到同一测试的 tree。"""
    deadline = time.monotonic() + timeout_seconds
    discovered_tree = tree
    while time.monotonic() < deadline:
        try:
            registered_pgid = _read_strict_child_pgid(child_pgid_path)
        except AssertionError:
            registered_pgid = None
        if registered_pgid is not None:
            return registered_pgid
        if discovered_tree is None:
            discovered_tree = _try_read_process_tree(tree_path)
        if discovered_tree is not None:
            return discovered_tree["child"]
        time.sleep(0.05)
    return discovered_tree["child"] if discovered_tree is not None else None


def _test_process_group_is_alive(process_group_id: int) -> bool:
    """只读判断测试专属进程组是否仍存在。"""
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for_test_process_group_exit(
    process_group_id: int,
    *,
    timeout_seconds: float,
    direct_process: subprocess.Popen[str] | None = None,
) -> bool:
    """有界等待测试组消失，并主动回收直属 Popen leader。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if direct_process is not None:
            direct_process.poll()
        if not _test_process_group_is_alive(process_group_id):
            return True
        time.sleep(0.05)
    if direct_process is not None:
        direct_process.poll()
    return not _test_process_group_is_alive(process_group_id)


def _terminate_test_process_group(
    process_group_id: int,
    *,
    forbidden_groups: set[int],
    direct_process: subprocess.Popen[str] | None = None,
) -> None:
    """拒绝危险 PGID，并以有界 TERM→KILL 顺序回收一个测试专属组。"""
    if process_group_id <= 1 or process_group_id in forbidden_groups:
        raise AssertionError(f"refusing unsafe test cleanup PGID: {process_group_id}")
    if direct_process is not None:
        direct_process.poll()
    if not _test_process_group_is_alive(process_group_id):
        return
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return
    if _wait_for_test_process_group_exit(
        process_group_id,
        timeout_seconds=1.0,
        direct_process=direct_process,
    ):
        return
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        return
    if not _wait_for_test_process_group_exit(
        process_group_id,
        timeout_seconds=5.0,
        direct_process=direct_process,
    ):
        raise AssertionError(f"test process group survived SIGKILL: {process_group_id}")


def _cleanup_core_process_tree(
    process: subprocess.Popen[str],
    *,
    child_pgid_path: Path,
    tree_path: Path,
    tree: dict[str, int] | None,
) -> None:
    """先定界回收独立 child 组，再回收 core 外层组，且始终避开 pytest 当前组。"""
    current_test_group = os.getpgrp()
    outer_group = process.pid
    cleanup_errors: list[str] = []
    child_group = _resolve_child_group_for_cleanup(child_pgid_path, tree_path, tree)
    if child_group is None:
        cleanup_errors.append("child PGID/tree identity did not become available")
    else:
        try:
            _terminate_test_process_group(
                child_group,
                forbidden_groups={current_test_group, outer_group},
            )
        except AssertionError as exc:
            cleanup_errors.append(str(exc))

    try:
        _terminate_test_process_group(
            outer_group,
            forbidden_groups={current_test_group},
            direct_process=process,
        )
    except AssertionError as exc:
        cleanup_errors.append(str(exc))
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5.0)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    child_pgid_path.unlink(missing_ok=True)
    if cleanup_errors:
        raise AssertionError("; ".join(cleanup_errors))


def _linux_pid_is_running(process_id: int) -> bool:
    """把已被终止但尚待系统回收的 Linux zombie 视为不再运行。"""
    stat_path = Path("/proc") / str(process_id) / "stat"
    if not stat_path.exists():
        return False
    fields = stat_path.read_text(encoding="ascii").split()
    return len(fields) > 2 and fields[2] != "Z"


def _assert_process_tree_stopped(tree: dict[str, int], timeout_seconds: float = 5.0) -> None:
    """等待真实 child/grandchild 均退出，并给异步 init 回收留出短窗口。"""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not any(_linux_pid_is_running(process_id) for process_id in tree.values()):
            return
        time.sleep(0.05)
    running = [process_id for process_id in tree.values() if _linux_pid_is_running(process_id)]
    pytest.fail(f"job core left process-tree members running: {running}")


_LINUX_CORE_TREE_UNAVAILABLE = (
    sys.platform != "linux"
    or shutil.which("bash") is None
    or shutil.which("setsid") is None
    or shutil.which("stdbuf") is None
)


@pytest.mark.skipif(_LINUX_CORE_TREE_UNAVAILABLE, reason="real Linux Bash process tree required")
def test_job_core_reaps_child_tree_after_ordinary_run_cmd_failure(tmp_path: Path) -> None:
    """普通 run_cmd 失败也必须在进入失败分支前回收登记的 child 与 grandchild。"""
    core_path, tree_path, child_pgid_path, environment, _job_id = (
        _prepare_job_core_process_tree(
            tmp_path,
            job_offset=1,
            wait_for_child=False,
            ignore_term=False,
        )
    )
    process: subprocess.Popen[str] | None = None
    tree: dict[str, int] | None = None
    try:
        process = subprocess.Popen(
            [shutil.which("bash") or "bash", str(core_path)],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        stdout, stderr = process.communicate(timeout=20)
        tree = _wait_for_process_tree(tree_path)
        assert process.returncode == 7, stdout + stderr
        _assert_process_tree_stopped(tree)
        assert not child_pgid_path.exists()
        assert "[Failure] run_cmd exited 7" in stdout
    finally:
        if process is not None:
            _cleanup_core_process_tree(
                process,
                child_pgid_path=child_pgid_path,
                tree_path=tree_path,
                tree=tree,
            )


@pytest.mark.skipif(_LINUX_CORE_TREE_UNAVAILABLE, reason="real Linux Bash process tree required")
def test_job_core_kill_lock_sigkills_term_ignoring_child_tree(tmp_path: Path) -> None:
    """kill-lock 必须以 SIGKILL 兜底清除忽略 TERM 的 child 与 grandchild。"""
    core_path, tree_path, child_pgid_path, environment, job_id = (
        _prepare_job_core_process_tree(
            tmp_path,
            job_offset=2,
            wait_for_child=True,
            ignore_term=True,
        )
    )
    kill_lock_path = child_pgid_path.parent / f"kill_lock_{job_id}"
    process: subprocess.Popen[str] | None = None
    tree: dict[str, int] | None = None
    try:
        process = subprocess.Popen(
            [shutil.which("bash") or "bash", str(core_path)],
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        tree = _wait_for_process_tree(tree_path)
        assert _read_strict_child_pgid(child_pgid_path) == tree["child"]
        kill_lock_path.touch()
        stdout, stderr = process.communicate(timeout=25)
        assert process.returncode != 0, stdout + stderr
        _assert_process_tree_stopped(tree)
        assert not child_pgid_path.exists()
        assert f"signal 9 to registered child process group {tree['child']}" in stdout
    finally:
        if process is not None:
            _cleanup_core_process_tree(
                process,
                child_pgid_path=child_pgid_path,
                tree_path=tree_path,
                tree=tree,
            )


def test_job_core_reaps_opt_in_child_group_before_outer_kill() -> None:
    """补算专用 PGID 登记启用时，kill-lock 必须先收割独立子组。"""
    core = (SBATCH_ROOT / "_adaligand_job_core.sh").read_text(encoding="utf-8")

    assert 'EXTRA_KILL_PGID_FILE="${ADALIGAND_EXTRA_KILL_PGID_FILE:-}"' in core
    assert 'expected_extra_pgid_file="/home/penghongen/child_pgid_${SLURM_JOB_ID}"' in core
    watcher_start = core.index('if [ -f "${KILL_LOCK}" ]; then')
    child_kill = core.index("reap_extra_process_group 0 5", watcher_start)
    outer_kill = core.index('kill -9 -"${RUN_PID}"', watcher_start)
    assert watcher_start < child_kill < outer_kill
    cleanup_start = core.index("cleanup()")
    cleanup_end = core.index("\n}", cleanup_start)
    assert "reap_extra_process_group 0 5" in core[cleanup_start:cleanup_end]
    assert 'ps -o pgid= -p "${candidate}"' not in core
    assert 'kill -0 -- "-${candidate}"' in core

    wait_start = core.index('wait "${RUN_PID}" && attempt_exit=0 || attempt_exit=$?')
    attempt_reap = core.index("reap_extra_process_group 10 5", wait_start)
    clear_run_pid = core.index('RUN_PID=""', wait_start)
    success_branch = core.index('if [ "${attempt_exit}" -eq 0 ]', clear_run_pid)
    assert wait_start < attempt_reap < clear_run_pid < success_branch


def test_de_f_g_use_cluster_unlimited_walltime_default() -> None:
    """DE/F/G 不应重新引入会截断多日正式运行的显式 walltime。"""
    for script_name in ("de_full.sbatch", "f_full.sbatch", "g_analyze.sbatch"):
        script = (SBATCH_ROOT / script_name).read_text(encoding="utf-8")
        assert "#SBATCH --time" not in script
