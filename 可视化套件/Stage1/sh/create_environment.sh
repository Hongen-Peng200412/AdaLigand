#!/usr/bin/env bash
set -euo pipefail

# 该环境独立于 Pocket Plus 训练环境；路径可由同名环境变量覆盖。
environment_prefix="${ADALIGAND_STAGE1_PYMOL_ENV:-${HOME}/anaconda3/envs/AdaLigand_stage1_pymol}"
environment_file="${TASK_PROJECT_ROOT}/可视化套件/Stage1/environment.yml"

if [[ -x "${environment_prefix}/bin/python" ]]; then
    "${environment_prefix}/bin/python" -c 'import numpy; from pymol import cmd; print(cmd.get_version()[0], numpy.__version__)'
    exit 0
fi

exec conda env create --prefix "${environment_prefix}" --file "${environment_file}"
