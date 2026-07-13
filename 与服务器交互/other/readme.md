# AdaLigand 服务器交互工具箱

本目录记录 AdaLigand 项目的服务器交互工具与使用纪律。工具随项目走，密码、本机依赖和 VS Code 用户设置不随项目走。

## 当前映射

- 本地同步源：`C:\Users\15919\Desktop\AdaLigand`
- 远端代码目录：`/home/penghongen/My_Project/AdaLigand`
- Stage A-C 数据根目录：`/storage/penghongen/AdaLigand/Ori_Data`
- 服务器：`penghongen@10.102.33.220:10022`
- Stage A-C 专用环境：`/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310`

## 同步入口

- `run_sync.bat` / `sync_code.ps1`：安全同步，只上传本地 AdaLigand 项目根，不删除远端目录。
- `run_syncWithClean.bat` / `sync_codeWithClean.ps1`：删除式同步，人类手动专用；agent 不擅自运行。

同步脚本会排除本地环境、缓存、测试输出和旧小样本产物：

```text
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
tests_output/
Data_Preprocessing/Ori_Data/tests_output/
mini-example/
mini-example-20/
mini-example-reorg/
resolution-check-30/
adaligand_stage1.egg-info/
```

## 历史 sbatch 草案位置

以下 Stage A/B/C array 脚本只保留为历史草案，不得用于当前正式全量 run：

```text
Data_Preprocessing/Ori_Data/sbatch/a.sbatch
Data_Preprocessing/Ori_Data/sbatch/b.sbatch
Data_Preprocessing/Ori_Data/sbatch/c.sbatch
```

历史约定：

- A：单任务，不使用 array。
- B：`--array=0-5`，每个 array task 申请 8 核，传给 joblib-loky 的 `--n_jobs` 为 7。
- C：`--array=0-5`，资源申请与 B 一致，建议通过 Slurm dependency 在 B 全部成功后运行。
- 数据根目录：`/storage/penghongen/AdaLigand/Ori_Data`
- sbatch 运行目录：`/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data`

当前正式入口是 `Data_Preprocessing/Ori_Data/sbatch/abc_full.sbatch`；其中 B 必须保持单节点、单 task、`n_jobs=1` 并复用已有下载。后继依次为 `de_full.sbatch`、`f_full.sbatch` 和只运行 analyze 的 `g_analyze.sbatch`，具体 run/Job ID 以 ExecPlan 为准。

## AI helper 使用纪律

`other\Invoke-PasswordSsh.ps1` 用于轻量远端命令、只读探测或把本地 LF 行尾的 bash 脚本通过 stdin 送给远端 `bash -s`。

注意：

- 不把密码写入项目文件。
- 不用 helper 跑正式数据处理、模型训练或重型推理。
- 远端写入默认只允许在用户明确授权的位置进行。
- `-InputFile` 传给远端 bash 时必须使用 LF 行尾。

## AdaLigand A–G 专用辅助入口

- `install_adaligand_tools.sh`：在用户目录安装并验证 Chimera 1.19 OSMesa、固定 MapQ 2.9.7 与 `mrcfile`；不写系统目录。正式 manifest 位于 `/home/penghongen/.local/opt/adaligand_tools_manifest.json`。
- `stage_adaligand_chimera_installer.ps1`：当服务器外网过慢时，把本机缓存的官方 Chimera installer 与固定 MapQ zip 用安全 rsync 上传；不使用删除式同步。
- `select_adaligand_smoke.py`：从正式 A 清单中选择覆盖 CCD/BRANCHED/缺原子/非默认 map geometry 的显式真实 smoke 子集。
- `probe_adaligand_server.sh`、`probe_adaligand_capacity.sh`、`probe_adaligand_map_sample.sh`：只读环境、容量和 map header 探测；不得代替 Slurm 跑正式计算。

