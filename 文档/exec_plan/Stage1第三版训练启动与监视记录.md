# Stage1 第三版训练启动与监视记录

本文记录 Stage1 第三版训练 I/O 实现完成后，Job `346737` 的一次正式接管、启动和阶段性监视。本文是运行历史，不改写当前训练契约；训练入口、数据字段和损失定义仍以 `文档/规划文档/Stage1第三版训练IO实施计划.md`、`文档/规划文档/BOX-level数据契约.md` 以及 Pocket_Plus 的正式入口为准。

## 记录范围

- 本文只覆盖 Job `346737`，不记录、不检查、不操作其他 Job。
- 运行目标是单卡 H100、16 CPU、16 个 Dataset worker 的 `unet_c1` 主链辅助损失版本。
- 本文覆盖一次性接管过程、正式执行启动证据和已经发生的稳定性检查；不把无事件的睡眠过程写成逐次流水账。
- 服务器控制文件由 Job 专属目录管理；`after_lock_346737` 在本记录期间一直保留，表示 allocation 仍由用户持有。

## 依据与运行位置

本记录实现并补充 `文档/exec_plan/Stage1第三版训练IO与入口实施.md` 中“正式训练需用户明确授权”的后续运行部分；用户已明确授权使用 `kill_lock_346737` 接管该 Job。

本次运行使用以下服务器位置：

