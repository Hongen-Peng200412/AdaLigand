#!/usr/bin/env bash
set -euo pipefail

# 本入口把“训练与运行”创建的只读 release 和零基连续 Slurm 数组参数交给 CPU
# 准备脚本。数组任务先按 PDB 交错分片；每个任务内部再使用自己申请到的 CPU
# 数量并行处理 PDB。第一个位置参数只决定样本范围，不修改 all_valid.json。

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
: "${SLURM_ARRAY_TASK_ID:?CPU 准备必须通过 --array 0-N 提供任务编号}"
: "${SLURM_ARRAY_TASK_COUNT:?Slurm 必须提供数组任务总数}"
: "${SLURM_ARRAY_TASK_MIN:?Slurm 必须提供数组任务最小编号}"
: "${SLURM_ARRAY_TASK_MAX:?Slurm 必须提供数组任务最大编号}"
: "${SLURM_ARRAY_TASK_STEP:?Slurm 必须提供数组任务编号步长}"
if ((
    SLURM_ARRAY_TASK_MIN != 0
    || SLURM_ARRAY_TASK_STEP != 1
    || SLURM_ARRAY_TASK_MAX + 1 != SLURM_ARRAY_TASK_COUNT
)); then
    echo "Slurm array 必须是零基连续范围，例如 --array 0-11" >&2
    exit 2
fi

python_bin=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python
data_root=/storage/penghongen/AdaLigand/Ori_Data
catalog_root=${data_root}/stage1_preparation_box_pool_2
output_root=${catalog_root}/ligand_language_models
workers=${SLURM_CPUS_PER_TASK:-1}

"${python_bin}" \
    "${TASK_PROJECT_ROOT}/Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/prepare_ligand_language_inputs.py" \
    --data-root "${data_root}" \
    --output-root "${output_root}" \
    --all-valid-path "${catalog_root}/all_valid.json" \
    --sample-scope "${sample_scope}" \
    --shard-index "${SLURM_ARRAY_TASK_ID}" \
    --num-shards "${SLURM_ARRAY_TASK_COUNT}" \
    --workers "${workers}" \
    "${overwrite_args[@]}"
