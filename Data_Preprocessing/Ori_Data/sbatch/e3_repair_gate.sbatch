#!/bin/bash
#SBATCH --job-name=adaligand_e3v3_gate
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/e3/%x_%j.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/e3/%x_%j.err
#SBATCH --partition=a100
#SBATCH --qos=a100g2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:a100:1

set -euo pipefail

PROJECT="/home/penghongen/My_Project/AdaLigand"
ROOT="/storage/penghongen/AdaLigand/Ori_Data"
PYTHON="/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python"

: "${E3_REPAIR_RUN:?E3_REPAIR_RUN is required}"
: "${E3_TARGET_MANIFEST_SHA:?E3_TARGET_MANIFEST_SHA is required}"

E3_GATE_N_JOBS="${E3_GATE_N_JOBS:-16}"
if [[ "${SLURM_CPUS_PER_TASK:-0}" -lt "${E3_GATE_N_JOBS}" ]]; then
    echo "[ConfigError] gate n_jobs=${E3_GATE_N_JOBS} exceeds cpus_per_task=${SLURM_CPUS_PER_TASK:-0}" >&2
    exit 64
fi

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export PYTHONHASHSEED=0

FREEZE="${ROOT}/reports/runs/${E3_REPAIR_RUN}/stage_e3_freeze"
RELEASE="${ROOT}/reports/runs/${E3_REPAIR_RUN}/stage_e3_repair_release/summary.json"

"${PYTHON}" "${PROJECT}/Data_Preprocessing/Ori_Data/scripts/e3_launch_control.py" verify \
    --root "${ROOT}" \
    --project_root "${PROJECT}" \
    --repair_run_id "${E3_REPAIR_RUN}" \
    --role gate

"${PYTHON}" "${PROJECT}/Data_Preprocessing/Ori_Data/scripts/e3_repair.py" gate \
    --root "${ROOT}" \
    --repair_run_id "${E3_REPAIR_RUN}" \
    --target_ids_file "${FREEZE}/target_ids.txt" \
    --target_manifest "${FREEZE}/target_manifest.json" \
    --target_manifest_sha256 "${E3_TARGET_MANIFEST_SHA}" \
    --n_jobs "${E3_GATE_N_JOBS}"

echo "[Success] E3 repair release summary SHA256=$(sha256sum "${RELEASE}" | awk '{print $1}')"
