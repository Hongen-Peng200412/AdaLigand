# 整理 AdaLigand A–G 数据管线并保持产物行为等价

本 ExecPlan 是本轮维护工作的唯一执行记录，实施期间必须持续更新 `Progress`、`Surprises & Discoveries`、`Decision Log` 与 `Outcomes & Retrospective`。本文件同时承担计划与执行日志职责，不另建内容重复的并行日志。

本工作依据 `文档/规划文档/数据处理_v2.md` 的现行 A–G 科学与产物规格，审计并整理 `Data_Preprocessing/Ori_Data/`。历史实现与正式全量运行过程保存在 `文档/exec_plan/A-G数据流水线实现与全量运行.md`，本轮不改写该历史记录。当前维护范围是代码结构、注释、产物 README、命令入口、测试组织和已经退出的一次任务脚本；不改变科学定义，不生成 Stage G `keep_list.jsonl`，也不处理 Pocket_Plus 的辅助标签、辅助损失、模型或训练。

## Purpose / Big Picture

完成后，读者可以沿 A、B、C、D、E、F、G 七个阶段依次找到正式入口、科学计算和产物契约，不再需要从混杂的生产模块、外部工具适配器、运行门禁、事故恢复脚本和一次任务调度脚本中猜测主线。数据管线附近的 README 将直接列出每种正式产物和全部非平凡字段。重构前后的代表性产物在文件位置、字段、形状、数据类型、单位、空值、编号、数组对齐、偏移量和数值上保持等价。

本轮同时保存两条 Git 历史。`codex/adaligand-data-preprocessing-maintenance` 保存真实调查、重构、修正和验证过程；`Learn/data-preprocessing-maintenance` 从同一提交 `817940a1682216cb54308a0a0aa87fd76e1216f0` 按人类理解顺序重建；只有两个端点等价并通过独立审计后，`Learn/CUMULATIVE` 才能快进到学习端点。实施和核验期间不推送。

## Progress

- [x] (2026-07-22 17:10+08:00) 从 `817940a1682216cb54308a0a0aa87fd76e1216f0` 建立 `Learn/CUMULATIVE`、`codex/adaligand-data-preprocessing-maintenance` 和 `Learn/data-preprocessing-maintenance`，并创建不含原工作树未提交修改的干净实现工作树。
- [x] (2026-07-22 17:15+08:00) 在实现分支形成第一个独立治理提交 `ce686d8`：只应用已经批准的顶层 `AGENTS.md` 重写和顶层 `CLAUDE.md` 删除。
- [x] (2026-07-22 17:25+08:00) 读取项目记忆索引、2026-07-20 A–G 收口 handoff、现行数据规格、历史 A–G ExecPlan、映射索引和当前 README 结构。
- [x] (2026-07-22 17:28+08:00) 在提交 `817940a` 的原始工作树使用项目 `.venv` 和短临时目录运行 Windows 全套：`402 passed, 10 skipped in 28.35s`。
- [x] (2026-07-22 17:33+08:00) 只读核对服务器：正式作业 `316114/316115/316116/316117` 均为 `COMPLETED 0:0`；当前三个活动作业均为 Stage1 训练，不是 A–G 生产者。
- [x] (2026-07-22 18:12+08:00) 在服务器隔离临时目录冻结 `5net/5mke/5mkf/7b14/7nll` 的代表性输入、A–F 产物、相关 CCD 与配体对象，并保存正式 G 汇总和逐字段语义摘要；随后独立重读归档并与正式文件逐个核对。
- [x] (2026-07-22 18:42+08:00) 建立 `Data_Preprocessing/Ori_Data/` 每个现有文件的职责、调用者、生命周期、目标职责、处理动作和证据矩阵；反向搜索正式脚本、测试、sbatch 与活动 Slurm 命令。
- [x] (2026-07-22 21:05+08:00) 建立 `adaligand_preprocessing` 包、薄命令入口、共享基础层、`ops/` 和最小 `pyproject.toml`；删除已退出的一次任务文件并迁移保留测试。
- [x] (2026-07-22 21:42+08:00) 将 Stage E 按实验密度、模拟密度、配体区域拆分，分离共享哈希与文件锁；Windows 完整测试为 `297 passed, 4 skipped`。
- [x] (2026-07-22 22:10+08:00) 从当前代码、测试、规格和冻结产物重写 `Data_Preprocessing/Ori_Data/README.md`，删除混入运行历史的旧 README 和错误的旧 `learn.md`；20 个命令入口的 `--help` 全部通过。
- [ ] 完成 Windows 全套、Linux 全部适用测试、命令入口、真实 Chimera/MapQ/MRC 小规模验证和冻结产物语义比较。
- [ ] 从共同起点重建 `Learn/data-preprocessing-maintenance`，验证实现端点与学习端点除允许的注释和学习文档外完全等价。
- [ ] 创建一个未参与实现的新审计 subagent；只向其提供原始问题表现、冻结行为边界、两个端点、验证命令和证据位置，处理其独立结论。
- [ ] 经原任务确认后，才允许对三个指定分支执行非强制推送。

## Surprises & Discoveries

- Observation: 新 worktree 在 Windows 全局 `core.autocrlf=true` 下把未在 `.gitattributes` 中固定行尾的 Python 文件检出为 CRLF，导致 Stage F 历史恢复脚本内保存的 SHA-256 与工作树文件不一致。
  Evidence: 干净 worktree 的首次全套为 `401 passed, 10 skipped, 1 failed`；唯一失败是 `test_signal11_resume_scripts_validate_then_run_real_stage_f`。`scripts/stage_f_process_audit.py` 在干净 worktree 的 SHA-256 为 `f47cd63b…cefdb`，原始工作树的 LF 文件为测试固定的 `6cdb58ee…d3af3`。原始工作树用短临时目录仍得到 `402 passed, 10 skipped`。

- Observation: 服务器 `/home/penghongen/My_Project/AdaLigand` 是同步代码目录，不包含 `.git`。
  Evidence: 远端 `git` 仓库探测明确返回“Not a git repository”；本轮删除判断必须组合本地 Git 历史、远端 Slurm 终态、活动作业命令和正式证据路径，不能引用不存在的远端 Git 状态。

