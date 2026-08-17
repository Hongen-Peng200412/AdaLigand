# PDB/mmCIF 中分子、链、序列、残基与原子的层次说明

> 状态：概念说明与 AdaLigand 数据契约讨论稿，尚未表示相应序列产物、原子映射或语言模型特征已经实现。  
> 目标：解释 PDB/mmCIF 如何描述蛋白质、RNA、DNA、小分子、链、序列、残基和原子，并给出 AdaLigand 中“受体原子 → 序列残基 → 语言模型特征”的建议保存方式。

## 1. 最重要的结论

PDB 条目中的结构信息不是一张只有“链和原子”的平面表，而是由多层身份共同描述：

```text
PDB 条目
└── model：一套原子坐标状态
    ├── entity：一种分子的定义
    │   ├── polymer entity：一种蛋白质、RNA 或 DNA
    │   │   ├── sequence：该 polymer entity 的完整残基序列
    │   │   ├── chain：该分子在沉积结构中的一个具体副本
    │   │   │   ├── residue：该 chain 中对应某个序列位置的残基
    │   │   │   │   └── atom：该残基中具有实验坐标的原子
    │   │   └── chain：同一种分子的另一个具体副本
    │   ├── non-polymer entity：小分子、离子等非聚合物
    │   └── branched entity：糖链等分支分子
    └── 水及其他结构成分
```

其中最容易混淆的三项是：

- **polymer entity** 表示“一种蛋白质、RNA 或 DNA 分子的定义”。
- **chain** 表示这种分子在当前沉积结构中的一个具体副本。
- **sequence** 是 polymer entity 的完整残基序列；即使某些残基没有解析出原子坐标，它们仍可能存在于完整序列中。

因此，同一种蛋白质在一个同源二聚体中出现两次时，通常只有一个 polymer entity 和一条完整序列，但有两个 chain 副本。

## 2. 常用术语速查

| 术语 | 具体含义 | 是否通常具有三维坐标 |
|---|---|---:|
| PDB entry | 一个 PDB 编号代表的完整结构条目，例如 `7abc` | 条目内部保存坐标 |
| model | 同一 PDB 条目中的一套原子坐标状态 | 是 |
| entity | 当前 PDB 中一种分子的定义 | entity 本身不是一组坐标 |
| polymer entity | 一种蛋白质、RNA、DNA 或其他聚合物分子 | 通过 chain 和 atom 获得坐标 |
| non-polymer entity | ATP、药物、金属离子等非聚合物分子 | 通常有坐标 |
| branched entity | 糖链等具有分支连接的分子 | 通常有坐标 |
| sequence | polymer entity 的完整残基序列 | 序列本身没有坐标 |
| chain | polymer entity 在沉积结构中的一个具体副本 | chain 中有坐标原子 |
| residue | 蛋白质中的氨基酸或核酸中的核苷酸等序列单元 | 可能只有部分原子有坐标，也可能全部缺失 |
| atom | 结构坐标的基本记录，例如蛋白质残基中的 `CA` 原子 | 是 |
| biological assembly | 根据沉积坐标和对称变换构造的生物学复合体 | 可能包含由变换生成的额外副本 |
| EMDB entry | 一个冷冻电镜密度图条目，例如 `EMD-12345` | 保存三维密度，不保存 PDB 的分子层次 |

## 3. PDB 条目和 EMDB 条目不是同一层次

一个 PDB 条目主要描述原子模型，一个 EMDB 条目主要描述三维电子密度图。两者可以互相引用，但它们不是同一个文件内部的父子层次。

```text
PDB 7abc
├── 蛋白质、RNA、DNA、小分子
├── 原子坐标
└── 指向 EMD-12345 的关联

EMD-12345
├── 三维密度图
├── voxel size、origin、分辨率等信息
└── 指向一个或多个 PDB 原子模型的关联
```

AdaLigand 使用 PDB/mmCIF 提供受体和配体原子，使用 EMDB 提供实验密度图。PDB 中的 entity、chain、sequence、residue 和 atom 层次不能从 EMDB 密度图中恢复。

