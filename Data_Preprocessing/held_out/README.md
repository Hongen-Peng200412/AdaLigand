# AdaLigand held-out 去冗余

本目录把冻结的 PDB/EMDB 数据整理成一份可复用的 polymer entity 序列目录，再从日期留出的 2,497 个 PDB 生成统一身份证、序列冗余关系和三个测试视图。科学定义以 `../../文档/规划文档/held-out去冗余与测试集构建.md` 为准；本 README 只说明当前代码入口和盘上字段。

## 目录组织

- `held_out_pipeline/catalog.py`：解析 mmCIF、审计 held-out 质量与资产、合并序列目录、生成 FASTA、对照 RCSB 官方 FASTA。
- `held_out_pipeline/redundancy.py`：运行 MMseqs2、读取真实 identity 与双向 coverage、在 entity 容量图计算三个一对一匹配，并生成与 PDB coverage 参数无关的共享边证据。
- `held_out_pipeline/selection.py`：对共享边证据应用一个 mode/threshold 组合，构建该 split 的身份证、固定种子贪心极大独立集 `full_test`，再派生 `test_0` 与 `test_1`。
- `held_out_pipeline/cli.py`：五个显式步骤的薄命令行入口，不隐式串联 Job。
- `tests/`：纯合成契约测试；真实 RCSB FASTA 和 MMseqs2 smoke 在服务器步骤执行。
- `sh/held_out_*.sh`：三个单任务步骤与两个数组步骤的正式任务脚本。

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

## 五个显式执行步骤

步骤 1 是目录数组任务，共 12 个分片，每个数组元素内部使用 `SLURM_CPUS_PER_TASK` 个进程：

```bash
bash 训练与运行/submit_task.sh --sh Data_Preprocessing/held_out/sh/held_out_catalog_array.sh --resource cpu --cpus 8 --array 0-11 --time 04:00:00
```

步骤 2 合并目录、生成自然 FASTA 与 MMseqs2 FASTA，并对三个真实 PDB 调用 RCSB 官方 FASTA：

```bash
bash 训练与运行/submit_task.sh --sh Data_Preprocessing/held_out/sh/held_out_catalog_finalize.sh --resource cpu --cpus 8 --time 02:00:00
```

步骤 3 用数组任务分别运行 protein 与 nucleic MMseqs2：

```bash
bash 训练与运行/submit_task.sh --sh Data_Preprocessing/held_out/sh/held_out_mmseqs_array.sh --resource cpu --cpus 8 --array 0-11 --time 12:00:00
```

步骤 4 只合并已有 MMseqs2 TSV，生成一份与 PDB coverage mode/threshold 无关的共享边证据：

```bash
bash 训练与运行/submit_task.sh --sh Data_Preprocessing/held_out/sh/held_out_finalize.sh --resource cpu --cpus 8 --mem 32G --time 04:00:00
```

步骤 5 从共享边证据并行生成 0.5/0.6 与 chain/residue/or/and 的八个 split：

```bash
bash 训练与运行/submit_task.sh --sh Data_Preprocessing/held_out/sh/held_out_split_array.sh --resource cpu --cpus 8 --mem 32G --array 0-7 --time 04:00:00
```

这些命令不建立自动依赖。`stage1/_COMPLETE` 和各 split 的 `_COMPLETE` 只记录相应步骤正常写完的事实，后续代码不读取它们作为门控。

> **当前实现边界：** `catalog-finalize` 仍把 RCSB 网络抽样对照与正式目录合并放在同一个函数和任务中。这是当前代码的实际耦合，不表示 RCSB 抽样对照属于科学契约。`official_fasta_smoke.json` 在本 README 中标记为“外部抽样审计”，不得把它当作序列目录、冗余边或测试集的科学结果。

## 主要产物

输出根固定为 `/storage/penghongen/AdaLigand/held_out`。

下文的“示例值”用于展示字段的精确格式和字段间关系。除了明确标注的正式运行统计，示例值是结构正确的说明性数值，不表示正式产物中一定存在对应的 PDB 记录。

为避免把盘上所有文件误认为同等重要的科学产物，目录树先在 `## <科学产物>` 下集中列出稳定科学接口；其余文件在注释末尾使用圆括号标明以下生命周期类别。正文的每个文件条目仍保留完整的“生命周期”说明。

- **稳定科学产物**：保存序列身份、冗余证据或测试集成员，可作为后续分析接口。
- **可再生辅助导出**：与稳定科学产物信息重复的格式转换，当前正式管线没有读取者。
- **可再生工具输入**：可从稳定科学产物无损重建，只因外部程序需要特定文件格式而存在，不是独立科学事实。
- **计算中间文件**：只服务于分片合并、证据构建或失败后复算，不得作为最终分析接口。
- **工具临时目录**：由外部程序管理的数据库、索引和工作目录，内部名称与布局均不可依赖。
- **运行诊断或统计**：用于失败定位、规模核对、命令留证或完成判定，不定义序列、冗余关系或测试集成员。
- **外部抽样审计**：依赖 RCSB 当前网络服务的样本检查，不属于冻结数据的科学契约。

### 服务器目录结构

下面的结构树已经与服务器 `/storage/penghongen/AdaLigand/held_out` 的实际目录逐项核对。连续编号文件用 `<000...011>` 压缩表示 12 份实际文件；`<05|06>` 与 `<chain|residue|or|and>` 的笛卡尔积表示 8 个实际 split 目录。两段结构树中重复出现的根目录和 `split/` 是同一个物理目录：第一段只列科学产物，第二段只列其他文件。

