# 完成 AdaLigand A–G 数据流水线并全量运行

本 ExecPlan 是动态文档。执行期间必须持续维护 `Progress`、`Surprises & Discoveries`、`Decision Log` 与 `Outcomes & Retrospective`，使只持有当前工作树和本文件的新手工程师或无上下文 AI agent 能够继续完成任务。

上游规格是 `文档/规划文档/数据处理_v2.md`；本计划与它的关系为 **implements and updates**。覆盖范围是现有 22,386-PDB 样本宇宙的 A–C 增量契约迁移、D–G 实现、Chimera/MapQ 集成、自动质量门、服务器全量运行和 G `analyze` 质量分布。最终 `keep_list.jsonl` 只有在正式分布产出、用户显式确认 schema v2 数值配置（含 `cc_field` 与全部阈值）后才进入后续授权，不属于本轮无人值守终点。旧执行日志 `文档/exec_plan/数据下载与解析.md` 只记录历史 A–C 实现，本文件从该基线继续推进。代码旁契约是 `Data_Preprocessing/Ori_Data/code/readme.md`，映射索引是 `文档/mapping/计划执行映射.md`。

本轮不切 BOX，不实现 BOX 第 2/3 层，不修改或重训 Stage 1，也不处理 Stage 2/3。Stage 1 重训将在 A–G 与后续 BOX 接缝完成后另行授权。

## Purpose / Big Picture

