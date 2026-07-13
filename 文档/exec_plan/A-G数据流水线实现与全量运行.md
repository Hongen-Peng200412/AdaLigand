# 完成 AdaLigand A–G 数据流水线并全量运行

本 ExecPlan 是动态文档。执行期间必须持续维护 `Progress`、`Surprises & Discoveries`、`Decision Log` 与 `Outcomes & Retrospective`，使只持有当前工作树和本文件的新手工程师或无上下文 AI agent 能够继续完成任务。

上游规格是 `文档/规划文档/数据处理_v2.md`；本计划与它的关系为 **implements and updates**。覆盖范围是现有 22,386-PDB 样本宇宙的 A–C 增量契约迁移、D–G 实现、Chimera/MapQ 集成、自动质量门、服务器全量运行和 G `analyze` 质量分布。最终 `keep_list.jsonl` 只有在正式分布产出、用户另行确认四类阈值后才进入后续授权，不属于本轮无人值守终点。旧执行日志 `文档/exec_plan/数据下载与解析.md` 只记录历史 A–C 实现，本文件从该基线继续推进。代码旁契约是 `Data_Preprocessing/Ori_Data/code/readme.md`，映射索引是 `文档/mapping/计划执行映射.md`。

本轮不切 BOX，不实现 BOX 第 2/3 层，不修改或重训 Stage 1，也不处理 Stage 2/3。Stage 1 重训将在 A–G 与后续 BOX 接缝完成后另行授权。

## Purpose / Big Picture

完成后，服务器数据根 `/storage/penghongen/AdaLigand/Ori_Data` 将在复用已有下载和旧 A–C 产物的前提下达到当前契约：C 产物包含配体质心、受体化学键、49 维受体特征和去重配体描述子；D 产出受体原子标签；E 通过 Pocket Plus 祖传原语产出 target=1 Å、保存实际 voxel 的实验图、严格去掉全部 `HETATM` 的 receptor-only 模拟图和逐 occurrence ligand-area；F 产出四种全局 map-model CC、配体逐原子 Q、6 Å 受体口袋逐原子 Q 及两类 occurrence 聚合；G 汇总质量和明确失败，先生成可追溯分布，并在用户确认四类阈值后生成 `keep_list.jsonl`。流水线由 Slurm 依赖自动推进，smoke gate 通过后无需人工复制日志或逐阶段确认。

可观察结果包括：所有成功样本的数组 shape、dtype、坐标系和主键均通过机器检查；每个未成功样本都有 run-scoped `failed_reason`；重复无覆盖运行只补缺项；最终报告能说明每个阶段成功、跳过、已知失败和未知失败的数量。

## Progress

