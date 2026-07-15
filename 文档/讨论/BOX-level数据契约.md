# AdaLigand BOX 级数据契约

> **本文定位**：AdaLigand 把“从冷冻电镜密度图里找配体并建模”拆成 Stage1 Find、Stage1 proposal selector、Stage2 Match、Stage3 Build 与可选轻量密度 U-Net。这些模型的训练和推理产物统一通过 BOX 组织。本文是“整图级产物 → 模型可读取的 BOX 级样本”之间的数据契约唯一权威：一个 BOX 存什么、怎样共享、如何添油、怎样追溯和各模型怎样读取。
>
> **上下游**：
> - **上游** = `文档/规划文档/数据处理_v2.md`，它产出**整图级 / occurrence 级**产物（受体 token、LigandObject、per-occurrence GT 坐标与两套中心、原子标签、exp/sim/ligand_area 密度网格、质量/过滤），**到此为止，不切 BOX**。本文从这里接手。
> - **下游** = `文档/讨论/模型总规划_v2.md`（Stage2 预测什么/损失）、`文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md`（怎么算/算子）。它们消费本文定义的 BOX 块；数据怎么存只在本文写一遍，那两份只留指针。
> - **产物来源** = `文档/规划文档/Stage1训练与多阈值推理.md`：全图概率、组件森林、候选谱系组（CLG）、Global Proposal、局部物化、候选打分、反链选择与可选精修的**产法和语义**归它；本文只规定这些量**怎么存**。
>
> **边界**：本文只管“**盘上长什么样**”。“块怎么拼成模型张量”见 `文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md §4`；“模型拿这些预测什么”见 `文档/讨论/模型总规划_v2.md`。本文不重复运算与监督细节。
>
> **治理与精度**：本文规定目标逻辑 schema，包括字段语义、解码后的 shape 与逻辑 dtype。物理文件可以压缩或分片，但不能改变解码结果。若实现与本文漂移，先按 `AGENTS.md` 审计并请求回填决定，不能让代码静默覆盖契约。

---

## §0 一句话总览

> 一个 BOX 不是一坨打包好的张量，而是**一个轻量身份 + 若干按来源分开、可拆卸、可添油的块**。重的东西**整图级存一次**，BOX 只是切片入口；模型在运行时拿一份**清单（配方）**，按需读到它要的块。换来源、换档位、加特征，都不动模型，也不重写老数据。
>
> **统一锚（贯穿全文）**：所有 BOX 共用同一套轻量身份 schema。`center/bias/context` 只表示训练 BOX 原点来源；blob 只来自全图推理并只属于 `infered_box`。一个 `clg_group_parent` 角色的 `infered_box` 对应一个 CLG，框内可以有多个 Global Proposal Candidate；Stage2/3 的正式候选行是反链选择后的 Global Proposal，而不是 BOX 本身。局部重跑的 mask 只作辅助观察，不能替换全图候选身份。

---

## §1 四层存储模型（核心）

数据分四层，各层的生命周期、粒度、可变性都不同。这是整个契约的骨架。

| 层 | 名称 | 粒度 | 何时产生 | 可变性 | 装什么 |
|---|---|---|---|---|---|
| **1** | 整图级落盘 | per-PDB | 数据处理阶段（慢、贵） | 固定 | exp/sim 密度、49 维受体特征、ligand_area mask + 两套质心、binding/instance 原子标签、LigandObject、per-occurrence GT 坐标 |
| **2** | BOX 描述子 | per-BOX（极小） | 枚举或物化 BOX 时 | 冻结 | 通用几何身份；`infered_box` 额外记录 materialization role、proposal run、CLG 和来源节点 |
| **3** | per-BOX 添油 | 仅需要添油的 BOX，按稳定 ID keyed | Stage1 整图推理后 / 任意时刻 | **只增不改** | proposal/CLG 表、Group-parent 共享 voxel/P/receptor 表、候选行索引、GT overlap、selector score、selection result、可选 refinement 与密度 U-Net 特征 |
| **4** | 现场算 | per-BOX，运行时 | dataset `__getitem__` | 瞬时 | 56 维辅助密度通道、diff、O-distance、覆盖矩阵装配、materialize 扰动 |

**为什么这么分**：

- 慢且固定的东西（第 1 层）**每个 PDB 整图算并存一次、现场切片复用**，避免把同一份密度、标签和受体拷进上百万个 80³ BOX 文件。这是避免物化重复大数组，**不是对 BOX 的空间位置或体素内容去重**。
- BOX 身份（第 2 层）小、冻结，是一切的索引锚；空间重合的两条采样记录也可以同时存在。
- 只有 Stage1 整图推理后才存在的第 3 层量只为 `infered_box` 添油。基础 proposal、不同 selector checkpoint、不同 selection 参数和 refinement 各自写独立 addon，不能原地覆盖。
- 便宜的派生量（第 4 层）现场算，省盘、留灵活。

**对接概览**（详见 §8）：Stage1 切第 1 层；Stage2 用第 2 层 + 第 3 层；Stage3 用第 2 层几何 + 第 3 层 blob 的 prompt 点；UNet 吃第 1 层密度、其特征按 box 落第 3 层。

---

## §2 第 1 层：整图级落盘（per-PDB）

凡是"相对固定、算起来慢、且对一张图全局成立"的东西，**per-PDB 存一份**，BOX 阶段只切片。

