"""Stage E contour、E1 provenance 与局部 ligand-area 契约测试。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

import density as density_module
import io_utils as io_utils_module
from density import (
    EXP_SCHEMA_VERSION,
    LIGAND_AREA_SCHEMA_VERSION,
    LIGAND_AREA_DISTANCE_PREDICATE,
    LIGAND_AREA_ORIGIN_SEMANTICS,
    LIGAND_AREA_STORAGE_ENCODING,
    LIGAND_AREA_VOXEL_CENTER_FORMULA,
    LIGAND_AREA_VOXEL_CENTER_DTYPE,
    LIGAND_AREA_VOXEL_CENTER_OFFSET_XYZ,
    MRC_GENERATED_ORIGIN_MODE,
    MRC_SOURCE_ORIGIN_MODE,
    MRC_TARGET_VOXEL_SIZE,
    SIM_SCHEMA_VERSION,
    VDW_RADIUS_SOURCE,
    build_ligand_area,
    build_ligand_area_arrays,
    experimental_density_errors,
    experimental_density_identity,
    extract_recommended_contour,
    ensure_model_map_frame_compatible,
    ligand_area_errors,
    simulated_density_errors,
    vdw_radius,
)
from contracts import CArtifactState, CInspection
from failures import KnownFailureCode, KnownSampleFailure
from io_utils import atomic_save_npz, atomic_save_npz_compressed, sha256_file, write_jsonl
from mrc import (
    POCKET_MRC_ALGORITHM,
    POCKET_MRC_ANCESTOR_SHA256,
    POCKET_MRC_VENDOR_SHA256,
    POCKET_RESAMPLE_ALL_DIFF,
)
from reports import ensure_filtered_stage_run_is_isolated
from voxel_gt_pocket_legacy import _build_voxel_center_coords_xyz


_E3_SOURCE_MANIFEST = "c" * 64


def _add_e3_metadata(
    arrays: dict[str, np.ndarray],
    *,
    shape: tuple[int, int, int],
    voxel: np.ndarray,
    origin: np.ndarray,
    source_manifest_sha256: str = _E3_SOURCE_MANIFEST,
) -> dict[str, np.ndarray]:
    """为纯 mask 数组补齐 E3 v3 自描述几何与 provenance。"""
    complete = dict(arrays)
    complete.update(
        {
            "schema_version": np.asarray(LIGAND_AREA_SCHEMA_VERSION, dtype=np.uint16),
            "source_manifest_sha256": np.asarray(source_manifest_sha256),
            "centroid_coordinate_system": np.asarray("world_xyz_angstrom"),
            "mask_index_order": np.asarray("zyx"),
            "vdw_radius_source": np.asarray(VDW_RADIUS_SOURCE),
            "grid_shape_zyx": np.asarray(shape, dtype=np.int64),
            "voxel_size_xyz": np.asarray(voxel, dtype=np.float32),
            "origin_xyz": np.asarray(origin, dtype=np.float32),
            "origin_semantics": np.asarray(LIGAND_AREA_ORIGIN_SEMANTICS),
            "voxel_center_offset_xyz": np.asarray(
                LIGAND_AREA_VOXEL_CENTER_OFFSET_XYZ,
                dtype=np.float32,
            ),
            "voxel_center_formula": np.asarray(LIGAND_AREA_VOXEL_CENTER_FORMULA),
            "voxel_center_dtype": np.asarray(LIGAND_AREA_VOXEL_CENTER_DTYPE),
            "distance_predicate": np.asarray(LIGAND_AREA_DISTANCE_PREDICATE),
            "storage_encoding": np.asarray(LIGAND_AREA_STORAGE_ENCODING),
        }
    )
    return complete


def _ligand_area_validation_kwargs(
    *,
    shape: tuple[int, int, int],
    voxel: np.ndarray,
    origin: np.ndarray,
    candidate_ids: list[int],
    source_manifest_sha256: str = _E3_SOURCE_MANIFEST,
) -> dict[str, object]:
    """集中构造 E3 validator 的固定参数，避免测试遗漏几何身份。"""
    return {
        "grid_shape_zyx": shape,
        "voxel_size_xyz": voxel,
        "origin_xyz": origin,
        "candidate_ids": candidate_ids,
        "source_manifest_sha256": source_manifest_sha256,
    }


def _pocket_centers_xyz_for_indices(
    indices_zyx: np.ndarray,
    *,
    voxel: np.ndarray,
    origin: np.ndarray,
) -> np.ndarray:
    """直接调用祖传整图函数并抽取给定 ZYX 索引的中心。"""
    indices = np.asarray(indices_zyx, dtype=np.int64)
    voxel_f32 = np.asarray(voxel, dtype=np.float32)
    origin_f32 = np.asarray(origin, dtype=np.float32)
    shape = tuple(int(value) for value in (indices.max(axis=0) + 1))
    centers = _build_voxel_center_coords_xyz(shape, origin_f32, voxel_f32)
    return centers.reshape(*shape, 3)[tuple(indices.T)]


def _full_grid_reference_indices(
    shape: tuple[int, int, int],
    *,
    voxel: np.ndarray,
    origin: np.ndarray,
    coord: np.ndarray,
    radius: float,
) -> np.ndarray:
    """以 Pocket float32 中心和 atom 坐标做不裁 bbox 的独立全图 membership。"""
    indices = np.argwhere(np.ones(shape, dtype=bool)).astype(np.int32)
    centers = _build_voxel_center_coords_xyz(
        shape,
        np.asarray(origin, dtype=np.float32),
        np.asarray(voxel, dtype=np.float32),
    )
    coord_f32 = np.asarray(coord, dtype=np.float32).reshape(3)
    distance2 = np.sum(
        (centers.astype(np.float64) - coord_f32.astype(np.float64)) ** 2,
        axis=1,
    )
    return indices[distance2 <= radius * radius + 1e-8]


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


def _write_ligand_area_build_inputs(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path]:
    """写入一个最小但完整的 E3 构建输入，并冻结 Stage C inspection。"""
    pdb_id = "1abc"
    density_dir = root / "density" / pdb_id
    parse_dir = root / "parse" / pdb_id
    object_dir = root / "ligand_objects"
    density_dir.mkdir(parents=True)
    parse_dir.mkdir(parents=True)
    object_dir.mkdir(parents=True)

    exp_path = density_dir / "exp.npz"
    sim_path = density_dir / "sim.npz"
    output_path = density_dir / "ligand_area.npz"
    atomic_save_npz(exp_path, **_valid_experimental_density())
    atomic_save_npz(sim_path, sentinel=np.arange(8, dtype=np.float32))

    occurrence = {"candidate_id": 0, "object_key": "CCD:LIG"}
    write_jsonl(parse_dir / "occurrences.jsonl", [occurrence])
    atomic_save_npz(
        parse_dir / "ligand_coords.npz",
        coords_0=np.asarray([[3.5, 3.5, 3.5]], dtype=np.float32),
        present_0=np.asarray([True], dtype=bool),
    )
    atoms = np.zeros((1,), dtype=[("element", np.int16)])
    atoms["element"] = 6
    atomic_save_npz(object_dir / "CCD_LIG.npz", atoms=atoms)

    inspection = CInspection(CArtifactState.COMPLETE, (), (occurrence,))
    monkeypatch.setattr(density_module, "inspect_stage_c", lambda *_: inspection)
    return exp_path, sim_path, output_path


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
    assert EXP_SCHEMA_VERSION == SIM_SCHEMA_VERSION == 2
    assert LIGAND_AREA_SCHEMA_VERSION == 3

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
    arrays = _add_e3_metadata(
        build_ligand_area_arrays(
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
        ),
        shape=shape,
        voxel=voxel,
        origin=origin,
    )
    errors = ligand_area_errors(
        arrays,
        **_ligand_area_validation_kwargs(
            shape=shape,
            voxel=voxel,
            origin=origin,
            candidate_ids=[2, 7],
        ),
    )
    assert errors == []
    for candidate_id in (2, 7):
        indices = arrays[f"mask_{candidate_id}"]
        linear = np.ravel_multi_index(indices.T, shape)
        assert np.all(np.diff(linear) > 0)
        centers_xyz = _pocket_centers_xyz_for_indices(
            indices,
            voxel=voxel,
            origin=origin,
        )
        expected_xyz = centers_xyz.astype(np.float64).mean(axis=0).astype(np.float32)
        np.testing.assert_array_equal(arrays[f"centroid_voxel_{candidate_id}"], expected_xyz)
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


def test_ligand_area_uses_corner_origin_and_anisotropic_voxel_centers() -> None:
    """反例必须只选中 +0.5 中心；旧 ``origin+index*voxel`` 会得到空 mask。"""
    shape = (3, 3, 3)
    voxel = np.asarray([4.0, 5.0, 6.0], dtype=np.float32)
    origin = np.asarray([10.0, -20.0, 30.0], dtype=np.float32)
    atom_xyz = origin + 0.5 * voxel
    arrays = build_ligand_area_arrays(
        shape,
        voxel,
        origin,
        {0: atom_xyz[None]},
        {0: np.asarray([6], dtype=np.int16)},
    )

    np.testing.assert_array_equal(
        arrays["mask_0"],
        np.asarray([[0, 0, 0]], dtype=np.int32),
    )
    np.testing.assert_array_equal(arrays["centroid_voxel_0"], atom_xyz)
    old_formula_distance = float(np.linalg.norm(origin.astype(np.float64) - atom_xyz))
    assert old_formula_distance > vdw_radius(6)


def test_ligand_area_bbox_covers_pocket_float32_center_rounding() -> None:
    """实际中心 searchsorted 必须与 Pocket-f32 全图 reference 完全一致。"""
    shape = (3, 3, 4)
    voxel = np.asarray([0.30897918, 1.0, 1.0], dtype=np.float32)
    origin = np.asarray([0.02594091, 0.0, 0.0], dtype=np.float32)
    coord = np.asarray([[-0.90161115, 0.5, 0.5]], dtype=np.float32)
    arrays = build_ligand_area_arrays(
        shape,
        voxel,
        origin,
        {0: coord},
        {0: np.asarray([6], dtype=np.int16)},
    )

    expected_indices = _full_grid_reference_indices(
        shape,
        voxel=voxel,
        origin=origin,
        coord=coord[0],
        radius=vdw_radius(6),
    )
    np.testing.assert_array_equal(arrays["mask_0"], expected_indices)
    assert any(
        np.array_equal(row, np.asarray([0, 0, 2], dtype=np.int32))
        for row in arrays["mask_0"]
    )

    effective_radius = float(np.sqrt(vdw_radius(6) ** 2 + 1e-8))
    upper_without_float32_guard = int(
        np.floor(
            (float(coord[0, 0]) + effective_radius - float(origin[0]))
            / float(voxel[0])
            - 0.5
            + 1e-12
        )
    )
    assert upper_without_float32_guard == 1


def test_sparse_axis_adapter_matches_ancestor_full_grid_with_repeated_centers() -> None:
    """退化轴调用必须与祖传整图中心逐位一致，包括重复 float32 中心。"""
    shape = (3, 3, 20)
    voxel = np.ones((3,), dtype=np.float32)
    origin = np.asarray([1.0e9, 0.0, 0.0], dtype=np.float32)
    coord = np.asarray([[1.0e9, 0.5, 0.5]], dtype=np.float32)
    arrays = build_ligand_area_arrays(
        shape,
        voxel,
        origin,
        {0: coord},
        {0: np.asarray([6], dtype=np.int16)},
    )

    expected_indices = _full_grid_reference_indices(
        shape,
        voxel=voxel,
        origin=origin,
        coord=coord[0],
        radius=vdw_radius(6),
    )
    np.testing.assert_array_equal(arrays["mask_0"], expected_indices)
    assert len(np.unique(expected_indices[:, 2])) == shape[2]


def test_ligand_area_rejects_noncanonical_or_extra_dynamic_keys() -> None:
    """schema v3 不得把非法动态后缀或未知额外数组当成合法可跳过产物。"""
    shape = (3, 3, 3)
    voxel = np.ones((3,), dtype=np.float32)
    origin = np.zeros((3,), dtype=np.float32)
    arrays = _add_e3_metadata(
        build_ligand_area_arrays(
            shape,
            voxel,
            origin,
            {0: np.asarray([[0.5, 0.5, 0.5]], dtype=np.float32)},
            {0: np.asarray([6], dtype=np.int16)},
        ),
        shape=shape,
        voxel=voxel,
        origin=origin,
    )
    validation_kwargs = _ligand_area_validation_kwargs(
        shape=shape,
        voxel=voxel,
        origin=origin,
        candidate_ids=[0],
    )

    for extra_key in ("mask_00", "mask_bad", "centroid_voxel_00", "unexpected"):
        corrupted = dict(arrays)
        corrupted[extra_key] = np.asarray([1], dtype=np.int8)
        errors = ligand_area_errors(corrupted, **validation_kwargs)
        assert any(
            error.startswith("ligand_area_contract:unexpected_keys:")
            for error in errors
        )


def test_ligand_area_far_boundary_uses_last_voxel_center() -> None:
    """靠近远端边界的原子按角点 box 语义落到最后一个体素，且不越界。"""
    shape = (4, 5, 6)
    voxel = np.asarray([2.0, 3.0, 4.0], dtype=np.float32)
    origin = np.asarray([-10.0, 20.0, 100.0], dtype=np.float32)
    last_center = origin + (np.asarray(shape[::-1], dtype=np.float32) - 0.5) * voxel
    arrays = build_ligand_area_arrays(
        shape,
        voxel,
        origin,
        {9: last_center[None]},
        {9: np.asarray([8], dtype=np.int16)},
    )

    np.testing.assert_array_equal(
        arrays["mask_9"],
        np.asarray([[3, 4, 5]], dtype=np.int32),
    )
    np.testing.assert_array_equal(arrays["centroid_voxel_9"], last_center)


def test_ligand_area_v3_metadata_and_actual_zip_encoding_are_required(tmp_path: Path) -> None:
    """schema/几何元数据与真实 ZIP_DEFLATED 必须同时成立，不能只信 metadata。"""
    shape = (3, 3, 3)
    voxel = np.asarray([1.2, 1.4, 1.6], dtype=np.float32)
    origin = np.asarray([2.0, 3.0, 4.0], dtype=np.float32)
    arrays = _add_e3_metadata(
        build_ligand_area_arrays(
            shape,
            voxel,
            origin,
            {0: np.asarray([[2.6, 3.7, 4.8]], dtype=np.float32)},
            {0: np.asarray([6], dtype=np.int16)},
        ),
        shape=shape,
        voxel=voxel,
        origin=origin,
    )
    validation_kwargs = _ligand_area_validation_kwargs(
        shape=shape,
        voxel=voxel,
        origin=origin,
        candidate_ids=[0],
    )

    legacy = dict(arrays)
    legacy["schema_version"] = np.asarray(2, dtype=np.uint16)
    assert "ligand_area_contract:schema_version" in ligand_area_errors(
        legacy,
        **validation_kwargs,
    )

    wrong_geometry = dict(arrays)
    wrong_geometry["voxel_center_offset_xyz"] = np.zeros((3,), dtype=np.float32)
    wrong_geometry["voxel_center_formula"] = np.asarray("origin_xyz+index_xyz*voxel")
    geometry_errors = ligand_area_errors(wrong_geometry, **validation_kwargs)
    assert "ligand_area_contract:voxel_center_offset_xyz" in geometry_errors
    assert "ligand_area_contract:voxel_center_formula" in geometry_errors

    uncompressed_path = tmp_path / "uncompressed.npz"
    atomic_save_npz(uncompressed_path, **arrays)
    assert "ligand_area_storage:not_zip_deflated" in ligand_area_errors(
        arrays,
        artifact_path=uncompressed_path,
        **validation_kwargs,
    )

    compressed_path = tmp_path / "compressed.npz"

    def _validate(path: Path) -> None:
        with np.load(path, allow_pickle=False) as archive:
            loaded = {key: archive[key] for key in archive.files}
        assert ligand_area_errors(
            loaded,
            artifact_path=path,
            **validation_kwargs,
        ) == []

    atomic_save_npz_compressed(compressed_path, validator=_validate, **arrays)
    with np.load(compressed_path, allow_pickle=False) as archive:
        assert set(archive.files) == set(arrays)
        for key, expected in arrays.items():
            np.testing.assert_array_equal(archive[key], expected)
            assert archive[key].dtype == expected.dtype
            assert archive[key].shape == expected.shape
    with zipfile.ZipFile(compressed_path, "r") as archive:
        assert archive.infolist()
        assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in archive.infolist())


def test_compressed_atomic_write_failure_preserves_target_and_siblings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """写入中断只清理本次唯一临时文件；旧正式文件和兄弟 PDB 逐字节不变。"""
    target = tmp_path / "density" / "1abc" / "ligand_area.npz"
    sibling = tmp_path / "density" / "2def" / "ligand_area.npz"
    target.parent.mkdir(parents=True)
    sibling.parent.mkdir(parents=True)
    target.write_bytes(b"old-target")
    sibling.write_bytes(b"old-sibling")

    def _partial_write_then_fail(path: Path, **_: object) -> None:
        Path(path).write_bytes(b"partial-new-file")
        raise RuntimeError("injected compressed writer failure")

    monkeypatch.setattr(io_utils_module.np, "savez_compressed", _partial_write_then_fail)
    with pytest.raises(RuntimeError, match="injected compressed writer failure"):
        atomic_save_npz_compressed(
            target,
            validator=lambda _: None,
            value=np.arange(4, dtype=np.int32),
        )

    assert target.read_bytes() == b"old-target"
    assert sibling.read_bytes() == b"old-sibling"
    assert list(target.parent.glob(f".{target.name}.tmp.*.npz")) == []


def test_compressed_atomic_validation_failure_preserves_old_target(tmp_path: Path) -> None:
    """完整临时 NPZ 若未通过重读 validator，也不得覆盖旧正式文件。"""
    target = tmp_path / "ligand_area.npz"
    target.write_bytes(b"old-artifact")

    def _reject(_: Path) -> None:
        raise RuntimeError("injected validator failure")

    with pytest.raises(RuntimeError, match="injected validator failure"):
        atomic_save_npz_compressed(
            target,
            validator=_reject,
            value=np.arange(4, dtype=np.int32),
        )
    assert target.read_bytes() == b"old-artifact"
    assert list(tmp_path.glob(f".{target.name}.tmp.*.npz")) == []


def test_ligand_area_centroid_qc_compares_the_declared_float32_value() -> None:
    """大坐标下先量化期望值再精确比较，不能把合法 float32 舍入误判为失败。"""
    shape = (2, 2, 2)
    indices = np.asarray([[0, 0, 0], [0, 1, 0], [1, 0, 1]], dtype=np.int32)
    origin = np.asarray([277.0, 300.0, 500.0], dtype=np.float32)
    voxel = np.ones((3,), dtype=np.float32)
    expected = _pocket_centers_xyz_for_indices(
        indices,
        voxel=voxel,
        origin=origin,
    ).astype(np.float64).mean(axis=0).astype(np.float32)
    union = np.zeros((1, *shape), dtype=bool)
    union[0][tuple(indices.T)] = True
    arrays = _add_e3_metadata(
        {
            "mask_0": indices,
            "centroid_voxel_0": expected,
            "union_mask": union,
        },
        shape=shape,
        voxel=voxel,
        origin=origin,
    )

    assert ligand_area_errors(
        arrays,
        **_ligand_area_validation_kwargs(
            shape=shape,
            voxel=voxel,
            origin=origin,
            candidate_ids=[0],
        ),
    ) == []

    arrays["centroid_voxel_0"] = expected.copy()
    arrays["centroid_voxel_0"][0] = np.nextafter(expected[0], np.float32(np.inf))
    assert "ligand_area_value:centroid:0" in ligand_area_errors(
        arrays,
        **_ligand_area_validation_kwargs(
            shape=shape,
            voxel=voxel,
            origin=origin,
            candidate_ids=[0],
        ),
    )


def test_build_ligand_area_rebuilds_v2_then_skips_valid_v3_without_touching_exp_sim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """旧 v2 即使 overwrite=False 也重建；合法压缩 v3 幂等 skip，E1/E2 不漂移。"""
    exp_path, sim_path, output_path = _write_ligand_area_build_inputs(tmp_path, monkeypatch)
    exp_sha_before = sha256_file(exp_path)
    sim_sha_before = sha256_file(sim_path)

    atomic_save_npz(
        output_path,
        schema_version=np.asarray(2, dtype=np.uint16),
        source_manifest_sha256=np.asarray("legacy"),
        union_mask=np.zeros((1, 6, 8, 10), dtype=bool),
        mask_0=np.asarray([[0, 0, 0]], dtype=np.int32),
        centroid_voxel_0=np.zeros((3,), dtype=np.float32),
    )
    rebuilt = build_ligand_area(tmp_path, "1ABC", overwrite=False)
    assert rebuilt["status"] == "success"
    assert sha256_file(exp_path) == exp_sha_before
    assert sha256_file(sim_path) == sim_sha_before

    with np.load(output_path, allow_pickle=False) as archive:
        assert int(archive["schema_version"]) == 3
        assert str(archive["origin_semantics"].item()) == LIGAND_AREA_ORIGIN_SEMANTICS
        assert str(archive["storage_encoding"].item()) == LIGAND_AREA_STORAGE_ENCODING
    with zipfile.ZipFile(output_path, "r") as archive:
        assert all(info.compress_type == zipfile.ZIP_DEFLATED for info in archive.infolist())

    artifact_sha = sha256_file(output_path)
    skipped = build_ligand_area(tmp_path, "1abc", overwrite=False)
    assert skipped["status"] == "skipped"
    assert sha256_file(output_path) == artifact_sha
    assert sha256_file(exp_path) == exp_sha_before
    assert sha256_file(sim_path) == sim_sha_before


def test_density_import_for_e3_does_not_import_chimera_or_mapq() -> None:
    """E3 专用入口可只导入 density；类型注解不能触发 Chimera/MapQ 运行时导入。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(CODE_DIR), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    command = (
        "import sys; import density; "
        "assert 'chimera' not in sys.modules; "
        "assert 'mapq' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", command],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


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


