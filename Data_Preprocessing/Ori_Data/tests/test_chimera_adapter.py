"""用 fake executable 验证 Chimera 适配层命令、日志和失败语义。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from chimera import ChimeraRunner, run_external_tool
from failures import ExternalToolError, ToolFailureCode


def _write_fake_chimera(path: Path) -> None:
    """写一个读取适配器脚本、伪造 MRC/CC 输出的命令行程序。"""
    path.write_text(
        """from pathlib import Path
import re
import sys
import time

if '--version' in sys.argv:
    print('UCSF Chimera fake 1.19')
    raise SystemExit(0)
mode = 'ok'
if '--mode' in sys.argv:
    mode = sys.argv[sys.argv.index('--mode') + 1]
if mode == 'exit':
    raise SystemExit(7)
if mode == 'fatal':
    print('Traceback (most recent call last):')
    raise SystemExit(0)
if mode == 'sleep':
    time.sleep(5)
script = Path(sys.argv[sys.argv.index('--script') + 1])
text = script.read_text(encoding='utf-8')
if 'saveStep 1 saveRegion all' in text:
    match = re.search(r'volume #2 save \\\"([^\\\"]+)\\\"', text)
    Path(match.group(1)).write_bytes(b'fake-mrc')
if 'ADALIGAND_CC_CONTOUR_BEGIN' in text:
    print('ADALIGAND_CC_CONTOUR_BEGIN')
    print('correlation = 8.1e-1, correlation about mean = 7.2E-1')
    print('ADALIGAND_CC_CONTOUR_END')
if 'ADALIGAND_CC_ALL_BEGIN' in text:
    print('ADALIGAND_CC_ALL_BEGIN')
    print('correlation = 0.51, correlation about mean = -1.2e-1')
    print('ADALIGAND_CC_ALL_END')
""",
        encoding="utf-8",
    )


def test_molmap_script_forces_full_region_step_one_and_save_contract(tmp_path: Path) -> None:
    """molmap 必须显式禁用体素上限并保存完整 step=1 网格。"""
    fake = tmp_path / "fake.py"
    _write_fake_chimera(fake)
    model = tmp_path / "model.cif"
    canonical = tmp_path / "canonical.mrc"
    output = tmp_path / "sim.mrc"
    model.write_text("data_x\n", encoding="utf-8")
    canonical.write_bytes(b"map")
    runner = ChimeraRunner([sys.executable, str(fake)], timeout_seconds=10)

    runner.molmap_on_grid(
        model,
        canonical,
        output,
        resolution=2.8,
        scratch_dir=tmp_path / "scratch",
    )

    script = (tmp_path / "scratch" / "molmap.py").read_text(encoding="utf-8")
    assert f"rc('open {model.resolve().as_posix()}')" in script
    assert f"rc('open {canonical.resolve().as_posix()}')" in script
    assert "volume #1 region all step 1 limitVoxelCount false" in script
    assert "molmap #0 2.8 onGrid #1 modelId #2 showDialog false" in script
    assert "saveStep 1 saveRegion all" in script
    assert output.read_bytes() == b"fake-mrc"


def test_measure_correlations_parses_scientific_notation_and_contour_semantics(tmp_path: Path) -> None:
    """四个量按 marker 唯一解析，实验图必须在脚本中先打开。"""
    fake = tmp_path / "fake.py"
    _write_fake_chimera(fake)
    exp = tmp_path / "exp.mrc"
    sim = tmp_path / "sim.mrc"
    exp.write_bytes(b"exp")
    sim.write_bytes(b"sim")
    runner = ChimeraRunner([sys.executable, str(fake)], timeout_seconds=10)

    values, _ = runner.measure_correlations(
        exp,
        sim,
        contour=0.025,
        scratch_dir=tmp_path / "cc",
    )

    assert values == {
        "cc_contour": 0.81,
        "cc_contour_about_mean": 0.72,
        "cc_all": 0.51,
        "cc_all_about_mean": -0.12,
    }
    script = (tmp_path / "cc" / "correlation.py").read_text(encoding="utf-8")
    assert script.index(exp.resolve().as_posix()) < script.index(sim.resolve().as_posix())
    assert "FitMap.map_overlap_and_correlation" in script
    assert "experimental_map, simulated_map, True" in script
    assert "experimental_map, simulated_map, False" in script


def test_missing_contour_skips_only_two_contour_values(tmp_path: Path) -> None:
    """缺 recommended contour 仍计算 nonzero-mask 两项，不令整个样本失败。"""
    fake = tmp_path / "fake.py"
    _write_fake_chimera(fake)
    exp = tmp_path / "exp.mrc"
    sim = tmp_path / "sim.mrc"
    exp.write_bytes(b"exp")
    sim.write_bytes(b"sim")
    runner = ChimeraRunner([sys.executable, str(fake)], timeout_seconds=10)
    values, _ = runner.measure_correlations(
        exp,
        sim,
        contour=None,
        scratch_dir=tmp_path / "cc_none",
    )
    assert values["cc_contour"] is None
    assert values["cc_contour_about_mean"] is None
    assert values["cc_all"] == 0.51
    assert values["cc_all_about_mean"] == -0.12


@pytest.mark.parametrize(
    ("mode", "expected_code"),
    [
        ("exit", ToolFailureCode.NONZERO_EXIT),
        ("fatal", ToolFailureCode.FATAL_LOG),
        ("sleep", ToolFailureCode.TIMEOUT),
    ],
)
def test_external_runner_rejects_nonzero_fatal_and_timeout(
    tmp_path: Path,
    mode: str,
    expected_code: ToolFailureCode,
) -> None:
    """返回码 0 不能掩盖 fatal log，超时必须走独立错误码。"""
    fake = tmp_path / "fake.py"
    _write_fake_chimera(fake)
    timeout = 0.1 if mode == "sleep" else 10
    with pytest.raises(ExternalToolError) as captured:
        run_external_tool(
            [sys.executable, str(fake), "--mode", mode],
            cwd=tmp_path / mode,
            stdout_path=tmp_path / mode / "stdout.log",
            stderr_path=tmp_path / mode / "stderr.log",
            timeout_seconds=timeout,
        )
    assert captured.value.code is expected_code
