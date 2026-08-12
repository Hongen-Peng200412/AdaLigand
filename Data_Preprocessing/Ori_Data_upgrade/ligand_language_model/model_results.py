"""在全局 GPU batch 前后整理 occurrence 输入、分子向量和逐 PDB 结果。

本模块把各 PDB 的 prepared 记录展平成一个跨 PDB 列表，使模型按全局 batch 编码；
随后把每个 occurrence 的状态归还所属 PDB。模型专属的分词和前向仍留在各自入口中。

调用者传入 ``output_root`` 和 ``model_stage``。先由 ``load_model_work`` 读取
``output_root/prepared/{pdb_id}/prepared_smiles.jsonl``，模型入口再用
``record_embedding_result`` 写 ``output_root/{model_stage}/{pdb_id}/candidate_*.npz``，
最后 ``finish_model_work`` 核对集合并写 ``results.jsonl``。NPZ 的核心数组是 occurrence
身份、模型名、两种 SMILES 和 ``float32 (768,)`` embedding；JSONL 每个对象的核心字段
是 ``pdb_id``、``candidate_id``、``status``、输出路径、异常和 diagnostics。
``write_model_report`` 另写 ``output_root/{model_stage}/reports/shard_*.json``，顶层记录
分片身份、PDB 数、输入数、batch_size、状态计数、依赖和 CUDA 事实。样本范围和数组
分片由调用者在进入本模块前决定。
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from artifacts import (
    FORMAL_TYPE_TAGS,
    ModelResult,
    PreparedLigand,
    read_prepared,
    write_embedding,
    write_model_results,
)
from run_context import format_error, shard_report_path, utc_now, write_report


@dataclass(frozen=True)
class ModelCandidate:
    """一个拥有非空 prepared SMILES、等待当前模型编码的 occurrence。

    属性:
        pdb_id: prepared 文件所属的小写 PDB 标识，决定结果写回哪个逐 PDB 目录。
        prepared: 当前 occurrence 的完整 CPU 记录；本类中 ``prepared.smiles`` 保证非空。
    """

    pdb_id: str
    prepared: PreparedLigand


@dataclass
class ModelWork:
    """一个 GPU 分片尚未收口的全局候选和逐 PDB 状态。

    属性:
        candidates: 跨 PDB 的全局模型输入，按 ``(pdb_id, candidate_id)`` 排序。相邻元素可以来自不同 PDB。
        results_by_pdb: 每个未完成 PDB 的状态列表。起初只含 ``no_smiles``，模型运行时再追加其他状态。
        expected_candidate_ids: 每个未完成 PDB 的全部 prepared candidate_id，用于收口时检查遗漏和重复。
        active_pdb_ids: prepared 可读且需要本次处理的 PDB，保持当前分片顺序。
        skipped_pdb_ids: 已有 ``results.jsonl`` 且 ``overwrite=False`` 的 PDB。
        source_failures: prepared 不可读或不符合正式五类契约的 PDB 事实。
    """

    candidates: list[ModelCandidate]
    results_by_pdb: dict[str, list[ModelResult]]
    expected_candidate_ids: dict[str, frozenset[int]]
    active_pdb_ids: list[str]
    skipped_pdb_ids: list[str]
    source_failures: list[dict[str, object]]


def is_fatal_cuda_error(error: BaseException) -> bool:
    """判断异常是否意味着当前 CUDA 上下文不宜继续逐 occurrence 重试。

    此判断只控制同一进程是否还能安全调用模型，不评价样本质量，也不决定数据发布。
    """

    message = format_error(error).lower()
    markers = (
        "cuda out of memory",
        "cuda error",
        "cublas",
        "cudnn",
        "device-side assert",
        "illegal memory access",
        "driver version",
    )
    return any(marker in message for marker in markers)


# ================================================================================================


def load_model_work(
    output_root: Path,
    model_stage: str,
    shard_pdb_ids: Iterable[str],
    overwrite: bool,
) -> ModelWork:
    """读取当前分片的 prepared 文件，并把有 SMILES 的 occurrence 跨 PDB 展平。

    ``results.jsonl`` 是一个 PDB 在当前模型阶段的完成标志。``overwrite=False`` 时直接
    跳过已有文件；显式覆盖或中断续跑时，先删除该 PDB 的旧完成标志和全部
    ``candidate_*.npz``，再从 prepared 记录完整重算。单独存在 candidate NPZ 不代表完成。

    没有 SMILES 的正式 occurrence 不进入模型候选，而是立即得到 ``no_smiles`` 状态。
    prepared 文件不可读、身份不属于该 PDB或 ``type_tag`` 不是五类正式标签时，该 PDB
    进入 ``source_failures``，不会伪造 occurrence 结果。
    """

    candidates: list[ModelCandidate] = []
    results_by_pdb: dict[str, list[ModelResult]] = {}
    expected_candidate_ids: dict[str, frozenset[int]] = {}
    active_pdb_ids: list[str] = []
    skipped_pdb_ids: list[str] = []
    source_failures: list[dict[str, object]] = []

    for pdb_id in shard_pdb_ids:
        result_path = output_root / model_stage / pdb_id / "results.jsonl"
        if result_path.exists() and not overwrite:
            skipped_pdb_ids.append(pdb_id)
            continue
        if result_path.exists():
            result_path.unlink()
        # 当前 PDB 一旦进入重算，就先清掉上次覆盖或中断遗留的向量，避免文件名枚举读到旧表示。
        for stale_embedding_path in sorted(result_path.parent.glob("candidate_*.npz")):
            stale_embedding_path.unlink()

        prepared_path = output_root / "prepared" / pdb_id / "prepared_smiles.jsonl"
        try:
            prepared_records = read_prepared(prepared_path, pdb_id)
            # read_prepared 已校验字段；这里再次固定模型消费者只接受五类正式标签，防止未来改动让 other 或未知标签进入训练特征。
            invalid_type_tags = sorted(
                {
                    prepared.type_tag
                    for prepared in prepared_records
                    if prepared.type_tag not in FORMAL_TYPE_TAGS
                }
            )
            if invalid_type_tags:
                raise ValueError(f"prepared 含非正式 type_tag: {invalid_type_tags}")
        except Exception as error:
            source_failures.append(
                {
                    "pdb_id": pdb_id,
                    "status": "prepared_unavailable",
                    "error": format_error(error),
                }
            )
            continue

        initial_results: list[ModelResult] = []
        for prepared in prepared_records:
            if prepared.smiles is not None:
                candidates.append(ModelCandidate(pdb_id=pdb_id, prepared=prepared))
            else:
                initial_results.append(
                    ModelResult(
                        pdb_id=pdb_id,
                        candidate_id=prepared.candidate_id,
                        type_tag=prepared.type_tag,
                        status="no_smiles",
                        prepared_smiles=None,
                        model_smiles=None,
                        output_file=None,
                        error=None,
                        diagnostics={},
                    )
                )

        active_pdb_ids.append(pdb_id)
        expected_candidate_ids[pdb_id] = frozenset(
            prepared.candidate_id for prepared in prepared_records
        )
        results_by_pdb[pdb_id] = initial_results

    # 排序只稳定 occurrence 与模型输出的对应关系；后续切 batch 时不以 PDB 为边界。
    candidates.sort(key=lambda value: (value.pdb_id, value.prepared.candidate_id))
    return ModelWork(
        candidates=candidates,
        results_by_pdb=results_by_pdb,
        expected_candidate_ids=expected_candidate_ids,
        active_pdb_ids=active_pdb_ids,
        skipped_pdb_ids=skipped_pdb_ids,
        source_failures=source_failures,
    )


def record_embedding_result(
    *,
    work: ModelWork,
    output_root: Path,
    model_stage: str,
    model_name: str,
    candidate: ModelCandidate,
    model_smiles: str | None,
    embedding: np.ndarray,
    diagnostics: dict[str, object],
) -> None:
    """写一个分子向量，并把 ``encoded`` 或写入失败状态归还所属 PDB。

    ``model_smiles`` 表示已确认送入 tokenizer 的字符串。MoLFormer 与 prepared 字符串
    相同；SMI-TED 若官方规范化失败但公开 ``encode`` 仍返回向量，则该值为 ``None``。
    ``write_embedding`` 保留 NaN 和正负无穷并返回计数，因此非有限向量仍是 encoded，
    不是写入失败。只有形状、数据类型或文件写入出错才追加 ``model_failed``。
    """

    prepared = candidate.prepared
    output_path = (
        output_root
        / model_stage
        / candidate.pdb_id
        / f"candidate_{prepared.candidate_id}.npz"
    )
    try:
        finite_diagnostics = write_embedding(
            path=output_path,
            prepared=prepared,
            model_name=model_name,
            model_smiles=model_smiles,
            embedding=embedding,
        )
    except Exception as error:
        work.results_by_pdb[candidate.pdb_id].append(
            ModelResult(
                pdb_id=candidate.pdb_id,
                candidate_id=prepared.candidate_id,
                type_tag=prepared.type_tag,
                status="model_failed",
                prepared_smiles=prepared.smiles,
                model_smiles=model_smiles,
                output_file=None,
                error=format_error(error),
                diagnostics=diagnostics,
            )
        )
        return

    work.results_by_pdb[candidate.pdb_id].append(
        ModelResult(
            pdb_id=candidate.pdb_id,
            candidate_id=prepared.candidate_id,
            type_tag=prepared.type_tag,
            status="encoded",
            prepared_smiles=prepared.smiles,
            model_smiles=model_smiles,
            output_file=str(output_path),
            error=None,
            diagnostics={**diagnostics, **finite_diagnostics},
        )
    )


def finish_model_work(
    output_root: Path,
    model_stage: str,
    work: ModelWork,
) -> list[dict[str, object]]:
    """核对每个 prepared 身份恰好有一个状态，再写逐 PDB ``results.jsonl``。

    对每个本次实际处理的 PDB，结果中的 candidate_id 必须与 prepared 文件中的
    candidate_id 集合完全相同，
    并且每个编号只出现一次。该核对只防止模型输出漏写、重复或串入其他 occurrence；
    不评价 SMILES、向量质量或是否发布。

    返回列表每项含 ``pdb_id``、固定的 ``status="completed"``、``result_count`` 和
    ``status_counts``。列表顺序与 ``work.active_pdb_ids`` 相同。
    """

    summaries: list[dict[str, object]] = []
    for pdb_id in work.active_pdb_ids:
        records = work.results_by_pdb[pdb_id]
        records.sort(key=lambda value: value.candidate_id)
        expected_ids = work.expected_candidate_ids[pdb_id]
        actual_id_counts = Counter(record.candidate_id for record in records)
        actual_ids = frozenset(actual_id_counts)
        duplicate_ids = sorted(
            candidate_id
            for candidate_id, count in actual_id_counts.items()
            if count != 1
        )
        if actual_ids != expected_ids or duplicate_ids:
            raise RuntimeError(
                f"{pdb_id}: 模型结果身份不完整；"
                f"缺失={sorted(expected_ids - actual_ids)}，"
                f"重复={duplicate_ids}，"
                f"额外={sorted(actual_ids - expected_ids)}"
            )

        result_dir = output_root / model_stage / pdb_id
        expected_embedding_names: set[str] = set()
        for record in records:
            if record.status != "encoded":
                continue
            expected_path = result_dir / f"candidate_{record.candidate_id}.npz"
            if record.output_file != str(expected_path):
                raise RuntimeError(
                    f"{pdb_id}: encoded output_file 与正式路径不一致: "
                    f"{record.output_file!r} != {str(expected_path)!r}"
                )
            expected_embedding_names.add(expected_path.name)

        # results.jsonl 写出后就是完成标志，因此写标志前必须确认目录里没有缺失或过期向量。
        actual_embedding_names = {
            path.name for path in result_dir.glob("candidate_*.npz")
        }
        if actual_embedding_names != expected_embedding_names:
            raise RuntimeError(
                f"{pdb_id}: 向量文件集合与 encoded 状态不一致；"
                f"缺失={sorted(expected_embedding_names - actual_embedding_names)}，"
                f"过期={sorted(actual_embedding_names - expected_embedding_names)}"
            )

        write_model_results(result_dir / "results.jsonl", records)
        status_counts = Counter(record.status for record in records)
        summaries.append(
            {
                "pdb_id": pdb_id,
                "status": "completed",
                "result_count": len(records),
                "status_counts": dict(sorted(status_counts.items())),
            }
        )
    return summaries


def write_model_report(
    *,
    output_root: Path,
    model_stage: str,
    model_name: str,
    work: ModelWork,
    pdb_summaries: list[dict[str, object]],
    sample_scope: str,
    all_pdb_count: int,
    selected_pdb_count: int,
    shard_index: int,
    num_shards: int,
    batch_size: int,
    started_at: str,
    started_monotonic: float,
    dependencies: dict[str, str | None],
    cuda: dict[str, object],
) -> Path:
    """写一个 GPU 分片的计数、速度、依赖和硬件事实。

    报告顶层字段:
        stage: 模型产物子目录名。
        model_name: 当前入口使用的官方模型名。
        started_at: 当前数组任务开始时的 UTC 时间。
        finished_at: 当前数组任务结束时的 UTC 时间。
        elapsed_seconds: 当前数组任务从开始到报告写入前的总秒数。
        sample_scope: 用户选择的 ``all_valid`` 或 ``all_existing``。
        all_pdb_count: 分片前的全局 PDB 数。
        shard_index: 当前零基数组分片编号。
        num_shards: 本轮数组任务总片数。
        selected_pdb_count: 当前分片负责的 PDB 数。
        processed_pdb_count: prepared 可读并写出 results 的 PDB 数。
        prepared_unavailable_pdb_count: prepared 不可读或契约非法的 PDB 数。
        skipped_existing_pdb_count: 已有完成文件而跳过的 PDB 数。
        skipped_existing_pdb_ids: 已有完成文件而跳过的 PDB 标识列表。
        global_model_input_count: 当前分片所有非空 prepared SMILES 的 occurrence 数；这些输入跨 PDB 组成 batch。
        batch_size: 调用者选择写入报告的正整数；MoLFormer 保存全局切块上限，SMI-TED 保存首次全局调用的有效参数，无输入时保存配置值。
        status_counts: 本次实际处理的 PDB 中 ``encoded``、``model_failed``、``no_smiles`` 的 occurrence 数。
        encoded_vectors_per_second: encoded 数除以分片总耗时；耗时为零时为 ``None``。
        dependencies: 当前 Python 进程中的指定分发包版本。
        cuda: 当前 Python 进程可见的 CUDA 设备与运行库事实。
        pdb_results: 已完成 PDB 的状态计数，加 prepared 不可用 PDB 的异常事实。

    报告只保存可追溯事实，不产生发布结论。
    """

    records = [
        record
        for pdb_id in work.active_pdb_ids
        for record in work.results_by_pdb[pdb_id]
    ]
    status_counts = Counter(record.status for record in records)
    elapsed_seconds = time.perf_counter() - started_monotonic
    report = {
        "stage": model_stage,
        "model_name": model_name,
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_seconds": elapsed_seconds,
        "sample_scope": sample_scope,
        "all_pdb_count": all_pdb_count,
        "shard_index": shard_index,
        "num_shards": num_shards,
        "selected_pdb_count": selected_pdb_count,
        "processed_pdb_count": len(work.active_pdb_ids),
        "prepared_unavailable_pdb_count": len(work.source_failures),
        "skipped_existing_pdb_count": len(work.skipped_pdb_ids),
        "skipped_existing_pdb_ids": work.skipped_pdb_ids,
        "global_model_input_count": len(work.candidates),
        "batch_size": batch_size,
        "status_counts": dict(sorted(status_counts.items())),
        "encoded_vectors_per_second": (
            status_counts.get("encoded", 0) / elapsed_seconds
            if elapsed_seconds > 0
            else None
        ),
        "dependencies": dependencies,
        "cuda": cuda,
        "pdb_results": sorted(
            [*pdb_summaries, *work.source_failures],
            key=lambda value: value["pdb_id"],
        ),
    }
    path = shard_report_path(output_root / model_stage, shard_index, num_shards)
    write_report(path, report)
    return path
