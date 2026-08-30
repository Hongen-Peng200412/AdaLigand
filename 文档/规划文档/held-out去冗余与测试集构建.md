# Held-out 去冗余与测试集构建

本文是 AdaLigand held-out PDB 身份、序列冗余和测试集视图的当前主规格。本文负责科学定义、选择顺序和最终产物，不负责记录具体 Job、临时故障或 Git 提交；这些事实写入 `文档/exec_plan/held-out去冗余与测试集构建实施.md`。代码旁字段契约见 `Data_Preprocessing/held_out/README.md`。

## 范围

本轮从冻结的 22,386 个 PDB 建立 polymer entity 序列目录，以 train、validation、calibration 合计 14,017 个 PDB 作为已暴露参考，以日期留出的 2,497 个 PDB 作为 held-out 候选。当前只完成序列去冗余、统一身份证和 `test_0`、`test_1` 两个身份视图。

ESM2、Luca、CryoAtom2 的真实 smoke，残基—原子映射、残基内原子平均坐标、ESM2 残基嵌入与空间位置对齐，以及密度图加序列的 CryoAtom2 推理属于后续范围。本轮保留稳定的 `pdb_id + entity_id + label_asym_id` 身份，未来残基位置统一使用 mmCIF `label_seq_id`，但不提前实现这些模型或映射。

## 序列目录

- 每个 polymer entity 只保存一次沉积全长序列，来源固定为冻结 mmCIF 的 `_entity_poly.pdbx_seq_one_letter_code_can`；只删除空白并转为大写，不从坐标残基反推或补齐序列。
- entity 到 chain 的关系来自 `_struct_asym.entity_id -> _struct_asym.id`，其中 `_struct_asym.id` 是 `label_asym_id`。
- protein 是全部 `polypeptide*`；RNA、DNA 和 DNA/RNA hybrid 分别保留自然类别；其余 polymer 记录为 `other`，但不参与本轮比对。
- 自然 FASTA 不改写序列。用于核酸比对的派生 FASTA 把 `U` 转成 `T`，使 RNA 与 DNA 的相同碱基可直接比较。
- protein 长度至少 30 aa、RNA/DNA/hybrid 长度至少 20 nt 才参与序列比对和 PDB coverage 分母。短链仍保存在目录和身份证统计中。
- 真实 smoke 从本地目录选择少量 protein、nucleic acid 和多 chain entity 代表，逐 entity 对照 RCSB 官方 `/fasta/entry/<pdb_id>/download` 结果。任何序列不一致都作为 smoke 失败报告。

## chain 高重复边

MMseqs2 使用真实 alignment identity，即 `--alignment-mode 3 --seq-id-mode 0`。coverage 必须同时覆盖 query 和 target，因此使用 `-c 0.8 --cov-mode 0`，并在读取结果时再次核对 `qcov >= 0.8` 与 `tcov >= 0.8`。

- protein：identity 至少 0.30，双向 coverage 至少 0.80。
- RNA、DNA 和 hybrid：统一作为核酸比较，identity 至少 0.80，双向 coverage 至少 0.80。
- entity 命中展开为其全部 `label_asym_id` chain 对。一个 PDB 对内的 chain coverage 必须通过一对一二分图匹配计算，不能让同一条 chain 重复覆盖多条 chain。

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

2,497 个 held-out PDB 全部进入统一 JSONL 身份证。每条记录包含 PDB/EMDB/日期、`map_resolution`、`cc_contour`、资产状态、六类配体计数、polymer/entity/chain/residue 统计、序列状态、参考集与 held-out 内部冗余摘要、贪心接受或拒绝状态，以及两个测试视图标记。完整 PDB 对关系单独保存在冗余边文件，身份证只保存摘要和直接见证。

正式候选依次要求：

1. `map_resolution < 4.0` 且 `cc_contour > 0.65`；
2. Stage1 当前资产契约完整，完整图三个维度均至少为 80；
3. mmCIF 序列解析成功；零可比 chain 不属于失败；
4. 与 14,017 个已暴露参考 PDB 没有当前参数下的冗余边。

在剩余 held-out 冲突图上，以 `SeedSequence(3407, spawn_key=(0,))` 产生固定贪心顺序，构建任意两成员之间均无冗余边的独立集。每个拒绝项保存已接受邻居作为见证。

从完整独立集用 `SeedSequence(3407, spawn_key=(1,))` 无放回抽取 200 个 PDB 得到 `test_0`。`test_1` 只保留 `test_0` 中总 occurrence 数严格满足 `1 < n < 100` 的 PDB，因此必为 `test_0` 子集且数量不预设。

## 执行边界

执行分成两个显式阶段：第一阶段用 12 个数组任务解析序列和审计 held-out，随后单任务合并目录、生成 FASTA 并运行 RCSB 官方 FASTA smoke；第二阶段用 12 个数组任务运行 protein 与 nucleic MMseqs2，随后单任务生成关系、身份证和测试视图。每个数组元素使用 8 CPU，不建立自动依赖、自动重试或多层状态机。

只有 held-out 中未预期的序列处理失败计入重跑门槛。失败数不超过 74 时保留失败清单并继续；达到 75 时停止正式发布并先诊断。质量不通过、资产不通过、短链和零可比 chain 都是预期状态，不计入该门槛。
