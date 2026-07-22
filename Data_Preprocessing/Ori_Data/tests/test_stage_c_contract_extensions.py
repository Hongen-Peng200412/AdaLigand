"""新版 Stage C 受体特征、化学键与配体描述子的 golden tests。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from rdkit import Chem

CODE_DIR = Path(__file__).resolve().parents[1] / "code"
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"

from adaligand_preprocessing.stages.stage_c.descriptors import compute_ligand_descriptors, ligand_descriptor_is_valid
from adaligand_preprocessing.stages.stage_c.ligand_objects import Atom, Bond
from adaligand_preprocessing.stages.stage_c.constants import RECEPTOR_BOND_TYPE_TO_ID, RES_TO_ID
from adaligand_preprocessing.stages.stage_c.upgrades import add_ligand_centroids, materialize_occurrence_descriptors, upgrade_stage_c
from adaligand_preprocessing.cli.stage_c import ensure_filtered_run_is_isolated
from adaligand_preprocessing.stages.stage_c.contracts import (
    CArtifactState,
    compare_receptor_base_arrays,
    inspect_stage_c,
    validate_receptor_arrays,
)
from adaligand_preprocessing.stages.stage_c.receptor import (
    BOND_TYPE_TO_ID,
    DENSITY_BIN_EDGES,
    ReceptorAtomNameCoverageError,
    build_receptor_arrays,
    build_receptor_bonds,
    compute_local_density,
    compute_receptor_features,
)
from adaligand_preprocessing.utils.io import atomic_save_npz, write_jsonl


def _atom(
    atom_site_id: int,
    atom_name: str,
    resname: str,
    label_seq_id: str,
    element: str,
    x: float,
) -> dict:
    """
    构造 receptor.py 所需的最小已选择 atom_site 行。

    输出:
        - atom: dict, 包含 label/auth 身份、元素和一维测试坐标
    """
    return {
        "atom_site_id": atom_site_id,
        "element": element,
        "label_atom_id": atom_name,
        "label_comp_id": resname,
        "label_asym_id": "A",
        "label_seq_id": label_seq_id,
        "auth_atom_id": atom_name,
        "auth_comp_id": resname,
        "auth_asym_id": "A",
        "auth_seq_id": label_seq_id,
        "icode": "",
        "x": x,
        "y": 0.0,
        "z": 0.0,
    }


def _empty_mol() -> Chem.Mol:
    """
    构造无内部键的 RDKit Mol，供受体 backbone/struct_conn 单测隔离 CCD 逻辑。

    输出:
        - mol: Chem.Mol, 0 原子空分子
    """
    return Chem.RWMol().GetMol()


def _triple_bond_mol() -> Chem.Mol:
    """构造带 atom name 属性的 C#N CCD 模板。"""
    editable = Chem.RWMol()
    for atomic_number, name in ((6, "C8"), (7, "N3")):
        atom = Chem.Atom(atomic_number)
        atom.SetProp("name", name)
        editable.AddAtom(atom)
    editable.AddBond(0, 1, Chem.BondType.TRIPLE)
    mol = editable.GetMol()
    mol.SetProp("PDB_NAME", "F86")
    return mol


def _write_old_c_core(root: Path, pdb_id: str = "1abc") -> list[dict]:
    """
    写入一个只有旧 C schema 的单 occurrence fixture。

    输出:
        - occurrences: list[dict], 长度 1, 对应 `CCD:LIG`
    """
    occurrences = [{
        "pdb_id": pdb_id,
        "candidate_id": 0,
        "object_key": "CCD:LIG",
        "components": [{"index": 1, "ccd_id": "LIG"}],
    }]
    parse_dir = root / "parse" / pdb_id
    write_jsonl(parse_dir / "occurrences.jsonl", occurrences)

    atoms = np.zeros((1,), dtype=Atom)
    atoms["element"] = 6
    bonds = np.zeros((0,), dtype=Bond)
    atomic_save_npz(
        root / "ligand_objects" / "CCD_LIG.npz",
        atoms=atoms,
        bonds=bonds,
        atom_names=np.asarray(["C1"], dtype=object),
    )
    atomic_save_npz(
        parse_dir / "ligand_coords.npz",
        coords_0=np.asarray([[1.0, 2.0, 3.0]], dtype=np.float32),
        present_0=np.asarray([True], dtype=bool),
    )
    atomic_save_npz(
        parse_dir / "receptor_tokens.npz",
        coords=np.asarray([[0.0, 0.0, 0.0]], dtype=np.float32),
        element=np.asarray([6], dtype=np.uint8),
        res_type=np.asarray([0], dtype=np.uint8),
        is_backbone=np.asarray([True], dtype=bool),
        atom_name=np.asarray([b"CA"], dtype="S4"),
        res_index=np.asarray([0], dtype=np.int32),
        chain_index=np.asarray([0], dtype=np.int32),
    )
    return occurrences


