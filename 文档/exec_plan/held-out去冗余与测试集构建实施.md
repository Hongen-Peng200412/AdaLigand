# Held-out 去冗余与测试集构建实施记录

本文记录 `文档/规划文档/held-out去冗余与测试集构建.md` 的实际实现、验证、审查、Git 双线和服务器运行证据。科学定义和字段解释不在此重复。

## 当前状态

- 2026-08-30：从唯一最新且工作树干净的 `Learn/CUMULATIVE@e90530c` 建立隔离实现分支 `codex/held-out-sequence-redundancy`。
- 已核实 RCSB 当前官方 FASTA 为 per-entity 输出，入口为 `/fasta/entry/<pdb_id>/download`；header 使用 `<pdb_id>_<entity_id>` 并附 chain。
- 已核实 MMseqs2 官方参数：`--cov-mode 0` 表示同时约束 query 和 target coverage；`--alignment-mode 3` 输出真实 identity。
- 已核实 MMseqs2 `fident` 是 `[0,1]` 的 identical-match fraction，`pident` 才是百分数；正式 TSV 因此使用 `fident` 并按 `0.30/0.80` 读取。
- 已核实现有冻结输入：完整 PDB 22,386，暴露参考 14,017，held-out 2,497；正式数据根为 `/storage/penghongen/AdaLigand/Ori_Data`。

## 八组合 split 追加执行

- 2026-08-31，用户要求在原 `or + 0.5` 产物之外，同时生成 `0.5/0.6 × chain/residue/or/and` 八组结果；所有参数相关文件统一进入 `held_out/split/held_out_<05|06>_<mode>/`。
- 本轮从 `Learn/CUMULATIVE@0e01739` 建立隔离实现分支 `codex/held-out-split-matrix`。实现把原 finalize 拆为一次共享边证据合并和八个轻量 split：共享根写 `pdb_edge_evidence.jsonl`、`stage2/edge_summary.json`，split 目录各自写冗余边、身份证、三个测试视图、summary 与完成事实。
- `classify_pdb_redundancy` 支持 `chain`、`residue`、`or`、`and` 四种模式；0.5 与 0.6 都使用包含边界。三个 matching 及四个双向 coverage 不随这些参数重算。
- `held_out_finalize.sh` 改为共享边证据任务；新增 `held_out_split_array.sh`，数组索引 0-7 显式对应八个目录。两项任务不建立自动依赖，先人工确认共享边任务终态，再提交 split 数组；正式提交为每任务 8 CPU、32 GB 内存。
- 旧根目录 `or + 0.5` 参数文件只在八组全部通过独立验收后精确移除；不建立兼容副本、硬链接或符号链接。新 `held_out_05_or` 必须与旧文件逐字节 `cmp` 一致。
- 主代理第一遍按文件顺序检查本轮全部修改函数的职责、位置、调用关系、嵌套与 Docstring；期间让共享边构造入口只返回 summary, 明确 `redundancy -> shared evidence -> selection` 的单向依赖, 并增加共享字段不随 split 漂移的测试。
- 主代理第二遍逐行核对三个科学函数和 split 产物构造中的非标量变量、形状符号、参数语义与 shell 变量注释；补全 `N_edge/N_held_out/N_full_test/N_test0/N_test1` 等符号, 拆开关键路径变量说明, 并确认本轮代码注释不含中文标点。
- 两遍自查后的 Windows 全套回归为 `21 passed, 1 skipped`；唯一跳过项仍是本机未安装 Gemmi。`compileall`、两个新 CLI 帮助、五份 shell 语法、`git diff --check` 与代码注释标点扫描均通过。三类独立三轮核查、双线 Git、服务器重跑与八组验收尚未开始。

## 实现与本地验证

