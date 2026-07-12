#!/usr/bin/env bash
# 提交 A–G analyze DAG。只有本脚本提交的 job 才能使用对应 kill_lock/after_lock 权限。
set -euo pipefail

CODE_ROOT=/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data
DATA_ROOT=/storage/penghongen/AdaLigand/Ori_Data
RUN_ID="${1:-adaligand_ag_$(date '+%Y%m%dT%H%M%S')}"
mkdir -p \
  "${DATA_ROOT}/logs/abc" \
  "${DATA_ROOT}/logs/de" \
  "${DATA_ROOT}/logs/f" \
  "${DATA_ROOT}/logs/g" \
  "${DATA_ROOT}/reports/runs/${RUN_ID}/submission"

abc_job=$(sbatch --parsable \
  --export="ALL,ADALIGAND_RUN_ID=${RUN_ID},C_N_JOBS=90" \
  "${CODE_ROOT}/sbatch/abc_full.sbatch")
de_job=$(sbatch --parsable --dependency="afterok:${abc_job}" \
  --export="ALL,ADALIGAND_RUN_ID=${RUN_ID},D_N_JOBS=64,E_N_JOBS=24" \
  "${CODE_ROOT}/sbatch/de_full.sbatch")
f_job=$(sbatch --parsable --dependency="afterok:${de_job}" \
  --export="ALL,ADALIGAND_RUN_ID=${RUN_ID},F_N_JOBS=12" \
  "${CODE_ROOT}/sbatch/f_full.sbatch")
g_job=$(sbatch --parsable --dependency="afterok:${f_job}" \
  --export="ALL,ADALIGAND_RUN_ID=${RUN_ID}" \
  "${CODE_ROOT}/sbatch/g_analyze.sbatch")

cat >"${DATA_ROOT}/reports/runs/${RUN_ID}/submission/jobs.env" <<EOF
RUN_ID=${RUN_ID}
ABC_JOB=${abc_job}
DE_JOB=${de_job}
F_JOB=${f_job}
G_ANALYZE_JOB=${g_job}
EOF
printf 'RUN_ID=%s\nABC_JOB=%s\nDE_JOB=%s\nF_JOB=%s\nG_ANALYZE_JOB=%s\n' \
  "${RUN_ID}" "${abc_job}" "${de_job}" "${f_job}" "${g_job}"
