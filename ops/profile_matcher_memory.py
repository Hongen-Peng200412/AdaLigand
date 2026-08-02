"""用一个真实 Matcher batch 测量完整 forward/loss/backward/AdamW step 峰值显存。"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import torch
from omegaconf import OmegaConf

from matcher.anchor_data import AnchorPocketDataset
from matcher.batching import collate_anchor_batch
from matcher.train import _data_config, _load_phase1_for_phase2, _loss, _model, _optimizer


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="测量完整 Phase2 真实训练步显存；脚本不自动搜索或修改配置。"
    )
    parser.add_argument("--config", type=Path, required=True, help="Phase2 profile YAML。")
    parser.add_argument(
        "--manifest-indices",
        required=True,
        help="逗号分隔的 train manifest 索引；这些完整 PDB 组成一个测量 batch。",
    )
    parser.add_argument(
        "--channels",
        required=True,
        help="四个逗号分隔 U-Net 通道，例如 16,32,48,64。",
    )
    parser.add_argument(
        "--phase1-checkpoint", type=Path, required=True, help="精确 Phase1 smoke/BEST checkpoint。"
    )
    parser.add_argument("--output", type=Path, required=True, help="memory_profile.json 输出路径。")
    parser.add_argument(
        "--memory-limit-gib",
        type=float,
        default=None,
        help="可选人工显存上限；A800 80 GiB 的 90%% 示例为 72。",
    )
    args = parser.parse_args()

    config = OmegaConf.load(args.config)
    config.model.map_channels = [int(value) for value in args.channels.split(",")]
    config.run.phase1_checkpoint = str(args.phase1_checkpoint)
    indices = [int(value) for value in args.manifest_indices.split(",")]
    dataset = AnchorPocketDataset(_data_config(config, "train", True))
    dataset.set_epoch(0)
    samples = [dataset[index] for index in indices]
    batch = collate_anchor_batch(samples)

    device = torch.device("cuda")
    model = _model(config)
    _load_phase1_for_phase2(model, args.phase1_checkpoint)
    model.to(device).train()
    optimizer = _optimizer(model, config)
    torch.cuda.reset_peak_memory_stats(device)
    torch.cuda.synchronize(device)
    OOM = False
    error = None
    try:
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=bool(config.run.bf16)):
            outputs = model(batch)
            loss = _loss(outputs, batch.samples, config)
        loss.loss_total.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), float(config.optimizer.gradient_clip_norm))
        optimizer.step()
        torch.cuda.synchronize(device)
    except torch.cuda.OutOfMemoryError as exception:
        OOM = True
        error = str(exception)
        torch.cuda.synchronize(device)

    reserved_gib = torch.cuda.max_memory_reserved(device) / 1024**3
    allocated_gib = torch.cuda.max_memory_allocated(device) / 1024**3
    result = {
        "OOM": OOM,
        "error": error,
        "GPU": torch.cuda.get_device_name(device),
        "GPU_total_gib": torch.cuda.get_device_properties(device).total_memory / 1024**3,
        "max_memory_allocated_gib": allocated_gib,
        "max_memory_reserved_gib": reserved_gib,
        "memory_limit_gib": args.memory_limit_gib,
        "within_memory_limit": (
            reserved_gib <= args.memory_limit_gib if args.memory_limit_gib is not None and not OOM else None
        ),
        "map_channels": list(config.model.map_channels),
        "occurrence_budget_per_batch": int(config.data.occurrence_budget_per_batch),
        "map_candidate_chunk_size": config.model.map_candidate_chunk_size,
        "fine_pair_chunk_size": config.model.fine_pair_chunk_size,
        "manifest_indices": indices,
        "pdb_ids": [sample.pdb_id for sample in batch.samples],
        "num_occurrences": sum(sample.num_occurrences for sample in batch.samples),
        "num_candidates": sum(sample.num_candidates for sample in batch.samples),
        "num_A_atoms": sum(
            candidate.A_graph.node_input.shape[0]
            for sample in batch.samples
            for candidate in sample.candidates
        ),
    }
    _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    if OOM:
        sys.exit(1)


if __name__ == "__main__":
    main()