- 已新增 `Data_Preprocessing/held_out/`，按 `catalog -> redundancy -> selection` 三条科学代码链和一个薄 CLI 组织；四个 shell 分别对应目录数组、目录合并、MMseqs2 数组和最终发布，没有自动依赖或重试。
- 第一遍主审按文件顺序检查了全部新增函数的职责、位置、调用方向、嵌套与 Docstring。期间把 MMseqs2 TSV 合并改为逐行读取，把 JSONL 输出改为逐行写临时文件后原子替换，并补上 `held_out_base` 与冻结 PDB identity 的完整一致性检查。
- 第二遍主审逐段检查了序列、体素资产、二分图匹配、双向 coverage、固定随机子流和身份证变量。科学变量均补充中文行内注释，代码注释与 Docstring 已统一使用英文标点。
- Windows 本地环境运行 `pytest` 得到 `16 passed, 1 skipped`；唯一跳过项是本机未安装 Gemmi 的 mmCIF 解析测试，必须在正式 Linux Conda 环境补跑。`compileall`、四个 shell 的语法检查和 `git diff --check` 均通过。

## 独立审查

主代理两遍自查完成后，由代码布局与 Git、中文注释、科学逻辑三名独立审查者各执行三轮全面核查；第三轮后只对已列问题做窄口径复核。

### 第 1 轮全面核查

- 布局与 Git 审查批准了当前模块依赖、函数位置、冷读分隔线和嵌套深度；要求在修复前保存独立审查前基线，并补全产物 Docstring、README 与四个显式步骤表述。
- 注释审查发现资产 Docstring 把 `union_mask` 误写为 `ligand_area`、类型/形状标点空格不统一、可配置维度被注释写死，以及若干非标量变量和外部 `TASK_PROJECT_ROOT` 缺少说明。
- 科学逻辑审查发现 Gemmi `row[index]` 保留 CIF 引号、高拷贝 entity 的 chain 笛卡尔积可能阻断全局合并、`and` 模式最强关系可能选到非冗余边，以及官方 FASTA smoke 不应声称验收 label chain 映射。
- 修复采用 Gemmi `row.str(index)` 解引号；用 entity chain-copy 容量上的稀疏整数 b-matching 数学等价替代候选 chain 笛卡尔积，并仍输出逐 chain 见证；关系摘要优先选择冗余见证；官方 smoke 明确只验收 entity identity 与序列。同步补全字段契约、四步命名、变量注释和 2,000-copy 回归测试。
- 修复后 Windows 本地回归为 `18 passed, 1 skipped`；唯一跳过项仍是需在正式 Linux Gemmi 环境补跑的 mmCIF 解析测试。`compileall`、四个 shell 语法和 diff 检查通过。

### 第 2 轮全面核查

- 布局与 Git 审查继续批准模块与函数布局以及真实实现提交时序；字段契约审查要求 README 和产物构造函数逐项展开序列状态、基础身份证、冗余边、最终身份证与两组 summary，并统一外部“四步”术语。
- 注释审查要求补充 entity 容量匹配的形状符号、整数容量与三种目标权重，说明 Gemmi `row.str` 的 CIF 解引号语义，并移除把可配置分片数写死为 12 的注释。
- 科学逻辑审查指出暴露参考 PDB 的序列失败会缩小实际去冗余范围，以及阈值 0 在无候选边时与判定公式不一致。经用户复核，全部失败率只保留为运行后的人工验收事实，不进入代码门控；`reference_redundant` 明确限定为成功序列目录的参考范围。PDB coverage 阈值契约收紧为 `(0, 1]`。两项均增加回归测试。
- 用户复核指出新增科学函数 Docstring 把多个字段压成了长段正文。主代理重新逐字核对 `code-comment-style-cn` 及其示例，把容量匹配、命中定向、PDB 边和身份证等关键结构统一改为“形状符号、输入参数、返回字段、科学约束”，每个条目只对应一个真实字段或子对象。
- 修复后 Windows 本地回归为 `20 passed, 1 skipped`；唯一跳过项仍是需在正式 Linux Gemmi 环境补跑的 mmCIF 解析测试。`compileall`、四个 shell 语法和 diff 检查通过。

