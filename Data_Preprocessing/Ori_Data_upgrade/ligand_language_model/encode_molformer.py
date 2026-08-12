"""用官方 MoLFormer-XL 为每个 prepared occurrence 生成一个 768 维分子向量。

当前 GPU 分片的所有非空 SMILES 先合成一个跨 PDB 列表，再按全局 batch 前向。
加载权重时显式启用官方特征提取示例使用的 ``deterministic_eval=True``，使同一输入不因
前向次数、batch 边界或逐 occurrence 重试而重新抽取随机特征映射权重。
正式产物仍按 PDB 写回；不会保存 tokenizer 的 token 级表示或模型的 token 级隐状态。

命令入口 ``main`` 由样本范围、数组分片、batch_size 和 ``--output-root`` 决定本次
工作；核心前向位于 ``run_molformer``。``--output-root/molformer/{pdb_id}/results.jsonl``
是 JSONL，每个对象以 ``pdb_id``、``candidate_id``、``status``、两种 SMILES、
``output_file``、``error`` 和 ``diagnostics`` 说明一个 occurrence。
``candidate_{candidate_id}.npz`` 以命名数组保存 occurrence 身份、模型名、两种 SMILES
和 ``float32 (768,)`` embedding。``--output-root/molformer/reports/shard_*.json`` 是单个
JSON 对象，核心字段是分片身份、PDB 数、输入数、batch_size、状态计数、依赖与 CUDA 事实。
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

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


MODEL_STAGE = "molformer"
MODEL_NAME = "ibm-research/MoLFormer-XL-both-10pct"
DEFAULT_BATCH_SIZE = 256


def diagnose_tokens(tokenizer: object, smiles: str) -> dict[str, object]:
    """记录 MoLFormer tokenizer 如何拆分一个 SMILES，但不据此阻止模型调用。

    返回字段:
        token_count_without_special_tokens: 不含起止符的化学 token 数；诊断成功时出现。
        token_count_with_special_tokens: 加入模型特殊 token 后的总长度；诊断成功时出现。
        unsupported_tokens: tokenizer 已拆出、但精确词表中不存在的 token 去重列表；诊断成功时出现。
        token_roundtrip_text: 把化学 token 按原顺序直接拼回的字符串；诊断成功时出现。
        token_roundtrip_matches_input: 拼回字符串是否与输入 SMILES 完全相同；诊断成功时出现。
        exceeds_pretraining_length_reference: 总长度是否超过 202 token 的预训练参考长度；诊断成功时出现。
        truncation_requested: 固定为 ``False``，诊断成功或失败时都出现。
        diagnostic_error: 诊断自身的异常；成功时为 ``None``，失败时为非空字符串。

    词表未知、拼回不一致或超过参考长度都只是事实。只要官方 tokenizer 和模型没有
    报错，后续仍可得到并保存向量。
    """

    try:
        tokens = tokenizer.tokenize(smiles)
        vocabulary = tokenizer.get_vocab()
        unsupported_tokens = sorted(
            {token for token in tokens if token not in vocabulary}
        )
        special_token_count = int(tokenizer.num_special_tokens_to_add(pair=False))
        roundtrip_text = "".join(tokens)
        total_token_count = len(tokens) + special_token_count
        return {
            "token_count_without_special_tokens": len(tokens),
            "token_count_with_special_tokens": total_token_count,
            "unsupported_tokens": unsupported_tokens,
            "token_roundtrip_text": roundtrip_text,
            "token_roundtrip_matches_input": roundtrip_text == smiles,
            "exceeds_pretraining_length_reference": total_token_count > 202,
            "truncation_requested": False,
            "diagnostic_error": None,
        }
    except Exception as error:
        return {
            "truncation_requested": False,
            "diagnostic_error": format_error(error),
        }


def encode_batch(
    model: object,
    tokenizer: object,
    candidates: list[ModelCandidate],
) -> tuple[np.ndarray, list[dict[str, object]]]:
    """执行一次官方 MoLFormer tokenizer 与模型前向，不请求截断。

    形状符号:
        B: 当前全局 batch 的 occurrence 数。
        L: 当前 batch 补齐后的最大 token 长度。

    tokenizer 产生两个关键张量：``input_ids`` 是整数 ``(B, L)``，每个数是一个 token
    在官方词表中的编号；``attention_mask`` 是 ``(B, L)``，1 表示真实 token，0 表示
    为对齐 batch 补上的 padding。两个张量的第 b 行都对应 ``candidates[b]``。它们只在
    内存中送入模型，不写正式产物。

    返回:
        embeddings: ``(B, 768)``，官方 ``pooler_output`` 的 NumPy 表示。
        diagnostics: 长度为 B，与 candidates 逐位置对应的 token 诊断。
    """

    smiles: list[str] = []
    for candidate in candidates:
        if candidate.prepared.smiles is None:
            raise ValueError("ModelCandidate.prepared.smiles 不得为 None")
        smiles.append(candidate.prepared.smiles)
    diagnostics = [diagnose_tokens(tokenizer, value) for value in smiles]

    token_batch = tokenizer(
        smiles,
        padding=True,
        truncation=False,
        return_tensors="pt",
    )
    if "input_ids" not in token_batch or "attention_mask" not in token_batch:
        raise RuntimeError("MoLFormer tokenizer 未同时返回 input_ids 和 attention_mask")
    if token_batch["input_ids"].shape != token_batch["attention_mask"].shape:
        raise RuntimeError("MoLFormer input_ids 与 attention_mask 形状不一致")
    if token_batch["input_ids"].ndim != 2 or token_batch["input_ids"].shape[0] != len(
        smiles
    ):
        raise RuntimeError(
            f"MoLFormer token 张量形状为 {tuple(token_batch['input_ids'].shape)}，"
            f"第一维应为 {len(smiles)}"
        )

    # 所有 tokenizer 张量保持 (B, L) 等原形状，只把设备从 CPU 移到当前 CUDA 卡。
    token_batch = {
        name: value.cuda(non_blocking=True) for name, value in token_batch.items()
    }
    with torch.inference_mode():
        model_output = model(**token_batch)
    if not hasattr(model_output, "pooler_output"):
        raise RuntimeError("MoLFormer 输出没有 pooler_output")

    embeddings = model_output.pooler_output.detach().cpu().numpy()
    if embeddings.shape != (len(candidates), 768):
        raise RuntimeError(
            f"MoLFormer 输出形状为 {embeddings.shape}，"
            f"预期为 ({len(candidates)}, 768)"
        )
    return embeddings, diagnostics


# ================================================================================================


def run_molformer(
    model: object,
    tokenizer: object,
    work: ModelWork,
    output_root: Path,
    batch_size: int,
) -> None:
    """按跨 PDB 的全局 batch 编码当前分片全部候选。

    ``work.candidates[start:start + batch_size]`` 直接切全局列表，所以一个 batch 可以含
    多个 PDB；不足 batch_size 的最后一块直接运行，不添加特殊分支。普通 batch 异常时，
    同批候选逐 occurrence 重试。CUDA OOM、驱动、cuBLAS、cuDNN 等致命异常直接抛出，
    不在可能损坏的 CUDA 上下文中继续调用模型。

    成功候选立即写 ``molformer/{pdb_id}/candidate_{candidate_id}.npz`` 并追加 encoded；
    普通失败只追加 model_failed，不写占位 NPZ。逐 PDB ``results.jsonl`` 由 main 最后收口。
    """

    total = len(work.candidates)
    for batch_start in range(0, total, batch_size):
        batch = work.candidates[batch_start : batch_start + batch_size]
        try:
            embeddings, diagnostics = encode_batch(model, tokenizer, batch)
        except Exception as batch_error:
            if is_fatal_cuda_error(batch_error):
                raise
            print(
                f"MoLFormer batch {batch_start}:{batch_start + len(batch)} 失败，"
                f"改为逐 occurrence 重试: {format_error(batch_error)}",
                flush=True,
            )
            for candidate in batch:
                prepared = candidate.prepared
                if prepared.smiles is None:
                    raise RuntimeError("ModelCandidate 中出现 smiles=None")
                diagnostic = diagnose_tokens(tokenizer, prepared.smiles)
                try:
                    single_embedding, single_diagnostics = encode_batch(
                        model,
                        tokenizer,
                        [candidate],
                    )
                except Exception as single_error:
                    if is_fatal_cuda_error(single_error):
                        raise
                    work.results_by_pdb[candidate.pdb_id].append(
                        ModelResult(
                            pdb_id=candidate.pdb_id,
                            candidate_id=prepared.candidate_id,
                            type_tag=prepared.type_tag,
                            status="model_failed",
                            prepared_smiles=prepared.smiles,
                            model_smiles=prepared.smiles,
                            output_file=None,
                            error=format_error(single_error),
                            diagnostics=diagnostic,
                        )
                    )
                else:
                    record_embedding_result(
                        work=work,
                        output_root=output_root,
                        model_stage=MODEL_STAGE,
                        model_name=MODEL_NAME,
                        candidate=candidate,
                        model_smiles=prepared.smiles,
                        embedding=single_embedding[0],
                        diagnostics=single_diagnostics[0],
                    )
        else:
            # 三个序列长度均为 B，第 b 个元素始终属于同一个 occurrence。
            for candidate, embedding, diagnostic in zip(
                batch,
                embeddings,
                diagnostics,
                strict=True,
            ):
                record_embedding_result(
                    work=work,
                    output_root=output_root,
                    model_stage=MODEL_STAGE,
                    model_name=MODEL_NAME,
                    candidate=candidate,
                    model_smiles=candidate.prepared.smiles,
                    embedding=embedding,
                    diagnostics=diagnostic,
                )
        completed = min(batch_start + len(batch), total)
        print(f"MoLFormer 已处理 {completed}/{total} 个 occurrence", flush=True)


def main() -> None:
    """加载本地官方权重，运行一个 GPU 数组分片，并写逐 PDB 与分片结果。

    顺序固定为：选择 PDB 分片；读取未完成 prepared 文件；跨 PDB 展平候选；加载一份
    tokenizer 与确定性推理模型；执行全局 batch；核对并写每个 PDB 的
    ``results.jsonl``；最后写分片报告。服务器只从 ``--model-dir`` 读取权重，不访问
    外网。
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
        raise RuntimeError("MoLFormer 正式入口需要可用 CUDA GPU")

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
        f"MoLFormer 分片 {args.shard_index}/{args.num_shards}: "
        f"{len(work.candidates)} 个模型输入，来自 "
        f"{len(work.active_pdb_ids)} 个未完成 PDB",
        flush=True,
    )

    if work.candidates:
        tokenizer = AutoTokenizer.from_pretrained(
            str(args.model_dir),
            trust_remote_code=True,
            local_files_only=True,
        )
        model = AutoModel.from_pretrained(
            str(args.model_dir),
            trust_remote_code=True,
            local_files_only=True,
            deterministic_eval=True,
        )
        # 官方模型在 deterministic_eval=False 时即使处于 eval 模式也会在每次前向重抽随机特征映射；特征提取必须显式固定该开关。
        if getattr(model.config, "deterministic_eval", None) is not True:
            raise RuntimeError("MoLFormer 未成功启用 deterministic_eval=True")
        model.eval()
        model.cuda()
        run_molformer(model, tokenizer, work, args.output_root, args.batch_size)

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
        batch_size=args.batch_size,
        started_at=started_at,
        started_monotonic=started,
        dependencies=dependency_versions(
            ("numpy", "torch", "transformers", "tokenizers", "rdkit")
        ),
        cuda=cuda_facts(torch),
    )
    print(f"已写入 MoLFormer 分片报告: {report_path}", flush=True)


if __name__ == "__main__":
    main()
