# 为 Find_1 增加结构与配体距离辅助监督并完成正式训练

本文是持续更新的 ExecPlan。实施过程中必须同步维护 `Progress`、`Surprises & Discoveries`、`Decision Log` 和 `Outcomes & Retrospective`；任何范围、接口、验证或服务器运行方式变化都要同时修改正文相关位置，并在文末记录修改原因。

本文依据 `C:\Users\15919\Desktop\AdaLigand\grill_with_memory\07-22-17-42.md` 中已经收敛的讨论结论，负责把这些结论实施为 AdaLigand 距离标签、Pocket_Plus 训练与推理代码、完整代码快照、正式 CPC1→CPC2 训练和可恢复的运行记录。本文不实施六分类配体类型标签，不替换整个体素主干，不训练 Selector，也不重新运行 A–G 数据处理管线。

## Purpose / Big Picture

完成后，每个满足现有 Stage1 样本条件的 PDB 都有一份与实验密度网格对齐的 `ligand_dist.npz`。Pocket_Plus Dataset 从现有受体原子字段即时构造蛋白和核酸主链原子体素类别，并从距离文件裁切当前 `80×80×80` BOX。新版 Find_1 使用五个结构一致的逐体素输出头，同时学习现有配体区域、现有受体结合区域、配体反距离、蛋白主链原子和核酸主链原子。

用户可以通过四类结果确认交付成立：距离文件的字段与几何契约可以独立校验；本地和 Linux 测试及真实小样本前向—反向通过；任意 checkpoint 能优先使用运行目录中保存的完整 `src/` 快照进行推理；Job `321540` 保留两张 H100 allocation 并运行新版 Find_1 的完整 CPC1→CPC2。

## Progress

