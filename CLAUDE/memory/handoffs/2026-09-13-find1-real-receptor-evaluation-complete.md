# Handoff: Find_1模型的真实受体的测评结果已完成

Date: 2026-09-13

## Current State

`Find_1` PDB-centric-v2 模型使用真实受体的 Stage1 测评已完成并通过产物门控。冻结 checkpoint 为 W&B 已完成步编号 `38622` 对应的 `TOP_epoch_04_score_0.6654.ckpt`。179-PDB `test_0` 同时完成 F1 blobs+basic 与 F2 blobs+Gaussian 两条流水线；149-PDB `test_1` 由 `test_0` 的逐 PDB 事实保序派生，没有重复前向或评估。

三份结果文档已在 AdaLigand 本地工作区重写，不再包含原先复制的 U-Net 数值与路径。文档当前保持未提交且未同步服务器，等待用户审阅。Job `368455` 的后续 scored-centered 任务由另一 Codex 线程继续运行；本轮没有查询或操作其进程、锁和 Slurm 状态。

## Completed

- 只读核验服务器上四份 metrics JSON、四份 JSONL 的字段契约、两份 `test_1` provenance、四份 tuning JSON、checkpoint/config、release/launch 与全部汇总产物 SHA-256。
- `主要结果.md` 收录 `test_0` 语义指标和 coverage/one-to-one@0.3/0.5，basic 与 Gaussian 在同表内并列。
- `补充结果.md` 收录 `test_0` 的 0.6 档实例指标与全部 top-K，以及 `test_1` 的语义、0.3/0.5/0.6 实例指标和 top-K。
- `说明.md` 记录模型与真实受体来源、两份测试清单、冻结参数、正式命令、release、launch、目录树、字段定义和复用边界。
- 文档门控通过：228 个六位小数指标在 `[0,1]`；36 个 top-K 单元格的计数、分母与百分比一致；Markdown 表格列数一致；无 U-Net Job、checkpoint、路径、哈希或指标残留。

## Decisions

- 实例主要结果固定为双向覆盖阈值 0.3 和 0.5 的 coverage/one-to-one P、R、F1 与 PRAUC；0.6 档和 top-K 固定为补充结果。
- `test_0` 的主要表放在 `主要结果.md`；`test_0` 的补充指标和 `test_1` 全部结果放在 `补充结果.md`。
- basic 与 Gaussian 是两条完整流水线的对比：它们不仅候选分数不同，语义阈值和候选集也不同；文档不将其表述为单因素打分消融。
- `test_1` 是 `test_0` 的重叠子集，两者不作为独立重复实验或独立统计样本比较。

## Open Questions

- 用户审阅三份本地 Markdown 后，是否将它们同步到 `/storage/penghongen/AdaLigand_stage1_inference/Find_1/真实受体/`。

## Next Actions

1. 由用户审阅主要/补充指标分类、basic/Gaussian 并表方式和可追溯说明。
2. 只有在用户明确同意后，才同步三份 Markdown 或安排 Git 提交。
3. Job `368455` 的 calibration/validation scored-centered 阶段继续由现有运行线程守护，不由本 handoff 重复接管。

## Files To Reopen

- [主要结果](../../../收口の结果/Stage1/Find_1(pdb_centric_v2)/使用真实的受体/主要结果.md)
- [补充结果](../../../收口の结果/Stage1/Find_1(pdb_centric_v2)/使用真实的受体/补充结果.md)
- [产物说明](../../../收口の结果/Stage1/Find_1(pdb_centric_v2)/使用真实的受体/说明.md)
- [文档收口执行记录](../../../文档/exec_plan/Find_1真实受体测试结果文档收口.md)
- [计划执行映射](../../../文档/mapping/计划执行映射.md)
- Pocket Plus `文档/exec_plan/2026-09-12_Find_1真实受体推理与评估.md`。

