# Find_0 推理、校准评估与 F1 居中产物实施

本 ExecPlan 是持续更新的执行记录。实施期间必须同步维护 `Progress`、`Surprises & Discoveries`、`Decision Log` 和 `Outcomes & Retrospective`。本文遵守仓库根目录 `AGENTS.md` 的项目入口规则；仓库没有另设 `PLANS.md`。

## Purpose / Big Picture

本任务要把已经完成训练的 Find_0 检查点接入 Pocket_Plus 现有 Stage1 推理管线。完成当前获准范围后，项目将具备以下可观察能力：

1. 使用指定 Find_0 检查点在 calibration 数据划分上生成完整图配体概率，冻结 `t_F1` 等校准阈值，并输出语义评估与实例评估。
2. 只生成 calibration、validation 和 train 的 `probability`、`components` 与 `F1_centered`，不必等待 `CLG_centered`。
3. 以后在同一产物根目录执行现有 `*-f1-clg` 命令时，已经完成的前三类产物保持不变，只补充 `CLG_centered`。
4. 人类可以从 `Pocket_Plus/训练与运行/sh/infer/` 直接阅读每个正式阶段的输入、参数、GPU 批量、分片和输出位置。

calibration 概率图、阈值冻结、calibration F1 与 validation F1 已经完成。Codex 在本阶段担任第二负责人：持续记录运行身份与产物位置，联合监视 Job 335116 的 train 0/50 与 Job 335493 的 train 1/50，并验收每个里程碑；已经完成的 Job 335115 validation allocation 保持 `try_lock` 与 `after_lock`，不重复执行。`min_voxels` 已直接冻结为 10，不再执行候选值比较。独立 Gauss scorer 的设计与实施见 `文档/exec_plan/Find_0高斯联合打分实施.md`；该支线不阻塞本计划的 GPU 主线。

## Progress

