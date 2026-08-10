#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "用法: $0 {all_valid|all_existing}" >&2
    exit 2
fi
sample_scope=$1
if [[ "${sample_scope}" != "all_valid" && "${sample_scope}" != "all_existing" ]]; then
    echo "sample scope 必须是 all_valid 或 all_existing" >&2
    exit 2
fi

: "${TASK_PROJECT_ROOT:?训练与运行完整模式必须提供 TASK_PROJECT_ROOT}"
python_bin=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python
data_root=/storage/penghongen/AdaLigand/Ori_Data
catalog_root=${data_root}/stage1_preparation_box_pool_2
workers=${SLURM_CPUS_PER_TASK:-1}

"${python_bin}" \
    "${TASK_PROJECT_ROOT}/Data_Preprocessing/Ori_Data_upgrade/upgrade_ligand_area_masks.py" \
    --root "${data_root}" \
    --sample-scope "${sample_scope}" \
    --all-valid "${catalog_root}/all_valid.json" \
    --workers "${workers}"