- [x] (2026-07-10 14:38+08:00) 完成计划/代码/服务器旧产物只读审计，确认 A=22,386 PDB、B 缺约 176 个唯一 map、C 仍是旧契约、D–G 未实现。
- [x] (2026-07-10 14:38+08:00) 与用户冻结本轮边界、科学语义、资源权限、Chimera 非商业许可和自动恢复权限。
- [x] (2026-07-10 14:38+08:00) 启动 `execplan` 动态记录并审计 CPU/A100/lock 模板；确认旧 Pocket Plus 模板不能直接运行。
- [x] (2026-07-10 14:42+08:00) 建立改动前本地基线：项目 `.venv` 可导入 gemmi 0.7.5、NumPy 2.4.6、SciPy 1.17.1、RDKit 2026.03.3；现有测试 21 passed、1 failed。
- [x] (2026-07-10 15:05+08:00) 修复 Windows JSONL 解锁回归；实现并测试受体 49 维纯函数、受体 backbone/disulfide 键语义和配体描述子纯函数，当前 30 tests passed。
- [x] (2026-07-10 23:29+08:00) 完成 Stage C schema-aware 增量迁移：旧核心字段逐项不变才原子升级，补齐 `centroid_atom`、受体键表、49 维特征和去重描述子；最小真实 mmCIF 测试证明二次运行幂等。
- [x] (2026-07-10 23:29+08:00) 当时完成一版独立 canonical MRC 几何核心及合成回归（46 tests）；该实现后来被真实 actual-voxel 核验证明不可用于 Stage E，已由 2026-07-12 的 Pocket Plus 祖传基线迁移取代，保留本条只记录时间线。
- [x] (2026-07-11 00:12+08:00) 建立共享契约、run-scoped 四终态、A–C release gate、密度/CC/Q-score QC 与 schema-aware 完成判据；legacy 失败文件不再参与本轮 gate。
- [x] 实现 Stage C 增量升级：`centroid_atom`、受体键表、`feat(N,49)`、`ligand_descriptors`，并证明旧字段行序不变和二次运行幂等。
- [x] (2026-07-11 00:12+08:00) 实现 Stage D 原子标签及契约检查；4 Å 含等号、背景真实距离、稀疏 cid 与等距稳定决胜均有测试。
- [x] (2026-07-11 00:12+08:00) 首次实现 Stage E target=1 Å canonical 实验图、strict ATOM-only receptor 模拟图、局部 stencil ligand-area 与三维内容 QC；其中 MRC 加载/重采样内核随后按祖传基线受检替换，其他 E 契约继续保留。
- [x] (2026-07-11 00:12+08:00) 实现 Stage F 四种 CC、MapQ 2.9.7 固定适配、逐原子严格身份映射、occurrence 聚合与 provenance。
- [x] (2026-07-11 00:12+08:00) 实现 Stage G 分布分析、显式配置过滤和最终 release gate；最终阈值仍按上游约定等待正式分布，analyze 模式不会伪造 `keep_list`。
- [x] (2026-07-11 15:46+08:00) 本地补齐纯函数、CLI 导入、fake external tool、负例和合成 A–G smoke；加入显式 PDB 子集入口、大图 provenance I/O 优化、真实 Chimera/MapQ/空口袋/错位 CC 回归后，94 tests passed，compileall、服务器全部 sbatch/shell `bash -n` 与 `git diff --check` 通过。
- [x] (2026-07-11 10:13+08:00) 完成服务器只读资源/环境/容量探测：AdaLigand Python 3.10 核心依赖齐全，仅缺 `mrcfile`；CPU96 节点可用，A100 保持备用；抽样估算 E/F 全量三套密度约需 9.93 TB，初始并发锁定为 8。
- [x] (2026-07-11 15:04+08:00) 按用户新增需求实现 occurrence 级 6 Å 受体口袋 Q：复用同一次全模型 MapQ，保存有序 pocket atom_site.id/逐原子 Q 与 mean/median/min/count/radius；固定包络并集、零口袋失败和合成端到端已进入 90 项全套回归。
- [x] (2026-07-11 11:17+08:00) 通过无删除安全同步上传代码；在用户目录安装并验证 Chimera 1.19 OSMesa、MapQ 2.9.7 固定包与 mrcfile 1.5.4，工具清单落在 `/home/penghongen/.local/opt/adaligand_tools_manifest.json`。
- [x] (2026-07-11 15:45+08:00) 真实 smoke `adaligand_smoke_20260711T113733` / job `316073` 最终 `COMPLETED 0:0`：三 PDB 的 C/D/E/F 严格门禁通过，99 occurrence 中 97 个正常口袋、2 个显式空口袋；job `316109` 的 12 Å 错位 CC 负对照也 `COMPLETED 0:0`。
- [ ] (2026-07-11 15:47+08:00) 全量 run `adaligand_ag_20260711T154658` 已提交：ABC `316114` → DE `316115` → F `316116` → G analyze `316117`；ABC 已完成，DE 在同一 96 核 allocation 内完成 MRC 放行前 hold，F/G 继续依赖等待，整条 DAG 尚未完成。
- [x] (2026-07-12 00:24+08:00) 长周期监控改为阶段感知策略：Codex heartbeat 从每 30 分钟降为每 2 小时；正常运行只静默记录，阶段切换、失败或契约异常才通知，并在 release gate、异常诊断和最终 QC 时临时启用多智能体独立审计。
- [x] (2026-07-12 02:58+08:00) 用户确认保留原 Job ID 的原地调度方案：pending core 支持预置普通文件 run_cmd，并在首次及每次 retry 前拒绝 symlink、检查非空/`0700`/`bash -n`、记录 SHA-256；本地全套增至 97 tests passed，shell/sbatch 语法与 `git diff --check` 通过。
- [x] (2026-07-12 02:58+08:00) 不取消或重提既有 DAG；原子预置 `316115` 的 D64/E24 run_cmd（SHA-256 `54658b7a4c2819793a22282ac21a005bfdc6fe1f6c48d4a006c760be2cd380b0`）和 `316116` 的 F12 run_cmd（SHA-256 `8399d571bab44881facbeaa9dd1e738594255a4b4212605cfe418878744f7d13`），将 `316115/316116/316117` 原地改为 `TimeLimit=UNLIMITED` 后 release `316115`；提交时间、CPU 数与 afterok 链均保持不变。
- [x] (2026-07-12 07:11+08:00) ABC 写出完整 B/C 状态后由 release gate 正确阻断：B 为 20,080 skipped、545 success、1,761 known_failed；C 为 22,017 success、3 skipped、366 unknown_failed。`316114` 保留 allocation 并进入精确 `try_lock`，DE/F/G 仍只等待 dependency，未产生下游污染。
- [x] (2026-07-12 07:32+08:00) 将 336 个 `AtomValenceException` 定位为 descriptor 临时 RDKit Mol 的过严全消毒，并把 mmCIF 意外刷新的根因定位为“前 1 MiB 必须出现 `_atom_site.`”的错误复用判据；完成两项非契约修复和回归，全套增至 102 tests passed，compileall 与 `git diff --check` 通过。
- [x] (2026-07-12 10:18+08:00) 用户显式接受两项契约：受体合法 `TRIPLE` 以向后兼容 `triple=6` 追加；接受本轮当前 RCSB mmCIF，但必须先审计全部 source-dirty 集合，仅对严格 `atom_name_only` 做 receptor-only 迁移。
- [x] (2026-07-12 11:05+08:00) 完成 `triple=6`、cache-only source audit、五直接输入 + LigandObject/CCD/实现依赖冻结、严格 CCD 身份/name/元素覆盖、全局 preflight、per-PDB CAS/原子修复、filtered 正式状态覆盖防护和回归；全套 119 tests passed，compileall 与 `git diff --check` 通过。
- [x] (2026-07-12 11:34+08:00) 服务器安全同步并在 316114 allocation 复验 119 tests；冻结 2,156-ID source-dirty 清单，SHA-256 `fc6f0068a1cd1529346e90e265c7d5844df38b69d3087bde19b0237d5b135349`。6 样本只读 smoke 为 exact=4/atom_name_only=2。
- [x] (2026-07-12 12:53+08:00) 完成 2,156 全集正式只读 audit，records SHA-256 `8a1336d06de15f4a0bef27539a8fb24d1cda96fe5c941e21a9fd6ae492109e38`；结果 exact=1,749、atom_name_only=379、blocked=23、failed=5。脚本按设计退出 1，未 apply、未修改 receptor、未动 try_lock/after_lock。
- [x] (2026-07-12 13:25+08:00) 用户授权对冻结的 14-PDB `CCD:5GP` 集合按当前 source 完整重建 Stage C，接受新增 20、删除 0 和 1,995 个既有 occurrence 的 `candidate_id` 重排；before/after manifest 仅作本次 repair run 的阶段性审计证据，不进入科学契约或下游字段。下游网络尚未训练，不存在旧主键消费者。
- [x] (2026-07-12 14:45+08:00) 本地实现 changed-residue-only 严格 CCD coverage、atom-name derived-delta 门禁、显式 CCD prefetch、14-PDB 独立 audit/prepare、联合 pre-apply gate 与带完整 backup/journal/rollback 的四件套事务；补回 auth-only `_struct_conn` 回归、CLI 哈希闭环、all-exact 硬门和阶段感知 try-lock 恢复脚本，本地全套 136 tests passed，尚未安全同步或写正式 C。
- [x] (2026-07-12) 完成无删除安全同步并在 316114 allocation 复验 136 tests；`CH/0UO/BB9` 显式 CCD prefetch 3/3 成功。`csrc_v2` 的 14-PDB rebuild audit 因缺少 `ligand_descriptors/CCD_5GP.npz` 按设计 14/14 fail-closed，migration 为空；未进入 2,156 gate，未产生 apply/backup/transaction 或 canonical C 写入。
- [x] (2026-07-12) 新增 `c_descriptor_prefetch.py` 业务模块与 CLI：冻结 `CCD:5GP` object-key 文件及 SHA，以 `overwrite=False` 从既有 LigandObject 补 descriptor，记录源/实现/产物哈希，成功复用时重新验证全部证据，失败/半写证据拒绝覆盖。恢复 run 改为 `csrc_v3` 以保留 v2 失败证据；本地全套 146 tests、`compileall`、wrapper `bash -n` 通过。
- [x] (2026-07-12) v3 安全同步与远端 146 tests 通过；`CCD:5GP` descriptor 实际 materialized，源/产物 SHA 分别为 `3c5fd52f…aae13` / `28a46620…f34f49`。14-PDB staging 精确通过 14 ready、+20/-0、1,995 reassigned，records/manifest SHA 分别为 `7c1c69c6…72ae2` / `83171f90…0d625`。
- [x] (2026-07-12) v3 的 2,156 联合 gate 正确 fail-closed：exact=1,756、atom_name_only=345、delegated=14、blocked=41。41/41 唯一原因都是 `atom_name` 变化加 `old_receptor_incomplete`；无其他 base/ligand 漂移。定位为实现把“缺派生比较基线”误当派生差异；未 apply、未解锁、canonical C 零写入。
- [x] (2026-07-12) 窄修复旧 schema 分类：只有旧 receptor 已完整时才比较 derived；旧 schema 不完整且唯一 base 差异为 atom name 时允许受检 apply 补齐三项派生数组，ligand 漂移和非 atom-name base 漂移仍阻断。新增 3 个回归，本地全套 149 tests 通过；恢复证据切换 `csrc_v4`，保留 v2/v3 失败证据。
- [x] (2026-07-12) v4 正式恢复已完成 14-PDB commit、386 receptor-only repair 和 post-exact=2,156；原正式 run id 的无过滤全量 C 已进入最后单样本长尾。独立 MRC 检验同时证明当时的 AdaLigand 自研 `make_canonical_grid` 把 `ceil(shape)` 与强制声明 1 Å 混用；A–C 与 D 未消费该函数，因而能在 E1 前安全替换为祖传基线。
- [x] (2026-07-12) 在 316115 仍为 `PENDING (Dependency)` 时原子安装 MRC contract hold：`run_cmd_316115.sh` SHA-256 `a1ca224dc23030aa483a5b102e55ed5f8860266d09f21542c1612aa0619a3cb0`，精确创建 `/home/penghongen/pre_lock_316115`，并要求缺省不存在的 `/home/penghongen/mrc_contract_release_316115` 才能放行；不取消、不重提、不改变原依赖链。
- [x] (2026-07-12) 按用户明确边界完成 Pocket Plus MRC 祖传基线本地接入：vendoring 时 HEAD `f4c3e5ce…40570`、文件最后修改 commit `a8380721…7ed80`，六函数源码/AST 零差异，祖先 SHA `d8e543e4…06ca8`、副本 SHA `acf74c25…8a45`，manifest 与 parity 测试落盘；Git checkpoint `6de3fb8` 只提交该祖传快照。
- [x] (2026-07-12) AdaLigand 仅保留 `Path/MapGrid/float32` 薄 wrapper、native=True/generated=False origin mode、标准 MRC writer、E1/E2/E3 schema v2、actual-voxel QC 与 lineage provenance；非单位 voxel/非零 origin 的合成 C→G smoke 通过，本地全套 153 tests 与 compileall 通过。
- [x] (2026-07-12) ABC gate 正式通过：`316114 COMPLETED 0:0`，22,386/22,386 C release-ready，1,761 个 B 下载失败均为显式 known failure。`316115` 已取得原 96 核 allocation，但日志确认只在 `[MRCContractHold]` 等待；D/E 进程和产物均未启动。
- [x] (2026-07-12) 在 `316115` allocation 内用 48 核完成正式 header-only 审计 `adaligand_mrc_contract_audit_20260712T192000_v2`：22,274 唯一 EMDB 中 22,269 header 可读，all_diff=21,941、all_equal=326、mixed=2，另 5 张缺图；risk 仅 EMD-11978/12465 与五个 B known failure。summary/risk SHA 为 `a9300d2d…44a7fe8` / `81784ee1…3a6712`。
- [x] (2026-07-12) 保持 Pocket grid 不变，新增只在 mixed-axis 触发的 `np.any` 薄兼容；E1 保存 native/scale/canonical contour 和 shape/mode provenance，F 只消费 canonical contour。常数/odd/random-mask/混合轴/合成 C→G 回归通过，本地全套增至 170 tests。
- [x] (2026-07-12 20:04+08:00) MRC 接入已无删除安全同步；远端代码哈希与本地一致，本地/服务器 Python 3.10 均为 172 tests passed。真实 smoke `adaligand_mrc_geometry_smoke_20260712T200227` 让 7b14/7nll 两张 mixed 图通过真实 Chimera `onGrid`、非精确 1 Å actual voxel、非零 origin、标准轴、`nstart=0`、真三维内容和 canonical/sim 几何闭合；summary/report SHA 为 `0e40d866…96957` / `451a6dce…de5`。316115 仍保持 hold，等待独立 release audit 与原子 marker。
- [x] (2026-07-12 19:08+08:00) v4 已完成依赖补足、14-PDB audit/prepare、2,156 联合零阻断 gate、受检 full rebuild、386 receptor-only apply、2,156 post-exact、原 run id 无过滤全量 C 和 ABC gate；316114 为 `COMPLETED 0:0`，未重跑 B。
- [x] (2026-07-12 20:02+08:00) 按“一个可验证任务一个精确提交”整理累计工作树：祖传快照、header 审计、contour 分布、Stage C 修复/事务、D、工具适配、E、F/G、release smoke、Slurm 与服务器工具均已有独立 Git checkpoint；暂存均使用精确路径，未使用 `git add -A`、未改写历史。
- [x] (2026-07-12 20:21+08:00) 独立 MRC release audit 判定无阻断；把祖传/代码/run_cmd、持久 172-test、header audit、真实 smoke 与无 D/E 污染快照写入普通临时文件并原子发布 `/home/penghongen/mrc_contract_release_316115`，marker SHA-256 `2ca92614…b6b2`。既有 run_cmd 自行删除 pre_lock 并记录 `[MRCContractRelease]`；D64/E24 已实际启动，日志分别出现 `Parallel(n_jobs=64)` 与 `Parallel(n_jobs=24)`。
- [x] (2026-07-13 06:27+08:00) Stage D/E 首轮全量运行完成写状态但被 gate 正确阻断：D 为 22,339 success、3 skipped、44 `no_occurrences`、0 unknown；E 为 22,295 success、72 known_failed、19 unknown。316115 保留原 96 核 allocation，精确 `try_lock_316115/after_lock_316115` 存在，F/G 未释放。
- [ ] (2026-07-13 07:25+08:00) 19 个 E unknown 已取证分解为 15 个 Chimera 3600 秒超时、3 个已完整出图但被 `monitor changes` 警告误判、1 个 2zhc model/map frame 不相交。最小 atom_site-only CIF、精确日志豁免、filtered 状态保护、21600 秒/2 并发独立恢复脚本已实现；其中 2 并发是针对最大 13.5 GB map 的内存与临时 I/O 安全约束，正式无过滤复核仍保持 E24。本地全套 175 tests、compileall、bash -n 与 diff check 通过；剩余工作是 18-ID repair 和正式无过滤 E 复核。2zhc 决定已在下一条获得，仍禁止猜平移。
- [x] (2026-07-13 07:30+08:00) 无删除安全同步和远端 175 tests 通过后，独立 smoke run `adaligand_ag_20260711T154658_eeng_smoke_v1` 使 8ro0/9qqp 2/2 success；release gate、实验/模拟图网格配对、严格 HETATM 删除和 E3 后验全部通过。8ro0 仅保留被精确豁免的 monitor warning，其他 fatal 检查未放宽。已原子发布 316115 run_cmd（SHA-256 `d4c0ff53…a1c1`）并在全部校验后精确删除 `try_lock_316115`；18-ID repair run `adaligand_ag_20260711T154658_eeng_v1` 正在原 allocation 以 E2/21600 秒运行，`after_lock_316115` 与 F/G 依赖仍保留。
- [x] (2026-07-13 10:02+08:00) 用户显式接受将合法但完全不相交的 model/map 归类为 `known_failed:model_map_frame_mismatch`，要求 E/F 统一确定性包围盒检查并记入全套日志。本地已实现单一纯 QC + 单一失败策略包装器，E/F 均在外部工具和 artifact reuse 前调用；禁止 PDB allowlist、猜平移/fitmap，非法输入和后置密度/工具失败仍为 unknown。专项 22 tests 和本地全套 178 tests、compileall、diff check 通过；待独立审查、Git checkpoint、安全同步、远端 smoke/全套和正式 E 复核。
- [ ] 持续监控、自动诊断/修复/重提，只在科学契约变化或外部不可恢复阻塞时请求用户。
- [ ] 完成全量验收、计划漂移收口、mapping/契约 README/项目记忆更新和最终报告。

## Surprises & Discoveries

- Observation: 当前权威计划、mapping 和代码契约只定义 Stage A–G；对话中的 “J” 是用户确认的口误。
  Evidence: `文档/规划文档/数据处理_v2.md` 只列 A–G，仓库中没有 H/I/J 脚本或产物契约。

- Observation: 服务器旧 C 产物虽然三个旧核心文件 22,386/22,386 齐套，但缺少全部新 C 字段；现有 skip-if-exists 会把旧 schema 误判为完成。
  Evidence: 五个服务器样本抽查均无 `bond_index`、`bond_type`、`feat` 和 `centroid_atom_*`；服务器代码也没有新字段标记。

- Observation: EMDB 下载对同一 CPU 节点的并发请求敏感，超过四个并发任务成功率显著降低。
  Evidence: 用户根据上一轮正式运行补充的运行约束；本轮 B 重试固定为单节点单 task 单进程。

- Observation: 当前 source 把 20 个旧 `resolve_failed` 的 5GP occurrence 变为合法项，因此 full rebuild 首次需要 `CCD:5GP` descriptor；旧正式 C 从未物化这份依赖。
  Evidence: `csrc_v2/stage_c_source_rebuild/audit.records.jsonl` 的 14 条记录均以同一缺失路径 fail-closed，migration manifest 为空，且 56 个 canonical C 文件与首轮冻结 audit 基线逐一哈希一致。

