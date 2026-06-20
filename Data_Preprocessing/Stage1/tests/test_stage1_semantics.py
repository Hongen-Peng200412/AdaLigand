"""Stage1 关键语义测试。"""

from __future__ import annotations

import zipfile

import gemmi
import numpy as np
import pytest

from adaligand_stage1.constants import METAL_ELEMENTS
from adaligand_stage1.io_utils import atomic_save_npz, safe_object_filename
from adaligand_stage1.ligand_object import BranchedBondError, process_branched_ligand
from adaligand_stage1.parse import (
    build_components,
    build_het_indices,
    clean_value,
    derive_type_tag,
    lookup_struct_conn_partner,
    materialize_ligand_objects,
    optional_category_rows,
    selected_atom_rows,
)
from adaligand_stage1.rcsb import emdb_references_pdb


def test_atomic_save_npz_is_not_compressed(tmp_path):
    """
    验证 atomic_save_npz 使用 ZIP_STORED 保存数组。

    输出:
        - None: zip 条目压缩类型均为 ZIP_STORED
    """
    path = tmp_path / "sample.npz"
    atomic_save_npz(path, arr=np.arange(4, dtype=np.int32))

    with zipfile.ZipFile(path) as archive:
        compress_types = {info.compress_type for info in archive.infolist()}

    assert compress_types == {zipfile.ZIP_STORED}


def test_safe_object_filename_keeps_object_key_semantics():
    """
    验证 object_key 文件名转义不保留 Windows 非法冒号。

    输出:
        - None: 转义后文件名可安全落盘
    """
    assert safe_object_filename("CCD:NAG") == "CCD_NAG"
    assert safe_object_filename("BRANCHED:NAG-NAG:abcdef") == "BRANCHED_NAG-NAG_abcdef"


def test_ion_tag_is_single_atom_metal_only():
    """
    验证 ion 仅由单原子金属触发。

    输出:
        - None: 单原子 NA 为 ion, 单原子 CL 不是 ion
    """
    assert "NA" in METAL_ELEMENTS
    sodium = [{"element": "NA", "label_entity_id": "1"}]
    chloride = [{"element": "CL", "label_entity_id": "1"}]

    assert derive_type_tag(sodium, [("A", "NA", "1", "")], {"1": "non-polymer"}, {"NA": "NON-POLYMER"}) == "ion"
    assert derive_type_tag(chloride, [("A", "CL", "1", "")], {"1": "non-polymer"}, {"CL": "NON-POLYMER"}) == "small_molecule"


def test_altloc_prefers_blank_then_a_then_high_occupancy():
    """
    验证 altloc 选择顺序为空 altloc 优先。

    输出:
        - None: 同一原子多 altloc 时选择空 altloc
    """
    base = {
        "group_PDB": "ATOM",
        "type_symbol": "C",
        "label_atom_id": "CA",
        "label_comp_id": "ALA",
        "label_asym_id": "A",
        "label_entity_id": "1",
        "label_seq_id": "1",
        "auth_atom_id": "CA",
        "auth_comp_id": "ALA",
        "auth_asym_id": "A",
        "auth_seq_id": "1",
        "pdbx_PDB_ins_code": "?",
        "Cartn_x": "0",
        "Cartn_y": "0",
        "Cartn_z": "0",
        "pdbx_PDB_model_num": "1",
    }
    rows = [
        dict(base, id="2", label_alt_id="A", occupancy="1.00", Cartn_x="2"),
        dict(base, id="1", label_alt_id=".", occupancy="0.20", Cartn_x="1"),
    ]

    selected = selected_atom_rows(rows)

    assert selected[0]["atom_site_id"] == 1
    assert selected[0]["x"] == 1.0


