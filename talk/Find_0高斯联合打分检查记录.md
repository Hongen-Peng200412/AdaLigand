# Find_0 高斯联合打分检查记录

本文记录独立 Gauss scorer 的代码身份、参数搜索、运行作业、指标、冻结参数和 forest 回填验收。科学公式与实施边界见 `文档/exec_plan/Find_0高斯联合打分实施.md`。完整图概率、阈值冻结和 F1-centered 主线的运行证据继续记录在 `talk/Find_0推理与评估检查记录.md`。

## 已冻结边界

- 输入是已经完成的 `components/forest.npz` 与 `centered/F1_centered.npz`。
- 原子概率来自预测 blob 口袋 A 表的 `A_probability`；不读取完整图受体概率，不重新执行模型。
- A 原子到来源预测 blob 最近体素中心的距离按世界坐标计算，固定截断为 5 Å。
- 正式参数是严格为正的 `lambda_positive`、`lambda_negative`、`tau_angstrom` 和 `gauss_score_min`。
- 每个参数取三个候选值形成 81 组，另设一组不执行 Gauss 过滤的现有候选基线。
- 正式 forest 只增加 `gauss_score` 和 `gauss_selected`；不改写 `candidate_eligible`，不限制 CLG 或 Selector 候选。
- calibration、validation、train 的基础候选都来自统一的 `min_voxels=10` 冻结阈值契约。
- 调参入口放在 Pocket_Plus `ops/Gauss_Scorer/`，长期代码放在 `src/inference/Gauss_Scorer/`，大文件只放 `/storage/penghongen/tmp`。

## 2026-08-04 实施启动

Pocket_Plus 只读 Git 审计确认 `Learn/CUMULATIVE@7fdaa98754c2e63694a9f68dcc71036102ca1860` 是按提交者时间形成的唯一最新提交。主工作树中三个 F1 人类脚本已有用户暂存修改，没有被纳入或改变。Gauss 实现从同一基点建立隔离分支 `codex/find0-gauss-scorer`，工作树为 `C:/Users/15919/.codex/worktrees/019fc1b6-gauss/Pocket_Plus`。

当前 calibration 概率图仍在生产，尚未生成可用于参数搜索的完整 calibration F1-centered 集合。Gauss 实现可以并行准备，但不得等待该支线后再启动阈值与 F1 主线。

在隔离分支中已经完成第一版长期计算、独立回填与 calibration 参数扫描入口：距离和 A 原子概率严格按 F1-centered offsets 与来源节点身份读取，5 Å 截断、未归一化正负和、四个正参数及 `gauss_score/gauss_selected` 可选字段已经实现。CLG 与 Selector 的 forest 解码只校验这两个字段成组出现，仍完全按原 `candidate_eligible` 与原候选集合工作。参数扫描会排除 `_BLOB_EXCEED` PDB，并报告现有候选基线以及四轴组合的语义、coverage、one-to-one 与 top-K 指标。

真实实现提交为 `codex/find0-gauss-scorer@b15c9ce`。学习历史按“基础阈值与评估契约 → 独立 forest scorer → calibration 参数扫描与文档”重建为三段，端点为 `Learn/find0-gauss-scorer@ffcaa40`；实现端点与学习端点的 tree 都是 `21035826ded80cd6860cec566f164c2f46065e52`。主分支 `Learn/CUMULATIVE` 已只快进到同一学习端点，原有三份 staged F1 脚本和三份 unstaged 人类入口改动在快进前后保持同一状态。

专项测试与相关回归共 32 项通过；另一次较广测试此前在未修改的 Windows Dataset 原生路径发生进程级中止，专项隔离后确认不位于 Gauss、组件或评估改动路径。正式 CPU 参数搜索仍必须等待 calibration F1-centered 完整，并在提交前进行一次节制的独立只读审计。

## 2026-08-04 calibration 输入就绪

09:33 的独立只读最终验收确认 calibration 的 100 项清单精确分成 86 份可消费的 components/F1-centered 产物和 14 份 `_BLOB_EXCEED`，没有 `_RUNNING`。86 份 forest 与 centered NPZ 已逐项读取；其中 `8tu8`、`9jeq` 是字段和 offset 均符合契约的零候选空产物。Gauss 参数搜索因此已经解除输入前置条件，可以与正在运行的 validation 和 train GPU 主线并行。

CPU 参数搜索已经完成网格、临时目录和数组切分冻结，并在一次节制的独立只读复核通过后提交；不得为了 Gauss 搜索暂停或修改 Job 335115/335116。

## 2026-08-04 正式参数搜索提交