| 产物 | 形式 | 来源（数据处理_v2） | 备注 |
|---|---|---|---|
| `exp` 密度 | `(1,D,H,W) float32` | Stage E1 `exp.npz` | 整图、已重采样 1Å、不归一化 |
| `sim` 密度 | `(1,D,H,W) float32` | Stage E2 `sim.npz` | 模拟图，与 exp 同网格 |
| `ligand_area` mask | `(1,D,H,W) bool` + 逐 occurrence mask | Stage E3 `ligand_area.npz` | 体素级 GT 区域；**逐 occurrence `mask_{cid}` 必存**（覆盖派生要数体素，§4.3） |
| occurrence 质心（两套） | `centroid_voxel_{cid}`、`centroid_atom_{cid}` | E3 / C4（见 §2.2） | 用途不同，分开维护 |
| per-occurrence GT 坐标 | `coords_{cid} (M,3)`、`present_{cid} (M,) bool` | Stage C4 `ligand_coords.npz` | 真实 pose |
| 受体 token（几何 + 键表 + 49 维特征） | coords/element/res_type/atom_name/res_index/chain_index + bond_index/bond_type + `feat(N_rec,49)` | Stage C3 `receptor_tokens.npz`（数据处理 §5.4） | 全局世界坐标；49 维**必须整图算**（见 §2.1） |
| binding / instance 原子标签 | `binding_atom (N_rec,) bool`、`instance_id (N_rec,) int32`、`nearest_dist` | Stage D `atom_labels.npz` | per-occurrence 实例 |
| LigandObject | 化学（atoms/bonds/atom_names/smiles/ref_pos） | Stage C2 `ligand_objects/{object_key}.npz` | 去重、跨 PDB 复用 |

**不在第 1 层的两样**：
- `diff` 密度**不落盘**——`diff = exp − sim` 在第 4 层现场算（exp/sim 同网格，安全）。
- UNet voxel 特征**不整图落盘**——按 box 只存"预测 ligand-area 之内"的体素特征（§4.4）。

### 2.1 49 维受体特征（统一、纯受体、必须整图算）

**所有模型的受体原子特征统一用这 49 维**（沿用 Pocket_Plus 已验证有效的特征工程）。构成（`Make_Data/PDB_processor/config.py`）：

```
49 = 元素 one-hot(6) + 残基类型 one-hot(25) + 理化性质(8) + 原子质量(1) + 局部密度直方图(9)
```

**这 49 维完全是纯受体的，与密度图无关。** 其中"局部密度"的 9 维是**原子堆积直方图**——对每个原子用 KD-tree 数它在 0–2, 2–4, …, 16–18 Å 各距离壳层内的**邻居原子数**，再 log1p（`compute_local_density_sparse`）。它是几何/堆积描述子，不是 cryo-EM 密度。由此两条硬约束：

1. **三档统一**：49 维在纯密度/纯受体/统一三档里**逐位一致**，不需要 40/49 切换。
2. **必须整图算、再切片**：那 9 维直方图依赖"框外的真实邻居"。若在 BOX 内部现算，边缘原子会数漏邻居、算错。所以 49 维**对完整受体算一次**，存第 1 层，BOX 阶段只按 `atom_global_indices` 切片。

### 2.2 occurrence 的两套中心（用途分开）

每个 occurrence 维护两套几何中心，**各管各的**，不可混用：

- **`centroid_voxel_{cid}`**：ligand_area mask 的**体素质心**（E3 产出）。用于 **recrop 落框**（center box 切在这）与 **prompt 点**的同源量——凡涉及"体素/mask 帧"的几何用它。
- **`centroid_atom_{cid}`**：**present 重原子坐标的几何中心** = `mean(coords_{cid}[present_{cid}])`，**派生自 C4**。用于 **box↔occurrence 的距离与 in-box 判定**（§3.2 / §6）——凡涉及"配体真实位置"的几何用它。

> `centroid_atom` 是 C4 既有产物（`coords`+`present`）的纯派生。**已定物化进 `ligand_coords.npz`**（由 C4 产：`centroid_atom_{cid}=mean(coords_{cid}[present_{cid}])`，见 `数据处理 §5.5`），下游直接读、不必现场重算。

---

## §3 第 2 层：BOX 描述子（per-BOX，冻结）

一个 BOX 的"身份"。极小、纯元数据、枚举时一次算好写死。

### 3.1 描述子字段

```json
{
  "pdb_id": "7abc",
  "box_type": "center",              // 开放字符串，见 §3.3
  "box_id": 17,                       // (pdb_id, box_type) 内唯一
  "box_start_zyx": [z0, y0, x0],     // 完整网格中的整数起点
  "origin_xyz": [x, y, z],           // 世界坐标 Å
  "shape_zyx": [80, 80, 80],
  "voxel_size_xyz": [1.0, 1.0, 1.0],
  "provenance": "...",               // bias 实际偏移向量 / context 随机种子 / infered_box 来自哪次全图推理 + 阈值
  "materialization_role": null,       // infered_box 才使用，见下文
  "proposal_run_id": null,
  "clg_id": -1,
  "source_tree_id": -1,
  "source_node_id": -1,
  "occ_distances": [                  // 稀疏：到各 in-box occurrence 的距离，见 §3.2
    {"cid": 3, "dist": 1.2},
    {"cid": 5, "dist": 31.7}
  ],
  "addons": ["stage1_blob", "..."]   // 本 box 现有哪些第 3 层添油
}
```

- **`box_id` 在 `(pdb_id, box_type)` 内唯一**：每个 box_type 的枚举器各自从 0 起编号，互不协调；寻址用 `(box_type, box_id)`（第 3 层添油同此 key，§4.1）。
- `box_start_zyx: int32[3]` 使全图 voxel index 与 BOX 局部 index 能精确互换。`origin_xyz: float32[3]` 严格定义为 BOX 局部 voxel `[0,0,0]` 的**中心**世界坐标；底层文件若使用 voxel 外角，数据适配层必须先转换。
- `shape_zyx: uint16[3]` 第一版固定为 `(80,80,80)`；`voxel_size_xyz: float32[3]` 与完整图一致。
- `infered_box` 的 `materialization_role` 取 `clg_group_parent`、`f1_baseline` 或 `selected_final`。其它 box_type 为 null。
- 所有 `infered_box` 都必须有 `proposal_run_id`。`clg_group_parent` 必须有 `clg_id`；`f1_baseline/selected_final` 还必须有 `source_tree_id + source_node_id`。不适用的整数 ID 用 `-1`，不能省略后让消费方猜测。

