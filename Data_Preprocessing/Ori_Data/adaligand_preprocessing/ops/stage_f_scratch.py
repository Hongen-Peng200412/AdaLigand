"""审计并精确清理 Stage F 硬中断后遗留的 scratch 文件。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import stat
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from statistics import median
from typing import Any, Iterable

from adaligand_preprocessing.utils.io import file_lock, read_jsonl, sha256_file, write_jsonl
from adaligand_preprocessing.stages.stage_f import _is_quality_attempt_transient
from adaligand_preprocessing.artifacts.reports import write_report
from adaligand_preprocessing.ops.stage_f_processes import (
    PROCESS_AUDIT_SCHEMA_VERSION,
    PROCESS_PROBE_CONTRACT,
    PROCESS_PROBE_SCHEMA_VERSION,
    implementation_identity,
    normalize_opaque_process_specs,
    partition_authorized_opaque_processes,
    validate_opaque_process_rows,
)


_SMALL_EVIDENCE_HASH_LIMIT = 16 * 1024 * 1024
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PUBLIC_TRIO_TEMPLATES = (
    "quality/{pdb_id}.jsonl",
    "quality/{pdb_id}.provenance.json",
    "quality_atoms/{pdb_id}.npz",
)


@dataclass(frozen=True)
class AttemptRef:
    """一个已经由原子 inventory 冻结的精确 Stage F attempt。"""

    run_id: str
    pdb_id: str
    attempt_id: str
    stage_root: Path

    @property
    def path(self) -> Path:
        """返回 attempt 的服务器绝对路径。"""
        return self.stage_root / self.pdb_id / self.attempt_id

    @property
    def key(self) -> tuple[str, str, str]:
        """返回稳定的 run/PDB/attempt 三元键。"""
        return self.run_id, self.pdb_id, self.attempt_id


def _validate_stopped_locks(lock_root: Path, job_ids: Iterable[int]) -> None:
    """验证每个精确 job 处于 after+try 且没有 kill/pre 的停止点。"""
    for job_id in job_ids:
        for kind in ("after", "try"):
            path = lock_root / f"{kind}_lock_{job_id}"
            if not path.is_file() or path.is_symlink():
                raise RuntimeError(f"missing regular {kind} lock for job {job_id}: {path}")
        for kind in ("kill", "pre"):
            path = lock_root / f"{kind}_lock_{job_id}"
            if path.exists() or path.is_symlink():
                raise RuntimeError(f"unexpected {kind} lock for job {job_id}: {path}")


@lru_cache(maxsize=1)
def _expected_process_probe_identity() -> dict[str, str]:
    """返回当前 checkout 中受信 probe 入口和模块的内容身份。"""
    script_path = Path(__file__).resolve().parents[1] / "cli" / "stage_f_process_audit.py"
    if not script_path.is_file() or script_path.is_symlink():
        raise RuntimeError(f"process probe script must be a regular file: {script_path}")
    return implementation_identity(script_path)


def _parse_aware_time(value: Any, *, label: str) -> datetime:
    """解析必须携带时区的证据时间。"""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid process audit timestamp for {label}: {value}") from exc
    if parsed.tzinfo is None:
        raise RuntimeError(f"process audit timestamp lacks timezone for {label}: {value}")
    return parsed.astimezone(timezone.utc)


def _validate_zero_process_check(
    check: Any,
    *,
    label: str,
    expected_node: str,
    expected_scope: str,
    expected_identity: dict[str, str],
    expected_job_id: int | None = None,
    authorized_opaque_specs: Iterable[dict[str, Any]] = (),
) -> dict[str, list[dict[str, Any]]]:
    """闭合验证一个节点；只允许 controller 上精确指纹匹配的 opaque 例外。"""
    if not isinstance(check, dict):
        raise RuntimeError(f"invalid process audit check for {label}: {check}")
    command = check.get("probe_command")
    output = check.get("probe_output")
    stderr = check.get("probe_stderr")
    probe_argv = check.get("probe_argv")
    try:
        probe = json.loads(output) if isinstance(output, str) else None
    except json.JSONDecodeError:
        probe = None
    zero_count_fields = ("active_stage_f_processes", "active_inventory_or_cleanup_processes")
    zero_process_lists = ("stage_f_processes", "inventory_or_cleanup_processes")
    command_markers = ("stage_f_process_audit", "probe")
    allocation_markers = (
        "srun",
        f"--jobid={expected_job_id}",
        f"--nodelist={expected_node}",
    )
    expected_script = (
        Path(__file__).resolve().parents[1] / "cli" / "stage_f_process_audit.py"
    ).resolve()
    try:
        started_at = _parse_aware_time(check.get("started_at"), label=f"{label} started_at")
        completed_at = _parse_aware_time(check.get("completed_at"), label=f"{label} completed_at")
    except RuntimeError:
        started_at = completed_at = datetime.min.replace(tzinfo=timezone.utc)
    identity_matches = all(
        check.get(key) == expected_identity[key]
        and isinstance(probe, dict)
        and probe.get(key) == expected_identity[key]
        for key in ("probe_contract", "probe_script_sha256", "probe_module_sha256")
    )
    argv_shape_matches = (
        isinstance(probe_argv, list)
        and all(isinstance(item, str) and item for item in probe_argv)
        and (
            (expected_scope == "controller" and len(probe_argv) == 3)
            or (
                expected_scope == "allocation"
                and len(probe_argv) == 10
                and probe_argv[0] == "srun"
            )
        )
        and Path(probe_argv[-3]).name.lower().startswith("python")
        and Path(probe_argv[-2]).resolve() == expected_script
        and probe_argv[-1] == "probe"
    )
    opaque_rows = probe.get("opaque_stdin_python_processes") if isinstance(probe, dict) else None
    try:
        validated_opaque_rows = validate_opaque_process_rows(
            opaque_rows if isinstance(opaque_rows, list) else []
        )
        authorized_rows, blocking_rows = partition_authorized_opaque_processes(
            validated_opaque_rows,
            authorized_opaque_specs,
            node=expected_node,
        )
    except (TypeError, ValueError):
        authorized_rows = []
        blocking_rows = [{"error": "invalid_opaque_partition"}]
    opaque_count = len(opaque_rows) if isinstance(opaque_rows, list) else -1
    valid = (
        isinstance(expected_node, str)
        and bool(expected_node)
        and check.get("scope") == expected_scope
        and check.get("job_id") == expected_job_id
        and check.get("node") == expected_node
        and check.get("reported_node") == expected_node
        and check.get("probe_exit_code") == 0
        and started_at <= completed_at
        and argv_shape_matches
        and isinstance(command, str)
        and bool(command.strip())
        and command == shlex.join(probe_argv)
        and all(marker in command for marker in command_markers)
        and (
            expected_scope != "allocation"
            or all(marker in probe_argv for marker in allocation_markers)
        )
        and isinstance(output, str)
        and isinstance(stderr, str)
        and stderr == ""
        and _sha256_text(command) == check.get("probe_command_sha256")
        and _sha256_text(output) == check.get("probe_output_sha256")
        and _sha256_text(stderr) == check.get("probe_stderr_sha256")
        and isinstance(probe, dict)
        and probe.get("schema_version") == PROCESS_PROBE_SCHEMA_VERSION
        and probe.get("probe_contract") == PROCESS_PROBE_CONTRACT
        and probe.get("node") == expected_node
        and type(probe.get("uid")) is int
        and int(probe["uid"]) >= 0
        and identity_matches
        and all(check.get(field) == 0 and probe.get(field) == 0 for field in zero_count_fields)
        and all(
            isinstance(probe.get(field), list) and not probe[field]
            for field in zero_process_lists
        )
        and check.get("active_opaque_stdin_python_processes") == opaque_count
        and probe.get("active_opaque_stdin_python_processes") == opaque_count
        and not blocking_rows
        and check.get("scan_error_count") == 0
        and probe.get("scan_error_count") == 0
        and isinstance(probe.get("scan_errors"), list)
        and not probe["scan_errors"]
    )
    if not valid:
        raise RuntimeError(f"invalid process audit check for {label}: {check}")
    return {
        "observed": opaque_rows,
        "authorized": authorized_rows,
        "blocking": blocking_rows,
    }


def _validate_process_audit(
    process_audit_path: Path,
    expected_sha256: str,
    job_ids: list[int],
) -> dict[str, Any]:
    """验证登录节点和各 allocation 的零 writer/零 recovery 结构化证据。"""
    if not process_audit_path.is_file() or process_audit_path.is_symlink():
        raise RuntimeError(f"process audit must be a regular file: {process_audit_path}")
    payload = process_audit_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError("process audit SHA-256 mismatch")
    audit = json.loads(payload.decode("utf-8"))
    job_checks = audit.get("job_checks")
    controller_check = audit.get("controller_check")
    scheduler_snapshot = audit.get("scheduler_snapshot")
    try:
        capture_started_at = _parse_aware_time(
            audit.get("capture_started_at"),
            label="capture_started_at",
        )
        captured_at = _parse_aware_time(audit.get("captured_at"), label="captured_at")
        age_seconds = (datetime.now(timezone.utc) - capture_started_at).total_seconds()
    except RuntimeError:
        capture_started_at = captured_at = datetime.min.replace(tzinfo=timezone.utc)
        age_seconds = float("inf")
    try:
        authorized_specs = normalize_opaque_process_specs(
            audit.get("authorized_controller_opaque_specs", [])
        )
    except (TypeError, ValueError):
        authorized_specs = [{"invalid": True}]
    if (
        audit.get("schema_version") != PROCESS_AUDIT_SCHEMA_VERSION
        or audit.get("status") != "success"
        or not -60 <= age_seconds <= 900
        or sorted(int(item) for item in audit.get("job_ids", [])) != sorted(job_ids)
        or int(audit.get("active_stage_f_processes", -1)) != 0
        or int(audit.get("active_inventory_or_cleanup_processes", -1)) != 0
        or int(audit.get("active_opaque_stdin_python_processes", -1)) != 0
        or int(audit.get("scan_error_count", -1)) != 0
        or not isinstance(job_checks, dict)
        or not isinstance(controller_check, dict)
        or not isinstance(audit.get("controller_node"), str)
        or not audit["controller_node"]
        or set(job_checks) != {str(job_id) for job_id in job_ids}
        or not isinstance(audit.get("job_nodes"), dict)
        or set(audit["job_nodes"]) != {str(job_id) for job_id in job_ids}
        or audit.get("scheduler_exit_code") != 0
        or not isinstance(scheduler_snapshot, str)
        or _sha256_text(scheduler_snapshot) != audit.get("scheduler_snapshot_sha256")
    ):
        raise RuntimeError(f"process audit does not prove a stopped writer set: {audit}")
    if audit["controller_node"].split(".", 1)[0].lower() in {
        str(node).split(".", 1)[0].lower() for node in audit["job_nodes"].values()
    }:
        raise RuntimeError("process audit controller overlaps an allocation node")
    expected_identity = _expected_process_probe_identity()
    if any(audit.get(key) != value for key, value in expected_identity.items()):
        raise RuntimeError("process audit implementation identity mismatch")
    controller_node = audit["controller_node"]
    controller_partition = _validate_zero_process_check(
        controller_check,
        label="controller",
        expected_node=controller_node,
        expected_scope="controller",
        expected_identity=expected_identity,
        authorized_opaque_specs=authorized_specs,
    )
    check_times = [
        (
            _parse_aware_time(controller_check["started_at"], label="controller started_at"),
            _parse_aware_time(controller_check["completed_at"], label="controller completed_at"),
        )
    ]
    job_partitions: list[dict[str, list[dict[str, Any]]]] = []
    for job_id in job_ids:
        check = job_checks.get(str(job_id))
        expected_node = audit["job_nodes"].get(str(job_id))
        job_partition = _validate_zero_process_check(
            check,
            label=f"job {job_id}",
            expected_node=expected_node,
            expected_scope="allocation",
            expected_identity=expected_identity,
            expected_job_id=job_id,
        )
        job_partitions.append(job_partition)
        check_times.append(
            (
                _parse_aware_time(check["started_at"], label=f"job {job_id} started_at"),
                _parse_aware_time(check["completed_at"], label=f"job {job_id} completed_at"),
            )
        )
    observed_rows = [
        *controller_partition["observed"],
        *(row for partition in job_partitions for row in partition["observed"]),
    ]
    if (
        audit.get("observed_opaque_stdin_python_processes") != len(observed_rows)
        or audit.get("authorized_controller_opaque_processes")
        != controller_partition["authorized"]
        or audit.get("blocking_controller_opaque_processes")
        != controller_partition["blocking"]
        or audit.get("authorized_controller_opaque_specs") != authorized_specs
    ):
        raise RuntimeError("process audit opaque exception partition mismatch")
    if (
        capture_started_at > min(start for start, _end in check_times)
        or max(end for _start, end in check_times) > captured_at
        or captured_at < capture_started_at
    ):
        raise RuntimeError("process audit capture window is inconsistent")
    return audit


def _sha256_text(value: str) -> str:
    """按 UTF-8 对自包含命令或输出正文计算 SHA-256。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _inventory_hashes(report_dir: Path) -> dict[str, str]:
    """读取 GNU sha256sum 输出，并按 basename 返回两个 inventory 摘要。"""
    hashes: dict[str, str] = {}
    for line in (report_dir / "inventory.sha256").read_text(encoding="utf-8").splitlines():
        digest, named_path = line.split(maxsplit=1)
        name = Path(named_path.lstrip("* ")).name
        hashes[name] = digest
    expected = {"raw_inventory.tsv", "attempts.tsv"}
    if set(hashes) != expected:
        raise RuntimeError(f"inventory hash set mismatch: {sorted(hashes)}")
    return hashes