def _write_minimal_upgrade_cif(root: Path, pdb_id: str = "1abc") -> None:
    """写入含一个 polymer CA 和一个 LIG C1 的最小 mmCIF。"""
    path = root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """data_1abc
loop_
_entity.id
_entity.type
1 polymer
2 non-polymer
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.auth_atom_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . ALA A 1 1 ? 0.0 0.0 0.0 1.0 CA ALA A 1 1
HETATM 2 C C1 . LIG B 2 . ? 1.0 2.0 3.0 1.0 C1 LIG B 10 1
""",
        encoding="utf-8",
    )


def test_local_density_matches_hand_counted_shells():
    """验证三个共线原子的 0–2/2–4 Å 壳层计数且不计自身。"""
    coords = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [3.0, 0.0, 0.0]], dtype=np.float32)

    density = compute_local_density(coords, DENSITY_BIN_EDGES)

    expected_counts = np.zeros((3, 9), dtype=np.float32)
    expected_counts[0, :2] = (1.0, 1.0)
    expected_counts[1, 0] = 2.0
    expected_counts[2, :2] = (1.0, 1.0)
    np.testing.assert_allclose(density, np.log1p(expected_counts), rtol=0, atol=1e-7)


def test_receptor_feature_layout_and_dna_parent_mapping():
    """验证 ALA-C 的精确通道，并验证 DA 只在 49 维中映射到 A。"""
    atoms = [
        _atom(1, "CA", "ALA", "1", "C", 0.0),
        _atom(2, "P", "DA", "2", "P", 30.0),
    ]

    feat = compute_receptor_features(atoms)

    assert feat.shape == (2, 49)
    assert feat.dtype == np.float32
    assert feat[0, 0] == 1.0
    assert feat[0, 6] == 1.0
    np.testing.assert_array_equal(feat[0, 31:39], [0, 1, 0, 0, 1, 0, 0, 1])
    assert feat[0, 39] == pytest.approx(12.011 / 32.0)
    assert feat[1, 4] == 1.0
    assert feat[1, 6 + 20] == 1.0  # 20 AA 之后的第一个核苷酸通道 A。
    np.testing.assert_array_equal(feat[:, 40:49], 0.0)


def test_path_graph_ligand_descriptors_have_exact_semantics():
    """四原子路径图应有 Wiener=10、atom_local(M,5) 和无环哨兵 -1。"""
    atoms = np.zeros((4,), dtype=Atom)
    atoms["element"] = 6
    atoms["ref_pos"] = np.asarray([[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]], dtype=np.float32)
    bonds = np.zeros((3,), dtype=Bond)
    bonds["atom_1"] = [0, 1, 2]
    bonds["atom_2"] = [1, 2, 3]
    bonds["type"][:, 0] = True

    descriptors = compute_ligand_descriptors(atoms, bonds)

    assert descriptors["n_heavy"].item() == 4
    assert descriptors["n_rings"].item() == 0
    assert descriptors["n_rotatable"].item() == 1
    assert descriptors["wiener_index"].item() == pytest.approx(10.0)
    assert descriptors["graph_energy"].item() == pytest.approx(4.47213595, rel=1e-6)
    assert descriptors["radius_gyration"].item() == pytest.approx(np.sqrt(1.25), rel=1e-6)
    np.testing.assert_array_equal(descriptors["atom_local"][0], [3, 1, 1, 1, -1])
    np.testing.assert_array_equal(descriptors["atom_local"][1], [2, 2, 1, 0, -1])