坐标转换唯一规定为：BOX 局部索引 `[z,y,x]` 的中心世界坐标是：

```text
world_xyz = origin_xyz + voxel_size_xyz * [x, y, z]
```

完整图使用同一定义，所以：

```text
origin_xyz = full_grid_origin_xyz + voxel_size_xyz * [box_start_x, box_start_y, box_start_z]
```

### 3.2 occ_distances 与 in-box 判定（没有"主锚"）

- **`occ_distances`**：稀疏 `{cid: dist}`，`dist = ||box 中心 − centroid_atom_{cid}||`。BOX 几何中心使用 voxel 中心约定：`origin_xyz + voxel_size_xyz * ([W,H,D]-1)/2`。只记 **in-box** 的 occurrence。
- **in-box 判定 = `centroid_atom_{cid}` 落在 box 体积内**（用重原子中心，不用 mask 相交——保持口径最小、不过度扩展）。
- 用途：(1) 纯受体档 **距离-O** 的几何原料（`O_dist = 1[dist < ρ]`，ρ 训练期定、不烤进盘）；(2) 圈定该 box 的"相关 occurrence 范围"，给第 3 层覆盖与矩阵装配（§6）当列范围。

> **没有 `main_occurrence_id`、没有 `member_occurrences`**：覆盖矩阵的列是**图级全部 occurrence**（与 box 无关）；某 box 的 blob 对某 occurrence 的覆盖只由 `blob mask × occurrence GT mask` 决定，box 到 occurrence 的距离只由两个中心决定——**都不需要 box 级交叉记录**。框外的 occurrence 对本 box 隐式"远/零覆盖"，稀疏不记。

### 3.3 box_type 是开放枚举 + box_index 选择表

- `box_type` 是**开放字符串字段**。当前集合 = `{center, bias, context, infered_box}`（语义见 §9），**未来可加新类型**。
- 当前整图推理 BOX 名称固定为 **`infered_box`**；新契约不引入其它拼写或兼容别名。
- 全量描述子拼成一张 **`box_index`** 表（`pdb_id, box_type, box_id, box_start_zyx, origin_xyz, shape_zyx, materialization_role, proposal_run_id, clg_id, source_tree_id, source_node_id, addons, ...`）。
- **挑选 = 查表**：要“只挑 context”就 `filter(box_type=="context")`；要 blob 条件样本就选择拥有对应添油的 `infered_box`。按任意维度都能挑。
- **描述子层不分文件夹**；选择灵活性交给索引字段，不交给目录结构。
- **空间查询**：给定一个 3D 坐标或区域，通过 `box_start_zyx/shape_zyx` 或 `origin_xyz/voxel_size_xyz` 找到所有覆盖该位置的 BOX。

---

## §4 第 3 层：per-BOX 添油（只增不改）

"添油式可加性"：给定一个 BOX 身份，可在它上面**任意追加**额外特征；加不加都不一定，加了也不动老数据。

### 4.1 存储布局（治文件数）

规模估算：~5 occurrence/图 → ~30 BOX/图；几万 PDB → 几十万~上百万 BOX。**绝不每个 BOX 每种添油写一个小文件**（inode 爆、rsync 拖死）。布局：**按 PDB 聚成一个文件，与第 1 层对齐**。

```
addons/{addon_name}/{pdb_id}.npz      # 装该 PDB 所有 BOX 在该添油上的条目
  内部: (box_type, box_id) → 行 的映射；变长内容用 offset/ragged 存
```

- **加新特征 = 新建 `addons/{新名}/` 目录**，老添油一字节不动。
- 寻址用 **`(box_type, box_id)`**（§3.1）。

### 4.2 proposal run、CLG 与 Global Proposal

blob 只来自完整全图概率图。一个 `clg_group_parent` BOX 对应一个 **候选谱系组（Candidate Lineage Group, CLG）**，组内有 `N` 个 **Global Proposal Candidate**。候选 mask 永远指第一次全图组件森林中的节点；Group-parent 局部重跑只补特征和局部形状观察。

#### 4.2.1 proposal run manifest（per-PDB、per-run）

每次 Stage1 全图推理先保存一份不隶属于某个 BOX 的 manifest：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `schema_version` | scalar `uint16` | 本 proposal 产物的 schema 版本 |
| `proposal_run_id` | string | checkpoint、滑窗融合、阈值和 CLG 配置的联合稳定身份 |
| `pdb_id` | string | PDB 身份 |
| `stage1_checkpoint_sha256` | string | checkpoint 内容哈希 |
| `full_grid_shape_zyx` | `[3] int32` | 完整概率图形状 |
| `full_grid_origin_xyz` | `[3] float32` | 完整网格 voxel `[0,0,0]` 的中心世界坐标 |
| `voxel_size_xyz` | `[3] float32` | 完整网格 voxel size |
| `threshold_value` | `[T] float32` | 物理阈值，严格按高到低排列，`T<255` |
| `alpha_value` | `[A] float32` | calibration 使用的全部 alpha |
| `alpha_to_threshold_rank` | `[A] uint8` | 每个 alpha 对应的物理阈值位次；重复阈值可映射同一 rank |
| `connectivity` | scalar `uint8` | 固定为 26 |
| `proposal_config` | JSON | 体素上下界、空间 fit、split/merge 深度、CLG 上限等完整配置 |
| `component_tree_asset_ref` | string + hash | 原始组件森林审计表引用 |
| `probability_asset_ref` | string + hash 或 null | 可选完整概率缓存引用；读取 BOX 不依赖它 |

阈值 rank 的重建规则固定为：`threshold_value[0]` 最高；局部 `threshold_rank_map <= r` 恰好得到第 `r` 个阈值下的前景。

#### 4.2.2 CLG 候选表

