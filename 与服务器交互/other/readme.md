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
- `sync_wandb_remote.bat` / `sync_wandb_remote.ps1`：通用 W&B 离线 run 快照同步入口，由调用者显式给出远端根目录。
- `sync_stage1_wandb_remote.bat` / `sync_stage1_wandb_remote.ps1`：AdaLigand Stage1 一键入口。双击 `.bat` 会扫描固定根目录 `/home/penghongen/My_Project/tmp/adaligand_stage1_20260721T024000/allocations`，同步其下全部 `offline-run-*`，覆盖 `unet_c1`、`Find_0`、`Find_1`、`Find_2` 及后续 CPC 阶段在该任务范围中生成的离线 run。它不扫描其他项目，不包含在线 run，不删除或修改服务器文件，并固定使用 `wandb sync --no-mark-synced`。

Stage1 一键入口默认执行真实同步，并在结束后保留窗口供查看结果。只读预览可在 PowerShell 中执行：

```powershell
& ".\与服务器交互\sync_stage1_wandb_remote.ps1" -DryRun
```

DryRun 只列出将同步的远端 run，不下载、不上传。真实同步会把每个远端 run 快照下载到本地临时会话目录，成功上传后只清理由工具自身创建且带 sentinel 的临时会话；不删除、改名或标记任何既有本地/服务器日志。同步失败时会保留该临时会话供排查。

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

## 历史 sbatch 草案

早期 Stage A/B/C array 脚本 `a.sbatch`、`b.sbatch`、`c.sbatch` 已从当前目录删除，不得用于新的正式任务；需要核对历史时，从提交 `817940a1682216cb54308a0a0aa87fd76e1216f0` 读取，不要把它们恢复成当前入口。

历史约定：

- A：单任务，不使用 array。
- B：`--array=0-5`，每个 array task 申请 8 核，传给 joblib-loky 的 `--n_jobs` 为 7。
- C：`--array=0-5`，资源申请与 B 一致，建议通过 Slurm dependency 在 B 全部成功后运行。
- 数据根目录：`/storage/penghongen/AdaLigand/Ori_Data`
- sbatch 运行目录：`/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data`

当前正式入口是 `Data_Preprocessing/Ori_Data/sbatch/abc_full.sbatch`；其中 B 必须保持单节点、单 task、`n_jobs=1` 并复用已有下载。后继依次为 `de_full.sbatch`、`f_full.sbatch` 和只运行 analyze 的 `g_analyze.sbatch`，具体 run/Job ID 以 ExecPlan 为准。

## AI helper 使用纪律

`other\Invoke-PasswordSsh.ps1` 是项目薄入口，实际调用本机统一入口 `%USERPROFILE%\.codex\tools\Invoke-ProjectSsh.ps1`。统一入口默认读取本机私有密码文件 `%USERPROFILE%\.ssh\pocket_plus_sshpass.txt`，因此 AI agent 不需要把密码写入命令。

执行轻量远端命令：

```powershell
& ".\与服务器交互\other\Invoke-PasswordSsh.ps1" -Command "hostname"
```

通过 master 直接检查计算节点：

```powershell
& ".\与服务器交互\other\Invoke-PasswordSsh.ps1" `
  -TargetHostName "gnode09" `
  -Command "hostname; nvidia-smi; ps -ef; squeue"
```

把 LF 行尾的本地 bash 脚本交给服务器执行：

```powershell
& ".\与服务器交互\other\Invoke-PasswordSsh.ps1" `
  -Command "bash -s" -InputFile ".\tmp\probe.sh"
