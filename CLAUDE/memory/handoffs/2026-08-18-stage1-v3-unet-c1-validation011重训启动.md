# Handoff: Stage1 第三版 unet_c1 采用 validation 0:1:1 重训

Date: 2026-08-18

## Current State

用户授权继续接管 Slurm Job `346737`，使用 Pocket_Plus 正式 `训练与运行/sh/unet_c1.sh` 从头训练带 protein 与 nucleic 主链辅助损失的单卡 `unet_c1`。本轮只处理 Job `346737`，没有检查或操作其他 Job。

- Job：`346737`，节点 `hnode02`，单张 H100，16 CPU，`after_lock_346737` 保留。
- 当前 release：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/feedback/releases/Pocket_Plus_8139f528eebc/Pocket_Plus`
- 当前 launch：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/feedback/launches/346737/tmp_stage1_mainchain_job346737_20260818T035126_a4`
- 当前输出：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/runtime/mainchain_official_346737`
- 当前阶段：a4 已连续通过 10 分钟与 30 分钟稳定检查。2026-08-18 04:43 的 W&B `hqumqkex` 为 `trainer/global_step=245`、`epoch=0`，五项 step loss 均为有限值；H100 快照利用率 67%，显存 79,826/81,559 MiB，未出现 a4 新异常，也尚无 checkpoint。

## Completed

- Pocket_Plus 本地把冻结 validation 选择改为硬编码 `center:bias:context = 0:1:1`，训练选择保持 `0:5:5`。
- Stage1 CPC1 与 CPC2 的 `ReduceLROnPlateau.threshold` 统一为绝对阈值 `0.003`；没有修改 Selector 的独立阈值。
- Pocket_Plus 定向测试 39 项通过，四个正式训练脚本通过 Bash 语法检查；本机全量测试因缺 `lightning`、`torch_cluster`、`wandb` 等训练依赖而止于收集。
- 真实实现端点为 `56a068f`，学习端点与 `Learn/CUMULATIVE` 为 `0c67fed`；两端 Git tree 同为 `565ba9a5ddf879f672287260f6448a59350195d5`。
- 通过正式安全同步入口更新共享代码，再以非删除式复制更新 346737 的专属任务根；关键脚本与配置的本地/服务器 SHA-256 一致。
- 按用户新授权写入 `kill_lock_346737` 终止 a3，保留 `after_lock_346737`。在全局 `try_lock_346737` 存在期间覆盖发布 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/box_pool/validation_selection.npz`，没有备份旧文件。
- 新 validation 产物已验证为 200 个 PDB、0 个 center、3,305 个 bias、3,305 个 context；`config.json.validation_entry_ratio`、`summary.json.validation_selection` 与 `_COMPLETE` 已同步。
- 删除全局 `try_lock_346737` 后启动 a4。冻结配置确认 batch 8、全局 batch 48、16 workers、`val_per_epoch=40`、主链损失 `0.05/0.05`、阈值 `0.003`、连续 3 次降学习率后停止、`init_from=null`。

## Decisions

- validation 的活动科学契约是 200 个 PDB 上的 `0:1:1`；训练仍为 `0:5:5`。旧 `0:5:5` validation 选择已经被覆盖，不保留备份。
- 若 batch 8 发生 CUDA OOM，可在同一任务中把 batch 降为 6，并保持全局 batch 48；发生这种调整时必须补写执行记录和新的 handoff。
- 若现有科学契约无法继续训练，可以做最小、证据驱动的调整，但必须记录调整原因、具体差异和新 release/launch。
- 不使用 heartbeat。a4 稳定前做短间隔定向检查；稳定后使用命令自然睡眠 10--30 分钟，随后可扩大到 1 小时。
- 只在启动、错误、稳定训练、validation/checkpoint、退出或锁变化等明确事件补写日志，不记无事件流水账。

## Risks To Check

- batch 8 当前占用约 79.8/81.6 GB H100 显存，余量较小但已持续训练 10 分钟。若出现明确 CUDA OOM，再按用户授权降为 batch 6；不能仅因显存接近上限提前改参。
- 历史 a2 曾出现 `torch_shm_manager: Invalid argument`。04:11 已按 a4 最后一次 `Seed set to 3407` 切片错误文件，a4 没有同类新错误；后续检查仍必须区分旧错误与 a4 新错误。

## Next Actions

1. 使用命令自然睡眠 1 小时，醒来后只检查 Job `346737` 的 a4 主进程、worker、H100、a4 日志、W&B、checkpoint 和锁。
2. 只有明确事件才补写执行记录或新的 handoff。
3. 不创建 heartbeat，不删除 `after_lock_346737`。

## Files To Reopen

- `C:\Users\15919\Desktop\AdaLigand\文档\exec_plan\Stage1第三版训练启动与监视记录.md`
- `C:\Users\15919\Desktop\AdaLigand\文档\规划文档\BOX-level数据契约.md`
- `C:\Users\15919\Desktop\AdaLigand\文档\规划文档\Stage1第三版训练IO实施计划.md`
- `C:\Users\15919\Desktop\AdaLigand\文档\mapping\计划执行映射.md`
- `C:\Users\15919\Desktop\Pocket_Plus\训练与运行\sh\unet_c1.sh`
