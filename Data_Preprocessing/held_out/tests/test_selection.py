"""验证 held-out 冲突图独立集, 统一身份证与测试视图子集关系."""

from __future__ import annotations

import json
from pathlib import Path

from held_out_pipeline.selection import (
    _strongest_edge,
    finalize_identity_views,
    greedy_independent_set,
    sample_test_0,
)


def write_json(path: Path, value: object) -> None:
    """写出测试输入 JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    """写出测试输入 JSONL."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def make_base_record(pdb_id: str, ligand_count: int, comparable_chains: int = 1) -> dict[str, object]:
    """建立质量, 资产与序列均成功的最小 held-out 基础身份证."""

    return {
        "pdb_id": pdb_id,
        "emdb_ids": [f"EMD-{pdb_id}"],
        "first_map_release": "2026-01-01",
        "quality": {"map_resolution": 3.0, "cc_contour": 0.8, "passed": True},
        "assets": {"status": "eligible", "passed": True, "shape_zyx": [80, 80, 80], "detail": ""},
        "ligands": {
            "total_count": ligand_count,
            "type_counts": {},
            "strict_1_100_passed": 1 < ligand_count < 100,
        },
        "sequence": {
            "status": "ok",
            "error": None,
            "entity_count": comparable_chains,
            "chain_count": comparable_chains,
            "residue_count": comparable_chains * 30,
            "comparable_entity_count": comparable_chains,
            "comparable_chain_count": comparable_chains,
            "comparable_residue_count": comparable_chains * 30,
            "by_class": {},
        },
    }


def make_edge(pdb_A: str, pdb_B: str, relation: str = "held_out_internal") -> dict[str, object]:
    """建立当前参数下判为冗余的 PDB 边."""

    return {
        "relation": relation,
        "pdb_A": pdb_A,
        "pdb_B": pdb_B,
        "chain_A": 0.5,
        "chain_B": 0.5,
        "residue_A": 0.4,
        "residue_B": 0.4,
        "chain_pass": True,
        "residue_pass": False,
        "redundant": True,
    }


def test_greedy_selection_is_pairwise_independent_not_connected_component_collapse() -> None:
    """A-B 与 B-C 冲突不产生 A-C 冲突, 输出只拒绝已接受的直接邻居."""

    # dict[str, dict], 三节点路径图在固定随机顺序下的贪心接受状态.
    states = greedy_independent_set(["a", "b", "c"], [("a", "b"), ("b", "c")], 3407)
    # set[str], 输出中的两两无直接冲突 PDB identity.
    accepted = {pdb_id for pdb_id, state in states.items() if state["accepted"]}
    assert not ({"a", "b"} <= accepted)
    assert not ({"b", "c"} <= accepted)
    assert len(accepted) == 2
    # list[dict] (1,), 路径图中唯一被更早直接邻居拒绝的状态.
    rejected = [state for state in states.values() if not state["accepted"]]
    assert len(rejected) == 1
    assert rejected[0]["rejected_by"] in accepted


def test_test_0_sampling_is_deterministic_and_without_replacement() -> None:
    """独立抽样子流对同一集合稳定, 且不产生重复 PDB."""

    # list[str] (20,), 输入顺序可反转的合成独立集 identity.
    pdb_ids = [f"p{index}" for index in range(20)]
    # list[str] (10,), 同一排序集合和固定抽样子流产生的两次无放回结果.
    first = sample_test_0(pdb_ids, 10, 3407)
    second = sample_test_0(reversed(pdb_ids), 10, 3407)
    assert first == second
    assert len(first) == len(set(first)) == 10


