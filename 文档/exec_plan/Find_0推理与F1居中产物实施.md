# Find_0 推理、校准评估与 F1 居中产物实施

本 ExecPlan 是持续更新的执行记录。实施期间必须同步维护 `Progress`、`Surprises & Discoveries`、`Decision Log` 和 `Outcomes & Retrospective`。本文遵守仓库根目录 `AGENTS.md` 的项目入口规则；仓库没有另设 `PLANS.md`。

## Purpose / Big Picture

本任务要把已经完成训练的 Find_0 检查点接入 Pocket_Plus 现有 Stage1 推理管线。完成当前获准范围后，项目将具备以下可观察能力：

1. 使用指定 Find_0 检查点在 calibration 数据划分上生成完整图配体概率，冻结 `t_F1` 等校准阈值，并输出语义评估与实例评估。
2. 只生成 calibration、validation 和 train 的 `probability`、`components` 与 `F1_centered`，不必等待 `CLG_centered`。
3. 以后在同一产物根目录执行现有 `*-f1-clg` 命令时，已经完成的前三类产物保持不变，只补充 `CLG_centered`。
4. 人类可以从 `Pocket_Plus/训练与运行/sh/infer/` 直接阅读每个正式阶段的输入、参数、GPU 批量、分片和输出位置。

当前授权只覆盖代码审查、最小修复、测试、隔离 smoke、正式脚本编写和静态核验。完整 calibration、validation 和 train 的正式 Slurm 提交必须在上述工作完成后再次获得用户明确授权。

## Progress

- [x] (2026-08-03 03:05+08:00) 通过 `grill_with_memory/08-02-18-07.md` 冻结任务目标、模型身份、产物根目录、阈值参数、分片方式、smoke 范围和正式提交门槛。
- [x] (2026-08-03 03:20+08:00) 核验 Pocket_Plus `Learn/CUMULATIVE@ad4dde8` 是所有本地与远端引用中按提交者时间形成的唯一最新提交；当前及登记工作树均无未提交修改。
- [x] (2026-08-03 03:25+08:00) 为 AdaLigand 记录建立独立 `Learn/CUMULATIVE` 工作树，避免碰触主目录中正在进行的 matcher 任务。
- [x] (2026-08-03 04:20+08:00) 完成 Pocket_Plus 推理入口、运行器、产物契约 README 与任务提交器的逐文件审查。
- [x] (2026-08-03 04:31+08:00) 在 `codex/find0-inference-f1` 保存最小实现提交 `f4ef879`：延迟唯一的 Dataset 导入、把缓存上限改为 500 GiB，并增加三个 F1-only 命令。
- [x] (2026-08-03 04:36+08:00) Windows 推理与产物测试 41 项通过，组件、阈值与评估测试 32 项通过；完整测试 390 项通过、3 项基线配置测试失败。
- [ ] 把实现安全同步到服务器临时发布位置，使用一张当时可用 GPU 和真实 Find_0 检查点完成全链路 smoke。
- [ ] 验证异常退出后的 `_RUNNING` 清理、`_COMPLETE` 发布顺序、同命令续跑、同目录补跑 CLG 和目录碰撞保护。
- [ ] 记录完整图与居中推理在实际 GPU 上的批量、峰值显存和运行速度。
- [ ] 在 `Pocket_Plus/训练与运行/sh/infer/` 编写按独立阶段和实际 GPU 类型拆分的正式脚本，并完成 shell、路径、参数和任务提交器静态核验。
- [ ] 重建 Pocket_Plus 学习分支，核验实现端点与学习端点 Git tree 等价，再推进 `Learn/CUMULATIVE`。
- [ ] 回填本文、映射、检查记录和 CLAUDE memory，向用户展示正式入口并请求生产提交授权。

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

## Decision Log

- Decision: 只把 `src.datasets.stage1_requests` 的导入延迟到真实使用位置，不改变快照校验范围。
  Rationale: 这是解除错误导入顺序所需的最小修复，并继续保证模型、Dataset、wrapper、损失与工具只来自一套训练快照。
  Date/Author: 2026-08-03 / 用户与 Codex

