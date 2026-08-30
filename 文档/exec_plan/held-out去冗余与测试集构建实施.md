# Held-out 去冗余与测试集构建实施记录

本文记录 `文档/规划文档/held-out去冗余与测试集构建.md` 的实际实现、验证、审查、Git 双线和服务器运行证据。科学定义和字段解释不在此重复。

## 当前状态

- 2026-08-30：从唯一最新且工作树干净的 `Learn/CUMULATIVE@e90530c` 建立隔离实现分支 `codex/held-out-sequence-redundancy`。
- 已核实 RCSB 当前官方 FASTA 为 per-entity 输出，入口为 `/fasta/entry/<pdb_id>/download`；header 使用 `<pdb_id>_<entity_id>` 并附 chain。
- 已核实 MMseqs2 官方参数：`--cov-mode 0` 表示同时约束 query 和 target coverage；`--alignment-mode 3` 输出真实 identity。
- 已核实 MMseqs2 `fident` 是 `[0,1]` 的 identical-match fraction，`pident` 才是百分数；正式 TSV 因此使用 `fident` 并按 `0.30/0.80` 读取。
- 已核实现有冻结输入：完整 PDB 22,386，暴露参考 14,017，held-out 2,497；正式数据根为 `/storage/penghongen/AdaLigand/Ori_Data`。

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

## Git 双线

- 实现线已提交独立审查前基线 `5ac2c97`，后续审查修复另存提交；Learn 历史仍待按人类理解顺序重建并核对 tree 等价。

## 服务器执行与验收

正式输出根固定为 `/storage/penghongen/AdaLigand/held_out`。待 MMseqs2 安装、同步、四个显式步骤完成后回填 Job、版本、结果计数和失败清单。