def test_struct_conn_lookup_preserves_zero_index():
    """
    验证 HET atom index 为 0 时不会被布尔短路误判为 None。

    输出:
        - None: 查找返回 0
    """
    atom_lookup = {("label", "A", "NAG", "", "C1"): 0}
    row = {
        "ptnr1_label_asym_id": "A",
        "ptnr1_label_comp_id": "NAG",
        "ptnr1_label_seq_id": ".",
        "ptnr1_label_atom_id": "C1",
        "ptnr1_auth_asym_id": "A",
        "ptnr1_auth_comp_id": "NAG",
        "ptnr1_auth_seq_id": "1",
        "ptnr1_auth_atom_id": "C1",
    }

    assert lookup_struct_conn_partner(row, "ptnr1_", atom_lookup) == 0


def test_clean_value_strips_outer_quotes_for_prime_atom_names():
    """
    验证 mmCIF 引号不会污染 `C1'` 这类 CCD 原子名。

    输出:
        - None: 外层引号被去除, 内部 prime 保留
    """
    assert clean_value("\"C1'\"") == "C1'"


def test_empty_label_seq_does_not_create_ambiguous_label_lookup():
    """
    验证 branched residue 的空 label_seq_id 不生成歧义 label-only key。

    输出:
        - None: 只能通过 auth_seq 或 label_authseq 查找同名原子
    """
    het_atoms = [
        {
            "het_index": 0,
            "label_asym_id": "E",
            "label_comp_id": "NAG",
            "label_seq_id": "",
            "auth_asym_id": "E",
            "auth_comp_id": "NAG",
            "auth_seq_id": "1",
            "auth_atom_id": "C1",
            "label_atom_id": "C1",
            "icode": "",
        },
        {
            "het_index": 1,
            "label_asym_id": "E",
            "label_comp_id": "NAG",
            "label_seq_id": "",
            "auth_asym_id": "E",
            "auth_comp_id": "NAG",
            "auth_seq_id": "2",
            "auth_atom_id": "C1",
            "label_atom_id": "C1",
            "icode": "",
        },
    ]

    _residue_atoms, atom_lookup = build_het_indices(het_atoms)

    assert ("label", "E", "NAG", "", "C1") not in atom_lookup
    assert atom_lookup[("label_authseq", "E", "NAG", "1", "C1")] == 0
    assert atom_lookup[("label_authseq", "E", "NAG", "2", "C1")] == 1


def test_missing_optional_category_returns_empty_rows():
    """
    验证不存在的可选 mmCIF category 返回空行表。

    输出:
        - None: 缺失 category 保持合法空表, 不伪造异常
    """
    block = gemmi.cif.read_string("data_test\n_entry.id TEST\n").sole_block()

    assert optional_category_rows(block, "_struct_conn.") == []


def test_branched_bond_missing_atom_is_not_silent(tmp_path):
    """
    验证 BRANCHED 跨残基键端点缺失时显式失败。

    输出:
        - None: inter_bond 引用不存在 atom name 时抛出 BranchedBondError
    """
    config = {
        "residues": ["1. NAG", "2. NAG"],
        "bonds": [[1, "NOT", 2, "C1"]],
    }

    with pytest.raises(BranchedBondError):
        process_branched_ligand(config, "BRANCHED:NAG-NAG:badbad", tmp_path, tmp_path / "ccd_cache")


def test_emdb_metadata_crossreference_matches_pdb_id():
    """
    验证 EMDB metadata 用明确 PDB crossreference 判断匹配。

    输出:
        - None: pdb_reference 中含目标 PDB 时返回 True, 否则返回 False
    """
    metadata = {
        "crossreferences": {
            "pdb_list": {
                "pdb_reference": [
                    {"pdb_id": "7D3F", "relationship": {"in_frame": "FULLOVERLAP"}},
                ]
            }
        }
    }

    assert emdb_references_pdb(metadata, "7d3f")
    assert not emdb_references_pdb(metadata, "1abc")


