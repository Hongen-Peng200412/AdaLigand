# Find_0 预测口袋原子高斯联合打分实施

本 ExecPlan 是持续更新的执行记录。实施期间必须同步维护 `Progress`、`Surprises & Discoveries`、`Decision Log` 和 `Outcomes & Retrospective`。本文依据 `文档/exec_plan/Find_0推理与F1居中产物实施.md` 已经生产的 Stage1 推理产物建立一条独立支线；该支线不得延迟或改变完整图概率、阈值冻结和 F1-centered 主线。

## Purpose / Big Picture

本任务为 Find 模型的 `t_F1` 合格预测组件增加一个可解释的原子联合得分。打分器读取已经完成的 `components/forest.npz` 与 `centered/F1_centered.npz`，利用每个预测 blob 口袋中的受体原子结合概率，对原有 `probability_mean` 加入距离衰减的正奖励和负惩罚。calibration 数据划分负责选择四个正参数；冻结后同一参数应用于 calibration、validation 和 train。

最终每个 `forest.npz` 只增加 `gauss_score` 和 `gauss_selected`。原有 `candidate_eligible`、组件树、体素成员、CLG 候选和 Selector 输入保持不变。Gauss scorer 是比 CLG/Selector 更简单的独立选择器，不能成为 CLG 或 Selector 的前置过滤器。

## Progress

- [x] (2026-08-04) 重新阅读用户原始提示、旧提交 `4d798c9c6e49d031e8f5fefa38f99fee4f463209` 的高斯响应逻辑、当前 `src/artifacts/readme.md` 和 centered 实现。
- [x] (2026-08-04) 核实 `F1_centered.npz` 的 `source_tree_id + source_node_id` 精确指回一个 `t_F1` 合格 forest 节点，`A_probability` 是该预测 blob 口袋在 centered 前向后的受体原子结合概率。
- [x] (2026-08-04) 用户批准独立 Gauss scorer 的科学边界、四参数搜索、CPU 数组、正式字段和非阻塞关系。
- [x] (2026-08-04) 从 Pocket_Plus 唯一最新的 `Learn/CUMULATIVE@7fdaa98754c2e63694a9f68dcc71036102ca1860` 建立隔离实现分支 `codex/find0-gauss-scorer`；主工作树中用户已经暂存的三个 F1 脚本保持不动。
- [x] (2026-08-04) 在 `ops/Gauss_Scorer` 实现 calibration 参数搜索与结果汇总入口；实现端点 `b15c9ce` 与学习端点 `ffcaa40` 已完成等价核验。
- [x] (2026-08-04) 在 `src/inference/Gauss_Scorer` 实现冻结参数读取、纯计算、原子 forest 回填和验收；相关回归共 32 项通过。
- [x] (2026-08-04) calibration 参数搜索与冻结完成：82 组配置全部验收，唯一最优参数为 `lambda_positive=0.1`、`lambda_negative=0.001`、`tau_angstrom=1.0`、`gauss_score_min=1.0`，截断 5 Å。
- [ ] (2026-08-04 12:35+08:00) calibration 的 86 份 forest 已完成正式回填和逐字段验收；validation 与 train 等待各自 F1 产物继续增量回填。
- [x] (2026-08-06) 完成下一版两阶段参数搜索与通用 centered 输入：第二阶段固定 tau 与 5 Å 截断，扫描 5×5×15 共 375 组正参数；同一实现可消费七个 Fα-centered 或独立 Li-centered。正式回填 CLI 默认强制刷新，但只能替换 `gauss_score` 与 `gauss_selected`；字段对残缺时始终报错。推理、产物与评估相关的 64 项回归测试、Python 编译和 shell 语法检查通过；完整测试在收集阶段因当前 Windows 环境缺少四项训练侧依赖而停止，尚未向当前冻结运行发布。
- [x] (2026-08-06) 按双线规则将 Gauss 正式实现压缩为学习提交 `ac2c02a`，其所在推理学习端点为 `d54ec20`；第二版 BOX 池续接后 `Learn/CUMULATIVE` 为 `0976f64`。真实实现端点 `5b014d6` 与学习端 tree 精确相同，均为 `a8157b3a084770fcc615b0a8035c82be15167fed`；旧 Gauss Learn 引用已移入 `archive/`，未修改远端。
- [ ] 更新 Pocket_Plus 与 AdaLigand 契约、执行记录、映射和 CLAUDE memory，并完成实现线与学习线等价收口。

