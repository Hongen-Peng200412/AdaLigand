"""Stage G run-scoped gate、分布模式与显式阈值边界测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from filtering import apply_map_filter_config, load_filter_config, load_stage_statuses, run_stage_g
from io_utils import write_jsonl
from reports import stage_report_path, stage_result, write_stage_results


def _schema_v2_config(**updates: object) -> dict[str, object]:
    """
    构造测试专用 Stage G schema v2 配置。

    输入参数:
        - updates: object, 需要覆盖的显式字段

    输出:
        - config: dict[str, object], 完整 map-level 配置
    """
    config: dict[str, object] = {
        "schema_version": 2,
        "cc_field": "cc_all_about_mean",
        "cc_min": 0.6,
        "resolution_max": 5.0,
        "resolution_comparison": "inclusive",
        "ligand_q_min": 0.7,
        "pocket_q_min": 0.65,
        "qualified_pair_fraction_min": 0.5,
        "empty_pocket": "fail_and_count_denominator",
        "keep_only_maps_that_pass": True,
        "keep_all_occurrences_in_passing_map": True,
    }
    config.update(updates)
    return config


def test_filter_config_accepts_only_explicit_schema_v2(tmp_path: Path) -> None:
    """唯一正式 schema 是 v2；旧 v1 与缺失固定策略都必须显式拒绝。"""
    config_path = tmp_path / "filter.json"
    config_path.write_text(json.dumps(_schema_v2_config()), encoding="utf-8")
    config = load_filter_config(config_path)
    assert config["schema_version"] == 2
    assert config["cc_field"] == "cc_all_about_mean"

    config_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema_version must be 2"):
        load_filter_config(config_path)

    invalid = _schema_v2_config()
    invalid.pop("empty_pocket")
    config_path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError, match="fields disagree"):
        load_filter_config(config_path)


def test_map_filter_counts_empty_pocket_and_keeps_all_occurrences(tmp_path: Path) -> None:
    """Q 使用严格大于，空口袋计分母；map 通过后保留其全部 occurrence。"""
    config_path = tmp_path / "filter.json"
    config_path.write_text(
        json.dumps(_schema_v2_config(qualified_pair_fraction_min=1 / 3)),
        encoding="utf-8",
    )
    config = load_filter_config(config_path)
    records = [
        {
            "pdb_id": "1aaa",
            "candidate_id": 0,
            "q_score": 0.71,
            "pocket_q_score": 0.66,
            "pocket_status": "ok",
            "map_resolution": 5.0,
            "cc_all_about_mean": 0.6,
        },
        {
            "pdb_id": "1aaa",
            "candidate_id": 1,
            "q_score": 0.7,
            "pocket_q_score": 0.9,
            "pocket_status": "ok",
            "map_resolution": 5.0,
            "cc_all_about_mean": 0.6,
        },
        {
            "pdb_id": "1aaa",
            "candidate_id": 2,
            "q_score": 0.9,
            "pocket_q_score": None,
            "pocket_status": "no_receptor_atoms_within_radius",
            "map_resolution": 5.0,
            "cc_all_about_mean": 0.6,
        },
        {
            "pdb_id": "2bbb",
            "candidate_id": 0,
            "q_score": 0.9,
            "pocket_q_score": 0.9,
            "pocket_status": "ok",
            "map_resolution": 2.0,
            "cc_all_about_mean": 0.59,
        },
    ]
    kept, excluded_maps, diagnostics = apply_map_filter_config(records, config)
    assert kept == [
        {"pdb_id": "1aaa", "candidate_id": 0},
        {"pdb_id": "1aaa", "candidate_id": 1},
        {"pdb_id": "1aaa", "candidate_id": 2},
    ]
    assert excluded_maps[0]["pdb_id"] == "2bbb"
    assert excluded_maps[0]["reasons"] == ["selected_cc_below_min"]
    first = diagnostics[0]
    assert first["cc_pass"] is True
    assert first["resolution_pass"] is True
    assert first["n_pair_pass"] == 1
    assert first["n_empty_pocket_occurrences"] == 1
    assert first["qualified_fraction"] == pytest.approx(1 / 3)
    assert first["qualified_fraction_pass"] is True
    assert first["map_pass"] is True
    assert first["occurrences"][1]["reasons"] == ["ligand_q_not_strictly_above_min"]
    assert first["occurrences"][2]["reasons"] == ["empty_pocket"]


def test_map_filter_rejects_inconsistent_pdb_level_values(tmp_path: Path) -> None:
    """同一 PDB 的 selected CC 或 resolution 不唯一属于上游契约错误。"""
    config_path = tmp_path / "filter.json"
    config_path.write_text(json.dumps(_schema_v2_config()), encoding="utf-8")
    config = load_filter_config(config_path)
    records = [
        {
            "pdb_id": "1aaa",
            "candidate_id": 0,
            "q_score": 0.8,
            "pocket_q_score": 0.8,
            "pocket_status": "ok",
            "map_resolution": 2.0,
            "cc_all_about_mean": 0.7,
        },
        {
            "pdb_id": "1aaa",
            "candidate_id": 1,
            "q_score": 0.8,
            "pocket_q_score": 0.8,
            "pocket_status": "ok",
            "map_resolution": 2.0,
            "cc_all_about_mean": 0.71,
        },
    ]
    with pytest.raises(RuntimeError, match="not one finite PDB-level value"):
        apply_map_filter_config(records, config)

    records[1]["cc_all_about_mean"] = 0.7
    records[1]["map_resolution"] = 2.1
    with pytest.raises(RuntimeError, match="map_resolution is not one finite"):
        apply_map_filter_config(records, config)


def test_pocket_q_equal_is_strict_failure_and_low_fraction_excludes_map(tmp_path: Path) -> None:
    """口袋 Q 等于阈值必须失败；合格比例低于含等号门时淘汰整张 map。"""
    config_path = tmp_path / "filter.json"
    config_path.write_text(
        json.dumps(_schema_v2_config(qualified_pair_fraction_min=0.75)),
        encoding="utf-8",
    )
    config = load_filter_config(config_path)
    records = [
        {
            "pdb_id": "1aaa",
            "candidate_id": 0,
            "q_score": 0.9,
            "pocket_q_score": 0.9,
            "pocket_status": "ok",
            "map_resolution": 2.0,
            "cc_all_about_mean": 0.8,
        },
        {
            "pdb_id": "1aaa",
            "candidate_id": 1,
            "q_score": 0.9,
            "pocket_q_score": 0.65,
            "pocket_status": "ok",
            "map_resolution": 2.0,
            "cc_all_about_mean": 0.8,
        },
    ]
    kept, excluded_maps, diagnostics = apply_map_filter_config(records, config)
    assert kept == []
    assert excluded_maps[0]["reasons"] == ["qualified_pair_fraction_below_min"]
    assert diagnostics[0]["qualified_fraction"] == 0.5
    assert diagnostics[0]["occurrences"][1]["reasons"] == [
        "pocket_q_not_strictly_above_min"
    ]


def test_selected_contour_cc_null_excludes_map_without_fallback(tmp_path: Path) -> None:
    """选定 contour CC 为 null 时淘汰 map，不能偷换成另一种可用 CC。"""
    config_path = tmp_path / "filter.json"
    config_path.write_text(
        json.dumps(_schema_v2_config(cc_field="cc_contour", cc_min=0.1)),
        encoding="utf-8",
    )
    config = load_filter_config(config_path)
    records = [
        {
            "pdb_id": "1aaa",
            "candidate_id": 0,
            "q_score": 0.9,
            "pocket_q_score": 0.9,
            "pocket_status": "ok",
            "map_resolution": 2.0,
            "cc_contour": None,
        }
    ]
    kept, excluded_maps, diagnostics = apply_map_filter_config(records, config)
    assert kept == []
    assert excluded_maps[0]["reasons"] == ["selected_cc_unavailable"]
    assert diagnostics[0]["cc_value"] is None
    assert diagnostics[0]["cc_pass"] is False

    records.append({**records[0], "candidate_id": 1, "cc_contour": 0.5})
    with pytest.raises(RuntimeError, match="mixes null and numeric"):
        apply_map_filter_config(records, config)


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
                stage_result("2bbb", stage, "known_failed", reason="no_occurrences"),
            ],
        )
    write_jsonl(
        root / "parse" / "1aaa" / "occurrences.jsonl",
        [
            {"candidate_id": 3, "type_tag": "small_molecule"},
            {"candidate_id": 4, "type_tag": "small_molecule"},
        ],
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
            },
            {
                "pdb_id": "1aaa",
                "candidate_id": 4,
                "q_score": 0.8,
                "q_score_median": 0.81,
                "q_score_min": 0.7,
                "n_valid": 10,
                "n_present": 10,
                "pocket_q_score": 0.7,
                "pocket_q_score_median": 0.71,
                "pocket_q_score_min": 0.6,
                "pocket_n_valid": 20,
                "pocket_n_atoms": 20,
                "pocket_status": "ok",
                "pocket_radius_angstrom": 6.0,
                "map_resolution": 2.8,
                "contour_status": "missing_primary_contour",
                "cc_contour": None,
                "cc_contour_about_mean": None,
                "cc_all": 0.5,
                "cc_all_about_mean": 0.4,
            },
        ],
    )
    (root / "quality" / "1aaa.provenance.json").write_text("{}", encoding="utf-8")


def test_analyze_mode_never_writes_final_keep_list(tmp_path: Path) -> None:
    """阈值未授权时只产分布/pending candidates，不伪装成最终筛选。"""
    _write_g_fixture(tmp_path, "run1")
    result = run_stage_g(tmp_path, "run1", mode="analyze")
    assert result["status"] == "analysis_complete_filter_pending"
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
    assert distribution["n_candidate_occurrences"] == 2
    assert distribution["n_known_failed_pdb"] == 1
    assert distribution["pocket_status_counts"] == {
        "no_receptor_atoms_within_radius": 1,
        "ok": 1,
    }
    assert distribution["fields"]["pocket_q_score"]["n_null"] == 1


def test_filter_mode_writes_map_diagnostics_and_all_occurrences(tmp_path: Path) -> None:
    """显式 v2 配置按 map 过滤，并把通过 map 的全部 occurrence 写入 keep list。"""
    _write_g_fixture(tmp_path, "run1")
    config_path = tmp_path / "filter.json"
    config_path.write_text(
        json.dumps(
            _schema_v2_config(
                cc_min=0.4,
                resolution_max=2.8,
                ligand_q_min=0.6,
                pocket_q_min=0.65,
                qualified_pair_fraction_min=0.5,
            )
        ),
        encoding="utf-8",
    )
    result = run_stage_g(tmp_path, "run1", mode="filter", config_path=config_path)
    assert result == {
        "status": "success",
        "n_passing_maps": 1,
        "n_excluded_maps": 0,
        "n_kept_occurrences": 2,
    }
    assert (tmp_path / "keep_list.jsonl").read_text(encoding="utf-8").splitlines() == [
        '{"candidate_id": 3, "pdb_id": "1aaa"}',
        '{"candidate_id": 4, "pdb_id": "1aaa"}',
    ]
    diagnostics = json.loads(
        (
            tmp_path
            / "reports"
            / "runs"
            / "run1"
            / "stage_g"
            / "map_filter_diagnostics.jsonl"
        ).read_text(encoding="utf-8")
    )
    assert diagnostics["n_occurrences"] == 2
    assert diagnostics["n_pair_pass"] == 1
    assert diagnostics["qualified_fraction"] == 0.5
    assert diagnostics["map_pass"] is True
    summary = json.loads(
        (
            tmp_path / "reports" / "runs" / "run1" / "stage_g" / "summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["config"]["schema_version"] == 2
    assert len(summary["config_sha256"]) == 64
    assert len(summary["filter_manifest_sha256"]) == 64
    assert summary["map_exclusion_reason_counts"] == {}
    assert summary["n_known_failed_pdb"] == 1
