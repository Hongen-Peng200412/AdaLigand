# Find_0 推理与评估检查记录

本文只记录 Find_0 正式推理的可追溯事实、产物位置、运行身份和验收结果。实施计划与恢复边界见 `文档/exec_plan/Find_0推理与F1居中产物实施.md`。

## 固定输入与输出

- 模型检查点：`/home/penghongen/My_Project/feedback_plus/logs/AdaLigand_Stage1-Find_0-CPC1/Find_0-CPC1____job321743_Find_0_CPC1_lr5e5_p2_val30_chunk2x_2gpu_m8_w1/checkpoints/TOP_epoch_00_score_0.2843.ckpt`
- 推理配置：同一训练目录中的 `config.yaml`
- calibration 清单：`/storage/penghongen/AdaLigand_stage1_inference/calibration_pdb_ids.json`
- 正式 calibration 目录：`/storage/penghongen/AdaLigand_stage1_inference/Find_0-CPC1-ligand_PRAUC_0.675477/artifacts/Find_0/calibration`

## Job 334936：旧 A100 数组

用户提交两个 A100 分片后，两个元素曾短暂运行，随后由用户取消。取消前可能产生合法完成产物或部分目录。合法 `_COMPLETE` 产物保留；最终通过 calibration 清单与完成集合的严格比较证明没有 PDB 掉队。

## Job 335115：当前 A800 数组

- 提交资源：`a800`，`QOS=cpu96`，每个数组元素 1 张 GPU、8 个 CPU 核。
- 分片 0：真实数字 Job 335116。
- 分片 1：真实数字 Job 335115。
- 共同 release：`Pocket_Plus_05c8e4d8216d`。
- 分片 0 launch：`Find_0_calibration_probability_job335116_20260803T163413_a1`。
- 分片 1 launch：`Find_0_calibration_probability_job335115_20260803T163415_a1`。
- 实际批量：每次模型前向处理 10 个窗口。
- Dataset 缓存上限：每个进程 100 GiB；该值不是预先分配的内存。

### 2026-08-03 17:10+08:00

两个数组元素都在 `gnode10` 运行。17:12 时已有 9 个 PDB 同时写入概率图、几何信息和完成标记。PDB 级租约位于 `<pdb_id>/_RUNNING`：`6w2t` 与 `7bl6` 分别由两个当前 A800 进程持有；`28um` 的 owner 是旧 A100 节点 `gnode07` 上已经取消的进程。第一轮仍在运行，因此未清理任何租约。

分片 0 的一次显存采样约为 76.2/81.9 GiB；分片 1 约为 80.9/81.9 GiB。没有发现 OOM 或未处理异常。两个 allocation 当时只有 `after_lock`，尚未出现 `try_lock`；未执行任何恢复操作。

### 2026-08-03 19:45+08:00

服务器 SSH 入口恢复后，两个 A800 分片仍健康运行。完整概率图、概率数组和几何文件均为 35 份；`28um/_RUNNING` 仍是旧 A100 残留，另两个 `_RUNNING` 属于当前活跃进程。错误扫描为空，尚未出现 `try_lock`，未执行任何恢复操作。后续监控间隔由 30 分钟调整为 2 小时。

### 2026-08-04 01:39+08:00

分片 0 的 Job 335116 已成功结束第一次推理并创建 `/home/penghongen/Feedback/Pocket_Plus/allocations/try_lock_335116`。分片 1 的 Job 335115 仍在处理 `9k3b`，因此没有清理任何 `_RUNNING` 或锁。

100 项 calibration 清单中已有 94 项写入 probability `_COMPLETE`。尚缺 `28um`、`9k3b`、`9mbz`、`9r66`、`9rwp`、`9wmu`；其中 `28um/_RUNNING` 属于已取消的旧 A100 进程，`9k3b/_RUNNING` 属于当前 Job 335115 进程。当前日志没有 OOM 或未处理异常。

### 2026-08-04 02:22+08:00

