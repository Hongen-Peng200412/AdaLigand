#!/usr/bin/env bash
# 本入口只为 job 318350 验证 v1旧六条不变，并仅重跑 v2；绝不再次执行 v1。
set -euo pipefail

readonly expected_job_id="318350"
readonly expected_v1_run_id="adaligand_ag_20260711T154658_fsupp96_v1"
readonly expected_v2_run_id="adaligand_ag_20260711T154658_fsupp96_v2"
readonly expected_formal_run_id="adaligand_ag_20260711T154658"
readonly expected_formal_job_id="316116"
readonly expected_formal_node="cnode04"
readonly expected_formal_log="/storage/penghongen/AdaLigand/Ori_Data/logs/f/adaligand_f_316116.err"
readonly expected_v2_ids_file="/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_ag_20260711T154658_fsupp96_v2/stage_f_tail_supplement_20260716_v2/pdb_ids.txt"
readonly expected_v2_ids_sha256="7f427993c3a2e8c2e147e8c40b9b83423b932e2275066ccd010efbbf79617c6c"
readonly expected_v2_plan_file="/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_ag_20260711T154658_fsupp96_v2/stage_f_tail_supplement_20260716_v2/plan.json"
readonly expected_v2_plan_sha256="116084c321c60d8802780457d2cbad86dbb058e2001f7b7f5c3e820111f464fc"
readonly transition_script="${CODE_ROOT}/scripts/f_signal11_exclusion_transition.py"
readonly expected_transition_sha256="12495e5180ad1736270a554fcfecdb0c4e086bca93a0aab369e39d08f19ec7e6"
readonly supplement_guard_script="${CODE_ROOT}/scripts/f_supplement_guard.py"
readonly supplement_guard_module="${CODE_ROOT}/code/f_supplement_guard.py"
readonly process_probe_script="${CODE_ROOT}/scripts/stage_f_process_audit.py"
readonly process_probe_module="${CODE_ROOT}/code/stage_f_process_audit.py"
readonly expected_supplement_guard_script_sha256="7804e08a9009c680ff3a544d1a6f0fcd688c133a0ab4c29d6b7bd79180ebf1c0"
readonly expected_supplement_guard_module_sha256="7982adfb17939f472feb5748280b1dd1061daee2b3ca3a72832721fe974ed274"
readonly expected_process_probe_script_sha256="6cdb58ee925345f6037be263fccea1b7d2a09ee263f7863cd71bbe18ea6d3af3"
readonly expected_process_probe_module_sha256="0f4dfe186040d0b389a2377216a7465f1163444fe433dc6a7ddfe2ecae5510ce"
readonly expected_child_pgid_file="/home/penghongen/child_pgid_${expected_job_id}"

: "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID:?v2 run id is required}"
: "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE:?v2 frozen IDs file is required}"
: "${ADALIGAND_F_SUPPLEMENT_V2_IDS_SHA256:?v2 frozen IDs SHA-256 is required}"
: "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_FILE:?v2 frozen plan is required}"
: "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_SHA256:?v2 frozen plan SHA-256 is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID:?formal run id is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID:?formal job id is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG:?formal log is required}"
: "${ADALIGAND_EXTRA_KILL_PGID_FILE:?child PGID file is required}"

if [[ "${SLURM_JOB_ID:-}" != "${expected_job_id}" || \
      "${ADALIGAND_RUN_ID:-}" != "${expected_v1_run_id}" ]]; then
    echo "[ConfigError] signal-11 supplement resume identity drift"
    exit 64
fi
if [[ "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" != "${expected_v2_run_id}" || \
      "${F_N_JOBS:-12}" != "12" || "${SLURM_CPUS_PER_TASK:-}" != "96" ]]; then
    echo "[ConfigError] extended supplement recovery requires exact v2/CPU96/F12 identity"
    exit 64
fi
if [[ "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" != "${expected_formal_run_id}" || \
      "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID}" != "${expected_formal_job_id}" || \
      "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG}" != "${expected_formal_log}" || \
      "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE}" != "${expected_v2_ids_file}" || \
      "${ADALIGAND_F_SUPPLEMENT_V2_IDS_SHA256}" != "${expected_v2_ids_sha256}" || \
      "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_FILE}" != "${expected_v2_plan_file}" || \
      "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_SHA256}" != "${expected_v2_plan_sha256}" ]]; then
    echo "[ConfigError] frozen v2/formal supplement contract drift"
    exit 64
