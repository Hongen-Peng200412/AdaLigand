# 诊断 ligand_object

## 结论

本次审计确认：当前语言准备管线按 occurrence（一个 PDB 中的一次具体配体出现）生成字符串，不能让一个 `object_key`（Stage C 配体解析阶段分配给可复用配体模板的键）唯一决定一个模型输入字符串。这里的核心歧义只按 [`产物字段参考.md`](../Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/产物字段参考.md) 第 47 行的 `smiles` 字段定义：同一 `object_key` 是否对应两个及以上非空 `smiles`。沉积坐标、`present` 掩码（模板各原子是否在该 occurrence 中被观测到的布尔标记）、坐标所对应的沉积原子选择，以及只改变立体信息却不改变该字段的情况，均不属于本次核心歧义。

但是，审计不支持把根因简单归结为“BRANCHED 内部连接端点通常不能唯一决定缩合离去原子”。BRANCHED 指由多个 CCD（PDB 化学组件字典中的标准组件）连接形成的配体；leaving atom 指 CCD 标为成键时离去的原子。在当前 692 个 BRANCHED 键涉及的 5,698 个连接端点中，没有任何端点邻接多个 leaving-atom 连通组。25 个多字符串键中，23 个键的 106 个端点都能各自唯一推出相邻离去组；其中 22 个键没有组间复用，1 个双 NAG 键让两条连接复用同一个 leaving 组。另 2 个 KC2/LMG 键的 4 个端点没有相邻 leaving 标志。也就是说，最初的离去原子多义性假设在当前多字符串对象的大多数样本上被反证。

更符合全部证据的根因是化学语义没有对齐：当前 `object_key` 的生成载荷描述完整 CCD 组分及配体内部连接端点，而正式语言输入来自 occurrence 对应的 pdbeccdutils CLC（该工具从结构文件识别和重建的共价连接配体）分子。CLC 会反映具体绑定形式、缺失原子或键重建质量；它不等于“只按内部连接端点组装的完整 CCD 分子”。两种对象被同一个 `object_key` 关联，却没有被要求产生同一个 `smiles`。

审计得到以下事实：

- 正式语言模型准备产物覆盖 22,386 个 PDB、677,835 个 occurrence，所有 occurrence 的 `smiles` 都非空。语言模型范围内共有 3,782 个 `object_key`，其中 3,126 个 CCD、656 个 BRANCHED。
- 25 个 `object_key` 对应多个 `smiles`，全部为 BRANCHED；CCD 为 0。歧义比例是全部语言模型对象的 0.661%，或 BRANCHED 对象的 3.811%。
- 这 25 个键覆盖 34,907 个 occurrence，占全部 occurrence 的 5.150%，占 BRANCHED occurrence 的 84.040%。但其中 34,789 个使用各自键的最高频字符串，只有 118 个使用少数变体。少数变体只占全部 occurrence 的 0.0174%，占 BRANCHED occurrence 的 0.2841%。因此“落在歧义身份内”和“实际使用少数字符串”必须分开理解。
- 25 个键共出现 66 个不同 `smiles`。其中 9 个字符串是断开的多片段图，涉及 45 个 occurrence；去掉这些明显的 CLC 图质量异常后，仍有 19 个键对应多个连通字符串，不能用输入质量异常完全解释。
- 25 个键的 34,907 个 occurrence 中，33,799 个标记为外部共价、1,108 个标记为非共价；118 个少数变体却几乎对半分布为 58 个共价和 60 个非共价。11 个键同时出现两种共价状态，只有 1 个键的字符串集合能被该状态完全分开。外部共价连接是局部来源，不是全部多值的唯一解释。
- 对 22 个端点离去组唯一且互不复用的键，审计原型从完整 CCD 删除这些 leaving 组并添加内部单键，22 个都生成单一连通分子。其中只有 3 个组装字符串等于当前主流 CLC 字符串，5 个等于少数非共价字符串，另 14 个在正式 CLC 字符串集合中从未出现。这个结果证明“完整内部装配对象”和“具体 occurrence CLC”并不是同一化学对象；它不证明审计原型已经是可直接上线的化学真值。
- 不同字符串确实产生不同向量。相同字符串的 112 组重复向量逐元素完全相同；不同字符串的 94 组配对中，MoLFormer 余弦距离中位数为 0.03889、最大值为 0.70553，SMI-TED Light 289M 中位数为 0.001984、最大值为 0.02951。最大的差异由断图字符串产生；只比较两侧都连通的 72 组，MoLFormer 余弦距离中位数、95% 分位数、最大值分别为 0.03217、0.09327、0.20343，SMI-TED 分别为 0.001679、0.003074、0.005990。
- 当前 Matcher `closed_set_v2` 清单没有触达这 25 个键。`closed_set_v3` 的 2,013 条 PDB 内身份记录中有 211 条属于 11 个歧义糖类键；但是两种语言模型在当前冻结清单中都只实际选择了各键的同一个主流字符串，train 与 validation 没有选择不同字符串。当前 v3 清单没有把少数变体混入训练与验证，但扩大 PDB 范围后不再有这一保证。
- 当前数据中没有发现六位十六进制拓扑哈希碰撞，也没有发现 `safe_object_key` 文件名碰撞。哈希碰撞不是这 25 个歧义键的原因。

因此，本问题是真问题，但严重程度不能用一个百分比概括：

| 评价层面 | 结论 | 依据 |
| --- | --- | --- |
| 语言输入契约 | 严重 | 一个被文档定义为“配体化学结构键”的 `object_key` 不能唯一决定当前 occurrence CLC `smiles`。不能继续把两者无条件当作同一层身份。 |
| 内部离去原子假设 | 多数不成立 | 25 个多字符串键中有 23 个的每个内部连接端点都能各自唯一推出 leaving 组；其中 1 个存在组间复用。全体 692 个 BRANCHED 键没有发现一个端点邻接多个候选组。 |
| 对象覆盖 | 有限但不可忽略 | 25/3,782 个语言模型对象，BRANCHED 内为 25/656。 |
| occurrence 暴露 | 很高 | 高频糖链使 84.040% 的 BRANCHED occurrence 属于歧义键。 |
| 实际少数变体 | 低 | 相对每个键的最高频字符串，仅 118/41,536 个 BRANCHED occurrence 使用少数变体。 |
| 向量后果 | 多数温和，尾部很大 | 连通变体通常比普通跨对象差异小；断图变体会达到典型跨对象差异量级。 |
| 当前 Matcher v3 | 目前未形成 train/validation 字符串冲突 | 211 条受触达身份全部选择同一主流字符串；该结论只适用于当前冻结清单。 |

