#!/usr/bin/env bash
# 在既有 318350 allocation 内顺序完成 v1，再用互斥的 v2 尾段继续加速正式 Stage F。

set -euo pipefail
cd "${CODE_ROOT}"

: "${ADALIGAND_RUN_ID:?existing v1 supplement run id is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID:?formal run id is required}"
: "${ADALIGAND_F_SUPPLEMENT_IDS_FILE:?v1 frozen PDB id file is required}"
: "${ADALIGAND_F_SUPPLEMENT_IDS_SHA256:?v1 frozen PDB id SHA-256 is required}"
: "${ADALIGAND_F_SUPPLEMENT_PLAN_FILE:?v1 frozen plan file is required}"
: "${ADALIGAND_F_SUPPLEMENT_PLAN_SHA256:?v1 frozen plan SHA-256 is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID:?formal Slurm Job ID is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG:?formal Stage F stderr log is required}"
: "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID:?v2 supplement run id is required}"
: "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE:?v2 frozen PDB id file is required}"
: "${ADALIGAND_F_SUPPLEMENT_V2_IDS_SHA256:?v2 frozen PDB id SHA-256 is required}"
: "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_FILE:?v2 frozen plan file is required}"
: "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_SHA256:?v2 frozen plan SHA-256 is required}"
: "${ADALIGAND_EXTRA_KILL_PGID_FILE:?shared child PGID file is required}"

readonly expected_supplement_job_id="318350"
readonly expected_v1_run_id="adaligand_ag_20260711T154658_fsupp96_v1"
readonly expected_v2_run_id="adaligand_ag_20260711T154658_fsupp96_v2"
readonly expected_formal_run_id="adaligand_ag_20260711T154658"
readonly expected_formal_job_id="316116"
readonly expected_formal_log="/storage/penghongen/AdaLigand/Ori_Data/logs/f/adaligand_f_316116.err"

if [[ "${SLURM_JOB_ID:-}" != "${expected_supplement_job_id}" ]]; then
    echo "[ConfigError] acceleration wrapper is bound to job ${expected_supplement_job_id}"
    exit 64
fi
if [[ "${ADALIGAND_RUN_ID}" != "${expected_v1_run_id}" ]]; then
    echo "[ConfigError] existing supplement run identity drift"
    exit 64
fi
if [[ "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" != "${expected_v2_run_id}" ]]; then
    echo "[ConfigError] v2 supplement run identity drift"
    exit 64
fi
if [[ "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" != "${expected_formal_run_id}" || \
      "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID}" != "${expected_formal_job_id}" || \
      "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG}" != "${expected_formal_log}" ]]; then
    echo "[ConfigError] formal Stage F run/job/log identity drift"
    exit 64
fi
if [[ "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" == "${ADALIGAND_RUN_ID}" || \
      "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" == "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" ]]; then
    echo "[ConfigError] v2 run id must be independent from formal and v1 runs"
    exit 64
fi

readonly expected_supplement_helper_sha256="c9cc8b590c6564c7a45da770959359cc1f5754bf7c7e616a28bbafd148887f50"
readonly supplement_helper_path="${CODE_ROOT}/sbatch/_f_supplement_stage.sh"
if [[ -L "${supplement_helper_path}" || ! -f "${supplement_helper_path}" ]]; then
    echo "[ConfigError] supplement helper must be a regular non-symlink file"
    exit 64
fi
helper_digest_line=""
if ! helper_digest_line="$(sha256sum -- "${supplement_helper_path}")"; then
    echo "[SafetyError] failed to hash supplement helper"
    exit 70
fi
actual_supplement_helper_sha256="${helper_digest_line%% *}"
if [[ "${actual_supplement_helper_sha256}" != "${expected_supplement_helper_sha256}" ]]; then
    echo "[SafetyError] supplement helper SHA-256 drift"
    exit 70
fi
source "${supplement_helper_path}"
supplement_n_jobs="${F_N_JOBS:-12}"

v1_exit=0
if run_adaligand_f_supplement_stage \
  "${ADALIGAND_RUN_ID}" \
  "${ADALIGAND_F_SUPPLEMENT_IDS_FILE}" \
  "${ADALIGAND_F_SUPPLEMENT_IDS_SHA256}" \
  "${ADALIGAND_F_SUPPLEMENT_PLAN_FILE}" \
  "${ADALIGAND_F_SUPPLEMENT_PLAN_SHA256}" \
  "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" \
  "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID}" \
  "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG}" \
  "${supplement_n_jobs}" \
  "${ADALIGAND_EXTRA_KILL_PGID_FILE}"; then
    v1_exit=0
else
    v1_exit="$?"
fi
if [[ "${v1_exit}" -eq 75 ]]; then
    echo "[SupplementAccel] v1 guard stopped; v2 will not start"
    exit 0
fi
if [[ "${v1_exit}" -ne 0 ]]; then
    exit "${v1_exit}"
fi
echo "[SupplementAccel] v1 gate passed; starting independent v2"

v2_exit=0
if run_adaligand_f_supplement_stage \
  "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" \
  "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE}" \
  "${ADALIGAND_F_SUPPLEMENT_V2_IDS_SHA256}" \
  "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_FILE}" \
  "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_SHA256}" \
  "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" \
  "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID}" \
  "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG}" \
  "${supplement_n_jobs}" \
  "${ADALIGAND_EXTRA_KILL_PGID_FILE}"; then
    v2_exit=0
else
    v2_exit="$?"
fi
if [[ "${v2_exit}" -eq 75 ]]; then
    echo "[SupplementAccel] v2 guard stopped; no later segment will start"
    exit 0
fi
exit "${v2_exit}"
