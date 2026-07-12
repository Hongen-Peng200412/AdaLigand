"""Stage G run-scoped gate、分布模式与显式阈值边界测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from filtering import apply_filter_config, load_filter_config, load_stage_statuses, run_stage_g
from io_utils import write_jsonl
from reports import stage_report_path, stage_result, write_stage_results


def test_filter_config_inclusive_boundary_and_resolution_policies(tmp_path: Path) -> None:
    """Q 等于阈值、resolution 等于上限均保留；soft flag 与 exclude 必须显式区分。"""
    config_path = tmp_path / "filter.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "q_score_min": 0.5,
                "resolution_max": 3.0,
                "resolution_policy": "exclude",
                "comparison": "inclusive",
            }
        ),
        encoding="utf-8",
    )
    config = load_filter_config(config_path)
    records = [
        {"pdb_id": "1aaa", "candidate_id": 0, "q_score": 0.5, "map_resolution": 3.0},
        {"pdb_id": "1aaa", "candidate_id": 1, "q_score": 0.49, "map_resolution": 2.0},
        {"pdb_id": "2bbb", "candidate_id": 0, "q_score": 0.8, "map_resolution": 3.1},
    ]
    kept, excluded, flagged = apply_filter_config(records, config)
    assert kept == [{"pdb_id": "1aaa", "candidate_id": 0}]
    assert flagged == []
    assert [item["reasons"] for item in excluded] == [
        ["q_score_below_min"],
        ["resolution_above_max"],
    ]
    config["resolution_policy"] = "flag_only"
    kept, excluded, flagged = apply_filter_config(records, config)
    assert {item["candidate_id"] for item in kept if item["pdb_id"] == "2bbb"} == {0}
    assert flagged == [
        {"pdb_id": "2bbb", "candidate_id": 0, "flags": ["resolution_above_max"]}
    ]


def test_load_stage_statuses_rejects_unknown_and_silent_missing(tmp_path: Path) -> None:
    """unknown failure 与缺样本都必须阻塞，不能被旧报告或路径存在掩盖。"""
    path = stage_report_path(tmp_path, "run1", "stage_d", 0, 1)
    write_stage_results(
        path,
        [
            stage_result("1aaa", "stage_d", "success"),
            stage_result("2bbb", "stage_d", "unknown_failed", reason="bug"),
        ],
    )
    with pytest.raises(RuntimeError, match="unknown failures"):
        load_stage_statuses(tmp_path, "run1", "stage_d", {"1aaa", "2bbb"})
    with pytest.raises(RuntimeError, match="silent/extra"):
        load_stage_statuses(tmp_path, "run1", "stage_d", {"1aaa", "2bbb", "3ccc"})


def _write_g_fixture(root: Path, run_id: str) -> None:
    """写两个 PDB：一个全成功、一个明确 known_failed 的最小 G 输入。"""
    write_jsonl(
        root / "raw" / "pair_list.jsonl",
        [
            {"pdb_id": "1aaa", "emdb_id": "EMD-1"},
            {"pdb_id": "2bbb", "emdb_id": "EMD-2"},
        ],
    )
    for stage in ("stage_d", "stage_e", "stage_f"):
        write_stage_results(
            stage_report_path(root, run_id, stage, 0, 1),
            [
                stage_result("1aaa", stage, "success"),
                stage_result("2bbb", stage, "known_failed", reason="missing_map"),
            ],
        )
    write_jsonl(
        root / "parse" / "1aaa" / "occurrences.jsonl",
        [{"candidate_id": 3, "type_tag": "small_molecule"}],
    )
    write_jsonl(
        root / "quality" / "1aaa.jsonl",
        [
            {
                "pdb_id": "1aaa",
                "candidate_id": 3,
                "q_score": 0.6,
                "q_score_median": 0.61,
                "q_score_min": 0.4,
                "n_valid": 8,
                "n_present": 8,
                "pocket_q_score": None,
                "pocket_q_score_median": None,
                "pocket_q_score_min": None,
                "pocket_n_valid": 0,
                "pocket_n_atoms": 0,
                "pocket_status": "no_receptor_atoms_within_radius",
                "pocket_radius_angstrom": 6.0,
                "map_resolution": 2.8,
                "contour_status": "missing_primary_contour",
                "cc_contour": None,
                "cc_contour_about_mean": None,
                "cc_all": 0.5,
                "cc_all_about_mean": 0.4,
            }
        ],
    )
    (root / "quality" / "1aaa.provenance.json").write_text("{}", encoding="utf-8")


def test_analyze_mode_never_writes_final_keep_list(tmp_path: Path) -> None:
    """阈值未授权时只产分布/pending candidates，不伪装成最终筛选。"""
    _write_g_fixture(tmp_path, "run1")
    result = run_stage_g(tmp_path, "run1", mode="analyze")
    assert result["status"] == "analysis_complete_threshold_pending"
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
    assert distribution["n_candidate_occurrences"] == 1
    assert distribution["n_known_failed_pdb"] == 1
    assert distribution["pocket_status_counts"] == {"no_receptor_atoms_within_radius": 1}
    assert distribution["fields"]["pocket_q_score"]["n_null"] == 1


def test_filter_mode_writes_stable_keep_list_only_with_explicit_config(tmp_path: Path) -> None:
    """显式配置通过后才生成正式 keep_list，并保存配置 hash/排除报告。"""
    _write_g_fixture(tmp_path, "run1")
    config_path = tmp_path / "filter.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "q_score_min": 0.6,
                "resolution_max": None,
                "resolution_policy": "flag_only",
                "comparison": "inclusive",
            }
        ),
        encoding="utf-8",
    )
    result = run_stage_g(tmp_path, "run1", mode="filter", config_path=config_path)
    assert result["n_kept"] == 1
    assert (tmp_path / "keep_list.jsonl").read_text(encoding="utf-8").strip().startswith(
        '{"candidate_id": 3, "pdb_id": "1aaa"}'
    )