- Observation: A–G 正式生产任务已经全部结束，但服务器当前仍有三个 Stage1 训练作业读取既有数据产物。
  Evidence: 2026-07-22 17:33+08:00 的 `squeue` 只列出 `adaligand_s1_unet`、`adaligand_s1_find2_h100x2` 和 `adaligand_s1_h200_probe_2`；A–G 作业 `316114/316115/316116/316117` 的顶层终态均为 `COMPLETED 0:0`。

- Observation: 五个代表样本足以同时覆盖正式 smoke 样本和非默认 MRC 几何，而且不需要复制三个较大的 Stage E 密度文件。
  Evidence: 快照共 87 个文件、44,706,883 字节、6 个 CCD 依赖和 11 个配体对象键。`7b14/7nll` 保存完整 Stage E 文件；`5net/5mke/5mkf` 的 Stage E 文件保存字段、形状、数据类型、数值哈希、极值、求和及空值统计。第二次核验确认 84 个直接复制文件与正式文件逐字节相同，正式目录和快照均不存在 `keep_list.jsonl`。

- Observation: 当前三个活动训练作业不执行待删除的一次任务脚本，但可能读取已经完成的正式 A–G 产物。
  Evidence: `scontrol show job` 显示作业 `321107` 与 `321743` 的命令和工作目录位于 Pocket_Plus，作业 `321540` 执行 `/home/penghongen/My_Project/tmp/adaligand_stage1_alloc_h100_2_replan.sbatch`，工作目录为 `/home/penghongen`；三者均未引用 `Data_Preprocessing/Ori_Data/scripts` 或 `sbatch/resume_*`。因此本轮仍把正式产物保持只读，只整理 Git 中的代码树。

- Observation: 历史收口说明曾把 `mrc.py::grid_world_bounds` 列为“看似未使用”的清理对象，但当前正式测试明确锁定其 XYZ 形状顺序。
  Evidence: `tests/test_mrc_contract.py::test_grid_world_bounds_use_xyz_shape_order` 直接导入并验证该函数。因此它属于公开 MRC 几何边界，本轮保留并随 `geometry/mrc.py` 迁移，不能仅凭生产调用搜索删除。

- Observation: 把 `.py`、Shell、sbatch、JSON 来源清单和 Markdown 的行尾固定为 LF 后，干净工作树可以逐字节复现原始 Windows 基线。
  Evidence: 提交 `e4ba5bb` 增加行尾规则；重构前在干净工作树重跑得到 `402 passed, 10 skipped in 28.68s`，原先唯一失败随源文件 SHA-256 恢复而消失。

- Observation: 退出的一次任务测试占重构前收集结果的 111 项，保留的科学、产物、外部工具、通用运维和正式调度测试共 301 项。
  Evidence: 重构前收集 412 项；重构后 Windows 收集 301 项并得到 `297 passed, 4 skipped`。退出测试逐文件对应职责矩阵中删除的 E3 修复、Stage F 补算、固定作业恢复、长尾截止和源文件快照入口；保留测试没有失败。

- Observation: 冻结 Pocket Plus 副本的模块说明也属于文件身份，不能为适应新路径直接修改。
  Evidence: 修改两份模块说明后，两个逐字节身份测试分别报告 SHA-256 漂移；恢复原字节后四项源码/AST 身份测试全部通过。新路径只写入副本外部的来源清单和 README。

## Decision Log

- Decision: 共同起点和三个分支名称固定为用户指定值，不因工具或目录命名偏好改变。
  Rationale: Git 图本身是实现过程和学习顺序的一部分，名称已经在原任务中收敛。
  Date/Author: 2026-07-22，用户与 Codex。

- Decision: 当前继承未提交修改的 Codex worktree 保持原样；正式实现只在新建干净 worktree 进行。
  Rationale: 原工作树包含用户尚未提交的治理、讨论和服务器同步文件，A–G 提交不得吸收、覆盖或清理它们。
  Date/Author: 2026-07-22，用户。

- Decision: 已批准的顶层 `AGENTS.md` 和顶层 `CLAUDE.md` 改动作为实现分支第一个独立提交，其余继承修改不复制。
  Rationale: 这两项是已经完成讨论的项目治理入口，且需要与服务器同步脚本、讨论记录和 `.review` 文件严格分离。
  Date/Author: 2026-07-22，用户。

- Decision: 只维护本文件一份维护 ExecPlan；执行证据、职责矩阵、删除理由、验证结果和最终回顾都写入本文件或由本文件链接到不可替代的机器产物。
  Rationale: 避免计划、日志和并行说明重复后互相漂移。
  Date/Author: 2026-07-22，用户。

- Decision: 正式产物目录在本轮保持只读，代表性基线先于重构冻结；实现后的真实 smoke 只写隔离运行目录。
  Rationale: 重构完成后重新生成的文件不能作为重构前基线，正式 22,386 个结构也不应因维护任务被重跑或覆盖。
  Date/Author: 2026-07-22，用户与 Codex。

- Decision: 脚本删除以“本地 Git 可追溯、正式 A–G 已结束、当前活动作业不调用、相应运行证据已经保存”四项同时成立为最低条件。
  Rationale: 文件名看似临时不足以证明可以删除，且 Stage1 活动作业仍可能读取正式数据。
  Date/Author: 2026-07-22，用户与 Codex。

## Outcomes & Retrospective

实现端结构整理和 README 重写已经完成，正式产物与科学计算行为没有主动改动。当前仍需完成 Linux 全套、真实外部工具验证、冻结产物比较、学习线重建和独立审计，尚不能宣告本轮完成。

## Context and Orientation

`Data_Preprocessing/Ori_Data/` 是 A–G 的当前实现根目录。`code/` 混合保存科学计算、产物契约、外部工具适配、状态门禁、事故恢复和一次任务控制；`scripts/` 同时包含正式阶段入口、审计入口和一次任务入口；`sbatch/` 同时包含当前通用调度、历史草案和固定 Job ID 的恢复脚本；`tests/` 覆盖科学契约、外部工具适配、调度脚本和历史恢复机制。当前 `code/readme.md` 同时包含产物契约和大量运行历史，`learn.md` 是一次失败的学习性阅读尝试。

