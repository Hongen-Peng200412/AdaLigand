#!/usr/bin/env bash
set -euo pipefail

# 正式提交入口: 每次提交一个分片, 分片编号为 0 或 1; 每个单卡 A800/16 CPU 任务处理 50 个 PDB, 结束后保留资源.
shard_index="${1:?需要分片编号 0 或 1}"
qos="${2:?需要 Slurm QOS 名称}"
task_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
project_root="$(cd "${task_dir}/../.." && pwd -P)"
log_root="/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/运行日志与统计"
exec bash "${project_root}/训练与运行/submit_task.sh" \
    --sh "${task_dir}/sh/predict_calibration.sh" \
    --resource a800 --partition nvlink --qos "${qos}" \
    --gpus 1 --cpus 16 --array "${shard_index}" \
    --after_hold --job-name cryoatom2_calibration \
    --feedback-root "${log_root}/slurm"
