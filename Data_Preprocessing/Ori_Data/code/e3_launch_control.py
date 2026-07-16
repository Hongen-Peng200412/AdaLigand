"""E3 全量迁移的独占写入、Slurm 身份授权与受检释放控制面。

该模块只管理“谁可以写、何时可以写”。它不导入密度标签生产代码，也不改变
Pocket_Plus 数值实现、E3 schema、原子半径或任何科学产物内容。控制证据全部位于
独立 repair run 下；跨 run 的唯一 writer 通过数据根内的全局目录锁实现。
"""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

from io_utils import sha256_file, sha256_named_values
from reports import resolve_run_id


LAUNCH_SCHEMA_VERSION = 1
AUTHORIZATION_SCHEMA_VERSION = 1
SCHEDULER_SNAPSHOT_SCHEMA_VERSION = 1
RELEASE_SCHEMA_VERSION = 1

LAUNCH_STAGE = "stage_e3_launch"
FREEZE_STAGE = "stage_e3_freeze"
REPAIR_RELEASE_STAGE = "stage_e3_repair_release"
GLOBAL_LOCK_RELATIVE = Path("reports") / "runs" / "_locks" / "stage_e3_writer.lock"

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_GIT_COMMIT_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
_SLURM_ID_PATTERN = re.compile(r"[0-9]+")
_ACTUAL_SLURM_JOB_PATTERN = re.compile(r"[0-9]+(?:_[0-9]+)?")
_ENV_NAME_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_SQUEUE_FORMAT = "%A|%a|%i|%T"


def prepare_launch_control(
    root: Path,
    project_root: Path,
    *,
    repair_run_id: str,
    target_manifest: Path,
    expected_target_manifest_sha256: str,
    git_commit: str,
    implementation_files: Sequence[Path],
    required_environment: Mapping[str, str] | None = None,
    extra_evidence: Mapping[str, Any] | None = None,
    python_executable: str | None = None,
    python_version: str | None = None,
) -> dict[str, Any]:
    """冻结启动 manifest，并取得整个数据根唯一的 E3 writer 所有权。

    输入参数:
        - root/project_root: Path, 数据根与代码仓库根
        - repair_run_id: str, 与正式 Stage E 隔离的迁移 run id
        - target_manifest: Path, 必须是该 run 的 ``stage_e3_freeze/target_manifest.json``
        - expected_target_manifest_sha256: str, 已冻结目标清单摘要
        - git_commit: str, 调度时明确绑定的完整 Git commit
        - implementation_files: Sequence[Path], 迁移实现闭包中的代码/脚本文件
        - required_environment: Mapping[str,str], worker 必须逐项相同的稳定环境变量
        - extra_evidence: Mapping[str,Any], 只读审计证据；文件必须位于数据根并绑定 SHA
        - python_executable/python_version: str, 运行时身份；缺省为当前解释器

    输出:
        - manifest: dict, 可供 worker 重放验证的不可变启动契约

    说明:
        先发布 run-scoped manifest，再原子创建全局目录锁。同一契约可幂等重放；
        其他 run 或任何实现身份差异都会被拒绝。崩溃产生的不完整锁会保守阻断，
        不会被自动猜测或清理。
    """
    context = _launch_context(root, project_root, repair_run_id)
    target_path = _require_exact_target_manifest(
        context["root"], context["repair_run_id"], target_manifest
    )
    expected_target_sha = _normalize_sha256(
        expected_target_manifest_sha256,
        field="expected_target_manifest_sha256",
    )
    _require_file_sha(target_path, expected_target_sha, label="target_manifest")
    target_payload = _read_json_object(target_path, label="target_manifest")
    if (
        resolve_run_id(str(target_payload.get("repair_run_id", "")))
        != context["repair_run_id"]
    ):
        raise RuntimeError("target manifest repair_run_id disagrees with launch run")

    normalized_commit = git_commit.strip().lower()
    if not _GIT_COMMIT_PATTERN.fullmatch(normalized_commit):
        raise ValueError(
            "git_commit must be a full 40- or 64-character lowercase hex digest"
        )
    implementation = _implementation_identity(
        context["project_root"], implementation_files
    )
    environment = _normalize_required_environment(required_environment or {})
    evidence = _normalize_extra_evidence(context["root"], extra_evidence or {})
    executable = str(Path(python_executable or sys.executable).resolve(strict=False))
    version = (python_version or platform.python_version()).strip()
    if not version:
        raise ValueError("python_version cannot be empty")

    manifest = {
        "schema_version": LAUNCH_SCHEMA_VERSION,
        "contract": "e3_single_writer_launch_control",
        "repair_run_id": context["repair_run_id"],
        "data_root": str(context["root"]),
        "project_root": str(context["project_root"]),
        "target_manifest_path": _relative_identity(context["root"], target_path),
        "target_manifest_sha256": expected_target_sha,
        "target_ids_sha256": _normalize_sha256(
            str(target_payload.get("target_ids_sha256", "")),
            field="target_manifest.target_ids_sha256",
        ),
        "target_count": _positive_int(
            target_payload.get("target_count"), field="target_count"
        ),
        "git_commit": normalized_commit,
        "implementation_files": implementation,
        "implementation_bundle_sha256": sha256_named_values(implementation),
        "python_executable": executable,
        "python_version": version,
        "required_environment": environment,
        "extra_evidence": evidence,
    }
    launch_path = (
        _launch_dir(context["root"], context["repair_run_id"]) / "launch_manifest.json"
    )
    _write_immutable_json(launch_path, manifest)
    manifest_sha = sha256_file(launch_path)
    owner = {
        "schema_version": LAUNCH_SCHEMA_VERSION,
        "repair_run_id": context["repair_run_id"],
        "launch_manifest_path": _relative_identity(context["root"], launch_path),
        "launch_manifest_sha256": manifest_sha,
        "target_manifest_sha256": expected_target_sha,
        "git_commit": normalized_commit,
        "implementation_bundle_sha256": manifest["implementation_bundle_sha256"],
    }
    _acquire_global_lock(context["root"], owner)
    return manifest