现行科学规格是 `文档/规划文档/数据处理_v2.md`。A–G 的正式全量运行只完成到 Stage G analyze：正式 `candidates.pending.jsonl` 和 `quality_distribution.json` 已生成，`keep_list.jsonl` 必须不存在。Stage F 的 19 条运行专属排除与 45 条原始 unknown waiver 是不同集合；`1zku` 和 `6r8n` 同时属于旧 known 集合和 waiver 集合，Stage G 的互斥终态采用 waiver 优先，因此不能把报告集合机械相加。

本轮目标包直接位于 `Data_Preprocessing/Ori_Data/adaligand_preprocessing/`，不再使用含义宽泛的 `code/` 包，也不增加 `src/` 中间层。`stages/` 是 A–G 的阅读主线；共享产物读写、外部工具适配、执行控制和非领域通用机制分别进入职责明确的下层目录。`utils/` 只保存被多个长期模块复用且不决定科学语义的机制，使用 `io.py`、`hashing.py` 等具体文件名，不收容领域规则、产物 schema、外部工具调用或一次任务控制。

## Frozen Behavior Boundary

以下内容必须在两个端点保持不变：

- A–G 科学定义、阈值、样本选择和失败分类；
- Chimera、MapQ、MRC 及其他外部工具参数、版本约束和默认行为；
- 正式产物的相对位置、文件名、字段、形状、数据类型、单位、轴顺序、坐标系、空值、编号、数组对齐、偏移量和数值；
- 命令入口中已经公开的 `--root`、`--part_id`、`--total_parts`、`--n_jobs`、overwrite 和明确的 repair 语义；
- Stage G analyze-only 的完成状态以及 `keep_list.jsonl` 缺失；
- Pocket Plus vendored MRC 六函数和体素中心函数的源码及 AST 等价边界。

发现真实缺陷、规格冲突、正式任务依赖或无法证明的数值差异时，先在本文件冻结证据并请求用户决定，不把修复静默混入结构整理。

## Existing File Responsibility And Lifecycle Matrix

本节是重构前清单。表中的“迁移”表示只改变代码位置、导入和人类可读说明，不改变公开参数或产物；“拆分”表示先用现有测试和冻结摘要锁定行为，再按职责移动函数；“删除”只用于 Git 已保存、正式运行已结束、活动任务未调用且运行证据仍存在的一次任务文件。目标路径是职责方向，不要求机械照搬旧文件名。

### `code/` 当前模块