```text
## <科学产物>
/storage/penghongen/AdaLigand/held_out/
├── sequence_catalog.jsonl                 # 全部成功解析的 polymer entity 序列目录
├── held_out_base.jsonl                    # held-out PDB 的质量、配体、资产与序列基础信息
├── qualifying_entity_hits.jsonl           # 通过 identity 与双向 coverage 门槛的 polymer entity 对
├── pdb_edge_evidence.jsonl                # 尚未应用 split 参数的 PDB 边证据
└── split/
    └── held_out_<05|06>_<chain|residue|or|and>/ # 2 个阈值 × 4 种判定模式，共 8 个目录
        ├── redundancy_edges.jsonl         # 当前参数下的全部 PDB 边与判定
        ├── held_out_identity.jsonl        # held-out PDB 的完整身份证
        ├── full_test.json                  # 贪心极大独立集
        ├── test_0.json                     # 从 full_test 无放回抽取的至多 200 个 PDB
        └── test_1.json                     # 对 test_0 应用配体 occurrence 数过滤后的保序子集

## <其他文件>
/storage/penghongen/AdaLigand/held_out/
├── pdb_sequence_status.jsonl              # 每个完整 PDB 的 mmCIF 序列解析状态（运行诊断）
├── held_out_sequence_failures.jsonl       # held_out_base.jsonl 的失败记录子集（运行诊断）
├── official_fasta_smoke.json              # 依赖 RCSB 当前网络服务的抽样对照（外部抽样审计）
├── fasta/                                  # 与 sequence_catalog.jsonl 同源且可由它重建（可再生辅助导出与工具输入）
│   ├── natural/                              # 当前正式管线无读取者（可再生辅助导出）
│   │   ├── protein.fasta                  # sequence_catalog.jsonl 的蛋白质格式转换（可再生辅助导出）
│   │   ├── rna.fasta                      # RNA 序列保留 U，当前无消费者（可再生辅助导出）
│   │   ├── dna.fasta                      # sequence_catalog.jsonl 的 DNA 格式转换（可再生辅助导出）
│   │   └── hybrid.fasta                   # sequence_catalog.jsonl 的杂合序列格式转换（可再生辅助导出）
│   └── mmseqs/                               # 只供 MMseqs2 读取（可再生工具输入）
│       ├── protein_target.fasta           # 可比较蛋白质的 MMseqs2 target（可再生工具输入）
│       ├── nucleic_target.fasta           # 可比较核酸 target，U 转换为 T（可再生工具输入）
│       ├── protein_query_<000...011>.fasta # 12 份 held-out 蛋白质 query（可再生工具输入）
│       └── nucleic_query_<000...011>.fasta # 12 份 held-out 核酸 query，U 转换为 T（可再生工具输入）
├── stage1/                                     # 目录解析分片、统计与完成标记（计算中间文件与运行诊断）
│   ├── shards/                                # 只供合并和分片重跑（计算中间文件）
│   │   ├── catalog_<000...011>.jsonl      # 12 份 mmCIF 解析分片（计算中间文件）
│   │   └── summary_<000...011>.json       # 12 份分片计数、状态与输出路径（运行诊断）
│   ├── summary.json                       # 目录规模、失败计数、FASTA 规模与外部抽样结果（运行统计）
│   └── _COMPLETE                          # 空文件，后续代码不读取（运行完成标记）
├── stage2/                                     # MMseqs2 原始比对、工具目录与统计（计算中间文件与运行诊断）
│   ├── mmseqs/                               # 原始比对与命令留证（计算中间文件与运行诊断）
│   │   ├── protein_<000...011>.tsv        # 12 份蛋白质 MMseqs2 原始比对（计算中间文件）
│   │   ├── nucleic_<000...011>.tsv        # 12 份核酸 MMseqs2 原始比对（计算中间文件）
│   │   └── summary_<000...011>.json       # 12 份 MMseqs2 命令、版本、状态与路径（运行诊断）
│   ├── mmseqs_tmp/                            # MMseqs2 内部数据库与索引（工具临时目录）
│   │   ├── protein_<000...011>/           # 蛋白质 easy-search 工作区与 latest 符号链接（工具临时目录）
│   │   └── nucleic_<000...011>/           # 核酸 easy-search 工作区与 latest 符号链接（工具临时目录）
│   └── edge_summary.json                  # entity 命中与 PDB 边聚合计数，不代替边证据（运行统计）
└── split/
    └── held_out_<05|06>_<chain|residue|or|and>/
        ├── summary.json                    # 参数、边数、排除原因与集合计数（运行统计）
        └── _COMPLETE                       # 空文件，后续代码不读取（运行完成标记）
```

八个实际参数目录依次是 `held_out_05_chain/`、`held_out_05_residue/`、`held_out_05_or/`、`held_out_05_and/`、`held_out_06_chain/`、`held_out_06_residue/`、`held_out_06_or/` 和 `held_out_06_and/`。例如，`held_out_05_or/` 表示 coverage 边界为 `0.5`，且 chain coverage 或 residue coverage 任一达到边界即判为冗余。

`## <科学产物>` 分组是科学分析接口的正面清单。`## <其他文件>` 中每条注释末尾的圆括号类别是文件职责的一部分，不只是阅读建议。`fasta/`、`stage1/`、`stage2/mmseqs/` 与 `stage2/mmseqs_tmp/` 中的文件均不得作为科学分析接口。共享根不保存任一 split 参数产物的兼容副本。

### 核心身份与序列数据

这一组先回答“有哪些 PDB、polymer entity 和可比较序列”。`sequence_catalog.jsonl` 是 polymer entity 序列的唯一持久化事实来源；本节同时列出当前实现额外生成的 FASTA，但这些 FASTA 只是可再生的格式转换或 MMseqs2 工具输入，不是独立科学产物。

#### `sequence_catalog.jsonl`

**生命周期：稳定科学产物，也是 polymer entity 序列的唯一持久化事实来源。** FASTA 文件中的序列都必须能从本文件重建。

`sequence_catalog.jsonl` 每行是一个 polymer entity：

| 字段 | 类型 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `sequence_id` | string | RCSB 风格的 `<PDB_ID>_<entity_id>` FASTA 序列标识，用于 FASTA 与 MMseqs2 对齐。 | `"1ABC_1"` |
| `pdb_id` | string | 小写 PDB 条目标识。 | `"1abc"` |
| `entity_id` | string | 当前 mmCIF 内的 polymer entity 标识。 | `"1"` |
| `polymer_type` | string | 原始 `_entity_poly.type`。 | `"polypeptide(L)"` |
| `sequence_class` | string | 归一化序列类别，取 `protein`、`rna`、`dna`、`hybrid` 或 `other`。 | `"protein"` |
| `sequence` | string | 仅去空白并转为大写的沉积规范全长序列。 | `"ACDEFGHIKLMNPQRSTVWYACDEFGHIKL"` |
| `length` | integer | `sequence` 字符数。 | `30` |
| `label_asym_ids` | list[string] | 指向该 entity 的全部 `_struct_asym.id`；列表中每个值表示一个 chain 结构副本。 | `["A", "B"]` |
| `comparable` | boolean | protein 长度至少 30 aa，或 RNA、DNA、hybrid 长度至少 20 nt 时为 `true`。 | `true` |

上表对应的一行 `sequence_catalog.jsonl` 示例为：

```json
{"comparable": true, "entity_id": "1", "label_asym_ids": ["A", "B"], "length": 30, "pdb_id": "1abc", "polymer_type": "polypeptide(L)", "sequence": "ACDEFGHIKLMNPQRSTVWYACDEFGHIKL", "sequence_class": "protein", "sequence_id": "1ABC_1"}
```

#### `held_out_base.jsonl`

