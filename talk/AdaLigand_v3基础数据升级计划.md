# AdaLigand v3 基础数据升级计划

> 状态：首轮本地实现已获授权；服务器同步、服务器提交和正式产物写入仍由用户执行。
> 依据：`talk/talking/data_upgrade.md`、`talk/PDB_mmCIF分子与序列层次说明.md`、`文档/规划文档/数据处理_v2.md`、`talk/talking/Matcher_单候选闭集配体身份分类新方案.md`。  
> 当前实现边界：只实现 `all_valid.json` 与 `info.json` 的一次性初始化，以及 `ligand_area.npz` 六个类别掩码的升级。受体序列、残基映射和语言模型仍只保留方案，必须另行授权实现。

## 1. 计划目标

本轮升级在现有 AdaLigand A–G 产物基础上增加以下能力：

1. 维护一个只会缩小的 `all_valid.json`。初始内容固定为当前 split 文件中全部 PDB 的并集。
2. 维护一个不参与训练、过滤或任务编排的 `info.json`。它只保存每个 PDB 已知的缺失、异常、超时和未来质量过滤原因。
3. 在现有 `ligand_area.npz` 中追加六个配体类别体素掩码，供未来五类配体加背景的 softmax 监督使用。
4. 从现有 mmCIF 提取受体蛋白质、RNA 和 DNA 的完整 polymer entity 序列，保存 FASTA 和机器可读清单。
5. 在现有受体原子信息基础上建立“受体原子 → 有坐标残基 → 完整序列位置 → 语言模型特征”的简化映射。
6. 为每个有坐标受体残基保存重原子几何中心，使未来模型可以直接把残基当作三维图节点。
7. 保留当前 49 维受体原子特征，同时新增包含主链标记的 50 维受体原子特征。
8. 为配体和受体语言模型离线特征规定不重复存储、可追溯的产物位置和字段。

本轮不会改变当前 Stage1 的训练样本身份或已经生成的 BOX：

- 不执行序列去冗余；
- 不生成新的 train、validation、calibration 或 test；
- 除新增或更新 `all_valid.json` 与 `info.json` 外，不修改 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2` 的其他内容；
- 不修改 BOX 请求比例、`fraction` 读取逻辑或 batch 抽样逻辑；
- 不处理相同 EMDB 被少数不同 PDB 引用的情况；
- 不运行新的 Stage G 数值质量过滤，也不生成新的 `keep_list.jsonl`；
- 不自动修改现有 `keep_list`、split 文件或 BOX pool 清单。

## 2. 用户执行权与程序职责

用户保留是否接受和继续使用一批产物的唯一决定权。未来实现遵守以下边界：

- AI 在获得额外授权后修改本地代码、编写测试和准备服务器命令。
- 服务器命令由用户亲手提交，除非用户另行明确授权 AI 提交。
- 新代码不自动启动下一处理步骤，不自动调用 Stage release，不创建替用户决定是否接受结果的发布门控。
- 产物校验只生成逐样本诊断和汇总，不根据未知异常数量替用户决定整批数据是否可用。
- 一个 PDB 的普通处理异常、超时或字段不完整不会让其他 PDB 停止处理。当前掩码升级只把这些结果打印到普通日志，不直接更新 `info.json`。
- 只有全局输入无法读取、命令参数自相矛盾、输出根无法安全定位等使整条命令无法开展的问题，才使命令整体以非零退出码终止。
- 只要控制进程完成全部可执行样本并写出汇总，即使存在逐样本失败，命令也可以正常结束；用户根据汇总和逐样本证据决定下一步。

原子写入、写后重读和字段校验用于防止生成半文件或错误文件，不属于发布门控。

## 3. 已确认的设计决定

### 3.1 样本身份

已检查确认，每个 PDB 至多对应一个 EMDB。只有极少数 EMDB 对应多个 PDB，本轮忽略这种反向重复，不加入额外处理逻辑。

因此本轮清单统一使用小写 `pdb_id` 作为主键：

- `all_valid.json` 保存排序后的 PDB 标识列表；
- `info.json` 以 PDB 标识为键；
- PDB 对应的 `emdb_id` 继续从 `raw/pair_list.jsonl` 查询，不在所有问题记录中重复保存。

### 3.2 旧目录和旧产物

- 不重命名 `parse/{pdb_id}`、`density/{pdb_id}`、`labels/{pdb_id}` 目录或现有 BOX pool 中的 PDB 文件。
- 一次性初始化先把 `5y6p`、`7n6g`、`7z8g`、`9hhl`、`9v7i` 的 `parse/{pdb_id}/receptor_tokens.npz` 改名为 `receptor_tokens_old.npz`，再扫描当前产物。这五个 PDB 是历史证据确认的完整辅助主链监督标签缺失样本；不存在有可靠证据的第六个样本。
- 辅助标签缺失、完整图过小或其他原因通过 `all_valid.json` 和 `info.json` 分别表达；`info.json` 中存在问题不自动决定样本是否进入 `all_valid.json`。
- 已存在字段保持原名称、数据类型、形状和数值；新能力使用附加字段或附加文件。

### 3.3 配体类别

五个正式配体类别按类别名的字典序固定为：

```text
ion
nucleotide_like
peptide_like
small_molecule
sugar
```

`other` 不作为第六个 softmax 配体类别。保存 `other_mask` 只用于备用；第一版训练把没有落入五个正式类别的体素当作背景，包括只有 `other_mask=True` 的体素。

五个正式类别发生体素重叠时，不设计专门消歧算法。Dataset 先计算 `background_mask = ~(ion_mask | nucleotide_like_mask | peptide_like_mask | small_molecule_mask | sugar_mask)`，再按 `[background_mask, ion_mask, nucleotide_like_mask, peptide_like_mask, small_molecule_mask, sugar_mask]` 的顺序堆叠布尔掩码并执行 `argmax`。多个正式类别同时为 True 时，固定顺序靠前的类别取得该体素；只有 `other_mask=True`、五个正式类别均为 False 的体素仍属于背景。

## 4. `all_valid.json` 与 `info.json`

### 4.1 初始样本集合

`all_valid.json` 来自 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2/split/` 中当前全部 split JSON 文件的 PDB 并集。初始文件为：