def _validate_inventory(report_dir: Path) -> dict[str, Any]:
    """只接受带完成标记、行数闭合且哈希正确的原子 inventory。"""
    done = json.loads((report_dir / "inventory.done.json").read_text(encoding="utf-8"))
    if done.get("status") != "success":
        raise RuntimeError(f"inventory is not successful: {done}")
    hashes = _inventory_hashes(report_dir)
    for name, expected in hashes.items():
        actual = sha256_file(report_dir / name)
        if actual != expected:
            raise RuntimeError(f"inventory hash mismatch for {name}: {actual} != {expected}")
    raw_lines = sum(1 for _ in (report_dir / "raw_inventory.tsv").open(encoding="utf-8"))
    attempts = sum(1 for _ in (report_dir / "attempts.tsv").open(encoding="utf-8"))
    if raw_lines != int(done["raw_lines"]) or attempts != int(done["attempts"]):
        raise RuntimeError("inventory line counts do not match completion marker")
    return {"done": done, "hashes": hashes}


def _load_attempts(root: Path, report_dir: Path, run_ids: set[str]) -> list[AttemptRef]:
    """从 inventory 加载恰为 PDB/attempt 两层的非 symlink 目录。"""
    _validate_run_ids(root, run_ids)
    attempts: list[AttemptRef] = []
    seen: set[tuple[str, str, str]] = set()
    for line in (report_dir / "attempts.tsv").read_text(encoding="utf-8").splitlines():
        run_id, relative = line.split("\t", maxsplit=1)
        parts = PurePosixPath(relative).parts
        if (
            run_id not in run_ids
            or len(parts) != 2
            or any(_SAFE_SEGMENT.fullmatch(part) is None for part in parts)
        ):
            raise RuntimeError(f"invalid attempt inventory row: {line!r}")
        ref = AttemptRef(run_id, parts[0], parts[1], root / "scratch" / run_id / "stage_f")
        if ref.key in seen:
            raise RuntimeError(f"duplicate attempt inventory row: {ref.key}")
        seen.add(ref.key)
        _validate_attempt_scope(ref)
        attempts.append(ref)
    return sorted(attempts, key=lambda item: item.key)


