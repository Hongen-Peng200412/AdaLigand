# Matcher Anchor O/O′ 端到端实施记录

## 职责与权威来源

本文按过去时持续记录本轮 Matcher 实施中的代码落点、验证证据、实际偏差和服务器运行状态。它不重新定义科学契约。最新决定以 `grill_with_memory/07-28-17-50.md` 的 Question 1–105 为最高优先级，执行规格见 `文档/规划文档/Matcher_Anchor_OOPrime实施计划.md`。

## 当前状态

- 状态：实施中。
- Git 基点：`Learn/CUMULATIVE@35d3e0e`。
- 实现分支：`codex/matcher-anchor-oo-prime`。
- 正式服务器提交：尚未授权；只允许完成实现、测试、隔离 smoke、显存画像和正式脚本准备。

## 2026-08-03：实施启动

已完成以下启动检查：

- 确认 `Learn/CUMULATIVE` 位于仓库按提交者时间形成的唯一最新提交，工作区清洁后创建实现分支。
- 重新核对五份事实/计划文档和 Question 1–105。最新账本覆盖旧计划中关于候选采样、粗分支微观结构、Phase2 接力、细分支、辅助监督和 O/O′ 解码的冲突描述。
- 确认 `matcher/` 在 HEAD 中没有正式源文件，因此本轮从清楚的职责边界开始，不兼容历史 Matcher 代码。
- 确认当前正式数据清单、BOX pool、配体对象、真实配体坐标、受体图和实验密度均已存在，可支持 Anchor 路线训练。
- 冻结可读性边界：当前路线使用显式 `anchor_data.py` 与 `oo_prime.py`；不创建 Dataset/decoder 工厂、模态注册器、Trainer/Callback 层级或 `utils.py`。

## 计划中的验证证据

后续每完成一个阶段，在本节追加实际命令、通过数、真实样本、GPU 型号、峰值显存、checkpoint 接力结果和发现的偏差。临时 smoke 产物只进入 `tmp/`；正式清单、YAML、shell、checkpoint 和评估结果使用各自正式目录。

## 开放门槛

1. 完成本地实现与 CPU 测试。
2. 完成真实数据读取和单步 forward/backward。
3. 在空闲 A100/A800 上完成隔离 smoke。
4. 使用完整 Phase2 训练步和用户指定的 90% 显存上限完成 U-Net 通道画像。
5. 准备正式 YAML 和 `.sh`，向用户报告后请求正式提交授权。

## 2026-08-03：本地实现第一轮闭环

已经建立当前 Anchor 路线的正式数据、模型、目标函数、训练和 O/O′ 推理骨架：

- `matcher/anchor_manifest.py` 一次性生成版本化实验清单；`AnchorPocketDataset` 只读取该清单和完整 BOX 池。训练期先固定本 epoch 的 synthetic-anchor 候选、跳过零候选 PDB，再交给 occurrence 预算装箱。
- `MatcherBatch` 沿候选轴打包 Map，并分别打包配体图与 A 图；集合注意力仍在模型主前向中按 PDB 显式隔离。
- 模型包含可配置的 4+4 个 Matcher Block、小型 48³ U-Net 与四尺度 `MapSummaryHead`、PocketXMol 式节点—边联合更新、八个独立 O/O′ 预测头，以及 Phase2 独立 stem、可选零初始化 `FiLM_plus`、FinePair 分支和两类辅助头。
- FinePair 原子辅助监督保存为 `[C,S_pred,S_gt]`，先完成最终 O/O′ Hungarian，再选择预测槽位实际分配到的真实 occurrence，避免同身份槽位编号泄漏。
- 训练入口支持每 epoch 五次完整验证、同构 O/O′ decoder/evaluator、全状态断点恢复、原子发布 checkpoint 与 BEST、BF16、AdamW、warmup-plateau 和两阶段 model-only 接力。
- 当前 profile YAML 只是通道画像起点，正式训练 YAML 尚未生成；正式服务器训练仍未获授权。

第一轮契约审查发现的七项阻断偏差均已修正：FinePair 对齐、正式 O 的 focal+Dice 权重、PocketXMol 节点消息、Phase2 冻结模块 `eval`、零候选过滤后装箱、Block 数可配置、Map 显式配置和立即失败。随后又补齐了 batch 打包、图边更新消融开关、训练历史最佳值恢复和来源清单身份记录。

本地验证命令：

```text
D:\Anaconda\envs\Pocket_Plus_windows\python.exe -m pytest matcher/tests -q
```

第一轮结果为 26 项通过；覆盖 Map 与 FinePair activation checkpoint 等价、FinePair 普通分块与 checkpoint 分块的输出和梯度等价、Phase2 冻结后 Map 梯度穿透、重复身份槽位交换、正式 O 损失、严格 Phase1→Phase2 加载和 occurrence 装箱。

下一道门槛是第二轮双审查、服务器环境与 18 Å 数据统计核对、真实样本 CPU 预检、隔离 GPU smoke 和显存画像。所有 smoke 与画像产物继续进入 `tmp/`；正式清单不得进入临时目录。

## 2026-08-03：数据边界与运行依赖收紧

第二轮审查后完成以下收紧：

- 图编码改编已逐项对齐 PocketXMol 的 gated edge-message 公式；补充上游 MIT 许可全文和版权声明。
- 图编码改为先打包 batch 内互不连边的图，再在每个 Block 后按 PDB 切回粗分支；打包与逐 PDB 前向的数值等价测试通过。
- 零候选 PDB 现在只存在于 `prepare_epoch` 的样本收集边界。sampler 只接收 `available_indices`；`AnchorSample`、collate、训练、验证、推理和显存画像都不再接受 `None`。
- 新增字段级自包含契约 `文档/规划文档/Matcher_Anchor_OOPrime数据契约.md`。Dataset 会立即核对实验清单的 `schema_version`、`route` 和六项候选抽样参数；清单同时记录来源 BOX manifest 与 config 的 SHA-256。
- 服务器 Torch 环境缺少 `gemmi`。为避免修改共享环境，使用既有 `AdaLigand_stage1_py310` 环境只读导出 0–127 号元素的四项属性，并固化到 `matcher/element_properties.py`。运行时不再依赖 Gemmi；后续真实数据 smoke 仍需逐字段对照原实现。
- O/O′ 独立评估改为使用 checkpoint 冻结阈值，不在测评时重新扫描；TP/P/G 增加一个未初始化时直接返回的可选分布式汇总边界。
- 断点恢复保存历史最佳 F1/阈值，并在恢复到已经完成第三次降学习率的 checkpoint 时立即正常结束。DataLoader 使用独立随机生成器，不消费模型的全局随机流。

本地验证命令保持不变，最新结果为 33 项通过，`python -m compileall -q matcher ops` 与 `git diff --check` 同时通过。第三轮契约与可读性审查已经闭合；审查确认数据、模型、训练和可读性没有剩余提交阻断项。
