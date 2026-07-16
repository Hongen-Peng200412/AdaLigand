"""Stage E3 独立迁移入口的冻结目标、分片隔离与 release gate 测试。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest


CODE_ROOT = Path(__file__).resolve().parents[1] / "code"
sys.path.insert(0, str(CODE_ROOT))

import e3_repair
from io_utils import read_jsonl, sha256_file, write_jsonl
from reports import stage_result, write_report


def _prepare_snapshot(tmp_path: Path) -> dict[str, object]:
    """建立 4 个 pair、3 个旧 Stage E 合格目标和不可变旧证据。"""
    root = tmp_path / "root"
    source_run_id = "formal"
    repair_run_id = "formal_e3_v3"
    pair_ids = ["1a00", "1a01", "1a02", "1a03"]
    pair_path = root / "raw" / "pair_list.jsonl"
    write_jsonl(pair_path, [{"pdb_id": pdb_id} for pdb_id in pair_ids])
    status_path = (
        root
        / "reports"
        / "runs"
        / source_run_id
        / "stage_e"
        / "status.part_0000_of_0001.jsonl"
    )
    statuses = [
        stage_result("1a00", "stage_e", "success"),
        stage_result("1a01", "stage_e", "skipped"),
        stage_result("1a02", "stage_e", "success"),
        stage_result("1a03", "stage_e", "known_failed", reason="fixture"),
    ]
    write_jsonl(status_path, statuses)
    run_dir = root / "reports" / "runs" / source_run_id
    de_release = run_dir / "de_release" / "summary.json"
    exclusions = run_dir / "exclusions.jsonl"
    write_report(de_release, {"status": "success", "fixture": True})
    write_jsonl(exclusions, [{"pdb_id": "1a03", "fixture": True}])
    freeze_dir = root / "reports" / "runs" / repair_run_id / "stage_e3_freeze"
    target_ids_path = freeze_dir / "target_ids.txt"
    manifest_path = freeze_dir / "target_manifest.json"
    e3_repair.prepare_repair_snapshot(
        root,
        source_run_id=source_run_id,
        repair_run_id=repair_run_id,
        target_ids_file=target_ids_path,
        target_manifest=manifest_path,
        expected_source_stage_status_sha256=sha256_file(status_path),
        expected_de_release_sha256=sha256_file(de_release),
        expected_exclusion_sha256=sha256_file(exclusions),
        expected_pair_list_sha256=sha256_file(pair_path),
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "root": root,
        "source_run_id": source_run_id,
        "repair_run_id": repair_run_id,
        "pair_path": pair_path,
        "status_path": status_path,
        "target_ids_path": target_ids_path,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "manifest_sha256": sha256_file(manifest_path),
        "de_release": de_release,
        "exclusions": exclusions,
    }


def _run_part(fixture: dict[str, object], part_id: int, total_parts: int) -> dict:
    """以单进程执行一个确定性 repair 分片。"""
    return e3_repair.run_repair_shard(
        fixture["root"],
        repair_run_id=fixture["repair_run_id"],
        target_ids_file=fixture["target_ids_path"],
        target_manifest=fixture["manifest_path"],
        expected_target_manifest_sha256=fixture["manifest_sha256"],
        part_id=part_id,
        total_parts=total_parts,
        n_jobs=1,
    )


def _rewrite_target_manifest(fixture: dict[str, object], **updates: object) -> None:
    """在负例中显式冻结新的 manifest，而不是依赖旧 hash 先失败。"""
    manifest = dict(fixture["manifest"])
    manifest.update(updates)
    path = fixture["manifest_path"]
    path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    fixture["manifest"] = manifest
    fixture["manifest_sha256"] = sha256_file(path)


def test_prepare_freezes_exact_eligible_targets_and_is_idempotent(tmp_path: Path) -> None:
    """prepare 只导出三条旧合格目标；known failure 不复活，重复运行逐字节不变。"""
    fixture = _prepare_snapshot(tmp_path)
    target_path = fixture["target_ids_path"]
    manifest_path = fixture["manifest_path"]
    before_ids = target_path.read_bytes()
    before_manifest = manifest_path.read_bytes()
    manifest = json.loads(before_manifest.decode("utf-8"))
    assert before_ids == b"1a00\n1a01\n1a02\n"
    assert b"1a03" not in before_ids
    assert manifest["target_count"] == 3
    assert manifest["pair_list_path"] == "raw/pair_list.jsonl"
    assert manifest["de_release_path"] == (
        "reports/runs/formal/de_release/summary.json"
    )
    assert manifest["exclusion_path"] == "reports/runs/formal/exclusions.jsonl"
    assert manifest["source_stage_status_paths"] == [
        "reports/runs/formal/stage_e/status.part_0000_of_0001.jsonl"
    ]

    report = e3_repair.prepare_repair_snapshot(
        fixture["root"],
        source_run_id=fixture["source_run_id"],
        repair_run_id=fixture["repair_run_id"],
        target_ids_file=target_path,
        target_manifest=manifest_path,
        expected_source_stage_status_sha256=sha256_file(fixture["status_path"]),
        expected_de_release_sha256=sha256_file(fixture["de_release"]),
        expected_exclusion_sha256=sha256_file(fixture["exclusions"]),
        expected_pair_list_sha256=sha256_file(fixture["pair_path"]),
    )
    assert report["target_count"] == 3
    assert target_path.read_bytes() == before_ids
    assert manifest_path.read_bytes() == before_manifest


def test_prepare_failure_does_not_publish_half_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """manifest 原子替换失败时回滚本次 target IDs，且清理独占临时文件。"""
    fixture = _prepare_snapshot(tmp_path)
    target_path = fixture["target_ids_path"]
    manifest_path = fixture["manifest_path"]
    target_path.unlink()
    manifest_path.unlink()
    real_atomic_replace = e3_repair.atomic_replace

    def fail_manifest_replace(source: Path, target: Path) -> None:
        if target == manifest_path:
            raise OSError("fixture manifest replace failure")
        real_atomic_replace(source, target)

    monkeypatch.setattr(e3_repair, "atomic_replace", fail_manifest_replace)
    with pytest.raises(OSError, match="manifest replace failure"):
        e3_repair.prepare_repair_snapshot(
            fixture["root"],
            source_run_id=fixture["source_run_id"],
            repair_run_id=fixture["repair_run_id"],
            target_ids_file=target_path,
            target_manifest=manifest_path,
            expected_source_stage_status_sha256=sha256_file(fixture["status_path"]),
            expected_de_release_sha256=sha256_file(fixture["de_release"]),
            expected_exclusion_sha256=sha256_file(fixture["exclusions"]),
            expected_pair_list_sha256=sha256_file(fixture["pair_path"]),
        )
    assert not target_path.exists()
    assert not manifest_path.exists()
    assert not list(target_path.parent.glob("*.tmp.*"))


def test_snapshot_revalidates_old_release_and_exclusion(tmp_path: Path) -> None:
    """run/gate 每次加载都重新验证旧 de_release 与 exclusion 的当前 SHA。"""
    fixture = _prepare_snapshot(tmp_path / "release")
    with fixture["de_release"].open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(RuntimeError, match="source de_release identity drift"):
        _run_part(fixture, 0, 1)

    fixture = _prepare_snapshot(tmp_path / "exclusion")
    with fixture["exclusions"].open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(RuntimeError, match="source exclusion identity drift"):
        _run_part(fixture, 0, 1)


def test_prepare_rejects_outputs_inside_source_run(tmp_path: Path) -> None:
    """新冻结文件不得落入旧正式 run 或任意非规范 repair 输入目录。"""
    fixture = _prepare_snapshot(tmp_path)
    wrong_dir = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["source_run_id"]
        / "stage_e"
    )
    with pytest.raises(ValueError, match="isolated E3 freeze path"):
        e3_repair.prepare_repair_snapshot(
            fixture["root"],
            source_run_id=fixture["source_run_id"],
            repair_run_id=fixture["repair_run_id"],
            target_ids_file=wrong_dir / "target_ids.txt",
            target_manifest=wrong_dir / "target_manifest.json",
            expected_source_stage_status_sha256=sha256_file(fixture["status_path"]),
            expected_de_release_sha256=sha256_file(fixture["de_release"]),
            expected_exclusion_sha256=sha256_file(fixture["exclusions"]),
            expected_pair_list_sha256=sha256_file(fixture["pair_path"]),
        )


def test_same_shard_concurrency_is_claimed_and_completed_rerun_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O_EXCL claim 阻断同 part 双跑；完整 status 只验证并返回，不重算。"""
    fixture = _prepare_snapshot(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    failures: list[BaseException] = []

    def slow_build(root: Path, pdb_id: str, *, overwrite: bool) -> dict:
        calls.append(pdb_id)
        entered.set()
        if not release.wait(timeout=10):
            raise TimeoutError("fixture did not release worker")
        return {"status": "success", "artifact": f"density/{pdb_id}/ligand_area.npz"}

    monkeypatch.setattr(e3_repair, "build_ligand_area", slow_build)

    def run_first() -> None:
        try:
            _run_part(fixture, 0, 1)
        except BaseException as exc:  # 测试线程需把异常交还主线程断言。
            failures.append(exc)

    thread = threading.Thread(target=run_first, daemon=True)
    thread.start()
    assert entered.wait(timeout=10)
    with pytest.raises(RuntimeError, match="claim exists without complete status"):
        _run_part(fixture, 0, 1)
    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert not failures
    assert sorted(calls) == ["1a00", "1a01", "1a02"]

    summary = _run_part(fixture, 0, 1)
    assert summary["n_records"] == 3
    assert sorted(calls) == ["1a00", "1a01", "1a02"]


def test_global_partition_contract_blocks_different_total_parts_before_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 status 时 total3 与 total1 也不能凭不同 claim 文件并发覆盖同一目标。"""
    fixture = _prepare_snapshot(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    failures: list[BaseException] = []

    def slow_build(root: Path, pdb_id: str, *, overwrite: bool) -> dict:
        entered.set()
        if not release.wait(timeout=10):
            raise TimeoutError("fixture did not release worker")
        return {"status": "success", "artifact": f"density/{pdb_id}/ligand_area.npz"}

    monkeypatch.setattr(e3_repair, "build_ligand_area", slow_build)

    def run_total_three() -> None:
        try:
            _run_part(fixture, 0, 3)
        except BaseException as exc:  # 测试线程需把异常交还主线程断言。
            failures.append(exc)

    thread = threading.Thread(target=run_total_three, daemon=True)
    thread.start()
    assert entered.wait(timeout=10)
    with pytest.raises(RuntimeError, match="partition contract drift"):
        _run_part(fixture, 0, 1)
    release.set()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert not failures


def test_run_shards_cover_target_once_and_keep_worker_status_paths_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """三分片并集必须恰为目标集合，且每个 worker 只写自己的 status 路径。"""
    fixture = _prepare_snapshot(tmp_path)
    calls: list[str] = []

    def fake_build(root: Path, pdb_id: str, *, overwrite: bool) -> dict:
        calls.append(pdb_id)
        return {
            "status": "skipped" if pdb_id == "1a01" else "success",
            "artifact": f"density/{pdb_id}/ligand_area.npz",
        }

    monkeypatch.setattr(e3_repair, "build_ligand_area", fake_build)
    for part_id in range(3):
        _run_part(fixture, part_id, 3)

    stage_dir = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_repair"
    )
    paths = sorted(stage_dir.glob("status.part_*_of_*.jsonl"))
    partition_contract = json.loads(
        (stage_dir / "partition_contract.json").read_text(encoding="utf-8")
    )
    assert partition_contract["partition_policy"] == "parallel.shard_items_modulo_v1"
    assert [path.name for path in paths] == [
        "status.part_0000_of_0003.jsonl",
        "status.part_0001_of_0003.jsonl",
        "status.part_0002_of_0003.jsonl",
    ]
    records = [record for path in paths for record in read_jsonl(path)]
    assert sorted(record["pdb_id"] for record in records) == ["1a00", "1a01", "1a02"]
    assert len({record["pdb_id"] for record in records}) == len(records)
    assert sorted(calls) == ["1a00", "1a01", "1a02"]
    assert {record["status"] for record in records} == {"success", "skipped"}


def test_v3_skip_and_v2_rebuild_status_are_forwarded_from_core(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """入口不猜 schema；v3 skip 与 v2 重建结果完全由 core 返回值决定。"""
    fixture = _prepare_snapshot(tmp_path)

    def fake_build(root: Path, pdb_id: str, *, overwrite: bool) -> dict:
        return {
            "status": "skipped" if pdb_id == "1a00" else "success",
            "artifact": f"density/{pdb_id}/ligand_area.npz",
        }

    monkeypatch.setattr(e3_repair, "build_ligand_area", fake_build)
    _run_part(fixture, 0, 1)
    status_path = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_repair"
        / "status.part_0000_of_0001.jsonl"
    )
    statuses = {record["pdb_id"]: record for record in read_jsonl(status_path)}
    assert statuses["1a00"]["build_status"] == "skipped"
    assert statuses["1a01"]["build_status"] == "success"
    assert statuses["1a02"]["build_status"] == "success"


def test_gate_is_read_only_for_old_stage_release_and_exclusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """迁移与 gate 只写独立 run；旧 Stage E 状态、release 和 exclusion 字节不变。"""
    fixture = _prepare_snapshot(tmp_path)
    frozen_paths = [fixture["status_path"], fixture["de_release"], fixture["exclusions"]]
    before = {path: sha256_file(path) for path in frozen_paths}
    monkeypatch.setattr(
        e3_repair,
        "build_ligand_area",
        lambda root, pdb_id, *, overwrite: {
            "status": "success",
            "artifact": f"density/{pdb_id}/ligand_area.npz",
        },
    )
    monkeypatch.setattr(e3_repair, "validate_ligand_area_artifact", lambda root, pdb_id: [])
    _run_part(fixture, 0, 1)
    summary = e3_repair.gate_repair(
        fixture["root"],
        repair_run_id=fixture["repair_run_id"],
        target_ids_file=fixture["target_ids_path"],
        target_manifest=fixture["manifest_path"],
        expected_target_manifest_sha256=fixture["manifest_sha256"],
        n_jobs=1,
    )
    assert summary["status"] == "success"
    assert summary["n_target_pdb"] == 3
    assert summary["artifact_schema_version"] == 3
    assert all(sha256_file(path) == digest for path, digest in before.items())
    release = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_repair_release"
        / "summary.json"
    )
    assert json.loads(release.read_text(encoding="utf-8")) == summary
    assert e3_repair.gate_repair(
        fixture["root"],
        repair_run_id=fixture["repair_run_id"],
        target_ids_file=fixture["target_ids_path"],
        target_manifest=fixture["manifest_path"],
        expected_target_manifest_sha256=fixture["manifest_sha256"],
        n_jobs=1,
    ) == summary


def test_snapshot_rejects_duplicate_outside_and_revived_known_ids(tmp_path: Path) -> None:
    """目标重复、pair 宇宙外 ID 或复活旧 known failure 都必须在计算前阻断。"""
    fixture = _prepare_snapshot(tmp_path)
    target_path = fixture["target_ids_path"]
    target_path.write_text("1a00\n1a01\n1a01\n", encoding="utf-8")
    _rewrite_target_manifest(
        fixture,
        target_ids_sha256=sha256_file(target_path),
        target_count=3,
    )
    with pytest.raises(ValueError, match="duplicate PDB IDs"):
        _run_part(fixture, 0, 1)

    fixture = _prepare_snapshot(tmp_path / "outside")
    target_path = fixture["target_ids_path"]
    target_path.write_text("1a00\n1a01\n9zzz\n", encoding="utf-8")
    _rewrite_target_manifest(
        fixture,
        target_ids_sha256=sha256_file(target_path),
        target_count=3,
    )
    with pytest.raises(RuntimeError, match="outside pair_list"):
        _run_part(fixture, 0, 1)

    fixture = _prepare_snapshot(tmp_path / "revived")
    target_path = fixture["target_ids_path"]
    target_path.write_text("1a00\n1a01\n1a03\n", encoding="utf-8")
    _rewrite_target_manifest(
        fixture,
        target_ids_sha256=sha256_file(target_path),
        target_count=3,
    )
    with pytest.raises(RuntimeError, match="not exactly the old Stage E eligible set"):
        _run_part(fixture, 0, 1)


def test_snapshot_rejects_manifest_hash_count_and_source_status_drift(tmp_path: Path) -> None:
    """manifest 自身、目标计数和旧 Stage E 状态任何漂移都必须 fail-closed。"""
    fixture = _prepare_snapshot(tmp_path)
    fixture["manifest_path"].write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="target manifest identity drift"):
        _run_part(fixture, 0, 1)

    fixture = _prepare_snapshot(tmp_path / "count")
    _rewrite_target_manifest(fixture, target_count=4)
    with pytest.raises(RuntimeError, match="target count drift"):
        _run_part(fixture, 0, 1)

    fixture = _prepare_snapshot(tmp_path / "status")
    with fixture["status_path"].open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(RuntimeError, match="source Stage E status identity drift"):
        _run_part(fixture, 0, 1)


def test_repair_run_is_isolated_and_rejects_partition_contract_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """repair 不得复用正式 run id，也不得把另一套分片状态混入同一目录。"""
    fixture = _prepare_snapshot(tmp_path)
    monkeypatch.setattr(
        e3_repair,
        "build_ligand_area",
        lambda root, pdb_id, *, overwrite: {
            "status": "success",
            "artifact": f"density/{pdb_id}/ligand_area.npz",
        },
    )
    with pytest.raises(RuntimeError, match="must be isolated"):
        e3_repair.run_repair_shard(
            fixture["root"],
            repair_run_id=fixture["source_run_id"],
            target_ids_file=fixture["target_ids_path"],
            target_manifest=fixture["manifest_path"],
            expected_target_manifest_sha256=fixture["manifest_sha256"],
            part_id=0,
            total_parts=1,
            n_jobs=1,
        )
    _run_part(fixture, 0, 1)
    with pytest.raises(RuntimeError, match="partition contract drift"):
        _run_part(fixture, 0, 2)


def test_gate_rejects_missing_status_and_artifact_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """silent missing 与任一 schema/source/geometry/storage 错误都不能生成 release。"""
    fixture = _prepare_snapshot(tmp_path)
    with pytest.raises(RuntimeError, match="no source stage status files"):
        e3_repair.gate_repair(
            fixture["root"],
            repair_run_id=fixture["repair_run_id"],
            target_ids_file=fixture["target_ids_path"],
            target_manifest=fixture["manifest_path"],
            expected_target_manifest_sha256=fixture["manifest_sha256"],
            n_jobs=1,
        )

    monkeypatch.setattr(
        e3_repair,
        "build_ligand_area",
        lambda root, pdb_id, *, overwrite: {
            "status": "success",
            "artifact": f"density/{pdb_id}/ligand_area.npz",
        },
    )
    _run_part(fixture, 0, 1)
    monkeypatch.setattr(
        e3_repair,
        "validate_ligand_area_artifact",
        lambda root, pdb_id: ["ligand_area_storage:not_zip_deflated"]
        if pdb_id == "1a02"
        else [],
    )
    with pytest.raises(RuntimeError, match="artifact validation failed"):
        e3_repair.gate_repair(
            fixture["root"],
            repair_run_id=fixture["repair_run_id"],
            target_ids_file=fixture["target_ids_path"],
            target_manifest=fixture["manifest_path"],
            expected_target_manifest_sha256=fixture["manifest_sha256"],
            n_jobs=1,
        )
    release = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_repair_release"
        / "summary.json"
    )
    assert not release.exists()


def test_gate_validates_each_file_part_identity_and_fresh_path_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gate 逐文件核对 part/ID，并拒绝审计期间新增的 status 分片。"""
    fixture = _prepare_snapshot(tmp_path / "part")
    monkeypatch.setattr(
        e3_repair,
        "build_ligand_area",
        lambda root, pdb_id, *, overwrite: {
            "status": "success",
            "artifact": f"density/{pdb_id}/ligand_area.npz",
        },
    )
    for part_id in range(3):
        _run_part(fixture, part_id, 3)
    stage_dir = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_repair"
    )
    first_path = stage_dir / "status.part_0000_of_0003.jsonl"
    records = read_jsonl(first_path)
    records[0]["part_id"] = 1
    write_jsonl(first_path, records)
    monkeypatch.setattr(e3_repair, "validate_ligand_area_artifact", lambda root, pdb_id: [])
    with pytest.raises(RuntimeError, match="part_id drifted"):
        e3_repair.gate_repair(
            fixture["root"],
            repair_run_id=fixture["repair_run_id"],
            target_ids_file=fixture["target_ids_path"],
            target_manifest=fixture["manifest_path"],
            expected_target_manifest_sha256=fixture["manifest_sha256"],
            n_jobs=1,
        )

    fixture = _prepare_snapshot(tmp_path / "fresh")
    _run_part(fixture, 0, 1)
    stage_dir = (
        fixture["root"]
        / "reports"
        / "runs"
        / fixture["repair_run_id"]
        / "stage_e3_repair"
    )
    added = False

    def add_status_during_audit(root: Path, pdb_id: str) -> list[str]:
        nonlocal added
        if not added:
            added = True
            write_jsonl(
                stage_dir / "status.part_9999_of_9999.jsonl",
                [stage_result("9zzz", "stage_e3_repair", "success")],
            )
        return []

    monkeypatch.setattr(e3_repair, "validate_ligand_area_artifact", add_status_during_audit)
    with pytest.raises(RuntimeError, match="path set changed during release audit"):
        e3_repair.gate_repair(
            fixture["root"],
            repair_run_id=fixture["repair_run_id"],
            target_ids_file=fixture["target_ids_path"],
            target_manifest=fixture["manifest_path"],
            expected_target_manifest_sha256=fixture["manifest_sha256"],
            n_jobs=1,
        )


def test_import_path_does_not_load_chimera_or_mapq() -> None:
    """E3 专用入口导入时不得把 Chimera 或 MapQ 带入进程。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(CODE_ROOT)
    command = (
        "import sys; import e3_repair; "
        "print(int('chimera' in sys.modules), int(any(k.startswith('mapq') for k in sys.modules)))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.stdout.strip() == "0 0"
