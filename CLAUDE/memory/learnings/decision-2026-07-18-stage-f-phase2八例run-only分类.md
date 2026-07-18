# Stage F Phase-2 八例按真实外部工具原因做本 run 排除

Type: decision
Date: 2026-07-18
Tags: AdaLigand, Stage F, Chimera, run-policy, exclusion, phase-2

## Context

独立补算 run `adaligand_ag_20260711T154658_fsupp96_v2` 已完成全部 5,984 个目标的计算，但状态为 2,984 skipped、2,986 success、6 known 和 8 unknown，status SHA-256 为 `3231dfe56403444c37ac962835c7ced2b97b13eb49cde5a934ad74b2330bb23e`；因此 `f_supplement_release` 没有形成。为避免正式 `316116` 运行到同一边界后重复失败，正式 F 与补算 v2 均已在精确锁机制下安全停写。

## Memory

- 用户先把正式 run `adaligand_ag_20260711T154658` 的 run-only exclusion 上限放宽到 30，随后于 2026-07-18 进一步提升为 100，并授权少数、已取证的巨大长尾或稳定外部工具边界显式收口。旧 cap30 继续作为首轮六例迁移的历史证据，不重写旧 manifest；Phase-2 与后续当前-run门使用 100。Phase-2 拟将新增 8 例追加后，本 run 累计将为 19/22,386，约 0.084874%；这个数量只在迁移与 gate 真实成功后才能称为已生效。
- `7ju4/7kzm/7z8f/7z8i/8olb` 在 molmap 与 contour CC 完成后，于祖传 full-grid ALL 路径返回 signal 11；它们的 run-scoped reason 冻结为 `chimera_full_grid_cc_signal11`。
- `7yiu/8e45/8j07` 都在 molmap 阶段运行满 3,600 秒后 timeout，run-scoped reason 冻结为 `chimera_molmap_timeout_3600s`。detail 必须区分：`7yiu/8e45` 为 `missing_ccd_template_fetch`，`8j07` 为 `large_grid_and_model`。禁止把前两者伪装成巨大网格长尾，也禁止用笼统“人工超时”覆盖真实原因。
- 8 例 canonical 公开质量三件套都必须保持 0/3。status、run-scoped manifest 和小日志记录真实 known failure；不生成占位 JSON/NPZ，训练、推理和 G 按产物完整性自然排除。审计已确认 attempt 仅留小型脚本/日志，没有大 MRC/MAP/CIF 残留。
- Stage E 共享 base4 manifest SHA-256 `380844d0b908b08707fada689f64b2fa4cc519f4771df92dec8b5bf0b2cd325f` 与已 release 的补算 v1 必须冻结。补算 v1 的 status/release SHA-256 为 `04d6474e371b3573e0f4479080b2006733ec84a2bc31a1aeab59c83b2d6839a7` / `9a445fa4d9a8a0d4845bd572220b60e0c4d353cc9e10a7b116375c1c45c09426`，其六条加法视图不得被 Phase-2 修改或重放。
- Phase-2 只允许将正式 Stage F 视图由 11 条原子迁移至 19 条，将补算 v2 视图由 6 条迁移至 14 条。这两个目标在代码、回归、远端 apply 和各自 gate 通过前都只是待迁移计划，不是已完成的产物事实。
- 当前 `316116/318350` 都保留各自 `after+try`，`kill/pre/child_pgid` 不存在，cnode04/cnode01 无 F/Loky/Chimera/MapQ writer；`316117` 继续等待 `afterok:316116`。在 Phase-2 迁移和补算 v2 release 闭合前不得恢复 writer。
- 本决定不改变四 CC、molmap、MapQ、配体/口袋 Q、成功产物 schema 或未来 run。生产代码禁止 PDB allowlist；ID 只能存在于绑定 run、授权、原始 status 行 SHA、attempt/日志 SHA 与 0/3 证据的 manifest。
- Phase-2 一次性生成/迁移/恢复脚手架的退出条件是：formal/v2 原子迁移和 gate 通过，补算 v2 为 5,984 行且 unknown/duplicate/silent missing 为 0，正式 F 为 22,386 行并形成 `f_release`，G analyze 与最终 A–G 审计闭合，且证据与 Git checkpoint 已冻结。此前不得清理；此后按复用价值分类为可复用运维工具或归档/移出生产入口。
- 不得直接用旧 v2 plan 的碰撞阈值恢复本次补算。旧阈值 14,386 已低于正式日志历史进度，会让 workload 尚未启动就以 guard=75 退出。Phase-2 checkpoint `a397e45` 改用显式 formal-held：绑定正式 after+try 的文件身份与 cnode04 零 writer，启动屏障前、运行中、child 末检和 release gate 前复核；漂移返回独立非零 76、精确回收补算 PGID、保留 allocation/try-lock，不把它伪装成正常 collision。旧 progress guard 默认行为和退出码 75 不变。

## When To Use

实施或审计当前 run 的 Phase-2 formal/v2 manifest 迁移、补算 v2 gate、正式 F 恢复和最终 19 项 run-only provenance 时使用。任何未来 run、新的 signal 11 聚类或 molmap timeout 都必须重新取证，不得自动继承当前 ID、detail 或 cap=100；100 不是自动排除配额。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `Data_Preprocessing/Ori_Data/scripts/f_signal11_exclusion_transition.py`
- `CLAUDE/memory/learnings/decision-2026-07-17-stage-f六大图run-only排除与上限30.md`
- `CLAUDE/memory/learnings/pattern-2026-07-17-known-failure不生成占位质量产物.md`
