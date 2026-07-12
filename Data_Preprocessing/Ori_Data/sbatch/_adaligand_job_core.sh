#!/usr/bin/env bash
# AdaLigand 专用长任务核心：动态 run_cmd、可选 pre_lock、失败 try_lock、kill_lock 与心跳。
# 不 source Pocket Plus 的 `_common.sh/_train_core.sh`，避免旧环境、CUDA 和删除式缓存绑定。
set -u

: "${SLURM_JOB_ID:?This script must run inside Slurm}"
: "${ADALIGAND_RUN_ID:?ADALIGAND_RUN_ID is required}"

export CODE_ROOT=/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data
export DATA_ROOT=/storage/penghongen/AdaLigand/Ori_Data
export PYTHON=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python
export CHIMERA_ROOT=/home/penghongen/.local/opt/UCSF-Chimera64-1.19
export CHIMERA=/home/penghongen/.local/opt/UCSF-Chimera64-1.19/bin/chimera
export MAPQ_ROOT=/home/penghongen/.local/opt/mapq-2.9.7-c3bdf305
export MAPQ_CMD=/home/penghongen/.local/opt/mapq-2.9.7-c3bdf305/mapq/mapq_cmd.py
export MAPQ_ZIP=/home/penghongen/.local/opt/downloads/mapq_v2.9.7.zip
export SCRATCH_ROOT="${DATA_ROOT}/scratch"
export PYTHONUNBUFFERED=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export VECLIB_MAXIMUM_THREADS=1
export NUMEXPR_NUM_THREADS=1
export LANG=C.UTF-8
export LC_ALL=C.UTF-8

RUN_CMD_FILE="/home/penghongen/run_cmd_${SLURM_JOB_ID}.sh"
PRE_LOCK="/home/penghongen/pre_lock_${SLURM_JOB_ID}"
AFTER_LOCK="/home/penghongen/after_lock_${SLURM_JOB_ID}"
TRY_LOCK="/home/penghongen/try_lock_${SLURM_JOB_ID}"
KILL_LOCK="/home/penghongen/kill_lock_${SLURM_JOB_ID}"
RUN_PID=""
WATCHER_PID=""
HEARTBEAT_PID=""
FINAL_EXIT=1

is_enabled() {
    case "${1:-0}" in
        1|true|TRUE|True|yes|YES|Yes|on|ON|On) return 0 ;;
        *) return 1 ;;
    esac
}

stop_background_watchers() {
    for pid in "${WATCHER_PID}" "${HEARTBEAT_PID}"; do
        if [ -n "${pid}" ]; then
            kill "${pid}" 2>/dev/null || true
            wait "${pid}" 2>/dev/null || true
        fi
    done
    WATCHER_PID=""
    HEARTBEAT_PID=""
}

