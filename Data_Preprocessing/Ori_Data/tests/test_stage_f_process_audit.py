"""Stage F scratch 回收前跨节点进程探针的回归测试。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from io_utils import sha256_file
import stage_f_process_audit as process_audit
import stage_f_scratch_recovery as recovery


PROCESS_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stage_f_process_audit.py"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["/usr/bin/python3", "-"], True),
        (["python3.10", "-u", "-"], True),
        (["python"], True),
        (["python", "-c", "print(1)", "-"], False),
        (["python", "-m", "worker"], False),
        (["python", "worker.py", "-"], False),
        (["bash", "-"], False),
    ],
)
def test_is_opaque_stdin_python(argv: list[str], expected: bool) -> None:
    """只把真正从 stdin 读取 Python 正文的命令计为不透明进程。"""
    assert process_audit.is_opaque_stdin_python(argv) is expected


def _write_proc_process(
    proc_root: Path,
    pid: int,
    *,
    ppid: int,
    uid: int,
    argv: list[str],
    start_time_ticks: int | None = None,
) -> None:
    """写一个足以供扫描器读取的最小 fake ``/proc/<pid>``。"""
    proc_dir = proc_root / str(pid)
    proc_dir.mkdir(parents=True)
    stat_tail = ["S", str(ppid), *(["0"] * 17), str(start_time_ticks or pid * 100)]
    (proc_dir / "stat").write_text(
        f"{pid} (worker) {' '.join(stat_tail)}\n",
        encoding="utf-8",
    )
    (proc_dir / "status").write_text(
        f"Name:\tworker\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n",
        encoding="utf-8",
    )
    (proc_dir / "cmdline").write_bytes(b"\0".join(item.encode() for item in argv) + b"\0")


def test_scan_owned_processes_classifies_and_excludes_ancestors(tmp_path: Path) -> None:
    """同 UID 进程按三类统计，自身、祖先和其他 UID 必须排除。"""
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    uid = 1000
    _write_proc_process(proc_root, 100, ppid=90, uid=uid, argv=["python", "-"])
    _write_proc_process(
        proc_root,
        90,
        ppid=1,
        uid=uid,
        argv=["python", "stage_f_scratch_recovery.py"],
    )
    _write_proc_process(proc_root, 110, ppid=1, uid=2000, argv=["python", "f_quality.py"])
    _write_proc_process(proc_root, 200, ppid=1, uid=uid, argv=["/usr/bin/python3", "-"])
    _write_proc_process(proc_root, 201, ppid=1, uid=uid, argv=["python", "-c", "print(1)"])
    _write_proc_process(proc_root, 202, ppid=1, uid=uid, argv=["python"])
    _write_proc_process(proc_root, 203, ppid=1, uid=uid, argv=["python", "worker.py", "-"])
    _write_proc_process(proc_root, 204, ppid=1, uid=uid, argv=["python3", "-u", "-"])
    _write_proc_process(proc_root, 210, ppid=1, uid=uid, argv=["python", "f_quality.py"])
    _write_proc_process(proc_root, 211, ppid=1, uid=uid, argv=["/opt/chimera"])
    _write_proc_process(proc_root, 212, ppid=1, uid=uid, argv=["python", "mapq_cmd.py"])
    _write_proc_process(
        proc_root,
        220,
        ppid=1,
        uid=uid,
        argv=["python", "stage_f_scratch_recovery.py", "apply"],
    )
    _write_proc_process(
        proc_root,
        221,
        ppid=1,
        uid=uid,
        argv=["python", "-c", "_cleanup_quality_attempt_transients()"],
    )
    _write_proc_process(
        proc_root,
        222,
        ppid=1,
        uid=uid,
        argv=["python", "stage_f_process_audit.py", "capture"],
    )

    payload = process_audit.scan_owned_processes(
        proc_root=proc_root,
        uid=uid,
        self_pid=100,
        node="test-node",
    )

    assert payload["node"] == "test-node"
    assert payload["uid"] == uid
    assert {row["pid"] for row in payload["stage_f_processes"]} == {210, 211, 212}
    assert {row["pid"] for row in payload["inventory_or_cleanup_processes"]} == {
        220,
        221,
        222,
    }
    assert {row["pid"] for row in payload["opaque_stdin_python_processes"]} == {
        200,
        202,
        204,
    }
    assert payload["scan_error_count"] == 0
    assert payload["scan_errors"] == []
    all_reported = {
        row["pid"]
        for name in (
            "stage_f_processes",
            "inventory_or_cleanup_processes",
            "opaque_stdin_python_processes",
        )
        for row in payload[name]
    }
    assert not {90, 100, 110, 201, 203}.intersection(all_reported)


def _zero_probe(node: str, identity: dict[str, str]) -> str:
    """返回一个真实 schema 的零进程 probe stdout。"""
    return (
        json.dumps(
            {
                "schema_version": process_audit.PROCESS_PROBE_SCHEMA_VERSION,
                "probe_contract": process_audit.PROCESS_PROBE_CONTRACT,
                "node": node,
                "uid": os.getuid() if hasattr(os, "getuid") else 1000,
                "active_stage_f_processes": 0,
                "active_inventory_or_cleanup_processes": 0,
                "active_opaque_stdin_python_processes": 0,
                "scan_error_count": 0,
                "stage_f_processes": [],
                "inventory_or_cleanup_processes": [],
                "opaque_stdin_python_processes": [],
                "scan_errors": [],
                **identity,
            },
            sort_keys=True,
        )
        + "\n"
    )


def _probe_with_opaque(
    node: str,
    identity: dict[str, str],
    rows: list[dict[str, object]],
) -> str:
    """返回保留原始 opaque 行的真实 probe stdout。"""
    payload = json.loads(_zero_probe(node, identity))
    payload["active_opaque_stdin_python_processes"] = len(rows)
    payload["opaque_stdin_python_processes"] = rows
    return json.dumps(payload, sort_keys=True) + "\n"


def test_capture_json_round_trip_is_accepted_by_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """生产 capture 的 JSON 正文必须能被 recovery validator 原样接受。"""
    identity = process_audit.implementation_identity(PROCESS_SCRIPT)
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, timeout_seconds: float = 120.0) -> tuple[int, str, str]:
        del timeout_seconds
        calls.append(argv)
        if argv[:2] == ["bash", "-lc"]:
            return 0, "scheduler-ok\n", ""
        node = "controller"
        for argument in argv:
            if argument.startswith("--nodelist="):
                node = argument.split("=", 1)[1]
        return 0, _zero_probe(node, identity), ""

    monkeypatch.setattr(process_audit, "_run_text", fake_run)
    monkeypatch.setattr(process_audit.socket, "gethostname", lambda: "controller")
    output = tmp_path / "process_audit.json"
    audit = process_audit.capture_process_audit(
        output,
        jobs=[(101, "node-101"), (102, "node-102")],
        script_path=PROCESS_SCRIPT,
        lock_root=tmp_path / "locks",
        expected_controller_node="controller",
    )

    assert audit["status"] == "success"
    assert calls[-1][-2:] == [str(PROCESS_SCRIPT.resolve()), "probe"]
    validated = recovery._validate_process_audit(output, sha256_file(output), [101, 102])
    assert validated["probe_module_sha256"] == identity["probe_module_sha256"]
    assert validated["controller_check"]["probe_output"].startswith("{")


def test_exact_controller_opaque_exception_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一次性 PID 指纹可放行同一 controller 进程，但原始 opaque 行必须保留。"""
    identity = process_audit.implementation_identity(PROCESS_SCRIPT)
    argv = ["python3", "-"]
    row = {
        "pid": 54412,
        "ppid": 53972,
        "start_time_ticks": 123456,
        "argv": argv,
        "argv_sha256": process_audit.process_argv_sha256(argv),
        "command": "python3 -",
    }
    spec = {
        "node": "master",
        "pid": row["pid"],
        "ppid": row["ppid"],
        "start_time_ticks": row["start_time_ticks"],
        "argv_sha256": row["argv_sha256"],
    }

    def fake_run(argv_: list[str], *, timeout_seconds: float = 120.0) -> tuple[int, str, str]:
        del timeout_seconds
        if argv_[:2] == ["bash", "-lc"]:
            return 0, "scheduler-ok\n", ""
        node = "master"
        for argument in argv_:
            if argument.startswith("--nodelist="):
                node = argument.split("=", 1)[1]
        stdout = _probe_with_opaque(node, identity, [row]) if node == "master" else _zero_probe(node, identity)
        return 0, stdout, ""

    monkeypatch.setattr(process_audit, "_run_text", fake_run)
    monkeypatch.setattr(process_audit.socket, "gethostname", lambda: "master")
    output = tmp_path / "authorized-opaque.json"
    audit = process_audit.capture_process_audit(
        output,
        jobs=[(101, "cnode01")],
        script_path=PROCESS_SCRIPT,
        lock_root=tmp_path / "locks",
        expected_controller_node="master",
        authorized_controller_opaque_specs=[spec],
    )

    assert audit["status"] == "success"
    assert audit["observed_opaque_stdin_python_processes"] == 1
    assert audit["active_opaque_stdin_python_processes"] == 0
    assert audit["authorized_controller_opaque_processes"] == [row]
    recovery._validate_process_audit(output, sha256_file(output), [101])