设：

- `N`：本 CLG 可供 selector 评分的候选数；
- `N_seed`：原始种子与类种子姐妹数量。

每个 `clg_group_parent` BOX 保存：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `clg_id` | scalar `int32` | proposal run 内唯一 |
| `tree_id` | scalar `int32` | 所属组件树 |
| `group_parent_node_id` | scalar `int32` | CLG 唯一 Group-parent Node |
| `group_parent_candidate_row` | scalar `int16` | Group-parent 在候选表中的行号 |
| `candidate_node_id` | `[N] int32` | 每行对应的原始全图组件树节点 |
| `candidate_tree_parent_node_id` | `[N] int32` | 原始树直接父节点，可不在本 CLG 内；树根为 `-1` |
| `candidate_threshold_rank` | `[N] uint8` | Global Proposal 所在物理阈值位次 |
| `seed_candidate_row` | `[N_seed] int16` | 原种子和类种子姐妹的候选行号 |
| `lca_distance_from_i` | `[N,N] uint8` | 有序对 `(i,j)` 中，`i` 到两者 LCA 的边数 |
| `lca_distance_from_j` | `[N,N] uint8` | `j` 到同一 LCA 的边数 |

LCA 距离沿完整原始树计算，即使路径经过没有物化的不可选节点也要计数。由两张距离矩阵可推导祖先、子孙、姐妹、其它分支、阈值差和反链冲突，不重复保存关系枚举表。

`N` 只包含可供 selector 评分的候选。因体素上下界、触边或 80³ fit 失败而不可选择的节点留在组件树审计表中。

#### 4.2.3 Group-parent voxel 共享表

设 `K_v` 为 Group-parent Global Proposal Mask 的体素数，`L_v` 为所有候选 voxel 行索引拼接后的总长度：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `parent_voxel_index_local_zyx` | `[K_v,3] int16` | Group-parent Mask 的 BOX 局部体素索引；字典序排序、唯一 |
| `parent_voxel_global_probability` | `[K_v] float32` | 第一次全图概率在这些体素上的值 |
| `candidate_voxel_offset` | `[N+1] int64` | ragged offset |
| `candidate_voxel_row` | `[L_v] int32` | 每个 Global Proposal Mask 在父 voxel 表中的行号 |
| `threshold_rank_map` | `[80,80,80] uint8` | Group-parent 局部重跑的多阈值形状；255 表示所有阈值下均为背景 |
| `voxel_feat__{source_name}` | `[K_v,C_{v,s}] float16` | 局部重跑产生的已命名多尺度 voxel 特征 |

必须区分：

- `candidate_voxel_row` 是 Global Proposal Mask，决定 selector 标签、打分和 Stage2/3 默认 blob。
- `threshold_rank_map` 是 Group-parent 局部观察，只作输入信息，不产生新候选。

可确定性派生而不重复落盘的量包括：候选 voxel 数、局部/全图 mask、bbox、质心、`prompt_point`、全图概率 mean/max、`rank_at_parent_voxel`、候选 rank histogram 和局部体积变化曲线。

#### 4.2.4 F1 baseline

F1 居中基线使用同一 schema，`materialization_role=f1_baseline`，`clg_id=-1`，`N=1`；`proposal_run_id + source_tree_id + source_node_id` 唯一指向该 F1 Global Proposal Node。它不另造“基线 blob”字段。

### 4.3 Global Proposal × GT overlap（稀疏）

对 CLG 内每个 Global Proposal Candidate，计算它与同一 PDB 各 GT occurrence mask 的非零交集。所有量都以全图 Global Proposal Mask 为准，不使用局部重跑形状或 Refined Mask。

设 `E` 为非零 candidate-occurrence 记录数：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `candidate_occ_offset` | `[N+1] int64` | 每个候选的非零 GT 相交记录区间 |
| `overlap_occurrence_id` | `[E] int32` | GT occurrence 身份 |
| `overlap_intersection_voxels` | `[E] int32` | Global Proposal 与该 GT mask 的交集体素数 |
| `atom_coverage_offset` | `[E+1] int64` | 每条 candidate-occurrence 记录的原子覆盖区间 |
| `atom_coverage_value` | `[L_atom] bool` | 对齐对应 LigandObject 原子行；缺失原子固定为 false |

派生关系（不另存）：

- `α = inter_voxels / |g|`（recall，`|g|` 来自 `mask_{cid}`）
- `β = inter_voxels / |b|`（precision，`|b|` 由 `candidate_voxel_offset` 相邻差得到）
- `O_IoU = inter_voxels / (|b| + |g| − inter_voxels)`（密度档对称分类目标）
- `O_dist = 1[ dist(box 中心, centroid_atom_{cid}) < ρ ]`（纯受体档；由 §3.2 `occ_distances` 现推，不入此表）

由上述 overlap 与第 1 层 GT mask 体积还可派生 selector 软标签 `q_i=max_j IoU(GlobalProposal_i,GT_j)`、最佳 occurrence 与任意 `theta_valid` 下的硬标签。硬标签不落基础契约，因为 `theta_valid` 是训练配置。

**逐配体原子覆盖**（细分支 recall 辅助监督 of 标签）：

- **定义（生产方写一遍）**：`covered[a] = 1[ world_to_voxel(coords_{cid}[a]) ∈ GlobalProposalMask ]`，仅对 `present_{cid}[a]` 为真的原子有效，缺失原子恒 0。
- **用途**：`文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md §12` 的“逐配体原子覆盖辅助”标签；下游只保留指针，不重写定义。
- 该表既保持旧 Stage2 coverage/逐原子监督可追溯，也避免 selector 训练反复做大规模 voxel 集合求交。

### 4.4 Group-parent 的 P 与 receptor 共享表

Group-parent 局部重跑只保存一份 P token 表和一份 parent pocket receptor 表；候选通过 ragged 行索引取得自己的视图。

#### 4.4.1 P token 表

