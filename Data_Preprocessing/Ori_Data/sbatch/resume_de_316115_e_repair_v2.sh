#!/usr/bin/env bash
set -euo pipefail

# 仅在独立 48 CPU 补足作业完成并发布受检 marker 后，刷新正式 Stage E 状态。
# 8ckb 不再走单样本私有修复；它由本次 run 的 exclusion manifest 记为稳定 known failure。
FORMAL="adaligand_ag_20260711T154658"
SUPPLEMENT="adaligand_ag_20260711T154658_eeng_supp48_v2"
DATA_ROOT="${DATA_ROOT:-/storage/penghongen/AdaLigand/Ori_Data}"
CODE_ROOT="${CODE_ROOT:-/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data}"
PYTHON="${PYTHON:-/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python}"
CHIMERA="${CHIMERA:-/home/penghongen/.local/opt/UCSF-Chimera64-1.19/bin/chimera}"
SCRATCH_ROOT="${SCRATCH_ROOT:-${DATA_ROOT}/scratch}"

FORMAL_STAGE_D_STATUS="${DATA_ROOT}/reports/runs/${FORMAL}/stage_d/status.part_0000_of_0001.jsonl"
FORMAL_STAGE_E_STATUS="${DATA_ROOT}/reports/runs/${FORMAL}/stage_e/status.part_0000_of_0001.jsonl"
EXCLUSIONS="${DATA_ROOT}/reports/runs/${FORMAL}/exclusions.jsonl"
SUPPLEMENT_IDS="${DATA_ROOT}/reports/runs/${FORMAL}/stage_e_repair_parallel_v2/ids_supp48.txt"
SUPPLEMENT_STATUS="${DATA_ROOT}/reports/runs/${SUPPLEMENT}/stage_e/status.part_0000_of_0001.jsonl"
SUPPLEMENT_GATE="${DATA_ROOT}/reports/runs/${SUPPLEMENT}/e_supp48_release/summary.json"
SUPPLEMENT_RELEASE="/home/penghongen/e_repair_supp48_v2_release_316115"

EXPECTED_STAGE_D_SHA="263fa2af81198e686616d2c8b1022a32668a689a6a74438d72c6e294662d5e9f"
INITIAL_STAGE_E_SHA="b03b7c72a00730f5fc0bb56b718f0f7f5a7313f11212fbc034fc74f4a6a6c7b0"
EXPECTED_EXCLUSIONS_SHA="b586cab20644c3cc8fb1f4e0eaa7eead4cff0d496a862c2313b5e0c1847257fe"
EXPECTED_SUPPLEMENT_IDS_SHA="21c14b03565807d5d52f59561ee771c84dd0c0042f56794f801c1ae7bd838366"

require_regular_file() {
    local path="$1"
    [[ -f "${path}" && ! -L "${path}" ]]
}

require_sha256() {
    local path="$1"
    local expected="$2"
    require_regular_file "${path}"
    [[ "$(sha256sum "${path}" | awk '{print $1}')" == "${expected}" ]]
}

cd "${CODE_ROOT}"

# 冻结正式 D/E 输入、run-scoped 排除决定以及独立补足样本集合。
require_sha256 "${FORMAL_STAGE_D_STATUS}" "${EXPECTED_STAGE_D_SHA}"
require_sha256 "${FORMAL_STAGE_E_STATUS}" "${INITIAL_STAGE_E_SHA}"
require_sha256 "${EXCLUSIONS}" "${EXPECTED_EXCLUSIONS_SHA}"
require_sha256 "${SUPPLEMENT_IDS}" "${EXPECTED_SUPPLEMENT_IDS_SHA}"
[[ "$(wc -l <"${SUPPLEMENT_IDS}")" -eq 6 ]]

# marker 只能由既有 job 316415 在 6/6 strict success gate 后原子发布。
require_regular_file "${SUPPLEMENT_RELEASE}"
require_regular_file "${SUPPLEMENT_STATUS}"
require_regular_file "${SUPPLEMENT_GATE}"
[[ "$(wc -l <"${SUPPLEMENT_STATUS}")" -eq 6 ]]
supplement_status_sha="$(sha256sum "${SUPPLEMENT_STATUS}" | awk '{print $1}')"
supplement_gate_sha="$(sha256sum "${SUPPLEMENT_GATE}" | awk '{print $1}')"
grep -Fxq "formal_job=316115" "${SUPPLEMENT_RELEASE}"
grep -Fxq "supplement_job=316415" "${SUPPLEMENT_RELEASE}"
grep -Fxq "run_id=${SUPPLEMENT}" "${SUPPLEMENT_RELEASE}"
grep -Fxq "ids_sha256=${EXPECTED_SUPPLEMENT_IDS_SHA}" "${SUPPLEMENT_RELEASE}"
grep -Fxq "status_sha256=${supplement_status_sha}" "${SUPPLEMENT_RELEASE}"
grep -Fxq "gate_sha256=${supplement_gate_sha}" "${SUPPLEMENT_RELEASE}"
grep -Eq '^completed_at=[^[:space:]]+$' "${SUPPLEMENT_RELEASE}"
[[ "$(wc -l <"${SUPPLEMENT_RELEASE}")" -eq 7 ]]

# exclusion manifest 必须仍由公共加载器解释为仅覆盖本 run 的 E/F 8ckb 排除。
PYTHONPATH="${CODE_ROOT}/code" "${PYTHON}" - "${DATA_ROOT}" "${FORMAL}" "${EXPECTED_EXCLUSIONS_SHA}" <<'PY'
from pathlib import Path
import sys

from exclusions import load_run_exclusions

root = Path(sys.argv[1])
run_id = sys.argv[2]
expected_sha = sys.argv[3]
for stage in ("stage_e", "stage_f"):
    records, manifest_sha = load_run_exclusions(root, run_id, stage)
    assert set(records) == {"8ckb"}
    assert manifest_sha == expected_sha
    assert records["8ckb"]["downstream_policy"] == "exclude_from_training_and_inference"
PY

# 专用分块路线未产生正式模拟密度；8ckb 将由正式 E 写为 run_policy_excluded。
[[ ! -e "${DATA_ROOT}/density/8ckb/sim.npz" ]]

# 公共 artifact 已由标准 Chimera 补齐后，只刷新一次正式 22,386 行 E 状态。
# 不带过滤、不 overwrite：已有合格 artifact 只做验证和复用，排除项保留完整 provenance。
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
