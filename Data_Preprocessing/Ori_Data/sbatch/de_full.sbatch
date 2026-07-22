#!/usr/bin/env bash
#SBATCH --job-name=adaligand_de
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/de/%x_%j.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/de/%x_%j.err
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

"${PYTHON}" -m adaligand_preprocessing.cli.stage_d \
  --root "${DATA_ROOT}" \
  --n_jobs "${D_N_JOBS:-64}" \
  --run_id "${ADALIGAND_RUN_ID}" &
d_pid=$!

e_exit=0
"${PYTHON}" -m adaligand_preprocessing.cli.stage_e \
  --root "${DATA_ROOT}" \
  --chimera "${CHIMERA}" \
  --scratch_root "${SCRATCH_ROOT}" \
  --n_jobs "${E_N_JOBS:-24}" \
  --timeout_seconds "${E_TIMEOUT_SECONDS:-3600}" \
  --run_id "${ADALIGAND_RUN_ID}" || e_exit=$?
d_exit=0
wait "${d_pid}" || d_exit=$?
if [ "${d_exit}" -ne 0 ] || [ "${e_exit}" -ne 0 ]; then
  echo "Stage D/E process failure: d=${d_exit} e=${e_exit}" >&2
  exit 1
fi

"${PYTHON}" -m adaligand_preprocessing.cli.stage_release \
  --root "${DATA_ROOT}" \
  --run_id "${ADALIGAND_RUN_ID}" \
  --stages stage_d,stage_e \
  --gate_name de_release
EOF
}

source "/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh"