设 `N_P` 为 P token 数，`L_P` 为全部候选 P 行索引拼接长度：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `p_pos_box_xyz` | `[N_P,3] float32` | 相对 BOX 原点的 Å 坐标 |
| `p_probability` | `[N_P] float32` | 已冻结语义的 P-head ligand-area 概率 |
| `p_feat__{source_name}` | `[N_P,C_{P,s}] float16` | 已命名多尺度 P 特征 |
| `candidate_p_offset` | `[N+1] int64` | ragged offset |
| `candidate_p_row` | `[L_P] int32` | 每个 Global Proposal 对应的 P 行索引 |
| `p_membership_rule_id` | string | 回指确定性的候选—P 空间归属规则及参数 |

P probability 必须在 feature manifest 中说明来自哪个 head，不能保留“base 或 P head 待猜”的语义。

#### 4.4.2 Group-parent pocket receptor 表

设 `R` 为 parent pocket 原子数，`L_R` 为全部候选 receptor 行索引拼接长度：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `receptor_atom_global_index` | `[R] int32` | 在第 1 层完整 receptor table 中的行号 |
| `receptor_binding_probability` | `[R] float32` | Group-parent 局部重跑的受体 binding 概率 |
| `receptor_feat__{source_name}` | `[R,C_{R,s}] float16` | 已命名多尺度 receptor 特征 |
| `candidate_receptor_offset` | `[N+1] int64` | ragged offset |
| `candidate_receptor_row` | `[L_R] int32` | 各候选自己的 pocket 原子在 parent 表中的行号 |
| `pocket_radius_angstrom` | scalar `float32` | 本产物实际使用的包络半径 |

受体坐标、49 维特征、元素/残基和键表由 `receptor_atom_global_index` 回到第 1 层获取，不重复保存。空 P 或空 receptor 子集由相邻 offset 相等表示；不在磁盘写伪 token。

#### 4.4.3 feature-source manifest

所有 `voxel_feat__*`、`p_feat__*`、`receptor_feat__*` 都必须有来源清单：

| 字段 | 说明 |
|---|---|
| `source_name` | 稳定字段名，例如 `voxel_feat__decoder_pre_head` |
| `entity` | `voxel`、`p_token` 或 `receptor_atom` |
| `producer_module` | 精确到模块出口的来源 |
| `checkpoint_sha256` | 生产 checkpoint |
| `channel_dim` | 通道数 |
| `storage_dtype` | 实际存储 dtype，第一版通常 float16 |
| `coordinate_frame` | 空间实体使用的坐标帧 |
| `semantic_description` | 特征含义，不用“第几层”代替 |

Stage2/3 的 `FuseSources` 从这些稳定来源装配输入。旧的 `P_feat_L*` / `receptor_feat_L*` 只能通过显式迁移映射读取，不能在新 schema 中继续作为含义不明的正式字段。

### 4.5 可选密度 U-Net 特征

Stage1 selector、Stage2 和 Stage3 可以共用一个可关闭的轻量密度 U-Net。原始 exp 密度仍从第 1 层按 BOX 描述子裁剪，不重复存储。该模块有两种运行方式：

1. **模型内现算**：只保存 U-Net checkpoint 与输入归一化 manifest，不增加第 3 层大数组。
2. **冻结后缓存**：把输出作为新的 feature source，沿 §4.2 voxel 表或 §4.4 P/receptor 共享表对齐保存。

现有预训练化学特征 U-Net 可以实现同一接口。若复用，它的输出字段命名为例如 `voxel_feat__chem_unet_*`；若另训更轻的密度上下文 U-Net，使用不同 `source_name`、checkpoint hash 和 addon 目录。不得只用同名 `blob_voxel_feat` 覆盖旧产物。

缓存 voxel 特征时不再重复保存一份 `blob_voxel_index`；它直接与 `parent_voxel_index_local_zyx` 的行对齐。点对象调制特征若缓存，则与 `p_pos_box_xyz` 或 `receptor_atom_global_index` 的共享表行对齐。

### 4.6 口袋视图

Stage2/3 是否使用预测候选或 GT 输入由运行配置决定，不增加“GT probe”样本身份。

| 口袋类型 | 定义 | 存储 |
|---|---|---|
| **GT ligand atom envelope** | 对所选 GT occurrence 的 present ligand atoms 分别做半径查询，再合并受体原子索引；不保留中心球备选 | Dataset 现场算；每个 worker 缓存 per-PDB receptor `cKDTree` |
| **Group-parent pocket** | 对 Group-parent Global Proposal Mask 的包络选受体原子 | §4.4 parent receptor 共享表 |
| **Candidate pocket** | 对某个 Global Proposal Mask 用同一半径选受体原子 | `candidate_receptor_offset/row`，是 parent pocket 的子集 |
| **Selected-final pocket** | 对可选 Refined Mask 或 final proposal 投影定义 | selected-final 自己的独立完整 receptor 表 |

旧的 `pocket_atom_index` 可由：

```text
receptor_atom_global_index[candidate_receptor_row]
```

直接得到。`n_pocket_atoms`、Rg、残基直方图、Wiener index 和 graph energy 均可由候选 receptor 行索引与第 1 层 receptor 表确定性派生，第一版不物化这些化学/碎片描述子，以减少契约复杂度。

### 4.7 selector score 与 selection result

基础 proposal 数据不能被某次网络推理或某组 calibration 参数覆盖。两类结果分别追加。

#### 4.7.1 selector score addon

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `selector_run_id` | string | checkpoint、模型配置和输入 feature manifest 的联合身份 |
| `proposal_run_id` | string | 回指基础 proposal |
| `clg_id` | scalar `int32` | CLG |
| `candidate_node_id` | `[N] int32` | 与基础候选表 join |
| `predicted_max_iou` | `[N] float32` | 反链目标唯一使用的 `q_hat` |
| `valid_logit` | `[N] float32` | 仅作辅助监督和诊断 |