建议在下一次把语言向量按全局身份去重之前先决定目标化学对象：如果目标是完整、可跨 PDB 去重的配体内部装配体，应从 CCD 与内部连接端点确定性构造一个对象级字符串，不应从 occurrence CLC 随机或固定挑一条；如果目标是具体绑定状态或具体 occurrence 化学图，则必须增加 occurrence 化学变体键，不能再要求当前 `object_key` 单独唯一。现有 occurrence 级语言模型产物不必仅因本次审计立即整体作废。

## 审计边界与统计口径

### 核心歧义

核心判断只读取正式 `prepared_smiles.jsonl` 的：

```text
(object_key, smiles)
```

若一个 `object_key` 对应至少两个不同的非空 `smiles`，则记为一个歧义对象。该字段是 RDKit 生成的 canonical non-isomeric SMILES，即规范化且不保留立体标记的字符串；它是 CPU 准备阶段交给两个模型公开接口的输入。MoLFormer 的 `model_smiles` 与该字段相同；SMI-TED 还会执行官方规范化，所以 `model_smiles` 和向量只用于衡量后果，不用于反向定义核心歧义。

本次统计没有把下列差异记为核心歧义：

- `ligand_coords.npz` 中的坐标差异；
- `present_{candidate_id}` 掩码差异；
- 沉积原子选择本身，除非它已经使本节定义的 `smiles` 发生变化；
- 只改变 canonical isomeric SMILES、但不改变正式 `smiles` 的立体差异；
- Stage3 是否因重原子坐标完整性而接受一个 occurrence。

### 三种不同分母

为了避免“84.040%”被误读，本报告同时使用三种分母：

1. 对象分母：一个 `object_key` 计一次，用于判断去重身份定义覆盖了多少种对象。
2. 身份成员 occurrence 分母：只要 occurrence 的 `object_key` 属于 25 个歧义键，就计入 34,907；这反映歧义身份被复用得多广。
3. 少数变体 occurrence 分母：对每个歧义键取最高频 `smiles`，其余字符串的 occurrence 合计为 118；这反映如果把最高频字符串暂当参考，实际有多少实例不同。

最高频不等于化学真值。它只用于估计实操规模，不能作为修复时自动保留字符串的充分理由。例如 `BRANCHED:NAG-NAG-BMA-BMA-BMA:e370f6` 的最高频字符串本身就是断图字符串。

## 当前设计为何不能保证唯一 `smiles`

### `object_key` 的生成载荷是组分序列和跨残基连接端点

[`pipeline.py`](../Data_Preprocessing/Ori_Data/adaligand_preprocessing/stages/stage_c/pipeline.py) 的 `build_object_key` 在第 861—880 行执行以下规则：

```python
ccds = [rkey[1] for rkey in group_residues]
digest_source = json.dumps({"ccds": ccds, "bonds": sorted(inter_bonds)}, sort_keys=True)
bond_hash = hashlib.md5(digest_source.encode("utf-8")).hexdigest()[:6]
```

BRANCHED 键因此能区分组分 CCD 顺序和跨残基键端点，但没有显式编码下列事实：

- 缩合后实际保留或离去的组分内原子；这些原子有时可以从 CCD 标志和连接端点确定性推导，并不必然构成信息缺失；
- occurrence 对应 CLC 的完整原子集合；
- CLC 的组分内键是否完整；
- CLC 产生的分子式、连接片段数和最终 canonical SMILES；
- 外部化学包版本和重建结果。

六位后缀只有 24 bit，理论上不是无碰撞身份。本次全量数据中，692 个 BRANCHED 拓扑键没有出现相同 `object_key` 对应不同 `{ccds, inter_bonds}` 的实测碰撞；3,833 个 Stage C 键也没有产生 `safe_object_key` 文件名碰撞。它们是应当单独加固的风险，不是本次 25 个多字符串对象的原因。

对正式 CCD pickle 的 leaving-atom 标志做端点审计后，得到 203 个 CCD、692 个 BRANCHED 键、5,698 个连接端点的结果：

| 端点状态 | 端点数 |
| --- | ---: |
| 唯一邻接一个 leaving 连通组 | 4,814 |
| 没有邻接 leaving 组 | 836 |
| 连接端点自身被标为 leaving | 48 |
| 邻接多个 leaving 连通组 | 0 |

692 个对象中，389 个的全部端点都有唯一邻接组，187 个完全没有相邻 leaving 证据，70 个混合了唯一端点和无证据端点，36 个存在“端点自身被标为 leaving”等异常，10 个让多个连接端点复用同一 leaving 组。

25 个多字符串对象的结果更集中：23 个对象的 106 个端点都分别唯一；其中 22 个对象没有组间复用，`BRANCHED:NAG-NAG:193493` 的 4 个端点虽然分别唯一，但两条连接复用了同一 NAG `C1` 邻接组。另 2 个 KC2/LMG 对象的 4 个端点都没有相邻 leaving 标志。没有一个多字符串对象出现“单端点有多个候选 leaving 组”。

### BRANCHED LigandObject 是完整 CCD 模板的拼接，不是缩合后的唯一分子

[`ligand_objects.py`](../Data_Preprocessing/Ori_Data/adaligand_preprocessing/stages/stage_c/ligand_objects.py) 的 `process_branched_ligand` 在第 407—421 行读取每个完整 CCD、去除显式氢、复制全部组分内原子和键；第 423—456 行再添加声明的跨残基单键。该过程没有删除缩合离去原子。生成的 BRANCHED `LigandObject.smiles` 在第 463—472 行固定为空字符串。

