# Stage1 第二版 BOX 池与 Find_0 重训练实施

本 ExecPlan 是持续更新的执行记录。实施期间必须同步维护 `Progress`、`Surprises & Discoveries`、`Decision Log` 和 `Outcomes & Retrospective`。本文遵守仓库根目录 `AGENTS.md`；仓库没有另设 `PLANS.md`。

## Purpose / Big Picture

本任务在不覆盖旧 Stage1 BOX 池、不改变 Find_0 架构与损失的前提下，建立一份可独立选择的第二版训练准备产物，并用它从头训练 Find_0 CPC1。第二版把每个选中配体 occurrence 的训练与冻结验证请求统一改为 5 个 bias BOX 加 5 个随机 context BOX，不再使用 center BOX。bias BOX 在旧的配体尺寸相关偏移上增加长度均匀分布于 0–3 Å 的物理空间位移；context BOX 从完整图所有合法 80³ 起点均匀抽样，不设置受体原子数量下限。

完成后，人类可以从 `Pocket_Plus/训练与运行/sh/train_2/Find_0.sh` 选择第二版准备根并运行双 H100、全局批量 48、CPC1-only 的 Find_0；旧 `训练与运行/sh/Find_0.sh` 仍可选择原始 `stage1_preparation`。新模型最终通过既有完整图 calibration、语义和实例评估比较，不增加旧模型在新 BOX 验证请求上的额外评估。

## Progress