真实计算入口位于 `Data_Preprocessing/Ori_Data/sbatch/`。`submit_real_smoke.sh` 先跑显式 PDB 子集并执行严格 success gate；只有 smoke 通过后才运行 `submit_full_pipeline.sh`。失败作业由本轮 job 自己的 `try_lock/after_lock` 控制，禁止操作无法精确归属的 lock。

AdaLigand 专用 core 保留四锁与动态 `run_cmd`：若 `/home/penghongen/run_cmd_${SLURM_JOB_ID}.sh` 已作为普通非空、非 symlink 文件存在，则直接复用；否则才由 sbatch 的 `write_adaligand_run_cmd` 生成。core 在首次和每次 `try_lock` 重试前都设为 `0700`、执行 `bash -n` 并记录 SHA-256。该机制用于保留 pending Job ID/FIFO 顺序的原地调参。预置文件必须对应本轮可精确归属的 job，使用同目录临时文件完成权限/语法/哈希检查后原子发布；`kill_lock → try_lock → 编辑 run_cmd → 删除 try_lock` 仅作为运行后故障回退。当前 CPU96 正式默认 D64/E24、F12×MapQ np=8，G 1 CPU；DE/F/G 不写 `--time`，依赖当前 `cpu` 分区 `MaxTime=UNLIMITED` 和 `Cpu96` 无 MaxWall 的集群事实。

## 316114 source-dirty 精确恢复（已完成）

本节只适用于 run `adaligand_ag_20260711T154658` 的既有 DAG `316114→316115→316116→316117`。不得取消或重提这些 Job，不得 clean sync，不得重跑 B；下游继续只由原 `afterok` 链释放。source repair、14-PDB 事务、386 receptor-only repair、2,156 post-exact、原 run id 无过滤全量 C 和 ABC gate 均已完成；最终 C status 为 22,386 行（22,056 skipped + 330 success）。316114 于 `2026-07-12T19:08:24` 以 `COMPLETED 0:0` 结束，`pre/try/after/kill_lock_316114` 与 `run_cmd_316114.sh` 均已由 core 清理。

已执行的恢复顺序固定为：

1. 用 `scripts/snapshot_source_dirty.py` 冻结 `2026-07-11T15:46:58+08:00 < st_mtime <= 2026-07-12T05:30:00+08:00` 的 mmCIF，预期 2,156 个 PDB；清单数量、路径与 SHA-256 写 run-scoped summary。
2. 使用独立 repair run id 运行 `scripts/c_source_repair.py --mode audit`；全集合必须为 `exact/atom_name_only` 且零 blocked/failed。
3. 使用同一清单、清单 SHA 和 repair run 运行 `--mode apply`；只允许受检 receptor-only 原子迁移。
4. 跳过 Stage B，随后以正式 run id、**不带 `--pdb_ids_file`** 重跑完整 22,386-PDB Stage C，并运行 `abc_release_gate.py`。任何 filtered smoke 都必须使用独立 run id，绝不能覆盖正式 C status。
5. 把上述命令写入 `/home/penghongen/run_cmd_316114.sh` 时，先在同目录临时文件完成 `chmod 0700`、`bash -n`、SHA-256 和普通文件/非 symlink 检查，再原子发布；全部证据通过后才删除 `/home/penghongen/try_lock_316114`。保留 `after_lock_316114`，成功后由现有 core/依赖机制收尾。

若未来审计证明历史 apply 有问题，不能直接重放旧 apply records；必须保留全部 run-scoped 证据并重新取得用户边界。316114 的运行中 TimeLimit 延长请求曾被 Slurm 以普通用户权限拒绝；这不授权取消/重排作业。

历史首轮证据：2,156-ID 清单 SHA-256 为 `fc6f0068a1cd1529346e90e265c7d5844df38b69d3087bde19b0237d5b135349`；v1 audit records SHA-256 为 `8a1336d06de15f4a0bef27539a8fb24d1cda96fe5c941e21a9fd6ae492109e38`，分类 exact=1,749、atom_name_only=379、blocked=23、failed=5。用户随后授权冻结 14-PDB 的 `CCD:5GP` ligand-side 完整 C rebuild，接受新增 20、删除 0 和 1,995 个 candidate_id 重排；before/after manifest 只作本次 run-scoped 审计，不改变通用科学契约。v2/v3 失败证据继续只读保留，v4 是成功恢复证据。