这个对象非常适合作为 occurrence 坐标对齐所需的完整原子模板，但它不是“缩合后唯一实际分子”的充分定义。当前名称把“可复用原子模板”和“精确化学身份”混成了同一层。

### 语言模型刻意使用 occurrence 级 CLC

[`AdaLigand_v3基础数据升级计划.md`](AdaLigand_v3基础数据升级计划.md) 第 510—518 行明确规定：处理单位是 `(pdb_id, candidate_id)`，相同 `object_key` 的不同 occurrence 分别准备 SMILES。BRANCHED 优先使用完整 mmCIF 中唯一残基身份精确匹配的 CLC；没有可用 CLC 时才用 `present` 图。

[`clc_assembly.py`](../Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/clc_assembly.py) 第 103—180 行直接采用 pdbeccdutils CLC 组件的 RDKit 分子；第 213—296 行只用完整残基身份多重集合选择唯一 CLC。跨残基连接比较只记录诊断，不改变 CLC 选择。文件自身也在第 120 行声明，外部包的形式电荷和键级不被视为唯一化学真值。

[`ligand_preparation.py`](../Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/ligand_preparation.py) 第 260—280 行只要选中的 CLC 能生成非空字符串，就直接采用 `smiles_source=clc`。当前没有拒绝“BRANCHED CLC 却含多个断开片段”的质量门槛，也不会因连接核验失败而放弃该字符串。

所以当前关系实际是：

```text
object_key
  = 完整 CCD 组分序列 + 配体内部跨残基连接端点的短哈希

smiles
  = 当前 occurrence 的唯一匹配 CLC 所生成的规范化非立体字符串，可能反映具体绑定状态和 CLC 重建质量
```

两者指向的化学对象不同。即使内部 leaving 组可以从前者唯一推出，后者仍会因具体 occurrence CLC 而变化；当前实现没有规定它们必须相等。

## 全量统计结果

### 输入完整性

第一轮作业逐个读取正式数据根中的四类文件：

| 输入 | 成功读取的 PDB 文件数 |
| --- | ---: |
| Stage C `occurrences.jsonl` | 22,386 |
| `prepared_smiles.jsonl` | 22,386 |
| MoLFormer `results.jsonl` | 22,386 |
| SMI-TED Light 289M `results.jsonl` | 22,386 |

解析失败、身份字段不一致、按当前规则重建的 `object_key` 不一致均为 0。正式 `smiles` 为空的 occurrence 为 0。

Stage C 全部 occurrence 共引用 3,833 个键；其中 51 个键只出现在 `type_tag=other` 的 161 个 occurrence 中，没有进入正式语言模型集合。语言模型统计因此使用 3,782 个有正式 `smiles` 的键作为对象分母。

### 对象与 occurrence 比例

| 指标 | 数量 | 比例 |
| --- | ---: | ---: |
| 全部有正式 `smiles` 的对象 | 3,782 | 100% |
| 全部歧义对象 | 25 | 0.661% |
| BRANCHED 有正式 `smiles` 的对象 | 656 | 100% |
| BRANCHED 歧义对象 | 25 | 3.811% |
| 全部 occurrence | 677,835 | 100% |
| 属于歧义对象的 occurrence | 34,907 | 5.150% |
| BRANCHED occurrence | 41,536 | 100% |
| 属于歧义对象的 BRANCHED occurrence | 34,907 | 84.040% |
| 少数变体 occurrence | 118 | 全部的 0.0174%；BRANCHED 的 0.2841% |

语言模型范围内共有 62,013 个 `(pdb_id, object_key)` 组合，其中 BRANCHED 为 8,168 个。只有 17 个组合在同一 PDB 内已经出现多个 `smiles`，占全部组合的 0.0274%，占 BRANCHED 组合的 0.2081%。因此 Matcher 旧日志中的“PDB 内多字符串身份数为 0”不能替代全局审计，但同一 PDB 内冲突本身确实很少。

若在每个歧义键内独立均匀抽取两个 occurrence，它们字符串不同的 occurrence 加权概率为 0.6282%；若按所有同键 occurrence 对的数量加权，字符串不同的配对比例为 0.4852%。这再次说明高频对象虽然存在多值，但主流字符串占比很高。

### 类型和字符串来源

| `type_tag` | 歧义对象数 | 属于歧义对象的 occurrence 数 |
| --- | ---: | ---: |
| `sugar` | 20 | 34,885 |
| `small_molecule` | 2 | 11 |
| `peptide_like` | 3 | 11 |

25 个对象的 34,907 个 occurrence 全部使用 `smiles_source=clc`，没有 CCD 路径或 `present_graph` 后备路径。所有记录的 CLC 残基身份精确匹配数都是 1；34,898 条的跨残基连接核验为 `true`，9 条为 `false`。因此歧义不是由“多个 CLC 随机任选”或 present 后备图造成的。

外部共价标志与字符串存在关联，但不能把多值完整分开：

| 范围 | `is_covalent=true` | `is_covalent=false` |
| --- | ---: | ---: |
| 25 个歧义键的全部 occurrence | 33,799 | 1,108 |
| 118 个少数变体 occurrence | 58 | 60 |

25 个键中有 11 个同时出现共价和非共价 occurrence。10 个键至少有一个相同字符串跨两种状态复用，只有 `BRANCHED:NAG-NAG-MAN-MAN:dda045` 的两种字符串被共价状态完全分开。因此“同键混入外部共价和非共价形式”是一个已证实的局部机制，但不是其余 24 个键的充分分类规则。

### 确定性 CCD 重组试验

对 22 个内部端点都有唯一 leaving 组且不同连接不复用该组的对象，审计原型执行以下过程：读取完整含氢 CCD；删除每个端点唯一邻接的 leaving 连通组；对每条 `inter_bond` 添加单键；sanitize 后生成 canonical non-isomeric SMILES。该原型没有处理金属、端点自身被标为 leaving 或缺少 leaving 标志的通用规则，因此只用于诊断，不是生产实现。

22 个对象全部成功生成一个连接片段，结果与 occurrence CLC 字符串集合的关系为：