```json
[
  "7abc",
  "8def"
]
```

数组中的 PDB 标识转换为小写，按 `pdb_id` 排序，不保存重复项。它不从 `pair_list.jsonl` 或现有产物目录推导。

### 4.2 只缩小、不自动恢复

未来完整性扫描脚本接收当前 `all_valid.json` 和本次显式要求的产物组，计算：

$$
V_{k+1}=V_k\cap C_k,
$$

其中：

- $V_k$ 是扫描前的 `all_valid.json`；
- $C_k$ 是本次要求的产物全部存在且通过对应字段检查的 PDB 集合；
- $V_{k+1}$ 是扫描后原子替换写出的新名单。

一个 PDB 一旦离开 `all_valid.json`，后续扫描不会自动把它重新加入。未来如果用户希望恢复某个 PDB，应由用户明确授权独立恢复动作，而不是由扫描脚本猜测。

本轮只实现一次性初始化，不实现上述维护扫描器。只有用户运行并验收六类掩码后，才能另行实现只扫描已有产物的维护脚本。

### 4.3 可叠加的扫描要求

未来完整性扫描脚本只实现已经落盘的产物组，不建立复杂插件框架，也不提前写入受体序列等尚未实现的逻辑。计划中的产物组包括：

| 产物组名称 | 需要检查的具体产物 |
|---|---|
| `density_base` | `exp.npz`、`sim.npz`、`ligand_area.npz` 的现有基础字段和共同网格 |
| `atom_labels` | `labels/{pdb_id}/atom_labels.npz` |
| `receptor_base` | `receptor_tokens.npz` 的现有基础数组、受体键表和 `feat (N,49)` |
| `ligand_type_masks` | `ligand_area.npz` 的六个类别掩码 |
| `receptor_sequences` | `receptor_sequences.json`、全量 sequence manifest 中的对应记录和 FASTA 身份 |
| `receptor_residue_mapping` | `receptor_tokens.npz` 的残基层数组及其与原子、chain、entity、序列位置的关系 |
| `ligand_language_model` | 当前要求的正式配体身份均具有指定模型的合法离线向量 |
| `receptor_language_model` | 当前要求的 polymer entity 均具有指定模型的完整逐残基特征 |

调用者每次显式给出要叠加的产物组。脚本不根据目录中偶然出现的文件自动扩大要求。

### 4.4 `info.json`

`info.json` 的键来自 `${ROOT}/raw/pair_list.jsonl` 中全部唯一、小写 `pdb_id`，其中 `${ROOT}` 表示正式 AdaLigand A–G 数据根。初始化时先检查八类当前产物：

