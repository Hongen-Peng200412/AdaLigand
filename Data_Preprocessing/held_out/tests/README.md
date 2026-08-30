# 测试边界

本目录用小型合成数据固定长度阈值、entity 多 chain、U/T 等价、MMseqs2 双向 coverage、一对一匹配、三个不同匹配目标、PDB `or/and` 聚合、冲突图极大独立集、零可比 chain 和三个测试视图的嵌套关系。

建议按以下顺序阅读：

1. `test_catalog.py`：序列规范、类别和长度边界、官方 FASTA entity 对照、资产 80³ 边界。
2. `test_mmcif_parser.py`：Gemmi 解引号、`_entity_poly` 序列和 `_struct_asym` label chain 外键。
3. `test_redundancy.py`：MMseqs2 参数、entity 容量匹配、三目标 coverage 与 `or/and`。
4. `test_selection.py`：冲突图极大独立集、冗余直接见证和 `test_1 ⊆ test_0 ⊆ full_test` 关系。

生产代码组织见 `../held_out_pipeline/README.md`，完整字段契约见 `../README.md`。

真实 RCSB FASTA 与真实 MMseqs2 二进制依赖网络和 Linux 工具，不伪装成 Windows 单元测试；它们分别由正式步骤 2 和步骤 3 产生可验收输出。
