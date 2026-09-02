"""验证 MMseqs2 边界, 一对一 chain 匹配和 PDB coverage 聚合."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from held_out_pipeline.redundancy import (
    _build_chain_tables,
    _orient_hit,
    calculate_pdb_edge,
    classify_pdb_redundancy,
    parse_mmseqs_rows,
    run_mmseqs_shard,
)


def test_redundancy_classifier_rejects_zero_pdb_threshold() -> None:
    """零阈值不属于公开判定契约."""

    with pytest.raises(ValueError, match=r"\(0, 1\]"):
        classify_pdb_redundancy(0.5, 0.5, 0.5, 0.5, "or", 0.0)


def make_chain(chain_id: str, length: int) -> dict[str, object]:
    """建立合成 comparable chain 记录."""

    return {
        "chain_id": chain_id,
        "entity_id": chain_id,
        "sequence_id": f"1ABC_{chain_id}",
        "length": length,
        "sequence_class": "protein",
    }


def make_evidence(
    chain_A: str,
    chain_B: str,
    length_A: int,
    length_B: int,
) -> dict[str, object]:
    """建立合成高重复 chain 边见证."""

    return {
        "chain_A": chain_A,
        "chain_B": chain_B,
        "entity_A": chain_A,
        "entity_B": chain_B,
        "sequence_id_A": f"A_{chain_A}",
        "sequence_id_B": f"B_{chain_B}",
        "length_A": length_A,
        "length_B": length_B,
        "sequence_kind": "protein",
        "identity": 0.3,
        "coverage_A": 0.8,
        "coverage_B": 0.8,
    }


def brute_matching_value(
    chains_A: list[dict[str, object]],
    chains_B: list[dict[str, object]],
    edge_pairs: set[tuple[str, str]],
    objective: str,
) -> int:
    """穷举小二分图, 返回 chain, A 残基或 B 残基目标的最优值."""

    def search(index_A: int, used_B: set[int]) -> int:
        """从 A 侧 index_A 开始枚举不复用 B chain 的剩余最大权匹配."""

        if index_A == len(chains_A):
            return 0
        # int, 不匹配当前 A chain 时的剩余最优值.
        best_value = search(index_A + 1, used_B)
        for index_B, chain_B in enumerate(chains_B):
            # tuple[str, str], 当前候选 A/B chain identity.
            pair = (str(chains_A[index_A]["chain_id"]), str(chain_B["chain_id"]))
            if index_B in used_B or pair not in edge_pairs:
                continue
            if objective == "chain":
                edge_value = 1
            elif objective == "residue_A":
                edge_value = int(chains_A[index_A]["length"])
            else:
                edge_value = int(chain_B["length"])
            # int, 当前边权和选择该边后的剩余最优值.
            best_value = max(best_value, edge_value + search(index_A + 1, used_B | {index_B}))
        return best_value

    return search(0, set())


def test_mmseqs_parser_uses_inclusive_identity_and_both_coverages(tmp_path: Path) -> None:
    """protein 30% 与双向 80% 都是包含边界, 任一 coverage 低于边界即拒绝."""

    # Path, 同时覆盖包含边界和两类单向 coverage 失败的合成 MMseqs2 TSV.
    result_path = tmp_path / "hits.tsv"
    result_path.write_text(
        "Q1\tT1\t0.30\t0.80\t0.80\t30\t30\t30\t1\n"
        "Q2\tT2\t0.299\t0.90\t0.90\t30\t30\t30\t1\n"
        "Q3\tT3\t0.40\t0.799\t0.90\t30\t30\t30\t1\n"
        "Q4\tT4\t0.40\t0.90\t0.799\t30\t30\t30\t1\n",
        encoding="utf-8",
    )
    # list[dict], (1,), 只有 identity=0.30 且 qcov=tcov=0.80 的边界命中.
    hits = list(parse_mmseqs_rows(result_path, "protein"))
    assert [(hit["query"], hit["target"]) for hit in hits] == [("Q1", "T1")]


def test_chain_matching_never_reuses_one_target_chain() -> None:
    """两条 A chain 同时命中一条 B chain 时, 最大匹配只能覆盖一条 A chain."""

    # list[dict], A 侧两条 chain 和 B 侧唯一 chain.
    chains_A = [make_chain("A1", 100), make_chain("A2", 50)]
    chains_B = [make_chain("B1", 80)]
    # dict[tuple, dict], 两条 A chain 都连接同一 B chain 的二分图.
    evidence = {
        ("A1", "B1"): make_evidence("A1", "B1", 100, 80),
        ("A2", "B1"): make_evidence("A2", "B1", 50, 80),
    }
    # dict, 三个一对一目标及四个方向 coverage 的聚合结果.
    edge = calculate_pdb_edge("held_out_internal", "a", "b", chains_A, chains_B, evidence)
    assert len(edge["chain_matching"]) == 1
    assert edge["chain_A"] == 0.5
    assert edge["chain_B"] == 1.0
    assert not {
        "pdb_coverage_mode",
        "pdb_coverage_threshold",
        "chain_pass",
        "residue_pass",
        "redundant",
    } & set(edge)


def test_many_chain_copies_use_entity_capacity_without_cartesian_evidence() -> None:
    """两千对同 entity chain copies 只需一条 entity edge, 且输出不复用 chain."""

    # int, 单个 entity 在 A/B 两侧各自映射的高拷贝 chain 数.
    copy_count = 2000
    # list[dict], (copy_count,), A/B 两侧共享 entity identity 的可互换 chain copies.
    chains_A = [
        {**make_chain(f"A{index:04d}", 100), "entity_id": "EA", "sequence_id": "A_EA"}
        for index in range(copy_count)
    ]
    chains_B = [
        {**make_chain(f"B{index:04d}", 80), "entity_id": "EB", "sequence_id": "B_EB"}
        for index in range(copy_count)
    ]
    # dict[tuple, dict], (1,), 一条 entity hit 表示两组 chain copies 间的完全二分图.
    evidence = {("EA", "EB"): make_evidence("EA", "EB", 100, 80)}
    # dict, entity 容量求解后展开出的三组各含 2,000 条 chain matching.
    edge = calculate_pdb_edge("held_out_internal", "a", "b", chains_A, chains_B, evidence)
    assert len(edge["chain_matching"]) == copy_count
    assert len({match["chain_A"] for match in edge["chain_matching"]}) == copy_count
    assert len({match["chain_B"] for match in edge["chain_matching"]}) == copy_count
    assert edge["chain_A"] == edge["chain_B"] == 1.0
    assert edge["residue_A"] == edge["residue_B"] == 1.0


def test_three_matching_objectives_are_solved_separately() -> None:
    """同一 A chain 可匹配两个 B chain 时, B 残基目标选择较长 B, 而非复用 chain 匹配."""

    # list[dict], 一条 A chain 和两条长度差异明显的 B chain.
    chains_A = [make_chain("A1", 100)]
    chains_B = [make_chain("B1", 10), make_chain("B2", 100)]
    # dict[tuple, dict], 唯一 A chain 同时连接两条 B chain 的二分图.
    evidence = {
        ("A1", "B1"): make_evidence("A1", "B1", 100, 10),
        ("A1", "B2"): make_evidence("A1", "B2", 100, 100),
    }
    # dict, B 残基目标应选 100 aa 的 B2, chain 目标只要求一条边.
    edge = calculate_pdb_edge("reference", "a", "b", chains_A, chains_B, evidence)
    assert edge["residue_B_matching"][0]["chain_B"] == "B2"
    assert edge["residue_B"] == 100 / 110
    assert edge["chain_B"] == 0.5


def test_pdb_modes_select_or_combine_chain_and_residue_levels() -> None:
    """四种 mode 只选取或组合两级判断, 阈值和 A/B 方向保持独立."""

    # dict[str, bool], 只有 chain 层级达到 0.5 时的 chain 模式判定字段.
    chain_only = classify_pdb_redundancy(0.5, 0.0, 0.1, 0.1, "chain", 0.5)
    assert chain_only == {"chain_pass": True, "residue_pass": False, "redundant": True}
    assert not classify_pdb_redundancy(0.5, 0.0, 0.1, 0.1, "residue", 0.5)[
        "redundant"
    ]
    assert classify_pdb_redundancy(0.5, 0.0, 0.1, 0.1, "or", 0.5)["redundant"]
    assert not classify_pdb_redundancy(0.5, 0.0, 0.1, 0.1, "and", 0.5)["redundant"]
    # dict[str, bool], chain 和 residue 分别由不同方向达到阈值的 and 判定.
    crossed = classify_pdb_redundancy(0.5, 0.0, 0.0, 0.5, "and", 0.5)
    assert crossed == {"chain_pass": True, "residue_pass": True, "redundant": True}
    assert not classify_pdb_redundancy(0.499, 0.0, 0.499, 0.0, "or", 0.5)["redundant"]
    assert classify_pdb_redundancy(0.6, 0.0, 0.0, 0.6, "and", 0.6)["redundant"]


def test_chain_table_excludes_short_entities_and_internal_hit_orientation_swaps_sides() -> None:
    """短 entity 不进入 coverage 分母, 反向 held-out hit 定向后同步交换 entity 与 coverage."""

    # list[dict], (3,), A PDB 含两条可比 chain 和一条短链, Z PDB 含一条可比 chain.
    entities = [
        {
            "sequence_id": "1AAA_1",
            "pdb_id": "1aaa",
            "entity_id": "1",
            "length": 30,
            "sequence_class": "protein",
            "label_asym_ids": ["A", "B"],
            "comparable": True,
        },
        {
            "sequence_id": "1AAA_2",
            "pdb_id": "1aaa",
            "entity_id": "2",
            "length": 29,
            "sequence_class": "protein",
            "label_asym_ids": ["C"],
            "comparable": False,
        },
        {
            "sequence_id": "1ZZZ_1",
            "pdb_id": "1zzz",
            "entity_id": "1",
            "length": 40,
            "sequence_class": "protein",
            "label_asym_ids": ["Z"],
            "comparable": True,
        },
    ]
    # dict, 分别用于 alignment identity 解析和 PDB coverage 分母的两个索引.
    entity_by_id, chains_by_pdb = _build_chain_tables(entities)
    assert [chain["chain_id"] for chain in chains_by_pdb["1aaa"]] == ["A", "B"]
    # tuple | None, 原 query=1zzz 在字典序定向后应成为 B 侧.
    oriented = _orient_hit(
        {
            "query": "1ZZZ_1",
            "target": "1AAA_1",
            "sequence_kind": "protein",
            "identity": 0.5,
            "query_coverage": 0.9,
            "target_coverage": 0.8,
            "alignment_length": 30,
            "evalue": 1.0,
        },
        entity_by_id,
        {"1aaa", "1zzz"},
        set(),
    )
    assert oriented is not None
    # tuple[str, str, str], relation 和固定字典序 PDB A/B identity.
    pair_key, hit = oriented
    assert pair_key == ("held_out_internal", "1aaa", "1zzz")
    assert hit["entity_A"] == "1"
    assert hit["coverage_A"] == 0.8
    assert hit["coverage_B"] == 0.9


def test_matching_objectives_equal_brute_force_on_random_small_domains() -> None:
    """随机小图中的三个 SciPy 匹配目标都与独立穷举最优值一致."""

    # Generator, 随机小图回归测试的固定数据子流.
    random_generator = np.random.default_rng(np.random.SeedSequence(20260830))
    for _ in range(25):
        # list[int], (4,), A/B 两侧合成 chain 的全长残基数.
        lengths_A = random_generator.integers(1, 150, size=4).tolist()
        lengths_B = random_generator.integers(1, 150, size=4).tolist()
        # list[dict], (4,), 由当前随机长度建立的 A/B chain 表.
        chains_A = [make_chain(f"A{index}", int(length)) for index, length in enumerate(lengths_A)]
        chains_B = [make_chain(f"B{index}", int(length)) for index, length in enumerate(lengths_B)]
        # ndarray bool, (4, 4), 第一轴索引 chains_A, 第二轴索引 chains_B; True 表示该 chain 对存在高重复边.
        edge_mask = random_generator.random((4, 4)) < 0.45
        # dict[tuple, dict], 邻接矩阵中 True 位置对应的高重复 chain 见证.
        evidence = {
            (f"A{index_A}", f"B{index_B}"): make_evidence(
                f"A{index_A}",
                f"B{index_B}",
                int(lengths_A[index_A]),
                int(lengths_B[index_B]),
            )
            for index_A in range(4)
            for index_B in range(4)
            if bool(edge_mask[index_A, index_B])
        }
        # dict, SciPy 三目标最大权匹配和对应 PDB coverage.
        edge = calculate_pdb_edge(
            "held_out_internal", "a", "b", chains_A, chains_B, evidence
        )
        # set[tuple[str, str]], 交给独立穷举器的无权 chain 边集合.
        edge_pairs = set(evidence)
        assert len(edge["chain_matching"]) == brute_matching_value(
            chains_A, chains_B, edge_pairs, "chain"
        )
        assert sum(match["length_A"] for match in edge["residue_A_matching"]) == brute_matching_value(
            chains_A, chains_B, edge_pairs, "residue_A"
        )
        assert sum(match["length_B"] for match in edge["residue_B_matching"]) == brute_matching_value(
            chains_A, chains_B, edge_pairs, "residue_B"
        )


def test_mmseqs_command_requests_real_identity_and_bidirectional_coverage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """正式 MMseqs2 命令显式包含 alignment-mode 3, seq-id-mode 0 与 cov-mode 0."""

    # Path, 合成 query/target FASTA 的输出根; 运行入口不读取完成标记作为门控.
    output_root = tmp_path / "output"
    # Path, protein/nucleic query 和 target FASTA 目录.
    fasta_root = output_root / "fasta" / "mmseqs"
    fasta_root.mkdir(parents=True)
    for kind in ("protein", "nucleic"):
        (fasta_root / f"{kind}_query_000.fasta").write_text(">Q\nAAAA\n", encoding="utf-8")
        (fasta_root / f"{kind}_target.fasta").write_text(">T\nAAAA\n", encoding="utf-8")
    # list[list[str]], fake subprocess 收集的两条 easy-search 和一条 version 命令.
    commands: list[list[str]] = []

    def fake_run(command: list[str], **kwargs):
        """记录命令并为 easy-search 建立空结果."""

        commands.append(command)
        if command[1] == "easy-search":
            Path(command[4]).parent.mkdir(parents=True, exist_ok=True)
            Path(command[4]).write_text("", encoding="utf-8")
            return SimpleNamespace(stdout="")
        return SimpleNamespace(stdout="18-8cc5c\n")

    monkeypatch.setattr("held_out_pipeline.redundancy.subprocess.run", fake_run)
    run_mmseqs_shard(Path("/tools/mmseqs"), output_root, 0, 8)
    # list[list[str]], (2,), protein 和 nucleic 的正式 easy-search 参数.
    easy_search_commands = [command for command in commands if command[1] == "easy-search"]
    assert len(easy_search_commands) == 2
    assert [
        command[command.index("--min-seq-id") + 1] for command in easy_search_commands
    ] == ["0.3", "0.8"]
    for command in easy_search_commands:
        assert command[command.index("--alignment-mode") + 1] == "3"
        assert command[command.index("--seq-id-mode") + 1] == "0"
        assert command[command.index("--cov-mode") + 1] == "0"
        assert command[command.index("-c") + 1] == "0.8"
