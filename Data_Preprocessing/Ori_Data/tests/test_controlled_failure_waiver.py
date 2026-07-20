"""Stage F 受控失败 waiver 的严格默认、证据绑定和 gate/G 共用测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


CODE_ROOT = Path(__file__).resolve().parents[1]
CODE_DIR = CODE_ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from controlled_failure_waiver import canonical_status_row_sha256, load_stage_status_view
from filtering import load_stage_statuses, run_stage_g
from io_utils import read_jsonl, sha256_file, write_jsonl
from reports import stage_report_path, stage_result, write_stage_results
import stage_f_process_audit as process_audit


PROCESS_AUDIT_SCRIPT = CODE_ROOT / "scripts" / "stage_f_process_audit.py"


def _write_canonical_process_audit(path: Path) -> None:
    """使用生产 capture 结构生成 master+cnode04 的零 writer 测试证据。"""
    identity = process_audit.implementation_identity(PROCESS_AUDIT_SCRIPT)

    def zero_probe(node: str) -> str:
        """返回包含生产 schema/实现身份的零进程 probe stdout。"""
        return json.dumps(
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
        ) + "\n"

    def fake_run(argv: list[str], *, timeout_seconds: float = 120.0) -> tuple[int, str, str]:
        """为 scheduler 和两个节点 probe 提供确定性只读输出。"""
        del timeout_seconds
        if argv[:2] == ["bash", "-lc"]:
            return 0, "scheduler-ok\n", ""
        node = "master"
        for argument in argv:
            if argument.startswith("--nodelist="):
                node = argument.split("=", 1)[1]
        return 0, zero_probe(node), ""

    with (
        patch.object(process_audit, "_run_text", fake_run),
        patch.object(process_audit.socket, "gethostname", lambda: "master"),
    ):
        process_audit.capture_process_audit(
            path,
            jobs=[(316116, "cnode04")],
            script_path=PROCESS_AUDIT_SCRIPT,
            lock_root=path.parent / "locks",
            expected_controller_node="master",
        )


def _write_stage_f_fixture(root: Path, run_id: str) -> Path:
    """写一个成功样本和一个 raw unknown，且 unknown 质量三件套保持 0/3。"""
    write_jsonl(
        root / "raw" / "pair_list.jsonl",
        [
            {"pdb_id": "1aaa", "emdb_id": "EMD-1"},
            {"pdb_id": "2bbb", "emdb_id": "EMD-2"},
        ],
    )
    status_path = stage_report_path(root, run_id, "stage_f", 0, 1)
    write_stage_results(
        status_path,
        [
            stage_result("1aaa", "stage_f", "success"),
            stage_result(
                "2bbb",
                "stage_f",
                "unknown_failed",
                reason="nonzero_exit",
                error="Chimera exited with signal 11",
                error_type="ExternalToolError",
            ),
        ],
    )
    return status_path


def _write_waiver(
    root: Path,
    run_id: str,
    status_path: Path,
    *,
    authorized_cap: int = 200,
) -> tuple[Path, str]:
    """
    依据当前 fixture 生成一份完整、可再次篡改的测试 manifest。

    输入参数:
        - root: Path, 测试数据根目录
        - run_id: str, 当前 run 标识
        - status_path: Path, Stage F 单分片状态文件
        - authorized_cap: int, 测试授权累计上限

    输出:
        - waiver_path: Path, manifest 路径
        - waiver_sha256: str, manifest 文件 SHA-256
    """
    process_path = root / "reports" / "runs" / run_id / "waiver_evidence" / "process.json"
    process_path.parent.mkdir(parents=True, exist_ok=True)
    _write_canonical_process_audit(process_path)
    diagnostic_path = (
        root
        / "scratch"
        / run_id
        / "stage_f"
        / "2bbb"
        / "attempt_0001"
        / "chimera.stderr.txt"
    )
    diagnostic_path.parent.mkdir(parents=True, exist_ok=True)
    diagnostic_path.write_text("signal 11 after ADALIGAND_CC_ALL_BEGIN\n", encoding="utf-8")
    unknown = next(record for record in read_jsonl(status_path) if record["pdb_id"] == "2bbb")
    relative_status_path = status_path.relative_to(root).as_posix()
    manifest = {
        "schema_version": 1,
        "batch_id": "test_stage_f_waiver_v1",
        "run_id": run_id,
        "stage": "stage_f",
        "generated_at_utc": "2026-07-20T02:00:00Z",
        "authorization": "user_explicit_test_authorization",
        "decision_scope": "current_run_only",
        "authorized_cap": authorized_cap,
        "existing_run_policy_excluded_count": 0,
        "n_waived": 1,
        "cumulative_controlled_failure_count": 1,
        "scientific_contract_unchanged": True,
        "no_placeholder_artifacts": True,
        "downstream_policy": "exclude_from_training_inference_and_stage_g",
        "pair_list": {
            "path": "raw/pair_list.jsonl",
            "sha256": sha256_file(root / "raw" / "pair_list.jsonl"),
        },
        "status_files": [
            {
                "path": relative_status_path,
                "sha256": sha256_file(status_path),
            }
        ],
        "process_audit": {
            "path": process_path.relative_to(root).as_posix(),
            "sha256": sha256_file(process_path),
            "nodes": ["master", "cnode04"],
            "no_active_writers": True,
        },
        "code_files": [
            {"path": relative_path, "sha256": sha256_file(CODE_ROOT / relative_path)}
            for relative_path in (
                "code/controlled_failure_waiver.py",
                "code/filtering.py",
                "scripts/stage_release_gate.py",
                "scripts/g_filter.py",
                "code/stage_f_process_audit.py",
                "code/stage_f_process_audit_contract.py",
            )
        ],
        "exit_condition": "current run Stage G analyze and final audit complete",
        "records": [
            {
                "pdb_id": "2bbb",
                "status_file": relative_status_path,
                "status_file_sha256": sha256_file(status_path),
                "status_row_sha256": canonical_status_row_sha256(unknown),
                "raw_status": "unknown_failed",
                "raw_reason": "nonzero_exit",
                "raw_error": "Chimera exited with signal 11",
                "raw_error_type": "ExternalToolError",
                "classification": "chimera_full_grid_cc_signal11",
                "attempt": {
                    "attempt_path": diagnostic_path.parent.relative_to(root).as_posix(),
                    "job_id": "316116",
                    "node": "cnode04",
                    "tool_phase": "chimera_correlation_all",
                    "code_identity": "test-code-identity",
                },
                "diagnostic_evidence": [
                    {
                        "path": diagnostic_path.relative_to(root).as_posix(),
                        "sha256": sha256_file(diagnostic_path),
                    }
                ],
                "required_artifacts": [
                    {"path": "quality/2bbb.jsonl", "state": "absent"},
                    {"path": "quality/2bbb.provenance.json", "state": "absent"},
                    {"path": "quality_atoms/2bbb.npz", "state": "absent"},
                ],
                "scientific_contract_unchanged": True,
                "no_placeholder_artifacts": True,
                "downstream_policy": "exclude_from_training_inference_and_stage_g",
            }
        ],
    }
    waiver_path = root / "reports" / "runs" / run_id / "waiver_evidence" / "waiver.json"
    waiver_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return waiver_path, sha256_file(waiver_path)


def _write_g_inputs(root: Path, run_id: str) -> None:
    """补齐一个成功 PDB 的 D/E 状态、occurrence 和最小合法质量记录。"""
    for stage in ("stage_d", "stage_e"):
        write_stage_results(
            stage_report_path(root, run_id, stage, 0, 1),
            [
                stage_result("1aaa", stage, "success"),
                stage_result("2bbb", stage, "success"),
            ],
        )
    write_jsonl(
        root / "parse" / "1aaa" / "occurrences.jsonl",
        [{"candidate_id": 0, "type_tag": "small_molecule"}],
    )
    write_jsonl(
        root / "quality" / "1aaa.jsonl",
        [
            {
                "pdb_id": "1aaa",
                "candidate_id": 0,
                "q_score": 0.6,
                "q_score_median": 0.61,
                "q_score_min": 0.4,
                "n_valid": 8,
                "n_present": 8,
                "pocket_q_score": 0.7,
                "pocket_q_score_median": 0.71,
                "pocket_q_score_min": 0.6,
                "pocket_n_valid": 20,
                "pocket_n_atoms": 20,
                "pocket_status": "ok",
                "pocket_radius_angstrom": 6.0,
                "map_resolution": 2.8,
                "contour_status": "ok",
                "cc_contour": 0.5,
                "cc_contour_about_mean": 0.4,
                "cc_all": 0.5,
                "cc_all_about_mean": 0.4,
            }
        ],
    )
    (root / "quality" / "1aaa.provenance.json").write_text("{}\n", encoding="utf-8")


def test_default_loader_stays_strict_and_valid_waiver_preserves_raw_unknown(
    tmp_path: Path,
) -> None:
    """没有显式 waiver 仍阻断；有效 overlay 只返回独立 waived 集合。"""
    status_path = _write_stage_f_fixture(tmp_path, "run1")
    with pytest.raises(RuntimeError, match="unknown failures"):
        load_stage_statuses(tmp_path, "run1", "stage_f", {"1aaa", "2bbb"})
    waiver_path, waiver_sha256 = _write_waiver(tmp_path, "run1", status_path)
    view = load_stage_status_view(
        tmp_path,
        "run1",
        "stage_f",
        {"1aaa", "2bbb"},
        controlled_failure_waiver_path=waiver_path,
        controlled_failure_waiver_sha256=waiver_sha256,
    )
    assert view.records_by_pdb["2bbb"]["status"] == "unknown_failed"
    assert set(view.raw_unknown_by_pdb) == {"2bbb"}
    assert set(view.waived_by_pdb) == {"2bbb"}
    assert view.waiver is not None
    assert view.waiver.authorized_cap == 200


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda manifest: manifest.update({"authorized_cap": 0}), "positive integer"),
        (
            lambda manifest: manifest["records"][0].update({"raw_reason": "tampered"}),
            "raw status mismatch",
        ),
        (
            lambda manifest: manifest["records"][0].update(
                {"status_row_sha256": "0" * 64}
            ),
            "status identity mismatch",
        ),
        (
            lambda manifest: manifest["records"][0].update(
                {"scientific_contract_unchanged": False}
            ),
            "changes scientific contract",
        ),
        (
            lambda manifest: manifest["records"][0]["attempt"].update(
                {"node": "cnode99"}
            ),
            "not bound to process audit",
        ),
    ],
)
def test_waiver_rejects_authorization_or_raw_identity_drift(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    """cap、raw 字段、逐行 SHA 或科学边界任一漂移都继续 fail-closed。"""
    status_path = _write_stage_f_fixture(tmp_path, "run1")
    waiver_path, _ = _write_waiver(tmp_path, "run1", status_path)
    manifest = json.loads(waiver_path.read_text(encoding="utf-8"))
    mutation(manifest)
    waiver_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match=message):
        load_stage_status_view(
            tmp_path,
            "run1",
            "stage_f",
            {"1aaa", "2bbb"},
            controlled_failure_waiver_path=waiver_path,
            controlled_failure_waiver_sha256=sha256_file(waiver_path),
        )


def test_waiver_rejects_new_artifact_and_manifest_sha_drift(tmp_path: Path) -> None:
    """waived PDB 一旦出现 partial/占位产物或命令 SHA 过期就必须阻断。"""
    status_path = _write_stage_f_fixture(tmp_path, "run1")
    waiver_path, waiver_sha256 = _write_waiver(tmp_path, "run1", status_path)
    (tmp_path / "quality").mkdir(parents=True, exist_ok=True)
    (tmp_path / "quality" / "2bbb.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="no longer absent"):
        load_stage_status_view(
            tmp_path,
            "run1",
            "stage_f",
            {"1aaa", "2bbb"},
            controlled_failure_waiver_path=waiver_path,
            controlled_failure_waiver_sha256=waiver_sha256,
        )
    (tmp_path / "quality" / "2bbb.jsonl").unlink()
    waiver_path.write_text(waiver_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="waiver SHA mismatch"):
        load_stage_status_view(
            tmp_path,
            "run1",
            "stage_f",
            {"1aaa", "2bbb"},
            controlled_failure_waiver_path=waiver_path,
            controlled_failure_waiver_sha256=waiver_sha256,
        )


def test_release_gate_and_g_analyze_consume_same_waiver_without_placeholder(
    tmp_path: Path,
) -> None:
    """gate 与 G 共用同一 SHA；G 仅分析成功样本并保留 waived raw unknown。"""
    status_path = _write_stage_f_fixture(tmp_path, "run1")
    _write_g_inputs(tmp_path, "run1")
    waiver_path, waiver_sha256 = _write_waiver(tmp_path, "run1", status_path)
    command = [
        sys.executable,
        str(CODE_ROOT / "scripts" / "stage_release_gate.py"),
        "--root",
        str(tmp_path),
        "--run_id",
        "run1",
        "--stages",
        "stage_f",
        "--gate_name",
        "f_release",
        "--controlled_failure_waiver",
        str(waiver_path),
        "--controlled_failure_waiver_sha256",
        waiver_sha256,
    ]
    passed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert passed.returncode == 0, passed.stderr
    summary = json.loads(
        (
            tmp_path / "reports" / "runs" / "run1" / "f_release" / "summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["status_counts"]["stage_f"]["unknown_failed"] == 1
    assert summary["raw_unknown_counts"] == {"stage_f": 1}
    assert summary["controlled_failure_waiver"]["sha256"] == waiver_sha256
    assert summary["waived_controlled_failures"]["stage_f"] == [
        {
            "classification": "chimera_full_grid_cc_signal11",
            "pdb_id": "2bbb",
            "raw_reason": "nonzero_exit",
        }
    ]

    result = run_stage_g(
        tmp_path,
        "run1",
        mode="analyze",
        controlled_failure_waiver_path=waiver_path,
        controlled_failure_waiver_sha256=waiver_sha256,
    )
    assert result == {
        "status": "analysis_complete_filter_pending",
        "distribution": str(
            Path("reports")
            / "runs"
            / "run1"
            / "stage_g_analysis"
            / "quality_distribution.json"
        ),
        "n_candidates": 1,
        "n_waived_controlled_failures": 1,
    }
    assert not (tmp_path / "keep_list.jsonl").exists()
    distribution = json.loads(
        (
            tmp_path
            / "reports"
            / "runs"
            / "run1"
            / "stage_g_analysis"
            / "quality_distribution.json"
        ).read_text(encoding="utf-8")
    )
    assert distribution["n_eligible_pdb"] == 1
    assert distribution["n_raw_unknown_pdb"] == 1
    assert distribution["n_waived_controlled_failure_pdb"] == 1
    assert distribution["controlled_failure_waiver_sha256"] == waiver_sha256
    g_status = read_jsonl(
        stage_report_path(tmp_path, "run1", "stage_g_analysis", 0, 1)
    )
    waived = next(record for record in g_status if record["pdb_id"] == "2bbb")
    assert waived["status"] == "unknown_failed"
    assert waived["waived_controlled_failure"] is True
    assert waived["controlled_failure_waiver_sha256"] == waiver_sha256
    assert not (tmp_path / "quality" / "2bbb.jsonl").exists()


def test_g_waiver_requires_successful_matching_f_release(tmp_path: Path) -> None:
    """缺失 f_release 或 gate/G manifest SHA 不同都必须阻断 G。"""
    status_path = _write_stage_f_fixture(tmp_path, "run1")
    _write_g_inputs(tmp_path, "run1")
    waiver_path, waiver_sha256 = _write_waiver(tmp_path, "run1", status_path)
    with pytest.raises(RuntimeError, match="requires a successful formal f_release"):
        run_stage_g(
            tmp_path,
            "run1",
            mode="analyze",
            controlled_failure_waiver_path=waiver_path,
            controlled_failure_waiver_sha256=waiver_sha256,
        )

    command = [
        sys.executable,
        str(CODE_ROOT / "scripts" / "stage_release_gate.py"),
        "--root",
        str(tmp_path),
        "--run_id",
        "run1",
        "--stages",
        "stage_f",
        "--gate_name",
        "f_release",
        "--controlled_failure_waiver",
        str(waiver_path),
        "--controlled_failure_waiver_sha256",
        waiver_sha256,
    ]
    passed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert passed.returncode == 0, passed.stderr
    manifest = json.loads(waiver_path.read_text(encoding="utf-8"))
    manifest["batch_id"] = "different_still_valid_waiver"
    waiver_path.write_text(json.dumps(manifest), encoding="utf-8")
    different_sha256 = sha256_file(waiver_path)
    with pytest.raises(RuntimeError, match="does not match successful formal f_release"):
        run_stage_g(
            tmp_path,
            "run1",
            mode="analyze",
            controlled_failure_waiver_path=waiver_path,
            controlled_failure_waiver_sha256=different_sha256,
        )


def test_gate_requires_fresh_audit_but_g_reuses_release_bound_history(
    tmp_path: Path,
) -> None:
    """gate 拒绝过期进程门；已由 f_release 绑定后 G 可完整重验历史证据。"""
    status_path = _write_stage_f_fixture(tmp_path, "run1")
    _write_g_inputs(tmp_path, "run1")
    waiver_path, _ = _write_waiver(tmp_path, "run1", status_path)
    manifest = json.loads(waiver_path.read_text(encoding="utf-8"))
    audit_path = tmp_path / manifest["process_audit"]["path"]
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    audit["capture_started_at"] = "2020-01-01T00:00:00+00:00"
    audit["controller_check"]["started_at"] = "2020-01-01T00:00:01+00:00"
    audit["controller_check"]["completed_at"] = "2020-01-01T00:00:02+00:00"
    for check in audit["job_checks"].values():
        check["started_at"] = "2020-01-01T00:00:01+00:00"
        check["completed_at"] = "2020-01-01T00:00:02+00:00"
    audit["captured_at"] = "2020-01-01T00:00:03+00:00"
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    manifest["process_audit"]["sha256"] = sha256_file(audit_path)
    waiver_path.write_text(json.dumps(manifest), encoding="utf-8")
    waiver_sha256 = sha256_file(waiver_path)
    with pytest.raises(RuntimeError, match="does not prove a stopped writer set"):
        load_stage_status_view(
            tmp_path,
            "run1",
            "stage_f",
            {"1aaa", "2bbb"},
            controlled_failure_waiver_path=waiver_path,
            controlled_failure_waiver_sha256=waiver_sha256,
        )

    release_path = tmp_path / "reports" / "runs" / "run1" / "f_release" / "summary.json"
    release_path.parent.mkdir(parents=True, exist_ok=True)
    release_path.write_text(
        json.dumps(
            {
                "status": "success",
                "run_id": "run1",
                "gate_name": "f_release",
                "stages": ["stage_f"],
                "controlled_failure_waiver": {
                    "path": waiver_path.relative_to(tmp_path).as_posix(),
                    "sha256": waiver_sha256,
                    "authorized_cap": 200,
                    "n_waived": 1,
                    "cumulative_controlled_failure_count": 1,
                },
            }
        ),
        encoding="utf-8",
    )
    result = run_stage_g(
        tmp_path,
        "run1",
        mode="analyze",
        controlled_failure_waiver_path=waiver_path,
        controlled_failure_waiver_sha256=waiver_sha256,
    )
    assert result["n_waived_controlled_failures"] == 1


def test_release_gate_rejects_waiver_in_strict_smoke(tmp_path: Path) -> None:
    """strict smoke 不得借用正式 run 的 controlled-failure waiver。"""
    status_path = _write_stage_f_fixture(tmp_path, "run1")
    waiver_path, waiver_sha256 = _write_waiver(tmp_path, "run1", status_path)
    command = [
        sys.executable,
        str(CODE_ROOT / "scripts" / "stage_release_gate.py"),
        "--root",
        str(tmp_path),
        "--run_id",
        "run1",
        "--stages",
        "stage_f",
        "--gate_name",
        "smoke_gate",
        "--require_success",
        "--controlled_failure_waiver",
        str(waiver_path),
        "--controlled_failure_waiver_sha256",
        waiver_sha256,
    ]
    blocked = subprocess.run(command, capture_output=True, text=True, check=False)
    assert blocked.returncode != 0
    assert "strict smoke gate does not accept" in blocked.stderr
