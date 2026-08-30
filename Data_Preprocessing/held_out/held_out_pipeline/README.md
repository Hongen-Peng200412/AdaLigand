# 包内职责

本包只有三条科学代码链：`catalog` 产生稳定序列身份与 held-out 基础事实，`redundancy` 产生 PDB 对 coverage，`selection` 把事实和关系合成身份证与测试视图。`cli` 只解析参数，不保存另一套科学规则。

依赖方向固定为 `cli -> catalog/redundancy/selection`、`selection -> redundancy`。`catalog` 不依赖去冗余或选择；`redundancy` 不读取质量与配体规则；`selection` 不重新解析 mmCIF 或重跑 MMseqs2。

推荐阅读顺序见 `../READING.md`。输入、命令、盘上产物和字段契约统一见 `../README.md`；本文件不复制另一套科学阈值。
