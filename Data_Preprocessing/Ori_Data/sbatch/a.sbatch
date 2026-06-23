#!/bin/bash
#SBATCH --job-name=adaligand_A
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/logs/a/%x_%j.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/logs/a/%x_%j.err

#SBATCH -p cpu                      # <--- 确认分区名
#SBATCH --qos=Cpu96                 # <--- 依然遵守96核配额限制
#SBATCH -N 1                        # 单节点
#SBATCH --ntasks=1                  # 1 个主进程
#SBATCH --cpus-per-task=1           # 申请 1 个核

export PATH="/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin:$PATH"

cd /home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data

python scripts/a_enumerate.py --root /storage/penghongen/AdaLigand/Ori_Data