- [x] (2026-08-04 23:27+08:00) 确认 Pocket_Plus `Learn/CUMULATIVE@ff0caa6371e3455b497964971fe5335f53f2b0dd` 是本地按提交者时间形成的唯一最新提交，且工作树干净。
- [x] (2026-08-04 23:45+08:00) 用户确认 train 与 validation 均采用一次生成后冻结的 `0 center + 5 bias + 5 context`，新旧 BOX 池并存，Find_0 只训练 CPC1。
- [x] (2026-08-04 23:57+08:00) 从共同基点建立 Pocket_Plus 实现分支 `codex/stage1-box-pool-2`。
- [x] (2026-08-05 00:05+08:00) 建立第二版 Find_0 正式训练入口；用户将 H100 单卡批量明确修正为 6，全局批量保持 48。
- [x] (2026-08-05 00:09+08:00) 提交双 H100、CPU48、`pre_hold+after_hold` 的新 Find_0 Job 336298；作业尚未取得资源，状态为 `PENDING(Resources)`，没有 release 或训练进程。
- [x] (2026-08-05 00:17+08:00) 在 Pocket_Plus 实现分支完成第二版 bias、context、训练请求与冻结验证请求的最小改动；旧默认 `1:5:3` 和新 `0:5:5` 同时通过定向测试，结果为 `20 passed`。
- [x] (2026-08-05 00:21+08:00) 在 `Pocket_Plus/ops/box_pool_2/` 建立分片生成与最终发布入口；实现端点为 `13cff42`，独立只读复核确认没有阻断问题。
- [x] (2026-08-05 00:40+08:00) CPU array Job 336412 的 24 个分片全部 `COMPLETED 0:0`；正式根已有 13,710 份 train NPZ、200 份 validation NPZ，`run_state/box_pool/` 中 24 份分片状态齐全。当前正在执行 finalize 前的独立只读复核，尚未发布根 `_COMPLETE`。
- [x] (2026-08-05 01:03+08:00) CPU16 Job 336466 完成单次 finalize；临时深验收 Job 336494 在修复两项仅属于临时脚本的工程错误后逐项检查 13,910 份 NPZ 并 `PASS`。正式过滤 split、16 个辅助标签排除编号、4 个合法短图、`0:5:5` 冻结请求和所有起点范围均已核对。
- [x] (2026-08-05 01:12+08:00) 按授权顺序结束旧 unet_c1 Job 321107 与旧 Find_1 Job 321540；两者最终均为 `CANCELLED by 1351`。hnode01/hnode02 的短暂 `Kill task failed` DRAIN 已自行恢复，Job 336298 取得 hnode01 两张 H100。
- [x] (2026-08-05 01:23+08:00) 核对并删除 Job 336298 的唯一 `pre_lock`。attempt a1 因 release 缺少 `.project-root` 在 `src/train.py` 导入期失败；以 Pocket_Plus 提交 `d4ec7e1` 最小补入项目根标记后，从同一 allocation 的 `try_lock` 启动 attempt a2。
- [x] (2026-08-05 01:38+08:00) Job 336298 attempt a2 完成 DDP 2/2 初始化并进入正式训练；W&B run `8z7x9dnl` 在线更新到 `global_step=23`，五项 step 损失均为有限值，两张 H100 均已加载模型并执行计算。resolved 配置仍为第二版准备根、每卡批量 6、全局批量 48、学习率 `5e-5` 与 `warmup_ratio=0.005`。
- [x] (2026-08-05 01:48+08:00) 同池 unet_c1 Job 336538 attempt a1 在 `trainer.fit` 前因 hnode02 分配到的 H100 无法初始化 CUDA 而退出。独立最小 CUDA 程序复现相同错误，GPU 诊断显示待重映射显存行 `Pending: Yes`，不是模型、数据、批量或脚本错误；证据保存在 `/home/penghongen/My_Project/tmp/stage1_boxpool2_unet_336538_cuda_failure`。
- [x] (2026-08-05 01:55+08:00) 释放无法训练的 Job 336538，并立即以同一正式脚本、相同 batch 6/global 48、学习率 `1e-4`、warmup `0.005` 和在线 W&B 提交 A800 恢复 Job 336558；只把 allocation CPU 从 48 调为足够承载 20 个 worker 的 24。Job 已取得 gnode09 一张 A800，在核对身份、正式脚本、pool `_COMPLETE` 与 `after_lock` 后删除唯一 `pre_lock`；attempt a1 使用 release `Pocket_Plus_803f3349868d`、launch `unet_c1_job336558_20260805T015223_a1`，当前正在模型与数据初始化。
- [x] (2026-08-05 02:29+08:00) unet_c1 Job 336558 attempt a1 已越过初始化并进入正式训练；W&B run `dvc1ubk4` 在线更新到 `global_step=113`，五项监督损失与总损失均有限，A800 使用约 67.2 GiB 显存且利用率 100%。进程环境明确指向第二版准备根。
- [x] (2026-08-05 03:00+08:00) 完成连续联合健康检查第 2 次：Find_0 Job 336298 推进到 `global_step=308`，unet_c1 Job 336558 推进到 `global_step=260`；两项当前训练损失均有限，在线 W&B、正式训练进程、第二版准备根、配置和锁身份保持正确，当前错误扫描为空。尚未进入首次 checkpoint 保存。
- [x] (2026-08-05 03:29+08:00) 完成连续联合健康检查第 3 次：Find_0 Job 336298 推进到 `global_step=407`，unet_c1 Job 336558 推进到 `global_step=386`；两项当前训练损失有限，GPU 正常计算，在线 W&B、第二版准备根、正式进程和锁身份无漂移，当前错误扫描为空。监控间隔调整为每 3 小时。
- [x] (2026-08-05 06:37+08:00) 发现 Find_0 attempt a2 于 03:55 在 `global_step=491` 后遭遇真实 CUDA OOM：rank 1 仅余 471.75 MiB，申请 750 MiB 失败，同时有 3.15 GiB PyTorch 保留但未分配显存；a2 尚未产生 checkpoint。保留完整证据后，在同一 Job 336298 allocation 中保持 batch 6/global 48 和全部科学参数不变，仅增加 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`，并固定继续使用 a2 的 release `Pocket_Plus_ad9875ec1f0a`，删除准确的 `try_lock_336298` 启动 attempt a3。新 launch 为 `Find_0_job336298_20260805T063728_a3`；监控临时恢复为每 30 分钟。
- [x] (2026-08-05 06:31+08:00) 同期 unet_c1 Job 336558 持续健康推进到 `global_step=1229`，六项当前训练损失有限，A800 使用约 67.2 GiB 且利用率 100%，第二版准备根、在线 W&B 与唯一 `after_lock` 均正常。
- [x] (2026-08-05 07:10+08:00) Find_0 attempt a3 完成 DDP 初始化并以 W&B run `ax7n3y7i` 推进到 `global_step=80`，五项当前训练损失有限，两张 H100 正常计算，第二版准备根和锁身份正确；这是 a3 恢复后的健康检查第 1 次。运行日志同时明确报告当前 H100 平台不支持 `expandable_segments`，因此该环境变量没有实际提供防 OOM 保护；暂不在训练活跃时强停，继续观察是否越过 a2 的 step 491，若 OOM 复现则按既定边界改为 batch 4/global 48。
- [x] (2026-08-05 07:40+08:00) Find_0 attempt a3 健康推进到 `global_step=206`，五项训练损失有限，两张 H100 使用 76.68/77.42 GiB 且利用率为 91%/98%；实际进程继续使用冻结 release `Pocket_Plus_ad9875ec1f0a` 和第二版准备根，只有 `after_lock`，当前无新错误。unet_c1 同期推进到 `global_step=1460`，六项损失有限，A800 使用 67.20 GiB、利用率 100%。这是 a3 连续健康检查第 2 次，尚未保存 checkpoint。
- [x] (2026-08-05 08:10+08:00) Find_0 attempt a3 健康推进到 `global_step=320`，五项训练损失有限，双 H100 利用率 100%，冻结 release、第二版数据根、W&B、进程和唯一 `after_lock` 正常，错误扫描为空；这是 a3 连续健康检查第 3 次。unet_c1 摘要仍为 `global_step=1460`，但 W&B 事件文件与内部日志持续更新到 08:09，A800 利用率 99%，训练进程和第二版数据根正常，没有停滞证据。两项仍无首次 checkpoint；监控间隔恢复为每 3 小时。
- [x] (2026-08-05 11:16+08:00) Find_0 attempt a3 已推进到 `global_step=1019`，越过 attempt a2 的 OOM 终点 step 491；五项损失有限，W&B 持续刷新，双 H100 使用 79.10/78.51 GiB，当前错误扫描为空。unet_c1 摘要仍为 step 1460，但 W&B 事件文件与内部日志持续更新到 11:14，A800 利用率 99%，没有停滞证据。两项仍只有 `after_lock` 且尚无首次 checkpoint。
- [x] (2026-08-05 12:12+08:00) 按用户授权采用 Pocket_Plus 当前低显存配置从头重训 Find_0。最小实现提交 `9a06734` 允许 `DensityCubeEncoder(num_conv=0)`，并把伪原子与真实原子 density cube 统一为边长 9、`num_downsample=2`、`num_conv=0`；Find_0 平台期耐心值从 2 调为 3。定向测试在本地和服务器各 38 项通过。主 agent 在 attempt a3 的 W&B step 1214 后创建准确的 `kill_lock_336298`，确认旧生产进程和显存都已退出，再以当前项目冻结新 release `Pocket_Plus_dc0f05168815` 启动 attempt a4；launch 为 `Find_0_job336298_20260805T121230_a4`。attempt a3 的退出码 137 是显式 `kill_lock` 所致，不是新 OOM。
- [x] (2026-08-05 12:15+08:00) attempt a4 已完成 release、命令和模型配置的第一轮核对：两类 density cube 均为 9³/`num_conv=0`，命令保持每卡批量 6、全局批量 48、学习率 `5e-5`、`warmup_ratio=0.005`，并使用 `patience=3`。13:49 已完成在线 W&B 首批有限损失、实际显存和三次连续健康验收。
- [x] (2026-08-05 12:55+08:00) attempt a4 使用在线 W&B run `es683hq5` 推进到 `global_step=116`，五项训练损失有限，第二版数据根、release、命令和唯一 `after_lock` 正常，当前错误扫描为空；这是连续健康检查第 1 次。两张 H100 当前使用 80.97/80.09 GiB，利用率 97%/94%，尚未显示相对旧配置约 79–81 GiB 的显著显存下降，因此不能把首次健康训练误记为 OOM 风险已经消除。unet_c1 Job 336558 的 W&B 摘要仍为 step 1460，但内部日志持续更新到 12:52，没有停滞或错误证据。
- [x] (2026-08-05 13:19+08:00) attempt a4 推进到 `global_step=209`，五项训练损失有限，W&B 事件与内部日志持续更新，release、第二版数据根、进程、命令和唯一 `after_lock` 正常；这是连续健康检查第 2 次。两张 H100 使用 80.96/80.62 GiB，仍未显示显存显著下降，但当前没有 OOM。unet_c1 的事件文件与内部日志分别更新到 13:13 和 13:16，Slurm、唯一 `after_lock` 与错误扫描正常，没有停滞证据。
- [x] (2026-08-05 13:49+08:00) attempt a4 推进到 `global_step=311`，五项训练损失有限，W&B、release、第二版数据根、进程、命令、唯一 `after_lock` 与错误扫描正常；连续健康检查达到 3/3。两张 H100 使用 79.37/80.00 GiB，仍无显存显著下降结论，但当前没有 OOM。unet_c1 的内部 W&B 日志持续更新到 13:46，Slurm、唯一 `after_lock` 与错误扫描正常。监控间隔恢复为每 3 小时。
- [x] (2026-08-05 16:52+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=956`，五项训练损失有限，双 H100、冻结 release、第二版数据根、在线 W&B、进程和唯一 `after_lock` 正常，错误扫描为空；两张 H100 使用 80.25/80.27 GiB，仍按高占用但无真实 OOM 处理。unet_c1 推进到 `global_step=1517` 并完成首次验证：总验证损失 `0.305254`、配体体素 PRAUC `0.253671`、受体 PRAUC `0.230980`，已保存 `TOP_epoch_00_score_0.2537.ckpt` 与 `last.ckpt`；作业、W&B 和唯一 `after_lock` 正常。
- [x] (2026-08-05 19:51+08:00) 三小时只读检查确认 Find_0 attempt a4 最近摘要推进到 `global_step=1460`，五项训练损失有限；摘要暂缓刷新，但 W&B 事件和内部日志持续更新到 19:51，双 H100、冻结 release、第二版数据根、进程、唯一 `after_lock` 和错误扫描正常，两张 H100 使用 80.16/79.88 GiB，没有真实 OOM，尚无 checkpoint。unet_c1 推进到 `global_step=1775`，六项训练损失有限；首次验证结果与 TOP/last checkpoint 保持完整，作业和日志持续活动。
- [x] (2026-08-05 22:52+08:00) Find_0 attempt a4 完成首次正式验证并推进到 `global_step=1733`：总验证损失 `0.419612`，配体体素、受体、原子和伪原子 PRAUC 分别为 `0.472018`、`0.535651`、`0.533216` 和 `0.485918`，已保存约 1.4 GiB 的 `TOP_epoch_00_score_0.4720.ckpt` 与 `last.ckpt`。refined/unrefined 面板因未启用 sparse-refine loss 仍按设计为 NaN；其余训练损失、验证损失与指标均有限。双 H100 使用 80.86/80.44 GiB，作业、release、数据根、W&B、唯一 `after_lock` 与错误扫描正常。unet_c1 推进到 `global_step=2021`，六项损失有限，首次验证与 checkpoint 保持完整。
- [x] (2026-08-06 01:51+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=2360`，五项训练损失有限；首次验证指标与 TOP/last checkpoint 保持完整，双 H100 使用 80.58/79.49 GiB，release、第二版数据根、进程、W&B、唯一 `after_lock` 和错误扫描正常，没有真实 OOM。unet_c1 最近摘要为 `global_step=2039` 且六项训练损失有限；摘要暂缓刷新，但 W&B 事件和内部日志持续更新到 01:49，首次验证与 TOP/last checkpoint 完整，没有停滞或错误证据。
- [x] (2026-08-06 04:52+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=2921`，五项训练损失有限；首次验证与 TOP/last checkpoint 完整，双 H100 使用 79.89/79.78 GiB，release、第二版数据根、进程、W&B、唯一 `after_lock` 和错误扫描正常，没有真实 OOM。unet_c1 最近摘要为 `global_step=2057` 且六项损失有限；W&B 事件和内部日志持续更新，首次验证与 checkpoint 完整，没有停滞或错误证据。
- [x] (2026-08-06 07:54+08:00) Find_0 attempt a4 推进到 `global_step=3143` 并完成第二次验证：总验证损失从 `0.419612` 改善到 `0.360815`，配体体素、受体、原子和伪原子 PRAUC 提升到 `0.511648`、`0.598803`、`0.603966` 和 `0.539441`；新 `TOP_epoch_00_score_0.5116.ckpt` 与 `last.ckpt` 已落盘。`BEST.ckpt` 当前仍对应上一轮 `0.4720` TOP，按一次验证延迟继续观察。双 H100 使用 80.97/80.28 GiB，无真实 OOM，作业身份、release、第二版数据根、W&B、唯一 `after_lock` 与错误扫描正常。unet_c1 推进到 `global_step=2348`，六项损失有限，首次验证和 checkpoint 完整。
- [x] (2026-08-06 10:55+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=3731`，五项训练损失有限；第二次验证、新 TOP/last checkpoint 完整，`BEST.ckpt` 仍对应上一轮 `0.4720` TOP，继续等待下一次验证刷新。双 H100 使用 80.30/80.62 GiB，release、第二版数据根、进程、唯一 `after_lock` 和错误扫描正常，没有真实 OOM。09:40–09:43 出现数次可重试的 W&B API 500 警告，随后事件、摘要与内部日志已恢复持续更新，不构成训练阻断。unet_c1 最近摘要为 `global_step=2921` 且六项损失有限；W&B 持续活动，首次验证与 checkpoint 完整。
- [x] (2026-08-06 13:57+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=4331`，五项训练损失有限；第二次验证、新 TOP/last checkpoint 继续完整，`BEST.ckpt` 仍对应上一轮 `0.4720` TOP，尚未到下一次验证刷新点。两张 H100 使用 79.57/80.79 GiB，作业、release、正式进程、唯一 `after_lock` 与当前日志正常，没有 OOM；本次 GPU 采样恰处于数据等待，W&B 摘要、事件文件和内部日志仍持续更新。unet_c1 摘要仍为 `global_step=2921`，但二进制事件、内部日志、A800 满载计算与正式进程持续活动；首次验证和 checkpoint 完整，没有停滞或异常证据。
- [x] (2026-08-06 16:57+08:00) 两项训练均完成新的验证并继续改善。Find_0 attempt a4 推进到 `global_step=4472`，第三次验证总损失降至 `0.345794`，配体体素、受体、原子和伪原子 PRAUC 提升到 `0.552684`、`0.617985`、`0.625505` 和 `0.581426`；新 TOP/last checkpoint 完整，`BEST.ckpt` 已正确刷新到上一轮 `0.5116` TOP。unet_c1 推进到 `global_step=3539`，第二次验证总损失降至 `0.274757`，配体体素与受体 PRAUC 提升到 `0.343178` 和 `0.345571`，新 TOP/last checkpoint 完整，`BEST.ckpt` 暂时对应上一轮 `0.2537` TOP。两项作业、GPU、W&B、唯一 `after_lock` 与当前错误扫描正常，无 OOM 或未处理异常。
- [x] (2026-08-06 21:34+08:00) 用户因吞吐过慢于 17:27 主动 `scancel 336558`，并明确要求不再监控该 unet_c1。Slurm 最终状态为 `CANCELLED`；最终摘要为 `global_step=3668`，第二次验证配体体素 PRAUC `0.343178`，`TOP_epoch_00_score_0.3432.ckpt` 与 `last.ckpt` 完整，`BEST.ckpt` 仍对应上一轮 `0.2537` TOP。该作业不恢复、不接管、不再纳入 heartbeat。
- [x] (2026-08-06 21:34+08:00) Find_0 attempt a4 继续健康推进到 `global_step=5426`，五项训练损失有限；第三次验证、TOP/last 与刷新到上一轮 `0.5116` TOP 的 BEST 保持完整。双 H100 使用 80.85/80.83 GiB，W&B、正式进程、唯一 `after_lock` 正常，无 OOM 或异常。
- [x] (2026-08-07 13:37+08:00) Find_0 attempt a4 推进到 `global_step=7853`，期间完成第四、第五次验证。最新验证总损失降至 `0.327828`，配体体素、受体、原子和伪原子 PRAUC 为 `0.560720`、`0.636979`、`0.640433` 和 `0.588258`；`TOP_epoch_00_score_0.5284.ckpt`、新 `TOP_epoch_00_score_0.5607.ckpt` 与 `last.ckpt` 完整，`BEST.ckpt` 已正确刷新到上一轮最佳 `0.5527` TOP。双 H100 使用 80.89/80.84 GiB，W&B、正式进程、唯一 `after_lock` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-07 16:40+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=8468`，五项训练损失均有限；第五次验证指标、TOP/last 与对应上一轮最佳 `0.5527` TOP 的 `BEST.ckpt` 保持完整，尚无第六次验证。两张 H100 使用 80.78/80.87 GiB，W&B 事件与内部日志持续更新；作业为 `RUNNING`，只有 `after_lock_336298`，当前错误扫描无 OOM、警告或未处理异常。
- [x] (2026-08-07 19:38+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=8768`，五项训练损失均有限；第五次验证指标、TOP/last 与对应上一轮最佳 `0.5527` TOP 的 `BEST.ckpt` 保持完整，尚无第六次验证。两张 H100 均使用 80.88/81.56 GiB，W&B 事件与内部日志持续更新；作业为 `RUNNING`，只有 `after_lock_336298`，当前错误扫描无 OOM、警告或未处理异常。
- [x] (2026-08-07 22:40+08:00) Find_0 attempt a4 推进到 `global_step=9299` 并完成第六次验证。验证总损失为 `0.327025`，配体体素、受体、原子和伪原子 PRAUC 为 `0.562431`、`0.628463`、`0.643336` 和 `0.600575`；新 `TOP_epoch_00_score_0.5624.ckpt` 与 `last.ckpt` 完整，`BEST.ckpt` 已正确刷新到上一轮最佳 `0.5607` TOP。两张 H100 使用 80.36/80.27 GiB，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-08 01:40+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=9920`，五项训练损失有限；第六次验证、TOP/last 与对应上一轮最佳 `0.5607` TOP 的 `BEST.ckpt` 保持完整，尚无第七次验证。两张 H100 使用 80.72/79.50 GiB，作业为 `RUNNING` 且只有 `after_lock_336298`。W&B 上传线程在检查时遇到一次可重试的 HTTP 408，但事件、摘要、内部日志和训练步持续更新且 `dropped=0`，没有 OOM、未处理异常或训练阻断。
- [x] (2026-08-08 04:40+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=10229`，五项训练损失有限；第六次验证、TOP/last 与对应上一轮最佳 `0.5607` TOP 的 `BEST.ckpt` 保持完整，尚无第七次验证。两张 H100 使用 80.68/80.25 GiB，作业为 `RUNNING` 且只有 `after_lock_336298`；W&B 事件和内部日志持续更新，上一轮 HTTP 408 没有继续出现，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-08 07:41+08:00) Find_0 attempt a4 推进到 `global_step=10715` 并完成第七次验证。验证总损失降至 `0.309085`，配体体素、受体、原子和伪原子 PRAUC 提升到 `0.576889`、`0.661014`、`0.669940` 和 `0.605355`；新 `TOP_epoch_00_score_0.5769.ckpt` 与 `last.ckpt` 完整，`BEST.ckpt` 已正确刷新到上一轮最佳 `0.5624` TOP。两张 H100 使用 80.82/80.43 GiB 且利用率 100%/98%，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-08 10:41+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=11315`，五项训练损失有限；第七次验证、新 TOP/last 与对应上一轮最佳 `0.5624` TOP 的 `BEST.ckpt` 保持完整，尚无第八次验证。两张 H100 使用 80.43/80.27 GiB，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-08 13:41+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=11690`，五项训练损失有限；第七次验证、新 TOP/last 与对应上一轮最佳 `0.5624` TOP 的 `BEST.ckpt` 保持完整，尚无第八次验证。两张 H100 使用 79.98/80.36 GiB，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-08 16:41+08:00) Find_0 attempt a4 推进到 `global_step=12089` 并完成第八次验证。验证总损失降至 `0.304401`；配体体素、受体、原子和伪原子 PRAUC 为 `0.566803`、`0.659098`、`0.667087` 和 `0.625045`，其中配体体素 PRAUC 未超过第七次验证的 `0.576889`。新 `TOP_epoch_00_score_0.5668.ckpt` 与 `last.ckpt` 完整，`BEST.ckpt` 已正确刷新到当前全局最佳 `0.5769` TOP。两张 H100 使用 80.88/80.75 GiB，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-08 19:42+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=12734`，五项训练损失有限；第八次验证、新 TOP/last 与当前全局最佳 `0.5769` TOP 的 `BEST.ckpt` 保持完整，尚无第九次验证。两张 H100 使用 80.74/80.65 GiB，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-08 23:21+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=13151`，五项训练损失有限；第八次验证、新 TOP/last 与当前全局最佳 `0.5769` TOP 的 `BEST.ckpt` 保持完整，尚无第九次验证。两张 H100 使用 80.77/80.61 GiB，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-09 01:45+08:00) Find_0 attempt a4 推进到 `global_step=13553` 并完成第九次验证。验证总损失为 `0.309025`，配体体素、受体、原子和伪原子 PRAUC 为 `0.587031`、`0.654145`、`0.658401` 和 `0.604590`；配体体素 PRAUC 创下新高。新 `TOP_epoch_00_score_0.5870.ckpt` 与 `last.ckpt` 完整，`BEST.ckpt` 当前仍正确对应上一轮全局最佳 `0.5769` TOP，等待下一次验证刷新。两张 H100 使用 80.82/80.91 GiB，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-09 04:46+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=14129`，五项训练损失有限；第九次验证、新 TOP/last 保持完整，尚无第十次验证。`BEST.ckpt` 仍对应上一轮全局最佳 `0.5769` TOP，继续等待验证边界刷新到新最佳 `0.5870`。两张 H100 使用 80.86/78.38 GiB，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-09 07:46+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=14612`，五项训练损失有限；第九次验证、新 TOP/last 保持完整，尚无第十次验证。`BEST.ckpt` 仍对应上一轮全局最佳 `0.5769` TOP，继续等待验证边界刷新到新最佳 `0.5870`。两张 H100 使用 79.89/80.17 GiB，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-09 10:45+08:00) Find_0 attempt a4 推进到 `global_step=14858` 并完成第十次验证。验证总损失为 `0.310329`，配体体素、受体、原子和伪原子 PRAUC 为 `0.594641`、`0.668659`、`0.678753` 和 `0.609944`；前三项 PRAUC 创下本次运行新高。新 `TOP_epoch_00_score_0.5946.ckpt` 与 `last.ckpt` 完整，`BEST.ckpt` 已按一次验证延迟刷新到上一轮最佳 `0.5870` TOP。两张 H100 使用 80.66/80.78 GiB，W&B、正式进程与唯一 `after_lock_336298` 正常，当前日志无 OOM、警告或未处理异常。
- [x] (2026-08-09 13:47+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=15431`，五项训练损失有限；第十次验证、新 TOP/last 与对应上一轮最佳 `0.5870` TOP 的 `BEST.ckpt` 保持完整，尚无第十一次验证。两张 H100 使用 80.88/79.76 GiB，W&B 摘要与内部日志持续更新，正式训练进程仍在双卡计算；作业为 `RUNNING`，只有 `after_lock_336298`，当前日志无 OOM 或未处理异常。
- [x] (2026-08-09 16:47+08:00) 三小时只读检查确认 Find_0 attempt a4 推进到 `global_step=16007`，五项训练损失有限；第十次验证、TOP0.5946、last 与对应上一轮最佳0.5870 TOP 的 `BEST.ckpt` 保持完整，尚无第十一次验证。正式进程继续使用release `Pocket_Plus_dc0f05168815`，resolved配置仍为两类9³/`num_conv=0`、batch6/global48、warmup0.005、patience3与在线W&B。两张H100使用79.79/80.87 GiB，作业为 `RUNNING` 且只有 `after_lock_336298`，当前错误扫描为空。
- [x] (2026-08-09 19:47+08:00) Find_0 attempt a4推进到 `global_step=16172` 并完成第十一次验证。验证总损失降至 `0.301422`；配体体素、受体、原子和伪原子PRAUC为 `0.589994`、`0.664389`、`0.668781` 和 `0.615416`，配体体素PRAUC未超过当前最佳 `0.594641`。新TOP0.5900与last完整，`BEST.ckpt`已刷新到当前全局最佳TOP0.5946；top-k保留策略移除最弱的TOP0.4720。两张H100使用80.93/80.89 GiB，作业为 `RUNNING` 且只有 `after_lock_336298`，当前错误扫描为空。
- [x] (2026-08-10 00:27+08:00) 本轮只读检查未能建立到 `10.102.33.220:10022` 的SSH连接：统一helper的两次有限重试均在认证前超时，随后独立TCP端口探测也超时。未执行任何服务器写入、锁操作或作业控制命令，不能据此判断Job336298的当前训练状态；最后一次成功证据仍为2026-08-09 19:47的step16172与健康第十一次验证。
- [ ] 只持续验收 Find_0 的后续验证指标和 checkpoint；本轮只运行 CPC1，不启动 CPC2。
- [ ] 回填 mapping、运行检查记录和 CLAUDE handoff/memory；后续完整图推理与评估沿用既有主线。

## Surprises & Discoveries

- Observation: 2026-08-06 已完成 unet_c1 A800 `dvc1ubk4` 与历史 H100 `3a323sl8` 的定量吞吐诊断。W&B 时间线、系统指标与三组独立 CPU 阶段切换复放共同证明：H100 首个验证点前较慢是输入饥饿；validation 中两卡均接近满载，A800 按请求归一后耗时为 H100 的 1.74 倍；A800 validation 后的低平均速度由 12 个离散长间隔造成，典型 step 吞吐并未下降。完整 validation 前后训练窗口没有可重复退化，直接排除了 DataLoader 被 validation 固定销毁或污染。
  Evidence: `/storage/penghongen/tmp/unet_c1_throughput_audit_20260806` 与 `talk/unet_c1_A800与H100吞吐定量诊断.md`。本诊断未修改、暂停或重启任何 GPU 训练。

- Observation: 原训练请求与冻结验证请求分别在 `src/datasets/stage1_requests.py` 和 `src/datasets/ops/stage1_box_pool.py` 中写死为 `1:5:3`，仅更换准备根路径不能实现第二版比例。
  Evidence: `Stage1TrainingRequestSet._build_epoch_requests()` 总是追加 1 个 center、5 个 bias 和 3 个 context；`freeze_validation_selection()` 使用相同比例。

- Observation: 2026-08-04 23:59 的 H100 节点检查显示 hnode01 与 hnode02 各有 3 张 H100，旧 Find_1 使用 hnode01 的 2 张，旧 unet_c1 使用 hnode02 的 1 张；Job 336298 提交后仍因 `Resources` 排队，说明不能只根据两个旧作业推断节点全部可用资源。
  Evidence: `squeue -j 321107,321540,336298` 与 `sinfo -N -p h100` 的实时输出。

- Observation: 当前账户虽然可以查看更大的 CPU QOS，但关联表只授权 `cpu96`；该 QOS 的单用户上限是 192 CPU，且另有一个保留作业占用 16 CPU。
  Evidence: `sacctmgr show assoc where user=penghongen` 只列出 `cpu96`，`sacctmgr show qos` 报告 `cpu96 MaxTRESPerUser=cpu=192`；Job 336412 的第 18–23 分片因 `QOSMaxCpuPerUserLimit` 排队。

- Observation: Job 336412 不需要人工补分片；前一批分片结束后，调度器依次启动受 `cpu96` 上限等待的分片，最终 24 个分片均以 `0:0` 完成。
  Evidence: `sacct -X -j 336412` 的实际数字 Job 336413–336430、336448、336450–336453 均为 `COMPLETED 0:0`；正式状态目录具有 `shard_000_of_024.json` 至 `shard_023_of_024.json`。

- Observation: 本对话的长期监控不得复用另一对话的自动化身份。
  Evidence: 已恢复旧自动化 `adaligand-stage1` 对 `codex://threads/019fc1b6-6900-7412-9580-51b0a2fc3b20` 的原有 Find_0 推理监控，并为本对话单独建立 `adaligand-stage1-boxpool2`；两者任务边界与触发目标分离。

- Observation: `stage1_preparation` 下确实同时保留历史源 split 与今后的正式过滤 split；第二版 BOX 池读取的是已经删除辅助标签缺失 PDB 的正式版本。
  Evidence: 正式 `/stage1_preparation/split/train.json` 有 13,714 个唯一 PDB，16 个冻结排除编号命中 0；历史 `/stage1_preparation/adaligand_stage1_20260721T024000/split/train.json` 有 13,719 个唯一 PDB，仍命中 `5y6p`、`7n6g`、`7z8g`、`9hhl`、`9v7i`。第二版 manifest 的 13,710 个 train PDB 不含 16 个排除编号，数量等于正式 13,714 扣除 4 个合法短图。

- Observation: 深验收前三次尝试中的前两次失败都属于临时验收脚本，不影响正式 finalize 或数据。
  Evidence: 第一次在 `set -u` 下激活 Conda，未进入 Python；第二次把 split 的候选配体字典行误当作 PDB 字符串。临时脚本分别增加 Conda 激活的 `set +u/set -u`，并按 `pdb_id` 首次出现去重；第三次产出 `PASS`。正式入口、BOX 文件和根契约没有修改。
- Observation: 训练型 release 依赖仓库根 `.project-root`，而第二版首次训练前的 Pocket_Plus 工作树没有该标记；纯数据构建任务不会触发这一缺口。
  Evidence: attempt a1 的 `src/train.py:19` 在 `rootutils.setup_root(..., indicator=".project-root")` 抛出 `FileNotFoundError`，未创建正式训练目录。使用同一 H100 allocation 的不训练诊断证明两张 H100、PyTorch CUDA 与 Conda 正常；补入标记后 attempt a2 已越过根解析并进入模型实例化。

- Observation: hnode02 在旧训练结束后看似恢复为 `mixed`，但 Job 336538 获得的 H100 仍不能建立 CUDA 上下文。
  Evidence: 正式 unet_c1 与 allocation 内独立 `torch.ones(..., device='cuda')` 均报 `CUDA unknown error`；`nvidia-smi -q -d ROW_REMAPPER` 显示 `Pending: Yes`，内核历史记录要求 reset GPU 才能激活新行重映射。该错误发生在 `trainer.fit` 前，没有训练步或 checkpoint。

## Decision Log

- Decision: 第二版 train 与 validation 都使用 `0:5:5`；validation 从固定 200 个 PDB 生成一次并冻结，以后重复复用。
  Rationale: 该比例与新训练分布一致，也比旧 `1:5:3` 更接近完整图中正 BOX 少于负 BOX 的真实分布。
  Date/Author: 2026-08-04 / 用户

- Decision: 新旧 BOX 池使用不同准备根；旧脚本和旧产物保持可选，不执行覆盖迁移。
  Rationale: 新训练实验必须可追溯且不能破坏旧模型、旧请求或复现实验的能力。
  Date/Author: 2026-08-04 / 用户与 Codex

- Decision: 第二版 bias 保留现有配体尺寸相关球内偏移，再叠加独立方向、长度在 0–3 Å 上均匀的物理空间偏移；context 不再检查受体重原子数量。
  Rationale: 用最小改动降低小配体过度居中的训练捷径，并让背景请求覆盖完整图合法区域。
  Date/Author: 2026-08-04 / 用户与 Codex

- Decision: 新 Find_0 使用双 H100、每卡批量 6、全局批量 48、在线 W&B，并只运行 CPC1。
  Rationale: 用户明确指定单卡批量 6；此前已决定本轮不运行 CPC2，其他模型、损失、学习率与调度参数保持现有 Find_0 CPC1 契约。
  Date/Author: 2026-08-05 / 用户

- Decision: 正式脚本、配置和产物契约不新增 SHA 或其他哈希身份；临时验收命令可以在任务外部使用哈希。
  Rationale: 用户要求正式管线保持可读，不让一次审计机制渗入长期科学入口。
  Date/Author: 2026-08-04 / 用户

- Decision: 数据统计与致命错误审计和任务排队并行，不设置“全部 smoke 完成后才提交 GPU”的前置门。
  Rationale: 原 Stage1 管线已经成熟，当前目标是尽快让新实验排队；只有发现系统性几何、标签或数据失效才阻止释放 `pre_lock`。
  Date/Author: 2026-08-04 / 用户与 Codex

- Decision: 不在 Job 336538 的故障 H100 上用 try_lock 重复执行；保存硬件证据并释放 allocation，随后以 A800 Job 336558 继续同一 unet_c1 实验。
  Rationale: GPU 需要节点级 reset，用户进程无法修复；A800 与 H100 都有 80 GiB 显存，保持每卡批量 6 与全部训练科学参数不变，比等待不可用 GPU 更符合快速启动目标。CPU 从 48 调为 24 只改变 allocation 资源，正式脚本仍使用 20 个 worker。
  Date/Author: 2026-08-05 / Codex，依据用户的自主修复授权

- Decision: Find_0 从头采用两类 density cube 均为 9³、`num_downsample=2`、`num_conv=0` 的低显存结构；每卡批量 6 与全局批量 48 保持不变，同时把调度器 `patience` 从 2 调为 3。
  Rationale: attempt a2 已出现真实 OOM，attempt a3 虽越过旧失败步数但仍长期占用约 79–81 GiB，且当前 H100 不支持 `expandable_segments`。用户提出的结构改动直接减少三维卷积激活量，比降低批量更符合“更稳、更快且保持全局批量”的目标；`num_conv=0` 只需放宽构造参数校验，不改变剩余两层 stride-2 卷积、GAP 和输出接口。
  Date/Author: 2026-08-05 / 用户与 Codex

## Outcomes & Retrospective

第二版 BOX 池已经最终发布并通过完整深验收；正式过滤 split 与16个辅助标签排除编号的版本关系也已复核。旧 unet_c1 与旧 Find_1 均已停止。新 unet_c1 的首个 H100 allocation 因 GPU 待重映射显存行而无法初始化 CUDA，证据保留后已释放；相同科学参数的 A800 Job 336558 已完成首次验证并保存可恢复 checkpoint。Find_0 attempt a2 在尚无 checkpoint 时遇到真实 CUDA OOM；attempt a3 越过旧失败步数后按用户授权由 `kill_lock` 主动结束。当前 attempt a4 从 release `Pocket_Plus_dc0f05168815` 采用 9³/`num_conv=0` 结构训练，已完成首次验证并保存 checkpoint；虽然显存仍接近 H100 上限，但没有新的真实 OOM。

对 A800 与历史 H100 unet_c1 的吞吐差异已经完成独立定量收口。训练阶段主要受共享 Lustre 上随机大 NPZ 完整读取限制：旧 H100 验证前 GPU 中位利用率只有 42.47%，当前 A800 为 98%。validation 请求具有很高的 PDB 局部性，两卡均保持约 90% 以上 GPU 利用率，因此反映出 H100 的前向计算优势；A800 每个 validation 请求耗时为 H100 的 1.74 倍。A800 validation 后的典型训练速度仍约 272.8 step/h，与验证前 273.8 step/h 相同；平均值下降来自 12 个合计 6.996 小时的离散 I/O/运行时长尾。三组受控 CPU 复放中，validation 后训练窗口分别比前置窗口快 2.9%、8.2% 和 7.0%，因此不能把现象归因于 validation 固定破坏 DataLoader。优先优化方向是把完整大 NPZ 改成可局部读取的 `.npy` memory map 或空间分块格式，其次才是分阶段缓存、worker 数和节点侧暂存。三个临时 CPU allocation 已释放，GPU 训练、正式脚本和科学参数均未因诊断而改变。

## Context and Orientation

完整 A–G 数据位于服务器 `/storage/penghongen/AdaLigand/Ori_Data`。旧训练准备根为 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation`；其 `box_pool/` 保存旧 `1:5:3` 请求所需的单 PDB NPZ、`manifest.json`、`validation_selection.npz`、`config.json`、`summary.json` 和 `_COMPLETE`。第二版准备根固定为 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2`，正式 BOX 池位于其 `box_pool/` 子目录。

`Pocket_Plus/src/datasets/ops/stage1_box_pool.py` 负责从 A–G 的 `exp.npz`、`ligand_area.npz` 和 `receptor_tokens.npz` 生成单 PDB BOX 起点。`Pocket_Plus/src/datasets/stage1_requests.py` 在训练时逐 epoch 从单 PDB pool 选择请求，在验证时读取冻结的 `validation_selection.npz`。第二版仍保留 `center_start_zyx` 字段以保持单 PDB NPZ 结构兼容，但正式训练和验证请求不引用该字段。

`pre_hold` 表示 Slurm 作业获得资源后先创建 `pre_lock_<job_id>`，删除该文件前不创建 release、不执行训练。`after_hold` 表示每次训练命令结束后创建 `try_lock_<job_id>` 并保留 allocation。Job 336298 同时启用两者，因此可以先排队，待 BOX 池最终验收后再开始训练。

## Plan of Work

首先在 `stage1_box_pool.py` 给 bias 生成函数增加真实体素尺寸和额外 Å 位移参数，并允许 context 的最少受体原子数为 0。随后让 BOX 池 `config.json` 明确记录训练请求比例，`Stage1TrainingRequestSet` 从同根配置读取比例；旧配置缺失时保留旧 `1:5:3` 行为。冻结验证入口接受同一组请求数量，第二版固定为 `0:5:5`。

然后在 `Pocket_Plus/ops/box_pool_2/` 建立正式 CPU array 入口。每个数组元素只写自己负责的 PDB NPZ 与分片完成记录，单 PDB 文件使用原子替换；所有分片齐全后由一次合并步骤写出根 manifest、冻结验证请求、配置、摘要和最终 `_COMPLETE`。中间文件只位于第二版准备根内部的运行状态目录，不覆盖旧 BOX 池。

第二版 BOX 池验收包括：train/validation PDB 集合与已过滤 split 一致；单 PDB NPZ 字段、形状、类型和起点范围正确；配置精确记录 `0:5:5`、额外 3 Å bias 与无受体门槛 context；冻结验证没有 center 请求，bias 与 context 均为每个选中 occurrence 5 项；训练请求真实展开为相同比例。验收通过后再依据实时 H100 调度证据处理旧作业与 Job 336298 的 `pre_lock`。

## Concrete Steps

本地实现与测试在 `C:\Users\15919\Desktop\Pocket_Plus` 的 `codex/stage1-box-pool-2` 分支进行。正式服务器提交统一使用：

    bash /home/penghongen/My_Project/Pocket_Plus/训练与运行/submit_task.sh \
      --sh <项目根内正式脚本> \
      --resource <cpu或h100> \
      <资源参数>

双 H100 训练 Job 336298 已使用 `--gpus 2 --cpus 48 --pre_hold --after_hold` 提交。CPU array Job 336412 使用 24 个分片、每项 8 CPU；调度器按 `cpu96` 的单用户 192 CPU 上限自动限制同时运行数量。

## Validation and Acceptance

代码层至少运行 Stage1 BOX pool、Stage1 请求源和 Dataset 相关定向测试，并要求旧 `1:5:3` 兼容测试与新 `0:5:5` 测试同时通过。脚本必须通过 `bash -n`。

正式 BOX 池只有在根 `_COMPLETE` 最后写入后才可消费。验收必须证明旧根未变化，新根的 train/validation 集合完整，全部起点位于合法范围，冻结验证请求无 center 且 bias/context 数量符合 `5:5`。正式训练启动后，`config.yaml` 必须指向第二版准备根，最终参数必须是 Find_0 CPC1、双 H100、每卡批量 6、全局批量 48、学习率 `5e-5`、warmup ratio `0.005` 和 `offline=false`。

## Idempotence and Recovery

新旧准备根分离，因此第二版失败不会破坏旧 BOX 池。单 PDB NPZ 原子发布，失败分片可以按相同数组编号重跑；根 `_COMPLETE` 缺失时训练不得开始。Job 336298 在 `pre_lock` 期间不会冻结 release，修复并安全同步后仍可从最新实现第一次执行。未经再次核对 Job 身份，不操作任何 `pre_lock`、`try_lock`、`after_lock` 或 `kill_lock`。

## Artifacts and Notes

正式入口与产物位置：

    Pocket_Plus/训练与运行/sh/train_2/Find_0.sh
    Pocket_Plus/ops/box_pool_2/
    /storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2/box_pool
    /home/penghongen/Feedback/Pocket_Plus/logs/AdaLigand_Stage1-Find_0_box_pool_2-CPC1/

## Interfaces and Dependencies

第二版继续使用 NumPy、现有 A–G NPZ、`Stage1TrainingRequestSet`、`Stage1ValidationRequestSet` 和现有 Hydra experiment `CPC1/Find_0`。不新增模型依赖、产物哈希字段或另一套训练入口。正式 CPU 入口只负责并行编排，BOX 几何与请求科学定义仍由 `src/datasets/ops/stage1_box_pool.py` 和 `src/datasets/stage1_requests.py` 负责。

## Plan Revision Note

2026-08-05：首次建立本文。计划吸收用户对 train/validation `0:5:5`、新旧准备根并存、CPC1-only、H100 batch 6、先排队后验收和正式管线不新增哈希的最终决定。