- [x] (2026-08-03 03:05+08:00) 通过 `grill_with_memory/08-02-18-07.md` 冻结任务目标、模型身份、产物根目录、阈值参数、分片方式、smoke 范围和正式提交门槛。
- [x] (2026-08-03 03:20+08:00) 核验 Pocket_Plus `Learn/CUMULATIVE@ad4dde8` 是所有本地与远端引用中按提交者时间形成的唯一最新提交；当前及登记工作树均无未提交修改。
- [x] (2026-08-03 03:25+08:00) 为 AdaLigand 记录建立独立 `Learn/CUMULATIVE` 工作树，避免碰触主目录中正在进行的 matcher 任务。
- [x] (2026-08-03 04:20+08:00) 完成 Pocket_Plus 推理入口、运行器、产物契约 README 与任务提交器的逐文件审查。
- [x] (2026-08-03 04:31+08:00) 在实现分支保存最小实现：延迟唯一的 Dataset 导入、提高缓存上限，并增加三个 F1-only 命令。
- [x] (2026-08-03 04:36+08:00) Windows 推理与产物测试 41 项通过，组件、阈值与评估测试 32 项通过；完整测试 390 项通过、3 项基线配置测试失败。
- [x] (2026-08-06) 完成下一版 Fα-centered 与独立 Li-centered，实现 `_BLOB_EXCEED` 生产/评估双开关；推理、产物与评估相关 64 项回归通过。真实实现端点为 Pocket_Plus `5b014d6`，推理学习端点为 `d54ec20`，最终 `Learn/CUMULATIVE@0976f64` 与实现端 tree 同为 `a8157b3a084770fcc615b0a8035c82be15167fed`。本轮代码未部署到当前冻结作业。
- [x] (2026-08-03) 使用真实 Find_0 检查点完成隔离 smoke，验证概率图、阈值冻结、F1 居中、CLG 补跑、完成标记与续跑。
- [x] (2026-08-03) 在 `Pocket_Plus/训练与运行/sh/infer/` 建立分阶段正式入口；实现端点与学习端点完成等价核验并推进到 `Learn/CUMULATIVE@e76e3fb`。
- [x] (2026-08-03) Job 334909 生成三份公共 PDB 清单：calibration 100 项、validation 200 项、train 13714 项；用户随后取消已经完成且因 `after_hold` 保留的作业。
- [x] (2026-08-03 15:39+08:00) 用户提交 A100 数组 Job 334936。两个分片均因 `Priority` 排队，尚未创建 release、launch、日志或正式产物；Slurm 当时估算开始时间为 2026-08-05 13:23:57。
- [x] (2026-08-03) 把现有 Stage1 heartbeat 扩展为联合监控：334936 每 30 分钟由只读 subagent 检查；既有训练仍按 5 小时节奏检查。只有实质阻断或概率图全部完成才向用户汇报。
- [x] (2026-08-03) 用户取消短暂运行的 A100 Job 334936，改用 `a800` 资源与通用 `cpu96` QOS 提交数组 Job 335115。旧任务可能留下无完成标记的部分目录，但合法 `_COMPLETE` 产物继续复用。
- [x] (2026-08-03 17:10+08:00) 查明 A800 两个真实数组元素：分片 0 是 Job 335116，分片 1 是 Job 335115；两者均在 `gnode10` 运行并使用同一冻结 release `Pocket_Plus_05c8e4d8216d`。实际命令使用 `window_batch_size=10` 与 100 GiB 缓存上限。
- [x] (2026-08-03 17:12+08:00) 代码与 owner 记录确认 `_RUNNING` 是 PDB 级租约，准确路径为 `calibration/<pdb_id>/_RUNNING`。当时已有 9 个完整概率图；`6w2t` 与 `7bl6` 分别由两个 A800 进程持有活跃租约，`28um` 由已经取消的旧 A100 进程 `gnode07:75525` 留下陈旧租约。第一轮仍在运行，因此不执行清理。
- [x] (2026-08-03) 用户授权在两个数组元素第一次执行都结束且分别进入 `try_lock` 后，按严格前置条件清理陈旧 `calibration/<pdb_id>/_RUNNING`；只有确有缺失 PDB 时才删除两个实际数组元素的 `try_lock` 原样续跑一次。禁止自动第三次运行，`after_lock` 始终保留。
- [x] (2026-08-03) Heartbeat 已从旧任务移到当前任务 `019fc1b6-6900-7412-9580-51b0a2fc3b20`。每次由只读 subagent 汇总证据，任何 bug 由主 agent 修复。
- [x] (2026-08-03 19:45+08:00) 用户与另一任务修复统一 SSH 入口后，主 agent 恢复服务器只读访问；两个 A800 分片均健康运行，完整概率图增至 35，错误扫描为空。Heartbeat 按用户要求从 30 分钟改为 2 小时。
- [x] (2026-08-04 01:39+08:00) 分片 0 的 Job 335116 已成功结束第一次推理并进入 `try_lock`；分片 1 的 Job 335115 仍在处理 `9k3b`。100 项中已有 94 项写入 probability `_COMPLETE`，尚缺 `28um`、`9k3b`、`9mbz`、`9r66`、`9rwp`、`9wmu`；当前没有 OOM 或异常栈，因此继续只读等待分片 1 结束，不清理租约或锁。
- [x] (2026-08-04 02:22+08:00) 重新启用当前任务 heartbeat，周期为 2 小时；删除“每次自动派 subagent”的旧要求，只允许在正式提交、恢复操作或最终验收前节制地进行一次独立只读复核。此时已有 96/100 项 probability `_COMPLETE`，缺少 `28um`、`9r66`、`9rwp`、`9wmu`；Job 335115 正在处理 `9r66`，GPU 利用率 100%，没有 OOM 或异常栈。
- [x] (2026-08-04) 用户直接冻结 `min_voxels=10`，要求 calibration、validation、train 的正式阈值、组件和 F1-centered 统一复用该值；取消此前临时候选比较。Pocket_Plus 人类入口 `Find_0_freeze_thresholds.sh`、清单准备说明和推理入口 README 已作对应小改，三个用户修改的 F1 脚本没有重新声明该参数，因此未改动。
- [x] (2026-08-04 02:55+08:00) 下一版评估实现最小修复 `_BLOB_EXCEED` 契约：阈值扫描仍使用完整 calibration 集合；冻结 `t_F1` 后，组件数超过 200 的 PDB 从平均精确率、Dice、实例与 top-K 指标中完全排除，并新增实际评估数。专项回归通过；该修复必须在正式阈值冻结前进入所用 release，不影响当前概率图作业。
- [x] (2026-08-04 02:55+08:00) calibration probability 完成 97/100，尚缺 `28um`、`9rwp`、`9wmu`；Job 335115 正在处理 `9rwp`，当前无错误，继续等待第二个分片首轮结束。
- [x] (2026-08-04 04:27+08:00) 两个 A800 分片均成功结束首轮并进入各自 `try_lock`。独立只读复核确认仅缺 `28um`，且唯一 `_RUNNING` 恰为旧 A100 `gnode07:75525` 留下、目录内只有 `owner.json`。按授权精准删除该文件与空租约目录，再删除 Job 335116、335115 的两个 `try_lock`；两个 `after_lock` 保留，正式命令已原样进入第二轮。分片 1 已跳过全部完整产物并再次进入 `try_lock`，分片 0 正在以新 owner `gnode10:6115` 补算 `28um`。
- [x] (2026-08-04 06:28+08:00) Job 335115 的两个 A800 分片完成 100 项 calibration 概率图并通过最终验收。独立只读复核确认两轮 release、launch、参数、日志、锁和完成集合正确；临时 CPU Job 335494 在 43 秒内深读全部 100 份 NPZ，验证精确字段、`float32` 三维有限 `[0,1]`、几何一致性、50+50 分片覆盖和零租约/零临时文件。验收结果保存在 `/home/penghongen/My_Project/tmp/find0_calibration_recover_335115/final_acceptance/acceptance.json`。
- [x] (2026-08-04 07:29+08:00) 正式阈值冻结 Job 335495 成功并进入 `try_lock`。主 agent 与独立只读复核均确认 release `Pocket_Plus_c65e77b0b031`、launch `Find_0_freeze_thresholds_job335495_20260804T070920_a1`、日志和四项正式产物正确。冻结值为 `t_F1=0.9962158203125`、`min_voxels=10`、`max_voxels=2046`、`denominator=32768`；100 个 PDB 中 86 个进入拟合评估，14 个按 `_BLOB_EXCEED` 契约排除。
- [ ] (2026-08-04 07:38+08:00) 已复用 Job 335115 与 335116 保留的两张 A800 启动 F1 主线：335115 顺序运行 calibration F1 后运行 validation F1；335116 运行用户冻结的 train 全局分片 0/50。两者实际 attempt a3 使用 release `Pocket_Plus_c65e77b0b031`，初始租约、组件推进和错误扫描正常。
- [ ] (2026-08-04 08:01+08:00) F1 启动后的第 1 次健康检查通过：calibration 已完成 20 份 components 与 19 份 F1-centered，另有 6 个 PDB 按 `_BLOB_EXCEED` 契约停止；train 0/50 分片已完成 3 份 probability、components 与 F1-centered。两项当前租约分别绑定 Job 335115/335116 的活跃 owner，锁与错误扫描正常，validation 尚未启动。
- [ ] (2026-08-04 08:31+08:00) 第 2 次 F1 健康检查通过：calibration 推进到 components 42、F1-centered 41、`_BLOB_EXCEED` 7；train 0/50 推进到 probability 4、components/F1-centered 各 3、`_BLOB_EXCEED` 1。两个 owner PID 未变，当前租约继续向后推进，锁与错误扫描正常。
- [ ] (2026-08-04 09:01+08:00) 第 3 次 F1 健康检查通过：calibration 推进到 components 73、F1-centered 72、`_BLOB_EXCEED` 10；train 0/50 推进到 probability 5、components/F1-centered 各 4、`_BLOB_EXCEED` 1。两个 owner PID、release、动态命令与锁身份不变，错误扫描为空。
- [x] (2026-08-04 09:33+08:00) calibration F1 最终验收通过并按顺序进入 validation。100 项清单精确分成 86 份 components/F1-centered 完成产物和 14 份 `_BLOB_EXCEED`，两组互斥且无 `_RUNNING`。独立只读复核完整读取 86 份 forest 与 F1 NPZ，确认冻结阈值身份、来源节点、offset、概率范围和两份合法零候选产物均符合契约；Job 335115 已由同一 attempt a3 启动 validation，Job 335116 的 train 0/50 继续运行，正式日志无 OOM 或未处理异常。
- [x] (2026-08-04 12:35+08:00) 独立 Gauss calibration 回填 Job 335572 已 `COMPLETED 0:0` 并验收 86/14 集合；validation 与 train GPU 主线继续健康推进到 F1-centered 各 9 份和 4 份，train 另有 2 份 `_BLOB_EXCEED`。CPU 回填入口已最小调整为可在 GPU 运行期间跳过未完成或被占用的 PDB，并在以后重复执行相同分片时增量补齐。
- [x] (2026-08-06 03:45+08:00) 按用户授权复用 Job 335493 保留的单张 A800 启动 train 全局分片 1/50。主 agent 通过精确 `kill_lock_335493` 结束原 Matcher v2 attempt 6，等待 runner 创建 `try_lock_335493` 后原子替换动态命令，并只删除该 `try_lock` 激活 attempt a7；`after_lock_335493` 始终保留，没有 `scancel`。新命令显式绑定已验收 release `Pocket_Plus_c65e77b0b031`，继续使用同一 Find_0 checkpoint、阈值、批量和 50 分片契约。03:57 已完成首个 PDB `10ay` 的 probability、components 与 F1-centered，进程推进到 `11ta`；A800 占用约 79.2/81.9 GiB，错误日志为空。
- [x] (2026-08-06) 在隔离实现工作树完成下一版推理灵活化：新增 `continue_on_blob_exceed` 与 `evaluate_on_blob_exceed` 两个独立开关；添油式生成七个既有冻结 Fα 阈值对应的 centered 文件；新增从主线 probability 读取、向独立根目录发布 `Li_centered.npz` 的 Li 变体。calibration 正式新脚本才开启继续生产，validation/train 保持历史停止行为；正式评估脚本始终纳入已有超限产物。该实现尚未同步到正在运行的冻结 release。
- [x] (2026-08-06 20:25+08:00) Job 335115 attempt a3 成功完成 validation F1 并进入 `try_lock_335115`。200 项清单精确分成 183 份 probability/components/F1-centered 完成产物与 17 份仅有 probability 完成标记的根级 `_BLOB_EXCEED`，两组互斥合计 200；目录无 `_RUNNING`，allocation 输出明确记录第 3 次执行成功，错误扫描为空。release 继续为 `Pocket_Plus_c65e77b0b031`，`after_lock_335115` 保留且未重复执行。
- [x] (2026-08-07 11:19+08:00) 用户要求单卡任务完成并通过验收后释放相应资源。主 agent 重新确认 Job 335115 的 `try_lock` 存在、validation 进程不存在且 A800 空闲后，只删除 `/home/penghongen/Feedback/Pocket_Plus/allocations/335115/after_lock_335115`。四锁执行器随后正常退出，Slurm 最终状态为 `COMPLETED 0:0`，`try_lock` 由执行器清理；validation 正式产物、release、launch 和日志均未改动。Job 335116 与 Job 335493 继续运行各自 train 分片，未被本次释放影响。
- [ ] 完成并验收 train 的 F1 居中产物；当前并行覆盖 0/50 与 1/50 两个互斥分片，其余 48 个分片等待后续可用显卡安排。
- [ ] 回填本文、映射、检查记录和 CLAUDE memory，记录所有正式产物地址与尚未实施的 CLG/Selector 支线。

