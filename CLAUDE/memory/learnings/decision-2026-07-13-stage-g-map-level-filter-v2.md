# Stage G 只保留 map-level filter schema v2

Type: decision
Date: 2026-07-13
Tags: stage-g, map-filter, q-score, cc, data-contract

## Context

Stage F 已为每个 occurrence 保存配体 `q_score`、6 Å 口袋 `pocket_q_score`、`pocket_status`，并在同一 PDB 各行重复四种全局 CC 和 `map_resolution`。Stage G 的旧 occurrence 级过滤从未正式运行，也没有生成需兼容的 `keep_list` 或下游消费者。

## Memory

Stage G 只接受唯一 `schema_version=2` 的 map-level 配置，不保留 v1 兼容分支。G 直接消费 analyze 阶段扁平化的 F 字段，不读取原始密度图、`quality_atoms`，也不重新运行 CC、MapQ 或 Q-score。

每个 eligible PDB 必须至少有一个 occurrence；正式流水线中的零 occurrence 会由 D/E/F 先分类为 `known_failed:no_occurrences`。同一 PDB 的 `map_resolution` 与配置选中的唯一 CC 必须在所有 occurrence 行中一致。

对每个 occurrence：

```text
pair_pass = (q_score > ligand_q_min) AND (pocket_q_score > pocket_q_min)
```

两个 Q 均严格大于阈值。空口袋 `pocket_q_score=null` 固定失败，但仍计入分母。map 的合格比例为 `n_pair_pass / n_occurrences`，只有 selected CC `>= cc_min`、resolution `<= resolution_max`、合格比例 `>= qualified_pair_fraction_min` 时通过。

一旦 map 通过，最终 `keep_list` 保留该 PDB 的全部 occurrence，包括自身 `pair_pass=false` 的行。pair 判定用于评价 map 整体质量，不用于通过 map 内的二次 occurrence 剪枝。选定 contour CC 合法为 null 时 map 失败，不回退到其他 CC。

用户给出的 `cc_all_about_mean/0.6/5.0/0.7/0.65/0.8` 目前只作为 schema 示例和候选数值，不是代码默认或服务器生产配置。正式 DAG 的 316117 继续 analyze-only；正式 filter 必须在分布完成后显式提供配置并保存 hash。

## When To Use

修改 `code/filtering.py`、解释 `keep_list`、编写 Stage G 配置、审计 map-level diagnostics，或在正式分布后准备 filter 时使用。不要恢复 occurrence 级 v1，也不要把 `pair_pass` 当成最终 occurrence keep 标记。

## Related Files

- `文档/规划文档/数据处理_v2.md`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/filtering.py`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `Data_Preprocessing/Ori_Data/learn.md`
- `Data_Preprocessing/Ori_Data/tests/test_filtering_stage_g.py`
