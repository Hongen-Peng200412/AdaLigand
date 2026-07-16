# A–G 巨大长尾 run-only 上限

Type: decision
Date: 2026-07-16
Tags: A-G, run-policy, long-tail, exclusion, provenance

## Context

正式 run `adaligand_ag_20260711T154658` 已有 5 个经用户授权和现场证据支持的 run-only exclusion：`8ckb`、`8glv`、`9e5c`、`9fqr`、`6kgx`。用户希望极少数巨大长尾不要继续阻塞 A–G，但也不能把系统性故障静默拆成个例排除。

## Memory

本次正式 run 可以自治追加至多 4 个巨大长尾 exclusion，使累计始终不超过 9，亦即严格少于 10。每次追加必须同时满足：

- 样本已有客观证据证明正处于活动计算长尾，不能把排队或尚未启动当成长尾；
- 本阶段要求的完整公开 artifact 尚未形成，partial 或 scratch 不冒充完成；
- 日志、进程、运行时或资源占用证据足以支持长尾判断，并进入 run-scoped 记录。

样本必须保留在 22,386 样本宇宙和状态分母，以 `known_failed:run_policy_excluded` 记录，并从训练、推理和 G 候选排除；不得伪造 success 或质量三件套。

若下一条会令累计达到 10，或相同失败模式开始聚集、呈现系统性趋势，立即停止逐例排除，转为根因诊断并向用户确认。该决定只属于当前正式 run 的运行与资源策略，不新增科学 known-failure 类别，不改变 E/F 成功定义，也不自动适用于未来 run。

## When To Use

在恢复和监控本次 A–G 正式 run 时，遇到新的极端长尾样本，先按上述证据和剩余额度判断是否可 run-only 收口；任何数量上限或系统性信号触发时都必须停下询问。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `CLAUDE/memory/projects/adaligand.json`