fi
if [[ "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" == "${ADALIGAND_RUN_ID}" || \
      "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" == "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" ]]; then
    echo "[ConfigError] v2 run id must remain independent from formal and v1"
    exit 64
fi
for path in \
  "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE}" \
  "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_FILE}"; do
    if [[ -L "${path}" || ! -f "${path}" || ! -s "${path}" ]]; then
        echo "[ConfigError] frozen v2 input must be a non-empty regular file: ${path}"
        exit 64
    fi
done
if [[ "$(sha256sum -- "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE}" | awk '{print $1}')" != \
      "${expected_v2_ids_sha256}" || \
      "$(sha256sum -- "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_FILE}" | awk '{print $1}')" != \
      "${expected_v2_plan_sha256}" ]]; then
    echo "[SafetyError] frozen v2 input content SHA-256 drift"
    exit 70
fi
for path in \
  "${transition_script}" \
  "${supplement_guard_script}" \
  "${supplement_guard_module}" \
  "${process_probe_script}" \
  "${process_probe_module}"; do
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
if [[ "$(sha256sum -- "${supplement_guard_script}" | awk '{print $1}')" != \
      "${expected_supplement_guard_script_sha256}" || \
      "$(sha256sum -- "${supplement_guard_module}" | awk '{print $1}')" != \
      "${expected_supplement_guard_module_sha256}" || \
      "$(sha256sum -- "${process_probe_script}" | awk '{print $1}')" != \
      "${expected_process_probe_script_sha256}" || \
      "$(sha256sum -- "${process_probe_module}" | awk '{print $1}')" != \
      "${expected_process_probe_module_sha256}" ]]; then
    echo "[SafetyError] formal-held guard implementation SHA-256 drift"
    exit 70
fi
if [[ "${ADALIGAND_EXTRA_KILL_PGID_FILE}" != "${expected_child_pgid_file}" ]]; then
    echo "[SafetyError] supplement child PGID path is not the exact Job 318350 path"
    exit 70
fi
if [[ ! -f "/home/penghongen/after_lock_${expected_job_id}" || \
      -L "/home/penghongen/after_lock_${expected_job_id}" || \
      -e "/home/penghongen/try_lock_${expected_job_id}" || \
      -L "/home/penghongen/try_lock_${expected_job_id}" || \
      -e "/home/penghongen/kill_lock_${expected_job_id}" || \
      -L "/home/penghongen/kill_lock_${expected_job_id}" || \
      -e "/home/penghongen/pre_lock_${expected_job_id}" || \
      -L "/home/penghongen/pre_lock_${expected_job_id}" ]]; then
    echo "[SafetyError] supplement lock state is not ready for signal-11 recovery"
    exit 70
fi

"${PYTHON}" "${transition_script}" --root "${DATA_ROOT}" --mode validate-extended
cd "${CODE_ROOT}"

readonly guard_evidence_dir="${DATA_ROOT}/reports/runs/${expected_v2_run_id}/f_supplement_guard"
readonly guard_started_ns="$(date +%s%N)"
readonly guard_attempt_id="job${SLURM_JOB_ID}.restart${SLURM_RESTART_COUNT:-0}.pid${BASHPID}.ns${guard_started_ns}"
readonly guard_marker="${guard_evidence_dir}/stop.formal_hold.${guard_attempt_id}.json"
readonly pre_gate_marker="${guard_evidence_dir}/stop.formal_hold.pre_gate.${guard_attempt_id}.json"
readonly -a formal_hold_args=(
  --formal_hold_node "${expected_formal_node}"
  --formal_hold_lock_root "/home/penghongen"
  --formal_hold_probe_timeout_seconds 30
)

