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


def test_f_supplement_uses_independent_cpu96_tail_contract() -> None:
    """单次补算入口复用共享实现，并保留原有 guard=75 成功退出语义。"""
    script = (SBATCH_ROOT / "f_supplement_96.sbatch").read_text(encoding="utf-8")
    helper = (SBATCH_ROOT / "_f_supplement_stage.sh").read_text(encoding="utf-8")

    assert "#SBATCH --cpus-per-task=96" in script
    assert "#SBATCH --time" not in script
    assert '${F_N_JOBS:-12}' in script
    assert 'source "${supplement_helper_path}"' in script
    assert script.count("run_adaligand_f_supplement_stage") == 1
    assert "ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID" in script
    assert "ADALIGAND_F_SUPPLEMENT_IDS_SHA256" in script
    assert "ADALIGAND_F_SUPPLEMENT_PLAN_SHA256" in script
    assert "ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID" in script
    assert "ADALIGAND_F_SUPPLEMENT_FORMAL_LOG" in script
    assert "ADALIGAND_EXTRA_KILL_PGID_FILE" in script
    assert 'if [[ "${supplement_exit}" -eq 75 ]]' in script
    assert "collision guard is a successful no-op" in script

    helper_digest = hashlib.sha256((SBATCH_ROOT / "_f_supplement_stage.sh").read_bytes()).hexdigest()
    frozen_digest = re.search(
        r'expected_supplement_helper_sha256="([0-9a-f]{64})"', script
    )
    assert frozen_digest is not None
    assert frozen_digest.group(1) == helper_digest
    helper_hash_check = script.index('if ! helper_digest_line="$(sha256sum')
    helper_source = script.index('source "${supplement_helper_path}"')
    assert helper_hash_check < helper_source

    assert 'if [[ "${supplement_n_jobs}" != "12" ]]' in helper
    assert 'if [[ "${SLURM_CPUS_PER_TASK:-}" != "96" ]]' in helper
    assert "scripts/f_supplement_guard.py" in helper
    assert "--stop_marker" in helper
    assert "--child_pgid_file" in helper
    assert '--pdb_ids_file "${ids_file}"' in helper
    assert '--run_id "${supplement_run_id}"' in helper
    assert "--gate_name f_supplement_release" in helper
    assert "--gate_name f_release" not in helper
    child_pgid_check = 'if [[ -L "${child_pgid_file}" || -e "${child_pgid_file}" ]]'
    assert helper.count(child_pgid_check) == 2
    guard_start = helper.index('if "${PYTHON}" scripts/f_supplement_guard.py')
    child_check = helper.index(child_pgid_check, guard_start)
    gate_start = helper.index('"${PYTHON}" scripts/stage_release_gate.py')
    assert guard_start < child_check < gate_start
    assert "validate-marker" in helper
    assert "reserved guard exit 75 lacks an authentic stop marker" in helper
    assert "release gate used reserved collision-guard exit code 75" in helper