def test_ring_ligand_marks_nearest_ring_distance_zero():
    """三元环的每个原子都应位于环上，最近环距离为 0。"""
    atoms = np.zeros((3,), dtype=Atom)
    atoms["element"] = 6
    bonds = np.zeros((3,), dtype=Bond)
    bonds["atom_1"] = [0, 1, 2]
    bonds["atom_2"] = [1, 2, 0]
    bonds["type"][:, 0] = True

    descriptors = compute_ligand_descriptors(atoms, bonds)

    assert descriptors["n_rings"].item() == 1
    np.testing.assert_array_equal(descriptors["atom_local"][:, 4], 0.0)


def test_descriptor_allows_complete_ccd_template_with_apparent_high_valence():
    """完整 CCD 模板中的表观五价碳应跳过严格价态检查，但仍生成有限描述子。"""
    atoms = np.zeros((6,), dtype=Atom)
    atoms["element"] = 6
    bonds = np.zeros((5,), dtype=Bond)
    bonds["atom_1"] = 0
    bonds["atom_2"] = np.arange(1, 6)
    bonds["type"][:, 0] = True

    descriptors = compute_ligand_descriptors(atoms, bonds)

    assert descriptors["n_heavy"].item() == 6
    assert descriptors["n_rings"].item() == 0
    assert descriptors["wiener_index"].item() == pytest.approx(25.0)
    assert descriptors["atom_local"].shape == (6, 5)
    assert all(np.isfinite(value).all() for value in descriptors.values())


def test_descriptor_still_rejects_non_ring_aromatic_bond():
    """放宽严格价态后，无法 kekulize 的非成环芳香键仍必须 fail-fast。"""
    atoms = np.zeros((2,), dtype=Atom)
    atoms["element"] = 6
    bonds = np.zeros((1,), dtype=Bond)
    bonds["atom_1"] = 0
    bonds["atom_2"] = 1
    bonds["type"][:, 4] = True

    with pytest.raises(ValueError, match="SANITIZE_KEKULIZE"):
        compute_ligand_descriptors(atoms, bonds)


def test_descriptor_allows_zero_charge_carbon_monoxide_template():
    """零形式电荷 C#O 的显式氧价态为 3，也应按完整 CCD 模板计算图描述子。"""
    atoms = np.zeros((2,), dtype=Atom)
    atoms["element"] = [6, 8]
    bonds = np.zeros((1,), dtype=Bond)
    bonds["atom_1"] = 0
    bonds["atom_2"] = 1
    bonds["type"][:, 2] = True

    descriptors = compute_ligand_descriptors(atoms, bonds)

    assert descriptors["n_heavy"].item() == 2
    assert descriptors["n_rings"].item() == 0
    assert descriptors["wiener_index"].item() == pytest.approx(1.0)


def test_ligand_descriptor_validator_rejects_wrong_atom_local_shape(tmp_path):
    """描述子的 scalar dtype 正确但 atom_local 维度错误时不得判为完成。"""
    path = tmp_path / "descriptor.npz"
    atomic_save_npz(
        path,
        mol_weight=np.asarray(12.0, dtype=np.float32),
        n_heavy=np.asarray(1, dtype=np.int32),
        n_rings=np.asarray(0, dtype=np.int32),
        n_rotatable=np.asarray(0, dtype=np.int32),
        wiener_index=np.asarray(0.0, dtype=np.float32),
        graph_energy=np.asarray(0.0, dtype=np.float32),
        radius_gyration=np.asarray(0.0, dtype=np.float32),
        atom_local=np.zeros((1, 4), dtype=np.float32),
    )

    assert not ligand_descriptor_is_valid(path)