| 当前文件 | 当前具体职责与直接使用者 | 生命周期判断 | 处理动作与目标职责 |
| --- | --- | --- | --- |
| `code/__init__.py` | 只说明旧 `code/` 导入方式；脚本实际通过 `sys.path.insert` 后裸导入模块 | 旧布局导航 | 删除；由 `adaligand_preprocessing/__init__.py` 和各子包直接表达边界 |
| `code/atom_labels.py` | 按配体重原子距离生成 Stage D 原子标签；由 `scripts/d_atom_labels.py` 与 Stage D 测试调用 | 长期科学计算 | 迁入 `stages/stage_d.py`，保留标签字段、4 Å 默认阈值和编号对齐 |
| `code/c_ccd_prefetch.py` | 并行预取给定 CCD 标识清单；由同名脚本和测试调用 | 默认关闭、可复用维护 | 迁入 `ops/stage_c_dependencies.py`，与描述符预取共享清单哈希和汇总机制 |
| `code/c_descriptor_prefetch.py` | 并行生成给定配体对象的描述符缓存；由同名脚本和测试调用 | 默认关闭、可复用维护 | 与 CCD 预取合并到 `ops/stage_c_dependencies.py` 的独立入口 |
| `code/c_source_rebuild.py` | 对给定结构清单审计并重建 Stage C 来源，要求固定清单哈希和预计增删改数量 | 默认关闭、可复用但高风险 | 迁入 `ops/stage_c_sources.py`；保留 audit/apply 分离、预期数量和提交前门禁 |
| `code/c_source_repair.py` | 审计或应用 Stage C 来源修复，可接收重建汇总作为委托证据 | 默认关闭、可复用但高风险 | 与 rebuild 合并到 `ops/stage_c_sources.py`，保留严格哈希、数量和 audit/apply 边界 |
| `code/c_upgrade.py` | 把旧 Stage C 产物升级到现行字段；由 `parse.py` 正式调用 | 长期兼容逻辑 | 迁入 `stages/stage_c/upgrades.py`，不得降为运维脚本 |
| `code/chimera.py` | 构造并执行 Chimera 命令，解析四种 CC 和密度生成结果 | 长期外部工具适配 | 迁入 `external_tools/chimera.py`，保持命令文本、环境、超时和解析规则 |
| `code/constants.py` | 保存 Stage C 配体、聚合物和元素映射等常量 | 长期科学常量 | 按所有权拆到 `stages/stage_c/constants.py`；跨阶段常量才保留在包级契约层 |
| `code/contracts.py` | 校验 Stage C occurrences、配体坐标、受体 token 和对象引用 | 长期产物契约 | 迁入 `stages/stage_c/contracts.py`，名称不再暗示管理所有阶段 |
| `code/controlled_failure_waiver.py` | 校验固定哈希的受控 unknown 清单，并供 release gate 与 Stage G 使用 | 长期执行契约 | 迁入 `execution/controlled_failures.py`；不改变默认严格拒绝和 waiver 优先规则 |
| `code/density.py` | 生成 Stage E 实验密度、模拟密度和 ligand-area；也含曾供 E3 修复复用的正式计算函数 | 长期科学计算，夹有已退出修复接口 | 按 E1/E2/E3 主要产物拆入 `stages/stage_e/`；删除只服务旧 E3 修复控制的包装，不改变计算函数 |
| `code/download.py` | 下载并复用 mmCIF、EMDB 元数据与 MRC 文件 | 长期 Stage B | 迁入 `stages/stage_b.py`，保持资源选择、重试、复用和原子替换语义 |
| `code/e3_launch_control.py` | 为一次 E3 修复创建授权、校验调度身份、抓取快照和释放门禁 | 绑定已结束修复运行 | 删除；Git、旧 ExecPlan、修复运行目录和已完成 Slurm 证据继续保存过程 |
| `code/e3_repair.py` | 准备、分片执行并合并一次 E3 修复目标 | 绑定已结束修复运行 | 删除；其中仍属于正式 E3 的纯计算继续由 `density.py` 迁移后的模块拥有 |
| `code/exclusions.py` | 读取运行级结构排除清单并应用于 Stage E/F 与 release gate | 长期执行契约 | 迁入 `execution/exclusions.py`，保持 19 条运行专属排除与 45 条 waiver 分离 |
| `code/f_supplement.py` | 依据正式运行尾段生成 Stage F 补算计划 | 绑定已结束补算运行 | 删除；历史计划与产物保留在 Git、旧 ExecPlan 和服务器证据目录 |
| `code/f_supplement_guard.py` | 监控正式作业、进程组和停止标记，控制一次 Stage F 补算 | 绑定已结束补算运行 | 删除；不把事故期间的并发控制提升为正式 Stage F 接口 |
| `code/failures.py` | 定义跨阶段已知失败分类和序列化名称 | 长期产物契约 | 迁入 `artifacts/failures.py`，保持枚举值和报告字符串 |
| `code/filtering.py` | 汇总 Stage G 质量分布、生成候选记录并执行 filter 模式 | 长期 Stage G，混合少量执行状态读取 | 科学与产物生成迁入 `stages/stage_g.py`；通用运行状态读取下沉 `execution/` |
| `code/io_utils.py` | 原子写入 JSON/JSONL/NPZ、哈希、文件锁和基础读取 | 长期共享机制，职责过多 | 拆入 `utils/io.py`、`utils/hashing.py`、`utils/locking.py`；不得吸收字段契约或科学规则 |
| `code/ligand_descriptors.py` | 计算并保存配体描述符 | 长期 Stage C | 迁入 `stages/stage_c/descriptors.py`，保持字段和 RDKit 语义 |
| `code/ligand_object.py` | 从 CCD 构造、缓存和读取配体对象 NPZ | 长期 Stage C | 迁入 `stages/stage_c/ligand_objects.py`，保持模板原子编号和占位表示 |
| `code/long_tail_cutoff.py` | 固化一次 Stage E 正式运行与补算作业的长尾停止证据 | 绑定具体 run id、Job ID 和停止标记 | 删除；停止决定继续由旧 ExecPlan、Git 和服务器日志保存 |
| `code/mapq.py` | 生成 MapQ 输入、执行固定 MapQ 并读取逐原子 Q | 长期外部工具适配 | 迁入 `external_tools/mapq.py`，保持版本、命令、原子映射和解析规则 |
| `code/model_cif.py` | 为 Chimera/MapQ 写入保留原子身份的模型 mmCIF | 长期外部工具输入 | 迁入 `external_tools/model_cif.py`，保持 `_atom_site` 标识语义 |
| `code/mrc.py` | 读取 MRC 几何、坐标变换和重采样，调用 Pocket Plus 冻结函数 | 长期 MRC 边界 | 迁入 `geometry/mrc.py`，保持轴、origin、start、actual voxel 与数值结果 |
| `code/mrc_contract_audit.py` | 参数化扫描 MRC 契约并合并审计分片 | 默认关闭、可复用审计 | 迁入 `ops/mrc_contract.py`，保留只读扫描和固定输入清单 |
| `code/mrc_origin_shift_audit.py` | 审计重采样前后 origin 位移并合并结果 | 默认关闭、可复用审计 | 迁入 `ops/mrc_origin_shift.py`，保留 scan/merge 契约 |
| `code/mrc_pocket_legacy.py` | vendored Pocket Plus 六个 MRC 函数 | 长期冻结兼容基线 | 原样迁入 `geometry/legacy/mrc_pocket.py`；源码和 AST 等价单独验证 |
| `code/mrc_pocket_legacy.source.json` | 记录六个函数的来源提交和源码哈希 | 长期来源证据 | 与 vendored 文件一起迁入 `geometry/legacy/`，只更新相对位置说明 |
| `code/parallel.py` | 结构清单分片和 joblib 并行执行 | 长期共享执行机制 | 迁入 `execution/parallel.py`，不包含阶段科学规则 |
| `code/parse.py` | 执行 Stage C：解析 mmCIF、物化配体对象/坐标/受体 token 并升级旧产物 | 长期 Stage C，文件过大 | 拆为 `stages/stage_c/pipeline.py` 与产物构造子模块；保留单结构和批量入口 |
| `code/qc.py` | 校验正式样本文件是否齐全及结构级产物契约 | 长期质量契约 | 按具体所有权迁入 `artifacts/validation.py`；Stage C 专属校验仍留在 Stage C 契约 |
| `code/quality.py` | 生成 Stage F 四种 CC、配体逐原子 Q 和口袋 Q，并管理 scratch 生命周期 | 长期科学计算，文件过大 | 按 CC、配体 Q、口袋 Q 和批处理拆入 `stages/stage_f/`；scratch 机制下沉 `execution/scratch.py` |
| `code/rcsb.py` | 查询 RCSB/EMDB、建立 PDB–EMDB 配对和分辨率摘要 | 长期 Stage A | 迁入 `stages/stage_a.py`，保持查询、主 EMDB 选择和排序 |
| `code/receptor.py` | 从 mmCIF 构造受体 token 与原子映射 | 长期 Stage C | 迁入 `stages/stage_c/receptor.py`，保持 token 编码和坐标顺序 |
| `code/reports.py` | 生成阶段状态、摘要和失败报告 | 长期跨阶段产物 | 按稳定文件格式迁入 `artifacts/reports.py`；运行门禁判断不留在此模块 |
| `code/smoke_checks.py` | 判断负 CC smoke 是否达到最小下降 | 默认关闭、可复用验证 | 迁入 `ops/smoke_checks.py`，只服务显式 smoke 命令 |
| `code/stage_f_process_audit.py` | 抓取和校验 Slurm/进程/锁状态证据 | 默认关闭、可复用服务器审计 | 与契约模块合并到 `ops/stage_f_processes.py`，保持只读 capture/validate |
| `code/stage_f_process_audit_contract.py` | 为受控 waiver 校验 Stage F 进程审计包 | 长期门禁与运维审计之间的连接 | 合并到 `ops/stage_f_processes.py`，由 `execution/controlled_failures.py` 只调用稳定验证接口 |
| `code/stage_f_scratch_recovery.py` | 审计或清理指定 run/job 的遗留 scratch，要求进程审计证据 | 默认关闭、可复用恢复 | 迁入 `ops/stage_f_scratch.py`，保留 audit/apply、路径限制和证据哈希 |
| `code/voxel_gt_pocket_legacy.py` | vendored Pocket Plus 体素中心函数 | 长期冻结兼容基线 | 原样迁入 `geometry/legacy/voxel_centers.py`；源码和 AST 等价单独验证 |
| `code/voxel_gt_pocket_legacy.source.json` | 记录体素中心函数来源提交和源码哈希 | 长期来源证据 | 与 vendored 文件一起迁入 `geometry/legacy/` |
| `code/readme.md` | 混合产物字段契约、运行命令、Job 事故、补算和 waiver 过程 | 长期文档但职责失焦 | 从现行实现、测试、规格和冻结产物重写为 `Data_Preprocessing/Ori_Data/README.md`；只回答产物位置、全部字段和必要读取约定 |

