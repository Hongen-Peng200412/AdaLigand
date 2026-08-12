"""按 PDB 分片，为五类正式配体准备 occurrence 级语言模型 SMILES。

CPU 数组任务先在全局 PDB 列表上分片，再由每个工作进程处理一个 PDB。正式产物
``prepared/{pdb_id}/prepared_smiles.jsonl`` 每行对应一个五类正式 occurrence；文件
存在表示该 PDB 的 CPU 准备已经完整写完，不表示其中每个 occurrence 都有 SMILES。

命令入口 ``main`` 先按 ``sample_scope`` 和 Slurm 数组参数选择 PDB，再让进程池调用
``prepare_one_pdb``。``--output-root/prepared/{pdb_id}/prepared_smiles.jsonl`` 是 JSONL，
每个对象的核心字段是 occurrence 身份、``kind``、``type_tag``、``smiles``、
``smiles_source`` 和 diagnostics。数组任务事实写入
``--output-root/prepared/reports/shard_{index}_of_{count}.json``；该文件是一个 JSON 对象，
顶层记录分片身份、PDB 状态、五类/other 数量、SMILES 数量、依赖版本和逐 PDB 结果。
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path

import numpy as np

from artifacts import FORMAL_TYPE_TAGS, PreparedLigand, write_prepared
from clc_assembly import read_clc_candidates
from ligand_preparation import prepare_ligand
from run_context import (
    dependency_versions,
    format_error,
    load_pdb_ids,
    select_shard,
    shard_report_path,
    utc_now,
    write_report,
)


# ================================================================================================


def prepare_one_pdb(
    data_root_text: str,
    output_root_text: str,
    pdb_id: str,
    overwrite: bool,
) -> dict[str, object]:
    """准备一个 PDB 的全部五类正式 occurrence，并返回该工作进程的事实。

    输入:
        data_root_text: 原始数据根目录字符串。子进程内重新构造 ``Path``，避免跨进程传递打开的文件。
        output_root_text: 语言模型产物根目录字符串。
        pdb_id: 当前进程处理的小写 PDB 标识。
        overwrite: False 且 prepared 文件存在时跳过；True 时撤掉旧完成文件并重算。

    读取:
        ``parse/{pdb_id}/occurrences.jsonl``: 当前 PDB 的全部 occurrence。
        ``parse/{pdb_id}/ligand_coords.npz``: BRANCHED 后备路径的 ``present_{candidate_id}`` 掩码；读取失败不阻止 CLC 主路径。
        ``ligand_objects/{safe_object_key}.npz``: CCD 主输入或 BRANCHED 后备模板；BRANCHED 读取失败不阻止 CLC 主路径。
        ``raw/rcsb_mmcif/{pdb_id}.cif``: pdbeccdutils 组装 CLC 使用的完整 mmCIF。

    返回字段:
        pdb_id: 当前 PDB 标识。
        status: ``completed``、``skipped_existing`` 或 ``failed``。
        elapsed_seconds: 当前 PDB 从进入函数到返回的秒数。
        occurrence_count: ``completed`` 时记录源文件中的全部 occurrence 数。
        formal_occurrence_count: ``completed`` 时记录写入 prepared 文件的五类正式配体数。
        other_occurrence_count: ``completed`` 时记录明确标为 ``other``、因而未写入的数量。
        with_smiles_count: ``completed`` 时记录最终有非空 SMILES 的正式配体数。
        without_smiles_count: ``completed`` 时记录最终没有 SMILES 的正式配体数。
        smiles_source_counts: ``completed`` 时按 ``smiles_source`` 统计记录数。
        error: ``failed`` 时记录 PDB 级读取、字段契约或最终写入异常。

    一个字段契约正确的正式 occurrence 如果化学处理失败，仍写出
    ``smiles_source="occurrence_error"``。源 JSON 本身无法提供合法身份字段时，无法构造
    可信的 occurrence 记录，因此该 PDB 返回 ``failed``。该状态只是运行事实，不是发布门控。
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
    if prepared_path.exists():
        # prepared_smiles.jsonl 是 PDB 级完成标志；显式覆盖时先撤掉旧标志。
        prepared_path.unlink()

    coordinates: np.lib.npyio.NpzFile | None = None
    try:
        if type(pdb_id) is not str or not pdb_id or pdb_id != pdb_id.lower():
            raise ValueError("pdb_id 必须是非空小写字符串")
        parse_root = data_root / "parse" / pdb_id

        occurrences: list[dict[str, object]] = []
        occurrence_path = parse_root / "occurrences.jsonl"
        with occurrence_path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                occurrence = json.loads(line)
                if not isinstance(occurrence, dict):
                    raise ValueError(
                        f"{occurrence_path}:{line_number} 必须是 JSON 对象"
                    )
                occurrences.append(occurrence)

        # type_tag 只允许五类正式标签或明确的 other。未知值不应被悄悄并入 other 计数。
        formal: list[dict[str, object]] = []
        other_occurrence_count = 0
        for occurrence_index, occurrence in enumerate(occurrences):
            if "type_tag" not in occurrence or type(occurrence["type_tag"]) is not str:
                raise TypeError(
                    f"occurrences[{occurrence_index}].type_tag 必须是字符串"
                )
            if occurrence["type_tag"] in FORMAL_TYPE_TAGS:
                formal.append(occurrence)
            elif occurrence["type_tag"] == "other":
                other_occurrence_count += 1
            else:
                raise ValueError(
                    f"occurrences[{occurrence_index}].type_tag 未知: "
                    f"{occurrence['type_tag']!r}"
                )

        # 一个 PDB 只调用一次 pdbeccdutils；其全部 BRANCHED occurrence 复用同一候选列表。
        has_branched = any(
            type(occurrence.get("kind")) is str
            and occurrence["kind"].strip() == "BRANCHED"
            for occurrence in formal
        )
        if has_branched:
            clc_candidates, clc_read_diagnostics = read_clc_candidates(
                data_root / "raw" / "rcsb_mmcif" / f"{pdb_id}.cif"
            )
            try:
                coordinates = np.load(
                    parse_root / "ligand_coords.npz",
                    allow_pickle=False,
                )
                coordinate_error = None
            except Exception as error:
                coordinate_error = format_error(error)
        else:
            clc_candidates = []
            clc_read_diagnostics = {
                "not_needed": True,
                "candidate_count": 0,
                "package_result_count": None,
                "error": None,
                "candidate_warnings": [],
                "candidate_errors": [],
                "package_charge_and_bond_order_are_not_treated_as_authoritative": True,
            }
            coordinate_error = None

        records: list[PreparedLigand] = []
        # 同一 PDB 内共享 object_key 的 occurrence 只读取一次 LigandObject NPZ。
        object_cache: dict[str, dict[str, np.ndarray]] = {}
        for occurrence_index, occurrence in enumerate(formal):
            # 这些字段同时用于成功记录与 occurrence_error，必须在进入化学处理前可靠取得。
            for field, expected_type in (
                ("candidate_id", int),
                ("object_key", str),
                ("kind", str),
                ("is_covalent", bool),
            ):
                if (
                    field not in occurrence
                    or type(occurrence[field]) is not expected_type
                ):
                    raise TypeError(
                        f"formal[{occurrence_index}].{field} 必须是 {expected_type.__name__}"
                    )
            candidate_id = occurrence["candidate_id"]
            object_key = occurrence["object_key"].strip()
            kind = occurrence["kind"].strip()
            if candidate_id < 0 or not object_key or not kind:
                raise ValueError(
                    f"formal[{occurrence_index}] 的 candidate_id、object_key 或 kind 非法"
                )

            try:
                ligand_object: dict[str, np.ndarray] = {}
                ligand_object_error = None
                if kind in {"CCD", "BRANCHED"}:
                    try:
                        if object_key not in object_cache:
                            # 该替换规则与 Stage C 的 LigandObject 文件名规则一致。
                            object_filename = re.sub(
                                r"[^A-Za-z0-9_.-]+", "_", object_key
                            )
                            object_path = (
                                data_root / "ligand_objects" / f"{object_filename}.npz"
                            )
                            with np.load(
                                object_path, allow_pickle=True
                            ) as ligand_archive:
                                object_cache[object_key] = {
                                    name: ligand_archive[name]
                                    for name in ligand_archive.files
                                }
                        ligand_object = object_cache[object_key]
                    except Exception as error:
                        if kind == "CCD":
                            raise
                        # CLC 使用完整 mmCIF，不依赖 LigandObject；空字典只让真正需要的 present 后备记录缺失事实。
                        ligand_object_error = format_error(error)

                present = None
                present_error = coordinate_error
                if kind == "BRANCHED" and coordinates is not None:
                    present_name = f"present_{candidate_id}"
                    if present_name in coordinates.files:
                        try:
                            # bool (N,)，N 是当前 LigandObject 模板原子数；True 表示该原子存在。
                            present = coordinates[present_name]
                        except Exception as error:
                            # 单个成员损坏不应遮蔽完全独立的 CLC 主路径；只有后备路径会引用该异常。
                            present_error = format_error(error)

                prepared = prepare_ligand(
                    pdb_id=pdb_id,
                    occurrence=occurrence,
                    ligand_object=ligand_object,
                    present=present,
                    clc_candidates=clc_candidates,
                    clc_read_diagnostics=clc_read_diagnostics,
                )
                if kind == "BRANCHED" and prepared.smiles_source == "present_graph":
                    fallback_input_diagnostics = {}
                    if ligand_object_error:
                        fallback_input_diagnostics["ligand_object_error"] = (
                            ligand_object_error
                        )
                    if present_error:
                        fallback_input_diagnostics["ligand_coords_error"] = (
                            present_error
                        )
                else:
                    fallback_input_diagnostics = {}
                if fallback_input_diagnostics:
                    prepared = replace(
                        prepared,
                        diagnostics={
                            **prepared.diagnostics,
                            **fallback_input_diagnostics,
                        },
                    )
                records.append(prepared)
            except Exception as error:
                records.append(
                    PreparedLigand(
                        pdb_id=pdb_id,
                        candidate_id=candidate_id,
                        object_key=object_key,
                        kind=kind,
                        type_tag=occurrence["type_tag"],
                        is_covalent=occurrence["is_covalent"],
                        smiles=None,
                        smiles_source="occurrence_error",
                        diagnostics={"error": format_error(error)},
                    )
                )

        records.sort(key=lambda record: record.candidate_id)
        write_prepared(prepared_path, records)
        source_counts = Counter(record.smiles_source for record in records)
        with_smiles_count = sum(record.smiles is not None for record in records)
        return {
            "pdb_id": pdb_id,
            "status": "completed",
            "occurrence_count": len(occurrences),
            "formal_occurrence_count": len(records),
            "other_occurrence_count": other_occurrence_count,
            "with_smiles_count": with_smiles_count,
            "without_smiles_count": len(records) - with_smiles_count,
            "smiles_source_counts": dict(sorted(source_counts.items())),
            "elapsed_seconds": time.perf_counter() - started,
        }
    except Exception as error:
        return {
            "pdb_id": pdb_id,
            "status": "failed",
            "error": format_error(error),
            "elapsed_seconds": time.perf_counter() - started,
        }
    finally:
        if coordinates is not None:
            coordinates.close()