## Surprises & Discoveries

- Observation: 当前完整图 `probability_map.npz` 只保存配体概率，但 Gauss scorer 并不需要在该文件中增加受体概率。
  Evidence: Find 的 `F1_centered.npz` 已保存与预测 blob 口袋逐行对齐的 `A_coord_local_xyz`、`A_probability` 和来源节点身份。

- Observation: A 表已经被 centered 生产器限制为 80³ 核心与来源预测 blob 的 10 Å 包络交集；Gauss scorer 的 5 Å 截断是在该现成集合上进一步缩小计算范围。
  Evidence: `src/inference/centered.py::_payload_from_forward` 调用 `_points_within_blob_envelope(..., distance_angstrom=10.0)` 后同步筛选全部 A 字段。

- Observation: 当前 `ComponentForest.from_npz_arrays` 使用精确字段集合，直接增加两个字段会使旧读取器拒绝文件。
  Evidence: `src/component_lineage/structures.py` 的 forest schema 校验列出固定字段集合。最终实现必须只增加“两个字段同时缺席或同时存在”的可选组，并让原有 forest 读取逻辑忽略该组，不把它接入 CLG 或 Selector 的候选判断。

## Decision Log

- Decision: 距离截断固定为 5 Å，不参与参数搜索。
  Rationale: A 表已是 10 Å 预测口袋；5 Å 截断保留近邻原子并减少远处大量原子对求和得分的影响。
  Date/Author: 2026-08-04 / 用户与 Codex

- Decision: 四个正参数是 `lambda_positive`、`lambda_negative`、`tau_angstrom` 和 `gauss_score_min`；每项三个候选值，共 81 组，另加现有候选集合的无过滤基线。
  Rationale: 前三个参数定义高斯联合得分，第四个参数把连续得分转换为保留或剔除决定；基线只用于比较，不违反正式参数严格为正的约束。
  Date/Author: 2026-08-04 / 用户与 Codex

- Decision: `min_voxels=10` 决定 Gauss scorer 接收的基础候选集合。
  Rationale: 用户要求正式 calibration、validation、train 的全部组件与 F1-centered 推理统一使用 10；Gauss scorer 不重新定义体素数资格。
  Date/Author: 2026-08-04 / 用户

- Decision: Gauss 结果不改写 `candidate_eligible`，不删除 forest 节点，也不改变 CLG/Selector 输入。
  Rationale: Gauss scorer 是独立降级选择器。未来 CLG/Selector 必须继续消费原有全部有效节点；`gauss_selected` 仅供直接读取该独立结果的调用者使用。
  Date/Author: 2026-08-04 / 用户

- Decision: 调参与正式代码分离。调参入口放在 `ops/Gauss_Scorer`，冻结后的精简计算与回填代码放在 `src/inference/Gauss_Scorer`，大文件只放 `/storage/penghongen/tmp`。
  Rationale: 参数实验需要保留可追溯入口，但不得污染长期生产模块；正式模块只保存已经冻结的计算定义和安全写入行为。
  Date/Author: 2026-08-04 / 用户与 Codex

- Decision: 正式 CPU 回填可以在 GPU 主线运行期间随时扫描；前置角色未完成或 PDB 租约被占用时只记录并跳过，不终止整个分片。
  Rationale: CPU 与 GPU 仍通过同一个 PDB 根租约保持互斥，同时已经静止的 forest 可以立即获得结果；GPU 完成后重复运行相同分片即可补齐，不需要第二套目录或额外状态机。
  Date/Author: 2026-08-04 / 用户与 Codex

- Decision: 参数搜索增加第二阶段局部精修。第一阶段最优的两个 lambda 各取 0.8 至 1.2 倍共 5 点，`gauss_score_min` 取 0.3 至 1.7 倍共 15 点，tau 与 5 Å 截断固定；第二阶段不重复加入无过滤基线。
  Rationale: 375 组配置在 CPU 数组上仍是可控规模，同时把搜索预算集中到用户指定的三个参数。
  Date/Author: 2026-08-06 / 用户与 Codex

- Decision: 回填默认允许使用当前冻结参数覆盖旧 Gauss 结果，但只改写两个 Gauss 字段；只存在其中一个字段时无条件视为损坏。
  Rationale: 用户需要随时采用新的调参结论刷新结果，又不能让覆盖能力掩盖不完整写入或改变 forest、CLG、Selector 的任何历史字段。
  Date/Author: 2026-08-06 / 用户与 Codex