## Surprises & Discoveries

- Observation: `src/inference/cli.py` 在恢复 checkpoint 之前导入 `src.inference.runner`，而 `runner.py` 顶层又导入 `src.datasets.stage1_requests`。严格快照激活随后会发现 `src.datasets` 已经从当前工作区加载并拒绝继续。
  Evidence: `src/inference/runner.py` 顶层导入 `centered_start_from_centroid_zyx`；`src/inference/checkpoint.py::_activate_checkpoint_source` 明确拒绝已经导入的 `src.datasets`。

- Observation: 命令行的 `--cache-max-bytes` 默认值是 512 MiB，而 `Stage1RuntimeAssembly` 自身默认值约 5 GiB；命令行始终覆盖后者。
  Evidence: `src/inference/cli.py::_add_runtime_arguments` 与 `src/inference/assembly.py::Stage1RuntimeAssembly.__init__` 的默认值不同。

- Observation: 现有运行器已经按产物角色检查 `_COMPLETE`，因此 F1-only 不需要新的磁盘状态或新生产算法。
  Evidence: `Stage1ProductionRunner.run_task` 逐个跳过已经完成的角色；F1 与 CLG 已由 `make_f1_clg_centered_role_producers` 作为两个独立回调注册。

- Observation: 当前 Pocket_Plus 分支没有 `.project-root`，完整测试若不临时补入该空标记，会在导入 `src/train.py` 时停止收集；临时补入后完整测试只剩三项既有 CPC v3 配置测试失败，因为该分支没有 `configs/experiment/CPC1/trunk_*` 文件。
  Evidence: 临时根标记下的完整结果为 `390 passed, 3 failed`；三项失败均来自 `tests/test_cpc_v3_configs.py`，本轮没有修改训练入口或 CPC 配置。

