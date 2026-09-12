#!/usr/bin/env bash
set -euo pipefail

# 在单卡 release 中顺序预测 calibration 的一个分片; 16 核线程上限与 Slurm 申请一致.
export PATH="/home/penghongen/anaconda3/envs/CryoAtom2/bin:${PATH}"
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=16
export MKL_NUM_THREADS=16
export OPENBLAS_NUM_THREADS=16
export NUMEXPR_NUM_THREADS=16
export CUDA_CACHE_PATH="/storage/penghongen/tmp/cryoatom2/cuda_cache/${SLURM_JOB_ID}"
export TMPDIR="/storage/penghongen/tmp/cryoatom2/${SLURM_JOB_ID}"
mkdir -p "${TMPDIR}" "${CUDA_CACHE_PATH}"
exec /home/penghongen/anaconda3/envs/CryoAtom2/bin/python -u \
    "${TASK_PROJECT_ROOT}/测评数据代码/cryoatom2原始预测结构/predict.py" run \
    --split-file /storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/split/pdb_split/calibration.json \
    --data-root /storage/penghongen/AdaLigand/Ori_Data \
    --sequence-catalog /storage/penghongen/AdaLigand/held_out/sequence_catalog.jsonl \
    --output-root /storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration \
    --scratch-root "${TMPDIR}" \
    --shard-index "${SLURM_ARRAY_TASK_ID}" --shard-count 2
