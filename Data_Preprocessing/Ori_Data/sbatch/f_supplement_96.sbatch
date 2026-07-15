#!/usr/bin/env bash
#SBATCH --job-name=adaligand_f_supp96
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/f/%x_%j.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/f/%x_%j.err
#SBATCH --partition=cpu
#SBATCH --qos=Cpu96
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=96

set -u
export ADALIGAND_EXTRA_KILL_PGID_FILE="/home/penghongen/child_pgid_${SLURM_JOB_ID}"

write_adaligand_run_cmd() {
    local output_path="$1"
    cat >"${output_path}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "${CODE_ROOT}"

: "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID:?formal run id is required}"
: "${ADALIGAND_F_SUPPLEMENT_IDS_FILE:?frozen PDB id file is required}"
: "${ADALIGAND_F_SUPPLEMENT_IDS_SHA256:?frozen PDB id SHA-256 is required}"
: "${ADALIGAND_F_SUPPLEMENT_PLAN_FILE:?frozen plan file is required}"
: "${ADALIGAND_F_SUPPLEMENT_PLAN_SHA256:?frozen plan SHA-256 is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID:?formal Slurm Job ID is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG:?formal Stage F stderr log is required}"

supplement_n_jobs="${F_N_JOBS:-12}"
if [[ "${supplement_n_jobs}" != "12" ]]; then
    echo "[ConfigError] CPU96 supplement requires F_N_JOBS=12"
    exit 64
fi
if [[ "${SLURM_CPUS_PER_TASK:-}" != "96" ]]; then
    echo "[ConfigError] supplement allocation must expose exactly 96 CPUs"
    exit 64
fi

if [[ "${ADALIGAND_RUN_ID}" == "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" ]]; then
    echo "[ConfigError] supplement run id must differ from formal run id"
    exit 64
fi
for path in "${ADALIGAND_F_SUPPLEMENT_IDS_FILE}" "${ADALIGAND_F_SUPPLEMENT_PLAN_FILE}"; do
    if [[ -L "${path}" || ! -f "${path}" || ! -s "${path}" ]]; then
        echo "[ConfigError] frozen supplement input must be a non-empty regular file: ${path}"
        exit 64
    fi
done
actual_ids_sha256="$(sha256sum "${ADALIGAND_F_SUPPLEMENT_IDS_FILE}" | awk '{print $1}')"
actual_plan_sha256="$(sha256sum "${ADALIGAND_F_SUPPLEMENT_PLAN_FILE}" | awk '{print $1}')"
if [[ "${actual_ids_sha256}" != "${ADALIGAND_F_SUPPLEMENT_IDS_SHA256}" ]]; then
    echo "[ConfigError] supplement PDB id SHA-256 drift"
    exit 64
fi
if [[ "${actual_plan_sha256}" != "${ADALIGAND_F_SUPPLEMENT_PLAN_SHA256}" ]]; then
    echo "[ConfigError] supplement plan SHA-256 drift"
    exit 64
fi
echo "[Supplement] formal_run=${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID} supplement_run=${ADALIGAND_RUN_ID}"
echo "[Supplement] ids_sha256=${actual_ids_sha256} plan_sha256=${actual_plan_sha256}"

guard_marker="${DATA_ROOT}/reports/runs/${ADALIGAND_RUN_ID}/f_supplement_guard/stop.json"
set +e
"${PYTHON}" scripts/f_supplement_guard.py \
  --plan "${ADALIGAND_F_SUPPLEMENT_PLAN_FILE}" \
  --ids "${ADALIGAND_F_SUPPLEMENT_IDS_FILE}" \
  --formal_run_id "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID}" \
  --supplement_run_id "${ADALIGAND_RUN_ID}" \
  --formal_job_id "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID}" \
  --formal_log "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG}" \
  --stop_marker "${guard_marker}" \
  --child_pgid_file "${ADALIGAND_EXTRA_KILL_PGID_FILE}" \
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
    --pdb_ids_file "${ADALIGAND_F_SUPPLEMENT_IDS_FILE}" \
    --run_id "${ADALIGAND_RUN_ID}"
supplement_exit="$?"
set -e
if [[ "${supplement_exit}" -eq 75 ]]; then
    echo "[SupplementGuard] stopped before collision; marker=${guard_marker}"
    exit 0
fi
if [[ "${supplement_exit}" -ne 0 ]]; then
    exit "${supplement_exit}"
fi

"${PYTHON}" scripts/stage_release_gate.py \
  --root "${DATA_ROOT}" \
  --run_id "${ADALIGAND_RUN_ID}" \
  --stages stage_f \
  --gate_name f_supplement_release \
  --pdb_ids_file "${ADALIGAND_F_SUPPLEMENT_IDS_FILE}"
EOF
}

source "/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh"