- Decision: Fα scorer 继续把结果写入主线 forest；Li scorer 只把同名字段写入独立 `Li_centered.npz`。
  Rationale: Li 不建立持久化 forest，Fα 与 Li 都不改变 `candidate_eligible` 或 Selector 候选；两者只共享计算和评估算法，不引入新的主线候选契约。
  Date/Author: 2026-08-06 / 用户与 Codex

## Outcomes & Retrospective

科学公式、输入身份、四参数空间、目录职责、主线隔离和最终字段已经冻结。真实实现端点为 `codex/find0-gauss-scorer@b15c9ce`；学习端点和 `Learn/CUMULATIVE` 均为 `ffcaa40`，两端 tree 精确相同。纯计算、forest 可选字段、独立原子回填和 calibration 参数扫描入口已经完成。随后补充的最小增量行为允许 `pending` 与 `skipped_running` PDB 留待下次扫描，相关专项与契约回归 20 项通过；本轮改动按用户要求保留在学习分支工作树，不提交。

提交使用三个数量级跨度的正负系数 `lambda_positive/lambda_negative=[0.001,0.01,0.1]`、空间尺度 `tau_angstrom=[0.5,1.0,2.0]` 与围绕原始 `probability_mean≈1` 的 `gauss_score_min=[0.5,1.0,1.5]`，截断距离固定为 5 Å。网格文件 SHA-256 为 `85dec01cddbf992e7f8170a0d87e5626a90252487bdab002b8a21beeddb6f8dd`。提交前独立只读审计通过，确认 8 个分片按 `config_index % 8` 精确覆盖 82 组、评估过程不写 forest、合并前不会冻结参数。

父数组 Job 335529 的实际数字 Job 为 335529 至 335536，每项使用 CPU16；八项共享 release `/home/penghongen/Feedback/Pocket_Plus/releases/Pocket_Plus_58afbf1dbaea/Pocket_Plus`，临时结果唯一写入 `/storage/penghongen/tmp/find0_gauss_scorer_job335529/parts/`。全部 `part_000.json` 至 `part_007.json` 成功且通过独立复核后，才允许运行 merge 并写正式 `gauss_scorer/calibration.json`；本阶段不回填任何 forest。

八项均已在约 2 分钟内以 `COMPLETED 0:0` 结束并生成八份 part。主 agent 与独立只读复核共同确认 86/14 PDB 集合一致、配置编号 0 至 81 精确覆盖、目标函数重算一致且指标有限。基线目标函数为 1.0722594872；唯一最优为配置 59：`lambda_positive=0.1`、`lambda_negative=0.001`、`tau_angstrom=1.0`、`gauss_score_min=1.0`，目标函数 1.5214190961。其三项组成指标分别为 semantic Dice micro 0.4633845442、coverage F1@0.3 0.5343108282、one-to-one F1@0.3 0.5237237237。

合并 Job 335539 使用同一 release `Pocket_Plus_58afbf1dbaea`，在 31 秒内 `COMPLETED 0:0`。完整 82 组结果保存于 `/storage/penghongen/tmp/find0_gauss_scorer_job335529/tuning_results.json`；正式参数已经冻结到 `/storage/penghongen/AdaLigand_stage1_inference/Find_0-CPC1-ligand_PRAUC_0.675477/artifacts/Find_0/gauss_scorer/calibration.json`。主 agent 完整重读两份 JSON，确认参数、最佳/基线指标、网格身份和 86/14 清单一致。当前仍未回填任何 forest；下一阶段先对已静止的 calibration forest 执行正式回填，再随 validation/train 主线完成情况安排其余数据划分。

正式 calibration 回填 Job 335572 使用 CPU16 与 release `Pocket_Plus_34a6b476fc71`，launch 为 `Find_0_calibration_Gauss_job335572_20260804T123137_a1`，4 分 16 秒后以 `COMPLETED 0:0` 结束。它精确报告 100 个清单项、86 个完成项和 14 个 `_BLOB_EXCEED`。回填前后对 86 份 forest 的全部 17 个旧字段按清单、字段名、dtype、形状和值计算的临时验收摘要一致；该临时哈希只用于验收，没有进入正式代码或产物。最终逐项确认 86 份 forest 都只新增 `gauss_score: float32` 与 `gauss_selected: bool`，3363 个 F1 来源节点具有有限分数，其中 1466 个达到冻结阈值；旧字段和 `candidate_eligible` 不变，14 份超限 PDB 未被回填，正式目录没有 `_RUNNING`。

