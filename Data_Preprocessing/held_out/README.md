# AdaLigand held-out 去冗余

本目录把冻结的 PDB/EMDB 数据整理成一份可复用的 polymer entity 序列目录，再从日期留出的 2,497 个 PDB 生成统一身份证、序列冗余关系和三个测试视图。科学定义以 `../../文档/规划文档/held-out去冗余与测试集构建.md` 为准；本 README 只说明当前代码入口和盘上字段。

## 目录组织

- `held_out_pipeline/catalog.py`：解析 mmCIF、审计 held-out 质量与资产、合并序列目录、生成 FASTA、对照 RCSB 官方 FASTA。
- `held_out_pipeline/redundancy.py`：运行 MMseqs2、读取真实 identity 与双向 coverage、在 entity 容量图计算三个一对一匹配并展开最终 chain 见证。
- `held_out_pipeline/selection.py`：汇总参考集和 held-out 内部关系，构建身份证、固定种子贪心极大独立集 `full_test`，再派生 `test_0` 与 `test_1`。
- `held_out_pipeline/cli.py`：四个显式步骤的薄命令行入口，不隐式串联 Job。
- `tests/`：纯合成契约测试；真实 RCSB FASTA 和 MMseqs2 smoke 在服务器步骤执行。
- `../../训练与运行/sh/held_out_*.sh`：两个数组步骤与两个合并步骤的正式任务脚本。

建议按 `READING.md` 的顺序阅读。

## 输入

正式运行读取 `/storage/penghongen/AdaLigand/Ori_Data` 下的既有冻结资产：

- `raw/pair_list.jsonl`：完整 PDB/EMDB 对照；按 `pdb_id` 去重得到 22,386 个序列目录身份。
- `raw/rcsb_mmcif/{pdb_id}.cif`：沉积结构与 polymer entity 全长序列。
- `stage1_preparation_box_pool_3/split/{train,validation,calibration,held_out}.json`：冻结 occurrence 级划分。
- `stage1_preparation_box_pool_3/split/pdb_audit.jsonl`：首次 EMDB 发布时间。
- `stage1_preparation_box_pool_3/split/pdb_split/*.json`：纯 PDB identity 列表。
- `density/`、`parse/`、`labels/`：held-out 资产审计输入。

代码不读取坐标残基重建序列。`_entity_poly.pdbx_seq_one_letter_code_can` 只去除空白并转为大写；entity 到 chain 使用 `_struct_asym.entity_id -> _struct_asym.id`。

## 四个显式执行步骤

步骤 1 是目录数组任务，共 12 个分片，每个数组元素内部使用 `SLURM_CPUS_PER_TASK` 个进程：

```bash
bash 训练与运行/submit_task.sh --sh held_out_catalog_array.sh --resource cpu --cpus 8 --array 0-11 --time 04:00:00
```

步骤 2 合并目录、生成自然 FASTA 与 MMseqs2 FASTA，并对三个真实 PDB 调用 RCSB 官方 FASTA：

```bash
bash 训练与运行/submit_task.sh --sh held_out_catalog_finalize.sh --resource cpu --cpus 8 --time 02:00:00
```

步骤 3 用数组任务分别运行 protein 与 nucleic MMseqs2：

```bash
bash 训练与运行/submit_task.sh --sh held_out_mmseqs_array.sh --resource cpu --cpus 8 --array 0-11 --time 12:00:00
```

步骤 4 合并并按 PDB coverage 选择测试身份。shell 的前两个可选参数依次为聚合模式和阈值；第一版省略参数即使用 `or 0.5`：

```bash
bash 训练与运行/submit_task.sh --sh held_out_finalize.sh --resource cpu --cpus 8 --time 04:00:00 -- or 0.5
```

这些命令不建立自动依赖。步骤 2 正常执行到末尾时写出 `stage1/_COMPLETE`，步骤 4 正常执行到末尾时写出 `stage2/_COMPLETE`。完成标记只记录步骤执行事实，后续代码不读取它们作为门控；提交下一步前由人工核对上一份 summary。

## 主要产物

输出根固定为 `/storage/penghongen/AdaLigand/held_out`。

### 序列目录

`sequence_catalog.jsonl` 每行是一个 polymer entity：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `sequence_id` | string | RCSB 风格的 `<PDB_ID>_<entity_id>`，用于 FASTA 与 MMseqs2 对齐。 |
| `pdb_id` | string | 小写 PDB identity。 |
| `entity_id` | string | mmCIF polymer entity identity。 |
| `polymer_type` | string | 原始 `_entity_poly.type`。 |
| `sequence_class` | string | `protein`、`rna`、`dna`、`hybrid` 或 `other`。 |
| `sequence` | string | 仅去空白并大写的沉积规范全长序列。 |
| `length` | integer | `sequence` 字符数。 |
| `label_asym_ids` | list[string] | 指向该 entity 的全部 `_struct_asym.id`。 |
| `comparable` | boolean | protein 至少 30 aa，或核酸至少 20 nt。 |

