# Handoff: Stage1 PDB 中心 BOX 采样完成

Date: 2026-08-25

## Current State

Stage1 活动训练请求已经从按整个候选池比例抽取改为按 PDB 分配。每个训练 PDB 每个 epoch 使用 25 个 bias BOX 和 25 个 context BOX；单个 occurrence 的 bias 上限为 25。正式 validation 候选池仍含 200 个 PDB，活动验证文件固定保存其中随机选择的 150 个 PDB，共 7,500 个 BOX。

服务器正式文件为 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/box_pool/validation_selection_pdb_centric.npz`，大小为 71,150 字节，SHA-256 为 `546ebd3a1f07b230af42911b6740f466c6af289c8bff91a387c4eb8b1d69dd8e`。原逐 PDB 候选池、`validation_selection.npz`、`manifest.json`、`config.json`、`summary.json` 和 `_COMPLETE` 均未改写。

## Completed

- Pocket_Plus `src/datasets/stage1_requests.py` 按 PDB 生成确定性 epoch 请求，bias 尽可能均匀分配到 occurrence，余数逐 epoch 轮转。
- 硬编码入口 `python -m ops.stage1_data_preparation.freeze_validation_selection_pdb_centric` 使用 `SeedSequence(3407, spawn_key=(2,))` 从原 200 个 validation PDB 中无放回选择 150 个身份，并保持 manifest 相对顺序。
- 四份活动 Dataset 配置、五个训练 Shell、训练预算和资源说明均已更新。Find_0 每个 epoch 验证 10 次；Find_1、unet_base、unet_c1 和 unet_diff 每个 epoch 验证 12 次；五个入口均为 70 epoch，`warmup_ratio=0.005`。
- 最终定向回归 50 项通过；除共同基点已经失效的 `tests/test_stage1_producers.py` 外，Windows 全量回归为 345 项通过、11 条 warning。Python 编译、Shell 语法和两个仓库的 `git diff --check` 均通过。
- 代码布局与 Git、中文注释、科学逻辑三类独立审查各完成三轮全面核查；第三轮后的三类窄口径复核均为 `APPROVED`。
- Pocket_Plus 科学实现端点为 `01888bf6ae1a1aa0b936114ef0569c5fe54cbd5c`，学习端点为 `752159b5ca2460227cebb429dcd7142b1b0c6292`，两端 tree 均为 `a538e6aae01ce24a45a740ca0193d465dcf9c5dc`。最终安全同步后的文件字节哈希由独立文档小周期记录，当前累计端点为 `718f9347215d42b696415f8c4b5a51717084f36e`。
- 本轮没有检查、提交、取消、重启或修改任何 GPU Job。

## Decisions

- 不建立 `box_pool_v4`；继续复用第三版逐 PDB bias/context 候选池，仅新增一个冻结 validation 文件。
- `pdb_foreground_box_num=25`、`pdb_foreground_fraction_target=0.5`、`pdb_occurrence_foreground_box_cap=25`。正式 PDB 至少含一个 occurrence，因此 cap 25 不减少每 PDB 的 25 个 bias。
- 验证 PDB 选择使用独立 `spawn_key` 随机域。原 `SeedSequence([3407, 2])` 会与第 3 个 manifest PDB 的 occurrence 随机状态碰撞；修正后的最终集合替换了中间集合中的 34 个身份，中间集合从未用于训练。
- 一次性冻结入口保留在 `ops/stage1_data_preparation/` 并硬编码正式路径和参数，不提供 CLI 参数。

## Next Actions

- 下一次正式训练应由新的冻结 release 读取 `validation_selection_pdb_centric.npz`；启动、重启或接管 GPU 任务仍须使用当次明确授权。
- 训练后如需比较 PDB 中心采样与历史 `0:5:5` 采样，应按各自 release 中冻结的配置和 validation 文件解释，不能混用指标口径。

## Files To Reopen

- `文档/规划文档/BOX-level数据契约.md`
- `文档/规划文档/Stage1第三版训练IO实施计划.md`
- `文档/exec_plan/Stage1_PDB中心BOX采样实施.md`
- `文档/mapping/计划执行映射.md`
- Pocket_Plus `src/datasets/stage1_requests.py`
- Pocket_Plus `ops/stage1_data_preparation/freeze_validation_selection_pdb_centric.py`
- Pocket_Plus `ops/stage1_data_preparation/EXECUTION.md`
