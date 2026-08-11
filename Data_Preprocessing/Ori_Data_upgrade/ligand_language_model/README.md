# 配体语言模型分子级特征

本目录为 AdaLigand Stage1 已有配体 occurrence 生成两套分子级语言模型表示。
occurrence 是“一条候选配体在一个具体 PDB 中的出现记录”，由该 PDB 内局部的
`candidate_id` 标识：

- MoLFormer：`ibm-research/MoLFormer-XL-both-10pct`；
- SMI-TED：`SMI-TED Light 289M`，权重文件为 `smi-ted-Light_40.pt`。

处理单位始终是一个具体 PDB 中的一个 `candidate_id`，即
`(pdb_id, candidate_id)`。即使两个 occurrence 的 `object_key` 相同，也会分别准备
SMILES、分别运行模型并分别落盘。产物只保存模型给出的 `float32 (768,)` 分子级
表示，不保存 token 级或原子级向量。

本目录不实现 Matcher，不重新划分数据，不去冗余，也不修改 `all_valid.json` 或
`info.json`。`type_tag=other` 不进入语言模型，只在准备阶段分片报告中计数。

## 输入和样本范围

默认服务器数据根目录是：

```text
/storage/penghongen/AdaLigand/Ori_Data
```

CPU 准备读取以下已有文件：

```text
parse/{pdb_id}/occurrences.jsonl
parse/{pdb_id}/ligand_coords.npz
ligand_objects/{safe_object_key}.npz
raw/rcsb_mmcif/{pdb_id}.cif
stage1_preparation_box_pool_2/all_valid.json
```

`safe_object_key` 是把 `object_key` 中不能直接用于文件名的字符替换为下划线后的
名称；它只用于定位现有 LigandObject 文件，不替代 occurrence 身份。

每个 `.sh` 的样本范围位置参数有两种取值：

- `all_existing`：处理所有存在 `parse/{pdb_id}/occurrences.jsonl` 的 PDB；
- `all_valid`：只处理 `stage1_preparation_box_pool_2/all_valid.json` 中的 PDB。

两种范围使用同一套文件格式和输出目录。本轮计划运行 `all_existing`。

## occurrence 化学准备

`prepare_ligand_language_inputs.py` 为每个正式配体 occurrence 生成一个模型输入。

### 普通 CCD

普通 `kind=CCD` 使用现有 `LigandObject.smiles`。RDKit 会尝试解析、sanitize，并生成
canonical non-isomeric SMILES，即按 RDKit 规则选择唯一书写顺序、但不保留手性和
双键立体标记的 SMILES。若 RDKit 不能解析或不能规范化，但原始 SMILES 非空，仍把
原始 SMILES 交给语言模型，并把 RDKit 异常保存在审计字段中。

### BRANCHED

`kind=BRANCHED` 的主路径是：

```text
完整 PDB mmCIF
  -> pdbeccdutils 官方 mmCIF 预处理
  -> clc_reader.read_pdb_cif_file(..., sanitize=True)
  -> occurrence 与 CLC 精确对应
  -> RDKit canonical non-isomeric SMILES
```

对应时比较完整残基身份的多重集合，而不是普通集合。一个残基身份是：

```text
(ccd_id, auth_asym_id, auth_seq_id, insertion_code)
```

空字符串、`.` 和 `?` 都归一为空插入码。只有恰好一个 CLC 与 occurrence 的完整
身份多重集合相同，才采用该 CLC；没有“最高重合”“并列任选”或其他模糊匹配。

CLC 无法唯一对应，或唯一 CLC 不能生成非空 SMILES 时，使用简单后备表示：

```text
LigandObject.atoms / LigandObject.bonds
  + ligand_coords.npz::present_{candidate_id}
  -> 删除 present=False 的模板原子
  -> 只保留两端原子都存在的已有键
  -> RDKit SMILES
```

`present=False` 既可能表示缩合离去原子，也可能表示普通缺失原子；记录只陈述删除
数量，不把后备图宣称为唯一化学真值。现有 BRANCHED `LigandObject` 的组分间键统一
保存为单键，这一限制也只记录。代码不实现手写离去原子规则、化学反应引擎、
字符串形式的 `SMILES_A.SMILES_B` 回退或多个 assembly variant。

配体若与受体共价连接，模型分子仍只包含配体。暴露价态可能由 RDKit 隐式氢封端；
`is_covalent` 会保留在记录中，但这种表示不自动判定为科学错误。

### 宽口径记录

