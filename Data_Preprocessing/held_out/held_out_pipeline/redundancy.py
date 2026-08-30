"""运行 MMseqs2 并把 entity 命中转换为 PDB 双向 coverage.

主要入口是 :func:`run_mmseqs_shard` 与 :func:`build_redundancy_edges`. 前者只运行一个 FASTA query 分片; 后者读取全部真实 alignment, 展开 entity 到 label asym chain 的边, 并对每个 PDB 对分别求最大 chain 数, 最大 A 侧残基数和最大 B 侧残基数的一对一匹配.

本模块不读取质量, 资产或配体计数, 也不选择测试集.

全部输入 FASTA 与输出 TSV/JSONL 都位于调用方 `output_root` 下. MMseqs2 TSV 一行对应一条 entity alignment; qualifying hit JSONL 一行对应一个定向 entity 对; redundancy edge JSONL 一行对应一个 PDB 对. :func:`calculate_pdb_edge` 定义单条 PDB 边的完整字段.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix


# float, protein chain 高重复的真实 alignment identity 包含下界.
PROTEIN_IDENTITY_THRESHOLD = 0.30
# float, RNA/DNA/hybrid chain 高重复的真实 alignment identity 包含下界.
NUCLEIC_IDENTITY_THRESHOLD = 0.80
# float, query 和 target 各自必须达到的 alignment coverage 包含下界.
CHAIN_COVERAGE_THRESHOLD = 0.80
# str, MMseqs2 TSV 固定列序; fident, qcov 和 tcov 都是 `[0, 1]` 比例.
MMSEQS_FORMAT = "query,target,fident,qcov,tcov,qlen,tlen,alnlen,evalue"


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


def parse_mmseqs_rows(
    path: Path,
    sequence_kind: Literal["protein", "nucleic"],
) -> Iterator[dict[str, Any]]:
    """读取一个 MMseqs2 TSV, 并再次应用 identity 与双向 coverage 包含边界.

    输入列顺序固定为 `query, target, fident, qcov, tcov, qlen, tlen, alnlen, evalue`. `fident` 使用 alignment length 归一化; `qcov` 和 `tcov` 都必须至少为 0.80. 函数逐行 yield 命中, 避免在合并阶段同时保留全部原始 TSV.

    Yield 字段:
        - `query`, `target`, `sequence_kind`: str, 两侧 entity FASTA identity 和 protein/nucleic 类别.
        - `identity`, `query_coverage`, `target_coverage`: float `[0, 1]`, 真实 identity 和双向全长覆盖率.
        - `query_length`, `target_length`, `alignment_length`: int, 两侧全长与 alignment 列数.
        - `evalue`: float, MMseqs2 alignment E-value.
    """

    # float, 当前 protein 或 nucleic TSV 使用的真实 identity 包含下界.
    identity_threshold = (
        PROTEIN_IDENTITY_THRESHOLD
        if sequence_kind == "protein"
        else NUCLEIC_IDENTITY_THRESHOLD
    )
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            # list[str] (9,), 当前 alignment 的固定 TSV 字段.
            columns = text.split("\t")
            if len(columns) != 9:
                raise ValueError(f"{path}:{line_number} 应有 9 列, 实际 {len(columns)} 列.")
            # float, identical aligned residues / alignment columns, 使用 `--seq-id-mode 0`.
            identity = float(columns[2])
            # float, alignment 覆盖 query 沉积全长的比例.
            query_coverage = float(columns[3])
            # float, alignment 覆盖 target 沉积全长的比例.
            target_coverage = float(columns[4])
            if (
                identity < identity_threshold
                or query_coverage < CHAIN_COVERAGE_THRESHOLD
                or target_coverage < CHAIN_COVERAGE_THRESHOLD
            ):
                continue
            yield {
                "query": columns[0].upper(),
                "target": columns[1].upper(),
                "sequence_kind": sequence_kind,
                "identity": identity,
                "query_coverage": query_coverage,
                "target_coverage": target_coverage,
                "query_length": int(columns[5]),
                "target_length": int(columns[6]),
                "alignment_length": int(columns[7]),
                "evalue": float(columns[8]),
            }


def classify_pdb_redundancy(
    chain_A: float,
    chain_B: float,
    residue_A: float,
    residue_B: float,
    mode: Literal["or", "and"],
    threshold: float,
) -> dict[str, bool]:
    """按 chain 与 residue 两级 coverage 组合 PDB 冗余判定.

    `chain_pass` 使用 A/B 两个方向的最大 chain coverage, `residue_pass` 使用 A/B 两个方向的最大 residue coverage. `or` 或 `and` 只组合这两个级别, 不改变方向 coverage. 四个输入和 threshold 都是 `[0, 1]` 比例, 比较使用包含边界.
    """

    if mode not in {"or", "and"}:
        raise ValueError(f"未知 PDB coverage mode: {mode}")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"PDB coverage threshold 必须位于 [0, 1]: {threshold}")
    # bool, 任一 PDB 方向的 chain 数覆盖达到当前 PDB 阈值.
    chain_pass = max(chain_A, chain_B) >= threshold
    # bool, 任一 PDB 方向的残基覆盖达到当前 PDB 阈值.
    residue_pass = max(residue_A, residue_B) >= threshold
    # bool, 用户可切换的 chain/residue 两级聚合结果; 默认 mode=or.
    redundant = chain_pass or residue_pass if mode == "or" else chain_pass and residue_pass
    return {
        "chain_pass": chain_pass,
        "residue_pass": residue_pass,
        "redundant": redundant,
    }


def _maximum_matching(
    chains_A: list[dict[str, Any]],
    chains_B: list[dict[str, Any]],
    evidence_by_entity_pair: dict[tuple[str, str], dict[str, Any]],
    objective: Literal["chain", "residue_A", "residue_B"],
) -> list[dict[str, Any]]:
    """在 entity 容量图上求与 chain 二分图等价的最大权一对一匹配.

    同一 entity 的 chain 具有相同序列和长度, 一条 entity 命中等价于两侧 chain copies 的完全二分图. 每个 entity 的 chain 数作为整数容量, 每单位流量代表一对 chain. 三种单位权重分别是 1, A 侧 chain 长度和 B 侧 chain 长度. 返回值仍展开为不复用 chain 的直接见证, 但不物化 `C_A * C_B` 条候选边.
    """

    if not chains_A or not chains_B or not evidence_by_entity_pair:
        return []

    # dict[str, list[dict]], A/B 两侧 entity identity 到可互换 chain copies 的映射.
    chains_by_entity_A: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chains_by_entity_B: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chain in chains_A:
        chains_by_entity_A[str(chain["entity_id"])].append(chain)
    for chain in chains_B:
        chains_by_entity_B[str(chain["entity_id"])].append(chain)
    for chain_group in (*chains_by_entity_A.values(), *chains_by_entity_B.values()):
        chain_group.sort(key=lambda chain: str(chain["chain_id"]))

    # list[tuple], 同时存在两侧 entity 和真实高重复命中的容量图边.
    entity_edges = [
        (entity_pair, evidence)
        for entity_pair, evidence in sorted(evidence_by_entity_pair.items())
        if entity_pair[0] in chains_by_entity_A and entity_pair[1] in chains_by_entity_B
    ]
    if not entity_edges:
        return []
    # list[str], 容量约束矩阵 A/B 两侧的稳定 entity 行顺序.
    entity_ids_A = sorted(chains_by_entity_A)
    entity_ids_B = sorted(chains_by_entity_B)
    # dict[str, int], entity identity 到容量约束矩阵行号的映射.
    row_by_entity_A = {entity_id: index for index, entity_id in enumerate(entity_ids_A)}
    row_by_entity_B = {
        entity_id: len(entity_ids_A) + index for index, entity_id in enumerate(entity_ids_B)
    }
    # list[int], 每个 entity edge 变量在稀疏约束矩阵中出现的两个行列坐标.
    constraint_rows: list[int] = []
    constraint_columns: list[int] = []
    for edge_index, ((entity_A, entity_B), _evidence) in enumerate(entity_edges):
        constraint_rows.extend((row_by_entity_A[entity_A], row_by_entity_B[entity_B]))
        constraint_columns.extend((edge_index, edge_index))
    # csr_matrix float64 (N_entity_A + N_entity_B, N_edge), 每列在两侧各消耗一个容量.
    constraint_matrix = coo_matrix(
        (
            np.ones(len(constraint_rows), dtype=np.float64),
            (constraint_rows, constraint_columns),
        ),
        shape=(len(entity_ids_A) + len(entity_ids_B), len(entity_edges)),
    ).tocsr()
    # ndarray float64 (N_entity_A + N_entity_B,), 每个 entity 可使用的 chain copy 数.
    entity_capacities = np.asarray(
        [len(chains_by_entity_A[entity_id]) for entity_id in entity_ids_A]
        + [len(chains_by_entity_B[entity_id]) for entity_id in entity_ids_B],
        dtype=np.float64,
    )
    # ndarray float64 (N_edge,), 三种目标下每匹配一对 chain 的正权重.
    objective_weights = np.asarray(
        [
            1.0
            if objective == "chain"
            else float(evidence["length_A"])
            if objective == "residue_A"
            else float(evidence["length_B"])
            for _entity_pair, evidence in entity_edges
        ],
        dtype=np.float64,
    )
    # ndarray float64 (N_edge,), 单条 entity edge 的最大整数流量.
    upper_bounds = np.asarray(
        [
            min(len(chains_by_entity_A[entity_A]), len(chains_by_entity_B[entity_B]))
            for (entity_A, entity_B), _evidence in entity_edges
        ],
        dtype=np.float64,
    )
    # OptimizeResult, entity 容量图上的最大权整数 b-matching; SciPy milp 以最小化为约定.
    optimization = milp(
        c=-objective_weights,
        integrality=np.ones(len(entity_edges), dtype=np.int32),
        bounds=Bounds(np.zeros(len(entity_edges), dtype=np.float64), upper_bounds),
        constraints=LinearConstraint(
            constraint_matrix,
            np.zeros_like(entity_capacities),
            entity_capacities,
        ),
    )
    if not optimization.success or optimization.x is None:
        raise RuntimeError(f"entity 容量匹配求解失败: {optimization.message}")
    # ndarray int64 (N_edge,), 每条 entity edge 实际承载的 chain 匹配数.
    flow_by_edge = np.rint(optimization.x).astype(np.int64)
    # Counter[str], 构造见证时每个 entity 已经消费的稳定 chain copy 数.
    used_chain_count_A: Counter[str] = Counter()
    used_chain_count_B: Counter[str] = Counter()
    # list[dict] (M,), M 条不复用 label_asym chain 的直接匹配见证.
    matching: list[dict[str, Any]] = []
    for ((entity_A, entity_B), evidence), flow_count in zip(
        entity_edges, flow_by_edge.tolist()
    ):
        for _ in range(flow_count):
            # dict, 当前 entity edge 下一条尚未使用的 A/B chain copy.
            chain_A = chains_by_entity_A[entity_A][used_chain_count_A[entity_A]]
            chain_B = chains_by_entity_B[entity_B][used_chain_count_B[entity_B]]
            used_chain_count_A[entity_A] += 1
            used_chain_count_B[entity_B] += 1
            matching.append(
                {
                    **evidence,
                    "chain_A": str(chain_A["chain_id"]),
                    "chain_B": str(chain_B["chain_id"]),
                }
            )
    return sorted(matching, key=lambda item: (str(item["chain_A"]), str(item["chain_B"])))


def calculate_pdb_edge(
    relation: Literal["reference", "held_out_internal"],
    pdb_A: str,
    pdb_B: str,
    chains_A: list[dict[str, Any]],
    chains_B: list[dict[str, Any]],
    evidence_by_entity_pair: dict[tuple[str, str], dict[str, Any]],
    mode: Literal["or", "and"],
    threshold: float,
) -> dict[str, Any]:
    """计算一个 PDB 对的四个 coverage, 三个最优匹配和当前冗余布尔值.

    输入参数:
        - relation: str, `reference` 或 `held_out_internal`.
        - pdb_A, pdb_B: str, 已固定方向的两侧 PDB identity.
        - chains_A, chains_B: list[dict], 两侧全部 comparable chain instance, 字段含 `chain_id`, `entity_id`, `length`.
        - evidence_by_entity_pair: dict[tuple[str, str], dict], 高重复 entity 边及 identity, 双向 coverage, 两侧长度.
        - mode, threshold: str 与 float, chain/residue 两级组合方式和 `[0, 1]` 包含边界.

    返回字段:
        - `relation`, `pdb_A`, `pdb_B`: str, 关系和固定方向身份.
        - `comparable_chain_count_A/B`, `comparable_residue_count_A/B`: int, 四个 coverage 的分母.
        - `chain_A/B`, `residue_A/B`: float, 最大 chain 数和两个残基目标得到的双向 coverage.
        - `chain_matching`, `residue_A_matching`, `residue_B_matching`: list[dict], 三个目标各自不复用 chain 的直接见证.
        - 每条 matching 见证含 A/B chain, entity, sequence identity 与长度, `sequence_kind`, `identity`, `coverage_A/B`.
        - `chain_pass`, `residue_pass`, `redundant`: bool, 当前 mode/threshold 下的两级和最终判定.

    chain 分母是每侧全部 comparable chain instance 数; residue 分母是这些 chain 的沉积全长序列长度之和. 三个匹配分别求解, 不能把某一个 matching 同时用于三个统计目标.
    """

    # list[dict], 使匹配 chain 对数量最大的见证集合.
    chain_matching = _maximum_matching(
        chains_A, chains_B, evidence_by_entity_pair, "chain"
    )
    # list[dict], 使已覆盖 A 侧 chain 全长残基数最大的见证集合.
    residue_A_matching = _maximum_matching(
        chains_A, chains_B, evidence_by_entity_pair, "residue_A"
    )
    # list[dict], 使已覆盖 B 侧 chain 全长残基数最大的见证集合.
    residue_B_matching = _maximum_matching(
        chains_A, chains_B, evidence_by_entity_pair, "residue_B"
    )
    # int, A 侧全部 comparable chain instance 的沉积全长残基分母.
    total_residues_A = sum(int(chain["length"]) for chain in chains_A)
    # int, B 侧全部 comparable chain instance 的沉积全长残基分母.
    total_residues_B = sum(int(chain["length"]) for chain in chains_B)
    # float, 最大 cardinality 匹配数 / A 侧 comparable chain 数.
    chain_A_coverage = len(chain_matching) / len(chains_A) if chains_A else 0.0
    # float, 同一最大 cardinality 匹配数 / B 侧 comparable chain 数.
    chain_B_coverage = len(chain_matching) / len(chains_B) if chains_B else 0.0
    # float, A 侧最大权匹配残基数 / A 侧 comparable 残基总数.
    residue_A_coverage = (
        sum(int(match["length_A"]) for match in residue_A_matching) / total_residues_A
        if total_residues_A
        else 0.0
    )
    # float, B 侧最大权匹配残基数 / B 侧 comparable 残基总数.
    residue_B_coverage = (
        sum(int(match["length_B"]) for match in residue_B_matching) / total_residues_B
        if total_residues_B
        else 0.0
    )
    # dict[str, bool], 当前 mode 和 threshold 下的 chain/residue 两级判断.
    decision = classify_pdb_redundancy(
        chain_A_coverage,
        chain_B_coverage,
        residue_A_coverage,
        residue_B_coverage,
        mode,
        threshold,
    )
    return {
        "relation": relation,
        "pdb_A": pdb_A,
        "pdb_B": pdb_B,
        "comparable_chain_count_A": len(chains_A),
        "comparable_chain_count_B": len(chains_B),
        "comparable_residue_count_A": total_residues_A,
        "comparable_residue_count_B": total_residues_B,
        "chain_A": chain_A_coverage,
        "chain_B": chain_B_coverage,
        "residue_A": residue_A_coverage,
        "residue_B": residue_B_coverage,
        "chain_matching": chain_matching,
        "residue_A_matching": residue_A_matching,
        "residue_B_matching": residue_B_matching,
        "pdb_coverage_mode": mode,
        "pdb_coverage_threshold": threshold,
        **decision,
    }


def _build_chain_tables(
    entities: Iterable[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """建立 sequence_id 到 entity 以及 PDB 到可比 chain instance 的两个索引.

    每个 `label_asym_id` 是一条独立 chain instance; `comparable=False` 的短链和 other 不进入第二个索引.
    """

    # dict[str, dict], 大写 `<PDB_ID>_<entity_id>` 到完整目录 entity 的映射.
    entity_by_sequence_id: dict[str, dict[str, Any]] = {}
    # dict[str, list[dict]], PDB 到 comparable label_asym chain instance 的映射.
    chains_by_pdb: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entity in entities:
        # str, MMseqs2 query/target header 使用的大写 entity identity.
        sequence_id = str(entity["sequence_id"]).upper()
        entity_by_sequence_id[sequence_id] = entity
        if not bool(entity["comparable"]):
            continue
        for chain_id in entity["label_asym_ids"]:
            # 每个多 chain entity 在 coverage 分母中展开成独立 chain instance.
            chains_by_pdb[str(entity["pdb_id"])].append(
                {
                    "chain_id": str(chain_id),
                    "entity_id": str(entity["entity_id"]),
                    "sequence_id": sequence_id,
                    "length": int(entity["length"]),
                    "sequence_class": str(entity["sequence_class"]),
                }
            )
    for pdb_id in chains_by_pdb:
        chains_by_pdb[pdb_id].sort(key=lambda chain: str(chain["chain_id"]))
    return entity_by_sequence_id, dict(chains_by_pdb)


def _orient_hit(
    hit: dict[str, Any],
    entity_by_sequence_id: dict[str, dict[str, Any]],
    held_out_ids: set[str],
    reference_ids: set[str],
) -> tuple[tuple[str, str, str], dict[str, Any]] | None:
    """把 query/target entity hit 定向为 reference 或字典序 held-out 内部 PDB 对.

    reference 边固定让 held-out query 位于 A; 内部边按 PDB identity 排序. 发生 A/B 交换时 entity, 长度和 query/target coverage 同步交换.
    """

    # dict, 当前 alignment query 的完整 entity 目录记录.
    query_entity = entity_by_sequence_id[hit["query"]]
    # dict, 当前 alignment target 的完整 entity 目录记录.
    target_entity = entity_by_sequence_id[hit["target"]]
    # str, query entity 所属的小写 PDB identity; query FASTA 应只含 held-out.
    query_pdb = str(query_entity["pdb_id"])
    # str, target entity 所属的小写 PDB identity; target 可为参考或 held-out.
    target_pdb = str(target_entity["pdb_id"])
    if query_pdb == target_pdb or query_pdb not in held_out_ids:
        return None
    if target_pdb in reference_ids:
        # str, held-out 对已暴露 train/validation/calibration 的冗余关系.
        relation = "reference"
        # str, reference 关系固定 A=held-out, B=暴露参考.
        pdb_A, pdb_B = query_pdb, target_pdb
        # dict, A/B 定向后的 entity 记录.
        entity_A, entity_B = query_entity, target_entity
        # float, 定向后 alignment 覆盖 A/B entity 全长的比例.
        coverage_A = float(hit["query_coverage"])
        coverage_B = float(hit["target_coverage"])
    elif target_pdb in held_out_ids:
        # str, 两个日期留出 PDB 之间的内部冲突关系.
        relation = "held_out_internal"
        # str, 内部关系按 PDB identity 字典序固定 A/B, 与 query 方向无关.
        pdb_A, pdb_B = sorted((query_pdb, target_pdb))
        if query_pdb == pdb_A:
            entity_A, entity_B = query_entity, target_entity
            coverage_A = float(hit["query_coverage"])
            coverage_B = float(hit["target_coverage"])
        else:
            entity_A, entity_B = target_entity, query_entity
            coverage_A = float(hit["target_coverage"])
            coverage_B = float(hit["query_coverage"])
    else:
        return None
    # dict, 与固定 PDB A/B 方向一致的 entity 命中及双向 coverage.
    oriented = {
        "relation": relation,
        "pdb_A": pdb_A,
        "pdb_B": pdb_B,
        "entity_A": str(entity_A["entity_id"]),
        "entity_B": str(entity_B["entity_id"]),
        "sequence_id_A": str(entity_A["sequence_id"]),
        "sequence_id_B": str(entity_B["sequence_id"]),
        "label_asym_ids_A": list(entity_A["label_asym_ids"]),
        "label_asym_ids_B": list(entity_B["label_asym_ids"]),
        "length_A": int(entity_A["length"]),
        "length_B": int(entity_B["length"]),
        "sequence_kind": hit["sequence_kind"],
        "identity": float(hit["identity"]),
        "coverage_A": coverage_A,
        "coverage_B": coverage_B,
        "alignment_length": int(hit["alignment_length"]),
        "evalue": float(hit["evalue"]),
    }
    return (relation, pdb_A, pdb_B), oriented


# ================================================================================================


def run_mmseqs_shard(
    mmseqs_binary: Path,
    output_root: Path,
    shard_index: int,
    threads: int,
) -> dict[str, Any]:
    """对一个 held-out query 分片依次运行 protein 和 nucleic MMseqs2 easy-search.

    两类命令都使用真实 identity, alignment length 归一化, query 和 target 双向 0.80 coverage. protein identity 下限为 0.30, nucleic 下限为 0.80. 结果和命令身份分别写到 `stage2/mmseqs/<kind>_<shard>.tsv` 与 shard summary.
    """

    if not (output_root / "stage1" / "_COMPLETE").is_file():
        raise FileNotFoundError("stage1 尚未完成, 不能运行 MMseqs2.")
    # Path, stage1 finalize 生成的 query/target FASTA 目录.
    fasta_root = output_root / "fasta" / "mmseqs"
    # Path, 当前 12 个数组分片的正式 MMseqs2 TSV 与命令摘要目录.
    result_root = output_root / "stage2" / "mmseqs"
    # Path, 每个 sequence kind 和 shard 独占的 MMseqs2 临时数据库目录.
    temporary_root = output_root / "stage2" / "mmseqs_tmp"
    result_root.mkdir(parents=True, exist_ok=True)
    temporary_root.mkdir(parents=True, exist_ok=True)
    # list[dict] (2,), protein 和 nucleic 命令, 状态及结果路径.
    command_records: list[dict[str, Any]] = []
    for sequence_kind, search_type, identity_threshold in (
        ("protein", 1, PROTEIN_IDENTITY_THRESHOLD),
        ("nucleic", 3, NUCLEIC_IDENTITY_THRESHOLD),
    ):
        # Path, 当前数组元素负责的 held-out entity FASTA.
        query_path = fasta_root / f"{sequence_kind}_query_{shard_index:03d}.fasta"
        # Path, 全部参考和 held-out comparable entity FASTA.
        target_path = fasta_root / f"{sequence_kind}_target.fasta"
        # Path, 当前 sequence kind 的真实 alignment TSV.
        result_path = result_root / f"{sequence_kind}_{shard_index:03d}.tsv"
        # Path, 当前命令独占的 MMseqs2 数据库与索引临时目录.
        temporary_path = temporary_root / f"{sequence_kind}_{shard_index:03d}"
        # list[str], 真实 identity, 双向 coverage 和固定输出列的完整 easy-search 命令.
        command = [
            str(mmseqs_binary),
            "easy-search",
            str(query_path),
            str(target_path),
            str(result_path),
            str(temporary_path),
            "--search-type",
            str(search_type),
            "--min-seq-id",
            str(identity_threshold),
            "-c",
            str(CHAIN_COVERAGE_THRESHOLD),
            "--cov-mode",
            "0",
            "--alignment-mode",
            "3",
            "--seq-id-mode",
            "0",
            "-s",
            "7.5",
            "-e",
            "1000000",
            "--max-seqs",
            "1000000",
            "--threads",
            str(threads),
            "--format-output",
            MMSEQS_FORMAT,
        ]
        if query_path.stat().st_size == 0:
            _write_text(result_path, "")
            status = "empty_query"
        else:
            subprocess.run(command, check=True)
            status = "completed"
        command_records.append(
            {
                "sequence_kind": sequence_kind,
                "status": status,
                "command": command,
                "result": str(result_path),
            }
        )
    # str, 实际执行二进制报告的 MMseqs2 版本, 用于服务器验收.
    version = subprocess.run(
        [str(mmseqs_binary), "version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # dict, 当前 query 分片的线程数, 二进制版本和两类命令执行记录.
    summary = {
        "shard_index": shard_index,
        "threads": threads,
        "mmseqs_version": version,
        "commands": command_records,
    }
    _write_json(result_root / f"summary_{shard_index:03d}.json", summary)
    return summary


def build_redundancy_edges(
    output_root: Path,
    train_pdb_path: Path,
    validation_pdb_path: Path,
    calibration_pdb_path: Path,
    held_out_pdb_path: Path,
    alignment_shard_count: int,
    mode: Literal["or", "and"],
    threshold: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """合并 MMseqs2 命中并构建 reference 与 held-out internal PDB 冗余边.

    输入参数:
        - output_root: Path, stage1 序列目录和 stage2 MMseqs2 TSV 的共享产物根.
        - train_pdb_path, validation_pdb_path, calibration_pdb_path: Path, 暴露参考 PDB JSON 列表.
        - held_out_pdb_path: Path, 冻结 held-out PDB JSON 列表.
        - alignment_shard_count: int, 必须读取的 protein/nucleic TSV 分片数.
        - mode, threshold: str 与 float, PDB chain/residue 聚合方式和包含边界.

    返回值:
        - edges: list[dict], 按 relation 与 PDB A/B 排序的 :func:`calculate_pdb_edge` 结果.
        - summary: dict, 原始 alignment, 定向 entity hit, PDB edge, redundant edge 数及 relation/mode/threshold.

    落盘产物:
        - `qualifying_entity_hits.jsonl`: 每行含定向 PDB/entity identity, label_asym 列表, 两侧长度, 类别, identity, 双向 coverage, alignment 长度和 E-value.
        - `redundancy_edges.jsonl`: 每行一个完整 PDB edge, 字段由 :func:`calculate_pdb_edge` 定义.

    原始 TSV 按行处理; 同一 entity 对的双向或重复 alignment 只保留 identity 较高, 再取最小双向 coverage 较高的一条, 精确并列时保留固定输入顺序中的首条. entity hit 以 chain copy 数作为容量求解, 只在 matching 结果中展开直接 chain 见证.
    """

    # list[dict] (N_entity,), stage1 发布的完整 polymer entity 目录.
    entities = _read_jsonl(output_root / "sequence_catalog.jsonl")
    # 两个索引分别解析 alignment header 和建立 PDB coverage 分母.
    entity_by_sequence_id, chains_by_pdb = _build_chain_tables(entities)
    # set[str], 2,497 个日期留出 PDB identity.
    held_out_ids = {
        str(pdb_id).strip().lower()
        for pdb_id in json.loads(held_out_pdb_path.read_text(encoding="utf-8"))
    }
    # set[str], train/validation/calibration 合计 14,017 个暴露参考 PDB.
    reference_ids: set[str] = set()
    for path in (train_pdb_path, validation_pdb_path, calibration_pdb_path):
        reference_ids.update(
            str(pdb_id).strip().lower()
            for pdb_id in json.loads(path.read_text(encoding="utf-8"))
        )

    # Path, 12 个数组分片的 protein/nucleic alignment TSV 目录.
    result_root = output_root / "stage2" / "mmseqs"
    # int, 通过真实 identity 和双向 0.80 coverage 的原始 alignment 数.
    raw_hit_count = 0
    # dict[tuple, dict], 固定 A/B 方向后每个 entity 对保留的最佳 alignment.
    oriented_hits_by_entity_pair: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for shard_index in range(alignment_shard_count):
        # tuple[tuple[Path, str], ...], 当前分片的 protein 与 nucleic TSV 及类别.
        result_paths = (
            (result_root / f"protein_{shard_index:03d}.tsv", "protein"),
            (result_root / f"nucleic_{shard_index:03d}.tsv", "nucleic"),
        )
        for result_path, sequence_kind in result_paths:
            for hit in parse_mmseqs_rows(result_path, sequence_kind):
                raw_hit_count += 1
                # tuple | None, 只保留 held-out->reference 或 held-out->held-out 的非自身命中.
                oriented_result = _orient_hit(
                    hit, entity_by_sequence_id, held_out_ids, reference_ids
                )
                if oriented_result is None:
                    continue
                pair_key, oriented_hit = oriented_result
                # tuple[str, ...], relation, PDB A/B 和 entity A/B 的去重主键.
                entity_pair_key = (
                    *pair_key,
                    str(oriented_hit["entity_A"]),
                    str(oriented_hit["entity_B"]),
                )
                # dict | None, 同一 entity 对先前方向或重复 alignment 的当前最佳见证.
                previous_hit = oriented_hits_by_entity_pair.get(entity_pair_key)
                # tuple[float, float], 先按 identity, 再按较小的双向 coverage 选见证.
                hit_score = (
                    float(oriented_hit["identity"]),
                    min(
                        float(oriented_hit["coverage_A"]),
                        float(oriented_hit["coverage_B"]),
                    ),
                )
                # tuple[float, float], 未出现时使用低于合法比例的哨兵值.
                previous_score = (
                    (-1.0, -1.0)
                    if previous_hit is None
                    else (
                        float(previous_hit["identity"]),
                        min(
                            float(previous_hit["coverage_A"]),
                            float(previous_hit["coverage_B"]),
                        ),
                    )
                )
                if hit_score > previous_score:
                    oriented_hits_by_entity_pair[entity_pair_key] = oriented_hit

    # list[dict], 去重且稳定排序的高重复 entity 对.
    oriented_hits = sorted(
        oriented_hits_by_entity_pair.values(),
        key=lambda hit: (
            str(hit["relation"]),
            str(hit["pdb_A"]),
            str(hit["pdb_B"]),
            str(hit["entity_A"]),
            str(hit["entity_B"]),
        ),
    )
    _write_jsonl(output_root / "qualifying_entity_hits.jsonl", oriented_hits)

    # dict[PDB pair, dict[entity pair, evidence]], 以 chain copy 数为容量的 entity 二分图.
    evidence_by_pdb_pair: dict[
        tuple[str, str, str], dict[tuple[str, str], dict[str, Any]]
    ] = defaultdict(dict)
    for hit in oriented_hits:
        # tuple[str, str, str], relation 和固定 A/B 方向的 PDB 对主键.
        pdb_pair_key = (str(hit["relation"]), str(hit["pdb_A"]), str(hit["pdb_B"]))
        # tuple[str, str], 当前 PDB 对内唯一的 A/B entity edge identity.
        entity_pair = (str(hit["entity_A"]), str(hit["entity_B"]))
        # dict, entity edge 的 alignment 见证; chain copies 在求解后才按容量展开.
        evidence_by_pdb_pair[pdb_pair_key][entity_pair] = {
            "entity_A": entity_pair[0],
            "entity_B": entity_pair[1],
            "sequence_id_A": str(hit["sequence_id_A"]),
            "sequence_id_B": str(hit["sequence_id_B"]),
            "length_A": int(hit["length_A"]),
            "length_B": int(hit["length_B"]),
            "sequence_kind": str(hit["sequence_kind"]),
            "identity": float(hit["identity"]),
            "coverage_A": float(hit["coverage_A"]),
            "coverage_B": float(hit["coverage_B"]),
        }

    # list[dict], 至少含一条高重复 chain 边的完整 PDB 对关系.
    edges: list[dict[str, Any]] = []
    for relation, pdb_A, pdb_B in sorted(evidence_by_pdb_pair):
        edges.append(
            calculate_pdb_edge(
                relation,
                pdb_A,
                pdb_B,
                chains_by_pdb.get(pdb_A, []),
                chains_by_pdb.get(pdb_B, []),
                evidence_by_pdb_pair[(relation, pdb_A, pdb_B)],
                mode,
                threshold,
            )
        )
    _write_jsonl(output_root / "redundancy_edges.jsonl", edges)
    # dict, alignment, entity hit, PDB edge 的规模和当前 PDB 判定参数.
    summary = {
        "raw_qualifying_alignment_count": raw_hit_count,
        "oriented_entity_hit_count": len(oriented_hits),
        "pdb_edge_count": len(edges),
        "redundant_pdb_edge_count": sum(bool(edge["redundant"]) for edge in edges),
        "relation_counts": dict(sorted(Counter(str(edge["relation"]) for edge in edges).items())),
        "mode": mode,
        "threshold": threshold,
    }
    return edges, summary
