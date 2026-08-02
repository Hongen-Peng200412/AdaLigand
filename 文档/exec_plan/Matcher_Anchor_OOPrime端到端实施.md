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
