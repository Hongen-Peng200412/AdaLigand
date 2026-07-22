"""Chimera/MapQ 标准化模型选择契约测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import gemmi


CODE_DIR = Path(__file__).resolve().parents[1] / "code"

from adaligand_preprocessing.external_tools.model_cif import write_normalized_model_cif
from adaligand_preprocessing.stages.stage_c.pipeline import category_rows


def _write_multistate_cif(path: Path) -> None:
    """写两 model、双 altloc、ATOM/HETATM/H 的最小身份 fixture。"""
    path.write_text(
        """data_demo
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
ATOM 10 C CA B ALA A 1 1 ? 9 0 0 0.9 CA ALA A 1 1
ATOM 11 C CA A ALA A 1 1 ? 1 0 0 0.2 CA ALA A 1 1
ATOM 12 O O . ALA A 1 1 ? 2 0 0 1.0 O ALA A 1 1
ATOM 13 H H . ALA A 1 1 ? 2 1 0 1.0 H ALA A 1 1
HETATM 14 C C1 . LIG B 2 . ? 3 0 0 1.0 C1 LIG B 9 1
ATOM 20 C CA . ALA A 1 1 ? 100 0 0 1.0 CA ALA A 1 2
loop_
_atom_site_anisotrop.id
_atom_site_anisotrop.type_symbol
10 C
14 C
loop_
_struct_conn.id
_struct_conn.ptnr1_label_asym_id
_struct_conn.ptnr2_label_asym_id
covale1 A B
""",
        encoding="utf-8",
    )


def _atom_rows(path: Path) -> list[dict[str, str]]:
    """读取 fixture 的 atom_site 行。"""
    block = gemmi.cif.read(str(path)).sole_block()
    return category_rows(block, "_atom_site.")


def test_normalized_full_model_preserves_ids_and_selected_full_heavy_atoms(tmp_path: Path) -> None:
    """full model 应保留首 model 的 ATOM+HETATM 重原子及原始 id。"""
    source = tmp_path / "source.cif"
    output = tmp_path / "full.cif"
    _write_multistate_cif(source)

    stats = write_normalized_model_cif(source, output, atom_only=False)
    rows = _atom_rows(output)

    assert [row["id"] for row in rows] == ["11", "12", "14"]
    assert [row["Cartn_x"] for row in rows] == ["1", "2", "3"]
    assert stats == {"n_atoms": 3, "n_atom": 2, "n_hetatm": 1, "model_num": "1"}

    block = gemmi.cif.read(str(output)).sole_block()
    assert block.get_mmcif_category("_atom_site_anisotrop.") == {}
    assert block.get_mmcif_category("_struct_conn.") == {}


def test_normalized_atom_only_strictly_removes_every_hetatm(tmp_path: Path) -> None:
    """E2 专用模型即使遇到 LIG/covalent 类 HETATM 也必须全部删除。"""
    source = tmp_path / "source.cif"
    output = tmp_path / "adaligand_preprocessing.stages.stage_c.receptor.cif"
    _write_multistate_cif(source)

    stats = write_normalized_model_cif(source, output, atom_only=True)
    rows = _atom_rows(output)

    assert [row["group_PDB"] for row in rows] == ["ATOM", "ATOM"]
    assert [row["id"] for row in rows] == ["11", "12"]
    assert [row["Cartn_x"] for row in rows] == ["1", "2"]
    assert stats["n_hetatm"] == 0

    block = gemmi.cif.read(str(output)).sole_block()
    assert block.get_mmcif_category("_atom_site_anisotrop.") == {}
    assert block.get_mmcif_category("_struct_conn.") == {}
