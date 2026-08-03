# Matcher Anchor O/O′ 实施启动

## Current State

用户已经授权端到端实施不依赖 Stage1 推理产物的 Matcher，但正式服务器训练提交仍需在 YAML 和 `.sh` 完成后再次授权。当前实现分支为 `codex/matcher-server-smoke`；上一轮已闭合的累计基点为 `Learn/CUMULATIVE@12206cd`。

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
5. 对正式 YAML、正式 `.sh` 和画像结论完成双审查并再次闭合双线 Git。
6. 向用户展示正式入口与提交命令；只有用户明确授权后才提交完整训练。

## 2026-08-03 本地实现进展

当前实现已经覆盖 `matcher/anchor_manifest.py`、`anchor_data.py`、`batching.py`、`graph.py`、`map.py`、`model.py`、`objectives.py`、`consistency.py`、`oo_prime.py`、`train.py`、`infer_anchor.py`、两份 profile YAML 和独立显存画像入口。最新本地回归为 33 项通过，compileall 和 diff-check 同时通过；第三轮契约与可读性审查没有剩余提交阻断项。

第一轮契约审查的七项阻断问题已经全部处理。尤其需要续接者记住：FinePair 辅助损失现在是 `[C,S_pred,S_gt]`，必须在最终 Hungarian 后按 `loss[:, predicted_slot, assignment]` 选择；不得退回先绑定原始 occurrence 编号再重排列的错误实现。Phase2 每次进入训练模式后必须让冻结的 Phase1 子树保持 `eval`，但不能用覆盖整个粗前段的 `no_grad` 阻断 Map 梯度。

第三轮契约/可读性审查正在进行。零候选状态已完全收口到 `prepare_epoch`；正式实验清单会校验版本、路线和六项采样参数，并记录来源 BOX manifest/config 身份。字段级契约见 `文档/规划文档/Matcher_Anchor_OOPrime数据契约.md`。

服务器 Torch 环境没有 `gemmi`，当前实现没有修改共享环境，而是把既有 Gemmi 的元素属性只读导出到 `matcher/element_properties.py`。正式 Matcher manifest 已生成；A100 真实数据 smoke 已完成 Phase1→精确 BEST→Phase2→冻结阈值推理评估。真实运行额外修复了配体结构化数组非对齐字段复制和 BF16 细配对承载张量 dtype，两者均有回归测试，最新本地 Matcher 回归为 35 项通过。

上一轮本地实现与学习历史端点为实现提交 `e699a00`、学习提交和 `Learn/CUMULATIVE@12206cd`；真实数据 smoke 修复、画像入口和正式配置目前还在 `codex/matcher-server-smoke` 工作区，必须在正式提交授权前再次完成双线历史闭合。正式 manifest Job `334806`、A100 smoke Job `334808` 与 A800 profile Job `334813` 均已完成。

A800 Job `334813` 的初步画像使用了改变候选抽样种子的 128-PDB 临时清单，而且只覆盖 55 occurrence 的普通 batch；其中 `[40,80,120,160]` 得到 allocated/reserved 60.756/68.229 GiB，但该通道结论已经撤回。CPU Job `334816` 已选出 `9cpk`（64 occurrence、177 candidate、106044 A 原子）和 `9kdv`（100 occurrence、235 candidate、156743 A 原子）并固化临时候选快照。A100 全清单基线 Job `334810` 因 epoch 0 串行 I/O 达到 1 小时时限而 `TIMEOUT`，没有进入 GPU 测量。

重负载对照已经排除盲目缩小 U-Net、FinePair chunk 和 Map checkpoint：对应正常负载均在约 78 GiB OOM。新增等价的 `graph_activation_checkpoint` 后，正常负载两步画像成功，allocated 降至 68.072 GiB，但预热缓存使 reserved 仍为 76.545 GiB；正式测量步约 640 秒。A800 Job `334836` 加入 `expandable_segments:True` 后得到 68.037/76.025 GiB，仍未通过 72 GiB reserved 门槛。Job `334837` 进一步把 U-Net 调为 `[24,48,72,96]`，`9cpk` 的 allocated/reserved 为 48.870/56.670 GiB，已通过正常负载门槛。Job `334841` 用同一设置验收 `9kdv`，持续计算且未报告 OOM，但在 90 分 06 秒 `TIMEOUT`，没有结果 JSON。Job `334868` 只把相同画像的时限放宽到 2 小时 30 分，当前正重新运行。

正式配置为 `configs/matcher/anchor_O_O_prime_phase{1,2}.yaml`，正式入口为 `训练与运行/sh/matcher/train_anchor_O_O_prime.sh`，输出根为 `/storage/penghongen/AdaLigand/Results/matcher/anchor_O_O_prime_v1/seed_3407/`。该入口会完成 Phase1→精确 BEST→Phase2→精确 BEST→冻结阈值 validation 评估；当前正式候选通道为 `[24,48,72,96]`，shell 已导出与画像一致的 `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`。极端负载门槛尚待 Job `334868` 闭合，正式长训练也尚未获准提交。

可读性终审删除了未被单卡正式路线调用的分布式 TP/P/G 汇总边界及其 noop 测试，并删除 AdamW 从同一参数列表构造后重复执行的恒真校验。当前本地回归为 35 项通过，compileall、正式 YAML 模型构造和 `git diff --check` 均通过。Job `334868` 已按 Dataset 的 4 个 worker 把 CPU 请求从 16 降到 8，但仍被更高优先级的 5×A800/40 CPU Job 阻挡；不得提高优先级、直连占卡或操作他人锁。

## Files To Reopen

- `grill_with_memory/07-28-17-50.md`
- `文档/规划文档/Matcher_Anchor_OOPrime实施计划.md`
- `文档/exec_plan/Matcher_Anchor_OOPrime端到端实施.md`
- `matcher/README.md`
- `talk/Matcher_输入与产物概览.md`
- `talk/Matcher_模块结构概览.md`
- `文档/mapping/计划执行映射.md`