def authorize_slurm_identity(
    root: Path,
    project_root: Path,
    *,
    repair_run_id: str,
    role: str,
    job_id: str | None = None,
    array_job_id: str | None = None,
    array_task_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    """为已经提交且保持阻断的 Slurm job/array 原子追加一个不可变授权。

    ``job_id`` 与 ``array_job_id`` 二选一。数组授权同时冻结允许的 task id 集合；
    每个授权独占一个 O_EXCL 文件，因此不同控制器并发追加不会覆盖彼此。
    """
    manifest, manifest_path = _verify_launch_identity(root, project_root, repair_run_id)
    normalized_role = _normalize_role(role)
    normalized_job = _optional_slurm_id(job_id, field="job_id")
    normalized_array = _optional_slurm_id(array_job_id, field="array_job_id")
    tasks = _normalize_task_ids(array_task_ids or [])
    if (normalized_job is None) == (normalized_array is None):
        raise ValueError("authorize exactly one of job_id or array_job_id")
    if normalized_job is not None and tasks:
        raise ValueError("array_task_ids are only valid with array_job_id")
    if normalized_array is not None and not tasks:
        raise ValueError("array authorization requires at least one array_task_id")

    if normalized_job is not None:
        authorization_id = f"{normalized_role}-job-{normalized_job}"
    else:
        authorization_id = f"{normalized_role}-array-{normalized_array}"
    authorization = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "authorization_id": authorization_id,
        "repair_run_id": manifest["repair_run_id"],
        "role": normalized_role,
        "launch_manifest_sha256": sha256_file(manifest_path),
        "job_id": normalized_job,
        "array_job_id": normalized_array,
        "array_task_ids": tasks,
    }
    path = (
        _authorization_dir(root, manifest["repair_run_id"]) / f"{authorization_id}.json"
    )
    with _authorization_transaction(root, manifest["repair_run_id"]):
        if _authorization_seal_path(root, manifest["repair_run_id"]).exists():
            raise RuntimeError("E3 Slurm authorizations are already sealed")
        _write_immutable_json(path, authorization)
    return authorization


def seal_slurm_authorizations(
    root: Path,
    project_root: Path,
    *,
    repair_run_id: str,
) -> dict[str, Any]:
    """封口全部已授权 Slurm 身份；封口后禁止继续追加或改变授权集合。"""
    manifest, manifest_path = _verify_launch_identity(root, project_root, repair_run_id)
    with _authorization_transaction(root, manifest["repair_run_id"]):
        authorizations = _load_authorizations(root, manifest["repair_run_id"])
        if not authorizations:
            raise RuntimeError("cannot seal an empty E3 Slurm authorization set")
        if not any(item["role"] == "worker" for item in authorizations):
            raise RuntimeError("E3 authorization set must contain at least one worker")
        if not any(item["role"] == "gate" for item in authorizations):
            raise RuntimeError("E3 authorization set must contain a gate job")
        file_sha256 = {
            f"{item['authorization_id']}.json": sha256_file(
                _authorization_dir(root, manifest["repair_run_id"])
                / f"{item['authorization_id']}.json"
            )
            for item in authorizations
        }
        seal = {
            "schema_version": AUTHORIZATION_SCHEMA_VERSION,
            "repair_run_id": manifest["repair_run_id"],
            "launch_manifest_sha256": sha256_file(manifest_path),
            "authorization_ids": sorted(
                item["authorization_id"] for item in authorizations
            ),
            "authorization_file_sha256": dict(sorted(file_sha256.items())),
            "authorization_set_sha256": sha256_named_values(file_sha256),
        }
        _write_immutable_json(
            _authorization_seal_path(root, manifest["repair_run_id"]), seal
        )
    return seal


