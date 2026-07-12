"""通用 release gate 的 full-run 与 strict-smoke 策略测试。"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


CODE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE_ROOT / "code"))

from io_utils import write_jsonl
from reports import stage_report_path, stage_result, write_stage_results


def test_strict_smoke_gate_rejects_known_failure_but_full_gate_allows_it(tmp_path: Path) -> None:
    """真实 smoke 必须实际成功；正式全量 gate 才允许已解释的样本不适用。"""
    write_jsonl(
        tmp_path / "raw" / "pair_list.jsonl",
        [{"pdb_id": "1aaa", "emdb_id": "EMD-1"}],
    )
    write_stage_results(
        stage_report_path(tmp_path, "run1", "stage_f", 0, 1),
        [stage_result("1aaa", "stage_f", "known_failed", reason="missing_map")],
    )
    base_command = [
        sys.executable,
        str(CODE_ROOT / "scripts" / "stage_release_gate.py"),
        "--root",
        str(tmp_path),
        "--run_id",
        "run1",
        "--stages",
        "stage_f",
    ]
    full = subprocess.run(
        [*base_command, "--gate_name", "full_gate"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert full.returncode == 0, full.stderr

    smoke = subprocess.run(
        [*base_command, "--gate_name", "smoke_gate", "--require_success"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert smoke.returncode != 0
    assert "strict smoke gate rejects known failures" in smoke.stderr