```

注意：

- 统一入口固定使用 `StrictHostKeyChecking=yes`；未知或变化的主机密钥必须停止并由人类核验。
- 只对认证前断连、连接重置、拒绝和超时进行有限退避重试；认证失败不重试。
- 若连接在 SSH 协议横幅或密钥交换前持续关闭，先关闭或调整 ATrust 等 VPN 后重试；本机已确认 ATrust 会干扰该私网地址的新连接。
- 密码只存在于本机私有文件和 SSH 子进程的临时环境中，不写入项目、release、日志或服务器。
- 不用 helper 跑正式数据处理、模型训练或重型推理。
- 远端写入默认只允许在用户明确授权的位置进行。
- `-InputFile` 传给远端 bash 时必须使用 LF 行尾。

### SSH 主机密钥基线

`penghongen@10.102.33.220:10022` 于 2026-07-15 发生过一次三种主机密钥同时变化。用户确认 endpoint、账号和密码未变，并明确授权恢复连接；三次独立 `ssh-keyscan` 观察完全一致，随后在严格主机校验下登录，并以 `master` 主机名、AdaLigand 固定目录、正式 run、Slurm Job ID 和历史时间线完成连续性核验。当前受信任指纹为：

- ED25519：`SHA256:wRrXzA2Yf/RD2+C0KnLOhdpg7pVNPLo9XnCCIlNP8yg`
- ECDSA：`SHA256:/B9db9yFvST5K4l+yW7UznZnghbtt4XGSSuhAD0dXPE`
- RSA：`SHA256:jWyUeF87w5UXCkurG/m1vwjBTjiOS8hQb7GTVFwozJo`

本机 `%USERPROFILE%\.ssh\known_hosts` 已只替换该精确 endpoint 的条目，更新后文件 SHA-256 为 `bc8a377526f81c42b7c69ab47ff3619c80191890d7fb6bba876054c3bdcbc4c4`；旧文件应保留带时间戳的同哈希备份。该记录不包含密码，也不授权未来自动接受新的密钥变化。若指纹再次变化，必须停止认证，不得使用 `StrictHostKeyChecking=no`；先备份旧 pin，再重复稳定采样、取得用户授权并核对主机/项目/Slurm 连续性。

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

全部代码/祖先/副本、正式 audit、测试和真实 smoke 哈希已写入 release 文件；`/home/penghongen/mrc_contract_release_316115` 于 `2026-07-12T20:21:28+08:00` 从同目录普通临时文件原子发布，权限 0600、SHA-256 `2ca92614cb53a9f08058a5186afe677264928b6a64ba2a4b60a044d8cea6b6b2`。既有 run_cmd 随后自行删除 `pre_lock_316115` 并打印 `[MRCContractRelease]`，没有人工删除。D/E 日志分别确认 `n_jobs=64` 与 `n_jobs=24`；`after_lock_316115` 在 DE release gate 闭合前始终保留。

## 316115 Stage E 长尾截止与 resume v3

本节只记录正式 run `adaligand_ag_20260711T154658` 的一次性运行恢复，不建立未来自动排除规则。首个 18-ID repair 临时只使用 `n_jobs=2`，没有继承此前对各阶段冻结的实测资源结论，后来成为主线瓶颈；独立补足 job `316415` 因而在用户追加授权的 48 CPU 上以 `n_jobs=12` 运行标准 Chimera。`48 CPU/n_jobs=12` 是这批长尾的本轮执行参数，不是所有 repair 或所有 map 尺寸的通用最优值；以后必须先查当前 ExecPlan/项目记忆中的冻结基准，不能重新拍脑袋设并发。

用户冻结的绝对截止为 `2026-07-13T19:54:19+08:00`。截止时 `8j07/9dp7/9qwt` 已有并通过完整 `exp.npz + sim.npz + ligand_area.npz` 三件套，继续复用；`8glv/9e5c/9fqr` 只有 partial artifact，因此与既有 `8ckb` 一起进入当前 run 的 `exclusions.jsonl`。partial 的含义是三件套任一缺失或未通过既有 validator，不能因已经存在 E1 或 scratch 文件就算完成。排除项仍留在样本宇宙和状态分母，由 E/F 写 `known_failed:run_policy_excluded`，不得删除 `pair_list` 或伪造 success。

截止操作先冻结 predecision，再只对精确 job `316415` 创建 kill-lock。主进程组退出后仍发现三个孤儿 Chimera：PID `160147/160179/160191`，分别由完整用户/命令行/scratch 路径绑定到 `9e5c/9fqr/8glv`；逐 PID TERM/KILL 并复核不存在后才删除精确 `after_lock_316415`。该 job 最终为 `FAILED 9:0`，elapsed `06:04:02`，EndTime `2026-07-13T20:09:28+08:00`；这是授权截止的预期证据，且它不是正式 DAG 的依赖节点。predecision/posttermination/before/after/summary SHA-256 分别为 `40e7c949…458a8`、`0f20f20c…97397`、`b586cab2…257fe`、`380844d0…325f`、`f4a26a93…f4761`。

cutoff 实现 `code/long_tail_cutoff.py`、CLI `scripts/stage_e_long_tail_cutoff.py` 和 `sbatch/resume_de_316115_e_repair_v3.sh` 的 SHA-256 分别为 `50967227…97b54`、`bb600c7b…c490e`、`eabfad6b…09626`；本地与远端全套均为 207 tests passed。`/home/penghongen/e_long_tail_cutoff_release_316115` SHA-256 为 `cd06ec33…64cfa`。第一次只验证运行因 Windows 生成的 7 位小数 ISO 时间戳被服务器 Python 拒绝，期间精确 try-lock 保持且 E 未启动；仅规范化 marker 的 `released_at` 为 6 位小数后，`VALIDATE_ONLY=1` 才返回 `decision=run`。

最终 `/home/penghongen/run_cmd_316115.sh` SHA-256 为 `6e8c88a18472c07c76d6c9caf64472548d39db65ea3aef26d6540024e8e3d828`。它绑定上述证据和 resume v3，按阶段状态决定运行或复用；2026-07-13 21:04:43 以正式 run id、无 filter、无 `--overwrite`、E24 启动全量 Stage E。正式 E 未再进入 try-lock；core 在 DE gate 成功后按既有 afterok 链正常结束，不曾取消或重提原 DAG，也未运行 clean sync。

## 316115 DE 闭合与 316116 F 启动

`316115` 于 `2026-07-14T01:26:42+08:00` 以 `COMPLETED 0:0` 结束。D 四终态为 22,339 success、3 skipped、44 known；E 四终态为 22,309 skipped-valid、77 known，unknown、duplicate、silent missing 均为 0。E status SHA-256 为 `3a0d4148…c54c`，`de_release` success marker SHA-256 为 `ab49f43c…da6`。不能只凭 Slurm 退出码宣称闭合：本次转换分别复核了完整 status/release gate、风险分层 E1/E2/E3 artifact、以及四条 run-only exclusion 与 2zhc `model_map_frame_mismatch` 的终态/provenance，三路独立审计均为 PASS。

`316116` 于同一时刻由 `afterok:316115` 自动启动；core 日志确认 `reusing preloaded file`、预置 run_cmd SHA-256 `8399d571…d13` 与 `F_N_JOBS=12`。2026-07-14 04:05 的只读快照为 944 个外层任务完成，874 份早期完整质量三件套（`quality/{pdb_id}.jsonl`、`quality_atoms/{pdb_id}.npz`、`quality/{pdb_id}.provenance.json`）抽查通过四 CC、配体/6 Å 口袋 Q、schema v3 空口袋、MapQ `sigma=0.4,np=8` 和 provenance 契约。`after_lock_316116` 存在，`try/kill_lock_316116` 不存在；四条 exclusion 的最终 F 终态要等全量状态写出后复核。`316117` 保持依赖等待且只运行 analyze，不执行示例阈值或写 `keep_list`。

## 316116 Stage F 长尾截止与原位恢复

本节只记录正式 run `adaligand_ag_20260711T154658` 的一次性 Stage F 运行决策，不建立未来自动超时或批量排除规则。首轮 F12 在 635.4 分钟推进到 22,363/22,386；只读 py-spy、调度/进程和 artifact 证据把唯一仍在执行的 worker 绑定到 `6kgx`。其外部 Chimera/MapQ 已完成，但 1,588 个 occurrence 向 1,011,574 行规范化模型原子投影时反复扫描全表，公开 `quality/6kgx.jsonl + quality/6kgx.provenance.json + quality_atoms/6kgx.npz` 均未形成。该事实属于 post-MapQ Python 工程性能长尾，不能误记成 Chimera/MapQ 科学失败。

用户明确要求按此前长尾策略把当前样本记为超时。操作只针对精确 job `316116`：冻结六份原始证据后创建 `kill_lock_316116`，core 记录退出 137、创建 `try_lock_316116`；`after_lock_316116` 全程保留，`316117` 始终为 `PENDING (Dependency)`。共享 `exclusions.jsonl` 保持 Stage E 已绑定的 SHA-256 `380844d0…325f`，另建只供 F 消费的加法视图 `exclusions.stage_f.jsonl`，SHA-256 `3b10abb5…8ee8`；原 `8ckb/8glv/9e5c/9fqr` 四条逐字段不变，仅追加 `6kgx` 的 `stages=["stage_f"]` run-only 记录。样本仍留在 22,386 宇宙和 F 状态分母，由 F 写 `known_failed:run_policy_excluded`，不得伪造质量三件套或删除上游条目。

恢复实现分别由 Git `bf60084` 与 `e44b933` 冻结；专项 23 tests、本地/远端全套 214 tests、`bash -n` 和两次独立审查通过。六份原始证据和 before/after/pre/post/summary 位于 `/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_ag_20260711T154658/stage_f_long_tail_cutoff_20260714T2213/`；before/after/summary SHA-256 为 `380844d0…325f` / `3b10abb5…8ee8` / `8b687f1a…53a3`。resume、release marker、最终 run_cmd SHA-256 为 `e6b357b2…9748` / `f59b09c8…5bc3` / `bd7edb94…5ffa`。先在 try-lock 内执行 apply-only，再执行真正只读的 `VALIDATE_ONLY=1`；前后全部 manifest、证据、测试日志、release 和 run_cmd 哈希完全一致，且无 F/Loky/Chimera/MapQ 残留进程后，才删除精确 try-lock。core 于 `2026-07-14T22:46:44+08:00` 复用受检 run_cmd，以原 run id、F12、无 filter、无 `--overwrite` 恢复；不得取消/重提原 job，也未运行 clean sync。

## CPU96 调度事实与 318350 Stage F 尾段补算

2026-07-15 的只读调度复核确认：`cpu` 分区有 `cnode01/02/04/05` 四台 96 CPU 节点，不 oversubscribe；用户 `Cpu96` QoS 的 `MaxTRESPU cpu=192`、`GrpTRES cpu=576`。96 核作业必须等待一台完整空闲节点；本轮提交前 `cnode01` 全空闲，因此单个 CPU96 补算是零排队方案。若完整节点槽位不存在，必须先读实时队列再评估 16 核 array 或已经授权的备用分区，不能取消/重提正式 DAG 来“抢”节点。

用户授权的本轮主用 CPU 是 192，另有 48 CPU 用于测试、审计或备用。这个授权不覆盖服务器 QoS：正式与补算各占 96 后，`Cpu96` 已达到用户 192 CPU 上限，额外 48 不能在同一 QoS 下同时启动；只能等待一个 96 核 allocation 释放，或先验证另一个 partition/QoS。任何后续 Agent 都不得把它误读为“当前可同时申请 240 CPU”。

正式 `316116` 保持原 run、F12×MapQ np8、状态、release、锁和 `afterok:316117` 不变。实测其平均活跃 CPU 约 43–44，但 MapQ 峰值仍可能达到 96；因此不能凭平均值把正式 F_N_JOBS 翻倍。独立补算 `318350` 使用 run `adaligand_ag_20260711T154658_fsupp96_v1`，在 `cnode01` 运行第二份 F12×MapQ np8，只处理尾段 `[19386,22386)` 的 2,990 个 eligible PDB。plan/ID SHA-256 为 `1d5c12172629bcba2af65a379c2c78d9bf7141fdcdd505e699add8b58b1dff4f` / `acacde79c2a5a8727949cdc0a986930aa8404419a8edaabfb264f4f05dacea80`；正式 pair list 与 Stage F exclusion SHA-256 为 `6c736180…35f8` / `3b10abb5…8ee8`。

planner 冻结了正式进度 6,248、碰撞停止阈值 17,386 和 2,000-task guard。守护器绑定正式 job/run/stderr device+inode 与资源契约，每 300 秒检查正式进度；阈值到达后 TERM→KILL 补算 child PGID、写 stop marker，并且不跑补算 gate。真实 kill-lock 也先收口 child PGID，再处理外层进程组。`318350` 于 `2026-07-15T16:23:59+08:00` 零等待启动，`after_lock_318350` 和 child PGID 文件存在，try/kill 不存在；正式 `316116` 同时继续在 `cnode04` 运行，两项总分配恰为 192 CPU。补算三件套只能由正式 F 的 validator 复用；Stage G 仍只由正式 `f_release` 释放。

以后设计 repair/补算时必须先查 ExecPlan、sbatch 和项目记忆中的冻结实测并发；不得用代码默认值或“保守”直觉把正式并发静默降级。确需偏离时，在启动前记录原/新参数、样本分层、CPU/内存/I/O、关键路径、互斥边界和用户授权。当前 2,990 尾段预计约 16.6 小时、正式流到 guard 约 31 小时、净节省约 14–16 小时；这些是本轮估算，不是未来 F 的通用吞吐保证。
