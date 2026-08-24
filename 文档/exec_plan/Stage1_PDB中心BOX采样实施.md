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
- `ops/stage1_data_preparation/freeze_validation_selection_pdb_centric.py` 复用生产请求类生成全部 validation epoch 0 请求，以独立随机流无放回选择 150 个 PDB，并原子写入八类既有索引数组与三个采样参数标量。
- `Find_0.sh`、`Find_1.sh`、`unet_base.sh`、`unet_c1.sh` 与 `unet_diff.sh` 已同步新的 epoch 与 validation 预算；既有 batch、学习率、worker 和其他科学参数保持不变。

## 当前验证证据

- 主代理逐文件逐函数检查职责、位置、调用关系、嵌套、Docstring 和科学变量注释后，Dataset、冻结脚本、训练配置与 Stage1 V3 推理兼容的主链回归为 72 项通过，Python 编译、五个 Shell 的 `bash -n` 与两个仓库的 `git diff --check` 均通过。
- 自审发现按文件路径执行硬编码脚本时，项目根目录不会自动进入 Python 搜索路径。正式命令因此改为模块调用 `python -m ops.stage1_data_preparation.freeze_validation_selection_pdb_centric`；没有增加 CLI 参数或第二个入口。
- 最终 `25/0.5/25` 与 150 PDB 版本的正式产物证据将在覆盖发布和服务器核验后写入本节。原 `validation_selection.npz`、manifest、config、summary 与 `_COMPLETE` 不属于覆盖范围；本轮不操作任何 GPU Job。
- 第一轮三类全面独立审查已完成。代码布局与 Git 审查要求补齐类分隔、五入口文档和配置覆盖；注释审查要求新代码统一 ASCII 标点、逐项字段说明和科学变量注释；逻辑审查确认采样与冻结算法正确，并指出活动资源说明仍残留 Find_1 的旧口径。整改后，正式 Find_1 说明统一为双卡 64 CPU、每 rank 30 workers，两个代码旁文档补齐 validation NPZ 的 11 字段表，五个入口的训练预算和配置测试保持一致。
- 第一轮整改后的 Stage1 Dataset、配置、冻结脚本、推理兼容和模型边界回归为 94 项通过；Python 编译、五个 Shell 的 `bash -n` 与两个仓库的 `git diff --check` 均通过。剩余两轮全面审查、最终全量测试和 Git 双线端点尚待本记录后续回填。

## 计划与实现差异

- 采用用户最终决定的 `25/0.5/25`，没有沿用讨论初期的 foreground 目标 30。
- cap 与目标 bias 数量相同，因此对至少含一个 occurrence 的正式 PDB 不减少 bias；每个 PDB 固定使用 25 个 bias 和 25 个 context。
- 没有新建完整 `box_pool_v4`，也没有给一次性脚本添加 CLI、通用 schema、策略字符串、冗余计数、候选不足回退或额外验证框架。
- `warmup_ratio` 保持用户冻结的精确值 0.005，没有为了数值拟合改成近似值。
- 有害差异：截至当前未发现。
