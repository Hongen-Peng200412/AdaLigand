# 配体语言模型分子向量

PDB 是一份蛋白质等生物大分子的三维结构记录。本目录以一个 PDB 中的一次配体出现为
处理单位；下文把“一次配体出现”简称为 occurrence：

```text
(pdb_id, candidate_id)
```

SMILES 是用一行字符写出分子原子、化学键、分支和电荷的文本格式。每个正式 occurrence
先得到一个 SMILES，再分别生成 MoLFormer 和 SMI-TED Light 289M 的 `float32 (768,)`
分子级向量：它由 768 个 32 位浮点数组成，用一串数字概括整个分子。即使两个 PDB 或
两个 candidate 共享同一个 `object_key`，即指向同一个可复用化学模板，它们也会分别
准备、分别编码、分别保存。

本目录不实现后续用于配体与密度对应的 Matcher 模型，不重新划分样本，不去冗余，也不
修改 `all_valid.json`、`info.json` 或用于第一阶段训练的 Stage1 产物。正式处理只包含
`ion`、`nucleotide_like`、`peptide_like`、`small_molecule` 和 `sugar` 五类；
`type_tag=other` 只进入 CPU 计数。

下文使用这些术语：CCD 是 PDB 化学组分字典中的单个标准组分；BRANCHED 是由多个残基
分支连接的配体；LigandObject 是 Stage C 化学解析阶段保存的可复用配体模板；RDKit 是把
SMILES 转成分子图并重新生成字符串的化学软件包；mmCIF 是 PDB 三维结构记录的文本格式；
pdbeccdutils 是读取该格式并处理化学组分的软件包；CLC 是它识别出的共价连接配体组分；
`present_{candidate_id}` 是与 LigandObject 原子逐项对齐的当前 PDB 原子存在掩码。batch 是
模型一次共同计算的一组 occurrence；NPZ 是按名称保存
多个 NumPy 数组的压缩文件；JSONL 是每个非空物理行保存一个 JSON 对象的文本文件；
token 是模型词表中的一个文本片段；diagnostics 是只记录转换与异常事实、不参与自动
筛选的诊断对象。

## 四个核心对象

| 对象 | 它回答的问题 | 来源或产物 |
|---|---|---|
| occurrence | 当前 PDB 中处理的是哪一次配体出现？ | `parse/{pdb_id}/occurrences.jsonl` |
| LigandObject | 该化学模板保存了哪些原子、键和已有 SMILES？ | `ligand_objects/{safe_object_key}.npz` |
| PreparedLigand | 当前 occurrence 最终准备出了什么 SMILES？ | `prepared/{pdb_id}/prepared_smiles.jsonl` |
| ModelResult | 模型是否返回向量，向量写在哪里？ | `{model_stage}/{pdb_id}/results.jsonl` 和 `candidate_*.npz` |

`object_key` 只用于找到 LigandObject，不是正式样本身份。正式样本身份始终是 `(pdb_id, candidate_id)`。

## 处理主线

```text
occurrences.jsonl
    │
    ├── type_tag == other ──► 只计数
    │
    └── 五类正式 occurrence
          │
          ├── CCD ──► LigandObject.smiles ──► RDKit 规范字符串
          │
          └── BRANCHED
                ├── 完整 mmCIF ──► pdbeccdutils CLC 候选
                ├── 唯一残基身份多重集合匹配 ──► CLC 规范字符串
                └── CLC 没有非空字符串
                       └── LigandObject + present 掩码 ──► 后备规范字符串
                                  │
                                  ▼
                 prepared/{pdb_id}/prepared_smiles.jsonl
                                  │
                    当前 GPU 分片内跨 PDB 展平
                       ├──────────────┬──────────────┐
                       ▼              ▼              │
                  MoLFormer        SMI-TED           │
                  全局 batch       官方 encode       │
                       └──────────────┴──────────────┘
                                  │
                                  ▼
              模型成功时每个 occurrence 一个 `(768,)` NPZ；失败写状态
```

## 样本范围

每个正式 `.sh` 都要求用户明确选择范围：

- `all_existing`：扫描所有存在 `parse/{pdb_id}/occurrences.jsonl` 的 PDB。
- `all_valid`：只读取 `stage1_preparation_box_pool_2/all_valid.json` 中的 PDB。

这个参数只决定处理范围，不会修改任何名单。完整命令见 [README_run.md](README_run.md)。

## CPU 怎样得到 SMILES

### CCD