**生命周期：稳定科学产物。** 本文件保存每个 held-out PDB 的选择基础事实，不是分片中间文件或运行摘要。

`held_out_base.jsonl` 固定覆盖全部 held-out PDB，每行字段如下：

| 字段 | 类型 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `pdb_id` | string | 小写 held-out PDB 条目标识。 | `"1abc"` |
| `emdb_ids` | list[string] | 该 PDB 在冻结对照中出现的全部 EMDB 标识。 | `["EMD-1234"]` |
| `first_map_release` | string 或 null | 首次 EMDB 发布时间；来源没有日期时为 `null`。 | `"2026-02-14"` |
| `quality` | object | 图级质量字段；`map_resolution` 单位为 Å，`passed` 仅在 `map_resolution < 4.0` 且 `cc_contour > 0.65` 时为 `true`。 | `{"map_resolution": 3.2, "cc_contour": 0.78, "passed": true}` |
| `ligands` | object | occurrence 总数、六类计数和严格 `1 < total_count < 100` 过滤结果；`type_counts` 六个键始终存在。 | `{"total_count": 3, "type_counts": {"ion": 1, "nucleotide_like": 0, "other": 0, "peptide_like": 0, "small_molecule": 2, "sugar": 0}, "strict_1_100_passed": true}` |
| `assets` | object | Stage1 资产状态、是否通过、完整图 Z/Y/X 形状和错误定位文本；状态取 `eligible`、`short_map`、`missing_file` 或 `invalid`。 | `{"status": "eligible", "passed": true, "shape_zyx": [96, 128, 128], "detail": ""}` |
| `sequence` | object | 序列状态和 polymer entity、chain、残基计数；`by_class` 固定含 `protein`、`rna`、`dna`、`hybrid`、`other` 五类，每类都含六个计数字段。 | 见下方完整 JSON 中的 `sequence` |

一条字段间数值互相一致的 `held_out_base.jsonl` 示例如下。其中蛋白质 entity 长 30 aa 且有 A、B 两个 chain，RNA entity 长 20 nt 且有 C 一个 chain，所以总残基数为 $30 \times 2 + 20 \times 1 = 80$：

```json
{
  "pdb_id": "1abc",
  "emdb_ids": ["EMD-1234"],
  "first_map_release": "2026-02-14",
  "quality": {"map_resolution": 3.2, "cc_contour": 0.78, "passed": true},
  "ligands": {
    "total_count": 3,
    "type_counts": {"ion": 1, "nucleotide_like": 0, "other": 0, "peptide_like": 0, "small_molecule": 2, "sugar": 0},
    "strict_1_100_passed": true
  },
  "assets": {"status": "eligible", "passed": true, "shape_zyx": [96, 128, 128], "detail": ""},
  "sequence": {
    "status": "ok",
    "error": null,
    "entity_count": 2,
    "chain_count": 3,
    "residue_count": 80,
    "comparable_entity_count": 2,
    "comparable_chain_count": 3,
    "comparable_residue_count": 80,
    "by_class": {
      "protein": {"entity_count": 1, "chain_count": 2, "residue_count": 60, "comparable_entity_count": 1, "comparable_chain_count": 2, "comparable_residue_count": 60},
      "rna": {"entity_count": 1, "chain_count": 1, "residue_count": 20, "comparable_entity_count": 1, "comparable_chain_count": 1, "comparable_residue_count": 20},
      "dna": {"entity_count": 0, "chain_count": 0, "residue_count": 0, "comparable_entity_count": 0, "comparable_chain_count": 0, "comparable_residue_count": 0},
      "hybrid": {"entity_count": 0, "chain_count": 0, "residue_count": 0, "comparable_entity_count": 0, "comparable_chain_count": 0, "comparable_residue_count": 0},
      "other": {"entity_count": 0, "chain_count": 0, "residue_count": 0, "comparable_entity_count": 0, "comparable_chain_count": 0, "comparable_residue_count": 0}
    }
  }
}
```

#### `fasta/natural/{protein,rna,dna,hybrid}.fasta`

**生命周期：可再生辅助导出，不是稳定科学接口。** 这四个文件的 header、序列类别和序列文本全部来自 `sequence_catalog.jsonl`；当前正式管线没有任何步骤读取它们，因此它们不增加新的科学信息，删除它们不会影响当前管线。

这四个文件按 `sequence_class` 分开保存自然序列。例如，长度为 20 nt 的 RNA 记录可为 `>1ABC_2` 后跟 `AUGCAUGCAUGCAUGCAUGC`；`rna.fasta` 保留字母 `U`。

#### `fasta/mmseqs/{protein,nucleic}_target.fasta`

**生命周期：可再生工具输入，不是稳定科学接口。** MMseqs2 `easy-search` 需要 FASTA 格式的 target。当前实现用与 `sequence_catalog.jsonl` 相同的内存 entity 列表写出这两个文件，因此它们不增加新的序列事实。它们只需在 MMseqs2 运行期间存在；MMseqs2 分片全部完成后可删除。当前代码尚无从 `sequence_catalog.jsonl` 单独重建 FASTA 的命令，删除后若要重跑 MMseqs2，必须重新执行 `catalog-finalize` 或先补充独立导出命令。

两个 target 文件保存暴露参考 PDB 与 held-out PDB 中的全部可比较序列，供每个 query 分片共同检索。`protein_target.fasta` 保留蛋白质序列；`nucleic_target.fasta` 合并 RNA、DNA 与 hybrid，并把 RNA 中的 `U` 转为 `T`。例如，上述 RNA 在这里写成 `>1ABC_2` 后跟 `ATGCATGCATGCATGCATGC`。

#### `fasta/mmseqs/{protein,nucleic}_query_<000...011>.fasta`

**生命周期：可再生工具输入，不是稳定科学接口。** MMseqs2 `easy-search` 需要与 target 分开的 query 文件；这 24 个文件只是 `sequence_catalog.jsonl` 中 held-out 可比较序列的分片视图，与 target 文件使用相同的删除和重建边界。

24 个 query 文件把 held-out PDB 按稳定分片编号拆成 12 份蛋白质 query 和 12 份核酸 query。每条 FASTA header 仍使用 `sequence_id`，如 `>1ABC_1`；核酸 query 与核酸 target 一样把 `U` 转为 `T`。

### 共享冗余证据

这一组保存不依赖 0.5/0.6 与 chain/residue/or/and 参数的公共科学证据：先记录满足序列门槛的 entity 对，再聚合为 PDB 对的 chain 与 residue coverage。

#### `qualifying_entity_hits.jsonl`

**生命周期：稳定科学产物。** 本文件是逐 polymer entity 冗余命中的正式证据接口。

