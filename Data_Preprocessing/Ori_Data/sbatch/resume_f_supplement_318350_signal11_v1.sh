#!/usr/bin/env bash
# 本入口只为 job 318350 在真实重跑 v1/v2 前验证六条 signal-11 run-scoped manifest。
set -euo pipefail

readonly expected_job_id="318350"
readonly expected_v1_run_id="adaligand_ag_20260711T154658_fsupp96_v1"
readonly transition_script="${CODE_ROOT}/scripts/f_signal11_exclusion_transition.py"
readonly expected_transition_sha256="8e2e1346b7c35452d4058c4a7c59faa116f80446982540332f0cae2a8ddba489"
readonly delegate="${CODE_ROOT}/sbatch/resume_f_supplement_318350_accel_v2.sh"
readonly expected_delegate_sha256="4ccd573bdfe6dfe264029e959cafb97dc18a96fb4db9a376f1a16ee364f083bd"

if [[ "${SLURM_JOB_ID:-}" != "${expected_job_id}" || \
      "${ADALIGAND_RUN_ID:-}" != "${expected_v1_run_id}" ]]; then
    echo "[ConfigError] signal-11 supplement resume identity drift"
    exit 64
fi
for path in "${transition_script}" "${delegate}"; do
    if [[ -L "${path}" || ! -f "${path}" ]]; then
        echo "[ConfigError] signal-11 resume dependency must be a regular file: ${path}"
        exit 64
    fi
done
if [[ "$(sha256sum -- "${transition_script}" | awk '{print $1}')" != \
      "${expected_transition_sha256}" ]]; then
    echo "[SafetyError] signal-11 transition SHA-256 drift"
    exit 70
fi
if [[ "$(sha256sum -- "${delegate}" | awk '{print $1}')" != \
      "${expected_delegate_sha256}" ]]; then
    echo "[SafetyError] existing supplement delegate SHA-256 drift"
    exit 70
fi
if [[ ! -f "/home/penghongen/after_lock_${expected_job_id}" || \
      -L "/home/penghongen/after_lock_${expected_job_id}" || \
      -e "/home/penghongen/try_lock_${expected_job_id}" || \
      -e "/home/penghongen/kill_lock_${expected_job_id}" ]]; then
    echo "[SafetyError] supplement lock state is not ready for signal-11 recovery"
    exit 70
fi

"${PYTHON}" "${transition_script}" --root "${DATA_ROOT}" --mode validate
exec bash "${delegate}"