四轴网格固定为：`lambda_positive=[0.001,0.01,0.1]`、`lambda_negative=[0.001,0.01,0.1]`、`tau_angstrom=[0.5,1.0,2.0]`、`gauss_score_min=[0.5,1.0,1.5]`；距离截断固定为 5 Å。正负系数覆盖 100 倍范围以容纳未归一化原子和的尺度变化，tau 覆盖亚埃到 2 Å，得分阈值围绕原始 `probability_mean≈1` 分布。网格 SHA-256 为 `85dec01cddbf992e7f8170a0d87e5626a90252487bdab002b8a21beeddb6f8dd`。

正式提交前的独立只读审计通过：82 组配置由 1 组无过滤基线和 81 组全正参数组成，按 `config_index % 8` 在八项数组间互斥且完整切分；14 份 `_BLOB_EXCEED` 被排除；目标函数字段正确；evaluate 阶段只读正式 forest、centered 与真值，唯一写入临时 part 文件，不会回填 forest。服务器同步后的三个入口文件通过 SHA-256 与 shell 语法核对。

10:15 提交父数组 Job 335529，实际数字 Job 为 335529、335530、335531、335532、335533、335534、335535、335536，每项申请 CPU16，未设置 `after_hold`。八项均以 full 模式启动，共享 release `/home/penghongen/Feedback/Pocket_Plus/releases/Pocket_Plus_58afbf1dbaea/Pocket_Plus`，各自 launch 位于 `/home/penghongen/Feedback/Pocket_Plus/launches/<job_id>/evaluate_find0_calibration_job<job_id>_20260804T10*/`。唯一临时结果目录为 `/storage/penghongen/tmp/find0_gauss_scorer_job335529/`。初始检查八项均为 RUNNING，release/launch 与动态命令身份一致，尚未产生 part 文件或错误；只有八份 part 全部成功后才允许 merge，当前不写正式 `calibration.json`，也不回填 forest。

八项随后全部以 `COMPLETED 0:0` 收口，耗时约 1 分 47 秒至 2 分 05 秒，`part_000.json` 至 `part_007.json` 齐全且错误扫描为空。主 agent 的只读解析确认：八份网格 SHA 一致，`task_index=0..7`、`task_count=8`，每份都记录同一 86 个评估 PDB 和 14 个 `_BLOB_EXCEED`，配置编号精确覆盖 0..81 且无重复，所有浮点指标有限。

无过滤基线的目标函数为 1.0722594872，其中 semantic Dice micro、coverage F1@0.3、one-to-one F1@0.3 分别为 0.3991587077、0.3386833316、0.3344174479。当前最优配置 59 同时是 `best_overall` 与 `best_gauss`：`lambda_positive=0.1`、`lambda_negative=0.001`、`tau_angstrom=1.0`、`gauss_score_min=1.0`、截断 5 Å；三项指标分别提高到 0.4633845442、0.5343108282、0.5237237237，目标函数为 1.5214190961。预测实例数由 3363 降到 1466；coverage recall@0.3 从 0.4860515021 轻微降到 0.4849785408，但 coverage precision@0.3 从 0.2598870056 提高到 0.5948158254。

独立只读复核最终完整通过：八项作业身份、共享 release、八份 part、86/14 PDB 集合、0..81 配置覆盖、全部有限指标和逐配置目标函数重算均一致；独立复核复现了相同的基线与配置 59 最优结论。

随后提交 CPU16 合并 Job 335539。它复用 release `Pocket_Plus_58afbf1dbaea`，launch 为 `/home/penghongen/Feedback/Pocket_Plus/launches/335539/merge_find0_calibration_job335539_20260804T102733_a1`，在 31 秒内 `COMPLETED 0:0`。完整 82 组结果位于 `/storage/penghongen/tmp/find0_gauss_scorer_job335529/tuning_results.json`；正式参数位于 `/storage/penghongen/AdaLigand_stage1_inference/Find_0-CPC1-ligand_PRAUC_0.675477/artifacts/Find_0/gauss_scorer/calibration.json`。主 agent 重读验收确认两者的网格 SHA、最佳参数、最佳/基线指标、86 个评估 PDB 与 14 个排除 PDB 完全一致，所有值有限。

## 2026-08-04 calibration forest 正式回填

提交前只读复核确认 calibration 已静止为 86 份可消费 forest 与 14 份 `_BLOB_EXCEED`，Job 335115/335116 当前只写 validation 与 train，不会触碰 calibration。回填前，主 agent 使用仅存在于本机临时目录的验收脚本读取 86 份 forest；两个 Gauss 字段均不存在，17 个旧字段的聚合 SHA-256 为 `83558c5427adec87b75958a2b9c1b9a12543eff5a27d21ade8fb0e396ef7f3d0`。该哈希只用于前后比对，不进入 Pocket_Plus 正式代码、配置或产物。

