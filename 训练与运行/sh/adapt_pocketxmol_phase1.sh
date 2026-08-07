#!/usr/bin/env bash
set -euo pipefail

if (($# < 2)); then
    printf '用法：%s OUTPUT_ROOT SPLIT_NAME=MANIFEST_PATH [...] [WORKERS]\n' "$0" >&2
    exit 2
fi

output_root="$1"
shift
workers="${SLURM_CPUS_PER_TASK:-$(nproc)}"
split_args=()
worker_argument_seen=0
for argument in "$@"; do
    if [[ "${argument}" =~ ^[1-9][0-9]*$ ]]; then
        if ((worker_argument_seen)); then
            printf '[错误] worker 数量只能传入一次。\n' >&2
            exit 2
        fi
        workers="${argument}"
        worker_argument_seen=1
    else
        split_args+=(--split "${argument}")
    fi
done
if ((${#split_args[@]} == 0)); then
    printf '[错误] 至少需要一项 SPLIT_NAME=MANIFEST_PATH。\n' >&2
    exit 2
fi
stage_c_root=/storage/penghongen/AdaLigand/Ori_Data
chemistry_audit="${output_root}/reports/source_chemistry_audit.json"
compat_pythonpath="${TASK_PROJECT_ROOT}/Data_Preprocessing/PocketXmol_compat"
full_pythonpath="${TASK_PROJECT_ROOT}/Data_Preprocessing/Ori_Data:${compat_pythonpath}"

source /home/penghongen/anaconda3/etc/profile.d/conda.sh
# 第一阶段必须使用产生 CCD pickle 的 A–G RDKit 环境；只输出版本中立 JSON。
conda activate /home/penghongen/anaconda3/envs/AdaLigand_stage1_py310
PYTHONPATH="${compat_pythonpath}" python -m pocketxmol_compat.ccd_audit \
    --stage-c-root "${stage_c_root}" \
    "${split_args[@]}" \
    --output "${chemistry_audit}"

# 第二阶段回到 PocketXMol 固定环境；主适配器不得再打开 CCD pickle。
conda activate /home/penghongen/anaconda3/envs/pxm_phase1
export PYTHONPATH="${full_pythonpath}"
python -m pocketxmol_compat.cli \
    --stage-c-root "${stage_c_root}" \
    --output-root "${output_root}" \
    --pocketxmol-root /home/penghongen/My_Project/PocketXMol \
    --ccd-audit "${chemistry_audit}" \
    "${split_args[@]}" \
    --workers "${workers}"