```text
parse/{pdb_id}/occurrences.jsonl
parse/{pdb_id}/ligand_coords.npz
parse/{pdb_id}/receptor_tokens.npz
labels/{pdb_id}/atom_labels.npz
density/{pdb_id}/exp.npz
density/{pdb_id}/sim.npz
density/{pdb_id}/ligand_area.npz
density/{pdb_id}/ligand_dist.npz
```

存在可靠历史证据时合并对应问题记录。一个 PDB 不在当前 split 并集内、又没有可恢复的逐 PDB 历史原因时，记录 `unknown_issue`，以区别于“已检查且没有已知问题”。位于 split 并集且没有已知问题的 PDB 保存空列表：

```json
{
  "7abc": [],
  "8def": []
}
```

发现问题后只追加具体记录：

```json
{
  "7abc": [
    {
      "action": "receptor_sequences",
      "reason": "sequence_position_unmapped",
      "detail": "chain B 的一个有坐标残基缺少合法 label_seq_id",
      "evidence": "reports/.../7abc.json"
    }
  ]
}
```

每项问题至少说明：

- `action`：在哪个处理动作中发现；
- `reason`：短而稳定的原因名称；
- `detail`：能够独立理解的具体事实；
- `evidence`：可选的详细报告位置。

`info.json` 不保存 `valid/invalid`、`released/unreleased` 或类似替用户做决定的状态。重复执行同一动作时，完全相同的 `action + reason + detail + evidence` 不重复追加。

一次性初始化由控制进程统一原子写出 `all_valid.json` 和 `info.json`。初始化脚本、配套 shell 和历史原因清单属于机械性临时代码，保存在 `Data_Preprocessing/Ori_Data_upgrade/tmp/`，不作为后续科学主线入口。

## 5. `ligand_area.npz` 的六个类别掩码

### 5.1 新增字段

每个 `density/{pdb_id}/ligand_area.npz` 追加：

| 字段 | 数据类型与形状 | 具体含义 |
|---|---|---|
| `ion_mask` | `bool (1,D,H,W)` | 当前 PDB 中全部 `type_tag=ion` occurrence 的 ligand-area 并集 |
| `nucleotide_like_mask` | `bool (1,D,H,W)` | 当前 PDB 中全部 `type_tag=nucleotide_like` occurrence 的 ligand-area 并集 |
| `peptide_like_mask` | `bool (1,D,H,W)` | 当前 PDB 中全部 `type_tag=peptide_like` occurrence 的 ligand-area 并集 |
| `small_molecule_mask` | `bool (1,D,H,W)` | 当前 PDB 中全部 `type_tag=small_molecule` occurrence 的 ligand-area 并集 |
| `sugar_mask` | `bool (1,D,H,W)` | 当前 PDB 中全部 `type_tag=sugar` occurrence 的 ligand-area 并集 |
| `other_mask` | `bool (1,D,H,W)` | 当前 PDB 中全部 `type_tag=other` occurrence 的 ligand-area 并集，只作备用 |

每个字段始终存在。当前 PDB 没有某一类别时，对应数组为全 False。

### 5.2 生成规则

现有 `mask_{candidate_id}` 保存一个 occurrence 的稀疏 ZYX 体素坐标，`occurrences.jsonl` 保存同一 `candidate_id` 的 `type_tag`。生成步骤为：

1. 建立六个全 False 的 `(1,D,H,W)` 布尔数组；
2. 读取每个 occurrence 的 `type_tag`；
3. 使用对应 `mask_{candidate_id}` 的稀疏坐标把该类别数组置为 True；
4. 不清除不同类别之间的重叠体素；
5. 不改变现有 `union_mask`、`mask_{candidate_id}` 或 `centroid_voxel_{candidate_id}`。

六类掩码的并集应等于现有 `union_mask`。该关系只在临时校验或结果分析中检查，不加入正式批处理的发布门控。

### 5.3 兼容方式

