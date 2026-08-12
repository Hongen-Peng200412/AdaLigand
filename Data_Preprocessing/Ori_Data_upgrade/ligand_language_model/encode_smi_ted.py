"""用官方 SMI-TED Light 289M 为每个 prepared occurrence 生成 768 维分子向量。

当前 GPU 分片中官方规范化成功的非空 prepared SMILES 组成一个跨 PDB 列表，交给
``model.encode``；官方规范化失败项仍逐条调用同一接口。该公开接口根据传入的
``batch_size`` 参数和自身分块公式运行。
正式产物只保存分子级向量，不保存 token 张量或 token 级隐状态。

命令入口 ``main`` 由样本范围、数组分片、batch_size、本地模型目录和
``--output-root`` 决定本次工作；核心诊断与编码位于 ``run_smi_ted``。
``--output-root/smi_ted_289m/{pdb_id}/results.jsonl`` 是 JSONL，每个对象以 ``pdb_id``、
``candidate_id``、``status``、两种 SMILES、``output_file``、``error`` 和 diagnostics
说明一个 occurrence。``candidate_{candidate_id}.npz`` 以命名数组保存 occurrence 身份、
模型名、两种 SMILES 和 ``float32 (768,)`` embedding。
``--output-root/smi_ted_289m/reports/shard_*.json`` 是单个 JSON 对象，核心字段是分片身份、
PDB 数、输入数、有效 batch_size、状态计数、依赖与 CUDA 事实。
"""

from __future__ import annotations

import argparse
import importlib.util
import time
from importlib import metadata
from pathlib import Path
from types import ModuleType

import numpy as np
import torch

from artifacts import ModelResult
from model_results import (
    ModelCandidate,
    ModelWork,
    finish_model_work,
    is_fatal_cuda_error,
    load_model_work,
    record_embedding_result,
    write_model_report,
)
from run_context import (
    cuda_facts,
    dependency_versions,
    format_error,
    load_pdb_ids,
    select_shard,
    utc_now,
)


MODEL_STAGE = "smi_ted_289m"
MODEL_NAME = "SMI-TED Light 289M"
DEFAULT_BATCH_SIZE = 100
REQUIRED_TRANSFORMERS_VERSION = "4.57.6"


def official_encode(model: object, smiles: list[str], batch_size: int) -> np.ndarray:
    """把一个跨 PDB SMILES 列表交给官方 ``model.encode``。

    B 是列表中的 occurrence 数。公开接口收到完整的长度 B 列表和 batch_size 参数；
    本包装层不按 PDB 或固定大小再次拆分。冻结的官方源码用自己的 ``array_split`` 公式
    决定实际分块，因此实际内部批量可能大于传入值，例如 B=199、batch_size=100 时仍是
    一个 199 项批量。返回值必须是数值 ``(B, 768)``。官方入口没有暴露内部
    ``input_ids``、``attention_mask`` 或 token 级向量，本函数不声称观察或保存这些张量。
    """

    if not smiles:
        raise ValueError("official_encode 不接受空 SMILES 列表")
    if batch_size < 1:
        raise ValueError("batch_size 必须是正整数")
    if any(type(value) is not str or not value for value in smiles):
        raise TypeError("official_encode 的每个 SMILES 必须是非空字符串")

    effective_batch_size = min(batch_size, len(smiles))
    with torch.inference_mode():
        output = model.encode(
            smiles,
            batch_size=effective_batch_size,
            return_torch=True,
        )
    if isinstance(output, torch.Tensor):
        embeddings = output.detach().cpu().numpy()
    else:
        embeddings = np.asarray(output)
    if embeddings.shape != (len(smiles), 768):
        raise RuntimeError(
            f"SMI-TED 输出形状为 {embeddings.shape}，预期为 ({len(smiles)}, 768)"
        )
    return embeddings


# ================================================================================================