## 4. model：同一条目中的一套坐标

一个 PDB 条目可以包含一个或多个 model。每个 model 都是一套原子坐标状态。

NMR 结构经常保存多套构象：

```text
PDB entry
├── model 1
├── model 2
├── model 3
└── ...
```

冷冻电镜原子模型通常只使用一套主要坐标。AdaLigand 当前 Stage C 使用第一个 model，并使用沉积态非对称单元，不自动展开生物学 assembly 或晶体对称副本。

同一个 entity、chain 和 residue 在多个 model 中可能都有坐标，但其坐标值可以不同。语言模型序列通常不随 model 改变；原子到序列位置的身份关系也通常不随 model 改变。

## 5. entity：一种分子的定义

entity 可以理解为“这个 PDB 条目中包含哪些不同的分子”。

假设一个结构包含：

- 两份序列完全相同的蛋白质；
- 一条 RNA；
- 三个 ATP 分子；
- 若干镁离子和水。

它可能具有如下 entity：

```text
entity 1：某种蛋白质，类型为 polymer
entity 2：某种 RNA，类型为 polymer
entity 3：ATP，类型为 non-polymer
entity 4：镁离子，类型为 non-polymer
entity 5：水
```

蛋白质在坐标中虽然出现两份，但如果两份蛋白质属于同一种分子定义，它们通常共同引用 entity 1。ATP 也可以只有一个 entity 定义，但在结构中具有多个空间 occurrence，也就是同一种分子在不同位置出现多次。

mmCIF 中常用 `_entity.id` 保存 entity 编号，使用 `_entity.type` 区分 `polymer`、`non-polymer`、`branched` 和水等类型。

## 6. polymer entity：一种聚合物分子

polymer entity 是 entity 的一种，表示由连续残基组成的聚合物，例如：

- 蛋白质；
- RNA；
- DNA；
- DNA/RNA hybrid；
- 某些其他聚合物。

一条 polymer entity 记录至少需要回答：

- 它在当前 PDB 中的 `entity_id` 是什么；
- 它属于蛋白质、RNA、DNA还是其他聚合物；
- 它的完整规范序列是什么；
- 它的序列长度是多少；
- 哪些 chain 是它的结构副本。

例如：

```text
entity_id = 1
polymer_type = protein
sequence = MKTLLV...
sequence_length = 238
chain instances = A, B
```

这表示当前 PDB 中存在一种长度为 238 的蛋白质，沉积坐标中有 chain A 和 chain B 两个副本。

## 7. sequence：polymer entity 的完整残基序列

sequence 是 polymer entity 的一维残基顺序。蛋白质序列使用氨基酸字母，RNA 和 DNA 序列使用核苷酸字母。

mmCIF 中与完整序列相关的常见位置包括：

- `_entity_poly`：保存 polymer 类型和一字母序列；
- `_entity_poly_seq`：逐残基保存 entity 内的序列位置和单体名称；
- `_pdbx_poly_seq_scheme`：连接规范序列编号、chain、作者残基编号和插入码。

### 7.1 原始序列和规范序列

含有修饰残基的 polymer entity 可能同时存在更接近原始单体组成的序列，以及映射到标准氨基酸或标准核苷酸字母的规范序列。

例如，硒代甲硫氨酸 `MSE` 在原子坐标中仍可以保留 `MSE` 的残基名称，但规范蛋白质序列通常把它映射到标准甲硫氨酸 `M`。未来用于 MMseqs2 或蛋白质语言模型的 FASTA 应采用经过明确规则得到的规范序列，同时在 manifest 中保留原始单体和规范化来源，避免把修饰残基的处理藏起来。

### 7.2 序列不是“把有坐标的残基拼起来”

完整序列不能通过遍历现有原子坐标、再把出现过的残基名称拼接而成。原因是实验结构经常缺少部分残基坐标。

假设 entity 的完整序列长度为 100，但原子模型只解析出序列位置 4～92：

```text
完整序列：位置 1 ........................................ 100
有坐标残基：    位置 4 .......................... 92
```

