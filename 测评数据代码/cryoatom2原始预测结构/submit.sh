#!/usr/bin/env bash
set -euo pipefail

# 正式提交入口: 三个数组任务各用一张 A100 和 8 核 CPU, 开始前等待放行, 结束后保留资源.
task_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
project_root="$(cd "${task_dir}/../.." && pwd -P)"
log_root="/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/运行日志与统计"
exec bash "${project_root}/训练与运行/submit_task.sh" \
    --sh "${task_dir}/sh/predict.sh" \
    --resource a100 --gpus 1 --cpus 8 --mem 96G --array 0-2 \
    --pre_hold --after_hold --job-name cryoatom2_test0 \
    --feedback-root "${log_root}/slurm"
