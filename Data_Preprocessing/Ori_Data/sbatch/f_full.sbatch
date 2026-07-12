#!/usr/bin/env bash
#SBATCH --job-name=adaligand_f
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/f/%x_%j.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/f/%x_%j.err
#SBATCH --partition=cpu
#SBATCH --qos=Cpu96
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=96

set -u

write_adaligand_run_cmd() {
    local output_path="$1"
    cat >"${output_path}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
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
  --run_id "${ADALIGAND_RUN_ID}"

"${PYTHON}" scripts/stage_release_gate.py \
  --root "${DATA_ROOT}" \
  --run_id "${ADALIGAND_RUN_ID}" \
  --stages stage_f \
  --gate_name f_release
EOF
}

source "/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh"