#### 4.7.2 selection addon

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `selection_run_id` | string | 一组唯一选择配置 |
| `selector_run_id` | string | 使用哪次候选打分 |
| `clg_id` | scalar `int32` | CLG |
| `b_over_a` | scalar `float32` | 固定 `a=1` 后的均值项系数 |
| `lambda_over_a` | scalar `float32` | 候选数惩罚 |
| `selected_candidate_row` | `[N_selected] int16` | 最优可行反链；允许长度为 0 |
| `selection_objective` | scalar `float32` | 该反链的目标值 |

改变 `b,lambda` 只写新的 selection addon，不重跑 selector，也不改基础 candidate 表。

### 4.8 可选 selected-final refinement

每个被精修候选建立独立 `infered_box`，并设置 `materialization_role=selected_final`：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `selection_run_id` | string | 哪次选择产生它 |
| `source_clg_id` | scalar `int32` | 来源 CLG |
| `source_group_parent_box_id` | scalar `int32` | 来源 Group-parent BOX |
| `source_candidate_node_id` | scalar `int32` | 被选中的全图树节点 |
| `source_threshold_rank` | scalar `uint8` | 精修固定使用的原阈值 |
| `final_voxel_index_local_zyx` | `[K_f,3] int16` | proposal 投影与 refined mask 坐标的并集表 |
| `proposal_voxel_row` | `[K_p] int32` | Global Proposal 投影进 final BOX 后的行索引 |
| `refined_voxel_row` | `[K_r] int32` | 固定阈值局部重跑选出的 refined component |
| `proposal_voxels_total` | scalar `int32` | 原 Global Proposal 总体素数 |
| `proposal_voxels_in_box` | scalar `int32` | 进入 final BOX 的体素数 |
| `refine_status` | enum string | `success`、`empty`、`no_overlap_component` 等显式终态 |
| `threshold_rank_map` | `[80,80,80] uint8` | final 居中重跑的完整局部多阈值观察 |

Selected-final BOX 还保存自己的 voxel/P/receptor 特征表，不与 Group-parent 特征混用。`proposal_was_clipped`、proposal/refined IoU、prompt 和 refined pocket都可派生。精修失败不得静默覆盖原 Global Proposal；下游显式决定是否回退。

### 4.9 旧字段追溯

| 旧字段 | 新契约中的来源 |
|---|---|
| `blob_mask` | `parent_voxel_index_local_zyx[candidate_voxel_row]`，默认指 Global Proposal Mask |
| `blob_voxels` | `candidate_voxel_offset` 相邻差 |
| `prompt_point` | Global Proposal 体素质心转换到世界坐标 |
| `scores` | Global Proposal 统计 + 指定 `selector_run_id` 的 score addon |
| `provenance` | proposal、materialization、selector、selection、refinement manifests |
| `coverage/atom_coverage` | §4.3 overlap ragged 表 |
| `blob_voxel_index` | 候选行查询 parent voxel 表 |
| `blob_voxel_prob` | `parent_voxel_global_probability[candidate_voxel_row]` |
| `blob_voxel_feat` | `voxel_feat__{source}[candidate_voxel_row]` |
| `P_pos/P_prob/P_feat_*` | Group-parent P 共享表；候选视图由 `candidate_p_row` 取得 |
| `receptor_atom_index` | Group-parent receptor 表；候选视图由 `candidate_receptor_row` 取得 |
| `receptor_binding_prob/receptor_feat_*` | 同上 |
| `pocket_atom_index` | `receptor_atom_global_index[candidate_receptor_row]` |
| chemical U-Net voxel feature | 一个命名化 `voxel_feat__{source_name}` |
| refined blob | 仅来自 selected-final 的 `refined_voxel_row`，不覆盖 Global Proposal |

---

## §5 第 4 层：现场算 + 两条不变量

### 5.1 现场算

- **56 维辅助密度通道**：dataset `__getitem__` 里从第 1 层 exp/sim 在线算（`density_channel_builder`，`{op}_{norm}_{post}` 命名）。
- **`diff`**：`exp − sim` 现场算。
- **O-distance**：box 中心 + `centroid_atom` 现推。
- **GT ligand atom envelope 口袋**：Stage2/3 Dataset 现场通过每-worker per-PDB receptor `cKDTree` 计算（§4.6）。
- **覆盖矩阵装配**：见 §6。

### 5.2 不变量 A：身份冻结 + materialize 时扰动

- **BOX 身份冻结**：`box_start_zyx/origin_xyz/shape_zyx/occ_distances` 等枚举或物化时定死、落盘。
- `box_index` 的每一行都是独立 BOX 身份；不按原点、覆盖区域或体素内容去重。训练 sampler 用简单权重/比例开关混采 center/bias/context，某类权重为 0 即关闭。
- 模型读取两种姿势：**原样读**（Stage2/3）按描述子直接切片；**先扰动再读**（仅 Stage1 基础训练）在 materialize 时对临时裁剪原点加 jitter / 体素增广再切第 1 层得标签——增广下沉到 materialize 层，不回写 BOX 身份。

### 5.3 不变量 B：扰动 ⟺ 放弃第 3 层

第 3 层 blob/coverage 只为整图推理建立的 `infered_box` 身份缓存。Stage1 的 center/bias/context 增广路径只用第 1、2 层；Stage2/3 是否读取预测 blob 添油由运行配置决定，无预测 blob 时可改用 §4.6 的 GT ligand atom envelope 现场视图。

---

## §6 覆盖矩阵装配（featurizer 职责，非落盘）

```text
对一张图 P：
  selector 训练行 = 收集 P 的所有 CLG Global Proposal Candidate
  Stage2/3 正式行 = 按 selection_run_id 收集各 CLG 的 selected_candidate_row
  列 = P 的全部 occurrence（候选身份 × count 展开成 slot；图级，与 box 无关）
  entry(候选 i, occurrence j):
     读 candidate_occ_offset / overlap 表
     → 命中 j 取其 α/β/O_IoU；未命中 = 0
  → [n_blobs, n_slots] 网格
```

