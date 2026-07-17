# Stage F 六个大网格 run-only 授权与本地实现

Type: handoff
Date: 2026-07-17

## Current state

- 正式 A–G run 仍为 `adaligand_ag_20260711T154658`。A–E 与独立 E3 已闭合；Stage F 尚未 release，Stage G 尚未启动。
- 修复后的补算 v1 status SHA-256 为 `7938aea615c19029265587d556622c8f2d6aea5acff59a94baa85813698496b6`，仅余 `9bw7/9c1k/9dgr/9fkb/9mxv/9nw3` 六个大网格 unknown。
- 六者 `n_jobs=1` 为 6/6 fail；有效 fresh ALL v2 用 `9hhl` 逐位复现 canonical 两个 ALL 值，并在 `9fkb` 重现 signal 11。约 2 TB 节点无节点/cgroup OOM 证据。
- 用户已授权六者仅在当前正式 run 中写 `run_policy_excluded:chimera_full_grid_cc_signal11`，并把本 run 的 run-only exclusion 上限由 9 放宽到 30。与既有五项合计 11/22,386，约 0.049138%。这不是通用科学契约或未来 run 默认值。

## Engineering and server checkpoint

- Commits: `879f2be/aec286b/ebbef37`，依次闭合 run-only 实现、三目标原子迁移/进程门与短证据名。
- 只修改 4 个专用文件：
  - `Data_Preprocessing/Ori_Data/scripts/f_signal11_exclusion_transition.py`，SHA-256 `55e81acc46326e766c0a7c44d7b5d89d213a7d26e17938eb2447a1e9c70a3dfb`；
  - `Data_Preprocessing/Ori_Data/sbatch/resume_f_316116_signal11_v1.sh`，SHA-256 `f8adf31fec1cdc45bed338abda58027931b3d4894ccd88d63e438d9b81476a95`；
  - `Data_Preprocessing/Ori_Data/sbatch/resume_f_supplement_318350_signal11_v1.sh`，SHA-256 `3da2b388acdbf599ab2f4d0ae7876c2b277cc74d6c346a8f2ab1c5f30cb0fc43`；
  - `Data_Preprocessing/Ori_Data/tests/test_f_signal11_exclusions.py`，SHA-256 `eed82818901df13ebb901db6f69b2a300376aa1b53b103832a0f7d6553b7b335`。
- transition 只生成绑定 run/evidence 的 manifest，不在生产 Python 写 PDB allowlist，不创建六者的伪质量三件套。正式视图应由原 5 条严格追加为 11 条；两个补算 run 各自使用仅含六条、重写对应 run_id 的 F-only manifest。
- 正式恢复入口要求补算 v1 恰 2,990 行、unknown=0、六者均为 manifest-bound known 且 gate 成功；随后还必须证明 v2 gate 已成功，或 job `318350` 正在运行且已登记新的正整数 child PGID。正式 `316116` 仍是 22,386 行 status/`f_release` 唯一 writer。

## Validation and live transition

- 专项：18 passed；本地全套：377 passed、10 skipped；远端 Linux 全套：387 passed。最终独立复核无阻断。
- 新鲜跨节点 process audit SHA-256 为 `697bcb28d0d3cf43bbd883e5e0247d4241630a84a87ae6ffb716de75e3ebd063`，capture 时 master/cnode04/cnode01 均无 F/recovery/blocking opaque 进程，双 job 恰为 `after+try`。
- transition apply/replay 已成功。正式共享 4 条 manifest 仍为 `380844d0…325f`；正式 Stage F 视图为 11 条、SHA-256 `10c5d923779645a6eeeeb5d277722e6f487593557c095cfcdef641553613c8ac`；补算 v1/v2 各六条 manifest SHA-256 为 `6f3a0a880e6e38768e1e096b2bcb776087372be56987b4a930c88306b5527f35` / `43da55a71885730458cab546f6eb96e38722b726445eaf3613873f23e74b7d40`。
- 六例 canonical 质量三件套仍严格为 0/3。manifest 不产生占位 JSON/NPZ；这既保留真实 known 状态，也允许下游用几行完整性检查自然排除。
- `318350` 已原子切换到 run_cmd SHA-256 `90489efe798aa324c3854b3f26adee4761d016f022b2b99b206b4c80395def29`，并于 12:59+08 只删除精确 `try_lock_318350` 重跑 v1；`316116` 继续由精确 `after+try` 停写。

## Next actions

1. 只读监控 `318350` v1；验收 2,990 unique、unknown/duplicate/silent missing=0、六例恰为 manifest-bound known、六例 0/3 与 v1 release success。
2. 确认 wrapper 自动进入 v2，核对 run/plan/IDs、guard、child PGID、F12/MapQ np8 和首个真实进度；随后原子发布受检 formal run_cmd，并只删除精确 `try_lock_316116`。不得同时盲放两个 writer。
3. 正式 F 完成后独立审计 22,386 四终态、11 条 provenance、unknown/duplicate/silent missing=0、六者 0/3 质量三件套以及四 CC/Q/MapQ 契约；`f_release` 成功后才允许 `316117` 只运行 G analyze。
4. manifest 的退出条件是正式 F release、G analyze 和最终 A–G 审计闭合。最终维护收口必须审查这些一次性生成/恢复脚本，并归档或移出生产入口；未来 run 不继承六个 ID 或 cap30。

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
