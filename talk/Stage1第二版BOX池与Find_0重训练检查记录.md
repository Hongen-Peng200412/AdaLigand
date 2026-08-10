# Stage1 第二版 BOX 池与 Find_0 重训练检查记录

本文记录第二版 Stage1 BOX 池、Find_0 CPC1 与后续同池 unet_c1 的服务器作业身份、运行状态、产物地址和验收结论。科学目的、请求定义和恢复边界由 `文档/exec_plan/Stage1第二版BOX池与Find_0重训练实施.md` 维护；本文不替代 BOX 字段契约或训练配置。

## 固定实验契约

- 旧准备根 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation` 保持不变；第二版准备根是 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2`。
- train 与 validation 都使用一次生成后冻结的 `0 center + 5 bias + 5 context`。
- bias 保留旧的配体尺寸相关球内偏移，并叠加独立方向、长度均匀分布于 0–3 Å 的物理漂移。
- context 从完整图所有合法 80³ 起点均匀抽样，不设置受体原子数量下限。
- 新 Find_0 只运行 CPC1；双 H100、每卡批量 6、全局批量 48、学习率 `5e-5`、`warmup_ratio=0.005`、在线 W&B。
- 正式脚本、配置和产物不新增哈希机制；任务外临时审计允许使用哈希。

## 2026-08-05：实现、排队与第二版 BOX 池启动

- Pocket_Plus 共同基点：`Learn/CUMULATIVE@ff0caa6371e3455b497964971fe5335f53f2b0dd`。
- Pocket_Plus 实现分支：`codex/stage1-box-pool-2`。
- 实现端点：`13cff42`；核心实现提交为 `58c3e10`。
- 定向测试：`tests/datasets/test_stage1_dataset.py` 共 20 项通过；三个正式 shell 入口通过 `bash -n`；独立只读复核没有发现阻断。
- 双 H100 预占训练作业：Job 336298，提交参数为 GPU 2、CPU 48、`pre_hold+after_hold`。当前为 `PENDING(Resources)`，尚无 release、launch、pre_lock 或训练进程。
- 第二版 BOX 池 CPU 父数组：Job 336412，24 个分片、每个分片 8 CPU、`cpu96` QOS，不启用资源保留。正式入口是 `ops/box_pool_2/build_box_pool_2.sh`。
- 首批实际数字 Job 336413–336430 对应数组分片 0–17，已取得资源；分片 18–23 因 `QOSMaxCpuPerUserLimit` 排队。该账户当前 `cpu96` 的单用户上限是 192 CPU，另有既存 CPU16 保留作业，因此限流符合调度契约。
- 数组使用冻结 release `Pocket_Plus_788b418871d5`。启动约两分钟后已发布 1,682 份 train NPZ，当前日志没有 traceback、OOM、进程被杀或身份错误。

后续只有全部 24 份分片状态齐全后才提交 `ops/box_pool_2/finalize_box_pool_2.sh`。最终发布必须核对 train/validation 集合、单 PDB 字段与起点范围、配置 `0:5:5`、冻结 validation 请求、训练请求真实展开和根 `_COMPLETE`。验收前不释放 Job 336298 的 `pre_lock`；验收后根据 H100 实时队列，按用户授权最多依次停止旧 unet_c1 Job 321107 和旧 Find_1 Job 321540，以便 Job 336298 取得资源。

## 2026-08-05 00:40：24 个 BOX 池分片完成

- Job 336412 已离开活动队列；实际数字 Job 336413–336430、336448、336450–336453 全部为 `COMPLETED 0:0`。
- `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2/box_pool` 当前有 13,710 份 train NPZ 和 200 份 validation NPZ。
- `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2/run_state/box_pool` 具有从 `shard_000_of_024.json` 到 `shard_023_of_024.json` 的完整 24 份状态。
- 根 `_COMPLETE` 尚未发布；当前只执行一次 finalize 前独立只读复核。复核通过后才提交 `ops/box_pool_2/finalize_box_pool_2.sh`，Job 336298 的 H100 启动门保持关闭。
- 自动化身份已纠正：另一对话继续使用原 `adaligand-stage1`，本对话只使用独立的 `adaligand-stage1-boxpool2`，不会覆盖前者。

## 2026-08-05 01:03：最终发布、split 版本与 H100 切换

- 独立只读复核确认正式冻结 split 共 13,914 个 PDB 身份：train 13,714、validation 200；24 份状态无缺失、额外或重复。4 个合法 train 短图为 `5ocu`、`6tql`、`6wcb`、`7sar`。
- CPU16 Job 336466 使用正式入口 `ops/box_pool_2/finalize_box_pool_2.sh` 成功发布根 `_COMPLETE`。摘要为 train 13,714 请求/13,710 发布/4 短图，validation 200/200；冻结 validation 共有 3,281 个 occurrence、16,405 个 bias 请求、16,405 个 context 请求、0 个 center 请求。
- 临时深验收 Job 336494 逐项读取 13,910 份 NPZ，核对字段、dtype、形状、500 个 context 候选、完整图形状对应的 80³ 起点范围与冻结请求，最终结论 `PASS`。证据为 `/storage/penghongen/tmp/stage1_boxpool2_acceptance_336494/acceptance.json`。
- 用户提醒存在两个 split 版本后，额外核对确认本轮读取的是正式过滤版 `/stage1_preparation/split`。其 train 有 13,714 个唯一 PDB，16 个辅助标签排除编号命中 0；历史源 `/stage1_preparation/adaligand_stage1_20260721T024000/split` 有 13,719 个 train PDB，仍含 5 个实际存在的排除编号。第二版 pool 没有版本选错。
- H100 切换前证据保存于 `/home/penghongen/My_Project/tmp/stage1_boxpool2_h100_switch/snapshot_before_cancel_20260805T010110.txt`。旧 unet_c1 Job 321107 在 step 36,824，`BEST.ckpt` 对应 `TOP_epoch_00_score_0.1918.ckpt`；旧 Find_1 Job 321540 在 step 29,339，最近配体区域 PR-AUC 为 0.6619786620，checkpoint 和 W&B 均完整。
- 已按授权顺序取消 Job 321107；其状态为 `CANCELLED by 1351` 并已离开队列。随后核对新 Job 336298 仍为两张 H100 的 `PENDING(Resources)`，再取消旧 Find_1 Job 321540；当前等待后者从 `COMPLETING` 离开及 Job 336298 建立 `pre_lock`。

## 2026-08-05 01:24：H100 取得、启动 bug 与 a2 恢复

- Job 321107 与 Job 321540 最终均为 `CANCELLED by 1351`。取消期间 hnode01、hnode02 曾短暂出现 `Kill task failed` 并进入 DRAIN；01:12 两节点已自行恢复为 `mixed`，`scontrol listpids` 也确认两个旧 Job 不再存在于节点。
- Job 336298 于 01:10 取得 hnode01 的两张 H100。正式 `pre_lock` 的准确路径是 `/home/penghongen/Feedback/Pocket_Plus/allocations/pre_lock_336298`；删除前已核对作业名、用户、节点、正式脚本、第二版 pool 根 `_COMPLETE` 和服务器三个关键文件与本地实现内容一致。
- attempt a1 使用 release `Pocket_Plus_e4e8704be491`、launch `Find_0_job336298_20260805T011602_a1`，在 `src/train.py` 导入最前段失败。根因是当前项目工作树缺少 `rootutils` 所需的既有项目根标记 `.project-root`，因此 release 也没有该文件；模型、Dataset 和 GPU 均尚未初始化。
- 最小修复只新增空标记文件 `Pocket_Plus/.project-root`，实现提交为 `d4ec7e1`。服务器项目根已精确补入该文件；同一 allocation 的动态命令仅把标准错误合并到标准输出，以避免 a1 独立 `err` 文件延迟显示诊断文本，没有改变训练参数或科学逻辑。
- attempt a2 使用 release `Pocket_Plus_ad9875ec1f0a`、launch `Find_0_job336298_20260805T012342_a2`。01:24 已创建正式运行目录与源码快照，配置核对为第二版准备根、Find_0 CPC1、双 H100、每卡批量 6、全局批量 48、学习率 `5e-5`、`warmup_ratio=0.005`、在线 W&B；当前处于模型实例化阶段，无 `try_lock`、`kill_lock` 或新异常。

## 2026-08-05 01:40：Find_0 进入训练并启动同池 unet_c1