> off-diagonal（merge、负样本）天然可算：只需 `blob_i` 与 `occurrence_j` 各自的量（mask 或中心），**不需要任何 box 级交叉记录**。
>
> 无预测 blob 的 Stage2/3 试水不装配本矩阵；它使用哪些 GT-envelope 输入与监督由运行配置决定，不通过新增样本身份或伪造 blob 来复用本矩阵。selected-final refinement 不改变这张矩阵的行身份；若下游专门评估 Refined Mask，应另算诊断量。

---

## §7 三档与可拆卸

三档 = **同一批 BOX 的不同清单切片**，由 dataset 配方决定激活哪些块；**不是切出了不同的产物**。

| 档 | Stage1 输入 | Stage2/3 激活的块 | 口袋/空间锚 | 备注 |
|---|---|---|---|---|
| **纯密度档** | 只有密度 | 第 1 层 density（+56 通道）、第 2 层；有预测 blob 时再激活第 3 层 blob/coverage/Stage1 PP 特征 | 由配置选择预测 blob 或 GT ligand atom envelope | 前置：Stage1 也只吃密度 |
| **统一档** | 密度 + 受体 | 上面全部 + 49 维受体特征 + A 侧特征 + 受体几何 | 由配置选择预测 blob 或 GT ligand atom envelope | 最强模型 |
| **"纯受体"档** | **密度 + 受体** | 49 维受体特征 + A 侧特征 + 受体几何；关 PP 特征、关 56 通道密度 | 早期试水可现场用 GT ligand atom envelope；后期消融可用预测 blob | Stage2/3 只消费受体侧 |

可拆卸 = 丢掉 PP 特征退回纯受体、丢掉受体块退回纯密度，**消融和换档是同一个开关**。输入来源和监督同样由配置开关决定；不为“GT envelope / predicted blob”增加样本级身份机制。

### 7.1 两条红线

1. **三档不另立 BOX 来源**：纯受体档**不能**为了“免费拿到位点+口袋”去单切一种 `site+pocket box`。三档都跑在现有 box_type 上，口袋只是由配置选择 Global Proposal 包络或 GT ligand atom envelope 后得到的受体切片视图（§8.1），不是新 box_type。
2. **box_type 可扩展 ≠ 三档后门**：§3.3 的开放性是为别的真实用途留的；**不得**用新 box_type 绕过三档可拆卸性。

---

## §8 四模型对接（docking）

| 模型 | 读什么 | 怎么对接 |
|---|---|---|
| **Stage1 基础 Find** | 第 1 层切片（密度 + 标签）；可 materialize 扰动 | Dataset 按比例迭代 center/bias/context，监督直接切全局 mask/原子标签；三类只表示原点来源 |
| **Stage1 selector** | 一个 CLG 的 Group-parent voxel/P/receptor 共享表、Global Proposal membership、rank map 派生量和树关系 | 一个 CLG 是一个样本；预测每个 Global Proposal 的最大 GT IoU，反链结果写 selection addon |
| **Stage2（Match）** | 现场 GT envelope，或 selected Global Proposal + Group-parent 共享特征/coverage | 默认不依赖 selected-final；同 PDB 已选候选为行、图级 occurrence 为列。可选读取 Refined Mask 或密度 U-Net 调制特征 |
| **Stage3（Build）** | GT envelope 试水输入，或 selected Global Proposal 的 prompt、Group-parent 特征与受体块 | 默认可直接使用 Global Proposal；selected-final 是独立形状精修输入，不是前置条件 |
| **轻量密度 U-Net** | 第 1 层原始 exp 密度 | 可模型内现算，或冻结后作为命名 feature source 缓存；selector/Stage2/Stage3 共享接口 |

**无预测 blob 训练的特殊性**：输入与监督由配置决定，GT pocket 统一由 ligand atom envelope 现场生成；它不伪造 blob，也不为样本增加额外模式身份。blob coverage、距离或其它监督是否启用，均属于训练配方，不烤进存储。

### 8.1 口袋 = 以 Global Proposal 为锚的视图（Stage2/3）

有预测候选时，Stage2/3 的“位点周围口袋”默认以 selected Global Proposal Mask 的包络为锚，读取它在 Group-parent receptor 共享表中的行索引。无预测 blob 的早期试水由配置改用 GT occurrence 的 ligand atom envelope；不保留中心球备选。若显式启用 selected-final，消费方可以改用 Refined Mask 自己的独立 pocket。

> 与 Stage1 的区别：Stage1 用 box+buffer（box 为锚，它还不知配体在哪）；Stage2/3 按配置使用 blob 包络或 GT ligand atom envelope。GT envelope 由每-worker 缓存的 per-PDB receptor `cKDTree` 现场计算。

---

## §9 BOX 家族枚举

### 9.1 当前四类（可扩展）

| box_type | 来源 | in-box occurrence | 备注 |
|---|---|---|---|
| **center** | 以 occurrence `centroid_voxel` 严格居中切 80³ | 该 occurrence（+ 落在框内的邻居） | 只表示原点来源；不携带正负语义，不运行逐 BOX Stage1 推理 |
| **bias** | 在 center 上按配方偏移，每 instance 多个 | 同上 | 只表示偏移采样来源；偏移配方见 §9.2；不拥有 blob 添油 |
| **context** | **只按受体原子比率 > 阈值**的随机裁剪 | 由实际裁剪内容决定 | 只表示 context 原点来源；不拥有 blob 添油，也不需要 clean/正负旗标 |
| **infered_box** | 全图概率组件森林及其局部物化产生 | 由 Global Proposal overlap/距离事后给出 | blob 的唯一 BOX 来源；用 `materialization_role` 区分 `clg_group_parent`、`f1_baseline`、`selected_final` |