- [x] (2026-07-23 00:00+08:00) 完成 `grill with doc`，冻结辅助标签、损失、模型、快照、Git、CPU、GPU 与监控边界，并获得端到端实施许可。
- [x] (2026-07-23 00:20+08:00) 读取 AdaLigand `AGENTS.md` 触发的规划、代码结构、表达、双线 Git、ExecPlan、项目记忆与服务器交互 skills。
- [x] (2026-07-23 00:30+08:00) 冻结两个累计学习基点并建立隔离实现工作树：AdaLigand `799293c`，Pocket_Plus `de6a89f`。
- [x] (2026-07-23 01:10+08:00) 建立距离标签字段契约、纯计算、原子写入、校验、命令行入口、README 与 5 项专项测试；Linux 完整依赖环境验证仍在后续里程碑执行。
- [x] (2026-07-23 03:20+08:00) 完成 Pocket_Plus Dataset、固定类别契约、精确比例抽样、五个固定输出头、损失、验证指标、Find_1 两阶段配置和完整 `src/` 快照；实现提交为 `c462825`、`acfb018`。
- [x] (2026-07-23 03:20+08:00) 受限 subagent 完成 checkpoint 快照推理、可变 `voxel_final` 通道产物和 Selector 惰性输入，主 agent 审查后提交为 `b54a28d`。
- [x] (2026-07-23 03:20+08:00) 完成独立只读审计并修复缺失原子 NaN、比例抽样总数与元数据、空类别 PR-AUC、固定类别单一来源、输出头宽度、Find_1 专属学习率和 DDP 快照竞争；审计结论为无剩余代码级阻断或科学契约漂移。
- [x] (2026-07-23 03:25+08:00) 本地合并回归为 Pocket_Plus `78 passed`、AdaLigand 距离专项 `5 passed`，两个仓库 `compileall` 与 `git diff --check` 通过。Windows 全量收集缺少服务器专用依赖，保留到 Linux 环境执行。
- [x] (2026-07-23 03:37+08:00) 在真实 `10ad` 上用正式 CLI 生成并校验 `ligand_dist.npz`；28 秒完成，产物约 40 MiB，`failed=0`。
- [x] (2026-07-23 03:48+08:00) 在精确发布目录通过 Pocket_Plus `378 passed` 与 AdaLigand `306 passed`；真实 `10ad` Dataset 读出 56 通道输入和三项新标签，固定模型具有 64 通道 `voxel_final` 与五个两层 1×1×1 输出头。
- [x] (2026-07-23 03:58+08:00) 从 Job `321107`、`321540`、`321743` 各自 allocation 运行时源码只增补缺失快照文件，原有 26 个文件逐字核验且未覆盖；三种真实 checkpoint 均从补齐快照严格恢复成功。
- [ ] 完成服务器真实前向—反向验证；该步骤在接管 Job `321540` 后使用同一两张 H100 执行，不额外提交 GPU 作业。
- [x] (2026-07-23 11:30+08:00) 聚合全量距离生产的 12 个分片。原数组元素 `323027_6` 在全部目标文件原子落盘、写后验证长时间停留后取消；补验数组 `323275` 对 36 个长尾候选施加每样本 90 秒硬超时。最终 22,386 条状态为 22,369 success、12 skipped、5 unknown_failed，冻结 16 个训练排除 PDB。
- [x] (2026-07-23 12:05+08:00) 用唯一 `POCKET_RUN_STAMP` 接管 Job `321540`；旧 Find_1 进程以 143 退出，Slurm allocation、两张 H100 与 `after_lock_321540` 保留。
- [x] (2026-07-23 12:35+08:00) 按用户补充要求，把 `unet_c1` 的 U-Net 骨干保持不变，仅将最终特征、五个输出头、五项损失、学习率和 16 项训练排除清单与新版 Find_1 对齐；提交 `6c798d6`、`eef5c5b`，本地 34 项专项测试与精确发布目录 Linux 全套 `380 passed`。
- [x] (2026-07-23 12:42+08:00) 用 Job `321107` 的 `kill_lock` 停止旧 `unet_c1`，保留单张 H100、Slurm allocation 与 `after_lock_321107`；唯一新运行目录和精确发布目录均在启动前核验无碰撞。
- [x] (2026-07-23 14:05+08:00) Job `321107` 的新版 `unet_c1` smoke 完成四个训练批次，五项训练损失均为有限值；正式在线 W&B 训练已自动启动。
- [x] (2026-07-23 14:20+08:00) Job `321540` 从精确发布目录 `Pocket_Plus_1909267` 完成新版 Find_1 两卡 smoke：训练前验证、四个训练批次、五项损失与新增 PR-AUC 均完成，上一版本的 CPU/NCCL 错误未再出现。脚本已自动进入正式在线 W&B CPC1，CPC1、CPC2 最高学习率均为 `5e-5`。
- [x] (2026-07-23 14:28+08:00) 独立只读端到端审计完成，没有发现需要中止正式训练的科学契约漂移、无效数据、训练计算错误或目录身份冲突。两项正式训练仍在对应 Job 内运行，两个 `after_lock` 均保留。
- [x] (2026-07-23 14:33+08:00) 完成正式训练启动后的第 2 次健康检查。Find_1 CPC1 到达 `global_step=17`，`unet_c1` 到达 `global_step=95`；两者五项训练损失均为有限值，在线 W&B 持续更新，没有 traceback、显存不足或非预期 NaN。两个正式验证尚未开始，因此蛋白与核酸 PR-AUC 留待后续检查；当前也尚未到达 checkpoint 保存时点。
- [x] (2026-07-23 15:37+08:00) 完成连续第 3 次健康检查并把 heartbeat 从每 30 分钟改为每 5 小时。Find_1 CPC1 到达 `global_step=119`，`unet_c1` 到达 `global_step=260`；五项训练损失仍为有限值，在线 W&B 持续更新，两个 Job 的进程身份、唯一运行目录和 `after_lock` 均正确，没有 traceback、显存不足或非预期 NaN。Find_1 两张 H100 采样约为 80.8/81.6 GiB；两个训练仍未进入首次正式验证，也尚未生成 checkpoint。
- [x] (2026-07-23 18:16+08:00) 用户从 W&B 曲线发现 CPC1 继承的 `warmup_ratio=0.025` 不符合此前统一决定的 `0.005`。按用户授权，分别用 Job `321540` 与 `321107` 的 `kill_lock` 停止错误 warmup 运行，保留两个 allocation 和 `after_lock`；未运行新测试或 smoke，直接以唯一运行标记启动 `warmup_ratio=0.005` 的正式 Find_1 CPC1 与 `unet_c1`。两份 resolved 配置确认五项损失权重、学习率及其他已冻结字段未变。Pocket_Plus 默认配置和契约断言同步修正为提交 `aa1b9e9`。
- [x] (2026-07-23 18:56+08:00) 完成 warmup 纠正重启后的第 1 次健康检查。Find_1 CPC1 到达 `global_step=23`，`unet_c1` 到达 `global_step=41`；两条 `warmup_lr` 均从各自 0.33 倍初始学习率缓慢上升，五项训练损失有限，在线 W&B 持续更新，日志没有 traceback、显存不足或非预期 NaN。Find_1 两张 H100 采样约为 80.3/80.8 GiB，`unet_c1` 约为 62.7/81.6 GiB；尚未到 checkpoint 保存时点。
- [x] (2026-07-23 18:56+08:00) 只读 subagent 完成 Job `321540`、`321107`、`321743` 的差异和从 sbatch 到 resolved 配置的入口链路调查；唯一写入为 `C:\Users\15919\Desktop\AdaLigand\talk\检查记录.md`，没有修改或打断代码、配置、锁、作业、运行产物或 Git。
- [x] (2026-07-23 19:24+08:00) 完成 warmup 纠正重启后的第 2 次健康检查。Find_1 CPC1 到达 `global_step=68`，`unet_c1` 到达 `global_step=113`；两条 `warmup_lr` 继续平稳上升，五项训练损失有限，在线 W&B 持续更新，日志没有 traceback、显存不足或非预期 NaN。Find_1 两张 H100 采样约为 80.6/80.4 GiB，`unet_c1` 约为 62.7/81.6 GiB；首次正式验证指标和 checkpoint 仍未出现。
- [x] (2026-07-23 19:54+08:00) 完成 warmup 纠正重启后的第 3 次健康检查。Find_1 CPC1 到达 `global_step=119`，`unet_c1` 到达 `global_step=191`；两条 `warmup_lr` 连续上升，五项训练损失有限，在线 W&B 持续更新，日志和锁正常。Find_1 两张 H100 采样约为 80.9/81.0 GiB，`unet_c1` 约为 62.9/81.6 GiB；没有显存不足，首次正式验证指标和 checkpoint 仍未出现。
- [x] (2026-07-23 20:24+08:00) 完成 warmup 纠正重启后的第 4 次健康检查。Find_1 CPC1 到达 `global_step=164`，`unet_c1` 到达 `global_step=275`；两条 `warmup_lr` 继续按 `0.005` 预期上升，五项训练损失有限，在线 W&B 持续更新，日志和锁正常。Find_1 两张 H100 采样约为 80.6/80.6 GiB，`unet_c1` 约为 62.9/81.6 GiB；没有显存不足，首次正式验证指标和 checkpoint 仍未出现。
- [x] (2026-07-23 20:54+08:00) 完成 warmup 纠正重启后的第 5 次健康检查并把 heartbeat 改为每 5 小时。Find_1 CPC1 到达 `global_step=215`，`unet_c1` 到达 `global_step=347`；两条 `warmup_lr`、五项训练损失、在线 W&B、日志和锁持续正常。Find_1 两张 H100 采样约为 81.0/80.7 GiB，`unet_c1` 约为 62.9/81.6 GiB；没有显存不足，首次正式验证指标和 checkpoint 仍未出现。
- [x] (2026-07-23 20:55+08:00) 按用户要求把 Job `321743` 的旧版 Find_0 一并纳入后续 heartbeat。它继续按自身运行目录、resolved 配置、学习率、损失、W&B、checkpoint 和锁检查，不套用新版辅助监督字段；入口链路和三项任务差异见 `C:\Users\15919\Desktop\AdaLigand\talk\检查记录.md`。
- [x] (2026-07-24 02:01+08:00) 完成第一次三作业联合检查。Job `321540` 新版 Find_1 到达 `global_step=698`，Job `321107` 新版 `unet_c1` 到达 `global_step=1112`；两者学习率、五项损失、在线 W&B、日志、锁和显存正常，仍未进入首次正式验证或保存 checkpoint。Job `321743` 旧版 Find_0 到达 `global_step=5483`，正式验证损失与 F1/PRAUC 有限，已有 BEST、last 和 TOP checkpoints，W&B 在线；两张 H200 采样约为 142.1/142.8 GiB（各总计约 143.8 GiB），余量较小但没有显存不足。
- [x] (2026-07-24 07:04+08:00) 完成第二次三作业联合检查。三个 Slurm 作业均为 `RUNNING`，各自只保留 `after_lock`，错误扫描没有发现 traceback、显存不足或非预期 NaN。Job `321540` 新版 Find_1 到达 `global_step=1241`，五项训练损失有限，运行配置仍为 Gaussian `sigma=0.7`、`warmup_ratio=0.005`、最高学习率 `5e-5` 和全局批量 48；尚未进入首次正式验证或保存 checkpoint。Job `321107` 新版 `unet_c1` 到达 `global_step=1325`，首次正式验证总损失为 `0.273812`，蛋白主链与核酸主链宏平均 PR-AUC 分别为 `0.0381163` 和 `0.00681047`，已保存 `TOP_epoch_00_score_0.2738.ckpt` 与 `last.ckpt`。Job `321743` 旧版 Find_0 到达 `global_step=6233`，既有验证指标和 BEST、last、TOP checkpoints 继续有效；两张 H200 采样约为 142.4/142.6 GiB（各总计约 143.8 GiB），余量仍小但没有显存不足。
- [x] (2026-07-24 12:01+08:00) 完成第三次三作业联合检查。三个作业仍为 `RUNNING`，Slurm batch step、W&B 步数和 GPU 采样持续推进，各自只有 `after_lock`，错误扫描为空。Job `321540` 新版 Find_1 到达 `global_step=1430`，首次正式验证总损失为 `0.423916`，蛋白主链与核酸主链宏平均 PR-AUC 分别为 `0.111973` 和 `0.00329660`，已保存 `TOP_epoch_00_score_0.4239.ckpt` 与 `last.ckpt`；运行配置与五项损失保持不变。Job `321107` 新版 `unet_c1` 到达 `global_step=2180`，首次验证指标与 TOP、last checkpoints 保持有效。Job `321743` 旧版 Find_0 到达 `global_step=6773`，最新验证总损失为 `0.330061`，受体与配体区域 PR-AUC 分别为 `0.660388` 和 `0.606173`，已更新 TOP 与 last checkpoints；两张 H200 采样约为 141.7/141.4 GiB。两个 Find 均尚未从 CPC1 切换到 CPC2。
- [x] (2026-07-24 17:03+08:00) 完成第四次三作业联合检查。三个作业均为 `RUNNING`，配置、唯一运行目录、`after_lock` 和错误扫描没有变化。Job `321540` 新版 Find_1 到达 `global_step=1973`，五项训练损失保持有限，首次验证与 TOP、last checkpoints 继续有效。Job `321107` 新版 `unet_c1` 到达 `global_step=2630`；`wandb-summary.json` 在 14:43 后暂未刷新，但 W&B 二进制事件文件、内部日志和 GPU 采样持续更新到 17:03，GPU 利用率为 84%–100%，因此当前没有进程停滞证据。allocation 总日志中出现的 Hydra traceback 属于已经退出的旧启动尝试，不属于当前唯一运行目录。Job `321743` 旧版 Find_0 到达 `global_step=7529`，既有验证与 checkpoints 保持有效；两张 H200 最新采样约为 142.7/142.5 GiB。两个 Find 均尚未进入 CPC2。
- [x] (2026-07-24 22:04+08:00) 完成第五次三作业联合检查。三个作业均为 `RUNNING`，各自配置、唯一运行目录、`after_lock`、GPU 采样和 W&B 事件流持续有效。Job `321540` 新版 Find_1 到达 `global_step=2528`，训练损失有限，首次验证与 TOP、last checkpoints 保持有效；W&B 内部日志中的 traceback 是 7 月 23 日一次 GraphQL 请求被限流后的自动重试，当前摘要已继续刷新，不是训练错误。Job `321107` 新版 `unet_c1` 到达 `global_step=3236`，第二次验证总损失从 `0.273812` 降至 `0.241217`，受体与配体区域 PR-AUC 从 `0.370737`、`0.397535` 升至 `0.448923`、`0.456689`，蛋白主链宏平均 PR-AUC 从 `0.0381163` 升至 `0.0508417`，核酸主链宏平均 PR-AUC 从 `0.00681047` 降至 `0.00279204`；已保存新的 TOP 与 last checkpoints。Job `321743` 旧版 Find_0 到达 `global_step=8084`，最新验证总损失为 `0.328610`，并更新 TOP 与 last checkpoints；两张 H200 最新采样最高约为 142.8/143.0 GiB，余量很小但没有显存不足。两个 Find 均尚未进入 CPC2。
- [x] (2026-07-25 16:27+08:00) 完成第六次三作业联合检查。三个作业均为 `RUNNING`，精确发布身份、最终配置、唯一运行目录和各自唯一的 `after_lock` 正确；当前运行目录没有训练 traceback、显存不足或数据契约错误，W&B 事件流与 GPU 采样持续更新。Job `321540` 新版 Find_1 到达 `global_step=3971`，最新验证总损失降至 `0.343283`，蛋白与核酸主链宏平均 PR-AUC 分别升至 `0.976166` 和 `0.947399`，并保存新的 TOP 与 last checkpoints。Job `321107` 新版 `unet_c1` 到达 `global_step=5258`，第三次验证总损失降至 `0.231801`，蛋白与核酸主链宏平均 PR-AUC 分别为 `0.0619655` 和 `0.0283426`，并保存新的 TOP 与 last checkpoints；其摘要文件在 13:09 后暂未刷新，但 W&B 二进制事件文件和 GPU 采样持续更新到 16:28，单张 H100 利用率为 97%，没有进程停滞证据。Job `321743` 旧版 Find_0 到达 `global_step=10931`，最新验证总损失降至 `0.317618`，受体与配体区域 PR-AUC 分别为 `0.686995` 和 `0.615032`，并保存新的 TOP 与 last checkpoints。此次检查期间两张 H200 的最高显存占用为 143.070 GiB，单卡总显存为 143.771 GiB，余量很小但没有显存不足。两个 Find 均尚未进入 CPC2。
- [x] (2026-07-25 21:29+08:00) 完成第七次三作业联合检查。三个作业均为 `RUNNING`，精确发布身份、最终配置、唯一运行目录和各自唯一的 `after_lock` 正确；当前应用日志没有训练 traceback、显存不足或数据契约错误，W&B 事件流与 GPU 采样持续更新。Job `321540` 新版 Find_1 到达 `global_step=4628`，五项训练损失均为有限值，最近一次验证与 TOP、last checkpoints 继续有效。Job `321107` 新版 `unet_c1` 到达 `global_step=6197`，第四次验证总损失从 `0.231801` 降至 `0.221887`，受体与配体区域 PR-AUC 分别升至 `0.535934` 和 `0.504227`，蛋白与核酸主链宏平均 PR-AUC 分别升至 `0.0797290` 和 `0.0845545`；已保存 `TOP_epoch_00_score_0.2219.ckpt` 与新的 `last.ckpt`。Job `321743` 旧版 Find_0 到达 `global_step=11843`，最近一次验证与 TOP、last checkpoints 继续有效。此次检查期间两张 H200 的最高显存占用仍为 143.070 GiB，单卡总显存为 143.771 GiB，余量很小但没有显存不足。两个 Find 均尚未进入 CPC2。
- [x] (2026-07-26 10:07+08:00) 完成第八次三作业联合检查。三个作业均为 `RUNNING`，实际训练进程仍来自各自冻结的发布目录，命令行参数与最终配置保持既定学习率、`warmup_ratio=0.005`、全局批量 48 和对应损失契约；各自只存在 `after_lock`，当前应用日志错误扫描为空，W&B 摘要与 GPU 计算继续更新。Job `321540` 新版 Find_1 到达 `global_step=5864`，最新验证总损失降至 `0.334012`，受体区域、配体区域、蛋白主链与核酸主链 PR-AUC 分别为 `0.651325`、`0.599134`、`0.987488` 和 `0.975704`，并保存 `TOP_epoch_00_score_0.3340.ckpt` 与新的 `last.ckpt`。Job `321107` 新版 `unet_c1` 到达 `global_step=7889`，最新验证总损失降至 `0.219721`，对应四项 PR-AUC 分别为 `0.544096`、`0.507334`、`0.0870110` 和 `0.116536`，并保存 `TOP_epoch_00_score_0.2197.ckpt` 与新的 `last.ckpt`。Job `321743` 旧版 Find_0 到达 `global_step=14066`，最新验证总损失降至 `0.316924`，受体与配体区域 PR-AUC 分别为 `0.693115` 和 `0.623365`，并保存 `TOP_epoch_00_score_0.3169.ckpt` 与新的 `last.ckpt`。新版 Find_1 两张 H100 的最高采样显存占用为 80.844/81.559 GiB，旧版 Find_0 两张 H200 的最高采样占用为 143.054/143.771 GiB；均未发生显存不足。两个 Find 仍在 CPC1。
- [x] (2026-07-26 15:16+08:00) 完成第九次三作业联合检查。三个作业均为 `RUNNING`，训练进程仍来自各自冻结的发布目录，命令行参数保持既定学习率、`warmup_ratio=0.005` 和全局批量 48；各自只存在 `after_lock`，当前应用日志错误扫描为空，W&B 摘要与 GPU 计算继续更新。Job `321540` 新版 Find_1 到达 `global_step=6500`，五项训练损失保持有限，最近一次验证总损失 `0.334012` 及四项 PR-AUC 继续有效。Job `321107` 新版 `unet_c1` 到达 `global_step=8051`，最新验证总损失降至 `0.216680`，受体区域、配体区域、蛋白主链与核酸主链 PR-AUC 分别升至 `0.552024`、`0.522347`、`0.0970976` 和 `0.143969`，并保存 `TOP_epoch_00_score_0.2167.ckpt` 与新的 `last.ckpt`。Job `321743` 旧版 Find_0 到达 `global_step=14678`，最新验证总损失降至 `0.310742`，受体与配体区域 PR-AUC 分别升至 `0.699974` 和 `0.644994`，并保存 `TOP_epoch_00_score_0.3107.ckpt` 与新的 `last.ckpt`。新版 Find_1 两张 H100 的最高采样显存占用为 80.734/81.559 GiB，旧版 Find_0 两张 H200 的最高采样占用为 143.064/143.771 GiB；均未发生显存不足。两个 Find 仍在 CPC1。
- [x] (2026-07-26 20:17+08:00) 完成第十次三作业联合检查。三个作业均为 `RUNNING`，训练进程仍来自各自冻结的发布目录，命令行参数保持既定学习率、`warmup_ratio=0.005` 和全局批量 48；各自只存在 `after_lock`，当前应用日志错误扫描为空，W&B 摘要与 GPU 计算继续更新。Job `321540` 新版 Find_1 到达 `global_step=6725`，最新验证总损失降至 `0.331998`，受体区域、配体区域、蛋白主链与核酸主链 PR-AUC 分别为 `0.654372`、`0.592297`、`0.991848` 和 `0.988387`，并保存 `TOP_epoch_00_score_0.3320.ckpt` 与新的 `last.ckpt`。Job `321107` 新版 `unet_c1` 到达 `global_step=8828`，最近一次验证总损失 `0.216680` 及四项 PR-AUC 继续有效。Job `321743` 旧版 Find_0 到达 `global_step=15389`，最近一次验证总损失 `0.310742` 及两项 PR-AUC 继续有效。新版 Find_1 两张 H100 的最高采样显存占用为 80.864/81.559 GiB，旧版 Find_0 两张 H200 的最高采样占用为 142.998/143.771 GiB；均未发生显存不足。两个 Find 仍在 CPC1。
- [x] (2026-07-27 01:17+08:00) 完成第十一次三作业联合检查。三个作业均为 `RUNNING`，训练进程仍来自各自冻结的发布目录，命令行参数与 W&B 运行配置保持既定学习率、`warmup_ratio=0.005`、全局批量 48 和对应损失权重；各自只存在 `after_lock`，当前应用日志错误扫描为空，W&B 摘要与 GPU 计算继续更新。Job `321540` 新版 Find_1 到达 `global_step=7304`，五项训练损失有限，最近一次验证总损失 `0.331998`、四项 PR-AUC 以及 TOP、last checkpoints 继续有效。Job `321107` 新版 `unet_c1` 到达 `global_step=9206`，五项训练损失有限，最近一次验证与 checkpoints 继续有效。Job `321743` 旧版 Find_0 到达 `global_step=15926`，最新验证总损失降至 `0.307528`，受体与配体区域 PR-AUC 分别升至 `0.703757` 和 `0.636299`，并保存 `TOP_epoch_00_score_0.3075.ckpt` 与新的 `last.ckpt`。本次采样中，新版 Find_1 两张 H100 最高占用 80.626/81.559 GiB，旧版 Find_0 两张 H200 最高占用 142.306/143.771 GiB；均未发生显存不足。两个 Find 仍在 CPC1。
- [x] (2026-07-27 06:16+08:00) 完成第十二次三作业联合检查。三个作业均为 `RUNNING`，训练进程仍来自各自冻结的发布目录，命令行参数保持既定学习率、`warmup_ratio=0.005` 和全局批量 48；各自只存在 `after_lock`，当前应用日志错误扫描为空，W&B 摘要与 GPU 计算继续更新。Job `321540` 新版 Find_1 到达 `global_step=7880`，五项训练损失有限，最近一次验证与 checkpoints 继续有效。Job `321107` 新版 `unet_c1` 到达 `global_step=9662`，最新验证总损失降至 `0.215768`，受体区域、配体区域、蛋白主链与核酸主链 PR-AUC 分别为 `0.550378`、`0.516296`、`0.109687` 和 `0.165010`，并保存 `TOP_epoch_00_score_0.2158.ckpt` 与新的 `last.ckpt`。Job `321743` 旧版 Find_0 到达 `global_step=16733`，最近一次验证与 checkpoints 继续有效。本次采样中，新版 Find_1 两张 H100 最高占用 80.682/81.559 GiB，旧版 Find_0 两张 H200 最高占用 143.014/143.771 GiB；均未发生显存不足。两个 Find 仍在 CPC1。
- [x] (2026-07-27 11:16+08:00) 完成第十三次三作业联合检查。三个作业均为 `RUNNING`，训练进程仍来自各自冻结的发布目录，命令行参数保持既定学习率、`warmup_ratio=0.005` 和全局批量 48；各自只存在 `after_lock`，当前应用日志错误扫描为空，W&B 摘要与 GPU 计算继续更新。Job `321540` 新版 Find_1 到达 `global_step=8126`，最新验证总损失降至 `0.325117`，受体区域、配体区域、蛋白主链与核酸主链 PR-AUC 分别升至 `0.682811`、`0.619510`、`0.993087` 和 `0.990706`，并保存 `TOP_epoch_00_score_0.3251.ckpt` 与新的 `last.ckpt`。Job `321107` 新版 `unet_c1` 到达 `global_step=10520`，五项训练损失有限，最近一次验证与 checkpoints 继续有效。Job `321743` 旧版 Find_0 到达 `global_step=17354`，本次验证总损失为 `0.311083`，受体与配体区域 PR-AUC 为 `0.699321` 和 `0.643448`；结果有限但未优于此前 `0.307528`，新的 `TOP_epoch_00_score_0.3111.ckpt` 与 `last.ckpt` 均完整保存。本次采样中，新版 Find_1 两张 H100 最高占用 80.776/81.559 GiB，旧版 Find_0 两张 H200 最高占用 142.312/143.771 GiB；均未发生显存不足。两个 Find 仍在 CPC1。
- [ ] 形成两个仓库的实现端点与学习端点，验证允许差异后推进各自 `Learn/CUMULATIVE`。
- [ ] 完成新版 Find_1 CPC1→CPC2 与新版 `unet_c1` 正式训练的短期检查和 heartbeat 监控。
- [ ] 收口映射索引、README、ExecPlan、`CLAUDE/memory/`、运行证据和 heartbeat。