| 关系 | 对象数 |
| --- | ---: |
| 等于当前最高频 CLC 字符串 | 3 |
| 等于少数 CLC 字符串 | 5 |
| 正式 occurrence 中从未出现该字符串 | 14 |

5 个“等于少数字符串”的匹配 occurrence 共 15 个，全部为 `is_covalent=false`。例如 `BRANCHED:NAG-NAG:547a2a` 按 `O4–C1` 内部连接删除 `{HO4}` 与 `{O1, HO1}` 后，确定性得到 `C16H28N2O11`，恰好匹配 5 个非共价 occurrence 的少数字符串；25,841 次最高频 CLC 字符串是 `C16H28N2O10`。这证明按 occurrence 频率选代表会偏向绑定数据中常见的 CLC 形式，不一定等于完整内部装配体。

其余 3 个对象中，2 个 KC2/LMG 键没有相邻 leaving 标志，原型没有组装；`BRANCHED:NAG-NAG:193493` 让两条键同时连接同一 NAG `C1`，复用同一 leaving 组后产生五价碳并在 sanitize 时失败。它是当前 25 个对象中真正需要额外化学规则或数据核验的内部连接特例。

### 25 个歧义对象

“少数数”表示该键总 occurrence 数减去最高频字符串次数。“断图数”表示 RDKit 判断字符串含多个连接片段的 occurrence 数。

| `object_key` | 类型 | occurrence | PDB | 字符串种数 | 少数数 | 断图数 | MoLFormer 最大余弦距离 | SMI-TED 最大余弦距离 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `BRANCHED:NAG-NAG:547a2a` | sugar | 25,904 | 3,164 | 10 | 63 | 31 | 0.52947 | 0.02510 |
| `BRANCHED:NAG-NAG-BMA:97d8a6` | sugar | 5,255 | 1,286 | 6 | 13 | 4 | 0.59504 | 0.02655 |
| `BRANCHED:NAG-NAG-BMA-MAN-MAN:b3d9fe` | sugar | 1,781 | 580 | 2 | 1 | 0 | 0.00668 | 0.00120 |
| `BRANCHED:NAG-NAG-BMA-MAN:f5c588` | sugar | 844 | 313 | 2 | 3 | 0 | 0.02335 | 0.00137 |
| `BRANCHED:NAG-NAG-MAN:62a061` | sugar | 519 | 88 | 3 | 4 | 1 | 0.59825 | 0.02697 |
| `BRANCHED:NAG-NAG-BMA-FUC:80abc7` | sugar | 222 | 95 | 2 | 2 | 2 | 0.66594 | 0.02792 |
| `BRANCHED:NAG-NAG-NAG:3bc5a7` | sugar | 157 | 74 | 2 | 2 | 0 | 0.01285 | 0.00087 |
| `BRANCHED:NAG-NAG-BMA-MAN-FUC:09704a` | sugar | 54 | 29 | 2 | 1 | 1 | 0.70553 | 0.02917 |
| `BRANCHED:NAG-NAG-MAN-MAN:4679a6` | sugar | 35 | 13 | 2 | 1 | 1 | 0.65790 | 0.02951 |
| `BRANCHED:GLC-GLC:cca284` | sugar | 28 | 15 | 2 | 1 | 0 | 0.00900 | 0.00053 |
| `BRANCHED:GAL-SIA:1001ec` | sugar | 18 | 7 | 2 | 3 | 0 | 0.01339 | 0.00053 |
| `BRANCHED:GAL-SIA:be3b94` | sugar | 14 | 4 | 2 | 5 | 0 | 0.01064 | 0.00050 |
| `BRANCHED:NAG-NAG-MAN:2d6d6c` | sugar | 12 | 8 | 2 | 1 | 0 | 0.01022 | 0.00068 |
| `BRANCHED:NAG-NAG:193493` | sugar | 9 | 5 | 2 | 1 | 0 | 0.01935 | 0.00090 |
| `BRANCHED:KC2-LMG:7b2b67` | small_molecule | 7 | 1 | 5 | 4 | 0 | 0.03374 | 0.00330 |
| `BRANCHED:NAG-NAG-BMA-BMA:379038` | sugar | 7 | 6 | 2 | 1 | 1 | 0.67829 | 0.02897 |
| `BRANCHED:SGN-IDS-SGN-IDS-SGN-IDS:49773a` | sugar | 7 | 5 | 2 | 2 | 0 | 0.01609 | 0.00561 |
| `BRANCHED:FME-PRO:12aefc` | peptide_like | 6 | 6 | 2 | 1 | 0 | 0.11303 | 0.00250 |
| `BRANCHED:BMA-MAN:54a66d` | sugar | 5 | 2 | 2 | 1 | 0 | 0.00972 | 0.00049 |
| `BRANCHED:NAG-NAG-BMA-BMA-BMA:e370f6` | sugar | 5 | 5 | 2 | 2 | 3 | 0.68939 | 0.02855 |
| `BRANCHED:NAG-NAG-BMA-BMA:313071` | sugar | 5 | 4 | 2 | 1 | 1 | 0.66381 | 0.02907 |
| `BRANCHED:LMG-KC2:901f60` | small_molecule | 4 | 1 | 2 | 2 | 0 | 0.01388 | 0.00266 |
| `BRANCHED:NAG-NAG-MAN-MAN:dda045` | sugar | 4 | 4 | 2 | 1 | 0 | 0.01575 | 0.00117 |
| `BRANCHED:PHE-FME:bbd4a6` | peptide_like | 3 | 3 | 2 | 1 | 0 | 0.07680 | 0.00157 |
| `BRANCHED:FME-PHE:63b870` | peptide_like | 2 | 2 | 2 | 1 | 0 | 0.20343 | 0.00599 |

字符串种数分布为：21 个对象各有 2 种，另有 1 个对象各有 3、5、6、10 种。

## 化学差异诊断

### 94 组字符串配对

对每个对象内部的不同字符串做两两比较，共得到 94 组：

| 差异 | 配对数 |
| --- | ---: |
| 分子式不同 | 91 |
| 重原子数不同 | 77 |
| 键数不同 | 87 |
| 连接片段数不同 | 22 |
| 形式电荷不同 | 0 |