@pytest.mark.parametrize("field", ["pid", "ppid", "start_time_ticks", "argv_sha256"])
def test_controller_opaque_exception_identity_drift_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    """PID、父进程、启动时刻或 argv 任一漂移都不能借用旧授权。"""
    identity = process_audit.implementation_identity(PROCESS_SCRIPT)
    argv = ["python3", "-"]
    row = {
        "pid": 54412,
        "ppid": 53972,
        "start_time_ticks": 123456,
        "argv": argv,
        "argv_sha256": process_audit.process_argv_sha256(argv),
        "command": "python3 -",
    }
    spec = {
        "node": "master",
        "pid": row["pid"],
        "ppid": row["ppid"],
        "start_time_ticks": row["start_time_ticks"],
        "argv_sha256": row["argv_sha256"],
    }
    spec[field] = "f" * 64 if field == "argv_sha256" else int(spec[field]) + 1

    def fake_run(argv_: list[str], *, timeout_seconds: float = 120.0) -> tuple[int, str, str]:
        del timeout_seconds
        if argv_[:2] == ["bash", "-lc"]:
            return 0, "scheduler-ok\n", ""
        node = "master" if not any(item.startswith("--nodelist=") for item in argv_) else "cnode01"
        stdout = _probe_with_opaque(node, identity, [row]) if node == "master" else _zero_probe(node, identity)
        return 0, stdout, ""

    monkeypatch.setattr(process_audit, "_run_text", fake_run)
    monkeypatch.setattr(process_audit.socket, "gethostname", lambda: "master")
    audit = process_audit.capture_process_audit(
        tmp_path / f"blocked-{field}.json",
        jobs=[(101, "cnode01")],
        script_path=PROCESS_SCRIPT,
        lock_root=tmp_path / "locks",
        expected_controller_node="master",
        authorized_controller_opaque_specs=[spec],
    )
    assert audit["status"] == "blocked"
    assert audit["active_opaque_stdin_python_processes"] == 1