分片 1 的 Job 335115 继续运行并处理 `9r66`。主进程 PID 46863 存在，GPU 利用率为 100%，进程显存约为 76.9/81.9 GiB；正式错误扫描为空。分片 0 的 Job 335116 仍由 `after_lock` 保留 allocation，并保持 `try_lock_335116`。

100 项 calibration 清单中已有 96 项 probability `_COMPLETE`；缺少 `28um`、`9r66`、`9rwp`、`9wmu`。`28um/_RUNNING` 仍属于已取消的旧 A100 进程，`9r66/_RUNNING` 属于当前 Job 335115。未发现无 `_COMPLETE` 的部分概率文件。由于分片 1 尚未结束，没有清理租约或锁。

用户随后直接冻结 `min_voxels=10`，取消临时候选比较。该值将由正式 `thresholds.json` 统一传递给 calibration、validation 和 train 的组件与 F1-centered 生产。三个 F1 脚本不重新声明该参数，因此保持用户现有分片、批量和资源设置；只把 `Find_0_freeze_thresholds.sh`、清单准备说明和推理入口 README 中的正式值改为 10。

当前任务 heartbeat 已按 2 小时周期重新启用。普通轮询由主 agent 只读执行，不再为每次 heartbeat 自动创建 subagent；只有正式脚本准备提交、恢复操作准备执行或最终验收时才进行一次独立只读复核。

### 2026-08-04 02:55+08:00

分片 1 继续健康处理 `9rwp`。100 项 calibration 清单已有 97 项 probability `_COMPLETE`；尚缺 `28um`、`9rwp`、`9wmu`。`28um/_RUNNING` 仍是已取消 A100 进程 `gnode07:75525` 的残留租约，`9rwp/_RUNNING` 由当前 A800 进程 `gnode10:46863` 持有。目录中没有原子写入临时文件，allocation 错误扫描为空。Job 335116 保持 `try_lock_335116`，Job 335115 尚未进入 `try_lock`，因此没有执行租约清理或续跑。

### 2026-08-04 04:27+08:00

两个 A800 数组元素均成功结束第一次执行并分别创建 `try_lock_335116`、`try_lock_335115`。此时正式集合完整 99/100，唯一缺失项是 `28um`；唯一 PDB 级租约是 `28um/_RUNNING`，目录内恰好只有 `owner.json`，owner 仍为已经取消的旧 A100 进程 `gnode07:75525`。独立只读复核同时确认两张 A800 空闲、当前无推理进程、旧 Job 334936/335103 已退出、日志无 OOM 或异常栈。

主 agent 按既有授权只删除 `28um/_RUNNING/owner.json` 并用 `rmdir` 删除空租约目录，随后删除两个实际数组元素位于 allocation 根目录的 `try_lock`；两个 `after_lock`、正式脚本、既有概率图和完成标记均未修改。恢复证据保存在 `/home/penghongen/My_Project/tmp/find0_calibration_recover_335115/recovery_20260804T042726.txt`。正式命令已原样进入第二轮：分片 1 跳过全部已完成样本并再次进入 `try_lock`，分片 0 为 `28um` 建立新租约，owner 为 `gnode10:6115`，正在补算唯一缺失概率图。

### 2026-08-04 06:28+08:00

第二轮完成后，Job 335115 与 Job 335116 均再次进入各自 `try_lock`，两个 `after_lock` 保留且没有 `kill_lock`。两张 A800 空闲，节点上没有概率图推理进程。第二轮 launch 分别为：

- Job 335115：`Find_0_calibration_probability_job335115_20260804T042658_a2`；
- Job 335116：`Find_0_calibration_probability_job335116_20260804T042658_a2`。

两轮四个 launch 均使用冻结 release `/home/penghongen/Feedback/Pocket_Plus/releases/Pocket_Plus_05c8e4d8216d/Pocket_Plus`，内容 SHA256 为 `05c8e4d8216d900802e1dd0f68567a465617846203bb54178d6732906d7a4e0a`；四份 `run_cmd.sh` 一致。独立只读复核确认 100 项清单有序无重复，完成集合与清单精确相等，每项三件套齐全且 `_COMPLETE.output_role=probability`，无 `_RUNNING`、临时文件、额外 PDB 或日志错误。

