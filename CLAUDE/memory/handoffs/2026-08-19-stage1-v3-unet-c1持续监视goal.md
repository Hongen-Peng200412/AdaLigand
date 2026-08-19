# Handoff: Stage1 第三版 unet_c1 持续监视目标

Date: 2026-08-19

## Current State

本对话已经建立 active goal：持续监视 Slurm Job `346737` 上的 Stage1 第三版 `unet_c1` a4；出现可恢复故障时，在既定训练范围内诊断、修复并记录；直到训练正常完成并验收。稳定期只使用 30 或 60 分钟命令自然睡眠，不创建 heartbeat，睡眠期间不发送消息。

- Job `346737`：`RUNNING`，节点 `hnode02`，单张 H100，16 CPU，`after_lock_346737` 保留。
- release：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/feedback/releases/Pocket_Plus_8139f528eebc/Pocket_Plus`
- launch：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/feedback/launches/346737/tmp_stage1_mainchain_job346737_20260818T035126_a4`
- 运行目录：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/runtime/mainchain_official_346737/logs/AdaLigand_Stage1-unet_c1-mainchain/unet_c1_mainchain____tmp_stage1_mainchain_job346737_20260818T035126_a4_formal`
- W&B：`hqumqkex`，2026-08-19 19:41 为 `trainer/global_step=10,421`、`epoch=0`。
- 最新 validation：配体体素 PRAUC `0.523583`；当前最高 TOP 文件是 `TOP_epoch_00_score_0.5382.ckpt`。
- H100 检查快照：利用率 96%，显存 80,708/81,559 MiB；a4 错误切片为空。

## Completed

- 验证训练继续使用 200 个 PDB 的冻结 `0:1:1` 请求；训练请求仍为 `0:5:5`。
- 验证冻结配置仍为 batch 8、全局 batch 48、16 workers、每 epoch 40 次 validation、主链损失 `0.05/0.05`、Stage1 调度器绝对改善阈值 `0.003`、`init_from=null`。
- 已发布 `BEST.ckpt`、`last.ckpt` 和十个 TOP checkpoint；最高 TOP 分数为 0.5382。
- 已把持续目标和本次明确 checkpoint/validation 节点写入 `文档/exec_plan/Stage1第三版训练启动与监视记录.md` 与 `文档/mapping/计划执行映射.md`。

## Decisions

- 只监视 Job `346737`，不检查或操作其他 Job。
- 不删除 `after_lock_346737`，不用 `scancel`，不创建 heartbeat。
- batch 8 显存余量小但已经稳定运行约 48 小时；只有出现明确 CUDA OOM 才按用户既有授权降为 batch 6，并保持全局 batch 48。
- 任何科学契约、batch、共享内存策略、代码 release 或动态命令变化都必须写入执行记录和新的 handoff。
- 没有明确事件时不追加运行流水账。

## Open Questions

- 当前仍为 `epoch=0`，因为训练集很大且每 epoch 包含 40 次 validation；应以 `trainer/global_step`、W&B 时间戳、GPU 活动和 checkpoint 更新时间联合判断进度，不能只看 epoch。
- 训练正常结束后，需要验收 Slurm 最终状态、退出码、BEST/last/TOP 文件、最终 W&B summary 和锁状态，再决定是否释放 `after_lock_346737`；释放资源需要用户明确授权。

## Next Actions

1. 执行 60 分钟命令自然睡眠，期间不发送消息。
2. 醒来后只读检查 Job `346737` 的 Slurm 状态、a4 进程、H100、W&B summary、checkpoint 与 a4 错误切片。
3. 若训练稳定且没有明确事件，继续 60 分钟命令睡眠；若失败，保存证据并在既定范围内修复。
4. 训练正常完成后验收最终产物、更新记录与 handoff，再把 active goal 标记为 complete。

## Files To Reopen

- `C:\Users\15919\Desktop\AdaLigand\文档\exec_plan\Stage1第三版训练启动与监视记录.md`
- `C:\Users\15919\Desktop\AdaLigand\文档\mapping\计划执行映射.md`
- `C:\Users\15919\Desktop\Pocket_Plus\训练与运行\sh\unet_c1.sh`
- `C:\Users\15919\Desktop\Pocket_Plus\src\train.py`
