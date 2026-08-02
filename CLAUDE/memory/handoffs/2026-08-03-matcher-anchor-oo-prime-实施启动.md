# Matcher Anchor O/O′ 实施启动

## Current State

用户已经授权端到端实施不依赖 Stage1 推理产物的 Matcher，但正式服务器训练提交仍需在 YAML 和 `.sh` 完成后再次授权。实现分支为 `codex/matcher-anchor-oo-prime`，基点为 `Learn/CUMULATIVE@35d3e0e`。

当前科学与工程决定的最高优先级来源是 `grill_with_memory/07-28-17-50.md` 的 Question 1–105。三份早期讨论稿仍提供背景，但其中与最新账本冲突的 Stage1/P/V/PP/A/B、PairFormer、旧粗细拓扑和旧 batch/loss 定义均不得进入首版。

## Completed

- 重新核对 Git、正式数据资源、五份计划/事实文档和 Question 1–105。
- 建立 `文档/规划文档/Matcher_Anchor_OOPrime实施计划.md`。
- 建立活动执行记录 `文档/exec_plan/Matcher_Anchor_OOPrime端到端实施.md` 并更新计划映射。
- 建立 `matcher/README.md`、`talk/Matcher_输入与产物概览.md` 和 `talk/Matcher_模块结构概览.md`，冻结当前 Anchor 路线与未来 Stage1 路线的隔离边界。
- 两个只读审查分别完成契约漂移和代码可读性基线检查，没有修改代码或服务器。

## Frozen Implementation Boundaries

- 当前数据入口只有 `AnchorPocketDataset`；未来 Stage1 数据入口必须新增文件，不能在当前入口增加 `mode/has_stage1`。
- 当前受体模态只有 A，Map 只产生 `Map_repr`；不实现 P/V/PP、Map 点头、A/B 或 Stage3。
- 配体与 A 使用同构 GatedGCN 算法和图字段，但权重不共享。
- 模型含 8 个 Block，Phase1 为 4 个完整实体 Block + 4 个 coarse-only Block；Phase2 冻结前四 Block，以独立原始 stem 为后四 Block 增加实体路径，正式细分支只在 Block8。
- O/O′ 的 decoder/evaluator 独立命名；未来 A/B 新增独立实现。
- 代码不得建立通用多模态框架、注册器、Trainer/Callback 层级或散落的防御性校验。

## Next Actions

1. 实现正式实验清单、Anchor 数据入口和 occurrence-budget 装箱。
2. 实现 Map、图层、粗模型和 Phase1 目标函数。
3. 实现 Phase2 独立 stem、细分支、辅助监督和严格 checkpoint 接力。
4. 实现训练、验证、解码、恢复、显存画像和正式脚本。
5. 本地测试后在有余量的 A100/A800 做隔离 smoke；A800 首轮显存上限示例为 72 GiB。
6. 正式 YAML/`.sh` 准备完成后请求用户授权提交完整训练。

## Files To Reopen

- `grill_with_memory/07-28-17-50.md`
- `文档/规划文档/Matcher_Anchor_OOPrime实施计划.md`
- `文档/exec_plan/Matcher_Anchor_OOPrime端到端实施.md`
- `matcher/README.md`
- `talk/Matcher_输入与产物概览.md`
- `talk/Matcher_模块结构概览.md`
- `文档/mapping/计划执行映射.md`
