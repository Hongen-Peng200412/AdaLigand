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
- [ ] 冻结代表性输入、重构前产物和逐字段语义摘要；已选择正式 smoke 的 `5net/5mke/5mkf` 以及非默认 MRC 几何的 `7b14/7nll`。
- [ ] 建立 `Data_Preprocessing/Ori_Data/` 每个现有文件的职责、调用者、生命周期、目标位置、处理动作和证据矩阵。
- [ ] 按阶段主线建立 `adaligand_preprocessing` 包、薄命令入口、共享基础层、`ops/` 和最小 `pyproject.toml`，逐步迁移测试并保持阶段验证通过。
- [ ] 从当前代码、测试、规格和冻结产物重写数据管线 README；删除已经确认错误的旧 `learn.md`，学习指南在学习分支按最终逻辑历史重建。
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

尚未完成。当前只完成隔离工作树、治理提交、事实调查和 Windows 测试基线；尚未改变任何 A–G 科学计算代码。

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

正式 A–G 终态和最终审计摘要继续引用历史 ExecPlan；本轮只保存与代码维护等价性直接相关的最小证据，不复制完整运行事故时间线。

## Interfaces and Dependencies

Python 运行依赖包括 NumPy、SciPy、Gemmi、RDKit、Requests、Joblib、mrcfile 和 pdbeccdutils。外部科学工具是 UCSF Chimera 1.19 OSMesa 与固定 MapQ。新包必须保持 Python 3.10 可用；最小 `pyproject.toml` 只负责包发现、测试和命令入口，不擅自升级依赖版本。

稳定的下层边界包括：产物路径和字段校验、原子写入、失败枚举、MRC 几何、Chimera/MapQ 调用、运行状态与 release gate。阶段模块可以调用这些边界，下层模块不得反向导入 A–G 高层入口。`utils/` 不拥有任何科学阈值、字段 schema、失败分类或外部工具命令。

## Plan Drift / Reconciliation

### Beneficial drift

尚未发现。

### Neutral drift

尚未发现。

### Harmful drift

尚未发现。

### Unfinished scope

- 文件职责和生命周期矩阵尚未完成。
- 代表性产物尚未完成逐字段冻结。
- 包迁移、README、学习线和独立审计尚未开始。

Revision note 2026-07-22 17:40+08:00: 创建本 ExecPlan，记录固定分支、隔离工作树、治理提交、行为边界、Windows 基线、服务器只读终态、代表样本选择和独立审计要求。