def test_receptor_backbone_bond_requires_consecutive_label_seq(monkeypatch, tmp_path):
    """二肽 1→2 生成 C–N backbone 键；1→3 的编号空洞不得误连。"""
    monkeypatch.setattr(
        "adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol",
        lambda _code, _cache, **_kwargs: _empty_mol(),
    )
    consecutive = [
        _atom(1, "C", "ALA", "1", "C", 0.0),
        _atom(2, "N", "GLY", "2", "N", 1.3),
    ]
    gapped = [
        _atom(1, "C", "ALA", "1", "C", 0.0),
        _atom(2, "N", "GLY", "3", "N", 1.3),
    ]

    bond_index, bond_type = build_receptor_bonds(consecutive, [], tmp_path)
    gap_index, gap_type = build_receptor_bonds(gapped, [], tmp_path)

    np.testing.assert_array_equal(bond_index, [[0], [1]])
    np.testing.assert_array_equal(bond_type, [BOND_TYPE_TO_ID["backbone"]])
    assert gap_index.shape == (2, 0)
    assert gap_type.shape == (0,)


def test_struct_conn_disulfide_overrides_template_semantics(monkeypatch, tmp_path):
    """两端都在受体中的 disulf 连接应落为稳定 disulfide 编码。"""
    monkeypatch.setattr(
        "adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol",
        lambda _code, _cache, **_kwargs: _empty_mol(),
    )
    atoms = [
        _atom(1, "SG", "CYS", "1", "S", 0.0),
        _atom(2, "SG", "CYS", "2", "S", 2.0),
    ]
    struct_conn = [{
        "conn_type_id": "disulf",
        "ptnr1_label_asym_id": "A",
        "ptnr1_label_comp_id": "CYS",
        "ptnr1_label_seq_id": "1",
        "ptnr1_label_atom_id": "SG",
        "ptnr2_label_asym_id": "A",
        "ptnr2_label_comp_id": "CYS",
        "ptnr2_label_seq_id": "2",
        "ptnr2_label_atom_id": "SG",
    }]

    bond_index, bond_type = build_receptor_bonds(atoms, struct_conn, tmp_path)

    np.testing.assert_array_equal(bond_index, [[0], [1]])
    np.testing.assert_array_equal(bond_type, [BOND_TYPE_TO_ID["disulfide"]])


def test_struct_conn_auth_only_partner_lookup_is_preserved(monkeypatch, tmp_path):
    """缺 label_seq_id 的显式共价键仍须通过 auth identity 找到两个受体原子。"""
    monkeypatch.setattr(
        "adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol",
        lambda _code, _cache, **_kwargs: _empty_mol(),
    )
    atoms = [
        _atom(1, "SG", "CYS", "10", "S", 0.0),
        _atom(2, "SG", "CYS", "20", "S", 2.0),
    ]
    for atom in atoms:
        atom["label_seq_id"] = ""
    struct_conn = [{
        "conn_type_id": "disulf",
        "ptnr1_auth_asym_id": "A",
        "ptnr1_auth_comp_id": "CYS",
        "ptnr1_auth_seq_id": "10",
        "ptnr1_auth_atom_id": "SG",
        "ptnr2_auth_asym_id": "A",
        "ptnr2_auth_comp_id": "CYS",
        "ptnr2_auth_seq_id": "20",
        "ptnr2_auth_atom_id": "SG",
    }]

    bond_index, bond_type = build_receptor_bonds(atoms, struct_conn, tmp_path)

    np.testing.assert_array_equal(bond_index, [[0], [1]])
    np.testing.assert_array_equal(bond_type, [BOND_TYPE_TO_ID["disulfide"]])


def test_receptor_triple_bond_appends_backward_compatible_code(monkeypatch, tmp_path):
    """合法 CCD 三键必须编码为新增 6，既有 0–5 枚举保持不变。"""
    monkeypatch.setattr(
        "adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol",
        lambda _code, _cache, **_kwargs: _triple_bond_mol(),
    )
    atoms = [
        _atom(1, "C8", "F86", "1", "C", 0.0),
        _atom(2, "N3", "F86", "1", "N", 1.2),
    ]

    bond_index, bond_type = build_receptor_bonds(atoms, [], tmp_path)

    assert RECEPTOR_BOND_TYPE_TO_ID == {
        "single": 0,
        "double": 1,
        "aromatic": 2,
        "backbone": 3,
        "disulfide": 4,
        "covale": 5,
        "triple": 6,
    }
    np.testing.assert_array_equal(bond_index, [[0], [1]])
    np.testing.assert_array_equal(bond_type, [6])