## Surprises & Discoveries

- Observation: 新版 `unet_c1` 保存验证总损失为 `0.221887` 的 TOP checkpoint 后，`BEST.ckpt` 仍与上一轮 `TOP_epoch_00_score_0.2318.ckpt` 内容相同。
  Evidence: 2026-07-25 21:31+08:00 的服务器只读校验显示两个文件 SHA-256 均为 `90fb5d33…210`，而 `TOP_epoch_00_score_0.2219.ckpt` 为 `467535c4…4d7`。精确发布 `Pocket_Plus_9417bcf/src/train.py` 中 `BestCheckpointAlias` 在 `on_validation_end` 和 `on_train_end` 刷新别名；服务器当前 Lightning 的 `trainer/connectors/callback_connector.py::_reorder_callbacks` 明确把 `ModelCheckpoint` 移到其他 callback 之后执行，因此训练过程中别名会落后一轮验证，训练正常结束时会再次刷新。当前 TOP checkpoint 已完整保存，训练继续运行，这一行为不阻断当前训练；CPC1 结束后必须核对 `BEST.ckpt` 与最终 `best_model_path` 的内容一致性。
  Update: 2026-07-26 10:07+08:00 的只读校验显示该行为继续保持，并且另外两个训练也表现出同样的一轮延迟：新版 Find_1 的 `BEST.ckpt` 对应 `0.3433`，最新 TOP 为 `0.3340`；新版 `unet_c1` 的 `BEST.ckpt` 对应 `0.2219`，最新 TOP 为 `0.2197`；旧版 Find_0 的 `BEST.ckpt` 对应 `0.3171`，最新 TOP 为 `0.3169`。三份最新 TOP 均完整存在，当前训练不受阻；两个 Find 从 CPC1 切换到 CPC2 前，以及 `unet_c1` 正常结束后，都必须核对最终 `BEST.ckpt`。
  Update: 2026-07-26 15:16+08:00 的只读校验显示，新版 `unet_c1` 与旧版 Find_0 又分别保存了 `0.2167` 和 `0.3107` 的新 TOP，`BEST.ckpt` 仍各自对应上一轮 `0.2197` 和 `0.3169`；新版 Find_1 尚未产生新验证。该现象继续符合已查明的回调执行顺序，最新 TOP 文件均完整存在。
  Update: 2026-07-26 20:17+08:00 的只读校验显示，新版 Find_1 保存了 `0.3320` 的新 TOP，`BEST.ckpt` 对应上一轮 `0.3340`；新版 `unet_c1` 与旧版 Find_0 尚未产生下一次验证。三项最新 TOP 文件继续完整存在。
  Update: 2026-07-27 01:17+08:00 的只读校验显示，旧版 Find_0 保存了 `0.3075` 的新 TOP，`BEST.ckpt` 仍对应上一轮 `0.3107`；新版 Find_1 与 `unet_c1` 尚未产生下一次验证。三项最新 TOP 文件继续完整存在。
  Update: 2026-07-27 06:16+08:00 的只读校验显示，新版 `unet_c1` 保存了 `0.2158` 的新 TOP，`BEST.ckpt` 仍对应上一轮 `0.2167`；两个 Find 尚未产生下一次验证。三项最新 TOP 文件继续完整存在。
  Update: 2026-07-27 11:16+08:00 的只读校验显示，新版 Find_1 保存了 `0.3251` 的新最佳 TOP，`BEST.ckpt` 仍对应上一轮 `0.3320`；新版 `unet_c1` 的 `BEST.ckpt` 仍对应 `0.2167`，尚未指向 `0.2158`。旧版 Find_0 本次验证总损失 `0.311083` 未优于此前的 `0.307528`，`BEST.ckpt` 已在本次验证开始时刷新并与 `TOP_epoch_00_score_0.3075.ckpt` 内容相同，因此其最佳别名当前正确。三项当前最佳 TOP 文件均完整存在。

