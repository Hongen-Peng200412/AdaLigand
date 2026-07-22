#!/usr/bin/env bash
#SBATCH --job-name=adaligand_g_analyze
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/g/%x_%j.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/g/%x_%j.err
#SBATCH --partition=cpu
#SBATCH --qos=Cpu96
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1

set -u

write_adaligand_run_cmd() {
    local output_path="$1"
    cat >"${output_path}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "${CODE_ROOT}"
"${PYTHON}" -m adaligand_preprocessing.cli.stage_g \
  --root "${DATA_ROOT}" \
  --run_id "${ADALIGAND_RUN_ID}" \
  --mode analyze
EOF
}

source "/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh"