def test_receptor_validator_accepts_triple_and_rejects_unknown_code():
    """receptor 契约接受 triple=6，但继续拒绝未来未声明的 7。"""
    arrays = {
        "coords": np.zeros((2, 3), dtype=np.float32),
        "element": np.asarray([6, 7], dtype=np.uint8),
        "res_type": np.asarray([0, 0], dtype=np.uint8),
        "is_backbone": np.asarray([False, False], dtype=bool),
        "atom_name": np.asarray([b"C8", b"N3"], dtype="S4"),
        "res_index": np.asarray([0, 0], dtype=np.int32),
        "chain_index": np.asarray([0, 0], dtype=np.int32),
        "bond_index": np.asarray([[0], [1]], dtype=np.int32),
        "bond_type": np.asarray([6], dtype=np.uint8),
        "feat": np.zeros((2, 49), dtype=np.float32),
    }

    assert validate_receptor_arrays(arrays, require_new=True) == []
    arrays["bond_type"] = np.asarray([7], dtype=np.uint8)
    assert "receptor_contract:bond_type_range" in validate_receptor_arrays(
        arrays,
        require_new=True,
    )


def test_strict_receptor_bond_build_rejects_unmapped_atom_name(monkeypatch, tmp_path):
    """source repair 不得把 CCD 无法识别的当前 atom_name 静默变成缺键受体。"""
    monkeypatch.setattr("adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol", lambda *_args, **_kwargs: _triple_bond_mol())
    atoms = [
        _atom(1, "C8", "F86", "1", "C", 0.0),
        _atom(2, "NX", "F86", "1", "N", 1.2),
    ]

    with pytest.raises(ReceptorAtomNameCoverageError, match="NX"):
        build_receptor_bonds(
            atoms,
            [],
            tmp_path,
            allow_ccd_fetch=False,
            require_atom_name_coverage=True,
        )


def test_strict_receptor_bond_build_rejects_element_mismatch(monkeypatch, tmp_path):
    """atom name 命中 CCD 仍须核对元素，避免串档模板生成错误键图。"""
    monkeypatch.setattr("adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol", lambda *_args, **_kwargs: _triple_bond_mol())
    atoms = [
        _atom(1, "C8", "F86", "1", "O", 0.0),
        _atom(2, "N3", "F86", "1", "N", 1.2),
    ]

    with pytest.raises(ReceptorAtomNameCoverageError, match="element mismatch"):
        build_receptor_bonds(
            atoms,
            [],
            tmp_path,
            allow_ccd_fetch=False,
            require_atom_name_coverage=True,
        )


def test_strict_receptor_bond_build_rejects_cache_identity_mismatch(
    monkeypatch,
    tmp_path,
):
    """cache 内声明的 CCD 身份必须等于当前 residue，防止错误 pickle 串档。"""
    mol = _triple_bond_mol()
    mol.SetProp("PDB_NAME", "OTHER")
    monkeypatch.setattr("adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol", lambda *_args, **_kwargs: mol)
    atoms = [
        _atom(1, "C8", "F86", "1", "C", 0.0),
        _atom(2, "N3", "F86", "1", "N", 1.2),
    ]

    with pytest.raises(ReceptorAtomNameCoverageError, match="identity mismatch"):
        build_receptor_bonds(
            atoms,
            [],
            tmp_path,
            allow_ccd_fetch=False,
            require_atom_name_coverage=True,
        )