- Observation: 2026-08-03 第一次服务器 smoke 前探测时，`10.102.33.220:10022` 的 SSH 与 TCP 连接均超时，尚未发生服务器写入或 Slurm 提交。
  Evidence: 项目 SSH helper 在建立连接时超时；随后 20 秒 TCP 探测也没有建立连接。

- Observation: Job 334936 使用新的完整任务模式，只有数组元素真正获得资源并开始执行时才冻结 release。因此排队期间没有 allocation 目录、launch、日志或锁是正常状态，验收必须以实际执行时生成的 release 和 launch 为准。
  Evidence: 2026-08-03 15:39+08:00，`334936_0` 与 `334936_1` 均为 `PENDING (Priority)`；正式 calibration 产物根目录尚不存在。

- Observation: Job 335115 的父数组编号不能直接代表两个实际数组元素。Slurm 把分片 1 记录为数字 Job 335115，把分片 0 记录为数字 Job 335116；锁和 allocation 操作必须分别使用这两个数字目录。
  Evidence: `scontrol show job 335115_0` 返回 `JobId=335116, ArrayTaskId=0`；`335115_1` 返回 `JobId=335115, ArrayTaskId=1`。

- Observation: 完整任务运行器把 `try_lock_<job_id>` 写在 `/home/penghongen/Feedback/Pocket_Plus/allocations/` 根目录，而 `after_lock_<job_id>` 与 `run_cmd_<job_id>.sh` 位于 `allocations/<job_id>/` 内。恢复时必须按实际落盘位置核对，不能只扫描数字 Job 子目录。
  Evidence: Job 335116 的标准输出明确记录已创建 `/home/penghongen/Feedback/Pocket_Plus/allocations/try_lock_335116`；对应子目录内只有 `after_lock_335116` 和 `run_cmd_335116.sh`。

- Observation: A800 正式 release 的实际批量是 10，不是排队前本地脚本曾显示的 6，也不是旧 manifest 中的 A800 批量 8。运行身份必须以 release、launch 和进程命令为准。
  Evidence: 两个 Python 进程均带 `--window-batch-size 10`；分片 0 与分片 1 共用 release `Pocket_Plus_05c8e4d8216d`。

