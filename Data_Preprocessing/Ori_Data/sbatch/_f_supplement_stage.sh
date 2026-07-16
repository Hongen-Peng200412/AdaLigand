#!/usr/bin/env bash
# Stage F 独立补算的单阶段共享实现；调用方负责决定 guard=75 的整体退出语义。

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "[ConfigError] _f_supplement_stage.sh must be sourced"
    exit 64
fi

run_adaligand_f_supplement_stage() {
    local supplement_run_id="${1:?supplement run id is required}"
    local ids_file="${2:?frozen PDB id file is required}"
    local ids_sha256="${3:?frozen PDB id SHA-256 is required}"
    local plan_file="${4:?frozen plan file is required}"
    local plan_sha256="${5:?frozen plan SHA-256 is required}"
    local formal_run_id="${6:?formal run id is required}"
    local formal_job_id="${7:?formal Slurm Job ID is required}"
    local formal_log="${8:?formal Stage F stderr log is required}"
    local supplement_n_jobs="${9:?supplement n_jobs is required}"
    local child_pgid_file="${10:?child PGID file is required}"

    : "${DATA_ROOT:?data root is required}"
    : "${PYTHON:?python is required}"
    : "${CHIMERA:?Chimera executable is required}"
    : "${CHIMERA_ROOT:?Chimera root is required}"
    : "${MAPQ_CMD:?MapQ command is required}"
    : "${MAPQ_ZIP:?MapQ archive is required}"
    : "${SCRATCH_ROOT:?scratch root is required}"

    # CPU96 上保持 12 个 PDB 外层 worker；MapQ 内部 np=8 由质量代码与 plan 双重冻结。
    if [[ "${supplement_n_jobs}" != "12" ]]; then
        echo "[ConfigError] CPU96 supplement requires F_N_JOBS=12"
        return 64
    fi
    if [[ "${SLURM_CPUS_PER_TASK:-}" != "96" ]]; then
        echo "[ConfigError] supplement allocation must expose exactly 96 CPUs"
        return 64
    fi
    if [[ "${supplement_run_id}" == "${formal_run_id}" ]]; then
        echo "[ConfigError] supplement run id must differ from formal run id"
        return 64
    fi
    for path in "${ids_file}" "${plan_file}"; do
        if [[ -L "${path}" || ! -f "${path}" || ! -s "${path}" ]]; then
            echo "[ConfigError] frozen supplement input must be a non-empty regular file: ${path}"
            return 64
        fi
    done
    if [[ -L "${child_pgid_file}" || -e "${child_pgid_file}" ]]; then
        echo "[ConfigError] refusing stale supplement child PGID file: ${child_pgid_file}"
        return 64
    fi

    local ids_digest_line=""
    local plan_digest_line=""
    local actual_ids_sha256=""
    local actual_plan_sha256=""
    if ! ids_digest_line="$(sha256sum -- "${ids_file}")"; then
        echo "[SafetyError] failed to hash supplement PDB id file"
        return 70
    fi
    if ! plan_digest_line="$(sha256sum -- "${plan_file}")"; then
        echo "[SafetyError] failed to hash supplement plan"
        return 70
    fi
    actual_ids_sha256="${ids_digest_line%% *}"
    actual_plan_sha256="${plan_digest_line%% *}"
    if [[ "${actual_ids_sha256}" != "${ids_sha256}" ]]; then
        echo "[ConfigError] supplement PDB id SHA-256 drift"
        return 64
    fi
    if [[ "${actual_plan_sha256}" != "${plan_sha256}" ]]; then
        echo "[ConfigError] supplement plan SHA-256 drift"
        return 64
    fi
    echo "[Supplement] formal_run=${formal_run_id} supplement_run=${supplement_run_id}"
    echo "[Supplement] ids_sha256=${actual_ids_sha256} plan_sha256=${actual_plan_sha256}"

    local guard_marker="${DATA_ROOT}/reports/runs/${supplement_run_id}/f_supplement_guard/stop.json"
    local guard_exit=0
    if "${PYTHON}" scripts/f_supplement_guard.py \
      --plan "${plan_file}" \
      --ids "${ids_file}" \
      --formal_run_id "${formal_run_id}" \
      --supplement_run_id "${supplement_run_id}" \
      --formal_job_id "${formal_job_id}" \
      --formal_log "${formal_log}" \
      --stop_marker "${guard_marker}" \
      --child_pgid_file "${child_pgid_file}" \
      --n_jobs "${supplement_n_jobs}" \
      -- \
      "${PYTHON}" scripts/f_quality.py \
        --root "${DATA_ROOT}" \
        --chimera "${CHIMERA}" \
        --chimera_root "${CHIMERA_ROOT}" \
        --mapq_python "${PYTHON}" \
        --mapq_cmd "${MAPQ_CMD}" \
        --mapq_zip "${MAPQ_ZIP}" \
        --scratch_root "${SCRATCH_ROOT}" \
        --n_jobs "${supplement_n_jobs}" \
        --pdb_ids_file "${ids_file}" \
        --run_id "${supplement_run_id}"; then
        guard_exit=0
    else
        guard_exit="$?"
    fi

    # guard 被 SIGKILL 或内部清理失败时，使用同一受检实现按精确 PGID 兜底回收。
    if [[ -L "${child_pgid_file}" ]]; then
        echo "[SafetyError] refusing symlink child PGID registration: ${child_pgid_file}"
        return 70
    fi
    if [[ -e "${child_pgid_file}" ]]; then
        local reaper_exit=0
        if "${PYTHON}" scripts/f_supplement_guard.py reap-child-group \
          --child_pgid_file "${child_pgid_file}" \
          --expected_child_pgid_file "${child_pgid_file}" \
          --termination_grace_seconds 60; then
            reaper_exit=0
        else
            reaper_exit="$?"
        fi
        if [[ "${reaper_exit}" -ne 0 ]]; then
            echo "[SafetyError] failed to reap registered supplement child process group"
            return 70
        fi
    fi
    if [[ -L "${child_pgid_file}" || -e "${child_pgid_file}" ]]; then
        echo "[SafetyError] supplement child PGID registration survived verified reaping"
        return 70
    fi
    if [[ "${guard_exit}" -eq 75 ]]; then
        local marker_validation_exit=0
        if "${PYTHON}" scripts/f_supplement_guard.py validate-marker \
          --plan "${plan_file}" \
          --ids "${ids_file}" \
          --formal_run_id "${formal_run_id}" \
          --supplement_run_id "${supplement_run_id}" \
          --formal_job_id "${formal_job_id}" \
          --formal_log "${formal_log}" \
          --stop_marker "${guard_marker}" \
          --n_jobs "${supplement_n_jobs}"; then
            marker_validation_exit=0
        else
            marker_validation_exit="$?"
        fi
        if [[ "${marker_validation_exit}" -ne 0 ]]; then
            echo "[SafetyError] reserved guard exit 75 lacks an authentic stop marker"
            return 70
        fi
        echo "[SupplementGuard] stopped before collision; marker=${guard_marker}"
        return 75
    fi
    if [[ "${guard_exit}" -ne 0 ]]; then
        return "${guard_exit}"
    fi

    local gate_exit=0
    if "${PYTHON}" scripts/stage_release_gate.py \
      --root "${DATA_ROOT}" \
      --run_id "${supplement_run_id}" \
      --stages stage_f \
      --gate_name f_supplement_release \
      --pdb_ids_file "${ids_file}"; then
        gate_exit=0
    else
        gate_exit="$?"
    fi
    if [[ "${gate_exit}" -eq 75 ]]; then
        echo "[SafetyError] release gate used reserved collision-guard exit code 75"
        return 70
    fi
    return "${gate_exit}"
}
