# Handoff: 受控 unknown 开路规则与 Stage F 当前停点

Date: 2026-07-18

## Current State

- 正式 A–G run 为 `adaligand_ag_20260711T154658`。A–E 与独立 E3 已闭合；正式 Stage F job `316116` 仍是 22,386 行 status 与 `f_release` 的唯一 writer，G job `316117` 继续只等待正式 `f_release` 并只允许 analyze。
- Stage F Phase-2 已原子迁移闭合：正式 exclusion 19 条，SHA-256 `f9482353f6f8a2ee574fbdc881715a1d3b5258fc6f397271294152b5665ffea8`；补算 v2 exclusion 14 条，SHA-256 `c1755825ee9d1bee5bff84eaa6a1318c3a39af6092403385527507c632f86d45`。Stage E base4、补算 v1 和历史 cap 证据不变。
- `318350/cnode01` 的补算 v2 已 `COMPLETED 0:0`：5,984/5,984 unique，5,970 skipped + 14 known，unknown/duplicate/silent missing 均为 0；status/release SHA-256 为 `8babca24…d0c` / `123bed2c…fd69`，8 个 Phase-2 样本继续保持公开质量三件套 0/3。补算锁与 child PGID 已由 core 清理，禁止重复运行。
- fresh 跨节点进程审计与独立复核通过后，2026-07-18 21:53:48+08 只删除精确 `try_lock_316116`，保留 `after_lock_316116`；正式 `316116/cnode04` 已由原 CPU96 allocation 复用 run_cmd `0ff22ef9…e131`、F12、no-overwrite 自行恢复。readiness、Loky12 与首批真实进度均已确认，`316117` 继续依赖等待。
- 本次用户新增的是后续事件的运维规则；它未追溯替代已完成的 Phase-2 迁移，也没有改变当前运行命令或科学契约。

## Completed

- 独立只读审查确认：现有 status loader、release gate 和 G 都会拒绝 raw unknown；未来临时开路不能只绕 release gate，gate 与 G 必须共享同一份受检有效状态视图。
- 已把规则写入 A–G ExecPlan、代码旁契约 README 和 durable decision memory。
- 规则正式命名为 **run-scoped controlled-failure waiver**。raw `unknown_failed`、原始错误和状态分母保留；命中项只进入独立 `waived_controlled_failures` 集合并排除训练、推理和 G，绝不能伪造 success/known。

## Decisions

- 仅当固定 ID、逐例根因闭合、样本已稳定终态、无活动 writer、无共享污染、科学契约不变、required artifact 明确 0/N 或完整通过 validator 且下游可安全排除时，才允许当前-run waiver。
- cap=100 是硬上限而不是自动配额；每批仍需单独取证。错误签名增长或提示系统性问题时停止个例化并诊断。
- duplicate、silent missing/extra、非法 schema、身份/SHA/manifest 漂移、未列 unknown、partial/损坏产物、系统性风险和 strict smoke 继续 fail-closed。其他 stage 不自动继承 E/F 经验。
- 上一条的 fail-closed 只表示未经用户决定不得放行，不授权 Agent 自动修复或重跑。即使风险看起来系统性或涉及科学契约，也要先冻结现场，向用户报告范围、证据、置信度、接受风险、修复路径和时间成本；用户明确选择后才可接受瑕疵开路，或严格阻断/修复。没有指令时不得终止 producer、改运行中代码或发起昂贵重跑。
- waiver 不修改运行中 producer、不改 raw status、不造占位产物。发布时必须绑定 status/row SHA、attempt/job/node/tool/code、日志/诊断 SHA、artifact 快照、无 writer 快照、授权、数量/cap、下游策略与退出条件。
- “补票”可在 producer 继续运行时异步完成：实现无 PDB allowlist 的一般化分类/修复和回归，使未来 clean run 无 waiver 通过；补票完成后退休 run-specific 脚手架。

## Open Questions

- 当前没有需要用户决定的新科学契约问题。
- controlled-failure waiver 的通用 adapter 尚未实现；只有未来真的出现符合条件的 raw unknown 时，才应按本记录建立独立 ticket/ExecPlan 项、实现默认关闭的 overlay 并测试。不得为了“预先完备”而改动当前运行代码。

## Next Actions

1. 只读监控正式 `316116` 的 squeue/sacct、日志与 heartbeat 增量、F12/外部工具进程、精确锁和 scratch；运行中不得 safe sync 或修改代码/命令。
2. 正式 F 完成后审计 22,386 四终态、19 条 run-only provenance、排除样本 0/3、四 CC、配体/6 Å 口袋 Q、MapQ 参数与 provenance；`f_release` 成功后才接受 G analyze。
3. 若出现任何新异常，先冻结并向用户报告范围、置信度、科学影响、接受风险和修复/重跑成本；未经用户决定不得自动停止 producer、开路或重跑。用户选择 current-run waiver 时才建立 gate/G 共用 overlay，并异步补票。
4. A–G 最终收口时盘点并退休所有 run-specific waiver、repair、supplement 与恢复脚手架，保留不可变证据和可复用、默认关闭且有完整测试的运维层。

## Files To Reopen

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `CLAUDE/memory/learnings/decision-2026-07-18-受控unknown不中断主线与延后补票.md`
- `CLAUDE/memory/learnings/pattern-2026-07-16-临时运行脚手架须在最终收口清理.md`
- `Data_Preprocessing/Ori_Data/code/filtering.py`
- `Data_Preprocessing/Ori_Data/scripts/stage_release_gate.py`
- `CLAUDE/memory/projects/adaligand.json`
