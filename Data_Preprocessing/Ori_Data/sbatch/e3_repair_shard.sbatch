#!/bin/bash
#SBATCH --job-name=adaligand_e3v3
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/e3/%x_%A_%a.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/e3/%x_%A_%a.err
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
: "${SLURM_ARRAY_TASK_ID:?this sbatch must run as an array task}"

E3_TOTAL_PARTS="${E3_TOTAL_PARTS:-48}"
E3_N_JOBS="${E3_N_JOBS:-16}"
if [[ "${SLURM_CPUS_PER_TASK:-0}" -lt "${E3_N_JOBS}" ]]; then
    echo "[ConfigError] n_jobs=${E3_N_JOBS} exceeds cpus_per_task=${SLURM_CPUS_PER_TASK:-0}" >&2
    exit 64
fi

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export PYTHONHASHSEED=0

FREEZE="${ROOT}/reports/runs/${E3_REPAIR_RUN}/stage_e3_freeze"

"${PYTHON}" "${PROJECT}/Data_Preprocessing/Ori_Data/scripts/e3_launch_control.py" verify \
    --root "${ROOT}" \
    --project_root "${PROJECT}" \
    --repair_run_id "${E3_REPAIR_RUN}" \
    --role worker

"${PYTHON}" "${PROJECT}/Data_Preprocessing/Ori_Data/scripts/e3_repair.py" run \
    --root "${ROOT}" \
    --repair_run_id "${E3_REPAIR_RUN}" \
    --target_ids_file "${FREEZE}/target_ids.txt" \
    --target_manifest "${FREEZE}/target_manifest.json" \
    --target_manifest_sha256 "${E3_TARGET_MANIFEST_SHA}" \
    --part_id "${SLURM_ARRAY_TASK_ID}" \
    --total_parts "${E3_TOTAL_PARTS}" \
    --n_jobs "${E3_N_JOBS}"

echo "[Success] E3 repair shard ${SLURM_ARRAY_TASK_ID}/${E3_TOTAL_PARTS} passed release statuses"