- Observation: 41 个 C 失败样本的旧 receptor 尚未升级到新派生 schema；它们在 source audit 中除 atom name 外的基础数组和 ligand-side 均一致。
  Evidence: `csrc_v3` 联合 gate 的 41 条 blocked records 具有完全相同的原因集合：`receptor_base_changed:atom_name` 与 `receptor_derived_delta:old_receptor_incomplete`。后者是“无比较基线”而非“比较后不一致”；clean spec 已要求只有旧 receptor 完整时才比较派生 delta。

- Observation: 远端用 shell 拼接冻结输入时曾把换行误写为字面字符；在任何 audit/staging/canonical 写入前即由 count/SHA 门禁发现并原子替换为正确文件。
  Evidence: 修正后的 14-PDB、3-CCD 清单分别满足固定行数和 SHA；错误版本未被任何成功 summary 消费。后续冻结小清单统一用 `printf '%s\n'`、行数与 SHA 三重校验。

- Observation: `与服务器交互/sbatch` 的 96 CPU 与 A100 参数可参考，但通用脚本绑定 Pocket Plus 环境、路径、CUDA 和 `rsync --delete`，不能 source 或照搬。
  Evidence: `与服务器交互/sbatch/_common.sh`、`_train_core.sh` 与各资源模板只读审计。

- Correction: 早期把一个人工构造的 Å 级非零 `header.origin` fixture 当作 Pocket Plus native-map 输入契约，因此曾错误地把 45 Å 偏差归咎于祖传 `load_map`。服务器真实 EMDB 图 `emd_0043.map.gz` 的 origin 为 0、nstart 为 `(-120,-120,-120)`、voxel 为 1.35 Å，Pocket 与 Ada 读取结果一致；该早期结论不再授权修改祖传函数。
  Evidence: 用户要求把 Pocket Plus 作为经训练/验证/测试的可信祖先；当前六函数源码和 AST 零差异。native 图继续使用祖传 `multiply_global_origin=True`，Ada/Chimera 自写的 Å-origin 图通过祖传已有参数 `False` 适配，并由非单位 voxel 往返测试覆盖。

- Observation: Pocket Fourier 原语不补偿输入/输出点数，因此重采样 grid 相对幅值比例为 `prod(even_input_shape)/prod(actual_output_shape)`。这是 Pocket grid 的祖传行为，不影响保持其训练输入；但 Ada 新增了“把 EMDB native recommended contour 用在 canonical map 上”的消费方式，必须把 threshold 乘同一比例。
  Evidence: 常数 up/down、odd padding 和随机场测试；随机阈值 mask 在 `raw_grid > native_contour×scale` 与幅值恢复图上 0 mismatch。正式 22,267 张几何闭合图的 scale min/median/p95/max 为 0.000354/0.943052/3.152994/56.895767，raw contour 原样消费会是系统性单位错误。

- Observation: 祖传 `rescale_real` 的 `np.all(out_sz != box.shape)` 只在“部分轴相等、部分轴变化”时产生 shape/voxel 不闭合；全量审计证明它确实是极少数边界，而不是主路径问题。
  Evidence: 22,269 个可读 header 中只有 EMD-11978 和 EMD-12465 两张 mixed；普通祖传路径覆盖其余 22,267。薄适配只对严格 mixed 关系使用同一函数体的 `np.any` 条件，vendored 六函数不改。

- Observation: 改动前 Windows 基线已有一个 JSONL 文件锁失败；`append_jsonl` 写完后文件位置移动到 EOF，但 `_locked_file` 未回到加锁位置就调用 `LK_UNLCK`。
  Evidence: `test_append_jsonl_roundtrip` 在 `code/io_utils.py:101` 报 `PermissionError: [Errno 13] Permission denied`；其余 21 个测试通过。

- Observation: 49 维中的 25 类残基 one-hot 与旧 `receptor_tokens.res_type` 的 29 类 id 是两套不同编码；不能直接复用 `RES_VOCAB`。
  Evidence: Pocket Plus 来源顺序是 20 AA + A/U/C/G + X，DNA 映射到 RNA 母体；AdaLigand `res_type` 保留 A/C/G/U/DA/DC/DG/DT/UNK 独立 id。

- Observation: MapQ 2.9.7 的 README/GUI 已推荐 sigma 0.4 以匹配 EMDB，但随包 `mapq_cmd.py` 仍硬编码默认 0.6，且会在 map 目录写固定 `_mapqScript.py`。
  Evidence: 上游 commit `c3bdf305677f5f9fc4b69aa404b834d9d3a75937` 的 `mapq/mapq.py` GUI 默认 0.4，而 `mapq/mapq_cmd.py` 默认 0.6；共享 map 目录并发会形成脚本名竞态。

- Observation: E3 若为全图每个体素构造世界坐标再建 KD-tree，在常见 512³ 网格上仅坐标就约 3 GiB，不能用于全量数据。
  Evidence: 当前计划 §7 E3 的伪代码枚举 `D*H*W`；改用逐配体原子的局部 voxel bbox/球形 stencil 可得到相同精确 mask，而内存与配体局部范围成正比。

- Historical observation: 旧 Ada 独立实现中，float32 乘法与 `ceil` 会导致 shape/声明 voxel 不一致；该实现已删除，不再通过吸附或其他自研规则修补。当前 shape、偶数约束与实际 voxel 完全服从 Pocket Plus 祖传 `normalize_voxel_size`。
  Evidence: wrapper 与祖传 `make_model_grid` 的逐值 parity；E1 保存 target=1.0 与实际 voxel，旧 schema/algorithm 被拒绝。

- Observation: MapQ CLI 的进程返回码不足以证明成功：参数错误可返回 0，内部 `os.system` 也不传播 Chimera 状态。
  Evidence: 固定包 `mapq_cmd.py` 的控制流与 fake rc=0/output-missing 测试；当前适配器额外要求预期 Q mmCIF、唯一 id 全集、完整身份、坐标和有限 Q 全部通过。

- Observation: classic Chimera 打开大图时可能自动调大当前 step 或只显示局部 region；`onGrid` 消费的是目标图的当前状态。
  Evidence: 官方 `molmap`/`volume` 语义；所有 E/F 命令在 `molmap` 前显式执行 `volume ... region all step 1 limitVoxelCount false`，保存时显式 `saveStep 1 saveRegion all`。

- Observation: target=1 Å canonical 图的体积远大于原始压缩图；若 E2/E3/F 各自再次哈希 `exp.npz`/`.map.gz`，会在 Lustre 上产生数 TB 的重复顺序读。
  Evidence: 128 图 header 抽样的 canonical voxel 中位数为 34,012,224、P99 为 152,273,304、最大样本为 622,835,864；按 exp/sim/union 初估全量约 9.93 TB。当前下游 provenance 组合 E1 已固化的原图 SHA、canonical 几何 identity 和小文件 manifest，并以原图 size+mtime 拒绝 stale E1。

- Observation: 第一次安全同步在实际上传前因远端 SSH/rsync 会话被关闭而失败，随后轻量 helper 也短暂得到 `Connection closed`。
  Evidence: `与服务器交互/sync_code.ps1` 在步骤 1 的远端 rsync/auth 检查退出；没有发生服务器写入。按项目纪律先停止密集探测并在本地完成回归，再重试轻量连接。

- Observation: classic Chimera 1.19 的 Midas `open` 解析器使用普通 `str.split()`，不会剥离 shell 风格双引号；`open "/path"` 会把引号当作文件名字符。
  Evidence: 首轮真实 smoke 三个 E2 均报 `MidasError: No such file or directory`，而输入文件存在；安装源 `Midas/midas_text.py::doOpen` 证实该行为。适配器现对无空白服务器路径传裸绝对路径并显式拒绝空白。

- Observation: `centroid_voxel` 声明为 float32 时，约 277 Å 以上的合法量化误差可略大于固定 `1e-5`；拿未量化 float64 期望值比较会误报。
  Evidence: 5net 的 13 个 occurrence 首次触发 `ligand_area_value:centroid`。验证器现先按契约量化期望值为 float32 再精确比较，新增大坐标及 1 ULP 负例。

- Observation: Chimera `measure correlation` 把结果写入 `replyobj.status/info`，`--silent` 时 stdout 只保留 marker，且人类日志只打印约四位有效数字。
  Evidence: 三个真实 F correlation 日志均有 BEGIN/END 而无数值；现从同一 Chimera 进程调用该命令底层 `FitMap.map_overlap_and_correlation` 并由适配器输出 17 位值。5mkf 已得到 contour/all CC 约 0.9286/0.7040。

- Observation: MapQ 2.9.7 `mapq_cmd.py` 的 CIF 分支用 `mmcif.ReadMol` 构造 molecule 后未加入 `chimera.openModels`，Q 内核访问 `mol.openState` 时必然报 `ValueError: unopen model`。
  Evidence: 三个真实样本均在 `qscores.py::CalcQ` 同一行失败；per-PDB compatibility CLI 只在 scratch 副本插入 `chimera.openModels.add([mol], noprefs=True)`，固定安装包保持不变，真实重试已越过该位置。

- Observation: MapQ np=1 在约 16.5k 原子上需 6.2–6.4 分钟；np=8 需约 59–61 秒。两模式的 5,215 个 occurrence 子集 Q 值 P99 差异低于 `5e-6`，只有三个口袋受体原子超过 `1e-5`，最大差异 `0.003821`；配体原子无该级别差异，口袋 id/NaN mask 完全一致。
  Evidence: 5mke/5mkf 的保留 np=1 Q-CIF 与 np=8 schema-v2 occurrence 数组逐 id 对照；np=8 正式 smoke schema v3 随后通过全部映射/聚合门禁。

- Observation: 已提交的 sbatch 正文和 `--export` 环境由 Slurm 固化；修改本地 `de_full.sbatch`、`f_full.sbatch` 或默认值不会改变 pending jobs `316115/316116` 的原 D32/E8/F8。当前集群 `cpu` 分区为 `DefaultTime=NONE, MaxTime=UNLIMITED`，`Cpu96` 无 MaxWall，因此省略 `--time` 才得到本项目期望的无限 walltime。
  Evidence: 原地变更前，`scontrol show job -o 316115,316116,316117` 分别显示 7d/7d/12h；提交时脚本显式 export D32/E8/F8；用户历史 cpu/Cpu96 作业未写 time 时由 `sacct` 记录为 `UNLIMITED`。这些旧并发和时限随后由受检 run_cmd 与 `scontrol update` 原地覆盖。

- Observation: 虽然 pending job 的 sbatch 正文与导出环境已经固化，但其正文在运行时 source 绝对路径的 AdaLigand core；因此可以保留 Job ID/FIFO 顺序，通过原子预置 `/home/penghongen/run_cmd_${SLURM_JOB_ID}.sh` 覆盖内置 hook，而无需取消后继链。
  Evidence: `316115/316116` 的 `Command` 保持原 sbatch 路径；同步后的 `_adaligand_job_core.sh` SHA-256 为 `2b811ce9c59ef8f9b5c2484b332b42b3f80204a1573c283412ebc10a5cb666b4`，两个预置文件均为 `0700` 普通非 symlink 文件并通过 `bash -n`。release 后 `316115` 优先级从 0 恢复，依赖仍为 `afterok:316114(unfulfilled)`。

