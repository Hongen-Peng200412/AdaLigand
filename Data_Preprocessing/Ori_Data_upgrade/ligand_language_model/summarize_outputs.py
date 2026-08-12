"""重新扫描一个阶段的逐 PDB 正式文件，并生成全局事实汇总。

汇总不拼接分片报告，而是按用户选择的样本范围重新读取每个 PDB 的
``prepared_smiles.jsonl`` 或 ``results.jsonl``。它不修改逐 PDB 产物，也不决定发布。

``main`` 是命令入口；``stage`` 决定扫描 prepared、molformer 或 smi_ted_289m，
``sample_scope`` 决定 PDB 名单，``--output-root`` 决定产物根。结果原子写入
``--output-root/{stage}/reports/final_summary.json``。该文件是一个 JSON 对象；公共顶层
字段是阶段、生成时间、样本范围、期望/已有 PDB 数、缺失 PDB 列表和依赖版本，阶段
专属字段再记录 occurrence 类别、准备来源或模型状态、向量有限性和最高频精确 SMILES。
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from artifacts import read_model_results, read_prepared
from run_context import dependency_versions, load_pdb_ids, utc_now, write_report


STAGES = ("prepared", "molformer", "smi_ted_289m")


# ================================================================================================


def main() -> None:
    """扫描一个阶段并写 ``{stage}/reports/final_summary.json``。

    三类报告共有字段:
        stage: ``prepared``、``molformer`` 或 ``smi_ted_289m``。
        generated_at: 生成报告的 UTC 时间。
        sample_scope: 用户选择的 ``all_valid`` 或 ``all_existing``。
        expected_pdb_count: 当前样本范围中的 PDB 总数。
        present_pdb_count: 存在且成功读取当前阶段正式文件的 PDB 数。
        missing_pdb_ids: 当前阶段正式文件不存在的 PDB 标识。
        dependencies: 运行汇总脚本的 NumPy 版本。

    prepared 额外字段:
        record_count: 已读取的五类正式 occurrence 数。
        type_tag_counts: 五类 ``type_tag`` 的 occurrence 数。
        smiles_source_counts: ``ccd``、``clc``、``present_graph``、``unsupported`` 和 ``occurrence_error`` 的记录数。
        with_smiles_count: 得到非空 CPU SMILES 的 occurrence 数。
        without_smiles_count: 没有得到 CPU SMILES 的 occurrence 数。
        distinct_exact_smiles_count: 不再次规范化的 prepared SMILES 字符串种数。
        most_common_exact_smiles: 最高频精确字符串、次数和并列字符串数；没有字符串时为 ``None``。

    两个模型阶段额外字段:
        record_count: 已读取的 occurrence 模型状态数。
        status_counts: ``encoded``、``model_failed`` 和 ``no_smiles`` 数量。
        type_tag_counts: 五类 ``type_tag`` 的 occurrence 数。
        encoded_finite_counts: encoded 记录按 ``all_finite``、``contains_nonfinite`` 或 ``unknown`` 分组的数量。
        encoded_output_missing_count: encoded 状态指向的 NPZ 当前不存在的数量。
        distinct_exact_model_smiles_count: 已确认 tokenizer 输入字符串的精确种数；``model_smiles=None`` 不计入。
        most_common_exact_model_smiles: 最高频已确认模型字符串、次数和并列字符串数；没有时为 ``None``。

    最高频字符串只进入报告，不参与任何 occurrence 的输入选择。并列时报告字典序最前
    的一个字符串，并用 ``tied_smiles_count`` 明确并列数。

    ``missing_pdb_ids`` 只表示正式文件不存在。已有文件一旦违反字段契约，读取会直接
    抛出异常；该次运行不会把非法文件伪装成缺失文件，也不会写新的
    ``final_summary.json``。
    """

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
    args = parser.parse_args()

    pdb_ids = load_pdb_ids(
        args.data_root,
        args.all_valid_path,
        args.sample_scope,
    )

    if args.stage == "prepared":
        missing_pdb_ids: list[str] = []
        prepared_records = []
        for pdb_id in pdb_ids:
            prepared_path = (
                args.output_root / "prepared" / pdb_id / "prepared_smiles.jsonl"
            )
            if prepared_path.is_file():
                prepared_records.extend(read_prepared(prepared_path, pdb_id))
            else:
                missing_pdb_ids.append(pdb_id)

        type_tag_counts = Counter(record.type_tag for record in prepared_records)
        smiles_source_counts = Counter(
            record.smiles_source for record in prepared_records
        )
        exact_smiles_counts = Counter(
            record.smiles for record in prepared_records if record.smiles is not None
        )
        if exact_smiles_counts:
            highest_count = max(exact_smiles_counts.values())
            tied_smiles = sorted(
                smiles
                for smiles, count in exact_smiles_counts.items()
                if count == highest_count
            )
            most_common_exact_smiles: dict[str, object] | None = {
                "smiles": tied_smiles[0],
                "count": highest_count,
                "tied_smiles_count": len(tied_smiles),
            }
        else:
            most_common_exact_smiles = None

        with_smiles_count = sum(
            record.smiles is not None for record in prepared_records
        )
        scanned: dict[str, object] = {
            "present_pdb_count": len(pdb_ids) - len(missing_pdb_ids),
            "missing_pdb_ids": missing_pdb_ids,
            "record_count": len(prepared_records),
            "type_tag_counts": dict(sorted(type_tag_counts.items())),
            "smiles_source_counts": dict(sorted(smiles_source_counts.items())),
            "with_smiles_count": with_smiles_count,
            "without_smiles_count": len(prepared_records) - with_smiles_count,
            "distinct_exact_smiles_count": len(exact_smiles_counts),
            "most_common_exact_smiles": most_common_exact_smiles,
        }

    else:
        missing_pdb_ids = []
        model_records = []
        for pdb_id in pdb_ids:
            result_path = args.output_root / args.stage / pdb_id / "results.jsonl"
            if result_path.is_file():
                model_records.extend(read_model_results(result_path, pdb_id))
            else:
                missing_pdb_ids.append(pdb_id)

        status_counts = Counter(record.status for record in model_records)
        type_tag_counts = Counter(record.type_tag for record in model_records)
        exact_model_smiles_counts = Counter(
            record.model_smiles
            for record in model_records
            if record.model_smiles is not None
        )
        if exact_model_smiles_counts:
            highest_count = max(exact_model_smiles_counts.values())
            tied_smiles = sorted(
                smiles
                for smiles, count in exact_model_smiles_counts.items()
                if count == highest_count
            )
            most_common_exact_model_smiles: dict[str, object] | None = {
                "smiles": tied_smiles[0],
                "count": highest_count,
                "tied_smiles_count": len(tied_smiles),
            }
        else:
            most_common_exact_model_smiles = None

        # results.jsonl 已保存有限性事实；汇总不为统计再次加载 768 维 NPZ。
        encoded_finite_counts: Counter[str] = Counter()
        encoded_output_missing_count = 0
        for record in model_records:
            if record.status != "encoded":
                continue
            all_finite = record.diagnostics.get("all_finite")
            if all_finite is True:
                encoded_finite_counts["all_finite"] += 1
            elif all_finite is False:
                encoded_finite_counts["contains_nonfinite"] += 1
            else:
                encoded_finite_counts["unknown"] += 1
            if record.output_file is None or not Path(record.output_file).is_file():
                encoded_output_missing_count += 1

        scanned = {
            "present_pdb_count": len(pdb_ids) - len(missing_pdb_ids),
            "missing_pdb_ids": missing_pdb_ids,
            "record_count": len(model_records),
            "status_counts": dict(sorted(status_counts.items())),
            "type_tag_counts": dict(sorted(type_tag_counts.items())),
            "encoded_finite_counts": dict(sorted(encoded_finite_counts.items())),
            "encoded_output_missing_count": encoded_output_missing_count,
            "distinct_exact_model_smiles_count": len(exact_model_smiles_counts),
            "most_common_exact_model_smiles": most_common_exact_model_smiles,
        }

    summary = {
        "stage": args.stage,
        "generated_at": utc_now(),
        "sample_scope": args.sample_scope,
        "expected_pdb_count": len(pdb_ids),
        "dependencies": dependency_versions(("numpy",)),
        **scanned,
    }
    output_path = args.output_root / args.stage / "reports" / "final_summary.json"
    write_report(output_path, summary)
    print(f"已写入全局汇总: {output_path}", flush=True)


if __name__ == "__main__":
    main()