完成后，服务器数据根 `/storage/penghongen/AdaLigand/Ori_Data` 将在复用已有下载和旧 A–C 产物的前提下达到当前契约：C 产物包含配体质心、受体化学键、49 维受体特征和去重配体描述子；D 产出受体原子标签；E 通过 Pocket Plus 祖传原语产出 target=1 Å、保存实际 voxel 的实验图、严格去掉全部 `HETATM` 的 receptor-only 模拟图和逐 occurrence ligand-area；F 产出四种全局 map-model CC、配体逐原子 Q、6 Å 受体口袋逐原子 Q 及两类 occurrence 聚合；G 汇总质量和明确失败，先生成可追溯分布，并在用户显式确认 schema v2 数值配置（含 `cc_field` 与全部阈值）后生成 `keep_list.jsonl`。流水线由 Slurm 依赖自动推进，smoke gate 通过后无需人工复制日志或逐阶段确认。

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
- [ ] (2026-07-11 15:47+08:00) 全量 run `adaligand_ag_20260711T154658` 已提交：ABC `316114` → DE `316115` → F `316116` → G analyze `316117`；ABC 与 DE 已完成。Stage F scratch v4、确定性适配恢复、补算 v1/v2 和 19 条正式 run-only exclusion 均已闭合。正式 F producer 已完成 22,386/22,386，raw status 为 16,944 skipped、5,323 success、74 known、45 unknown；原严格 gate 因 45 条 unknown 进入精确 try-lock，`f_release` 尚未形成。用户已批准保留 raw unknown、不重跑、不造占位，并让 gate/G 共用同一份精确 waiver；本地实现与测试已通过，服务器 manifest、远端测试和 gate-only 放行尚待闭合。`316117` 继续只等待正式 `f_release` 并只运行 analyze，整条 DAG 尚未完成。
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
- [x] (2026-07-13 07:25+08:00) 19 个 E unknown 已取证分解为 15 个 Chimera 3600 秒超时、3 个已完整出图但被 `monitor changes` 警告误判、1 个 2zhc model/map frame 不相交。最小 atom_site-only CIF、精确日志豁免、filtered 状态保护和 21600 秒独立恢复入口均已实现；最初以 `n_jobs=2` 启动恢复，随后确认该值偏离此前实测冻结的资源方案并成为主线瓶颈，改由独立 48 CPU、`n_jobs=12` 的标准 Chimera 补足作业推进。这里记录的是本轮恢复路径，不把 12 写成所有未来 repair 的通用最优值。
- [x] (2026-07-13 07:30+08:00) 无删除安全同步和远端 175 tests 通过后，独立 smoke run `adaligand_ag_20260711T154658_eeng_smoke_v1` 使 8ro0/9qqp 2/2 success；release gate、实验/模拟图网格配对、严格 HETATM 删除和 E3 后验全部通过。8ro0 仅保留被精确豁免的 monitor warning，其他 fatal 检查未放宽。已原子发布 316115 run_cmd（SHA-256 `d4c0ff53…a1c1`）并在全部校验后精确删除 `try_lock_316115`；18-ID repair run `adaligand_ag_20260711T154658_eeng_v1` 正在原 allocation 以 E2/21600 秒运行，`after_lock_316115` 与 F/G 依赖仍保留。
- [x] (2026-07-13 10:02+08:00) 用户显式接受将合法但完全不相交的 model/map 归类为 `known_failed:model_map_frame_mismatch`，要求 E/F 统一确定性包围盒检查并记入全套日志。本地已实现单一纯 QC + 单一失败策略包装器，E/F 均在外部工具和 artifact reuse 前调用；禁止 PDB allowlist、猜平移/fitmap，非法输入和后置密度/工具失败仍为 unknown。专项 22 tests 和本地全套 178 tests、compileall、diff check 通过；待独立审查、Git checkpoint、安全同步、远端 smoke/全套和正式 E 复核。
- [x] (2026-07-13 11:42+08:00) 用户冻结 Stage G 为唯一 `schema_version=2` map-level 过滤契约，并明确无需兼容从未正式运行的 occurrence 级 v1。实现直接消费 analyze 的扁平 F 字段，按 PDB 验证唯一 CC/resolution、严格 Q pair、空口袋计分母、含等号比例门和“通过 map 保留全部 occurrence”；新增 map diagnostics，专项 9 tests 与本地全套 182 tests、compileall、diff check 通过。316117 仍保持 analyze-only，本次未同步服务器或执行正式 filter。
- [x] (2026-07-13 15:45+08:00) 取证确认一次性 Chimera 分块/变形路线只服务于超大资源异常 `8ckb`；用户授权撤销该私有算法。专用脚本与隔离 scratch 已删除，`8ckb` 仍保留在 22,386 样本宇宙和审计中，但由正式 run 的 `exclusions.jsonl`（SHA-256 `b586cab2…257fe`）在 E/F 写为 `known_failed:run_policy_excluded`，并从训练、推理和 G 候选自然排除。实现/恢复/gate 加固分别提交为 `43084b7`、`a5b4234`、`7811533`、`59abdd4`、`28b0703`；本地全套为 194 tests。
- [x] (2026-07-13 20:09+08:00) 独立标准补足 job `316415` 使用 48 CPU、`n_jobs=12` 处理 `8glv/8j07/9dp7/9e5c/9fqr/9qwt`。绝对截止 `2026-07-13T19:54:19+08:00` 时，`8j07/9dp7/9qwt` 已有完整三件套，`8glv/9e5c/9fqr` 只有部分产物；后者按用户授权追加本次 run 专属 exclusion，前者继续复用。作业经精确 kill-lock 和孤儿进程复核后于 20:09:28 以 `FAILED 9:0` 结束，elapsed `06:04:02`；该失败是截止协议的预期运行证据，不是 DAG 依赖失败，也未伪造 6/6 success。
- [x] (2026-07-13 15:54+08:00) 用户为 Stage E 长尾冻结绝对截止 `2026-07-13T19:54:19+08:00`：届时仅对仍无完整合格 artifact 的子集追加本次 run 专属的人工授权 timeout/exclusion；已完成样本继续复用。回退必须保留样本宇宙、逐样本运行/超时/无产物证据和 before/after manifest，不能伪造 success、删除 `pair_list` 或把本次特例改写成通用科学契约；完成受检回退后继续 E→F→G。
- [x] (2026-07-13 21:04+08:00) cutoff 工具和 resume v3 已在本地、远端各通过 207 tests；before/after manifest、pre/post 终止证据与 release marker 全部闭合。`VALIDATE_ONLY=1` 返回 `decision=run` 后，原子发布 run_cmd SHA-256 `6e8c88a18472c07c76d6c9caf64472548d39db65ea3aef26d6540024e8e3d828`，并在 21:04:43 以正式 run id、无 filter、无 `--overwrite`、E24 启动全量 Stage E。`316115` 的 `after_lock` 保留，`try/kill_lock` 均不存在；`316116/316117` 继续依赖等待。
- [x] (2026-07-14 01:26+08:00) `316115` 以 `COMPLETED 0:0` 闭合 DE：D 为 22,339 success、3 skipped、44 known；E 为 22,309 skipped-valid、77 known，unknown/duplicate/silent missing 均为 0。E status SHA-256 `3a0d4148…c54c`、`de_release` success SHA-256 `ab49f43c…da6`；完整 status/gate、风险分层 E artifact、四条 run-only exclusion 与 2zhc frame mismatch 三路独立审计均通过。
- [x] (2026-07-14 04:05+08:00) `316116` 已由原 afterok 链同刻启动，日志确认复用预置 run_cmd SHA-256 `8399d571…d13`、`F_N_JOBS=12`；当时完成 944 个外层任务，874 份早期完整质量三件套抽查通过 F 契约。此条只记录首次启动检查点；后续 scratch 回收、补算与兼容恢复另见下文，不能把早期抽查冒充全量 F 验收。
- [x] (2026-07-14 22:46+08:00) F 首轮推进到 22,363/22,386 后，现场栈和只读进程证据把唯一仍在执行的工程长尾定位为 `6kgx`：1,588 个 occurrence、1,011,574 行规范化模型原子，外部 Chimera/MapQ 已完成，Python 在 occurrence 投影中反复扫描百万行 `selected_atom_rows`，且公开质量三件套尚未形成。用户明确授权把当前长尾按本轮超时处理；只对精确 `316116` 使用 kill-lock，core 退出 137 并进入 try-lock，下游 `316117` 始终保持 Dependency。
- [x] (2026-07-14 22:46+08:00) 为避免改写已经闭合的 Stage E，保留共享 `exclusions.jsonl` SHA-256 `380844d0…325f`，新增只供 Stage F 消费的加法视图 `exclusions.stage_f.jsonl`，SHA-256 `3b10abb5…8ee8`；其中原四条逐字段不变，仅追加 `6kgx` 的 `stage_f` run-only 记录。专项 23 tests、本地/远端全套 214 tests、脚本语法和两次独立审查通过；apply 后只读重放前后全部证据哈希逐字节一致。core 随后复用 run_cmd SHA-256 `bd7edb94…5ffa`，于 22:46:44 以原 run id、F12、无 filter、无 `--overwrite` 恢复；全量 F/G 仍未完成。
- [x] (2026-07-15 16:29+08:00) 在不停止、不重提正式 `316116` 的前提下，按用户新增的主用 CPU192 授权启动独立尾部补算 `318350`：正式 F12 留在 `cnode04` 的 96 核，补算 F12 留在 `cnode01` 的另一整台 96 核，总分配恰为 192。补算 run `adaligand_ag_20260711T154658_fsupp96_v1` 只处理冻结尾段 `[19386,22386)` 中 2,990 个 eligible PDB；plan/ID SHA-256 分别为 `1d5c1217…dff4f` / `acacde79…cea80`，并在正式进度到 17,386 前由守护进程主动停止以避免相撞。Windows 全套为 224 passed、2 skipped，服务器 Linux 全套为 226 passed；启动后 `after_lock_318350` 与 child PGID 证据存在，正式/补算均无 try/kill，`316117` 继续只等待正式 F release。
- [x] (2026-07-16 07:45+08:00) Stage F scratch 只读取证确认异常路径会永久残留大型 MRC/CIF；账号分配块在 02:37:40→02:48:29 的 649 秒内净增约 36.61 GiB，即约 3.47 GiB/min。精确 `kill_lock` 同时把 `316116/318350` 分别停在 8,821/22,386 与 2,426/2,990 并收口到各自 try-lock，两个 after-lock/allocation 均保留。exact-attempt 异常安全清理提交为 `a9d9e30`，bundle-bound audit/apply 与 fsync journal 为 `39e5185`，补充生命周期回归为 `d4849fc`。首份 v3 inventory 为 141,437 条文件/11,445 attempts；audit 命中 5,838 个 MRC/CIF、预计实际分配约 2.22 TB，但其后发现 03:03 起遗留在 master 的旧 SSH/stdin v1 `python -` 进程：它在 v3 audit 结束后自行进入无 journal 清理，精确删除 1,497 个 transient（570 CIF+927 MRC，冻结清单预计约 1.085 TiB）。受影响 attempt 的 3,395 条小证据和 744 个公开三件套路径均无存在性/大小/mtime/hash 漂移；v3 bundle 因 live-tree drift 永久作废，v1/v3 均只作事故证据。该旧进程来源有父 bash、stdin 与时间线支持，但缺少系统账本权限，只记录为高可信推断。事故诊断与有效 v4 回收均已由后续条目闭合。
- [x] (2026-07-16 13:22+08:00) 为补上 schema v1 只查 compute 节点的缺口，提交 `d53d190`：正式 process-audit 绑定当前脚本/模块 SHA，逐 allocation probe 与 scheduler/四锁快照后最后探测 `master`，显式阻断 F/工具进程、inventory/recovery、同 UID 裸/`python -`、scan error、stderr、节点/argv/时间窗漂移；audit/apply 必须分别使用新鲜证据。Windows 进程/回收/生命周期专项 48 passed+2 skipped、全套 272 passed+4 skipped；cnode01 Linux 专项 50 passed、全套 276 passed。v4 inventory step `316116.43` 已 `COMPLETED 0:0`：`raw_inventory.tsv` 为 139,940 行、`attempts.tsv` 为 11,445 行，二者 SHA-256 分别为 `e5f3075c…c502a` / `3f9f2096…a863`，`sha256sum -c` 全部通过，`inventory.done.json` 为 `status=success`。
- [x] (2026-07-16 13:32+08:00) 两个 F writer 继续停在各自精确 `after+try`。只读复核确认 PID `54412` 是不归属本任务、扫描其他数据根的容量探针；用户明确决定它不应阻塞 A–G，且不得发信号。commit `cdcf031` 将 process gate 升级为 schema v3：最多允许 controller 上一个 `node+PID+PPID+start_ticks+argv SHA` 完全匹配的一次性例外，raw opaque 行完整保留；第二个 opaque、任一身份漂移、F/recovery、scan error 或 audit/apply 例外漂移仍 fail-closed。本地专项 43 passed+2 skipped、全套 284 passed+4 skipped，compileall 与 diff check 通过。
- [x] (2026-07-16 17:41+08:00) 以两个不同时间点的真实指纹闭合 `process_audit.before_audit.json` 与 `process_audit.before_apply.json`；零删除 audit、独立 bundle 验收和 journaled apply 均已完成。两个证据复用同一 controller 例外指纹，第二个 opaque、身份漂移、F/recovery 或 scan error 始终会阻断。
- [x] (2026-07-16 13:30+08:00) 用户为优先恢复 A–G 明确放宽 scratch 验收：公开质量三件套仍须完整 SHA-256 逐字节不变；普通 nontransient 日志/证据只须以路径、类型、大小、mtime 和已有或必要哈希证明实质内容未变，不要求为全部大于 16 MiB 的保留文件追加全量哈希。该决定只降低回收工具的非科学证据成本，不改变四 CC、配体/口袋 Q、质量三件套或任何 F/G 科学契约。
- [x] (2026-07-16 17:41+08:00) 唯一有效 v4 bundle 已完成 journal/fsync apply 并通过独立定向验收：删除 manifest 恰含 4,341 个 transient，journal 恰含 4,341 条 intent 与 4,341 条 deleted；923 个受影响 attempt 的 10,260 个普通 nontransient 与 2,568 个公开质量三件套路径均通过冻结身份复核。预计回收 1,028,652,285,952 B（约 958.01 GiB），quota 约下降 1008.73 GiB 只作旁证。delete manifest/bundle/progress/apply-summary SHA-256 分别为 `fd4b6ec3…5993`、`0966e35c…f92`、`6071109a…f0fc`、`4dfd0853…f649`；v1/v3 永久作废且未被 apply。两个 F writer 仍由各自 `after+try` 精确停写，等待代码同步、远端全套和顺序恢复，不再受 scratch 回收门阻断。
- [x] (2026-07-16) 用户冻结本次正式 run 的巨大长尾运行策略：当前 `8ckb/8glv/9e5c/9fqr/6kgx` 共 5 个 run-only exclusion；后续只有在客观证明样本正在形成活动长尾、缺少本阶段完整公开 artifact 且存在明确运行时/资源证据时，才可自治追加，最多再追加 4 个，使累计始终不超过 9（严格少于 10）。样本继续留在 22,386 分母，以 `known_failed:run_policy_excluded` 终态审计并排除训练、推理和 G 候选，不伪造 success；累计将达到 10，或同类失败开始聚集/呈系统性趋势时，必须停止个例化、诊断根因并询问用户。
- [x] (2026-07-16 18:10+08:00) 用户冻结 E3 半体素修复契约后完成本地实现：MRC 六函数继续零差异，E3 直接原样 vendoring Pocket `_build_voxel_center_coords_xyz`，以网格下角点 `origin` 和 `origin+(index+0.5)*voxel` 从 Stage C 原子重新生成 schema v3 稀疏 mask；仅 `ligand_area.npz` 使用 `np.savez_compressed`、写后完整 validator 和原子覆盖。核心 Git checkpoint `75d8f42` 与信任边界/记忆 checkpoint `92fc2e8` 的本地全套为 309 passed、10 个 Windows 条件项 skipped。后续 `e90fccc` 又彻底删除解析 bbox/`searchsorted`/索引反推，只直接筛选祖传函数实际生成的 float32 中心，300/300 完整 Pocket 网格 oracle 零差异；`1780942` 把 E/F frame preflight 窄修为 Pocket 物理 BOX `[origin, origin+shape*voxel]`，专项 9 passed，不改 MRC、molmap、CC 或 Q 数值内核。
- [x] (2026-07-16 20:52+08:00) E3 服务器迁移前门禁与 pilot 已闭合。远端 Linux 全套为 361 passed，三项独立终验分别确认上下游对齐、Pocket 祖传中心忠实性和 v2→v3 差异可接受；未发现广泛硬伤。迁移 run `adaligand_ag_20260711T154658_e3v3_v1` 冻结旧 E 合格集合恰 22,309，target IDs/manifest SHA-256 为 `35108a7a…a10b` / `18313414…1f10`，77 个 known failure 不复活。held array `318882` 的 part 0 pilot 用 16 CPU 完成 465/465 success，状态 SHA-256 `072f66a5…6cbc4`；28,115 个 ZIP 成员全部为 DEFLATED，轻量落盘复核 summary SHA-256 为 `880f1f8d…13f93`。launch/authorization manifest SHA-256 为 `86851f67…3ac0` / `c179829b…5aa7`。
- [x] (2026-07-17 05:30+08:00) E3 全量迁移与 canonical release 闭合：`318882` 的 48 个 array task 和 `318883` 共 49 个授权作业全部 `COMPLETED`，48 份状态恰覆盖 22,309 个唯一目标且全部 success。source-aware gate 验证 22,309 份 schema v3、当前 Stage C 原子重建、Pocket 几何身份和 `ZIP_DEFLATED`，summary SHA-256 为 `796bc90c…be37`。直接 `squeue` 终态快照 SHA-256 `f9705efe…32d8` 仅查询 `318882/318883` 且 stdout/stderr 为空；canonical launch control 随后发布 intent/release SHA-256 `0657c85b…e25d` / `fdcef799…bb3e`，精确移除该 run 持有的全局 writer lock。独立事后验收确认锁根仍存在、仅目标锁被移除，旧 Stage E status、`de_release`、exclusion 与 pair-list SHA 均逐字节不变；77 个旧 known failure 没有复活。E3 不再阻塞 Stage1，训练就绪现在只等待 A–G 最终 gate。
- [x] (2026-07-17 03:02+08:00) 尾段补算 v1 的 2,990 行状态闭合为 2,153 skipped、484 success、353 unknown；2,637 个 success/skipped 全部具有合法质量三件套，353 个 unknown 均为 0/3。逐例归因把 unknown 完整分解为 289 个 MapQ 三位小数坐标写出差异、15 个跨 occurrence 合法复用 `_atom_site.id` 被全局唯一检查误拒、45 个 Chimera solid contour 的 Midas level 语法失败、4 个 MapQ 确定性身份规范化差异；没有未分类余项。
- [x] (2026-07-17 03:02+08:00) 确定性适配修复提交为 `751c8b5`，远端 Linux 全套 369 tests passed。独立 shadow smoke `adaligand_ag_20260711T154658_fcompat_smoke_v1` 与只读重放 `adaligand_ag_20260711T154658_fcompat_smoke_validate_v1` 覆盖 7 个旧失败代表和成功基线 `9jcs`；其证据目录为 `/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_ag_20260711T154658/stage_f_adapter_recovery_20260717_v1/real_smoke/`，smoke manifest/acceptance SHA-256 为 `51ea388f7e619f74aed9ae60bb8ae30f0c62473dd625aef6491b411fd8d2b19f` / `c07a40bb750a67129f127097b575b8d03d7928e81ce2447ae88f3139c9008581`，`9jcs` 四项 CC 新旧 `max_abs_diff=0`。随后独立 promotion run `adaligand_ag_20260711T154658_fcompat_promote_v1` 使 7/7 旧失败样本形成合法三件套；promotion 由该独立 run 及 acceptance/gate SHA-256 `0d570a9dbb424923f54ffeafcb6e323d5690f175f842b98e884eafb930d6de80` / `3d5af50a1f6062816c5d539728c868e309c5df4330bf99ffc575b0a717aed681` 定位。
- [x] (2026-07-17 03:02+08:00) 此冻结检查点上，`318350` 与 `316116` 仍各自保留 `after_lock+try_lock`，`kill/pre` 均不存在，且没有 F/Loky/Chimera/MapQ 进程；兼容 promotion 通过不等于两个 writer 已恢复。该状态只记录放行前证据，不代表当前仍有两个 try-lock。
- [x] (2026-07-17 03:07+08:00) 当时在远端 369 项全套、真实 smoke/replay、promotion、锁 inode 与双节点无残留进程门通过后，只删除精确 `try_lock_318350`；release script SHA-256 为 `784adf6e…1187`。wrapper 于 03:07:24 复用 run_cmd SHA-256 `ca04f4f…25f3e` 重进 v1，child PGID `113024`、guard、12 个 Loky worker 及 MapQ/Chimera 子进程均绑定补算 run。该次恢复最终把 353 unknown 收敛为下一条记录的六个 signal-11 unknown，未满足原定 unknown=0 放行条件，因此 `316116/318350` 又回到精确 `after+try` 停点；后续路径已被用户的 run-only 授权取代。正式 `316116` 始终是 22,386 行 status/`f_release` 唯一 writer，`316117` 继续 dependency/analyze-only。
- [x] (2026-07-17) 修复后的补算 v1 最终仅余 `9bw7/9c1k/9dgr/9fkb/9mxv/9nw3` 六个 unknown，status SHA-256 为 `7938aea615c19029265587d556622c8f2d6aea5acff59a94baa85813698496b6`。独立 `n_jobs=1` shadow 对六者仍为 6/6 fail，step `318350.61`，status/acceptance SHA-256 为 `5c41167deb1e17e8fade06c588c25bf4786048ca9286f4e1e317b4c296af50f9` / `67cc083c94efbb72648db07e5d62ec8fee195bbf3a3dc59eecb5dcbf0ed868b2`，排除了外层 Loky 并发作为唯一原因。首版 ALL-only fresh-process shadow `318350.63` 因诊断 harness 自身 `ImportError` 而零科学计算，永久只作失败证据；修正后的 v2 `318350.64` 以 `COMPLETED 0:0`、elapsed `00:04:24` 闭合，控制样本 `9hhl` 的 `cc_all/cc_all_about_mean` 与 canonical 值逐位相同，而 `9fkb` 的 fresh ALL 子进程仍为 signal 11，acceptance SHA-256 为 `e0bef08c6a4da804d0173ccc920e3e58316912ee4fea303bf9045ad4f50032e9`。
- [x] (2026-07-17) 用户选择 run-only 收口：只对正式 run `adaligand_ag_20260711T154658` 的 `9bw7/9c1k/9dgr/9fkb/9mxv/9nw3` 记录 `run_policy_excluded:chimera_full_grid_cc_signal11`，并把本 run 的排除上限由 9 显式放宽到 30。追加后总数为 11/22,386（约 0.049138%）。该授权不改变四 CC、F 成功定义或未来 run 的科学契约；生产代码禁止写 PDB allowlist，六个 ID 只能存在于绑定 run/evidence 的 manifest。
- [x] (2026-07-17 12:50+08:00) 六项 run-scoped manifest 工程由 `879f2be/aec286b/ebbef37` 闭合半迁移恢复、进程门和 Windows MAX_PATH；最终 transition/supplement resume/formal resume/test SHA-256 分别为 `55e81acc46326e766c0a7c44d7b5d89d213a7d26e17938eb2447a1e9c70a3dfb` / `3da2b388acdbf599ab2f4d0ae7876c2b277cc74d6c346a8f2ab1c5f30cb0fc43` / `f8adf31fec1cdc45bed338abda58027931b3d4894ccd88d63e438d9b81476a95` / `eed82818901df13ebb901db6f69b2a300376aa1b53b103832a0f7d6553b7b335`。独立复核无阻断；本地专项 18 passed、全套 377 passed+10 skipped，远端 Linux 全套 387 passed。端到端 fixture 证明六例只写真实 known 状态，质量三件套保持 0/3，G 可按完整性自然排除，不生成任何占位产物。
- [x] (2026-07-17 12:59+08:00) 新鲜 master+cnode04+cnode01 进程门以 schema v3/status success 闭合，audit SHA-256 为 `697bcb28d0d3cf43bbd883e5e0247d4241630a84a87ae6ffb716de75e3ebd063`；当时双 job 仍为精确 `after+try` 且无 writer。受检 apply/replay 后，正式共享 4 条 manifest 仍为 `380844d0…325f`，正式 Stage F 视图从 `3b10abb5…8ee8` 原子追加为 11 条、SHA-256 `10c5d923779645a6eeeeb5d277722e6f487593557c095cfcdef641553613c8ac`；补算 v1/v2 各自六条 manifest SHA-256 为 `6f3a0a880e6e38768e1e096b2bcb776087372be56987b4a930c88306b5527f35` / `43da55a71885730458cab546f6eb96e38722b726445eaf3613873f23e74b7d40`，六例 canonical 质量产物仍恰为 0/3。
- [x] (2026-07-17 14:16+08:00) 补算 v1 以 2,990 unique 闭合为 2,984 skipped + 6 manifest-bound known，unknown/duplicate/silent missing 均为 0；status/release SHA-256 为 `04d6474e…39a7` / `9a445fa4…9426`，六例公开质量三件套仍为 0/3，且补算未写正式 status/`f_release`。wrapper 随后进入独立 v2，5,984-ID/plan SHA-256 为 `7f427993…17c6c` / `116084c3…64fc`，guard、child PGID `165143`、F12 与首个真实进度均通过。受检 release 两次复核这些事实后，原子替换正式 run_cmd 为 SHA-256 `6c1f89a5…c00d`，仅删除精确 `try_lock_316116`；正式 F 已在原 CPU96 allocation 恢复，`after` 保留、`try/kill/pre` 不存在。manifest 的退出条件仍是正式 F status/`f_release`、Stage G analyze 与最终 A–G 审计闭合；依赖它的一次性脚手架须在最终维护收口中审查、归档或移出生产入口。
- [x] (2026-07-18 16:33+08:00) 补算 v2 已完成 5,984/5,984 并写出 5,984 行唯一状态，但 `f_supplement_release` 因 8 个真实 unknown 未形成：2,984 skipped + 2,986 success + 6 已有 known + 8 unknown，status SHA-256 为 `3231dfe5…23e`。五例 `7ju4/7kzm/7z8f/7z8i/8olb` 在 molmap 与 contour CC 后于祖传 full-grid ALL 路径 signal 11；三例 `7yiu/8e45/8j07` 在 molmap 运行满 3,600 秒后 timeout，其中前两例是缺失 CCD 模板抓取，`8j07` 才是巨大模型/网格。八例公开质量三件套均为 0/3，attempt 只剩小日志，没有大 MRC/MAP/CIF 残留。为避免正式 F 在约 17k–19k 位置再次撞到同一边界，已对精确 `316116` 创建 kill-lock；core 自行移除 kill 并创建 try。当前 `316116/318350` 均保留 `after+try`，`kill/pre/child_pgid` 不存在，cnode04/cnode01 无 F/Loky/Chimera/MapQ 进程，`316117` 仍严格等待 `afterok:316116`。Phase-2 只允许把正式 F 视图从 11 条追加为 19 条、补算 v2 从 6 条追加为 14 条；共享 Stage E base4 与补算 v1 六条必须逐字节冻结。
- [x] (2026-07-18 17:00+08:00) 用户把当前正式 run 的 run-only exclusion 上限从 30 进一步放宽到 100。旧 30 继续作为 2026-07-17 首轮六例迁移的历史证据，不回写旧 manifest；Phase-2 与此后的当前-run门使用 100。该上限只表示最多可容纳多少条经过逐例取证的决策，不是自动排除配额，也不允许把系统性失败拆成无上限 PDB 特判。
- [x] (2026-07-18 17:45+08:00) Phase-2 本地工程 checkpoint `a397e45` 已闭合。独立终审发现旧 v2 plan 的 `collision_stop_completed_tasks=14386` 已低于正式日志历史进度，直接复用会让补算在启动前以 75 退出且永远不形成 release；服务器尚未同步或解锁，因此没有产生写入。修复保留旧 progress guard 默认语义，只为本次 v2 显式启用 formal-held：冻结 `316116` 的 after+try 文件身份、要求 kill/pre/child 缺失并用 canonical cnode04 probe 证明零 writer；启动屏障前、运行中、child 末检和 release gate 前均复核，漂移以独立非零 76 回收精确 PGID 并写唯一严格 marker。专项为 59 passed、8 个 Linux/POSIX 项 skipped，`py_compile`、两 wrapper `bash -n`、占位扫描和 `git diff --check` 通过；Windows 默认 Python 缺 `rdkit/gemmi`，全套在 collection 明确失败，必须由远端 Linux 全套补齐，不能冒充本地全套通过。formal 11→19 / v2 6→14 仍未 apply，双 writer 继续处于 `after+try` 停点。
- [x] (2026-07-18 20:51+08:00) Phase-2 迁移后的补算 v2 以 5,984/5,984 unique 闭合为 5,970 skipped + 14 manifest-bound known，unknown/duplicate/silent missing 均为 0；status/release SHA-256 为 `8babca24…d0c` / `123bed2c…fd69`，八例公开质量三件套继续保持 0/3。`318350` 为 `COMPLETED 0:0`，其 after/try/kill/pre/child PGID 已由 core 清理，补算未写正式 status/`f_release` 或释放 G。
- [x] (2026-07-18 21:54+08:00) fresh master+cnode04 process audit `eb6f8638…ac6f6` 与独立只读复核均 PASS；原子 intent/result `8d0caa57…2ee6` / `bc5006a2…60d2` 在复核 after/try inode、run_cmd、补算 release、八例 0/3 和 `316117` 依赖后，只删除精确 `try_lock_316116` 并保留 after-lock。core 记录 `[Retry]` 与 `[Attempt] 21:53:48`，复用 run_cmd `0ff22ef9…e131`；readiness success、F12/Loky12 与 289→341 的真实进度增量经独立审计通过，`316117` 仍为 `PENDING(afterok:316116)`。
- [x] (2026-07-20 06:43+08:00) 正式 F producer 完成 22,386/22,386；状态集合与 pair-list 精确一致，重复、silent missing 和 extra 均为 0。四终态为 16,944 skipped、5,323 success、74 known、45 raw unknown，status SHA-256 `4280757c…f503d`。45 条与正式 19 条 `run_policy_excluded` 无交集，公开质量三件套全部为 0/3，最终 attempt 未留 MRC/MAP/CIF；严格 gate 按原契约阻断并创建精确 try-lock，`f_release` 不存在，cnode04 无 F/Loky/Chimera/MapQ writer，`316117` 继续等待依赖。
- [x] (2026-07-20) 用户明确授权保留这 45 条原始 `unknown_failed`，不伪造 success/known、不重跑科学计算、不生成占位产物；gate 与 G 必须消费同一份逐状态行/证据/0-of-3/代码/进程门 SHA 绑定的 waiver，自然排除训练、推理与 G 候选。当前 run 的硬上限由 100 提升到 200；既有 19 条 exclusion 加 45 条 waiver 的累计为 64，但两类集合和历史 manifest 必须保持分离。
- [x] (2026-07-20) 本地完成默认严格的 waiver schema v1：无参数时所有 unknown 仍阻断；只有 Stage F 非 strict-smoke gate 可显式使用 waiver，G analyze 必须匹配成功 `f_release` 中同一 SHA 并在输出中保留 raw unknown。独立审查补齐 attempt→process-audit job/node 绑定、canonical schema v3/15 分钟进程门、单次字节 hash+parse 与 gate-A/G-B 负例；专项 65 passed、2 skipped，本地全套 402 passed、10 skipped，compileall 与 diff check 通过；尚未安全同步服务器或释放正式锁。
- [ ] 持续只读监控；任何可能阻断 gate 的异常先冻结证据并向用户报告范围、风险、置信度、修复/重跑成本与选项。未经用户明确决定不得自动终止 producer、修改代码、开路、重跑或重提。
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

