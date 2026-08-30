"""在提供 Gemmi 的正式环境验证 mmCIF entity-chain-序列读取."""

from pathlib import Path

import pytest

from held_out_pipeline.catalog import parse_mmcif_entities


pytest.importorskip("gemmi")


def test_mmcif_parser_uses_entity_poly_and_label_asym_without_nonpolymer(tmp_path: Path) -> None:
    """polymer entity 可映射多条 label asym chain, 非 polymer struct_asym 不进入目录."""

    # Path, 两个 polymer entity 和一个非 polymer struct_asym 外键的合成 mmCIF.
    mmcif_path = tmp_path / "1abc.cif"
    mmcif_path.write_text(
        "data_1abc\n"
        "loop_\n"
        "_entity_poly.entity_id\n"
        "_entity_poly.type\n"
        "_entity_poly.pdbx_seq_one_letter_code_can\n"
        "1 'polypeptide(L)' 'a c d'\n"
        "2 polyribonucleotide 'A U G'\n"
        "loop_\n"
        "_struct_asym.id\n"
        "_struct_asym.entity_id\n"
        "A 1\n"
        "B 1\n"
        "C 2\n"
        "H 9\n",
        encoding="utf-8",
    )
    # list[dict] (2,), 只由 `_entity_poly` 发布的 protein 和 RNA entity.
    entities = parse_mmcif_entities(mmcif_path, "1abc")
    assert [entity["sequence_id"] for entity in entities] == ["1ABC_1", "1ABC_2"]
    assert entities[0]["sequence"] == "ACD"
    assert entities[0]["label_asym_ids"] == ["A", "B"]
    assert entities[1]["sequence_class"] == "rna"
    assert entities[1]["label_asym_ids"] == ["C"]