def test_scoped_receptor_coverage_ignores_unrelated_placeholder(
    monkeypatch,
    tmp_path,
):
    """无关 N/UNK 占位 residue 不得阻断另一个实际改名 residue 的严格复核。"""
    def _ccd(code, _cache, **_kwargs):
        return _triple_bond_mol() if code == "F86" else _empty_mol()

    monkeypatch.setattr("adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol", _ccd)
    atoms = [
        _atom(1, "C8", "F86", "1", "C", 0.0),
        _atom(2, "N3", "F86", "1", "N", 1.2),
        _atom(3, "N1", "N", "2", "N", 5.0),
    ]

    bond_index, bond_type = build_receptor_bonds(
        atoms,
        [],
        tmp_path,
        allow_ccd_fetch=False,
        required_atom_name_coverage_residues={
            ("A", "F86", "1", ""),
        },
    )

    np.testing.assert_array_equal(bond_index, [[0], [1]])
    np.testing.assert_array_equal(bond_type, [6])


def test_scoped_receptor_coverage_rejects_absent_requested_residue(
    monkeypatch,
    tmp_path,
):
    """调用方列出的改名 residue 若已从当前 source 消失，必须 fail closed。"""
    monkeypatch.setattr(
        "adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol",
        lambda _code, _cache, **_kwargs: _triple_bond_mol(),
    )
    atoms = [
        _atom(1, "C8", "F86", "1", "C", 0.0),
        _atom(2, "N3", "F86", "1", "N", 1.2),
    ]

    with pytest.raises(ReceptorAtomNameCoverageError, match="absent"):
        build_receptor_bonds(
            atoms,
            [],
            tmp_path,
            allow_ccd_fetch=False,
            required_atom_name_coverage_residues={
                ("A", "6MZ", "9", ""),
            },
        )


def test_receptor_arrays_keep_dna_token_distinct_from_feature_parent(monkeypatch, tmp_path):
    """`res_type` 保留 DA id，而 49 维 residue one-hot 使用 A 母体。"""
    monkeypatch.setattr(
        "adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol",
        lambda _code, _cache, **_kwargs: _empty_mol(),
    )
    atoms = [_atom(1, "P", "DA", "1", "P", 0.0)]

    arrays = build_receptor_arrays(atoms, [], tmp_path)

    assert arrays["res_type"].item() == RES_TO_ID["DA"]
    assert arrays["feat"][0, 6 + 20] == 1.0
    assert arrays["bond_index"].shape == (2, 0)


def test_old_stage_c_core_is_upgrade_not_skipped(tmp_path):
    """旧三件套内部一致但缺四类新增产物时必须判为 UPGRADE。"""
    _write_old_c_core(tmp_path)

    inspection = inspect_stage_c(tmp_path, "1abc")

    assert inspection.state == CArtifactState.UPGRADE
    assert any(reason.startswith("ligand_centroid_missing") for reason in inspection.reasons)
    assert any(reason.startswith("receptor_missing:bond_index") for reason in inspection.reasons)
    assert "descriptor_invalid:CCD:LIG" in inspection.reasons


def test_centroid_and_descriptor_upgrade_preserve_old_arrays(tmp_path):
    """补 centroid/descriptor 后旧 coords/present 数组逐位保持不变。"""
    occurrences = _write_old_c_core(tmp_path)
    coords_path = tmp_path / "parse" / "1abc" / "ligand_coords.npz"
    with np.load(coords_path) as before_data:
        before = {key: before_data[key].copy() for key in before_data.files}

    changed = add_ligand_centroids(coords_path, occurrences)
    n_objects = materialize_occurrence_descriptors(tmp_path, occurrences, overwrite=False)

    assert changed
    assert n_objects == 1
    with np.load(coords_path) as after:
        np.testing.assert_array_equal(after["coords_0"], before["coords_0"])
        np.testing.assert_array_equal(after["present_0"], before["present_0"])
        np.testing.assert_array_equal(after["centroid_atom_0"], [1.0, 2.0, 3.0])
    assert ligand_descriptor_is_valid(tmp_path / "ligand_descriptors" / "CCD_LIG.npz")


