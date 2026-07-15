"""Stage F attempt scratch 的异常安全清理与作用域回归测试。"""

from __future__ import annotations

import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
TESTS_DIR = Path(__file__).resolve().parent
for import_dir in (CODE_DIR, TESTS_DIR):
    if str(import_dir) not in sys.path:
        sys.path.insert(0, str(import_dir))

import quality
from chimera import ChimeraRunner
from density import build_experimental_density
from failures import ExternalToolError, ToolFailureCode
from mapq import MapQRunner
from parse import parse_one_pdb
from test_pipeline_smoke import _write_fake_chimera, _write_fake_mapq, _write_inputs


_TRANSIENT_SUFFIXES = {".mrc", ".map", ".cif"}


class _InjectedFailure(RuntimeError):
    """表示由测试在指定生命周期阶段注入的故障。"""


@dataclass(frozen=True)
class _QualityCase:
    """
    保存一个可直接进入 ``build_quality`` 的最小真实 fixture。

    字段:
        - root: Path, 独立数据根目录
        - scratch_root: Path, 所有 attempt 的共享 scratch 根目录
        - record: dict[str, Any], 当前 PDB/map 输入记录
        - run_id: str, 当前测试运行标识
        - chimera_runner: ChimeraRunner, 使用假可执行文件的 Chimera adapter
        - mapq_runner: MapQRunner, 使用假 CLI 的 MapQ adapter
        - chimera_version: str, 写入 provenance 的稳定版本文本
    """

    root: Path
    scratch_root: Path
    record: dict[str, Any]
    run_id: str
    chimera_runner: ChimeraRunner
    mapq_runner: MapQRunner
    chimera_version: str


class _FaultAfterChimera:
    """Chimera delegate 已生成产物和日志后，在指定阶段抛错。"""

    def __init__(self, delegate: ChimeraRunner, phase: str) -> None:
        self.delegate = delegate
        self.phase = phase

    def molmap_on_grid(self, *args: Any, **kwargs: Any) -> Any:
        """生成合法模拟图后可选模拟 molmap timeout。"""
        result = self.delegate.molmap_on_grid(*args, **kwargs)
        if self.phase == "molmap":
            raise ExternalToolError(ToolFailureCode.TIMEOUT, "injected molmap timeout")
        return result

    def measure_correlations(self, *args: Any, **kwargs: Any) -> Any:
        """生成合法 CC 日志后可选模拟 correlation 故障。"""
        result = self.delegate.measure_correlations(*args, **kwargs)
        if self.phase == "correlation":
            raise ExternalToolError(
                ToolFailureCode.CORRELATION_PARSE,
                "injected correlation failure",
            )
        return result


class _FaultAfterMapQ:
    """MapQ delegate 已写出 CIF/日志但尚未向 ``build_quality`` 返回时抛错。"""

    def __init__(self, delegate: MapQRunner) -> None:
        self.delegate = delegate
        self.mapq_cmd_path = delegate.mapq_cmd_path

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """在 MapQ 返回值尚未赋给调用方前注入故障。"""
        result = self.delegate.run(*args, **kwargs)
        scratch_dir = Path(kwargs["scratch_dir"])
        nested_dir = scratch_dir / "mapq_nested"
        nested_dir.mkdir(parents=True, exist_ok=True)
        (nested_dir / "unexpected_mapq_tmp.mrc").write_bytes(b"mapq-mrc")
        (nested_dir / "unexpected_output.cif.tmp.123").write_text(
            "data_partial\n",
            encoding="utf-8",
        )
        raise ExternalToolError(ToolFailureCode.OUTPUT_SCHEMA, "injected MapQ failure")


class _DoNotRunChimera:
    """合法三件套 skip 路径不得调用的 Chimera sentinel。"""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"skip path unexpectedly accessed Chimera: {name}")


