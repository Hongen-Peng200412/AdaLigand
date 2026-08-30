#!/usr/bin/env bash
set -euo pipefail

# str, chain 和 residue 两级判定的组合方式, 可取 or 或 and.
pdb_coverage_mode="${1:-or}"
# float [0,1], chain 和 residue 两级共用的包含边界阈值.
pdb_coverage_threshold="${2:-0.5}"
# path, 冻结 PDB split 目录和本轮独立输出根目录.
data_root=/storage/penghongen/AdaLigand/Ori_Data
pdb_split_root="${data_root}/stage1_preparation_box_pool_3/split/pdb_split"
output_root=/storage/penghongen/AdaLigand/held_out
# int, 贪心独立集和 test_0 抽样共享 entropy, 但使用两个独立 spawn_key.
seed=3407
# int, test_0 的固定目标 PDB 数; 独立集不足时 finalize 明确失败.
test_0_size=200

source /home/penghongen/anaconda3/etc/profile.d/conda.sh
conda activate /home/penghongen/anaconda3/envs/AdaLigand_stage1_py310
# path, 通用任务执行器注入的冻结 release 项目根, 用于导入本次提交的代码.
export PYTHONPATH="${TASK_PROJECT_ROOT}/Data_Preprocessing/held_out"

python -u -m held_out_pipeline.cli finalize \
    --output-root "${output_root}" \
    --train-pdb "${pdb_split_root}/train.json" \
    --validation-pdb "${pdb_split_root}/validation.json" \
    --calibration-pdb "${pdb_split_root}/calibration.json" \
    --held-out-pdb "${pdb_split_root}/held_out.json" \
    --alignment-shard-count 12 \
    --pdb-coverage-mode "${pdb_coverage_mode}" \
    --pdb-coverage-threshold "${pdb_coverage_threshold}" \
    --seed "${seed}" \
    --test-0-size "${test_0_size}"