语言模型仍然可以为全部 100 个残基生成特征；只有位置 4～92 中实际出现的原子能够建立“原子 → 序列残基”映射。

## 8. chain：同一种分子的结构副本

chain 表示 polymer entity 在沉积坐标中的一个具体实例。

考虑一个同源二聚体：

```text
entity 1：蛋白质序列 MKTLLV...，长度 238
├── chain A：entity 1 的第一个坐标副本
└── chain B：entity 1 的第二个坐标副本
```

chain A 和 chain B 引用同一个 entity，因此通常具有同一条完整序列。没有必要为了语言模型把完全相同的 entity 序列重复计算两次；可以计算一次 `(238,H)` 的逐残基特征，再让两个 chain 的原子共同引用它。

### 8.1 `label_asym_id` 和 `auth_asym_id`

mmCIF 常同时保存两种 chain 标识：

- `label_asym_id`：mmCIF 数据模型使用的规范 chain 标识；
- `auth_asym_id`：结构作者在原始提交或论文中使用的 chain 标识。

两者经常相同，但不能假定永远相同。程序内部应使用 `label_asym_id` 建立稳定关系，同时保留 `auth_asym_id`，方便读者与原论文、可视化软件和作者编号对应。

`_struct_asym.id` 通常对应 `label_asym_id`，`_struct_asym.entity_id` 指明该 chain 引用哪个 entity。

### 8.2 chain 与 biological assembly

沉积态非对称单元中的 chain 是 mmCIF 直接保存的结构副本。biological assembly 还可能通过旋转、平移或对称操作产生更多副本。

AdaLigand 当前使用沉积态非对称单元，不生成 assembly 额外副本。因此序列和原子映射首先只需要覆盖 `_atom_site` 中实际存在的 `label_asym_id`。

## 9. residue：chain 中对应某个序列位置的残基

蛋白质中的氨基酸、RNA/DNA 中的核苷酸都是 residue，也就是残基。

残基身份通常需要组合多个字段才能唯一解释：

- 它属于哪个 entity；
- 它属于哪个 chain；
- 它在规范序列中的位置；
- 它使用什么单体名称；
- 作者为它指定了什么编号和插入码。

### 9.1 `label_seq_id`：规范序列位置

`label_seq_id` 表示残基在 polymer entity 序列中的规范位置。它最适合用来连接完整序列和语言模型特征。

如果语言模型特征数组采用 Python/NumPy 的零基下标，则通常有：

```text
sequence_residue_index = label_seq_id - 1
```

该换算只有在 `label_seq_id` 合法、并且它与当前 entity 序列契约一致时才能使用。不能对缺失、非法或越界的值静默猜测。

### 9.2 `auth_seq_id`：作者残基编号

`auth_seq_id` 是结构作者使用的残基编号。它可能：

- 不从 1 开始；
- 中间跳号；
- 使用负数；
- 与规范序列位置不同；
- 与插入码组合成 `101A` 等编号。

因此 `auth_seq_id` 适合人类查阅和与论文对应，不适合直接作为语言模型特征数组的下标。

### 9.3 `label_comp_id`：残基或单体名称

`label_comp_id` 保存残基的化学组分名称，例如：

- 标准氨基酸 `ALA`、`GLY`、`LYS`；
- 标准核苷酸 `A`、`C`、`G`、`U`、`DA`、`DC`、`DG`、`DT`；
- 修饰残基 `MSE` 等。

同一个序列位置的坐标残基名称和规范 FASTA 字母不一定完全相同。映射时应依据 mmCIF 的 entity 和序列编号关系，不应只比较三字母残基名称。

## 10. atom：具有三维坐标的最小记录

mmCIF 的 `_atom_site` 表中，一项原子记录通常包含：

- `label_entity_id`：该原子属于哪个 entity；
- `label_asym_id`：该原子属于哪个规范 chain；
- `label_seq_id`：该原子属于 entity 序列中的哪个位置；
- `label_comp_id`：该原子所在残基的名称；
- `label_atom_id`：原子名称，例如 `CA`、`N`、`C`、`O`；
- `auth_asym_id`、`auth_seq_id`：作者使用的 chain 和残基编号；
- `Cartn_x`、`Cartn_y`、`Cartn_z`：原子的笛卡尔世界坐标。