- Observation: 既有 mmCIF 复用判据只在前 1 MiB 搜索 `_atom_site.`，会把合法大文件误判为不可复用。最初依据 Stage B `success` 记录只看到 400 份刷新，但这是低估：旧 `known_failed` 状态没有保存 `resources`，无法反映已下载 mmCIF。对 job 窗口做文件系统 mtime 扫描得到 2,156 份实际刷新 source。
  Evidence: 在既有 316114 allocation 内只读扫描 `/storage/penghongen/AdaLigand/Ori_Data/raw/rcsb_mmcif`，窗口 `2026-07-11T15:46:58+08:00 < st_mtime <= 2026-07-12T05:30:00+08:00` 命中 2,156 份，窗口后无新增。未来 B 的 `known_failed` 状态已改为保留逐资源 `resources`；本轮仍必须冻结 2,156-ID 清单与 SHA，并在任何写入前全量审计。

- Observation: 366 个 C failure 虽只占 22,386 PDB 的 1.635%，却涉及 43,175 个 occurrence 和 506 个 object_key，不能当作随机小尾部忽略。336 个价态异常由 1,505 个 occurrence/276 个对象触发，却连带阻断整 PDB；276 个对象约占当前 3,833 个 LigandObject 宇宙的 7.20%。
  Evidence: run-scoped C 状态、occurrences 与 object_key 只读交叉审计。失败由三项系统性问题组成：336 descriptor 价态、23 source mismatch、7 合法 triple；直接丢弃会偏向损失稀有/复杂化学对象并掩盖工程缺陷。

- Observation: 全集 source audit 暴露 379 个 atom_name_only，而原 C 状态只报 23 个；其余 COMPLETE 样本此前因 schema-aware skip 没有重新核对当前 raw。这证明 source-dirty 全集审计不能由 unknown-failure 子集替代。
  Evidence: repair run `adaligand_ag_20260711T154658_csrc_v1` 的 2,156 行 audit records；1,749 exact + 379 atom_name_only + 23 blocked + 5 failed 恰为全集。

- Observation: 14 个 ligand-side blocked 全部来自 `CCD:5GP` 的当前 source 命名修订。当前重建比旧 occurrences 新增 20 个此前 resolve_failed occurrence、删除 0；所有匹配 occurrence 的 coords/present 均逐位不变，但 atom serial 排序变化使 1,995 个既有 candidate_id 改变。
  Evidence: 对 6gaw/6gb2/6ydp/6ydw/7nqh/7nql/7nsh/7nsi/7nsj/7tql/8vvp/8vvq/8vvr/8vvs 做签名级只读 diff；旧失败共同为 5GP 磷酸氧 `O1P/O2P/O3P` 无法匹配，当前 source 可解析。D–G 尚未启动，因此没有下游产物需要迁移，但这仍超出已批准的 receptor-only 写入边界。

- Observation: 336 个 `AtomValenceException` 覆盖 276 个缺 descriptor 对象，来自完整 CCD/leaving-atom 契约下的表观高价态，而非 LigandObject 键型丢失。关闭 RDKit `SANITIZE_PROPERTIES` 的严格价态检查后，276 个对象均通过其余 sanitize；抽查 200 个既有合法 descriptor 的 `n_rings/n_rotatable` 无差异。
  Evidence: CCD:ICS/OEX/FCO 与 BRANCHED:FME-TRP 等真实对象的只读对照；新增五价 C、零电荷 C#O 和非成环芳香键 fail-fast 回归。

- Observation: 7 个 C unknown failure 是受体 CCD F86/L5R 的合法 `TRIPLE` 键，而当前受体枚举只编码 single/double/aromatic/backbone/disulfide/covale。
  Evidence: 6 个 F86 和 1 个 L5R 样本；忽略三键会使氰基 N 孤立或切断大子图。追加 `triple=6` 可保持既有 0–5 不变，但属于 artifact enum 扩展，需用户显式确认后再修改计划规格和代码。

- Observation: 5net 的 candidate 7/14 到最近 `group_PDB=ATOM` 原子的距离为 6.0018/6.6398 Å，因此严格 6 Å 包络为空；把它升级成 PDB known failure会无意丢弃同 PDB 其余 13 个有效 occurrence。
  Evidence: 真实 KD-tree 几何复核；schema v3 现保存 empty typed arrays、null 聚合和 occurrence status，最终 F 三 PDB 全部 success。

- Observation: Stage E 首轮 15 个 `timeout` 不是统一的大图边界：既含 13.5 GB 的 1500³ canonical 图，也含约 126–304 MB 的 316³–424³ 图。旧标准化模型只替换 `_atom_site` 却复制整个 source document，留下引用已删除原子的 anisotrop/struct_conn；7y7a 因此打印约 227 万条 warning。
  Evidence: 15 个 timeout 均无 `sim.npz/ligand_area.npz`，但 E1 已完成；scratch normalized CIF 为 14.1–447.6 MB。恢复改为只含受检 `_atom_site` 的最小独立 document，并用原子 id/坐标/ATOM-HETATM 选择回归证明科学输入不变。

- Observation: 8ro0/8ro1/8ro2 的 Chimera 返回码为 0 且均生成与 canonical MRC 同尺寸的 `sim.mrc`，但日志在金属配位连接 warning 后打印 `Error processing trigger "monitor changes":` / `KeyError: '?'`，被通用 `^Error` 正则误判。
  Evidence: 三份 stdout 均为空，stderr 的固定两行分别位于 131–132、149–150、53–54；sim 字节数分别为 788,550,496、96,737,664、562,433,024。修复只豁免精确两行，仍执行完整 MRC 与几何 QC。

- Observation: 2zhc/EMD-1470 的实验图并非重采样错误，而是沉积 map/model 世界坐标 frame 不相交。native header 为 shape 40×40×42、nstart/origin=0、cell 160.44×160.44×168.462 Å；canonical upper XYZ 约 159.44/159.44/167.46 Å，而 receptor bbox 的 Z 为 329.12–393.99 Å。mmCIF 的 ORIGX、assembly operation 和 atom_sites transform 都是 identity。
  Evidence: canonical 实验图非零，Chimera `onGrid` 模拟图同 shape/origin 但全零；自动平移只能靠猜测。用户于 2026-07-13 选择稳定 frame-mismatch known failure，明确不使用猜测平移或 fitmap。

## Decision Log

- Decision: MRC 加载/重采样以 Pocket Plus 祖传实现为当前可信参考，不再由 AdaLigand 重新设计一套“更正确”的替代实现。相关函数先以独立 vendored 模块逐函数原样复制，AdaLigand 仅保留 `Path`、`MapGrid`、gzip/落盘 schema、dtype 与调用接口所必需的薄适配。
  Rationale: 用户无法在当前阶段重新核验一套大幅改写的数值实现，而 Pocket Plus 已经过训练、验证和测试的多重工作流验证；可审计的近零 diff 比未经项目实证的新算法更重要。此前独立审计发现的潜在边界问题只作为回归观察项，不授权偏离祖传主路径。
  Date/Author: 2026-07-12 / User + Codex

- Decision: 每一项与 Pocket Plus 源函数不同的代码必须逐条登记：源文件/SHA、函数名、原样函数哈希、适配位置、必要性、行为影响和对应测试。优先通过“原样 vendored 模块 + 薄 wrapper”隔离差异；若 diff 无法保持接近零，则直接保留原函数，不在内部重写。
  Rationale: 让人类能直接用 diff 复核祖传代码是否被改变，并防止后续 Agent 以清理/重构名义悄然改变数值语义。
  Date/Author: 2026-07-12 / User + Codex

- Decision: 本次祖传接入的完整差异集合冻结为：(1) vendored 模块只选六函数、缩减无关 imports、增加来源 Docstring；(2) `load_map` 做 `Path→str`、显式暴露原有 `multiply_global_origin`、实体化 closed-handle grid、float32/MapGrid/基础几何验收；(3) `make_canonical_grid` 校验正 target、调用祖传 `make_model_grid`、转 MapGrid/float32并核对物理闭合；(4) 仅对正式审计命中的两张 mixed-axis 图复用祖传补偶输出，以同一 `rescale_real` 函数体把条件 `np.all` 窄改为 `np.any`，仍调用祖传 `rescale_fourier`，模式显式落盘；(5) Ada 自有 writer 写标准轴、`nstart=0`、Å 级 header.origin；(6) native EMDB 调用 True，Ada/Chimera generated 调用 False；(7) E1/E2/E3 schema v2、target+actual voxel、shape/mode 与 lineage/origin-mode provenance；(8) Pocket grid 不改，另存 native/scale/canonical contour，F 只消费 canonical 值且 provenance 与当前 E1 逐项绑定；(9) QC 要求 exp/sim actual voxel、shape、origin 严格相同；(10) `.gitattributes` 只为 vendored Python 固定 LF。除此之外没有祖传数值改动。
  Rationale: 这些差异分别服务于依赖隔离、Ada 接口、关闭 handle 后的所有权、两张已证明存在的祖传边界、Chimera 标准 MRC 互操作、旧错误 artifact 失效、canonical contour 单位映射和跨平台哈希复核；每项均有机器测试。真实 Chimera smoke 已证明 generated=False、非零 Å origin、非精确 1 Å voxel、标准轴和 `nstart=0` 全部闭合。
  Date/Author: 2026-07-12 / Codex（用户信任边界内的必要兼容适配）

- Decision: “重跑 A–C”表示把冻结的 22,386-PDB snapshot 升级到当前契约，而不是删除已有产物后全量重算。
  Rationale: A 样本宇宙预计稳定；B 已有 mmCIF/meta/map 与 C 旧字段可安全复用，增量迁移能避免数日无效下载和重算。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: A 只做清单 guard 和 QC；B 只补当前缺图；C 使用 schema-aware 组件级完成判据，不使用单一 `--overwrite` 覆盖全部内容。
  Rationale: 文件存在不代表新 schema 完成；配体去重对象在并行覆盖时也存在竞态和浪费。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: A–C 必须通过硬 release gate，D–G 的 Slurm 依赖才会释放。
  Rationale: 既实现无人值守自动推进，又阻止旧 C schema 被下游误消费。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: Stage E 的 canonical grid 由 Pocket Plus 祖传 `make_model_grid(target=1.0)` 生成偶数 shape 并返回实际 voxel；随后让 Chimera `molmap ... onGrid` 直接生成同网格模拟图。下游读取 artifact 的实际 voxel，`volume step 1` 不承担重采样，也不把 header 强制声明为精确 1.0 Å。
  Rationale: 保证模拟图与实验图的 shape、voxel、origin 和轴语义严格一致，避免旧代码曾产生二维或错误空间范围的产物。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: receptor-only 模拟图专用结构严格删除全部 `HETATM`；这一规则不改变 C 的受体 token、F 的全模型 CC 或 Q-score 输入。
  Rationale: 该模拟图有意匹配 cryoatom2 只能表达受体主体的能力；全模型质量评估仍必须使用原始沉积模型。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: F 保存 `cc_contour`、`cc_contour_about_mean`、`cc_all`、`cc_all_about_mean` 四个原始量，并在代码中文 Docstring、注释和契约 README 中解释公式、mask 与空值语义。
  Rationale: 当前只保存原始可审计量，不提前选择单一指标；Stage G 后续可按分布和明确配置消费。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: Q-score 使用原始 native EMDB map 与原始完整沉积模型，经 classic Chimera + MapQ 计算；保存与 `LigandObject` 行序严格对齐的逐原子 `qscore_{cid}`，未出现原子填 `NaN`，另存 mean/median/min/n_valid/n_present 聚合。
  Rationale: 不自研数值算法，也不按残基遍历顺序猜原子映射；逐原子原始量便于复查聚合。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: occurrence 口袋定义为到任一 present 配体重原子 ≤ 6.0 Å 的首 model/规范 altloc/`group_PDB=ATOM` 受体重原子并集；复用全模型 MapQ 原子值，保存 pocket atom_site.id/Q 子集和 mean/median/min/count/radius/status，不预过滤。
  Rationale: 原子包络并集比配体中心球更适配非球形配体，实现成本相同；固定半径、原始 id 与逐原子值让后续阈值可审计、可零成本重算。真实 5net 中 candidate 7/14 的最近 ATOM 距离为 6.0018/6.6398 Å，故零口袋是 occurrence 级观测结果：保存 typed empty、count=0、聚合 null 和 `no_receptor_atoms_within_radius`，不连带淘汰同 PDB 的其他 occurrence。
  Date/Author: 2026-07-11 / 用户授权范围内由 Codex 固化 6.0 Å 口径