def test_exact_exception_does_not_hide_a_second_opaque_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """一个精确例外只能扣除一行，另一个 opaque Python 仍须阻断。"""
    identity = process_audit.implementation_identity(PROCESS_SCRIPT)
    argv = ["python3", "-"]
    digest = process_audit.process_argv_sha256(argv)
    authorized = {
        "pid": 54412,
        "ppid": 53972,
        "start_time_ticks": 123456,
        "argv": argv,
        "argv_sha256": digest,
        "command": "python3 -",
    }
    other = {**authorized, "pid": 60000, "start_time_ticks": 654321}
    spec = {
        "node": "master",
        "pid": 54412,
        "ppid": 53972,
        "start_time_ticks": 123456,
        "argv_sha256": digest,
    }

    def fake_run(argv_: list[str], *, timeout_seconds: float = 120.0) -> tuple[int, str, str]:
        del timeout_seconds
        if argv_[:2] == ["bash", "-lc"]:
            return 0, "scheduler-ok\n", ""
        is_allocation = any(item.startswith("--nodelist=") for item in argv_)
        return (
            0,
            _zero_probe("cnode01", identity)
            if is_allocation
            else _probe_with_opaque("master", identity, [authorized, other]),
            "",
        )

    monkeypatch.setattr(process_audit, "_run_text", fake_run)
    monkeypatch.setattr(process_audit.socket, "gethostname", lambda: "master")
    audit = process_audit.capture_process_audit(
        tmp_path / "second-opaque.json",
        jobs=[(101, "cnode01")],
        script_path=PROCESS_SCRIPT,
        lock_root=tmp_path / "locks",
        expected_controller_node="master",
        authorized_controller_opaque_specs=[spec],
    )
    assert audit["status"] == "blocked"
    assert audit["authorized_controller_opaque_processes"] == [authorized]
    assert audit["blocking_controller_opaque_processes"] == [other]