- Observation: 2026-07-15 的低噪声监控遇到三种 SSH 主机密钥同时变化；密码不构成服务器身份证明，因此在恢复认证前先停止连接，保留旧 pin，并取得用户对当前 endpoint 的显式恢复授权。
  Evidence: 三次独立公开握手得到完全一致的 ED25519/ECDSA/RSA 指纹；精确更新 `known_hosts` 后只使用严格主机校验登录，随后 `master` 主机名、账号、两个固定 AdaLigand 根目录、正式 run、DAG `316114→316115→316116→316117` 及其完整 Slurm 时间线均与冻结证据连续。恢复期间没有触碰远端作业、锁或产物。

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

- Observation: Stage E 工程恢复最初临时采用 `n_jobs=2`，但该并发没有继承此前对正式阶段做过的实测资源结论，长时间没有新增完成样本，实际成为 A–G 主线瓶颈。
  Evidence: 用户指出漂移后，独立补足 job `316415` 改为授权范围内的 48 CPU、`n_jobs=12`，仍只运行标准 Chimera；本条只说明本次低并发漂移与纠正，不能据此推导所有 map 尺寸下的通用最优并发。

- Observation: kill-lock 停止 `316415` 的主进程组后，三个标准 Chimera 子进程仍成为孤儿进程，不能仅以 Slurm 主脚本退出判断外部工具已经停止。
  Evidence: PID `160147/160179/160191` 分别绑定 `9e5c/9fqr/8glv` 的用户、完整命令行和 scratch 路径；逐 PID 复核后发送 TERM/KILL，并以独立进程审计确认三者均已消失，之后才删除该 job 的精确 after-lock。截止时只有 exp 而没有 sim/ligand-area 的 partial 三件套不算完成。

- Observation: resume v3 第一次 `VALIDATE_ONLY` 被 release marker 中 7 位小数的 ISO 时间戳阻断；该时间戳由 Windows `Get-Date -Format o` 生成，而服务器 Python 的 `datetime.fromisoformat` 只接受到 6 位小数。
  Evidence: 预检失败期间 `try_lock_316115` 保持、正式 E 零启动；仅把 marker 的 `released_at` 规范化为 6 位小数并重新发布后，预检才返回 `decision=run`。这证明 release 预检在进入正式计算前实际生效。

- Observation: 正式 E24 的无覆盖全量刷新最终没有重新计算已合格 artifact，而是把 22,309 个样本记为 skipped-valid，并把其余 77 个全部收敛为显式 known failure；因此正式状态重建与昂贵 artifact 重算可以安全解耦。
  Evidence: E status 恰为 22,386 行，unknown、duplicate、silent missing 均为 0，SHA-256 `3a0d4148…c54c`；风险分层 E1/E2/E3 artifact 审计和 `de_release` marker `ab49f43c…da6` 同时通过。

- Observation: 正式 F 的 96 核 allocation 不等于外层 Python 会持续占满 96 核；F12 在 MapQ 阶段可瞬时达到约 12×8 个内层 worker，但真实采样的整作业平均活跃 CPU 约为 43–44。直接把正式 F 外层并发提高到 24 会在 MapQ 峰值过订阅，并且需要中断正式作业；更安全的加速是让另一台 96 核节点对尚未接近的尾段运行同一 F12 契约。
  Evidence: `sstat`/节点进程采样、正式日志进度 6,248/22,386、冻结 F12×MapQ np8 资源契约，以及尾段 3,000 任务的独立关键路径核算。末 3,000 预计补算约 16.6 小时，正式流到 17,386 碰撞门约 31 小时，预期缩短关键路径约 14–16 小时；扩大到 5,000/6,000 会失去安全裕量，故未采用。

- Observation: Stage F 原实现只在 `build_quality()` 成功写完三件套后 unlink 五个最终路径，清理不在 `finally`；canonical/model 原子临时文件、Chimera partial MRC、native 解压 partial 和 MapQ 返回前 CIF 都可在异常后永久留在 scratch。Lustre 的逻辑大小不能代替实际分配，且对整个 scratch 做一次全树 metadata inventory 可能超过 30 分钟。
  Evidence: 早已完成的补算样本 `8pvd` 仍有约 137 MiB 实际分配；停写前在途样本 `5iqr/5ij0/9pgm` 分别约 1.43/2.30/2.82 GiB。`lfs quota` 三次快照为 79,782,312,468、79,820,704,716、79,826,663,828 KiB；共享 `/storage` 使用率 94%、可用约 97.58 TB，虽然没有用户 hard quota，净增长仍必须立即止损。交互式 Python/`find` inventory 两次分别在 15/30 分钟连接上限前未原子完成，因此最终 inventory 改为绑定保留 allocation 的后台 step，避免盲目重扫或无证据删除。

- Observation: “allocation 内零进程”不足以证明 scratch 可安全回收。旧 process-audit schema v1 没有检查 master，也只按脚本 token 匹配；一个命令行为 `python -` 的旧 SSH/stdin 脚本可在登录节点长时间扫描后进入删除阶段，同时让两台 compute probe 都报告零。quota 下降也不能精确反演 unlink：Lustre 的空间回收和计账存在明显延迟。
  Evidence: PID 52523/PPID 52118 的父链、stdin 命令、v1 manifest/summary mtime 与 v3 audit 结束时间构成闭合时间线；v1 无 journal/apply/stop marker。精确存在性重放显示删除前沿停在 1,497 个 transient，而小证据/公开三件套未漂移。终止该进程后 quota 仍缓慢下降，但 controller/compute 均无 cleanup，说明后续下降不能解释为继续删除。新 schema v2 的首次真实 probe 又正确识别了另一个只读 `python3 -` 容量扫描，证明 opaque-stdin guard 有效且会保守阻断。

- Observation: E3 旧 schema v2 把 Pocket Plus 的下角点 `origin` 直接当作索引中心，造成确定性的半体素错位；这不是 `load_map` 或 `make_model_grid` 的祖传缺陷。修复时一度考虑自写等价中心轴和解析候选边界，用户明确拒绝后全部删除；当前代码直接 vendoring Pocket `_build_voxel_center_coords_xyz`，并只对祖传函数实际生成的各轴 float32 中心做范围筛选。
  Evidence: Git `75d8f42` 保持 MRC 六函数零差异，新增 `voxel_gt_pocket_legacy.py/.source.json` 与直接源码/AST parity；`e90fccc` 删除解析 bbox、`searchsorted` 与索引反推。300/300 组完整 Pocket 网格 oracle 对照零差异；`75d8f42/92fc2e8` 基线本地全套为 309 passed、10 skipped。旧 mask 不参与迁移计算。

- Observation: 用户冻结下角点/半体素语义后，只读审阅发现 E2/F 的 model-map frame preflight 和未使用的 `grid_world_bounds` 仍使用旧端点公式 `origin` 到 `origin+(shape-1)*voxel`。生产前置门已由 `1780942` 窄修为 Pocket 物理 BOX `[origin, origin+shape*voxel]`，专项 9 passed；该修复不参与 MRC 重采样、molmap、CC 或 Q-score 数值。`mrc.py::grid_world_bounds` 当前只有测试引用，保留为 P2 维护项，不能误称为生产阻塞。
  Evidence: `code/qc.py::model_map_frame_errors`、`code/density.py::ensure_model_map_frame_compatible`、`code/quality.py` 与 `code/mrc.py::grid_world_bounds` 的调用审计；Git `1780942` 及对应 9 项 frame-preflight 回归。

- Observation: 补算 v1 的 353 个 unknown 并非 353 份独立科学输入失败，而是四类可由固定上游写出行为完全解释的适配器误拒：289 个 MapQ 坐标三位小数序列化、15 个跨 occurrence 合法复用 `_atom_site.id`、45 个 Chimera solid contour 参数语法、4 个 MapQ 确定性身份规范化。
  Evidence: 2,990 行补算状态中 2,637 个 success/skipped 都有合法三件套，353 个 unknown 均为 0/3 且四类计数相加恰为 353。commit `751c8b5` 后远端 369 tests passed；8 样本 shadow smoke/replay 全部通过，成功基线 `9jcs` 四项 CC 新旧 `max_abs_diff=0`，7 个旧失败样本的独立 promotion gate 通过。该证据只授权固定序列化/规范化兼容，不授权 PDB allowlist、任意坐标容差或身份放宽。

- Observation: 上述适配误拒修复后仍有六个大网格样本在单 PDB、单进程条件下失败；fresh-process 隔离又把故障收窄到 classic Chimera 的 ALL 相关路径，而不是 contour CC、MapQ、外层 joblib 并发或 Python 三件套 writer。
  Evidence: 补算 v1 status SHA-256 `7938aea6…96b6` 只剩 `9bw7/9c1k/9dgr/9fkb/9mxv/9nw3` 六个 unknown；`stage_f_cc_sigsegv_shadow_20260717_v1` 的 `n_jobs=1` step `318350.61` 为 6/6 fail。ALL-only v1 step `318350.63` 因 harness `ImportError` 没有执行科学计算，不能支撑任何结论；修正后的 v2 step `318350.64` 中，`9hhl` 两个 ALL 值与 canonical 逐位相同，证明 fresh harness 能忠实执行祖传公式，而 `9fkb` 仍 signal 11。运行节点约 2 TB RAM，且现场没有节点或 cgroup OOM 证据，因此不能把问题简单归因为宿主物理内存不足或继续拍脑袋增加 worker/RAM。

- Observation: classic Chimera 1.19 的 ALL 路径会先把实验图全部非零 grid 点物化为 `float32 (N,3)` 世界坐标，再生成权重和插值向量，峰值工作集随非零体素数线性增长；这解释了故障为何只聚集在超大图，但 signal 11 本身仍不是修改四 CC 科学公式的授权。
  Evidence: 安装版 `FitMap/fitmap.py` 的 `map_points_and_weights(..., above_threshold=False)` 调用 `grid_indices(m.shape[::-1], float32)`、按 `m.ravel()!=0` 取点，再由 `map2.interpolated_values` 三线性插值；最终 `overlap_and_correlation` 仍用 `_volume.inner_product_64` 与 float64 mean 计算 `cc_all/cc_all_about_mean`。若采用分块实现，必须保持非零点 C-ravel 顺序、float32 点/权重、原世界变换、原插值及最终 reducer；单纯流式 sufficient statistics 因改变浮点归约顺序不能自动宣称祖传结果等价。