def test_f_supplement_accel_wrapper_runs_v1_gate_before_independent_v2() -> None:
    """318350 只能串行完成 v1 gate 后再进入显式冻结的独立 v2。"""
    script = (
        SBATCH_ROOT / "resume_f_supplement_318350_accel_v2.sh"
    ).read_text(encoding="utf-8")

    assert 'expected_supplement_job_id="318350"' in script
    assert 'expected_v1_run_id="adaligand_ag_20260711T154658_fsupp96_v1"' in script
    assert 'expected_v2_run_id="adaligand_ag_20260711T154658_fsupp96_v2"' in script
    assert 'expected_formal_run_id="adaligand_ag_20260711T154658"' in script
    assert 'expected_formal_job_id="316116"' in script
    assert (
        'expected_formal_log="/storage/penghongen/AdaLigand/Ori_Data/logs/f/'
        'adaligand_f_316116.err"'
    ) in script
    assert '${F_N_JOBS:-12}' in script
    assert script.count("run_adaligand_f_supplement_stage") == 2
    assert '${ADALIGAND_EXTRA_KILL_PGID_FILE:?' in script
    assert script.count('"${ADALIGAND_EXTRA_KILL_PGID_FILE}"') == 2

    for variable in (
        "ADALIGAND_F_SUPPLEMENT_V2_RUN_ID",
        "ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE",
        "ADALIGAND_F_SUPPLEMENT_V2_IDS_SHA256",
        "ADALIGAND_F_SUPPLEMENT_V2_PLAN_FILE",
        "ADALIGAND_F_SUPPLEMENT_V2_PLAN_SHA256",
    ):
        assert f'${{{variable}:?' in script

    v1_call = script.index("if run_adaligand_f_supplement_stage")
    v1_guard_stop = script.index('if [[ "${v1_exit}" -eq 75 ]]', v1_call)
    v1_failure = script.index('if [[ "${v1_exit}" -ne 0 ]]', v1_guard_stop)
    v1_gate_message = script.index("v1 gate passed", v1_failure)
    v2_call = script.index("if run_adaligand_f_supplement_stage", v1_gate_message)
    assert v1_call < v1_guard_stop < v1_failure < v1_gate_message < v2_call
    assert "v1 guard stopped; v2 will not start" in script
    assert "v2 guard stopped; no later segment will start" in script
    assert 'if [[ "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" != "${expected_v2_run_id}" ]]' in script
    assert 'if [[ "${v2_exit}" -eq 75 ]]' in script
    assert 'exit "${v2_exit}"' in script

    helper_digest = hashlib.sha256((SBATCH_ROOT / "_f_supplement_stage.sh").read_bytes()).hexdigest()
    frozen_digest = re.search(
        r'expected_supplement_helper_sha256="([0-9a-f]{64})"', script
    )
    assert frozen_digest is not None
    assert frozen_digest.group(1) == helper_digest


@pytest.mark.parametrize(
    (
        "guard_exit",
        "marker_exit",
        "gate_exit",
        "create_pgid",
        "reaper_exit",
        "expected_exit",
    ),
    (
        (75, 0, 0, False, 0, 75),
        (75, 1, 0, False, 0, 70),
        (0, 0, 75, False, 0, 70),
        (0, 0, 0, False, 0, 0),
        (137, 0, 0, True, 0, 137),
        (137, 0, 0, True, 1, 70),
    ),
)
def test_f_supplement_helper_reserves_exit_75_for_validated_guard_marker(
    tmp_path: Path,
    guard_exit: int,
    marker_exit: int,
    gate_exit: int,
    create_pgid: bool,
    reaper_exit: int,
    expected_exit: int,
) -> None:
    """真实 Bash 调用中，只有 marker 复核成功的 guard=75 才能向上传播。"""
    bash = _bash_executable()
    if bash is None:
        pytest.skip("Bash is required for sourced-helper integration tests")

    fake_root = tmp_path / "fake-code"
    scripts = fake_root / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "f_supplement_guard.py").write_text(
        "import os,sys\nfrom pathlib import Path\n"
        "def option(name):\n"
        "    return sys.argv[sys.argv.index(name) + 1]\n"
        "if sys.argv[1:2] == ['reap-child-group']:\n"
        "    if int(os.environ['FAKE_REAPER_EXIT']) == 0:\n"
        "        Path(option('--child_pgid_file')).unlink(missing_ok=True)\n"
        "    raise SystemExit(int(os.environ['FAKE_REAPER_EXIT']))\n"
        "if sys.argv[1:2] == ['validate-marker']:\n"
        "    raise SystemExit(int(os.environ['FAKE_MARKER_EXIT']))\n"
        "if int(os.environ['FAKE_CREATE_PGID']):\n"
        "    Path(option('--child_pgid_file')).write_text('4242\\n')\n"
        "raise SystemExit(int(os.environ['FAKE_GUARD_EXIT']))\n",
        encoding="utf-8",
    )
    (scripts / "stage_release_gate.py").write_text(
        "import os\nraise SystemExit(int(os.environ['FAKE_GATE_EXIT']))\n",
        encoding="utf-8",
    )
    (scripts / "f_quality.py").write_text("raise SystemExit(99)\n", encoding="utf-8")
    ids_path = tmp_path / "ids.txt"
    ids_path.write_text("1abc\n", encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    plan_path.write_text("{}\n", encoding="utf-8")
    formal_log = tmp_path / "formal.err"
    formal_log.write_text("Done 1 tasks\n", encoding="utf-8")
    child_pgid = tmp_path / "child.pgid"

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"/usr/bin:{environment.get('PATH', '')}",
            "DATA_ROOT": _bash_path(tmp_path / "data"),
            "PYTHON": _bash_path(Path(sys.executable)),
            "CHIMERA": "fake-chimera",
            "CHIMERA_ROOT": "fake-chimera-root",
            "MAPQ_CMD": "fake-mapq",
            "MAPQ_ZIP": "fake-mapq-zip",
            "SCRATCH_ROOT": _bash_path(tmp_path / "scratch"),
            "SLURM_CPUS_PER_TASK": "96",
            "FAKE_GUARD_EXIT": str(guard_exit),
            "FAKE_MARKER_EXIT": str(marker_exit),
            "FAKE_GATE_EXIT": str(gate_exit),
            "FAKE_CREATE_PGID": "1" if create_pgid else "0",
            "FAKE_REAPER_EXIT": str(reaper_exit),
            "HELPER_PATH": _bash_path(SBATCH_ROOT / "_f_supplement_stage.sh"),
            "IDS_PATH": _bash_path(ids_path),
            "PLAN_PATH": _bash_path(plan_path),
            "FORMAL_LOG": _bash_path(formal_log),
            "CHILD_PGID": _bash_path(child_pgid),
            "IDS_SHA": hashlib.sha256(ids_path.read_bytes()).hexdigest(),
            "PLAN_SHA": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        }
    )
    command = """
set -u
source "${HELPER_PATH}"
helper_exit=0
if run_adaligand_f_supplement_stage \
  supplement_run "${IDS_PATH}" "${IDS_SHA}" "${PLAN_PATH}" "${PLAN_SHA}" \
  formal_run 316116 "${FORMAL_LOG}" 12 "${CHILD_PGID}"; then
    helper_exit=0
else
    helper_exit="$?"
fi
printf '%s\n' "${helper_exit}"
"""
    result = subprocess.run(
        [str(bash), "-c", command],
        cwd=fake_root,
        env=environment,
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout.splitlines()[-1]) == expected_exit, (
        result.stdout,
        result.stderr,
    )