def test_stage_c_becomes_complete_only_after_all_new_receptor_fields(tmp_path):
    """centroid/descriptor 已齐时，receptor 新字段仍必须全部有效才能 COMPLETE。"""
    occurrences = _write_old_c_core(tmp_path)
    add_ligand_centroids(tmp_path / "parse" / "1abc" / "ligand_coords.npz", occurrences)
    materialize_occurrence_descriptors(tmp_path, occurrences, overwrite=False)
    receptor_path = tmp_path / "parse" / "1abc" / "receptor_tokens.npz"
    with np.load(receptor_path) as old_data:
        arrays = {key: old_data[key].copy() for key in old_data.files}
    arrays.update({
        "bond_index": np.empty((2, 0), dtype=np.int32),
        "bond_type": np.empty((0,), dtype=np.uint8),
        "feat": np.zeros((1, 49), dtype=np.float32),
    })
    atomic_save_npz(receptor_path, **arrays)

    inspection = inspect_stage_c(tmp_path, "1abc")

    assert inspection.state == CArtifactState.COMPLETE
    assert inspection.reasons == ()


def test_corrupt_old_ligand_shape_requires_rebuild(tmp_path):
    """旧核心 coords 行数与 LigandObject 不一致时不得走增量升级。"""
    _write_old_c_core(tmp_path)
    atomic_save_npz(
        tmp_path / "parse" / "1abc" / "ligand_coords.npz",
        coords_0=np.zeros((2, 3), dtype=np.float32),
        present_0=np.ones((2,), dtype=bool),
    )

    inspection = inspect_stage_c(tmp_path, "1abc")

    assert inspection.state == CArtifactState.REBUILD
    assert any(reason.startswith("ligand_coords_contract") for reason in inspection.reasons)


def test_receptor_base_comparison_handles_nonfloating_arrays():
    """基础数组比较对 bytes/bool 不调用 `isnan`，且能定位单一差异字段。"""
    old = {
        "coords": np.zeros((1, 3), dtype=np.float32),
        "element": np.asarray([6], dtype=np.uint8),
        "res_type": np.asarray([0], dtype=np.uint8),
        "is_backbone": np.asarray([True], dtype=bool),
        "atom_name": np.asarray([b"CA"], dtype="S4"),
        "res_index": np.asarray([0], dtype=np.int32),
        "chain_index": np.asarray([0], dtype=np.int32),
    }
    rebuilt = {key: value.copy() for key, value in old.items()}
    rebuilt["atom_name"][0] = b"CB"

    assert compare_receptor_base_arrays(old, old) == []
    assert compare_receptor_base_arrays(old, rebuilt) == ["receptor_base_changed:atom_name"]


def test_stage_c_upgrade_is_end_to_end_and_idempotent(monkeypatch, tmp_path):
    """旧三件套经真实 mmCIF 受体重建后到 COMPLETE，第二次运行应直接 skipped。"""
    _write_old_c_core(tmp_path)
    _write_minimal_upgrade_cif(tmp_path)
    monkeypatch.setattr(
        "adaligand_preprocessing.stages.stage_c.receptor.get_ccd_mol",
        lambda _code, _cache, **_kwargs: _empty_mol(),
    )

    first = upgrade_stage_c(tmp_path, "1abc")
    second = upgrade_stage_c(tmp_path, "1abc")

    assert first["status"] == "upgraded"
    assert first["centroids_changed"]
    assert first["receptor_changed"]
    assert second == {"pdb_id": "1abc", "status": "skipped"}
    assert inspect_stage_c(tmp_path, "1abc").state == CArtifactState.COMPLETE


def test_filtered_stage_c_cannot_overwrite_formal_run_status(tmp_path):
    """带样本子集的 C 不得复用已有正式 A/C 证据的 run id。"""
    formal_a = tmp_path / "reports" / "runs" / "formal" / "stage_a" / "guard.json"
    formal_a.parent.mkdir(parents=True)
    formal_a.write_text("{}\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="fresh independent run_id"):
        ensure_filtered_run_is_isolated(
            tmp_path,
            "formal",
            tmp_path / "subset.txt",
        )


def test_full_stage_c_can_refresh_existing_formal_status(tmp_path):
    """无过滤的全量 C 允许在同一正式 run 中原子刷新完整状态。"""
    formal_a = tmp_path / "reports" / "runs" / "formal" / "stage_a" / "guard.json"
    formal_a.parent.mkdir(parents=True)
    formal_a.write_text("{}\n", encoding="utf-8")

    ensure_filtered_run_is_isolated(tmp_path, "formal", None)