def _validate_run_ids(root: Path, run_ids: set[str]) -> None:
    """要求 run_id 是 scratch 根下的单一安全路径段。"""
    if not run_ids:
        raise RuntimeError("at least one run_id is required")
    for run_id in run_ids:
        run_root = root / "scratch" / run_id
        stage_root = run_root / "stage_f"
        if run_root.is_symlink() or stage_root.is_symlink():
            raise RuntimeError(f"run/stage root must not be a symlink: {stage_root}")
        _validated_stage_root(root, run_id)


@lru_cache(maxsize=None)
def _validated_stage_root(root: Path, run_id: str) -> Path:
    """缓存同一进程内不变的 run/stage canonical 边界，减少 Lustre realpath。"""
    if _SAFE_SEGMENT.fullmatch(run_id) is None:
        raise RuntimeError(f"unsafe run_id: {run_id!r}")
    scratch_root = (root / "scratch").resolve(strict=True)
    run_root = root / "scratch" / run_id
    stage_root = run_root / "stage_f"
    if run_root.is_symlink() or stage_root.is_symlink():
        raise RuntimeError(f"run/stage root must not be a symlink: {stage_root}")
    resolved_run = run_root.resolve(strict=True)
    resolved_stage = stage_root.resolve(strict=True)
    if resolved_run.parent != scratch_root or resolved_run.name != run_id:
        raise RuntimeError(f"run root escaped scratch root: {run_root} -> {resolved_run}")
    if resolved_stage != resolved_run / "stage_f":
        raise RuntimeError(f"stage root escaped run root: {stage_root} -> {resolved_stage}")
    return resolved_stage


def _validate_attempt_scope(ref: AttemptRef) -> None:
    """拒绝缺失、symlink 或 realpath 越过精确 Stage F root 的 attempt。"""
    if not ref.path.is_dir() or ref.path.is_symlink() or ref.path.parent.is_symlink():
        raise RuntimeError(f"attempt must remain a regular directory: {ref.path}")
    _validated_attempt_root(ref)