def test_strongest_edge_prioritizes_redundant_witness_in_and_mode() -> None:
    """and 模式存在冗余边时, 单项 coverage 更高的非冗余边不能替代排除见证."""

    # dict, chain 单项为 0.99 但 residue 未过阈值的非冗余参考边.
    nonredundant_edge = make_edge("a", "x", relation="reference")
    nonredundant_edge.update(
        {
            "chain_A": 0.99,
            "chain_B": 0.1,
            "residue_A": 0.49,
            "residue_B": 0.1,
            "chain_pass": True,
            "residue_pass": False,
            "redundant": False,
        }
    )
    # dict, chain 与 residue 两级都恰好达到 0.5 的冗余参考边.
    redundant_edge = make_edge("a", "y", relation="reference")
    redundant_edge.update(
        {
            "residue_A": 0.5,
            "residue_B": 0.5,
            "residue_pass": True,
        }
    )
    # dict, 身份证应保存真正触发 reference_redundant 的 Y 边.
    witness = _strongest_edge([nonredundant_edge, redundant_edge], "a")
    assert witness is not None
    assert witness["other_pdb_id"] == "y"
    assert witness["redundant"]


def test_finalize_keeps_zero_comparable_chain_and_test_1_is_test_0_subset(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """零可比 chain 不是失败; test_1 只从 test_0 应用 occurrence 数过滤."""

    # Path, 最终身份视图的合成输出根; 运行入口不读取完成标记作为门控.
    output_root = tmp_path / "output"
    # list[dict] (4,), occurrence 数覆盖 test_1 两个边界外侧并含一个零可比 chain PDB.
    base_records = [
        make_base_record("a", 10),
        make_base_record("b", 1),
        make_base_record("c", 101),
        make_base_record("d", 5, comparable_chains=0),
    ]
    write_jsonl(output_root / "held_out_base.jsonl", base_records)
    # Path, 四个冻结 held-out PDB identity 的合成 split.
    held_out_path = tmp_path / "held.json"
    write_json(held_out_path, ["a", "b", "c", "d"])
    # list[Path] (3,), 空的 train/validation/calibration 暴露参考 split.
    split_paths = []
    for name in ("train", "validation", "calibration"):
        path = tmp_path / f"{name}.json"
        write_json(path, [])
        split_paths.append(path)
    # list[dict] (2,), A-B-C 路径形内部冗余边.
    edges = [make_edge("a", "b"), make_edge("b", "c")]

    def fake_build_edges(*_args, **_kwargs):
        """返回固定内部冲突链, 避免单元测试调用 MMseqs2."""

        return edges, {
            "raw_qualifying_alignment_count": 2,
            "oriented_entity_hit_count": 2,
            "pdb_edge_count": 2,
            "redundant_pdb_edge_count": 2,
            "relation_counts": {"held_out_internal": 2},
            "mode": "or",
            "threshold": 0.5,
        }

    monkeypatch.setattr("held_out_pipeline.selection.build_redundancy_edges", fake_build_edges)
    # dict, 使用固定边和 test_0_size=2 得到的最终汇总.
    summary = finalize_identity_views(
        output_root,
        split_paths[0],
        split_paths[1],
        split_paths[2],
        held_out_path,
        1,
        "or",
        0.5,
        3407,
        2,
    )
    # list[str] (2,), 未应用 occurrence 数过滤的固定种子 test_0.
    test_0 = json.loads((output_root / "test_0.json").read_text(encoding="utf-8"))["pdb_ids"]
    # list[str], 只从 test_0 派生的 `(1, 100)` occurrence 子集.
    test_1 = json.loads((output_root / "test_1.json").read_text(encoding="utf-8"))["pdb_ids"]
    # dict[str, dict], 四个 PDB 的最终统一身份证索引.
    identities = {
        row["pdb_id"]: row
        for row in (
            json.loads(line)
            for line in (output_root / "held_out_identity.jsonl").read_text(encoding="utf-8").splitlines()
        )
    }
    assert set(test_1) <= set(test_0)
    assert all(1 < identities[pdb_id]["ligands"]["total_count"] < 100 for pdb_id in test_1)
    assert identities["d"]["selection"]["base_eligible"]
    assert summary["test_0_count"] == 2
