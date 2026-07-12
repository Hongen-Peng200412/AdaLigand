# AdaLigand BOX 级数据契约

> **本文定位**：AdaLigand 把"从冷冻电镜密度图里找配体并建模"拆成多个模型训练（Stage1 Find / Stage2 Match / Stage3 Build / 预训练化学 UNet）。这些模型的训练样本统一是 **BOX 形式**。本文是「整图级产物 → 每个模型可直接训练的 BOX 级样本」之间那段**数据契约**的唯一权威：一个 BOX 到底存哪些东西、按什么来源拆分、怎么落盘、怎么挑选、怎么添油、各模型怎么对接。
>
> **上下游**：
> - **上游** = `规划文档/数据处理_v2.md`，它产出**整图级 / occurrence 级**产物（受体 token、LigandObject、per-occurrence GT 坐标与两套中心、原子标签、exp/sim/ligand_area 密度网格、质量/过滤），**到此为止，不切 BOX**。本文从这里接手。
> - **下游** = `模型总规划_v2.md`（Stage2 预测什么/损失）、`Stage2_Stage3_迭代运算设计_讨论.md`（怎么算/算子）。它们消费本文定义的 BOX 块；数据怎么存只在本文写一遍，那两份只留指针。
> - **产物来源** = `Stage1_Find_接缝与推理重写.md`：第 3 层 blob / 两个概率 / UNet 特征的**产法与语义**（二阶段推理、打分、二次筛选）归它；本文只管这些量**怎么存**（同一个 blob，产法写在 Stage1、存储写在本文）。
>
> **边界**：本文只管"**盘上长什么样**"。"块怎么拼成模型张量"是 featurizer 的事（见 `迭代运算 §4`），"模型拿这些预测什么"是模型文档的事。本文不重复运算与监督细节。
>
> **权威层级**：实际代码 > Hydra 配置 / checkpoint > 真实 `.npz`/`.json` 产物与日志 > 本文。字段/布局以实现为准；给出的 schema 是可照着实现的规范，不把 dtype 钉死。

---

## §0 一句话总览

> 一个 BOX 不是一坨打包好的张量，而是**一个轻量身份 + 若干按来源分开、可拆卸、可添油的块**。重的东西**整图级存一次**，BOX 只是切片入口；模型在运行时拿一份**清单（配方）**，按需读到它要的块。换来源、换档位、加特征，都不动模型，也不重写老数据。
>
> **统一锚（贯穿全文）**：所有 box（center/bias/context/infered_box）对 blob 与 occurrence 的态度**完全一致**。每个 box 至多对应**一个 blob**，充当覆盖矩阵的一行；覆盖矩阵的**列是整张图的全部 occurrence**（Stage2 的输入：候选身份 × count）。box **不记"主锚"**，只记两件事——**枚举时**它到各 in-box occurrence 的几何距离、**推理后**它那一个 blob 对各 in-box occurrence 的覆盖。α/β/O 全由这两样 + 整图级 GT **现场派生**。

---

## §1 四层存储模型（核心）

数据分四层，各层的生命周期、粒度、可变性都不同。这是整个契约的骨架。

| 层 | 名称 | 粒度 | 何时产生 | 可变性 | 装什么 |
|---|---|---|---|---|---|
| **1** | 整图级落盘 | per-PDB | 数据处理阶段（慢、贵） | 固定 | exp/sim 密度、49 维受体特征、ligand_area mask + 两套质心、binding/instance 原子标签、LigandObject、per-occurrence GT 坐标 |
| **2** | BOX 描述子 | per-BOX（极小） | 枚举 BOX 时 | 冻结 | `pdb_id, box_type, box_id, origin, shape_zyx, voxel_size, source/provenance, occ_distances(稀疏)` |
| **3** | per-BOX 添油 | per-BOX，按 `(box_type, box_id)` keyed | Stage1 推理后 / 任意时刻 | **只增不改** | blob（mask + `scores` 套打分 + 对各 in-box occurrence 的覆盖 + 逐配体原子覆盖 + provenance）、ligand-area 内 UNet 特征 + 概率、逐受体原子 binding 概率（受体上下文）、其余落盘特征与未来任意派生特征等等 |
| **4** | 现场算 | per-BOX，运行时 | dataset `__getitem__` | 瞬时 | 56 维辅助密度通道、diff、O-distance、覆盖矩阵装配、materialize 扰动 |