完整执行链为：本地实现/全套测试 → 安全同步 → `CH/0UO/BB9` cache-only 补足 → `CCD:5GP` 非覆盖 descriptor supplement → 14-PDB audit/prepare/manifest → 2,156 联合零阻断 gate → 14-PDB 四件套事务 → 通用 receptor-only apply → post-apply 2,156 全 exact → 原 run id 无 filter、无 `--overwrite` 的全量 C → ABC gate。不得把这条一次性历史链改写成通用科学契约或未来自动 rebuild 许可。

用户额外授权最多 48 CPU 用于独立测试、只读审计或依赖补足。额外资源必须有独立 Job ID、run id、日志和精确锁；CCD 补足必须在最终 audit 冻结前结束，final audit 开始后不得再改变输入。316114 的既有 96 核 allocation 始终是唯一正式 Stage C 写入者，额外作业不得并发写 canonical C 或正式 status。

`Data_Preprocessing/Ori_Data/sbatch/resume_abc_316114_source_v2.sh` 是本轮 try-lock 重启的唯一阶段感知恢复入口；脚本实现版本名保留 `source_v2`，当前正式 repair 证据使用 `adaligand_ag_20260711T154658_csrc_v4`。`csrc_v2` 保留缺 descriptor 的失败证据，`csrc_v3` 保留 14-PDB staging 成功但联合 gate 因旧 schema 过度阻断 41 条的失败证据；二者均不得覆盖或作为 v4 apply 输入。成功的 dependency supplement、专用 audit/pre-gate summary 必须只读复用；14-PDB rebuild apply 可按 receipt 幂等重放；generic receptor apply 若 partial/中断，必须换新的 `generic_attempt_N` run id 从当前 canonical 重做 audit→apply，绝不能复用旧 before records，也不能重新覆盖已经成功的 pre-rebuild audit。post-exact 使用独立 run id 和 `--require_all_exact`，不会覆盖 preapply 证据。

## 316115 MRC contract 放行与当前运行

Pocket Plus MRC 祖传迁移发生在 Stage E 前，D 本身不消费 MRC，但 316115 在同一 allocation 内并发执行 D/E，因此放行前曾整作业 hold。`/home/penghongen/run_cmd_316115.sh` SHA-256 为 `a1ca224dc23030aa483a5b102e55ed5f8860266d09f21542c1612aa0619a3cb0`；保留了原 Job ID、提交顺序、D64/E24 命令、96 CPU allocation 与 `afterok:316114`，没有取消或重提。

放行前必须依次完成：本地六函数零差异/薄适配/172 tests → 无删除安全同步 → 远端代码与 manifest 哈希复核 → 远端 Python 3.10 全套 172 tests → 真实 Chimera `molmap onGrid` smoke。上述条件已全部满足：正式 header audit run `adaligand_mrc_contract_audit_20260712T192000_v2` 只有 EMD-11978/12465 两张 mixed；真实 run `adaligand_mrc_geometry_smoke_20260712T200227` 使用对应 PDB 7b14/7nll，验证 actual voxel 非精确 1 Å、origin 非零、canonical/sim 同 shape/voxel/origin、标准轴和 `nstart=0`。其 ID/summary/report SHA-256 分别为 `41c7a456…cd56` / `0e40d866…96957` / `451a6dce…de5`。

全部代码/祖先/副本、正式 audit、测试和真实 smoke 哈希已写入 release 文件；`/home/penghongen/mrc_contract_release_316115` 于 `2026-07-12T20:21:28+08:00` 从同目录普通临时文件原子发布，权限 0600、SHA-256 `2ca92614cb53a9f08058a5186afe677264928b6a64ba2a4b60a044d8cea6b6b2`。既有 run_cmd 随后自行删除 `pre_lock_316115` 并打印 `[MRCContractRelease]`，没有人工删除。当前 D/E 日志已分别确认 `n_jobs=64` 与 `n_jobs=24`；`after_lock_316115` 在 DE release gate 完成前继续保留。

