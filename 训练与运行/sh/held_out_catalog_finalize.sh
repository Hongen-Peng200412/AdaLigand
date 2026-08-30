#!/usr/bin/env bash
set -euo pipefail

# path, 冻结输入数据根目录, PDB split 目录和本轮独立输出根目录.
data_root=/storage/penghongen/AdaLigand/Ori_Data
split_root="${data_root}/stage1_preparation_box_pool_3/split"
pdb_split_root="${split_root}/pdb_split"
output_root=/storage/penghongen/AdaLigand/held_out
# int, 目录 array 与后续 MMseqs2 query array 各自固定使用 12 个分片.
catalog_shard_count=12
alignment_shard_count=12
# int, 3 个官方 smoke 身份优先覆盖 protein 和核酸, 再稳定补足一个 PDB.
official_smoke_count=3
source /home/penghongen/anaconda3/etc/profile.d/conda.sh
conda activate /home/penghongen/anaconda3/envs/AdaLigand_stage1_py310
# path, 通用任务执行器注入的冻结 release 项目根, 用于导入本次提交的代码.
export PYTHONPATH="${TASK_PROJECT_ROOT}/Data_Preprocessing/held_out"

python -u -m held_out_pipeline.cli catalog-finalize \
    --output-root "${output_root}" \
    --pair-list "${data_root}/raw/pair_list.jsonl" \
    --train-pdb "${pdb_split_root}/train.json" \
    --validation-pdb "${pdb_split_root}/validation.json" \
    --calibration-pdb "${pdb_split_root}/calibration.json" \
    --held-out-pdb "${pdb_split_root}/held_out.json" \
    --shard-count "${catalog_shard_count}" \
    --alignment-shard-count "${alignment_shard_count}" \
    --official-smoke-count "${official_smoke_count}" \
    --official-timeout-seconds 30