- Observation: calibration 概率图与语义阈值 `t_F1` 不依赖 `min_voxels`；`min_voxels` 只改变通过体素数下限的连通组件，因而影响实例评估与后续 F1/CLG 居中产物。当前实现要求 `min_voxels > 0`，所以“完全不设下限”的合法近似值是 1，不是 0。
  Evidence: 阈值扫描先由完整图概率确定 `t_F1`；组件筛选和实例指标才读取 `min_voxels`，命令行参数校验拒绝 0。

## Decision Log

- Decision: 只把 `src.datasets.stage1_requests` 的导入延迟到真实使用位置，不改变快照校验范围。
  Rationale: 这是解除错误导入顺序所需的最小修复，并继续保证模型、Dataset、wrapper、损失与工具只来自一套训练快照。
  Date/Author: 2026-08-03 / 用户与 Codex

- Decision: 当前正式脚本把单进程 Dataset 缓存上限设为 100 GiB；该值只是允许上限，不预先分配内存。
  Rationale: 100 GiB 已远高于旧 512 MiB/5 GiB 上限，并与 Job 334936 实际待冻结脚本一致；后续只在真实读盘成为瓶颈时再调整。
  Date/Author: 2026-08-03 / 用户

- Decision: 新增 calibration、validation 和 train 三个 F1-only 子命令；旧 `*-f1-clg` 命令保留，未来在同一输出根目录补齐 CLG。
  Rationale: 当前主线优先得到 F1-centered，又不能破坏后续 CLG 能力。
  Date/Author: 2026-08-03 / 用户与 Codex

- Decision: 正式 Stage1 推理统一使用 `min_voxels=10`、`max_voxels=2046`、`denominator=32768`，不再执行 `min_voxels` 临时候选比较。
  Rationale: 用户要求在没有明确反证时直接采用 10，并让 calibration 冻结值经 `thresholds.json` 统一约束 calibration、validation 和 train 的组件及 F1-centered 生产，以减少额外分支和时间消耗。
  Date/Author: 2026-08-04 / 用户

- Decision: 正式推理根目录固定为 `/storage/penghongen/AdaLigand_stage1_inference/Find_0-CPC1-ligand_PRAUC_0.675477/`，`artifacts/` 作为推理输出根目录；公共划分清单位于其上一级推理根目录并供不同模型复用。
  Rationale: 同一检查点和契约的分批运行、失败重试与不同 GPU 类型可以安全汇入同一身份目录，同时不重复复制已经过滤的 PDB 清单。
  Date/Author: 2026-08-03 / 用户

- Decision: 正式脚本名称不绑定 GPU 类型；GPU 类型、卡数与数组编号由 `submit_task.sh` 的提交命令决定。Job 334936 使用两项 A100 数组，脚本内部每项处理一个 calibration 分片。
  Rationale: 可用卡会变化，同一份可读脚本配合显式提交参数比按卡型复制脚本更易维护，也允许不同卡型共同完成互斥分片。
  Date/Author: 2026-08-03 / 用户

- Decision: Gauss scorer 是消费既有 `F1_centered.npz` 的独立降级打分支线，不修改 `candidate_eligible`，也不限制 CLG 或 Selector 的有效节点与候选集合。
  Rationale: Gauss 只为 forest 的 `t_F1` 合格节点增加独立得分和布尔选择结果，完整图概率、阈值、F1-centered、CLG 和 Selector 仍遵守原有契约。
  Date/Author: 2026-08-04 / 用户与 Codex

- Decision: 旧 A100 Job 334936 的合法 `_COMPLETE` 概率图保留并由 A800 Job 335115 跳过；部分目录或无完成标记文件不被视为完成。第一轮运行结束前不清理任何租约。
  Rationale: GPU 类型差异不构成阻断；真正风险是强制取消留下的陈旧租约或不完整发布。等待两个当前生产者全部停止后再判断，可以避免误删活跃租约。
  Date/Author: 2026-08-03 / 用户与 Codex

- Decision: 陈旧租约的唯一允许清理目标是 `calibration/<pdb_id>/_RUNNING`。只有目录内恰好只有 `owner.json` 时，才删除该文件并用 `rmdir` 删除空目录；禁止递归删除。
  Rationale: 该操作足以解除已经证明无主的租约，同时不会碰触概率图、几何信息、完成标记或其他状态。
  Date/Author: 2026-08-03 / 用户与 Codex

- Decision: train 分片 1/50 复用 Job 335493 已保留的 A800；本地只增加一个固定 `shard_index=1` 的人类入口，不修改通用推理代码或原有 F1 脚本。
  Rationale: 50 分片本来就允许不同资源分批执行。显式绑定既有冻结 release，可以保证分片 0 与分片 1 使用相同代码、模型、checkpoint、阈值和产物契约，同时把本轮改动限制在一个易读脚本与运行记忆内。
  Date/Author: 2026-08-06 / 用户与 Codex

