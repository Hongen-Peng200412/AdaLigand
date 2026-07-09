#!/bin/bash
#SBATCH --job-name=adaligand_B
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/b/%x_%A_%a.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/b/%x_%A_%a.err
#SBATCH -p cpu
#SBATCH --qos=Cpu96
#SBATCH -N 1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=5
#SBATCH --array=0-3

export PATH="/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin:$PATH"

cd /home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data

python scripts/b_download.py --root /storage/penghongen/AdaLigand/Ori_Data --part_id "${SLURM_ARRAY_TASK_ID}" --total_parts 4 --n_jobs 4 --resources mmcif,meta,map
