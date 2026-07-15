# Stage F 尾部补算与 CPU192 调度

Type: decision
Date: 2026-07-15
Tags: AdaLigand, Stage F, Slurm, CPU192, supplement, collision-guard, throughput

## Context

正式 Stage F job `316116` 已在一台 CPU96 节点上以 F12×MapQ np8 运行。实时采样显示整作业平均活跃 CPU 约为 43–44，但 MapQ 峰值仍可能达到 12×8；直接提高正式 `F_N_JOBS` 会过订阅峰值并要求中断正式 DAG。用户授权本轮主用 CPU 扩为 192，另有 48 CPU 只作测试、审计或备用。

服务器只读事实是：`cpu` 分区有 4×96 CPU 节点且不 oversubscribe；`Cpu96` 用户 QoS 的 `MaxTRESPU cpu=192`。因此两个 CPU96 作业并发已达到用户在该 QoS 的硬上限，额外 48 CPU 不能同时在同一 QoS 启动。

## Decision

- 保留正式 `316116`、正式 run、F12×MapQ np8、正式 status/release、locks 和 `316117` afterok 全部不变。
- 使用独立 job `318350` / run `adaligand_ag_20260711T154658_fsupp96_v1` 在第二台整节点上补算冻结尾段，只提前生成可被正式 F 的既有 validator 复用的质量三件套。
- 尾段固定为 `[19386,22386)`，实际选择 2,990 个 eligible PDB；正式进度达到 17,386 时停止，保留 2,000-task guard。
- plan/ID SHA-256 分别为 `1d5c12172629bcba2af65a379c2c78d9bf7141fdcdd505e699add8b58b1dff4f` 与 `acacde79c2a5a8727949cdc0a986930aa8404419a8edaabfb264f4f05dacea80`。
- 补算 status/gate 与正式 run 隔离，绝不写正式 Stage F 状态或 release；Stage G 只能由正式 `f_release` 释放。

## Durable Rules

- repair、恢复或补算的并发必须先查 ExecPlan、sbatch 和项目记忆中的冻结实测。不得因默认值、“保守”直觉或小样本数量静默偏离正式吞吐；确需偏离时，启动前记录原值、新值、样本体量、CPU/内存/I/O、关键路径、互斥边界和用户授权。
- 低平均 CPU 利用率不等于可以提高同一作业外层并发。先检查内层并行峰值；F12×MapQ np8 的理论峰值就是 96。
- 多 writer 只能处理冻结且互不重叠的 PDB 集合。没有共同 per-PDB 锁时，必须用正式进度区间、ID 哈希和运行期碰撞守卫形成互斥；不能依赖“应该追不上”。
- 守卫必须绑定正式 Job ID、run id、日志绝对路径及 device/inode、计划/ID SHA 和资源契约。阈值、TERM、异常或 kill-lock 都必须收口整个 child PGID，不能只杀外层 shell。
- 补算完成的公共 artifact 只有通过正式 validator 后才可被正式运行 skip；补算自己的 gate 不能替代正式四终态与 release gate。
- 96 核整节点作业需要完整空闲节点。提交前先读 `sinfo/squeue/QoS`；有空闲整节点时优先单个 CPU96，整节点窗口消失后才评估 16 核 array 或已授权备用分区，不取消/重提正式 DAG。
- 用户授权的“192+48”是用途边界，不会覆盖 QoS。两台 CPU96 并发时 48 核是待释放后的备用，除非另一个 partition/QoS 已被重新只读验证。

## Evidence

- 正式规划时进度 6,248/22,386；预计补算约 16.6 小时、正式到 guard 约 31 小时，预计净节省 14–16 小时。估算只服务本轮，不能提升为通用吞吐。
- `318350` 于 `2026-07-15T16:23:59+08:00` 在空闲 `cnode01` 零等待启动；正式 `316116` 保持 `cnode04`，两者总分配恰 192 CPU。
- 补算 `after_lock` 和 child PGID 存在，try/kill 不存在；日志确认独立 run、哈希与 `Parallel(n_jobs=12)`。
- 本地测试 224 passed、2 个 POSIX-only skipped；服务器 Linux 226 passed，shell/sbatch `bash -n` 通过。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `Data_Preprocessing/Ori_Data/scripts/f_supplement_plan.py`
- `Data_Preprocessing/Ori_Data/scripts/f_supplement_guard.py`
- `Data_Preprocessing/Ori_Data/sbatch/f_supplement_96.sbatch`
- `Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh`
- `CLAUDE/memory/learnings/gotcha-2026-07-13-repair资源不得偏离冻结吞吐.md`
