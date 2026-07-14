# Stage F 长尾必须用阶段专属、可审计的 run-only 排除

Type: decision
Date: 2026-07-14
Tags: stage-f, long-tail, exclusions, provenance, slurm-lock

## Context

正式 run `adaligand_ag_20260711T154658` 的 Stage F job `316116` 以 F12 推进到 22,363/22,386 后，唯一仍在执行的 `6kgx` 已完成 Chimera/MapQ，但在 Python occurrence Q-score 投影中对 1,588 个 occurrence 反复扫描 1,011,574 行规范化模型原子，公开质量三件套仍未形成。用户明确授权把这个已取证长尾按本轮超时处理，继续 A–G 主线。

## Memory

- 这类决定是当前 run 的工程运行策略，不是新的科学 known-failure 类别，也不是未来自动超时规则。必须先证明样本确实是当前活动长尾，并冻结调度、进程、栈、日志和 artifact 证据；不能因为任务排在队尾就批量排除。
- 已闭合阶段的 manifest 及其 SHA 不得被后置决策改写。本轮共享 `exclusions.jsonl` 已被 Stage E status/release 绑定，因而保持 SHA-256 `380844d0…325f`；Stage F 通过严格加法视图 `exclusions.stage_f.jsonl` 追加 `6kgx`，SHA-256 `3b10abb5…8ee8`。
- Stage F 视图必须逐字段保留共享 manifest 中所有适用于 F 的记录，只能追加新的 `stages=["stage_f"]` PDB；孤立视图、broken symlink、删改旧记录、同 ID 遮蔽和静默空回退都要 fail-fast。
- 被授权排除的样本仍留在冻结样本宇宙和状态分母，写 `known_failed:run_policy_excluded`；不得伪造 `quality/*.jsonl`、provenance 或 `quality_atoms/*.npz`，训练、推理和 G 候选不得消费它。
- 长任务恢复继续遵守精确锁状态机：冻结证据 → 精确 kill-lock → 等待 core 产生 try-lock并确认无残留进程 → 本地测试/Git checkpoint/精确安全同步 → 绑定远端测试日志与最终代码/run_cmd SHA 的 release marker → try-lock 内 apply-only → try-lock 内真正只读验证并比较前后哈希 → 只删除精确 try-lock。保留 after-lock，不取消或重提原 DAG。
- repair/恢复并发必须先查 ExecPlan 和项目记忆中的实测冻结基准。不得用临时拍脑袋的小并发制造主线瓶颈，也不得把某次补足的并发值泛化为所有数据尺寸的最优值。

## When To Use

当已经放行的上游阶段之后出现少量、已充分取证的工程长尾，而用户授权当前 run 继续推进时；尤其适用于旧阶段 status 已绑定原 manifest SHA、不能安全改写共享 provenance 的情况。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/exclusions.py`
- `Data_Preprocessing/Ori_Data/sbatch/resume_f_316116_long_tail_v1.sh`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `与服务器交互/other/readme.md`