- Decision: Fα 只为现有 forest 阈值层增加同构 centered 文件；Li 使用独立根目录，只落盘 `Li_centered.npz`，不落盘 forest、CLG 或 Selector 输入。
  Rationale: 两种扩展都不能改动历史 F1/CLG/Selector 契约。Fα 可直接复用 calibration 已冻结的七层，Li 则保留同构的 centered 数值表而与主线 Stage2/3 消费路径隔离。
  Date/Author: 2026-08-06 / 用户与 Codex

- Decision: `_BLOB_EXCEED` 的生产继续开关与评估纳入开关相互独立。正式新 calibration 生产开启前者，validation/train 关闭；正式评估总是开启后者。
  Rationale: 超限标记继续记录工程风险，但不再替代“是否有产物”和“是否进入指标”两个独立事实。
  Date/Author: 2026-08-06 / 用户与 Codex

## Outcomes & Retrospective

最小实现、本地回归、服务器 smoke、正式入口和既有推理实现的 Git 双线已经完成。公共 PDB 清单已经生成；旧 A100 Job 334936 已取消。A800 数组 Job 335115 在一次精准租约恢复后完成全部 100 项 calibration 概率图，2026-08-04 06:28 已通过独立只读复核与临时 CPU Job 335494 的全量深验收。正式阈值冻结 Job 335495 随后从包含 `_BLOB_EXCEED` 排除修复与 `min_voxels=10` 的 release `Pocket_Plus_c65e77b0b031` 成功生成并验收阈值、扫描、指标和完成标记。Job 335115/335116 的两张保留 A800 已在独立边界复核后原位切换到 F1 主线；其中 Job 335115 于 2026-08-06 20:25 完成 validation 的 200 项集合，183 份完整 F1 产物与 17 份 `_BLOB_EXCEED` 构成无遗漏终态，并在 2026-08-07 11:19 按用户要求通过删除自身 `after_lock` 正常释放 A800。Job 335116 继续执行 train 0/50；2026-08-06 又按用户授权复用 Job 335493 的保留 A800，以同一 release 和 checkpoint 启动 train 1/50。当前仍只覆盖 train 的两个分片，不能视为 train 全量完成。

## Context and Orientation

AdaLigand 保存科学契约、运行决策与执行记录，Pocket_Plus 保存实际推理代码和任务入口。关键文件如下：

- `AdaLigand/文档/讨论/BOX-level数据契约.md`：完整图、组件、F1/CLG/Selected 居中产物的字段、形状、编号和完成标记契约。
- `AdaLigand/grill_with_memory/08-02-18-07.md`：本任务已经确认的全部边界。
- `Pocket_Plus/src/artifacts/readme.md`：Pocket_Plus 当前落盘产物契约。
- `Pocket_Plus/src/inference/README.md`：现有推理命令、依赖顺序、分片与续跑说明。
- `Pocket_Plus/src/inference/cli.py`：命令行子命令和运行器装配。
- `Pocket_Plus/src/inference/runner.py`：按 PDB 与产物角色续跑的编排器。
- `Pocket_Plus/src/inference/checkpoint.py`：严格选择训练源码快照并恢复完整模型包装器。
- `Pocket_Plus/训练与运行/submit_task.sh`：正式 Slurm 统一入口。

本轮模型身份固定如下：

- 模型来源：`Find_0`。
- 检查点文件：`TOP_epoch_00_score_0.2843.ckpt`。
- SHA-256：`87ec6080809a14e2558e10c0740c16371b363fed0f672081b389f46c64928b44`。
- 对应 validation 配体区域 PR-AUC：`0.6754766702651978`。
- 检查点所在训练目录：`/home/penghongen/My_Project/feedback_plus/logs/AdaLigand_Stage1-Find_0-CPC1/Find_0-CPC1____job321743_Find_0_CPC1_lr5e5_p2_val30_chunk2x_2gpu_m8_w1/`。
- 推理读取配置：上述训练目录中的 `config.yaml`。
- 冻结训练代码：`/home/penghongen/My_Project/tmp/adaligand_stage1_20260721T024000/allocations/321743/runtime/My_Project/Pocket_Plus/`。

PDB 清单由 `Pocket_Plus/src/datasets/ops` 的既有过滤结果生成。服务器公共清单为 `/storage/penghongen/AdaLigand_stage1_inference/calibration_pdb_ids.json`、`validation_pdb_ids.json` 和 `train_pdb_ids.json`；当前数量分别为 100、200 和 13714，实际推理直接读取这些有序、无重复清单。

“F1-centered”表示对完整图概率在校准阈值 `t_F1` 上形成的每个合格组件，解析一个合法的 `80×80×80` BOX，并在该 BOX 内重新执行完整模型。“CLG-centered”表示对同一个组件谱系组解析 BOX 并重新执行模型。本轮只正式生成前者。

## Plan of Work