- Observation: AdaLigand 与 Pocket_Plus 的常用工作区都已有未提交修改，Pocket_Plus 还包含当前正式训练相关的大量代码和配置变化。
  Evidence: 2026-07-23 的 `git status --short --branch` 显示 AdaLigand 有讨论和同步工具修改，Pocket_Plus 有 Dataset、模型、推理、Selector、配置和项目记忆修改。本文因此使用两个隔离 worktree，不在原工作区编辑或暂存文件。
- Observation: Pocket_Plus 尚未建立新名称 `Learn/CUMULATIVE`，当前累计学习基点仍名为 `Learn/model-cumulative`。
  Evidence: `Learn/model-cumulative` 与 `origin/Learn/model-cumulative` 均指向 `de6a89f`。本任务保留旧分支，并创建 `Learn/CUMULATIVE` 指向同一提交。
- Observation: 正式 centered 产物和 Selector 输入把 `voxel_final` 固定为 48 通道，但当前没有已经训练的 Selector 权重。
  Evidence: `src/artifacts/io.py`、`src/inference/centered.py` 和 `src/selector/model/input_fusion.py` 存在固定 48 的形状检查或 `nn.Linear(48, ...)`；用户确认尚未训练 Selector。
- Observation: 当前 Find_1 是 CPC1→CPC2 两段训练，而不是一个配置完成全部训练。
  Evidence: `configs/experiment/CPC2/Find_1.yaml` 从同名 CPC1 最佳 checkpoint 初始化，`configs/frozen_module/adaligand_stage2.yaml` 冻结体素主干，`configs/loss/stage1_find_cpc2.yaml` 把现有体素损失权重设为零。