- Decision: MapQ 固定上游 commit/安装包校验和，显式传 `sigma=0.4,np=8`，并在 per-PDB scratch 中运行；不依赖 `mapq_cmd.py` 的隐式默认或共享 `_mapqScript.py`。
  Rationale: 0.4 是当前上游与 EMDB 对齐的推荐值；np=1 的真实基准约 16.5k 原子需 6.2–6.4 分钟，证明必须使用 MapQ 内层并行。np=8 的真实 smoke 已与 np=1 基线逐 id 对照通过；正式 F 采用 12 个 PDB 外层并发，最多约 96 个 MapQ worker，并已取消原 7 天截断时限。
  Date/Author: 2026-07-10 / Codex（依据 MapQ 当前上游）

- Decision: MapQ CIF 运行使用 basename 仍为 `mapq_cmd.py` 的 per-PDB 兼容副本，仅补 `ReadMol` 后的 `openModels.add`；原始 CLI hash、固定 zip hash和补丁版本都写入 provenance。
  Rationale: 保持 MapQ 数值内核、sigma、np 和输出格式不变，同时绕开固定上游包在 classic Chimera 1.19 上可复现的 `unopen model` 缺陷；不污染用户目录安装。
  Date/Author: 2026-07-11 / Codex（真实 smoke 证据）

- Decision: 四种 CC 通过 Chimera `measure correlation` 的同一底层官方 `FitMap.map_overlap_and_correlation` API 获取，并由适配器打印高精度 marker。
  Rationale: `--silent` 会吞掉 GUI reply 文本，直接调用同一实现可保留精度、确定输出格式和严格区段解析，不改变 contour/nonzero mask 语义。
  Date/Author: 2026-07-11 / Codex（真实 smoke 证据）

- Decision: 缺少可用 map resolution 的样本在 E2/F 的需要分辨率路径中记为 `known_failed`，不猜保守默认。
  Rationale: molmap resolution 会直接改变模拟密度，猜测值会污染 CC、sim 和下游训练输入。
  Date/Author: 2026-07-10 / Codex（落实用户“机器检查优先、禁止静默兜底”的边界）

- Decision: E1 重采样除几何正确外还必须保持常数/DC 幅值；E3 使用局部 voxel stencil，禁止构造全图坐标 KD-tree。
  Rationale: recommended contour 只有在幅值语义保留时才能迁移到 canonical map；局部 stencil 在数学上等价且避免多 GiB 临时内存。
  Date/Author: 2026-07-10 / Codex

- Decision: 服务器安装官方 Chimera 1.19 headless/OSMesa 与 MapQ 到用户目录，不写系统目录；用户确认项目符合非商业许可并授权安装。
  Rationale: `molmap`、CC 和 MapQ 需要 classic Chimera/插件，旧服务器路径已失效。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: Stage B map 重试固定 `--nodes=1 --ntasks=1 --cpus-per-task=1 --n_jobs=1`，同一节点只发一个下载请求。
  Rationale: 遵守用户提供的 EMDB 服务并发经验；缺图只有约 176 个，顺序重试成本可接受。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: 正式计算优先使用 CPU96；只有 CPU 分区不足时才允许在最多两张 A100 节点上运行 CPU-only 任务，每卡最多 16 CPU。
  Rationale: A–G 当前负载以 CPU/I/O 为主，不为无 GPU 收益的任务优先占用 A100。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: 仅对 Codex 本轮提交且能精确归属的作业使用 `kill_lock`；对应任务、产物和 QC 完成后可删除 `after_lock` 释放资源。
  Rationale: 用户明确扩充权限，同时保持项目级资源边界和可追溯性。
  Date/Author: 2026-07-10 / 用户与 Codex

- Decision: 多日全量运行由服务器端 `afterok`、作业 heartbeat 和精确 locks 作为实时控制面；Codex heartbeat 每 2 小时做一次低噪声只读巡检，正常不展开重复证据，阶段切换/异常/最终验收再按需启用多智能体。
  Rationale: 30 分钟轮询会重复消耗上下文，而长驻子智能体的汇报最终仍会回流主任务；阶段感知的稀疏巡检既保留自动恢复能力，也降低上下文与推理开销。
  Date/Author: 2026-07-12 / 用户与 Codex

- Decision: 在用户确认 DE/F/G 新并发和 walltime 前，对精确入口 job `316115` 使用可逆 user hold；不暂停 ABC、不取消后继、不触碰任何 lock。
  Rationale: pending job 使用提交时快照，ABC 可能在讨论期间完成；hold 能严格保证未经确认的 D32/E8/F8 不会意外启动，同时保留整条依赖关系供审计。
  Date/Author: 2026-07-12 / Codex

- Decision: 用户确认后保留 `316115→316116→316117` 的 Job ID、提交时间和依赖排位，不取消重提；用预置 run_cmd 把 DE 固定为 D64/E24、F 固定为 12 个 PDB 外层并发（每个 MapQ 仍为 `np=8`），并用 `scontrol update` 把三者时限原地改为 `UNLIMITED`。
  Rationale: 96 核作业重新提交很难再次获得整节点，而 pending job 可通过外部 core 的受检预置命令安全覆盖固化的旧 D32/E8/F8；D64+E24 保留 8 核余量，F12×MapQ np=8 对齐 96 核授权。每次 retry 前重验 run_cmd，`kill_lock/try_lock` 只作为失败后的精确回退。
  Date/Author: 2026-07-12 / 用户与 Codex

- Decision: descriptor 临时 RDKit Mol 使用 non-strict property cache，并执行 `SANITIZE_ALL` 去除 `SANITIZE_PROPERTIES` 后的全部 sanitize；任何剩余 failed operation 继续显式报错。
  Rationale: LigandObject 必须保留完整 CCD 模板和未出现 leaving atom，严格价态不适用于该临时图；保留其他 sanitize 能修复系统性兼容问题而不把真实芳香性/图错误静默降级。
  Date/Author: 2026-07-12 / Codex

- Decision: Stage B 复用既有 mmCIF 时只检查非空、`data_` 文件头和前 1 MiB 的 `_entry.id`；不再把 `_atom_site.` 的固定窗口位置当成有效性条件。
  Rationale: 完整 mmCIF 由 Stage C 解析，跳过路径必须低 I/O 且不能因 category 排布误刷已有 source snapshot。
  Date/Author: 2026-07-12 / Codex

- Decision: 受体化学键枚举在既有 `single=0,double=1,aromatic=2,backbone=3,disulfide=4,covale=5` 后追加 `triple=6`；0–5 永不改写，其他未声明键型仍 fail-fast。
  Rationale: 7 个失败来自 CCD F86/L5R 的合法三键；追加新值恢复真实化学而不破坏既有数据消费者。
  Date/Author: 2026-07-12 / 用户与 Codex

- Decision: 接受本轮 2,156 份当前 RCSB mmCIF 作为 raw source，但不等于允许盲目覆盖旧 C。冻结 dirty IDs/数量/SHA 后，全集合先分 `exact/atom_name_only/blocked`；零 blocked 才 apply，且仅修改受体 `atom_name/bond_index/bond_type/feat`。
  Rationale: 用户确认样本宇宙复用与当前 source；严格逐位不变量、五个直接输入及 LigandObject/CCD 依赖闭包哈希把“接受 source”和“允许数据迁移”分离。任何 ligand-side 或其他受体基础漂移仍阻塞。
  Date/Author: 2026-07-12 / 用户与 Codex

- Decision: 对冻结的 14-PDB `CCD:5GP` 集合执行一次 run-scoped 完整 Stage C 重建，接受 20 条新增 occurrence、0 条删除和 1,995 条既有 occurrence 的 `candidate_id` 重排；通用 source repair 仍只接受 `exact/atom_name_only`。
  Rationale: 下游训练与 D–G 尚未启动，当前是修正 snapshot 派生主键的最低风险窗口。冻结 ID/SHA、精确聚合计数、匹配 occurrence 的 coords/present 逐位不变量和可恢复四件套事务，把本次特例限制在一轮受检迁移内；before/after manifest 不是 Stage C 主产物、训练字段、跨 source 永久 accession 或未来自动 rebuild 许可。
  Date/Author: 2026-07-12 / 用户与 Codex

- Decision: 保留现有 96 核 Job 316114 作为唯一正式 Stage C 写入者；用户新增授权的 48 CPU 只可用独立 Job ID/run id/锁执行测试、只读审计或最终 audit 冻结前的依赖补足。
  Rationale: 并行补足能压缩 316114 的硬截止关键路径，但第二个正式 C 写入者会破坏 CAS、状态报告和事务恢复边界。额外资源不改变算法、schema 或科学门禁。
  Date/Author: 2026-07-12 / 用户与 Codex

- Decision: 366 个 Stage C unknown failure 不降级为可忽略样本；343 个 descriptor/triple 系统性问题必须恢复，23 个 source mismatch 只有严格审计通过后才迁移。真正不可恢复的个例只能在有证据时转为明确 `known_failed`。
  Rationale: 1.635% PDB 关联 43,175 occurrences、506 object_keys，且对稀有化学对象有系统性偏差；release gate 的目的正是阻止这种静默丢样本。
  Date/Author: 2026-07-12 / 用户与 Codex

- Decision: 316114 的恢复跳过 B，使用独立 repair run 完成 snapshot→audit→apply，随后以原正式 run id 无过滤重跑 22,386-PDB C 与 ABC gate。filtered C 在代码层拒绝覆盖已有正式 A guard/C status。
  Rationale: B 状态已经覆盖全集，重跑会再次改变已冻结 raw；filtered 原 run 会把 22,386 行正式状态覆盖成子集。整轮 audit→apply 是中断后的幂等恢复单位。
  Date/Author: 2026-07-12 / Codex（用户已授权原地端到端恢复）

- Decision: E2 与 F 共用首 model、Stage C 同款 altloc、重原子的标准化 mmCIF；E2 再严格筛 `group_PDB==ATOM`，F 保留 `ATOM+HETATM`，两者均保留原始 `atom_site.id`。
  Rationale: 避免 Chimera/MapQ 把多个 model/altloc 一起计算，并使 C occurrence、CC 与 Q-score 使用同一原子身份源。
  Date/Author: 2026-07-11 / Codex

- Decision: E1 的 contour null 编码固定为 `contour=NaN`、`contour_present=False` 和显式 status/path/source；只搜索主图 `map.contour_list.contour` 的唯一 primary。
  Rationale: NPZ scalar 需要无 pickle 的缺值表达；附加图也可能含 contour 字段，递归搜索会误配。
  Date/Author: 2026-07-11 / Codex