代码读取 `LigandObject.smiles`，先在不执行化学合法性整理的模式
`sanitize=False` 下建立 RDKit 分子。随后执行 sanitize，即检查并整理原子价态、芳香性等
化学属性；再生成 canonical SMILES，即让同一分子按确定规则得到统一字符串。其中
isomeric 版本保留立体化学，non-isomeric 版本不保留立体化学；后者是两个模型共同使用的
候选。

若 RDKit 无法解析或无法产生非空规范字符串，但原始字符串非空，代码仍保留原文，让官方模型自行尝试。原始字符串为空时，`smiles=null`。

### BRANCHED 的 CLC 主路径

CLC 是 pdbeccdutils 从完整 PDB mmCIF 识别出的 Covalently Linked Component，即共价连接组分。一个 occurrence 与一个 CLC 的比较身份是：

```text
(ccd_id, auth_asym_id, auth_seq_id, insertion_code)
```

两侧按多重集合比较，相同身份出现两次仍计为两个实例。只有恰好一个候选完全相同才选中；代码不做最高重合、并列任选或模糊匹配。

`inter_bonds` 与 CLC 图边会另外比较，但连接比较不改变候选选择。原因是当前 occurrence 没有保存原始 mmCIF 的完整键级和离去原子语义。包返回的电荷、键级、连接差异和包警告只保存为事实，不被包装成唯一化学真值。

LigandObject 或 `ligand_coords.npz` 缺失、损坏时，仍允许有效 CLC 产生 SMILES；这些文件只决定 present 后备路径能否使用。

### BRANCHED 的 present 后备路径

CLC 没有产生非空 SMILES 时，代码才采用以下机械表示：

1. 删除 `present=False` 的模板原子。
2. 只保留两端原子都存在的 LigandObject 原有键。
3. 不新增键，不重写键级，不执行手写离去反应。
4. 让 RDKit 分别尝试 sanitize 和 canonical non-isomeric SMILES。

`present=False` 可能表示缩合离去原子，也可能表示普通缺失原子。因此后备结果只是透明、可复现的表示，不被宣称为唯一化学结构。

### 宽口径原则

只要任一路径得到非空字符串，sanitize 异常、连接不一致、断开片段、金属、形式电荷、单原子离子和 token 诊断都不会自动阻止模型调用。代码不去盐、不取最大组分、不中和电荷，也不因 BRANCHED 根部没有包含受体 ASN 而自动判错。

这些事实进入 diagnostics 和汇总，最终是否使用由后续研究者决定；本目录不写发布门控。

## GPU 怎样产生向量

GPU array 先按 PDB 分片，避免两个任务写同一个 PDB。每个任务再把自己负责的全部未完成
occurrence 展平成一个跨 PDB 列表。batch 是模型一次共同计算的一组分子；这里的 batch
边界不按 PDB 切分。

### MoLFormer

- 官方模型为 `ibm-research/MoLFormer-XL-both-10pct`。
- 默认全局 batch_size 参数为 256。
- 模型加载使用官方特征提取示例的 `deterministic_eval=True`，使相同输入不因前向次数、
  batch 边界或逐 occurrence 重试而重新抽取随机特征映射权重。
- tokenizer 是把 SMILES 拆成模型词表编号的转换器；它用 padding 在短序列末尾补齐长度，
  并明确设置 `truncation=False`，即不主动截短输入。
- 正式向量取官方 `pooler_output`，也就是模型为整个分子汇总出的向量；形状必须是
  `(B, 768)`，B 是当前 batch 的分子数。
- `input_ids` 和 `attention_mask` 只在内存中使用，不落盘。

202 token 只作为预训练参考长度写入诊断，不成为筛选条件。

### SMI-TED Light 289M

- 权重文件为 `smi-ted-Light_40.pt`。
- 一个 GPU 分片先用官方 `normalize_smiles` 区分“得到非空规范字符串”和“返回空值或异常”两组。第一组仍作为一个完整的跨 PDB 列表传给官方 `model.encode`；第二组不被丢弃，而是逐 occurrence 调用同一公开接口。
- 传入的 batch_size 参数默认为 100；冻结的官方源码自行用 `array_split` 分块，实际内部批量可能大于 100，例如总数为 199 时仍可能形成一个 199 项批量。
- 官方规范化、tokenizer、202 token 默认截断、token 聚合和自编码器池化保持原样。
- 运行时使用 `transformers==4.57.6`，与当前冻结的官方实现一致。

