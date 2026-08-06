# Stage1 第二版 BOX 池与 Find_0 重训练启动交接

## 当前目标

建立与旧池并存的 Stage1 第二版 BOX 池，并从头训练 Find_0 CPC1。第二版 train 与 validation 都是冻结的 `0 center + 5 bias + 5 context`；bias 在旧偏移上增加独立方向、长度均匀 0–3 Å 的物理漂移，context 不设受体原子数量门槛。新 Find_0 不运行 CPC2。

## Pocket_Plus 实现

- 基点：`Learn/CUMULATIVE@ff0caa6371e3455b497964971fe5335f53f2b0dd`。
- 实现分支：`codex/stage1-box-pool-2`。
- 当前实现端点：`9a06734`。第二版 BOX 池与 Find_0 入口截至 `13cff42`，启动期项目根标记最小修复为 `d4ec7e1`，同池 unet_c1 正式入口为 `4b0873a`；低显存 Find_0 的 9³/`num_conv=0` 与最小构造修复为 `9a06734`。
- 正式训练入口：`训练与运行/sh/train_2/Find_0.sh`、`训练与运行/sh/train_2/unet_c1.sh`。
- 正式 BOX 池入口：`ops/box_pool_2/build_box_pool_2.sh`、`ops/box_pool_2/finalize_box_pool_2.sh`。
- 科学定义仍位于 `src/datasets/ops/stage1_box_pool.py` 与 `src/datasets/stage1_requests.py`；旧默认 `1:5:3` 保持，新池从自身 `config.json` 读取 `0:5:5`。
- 定向测试 20 项通过；正式 shell 通过语法检查；独立只读复核通过。
- Pocket_Plus 工作树另有用户修改 `talk/global.md`，没有纳入本任务提交或服务器精确同步，不得丢弃或混入。

## 服务器作业

- 双 H100 Job 336298：2 GPU、48 CPU、`pre_hold+after_hold`，正式参数为每卡批量 6、全局批量 48、学习率 `5e-5`、`warmup_ratio=0.005`、在线 W&B、CPC1-only。Job 已取得 hnode01 两张 H100；attempt a1 因 release 缺少 `.project-root` 在导入 `src/train.py` 时退出，证据保留于 release `Pocket_Plus_e4e8704be491` 和 launch `Find_0_job336298_20260805T011602_a1`。
- `.project-root` 已作为最小项目结构修复提交为 `d4ec7e1` 并精确同步。attempt a2 使用 release `Pocket_Plus_ad9875ec1f0a`、launch `Find_0_job336298_20260805T012342_a2`，已创建正式运行目录与源码快照并进入模型实例化。动态命令只增加 `2>&1` 以保留启动错误文本，不改变正式脚本或训练科学契约。
- Find_0 attempt a2 已完成 DDP 2/2 初始化并在线写入 W&B run `8z7x9dnl`。2026-08-05 01:38 的摘要为 `trainer/global_step=23`，五项训练损失均有限；两张 H100 已加载模型并执行计算，没有 OOM。
- 同池 unet_c1 Job 336538：attempt a1 使用 release `Pocket_Plus_803f3349868d`、launch `unet_c1_job336538_20260805T013552_a1`，resolved 配置正确，但在 `trainer.fit` 前因 hnode02 分配的 H100 报 `CUDA unknown error` 退出。独立 CUDA 最小程序复现，GPU 行重映射为 `Pending: Yes`；证据在 `/home/penghongen/My_Project/tmp/stage1_boxpool2_unet_336538_cuda_failure`。该 Job 已取消释放，不得恢复。
- A800 恢复 Job 336558：复用同一正式脚本、第二版 pool、batch 6/global 48、学习率 `1e-4`、warmup `0.005` 和在线 W&B；申请 1 张 A800、24 CPU、`cpu96` QOS、`pre_hold+after_hold`。attempt a1 使用 release `Pocket_Plus_803f3349868d`、launch `unet_c1_job336558_20260805T015223_a1`、W&B run `dvc1ubk4`；02:29 已推进到 `global_step=113`，五项监督损失与总损失有限，A800 约 67.2 GiB、利用率 100%。H100 改为同显存容量 A800 是为绕过必须由管理员 reset 的硬件，不改变模型、数据或优化器科学契约；CPU 24 仍覆盖脚本的 20 个 worker。
- CPU 父数组 Job 336412：24 个分片，每项 8 CPU，QOS=`cpu96`，不保留 allocation。实际数字 Job 336413–336430、336448、336450–336453 已全部 `COMPLETED 0:0`。
- CPU release：`/home/penghongen/Feedback/Pocket_Plus/releases/Pocket_Plus_788b418871d5/Pocket_Plus`。
- 第二版产物根：`/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2`；正式 pool 为其 `box_pool/`，分片状态为 `run_state/box_pool/`。
- 第二版 pool 已由 Job 336466 完成 finalize，并由临时 CPU16 Job 336494 深读 13,910 份 NPZ 后最终 `PASS`。正式过滤 split 是 `/stage1_preparation/split`：train 13,714、validation 200；第二版发布为 train 13,710、validation 200，差额仅为 `5ocu`、`6tql`、`6wcb`、`7sar` 四个合法短图。历史未过滤 split 的 train 13,719 仍含 5 个辅助标签排除编号，本轮没有误用该版本。
- 本对话使用独立自动化 `adaligand-stage1-boxpool2`；不得改写另一对话 `codex://threads/019fc1b6-6900-7412-9580-51b0a2fc3b20` 的 `adaligand-stage1`。

