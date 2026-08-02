# Matcher

本目录实现 AdaLigand Stage2 Matcher。首个正式版本只包含不依赖 Stage1 推理产物的 Anchor 路线、受体原子模态 A 和 O/O′ 输出。

## 当前公开边界

- 数据入口：`AnchorPocketDataset`。候选来自已有 bias/context 池，验证候选关系由正式清单冻结。
- 模型入口：`Matcher`。输入是已装配的配体图、候选 A 图、候选中心 48³ Map、PDB/候选/occurrence 索引和可选辅助标签。
- 目标函数：按配体身份执行 Hungarian，对 O 与 O′ 共用分配；辅助任务只在权重大于零时构造。
- 当前解码：`OOPrimeDecoder`。允许 slot 拒绝和候选复用；不执行 A/B merge/split 推理。
- 当前评估：`OOPrimeEvaluation`。完整验证集上扫描全局 O 阈值，以 occurrence 级 F1 选择 checkpoint。

字段级输入、清单、内存张量与 batch 约束见 `文档/规划文档/Matcher_Anchor_OOPrime数据契约.md`。

模型不得读取 `bias/context` 来源标记。真实 occurrence 配体坐标只生成标签，不能进入模型输入。A 允许为空；零候选 PDB 已在样本收集边界剔除。

未来 Stage1 推理产物使用新的数据与推理入口，不在 Anchor 文件中加入模式分支。未来 A/B 使用独立 decoder/evaluator，不改变当前 O/O′ 的阈值和正确性定义。

## 配置与运行

正式配置位于 `configs/matcher/`，训练入口为 `python -m matcher.train`。本地或服务器 smoke 产物必须写入 `tmp/`；正式运行通过 `训练与运行/sh/matcher/` 的薄脚本调用项目通用任务提交系统。正式服务器训练需要用户在审阅 YAML 与 `.sh` 后单独授权。