代码额外调用同一官方 `normalize_smiles` 和 tokenizer 记录事实。官方 `encode` 内部也会
规范化；失败值会变成 `None`，一个这样的值便会让 tokenizer 拒绝整个混合列表。因此
规范化失败的 occurrence 仍会被公开接口实际尝试，但不会混入规范化成功的大列表。若单条
公开调用返回向量，而独立诊断无法确认 tokenizer 字符串，向量照常保存，
`model_smiles` 记为 `null`；若官方单条调用报错，则记录 `model_failed`。

### 模型异常

MoLFormer 或 SMI-TED 规范化成功组的普通 batch 异常会逐 occurrence 重试。CUDA 是
NVIDIA GPU 执行模型计算所用的软件与设备接口；OOM 表示显存不足；cuBLAS 与 cuDNN 是
CUDA 提供的矩阵计算和神经网络运算库。上述 CUDA 错误、驱动错误、设备断言或非法显存
访问会终止当前分片，因为此时 GPU 运行环境可能已损坏。

只要模型返回数值 `(768,)`，NaN 和正负无穷也原样保存并计数；NaN 表示无法解释为普通
有限实数的数值。它们不会被静默替换，也不会触发自动发布决定。

## 正式产物

输出根目录为：

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2/ligand_language_models
```

目录结构为：

```text
prepared/{pdb_id}/prepared_smiles.jsonl
prepared/reports/shard_*.json
prepared/reports/final_summary.json

molformer/{pdb_id}/results.jsonl
molformer/{pdb_id}/candidate_{candidate_id}.npz
molformer/reports/shard_*.json
molformer/reports/final_summary.json

smi_ted_289m/{pdb_id}/results.jsonl
smi_ted_289m/{pdb_id}/candidate_{candidate_id}.npz
smi_ted_289m/reports/shard_*.json
smi_ted_289m/reports/final_summary.json
```

日常判断只需要看以下字段。`pdb_id` 与 `candidate_id` 共同确定一次配体出现；`type_tag`
是五类正式配体标签；`smiles_source` 说明 CPU 字符串来自 CCD、CLC 还是 present 后备图；
`status` 说明模型是否写出向量；`prepared_smiles` 是 CPU 准备的字符串；`model_smiles` 是
能够确认的 tokenizer 实际输入；`output_file` 是向量文件路径；`error` 是失败原因；
`model_name` 是模型名称；`embedding` 是 `float32 (768,)` 分子级向量。

| 文件 | 核心字段 |
|---|---|
| `prepared_smiles.jsonl` | `pdb_id`、`candidate_id`、`type_tag`、`smiles`、`smiles_source` |
| `results.jsonl` | `pdb_id`、`candidate_id`、`type_tag`、`status`、`prepared_smiles`、`model_smiles`、`output_file`、`error` |
| `candidate_*.npz` | `pdb_id`、`candidate_id`、`object_key`、`model_name`、`prepared_smiles`、`model_smiles`、`embedding` |

完整字段、嵌套 diagnostics 和条件出现规则见 [产物字段参考.md](产物字段参考.md)。真实输入到正式结果的逐步对应见 [真实样本端到端处理示例.md](真实样本端到端处理示例.md)。

`prepared_smiles.jsonl` 和 `results.jsonl` 都是逐 PDB 完成标志。显式覆盖或中断续跑模型阶段时，代码先删除该 PDB 旧的 `candidate_*.npz`；写 `results.jsonl` 前再核对目录中的向量文件集合与 `status=encoded` 的记录完全相同，避免旧向量冒充本次结果。

## 报告与失败语义

每个数组任务写 `{stage}/reports/shard_{index}_of_{count}.json`，记录范围、分片、PDB 和 occurrence 状态、耗时、依赖版本与 GPU 事实。报告不参与样本筛选。

`summarize_outputs.py` 重新扫描逐 PDB 正式文件，生成 `{stage}/reports/final_summary.json`。最高频精确 SMILES 只用于描述，不替代任何 occurrence 的输入。

`missing_pdb_ids` 只表示正式文件不存在。已有 JSONL 若违反字段契约，汇总会直接报错并且不写新的 `final_summary.json`，不会把非法文件伪装成缺失文件。

## 运行入口

稳定离线环境核对、CPU 准备、两个 GPU 模型和三个汇总阶段的可复制命令统一写在 [README_run.md](README_run.md)。所有命令都由用户手动提交；本目录不会自动启动下一阶段。
