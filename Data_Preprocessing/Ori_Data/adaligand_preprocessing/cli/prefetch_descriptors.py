# 按固定对象清单预取 Stage C 描述符的命令入口。
# 实际逻辑：调用 Stage C 描述子维护模块补足依赖并生成审计证据。
# 输入/输出：object-key 清单与 cache → descriptor 状态；不直接改变正式 occurrence 产物。
# 关键边界：只传播 CLI 配置，不能把补足成功等同于 Stage C release 成功。
"""按冻结 object-key 清单补足 ligand descriptor，并写入 run-scoped 证据。"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from joblib import Parallel, delayed



from adaligand_preprocessing.ops.stage_c_descriptors import (
    DESCRIPTOR_PREFETCH_SCHEMA_VERSION,
    materialize_and_audit_descriptor,
    validate_descriptor_object_key,
)
from adaligand_preprocessing.utils.io import safe_object_filename, sha256_file, write_jsonl
from adaligand_preprocessing.artifacts.reports import resolve_run_id, write_report


def main() -> None:
    """补足冻结清单中的 descriptor；任一失败均保留证据并以非零状态退出。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--object_keys_file", type=Path, required=True)
    parser.add_argument("--keys_sha256", required=True)
    parser.add_argument("--expected_count", type=int, required=True)
    parser.add_argument("--run_id", required=True)
    parser.add_argument("--n_jobs", type=int, required=True)
    args = parser.parse_args()
    args.run_id = resolve_run_id(args.run_id)

    object_keys, keys_sha256 = _frozen_object_keys(
        args.object_keys_file,
        args.keys_sha256,
        args.expected_count,
    )
    report_dir = (
        args.root
        / "reports"
        / "runs"
        / args.run_id
        / "stage_c_descriptor_prefetch"
    )
    records_path = report_dir / "records.jsonl"
    summary_path = report_dir / "summary.json"
    implementation_files = _implementation_hashes()
    if _reuse_success_evidence(
        args.root,
        records_path,
        summary_path,
        args.run_id,
        str(args.object_keys_file),
        object_keys,
        keys_sha256,
        implementation_files,
    ):
        return

    records = Parallel(n_jobs=args.n_jobs, backend="loky", verbose=10)(
        delayed(_materialize_one)(args.root, object_key)
        for object_key in object_keys
    )
    write_jsonl(records_path, records)
    counts = Counter(str(record["status"]) for record in records)
    implementation_files_after = _implementation_hashes()
    implementation_stable = implementation_files_after == implementation_files
    success = (
        counts == Counter({"success": len(object_keys)})
        and implementation_stable
    )
    summary = {
        "status": "success" if success else "failed",
        "schema_version": DESCRIPTOR_PREFETCH_SCHEMA_VERSION,
        "run_id": args.run_id,
        "object_keys_path": str(args.object_keys_file),
        "object_keys_sha256": keys_sha256,
        "object_key_count": len(object_keys),
        "n_records": len(records),
        "counts": dict(sorted(counts.items())),
        "records_sha256": sha256_file(records_path),
        "implementation_files": implementation_files,
        "implementation_stable": implementation_stable,
        "policy": (
            "run-scoped dependency supplement only; writes frozen-key global "
            "ligand_descriptors with overwrite=False, does not write per-PDB parse/ "
            "artifacts, and does not alter the science schema"
        ),
    }
    if not implementation_stable:
        summary["implementation_files_after"] = implementation_files_after
    write_report(summary_path, summary)
    if not success:
        raise RuntimeError(
            "descriptor prefetch failed: "
            f"counts={dict(sorted(counts.items()))}, "
            f"implementation_stable={implementation_stable}"
        )