- 继续保留现有 `schema_version=3`，把六个字段视为可识别的附加标签；不因添加字段让现有 Pocket_Plus BOX pool 拒绝读取。
- 当前 E3 校验函数需要从“拒绝全部额外字段”改为“允许六个类别掩码，并在六个字段出现时检查它们全部齐全”。
- 尚未升级的旧 `ligand_area.npz` 仍是合法基础产物；只有未来完整性扫描显式要求 `ligand_type_masks` 时，缺少六个字段的 PDB 才离开 `all_valid.json`。
- 升级一份 `ligand_area.npz` 时，先证明全部旧字段逐数组保持一致，再原子替换正式文件。
- 六个字段已经全部存在时直接跳过；六个字段只存在一部分时打印 `partial_existing_masks` 并保持文件不变；六个字段全部不存在时才生成。
- 批处理入口必须显式接收 `--sample-scope all_valid|all_existing`。`all_valid` 只处理 `all_valid.json` 中的 PDB；`all_existing` 处理所有已有 `density/{pdb_id}/ligand_area.npz` 的 PDB。本轮正式命令使用 `all_existing`。
- 正式 shell 必须由零基连续的 Slurm 数组启动。本轮使用 `--array 0-11`：每个数组任务先得到相同的排序全局 PDB 清单，再处理 `global_pdb_ids[SLURM_ARRAY_TASK_ID::SLURM_ARRAY_TASK_COUNT]`。12 个分片两两不重叠且并集等于全局清单；每个分片内部使用本任务的 `SLURM_CPUS_PER_TASK` 并行处理 PDB。

### 5.4 第一版多分类读取

第一版多分类体素标签使用六个 softmax 通道：

```text
0 = background
1 = ion
2 = nucleotide_like
3 = peptide_like
4 = small_molecule
5 = sugar
```

`other_mask` 不进入类别通道。只有 `other_mask=True`、五个正式类别均为 False 的体素仍标为 background。

## 6. 现有受体索引到底表示什么

### 6.1 mmCIF 中的原始身份字段

受体原子来自 mmCIF `_atom_site`。与本轮映射直接相关的原始字段为：

| mmCIF 字段 | 具体含义 |
|---|---|
| `label_entity_id` | 当前原子属于哪个 polymer entity，也就是哪一种蛋白质、RNA 或 DNA 分子定义 |
| `label_asym_id` | 当前原子属于该 polymer entity 的哪个结构 chain 副本 |
| `label_seq_id` | 当前原子所在残基在 polymer entity 完整规范序列中的一基位置 |
| `auth_asym_id` | 结构作者使用的 chain 名称，保留用于和论文或可视化软件对应 |
| `auth_seq_id` | 结构作者使用的残基编号，可能跳号或带插入码，不能直接索引语言模型数组 |
| `label_comp_id` | 坐标残基的化学组分名称，例如 `ALA`、`MSE`、`A` 或 `DA` |

### 6.2 现有 `chain_index`

`receptor_tokens.npz::chain_index` 不是 PDB/mmCIF 原始字段。AdaLigand 按受体原子首次出现的 `label_asym_id` 建立从 0 开始的紧凑编号：

```text
label_asym_id A → chain_index 0
label_asym_id B → chain_index 1
label_asym_id C → chain_index 2
```

`chain_index[i]` 表示第 `i` 个受体原子属于哪一个有坐标 chain。它便于使用整数分组原子，但当前文件没有保存整数编号对应的 `label_asym_id`、`auth_asym_id` 和 `entity_id`。

### 6.3 现有 `res_index`

`receptor_tokens.npz::res_index` 也不是 PDB/mmCIF 原始序列编号。AdaLigand 根据下列坐标残基身份，在受体原子首次出现时建立从 0 开始的紧凑编号：

```text
(label_asym_id, label_comp_id, label_seq_id 或 auth_seq_id, insertion_code)
```

`res_index[i]` 表示第 `i` 个受体原子属于当前有坐标受体残基集合中的哪一项。同一残基的全部重原子具有同一个 `res_index`。

`res_index` 不能直接当作完整序列位置，原因包括：

- 它同时编号多个 chain；
- 没有坐标的序列残基不会获得 `res_index`；
- 坐标中间缺失残基时，连续 `res_index` 不代表连续 `label_seq_id`；
- `res_index` 的建立顺序服从当前原子记录顺序，不是语言模型数组契约。

### 6.4 为什么继续保留它们

`chain_index` 和 `res_index` 已经被现有产物和程序使用。本轮不改写它们，而是补充它们指向的 chain 表和残基表。这样既保留旧程序，又避免为每个原子重复保存 entity 和完整序列位置。

## 7. 简化后的受体原子—残基—序列映射

### 7.1 总体关系

本轮采用以下简化关系：

