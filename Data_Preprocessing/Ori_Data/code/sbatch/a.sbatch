#!/bin/bash
#SBATCH --job-name=adaligand_A
#SBATCH --output=/storage/penghongen/AdaLigand/Ori_Data/%x_%j.out
#SBATCH --error=/storage/penghongen/AdaLigand/Ori_Data/%x_%j.err
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1

export PATH="/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin:$PATH"

cd /storage/penghongen/AdaLigand/Ori_Data

python scripts/a_enumerate.py --root /storage/penghongen/AdaLigand/Ori_Data