第一至第四里程碑已经完成：审查并最小修复现有推理管线；完成 Windows 测试与真实检查点 smoke；建立通用的正式分阶段脚本；完成 Pocket_Plus 实现历史与学习历史的等价收口。

第五里程碑是 calibration 概率图生产，已经完成最终验收。当前 heartbeat 每 3 小时由主 agent 对 train 0/50 与 train 1/50 进行普通只读核对；Job 335115 的 validation allocation 已在验收后释放，不再纳入轮询。只在恢复操作、正式追加分片或最终验收前节制地派一次独立只读 subagent。以每个作业的 release、launch、最终脚本、日志与产物为准，不能把执行前服务器工作区内容当作冻结证据。

第六里程碑是在 100 项概率图完整验收后，直接以 `min_voxels=10` 冻结 calibration 阈值，生成正式语义与实例评估，并依次推进 calibration F1、validation F1 和 train F1。CLG 可以以后在同一目录续跑；Selector 不在本轮主线。Gauss scorer 在 calibration F1 完整后使用 CPU 独立调参，与仍在运行的 validation/train GPU 主线并行。

## Concrete Steps

在 `C:/Users/15919/Desktop/Pocket_Plus`：

1. 保持 Job 335115 的两个数组元素原样运行，不重复提交，不修改冻结 release、正式脚本或正式产物。
2. 每次监控同时核对 Job 335116（分片 0）与 Job 335115（分片 1）的 Slurm 状态、release、launch、锁、日志和 `_COMPLETE` 计数；正常推进不打扰用户。
3. 两个分片第一次执行均进入 `try_lock` 后，确认没有活跃生产者并分类完成集合、缺失集合和陈旧租约。若 100 项已完整则不续跑；若陈旧租约阻断未完成 PDB，则按授权精准清理并删除两个实际数组元素的 `try_lock` 原样续跑一次；没有租约但仍缺失时先诊断和报告。
4. 最终确认 calibration 的 100 个 PDB 恰好各有一份概率图、geometry 与 `_COMPLETE`，并检查无 OOM、traceback、重复归属、目录碰撞、残留 `_RUNNING` 或原子写入临时文件。
5. 确认服务器正式 `Find_0_freeze_thresholds.sh` 显式使用 `min_voxels=10`，通过项目任务系统提交一次 16 核 CPU 阈值冻结任务。
6. 验收 `thresholds.json`、`threshold_scan.npz`、`metrics.json` 和 calibration `_COMPLETE`，确认冻结文件中的 `min_voxels` 精确为 10。
7. 按用户冻结的人类入口提交 calibration F1 与 train F1；calibration 完成后在同一资源安排中运行 validation F1。只有真实 OOM、参数无效或其他硬错误才修改这三个脚本。

正式生产顺序是：calibration probability 全部分片完成；以 `min_voxels=10` 冻结正式阈值；运行 calibration F1 与 train F1；calibration F1 完成并验收后运行 validation F1。Gauss CPU 支线从 calibration F1 完成后开始，但不阻塞 validation/train。

## Validation and Acceptance

代码验收必须证明：

- 仅导入 `src.inference.cli` 不会提前导入 `src.datasets`，真实检查点快照可以随后激活。
- 三个 F1-only 命令的角色顺序分别是 `components,F1_centered` 或 `probability,components,F1_centered`。
- F1-only 完成后执行旧 `*-f1-clg`，已有文件内容和完成标记不变，只新增 CLG；再次运行返回跳过。
- 正式脚本显式传入 100 GiB 缓存上限；实际进程不会因此预先分配 100 GiB。
- 真异常非零退出，当前进程创建的 `_RUNNING` 被清理，未完成角色不出现 `_COMPLETE`。
- 真实 Find_0 权重严格完整加载，代表性 probability、components 和 F1-centered 满足两份产物契约；Find 的受体体素概率为零。
- 正式脚本不引用 smoke 目录，且分片、模型、配置、数据、输出和批量参数可独立读懂。

用户已授权从概率图恢复与验收继续执行到正式阈值冻结和三个 F1 数据划分。正式阈值文件必须记录 `min_voxels=10`。三个 F1 脚本的分片和批量视为用户冻结输入，除非运行出现真实硬错误，否则不得修改。

## Idempotence and Recovery

所有 PDB 级命令复用现有 `_COMPLETE`：同一身份再次运行会跳过已经完成的角色。真正异常不会被改写成“跳过”或 `_BLOB_EXCEED`；修复后重跑同一分片即可继续。当前进程持有的 `_RUNNING` 会由上下文管理器在异常传播时释放；遇到历史残留租约时只人工确认进程已经退出，再删除那一个目录。

smoke 与候选参数比较都使用隔离临时根目录，不覆盖正式 A—G 数据、旧训练目录、检查点或正式推理根目录。正式推理根目录采用固定检查点身份，可跨 Job 和不同 GPU 类型续跑。候选比较失败时只重跑对应临时任务；Job 334936 的概率图不受影响。