- **冻结枚举**：center/bias/context 的原点在枚举时定死、落第 2 层；每条记录独立存在，不按原点或体素内容去重。
- **来源比例开关**：Stage1 训练 sampler 用简单权重/比例控制 center/bias/context 的输入占比，权重为 0 即关闭；`box_type` 不进入 loss，监督来自现场裁剪的真实字段。
- **加新 box_type = 加一个枚举器**，不改 schema、不动存储布局。
- **不为 CLG 角色加 box_type**：Group-parent、F1 baseline 和 selected-final 是同一 `infered_box` 家族中的物化角色。

### 9.2 bias 偏移配方（提前切、冻结）

```text
1. 采样概率场 = 高斯衰减(从 GT ligand-area 中心) ∩ ligand-area（区域外为 0）
2. 在该场里采一点，取其相对中心的位移 d
3. 偏移 = 比例 × d + floor
   - 比例项随配体尺寸自适应（支撑集就是配体区域，截断保证偏移点落在配体内）
   - floor ~ 某【全局】固定分布的随机量（保证小配体也有非平凡偏移；不再对配体自适应——采样场已适应过一次）
4. clamp 保证配体仍在 box 内
```

> 比例、floor 分布、阈值的具体数值待标定（可对着 Find 实际定心误差校准）。

---

## §10 与 featurizer / 模型输入契约的接缝

三层逻辑必须分开（"算子与数据输入分离"）：

1. **盘上数据契约**（本文）：BOX 存按来源分开的块。
2. **模型输入契约 / featurizer**（见 `文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md §4`）：按“某模型 + 某档”的配方，把块拼成模型张量视图（含 §6 矩阵装配）。
3. **模型算子**（见同一迭代运算文档）：只看拼好的张量，不知盘上长什么样。

**继承的原则与可复用叶子**（代码可重写、原则/叶子保留）：

- **原则**：训练侧与推理侧严格共用同一个 Dataset `__getitem__` 处理路径、BOX→样本 builder 与 collate，靠同一条实际调用链强制两边契约一致。差别只在 BOX 原点来源和 sampler：训练读取 center/bias/context 的 `box_index`；整图推理按 map shape、window size、stride 和样本索引公式产生窗口原点。
- **可直接当库用的纯叶子**（与配体种类零耦合）：`box_geometry`（选框内+buffer 原子、三套坐标、hardmask、按索引切特征）、`density_channel_builder`（在线 56 通道）。
- **要重写的耦合层**：旧 `box_point_dataset` 按配体种类分文件夹/分 split/平衡采样那一套——推倒，改成按 §3 描述子 + `box_index` 组织；推理不得预先构造完整 `box_dicts` 列表。
- **流水线职责**：DataLoader worker 负责整图读取、BOX 裁剪和 56 通道构造；概率 BOX 合并与完整图后处理使用独立可配置 worker/有界队列，以便与 GPU forward 或下一张图的处理重叠。不得让多个进程无协调地写同一张概率 accumulator。
- **非依赖项**：`pin_memory` 默认不启用，不作为 CPU/GPU 重叠成立的前提；固定形状 BOX 不增加 `voxel_valid_mask` 字段；少量 voxel size 非严格等方的样本不因旋转增强增加硬门禁或抛异常。

### 10.1 冷读验证不变量

每个正式产物必须通过以下检查：

- `proposal_run_id` 能唯一解析 proposal manifest、组件树引用和阈值表。
- `box_start_zyx >= 0` 且 `box_start_zyx + shape_zyx <= full_grid_shape_zyx`；`origin_xyz` 与 voxel-center 坐标公式一致，不允许依赖 padding 或 clamp。
- 一个 CLG 只有一个 `group_parent_candidate_row`，且该行 `candidate_node_id` 等于 `group_parent_node_id`。
- 所有 candidate voxel/P/receptor row 均在共享表范围内，同一候选内部不重复。
- 每个候选 Global Proposal Mask 都是 Group-parent Mask 的子集。
- `threshold_rank_map` 的值只属于 `0..T-1` 或 255。
- `lca_distance_from_i/j` 与原始组件树一致，且能正确恢复反链冲突。
- selector score、selection 与 refinement 都通过稳定 ID 回指相同的 Global Proposal Node。
- selected-final 缺失时，Group-parent materialization + Global Proposal + selection addon 已足够构造 Stage2/3 输入。
- 旧字段追溯表中的每一项都能在不读取历史文件的情况下还原。

---

## §11 待定与维护

**待定（实现时定）**：

1. 第 3 层 ragged 逻辑字段已经固定为 offset + row-index；物理容器选 NPZ 分片、Zarr 或其它格式仍待 IO benchmark。
2. `box_index` 的物理形式（单张 parquet/jsonl vs 按 PDB 分片再聚合）。
3. bias 的比例与 floor 分布、context 受体比率阈值、距离-O 的 `ρ`、IoU-O 的 `τ`、覆盖条目入选阈值——先看分布再定。
4. ~~`centroid_atom` 是否物化~~ **已定物化进 `ligand_coords.npz`**（C4 产，§2.2）。
5. `voxel/P/receptor` feature-source 的最终字段全集、源码出口、通道数与 storage dtype。
6. `infered_box` 是否回填某种 occurrence 锚（默认不填，靠覆盖/距离）。
7. pocket 半径与候选—P membership 规则的最终数值；规则 ID 与实际参数必须进入 manifest。
8. 轻量密度 U-Net 采用现算还是冻结缓存，由 profiling 与下游实验决定；两种方式共享 feature-source 接口。

**维护**：实现后用真实产物验证字段、dtype、shape 和不变量；发现漂移先按 `AGENTS.md` 审计并请求用户决定，再更新本文、正式 Stage1 计划、mapping 与下游指针。本文仍是 BOX 级盘上契约的唯一权威，事实只写一遍。
