# AdaLigand held-out 去冗余

本目录把冻结的 PDB/EMDB 数据整理成一份可复用的 polymer entity 序列目录，再从日期留出的 2,497 个 PDB 生成统一身份证、序列冗余关系和两个测试视图。科学定义以 `../../文档/规划文档/held-out去冗余与测试集构建.md` 为准；本 README 只说明当前代码入口和盘上字段。

## 目录组织

- `held_out_pipeline/catalog.py`：解析 mmCIF、审计 held-out 质量与资产、合并序列目录、生成 FASTA、对照 RCSB 官方 FASTA。
- `held_out_pipeline/redundancy.py`：运行 MMseqs2、读取真实 identity 与双向 coverage、把 entity 命中展开为 chain 边并计算三个一对一匹配。
- `held_out_pipeline/selection.py`：汇总参考集和 held-out 内部关系，构建身份证、固定种子独立集、`test_0` 与 `test_1`。
- `held_out_pipeline/cli.py`：四个显式阶段的薄命令行入口，不隐式串联 Job。
- `tests/`：纯合成契约测试；真实 RCSB FASTA 和 MMseqs2 smoke 在服务器阶段执行。
- `../../../训练与运行/sh/held_out_*.sh`：两个数组阶段与两个合并阶段的正式任务脚本。

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

## 四个显式阶段

第一阶段数组任务为 12 个分片，每个数组元素内部使用 `SLURM_CPUS_PER_TASK` 个进程：

```bash
bash 训练与运行/submit_task.sh --sh held_out_catalog_array.sh --resource cpu --cpus 8 --array 0-11 --time 04:00:00
```

第一阶段合并目录、生成自然 FASTA 与 MMseqs2 FASTA，并对三个真实 PDB 调用 RCSB 官方 FASTA：

```bash
bash 训练与运行/submit_task.sh --sh held_out_catalog_finalize.sh --resource cpu --cpus 8 --time 02:00:00
```

第二阶段数组任务分别运行 protein 与 nucleic MMseqs2：

```bash
bash 训练与运行/submit_task.sh --sh held_out_mmseqs_array.sh --resource cpu --cpus 8 --array 0-11 --time 12:00:00
```

第二阶段合并并按 PDB coverage 选择测试身份。shell 的前两个可选参数依次为聚合模式和阈值；第一版省略参数即使用 `or 0.5`：

```bash
bash 训练与运行/submit_task.sh --sh held_out_finalize.sh --resource cpu --cpus 8 --time 04:00:00 -- or 0.5
```

这些命令不建立自动依赖。只有确认上一阶段 `_COMPLETE` 与 summary 后才提交下一阶段。

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

`pdb_sequence_status.jsonl` 每个完整 PDB 一行，保存 `ok`、`missing_mmcif` 或 `parse_error`，以及 entity 数。没有 polymer entity 仍是 `ok`。

`fasta/natural/{protein,rna,dna,hybrid}.fasta` 保留自然序列。`fasta/mmseqs/` 保存 12 份 held-out query 和完整 target；nucleic FASTA 只在这个派生视图把 `U` 改为 `T`。

`official_fasta_smoke.json` 保存三个代表 PDB 的本地 entity、官方 entity、逐 entity 是否相等和最终 `passed`。

### 冗余边

`redundancy_edges.jsonl` 只保存至少存在一条高重复 chain 边的 PDB 对：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `relation` | string | `reference` 或 `held_out_internal`。 |
| `pdb_A`、`pdb_B` | string | 当前边两端；reference 边的 A 固定为 held-out。 |
| `chain_A`、`chain_B` | float | 最大 cardinality 一对一匹配数除以各侧可比 chain 数。 |
| `residue_A`、`residue_B` | float | 分别按 A 侧和 B 侧 chain 长度最大化的一对一匹配残基数比例。 |
| `chain_matching` | list[object] | 最大 chain 数匹配及其 chain/entity 见证。 |
| `residue_A_matching`、`residue_B_matching` | list[object] | 两个残基目标各自的最优匹配见证。 |
| `chain_pass`、`residue_pass` | boolean | 两级 coverage 是否达到当前阈值。 |
| `redundant` | boolean | 当前 `pdb_coverage_mode` 与阈值的最终判断。 |

`or` 表示 `chain_pass or residue_pass`，`and` 表示 `chain_pass and residue_pass`。A/B 方向始终保留，模式不会改变四个原始 coverage。

### Held-out 身份证

`held_out_identity.jsonl` 固定包含全部 2,497 个 held-out PDB。顶层字段是：

- `pdb_id`、`emdb_ids`、`first_map_release`；
- `quality`：分辨率、`cc_contour` 和严格质量布尔值；
- `assets`：资产状态、完整图形状、布尔值和失败说明；
- `ligands`：六类 occurrence 计数、总数和 `1 < n < 100` 布尔值；
- `sequence`：状态、错误、entity/chain/residue 与可比子集统计；
- `redundancy`：当前模式、阈值、参考/内部关系数量、是否命中和最强直接见证；
- `selection`：统一资格原因、贪心顺序、接受或拒绝见证，以及 `test_0/test_1` 标记与排序。

`test_0.json` 与 `test_1.json` 都保存 schema、选择参数和 `pdb_ids`。`test_0` 固定 200 个；`test_1` 只对这 200 个应用 occurrence 总数严格 `(1,100)` 过滤。

### 汇总与完成标记

`stage1/summary.json`、`stage2/summary.json` 保存输入计数、状态计数、参数和输出计数。对应阶段成功后分别写 `stage1/_COMPLETE` 与 `stage2/_COMPLETE`。分片中间结果位于 `stage1/shards/` 和 `stage2/mmseqs/`，不是下游正式接口。

## 失败与重跑

held-out 的 `missing_mmcif` 和 `parse_error` 是未预期序列失败。最多 74 个时仍发布身份证和失败清单；达到 75 个时合并阶段退出，不写正式阶段完成标记。质量、资产、短链和零可比 chain 不属于处理失败。

正式运行不自动重试、不自动换参数、不自动清理旧产物。只有未预期失败超过 held-out 的 3% 时，才在诊断后考虑修改代码与重跑。