`qualifying_entity_hits.jsonl` 保存通过类别 identity 和双向 0.80 coverage 的去重 entity 对。每行字段如下：

| 字段 | 类型 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `relation` | string | PDB 对关系；`reference` 表示 held-out 对暴露参考，`held_out_internal` 表示两个 held-out PDB 之间的关系。 | `"reference"` |
| `pdb_A`、`pdb_B` | string | 定向后的两个小写 PDB 标识；reference 关系中 A 固定是 held-out。 | `"1abc"`、`"2xyz"` |
| `entity_A`、`entity_B` | string | A、B 两侧参与比对的 polymer entity 标识。 | `"1"`、`"2"` |
| `sequence_id_A`、`sequence_id_B` | string | A、B 两侧 entity 的 FASTA 序列标识。 | `"1ABC_1"`、`"2XYZ_2"` |
| `label_asym_ids_A`、`label_asym_ids_B` | list[string] | 两侧 entity 对应的全部 chain 结构副本。 | `["A", "B"]`、`["C"]` |
| `length_A`、`length_B` | integer | 两侧 entity 的沉积全长，单位为 aa 或 nt。 | `30`、`32` |
| `sequence_kind` | string | MMseqs2 比对序列类别，取 `protein` 或 `nucleic`。 | `"protein"` |
| `identity` | float | MMseqs2 真实序列 identity，取值范围为 `[0, 1]`。 | `0.90` |
| `coverage_A`、`coverage_B` | float | alignment 分别覆盖 A、B 侧 entity 全长的比例。 | `1.0`、`0.9375` |
| `alignment_length` | integer | alignment 长度，单位为 aa 或 nt。 | `30` |
| `evalue` | float | MMseqs2 alignment E-value。 | `1e-20` |

上表对应的一行 `qualifying_entity_hits.jsonl` 构造示例为：

```json
{"alignment_length": 30, "coverage_A": 1.0, "coverage_B": 0.9375, "entity_A": "1", "entity_B": "2", "evalue": 1e-20, "identity": 0.9, "label_asym_ids_A": ["A", "B"], "label_asym_ids_B": ["C"], "length_A": 30, "length_B": 32, "pdb_A": "1abc", "pdb_B": "2xyz", "relation": "reference", "sequence_id_A": "1ABC_1", "sequence_id_B": "2XYZ_2", "sequence_kind": "protein"}
```

#### `pdb_edge_evidence.jsonl`

**生命周期：稳定科学产物。** 本文件是尚未应用 split coverage 参数的逐 PDB 边正式证据接口。

共享根的 `pdb_edge_evidence.jsonl` 只保存至少存在一条高重复 chain 边的 PDB 对。它不含 mode、threshold 或判定布尔值：

| 字段 | 类型 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `relation` | string | `reference` 或 `held_out_internal`。 | `"reference"` |
| `pdb_A`、`pdb_B` | string | 当前边两端；reference 边的 A 固定为 held-out。 | `"1abc"`、`"2xyz"` |
| `comparable_chain_count_A`、`comparable_chain_count_B` | integer | 各侧进入比对和 chain coverage 分母的 chain 结构副本数。 | `2`、`1` |
| `comparable_residue_count_A`、`comparable_residue_count_B` | integer | 各侧 comparable chain 沉积全长序列长度之和。 | `60`、`32` |
| `chain_A`、`chain_B` | float | 最大 chain 数一对一匹配数除以各侧可比 chain 数。 | `0.5`、`1.0` |
| `residue_A`、`residue_B` | float | 分别按 A 侧和 B 侧 chain 长度最大化的一对一匹配残基数比例。 | `0.5`、`1.0` |
| `chain_matching` | list[object] | 使匹配 chain 对数最大的直接见证列表。 | 含一项下表示例见证的列表 |
| `residue_A_matching`、`residue_B_matching` | list[object] | 分别使 A 侧和 B 侧匹配残基数最大的见证列表；两个列表可以不同。 | 各含一项下表示例见证的列表 |

三类 matching 的每条见证使用同一组字段：

| 见证字段 | 类型 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `chain_A`、`chain_B` | string | 被选中的 A、B 侧 `label_asym_id`。 | `"A"`、`"C"` |
| `entity_A`、`entity_B` | string | 两条 chain 各自所属的 entity 标识。 | `"1"`、`"2"` |
| `sequence_id_A`、`sequence_id_B` | string | 两侧 entity 的 FASTA 序列标识。 | `"1ABC_1"`、`"2XYZ_2"` |
| `length_A`、`length_B` | integer | 两条 chain 共用的 entity 沉积全长，单位为 aa 或 nt。 | `30`、`32` |
| `sequence_kind` | string | 序列比对类别。 | `"protein"` |
| `identity` | float | 产生该 entity 边的真实序列 identity。 | `0.90` |
| `coverage_A`、`coverage_B` | float | alignment 覆盖两侧 entity 全长的比例。 | `1.0`、`0.9375` |

一条 matching 见证的完整示例为：

```json
{"chain_A": "A", "chain_B": "C", "coverage_A": 1.0, "coverage_B": 0.9375, "entity_A": "1", "entity_B": "2", "identity": 0.9, "length_A": 30, "length_B": 32, "sequence_id_A": "1ABC_1", "sequence_id_B": "2XYZ_2", "sequence_kind": "protein"}
```

由该见证组成的一条字段齐全的 `pdb_edge_evidence.jsonl` 构造示例为：

```json
{
  "relation": "reference",
  "pdb_A": "1abc",
  "pdb_B": "2xyz",
  "comparable_chain_count_A": 2,
  "comparable_chain_count_B": 1,
  "comparable_residue_count_A": 60,
  "comparable_residue_count_B": 32,
  "chain_A": 0.5,
  "chain_B": 1.0,
  "residue_A": 0.5,
  "residue_B": 1.0,
  "chain_matching": [
    {"chain_A": "A", "chain_B": "C", "coverage_A": 1.0, "coverage_B": 0.9375, "entity_A": "1", "entity_B": "2", "identity": 0.9, "length_A": 30, "length_B": 32, "sequence_id_A": "1ABC_1", "sequence_id_B": "2XYZ_2", "sequence_kind": "protein"}
  ],
  "residue_A_matching": [
    {"chain_A": "A", "chain_B": "C", "coverage_A": 1.0, "coverage_B": 0.9375, "entity_A": "1", "entity_B": "2", "identity": 0.9, "length_A": 30, "length_B": 32, "sequence_id_A": "1ABC_1", "sequence_id_B": "2XYZ_2", "sequence_kind": "protein"}
  ],
  "residue_B_matching": [
    {"chain_A": "A", "chain_B": "C", "coverage_A": 1.0, "coverage_B": 0.9375, "entity_A": "1", "entity_B": "2", "identity": 0.9, "length_A": 30, "length_B": 32, "sequence_id_A": "1ABC_1", "sequence_id_B": "2XYZ_2", "sequence_kind": "protein"}
  ]
}
```