def verify_slurm_worker(
    root: Path,
    project_root: Path,
    *,
    repair_run_id: str,
    role: str,
    environ: Mapping[str, str] | None = None,
    python_executable: str | None = None,
    python_version: str | None = None,
) -> dict[str, Any]:
    """worker/gate 启动前验证精确 Slurm 身份与全部文件、解释器、环境身份。"""
    manifest, manifest_path = _verify_launch_identity(
        root,
        project_root,
        repair_run_id,
        environ=environ,
        python_executable=python_executable,
        python_version=python_version,
        verify_runtime=True,
    )
    normalized_role = _normalize_role(role)
    actual_env = dict(os.environ if environ is None else environ)
    actual = _actual_slurm_identity(actual_env)
    _, authorizations = _load_sealed_authorizations(root, manifest["repair_run_id"])
    matches = [
        authorization
        for authorization in authorizations
        if authorization["role"] == normalized_role
        and authorization["launch_manifest_sha256"] == sha256_file(manifest_path)
        and _authorization_matches(authorization, actual)
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "Slurm identity is not authorized exactly once: "
            f"role={normalized_role}, actual={actual}, matches={len(matches)}"
        )
    return {
        "status": "authorized",
        "repair_run_id": manifest["repair_run_id"],
        "role": normalized_role,
        "authorization_id": matches[0]["authorization_id"],
        "actual_slurm_identity": actual,
        "launch_manifest_sha256": sha256_file(manifest_path),
    }


def release_launch_control(
    root: Path,
    project_root: Path,
    *,
    repair_run_id: str,
    scheduler_snapshot: Path,
    expected_gate_summary_sha256: str,
) -> dict[str, Any]:
    """在 E3 gate 成功且全部已授权作业退出后，受检释放全局 writer 锁。

    最终 ``released`` 标记只在全局锁确实删除后发布；锁删除前先写不可变 intent，
    因而任意中断都能区分“已审计待释放”和“已完成释放”。
    """
    context = _launch_context(root, project_root, repair_run_id)
    intent_path = (
        _launch_dir(context["root"], context["repair_run_id"])
        / "launch_release_intent.json"
    )
    release_path = (
        _launch_dir(context["root"], context["repair_run_id"]) / "launch_release.json"
    )
    gate_sha = _normalize_sha256(
        expected_gate_summary_sha256,
        field="expected_gate_summary_sha256",
    )
    snapshot_path = _require_regular_file(
        scheduler_snapshot, label="scheduler_snapshot"
    )
    owns_lock = _global_lock_owned_by(context["root"], context["repair_run_id"])
    if release_path.exists():
        if owns_lock:
            raise RuntimeError(
                "released marker exists while this run still owns writer lock"
            )
        existing = _read_json_object(release_path, label="launch_release")
        _validate_release_replay(
            existing,
            root=context["root"],
            repair_run_id=context["repair_run_id"],
            gate_sha256=gate_sha,
            scheduler_snapshot=snapshot_path,
        )
        return existing
    if intent_path.exists() and not owns_lock:
        return _commit_release_from_intent(
            context["root"],
            context["repair_run_id"],
            intent_path,
            release_path,
            gate_sha256=gate_sha,
            scheduler_snapshot=snapshot_path,
        )
    if not owns_lock:
        raise RuntimeError("this repair run does not own the E3 writer lock")

    manifest, manifest_path = _verify_launch_identity(
        context["root"], context["project_root"], context["repair_run_id"]
    )
    gate_path = (
        context["root"]
        / "reports"
        / "runs"
        / context["repair_run_id"]
        / REPAIR_RELEASE_STAGE
        / "summary.json"
    )
    _require_file_sha(gate_path, gate_sha, label="E3 gate summary")
    gate = _read_json_object(gate_path, label="E3 gate summary")
    if (
        gate.get("status") != "success"
        or gate.get("run_id") != context["repair_run_id"]
    ):
        raise RuntimeError("E3 gate summary is not a success for this repair run")
    if gate.get("stage") != "stage_e3_repair":
        raise RuntimeError("E3 gate summary stage must be stage_e3_repair")
    if gate.get("target_manifest_sha256") != manifest["target_manifest_sha256"]:
        raise RuntimeError("E3 gate target manifest identity drift")

    seal, authorizations = _load_sealed_authorizations(
        context["root"], context["repair_run_id"]
    )
    query_job_ids = sorted(
        {str(item["job_id"] or item["array_job_id"]) for item in authorizations},
        key=int,
    )
    snapshot = _read_json_object(snapshot_path, label="scheduler_snapshot")
    _validate_scheduler_snapshot(
        snapshot,
        repair_run_id=context["repair_run_id"],
        launch_manifest_sha256=sha256_file(manifest_path),
        authorization_seal_sha256=sha256_file(
            _authorization_seal_path(context["root"], context["repair_run_id"])
        ),
        authorization_ids=seal["authorization_ids"],
        authorization_set_sha256=seal["authorization_set_sha256"],
        query_job_ids=query_job_ids,
    )

    owner = _validate_global_lock(context["root"], manifest, manifest_path)
    intent = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "status": "release_intent",
        "repair_run_id": context["repair_run_id"],
        "launch_manifest_sha256": sha256_file(manifest_path),
        "target_manifest_sha256": manifest["target_manifest_sha256"],
        "gate_summary_path": _relative_identity(context["root"], gate_path),
        "gate_summary_sha256": gate_sha,
        "scheduler_snapshot_path": _relative_identity(context["root"], snapshot_path),
        "scheduler_snapshot_sha256": sha256_file(snapshot_path),
        "authorization_seal_path": _relative_identity(
            context["root"],
            _authorization_seal_path(context["root"], context["repair_run_id"]),
        ),
        "authorization_seal_sha256": sha256_file(
            _authorization_seal_path(context["root"], context["repair_run_id"])
        ),
        "authorization_ids": seal["authorization_ids"],
        "authorization_set_sha256": seal["authorization_set_sha256"],
        "lock_owner": owner,
    }
    _write_immutable_json(intent_path, intent)
    _remove_exact_global_lock(context["root"], owner)
    return _commit_release_from_intent(
        context["root"],
        context["repair_run_id"],
        intent_path,
        release_path,
        gate_sha256=gate_sha,
        scheduler_snapshot=snapshot_path,
    )


