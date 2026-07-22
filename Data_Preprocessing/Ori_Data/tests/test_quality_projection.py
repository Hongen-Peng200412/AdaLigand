"""Stage F occurrence Q-score 严格投影与四原始量聚合测试。"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"

from adaligand_preprocessing.artifacts.failures import ExternalToolError, ToolFailureCode
from adaligand_preprocessing.stages.stage_f import (
    POCKET_RADIUS_ANGSTROM,
    build_quality_records,
    compute_occurrence_pocket_qscores,
    project_occurrence_qscores,
)


def _row(atom_id: str, atom_name: str, auth_seq: str, x: float) -> dict[str, str]:
    """构造一个 selected atom_site 行。"""
    return {
        "group_PDB": "HETATM",
        "id": atom_id,
        "type_symbol": "C",
        "label_atom_id": atom_name,
        "label_alt_id": ".",
        "label_comp_id": "NAG",
        "label_asym_id": "B",
        "label_entity_id": "2",
        "label_seq_id": ".",
        "pdbx_PDB_ins_code": "?",
        "Cartn_x": str(x),
        "Cartn_y": "2.0",
        "Cartn_z": "3.0",
        "auth_atom_id": atom_name,
        "auth_comp_id": "NAG",
        "auth_asym_id": "Z",
        "auth_seq_id": auth_seq,
        "pdbx_PDB_model_num": "1",
    }


def _receptor_row(atom_id: str, x: float) -> dict[str, str]:
    """构造一个参与口袋包络的 ``group_PDB=ATOM`` 受体重原子行。"""
    row = _row(atom_id, f"C{atom_id}", "1", x)
    row.update(
        {
            "group_PDB": "ATOM",
            "label_comp_id": "ALA",
            "label_asym_id": "A",
            "label_entity_id": "1",
            "label_seq_id": "1",
            "auth_comp_id": "ALA",
            "auth_asym_id": "A",
        }
    )
    return row


def _branched_fixture() -> tuple[list[dict], dict[str, np.ndarray], dict[str, dict], list[dict], dict[str, float]]:
    """两个 residue 都含 C1，另有一个模板缺失原子的 BRANCHED fixture。"""
    atom_dtype = np.dtype([("residue_id", np.int32)])
    atoms = np.asarray([(1,), (2,), (2,)], dtype=atom_dtype)
    occurrences = [
        {
            "candidate_id": 5,
            "object_key": "BRANCHED:NAG-NAG:test",
            "components": [
                {
                    "index": 1,
                    "ccd_id": "NAG",
                    "label_asym_id": "B",
                    "label_seq_id": 9,
                    "auth_asym_id": "Z",
                    "auth_seq_id": 9,
                    "icode": "",
                },
                {
                    "index": 2,
                    "ccd_id": "NAG",
                    "label_asym_id": "B",
                    "label_seq_id": 10,
                    "auth_asym_id": "Z",
                    "auth_seq_id": 10,
                    "icode": "",
                },
            ],
        }
    ]
    coords = np.asarray([[1, 2, 3], [4, 2, 3], [np.nan, np.nan, np.nan]], dtype=np.float32)
    coords_arrays = {
        "coords_5": coords,
        "present_5": np.asarray([True, True, False]),
    }
    objects = {
        "BRANCHED:NAG-NAG:test": {
            "atoms": atoms,
            "atom_names": np.asarray(["C1", "C1", "O9"], dtype=object),
        }
    }
    rows = [_row("20", "C1", "10", 4), _row("10", "C1", "9", 1)]
    q_by_id = {"10": 0.2, "20": 0.8}
    return occurrences, coords_arrays, objects, rows, q_by_id


def test_project_qscore_uses_component_identity_not_repeated_atom_name_or_row_order() -> None:
    """BRANCHED 重名原子和 MapQ 反序仍严格投到 LigandObject 正确行。"""
    occurrences, coords, objects, rows, q_by_id = _branched_fixture()
    arrays = project_occurrence_qscores(occurrences, coords, objects, rows, q_by_id)
    np.testing.assert_allclose(arrays["qscore_5"][:2], [0.2, 0.8])
    assert np.isnan(arrays["qscore_5"][2])
    assert arrays["qscore_5"].dtype == np.float32


def test_project_qscore_rejects_coordinate_or_identity_mismatch() -> None:
    """present 原子的沉积坐标不一致时，禁止用最近邻猜回。"""
    occurrences, coords, objects, rows, q_by_id = _branched_fixture()
    rows[1]["Cartn_x"] = "100.0"
    with pytest.raises(ExternalToolError) as captured:
        project_occurrence_qscores(occurrences, coords, objects, rows, q_by_id)
    assert captured.value.code is ToolFailureCode.ATOM_MAPPING


def test_project_qscore_allows_same_atom_site_id_in_distinct_occurrences() -> None:
    """两个 occurrence 可独立引用同一沉积原子，且各自保存相同的原子 Q。"""
    occurrences, coords, objects, rows, q_by_id = _branched_fixture()
    repeated = dict(occurrences[0])
    repeated["candidate_id"] = 6
    occurrences.append(repeated)
    coords["coords_6"] = coords["coords_5"].copy()
    coords["present_6"] = np.asarray([True, False, False])

    arrays = project_occurrence_qscores(occurrences, coords, objects, rows, q_by_id)

    assert arrays["qscore_6"][0] == arrays["qscore_5"][0]
    assert np.isnan(arrays["qscore_6"][1:]).all()


def test_project_qscore_rejects_cross_occurrence_component_identity_drift() -> None:
    """跨 occurrence 复用不得借空 label_seq 将同一原子投到不同 component。"""
    occurrences, coords, objects, rows, q_by_id = _branched_fixture()
    repeated = copy.deepcopy(occurrences[0])
    repeated["candidate_id"] = 6
    repeated["components"][0]["label_seq_id"] = 999
    occurrences.append(repeated)
    coords["coords_6"] = coords["coords_5"].copy()
    coords["present_6"] = coords["present_5"].copy()

    with pytest.raises(ExternalToolError) as captured:
        project_occurrence_qscores(occurrences, coords, objects, rows, q_by_id)
    assert captured.value.code is ToolFailureCode.ATOM_MAPPING


def test_project_qscore_rejects_duplicate_atom_site_id_within_one_occurrence() -> None:
    """同一 occurrence 内两个 LigandObject 槽位仍不得复用一个沉积原子。"""
    occurrences, coords, objects, rows, q_by_id = _branched_fixture()
    atom_dtype = np.dtype([("residue_id", np.int32)])
    objects["BRANCHED:NAG-NAG:test"]["atoms"] = np.asarray([(1,), (1,)], dtype=atom_dtype)
    objects["BRANCHED:NAG-NAG:test"]["atom_names"] = np.asarray(["C1", "C1"], dtype=object)
    coords["coords_5"] = np.asarray([[1, 2, 3], [1, 2, 3]], dtype=np.float32)
    coords["present_5"] = np.asarray([True, True])

    with pytest.raises(ExternalToolError) as captured:
        project_occurrence_qscores(occurrences, coords, objects, rows, q_by_id)
    assert captured.value.code is ToolFailureCode.ATOM_MAPPING


def test_pocket_qscore_uses_union_of_six_angstrom_atom_envelopes() -> None:
    """非球形配体两端各自附近的受体原子都应进入同一 occurrence 口袋。"""
    occurrences, coords, _, ligand_rows, _ = _branched_fixture()
    receptor_rows = [
        _receptor_row("1", -4.5),  # 到 x=1 配体原子 5.5 Å
        _receptor_row("2", 9.5),   # 到 x=4 配体原子 5.5 Å
        _receptor_row("3", 20.0),  # 位于固定包络之外
    ]
    q_by_id = {"1": 0.3, "2": 0.7, "3": 0.9}
    arrays = compute_occurrence_pocket_qscores(
        occurrences,
        coords,
        [*ligand_rows, *receptor_rows],
        q_by_id,
    )
    np.testing.assert_array_equal(arrays["pocket_atom_site_id_5"], [1, 2])
    np.testing.assert_allclose(arrays["pocket_qscore_5"], [0.3, 0.7])
    assert arrays["pocket_atom_site_id_5"].dtype == np.int64
    assert arrays["pocket_qscore_5"].dtype == np.float32


def test_pocket_qscore_zero_receptor_atoms_is_explicit_empty_occurrence() -> None:
    """固定包络为空时保存 typed empty 数组，不得连带淘汰同 PDB 的其他 occurrence。"""
    occurrences, coords, _, ligand_rows, _ = _branched_fixture()
    arrays = compute_occurrence_pocket_qscores(
        occurrences,
        coords,
        [*ligand_rows, _receptor_row("1", 100.0)],
        {"1": 0.5},
    )
    assert arrays["pocket_atom_site_id_5"].dtype == np.int64
    assert arrays["pocket_qscore_5"].dtype == np.float32
    assert arrays["pocket_atom_site_id_5"].shape == arrays["pocket_qscore_5"].shape == (0,)


def test_quality_records_save_mean_median_min_counts_and_four_raw_cc() -> None:
    """每行保存兼容 mean 字段、median/min、计数及四个全局原始 CC。"""
    occurrences, coords, objects, rows, q_by_id = _branched_fixture()
    arrays = project_occurrence_qscores(occurrences, coords, objects, rows, q_by_id)
    arrays.update(
        {
            "pocket_atom_site_id_5": np.asarray([1, 2], dtype=np.int64),
            "pocket_qscore_5": np.asarray([0.3, 0.7], dtype=np.float32),
        }
    )
    cc_values = {
        "cc_contour": 0.7,
        "cc_contour_about_mean": 0.6,
        "cc_all": 0.5,
        "cc_all_about_mean": 0.4,
    }
    records = build_quality_records(
        "1abc",
        occurrences,
        coords,
        arrays,
        resolution=2.8,
        cc_values=cc_values,
        contour_status="ok",
    )
    assert len(records) == 1
    record = records[0]
    assert record["q_score"] == pytest.approx(0.5)
    assert record["q_score_median"] == pytest.approx(0.5)
    assert record["q_score_min"] == pytest.approx(0.2)
    assert record["n_valid"] == record["n_present"] == 2
    assert record["pocket_q_score"] == pytest.approx(0.5)
    assert record["pocket_q_score_median"] == pytest.approx(0.5)
    assert record["pocket_q_score_min"] == pytest.approx(0.3)
    assert record["pocket_n_valid"] == record["pocket_n_atoms"] == 2
    assert record["pocket_status"] == "ok"
    assert record["pocket_radius_angstrom"] == POCKET_RADIUS_ANGSTROM
    assert {key: record[key] for key in cc_values} == cc_values


def test_quality_records_preserve_empty_pocket_as_null_without_filtering() -> None:
    """空口袋 occurrence 的聚合为 JSON null/count=0，并保留配体 Q 与整图 CC。"""
    occurrences, coords, objects, rows, q_by_id = _branched_fixture()
    arrays = project_occurrence_qscores(occurrences, coords, objects, rows, q_by_id)
    arrays.update(
        {
            "pocket_atom_site_id_5": np.empty((0,), dtype=np.int64),
            "pocket_qscore_5": np.empty((0,), dtype=np.float32),
        }
    )
    records = build_quality_records(
        "1abc",
        occurrences,
        coords,
        arrays,
        resolution=2.8,
        cc_values={
            "cc_contour": 0.7,
            "cc_contour_about_mean": 0.6,
            "cc_all": 0.5,
            "cc_all_about_mean": 0.4,
        },
        contour_status="ok",
    )
    record = records[0]
    assert record["q_score"] == pytest.approx(0.5)
    assert record["pocket_q_score"] is None
    assert record["pocket_q_score_median"] is None
    assert record["pocket_q_score_min"] is None
    assert record["pocket_n_valid"] == record["pocket_n_atoms"] == 0
    assert record["pocket_status"] == "no_receptor_atoms_within_radius"
