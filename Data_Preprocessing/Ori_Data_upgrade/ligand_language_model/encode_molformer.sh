#!/usr/bin/env bash
set -euo pipefail

# 位置参数 1 只决定样本范围；可选位置参数 2 为 --overwrite，它让 Python 撤掉已有 results.jsonl 完成标志并重做相应 PDB。
if [[ $# -lt 1 || $# -gt 2 ]]; then
    echo "用法: $0 {all_valid|all_existing} [--overwrite]" >&2
    exit 2
fi
sample_scope=$1
if [[ ${sample_scope} != "all_valid" && ${sample_scope} != "all_existing" ]]; then
    echo "样本范围必须是 all_valid 或 all_existing" >&2
    exit 2
fi
overwrite=0
if [[ $# -eq 2 ]]; then
    if [[ $2 != "--overwrite" ]]; then
        echo "第二个参数只能是 --overwrite" >&2
        exit 2
    fi
    overwrite=1
fi

# 单卡任务按 0/1 运行；GPU array 必须是零基连续范围，例如 --array 0-3。
: "${TASK_PROJECT_ROOT:?训练与运行完整模式必须提供 TASK_PROJECT_ROOT}"
if [[ -n ${SLURM_ARRAY_TASK_ID:-} ]]; then
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

# Pocket_Plus_centos7_cu121_allgpu 提供 PyTorch 2.4.1+cu121。
# CPU 化学准备环境不含 PyTorch，因此模型入口必须显式选择这套 GPU 环境。
python_bin=/home/penghongen/anaconda3/envs/Pocket_Plus_centos7_cu121_allgpu/bin/python
data_root=/storage/penghongen/AdaLigand/Ori_Data
catalog_root=${data_root}/stage1_preparation_box_pool_2
output_root=${catalog_root}/ligand_language_models
weight_root=/storage/penghongen/AdaLigand/model_weights/ligand_language_models
model_dir=${weight_root}/models/molformer
runtime_dir=${weight_root}/runtime/molformer

# 模型只读取本地权重；一个数组任务会把所属 PDB 的 occurrence 合并后按 256 组成全局 batch，batch 边界不按 PDB 切分。
export PYTHONNOUSERSITE=1
export PYTHONPATH="${runtime_dir}${PYTHONPATH:+:${PYTHONPATH}}"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false

# 参数数组始终以 Python 入口脚本路径开头，避免 set -u 把空数组展开判为未绑定变量。
python_args=(
    "${TASK_PROJECT_ROOT}/Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_molformer.py"
    --data-root "${data_root}"
    --output-root "${output_root}"
    --all-valid-path "${catalog_root}/all_valid.json"
    --model-dir "${model_dir}"
    --sample-scope "${sample_scope}"
    --shard-index "${shard_index}"
    --num-shards "${num_shards}"
    --batch-size 256
)
if ((overwrite)); then
    python_args+=(--overwrite)
fi
"${python_bin}" "${python_args[@]}"