真实断开组分、盐、形式电荷、金属和单原子离子都保留；代码不去盐、不取最大
组分、不中和。以下事实写入 `chemistry` 或 `preparation_audit`：

- 组分数、是否断开、原子数、带电原子数、总形式电荷和是否含金属；
- RDKit parse、sanitize 和两次 `MolToSmiles` 的独立结果；
- occurrence 的 components、inter_bonds 和所有 CLC 候选；
- CLC 精确匹配数、包报告的 warnings/errors、连接边和键级字段；
- occurrence 与唯一 CLC 的“完整残基身份—原子名”连接多重集合是否一致、缺失边和
  额外边；该比较不含 occurrence 未保存的原始键级，也不参与模型输入选择；
- 后备图删除原子数、保留键数、片段数和异常。

这些字段不构成自动门控。只要获得非空 `model_input_smiles`，GPU 阶段就可以尝试
编码；最终是否采用某类记录由使用者决定。

## 模型行为

### MoLFormer

MoLFormer 使用官方 tokenizer 和模型，保持 FP32、eval 模式。脚本明确
`truncation=False`，因此超过 202 token 的输入仍交给模型；202 只作为预训练长度
参考写入诊断。A100-PCIE-40GB 前探中，batch size 256 在短 SMILES 上约为
621 occurrence/s，在约 970 token 输入上约为 129 occurrence/s，因此正式默认值是
256。

### SMI-TED Light 289M

SMI-TED 直接调用官方 `model.encode`。以下官方行为保持不变：

- RDKit canonical、non-isomeric 规范化；
- 官方 tokenizer；
- 最大长度 202 与官方截断；
- token 表示聚合和自编码器池化；
- `batch_size=100`。

前探发现官方 tokenizer 在 `transformers==5.12.1` 下会把普通化学 token 静默变为
`<pad>`，而 `transformers==4.57.6` 表现正确，因此 SMI-TED 入口明确要求
`transformers==4.57.6`。未知 token 与 pad token 共用 `<pad>` 的官方设计不改变，
脚本只另外记录词表覆盖、token 回拼和截断后的有效 token 文本。

当当前 GPU 分片少于 100 个可编码 occurrence 时，传给官方入口的 batch size 等于
该分片 occurrence 数。这样可避免官方小样本分片公式把每条输入拆成单独前向；
达到 100 条后继续使用官方默认 100。

### 全局 batch 与失败处理

GPU 数组仍按 PDB 分片，以保证不同数组任务不写同一 PDB；但是每个数组任务会先
把自己负责的所有未完成 PDB occurrence 展平成一个全局列表，再跨 PDB 组成 batch。
单个 PDB occurrence 少于 100 或 256，不会退化成单样本 batch。

普通 batch 异常只对该 batch 中的 occurrence 逐条重试。CUDA OOM、CUDA runtime、
cuBLAS 或 cuDNN 错误会终止当前数组任务，不暗自缩小 batch。模型只要返回数值
`(768,)` 就保存；NaN 和正负无穷不会被替换或拒绝，而是在结果记录中计数。模型
无输出或形状不为 `(768,)` 时不伪造向量，只写 `model_failed` 记录。

## 正式输出

统一输出根目录是：

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2/ligand_language_models
```

目录结构为：

```text
prepared/{pdb_id}/prepared_smiles.jsonl
prepared/reports/shard_*.json
prepared/reports/final_summary.json

molformer/{pdb_id}/candidate_{candidate_id}.npz
molformer/{pdb_id}/results.jsonl
molformer/reports/shard_*.json
molformer/reports/final_summary.json

