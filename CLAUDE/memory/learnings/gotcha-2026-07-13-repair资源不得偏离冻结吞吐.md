# Repair 资源不得偏离冻结吞吐

Type: gotcha
Date: 2026-07-13
Tags: AdaLigand, Slurm, repair, 并发, 资源漂移, critical-path

## Context

正式 Stage D/E 已冻结为同一 96 核作业内的 D64/E24，但 18 个 Stage E 工程失败的首轮 repair 因单个最大 canonical 图约 13.5 GB，被整体配置为 `n_jobs=2`。该配置让 96 核 allocation 长期只有约 2 核有效计算；两个大样本占满 worker 后，所有小中样本排队，repair 反而成为 A–G 依赖链的关键瓶颈。用户明确判定这是不可接受的中途资源漂移。

后续纠偏使用额外 CPU48、`n_jobs=12` 的 316415 执行标准 Chimera 长尾补足，并在用户授权的绝对截止点收口。这个配置解决了本次特定瓶颈，但它只是一次受检纠偏，不是新的通用最优并发。

## Memory

- 已经通过实证冻结的阶段并发属于运行契约。恢复、repair 或补算必须先复用 ExecPlan、sbatch 和项目记忆中的冻结值，不能因为代码默认值或临时保守判断把 E24 静默改为 `n_jobs=2`。确需偏离时，必须在启动前记录原值、新值、资源/样本依据、关键路径影响和用户授权。
- “个别超大样本需要低并发”只能转化为按样本体量分组的资源策略，不能静默把整个 repair 阶段降成最低并发。
- 任何长周期 repair 启动前都必须把冻结的正式并发、repair 并发、样本体量分层、CPU/内存/I/O 预算和预计关键路径并列核对。若 repair 会明显降低既定吞吐，必须先写入 ExecPlan/运行日志并取得用户确认，不能只在命令里留下一个保守数字。
- Stage E 的进度必须按每个 PDB 的完整公共三件套 `exp.npz + sim.npz + ligand_area.npz` 判定。只有 `exp.npz`、scratch、Chimera 仍在运行或 Joblib 已领取任务都不算完成，不能据此放行或覆盖正式状态。
- 扩容 canonical Stage E writer 前必须先停止旧 writer、确认其 Chimera/Joblib 子进程全部退出，再按已完成 artifact 冻结互不重叠的 PDB 清单。不同批次使用独立 run id、状态和 release gate；没有所有 writer 都遵守的 per-PDB 锁时，禁止让两个 run 同时拥有同一个 PDB。
- 优先复用既有 96 核 allocation 的空闲 CPU，避免取消或重提正式 DAG。需要额外节点时，可申请用户授权的 CPU48；若 48 核整块不能及时排队，立即按既有服务器纪律降级为 16 核 array 分片，或在 CPU 分区不足时使用已授权的 A100 分区 CPU-only 作业，不能提交后无期限等待。
- `CPU48/n_jobs=12` 只描述 316415 对六个 Stage E 长尾样本的本次纠偏证据，不能提升为未来 repair 的默认并发。未来仍须从冻结吞吐和当时实测资源重新推导。
- `kill_lock`、`try_lock`、`after_lock` 只操作精确 Job ID。切换 repair 时保留正式 Job ID、`after_lock` 和下游 `afterok`，并把旧尝试、切换原因、清单 SHA、run_cmd SHA、实际并发和最终状态写入日志。
- `kill_lock` 只证明 core 收到了停止信号，不证明外部 Chimera 已退出。core 收口后还要按用户、PID、完整命令行和 scratch 路径核对孤儿进程；只有精确归属进程全部消失，才可删除该补足作业的 `after_lock`、同步后续代码或切换正式 writer。
- 用户授权的 deadline/timeout 排除必须是 run-scoped 数据政策：样本仍留在冻结宇宙和 E/F 审计状态中，以 `known_failed:run_policy_excluded` 传播，并由 manifest 从训练、推理和 G 候选排除。它不是新的通用科学 KnownFailureCode，也不能改变坐标、密度或质量契约。

## When To Use

设计或恢复 AdaLigand 的 Stage C–G repair、补算、长尾重试、额外 CPU/GPU-CPU 调度时，先用本条审查资源配置。尤其当“安全”理由会把正式阶段已冻结的并发大幅降低时，必须做样本分层和关键路径核算，而不是整阶段降并发。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/sbatch/resume_de_316115_e_repair_v1.sh`
- `Data_Preprocessing/Ori_Data/sbatch/resume_de_316115_e_repair_v3.sh`
- `Data_Preprocessing/Ori_Data/code/long_tail_cutoff.py`
- `Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh`
- `CLAUDE/memory/handoffs/2026-07-13-stage-e长尾截止与正式恢复.md`
- `CLAUDE/memory/learnings/decision-2026-07-12-a-g原地调度已确认.md`
- `CLAUDE/memory/learnings/decision-2026-07-12-14pdb完整c重建与额外资源.md`