- Observation: 补算 v2 新增的 8 个 unknown 不是一个同质的“大图长尾”集合。五个 952³–1168³ 网格与既有六例相同，稳定落在祖传 full-grid ALL 的 signal-11 边界；`7yiu/8e45` 是小网格下缺失 CCD 模板抓取直至 3,600 秒，只有 `8j07` 同时具有约 3.07 GiB 网格和 353,362,726 B 原始 CIF。三类必须分别记录，不能把模板网络/缓存边界伪装成大图或笼统人工超时。
  Evidence: v2 status SHA-256 `3231dfe5…23e` 的 8 条原始 unknown、各自 Chimera stdout/stderr、网格 shape/字节、raw CIF 大小、attempt 目录与 0/3 公开产物快照；独立审计确认五例都在 `ADALIGAND_CC_ALL_BEGIN` 后返回 `-11`，而三例都在 molmap 阶段达到 3,600 秒。

- Observation: 现有 `unknown_failed` 门把“原始运行证据”“下游是否可安全排除”和“未来代码是否已原生分类”耦合在一起。对已经逐例闭合、公开产物明确缺失且不影响兄弟样本的少量失败，仅为把 raw unknown 改写成 known 而停止 producer、修改分类器并重放 no-overwrite 全集，会产生与科学收益不成比例的调度和校验开销。
  Evidence: `filtering.load_stage_statuses()` 会在加载后直接拒绝 unknown，`stage_release_gate.py` 又要求 exclusion manifest 与真实 `known_failed:run_policy_excluded` 逐项一致；G 使用同一 loader，因而只绕 release gate 仍会阻断。Phase-2 虽未重算已有合法 CC/Q 三件套，但停写、工程实现、远端验证、manifest 迁移和补算/正式状态重放仍累计消耗约 10 小时。用户据此冻结“受控失败放行与延后补票”规则，要求未来不再为同类小批可控失败做面子式科学重跑。

- Observation: 正式 F 的最后 45 条 raw unknown 不是一个可安全统称的单一类别：32 条为 Chimera ALL signal-11、8 条为外部工具 timeout、2 条为 fatal-log、3 条为 MapQ Q 值越界。它们共同满足的运行级事实是计算已终止、公开质量三件套 0/3、无活动 writer 与无共享污染，而不是共同拥有同一科学原因。
  Evidence: 正式 status/pair-list/19 条 exclusion 三路独立只读审计；45-ID SHA-256 `bfa2080d…b5d6`，逐 raw-row 分类表 SHA-256 `0b74e9df…76de`，45/45 产物完整性与 attempt 定向审计通过。

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

- Decision: Stage F 对 MapQ/Chimera 输出只接受可由固定上游实现逐字段证明的确定性兼容：(1) MapQ 坐标按其 `%.3f` 写出值比较；(2) `_atom_site.id` 只要求同一 occurrence 内不重复，允许不同 occurrence 合法复用；(3) `HETATM X/UNK/UNX` 到 `type_symbol=LP` 及真实 author-residue-key 冲突引发的 component 规范化按 MapQ `ReadMol/WriteMol` 规则核验；(4) contour 通过 `experimental_map.set_parameters(surface_levels=[contour])` 设置，不再把 solid representation 交给 Midas `volume ... level`。四项 CC 公式、mask、contour 数值、MapQ `sigma=0.4,np=8`、配体/口袋 Q 和 occurrence 身份契约均不改变。
  Rationale: 适配器必须验证外部工具真正写出的稳定结果，而不能拿内部高精度值或另一套命令解析语义制造假阴性；同时，兼容边界必须窄到可由上游源码和真实 shadow smoke 重放证明，禁止任意容差、PDB allowlist 或宽松身份匹配。
  Date/Author: 2026-07-17 / Codex（用户既有严格身份与不改科学量边界内）

- Decision: 四种 CC 通过 Chimera `measure correlation` 的同一底层官方 `FitMap.map_overlap_and_correlation` API 获取，并由适配器打印高精度 marker。
  Rationale: `--silent` 会吞掉 GUI reply 文本，直接调用同一实现可保留精度、确定输出格式和严格区段解析，不改变 contour/nonzero mask 语义。
  Date/Author: 2026-07-11 / Codex（真实 smoke 证据）

- Decision: 缺少可用 map resolution 的样本在 E2/F 的需要分辨率路径中记为 `known_failed`，不猜保守默认。
  Rationale: molmap resolution 会直接改变模拟密度，猜测值会污染 CC、sim 和下游训练输入。
  Date/Author: 2026-07-10 / Codex（落实用户“机器检查优先、禁止静默兜底”的边界）

- Decision: E1 重采样除几何正确外还必须保持常数/DC 幅值；早期 E3 使用局部 voxel stencil 的实现决定已于 2026-07-16 被用户冻结的 Pocket-first 规则取代。当前 E3 必须直接筛选 Pocket 祖传函数实际生成的 float32 中心，禁止解析 bbox、`searchsorted`、索引反推、自写等价中心或全图坐标 KD-tree。
  Rationale: recommended contour 只有在幅值语义保留时才能迁移到 canonical map；E3 的中心数值则以经过项目训练/验证/测试的 Pocket 实现为唯一权威，不能再用“数学等价”主张替代可逐项直比的祖传行为。
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

- Decision: G 的唯一正式过滤配置升级为 `schema_version=2` map-level 契约，不兼容从未正式执行的 occurrence 级 v1。每个 occurrence 以严格大于的 ligand/pocket Q 计算 pair pass，空口袋失败且计入分母；CC、resolution 和合格比例按含等号边界决定 map，通过 map 保留其全部 occurrence。正式 DAG 的 316117 仍只运行 analyze；示例数值不自动成为生产配置，只有显式 JSON 及 hash 才允许写 `keep_list.jsonl`。
  Rationale: F 已保存全部原始量，G 可零重算完成 map 级选择；首次正式 filter 尚未发生，没有旧 keep list 或下游消费者需要兼容。单一 v2 避免同一仓库同时保留两套相反的 occurrence/map 过滤语义，并继续避免把 artifact-valid 清单冒充科学筛选结果。
  Date/Author: 2026-07-13 / User + Codex

- Decision: Stage E/F 标准模型只保留 `_entry.id`（若存在）与逐字段原样筛选的 `_atom_site`；Stage E 的 Chimera fatal-log 扫描只豁免精确的 `monitor changes`/`KeyError '?'` 两行组合。filtered E repair 必须使用新 run id，补齐 artifact 后再用正式 run id 无过滤、无 overwrite 全量刷新状态。
  Rationale: 悬挂 anisotrop/struct_conn 引用造成数百万 warning 与系统性超时，而外部工具的科学输入是受检原子身份和 Cartesian 坐标。最小文档不改变这些值；日志窄豁免后仍由输出存在、MRC/几何 QC 与正式 release gate 提供独立硬门。
  Date/Author: 2026-07-13 / Codex（工程恢复，不改变科学数值）

- Decision: 合法 E1 canonical map 与合法 Stage C polymer receptor token 坐标（`receptor_tokens.coords`）的 XYZ 包围盒完全分离时，E/F 统一记 `known_failed:model_map_frame_mismatch`。该 token 是两阶段共用 frame anchor，不等同于 E2 严格 ATOM-only 模型或 F 完整 ATOM+HETATM 模型。两阶段共用单一函数和 `1e-5 Å` 容差，并在任何 artifact reuse/Chimera/MapQ 前短路；禁止 PDB allowlist、猜测平移、fitmap 或改写坐标。
  Rationale: 权威 source 可能没有可证实的共同 frame；生成全零 sim 或猜变换都会伪造数据。该 known failure 只接受完全分离的合法包围盒；空/NaN/错 schema、后置 all-zero/几何不一致和外部工具错误仍为 unknown。
  Date/Author: 2026-07-13 / User + Codex

- Decision: `8ckb` 以及 `2026-07-13T19:54:19+08:00` 截止时仍未完成的 Stage E 标准 Chimera 长尾，不再为单样本维护专用几何/变形算法；只在正式 run 的显式 exclusion manifest 中记录为 `known_failed:run_policy_excluded`，并从训练和推理排除。截止前已完成且通过既有 E artifact/QC 的样本继续复用，未完成子集必须逐项绑定用户授权、deadline、Job ID、运行时长和缺少完整 artifact 的证据。
  Rationale: 少量极端资源长尾不应无限阻塞 22,386-PDB 的 E→F→G 主线，但静默删除、伪造成功或改变坐标同样不可接受。run-scoped manifest、正式四终态和 release gate 同时保留全集审计与下游安全；该决策是本轮资源/运行策略，不扩大通用科学 known-failure 集合，也不成为未来自动排除许可。
  Date/Author: 2026-07-13 / User + Codex

- Decision: `6kgx` 按用户 2026-07-14 的明确授权，只在正式 run `adaligand_ag_20260711T154658` 的 Stage F 记为 `known_failed:run_policy_excluded`。它继续留在 22,386 样本宇宙和 F 状态分母，不伪造质量三件套；训练、推理和 G 候选不得消费它。共享 `exclusions.jsonl` 保持 Stage E 放行时的原字节，Stage F 通过严格加法视图 `exclusions.stage_f.jsonl` 获得这条新决策。
  Rationale: 现场证据表明外部工具已结束，长尾来自 post-MapQ Python occurrence 投影的工程复杂度，而不是新的科学失败类别。Stage F 专用视图解决既有 E status 已绑定旧 manifest SHA 的 provenance 冲突；它是本轮 artifact/审计接口，不是未来自动超时规则，也不授权把尚未取证的排队样本批量排除。
  Date/Author: 2026-07-14 / User + Codex

- Decision: 对正式 run `adaligand_ag_20260711T154658`，允许把极少数有完整现场证据的巨大活动长尾继续记为 run-only exclusion，而不让其无限阻塞 A–G。当前累计为 5 个，自治追加额度至多为 4 个，故累计必须始终严格少于 10。每次追加都必须证明：样本确实处于活动计算而非排队；本阶段要求的完整公开 artifact 尚未形成；日志、进程、运行时或资源占用能客观解释长尾。记录继续使用 `known_failed:run_policy_excluded`，保留 22,386 样本宇宙和状态分母，并排除训练、推理与 G 候选；禁止伪造 success。若下一条会使累计达到 10，或同一失败模式出现聚集/系统性趋势，必须停止逐例排除，转为根因诊断并向用户确认。
  Rationale: 少于 10 个极端样本不足以合理占用整条 A–G 关键路径，但上限和逐样本证据可以防止把系统性工程故障误包装成零散超时。这是当前正式 run 的资源与完成策略，不新增科学 known-failure 类别，不改 E/F 成功定义，也不授权未来 run 自动沿用。
  Date/Author: 2026-07-16 / User + Codex

- Decision: 本次 cutoff 只把 `exp.npz`、`sim.npz`、`ligand_area.npz` 三者都存在且通过既有 artifact 校验的样本认作完成；仅有其中一项或两项属于 partial，继续按截止时的未完成事实审计。before/after manifest 和逐样本迁移记录只服务于正式 run `adaligand_ag_20260711T154658`，不改变 Stage E 的通用成功定义或科学契约。
  Rationale: 把 partial 当作完成会让下游消费缺失或未验证的模拟图/体素标签；把这次名单写成通用规则又会把一次性资源决定误扩散到未来 run。独立 cutoff CLI 同时验证截止时间、补足 job 身份、前后终止证据、manifest 哈希和幂等重放，随后才允许 resume v3 放行正式 E。
  Date/Author: 2026-07-13 / User + Codex

- Decision: DE→F 的完成判据不能只看 `316115 COMPLETED 0:0`；必须同时通过 status/release gate、风险分层 E artifact，以及 exclusion/frame-mismatch provenance 三路独立审计，才把自动 afterok 启动的 F 视为合法阶段切换。
  Rationale: Slurm 退出码只能证明调度脚本正常退出，不能独自排除 silent missing、旧 schema 复用、run-only exclusion 丢失或 2zhc 被错误降级。三路证据互相独立，既保留自动流水线，也避免把调度成功误当科学数据通过。
  Date/Author: 2026-07-14 / Codex（遵循用户既定 release-gate 与独立审计授权）

- Decision: 用户把本轮主用 CPU 上限扩为 192，并另留 48 CPU 作为测试、审计或备用；Stage F 加速不改变正式 `316116` 的 F12×MapQ np8，而是以独立 run/job/status/gate 对冻结尾段补算。补算只写共享的 schema-aware 质量三件套，不写正式 Stage F status/release；正式流仍负责 22,386 行终态和 F release。守护进程绑定正式 Job ID、run id、stderr 设备/inode、plan/ID SHA 与资源契约，并在正式进度达到冻结阈值时 TERM→KILL 补算进程组。
  Rationale: 这能复用正式 F 的 skip-valid-artifact 语义，同时避免重启正式 DAG、MapQ 峰值过订阅和两个 writer 处理同一 PDB。当前 `Cpu96` 用户 QoS 的 `MaxTRESPU cpu=192` 表示两台 96 核同时运行时，额外 48 核不能在同一 QoS 下并发启动；它是任一 96 核释放后的备用额度，或需另行验证可用分区/QoS，不能把“192+48 授权”误写成当前可同时占用 240 核。
  Date/Author: 2026-07-15 / User + Codex

- Decision: Stage F attempt 中的 MRC/MAP/CIF（包括原子写临时文件和 MapQ 返回前输出）全部视为可重建大型中间体；成功或 Python/外部工具异常都在当前 UUID attempt 的异常安全边界内清理。小型 stdout/stderr、生成脚本、MapQ 兼容脚本和结构化 stage failure 保留；默认不保留大型 debug 文件，也不把一次性 scratch manifest 提升为科学契约。
  Rationale: 四 CC、MapQ、配体/口袋 Q 和正式三件套不依赖 scratch 大文件长期存在；日志与 run-scoped status 已提供可复现入口。精确 attempt 范围、越界 fail-closed 和兄弟 run/PDB/attempt 隔离可避免清理扩大。`SIGKILL`/节点掉电不能执行 Python `finally`，此类 stale scratch 必须先精确停 writer、冻结 before manifest，再单独回收；不得在运行中全树删除。