实现先在 entity 容量图上求解数学等价的一对一 chain matching，再只展开被选中的 chain 见证，不物化高拷贝 entity 的完整 chain 笛卡尔积。

### 参数化去冗余与测试集

这一组把共享 PDB 边证据应用到八组参数，给出每个 held-out PDB 的判定身份，以及 `full_test`、`test_0`、`test_1` 三层测试集合。

#### `split/held_out_<05|06>_<chain|residue|or|and>/redundancy_edges.jsonl`

**生命周期：参数化的稳定科学产物。** 本文件是当前 coverage 阈值和判定模式下的逐 PDB 边正式接口。

每个 `redundancy_edges.jsonl` 在共享证据上增加以下字段：

| 新增字段 | 类型 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `pdb_coverage_mode` | string | 当前 PDB coverage 判定模式，取 `chain`、`residue`、`or` 或 `and`。 | `"or"` |
| `pdb_coverage_threshold` | float | chain 和 residue 两级共用的包含边界。 | `0.5` |
| `chain_pass` | boolean | `max(chain_A, chain_B)` 是否达到当前边界。 | `true` |
| `residue_pass` | boolean | `max(residue_A, residue_B)` 是否达到当前边界。 | `true` |
| `redundant` | boolean | 当前 mode 选取或组合 `chain_pass` 与 `residue_pass` 后的最终判定。 | `mode="or"` 且两级都通过时为 `true` |

`chain` 只取 `chain_pass`，`residue` 只取 `residue_pass`，`or` 和 `and` 分别组合两级判断。A/B 方向始终保留，模式不会改变四个原始 coverage。

#### `split/held_out_<05|06>_<chain|residue|or|and>/held_out_identity.jsonl`

**生命周期：参数化的稳定科学产物。** 本文件是当前参数下逐 held-out PDB 身份、冗余状态与选择状态的正式接口。

每个 split 的 `held_out_identity.jsonl` 固定包含全部 2,497 个 held-out PDB。每行字段如下：

| 字段 | 类型 | 含义与子字段 | 示例值 |
| --- | --- | --- | --- |
| `schema`、`schema_version` | string、integer | 身份证 schema 标识与版本。 | `"adaligand.held_out_identity"`、`1` |
| `pdb_id`、`emdb_ids`、`first_map_release` | string、list[string]、string 或 null | PDB、EMDB 和首次密度图发布日期。 | `"1abc"`、`["EMD-1234"]`、`"2026-02-14"` |
| `quality` | object | 与 `held_out_base.jsonl` 相同；分辨率单位为 Å，缺失数值为 `null`。 | `{"map_resolution": 3.2, "cc_contour": 0.78, "passed": true}` |
| `assets` | object | 与 `held_out_base.jsonl` 相同；含资产状态、通过布尔值、ZYX 顺序的可空形状与定位文本。 | `{"status": "eligible", "passed": true, "shape_zyx": [96, 128, 128], "detail": ""}` |
| `ligands` | object | 与 `held_out_base.jsonl` 相同；含 occurrence 总数、六个具名类别计数与严格过滤布尔值。 | 如 `total_count=3`、`small_molecule=2`、`strict_1_100_passed=true` |
| `sequence` | object | 与 `held_out_base.jsonl` 相同；含状态、可空错误、六个总计字段和五类各自的六个计数字段。 | 如 `entity_count=2`、`chain_count=3`、`residue_count=80` |
| `redundancy` | object | 当前参数下的参考与 held-out 内部冗余边计数和直接见证；子字段见下表。 | 如内部冗余边为 1 条，参考边为 0 条 |
| `selection` | object | 当前 PDB 的前置资格、贪心极大独立集状态和三个测试视图成员身份；子字段见下表。 | 如前置资格通过且进入 `full_test`、`test_0`、`test_1` |

`redundancy` 的子字段如下：

| 子字段 | 类型 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `pdb_coverage_mode` | string | 当前判定模式。 | `"or"` |
| `pdb_coverage_threshold` | float | 当前 coverage 包含边界。 | `0.5` |
| `reference_edge_count` | integer | 当前 PDB 与序列状态为 `ok` 的暴露参考 PDB 之间的直接边数。 | `0` |
| `reference_redundant_edge_count` | integer | 参考边中 `redundant=true` 的数量。 | `0` |
| `reference_redundant` | boolean | 是否至少存在一条冗余参考边。 | `false` |
| `strongest_reference_edge` | object 或 null | 最强参考边的压缩见证；没有参考边时为 `null`。 | `null` |
| `internal_edge_count` | integer | 当前 PDB 与其他 held-out PDB 的直接边数。 | `1` |
| `internal_redundant_edge_count` | integer | 内部边中 `redundant=true` 的数量。 | `1` |
| `strongest_internal_edge` | object 或 null | 最强内部边的压缩见证；没有内部边时为 `null`。 | `{"other_pdb_id": "1def", "relation": "held_out_internal", "chain_A": 0.5, "chain_B": 1.0, "residue_A": 0.5, "residue_B": 1.0, "max_coverage": 1.0, "chain_pass": true, "residue_pass": true, "redundant": true}` |

`selection` 的子字段如下：

| 子字段 | 类型 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `base_eligible` | boolean | 质量、资产、序列和参考去冗余四项前置条件是否全部通过。 | `true` |
| `exclusion_reasons` | list[string] | 可同时包含 `quality_failed`、`asset_failed`、`sequence_failed`、`reference_redundant`；无前置排除原因时为空列表。 | `[]` |
| `greedy_rank` | integer 或 null | 通过前置条件的 PDB 在固定随机贪心访问顺序中的零基排名；未通过前置条件时为 `null`。 | `0` |
| `full_test` | boolean | 是否进入贪心极大独立集。 | `true` |
| `full_test_rank` | integer 或 null | 在 `full_test` 贪心接受顺序中的零基排名；非成员为 `null`。 | `0` |
| `rejected_by` | string 或 null | 拒绝当前 PDB 的更早已接受直接冲突 PDB；当前 PDB 被接受或未进入贪心图时为 `null`。 | `null` |
| `rejection_edge` | object 或 null | 当前 PDB 与 `rejected_by` 的压缩直接见证；`rejected_by=null` 时为 `null`。 | `null` |
| `test_0` | boolean | 是否属于从 `full_test` 无放回抽取的 `test_0`。 | `true` |
| `test_0_rank` | integer 或 null | 在 `test_0` 随机抽取顺序中的零基排名；非成员为 `null`。 | `0` |
| `test_1` | boolean | 是否属于对 `test_0` 应用 occurrence 数过滤后的 `test_1`。 | `true` |
| `test_1_rank` | integer 或 null | 在 `test_1` 保序子集中的零基排名；非成员为 `null`。 | `0` |

