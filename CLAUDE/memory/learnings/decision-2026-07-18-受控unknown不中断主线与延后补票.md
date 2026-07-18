# 受控 unknown 不打断主线，并将“补票”异步化

Type: decision
Date: 2026-07-18
Tags: adaligand, gate, unknown-failure, run-scoped, recovery, scaffolding

## Context

AdaLigand A–G 的默认门禁会拒绝任何 `unknown_failed`。Stage F Phase-2 证明：即使失败原因已经逐例闭合、目标样本公开质量产物明确为 0/3、科学量不受影响，为了把 raw unknown 改写成原生 known，仍可能需要停 writer、修改分类器、远端测试、迁移 manifest，并对 no-overwrite 全集重放状态/validator；这类“状态闭合”累计消耗约 10 小时，却没有重算或改善已有合法 CC/Q 产物。

## Memory

后续 A–G 对少量、固定 ID、原因完全查清且影响可控的 unknown，优先采用 **run-scoped controlled-failure waiver（受控失败放行）**，而不是中断正在正常工作的 producer 或为状态改名重放科学计算。

waiver 的硬边界：

- 只限当前 run、当前 stage、逐 ID 精确匹配；当前用户授权 cap=100 是硬上限，不是可自动消费的配额。
- 原始 `unknown_failed`、错误、status 文件和状态分母保持不变；不得伪造 `known_failed` 或 `success`。
- 目标样本必须不再 in-flight，根因、工具/代码/attempt 身份、影响范围、公开产物 0/N 或 validator 结果、无活动 writer 都有不可变证据。
- 科学契约、算法、坐标、schema、来源、身份和兄弟样本可信度均不得存在未决风险；不得用裁图、默认值、容差放宽或占位产物换取通过。
- gate 与 G 必须显式消费同一受检 overlay，把命中项单列为 `waived_controlled_failures` 并排除训练、推理和 G 候选。只绕 release gate 不够。
- 未列 unknown、duplicate、silent missing/extra、schema/身份/manifest/SHA 漂移、partial/损坏产物、系统性增长趋势继续 fail-closed；strict smoke 不接受 waiver。
- 每批仍需独立取证和用户授权语义；不能按错误前缀、通配符或“剩余额度”自动扩张。

每条 waiver 至少绑定：`run_id/stage/pdb_id`、status 文件 SHA、canonical raw-row SHA、原始 status/reason/error、attempt/job/node/tool/code 身份、诊断证据 SHA、required-artifact 完整性快照、无活动 writer 快照、authorization、批次/累计数量与 cap、`scientific_contract_unchanged=true`、`no_placeholder_artifacts=true`、下游排除策略和退出条件。默认入口无 waiver 参数时必须保持原有严格行为。

“补票”是后续的一般化生产改进：在不停止当前 producer 的前提下，为无 PDB allowlist 的 failure classifier/adapter 补齐实现、测试和文档，使下一次 clean run 原生写 known 或真正成功。补票不是当前 release 的前置条件；完成后必须退休 run-specific 命令/ID 脚本，manifest/summary 只归档为历史证据。

## When To Use

- 长跑 stage 已接近 gate，仅有不超过授权上限的小批 unknown，且每项根因和下游安全都已闭合。
- 继续科学重算不会改善已有产物，只会重复 validator/调度开销。
- 需要在不停止当前 producer 的前提下并行准备 gate 开路和未来 clean-run 补票。

不要用于系统性失败、根因不明、共享文件污染、科学数值/坐标/schema/身份风险、仍有活动写者，或任何会让不完整样本进入训练/推理/G 的情形。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `Data_Preprocessing/Ori_Data/code/filtering.py`
- `Data_Preprocessing/Ori_Data/scripts/stage_release_gate.py`
- `CLAUDE/memory/learnings/pattern-2026-07-16-临时运行脚手架须在最终收口清理.md`
