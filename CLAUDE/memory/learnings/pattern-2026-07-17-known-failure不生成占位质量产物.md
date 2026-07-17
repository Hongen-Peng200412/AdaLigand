# Known failure 不生成占位质量产物

Type: pattern
Date: 2026-07-17
Tags: AdaLigand, artifact-completeness, known-failure, Stage F, Stage G

## Context

正式 run `adaligand_ag_20260711T154658` 的六个大网格样本已由独立单进程和 fresh ALL 证据证明会稳定触发 Chimera signal 11。用户授权把它们记为当前 run 的 `run_policy_excluded:chimera_full_grid_cc_signal11`，但特别强调“排除”不等于生成伪装式质量产物。

## Memory

- 对不能形成真实科学量的 known failure，只在 run-scoped status、manifest 与审计证据中记录真实失败；不要创建空 JSON、默认值 NPZ、全 null 记录或其他占位质量产物。
- 样本可继续留在阶段状态分母中，以便总数守恒和失败率可审计；训练、推理和后续候选生成则通过“要求公开产物集合完整且逐项通过 validator”自然排除。
- 对 Stage F，公开质量产物集合是 `quality/{pdb_id}.jsonl`、`quality/{pdb_id}.provenance.json`、`quality_atoms/{pdb_id}.npz`。本次六例必须保持 0/3，而不是伪造 3/3。
- status 中的 `known_failed` 和产物缺失表达两个互补事实：前者说明失败已分类且不是 silent missing，后者保证任何简单完整性过滤都不会误把样本纳入训练、推理或 G。
- 只有科学契约明确规定的“合法空值”才能写入真实产物，例如 schema v3 的空口袋 `null/status`；外部工具没有产出完整质量结果时，不能借合法空值语义伪装完整样本。

## When To Use

在任一阶段需要把已取证失败保留在状态宇宙、同时确保下游可按产物完整性自然排除时使用。若失败应当产生部分真实产物，必须先由对应 artifact schema 明确允许，并保证 validator 不会把部分产物误判为完整成功。

## Related Files

- `Data_Preprocessing/Ori_Data/code/readme.md`
- `Data_Preprocessing/Ori_Data/code/quality.py`
- `Data_Preprocessing/Ori_Data/scripts/f_signal11_exclusion_transition.py`
- `Data_Preprocessing/Ori_Data/scripts/stage_release_gate.py`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `CLAUDE/memory/learnings/decision-2026-07-17-stage-f六大图run-only排除与上限30.md`
