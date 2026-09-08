#!/usr/bin/env bash
set -euo pipefail

# 此脚本由项目提交系统在已分配 GPU 的 release 中执行; Python 与模型来自固定 Conda 环境.
export PATH="/home/penghongen/anaconda3/envs/CryoAtom2/bin:${PATH}"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=8
export MKL_NUM_THREADS=8
export OPENBLAS_NUM_THREADS=8
export NUMEXPR_NUM_THREADS=8
export CUDA_CACHE_PATH="/storage/penghongen/tmp/cryoatom2/cuda_cache/${SLURM_JOB_ID}"
export TMPDIR="/storage/penghongen/tmp/cryoatom2/${SLURM_JOB_ID}"
mkdir -p "${TMPDIR}" "${CUDA_CACHE_PATH}"
exec /home/penghongen/anaconda3/envs/CryoAtom2/bin/python -u \
    "${TASK_PROJECT_ROOT}/测评数据代码/cryoatom2原始预测结构/predict.py" run \
    --split-file /storage/penghongen/AdaLigand/held_out/split/held_out_06_chain/test_0.json \
    --data-root /storage/penghongen/AdaLigand/Ori_Data \
    --sequence-catalog /storage/penghongen/AdaLigand/held_out/sequence_catalog.jsonl \
    --output-root /storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06 \
    --scratch-root "${TMPDIR}" \
    --shard-index "${SLURM_ARRAY_TASK_ID}" --shard-count 3