- Job 336298 attempt a2 已完成 DDP 2/2 注册。W&B run ID 为 `8z7x9dnl`，01:38 的摘要为 `trainer/global_step=23`；总损失、原子损失、受体损失、配体体素损失和伪原子损失均为有限值。两张 H100 分别使用约 80.86 GiB 和 80.95 GiB 显存，采样利用率为 54% 和 100%，没有 OOM。allocation 只有 `after_lock_336298`；日志中的 `Traceback` 是 attempt a1 的历史根标记错误，不属于 a2。
- 新 unet_c1 正式入口为 `Pocket_Plus/训练与运行/sh/train_2/unet_c1.sh`，实现提交为 `4b0873a`。它复用第二版准备根，单 H100、每卡批量 6、全局批量 48、学习率 `1e-4`、`warmup_ratio=0.005`、在线 W&B，不启动 CPC2；独立只读复核与 `bash -n` 均通过。
- Job 336538 以 GPU 1、CPU 48、`pre_hold+after_hold` 提交并立即取得 hnode02。删除 `pre_lock_336538` 前已核对 Slurm 身份、脚本、第二版 pool 根 `_COMPLETE` 与服务器精确同步内容。attempt a1 使用 release `Pocket_Plus_803f3349868d`、launch `unet_c1_job336538_20260805T013552_a1`，运行目录为 `/home/penghongen/Feedback/Pocket_Plus/logs/AdaLigand_Stage1-unet_c1_box_pool_2/unet_c1_box_pool_2____unet_c1_job336538_20260805T013552_a1_formal`。
- 01:40 时 unet_c1 的 resolved 配置已确认 batch 6、global 48、单卡、学习率 `1e-4`、warmup `0.005` 与 `offline=false`。随后 a1 在 `trainer.fit` 前报 `CUDA unknown error` 并进入 `try_lock_336538`，没有产生训练步或 checkpoint。
- allocation 内独立 PyTorch CUDA 测试复现同一错误；GPU 的行重映射状态为 `Pending: Yes`，内核历史信息明确要求 reset GPU 才能激活。由此确认故障属于 hnode02 分配到的 H100，和第二版 pool、unet 模型、batch 6、W&B 或正式脚本无关。证据目录为 `/home/penghongen/My_Project/tmp/stage1_boxpool2_unet_336538_cuda_failure`。
- 01:48 取消并释放 Job 336538，最终状态为 `CANCELLED by 1351`。01:49 用同一 `训练与运行/sh/train_2/unet_c1.sh` 提交 A800 恢复 Job 336558：GPU 1、CPU 24、`cpu96` QOS、`pre_hold+after_hold`；batch 6/global 48、学习率、warmup、数据和在线 W&B 契约均不变。
- Job 336558 于 01:49 取得 gnode09 一张 A800。01:54 删除 `pre_lock_336558` 前，已核对 Job 名、用户、节点、A800 GRES、正式脚本语法、第二版 pool `_COMPLETE`、batch 6/global 48、学习率 `1e-4`、warmup `0.005`、在线 W&B 和 `after_lock_336558`；当前开始首次冻结 release 与执行。
- attempt a1 使用 release `Pocket_Plus_803f3349868d`、launch `unet_c1_job336558_20260805T015223_a1`，运行目录为 `/home/penghongen/Feedback/Pocket_Plus/logs/AdaLigand_Stage1-unet_c1_box_pool_2/unet_c1_box_pool_2____unet_c1_job336558_20260805T015223_a1_formal`。24 CPU 中正式启用 20 个 worker；01:55 处于模型与数据初始化，无 try/kill 锁。

## 2026-08-05 02:29：两项训练联合健康检查 1/3

- Find_0 Job 336298 attempt a2 推进到 `trainer/global_step=200`；总损失、原子损失、受体损失、配体体素损失与伪原子损失均有限。两张 H100 分别使用约 80.74 GiB 和 79.44 GiB，采样利用率均为 98%。
- unet_c1 Job 336558 attempt a1 已越过初始化，W&B run ID 为 `dvc1ubk4`，推进到 `trainer/global_step=113`；总损失、受体损失、配体体素损失、蛋白主链损失、核酸主链损失与配体距离损失均有限。A800 使用约 67.20 GiB，利用率 100%。
- 两个训练进程的实际环境变量 `ADALIGAND_STAGE1_PREPARATION_ROOT` 均精确为 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2`。配置分别保持 Find_0 的双卡、学习率 `5e-5`，以及 unet_c1 的单卡、学习率 `1e-4`；两者均为 batch 6/global 48、warmup `0.005`、在线 W&B。
- 两项均为 `RUNNING`，各自只有 `after_lock`；当前正式运行日志错误扫描为空，没有 OOM、traceback、数据失效或身份漂移。本次计为连续双健康检查第 1 次。

## 2026-08-05 03:00：两项训练联合健康检查 2/3

- Find_0 Job 336298 attempt a2 推进到 `trainer/global_step=308`；当前总损失为 `0.4900423`，原子、受体、配体体素和伪原子损失分别为 `0.2700313`、`0.2045962`、`0.1743740` 和 `0.2517735`，均为有限值。两张 H100 分别使用约 80.83 GiB 和 80.46 GiB；采样时利用率为 17% 和 23%，但 W&B 摘要、内部日志和训练步持续刷新，没有停滞证据。
- unet_c1 Job 336558 attempt a1 推进到 `trainer/global_step=260`；当前总损失为 `0.3047090`，受体、配体体素、蛋白主链、核酸主链和配体距离损失分别为 `0.2853343`、`0.2439663`、`0.3114263`、`0.3004903` 和 `0.00537840`，均为有限值。A800 使用约 67.20 GiB，利用率 100%。
- 两项实际训练进程的 `ADALIGAND_STAGE1_PREPARATION_ROOT` 再次核对为 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2`。resolved 配置继续满足 batch 6/global 48、各自学习率、warmup `0.005` 和在线 W&B 契约；两项均只有 `after_lock`，错误扫描为空，尚未保存首次 checkpoint。本次计为连续联合健康检查第 2 次。

## 2026-08-05 03:29：两项训练联合健康检查 3/3

- Find_0 Job 336298 attempt a2 推进到 `trainer/global_step=407`；当前总损失为 `0.4696113`，原子、受体、配体体素和伪原子损失分别为 `0.2495809`、`0.2117451`、`0.1726717` 和 `0.2618416`，均为有限值。两张 H100 分别使用约 80.59 GiB 和 80.48 GiB，采样利用率为 54% 和 51%。
- unet_c1 Job 336558 attempt a1 推进到 `trainer/global_step=386`；当前总损失为 `0.3061380`，受体、配体体素、蛋白主链、核酸主链和配体距离损失分别为 `0.2955504`、`0.2461900`、`0.2998029`、`0.3001035` 和 `0.00132562`，均为有限值。A800 使用约 67.20 GiB，利用率 100%。
- 两项实际训练进程继续指向第二版准备根，各自只有 `after_lock`；在线 W&B 持续刷新，当前错误扫描为空，尚未保存首次 checkpoint。本次为连续联合健康检查第 3 次，后续监控间隔调整为每 3 小时。

## 2026-08-05 06:37：Find_0 OOM 与 allocator 原位恢复

- Find_0 Job 336298 attempt a2 实际于 03:55 结束并进入 `try_lock`。最后一个 W&B 摘要为 `trainer/global_step=491`；当前总损失、原子损失、受体损失、配体体素损失和伪原子损失仍有限，但随后 rank 1 在 RAUNet 反向重计算中申请 750 MiB 失败。错误现场为 H100 总容量 79.10 GiB、空闲 471.75 MiB、PyTorch 已分配 74.46 GiB、保留但未分配 3.15 GiB；这是实际 CUDA OOM，不是历史日志或身份误判。
- attempt a2 没有保存 checkpoint，因此无法从 step 491 恢复。完整 allocation 输出、原动态命令、锁、GPU 状态和 OOM 摘要已保存到 `/home/penghongen/My_Project/tmp/stage1_boxpool2_find0_336298_oom_20260805T0355`。
- 按用户对 OOM 自主修复的授权，主 agent 先在同一 H100 allocation 验证 PyTorch 2.4.1 接受 `expandable_segments` 配置，然后只修改 Job 336298 的动态命令：增加 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`，并绝对路径固定使用 a2 的冻结 release `Pocket_Plus_ad9875ec1f0a`。batch 6/global 48、模型、数据、学习率、warmup 和所有损失均未改变。
- 06:37 删除准确的 `/home/penghongen/Feedback/Pocket_Plus/allocations/try_lock_336298`，保留 `after_lock`，启动 attempt a3。allocation runner 为本次尝试建立的 launch 是 `Find_0_job336298_20260805T063728_a3`，其记录 release 为 `Pocket_Plus_ed3edf4ab38c`；实际训练入口由动态命令明确固定到 `Pocket_Plus_ad9875ec1f0a`。新运行目录独立，不覆盖 a2。
- unet_c1 Job 336558 同期推进到 `global_step=1229`；六项当前训练损失有限，A800 使用约 67.20 GiB 且利用率 100%，第二版数据根、在线 W&B、进程和锁正常。为尽快确认 a3 是否越过初始化并避免 OOM 复现，heartbeat 临时恢复为每 30 分钟。

## 2026-08-05 07:10：Find_0 attempt a3 健康检查 1/3

- Find_0 Job 336298 attempt a3 已完成双卡初始化并写入在线 W&B run `ax7n3y7i`，推进到 `trainer/global_step=80`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.4549933`、`0.1492338`、`0.1487268`、`0.2614607` 和 `0.2942608`，均为有限值。两张 H100 各使用约 76.68 GiB，采样利用率为 39% 和 48%；实际数据根仍精确指向第二版准备根，作业只有 `after_lock`，当前训练错误扫描为空。
- 完整 DDP 日志明确出现 `expandable_segments not supported on this platform`。这证明仅导入 PyTorch 时“接受该环境变量”不能证明 H100 平台实际支持该分配器模式；attempt a3 的训练契约没有改变，但该设置没有提供预期的防碎片化保护。当前训练仍健康，因此不主动中断；若真实 OOM 再次发生，则按既定恢复边界把每卡批量从 6 改为 4、梯度累积从 4 改为 6，继续保持全局批量 48，并精确记录这一工程性契约变化。
- unet_c1 Job 336558 同期推进到 `trainer/global_step=1403`；当前总损失、受体损失、配体体素损失、蛋白主链损失、核酸主链损失和配体距离损失分别为 `0.3307080`、`0.2857675`、`0.2717077`、`0.3023773`、`0.2998637` 和 `0.00103825`，均为有限值。A800 使用约 67.20 GiB、利用率 100%，第二版数据根、在线 W&B、进程和唯一 `after_lock` 正常。本次计为 Find_0 attempt a3 连续健康检查第 1 次。