## Context and Orientation

`components/forest.npz` 为一个 PDB 保存多阈值组件树。Gauss scorer 只处理冻结阈值 `t_F1` 上满足 `candidate_eligible == True` 的节点。`centered/F1_centered.npz` 为这些节点逐项重新执行 80³ BOX 前向，并使用 `source_tree_id` 与 `source_node_id` 保存来源身份。

对一个来源节点 $j$，设它的预测 blob 体素中心集合为 $V_j$。其预测口袋 A 表中的第 $i$ 个受体原子具有世界距离 $d_{ji}$ 和结合概率 $p_{ji}$。$d_{ji}$ 是该原子到 $V_j$ 最近体素中心的欧氏距离，单位 Å；它不使用真实配体坐标。

固定截断半径 $r=5$ Å，定义：

$$
w_{ji}(\tau)=\exp\left(-\frac{d_{ji}^{2}}{2\tau^{2}}\right)\mathbf{1}[d_{ji}\le r]
$$

$$
G_j^{+}=\sum_i w_{ji}(\tau)p_{ji}
$$

$$
G_j^{-}=\sum_i w_{ji}(\tau)(1-p_{ji})
$$

$$
S_j=\operatorname{probability\_mean}_j+\lambda_{+}G_j^{+}-\lambda_{-}G_j^{-}
$$

所有和都不除以原子数或权重和。5 Å 内没有原子时，两个和都是 0，$S_j$ 等于原有 `probability_mean`。正式选择条件是 $S_j\ge s_{min}$。

最终 `forest.npz` 增加：

- `gauss_score: float32 (N_node,)`：只在存在对应 F1 centered 项的 `t_F1` 合格节点上保存有限得分；其他节点为 `NaN`，表示没有执行 Gauss 打分。
- `gauss_selected: bool (N_node,)`：只在上述已打分节点且 `gauss_score >= gauss_score_min` 时为 `True`；其他节点为 `False`。

这两个字段必须同时存在或同时缺席。任何代码不得从 `gauss_selected` 反向改写 `candidate_eligible`。

## Plan of Work

第一里程碑实现纯计算与输入校验。代码从 F1 centered 的 offsets 中逐项取出 A 坐标、A 概率和来源 blob 体素，使用与 centered 口袋筛选相同的世界坐标定义计算最近距离。单元测试覆盖空 A 表、5 Å 边界、非单位体素尺寸、各向异性体素、正负项和来源节点身份。

第二里程碑实现 calibration 调参工具。工具先把每个 PDB 的来源节点、A 概率、最近距离、预测体素和真实 occurrence 交集整理成紧凑缓存，再把 81 组参数按稳定编号分给 Slurm CPU 数组。每组报告标准语义和实例指标。标记 `_BLOB_EXCEED` 的 PDB 完全排除，不计入分子或分母。

目标函数为：

$$
J=\operatorname{semantic\_dice\_micro}+\operatorname{coverage\_f1\_0p3}+\operatorname{one\_to\_one\_f1\_0p3}
$$

并列时依次比较 `one_to_one_f1_0p3`、`coverage_f1_0p3`、semantic Dice micro，最后使用固定参数组合编号。全部 0.3/0.5 指标、macro 诊断、预测实例数和基线都写入汇总报告。

第三里程碑冻结参数。正式配置保存到 `<artifacts-root>/Find_0/gauss_scorer/calibration.json`，其中写明四个参数、5 Å 截断、目标函数、清单身份、代码身份、基线指标和最佳指标。临时网格结果继续留在 `/storage/penghongen/tmp`，不复制进正式 forest。

第四里程碑实现原子回填。对一个已经完成 F1-centered 的 PDB，先读取并验证原 forest 和 centered 身份；写出临时 NPZ，完整重读并验证所有旧字段逐值不变以及两个新字段满足契约，最后在同一文件系统内原子替换正式 `forest.npz`。同一冻结参数重复运行必须得到相同数组并安全跳过或原子重写。

第五里程碑依次回填 calibration、validation 和 train。只处理 F1-centered 已完成的 PDB；某个数据划分仍有 GPU 主线生产者时不修改该 PDB 的 forest。Gauss 失败不会删除或重跑主线产物。

## Concrete Steps

在隔离 Pocket_Plus 工作树 `C:/Users/15919/.codex/worktrees/019fc1b6-gauss/Pocket_Plus` 中：