随后通过项目任务系统提交一次性 simple CPU16 验收 Job 335494。该作业在 `cnode01` 用时 43 秒并以 `COMPLETED 0:0` 退出，顺序或并行深读全部 100 份 `probability_map.npz`：字段集合精确为 `probability_map`、`origin_xyz`、`voxel_size_xyz`；概率图均为 `float32` 三维有限数组且范围在 `[0,1]`，几何 JSON 与 NPZ 一致；两个分片各覆盖 50 项。全体 NPZ 合计 `17,823,779,720` 字节，统一 `gaussian_sigma=0.5`、窗口 `80×80×80`、步长 `40×40×40`。正式验收证据为 `/home/penghongen/My_Project/tmp/find0_calibration_recover_335115/final_acceptance/acceptance.json`。calibration 概率图阶段至此完成。

代码审查同时确认，旧评估实现会把冻结 `t_F1` 后合格组件数超过 200 的 PDB 继续计入平均精确率、Dice、实例和 top-K 指标，这与正式消费契约不一致。下一版最小修复保持阈值扫描使用完整 calibration 集合，但在冻结 `t_F1` 后先构建组件，并在全部拟合评估指标前完全排除超限 PDB；报告新增 `n_evaluated_pdb`，同时保留 `n_total_pdb` 与 `n_blob_exceed_pdb`。该修复不改变正在运行的概率图作业。

### 2026-08-04 07:09+08:00

本地 Pocket_Plus 学习端点与服务器工作树已逐文件核对一致；服务器 `src/evaluation/calibration.py` 包含 `_BLOB_EXCEED` 拟合评估最小修复，正式阈值脚本显式使用 `min_voxels=10`、`max_voxels=2046` 和 `denominator=32768`。独立只读复核确认 100 项输入完整、正式阈值输出目录此前不存在碰撞且脚本语法有效。

正式阈值冻结通过项目任务系统提交为 CPU16 Job 335495，当前在 `cnode01` 运行。实际 release 为 `/home/penghongen/Feedback/Pocket_Plus/releases/Pocket_Plus_c65e77b0b031/Pocket_Plus`，内容 SHA-256 为 `c65e77b0b0315fc42216563211312213a7cf492852cdd6bb2d289373a1dac72f`；launch 为 `/home/penghongen/Feedback/Pocket_Plus/launches/335495/Find_0_freeze_thresholds_job335495_20260804T070920_a1`。07:12 的早期检查只有 `after_lock_335495`，没有 `try_lock`、`kill_lock`、输出文件或错误；这表示任务仍在读取并计算 100 份 calibration 概率图，尚不能验收。

### 2026-08-04 07:29+08:00

Job 335495 第一次执行成功并创建 `try_lock_335495`；`after_lock_335495` 保留，未出现 `kill_lock`。主 agent 与独立只读复核分别验收了四项正式产物：`thresholds.json`、`threshold_scan.npz`、`metrics.json` 和 calibration `_COMPLETE`。阈值身份为 Find_0，`t_F1=0.9962158203125`、`min_voxels=10`、`max_voxels=2046`、`denominator=32768`、26 连通；七个 $F_\alpha$ 阈值与 32769 点扫描全部有限且形状正确。拟合评估范围为 `calibration_fitted`，100 个 PDB 中 `n_evaluated_pdb=86`、`n_blob_exceed_pdb=14`，两者之和为 100。语义 micro Dice 为 `0.3897391307179645`，0.3 阈值下 coverage F1 与一对一 F1 分别为 `0.3386833315725744` 和 `0.3344174478668452`。日志无异常。

### 2026-08-04 07:38+08:00

