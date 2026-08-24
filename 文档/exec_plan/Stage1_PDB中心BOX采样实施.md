# Stage1 PDB 中心 BOX 采样实施记录

本文记录 `文档/规划文档/Stage1第三版训练IO实施计划.md` 与 `文档/规划文档/BOX-level数据契约.md` 在 2026-08-24 的 PDB 中心采样修订。实施范围包括 Pocket_Plus 的请求生成、冻结验证选择、Dataset 配置、五个训练入口、测试、两仓库文档和 Git 双线；不启动或重启 GPU 训练。

## 实施边界

- 复用 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/box_pool` 的逐 PDB bias/context 候选池，不建立 `box_pool_v4`。
- 不修改原逐 PDB NPZ、`manifest.json`、`validation_selection.npz`、`config.json`、`summary.json` 或 `_COMPLETE`。
- 新增唯一正式数据产物 `validation_selection_pdb_centric.npz`，用于冻结从原 200 个 validation PDB 中无放回随机选择的 150 个身份及其 epoch 0 请求。
- 冻结脚本保留在 Pocket_Plus `ops/stage1_data_preparation/`，固定正式路径、seed 3407、150 个 PDB 与 `25/0.5/25` 参数，不提供参数化命令行。
- 不检查、取消、重启或提交任何 GPU Job。

## 科学与训练参数

- `pdb_foreground_box_num=25`：每个 PDB 的目标 bias BOX 数量。
- `pdb_foreground_fraction_target=0.5`：bias 占目标 bias 与 context 总数的比例。
- `pdb_occurrence_foreground_box_cap=25`：单个 occurrence 每个 epoch 最多获得的 bias BOX 数量；该值等于每 PDB 目标 bias 数量。
- 一个含 `O` 个 occurrence 的 PDB 实际使用 `min(25, 25O)` 个 bias。正式 pool 的每个 PDB 至少含一个 occurrence，因此实际 bias 固定为 25；这些 BOX 尽可能均匀分到全部 occurrence，余数分配逐 epoch 轮转。
- 每个 PDB 固定使用 25 个 context。正式 V3 train 与 validation 的每个 PDB 都有超过 25 个 context 候选。
- 五个入口的 `max_epochs` 都保持 70，`warmup_ratio` 保持 0.005。Find_0 每个 epoch 验证 10 次；Find_1、unet_base、unet_c1 与 unet_diff 每个 epoch 验证 12 次。

## 已实现代码

- `src/datasets/stage1_requests.py` 不再读取 `config.json::entry_ratio`，按显式 PDB 中心参数生成每个 epoch 的 bias/context 请求，并保留 manifest PDB 顺序。
- `src/datasets/stage1_dataset.py` 接收三个采样参数；四份活动 Dataset YAML 显式设置 `25/0.5/25` 并改读 `validation_selection_pdb_centric.npz`。
- `ops/stage1_data_preparation/freeze_validation_selection_pdb_centric.py` 复用生产请求类生成全部 validation epoch 0 请求，以 `SeedSequence(3407, spawn_key=(2,))` 的独立随机域无放回选择 150 个 PDB，并原子写入八类既有索引数组与三个采样参数标量。
- `Find_0.sh`、`Find_1.sh`、`unet_base.sh`、`unet_c1.sh` 与 `unet_diff.sh` 已同步新的 epoch 与 validation 预算；既有 batch、学习率、worker 和其他科学参数保持不变。

## 最终验证证据

- 主代理按文件顺序逐一检查每个新增或修改函数的职责、位置、调用关系、嵌套、Docstring 和科学变量注释。自审发现按文件路径执行硬编码脚本时，项目根目录不会自动进入 Python 搜索路径，因此正式命令改为模块调用 `python -m ops.stage1_data_preparation.freeze_validation_selection_pdb_centric`；没有增加 CLI 参数或第二个入口。
- 最终定向回归 50 项通过。除共同基点已经失效的 `tests/test_stage1_producers.py` 外，Windows 全量回归为 345 项通过、11 条 warning，耗时 140.68 秒。该遗留测试在共同基点 `8561d2790614a0d92f0ad88ebce241a9f1c77ba3` 上同样因不存在的 `src.artifacts` 包而在收集阶段失败，本轮没有扩大范围修复。
- Python 编译检查、`submit_task.sh` 与五个训练 Shell 的 `bash -n`、两个仓库的 `git diff --check` 均通过。对 occurrence 数量 `O=1..1000` 的独立数学审计确认每个 PDB 分配总数为 25、任意两个 occurrence 的分配数之差不超过 1、单个 occurrence 不超过 cap 25，完整轮转周期内累计分配相等。
- 最终 `25/0.5/25` 与 150 PDB 版本已用硬编码模块命令覆盖发布。文件包含 150 个 PDB、3,750 个 bias、3,750 个 context 和 0 个 center 请求，共 7,500 个验证 BOX；每个 PDB 恰好包含 25 个 bias 与 25 个 context。逐字段 dtype、shape、候选索引范围、PDB manifest 顺序和逐 PDB 计数均通过服务器核验。
- 第三轮逻辑审查发现原 PDB 子集随机种子与第 3 个 manifest PDB 的 occurrence 排列随机状态碰撞。验证 PDB 选择改用 `SeedSequence(3407, spawn_key=(2,))` 后，最终冻结集合相对碰撞版本保留 116 个身份并替换 34 个身份；该中间版本未用于训练。回归测试精确锁定 seed、spawn key、四 PDB 夹具选择结果和验证随机状态与 200 个 PDB 的 occurrence/candidate 随机状态互不相等。
- `validation_selection_pdb_centric.npz` 最终大小为 71,150 字节，SHA-256 为 `546ebd3a1f07b230af42911b6740f466c6af289c8bff91a387c4eb8b1d69dd8e`；重复执行正式命令后哈希不变。原 `validation_selection.npz`、manifest、config、summary 与 `_COMPLETE` 的修改时间和 SHA-256 均未变化。
- 代码布局与 Git、中文注释、科学逻辑三类独立审查各完成三轮全面核查。每轮意见均先整改再进入下一轮；第三轮后的三类窄口径复核全部为 `APPROVED`，没有继续扩大审查范围。正式 Find_1 说明统一为双卡 64 CPU、每 rank 30 workers；Find_0、unet_base、unet_c1 与 unet_diff 的资源说明和五个入口的训练预算均由配置测试锁定。
- 本轮没有检查、提交、取消、重启或修改任何 GPU Job。Pocket_Plus 实现端点 `01888bf6ae1a1aa0b936114ef0569c5fe54cbd5c` 与学习/累计端点 `752159b5ca2460227cebb429dcd7142b1b0c6292` 的 tree 均为 `a538e6aae01ce24a45a740ca0193d465dcf9c5dc`；AdaLigand 同样从原累计基点按最终文档树重建学习线，并在推进 `Learn/CUMULATIVE` 前执行 tree 与路径级等价核验。

## 计划与实现差异

- 采用用户最终决定的 `25/0.5/25`，没有沿用讨论初期的 foreground 目标 30。
- cap 与目标 bias 数量相同，因此对至少含一个 occurrence 的正式 PDB 不减少 bias；每个 PDB 固定使用 25 个 bias 和 25 个 context。
- 没有新建完整 `box_pool_v4`，也没有给一次性脚本添加 CLI、通用 schema、策略字符串、冗余计数、候选不足回退或额外验证框架。
- `warmup_ratio` 保持用户冻结的精确值 0.005，没有为了数值拟合改成近似值。
- 有害差异：截至当前未发现。
