#!/usr/bin/env bash
set -euo pipefail

# path, 第一组输出根目录和冻结版本 MMseqs2 可执行文件.
output_root=/storage/penghongen/AdaLigand/held_out
mmseqs_binary=/home/penghongen/software/mmseqs2/18-8cc5c/bin/mmseqs
# int, 单个 easy-search 的线程数, 默认跟随申请的 8 个 CPU core.
threads="${SLURM_CPUS_PER_TASK:-8}"
# int, 当前 held-out query FASTA 分片编号.
shard_index="${SLURM_ARRAY_TASK_ID:?本任务必须用 Slurm array 提交}"

source /home/penghongen/anaconda3/etc/profile.d/conda.sh
conda activate /home/penghongen/anaconda3/envs/AdaLigand_stage1_py310
# path, 通用任务执行器注入的冻结 release 项目根, 用于导入本次提交的代码.
export PYTHONPATH="${TASK_PROJECT_ROOT}/Data_Preprocessing/held_out"

python -u -m held_out_pipeline.cli mmseqs-shard \
    --mmseqs-binary "${mmseqs_binary}" \
    --output-root "${output_root}" \
    --shard-index "${shard_index}" \
    --threads "${threads}"