def main() -> None:
    """解析 CPU 参数，执行当前 PDB 分片，并写一份不参与发布决策的运行报告。

    报告顶层字段:
        stage: 固定为 ``prepared``。
        started_at: 当前数组任务开始时的 UTC 时间。
        finished_at: 当前数组任务结束时的 UTC 时间。
        elapsed_seconds: 当前数组任务从开始到报告写入前的总秒数。
        sample_scope: 用户选择的 ``all_valid`` 或 ``all_existing``。
        all_pdb_count: 分片前全局 PDB 数。
        shard_index: 当前零基数组分片编号。
        num_shards: 本轮数组任务总片数。
        selected_pdb_count: 当前分片负责的 PDB 数。
        workers: 当前数组任务使用的进程数。
        overwrite: 是否重新计算已经存在完成文件的 PDB。
        status_counts: ``completed``、``skipped_existing``、``failed`` 的 PDB 数。
        formal_occurrence_count: 本次已完成 PDB 中五类正式 occurrence 的总数。
        with_smiles_count: 本次已完成 PDB 中得到非空 SMILES 的正式 occurrence 数。
        without_smiles_count: 本次已完成 PDB 中没有得到 SMILES 的正式 occurrence 数。
        other_occurrence_count: 本次已完成 PDB 中只计数而不准备 SMILES 的 other 数。
        dependencies: NumPy、RDKit、pdbeccdutils 和 gemmi 的已安装版本。
        pdb_results: 每个 PDB 的 ``prepare_one_pdb`` 返回对象，按 PDB 标识排序。

    ``load_pdb_ids`` 先建立全局列表，``select_shard`` 再按
    ``pdb_ids[shard_index::num_shards]`` 取片。每个子进程独占一个 PDB 的 prepared 文件。
    """

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
    args = parser.parse_args()
    if args.workers < 1:
        raise ValueError("workers 必须是正整数")

    started_at = utc_now()
    started = time.perf_counter()
    all_pdb_ids = load_pdb_ids(
        args.data_root,
        args.all_valid_path,
        args.sample_scope,
    )
    shard_pdb_ids = select_shard(all_pdb_ids, args.shard_index, args.num_shards)
    print(
        f"prepared 分片 {args.shard_index}/{args.num_shards}: "
        f"处理 {len(shard_pdb_ids)}/{len(all_pdb_ids)} 个 PDB",
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

    results.sort(key=lambda value: value["pdb_id"])
    status_counts = Counter(value["status"] for value in results)
    completed_results = [value for value in results if value["status"] == "completed"]
    report = {
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
            value["formal_occurrence_count"] for value in completed_results
        ),
        "with_smiles_count": sum(
            value["with_smiles_count"] for value in completed_results
        ),
        "without_smiles_count": sum(
            value["without_smiles_count"] for value in completed_results
        ),
        "other_occurrence_count": sum(
            value["other_occurrence_count"] for value in completed_results
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
    write_report(report_path, report)
    print(f"已写入分片报告: {report_path}", flush=True)


if __name__ == "__main__":
    main()