- Decision: 正式推理缓存上限采用约 500 GiB；该值只是允许上限，不预先分配内存。
  Rationale: 计算节点约有 1 TiB 内存，避免完整密度图因 512 MiB 或 5 GiB 上限反复解压读取。
  Date/Author: 2026-08-03 / 用户

- Decision: 新增 calibration、validation 和 train 三个 F1-only 子命令；旧 `*-f1-clg` 命令保留，未来在同一输出根目录补齐 CLG。
  Rationale: 当前主线优先得到 F1-centered，又不能破坏后续 CLG 能力。
  Date/Author: 2026-08-03 / 用户与 Codex

- Decision: 当前正式阈值扫描显式使用 `min_voxels=15`、`max_voxels=2046`、`denominator=32768`；不把本轮运行参数机械改成所有实验的全局默认。
  Rationale: 运行身份应在正式脚本中一目了然，同时避免无意改变其他调用者。
  Date/Author: 2026-08-03 / 用户与 Codex

- Decision: 正式推理根目录固定为 `/storage/penghongen/AdaLigand_stage1_inference/Find_0-CPC1-ligand_PRAUC_0.675477/`，其中 `inputs/` 保存冻结输入与来源记录，`artifacts/` 作为推理输出根目录。
  Rationale: 同一检查点和契约的分批运行、失败重试与不同 GPU 类型可以安全汇入同一身份目录。
  Date/Author: 2026-08-03 / 用户

- Decision: 不预先固定 GPU 类型；smoke 后只为实际采用的 GPU 类型编写“独立阶段 × GPU 类型”脚本，分片编号由人手填写。
  Rationale: 可用卡会变化，简单显式的脚本比自动分片包装更容易核对和续跑。
  Date/Author: 2026-08-03 / 用户

- Decision: 正式生产提交保留第二次授权门槛。
  Rationale: 用户要先验收所有 smoke、最小修复、正式脚本和静态核验结果。
  Date/Author: 2026-08-03 / 用户

## Outcomes & Retrospective

最小实现和本地回归已经完成。Pocket_Plus 实现提交为 `f4ef879`；相关测试 73 项通过，完整测试中的三项失败已经证明属于当前分支缺少旧 CPC v3 配置的基线问题。服务器 smoke 尚未开始，第一次连接探测超时；没有申请 GPU，也没有提交正式推理。每个后续里程碑完成后继续补充实际结果、未完成内容与经验。

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
- 最终解析配置：`/home/penghongen/My_Project/tmp/adaligand_stage1_20260721T024000/allocations/321743/formal/Find_0_CPC1/launch_1/resolved_config.yaml`。
- 冻结训练代码：`/home/penghongen/My_Project/tmp/adaligand_stage1_20260721T024000/allocations/321743/runtime/My_Project/Pocket_Plus/`。