smi_ted_289m/{pdb_id}/candidate_{candidate_id}.npz
smi_ted_289m/{pdb_id}/results.jsonl
smi_ted_289m/reports/shard_*.json
smi_ted_289m/reports/final_summary.json
```

### `prepared_smiles.jsonl`

每个 JSON 对象对应一个正式 occurrence。当前 `schema_version` 固定为整数 `1`。

| 字段 | 类型 | 含义 |
|---|---|---|
| `schema_version` | int | 当前为 `1` |
| `pdb_id` | str | 当前正在处理的 `parse/{pdb_id}` 目录名；正式产物身份使用此值 |
| `source_occurrence_pdb_id` | str | 源 `occurrences.jsonl` 对象内的 `pdb_id`，缺失时为空字符串 |
| `pdb_id_matches_source_occurrence` | bool | 上述两个 PDB 身份是否一致；不一致只记录，不阻止准备 |
| `candidate_id` | int | 当前 PDB 内的 occurrence 编号 |
| `object_key` | str | occurrence 引用的 LigandObject 化学模板键 |
| `kind` | str | `CCD` 或 `BRANCHED`；其他值进入无输入记录 |
| `type_tag` | str | 五个正式类别之一；`other` 不写入本文件 |
| `is_covalent` | bool | 原 occurrence 是否被 Stage C 标记为与受体共价连接 |
| `components` | list[object] | 原 occurrence 的 CCD 组分及其残基身份 |
| `inter_bonds` | list[list] | 原 occurrence 的 `[组分编号, 原子名, 组分编号, 原子名]` 连接 |
| `preparation_source` | str | `ligand_object_smiles`、`pdbeccdutils_clc`、`ligand_object_present_graph_fallback`、`unsupported_occurrence_kind` 或 `occurrence_exception` |
| `source_smiles` | str 或 null | LigandObject 原始 SMILES；BRANCHED 通常为 null |
| `assembled_isomeric_smiles` | str 或 null | RDKit 成功生成时保留立体标记的 SMILES；失败不拿原文冒充 |
| `model_input_smiles` | str 或 null | CPU 准备的 canonical non-isomeric SMILES；CCD 规范化失败时可为非空原文 |
| `has_model_input` | bool | `model_input_smiles` 是否为非空字符串 |
| `chemistry` | object | 从成功构造的 RDKit Mol 读取的宽口径事实；没有 Mol 时为空对象 |
| `preparation_audit` | object | 随准备来源变化的步骤、候选、连接、RDKit 与后备图事实 |
| `preparation_warnings` | list[str] | 顶层警告；当前正式路径通常为空，包警告保存在 audit 内 |
| `preparation_errors` | list[str] | occurrence 外层异常；普通步骤异常通常保存在 audit 内 |

`chemistry` 的字段如下：

| 字段 | 类型 | 含义 |
|---|---|---|
| `atom_count` | int | 当前 RDKit 图原子数 |
| `fragment_count` | int 或 null | `Chem.GetMolFrags` 得到的断开片段数；调用失败时为 null |
| `fragment_count_error` | str 或 null | 片段枚举异常；成功时为 null |
| `has_disconnected_components` | bool 或 null | `fragment_count > 1`；片段数未知时为 null |
| `has_metal` | bool | 是否含项目报告集合中的金属原子 |
| `charged_atom_count` | int | 形式电荷不为零的原子数 |
| `has_charged_atoms` | bool | `charged_atom_count > 0` |
| `total_formal_charge` | int | 全部原子形式电荷之和 |
| `stereo_removed` | bool 或 null | 异构与非异构 SMILES 是否不同；任一生成失败时为 null |

`preparation_audit` 按来源解释：

- `ligand_object_smiles`：固定保存 `rdkit_parse_success` 与
  `rdkit_parse_error`；解析成功后再保存 `sanitize_success`、`sanitize_error`、
  `isomeric_smiles_error` 和 `model_input_smiles_error`。
- `pdbeccdutils_clc`：保存 mmCIF 路径、官方预处理和 CLC reader 的成功/异常、候选
  数、包的电荷/连接键级不视为权威的标记、occurrence 残基身份、精确匹配数、原始
  inter_bonds、所有候选摘要、唯一 `selected_clc`、显式氢删除和 RDKit 结果。
- `ligand_object_present_graph_fallback`：保存上述 CLC 事实、唯一 CLC 尝试或异常，
  以及 `present_graph`。后者包含模板/掩码/present/删除原子数、模板/保留键数、
  “组分间键来自现有单键”标记、图构造异常和独立 RDKit 结果。若键类型或手性
  one-hot 不是恰好一个 True，还会分别计数全 False 与多个 True 的原子/键，并记录
  “全 False 使用默认值、多个 True 使用 Stage C 固定顺序第一项”的确定性回退；
  该字段漂移只进入审计，不自动拒绝非空后备 SMILES。
- `unsupported_occurrence_kind`：只保存 `unsupported_kind`。
- `occurrence_exception`：`preparation_audit` 为空，异常写入
  `preparation_errors`，且三个 SMILES 均为 null。

每个 `clc_candidates[]` 摘要包含 `clc_index`、`component_identities`、
`reported_sanitized`、`warnings`、`errors`、`graph_edge_count`、`edges` 和
`smiles_generation_attempted=false`。只有唯一精确候选进入 `selected_clc`；该对象把
`smiles_generation_attempted` 改为 true，并增加两种生成 SMILES 与
`connection_audit`。未选候选明确表示“未尝试生成 SMILES”，不等同于生成失败。

`selected_clc.connection_audit` 比较 occurrence 与 CLC 的“完整残基身份—原子名”
连接多重集合，保存比较层级、是否为模型输入门控（固定 false）、重复残基身份、
键级不可比较、期望/观察连接数、解析异常、是否相等、两侧完整连接、缺失连接和
额外连接。若诊断代码自身异常，只保存 `audit_error`，唯一 CLC 仍继续生成 SMILES。

### 模型 NPZ

`molformer` 与 `smi_ted_289m` 的 `candidate_{candidate_id}.npz` schema 相同：

| 字段 | dtype 与形状 | 含义 |
|---|---|---|
| `pdb_id` | 字符串标量 | 输出目录 PDB |
| `candidate_id` | int32 标量 | occurrence 编号 |
| `object_key` | 字符串标量 | LigandObject 键 |
| `model_name` | 字符串标量 | 精确模型身份 |
| `prepared_model_input_smiles` | 字符串标量 | CPU prepared 文件提供的输入 |
| `model_input_smiles` | 字符串标量 | MoLFormer 为原样交给 tokenizer 的 prepared 字符串；SMI-TED 在诊断复现成功时为完整官方规范化字符串，诊断失败时回退为交给 `model.encode` 的 prepared 字符串；它不表示截断后的 token 序列 |
| `embedding` | float32 `(768,)` | 官方分子级池化表示；MoLFormer 来自 `pooler_output`，SMI-TED 来自官方自编码器池化 |

### 模型 `results.jsonl`

每个 prepared occurrence 恰好对应一个结果。公共字段如下：

| 字段 | 类型 | 含义 |
|---|---|---|
| `schema_version` | int | 当前为 `1` |
| `model_name` | str | 精确模型身份 |
| `pdb_id` | str | 模型输出目录 PDB |
| `source_prepared_pdb_id` | str | prepared 对象内的 PDB |
| `pdb_id_matches_prepared_record` | bool | 目录 PDB 与 prepared PDB 是否一致 |
| `candidate_id`、`object_key` | int、str | occurrence 身份 |
| `kind`、`type_tag`、`is_covalent` | str、str、bool | 化学类别与共价事实 |
| `preparation_source` | str | CPU SMILES 来源 |
| `prepared_model_input_smiles` | str 或 null | CPU 准备输入 |
| `status` | str | `encoded`、`model_failed` 或 `no_model_input` |
| `actual_model_input_smiles` | str 或 null | 与 NPZ `model_input_smiles` 同一条件语义；没有模型输入时为 null |
| `input_diagnostics` | object | 模型 tokenizer/长度事实；没有模型输入时为空对象 |
| `output_path` | str 或 null | `encoded` 对应 NPZ 的绝对路径 |
| `output_shape` | list[int] 或 null | `encoded` 固定为 `[768]` |
| `output_dtype` | str 或 null | `encoded` 固定为 `float32` |
| `all_finite` | bool 或 null | `encoded` 向量是否全部有限 |
| `nan_count`、`positive_inf_count`、`negative_inf_count` | int 或 null | `encoded` 向量三类非有限值数量 |
| `error` | str 或 null | `model_failed` 的异常/形状说明；其他状态为 null |

三种 status 的缺失值规则固定为：

- `encoded`：NPZ 存在；输出字段和有限性字段有值，`error=null`；
- `model_failed`：没有 NPZ；输出字段和有限性字段均为 null，`error` 非空；
- `no_model_input`：没有调用模型、没有 NPZ；`actual_model_input_smiles=null`、
  `input_diagnostics={}`、输出字段/有限性字段为 null、`error=null`。

MoLFormer 的 `input_diagnostics` 保存特殊 token 前后长度、词表外 token 数及列表、
token 回拼是否等于输入及回拼文本、202 token 参考长度、是否超过参考长度、
`truncation_requested=false` 和诊断异常。SMI-TED 保存官方规范化字符串与成功状态、
截断前 token 数、官方最大长度 202、是否截断、截断后保留的化学 token 文本、
词表外 token、`unknown_token_is_pad_token=true`、回拼结果和诊断异常。规范化失败时
SMI-TED 诊断只保存失败状态；诊断异常不阻止官方 `model.encode`。

### 分片报告与最终汇总

三个阶段的 `shard_*.json` 均使用 `schema_version=1`，保存开始/结束时间、耗时、
样本范围、全局 PDB 数、分片编号/总数和当前分片 PDB 数。

- prepared 分片另存 worker 数、overwrite、PDB status 计数、正式/有输入/无输入/
  other occurrence 数、依赖版本和 `pdb_results`。逐 PDB status 为 `completed`、
  `skipped_existing` 或 `failed`；完成项含各类别/准备来源计数，失败项含异常。
- 模型分片另存模型名、处理/已完成跳过/prepared 不可读或必要字段不合法的 PDB 数、跳过清单、跨 PDB
  输入数、batch size、结果 status、编码吞吐、依赖、CUDA 设备事实和
  `pdb_results`。逐 PDB status 为 `completed` 或 `prepared_unavailable`。schema、
  必要字段类型、`has_model_input` 与 SMILES 一致性，以及同一 PDB 内
  `candidate_id` 唯一性都在调用模型前核对；失败只记录该 PDB，不覆盖同名 NPZ，
  也不阻止当前 GPU 分片的其他 PDB。

三个 `final_summary.json` 也使用 `schema_version=1`，由显式汇总任务重扫正式文件：

- 公共字段为 stage、生成时间、样本范围、期望/已有/缺失 PDB 数、缺失 PDB 清单、
  记录数和依赖；
- prepared 另存 type/source/input 计数、不同精确模型输入数及最高频精确字符串；
- 两个模型另存 status/type/有限性计数、encoded 记录指向的缺失 NPZ 数、不同精确
  实际输入数及最高频精确字符串。

最高频字段为 null 或一个包含 `smiles`、`count`、`tied_smiles_count`、
`tie_break=lexicographically_first` 的对象。所有缺失和异常只进入报告，不形成发布
门控。

## 续跑和覆盖

- `prepared/{pdb_id}/prepared_smiles.jsonl` 存在时，CPU 准备默认跳过该 PDB；
- `{model}/{pdb_id}/results.jsonl` 存在时，对应模型默认跳过该 PDB；
- 只有 candidate NPZ、没有 `results.jsonl` 表示中断残留，模型会重做整个 PDB；
- 在 `.sh` 的样本范围后加 `--overwrite` 可以显式重算已有完成文件。

所有完成文件先写同目录临时文件，再通过原子替换建立。最终汇总必须在相应数组
任务结束后显式运行；它重新扫描正式逐 PDB 文件，不使用分片报告中的局部赢家。
每个阶段报告的最高频精确 SMILES 只用于描述数据，不参与模型输入选择。

## 权重和独立运行时

权重与 Python 运行时不进入 Git，也不放入数据产物目录。服务器固定位置为：

```text
/storage/penghongen/AdaLigand/model_weights/ligand_language_models/
├── models/
│   ├── molformer/
│   └── smi_ted_289m/
└── runtime/
    ├── molformer/
    └── smi_ted_289m/
        ├── common/
        └── transformers4/