class _DoNotRunMapQ:
    """提供 provenance 校验所需路径，但禁止 skip 路径运行 MapQ。"""

    def __init__(self, mapq_cmd_path: Path) -> None:
        self.mapq_cmd_path = mapq_cmd_path

    def run(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("skip path unexpectedly ran MapQ")


@pytest.fixture
def quality_case(tmp_path: Path) -> _QualityCase:
    """
    构造真实 Stage C/E1 产物与轻量 fake Chimera/MapQ。

    输出:
        - case: _QualityCase, 可直接用于 Stage F 生命周期测试的输入集合
    """
    root = tmp_path / "data"
    scratch_root = tmp_path / "scratch"
    record = _write_inputs(root)
    assert parse_one_pdb(root, "1abc", overwrite=True)["status"] == "ok"
    assert build_experimental_density(root, record)["status"] == "success"

    fake_chimera = tmp_path / "fake_chimera.py"
    fake_mapq = tmp_path / "mapq_cmd.py"
    chimera_root = tmp_path / "chimera"
    _write_fake_chimera(fake_chimera)
    _write_fake_mapq(fake_mapq)
    chimera_root.mkdir()
    return _QualityCase(
        root=root,
        scratch_root=scratch_root,
        record=record,
        run_id="scratch_lifecycle",
        chimera_runner=ChimeraRunner([sys.executable, str(fake_chimera)], timeout_seconds=10),
        mapq_runner=MapQRunner(
            [sys.executable],
            fake_mapq,
            chimera_root,
            timeout_seconds=10,
        ),
        chimera_version="UCSF Chimera fake 1.19",
    )


def _build_quality(
    case: _QualityCase,
    *,
    chimera_runner: Any | None = None,
    mapq_runner: Any | None = None,
) -> dict[str, Any]:
    """使用 fixture 的稳定参数调用 ``build_quality``。"""
    return quality.build_quality(
        case.root,
        case.record,
        chimera_runner=chimera_runner or case.chimera_runner,
        mapq_runner=mapq_runner or case.mapq_runner,
        chimera_version=case.chimera_version,
        run_id=case.run_id,
        scratch_root=case.scratch_root,
    )


def _attempt_dirs(case: _QualityCase) -> set[Path]:
    """返回当前 run/PDB 下已创建的 attempt 目录集合。"""
    pdb_scratch = case.scratch_root / case.run_id / "stage_f" / "1abc"
    if not pdb_scratch.exists():
        return set()
    return {path for path in pdb_scratch.iterdir() if path.is_dir()}


def _only_new_attempt(case: _QualityCase, before: set[Path]) -> Path:
    """校验故障调用只创建了一个新 attempt，并返回其路径。"""
    created = _attempt_dirs(case).difference(before)
    assert len(created) == 1
    return created.pop()


def _transient_files(attempt_dir: Path) -> list[Path]:
    """收集当前 attempt 中不应持久保留的大型中间文件。"""
    return sorted(
        path
        for path in attempt_dir.rglob("*")
        if path.is_file()
        and (
            path.suffix.lower() in _TRANSIENT_SUFFIXES
            or ".cif.tmp." in path.name.lower()
        )
    )


def _assert_no_transients(attempt_dir: Path) -> None:
    """断言精确 attempt 范围内已无大型 MRC/map/CIF 中间件。"""
    assert _transient_files(attempt_dir) == []


def _assert_logs_exist(attempt_dir: Path, stems: tuple[str, ...]) -> None:
    """断言已执行工具的小型 stdout/stderr 证据仍在。"""
    for stem in stems:
        assert (attempt_dir / f"{stem}.stdout.log").is_file()
        assert (attempt_dir / f"{stem}.stderr.log").is_file()


def test_build_quality_success_cleans_large_transients_and_keeps_logs(
    quality_case: _QualityCase,
) -> None:
    """成功路径清理全部大文件，且 provenance 引用的小日志仍可读。"""
    result = _build_quality(quality_case)
    assert result["status"] == "success"
    attempt_dir = quality_case.scratch_root / result["scratch"]
    _assert_no_transients(attempt_dir)
    _assert_logs_exist(attempt_dir, ("molmap", "correlation", "mapq"))

    provenance_path = quality_case.root / "quality" / "1abc.provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    for log_path in provenance["logs"].values():
        assert (quality_case.scratch_root / log_path).is_file()


def test_build_quality_cleans_after_canonical_mrc_failure(
    quality_case: _QualityCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """canonical MRC 已写出后抛错时，full-model CIF 与 partial MRC 都被清理。"""
    original = quality.write_canonical_mrc

    def _write_then_fail(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        raise _InjectedFailure("canonical MRC failure")

    monkeypatch.setattr(quality, "write_canonical_mrc", _write_then_fail)
    before = _attempt_dirs(quality_case)
    with pytest.raises(_InjectedFailure):
        _build_quality(quality_case)
    _assert_no_transients(_only_new_attempt(quality_case, before))


@pytest.mark.parametrize(
    ("phase", "expected_logs"),
    [
        ("molmap", ("molmap",)),
        ("correlation", ("molmap", "correlation")),
    ],
)
def test_build_quality_cleans_after_chimera_failure_and_keeps_logs(
    quality_case: _QualityCase,
    phase: str,
    expected_logs: tuple[str, ...],
) -> None:
    """molmap/CC 已落盘后异常不得留下大文件，工具日志必须保留。"""
    before = _attempt_dirs(quality_case)
    with pytest.raises(ExternalToolError):
        _build_quality(
            quality_case,
            chimera_runner=_FaultAfterChimera(quality_case.chimera_runner, phase),
        )
    attempt_dir = _only_new_attempt(quality_case, before)
    _assert_no_transients(attempt_dir)
    _assert_logs_exist(attempt_dir, expected_logs)


def test_build_quality_cleans_partial_native_decompression(
    quality_case: _QualityCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """native map 解压只写出一块就失败时，partial MRC 不得残留。"""

    def _copy_one_block_then_fail(source: Any, target: Any, *, length: int) -> None:
        target.write(source.read(min(length, 4096)))
        raise _InjectedFailure("native decompression failure")

    monkeypatch.setattr(quality.shutil, "copyfileobj", _copy_one_block_then_fail)
    before = _attempt_dirs(quality_case)
    with pytest.raises(_InjectedFailure):
        _build_quality(quality_case)
    attempt_dir = _only_new_attempt(quality_case, before)
    _assert_no_transients(attempt_dir)
    _assert_logs_exist(attempt_dir, ("molmap", "correlation"))


def test_build_quality_cleans_mapq_outputs_when_runner_raises_before_return(
    quality_case: _QualityCase,
) -> None:
    """MapQ 已生成 Q CIF 但尚未返回时失败，递归大产物仍必须清理。"""
    before = _attempt_dirs(quality_case)
    with pytest.raises(ExternalToolError):
        _build_quality(
            quality_case,
            mapq_runner=_FaultAfterMapQ(quality_case.mapq_runner),
        )
    attempt_dir = _only_new_attempt(quality_case, before)
    _assert_no_transients(attempt_dir)
    _assert_logs_exist(attempt_dir, ("molmap", "correlation", "mapq"))


@pytest.mark.parametrize("phase", ["geometry", "quality", "provenance"])
def test_build_quality_cleans_after_qc_failure(
    quality_case: _QualityCase,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    """geometry、质量 artifact 与 provenance QC 失败都不得绕过 scratch 清理。"""
    if phase == "geometry":
        monkeypatch.setattr(quality, "density_pair_errors", lambda *args, **kwargs: ["injected"])
        expected_logs = ("molmap",)
    elif phase == "quality":
        monkeypatch.setattr(
            quality,
            "quality_artifact_errors",
            lambda *args, **kwargs: ["injected"],
        )
        expected_logs = ("molmap", "correlation", "mapq")
    else:
        monkeypatch.setattr(
            quality,
            "quality_provenance_errors",
            lambda *args, **kwargs: ["injected"],
        )
        expected_logs = ("molmap", "correlation", "mapq")

    before = _attempt_dirs(quality_case)
    with pytest.raises((RuntimeError, ExternalToolError)):
        _build_quality(quality_case)
    attempt_dir = _only_new_attempt(quality_case, before)
    _assert_no_transients(attempt_dir)
    _assert_logs_exist(attempt_dir, expected_logs)


@pytest.mark.parametrize("writer_name", ["atomic_save_npz", "write_jsonl", "write_report"])
def test_build_quality_cleans_when_formal_artifact_writer_raises(
    quality_case: _QualityCase,
    monkeypatch: pytest.MonkeyPatch,
    writer_name: str,
) -> None:
    """正式产物 writer 已落盘后抛错，attempt scratch 仍必须异常安全清理。"""
    before = _attempt_dirs(quality_case)
    original = getattr(quality, writer_name)

    def _write_then_fail(*args: Any, **kwargs: Any) -> None:
        original(*args, **kwargs)
        raise _InjectedFailure(f"{writer_name} failure")

    with monkeypatch.context() as patch:
        patch.setattr(quality, writer_name, _write_then_fail)
        with pytest.raises(_InjectedFailure):
            _build_quality(quality_case)

    first_attempt = _only_new_attempt(quality_case, before)
    _assert_no_transients(first_attempt)
    _assert_logs_exist(first_attempt, ("molmap", "correlation", "mapq"))

    # 三件套部分落盘也不得被误当成 skip；完整落盘则允许安全 skip。
    retry = _build_quality(quality_case)
    assert retry["status"] in {"success", "skipped"}
    for attempt_dir in _attempt_dirs(quality_case):
        _assert_no_transients(attempt_dir)


def test_build_quality_valid_trio_skip_does_not_touch_scratch(
    quality_case: _QualityCase,
) -> None:
    """合法质量三件套的 skip 不创建新 attempt，也不回扫历史 scratch。"""
    first = _build_quality(quality_case)
    assert first["status"] == "success"
    historical = (
        quality_case.scratch_root
        / quality_case.run_id
        / "stage_f"
        / "1abc"
        / "historical_attempt"
    )
    historical.mkdir(parents=True)
    sentinel = historical / "must_not_be_touched.mrc"
    sentinel.write_bytes(b"historical")
    before = _attempt_dirs(quality_case)

    skipped = _build_quality(
        quality_case,
        chimera_runner=_DoNotRunChimera(),
        mapq_runner=_DoNotRunMapQ(quality_case.mapq_runner.mapq_cmd_path),
    )
    assert skipped["status"] == "skipped"
    assert _attempt_dirs(quality_case) == before
    assert sentinel.read_bytes() == b"historical"


def test_quality_attempt_scope_cleans_only_current_attempt(tmp_path: Path) -> None:
    """清理仅限当前 attempt，不得跨 PDB、旧 attempt 或 run。"""
    scratch = tmp_path / "scratch"
    current = scratch / "run_a" / "stage_f" / "1abc" / "current"
    siblings = [
        scratch / "run_a" / "stage_f" / "1abc" / "old_attempt" / "keep.mrc",
        scratch / "run_a" / "stage_f" / "2def" / "attempt" / "keep.cif",
        scratch / "run_b" / "stage_f" / "1abc" / "attempt" / "keep.map",
    ]
    current.mkdir(parents=True)
    for sentinel in siblings:
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_bytes(b"keep")

    with pytest.raises(_InjectedFailure):
        with quality._quality_attempt_scope(current):
            (current / "canonical.mrc").write_bytes(b"large")
            nested = current / "nested"
            nested.mkdir()
            (nested / "partial.cif.tmp.42").write_bytes(b"partial")
            (current / "molmap.stdout.log").write_text("evidence", encoding="utf-8")
            raise _InjectedFailure("scope failure")

    _assert_no_transients(current)
    assert (current / "molmap.stdout.log").read_text(encoding="utf-8") == "evidence"
    for sentinel in siblings:
        assert sentinel.read_bytes() == b"keep"


def test_quality_attempt_scope_isolated_under_concurrency(tmp_path: Path) -> None:
    """并发 attempt 中一个异常退出时，不得提前删除另一个的在途文件。"""
    scratch = tmp_path / "scratch" / "run" / "stage_f" / "1abc"
    failing_attempt = scratch / "attempt_a"
    active_attempt = scratch / "attempt_b"
    failing_attempt.mkdir(parents=True)
    active_attempt.mkdir(parents=True)
    both_created = threading.Barrier(2)
    failed_cleaned = threading.Event()

    def _failing_worker() -> None:
        try:
            with quality._quality_attempt_scope(failing_attempt):
                (failing_attempt / "large.mrc").write_bytes(b"a")
                (failing_attempt / "worker.log").write_text("a", encoding="utf-8")
                both_created.wait(timeout=5)
                raise _InjectedFailure("worker a")
        except _InjectedFailure:
            failed_cleaned.set()

    def _active_worker() -> None:
        with quality._quality_attempt_scope(active_attempt):
            live_file = active_attempt / "large.mrc"
            live_file.write_bytes(b"b")
            (active_attempt / "worker.log").write_text("b", encoding="utf-8")
            both_created.wait(timeout=5)
            assert failed_cleaned.wait(timeout=5)
            assert live_file.read_bytes() == b"b"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_failing_worker), executor.submit(_active_worker)]
        for future in futures:
            future.result(timeout=10)

    _assert_no_transients(failing_attempt)
    _assert_no_transients(active_attempt)
    assert (failing_attempt / "worker.log").is_file()
    assert (active_attempt / "worker.log").is_file()


def test_quality_attempt_scope_records_unlink_failure_and_preserves_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    transient 删除失败时落盘小型证据，并保留原始 attempt 异常链。

    该场景同时验证 cleanup 故障不会删除小日志，也不会扩大到兄弟
    attempt。被操作系统拒绝删除的大文件保留，供后续受控重试。
    """
    scratch = tmp_path / "scratch" / "run" / "stage_f" / "1abc"
    attempt = scratch / "current_attempt"
    sibling = scratch / "sibling_attempt"
    attempt.mkdir(parents=True)
    sibling.mkdir(parents=True)
    locked_transient = attempt / "locked.mrc"
    small_log = attempt / "mapq.stderr.log"
    sibling_sentinel = sibling / "must_not_be_touched.mrc"
    original_unlink = Path.unlink

    def _deny_only_locked_transient(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == locked_transient:
            raise PermissionError("injected transient lock")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", _deny_only_locked_transient)
    with pytest.raises(RuntimeError) as captured:
        with quality._quality_attempt_scope(attempt):
            locked_transient.write_bytes(b"large")
            small_log.write_text("diagnostic log", encoding="utf-8")
            sibling_sentinel.write_bytes(b"sibling")
            raise _InjectedFailure("primary build failure")

    assert isinstance(captured.value.__cause__, _InjectedFailure)
    assert "primary build failure" in str(captured.value)
    assert "scratch cleanup also failed" in str(captured.value)
    assert locked_transient.read_bytes() == b"large"
    assert small_log.read_text(encoding="utf-8") == "diagnostic log"
    assert sibling_sentinel.read_bytes() == b"sibling"

    evidence_path = attempt / "cleanup_errors.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == 1
    assert evidence["attempt_dir"] == str(attempt)
    assert len(evidence["failures"]) == 1
    assert "unlink_failed:" in evidence["failures"][0]
    assert "PermissionError" in evidence["failures"][0]
    assert "injected transient lock" in evidence["failures"][0]