**为什么这么分**：

- 慢且固定的东西（第 1 层）**整图算一次、切片复用**，避免把同一份密度拷进上百万个 BOX 文件。
- BOX 身份（第 2 层）小、冻结，是一切的索引锚。
- 只有 Stage1 跑完才存在、且 per-BOX 不可共享的东西（第 3 层 blob）单独添油，**加它不重写 BOX**。
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
  "origin": [x, y, z],               // 世界坐标 Å
  "shape_zyx": [80, 80, 80],
  "voxel_size": [1.0, 1.0, 1.0],
  "provenance": "...",               // bias 实际偏移向量 / context 随机种子 / infered_box 来自哪次全图推理 + 阈值
  "occ_distances": [                  // 稀疏：到各 in-box occurrence 的距离，见 §3.2
    {"cid": 3, "dist": 1.2},
    {"cid": 5, "dist": 31.7}
  ],
  "addons": ["stage1_blob", "..."]   // 本 box 现有哪些第 3 层添油
}
```

- **`box_id` 在 `(pdb_id, box_type)` 内唯一**：每个 box_type 的枚举器各自从 0 起编号，互不协调；寻址用 `(box_type, box_id)`（第 3 层添油同此 key，§4.1）。

### 3.2 occ_distances 与 in-box 判定（没有"主锚"）

- **`occ_distances`**：稀疏 `{cid: dist}`，`dist = ||box 中心 − centroid_atom_{cid}||`（box 中心 = origin + shape/2）。只记 **in-box** 的 occurrence。
- **in-box 判定 = `centroid_atom_{cid}` 落在 box 体积内**（用重原子中心，不用 mask 相交——保持口径最小、不过度扩展）。
- 用途：(1) 纯受体档 **距离-O** 的几何原料（`O_dist = 1[dist < ρ]`，ρ 训练期定、不烤进盘）；(2) 圈定该 box 的"相关 occurrence 范围"，给第 3 层覆盖与矩阵装配（§6）当列范围。

> **没有 `main_occurrence_id`、没有 `member_occurrences`**：覆盖矩阵的列是**图级全部 occurrence**（与 box 无关）；某 box 的 blob 对某 occurrence 的覆盖只由 `blob mask × occurrence GT mask` 决定，box 到 occurrence 的距离只由两个中心决定——**都不需要 box 级交叉记录**。框外的 occurrence 对本 box 隐式"远/零覆盖"，稀疏不记。

### 3.3 box_type 是开放枚举 + box_index 选择表

- `box_type` 是**开放字符串字段**。当前集合 = `{center, bias, context, infered_box}`（语义见 §9），**未来可加新类型**。
- 全量描述子拼成一张 **`box_index`** 表（`pdb_id, box_type, box_id, origin, shape, addons, ...`）。
- **挑选 = 查表**：要"只挑 context"就 `filter(box_type=="context")`；要"只挑有 blob 添油的 bias"就再叠条件。按任意维度都能挑。
- **描述子层不分文件夹**；选择灵活性交给索引字段，不交给目录结构。
- **空间查询**：给定一个 3D 坐标或区域，通过 origin/shape 找到所有覆盖该位置的 BOX（filter/match by `origin/shape` + BOX 身份）。

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

### 4.2 blob（Stage1 推理产出，喂 Stage2 的关键料）

**每个 box 至多一个 blob**，充当覆盖矩阵的一行。**产法与语义归 `Stage1_Find_接缝与推理重写.md`**，本节只管存储：

- **box 级推理（冻结 box）**：一个冻结 box（center/bias/context）跑 Stage1，可能出多个 blob → 取 **mask 体素中心离 box 中心最近**的那一个，其余忽略（邻近 occurrence 由它们自己的 box 负责）。
- **全图划窗推理（infered_box，两阶段）**：pass-1 全图滑窗定位 blob → pass-2 以每个 blob 中心重裁 box 再推一遍 → **落盘 pass-2（近似中心化）的 blob**（详见 `Stage1 §3.2`、本文 §9.1）。天生一框一 blob，不涉挑选。
- **不删、过量保存**：两个 pass 后**只存不删**，比"最优 F1 截取数目"存更多，只用很松的 recall-first 下限丢明显垃圾；每 blob 附 `scores`（下）。**"用哪些 blob"是消费侧的事**（`迭代运算 §4` featurizer 选择旋钮），不在存储层决定——这是"怎么存 / 用哪些"两个独立问题的落地。
- **没有 blob 的 box 不进训练**（直接丢，不留空行）。

字段：

| 字段 | 形式 | 说明 |
|---|---|---|
| `blob_mask` | ragged 体素 mask（COO/offset） | pass-2 产的 blob 体素集；**不在存储层硬过滤/删除**，保留供下游按 `scores` 自选 |
| `blob_voxels` | int | `|b|`，供覆盖派生 |
| `prompt_point` | `[3] float` | blob 的 ligand-area 体素质心 → 交 Stage3 |
| `scores` | dict `{name: float}`（**可扩展命名集，只增不改**） | **套打分**：老的粗预测置信分（必存，老代码用来排序、被"最优 F1"切的那个）+ "最优 F1 截取参考值" + 将来迷你网分数**并列**。每个打分器产一个条目，下游 featurizer 按名选阈截取（`Stage1 §4`） |
| `provenance` | dict | Stage1 checkpoint、阈值、pass-1/pass-2 参数 |

### 4.3 coverage + 逐配体原子覆盖（稀疏，落 blob 时顺手算）

落 blob 的同时，算这个 blob 对**各 occurrence** 的覆盖，**稀疏落盘**（只存有交的条目；有任何原子在 BOX 内即算 in-box，无交集的 coverage=0 省略不存）：

```
coverage = [ {cid, inter_voxels}, ... ]   # inter_voxels = |blob ∩ occurrence GT mask|
```

派生关系（不另存）：

- `α = inter_voxels / |g|`（recall，`|g|` 来自 `mask_{cid}`）
- `β = inter_voxels / |b|`（precision，`|b| = blob_voxels`）
- `O_IoU = inter_voxels / (|b| + |g| − inter_voxels)`（密度档对称分类目标）
- `O_dist = 1[ dist(box 中心, centroid_atom_{cid}) < ρ ]`（纯受体档；由 §3.2 `occ_distances` 现推，不入此表）

> 离线一次性算（blob 出生时），稀疏存（一个 blob 通常压 1 条，merge 时 2+ 条）。这是 Stage2 覆盖监督的数据根。

**逐配体原子覆盖**（细分支 recall 辅助监督 of 标签）：

落 blob 时同时算它对各 occurrence 的**逐配体原子覆盖**——即该 occurrence 每个 present 重原子的体素是否落在 blob mask 内，**稀疏落盘**（只存有交 occurrence 的条目）：

```
atom_coverage = [ {cid, covered}, ... ]   # covered: 长度 = 该 occurrence LigandObject 原子数的 bool，行序对齐 present
```

- **定义（生产方写一遍）**：`covered[a] = 1[ world_to_voxel(coords_{cid}[a]) ∈ blob_mask ]`，仅对 `present_{cid}[a]` 为真的原子有效，缺失原子恒 0。
- **用途**：`迭代运算 §12（监督全清单）` 的"逐配体原子覆盖辅助"（挂 `fine_probe_recall`）的标签；§12 只留指针指到本节，不重写定义。
- 依赖 blob（第 3 层），随 `coverage` 一起在 blob 出生时算；无 blob 的 box 不进训练、自然无此条目。

### 4.4 Stage1 per-box 多尺度中间产出 → `addons/stage1_feat/{pdb_id}.npz`

Stage1（Pocket_Plus）对每个 BOX 产出 4 个层级的多尺度特征（PP 侧 = 体素特征，A 侧 = 受体原子特征），供 Stage2/3 表示前导的 `FuseSources` 多源融合作为 conditioning 使用。产法与语义归 `Stage1_Find_接缝与推理重写.md`，本节只管存储。

| key | 形式 | 说明 |
|---|---|---|
| `ligand_voxel_index` | `[K, 3] int` | 预测 ligand-area 内体素索引（K 可变、完整不截断） |
| `ligand_voxel_prob` | `[K] float` | Stage1 逐体素 `ligand_area` 概率；PP 采样按它 top-k，且作 PP 节点输入特征（= 模型侧 `density_point_ligand_area_probability`） |
| `ligand_voxel_feat_L2` | `[K, C] float` | PP 侧 L2：UNet 中间层特征 |
| `ligand_voxel_feat_L3` | `[K, C] float` | PP 侧 L3：cross-attn 前特征 |
| `ligand_voxel_feat_L4` | `[K, C] float` | PP 侧 L4：cross-attn 后特征 |
| `receptor_atom_index` | `[R] int32` | 本 box 口袋受体原子的**全局索引**（切回第 1 层受体几何 / 49 维特征） |
| `receptor_binding_prob` | `[R] float` | Stage1 逐受体原子 binding 概率 |
| `receptor_feat_L1` | `[R, C] float` | A 侧 L1：embed head 后 |
| `receptor_feat_L2` | `[R, C] float` | A 侧 L2：density box 特征 |
| `receptor_feat_L3` | `[R, C] float` | A 侧 L3：cross-attn 前 |
| `receptor_feat_L4` | `[R, C] float` | A 侧 L4：cross-attn 后 |

- **多尺度 conditioning 对接**（与 `迭代运算 §4` 表示前导）：
  - **A 的 `FuseSources`**：main = 49 维手工特征（第 1 层）；aux_sources = L1–L4 的 receptor 侧特征
  - **PP 的 `FuseSources`**：main = 化学 UNet 特征（§4.5）⊕ Stage1 UNet voxel 特征 拼接；aux_sources = L2–L4 的 ligand 侧特征（L1 不含 PP）
- **口袋以 blob 为锚**（§8.2）；空间分布由 `receptor_atom_index → 第 1 层 coords` 现推，不重复落坐标。
- PP 采样运行时从 `ligand_voxel_prob` top-k（加 min 兜住太小的 blob）；**灌不灌背景是一个运行时开关，不在落盘层决定**。
- Stage1 UNet 很重、**不能现场算**，故必须落；**只落 ligand-area 内**把体量从"整图几十 TB"压到"单位数 TB"。同一区域 of center/bias box 因 Stage1 特征带 box 上下文而**各不相同**，不是冗余副本，是有意的增广。
- **命名对称**：PP 侧统一 `ligand_` 前缀，A 侧统一 `receptor_` 前缀。

### 4.5 预训练化学 UNet 特征 → `addons/chem_unet_feat/{pdb_id}.npz`

独立于 Stage1 的预训练化学 UNet，其特征**在 Stage1 推理之后、根据 pred-ligand-area mask 计算并存储**。与 `stage1_feat` 分开存储（计算时序不同、可独立添油）。

| key | 形式 | 说明 |
|---|---|---|
| `ligand_voxel_index` | `[K, 3] int` | 冗耐存储（与 `stage1_feat` 当前一致，未来可能不同） |
| `ligand_voxel_feat` | `[K, C_chem] float` | 化学 UNet 特征 |

- 消费方在 `FuseSources` 时与 `stage1_feat` 的 voxel 特征**拼接**后作为 PP 的 main source。
- **加新特征 = 新建 `addons/{新名}/` 目录**，老添油一字节不动（第 3 层"只增不改"原则）。

### 4.6 口袋描述子 → `addons/pocket_gt/` + `addons/pocket_blob/`

两种口袋定义，各为独立添油，各自记录**口袋身份**（包含哪些受体原子）+ **口袋描述子**：

| 口袋类型 | 定义 | 何时产 | 依赖 |
|---|---|---|---|
| **`pocket_gt`** | per-BOX，取中心最近的 occurrence（`centroid_atom` 距离），对该 occurrence 的 GT 原子逐个取 vdW 包络，包络内的受体原子 | BOX 枚举时（只需第 1 层 GT 坐标 + 受体坐标） | 不依赖 Stage1 |
| **`pocket_blob`** | per-BOX，blob 体素包络选周围受体原子 | blob 出生时 | 依赖 blob（第 3 层） |

`addons/pocket_gt/{pdb_id}.npz` 与 `addons/pocket_blob/{pdb_id}.npz` 内部字段**对称**：

| key | 形式 | 说明 |
|---|---|---|
| `pocket_atom_index` | `[P] int32` | 口袋受体原子全局索引 |
| `n_pocket_atoms` | `int32` | 口袋原子数 |
| `radius_gyration` | `float32` | 口袋 Rg |
| `res_type_hist` | `(25,) float32` | 残基类型直方图（RES_VOCAB 25 类） |
| `wiener_index` | `float32` | 口袋内化学键子图的 Wiener 指数 |
| `graph_energy` | `float32` | 口袋内化学键子图邻接矩阵的谱能量 |

- 描述子计算**复用配体侧通用函数**（`wiener_index`, `graph_energy`, `radius_gyration` 为通用实现，配体和口袋共用）。
- 口袋的化学键子图 = 第 1 层受体键表（`bond_index`/`bond_type`）按 `pocket_atom_index` 切片。
- context box 通常无 in-box occurrence → 无 `pocket_gt`（自然缺失）。
- `pocket_gt` 用于训练（GT 可见）；`pocket_blob` 用于模拟推理（blob 为锚）。

---

## §5 第 4 层：现场算 + 两条不变量

### 5.1 现场算

- **56 维辅助密度通道**：dataset `__getitem__` 里从第 1 层 exp/sim 在线算（`density_channel_builder`，`{op}_{norm}_{post}` 命名）。
- **`diff`**：`exp − sim` 现场算。
- **O-distance**：box 中心 + `centroid_atom` 现推。
- **覆盖矩阵装配**：见 §6。

### 5.2 不变量 A：身份冻结 + materialize 时扰动

- **BOX 身份冻结**：origin/shape/occ_distances 等枚举时定死、落盘。
- 模型读取两种姿势：**原样读**（Stage2/3）按描述子直接切片；**先扰动再读**（仅 Stage1）在 materialize 时对 origin 加 jitter / 体素增广再切第 1 层得标签——增广**下沉到 materialize 层**，不动 BOX 身份。

### 5.3 不变量 B：扰动 ⟺ 放弃第 3 层

第 3 层 blob/coverage 是为**冻结那个身份**缓存的。一旦 Stage1 把 origin 扰动了就对不上。所以：**扰动路径只用第 1、2 层；原样读才能吃第 3 层添油。** 即 Stage1 增广路径 ⟺ 不用 blob；Stage2/3 原样读 ⟺ 可用 blob。

---

## §6 覆盖矩阵装配（featurizer 职责，非落盘）

```text
对一张图 P：
  行 = 收集 P 的所有 box 的 blob（无 blob 的 box 已不在样本里）
  列 = P 的全部 occurrence（候选身份 × count 展开成 slot；图级，与 box 无关）
  entry(行 i, 列 j):
     密度档：读 box_i 的稀疏 coverage → 命中 j 取其 α/β/O_IoU；未命中 = 0（拒假阳负监督）
     纯受体档：读 box_i 的稀疏 occ_distances → O_dist(box_i, occ_j)；未命中 = 远/0
  → [n_blobs, n_slots] 网格