```

`models/molformer` 必须包含 Hugging Face 本地模型、tokenizer 和官方自定义代码。
`models/smi_ted_289m` 必须包含 `smi-ted-Light_40.pt`、
`bert_vocab_curated.txt` 和 `smi-ted/inference/smi_ted_light/load.py`。两个 `.sh` 分别
把自己的 `runtime` 放到 `PYTHONPATH` 首位并启用离线模式。SMI-TED 先读取
`runtime/smi_ted_289m/transformers4`，再读取提供 tokenizers、regex 和
pytorch-fast-transformers 的 `runtime/smi_ted_289m/common`，避免两套 transformers
版本互相污染。

## 通过“训练与运行”提交

CPU 准备示例使用 12 个数组任务，每个任务 8 个 CPU：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/prepare_ligand_language_inputs.sh \
  --resource cpu \
  --array 0-11 \
  --cpus 8 \
  --mem 768G \
  -- all_existing
```

两套模型都支持单卡单任务，也支持 4 个 A100 数组任务。数组形式示例：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_molformer.sh \
  --resource a100 \
  --array 0-3 \
  -- all_existing

bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_smi_ted_289m.sh \
  --resource a100 \
  --array 0-3 \
  -- all_existing
```

每个阶段全部数组任务结束后，分别生成全局汇总：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/summarize_ligand_language_outputs.sh \
  --resource cpu \
  -- prepared all_existing
```

把 `prepared` 换成 `molformer` 或 `smi_ted_289m`，即可汇总对应模型。正式任务只由
使用者提交；这些脚本本身不会自动启动下一阶段。