例如：

```text
label_entity_id = 1
label_asym_id = B
label_seq_id = 57
label_comp_id = ALA
label_atom_id = CA
Cartn_x, Cartn_y, Cartn_z = 12.3, -4.5, 18.9
```

其含义是：

```text
entity 1 定义的聚合物分子
→ chain B 这个具体结构副本
→ 规范序列中的第 57 个残基
→ 该残基的 CA 原子
→ 世界坐标 (12.3, -4.5, 18.9) Å
```

## 11. 一条序列可以对应多个 chain，但一个原子只对应一个结构位置

entity、chain、residue 和 atom 的关系可以概括为：

```text
一个 polymer entity
├── 一条完整规范序列
├── 零个、一个或多个 chain 副本
│   ├── chain A
│   │   └── 若干有坐标的 residue 和 atom
│   └── chain B
│       └── 若干有坐标的 residue 和 atom
└── 一份可复用的逐残基语言模型特征
```

一个受体原子只属于一个 chain、一个 entity 和一个序列位置。一个序列残基却可能有以下三种情况：

1. 在一个 chain 中具有多个原子；
2. 在多个同序列 chain 副本中分别具有原子；
3. 因实验坐标缺失，在任何 chain 中都没有原子。

## 12. non-polymer 和 branched ligand 与 polymer receptor 的区别

AdaLigand 当前把 `entity.type == polymer` 的重原子作为受体原子。配体 occurrence 主要来自 `non-polymer` 和 `branched` entity 中符合筛选条件的原子。

因此：

- 受体蛋白质、RNA 和 DNA 适合使用 polymer entity 序列；
- 小分子和金属离子没有蛋白质或核酸意义上的 polymer sequence；
- 糖链虽然由多个糖残基组成，但其分支化学结构不能直接按蛋白质 FASTA 处理；
- 配体语言模型通常读取 SMILES 或配体图，而不是受体 FASTA。

“同一个 ligand entity”也不等于“只有一个 ligand occurrence”。例如同一种 ATP 可以在结构中出现三次，每次具有不同空间坐标，但共享同一种化学身份。

## 13. `sequence_id` 是 AdaLigand 建立的连接标识

`sequence_id` 不是必须照搬 PDB 中某一个现成字段，而是 AdaLigand 为连接 FASTA、PDB entity、chain、原子映射和语言模型特征定义的稳定字符串。

一种清楚的形式是：

```text
{pdb_id}:entity:{entity_id}
```

例如：

```text
7abc:entity:1
```

它表示 PDB `7abc` 中 `entity_id=1` 的聚合物序列。该标识在冻结的 mmCIF 来源内稳定；如果未来更换 PDB source revision，应重新核对 entity 编号、序列内容和来源摘要。

sequence 内容相同的不同 PDB entity 仍然具有不同 `sequence_id`。如果语言模型特征需要跨 PDB 去重，可以另外根据“polymer 类型 + 规范序列内容 + 模型身份”计算 `sequence_key`；不要让内容去重键取代 PDB 内的 entity 身份。

## 14. FASTA 应该按 polymer entity 保存一次

未来生成的蛋白质、RNA 和 DNA FASTA 建议每个 polymer entity 只写一条记录，不因为相同 entity 在结构中有多个 chain 而重复写入。

示例 FASTA：

```text
>7abc:entity:1 pdb_id=7abc entity_id=1 polymer_type=protein chains=A,B
MKTLLV...
```

配套 manifest 保存机器可读字段：

```json
{
  "sequence_id": "7abc:entity:1",
  "pdb_id": "7abc",
  "entity_id": "1",
  "polymer_type": "protein",
  "chain_ids": ["A", "B"],
  "sequence_length": 238,
  "sequence": "MKTLLV..."
}
```

如果未来某个外部工具必须接受逐 chain FASTA，可以从 manifest 展开 chain 记录，但语言模型特征仍可以按 entity 序列计算一次并复用。