def run_smi_ted(
    official_module: ModuleType,
    model: object,
    work: ModelWork,
    output_root: Path,
    batch_size: int,
) -> int:
    """记录 SMI-TED 输入事实，并编码当前分片的跨 PDB 全局候选。

    对每个 occurrence 区分三个字符串事实：

    ``prepared_smiles`` 是 CPU 阶段保存、随后传给官方公开 ``model.encode`` 的字符串；
    ``official_normalized_smiles`` 是本代码调用同一官方 ``normalize_smiles`` 后观察到的
    字符串；``official_tokenizer_input_smiles`` 只有在该规范化调用成功时才能确认，否则为
    ``None``。官方公开接口仍可能在诊断规范化失败时返回向量；这种向量照常保存，但不会
    用 prepared 字符串冒充已确认的 tokenizer 输入。

    token 诊断会记录规范字符串的拆分、词表覆盖和官方长度上限，但不充当筛选条件。
    官方规范化成功的 occurrence 组成一个跨 PDB 全局调用；规范化失败的 occurrence 仍逐条
    传给公开 ``encode``，但不混入本次独立规范化未得到非空字符串的项。全局调用发生
    普通异常时逐 occurrence 重试；CUDA 上下文相关致命异常直接抛出。返回值是写入
    分片报告的 batch_size：规范化成功组非空时为公开全局调用的实际参数，否则保留配置值。
    """

    candidates = work.candidates
    prepared_smiles: list[str] = []
    for candidate in candidates:
        if candidate.prepared.smiles is None:
            raise RuntimeError("ModelCandidate.prepared.smiles 不得为 None")
        prepared_smiles.append(candidate.prepared.smiles)

    # token_facts 是长度 B 的列表；第 b 项为“可确认的 tokenizer 输入或 None、诊断字典”，并与 candidates[b]、prepared_smiles[b] 和最终 embeddings[b] 对齐。
    token_facts: list[tuple[str | None, dict[str, object]]] = []
    for public_api_input in prepared_smiles:
        try:
            normalized_value = official_module.normalize_smiles(public_api_input)
        except Exception as error:
            token_facts.append(
                (
                    None,
                    {
                        "public_api_input_smiles": public_api_input,
                        "official_normalized_smiles": None,
                        "official_tokenizer_input_smiles": None,
                        "official_normalization_success": False,
                        "official_normalization_error": format_error(error),
                        "token_diagnostic_error": None,
                    },
                )
            )
            continue

        if type(normalized_value) is not str or not normalized_value:
            token_facts.append(
                (
                    None,
                    {
                        "public_api_input_smiles": public_api_input,
                        "official_normalized_smiles": None,
                        "official_tokenizer_input_smiles": None,
                        "official_normalization_success": False,
                        "official_normalization_error": (
                            "ValueError: 官方 normalize_smiles 未返回非空字符串"
                        ),
                        "token_diagnostic_error": None,
                    },
                )
            )
            continue

        normalized_smiles = normalized_value
        try:
            # tokens 不含起止 token；这次独立诊断复用官方 tokenizer，但不替代 model.encode 的内部调用，也不声称拿到内部张量。
            tokens = model.tokenizer.tokenize(normalized_smiles)
            vocabulary = model.tokenizer.get_vocab()
            unsupported_tokens = sorted(
                {token for token in tokens if token not in vocabulary}
            )
            max_length = int(model.max_len)
            special_token_count = int(
                model.tokenizer.num_special_tokens_to_add(pair=False)
            )
            token_count_with_special = len(tokens) + special_token_count
            retained_prefix_length = max(max_length - special_token_count, 0)
            roundtrip_text = "".join(tokens)
            diagnostics: dict[str, object] = {
                "public_api_input_smiles": public_api_input,
                "official_normalized_smiles": normalized_smiles,
                "official_tokenizer_input_smiles": normalized_smiles,
                "official_normalization_success": True,
                "official_normalization_error": None,
                "token_count_without_special_tokens": len(tokens),
                "token_count_with_special_tokens_before_truncation": (
                    token_count_with_special
                ),
                "official_max_length": max_length,
                "official_default_will_truncate": token_count_with_special > max_length,
                "diagnostic_token_prefix_within_length": "".join(
                    tokens[:retained_prefix_length]
                ),
                "unsupported_tokens": unsupported_tokens,
                "unknown_token": model.tokenizer.unk_token,
                "pad_token": model.tokenizer.pad_token,
                "unknown_token_equals_pad_token": (
                    model.tokenizer.unk_token == model.tokenizer.pad_token
                ),
                "token_roundtrip_text": roundtrip_text,
                "token_roundtrip_matches_normalized_smiles": (
                    roundtrip_text == normalized_smiles
                ),
                "token_diagnostic_error": None,
            }
        except Exception as error:
            diagnostics = {
                "public_api_input_smiles": public_api_input,
                "official_normalized_smiles": normalized_smiles,
                "official_tokenizer_input_smiles": normalized_smiles,
                "official_normalization_success": True,
                "official_normalization_error": None,
                "token_diagnostic_error": format_error(error),
            }
        token_facts.append((normalized_smiles, diagnostics))

    # 官方 encode 会再次调用 normalize_smiles；其中任何解析失败的 None 都会使 tokenizer 拒绝整个列表。
    # batch_items 与 individual_items 的每项均为“当前 ModelCandidate、公开接口输入 SMILES、对应 token_fact”，前者独立规范化成功，后者失败。
    batch_items: list[
        tuple[ModelCandidate, str, tuple[str | None, dict[str, object]]]
    ] = []
    individual_items: list[
        tuple[ModelCandidate, str, tuple[str | None, dict[str, object]]]
    ] = []
    for candidate, public_api_input, token_fact in zip(
        candidates,
        prepared_smiles,
        token_facts,
        strict=True,
    ):
        item = (candidate, public_api_input, token_fact)
        if token_fact[1]["official_normalization_success"] is True:
            batch_items.append(item)
        else:
            individual_items.append(item)

    # retry_items 初始只含规范化失败项；若规范化成功组的全局调用发生普通异常，则改为包含所有项并逐条调用公开接口。
    retry_items = individual_items
    if individual_items:
        print(
            "SMI-TED 官方规范化失败但仍将逐 occurrence 调用公开 encode: "
            f"{len(individual_items)}",
            flush=True,
        )

    if batch_items:
        try:
            embeddings = official_encode(
                model,
                [item[1] for item in batch_items],
                batch_size,
            )
        except Exception as batch_error:
            if is_fatal_cuda_error(batch_error):
                raise
            print(
                "SMI-TED 规范化成功组的全局 encode 失败，改为逐 occurrence 重试: "
                f"{format_error(batch_error)}",
                flush=True,
            )
            retry_items = [*batch_items, *individual_items]
        else:
            for item, embedding in zip(batch_items, embeddings, strict=True):
                candidate, _, token_fact = item
                model_smiles, diagnostics = token_fact
                record_embedding_result(
                    work=work,
                    output_root=output_root,
                    model_stage=MODEL_STAGE,
                    model_name=MODEL_NAME,
                    candidate=candidate,
                    model_smiles=model_smiles,
                    embedding=embedding,
                    diagnostics=diagnostics,
                )

    for index, item in enumerate(retry_items, start=1):
        candidate, public_api_input, token_fact = item
        model_smiles, diagnostics = token_fact
        try:
            embedding = official_encode(model, [public_api_input], 1)[0]
        except Exception as single_error:
            if is_fatal_cuda_error(single_error):
                raise
            prepared = candidate.prepared
            work.results_by_pdb[candidate.pdb_id].append(
                ModelResult(
                    pdb_id=candidate.pdb_id,
                    candidate_id=prepared.candidate_id,
                    type_tag=prepared.type_tag,
                    status="model_failed",
                    prepared_smiles=prepared.smiles,
                    model_smiles=model_smiles,
                    output_file=None,
                    error=format_error(single_error),
                    diagnostics=diagnostics,
                )
            )
        else:
            record_embedding_result(
                work=work,
                output_root=output_root,
                model_stage=MODEL_STAGE,
                model_name=MODEL_NAME,
                candidate=candidate,
                model_smiles=model_smiles,
                embedding=embedding,
                diagnostics=diagnostics,
            )
        if index % 100 == 0 or index == len(retry_items):
            print(
                f"SMI-TED 已逐 occurrence 重试 {index}/{len(retry_items)}",
                flush=True,
            )

    return min(batch_size, len(batch_items)) if batch_items else batch_size


