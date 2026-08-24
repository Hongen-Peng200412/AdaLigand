# Stage1 第三版训练 I/O 与入口实施计划

本文是第三版 split、BOX pool 和迁移后 NPY 的训练消费主规格。统一 Dataset/Loader、模型输入接缝和训练入口已经收口；2026-08-24 的修订保持 V3 几何候选池不变，把活动训练与验证请求改为 PDB 中心采样。既有训练的参数和结果由各自执行记录解释，不属于本规划文档。新版推理算法属于独立时间节点。

## 已冻结前提

- 正式完整图根为 `/storage/penghongen/AdaLigand/Ori_Data`，第三版准备根为 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3`。
- split 要求首次 EMDB 发布时间 `< 2026-01-01`、`map_resolution < 4.0`、`cc_contour > 0.65`，并通过完整资产和三轴均不小于 80 的门禁。train、validation、calibration 分别为 13,717、200、100 个 PDB。
- V3 逐 PDB BOX 候选池保持不变。活动训练使用 `pdb_foreground_box_num=25`、`pdb_foreground_fraction_target=0.5` 与 `pdb_occurrence_foreground_box_cap=25`；验证以 seed 3407 从原 200 个 validation PDB 中无放回选择 150 个身份，并冻结相同规则的 epoch 0 到 `validation_selection_pdb_centric.npz`。原 `validation_selection.npz` 与 `config.json::entry_ratio` 只保留历史构建含义。第二版数据目录保留，不读取、不改写、不删除。
- 四个完整体数组已经迁移为同目录 `exp.npy`、`sim.npy`、`union_mask.npy` 和 `ligand_dist.npy`；NPZ 只保留小型元数据和逐 occurrence 稀疏字段。
- 训练继续全局打散 BOX 请求，不按 PDB 分组加载。

## 唯一 Dataset 与 Loader

- 活动代码只保留 `Stage1Dataset` 与 `Stage1BatchCollator`，不并存 `Stage1V3Dataset`。训练、验证、完整图与指定中心裁块共用同一套 80³ 物化逻辑。
- NPY 使用只读 `numpy.load(..., mmap_mode="r", allow_pickle=False)` 延迟打开。运行时只读取 NPY 头、小型 NPZ 元数据和实际 80³ 裁块；不在 mmap 缓存未命中时扫描完整图数值。
- 实际密度裁块必须有限；距离裁块必须有限且非负；union mask 保持 bool 语义。完整数组逐值一致性由一次性迁移验收与 `_COMPLETE` 负责。
- Dataset 返回 `atom_feat: float32 (N,49)` 与 `atom_is_backbone: bool (N,)`，不修改 `receptor_tokens.npz`。模型输入边界根据期望特征维数决定是否拼成 50 维，并继续兼容旧 49 维模型。
- 完整删除 `box_sample_fraction` 构造参数、请求持久化、Hydra 字段、测试和活动说明。
- 训练请求按 manifest 中的 PDB 顺序生成。一个含 `O` 个 occurrence 的 PDB 每个 epoch 使用 `min(25, 25O)` 个 bias；正式 pool 的每个 PDB 至少含一个 occurrence，因此实际 bias 固定为 25。bias 尽可能均匀分配到全部 occurrence，不能整除的余数按 epoch 轮转；context 同样固定选择 25 个。
- DataLoader 固定 `pin_memory=true`、`prefetch_factor=4`、`persistent_workers=false`。`Find_1.sh` 的双卡任务申请 64 CPU，每个 DDP rank 使用 30 workers；其他当前 Stage1 入口每个 rank 使用 16 workers。

## 模型与一键入口

- `protein`、`nucleic` 与 `distance` 三个结构预测头继续由既有总开关创建，不新增独立 head 开关。
- `unet_c1/mainchain` 使用单卡 H100、16 CPU/16 workers，三项损失权重为 `0.05/0.05/0.3`。
- `unet_c1/no_mainchain` 使用双卡 H100、总计 32 CPU/32 workers，保留三个结构头，把 protein/nucleic 权重设为 `0.0/0.0`，distance 保持 `0.3`；双卡配置使用 `ddp_find_unused_parameters=true` 处理两个零权重头。
- `Find_0/CPC1` 与 `Find_1/CPC1` 只启动 CPC1，不自动串联 CPC2。双卡 Find_0 每个 rank 使用 16 workers；双卡 Find_1 申请 64 CPU，每个 rank 使用 30 workers。
- 正式入口为 `训练与运行/sh/Find_0.sh`、`Find_1.sh`、`unet_base.sh`、`unet_c1.sh`、`unet_diff.sh` 和薄包装 `unet_c1_no_mainchain.sh`。旧 `train_2/`、`train_3/` 副本从活动树删除。
- 当前 PDB 中心采样入口统一使用 `max_epochs=70` 和 `warmup_ratio=0.005`。Find_0 每个 epoch 执行 10 次完整 validation，相邻验证事件之间约有 68,585 个训练 BOX；Find_1 与三个 U-Net 入口每个 epoch 执行 12 次，相邻验证事件之间约有 57,154 个训练 BOX。每次活动 validation 固定读取 150 个 PDB 的 7,500 个 BOX。Stage1 CPC1 与 CPC2 的 `ReduceLROnPlateau` 都采用绝对改善阈值 `0.003`；该阈值不修改 Selector 的独立优化参数。

## 删除与依赖迁移

- `src/datasets/ops/stage1_split.py`、`stage1_box_pool.py`、`ops/box_pool_2/` 和旧 materializer 只通过 Git 历史阅读。
- V3 数据准备仍需的 occurrence mask、确定性 PDB seed、bias/context 起点和 validation selection 冻结函数集中到 `ops/stage1_data_preparation/utils/`。
- 推理 PDB 清单脚本改用 `src.datasets.stage1_requests.load_split_pdb_ids`，并读取 V3 split；该解析器对候选记录级 JSON 按 PDB 首次出现顺序去重。
- `Make_Data/`、`Bundle_of_Maps/`、`processedPDB_EMDB_binder/` 与旧 `Docking/` 退出活动树，历史内容由 Git 保存。

## 验证与放行

- 本地测试覆盖 PDB 中心请求、epoch 轮转、bias 不足时保持 context 目标、冻结验证字段、mmap 延迟读取、80³ 裁块数值检查、Hydra 配置和推理兼容。
- 五个正式 shell 入口执行 `bash -n`；代码执行全量 pytest 与 `git diff --check`。
- 主代理先逐文件检查全部新增或修改函数的职责、位置、调用关系、嵌套、Docstring 和科学变量注释。随后分别由代码布局与 Git 双线、中文代码注释、科学逻辑三类独立审查者完成三轮全面核查；三轮之后只对已报告问题做窄口径复核。
- 用户已经取消本轮服务器 smoke 前置要求。本次 PDB 中心采样修订完成代码、测试、审查、说明和 Git 双线即可收口，不启动或重启 GPU 训练；既有训练证据继续由对应执行记录维护。

## Git 与任务边界

- 原训练 I/O 实现分支从 `8ff69abd608192d85686f73da2d1f9f15fe67a1e` 建立。2026-08-24 的 PDB 中心采样修订从当时唯一最新的 `Learn/CUMULATIVE` 建立独立实现分支，仍使用现有工作区，不另建工作树。
- 实现稳定后按人类理解顺序重建学习分支，核验实现端点与学习端点 tree 等价，再快进 `Learn/CUMULATIVE`。
- 不检查、不记录、不操作其他任务或服务器 allocation。未来训练如何占用资源，以用户届时明确授权和指定对象为准。
- 时间节点 1 验收后，当前任务才进入新版推理程序重构；hardmask、F-alpha、高斯打分、最低体素阈值、Selector 和 CLG 精简等科学契约届时另行确认。
