"""把 held-out 基础事实和冗余边合成为身份证与测试视图.

主要入口是 :func:`finalize_identity_views`. 该入口先调用 redundancy 模块生成完整 PDB 对关系, 再排除参考集冗余, 最后把 held-out 内部冲突图的固定种子贪心极大独立集写为 `full_test`, 并派生 `test_0`, `test_1`.

本模块不解析 mmCIF, 不运行 MMseqs2, 也不改变质量, 资产或序列阈值.

全部路径相对于调用方 `output_root`. `held_out_identity.jsonl` 一行对应一个冻结 held-out PDB; `full_test.json`, `test_0.json`, `test_1.json` 各保存一个身份视图; `stage2/summary.json` 与 `_COMPLETE` 收口第二组产物.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Literal

import numpy as np

from held_out_pipeline.redundancy import build_redundancy_edges


# str, held-out 统一身份证的稳定 schema identity.
IDENTITY_SCHEMA = "adaligand.held_out_identity"
# int, 本轮身份证字段契约版本.
IDENTITY_SCHEMA_VERSION = 1


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """读取 UTF-8 JSONL 对象记录."""

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise TypeError(f"{path}:{line_number} 必须是 JSON object.")
            records.append(value)
    return records


def _write_text(path: Path, text: str) -> None:
    """以同目录临时文件原子替换 UTF-8 文本."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary_path.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary_path, path)