## 2026-08-05 07:40：Find_0 attempt a3 健康检查 2/3

- Find_0 Job 336298 attempt a3 推进到 `trainer/global_step=206`；当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.5877091`、`0.2974105`、`0.2881166`、`0.2330770` 和 `0.2841001`，均为有限值。两张 H100 分别使用约 76.68 GiB 和 77.42 GiB，利用率为 91% 和 98%。训练进程继续从冻结 release `Pocket_Plus_ad9875ec1f0a` 执行，数据根仍精确指向第二版准备根；只有 `after_lock`，W&B 与内部日志持续刷新，当前没有新的 OOM 或未处理异常。
- unet_c1 Job 336558 推进到 `trainer/global_step=1460`；当前总损失、受体损失、配体体素损失、蛋白主链损失、核酸主链损失和配体距离损失分别为 `0.2980212`、`0.2678983`、`0.2410973`、`0.2971648`、`0.3002198` 和 `0.000882709`，均为有限值。A800 使用约 67.20 GiB、利用率 100%；第二版数据根、在线 W&B、进程和唯一 `after_lock` 正常。
- 两项仍未保存首次 checkpoint。本次计为 Find_0 attempt a3 连续健康检查第 2 次；下一次若仍健康，则把监控间隔恢复为每 3 小时。

## 2026-08-05 08:10：Find_0 attempt a3 健康检查 3/3

- Find_0 Job 336298 attempt a3 推进到 `trainer/global_step=320`；当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.4256353`、`0.2420914`、`0.1736932`、`0.1450129` 和 `0.2116157`，均为有限值。两张 H100 分别使用约 76.68 GiB 和 77.42 GiB，利用率均为 100%；冻结 release、第二版数据根、W&B、进程和唯一 `after_lock` 正常，当前错误扫描为空。
- unet_c1 Job 336558 的 W&B 摘要仍为 `trainer/global_step=1460`，最近六项损失均有限；摘要文件自 07:20 暂未刷新，但 W&B 二进制事件文件与内部日志持续更新到 08:09，A800 使用约 67.20 GiB、利用率 99%，训练进程、第二版数据根和唯一 `after_lock` 正常，没有停滞证据。
- 两项仍未保存首次 checkpoint。本次为 Find_0 attempt a3 连续健康检查第 3 次；监控间隔恢复为每 3 小时。`expandable_segments` 仍按不受当前 H100 支持处理，若 OOM 复现则执行每卡 batch 4、累积 6、全局批量 48 的恢复方案。

## 2026-08-05 11:16：Find_0 attempt a3 越过旧 OOM 终点

- Find_0 Job 336298 attempt a3 推进到 `trainer/global_step=1019`，已经越过 attempt a2 的 OOM 终点 step 491。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.4249582`、`0.1862133`、`0.1939919`、`0.1957287` 和 `0.2361706`，均为有限值。两张 H100 分别使用约 79.10 GiB 和 78.51 GiB；W&B 摘要、二进制事件文件和内部日志持续更新到 11:16，当前错误扫描为空。
- unet_c1 Job 336558 的摘要仍为 `trainer/global_step=1460` 和此前六项有限损失；摘要文件暂未刷新，但 W&B 二进制事件文件与内部日志持续更新到 11:14，A800 使用约 67.20 GiB、利用率 99%，训练进程和第二版数据根正常，没有停滞证据。
- 两项 Slurm 状态均为 `RUNNING`，实际训练进程继续指向第二版准备根，各自只有 `after_lock`，尚无首次 checkpoint。Find_0 已越过旧 OOM 步数是恢复有效的重要证据，但不改变 `expandable_segments` 在当前平台不受支持的判断；后续仍按每 3 小时监控真实 OOM、首次验证和 checkpoint。

## 2026-08-05 12:12：按低显存结构主动重启 Find_0

- 用户要求采用 Pocket_Plus 工作树中的低显存配置从头训练，替代仍接近 H100 上限的 attempt a3。变更前为伪原子与真实原子 density cube 边长 11、各有两层 stride-2 卷积和一层 stride-1 卷积；变更后两者均为边长 9、两层 stride-2 卷积、零层 stride-1 卷积。每卡批量 6、全局批量 48、学习率 `5e-5`、`warmup_ratio=0.005`、第二版数据根、损失定义与 CPC1-only 均保持不变；脚本中的调度器 `patience` 从 2 调为 3。
- `DensityCubeEncoder` 原先拒绝 `num_conv=0`。最小修复只把参数下界从 1 放宽到 0，并继续禁止 `num_downsample=0` 且 `num_conv=0` 的无卷积编码器；没有增加兼容包装或改变前向接口。实现与定向测试保存于 Pocket_Plus 提交 `9a06734`，本地 Windows 环境和服务器正式环境各有 38 项测试通过；服务器 Hydra 组合结果为两类 cube 均为 9³、`num_conv=0`。
- 12:09 创建 Job 336298 的准确 `kill_lock_336298` 前，attempt a3 的 W&B 最后记录为 step 1214。allocation runner 按正式控制协议结束旧进程组并建立 `try_lock_336298`；主 agent 确认没有 `src/train.py` 生产进程、两张 H100 均回落到 1 MiB 后，才恢复不固定旧 release 的动态入口并删除准确 try_lock。退出码 137 来自该次显式终止，不能记为 OOM。
- attempt a4 于 12:12 启动，release 为 `/home/penghongen/Feedback/Pocket_Plus/releases/Pocket_Plus_dc0f05168815/Pocket_Plus`，launch 为 `/home/penghongen/Feedback/Pocket_Plus/launches/336298/Find_0_job336298_20260805T121230_a4`，运行目录为 `/home/penghongen/Feedback/Pocket_Plus/logs/AdaLigand_Stage1-Find_0_box_pool_2-CPC1/Find_0-box_pool_2-CPC1____Find_0_job336298_20260805T121230_a4_CPC1`。release 已核对含 9³/`num_conv=0`、最小构造修复和 `patience=3`，命令中不存在旧 11³ 覆盖或无效的 allocator 环境变量；当前处于模型与数据初始化，只有 `after_lock`。后续每 30 分钟核对 resolved 配置、首批有限损失、W&B 与显存，连续三次健康后恢复每 3 小时。

## 2026-08-05 12:55：Find_0 低显存 attempt a4 健康检查 1/3

- Find_0 已建立在线 W&B run `es683hq5`，推进到 `trainer/global_step=116`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.5996865`、`0.3009692`、`0.2980320`、`0.2394198` 和 `0.2949435`，均为有限值。W&B 事件、摘要和内部日志持续更新到 12:54，当前运行目录错误扫描为空。
- 训练进程的实际 `TASK_PROJECT_ROOT` 为 release `Pocket_Plus_dc0f05168815`，`ADALIGAND_STAGE1_PREPARATION_ROOT` 精确指向 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2`，run stamp 为 `Find_0_job336298_20260805T121230_a4_CPC1`。进程命令保持 batch 6/global 48、学习率 `5e-5`、warmup `0.005` 与 `patience=3`；release 中两类 density cube 已核对为 9³、`num_downsample=2`、`num_conv=0`。当前只有 `after_lock_336298`，尚无 checkpoint。
- 两张 H100 本次采样分别使用 80,966/81,559 MiB 与 80,094/81,559 MiB，利用率 97% 和 94%。这仍处于旧配置约 79–81 GiB 的范围，没有形成“显存显著下降”的证据；训练当前健康，但不能据此认定 OOM 风险已经消除。继续按 30 分钟观察大样本峰值与错误，不在没有真实错误时主动重启。
- unet_c1 Job 336558 仍为 `RUNNING` 且只有 `after_lock_336558`。W&B 摘要仍停在 step 1460，但 `debug-internal.log` 持续更新到 12:52；当前运行目录没有 OOM、traceback、非预期 NaN 或 checkpoint，Slurm 和日志共同表明作业没有停滞证据。本次计为 Find_0 a4 连续健康检查第 1 次。

## 2026-08-05 13:19：Find_0 低显存 attempt a4 健康检查 2/3

- Find_0 W&B run `es683hq5` 推进到 `trainer/global_step=209`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.5918606`、`0.2948396`、`0.2932305`、`0.2387133` 和 `0.2898458`，均为有限值；W&B 事件、摘要和内部日志持续更新到 13:18，当前运行目录错误扫描为空。
- 实际进程继续使用 release `Pocket_Plus_dc0f05168815` 和第二版准备根，命令保持 batch 6/global 48、学习率 `5e-5`、warmup `0.005` 与 `patience=3`。Job 336298 为 `RUNNING`，只有 `after_lock_336298`，尚无 checkpoint。
- 两张 H100 本次采样分别使用 80,962/81,559 MiB 与 80,622/81,559 MiB，利用率 31% 和 57%。这再次证明当前低显存结构没有形成显著降低整体显存占用的证据，但训练已从 step116继续推进到step209且没有真实 OOM；按契约继续观察，不仅凭高占用主动中断。
- unet_c1 Job 336558 仍为 `RUNNING` 且只有 `after_lock_336558`。其摘要仍为 step1460，但 W&B 事件文件与内部日志分别更新到 13:13 和 13:16；运行目录错误扫描为空，没有 OOM、未处理异常或停滞证据。本次计为 Find_0 a4 连续健康检查第 2 次。

