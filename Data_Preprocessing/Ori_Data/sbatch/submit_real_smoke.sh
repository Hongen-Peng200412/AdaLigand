#!/usr/bin/env bash
# 提交一个显式 PDB 子集的真实 C–F smoke；不触碰全量 G 阈值。
set -euo pipefail

CODE_ROOT=/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data
DATA_ROOT=/storage/penghongen/AdaLigand/Ori_Data
IDS_FILE="${1:?Usage: submit_real_smoke.sh /absolute/path/to/pdb_ids.txt [run_id]}"
RUN_ID="${2:-adaligand_smoke_$(date '+%Y%m%dT%H%M%S')}"
test -f "${IDS_FILE}"
mkdir -p "${DATA_ROOT}/logs/smoke" "${DATA_ROOT}/reports/runs/${RUN_ID}/submission"

smoke_job=$(sbatch --parsable \
  --export="ALL,ADALIGAND_RUN_ID=${RUN_ID},ADALIGAND_SMOKE_IDS_FILE=${IDS_FILE}" \
  "${CODE_ROOT}/sbatch/real_smoke.sbatch")
cat >"${DATA_ROOT}/reports/runs/${RUN_ID}/submission/jobs.env" <<EOF
RUN_ID=${RUN_ID}
SMOKE_JOB=${smoke_job}
SMOKE_IDS_FILE=${IDS_FILE}
EOF
printf 'RUN_ID=%s\nSMOKE_JOB=%s\nSMOKE_IDS_FILE=%s\n' "${RUN_ID}" "${smoke_job}" "${IDS_FILE}"