@lru_cache(maxsize=None)
def _validated_attempt_root(ref: AttemptRef) -> Path:
    """缓存一个只读恢复进程内不变的 attempt canonical 边界。"""
    attempt = ref.path
    if not attempt.is_dir() or attempt.is_symlink() or attempt.parent.is_symlink():
        raise RuntimeError(f"attempt must be a regular directory: {attempt}")
    stage_root = _validated_stage_root(ref.stage_root.parents[2], ref.run_id)
    resolved = attempt.resolve(strict=True)
    if not resolved.is_relative_to(stage_root) or resolved.parent.parent != stage_root:
        raise RuntimeError(f"attempt escaped stage root: {attempt} -> {resolved}")
    return resolved


def _path_kind(mode: int) -> str:
    """把 lstat mode 压缩为审计稳定的文件类型。"""
    if stat.S_ISREG(mode):
        return "regular"
    if stat.S_ISLNK(mode):
        return "symlink"
    return "other"


def _snapshot_path(path: Path, ref: AttemptRef, *, hash_small: bool) -> dict[str, Any]:
    """记录一个 attempt 内文件的身份、实际分配空间与可选内容哈希。"""
    attempt_root = _validated_attempt_root(ref)
    resolved = path.resolve(strict=False)
    if not resolved.is_relative_to(attempt_root):
        raise RuntimeError(f"attempt child escaped scope: {path} -> {resolved}")
    info = path.lstat()
    kind = _path_kind(info.st_mode)
    if kind not in {"regular", "symlink"}:
        raise RuntimeError(f"unsupported attempt entry type: {path}")
    relative = path.relative_to(ref.path).as_posix()
    blocks = int(getattr(info, "st_blocks", (info.st_size + 511) // 512))
    record: dict[str, Any] = {
        "run_id": ref.run_id,
        "pdb_id": ref.pdb_id,
        "attempt_id": ref.attempt_id,
        "relative_path": relative,
        "kind": kind,
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": info.st_mode,
        "size": info.st_size,
        "blocks": blocks,
        "allocated_bytes": blocks * 512,
        "mtime_ns": info.st_mtime_ns,
    }
    if kind == "symlink":
        record["symlink_target"] = os.readlink(path)
    elif hash_small and info.st_size <= _SMALL_EVIDENCE_HASH_LIMIT:
        record["sha256"] = sha256_file(path)
    return record


def _scan_attempt(
    ref: AttemptRef,
    *,
    hash_retained: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """使用与 build_quality 相同 matcher，无深度上限扫描一个 attempt。"""
    transient: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []
    for path in sorted(ref.path.rglob("*"), key=lambda item: item.as_posix()):
        if not (path.is_file() or path.is_symlink()):
            continue
        is_transient = _is_quality_attempt_transient(path)
        record = _snapshot_path(path, ref, hash_small=hash_retained and not is_transient)
        (transient if is_transient else retained).append(record)
    return transient, retained


def _add_retained_hashes(ref: AttemptRef, records: list[dict[str, Any]]) -> None:
    """只为实际含 transient 的 attempt 补充小型保留证据内容哈希。"""
    for record in records:
        if record["kind"] != "regular" or int(record["size"]) > _SMALL_EVIDENCE_HASH_LIMIT:
            continue
        path = ref.path.joinpath(*PurePosixPath(str(record["relative_path"])).parts)
        record["sha256"] = sha256_file(path)


def _trio_paths(root: Path, pdb_id: str) -> list[Path]:
    """返回一个 PDB 的三个正式 Stage F 公开产物。"""
    return [root / template.format(pdb_id=pdb_id) for template in _PUBLIC_TRIO_TEMPLATES]


def _has_public_trio(root: Path, pdb_id: str) -> bool:
    """只把三个 regular non-symlink 文件同时存在记为 public trio。"""
    return all(path.is_file() and not path.is_symlink() for path in _trio_paths(root, pdb_id))


def _snapshot_public_trio(root: Path, pdb_ids: set[str]) -> list[dict[str, Any]]:
    """对将被回收 scratch 的 PDB 冻结正式三件套内容哈希。"""
    records: list[dict[str, Any]] = []
    for pdb_id in sorted(pdb_ids):
        for path in _trio_paths(root, pdb_id):
            exists = path.is_file() and not path.is_symlink()
            record: dict[str, Any] = {
                "pdb_id": pdb_id,
                "path": path.relative_to(root).as_posix(),
                "exists": exists,
            }
            if exists:
                info = path.stat()
                record.update(
                    size=info.st_size,
                    mtime_ns=info.st_mtime_ns,
                    sha256=sha256_file(path),
                )
            records.append(record)
    return records


def _summarize_values(values: list[int]) -> dict[str, int | float]:
    """汇总 count/sum/median/max；空组返回全零。"""
    if not values:
        return {"count": 0, "sum": 0, "median": 0, "max": 0}
    return {
        "count": len(values),
        "sum": sum(values),
        "median": median(values),
        "max": max(values),
    }


def _raw_inventory_summary(report_dir: Path) -> dict[str, Any]:
    """流式统计原始 regular-file inventory 的逻辑与实际分配空间。"""
    groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: {"logical": [], "allocated": []})
    nontransient_top: list[tuple[int, str, str]] = []
    with (report_dir / "raw_inventory.tsv").open(encoding="utf-8") as handle:
        for line in handle:
            run_id, relative, size_text, blocks_text, _mtime = line.rstrip("\n").split("\t")
            path = Path(relative)
            if _is_quality_attempt_transient(path):
                group = f"transient:{_transient_type(path)}"
            else:
                suffix = path.suffix.lower() or "<no_suffix>"
                group = f"retained:{suffix}"
            logical = int(size_text)
            allocated = int(blocks_text) * 512
            groups[group]["logical"].append(logical)
            groups[group]["allocated"].append(allocated)
            if group.startswith("retained:"):
                nontransient_top.append((allocated, run_id, relative))
    return {
        "by_type": {
            name: {
                "logical_bytes": _summarize_values(values["logical"]),
                "allocated_bytes": _summarize_values(values["allocated"]),
            }
            for name, values in sorted(groups.items())
        },
        "largest_retained_files": [
            {"allocated_bytes": size, "run_id": run_id, "relative_path": path}
            for size, run_id, path in sorted(nontransient_top, reverse=True)[:20]
        ],
    }


def _raw_transient_attempts(
    report_dir: Path,
    run_ids: set[str],
) -> dict[tuple[str, str, str], set[str]]:
    """由已哈希 raw inventory 定位需要无限深度复核的候选 attempt。"""
    candidates: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    with (report_dir / "raw_inventory.tsv").open(encoding="utf-8") as handle:
        for line in handle:
            run_id, relative, _size, _blocks, _mtime = line.rstrip("\n").split("\t")
            parts = PurePosixPath(relative).parts
            if run_id not in run_ids or len(parts) < 3:
                raise RuntimeError(f"invalid raw inventory path: {run_id}:{relative}")
            if _is_quality_attempt_transient(Path(relative)):
                key = run_id, parts[0], parts[1]
                candidates[key].add(PurePosixPath(*parts[2:]).as_posix())
    return candidates


def _transient_type(path: Path) -> str:
    """按原子临时标记优先、最终 suffix 次之分组大型中间体。"""
    name = path.name.lower()
    for marker in (".cif.tmp.", ".map.tmp.", ".mrc.tmp."):
        if marker in name:
            return marker.strip(".").replace(".", "_")
    return path.suffix.lower().lstrip(".")


def _classification_summary(
    attempts: list[AttemptRef],
    transient_by_attempt: dict[tuple[str, str, str], list[dict[str, Any]]],
    root: Path,
) -> dict[str, Any]:
    """按是否有 transient 与当前 PDB 是否有公开三件套做非归因分类。"""
    counts: Counter[str] = Counter()
    allocated: Counter[str] = Counter()
    recent: dict[str, list[dict[str, Any]]] = {}
    trio_cache: dict[str, bool] = {}
    for ref in attempts:
        rows = transient_by_attempt.get(ref.key, [])
        state = "has_transient" if rows else "small_only"
        if ref.pdb_id not in trio_cache:
            trio_cache[ref.pdb_id] = _has_public_trio(root, ref.pdb_id)
        has_trio = trio_cache[ref.pdb_id]
        trio = "public_trio" if has_trio else "no_public_trio"
        key = f"{state}+{trio}"
        counts[key] += 1
        allocated[key] += sum(int(row["allocated_bytes"]) for row in rows)
    for run_id in sorted({ref.run_id for ref in attempts}):
        candidates: list[tuple[int, tuple[str, str, str], int]] = []
        for key, rows in transient_by_attempt.items():
            if key[0] == run_id and rows:
                candidates.append(
                    (
                        max(int(row["mtime_ns"]) for row in rows),
                        key,
                        sum(int(row["allocated_bytes"]) for row in rows),
                    )
                )
        recent[run_id] = [
            {
                "pdb_id": key[1],
                "attempt_id": key[2],
                "newest_transient_mtime_ns": mtime_ns,
                "allocated_bytes": size,
                "label": "recent_at_cutoff_candidate_not_proven_active",
            }
            for mtime_ns, key, size in sorted(candidates, reverse=True)[:12]
        ]
    return {
        "attempt_counts": dict(sorted(counts.items())),
        "transient_allocated_bytes": dict(sorted(allocated.items())),
        "recent_at_cutoff_candidates": recent,
    }


def _build_scratch_audit_locked(
    root: Path,
    report_dir: Path,
    *,
    run_ids: set[str],
    lock_root: Path,
    job_ids: list[int],
    process_audit_path: Path,
    expected_process_audit_sha256: str,
) -> dict[str, Any]:
    """生成权威 delete/nontransient/public-trio manifest，但不删除任何文件。"""
    owned_outputs = (
        "delete_manifest.jsonl",
        "nontransient_manifest.jsonl",
        "public_trio_manifest.jsonl",
        "audit_summary.json",
        "audit_bundle.json",
        "apply.started.json",
        "apply_progress.jsonl",
        "apply_summary.json",
    )
    existing = [name for name in owned_outputs if (report_dir / name).exists()]
    if existing:
        raise RuntimeError(f"scratch audit output already exists; use a new report directory: {existing}")
    _validate_stopped_locks(lock_root, job_ids)
    process_audit = _validate_process_audit(
        process_audit_path,
        expected_process_audit_sha256,
        job_ids,
    )
    inventory = _validate_inventory(report_dir)
    attempts = _load_attempts(root, report_dir, run_ids)
    attempts_by_key = {ref.key: ref for ref in attempts}
    raw_candidates = _raw_transient_attempts(report_dir, run_ids)
    unknown_candidates = sorted(set(raw_candidates).difference(attempts_by_key))
    if unknown_candidates:
        raise RuntimeError(f"raw inventory references unknown attempts: {unknown_candidates[:10]}")
    delete_records: list[dict[str, Any]] = []
    retained_records: list[dict[str, Any]] = []
    transient_by_attempt: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    affected_pdb_ids: set[str] = set()
    for key in sorted(raw_candidates):
        ref = attempts_by_key[key]
        transient, retained = _scan_attempt(ref)
        discovered = {str(row["relative_path"]) for row in transient}
        missing_raw = sorted(raw_candidates[key].difference(discovered))
        if missing_raw:
            raise RuntimeError(f"raw transient disappeared before audit for {key}: {missing_raw[:10]}")
        transient_by_attempt[ref.key] = transient
        delete_records.extend(transient)
        if transient:
            _add_retained_hashes(ref, retained)
            retained_records.extend(retained)
            affected_pdb_ids.add(ref.pdb_id)
    trio_records = _snapshot_public_trio(root, affected_pdb_ids)
    _validate_stopped_locks(lock_root, job_ids)
    write_jsonl(report_dir / "delete_manifest.jsonl", delete_records)
    write_jsonl(report_dir / "nontransient_manifest.jsonl", retained_records)
    write_jsonl(report_dir / "public_trio_manifest.jsonl", trio_records)
    manifest_hashes = {
        name: sha256_file(report_dir / name)
        for name in (
            "delete_manifest.jsonl",
            "nontransient_manifest.jsonl",
            "public_trio_manifest.jsonl",
        )
    }
    summary = {
        "schema_version": 1,
        "status": "audit_complete_no_delete",
        "run_ids": sorted(run_ids),
        "job_ids": sorted(job_ids),
        "current_active_attempts": 0,
        "current_active_basis": {
            "process_audit_path": str(process_audit_path),
            "process_audit_sha256": expected_process_audit_sha256,
            "process_audit": process_audit,
        },
        "inventory": inventory,
        "attempts": len(attempts),
        "delete_files": len(delete_records),
        "delete_logical_bytes": sum(int(row["size"]) for row in delete_records),
        "delete_allocated_bytes": sum(int(row["allocated_bytes"]) for row in delete_records),
        "affected_attempts": sum(bool(rows) for rows in transient_by_attempt.values()),
        "affected_pdb_ids": len(affected_pdb_ids),
        "authoritative_scan_coverage": {
            "raw_regular_file_depth": "3..6 under stage_f",
            "candidate_attempts_scanned_without_depth_limit": len(raw_candidates),
            "noncandidate_attempts_not_rescanned": len(attempts) - len(raw_candidates),
            "basis": "quality.py creates transient regular files within raw inventory depth and creates no symlinks",
        },
        "classification": _classification_summary(attempts, transient_by_attempt, root),
        "raw_inventory_summary": _raw_inventory_summary(report_dir),
        "manifest_sha256": manifest_hashes,
    }
    write_report(report_dir / "audit_summary.json", summary)
    bundle = {
        "schema_version": 1,
        "run_ids": sorted(run_ids),
        "job_ids": sorted(job_ids),
        "inventory_sha256": inventory["hashes"],
        "manifest_sha256": manifest_hashes,
        "audit_summary_sha256": sha256_file(report_dir / "audit_summary.json"),
        "audit_process_sha256": expected_process_audit_sha256,
        "authorized_controller_opaque_specs": process_audit[
            "authorized_controller_opaque_specs"
        ],
    }
    write_report(report_dir / "audit_bundle.json", bundle)
    return summary


def build_scratch_audit(
    root: Path,
    report_dir: Path,
    *,
    run_ids: set[str],
    lock_root: Path,
    job_ids: list[int],
    process_audit_path: Path,
    expected_process_audit_sha256: str,
) -> dict[str, Any]:
    """以 report-scoped 独占锁生成一次不可覆盖的 scratch audit。"""
    report_dir.mkdir(parents=True, exist_ok=True)
    with file_lock(report_dir / "audit.lock"):
        return _build_scratch_audit_locked(
            root,
            report_dir,
            run_ids=run_ids,
            lock_root=lock_root,
            job_ids=job_ids,
            process_audit_path=process_audit_path,
            expected_process_audit_sha256=expected_process_audit_sha256,
        )


def _manifest_record_path(root: Path, record: dict[str, Any]) -> tuple[AttemptRef, Path]:
    """从 manifest 行重建精确路径，并再次执行 attempt scope 校验。"""
    run_id = str(record["run_id"])
    pdb_id = str(record["pdb_id"])
    attempt_id = str(record["attempt_id"])
    _validate_run_ids(root, {run_id})
    if _SAFE_SEGMENT.fullmatch(pdb_id) is None or _SAFE_SEGMENT.fullmatch(attempt_id) is None:
        raise RuntimeError(f"unsafe manifest attempt identity: {(run_id, pdb_id, attempt_id)}")
    ref = AttemptRef(
        run_id,
        pdb_id,
        attempt_id,
        root / "scratch" / run_id / "stage_f",
    )
    _validate_attempt_scope(ref)
    relative_text = str(record["relative_path"])
    relative = PurePosixPath(relative_text)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or "\\" in relative_text
        or any(part.endswith(":") for part in relative.parts)
    ):
        raise RuntimeError(f"invalid manifest relative path: {relative}")
    path = ref.path.joinpath(*relative.parts)
    if not path.resolve(strict=False).is_relative_to(_validated_attempt_root(ref)):
        raise RuntimeError(f"manifest path escaped attempt: {path}")
    return ref, path


def _assert_snapshot(root: Path, record: dict[str, Any]) -> None:
    """要求文件身份、空间、时间、symlink target 和小文件内容均未漂移。"""
    _ref, path = _manifest_record_path(root, record)
    if not (path.exists() or path.is_symlink()):
        raise RuntimeError(f"manifest path disappeared: {path}")
    info = path.lstat()
    for key, actual in (
        ("device", info.st_dev),
        ("inode", info.st_ino),
        ("mode", info.st_mode),
        ("size", info.st_size),
        ("blocks", int(getattr(info, "st_blocks", (info.st_size + 511) // 512))),
        ("mtime_ns", info.st_mtime_ns),
    ):
        if int(record[key]) != int(actual):
            raise RuntimeError(f"manifest metadata drift for {path}: {key}")
    if record["kind"] == "symlink" and record.get("symlink_target") != os.readlink(path):
        raise RuntimeError(f"manifest symlink drift for {path}")
    if "sha256" in record and sha256_file(path) != record["sha256"]:
        raise RuntimeError(f"manifest content drift for {path}")


def _assert_public_trio(root: Path, records: list[dict[str, Any]]) -> None:
    """要求 scratch 回收涉及的所有公开质量三件套逐字节不变。"""
    for record in records:
        path = root / str(record["path"])
        exists = path.is_file() and not path.is_symlink()
        if exists != bool(record["exists"]):
            raise RuntimeError(f"public trio existence drift: {path}")
        if exists:
            info = path.stat()
            if (
                info.st_size != int(record["size"])
                or info.st_mtime_ns != int(record["mtime_ns"])
                or sha256_file(path) != record["sha256"]
            ):
                raise RuntimeError(f"public trio content drift: {path}")


def _record_key(record: dict[str, Any]) -> tuple[str, str, str, str]:
    """返回 journal 与 manifest 共用的稳定文件键。"""
    return (
        str(record["run_id"]),
        str(record["pdb_id"]),
        str(record["attempt_id"]),
        str(record["relative_path"]),
    )


def _validate_audit_bundle(
    report_dir: Path,
    expected_sha256: str,
    run_ids: set[str],
    job_ids: list[int],
) -> dict[str, Any]:
    """把 inventory、三个 manifest 与 audit summary 绑定为不可混批的证据包。"""
    bundle_path = report_dir / "audit_bundle.json"
    payload = bundle_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError("audit bundle SHA-256 mismatch")
    bundle = json.loads(payload.decode("utf-8"))
    if bundle.get("run_ids") != sorted(run_ids) or bundle.get("job_ids") != sorted(job_ids):
        raise RuntimeError("audit bundle run/job identity mismatch")
    for name, expected in bundle["inventory_sha256"].items():
        if sha256_file(report_dir / name) != expected:
            raise RuntimeError(f"audit bundle inventory drift: {name}")
    for name, expected in bundle["manifest_sha256"].items():
        if sha256_file(report_dir / name) != expected:
            raise RuntimeError(f"audit bundle manifest drift: {name}")
    if sha256_file(report_dir / "audit_summary.json") != bundle["audit_summary_sha256"]:
        raise RuntimeError("audit summary drift")
    return bundle


def _read_bound_jsonl(path: Path, expected_sha256: str) -> list[dict[str, Any]]:
    """一次读取同一字节快照，先验哈希再解析 JSONL。"""
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise RuntimeError(f"bound JSONL hash mismatch: {path}")
    records: list[dict[str, Any]] = []
    for line in payload.decode("utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise RuntimeError(f"bound JSONL row is not an object: {path}")
            records.append(record)
    return records


def _write_fsynced_json_once(path: Path, payload: dict[str, Any]) -> None:
    """一次性写入、fsync 并原子提升硬中断恢复证据。"""
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise RuntimeError(f"existing recovery evidence differs: {path}")
        return
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    try:
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        if os.name != "nt":
            raise


def _recover_truncated_journal_tail(path: Path, payload: bytes, report_dir: Path) -> bytes:
    """保存未换行尾部原始字节后，只截断该尾部；中间内容不修复。"""
    last_newline = payload.rfind(b"\n")
    complete = payload[: last_newline + 1] if last_newline >= 0 else b""
    tail = payload[last_newline + 1 :]
    original_sha256 = hashlib.sha256(payload).hexdigest()
    evidence_path = report_dir / f"journal_tail_recovery_{original_sha256[:16]}.json"
    _write_fsynced_json_once(
        evidence_path,
        {
            "schema_version": 1,
            "status": "truncated_tail_frozen_before_repair",
            "journal_path": str(path),
            "original_size": len(payload),
            "original_sha256": original_sha256,
            "complete_prefix_size": len(complete),
            "complete_prefix_sha256": hashlib.sha256(complete).hexdigest(),
            "tail_size": len(tail),
            "tail_sha256": hashlib.sha256(tail).hexdigest(),
            "tail_hex": tail.hex(),
        },
    )
    with path.open("r+b") as handle:
        handle.truncate(len(complete))
        handle.flush()
        os.fsync(handle.fileno())
    return complete


def _load_progress(path: Path, report_dir: Path) -> dict[tuple[str, str, str, str], str]:
    """读取 journal；只受检修复最后一条无换行尾部，中间坏行 fail-closed。"""
    states: dict[tuple[str, str, str, str], str] = {}
    if not path.exists():
        return states
    payload = path.read_bytes()
    if payload and not payload.endswith(b"\n"):
        payload = _recover_truncated_journal_tail(path, payload, report_dir)
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(payload.splitlines(), start=1):
        try:
            record = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid complete cleanup journal line {line_number}") from exc
        if not isinstance(record, dict):
            raise RuntimeError(f"cleanup journal line {line_number} is not an object")
        records.append(record)
    for record in records:
        key = _record_key(record)
        event = str(record["event"])
        previous = states.get(key)
        if event == "intent" and previous is None:
            states[key] = event
        elif event in {"deleted", "recovered_deleted"} and previous == "intent":
            states[key] = event
        else:
            raise RuntimeError(f"invalid cleanup journal transition for {key}: {previous} -> {event}")
    return states


def _append_progress(path: Path, record: dict[str, Any]) -> None:
    """追加一条逐文件 journal 并立即 fsync。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _assert_affected_delete_set(
    root: Path,
    expected_records: list[dict[str, Any]],
    progress: dict[tuple[str, str, str, str], str],
) -> set[tuple[str, str, str]]:
    """只重扫受影响 attempt，要求 live matcher 等于 journal 尚未完成的 manifest。"""
    refs: dict[tuple[str, str, str], AttemptRef] = {}
    for record in expected_records:
        ref, _path = _manifest_record_path(root, record)
        refs[ref.key] = ref
    actual_keys: set[tuple[str, str, str, str]] = set()
    for key, ref in sorted(refs.items()):
        transient, _retained = _scan_attempt(ref)
        actual_keys.update((*key, str(row["relative_path"])) for row in transient)
    expected_live = {
        _record_key(record)
        for record in expected_records
        if progress.get(_record_key(record)) not in {"deleted", "recovered_deleted"}
        and (
            progress.get(_record_key(record)) != "intent"
            or (_manifest_record_path(root, record)[1].exists() or _manifest_record_path(root, record)[1].is_symlink())
        )
    }
    if actual_keys != expected_live:
        raise RuntimeError(
            "affected delete set drift: "
            f"missing={sorted(expected_live - actual_keys)[:10]} "
            f"new={sorted(actual_keys - expected_live)[:10]}"
        )
    return set(refs)


def _write_apply_failure(report_dir: Path, exc: BaseException, progress_path: Path) -> None:
    """尽力原子记录半途失败；原异常仍由调用方抛出。"""
    try:
        write_report(
            report_dir / "apply.failed.json",
            {
                "schema_version": 1,
                "status": "failed",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "progress_sha256": sha256_file(progress_path) if progress_path.exists() else None,
            },
        )
    except OSError:
        pass


def _apply_scratch_cleanup_locked(
    root: Path,
    report_dir: Path,
    *,
    run_ids: set[str],
    lock_root: Path,
    job_ids: list[int],
    expected_audit_bundle_sha256: str,
    process_audit_path: Path,
    expected_process_audit_sha256: str,
) -> dict[str, Any]:
    """按已审计 manifest 精确清理 transient，并证明保留文件与正式产物不变。"""
    _validate_stopped_locks(lock_root, job_ids)
    process_audit = _validate_process_audit(
        process_audit_path,
        expected_process_audit_sha256,
        job_ids,
    )
    bundle = _validate_audit_bundle(
        report_dir,
        expected_audit_bundle_sha256,
        run_ids,
        job_ids,
    )
    if (
        process_audit.get("authorized_controller_opaque_specs")
        != bundle.get("authorized_controller_opaque_specs")
    ):
        raise RuntimeError("apply process exception differs from audit process exception")
    delete_path = report_dir / "delete_manifest.jsonl"
    actual_manifest_sha256 = bundle["manifest_sha256"]["delete_manifest.jsonl"]
    delete_records = _read_bound_jsonl(delete_path, actual_manifest_sha256)
    retained_records = _read_bound_jsonl(
        report_dir / "nontransient_manifest.jsonl",
        bundle["manifest_sha256"]["nontransient_manifest.jsonl"],
    )
    trio_records = _read_bound_jsonl(
        report_dir / "public_trio_manifest.jsonl",
        bundle["manifest_sha256"]["public_trio_manifest.jsonl"],
    )
    progress_path = report_dir / "apply_progress.jsonl"
    started_path = report_dir / "apply.started.json"
    if progress_path.exists() and not started_path.exists():
        raise RuntimeError("cleanup journal exists without apply.started evidence")
    if started_path.exists():
        started = json.loads(started_path.read_text(encoding="utf-8"))
        if started.get("audit_bundle_sha256") != expected_audit_bundle_sha256:
            raise RuntimeError("existing apply evidence belongs to another audit bundle")
    else:
        write_report(
            started_path,
            {
                "schema_version": 1,
                "status": "preflight_started",
                "audit_bundle_sha256": expected_audit_bundle_sha256,
                "delete_manifest_sha256": actual_manifest_sha256,
                "job_ids": sorted(job_ids),
                "process_audit": process_audit,
                "process_audit_sha256": expected_process_audit_sha256,
                "delete_files": len(delete_records),
            },
        )
    progress = _load_progress(progress_path, report_dir)
    delete_keys = [_record_key(record) for record in delete_records]
    if len(delete_keys) != len(set(delete_keys)):
        raise RuntimeError("delete manifest contains duplicate paths")
    unknown_progress = sorted(set(progress).difference(delete_keys))
    if unknown_progress:
        raise RuntimeError(f"cleanup journal contains paths outside manifest: {unknown_progress[:10]}")
    try:
        affected_attempts = _assert_affected_delete_set(root, delete_records, progress)
        for record in delete_records:
            state = progress.get(_record_key(record))
            _ref, path = _manifest_record_path(root, record)
            if state in {"deleted", "recovered_deleted"}:
                if path.exists() or path.is_symlink():
                    raise RuntimeError(f"journal says deleted but path exists: {path}")
            elif state == "intent" and not (path.exists() or path.is_symlink()):
                _append_progress(progress_path, {**record, "event": "recovered_deleted"})
                progress[_record_key(record)] = "recovered_deleted"
            else:
                _assert_snapshot(root, record)
        for record in retained_records:
            _assert_snapshot(root, record)
        _assert_public_trio(root, trio_records)
        for record in sorted(delete_records, key=_record_key):
            key = _record_key(record)
            state = progress.get(key)
            if state in {"deleted", "recovered_deleted"}:
                continue
            _validate_stopped_locks(lock_root, job_ids)
            _ref, path = _manifest_record_path(root, record)
            if state is None:
                _assert_snapshot(root, record)
                _append_progress(progress_path, {**record, "event": "intent"})
                progress[key] = "intent"
            _validate_stopped_locks(lock_root, job_ids)
            _assert_snapshot(root, record)
            if not _is_quality_attempt_transient(path):
                raise RuntimeError(f"manifest path is no longer transient: {path}")
            path.unlink()
            _append_progress(progress_path, {**record, "event": "deleted"})
            progress[key] = "deleted"
        for key in sorted(affected_attempts):
            ref = AttemptRef(key[0], key[1], key[2], root / "scratch" / key[0] / "stage_f")
            transient, _retained = _scan_attempt(ref)
            if transient:
                raise RuntimeError(f"transient remains after cleanup: {key}")
        for record in retained_records:
            _assert_snapshot(root, record)
        _assert_public_trio(root, trio_records)
    except BaseException as exc:
        _write_apply_failure(report_dir, exc, progress_path)
        raise
    summary = {
        "schema_version": 1,
        "status": "success",
        "delete_manifest_sha256": actual_manifest_sha256,
        "removed_files": len(delete_records),
        "audit_bundle_sha256": expected_audit_bundle_sha256,
        "affected_attempts": len(affected_attempts),
        "reclaimed_allocated_bytes_expected": sum(int(row["allocated_bytes"]) for row in delete_records),
        "nontransient_files_verified": len(retained_records),
        "public_trio_paths_verified": len(trio_records),
        "progress_sha256": sha256_file(progress_path),
    }
    write_report(report_dir / "apply_summary.json", summary)
    return summary


def apply_scratch_cleanup(
    root: Path,
    report_dir: Path,
    *,
    run_ids: set[str],
    lock_root: Path,
    job_ids: list[int],
    expected_audit_bundle_sha256: str,
    process_audit_path: Path,
    expected_process_audit_sha256: str,
) -> dict[str, Any]:
    """以 report-scoped 独占锁执行可续跑的逐 manifest 回收。"""
    with file_lock(report_dir / "apply.lock"):
        return _apply_scratch_cleanup_locked(
            root,
            report_dir,
            run_ids=run_ids,
            lock_root=lock_root,
            job_ids=job_ids,
            expected_audit_bundle_sha256=expected_audit_bundle_sha256,
            process_audit_path=process_audit_path,
            expected_process_audit_sha256=expected_process_audit_sha256,
        )
