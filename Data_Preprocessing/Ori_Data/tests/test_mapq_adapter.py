"""MapQ 固定参数命令与 atom_site.id 严格映射测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import gemmi
import pytest


CODE_DIR = Path(__file__).resolve().parents[1] / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from failures import ExternalToolError, ToolFailureCode
from mapq import MAPQ_CIF_OPENMODELS_PATCH, MAPQ_NP, MAPQ_SIGMA, MapQRunner, parse_mapq_output


def _write_model(path: Path) -> None:
    """写两个身份不同原子的标准化 full-model mmCIF。"""
    path.write_text(
        """data_x
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
HETATM 10 C C1 . LIG B 2 . ? 1 2 3 1.0 C1 LIG Z 9 1
HETATM 20 O O1 . LIG B 2 . ? 2 2 3 1.0 O1 LIG Z 9 1
""",
        encoding="utf-8",
    )


def _write_q_output(input_path: Path, output_path: Path, *, reverse: bool = False) -> None:
    """复制 atom_site、添加 Q-score，可选反转行序。"""
    document = gemmi.cif.read(str(input_path))
    block = document.sole_block()
    category = block.get_mmcif_category("_atom_site.")
    category["Q-score"] = ["0.25", "0.75"]
    if reverse:
        category = {key: list(reversed(values)) for key, values in category.items()}
    block.set_mmcif_category("_atom_site.", category)
    output_path.write_text(document.as_string(), encoding="utf-8")


def _write_fake_mapq(path: Path) -> None:
    """写一个模拟 mapq_cmd 的程序，输出行序反转的合法 Q mmCIF。"""
    path.write_text(
        """from pathlib import Path
import sys
import gemmi

def _upstream_cif_anchor(fp, mod):
    fp.write ( "mol = mmcif.ReadMol ( '%s' )[0]\\n" % mod )

args = dict(item.split('=', 1) for item in sys.argv if '=' in item)
cif = Path(args['cif'])
native = Path(args['map'])
document = gemmi.cif.read(str(cif))
block = document.sole_block()
category = block.get_mmcif_category('_atom_site.')
category['Q-score'] = ['0.25', '0.75']
category = {key: list(reversed(values)) for key, values in category.items()}
block.set_mmcif_category('_atom_site.', category)
output = Path(str(cif) + '__Q__' + native.name + '.cif')
output.write_text(document.as_string(), encoding='utf-8')
print('MapQ CLI 1.9.12')
""",
        encoding="utf-8",
    )


def test_mapq_runner_explicit_sigma_np_and_order_independent_id_join(tmp_path: Path) -> None:
    """CLI 必须显式 0.4/1，输出反序仍按 id 得到正确 Q。"""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    model = scratch / "model.cif"
    native = scratch / "native.mrc"
    _write_model(model)
    native.write_bytes(b"mrc")
    fake_cmd = tmp_path / "mapq_cmd.py"
    _write_fake_mapq(fake_cmd)
    chimera_root = tmp_path / "chimera"
    chimera_root.mkdir()
    runner = MapQRunner([sys.executable], fake_cmd, chimera_root, timeout_seconds=10)

    result = runner.run(native, model, resolution=2.8, scratch_dir=scratch)

    assert f"sigma={MAPQ_SIGMA}" in result.tool_result.argv
    assert f"np={MAPQ_NP}" in result.tool_result.argv
    assert result.q_by_atom_site_id == {"10": 0.25, "20": 0.75}
    assert "MapQ CLI 1.9.12" in result.cli_banner
    assert result.adapter_patch == MAPQ_CIF_OPENMODELS_PATCH
    assert result.compatibility_cli.name == "mapq_cmd.py"
    compatibility_text = result.compatibility_cli.read_text(encoding="utf-8")
    assert "chimera.openModels.add ( [mol], noprefs = True )" in compatibility_text


def test_parse_mapq_rejects_identity_swap_even_when_id_set_matches(tmp_path: Path) -> None:
    """交换两个 id 对应的身份必须失败，不能只看 id 集合。"""
    source = tmp_path / "model.cif"
    output = tmp_path / "q.cif"
    _write_model(source)
    _write_q_output(source, output)
    document = gemmi.cif.read(str(output))
    block = document.sole_block()
    category = block.get_mmcif_category("_atom_site.")
    category["label_atom_id"] = list(reversed(category["label_atom_id"]))
    block.set_mmcif_category("_atom_site.", category)
    output.write_text(document.as_string(), encoding="utf-8")

    with pytest.raises(ExternalToolError) as captured:
        parse_mapq_output(source, output)
    assert captured.value.code is ToolFailureCode.ATOM_MAPPING


def test_parse_mapq_accepts_equivalent_element_symbol_case(tmp_path: Path) -> None:
    """mmCIF 的 CA/Ca 元素规范化等价，不能误判为 atom identity 交换。"""
    source = tmp_path / "model.cif"
    output = tmp_path / "q.cif"
    _write_model(source)
    source_document = gemmi.cif.read(str(source))
    source_block = source_document.sole_block()
    source_category = source_block.get_mmcif_category("_atom_site.")
    source_category["type_symbol"][0] = "CA"
    source_block.set_mmcif_category("_atom_site.", source_category)
    source.write_text(source_document.as_string(), encoding="utf-8")
    _write_q_output(source, output)
    output_document = gemmi.cif.read(str(output))
    output_block = output_document.sole_block()
    output_category = output_block.get_mmcif_category("_atom_site.")
    output_category["type_symbol"][0] = "Ca"
    output_block.set_mmcif_category("_atom_site.", output_category)
    output.write_text(output_document.as_string(), encoding="utf-8")

    assert parse_mapq_output(source, output)["10"] == 0.25


@pytest.mark.parametrize("mutation", ["duplicate_id", "missing_q", "bad_q"])
def test_parse_mapq_rejects_schema_corruption(tmp_path: Path, mutation: str) -> None:
    """重复 id、缺 Q tag 和非有限 Q 都是硬输出失败。"""
    source = tmp_path / "model.cif"
    output = tmp_path / "q.cif"
    _write_model(source)
    _write_q_output(source, output)
    document = gemmi.cif.read(str(output))
    block = document.sole_block()
    category = block.get_mmcif_category("_atom_site.")
    if mutation == "duplicate_id":
        category["id"][1] = category["id"][0]
    elif mutation == "missing_q":
        category.pop("Q-score")
    else:
        category["Q-score"][0] = "nan"
    block.set_mmcif_category("_atom_site.", category)
    output.write_text(document.as_string(), encoding="utf-8")

    with pytest.raises(ExternalToolError) as captured:
        parse_mapq_output(source, output)
    assert captured.value.code is ToolFailureCode.OUTPUT_SCHEMA