def main() -> None:
    """加载本地官方源码与权重，运行一个 SMI-TED GPU 数组分片并收口结果。

    顺序固定为：选择 PDB 分片；读取未完成 prepared；跨 PDB 展平全局候选；核对官方
    依赖版本；加载一份模型；批量编码规范化成功项并逐条尝试规范化失败项；写逐 PDB
    ``results.jsonl``；写分片报告。服务器只读取 ``--model-dir``，不会在运行时联网下载
    源码或权重。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--all-valid-path", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument(
        "--sample-scope",
        choices=("all_valid", "all_existing"),
        required=True,
    )
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--num-shards", type=int, required=True)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size 必须是正整数")
    if not torch.cuda.is_available():
        raise RuntimeError("SMI-TED 正式入口需要可用 CUDA GPU")

    started_at = utc_now()
    started = time.perf_counter()
    all_pdb_ids = load_pdb_ids(
        args.data_root,
        args.all_valid_path,
        args.sample_scope,
    )
    shard_pdb_ids = select_shard(all_pdb_ids, args.shard_index, args.num_shards)
    work = load_model_work(
        args.output_root,
        MODEL_STAGE,
        shard_pdb_ids,
        args.overwrite,
    )
    print(
        f"SMI-TED 分片 {args.shard_index}/{args.num_shards}: "
        f"{len(work.candidates)} 个模型输入，来自 "
        f"{len(work.active_pdb_ids)} 个未完成 PDB",
        flush=True,
    )

    effective_batch_size = args.batch_size
    if work.candidates:
        # 官方实现把未知 token 配置成 pad token；该行为依赖精确 transformers 版本。
        actual_version = metadata.version("transformers")
        if actual_version != REQUIRED_TRANSFORMERS_VERSION:
            raise RuntimeError(
                f"SMI-TED 需要 transformers {REQUIRED_TRANSFORMERS_VERSION}，"
                f"当前为 {actual_version}"
            )

        source_path = (
            args.model_dir / "smi-ted" / "inference" / "smi_ted_light" / "load.py"
        )
        specification = importlib.util.spec_from_file_location(
            "adaligand_official_smi_ted_light",
            source_path,
        )
        if specification is None or specification.loader is None:
            raise ImportError(f"无法加载官方 SMI-TED 源码: {source_path}")
        official_module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(official_module)

        model = official_module.load_smi_ted(
            folder=str(args.model_dir),
            ckpt_filename="smi-ted-Light_40.pt",
            vocab_filename="bert_vocab_curated.txt",
        )
        model.eval()
        effective_batch_size = run_smi_ted(
            official_module,
            model,
            work,
            args.output_root,
            args.batch_size,
        )

    pdb_summaries = finish_model_work(args.output_root, MODEL_STAGE, work)
    report_path = write_model_report(
        output_root=args.output_root,
        model_stage=MODEL_STAGE,
        model_name=MODEL_NAME,
        work=work,
        pdb_summaries=pdb_summaries,
        sample_scope=args.sample_scope,
        all_pdb_count=len(all_pdb_ids),
        selected_pdb_count=len(shard_pdb_ids),
        shard_index=args.shard_index,
        num_shards=args.num_shards,
        batch_size=effective_batch_size,
        started_at=started_at,
        started_monotonic=started,
        dependencies=dependency_versions(
            (
                "numpy",
                "torch",
                "transformers",
                "tokenizers",
                "rdkit",
                "pandas",
                "pytorch-fast-transformers",
            )
        ),
        cuda=cuda_facts(torch),
    )
    print(f"已写入 SMI-TED 分片报告: {report_path}", flush=True)


if __name__ == "__main__":
    main()
