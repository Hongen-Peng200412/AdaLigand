#!/usr/bin/env bash
set -euo pipefail

environment_prefix="${ADALIGAND_STAGE1_PYMOL_ENV:-${HOME}/anaconda3/envs/AdaLigand_stage1_pymol}"
python_entry="${TASK_PROJECT_ROOT}/可视化套件/Stage1/build_comparison_sessions.py"
profile="${TASK_PROJECT_ROOT}/可视化套件/Stage1/profiles/stage1_7mode_pcv2_test0.json"

exec "${environment_prefix}/bin/python" "${python_entry}" --profile "${profile}" "$@"
