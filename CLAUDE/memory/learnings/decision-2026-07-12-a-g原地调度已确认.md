# A–G 原地调度已确认

Type: decision
Date: 2026-07-12
Tags: AdaLigand, Slurm, run_cmd, UNLIMITED, 并发

## Context

全量 run `adaligand_ag_20260711T154658` 的 96 核后继作业已经排队。取消并重提可能失去整节点排位，因此用户确认保留 `316114 (ABC) → 316115 (DE) → 316116 (F) → 316117 (G analyze)` 的原 Job ID 和依赖链，采用受检预置命令原地调整。

## Memory

- `316115` 已解除 user hold，只等待 `afterok:316114`；不得再把它视为等待参数确认的暂停作业。
- `316115/316116/316117` 已用 `scontrol update` 原地设为 `TimeLimit=UNLIMITED`，三者提交时间均仍为 `2026-07-11T15:46:58`。
- `/home/penghongen/run_cmd_316115.sh` 固定执行 D64/E24，SHA-256 为 `54658b7a4c2819793a22282ac21a005bfdc6fe1f6c48d4a006c760be2cd380b0`。
- `/home/penghongen/run_cmd_316116.sh` 固定执行 F12；每个 PDB 的 MapQ 仍固定 `sigma=0.4,np=8`，SHA-256 为 `8399d571bab44881facbeaa9dd1e738594255a4b4212605cfe418878744f7d13`。
- AdaLigand core 优先复用预置普通文件，拒绝 symlink，并在首次及每次 `try_lock` 重试前检查非空、设为 `0700`、执行 `bash -n` 和记录 SHA-256。预置必须经同目录临时文件原子发布。
- 不得取消或重提这条 DAG，不得运行 clean sync。阶段启动时必须从日志核对 `reusing preloaded file`、预期哈希与实际并行参数；失败后才允许对精确归属作业使用 `kill_lock/try_lock`。

## When To Use

恢复 A–G 监控、审计 DE/F 阶段切换、处理 Slurm 时限或判断是否需要重提作业时，使用本条已确认状态。旧的“316115 被 hold、参数待确认”记忆只代表讨论期间的历史状态。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh`
- `Data_Preprocessing/Ori_Data/sbatch/de_full.sbatch`
- `Data_Preprocessing/Ori_Data/sbatch/f_full.sbatch`
- `Data_Preprocessing/Ori_Data/sbatch/g_analyze.sbatch`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `与服务器交互/other/readme.md`