Morgan 半径 2 指纹的 Tanimoto 相似度中位数为 0.5487，范围为 0.03125—1.0。这个分布把合理的小变化和断图异常混在一起，不能单独用于选择真值。

### 断图异常不是理论上的缩合歧义

66 个不同字符串中有 9 个由多个连接片段组成，涉及 9 个对象、45 个 occurrence。例如 `8bon` 的 candidate 6：

- `object_key=BRANCHED:NAG-NAG:547a2a`；
- CLC 残基身份精确匹配数为 1；
- 声明和观察到的跨残基连接数都为 1，连接核验为 `true`；
- 但 28 个原子只形成 1 条键，最终 `smiles` 有 27 个连接片段。

这说明当前连接核验只确认跨残基端点，不能发现组分内键全部或大部分丢失。非空字符串检查也会接收该图。22 组涉及连接片段变化的向量配对具有明显更大差异：

| 模型 | 余弦距离中位数 | 95% 分位数 | 最大值 |
| --- | ---: | ---: | ---: |
| MoLFormer | 0.56583 | 0.68884 | 0.70553 |
| SMI-TED Light 289M | 0.02574 | 0.02917 | 0.02951 |

这些是语言准备阶段的 CLC 图质量问题，不能用“同一化学身份的合理多表示”解释。

### 去掉断图后仍有真实多值

移除 9 个断图字符串后，仍有 19 个 `object_key` 对应至少两个连通字符串。以每个键最高频的连通字符串作统计参考，其余连通字符串涉及 74 个 occurrence：

- 36 个 occurrence 的分子式差只涉及 H/O，分布在 12 个对象；它们表现为缩合或质子状态差异，但端点审计已经证明这些对象的内部 leaving 组大多唯一，不能据此反推“内部端点有多个候选离去组”。
- 37 个 occurrence 还涉及 C、N、S 等其他元素变化，分布在 8 个对象；其中包括糖环或酰基原子缺失、肽样组分差异，以及 KC2/LMG 长链原子数不同。它们超出单一离去氧解释。
- 1 个 occurrence 与参考字符串分子式相同，但连接关系不同。

例如最高频糖链 `BRANCHED:NAG-NAG:547a2a` 的主流分子式是 `C16H28N2O10`，25,841/25,904 个 occurrence 使用同一字符串。其连通少数变体包括 `C16H28N2O11`、`C15H26N2O10`、`C15H26N2O8` 等，另有 31 个断图 occurrence。CCD 端点规则却能唯一构造 `C16H28N2O11`，所以该对象的多值证明 CLC 形式不统一，而不是证明 `O4–C1` 内部端点本身多义。

当前证据支持把根因拆成四层：

1. 化学对象定义错位：当前键描述完整 CCD 的内部装配模板，`smiles` 却来自具体 occurrence CLC；项目没有先决定语言向量应代表自由装配体、绑定后形式还是原样 occurrence 图。
2. occurrence CLC 变化：相同 CCD 组分和内部连接端点下，CLC 原子集合或连接关系仍会变化；外部共价状态只能解释一部分。
3. 输入质量门槛缺口：明显断开的 BRANCHED CLC 仍因字符串非空而被接收。
4. 少量内部规则例外：2 个 KC2/LMG 键缺少 leaving 标志，1 个双 NAG 键复用 leaving 组并产生非法价态；它们确实需要额外化学规则或数据修正。

本次审计没有把最高频字符串或确定性组装原型宣称为化学真值，也没有逐个检查 118 个少数 occurrence 的原始 atom_site。修复前仍需要对这 118 个 occurrence、14 个“组装字符串从未被 CLC 观察到”的对象和 3 个组装例外做原子级归因清单。

## 语言向量差异

### 相同输入的数值基线

MoLFormer 已使用 `deterministic_eval=True`。两种模型各抽取了 112 组“相同 `model_smiles`、不同 occurrence”的重复向量；两种模型的欧氏距离和逐元素最大绝对差都为 0，余弦距离只剩约 `2.22e-16` 的浮点舍入误差。不同字符串的向量差异不是模型随机前向造成的。

### 不同输入与普通跨对象差异比较

随机抽取 100,000 组不同 `object_key` 的代表向量作为尺度参考。该基线没有强制化学结构唯一，所以包含少量不同键却相同向量的情况，是一个保守参考。

| 模型 | 歧义对象内不同字符串：中位数 / 最大值 | 两侧连通：中位数 / 95% 分位数 / 最大值 | 随机跨对象：5% 分位数 / 中位数 |
| --- | --- | --- | --- |
| MoLFormer | 0.03889 / 0.70553 | 0.03217 / 0.09327 / 0.20343 | 0.11073 / 0.30414 |
| SMI-TED Light 289M | 0.001984 / 0.02951 | 0.001679 / 0.003074 / 0.005990 | 0.005877 / 0.01293 |

94 组不同字符串中，MoLFormer 有 22 组达到或超过随机跨对象中位数，SMI-TED 也有 22 组；这 22 组正是涉及连接片段变化的配对。若只看连通变体，绝大多数距离低于普通跨对象距离的 5% 分位数。

尽管连通变体的绝对距离通常较小，它们仍会改变局部最近身份。对 19 个仍有多个连通字符串的对象，两种模型各有 12 个对象在改用另一个连通字符串后改变了最近的其他 `object_key`。

按 occurrence 频率衡量，如果把每个键的最高频字符串向量暂当参考：

| 模型 | 118 个少数 occurrence 的余弦距离中位数 | 平均值 | 95% 分位数 | 把主流 occurrence 记为 0 后，全部 BRANCHED occurrence 平均值 |
| --- | ---: | ---: | ---: | ---: |
| MoLFormer | 0.02726 | 0.22137 | 0.66413 | 0.000629 |
| SMI-TED Light 289M | 0.001662 | 0.01021 | 0.02802 | 0.0000290 |

少数 occurrence 的均值被 45 个断图 occurrence 明显抬高；最后一列则被 41,418 个主流或非歧义 BRANCHED occurrence 稀释。两个数字回答的是不同问题，都不能单独替代对象身份审计。

## 当前实际影响