- Observation: 当前 Windows 默认 Python 有 NumPy 与 SciPy，但没有 RDKit；原计划中的本地 `AdaLigand_stage1_py310` Conda 环境也不存在。
  Evidence: `python -m pytest tests/test_ligand_distance.py` 在把 Stage C 导入延迟到文件读取边界后为 `5 passed`；导入现有 Stage C 完整契约会因 `ModuleNotFoundError: rdkit` 中止。完整 A–G 测试必须使用服务器既有依赖环境。
- Observation: Stage C 允许 `present=False` 的配体坐标保存 NaN，距离生产只能检查 `present=True` 坐标是否有限。
  Evidence: 独立审计用 A–G 契约核对后发现第一版在应用 `present` 掩码前检查全部坐标；修正提交 `e5234c9` 使用真实 NaN 测试覆盖缺失原子。
- Observation: 单个 Slurm task 内运行两张 GPU 时，Lightning 子进程共享 `SLURM_PROCID=0`，必须优先使用 `RANK` 或 `LOCAL_RANK` 判断代码快照写入者。
  Evidence: 独立审计发现第二个 DDP 子进程可能重复创建 `src_snapshot`；`ExperimentManager` 现按 `RANK → LOCAL_RANK → SLURM_PROCID` 解析，并有继承组合测试。
- Observation: Job `321540` 仍为 `RUNNING`，`after_lock` 保留；同一 allocation 再次运行 Find_1 时，默认 `job321540` 标记会与旧运行目录重名。
  Evidence: 2026-07-23 02:55+08:00 的只读 `scontrol` 与 allocation 脚本检查确认两张 H100 和锁循环仍在。新版启动必须显式设置唯一 `POCKET_RUN_STAMP`，在触碰 `kill_lock` 前打印并证明新旧运行目录不同。
- Observation: 项目安全同步入口不删除远端旧文件，因此共享服务器代码目录可以保留本地分支已经删除的配置和测试，不能作为精确发布目录。
  Evidence: 共享目录测试额外收集旧 `Find_2` 配置与历史测试并得到与本地不同的测试数量；从空目录建立的提交命名发布副本分别通过 Pocket_Plus `378 passed` 与 AdaLigand `306 passed`。新版训练必须从精确发布副本启动，不从共享目录或旧 allocation runtime 猜测代码集合。
- Observation: 真实 `10ad` 中，第一个中心 BOX 的蛋白 N/CA/C/O 体素数分别为 968、965、945、943，核酸前景类别为空；配体反距离目标范围为 0.0143756–0.7884504。
  Evidence: CPU 作业 `323026` 从正式 BOX pool 的 `train/10ad.npz` 直接构造请求，读取新距离文件、三项标签和 56 通道密度输入，并成功实例化新版固定五头模型。
- Observation: 全量距离 array `323027` 的分片 2、3、4、7、11 各出现一条 `unknown_failed`；对应 PDB 是 `6k0a`、`7pel`、`9wqp`、`7ojf`、`9yx6`，五者均缺少正式 `density/{pdb_id}/exp.npz`，不是距离计算产生 NaN 或写盘失败。
  Evidence: `status.part_0002_of_0012.jsonl`、`status.part_0003_of_0012.jsonl`、`status.part_0004_of_0012.jsonl`、`status.part_0007_of_0012.jsonl` 与 `status.part_0011_of_0012.jsonl` 分别记录 `FileNotFoundError`；对应 Slurm task 本身均为 `COMPLETED 0:0`，程序汇总各报告 `failed=1`。在 12 个分片聚合完毕并处理训练样本排除前，不允许接管 Job `321540`。
- Observation: 分片 6 的 1,865 个目标文件已经全部原子落盘，但原作业停在少数超大文件的写后完整重读验证；`2w49` 的距离文件约 99 GB，分片峰值内存约 636 GB。
  Evidence: 原日志长时间停在 `Done 1829 tasks`，同时精确核对确认分片 6 的 1,865 个 `ligand_dist.npz` 均存在。取消 `323027_6` 后，数组 `323275` 对 36 个最大长尾候选执行独立 90 秒验证，25 个通过，11 个按超时跳过，无其他错误。
- Observation: Find_1 的第一份单步 smoke 把 `max_steps` 限制为 1，而候选 warmup 步数按 `round(total_steps × warmup_ratio)` 解析，因此得到 0 并在尚无验证阈值时错误进入自适应阈值路径。
  Evidence: 两个 DDP rank 均报 `p_best_by_class` 缺失；GPU 峰值约 29–30 GiB，不是显存不足。旧正式运行和新正式 CPC1 都保留 `warmup_steps: null` 与正的 warmup 比例，完整训练会解析出正数 warmup。重试只给单步 smoke 显式设置 `warmup_steps=1`，没有修改模型、候选逻辑或正式 CPC1 配置。
- Observation: 两次 Find_1 重试都在训练前验证结束时把 CPU 上的非分箱 PRAUC 标量交给 NCCL，两个进程均报 `No backend type associated with device type cpu`。
  Evidence: 旧 Job `321540` 的实际运行快照不但给 CPU 指标使用 Gloo 通信组，还在指标已经完成跨卡聚合后以 `sync_dist=False` 写入 Lightning。提交 `9f4012d` 只恢复了前半项；提交 `1909267` 同时恢复后半项，避免 Lightning 使用默认 NCCL 通信组二次同步 CPU 标量。正式 CPC1 的候选选择和 warmup 配置未改变。