`pdb_sequence_status.jsonl` 每个完整 PDB 一行，字段为小写 `pdb_id`、取值 `ok`/`missing_mmcif`/`parse_error` 的 `status`、`error` 和 `entity_count`。`status=ok` 时 `error=null`；失败时 `error` 是缺失 mmCIF 路径或异常类型与文本。没有 polymer entity 仍是 `ok`。

`held_out_base.jsonl` 固定覆盖全部 held-out PDB，每行字段如下：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `pdb_id` | string | 小写 held-out PDB identity。 |
| `emdb_ids` | list[string] | 该 PDB 在冻结对照中出现的全部 EMDB identity。 |
| `first_map_release` | string 或 null | 首次 EMDB 发布时间。 |
| `quality` | object | `map_resolution` 为 float 或 null，单位 Å；`cc_contour` 为 float 或 null；`passed` 仅在二者存在且严格满足 `<4.0`、`>0.65` 时为 true。 |
| `ligands` | object | `total_count` 为 occurrence 总数；`type_counts` 固定含 `ion`、`nucleotide_like`、`other`、`peptide_like`、`small_molecule`、`sugar` 六个整数键；`strict_1_100_passed` 表示严格 `1 < total_count < 100`。 |
| `assets` | object | `status` 取 `eligible`、`short_map`、`missing_file` 或 `invalid`；`passed` 仅对 eligible 为 true；`shape_zyx` 为按 Z、Y、X 排列的三个整数，无法取得合法形状时为 null；`detail` 为成功时空字符串或失败定位文本。 |
| `sequence` | object | `status` 与 `error` 语义同 `pdb_sequence_status.jsonl`；顶层含 `entity_count`、`chain_count`、`residue_count`、`comparable_entity_count`、`comparable_chain_count`、`comparable_residue_count` 六个整数；`by_class` 固定含 `protein`、`rna`、`dna`、`hybrid`、`other` 五类，每类重复这六个计数字段。 |

`held_out_sequence_failures.jsonl` 是其中 `sequence.status` 为 `missing_mmcif` 或 `parse_error` 的完整记录子集。

`fasta/natural/{protein,rna,dna,hybrid}.fasta` 保留自然序列。`fasta/mmseqs/` 保存 12 份 held-out query 和完整 target；nucleic FASTA 只在这个派生视图把 `U` 改为 `T`。

`official_fasta_smoke.json` 保存 `requested_count`、实际 `pdb_ids`、总 `passed` 和 `results`。每个 result 含 `pdb_id`、`source_url`、`passed` 与逐 entity 的 `sequence_id`、本地/官方序列和 `equal`。样本优先覆盖 protein 与核酸；本轮 smoke 只验收 entity identity 和沉积全长序列，不声称核对官方 header 中的 author chain 文本。

### 冗余边

`qualifying_entity_hits.jsonl` 保存通过类别 identity 和双向 0.80 coverage 的去重 entity 对。每行包含 `relation`、PDB/entity/sequence identity A/B、两侧 `label_asym_ids` 与全长、`sequence_kind`、`identity`、`coverage_A`、`coverage_B`、`alignment_length` 和 `evalue`。

`redundancy_edges.jsonl` 只保存至少存在一条高重复 chain 边的 PDB 对：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `relation` | string | `reference` 或 `held_out_internal`。 |
| `pdb_A`、`pdb_B` | string | 当前边两端；reference 边的 A 固定为 held-out。 |
| `comparable_chain_count_A`、`comparable_chain_count_B` | integer | 各侧进入比对和 chain coverage 分母的 chain instance 数。 |
| `comparable_residue_count_A`、`comparable_residue_count_B` | integer | 各侧 comparable chain 沉积全长序列长度之和。 |
| `chain_A`、`chain_B` | float | 最大 cardinality 一对一匹配数除以各侧可比 chain 数。 |
| `residue_A`、`residue_B` | float | 分别按 A 侧和 B 侧 chain 长度最大化的一对一匹配残基数比例。 |
| `chain_matching` | list[object] | 最大 chain 数匹配及其 chain/entity 见证。 |
| `residue_A_matching`、`residue_B_matching` | list[object] | 两个残基目标各自的最优匹配见证。 |
| `chain_pass`、`residue_pass` | boolean | 两级 coverage 是否达到当前阈值。 |
| `pdb_coverage_mode`、`pdb_coverage_threshold` | string、float | 生成该边时使用的 `or`/`and` 模式和 `(0, 1]` 阈值。 |
| `redundant` | boolean | 当前 `pdb_coverage_mode` 与阈值的最终判断。 |

三类 matching 的每条见证均含 `chain_A`、`chain_B`、`entity_A`、`entity_B`、`sequence_id_A`、`sequence_id_B`、`length_A`、`length_B`、`sequence_kind`、`identity`、`coverage_A` 和 `coverage_B`。实现先在 entity 容量图上求解数学等价的一对一 chain matching，再只展开被选中的 chain 见证，不物化高拷贝 entity 的完整 chain 笛卡尔积。

`or` 表示 `chain_pass or residue_pass`，`and` 表示 `chain_pass and residue_pass`。A/B 方向始终保留，模式不会改变四个原始 coverage。

