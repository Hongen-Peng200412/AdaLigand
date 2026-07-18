# Handoff: Stage F Phase-2 八例迁移停点

Date: 2026-07-18

## Current State

- 正式 A–G run 是 `adaligand_ag_20260711T154658`。A–E 与独立 E3 已闭合；正式 Stage F job `316116` 是 22,386 行 status 与 `f_release` 的唯一 writer。
- 补算 job `318350` 的 v2 run 是 `adaligand_ag_20260711T154658_fsupp96_v2`。它已完成 5,984 个目标，但状态为 2,984 skipped + 2,986 success + 6 known + 8 unknown，status SHA-256 `3231dfe56403444c37ac962835c7ced2b97b13eb49cde5a934ad74b2330bb23e`，`f_supplement_release` 不存在。
- 为避免正式 F 重复命中这些外部工具边界，`316116` 已由精确 kill-lock 安全转入 try-lock。当前 `316116/318350` 均为 `after+try`，`kill/pre/child_pgid` 不存在，cnode04/cnode01 无 F/Loky/Chimera/MapQ 进程。
- `316117` 仍严格等待 `afterok:316116`，只允许 G analyze；不执行示例阈值，不写或删除 `keep_list`。

## Completed

- 对 8 个 unknown 的只读取证已闭合。五个 `7ju4/7kzm/7z8f/7z8i/8olb` 在 molmap 和 contour CC 后于 full-grid ALL 返回 signal 11；三个 `7yiu/8e45/8j07` 在 molmap 阶段精确超时 3,600 秒。
- timeout 已细分为 `7yiu/8e45: missing_ccd_template_fetch` 与 `8j07: large_grid_and_model`。前两者不是大网格样本，不得被归为与 `8j07` 相同的长尾机制。
- 8 例 canonical 公开质量产物均为 0/3；scratch 仅保留小日志/脚本，没有大 MRC/MAP/CIF 残留。本次不需要再次执行 scratch v4 回收。
- 补算 v1 已稳定 release：2,990 unique = 2,984 skipped + 6 known，unknown/duplicate/silent missing 为 0；status/release SHA-256 为 `04d6474e371b3573e0f4479080b2006733ec84a2bc31a1aeab59c83b2d6839a7` / `9a445fa4d9a8a0d4845bd572220b60e0c4d353cc9e10a7b116375c1c45c09426`。该 run 与其六条 manifest 已冻结，不参与 Phase-2 迁移。
- Phase-2 代码 checkpoint `a397e45` 已提交。独立终审抓到旧 plan 阈值 14,386 会因正式历史日志越界而让 v2 启动前错误退出；现已改为本次 v2 专用 formal-held guard，绑定 `316116/cnode04` after+try 身份和 canonical 零 writer probe，漂移使用独立非零 76 回收精确 PGID且不跑 gate。专项 59 passed、8 个 Linux/POSIX 项 skipped，静态检查均通过；远端 Linux 全套和真实 held probe 尚待执行。

## Decisions

- 用户已把本 run 的 run-only exclusion 上限从 30 进一步放宽到 100。旧 cap30 只保留为首轮迁移历史证据；Phase-2 使用 100，但每一条仍需独立证据。拟追加这 8 例后，迁移成功时正式总数将从 11 变为 19/22,386（约 0.084874%）。
- 五个 ALL signal-11 使用 `chimera_full_grid_cc_signal11`；三个 molmap 超时使用 `chimera_molmap_timeout_3600s`，并保留两类 detail。不改四 CC、molmap、MapQ、Q-score 或成功产物契约。
- Phase-2 仅允许两个迁移目标：formal Stage F 视图 11→19，supplement v2 视图 6→14。Stage E shared base4 SHA-256 `380844d0…325f` 与已 release 的 supplement v1 必须逐字节不变。
- 8 例只写真实 known status 与 run-scoped provenance，canonical 公开质量三件套继续 0/3；不生成占位产物。训练、推理和 G 通过产物完整性自然排除。
- 上述均是当前已批准的迁移决策，不代表 formal/v2 manifest、新 status 或 release gate 已完成。

## Open Questions

- 当前没有新的科学契约问题需要用户决定。当前阻塞是 Phase-2 工程迁移、回归测试、远端 apply 与 gate，不是 A–G 科学算法漂移。

## Next Actions

1. 精确同步 checkpoint `a397e45` 的 7 个文件；在服务器 Linux 环境完成 SHA、`bash -n`、专项、8 个 POSIX/Bash 项、全套和真实 formal-held probe，任何失败都保持双 try-lock。
2. 以新鲜跨节点零进程门验证双 writer 停止，再事务化更新 formal 11→19 与 v2 6→14；独立复核 base4、supplement v1、已有公开质量产物与锁 inode 未漂移。
3. 重放补算 v2，要求恰 5,984 行 unique，unknown/duplicate/silent missing 为 0，8 例为 manifest-bound known、产物仍 0/3，并形成成功 `f_supplement_release`。
4. 补算 v2 gate 闭合后，才可通过受检 run_cmd 删除精确 `try_lock_316116` 恢复正式 F。正式 F 仍是 22,386 行 status/`f_release` 唯一 writer。
5. 正式 F 完成后审计 22,386 四终态、19 条 run-only provenance、全部排除样本 0/3、四 CC、配体与 6 Å 口袋 Q、MapQ 参数与 provenance；只有正式 `f_release` 成功后才接受 `316117` 进入 analyze-only G。
6. G analyze 与最终 A–G 审计后，冻结证据/Git checkpoint，再按项目“一次性脚手架最终收口”规则分类、归档或移出 Phase-2 专用入口。

## Files To Reopen

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `Data_Preprocessing/Ori_Data/scripts/f_signal11_exclusion_transition.py`
- `CLAUDE/memory/learnings/decision-2026-07-18-stage-f-phase2八例run-only分类.md`
- `CLAUDE/memory/learnings/pattern-2026-07-17-known-failure不生成占位质量产物.md`
- `CLAUDE/memory/projects/adaligand.json`