## 2026-08-05 13:49：Find_0 低显存 attempt a4 健康检查 3/3

- Find_0 W&B run `es683hq5` 推进到 `trainer/global_step=311`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.4464981`、`0.2526673`、`0.1962525`、`0.1468039` 和 `0.2740164`，均为有限值；W&B 摘要和内部日志持续更新到 13:48，运行目录错误扫描为空。
- 实际进程继续使用 release `Pocket_Plus_dc0f05168815`、第二版准备根与 `Find_0_job336298_20260805T121230_a4_CPC1` 身份；命令保持 batch 6/global 48、学习率 `5e-5`、warmup `0.005` 和 `patience=3`。Job 336298 为 `RUNNING`，只有 `after_lock_336298`，尚无 checkpoint。
- 两张 H100 本次采样分别使用 79,372/81,559 MiB 与 79,998/81,559 MiB，利用率 71% 和 77%。三次检查均表明整体显存仍接近旧配置，不能声称低显存结构已经显著降低峰值；另一方面，a4 已连续推进到 step311且没有 OOM，因此继续训练并保留高显存观察项。
- unet_c1 Job 336558 仍为 `RUNNING`，只有 `after_lock_336558`；W&B 内部日志更新到 13:46，当前错误扫描为空，没有 OOM、未处理异常或停滞证据。Find_0 a4 连续健康检查完成 3/3，监控间隔恢复为每 3 小时。

## 2026-08-05 16:52：unet_c1 首次验证与 checkpoint 落盘

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=956`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3508378`、`0.1687929`、`0.1629671`、`0.1462193` 和 `0.1952888`，均为有限值。实际进程继续使用 release `Pocket_Plus_dc0f05168815`、第二版准备根与原 batch 6/global 48、学习率 `5e-5`、warmup `0.005`、`patience=3` 契约；两张 H100 使用 80,248/81,559 MiB 和 80,272/81,559 MiB。Job 为 `RUNNING`，只有 `after_lock_336298`，错误扫描为空，尚无首次 checkpoint。高显存观察项保留，但没有真实 OOM。
- unet_c1 Job 336558 推进到 `trainer/global_step=1517`，完成首次正式验证。验证总损失为 `0.3052543`；配体体素、受体、蛋白主链和核酸主链 PRAUC 分别为 `0.2536706`、`0.2309798`、`0.0363389` 和 `0.0075782`。当前六项训练损失有限，W&B 摘要和内部日志继续更新，没有 OOM 或未处理异常。
- unet_c1 已保存 `/home/penghongen/Feedback/Pocket_Plus/logs/AdaLigand_Stage1-unet_c1_box_pool_2/unet_c1_box_pool_2____unet_c1_job336558_20260805T015223_a1_formal/checkpoints/TOP_epoch_00_score_0.2537.ckpt` 与同目录 `last.ckpt`，大小均约 500 MB。Job 仍为 `RUNNING` 且只有 `after_lock_336558`。本次是第二版 BOX 池训练首次形成可恢复 checkpoint 与完整验证指标；继续每 3 小时监控，不启动 CPC2。

## 2026-08-05 19:51：两项训练继续健康推进

- Find_0 Job 336298 attempt a4 的最近摘要为 `trainer/global_step=1460`，当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.4756253`、`0.2096784`、`0.2138302`、`0.2202641` 和 `0.2429980`，均为有限值。摘要暂缓刷新，但 W&B 二进制事件文件和内部日志持续更新到 19:51，正式进程仍使用 release `Pocket_Plus_dc0f05168815`、第二版准备根及原 batch 6/global 48 契约。
- 两张 H100 本次采样分别使用 80,158/81,559 MiB 和 79,882/81,559 MiB，利用率 33% 和 76%。Job 为 `RUNNING`，只有 `after_lock_336298`，错误扫描为空且没有真实 OOM；尚无首次 checkpoint。摘要停在 step1460 不能单独解释为停滞，因为事件文件、内部日志和 GPU 计算均持续推进。
- unet_c1 Job 336558 推进到 `trainer/global_step=1775`，当前总损失、配体距离、受体、配体体素、蛋白主链和核酸主链损失分别为 `0.2509742`、`0.0016829`、`0.2701032`、`0.1929847`、`0.2960090` 和 `0.3134779`，均为有限值。首次验证指标未被新的验证覆盖；`TOP_epoch_00_score_0.2537.ckpt` 与 `last.ckpt` 继续完整存在。Job 为 `RUNNING`，只有 `after_lock_336558`，错误扫描为空。

## 2026-08-05 22:52：Find_0 首次验证与 checkpoint 落盘

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=1733` 并完成首次正式验证。验证总损失为 `0.4196117`；配体体素、受体、实际原子和伪原子 PRAUC 分别为 `0.4720177`、`0.5356513`、`0.5332157` 和 `0.4859179`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3326334`、`0.1552532`、`0.1553625`、`0.1422793` 和 `0.1956468`，均为有限值。
- refined/unrefined 面板因本模型未启用 sparse-refine loss 而按既有设计为 NaN，不作为错误；训练主损失、五项验证损失和四项 PRAUC 均有限。运行目录当前错误扫描为空，没有真实 OOM或未处理异常。
- Find_0 已保存同一运行目录 `checkpoints/` 下约 1.4 GiB 的 `TOP_epoch_00_score_0.4720.ckpt` 与 `last.ckpt`。两张 H100 本次采样使用 80,864/81,559 MiB 和 80,440/81,559 MiB，利用率 86% 和 83%；实际进程继续使用 release `Pocket_Plus_dc0f05168815`、第二版准备根及原 batch 6/global 48 契约。Job 为 `RUNNING`，只有 `after_lock_336298`。
- unet_c1 Job 336558 推进到 `trainer/global_step=2021`，当前六项训练损失均有限；首次验证总损失 `0.3052543`、配体体素 PRAUC `0.2536706` 和对应 TOP/last checkpoint 保持完整。Job 为 `RUNNING`，只有 `after_lock_336558`，W&B 和内部日志持续活动，错误扫描为空。两项继续每 3 小时监控，不启动 CPC2。

## 2026-08-06 01:51：两项训练继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=2360`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.4465013`、`0.2302295`、`0.2287425`、`0.1723570` 和 `0.2104053`，均为有限值；首次验证指标仍为总验证损失 `0.4196117` 和配体体素 PRAUC `0.4720177`，TOP/last checkpoint 完整。
- 两张 H100 本次采样分别使用 80,578/81,559 MiB 和 79,486/81,559 MiB，利用率 100% 和 99%。实际进程继续使用 release `Pocket_Plus_dc0f05168815`、第二版准备根及原 batch 6/global 48 契约。Job 为 `RUNNING`，只有 `after_lock_336298`，错误扫描为空，没有真实 OOM。
- unet_c1 Job 336558 的最近摘要为 `trainer/global_step=2039`，六项训练损失均为有限值。摘要暂缓刷新，但 W&B 二进制事件文件和内部日志持续更新到 01:49；首次验证总损失 `0.3052543`、配体体素 PRAUC `0.2536706` 与 TOP/last checkpoint 保持完整。Job 为 `RUNNING`，只有 `after_lock_336558`，没有 OOM、未处理异常或停滞证据。

## 2026-08-06 04:52：两项训练继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=2921`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2471005`、`0.1133741`、`0.1166574`、`0.1064652` 和 `0.1559548`，均为有限值；首次验证总损失 `0.4196117`、配体体素 PRAUC `0.4720177` 与 TOP/last checkpoint 保持完整。
- 两张 H100 本次采样分别使用 79,886/81,559 MiB 和 79,778/81,559 MiB，利用率 99% 和 88%。实际进程继续使用 release `Pocket_Plus_dc0f05168815`、第二版准备根及原 batch 6/global 48 契约。Job 为 `RUNNING`，只有 `after_lock_336298`，错误扫描为空，没有真实 OOM。
- unet_c1 Job 336558 的最近摘要为 `trainer/global_step=2057`，六项训练损失均为有限值；W&B 二进制事件文件和内部日志持续更新到 04:50。首次验证总损失 `0.3052543`、配体体素 PRAUC `0.2536706` 与 TOP/last checkpoint 保持完整。Job 为 `RUNNING`，只有 `after_lock_336558`，没有 OOM、未处理异常或停滞证据。

## 2026-08-06 06:49：unet_c1 A800/H100 吞吐差异定量收口