- Decision: 本项目所有为单次 repair、migration、cutoff、supplement、recovery、审计或资源覆盖而增加的脚手架，都必须在任务闭合前接受一次项目级依赖审阅。审阅将文件分为生产主线、可复用运维、本次 run 专用和过时/危险四类；仍被活动作业、恢复入口或迁移 gate 引用的文件先保留，依赖闭合后再以精确 Git 路径、回归测试和可追溯提交完成删除、归档或重构。最终生产路径必须在移除一次性脚手架后仍生成相同科学产物。
  Rationale: 运行中临时授权和故障恢复会持续累积辅助入口；若不在收口时反向审计，它们会与长期科学实现混杂，降低可读性并诱导后续 Agent 误用。该规则只约束维护与收口方式，不改变任何科学契约或当前运行状态。
  Date/Author: 2026-07-16 / User + Codex

- Decision: 硬中断回收的零进程门必须覆盖 `master` 和所有保留 allocation，并把同 UID 裸 Python/stdin Python 视为不透明活动进程；由 canonical 脚本生成 argv/stdout/stderr/节点/时间/实现 SHA 全闭合的 schema v2 证据。audit 与 apply 各自重新 capture，controller probe 在 scheduler 快照之后最后执行。
  Rationale: 旧 schema v1 已被真实孤儿进程反例推翻；脚本 token 无法还原 `python -` 正文。显式 `--controller_node master`、controller/allocation 分离、scan-error fail-closed 和最老 probe 15 分钟时限可防止在错误节点、自报节点或过期证据下删除。该门只改变工程回收授权，不改变质量科学契约。
  Date/Author: 2026-07-16 / Codex（基于事故取证与用户“严谨完成 A–G”授权）

- Decision: Pocket Plus 对体素中心的稳定数值行为是 E3 权威：`origin` 是网格/BOX 下角点，索引 `(x,y,z)` 的中心为 `origin_xyz+(index_xyz+0.5)*voxel_size_xyz`。E3 直接原样 vendoring `_build_voxel_center_coords_xyz`，不得以 Agent 自写的“等价/更稳健”实现替代；Ada 只可直接筛选祖传函数实际生成的 float32 中心，再执行逐元素半径、独立 occurrence mask、重叠允许和稀疏排序等已冻结科学契约。
  Rationale: 用户无法重新人工核验大幅改写的几何实现，而 Pocket Plus 已经过训练、验证和测试。直接 vendoring、来源哈希和完整网格 oracle 能把几何数值与 Ada 的标签科学差异清楚分开；合成极端输入不构成修改祖传实现的授权。
  Date/Author: 2026-07-16 / User + Codex

- Decision: `ligand_area.npz` 升为 schema v3，并成为全局“不压缩 NPZ”规则的唯一窄例外。它必须从当前 Stage C present 原子重新生成，保存下角点/半体素公式、中心 dtype、距离谓词、稀疏轴序、来源和 `storage_encoding`，以 `np.savez_compressed` 写同目录独占临时文件，重读完整验证并确认所有 ZIP 成员为 DEFLATED 后才原子覆盖原路径。旧 schema v2 即使 `overwrite=False` 也必须重建；严禁 roll/平移旧 mask，且不得改变 `atomic_save_npz()` 的全局默认。
  Rationale: 算法与存储身份必须让半体素旧产物可靠失效，同时避免 E3 的大 boolean union 继续浪费空间或把压缩行为扩散到 exp/sim/LigandObject。临时文件验证与原子替换保证失败时旧正式件、兄弟 PDB 和其他 run 不受影响。
  Date/Author: 2026-07-16 / User + Codex

- Decision: 本次 E3 全量迁移的目标集合冻结为旧正式 Stage E 的 22,309 个合格 PDB；77 个 known failure 不因本次修复复活。旧 Stage E status SHA `3a0d4148…c54c`、`de_release` SHA `ab49f43c…da6` 和 exclusion manifest SHA `380844d0…325f` 只读保留，迁移写独立 `stage_e3_repair` status/gate/账本。F/G 不消费 E3，可继续并行推进；Stage1 训练就绪则必须等待 E3 新 gate。
  Rationale: 这是既有科学产物的确定性几何修复，不是扩张样本宇宙或改写历史放行证据。独立账本可证明 22,309 个原路径被受检原子替换，同时避免把旧 release 伪造成新算法证明。
  Date/Author: 2026-07-16 / User + Codex

- Decision: 在用户作出选择前，六个 fresh ALL signal-11 样本保持 unknown，`316116/318350` 以各自精确 `after+try` 停写；无科学计算的 ALL-only v1 ImportError 不作为排除或公式结论，也不得静默裁图、换工具、改 mask/均值/精度或用 contour CC 代替 ALL。该停点决策已由下一条用户授权解除，但诊断边界继续有效。
  Rationale: v2 的 `9hhl` 控制已证明 fresh harness 可逐位复现 canonical ALL，`9fkb` 又证明故障在有效祖传路径内仍可重现。旧上限下六项会使总数达到 11，且同类聚集属于系统性趋势，因此当时必须停下请求用户，而不能由 Agent 自行个例化。
  Date/Author: 2026-07-17 / Codex

- Decision: 用户授权六个固定 ID 仅在当前正式 run 中以 `run_policy_excluded:chimera_full_grid_cc_signal11` 收口，并把该 run 的 run-only exclusion 硬上限放宽到 30；本次追加后累计 11/22,386（约 0.049138%）。
  Rationale: 六者已由单进程 6/6 fail、有效 fresh ALL 正/负控制、signal 11 与非 OOM 证据逐项闭合；继续改四 CC 或无限等待不优于把约万分之 4.9 的已取证运行失败显式排除。该决定只改变本次运行的完成策略，不新增通用 known-failure 科学类别。生产路径只能通用读取 run-scoped manifest，禁止把六个 PDB 写进代码 allowlist；manifest 必须绑定授权、证据、run id、阶段、下游策略、退出条件与最终脚手架审查。六者不得产生占位 JSON/NPZ：状态分母保留真实 known failure，而训练、推理和 G 通过公开质量三件套完整性自然排除。
  Date/Author: 2026-07-17 / User + Codex

- Decision: 依照用户已授权的当前 run exclusion cap=100 和“少数已取证外部工具边界可显式忽略”的运行策略，Phase-2 对新增八例按真实原因追加 run-only 决策：五例为 `chimera_full_grid_cc_signal11`，三例为 `chimera_molmap_timeout_3600s`；迁移后累计 19/22,386（约 0.084874%）。共享 Stage E base4 和已经 release 的补算 v1 六条逐字节不变；只原子更新正式 Stage F 视图与失败的补算 v2 视图。八例保留在状态分母，公开质量三件套继续 0/3，不进入训练、推理或 G，且未来 run 不继承这些 ID。旧 cap30 只保留为首轮迁移历史身份，不重写旧记录。
  Rationale: 五例与已经独立复现的祖传 ALL 工具边界同型，三例有精确 3,600 秒 molmap 证据；继续让正式 F 运行到对应位置只会再次失败并浪费约一天以上。分层 manifest 能保留历史 release 身份和真实失败原因，同时不修改四 CC、molmap、MapQ、Q-score 或成功产物算法。
  Date/Author: 2026-07-18 / User + Codex

- Decision: 后续 A–G 若出现不超过当前 run 用户授权上限的小批 `unknown_failed`，且已逐例证明根因闭合、影响边界有限、目标样本不再 in-flight、没有共享写入污染、科学契约不变，并能以公开产物完整性安全排除，则优先使用 **run-scoped controlled-failure waiver（受控失败放行）**，不得为“把 unknown 改成 known”而中断正在运行的 producer 或重放科学计算。raw status、原始错误与状态分母保持不变；gate 与 G 只在显式传入同一份、精确指纹绑定的 waiver overlay 时，把命中项列入独立的 `waived_controlled_failures` 并排除训练、推理和 G 候选，绝不能计为 success 或改写成原生 known。
  Rationale: 这把“本次 run 可安全继续”与“生产分类器已经永久修复”解耦。waiver 必须逐 ID 绑定 run/stage、status 文件与原始行 SHA、attempt/job/node/tool/code 身份、诊断证据、公开产物 0/N 或 validator 快照、无活动 writer 证据、用户授权、累计数量/上限、`scientific_contract_unchanged=true`、`no_placeholder_artifacts=true`、下游排除策略和退出条件；任何未列 unknown、duplicate、silent missing/extra、schema/身份/manifest 漂移、部分损坏产物、系统性增长趋势或潜在科学污染仍 fail-closed。这里的 fail-closed 只表示“Agent 不得自行放行”，绝不授权 Agent 擅自修改代码、终止 producer 或重跑；即使判断为系统性/科学风险，也要先冻结现场，向用户完整报告真实影响、证据、可接受风险、重跑成本和选项，由用户明确决定“接受瑕疵顾全大局”还是“严格阻断/修复重跑”。没有用户指令时保持现场，不把重跑当默认恢复动作。当前 cap=100 是硬上限而非可自动消费配额，每批仍须单独取证；strict smoke 不接受 waiver，A/B/C/D/G 也不得未经阶段专门证明自动套用。随后可异步“补票”：在不停止当前 producer 的前提下加入一般化、无 PDB allowlist 的原生分类/修复与测试，使未来 clean run 无 waiver 通过；补票闭合后按一次性脚手架规则退休当前 run 的适配入口，历史 manifest/summary 只作证据归档。
  Date/Author: 2026-07-18 / User + Codex

- Decision: 正式 F 当前 45 条 raw unknown 全部采用上述 waiver，并把当前 run 的累计硬上限从 100 提升到 200。45 条保持原始状态、错误和 0/3 公开质量产物；既有 19 条 `run_policy_excluded` manifest 不追加、不改写。正式 gate summary 与 Stage G analyze 必须报告同一 manifest SHA、45 条 raw unknown 与独立 waived 集合；64 只表示 cap 校验中的累计受控数量，不能冒充 64 条原生 exclusion 或成功样本。
  Rationale: 三路独立审计已经证明 45 条均有稳定终态、逐条诊断、无活动 writer、无公开 partial 或共享污染；再次运行外部科学工具只增加时间成本，不会改善已经冻结的本次运行事实。逐行 SHA、全部 status 分片、pair-list、进程门、代码身份和 required-artifact 0/3 的共同绑定可确保 waiver 只覆盖用户批准的当前现场；默认无参数路径仍严格拒绝 unknown。
  Date/Author: 2026-07-20 / User + Codex

## Outcomes & Retrospective

尚未完成。Stage C v4、ABC gate、MRC 放行及正式 D/E 已闭合；`316115` 于 2026-07-14 01:26:42 `COMPLETED 0:0`，D/E 四终态、风险分层 artifact、四条 Stage E run-only exclusion 与 2zhc frame mismatch 均已通过独立审计。Stage F scratch v4 已完成零删除 audit、4,341 条 transient 的 journal/fsync apply 和定向独立验收；10,260 条 nontransient 与 2,568 条 public trio 后验通过，`apply_summary` SHA-256 为 `4dfd0853…2f649`，v1/v3 继续永久作废。2026-07-16 19:03–19:07 依次恢复 `318350→316116`：补算以受检 run_cmd SHA-256 `ca04f4f…25f3e` 顺序执行 v1/v2，正式 F 继续以 `bd7edb94…5ffa` 运行；两台 CPU96、各 12 个外层 worker 与 MapQ `np=8` 均已实机确认，guard/child PGID 已登记，正式 `316116` 仍是唯一 22,386 行 status/release writer。全量 F 状态、五条 Stage F exclusion 终态与总体质量分布仍待完成。Stage G 单一 map-level schema v2 已实现，`316117` 仍只安排 analyze。显式阈值配置和 `keep_list` 仍不属于本轮无人值守终点。

E3 的 Pocket 祖传半体素修复及 source-aware release runner 已实现并完成服务器迁移：`75d8f42/92fc2e8/e90fccc/1780942/7202bc9/97a9c07` 依次冻结祖传中心、删除 Agent 自研候选边界、收敛 Pocket BOX、建立 22,309 目标快照与让 validator 从当前 Stage C 原子逐 mask 重建。三项独立终验、本地/远端全套、真实 Pocket oracle 和全量 header 风险审计均已闭合；严格 Z/X padding-shift 风险命中 182/22,309（约 0.816%），按用户边界只记录、不修改祖传实现或排除样本。`318882→318883` 已使 22,309 个冻结目标全部成为合法 schema v3 压缩产物，gate SHA-256 `796bc90c…be37`；canonical snapshot/intent/release SHA-256 为 `f9705efe…32d8` / `0657c85b…e25d` / `fdcef799…bb3e`，全局 writer lock 已受检释放。F/G 不消费 E3，当前继续独立推进；Stage1 训练就绪只等待 A–G gate。

旧的 run-only 规则在累计达到 10 或同类聚集前要求停下询问；它已成功阻止 Agent 自行个例化。用户随后只对当前正式 run 显式把硬上限放宽到 30，并授权六个已取证 Fresh ALL signal-11 PDB。当前应有 11/22,386 项，未来 run 不继承 30 或六个 ID；生产路径禁止 PDB allowlist。

2026-07-17 的最新 Stage F 状态覆盖上文早期“双 writer 停写”的时间点：补算 v1 已把 353 个旧 unknown 先归因为四类确定性适配误拒，再把最终六个稳定 signal-11 样本按用户授权写成真实 run-only known failure。最终 v1 为 2,990 unique、2,984 skipped + 6 known，unknown/duplicate/silent missing 均为 0；六例公开质量三件套严格保持 0/3。补算 wrapper 已进入 5,984-ID 的独立 v2，正式 `316116` 也在 v2 guard/child PGID/F12 门闭合后恢复为唯一 22,386 行 status/`f_release` writer。因此 A–G 仍未完成，但已不存在科学决策阻塞；`316117` 继续只等待正式 `f_release`。

随后完成的重跑把旧 353 unknown 收敛到六个大网格 PDB。六者在 `n_jobs=1` 仍 6/6 fail；有效 ALL-only v2 以 `9hhl` 逐位复现 canonical 的正控制排除了 harness/公式漂移，同时以 `9fkb` fresh 子进程 signal 11 复现故障。约 2 TB 节点没有 OOM 证据，继续增加 RAM/worker 不是已有证据支持的修复。用户选择只对本 run 的六者使用 `run_policy_excluded:chimera_full_grid_cc_signal11`，并把本 run 上限放宽到 30；累计 11/22,386（约 0.049138%）。本地/远端全套、三份 manifest 原子迁移、补算 v1 gate、v2 进程门和正式 F 恢复现已全部闭合；六例仍为 0/3，未生成伪装产物。G 尚未开始。