## 15. AdaLigand 当前 `receptor_tokens.npz` 已经保存什么

当前 `parse/{pdb_id}/receptor_tokens.npz` 的主要受体字段包括：

| 字段 | 数据类型与形状 | 具体含义 |
|---|---|---|
| `coords` | `float32 (N,3)` | `N` 个受体重原子的世界 XYZ 坐标，单位 Å |
| `element` | `uint8 (N,)` | 每个受体原子的原子序数 |
| `res_type` | `uint8 (N,)` | 每个原子的 AdaLigand 残基类型编号 |
| `is_backbone` | `bool (N,)` | 每个原子是否属于蛋白质或核酸主链 |
| `atom_name` | `S4 (N,)` | 每个受体原子的规范原子名称 |
| `res_index` | `int32 (N,)` | 当前有坐标受体残基的连续编号 |
| `chain_index` | `int32 (N,)` | 当前有坐标 chain 的连续编号 |
| `bond_index` | `int32 (2,E)` | 受体化学键的两端原子下标 |
| `bond_type` | `uint8 (E,)` | 每条受体化学键的类型编号 |
| `feat` | `float32 (N,49)` | 每个受体原子的 49 维基础特征 |

这里的 `res_index` 只编号当前原子模型中实际出现的残基，不等于完整 entity 序列位置。`chain_index` 也只是整数编号；当前文件没有独立保存这个编号对应哪个 `label_asym_id`、哪个 entity 和哪条完整序列。

因此，仅凭现有 `receptor_tokens.npz` 不能可靠完成“受体原子 → 完整序列残基”的映射。

## 16. AdaLigand 建议新增的序列与 chain 清单

建议为每个 PDB 新增：

```text
parse/{pdb_id}/receptor_sequences.json
```

该文件保存不同于逐原子数组的 entity 和 chain 表。建议结构如下：

```json
{
  "schema_version": 1,
  "pdb_id": "7abc",
  "entities": [
    {
      "entity_index": 0,
      "entity_id": "1",
      "sequence_id": "7abc:entity:1",
      "polymer_type": "protein",
      "canonical_sequence": "MKTLLV...",
      "sequence_length": 238
    }
  ],
  "chains": [
    {
      "chain_index": 0,
      "label_asym_id": "A",
      "auth_asym_id": "A",
      "entity_index": 0
    },
    {
      "chain_index": 1,
      "label_asym_id": "B",
      "auth_asym_id": "B",
      "entity_index": 0
    }
  ]
}
```

字段关系为：

- `entities[entity_index]` 保存一条 polymer entity 的完整序列；
- `chains[chain_index]` 保存一个沉积态 chain；
- `chains[chain_index].entity_index` 指向该 chain 复用的 entity 序列；
- `chain_index` 应与 `receptor_tokens.npz` 现有逐原子 `chain_index` 数值一致。

## 17. 建议原地追加到 `receptor_tokens.npz` 的映射字段

逐原子映射适合追加到现有 `receptor_tokens.npz`，因为它们与现有 `coords` 等字段共享相同的原子行序：

| 新字段 | 数据类型与形状 | 具体含义 | 特殊值 |
|---|---|---|---|
| `sequence_entity_index` | `int32 (N,)` | 第 `i` 个受体原子引用 `receptor_sequences.json::entities` 中的哪一项 | 无法映射时为 `-1` |
| `sequence_residue_index` | `int32 (N,)` | 第 `i` 个受体原子对应 entity 规范序列中的零基残基位置 | 无法映射时为 `-1` |

对于一项合法映射，必须满足：

```text
0 <= sequence_entity_index[i] < len(entities)
0 <= sequence_residue_index[i] < entities[sequence_entity_index[i]].sequence_length
```

同一残基中的多个原子具有相同的 `sequence_entity_index` 和 `sequence_residue_index`。同一个 entity 的不同 chain 副本也可以引用相同的 entity 序列位置，但它们的 `chain_index` 不同，三维坐标也不同。

