# 阅读顺序

本文件只给出代码阅读顺序。字段与运行入口见同目录 `README.md`，科学取舍见 `../../文档/规划文档/held-out去冗余与测试集构建.md`。

1. `held_out_pipeline/catalog.py`：先看 mmCIF 的 entity、chain、序列身份，再看 held-out 质量和资产事实如何进入步骤 1 分片，最后看合并 FASTA 与官方 smoke。
2. `held_out_pipeline/redundancy.py`：先看 MMseqs2 命令参数，再看 entity 命中怎样进入容量图和三个一对一匹配，最后看不含 mode/threshold 的共享 PDB 边证据。
3. `held_out_pipeline/selection.py`：先看 chain/residue/or/and 怎样应用于共享证据，再看参考冗余排除、内部冲突图、固定种子贪心极大独立集 `full_test`、至多 200 项 `test_0` 抽样和身份证回填。
4. `held_out_pipeline/cli.py`：最后看五个显式命令如何把前三个模块连接起来。
5. `tests/`：按 `test_catalog.py`、`test_mmcif_parser.py`、`test_redundancy.py`、`test_selection.py` 阅读边界例子。