### `full_test` 补充

- 用户在第三轮审查期间补充 `full_test`：保存满足质量、资产、序列、参考非冗余与 held-out 内部非冗余条件的完整贪心极大独立集，不应用 occurrence 数过滤；`test_0` 改为从该集合抽样，`test_1` 继续从 `test_0` 保序过滤。
- 现有贪心算法已经遍历全部合格 PDB，并为每个拒绝项保存一个已接受的直接冲突邻居，因此其接受集合天然满足极大性。本次只把该集合明确写盘并补充身份证排名、嵌套关系和回归检查，没有增加最大独立集求解器或运行门控。
- 补充提交前重新完成两遍主审。第一遍按文件和函数顺序确认贪心职责不变、`sample_test_0` 只改输入命名、最终入口只新增一个同级视图且没有增加嵌套或隐藏调用；第二遍逐行核对 `full_test_ids`、紧凑排名、三个成员集合、共享视图字段和测试中的冲突集合，补齐形状与具体语义注释。
- 补充后的 Windows 本地回归仍为 `20 passed, 1 skipped`；新增断言直接检查 full_test 的内部独立性、对全部合格未入选项的极大性见证、`test_1 ⊆ test_0 ⊆ full_test` 和身份证排名。`compileall` 与四个 shell 语法检查通过。
- 服务器首次全量 finalize 在完整写出 PDB 边后得到 `full_test=124`，随后因 test_0 固定要求 200 个而失败。该数量要求改为目标上限：test_0 抽取 200 与 full_test 成员数中的较小值，仍只来自 full_test；不改变 `or + 0.5`、固定种子、极大独立集或 occurrence 条件。
- 修复后 Windows 本地选择测试为 `5 passed`，全套为 `21 passed, 1 skipped`；完整 finalize 合成测试已直接覆盖目标 200 大于 full_test 规模的分支，并核对 test_0 身份证排名。

### 第 3 轮与窄口径复核

- 第 3 轮旧端点核查确认失败计数、官方 FASTA smoke 和 `_COMPLETE` 都只记录事实而不参与发布门控；参考失败范围、PDB coverage 参数、三种匹配目标、四个执行步骤与既定契约一致。
- 用户追加 `full_test` 后，三名审查者只复核 `d832f47..d7072e0` 增量。科学逻辑审查批准，并额外穷举最多 5 个节点的全部简单无向图与 3 个种子，确认独立性、极大性和直接拒绝见证均成立。
- 注释审查只要求显式定义两处 `N_full_test` 并写明 `full_test.json::pdb_ids` 长度；布局与 Git 审查只要求同步两个文档中的提交事实。修订保存为 `6f07be8`，两名审查者随后按原问题窄口径复核并批准。

## Git 双线

- 实现线已提交独立审查前基线 `5ac2c97`、第一轮修复 `131991f`、第二轮修复 `d832f47`、`full_test` 补充 `d7072e0` 和窄口径修复 `6f07be8`。Learn 历史仍待按人类理解顺序重建并核对 tree 等价。

## 服务器执行与验收

正式输出根固定为 `/storage/penghongen/AdaLigand/held_out`。MMseqs2 已安装；目录数组 Job `366076`、目录合并与官方 FASTA smoke Job `366090`、MMseqs2 数组 Job `366094` 均已完成。首次 finalize Job `366110` 在完整写出 PDB 边后因旧的固定 200 契约失败；修复版 finalize Job `366127` 已完成，项目外审计 Job `366153` 已通过。

旧 `or + 0.5` 正式结果为 622,986 条 PDB 边、388,797 条冗余边、315 个基础合格 PDB、124 个 full_test/test_0 成员和 108 个 test_1 成员。当前开放事项是追加八组合 split、完成逐组合验收并在全部通过后移除根目录旧参数副本。