独立只读复核确认 Job 335115/335116 均处于各自 `try_lock`、保留 `after_lock`、没有 `kill_lock` 或活跃推理进程；两张 A800 空闲。正式 calibration 已有 100/100 probability，尚无 components/F1，validation 与 train 正式目录均不存在，因此没有产物碰撞。三个用户冻结脚本在服务器的 SHA-256 分别为 calibration `0495ef6a6de7123fe75e6f62342472ef0e696aae62b1fe477942fe6689196323`、validation `904bccfe4589cee690da63915ff25897b649900da8625a41eb5f35b3fc9df687`、train `62909ad35aecdde8a54f7bcf4012e8742cd5c72c5d61df78ea1d7b066a8de41f`，语法与实际参数通过复核。

主 agent 在同目录临时文件中生成并检查新命令，随后原子替换两个动态 `run_cmd`，最后只删除对应的 `try_lock`。Job 335115 依次运行 calibration F1 与 validation F1；Job 335116 运行 train 的全局分片 0/50。旧命令、新命令和哈希证据保存在 `/home/penghongen/My_Project/tmp/find0_f1_reuse_335115_335116/activation_20260804T073854.txt` 及同目录副本中。两个 attempt a3 均复用 release `Pocket_Plus_c65e77b0b031`；launch 名称因原 allocation 身份仍带 `Find_0_calibration_probability`，但其中冻结的 `run_cmd.sh` 明确记录实际 F1 命令。初始检查已经出现 calibration 与 train 的合法 PDB 级 `_RUNNING`；calibration 开始生成 components，并按契约记录 `_BLOB_EXCEED`，未见 OOM 或异常栈。

### 2026-08-04 08:01+08:00

F1 启动后的第 1 次健康检查通过。Job 335115 已完成 20 份 calibration components、19 份 F1-centered，另有 6 个 PDB 因合格组件数超过上限而写入 `_BLOB_EXCEED`；当前处理 `7too`。Job 335116 的 train 全局分片 0/50 已完成 3 份 probability、components 和 F1-centered；当前处理 `3j6b`。两项 PDB 级租约的 owner 分别为 `gnode10:8655` 与 `gnode10:8656`，与 attempt a3 一致；两项均无 `try_lock` 或 `kill_lock`，各自 `after_lock` 保留。当前日志错误扫描为空，validation 按顺序尚未启动。

### 2026-08-04 08:31+08:00

第 2 次 F1 健康检查通过。Job 335115 的 calibration 已完成 42 份 components、41 份 F1-centered，`_BLOB_EXCEED` 为 7，当前处理 `8cue`。Job 335116 的 train 0/50 已完成 4 份 probability、3 份 components 和 F1-centered，另有 1 个 `_BLOB_EXCEED`，当前处理 `5a9z`。两个 owner 仍分别为 `gnode10:8655` 与 `gnode10:8656`，说明同一 attempt 正常连续推进；锁和正式日志错误扫描仍为空，validation 尚未启动。

### 2026-08-04 09:01+08:00

第 3 次 F1 健康检查通过。Job 335115 的 calibration 已完成 73 份 components、72 份 F1-centered，`_BLOB_EXCEED` 为 10，当前处理 `9gkl`。Job 335116 的 train 0/50 已完成 5 份 probability、4 份 components 和 F1-centered，`_BLOB_EXCEED` 仍为 1，当前处理 `5j8k`。两个 owner PID、release、动态命令和锁身份均未变化；当前正式日志错误扫描为空，validation 尚未启动。

### 2026-08-04 09:33+08:00

Job 335115 的 calibration F1 已完成并由同一 attempt a3 顺序进入 validation。calibration 的 100 项公共清单精确分成 86 份 components/F1-centered 完成产物与 14 份 `_BLOB_EXCEED`，两组互斥、合计 100，目录中没有 `_RUNNING`。14 份超限标记均满足 `N_F1_eligible > 200`，且没有错误地同时发布 components 或 F1-centered。

独立只读验收逐项读取 86 份 `forest.npz` 与 `F1_centered.npz`。84 份非空产物的字段、形状、offset 末端、forest 体素数、来源 tree/node、`t_F1` 网格位置 32644、`t_F1=0.9962158203125`、概率范围与有限性均通过；`8tu8` 和 `9jeq` 是合法零候选产物，forest 和 centered 文件均使用规范空数组与零 offset，不是失败。components 与 F1-centered 完成标记的 `output_role` 及 `min_voxels=10`、`max_voxels=2046`、`denominator=32768`、26 连通身份全部一致。

