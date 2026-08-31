# Held-out 去冗余与测试集构建

本文是 AdaLigand held-out PDB 身份、序列冗余和测试集视图的当前主规格。本文负责科学定义、选择顺序和最终产物，不负责记录具体 Job、临时故障或 Git 提交；这些事实写入 `文档/exec_plan/held-out去冗余与测试集构建实施.md`。代码旁字段契约见 `Data_Preprocessing/held_out/README.md`。

## 范围

本轮从冻结的 22,386 个 PDB 建立 polymer entity 序列目录，以 train、validation、calibration 合计 14,017 个 PDB 作为已暴露参考，以日期留出的 2,497 个 PDB 作为 held-out 候选。当前只完成序列去冗余、统一身份证和 `full_test`、`test_0`、`test_1` 三个身份视图。

ESM2、Luca、CryoAtom2 的真实 smoke，残基—原子映射、残基内原子平均坐标、ESM2 残基嵌入与空间位置对齐，以及密度图加序列的 CryoAtom2 推理属于后续范围。本轮保留稳定的 `pdb_id + entity_id + label_asym_id` 身份，未来残基位置统一使用 mmCIF `label_seq_id`，但不提前实现这些模型或映射。

## 序列目录

- 每个 polymer entity 只保存一次沉积全长序列，来源固定为冻结 mmCIF 的 `_entity_poly.pdbx_seq_one_letter_code_can`；只删除空白并转为大写，不从坐标残基反推或补齐序列。
- entity 到 chain 的关系来自 `_struct_asym.entity_id -> _struct_asym.id`，其中 `_struct_asym.id` 是 `label_asym_id`。
- protein 是全部 `polypeptide*`；RNA、DNA 和 DNA/RNA hybrid 分别保留自然类别；其余 polymer 记录为 `other`，但不参与本轮比对。
- 自然 FASTA 不改写序列。用于核酸比对的派生 FASTA 把 `U` 转成 `T`，使 RNA 与 DNA 的相同碱基可直接比较。
- protein 长度至少 30 aa、RNA/DNA/hybrid 长度至少 20 nt 才参与序列比对和 PDB coverage 分母。短链仍保存在目录和身份证统计中。
- 真实 smoke 从本地目录选择少量 PDB，优先覆盖 protein 与 nucleic acid，逐 entity 对照 RCSB 官方 `/fasta/entry/<pdb_id>/download` 结果。任何 entity identity 或序列不一致都作为 smoke 失败；本轮不把官方 header 中的 author chain 文本当作 `label_asym_id` 验收来源。

## chain 高重复边

MMseqs2 使用真实 alignment identity，即 `--alignment-mode 3 --seq-id-mode 0`。coverage 必须同时覆盖 query 和 target，因此使用 `-c 0.8 --cov-mode 0`，并在读取结果时再次核对 `qcov >= 0.8` 与 `tcov >= 0.8`。

- protein：identity 至少 0.30，双向 coverage 至少 0.80。
- RNA、DNA 和 hybrid：统一作为核酸比较，identity 至少 0.80，双向 coverage 至少 0.80。
- 一条 entity 命中在科学定义上连接两侧全部 `label_asym_id` chain copies。实现以 entity 的 chain copy 数作为容量求解数学等价的二分图匹配，只展开最终匹配见证，不物化高拷贝 entity 的完整笛卡尔积。一个 PDB 对内不能让同一条 chain 重复覆盖多条 chain。

每个 PDB 对分别计算三个最优匹配：最大 chain 数、最大 A 侧匹配残基数、最大 B 侧匹配残基数。由此得到 `chain_A`、`chain_B`、`residue_A`、`residue_B` 四个双向 coverage。

## PDB 冗余判定

给定阈值 $t$，先定义：

- `chain_pass = max(chain_A, chain_B) >= t`；
- `residue_pass = max(residue_A, residue_B) >= t`。

聚合模式可在命令行切换为 `or` 或 `and`：

- `or`：`chain_pass or residue_pass`；
- `and`：`chain_pass and residue_pass`。

第一版固定运行 `mode=or`、`t=0.5`，但实现不得把模式或阈值写死。关系文件保存四个原始 coverage、三组最优匹配和当前参数下的布尔判定，使未来改变判定参数时不需要重新解释 chain 匹配含义。

## Held-out 身份证与选择

2,497 个 held-out PDB 全部进入统一 JSONL 身份证。每条记录包含 PDB/EMDB/日期、`map_resolution`、`cc_contour`、资产状态、六类配体计数、polymer/entity/chain/residue 统计、序列状态、参考集与 held-out 内部冗余摘要、贪心接受或拒绝状态，以及三个测试视图标记。完整 PDB 对关系单独保存在冗余边文件，身份证只保存摘要和直接见证。

正式候选依次要求：

1. `map_resolution < 4.0` 且 `cc_contour > 0.65`；
2. Stage1 当前资产契约完整，完整图三个维度均至少为 80；
3. mmCIF 序列解析成功；零可比 chain 不属于失败；
4. 与 14,017 个已暴露参考 PDB 没有当前参数下的冗余边。

在剩余 held-out 冲突图上，以 `SeedSequence(3407, spawn_key=(0,))` 产生固定贪心顺序，依次接受与已有成员均不冲突的 PDB。遍历全部合格 PDB 后，完整接受集合写为 `full_test`。任意两个成员之间均无冗余边；每个拒绝项都保存一个已接受的直接冲突邻居，因此再加入任何一个被拒绝 PDB 都会破坏独立性。`full_test` 由此是极大独立集，但不保证是基数最大的独立集。

从 `full_test` 用 `SeedSequence(3407, spawn_key=(1,))` 无放回抽取至多 200 个 PDB 得到 `test_0`；full_test 少于 200 个时取其全部成员。`test_1` 只保留 `test_0` 中总 occurrence 数严格满足 `1 < n < 100` 的 PDB，因此 `test_1 ⊆ test_0 ⊆ full_test`。`full_test` 与 `test_0` 都不按 occurrence 数过滤；`test_1` 数量不预设。

## 执行边界

执行有两组产物、四个显式步骤：目录数组、目录合并与 RCSB smoke、MMseqs2 数组、关系/身份证/测试视图合并。两个数组步骤各使用 12 个任务，每个数组元素使用 8 CPU。步骤间不建立自动依赖、自动重试或多层状态机。

失败率只用于运行后的人工验收，不写成代码门控。held-out 中未预期的序列处理失败不超过 74 个时不因这些失败修改代码或重跑；达到 75 个时先诊断，再决定是否修改代码与重跑。质量不通过、资产不通过、短链和零可比 chain 都是预期状态，不计入该失败率。