## 必须遵守的恢复与验收边界

- 旧 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation` 不得写入或覆盖。
- 分片只发布单 PDB NPZ 与自己的状态 JSON；只有 24 份状态的身份集合精确覆盖 train/validation 后，才运行 finalize 并最后写根 `_COMPLETE`。
- 工程性错误可保留证据后自主最小修复并恢复。用户也授权在必要时自主修复会轻微改变科学契约的问题，但必须精确记录变更前后、原因、影响范围和恢复证据；不得静默漂移。
- Job 321107 与 Job 321540 已按授权顺序取消并保留最终 checkpoint/W&B 证据；不得重启或重新接管。Job 336298 的 `pre_lock` 已在身份、代码和数据核对后删除。
- Find_0 attempt a2 于 03:55 在 `global_step=491` 后因真实 CUDA OOM 结束，尚无 checkpoint；错误显示 rank 1 仅余 471.75 MiB，而 PyTorch 有 3.15 GiB 保留但未分配显存。证据在 `/home/penghongen/My_Project/tmp/stage1_boxpool2_find0_336298_oom_20260805T0355`。06:37 已在同一 allocation 启动 attempt a3：动态命令固定执行 a2 release `Pocket_Plus_ad9875ec1f0a`，只增加 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`，batch 6/global 48 和全部科学参数不变；launch 为 `Find_0_job336298_20260805T063728_a3`。先按每 30 分钟监控初始化、首批有限损失和 OOM 是否复现；若仍 OOM，再依据证据考虑 batch 4/global 48。
- 06:31 的 unet_c1 Job 336558 已健康推进到 `global_step=1229`，六项当前训练损失有限，第二版数据根、A800、在线 W&B、进程和唯一 `after_lock` 均正常。
- 07:10，Find_0 attempt a3 已使用在线 W&B run `ax7n3y7i` 健康推进到 `global_step=80`，五项损失有限，双 H100、第二版数据根、进程和唯一 `after_lock` 正常；这是 a3 连续健康检查第 1 次。完整 DDP 日志同时明确报告 `expandable_segments not supported on this platform`，因此该环境变量在当前 H100 上没有预期的防碎片化效果。健康训练期间不得主动中断；若真实 OOM 再次发生，则将每卡批量改为 4、梯度累积改为 6，保持全局批量 48 后从同一 allocation 恢复，并记录变更前后、原因和影响。同期 unet_c1 已推进到 `global_step=1403`，六项损失有限。
- 07:40，Find_0 attempt a3 已健康推进到 `global_step=206`，五项损失有限，双 H100、冻结 release、第二版数据根、W&B 和唯一 `after_lock` 正常；unet_c1 已推进到 `global_step=1460`，六项损失与 A800 正常。两项尚无首次 checkpoint，这是 a3 连续健康检查第 2 次；下一次仍健康时恢复每 3 小时监控。
- 08:10，Find_0 attempt a3 已健康推进到 `global_step=320`，五项损失有限，双 H100、冻结 release、第二版数据根、W&B、进程和唯一 `after_lock` 正常；连续健康检查已达 3/3。unet_c1 摘要仍为 `global_step=1460`，但 W&B 事件文件和内部日志持续更新到 08:09，A800 利用率 99%，没有停滞证据。两项尚无首次 checkpoint；heartbeat 已恢复为每 3 小时。
- 11:16，Find_0 attempt a3 已推进到 `global_step=1019`，越过 attempt a2 的 OOM 终点 step 491；五项损失有限，双 H100、W&B、进程、第二版数据根和唯一 `after_lock` 正常，错误扫描为空。unet_c1 摘要仍为 step 1460，但 W&B 事件文件和内部日志持续更新到 11:14，A800 利用率 99%，没有停滞证据。两项仍无首次 checkpoint，继续每 3 小时监控。
- 用户随后授权直接采用 Pocket_Plus 工作树的低显存结构从头重训 Find_0：伪原子与真实原子 density cube 均由 11³/`num_conv=1` 改为 9³/`num_conv=0`，`num_downsample=2` 不变；Find_0 调度器 `patience` 从 2 改为 3。batch 6/global 48、学习率、warmup、第二版数据根、损失与 CPC1-only 不变。`DensityCubeEncoder` 的最小修复允许 `num_conv=0`，但继续拒绝完全没有卷积层的配置；本地与服务器定向测试各 38 项通过。
- 12:09 在 attempt a3 的 W&B step 1214 后创建准确 `kill_lock_336298`，确认旧进程和显存已退出，再删除 allocation runner 建立的准确 `try_lock_336298`。12:12 启动 attempt a4，release 为 `Pocket_Plus_dc0f05168815`，launch 为 `Find_0_job336298_20260805T121230_a4`。release 已核对为两类 9³/`num_conv=0`、`patience=3`，命令没有旧 11³ 覆盖或无效 allocator 变量；attempt a3 的退出码 137 是显式 kill_lock，不是 OOM。a4 当前处于初始化，等待 resolved 配置、在线 W&B 首批有限损失和实际显存；heartbeat 暂时每 30 分钟。
- 12:55，Find_0 attempt a4 已使用在线 W&B run `es683hq5` 推进到 step 116，五项训练损失有限；release、第二版数据根、进程、命令和唯一 `after_lock` 正常，当前错误扫描为空，这是 a4 连续健康检查第 1 次。两张 H100 当前使用 80.97/80.09 GiB，仍处于旧配置约79–81GiB的范围，不能认定低显存结构已经显著降低峰值或消除 OOM 风险；无真实错误时继续观察，不主动重启。unet_c1 的摘要仍为 step1460，但内部 W&B 日志持续更新到12:52，没有停滞证据。
- 13:19，Find_0 attempt a4 已推进到 step209，五项损失有限；两张H100使用80.96/80.62GiB，release、第二版数据根、进程、命令、W&B、唯一after_lock和错误扫描正常，这是连续健康检查第2次。显存仍无显著下降证据，但没有真实OOM，不主动中断。unet_c1 的事件文件与内部日志持续更新到13:13/13:16，Slurm和错误扫描正常，没有停滞证据。
- 13:49，Find_0 attempt a4 已推进到 step311，五项损失有限；两张H100使用79.37/80.00GiB，release、第二版数据根、进程、命令、W&B、唯一after_lock和错误扫描正常，连续健康检查达到3/3。显存仍无显著下降结论，但没有真实OOM；后续每3小时监控。unet_c1 内部W&B日志更新到13:46，Slurm和错误扫描正常，没有停滞证据。
- 16:52，Find_0 attempt a4 已推进到 step956，五项损失有限；两张H100使用80.25/80.27GiB，release、第二版数据根、进程、W&B、唯一after_lock和错误扫描正常，仍无真实OOM，尚无checkpoint。unet_c1 已推进到 step1517并完成首次验证：总验证损失0.305254，配体体素PRAUC 0.253671、受体PRAUC 0.230980，蛋白/核酸主链PRAUC 0.036339/0.007578；已保存约500MB的 `TOP_epoch_00_score_0.2537.ckpt` 与 `last.ckpt`。两项继续每3小时监控且不启动CPC2。
- 19:51，Find_0 attempt a4 最近摘要为 step1460，五项损失有限；摘要暂缓刷新但W&B事件、内部日志和双H100计算持续推进，两张H100使用80.16/79.88GiB，release、第二版数据根、进程、唯一after_lock和错误扫描正常，没有真实OOM，尚无checkpoint。unet_c1推进到step1775，六项训练损失有限，首次验证指标与TOP/last checkpoint保持完整，作业和W&B继续活动。
- 22:52，Find_0 attempt a4 已推进到 step1733并完成首次验证：总验证损失0.419612，配体体素/受体/原子/伪原子PRAUC为0.472018/0.535651/0.533216/0.485918；约1.4GiB的 `TOP_epoch_00_score_0.4720.ckpt` 与 `last.ckpt` 已落盘。refined/unrefined面板因未启用sparse-refine loss按设计为NaN，其余训练损失、验证损失和指标有限。双H100使用80.86/80.44GiB，无真实OOM；release、第二版数据根、进程、唯一after_lock和错误扫描正常。unet_c1推进到step2021，六项损失有限，首次验证和checkpoint继续完整。
- 2026-08-06 01:51，Find_0 attempt a4 推进到step2360，五项训练损失有限；首次验证和TOP/last checkpoint完整，双H100使用80.58/79.49GiB，无真实OOM，release、第二版数据根、进程、唯一after_lock和错误扫描正常。unet_c1最近摘要为step2039且六项损失有限；摘要暂缓刷新但W&B事件与内部日志更新到01:49，首次验证和checkpoint完整，没有停滞或错误证据。
- 2026-08-06 04:52，Find_0 attempt a4 推进到step2921，五项训练损失有限；首次验证和TOP/last checkpoint完整，双H100使用79.89/79.78GiB，无真实OOM，release、第二版数据根、进程、唯一after_lock和错误扫描正常。unet_c1最近摘要为step2057且六项损失有限；W&B事件与内部日志持续更新，首次验证和checkpoint完整，没有停滞或错误证据。
- 正式脚本、配置和产物不新增 SHA/哈希；临时验收命令可以使用。