### 根目录、`scripts/` 与 `sbatch/`

| 当前文件 | 当前具体职责与直接使用者 | 生命周期判断 | 处理动作与目标职责 |
| --- | --- | --- | --- |
| `learn.md` | 按旧混合目录解释代码，且把一次任务控制与正式逻辑交织为阅读主线 | 已确认失败的学习文档 | 实现端删除；学习分支在最终逻辑提交顺序确定后重建新的阅读指南 |
| `pytest.ini` | 指定测试目录、默认临时目录并禁用缓存 | 长期测试配置 | 保留并改用短的可覆盖临时目录策略；包发现交给 `pyproject.toml` |
| `scripts/a_enumerate.py` | Stage A 参数解析与落盘 | 长期正式入口 | 改为调用包内 `cli/stage_a.py` 的薄入口；保留全部参数和默认值 |
| `scripts/a_guard.py` | 核对 pair list 数量与哈希 | 长期 Stage A 门禁 | 迁入统一 `cli/release.py` 的具体 Stage A 检查入口 |
| `scripts/abc_release_gate.py` | 固定调用 A/B/C release gate | 长期入口但与通用 gate 重复 | 合并到统一 release CLI 的 `abc` 子命令；更新正式 sbatch 调用 |
| `scripts/b_download.py` | Stage B 参数解析、分片和下载 | 长期正式入口 | 改为薄入口，参数保持不变 |
| `scripts/c_parse.py` | Stage C 参数解析、分片和解析 | 长期正式入口 | 改为薄入口，参数保持不变 |
| `scripts/d_atom_labels.py` | Stage D 参数解析、分片和标签生成 | 长期正式入口 | 改为薄入口，参数保持不变 |
| `scripts/e_density.py` | Stage E 参数解析、Chimera 与 scratch 配置 | 长期正式入口 | 改为薄入口，参数保持不变 |
| `scripts/f_quality.py` | Stage F 参数解析、Chimera/MapQ 与 scratch 配置 | 长期正式入口 | 改为薄入口，参数保持不变 |
| `scripts/g_filter.py` | Stage G analyze/filter 参数解析 | 长期正式入口 | 改为薄入口；本轮只验证 analyze，不生成 `keep_list.jsonl` |
| `scripts/stage_release_gate.py` | 按指定阶段校验状态、排除和 waiver | 长期统一门禁入口 | 迁入包内 `cli/release.py`；保留参数，吸收重复的 ABC 包装 |
| `scripts/c_ccd_prefetch.py`, `scripts/c_descriptor_prefetch.py` | 校验固定输入清单后执行 Stage C 依赖预取 | 默认关闭、可复用维护入口 | 迁入 `cli/ops.py` 的独立子命令；保留哈希与预计数量参数 |
| `scripts/c_source_rebuild.py`, `scripts/c_source_repair.py` | 对固定结构清单执行 Stage C 来源 audit/apply | 默认关闭、高风险维护入口 | 迁入 `cli/ops.py`；保留 audit/apply 分离和所有证据参数 |
| `scripts/audit_mrc_contract.py`, `scripts/audit_mrc_origin_shift.py` | 运行 MRC 契约与 origin 位移审计 | 默认关闭、可复用审计入口 | 迁入 `cli/ops.py`，保留分片与合并方式 |
| `scripts/smoke_mrc_geometry.py`, `scripts/smoke_negative_cc.py` | 在显式输出目录执行真实 MRC/Chimera 小规模验证 | 默认关闭、可复用验证入口 | 迁入 `cli/smoke.py`，保持输出隔离和判定阈值 |
| `scripts/stage_f_process_audit.py`, `scripts/stage_f_scratch_recovery.py` | 抓取进程证据及 audit/apply 遗留 scratch | 默认关闭、可复用服务器维护入口 | 迁入 `cli/ops.py`，保留路径限制、哈希和审计先行要求 |
| `scripts/snapshot_source_dirty.py` | 按 mtime 窗口冻结 Stage C 来源变更清单 | 绑定一次来源污染事故，不能可靠表达长期来源定义 | 删除；相应输入清单、哈希和运行摘要已由 Git、旧 ExecPlan 与服务器证据保存 |
| `scripts/e3_launch_control.py`, `scripts/e3_repair.py` | 启动并执行一次 E3 修复 | 绑定已结束修复运行 | 与对应 `code/` 模块一起删除 |
| `scripts/f_signal11_exclusion_transition.py` | 为固定正式运行、Job ID、PDB 和证据 UUID 迁移 Signal 11 排除 | 明确一次任务 | 删除；不保留参数化假象 |
| `scripts/f_supplement_guard.py`, `scripts/f_supplement_plan.py` | 规划和保护一次 Stage F 尾段补算 | 绑定已结束补算运行 | 与对应 `code/` 模块一起删除 |
| `scripts/stage_e_long_tail_cutoff.py` | 应用一次 Stage E 长尾截止授权 | 绑定固定 Job ID 与证据文件 | 与 `code/long_tail_cutoff.py` 一起删除 |
| `sbatch/_adaligand_job_core.sh` | 提供 run_cmd、pre/try/kill lock、心跳与进程组清理 | 长期服务器执行基础 | 迁入 `execution/slurm/_job_core.sh` 或保留同等明确位置；固定 LF 并保持锁语义 |
| `sbatch/abc_full.sbatch`, `sbatch/de_full.sbatch`, `sbatch/f_full.sbatch`, `sbatch/g_analyze.sbatch` | 正式 A–G 阶段调度模板 | 长期正式调度 | 保留为薄调度文件并改用新 CLI；资源、依赖与 analyze-only 不变 |
| `sbatch/real_smoke.sbatch`, `sbatch/negative_cc_smoke.sbatch` | 正式工具链小规模验证调度 | 长期显式 smoke | 保留并改用新 smoke CLI，输出仍要求隔离 run id |
| `sbatch/submit_full_pipeline.sh`, `sbatch/submit_real_smoke.sh` | 提交正式阶段依赖链或 smoke | 长期提交入口 | 保留，更新脚本位置但不改变依赖顺序 |
| `sbatch/a.sbatch`, `sbatch/b.sbatch`, `sbatch/c.sbatch` | 早期单阶段草案，服务器 README 已标记非当前入口 | 已被正式模板替代 | 删除；Git 保留草案历史 |
| `sbatch/_f_supplement_stage.sh`, `sbatch/f_supplement_96.sbatch` | 一次 Stage F 补算的共享阶段与提交配置 | 绑定已结束补算运行 | 删除 |
| `sbatch/e3_repair_gate.sbatch`, `sbatch/e3_repair_shard.sbatch` | 一次 E3 修复 worker/gate | 绑定已结束修复运行 | 删除 |
| `sbatch/resume_abc_316114_source_v2.sh` | 固定作业 316114、来源修复和 CCD:5GP 的恢复命令 | 明确一次任务 | 删除；正式作业已完成，命令仍在 Git 与运行证据中 |
| `sbatch/resume_de_316115_e_repair_v1.sh`, `v2.sh`, `v3.sh` | 固定作业 316115、修复 run id 和目标 PDB 的恢复命令 | 明确一次任务 | 删除；三个版本由 Git 保存 |
| `sbatch/resume_f_316116_long_tail_v1.sh`, `resume_f_316116_signal11_v1.sh` | 固定作业 316116 的长尾与 Signal 11 恢复命令 | 明确一次任务 | 删除 |
| `sbatch/resume_f_supplement_318350_accel_v2.sh`, `resume_f_supplement_318350_signal11_v1.sh` | 固定补算作业 318350 的加速与 Signal 11 恢复命令 | 明确一次任务 | 删除 |