- Job 专属任务根：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/task_root/Pocket_Plus`。
- Job 控制目录：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/feedback/allocations/346737`。
- 当前重训 release：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/feedback/releases/Pocket_Plus_8139f528eebc/Pocket_Plus`。
- 当前重训 launch：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/feedback/launches/346737/tmp_stage1_mainchain_job346737_20260818T035126_a4`。
- 正式输出目录：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/runtime/mainchain_official_346737`。

## 已发生事件

| 时间或阶段 | 事件 | 证据与结果 |
| --- | --- | --- |
| 2026-08-17 18:35:38 提交、19:15:09 获得资源 | Job `346737` 获得 `hnode02` 上的单张 H100 和 16 CPU，启用 `--after_hold`。 | `scontrol show job 346737`；`after_lock_346737` 保留。 |
| 第一次、第二次执行 | 既有 `a1`（19:16:14）和 `a2`（19:33:21）执行的是专属目录中的临时 `tmp_stage1_mainchain.sh`。第二次执行出现多次 `torch_shm_manager: Invalid argument`，随后被当前接管流程终止。 | 旧 launch：`.../tmp_stage1_mainchain_job346737_20260817T191614_a1`、`..._20260817T193321_a2`；错误仅作为历史背景保留，不与新执行段混淆。 |
| 接管前 | 通过 Pocket_Plus 正式安全同步入口更新共享代码，再以非删除式复制更新 346737 的专属任务根；`unet_c1.sh`、`src/train.py`、`src/datasets/stage1_dataset.py` 和 `src/datasets/stage1_requests.py` 的 SHA-256 在共享目录和专属任务根逐项相同。 | 复制没有删除专属任务根中的临时文件，也没有触碰其他 Job。 |
| 接管阶段 | 按用户授权创建 `kill_lock_346737`。执行器终止旧命令组、删除该 kill lock 并创建 `try_lock_346737`；`after_lock_346737` 未删除。 | 控制目录状态和 allocation 输出均显示旧命令已停止、资源仍保留。 |
| try lock 阶段 | 将 `run_cmd_346737.sh` 原子替换为正式 `训练与运行/sh/unet_c1.sh` 包装命令，并通过 `bash -n`。包装命令只设置 Job 专属输出根、有效 `TMPDIR` 和 `UNET_C1_VARIANT=mainchain`。 | `run_cmd_346737.sh` 回读通过；未执行其他 Job 的命令。 |
| 2026-08-17 20:59:07 | 删除 `try_lock_346737`，启动第 3 次执行。 | 新 release 为 `Pocket_Plus_b150098bfd62`，新 launch 为 `..._a3`；正式命令行包含 `train.devices=1`、`train.num_workers=16`、`train.prefetch_factor=4`、主链损失权重 `0.05/0.05`。 |
| 第一次稳定检查 | 新执行完成初始化并进入 GPU 计算；16 个 Dataset worker 已出现，未在新执行段发现旧的共享内存错误。 | H100 利用率约 100%，显存约 62.7 GB；W&B run 为 `lolou7cc`。 |
| 2026-08-18 01:46:11 醒来检查 | 经过一次 20 分钟自然睡眠后，Job 仍为 `RUNNING`；主进程和 16 个 worker 存活，H100 利用率约 83%，显存约 62.9 GB。 | W&B `wandb-summary.json` 报告 `epoch=0`、`trainer/global_step=1505`；新执行段错误筛选为空；`try_lock` 与 `kill_lock` 缺失，`after_lock` 仍存在。 |
| 2026-08-18 02:49:21--02:52:44 醒来与定向核对 | 一小时自然睡眠后，Job 仍为 `RUNNING`。通过 `srun --jobid=346737 --overlap` 定向核对到 GPU 计算进程 `PID 76836`：运行约 5 小时 54 分、CPU 约 97%，H100 利用率 97%、显存约 62.9 GB；锁状态未变且新执行段无错误。 | W&B `run-lolou7cc.wandb` 在 02:47:56 仍增长、`debug-internal.log` 在 02:52:48 更新，但 `wandb-summary.json` 仍为 `epoch=0`、`trainer/global_step=1505`，尚未出现 checkpoint。当前只确认“训练进程和 GPU 活跃、summary 刷新滞后”，尚不能据此判定训练停滞。 |
| 2026-08-18 03:46--03:48 | 用户要求按最新 `unet_c1.sh` 参数从头重训，并把 200 个 validation PDB 的冻结选择从 `0:5:5` 改为 `0:1:1`。按新授权再次写入 `kill_lock_346737`，终止 a3 并保留 `after_lock_346737`；随后在 `try_lock_346737` 存在期间覆盖发布验证选择。 | 活动 `validation_selection.npz` 为 200 个 PDB、0 个 center、3,305 个 bias、3,305 个 context；`config.json.validation_entry_ratio` 与 `summary.json.validation_selection` 同步更新，最后恢复 `_COMPLETE`。没有备份旧选择。 |
| 2026-08-18 03:51:26 | 专属任务根完成非删除式代码更新并核对关键文件 SHA-256 后，删除全局 `try_lock_346737`，启动第 4 次执行 a4。 | release 为 `Pocket_Plus_8139f528eebc`，launch 为 `..._20260818T035126_a4`。冻结配置确认 batch 8、全局 batch 48、16 workers、每 epoch 40 次 validation、主链损失 `0.05/0.05`、调度器绝对改善阈值 `0.003`、连续 3 次降学习率后停止、`init_from=null`。 |
| 2026-08-18 03:56 启动阶段检查 | a4 主进程存活，正在首次 Dataset 样本与 lazy 模块初始化阶段；RSS 约 840 MB，节点内存充足，尚未进入 GPU 计算，且没有 a4 新异常。 | 当前只确认启动未退出；达到稳定训练循环后再记录 W&B、GPU 和训练步证据。 |
| 2026-08-18 04:10--04:11 稳定检查 | 经过 10 分钟命令自然睡眠后，a4 已进入训练循环。主进程持续运行，训练与验证 DataLoader 的两个 16-worker 池存活；H100 利用率 100%，显存 79,824/81,559 MiB。 | W&B run 为 `hqumqkex`，`trainer/global_step=65`、`epoch=0`，五项 step loss 均为有限值。按 a4 最后一次 `Seed set to 3407` 切片检查错误文件，没有新 Traceback、OOM、`torch_shm_manager` 异常或 RuntimeError；batch 8 暂不下调。 |
| 2026-08-18 04:43--04:44 二次稳定检查 | 经过 30 分钟命令自然睡眠后，Job 仍为 `RUNNING`，主进程和两个 16-worker 池存活；H100 快照利用率 67%，显存 79,826/81,559 MiB。 | W&B `hqumqkex` 前进到 `trainer/global_step=245`、`epoch=0`，五项 step loss 仍为有限值；a4 错误切片为空，锁状态正常，尚无 checkpoint。后续自然睡眠间隔可扩大到 1 小时。 |
| 2026-08-19 19:41--19:42 持续目标首次检查 | 用户为本对话建立持续目标：只监视 Job `346737`，出现可恢复故障时在同一训练范围内修复并留痕，直到训练正常完成。Job 已连续运行约 48 小时，H100 快照利用率 96%，显存 80,708/81,559 MiB；a4 错误切片为空。 | W&B `hqumqkex` 前进到 `trainer/global_step=10,421`、`epoch=0`。最新验证配体体素 PRAUC 为 `0.523583`，已有最高 TOP 文件为 `TOP_epoch_00_score_0.5382.ckpt`；`BEST.ckpt`、`last.ckpt` 和十个 TOP checkpoint 已发布。 |
| 2026-08-20 00:21--00:22 新最佳检查 | 本机私网 SSH 路由在一次 60 分钟睡眠结束时暂时超时；30 分钟命令睡眠后重新连接成功，Job 始终为 `RUNNING`。H100 快照利用率 98%，显存 80,454/81,559 MiB；33 个训练相关 Python 进程存活，a4 错误切片为空。 | W&B `hqumqkex` 前进到 `trainer/global_step=11,624`。最新验证配体体素 PRAUC 为 `0.551052`；`TOP_epoch_00_score_0.5511.ckpt` 与 `last.ckpt` 已于 2026-08-19 23:15 发布，成为当前新最高 TOP。SSH 路由超时没有改变训练进程、checkpoint 或锁。 |

## 当前训练契约证据

| 配置项 | 当前值 | 证据 |
| --- | --- | --- |
| 训练入口 | `训练与运行/sh/unet_c1.sh` | 第 4 次 launch 的动态命令回读 |
| 数据划分 | V3 `box_pool`，根目录为 `stage1_preparation_box_pool_3` | frozen `config.yaml` 中的 `box_pool_root` |
| GPU 与 worker | 单卡 H100；每个 rank 16 workers | Slurm 资源、命令行和 `Worker Config: Requested=16, Available=16, Using=16` |
| 主链辅助损失 | protein `0.05`；nucleic `0.05` | 第 4 次 Python 命令行与 `config.yaml` |
| 配体距离损失 | `0.3` | frozen `config.yaml` |
| 数据加载参数 | `prefetch_factor=4`、`persistent_workers=false` | frozen `config.yaml` 与正式实现 |
| 优化与验证 | batch 8；全局 batch 48；每 epoch 40 次 validation；调度器绝对改善阈值 `0.003` | 第 4 次 `config.yaml` |
| 当前进度 | W&B `hqumqkex`；`trainer/global_step=11,624`、`epoch=0`；最新验证配体体素 PRAUC `0.551052` | 2026-08-20 00:22 的 `wandb-summary.json` |
| 当前 checkpoint | `BEST.ckpt`、`last.ckpt`；最高 TOP 为 `TOP_epoch_00_score_0.5511.ckpt` | 2026-08-20 00:22 的服务器文件清单 |

## 后续监视规则

Job `346737` 的 a4 已稳定运行约 48 小时。后续使用命令执行 1 小时自然睡眠；睡眠期间不发送消息，醒来后只检查同一 Job 的 Slurm 状态、锁、训练进程、GPU、W&B/checkpoint 和 a4 新错误。没有明确事件时不追加记录、不创建 heartbeat、不修改 `run_cmd_346737.sh`，也不删除 `after_lock_346737`。

明确事件包括：训练退出或失败、checkpoint/BEST 产生、epoch 或验证阶段发生可确认变化、GPU/进程异常、锁状态变化，或用户要求接管/释放。下一次有明确事件时，将把本次之后的观测与本文合并补记。

## 计划与实现差异

- 有益差异：用户授权后使用 Job 专属任务根和独立输出根启动正式入口，保留 allocation 的 `after_lock`，避免把运行证据混入共享默认目录。
- 中性差异：既有临时脚本的两次尝试被保留在历史 launch 中；正式第 3 次执行改用统一 `unet_c1.sh`，不改变模型、损失或数据契约。
- 有益差异：用户后续把冻结验证从 `0:5:5` 收窄为 `0:1:1`，并把 CPC1/CPC2 的绝对改善阈值统一为 `0.003`；a4 从头训练，采用 batch 8、每 epoch 40 次 validation 和最新正式入口。
- 有害差异：截至 2026-08-18 01:46:11 未发现。
- 未完成范围：本次仅启动并监视主链版 `unet_c1`；无主链双卡版本、Find 系列训练和新版推理程序不在本文范围内。