def test_model_map_frame_policy_records_bounds_and_rejects_invalid_input() -> None:
    """frame mismatch 的 known 详情自包含，非法坐标仍为 unknown 路径。"""
    exp = _valid_experimental_density()
    outside = np.asarray([[1000.0, 1000.0, 1000.0]], dtype=np.float32)
    with pytest.raises(KnownSampleFailure) as caught:
        ensure_model_map_frame_compatible("2zhc", exp, outside)
    assert caught.value.code is KnownFailureCode.MODEL_MAP_FRAME_MISMATCH
    detail = caught.value.detail
    assert '"pdb_id":"2zhc"' in detail
    assert '"grid_shape_order":"ZYX"' in detail
    assert '"world_axis_order":"XYZ"' in detail
    assert '"policy":"no_transform_or_fitmap"' in detail
    assert all(key in detail for key in ("map_lower_xyz", "map_upper_xyz", "model_lower_xyz", "model_upper_xyz"))
    parsed_detail = json.loads(detail)
    grid = np.asarray(exp["grid"])
    expected_upper = np.asarray(exp["origin"], dtype=np.float64) + np.asarray(
        grid.shape[:0:-1], dtype=np.float64
    ) * np.asarray(exp["voxel_size"], dtype=np.float64)
    np.testing.assert_array_equal(parsed_detail["map_lower_xyz"], exp["origin"])
    np.testing.assert_array_equal(parsed_detail["map_upper_xyz"], expected_upper)

    invalid = np.asarray([[np.nan, 0.0, 0.0]], dtype=np.float32)
    with pytest.raises(RuntimeError, match="input contract failed"):
        ensure_model_map_frame_compatible("bad", exp, invalid)

    invalid_map = dict(exp)
    invalid_map["origin"] = np.asarray([np.nan, 0.0, 0.0], dtype=np.float32)
    with pytest.raises(RuntimeError, match="input contract failed"):
        ensure_model_map_frame_compatible(
            "bad_map",
            invalid_map,
            np.asarray([[1.0, 1.0, 1.0]], dtype=np.float32),
        )


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
