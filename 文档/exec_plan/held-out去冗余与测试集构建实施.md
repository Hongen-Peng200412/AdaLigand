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

待主代理两遍自查完成后，由代码布局与 Git、中文注释、科学逻辑三名独立审查者各执行三轮全面核查；第三轮后只对已列问题做窄口径复核。

## Git 双线

待实现提交与 Learn 历史重建完成后回填端点和 tree 等价证据。

## 服务器执行与验收

正式输出根固定为 `/storage/penghongen/AdaLigand/held_out`。待 MMseqs2 安装、同步、两阶段 Job 完成后回填 Job、版本、结果计数和失败清单。