## 316115 Stage E 长尾截止与 resume v3

本节只记录正式 run `adaligand_ag_20260711T154658` 的一次性运行恢复，不建立未来自动排除规则。首个 18-ID repair 临时只使用 `n_jobs=2`，没有继承此前对各阶段冻结的实测资源结论，后来成为主线瓶颈；独立补足 job `316415` 因而在用户追加授权的 48 CPU 上以 `n_jobs=12` 运行标准 Chimera。`48 CPU/n_jobs=12` 是这批长尾的本轮执行参数，不是所有 repair 或所有 map 尺寸的通用最优值；以后必须先查当前 ExecPlan/项目记忆中的冻结基准，不能重新拍脑袋设并发。

用户冻结的绝对截止为 `2026-07-13T19:54:19+08:00`。截止时 `8j07/9dp7/9qwt` 已有并通过完整 `exp.npz + sim.npz + ligand_area.npz` 三件套，继续复用；`8glv/9e5c/9fqr` 只有 partial artifact，因此与既有 `8ckb` 一起进入当前 run 的 `exclusions.jsonl`。partial 的含义是三件套任一缺失或未通过既有 validator，不能因已经存在 E1 或 scratch 文件就算完成。排除项仍留在样本宇宙和状态分母，由 E/F 写 `known_failed:run_policy_excluded`，不得删除 `pair_list` 或伪造 success。

截止操作先冻结 predecision，再只对精确 job `316415` 创建 kill-lock。主进程组退出后仍发现三个孤儿 Chimera：PID `160147/160179/160191`，分别由完整用户/命令行/scratch 路径绑定到 `9e5c/9fqr/8glv`；逐 PID TERM/KILL 并复核不存在后才删除精确 `after_lock_316415`。该 job 最终为 `FAILED 9:0`，elapsed `06:04:02`，EndTime `2026-07-13T20:09:28+08:00`；这是授权截止的预期证据，且它不是正式 DAG 的依赖节点。predecision/posttermination/before/after/summary SHA-256 分别为 `40e7c949…458a8`、`0f20f20c…97397`、`b586cab2…257fe`、`380844d0…325f`、`f4a26a93…f4761`。

cutoff 实现 `code/long_tail_cutoff.py`、CLI `scripts/stage_e_long_tail_cutoff.py` 和 `sbatch/resume_de_316115_e_repair_v3.sh` 的 SHA-256 分别为 `50967227…97b54`、`bb600c7b…c490e`、`eabfad6b…09626`；本地与远端全套均为 207 tests passed。`/home/penghongen/e_long_tail_cutoff_release_316115` SHA-256 为 `cd06ec33…64cfa`。第一次只验证运行因 Windows 生成的 7 位小数 ISO 时间戳被服务器 Python 拒绝，期间精确 try-lock 保持且 E 未启动；仅规范化 marker 的 `released_at` 为 6 位小数后，`VALIDATE_ONLY=1` 才返回 `decision=run`。

最终 `/home/penghongen/run_cmd_316115.sh` SHA-256 为 `6e8c88a18472c07c76d6c9caf64472548d39db65ea3aef26d6540024e8e3d828`。它绑定上述证据和 resume v3，按阶段状态决定运行或复用；2026-07-13 21:04:43 已以正式 run id、无 filter、无 `--overwrite`、E24 启动全量 Stage E。当前 `after_lock_316115` 必须继续保留，`try/kill_lock_316115` 均不存在，`316116/316117` 继续按原 afterok 链等待。若正式 E 再失败，只能在进程退出且精确 try-lock 出现后取证、修复和受检更新 run_cmd；不得手工删除 after-lock、取消重提原 DAG 或 clean sync。