2026-07-18 的补算 v2 首轮完成全部 5,984 个目标后暴露五个同型 ALL signal-11 和三个 molmap 3,600 秒 timeout；八例均为 0/3，scratch 异常安全清理有效。Phase-2 随后完成 formal 19 条 / v2 14 条、v1/base4 冻结的两目标迁移，并以 no-overwrite 重放闭合为 5,984 unique、5,970 skipped + 14 known、零 unknown/duplicate/silent missing；status/release SHA-256 为 `8babca24…d0c` / `123bed2c…fd69`。fresh 跨节点进程审计与独立复核通过后，2026-07-18 21:53:48+08 保留 `after_lock_316116`、只删除精确 try-lock，正式 F 由原 CPU96 allocation 复用 run_cmd `0ff22ef9…e131`、F12、no-overwrite 自行恢复；readiness 与首批真实进度均已确认。当前 A–G 仍未完成，G 尚未开始；在正式 `f_release` 前不得接受 `316117`。

2026-07-20 正式 F producer 已完成全量计算，但严格 gate 因 45 条 raw unknown 停在 after+try；四终态为 16,944 skipped、5,323 success、74 known、45 unknown，且 45 条均为 0/3、无活动 writer。用户批准 cap200 与 gate/G 共用 waiver；本地实现保持 raw status、默认严格和 strict-smoke 禁用，专项 65 passed+2 skipped、全套 402 passed+10 skipped，独立代码审查 PASS。当前尚未完成服务器 manifest、远端测试、gate-only 原地 release 和 G analyze，因此不得把本段视为 A–G 最终完成；它只把“不重跑科学计算的受控放行路径”实现到了本地可验证停点。

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

D 读取 C 受体/配体坐标，生成 `binding_atom`、`instance_id`、`nearest_dist`。E 的实验图加载和 target=1 Å/actual-voxel 重采样由零差异 `code/mrc_pocket_legacy.py` 与 `code/mrc.py` 薄适配共同提供；receptor-only CIF 只在 E2 临时目录生成并删除全部 `HETATM`；Chimera 调用集中在 `code/chimera.py`，命令、版本、输入 hash、退出码和日志都进入 provenance。E3 直接复用 `code/voxel_gt_pocket_legacy.py` 的祖传体素中心，从 present 原子与逐元素 vdW 半径重新生成 schema v3 稀疏 mask，并只通过 E3 专用压缩原子 writer 覆盖原 `ligand_area.npz`。

F 用 Chimera 在 canonical grid 上生成全模型模拟密度并取得四种 CC；contour 缺失时 contour 两项为 `null`，不得猜阈值。MapQ 读取 native map 和完整模型，输出逐原子 Q；适配层用 mmCIF 原子身份与 C component/atom_name 做严格 join，再投影到 LigandObject 行序，并按 6 Å 原子包络聚合 occurrence 受体口袋 Q。G 汇总完整度、resolution、CC、配体/口袋 Q 和所有阶段状态，先输出质量分布；正式 filter 只接受 schema v2，按 PDB/map 聚合 occurrence pair pass，空口袋计入分母，通过 map 后保留其全部 occurrence。

### Milestone 4: 自动 smoke gate

本地先用合成 MRC、最小 mmCIF 和 fake Chimera/MapQ 输出覆盖纯 Python 逻辑。服务器 smoke 选少量包含单 CCD、BRANCHED、缺原子、不同 map axis/origin 的真实样本，实际调用 Chimera/MapQ。加入负对照：错配模型与 map 的 CC 应明显恶化；故意交换原子身份必须被 mapping QC 拒绝；二维/单切片或错 shape 的模拟图必须失败。smoke 全部通过后，Slurm 依赖自动释放全量任务。

### Milestone 5: 全量 DAG、监控与收口

初始正式 DAG 为 A guard，B retry 与 C upgrade 并行，各自 QC 后进入 A–C release gate；通过后进入同一作业内并发的 D+E，再依次运行 F 和 G analyze。当前 316114 的 gate-repair 路径不再重跑 B：snapshot→独立 source audit→apply→无过滤全量 C→ABC gate。长任务使用 Slurm 持久运行，heartbeat 定期只读检查队列、日志增长、失败类型和产物计数。例行代码/批脚本/QC 修复可安全同步，并优先通过精确 run_cmd/lock 原地恢复；科学契约变化、删除数据或 clean sync 不在自主修复权限内。

正式 F 运行期间如需跨节点尾部补算，必须先冻结 pair list、Stage F exclusion、正式进度区间和互不重叠的尾段 ID；补算使用独立 run/status/gate，不能写正式状态。运行期守护绑定正式日志身份并按冻结阈值轮询；碰撞前主动停止补算进程组，已经原子完成且通过既有 validator 的公共质量三件套由正式 F 自然 skip。第二个作业不改变正式 Job ID、afterok 链、F12×MapQ np8 或科学契约。

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

E3 schema v3 验收还必须满足：Pocket `_build_voxel_center_coords_xyz` 的 vendored 源码/AST 与祖先零差异；非零 origin、各向异性 voxel、边界原子和能击败旧 `origin+index*voxel` 的反例均按 `+0.5` 中心通过；mask 唯一/字典序/范围、union 与世界质心逐项闭合。旧 v2 必重建、合法 v3 幂等 skip；临时压缩文件经 `allow_pickle=False` 重读后 dtype/shape/值不变，全部成员确为 `ZIP_DEFLATED`；任一写入/validator/替换异常保持旧正式文件逐字节不变且不触碰兄弟 PDB/exp/sim。专用迁移入口不得导入 Chimera/MapQ，分片不能重复写同一 PDB。真实放行必须用多张当前密度图分别运行 Pocket 祖传中心/标签 oracle 与 Ada E3；任何中心几何差异阻断，因统一半径/严格小于/first-writer-wins 与 Ada 逐元素半径/独立重叠 mask 造成的标签科学差异则必须逐条报告，不能隐藏为兼容。

F 验收必须满足：四个 CC 非空值均有限且在 `[-1,1]`；contour 缺失时只允许两个 contour 值为 null；错配负对照不优于正确配对；`qscore_{cid}.shape == (M,)` 且与 LigandObject 行序严格一致；`present=False` 位置为 NaN；`n_valid` 与成功 join 数一致。每个 occurrence 还必须有数值升序的 `pocket_atom_site_id_{cid} (K,) int64` 与同序 `pocket_qscore_{cid} (K,) float32`；`K>0` 时全部原子精确满足 6 Å 包络，`K=0` 时两个数组均为空、聚合 null、状态显式且 occurrence 仍保留；不存在按输出/残基遍历顺序或坐标最近邻猜测映射。

Stage F 尾部补算验收还必须满足：planner 对 plan/ID 文件、正式 run/job/log inode、pair list、exclusion 和 F12×MapQ np8 资源契约做交叉哈希；守护在子进程启动前安装 signal handler，正常阈值、TERM、异常和真实 kill-lock 路径都能回收整个补算子进程组并落盘完整 stop evidence；补算 status/gate 与正式 run 隔离。本轮实现的 Windows 全套为 224 passed、2 个 POSIX-only skipped，服务器 Linux 为 226 passed，所有 shell/sbatch 均通过 `bash -n`。

Stage F scratch 生命周期验收还必须满足：成功以及 canonical MRC、molmap、correlation、native 解压、MapQ、geometry/quality/provenance QC 和三种正式 writer 异常后，当前 attempt 递归不存在 MRC/MAP/CIF；必要日志/脚本仍存在，已有合法三件套的 skip 不创建 attempt；兄弟 PDB/attempt/run 与并发 worker 不受影响。清理自身失败要写小型 `cleanup_errors.json`、保留原始异常 cause 并阻断 release。当前专项 16 项、Windows 全套 240 passed+2 POSIX-only skipped、服务器 Linux 全套 242 passed；科学数值主体经 whitespace-insensitive diff 独立审查为零变化。

硬中断 stale 回收还必须满足：原子 inventory 完成且 SHA 闭合；15 分钟内的 scheduler、master 与双 allocation probe 正文证明零 F/Chimera/MapQ/Loky、零旧 inventory/cleanup、零 blocking opaque stdin Python、零 scan error；probe argv/stdout/stderr、node/scope/job、最早时间和 canonical implementation SHA 全部闭合。用户授权的非任务扫描只能作为 controller 上最多一个精确 `node+PID+PPID+start_ticks+argv SHA` 例外，raw 行不能消失，第二个 opaque 或任何字段漂移均阻断；start_ticks 只在当前启动周期内有效，而保留 Slurm allocation/scheduler 门使服务器重启同样 fail-closed。audit 零删除并冻结 delete/nontransient/public-trio manifest 与完整 bundle；apply 使用另一份新鲜 process-audit，且例外指纹必须与 audit 相同，逐文件先 fsync intent、立即复核锁与 lstat 后只 unlink manifest 路径，再 fsync deleted。最后无换行的 journal 尾部先固化原始 bytes/hash 后才允许受检截断，中间坏行、run/stage symlink、bundle 漂移、新增 transient 或小日志/正式三件套变化均阻断。回收实现提交 `39e5185`，跨节点进程门基线提交 `d53d190`；schema v3 本地专项 43 passed+2 skipped、全套 284 passed+4 skipped。

本轮 G analyze 验收必须满足：每个 A 样本在每个适用阶段恰好处于 success/skipped/known_failed 之一；任何静默缺失或 unknown failure 都阻塞；`quality_distribution.json` 与 `candidates.pending.jsonl` 保存完整候选、四 CC/配体 Q/口袋 Q/分辨率分布和输入 manifest hash，且不写 `keep_list`。后续显式 schema v2 filter 还必须证明：同 PDB selected CC/resolution 唯一一致；Q 等于阈值时 pair 失败，CC/resolution/fraction 等于边界时 map 可通过；空口袋失败且计入分母；通过 map 的全部 occurrence 进入稳定排序的 `keep_list`。`map_filter_diagnostics.jsonl`、summary、配置 hash 和输入 manifest 必须闭合。

## Idempotence and Recovery

所有 stage 都默认 skip-valid-artifact，而非 skip-existing-path。临时写入采用同目录临时文件，校验成功后原子 rename；`kill -9` 最多留下可识别临时文件，不能留下被完成判据接受的半文件。失败报告按 run id 隔离，当前状态以产物验证和本轮报告为准，不累加历史 append 文件。

Stage B 逐文件恢复，不覆盖已验证下载；但当前 316114 repair 明确跳过 B，以免改变冻结 source。普通 C 每个组件单独恢复；若受体重建与旧行序不一致，不覆盖旧文件，记录 contract failure。source apply 可能在中断前已有部分 receptor 完成原子替换，恢复时必须重新执行完整 audit→apply，使已修复项在新 audit 中变为 exact；不得单独重放旧 apply records。E/F 外部工具使用 per-PDB 临时目录，成功后只提升最终产物；F 成功和可捕获异常都删除当前 attempt 的大型 MRC/MAP/CIF，只保留小日志和 provenance。不可捕获的硬杀/节点故障必须在 writer 停止后用 run-scoped before/apply/after 证据回收 stale scratch。G 是纯派生阶段，可在不重算 A–F 的情况下用新配置重跑。

受控失败放行不改变上述默认行为：没有显式 waiver 参数时，现有 loader/gate/G 仍对所有 unknown fail-closed。需要开路时，先等待对应样本形成稳定 raw 终态并冻结 status/row/process/artifact 身份，再原子发布 current-run-only waiver；gate 与 G 必须消费同一受检有效状态视图，并同时报告 raw unknown、waived、未豁免 unknown、effective eligible 和 waiver SHA。waiver 只控制下游排除，不修改 raw status 或公开产物；任何匹配缺失、多匹配、SHA/run/stage/cap 漂移立即失败。补票可并行开发和测试，但不得修改运行中 producer；默认入口在补票前后都必须保持无 waiver 时的严格语义。

只允许删除本轮作业对应且已验收完成的 `after_lock`；`kill_lock` 只针对本轮可精确归属且卡死/错误的作业。不得 clean sync，不得删除正式数据根，不得修改服务器公共配置。

## Artifacts and Notes

初始服务器证据：

    A: pair_list=22,386 PDB
    B: mmCIF=22,386, meta=22,386, unique EMDB=22,274, maps=22,098, missing=176
    C old contract: parse dirs=22,386, ligand_objects=3,833
    C new contract: centroid_atom/bond_index/bond_type/feat/ligand_descriptors 均未实现

资源边界：本轮主用 CPU 上限为 192，另有 48 CPU 只作测试、只读审计或备用；`cpu96` 用户 QoS 的实时只读证据为 `MaxTRESPU cpu=192`，因此两台 96 核并发时这 48 核不能在同一 QoS 下同时启动。CPU 分区由 4 台 96 核节点组成且不 oversubscribe；96 核整节点作业只有在单节点完全空闲时才能立即运行，空闲整节点存在时优先单作业占满，若整节点槽位丢失再按既有 16 核 array/已授权备用分区策略评估。A100 最多两张，每张配 16 CPU，仅作 CPU 分区不足时的 CPU-only 备用。Stage B 固定单节点单进程。

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

2026-07-13 Stage E 长尾截止证据：绝对截止为 `2026-07-13T19:54:19+08:00`。补足 job `316415` 最终状态为 `FAILED 9:0`，elapsed `06:04:02`，EndTime `2026-07-13T20:09:28+08:00`；这是精确 cutoff 后让独立补足 allocation 退出的预期证据。截止前完成并保留 `8j07/9dp7/9qwt`，新增 run-only exclusion `8glv/9e5c/9fqr`，与既有 `8ckb` 组成最终 manifest。predecision、posttermination、before manifest、after manifest、summary SHA-256 依次为 `40e7c949df528b81e1c4a8ee8bbd60daec5ec4d06089037e64958f08fd5458a8`、`0f20f20cae3b9958cfe3fd3085233782b2e2e5533144cec704fa22dec2d97397`、`b586cab20644c3cc8fb1f4e0eaa7eead4cff0d496a862c2313b5e0c1847257fe`、`380844d0b908b08707fada689f64b2fa4cc519f4771df92dec8b5bf0b2cd325f`、`f4a26a9359519e4b94b9f28ecdb21645929c018a014729feadb44b29eadf4761`。终止主进程组后另核对并清理 PID `160147/160179/160191`；三者分别对应 `9e5c/9fqr/8glv`，独立进程审计为零后才完成锁收尾。

