"""Stage E contour、E1 provenance 与局部 ligand-area 契约测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from density import (
    EXP_SCHEMA_VERSION,
    LIGAND_AREA_SCHEMA_VERSION,
    MRC_GENERATED_ORIGIN_MODE,
    MRC_SOURCE_ORIGIN_MODE,
    MRC_TARGET_VOXEL_SIZE,
    SIM_SCHEMA_VERSION,
    build_ligand_area_arrays,
    experimental_density_errors,
    experimental_density_identity,
    extract_recommended_contour,
    ligand_area_errors,
    simulated_density_errors,
    vdw_radius,
)
from mrc import (
    POCKET_MRC_ALGORITHM,
    POCKET_MRC_ANCESTOR_SHA256,
    POCKET_MRC_VENDOR_SHA256,
    POCKET_RESAMPLE_ALL_DIFF,
)
from reports import ensure_filtered_stage_run_is_isolated


def _valid_experimental_density() -> dict[str, np.ndarray]:
    """构造携带 Pocket 祖传 provenance 和非单位实际 voxel 的 E1 v2 artifact。"""
    volume = np.zeros((6, 8, 10), dtype=np.float32)
    volume[1:5, 1:7, 2:8] = np.arange(144, dtype=np.float32).reshape(4, 6, 6) + 1
    contour_scale = 0.4
    contour_native = np.asarray(0.02, dtype=np.float32)
    return {
        "grid": volume[None],
        "voxel_size": np.asarray([0.997, 1.001, 0.999], dtype=np.float32),
        "origin": np.zeros((3,), dtype=np.float32),
        "contour": contour_native.copy(),
        "contour_native": contour_native,
        "contour_canonical": np.asarray(
            np.float32(float(contour_native) * contour_scale)
        ),
        "contour_scale_to_canonical": np.asarray(contour_scale, dtype=np.float64),
        "contour_present": np.asarray(True, dtype=bool),
        "contour_status": np.asarray("ok"),
        "contour_path": np.asarray("map.contour_list.contour[0].level"),
        "contour_source": np.asarray("AUTHOR"),
        "schema_version": np.asarray(EXP_SCHEMA_VERSION, dtype=np.uint16),
        "source_map_sha256": np.asarray("a" * 64),
        "source_meta_sha256": np.asarray("b" * 64),
        "source_map_size": np.asarray(10, dtype=np.int64),
        "source_map_mtime_ns": np.asarray(20, dtype=np.int64),
        "source_meta_size": np.asarray(30, dtype=np.int64),
        "source_meta_mtime_ns": np.asarray(40, dtype=np.int64),
        "target_voxel_size": np.asarray(MRC_TARGET_VOXEL_SIZE, dtype=np.float32),
        "mrc_algorithm": np.asarray(POCKET_MRC_ALGORITHM),
        "mrc_ancestor_sha256": np.asarray(POCKET_MRC_ANCESTOR_SHA256),
        "mrc_vendor_sha256": np.asarray(POCKET_MRC_VENDOR_SHA256),
        "source_origin_mode": np.asarray(MRC_SOURCE_ORIGIN_MODE),
        "native_shape_zyx": np.asarray([4, 6, 8], dtype=np.int64),
        "even_input_shape_zyx": np.asarray([4, 6, 8], dtype=np.int64),
        "canonical_shape_zyx": np.asarray([6, 8, 10], dtype=np.int64),
        "resample_mode": np.asarray(POCKET_RESAMPLE_ALL_DIFF),
    }


def test_experimental_density_v2_accepts_actual_voxel_and_rejects_v1() -> None:
    """E1 v2 接受 Pocket 返回的实际 voxel，并阻断旧重采样 schema/algorithm。"""
    arrays = _valid_experimental_density()
    assert experimental_density_errors(
        arrays,
        source_map_size=10,
        source_map_mtime_ns=20,
        source_meta_size=30,
        source_meta_mtime_ns=40,
    ) == []

    old = dict(arrays)
    old["schema_version"] = np.asarray(1, dtype=np.uint16)
    old["mrc_algorithm"] = np.asarray("scipy.signal.resample_float32_sequential_axes_v1")
    errors = experimental_density_errors(
        old,
        source_map_size=10,
        source_map_mtime_ns=20,
        source_meta_size=30,
        source_meta_mtime_ns=40,
    )
    assert "exp_contract:schema_version" in errors
    assert "exp_contract:mrc_algorithm" in errors
    assert EXP_SCHEMA_VERSION == SIM_SCHEMA_VERSION == LIGAND_AREA_SCHEMA_VERSION == 2

    wrong_contour = dict(arrays)
    wrong_contour["contour_canonical"] = wrong_contour["contour_native"].copy()
    wrong_errors = experimental_density_errors(
        wrong_contour,
        source_map_size=10,
        source_map_mtime_ns=20,
        source_meta_size=30,
        source_meta_mtime_ns=40,
    )
    assert "exp_value:contour_canonical_scale" in wrong_errors


def test_contour_reads_only_unique_primary_main_map() -> None:
    """主图唯一 primary level 生效，additional map 的伪候选不得参与。"""
    metadata = {
        "map": {
            "contour_list": {
                "contour": [
                    {"level": "0.025", "primary": True, "source": "AUTHOR"},
                    {"level": 0.1, "primary": False},
                ]
            }
        },
        "interpretation": {
            "additional_map_list": {
                "additional_map": [{"contour_list": {"contour": {"primary": True}}}]
            }
        },
    }
    info = extract_recommended_contour(metadata)
    assert info.value == 0.025
    assert info.status == "ok"
    assert info.path == "map.contour_list.contour[0].level"
    assert info.source == "AUTHOR"


def test_contour_accepts_dict_and_missing_source() -> None:
    """单 dict 形态和缺 source 都不妨碍有效主图 level。"""
    info = extract_recommended_contour(
        {"map": {"contour_list": {"contour": {"level": 81.2, "primary": "true"}}}}
    )
    assert info.value == 81.2
    assert info.source is None


def test_contour_missing_ambiguous_and_nonfinite_are_null() -> None:
    """无 primary、多 primary 和 NaN 都必须返回可审计 null，禁止猜值。"""
    missing = extract_recommended_contour({"map": {"contour_list": {"contour": []}}})
    ambiguous = extract_recommended_contour(
        {
            "map": {
                "contour_list": {
                    "contour": [
                        {"level": 1, "primary": True},
                        {"level": 1, "primary": True},
                    ]
                }
            }
        }
    )
    nonfinite = extract_recommended_contour(
        {"map": {"contour_list": {"contour": {"level": "nan", "primary": True}}}}
    )
    assert missing.value is None and missing.status == "missing_primary_contour"
    assert ambiguous.value is None and ambiguous.status == "ambiguous_primary_contour"
    assert nonfinite.value is None and nonfinite.status == "nonfinite_primary_level"


def test_vdw_uses_locked_common_values_and_element_fallback() -> None:
    """计划锁定的 C/N/O/P/S 值精确，卤素使用逐元素 RDKit 半径而非统一默认。"""
    assert vdw_radius(6) == 1.70
    assert vdw_radius(7) == 1.55
    assert vdw_radius(8) == 1.52
    assert vdw_radius(15) == 1.80
    assert vdw_radius(16) == 1.80
    assert vdw_radius(17) > 0
    assert vdw_radius(17) != vdw_radius(35)


def test_ligand_area_local_stencil_sparse_order_union_and_world_centroid() -> None:
    """非零 origin 下稀疏 ZYX、union 和世界 XYZ 质心必须精确一致。"""
    shape = (8, 9, 10)
    voxel = np.ones((3,), dtype=np.float32)
    origin = np.asarray([10.0, 20.0, 30.0], dtype=np.float32)
    arrays = build_ligand_area_arrays(
        shape,
        voxel,
        origin,
        {
            2: np.asarray([[13.0, 24.0, 35.0]], dtype=np.float32),
            7: np.asarray([[14.0, 24.0, 35.0]], dtype=np.float32),
        },
        {
            2: np.asarray([6], dtype=np.int16),
            7: np.asarray([8], dtype=np.int16),
        },
    )
    errors = ligand_area_errors(
        arrays,
        grid_shape_zyx=shape,
        voxel_size_xyz=voxel,
        origin_xyz=origin,
        candidate_ids=[2, 7],
    )
    assert errors == []
    for candidate_id in (2, 7):
        indices = arrays[f"mask_{candidate_id}"]
        linear = np.ravel_multi_index(indices.T, shape)
        assert np.all(np.diff(linear) > 0)
        expected_xyz = origin + np.asarray(
            [indices[:, 2].mean(), indices[:, 1].mean(), indices[:, 0].mean()],
            dtype=np.float32,
        )
        np.testing.assert_allclose(arrays[f"centroid_voxel_{candidate_id}"], expected_xyz)
    reconstructed = np.zeros(shape, dtype=bool)
    for candidate_id in (2, 7):
        reconstructed[tuple(arrays[f"mask_{candidate_id}"].T)] = True
    np.testing.assert_array_equal(arrays["union_mask"][0], reconstructed)


def test_ligand_area_handles_boundary_clipping_without_duplicate_indices() -> None:
    """靠近图边界的球只裁剪出图部分，不能产生越界或重复 COO。"""
    arrays = build_ligand_area_arrays(
        (4, 4, 4),
        np.ones((3,), dtype=np.float32),
        np.zeros((3,), dtype=np.float32),
        {0: np.asarray([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0]], dtype=np.float32)},
        {0: np.asarray([6, 6], dtype=np.int16)},
    )
    indices = arrays["mask_0"]
    assert np.all(indices >= 0)
    assert np.all(indices < 4)
    assert len(indices) == len(np.unique(indices, axis=0))


def test_ligand_area_centroid_qc_compares_the_declared_float32_value() -> None:
    """大坐标下先量化期望值再精确比较，不能把合法 float32 舍入误判为失败。"""
    shape = (2, 2, 2)
    indices = np.asarray([[0, 0, 0], [0, 1, 0], [1, 0, 1]], dtype=np.int32)
    origin = np.asarray([277.0, 300.0, 500.0], dtype=np.float32)
    voxel = np.ones((3,), dtype=np.float32)
    expected = (
        origin.astype(np.float64)
        + np.asarray([1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0], dtype=np.float64)
    ).astype(np.float32)
    union = np.zeros((1, *shape), dtype=bool)
    union[0][tuple(indices.T)] = True
    arrays = {
        "mask_0": indices,
        "centroid_voxel_0": expected,
        "union_mask": union,
    }

    assert ligand_area_errors(
        arrays,
        grid_shape_zyx=shape,
        voxel_size_xyz=voxel,
        origin_xyz=origin,
        candidate_ids=[0],
    ) == []

    arrays["centroid_voxel_0"] = expected.copy()
    arrays["centroid_voxel_0"][0] = np.nextafter(expected[0], np.float32(np.inf))
    assert "ligand_area_value:centroid:0" in ligand_area_errors(
        arrays,
        grid_shape_zyx=shape,
        voxel_size_xyz=voxel,
        origin_xyz=origin,
        candidate_ids=[0],
    )


def test_simulated_density_validator_rejects_plane_and_geometry_mismatch() -> None:
    """E2 完成判据必须同时拦截伪二维内容和 origin 漂移。"""
    exp = _valid_experimental_density()
    sim_volume = np.zeros_like(exp["grid"][0])
    sim_volume[2, 1:5, 1:6] = 1
    sim = {
        "grid": sim_volume[None],
        "voxel_size": exp["voxel_size"].copy(),
        "origin": np.asarray([1.0, 0.0, 0.0], dtype=np.float32),
        "schema_version": np.asarray(SIM_SCHEMA_VERSION, dtype=np.uint16),
        "resolution": np.asarray(2.8, dtype=np.float32),
        "chimera_version": np.asarray("UCSF Chimera 1.19"),
        "source_exp_identity_sha256": np.asarray(experimental_density_identity(exp)),
        "source_cif_sha256": np.asarray("b" * 64),
        "normalized_model_sha256": np.asarray("c" * 64),
        "chimera_script_sha256": np.asarray("d" * 64),
        "source_exp_size": np.asarray(10, dtype=np.int64),
        "source_exp_mtime_ns": np.asarray(20, dtype=np.int64),
        "source_cif_size": np.asarray(30, dtype=np.int64),
        "source_cif_mtime_ns": np.asarray(40, dtype=np.int64),
        "strict_hetatm_removed": np.asarray(True),
        "model_selection": np.asarray("first_model_stage_c_altloc_heavy_group_PDB_ATOM"),
        "generated_mrc_origin_mode": np.asarray(MRC_GENERATED_ORIGIN_MODE),
    }
    errors = simulated_density_errors(
        sim,
        exp_arrays=exp,
        receptor_coords=np.asarray([[2.0, 2.0, 2.0]], dtype=np.float32),
        resolution=2.8,
        source_exp_size=10,
        source_exp_mtime_ns=20,
        source_cif_size=30,
        source_cif_mtime_ns=40,
    )
    assert "sim:density_content:single_z_slice" in errors
    assert "density_pair:origin_mismatch" in errors

    sim["source_exp_identity_sha256"] = np.asarray("f" * 64)
    mismatched = simulated_density_errors(
        sim,
        exp_arrays=exp,
        receptor_coords=np.asarray([[2.0, 2.0, 2.0]], dtype=np.float32),
        resolution=2.8,
        source_exp_size=10,
        source_exp_mtime_ns=20,
        source_cif_size=30,
        source_cif_mtime_ns=40,
    )
    assert "sim_provenance:source_exp_identity_mismatch" in mismatched


def test_filtered_stage_e_cannot_overwrite_formal_or_existing_status(tmp_path: Path) -> None:
    """Stage E 子集修复必须使用没有正式 A/E 证据的独立 run id。"""
    ids_path = tmp_path / "ids.txt"
    ids_path.write_text("1abc\n", encoding="utf-8")
    formal_guard = tmp_path / "reports" / "runs" / "formal" / "stage_a" / "guard.json"
    formal_guard.parent.mkdir(parents=True)
    formal_guard.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="fresh independent run_id"):
        ensure_filtered_stage_run_is_isolated(
            tmp_path,
            "formal",
            "stage_e",
            ids_path,
        )

    existing = (
        tmp_path
        / "reports"
        / "runs"
        / "repair_used"
        / "stage_e"
        / "status.part_0000_of_0001.jsonl"
    )
    existing.parent.mkdir(parents=True)
    existing.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="fresh independent run_id"):
        ensure_filtered_stage_run_is_isolated(
            tmp_path,
            "repair_used",
            "stage_e",
            ids_path,
        )

    ensure_filtered_stage_run_is_isolated(
        tmp_path,
        "repair_fresh",
        "stage_e",
        ids_path,
    )