### 语言模型产物本身

当前语言模型产物从一开始就按 `(pdb_id, candidate_id)` 保存，没有声称把一个 `object_key` 强制压成一条向量。因此：

- 现有 677,835 条 occurrence 级准备记录与 MoLFormer 向量没有因本次审计变成格式错误；
- 现有 SMI-TED 的 575 条模型失败属于既有模型运行事实，不是本次身份歧义导致；
- 真正不能成立的是“从 `object_key` 无条件取得唯一语言模型输入或唯一语言向量”的接口假设。

如果某个消费者只需要 occurrence 级表示，可以继续使用当前键定位 occurrence 之外的模板对象；如果消费者要按全局化学身份去重，就必须增加化学变体维度。

### Matcher

Matcher 当前实际读取所选语言 NPZ 的 `embedding`，同时按同一个 `object_key` 读取图模板。当前 [`manifest.py`](../../Matcher/matcher/data/manifest.py) 的选择单位是单个 PDB 内的 `(class_name, object_key)`；`_select_language_representation` 对该组有效 occurrence 排序后，用 `selection_seed` 与固定字节加权和确定一个 occurrence。它是可复现的固定选择，不是每次运行重新抽样。

旧执行记录中的 `language_multi_smiles_identity_count=0` 只检查单个 PDB 内身份组，不检查同一键跨 PDB 的全局字符串集合。全量审计找到了 17 个同一 PDB 内多字符串组合，说明旧冻结子集不能代表全量数据。

当前正式清单的实测影响为：

| 清单 | 身份记录总数 | 触达歧义键的身份记录 | 歧义键数 | 当前是否选择多个字符串 |
| --- | ---: | ---: | ---: | --- |
| `closed_set_v2` | 1,132 | 0 | 0 | 否 |
| `closed_set_v3` | 2,013 | 211 | 11 | 否 |

v3 的 211 条记录全部是 sugar，train 164、validation 47。两个模型都只选择各键的同一个主流字符串，train 与 validation 没有字符串差异。因此本次审计本身不足以判定当前 v3 训练结果失效；但清单扩大到包含 118 个少数 occurrence 后，现有局部检查不能阻止全局身份混入多个向量。

### 其他仓库和 Stage3 边界

- Builder 的正式接口只读取 AdaLigand 兼容层生成的 PocketXMol 原生缓存，不读取 `occurrences.jsonl`、`ligand_objects` 或语言模型产物。
- PocketXMol 仓库没有直接读取 AdaLigand 的 `object_key` 或语言模型产物。
- Pocket Plus 只有讨论文档提到 LigandObject，没有发现正式语言向量消费者。
- Emap2lig 是当前 BRANCHED LigandObject 构造血统的来源，具有相似的完整 CCD 拼接逻辑，但不消费本次 AdaLigand occurrence 级语言模型产物。
- Stage3 兼容层读取 `object_key` 对应的全局 LigandObject，再读取 occurrence 坐标和 `present`；它只接受 `small_molecule` 与 `peptide_like`，并拒绝重原子坐标不完整的实例。Stage3 不读取本报告定义的 `smiles` 或语言向量，所以其坐标与沉积原子问题不属于本次核心 bug。25 个歧义键中有 2 个 small_molecule、3 个 peptide_like；这些模板是否需要另行迁移，应在 Stage3 专项中判断。
- `ligand_descriptors` 也按当前 `object_key` 全局保存一份，但它从 LigandObject 模板图计算，不读取 occurrence CLC `smiles`。它可能受到“模板键是否应代表精确化学身份”的相邻语义影响，本次没有把它计入语言模型 bug 的实测影响。

## 修复策略比较

首先必须决定语言模型究竟要表达哪一种对象：由 CCD 组件和内部连接定义的完整、游离装配体，还是 PDB occurrence 中 CLC 给出的结合态或重建态分子。两者不是同一个问题，也不应共用一个含混的“化学身份”名称。本次试验表明，直接把 occurrence CLC 字符串哈希成新身份会把明显断图、包重建差异和可能的结合态化学一起固化，所以不应作为默认修复。

### 策略一：为完整装配体建立确定性分子构造器

如果语言模型目标是“同一 `object_key` 只有一个完整配体表示”，最直接的方向是从完整 CCD 组件、内部连接端点和版本化离去基团规则构造分子，再生成例如 `assembled_smiles` 与 `assembled_chemical_key`。现有 `object_key` 可以保留为装配定义键。

离去基团审计表明，25 个歧义键中有 23 个的每个内部连接端点都各自只有一个相邻离去基团，因此最初担心的“离去原子普遍无法唯一决定”没有得到支持。诊断原型对其中 22 个不复用离去组的键都成功生成了单一连通分子。另 1 个双 NAG 键因两条连接复用同一端点的离去基团而出现碳五价；其余 2 个 KC2/LMG 方向键的端点没有 CCD leaving-atom 标记。

这个方向仍不能直接投产：22 个成功结果只有 3 个匹配主流 CLC 字符串、5 个匹配少数 CLC 字符串，另有 14 个从未出现在正式 CLC 产物中。这里的“不匹配”既可能说明 CLC 表达结合态或缺原子，也可能说明原型的删原子、补氢、键级或电荷规则不完整。必须逐原子校验后才能指定真值。

优点：同一装配定义可得到可复现输入，不依赖 occurrence 坐标或沉积原子子集。缺点：需要定义并版本化糖、肽、非标准组件、端点复用和无 leaving-atom 标记时的例外规则；在全部 692 个 BRANCHED 键中，只有 389 个满足“所有端点均有唯一相邻离去基团，且不同端点不复用该组”，所以 25 个歧义键上的高覆盖率不能外推为全库覆盖率。

### 策略二：需要 occurrence 化学时采用分层身份

如果项目同时需要“完整装配体身份”和“PDB occurrence 中实际重建出的图”，建议明确保留分层字段，而不是让单个 `object_key` 兼任全部含义：

```text
assembly_template_key
  = CCD 组分序列 + 内部连接端点 + 构造规则版本

assembled_chemical_key
  = 确定性完整装配图的规范化载荷摘要

occurrence_clc_key
  = 通过质量门槛后的 occurrence CLC 规范化图摘要
```