2026-07-13 cutoff/v3 放行证据：`code/long_tail_cutoff.py` 与 `scripts/stage_e_long_tail_cutoff.py` SHA-256 为 `509672275f61e84a22b5e56c4842a3904769736dddeafe98802f9d19f7197b54` / `bb600c7bf5632af2fc575cd6f1f992a38210aaecbdc55ca568dd1895d26c490e`；本地和远端全套均为 207 tests passed。resume v3 SHA-256 为 `eabfad6bd33b7ae3bfca619000cf120f9585796a8dc7fc497e8f2328f7009626`，cutoff release marker SHA-256 为 `cd06ec335ab109f25a9da9660a0ce943888c72546a11dbb3852d4ff897764cfa`。`VALIDATE_ONLY=1` 最终输出 `decision=run`；正式 run_cmd SHA-256 `6e8c88a18472c07c76d6c9caf64472548d39db65ea3aef26d6540024e8e3d828` 于 21:04:43 启动 E24、无 filter、无 `--overwrite` 的正式全量 E。启动后 `after_lock_316115` 存在、`try/kill_lock_316115` 不存在，`316116/316117` 仍按原 afterok 链等待。

2026-07-14 DE→F 转换证据：`316115` EndTime 为 `2026-07-14T01:26:42+08:00`、终态 `COMPLETED 0:0`；D 为 22,339 success + 3 skipped + 44 known，E 为 22,309 skipped-valid + 77 known，且 unknown/duplicate/silent missing 全为 0。E status SHA-256 `3a0d4148…c54c`，`de_release` success SHA-256 `ab49f43c…da6`。风险分层 E artifact 审计、四条 exclusion/2zhc provenance 审计均通过。`316116` 同刻启动并记录 `reusing preloaded file`，run_cmd SHA-256 `8399d571…d13`、`F_N_JOBS=12`；04:05 快照为 944 tasks、874 份完整质量三件套抽查通过，`after_lock_316116` 存在、`try/kill` 不存在，`316117` 继续依赖等待。

2026-07-14 Stage F 长尾截止证据：`316116` 首轮日志在 635.4 分钟到达 22,363/22,386，现场 py-spy 将唯一活动 worker 绑定到 `6kgx` 的 `quality.project_occurrence_qscores/_row_matches_component`；该样本有 1,588 个 occurrence、1,011,574 个规范化模型原子，外部工具 scratch 已完整但公开质量三件套均不存在。六份原始调度/日志/进程/artifact 证据位于 `/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_ag_20260711T154658/stage_f_long_tail_cutoff_20260714T2213/` 并绑定固定 SHA。共享 before manifest SHA-256 `380844d0…325f` 保持不变；Stage F after/view SHA-256 为 `3b10abb5…8ee8`，summary SHA-256 为 `8b687f1a…53a3`。本地与远端全套均为 214 tests passed；resume、release marker、run_cmd SHA-256 分别为 `e6b357b2…9748`、`f59b09c8…5bc3`、`bd7edb94…5ffa`。apply 后 `VALIDATE_ONLY=1` 的前后全量哈希完全一致；22:46:44 删除精确 try-lock 后，core 记录该 run_cmd SHA 并以原 run id/F12/无 overwrite 重启，`after_lock_316116` 保留，G 仍依赖等待。

2026-07-15 Stage F CPU192 尾部补算证据：正式日志在规划时已完成 6,248 个任务；冻结正式 pair list SHA-256 `6c736180…35f8`、Stage F exclusion SHA-256 `3b10abb5…8ee8`，从索引 `[19386,22386)` 选出 2,990 个 eligible PDB，剔除 2 条 exclusion 与 8 条 Stage E ineligible。证据目录为 `/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_ag_20260711T154658/stage_f_tail_supplement_20260715_v1/`；plan/ID SHA-256 为 `1d5c12172629bcba2af65a379c2c78d9bf7141fdcdd505e699add8b58b1dff4f` / `acacde79c2a5a8727949cdc0a986930aa8404419a8edaabfb264f4f05dacea80`，碰撞门为正式完成 17,386。Git `7bdf1e1/60a1d53/5d2342e/6a3b3b0/bd579c3` 依次冻结补算入口、绑定与清理、真实 kill-lock 子进程组回收、守护证据等待和 signal-handler race 修复；本地 224 passed+2 POSIX skipped、服务器 226 passed及 `bash -n` 通过。job `318350` 于 16:23:59 零等待在 `cnode01` 启动，正式 `316116` 保持 `cnode04`；两者各 96 CPU、F12×MapQ np8，总计恰 192 CPU。补算 `after_lock`/child PGID 存在、try/kill 不存在，日志已进入 `Parallel(n_jobs=12)`；G 仍只依赖正式 F。

2026-07-16 Stage E3 本地修复证据：核心 checkpoint `75d8f42 fix(stage-e3): align ligand masks with Pocket voxel centers` 保持 MRC 六函数零差异，新增原样 vendored `voxel_gt_pocket_legacy.py`、机器来源 manifest、schema v3 几何/压缩字段、E3 专用 `atomic_save_npz_compressed()` 与完整回归；信任边界和 durable memory checkpoint 为 `92fc2e8 docs(memory): freeze Pocket-first E3 implementation rule`。该基线本地隔离全套为 309 passed、10 个 Windows 条件项 skipped，`compileall`、JSON/source diff 检查通过。随后 `e90fccc` 删除解析 bbox、`searchsorted` 和索引反推，只直接筛选祖传函数实际生成的 float32 中心；300/300 组随机各向异性、非零/极大 origin 的完整 Pocket 网格 oracle 零差异。`1780942` 将生产 E/F frame preflight 窄修为 Pocket 物理 BOX `[origin, origin+shape*voxel]`，专项 9 passed且数值内核不变。该段曾是“本地证据不等于服务器放行”的安全停点；2026-07-17 的 22,309-ID 全量迁移、source-aware gate 和 canonical writer release 已按上文哈希闭合，因此现在可以声明服务器 E3 产物已修复。

## Interfaces and Dependencies

公共 CLI 必须保留 `--root`、`--part_id`、`--total_parts`、`--n_jobs` 与显式 overwrite/repair 语义。stage 函数返回结构化状态，不用跨模块散落自由文本错误。稳定失败枚举、artifact validators、Chimera runner、MRC geometry 和 quality schema 必须各有单一实现位置。

Python 依赖包括 `numpy`、`scipy`、`gemmi`、`rdkit`、`requests`、`joblib`、`mrcfile`；配体解析继续使用现有 CCD/RDKit 路径。外部依赖是官方 UCSF Chimera 1.19 headless/OSMesa 与 MapQ。AdaLigand 只负责选择、输入构造、调度、严格映射和 QC；CC、molmap 与 Q-score 数值算法调用 Chimera/MapQ，不自研替代实现。E3 体素中心同样不自研：只调用 `voxel_gt_pocket_legacy._build_voxel_center_coords_xyz`，机器来源与哈希由 `voxel_gt_pocket_legacy.source.json` 冻结。

四种 CC 的代码与 README 必须解释：是否使用 contour mask，以及是否先在 mask 内减各自均值；同时保存工具版本、map/model 标识、canonical grid 元数据和 contour provenance。Q-score per-atom 文件必须说明配体 NaN/行序语义，以及口袋的 6 Å 原子包络、受体范围、atom_site.id 排序和 count 语义。

## Plan Drift / Reconciliation

### Beneficial drift

- E2 改为仅在 receptor-only simulated map 中严格删除全部 `HETATM`，与 cryoatom2 受体表达能力对齐。
- E2 改为直接在 E1 target=1 Å/actual-voxel canonical grid 上 `molmap onGrid`，并增加严格三维、shape/origin/actual-voxel/内容 QC。
- MRC 数值核心从未经项目验证的 Ada 独立实现收敛为 Pocket Plus 六函数零差异祖传快照；所有兼容仅留在可枚举薄 wrapper，旧 E schema v1 明确失效。
- F 增加四种全局 CC 和逐原子 Q-score 原始量，使后续过滤可审计、可重算。
- F 增加同一次 MapQ 上的 occurrence 受体口袋逐原子 Q/聚合，不增加外部工具运行次数。
- F 的外部工具适配器改为核验 MapQ/Chimera 的确定性实际写出语义：三位小数坐标、per-occurrence id 唯一、窄化的 ReadMol/WriteMol 身份规范化和 solid contour 的 API 设置均有源码、回归与真实 shadow smoke；四 CC、Q-score 和 occurrence 身份科学量不变。
- 失败处理从历史 append 文件升级为 run-scoped 状态与 release gate，消除陈旧失败误报。
- 受体键枚举向后兼容追加 `triple=6`；source-dirty C 增加全集 cache-only audit、完整输入/依赖哈希、CCD atom-name 覆盖和受检 receptor-only 迁移。
- filtered Stage C 增加正式 run 证据覆盖防护，避免子集状态替换 22,386 行全量状态。
- E/F 增加单一确定性 model-map 包围盒前置门与稳定 `model_map_frame_mismatch` known failure，不再用全零模拟图或猜测坐标变换表达 source frame 缺口。
- Stage G 从尚未正式使用的 occurrence 级 v1 收敛为唯一 map-level schema v2；直接复用 F 原始量，以 occurrence 合格比例评价 map，同时避免在通过 map 内二次删除 occurrence。
- E3 从旧 schema v2 的下角点误用收敛为 Pocket 祖传半体素中心、schema v3 和 E3 专用压缩原子覆盖；原子、半径、occurrence、重叠和稀疏排序科学语义不变，MRC 六函数完全未动。

### Neutral drift

- A–C 从“阶段文件存在即跳过”改为组件级 schema-aware 增量迁移；目标样本宇宙和旧基础数组语义不变。
- 运行资源和分片数由真实基准与服务限流决定，不固化旧 4/6 分片模板。
- Stage E 长尾在本次 run 的明确截止点转为 run-scoped exclusion；完整样本继续复用，partial 样本保留失败与迁移证据。这只改变一次性运行策略，不改变通用 Stage E 成功条件、样本宇宙或科学阈值。
- Stage F 在正式 F12 作业之外增加受检的独立 CPU96 尾段补算；它只改变本轮关键路径和资源调度，不改变 F 算法、schema、正式状态 writer、release gate 或 G 候选语义。
- 对少量已闭合的可控 unknown，后续允许使用 current-run-only 的 gate/G waiver overlay 先完成本次运行，再异步补齐未来 clean run 的原生分类。该运行例外保留 raw unknown、分母与缺失产物事实，不改变 clean scientific spec；没有显式 overlay 时所有 gate 继续严格阻断。
- 正式 F 的 45 条已闭合 raw unknown 按用户授权成为上述运行例外的首个实例；cap 从历史 100 提升为当前 200。该变化只影响当前 run 的 gate/G 运维视图，不改 `数据处理_v2.md` 的科学成功条件，也不把 45 条写成新的原生 failure taxonomy。

### Harmful drift

- clean spec 曾仍写“E2 保留共价 HETATM、缺分辨率猜默认、sim 二次重采样、legacy 失败不阻塞”，与已经确认并实现的契约相冲突；本次已在用户要求“更新全套日志、计划书、README”后回填为当前规格。
- mmCIF 刷新数最初由不完整 B success 状态低估为 400；文件系统证据修正为 2,156。旧 `known_failed` 丢失逐资源 provenance 的实现缺口已修复，事故细节保留在本 ExecPlan，不把数量写成通用科学规格。
- 契约 README 曾把“EMDB map 与 mmCIF 沉积坐标天然同框”写成无条件事实；2zhc 真实证据否定该假设。现已改为成功样本契约 + 对所有样本执行受检前置检查。

### Unfinished scope

- C source repair、全量 C、ABC gate 与正式 D/E 已完成；D–G 代码已实现。DE→F 的 status/gate、E artifact 风险分层和 exclusion/frame-mismatch 三路审计均通过。Stage F scratch v4、adapter recovery、补算 v1/v2 和 19 条原生 run-only exclusion 均已闭合；旧 v1/base4 与历史授权证据保持不变。正式 `316116` 已完成 22,386 行科学计算并形成 16,944 skipped、5,323 success、74 known、45 raw unknown；严格 gate 按设计停在 after+try。未完成范围是：安全同步 waiver 实现、冻结 45 条逐行 manifest 与 fresh process audit、远端全套、gate-only `f_release`、G analyze、22,386/F/G 最终独立 QC，以及 run-specific 脚手架审查。19 条原生 exclusion 与 45 条 waiver 必须分开报告，均不得被改写成 success。
- G 的 map-level 算法、比较边界、空口袋分母和整 map 保留规则已冻结；最终分辨率、选定 CC、配体 Q、口袋 Q 与比例数值仍须先看正式分布后以 schema v2 配置显式给出。当前示例不写入默认值，正式 filter/`keep_list` 尚未执行。
- E3 代码、独立 runner、source-aware validator、本地/远端全套、多图 Pocket oracle、22,309-ID 全量迁移、独立 gate 与 canonical writer release 均已通过；77 个旧 known failure 未复活，旧 E status/de_release/exclusion/pair-list 始终只读。独立 48 CPU header 审计中的 182/22,309 个小范围风险候选继续只作证据，不修改祖传实现或排除样本。E3 已无未完成生产范围；未使用的 `mrc.py::grid_world_bounds` 仍是 P2 维护项，最终一次性脚手架收口时一并分类。

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

Revision note 2026-07-13 11:42+08:00: 用户明确取消 Stage G v1 兼容，冻结唯一 map-level schema v2。实现严格 occurrence Q pair、空口袋分母、map 级 CC/resolution/fraction 门、通过 map 全 occurrence 保留与 run-scoped map diagnostics；本地 182 tests 通过。保持 316117 analyze-only，具体示例阈值未成为生产配置或服务器命令。

Revision note 2026-07-13 21:04+08:00: 回填 Stage E 长尾绝对截止的实际执行结果、316415 预期失败终态、三个孤儿 Chimera 进程和 partial 三件套边界；冻结 before/after/summary 证据及最终四项 run-only exclusion。记录 cutoff/resume v3 本地与远端 207 tests、release marker、`VALIDATE_ONLY decision=run` 和正式 E24 无过滤启动。该回填只更新执行日志、契约 README、服务器操作说明和 mapping，不把具体样本或截止名单写入 `数据处理_v2.md` 的通用科学契约。

Revision note 2026-07-14 04:05+08:00: 回填 `316115 COMPLETED 0:0`、D/E 最终四终态、E status 与 `de_release` 哈希，以及 status/gate、风险分层 artifact、exclusion/frame-mismatch 三路独立审计。记录 `316116` 复用预置 F12 命令、早期 944 tasks/874 份完整质量三件套抽查和当前锁；仅更新执行日志、契约/服务器 README 与 mapping，未改 clean spec，且不把 F 早期抽查冒充全量验收。