Job 335115 已运行 validation 的 `val-produce-prob-f1`，当前有效租约属于 `11co`，owner 为 `gnode10:21156`；Job 335116 的 train 0/50 继续处理 `5j8k`，owner 为 `gnode10:8656`。两个作业仍为 RUNNING、各自只保留 `after_lock`，没有 `try_lock` 或 `kill_lock`，allocation 日志没有 OOM、traceback、CUDA 错误或未处理异常。此时 validation 已完成首个 PDB 的 probability、components 与 F1-centered；train 0/50 为 probability 5、components/F1-centered 各 4、`_BLOB_EXCEED` 1。

## 待补充

- calibration、validation 和 train 的 F1 居中产物地址；
- 独立 Gauss scorer 的 calibration 参数搜索与 forest 回填结果，详细过程另记 `talk/Find_0高斯联合打分检查记录.md`。

### 2026-08-04 10:01+08:00

第 5 次 F1 健康检查通过。Job 335115 的 validation 已完成 probability、components 与 F1-centered 各 4 份，当前处理 `5lmq`，owner 为 `gnode10:21156`。Job 335116 的 train 0/50 已完成 probability 5、components/F1-centered 各 4 份并记录 1 份 `_BLOB_EXCEED`，继续处理 `5j8k`，owner 为 `gnode10:8656`。两项 Slurm、动态命令、租约和 allocation 错误扫描正常；从登录节点向计算节点的嵌套 SSH 仍被拒绝，因此本次未取得直接 GPU 采样，但完成数量与活跃租约持续推进，不构成训练停滞证据。连续五次健康检查完成后，heartbeat 已恢复为每 2 小时。

### 2026-08-04 12:35+08:00

Job 335115 与 Job 335116 继续在 `gnode10` 运行，分别处理 validation 与 train 全局分片 0/50；两项各自只有 `after_lock`，没有 `try_lock` 或 `kill_lock`，allocation 错误扫描为空。validation 已完成 probability、components 与 F1-centered 各 9 份，当前租约为 `6az1`；train 0/50 已完成 probability 6 份、components/F1-centered 各 4 份，并记录 2 份 `_BLOB_EXCEED`，当前租约为 `5lzy`。本次没有 OOM、未处理异常或目录碰撞，GPU 主线继续健康。

独立 Gauss calibration forest 回填已经完成并深验收，作业、字段数量和数值证据见 `talk/Find_0高斯联合打分检查记录.md`。正式 CPU 回填入口已经补为可在 GPU 运行期间增量扫描：尚未完成或正在被 GPU 持有的 PDB 只跳过，未来重复执行相同分片即可补齐。该调整不修改当前两个冻结 GPU release 或用户的 F1 脚本。普通监控间隔按用户要求改为每 3 小时。

### 2026-08-06 03:49+08:00

按用户授权，为 train 增加全局分片 1/50，并复用 Job 335493 已由 `after_lock` 保留的单张 A800。Pocket_Plus 本地只新增 `训练与运行/sh/infer/Find_0_train_F1_shard_01.sh`：它从既有 train F1 人类入口作最小复制，固定 `global_shard_count=50` 与 `shard_index=1`，其余 checkpoint、配置、输入清单、输出根、完整图批量 10、居中批量 8、100 GiB 缓存和组件参数均不变。文件保持未跟踪、未暂存，SHA-256 为 `b3cf8f625f9af1956865633803afe3d095fa1f831bca48e70e87dd69b2076ece`；服务器项目入口和一次性 runtime 副本与该哈希一致，均已通过 `bash -n`。