语言模型和 Matcher 必须显式声明使用哪一层。`occurrence_clc_key` 只能表示“该 occurrence 的模型输入图”，不能在未经化学归因时自动升格为去重真值。当前 non-isomeric `smiles` 不保留立体信息；若未来把立体异构体区分为不同身份，载荷和键名还需扩展。

优点：精确保留装配定义、完整构造结果和 occurrence 图之间的一对多关系。缺点：消费者接口与缓存迁移更复杂，项目不再只有一个未经限定的“配体身份”。

### 策略三：把 BRANCHED `object_key` 全面改为完整规范化分子图

可以使用完整原子、键、形式电荷和版本化规范化规则生成新 `object_key`，让它只代表精确化学结构；若同时提供稳定原子映射，`ligand_objects`、描述子、语言向量和 Matcher 可以统一迁移。

优点：最终身份概念最整洁。缺点：迁移范围最大；必须先解决确定性构造器的 14 个未观察结果和 3 个例外，还需重建 occurrence 坐标到新模板的原子映射。当前 CLC 含断图和不完整原子，不能直接作为新键载荷。

### 策略四：固定选择最高频或固定 occurrence

为每个当前 `object_key` 固定一个字符串或向量，记录来源并拒绝后续改变。这与当前 Matcher 的固定选择思路类似。

优点：改动最小，能立即为接口提供单值。缺点：它把多值隐藏在选择规则后，不能证明所选字符串正确；小样本对象的最高频字符串甚至可能是断图。该策略只能作为缓存兼容或短期冻结办法，不能继续称为“化学身份修复”。

### 独立质量修复：拒绝明显异常 CLC

无论采用哪种身份策略，都应为 BRANCHED CLC 增加至少以下诊断门槛：

- 期望为一个连接分子时，`fragment_count` 必须为 1；
- CLC 的组分内键数量不能退化为只剩跨残基键；
- `connection_check.matches=false` 时不能无条件采用 CLC；
- 记录外部包警告、错误、原子数与 CCD 期望重原子数差；
- 质量检查失败时，应明确选择“按确定性 CCD 缩合规则重建”“使用经过验证的 present 图”或“记为无字符串”，不能只因 `MolToSmiles` 返回非空值就通过。

这项修复可以直接消除 9 个断图字符串和 45 个 occurrence 的明显异常，但仍会剩下 19 个连通多字符串对象，所以它不是完整身份修复。

### 哈希加固

当前六位 MD5 后缀本次没有碰撞，但 24 bit 不适合作为长期全局身份。新版本键应保存足够长的摘要，并在物化时验证“同键的完整规范化载荷完全相同”。这项加固与 `smiles` 多值修复应分开验收。

## 建议的实施顺序

本阶段不实施修复。若进入实现阶段，建议按以下顺序推进：

1. 冻结本次 25 个对象、66 个字符串、118 个少数 occurrence 和 45 个断图 occurrence 为回归清单。
2. 明确语言模型的目标语义：完整游离装配体、occurrence 结合/重建态，或两者分别保存；同时明确立体、质子化、盐、金属配位和外部共价结合是否改变身份。
3. 对 118 个少数 occurrence、14 个“确定性结果未在 CLC 中出现”的对象和 3 个构造例外做原子级归因。逐项标记离去基团、组分内键、补氢、键级、电荷、外部共价关系和包重建差异，不得把最高频 CLC 自动当真值。
4. 先增加 CLC 断图和连接质量门槛，验证 45 个明显异常不再无条件进入模型；但不得把这一门槛误当成完整身份修复。
5. 若选择完整装配体语义，开发带规则版本和来源记录的确定性构造器；先让 25 个回归对象通过人工化学验收，再覆盖全部 692 个 BRANCHED 键，并为“无唯一离去基团”“端点本身被标记为 leaving atom”“复用离去基团”等状态制定显式例外政策。
6. 设计并评审身份契约。若还需 occurrence 图，采用装配定义键、完整化学键和 occurrence CLC 键的分层字段；如果不需要 occurrence 图，则不要因现有多字符串而无条件制造 66 个永久化学身份。
7. 用回归集验证：确定性对象级输入必须单值；同一字符串的正式重复向量必须逐元素一致；质量失败必须可追踪且不能静默回退。
8. 建立旧键到新键的兼容映射后，再迁移 Matcher 清单、语言向量缓存和对象级索引。当前 v3 清单应保留其实际选中字符串，供迁移前后等价核验；本次审计没有证据要求立即废弃现有 v3 结果。
9. 最后再决定是否把现有 `object_key` 正式更名为装配定义键，或在更大版本中用完整化学图键替换它。

在上述契约落地前，新的消费者不得仅凭 `object_key` 请求“唯一配体语言向量”。如果必须临时使用，应同时记录所选 `(pdb_id, candidate_id, smiles, model family, selection rule)`，并明确它是代表样本而不是去重化学真值。

## 审计复现与证据位置

本次只写服务器临时聚合结果，没有修改正式数据、语言模型产物、Matcher 清单、样本划分或训练结果。

### 本地代码、历史文档与项目记忆

结论不是只从服务器聚合数字反推。审计先后核对了以下来源，并用当前代码和正式数据覆盖历史文档中可能已经过时的描述：

