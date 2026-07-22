#!/usr/bin/env bash
#SBATCH --job-name=adaligand_abc
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/abc/%x_%j.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/abc/%x_%j.err
#SBATCH --partition=cpu
#SBATCH --qos=Cpu96
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=96
#SBATCH --time=2-00:00:00

set -u

write_adaligand_run_cmd() {
    local output_path="$1"
    cat >"${output_path}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "${CODE_ROOT}"

"${PYTHON}" -m adaligand_preprocessing.cli.stage_a_guard \
  --root "${DATA_ROOT}" \
  --expected_count 22386 \
  --expected_sha256 6c736180f5268e96329c62d9fceb8cc5c5917935677b3ddd815202e5891035f8 \
  --run_id "${ADALIGAND_RUN_ID}"

"${PYTHON}" -m adaligand_preprocessing.cli.stage_b \
  --root "${DATA_ROOT}" \
  --resources mmcif,meta,map \
  --n_jobs 1 \
  --run_id "${ADALIGAND_RUN_ID}" &
b_pid=$!

"${PYTHON}" -m adaligand_preprocessing.cli.stage_c \
  --root "${DATA_ROOT}" \
  --n_jobs "${C_N_JOBS:-90}" \
  --run_id "${ADALIGAND_RUN_ID}" &
c_pid=$!

b_exit=0
c_exit=0
wait "${b_pid}" || b_exit=$?
wait "${c_pid}" || c_exit=$?
if [ "${b_exit}" -ne 0 ] || [ "${c_exit}" -ne 0 ]; then
  echo "Stage B/C process failure: b=${b_exit} c=${c_exit}" >&2
  exit 1
fi
"${PYTHON}" -m adaligand_preprocessing.cli.abc_release --root "${DATA_ROOT}" --run_id "${ADALIGAND_RUN_ID}"
EOF
}

source "/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh"