- 比较对象为当前 A800 run `pencounkdual-111/AdaLigand_Stage1/dvc1ubk4` 与历史 H100 run `pencounkdual-111/AdaLigand_Stage1/3a323sl8`。两者均为单卡、batch 6、梯度累积 8、全局批量 48、20 个 DataLoader worker 和 512 MiB 每 worker 缓存；但 BOX 池、部分源码与配置并非逐字节相同，因此没有预设“唯一差异就是 GPU 或 BOX 池”。本次只读分析和独立 CPU 复放没有修改、暂停或重启当前 GPU 作业。
- W&B 直接观测：A800 验证前为 `273.784 step/h`，GPU 利用率中位数 98%；历史 H100 为 `151.853 step/h`，GPU 利用率中位数仅 42.47%。这证明 H100 训练阶段被数据输入限制，而不是算力更弱。validation 中 A800/H100 的 GPU 利用率均值分别为 92.64%/89.57%；第二版请求数只多 11.1%，但按请求归一后 A800 耗时仍为 H100 的 1.74 倍，反转主要来自 H100 的前向计算优势。
- A800 validation 后观测平均速度只有 `58.867 step/h`，但排除至少 5 分钟的长间隔后为 `193.638 step/h`；更稳健的三步间隔中位数折算为 `272.778 step/h`，与验证前基本相同。12 个长间隔累计 6.996 小时；这些间隔中 GPU 通常为 0%–0.5%、活跃 CPU 核为 0–1、进程常驻内存稳定，说明作业是在等待数据或底层文件读取，而不是持续做慢计算。
- 三组阶段切换因果对照均使用 16 worker、batch 6、512 MiB 缓存，只运行 Dataset/DataLoader。第二版无 validation、第二版完整 32,810 请求 validation、第一版完整 29,529 请求 validation 的后置训练窗口分别比前置窗口快 2.89%、8.16% 和 6.99%；后置批次最大等待只有 44.46、50.38 和 48.78 秒。由此排除 validation 固定销毁/污染训练 DataLoader、validation 后请求天然更重及时间推移必然退化三种解释。两套完整 validation 在同一 CPU 节点并行，绝对 CPU validation 时长受相互竞争影响，未用于估计 GPU 算力。

## 2026-08-06 07:54：Find_0 第二次验证继续改善

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=3143` 并完成第二次验证。验证总损失从首次的 `0.4196117` 改善到 `0.3608155`；配体体素、受体、实际原子和伪原子 PRAUC 分别从 `0.4720177`、`0.5356513`、`0.5332157`、`0.4859179` 提升到 `0.5116482`、`0.5988029`、`0.6039660` 和 `0.5394412`。refined/unrefined 面板继续按未启用 sparse-refine loss 的设计为 NaN，其余训练损失、验证损失和指标有限。
- 新的 `TOP_epoch_00_score_0.5116.ckpt` 与 `last.ckpt` 已于 06:46 落盘；`BEST.ckpt` 当前仍与上一轮 `TOP_epoch_00_score_0.4720.ckpt` 对应，符合一次验证延迟，后续检查其是否刷新。两张 H100 使用 80,972/81,559 MiB 和 80,282/81,559 MiB，利用率 100% 和 84%；没有真实 OOM。实际进程、release `Pocket_Plus_dc0f05168815`、第二版数据根、唯一 `after_lock_336298` 与错误扫描正常。
- unet_c1 Job 336558 推进到 `trainer/global_step=2348`，六项训练损失均有限；首次验证总损失 `0.3052543`、配体体素 PRAUC `0.2536706` 与 TOP/last checkpoint 保持完整。Job 为 `RUNNING`，只有 `after_lock_336558`，W&B 和内部日志持续活动，错误扫描为空。

## 2026-08-06 10:55：两项训练继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=3731`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2893483`、`0.1441547`、`0.1470163`、`0.1162031` 和 `0.1428888`，均为有限值；第二次验证总损失 `0.3608155`、配体体素 PRAUC `0.5116482` 与新 TOP/last checkpoint 保持完整。
- `BEST.ckpt` 仍与上一轮 `TOP_epoch_00_score_0.4720.ckpt` 对应，继续按一次验证延迟等待下一次验证刷新。两张 H100 使用 80,300/81,559 MiB 和 80,620/81,559 MiB，实际进程继续使用 release `Pocket_Plus_dc0f05168815`、第二版准备根及原 batch 6/global 48 契约。Job 为 `RUNNING`，只有 `after_lock_336298`，没有真实 OOM。
- W&B 文件上传线程在 09:40–09:43 遇到数次可重试的 API 500 响应；训练进程未退出，未丢弃记录，10:55 时摘要、二进制事件和内部日志均已继续更新到 step3731，因此这是已自行恢复的平台传输警告，不是训练 traceback 或科学契约问题。
- unet_c1 Job 336558 的最近摘要为 `trainer/global_step=2921`，六项训练损失均为有限值；W&B 事件和内部日志持续更新到 10:53。首次验证总损失 `0.3052543`、配体体素 PRAUC `0.2536706` 与 TOP/last checkpoint 保持完整。Job 为 `RUNNING`，只有 `after_lock_336558`，没有 OOM、未处理异常或停滞证据。
- 主要工程风险已经定位到共享 Lustre 上的随机大文件读取：训练请求没有短距离 PDB 复用，19,200 次受控资产访问全部缓存 miss；部分 `exp.npz` 为 1.3–1.6 GiB、`ligand_dist.npz` 约 780 MiB，文件为单 stripe，Dataset 会先物化完整 NPZ 数组再裁剪 80³。16-worker 冷复放仅比当前 A800 顺畅训练需求多约 5.7% 供给余量，少量 I/O 尾延迟即可让 GPU 空转。现有证据不能把某一次 30.71 分钟空档唯一归因到某个 OST、外部作业或节点瞬时事件。
- 优化优先级：首先把大数组改为可局部读取的独立 `.npy` 加 memory map 或空间分块格式；其次为 train/validation 分开设置缓存策略、为固定 validation 使用节点侧暂存，并在受控基准后再调整 worker/CPU。PDB 局部微分组采样会改变相邻样本相关性，只能作为明确科学实验。后续监控应同时记录 batch 获取 p50/p95/p99、GPU 空转比例和累计读取增量，不能只看区间平均 step/h。
- 自包含报告：`talk/unet_c1_A800与H100吞吐定量诊断.md`。服务器证据根：`/storage/penghongen/tmp/unet_c1_throughput_audit_20260806`；机器摘要：`analysis/final_summary.json`。临时 CPU Job 335495、336466 已 `COMPLETED 0:0`；Job 336494 在有效第二版结果落盘后以准确 `kill_lock` 停止重复第一版复放，最终预期为 `FAILED 9:0`，不表示诊断失败。三个 Job 的准确 `after_lock` 均已删除，资源已释放；现有证据未删除或移动。

## 2026-08-06 13:57：两项训练继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=4331`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3294327`、`0.1551473`、`0.1606256`、`0.1407293` 和 `0.1749360`，均为有限值；第二次验证总损失 `0.3608155`、配体体素 PRAUC `0.5116482` 与新 TOP/last checkpoint 保持完整。
- `BEST.ckpt` 仍与上一轮 `TOP_epoch_00_score_0.4720.ckpt` 同尺寸、同修改时间；当前尚未产生第三次验证，因此继续等待下一次验证后的别名刷新，不把延迟误记为 checkpoint 损坏。两张 H100 本次采样分别使用 79,568/81,559 MiB 和 80,792/81,559 MiB；瞬时利用率均为 0%，但 W&B 摘要、二进制事件与内部日志在检查时持续更新，正式进程仍存在，符合已知随机大文件读取等待特征。作业为 `RUNNING`，只有 `after_lock_336298`，当前日志没有新的 W&B 上传警告、OOM 或未处理异常。
- unet_c1 Job 336558 的摘要仍为 `trainer/global_step=2921`，六项训练损失均有限；二进制事件文件与内部日志分别更新到 13:51 和 13:55，A800 使用 72,401/81,920 MiB 且利用率 100%，正式训练进程持续存在。首次验证总损失 `0.3052543`、配体体素 PRAUC `0.2536706` 与 TOP/last checkpoint 完整。作业为 `RUNNING`，只有 `after_lock_336558`，没有 OOM、异常或停滞证据。

## 2026-08-06 16:57：Find_0 与 unet_c1 新验证继续改善

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=4472` 并完成第三次验证。验证总损失从 `0.3608155` 降至 `0.3457936`；配体体素、受体、实际原子和伪原子 PRAUC 从 `0.5116482`、`0.5988029`、`0.6039660` 和 `0.5394412` 提升到 `0.5526835`、`0.6179847`、`0.6255053` 和 `0.5814264`。当前五项训练损失均有限。
- 新的 `TOP_epoch_00_score_0.5527.ckpt` 与 `last.ckpt` 已完整落盘；`BEST.ckpt` 已正确刷新到上一轮 `TOP_epoch_00_score_0.5116.ckpt`，继续表现为预期的一次验证延迟。两张 H100 使用 80,760/81,559 MiB 和 80,870/81,559 MiB，利用率 72% 和 45%；作业为 `RUNNING`，只有 `after_lock_336298`，W&B 持续活动，最近日志没有 OOM、未处理异常或新的传输警告。
- unet_c1 Job 336558 推进到 `trainer/global_step=3539` 并完成第二次验证。验证总损失从 `0.3052543` 降至 `0.2747575`；配体体素与受体 PRAUC 从 `0.2536706` 和 `0.2309798` 提升到 `0.3431777` 和 `0.3455715`，蛋白主链与核酸主链宏平均 PRAUC 为 `0.0447872` 和 `0.0001185`。新 `TOP_epoch_00_score_0.3432.ckpt` 与 `last.ckpt` 完整；`BEST.ckpt` 暂时对应上一轮 `0.2537` TOP，等待下一次验证刷新。A800 使用 72,401/81,920 MiB、利用率 98%；作业为 `RUNNING`，只有 `after_lock_336558`，W&B、正式进程和当前错误扫描正常。