- Decision: E3 的 `mask_{cid}` 固定为唯一、字典序排序的 `(K,3) int32` ZYX；`centroid_voxel_{cid}` 明确为世界 XYZ Å。C/N/O/P/S 用计划锁定半径，其他元素调用 RDKit 逐元素半径，不用统一默认。
  Rationale: 稀疏 schema 和坐标语义必须让 BOX 可直接消费；逐元素库值覆盖卤素/金属而不手造单一兜底常数。
  Date/Author: 2026-07-11 / Codex

- Decision: G 在阈值未授权时只运行 `analyze` 并写 run-scoped 分布/pending candidates；只有带 hash 的显式 JSON 配置才允许写正式 `keep_list.jsonl`。
  Rationale: 同时满足无人值守跑完可计算部分和“先看正式分布再定阈值”，避免把 artifact-valid 清单冒充科学过滤结果。
  Date/Author: 2026-07-11 / Codex

- Decision: Stage E/F 标准模型只保留 `_entry.id`（若存在）与逐字段原样筛选的 `_atom_site`；Stage E 的 Chimera fatal-log 扫描只豁免精确的 `monitor changes`/`KeyError '?'` 两行组合。filtered E repair 必须使用新 run id，补齐 artifact 后再用正式 run id 无过滤、无 overwrite 全量刷新状态。
  Rationale: 悬挂 anisotrop/struct_conn 引用造成数百万 warning 与系统性超时，而外部工具的科学输入是受检原子身份和 Cartesian 坐标。最小文档不改变这些值；日志窄豁免后仍由输出存在、MRC/几何 QC 与正式 release gate 提供独立硬门。
  Date/Author: 2026-07-13 / Codex（工程恢复，不改变科学数值）

- Decision: 合法 E1 canonical map 与合法 Stage C polymer receptor token 坐标（`receptor_tokens.coords`）的 XYZ 包围盒完全分离时，E/F 统一记 `known_failed:model_map_frame_mismatch`。该 token 是两阶段共用 frame anchor，不等同于 E2 严格 ATOM-only 模型或 F 完整 ATOM+HETATM 模型。两阶段共用单一函数和 `1e-5 Å` 容差，并在任何 artifact reuse/Chimera/MapQ 前短路；禁止 PDB allowlist、猜测平移、fitmap 或改写坐标。
  Rationale: 权威 source 可能没有可证实的共同 frame；生成全零 sim 或猜变换都会伪造数据。该 known failure 只接受完全分离的合法包围盒；空/NaN/错 schema、后置 all-zero/几何不一致和外部工具错误仍为 unknown。
  Date/Author: 2026-07-13 / User + Codex

## Outcomes & Retrospective

尚未完成。Stage C v4、ABC gate、MRC 放行与 Stage D 全量状态已完成；Stage E 已处理 22,386/22,386 并写出完整状态，但 DE gate 因首轮 19 个 unknown 正确保留原 allocation。其中 18 个工程失败正在独立恢复；2zhc 的科学决定已获得，本地 E/F 统一 `model_map_frame_mismatch` 实现和 178 项测试已通过，仍待安全同步、远端验收与正式无过滤 E/D-E gate。316116/316117 继续依赖等待，随后自动进入 F12、G analyze 和最终全量 QC。

## Context and Orientation

代码根 `Data_Preprocessing/Ori_Data/` 由 `code/` 业务模块、`scripts/` CLI、`tests/` 测试和 `sbatch/` 调度脚本组成。A–G 均已有正式 CLI；完整调度入口为 `abc_full.sbatch`、`de_full.sbatch`、`f_full.sbatch` 与只做 analyze 的 `g_analyze.sbatch`。

正式服务器代码根是 `/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data`，正式数据根是 `/storage/penghongen/AdaLigand/Ori_Data`。服务器入口为 `penghongen@10.102.33.220:10022`。普通 SSH helper 只用于轻量探测和提交；重计算必须通过 Slurm/lock 机制。

“schema-aware”表示完成判据检查文件内部必需 key、dtype、shape、行序和跨文件主键，而不是只检查路径存在。“release gate”是一个轻量验收作业：任何未知失败、契约不一致或静默缺失都会让它非零退出；已分类的样本级失败可以继续，但必须进入失败清单并从 `keep_list` 排除。“run-scoped report”表示每次运行有独立 run id，旧失败记录不会被误当成当前失败。

当前服务器基线是 A 清单 22,386 个唯一 PDB；mmCIF 与 meta 各 22,386 份；22,274 个唯一 EMDB 中已有 22,098 张 map，缺 176 张；旧 C 的三个核心文件各 22,386 份；去重 LigandObject 3,833 份。

## Plan of Work

### Milestone 1: 固化契约和可恢复基础设施

先补共享失败、契约和 QC 模块，使每个 stage 入口只编排任务，不各自复制错误处理。失败模块定义有限枚举、run id、输入主键、错误摘要和日志路径；契约模块验证 A–G 文件内部结构；QC 模块实现数值、三维网格、坐标覆盖和跨产物一致性检查。所有写入继续使用临时文件加原子 rename。

同时建立独立 AdaLigand Slurm 包装器。只借鉴旧 `_train_core.sh` 的绝对路径 lock、独立进程组、kill watcher 和退出清理，不 source Pocket Plus `_common.sh`。成功且验收通过的作业自动退出，避免 `afterok` 永久等待；失败作业进入有限重试/诊断流程，不无限占住节点。

### Milestone 2: 增量升级 A–C

A guard 验证 `pair_list.jsonl` 行数、唯一性和 snapshot 指纹，不访问 RCSB 覆盖原清单。B 枚举实际缺文件而非累加历史失败报告，顺序补图并写本轮失败记录。

C 把旧文件拆成可独立补算的组件。`ligand_coords.npz` 在保留旧数组行序和数值的前提下增加 `centroid_atom_{cid}`。受体基础数组先与 mmCIF 重建结果逐行核对，再增加化学 `bond_index/bond_type` 和按完整受体计算的 `feat(N,49)`。配体描述子按 `object_key` 全局去重生成，并通过锁或原子竞争确保并发安全。完成判据逐组件检查；第二次运行必须只报告 skip。

若 raw mmCIF 在旧 C 之后刷新，先按显式 mtime 窗口冻结 source-dirty 清单、数量和 SHA。独立 repair run 对全集合 cache-only dry-build，冻结五个直接输入与 LigandObject/CCD 依赖闭包；只有全部为 exact/atom_name_only 才能 apply。atom_name_only 只原子迁移 receptor 的 atom_name 与派生 bond/feat；任何 occurrence、配体坐标或其他受体基础漂移都阻塞。正式 C 状态最终由无过滤全量运行刷新。

### Milestone 3: 实现 D–G 和外部工具适配层

D 读取 C 受体/配体坐标，生成 `binding_atom`、`instance_id`、`nearest_dist`。E 的实验图加载和 target=1 Å/actual-voxel 重采样由零差异 `code/mrc_pocket_legacy.py` 与 `code/mrc.py` 薄适配共同提供；receptor-only CIF 只在 E2 临时目录生成并删除全部 `HETATM`；Chimera 调用集中在 `code/chimera.py`，命令、版本、输入 hash、退出码和日志都进入 provenance。ligand-area 使用逐元素 vdW 半径。

F 用 Chimera 在 canonical grid 上生成全模型模拟密度并取得四种 CC；contour 缺失时 contour 两项为 `null`，不得猜阈值。MapQ 读取 native map 和完整模型，输出逐原子 Q；适配层用 mmCIF 原子身份与 C component/atom_name 做严格 join，再投影到 LigandObject 行序，并按 6 Å 原子包络聚合 occurrence 受体口袋 Q。G 汇总完整度、resolution、CC、配体/口袋 Q 和所有阶段状态，先输出质量分布；收到显式四类阈值后再输出排除原因和 `keep_list.jsonl`。

### Milestone 4: 自动 smoke gate

本地先用合成 MRC、最小 mmCIF 和 fake Chimera/MapQ 输出覆盖纯 Python 逻辑。服务器 smoke 选少量包含单 CCD、BRANCHED、缺原子、不同 map axis/origin 的真实样本，实际调用 Chimera/MapQ。加入负对照：错配模型与 map 的 CC 应明显恶化；故意交换原子身份必须被 mapping QC 拒绝；二维/单切片或错 shape 的模拟图必须失败。smoke 全部通过后，Slurm 依赖自动释放全量任务。

### Milestone 5: 全量 DAG、监控与收口

初始正式 DAG 为 A guard，B retry 与 C upgrade 并行，各自 QC 后进入 A–C release gate；通过后进入同一作业内并发的 D+E，再依次运行 F 和 G analyze。当前 316114 的 gate-repair 路径不再重跑 B：snapshot→独立 source audit→apply→无过滤全量 C→ABC gate。长任务使用 Slurm 持久运行，heartbeat 定期只读检查队列、日志增长、失败类型和产物计数。例行代码/批脚本/QC 修复可安全同步，并优先通过精确 run_cmd/lock 原地恢复；科学契约变化、删除数据或 clean sync 不在自主修复权限内。

## Concrete Steps

所有本地命令从仓库根执行：

    cd C:\Users\15919\Desktop\AdaLigand
    .\Data_Preprocessing\Ori_Data\.venv\Scripts\python.exe -m pytest Data_Preprocessing\Ori_Data\tests -q

先检查环境依赖，不在系统 Python 中临时安装：

    .\Data_Preprocessing\Ori_Data\.venv\Scripts\python.exe -c "import gemmi, numpy, scipy, rdkit; print('core imports ok')"

实现期间每次停止前运行语法和测试：

    .\Data_Preprocessing\Ori_Data\.venv\Scripts\python.exe -m compileall -q Data_Preprocessing\Ori_Data\code Data_Preprocessing\Ori_Data\scripts
    .\Data_Preprocessing\Ori_Data\.venv\Scripts\python.exe -m pytest Data_Preprocessing\Ori_Data\tests -q

服务器只读核实分区/QoS/节点拓扑和当前环境后，使用项目安全同步入口上传项目代码；禁止运行 clean sync。Chimera 与 MapQ 安装在用户目录并记录版本、校验和与安装命令。具体安装路径和 sbatch 命令在完成实际探测后写回本节，不能依赖聊天记忆。

正式提交前先运行自动 smoke submitter。完整 DAG 的 job id、依赖、资源参数、run id、提交时间和重提历史必须追加到本文件 `Artifacts and Notes`。

当前 316114 恢复在服务器上的固定步骤为：保留既有 2,156-ID 清单/SHA；先显式补足并 cache-only 复核缺失 CCD，再按冻结 object-key `CCD:5GP` 从既有 LigandObject 非覆盖补足 descriptor 并冻结源/实现/产物哈希；冻结 14-PDB ID/SHA 后执行专用 audit/prepare 与主键 manifest；把该 staging 作为 delegated evidence 纳入 2,156 联合 pre-apply audit，要求 blocked=0、failed=0；之后依次提交 14-PDB 可恢复四件套事务与通用 receptor-only apply，再做 post-apply 2,156 全 exact 审计。最后只用原正式 run id、不带任何 filter、无 `--overwrite` 的 `c_parse.py --n_jobs 90` 重跑 22,386 PDB，再执行 `abc_release_gate.py`。把命令写入 `/home/penghongen/run_cmd_316114.sh` 时先原子发布、`0700`、`bash -n` 和 SHA 验证，之后才删除 `/home/penghongen/try_lock_316114`；不得删除 after_lock、取消/重提 Job 或运行 B。

