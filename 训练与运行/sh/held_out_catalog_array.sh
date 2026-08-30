#!/usr/bin/env bash
set -euo pipefail

# path, 冻结输入数据根目录和本轮独立输出根目录.
data_root=/storage/penghongen/AdaLigand/Ori_Data
split_root="${data_root}/stage1_preparation_box_pool_3/split"
output_root=/storage/penghongen/AdaLigand/held_out
# int, 单个数组任务的进程数, 默认跟随申请的 8 个 CPU core.
workers="${SLURM_CPUS_PER_TASK:-8}"
# int, 当前完整 PDB 目录分片编号和数组总分片数.
shard_index="${SLURM_ARRAY_TASK_ID:?本任务必须用 Slurm array 提交}"
shard_count="${SLURM_ARRAY_TASK_COUNT:?缺少 Slurm array 总数}"

source /home/penghongen/anaconda3/etc/profile.d/conda.sh
conda activate /home/penghongen/anaconda3/envs/AdaLigand_stage1_py310
# path, 通用任务执行器注入的冻结 release 项目根, 用于导入本次提交的代码.
export PYTHONPATH="${TASK_PROJECT_ROOT}/Data_Preprocessing/held_out"

python -u -m held_out_pipeline.cli catalog-shard \
    --data-root "${data_root}" \
    --pair-list "${data_root}/raw/pair_list.jsonl" \
    --held-out-split "${split_root}/held_out.json" \
    --pdb-audit "${split_root}/pdb_audit.jsonl" \
    --output-root "${output_root}" \
    --shard-index "${shard_index}" \
    --shard-count "${shard_count}" \
    --workers "${workers}"
