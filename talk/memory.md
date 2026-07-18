# Stage1 审阅工作记忆

> 本文件只保存本轮审阅的关键事实、证据指针和待核对项，防止长上下文压缩造成信息丢失。它不是正式规格、执行日志或最终审阅结论；最终结论分别写入 `talk/术语问题.md`、`talk/优化建议.md`、`talk/文档遗漏&冲突.md` 和 `talk/实操.md`。

## 当前任务

- 完整审阅 `文档/讨论/BOX-level数据契约.md`、`文档/规划文档/Stage1训练实现计划.md`、`文档/规划文档/Stage1训练与多阈值推理.md`。
- 恢复并核对 A–G agent 的 Codex 任务 `019f4a1b-80c2-7c73-afee-758a28335dbd`；`019f61b9-97b1-78a0-8ce0-6a6b90d0368c` 是另一条 Stage1 规划/BOX 契约讨论任务，不是用户本轮所指的 A–G 记忆。
- 从术语、优化、文档遗漏/冲突、实操四方面给出证据化审阅。
- 实操重点：Find 训练紧急启动包，以及后续全图推理/多阈值/局部物化、测试集评估、Stage2 训练评估路线。

## 治理边界

- 完整结果写入四个 `talk/*.md`；对话只交付总览和导航。
- 本轮不直接修改正式规划、BOX 契约、代码、mapping 或执行日志。
- 发现实现漂移后先分类和报告，不静默回填 clean spec。
- 项目文档中的本地路径使用仓库相对路径；服务器契约路径可以使用绝对路径。

## 已确认事实

- 四个最终反馈文件在本轮开始时均为空。
- `文档/规划文档/Stage1训练实现计划.md` 是新增且已有工作树改动；另外两份核心文档也存在未提交改动。必须以当前工作树内容为审阅对象，并用 Git 历史解释来源，不能假设 HEAD 等同当前规格。
- mapping 将 `Stage1训练与多阈值推理.md` 标为当前主规格、未开工；BOX 契约为盘上 schema 唯一权威、未开工。
- `CLAUDE/memory/projects/adaligand.json` 当前目标明确写有“A–G 完成并验收后，再进入 Stage1 重训”。本地最新记录中的“Stage F 与尾段补算仍运行、Stage G 等待 analyze”只是历史快照，不是服务器 live status；因此执行前要复核远端，而 Find 训练的“现在就启动”至少要区分代码/小样本 smoke 与正式数据训练。
- Codex 任务 `019f61b9-…` 是 Stage1 规格讨论：它修改了 `Stage1训练与多阈值推理.md` 与 `BOX-level数据契约.md`，未修改代码、配置、mapping 或执行日志。该任务早期曾讨论 one-to-one oracle，但后半段已收敛并落盘 independent-max；早期分支不能再作为当前漂移证据。
- 用户于 2026-07-16 再次明确：Stage1 第二推理树网络使用 independent-max，`q_i=max_o IoU(M_i,G_o)`、`Q_GT(S)=sum q_i-lambda_count|S|`；它不构造 A/B，也不做候选—occurrence Hungarian。
- Stage2 Matcher 才使用 occurrence 级 A/B/O 与 identity 内 slot↔occurrence Hungarian；最终报告的 `1to1F1` 是独立 evaluator 指标。三者不可互相替代。
- Pocket Plus 当前本地分支为 `大重构`、HEAD `f4c3e5c`，但 `origin/大重构@4d798c9` 已包含本地工作树里对应的 frozen BN/Dropout eval 修复；当前 clone 另有无关删除/记忆改动。正式适配应从干净 `4d798c9` 起步，并同时记录 AdaLigand/Pocket Plus commit。
- 当前 AdaLigand 内没有 `stage1_data`、Find adapter 或新的可直接运行训练配置。现有 Stage1 相关 Codex 记录做的是规划/契约修改，不是实现。
- A–G 现有资产足以做适配开发和小样本 smoke，但正式 Find 数据集必须等待 F release/QC、G analyze、用户冻结 schema-v2 过滤配置、G filter 和 final keep-list。
- `019f4a1b-…` 的本地 rollout 末尾状态也已交叉核对：当时正式 F `316116` 与补算 `318350` 双 96 核正常推进，G `316117` 仍依赖等待。该记录是历史记忆而非当前服务器实时状态，不能据此宣布 F/G 已完成。

## 已定位的硬接口问题

- BOX 契约把 `origin_xyz` 定义为体素 `[0,0,0]` 的中心；Pocket Plus `box_geometry.py` 把 origin 当作 box 下角点。适配必须使用 `legacy_corner_xyz = contract_origin_center_xyz - 0.5 * voxel_size_xyz`，否则全体坐标错半个体素。
- 新数据提供 `ligand_area.npz/union_mask` 二值标签；Pocket Plus 旧 dense ligand loss 从 `ligand_dist_map` 构造目标。“复用旧损失”尚不是可执行契约，禁止静默伪造距离图。
- buffer 原子应只供上下文、core 原子才参与 receptor loss；旧模型已有 `atom_is_in_core_box`。实现计划同时写了“所有 receptor atoms”并把 core-loss 列为未决，必须修正。
- `hardmask` 是在线生成的 receptor occupancy/geometry，不是磁盘 `voxel_valid_mask`；后者可不存，前者仍被部分 density channels 使用。
- 旧基线 `density_channels=all` 实际为 56 通道；单个 `56×80³ float32` 约 114.7 MB。应先做通道顺序/数值 parity，再做显存、吞吐与消融，不应凭名称直接继承。
- 文档的 zero-padding 边界已经在主计划和 BOX 契约冻结；只有实现计划仍误写“待定”。