```text
受体原子 i
  ├── chain_index[i] ───────────────→ receptor_sequences.json 中的 chain
  └── res_index[i] = r ─────────────→ receptor_tokens.npz 中第 r 个有坐标残基
                                         ├── residue_chain_index[r]
                                         ├── residue_entity_index[r]
                                         ├── residue_sequence_index[r]
                                         └── residue_centroid[r]

第 r 个有坐标残基
  └── residue_entity_index[r] = e ──→ receptor_sequences.json 中第 e 个 polymer entity
       residue_sequence_index[r] = s → 该 entity 的完整序列位置 s
                                        → 语言模型 features[s]
```

因此不再新增逐原子的 `sequence_entity_index (N,)` 和 `sequence_residue_index (N,)`。现有 `res_index (N,)` 已经完成“原子属于哪个有坐标残基”的映射；entity、序列位置和残基坐标只需要按残基保存一次。

### 7.2 `receptor_tokens.npz` 新增的残基层数组

设：

- $N$ 为受体重原子数；
- $R$ 为具有至少一个受体重原子坐标的残基数；
- $C$ 为具有受体原子坐标的 chain 数；
- $E$ 为当前 PDB 的 polymer entity 数。

计划追加：

| 字段 | 数据类型与形状 | 具体含义 | 特殊值 |
|---|---|---|---|
| `residue_centroid` | `float32 (R,3)` | 每个有坐标残基全部受体重原子世界 XYZ 坐标的算术平均，单位 Å | 不允许 NaN 或 Inf |
| `residue_type` | `uint8 (R,)` | 每个残基的 AdaLigand 残基类型编号，与该残基原子的 `res_type` 一致 | 无法归一化时使用现有 `UNK` 编号 |
| `residue_chain_index` | `int32 (R,)` | 每个残基属于哪个 chain；数值必须位于 `[0,C)` | 无合法 chain 时为 `-1` |
| `residue_entity_index` | `int32 (R,)` | 每个残基属于 `receptor_sequences.json::entities` 中哪一个 polymer entity | 无法可靠映射时为 `-1` |
| `residue_sequence_index` | `int32 (R,)` | 每个残基在对应 entity 完整规范序列中的零基位置 | 缺失、非法或越界时为 `-1` |

`res_index` 必须恰好覆盖 `[0,R)`，并满足：

- 所有 `res_index[i]=r` 的原子共同定义 `residue_centroid[r]`；
- 同一 `r` 的全部原子具有相同的 `chain_index`；
- 同一 `r` 的全部原子具有相同的残基类型；
- `residue_sequence_index[r]` 优先由合法 `label_seq_id-1` 得到，并通过 mmCIF polymer sequence 表核对；
- 不使用 `auth_seq_id` 或坐标出现顺序猜测语言模型位置。

### 7.3 残基坐标和未来残基图

`residue_centroid[r]` 定义为：

$$
\mathbf c_r=\frac{1}{|A_r|}\sum_{i\in A_r}\mathbf x_i,
$$

其中：

- $A_r$ 是满足 `res_index[i]=r` 的受体重原子集合；
- $\mathbf x_i$ 是 `coords[i]` 保存的世界 XYZ 坐标，单位 Å；
- $\mathbf c_r$ 是第 $r$ 个有坐标残基的三维几何中心。

这些坐标足以让未来模型把有坐标残基作为图节点。残基图的空间半径边、K 近邻边或序列相邻边在模型读取时构造，本轮不额外落盘残基图边，避免提前锁定模型结构。

完整序列中没有原子坐标的残基仍保存在序列和语言模型特征中，但不会出现在 `residue_centroid` 中。

## 8. `receptor_sequences.json` 与全量 FASTA

### 8.1 每个 PDB 的序列和 chain 表

每个 PDB 新增：

```text
parse/{pdb_id}/receptor_sequences.json
```

