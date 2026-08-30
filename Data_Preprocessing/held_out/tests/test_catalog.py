"""验证序列身份, 长度边界, 官方 FASTA 和 held-out 资产契约."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from held_out_pipeline.catalog import (
    _select_official_smoke_pdbs,
    _write_fasta,
    classify_polymer_type,
    compare_official_fasta,
    inspect_training_assets,
    normalize_sequence,
    sequence_is_comparable,
    summarize_entities,
)


def test_sequence_normalization_and_length_boundaries() -> None:
    """规范序列只删除空白并大写, protein 30 和核酸 20 都是包含边界."""

    assert normalize_sequence(" a C\nD? ") == "ACD?"
    assert not sequence_is_comparable("protein", 29)
    assert sequence_is_comparable("protein", 30)
    assert not sequence_is_comparable("rna", 19)
    assert sequence_is_comparable("rna", 20)
    assert sequence_is_comparable("dna", 20)
    assert sequence_is_comparable("hybrid", 20)
    assert not sequence_is_comparable("other", 200)


def test_polymer_classification_and_multichain_residue_counts() -> None:
    """polypeptide 前缀统一归 protein, 多 chain entity 按 chain instance 计残基."""

    assert classify_polymer_type("polypeptide(L)") == "protein"
    assert classify_polymer_type("polypeptide(D)") == "protein"
    assert classify_polymer_type("polyribonucleotide") == "rna"
    assert classify_polymer_type("polydeoxyribonucleotide") == "dna"
    assert (
        classify_polymer_type("polydeoxyribonucleotide/polyribonucleotide hybrid")
        == "hybrid"
    )
    assert classify_polymer_type("polysaccharide(D)") == "other"
    # list[dict] (2,), 一条 30 aa 双 chain protein 和一条 19 nt 单 chain RNA.
    entities = [
        {
            "sequence_class": "protein",
            "length": 30,
            "label_asym_ids": ["A", "B"],
            "comparable": True,
        },
        {
            "sequence_class": "rna",
            "length": 19,
            "label_asym_ids": ["C"],
            "comparable": False,
        },
    ]
    # dict, entity, chain instance 和全长残基的总计及可比子集计数.
    summary = summarize_entities(entities)
    assert summary["entity_count"] == 2
    assert summary["chain_count"] == 3
    assert summary["residue_count"] == 79
    assert summary["comparable_chain_count"] == 2
    assert summary["comparable_residue_count"] == 60


def test_nucleic_mmseqs_fasta_changes_u_to_t_without_changing_natural_fasta(
    tmp_path: Path,
) -> None:
    """U/T 等价只存在于派生比对 FASTA, 自然 FASTA 保持 RNA 的 U."""

    # dict, 同时含 U 和 T 的四碱基 RNA entity.
    entity = {"sequence_id": "1ABC_1", "sequence": "AUTG"}
    # Path, 自然序列视图和 U->T 派生比对视图.
    natural_path = tmp_path / "natural.fasta"
    mmseqs_path = tmp_path / "mmseqs.fasta"
    _write_fasta(natural_path, [entity], False)
    _write_fasta(mmseqs_path, [entity], True)
    assert natural_path.read_text(encoding="utf-8").endswith("AUTG\n")
    assert mmseqs_path.read_text(encoding="utf-8").endswith("ATTG\n")


def test_official_fasta_comparison_is_per_entity_and_detects_mismatch() -> None:
    """官方 smoke 按 `<PDB>_<entity>` 对齐, 不依赖 FASTA 记录顺序."""

    # list[dict] (2,), 本地 mmCIF 派生的两个 entity identity 和全长序列.
    local_entities = [
        {"sequence_id": "4HHB_1", "sequence": "ACD"},
        {"sequence_id": "4HHB_2", "sequence": "EFG"},
    ]
    # str, 顺序与本地相反且含序列空白的合成 RCSB per-entry FASTA.
    official = ">4HHB_2|Chains B, D\nEFG\n>4HHB_1|Chains A, C\nA C D\n"
    assert compare_official_fasta("4hhb", local_entities, official)["passed"]
    # dict, 只让 entity 2 最后一位不同的逐 entity 对照报告.
    mismatch = compare_official_fasta("4hhb", local_entities, official.replace("EFG", "EFA"))
    assert not mismatch["passed"]
    assert [row["equal"] for row in mismatch["entities"]] == [True, False]


def test_official_smoke_selection_covers_protein_nucleic_and_multichain_roles() -> None:
    """三个 smoke 身份依次覆盖 protein, 核酸和多 chain entity, 且彼此不同."""

    # dict[str,list[dict]], 三个 PDB 分别只满足一个优先 smoke 角色.
    entities_by_pdb = {
        "1aaa": [{"sequence_class": "protein", "label_asym_ids": ["A"]}],
        "1bbb": [{"sequence_class": "rna", "label_asym_ids": ["B"]}],
        "1ccc": [{"sequence_class": "other", "label_asym_ids": ["C", "D"]}],
    }
    assert _select_official_smoke_pdbs(entities_by_pdb, 3) == ["1aaa", "1bbb", "1ccc"]


def test_training_asset_audit_accepts_exact_80_cube_and_rejects_short_cube(
    tmp_path: Path,
) -> None:
    """完整资产的 80³ 边界通过, 任一维 79 时只记为 short_map."""

    # Path, 合成 A-G 数据根及当前 PDB 的 density/parse/labels 子目录.
    data_root = tmp_path / "data"
    pdb_id = "1abc"
    density_root = data_root / "density" / pdb_id
    parse_root = data_root / "parse" / pdb_id
    label_root = data_root / "labels" / pdb_id
    density_root.mkdir(parents=True)
    parse_root.mkdir(parents=True)
    label_root.mkdir(parents=True)
    # ndarray float32 (3,), 三个世界 XYZ 轴的体素尺寸, 单位 Å.
    voxel_size = np.asarray([1.0, 1.0, 1.0], dtype=np.float32)
    # ndarray float32 (3,), 合成网格的世界 XYZ 原点, 单位 Å.
    origin = np.asarray([0.0, 0.0, 0.0], dtype=np.float32)

    def write_assets(shape_zyx: tuple[int, int, int]) -> None:
        """写出资产审计所需的最小一致文件集合."""

        np.savez(
            density_root / "exp.npz",
            canonical_shape_zyx=np.asarray(shape_zyx, dtype=np.int64),
            voxel_size=voxel_size,
            origin=origin,
        )
        np.savez(density_root / "sim.npz", voxel_size=voxel_size, origin=origin)
        for name in ("ligand_dist.npz", "ligand_area.npz"):
            np.savez(
                density_root / name,
                grid_shape_zyx=np.asarray(shape_zyx, dtype=np.int64),
                voxel_size_xyz=voxel_size,
                origin_xyz=origin,
            )
        # tuple[int,int,int,int], 单通道完整体数组的 `(1,Z,Y,X)` 形状.
        full_shape = (1, *shape_zyx)
        np.lib.format.open_memmap(density_root / "exp.npy", mode="w+", dtype=np.float32, shape=full_shape)
        np.lib.format.open_memmap(density_root / "sim.npy", mode="w+", dtype=np.float32, shape=full_shape)
        np.lib.format.open_memmap(
            density_root / "ligand_dist.npy", mode="w+", dtype=np.float16, shape=full_shape
        )
        np.lib.format.open_memmap(
            density_root / "union_mask.npy", mode="w+", dtype=np.bool_, shape=full_shape
        )
        np.savez(parse_root / "receptor_tokens.npz", coords=np.zeros((2, 3), dtype=np.float32))
        np.savez(label_root / "atom_labels.npz", binding_atom=np.zeros((2,), dtype=np.bool_))

    write_assets((80, 80, 80))
    assert inspect_training_assets(data_root, pdb_id)["status"] == "eligible"
    write_assets((79, 80, 80))
    # dict, 只有 Z 轴低于 80 的资产审计结果.
    short_report = inspect_training_assets(data_root, pdb_id)
    assert short_report["status"] == "short_map"
    assert not short_report["passed"]