## unet_c1 A800/H100 吞吐诊断

- 2026-08-06 已完成当前 A800 `dvc1ubk4` 与历史 H100 `3a323sl8` 的只读 W&B/Slurm 分析和三组独立 CPU 因果复放；没有修改、暂停或重启当前 GPU 训练。完整报告为 `talk/unet_c1_A800与H100吞吐定量诊断.md`，服务器证据根为 `/storage/penghongen/tmp/unet_c1_throughput_audit_20260806`，机器摘要为 `analysis/final_summary.json`。
- 验证前 A800/H100 训练速度为 273.784/151.853 step/h，但 GPU 利用率中位数为 98%/42.47%；历史 H100 较慢是随机大文件输入饥饿。validation 中两卡利用率均约 90% 以上，按请求归一后 A800 用时为 H100 的 1.74 倍，反映 H100 的模型前向计算优势。
- A800 validation 后典型三步间隔折算为 272.778 step/h，与验证前几乎相同；低区间平均值来自 12 个合计 6.996 小时的离散长空档。空档中 GPU、CPU 基本空闲且进程内存稳定。无 validation、第二版完整 validation、第一版完整 validation 三组 CPU 对照的后置训练窗口分别比前置窗口快 2.9%、8.2% 和 7.0%，排除了 validation 固定破坏 DataLoader。
- 根本工程风险是训练请求没有 PDB 局部性、512 MiB worker 私有缓存持续 miss、单 stripe 大 NPZ 需要完整数组物化，以及共享 Lustre 尾延迟；当前证据不能把某个历史长空档唯一归因到特定 OST、外部作业或节点事件。优先改进大数组局部读取格式，其次再分别优化 train/validation 缓存、节点侧 validation 暂存和 worker/CPU；PDB 局部微分组采样属于会改变样本相关性的科学实验。
- 07:54，Find_0 attempt a4 推进到step3143并完成第二次验证：总验证损失由0.419612改善到0.360815，配体体素/受体/原子/伪原子PRAUC提升到0.511648/0.598803/0.603966/0.539441；新 `TOP_epoch_00_score_0.5116.ckpt` 与 `last.ckpt` 已落盘。`BEST.ckpt` 当前仍对应上一轮0.4720 TOP，按一次验证延迟继续观察。双H100使用80.97/80.28GiB，无真实OOM，release、第二版数据根、进程、唯一after_lock与错误扫描正常。unet_c1推进到step2348，六项损失有限，首次验证和checkpoint完整。
- 10:55，Find_0 attempt a4 推进到step3731，五项训练损失有限；第二次验证与新TOP/last checkpoint完整，BEST仍对应上一轮0.4720 TOP。双H100使用80.30/80.62GiB，无真实OOM，release、第二版数据根、进程和唯一after_lock正常。09:40–09:43数次可重试W&B API 500警告已经自行恢复，摘要、事件与内部日志继续更新。unet_c1最近摘要step2921，六项损失有限，W&B持续活动，首次验证和checkpoint完整。
- 13:57，Find_0 attempt a4 推进到step4331，五项损失有限；第二次验证与新TOP/last checkpoint完整，BEST仍对应上一轮0.4720 TOP，尚未产生第三次验证。双H100使用79.57/80.79GiB；瞬时利用率为0%，但W&B摘要、事件、内部日志与正式进程持续活动，按已知数据读取等待处理，作业只有after_lock且无OOM或异常。unet_c1摘要仍为step2921，但事件和内部日志持续更新、A800利用率100%，首次验证与checkpoint完整，没有停滞证据。
- 16:57，Find_0 attempt a4 推进到step4472并完成第三次验证：总验证损失0.345794，配体体素/受体/原子/伪原子PRAUC提升到0.552684/0.617985/0.625505/0.581426；新TOP0.5527与last完整，BEST已刷新到上一轮0.5116 TOP。unet_c1推进到step3539并完成第二次验证：总验证损失0.274757，配体体素/受体PRAUC提升到0.343178/0.345571；新TOP0.3432与last完整，BEST暂时仍为上一轮0.2537 TOP。两项GPU、W&B、正式进程、唯一after_lock和当前错误扫描正常，无OOM或未处理异常。
- 诊断使用的 CPU Job 335495、336466 和 336494 均已停止生产进程并进入 `try_lock` 后释放准确 `after_lock`。335495/336466 最终为 `COMPLETED 0:0`；336494 在有效第二版结果落盘后停止重复第一版复放，预期为 `FAILED 9:0`。三个 CPU allocation 均已释放，远端证据保留。

## AdaLigand 记录

- ExecPlan：`文档/exec_plan/Stage1第二版BOX池与Find_0重训练实施.md`。
- 检查记录：`talk/Stage1第二版BOX池与Find_0重训练检查记录.md`。
- 上述文件、mapping 与本 handoff 只留在 AdaLigand `Learn/CUMULATIVE` 工作树，不修改索引或其他任务内容。