```

> off-diagonal（merge、负样本）天然可算：只需 `blob_i` 与 `occurrence_j` 各自的量（mask 或中心），**不需要任何 box 级交叉记录**。

---

## §7 三档与可拆卸

三档 = **同一批 BOX 的不同清单切片**，由 dataset 配方决定激活哪些块；**不是切出了不同的产物**。

| 档 | Stage1 输入 | Stage2/3 激活的块 | blob | 备注 |
|---|---|---|---|---|
| **纯密度档** | 只有密度 | 第 1 层 density（+56 通道）、第 2 层、第 3 层 blob/coverage/Stage1 voxel 特征 | 有 | 前置：Stage1 也只吃密度 |
| **统一档** | 密度 + 受体 | 上面全部 + 49 维受体特征 + A 侧多尺度特征 + 受体几何 | 有 | 最强模型 |
| **"纯受体"档** | **密度 + 受体** | 49 维受体特征 + A 侧多尺度特征 + 受体几何 + **blob mask 作空间锚**（关 PP 特征、关 56 通道密度） | **有** | Stage1 仍有密度 → blob 仍产出；Stage2/3 只用受体侧 |

可拆卸 = 丢掉 PP 特征退回纯受体、丢掉受体块退回纯密度，**消融和换档是同一个开关**。

### 7.1 两条红线

1. **三档不另立 BOX 来源**：纯受体档**不能**为了"免费拿到位点+口袋"去单切一种"site+pocket box"。三档都跑在现有 box_type 上，口袋只是"以 blob/box 为锚选受体原子"的**视图**（§8.2），不是新产物。
2. **box_type 可扩展 ≠ 三档后门**：§3.3 的开放性是为别的真实用途留的；**不得**用新 box_type 绕过三档可拆卸性。

---

## §8 四模型对接（docking）

| 模型 | 读什么 | 怎么对接 |
|---|---|---|
| **Stage1（Find）** | 第 1 层切片（密度 + 标签）；可 materialize 扰动 | dataset 迭代 BOX 描述子，懒切 80³ 样本；标签 = 切全局 mask/原子标签。口袋 = **box + buffer** 选受体原子（它没有更精细的锚）。复用 `box_geometry` + `density_channel_builder` |
| **Stage2（Match）** | 第 2 层 + 第 3 层 blob/coverage | 同 PDB 多 box 的 blob 拼成行、图级 occurrence 拼成列（§6）；早期（无全图推理）：混采 bias（真）+ context（假）；正式（全图推理完毕）：infered_box（自然分布）；口袋以 **blob 为锚**（§8.2） |
| **Stage3（Build）** | 第 2 层几何 + 第 3 层 blob 的 prompt 点 + 受体块 | (blob box, 配对身份, prompt 点) 三元组；口袋以 **blob 为锚** |
| **UNet（预训练化学）** | 第 1 层密度（输入）→ 第 3 层 ligand-area 内 voxel 特征（产出） | 特征按 box 落盘，PP 采样 gather |

**纯受体档 Stage2 的特殊性**：无密度 → 无 blob → precision-B 无原生定义，监督走对称 O（由 box 中心到 occurrence `centroid_atom` 的**距离**定义，第 2 层 `occ_distances` 备好原料）；**"用距离还是覆盖定义标签"是配方层选择，不烤进存储**。

### 8.2 口袋 = 以 blob 为锚的视图（Stage2/3）

Stage2/3 的"位点周围口袋" = 以 **blob**（预测 ligand-area 体素并集 / 其包络）为锚、选周围 X 埃的受体原子。它是**第 1 层受体的一个切片视图**，不单独切产物。训练用预测 blob、推理也用预测 blob——**同源、无域差**（冷启动、blob 尚未产出时可暂以 GT ligand-area 顶替）。

> 与 Stage1 的区别：Stage1 用 box+buffer（box 为锚，它还不知配体在哪）；Stage2/3 用 blob 包络（blob 为锚，位点已定）。

---

## §9 BOX 家族枚举

### 9.1 当前四类（可扩展）

| box_type | 来源 | in-box occurrence | 备注 |
|---|---|---|---|
| **center** | 以 occurrence `centroid_voxel` 严格居中切 80³ | 该 occurrence（+ 落在框内的邻居） | 正样本（居中 blob） |
| **bias** | 在 center 上按配方偏移，每 instance 多个 | 同上 | 偏心 blob，模拟 Find 定心误差；偏移配方见 §9.2 |
| **context** | **只按受体原子比率 > 阈值**的随机裁剪 | 通常无（撞上则覆盖几何如实给出） | 假阳来源；**不需 clean 旗**——真撞上配体，§4.3 覆盖会如实非零 |
| **infered_box** | 全图划窗**两阶段**推理：pass-1 滑窗定位 blob → pass-2 以其中心重裁 box 再推、**落盘 pass-2 结果**（`Stage1 §3.2`） | 由覆盖/距离事后给出 | 自然分布（merge/split、真实假阳）；中心化重推闭合训/推域差 |

- **冻结枚举**：bias/context 的偏移/裁剪在枚举时定死、落第 2 层；blob/coverage 缓存要求 box 身份稳定（§5.2/5.3）。
- **加新 box_type = 加一个枚举器**，不改 schema、不动存储布局。

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
2. **模型输入契约 / featurizer**（见 `迭代运算 §4`）：按"某模型 + 某档"的配方，把块拼成模型张量视图（含 §6 矩阵装配）。
3. **模型算子**（见 `迭代运算`）：只看拼好的张量，不知盘上长啥样。

**继承的原则与可复用叶子**（代码可重写、原则/叶子保留）：

- **原则**：训练侧与推理侧**共用同一个 BOX→样本 builder**，靠它强制两边契约一致。
- **可直接当库用的纯叶子**（与配体种类零耦合）：`box_geometry`（选框内+buffer 原子、三套坐标、hardmask、按索引切特征）、`density_channel_builder`（在线 56 通道）。
- **要重写的耦合层**：旧 `box_point_dataset` 按配体种类分文件夹/分 split/平衡采样那一套——推倒，改成按 §3 描述子 + `box_index` 组织。

---

## §11 待定与维护

**待定（实现时定）**：

1. 第 3 层变长添油（blob mask / la_voxel_*）的具体 ragged 落盘格式（offset 数组 vs 稀疏 COO）。
2. `box_index` 的物理形式（单张 parquet/jsonl vs 按 PDB 分片再聚合）。
3. bias 的比例与 floor 分布、context 受体比率阈值、距离-O 的 `ρ`、IoU-O 的 `τ`、覆盖条目入选阈值——先看分布再定。
4. ~~`centroid_atom` 是否物化~~ **已定物化进 `ligand_coords.npz`**（C4 产，§2.2）。
5. 各层级通道数 C（L1–L4 维度）与 `C_chem`（化学 UNet 通道数）。
6. `infered_box` 是否回填某种 occurrence 锚（默认不填，靠覆盖/距离）。
7. blob `scores` 集具体成员、over-save 的 recall-first 下限——先看分布再定（`Stage1 §4/§8`）。
8. §4.4 `receptor_feat_L1`–`L4` 是否全部有效，以及它们的维度。
9. 口袋描述子的 vdW 包络半径是否与数据处理 E3 的 ligand-area 半径一致（默认一致）。

**维护**：实现后以代码与真实产物为准回填字段/dtype/shape。改动四层划分 / 描述子字段 / 添油机制 / 三档语义 / box_type 集合 / 对接方式时，同步更新本文与下游两份模型文档的指针。本文是 BOX 级数据契约的唯一权威，事实只写一遍。
