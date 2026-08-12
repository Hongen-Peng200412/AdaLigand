#!/usr/bin/env bash
set -euo pipefail

# 位置参数 1 只决定样本范围：all_valid 读取 all_valid.json，all_existing 处理所有存在 occurrences.jsonl 的 PDB；可选位置参数 2 为 --overwrite。
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

# CPU 准备必须通过零基连续数组启动，例如 --array 0-11；每个数组任务处理互不重叠的一组 PDB，并使用 SLURM_CPUS_PER_TASK 个进程。
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

# 参数数组始终以 Python 入口脚本路径开头，避免 set -u 把空数组展开判为未绑定变量。
python_args=(
    "${TASK_PROJECT_ROOT}/Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/prepare_smiles.py"
    --data-root "${data_root}"
    --output-root "${output_root}"
    --all-valid-path "${catalog_root}/all_valid.json"
    --sample-scope "${sample_scope}"
    --shard-index "${SLURM_ARRAY_TASK_ID}"
    --num-shards "${SLURM_ARRAY_TASK_COUNT}"
    --workers "${workers}"
)
if ((overwrite)); then
    python_args+=(--overwrite)
fi
"${python_bin}" "${python_args[@]}"