def test_generated_f_supplement_run_cmd_rejects_helper_sha_drift(tmp_path: Path) -> None:
    """run_cmd 生成后 helper 即使被 safe sync 替换，也必须在 source 前失败。"""
    bash = _bash_executable()
    if bash is None:
        pytest.skip("Bash is required for run_cmd integration tests")
    sbatch = (SBATCH_ROOT / "f_supplement_96.sbatch").read_text(encoding="utf-8")
    run_cmd = sbatch.split("cat >\"${output_path}\" <<'EOF'\n", 1)[1].split(
        "\nEOF\n", 1
    )[0]
    fake_root = tmp_path / "fake-code"
    helper = fake_root / "sbatch" / "_f_supplement_stage.sh"
    helper.parent.mkdir(parents=True)
    helper.write_text("#!/usr/bin/env bash\n# drifted helper\n", encoding="utf-8")
    run_cmd_path = tmp_path / "run_cmd.sh"
    run_cmd_path.write_text(run_cmd + "\n", encoding="utf-8")

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"/usr/bin:{environment.get('PATH', '')}",
            "CODE_ROOT": _bash_path(fake_root),
            "ADALIGAND_RUN_ID": "supplement",
            "ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID": "formal",
            "ADALIGAND_F_SUPPLEMENT_IDS_FILE": "unused-ids",
            "ADALIGAND_F_SUPPLEMENT_IDS_SHA256": "0" * 64,
            "ADALIGAND_F_SUPPLEMENT_PLAN_FILE": "unused-plan",
            "ADALIGAND_F_SUPPLEMENT_PLAN_SHA256": "0" * 64,
            "ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID": "316116",
            "ADALIGAND_F_SUPPLEMENT_FORMAL_LOG": "unused-log",
            "ADALIGAND_EXTRA_KILL_PGID_FILE": "unused-pgid",
        }
    )
    result = subprocess.run(
        [str(bash), _bash_path(run_cmd_path)],
        env=environment,
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 70
    assert "supplement helper SHA-256 drift" in result.stdout


def test_supplement_runtime_files_are_frozen_to_lf_by_git_attributes() -> None:
    """源码库检查属性；无 ``.git`` 的服务器副本仍逐文件检查 LF。"""
    relative_paths = (
        "Data_Preprocessing/Ori_Data/code/f_supplement_guard.py",
        "Data_Preprocessing/Ori_Data/scripts/f_supplement_guard.py",
        "Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh",
        "Data_Preprocessing/Ori_Data/sbatch/_f_supplement_stage.sh",
        "Data_Preprocessing/Ori_Data/sbatch/f_supplement_96.sbatch",
        "Data_Preprocessing/Ori_Data/sbatch/resume_f_supplement_318350_accel_v2.sh",
    )
    repository_root = PROJECT_ROOT.parents[1]
    worktree_probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=repository_root,
        check=False,
        text=True,
        capture_output=True,
    )
    attributes = ""
    if worktree_probe.returncode == 0:
        attributes = subprocess.run(
            ["git", "check-attr", "text", "eol", "--", *relative_paths],
            cwd=repository_root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout
    for relative_path in relative_paths:
        if attributes:
            assert f"{relative_path}: text: set" in attributes
            assert f"{relative_path}: eol: lf" in attributes
        assert b"\r\n" not in (repository_root / relative_path).read_bytes()


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


def test_abc_source_resume_is_stage_aware_and_never_runs_b() -> None:
    """316114 恢复必须保留 pre-gate 证据，并用新 attempt 收敛 partial generic apply。"""
    script = (
        SBATCH_ROOT / "resume_abc_316114_source_v2.sh"
    ).read_text(encoding="utf-8")

    assert "scripts/b_download.py" not in script
    assert 'REPAIR="adaligand_ag_20260711T154658_csrc_v4"' in script
    assert 'POST="adaligand_ag_20260711T154658_csrc_v4_post_exact"' in script
    assert "scripts/c_descriptor_prefetch.py" in script
    assert "CCD:5GP" in script
    assert "descriptor_prefetch" in script
    descriptor_function = script[
        script.index("run_descriptor_prefetch()"):
        script.index("run_rebuild_audit_once()")
    ]
    assert 'if [[ -e "$summary" ]]' not in descriptor_function
    assert "delegated_full_rebuild_ready" in script
    assert "generic_attempt_${attempt}" in script
    assert "--require_all_exact" in script
    assert 'summary.get("counts") != {"exact": 2156}' in script
    assert "primary_key_migration" not in script  # 计数由冻结 rebuild summary 统一门禁

    final_c_start = script.rindex('"$PY" scripts/c_parse.py')
    final_c_end = script.index('"$PY" scripts/abc_release_gate.py', final_c_start)
    final_c = script[final_c_start:final_c_end]
    assert "--pdb_ids_file" not in final_c
    assert "--overwrite" not in final_c
    assert '--run_id "$FORMAL"' in final_c


def test_de_e_repair_is_filtered_then_refreshes_formal_status_without_d() -> None:
    """316115 恢复先隔离 18 个工程失败，再以正式 run id 无过滤复核 E。"""
    script = (SBATCH_ROOT / "resume_de_316115_e_repair_v1.sh").read_text(
        encoding="utf-8"
    )

    assert "scripts/d_atom_labels.py" not in script
    assert 'REPAIR="adaligand_ag_20260711T154658_eeng_v1"' in script
    assert "6f9bea3a9448f8f24940d3241520633890aefad88d737fad0580f47ff0b280be" in script
    assert "b03b7c72a00730f5fc0bb56b718f0f7f5a7313f11212fbc034fc74f4a6a6c7b0" in script
    assert "--n_jobs 2" in script
    assert "--timeout_seconds 21600" in script
    assert "--require_success" in script

    repair_start = script.index('"${PYTHON}" scripts/e_density.py')
    repair_end = script.index('"${PYTHON}" scripts/stage_release_gate.py', repair_start)
    repair_command = script[repair_start:repair_end]
    assert '--pdb_ids_file "${IDS_FILE}"' in repair_command
    assert '--run_id "${REPAIR}"' in repair_command

    formal_start = script.rindex('"${PYTHON}" scripts/e_density.py')
    formal_end = script.index('"${PYTHON}" scripts/stage_release_gate.py', formal_start)
    formal_command = script[formal_start:formal_end]
    assert "--pdb_ids_file" not in formal_command
    assert "--overwrite" not in formal_command
    assert '--run_id "${FORMAL}"' in formal_command


def test_de_e_resume_v2_waits_for_supplement_and_uses_run_exclusion() -> None:
    """316115 v2 只接受 316415 的受检补足结果，再无过滤刷新正式 E。"""
    script = (SBATCH_ROOT / "resume_de_316115_e_repair_v2.sh").read_text(
        encoding="utf-8"
    )

    assert "scripts/d_atom_labels.py" not in script
    assert 'SUPPLEMENT="adaligand_ag_20260711T154658_eeng_supp48_v2"' in script
    assert "e_repair_supp48_v2_release_316115" in script
    assert "formal_job=316115" in script
    assert "supplement_job=316415" in script
    assert "21c14b03565807d5d52f59561ee771c84dd0c0042f56794f801c1ae7bd838366" in script
    assert "b586cab20644c3cc8fb1f4e0eaa7eead4cff0d496a862c2313b5e0c1847257fe" in script
    assert "load_run_exclusions" in script
    assert 'set(records) != {"8ckb"}' in script
    assert "load_stage_statuses" in script
    assert "need_formal_e=1" in script
    assert "need_formal_e=0" in script
    assert 'if [[ "${need_formal_e}" -eq 1 ]]' in script
    assert "rerunning gate only" in script
    assert 'record.get("status") not in {"success", "skipped"}' in script
    assert '"gate_name": "e_supp48_release"' in script
    assert "supplement gate field mismatch" in script
    assert "assert " not in script
    assert '[[ ! -e "${DATA_ROOT}/density/8ckb/sim.npz" ]]' in script

    assert script.count('"${PYTHON}" scripts/e_density.py') == 1
    formal_start = script.index('"${PYTHON}" scripts/e_density.py')
    formal_end = script.index('"${PYTHON}" scripts/stage_release_gate.py', formal_start)
    formal_command = script[formal_start:formal_end]
    assert "--n_jobs 24" in formal_command
    assert "--timeout_seconds 21600" in formal_command
    assert "--pdb_ids_file" not in formal_command
    assert "--overwrite" not in formal_command
    assert '--run_id "${FORMAL}"' in formal_command
    assert "--stages stage_d,stage_e" in script
    assert "--gate_name de_release" in script


def test_de_e_resume_v3_consumes_cutoff_and_refreshes_formal_e_only() -> None:
    """316115 v3 接受 run-only cutoff 证据，不再伪装 316415 六样本成功。"""
    script = (SBATCH_ROOT / "resume_de_316115_e_repair_v3.sh").read_text(
        encoding="utf-8"
    )

    assert "scripts/d_atom_labels.py" not in script
    assert "e_repair_supp48_v2_release_316115" not in script
    assert "e_supp48_release" not in script
    assert "e_long_tail_cutoff_release_316115" in script
    assert "FAILED_expected_user_cutoff" in script
    assert "06:04:02" in script
    assert '"remote_tests": "207_passed"' in script
    for digest in (
        "40e7c949df528b81e1c4a8ee8bbd60daec5ec4d06089037e64958f08fd5458a8",
        "0f20f20cae3b9958cfe3fd3085233782b2e2e5533144cec704fa22dec2d97397",
        "b586cab20644c3cc8fb1f4e0eaa7eead4cff0d496a862c2313b5e0c1847257fe",
        "380844d0b908b08707fada689f64b2fa4cc519f4771df92dec8b5bf0b2cd325f",
        "f4a26a9359519e4b94b9f28ecdb21645929c018a014729feadb44b29eadf4761",
    ):
        assert digest in script
    assert 'final_ids = {"8ckb", "8glv", "9e5c", "9fqr"}' in script
    assert 'added_ids = {"8glv", "9e5c", "9fqr"}' in script
    assert '("8j07", "9dp7", "9qwt")' in script
    assert "standard_chimera_molmap_on_canonical_grid" in script
    assert "standard_chimera_timeout_seconds" in script
    assert "supplement_elapsed_at_posttermination" in script
    assert "scratch_molmap_evidence_at_cutoff" in script
    assert "resume_v3_sha256" in script
    assert "run_cmd_sha256" in script

    assert "StageStatus.UNKNOWN_FAILED.value" in script
    assert "provenance_current = False" in script
    assert 'print("run")' in script
    assert 'print("skip")' in script
    assert "formal Stage E coverage drift" in script
    assert "duplicate/empty formal Stage E status" in script
    assert "run_policy_excluded leaked outside the manifest" in script
    assert 'VALIDATE_ONLY:-0' in script
    assert "validation-only decision=" in script
    assert "assert " not in script

    assert script.count('"${PYTHON}" scripts/e_density.py') == 1
    formal_start = script.index('"${PYTHON}" scripts/e_density.py')
    formal_end = script.index('"${PYTHON}" scripts/stage_release_gate.py', formal_start)
    formal_command = script[formal_start:formal_end]
    assert "--n_jobs 24" in formal_command
    assert "--timeout_seconds 21600" in formal_command
    assert "--pdb_ids_file" not in formal_command
    assert "--overwrite" not in formal_command
    assert '--run_id "${FORMAL}"' in formal_command
    assert "--stages stage_d,stage_e" in script
    assert "--gate_name de_release" in script


def test_f_resume_records_only_6kgx_as_run_scoped_stage_f_timeout() -> None:
    """316116 恢复入口只能追加已取证的 6kgx F 超时，并继续 F12 全量复核。"""
    script = (SBATCH_ROOT / "resume_f_316116_long_tail_v1.sh").read_text(
        encoding="utf-8"
    )

    assert 'FORMAL_JOB="316116"' in script
    assert "stage_f_long_tail_cutoff_20260714T2213" in script
    assert "exclusions.stage_f.jsonl" in script
    assert "380844d0b908b08707fada689f64b2fa4cc519f4771df92dec8b5bf0b2cd325f" in script
    assert '"pdb_id": "6kgx"' in script
    assert '"stages": ["stage_f"]' in script
    assert "user_authorized_stage_f_engineering_long_tail_timeout" in script
    assert '"downstream_policy": "exclude_from_training_and_inference"' in script
    assert 'set(stage_e) != set(base_records)' in script
    assert 'set(stage_f) != set(final_records)' in script
    assert "shared Stage E/F exclusion manifest drifted after Stage E release" in script
    assert "quality.project_occurrence_qscores/_row_matches_component" in script
    assert '"occurrence_count": 1588' in script
    assert '"selected_model_atom_count": 1011574' in script
    assert "run_cmd_exit_137" in script
    assert "VALIDATE_ONLY" in script
    assert "APPLY_CUTOFF" in script
    assert 'transition_mode="apply"' in script
    assert 'transition_mode="validate"' in script
    assert "read-only validation succeeded" in script
    assert "remote_test_log_sha256" in script
    assert '"remote_test_exit_code"' in script
    assert "unique clean pass summary" in script
    assert "resume_script_sha256" in script
    assert "run_cmd_sha256" in script
    assert "assert " not in script

    assert script.count('"${PYTHON}" scripts/f_quality.py') == 1
    formal_start = script.index('"${PYTHON}" scripts/f_quality.py')
    formal_end = script.index('"${PYTHON}" scripts/stage_release_gate.py', formal_start)
    formal_command = script[formal_start:formal_end]
    assert "--n_jobs 12" in formal_command
    assert "--overwrite" not in formal_command
    assert '--run_id "${FORMAL}"' in formal_command
    assert "--stages stage_f" in script
    assert "--gate_name f_release" in script