不建议把完整序列字符串或语言模型特征直接复制到每个原子。这样会重复存储同一残基特征，并模糊“entity 序列”和“原子坐标”两种不同粒度。

## 18. 全量 FASTA 和 sequence manifest 的建议位置

每个 PDB 的 `receptor_sequences.json` 便于局部读取；全量去冗余和批量语言模型推理还需要聚合产物：

```text
sequences/
├── protein.fasta
├── rna.fasta
├── dna.fasta
└── sequence_manifest.jsonl
```

`sequence_manifest.jsonl` 每项对应一个 polymer entity，至少包含：

| 字段 | 具体含义 |
|---|---|
| `sequence_id` | AdaLigand 定义的 entity 序列标识 |
| `pdb_id` | 来源 PDB 标识，小写保存 |
| `entity_id` | mmCIF entity 编号 |
| `polymer_type` | 明确的蛋白质、RNA、DNA 或其他聚合物类型 |
| `chain_ids` | 引用该 entity 的 `label_asym_id` 列表 |
| `sequence_length` | 规范序列残基数 |
| `canonical_sequence` | 实际写入 FASTA 的规范序列 |
| `source_manifest_sha256` | 冻结 mmCIF 来源的摘要或可定位该来源的等价信息 |

蛋白质、RNA 和 DNA 分开写 FASTA，避免外部程序隐式混合不同字母表。DNA/RNA hybrid 应在正式实现前确定归类规则，不能根据字符内容临时猜测。

## 19. 语言模型特征应按序列残基保存

蛋白质或核酸语言模型为完整序列生成逐残基特征。建议按去重后的 `sequence_key` 和明确的模型身份保存：

```text
receptor_language_models/{model_identity}/{sequence_key}.npz
```

建议字段包括：

| 字段 | 数据类型与形状 | 具体含义 |
|---|---|---|
| `features` | `float16/float32 (L,H)` | 序列中 `L` 个残基的 `H` 维语言模型特征 |
| `valid_mask` | `bool (L,)` | 每个序列位置是否成功得到可用特征 |
| `sequence_id` 或引用清单 | 字符串或清单字段 | 哪些 PDB entity 引用该序列特征 |
| `model_name` | 字符串标量 | 使用的语言模型名称 |
| `model_revision` | 字符串标量 | checkpoint 或代码 revision |
| `sequence_sha256` | 字符串标量 | 实际输入规范序列的 SHA-256 |
| `feature_dtype` | 字符串标量 | 正式保存的数据类型 |

其中 `L` 必须等于 manifest 中的 `sequence_length`。长序列如果需要分窗推理，必须记录窗口、重叠区域聚合方式和没有成功生成特征的位置，不能把截断后的特征伪装成完整序列特征。

## 20. 从一个受体原子读取语言模型特征

设 `i` 是 `receptor_tokens.npz` 中的受体原子下标。完整读取过程为：

```text
1. 读取 sequence_entity_index[i]
2. 在 receptor_sequences.json::entities 中找到对应 entity
3. 通过 entity 的 sequence_id 或 sequence_key 找到语言模型特征文件
4. 读取 sequence_residue_index[i]
5. 取得 features[sequence_residue_index[i]]
```

用公式表示：

$$
f_i^{\mathrm{LM}}
=
F_{e_i}[r_i],
$$

其中：

- $i$ 是受体原子下标；
- $e_i$ 是 `sequence_entity_index[i]`；
- $r_i$ 是 `sequence_residue_index[i]`；
- $F_{e_i}\in\mathbb{R}^{L_{e_i}\times H}$ 是对应 entity 序列的逐残基语言模型特征；
- $f_i^{\mathrm{LM}}\in\mathbb{R}^{H}$ 是该受体原子引用的残基特征。

同一残基的多个原子会读取同一个 $f_i^{\mathrm{LM}}$。模型仍可通过原子元素、原子名称、空间坐标和现有 49 维特征区分这些原子。

## 21. 映射校验需要回答的问题

每个 PDB 的序列与原子映射至少需要检查：

