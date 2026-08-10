#!/usr/bin/env bash
set -euo pipefail

# 本入口只负责把“训练与运行”提供的 Slurm 环境转换成 Python 参数：
# - 第一个位置参数决定处理 all_valid.json，还是处理全部现存 ligand_area.npz；
# - SLURM_ARRAY_TASK_ID 决定当前数组任务的零基分片编号；
# - SLURM_ARRAY_TASK_COUNT 决定分片总数；
# - SLURM_ARRAY_TASK_MIN/MAX/STEP 用于确认任务编号从 0 开始且连续；
# - SLURM_CPUS_PER_TASK 决定当前分片内部并行处理多少个 PDB。
# 正式命令使用 --array 0-11 --cpus 8，因此共有 12 个互斥分片，每个分片最多
# 同时处理 8 个 PDB。文件写入、跳过和失败语义全部由 Python 入口负责。

if [[ $# -ne 1 ]]; then
    echo "用法: $0 {all_valid|all_existing}" >&2
    exit 2
fi
sample_scope=$1
if [[ "${sample_scope}" != "all_valid" && "${sample_scope}" != "all_existing" ]]; then
    echo "sample scope 必须是 all_valid 或 all_existing" >&2
    exit 2
fi

# 完整模式会在每个数组任务真正执行前建立只读 release，并把该 release 的项目根
# 写入 TASK_PROJECT_ROOT。脚本不从本机工作区或调用位置猜测 Python 文件路径。
: "${TASK_PROJECT_ROOT:?训练与运行完整模式必须提供 TASK_PROJECT_ROOT}"
# 本脚本必须由零基连续 Slurm array 启动；没有 --array 时不静默退化为全量单任务。
: "${SLURM_ARRAY_TASK_ID:?必须通过 --array 0-N 提供当前数组任务编号}"
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
# 每个数组任务只使用自己申请到的 CPU 数；正式 --cpus 8 会传入 8 个 worker。
workers=${SLURM_CPUS_PER_TASK:-1}
shard_index=${SLURM_ARRAY_TASK_ID}
num_shards=${SLURM_ARRAY_TASK_COUNT}

# Python 入口会先重建同一份排序全局 PDB 清单，再按 [shard_index::num_shards]
# 选择当前任务的互斥子集。12 个任务不会同时修改同一个 ligand_area.npz。
"${python_bin}" \
    "${TASK_PROJECT_ROOT}/Data_Preprocessing/Ori_Data_upgrade/upgrade_ligand_area_masks.py" \
    --root "${data_root}" \
    --sample-scope "${sample_scope}" \
    --all-valid "${catalog_root}/all_valid.json" \
    --workers "${workers}" \
    --shard-index "${shard_index}" \
    --num-shards "${num_shards}"