正式 CPU16 Job 335572 使用 release `/home/penghongen/Feedback/Pocket_Plus/releases/Pocket_Plus_34a6b476fc71/Pocket_Plus`，launch 为 `/home/penghongen/Feedback/Pocket_Plus/launches/335572/Find_0_calibration_Gauss_job335572_20260804T123137_a1`。作业运行 4 分 16 秒并以 `COMPLETED 0:0` 结束；标准输出记录 `n_assigned=100`、`n_completed=86` 与同一 14 项超限清单，错误输出只有 release 创建记录，没有异常栈。

最终深验收逐项读取 86 份回填后的 forest 与 F1-centered 来源表：

- 86/86 都同时新增 `gauss_score: float32 (N_node,)` 与 `gauss_selected: bool (N_node,)`；
- 有限得分位置精确等于 3363 个 F1 来源节点，其余 forest 节点为 `NaN`；
- `gauss_selected` 精确等于有限得分且 `gauss_score >= 1.0`，共有 1466 个节点为 `True`；
- 有限分数范围为 `[0.9963870049, 2.9656352997]`；
- 所有被选节点仍满足原 `candidate_eligible`；
- 17 个旧字段的回填后聚合 SHA-256 仍为 `83558c5427adec87b75958a2b9c1b9a12543eff5a27d21ade8fb0e396ef7f3d0`；
- 14 份 `_BLOB_EXCEED` 没有 forest 回填，正式 calibration 目录没有 `_RUNNING`。

用户随后要求正式入口可以在 GPU 主线运行时随时增量执行。`src/inference/Gauss_Scorer/cli.py` 已作最小调整：前置角色尚未完成时记录 `pending`，租约被 GPU 持有时记录 `skipped_running`，两者都跳过当前 PDB 并继续处理其余项；真实输入损坏、字段冲突或科学契约错误仍然失败。正式人类入口统一为 `训练与运行/sh/infer/Find_0_Gauss.sh`，可显式选择数据划分与全局分片数。专项及相关契约回归 20 项通过，文档已补入推理 README、产物 README 与 BOX-level 数据契约；这些工作树改动没有提交或加入 Git 索引。

## 待补充

- 实现提交、学习提交和端点等价证据；
- 参数候选值及其选择依据；
- CPU 数组 Job、release、launch、分片与临时目录；
- 82 组 calibration 指标和唯一最佳参数；
- 正式 `calibration.json` 地址与身份；
- validation 与 train 的 forest 增量回填数量、待补清单和最终字段验收。

## 2026-08-06：第二阶段精修、通用 centered 与强制回填实现检查

下一版 Gauss scorer 已在隔离 Pocket_Plus 实现工作树完成以下扩展，当前冻结服务器任务未使用这些改动：

- 第二阶段网格固定第一阶段最优的 `tau_angstrom` 与 5 Å 截断；`lambda_positive`、`lambda_negative` 分别取中心值的 0.8、0.9、1.0、1.1、1.2 倍，`gauss_score_min` 取中心值的 0.3 至 1.7 倍、步长 0.1，共 375 组严格正参数，不重复无过滤基线。
- 同一评分和评估实现可消费七个 Fα-centered 角色或独立 `Li_centered`。Fα 结果仍只占用 forest 的 `gauss_score`、`gauss_selected`；Li 结果写入自身 centered 文件，不创建 forest。
- 正式回填 CLI 默认强制刷新已有完整 Gauss 字段对，只替换这两个字段；关闭强制刷新时要求重算结果逐值相同。只存在一个字段时，无论是否强制刷新都视为损坏并停止。
- 生产与评估继续使用同一 PDB 租约；正式评估入口显式开启 `evaluate_on_blob_exceed`。Gauss 选择结果仍不改写 `candidate_eligible`，不限制 CLG 或 Selector 候选。
- 推理、产物与评估相关的 64 项回归测试、Python 编译和相关 shell 语法检查通过。完整测试在收集阶段因当前 Windows 环境缺少 `rootutils`、`lightning`、`torch_cluster` 与 `addict` 而停止；尚未运行新的第二阶段服务器参数搜索，也没有覆盖 2026-08-04 已冻结和回填的第一阶段结果。
- 双线收口：Gauss 正式代码在学习线集中为 `ac2c02a`，推理学习端点 `d54ec20`；真实实现端点 `5b014d6` 与最终学习端点 `0976f64` 的 tree 同为 `a8157b3a084770fcc615b0a8035c82be15167fed`。旧 Gauss Learn 引用移入 `archive/`，第一阶段服务器参数与 forest 回填未改动，未 push。
