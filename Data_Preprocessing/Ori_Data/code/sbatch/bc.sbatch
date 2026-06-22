#!/bin/bash
#SBATCH --job-name=adaligand_B
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/%x_%A_%a.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/%x_%A_%a.err
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --array=0-5

export PATH="/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin:$PATH"

cd /storage/penghongen/AdaLigand/Ori_Data

python scripts/b_download.py --root /storage/penghongen/AdaLigand/Ori_Data --part_id "${SLURM_ARRAY_TASK_ID}" --total_parts 6 --n_jobs 7 --resources mmcif,meta,map