建议结构为：

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
    }
  ]
}
```

`entity_index` 和 `chain_index` 是 AdaLigand 在当前 PDB 内建立的紧凑整数下标：

- `entities[entity_index]` 保存一条完整 polymer entity 序列；
- `chains[chain_index]` 保存一个实际有坐标的 chain；
- `chains[chain_index].entity_index` 指明该 chain 复用哪条 entity 序列；
- `chains[chain_index]` 的编号与 `receptor_tokens.npz::chain_index` 完全一致。

同一个 polymer entity 即使具有多个 chain 副本，也只保存和计算一次完整序列。

### 8.2 序列来源

序列优先从已经下载的 mmCIF `_entity_poly`、`_entity_poly_seq`、`_struct_asym` 和 `_pdbx_poly_seq_scheme` 读取，不从有坐标残基临时拼接，也不为已有 mmCIF 再发起网络下载。

- `_entity_poly` 提供 polymer 类型和一字母序列；
- `_entity_poly_seq` 提供 entity 内逐残基序列位置；
- `_struct_asym` 把 `label_asym_id` chain 连接到 entity；
- `_pdbx_poly_seq_scheme` 连接规范序列位置、chain、作者编号和插入码。

缺少必要 category、序列非法或映射不完整时记录具体问题，不使用作者编号、坐标顺序或其他隐式回退构造另一条序列。

### 8.3 全量产物

从每个 PDB 的 `receptor_sequences.json` 聚合：

```text
sequences/
├── protein.fasta
├── rna.fasta
├── dna.fasta
└── sequence_manifest.jsonl
```

每个 polymer entity 在相应 FASTA 中只出现一次。`sequence_id` 使用：

```text
{pdb_id}:entity:{entity_id}
```

`sequence_manifest.jsonl` 至少保存 `sequence_id`、`pdb_id`、`entity_id`、`polymer_type`、`chain_ids`、`sequence_length`、`canonical_sequence` 和 mmCIF 来源摘要。

DNA/RNA hybrid 的正式分类仍需在实现前由用户确认；程序不根据字符内容自行猜测为 DNA 或 RNA。

## 9. 49 维与 50 维受体原子特征

### 9.1 现有 49 维字段不能原地改形状

当前 `receptor_tokens.npz::feat` 为 `float32 (N,49)`：

```text
49 = 元素 one-hot 6
   + 残基类型 one-hot 25
   + 理化性质 8
   + 原子质量 1
   + 局部原子密度直方图 9
