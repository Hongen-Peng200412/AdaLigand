#!/usr/bin/env bash
set -euo pipefail

# path, 冻结 mmCIF, 密度图和 Stage1 split 的 AdaLigand 数据根.
data_root=/storage/penghongen/AdaLigand/Ori_Data
# path, train/validation/calibration/held_out 四份纯 PDB identity 列表目录.
pdb_split_root="${data_root}/stage1_preparation_box_pool_3/split/pdb_split"
# path, 序列目录, MMseqs2 TSV 和共享 PDB 边证据的正式产物根.
output_root=/storage/penghongen/AdaLigand/held_out

source /home/penghongen/anaconda3/etc/profile.d/conda.sh
conda activate /home/penghongen/anaconda3/envs/AdaLigand_stage1_py310
# path, 通用任务执行器注入的冻结 release 项目根, 用于导入本次提交的代码.
export PYTHONPATH="${TASK_PROJECT_ROOT}/Data_Preprocessing/held_out"

python -u -m held_out_pipeline.cli edge-finalize \
    --output-root "${output_root}" \
    --train-pdb "${pdb_split_root}/train.json" \
    --validation-pdb "${pdb_split_root}/validation.json" \
    --calibration-pdb "${pdb_split_root}/calibration.json" \
    --held-out-pdb "${pdb_split_root}/held_out.json" \
    --alignment-shard-count 12