1. 在 `src/inference/Gauss_Scorer/` 编写距离加权、得分、选择、配置读取和原子回填模块。
2. 在 `ops/Gauss_Scorer/` 编写 calibration 缓存、参数网格、单分片执行、结果汇总和简短运行说明。
3. 为 forest 可选字段组、A 表切片、坐标距离、指标重用和回填原子性增加专项测试。
4. 运行相关 inference、artifacts、component lineage 与 evaluation 测试，再运行完整 Windows 测试。
5. 代码与正式 CPU 脚本完成后，节制地派一个只读 subagent 做独立提交前审计；所有修复仍由主 agent 完成。
6. calibration F1 完成后，通过 `训练与运行/submit_task.sh` 提交约 8 项 CPU 数组，每项 8 至 16 核；任务只写 `/storage/penghongen/tmp/find0_gauss_scorer_<run_stamp>/`。
7. 汇总 82 组结果并冻结唯一 `calibration.json`，然后执行三个数据划分的正式回填。

## Validation and Acceptance

实现验收必须证明：

- `A_probability` 与 `A_coord_local_xyz` 按 `A_offsets` 正确切片，来源节点由 `source_tree_id + source_node_id` 唯一定位。
- 距离以世界 Å 计算，5 Å 包含端点，且不使用真实配体坐标。
- 正负高斯项是未归一化求和；空原子集合退化为 `probability_mean`。
- 四个正式参数严格为正；baseline 不写成正式参数。
- `gauss_selected` 不改变 `candidate_eligible`、CLG、Selector 或 F1-centered 字段。
- 原 forest 的所有旧字段在回填前后逐值相同；只允许新增两个字段。
- 可选字段组同时缺席或同时存在；CLG/Selector 读取增加字段后的 forest 时继续使用原候选集合。
- 参数搜索排除 `_BLOB_EXCEED` PDB，并完整报告 81 组正参数与一组基线。
- calibration、validation、train 采用同一冻结参数；正式配置与运行记录可以追溯输入、代码和产物位置。

## Idempotence and Recovery

参数搜索只写带唯一运行标记的 `/storage/penghongen/tmp` 目录，不覆盖旧实验。单个数组分片可以按配置编号续跑，已完成配置由完整结果文件跳过。

forest 回填采用同目录临时文件和原子替换。进程在替换前失败时，原 forest 保持不变；替换后失败时，新 forest 已经通过完整重读校验。不得保留半写临时文件，不创建第二套 forest 目录，也不修改主线 `_COMPLETE` 的候选资格语义。

## Artifacts and Notes

长期代码：

- `Pocket_Plus/src/inference/Gauss_Scorer/`
- `Pocket_Plus/ops/Gauss_Scorer/`

正式配置：

- `/storage/penghongen/AdaLigand_stage1_inference/Find_0-CPC1-ligand_PRAUC_0.675477/artifacts/Find_0/gauss_scorer/calibration.json`

临时结果：

- `/storage/penghongen/tmp/find0_gauss_scorer_<run_stamp>/`

执行证据写入 `AdaLigand/talk/Find_0高斯联合打分检查记录.md`。当前字段契约在实现稳定后更新 `Pocket_Plus/src/artifacts/readme.md` 与 `AdaLigand/文档/讨论/BOX-level数据契约.md`；运行历史和 81 组明细不写入契约 README。

## Interfaces and Dependencies

正式计算使用 NumPy 与 SciPy `cKDTree`。距离查询使用 centered 产物已经冻结的局部坐标和 `voxel_size_world`，不重新加载模型或 Dataset。指标复用 `src/evaluation` 现有语义 Dice、coverage 和 one-to-one 统计函数，不另写一套数学定义。

长期 Python 入口保持在 `src.inference.Gauss_Scorer`；CPU 调参与任务切分只位于 `ops/Gauss_Scorer`。不得把参数网格、Slurm 数组编号或临时路径导入长期生产模块。

Revision note (2026-08-04): 初次建立。根据用户重新提供的原始提示和审批意见，固定 Gauss scorer 与主线隔离、A 原子概率语义、四参数空间、5 Å 截断、两个 forest 字段、CLG/Selector 不受过滤以及受限 subagent 规则。

Revision note (2026-08-06): 增加 375 组第二阶段局部网格、Fα/Li 通用评分、默认强制刷新和独立超限评估开关。历史 calibration 第一阶段结果与当前服务器冻结运行不被本次本地实现覆盖；待 Git 双线重整完成后再按新入口安排后续实验。
