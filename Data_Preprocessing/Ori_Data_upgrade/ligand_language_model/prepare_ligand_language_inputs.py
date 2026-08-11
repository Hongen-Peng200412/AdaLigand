"""按 PDB 分片准备 occurrence 级配体语言模型 SMILES。

一个 Slurm 数组任务只处理 ``pdb_ids[shard_index::num_shards]``。每个 PDB 的
全部正式配体 occurrence 写入一个 ``prepared/{pdb_id}/prepared_smiles.jsonl``；
该文件通过原子替换建立，因而“文件存在”可作为本阶段默认续跑完成标志。

化学校验结论只进入逐 occurrence 记录和分片报告。某一条记录没有模型输入不会
阻止同一 PDB 的其他记录落盘，也不会修改 ``all_valid.json`` 或 ``info.json``。
"""

from __future__ import annotations

import argparse
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from ligand_chemistry import (
    base_prepared_record,
    load_ligand_object,
    prepare_occurrence,
    read_clc_candidates,
)
from ligand_language_contracts import FORMAL_TYPE_TAGS
from ligand_language_common import (
    atomic_write_json,
    atomic_write_jsonl,
    clean_exception,
    dependency_versions,
    load_sample_ids,
    read_jsonl,
    select_shard,
    shard_report_path,
    utc_now,
)


def no_input_record(
    output_pdb_id: str,
    occurrence: dict[str, object],
    source: str,
    error: BaseException,
) -> dict[str, object]:
    """把单条 occurrence 异常转成不会伪造 SMILES 的正式结果记录。"""

    record = base_prepared_record(occurrence, output_pdb_id)
    record.update(
        {
            "preparation_source": source,
            "source_smiles": None,
            "assembled_isomeric_smiles": None,
            "model_input_smiles": None,
            "has_model_input": False,
            "chemistry": {},
            "preparation_audit": {},
            "preparation_errors": [clean_exception(error)],
        }
    )
    return record


def prepare_one_pdb(
    data_root_text: str,
    output_root_text: str,
    pdb_id: str,
    overwrite: bool,
) -> dict[str, object]:
    """准备一个 PDB 的全部正式 occurrence。

    返回值仅供当前数组任务汇总。单条 occurrence 失败会生成
    ``has_model_input=false`` 的记录；只有 PDB 级源文件无法读取或正式完成文件
    无法写入时，才把整个 PDB 标成 ``failed``。
    """

    started = time.perf_counter()
    data_root = Path(data_root_text)
    output_root = Path(output_root_text)
    prepared_path = output_root / "prepared" / pdb_id / "prepared_smiles.jsonl"
    if prepared_path.exists() and not overwrite:
        return {
            "pdb_id": pdb_id,
            "status": "skipped_existing",
            "elapsed_seconds": time.perf_counter() - started,
        }
    if prepared_path.exists() and overwrite:
        # 显式覆盖先撤销旧完成标志；新计算失败后，默认续跑不会把旧文件当成新结果。
        prepared_path.unlink()

    try:
        parse_root = data_root / "parse" / pdb_id
        occurrences = read_jsonl(parse_root / "occurrences.jsonl")
        formal_occurrences = [
            value for value in occurrences if value.get("type_tag") in FORMAL_TYPE_TAGS
        ]
        other_count = len(occurrences) - len(formal_occurrences)

        has_branched = any(
            value.get("kind") == "BRANCHED" for value in formal_occurrences
        )
        if has_branched:
            clc_candidates, pdb_clc_audit = read_clc_candidates(
                data_root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif"
            )
        else:
            clc_candidates = []
            pdb_clc_audit = {
                "clc_reader_not_needed": True,
                "clc_candidate_count": 0,
            }

        records: list[dict[str, object]] = []
        ligand_object_cache: dict[str, dict[str, np.ndarray]] = {}
        with np.load(
            parse_root / "ligand_coords.npz", allow_pickle=False
        ) as coordinate_archive:
            for occurrence in formal_occurrences:
                candidate_id = int(occurrence["candidate_id"])
                object_key = str(occurrence["object_key"])
                try:
                    if object_key not in ligand_object_cache:
                        ligand_object_cache[object_key] = load_ligand_object(
                            data_root,
                            object_key,
                        )
                    present = coordinate_archive[f"present_{candidate_id}"]
                    records.append(
                        prepare_occurrence(
                            pdb_id,
                            occurrence,
                            present,
                            ligand_object_cache[object_key],
                            clc_candidates,
                            pdb_clc_audit,
                        )
                    )
                except Exception as exc:
                    records.append(
                        no_input_record(
                            pdb_id,
                            occurrence,
                            "occurrence_exception",
                            exc,
                        )
                    )

        records.sort(key=lambda value: int(value["candidate_id"]))
        atomic_write_jsonl(prepared_path, records)
        source_counts = Counter(str(value["preparation_source"]) for value in records)
        type_counts = Counter(str(value["type_tag"]) for value in records)
        return {
            "pdb_id": pdb_id,
            "status": "completed",
            "occurrence_count": len(occurrences),
            "formal_occurrence_count": len(records),
            "other_occurrence_count": other_count,
            "with_model_input_count": sum(
                bool(value["has_model_input"]) for value in records
            ),
            "without_model_input_count": sum(
                not bool(value["has_model_input"]) for value in records
            ),
            "preparation_source_counts": dict(sorted(source_counts.items())),
            "type_tag_counts": dict(sorted(type_counts.items())),
            "elapsed_seconds": time.perf_counter() - started,
        }
    except Exception as exc:
        return {
            "pdb_id": pdb_id,
            "status": "failed",
            "error": clean_exception(exc),
            "elapsed_seconds": time.perf_counter() - started,
        }


