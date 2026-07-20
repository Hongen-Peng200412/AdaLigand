# Stage F 45 条受控失败 waiver 与 cap200

Type: decision
Date: 2026-07-20
Tags: AdaLigand, Stage F, controlled-failure waiver, gate, Stage G, run-scoped operations

## Context

正式 run `adaligand_ag_20260711T154658` 的 Stage F producer 已完成 22,386/22,386，但严格 release gate 因 45 条 `unknown_failed` 停在精确 try-lock。45 条公开质量三件套均为 0/3，且已确认没有活动 F/Loky/Chimera/MapQ writer 或共享产物污染。它们与既有 19 条 `known_failed:run_policy_excluded` 不重叠。

## Memory

用户明确批准对这 45 条使用当前 run 专属的 controlled-failure waiver：

- raw status、reason、error、状态分母和 0/3 产物事实保持不变；
- 不伪造 success/known，不生成占位质量产物，不重跑科学计算；
- Stage F release gate 与 Stage G 必须显式消费同一份 manifest 路径和 SHA；
- G 不读取这些 PDB 的质量文件，不把它们计入 eligible 或 candidate；
- waiver 必须绑定 pair-list、全部 status 分片、canonical raw-row SHA、最终 attempt、诊断证据、0/3 三件套、零 writer 进程审计、gate/G 代码身份、用户授权和退出条件；
- 无 waiver 参数时保持历史严格行为，strict smoke 和非 Stage F gate 不接受 waiver；
- 既有 19 条 exclusion manifest 不得追加或改写。19+45=64 只用于 cap 校验，不能称为 64 条原生 exclusion；
- 当前 run 的硬上限从历史 100 提升为 200。cap200 不是自动配额，任何新增批次仍需重新取证并向用户报告/获得授权。

45 条真实分类为 32 个 Chimera ALL signal-11、8 个外部工具 timeout、2 个 fatal-log、3 个 MapQ Q 越界。不要为了叙述方便把它们统一伪装成“超时”或“大图”。

## When To Use

恢复本次正式 F gate、预置 `316117` 的 analyze-only 命令、审计 G 候选或解释为何 raw unknown 可在本 run 继续时使用。未来 run 默认不得继承这 45 个 ID、cap200 或 manifest；遇到新异常必须先冻结证据并向用户报告，不得自动重跑或开路。

## Related Files

- `Data_Preprocessing/Ori_Data/code/controlled_failure_waiver.py`
- `Data_Preprocessing/Ori_Data/code/filtering.py`
- `Data_Preprocessing/Ori_Data/scripts/stage_release_gate.py`
- `Data_Preprocessing/Ori_Data/scripts/g_filter.py`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `文档/mapping/计划执行映射.md`
