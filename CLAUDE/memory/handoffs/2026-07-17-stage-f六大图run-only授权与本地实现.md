# Stage F 六个大网格 run-only 授权与本地实现

Type: handoff
Date: 2026-07-17

## Current state

- 正式 A–G run 仍为 `adaligand_ag_20260711T154658`。A–E 与独立 E3 已闭合；Stage F 尚未 release，Stage G 尚未启动。
- 修复后的补算 v1 status SHA-256 为 `7938aea615c19029265587d556622c8f2d6aea5acff59a94baa85813698496b6`，仅余 `9bw7/9c1k/9dgr/9fkb/9mxv/9nw3` 六个大网格 unknown。
- 六者 `n_jobs=1` 为 6/6 fail；有效 fresh ALL v2 用 `9hhl` 逐位复现 canonical 两个 ALL 值，并在 `9fkb` 重现 signal 11。约 2 TB 节点无节点/cgroup OOM 证据。
- 用户已授权六者仅在当前正式 run 中写 `run_policy_excluded:chimera_full_grid_cc_signal11`，并把本 run 的 run-only exclusion 上限由 9 放宽到 30。与既有五项合计 11/22,386，约 0.049138%。这不是通用科学契约或未来 run 默认值。

## Local engineering checkpoint

- Commit: `879f2be fix(stage-f): exclude six reproducible Chimera signal-11 cases`。
- 只修改 4 个专用文件：
  - `Data_Preprocessing/Ori_Data/scripts/f_signal11_exclusion_transition.py`，SHA-256 `8e2e1346b7c35452d4058c4a7c59faa116f80446982540332f0cae2a8ddba489`；
  - `Data_Preprocessing/Ori_Data/sbatch/resume_f_316116_signal11_v1.sh`，SHA-256 `6e16aec8f9c2f7c8fc6a3c2e643053daf3c574b13a774141b8757e836fdacc79`；
  - `Data_Preprocessing/Ori_Data/sbatch/resume_f_supplement_318350_signal11_v1.sh`，SHA-256 `99f81c76bcdce7038a6020c400889ebdd7d09d624d41c28052113379a80ee787`；
  - `Data_Preprocessing/Ori_Data/tests/test_f_signal11_exclusions.py`，SHA-256 `46d07664990e1bf9aab1f8bdd1d13d734350c69466a27c749d2e8f4201c3ebdc`。
- transition 只生成绑定 run/evidence 的 manifest，不在生产 Python 写 PDB allowlist，不创建六者的伪质量三件套。正式视图应由原 5 条严格追加为 11 条；两个补算 run 各自使用仅含六条、重写对应 run_id 的 F-only manifest。
- 正式恢复入口要求补算 v1 恰 2,990 行、unknown=0、六者均为 manifest-bound known 且 gate 成功；随后还必须证明 v2 gate 已成功，或 job `318350` 正在运行且已登记新的正整数 child PGID。正式 `316116` 仍是 22,386 行 status/`f_release` 唯一 writer。

## Validation

- 专项：12 passed。
- 相关：42 passed，2 个 Linux-only skipped。
- 本机完整收集因环境缺少 `rdkit/gemmi` 出现 16 个 collection errors；这不是全套通过，也不是实现失败的科学证据。
- 截至本 handoff，代码尚未 safe sync 到服务器，远端 Linux 全套尚未运行，manifest 实例 SHA/行数尚未生成，任何 try-lock/after-lock 均未由本地实现提交动作改变。

## Next actions

1. 按 `project-server-interaction` 做无删除 safe sync，复核远端四文件 SHA，并运行远端 Linux 全套；不得把 collection failure 或测试未收集冒充通过。
2. 在 fresh process/锁门通过后运行 transition 的 audit/validate，再生成正式 11 条与两个补算各 6 条 manifest；记录精确路径、SHA-256、行数和旧五条逐字节保持证据。
3. 更新受检 run_cmd/release marker，先只恢复 `318350`；确认补算 v1 gate 与 v2 gate/child-PGID/F12 后，再恢复唯一正式 writer `316116`。不得同时盲放两个 try-lock。
4. 正式 F 完成后独立审计 22,386 四终态、11 条 provenance、unknown/duplicate/silent missing=0、六者 0/3 质量三件套以及四 CC/Q/MapQ 契约；`f_release` 成功后才允许 `316117` 只运行 G analyze。
5. manifest 的退出条件是正式 F release、G analyze 和最终 A–G 审计闭合。最终维护收口必须审查这些一次性生成/恢复脚本，并归档或移出生产入口；未来 run 不继承六个 ID 或 cap30。

## Do not do

- 不修改四 CC、mask、均值、归约精度或祖传 Chimera ALL 公式。
- 不把六个 PDB 写入生产 allowlist，不生成占位质量产物，不伪造 success。
- 不覆盖共享 Stage E exclusion，不删除 pair-list，不在远端全套与锁门前释放 G。
- 不提交或改写用户当前 dirty 的 mapping、Stage1、BOX-level 或 `talk/` 文件。

## Related memory

- `CLAUDE/memory/learnings/decision-2026-07-17-stage-f六大图run-only排除与上限30.md`
- `CLAUDE/memory/learnings/gotcha-2026-07-17-chimera-all大网格单进程崩溃.md`
- `CLAUDE/memory/handoffs/2026-07-17-stage-f-fresh-all阻断.md`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