- [`数据处理_v2.md`](../文档/规划文档/数据处理_v2.md) 与 [`数据下载与解析.md`](../文档/exec_plan/数据下载与解析.md)：确认 `LigandObject` 的 Emap2lig 血统、全局去重意图、完整模板图与 occurrence 坐标分离的原始契约。
- [`2026-06-22-adaligand-data-abc-ori_data-closeout.md`](../CLAUDE/memory/handoffs/2026-06-22-adaligand-data-abc-ori_data-closeout.md) 与 [`2026-07-10-abc服务器产物与增量重跑审计.md`](../CLAUDE/memory/handoffs/2026-07-10-abc服务器产物与增量重跑审计.md)：复核 Stage C 全量产物、3,833 个去重键以及模板/真实坐标的历史边界。
- [`AdaLigand_v3基础数据升级计划.md`](AdaLigand_v3基础数据升级计划.md)、[`AdaLigand_v3基础数据升级实施.md`](../文档/exec_plan/AdaLigand_v3基础数据升级实施.md) 和当前 `ligand_language_model` 实现：确认正式语言准备单位、CLC 选择顺序、后备路径、字符串规范化与两个模型的实际输入。
- Matcher 的 [`Matcher_单候选闭集身份分类重写执行记录.md`](../../Matcher/文档/exec_plan/Matcher_单候选闭集身份分类重写执行记录.md)、当前 `manifest.py` 和两套服务器冻结清单：区分旧日志的 PDB 内检查与本次跨 PDB 全局检查，并复算当前实际选择结果。
- Builder、PocketXMol、Pocket Plus、Emap2lig 和 Stage3 适配代码：逐仓搜索正式读取路径，区分构造血统、模板消费者、语言向量消费者与只存在于讨论文档的引用。

### 第一轮：身份与输入多重性

- Slurm Job：`341830`
- 资源：16 CPU、64 GB 内存上限
- 状态：`COMPLETED 0:0`
- 耗时：12 分 09 秒
- 峰值内存：约 976 MB
- 输出：`/storage/penghongen/tmp/ligand_object_audit_20260814/input_multiplicity_initial/`
- 主要文件：`summary.json`、`objects.jsonl`、`ambiguous_objects.jsonl`、`topology_collisions.jsonl`、`failures.jsonl`
- `failures.jsonl`：0 条

### 第二轮：化学、向量和 Matcher 影响

- Slurm Job：`341836`
- 资源：16 CPU、64 GB 内存上限
- 状态：`COMPLETED 0:0`
- 耗时：10 分 22 秒
- 峰值内存：约 199 MB
- 输出：`/storage/penghongen/tmp/ligand_object_audit_20260814/effects_initial/`
- 主要文件：`summary.json`、`ambiguous_details.jsonl`、`failures.jsonl`
- `failures.jsonl`：0 条

### 第三轮：CCD leaving-atom 端点审计

- Slurm Job：`341858`
- 资源：1 CPU、16 GB 内存上限
- 状态：`COMPLETED 0:0`
- 耗时：3 分 03 秒
- 峰值内存：约 82 MB
- 输出：`/storage/penghongen/tmp/ligand_object_audit_20260814/leaving_atoms_initial/`
- 主要文件：`summary.json`、`objects.jsonl`、`failures.jsonl`
- `failures.jsonl`：0 条；203 个被引用 CCD 全部读取成功

### 第四轮：外部共价状态与字符串的关联

- Slurm Job：`341861`
- 资源：16 CPU、64 GB 内存上限
- 状态：`COMPLETED 0:0`
- 耗时：2 分 54 秒
- 峰值内存：约 24 MB
- 输出：`/storage/penghongen/tmp/ligand_object_audit_20260814/covalent_smiles_initial/`
- 主要文件：`summary.json`、`objects.jsonl`、`failures.jsonl`
- `failures.jsonl`：0 条

### 第五轮：确定性 CCD 重组诊断

- Slurm Job：`341862`
- 资源：1 CPU、16 GB 内存上限
- 状态：`COMPLETED 0:0`
- 耗时：3 分 01 秒
- 峰值内存：约 23 MB
- 输出：`/storage/penghongen/tmp/ligand_object_audit_20260814/deterministic_assembly_initial/`
- 主要文件：`summary.json`、`objects.jsonl`、`failures.jsonl`
- 22 个对象成功生成单一连通分子，2 个因无相邻 leaving 标志跳过，1 个因端点复用导致 sanitize 失败

一次性只读统计脚本位于 Git 忽略目录：

- `Data_Preprocessing/Ori_Data_upgrade/tmp/ligand_object_audit_20260814/audit_input_multiplicity.py`
- `Data_Preprocessing/Ori_Data_upgrade/tmp/ligand_object_audit_20260814/audit_effects.py`
- `Data_Preprocessing/Ori_Data_upgrade/tmp/ligand_object_audit_20260814/audit_leaving_atoms.py`
- `Data_Preprocessing/Ori_Data_upgrade/tmp/ligand_object_audit_20260814/audit_covalent_smiles.py`
- `Data_Preprocessing/Ori_Data_upgrade/tmp/ligand_object_audit_20260814/audit_deterministic_assembly.py`

服务器正式输入根为：

- Stage C：`/storage/penghongen/AdaLigand/Ori_Data`
- 语言模型：`/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2/ligand_language_models`
- Matcher 清单：`/storage/penghongen/tmp/Matcher/manifests/closed_set_v2` 与 `closed_set_v3`

## 限制

- 本报告审计的是正式 non-isomeric `smiles` 字段，不评价立体化学唯一性。即使本报告判为单值，也不等于完整立体化学身份唯一。
- RDKit 分子式、连接片段和指纹来自已经生成的字符串，能证明字符串代表不同图，但不能单独判定哪个图是化学真值。
- leaving-atom 审计只按 CCD 中的 leaving 标志和分子图邻接关系判断候选连通组；“唯一”表示数据规则上的唯一，不等于已经人工证明该基团在所有化学环境中都应离去。
- 确定性重组脚本是诊断原型，只删除端点邻接的 leaving 连通组并添加单键，没有为键级、形式电荷、质子化、金属、外部共价结合和特殊 CCD 编写完整生产规则。22 个成功结果不能直接作为新正式字符串。
- `is_covalent` 是 Stage C 对外部共价关系的 occurrence 标志；它能证明关联，不能完整描述 CLC 为什么丢失或保留具体原子。
- 向量差异对每个字符串最多读取 3 个正式 occurrence 示例；94 组不同字符串配对都至少有一个正式向量。随机跨对象基线每个对象只取一条代表向量。
- Matcher 结论只适用于 2026-08-14 读取到的 `closed_set_v2` 与 `closed_set_v3` 冻结清单；未来清单扩大后必须重新相交。
- 本次没有重新编码模型、没有训练 Matcher、没有修改 Stage3，也没有逐原子完成 118 个少数 occurrence 的化学真值判定。