- Observation: 旧 Job `321540` 的实际配置同时写有 `use_soft_splatting=true` 与 `use_gaussian_splatting=true`，旧代码按 Gaussian 优先级执行 sigma=0.7 的 `3×3×3` 写入；原训练计划误写成三线性写入。
  Evidence: 独立审计对比旧运行快照和新版代码后发现该差异。用户明确选择以旧运行的真实 Gaussian 行为为新基线；提交 `9417bcf` 恢复开关、优先级和两条前向路径，并把冲突规格同步为 Gaussian。
- Observation: 新版正式启动沿用了 `configs/train/stage1_cpc1.yaml` 中的 `warmup_ratio=0.025`，但用户此前统一决定的优化器学习率 warmup 比例是 `0.005`。
  Evidence: 两项旧运行的 resolved 配置均记录 `0.025`，W&B 的 `warmup_lr` 曲线也显示过长的线性增长。用户发现后要求立即重启；新运行 resolved 配置均记录 `0.005`，且五项损失权重逐项不变。
- Observation: Find_1 smoke 的 `refined` 与 `unrefined` 面板显示 `NaN`，但训练损失、验证损失、候选统计和已定义的 PR-AUC 均为有限值。
  Evidence: 当前 Find_1 没有启用 `ligand_sparse_refine_loss`，因此不会生成 `ligand_refine_target_C`，对应诊断缓冲区按既有定义把未启用面板记为 `NaN`。这些面板不参与损失、学习率调度、BEST checkpoint 选择或本次新增监督；smoke 的 `val_loss/global/total=0.76348`，蛋白主链宏平均 PR-AUC 为 `0.00133`。正式完整验证仍需确认核酸主链 PR-AUC 能在出现正类后记录。
- Observation: Find_1 两卡 smoke 和正式 CPC1 的单卡显存峰值接近 H100 容量上限。
  Evidence: smoke 峰值约为 80.98 GiB 与 81.56 GiB；14:28 的正式 CPC1 采样为 80.78 GiB 与 80.84 GiB，尚未发生显存不足。若后续样本触发显存不足，先按既定顺序把 density-cube 的 `hidden_channels` 从 64 调到 48，再考虑减小批量。
- Observation: 第一版 `unet_c1` 对齐配置已经构造三个新增输出头，但 Dataset 最初只在 `Find_1` 名称下返回蛋白、核酸与反距离目标。
  Evidence: 新增真实 `unet_c1` Dataset 测试首先复现缺少 `protein_mainchain_target`，随后把固定辅助标签返回范围精确扩展到 `Find_1` 与 `unet_c1`；34 项专项测试和 Linux 全套测试通过。

## Decision Log

- Decision: 蛋白分类头固定为背景、`N`、`CA`、`C`、`O`；核酸分类头固定为背景、`P`、`O5'`、`C5'`、`C4'`、`C3'`、`O3'`。训练配置不提供动态类别规则或 `class_id`。
  Rationale: 固定类别覆盖本轮科学目的，避免把小范围改动扩大成动态标签框架。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: 两个分类头在完整 `80³` BOX 上计算 `0.7×Focal + 0.3×Dice`，Focal `gamma=2`、无类别 alpha；Dice 对每个非背景类别分别计算后等权平均。
  Rationale: 完整网格监督训练空间定位能力，并沿用现有体素损失归约方式。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: `ligand_dist.npz` 保存 `float16` 原始 Å 距离；训练目标为 `1/(1+d/(1 Å))`，完整 BOX 平均 MSE。没有实际配体原子时磁盘距离全为正无穷，训练目标全为零。
  Rationale: 原始距离是稳定事实；反距离是有限、可训练的表达。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: 五个最高分辨率体素输出头统一为 `Conv1x1(C,C) → ReLU → Conv1x1(C,C_out)`。新版 Find_1 关闭 RAUNet 末端多尺度输出块，令 `voxel_final=c0` 并把通道数改为 64。
  Rationale: 最高分辨率的 3、5、7 体素宽空间卷积成本很高，体素主干此前已经混合空间信息。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: 现有配体区域、受体结合区域、配体反距离、蛋白原子、核酸原子损失权重分别为 `1.0:0.1:0.3:0.05:0.05`。新增 W&B 曲线只包含三项新增组合损失和两个验证宏平均 PR-AUC。
  Rationale: 保持现有主损失尺度，并限制监控改动范围。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: 新 Find_1 从头运行完整 CPC1→CPC2；新增辅助损失和 PR-AUC 只在 CPC1 启用，CPC2 冻结体素主干并把三项新增损失权重设为零。Find_1 两段最高学习率均为 `5e-5`；新版 `unet_c1` 继续使用 `1e-4`。
  Rationale: 保持 Find_1 的既有两阶段职责，同时让辅助监督只塑造 CPC1 体素表示。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: `box_sample_fraction=1.0` 完全保留当前逐 epoch BOX 选择；只有小于 1 时才生成并复用按比例和 seed 命名的训练、验证选择文件。首次正式新 Find_1 使用 1.0。
  Rationale: 默认训练不能因为新增消融开关改变样本多样性。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: 训练运行目录保存完整 `src/`、解析后的配置和来源清单。checkpoint 推理优先使用相邻快照；缺少快照时默认报错，只有显式选择才允许当前工作区代码。
  Rationale: 模型、Dataset、wrapper 与推理代码共同决定 checkpoint 的可复现行为。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: 正式产物按实际模型通道数处理 `voxel_final`，Selector 使用 `nn.LazyLinear` 接受第一次看到的通道数，不增加 64→48 投影。
  Rationale: 当前没有 Selector 权重需要兼容，通道数不应成为多个文件复制的常量。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: 距离标签 CPU 生产的同时运行上限为 192 核；96 核整节点不能立即取得时，使用每项约 16 核的 Slurm array 与 joblib loky。正式 GPU 训练只接管 Job `321540`，不提交其他 GPU 训练作业。
  Rationale: 小 CPU 任务更容易使用碎片资源，GPU allocation 必须保留现有两张 H100 和锁语义。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: 本次全量生产只对分片 6 的 36 个长尾候选使用 90 秒硬超时，不增加体素数上限，不重跑已经完成的 95% 样本。超时 PDB 与缺少实验密度的 PDB 一并进入冻结训练排除清单。
  Rationale: 当前优先快速启动训练；独立子进程硬超时能结束 SciPy 的长时间 C 计算，同时不改变已经落盘距离文件的字段、数值与单位契约。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: Job `321107` 重新训练 `unet_c1`；U-Net 骨干和五路中间特征接口不替换，只把最终体素特征设为 64 通道、关闭末端多尺度卷积、启用与 Find_1 相同的五个两层 `1×1×1` 输出头，并使用相同辅助损失、学习率和训练排除清单。
  Rationale: 用户要求比较同一 `unet_c1` 骨干在新版输出监督下的训练结果，不把任务扩大成体素骨干替换。
  Date/Author: 2026-07-23，用户与 Codex。
- Decision: Find_1 CPC1 与 `unet_c1` 的优化器学习率 warmup 比例统一为 `0.005`；Find_1 CPC2 继续无 warmup。此次纠正保留全部辅助损失权重、学习率、网络和数据设置。
  Rationale: 用户确认 `0.005` 才是此前统一决定的值，并要求不把调度器纠正扩大成其他训练改动。
  Date/Author: 2026-07-23，用户与 Codex。

## Outcomes & Retrospective

距离标签代码、Pocket_Plus 新版训练代码、完整快照和推理适配已经完成本地与 Linux 测试、独立审计和真实 `10ad` 验证。三个历史运行快照已经按各自实际执行源码只增补缺失文件，并通过真实 checkpoint 严格恢复。正式距离生产已经形成 22,386 条完整状态和 16 个 PDB 的冻结训练排除清单；证据位于本次运行的 `summary.json`、`ligand_dist_failures.json` 和 `timeout_repair_status.jsonl`。独立端到端审计未发现正式训练阻塞。首轮正式训练因错误继承 `warmup_ratio=0.025` 而由用户叫停；Job `321107` 与 `321540` 现已直接启动 `warmup_ratio=0.005` 的新版正式训练，两个 allocation 和 `after_lock` 均保留。

## Context and Orientation

