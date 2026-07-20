# 2026-07-20 Stage F waiver 本地实现与远端放行前停点

## Current State

正式 run 为 `adaligand_ag_20260711T154658`。`316116` 已完成 Stage F 22,386/22,386 科学计算，状态为 16,944 skipped、5,323 success、74 known、45 raw unknown；status SHA-256 为 `4280757cab61989a70684d745f428f8ed8028634c8dc6c627455202a1b6f503d`。严格 gate 已进入精确 after+try 停点，`f_release` 不存在，cnode04 无 F/Loky/Chimera/MapQ writer。`316117` 仍等待 `afterok:316116`，只能运行 G analyze。

## Completed

- 三路独立只读审计确认 22,386 unique 与 pair-list 精确一致，duplicate/silent missing/extra=0。
- 45 条 raw unknown 已逐条分类，45/45 公开质量三件套为 0/3，最终 attempt 无 MRC/MAP/CIF 残留。
- 用户批准保留 raw unknown、不重跑、不造占位，并把当前 run cap 提升为 200。
- 本地实现 `controlled_failure_waiver.py` schema v1 与轻量 canonical process-audit 验证器，并接入 Stage F release gate 与 Stage G。
- 默认无参数路径仍严格拒绝 unknown；strict smoke 不接受 waiver。
- 专项测试 65 passed、2 skipped；本地全套 402 passed、10 skipped；compileall、diff check 和独立代码审查通过。
- ExecPlan、mapping、契约 README 和 durable decision memory 已回填。

## Decisions

- 45 条 waiver 与既有 19 条原生 `run_policy_excluded` 保持两套身份；累计 64 只用于 cap200 校验。
- gate 与 G 必须使用同一份 manifest 路径和显式 SHA；不能只放 gate 而让 G 仍严格失败。
- G waived 行仍是 `unknown_failed`，只增加 waiver 分类和 SHA；不能记 success/known。
- `316116` 的下一次原地命令应只运行 gate，不得重启 F producer。
- `316117` 只能 analyze，不执行示例阈值，不写或删除 `keep_list`。

## Open Questions

没有待用户科学决定。若远端测试、manifest 身份、进程门或调度状态出现漂移，先报告证据与时间成本，不得自动重跑。

## Next Actions

1. 精确提交当前代码、测试、文档和记忆，不带入用户的三个无关 untracked 文件。
2. 无删除、精确路径同步到服务器；运行相关与 Linux 全套测试。
3. fresh capture master+cnode04 的零 writer process audit，生成 45 条逐行绑定 waiver 并用当前代码只读验证。
4. 原子预置 gate-only `run_cmd_316116` 和携带同一 waiver SHA 的 analyze-only `run_cmd_316117`。
5. 复核锁 inode、scheduler 依赖和无旧 `keep_list` 后，只删除精确 `try_lock_316116`；监控 F→G。
6. 审计 `f_release`、G 分布、45 条 raw/waived 双重报告、19 条原生 exclusion、全量 QC 和一次性脚手架，最终删除 heartbeat。

## Files To Reopen

- `AGENTS.md`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `文档/mapping/计划执行映射.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `Data_Preprocessing/Ori_Data/code/controlled_failure_waiver.py`
- `Data_Preprocessing/Ori_Data/code/filtering.py`
- `Data_Preprocessing/Ori_Data/scripts/stage_release_gate.py`
- `Data_Preprocessing/Ori_Data/scripts/g_filter.py`
- `Data_Preprocessing/Ori_Data/tests/test_controlled_failure_waiver.py`