当前活动 Slurm 作业的命令核查未发现上述删除候选。正式 A–G 作业均已结束；每个删除提交仍须在提交说明和本文件中列出文件集合，使 Git 历史可以直接恢复任一文件。

### `tests/` 当前文件

测试随被测职责迁移到新的包导入，不通过兼容壳继续引用 `code/`。删除一次任务测试不会被误报成正式科学覆盖减少；Windows 接受结果同时报告“保留测试”和“有证据退出的测试”数量。

| 当前文件 | 锁定的行为 | 处理动作 |
| --- | --- | --- |
| `tests/test_atom_labels.py` | Stage D 标签、距离阈值和产物字段 | 保留，迁移导入 |
| `tests/test_chimera_adapter.py` | Chimera 命令、环境、超时与结果解析 | 保留，迁移到外部工具测试 |
| `tests/test_density_stage_e.py` | E1/E2/E3 几何、字段和数值语义，以及少量旧 E3 修复包装 | 保留正式 Stage E 断言；随删除的修复控制断言退出并逐项记录 |
| `tests/test_download_reuse.py` | Stage B 已下载资源复用 | 保留 |
| `tests/test_filtering_stage_g.py` | Stage G 分布、候选、analyze/filter 和状态优先级 | 保留；明确验证本轮不产生 keep list |
| `tests/test_mapq_adapter.py` | MapQ 命令、输入和逐原子 Q 解析 | 保留 |
| `tests/test_model_cif.py` | 外部工具模型 mmCIF 的原子身份 | 保留 |
| `tests/test_mrc_contract.py` | MRC 轴、origin、start、actual voxel 和坐标换算 | 保留 |
| `tests/test_mrc_pocket_legacy_parity.py` | vendored Pocket Plus 六函数的源码/行为等价 | 保留，并更新来源位置 |
| `tests/test_voxel_gt_pocket_legacy_parity.py` | vendored 体素中心函数等价 | 保留，并更新来源位置 |
| `tests/test_pipeline_smoke.py` | 合成 A–G 端到端产物衔接 | 保留，作为迁移逐步门禁 |
| `tests/test_qc_contract.py` | 样本完整性与正式产物校验 | 保留 |
| `tests/test_quality_projection.py` | Stage F 坐标投影、原子与体素对齐 | 保留 |
| `tests/test_quality_scratch_lifecycle.py` | Stage F scratch 创建、提交、失败与回收 | 保留；随执行机制迁移 |
| `tests/test_run_exclusions.py` | 运行级结构排除的读取与应用 | 保留 |
| `tests/test_stage_c_contract_extensions.py` | Stage C 扩展字段、升级和严格校验 | 保留 |
| `tests/test_stage1_semantics.py` | Pocket Plus 所需 Stage1 字段与语义 | 保留；只验证现有契约，不修改 Pocket_Plus |
| `tests/test_controlled_failure_waiver.py` | waiver 哈希、集合关系、默认严格失败和审计证据 | 保留 |
| `tests/test_stage_release_gate.py` | 阶段 release gate、排除与 waiver | 保留；吸收 ABC 专用入口覆盖 |
| `tests/test_c_ccd_prefetch.py`, `test_c_descriptor_prefetch.py` | 固定输入清单与依赖预取 | 保留为 `ops` 测试 |
| `tests/test_c_source_rebuild.py`, `test_c_source_rebuild_cli.py`, `test_c_source_repair.py` | Stage C 来源 audit/apply、委托证据和严格计数 | 保留为高风险 `ops` 测试 |
| `tests/test_mrc_contract_audit.py`, `test_mrc_origin_shift_audit.py` | MRC 审计扫描、分片合并和证据哈希 | 保留为 `ops` 测试 |
| `tests/test_smoke_checks.py` | 负 CC smoke 的最小下降判定 | 保留 |
| `tests/test_stage_f_process_audit.py` | 进程、Slurm、锁文件审计包的 capture/validate | 保留，与重复契约实现合并 |
| `tests/test_stage_f_scratch_recovery.py` | 遗留 scratch 的 audit/apply 和安全路径限制 | 保留 |
| `tests/test_e3_launch_control.py` | 一次 E3 修复授权和调度身份 | 随被测一次任务代码删除 |
| `tests/test_e3_repair.py`, `tests/test_e3_repair_cli.py` | 一次 E3 修复准备、执行和合并 | 随被测一次任务代码删除；正式 E3 计算仍由 Stage E 测试覆盖 |
| `tests/test_f_signal11_exclusions.py` | 固定 run、Job ID、PDB 和证据 UUID 的迁移过程 | 随一次任务脚本删除 |
| `tests/test_f_supplement.py`, `tests/test_f_supplement_guard.py` | 一次补算计划、进程组和停止标记 | 随一次任务代码删除 |
| `tests/test_long_tail_cutoff.py` | 一次长尾截止授权和固定证据文件 | 随一次任务代码删除 |
| `tests/test_source_snapshot.py` | 一次来源污染事故的 mtime 窗口快照 | 随 `snapshot_source_dirty.py` 删除 |
| `tests/test_sbatch_contract.py` | 混合验证正式调度、历史草案、固定恢复脚本及其源码哈希 | 拆分：保留正式调度、锁与提交依赖链；删除仅针对退出文件的断言 |

