"""用官方 MoLFormer-XL 模型编码 occurrence 级配体 SMILES。

当前数组任务负责的所有未完成 PDB 会先展平成一个全局 occurrence 列表，再按
``batch_size`` 跨 PDB 推理。默认 256 来自 A100-PCIE-40GB 的正式前探测试；模型
保持 FP32、eval 模式，不启用自动混合精度，也不对 202 token 以上输入截断。

tokenizer 词表、回拼和长度检查只写入诊断字段。模型若返回数值 ``(768,)``，即使
包含 NaN 或 Inf 也原样保存；普通 batch 异常只逐条重试该 batch，CUDA/OOM 错误
则终止当前分片，不暗自缩小 batch。

逐 occurrence 向量写入 ``molformer/{pdb_id}/candidate_{candidate_id}.npz``，同一
PDB 的状态写入 ``molformer/{pdb_id}/results.jsonl``，数组任务事实写入
``molformer/reports/shard_*.json``。
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from ligand_language_common import (
    clean_exception,
    dependency_versions,
    load_sample_ids,
    select_shard,
    utc_now,
)
from model_output import (
    CandidateInput,
    ModelWork,
    append_embedding_result,
    append_failed_result,
    cuda_runtime_details,
    finish_model_pdbs,
    is_fatal_cuda_error,
    load_model_work,
    write_model_shard_report,
)


MODEL_STAGE = "molformer"
MODEL_NAME = "ibm-research/MoLFormer-XL-both-10pct"
DEFAULT_BATCH_SIZE = 256


def diagnose_input(tokenizer: object, smiles: str) -> dict[str, object]:
    """记录 MoLFormer tokenizer 的无损性和预训练长度诊断，不改变输入。

    返回特殊 token 前后长度、词表外 token、token 回拼文本、是否超过 202 token
    参考长度和 ``truncation_requested=false``。诊断自身失败时只返回截断事实与
    ``diagnostic_error``，模型仍接收原始 SMILES。
    """

    try:
        tokens = tokenizer.tokenize(smiles)
        vocabulary = tokenizer.get_vocab()
        special_count = int(tokenizer.num_special_tokens_to_add(pair=False))
        reconstructed = "".join(tokens)
        unsupported = [token for token in tokens if token not in vocabulary]
        return {
            "token_count_without_special_tokens": len(tokens),
            "token_count_with_special_tokens": len(tokens) + special_count,
            "unsupported_token_count": len(unsupported),
            "unsupported_tokens": sorted(set(unsupported)),
            "token_roundtrip_matches_input": reconstructed == smiles,
            "token_roundtrip_text": reconstructed,
            "pretraining_length_reference": 202,
            "exceeds_pretraining_length_reference": len(tokens) + special_count > 202,
            "truncation_requested": False,
            "diagnostic_error": None,
        }
    except Exception as exc:
        return {
            "truncation_requested": False,
            "diagnostic_error": clean_exception(exc),
        }


def infer_batch(
    model: object,
    tokenizer: object,
    candidates: list[CandidateInput],
) -> tuple[np.ndarray, list[dict[str, object]]]:
    """执行一次不截断的官方 tokenizer 与 MoLFormer 前向。

    B 是 ``candidates`` 数，L 是本 batch 补齐后的 token 数。tokenizer 产生
    ``input_ids/attention_mask (B,L)``；官方 ``pooler_output (B,768)`` 转成 NumPy
    后与长度 B 的诊断列表逐 occurrence 对齐返回。
    """

    smiles = [candidate.smiles for candidate in candidates]
    diagnostics = [diagnose_input(tokenizer, value) for value in smiles]
    encoded = tokenizer(
        smiles,
        padding=True,
        truncation=False,
        return_tensors="pt",
    )
    encoded = {name: value.cuda(non_blocking=True) for name, value in encoded.items()}
    with torch.inference_mode():
        output = model(**encoded)
    if not hasattr(output, "pooler_output"):
        raise RuntimeError("MoLFormer output has no pooler_output")
    embeddings = output.pooler_output.detach().cpu().numpy()
    if embeddings.ndim != 2 or embeddings.shape[0] != len(candidates):
        raise RuntimeError(
            f"MoLFormer batch output shape {embeddings.shape} does not match "
            f"batch size {len(candidates)}"
        )
    return embeddings, diagnostics


def run_inference(
    model: object,
    tokenizer: object,
    work: ModelWork,
    output_root: Path,
    batch_size: int,
) -> None:
    """按全局 batch 推理；普通 batch 失败时仅逐条重试其中候选。"""

    total = len(work.candidates)
    for batch_start in range(0, total, batch_size):
        batch = work.candidates[batch_start : batch_start + batch_size]
        try:
            embeddings, diagnostics = infer_batch(model, tokenizer, batch)
        except Exception as batch_error:
            if is_fatal_cuda_error(batch_error):
                raise
            print(
                f"MoLFormer batch {batch_start}:{batch_start + len(batch)} failed; "
                "retrying its candidates individually: "
                f"{clean_exception(batch_error)}",
                flush=True,
            )
            for candidate in batch:
                diagnostic = diagnose_input(tokenizer, candidate.smiles)
                try:
                    embedding, single_diagnostics = infer_batch(
                        model,
                        tokenizer,
                        [candidate],
                    )
                    append_embedding_result(
                        work,
                        output_root,
                        MODEL_STAGE,
                        MODEL_NAME,
                        candidate,
                        candidate.smiles,
                        single_diagnostics[0],
                        embedding[0],
                    )
                except Exception as single_error:
                    if is_fatal_cuda_error(single_error):
                        raise
                    append_failed_result(
                        work,
                        MODEL_NAME,
                        candidate,
                        candidate.smiles,
                        diagnostic,
                        single_error,
                    )
        else:
            for candidate, embedding, diagnostic in zip(
                batch,
                embeddings,
                diagnostics,
                strict=True,
            ):
                append_embedding_result(
                    work,
                    output_root,
                    MODEL_STAGE,
                    MODEL_NAME,
                    candidate,
                    candidate.smiles,
                    diagnostic,
                    embedding,
                )
        print(
            f"MoLFormer encoded or recorded {min(batch_start + len(batch), total)}/{total}",
            flush=True,
        )


def parse_args() -> argparse.Namespace:
    """解析 MoLFormer GPU 数组入口参数。"""

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
    return parser.parse_args()


def main() -> None:
    """加载本地官方权重，完成当前 GPU 分片并写回逐 PDB 结果。"""

    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size 必须为正整数")
    if not torch.cuda.is_available():
        raise RuntimeError("MoLFormer 正式入口需要可用 CUDA GPU")

    started_at = utc_now()
    started = time.perf_counter()
    all_pdb_ids = load_sample_ids(
        args.data_root, args.sample_scope, args.all_valid_path
    )
    shard_pdb_ids = select_shard(all_pdb_ids, args.shard_index, args.num_shards)
    work = load_model_work(
        args.output_root,
        MODEL_STAGE,
        MODEL_NAME,
        shard_pdb_ids,
        args.overwrite,
    )
    print(
        f"MoLFormer shard {args.shard_index}/{args.num_shards}: "
        f"{len(work.candidates)} model inputs across "
        f"{len(work.processed_pdb_ids)} unfinished PDBs",
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
        )
        model.eval()
        model.cuda()
        run_inference(model, tokenizer, work, args.output_root, args.batch_size)

    pdb_summaries = finish_model_pdbs(
        args.output_root,
        MODEL_STAGE,
        MODEL_NAME,
        work,
    )
    report_path = write_model_shard_report(
        output_root=args.output_root,
        model_stage=MODEL_STAGE,
        model_name=MODEL_NAME,
        shard_index=args.shard_index,
        num_shards=args.num_shards,
        sample_scope=args.sample_scope,
        all_pdb_count=len(all_pdb_ids),
        selected_pdb_count=len(shard_pdb_ids),
        work=work,
        pdb_summaries=pdb_summaries,
        started_at=started_at,
        started_monotonic=started,
        batch_size=args.batch_size,
        dependencies=dependency_versions(
            ("numpy", "torch", "transformers", "tokenizers", "rdkit")
        ),
        cuda=cuda_runtime_details(torch),
    )
    print(f"wrote MoLFormer shard report: {report_path}", flush=True)


if __name__ == "__main__":
    main()
