#!/usr/bin/env bash
set -euo pipefail

# 最终汇总必须在相应数组任务完成后由用户显式提交。它重新扫描逐 PDB 正式产物，
# 不依赖分片报告中的局部统计，也不修改任何模型输入或向量。

if [[ $# -ne 2 ]]; then
    echo "用法: $0 {prepared|molformer|smi_ted_289m} {all_valid|all_existing}" >&2
    exit 2
fi
stage=$1
sample_scope=$2
if [[ "${stage}" != "prepared" && "${stage}" != "molformer" && "${stage}" != "smi_ted_289m" ]]; then
    echo "stage 必须是 prepared、molformer 或 smi_ted_289m" >&2
    exit 2
fi
if [[ "${sample_scope}" != "all_valid" && "${sample_scope}" != "all_existing" ]]; then
    echo "sample scope 必须是 all_valid 或 all_existing" >&2
    exit 2
fi

: "${TASK_PROJECT_ROOT:?训练与运行完整模式必须提供 TASK_PROJECT_ROOT}"
python_bin=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python
data_root=/storage/penghongen/AdaLigand/Ori_Data
catalog_root=${data_root}/stage1_preparation_box_pool_2
output_root=${catalog_root}/ligand_language_models

"${python_bin}" \
    "${TASK_PROJECT_ROOT}/Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/summarize_ligand_language_outputs.py" \
    --data-root "${data_root}" \
    --output-root "${output_root}" \
    --all-valid-path "${catalog_root}/all_valid.json" \
    --stage "${stage}" \
    --sample-scope "${sample_scope}"
