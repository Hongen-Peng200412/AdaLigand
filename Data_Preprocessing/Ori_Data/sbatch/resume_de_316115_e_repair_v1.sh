#!/usr/bin/env bash
set -euo pipefail

# 只恢复正式 job 316115 已取证的 18 个 Stage E 工程失败；2zhc 的坐标系
# 不相交仍由正式 gate 阻断，等待显式科学数据契约决定。
FORMAL="adaligand_ag_20260711T154658"
REPAIR="adaligand_ag_20260711T154658_eeng_v1"
DATA_ROOT="${DATA_ROOT:-/storage/penghongen/AdaLigand/Ori_Data}"
CODE_ROOT="${CODE_ROOT:-/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data}"
PYTHON="${PYTHON:-/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python}"
CHIMERA="${CHIMERA:-/home/penghongen/.local/opt/UCSF-Chimera64-1.19/bin/chimera}"
SCRATCH_ROOT="${SCRATCH_ROOT:-${DATA_ROOT}/scratch}"

FORMAL_STAGE_D_STATUS="${DATA_ROOT}/reports/runs/${FORMAL}/stage_d/status.part_0000_of_0001.jsonl"
FORMAL_STAGE_E_STATUS="${DATA_ROOT}/reports/runs/${FORMAL}/stage_e/status.part_0000_of_0001.jsonl"
REPAIR_STAGE_E_STATUS="${DATA_ROOT}/reports/runs/${REPAIR}/stage_e/status.part_0000_of_0001.jsonl"
IDS_DIR="${DATA_ROOT}/reports/runs/${FORMAL}/stage_e_repair"
IDS_FILE="${IDS_DIR}/engineering_unknown_ids_v1.txt"

EXPECTED_STAGE_D_SHA="263fa2af81198e686616d2c8b1022a32668a689a6a74438d72c6e294662d5e9f"
INITIAL_STAGE_E_SHA="b03b7c72a00730f5fc0bb56b718f0f7f5a7313f11212fbc034fc74f4a6a6c7b0"
EXPECTED_IDS_SHA="6f9bea3a9448f8f24940d3241520633890aefad88d737fad0580f47ff0b280be"

cd "${CODE_ROOT}"

mkdir -p "${IDS_DIR}"
if [[ ! -e "${IDS_FILE}" ]]; then
    tmp_ids="${IDS_FILE}.tmp.$$"
    printf '%s\n' \
        7y7a 8bhf 8bpo 8ckb 8glv 8j07 \
        8ro0 8ro1 8ro2 8vvt 8vvv \
        9dp7 9e5c 9fqr 9qqp 9qsa 9qwt 9y6s >"${tmp_ids}"
    chmod 0644 "${tmp_ids}"
    mv -f -- "${tmp_ids}" "${IDS_FILE}"
fi
[[ -f "${IDS_FILE}" && ! -L "${IDS_FILE}" ]]
[[ "$(wc -l <"${IDS_FILE}")" -eq 18 ]]
[[ "$(sha256sum "${IDS_FILE}" | awk '{print $1}')" == "${EXPECTED_IDS_SHA}" ]]
[[ "$(sha256sum "${FORMAL_STAGE_D_STATUS}" | awk '{print $1}')" == "${EXPECTED_STAGE_D_SHA}" ]]

if [[ ! -e "${REPAIR_STAGE_E_STATUS}" ]]; then
    # 第一次工程恢复必须从已冻结的 19-unknown 正式状态开始；不能消费漂移后的证据。
    [[ "$(sha256sum "${FORMAL_STAGE_E_STATUS}" | awk '{print $1}')" == "${INITIAL_STAGE_E_SHA}" ]]
    "${PYTHON}" scripts/e_density.py \
        --root "${DATA_ROOT}" \
        --chimera "${CHIMERA}" \
        --scratch_root "${SCRATCH_ROOT}" \
        --n_jobs 2 \
        --timeout_seconds 21600 \
        --pdb_ids_file "${IDS_FILE}" \
        --run_id "${REPAIR}"
fi

# repair run 必须严格 18/18 success-or-skipped；失败证据不覆盖，需新 run id 才能再试。
"${PYTHON}" scripts/stage_release_gate.py \
    --root "${DATA_ROOT}" \
    --run_id "${REPAIR}" \
    --stages stage_e \
    --gate_name e_engineering_release \
    --pdb_ids_file "${IDS_FILE}" \
    --require_success

# 公共 artifact 补齐后，用正式 run id 无过滤、无 overwrite 重写 22,386 行状态。
# 当前若仅剩 2zhc frame mismatch，下面的正式 D/E gate 会继续非零退出并保留 allocation。
"${PYTHON}" scripts/e_density.py \
    --root "${DATA_ROOT}" \
    --chimera "${CHIMERA}" \
    --scratch_root "${SCRATCH_ROOT}" \
    --n_jobs 24 \
    --timeout_seconds 21600 \
    --run_id "${FORMAL}"

"${PYTHON}" scripts/stage_release_gate.py \
    --root "${DATA_ROOT}" \
    --run_id "${FORMAL}" \
    --stages stage_d,stage_e \
    --gate_name de_release