Revision note 2026-07-14 22:46+08:00: 回填 `6kgx` 的 Stage F post-MapQ occurrence 投影工程长尾、用户明确超时授权、精确 kill→try→受检 retry 状态机和六份冻结证据。记录 Stage E shared manifest 不变、Stage F 加法视图、214 项本地/远端回归、release/run_cmd 哈希和只读重放零漂移；不把单次运行决策改写进 clean spec，也不把尚未完成的 F/G 冒充验收完成。

Revision note 2026-07-15 16:29+08:00: 记录用户把主用 CPU 扩为 192、48 CPU 保持测试/备用的资源边界；回填 CPU96 节点/QoS 事实、正式 F 实际利用率、尾部 3,000 关键路径核算、独立补算实现与五轮审查修复、本地/远端全套测试、plan/ID 哈希及 job `318350` 零排队启动证据。正式 `316116`、其锁和 `316117` afterok 均未改动；A–G 尚未完成。

Revision note 2026-07-16 13:22+08:00: 回填 Stage F scratch 生命周期事故、安全停写、v1/v3 证据边界、跨节点 schema v2 进程门和唯一有效 v4 inventory 的闭合证据。v4 共有 139,940 条文件行和 11,445 个 attempt，清单哈希复核通过；由于不归属 PID `54412` 仍存活，尚未运行 audit/apply 或解除任何 try-lock。该回填只更新执行现实和工程恢复路径，不改变 clean spec 或 F/G 科学契约。

Revision note 2026-07-16 13:30+08:00: 记录用户为避免非科学证据加固继续阻塞主线，放宽普通 nontransient 大文件的逐字节哈希要求；公开质量三件套仍完整哈希，其他保留证据以元数据和已有/必要哈希证明实质内容未变。未修改 clean spec、F 计算或 G 分析契约。

Revision note 2026-07-16 13:32+08:00: 记录用户明确决定不归属容量扫描 PID `54412` 不应阻塞 A–G。schema v3 仅以一次性精确进程指纹从 blocking 计数扣除该 raw 行，不信号该进程，也不放宽任何其他 opaque/F/recovery/scan-error 门；audit/apply 必须复用同一指纹。该变更只影响本轮 scratch 工程门，不修改科学契约。

Revision note 2026-07-16 17:20+08:00: 用户把“临时脚手架最终收口”提升为整个项目的维护规则，并要求追溯审阅此前已经加入代码库的同类文件。已启动全项目只读盘点；在 `316116/318350` scratch 恢复和 E3 迁移仍依赖相应入口期间不提前删除，最终按依赖和风险分类完成测试后收口。该新增项不改变 A–G 或 E3 科学契约。
Revision note 2026-07-16 18:05+08:00: 回填用户冻结的 E3 半体素修复契约与本地实现证据。`75d8f42/92fc2e8` 建立直接调用 Pocket vendored 体素中心、schema v3、原子坐标重建及仅限 `ligand_area.npz` 的压缩原子覆盖，基线全套为 309 passed、10 skipped；`e90fccc` 随后彻底删除解析 bbox/`searchsorted`/索引反推并取得 300/300 Pocket 完整网格 oracle 零差异，`1780942` 将 E/F frame preflight 窄修为 Pocket 物理 BOX且专项 9 passed。正式迁移集合冻结为旧 Stage E 合格的 22,309 个 PDB，77 个旧 known failure 不复活，旧 E status、`de_release` 与 exclusion 证据只读保留；E3 修复支线不阻断正在推进的 F/G。尚待最新 HEAD 本地全套、远端 Linux 全套、真实多图 Pocket 端到端 oracle与22,309-ID 独立迁移/release gate；在这些证据闭合前不得把本地实现冒充服务器迁移完成。未使用的 `mrc.py::grid_world_bounds` 只作为 P2 维护项跟踪。

Revision note 2026-07-16 19:07+08:00: scratch v4 journaled apply 与独立验收闭合后，先受检发布 `318350` 的 v1→v2 run_cmd（SHA-256 `ca04f4f…25f3e`），确认 guard、child PGID、12 个 Loky worker 和 MapQ `np=8` 后，再删除精确 `try_lock_316116`。正式 `316116` 随后复用 `bd7edb94…5ffa` 恢复 12 个 worker；两台 CPU96 总计 192 CPU，`316117` 仍等待正式 F。v2 冻结 5,984 个 eligible ID，plan/ID SHA-256 为 `116084c3…64fc` / `7f427993…7c6c`，正式初始间隔 7,565、stop=14,386、guard=2,000；该变更只优化本轮吞吐，不改变 F 科学契约或正式 writer。

Revision note 2026-07-16 19:10+08:00: 三个独立审计分别核验 E3 上下游轴序、Pocket 中心 oracle 与 v2→v3 真实产物差异；几何/内容均通过，source-aware validator 的 P1 缺口由 `97a9c07` 修复。审计还发现祖传 `make_model_grid` 的 `shift_zyx`/`origin_xyz` 轴序风险，严格条件为 Z/X padding shift 不同，当前严格证据下界为 `7nll` 一例。遵照用户边界，祖传与生产逻辑均未改；先用独立 48 CPU 输出全量受影响 EMD/PDB、SHA 和正式 E 状态 join，再由用户决定是否接受、run-only 排除或批准窄兼容。

Revision note 2026-07-16 19:48+08:00: 独立 48 CPU origin 风险量化以 run `adaligand_e3_origin_shift_audit_20260716T192000` 闭合。22,274 个唯一 EMDB 中 22,269 个 header 可读；5 个失败全部是既有 `missing_map`，正式 E 合格集合 header coverage 完整。严格风险谓词命中 181 个 EMDB、185 个 PDB、182/22,309 个正式 E 合格 PDB（约 0.816%）；summary SHA-256 为 `7450b95a…410c`，eligible-ID 清单 SHA-256 为 `707c7c40…cb6`。三项独立审计因此形成同一结论：上下游没有新增 Ada 轴序补偿，祖传方法存在可枚举的小范围风险机制，v2→v3 产物差异则与冻结的半体素修复相符。按用户“只有明显广泛硬伤才请求批准修改”的边界，祖传函数和生产适配均不改，182 个候选不排除、不伪造成功，只作为迁移/release 的附属风险证据；E3 按祖传语义继续全量迁移。

Revision note 2026-07-17 03:02+08:00: 回填补算 v1 的 353 个 unknown 四类归因、commit `751c8b5`、远端 369 tests、8 样本 shadow smoke/replay、`9jcs` 四 CC 零漂移及 7 样本 promotion 证据。兼容只覆盖固定 MapQ/Chimera 写出语义，不引入 PDB allowlist、任意容差或科学量变化。两个 writer 仍各自保持 `after+try`；冻结 `318350 v1→v2→316116` 的顺序放行门，不把 promotion 冒充正式 F/G 已完成。

Revision note 2026-07-17 03:07+08:00: 03:02 的“双 try-lock”只作为放行前冻结证据保留。全部代码、真实产物和进程门闭合后，受检 release script（SHA-256 `784adf6e…1187`）只删除 `try_lock_318350`；补算随即在原 allocation 复用 `ca04f4f…25f3e` 进入 v1 重跑，guard、child PGID `113024`、F12 与外部工具进程均通过只读核验。正式 `316116` 继续 `after+try` 停写，待 v1 gate 和 v2 guard/PGID/F12 闭合后再放行。

Revision note 2026-07-17 05:30+08:00: E3 array/gate 共 49 个授权作业全部完成，48 份状态恰覆盖 22,309 个唯一目标且全部 success；source-aware gate SHA-256 为 `796bc90c…be37`。canonical launch control 生成 squeue 终态快照 `f9705efe…32d8` 后，发布 intent/release `0657c85b…e25d` / `fdcef799…bb3e` 并精确释放全局 writer lock。独立事后审计确认 gate、target、repair status 和所有旧 Stage E 证据哈希不变，锁根仍存在且只移除目标锁；E3 全量修复正式闭合。

Revision note 2026-07-17 Fresh ALL 隔离诊断: 补算 v1 已由 353 个适配 unknown 收敛为六个固定大网格 unknown；单进程 6/6 fail，首版 ALL-only harness 因 ImportError 作废，修正后的 v2 由 `9hhl` 两个 ALL 值逐位复现 canonical 并由 `9fkb` signal 11 复现真实故障。约 2 TB 节点没有 OOM 证据；两个 F writer 均保持 `after+try`，未改四 CC、未追加 exclusion、未释放 G。该修订记录新的系统性阻塞和待用户选择，不修改 clean spec。

Revision note 2026-07-17 六项 run-only 授权: 用户选择不修改祖传 ALL 或四 CC，而只对当前 run 的六个已取证 signal-11 PDB 写 `run_policy_excluded:chimera_full_grid_cc_signal11`，并把本 run 排除硬上限从 9 放宽到 30。累计 11/22,386（约 0.049138%）；生产代码禁止 PDB allowlist，manifest 必须绑定本 run、退出条件和最终一次性脚手架审查。本地工程检查点 `879f2be` 已通过专项 12 项与相关 42 项测试（另 2 项 Linux-only skipped）；远端 Linux 全套、manifest 实例和锁恢复仍待受检闭合。

Revision note 2026-07-17 12:59+08:00: 六项授权实现经追加工程修复与最终独立复核闭合，本地全套 377 passed+10 skipped、远端 Linux 全套 387 passed。新鲜跨节点 process audit 通过后，正式 Stage F 视图原子迁移为 11 条、补算 v1/v2 各自迁移为六条；正式共享 4 条历史 manifest 和六例 0/3 质量产物均不变。随后只恢复 `318350` 重跑 v1，正式 `316116` 继续停写，等待 v1 gate 与 v2 guard/PGID 门；该修订只更新运行现实，不改变四 CC 或 clean spec。

Revision note 2026-07-17 14:16+08:00: 补算 v1 以 status/release SHA-256 `04d6474e…39a7` / `9a445fa4…9426` 通过 2,990 行 gate，六例为真实 known failure 且公开质量三件套保持 0/3；补算未触碰正式 status/`f_release`。wrapper 自动进入独立 v2，5,984-ID/plan SHA-256 为 `7f427993…17c6c` / `116084c3…64fc`。两次 validate-only/正式 release 绑定 v1/v2、进程树、六例 0/3 和锁 inode，正式证据 SHA-256 为 `b7d70433…5477`；随后原子发布正式 run_cmd `6c1f89a5…c00d` 并只删除精确 `try_lock_316116`。正式 F 与补算 v2 现各用 CPU96/F12 继续运行；14:26–14:32 的独立只读双快照分别为正式 457→661 outer tasks、v2 104→121/5,984，且现场 v2 MapQ 命令均显式 `sigma=0.4,np=8`。本次记录强调 known failure 不生成占位产物，训练、推理和 G 按完整性自然排除。

Revision note 2026-07-18 16:33+08:00: 补算 v2 以 5,984 unique 完成计算，但 status SHA-256 `3231dfe5…23e` 含五个 full-grid ALL signal-11 与三个 molmap 3,600 秒 timeout，因而没有 `f_supplement_release`。八例均为 0/3，且无大 scratch 残留。独立碰撞审计确认正式 F 尚未触达它们后，只对 `316116` 使用精确 kill-lock；core 自行转为 try-lock。当前 `316116/318350` 都为 `after+try`、双节点零 writer，`316117` 仍等待依赖。Phase-2 采用 formal/v2 两目标原子迁移，补算 v1 与 Stage E base4 永久冻结；完成代码、测试、远端 gate 和证据前不恢复任何 writer。

Revision note 2026-07-18 17:00+08:00: 用户把当前 run 的 exclusion cap 从 30 提升到 100。旧 30 不回写，继续标识首轮六例迁移的历史授权；Phase-2 contract 使用 100，并仍要求逐例绑定真实 status/raw-line/attempt/log/0-of-3 证据。该变化不授权自动消费剩余配额，不改变任何科学算法或未来 run。

Revision note 2026-07-18 controlled-failure waiver: 用户冻结“少量、根因闭合、影响可控的 unknown 不应为状态改名而中断 producer 或重放科学计算”的运行纪律。后续采用 current-run-only、逐 ID/逐 raw-row SHA 绑定的 gate/G 共同 overlay：保留原始 unknown、状态分母和缺失产物，不伪造 success/known，命中项只进入独立 waived 集合并排除下游。duplicate/silent missing/schema/身份漂移、未列 unknown、活动 writer、系统性趋势和任何科学风险继续 fail-closed；cap100 不是自动配额。“补票”作为异步的一般化生产分类/修复任务，不阻塞当前 producer，闭合后退休 run-specific 脚手架。该项属于运维恢复规则，不回填 clean scientific spec；当前正在运行的补算 v2 未因本次记录而修改或中断。

Revision note 2026-07-18 no-autonomous-rerun: 用户进一步澄清“fail-closed”只代表未经授权不放行，不代表 Agent 应自动修复或重跑。以后即使发现系统性故障、科学风险、身份/schema 漂移或根因不明，也先冻结证据并报告真实影响、范围、置信度、放行风险、修复方案及时间成本，由用户决定接受瑕疵还是严格阻断；没有明确指令不得终止当前 producer、改运行中代码或启动昂贵重跑。该审批纪律已加入 handoff、durable memory、README 与 heartbeat，不改变当前补算 v2。

Revision note 2026-07-18 21:54+08:00: 补算 v2 以 5,984 unique、5,970 skipped + 14 known、零 unknown/duplicate/silent missing 通过 `f_supplement_release`，status/release SHA-256 为 `8babca24…d0c` / `123bed2c…fd69`；八例继续 0/3。fresh process audit `eb6f8638…ac6f6` 与独立审计 PASS 后，原子 intent/result `8d0caa57…2ee6` / `bc5006a2…60d2` 仅解除 `try_lock_316116`，保留 after-lock；正式 F 于 21:53:48 由原 CPU96 allocation 复用 run_cmd `0ff22ef9…e131` 恢复 F12/no-overwrite，readiness 与首批真实进度通过。未取消、重提或改写正式 DAG，`316117` 继续等待正式 `f_release`。

Revision note 2026-07-20 controlled-failure waiver v1: 回填正式 F 22,386/22,386 计算完成、45 条 raw unknown 的四类真实分解、0/3 产物与零 writer 停点。记录用户明确批准“不重跑、不改状态、不造占位、gate/G 共用精确 waiver”并把当前 run cap 从 100 提升到 200；本地实现以逐 status-row、全部分片、pair-list、进程门、代码和 artifact 快照绑定，默认路径及 strict smoke 仍严格。本次只更新执行日志、契约 README、mapping 与记忆，不修改 clean scientific spec；服务器放行和 G 仍待实际证据。
