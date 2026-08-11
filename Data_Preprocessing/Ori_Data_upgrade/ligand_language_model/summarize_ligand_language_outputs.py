"""扫描实际 occurrence 产物并生成一个阶段的全局事实汇总。

本入口不会合并分片报告中的局部赢家，而是重新读取所选 PDB 的正式
``prepared_smiles.jsonl`` 或 ``results.jsonl``。因此“出现次数最多的精确
SMILES”来自全局逐 occurrence 记录；它只进入报告，不参与任何输入选择。

缺失 PDB、失败状态、非有限向量和结果文件记录不一致都只作为事实计数。脚本不
建立发布门控，不修改 ``all_valid.json``、``info.json`` 或任何模型向量。
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from ligand_language_common import (
    atomic_write_json,
    dependency_versions,
    load_sample_ids,
    read_jsonl,
    utc_now,
)


STAGES = ("prepared", "molformer", "smi_ted_289m")


def most_common_exact_smiles(counter: Counter[str]) -> dict[str, object] | None:
    """用字典序打破并列，仅简要报告全局最高频精确字符串。"""

    if not counter:
        return None
    highest_count = max(counter.values())
    tied = sorted(value for value, count in counter.items() if count == highest_count)
    return {
        "smiles": tied[0],
        "count": highest_count,
        "tied_smiles_count": len(tied),
        "tie_break": "lexicographically_first",
    }


def scan_prepared(
    output_root: Path,
    pdb_ids: list[str],
) -> dict[str, object]:
    """直接扫描准备阶段正式 JSONL，并汇总化学来源和输入覆盖率。

    返回已有/缺失 PDB、记录总数、type/source/input 计数、不同精确 SMILES 数和
    全局最高频精确 SMILES；缺失清单只进入报告，不修改样本范围。
    """

    type_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    input_counts: Counter[str] = Counter()
    smiles_counts: Counter[str] = Counter()
    missing_pdb_ids: list[str] = []
    record_count = 0
    for pdb_id in pdb_ids:
        path = output_root / "prepared" / pdb_id / "prepared_smiles.jsonl"
        if not path.exists():
            missing_pdb_ids.append(pdb_id)
            continue
        records = read_jsonl(path)
        record_count += len(records)
        for record in records:
            type_counts[str(record.get("type_tag", ""))] += 1
            source_counts[str(record.get("preparation_source", ""))] += 1
            has_input = bool(record.get("has_model_input"))
            input_counts[
                "with_model_input" if has_input else "without_model_input"
            ] += 1
            smiles = record.get("model_input_smiles")
            if isinstance(smiles, str) and smiles:
                smiles_counts[smiles] += 1
    return {
        "present_pdb_count": len(pdb_ids) - len(missing_pdb_ids),
        "missing_pdb_count": len(missing_pdb_ids),
        "missing_pdb_ids": missing_pdb_ids,
        "record_count": record_count,
        "type_tag_counts": dict(sorted(type_counts.items())),
        "preparation_source_counts": dict(sorted(source_counts.items())),
        "model_input_counts": dict(sorted(input_counts.items())),
        "distinct_exact_model_input_smiles_count": len(smiles_counts),
        "most_common_exact_model_input_smiles": most_common_exact_smiles(smiles_counts),
    }


def scan_model(
    output_root: Path,
    stage: str,
    pdb_ids: list[str],
) -> dict[str, object]:
    """直接扫描一个模型的逐 PDB 结果清单，并核对已编码 NPZ 是否仍存在。

    返回已有/缺失 PDB、记录总数、status/type/有限性计数、encoded 记录指向的缺失
    NPZ 数、不同精确实际输入数和最高频字符串；所有不一致都只作为事实计数。
    """

    status_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    finite_counts: Counter[str] = Counter()
    smiles_counts: Counter[str] = Counter()
    missing_pdb_ids: list[str] = []
    encoded_output_missing_count = 0
    record_count = 0
    for pdb_id in pdb_ids:
        path = output_root / stage / pdb_id / "results.jsonl"
        if not path.exists():
            missing_pdb_ids.append(pdb_id)
            continue
        records = read_jsonl(path)
        record_count += len(records)
        for record in records:
            status = str(record.get("status", ""))
            status_counts[status] += 1
            type_counts[str(record.get("type_tag", ""))] += 1
            if status == "encoded":
                finite_counts[
                    (
                        "all_finite"
                        if bool(record.get("all_finite"))
                        else "contains_nonfinite"
                    )
                ] += 1
                output_path = record.get("output_path")
                if not isinstance(output_path, str) or not Path(output_path).is_file():
                    encoded_output_missing_count += 1
            smiles = record.get("actual_model_input_smiles")
            if isinstance(smiles, str) and smiles:
                smiles_counts[smiles] += 1
    return {
        "present_pdb_count": len(pdb_ids) - len(missing_pdb_ids),
        "missing_pdb_count": len(missing_pdb_ids),
        "missing_pdb_ids": missing_pdb_ids,
        "record_count": record_count,
        "status_counts": dict(sorted(status_counts.items())),
        "type_tag_counts": dict(sorted(type_counts.items())),
        "encoded_finite_counts": dict(sorted(finite_counts.items())),
        "encoded_output_missing_count": encoded_output_missing_count,
        "distinct_exact_actual_model_input_smiles_count": len(smiles_counts),
        "most_common_exact_actual_model_input_smiles": most_common_exact_smiles(
            smiles_counts
        ),
    }


def parse_args() -> argparse.Namespace:
    """解析显式最终汇总入口参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--all-valid-path", type=Path, required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument(
        "--sample-scope",
        choices=("all_valid", "all_existing"),
        required=True,
    )
    return parser.parse_args()


def main() -> None:
    """从正式逐 PDB 文件重算并原子写入一个阶段的全局汇总。"""

    args = parse_args()
    pdb_ids = load_sample_ids(args.data_root, args.sample_scope, args.all_valid_path)
    if args.stage == "prepared":
        scanned = scan_prepared(args.output_root, pdb_ids)
    else:
        scanned = scan_model(args.output_root, args.stage, pdb_ids)
    summary = {
        "schema_version": 1,
        "stage": args.stage,
        "generated_at": utc_now(),
        "sample_scope": args.sample_scope,
        "expected_pdb_count": len(pdb_ids),
        "dependencies": dependency_versions(("numpy",)),
        **scanned,
    }
    output_path = args.output_root / args.stage / "reports" / "final_summary.json"
    atomic_write_json(output_path, summary)
    print(f"wrote final summary: {output_path}", flush=True)


if __name__ == "__main__":
    main()
