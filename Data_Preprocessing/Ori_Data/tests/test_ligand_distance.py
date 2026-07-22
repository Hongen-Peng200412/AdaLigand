"""验证配体距离标签的数值、字段契约、来源身份和幂等写入。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from adaligand_preprocessing.labels import ligand_distance as distance_module
from adaligand_preprocessing.labels.ligand_distance import (
    LIGAND_DISTANCE_SCHEMA_VERSION,
    build_ligand_distance,
    build_ligand_distance_array,
    ligand_distance_errors,
    validate_ligand_distance_artifact,
)
from adaligand_preprocessing.utils.io import atomic_save_npz, write_jsonl


def _direct_distance(
    shape_zyx: tuple[int, int, int],
    voxel_size_xyz: np.ndarray,
    origin_xyz: np.ndarray,
    ligand_coords_xyz: np.ndarray,
) -> np.ndarray:
    """用小型广播计算测试用最近距离。"""
    z_index, y_index, x_index = np.indices(shape_zyx, dtype=np.float64)
    centers = np.stack(
        (
            origin_xyz[0] + (x_index + 0.5) * voxel_size_xyz[0],
            origin_xyz[1] + (y_index + 0.5) * voxel_size_xyz[1],
            origin_xyz[2] + (z_index + 0.5) * voxel_size_xyz[2],
        ),
        axis=-1,
    )
    squared = np.sum(
        (centers[..., None, :] - ligand_coords_xyz[None, None, None, ...]) ** 2,
        axis=-1,
    )
    return np.sqrt(np.min(squared, axis=-1)).astype(np.float16)[None]


def _write_build_inputs(
    root: Path,
    monkeypatch,
    *,
    present: np.ndarray,
) -> tuple[Path, Path]:
    """写入一个可由正式构建函数读取的最小实验密度与配体坐标。"""
    density_dir = root / "density" / "1abc"
    parse_dir = root / "parse" / "1abc"
    density_dir.mkdir(parents=True)
    parse_dir.mkdir(parents=True)

    exp_path = density_dir / "exp.npz"
    coords_path = parse_dir / "ligand_coords.npz"
    atomic_save_npz(
        exp_path,
        grid=np.arange(27, dtype=np.float32).reshape(1, 3, 3, 3),
        voxel_size=np.asarray([1.0, 1.5, 2.0], dtype=np.float32),
        origin=np.asarray([-1.0, 2.0, 4.0], dtype=np.float32),
    )
    occurrence = {"candidate_id": 0, "object_key": "CCD:LIG"}
    write_jsonl(parse_dir / "occurrences.jsonl", [occurrence])
    atomic_save_npz(
        coords_path,
        coords_0=np.asarray(
            [[-0.5, 2.75, 5.0], [0.5, 4.25, 7.0]],
            dtype=np.float32,
        ),
        present_0=np.asarray(present, dtype=bool),
    )
    inspection = SimpleNamespace(
        state=SimpleNamespace(value="complete"),
        reasons=(),
        occurrences=(occurrence,),
    )
    monkeypatch.setattr(distance_module, "_inspect_stage_c", lambda *_: inspection)
    monkeypatch.setattr(
        distance_module,
        "_experimental_density_identity",
        lambda *_: "a" * 64,
    )
    return exp_path, coords_path


def test_distance_matches_direct_calculation_with_anisotropic_voxels() -> None:
    """分块 KD-tree 结果必须等于小网格上的直接欧氏距离。"""
    shape = (3, 2, 4)
    voxel_size = np.asarray([1.25, 2.0, 3.0], dtype=np.float32)
    origin = np.asarray([-2.0, 5.0, 11.0], dtype=np.float32)
    ligand_coords = np.asarray(
        [[-1.375, 6.0, 12.5], [1.9, 7.4, 17.2]],
        dtype=np.float32,
    )

    actual = build_ligand_distance_array(shape, voxel_size, origin, ligand_coords)
    expected = _direct_distance(shape, voxel_size, origin, ligand_coords)

    assert actual.dtype == np.float16
    assert actual.shape == (1, *shape)
    assert np.array_equal(actual, expected)


def test_distance_without_present_ligand_atoms_is_positive_infinity() -> None:
    """没有实际配体原子时仍生成合法的全正无穷距离图。"""
    distance = build_ligand_distance_array(
        (2, 3, 4),
        np.asarray([1.0, 1.0, 1.0], dtype=np.float32),
        np.asarray([0.0, 0.0, 0.0], dtype=np.float32),
        np.empty((0, 3), dtype=np.float32),
    )

    assert distance.dtype == np.float16
    assert distance.shape == (1, 2, 3, 4)
    assert np.isposinf(distance).all()


def test_contract_rejects_wrong_source_and_mixed_infinity() -> None:
    """来源摘要和有限值语义变化必须被字段校验器发现。"""
    shape = (2, 2, 2)
    voxel_size = np.asarray([1.0, 1.0, 1.0], dtype=np.float32)
    origin = np.asarray([0.0, 0.0, 0.0], dtype=np.float32)
    distance = build_ligand_distance_array(
        shape,
        voxel_size,
        origin,
        np.asarray([[0.5, 0.5, 0.5]], dtype=np.float32),
    )
    arrays = distance_module.ligand_distance_artifact_arrays(
        distance,
        grid_shape_zyx=shape,
        voxel_size_xyz=voxel_size,
        origin_xyz=origin,
        source_exp_identity_sha256="a" * 64,
        source_occurrences_sha256="b" * 64,
        source_ligand_coords_sha256="c" * 64,
    )
    assert ligand_distance_errors(
        arrays,
        grid_shape_zyx=shape,
        voxel_size_xyz=voxel_size,
        origin_xyz=origin,
        source_exp_identity_sha256="a" * 64,
        source_occurrences_sha256="b" * 64,
        source_ligand_coords_sha256="c" * 64,
        expected_distance=distance,
    ) == []

    wrong = dict(arrays)
    wrong["source_occurrences_sha256"] = np.asarray("d" * 64)
    wrong["distance"] = distance.copy()
    wrong["distance"][0, 0, 0, 1] = np.inf
    errors = ligand_distance_errors(
        wrong,
        grid_shape_zyx=shape,
        voxel_size_xyz=voxel_size,
        origin_xyz=origin,
        source_exp_identity_sha256="a" * 64,
        source_occurrences_sha256="b" * 64,
        source_ligand_coords_sha256="c" * 64,
    )
    assert "ligand_distance_provenance:source_occurrences_sha256" in errors
    assert "ligand_distance_value:mixed_finite_and_infinite" in errors


def test_build_reuses_valid_file_and_rebuilds_after_coordinate_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """来源不变时复用文件，配体坐标文件变化后自动重建。"""
    _, coords_path = _write_build_inputs(
        tmp_path,
        monkeypatch,
        present=np.asarray([True, False]),
    )

    first = build_ligand_distance(tmp_path, "1ABC")
    output_path = tmp_path / "density" / "1abc" / "ligand_dist.npz"
    assert first["status"] == "success"
    assert first["n_present_ligand_atoms"] == 1
    assert validate_ligand_distance_artifact(tmp_path, "1abc") == []
    first_mtime = output_path.stat().st_mtime_ns

    second = build_ligand_distance(tmp_path, "1abc")
    assert second["status"] == "skipped"
    assert output_path.stat().st_mtime_ns == first_mtime

    with np.load(coords_path, allow_pickle=False) as handle:
        coords = {key: handle[key].copy() for key in handle.files}
    coords["coords_0"][0, 0] += np.float32(0.25)
    atomic_save_npz(coords_path, **coords)

    third = build_ligand_distance(tmp_path, "1abc")
    assert third["status"] == "success"
    assert validate_ligand_distance_artifact(tmp_path, "1abc") == []
    with np.load(output_path, allow_pickle=False) as handle:
        assert int(handle["schema_version"]) == LIGAND_DISTANCE_SCHEMA_VERSION
        assert str(handle["source_exp_identity_sha256"].item()) == "a" * 64


def test_build_without_present_atoms_writes_all_infinity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """全部 present 标志为 False 时不排除 PDB。"""
    _write_build_inputs(
        tmp_path,
        monkeypatch,
        present=np.asarray([False, False]),
    )

    result = build_ligand_distance(tmp_path, "1abc")
    assert result["status"] == "success"
    assert result["n_present_ligand_atoms"] == 0
    with np.load(
        tmp_path / "density" / "1abc" / "ligand_dist.npz",
        allow_pickle=False,
    ) as handle:
        assert np.isposinf(handle["distance"]).all()
    assert validate_ligand_distance_artifact(tmp_path, "1abc") == []