def _frozen_object_keys(
    path: Path,
    expected_hash: str,
    expected_count: int,
) -> tuple[list[str], str]:
    """
    从同一份已哈希字节解析规范 object key，并验证数量、重复项和文件名碰撞。

    输入参数:
        - path: Path, UTF-8 object-key 清单，每行一个键
        - expected_hash: str, 清单原始字节的预期 SHA-256
        - expected_count: int, 清单中唯一合法键的预期数量

    输出:
        - result: tuple[list[str], str], 包含:
            - object_keys: list[str], 按字典序排列的冻结 object key
            - actual_hash: str, 清单原始字节的 SHA-256
    """
    payload = path.read_bytes()
    actual_hash = hashlib.sha256(payload).hexdigest()
    if actual_hash != expected_hash.lower():
        raise RuntimeError(
            f"object keys sha256 {actual_hash} != expected {expected_hash}"
        )
    try:
        lines = payload.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError(f"object keys file must be UTF-8: {path}") from exc
    if not lines or any(not line for line in lines):
        raise ValueError(f"object keys file contains an empty row: {path}")
    object_keys = [validate_descriptor_object_key(line) for line in lines]
    if len(object_keys) != len(set(object_keys)):
        raise ValueError(f"duplicate object keys in {path}")
    safe_names = [safe_object_filename(object_key) for object_key in object_keys]
    if len(safe_names) != len(set(safe_names)):
        raise ValueError(f"object keys collide after filename escaping in {path}")
    if len(object_keys) != expected_count:
        raise RuntimeError(
            f"object keys count {len(object_keys)} != expected {expected_count}"
        )
    return sorted(object_keys), actual_hash


def _materialize_one(root: Path, object_key: str) -> dict:
    """将单个依赖异常转为完整 failed record，供批次汇总后统一阻断。"""
    try:
        return materialize_and_audit_descriptor(root, object_key)
    except Exception as exc:
        safe_key = safe_object_filename(object_key)
        object_path = root / "ligand_objects" / f"{safe_key}.npz"
        descriptor_path = root / "ligand_descriptors" / f"{safe_key}.npz"
        return {
            "status": "failed",
            "object_key": object_key,
            "action": "failed",
            "ligand_object_path": object_path.relative_to(root).as_posix(),
            "ligand_object_sha256": (
                sha256_file(object_path) if object_path.is_file() else None
            ),
            "descriptor_path": descriptor_path.relative_to(root).as_posix(),
            "descriptor_sha256": (
                sha256_file(descriptor_path) if descriptor_path.is_file() else None
            ),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "schema_version": DESCRIPTOR_PREFETCH_SCHEMA_VERSION,
        }