cleanup() {
    stop_background_watchers
    if [ -n "${RUN_PID}" ]; then
        kill -TERM -"${RUN_PID}" 2>/dev/null || kill -TERM "${RUN_PID}" 2>/dev/null || true
    fi
    rm -f "${RUN_CMD_FILE}" "${PRE_LOCK}" "${TRY_LOCK}" "${KILL_LOCK}" "${AFTER_LOCK}"
    echo "[Cleanup] removed lock/cmd files for job ${SLURM_JOB_ID}"
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT

validate_run_cmd() {
    # 每次 attempt 都重新校验，确保通过 try_lock 编辑后的命令不会绕过语法与来源记录。
    if [ -L "${RUN_CMD_FILE}" ] || [ ! -f "${RUN_CMD_FILE}" ]; then
        echo "[ConfigError] run_cmd must be a regular non-symlink file: ${RUN_CMD_FILE}"
        exit 64
    fi
    if ! chmod 700 "${RUN_CMD_FILE}"; then
        echo "[ConfigError] cannot set run_cmd permissions: ${RUN_CMD_FILE}"
        exit 64
    fi
    if [ ! -s "${RUN_CMD_FILE}" ] || ! bash -n "${RUN_CMD_FILE}"; then
        echo "[ConfigError] run_cmd is empty or fails bash -n: ${RUN_CMD_FILE}"
        exit 64
    fi
    echo "[RunCmd] sha256=$(sha256sum "${RUN_CMD_FILE}" | awk '{print $1}')"
}

# 已存在的精确 job run_cmd 是人工/Agent 预置覆盖；不存在时才调用 sbatch 内置生成钩子。
# 该顺序与 Pocket Plus `_train_core.sh` 一致，可保留原 Job ID 和排队顺序完成原地调参。
if [ -L "${RUN_CMD_FILE}" ]; then
    echo "[ConfigError] refusing symlink run_cmd: ${RUN_CMD_FILE}"
    exit 64
elif [ -e "${RUN_CMD_FILE}" ] && [ ! -f "${RUN_CMD_FILE}" ]; then
    echo "[ConfigError] run_cmd exists but is not a regular file: ${RUN_CMD_FILE}"
    exit 64
elif [ -f "${RUN_CMD_FILE}" ]; then
    echo "[RunCmd] reusing preloaded file: ${RUN_CMD_FILE}"
else
    if ! type write_adaligand_run_cmd >/dev/null 2>&1; then
        echo '[ConfigError] sbatch script must define write_adaligand_run_cmd'
        exit 64
    fi
    write_adaligand_run_cmd "${RUN_CMD_FILE}"
    echo "[RunCmd] generated from sbatch hook: ${RUN_CMD_FILE}"
fi
validate_run_cmd

touch "${AFTER_LOCK}"
echo "[Lock] after_lock=${AFTER_LOCK}"
if is_enabled "${ADALIGAND_PRE_LOCK_ENABLED:-0}"; then
    touch "${PRE_LOCK}"
    echo "[Lock] pre_lock=${PRE_LOCK}; delete it to start"
    while [ -f "${PRE_LOCK}" ]; do
        sleep 20
    done
fi

echo "[Context] run_id=${ADALIGAND_RUN_ID} job=${SLURM_JOB_ID} host=$(hostname) cpus=${SLURM_CPUS_PER_TASK:-unknown}"
echo "[Context] python=$(${PYTHON} --version 2>&1) code=${CODE_ROOT} data=${DATA_ROOT}"
cd "${CODE_ROOT}"

while true; do
    validate_run_cmd
    rm -f "${KILL_LOCK}"
    echo "[Attempt] $(date --iso-8601=seconds) executing ${RUN_CMD_FILE}"
    sed -n '1,240p' "${RUN_CMD_FILE}"
    setsid stdbuf -oL -eL bash "${RUN_CMD_FILE}" &
    RUN_PID=$!

    (
        while kill -0 "${RUN_PID}" 2>/dev/null; do
            sleep 10
            if [ -f "${KILL_LOCK}" ]; then
                echo "[KillWatcher] ${KILL_LOCK} detected; killing process group ${RUN_PID}"
                kill -9 -"${RUN_PID}" 2>/dev/null || kill -9 "${RUN_PID}" 2>/dev/null || true
                rm -f "${KILL_LOCK}"
                exit 0
            fi
        done
    ) &
    WATCHER_PID=$!
    (
        while kill -0 "${RUN_PID}" 2>/dev/null; do
            sleep 300
            echo "[Heartbeat] $(date --iso-8601=seconds) job=${SLURM_JOB_ID} run_pid=${RUN_PID}"
        done
    ) &
    HEARTBEAT_PID=$!

    wait "${RUN_PID}" && attempt_exit=0 || attempt_exit=$?
    RUN_PID=""
    stop_background_watchers
    if [ "${attempt_exit}" -eq 0 ]; then
        FINAL_EXIT=0
        rm -f "${AFTER_LOCK}" "${TRY_LOCK}"
        echo '[Success] run_cmd and all embedded release gates passed; allocation will exit'
        break
    fi

    FINAL_EXIT="${attempt_exit}"
    echo "[Failure] run_cmd exited ${attempt_exit}"
    if ! is_enabled "${ADALIGAND_HOLD_ON_FAILURE:-1}"; then
        rm -f "${AFTER_LOCK}"
        break
    fi
    touch "${TRY_LOCK}"
    echo "[Hold] edit ${RUN_CMD_FILE}; delete ${TRY_LOCK} to retry, or delete ${AFTER_LOCK} to release"
    while [ -f "${TRY_LOCK}" ] && [ -f "${AFTER_LOCK}" ]; do
        sleep 20
    done
    if [ ! -f "${AFTER_LOCK}" ]; then
        echo '[Release] after_lock deleted; leaving failed allocation'
        break
    fi
    echo '[Retry] try_lock deleted; starting edited run_cmd'
done

exit "${FINAL_EXIT}"
