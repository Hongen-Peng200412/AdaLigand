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

: "${ADALIGAND_RUN_ID:?supplement run id is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_RUN_ID:?formal run id is required}"
: "${ADALIGAND_F_SUPPLEMENT_IDS_FILE:?frozen PDB id file is required}"
: "${ADALIGAND_F_SUPPLEMENT_IDS_SHA256:?frozen PDB id SHA-256 is required}"
: "${ADALIGAND_F_SUPPLEMENT_PLAN_FILE:?frozen plan file is required}"
: "${ADALIGAND_F_SUPPLEMENT_PLAN_SHA256:?frozen plan SHA-256 is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_JOB_ID:?formal Slurm Job ID is required}"
: "${ADALIGAND_F_SUPPLEMENT_FORMAL_LOG:?formal Stage F stderr log is required}"
: "${ADALIGAND_EXTRA_KILL_PGID_FILE:?child PGID file is required}"

supplement_n_jobs="${F_N_JOBS:-12}"
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
supplement_exit=0
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
    supplement_exit=0
else
    supplement_exit="$?"
fi
if [[ "${supplement_exit}" -eq 75 ]]; then
    echo "[Supplement] collision guard is a successful no-op for the single-stage entry"
    exit 0
fi
exit "${supplement_exit}"
EOF
}

source "/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh"