清单覆盖重构前 `Data_Preprocessing/Ori_Data/` 中全部 Git 跟踪的 Python、Shell、sbatch、Markdown、JSON 来源记录和 pytest 配置。数据目录、运行输出与日志不在 Git 树内，也不作为本轮移动或删除对象。

## Plan of Work

第一阶段建立重构前事实。枚举 `code/`、`scripts/`、`sbatch/`、`tests/` 和根目录文件，对每个文件记录当前职责、直接调用者、它属于长期生产、默认关闭的可复用运维还是已经退出的一次任务、建议目标位置、保留/拆分/合并/提升/删除动作及证据。冻结合成端到端 fixture 与五个真实代表样本的输入和产物，生成可重算的字段与数值摘要。

第二阶段建立新的包骨架和测试导入方式。先固定契约测试和基线比较器，再迁移共享产物、外部工具和执行机制，最后按 A–G 阶段迁移正式入口。每一步都使用路径明确的提交和阶段测试，不建立 `code/*.py` 兼容壳，不保留 `sys.path.insert` 或裸模块导入。

第三阶段收口生命周期。仍有明确长期价值的默认关闭工具进入 `ops/`，并具备参数化入口、测试和使用边界。只服务已经结束的 source repair、固定 Job ID 恢复、长尾截止、补算、迁移和事故恢复代码，在逐项确认远端无活动依赖并保存证据后从活跃树删除；历史继续由 Git、旧 ExecPlan 和服务器运行目录保存。

第四阶段重写注释与 README。生产模块说明一个主要职责、稳定入口和具体产物；产物构造、读写和校验函数逐字段解释形状、单位、坐标、编号与对齐。README 从当前实现、测试、现行规格和代表产物重建，开头直接给出文件清单和字段契约，不保存 Job ID、事故过程和一次任务脚本说明。

第五阶段完成实现端验证和学习线重建。Windows 使用短 `--basetemp`，Linux 运行全部适用测试；在隔离目录完成真实 MRC、Chimera 和 MapQ 小规模执行；比较冻结输入与产物摘要。实现端稳定后，从 `817940a` 重建学习分支，先展示契约和测试，再展示共享层和 A–G 阶段，最后加入学习注释和指南。

第六阶段启动独立审计。审计 subagent 不读取本文件中的职责判断和删除理由，只接收用户规定的最小材料。任何审计阻断先回到实现分支处理，再重建受影响的学习提交和重新审计。

## Concrete Steps

所有本地命令从仓库根目录执行。Windows 测试使用原项目 `.venv` 的解释器，并把 pytest 临时目录放到 `C:\tmp` 下的短路径。最终命令在路径迁移后更新为新的包入口；基线命令为：

    <project-python> -m pytest Data_Preprocessing/Ori_Data/tests -q --basetemp C:\tmp\ada_ag_817940a_pytest

服务器只读核对使用项目自己的 `与服务器交互/other/Invoke-PasswordSsh.ps1`，严格主机密钥检查，不运行删除式同步，不改正式产物。真实验证需要写入时，只使用新 run id 和隔离目录，并在启动前把命令、输入清单与退出条件补到本节。

分支端点比较至少包含：

    git diff --name-status <work-endpoint> <learn-endpoint>
    git diff --check <work-endpoint> <learn-endpoint>

Python 可执行语句另做忽略纯注释、单独检查 Docstring 的 AST 比较；两个端点分别运行同一组测试和代表性产物比较。

## Validation and Acceptance

接受标准不是“目录更整齐”，而是同时满足以下可观察结果：

