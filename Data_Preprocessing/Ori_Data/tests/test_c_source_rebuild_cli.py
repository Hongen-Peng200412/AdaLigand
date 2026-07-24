"""专用 rebuild 与 generic source-repair CLI 的 delegated 哈希闭环测试。"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "adaligand_preprocessing" / "cli"


def _load_script(name: str, filename: str):
    """以唯一模块名加载 CLI 文件，避免与同名 code 模块冲突。"""
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_delegated_rebuild_cli_hash_chain(monkeypatch, tmp_path):
    """audit→联合 gate→rebuild apply→generic apply 必须绑定同一组 summary/records SHA。"""
    rebuild_cli = _load_script("test_rebuild_cli", "stage_c_rebuild.py")
    repair_cli = _load_script("test_repair_cli", "stage_c_repair.py")
    root = tmp_path / "root"
    root.mkdir()
    authorized_ids = tmp_path / "authorized.txt"
    dirty_ids = tmp_path / "dirty.txt"
    authorized_ids.write_text("1abc\n", encoding="utf-8", newline="\n")
    dirty_ids.write_text("1abc\n", encoding="utf-8", newline="\n")
    authorized_hash = _sha256(authorized_ids)
    dirty_hash = _sha256(dirty_ids)
    run_id = "adaligand_test_repair"

    base_audit = {
        "pdb_id": "1abc",
        "classification": "blocked",
        "reasons": [
            "failed_occurrences_changed",
            "ligand_coords_keys_changed",
            "occurrences_changed",
        ],
        "schema_version": 2,
    }
    rebuild_record = {
        "pdb_id": "1abc",
        "classification": "full_rebuild_ready",
        "base_audit": base_audit,
        "schema_version": 1,
    }
    migration_row = {
        "pdb_id": "1abc",
        "status": "added",
        "old_candidate_id": None,
        "new_candidate_id": 0,
        "schema_version": 1,
    }
    monkeypatch.setattr(
        rebuild_cli,
        "_prepare_one",
        lambda *_args, **_kwargs: (rebuild_record, [migration_row]),
    )
    _run_rebuild_cli(
        monkeypatch,
        rebuild_cli,
        root,
        authorized_ids,
        authorized_hash,
        dirty_ids,
        dirty_hash,
        run_id,
        "audit",
    )

    rebuild_dir = root / "reports" / "runs" / run_id / "stage_c_source_rebuild"
    rebuild_summary = rebuild_dir / "audit.summary.json"
    monkeypatch.setattr(repair_cli, "audit_stage_c_source", lambda *_args: base_audit)
    _run_repair_cli(
        monkeypatch,
        repair_cli,
        root,
        dirty_ids,
        dirty_hash,
        run_id,
        "audit",
        rebuild_summary,
        _sha256(rebuild_summary),
    )

    repair_summary = (
        root / "reports" / "runs" / run_id / "stage_c_source_repair" / "audit.summary.json"
    )
    monkeypatch.setattr(
        rebuild_cli,
        "apply_prepared_source_rebuilds",
        lambda *_args, **_kwargs: [{"pdb_id": "1abc", "action": "committed"}],
    )
    _run_rebuild_cli(
        monkeypatch,
        rebuild_cli,
        root,
        authorized_ids,
        authorized_hash,
        dirty_ids,
        dirty_hash,
        run_id,
        "apply",
        repair_summary,
        _sha256(repair_summary),
    )

    rebuild_apply_summary = rebuild_dir / "apply.summary.json"
    monkeypatch.setattr(
        repair_cli,
        "_verify_delegated_after_apply",
        lambda _root, record: {
            "pdb_id": record["pdb_id"],
            "action": "delegated_rebuild_verified",
        },
    )
    _run_repair_cli(
        monkeypatch,
        repair_cli,
        root,
        dirty_ids,
        dirty_hash,
        run_id,
        "apply",
        rebuild_summary,
        _sha256(rebuild_summary),
        rebuild_apply_summary,
        _sha256(rebuild_apply_summary),
    )

    generic_apply = json.loads(
        (
            root
            / "reports"
            / "runs"
            / run_id
            / "stage_c_source_repair"
            / "apply.summary.json"
        ).read_text(encoding="utf-8")
    )
    assert generic_apply["status"] == "success"
    assert generic_apply["counts"] == {"delegated_rebuild_verified": 1}


def test_require_all_exact_rejects_residual_atom_name_only(monkeypatch, tmp_path):
    """post audit 即使没有 blocked，也必须因残余 atom_name_only 退出非零。"""
    repair_cli = _load_script("test_post_exact_cli", "stage_c_repair.py")
    root = tmp_path / "root"
    root.mkdir()
    ids = tmp_path / "dirty.txt"
    ids.write_text("1abc\n", encoding="utf-8", newline="\n")
    ids_hash = _sha256(ids)
    monkeypatch.setattr(
        repair_cli,
        "audit_stage_c_source",
        lambda *_args: {
            "pdb_id": "1abc",
            "classification": "atom_name_only",
            "reasons": [],
            "schema_version": 2,
        },
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stage_c_repair.py",
            "--root", str(root),
            "--pdb_ids_file", str(ids),
            "--ids_sha256", ids_hash,
            "--expected_count", "1",
            "--repair_run_id", "post_exact_test",
            "--mode", "audit",
            "--n_jobs", "1",
            "--require_all_exact",
        ],
    )

    with pytest.raises(RuntimeError, match="not all exact"):
        repair_cli.main()

    summary = json.loads(
        (
            root
            / "reports"
            / "runs"
            / "post_exact_test"
            / "stage_c_source_repair"
            / "audit.summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["status"] == "failed"
    assert summary["counts"] == {"atom_name_only": 1}


def _run_rebuild_cli(
    monkeypatch,
    module,
    root: Path,
    authorized_ids: Path,
    authorized_hash: str,
    dirty_ids: Path,
    dirty_hash: str,
    run_id: str,
    mode: str,
    gate_summary: Path | None = None,
    gate_hash: str | None = None,
) -> None:
    """用单样本冻结参数调用 rebuild CLI。"""
    argv = [
        "stage_c_rebuild.py",
        "--root", str(root),
        "--pdb_ids_file", str(authorized_ids),
        "--ids_sha256", authorized_hash,
        "--expected_count", "1",
        "--dirty_ids_file", str(dirty_ids),
        "--dirty_ids_sha256", dirty_hash,
        "--dirty_expected_count", "1",
        "--repair_run_id", run_id,
        "--mode", mode,
        "--n_jobs", "1",
        "--expected_added", "1",
        "--expected_removed", "0",
        "--expected_reassigned", "0",
    ]
    if gate_summary is not None:
        argv.extend([
            "--preapply_gate_summary", str(gate_summary),
            "--preapply_gate_sha256", str(gate_hash),
        ])
    monkeypatch.setattr(sys, "argv", argv)
    module.main()


def _run_repair_cli(
    monkeypatch,
    module,
    root: Path,
    dirty_ids: Path,
    dirty_hash: str,
    run_id: str,
    mode: str,
    rebuild_summary: Path,
    rebuild_hash: str,
    rebuild_apply_summary: Path | None = None,
    rebuild_apply_hash: str | None = None,
) -> None:
    """用单样本 delegated 参数调用 generic source-repair CLI。"""
    argv = [
        "stage_c_repair.py",
        "--root", str(root),
        "--pdb_ids_file", str(dirty_ids),
        "--ids_sha256", dirty_hash,
        "--expected_count", "1",
        "--repair_run_id", run_id,
        "--mode", mode,
        "--n_jobs", "1",
        "--delegated_rebuild_summary", str(rebuild_summary),
        "--delegated_rebuild_summary_sha256", rebuild_hash,
    ]
    if rebuild_apply_summary is not None:
        argv.extend([
            "--delegated_rebuild_apply_summary", str(rebuild_apply_summary),
            "--delegated_rebuild_apply_sha256", str(rebuild_apply_hash),
        ])
    monkeypatch.setattr(sys, "argv", argv)
    module.main()


def _sha256(path: Path) -> str:
    """计算测试输入文件 SHA-256。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()
