#!/usr/bin/env bash

# 为 Find_1 CryoAtom2 受体实验生成 calibration 与 test_0 的长期 Ori_Data 视图.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd -P)"
ADAPTER_ROOT="${PROJECT_ROOT}/测评数据代码/cryoatom2_受体Adapter"
REFERENCE_ROOT="/storage/penghongen/AdaLigand/Ori_Data"
CHIMERA="/home/penghongen/.local/opt/UCSF-Chimera64-1.19/bin/chimera"
RUN_STAMP="${TASK_RUN_STAMP:?TASK_RUN_STAMP 未设置}"
export PYTHONPATH="${PROJECT_ROOT}/Data_Preprocessing/Ori_Data"
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python "${ADAPTER_ROOT}/run.py" \
    --split-file "${REFERENCE_ROOT}/stage1_preparation_box_pool_3/split/pdb_split/calibration.json" \
    --cryoatom2-root "/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration" \
    --reference-root "${REFERENCE_ROOT}" \
    --output-root "/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/Ori_Data" \
    --scratch-root "/storage/penghongen/tmp/find1_cryoatom2_receptor_adapter/${RUN_STAMP}/calibration" \
    --chimera "${CHIMERA}" \
    --workers 32 \
    --timeout-seconds 3600

python "${ADAPTER_ROOT}/run.py" \
    --split-file "/storage/penghongen/AdaLigand/held_out/split/held_out_06_chain/test_0.json" \
    --cryoatom2-root "/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06" \
    --reference-root "${REFERENCE_ROOT}" \
    --output-root "/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/Ori_Data" \
    --scratch-root "/storage/penghongen/tmp/find1_cryoatom2_receptor_adapter/${RUN_STAMP}/test_0" \
    --chimera "${CHIMERA}" \
    --workers 32 \
    --timeout-seconds 3600
