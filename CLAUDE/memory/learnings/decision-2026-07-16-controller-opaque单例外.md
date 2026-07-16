# Stage F process gate 的 controller 单例外

Type: decision
Date: 2026-07-16
Tags: stage-f, process-gate, scratch-recovery, slurm

## Context

Stage F scratch 回收要求 master、cnode04、cnode01 上零 writer/cleanup/未知进程。master 上 PID 54412 是不归属本任务、扫描其他数据根的只读容量探针，长期处于 Lustre I/O 等待；继续等待它自然退出会无意义地延迟 A–G。

## Memory

用户明确决定本轮不等待、也不信号 PID 54412。process gate 只允许 controller 上最多一个一次性精确例外，必须同时匹配 node、PID、PPID、`/proc/<pid>/stat` start ticks 和 NUL 分隔 argv 的 SHA-256。probe 的原始 opaque 行必须保留并由 validator 复算；第二个 opaque、PID/父进程/启动时刻/argv 漂移、任何 F/recovery 进程、scan error 或 audit/apply 指纹不一致都继续 fail-closed。

start ticks 只在同一次系统启动内有效；本次证据新鲜度不超过 15 分钟，并且两个 Slurm allocation、scheduler 快照和精确锁同时受检，因此服务器重启不能沿用该例外。该接口不是通用 PID allowlist，也不授权终止不归属进程。

## When To Use

只在已由用户明确授权、已核验不归属当前任务且无需终止的 controller opaque 进程妨碍一次性恢复门时使用。不得把它用于 allocation 节点、多个 opaque 进程或未知用途进程。

## Related Files

- `Data_Preprocessing/Ori_Data/code/stage_f_process_audit.py`
- `Data_Preprocessing/Ori_Data/code/stage_f_scratch_recovery.py`
- `Data_Preprocessing/Ori_Data/scripts/stage_f_process_audit.py`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