## Artifacts and Notes

实施期间把以下证据写入 `AdaLigand/talk/Find_0推理与评估检查记录.md`：

- 本地与服务器代码版本；
- 检查点、配置和三份冻结清单的路径与 SHA-256；
- 快照源码与当前源码的必要差异；
- 每条 smoke 命令、卡型、批量、峰值显存、运行结果；
- 代表性产物字段、形状、范围和完成标记；
- 正式脚本清单及尚未执行的提交命令。

## Interfaces and Dependencies

最终必须保留 `python -m src.inference.cli` 作为唯一 Python 命令入口。新增子命令建议为：

- `cal-produce-f1`
- `val-produce-prob-f1`
- `train-produce-prob-f1`

`Stage1ProductionRunner` 可以增加与现有 `run_*_f1_clg` 对称的薄方法，或由命令行直接调用现有 `run_task`；优先选择测试最清楚、代码最少的形式。不得新增通用阶段框架、自动分片器、兼容层、检查点包或 Selector 入口。

Python 依赖继续使用现有 PyTorch、Hydra、NumPy 和项目内部模块。Slurm 继续使用 `训练与运行/submit_task.sh`、`sbatch/task.sbatch` 和四锁执行器，不复制第二套提交系统。

Revision note (2026-08-03): 初次建立。根据 `grill_with_memory/08-02-18-07.md` 固定初始实施边界。

Revision note (2026-08-03): 根据已经完成的 smoke、通用脚本改名、公共 PDB 清单、用户提交的 Job 334936 与第二负责人职责重写当前里程碑；正式 `min_voxels` 仍为 15，临时候选比较尚未执行。

Revision note (2026-08-04): 用户授权继续端到端执行，并直接把 `min_voxels` 冻结为 10；删除临时候选比较，增加独立且不阻塞主线的 Gauss scorer 计划链接，并更新 heartbeat 与 subagent 边界。

Revision note (2026-08-04): calibration F1 的 86 份完成产物与 14 份 `_BLOB_EXCEED` 已完成独立最终验收，Job 335115 已进入 validation；Gauss CPU 参数搜索由“等待 calibration F1”转入提交前准备。

Revision note (2026-08-04): 10:01 的第 5 次 F1 健康检查通过；validation 已完成 probability、components 与 F1-centered 各 4 份，train 0/50 保持 probability 5、components/F1-centered 各 4 份与 1 份 `_BLOB_EXCEED`，两项活跃租约和错误扫描正常。普通监控间隔因此恢复为每 2 小时。独立 Gauss 参数搜索已经作为 CPU 数组 Job 335529 启动，不阻塞两项 GPU 主线。

Revision note (2026-08-06): 用户授权把 Job 335493 的保留 A800 从已经停止的 Matcher v2 attempt 6 精确切换到 Find_0 train 分片 1/50。本地仅增加 `Find_0_train_F1_shard_01.sh`，服务器 attempt a7 显式绑定 `Pocket_Plus_c65e77b0b031`；原 train 0/50 和 validation 作业不变，heartbeat 继续每 3 小时联合监控三个 GPU 作业。

Revision note (2026-08-06): 下一版实现把 F1-centered 泛化为不重建 forest 的七个 Fα-centered 添油式角色，并建立独立 Li-centered 根目录；同时把 `_BLOB_EXCEED` 的继续生产与评估纳入拆成两个显式开关。实现只位于隔离工作树，现有服务器运行及其冻结 release 不受影响。

Revision note (2026-08-06): Job 335115 attempt a3 已完成 validation。200 项清单由 183 份完整 probability/components/F1-centered 产物与 17 份根级 `_BLOB_EXCEED` 构成，目录无活跃租约或错误；后续 heartbeat 不再把 validation 记为运行中，只监控 train 0/50 与 1/50，并保留 Job 335115 的 `try_lock` 与 `after_lock`。

Revision note (2026-08-07): 用户明确要求已经完成并通过验收的单卡任务释放相应资源。主 agent 通过删除 Job 335115 自身的 `after_lock` 正常结束 allocation，Slurm 最终为 `COMPLETED 0:0`；heartbeat 继续只监控 Job 335116 与 Job 335493 的两个 train 分片，并在任一分片最终验收通过后按同一原则释放对应单卡资源。

Revision note (2026-08-09): train 全局分片 0/50 与 1/50 均完成最终验收并释放各自 A800。Job 335116 的 275 项由 246 份完整 probability/components/F1-centered 产物与 29 份合法 `_BLOB_EXCEED` 构成；Job 335493 的 275 项由 247 份完整产物与 28 份合法 `_BLOB_EXCEED` 构成。两个集合均无缺失、冲突、活跃租约或原子临时文件。主 agent 分别只删除对应 `after_lock`，两个数字 Job 最终均为 `COMPLETED 0:0`。当前只完成 train 清单的 2/50，后续分片与 validation/train Gauss 增量回填均等待用户重新安排资源。
