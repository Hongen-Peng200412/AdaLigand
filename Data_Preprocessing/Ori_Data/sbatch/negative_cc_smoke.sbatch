#!/usr/bin/env bash
#SBATCH --job-name=adaligand_negative_cc
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/smoke/%x_%j.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/smoke/%x_%j.err
#SBATCH --partition=cpu
#SBATCH --qos=Cpu96
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --time=01:00:00

set -u

write_adaligand_run_cmd() {
    local output_path="$1"
    cat >"${output_path}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "${CODE_ROOT}"

"${PYTHON}" -m adaligand_preprocessing.cli.smoke_negative_cc \
  --root "${DATA_ROOT}" \
  --pdb_id 5mkf \
  --chimera "${CHIMERA}" \
  --scratch_root "${SCRATCH_ROOT}" \
  --run_id "${ADALIGAND_RUN_ID}" \
  --shift_voxels 12 \
  --minimum_drop 0.05
EOF
}

source "/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh"