Job 335493 原来正在运行 Matcher v2 attempt 6。主 agent 先建立精确 `kill_lock_335493`，等待旧命令结束、kill 锁被 runner 删除并出现 `try_lock_335493`；随后在 `try_lock` 保护下原子替换动态 `run_cmd`，最后只删除该 `try_lock` 激活新命令。整个过程没有 `scancel`，`after_lock_335493` 始终保留；旧动态命令和切换前证据分别保存在 `/home/penghongen/My_Project/tmp/find0_train_shard01_job335493/run_cmd_before_takeover.sh` 与 `pre_takeover.txt`。新动态命令 SHA-256 为 `9b9a690c7114e371d9710fba411447086c7cc9f9fbcc7b6695439e312a4596a6`，契约证据为同目录 `activation_contract.txt`。

新任务是 Job 335493 attempt a7，launch 为 `/home/penghongen/Feedback/AdaLigand/launches/335493/train_anchor_O_O_prime_job335493_20260806T034515_a7`。launch 名称继承 allocation 的历史任务名称，真实身份以 launch 内 `run_cmd.sh`、动态命令和 Python 进程为准。运行时通过 `POCKET_INFERENCE_PROJECT_ROOT` 显式绑定 `/home/penghongen/Feedback/Pocket_Plus/releases/Pocket_Plus_c65e77b0b031/Pocket_Plus`，与 Job 335116 的 train 0/50 使用同一冻结代码；checkpoint 仍为 `TOP_epoch_00_score_0.2843.ckpt`，SHA-256 为 `87ec6080809a14e2558e10c0740c16371b363fed0f672081b389f46c64928b44`。

train 公共清单共 13,714 项，零起始分片 1/50 精确包含 275 个 PDB。启动后 Python 命令带 `--shard-index 1 --shard-count 50`，首个 PDB `10ay` 已建立 owner `gnode10:62611` 的活跃 `_RUNNING`；一次计算节点采样显示该进程已占用约 56 GiB A800 显存。03:49 时仍在首个样本初始化，尚无 `_COMPLETE` 或 `_BLOB_EXCEED`，allocation 新错误日志为空。这证明任务身份和运行入口已生效，但首次完整 PDB 仍由后续 heartbeat 确认。原 Job 335115 validation 与 Job 335116 train 0/50 不受本次切换影响；三个作业统一纳入每 3 小时 heartbeat。

03:57 的继续检查完成首次端到端健康验收：`10ay` 已同时写入 probability、components 与 F1-centered `_COMPLETE`，进程把活跃租约推进到第二个 PDB `11ta`。A800 占用约 79.2/81.9 GiB，当前没有 `try_lock`、`kill_lock` 或新错误日志；高显存占用与原正式 train 0/50 的参数画像一致，尚无 OOM 证据。

### 2026-08-06 21:35+08:00

Job 335115 attempt a3 已于 20:25 成功完成 validation 并创建 `/home/penghongen/Feedback/Pocket_Plus/allocations/try_lock_335115`。`after_lock_335115` 继续保留；计算节点上只剩 allocation 包装进程，没有 validation Python 子进程，A800 显存回落到空闲水平。动态命令仍是先运行 calibration F1、再以 `exec` 运行 validation F1，冻结 release 为 `/home/penghongen/Feedback/Pocket_Plus/releases/Pocket_Plus_c65e77b0b031/Pocket_Plus`。allocation 标准输出明确记录第 3 次执行成功，标准错误只包含 release 创建或复用记录，OOM、traceback、运行时异常和模型身份错误扫描均为空。

validation 公共清单恰好包含 200 个 PDB。正式目录中 200 项均有 probability `_COMPLETE`；其中 183 项同时具有 components 与 F1-centered `_COMPLETE`，其余 17 项只具有 probability 完成标记和 PDB 根目录 `_BLOB_EXCEED`。两个集合互斥并精确覆盖 200 项；不存在 `_RUNNING`。17 个超限 PDB 是 `6c3p`、`6nc3`、`6w2s`、`6wmr`、`7a5i`、`7v3u`、`8jdk`、`8oe0`、`8oo0`、`8t2y`、`9dbe`、`9eh2`、`9h54`、`9pj8`、`9qlq`、`9srd`、`9ypw`。Job 335115 保持 `try_lock` 与 `after_lock`，没有删除锁、重复运行或释放 A800。