AdaLigand 实现工作树是 `C:\Users\15919\.codex\worktrees\019f8834-aux\AdaLigand`，分支是 `codex/auxiliary-supervision-find1`，共同基点是 `Learn/CUMULATIVE@799293c`。数据处理代码位于 `Data_Preprocessing/Ori_Data/adaligand_preprocessing/`，产物冷读契约位于 `Data_Preprocessing/Ori_Data/README.md`。

Pocket_Plus 实现工作树是 `C:\Users\15919\.codex\worktrees\019f8834-aux\Pocket_Plus`，分支同为 `codex/auxiliary-supervision-find1`，共同基点是新建的 `Learn/CUMULATIVE@de6a89f`。Dataset 位于 `src/datasets/stage1_dataset.py`，模型位于 `src/model/`，训练 wrapper 位于 `src/wrappers/`，正式产物位于 `src/artifacts/`，推理位于 `src/inference/`，Selector 位于 `src/selector/`。

受体原子局部坐标向下取整后得到该原子所属的唯一体素。蛋白和核酸标签不是只在这些体素上计算损失；目标原子所在体素为相应前景类别，BOX 内其余体素为背景。一个体素包含多个目标原子的极少数情况不建立专门分支，普通写入顺序留下的类别即可。

`ligand_dist.npz` 位于服务器正式数据根的 `density/{pdb_id}/ligand_dist.npz`。主数组 `distance` 形状为 `(1,Z,Y,X)`、类型为 `float16`，每个数值是对应实验密度体素中心到最近实际配体重原子的欧氏距离，单位 Å。实际配体重原子来自全部成功 occurrence 中 `present=True` 的原子。

Job `321540` 当前持有两张 H100。只有标签、代码、推理、测试和历史快照补齐全部完成后，才重新核实它仍在运行且实际承载旧 Find_1；核实通过后使用该运行目录的 `kill_lock` 停止旧进程，保留 `after_lock` 和 allocation，再启动新版 Find_1。不得执行 `scancel`。

复用 Job `321540` 时必须为新版训练显式设置唯一 `POCKET_RUN_STAMP`。启动脚本在创建 `kill_lock` 前先打印计划运行目录，并与旧 Find_1 路径比较；相同则停止，不允许覆盖旧运行目录或放宽快照拒绝覆盖保护。

## Plan of Work

第一个里程碑在 AdaLigand 中建立距离标签生产。先把距离的纯计算、字段契约、原子写入和校验分开，使小数组测试不依赖服务器。命令行入口只解析路径、分片和并行参数。代表性测试覆盖普通配体、没有实际配体原子、来源摘要变化、各向异性体素尺寸和断点复用。README 增加 `ligand_dist.npz` 的完整字段、坐标和缺失值说明。

第二个里程碑在 Pocket_Plus 中实现 Dataset 与模型训练。固定类别表只保存在一个模块；Dataset 根据现有逐原子坐标、残基类型、主链标志和原子名构造两张分类标签，并裁切距离图。`box_sample_fraction` 的默认路径不得生成选择文件。模型建立五个统一输出头，关闭多尺度输出块时不申请相关参数。wrapper 连接损失、权重和最少 W&B 指标。训练配置明确写出 64 通道、关闭多尺度块、学习率和辅助权重。

第三个里程碑扩大代码快照并并行完成推理适配。主 agent 先固定快照目录、来源清单和加载接口，再把 checkpoint 推理、正式产物可变通道和 Selector 惰性输入交给一个 subagent。subagent 只修改约定的推理、产物、Selector 与专项测试文件；主 agent 审查接口、测试和与训练代码的组合结果。历史 Job `321107`、`321540`、`321743` 只从各自实际执行代码或已证明提交补充缺失快照文件，绝不覆盖已有运行文件。

第四个里程碑完成验证。先运行两个 Windows 环境可执行的测试和静态检查，再安全同步到服务器项目目录，在 Linux 环境运行完整测试。代表性真实数据验证距离文件、Dataset 小批次、五个输出头、有限损失、非零梯度、CPC1→CPC2 严格加载、完整快照推理和 64 通道正式产物。真实发生 CUDA 显存不足时，先把 `both.yaml` 的两个 `hidden_channels` 从 64 改为 48；仍不足才降低单卡 batch 并提高梯度累积保持全局 batch。

第五个里程碑整理 Git 双线。两个仓库分别保留实现分支的真实提交；从共同基点建立 `Learn/auxiliary-supervision-find1`，按契约与测试、数据生产、Dataset 与模型、快照与推理、运行配置与证据的顺序重建。实现端点和学习端点只允许学习注释或学习文档差异，通过相同测试后快进各自 `Learn/CUMULATIVE`。

第六个里程碑生产正式距离标签并启动训练。CPU 作业先查看实时节点和 QoS；总申请量不超过 192，分片对 PDB 写入互斥并可断点续跑。最终失败为零时不增加过滤行为；仍有失败时写 `ligand_dist_failures.json`，在训练请求建立前排除对应 PDB。训练前重新核实 Job `321540`、运行目录、锁和 resolved 配置，随后按授权完成旧进程停止与新版 CPC1→CPC2 启动。

第七个里程碑监控和收口。`warmup_ratio=0.005` 的训练启动后，把现有 `adaligand-stage1` heartbeat 指向当前 Codex 任务，每 30 分钟检查一次；连续五次健康后改为每 5 小时。CPC2 正常结束后记录最终状态并删除 heartbeat。同步更新本 ExecPlan、映射索引、项目状态、阶段 handoff 和必要的长期学习记录。

## Concrete Steps

在 AdaLigand 实现工作树运行轻依赖专项检查：

    cd Data_Preprocessing/Ori_Data
    python -m pytest tests/test_ligand_distance.py
    python -m compileall adaligand_preprocessing

在 Pocket_Plus 实现工作树运行：

    conda run -n Pocket_Plus_windows python -m pytest tests
    conda run -n Pocket_Plus_windows python -m compileall src

服务器使用 `/home/penghongen/anaconda3/envs/Pocket_Plus_centos7_cu121_allgpu` 运行 Pocket_Plus 测试。AdaLigand 距离生产使用项目现有 Python 3.10 完整依赖环境；正式命令必须在执行前从当前 sbatch、执行记录和远端环境重新核实，核实结果写回本文。

每个里程碑结束时执行：

    git status --short
    git diff --check

并把实际测试命令、通过数量、失败摘要、提交哈希和服务器证据路径写入本文。

## Validation and Acceptance

距离契约验收要求普通配体样本的若干体素能用直接 NumPy 计算得到相同最近距离；没有配体原子的样本全为正无穷；`distance`、空间字段和三个来源摘要由读取器重新验证。重复执行有效文件必须复用，损坏或来源变化必须明确失败或重建，不留下半成品目标文件。

Dataset 验收要求蛋白、核酸、混合受体、修饰或未知残基和无配体样本均能构造固定形状标签。蛋白和核酸前景体素计数可由受体原子直接核对；距离 BOX 与实验密度 BOX 使用相同起点。`box_sample_fraction=1.0` 的多个 epoch 保持当前不同 BOX 行为，小于 1 的相同 seed 复用同一选择文件且训练读取顺序仍随 epoch 改变。

模型验收要求五个头均为两层 `1×1×1` 卷积；关闭多尺度输出时对应参数不存在，`voxel_final` 为 64 通道。一次完整前向—反向必须得到有限的五项损失，启用的新增头具有非零梯度。CPC2 能严格加载 CPC1 最佳 checkpoint，新增辅助损失不进入 CPC2 total loss。

推理验收要求 checkpoint 有完整快照时使用该快照；缺少快照默认报错；一个进程只加载一套快照。64 通道 centered 文件能够写入、读取和校验，Selector 第一层在首次接收 64 通道特征时正确实例化。

