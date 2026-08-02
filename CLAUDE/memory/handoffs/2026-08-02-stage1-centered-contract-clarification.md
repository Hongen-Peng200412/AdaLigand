# Handoff: Stage1 centered 契约补齐与历史收口

Date: 2026-08-02

## Current State

AdaLigand 中与 Stage1 centered 归档相关的规划、讨论、映射和执行记录已经同步到新契约。本轮修改保留在未暂存区，动手前已有的暂存区树对象保持不变。Pocket_Plus 的实现、测试、代码旁文档、记忆和一对一历史重建均已完成；远端引用未修改。

## Completed

- `文档/讨论/BOX-level数据契约.md` 等文档补充 `A_feat_L0`、三类 centered 体素集合的来源、当前 centered 概率来源、局部与全局索引边界以及来源节点阈值语义。
- `semantic_dice_t_F1` 改名为 `semantic_dice_micro_t_F1`，并新增按 PDB 等权平均的 `semantic_dice_macro_t_F1`。
- `文档/exec_plan/Stage1代码实现.md` 追加本轮决定和验证事实，不改写历史段落。
- Pocket_Plus centered 契约的直接相关测试为 77 项通过；加入 `max_voxels=2046` 默认值与 component lineage 后，相关完整回归为 87 项通过；扩展测试另有 374 项通过。
- Pocket_Plus 历史候选覆盖 53 个受影响提交和 12 个本地分支；主端点树、父节点数量与顺序、提交主题均通过核验，最终没有增加提交或分支。

## Decisions

- Find centered 归档直接保存 `float32 (L_A,49)` 的 `A_feat_L0`，顺序与 `A_global_index` 对齐。
- Selector 不再二次读取 `receptor_tokens.npz/feat`，`upstream_root` 只继续提供实验密度。
- 不修改 Stage1-Find 模型或配置中的现有前向结构；不提供旧归档兼容或迁移逻辑。
- 单个 PDB 的语义 Dice 分母为零时，宏平均中的该项记为 `0.0`。
- `max_voxels` 使用全量 `Q95=682` 的 3.0 倍并向上取整，当前正式值为 `2046`；历史记录中的 `1023` 仅表示此前采用的 1.5 倍初始值。
- Pocket_Plus 一对一历史重建已经完成，提交数量和分支拓扑保持不变。

## Open Questions

- Pocket_Plus 全量测试的既有环境缺口是否另行处理：缺少 `.project-root`，以及缺少 CPC v3 配置文件。

## Next Actions

1. 正式 Stage1 推理开始前，使用当前 `max_voxels=2046` 运行 calibration 与组件生产。
2. AdaLigand 的本轮文档与记忆改动继续留在未暂存区，由用户决定后续处理方式。

## Files To Reopen

- `文档/讨论/BOX-level数据契约.md`
- `文档/exec_plan/Stage1代码实现.md`
- `文档/mapping/计划执行映射.md`
- `../Pocket_Plus/src/inference/centered.py`
- `../Pocket_Plus/src/selector/dataset.py`
- `../Pocket_Plus/src/evaluation/calibration.py`
- `../Pocket_Plus/src/artifacts/readme.md`
- `../Pocket_Plus/CLAUDE/memory/handoffs/2026-08-02-stage1-centered-contract-clarification.md`
