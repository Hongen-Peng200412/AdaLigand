#!/usr/bin/env bash
set -euo pipefail

# MoLFormer 可以由单个 A100 任务或零基连续 GPU array 启动。每个数组任务负责一组
# PDB，但 Python 会把这组 PDB 的 occurrence 全部展平后跨 PDB 组成 256 大小的
# batch。模型权重和 Python 运行时位于数据目录之外的稳定只读位置，脚本禁止联网。

if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "用法: $0 {all_valid|all_existing} [--overwrite]" >&2
    exit 2
fi
sample_scope=$1
if [[ "${sample_scope}" != "all_valid" && "${sample_scope}" != "all_existing" ]]; then
    echo "sample scope 必须是 all_valid 或 all_existing" >&2
    exit 2
fi
overwrite_args=()
if [[ $# -eq 2 ]]; then
    if [[ $2 != "--overwrite" ]]; then
        echo "第二个参数只能是 --overwrite" >&2
        exit 2
    fi
    overwrite_args=(--overwrite)
fi

: "${TASK_PROJECT_ROOT:?训练与运行完整模式必须提供 TASK_PROJECT_ROOT}"
if [[ -n "${SLURM_ARRAY_TASK_ID:-}" ]]; then
    : "${SLURM_ARRAY_TASK_COUNT:?Slurm 必须提供数组任务总数}"
    : "${SLURM_ARRAY_TASK_MIN:?Slurm 必须提供数组任务最小编号}"
    : "${SLURM_ARRAY_TASK_MAX:?Slurm 必须提供数组任务最大编号}"
    : "${SLURM_ARRAY_TASK_STEP:?Slurm 必须提供数组任务编号步长}"
    if ((
        SLURM_ARRAY_TASK_MIN != 0
        || SLURM_ARRAY_TASK_STEP != 1
        || SLURM_ARRAY_TASK_MAX + 1 != SLURM_ARRAY_TASK_COUNT
    )); then
        echo "GPU array 必须是零基连续范围，例如 --array 0-3" >&2
        exit 2
    fi
    shard_index=${SLURM_ARRAY_TASK_ID}
    num_shards=${SLURM_ARRAY_TASK_COUNT}
else
    shard_index=0
    num_shards=1
fi

python_bin=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python
data_root=/storage/penghongen/AdaLigand/Ori_Data
catalog_root=${data_root}/stage1_preparation_box_pool_2
output_root=${catalog_root}/ligand_language_models
weight_root=/storage/penghongen/AdaLigand/model_weights/ligand_language_models
model_dir=${weight_root}/models/molformer
runtime_dir=${weight_root}/runtime/molformer

export PYTHONNOUSERSITE=1
export PYTHONPATH="${runtime_dir}${PYTHONPATH:+:${PYTHONPATH}}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

"${python_bin}" \
    "${TASK_PROJECT_ROOT}/Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_molformer.py" \
    --data-root "${data_root}" \
    --output-root "${output_root}" \
    --all-valid-path "${catalog_root}/all_valid.json" \
    --model-dir "${model_dir}" \
    --sample-scope "${sample_scope}" \
    --shard-index "${shard_index}" \
    --num-shards "${num_shards}" \
    --batch-size 256 \
    "${overwrite_args[@]}"
