"""共享两套配体语言模型的 occurrence 读取、结果落盘和分片报告逻辑。

模型入口先选定当前 Slurm 数组任务负责的 PDB，再把这些 PDB 尚未完成的全部
occurrence 展平成一个全局列表。模型因此能够跨 PDB 组成大 batch；推理完成后，
本模块再按 ``pdb_id`` 分发回各自目录。

``results.jsonl`` 是一个 PDB 在某模型阶段的完成标志。单个 candidate NPZ 不是
完成标志：若任务中断后只留下 NPZ，续跑仍会重做整个 PDB，并在最后原子写入
``results.jsonl``。本模块不删除孤立文件，也不据此修改数据目录中的清单。
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from ligand_language_contracts import validate_prepared_records
from ligand_language_common import (
    atomic_save_npz,
    atomic_write_json,
    atomic_write_jsonl,
    clean_exception,
    read_jsonl,
    shard_report_path,
    utc_now,
)


@dataclass(frozen=True)
class CandidateInput:
    """一个准备进入语言模型的 occurrence 及其原始准备记录。

    ``pdb_id`` 与 ``candidate_id`` 决定逐 PDB 输出路径；``prepared_record`` 是
    ``prepared_smiles.jsonl`` 的完整对象。``smiles`` 属性只在
    ``has_model_input=true`` 时读取非空 ``model_input_smiles``。
    """

    pdb_id: str
    candidate_id: int
    prepared_record: dict[str, object]

    @property
    def smiles(self) -> str:
        """返回 CPU 准备阶段提供的非空模型输入 SMILES。"""

        return str(self.prepared_record["model_input_smiles"])


@dataclass
class ModelWork:
    """当前 GPU 数组任务的全局候选列表和逐 PDB 结果缓冲区。

    ``candidates`` 跨 ``processed_pdb_ids`` 展平；``results_by_pdb`` 接收模型结果；
    ``skipped_pdb_ids`` 已有完成文件；``prepared_record_counts`` 用于最终一一对应；
    ``source_failures`` 保存 prepared 文件缺失或不可读的 PDB，不阻止其他 PDB。
    """

    candidates: list[CandidateInput]
    results_by_pdb: dict[str, list[dict[str, object]]]
    processed_pdb_ids: list[str]
    skipped_pdb_ids: list[str]
    prepared_record_counts: dict[str, int]
    source_failures: list[dict[str, object]]


def base_model_result(
    model_name: str,
    prepared_record: dict[str, object],
    output_pdb_id: str,
) -> dict[str, object]:
    """构造模型结果公共字段。

    返回模型名、目录 PDB、prepared PDB 及一致性、candidate/object/kind/type/covalent
    身份、准备来源和 CPU 准备 SMILES。status、模型实际输入、诊断、输出与异常由
    ``append_failed_result``、``append_embedding_result`` 或 no-input 分支补充。
    """

    prepared_pdb_id = str(prepared_record.get("pdb_id", "")).lower()
    return {
        "schema_version": 1,
        "model_name": model_name,
        "pdb_id": output_pdb_id,
        "source_prepared_pdb_id": prepared_pdb_id,
        "pdb_id_matches_prepared_record": output_pdb_id == prepared_pdb_id,
        "candidate_id": int(prepared_record["candidate_id"]),
        "object_key": str(prepared_record["object_key"]),
        "kind": str(prepared_record.get("kind", "")),
        "type_tag": str(prepared_record.get("type_tag", "")),
        "is_covalent": bool(prepared_record.get("is_covalent", False)),
        "preparation_source": str(prepared_record.get("preparation_source", "")),
        "prepared_model_input_smiles": prepared_record.get("model_input_smiles"),
    }


def load_model_work(
    output_root: Path,
    model_stage: str,
    model_name: str,
    shard_pdb_ids: Iterable[str],
    overwrite: bool,
) -> ModelWork:
    """读取当前分片中尚未完成的 PDB，并跨 PDB 展平可编码 occurrence。

    没有模型输入的 occurrence 直接生成 ``no_model_input`` 结果，但仍等待同一
    PDB 的其他 occurrence 推理结束后一起写入正式 ``results.jsonl``。返回的
    ``ModelWork.candidates`` 是跨 PDB 全局列表；每个 PDB 只有在 prepared 文件全部
    解析成功后才加入 ``processed_pdb_ids``，否则进入 ``source_failures``。
    """

    candidates: list[CandidateInput] = []
    results_by_pdb: dict[str, list[dict[str, object]]] = {}
    processed_pdb_ids: list[str] = []
    skipped_pdb_ids: list[str] = []
    prepared_record_counts: dict[str, int] = {}
    source_failures: list[dict[str, object]] = []
    model_root = output_root / model_stage

    for pdb_id in shard_pdb_ids:
        result_path = model_root / pdb_id / "results.jsonl"
        if result_path.exists() and not overwrite:
            skipped_pdb_ids.append(pdb_id)
            continue
        if result_path.exists() and overwrite:
            # 显式覆盖时先撤销旧完成标志；若新任务中断，后续默认续跑才不会误跳过。
            result_path.unlink()

        prepared_path = output_root / "prepared" / pdb_id / "prepared_smiles.jsonl"
        try:
            prepared_records = read_jsonl(prepared_path)
            validate_prepared_records(prepared_records, pdb_id)
            pdb_candidates: list[CandidateInput] = []
            pdb_results: list[dict[str, object]] = []
            for record in prepared_records:
                if bool(record.get("has_model_input")) and record.get(
                    "model_input_smiles"
                ):
                    pdb_candidates.append(
                        CandidateInput(
                            pdb_id=pdb_id,
                            candidate_id=int(record["candidate_id"]),
                            prepared_record=record,
                        )
                    )
                else:
                    result = base_model_result(model_name, record, pdb_id)
                    result.update(
                        {
                            "status": "no_model_input",
                            "actual_model_input_smiles": None,
                            "input_diagnostics": {},
                            "output_path": None,
                            "output_shape": None,
                            "output_dtype": None,
                            "all_finite": None,
                            "nan_count": None,
                            "positive_inf_count": None,
                            "negative_inf_count": None,
                            "error": None,
                        }
                    )
                    pdb_results.append(result)
        except Exception as exc:
            source_failures.append(
                {
                    "pdb_id": pdb_id,
                    "status": "prepared_unavailable",
                    "error": clean_exception(exc),
                }
            )
            continue

        processed_pdb_ids.append(pdb_id)
        prepared_record_counts[pdb_id] = len(prepared_records)
        results_by_pdb[pdb_id] = pdb_results
        candidates.extend(pdb_candidates)

    candidates.sort(key=lambda value: (value.pdb_id, value.candidate_id))
    return ModelWork(
        candidates=candidates,
        results_by_pdb=results_by_pdb,
        processed_pdb_ids=processed_pdb_ids,
        skipped_pdb_ids=skipped_pdb_ids,
        prepared_record_counts=prepared_record_counts,
        source_failures=source_failures,
    )


def append_failed_result(
    work: ModelWork,
    model_name: str,
    candidate: CandidateInput,
    actual_model_input_smiles: str | None,
    input_diagnostics: dict[str, object],
    error: BaseException | str,
) -> None:
    """记录模型对单条 occurrence 没有返回可保存向量的事实。

    结果 ``status=model_failed``；保留模型实际输入和 tokenizer 诊断，所有输出
    路径/形状/dtype/有限性字段为 ``None``，``error`` 保存单行异常或说明。
    """

    result = base_model_result(
        model_name,
        candidate.prepared_record,
        candidate.pdb_id,
    )
    result.update(
        {
            "status": "model_failed",
            "actual_model_input_smiles": actual_model_input_smiles,
            "input_diagnostics": input_diagnostics,
            "output_path": None,
            "output_shape": None,
            "output_dtype": None,
            "all_finite": None,
            "nan_count": None,
            "positive_inf_count": None,
            "negative_inf_count": None,
            "error": (
                clean_exception(error)
                if isinstance(error, BaseException)
                else str(error)
            ),
        }
    )
    work.results_by_pdb[candidate.pdb_id].append(result)


def append_embedding_result(
    work: ModelWork,
    output_root: Path,
    model_stage: str,
    model_name: str,
    candidate: CandidateInput,
    actual_model_input_smiles: str,
    input_diagnostics: dict[str, object],
    embedding: np.ndarray,
) -> None:
    """核对并保存一条 occurrence 的原始 768 维分子表示。

    仅检查“数值数组且形状为 ``(768,)``”这一模型输出契约。NaN 和正负无穷不会
    被替换或拒绝，而是原样保存为 ``float32`` 并在结果记录中分别计数。成功结果
    ``status=encoded``，保存 NPZ 路径、``[768]``、``float32``、全有限标记及三类
    非有限值数量；非数值或错误形状转成 ``model_failed``，不创建假向量。
    """

    array = np.asarray(embedding)
    if not np.issubdtype(array.dtype, np.number):
        append_failed_result(
            work,
            model_name,
            candidate,
            actual_model_input_smiles,
            input_diagnostics,
            f"model output dtype is not numeric: {array.dtype}",
        )
        return
    if array.shape != (768,):
        append_failed_result(
            work,
            model_name,
            candidate,
            actual_model_input_smiles,
            input_diagnostics,
            f"model output shape {array.shape} != (768,)",
        )
        return

    vector = array.astype(np.float32, copy=False)
    output_path = (
        output_root
        / model_stage
        / candidate.pdb_id
        / f"candidate_{candidate.candidate_id}.npz"
    )
    atomic_save_npz(
        output_path,
        pdb_id=np.asarray(candidate.pdb_id),
        candidate_id=np.asarray(candidate.candidate_id, dtype=np.int32),
        object_key=np.asarray(str(candidate.prepared_record["object_key"])),
        model_name=np.asarray(model_name),
        prepared_model_input_smiles=np.asarray(candidate.smiles),
        model_input_smiles=np.asarray(actual_model_input_smiles),
        embedding=vector,
    )

    result = base_model_result(
        model_name,
        candidate.prepared_record,
        candidate.pdb_id,
    )
    result.update(
        {
            "status": "encoded",
            "actual_model_input_smiles": actual_model_input_smiles,
            "input_diagnostics": input_diagnostics,
            "output_path": str(output_path),
            "output_shape": list(vector.shape),
            "output_dtype": str(vector.dtype),
            "all_finite": bool(np.isfinite(vector).all()),
            "nan_count": int(np.isnan(vector).sum()),
            "positive_inf_count": int(np.isposinf(vector).sum()),
            "negative_inf_count": int(np.isneginf(vector).sum()),
            "error": None,
        }
    )
    work.results_by_pdb[candidate.pdb_id].append(result)


def finish_model_pdbs(
    output_root: Path,
    model_stage: str,
    model_name: str,
    work: ModelWork,
) -> list[dict[str, object]]:
    """在全部全局 batch 完成后，原子写入各 PDB 的模型结果清单。

    每个 processed PDB 的结果数必须等于 prepared 记录数；随后按 candidate_id
    排序写入 ``{model_stage}/{pdb_id}/results.jsonl``。返回逐 PDB 完成状态、记录
    数、各 status 数和模型名，供分片报告使用。
    """

    pdb_summaries: list[dict[str, object]] = []
    for pdb_id in work.processed_pdb_ids:
        records = work.results_by_pdb[pdb_id]
        records.sort(key=lambda value: int(value["candidate_id"]))
        expected = work.prepared_record_counts[pdb_id]
        if len(records) != expected:
            raise RuntimeError(
                f"{pdb_id}: model result count {len(records)} != prepared count {expected}"
            )
        result_path = output_root / model_stage / pdb_id / "results.jsonl"
        atomic_write_jsonl(result_path, records)
        statuses = Counter(str(value["status"]) for value in records)
        pdb_summaries.append(
            {
                "pdb_id": pdb_id,
                "status": "completed",
                "result_count": len(records),
                "status_counts": dict(sorted(statuses.items())),
                "model_name": model_name,
            }
        )
    return pdb_summaries


def cuda_runtime_details(torch_module: object) -> dict[str, object]:
    """记录当前 GPU 与 CUDA 运行时事实，不参与是否发布的判断。"""

    torch = torch_module
    available = bool(torch.cuda.is_available())
    return {
        "cuda_available": available,
        "cuda_version": torch.version.cuda,
        "cudnn_version": torch.backends.cudnn.version(),
        "device_count": torch.cuda.device_count(),
        "device_name": torch.cuda.get_device_name(0) if available else None,
    }


def is_fatal_cuda_error(error: BaseException) -> bool:
    """区分必须终止分片的 CUDA/OOM 错误与可逐条重试的普通输入错误。"""

    message = clean_exception(error).lower()
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


def write_model_shard_report(
    output_root: Path,
    model_stage: str,
    model_name: str,
    shard_index: int,
    num_shards: int,
    sample_scope: str,
    all_pdb_count: int,
    selected_pdb_count: int,
    work: ModelWork,
    pdb_summaries: list[dict[str, object]],
    started_at: str,
    started_monotonic: float,
    batch_size: int,
    dependencies: dict[str, str | None],
    cuda: dict[str, object],
) -> Path:
    """写出模型数组任务事实报告，不对结果是否可发布作自动判定。

    报告包含时间、样本范围、分片、处理/跳过/源缺失 PDB、跨 PDB 输入数、batch
    size、逐 occurrence status、吞吐、依赖、CUDA 和逐 PDB 结果；路径固定为
    ``{model_stage}/reports/shard_{index}_of_{count}.json``。
    """

    all_records = [
        record
        for pdb_id in work.processed_pdb_ids
        for record in work.results_by_pdb[pdb_id]
    ]
    statuses = Counter(str(value["status"]) for value in all_records)
    encoded_count = statuses.get("encoded", 0)
    elapsed = time.perf_counter() - started_monotonic
    report = {
        "schema_version": 1,
        "stage": model_stage,
        "model_name": model_name,
        "started_at": started_at,
        "finished_at": utc_now(),
        "elapsed_seconds": elapsed,
        "sample_scope": sample_scope,
        "all_pdb_count": all_pdb_count,
        "shard_index": shard_index,
        "num_shards": num_shards,
        "selected_pdb_count": selected_pdb_count,
        "processed_pdb_count": len(work.processed_pdb_ids),
        "prepared_unavailable_pdb_count": len(work.source_failures),
        "skipped_existing_pdb_count": len(work.skipped_pdb_ids),
        "skipped_existing_pdb_ids": work.skipped_pdb_ids,
        "global_model_input_count": len(work.candidates),
        "batch_size": batch_size,
        "status_counts": dict(sorted(statuses.items())),
        "encoded_vectors_per_second": encoded_count / elapsed if elapsed > 0 else None,
        "dependencies": dependencies,
        "cuda": cuda,
        "pdb_results": sorted(
            [*pdb_summaries, *work.source_failures],
            key=lambda value: str(value["pdb_id"]),
        ),
    }
    path = shard_report_path(output_root / model_stage, shard_index, num_shards)
    atomic_write_json(path, report)
    return path