正式训练验收要求 Job `321540` allocation 未释放，没有其他 GPU 训练作业被提交；resolved 配置显示 Find_1、64 通道、关闭多尺度输出、学习率 `5e-5`、`box_sample_fraction=1.0` 和五项正确权重。短期日志没有 traceback、NaN、CUDA 显存不足或数据契约错误，W&B 优先联网并在失败时保留完整 offline 日志。

## Idempotence and Recovery

距离标签按来源摘要复用，写入使用同目录临时文件与原子改名。CPU 分片只处理各自 PDB，重复提交不会覆盖来源相同的有效文件。最终失败 PDB 使用单独 JSON 清单，不修改 A–G keep list、BOX manifest、验证选择或逐 PDB BOX 池。

任何服务器同步只使用项目安全同步入口，不运行删除式同步。任何锁操作前重新读取 Job、进程、运行目录和锁状态。`kill_lock` 只用于用户明确授权的 Job `321540` 旧 Find_1；不删除 `after_lock`，不执行 `scancel`。

实现中发现标签科学定义、A–G 正式产物、现有训练样本或 Job 身份与本文冲突时停止相应副作用，保存证据并报告；不在昂贵运行中静默回退。

## Artifacts and Notes

当前共同基点：

    AdaLigand  799293c584586278ab5f313ce435533e2e1c3ff1
    Pocket_Plus de6a89f38e48553edfd440c76bf61823229d9205

当前实现分支：

    codex/auxiliary-supervision-find1

讨论结论：

    C:\Users\15919\Desktop\AdaLigand\grill_with_memory\07-22-17-42.md

## Interfaces and Dependencies

AdaLigand 最终必须提供一个长期生产函数，接收单个 PDB 的实验密度空间定义、成功配体实例和实际配体坐标，返回或写出本文定义的距离数组与来源字段；另有薄命令行入口支持 PDB 清单、分片、并行数、复用和校验。

Pocket_Plus 最终必须在 Dataset batch 中提供两个整数分类张量和一个浮点反距离张量，三者空间形状均为 `(80,80,80)`；Collator 堆叠为 `(B,80,80,80)`。模型前向返回蛋白、核酸和反距离 logits，wrapper 负责变换、损失与日志。固定类别顺序由单一代码常量定义，测试从同一常量取得预期编号。

完整快照目录固定为运行目录下 `src_snapshot/src/`，并保存来源清单。推理加载器必须把该目录中的 `src` 作为一个 checkpoint 专属实现使用，不在同一 Python 进程混用不同 checkpoint 的模块。

Revision note 2026-07-23：根据用户最终授权初始化本文，并记录隔离工作树、完整范围、固定科学定义、服务器资源纪律和验收要求。

Revision note 2026-07-23 01:10+08:00：记录距离标签第一版、5 项专项测试和 Windows 环境缺少 RDKit 的真实限制，并把 AdaLigand 本地命令改为当前能够执行的轻依赖检查。

Revision note 2026-07-23 03:25+08:00：记录 Pocket_Plus 实现、推理 subagent、独立审计修复、本地合并测试、实现提交和复用 Job `321540` 时必须使用唯一运行标记的启动门槛。

Revision note 2026-07-23 04:01+08:00：记录精确发布目录的 Linux 全套测试、真实 `10ad` 标签与 Dataset 证据、历史 checkpoint 快照补齐及严格恢复、全量距离 array `323027` 和共享目录不能作为精确发布目录的事实。

Revision note 2026-07-23 07:05+08:00：记录 array `323027` 已确认的两个缺失实验密度文件、对应正式状态证据及暂停训练接管的发布门。

Revision note 2026-07-23 07:35+08:00：把分片 4 新确认的 `9wqp` 纳入缺失实验密度文件集合。

Revision note 2026-07-23 08:35+08:00：把分片 11 新确认的 `9yx6` 纳入缺失实验密度文件集合，并确认分片 3、6、8 的累计 CPU 时间仍持续增长。

Revision note 2026-07-23 09:05+08:00：把分片 3 新确认的 `7pel` 纳入缺失实验密度文件集合；array 只剩分片 6，且其累计 CPU 时间仍持续增长。

Revision note 2026-07-23 11:35+08:00：记录分片 6 全部目标已落盘后的 90 秒长尾补验、16 个 PDB 的冻结训练排除清单、完整 22,386 条状态与正式证据摘要。

Revision note 2026-07-23 12:50+08:00：记录 Job `321540` 与 `321107` 的保留资源接管、`unet_c1` 输出监督对齐、Dataset 缺字段修复，以及 Find_1 单步 smoke 的 warmup 取整原因和测试专用修正边界。
Revision note 2026-07-23 13:35+08:00：记录 CPU PRAUC 的 NCCL/Gloo 适配遗漏、旧 Find_1 实际 Gaussian scatter 与书面规格冲突、用户确认的新损失权重、精确发布提交 `9417bcf` 及两个 smoke 同时启动。

Revision note 2026-07-23 14:10+08:00：记录 CPU PRAUC 在 Gloo 聚合后仍被 Lightning/NCCL 二次同步的完整根因、修复提交 `1909267`、Find_1 最高学习率回调到 `5e-5`，以及 `unet_c1` smoke 通过并进入正式训练。

Revision note 2026-07-23 18:20+08:00：记录 `warmup_ratio=0.025` 与用户既定 `0.005` 不符、两项运行经 `kill_lock` 保留资源重启，以及新的五次短周期健康检查要求。

Revision note 2026-07-24 07:08+08:00：记录第二次三作业联合检查、新版 `unet_c1` 的首次正式验证与首批 checkpoint，以及新版 Find_1 尚未进入首次正式验证的当前状态。

Revision note 2026-07-24 12:05+08:00：记录第三次三作业联合检查、新版 Find_1 的首次正式验证与首批 checkpoint，以及两个 Find 尚未进入 CPC2 的状态。

Revision note 2026-07-24 17:07+08:00：记录第四次三作业联合检查，并区分新版 `unet_c1` 当前运行证据与 allocation 总日志中更早的已退出启动错误。

Revision note 2026-07-24 22:08+08:00：记录第五次三作业联合检查、新版 `unet_c1` 第二次正式验证，以及新版 Find_1 历史 W&B 限流重试不影响当前训练的判定。

Revision note 2026-07-24：辅助监督实现已纳入 AdaLigand 与 Pocket_Plus 的本地 Git 双线重建。实现端点、学习端点和核验结果记录在 `文档/exec_plan/双线Git与学习注释重建.md`；本条只关闭“学习线未补全”事项，不关闭仍在进行的三项训练监控和两个 Find 的 CPC 阶段切换。

Revision note 2026-07-25 16:32+08:00：记录第六次三作业联合检查、三项训练的新验证结果，以及新版 `unet_c1` 摘要文件暂缓刷新但事件流与 GPU 计算继续推进的判定。

Revision note 2026-07-25 21:35+08:00：记录第七次三作业联合检查、新版 `unet_c1` 第四次验证，以及 `BEST.ckpt` 在训练中可能落后一轮验证但会在 `on_train_end` 再次刷新的回调行为。

Revision note 2026-07-26 10:12+08:00：记录第八次三作业联合检查、三项训练的新验证结果，并把训练期间 `BEST.ckpt` 落后一轮的核对范围扩展到三项训练。

Revision note 2026-07-26 15:20+08:00：记录第九次三作业联合检查，以及新版 `unet_c1` 和旧版 Find_0 的新验证结果与 checkpoint 状态。

Revision note 2026-07-26 20:21+08:00：记录第十次三作业联合检查，以及新版 Find_1 的新验证结果与 checkpoint 状态。

Revision note 2026-07-27 01:21+08:00：记录第十一次三作业联合检查，以及旧版 Find_0 的新验证结果与 checkpoint 状态。

Revision note 2026-07-27 06:20+08:00：记录第十二次三作业联合检查，以及新版 `unet_c1` 的新验证结果与 checkpoint 状态。

Revision note 2026-07-27 11:20+08:00：记录第十三次三作业联合检查、新版 Find_1 与旧版 Find_0 的新验证结果，以及三项训练当前不同的 `BEST.ckpt` 刷新状态。