同一时刻，Job 335116 的 train 0/50 已完成 215 份 probability，其中 192 份完成 components/F1-centered、23 份写入根级 `_BLOB_EXCEED`，并持有一个活跃 PDB 租约；Job 335493 的 train 1/50 已完成 49 份 probability，其中 42 份完成 components/F1-centered、7 份写入根级 `_BLOB_EXCEED`，并持有一个活跃租约。两个训练进程、A800 显存、正式命令和错误日志正常；两个分片各自只覆盖 275 个 PDB，仍不能视为 train 全量完成。

## 2026-08-06：下一版 Fα、Li 与超限开关实现检查

本次只修改隔离的 Pocket_Plus 实现工作树与 AdaLigand 记忆文档，没有同步服务器，也没有改动 Job 335115、335116、335493 的冻结 release、动态命令、锁或正式产物。

- Fα：直接读取 calibration 已冻结的七个 `t_alpha` 层，添油式生成同构 centered 文件；alpha 等于 1 时继续使用历史 `F1_centered.npz`，其余六个角色使用有理数文件名。不重建 forest 或 CLG。
- Li：读取主线已完成的 `probability_map.npz`，逐图计算 Li 阈值并向上量化到 32768 分母网格，以 `min_voxels=10` 在内存中构造 blob，结果只写入 `/storage/penghongen/AdaLigand_stage1_LI_inference` 下的 `Li_centered.npz`。不落盘 forest、CLG 或 Selector 输入。
- `_BLOB_EXCEED`：生产开关 `continue_on_blob_exceed` 与评估开关 `evaluate_on_blob_exceed` 相互独立。正式新 calibration 脚本才开启继续生产，validation/train 保持关闭；正式评估脚本始终开启评估纳入。
- 验证：Fα 与 Li 的真实 CLI 小型端到端路径、归档校验、超限续跑和评估纳入均进入回归；推理、产物与评估相关的 64 项测试通过，Python 编译和正式 shell 语法检查通过。完整测试在收集阶段因当前 Windows 环境缺少 `rootutils`、`lightning`、`torch_cluster` 与 `addict` 而停止，没有出现本轮相关测试失败。
- Git 收口：Pocket_Plus 真实实现端点为 `5b014d6`，推理/Gauss 学习端点为 `d54ec20`，第二版 BOX 池与 `Learn/CUMULATIVE` 端点为 `0976f64`。两端 tree 精确相同；额外 54 项 BOX、数据集、配置与任务调度测试通过。主工作树保留 staged 的 `talk/global.md` 与未跟踪的 `Find_0_train_F1_shard_01.sh`，没有 push。

该记录只证明下一版源码的本地实现状态，不表示 Fα 或 Li 正式服务器推理已经开始。

### 2026-08-07 11:19+08:00

用户要求已经完成并通过验收的单卡任务释放相应资源。主 agent 在释放前重新核对 Job 335115：Slurm 身份为父数组 `335115` 的分片 1，`try_lock_335115` 存在，`after_lock_335115` 存在，`kill_lock` 不存在；计算节点没有 validation 推理进程，A800 显存仅有 2 MiB 基础占用且利用率为 0%。此前 200 项 validation 的 183 份完整 F1-centered 产物与 17 份合法 `_BLOB_EXCEED` 已完成独立验收，因此满足安全释放条件。

主 agent 只删除 `/home/penghongen/Feedback/Pocket_Plus/allocations/335115/after_lock_335115`，没有使用 `scancel`，也没有修改 `try_lock`、动态命令、release、launch、日志或正式推理产物。四锁执行器随后正常退出并清理活动锁；`sacct` 记录数字 Job 335115，即数组元素 `335115_1`，最终为 `COMPLETED 0:0`，`squeue` 中只剩仍在运行的 `335115_0`（数字 Job 335116，train 0/50）与 Job 335493（train 1/50）。本次释放没有触碰两个 train 作业。