1. 从 A 到 G 的每个正式入口都能通过新包和薄 CLI 调用，帮助信息和参数默认值与基线一致。
2. Windows 全套不低于重构前可比测试集合，基线是 `402 passed, 10 skipped`；删除历史脚手架测试造成的数量减少必须逐个映射到被删除入口。
3. Linux 运行全部适用测试，不要求跳过数量与 Windows 相同。
4. 五个真实代表样本和合成端到端 fixture 的产物位置、字段、形状、数据类型、单位、空值、编号、数组对齐、偏移量和数值与冻结基线一致；时间、临时路径和明确列出的 provenance 代码哈希变化单独解释。
5. 真实 Chimera/MapQ/MRC smoke 只写隔离目录，验证非零 origin、非精确 1 Å actual voxel、标准轴、canonical/sim 几何、四种 CC 和逐原子/配体/口袋 Q。
6. 正式 22,386 个结构不重跑，正式 A–G 产物不覆盖，`keep_list.jsonl` 不生成。
7. 实现端点和学习端点的所有差异都属于预先批准的中文学习注释、Docstring 或学习文档，且两个端点运行结果等价。
8. 独立审计 subagent 没有未处理的阻断；原任务明确确认后才允许非强制推送。

## Idempotence and Recovery

所有调查和基线摘要命令必须只读或写入隔离证据目录，可以重复执行。正式产物目录不作为测试输出。模块迁移以小提交进行；某一步失败时保留实现分支历史，修复当前步骤，不 reset 用户工作树，也不强制移动公开分支。

删除文件前先确认它已被 Git 保存、历史 ExecPlan 或服务器证据引用可用、远端活动作业不调用、替代入口已经测试。条件不足时保留文件并在职责矩阵标记阻断，不以清洁目录为由扩大删除范围。

学习线只在实现端点稳定后重建。`Learn/CUMULATIVE` 只允许从当前端点快进；无法快进时停止检查，不强制移动。

## Artifacts and Notes

重构前共同起点：

    817940a1682216cb54308a0a0aa87fd76e1216f0

实现分支第一个治理提交：

    ce686d8 chore: simplify agent governance entry

Windows 基线：

    402 passed, 10 skipped in 28.35s

干净工作树固定 LF 后的重构前基线：

    402 passed, 10 skipped in 28.68s

当前实现端 Windows 完整结果：

    297 passed, 4 skipped in 35.20s

实现端主要提交：

    e4ba5bb chore: pin preprocessing text line endings
    1dff68d refactor: organize A-G preprocessing package
    d1ab95c refactor: separate hashing and file locking
    7319f96 refactor: separate Stage E artifact builders
    e83dc52 docs: replace A-G artifact guide

重构前服务器快照：

    /home/penghongen/My_Project/tmp/adaligand_a_g_maintenance_817940a_20260722
    /home/penghongen/My_Project/tmp/adaligand_a_g_maintenance_817940a_20260722.tar.gz

快照清单 `baseline_manifest.json` 的 SHA-256：

    d24689c466a60ae22c349fa2b45bb2a214c721707a1cb0809c788f0c71559449

归档文件共 25,753,538 字节，SHA-256 为：

    5207d2b5448aae5b19375af39f3326a43c7f1cd99cbbae230d7dd0fe04b10b3e

归档复核共读取 114 个归档条目；除快照内另外生成的样本子集外，84 个复制文件均与正式文件逐字节一致。该快照位于项目授权的服务器临时目录，不在正式数据树内。

正式 A–G 终态和最终审计摘要继续引用历史 ExecPlan；本轮只保存与代码维护等价性直接相关的最小证据，不复制完整运行事故时间线。

## Interfaces and Dependencies

Python 运行依赖包括 NumPy、SciPy、Gemmi、RDKit、Requests、Joblib、mrcfile 和 pdbeccdutils。外部科学工具是 UCSF Chimera 1.19 OSMesa 与固定 MapQ。新包必须保持 Python 3.10 可用；最小 `pyproject.toml` 只负责包发现、测试和命令入口，不擅自升级依赖版本。

稳定的下层边界包括：产物路径和字段校验、原子写入、失败枚举、MRC 几何、Chimera/MapQ 调用、运行状态与 release gate。阶段模块可以调用这些边界，下层模块不得反向导入 A–G 高层入口。`utils/` 不拥有任何科学阈值、字段 schema、失败分类或外部工具命令。

## Plan Drift / Reconciliation

### Beneficial drift

- Stage C 没有按初始草案合并为少数大文件，而是保留 `constants/contracts/descriptors/ligand_objects/pipeline/receptor/upgrades` 七个具名职责；这比 `ops/stage_c_dependencies.py` 一类合并名更便于定位稳定科学逻辑与维护入口。
- Stage E 最终形成包级公开接口和三个产物职责文件，共用坐标与等高线规则进入 `common.py`；测试不再依赖旧单文件内部属性。
- 已退出的一次任务测试与实现同时删除，正式测试保留并单独报告收集数量，避免用兼容壳伪装旧入口仍受支持。

### Neutral drift

- 当前 `stages/stage_f.py` 仍约一千行。它围绕唯一的质量三件套、其构建函数和同一验证闭环，暂不为满足文件长度机械拆分；独立审计若证明阅读边界仍不清楚，再按实际依赖拆分。

### Harmful drift

尚未发现。

### Unfinished scope

- Linux 全套、真实 Chimera/MapQ/MRC 检查、冻结产物语义比较尚未完成。
- 学习线和独立审计尚未开始。

Revision note 2026-07-22 17:40+08:00: 创建本 ExecPlan，记录固定分支、隔离工作树、治理提交、行为边界、Windows 基线、服务器只读终态、代表样本选择和独立审计要求。

Revision note 2026-07-22 18:20+08:00: 回填重构前服务器快照、逐字段摘要、归档哈希、第二次只读核验和活动任务命令证据；代表性行为基线已经在任何代码重构之前冻结。

Revision note 2026-07-22 18:45+08:00: 加入覆盖全部现有代码、入口、调度、文档和测试的职责与生命周期矩阵；结合直接导入、测试、固定运行标识和活动 Slurm 命令确定迁移、合并或退出方向。

Revision note 2026-07-22 22:15+08:00: 回填 LF 身份修复、包迁移、一次任务删除、Stage E 与共享工具拆分、Windows 完整结果、README 重写、命令入口验证和当前计划偏差。
