# Stage F 六个大网格仅按本 run 排除并把上限放宽到 30

Type: decision
Date: 2026-07-17
Tags: AdaLigand, Stage F, Chimera, cc_all, run-policy, exclusion

## Context

正式 run `adaligand_ag_20260711T154658` 在修复 353 个确定性适配误拒后，仅余 `9bw7/9c1k/9dgr/9fkb/9mxv/9nw3` 六个大网格 unknown。六者在单 PDB、`n_jobs=1` 下仍 6/6 fail；有效 fresh ALL v2 用 `9hhl` 逐位复现两个 canonical ALL 值，并在 `9fkb` 重现 signal 11。约 2 TB 节点没有 OOM 证据。旧 run-only 上限要求累计严格少于 10，因此 Agent 已停写并请求用户决定。

## Memory

- 用户明确选择只对本次正式 run 的六个 ID 写 `run_policy_excluded:chimera_full_grid_cc_signal11`，并把该 run 的 run-only exclusion 硬上限放宽到 30。原有 5 项加本次 6 项后累计为 11/22,386，约 0.049138%。
- 这是运维完成策略，不是新的通用科学 known-failure 类别，不改变 `cc_all`、`cc_all_about_mean`、四 CC mask/公式、F 成功定义或未来 run 的默认行为。六者保留在 22,386 状态分母，排除训练、推理与 G 候选，不伪造质量三件套或 success。
- 生产代码禁止 PDB allowlist。六个 ID 只能存在于 run-scoped manifest；manifest 必须绑定 `run_id`、仅 `stage_f`、用户授权、fresh ALL/n_jobs1 证据、原因、下游策略、实现/输入 SHA 和失败时 fail-closed 的 schema 校验。
- 旧的“累计不超过 9”决策仍作为当时要求 Agent 停下询问的历史证据；对于这个正式 run，其数量上限已被本决定显式取代为 30。未来 run 不自动继承 30，也不自动继承这六个 ID。
- manifest 的退出条件是本 run 的正式 Stage F status/`f_release`、Stage G analyze 与最终 A–G 审计闭合。专门生成/应用/恢复该 manifest 的一次性脚手架必须在最终维护收口中分类；没有跨 run 通用价值的入口应归档或移出生产路径，通用 manifest validator/loader 只有在完成测试和默认调用边界审查后才可保留。
- 本地实现检查点是 `879f2be`，仅含 transition、正式恢复、补算恢复和测试 4 个专用文件。四者 SHA-256 依次为 `8e2e1346b7c35452d4058c4a7c59faa116f80446982540332f0cae2a8ddba489`、`6e16aec8f9c2f7c8fc6a3c2e643053daf3c574b13a774141b8757e836fdacc79`、`99f81c76bcdce7038a6020c400889ebdd7d09d624d41c28052113379a80ee787`、`46d07664990e1bf9aab1f8bdd1d13d734350c69466a27c749d2e8f4201c3ebdc`。专项 12 passed，相关 42 passed、2 个 Linux-only skipped；本机完整收集因缺 `rdkit/gemmi` 的 16 个 collection errors 不是测试通过。远端同步、Linux 全套、manifest 实例和锁恢复仍须独立记录。

## When To Use

恢复本次 `316116/318350`、审计 11 项 Stage F run-only exclusion、生成正式 F status 或确认 G 候选排除时使用。任何未来 run、其他 signal 11 聚类或新的排除原因都必须重新取证与授权。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `Data_Preprocessing/Ori_Data/scripts/f_signal11_exclusion_transition.py`
- `Data_Preprocessing/Ori_Data/sbatch/resume_f_316116_signal11_v1.sh`
- `Data_Preprocessing/Ori_Data/sbatch/resume_f_supplement_318350_signal11_v1.sh`
- `Data_Preprocessing/Ori_Data/tests/test_f_signal11_exclusions.py`
- `CLAUDE/memory/learnings/decision-2026-07-16-a-g巨大长尾run-only上限.md`
- `CLAUDE/memory/learnings/gotcha-2026-07-17-chimera-all大网格单进程崩溃.md`
