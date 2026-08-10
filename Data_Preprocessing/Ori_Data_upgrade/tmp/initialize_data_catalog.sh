#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "用法: $0 DATA_ROOT CATALOG_ROOT" >&2
    exit 2
fi

: "${TASK_PROJECT_ROOT:?训练与运行完整模式必须提供 TASK_PROJECT_ROOT}"
python_bin=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python
data_root=$1
catalog_root=$2
script_root=${TASK_PROJECT_ROOT}/Data_Preprocessing/Ori_Data_upgrade/tmp

"${python_bin}" \
    "${script_root}/initialize_data_catalog.py" \
    --data-root "${data_root}" \
    --catalog-root "${catalog_root}" \
    --reasons "${script_root}/initial_info_reasons.json"