```

Pocket_Plus 当前 Stage1 Dataset 明确要求第二维等于 49。直接把 `feat` 改为 `(N,50)` 会让当前 Stage1 和已有模型拒绝读取，因此本轮保留 `feat` 原样。

### 9.2 新增 `feat_with_backbone`

在同一 `receptor_tokens.npz` 中追加：

```text
feat_with_backbone  float32 (N,50)
```

其定义为：

```text
feat_with_backbone[:, 0:49] = feat
feat_with_backbone[:, 49]   = is_backbone.astype(float32)
```

最后一维取值为：

- `1.0`：该原子是蛋白质或核酸主链原子；
- `0.0`：该原子不是主链原子。

这是有意的字段重复：旧程序继续读取 `feat` 和独立 `is_backbone`，新模型可以直接读取连续的 50 维原子输入。语言模型特征不拼入这 50 维字段，避免把模型身份和基础受体契约绑定。

## 10. 受体语言模型特征

受体语言模型对完整 polymer entity 序列生成逐残基特征，不按 atom 或 chain 重复计算。建议保存：

```text
receptor_language_models/{model_identity}/{sequence_key}.npz
```

其中：

- `model_identity` 同时包含模型名称和冻结 checkpoint revision；
- `sequence_key` 根据 polymer 类型、规范序列内容和模型输入规则计算，用于跨 PDB 复用相同序列特征；
- PDB 内身份仍使用 `sequence_id={pdb_id}:entity:{entity_id}`，不能让内容去重键替代 PDB entity 身份。

建议字段为：

| 字段 | 数据类型与形状 | 具体含义 |
|---|---|---|
| `features` | `float16/float32 (L,H)` | 完整规范序列中 `L` 个残基的 `H` 维特征 |
| `valid_mask` | `bool (L,)` | 每个序列位置是否具有可用特征 |
| `sequence_sha256` | 字符串标量 | 实际输入模型的规范序列摘要 |
| `model_name` | 字符串标量 | 模型名称 |
| `model_revision` | 字符串标量 | checkpoint revision |
| `input_length` | 整数标量 | 实际输入残基数，必须与 `L` 一致 |

一个有坐标残基 $r$ 读取语言模型特征的方式为：

```text
e = residue_entity_index[r]
s = residue_sequence_index[r]
features_for_entity_e[s]
```

同一 entity 的多个 chain 副本在相同序列位置共享语言模型特征，但保留各自不同的 `residue_centroid`。

首批受体语言模型名称、长序列分窗方式、特征保存精度和 DNA/RNA 模型尚未冻结，实施前需要用户另行确认。

## 11. 配体语言模型特征

配体语言模型部分依据 `talk/talking/Matcher_单候选闭集配体身份分类新方案.md`。第一轮计划比较 MoLFormer 与 SMI-TED$_{289M}$，按配体化学身份 `object_key` 计算，不按 occurrence 重复计算。

建议保存：

```text
ligand_language_models/{model_identity}/{safe_object_key}.npz
```

每份产物至少保存：

- 原始结构身份和 `object_key`；
- 原始 SMILES；
- 实际送入模型的规范化 SMILES；
- 模型名称、checkpoint revision 和 tokenizer revision；
- token 数；
- 是否超过模型长度限制；
- 是否包含断开的多个组分、金属或电荷；
- 输入规范化是否删除立体信息；
- 冻结向量及其数据类型和维度；
- 失败或不支持原因。

五个正式配体类别中的一个配体身份如果缺少本轮指定语言模型的合法产物，对应 PDB 在显式执行 `ligand_language_model` 完整性扫描后离开 `all_valid.json`。`type_tag=other` 的配体不作为正式类别要求。

超过模型 token 上限的配体不静默截断并伪装成完整表示。具体采用“不支持”、片段聚合还是其他模型，需要在语言模型实施前由用户确认。

## 12. 计划执行顺序

代码实现和服务器执行分别授权。当前仅阶段 A 与阶段 B 的本地实现已获授权；服务器命令仍由用户提交。

### 阶段 A：名单和问题留档

1. 在 `Data_Preprocessing/Ori_Data_upgrade/tmp/` 实现 `all_valid.json` 与 `info.json` 的一次性初始化入口、配套 shell 和历史原因清单。
2. 在扫描八类当前产物前，把五个已确认样本的 `receptor_tokens.npz` 改名为 `receptor_tokens_old.npz`。
3. 使用本地小型 fixture 测试 split 并集、问题去重、`unknown_issue`、五文件改名和原子写。
4. 准备服务器初始化命令，由用户提交。
5. 读取运行结果，形成逐原因、逐文件和总数量分析；不自动启动下一阶段。

### 阶段 B：六类 ligand-area 掩码

1. 最小修改现有 E3 校验器，使旧文件、六字段完整文件均合法，六字段部分存在时明确报错。
2. 编写旧字段不变、类别并集、空类别、类别重叠和 `other` 背景语义测试。
3. 在 `Data_Preprocessing/Ori_Data_upgrade/` 编写必须显式选择 `all_valid` 或 `all_existing` 的批量入口；本轮使用 `all_existing`，并按排序全局清单的交错切片分配给 12 个 Slurm 数组任务。
4. 为该 Python 入口编写配套 shell，从 `SLURM_ARRAY_TASK_ID`、`SLURM_ARRAY_TASK_COUNT` 和 `SLURM_CPUS_PER_TASK` 传递分片与分片内并行参数；通过 `训练与运行` 的完整模式准备服务器命令，由用户提交。
5. 每个 PDB 的成功、跳过、字段部分存在和异常只写普通日志。任务结束后由子代理统一汇总日志，不直接修改 `info.json`。
6. 用户运行并验收掩码后，才能另行授权实现维护 `info.json` 与 `all_valid.json` 的扫描器。

### 阶段 C：受体序列、残基映射和 50 维特征

1. 从现有 mmCIF 解析 polymer entity、chain 和规范序列。
2. 生成 `receptor_sequences.json`。
3. 在 `receptor_tokens.npz` 中追加残基层数组和 `feat_with_backbone`。
4. 聚合 protein、RNA、DNA FASTA 和 `sequence_manifest.jsonl`。
5. 编写映射、残基中心、序列缺失、修饰残基和多 chain 复用测试。
6. 准备服务器命令，由用户提交。
7. 汇总逐样本问题并更新 `info.json`。
8. 用户决定后显式运行 `receptor_sequences` 与 `receptor_residue_mapping` 完整性扫描。

### 阶段 D：配体语言模型

1. 冻结 MoLFormer 与 SMI-TED 的精确模型和 tokenizer revision。
2. 从 `object_key` 清单准备规范化 SMILES 和长度分桶。
3. 本地验证产物字段、去重和失败记录。
4. 准备 GPU 服务器命令，由用户提交。
5. 分析五类配体的可编码率、超长率、立体信息删除率和失败原因。
6. 用户决定后显式运行 `ligand_language_model` 完整性扫描。

### 阶段 E：受体语言模型

1. 用户先决定蛋白质、RNA、DNA 使用的模型和长序列处理方式。
2. 按 `sequence_key` 去重并生成逐残基特征。
3. 验证第一维与完整规范序列长度一致。
4. 准备服务器命令，由用户提交。
5. 分析各 polymer 类型的完整覆盖率和缺失位置。
6. 用户决定后显式运行 `receptor_language_model` 完整性扫描。

任何阶段都不会自动进入下一阶段，也不会修改当前 split 或 BOX pool。

## 13. 本地测试要求

### 13.1 名单和留档

- 初始名单来自当前全部 split JSON 文件的唯一 PDB 并集；
- 重复 PDB 不进入输出；
- `info.json` 初始化覆盖 `pair_list.jsonl` 中的全部唯一 PDB；
- split 外且没有可靠逐 PDB 原因的样本记录 `unknown_issue`；
- 五个已确认缺失完整辅助主链监督标签的受体文件按约定改名；
- 完全相同的问题记录不会重复追加。

### 13.2 类别掩码

- 六个字段均为 `bool (1,D,H,W)`；
- 空类别为全 False；
- 每个 `mask_{candidate_id}` 只进入其 `type_tag` 对应类别；
- 六类并集等于原 `union_mask`；
- 五个正式类别的固定顺序与类别编号一致；
- `other` 体素在第一版整数标签中成为 background；
- 类别重叠按固定顺序产生确定结果；
- 新增字段前后所有旧数组逐数组相等。
- 六字段完整的文件不重复写；六字段部分存在的文件保持不变；
- `all_valid` 与 `all_existing` 两种样本范围只选择各自规定的 PDB。
- `--array 0-11` 的 12 个分片两两不重叠，并集严格等于未分片的排序全局 PDB 清单。

### 13.3 受体序列和残基映射

- `chain_index` 可以在 `receptor_sequences.json::chains` 中找到唯一记录；
- chain 的 `entity_index` 可以在 `entities` 中找到唯一记录；
- `res_index` 恰好覆盖全部有坐标残基；
- 同一 `res_index` 的全部原子具有一致 chain 和残基类型；
- `residue_centroid` 等于该残基全部受体重原子坐标的算术平均；
- 每个非负 `residue_sequence_index` 位于对应完整序列范围内；
- 同一 entity 的不同 chain 可以映射到相同序列位置，但具有不同残基坐标；
- 没有坐标的序列残基允许只存在于完整序列和语言模型特征中；
- 不使用 `auth_seq_id` 或坐标顺序猜测无法确认的序列位置；
- `feat_with_backbone[:, :49]` 与旧 `feat` 完全相等；
- `feat_with_backbone[:, 49]` 与 `is_backbone.astype(float32)` 完全相等；
- 当前 Pocket_Plus Stage1 继续读取旧 `feat (N,49)`，行为不变。

### 13.4 语言模型产物

- 相同 `object_key` 的配体不重复编码；
- 相同 `sequence_key` 的受体序列不重复编码；
- 特征中没有 NaN 或 Inf；
- 受体特征第一维等于完整序列长度；
- 配体超长、解析失败和规范化变化均有明确记录；
- 模型名称、模型 revision、tokenizer revision 和输入摘要能够重建产物身份。

## 14. 完成后的分析报告

每次由用户提交的服务器任务完成后，AI 可以在用户要求下进行只读监控和最终分析。报告至少包含：

- 输入 PDB 数、成功数、跳过数、超时数和异常数；
- 每种 `reason` 的数量和具体 PDB；
- 已知问题与未知问题分别列出；
- 失败是否集中在特定序列长度、配体类别、原子数或文件状态；
- 新旧字段一致性检查；
- `all_valid.json` 扫描前后数量和被删除 PDB；
- 对每类问题是否值得补算、修复或直接接受的具体建议。

报告只提供事实和建议，不替用户改变名单、修改 split、重新运行任务或决定产物可以发布。

## 15. 后续阶段仍需用户确认的事项

以下事项不阻止本计划落盘，但在相应代码实现前必须确认：

1. DNA/RNA hybrid 写入哪一种 FASTA，还是保存为独立类别；
2. 修饰残基无法转换成标准一字母符号时使用未知字符还是排除该 entity；
3. 首批受体蛋白质、RNA 和 DNA 语言模型及其 checkpoint revision；
4. 受体语言模型长序列的分窗和重叠区域聚合方式；
5. 语言模型特征保存为 `float16` 还是 `float32`；
6. 配体超过 202 token 时采用“不支持”、片段聚合还是其他编码器。

阶段 A 与阶段 B 仅获本地实现和本地测试授权。AI 不同步服务器、不提交服务器任务、不写正式服务器产物；这些动作由用户亲手执行，除非用户再次明确授权。阶段 C–E 仍不得开始实现。
