#!/usr/bin/env bash
# 本入口只在六条 signal-11 决策已闭合后恢复正式 F；不会创建占位质量三件套。
set -euo pipefail

: "${ADALIGAND_SIGNAL11_SUPPLEMENT_RUN_CMD_SHA256:?trusted supplement run_cmd SHA-256 is required}"

readonly formal_run_id="adaligand_ag_20260711T154658"
readonly formal_job_id="316116"
readonly transition_script="${CODE_ROOT}/scripts/f_signal11_exclusion_transition.py"
readonly expected_transition_sha256="8e2e1346b7c35452d4058c4a7c59faa116f80446982540332f0cae2a8ddba489"

if [[ "${SLURM_JOB_ID:-}" != "${formal_job_id}" || \
      "${ADALIGAND_RUN_ID:-}" != "${formal_run_id}" ]]; then
    echo "[ConfigError] signal-11 formal resume identity drift"
    exit 64
fi
if [[ "${F_N_JOBS:-12}" != "12" || "${SLURM_CPUS_PER_TASK:-}" != "96" ]]; then
    echo "[ConfigError] formal signal-11 recovery requires CPU96 and F_N_JOBS=12"
    exit 64
fi
if [[ -L "${transition_script}" || ! -f "${transition_script}" ]]; then
    echo "[ConfigError] signal-11 transition script must be a regular file"
    exit 64
fi
if [[ "$(sha256sum -- "${transition_script}" | awk '{print $1}')" != \
      "${expected_transition_sha256}" ]]; then
    echo "[SafetyError] signal-11 transition SHA-256 drift"
    exit 70
fi
if [[ ! -f "/home/penghongen/after_lock_${formal_job_id}" || \
      -L "/home/penghongen/after_lock_${formal_job_id}" || \
      -e "/home/penghongen/try_lock_${formal_job_id}" || \
      -e "/home/penghongen/kill_lock_${formal_job_id}" ]]; then
    echo "[SafetyError] formal lock state is not ready for signal-11 recovery"
    exit 70
fi

"${PYTHON}" "${transition_script}" \
    --root "${DATA_ROOT}" \
    --mode readiness \
    --expected_supplement_run_cmd_sha256 \
      "${ADALIGAND_SIGNAL11_SUPPLEMENT_RUN_CMD_SHA256}"
cd "${CODE_ROOT}"

"${PYTHON}" scripts/f_quality.py \
    --root "${DATA_ROOT}" \
    --chimera "${CHIMERA}" \
    --chimera_root "${CHIMERA_ROOT}" \
    --mapq_python "${PYTHON}" \
    --mapq_cmd "${MAPQ_CMD}" \
    --mapq_zip "${MAPQ_ZIP}" \
    --scratch_root "${SCRATCH_ROOT}" \
    --n_jobs "${F_N_JOBS:-12}" \
    --run_id "${formal_run_id}"

"${PYTHON}" scripts/stage_release_gate.py \
    --root "${DATA_ROOT}" \
    --run_id "${formal_run_id}" \
    --stages stage_f \
    --gate_name f_release
