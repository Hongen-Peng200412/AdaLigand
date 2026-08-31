#!/usr/bin/env bash
set -euo pipefail

# int, Slurm 数组索引; 0-7 依次覆盖两个阈值和四种 PDB coverage 模式.
task_index="${SLURM_ARRAY_TASK_ID}"
# list[str], (8,), 每个数组索引对应的独立 split 目录名.
split_names=(
    held_out_05_chain
    held_out_05_residue
    held_out_05_or
    held_out_05_and
    held_out_06_chain
    held_out_06_residue
    held_out_06_or
    held_out_06_and
)
# list[str], (8,), 与 split_names 同位置的单层或双层 coverage 判定模式.
pdb_coverage_modes=(chain residue or and chain residue or and)
# list[str], (8,), 与 split_names 同位置且可解析为 float 的 chain/residue coverage 包含边界.
pdb_coverage_thresholds=(0.5 0.5 0.5 0.5 0.6 0.6 0.6 0.6)

# str, 当前数组索引对应的 split 目录名.
split_name="${split_names[task_index]}"
# str, 当前 split 采用的 chain, residue, or 或 and 判定模式.
pdb_coverage_mode="${pdb_coverage_modes[task_index]}"
# float, 当前 split 采用的 0.5 或 0.6 coverage 包含边界.
pdb_coverage_threshold="${pdb_coverage_thresholds[task_index]}"
# path, 冻结 mmCIF, 密度图和 Stage1 split 的 AdaLigand 数据根.
data_root=/storage/penghongen/AdaLigand/Ori_Data
# path, held_out 纯 PDB identity 列表所在目录.
pdb_split_root="${data_root}/stage1_preparation_box_pool_3/split/pdb_split"
# path, 参数无关序列, MMseqs2 和 PDB 边证据的共享产物根.
shared_output_root=/storage/penghongen/AdaLigand/held_out
# path, 当前 mode/threshold 的冗余边, 身份证与三个测试视图目录.
split_output_root="${shared_output_root}/split/${split_name}"
# int, 贪心独立集和 test_0 抽样共享的 SeedSequence entropy.
seed=3407
# int, test_0 从 full_test 抽取的目标数量上限.
test_0_size=200

source /home/penghongen/anaconda3/etc/profile.d/conda.sh
conda activate /home/penghongen/anaconda3/envs/AdaLigand_stage1_py310
# path, 通用任务执行器注入的冻结 release 项目根, 用于导入本次提交的代码.
export PYTHONPATH="${TASK_PROJECT_ROOT}/Data_Preprocessing/held_out"

python -u -m held_out_pipeline.cli split-finalize \
    --shared-output-root "${shared_output_root}" \
    --split-output-root "${split_output_root}" \
    --held-out-pdb "${pdb_split_root}/held_out.json" \
    --pdb-coverage-mode "${pdb_coverage_mode}" \
    --pdb-coverage-threshold "${pdb_coverage_threshold}" \
    --seed "${seed}" \
    --test-0-size "${test_0_size}"