## 2026-08-06 21:34：unet_c1 按用户决定停止，后续只监控 Find_0

- 用户因 Job 336558 吞吐过慢，于 17:27 主动执行 `scancel 336558`，并明确要求不再监控该作业。Slurm 最终状态为 `CANCELLED by 1351`；allocation 已离开队列且没有遗留锁，不执行恢复、接管或重新提交。
- unet_c1 最终 W&B 摘要为 `trainer/global_step=3668`，六项训练损失有限；最终已完成的验证仍为总损失 `0.2747575`、配体体素 PRAUC `0.3431777` 和受体 PRAUC `0.3455715`。`TOP_epoch_00_score_0.3432.ckpt` 与 `last.ckpt` 完整，`BEST.ckpt` 未经历下一次验证刷新，仍对应上一轮 `TOP_epoch_00_score_0.2537.ckpt`。这些产物保留，但 heartbeat 不再检查该作业。
- Find_0 Job 336298 attempt a4 同期推进到 `trainer/global_step=5426`；当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3171668`、`0.1478591`、`0.1519735`、`0.1298965` 和 `0.2421382`，均有限。第三次验证总损失 `0.3457936`、配体体素 PRAUC `0.5526835` 与新 TOP/last checkpoint 完整；`BEST.ckpt` 正确对应上一轮 `0.5116` TOP。
- 两张 H100 使用 80,854/81,559 MiB 和 80,826/81,559 MiB，利用率 68% 和 84%；Find_0 仍为 `RUNNING`，只有 `after_lock_336298`，W&B 与正式进程持续活动，没有 OOM 或未处理异常。后续每 3 小时只监控 Find_0。

## 2026-08-07 13:37：Find_0 第四、第五次验证继续改善

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=7853`。在上次检查后先保存 `TOP_epoch_00_score_0.5284.ckpt`，随后第五次验证总损失进一步降至 `0.3278278`；配体体素、受体、实际原子和伪原子 PRAUC 为 `0.5607202`、`0.6369786`、`0.6404328` 和 `0.5882578`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3239051`、`0.1509583`、`0.1564204`、`0.1358805` 和 `0.2142418`，均有限。
- 新的 `TOP_epoch_00_score_0.5607.ckpt` 与 `last.ckpt` 完整落盘；`BEST.ckpt` 已正确刷新到上一轮最佳 `TOP_epoch_00_score_0.5527.ckpt`，继续表现为预期的一次验证延迟。历史 `TOP_epoch_00_score_0.5284.ckpt` 也保留完整，没有覆盖或丢失已有候选。
- 两张 H100 使用 80,888/81,559 MiB 和 80,844/81,559 MiB，利用率 78% 和 72%。Job 为 `RUNNING`，只有 `after_lock_336298`；W&B 摘要、事件文件、内部日志与正式进程持续活动，最近日志没有 OOM、警告或未处理异常。

## 2026-08-07 16:40：Find_0 健康推进，等待第六次验证

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=8468`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2560695`、`0.1241931`、`0.1282090`、`0.1027220` 和 `0.1633347`，均为有限值；最新完成的仍是第五次验证，总损失 `0.3278278`、配体体素 PRAUC `0.5607202`。
- `TOP_epoch_00_score_0.5607.ckpt`、`last.ckpt` 与历史 TOP 候选均保持完整；`BEST.ckpt` 正确对应上一轮最佳 `TOP_epoch_00_score_0.5527.ckpt`。本次没有第六次验证，因此没有新的 checkpoint 别名变化。
- 两张 H100 使用 80,776/81,559 MiB 和 80,868/81,559 MiB，利用率 87% 和 43%。Slurm 状态为 `RUNNING`，只有 `after_lock_336298`；W&B 事件文件和内部日志持续更新，正式训练进程存在，最近日志没有 OOM、警告或未处理异常。

## 2026-08-07 19:38：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=8768`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2440135`、`0.1094993`、`0.1153643`、`0.1054720` 和 `0.1750583`，均为有限值；最新完成的仍是第五次验证，总损失 `0.3278278`、配体体素 PRAUC `0.5607202`。
- `TOP_epoch_00_score_0.5607.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；`BEST.ckpt` 正确对应上一轮最佳 `TOP_epoch_00_score_0.5527.ckpt`。本次尚无第六次验证或新的 checkpoint 别名变化。
- 两张 H100 均使用 80,876/81,559 MiB，利用率 69% 和 72%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 二进制事件和内部日志持续更新，正式训练进程存在，最近日志没有 OOM、警告或未处理异常。

## 2026-08-07 22:40：Find_0 第六次验证继续改善

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=9299` 并完成第六次验证。验证总损失从 `0.3278278` 小幅降至 `0.3270249`；配体体素、受体、实际原子和伪原子 PRAUC 分别为 `0.5624313`、`0.6284630`、`0.6433361` 和 `0.6005753`。配体体素、实际原子和伪原子 PRAUC 创下本次运行新高，受体 PRAUC 低于第五次验证的 `0.6369786`，各项数值均有限。
- 新 `TOP_epoch_00_score_0.5624.ckpt` 与 `last.ckpt` 已完整落盘；`BEST.ckpt` 已正确刷新到上一轮最佳 `TOP_epoch_00_score_0.5607.ckpt`，继续符合一次验证延迟。
- 两张 H100 使用 80,358/81,559 MiB 和 80,272/81,559 MiB，利用率 13% 和 77%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件和内部日志持续更新，正式训练进程存在，最近日志没有 OOM、警告或未处理异常。

## 2026-08-08 01:40：Find_0 健康推进，W&B 上传超时正在自动重试

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=9920`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2616243`、`0.1192876`、`0.1210741`、`0.1109935` 和 `0.1923577`，均为有限值；最新完成的仍是第六次验证，总损失 `0.3270249`、配体体素 PRAUC `0.5624313`。
- `TOP_epoch_00_score_0.5624.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；`BEST.ckpt` 正确对应上一轮最佳 `TOP_epoch_00_score_0.5607.ckpt`。本次尚无第七次验证或 checkpoint 别名变化。
- 两张 H100 使用 80,722/81,559 MiB 和 79,502/81,559 MiB，利用率 85% 和 87%。作业为 `RUNNING`，只有 `after_lock_336298`；正式训练进程、W&B 摘要、事件和内部日志持续更新。检查时上传线程记录一次可重试的 HTTP 408，证据同时显示 `dropped=0`，因此当前按平台传输瞬时警告处理，不构成训练阻断；日志没有 OOM 或未处理异常。

## 2026-08-08 04:40：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=10229`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3930888`、`0.1775579`、`0.1788286`、`0.1693245` 和 `0.2832346`，均为有限值；最新完成的仍是第六次验证，总损失 `0.3270249`、配体体素 PRAUC `0.5624313`。
- `TOP_epoch_00_score_0.5624.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；`BEST.ckpt` 正确对应上一轮最佳 `TOP_epoch_00_score_0.5607.ckpt`。本次尚无第七次验证或 checkpoint 别名变化。
- 两张 H100 使用 80,680/81,559 MiB 和 80,246/81,559 MiB，利用率 56% 和 24%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件与内部日志持续更新，上一轮可重试 HTTP 408 没有继续出现，正式训练进程存在，当前日志没有 OOM、警告或未处理异常。

## 2026-08-08 07:41：Find_0 第七次验证显著改善

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=10715` 并完成第七次验证。验证总损失从 `0.3270249` 降至 `0.3090848`；配体体素、受体、实际原子和伪原子 PRAUC 分别从 `0.5624313`、`0.6284630`、`0.6433361` 和 `0.6005753` 提升到 `0.5768888`、`0.6610140`、`0.6699396` 和 `0.6053548`，四项 PRAUC 均创下本次运行新高。
- 新 `TOP_epoch_00_score_0.5769.ckpt` 与 `last.ckpt` 已完整落盘；`BEST.ckpt` 已正确刷新到上一轮最佳 `TOP_epoch_00_score_0.5624.ckpt`，继续符合一次验证延迟。
- 两张 H100 使用 80,816/81,559 MiB 和 80,432/81,559 MiB，利用率 100% 和 98%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件与内部日志持续更新，正式训练进程存在，当前日志没有 OOM、警告或未处理异常。

