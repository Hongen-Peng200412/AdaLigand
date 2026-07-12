"""Stage C source-dirty mtime 快照契约测试。"""

from __future__ import annotations

import json
import os
import runpy
import sys
from datetime import datetime
from pathlib import Path

import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
for path in (CODE_DIR, SCRIPTS_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from io_utils import sha256_file, write_jsonl
from snapshot_source_dirty import _aware_timestamp, main


def test_snapshot_freezes_exact_timezone_aware_mtime_window(monkeypatch, tmp_path):
    """快照严格使用开区间下界、闭区间上界，并把清单哈希写入 summary。"""
    mmcif_dir = tmp_path / "raw" / "rcsb_mmcif"
    mmcif_dir.mkdir(parents=True)
    ids = ("1aaa", "2bbb", "3ccc", "4ddd")
    write_jsonl(
        tmp_path / "raw" / "pair_list.jsonl",
        [{"pdb_id": pdb_id} for pdb_id in ids],
    )
    start_text = "2026-07-11T15:46:58+08:00"
    end_text = "2026-07-12T05:30:00+08:00"
    start = _aware_timestamp(start_text)
    end = _aware_timestamp(end_text)
    for pdb_id, mtime in zip(
        ids,
        (start, start + 1.0, end, end + 1.0),
        strict=True,
    ):
        path = mmcif_dir / f"{pdb_id}.cif"
        path.write_text(f"data_{pdb_id}\n", encoding="utf-8")
        os.utime(path, (mtime, mtime))

    output = tmp_path / "reports" / "dirty_ids.txt"
    summary = tmp_path / "reports" / "dirty_summary.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "snapshot_source_dirty.py",
            "--root", str(tmp_path),
            "--mtime_after", start_text,
            "--mtime_at_or_before", end_text,
            "--expected_count", "2",
            "--output", str(output),
            "--summary", str(summary),
        ],
    )

    main()

    assert output.read_text(encoding="utf-8").splitlines() == ["2bbb", "3ccc"]
    record = json.loads(summary.read_text(encoding="utf-8"))
    assert record["n_pdb_ids"] == 2
    assert record["ids_sha256"] == sha256_file(output)


def test_snapshot_rejects_timezone_naive_bounds():
    """mtime 边界必须携带 UTC offset，避免服务器时区变化导致集合漂移。"""
    with pytest.raises(ValueError, match="UTC offset"):
        _aware_timestamp(datetime(2026, 7, 11, 15, 46, 58).isoformat())


def test_source_repair_rejects_run_id_path_traversal(monkeypatch, tmp_path):
    """repair_run_id 必须是单级安全目录名，不能逃逸 reports/runs。"""
    script = SCRIPTS_DIR / "c_source_repair.py"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(script),
            "--root", str(tmp_path),
            "--pdb_ids_file", str(tmp_path / "ids.txt"),
            "--ids_sha256", "0" * 64,
            "--expected_count", "1",
            "--repair_run_id", "../escape",
            "--mode", "audit",
            "--n_jobs", "1",
        ],
    )

    with pytest.raises(ValueError, match="run_id"):
        runpy.run_path(str(script), run_name="__main__")
