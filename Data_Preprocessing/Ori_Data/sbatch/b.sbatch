#!/bin/bash
#SBATCH --job-name=adaligand_B
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/b/%x_%A_%a.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/b/%x_%A_%a.err

#SBATCH -p cpu                      # <--- 确认分区名
#SBATCH --qos=Cpu96                 # <--- 依然遵守96核配额限制
#SBATCH -N 1                        # 单节点
#SBATCH --ntasks=1                  # 1 个主进程
#SBATCH --cpus-per-task=8           # 申请 1 个核

#SBATCH --array=0-5

export PATH="/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin:$PATH"

cd /home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data

python scripts/b_download.py --root /storage/penghongen/AdaLigand/Ori_Data --part_id "${SLURM_ARRAY_TASK_ID}" --total_parts 6 --n_jobs 7 --resources mmcif,meta,map
