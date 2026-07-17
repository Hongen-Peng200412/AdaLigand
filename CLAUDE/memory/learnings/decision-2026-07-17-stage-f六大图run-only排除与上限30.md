# Stage F 六个大网格仅按本 run 排除并把上限放宽到 30

Type: decision
Date: 2026-07-17
Tags: AdaLigand, Stage F, Chimera, cc_all, run-policy, exclusion

## Context

正式 run `adaligand_ag_20260711T154658` 在修复 353 个确定性适配误拒后，仅余 `9bw7/9c1k/9dgr/9fkb/9mxv/9nw3` 六个大网格 unknown。六者在单 PDB、`n_jobs=1` 下仍 6/6 fail；有效 fresh ALL v2 用 `9hhl` 逐位复现两个 canonical ALL 值，并在 `9fkb` 重现 signal 11。约 2 TB 节点没有 OOM 证据。旧 run-only 上限要求累计严格少于 10，因此 Agent 已停写并请求用户决定。

## Memory

- 用户明确选择只对本次正式 run 的六个 ID 写 `run_policy_excluded:chimera_full_grid_cc_signal11`，并把该 run 的 run-only exclusion 硬上限放宽到 30。原有 5 项加本次 6 项后累计为 11/22,386，约 0.049138%。
- 这是运维完成策略，不是新的通用科学 known-failure 类别，不改变 `cc_all`、`cc_all_about_mean`、四 CC mask/公式、F 成功定义或未来 run 的默认行为。六者保留在 22,386 状态分母，但 canonical `quality/*.jsonl`、`quality/*.provenance.json`、`quality_atoms/*.npz` 必须保持 0/3；只由状态、run-scoped manifest 和审计证据记录真实 known failure。这样既不伪造产物或 success，也允许训练、推理和 G 仅凭产物完整性自然排除。
- 生产代码禁止 PDB allowlist。六个 ID 只能存在于 run-scoped manifest；manifest 必须绑定 `run_id`、仅 `stage_f`、用户授权、fresh ALL/n_jobs1 证据、原因、下游策略、实现/输入 SHA 和失败时 fail-closed 的 schema 校验。
- 旧的“累计不超过 9”决策仍作为当时要求 Agent 停下询问的历史证据；对于这个正式 run，其数量上限已被本决定显式取代为 30。未来 run 不自动继承 30，也不自动继承这六个 ID。
- manifest 的退出条件是本 run 的正式 Stage F status/`f_release`、Stage G analyze 与最终 A–G 审计闭合。专门生成/应用/恢复该 manifest 的一次性脚手架必须在最终维护收口中分类；没有跨 run 通用价值的入口应归档或移出生产路径，通用 manifest validator/loader 只有在完成测试和默认调用边界审查后才可保留。
- 最终工程检查点为 `879f2be/aec286b/ebbef37`，仅含 transition、正式恢复、补算恢复和测试 4 个专用文件。四者 SHA-256 依次为 `55e81acc46326e766c0a7c44d7b5d89d213a7d26e17938eb2447a1e9c70a3dfb`、`f8adf31fec1cdc45bed338abda58027931b3d4894ccd88d63e438d9b81476a95`、`3da2b388acdbf599ab2f4d0ae7876c2b277cc74d6c346a8f2ab1c5f30cb0fc43`、`eed82818901df13ebb901db6f69b2a300376aa1b53b103832a0f7d6553b7b335`。专项 18 passed，本地全套 377 passed+10 skipped，远端 Linux 全套 387 passed；独立复核通过。
- 新鲜 process audit `697bcb28…bd063` 后已原子迁移三份 manifest：正式 Stage F 11 条 `10c5d923…c8ac`，补算 v1/v2 各六条 `6f3a0a88…7f35` / `43da55a7…7d40`；正式共享 4 条 `380844d0…325f` 与六例 0/3 均未改变。`318350` 已以 run_cmd `90489efe…ef29` 重跑 v1，正式 `316116` 仍停写等待 v1 gate 与 v2 guard/PGID。

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
