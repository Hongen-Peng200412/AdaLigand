"""Stage C ligand descriptor 显式补足及 run-scoped 证据测试。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from uuid import uuid4

import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
SCRIPT_DIR = Path(__file__).resolve().parents[1] / "adaligand_preprocessing" / "cli"

from adaligand_preprocessing.ops.stage_c_descriptors import (
    DESCRIPTOR_PREFETCH_SCHEMA_VERSION,
    materialize_and_audit_descriptor,
)


def _load_cli(name: str):
    """以唯一模块名加载 descriptor prefetch CLI，避免与 code 模块冲突。"""
    spec = importlib.util.spec_from_file_location(
        name,
        SCRIPT_DIR / "prefetch_descriptors.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_materialize_descriptor_uses_non_overwrite_and_freezes_dependencies(
    monkeypatch,
    tmp_path,
):
    """缺失 descriptor 只能以 overwrite=False 补足，并记录源/目标相对路径与哈希。"""
    root = tmp_path / f"root_{uuid4().hex}"
    object_path = root / "ligand_objects" / "CCD_5GP.npz"
    descriptor_path = root / "ligand_descriptors" / "CCD_5GP.npz"
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(b"ligand-object")
    calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.ligand_object_is_valid",
        lambda path, key: path == object_path and key == "CCD:5GP",
    )
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.ligand_descriptor_is_valid",
        lambda path: path.is_file() and path.read_bytes() == b"descriptor",
    )

    def _fake_materialize(_root, object_key, overwrite):
        calls.append((object_key, overwrite))
        descriptor_path.parent.mkdir(parents=True)
        descriptor_path.write_bytes(b"descriptor")
        return descriptor_path

    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.materialize_ligand_descriptor",
        _fake_materialize,
    )

    record = materialize_and_audit_descriptor(root, "CCD:5GP")

    assert calls == [("CCD:5GP", False)]
    assert record == {
        "status": "success",
        "object_key": "CCD:5GP",
        "action": "materialized",
        "ligand_object_path": "ligand_objects/CCD_5GP.npz",
        "ligand_object_sha256": hashlib.sha256(b"ligand-object").hexdigest(),
        "descriptor_path": "ligand_descriptors/CCD_5GP.npz",
        "descriptor_sha256": hashlib.sha256(b"descriptor").hexdigest(),
        "schema_version": DESCRIPTOR_PREFETCH_SCHEMA_VERSION,
    }


def test_materialize_descriptor_marks_valid_existing_file_as_reused(
    monkeypatch,
    tmp_path,
):
    """已有有效 descriptor 仍调用幂等 API，但证据动作必须是 reused。"""
    root = tmp_path / f"root_{uuid4().hex}"
    object_path = root / "ligand_objects" / "CCD_5GP.npz"
    descriptor_path = root / "ligand_descriptors" / "CCD_5GP.npz"
    object_path.parent.mkdir(parents=True)
    descriptor_path.parent.mkdir(parents=True)
    object_path.write_bytes(b"ligand-object")
    descriptor_path.write_bytes(b"descriptor")

    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.ligand_object_is_valid",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.ligand_descriptor_is_valid",
        lambda path: path == descriptor_path,
    )
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.materialize_ligand_descriptor",
        lambda _root, _key, overwrite: descriptor_path if overwrite is False else None,
    )

    record = materialize_and_audit_descriptor(root, "CCD:5GP")

    assert record["action"] == "reused"
    assert record["descriptor_sha256"] == hashlib.sha256(b"descriptor").hexdigest()


def test_materialize_descriptor_fails_when_final_schema_is_invalid(
    monkeypatch,
    tmp_path,
):
    """物化 API 返回后若 descriptor schema 仍无效，必须在写成功证据前阻断。"""
    root = tmp_path / f"root_{uuid4().hex}"
    object_path = root / "ligand_objects" / "CCD_5GP.npz"
    descriptor_path = root / "ligand_descriptors" / "CCD_5GP.npz"
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(b"ligand-object")
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.ligand_object_is_valid",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.ligand_descriptor_is_valid",
        lambda _path: False,
    )

    def _write_invalid(*_args, **_kwargs):
        descriptor_path.parent.mkdir(parents=True)
        descriptor_path.write_bytes(b"invalid")
        return descriptor_path

    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.materialize_ligand_descriptor",
        _write_invalid,
    )

    with pytest.raises(RuntimeError, match="invalid descriptor after materialization"):
        materialize_and_audit_descriptor(root, "CCD:5GP")


def test_materialize_descriptor_detects_source_object_race(
    monkeypatch,
    tmp_path,
):
    """补足期间 LigandObject 内容发生漂移时必须阻断，不能签发成功哈希证据。"""
    root = tmp_path / f"root_{uuid4().hex}"
    object_path = root / "ligand_objects" / "CCD_5GP.npz"
    descriptor_path = root / "ligand_descriptors" / "CCD_5GP.npz"
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(b"before")
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.ligand_object_is_valid",
        lambda *_args: True,
    )
    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.ligand_descriptor_is_valid",
        lambda path: path == descriptor_path and path.is_file(),
    )

    def _race_source(*_args, **_kwargs):
        descriptor_path.parent.mkdir(parents=True)
        descriptor_path.write_bytes(b"descriptor")
        object_path.write_bytes(b"after")
        return descriptor_path

    monkeypatch.setattr(
        "adaligand_preprocessing.ops.stage_c_descriptors.materialize_ligand_descriptor",
        _race_source,
    )

    with pytest.raises(RuntimeError, match="LigandObject changed"):
        materialize_and_audit_descriptor(root, "CCD:5GP")


def test_descriptor_prefetch_cli_freezes_and_reuses_success_evidence(
    monkeypatch,
    tmp_path,
):
    """成功 summary 必须绑定冻结输入、records 和实现哈希，重复运行不得改写证据。"""
    cli = _load_cli("test_descriptor_prefetch_success_cli")
    root = tmp_path / f"root_{uuid4().hex}"
    root.mkdir()
    object_path = root / "ligand_objects" / "CCD_5GP.npz"
    descriptor_path = root / "ligand_descriptors" / "CCD_5GP.npz"
    object_path.parent.mkdir(parents=True)
    descriptor_path.parent.mkdir(parents=True)
    object_path.write_bytes(b"object")
    descriptor_path.write_bytes(b"descriptor")
    keys_path = tmp_path / "object_keys.txt"
    keys_path.write_text("CCD:5GP\n", encoding="utf-8", newline="\n")
    keys_hash = hashlib.sha256(keys_path.read_bytes()).hexdigest()
    calls: list[str] = []

    def _fake_materialize(_root, object_key):
        calls.append(object_key)
        return {
            "status": "success",
            "object_key": object_key,
            "action": "materialized",
            "ligand_object_path": "ligand_objects/CCD_5GP.npz",
            "ligand_object_sha256": hashlib.sha256(b"object").hexdigest(),
            "descriptor_path": "ligand_descriptors/CCD_5GP.npz",
            "descriptor_sha256": hashlib.sha256(b"descriptor").hexdigest(),
            "schema_version": DESCRIPTOR_PREFETCH_SCHEMA_VERSION,
        }

    monkeypatch.setattr(cli, "materialize_and_audit_descriptor", _fake_materialize)
    monkeypatch.setattr(
        cli,
        "_implementation_hashes",
        lambda: {"code/frozen.py": "0" * 64},
    )
    argv = [
        "prefetch_descriptors.py",
        "--root", str(root),
        "--object_keys_file", str(keys_path),
        "--keys_sha256", keys_hash,
        "--expected_count", "1",
        "--run_id", "descriptor_prefetch_test",
        "--n_jobs", "1",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    cli.main()

    evidence_dir = (
        root
        / "reports"
        / "runs"
        / "descriptor_prefetch_test"
        / "stage_c_descriptor_prefetch"
    )
    summary_path = evidence_dir / "summary.json"
    records_path = evidence_dir / "records.jsonl"
    first_summary_bytes = summary_path.read_bytes()
    first_records_bytes = records_path.read_bytes()
    summary = json.loads(first_summary_bytes)
    assert summary["status"] == "success"
    assert summary["object_keys_sha256"] == keys_hash
    assert summary["object_key_count"] == 1
    assert summary["records_sha256"] == hashlib.sha256(first_records_bytes).hexdigest()
    assert summary["implementation_files"] == {"code/frozen.py": "0" * 64}
    assert calls == ["CCD:5GP"]

    monkeypatch.setattr(
        cli,
        "materialize_and_audit_descriptor",
        lambda *_args: pytest.fail("successful evidence should be reused"),
    )
    cli.main()
    assert calls == ["CCD:5GP"]
    assert summary_path.read_bytes() == first_summary_bytes
    assert records_path.read_bytes() == first_records_bytes

    record = json.loads(first_records_bytes.decode("utf-8"))
    record["descriptor_path"] = "ligand_descriptors/CCD_OTHER.npz"
    tampered_records = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    records_path.write_bytes(tampered_records)
    summary["records_sha256"] = hashlib.sha256(tampered_records).hexdigest()
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="output path does not match object key"):
        cli.main()


def test_descriptor_prefetch_cli_records_failure_and_refuses_overwrite(
    monkeypatch,
    tmp_path,
):
    """单项失败必须写 failed summary、退出非零，并禁止同一 run id 覆盖证据。"""
    cli = _load_cli("test_descriptor_prefetch_failed_cli")
    root = tmp_path / f"root_{uuid4().hex}"
    root.mkdir()
    keys_path = tmp_path / "object_keys.txt"
    keys_path.write_text("CCD:5GP\n", encoding="utf-8", newline="\n")
    keys_hash = hashlib.sha256(keys_path.read_bytes()).hexdigest()
    monkeypatch.setattr(
        cli,
        "materialize_and_audit_descriptor",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("dependency missing")),
    )
    monkeypatch.setattr(
        cli,
        "_implementation_hashes",
        lambda: {"code/frozen.py": "0" * 64},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prefetch_descriptors.py",
            "--root", str(root),
            "--object_keys_file", str(keys_path),
            "--keys_sha256", keys_hash,
            "--expected_count", "1",
            "--run_id", "descriptor_prefetch_failed",
            "--n_jobs", "1",
        ],
    )

    with pytest.raises(RuntimeError, match="descriptor prefetch failed"):
        cli.main()

    summary_path = (
        root
        / "reports"
        / "runs"
        / "descriptor_prefetch_failed"
        / "stage_c_descriptor_prefetch"
        / "summary.json"
    )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["counts"] == {"failed": 1}
    failed_record_path = summary_path.with_name("records.jsonl")
    failed_record = json.loads(failed_record_path.read_text(encoding="utf-8"))
    assert failed_record["action"] == "failed"
    assert failed_record["ligand_object_path"] == "ligand_objects/CCD_5GP.npz"
    assert failed_record["ligand_object_sha256"] is None
    assert failed_record["descriptor_path"] == "ligand_descriptors/CCD_5GP.npz"
    assert failed_record["descriptor_sha256"] is None

    with pytest.raises(RuntimeError, match="refusing to overwrite non-success"):
        cli.main()


@pytest.mark.parametrize(
    "payload,error",
    [
        (b"CCD:5GP\nCCD:5GP\n", "duplicate object keys"),
        (b"CCD:5GP\n\nCCD:ABC\n", "empty row"),
        (b"ccd:5gp\n", "invalid Stage C descriptor object key"),
    ],
)
def test_frozen_object_keys_rejects_ambiguous_input(
    tmp_path,
    payload,
    error,
):
    """冻结清单拒绝重复、空行和非规范 key，避免静默改写科学身份。"""
    cli = _load_cli(f"test_descriptor_keys_{hashlib.sha256(payload).hexdigest()[:8]}")
    path = tmp_path / "keys.txt"
    path.write_bytes(payload)

    with pytest.raises((ValueError, RuntimeError), match=error):
        cli._frozen_object_keys(
            path,
            hashlib.sha256(payload).hexdigest(),
            2,
        )


def test_frozen_object_keys_rejects_sha_mismatch(tmp_path):
    """冻结清单原始字节与声明 SHA 不同，必须在解析和任何物化前阻断。"""
    cli = _load_cli("test_descriptor_keys_sha_mismatch")
    path = tmp_path / "keys.txt"
    path.write_text("CCD:5GP\n", encoding="utf-8", newline="\n")

    with pytest.raises(RuntimeError, match="object keys sha256"):
        cli._frozen_object_keys(path, "0" * 64, 1)