## 指标与划分结论

- 用户要求正式报告 covF1/1to1F1 使用 IoU `0.3/0.5`；主计划和旧 evaluator 当前仍是 `0.3/0.6`。selector gate 的 `M_instance` 是否同步改阈值是独立待决项。
- 旧 Find evaluator 的 coverage 使用两个非对称覆盖率，其指标实现先按 Ochiai 分数做 Hungarian 再阈值过滤；主计划要求基于 IoU 的 covF1，以及在每个阈值二分图上求最大基数一对一匹配。这里只讨论 evaluator，不是 Stage2 Matcher。只能复用统计骨架，不能直接复用数学口径。
- 推荐每个测试集至少输出 PDB 宏 Dice、全局微 Dice、`covF1_iou03/iou05`、`1to1F1_iou03/iou05`、top3/4/5 命中数/eligible PDB 数/比例，并冻结空 GT、排序字段、tie-break 和 top-K 命中定义。
- 为避免 checkpoint 候选逐个调阈值，推荐在固定 validation 原图全 voxel 上以 non-interpolated `full_map_voxel_average_precision_micro_global` 选权重；该新指标仍须冻结 domain、AP variant、micro/macro、空 GT、score 同分与 checkpoint tie-break。
- 去冗余顺序：先冻结 train，再冻结 validation；二者内部按用户要求不去冗余；从剩余候选反向构造 test，先排除与 train/val 超阈值者，再在 test 内聚类选代表。多测试集必须互斥或显式记录交叠。序列来源、identity/qcov/tcov、PDB 多链传播、calibration 归属仍需用户冻结。

## 高成本存储/运行风险

- 每个 CLG 保存完整 `threshold_rank_map[80^3] uint8` 约 0.49 MiB；若每 PDB 300 个 CLG，约 146 MiB/PDB，约 2.2 万 PDB 时仅此字段可到约 3.2 TiB。selector 实际只需 parent voxels 的 rank，但当前 BOX 契约强制 dense map；稀疏 `rank_at_parent_voxel` 只能作为先 benchmark、再由用户批准正式收口的优化提案，实施前不能擅改契约。
- 以“PDB 数量 128”为单位缓存完整 exp/sim/grid 会失控；A–G 单图可很大，应使用字节预算 LRU、mmap/chunked reader，或按 PDB 调度。
- 全图概率与 add-on 应使用独立、原子、压缩的新 writer；不能直接改 A–G 现有明确使用未压缩 NPZ 的 helper。
- 首次居中物化应按 Group-parent 分组和去重相同几何请求，避免对同一中心框反复跑 Find；仍需保留多个逻辑候选身份。
- calibration 只冻结 F1/多阈值 recipe；之后必须对 OOF/in-sample/独立 downstream-train、val、calibration、各 test 的各自 `P_global` 生产 split-scoped proposal/materialization，不能只物化 calibration。
- OOF、formal in-sample、独立 downstream-train 都是待用户选择的下游 producer 路线；若希望保留第三种，必须在 Find train 冻结前预留该集合并从 Find train 排除。
- Stage2 测试统一使用 `gt_blind_regime ∈ {fully_gt_blind, spatial_overlap_gt_blind}`，并另记 candidate/count source 与 oracle side-information。Stage2 当前收敛设计规定 O 的密度档严格 `IoU>tau_O`、纯受体档严格 `distance<rho`；数值仍待定，正式实现计划需再提升为可执行契约。
- Stage2 phase2 权威冻结范围：冻 phase1 stem（含 repr seed）、前 m trunk 与前 m coarse；从头训后 n trunk，训练后 n coarse（含零初始化回吸门），fine 只在末块/末段训练。

## 主要证据入口

- 计划与契约：`文档/规划文档/Stage1训练实现计划.md`、`文档/规划文档/Stage1训练与多阈值推理.md`、`文档/讨论/BOX-level数据契约.md`
- 治理：`文档/mapping/计划执行映射.md`、`AGENTS.md`
- 数据执行：`文档/exec_plan/A-G数据流水线实现与全量运行.md`
- 项目记忆：`CLAUDE/memory/projects/adaligand.json`、`CLAUDE/memory/handoffs/`、`CLAUDE/memory/learnings/`
- 代码现实：Pocket Plus 的 `src/model/stage1_*`、`src/datasets/box_point_dataset.py`、`src/datasets/density_channel_builder.py`、`src/wrappers/voxel_point_stage1.py`、`src/train.py` 可作基线；AdaLigand 需新建 adapter/config/tests，不能把旧 `dataset/fused`、旧路径或旧损失配置视为已适配。

## 待核对

- 冻结 Find 的 head/loss 矩阵：C/P/P、P head、cross-attention、dense ligand、atom/core、voxel aux、pseudo P、sparse refine 各自是保留、训练、冻结、删除还是仅推理。
- 冻结初始化 checkpoint、优化器/调度器、precision/DDP、epoch/step、early stop、checkpoint 指标、seed 和 exact density channel order。
- 冻结 center/bias/context 数值枚举、离散舍入、box_id 并发/确定性方案，以及 train/val/calibration/test manifests。
- 已明确：Stage1 的“第二推理树网络”是 proposal selector，使用 independent-max；主规划的 Stage2 Matcher 是另一网络，使用 A/B/O 与身份内 Hungarian。仍待决定的是 Stage2 train 材料采用 out-of-fold、in-sample 还是独立 downstream-train Find producer。
- 完善全图 sliding-window 契约：stride/start、覆盖保证、logit/probability 聚合、`weight_sum` dtype、确定性累加/reduce 顺序与 `weight_sum==0` 处理；主计划已指定 probability accumulator/P_global 为 float32。