PDB 清单来自 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation/split/` 中的 `calibration.json`、`validation.json` 和 `train.json`。正式生产前把三份清单复制到正式根目录的 `inputs/` 并记录 SHA-256；实际推理只读这些冻结副本。

“F1-centered”表示对完整图概率在校准阈值 `t_F1` 上形成的每个合格组件，解析一个合法的 `80×80×80` BOX，并在该 BOX 内重新执行完整模型。“CLG-centered”表示对同一个组件谱系组解析 BOX 并重新执行模型。本轮只正式生成前者。

## Plan of Work

第一里程碑审查现有命令调用链、快照激活、Dataset 缓存、角色生成器、完成标记与测试。先写会暴露错误导入和缺少 F1-only 命令的失败测试，再进行局部修复。

第二里程碑在 Pocket_Plus 实现分支中完成三项最小修改：延迟唯一的 Dataset 导入；把命令行缓存默认值提升到约 500 GiB；让标准角色装配可以选择是否包含 `CLG_centered`，并增加三个直接调用既有运行器的 F1-only 命令。旧命令、产物字段和旧默认运行契约保持不变。

第三里程碑在 Windows 运行针对性和完整测试。随后用项目服务器交互工具把实现同步到隔离位置，借用一张当时空闲 GPU，在临时目录严格加载真实 Find_0 检查点。smoke 依次执行 calibration probability、阈值冻结、三个数据划分的 F1-only、同目录 CLG 补跑和再次续跑。

第四里程碑根据 smoke 的实际显存结果，在 `Pocket_Plus/训练与运行/sh/infer/` 编写只针对实际采用 GPU 类型的正式脚本。每个脚本只做一项工作，直接写出检查点、最终配置、冻结清单、数据根、输出根、分片总数、当前分片、缓存上限、批量和阈值参数。正式脚本不依赖 smoke 产物。

第五里程碑完成 shell 静态检查、任务提交器路径解析检查和双线 Git 重建。最后只向用户报告可提交的命令、脚本与 smoke 证据，不执行正式 Slurm 提交。

## Concrete Steps

在 `C:/Users/15919/Desktop/Pocket_Plus`：

1. 检查 Git 基点与工作树，随后从 `Learn/CUMULATIVE@ad4dde8` 建立实现分支。
2. 修改 `src/inference/runner.py`、`src/inference/cli.py`、对应测试和两份代码旁 README。
3. 使用本机 `Pocket_Plus_windows` Conda 环境运行推理测试，然后运行完整测试。
4. 使用 `与服务器交互` 的安全同步入口更新服务器共享源码；smoke 产物只写隔离临时目录。
5. 使用 `训练与运行/submit_task.sh --simple` 或等价的现有一次性入口申请一张 GPU，保留四锁，不创建正式推理产物。
6. smoke 完成后增加 `训练与运行/sh/infer/` 下的正式脚本，运行 `bash -n` 和任务路径解析测试。
7. 保存实现历史，按人类理解顺序重建学习历史，比较两个端点的 Git tree。

预期的正式生产顺序是：calibration probability 全部分片完成；单独冻结阈值；运行 calibration F1；人工核对 calibration；再并行运行 validation F1 和 train F1。该顺序只写入脚本和说明，当前不会实际提交。

## Validation and Acceptance

代码验收必须证明：

- 仅导入 `src.inference.cli` 不会提前导入 `src.datasets`，真实检查点快照可以随后激活。
- 三个 F1-only 命令的角色顺序分别是 `components,F1_centered` 或 `probability,components,F1_centered`。
- F1-only 完成后执行旧 `*-f1-clg`，已有文件内容和完成标记不变，只新增 CLG；再次运行返回跳过。
- 命令行未显式填写缓存值时得到约 500 GiB。
- 真异常非零退出，当前进程创建的 `_RUNNING` 被清理，未完成角色不出现 `_COMPLETE`。
- 真实 Find_0 权重严格完整加载，代表性 probability、components 和 F1-centered 满足两份产物契约；Find 的受体体素概率为零。
- 正式脚本不引用 smoke 目录，且分片、模型、配置、数据、输出和批量参数可独立读懂。

正式生产验收不属于当前授权。脚本和 smoke 全部通过后必须停下来请求用户确认。

## Idempotence and Recovery

所有 PDB 级命令复用现有 `_COMPLETE`：同一身份再次运行会跳过已经完成的角色。真正异常不会被改写成“跳过”或 `_BLOB_EXCEED`；修复后重跑同一分片即可继续。当前进程持有的 `_RUNNING` 会由上下文管理器在异常传播时释放；遇到历史残留租约时只人工确认进程已经退出，再删除那一个目录。

smoke 使用隔离临时根目录，不覆盖正式 A—G 数据、旧训练目录、检查点或正式推理根目录。正式推理根目录采用固定检查点身份，可跨 Job 和不同 GPU 类型续跑。任何正式提交前仍需用户授权。

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

Revision note (2026-08-03): 初次建立。根据 `grill_with_memory/08-02-18-07.md` 和用户最终授权，固定当前实施边界与正式提交第二道门槛。