def test_only_one_controller_opaque_exception_is_allowed() -> None:
    """接口本身不得演变成可逐条放行所有 opaque 进程的 allowlist。"""
    digest = process_audit.process_argv_sha256(["python3", "-"])
    specs = [
        {
            "node": "master",
            "pid": pid,
            "ppid": 1,
            "start_time_ticks": pid * 10,
            "argv_sha256": digest,
        }
        for pid in (54412, 60000)
    ]
    with pytest.raises(ValueError, match="at most one"):
        process_audit.normalize_opaque_process_specs(specs)


@pytest.mark.parametrize("tamper", ["digest", "command", "nonopaque", "duplicate"])
def test_raw_opaque_rows_are_recomputed_before_authorization(tamper: str) -> None:
    """raw 行不能靠自报摘要、命令或重复身份冒充精确例外。"""
    argv = ["python3", "-"]
    row = {
        "pid": 54412,
        "ppid": 53972,
        "start_time_ticks": 123456,
        "argv": argv,
        "argv_sha256": process_audit.process_argv_sha256(argv),
        "command": "python3 -",
    }
    rows = [row]
    if tamper == "digest":
        row["argv_sha256"] = "f" * 64
    elif tamper == "command":
        row["command"] = "python3 worker.py"
    elif tamper == "nonopaque":
        row["argv"] = ["python3", "-c", "print(1)"]
        row["argv_sha256"] = process_audit.process_argv_sha256(row["argv"])
        row["command"] = "python3 -c print(1)"
    else:
        rows.append(dict(row))
    with pytest.raises(ValueError):
        process_audit.validate_opaque_process_rows(rows)


def test_capture_requires_the_expected_nonallocation_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """误在计算节点启动 capture 时，必须在任何 srun/probe 前阻断。"""
    monkeypatch.setattr(process_audit.socket, "gethostname", lambda: "cnode04")
    with pytest.raises(RuntimeError, match="expected controller"):
        process_audit.capture_process_audit(
            tmp_path / "wrong-controller.json",
            jobs=[(101, "cnode01")],
            script_path=PROCESS_SCRIPT,
            lock_root=tmp_path / "locks",
            expected_controller_node="master",
        )
    with pytest.raises(RuntimeError, match="must not also be an allocation"):
        process_audit.capture_process_audit(
            tmp_path / "overlap-controller.json",
            jobs=[(101, "cnode04")],
            script_path=PROCESS_SCRIPT,
            lock_root=tmp_path / "locks",
            expected_controller_node="cnode04",
        )


def test_capture_and_validator_agree_that_probe_stderr_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """capture 不得自报 success 后再由 validator 因同一 stderr 拒绝。"""
    identity = process_audit.implementation_identity(PROCESS_SCRIPT)

    def fake_run(argv: list[str], *, timeout_seconds: float = 120.0) -> tuple[int, str, str]:
        del timeout_seconds
        if argv[:2] == ["bash", "-lc"]:
            return 0, "scheduler-ok\n", ""
        node = "master"
        for argument in argv:
            if argument.startswith("--nodelist="):
                node = argument.split("=", 1)[1]
        stderr = "srun warning\n" if node == "cnode01" else ""
        return 0, _zero_probe(node, identity), stderr

    monkeypatch.setattr(process_audit, "_run_text", fake_run)
    monkeypatch.setattr(process_audit.socket, "gethostname", lambda: "master")
    output = tmp_path / "stderr-blocked.json"
    audit = process_audit.capture_process_audit(
        output,
        jobs=[(101, "cnode01")],
        script_path=PROCESS_SCRIPT,
        lock_root=tmp_path / "locks",
        expected_controller_node="master",
    )
    assert audit["status"] == "blocked"
    with pytest.raises(RuntimeError, match="does not prove"):
        recovery._validate_process_audit(output, sha256_file(output), [101])