try-lock 重启必须执行 `Data_Preprocessing/Ori_Data/sbatch/resume_abc_316114_source_v2.sh` 的阶段感知规则；文件名表示恢复脚本实现版本，本次 evidence run 是 `csrc_v4`，失败的 `csrc_v2/v3` 保持只读。descriptor supplement CLI 每次调用并重新验证证据，不能只因 summary 存在而早退；成功的 14-PDB audit 与联合 pre-gate 只读复用、绝不覆盖；rebuild apply 依据 transaction receipt 幂等续跑；14 commit 后的 generic receptor repair 每次使用新的 `generic_attempt_N` run id 从当前 canonical 重新 audit/apply，旧 attempt 的 before records 不得复用；post-exact 使用独立 run id 和 `--require_all_exact`。因此 generic partial apply 会被下一份当前态 audit 吸收，而不会把整条流水线错误地从 pre-rebuild audit 重放。

## Validation and Acceptance

本地验收必须满足：所有测试通过；Pocket 六函数的源码片段和 AST 与冻结祖先零差异；MRC 六种合法 axis mapping、gzip、OWNDATA、native=True/generated=False 都与祖传函数逐值一致；`make_canonical_grid` 输出与祖传 `make_model_grid` 一致并保存实际 voxel；非单位 voxel+非零 origin 的标准 MRC 往返和合成 C→G smoke 通过；C 旧 fixture 升级后基础数组逐位不变；同一升级命令第二次运行零重算；并发描述子写入不产生破损文件。

A–C release gate 必须满足：A snapshot 指纹固定；每个 PDB 的 mmCIF/meta 成功或有明确已知失败；map 成功或有本轮不可得原因；所有成功 C 样本满足新 keys/shape/dtype；descriptor key 集等于成功 occurrence 引用的 distinct object key；没有未知/契约失败。

source-dirty 验收必须满足：mtime 清单恰为预期数量且 SHA 固定；ID 与 audit records 均从同一份已哈希字节解析，records 数/ID 集一致、自身 SHA 被 summary 冻结，summary 的实现哈希在 apply 前不变。通用记录只能是 exact/atom_name_only；本轮 14 条可在同一 pre-apply gate 中以 `delegated_full_rebuild_ready` 表示，但必须逐条绑定冻结的 rebuild record、ID/SHA、输入/依赖/staging/manifest 哈希，联合 2,156 条的 blocked/failed 均为 0 后才允许任何 canonical 写入。专用 manifest 必须精确证明新增 20、删除 0、reassigned 1,995，所有匹配 occurrence 的身份及 coords/present/centroid 逐位不变；14 个 PDB 的所有 candidate-indexed C 文件来自同一 source snapshot，before backup、二次全局 CAS、durable transaction receipt 与中断 rollback/recovery 全部通过。旧完整 receptor 的 exact 还要求 `bond_index/bond_type/feat` 与当前 source 重建逐位一致；atom_name_only apply 后六个其余受体基础数组、occurrences、ligand_coords 和额外 provenance key 不变，严格 CCD 身份/name/元素覆盖只作用于实际改名 residue，bond_type 只允许 0–6。post-apply 2,156 audit 必须全部 exact；任何 blocked/failed 都继续阻断 316114 release。

E 验收必须满足：成功样本的 `exp.grid.shape == sim.grid.shape == (1,Z,Y,X)`；`sim.mrc` 为严格三维，读取后的 `sim.shape == exp.shape[1:]`；E1 记录 target=1.0 与 Pocket 返回的实际 XYZ voxel，E2 与 E1 的实际 voxel/origin 逐轴一致；数组有限、非零、有方差，并在 X/Y/Z 多个切片上存在内容；受体坐标包围盒与网格世界范围相交。合法但完全分离的包围盒必须在 E/F 都精确产生 `known_failed:model_map_frame_mismatch`，且外部工具零调用；其他输入、数值和工具失败仍是 unknown。真实 Chimera smoke 还必须证明 generated MRC 的 `nstart=0`、header.origin 按 Å 保留，不能只用 unit-voxel/zero-origin fixture 放行。

F 验收必须满足：四个 CC 非空值均有限且在 `[-1,1]`；contour 缺失时只允许两个 contour 值为 null；错配负对照不优于正确配对；`qscore_{cid}.shape == (M,)` 且与 LigandObject 行序严格一致；`present=False` 位置为 NaN；`n_valid` 与成功 join 数一致。每个 occurrence 还必须有数值升序的 `pocket_atom_site_id_{cid} (K,) int64` 与同序 `pocket_qscore_{cid} (K,) float32`；`K>0` 时全部原子精确满足 6 Å 包络，`K=0` 时两个数组均为空、聚合 null、状态显式且 occurrence 仍保留；不存在按输出/残基遍历顺序或坐标最近邻猜测映射。

本轮 G analyze 验收必须满足：每个 A 样本在每个适用阶段恰好处于 success/skipped/known_failed 之一；任何静默缺失或 unknown failure 都阻塞；`quality_distribution.json` 与 `candidates.pending.jsonl` 保存完整候选、四 CC/配体 Q/口袋 Q/分辨率分布和输入 manifest hash，且不写 `keep_list`。后续用户显式授权 filter 时，`keep_list` 才只包含所有必需上游产物齐全且未被规则排除的 `(pdb_id,candidate_id)`，报告同时保存带 hash 的过滤配置与各原因计数。

## Idempotence and Recovery

所有 stage 都默认 skip-valid-artifact，而非 skip-existing-path。临时写入采用同目录临时文件，校验成功后原子 rename；`kill -9` 最多留下可识别临时文件，不能留下被完成判据接受的半文件。失败报告按 run id 隔离，当前状态以产物验证和本轮报告为准，不累加历史 append 文件。

Stage B 逐文件恢复，不覆盖已验证下载；但当前 316114 repair 明确跳过 B，以免改变冻结 source。普通 C 每个组件单独恢复；若受体重建与旧行序不一致，不覆盖旧文件，记录 contract failure。source apply 可能在中断前已有部分 receptor 完成原子替换，恢复时必须重新执行完整 audit→apply，使已修复项在新 audit 中变为 exact；不得单独重放旧 apply records。E/F 外部工具使用 per-PDB 临时目录，成功后只提升最终产物；日志和 provenance 保留。G 是纯派生阶段，可在不重算 A–F 的情况下用新配置重跑。

只允许删除本轮作业对应且已验收完成的 `after_lock`；`kill_lock` 只针对本轮可精确归属且卡死/错误的作业。不得 clean sync，不得删除正式数据根，不得修改服务器公共配置。

## Artifacts and Notes

初始服务器证据：

    A: pair_list=22,386 PDB
    B: mmCIF=22,386, meta=22,386, unique EMDB=22,274, maps=22,098, missing=176
    C old contract: parse dirs=22,386, ligand_objects=3,833
    C new contract: centroid_atom/bond_index/bond_type/feat/ligand_descriptors 均未实现

资源边界：原正式 DAG 保留单台 96 核节点；用户额外授权最多 48 CPU 并行执行独立测试、只读审计或依赖补足，但不能成为第二个正式 Stage C 写入者。A100 最多两张，每张配 16 CPU，仅作 CPU 分区不足时的 CPU-only 备用。Stage B 固定单节点单进程。

2026-07-11 服务器只读补充证据：AdaLigand 环境为 Python 3.10.20，已有 NumPy 2.2.6、SciPy 1.15.2、Gemmi 0.7.5、RDKit 2026.03.3、joblib 1.5.3、requests 2.34.2、pdbeccdutils 1.0.3 与 pytest 9.1.1，仅缺 `mrcfile`；CPU 节点 96 核且约 2 TB RAM，`cnode04` 探测时 idle；`/storage` 约 106 TB 可用但整体使用率 92%。

2026-07-11 工具与 smoke 证据：Chimera 根 `/home/penghongen/.local/opt/UCSF-Chimera64-1.19`，MapQ 根 `/home/penghongen/.local/opt/mapq-2.9.7-c3bdf305`；manifest 为 `/home/penghongen/.local/opt/adaligand_tools_manifest.json`。真实清单 `/storage/penghongen/AdaLigand/Ori_Data/reports/smoke/real_smoke_ids_v1.txt` 含 5net/5mke/5mkf；run id `adaligand_smoke_20260711T113733`，Slurm job `316073`。

2026-07-11 全量提交证据：run id `adaligand_ag_20260711T154658`；ABC job `316114`、DE job `316115`、F job `316116`、G analyze job `316117`，依赖依次为 afterok。提交清单位于 `/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_ag_20260711T154658/submission/jobs.env`。

2026-07-12 原地调度证据：`316115/316116/316117` 的 `SubmitTime` 均保持 `2026-07-11T15:46:58`，`TimeLimit` 均为 `UNLIMITED`；release 后 `316115` 为 pending、非 hold、`Dependency=afterok:316114(unfulfilled)`。DE/F 预置命令路径分别为 `/home/penghongen/run_cmd_316115.sh` 与 `/home/penghongen/run_cmd_316116.sh`，哈希见 Progress；阶段启动后 core 成功清理前这些文件必须保留。

2026-07-12 source repair 前调度证据：316114 仍在 cnode04 的精确 `try_lock_316114`/`after_lock_316114`，B/C 状态哈希未变；316115–316117 继续 dependency 等待。316114 自身仍是原提交的两天 TimeLimit，EndTime `2026-07-13T15:46:58`；尝试仅把该运行中 Job 原地改为 UNLIMITED 被 Slurm 返回 `Access/permission denied`，作业与锁没有变化。因此恢复需优先推进，但此事实不授权取消或重提。

2026-07-12 source audit 证据：冻结清单位于 `/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_ag_20260711T154658/source_dirty/mmcif_refreshed_ids.txt`，数量 2,156，SHA-256 `fc6f0068a1cd1529346e90e265c7d5844df38b69d3087bde19b0237d5b135349`。正式 repair run 为 `adaligand_ag_20260711T154658_csrc_v1`，audit records SHA-256 `8a1336d06de15f4a0bef27539a8fb24d1cda96fe5c941e21a9fd6ae492109e38`；分类 exact=1,749、atom_name_only=379、blocked=23、failed=5。audit step 读取/计算活跃并正常完成 2,156/2,156，因门禁非零退出；未进入 apply。

2026-07-12 MRC 祖传快照证据：源文件 `Pocket_Plus/processedPDB_EMDB_binder/utils/mrc_tools.py` SHA-256 `d8e543e4c6763a44cde3d350434c51506d794ecf1c2143db2ce304419bc06ca8`；vendored 文件 SHA-256 `acf74c256e6d88f9e40e972c0d86d35262aa9ac6ac790346adbd54e3109e8a45`；六函数源码与 AST 零差异；Git checkpoint `6de3fb8`。跨 Python portable AST 修复为 `f26b737`，Stage E 薄适配 checkpoint 为 `17b95d5`，真实几何 smoke 入口 checkpoint 为 `4d27af2`。本地与服务器 Python 3.10 全套均为 172 passed、compileall 通过。放行前 316115 的 run_cmd SHA 为 `a1ca224dc23030aa483a5b102e55ed5f8860266d09f21542c1612aa0619a3cb0`，当时 `pre_lock_316115` 存在且 release marker 不存在；最终放行见下述独立证据。