上述示例表示 `1abc` 没有参考冗余边，但与 `1def` 存在一条 held-out 内部冗余边。`1abc` 在贪心顺序中先被访问并接受，所以它可以进入 `full_test`；后被访问的 `1def` 才会被 `1abc` 拒绝。压缩关系见证存在冗余边时优先选择冗余见证，保证参考排除原因与身份证见证一致。

将上述各组示例组合后，一条字段齐全且数值自洽的 `held_out_identity.jsonl` 构造示例为：

```json
{
  "schema": "adaligand.held_out_identity",
  "schema_version": 1,
  "pdb_id": "1abc",
  "emdb_ids": ["EMD-1234"],
  "first_map_release": "2026-02-14",
  "quality": {"map_resolution": 3.2, "cc_contour": 0.78, "passed": true},
  "assets": {"status": "eligible", "passed": true, "shape_zyx": [96, 128, 128], "detail": ""},
  "ligands": {
    "total_count": 3,
    "type_counts": {"ion": 1, "nucleotide_like": 0, "other": 0, "peptide_like": 0, "small_molecule": 2, "sugar": 0},
    "strict_1_100_passed": true
  },
  "sequence": {
    "status": "ok",
    "error": null,
    "entity_count": 2,
    "chain_count": 3,
    "residue_count": 80,
    "comparable_entity_count": 2,
    "comparable_chain_count": 3,
    "comparable_residue_count": 80,
    "by_class": {
      "protein": {"entity_count": 1, "chain_count": 2, "residue_count": 60, "comparable_entity_count": 1, "comparable_chain_count": 2, "comparable_residue_count": 60},
      "rna": {"entity_count": 1, "chain_count": 1, "residue_count": 20, "comparable_entity_count": 1, "comparable_chain_count": 1, "comparable_residue_count": 20},
      "dna": {"entity_count": 0, "chain_count": 0, "residue_count": 0, "comparable_entity_count": 0, "comparable_chain_count": 0, "comparable_residue_count": 0},
      "hybrid": {"entity_count": 0, "chain_count": 0, "residue_count": 0, "comparable_entity_count": 0, "comparable_chain_count": 0, "comparable_residue_count": 0},
      "other": {"entity_count": 0, "chain_count": 0, "residue_count": 0, "comparable_entity_count": 0, "comparable_chain_count": 0, "comparable_residue_count": 0}
    }
  },
  "redundancy": {
    "pdb_coverage_mode": "or",
    "pdb_coverage_threshold": 0.5,
    "reference_edge_count": 0,
    "reference_redundant_edge_count": 0,
    "reference_redundant": false,
    "strongest_reference_edge": null,
    "internal_edge_count": 1,
    "internal_redundant_edge_count": 1,
    "strongest_internal_edge": {"other_pdb_id": "1def", "relation": "held_out_internal", "chain_A": 0.5, "chain_B": 1.0, "residue_A": 0.5, "residue_B": 1.0, "max_coverage": 1.0, "chain_pass": true, "residue_pass": true, "redundant": true}
  },
  "selection": {
    "base_eligible": true,
    "exclusion_reasons": [],
    "greedy_rank": 0,
    "full_test": true,
    "full_test_rank": 0,
    "rejected_by": null,
    "rejection_edge": null,
    "test_0": true,
    "test_0_rank": 0,
    "test_1": true,
    "test_1_rank": 0
  }
}
```

#### `split/held_out_<05|06>_<chain|residue|or|and>/full_test.json`

**生命周期：参数化的稳定科学产物。**

每个 `full_test.json` 保存当前 split 的贪心极大独立集。字段包括 `schema_version`、`pdb_coverage_mode`、`pdb_coverage_threshold`、`seed`、固定值 `name="full_test"`、固定空值 `occurrence_filter=null`，以及按贪心接受顺序排列的 `pdb_ids`。集合成员两两没有当前参数判定的内部冗余边；每个未进入集合的合格 PDB 都与一个已进入成员直接冲突，但本文件不声称集合大小达到全局最大。

```json
{"schema_version": 1, "pdb_coverage_mode": "or", "pdb_coverage_threshold": 0.5, "seed": 3407, "name": "full_test", "occurrence_filter": null, "pdb_ids": ["1abc", "1ghi"]}
```

#### `split/held_out_<05|06>_<chain|residue|or|and>/test_0.json`

**生命周期：参数化的稳定科学产物。**

每个 `test_0.json` 保存从同目录 `full_test.json` 无放回抽取的至多 200 个 PDB。除同一版本和选择参数外，文件含固定值 `name="test_0"`、固定空值 `occurrence_filter=null`、固定父集合 `parent="full_test"` 与抽取顺序中的 `pdb_ids`；`full_test` 少于 200 个时取其全部成员。

```json
{"schema_version": 1, "pdb_coverage_mode": "or", "pdb_coverage_threshold": 0.5, "seed": 3407, "name": "test_0", "occurrence_filter": null, "parent": "full_test", "pdb_ids": ["1ghi", "1abc"]}
```

#### `split/held_out_<05|06>_<chain|residue|or|and>/test_1.json`

**生命周期：参数化的稳定科学产物。**

每个 `test_1.json` 保存对同目录 `test_0.json` 应用配体 occurrence 数过滤后的保序子集。除同一版本和选择参数外，文件含固定值 `name="test_1"`、过滤表达式 `occurrence_filter="1 < total_count < 100"`、固定父集合 `parent="test_0"` 与过滤后仍按 `test_0` 顺序排列的 `pdb_ids`。

```json
{"schema_version": 1, "pdb_coverage_mode": "or", "pdb_coverage_threshold": 0.5, "seed": 3407, "name": "test_1", "occurrence_filter": "1 < total_count < 100", "parent": "test_0", "pdb_ids": ["1abc"]}
```

同一 split 的三个视图满足 `test_1 ⊆ test_0 ⊆ full_test`。`full_test` 与 `test_0` 都不应用 occurrence 数过滤；200 只是 `test_0` 的目标数量上限，不会为凑数放宽冗余条件。

### 中间计算文件

这一组用于追溯分片计算和复算共享证据，不应优先于上面的稳定科学产物阅读，也不能作为 split 参数结果使用。

#### `stage1/shards/catalog_<000...011>.jsonl`

**生命周期：计算中间文件，不是科学分析接口。**