### Held-out 身份证

`held_out_identity.jsonl` 固定包含全部 2,497 个 held-out PDB。每行字段如下：

| 字段 | 类型 | 含义与子字段 |
| --- | --- | --- |
| `schema`、`schema_version` | string、integer | 身份证 schema identity 与版本。 |
| `pdb_id`、`emdb_ids`、`first_map_release` | string、list[string]、string 或 null | PDB/EMDB/日期身份。 |
| `quality` | object | 与 `held_out_base.jsonl` 相同；resolution 单位为 Å，缺失数值为 null。 |
| `assets` | object | 与 `held_out_base.jsonl` 相同；含四种 status、passed、ZYX 顺序的可空形状与 detail。 |
| `ligands` | object | 与 `held_out_base.jsonl` 相同；含总数、六个具名类别计数与严格 occurrence 过滤布尔值。 |
| `sequence` | object | 与 `held_out_base.jsonl` 相同；含状态、可空错误、六个总计字段和五类各自的六个计数字段。 |
| `redundancy` | object | mode、threshold，参考/内部 edge 数与 redundant edge 数，`reference_redundant`，以及可空 `strongest_reference_edge`、`strongest_internal_edge`。`reference_redundant` 只针对 `pdb_sequence_status.status=ok` 的参考目录；实际失败数见 stage1 summary。压缩见证字段见下文。 |
| `selection` | object | `base_eligible`；`exclusion_reasons` 可含 `quality_failed`、`asset_failed`、`sequence_failed`、`reference_redundant`；可空 `greedy_rank`、`full_test` 布尔值、可空 `full_test_rank`、可空 `rejected_by`/`rejection_edge`、`test_0`/`test_1` 布尔值及可空排名。 |

压缩关系见证为 null 或 object；object 含 `other_pdb_id`、`relation`、四个原始 coverage、`max_coverage`、`chain_pass`、`residue_pass` 和 `redundant`。存在冗余边时优先选择冗余见证，保证参考排除原因与身份证见证一致。

三个测试视图的准确字段是：

| 文件 | 字段 |
| --- | --- |
| `full_test.json` | `schema_version`、`pdb_coverage_mode`、`pdb_coverage_threshold`、`seed`、`name="full_test"`、`occurrence_filter=null`、按贪心接受顺序保存的全部 `pdb_ids`。该集合两两无内部冗余边；每个未进入集合的合格 PDB 都与一个已进入成员直接冲突，因此它是极大独立集，但不声称是基数最大的独立集。 |
| `test_0.json` | 同一版本与选择参数、`name="test_0"`、`occurrence_filter=null`、`parent="full_test"`、从 full_test 无放回抽取的 200 个 `pdb_ids`。 |
| `test_1.json` | 同一版本与选择参数、`name="test_1"`、`occurrence_filter="1 < total_count < 100"`、`parent="test_0"`、从 test_0 保序过滤得到的 `pdb_ids`。 |

三个视图满足 `test_1 ⊆ test_0 ⊆ full_test`。`full_test` 与 `test_0` 都不应用 occurrence 数过滤。

### 汇总与完成标记

`stage1/summary.json` 字段为 `catalog_pdb_count`、`catalog_entity_count`、`reference_pdb_count`、`reference_sequence_failure_count`、`held_out_pdb_count`、`held_out_sequence_failure_count`、`sequence_status_counts`、`protein_target_entity_count`、`nucleic_target_entity_count`、`alignment_shard_count`、`official_fasta_smoke_passed`。

`stage2/summary.json` 字段为 `raw_qualifying_alignment_count`、`oriented_entity_hit_count`、`pdb_edge_count`、`redundant_pdb_edge_count`、`relation_counts`、`mode`、`threshold`、`held_out_pdb_count`、`base_eligible_count`、`full_test_count`、`test_0_count`、`test_1_count`、`exclusion_reason_counts`、`seed`。

步骤 1 的分片 summary 含 `shard_index`、`shard_count`、`assigned_pdb_count`、`held_out_pdb_count`、`sequence_status_counts`、`workers`、`output`。步骤 3 的分片 summary 含 `shard_index`、`threads`、`mmseqs_version` 和两项 `commands`；每项 command 含 `sequence_kind`、`status`、完整命令与结果路径。对应步骤正常结束后分别写 `stage1/_COMPLETE` 与 `stage2/_COMPLETE`。分片中间结果位于 `stage1/shards/` 和 `stage2/mmseqs/`，不是下游正式接口。

## 失败与重跑

held-out 的 `missing_mmcif` 和 `parse_error` 是未预期序列失败，但失败数不参与代码门控。人工验收时，最多 74 个意味着不因这些失败修改代码或重跑；达到 75 个时先诊断再决定。暴露参考失败单独计入 `reference_sequence_failure_count`；因此有失败时只能声称已对序列状态为 `ok` 的参考 PDB 完成去冗余。质量、资产、短链和零可比 chain 不属于处理失败。

正式运行不自动重试、不自动换参数、不自动清理旧产物。只有未预期失败超过 held-out 的 3% 时，才在诊断后考虑修改代码与重跑。