def capture_scheduler_snapshot(
    root: Path,
    project_root: Path,
    *,
    repair_run_id: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    """直接调用 ``squeue``，只在全部封口作业均不活跃时返回调度快照。"""
    manifest, manifest_path = _verify_launch_identity(root, project_root, repair_run_id)
    seal, authorizations = _load_sealed_authorizations(root, repair_run_id)
    query_job_ids = sorted(
        {str(item["job_id"] or item["array_job_id"]) for item in authorizations},
        key=int,
    )
    command = [
        "squeue",
        "--noheader",
        "--jobs",
        ",".join(query_job_ids),
        "--format",
        _SQUEUE_FORMAT,
    ]
    execute = subprocess.run if runner is None else runner
    completed = execute(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "squeue failed while capturing E3 terminal snapshot: "
            f"returncode={completed.returncode}, stderr={completed.stderr!r}"
        )
    if completed.stdout.strip():
        raise RuntimeError(
            "E3 Slurm jobs are still active; writer lock cannot be released: "
            f"{completed.stdout.strip().splitlines()[:20]}"
        )
    return {
        "schema_version": SCHEDULER_SNAPSHOT_SCHEMA_VERSION,
        "repair_run_id": manifest["repair_run_id"],
        "launch_manifest_sha256": sha256_file(manifest_path),
        "authorization_seal_sha256": sha256_file(
            _authorization_seal_path(root, repair_run_id)
        ),
        "authorization_ids": seal["authorization_ids"],
        "authorization_set_sha256": seal["authorization_set_sha256"],
        "query_job_ids": query_job_ids,
        "squeue_command": command,
        "squeue_returncode": completed.returncode,
        "squeue_stdout": completed.stdout,
        "squeue_stderr": completed.stderr,
    }


def _verify_launch_identity(
    root: Path,
    project_root: Path,
    repair_run_id: str,
    *,
    environ: Mapping[str, str] | None = None,
    python_executable: str | None = None,
    python_version: str | None = None,
    verify_runtime: bool = False,
) -> tuple[dict[str, Any], Path]:
    context = _launch_context(root, project_root, repair_run_id)
    manifest_path = (
        _launch_dir(context["root"], context["repair_run_id"]) / "launch_manifest.json"
    )
    manifest = _read_json_object(manifest_path, label="launch_manifest")
    if manifest.get("schema_version") != LAUNCH_SCHEMA_VERSION:
        raise RuntimeError("launch manifest schema drift")
    if manifest.get("repair_run_id") != context["repair_run_id"]:
        raise RuntimeError("launch manifest repair_run_id drift")
    if manifest.get("data_root") != str(context["root"]):
        raise RuntimeError("launch manifest data_root drift")
    if manifest.get("project_root") != str(context["project_root"]):
        raise RuntimeError("launch manifest project_root drift")

    target_path = context["root"] / Path(str(manifest.get("target_manifest_path", "")))
    _require_exact_target_manifest(
        context["root"], context["repair_run_id"], target_path
    )
    _require_file_sha(
        target_path,
        _normalize_sha256(
            str(manifest.get("target_manifest_sha256", "")),
            field="launch_manifest.target_manifest_sha256",
        ),
        label="target_manifest",
    )
    implementation = manifest.get("implementation_files")
    if not isinstance(implementation, dict) or not implementation:
        raise RuntimeError("launch manifest implementation_files must be non-empty")
    actual_implementation: dict[str, str] = {}
    for relative, expected in sorted(implementation.items()):
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise RuntimeError("launch manifest implementation identity is malformed")
        path = _project_file(context["project_root"], Path(relative))
        actual_implementation[relative] = sha256_file(path)
        if actual_implementation[relative] != expected:
            raise RuntimeError(f"implementation file drift: {relative}")
    if sha256_named_values(actual_implementation) != manifest.get(
        "implementation_bundle_sha256"
    ):
        raise RuntimeError("implementation bundle identity drift")

    _verify_extra_evidence(context["root"], manifest.get("extra_evidence"))

    if verify_runtime:
        actual_executable = str(
            Path(python_executable or sys.executable).resolve(strict=False)
        )
        actual_version = (python_version or platform.python_version()).strip()
        if actual_executable != manifest.get("python_executable"):
            raise RuntimeError("Python executable identity drift")
        if actual_version != manifest.get("python_version"):
            raise RuntimeError("Python version identity drift")
        actual_env = dict(os.environ if environ is None else environ)
        required = manifest.get("required_environment")
        if not isinstance(required, dict):
            raise RuntimeError("launch manifest required_environment is malformed")
        drifted_env = [
            key
            for key, value in sorted(required.items())
            if actual_env.get(key) != value
        ]
        if drifted_env:
            raise RuntimeError(f"required environment drift: {drifted_env}")
    _validate_global_lock(context["root"], manifest, manifest_path)
    return manifest, manifest_path


def _launch_context(
    root: Path, project_root: Path, repair_run_id: str
) -> dict[str, Any]:
    normalized_root = root.resolve(strict=True)
    normalized_project = project_root.resolve(strict=True)
    if not normalized_root.is_dir() or not normalized_project.is_dir():
        raise ValueError("root and project_root must be existing directories")
    return {
        "root": normalized_root,
        "project_root": normalized_project,
        "repair_run_id": resolve_run_id(repair_run_id),
    }


def _launch_dir(root: Path, repair_run_id: str) -> Path:
    return root / "reports" / "runs" / resolve_run_id(repair_run_id) / LAUNCH_STAGE


def _authorization_dir(root: Path, repair_run_id: str) -> Path:
    return _launch_dir(root, repair_run_id) / "allowed_jobs"


def _authorization_seal_path(root: Path, repair_run_id: str) -> Path:
    return _launch_dir(root, repair_run_id) / "authorization_manifest.json"


@contextmanager
def _authorization_transaction(root: Path, repair_run_id: str) -> Iterator[None]:
    """串行化授权追加与封口；崩溃遗留锁会保守阻断，不自动猜测清理。"""
    directory = _authorization_dir(root, repair_run_id)
    directory.mkdir(parents=True, exist_ok=True)
    lock_path = directory / ".authorization_update.lock"
    deadline = time.monotonic() + 30.0
    while True:
        try:
            lock_path.mkdir()
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError("timed out waiting for E3 authorization update lock")
            time.sleep(0.01)
    try:
        yield
    finally:
        lock_path.rmdir()


def _global_lock_path(root: Path) -> Path:
    return root.resolve(strict=True) / GLOBAL_LOCK_RELATIVE


def _require_exact_target_manifest(root: Path, repair_run_id: str, path: Path) -> Path:
    expected = (
        root
        / "reports"
        / "runs"
        / repair_run_id
        / FREEZE_STAGE
        / "target_manifest.json"
    )
    actual = path.resolve(strict=True)
    if actual != expected.resolve(strict=False):
        raise ValueError(
            f"target_manifest must be the canonical freeze output: {expected}"
        )
    return _require_regular_file(actual, label="target_manifest")


def _implementation_identity(
    project_root: Path, files: Sequence[Path]
) -> dict[str, str]:
    if not files:
        raise ValueError("implementation_files cannot be empty")
    identity: dict[str, str] = {}
    for raw_path in files:
        path = raw_path if raw_path.is_absolute() else project_root / raw_path
        path = _project_file(project_root, path)
        relative = path.relative_to(project_root).as_posix()
        if relative in identity:
            raise ValueError(f"duplicate implementation file: {relative}")
        identity[relative] = sha256_file(path)
    return dict(sorted(identity.items()))


def _project_file(project_root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else project_root / path
    if candidate.is_symlink():
        raise ValueError(f"implementation file cannot be a symlink: {candidate}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(
            f"implementation file escapes project_root: {candidate}"
        ) from exc
    return _require_regular_file(resolved, label="implementation file")


def _acquire_global_lock(root: Path, owner: dict[str, Any]) -> None:
    lock_path = _global_lock_path(root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_path.mkdir()
    except FileExistsError:
        existing = _read_json_object(
            lock_path / "owner.json", label="global lock owner"
        )
        if existing != owner:
            raise RuntimeError(
                "another E3 writer owns the global lock: "
                f"repair_run_id={existing.get('repair_run_id')}"
            )
        return
    try:
        _write_immutable_json(lock_path / "owner.json", owner)
    except Exception:
        # 不猜测失败点；不完整锁必须保守保留，供人工审计后处理。
        raise


def _validate_global_lock(
    root: Path,
    manifest: Mapping[str, Any],
    manifest_path: Path,
) -> dict[str, Any]:
    lock_path = _global_lock_path(root)
    if lock_path.is_symlink() or not lock_path.is_dir():
        raise RuntimeError("E3 global writer lock is missing or not a real directory")
    owner = _read_json_object(lock_path / "owner.json", label="global lock owner")
    expected = {
        "schema_version": LAUNCH_SCHEMA_VERSION,
        "repair_run_id": manifest["repair_run_id"],
        "launch_manifest_path": _relative_identity(root, manifest_path),
        "launch_manifest_sha256": sha256_file(manifest_path),
        "target_manifest_sha256": manifest["target_manifest_sha256"],
        "git_commit": manifest["git_commit"],
        "implementation_bundle_sha256": manifest["implementation_bundle_sha256"],
    }
    if owner != expected:
        raise RuntimeError("E3 global writer lock owner identity drift")
    return owner


def _remove_exact_global_lock(root: Path, expected_owner: Mapping[str, Any]) -> None:
    lock_path = _global_lock_path(root)
    entries = sorted(path.name for path in lock_path.iterdir())
    if entries != ["owner.json"]:
        raise RuntimeError(f"global lock contains unexpected entries: {entries}")
    owner_path = lock_path / "owner.json"
    if _read_json_object(owner_path, label="global lock owner") != dict(expected_owner):
        raise RuntimeError("global lock owner changed before release")
    owner_path.unlink()
    lock_path.rmdir()


def _global_lock_owned_by(root: Path, repair_run_id: str) -> bool:
    lock_path = _global_lock_path(root)
    if not lock_path.exists():
        return False
    if lock_path.is_symlink() or not lock_path.is_dir():
        raise RuntimeError("E3 global writer lock is not a real directory")
    owner = _read_json_object(lock_path / "owner.json", label="global lock owner")
    return owner.get("repair_run_id") == resolve_run_id(repair_run_id)


def _commit_release_from_intent(
    root: Path,
    repair_run_id: str,
    intent_path: Path,
    release_path: Path,
    *,
    gate_sha256: str,
    scheduler_snapshot: Path,
) -> dict[str, Any]:
    intent = _read_json_object(intent_path, label="launch_release_intent")
    _validate_release_replay(
        intent,
        root=root,
        repair_run_id=repair_run_id,
        gate_sha256=gate_sha256,
        scheduler_snapshot=scheduler_snapshot,
    )
    if intent.get("status") != "release_intent":
        raise RuntimeError("launch release intent status drift")
    release = {
        **intent,
        "status": "released",
        "release_intent_path": _relative_identity(root, intent_path),
        "release_intent_sha256": sha256_file(intent_path),
    }
    _write_immutable_json(release_path, release)
    return release


def _validate_release_replay(
    record: Mapping[str, Any],
    *,
    root: Path,
    repair_run_id: str,
    gate_sha256: str,
    scheduler_snapshot: Path,
) -> None:
    if (
        record.get("status") not in {"release_intent", "released"}
        or record.get("repair_run_id") != resolve_run_id(repair_run_id)
        or record.get("gate_summary_sha256") != gate_sha256
        or record.get("scheduler_snapshot_sha256") != sha256_file(scheduler_snapshot)
        or record.get("scheduler_snapshot_path")
        != _relative_identity(root, scheduler_snapshot)
    ):
        raise RuntimeError(
            "existing E3 launch release disagrees with replayed evidence"
        )


def _load_authorizations(root: Path, repair_run_id: str) -> list[dict[str, Any]]:
    normalized_run_id = resolve_run_id(repair_run_id)
    directory = _authorization_dir(root, normalized_run_id)
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise RuntimeError("allowed_jobs must be a real directory")
    records: list[dict[str, Any]] = []
    launch_path = _launch_dir(root, normalized_run_id) / "launch_manifest.json"
    launch_sha = sha256_file(
        _require_regular_file(launch_path, label="launch_manifest")
    )
    required_fields = {
        "schema_version",
        "authorization_id",
        "repair_run_id",
        "role",
        "launch_manifest_sha256",
        "job_id",
        "array_job_id",
        "array_task_ids",
    }
    for path in sorted(directory.glob("*.json")):
        record = _read_json_object(path, label="Slurm authorization")
        if set(record) != required_fields:
            raise RuntimeError(f"authorization fields drift: {path}")
        expected_name = f"{record.get('authorization_id')}.json"
        if path.name != expected_name:
            raise RuntimeError(f"authorization filename disagrees with payload: {path}")
        if record.get("schema_version") != AUTHORIZATION_SCHEMA_VERSION:
            raise RuntimeError(f"authorization schema drift: {path}")
        if record.get("repair_run_id") != normalized_run_id:
            raise RuntimeError(f"authorization repair_run_id drift: {path}")
        if record.get("launch_manifest_sha256") != launch_sha:
            raise RuntimeError(f"authorization launch identity drift: {path}")
        role = _normalize_role(str(record.get("role", "")))
        job_id = _optional_slurm_id(record.get("job_id"), field="authorization.job_id")
        array_job_id = _optional_slurm_id(
            record.get("array_job_id"), field="authorization.array_job_id"
        )
        task_values = record.get("array_task_ids")
        if not isinstance(task_values, list):
            raise RuntimeError(f"authorization array_task_ids drift: {path}")
        task_ids = _normalize_task_ids(task_values)
        if (job_id is None) == (array_job_id is None):
            raise RuntimeError(f"authorization job/array identity drift: {path}")
        if job_id is not None and task_ids:
            raise RuntimeError(f"singleton authorization contains array tasks: {path}")
        if array_job_id is not None and not task_ids:
            raise RuntimeError(f"array authorization has no tasks: {path}")
        expected_id = (
            f"{role}-job-{job_id}"
            if job_id is not None
            else f"{role}-array-{array_job_id}"
        )
        if record["authorization_id"] != expected_id:
            raise RuntimeError(f"authorization_id drift: {path}")
        records.append(record)
    return records


def _load_sealed_authorizations(
    root: Path, repair_run_id: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """读取同一不可变封口清单，并拒绝封口后新增、删除或改写授权。"""
    normalized_run_id = resolve_run_id(repair_run_id)
    seal_path = _authorization_seal_path(root, normalized_run_id)
    seal = _read_json_object(seal_path, label="authorization_manifest")
    required_fields = {
        "schema_version",
        "repair_run_id",
        "launch_manifest_sha256",
        "authorization_ids",
        "authorization_file_sha256",
        "authorization_set_sha256",
    }
    if set(seal) != required_fields:
        raise RuntimeError("authorization manifest fields drift")
    authorizations = _load_authorizations(root, normalized_run_id)
    actual_files = {
        f"{item['authorization_id']}.json": sha256_file(
            _authorization_dir(root, normalized_run_id)
            / f"{item['authorization_id']}.json"
        )
        for item in authorizations
    }
    expected = {
        "schema_version": AUTHORIZATION_SCHEMA_VERSION,
        "repair_run_id": normalized_run_id,
        "launch_manifest_sha256": sha256_file(
            _launch_dir(root, normalized_run_id) / "launch_manifest.json"
        ),
        "authorization_ids": sorted(
            item["authorization_id"] for item in authorizations
        ),
        "authorization_file_sha256": dict(sorted(actual_files.items())),
        "authorization_set_sha256": sha256_named_values(actual_files),
    }
    if seal != expected:
        raise RuntimeError("sealed E3 authorization set drift")
    return seal, authorizations


def _actual_slurm_identity(environ: Mapping[str, str]) -> dict[str, Any]:
    job_id = environ.get("SLURM_JOB_ID", "").strip()
    if not _ACTUAL_SLURM_JOB_PATTERN.fullmatch(job_id):
        raise RuntimeError("SLURM_JOB_ID is missing or malformed")
    array_job = environ.get("SLURM_ARRAY_JOB_ID")
    array_task = environ.get("SLURM_ARRAY_TASK_ID")
    if (array_job is None) != (array_task is None):
        raise RuntimeError("Slurm array identity is incomplete")
    if array_job is None:
        return {"job_id": job_id, "array_job_id": None, "array_task_id": None}
    normalized_array = _optional_slurm_id(array_job, field="SLURM_ARRAY_JOB_ID")
    if not str(array_task).isdigit():
        raise RuntimeError("SLURM_ARRAY_TASK_ID is malformed")
    return {
        "job_id": job_id,
        "array_job_id": normalized_array,
        "array_task_id": int(str(array_task)),
    }


def _authorization_matches(
    authorization: Mapping[str, Any], actual: Mapping[str, Any]
) -> bool:
    if authorization["job_id"] is not None:
        return (
            actual["array_job_id"] is None
            and actual["job_id"] == authorization["job_id"]
        )
    return (
        actual["array_job_id"] == authorization["array_job_id"]
        and actual["array_task_id"] in authorization["array_task_ids"]
    )


def _validate_scheduler_snapshot(
    snapshot: Mapping[str, Any],
    *,
    repair_run_id: str,
    launch_manifest_sha256: str,
    authorization_seal_sha256: str,
    authorization_ids: Sequence[str],
    authorization_set_sha256: str,
    query_job_ids: Sequence[str],
) -> None:
    required_fields = {
        "schema_version",
        "repair_run_id",
        "launch_manifest_sha256",
        "authorization_seal_sha256",
        "authorization_ids",
        "authorization_set_sha256",
        "query_job_ids",
        "squeue_command",
        "squeue_returncode",
        "squeue_stdout",
        "squeue_stderr",
    }
    expected_command = [
        "squeue",
        "--noheader",
        "--jobs",
        ",".join(query_job_ids),
        "--format",
        _SQUEUE_FORMAT,
    ]
    if (
        set(snapshot) != required_fields
        or snapshot.get("schema_version") != SCHEDULER_SNAPSHOT_SCHEMA_VERSION
        or snapshot.get("repair_run_id") != repair_run_id
        or snapshot.get("launch_manifest_sha256") != launch_manifest_sha256
        or snapshot.get("authorization_seal_sha256") != authorization_seal_sha256
        or snapshot.get("authorization_ids") != sorted(authorization_ids)
        or snapshot.get("authorization_set_sha256") != authorization_set_sha256
        or snapshot.get("query_job_ids") != list(query_job_ids)
        or snapshot.get("squeue_command") != expected_command
        or snapshot.get("squeue_returncode") != 0
        or not isinstance(snapshot.get("squeue_stdout"), str)
        or str(snapshot.get("squeue_stdout")).strip()
        or not isinstance(snapshot.get("squeue_stderr"), str)
    ):
        raise RuntimeError(
            "scheduler snapshot is active, incomplete, or identity-drifted"
        )


def _normalize_role(role: str) -> str:
    normalized = role.strip().lower()
    if normalized not in {"worker", "gate"}:
        raise ValueError("role must be worker or gate")
    return normalized


def _optional_slurm_id(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not _SLURM_ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} must contain decimal digits only")
    return normalized


def _normalize_task_ids(values: Sequence[int]) -> list[int]:
    tasks = sorted(set(values))
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in tasks
    ):
        raise ValueError("array_task_ids must contain non-negative integers")
    return tasks


def _normalize_required_environment(values: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in sorted(values.items()):
        if not _ENV_NAME_PATTERN.fullmatch(key):
            raise ValueError(f"invalid environment variable name: {key}")
        if not isinstance(value, str):
            raise ValueError(f"required environment value must be a string: {key}")
        normalized[key] = value
    return normalized


def _normalize_extra_evidence(root: Path, values: Mapping[str, Any]) -> dict[str, Any]:
    """规范化通用只读证据；不解释 policy，也不把审计结论变成科学规则。"""
    normalized: dict[str, Any] = {}
    for evidence_id, raw_record in sorted(values.items()):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", evidence_id):
            raise ValueError(f"invalid extra evidence id: {evidence_id}")
        if not isinstance(raw_record, Mapping):
            raise ValueError(f"extra evidence must be an object: {evidence_id}")
        if set(raw_record) != {"policy", "files"}:
            raise ValueError(
                f"extra evidence fields must be policy/files only: {evidence_id}"
            )
        policy = raw_record["policy"]
        files = raw_record["files"]
        if not isinstance(policy, str) or not policy.strip():
            raise ValueError(f"extra evidence policy must be non-empty: {evidence_id}")
        if not isinstance(files, Mapping) or not files:
            raise ValueError(f"extra evidence files must be non-empty: {evidence_id}")
        normalized_files: dict[str, dict[str, str]] = {}
        for label, raw_file in sorted(files.items()):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", label):
                raise ValueError(f"invalid extra evidence file label: {label}")
            if not isinstance(raw_file, Mapping) or set(raw_file) != {"path", "sha256"}:
                raise ValueError(
                    f"extra evidence file fields must be path/sha256 only: {evidence_id}.{label}"
                )
            raw_path = raw_file["path"]
            if not isinstance(raw_path, (str, Path)):
                raise ValueError(
                    f"extra evidence path must be a string: {evidence_id}.{label}"
                )
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = root / candidate
            candidate = _require_regular_file(
                candidate, label=f"extra evidence {evidence_id}.{label}"
            )
            relative = _relative_identity(root, candidate)
            expected = _normalize_sha256(
                str(raw_file["sha256"]),
                field=f"extra_evidence.{evidence_id}.{label}.sha256",
            )
            _require_file_sha(
                candidate, expected, label=f"extra evidence {evidence_id}.{label}"
            )
            normalized_files[label] = {"path": relative, "sha256": expected}
        normalized[evidence_id] = {
            "policy": policy.strip(),
            "files": normalized_files,
        }
    return normalized


def _verify_extra_evidence(root: Path, values: Any) -> None:
    if not isinstance(values, dict):
        raise RuntimeError("launch manifest extra_evidence is malformed")
    # 重新走同一规范化路径，并要求 manifest 已经是 canonical 形式。
    normalized = _normalize_extra_evidence(root, values)
    if normalized != values:
        raise RuntimeError("launch manifest extra_evidence canonical identity drift")


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _normalize_sha256(value: str, *, field: str) -> str:
    normalized = value.strip().lower()
    if not _SHA256_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field} must be a 64-character lowercase SHA-256")
    return normalized


def _require_file_sha(path: Path, expected: str, *, label: str) -> None:
    actual = sha256_file(_require_regular_file(path, label=label))
    if actual != expected:
        raise RuntimeError(
            f"{label} identity drift: actual={actual}, expected={expected}"
        )


def _require_regular_file(path: Path, *, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} cannot be a symlink: {path}")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return resolved


def _relative_identity(root: Path, path: Path) -> str:
    resolved = path.resolve(strict=False)
    try:
        return resolved.relative_to(root.resolve(strict=True)).as_posix()
    except ValueError as exc:
        raise ValueError(f"path escapes data root: {path}") from exc


def _read_json_object(path: Path, *, label: str) -> dict[str, Any]:
    regular = _require_regular_file(path, label=label)
    payload = json.loads(regular.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload


def _write_immutable_json(path: Path, payload: Mapping[str, Any]) -> bool:
    serialized = (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        if _read_json_object(path, label="immutable JSON") != dict(payload):
            raise RuntimeError(
                f"immutable control evidence already exists with drift: {path}"
            )
        return False
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        # 当前调用只移除自己尚未成功发布的空/半写文件；不会触碰其他证据。
        path.unlink(missing_ok=True)
        raise
    return True