12 个 catalog 分片按排序后的完整 PDB 标识列表做步长切分。每行对应一个完整 PDB，保存 `pdb_id`、`sequence_status`、可空的 `sequence_error`、解析出的 `entities`，以及仅在该 PDB 属于 held-out 时出现的 `held_out` 基础事实。它们是合并 `sequence_catalog.jsonl`、`pdb_sequence_status.jsonl` 和 `held_out_base.jsonl` 的中间输入，不是后续步骤的稳定接口。例如，`catalog_000.jsonl` 保存分片编号 0 负责的 PDB 记录。

#### `stage2/mmseqs/{protein,nucleic}_<000...011>.tsv`

**生命周期：计算中间文件，不是最终冗余证据接口。** 它们的正式消费者是共享边证据构建步骤；后续分析应读取 `qualifying_entity_hits.jsonl` 或 `pdb_edge_evidence.jsonl`。

24 个 TSV 文件分别保存 12 份蛋白质和 12 份核酸 MMseqs2 alignment。每行列顺序固定为 `query`、`target`、`fident`、`qcov`、`tcov`、`qlen`、`tlen`、`alnlen`、`evalue`。下面一行表示 query `1ABC_1` 与 target `2XYZ_2` 的真实 identity 为 `0.9`、双向 coverage 分别为 `1.0` 和 `0.9375`、两侧全长为 30 和 32、alignment 长度为 30、E-value 为 `1e-20`：

```text
1ABC_1\t2XYZ_2\t0.9\t1.0\t0.9375\t30\t32\t30\t1e-20
```

这些 TSV 是构建共享边证据的中间输入，不是 split 参数产物。

#### `stage2/mmseqs_tmp/{protein,nucleic}_<000...011>/`

**生命周期：工具临时目录，禁止作为科学或运行接口。**

这 24 个目录是 MMseqs2 `easy-search` 建立的内部数据库和索引工作区。服务器实况中每个目录含一个数字命名的运行子目录和 `latest` 符号链接，例如 `stage2/mmseqs_tmp/protein_000/latest`；其内部命名由 MMseqs2 决定，可在不需要重用 MMseqs2 索引时删除。

### 统计、报错、校验与完成状态

这一组不改变序列、冗余边或测试集的科学含义，只用于定位序列解析失败、核对运行参数、查看规模统计和确认某一步是否正常写完。因此放在全部科学契约与中间数据之后。

#### `pdb_sequence_status.jsonl`

**生命周期：运行诊断，不是科学结果。** 它用于界定 `sequence_catalog.jsonl` 的实际解析覆盖范围，但不定义 polymer entity 序列。

`pdb_sequence_status.jsonl` 每个完整 PDB 一行：

| 字段 | 类型 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `pdb_id` | string | 小写 PDB 条目标识。 | `"1abc"` |
| `status` | string | 序列解析状态，取 `ok`、`missing_mmcif` 或 `parse_error`。 | `"ok"` |
| `error` | string 或 null | `status="ok"` 时为 `null`；失败时为缺失 mmCIF 路径，或“异常类型: 异常文本”。 | `null`；缺文件时如 `"/storage/penghongen/AdaLigand/Ori_Data/raw/rcsb_mmcif/1xyz.cif"` |
| `entity_count` | integer | 成功解析的 polymer entity 数；解析失败时为 `0`，成功但没有 polymer entity 时也可为 `0`。 | `2` |

成功与缺少 mmCIF 的两种完整记录示例为：

```json
{"entity_count": 2, "error": null, "pdb_id": "1abc", "status": "ok"}
{"entity_count": 0, "error": "/storage/penghongen/AdaLigand/Ori_Data/raw/rcsb_mmcif/1xyz.cif", "pdb_id": "1xyz", "status": "missing_mmcif"}
```

#### `held_out_sequence_failures.jsonl`

**生命周期：运行诊断，不是独立科学产物。** 它只是 `held_out_base.jsonl` 中失败记录的便利子集。

`held_out_sequence_failures.jsonl` 是 `held_out_base.jsonl` 中 `sequence.status` 为 `missing_mmcif` 或 `parse_error` 的完整记录子集。例如，缺少 mmCIF 的记录中，`pdb_id` 可为 `"1xyz"`，`sequence.status` 为 `"missing_mmcif"`，`sequence.error` 为 `"/storage/penghongen/AdaLigand/Ori_Data/raw/rcsb_mmcif/1xyz.cif"`；该记录的其他顶层字段与 `held_out_base.jsonl` 相同。

#### `official_fasta_smoke.json`

**生命周期：外部抽样审计，不属于冻结数据的科学契约。** 本文件依赖 RCSB 当前网络服务；对照成功或失败都不能替代对 `sequence_catalog.jsonl` 完整性和冻结输入版本的验收。当前实现在 `catalog-finalize` 中运行该审计，这是已知的职责耦合，不应被理解为必要的科学步骤。

`official_fasta_smoke.json` 保存 `requested_count`（如 `1`）、实际 `pdb_ids`（如 `["1abc"]`）、总 `passed`（如 `true`）和 `results`。每个 result 含 `pdb_id`（如 `"1abc"`）、`source_url`（如 `"https://www.rcsb.org/fasta/entry/1ABC/download"`）、`passed`（如 `true`）与逐 entity 的 `sequence_id`（如 `"1ABC_1"`）、`local_sequence`（如 `"ACD"`）、`official_sequence`（如 `"ACD"`）和 `equal`（两条序列相同时如 `true`）。一个字段齐全的构造示例为：

```json
{
  "requested_count": 1,
  "pdb_ids": ["1abc"],
  "passed": true,
  "results": [
    {
      "pdb_id": "1abc",
      "source_url": "https://www.rcsb.org/fasta/entry/1ABC/download",
      "passed": true,
      "entities": [
        {"sequence_id": "1ABC_1", "local_sequence": "ACD", "official_sequence": "ACD", "equal": true}
      ]
    }
  ]
}
```

样本优先覆盖 protein 与核酸；本轮 smoke 只验收 entity 标识和沉积全长序列，不声称核对官方 header 中的 author chain 文本。

#### `stage1/shards/summary_<000...011>.json`

**生命周期：运行诊断，不是科学结果。**

每个 summary 对应同编号的 catalog 分片，保存 `shard_index`、`shard_count`、`assigned_pdb_count`、`held_out_pdb_count`、`sequence_status_counts`、`workers` 和 `output`。分片编号 0 的小规模构造示例为：

```json
{"shard_index": 0, "shard_count": 12, "assigned_pdb_count": 1866, "held_out_pdb_count": 209, "sequence_status_counts": {"ok": 1865, "missing_mmcif": 1}, "workers": 8, "output": "/storage/penghongen/AdaLigand/held_out/stage1/shards/catalog_000.jsonl"}
```