v2_exit=0
if "${PYTHON}" "${supplement_guard_script}" \
  --plan "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_FILE}" \
  --ids "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE}" \
  --formal_run_id "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" \
  --supplement_run_id "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" \
  --formal_job_id "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID}" \
  --formal_log "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG}" \
  --stop_marker "${guard_marker}" \
  --child_pgid_file "${ADALIGAND_EXTRA_KILL_PGID_FILE}" \
  --n_jobs "${F_N_JOBS:-12}" \
  --poll_seconds 10 \
  --termination_grace_seconds 60 \
  "${formal_hold_args[@]}" \
  -- \
  "${PYTHON}" scripts/f_quality.py \
    --root "${DATA_ROOT}" \
    --chimera "${CHIMERA}" \
    --chimera_root "${CHIMERA_ROOT}" \
    --mapq_python "${PYTHON}" \
    --mapq_cmd "${MAPQ_CMD}" \
    --mapq_zip "${MAPQ_ZIP}" \
    --scratch_root "${SCRATCH_ROOT}" \
    --n_jobs "${F_N_JOBS:-12}" \
    --pdb_ids_file "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE}" \
    --run_id "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}"; then
    v2_exit=0
else
    v2_exit="$?"
fi

if [[ -L "${ADALIGAND_EXTRA_KILL_PGID_FILE}" ]]; then
    echo "[SafetyError] refusing symlink child PGID registration"
    exit 70
fi
if [[ -e "${ADALIGAND_EXTRA_KILL_PGID_FILE}" ]]; then
    "${PYTHON}" "${supplement_guard_script}" reap-child-group \
      --child_pgid_file "${ADALIGAND_EXTRA_KILL_PGID_FILE}" \
      --expected_child_pgid_file "${expected_child_pgid_file}" \
      --termination_grace_seconds 60
fi
if [[ -e "${ADALIGAND_EXTRA_KILL_PGID_FILE}" || \
      -L "${ADALIGAND_EXTRA_KILL_PGID_FILE}" ]]; then
    echo "[SafetyError] supplement child PGID survived exact reaping"
    exit 70
fi
if [[ "${v2_exit}" -eq 76 ]]; then
    "${PYTHON}" "${supplement_guard_script}" validate-marker \
      --plan "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_FILE}" \
      --ids "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE}" \
      --formal_run_id "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" \
      --supplement_run_id "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" \
      --formal_job_id "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID}" \
      --formal_log "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG}" \
      --stop_marker "${guard_marker}" \
      --n_jobs "${F_N_JOBS:-12}" \
      "${formal_hold_args[@]}"
    echo "[SupplementPhase2] formal hold drift; v2 stopped with immutable evidence"
    exit 76
fi
if [[ "${v2_exit}" -eq 75 ]]; then
    echo "[SafetyError] formal-held mode returned legacy collision exit 75"
    exit 70
fi
if [[ "${v2_exit}" -ne 0 ]]; then
    exit "${v2_exit}"
fi

pre_gate_exit=0
if "${PYTHON}" "${supplement_guard_script}" check-formal-hold \
  --plan "${ADALIGAND_F_SUPPLEMENT_V2_PLAN_FILE}" \
  --ids "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE}" \
  --formal_run_id "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" \
  --supplement_run_id "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" \
  --formal_job_id "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID}" \
  --formal_log "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG}" \
  --stop_marker "${pre_gate_marker}" \
  --n_jobs "${F_N_JOBS:-12}" \
  "${formal_hold_args[@]}"; then
    pre_gate_exit=0
else
    pre_gate_exit="$?"
fi
if [[ "${pre_gate_exit}" -eq 76 ]]; then
    echo "[SupplementPhase2] formal hold drift before release gate"
    exit 76
fi
if [[ "${pre_gate_exit}" -ne 0 ]]; then
    exit "${pre_gate_exit}"
fi

gate_exit=0
if "${PYTHON}" scripts/stage_release_gate.py \
  --root "${DATA_ROOT}" \
  --run_id "${ADALIGAND_F_SUPPLEMENT_V2_RUN_ID}" \
  --stages stage_f \
  --gate_name f_supplement_release \
  --pdb_ids_file "${ADALIGAND_F_SUPPLEMENT_V2_IDS_FILE}"; then
    gate_exit=0
else
    gate_exit="$?"
fi
if [[ "${gate_exit}" -eq 75 || "${gate_exit}" -eq 76 ]]; then
    echo "[SafetyError] release gate used a reserved supplement guard exit code"
    exit 70
fi
exit "${gate_exit}"