def _reuse_success_evidence(
    root: Path,
    records_path: Path,
    summary_path: Path,
    expected_run_id: str,
    expected_keys_path: str,
    expected_keys: list[str],
    expected_keys_sha256: str,
    implementation_files: dict[str, str],
) -> bool:
    """
    复核并复用同一 run id 的成功证据，拒绝覆盖失败或半写入证据。

    输入参数:
        - root: Path, Stage root
        - records_path: Path, 既有 records JSONL 路径
        - summary_path: Path, 既有 summary JSON 路径
        - expected_run_id: str, 当前 CLI 已验证的 run id
        - expected_keys_path: str, 当前 CLI 使用的冻结清单路径字符串
        - expected_keys: list[str], 本次冻结输入解析出的 object key
        - expected_keys_sha256: str, 本次冻结输入文件 SHA-256
        - implementation_files: dict[str, str], 当前实现文件及 SHA-256

    输出:
        - reused: bool, 既有证据完整且所有依赖仍与记录一致时为 True
    """
    if not records_path.exists() and not summary_path.exists():
        return False
    if not records_path.is_file() or not summary_path.is_file():
        raise RuntimeError(
            "descriptor prefetch evidence is incomplete; use a fresh run_id"
        )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "success":
        raise RuntimeError(
            "refusing to overwrite non-success descriptor prefetch evidence; "
            "use a fresh run_id"
        )
    if summary.get("schema_version") != DESCRIPTOR_PREFETCH_SCHEMA_VERSION:
        raise RuntimeError("descriptor prefetch evidence schema mismatch")
    if summary.get("run_id") != expected_run_id:
        raise RuntimeError("descriptor prefetch evidence run-id mismatch")
    if summary.get("object_keys_path") != expected_keys_path:
        raise RuntimeError("descriptor prefetch frozen-key path mismatch")
    if summary.get("object_keys_sha256") != expected_keys_sha256:
        raise RuntimeError("descriptor prefetch frozen-key hash mismatch")
    if summary.get("object_key_count") != len(expected_keys):
        raise RuntimeError("descriptor prefetch frozen-key count mismatch")
    if summary.get("n_records") != len(expected_keys):
        raise RuntimeError("descriptor prefetch evidence record count mismatch")
    if summary.get("counts") != {"success": len(expected_keys)}:
        raise RuntimeError("descriptor prefetch evidence status counts mismatch")
    if summary.get("implementation_stable") is not True:
        raise RuntimeError("descriptor prefetch evidence implementation was unstable")
    if summary.get("implementation_files") != implementation_files:
        raise RuntimeError(
            "descriptor prefetch implementation changed; use a fresh run_id"
        )
    payload = records_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != summary.get("records_sha256"):
        raise RuntimeError("descriptor prefetch records hash mismatch")
    records = _read_jsonl_bytes(payload, records_path)
    record_keys = [str(record.get("object_key")) for record in records]
    if (
        len(record_keys) != len(set(record_keys))
        or set(record_keys) != set(expected_keys)
        or len(records) != len(expected_keys)
    ):
        raise RuntimeError("descriptor prefetch records do not match frozen keys")
    for record in records:
        if (
            record.get("status") != "success"
            or record.get("action") not in {"materialized", "reused"}
            or record.get("schema_version") != DESCRIPTOR_PREFETCH_SCHEMA_VERSION
        ):
            raise RuntimeError("descriptor prefetch success evidence contains failure")
        safe_key = safe_object_filename(str(record["object_key"]))
        expected_object_path = f"ligand_objects/{safe_key}.npz"
        expected_descriptor_path = f"ligand_descriptors/{safe_key}.npz"
        if record.get("ligand_object_path") != expected_object_path:
            raise RuntimeError(
                "descriptor prefetch LigandObject path does not match object key"
            )
        if record.get("descriptor_path") != expected_descriptor_path:
            raise RuntimeError(
                "descriptor prefetch output path does not match object key"
            )
        _verify_recorded_file(
            root,
            expected_object_path,
            str(record["ligand_object_sha256"]),
        )
        _verify_recorded_file(
            root,
            expected_descriptor_path,
            str(record["descriptor_sha256"]),
        )
    return True


def _verify_recorded_file(root: Path, relative_path: str, expected_hash: str) -> None:
    """复核证据中一个 Stage-root 相对文件的边界与内容哈希。"""
    root_resolved = root.resolve()
    path = (root / relative_path).resolve()
    try:
        path.relative_to(root_resolved)
    except ValueError as exc:
        raise RuntimeError(
            f"descriptor prefetch evidence path escapes Stage root: {relative_path}"
        ) from exc
    if not path.is_file() or sha256_file(path) != expected_hash:
        raise RuntimeError(
            f"descriptor prefetch dependency changed after success: {relative_path}"
        )


def _read_jsonl_bytes(payload: bytes, source: Path) -> list[dict]:
    """从已哈希 JSONL 字节解析对象列表，不重新读取可变文件。"""
    records = []
    for line_number, line in enumerate(payload.decode("utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row must be an object: {source}:{line_number}")
        records.append(value)
    return records


def _implementation_hashes() -> dict[str, str]:
    """冻结本次补足依赖的项目代码，避免证据跨 safe sync 漂移。"""
    project_root = Path(__file__).resolve().parents[2]
    paths = sorted((project_root / "adaligand_preprocessing").rglob("*.py"))
    return {
        path.relative_to(project_root).as_posix(): sha256_file(path)
        for path in paths
    }


if __name__ == "__main__":
    main()