def test_single_ccd_ligand_object_name_and_residue_name_are_separate(tmp_path):
    """
    验证单 CCD LigandObject 的对象名与真实 residue 名分离。

    输出:
        - None: `name` 保留 object_key, `residue_names` 保留 CCD id
    """
    from rdkit import Chem

    mol = Chem.MolFromSmiles("O")
    mol.GetAtomWithIdx(0).SetProp("name", "O")

    from adaligand_stage1.ligand_object import process_molecule

    process_molecule(mol, "CCD:HOH", "O", tmp_path, None, "HOH")
    obj = np.load(tmp_path / "CCD_HOH.npz", allow_pickle=True)

    assert str(obj["name"]) == "CCD:HOH"
    assert obj["residue_names"].tolist() == ["HOH"]


def test_occurrence_schema_omits_molecular_weight():
    """
    验证 occurrence schema 不再输出 molecular_weight 字段。

    输出:
        - None: build_components 返回记录不包含 molecular_weight
    """
    het_atoms = [
        {
            "het_index": 0,
            "label_asym_id": "A",
            "label_comp_id": "NA",
            "label_seq_id": "1",
            "auth_asym_id": "A",
            "auth_seq_id": "1",
            "icode": "",
            "atom_site_id": 1,
            "label_entity_id": "1",
            "element": "NA",
        }
    ]
    residue_atoms = {("A", "NA", "1", ""): {"NA": 0}}
    from adaligand_stage1.parse import UnionFind

    components = build_components(
        "test",
        UnionFind(1),
        het_atoms,
        residue_atoms,
        set(),
        set(),
        {"1": "non-polymer"},
        {"NA": "NON-POLYMER"},
    )

    assert "molecular_weight" not in components[0]


def test_materialize_ligand_objects_respects_overwrite_flag(tmp_path):
    """
    验证 overwrite=True 会刷新已存在的 LigandObject。

    输出:
        - None: 已存在的占位文件被真实 CCD LigandObject 覆盖
    """
    atomic_save_npz(
        tmp_path / "ligand_objects" / "CCD_HOH.npz",
        name="old",
        residue_names=np.array(["old"], dtype=object),
    )
    component = {
        "kind": "CCD",
        "object_key": "CCD:HOH",
        "components": [{"ccd_id": "HOH"}],
    }

    materialize_ligand_objects(tmp_path, [component], overwrite=True)
    obj = np.load(tmp_path / "ligand_objects" / "CCD_HOH.npz", allow_pickle=True)

    assert str(obj["name"]) == "CCD:HOH"
    assert obj["residue_names"].tolist() == ["HOH"]


def test_materialize_ligand_objects_skips_repeated_object_in_same_process(tmp_path):
    """
    验证同一进程内重复 object_key 不会反复覆盖同一 LigandObject。

    输出:
        - None: 第二次物化同一 object_key 时保留第一次写入结果
    """
    component = {
        "kind": "CCD",
        "object_key": "CCD:HOH",
        "components": [{"ccd_id": "HOH"}],
    }

    materialize_ligand_objects(tmp_path, [component], overwrite=True)
    first_mtime = (tmp_path / "ligand_objects" / "CCD_HOH.npz").stat().st_mtime_ns
    materialize_ligand_objects(tmp_path, [component], overwrite=True)
    second_mtime = (tmp_path / "ligand_objects" / "CCD_HOH.npz").stat().st_mtime_ns

    assert second_mtime == first_mtime


def test_npz_load_context_releases_file_for_overwrite(tmp_path):
    """
    验证 npz 读取后释放文件句柄, 允许 Windows 上原子覆盖。

    输出:
        - None: 同一路径可在读取后再次 atomic_save_npz 覆盖
    """
    path = tmp_path / "sample.npz"
    atomic_save_npz(path, value=np.array([1], dtype=np.int32))
    with np.load(path) as archive:
        assert archive["value"].tolist() == [1]

    atomic_save_npz(path, value=np.array([2], dtype=np.int32))
    with np.load(path) as archive:
        assert archive["value"].tolist() == [2]
