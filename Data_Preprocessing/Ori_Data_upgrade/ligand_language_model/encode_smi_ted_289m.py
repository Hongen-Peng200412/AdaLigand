"""用官方 SMI-TED Light 289M 模型编码 occurrence 级配体 SMILES。

脚本对当前数组任务的全部未完成 PDB 建立一个跨 PDB 全局列表，并把完整列表一次
交给官方 ``model.encode``。官方入口内部继续使用默认规范化、tokenizer、202 token
截断、均值聚合和自编码器池化行为；默认 ``batch_size=100``。只有全局候选少于
100 时把 batch_size 设为候选数，避免官方小样本分片公式把每条输入拆成单样本。

SMI-TED 的未知 token 与 pad token 共用 ``<pad>``，因此脚本额外记录精确词表、
回拼和截断事实，但不以这些诊断阻止调用官方模型。普通批量异常会逐条重试；
CUDA/OOM 错误终止分片，不暗自改变 batch。

逐 occurrence 向量写入 ``smi_ted_289m/{pdb_id}/candidate_{candidate_id}.npz``，同一
PDB 的状态写入 ``smi_ted_289m/{pdb_id}/results.jsonl``，数组任务事实写入
``smi_ted_289m/reports/shard_*.json``。
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

from ligand_language_common import (
    clean_exception,
    dependency_versions,
    load_sample_ids,
    select_shard,
    utc_now,
)
from model_output import (
    ModelWork,
    append_embedding_result,
    append_failed_result,
    cuda_runtime_details,
    finish_model_pdbs,
    is_fatal_cuda_error,
    load_model_work,
    write_model_shard_report,
)


MODEL_STAGE = "smi_ted_289m"
MODEL_NAME = "SMI-TED Light 289M"
DEFAULT_BATCH_SIZE = 100
REQUIRED_TRANSFORMERS_VERSION = "4.57.6"


def load_official_module(model_dir: Path) -> ModuleType:
    """从稳定本地权重目录加载官方 ``load.py``，不访问外网。"""

    actual_version = metadata.version("transformers")
    if actual_version != REQUIRED_TRANSFORMERS_VERSION:
        raise RuntimeError(
            "SMI-TED tokenizer requires transformers "
            f"{REQUIRED_TRANSFORMERS_VERSION}; current version is {actual_version}"
        )
    source_path = model_dir / "smi-ted" / "inference" / "smi_ted_light" / "load.py"
    specification = importlib.util.spec_from_file_location(
        "adaligand_official_smi_ted_light",
        source_path,
    )
    if specification is None or specification.loader is None:
        raise ImportError(f"cannot load official SMI-TED source: {source_path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def diagnose_input(
    official_module: ModuleType,
    model: object,
    prepared_smiles: str,
) -> tuple[str | None, dict[str, object]]:
    """复现官方规范化并记录 tokenizer 是否无损、是否会被截断。

    第一个返回值是诊断代码复现出的完整规范化 SMILES；规范化失败时为 ``None``。
    第二个返回值保存规范化状态、截断前 token 数、官方上限、是否截断、有效化学
    token 文本、词表外 token、回拼结果和诊断异常。所有字段只用于记录。
    """

    try:
        normalized = official_module.normalize_smiles(prepared_smiles)
    except Exception as exc:
        return None, {"diagnostic_error": clean_exception(exc)}
    if not isinstance(normalized, str) or not normalized:
        return None, {
            "official_normalized_smiles": None,
            "official_normalization_success": False,
            "diagnostic_error": None,
        }

    try:
        tokens = model.tokenizer.tokenize(normalized)
        vocabulary = model.tokenizer.get_vocab()
        unsupported = [token for token in tokens if token not in vocabulary]
        max_length = int(model.max_len)
        special_count = int(model.tokenizer.num_special_tokens_to_add(pair=False))
        token_count = len(tokens) + special_count
        # 官方 tokenizer 保留开头和结尾特殊 token，中间化学 token 在超过上限时截断。
        retained_chemical_count = max(max_length - special_count, 0)
        effective_token_text = "".join(tokens[:retained_chemical_count])
        return normalized, {
            "official_normalized_smiles": normalized,
            "official_normalization_success": True,
            "token_count_without_special_tokens": len(tokens),
            "token_count_with_special_tokens_before_truncation": token_count,
            "official_max_length": max_length,
            "truncation_applied": token_count > max_length,
            "effective_chemical_token_text": effective_token_text,
            "unsupported_token_count": len(unsupported),
            "unsupported_tokens": sorted(set(unsupported)),
            "unknown_token_is_pad_token": True,
            "token_roundtrip_matches_normalized_smiles": "".join(tokens) == normalized,
            "token_roundtrip_text": "".join(tokens),
            "diagnostic_error": None,
        }
    except Exception as exc:
        return normalized, {
            "official_normalized_smiles": normalized,
            "official_normalization_success": True,
            "diagnostic_error": clean_exception(exc),
        }


def official_encode(
    model: object,
    smiles: list[str],
    batch_size: int,
) -> np.ndarray:
    """调用未经改写的官方 ``model.encode`` 并返回 ``(B,768)`` NumPy 数组。

    B 是当前跨 PDB 输入数。官方 tokenizer 内部产生最大 202 token 的张量并执行
    官方池化；本函数只把返回 Tensor 移到 CPU，不保存 ``(B,L)`` token 张量。
    """

    effective_batch_size = min(batch_size, len(smiles))
    with torch.inference_mode():
        output = model.encode(
            smiles,
            batch_size=effective_batch_size,
            return_torch=True,
        )
    if isinstance(output, torch.Tensor):
        array = output.detach().cpu().numpy()
    else:
        array = np.asarray(output)
    if array.ndim != 2 or array.shape[0] != len(smiles):
        raise RuntimeError(
            f"SMI-TED batch output shape {array.shape} does not match input count {len(smiles)}"
        )
    return array


def run_inference(
    official_module: ModuleType,
    model: object,
    work: ModelWork,
    output_root: Path,
    batch_size: int,
) -> None:
    """一次调用官方全局批处理；普通异常时对每条 occurrence 单独重试。"""

    candidates = work.candidates
    prepared_smiles = [candidate.smiles for candidate in candidates]
    diagnostics = [
        diagnose_input(official_module, model, value) for value in prepared_smiles
    ]
    try:
        embeddings = official_encode(model, prepared_smiles, batch_size)
    except Exception as batch_error:
        if is_fatal_cuda_error(batch_error):
            raise
        print(
            "SMI-TED global encode failed; retrying candidates individually: "
            f"{clean_exception(batch_error)}",
            flush=True,
        )
        for index, candidate in enumerate(candidates, start=1):
            actual_smiles, diagnostic = diagnostics[index - 1]
            try:
                embedding = official_encode(model, [candidate.smiles], 1)[0]
                append_embedding_result(
                    work,
                    output_root,
                    MODEL_STAGE,
                    MODEL_NAME,
                    candidate,
                    actual_smiles or candidate.smiles,
                    diagnostic,
                    embedding,
                )
            except Exception as single_error:
                if is_fatal_cuda_error(single_error):
                    raise
                append_failed_result(
                    work,
                    MODEL_NAME,
                    candidate,
                    actual_smiles,
                    diagnostic,
                    single_error,
                )
            if index % 100 == 0 or index == len(candidates):
                print(
                    f"SMI-TED individually recorded {index}/{len(candidates)}",
                    flush=True,
                )
    else:
        for candidate, embedding, diagnostic_pair in zip(
            candidates,
            embeddings,
            diagnostics,
            strict=True,
        ):
            actual_smiles, diagnostic = diagnostic_pair
            append_embedding_result(
                work,
                output_root,
                MODEL_STAGE,
                MODEL_NAME,
                candidate,
                actual_smiles or candidate.smiles,
                diagnostic,
                embedding,
            )


def parse_args() -> argparse.Namespace:
    """解析 SMI-TED GPU 数组入口参数。"""

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
    """加载官方本地 SMI-TED 代码和权重，完成当前 GPU 分片。"""

    args = parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size 必须为正整数")
    if not torch.cuda.is_available():
        raise RuntimeError("SMI-TED 正式入口需要可用 CUDA GPU")

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
        f"SMI-TED shard {args.shard_index}/{args.num_shards}: "
        f"{len(work.candidates)} model inputs across "
        f"{len(work.processed_pdb_ids)} unfinished PDBs",
        flush=True,
    )

    if work.candidates:
        official_module = load_official_module(args.model_dir)
        model = official_module.load_smi_ted(
            folder=str(args.model_dir),
            ckpt_filename="smi-ted-Light_40.pt",
            vocab_filename="bert_vocab_curated.txt",
        )
        model.eval()
        run_inference(
            official_module,
            model,
            work,
            args.output_root,
            args.batch_size,
        )

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
        batch_size=(
            min(args.batch_size, len(work.candidates))
            if work.candidates
            else args.batch_size
        ),
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
        cuda=cuda_runtime_details(torch),
    )
    print(f"wrote SMI-TED shard report: {report_path}", flush=True)


if __name__ == "__main__":
    main()