def _write_json(path: Path, value: Any) -> None:
    """按稳定键序写出 JSON."""

    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """按传入顺序逐行写出 JSONL, 再原子替换目标文件."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary_path, path)


def greedy_independent_set(
    eligible_pdb_ids: Iterable[str],
    conflict_pairs: Iterable[tuple[str, str]],
    seed: int,
) -> dict[str, dict[str, Any]]:
    """按固定 SeedSequence 顺序构建 held-out 冲突图的贪心极大独立集.

    输入参数:
        - eligible_pdb_ids: Iterable[str], 已排除参考冗余的候选身份.
        - conflict_pairs: Iterable[tuple[str, str]], 当前 PDB 参数下的 held-out 内部冗余无向边.
        - seed: int, 全局种子; 本入口固定使用 `spawn_key=(0,)`.

    返回字段:
        - states: dict[str, dict], 候选 PDB identity 到贪心选择状态的映射.
            - states[*].greedy_rank: int, 当前 PDB 在固定随机访问顺序中的零基排名.
            - states[*].accepted: bool, 当前 PDB 是否被加入独立集.
            - states[*].rejected_by: str | None, 拒绝当前 PDB 的更早已接受直接邻居.

    每个未接受候选都保存一个已接受的直接冲突邻居, 因此接受集合是极大独立集; 本算法不保证它是基数最大的独立集.
    """

    # list[str] (N,), 去重, 排序后的统一资格 PDB identity.
    sorted_ids = sorted(set(eligible_pdb_ids))
    # set[str], 过滤内部边两端是否仍属于当前选择域.
    eligible_set = set(sorted_ids)
    # dict[str, set[str]], 当前参数下的 held-out 冗余无向邻接表.
    neighbors: dict[str, set[str]] = defaultdict(set)
    for pdb_A, pdb_B in conflict_pairs:
        if pdb_A in eligible_set and pdb_B in eligible_set:
            neighbors[pdb_A].add(pdb_B)
            neighbors[pdb_B].add(pdb_A)
    # Generator, 贪心顺序专用随机子流; 与 test_0 抽样子流相互独立.
    random_generator = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(0,)))
    # list[str] (N,), 对排序身份做一次固定种子全排列后的贪心访问顺序.
    random_order = [sorted_ids[index] for index in random_generator.permutation(len(sorted_ids))]
    # set[str], 已接受且两两无冲突的当前独立集.
    accepted_ids: set[str] = set()
    # dict[str, dict], 每个统一资格 PDB 的顺序, 接受布尔值和直接拒绝见证.
    states: dict[str, dict[str, Any]] = {}
    for greedy_rank, pdb_id in enumerate(random_order):
        # list[str], 当前 PDB 已经接受的直接冗余邻居; 非传递闭包.
        accepted_neighbors = [neighbor for neighbor in neighbors[pdb_id] if neighbor in accepted_ids]
        if accepted_neighbors:
            # str, 最早接受的直接邻居; 保存稳定, 可追溯的拒绝见证.
            rejected_by = min(
                accepted_neighbors,
                key=lambda neighbor: int(states[neighbor]["greedy_rank"]),
            )
            states[pdb_id] = {
                "greedy_rank": greedy_rank,
                "accepted": False,
                "rejected_by": rejected_by,
            }
        else:
            accepted_ids.add(pdb_id)
            states[pdb_id] = {
                "greedy_rank": greedy_rank,
                "accepted": True,
                "rejected_by": None,
            }
    return states


def sample_test_0(full_test_pdb_ids: Iterable[str], sample_size: int, seed: int) -> list[str]:
    """用独立 SeedSequence 子流从 full_test 无放回抽取 `test_0`.

    输入参数:
        - full_test_pdb_ids: Iterable[str], 贪心极大独立集 full_test 中的 PDB identities.
        - sample_size: int, 要抽取的 test_0 PDB 数.
        - seed: int, 全局 SeedSequence entropy; 本入口固定使用 `spawn_key=(1,)`.

    返回值:
        - test_0_pdb_ids: 长度 sample_size 的 list[str], 按无放回随机抽取顺序保存的 PDB identities.

    输入集合先排序去重, 再固定使用 `SeedSequence(seed, spawn_key=(1,))`; 返回顺序就是随机抽取顺序.
    """

    # list[str] (N_full_test,), full_test 的稳定 PDB identity 顺序.
    sorted_ids = sorted(set(full_test_pdb_ids))
    if len(sorted_ids) < sample_size:
        raise ValueError(f"full_test 只有 {len(sorted_ids)} 个 PDB, 不足 {sample_size} 个.")
    # Generator, test_0 抽样专用随机子流; 不受贪心顺序消费量影响.
    random_generator = np.random.default_rng(np.random.SeedSequence(seed, spawn_key=(1,)))
    # ndarray int64 (sample_size,), 无放回随机排列的前 sample_size 个索引.
    draw_indices = random_generator.permutation(len(sorted_ids))[:sample_size]
    return [sorted_ids[index] for index in draw_indices]


def _strongest_edge(edges: list[dict[str, Any]], pdb_id: str) -> dict[str, Any] | None:
    """优先从冗余边中按最大原始 coverage 选一个稳定直接见证.

    返回字段:
        - witness: dict | None, 没有直接关系时为 None; 否则返回一个压缩关系见证.
            - witness.other_pdb_id: str, 当前 pdb_id 的另一端 PDB identity.
            - witness.relation: str, 取 reference 或 held_out_internal.
            - witness.chain_A: float, 原始 PDB 边的 A 侧 chain coverage.
            - witness.chain_B: float, 原始 PDB 边的 B 侧 chain coverage.
            - witness.residue_A: float, 原始 PDB 边的 A 侧 residue coverage.
            - witness.residue_B: float, 原始 PDB 边的 B 侧 residue coverage.
            - witness.max_coverage: float, 四个原始 coverage 的最大值.
            - witness.chain_pass: bool, 当前阈值下的 chain 级判定.
            - witness.residue_pass: bool, 当前阈值下的 residue 级判定.
            - witness.redundant: bool, 当前 mode 和 threshold 下的最终判定.

    若没有冗余边, 再从全部非冗余关系中选择. 完整三组 matching 仍以 `redundancy_edges.jsonl` 为准.
    """

    if not edges:
        return None
    # list[dict], 从当前 pdb_id 视角压缩的直接关系; A/B 原始 coverage 不交换或丢失.
    compressed_edges = [
        {
            "other_pdb_id": edge["pdb_B"] if edge["pdb_A"] == pdb_id else edge["pdb_A"],
            "relation": edge["relation"],
            "chain_A": edge["chain_A"],
            "chain_B": edge["chain_B"],
            "residue_A": edge["residue_A"],
            "residue_B": edge["residue_B"],
            "max_coverage": max(
                float(edge["chain_A"]),
                float(edge["chain_B"]),
                float(edge["residue_A"]),
                float(edge["residue_B"]),
            ),
            "chain_pass": edge["chain_pass"],
            "residue_pass": edge["residue_pass"],
            "redundant": edge["redundant"],
        }
        for edge in edges
    ]
    return max(
        compressed_edges,
        key=lambda edge: (
            bool(edge["redundant"]),
            float(edge["max_coverage"]),
            str(edge["other_pdb_id"]),
        ),
    )


# ================================================================================================


def finalize_identity_views(
    output_root: Path,
    train_pdb_path: Path,
    validation_pdb_path: Path,
    calibration_pdb_path: Path,
    held_out_pdb_path: Path,
    alignment_shard_count: int,
    mode: Literal["or", "and"],
    threshold: float,
    seed: int,
    test_0_size: int,
) -> dict[str, Any]:
    """生成完整 PDB 关系, held-out 身份证和三个冻结测试视图.

    输入参数:
        - output_root: Path, 第一组产物, MMseqs2 TSV 和最终视图的共享根目录.
        - train_pdb_path: Path, train 暴露参考 PDB JSON 列表.
        - validation_pdb_path: Path, validation 暴露参考 PDB JSON 列表.
        - calibration_pdb_path: Path, calibration 暴露参考 PDB JSON 列表.
        - held_out_pdb_path: Path, 冻结 held-out PDB JSON 列表.
        - alignment_shard_count: int, 要合并的 MMseqs2 query 分片数.
        - mode: str, 取 or 或 and; 只组合 chain_pass 与 residue_pass.
        - threshold: float, chain 和 residue 两级共用的包含边界, 取值位于 `(0, 1]`.
        - seed: int, 贪心顺序和 test_0 抽样使用的 SeedSequence entropy.
        - test_0_size: int, test_0 固定抽取的 PDB 数.

    返回字段:
        - summary: dict, 保留 :func:`build_redundancy_edges` summary 并增加最终视图规模.
            - summary.held_out_pdb_count: int, 冻结 held-out PDB 数.
            - summary.base_eligible_count: int, 质量, 资产, 序列和参考冗余前置条件全部通过的 PDB 数.
            - summary.full_test_count: int, held-out 内部贪心极大独立集 PDB 数.
            - summary.test_0_count: int, 未应用 occurrence 数过滤的 test_0 PDB 数.
            - summary.test_1_count: int, 从 test_0 应用严格 `(1, 100)` 过滤后的 PDB 数.
            - summary.exclusion_reason_counts: dict[str, int], 四种前置排除原因各自出现的 PDB 数.
            - summary.seed: int, 当前固定随机 entropy.

    落盘产物:
        - `held_out_identity.jsonl`: JSONL; 每行一个冻结 held-out PDB 的统一身份证.
            - schema: str, 固定为 adaligand.held_out_identity.
            - schema_version: int, 当前为 1.
            - pdb_id: str, 小写 held-out PDB identity.
            - emdb_ids: list[str], 当前 PDB 对应的全部 EMDB identities.
            - first_map_release: str | None, 首次 EMDB 发布时间.
            - quality: dict, 从 held_out_base.jsonl 原样复制的质量事实.
            - assets: dict, 从 held_out_base.jsonl 原样复制的资产审计.
            - ligands: dict, 从 held_out_base.jsonl 原样复制的 occurrence 统计.
            - sequence: dict, 从 held_out_base.jsonl 原样复制的序列状态和 polymer 统计.
            - redundancy: dict, 当前 PDB 的参考和 held-out 内部冗余摘要.
                - redundancy.pdb_coverage_mode: str, 当前 or/and 组合模式.
                - redundancy.pdb_coverage_threshold: float, 当前 PDB coverage 包含边界.
                - redundancy.reference_edge_count: int, 当前 PDB 与成功序列目录中参考 PDB 的直接关系数.
                - redundancy.reference_redundant_edge_count: int, reference_edge_count 中 redundant=True 的关系数.
                - redundancy.reference_redundant: bool, 是否存在至少一条冗余参考关系.
                - redundancy.strongest_reference_edge: dict | None, 使用 :func:`_strongest_edge` 的压缩参考见证.
                - redundancy.internal_edge_count: int, 当前 PDB 与其他 held-out PDB 的直接关系数.
                - redundancy.internal_redundant_edge_count: int, internal_edge_count 中 redundant=True 的关系数.
                - redundancy.strongest_internal_edge: dict | None, 使用 :func:`_strongest_edge` 的压缩内部见证.
            - selection: dict, 当前 PDB 的前置资格, 极大独立集状态和测试视图成员身份.
                - selection.base_eligible: bool, 四类 exclusion_reasons 均未出现时为 True.
                - selection.exclusion_reasons: list[str], 可含 quality_failed, asset_failed, sequence_failed, reference_redundant.
                - selection.greedy_rank: int | None, 前置资格 PDB 在固定贪心顺序中的零基排名.
                - selection.full_test: bool, 当前 PDB 是否属于贪心极大独立集 full_test.
                - selection.full_test_rank: int | None, 当前 PDB 在 full_test 贪心接受顺序中的零基排名.
                - selection.rejected_by: str | None, 拒绝当前 PDB 的已接受直接冲突 PDB.
                - selection.rejection_edge: dict | None, 使用 :func:`_strongest_edge` 的直接冲突见证.
                - selection.test_0: bool, 当前 PDB 是否属于 test_0.
                - selection.test_0_rank: int | None, 当前 PDB 在 test_0 随机顺序中的零基排名.
                - selection.test_1: bool, 当前 PDB 是否属于 test_1.
                - selection.test_1_rank: int | None, 当前 PDB 在 test_1 保序子集中的零基排名.
        - `full_test.json`: dict; 满足全部前置条件且 held-out 内部无冗余边的贪心极大独立集.
            - schema_version: int, 当前为 1.
            - pdb_coverage_mode: str, 当前 or/and 组合模式.
            - pdb_coverage_threshold: float, 当前 PDB coverage 包含边界.
            - seed: int, 当前固定随机 entropy.
            - name: str, 固定为 full_test.
            - occurrence_filter: None, 表示不按 occurrence 数过滤.
            - pdb_ids: list[str], 按贪心接受顺序保存的 PDB identities.
        - `test_0.json`: dict; 从 full_test 无放回抽取且不应用 occurrence 数过滤的固定视图.
            - schema_version: int, 当前为 1.
            - pdb_coverage_mode: str, 当前 or/and 组合模式.
            - pdb_coverage_threshold: float, 当前 PDB coverage 包含边界.
            - seed: int, 当前固定随机 entropy.
            - name: str, 固定为 test_0.
            - occurrence_filter: None, 表示不按 occurrence 数过滤.
            - parent: str, 固定为 full_test.
            - pdb_ids: 长度 test_0_size 的 list[str], 按固定随机抽样顺序保存的 PDB identities.
        - `test_1.json`: dict; 只从 test_0 应用 occurrence 数过滤的保序子集.
            - schema_version: int, 与 test_0 相同.
            - pdb_coverage_mode: str, 与 test_0 相同.
            - pdb_coverage_threshold: float, 与 test_0 相同.
            - seed: int, 与 test_0 相同.
            - name: str, 固定为 test_1.
            - occurrence_filter: str, 固定为 `1 < total_count < 100`.
            - parent: str, 固定为 test_0.
            - pdb_ids: list[str], 从 test_0.pdb_ids 保序过滤得到的 PDB identities.
        - `stage2/summary.json`: dict; 字段与函数返回值相同.
        - `stage2/_COMPLETE`: 空文件; 本函数正常执行到末尾时写出, 不作为后续代码门控.

    选择顺序固定为质量, 资产, 序列成功, 无参考冗余, held-out 内部贪心极大独立集 full_test, 固定种子抽取 `test_0_size` 项, 最后仅对 `test_0` 应用 occurrence 总数 `(1, 100)` 过滤得到 `test_1`.

    完成标记只记录本步骤正常执行到末尾, 不参与失败率或步骤间门控.
    """

    # list[dict], reference 和 held-out internal 的全部 PDB 关系及三组 matching.
    edges, edge_summary = build_redundancy_edges(
        output_root,
        train_pdb_path,
        validation_pdb_path,
        calibration_pdb_path,
        held_out_pdb_path,
        alignment_shard_count,
        mode,
        threshold,
    )
    # list[dict] (N_held_out,), stage1 基础事实; 正式 N_held_out=2497.
    base_records = _read_jsonl(output_root / "held_out_base.jsonl")
    # dict[str, dict], PDB identity 到唯一基础身份证的映射.
    base_by_pdb = {str(record["pdb_id"]): record for record in base_records}
    # set[str], 冻结 held-out 身份基准.
    held_out_ids = {
        str(pdb_id).strip().lower()
        for pdb_id in json.loads(held_out_pdb_path.read_text(encoding="utf-8"))
    }
    if set(base_by_pdb) != held_out_ids:
        raise ValueError("held_out_base 与冻结 held-out PDB identity 不一致.")

    # dict[str, list[dict]], held-out PDB 到全部暴露参考关系的映射.
    reference_edges_by_pdb: dict[str, list[dict[str, Any]]] = defaultdict(list)
    # dict[str, list[dict]], held-out PDB 到全部内部关系的双端邻接映射.
    internal_edges_by_pdb: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        if edge["relation"] == "reference":
            reference_edges_by_pdb[str(edge["pdb_A"])].append(edge)
        else:
            internal_edges_by_pdb[str(edge["pdb_A"])].append(edge)
            internal_edges_by_pdb[str(edge["pdb_B"])].append(edge)

    # dict[str, list[str]], 独立记录质量, 资产, 序列和参考冗余的全部排除原因.
    exclusion_reasons_by_pdb: dict[str, list[str]] = {}
    # list[str], 通过四项统一前置条件, 尚待内部去冗余的 PDB.
    eligible_ids: list[str] = []
    for pdb_id in sorted(held_out_ids):
        record = base_by_pdb[pdb_id]
        # list[str], 当前 PDB 可同时包含多个前置排除原因.
        exclusion_reasons: list[str] = []
        if not bool(record["quality"]["passed"]):
            exclusion_reasons.append("quality_failed")
        if not bool(record["assets"]["passed"]):
            exclusion_reasons.append("asset_failed")
        if record["sequence"]["status"] != "ok":
            exclusion_reasons.append("sequence_failed")
        if any(bool(edge["redundant"]) for edge in reference_edges_by_pdb[pdb_id]):
            exclusion_reasons.append("reference_redundant")
        exclusion_reasons_by_pdb[pdb_id] = exclusion_reasons
        if not exclusion_reasons:
            eligible_ids.append(pdb_id)

    # list[tuple[str, str]], 当前 mode/threshold 下 redundant=True 的内部无向边.
    conflict_pairs = [
        (str(edge["pdb_A"]), str(edge["pdb_B"]))
        for edge in edges
        if edge["relation"] == "held_out_internal" and bool(edge["redundant"])
    ]
    # dict[str, dict], 每个统一资格 PDB 的固定种子贪心接受或拒绝状态.
    greedy_states = greedy_independent_set(eligible_ids, conflict_pairs, seed)
    # list[str] (N_full_test,), 完整贪心极大独立集; 任意两个成员之间没有当前冗余边.
    full_test_ids = [
        pdb_id for pdb_id, state in greedy_states.items() if bool(state["accepted"])
    ]
    # dict[str, int], full_test PDB 到贪心接受顺序中紧凑排名的映射.
    full_test_rank = {pdb_id: rank for rank, pdb_id in enumerate(full_test_ids)}
    # list[str] (N_test0,), 不应用 occurrence 数过滤的固定随机身份; N_test0=test_0_size.
    test_0_ids = sample_test_0(full_test_ids, test_0_size, seed)
    # dict[str, int], test_0 PDB 到随机抽取顺序的映射.
    test_0_rank = {pdb_id: rank for rank, pdb_id in enumerate(test_0_ids)}
    # list[str] (N_test1,), test_0 中 total occurrence 严格位于 `(1, 100)` 的子集.
    test_1_ids = [
        pdb_id
        for pdb_id in test_0_ids
        if bool(base_by_pdb[pdb_id]["ligands"]["strict_1_100_passed"])
    ]
    # dict[str, int], 继承 test_0 相对顺序后的 test_1 紧凑排名.
    test_1_rank = {pdb_id: rank for rank, pdb_id in enumerate(test_1_ids)}

    # list[dict] (N_held_out,), 最终统一身份证; 正式 N_held_out=2497.
    identities: list[dict[str, Any]] = []
    for pdb_id in sorted(held_out_ids):
        base_record = base_by_pdb[pdb_id]
        # list[dict], 当前 held-out PDB 的全部暴露参考关系.
        reference_edges = reference_edges_by_pdb[pdb_id]
        # list[dict], 当前 held-out PDB 的全部内部关系.
        internal_edges = internal_edges_by_pdb[pdb_id]
        # dict | None, 只有通过统一前置条件的 PDB 才进入贪心图.
        state = greedy_states.get(pdb_id)
        # str | None, 拒绝时最早接受的直接冗余邻居.
        rejected_by = None if state is None else state["rejected_by"]
        # dict | None, 当前 PDB 与 rejected_by 的四个 coverage 直接见证.
        rejection_edge = None
        if rejected_by is not None:
            # list[dict] (1,), 当前拒绝 PDB 对的 redundant 内部关系.
            matching_edges = [
                edge
                for edge in internal_edges
                if {str(edge["pdb_A"]), str(edge["pdb_B"])} == {pdb_id, rejected_by}
                and bool(edge["redundant"])
            ]
            rejection_edge = _strongest_edge(matching_edges, pdb_id)
        # dict, 当前参数下的参考/内部关系规模, 布尔值和最强直接见证.
        redundancy_summary = {
            "pdb_coverage_mode": mode,
            "pdb_coverage_threshold": threshold,
            "reference_edge_count": len(reference_edges),
            "reference_redundant_edge_count": sum(
                bool(edge["redundant"]) for edge in reference_edges
            ),
            "reference_redundant": any(bool(edge["redundant"]) for edge in reference_edges),
            "strongest_reference_edge": _strongest_edge(reference_edges, pdb_id),
            "internal_edge_count": len(internal_edges),
            "internal_redundant_edge_count": sum(
                bool(edge["redundant"]) for edge in internal_edges
            ),
            "strongest_internal_edge": _strongest_edge(internal_edges, pdb_id),
        }
        # dict, 当前 PDB 的前置资格, 贪心状态, 拒绝见证和三个测试视图成员身份.
        selection_summary = {
            "base_eligible": not exclusion_reasons_by_pdb[pdb_id],
            "exclusion_reasons": exclusion_reasons_by_pdb[pdb_id],
            "greedy_rank": None if state is None else state["greedy_rank"],
            "full_test": pdb_id in full_test_rank,
            "full_test_rank": full_test_rank.get(pdb_id),
            "rejected_by": rejected_by,
            "rejection_edge": rejection_edge,
            "test_0": pdb_id in test_0_rank,
            "test_0_rank": test_0_rank.get(pdb_id),
            "test_1": pdb_id in test_1_rank,
            "test_1_rank": test_1_rank.get(pdb_id),
        }
        # dict, 一个冻结 held-out PDB 的完整 schema v1 身份证.
        identity_record = {
            "schema": IDENTITY_SCHEMA,
            "schema_version": IDENTITY_SCHEMA_VERSION,
            "pdb_id": pdb_id,
            "emdb_ids": base_record["emdb_ids"],
            "first_map_release": base_record["first_map_release"],
            "quality": base_record["quality"],
            "assets": base_record["assets"],
            "ligands": base_record["ligands"],
            "sequence": base_record["sequence"],
            "redundancy": redundancy_summary,
            "selection": selection_summary,
        }
        identities.append(identity_record)

    _write_jsonl(output_root / "held_out_identity.jsonl", identities)
    # dict[str, object], 三个测试视图共享的 schema 版本, PDB coverage 参数和随机 entropy.
    common_view_fields = {
        "schema_version": IDENTITY_SCHEMA_VERSION,
        "pdb_coverage_mode": mode,
        "pdb_coverage_threshold": threshold,
        "seed": seed,
    }
    _write_json(
        output_root / "full_test.json",
        {
            **common_view_fields,
            "name": "full_test",
            "occurrence_filter": None,
            "pdb_ids": full_test_ids,
        },
    )
    _write_json(
        output_root / "test_0.json",
        {
            **common_view_fields,
            "name": "test_0",
            "occurrence_filter": None,
            "parent": "full_test",
            "pdb_ids": test_0_ids,
        },
    )
    _write_json(
        output_root / "test_1.json",
        {
            **common_view_fields,
            "name": "test_1",
            "occurrence_filter": "1 < total_count < 100",
            "parent": "test_0",
            "pdb_ids": test_1_ids,
        },
    )

    # Counter[str], 前置过滤原因可重叠计数, 不包含内部贪心拒绝.
    exclusion_counts = Counter(
        reason for reasons in exclusion_reasons_by_pdb.values() for reason in reasons
    )
    # dict, 冗余边, 前置资格和三个测试视图的最终规模.
    summary = {
        **edge_summary,
        "held_out_pdb_count": len(held_out_ids),
        "base_eligible_count": len(eligible_ids),
        "full_test_count": len(full_test_ids),
        "test_0_count": len(test_0_ids),
        "test_1_count": len(test_1_ids),
        "exclusion_reason_counts": dict(sorted(exclusion_counts.items())),
        "seed": seed,
    }
    stage2_root = output_root / "stage2"
    _write_json(stage2_root / "summary.json", summary)
    _write_text(stage2_root / "_COMPLETE", "")
    return summary
