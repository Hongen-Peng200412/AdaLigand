"""Stage F 硬中断 scratch 清单与精确回收工具的回归测试。"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from io_utils import sha256_file
import stage_f_scratch_recovery as recovery
from stage_f_process_audit import (
    PROCESS_AUDIT_SCHEMA_VERSION,
    PROCESS_PROBE_CONTRACT,
    PROCESS_PROBE_SCHEMA_VERSION,
    implementation_identity,
)
from stage_f_scratch_recovery import apply_scratch_cleanup, build_scratch_audit


RUN_A = "formal_run"
RUN_B = "supplement_run"
JOB_IDS = [101, 102]
PROCESS_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "stage_f_process_audit.py"


def _write_public_trio(root: Path, pdb_id: str) -> dict[str, str]:
    """写一组最小正式三件套，并返回逐文件内容哈希。"""
    paths = [
        root / "quality" / f"{pdb_id}.jsonl",
        root / "quality" / f"{pdb_id}.provenance.json",
        root / "quality_atoms" / f"{pdb_id}.npz",
    ]
    for index, path in enumerate(paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"{pdb_id}-{index}".encode("ascii"))
    return {path.relative_to(root).as_posix(): sha256_file(path) for path in paths}


def _write_locks(lock_root: Path) -> None:
    """建立两个 job 的 after+try 安全停点。"""
    lock_root.mkdir(parents=True, exist_ok=True)
    for job_id in JOB_IDS:
        (lock_root / f"after_lock_{job_id}").write_text("after", encoding="utf-8")
        (lock_root / f"try_lock_{job_id}").write_text("try", encoding="utf-8")


def _write_process_audit(report_dir: Path) -> tuple[Path, str]:
    """写登录节点与两个 allocation 的零 writer/零 recovery 进程证据。"""
    path = report_dir / "process_audit.json"
    scheduler_snapshot = "316116|RUNNING|node-101\n318350|RUNNING|node-102\n"
    identity = implementation_identity(PROCESS_SCRIPT)
    captured_at = datetime.now(timezone.utc).isoformat()

    def process_check(
        node: str,
        *,
        scope: str,
        job_id: int | None = None,
    ) -> dict[str, object]:
        """构造与生产 probe JSON 完全同形的零进程节点证据。"""
        payload = {
            "schema_version": PROCESS_PROBE_SCHEMA_VERSION,
            "probe_contract": PROCESS_PROBE_CONTRACT,
            "node": node,
            "uid": 1000,
            "active_stage_f_processes": 0,
            "active_inventory_or_cleanup_processes": 0,
            "active_opaque_stdin_python_processes": 0,
            "scan_error_count": 0,
            "stage_f_processes": [],
            "inventory_or_cleanup_processes": [],
            "opaque_stdin_python_processes": [],
            "scan_errors": [],
            **identity,
        }
        if job_id is None:
            argv = [sys.executable, str(PROCESS_SCRIPT), "probe"]
        else:
            argv = [
                "srun",
                "--overlap",
                f"--jobid={job_id}",
                "--nodes=1",
                "--ntasks=1",
                "--cpus-per-task=1",
                f"--nodelist={node}",
                sys.executable,
                str(PROCESS_SCRIPT),
                "probe",
            ]
        command = shlex.join(argv)
        output = json.dumps(payload, sort_keys=True) + "\n"
        return {
            "scope": scope,
            "job_id": job_id,
            "started_at": captured_at,
            "completed_at": captured_at,
            "node": node,
            "reported_node": node,
            "active_stage_f_processes": 0,
            "active_inventory_or_cleanup_processes": 0,
            "active_opaque_stdin_python_processes": 0,
            "scan_error_count": 0,
            **identity,
            "probe_exit_code": 0,
            "probe_argv": argv,
            "probe_command": command,
            "probe_command_sha256": hashlib.sha256(command.encode()).hexdigest(),
            "probe_output": output,
            "probe_output_sha256": hashlib.sha256(output.encode()).hexdigest(),
            "probe_stderr": "",
            "probe_stderr_sha256": hashlib.sha256(b"").hexdigest(),
        }

    job_checks = {}
    for job_id in JOB_IDS:
        node = f"node-{job_id}"
        job_checks[str(job_id)] = process_check(
            node,
            scope="allocation",
            job_id=job_id,
        )
    controller_check = process_check("controller", scope="controller")
    path.write_text(
        json.dumps(
            {
                "schema_version": PROCESS_AUDIT_SCHEMA_VERSION,
                "status": "success",
                "capture_started_at": captured_at,
                "captured_at": captured_at,
                "job_ids": JOB_IDS,
                "job_nodes": {str(job_id): f"node-{job_id}" for job_id in JOB_IDS},
                "controller_node": "controller",
                **identity,
                "active_stage_f_processes": 0,
                "active_inventory_or_cleanup_processes": 0,
                "active_opaque_stdin_python_processes": 0,
                "scan_error_count": 0,
                "scheduler_exit_code": 0,
                "scheduler_snapshot": scheduler_snapshot,
                "scheduler_snapshot_sha256": hashlib.sha256(scheduler_snapshot.encode()).hexdigest(),
                "job_checks": job_checks,
                "controller_check": controller_check,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path, sha256_file(path)


def _write_inventory(root: Path, report_dir: Path) -> None:
    """模拟服务器 `find -printf` 产出的原子 raw/attempt inventory。"""
    report_dir.mkdir(parents=True, exist_ok=True)
    raw_lines: list[str] = []
    attempt_lines: list[str] = []
    for run_id in (RUN_A, RUN_B):
        stage_root = root / "scratch" / run_id / "stage_f"
        for pdb_dir in sorted(path for path in stage_root.iterdir() if path.is_dir()):
            for attempt_dir in sorted(path for path in pdb_dir.iterdir() if path.is_dir()):
                attempt_lines.append(f"{run_id}\t{pdb_dir.name}/{attempt_dir.name}\n")
        for path in sorted(stage_root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(stage_root).as_posix()
            if not 3 <= len(Path(relative).parts) <= 6:
                continue
            info = path.stat()
            blocks = int(getattr(info, "st_blocks", (info.st_size + 511) // 512))
            raw_lines.append(
                f"{run_id}\t{relative}\t{info.st_size}\t{blocks}\t{info.st_mtime_ns / 1e9:.9f}\n"
            )
    raw_path = report_dir / "raw_inventory.tsv"
    attempts_path = report_dir / "attempts.tsv"
    raw_path.write_text("".join(raw_lines), encoding="utf-8")
    attempts_path.write_text("".join(attempt_lines), encoding="utf-8")
    (report_dir / "inventory.sha256").write_text(
        f"{sha256_file(raw_path)}  {raw_path}\n{sha256_file(attempts_path)}  {attempts_path}\n",
        encoding="utf-8",
    )
    (report_dir / "inventory.done.json").write_text(
        json.dumps(
            {
                "status": "success",
                "completed_at": "2026-07-16T00:00:00+08:00",
                "raw_lines": len(raw_lines),
                "attempts": len(attempt_lines),
            }
        ),
        encoding="utf-8",
    )


def _build_fixture(tmp_path: Path) -> dict[str, object]:
    """构造两个受检 run、一个越界 run、残留大文件和保留日志。"""
    root = tmp_path / "root"
    report_dir = root / "reports" / "scratch_recovery"
    lock_root = tmp_path / "locks"
    formal_attempt = root / "scratch" / RUN_A / "stage_f" / "1abc" / "attempt-a"
    clean_attempt = root / "scratch" / RUN_A / "stage_f" / "2abc" / "attempt-b"
    supplement_attempt = root / "scratch" / RUN_B / "stage_f" / "3abc" / "attempt-c"
    outside_attempt = root / "scratch" / "outside_run" / "stage_f" / "9abc" / "attempt-z"
    for path in (formal_attempt, clean_attempt, supplement_attempt, outside_attempt):
        path.mkdir(parents=True)
    (formal_attempt / "nested").mkdir()
    (formal_attempt / "nested" / "canonical.mrc").write_bytes(b"mrc" * 200)
    (formal_attempt / "full_model.cif").write_bytes(b"cif" * 100)
    (formal_attempt / "chimera.stdout.log").write_text("keep formal", encoding="utf-8")
    (clean_attempt / "mapq.stderr.log").write_text("keep clean", encoding="utf-8")
    (supplement_attempt / "native.map.tmp.123").write_bytes(b"map" * 150)
    (supplement_attempt / "All.txt").write_text("keep supplement", encoding="utf-8")
    (outside_attempt / "outside.mrc").write_bytes(b"outside")
    trio_hashes = {}
    trio_hashes.update(_write_public_trio(root, "1abc"))
    trio_hashes.update(_write_public_trio(root, "2abc"))
    _write_locks(lock_root)
    _write_inventory(root, report_dir)
    process_audit, process_audit_sha256 = _write_process_audit(report_dir)
    return {
        "root": root,
        "report_dir": report_dir,
        "lock_root": lock_root,
        "formal_attempt": formal_attempt,
        "clean_attempt": clean_attempt,
        "supplement_attempt": supplement_attempt,
        "outside_attempt": outside_attempt,
        "trio_hashes": trio_hashes,
        "process_audit": process_audit,
        "process_audit_sha256": process_audit_sha256,
    }


def _audit(fixture: dict[str, object]) -> dict:
    """用统一参数执行一次无删除 audit。"""
    return build_scratch_audit(
        fixture["root"],
        fixture["report_dir"],
        run_ids={RUN_A, RUN_B},
        lock_root=fixture["lock_root"],
        job_ids=JOB_IDS,
        process_audit_path=fixture["process_audit"],
        expected_process_audit_sha256=fixture["process_audit_sha256"],
    )


def _apply(fixture: dict[str, object], audit_bundle_sha256: str) -> dict:
    """用统一参数执行一次受检 apply。"""
    return apply_scratch_cleanup(
        fixture["root"],
        fixture["report_dir"],
        run_ids={RUN_A, RUN_B},
        lock_root=fixture["lock_root"],
        job_ids=JOB_IDS,
        process_audit_path=fixture["process_audit"],
        expected_process_audit_sha256=fixture["process_audit_sha256"],
        expected_audit_bundle_sha256=audit_bundle_sha256,
    )


def test_audit_then_apply_is_exact_and_preserves_evidence(tmp_path: Path) -> None:
    """audit 不删除；apply 只清 manifest 大文件并逐字节保留日志和三件套。"""
    fixture = _build_fixture(tmp_path)
    summary = _audit(fixture)
    formal_attempt = fixture["formal_attempt"]
    supplement_attempt = fixture["supplement_attempt"]
    assert summary["status"] == "audit_complete_no_delete"
    assert summary["current_active_attempts"] == 0
    assert summary["delete_files"] == 3
    assert (formal_attempt / "nested" / "canonical.mrc").exists()
    assert (supplement_attempt / "native.map.tmp.123").exists()

    bundle_path = fixture["report_dir"] / "audit_bundle.json"
    applied = _apply(fixture, sha256_file(bundle_path))
    assert applied["status"] == "success"
    assert applied["removed_files"] == 3
    assert not (formal_attempt / "nested" / "canonical.mrc").exists()
    assert not (formal_attempt / "full_model.cif").exists()
    assert not (supplement_attempt / "native.map.tmp.123").exists()
    assert (formal_attempt / "chimera.stdout.log").read_text(encoding="utf-8") == "keep formal"
    assert (supplement_attempt / "All.txt").read_text(encoding="utf-8") == "keep supplement"
    assert (fixture["outside_attempt"] / "outside.mrc").exists()
    for relative, digest in fixture["trio_hashes"].items():
        assert sha256_file(fixture["root"] / relative) == digest


def test_apply_refuses_new_transient_after_audit(tmp_path: Path) -> None:
    """before manifest 后出现新的 MRC 时，整批 preflight 阻断且旧文件不删。"""
    fixture = _build_fixture(tmp_path)
    _audit(fixture)
    new_path = fixture["formal_attempt"] / "late.map"
    new_path.write_bytes(b"late")
    bundle_path = fixture["report_dir"] / "audit_bundle.json"
    with pytest.raises(RuntimeError, match="affected delete set drift"):
        _apply(fixture, sha256_file(bundle_path))
    assert new_path.exists()
    assert (fixture["formal_attempt"] / "full_model.cif").exists()
    assert (fixture["report_dir"] / "apply.started.json").exists()
    assert (fixture["report_dir"] / "apply.failed.json").exists()
    assert not (fixture["report_dir"] / "apply_progress.jsonl").exists()


def test_audit_requires_exact_try_lock_and_process_evidence(tmp_path: Path) -> None:
    """缺 try-lock 或进程证据哈希漂移时，audit 在扫描前失败。"""
    fixture = _build_fixture(tmp_path)
    (fixture["lock_root"] / f"try_lock_{JOB_IDS[0]}").unlink()
    with pytest.raises(RuntimeError, match="missing regular try lock"):
        _audit(fixture)
    (fixture["lock_root"] / f"try_lock_{JOB_IDS[0]}").write_text("try", encoding="utf-8")
    fixture["process_audit"].write_text("{}", encoding="utf-8")
    with pytest.raises(RuntimeError, match="process audit SHA-256 mismatch"):
        _audit(fixture)


def test_process_audit_recomputes_embedded_command_and_output_hashes(tmp_path: Path) -> None:
    """64 位占位文本不能冒充真实 scheduler/probe 正文哈希。"""
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture["process_audit"].read_text(encoding="utf-8"))
    payload["scheduler_snapshot_sha256"] = "a" * 64
    payload["job_checks"][str(JOB_IDS[0])]["probe_output_sha256"] = "b" * 64
    fixture["process_audit"].write_text(json.dumps(payload), encoding="utf-8")
    fixture["process_audit_sha256"] = sha256_file(fixture["process_audit"])
    with pytest.raises(RuntimeError, match="process audit does not prove"):
        _audit(fixture)


def test_process_audit_rejects_controller_opaque_stdin_python(tmp_path: Path) -> None:
    """登录节点遗留的 ``python -`` 即使没有脚本 token，也必须阻断 audit。"""
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture["process_audit"].read_text(encoding="utf-8"))
    check = payload["controller_check"]
    check["active_opaque_stdin_python_processes"] = 1
    probe = json.loads(check["probe_output"])
    probe["active_opaque_stdin_python_processes"] = 1
    probe["opaque_stdin_python_processes"] = [
        {"pid": 52523, "ppid": 52118, "argv": ["python", "-"], "command": "python -"}
    ]
    check["probe_output"] = json.dumps(probe, sort_keys=True) + "\n"
    check["probe_output_sha256"] = hashlib.sha256(check["probe_output"].encode()).hexdigest()
    fixture["process_audit"].write_text(json.dumps(payload), encoding="utf-8")
    fixture["process_audit_sha256"] = sha256_file(fixture["process_audit"])
    with pytest.raises(RuntimeError, match="invalid process audit check for controller"):
        _audit(fixture)


def test_process_audit_rejects_legacy_schema_without_controller_check(tmp_path: Path) -> None:
    """旧 schema 只探测 compute 节点，不能继续冒充完整停写证据。"""
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture["process_audit"].read_text(encoding="utf-8"))
    payload["schema_version"] = 1
    payload.pop("controller_check")
    payload.pop("active_opaque_stdin_python_processes")
    fixture["process_audit"].write_text(json.dumps(payload), encoding="utf-8")
    fixture["process_audit_sha256"] = sha256_file(fixture["process_audit"])
    with pytest.raises(RuntimeError, match="process audit does not prove"):
        _audit(fixture)


@pytest.mark.parametrize(
    "tamper",
    ["raw_node", "raw_count", "raw_identity", "reported_node", "scope", "stderr"],
)
def test_process_audit_rejects_inner_probe_tamper(tmp_path: Path, tamper: str) -> None:
    """即使重算外层哈希，raw JSON、节点、身份和 stderr 漂移仍必须阻断。"""
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture["process_audit"].read_text(encoding="utf-8"))
    check = payload["controller_check"]
    probe = json.loads(check["probe_output"])
    if tamper == "raw_node":
        probe["node"] = "other-controller"
    elif tamper == "raw_count":
        probe["active_stage_f_processes"] = 1
        probe["stage_f_processes"] = [{"pid": 1}]
    elif tamper == "raw_identity":
        probe["probe_module_sha256"] = "f" * 64
    elif tamper == "reported_node":
        check["reported_node"] = "other-controller"
    elif tamper == "scope":
        check["scope"] = "allocation"
    else:
        check["probe_stderr"] = "warning\n"
        check["probe_stderr_sha256"] = hashlib.sha256(b"warning\n").hexdigest()
    if tamper.startswith("raw_"):
        check["probe_output"] = json.dumps(probe, sort_keys=True) + "\n"
        check["probe_output_sha256"] = hashlib.sha256(check["probe_output"].encode()).hexdigest()
    fixture["process_audit"].write_text(json.dumps(payload), encoding="utf-8")
    fixture["process_audit_sha256"] = sha256_file(fixture["process_audit"])
    with pytest.raises(RuntimeError, match="invalid process audit check for controller"):
        _audit(fixture)


@pytest.mark.parametrize("tamper", ["scheduler_exit", "top_identity", "extra_job"])
def test_process_audit_rejects_top_level_tamper(tmp_path: Path, tamper: str) -> None:
    """顶层调度、实现身份和 job 集合也必须与节点正文闭合。"""
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture["process_audit"].read_text(encoding="utf-8"))
    if tamper == "scheduler_exit":
        payload["scheduler_exit_code"] = 1
    elif tamper == "top_identity":
        payload["probe_module_sha256"] = "e" * 64
    else:
        payload["job_checks"]["999"] = payload["job_checks"][str(JOB_IDS[0])]
    fixture["process_audit"].write_text(json.dumps(payload), encoding="utf-8")
    fixture["process_audit_sha256"] = sha256_file(fixture["process_audit"])
    message = "implementation identity mismatch" if tamper == "top_identity" else "does not prove"
    with pytest.raises(RuntimeError, match=message):
        _audit(fixture)


def test_process_audit_freshness_uses_oldest_probe_start(tmp_path: Path) -> None:
    """不能用刚写出的 captured_at 掩盖已过期的早期 allocation probe。"""
    fixture = _build_fixture(tmp_path)
    payload = json.loads(fixture["process_audit"].read_text(encoding="utf-8"))
    stale = datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()
    payload["capture_started_at"] = stale
    payload["job_checks"][str(JOB_IDS[0])]["started_at"] = stale
    payload["job_checks"][str(JOB_IDS[0])]["completed_at"] = stale
    fixture["process_audit"].write_text(json.dumps(payload), encoding="utf-8")
    fixture["process_audit_sha256"] = sha256_file(fixture["process_audit"])
    with pytest.raises(RuntimeError, match="does not prove"):
        _audit(fixture)


def test_audit_rejects_unsafe_run_id_and_cross_run_symlink(tmp_path: Path) -> None:
    """run_id 路径逃逸和指向另一 run 的目录 symlink 均 fail-closed。"""
    fixture = _build_fixture(tmp_path)
    with pytest.raises(RuntimeError, match="unsafe run_id"):
        build_scratch_audit(
            fixture["root"],
            fixture["report_dir"],
            run_ids={"../escape"},
            lock_root=fixture["lock_root"],
            job_ids=JOB_IDS,
            process_audit_path=fixture["process_audit"],
            expected_process_audit_sha256=fixture["process_audit_sha256"],
        )
    run_a = fixture["root"] / "scratch" / RUN_A
    run_b = fixture["root"] / "scratch" / RUN_B
    shutil.rmtree(run_a)
    try:
        run_a.symlink_to(run_b, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink is unavailable on this platform: {exc}")
    with pytest.raises(RuntimeError, match="must not be a symlink"):
        _audit(fixture)


def test_apply_binds_all_manifests_and_refuses_tamper(tmp_path: Path) -> None:
    """任一保留文件 manifest 被改写后，bundle 门在删除前阻断。"""
    fixture = _build_fixture(tmp_path)
    _audit(fixture)
    bundle_path = fixture["report_dir"] / "audit_bundle.json"
    retained = fixture["report_dir"] / "nontransient_manifest.jsonl"
    retained.write_text("", encoding="utf-8")
    with pytest.raises(RuntimeError, match="audit bundle manifest drift"):
        _apply(fixture, sha256_file(bundle_path))
    assert (fixture["formal_attempt"] / "full_model.cif").exists()


def test_apply_resumes_intent_after_unlink_before_result_journal(tmp_path: Path) -> None:
    """intent 已 fsync、unlink 已发生但 result 未写时，可对账后继续而不重复越界删除。"""
    fixture = _build_fixture(tmp_path)
    _audit(fixture)
    report_dir = fixture["report_dir"]
    bundle_path = report_dir / "audit_bundle.json"
    bundle_sha256 = sha256_file(bundle_path)
    records = [json.loads(line) for line in (report_dir / "delete_manifest.jsonl").read_text(encoding="utf-8").splitlines()]
    first = records[0]
    target = (
        fixture["root"]
        / "scratch"
        / first["run_id"]
        / "stage_f"
        / first["pdb_id"]
        / first["attempt_id"]
        / Path(first["relative_path"])
    )
    (report_dir / "apply.started.json").write_text(
        json.dumps({"audit_bundle_sha256": bundle_sha256}),
        encoding="utf-8",
    )
    (report_dir / "apply_progress.jsonl").write_text(
        json.dumps({**first, "event": "intent"}, sort_keys=True)
        + "\n"
        + '{"event":"deleted"',
        encoding="utf-8",
    )
    target.unlink()
    summary = _apply(fixture, bundle_sha256)
    assert summary["status"] == "success"
    events = [json.loads(line)["event"] for line in (report_dir / "apply_progress.jsonl").read_text().splitlines()]
    assert "recovered_deleted" in events
    evidence = list(report_dir.glob("journal_tail_recovery_*.json"))
    assert len(evidence) == 1
    assert json.loads(evidence[0].read_text())["tail_hex"]


def test_apply_recovers_truncated_intent_tail_before_any_unlink(tmp_path: Path) -> None:
    """未换行的截断 intent 先冻结证据并截断；live 文件仍按正式 manifest 处理。"""
    fixture = _build_fixture(tmp_path)
    _audit(fixture)
    report_dir = fixture["report_dir"]
    bundle_path = report_dir / "audit_bundle.json"
    bundle_sha256 = sha256_file(bundle_path)
    (report_dir / "apply.started.json").write_text(
        json.dumps({"audit_bundle_sha256": bundle_sha256}),
        encoding="utf-8",
    )
    (report_dir / "apply_progress.jsonl").write_bytes(b'{"event":')
    summary = _apply(fixture, bundle_sha256)
    assert summary["status"] == "success"
    assert list(report_dir.glob("journal_tail_recovery_*.json"))
    assert not (fixture["formal_attempt"] / "full_model.cif").exists()


def test_apply_rechecks_locks_immediately_before_unlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """全局 preflight 后 try-lock 漂移时，不得删除第一份 manifest 文件。"""
    fixture = _build_fixture(tmp_path)
    _audit(fixture)
    bundle_path = fixture["report_dir"] / "audit_bundle.json"
    original = recovery._validate_stopped_locks
    calls = 0

    def _drift_on_second_check(lock_root: Path, job_ids: list[int]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            (lock_root / f"try_lock_{JOB_IDS[0]}").unlink()
        original(lock_root, job_ids)

    monkeypatch.setattr(recovery, "_validate_stopped_locks", _drift_on_second_check)
    with pytest.raises(RuntimeError, match="missing regular try lock"):
        _apply(fixture, sha256_file(bundle_path))
    assert (fixture["formal_attempt"] / "full_model.cif").exists()


def test_audit_rejects_transient_symlink_outside_attempt(tmp_path: Path) -> None:
    """matcher 命中的越界 symlink 不进入 delete manifest，而是 fail-closed。"""
    fixture = _build_fixture(tmp_path)
    outside = tmp_path / "outside.mrc"
    outside.write_bytes(b"outside")
    link = fixture["formal_attempt"] / "escape.mrc"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink is unavailable on this platform: {exc}")
    with pytest.raises(RuntimeError, match="attempt child escaped scope"):
        _audit(fixture)
    assert outside.read_bytes() == b"outside"