2026-07-12 MRC 全量/真实验收证据：header-only run `adaligand_mrc_contract_audit_20260712T192000_v2` 的 summary/risk SHA-256 为 `a9300d2db48c658301af36d116e751c705ffa5b7f8eae93b682bfc9683447fe8` / `81784ee19ab0a7fcee5814aed4e5e251a518018b28bcc8ec277f5446e83a6712`；22,269 张可读 header 中只有 EMD-11978/12465 为 mixed，另 5 张缺图均对应 B known failure。真实 smoke `adaligand_mrc_geometry_smoke_20260712T200227` 的 ID/summary/report SHA-256 为 `41c7a456e2c31b19c02636e19d1462adced837a83e81787694ca101e2744cd56` / `0e40d866c3a30a408921c48ce6831e110fe6c8f7929b7c22bcc1ce0370096957` / `451a6dced12cb81e1c816de185ec0baa2f05000935643928da29d02e09ca9de5`；7b14/7nll 的 canonical/sim shape、actual voxel、origin、标准轴和 `nstart=0` 全部通过，错误列表为空。

2026-07-12 MRC 放行证据：持久测试 run `adaligand_mrc_release_evidence_20260712T201306` 的 command/log/code-manifest/summary SHA-256 为 `fbe3b3c8…c6aa` / `f48d397a…f11a` / `9dc710fd…9f1f` / `1ef89ae0…3ffd`，Slurm step `316115.6 COMPLETED 0:0`，日志为 172 passed。独立只读审计复核祖传直比、所有代码/证据哈希、四个真实 MRC 和放行前锁/零污染状态后判定 pass。`/home/penghongen/mrc_contract_release_316115` 于 `2026-07-12T20:21:28+08:00` 原子发布，权限 0600、SHA-256 `2ca92614cb53a9f08058a5186afe677264928b6a64ba2a4b60a044d8cea6b6b2`；pre_lock 只由 run_cmd 删除。

2026-07-13 首轮 DE gate 证据：Stage D status SHA-256 `263fa2af…d5e9f`，Stage E status SHA-256 `b03b7c72…a6c7b0`。E 四终态为 success=22,295、known_failed=72、unknown_failed=19；known failure 分解为 no_occurrences=44、no_present_ligand_atoms=18、missing_map=5、missing_resolution=5。18 个工程失败冻结清单 SHA-256 `6f9bea3a…b280be`；2zhc 单独保留为待决科学数据契约，不进入该清单。

## Interfaces and Dependencies

公共 CLI 必须保留 `--root`、`--part_id`、`--total_parts`、`--n_jobs` 与显式 overwrite/repair 语义。stage 函数返回结构化状态，不用跨模块散落自由文本错误。稳定失败枚举、artifact validators、Chimera runner、MRC geometry 和 quality schema 必须各有单一实现位置。

Python 依赖包括 `numpy`、`scipy`、`gemmi`、`rdkit`、`requests`、`joblib`、`mrcfile`；配体解析继续使用现有 CCD/RDKit 路径。外部依赖是官方 UCSF Chimera 1.19 headless/OSMesa 与 MapQ。AdaLigand 只负责选择、输入构造、调度、严格映射和 QC；CC、molmap 与 Q-score 数值算法调用 Chimera/MapQ，不自研替代实现。

四种 CC 的代码与 README 必须解释：是否使用 contour mask，以及是否先在 mask 内减各自均值；同时保存工具版本、map/model 标识、canonical grid 元数据和 contour provenance。Q-score per-atom 文件必须说明配体 NaN/行序语义，以及口袋的 6 Å 原子包络、受体范围、atom_site.id 排序和 count 语义。

## Plan Drift / Reconciliation

### Beneficial drift

- E2 改为仅在 receptor-only simulated map 中严格删除全部 `HETATM`，与 cryoatom2 受体表达能力对齐。
- E2 改为直接在 E1 target=1 Å/actual-voxel canonical grid 上 `molmap onGrid`，并增加严格三维、shape/origin/actual-voxel/内容 QC。
- MRC 数值核心从未经项目验证的 Ada 独立实现收敛为 Pocket Plus 六函数零差异祖传快照；所有兼容仅留在可枚举薄 wrapper，旧 E schema v1 明确失效。
- F 增加四种全局 CC 和逐原子 Q-score 原始量，使后续过滤可审计、可重算。
- F 增加同一次 MapQ 上的 occurrence 受体口袋逐原子 Q/聚合，不增加外部工具运行次数。
- 失败处理从历史 append 文件升级为 run-scoped 状态与 release gate，消除陈旧失败误报。
- 受体键枚举向后兼容追加 `triple=6`；source-dirty C 增加全集 cache-only audit、完整输入/依赖哈希、CCD atom-name 覆盖和受检 receptor-only 迁移。
- filtered Stage C 增加正式 run 证据覆盖防护，避免子集状态替换 22,386 行全量状态。
- E/F 增加单一确定性 model-map 包围盒前置门与稳定 `model_map_frame_mismatch` known failure，不再用全零模拟图或猜测坐标变换表达 source frame 缺口。

### Neutral drift

- A–C 从“阶段文件存在即跳过”改为组件级 schema-aware 增量迁移；目标样本宇宙和旧基础数组语义不变。
- 运行资源和分片数由真实基准与服务限流决定，不固化旧 4/6 分片模板。

### Harmful drift

- clean spec 曾仍写“E2 保留共价 HETATM、缺分辨率猜默认、sim 二次重采样、legacy 失败不阻塞”，与已经确认并实现的契约相冲突；本次已在用户要求“更新全套日志、计划书、README”后回填为当前规格。
- mmCIF 刷新数最初由不完整 B success 状态低估为 400；文件系统证据修正为 2,156。旧 `known_failed` 丢失逐资源 provenance 的实现缺口已修复，事故细节保留在本 ExecPlan，不把数量写成通用科学规格。
- 契约 README 曾把“EMDB map 与 mmCIF 沉积坐标天然同框”写成无条件事实；2zhc 真实证据否定该假设。现已改为成功样本契约 + 对所有样本执行受检前置检查。

### Unfinished scope

- C source repair、全量 C、ABC gate 和 Stage D 已完成；D–G 代码已实现。MRC 放行证据均已验收；Stage E 首轮全量状态已完成，18 个工程失败正在恢复，2zhc frame mismatch 契约已授权且本地实现通过。未完成范围是安全同步/远端验收、E 正式复核、DE→F→G release gate 与最终独立 QC。
- G 的最终分辨率、选定 CC、配体 Q、口袋 Q 阈值及 contour-null 策略仍须先看正式分布再由用户确认；不得把猜测阈值写死在数值代码里。

Revision note 2026-07-10 14:38+08:00: 创建本 ExecPlan，记录已确认边界、旧产物证据、科学语义、资源/许可纪律和从实现到服务器全量验收的恢复路径。

Revision note 2026-07-11 15:04+08:00: 回填安全同步、工具安装、90 项测试、真实 smoke job 与四类工具兼容性发现；保持全量提交仍受真实 MapQ 严格门禁约束。

Revision note 2026-07-12 01:55+08:00: 记录用户对 DE/F/G 并发与 walltime 的运行前复核、Slurm 提交快照事实和 `316115` 的可逆 hold；当时最终参数仍待用户确认，未改计划规格或下游产物契约。

Revision note 2026-07-12 02:58+08:00: 记录用户确认的原地调度方案、D64/E24/F12、受检预置 run_cmd、三个下游 `UNLIMITED` 与 `316115` release 证据；保留全部原 Job ID 和 afterok 链，更新测试总数及恢复入口。

Revision note 2026-07-12 07:32+08:00: 记录 ABC gate 的 366 个 C unknown failure、`try_lock` 安全暂停、descriptor/mmCIF 复用根因及 102 项回归；明确把受体三键枚举与 source-dirty 迁移留作显式科学决策，未提前修改规划规格或 release gate。

Revision note 2026-07-12 11:20+08:00: 用户显式接受 `triple=6` 与当前 RCSB source 的严格迁移；把 dirty-set 文件系统证据从早期低估 400 修正为 2,156，记录 366 failure 对 43,175 occurrences/506 objects 的系统性影响。实现 cache-only audit、五直接输入 + LigandObject/CCD/实现依赖冻结、CCD 身份/name/元素覆盖、per-PDB CAS、filtered 正式状态保护与独立 repair run；119 项测试、compileall、diff check 通过，并同步回填 clean spec、mapping、README 与记忆。服务器 audit/apply 和全量 C gate 尚待真实执行证据。

Revision note 2026-07-12 13:20+08:00: 回填 2,156-ID 快照、远端 119 tests、6 样本 smoke 与正式全集 audit 证据；记录 379 个隐藏 atom_name_only、23 blocked/5 failed 分解，以及 14 个 5GP source revision 对 20 个新增 occurrence 和 1,995 个 candidate_id 的影响。保持 apply/locks 零动作，新增 ligand-side 迁移等待用户显式授权。

Revision note 2026-07-12 14:45+08:00: 记录用户对冻结 14-PDB 完整 C 重建及额外 48 CPU 的明确授权；把 before/after manifest 限定为本次 run-scoped 审计证据。实现 changed-residue-only coverage、atom-name derived-delta 门禁、显式 CCD prefetch、专用 audit/prepare、2,156 联合零阻断 gate 与四件套 backup/journal/rollback；独立审查发现并在同步前修复 auth-only `_struct_conn` 缩进回归、gate 后全体 CAS、受体额外 key 保留及 try-lock 整链重放缺口，增加 delegated CLI 哈希闭环、all-exact 硬门和阶段感知恢复脚本。本地 136 tests 通过，服务器仍零 apply/零解锁。

Revision note 2026-07-12 MRC contract recovery: 用户明确把 Pocket Plus 训练/验证/测试过的实现设为可信祖传基线，并要求 diff 近零、每一项兼容改动可审计。六个相关函数已零差异 vendoring，Git checkpoint 为 `6de3fb8`；Ada 只保留 Path/MapGrid/float32、两种祖传 origin mode、标准 writer、schema/provenance 和 actual-voxel QC。纠正此前由不符合 Pocket native 输入契约的人工 fixture 导出的 45 Å 批评；当前本地 153 tests 通过。316115 在真实 Chimera 几何 smoke 和远端哈希验收前继续由 MRC contract hold 阻断。

Revision note 2026-07-12 20:04+08:00: 收口 MRC release 前证据。完整差异清单追加两张 mixed-axis 的 `np.any` 薄兼容、祖传补偶 grid 复用和 native/scale/canonical contour 映射；F provenance 逐项绑定当前 E1。正式 header audit、两张 mixed 图真实 Chimera geometry smoke、本地/远端 172 tests 通过，ABC 已完成。Git 按任务拆分 checkpoint；316115 在独立 release audit 和原子 marker 前仍保持 hold。

Revision note 2026-07-12 20:21+08:00: 补齐持久远端 pytest 证据与独立只读 release audit；在同一原 Job 316115 内原子发布带完整哈希的 MRC marker，run_cmd 自行删除 pre_lock 并启动 D64/E24。更新 Outcomes、Artifacts、Plan Drift 与项目记忆到“DE 正式运行”状态。

Revision note 2026-07-13 07:10+08:00: 记录首轮 DE gate 的 D 完整闭合、E 19 unknown 分解和精确 try-lock 安全停点；实现 8ro 固定非致命日志序列窄豁免、filtered E 正式证据保护、未来 E timeout 参数与 18-ID 阶段感知恢复脚本。2zhc 的 frame mismatch 明确保持未决，不把猜测平移或 known-failure 分类静默写入 clean spec。

Revision note 2026-07-13 10:02+08:00: 记录用户授权 `model_map_frame_mismatch`，把通用契约同步到 clean spec/README/mapping 并新建 durable decision memory；实现 E/F 共用确定性包围盒 preflight、自包含失败 detail 和禁止猜变换边界。专项 22 tests 与全套 178 tests 通过，远端同步/复核仍待当前 18-ID repair 进入安全停点。
