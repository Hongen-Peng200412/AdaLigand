# Handoff: Stage F Fresh ALL 大网格阻断

Date: 2026-07-17

## Current State

- 正式 A–G run 仍为 `adaligand_ag_20260711T154658`。A–E 与 E3 已闭合；F 尚未 release，G 尚未启动。
- `316116` 与 `318350` 当前均保留各自精确 `after+try`，没有 Stage F writer。不得在用户选择后续路径前删除任一 try-lock。
- 修复后的补算 v1 status SHA-256 为 `7938aea615c19029265587d556622c8f2d6aea5acff59a94baa85813698496b6`，仅余 `9bw7/9c1k/9dgr/9fkb/9mxv/9nw3` 六个 unknown。

## Completed

- 单 PDB、`n_jobs=1` shadow 对六者仍为 6/6 fail。证据目录为 `/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_ag_20260711T154658/stage_f_cc_sigsegv_shadow_20260717_v1/`，step `318350.61`，status/acceptance SHA-256 为 `5c41167deb1e17e8fade06c588c25bf4786048ca9286f4e1e317b4c296af50f9` / `67cc083c94efbb72648db07e5d62ec8fee195bbf3a3dc59eecb5dcbf0ed868b2`。
- ALL-only v1 `stage_f_cc_all_fresh_process_shadow_20260717_v1`、step `318350.63` 因 harness `ImportError` 而零科学计算，永久只作无效诊断证据。
- 修正后的 v2 位于 `stage_f_cc_all_fresh_process_shadow_20260717_v2`。step `318350.64` 为 `COMPLETED 0:0`、elapsed `00:04:24`；preflight/harness/run/launch SHA-256 分别为 `f22a18bb…f1cd` / `ebc4afc5…e4fb` / `650d354c…ccd4` / `53feeb72…c7a`，acceptance SHA-256 为 `e0bef08c6a4da804d0173ccc920e3e58316912ee4fea303bf9045ad4f50032e9`。
- v2 控制样本 `9hhl` 的 `cc_all` 与 `cc_all_about_mean` 均逐位等于 canonical；`9fkb` 的 fresh ALL 子进程仍 signal 11。约 2 TB 节点没有 OOM 证据，排除了 harness 漂移、外层并发和宿主 RAM 耗尽作为简单解释。

## Decisions

- signal 11 继续保留为 unknown，不改四 CC、MapQ、配体/口袋 Q 或质量三件套契约。
- 当前已有 5 个 run-only exclusion；六者全部追加会达到 11，违反严格 `<10` 上限，且同类大图聚集属于系统性趋势。Agent 无权自行追加或只挑其中四个掩盖余项。
- 如选择实现有界内存适配，应保持祖传非零点顺序、float32 点/权重、世界变换、三线性插值与原 reducer，并用逐位控制证明等价；否则必须把换工具、裁图或新归约明确记为科学变更。

## Open Questions

等待用户在以下路径中显式选择：

1. 批准通用、可证明祖传数值等价的分块向量/memmap 适配；
2. 显式放宽本 run 的 run-only exclusion 上限，让六个大图作为运行级失败退出；
3. 批准另行命名并重新验收的裁图、换工具/公式等科学替代。

## Next Actions

1. 用户决定前只读保持 `316116/318350` 的 `after+try`，不恢复 F，不启动 `316117`。
2. 若批准等价适配，先做合成与分层真实控制的向量/最终 float64 逐位验收，再在独立 run 中重算六者；不能直接改正式 writer。
3. 六者闭合后恢复唯一正式 F writer，完成 22,386 四终态、五项既有 run-only exclusion、四 CC、配体/6 Å 口袋 Q、schema v3 空口袋和 provenance 审计，随后才接受 G analyze。

## Files To Reopen

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `CLAUDE/memory/learnings/gotcha-2026-07-17-chimera-all大网格单进程崩溃.md`
- `CLAUDE/memory/learnings/decision-2026-07-14-stage-f长尾与阶段专属排除.md`