## 2026-08-08 10:41：Find_0 健康推进，等待第八次验证

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=11315`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3428891`、`0.1701978`、`0.1728769`、`0.1329162` 和 `0.2248738`，均为有限值；最新完成的仍是第七次验证，总损失 `0.3090848`、配体体素 PRAUC `0.5768888`。
- `TOP_epoch_00_score_0.5769.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；`BEST.ckpt` 正确对应上一轮最佳 `TOP_epoch_00_score_0.5624.ckpt`。本次尚无第八次验证或 checkpoint 别名变化。
- 两张 H100 使用 80,428/81,559 MiB 和 80,270/81,559 MiB，利用率 79% 和 87%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件与内部日志持续更新，正式训练进程存在，当前日志没有 OOM、警告或未处理异常。

## 2026-08-08 13:41：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=11690`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3446828`、`0.1669642`、`0.1719981`、`0.1370286` 和 `0.2349013`，均为有限值；最新完成的仍是第七次验证，总损失 `0.3090848`、配体体素 PRAUC `0.5768888`。
- `TOP_epoch_00_score_0.5769.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；`BEST.ckpt` 正确对应上一轮最佳 `TOP_epoch_00_score_0.5624.ckpt`。本次尚无第八次验证或 checkpoint 别名变化。
- 两张 H100 使用 79,978/81,559 MiB 和 80,362/81,559 MiB，利用率 42% 和 77%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件与内部日志持续更新，正式训练进程存在，当前日志没有 OOM、警告或未处理异常。

## 2026-08-08 16:41：Find_0 完成第八次验证

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=12089` 并完成第八次验证。验证总损失从 `0.3090848` 降至 `0.3044009`；配体体素、受体、实际原子和伪原子 PRAUC 分别为 `0.5668026`、`0.6590984`、`0.6670865` 和 `0.6250447`。配体体素、受体和实际原子 PRAUC 未超过第七次验证，伪原子 PRAUC 与总损失创下本次运行新高。
- 新 `TOP_epoch_00_score_0.5668.ckpt` 与 `last.ckpt` 已完整落盘；`BEST.ckpt` 已正确刷新到当前全局最佳 `TOP_epoch_00_score_0.5769.ckpt`，没有被本次较低的配体体素 PRAUC 覆盖。
- 两张 H100 使用 80,880/81,559 MiB 和 80,746/81,559 MiB，利用率 40% 和 42%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件与内部日志持续更新，正式训练进程存在，当前日志没有 OOM、警告或未处理异常。

## 2026-08-08 19:42：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=12734`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2221405`、`0.0977300`、`0.1006914`、`0.0956986` 和 `0.1864274`，均为有限值；最新完成的仍是第八次验证，总损失 `0.3044009`、配体体素 PRAUC `0.5668026`。
- `TOP_epoch_00_score_0.5668.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；`BEST.ckpt` 正确对应当前全局最佳 `TOP_epoch_00_score_0.5769.ckpt`。本次尚无第九次验证或 checkpoint 别名变化。
- 两张 H100 使用 80,740/81,559 MiB 和 80,646/81,559 MiB，利用率 48% 和 45%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件与内部日志持续更新，正式训练进程存在，当前日志没有 OOM、警告或未处理异常。

## 2026-08-08 23:21：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=13151`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3390893`、`0.1488090`、`0.1520463`、`0.1504622` 和 `0.2461346`，均为有限值；最新完成的仍是第八次验证，总损失 `0.3044009`、配体体素 PRAUC `0.5668026`。
- `TOP_epoch_00_score_0.5668.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；`BEST.ckpt` 正确对应当前全局最佳 `TOP_epoch_00_score_0.5769.ckpt`。本次尚无第九次验证或 checkpoint 别名变化。
- 两张 H100 使用 80,770/81,559 MiB 和 80,614/81,559 MiB，利用率 76% 和 77%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件与内部日志持续更新，正式训练进程存在，当前日志没有 OOM、警告或未处理异常。

## 2026-08-09 01:45：Find_0 第九次验证产生新的配体体素最佳值

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=13553` 并完成第九次验证。验证总损失为 `0.3090253`；配体体素、受体、实际原子和伪原子 PRAUC 分别为 `0.5870306`、`0.6541455`、`0.6584011` 和 `0.6045898`。配体体素 PRAUC 超过第七次验证的 `0.5768888` 并创下本次运行新高；其余三项 PRAUC 未超过各自历史最佳。
- 新 `TOP_epoch_00_score_0.5870.ckpt` 与 `last.ckpt` 已完整落盘；`BEST.ckpt` 当前仍对应上一轮全局最佳 `TOP_epoch_00_score_0.5769.ckpt`，符合一次验证延迟，后续确认其是否刷新到 `0.5870`。
- 两张 H100 使用 80,818/81,559 MiB 和 80,910/81,559 MiB，利用率 64% 和 97%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件与内部日志持续更新，正式训练进程存在，当前日志没有 OOM、警告或未处理异常。

## 2026-08-09 04:46：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=14129`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3054307`、`0.1334731`、`0.1363745`、`0.1360221` 和 `0.2229794`，均为有限值；最新完成的仍是第九次验证，总损失 `0.3090253`、配体体素 PRAUC `0.5870306`。
- `TOP_epoch_00_score_0.5870.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；本次尚无第十次验证，`BEST.ckpt` 仍对应上一轮全局最佳 `TOP_epoch_00_score_0.5769.ckpt`，继续等待验证边界刷新到新最佳。
- 两张 H100 使用 80,860/81,559 MiB 和 78,376/81,559 MiB，利用率 25% 和 100%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件与内部日志持续更新，正式训练进程存在，当前日志没有 OOM、警告或未处理异常。

## 2026-08-09 07:46：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=14612`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3812863`、`0.1714312`、`0.1762237`、`0.1687160` 和 `0.2351671`，均为有限值；最新完成的仍是第九次验证，总损失 `0.3090253`、配体体素 PRAUC `0.5870306`。
- `TOP_epoch_00_score_0.5870.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；本次尚无第十次验证，`BEST.ckpt` 仍对应上一轮全局最佳 `TOP_epoch_00_score_0.5769.ckpt`，继续等待验证边界刷新到新最佳。
- 两张 H100 使用 79,890/81,559 MiB 和 80,166/81,559 MiB，利用率 89% 和 46%。作业为 `RUNNING`，只有 `after_lock_336298`；W&B 事件与内部日志持续更新，正式训练进程存在，当前日志没有 OOM、警告或未处理异常。

## 2026-08-09 10:45：Find_0 第十次验证继续刷新配体体素最佳值

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=14858` 并完成第十次验证。验证总损失为 `0.3103289`；配体体素、受体、实际原子和伪原子 PRAUC 分别为 `0.5946411`、`0.6686592`、`0.6787534` 和 `0.6099436`。配体体素、受体和实际原子 PRAUC 均创下本次运行新高，伪原子 PRAUC 未超过第八次验证的 `0.6250447`。
- 当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3237860`、`0.1552315`、`0.1597767`、`0.1328033` 和 `0.1977355`，均为有限值。新的 `TOP_epoch_00_score_0.5946.ckpt` 与 `last.ckpt` 已完整落盘；`BEST.ckpt` 已正确刷新到上一轮最佳 `TOP_epoch_00_score_0.5870.ckpt`，继续符合一次验证延迟。
- 两张 H100 使用 80,662/81,559 MiB 和 80,780/81,559 MiB；采样时利用率为 10% 和 5%，但 W&B 摘要、二进制事件、内部日志和 44 个正式训练进程持续活动。作业为 `RUNNING`，只有 `after_lock_336298`，当前日志没有 OOM、警告或未处理异常。

## 2026-08-09 13:47：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=15431`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3033937`、`0.1284922`、`0.1295640`、`0.1420329` 和 `0.1991215`，均为有限值；最新完成的仍是第十次验证，总损失 `0.3103289`、配体体素 PRAUC `0.5946411`。
- `TOP_epoch_00_score_0.5946.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；本次尚无第十一次验证，`BEST.ckpt` 继续对应上一轮最佳 `TOP_epoch_00_score_0.5870.ckpt`，符合一次验证延迟。
- 两张 H100 使用 80,884/81,559 MiB 和 79,762/81,559 MiB，利用率均为 44%。Slurm 状态为 `RUNNING`，只有 `after_lock_336298`；W&B 摘要与内部日志持续更新，计算节点上存在正式训练进程。日志中仅有 Lightning 对批量大小自动推断的既有提示，没有 OOM 或未处理异常。

## 2026-08-09 16:47：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=16007`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2446605`、`0.1079736`、`0.1123107`、`0.1081431` 和 `0.1731274`，均为有限值；最新完成的仍是第十次验证，总损失 `0.3103289`、配体体素 PRAUC `0.5946411`。
- `TOP_epoch_00_score_0.5946.ckpt`、`last.ckpt` 与历史 TOP 候选保持完整；本次尚无第十一次验证，`BEST.ckpt` 继续对应上一轮最佳 `TOP_epoch_00_score_0.5870.ckpt`，等待下一次验证边界刷新。计算节点的正式进程明确使用release `Pocket_Plus_dc0f05168815`；`config.yaml` 仍记录两类density cube均为9³、`num_downsample=2`、`num_conv=0`、batch6/global48、`warmup_ratio=0.005`、`patience=3`与`offline=false`。
- 两张 H100 使用 79,794/81,559 MiB 和 80,874/81,559 MiB，利用率为97%和21%。Slurm状态为 `RUNNING`，只有 `after_lock_336298`；W&B摘要和内部日志持续更新，计算节点有43个匹配正式训练命令的进程，当前错误扫描为空。

## 2026-08-09 19:47：Find_0 完成第十一次验证

- Find_0 Job 336298 attempt a4 推进到 `trainer/global_step=16172` 并完成第十一次验证。验证总损失由 `0.3103289` 降至 `0.3014218`；配体体素、受体、实际原子和伪原子 PRAUC 分别为 `0.5899938`、`0.6643889`、`0.6687806` 和 `0.6154157`。配体体素 PRAUC 未超过第十次验证的当前最佳 `0.5946411`，其余三项也未超过各自已有最佳值。
- 当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3259211`、`0.1557486`、`0.1594718`、`0.1335916` 和 `0.2063368`，均为有限值。新的 `TOP_epoch_00_score_0.5900.ckpt` 与 `last.ckpt` 已完整落盘；`BEST.ckpt` 已刷新为当前全局最佳 `TOP_epoch_00_score_0.5946.ckpt`。top-k保留数量维持10份，最弱的 `TOP_epoch_00_score_0.4720.ckpt` 已按策略移除。
- 两张 H100 使用 80,934/81,559 MiB 和 80,892/81,559 MiB，利用率为49%和59%。Slurm状态为 `RUNNING`，只有 `after_lock_336298`；W&B摘要与内部日志持续更新，计算节点有43个匹配正式训练命令的进程，当前错误扫描为空。