#### `stage1/summary.json`

**生命周期：运行统计，不是科学结果。** 本文件只用于核对规模和失败数；其中 `official_fasta_smoke_passed` 是外部抽样状态，不得作为科学完整性标志。

`stage1/summary.json` 保存完整序列目录、参考/held-out 失败数、MMseqs2 target 规模和官方 FASTA 对照结果。一个结构完整的小规模示例为：

```json
{"alignment_shard_count": 12, "catalog_entity_count": 4, "catalog_pdb_count": 3, "held_out_pdb_count": 2, "held_out_sequence_failure_count": 0, "nucleic_target_entity_count": 1, "official_fasta_smoke_passed": true, "protein_target_entity_count": 3, "reference_pdb_count": 1, "reference_sequence_failure_count": 0, "sequence_status_counts": {"ok": 3}}
```

#### `stage2/mmseqs/summary_<000...011>.json`

**生命周期：运行诊断与命令留证，不是科学结果。**

每个 summary 对应同编号的 protein 与 nucleic 两次检索，含 `shard_index`（如 `0`）、`threads`（如 `8`）、`mmseqs_version`（如 `"15.6f452"`）和两项 `commands`。每项 command 含 `sequence_kind`（如 `"protein"`）、`status`（如 `"completed"`）、`command` 完整参数列表和 `result` 结果路径。一个字段齐全的构造示例为：

```json
{
  "shard_index": 0,
  "threads": 8,
  "mmseqs_version": "15.6f452",
  "commands": [
    {
      "sequence_kind": "protein",
      "status": "completed",
      "command": ["/opt/mmseqs/bin/mmseqs", "easy-search", "/storage/penghongen/AdaLigand/held_out/fasta/mmseqs/protein_query_000.fasta", "/storage/penghongen/AdaLigand/held_out/fasta/mmseqs/protein_target.fasta", "/storage/penghongen/AdaLigand/held_out/stage2/mmseqs/protein_000.tsv", "/storage/penghongen/AdaLigand/held_out/stage2/mmseqs_tmp/protein_000", "--search-type", "1", "--min-seq-id", "0.3", "-c", "0.8", "--cov-mode", "0", "--alignment-mode", "3", "--seq-id-mode", "0", "-s", "7.5", "-e", "1000000", "--max-seqs", "1000000", "--threads", "8", "--format-output", "query,target,fident,qcov,tcov,qlen,tlen,alnlen,evalue"],
      "result": "/storage/penghongen/AdaLigand/held_out/stage2/mmseqs/protein_000.tsv"
    },
    {
      "sequence_kind": "nucleic",
      "status": "completed",
      "command": ["/opt/mmseqs/bin/mmseqs", "easy-search", "/storage/penghongen/AdaLigand/held_out/fasta/mmseqs/nucleic_query_000.fasta", "/storage/penghongen/AdaLigand/held_out/fasta/mmseqs/nucleic_target.fasta", "/storage/penghongen/AdaLigand/held_out/stage2/mmseqs/nucleic_000.tsv", "/storage/penghongen/AdaLigand/held_out/stage2/mmseqs_tmp/nucleic_000", "--search-type", "3", "--min-seq-id", "0.8", "-c", "0.8", "--cov-mode", "0", "--alignment-mode", "3", "--seq-id-mode", "0", "-s", "7.5", "-e", "1000000", "--max-seqs", "1000000", "--threads", "8", "--format-output", "query,target,fident,qcov,tcov,qlen,tlen,alnlen,evalue"],
      "result": "/storage/penghongen/AdaLigand/held_out/stage2/mmseqs/nucleic_000.tsv"
    }
  ]
}
```

#### `stage2/edge_summary.json`

**生命周期：运行统计，不是冗余边的科学证据接口。** 需要逐 entity 命中或逐 PDB 边证据时，分别读取 `qualifying_entity_hits.jsonl` 和 `pdb_edge_evidence.jsonl`。

`stage2/edge_summary.json` 保存原始合格 alignment、定向去重 entity 命中和 PDB 边的数量。例如，5 条原始 alignment 去重成 4 条 entity 命中，再聚合成 2 条参考边和 1 条 held-out 内部边：

```json
{"raw_qualifying_alignment_count": 5, "oriented_entity_hit_count": 4, "pdb_edge_count": 3, "relation_counts": {"held_out_internal": 1, "reference": 2}}
```

#### `split/held_out_<05|06>_<chain|residue|or|and>/summary.json`

**生命周期：运行统计，不是测试集成员接口。** 测试集成员必须从同目录 `full_test.json`、`test_0.json` 或 `test_1.json` 读取。

每个 split 的 `summary.json` 在共享边汇总上增加当前判定参数、资格规模、三个测试视图规模、排除原因计数和随机种子。对上述 3 条共享边应用 `or + 0.5` 的示例为：

```json
{"raw_qualifying_alignment_count": 5, "oriented_entity_hit_count": 4, "pdb_edge_count": 3, "relation_counts": {"held_out_internal": 1, "reference": 2}, "redundant_pdb_edge_count": 2, "mode": "or", "threshold": 0.5, "held_out_pdb_count": 2, "base_eligible_count": 1, "full_test_count": 1, "test_0_count": 1, "test_1_count": 1, "exclusion_reason_counts": {"reference_redundant": 1}, "seed": 3407}
```

#### `stage1/_COMPLETE`

**生命周期：运行完成标记，不是科学结果，也不是强制门控。** `stage1/_COMPLETE` 是空文件。它只表示 `finalize-catalog` 已正常执行到末尾，后续代码不会读取它。

#### `split/held_out_<05|06>_<chain|residue|or|and>/_COMPLETE`

**生命周期：运行完成标记，不是科学结果，也不是强制门控。** 每个 split 的 `_COMPLETE` 是空文件，只表示该参数目录已正常写完五个数据文件与 `summary.json`。后续代码不读取它，也不能用某一个 split 的标记推断其他七个 split 已完成。

## 失败与重跑

held-out 的 `missing_mmcif` 和 `parse_error` 是未预期序列失败，但失败数不参与代码门控。人工验收时，最多 74 个意味着不因这些失败修改代码或重跑；达到 75 个时先诊断再决定。暴露参考失败单独计入 `reference_sequence_failure_count`；因此有失败时只能声称已对序列状态为 `ok` 的参考 PDB 完成去冗余。质量、资产、短链和零可比 chain 不属于处理失败。

正式运行不自动重试、不自动换参数、不自动清理旧产物。只有未预期失败超过 held-out 的 3% 时，才在诊断后考虑修改代码与重跑。
