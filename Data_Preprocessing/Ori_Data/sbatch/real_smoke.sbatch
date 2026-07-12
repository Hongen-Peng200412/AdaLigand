#!/usr/bin/env bash
#SBATCH --job-name=adaligand_real_smoke
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/smoke/%x_%j.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/smoke/%x_%j.err
#SBATCH --partition=cpu
#SBATCH --qos=Cpu96
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --time=12:00:00

set -u
: "${ADALIGAND_SMOKE_IDS_FILE:?ADALIGAND_SMOKE_IDS_FILE is required}"

write_adaligand_run_cmd() {
    local output_path="$1"
    cat >"${output_path}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "${CODE_ROOT}"

"${PYTHON}" scripts/c_parse.py --root "${DATA_ROOT}" --n_jobs 8 \
  --pdb_ids_file "${ADALIGAND_SMOKE_IDS_FILE}" --run_id "${ADALIGAND_RUN_ID}"
"${PYTHON}" scripts/stage_release_gate.py --root "${DATA_ROOT}" --run_id "${ADALIGAND_RUN_ID}" \
  --stages stage_c --gate_name smoke_c_release --pdb_ids_file "${ADALIGAND_SMOKE_IDS_FILE}" \
  --require_success

"${PYTHON}" scripts/d_atom_labels.py --root "${DATA_ROOT}" --n_jobs 4 \
  --pdb_ids_file "${ADALIGAND_SMOKE_IDS_FILE}" --run_id "${ADALIGAND_RUN_ID}" &
d_pid=$!
e_exit=0
"${PYTHON}" scripts/e_density.py --root "${DATA_ROOT}" --chimera "${CHIMERA}" \
  --scratch_root "${SCRATCH_ROOT}" --n_jobs 2 \
  --pdb_ids_file "${ADALIGAND_SMOKE_IDS_FILE}" --run_id "${ADALIGAND_RUN_ID}" || e_exit=$?
d_exit=0
wait "${d_pid}" || d_exit=$?
if [ "${d_exit}" -ne 0 ] || [ "${e_exit}" -ne 0 ]; then
  echo "Smoke Stage D/E process failure: d=${d_exit} e=${e_exit}" >&2
  exit 1
fi
"${PYTHON}" scripts/stage_release_gate.py --root "${DATA_ROOT}" --run_id "${ADALIGAND_RUN_ID}" \
  --stages stage_d,stage_e --gate_name smoke_de_release --pdb_ids_file "${ADALIGAND_SMOKE_IDS_FILE}" \
  --require_success

"${PYTHON}" scripts/f_quality.py --root "${DATA_ROOT}" --chimera "${CHIMERA}" \
  --chimera_root "${CHIMERA_ROOT}" --mapq_python "${PYTHON}" --mapq_cmd "${MAPQ_CMD}" \
  --mapq_zip "${MAPQ_ZIP}" --scratch_root "${SCRATCH_ROOT}" --n_jobs 2 \
  --pdb_ids_file "${ADALIGAND_SMOKE_IDS_FILE}" --run_id "${ADALIGAND_RUN_ID}"
"${PYTHON}" scripts/stage_release_gate.py --root "${DATA_ROOT}" --run_id "${ADALIGAND_RUN_ID}" \
  --stages stage_f --gate_name smoke_f_release --pdb_ids_file "${ADALIGAND_SMOKE_IDS_FILE}" \
  --require_success
EOF
}

source "/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh"