## 2026-08-10 00:27：服务器连接超时，本轮未取得新训练证据

- 通过项目统一SSH helper连接 `10.102.33.220:10022` 时，两次有限重试均在认证前超时；随后使用本机TCP客户端对同一地址和端口进行5秒探测，结果仍为超时。
- 本轮没有执行服务器写入、锁操作、作业控制命令或训练状态读取，因此不能把连接失败解释为Job336298停止、失败或继续运行。最后一次成功检查仍是2026-08-09 19:47：step16172、第十一次验证完成、TOP0.5900与last完整、BEST指向全局最佳TOP0.5946，作业当时健康。

## 2026-08-10 03:28：服务器连接恢复，Find_0 健康推进

- 到 `10.102.33.220:10022` 的SSH连接已经恢复。Find_0 Job 336298 attempt a4推进到 `trainer/global_step=17537`；当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3159079`、`0.1560811`、`0.1565606`、`0.1237661` 和 `0.2040469`，均为有限值。
- 最新完成的仍是第十一次验证，总损失 `0.3014218`、配体体素PRAUC `0.5899938`。`TOP_epoch_00_score_0.5900.ckpt`、`last.ckpt` 与历史TOP候选保持完整，`BEST.ckpt`继续对应当前全局最佳 `TOP_epoch_00_score_0.5946.ckpt`；本次尚无第十二次验证。
- 计算节点的正式训练进程明确使用release `Pocket_Plus_dc0f05168815`及batch6/global48、warmup0.005、patience3、在线W&B契约。两张H100使用80,142/81,559 MiB和79,884/81,559 MiB，利用率为87%和75%。Slurm状态为 `RUNNING`，只有 `after_lock_336298`；W&B内部日志持续更新，计算节点有43个匹配正式训练命令的进程，当前错误扫描为空。

## 2026-08-10 06:30：Find_0 第十二次验证刷新全部主要指标

- Find_0 Job 336298 attempt a4推进到 `trainer/global_step=17804` 并完成第十二次验证。验证总损失由 `0.3014218` 降至 `0.2952096`；配体体素、受体、实际原子和伪原子PRAUC分别提升到 `0.6012025`、`0.6831643`、`0.6839005` 和 `0.6361594`，四项PRAUC和总验证损失均创下本次运行最佳值。
- 当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2918329`、`0.1253597`、`0.1294826`、`0.1344216` 和 `0.1910335`，均为有限值。新的 `TOP_epoch_00_score_0.6012.ckpt` 与 `last.ckpt` 已完整落盘；`BEST.ckpt` 仍按一次验证延迟对应上一轮全局最佳 `TOP_epoch_00_score_0.5946.ckpt`。top-k保留数量维持10份，最弱的 `TOP_epoch_00_score_0.5116.ckpt` 已按策略移除。
- 两张H100使用79,018/81,559 MiB和78,554/81,559 MiB，利用率为30%和15%。Slurm状态为 `RUNNING`，只有 `after_lock_336298`；W&B摘要与内部日志持续更新，计算节点有43个匹配正式训练命令的进程，当前错误扫描为空。

## 2026-08-10 09:31：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4推进到 `trainer/global_step=18395`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2966442`、`0.1575673`、`0.1630947`、`0.1068642` 和 `0.1590324`，均为有限值；最新完成的仍是第十二次验证，总损失 `0.2952096`、配体体素PRAUC `0.6012025`。
- `TOP_epoch_00_score_0.6012.ckpt`、`last.ckpt` 与10份TOP候选保持完整；本次尚无第十三次验证，`BEST.ckpt` 仍按一次验证延迟对应上一轮最佳 `TOP_epoch_00_score_0.5946.ckpt`，等待下一次验证边界刷新。
- 两张H100使用80,722/81,559 MiB和80,102/81,559 MiB，利用率为65%和90%。计算节点的正式进程继续使用release `Pocket_Plus_dc0f05168815`及batch6/global48、warmup0.005、patience3、在线W&B契约。Slurm状态为 `RUNNING`，只有 `after_lock_336298`；W&B摘要和内部日志持续更新，当前错误扫描为空。

## 2026-08-10 12:33：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4推进到 `trainer/global_step=18998`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2684200`、`0.1129740`、`0.1183669`、`0.1236741` 和 `0.1993517`，均为有限值；最新完成的仍是第十二次验证，总损失 `0.2952096`、配体体素PRAUC `0.6012025`。
- `TOP_epoch_00_score_0.6012.ckpt`、`last.ckpt` 与10份TOP候选保持完整；本次尚无第十三次验证，`BEST.ckpt` 仍按一次验证延迟对应上一轮最佳 `TOP_epoch_00_score_0.5946.ckpt`，等待下一次验证边界刷新。
- 两张H100使用80,586/81,559 MiB和80,176/81,559 MiB，利用率为89%和66%。计算节点的正式进程继续使用release `Pocket_Plus_dc0f05168815`及batch6/global48、warmup0.005、patience3、在线W&B契约。Slurm状态为 `RUNNING`，只有 `after_lock_336298`；W&B内部日志持续更新，计算节点有43个匹配正式训练命令的进程，当前错误扫描为空。

## 2026-08-10 15:34：Find_0 完成第十三次验证

- Find_0 Job 336298 attempt a4推进到 `trainer/global_step=19220` 并完成第十三次验证。验证总损失为 `0.2979122`；配体体素PRAUC由 `0.6012025` 提升到新高 `0.6105047`，受体、实际原子和伪原子PRAUC分别为 `0.6759748`、`0.6753560` 和 `0.6220586`，后三项未超过第十二次验证的当前最佳值。
- 当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.2754909`、`0.1203866`、`0.1238235`、`0.1238711` 和 `0.1885087`，均为有限值。新的 `TOP_epoch_00_score_0.6105.ckpt` 与 `last.ckpt` 已完整落盘；`BEST.ckpt` 已按一次验证延迟刷新为上一轮最佳 `TOP_epoch_00_score_0.6012.ckpt`。top-k保留数量维持10份，最弱的 `TOP_epoch_00_score_0.5284.ckpt` 已按策略移除。
- 两张H100使用80,918/81,559 MiB和79,568/81,559 MiB，利用率为71%和52%。计算节点的正式进程继续使用release `Pocket_Plus_dc0f05168815`及batch6/global48、warmup0.005、patience3、在线W&B契约。Slurm状态为 `RUNNING`，只有 `after_lock_336298`；W&B摘要和内部日志持续更新，计算节点有43个匹配正式训练命令的进程，未发现当前OOM、Traceback或未处理异常。历史W&B 500/408重试和refined/unrefined设计性NaN不属于当前训练错误。

## 2026-08-10 18:34：Find_0 继续健康推进

- Find_0 Job 336298 attempt a4推进到 `trainer/global_step=19814`。当前总损失、原子损失、受体损失、配体体素损失和伪原子损失分别为 `0.3242207`、`0.1445206`、`0.1489209`、`0.1421704` 和 `0.2263755`，均为有限值；最新完成的仍是第十三次验证，总损失 `0.2979122`、配体体素PRAUC `0.6105047`。
- `TOP_epoch_00_score_0.6105.ckpt`、`last.ckpt` 与10份TOP候选保持完整；本次尚无第十四次验证，`BEST.ckpt` 仍按一次验证延迟对应上一轮最佳 `TOP_epoch_00_score_0.6012.ckpt`，等待下一次验证边界刷新。
- 两张H100使用80,006/81,559 MiB和80,790/81,559 MiB，利用率为15%和63%。计算节点的正式进程继续使用release `Pocket_Plus_dc0f05168815`及batch6/global48、warmup0.005、patience3、在线W&B契约。Slurm状态为 `RUNNING`，只有 `after_lock_336298`；W&B摘要和内部日志持续更新，计算节点有43个匹配正式训练命令的进程，当前OOM、Traceback和NCCL错误扫描为空。