def parse_args() -> argparse.Namespace:
    """解析正式 CPU 数组入口参数。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--all-valid-path", type=Path, required=True)
    parser.add_argument(
        "--sample-scope",
        choices=("all_valid", "all_existing"),
        required=True,
    )
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--num-shards", type=int, required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    """并行准备当前数组分片，并写入不承担发布决策的事实报告。"""

    args = parse_args()
    if args.workers < 1:
        raise ValueError("workers 必须为正整数")

    started_at = utc_now()
    started = time.perf_counter()
    all_pdb_ids = load_sample_ids(
        args.data_root, args.sample_scope, args.all_valid_path
    )
    shard_pdb_ids = select_shard(all_pdb_ids, args.shard_index, args.num_shards)
    print(
        f"prepared shard {args.shard_index}/{args.num_shards}: "
        f"selected {len(shard_pdb_ids)} of {len(all_pdb_ids)} PDBs",
        flush=True,
    )

    results: list[dict[str, object]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_pdb = {
            executor.submit(
                prepare_one_pdb,
                str(args.data_root),
                str(args.output_root),
                pdb_id,
                args.overwrite,
            ): pdb_id
            for pdb_id in shard_pdb_ids
        }
        for completed_count, future in enumerate(as_completed(future_to_pdb), start=1):
            result = future.result()
            results.append(result)
            print(
                f"[{completed_count}/{len(shard_pdb_ids)}] "
                f"{result['pdb_id']}: {result['status']}",
                flush=True,
            )

    results.sort(key=lambda value: str(value["pdb_id"]))
    status_counts = Counter(str(value["status"]) for value in results)
    report = {
        "schema_version": 1,
        "stage": "prepared",
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_seconds": time.perf_counter() - started,
        "sample_scope": args.sample_scope,
        "all_pdb_count": len(all_pdb_ids),
        "shard_index": args.shard_index,
        "num_shards": args.num_shards,
        "selected_pdb_count": len(shard_pdb_ids),
        "workers": args.workers,
        "overwrite": args.overwrite,
        "status_counts": dict(sorted(status_counts.items())),
        "formal_occurrence_count": sum(
            int(value.get("formal_occurrence_count", 0)) for value in results
        ),
        "with_model_input_count": sum(
            int(value.get("with_model_input_count", 0)) for value in results
        ),
        "without_model_input_count": sum(
            int(value.get("without_model_input_count", 0)) for value in results
        ),
        "other_occurrence_count": sum(
            int(value.get("other_occurrence_count", 0)) for value in results
        ),
        "dependencies": dependency_versions(
            ("numpy", "rdkit", "pdbeccdutils", "gemmi")
        ),
        "pdb_results": results,
    }
    report_path = shard_report_path(
        args.output_root / "prepared",
        args.shard_index,
        args.num_shards,
    )
    atomic_write_json(report_path, report)
    print(f"wrote shard report: {report_path}", flush=True)


if __name__ == "__main__":
    main()