1. 每个 polymer chain 都能找到明确的 entity；
2. 每个 entity 都有明确的 polymer 类型和规范序列；
3. 每个有效 `sequence_residue_index` 都位于对应序列的合法范围内；
4. 同一坐标残基的全部原子映射到同一个序列位置；
5. `chain_index` 能在 chain 表中找到唯一记录；
6. chain 表中的 `entity_index` 与原子的 `sequence_entity_index` 一致；
7. 规范序列长度与逐残基语言模型特征的第一维一致；
8. 没有原子坐标的序列残基允许存在，不把它们判为映射错误；
9. 有原子但缺少合法 entity 或序列位置的情况必须记录，不能回退到作者编号猜测；
10. 修饰残基、插入码和序列规范化都保留可追溯来源。

这些检查用于生成诊断和 `info.json` 问题记录，不自动替代用户对整批产物是否可以继续使用的判断。

## 22. 一个完整示例

假设 PDB `7abc` 包含一个蛋白质同源二聚体和一条 RNA：

```text
entity 1：protein，长度 100
├── chain A
└── chain B

entity 2：RNA，长度 24
└── chain C
```

`receptor_sequences.json` 中有两个 entity 和三个 chain。蛋白质 entity 只保存一次序列。

假设 `receptor_tokens.npz` 的第 500 个原子具有：

```text
chain_index = 1
sequence_entity_index = 0
sequence_residue_index = 56
atom_name = CA
```

其含义是：

```text
第 500 个受体原子
→ chain 表中的第 1 项，也就是 chain B
→ entity 表中的第 0 项，也就是 protein entity 1
→ 规范序列的零基位置 56，也就是一基 label_seq_id 57
→ 读取蛋白质语言模型 features[56]
```

假设 chain A 中同一个序列位置也有 `CA` 原子，它的 `chain_index` 不同，但 `sequence_entity_index` 和 `sequence_residue_index` 可以相同。两个原子共享序列先验，却保留各自独立的三维坐标。

## 23. 容易犯的错误

- 把 chain 当成一种独立序列，导致同源多聚体重复计算完全相同的语言模型特征；
- 把 `res_index` 当成完整序列下标，忽略它只编号有坐标的残基；
- 使用 `auth_seq_id` 直接索引语言模型数组，导致跳号和插入码错位；
- 从坐标残基临时拼 FASTA，丢失没有坐标的残基；
- 只比较残基名称建立映射，无法正确处理修饰残基；
- 把完整序列或逐残基特征复制到每个原子，造成大量重复存储；
- 把 biological assembly 生成副本与沉积态 chain 混为一谈；
- 把 PDB entity 身份键与跨 PDB 序列内容去重键混为一谈；
- 语言模型截断长序列后仍声明得到完整残基特征；
- 发现映射缺失后静默使用作者编号或坐标顺序猜测。

## 24. 当前讨论结论和未决问题

当前可以形成的建议结论是：

1. 蛋白质、RNA 和 DNA 的规范序列按 polymer entity 保存一次；
2. chain 表记录每个沉积态 chain 引用哪个 polymer entity；
3. `receptor_tokens.npz` 原地追加逐原子的 `sequence_entity_index` 和 `sequence_residue_index`；
4. 完整序列保存在 `receptor_sequences.json` 和全量 FASTA/manifest 中；
5. 语言模型特征按序列残基保存，不复制成逐原子数组；
6. 原子通过 entity 下标和序列位置读取对应残基特征；
7. 没有坐标的序列残基仍保留语言模型特征；
8. 无法建立可靠映射的原子使用 `-1` 并记录具体原因，不猜测回退。

正式实现前仍需决定：

- `receptor_sequences.json` 是否采用该文件名和字段名；
- DNA/RNA hybrid 的正式分类；
- 使用原始一字母序列还是规范一字母序列作为各类模型的具体输入；
- 修饰残基无法规范化时使用未知字符、排除 entity 还是采用其他策略；
- 首批受体语言模型的名称、checkpoint revision、最大长度和长序列分窗方式；
- `sequence_key` 的精确计算公式以及语言模型特征保存为 `float16` 还是 `float32`。
