# AdaLigand BOX 级数据契约

> **本文定位**：本文是 Stage1 训练预定位、完整概率、proposal/CLG、局部物化、selector/selection addon 与 selected-final 的盘上契约。训练预定位池和推理物化 BOX 用途不同、物理存储分家；推理侧继续保留按 run 追加、不覆盖旧产物的 addon 机制。
>
> **上下游**：
> - **上游** = `文档/规划文档/数据处理_v2.md`，它产出**整图级 / occurrence 级**产物（受体 token、LigandObject、per-occurrence GT 坐标与两套中心、原子标签、exp/sim/ligand_area 密度网格、质量/过滤），**到此为止，不切 BOX**。本文从这里接手。
> - **下游** = `文档/讨论/模型总规划_v2.md`（Stage2 预测什么/损失）、`文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md`（怎么算/算子）。它们消费本文定义的 BOX 块；数据怎么存只在本文写一遍，那两份只留指针。
> - **产物来源** = `文档/规划文档/Stage1训练与多阈值推理.md`：全图概率、组件森林、候选谱系组（CLG）、Global Proposal、局部物化、候选打分、反链选择与可选精修的**产法和语义**归它；本文只规定这些量**怎么存**。
>
> **边界**：本文只管“**盘上长什么样**”。“块怎么拼成模型张量”见 `文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md §4`；“模型拿这些预测什么”见 `文档/讨论/模型总规划_v2.md`。本文不重复运算与监督细节。
>
> **测试设定**：本文保留的 Match/coverage/one-to-one 接缝仅服务“已知配体身份和数量”的测试；未知身份或未知数量不是本轮契约目标。Stage1 proposal/CLG 生产本身不读取该先验。
>
> **治理与精度**：本文规定目标逻辑 schema，包括字段语义、解码后的 shape 与逻辑 dtype。物理文件可以压缩或分片，但不能改变解码结果。若实现与本文漂移，先按 `AGENTS.md` 审计并请求回填决定，不能让代码静默覆盖契约。
>
> **NumPy 写盘纪律**：本文范围内所有新写 `.npz` 产物统一调用 `np.savez_compressed`；禁止把 `np.compress` 误当作归档压缩 API。容器迁移不得改变逻辑 schema。

---

## §0 一句话总览

> 一个 BOX 不是一坨打包好的张量，而是**一个轻量身份 + 若干按来源分开、可拆卸、可添油的块**。重的东西**整图级存一次**，BOX 只是切片入口；模型在运行时拿一份**清单（配方）**，按需读到它要的块。换来源、换档位、加特征，都不动模型，也不重写老数据。
>
> **两个体系（贯穿全文）**：`center/bias/context` 只在紧凑训练预定位池中保存；它们不使用通用 `box_type`、不挂 addon。blob 只来自完整 `P_global`，Group-parent/F1 baseline/selected-final 是推理物化角色，并继续使用 BOX identity + addon。一个 `CLG_group_parent` BOX 对应一个 CLG，框内可以有多个 Global Proposal Candidate；局部重跑的 mask 只作辅助观察，不能替换全图候选身份。

---

## §1 两个物理体系、四种逻辑层

训练位置多、字段少；推理物化位置少、特征多。二者盘上分家，但都从同一整图层读取，并解析到同一个 runtime materializer。

| 层 | 名称 | 粒度 | 何时产生 | 可变性 | 装什么 |
|---|---|---|---|---|---|
| **1** | 整图级落盘 | per-PDB | 数据处理阶段（慢、贵） | 固定 | exp/sim 密度、49 维受体特征、ligand_area mask + 两套质心、binding/instance 原子标签、LigandObject、per-occurrence GT 坐标 |
| **2A** | 训练预定位池 | per-PDB 紧凑数组 | 训练准备 | 冻结 | center/bias/context 的 occurrence 引用与整数起点；不保存实际 80³ 切片 |
| **2B** | 推理物化 BOX | per-BOX（极小） | F1/CLG/selected-final 物化时 | 冻结 | `box_id`、几何、materialization role、上游 run 与来源节点 |
| **3** | 推理 run 与 per-BOX addon | per-PDB 概率/proposal/CLG run；以及需要添油的 2B BOX | Stage1 整图推理后 / 任意时刻 | **只增不改** | 完整概率图、proposal/CLG 表、共享 voxel/P/receptor、membership、GT overlap、selector score、selection result、selected-final 与密度 U-Net 特征 |
| **4** | 现场算 | per-BOX，运行时 | dataset `__getitem__` | 瞬时 | 56 维辅助密度通道、diff、O-distance、覆盖矩阵装配、materialize 扰动 |

**为什么这么分**：

- 慢且固定的东西（第 1 层）**每个 PDB 整图算并存一次、现场切片复用**，避免把同一份密度、标签和受体拷进上百万个 80³ BOX 文件。这是避免物化重复大数组，**不是对 BOX 的空间位置或体素内容去重**。
- 训练预定位池只存数组下标与起点；一个 epoch 如何取 `1:5:3` 由训练计划规定，不复制大数组。
- 推理物化 BOX 身份小、冻结，是 addon 的索引锚。基础 proposal、不同 selector checkpoint、不同 selection 参数和 refinement 各自写独立 run/addon，不能原地覆盖。
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
| occurrence 质心（两套） | `centroid_voxel_{cid}`、`centroid_atom_{cid}` | E3 / C4（见 §2.2） | 两者盘上都是世界 XYZ Å；来源与用途不同，分开维护 |
| per-occurrence GT 坐标 | `coords_{cid} (M,3)`、`present_{cid} (M,) bool` | Stage C4 `ligand_coords.npz` | 真实 pose |
| 受体 token（几何 + 键表 + 49 维特征） | coords/element/res_type/atom_name/res_index/chain_index + bond_index/bond_type + `feat(N_rec,49)` | Stage C3 `receptor_tokens.npz`（数据处理 §5.4） | 全局世界坐标；49 维**必须整图算**（见 §2.1） |
| binding / instance 原子标签 | `binding_atom (N_rec,) bool`、`instance_id (N_rec,) int32`、`nearest_dist` | Stage D `atom_labels.npz` | per-occurrence 实例 |
| LigandObject | 化学（atoms/bonds/atom_names/smiles/ref_pos） | Stage C2 `ligand_objects/{object_key}.npz` | 去重、跨 PDB 复用 |

**不在第 1 层的两样**：
- `diff` 密度**不落盘**——`diff = exp − sim` 在第 4 层现场算（exp/sim 同网格，安全）。
- UNet voxel 特征**不整图落盘**——按物化 BOX 只存候选范围内的 voxel 特征（§4.2.5、§4.5）。

### 2.1 49 维受体特征（统一、纯受体、必须整图算）

**所有模型的受体原子特征统一用这 49 维**（沿用 Pocket_Plus 已验证有效的特征工程）。构成（`Make_Data/PDB_processor/config.py`）：

```
49 = 元素 one-hot(6) + 残基类型 one-hot(25) + 理化性质(8) + 原子质量(1) + 局部密度直方图(9)
```

**这 49 维完全是纯受体的，与密度图无关。** 其中"局部密度"的 9 维是**原子堆积直方图**——对每个原子用 KD-tree 数它在 0–2, 2–4, …, 16–18 Å 各距离壳层内的**邻居原子数**，再 log1p（`compute_local_density_sparse`）。它是几何/堆积描述子，不是 cryo-EM 密度。由此两条硬约束：

1. **受体块统一**：凡某个模型档位启用受体块，都使用逐位一致的 49 维，不做 40/49 切换；`unet_c1` 是单通道纯密度模型，完全不读取这 49 维。
2. **必须整图算、再切片**：那 9 维直方图依赖"框外的真实邻居"。若在 BOX 内部现算，边缘原子会数漏邻居、算错。所以 49 维**对完整受体算一次**，存第 1 层，BOX 阶段只按 `atom_global_indices` 切片。

### 2.2 occurrence 的两套中心（用途分开）

每个 occurrence 维护两套几何中心，**各管各的**，不可混用：

- **`centroid_voxel_{cid}`**：ligand_area mask 各入选体素中心的均值，E3 以 `[3] float32` 的**世界 XYZ 坐标（Å）**保存；名字中的 `voxel` 表示它由 voxel mask 派生，绝不表示 ZYX voxel index。用于 **recrop 落框**（先经统一 helper 换算成起点，不能直接当 index）与 **prompt 点**的同源量——凡涉及"体素/mask 帧"的几何用它。
- **`centroid_atom_{cid}`**：**present 重原子坐标的几何中心** = `mean(coords_{cid}[present_{cid}])`，**派生自 C4**。用于 proposal↔occurrence 距离、GT envelope 与图级评估——凡涉及“配体真实位置”的几何用它。

> `centroid_atom` 是 C4 既有产物（`coords`+`present`）的纯派生。**已定物化进 `ligand_coords.npz`**（由 C4 产：`centroid_atom_{cid}=mean(coords_{cid}[present_{cid}])`，见 `数据处理 §5.5`），下游直接读、不必现场重算。

---

## §3 第 2 层：训练预定位池与推理物化 BOX

### 3.1 训练预定位池（2A）

布局：

```text
stage1_train_pool/{box_set_id}/manifest.json
stage1_train_pool/{box_set_id}/{pdb_id}.npz
stage1_train_pool/{box_set_id}/validation_selection.npz
```

每个 PDB 只保存紧凑数组：

| 字段 | shape / dtype | 说明 |
|---|---|---|
| `occurrence_id` | `[O] int32` | 当前 PDB occurrence 身份 |
| `center_start_zyx` | `[O,3] int32` | 每 occurrence 一个 center 起点；由 `mask_{cid}` 的 mean ZYX index 经统一 half-up helper 生成，禁止把世界 XYZ 的 `centroid_voxel_{cid}` 三元组直接当 index |
| `bias_start_zyx` | `[O,N_bias_pool,3] int32` | 默认 pool 为 15；每 epoch 选 5 |
| `context_start_zyx` | `[C,3] int32` | 每 PDB 目标 500 个合法起点，最多尝试 3000 次 |

context 合法条件中的受体重原子下限固定为 `N_context_min=1000`；完全相同的 context 起点只保留一条，尝试耗尽后允许 `C<500`。manifest 记录上游 release/split、BOX shape、bias pool 数、context 参数、schema version 和 per-PDB 文件校验值。

`validation_selection.npz` 冻结验证时真正使用的子集。令 `O_val` 为 validation 全部 occurrence 数；center 默认使用这些 occurrence，不重复列，其余数组为：

| 字段 | shape / dtype | 说明 |
|---|---|---|
| `bias_pdb_row` | `[5*O_val] int32` | 指向 manifest 中固定顺序的 validation PDB 表 |
| `bias_occurrence_id` | `[5*O_val] int32` | 每个 occurrence 恰好出现 5 次 |
| `bias_candidate_id` | `[5*O_val] int16` | 指向该 occurrence 的 bias pool |
| `context_pdb_row` | `[3*O_val] int32` | 固定的全局 context 清单 |
| `context_candidate_id` | `[3*O_val] int32` | 指向对应 PDB 的 context pool |

manifest 同时记录 validation PDB 表、选择 seed、是否因全局 context pool 不足而循环取样、entry 数和文件哈希。该清单不含增强结果；读取时必须关闭增强和 shuffle。

训练池不保存 `box_type`、`box_id`、`origin_xyz`、voxel size、`occ_distances`、JSON provenance、增强结果或实际 80³ 数组。自然身份就是数组位置：center 为 `(box_set_id,pdb_id,occurrence_id)`，bias 再加 `bias_candidate_id`，context 使用 `context_candidate_id`。起点生成必须调用坐标 parity 放行后的同一 helper；manifest 记录 helper/version 与实际 rounding policy，不在本文复制另一套坐标公式。

### 3.2 推理物化 BOX 描述子（2B）

Group-parent、F1 baseline 和 selected-final 继续使用冻结 BOX identity。第一版物理布局为：

```text
materializations/{materialization_run_id}/manifest.json
materializations/{materialization_run_id}/{pdb_id}.npz
```

一个 materialization run 只对应一种 `materialization_role`。manifest 保存 `schema_version`、`materialization_run_id`、`materialization_role`、直接上级 run ID、实际 Stage1 checkpoint/forward 与裁剪配置，以及每个 PDB 文件的引用、行数和哈希。per-PDB NPZ 只保存紧凑数组：

| 字段 | shape / dtype | 说明 |
|---|---|---|
| `box_id` | `[B] int32` | 直接使用本文件行号 `0..B-1` |
| `box_start_zyx` | `[B,3] int32` | 80³ 裁剪起点，可越出完整网格 |
| `shape_zyx` | `[B,3] uint16` | 第一版全部为 `[80,80,80]` |
| `CLG_id` | `[B] int32` | Group-parent/多阈值 selected-final 的来源 CLG；不适用为 `-1` |
| `source_tree_id` | `[B] int32` | 来源 Global Proposal tree；不适用为 `-1` |
| `source_node_id` | `[B] int32` | Group-parent/F1/被精修 Global Proposal node；不适用为 `-1` |
| `source_materialization_box_id` | `[B] int32` | selected-final 的来源 Group-parent/F1 BOX；其它角色为 `-1` |
| `source_candidate_index` | `[B] int16` | selected-final 的来源 CLG candidate；F1 路线和其它角色为 `-1` |

- `box_id` 只在 `(materialization_run_id,pdb_id)` 内唯一，不需要跨 run 分配器。
- `materialization_role` 取 `CLG_group_parent`、`f1_baseline` 或 `selected_final`。Group-parent manifest 直接引用 `CLG_run_id`；F1 manifest 直接引用 `proposal_run_id`；selected-final manifest 固定一种 `source_route` 和一个 `source_materialization_run_id`，多阈值路线同时引用 `selection_run_id`。
- 对 selected-final，`materialization_run_id` 与 `refinement_run_id` 使用同一个字符串。实现先在本 refinement run 内分配行号，再共同写出 index 与 refinement payload，最后原子发布 manifest，因此不存在“先找 BOX 还是先找 addon”的循环。
- 三种角色的 `source_tree_id/source_node_id` 都使用 proposal 节点原字段名；overlap 中的 `proposal_tree_id/proposal_node_id` 只是批量表前缀，必须逐值等于它们。
- `box_start_zyx` 可以越出完整网格；`shape_zyx` 第一版固定 `[80,80,80]`。完整图 origin、实际 voxel size 与 BOX 世界原点从权威完整图几何和同一个 materializer 派生，不在每条描述子重复保存。
- 坐标帧以修改后的 AdaLigand A–G 与当前 Pocket_Plus 的 parity 审计为准：数组为 ZYX、世界量为 XYZ、origin 为网格下角点、voxel center 使用 `+0.5 voxel`。该 parity 比较坐标、局部化和裁剪，不要求 Ada schema v3 的逐元素 VdW mask 与 Pocket 的统一阈值 GT 生成逻辑相同；本契约也不复制第二套坐标公式。
- 切片先求 BOX 与完整网格交集，图外密度、概率和 GT mask 补 0；图外没有 receptor 原子；不保存 `voxel_valid_mask`，也不 silent clamp 或平移 BOX 起点。

### 3.3 统一 runtime 请求

训练位置、滑窗和推理物化 BOX 在盘上分家，读取后都解析为：

```text
ResolvedStage1Crop
  pdb_id
  box_start_zyx: int32[3]
  shape_zyx: uint16[3] = [80,80,80]
  require_targets: bool
  source_kind: enum
  source_key: typed tuple
```

`source_kind/source_key` 只允许以下五种组合：

| `source_kind` | `source_key` |
|---|---|
| `train_center` | `(box_set_id, occurrence_id)` |
| `train_bias` | `(box_set_id, occurrence_id, bias_candidate_id)` |
| `train_context` | `(box_set_id, context_candidate_id)` |
| `full_map_window` | `(probability_run_id, window_index)` |
| `materialized_box` | `(materialization_run_id, box_id)` |

一个 runtime 请求的完整身份是 `(pdb_id,source_kind,source_key)`；`source_key` 只在给定 `pdb_id/source_kind` 的作用域内解释，不能脱离 PDB 单独 join。

训练、整图推理、Group-parent、F1 baseline 与 selected-final 必须调用同一个 crop/builder/collate。差别只在起点来源、是否增强、是否加载 GT 和 forward 是否导出中间特征。proposal overlap 始终由 Global Proposal Mask 与图级全部 occurrence GT mask 计算，不依赖训练池中的 in-box 列表或描述性距离。

Find 的 runtime materializer 还必须保留 Pocket_Plus 现有两种 receptor voxel 量：`hardmask[80,80,80]` 是全部 core receptor 原子 home voxel 的几何占据，训练/推理都现场构造；`voxel_label[80,80,80]` 是其中 `binding_atom=True` 的 home voxel 并集，仅在 `require_targets=True` 时构造。二者都不落盘为 BOX 数组；`hardmask` 不是 `voxel_valid_mask`，`voxel_label` 也不是 `ligand_area_target`。`unet_c1` 不查询 receptor，因而不构造或读取这两个字段。

---

## §4 第 3 层：推理 run 与 per-BOX 添油（只增不改）

完整概率、proposal 和 CLG 是图级 run 产物；局部特征、overlap、selector score、selection 与 refinement 是挂在物化 BOX 上的 addon。两者都只增不改，但物理目录和寻址键不同。

### 4.1 存储布局（治文件数）

训练位置已由 2A 紧凑数组解决；图级 run 与 per-BOX addon 分别按 PDB 聚合。**绝不每个 BOX 每种 addon 写一个小文件**：

```text
stage1_runs/{run_kind}/{run_id}/manifest.json
stage1_runs/{run_kind}/{run_id}/{pdb_id}.npz

addons/{addon_name}/{addon_run_id}/manifest.json
addons/{addon_name}/{addon_run_id}/{pdb_id}.npz
  内部: box_id → entry 的映射；变长内容用 offsets + indices 存
```

- `run_kind` 第一版包括 `probability`、`proposal`、`CLG`；分别使用 `probability_run_id`、`proposal_run_id`、`CLG_run_id`，并由 manifest 回指直接上级。
- **加新特征 = 新建 `addon_name/addon_run_id` namespace**，老 addon 一字节不动。selector、selection 和 refinement 分别使用 `selector_run_id`、`selection_run_id`、`refinement_run_id`；其它 feature addon 也必须有自己的 run ID 与直接上级。
- 每个 per-BOX addon manifest 必须绑定唯一的 `materialization_run_id`。完整逻辑键是 **`(addon_name,addon_run_id,materialization_run_id,pdb_id,box_id)`**；目录已给出前两项，manifest 给出第三项，文件内部只需保存 `box_id` entry 映射。
- 不再另建通用 `addon_inventory` 服务。每个 run/addon manifest 直接记录 per-PDB 文件引用、entry 数和内容哈希；不得回写冻结的 materialization index。
- run ID 只需在项目内唯一并能定位不可变 manifest；普通 local ID 只需在对应 run/PDB 内唯一。本文不要求 canonical JSON、跨重跑稳定编号或自定义同分排序。
- 第一版 NumPy 物理产物统一用 `np.savez_compressed` 写入。配置对象和 provenance 只写独立 UTF-8 JSON manifest；NPZ 只保存数值、布尔和固定宽度字符串数组，禁止 object array/pickle。若 IO benchmark 后改用 Zarr 或其它容器，解码后的字段、dtype、shape、offsets/indices 语义和压缩要求不得变化。

### 4.2 probability run、proposal run、CLG 与 Global Proposal

blob 只来自完整全图概率图。一个 `CLG_group_parent` BOX 对应一个 **候选谱系组（Candidate Lineage Group, CLG）**，组内有 `N` 个 **Global Proposal Candidate**。候选 mask 永远指第一次全图组件森林中的节点；Group-parent 局部重跑只补特征和局部形状观察。

#### 4.2.1 probability run manifest（per-PDB、per-run）

每次 Stage1 全图滑窗推理先保存一份不隶属于某个 BOX 的 probability manifest，并正式保存融合后的完整概率图：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `schema_version` | scalar `uint16` | 本概率产物的 schema 版本 |
| `probability_run_id` | string | Stage1 checkpoint、上游 data release、输入归一化、滑窗与融合配置的运行身份；不包含阈值或 CLG 配置 |
| `pdb_id` | string | PDB 身份 |
| `producer_model_name` | enum string | `unet_c1` 或 `Find` |
| `stage1_checkpoint_sha256` | string | checkpoint 内容哈希 |
| `full_map_inference_config` | JSON | 输入通道、窗口 shape/stride、Gaussian 权重、累加与融合公式等完整配置 |
| `full_grid_shape_zyx` | `[3] int32` | 完整概率图形状 |
| `full_grid_origin_xyz` | `[3] float32` | 完整网格权威 origin；不得自行平移 |
| `origin_semantics` | string | 直接复制上游 schema 声明，并由修改后 AdaLigand/Pocket_Plus parity 测试验证 |
| `voxel_size_xyz` | `[3] float32` | 完整网格 voxel size |
| `probability_asset_ref` | string + hash | 必需的完整 `P_global[Z,Y,X] float32` 压缩产物引用与内容校验值 |

第一版物理布局为：

```text
stage1_runs/probability/{probability_run_id}/{pdb_id}.npz
  P_global: [Z,Y,X] float32
```

同一 `probability_run_id` 的正式概率图是后续所有阈值、tree 和 CLG 的唯一输入。更换 checkpoint 或任何影响完整概率图的推理配置必须产生新 ID；后处理不得绕过该产物改用另一份临时精度或临时数组。

#### 4.2.2 proposal run manifest（per-PDB、per-run）

一份正式概率图可以被多套阈值与组件规则复用。每套配置保存独立 proposal manifest：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `schema_version` | scalar `uint16` | 本 proposal 产物的 schema 版本 |
| `proposal_run_id` | string | `probability_run_id`、阈值、连通组件与节点合法性配置的运行身份；不包含 CLG 枚举参数 |
| `probability_run_id` | string | 回指唯一正式完整概率图 |
| `pdb_id` | string | PDB 身份 |
| `threshold_value` | `[T] float32` | 物理阈值，严格按高到低排列，`T<255` |
| `alpha_value` | `[A] float32` | calibration 使用的全部 alpha |
| `alpha_to_threshold_rank` | `[A] uint8` | 每个 alpha 对应的物理阈值位次；重复阈值可映射同一 rank |
| `connectivity` | scalar `uint8` | 固定为 26 |
| `proposal_config` | JSON | 体素上下界、统一边界规则、组件森林构造版本和节点合法性参数 |
| `component_tree_asset_ref` | string + hash | 原始组件森林审计表引用 |

阈值 rank 的重建规则固定为：`threshold_value[0]` 最高；局部 `threshold_rank_map <= r` 恰好得到第 `r` 个阈值下的前景。

一个 `probability_run_id` 可以被多个 `proposal_run_id` 引用。`tree_id` 在 `(proposal_run_id,pdb_id)` 内唯一，`node_id` 在 `tree_id` 内唯一；它们可以直接使用本次组件构造的数组顺序，不要求跨重跑相同。

#### 4.2.3 CLG run manifest（per-PDB、per-run）

CLG 枚举是 proposal 之后的独立步骤。同一份组件森林可以用不同的 CLG 枚举参数产生多套候选组，因此不能把这些参数塞回 `proposal_run_id`：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `schema_version` | scalar `uint16` | 本 CLG 产物的 schema 版本 |
| `CLG_run_id` | string | `proposal_run_id` 与本次 CLG 枚举配置的运行身份 |
| `proposal_run_id` | string | 回指唯一组件森林 |
| `pdb_id` | string | PDB 身份 |
| `CLG_config` | JSON | `max_split_events`、`max_merge_events`、`max_candidates_per_CLG`、`N_abs`、`N_multi`、总量上限公式和工作树删除规则版本 |
| `n_f1_legal_seeds` | scalar `int32` | 本 PDB 可作为起点的 F1 合法节点数 |
| `n_CLG_cap` | scalar `int32` | 本 PDB 本次运行允许产生的 CLG 上限 |
| `n_CLG_completed` | scalar `int32` | 实际完成的 CLG 数 |
| `CLG_cap_reached` | scalar `bool` | 是否因达到上限停止 |
| `next_eligible_seed_exists_at_stop` | scalar `bool` | 停止时工作树中是否仍有合法起点 |
| `n_candidate_cap_events_attempted` | scalar `int32` | 尝试接受的 split/merge 原子事件数 |
| `n_candidate_cap_events_rejected` | scalar `int32` | 因 `max_candidates_per_CLG` 拒绝的原子事件数 |
| `CLG_asset_ref` | string + hash | CLG 清单及候选数组的压缩产物引用 |

组件森林保持只读；枚举器只在工作副本（或等价的 `active` 布尔数组）上生成 CLG，并在一个 CLG 完成后删除计划规定的节点集合。一个 `proposal_run_id` 可以被多个 `CLG_run_id` 引用。

#### 4.2.4 CLG 候选表

设：

- `N`：本 CLG 可供 selector 评分的候选数；
- `N_seed`：原始种子与类种子姐妹数量。

每个 `CLG_group_parent` BOX 保存：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `CLG_run_id` | string | 回指生成本候选组的 CLG run |
| `CLG_id` | scalar `int32` | `(CLG_run_id,pdb_id)` 内唯一 |
| `tree_id` | scalar `int32` | `(proposal_run_id,pdb_id)` 内唯一的所属组件树 |
| `group_parent_node_id` | scalar `int32` | CLG 唯一 Group-parent Node |
| `group_parent_candidate_index` | scalar `int16` | Group-parent 在本 CLG 候选数组中的 index |
| `candidate_node_id` | `[N] int32` | 每个 `candidate_index` 对应的原始全图组件树节点；`node_id` 在 `tree_id` 内唯一 |
| `candidate_tree_parent_node_id` | `[N] int32` | 原始树直接父节点，可不在本 CLG 内；树根为 `-1` |
| `candidate_threshold_rank` | `[N] uint8` | Global Proposal 所在物理阈值位次 |
| `seed_candidate_indices` | `[N_seed] int16` | 原种子和类种子姐妹在候选数组中的 indices |
| `lca_distance_from_i` | `[N,N] uint8` | 有序对 `(i,j)` 中，`i` 到两者 LCA 的边数 |
| `lca_distance_from_j` | `[N,N] uint8` | `j` 到同一 LCA 的边数 |

LCA 距离沿完整原始树计算，即使路径经过没有物化的不可选节点也要计数。由两张距离矩阵可推导祖先、子孙、姐妹、其它分支、阈值差和反链冲突，不重复保存关系枚举表。

`N` 只包含可供 selector 评分的候选。候选合法性的统一边界规则是：完整 Global Proposal Mask 必须严格位于 `centered 80³ BOX ∩ original density grid` 内部。BOX 某个面仍在原图内时，以该 BOX 面审查；BOX 越过原图的面改以原图边界面审查。因体素上下界或违反该规则而不可选择的节点只留在组件树审计表中，CLG 扩展不能穿过它继续取后代。

#### 4.2.5 Group-parent voxel 共享表

设 `K_v` 为 Group-parent Global Proposal Mask 的体素数，`L_v` 为所有候选 voxel membership indices 拼接后的总长度：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `parent_voxel_index_local_zyx` | `[K_v,3] int16` | Group-parent Mask 的 BOX 局部体素索引；唯一，数组顺序按本次产物原样保存 |
| `parent_voxel_global_probability` | `[K_v] float32` | 第一次全图概率在这些体素上的值 |
| `candidate_voxel_offsets` | `[N+1] int64` | 每个候选 membership 的区间边界 |
| `candidate_voxel_indices` | `[L_v] int32` | 每个 Global Proposal Mask 引用 parent voxel 表的 indices |
| `threshold_rank_map` | `[80,80,80] uint8` | Group-parent 局部重跑的多阈值形状；255 表示所有阈值下均为背景 |
| `voxel_feat__{source_name}` | `[K_v,C_{v,s}] float16` | 局部重跑产生的已命名多尺度 voxel 特征 |

必须区分：

- `candidate_voxel_indices` 是 Global Proposal Mask，决定 selector 标签、打分和 Stage2/3 默认 blob。同一候选内部必须唯一；不同候选可以引用相同 parent index，交叉是合法的。无需为它增加稳定排序。
- `threshold_rank_map` 是 Group-parent 局部观察，只作输入信息，不产生新候选。

可从已保存字段直接派生而不重复落盘的量包括：候选 voxel 数、局部/全图 mask、bbox、质心、`prompt_point`、全图概率 mean/max 和 `rank_at_parent_voxel`。第一版 selector 不使用定义尚未稳定的候选 rank histogram 或局部体积变化曲线。

`rank_at_parent_voxel[k]` 固定为在第 `k` 个 `parent_voxel_index_local_zyx` 位置查询 `threshold_rank_map`，全部阈值下均为背景时为 255。完整 rank map 可以包含 Group-parent 之外的局部连通组件，但候选读取和任何候选统计都必须受 parent/candidate membership 限制；这些额外组件不产生候选身份。

#### 4.2.6 F1 baseline

本节的局部 F1 materialization 服务 Find 主路线：它要求同源 voxel、P 与 receptor 特征。`unet_c1` 的 `probability_run_id` 仍可在 F1 阈值查询合法组件并计算纯密度指标，但不创建本节 2B BOX 或伪造 P/receptor addon。

语义 F1 阈值层的每个合法连通 blob 都建立一个居中的推理物化 BOX，设置 `materialization_role=f1_baseline`，并由 `proposal_run_id + pdb_id + source_tree_id + source_node_id` 唯一指向原始全图 F1 节点。F1 baseline 保存全部合法 F1 blob，不受多阈值路线 `N_cap` 限制。

该 BOX 仍运行一次局部 Stage1，并保存与 Group-parent 路线同源的 voxel、完整 P token 和该 blob 自己 pocket 的 receptor 特征；但它不创建 CLG 候选表、LCA、selector score 或 selection result。F1 blob 本身就是 parent voxel 表的完整集合，因此也不为这个单体样本伪造 `N=1` 的 candidate membership。局部重跑只补特征和 `threshold_rank_map`，不替换原始全图 F1 mask；Stage2/3 直接消费该 blob。

### 4.3 Global Proposal × GT overlap（稀疏）

一个 overlap addon run 只绑定一个 `materialization_run_id`；Group-parent 与 F1 baseline 分开写 run。对其中每个全图 proposal blob 计算它与同一 PDB 各 GT occurrence mask 的非零交集。多阈值路线中，一条 proposal entry 对应 CLG 的一个 `candidate_index`；F1 baseline 中，一个 BOX 只有它自己的 F1 proposal entry。所有量都以原始全图 mask 为准，不使用局部重跑形状或 Refined Mask。

设 `N_proposal` 为本 addon 中的 proposal 数，`E` 为非零 proposal-occurrence 记录数：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `proposal_box_id` | `[N_proposal] int32` | 每个 proposal 在本 addon 绑定的 materialization run 中所属 BOX |
| `proposal_candidate_index` | `[N_proposal] int16` | CLG 路线为对应 `candidate_index`；F1 baseline 固定为 `-1` |
| `proposal_tree_id` | `[N_proposal] int32` | 原始全图组件树身份 |
| `proposal_node_id` | `[N_proposal] int32` | 原始全图组件树节点 |
| `proposal_occurrence_offsets` | `[N_proposal+1] int64` | 每个 proposal 的非零 GT 相交记录区间 |
| `overlap_occurrence_id` | `[E] int32` | GT occurrence 身份 |
| `overlap_intersection_voxels` | `[E] int32` | Global Proposal 与该 GT mask 的交集体素数 |
| `atom_coverage_offsets` | `[E+1] int64` | 每条 proposal-occurrence 记录的原子覆盖区间 |
| `atom_coverage_value` | `[L_atom] bool` | 对齐对应 LigandObject 原子行；缺失原子固定为 false |

Global Proposal Node 的完整 join key 是 `(proposal_run_id,pdb_id,proposal_tree_id,proposal_node_id)`；不能只用 tree/node 跨 run 连接。多阈值物化视图再由 addon manifest 的 `CLG_run_id` 与 `proposal_box_id/proposal_candidate_index` 回到对应 CLG；F1 baseline 直接由 `proposal_box_id` 回到自己的物化 BOX。这里要求 run 内可追溯，不要求不同重跑生成相同编号。

派生关系（不另存）：

- `α = inter_voxels / |g|`（recall，`|g|` 来自 `mask_{cid}`）
- `β = inter_voxels / |b|`（precision；CLG 候选的 `|b|` 由 `candidate_voxel_offsets` 相邻差得到，F1 baseline 由 parent voxel 表长度得到）
- `O_IoU = inter_voxels / (|b| + |g| − inter_voxels)`（密度档对称分类目标）
- `O_dist = 1[ dist(proposal mask 体素质心的世界坐标, centroid_atom_{cid}) < ρ ]`（纯受体档；对图级全部 occurrence 现场计算，不入此表）

由上述 overlap 与第 1 层 GT mask 体积还可派生 selector 软标签 $q_i=\max_j IoU(GlobalProposal_i,GT_j)$、最佳 occurrence，以及实例指标所需的 IoU 矩阵。Dataset worker 在训练读取时根据 $Q_{GT}(S)=\sum_{i\in S}q_i-\lambda_{count}|S|$ 用 CPU 在线计算 oracle 最优反链与 $y_{CLG}=\mathbf 1[S^*\ne\varnothing]$；不把 oracle 标签写入不可变 overlap addon，也不建立持久 oracle 标签缓存。

**逐配体原子覆盖**（细分支 recall 辅助监督 of 标签）：

- **定义（生产方写一遍）**：`covered[a] = 1[ world_to_voxel(coords_{cid}[a]) ∈ GlobalProposalMask ]`，仅对 `present_{cid}[a]` 为真的原子有效，缺失原子恒 0。
- **用途**：`文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md §12` 的“逐配体原子覆盖辅助”标签；下游只保留指针，不重写定义。
- 该表既保持旧 Stage2 coverage/逐原子监督可追溯，也避免 selector 训练反复做大规模 voxel 集合求交。

### 4.4 局部物化的 P 与 receptor 共享表

Group-parent 局部重跑只保存一份 BOX 级 P token 表和一份 parent pocket receptor 表。所有候选读取完整 P 表；候选只在 receptor 表上保存自己的 pocket membership。F1 baseline 保存同样来源的 P/receptor 字段，但其 receptor 表就是该 F1 blob 自己的 pocket，不需要 candidate membership。

#### 4.4.1 P token 表

设 `N_P` 为 BOX 内 P token 数：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `P_pos_box_xyz` | `[N_P,3] float32` | 相对 BOX 原点的 Å 坐标 |
| `P_probability` | `[N_P] float32` | 已冻结语义的 P-head ligand-area 概率 |
| `P_feat_L2` | `[N_P,C_{P2}] float16` | density-box 特征；仅在本次上游路径实际产生时保存 |
| `P_feat_L3` | `[N_P,C_{P3}] float16` | cross-attention 前的 P 特征；仅在实际产生时保存 |
| `P_feat_L4` | `[N_P,C_{P4}] float16` | cross-attention 后的 P 特征；未执行对应模块时不保存 |

`P_probability` 必须在 feature manifest 中说明来自哪个 head，不能保留“base 或 P head 待猜”的语义。P 是 BOX 级伪原子集合，不按 blob 划分，盘上不存在 candidate-P membership。

#### 4.4.2 Group-parent pocket receptor 表

设 `R` 为 parent pocket 原子数，`L_R` 为全部候选 receptor membership indices 拼接长度：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `receptor_atom_global_index` | `[R] int32` | 在第 1 层完整 receptor table 中的全局 index |
| `receptor_binding_probability` | `[R] float32` | Group-parent 局部重跑的受体 binding 概率 |
| `receptor_feat_L1` | `[R,C_{R1}] float16` | receptor embed head 后特征；仅在实际产生时保存 |
| `receptor_feat_L2` | `[R,C_{R2}] float16` | receptor density-box 特征；仅在实际产生时保存 |
| `receptor_feat_L3` | `[R,C_{R3}] float16` | receptor cross-attention 前特征；仅在实际产生时保存 |
| `receptor_feat_L4` | `[R,C_{R4}] float16` | receptor cross-attention 后特征；未执行对应模块时不保存 |
| `candidate_receptor_offsets` | `[N+1] int64` | 每个候选 pocket membership 的区间边界；仅 CLG Group-parent 使用 |
| `candidate_receptor_indices` | `[L_R] int32` | 各候选自己的 pocket 原子在 parent 表中的 indices；仅 CLG Group-parent 使用 |
| `pocket_radius_angstrom` | scalar `float32` | 本产物实际使用的包络半径；第一轮默认 10 Å |

受体坐标、49 维特征、元素/残基和键表由 `receptor_atom_global_index` 回到第 1 层获取，不重复保存。同一候选内部 receptor indices 唯一，不同候选可以共享原子；交叉是合法的。空 P 由 `N_P=0` 表示，空 receptor 子集由相邻 offsets 相等表示；不在磁盘写伪 token。

#### 4.4.3 feature-source manifest

本次上游运行实际保存的每个 `voxel_feat__*`、`P_feat_*` 和 `receptor_feat_*` 字段都必须有来源清单：

| 字段 | 说明 |
|---|---|
| `source_name` | 稳定字段名，例如 `voxel_feat__decoder_pre_head` 或 `P_feat_L3` |
| `entity` | `voxel`、`P_token` 或 `receptor_atom` |
| `producer_module` | 精确到模块出口的来源 |
| `checkpoint_sha256` | 生产 checkpoint |
| `channel_dim` | 通道数 |
| `storage_dtype` | 实际存储 dtype，第一版通常 float16 |
| `coordinate_frame` | 空间实体使用的坐标帧 |
| `semantic_description` | 特征含义，不用“第几层”代替 |

Stage2/3 的 `FuseSources` 从这些稳定来源装配输入。实际字段名及其语义是核心 schema；feature-source manifest 补充生产模块出口、checkpoint、通道数、dtype 与坐标帧。消费者的模型配置直接声明必需字段；缺少必需字段即契约不兼容，不保存或现场制造全零数组来冒充未执行的网络层。

属于 Stage1-Find 主路径的 voxel/P/receptor 字段，其 `checkpoint_sha256` 和模型执行路径必须与上级 `probability_run_id` 一致；更换 Stage1-Find 权重必须先产生新的正式概率图和 `probability_run_id`，不得把新模型特征挂接到旧概率图生成的 tree。可选密度 U-Net 是独立调制器，按 §4.5 记录自己的 checkpoint，不冒充 Stage1-Find 主路径字段。

### 4.5 可选密度 U-Net 特征

Stage1 selector、Stage2 和 Stage3 可以共用一个可关闭的轻量密度 U-Net。原始 exp 密度仍从第 1 层按 BOX 描述子裁剪，不重复存储。该模块有两种运行方式：

1. **模型内现算**：只保存 U-Net checkpoint 与输入归一化 manifest，不增加第 3 层大数组。
2. **冻结后缓存**：把输出作为新的 voxel feature source，沿 §4.2 voxel 表对齐保存。

现有预训练化学特征 U-Net 可以实现同一接口。若复用，它的输出字段命名为例如 `voxel_feat__chem_unet_*`；若另训更轻的密度上下文 U-Net，使用不同 `source_name`、checkpoint hash 和 addon 目录。不得只用同名 `blob_voxel_feat` 覆盖旧产物。

缓存 voxel 特征时不再重复保存一份 `blob_voxel_index`；它直接与 `parent_voxel_index_local_zyx` 对齐。第一版密度上下文调制器只作用于 voxel/密度点，不对 P 或 receptor 做三线性插值调制；点对象调制仅作为后续消融，不进入本契约。

### 4.6 口袋视图

Stage2/3 是否使用预测候选或 GT 输入由运行配置决定，不增加“GT probe”样本身份。

| 口袋类型 | 定义 | 存储 |
|---|---|---|
| **GT ligand atom envelope** | 对所选 GT occurrence 的 present ligand atoms 分别做半径查询，再合并受体原子索引；不保留中心球备选 | Dataset 现场算；每个 worker 缓存 per-PDB receptor `cKDTree` |
| **Group-parent pocket** | 对 Group-parent Global Proposal Mask 的包络选受体原子 | §4.4 parent receptor 共享表 |
| **Candidate pocket** | 对某个 Global Proposal Mask 用同一半径选受体原子 | `candidate_receptor_offsets/indices`，是 parent pocket 的子集；不同候选可交叉 |
| **Selected-final pocket** | 对可选 Refined Mask 或 final proposal 投影定义 | selected-final 自己的独立完整 receptor 表 |

旧的 `pocket_atom_index` 可由：

```text
receptor_atom_global_index[
  candidate_receptor_indices[
    candidate_receptor_offsets[i]:candidate_receptor_offsets[i+1]]
]
```

直接得到。`n_pocket_atoms`、Rg、残基直方图、Wiener index 和 graph energy 均可由候选 receptor membership 与第 1 层 receptor 表直接派生，第一版不物化这些化学/碎片描述子，以减少契约复杂度。

### 4.7 selector score 与 selection result

基础 proposal 数据不能被某次网络推理或某组 calibration 参数覆盖。两类结果分别追加。

#### 4.7.1 selector score addon

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `selector_run_id` | string | checkpoint、模型配置和输入 feature manifest 的联合身份 |
| `selector_manifest_ref` | string + hash | 含 `lambda_count`、在线 oracle 规则、三项 loss 权重、`gamma_focal`、概率 prior、候选属性 recipe 和模型配置 |
| `proposal_run_id` | string | 回指基础 proposal |
| `CLG_run_id` | string | 回指本次使用的 CLG 清单 |
| `materialization_run_id` | string | 回指本次使用的 Group-parent 物化输入 |
| `CLG_id` | scalar `int32` | CLG |
| `CLG_logit` | scalar `float32` | 独立全节点 CLG query/readout 输出的 `a_G` |
| `CLG_valid_probability` | scalar `float32` | `sigmoid(CLG_logit)`，表示 CLG 存在值得选择的非空反链的置信度 |
| `candidate_index` | `[N] int16` | 固定为 `0..N-1`，与基础 CLG 候选数组逐 index 对齐 |
| `candidate_node_id` | `[N] int32` | 必须逐 index 等于基础候选表的 `candidate_node_id` |
| `predicted_max_iou` | `[N] float32` | 逐 blob 最大 GT IoU 的回归输出 `q_hat` |
| `selection_logit` | `[N] float32` | 条件反链能量中的逐候选未归一化选择效用 `z_i`，本身不是概率 |

#### 4.7.2 selection addon

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `selection_run_id` | string | selector score、CLG 门控阈值、原始树非空 DP 与解码配置的联合身份 |
| `selection_manifest_ref` | string + hash | 含 calibration 扫描规则、`M_instance` 曲线、所选 `tau_G`、`lambda_count` 引用和 DP 解码配置 |
| `selector_run_id` | string | 使用哪次候选打分 |
| `CLG_run_id` | string | 回指 selector 使用的 CLG 清单 |
| `materialization_run_id` | string | 必须与 selector run 的物化输入一致 |
| `CLG_id` | scalar `int32` | CLG |
| `CLG_threshold` | scalar `float32` | 本 selection run 使用的 `tau_G`；未校准基线为 0.5，正式值由 calibration 冻结 |
| `CLG_gate_pass` | scalar `bool` | `CLG_valid_probability >= CLG_threshold` |
| `selected_candidate_indices` | `[N_selected] int16` | 门控未通过时为空；通过时是原始组件树上的精确非空 MAP 反链 |
| `selection_score` | scalar `float32` | `sum(selection_logit[selected])-lambda_count*N_selected`；门控未通过时为 0 |

selector 先用独立 `CLG_valid_probability` 门控。门控通过后，条件反链的 log-partition 与非空 MAP 才在当前 CLG 候选 `G` 于完整原始组件树上的最小连接闭包中精确 DP；只有 `i∈G` 的节点可被选择，闭包内其它节点只传递结构状态。不得把同一原树中其它 CLG 的候选纳入本样本，也不落盘 Candidate-induced Tree。反链能量固定为 `sum(z_i)-lambda_count*|S|`。完全同分时接受当前数组/库实现自然返回的任一最大解，不增加自定义 tie-break、稳定排序或跨重跑一致性测试。训练 oracle 由 Dataset worker 在线生成；`lambda_count` 属于 selector 训练身份，正式改变它需要新的 selector 训练，不能只在事后 selection 中偷偷替换。

### 4.8 可选 selected-final refinement

每个被精修候选建立独立推理物化 BOX，并设置 `materialization_role=selected_final`。一个 refinement run 只消费一种 `source_route` 和一个 `source_materialization_run_id`；多阈值与 F1 baseline、或不同来源 materialization run 必须分开运行。该来源写入 refinement/materialization manifest：

| 字段 | shape / 逻辑 dtype | 说明 |
|---|---|---|
| `refinement_run_id` | string | checkpoint、固定原阈值规则、输入 manifest 与 schema 的联合身份；也是本 addon 的 `addon_run_id` |
| `source_route` | enum string | `multi_threshold` 或 `f1_baseline`；必须与本 run manifest 的固定值一致 |
| `selection_run_id` | string or null | 多阈值路线为产生它的 selection run；F1 baseline 为 null |
| `source_CLG_run_id` | string or null | 多阈值路线的来源 CLG run；F1 baseline 为 null |
| `source_CLG_id` | scalar `int32` | 多阈值路线的来源 CLG；F1 baseline 为 `-1` |
| `source_materialization_run_id` | string | 本 refinement run 唯一的来源 materialization run |
| `source_materialization_box_id` | scalar `int32` | 来源 Group-parent BOX 或 F1 baseline BOX |
| `source_candidate_index` | scalar `int16` | 多阈值路线在来源 CLG 内的 candidate index；F1 baseline 为 `-1` |
| `source_tree_id` | scalar `int32` | 原始全图组件树 |
| `source_node_id` | scalar `int32` | 被精修的原始全图节点 |
| `source_threshold_rank` | scalar `uint8` | 精修固定使用的原阈值 |
| `final_voxel_index_local_zyx` | `[K_f,3] int16` | proposal 投影与 refined mask 坐标的并集表 |
| `proposal_voxel_indices` | `[K_p] int32` | Global Proposal 投影进 final BOX 后引用并集表的 indices |
| `refined_voxel_indices` | `[K_r] int32` | 固定阈值局部重跑选出的 refined component 对并集表的 indices |
| `proposal_voxels_total` | scalar `int32` | 原 Global Proposal 总体素数 |
| `proposal_voxels_in_observable_region` | scalar `int32` | 进入 `final BOX ∩ original density grid` 的体素数 |
| `proposal_outside_observable_region_voxel_count` | scalar `int32` | 按候选合法性应为 0；非 0 是契约错误，不能静默裁剪 |
| `refine_status` | enum string | `success`、`empty`、`no_overlap_component` 等显式终态 |
| `threshold_rank_map` | `[80,80,80] uint8` | final 居中重跑的完整局部多阈值观察 |

Selected-final 的每个 `voxel_feat__{source_name}` 固定为 `[K_f,C]`，逐 index 对齐 `final_voxel_index_local_zyx`；不得另造未说明的 voxel 表。它还保存完整 BOX 级 P 表和自己的完整 refined pocket receptor 表，不使用 candidate membership，也不与来源 BOX 特征混用。多个局部组件与原 proposal IoU 同分时，接受当前连通组件遍历自然返回的任一最大值，不叠加额外概率、体积、坐标裁决或稳定性测试。proposal/refined IoU、prompt 和 refined pocket 都可派生。精修失败不得静默覆盖原 Global Proposal；下游显式决定是否回退。F1 baseline 即使启用该可选路径，也不因此创建 CLG、selector 或 selection 身份。

### 4.9 旧字段追溯

对 CLG 的候选 `i`，先定义：

```text
V_i = candidate_voxel_indices[
        candidate_voxel_offsets[i]:candidate_voxel_offsets[i+1]]
R_i = candidate_receptor_indices[
        candidate_receptor_offsets[i]:candidate_receptor_offsets[i+1]]
```

F1 baseline 没有 candidate slice：其 blob 使用完整 parent voxel 表，其 pocket 使用完整 receptor 表。

| 旧字段 | 新契约中的来源 |
|---|---|
| `blob_mask` | CLG 路线为 `parent_voxel_index_local_zyx[V_i]`；F1 baseline 为完整 parent voxel 表 |
| `blob_voxels` | CLG 路线为 `candidate_voxel_offsets` 相邻差；F1 baseline 为 parent voxel 表长度 |
| `prompt_point` | Global Proposal 体素质心转换到世界坐标 |
| `scores` | CLG 路线为 Global Proposal 统计 + 指定 `selector_run_id` 的 `CLG_logit/CLG_valid_probability/predicted_max_iou/selection_logit`；F1 baseline 只有 Global Proposal 统计，不伪造 selector score |
| `provenance` | proposal、materialization、selector、selection、refinement manifests |
| `coverage/atom_coverage` | §4.3 overlap ragged 表 |
| `blob_voxel_index` | CLG 路线为 `parent_voxel_index_local_zyx[V_i]`；F1 baseline 为完整 parent voxel index |
| `blob_voxel_prob` | CLG 路线为 `parent_voxel_global_probability[V_i]`；F1 baseline 为完整 parent probability |
| `blob_voxel_feat` | CLG 路线为 `voxel_feat__{source}[V_i]`；F1 baseline 为完整 parent voxel feature |
| `P_pos/P_prob/P_feat_*` | BOX 级完整 `P_pos_box_xyz/P_probability` 与本次实际保存的具名 `P_feat_*`；所有候选共享 |
| `receptor_atom_index` | CLG 路线为 `receptor_atom_global_index[R_i]`；F1 baseline 为完整 receptor global index |
| `receptor_binding_prob/receptor_feat_*` | CLG 路线按 `R_i` 切完整 receptor 表；F1 baseline 使用完整 receptor 表 |
| `pocket_atom_index` | CLG 路线为 `receptor_atom_global_index[R_i]`；F1 baseline 为完整 receptor global index |
| chemical U-Net voxel feature | 一个命名化 `voxel_feat__{source_name}` |
| refined blob | 仅来自 selected-final 的 `refined_voxel_indices`，不覆盖 Global Proposal |

---

## §5 第 4 层：现场算 + 两条不变量

### 5.1 现场算

- **56 维辅助密度通道**：dataset `__getitem__` 里从第 1 层 exp/sim 在线算（`density_channel_builder`，`{op}_{norm}_{post}` 命名）。
- **`diff`**：`exp − sim` 现场算。
- **O-distance**：Global Proposal mask 体素质心的世界坐标 + `centroid_atom` 现推；不使用共享 BOX 中心。
- **GT ligand atom envelope 口袋**：Stage2/3 Dataset 现场通过每-worker per-PDB receptor `cKDTree` 计算（§4.6）。
- **覆盖矩阵装配**：见 §6。

### 5.2 不变量 A：身份冻结 + materialize 时扰动

- **训练预定位池冻结**：center/bias/context 的候选起点写入 2A 后不回写；同一个预定位可以在不同 epoch 被重复选中。
- **推理物化身份冻结**：2B 的 `box_id/box_start_zyx/shape_zyx/materialization_role` 与来源 run/node 写入后不改。
- **增强是瞬时视图**：仅 Stage1 基础训练在 `ResolvedStage1Crop` materialize 时对选中的起点应用小幅平移/旋转，再从第 1 层同时裁输入和标签；增强结果不落盘、不改变预定位身份。固定 validation 清单不增强、不逐 epoch 重抽。

### 5.3 不变量 B：扰动 ⟺ 放弃第 3 层

第 3 层 blob/coverage 只挂在推理物化 BOX 上。Stage1 的 center/bias/context 增广路径只用第 1 层整图产物与第 2A 层预定位池；Stage2/3 是否读取预测 blob addon 由运行配置决定，无预测 blob 时可改用 §4.6 的 GT ligand atom envelope 现场视图。

---

## §6 覆盖矩阵装配（featurizer 职责，非落盘）

```text
对一张图 P：
  selector 训练行 = 收集 P 的所有 CLG Global Proposal Candidate
  多阈值 Stage2/3 正式行 = 按 selection_run_id 收集各 CLG 的 selected_candidate_indices
  F1 baseline Stage2/3 正式行 = 收集全部合法 f1_baseline BOX 的原始 F1 blob
  列 = P 的全部 occurrence（候选身份 × count 展开成 slot；图级，与 box 无关）
  entry(候选 i, occurrence j):
     读 proposal_occurrence_offsets / overlap 表
     → 命中 j 取其 α/β/O_IoU；未命中 = 0
  → [n_blobs, n_slots] 网格
```

> off-diagonal（merge、负样本）天然可算：只需 `blob_i` 与 `occurrence_j` 各自的量（mask 或中心），**不需要任何 box 级交叉记录**。
>
> 无预测 blob 的 Stage2/3 试水不装配本矩阵；它使用哪些 GT-envelope 输入与监督由运行配置决定，不通过新增样本身份或伪造 blob 来复用本矩阵。selected-final refinement 不改变这张矩阵的行身份；若下游专门评估 Refined Mask，应另算诊断量。

---

## §7 三档与可拆卸

三档 = **同一整图来源与同一 runtime materializer 的不同输入配方**，由 dataset 配方决定激活哪些块；**不是再切出三套盘上 BOX**。

| 档 | Stage1 输入 | Stage2/3 激活的块 | 口袋/空间锚 | 备注 |
|---|---|---|---|---|
| **纯密度档** | `unet_c1` 只读取 1 通道 `exp_clipnorm_nopost` | 第 1 层 density（下游可按自己的配方另建通道）、第 2 层；有预测 blob 时再激活第 3 层 blob/coverage/Stage1 特征 | 由配置选择预测 blob 或 GT ligand atom envelope | Stage1 纯密度基线不读取受体、sim 或 diff |
| **统一档** | Find 读取密度 + 受体 | 上面全部 + 49 维受体特征 + A 侧特征 + 受体几何 | 由配置选择预测 blob 或 GT ligand atom envelope | Stage1 主模型 |
| **"纯受体"档** | **密度 + 受体** | 49 维受体特征 + A 侧特征 + 受体几何；关 PP 特征、关 56 通道密度 | 早期试水可现场用 GT ligand atom envelope；后期消融可用预测 blob | Stage2/3 只消费受体侧 |

可拆卸 = 丢掉 PP 特征退回纯受体、丢掉受体块退回纯密度，**消融和换档是同一个开关**。输入来源和监督同样由配置开关决定；不为“GT envelope / predicted blob”增加样本级身份机制。

### 7.1 两条红线

1. **三档不另立 BOX 来源**：纯受体档**不能**为了“免费拿到位点+口袋”另建 `site+pocket box`。三档都从 2A 预定位或 2B 推理物化身份解析到同一 runtime 请求；口袋只是由配置选择 Global Proposal 包络或 GT ligand atom envelope 后得到的受体切片视图（§8.1）。
2. **输入配方可扩展 ≠ 样本身份后门**：新增特征可走 addon 或 featurizer 配方，但不得为了换档复制一套预定位池、创造新的物化角色或改写样本身份。

---

## §8 四模型对接（docking）

| 模型 | 读什么 | 怎么对接 |
|---|---|---|
| **Stage1 `unet_c1`** | 第 1 层 1 通道原始 exp 密度与直接 `ligand_area_target` | Dataset 按固定 `1:5:3` 迭代 center/bias/context；只做 density→ligand-area |
| **Stage1 Find** | 第 1 层 exp 密度、受体表与直接标签；可 materialize 扰动 | 同一训练预定位池与 runtime builder；CPC1/CPC2 的模型输入和冻结边界由训练计划规定 |
| **Stage1 selector** | 一个 CLG 的 Group-parent voxel/P/receptor 共享表、Global Proposal membership、rank map 派生量和树关系 | 一个 CLG 是一个样本；独立 CLG query 输出 `CLG_logit`，逐 blob 输出 `predicted_max_iou/selection_logit`；先门控真假，再对有效 CLG 在原树上做条件非空反链 DP。F1 baseline 不运行该网络 |
| **Stage2（Match）** | 现场 GT envelope；或多阈值 selected Global Proposal + Group-parent 共享特征/coverage；或直接 F1 baseline blob + 同源局部特征 | 默认不依赖 selected-final；同 PDB 的输入 blob 为行、图级 occurrence 为列。可选读取 Refined Mask 或 voxel 密度上下文特征 |
| **Stage3（Build）** | GT envelope 试水输入；多阈值 selected Global Proposal；或 F1 baseline blob 的 prompt、局部共享特征与受体块 | 默认可直接使用原始全图 proposal；selected-final 是独立形状精修输入，不是前置条件 |
| **轻量密度 U-Net** | 第 1 层原始 exp 密度 | 可模型内现算，或冻结后作为命名 feature source 缓存；selector/Stage2/Stage3 共享接口 |

`ligand_area_target` 不是新的盘上字段：它固定为当前 80³ 请求从第 1 层 union `ligand_area` mask 裁剪并补零后的 `[80,80,80] bool` runtime key。AdaLigand 的 dense loss、validation AP 与 P 监督都消费这个直接二值 target，不生成 `ligand_dist_map`。Find 的精确密度通道清单与 loss 权重由 `文档/规划文档/Stage1训练实现计划.md` 的 resolved config 冻结；本文只规定其整图来源，不复制第二套模型配置。

**无预测 blob 训练的特殊性**：输入与监督由配置决定，GT pocket 统一由 ligand atom envelope 现场生成；它不伪造 blob，也不为样本增加额外模式身份。blob coverage、距离或其它监督是否启用，均属于训练配方，不烤进存储。

### 8.1 口袋 = 以 Global Proposal 为锚的视图（Stage2/3）

有预测候选时，多阈值路线以 selected Global Proposal Mask 的包络为锚，读取其 receptor membership；F1 baseline 直接读取自己 BOX 的完整 receptor pocket。无预测 blob 的早期试水由配置改用 GT occurrence 的 ligand atom envelope；不保留中心球备选。若显式启用 selected-final，消费方可以改用 Refined Mask 自己的独立 pocket。

> 与 Stage1 的区别：Stage1 用 box+buffer（box 为锚，它还不知配体在哪）；Stage2/3 按配置使用 blob 包络或 GT ligand atom envelope。GT envelope 由每-worker 缓存的 per-PDB receptor `cKDTree` 现场计算。

---

## §9 两套位置注册表

### 9.1 训练预定位角色（2A）

| 角色 | 来源 | 预生成规模 | 每 epoch 使用方式 |
|---|---|---|---|
| **center** | 从 occurrence `mask_{cid}` 求 mean ZYX index，再经统一 half-up helper 得到严格居中的 80³ 起点；若实现从 `centroid_voxel_{cid}` 出发，必须先按权威 origin/voxel 做 world XYZ→corner voxel XYZ→ZYX 转换 | 每 occurrence 1 个 | 全部使用；再应用在线小幅平移/旋转增强 |
| **bias** | 在 center 上按 §9.2 配方产生偏移起点 | 每 occurrence 默认 15 个候选 | 每 occurrence 重抽 5 个；再用同一在线增强配方 |
| **context** | 随机起点，裁剪后受体重原子数至少 `N_context_min=1000` | 每 PDB 目标 500 个，最多尝试 3000 次 | 全训练集本 epoch 总共抽取 `3 × occurrence 总数` 个；再用同一在线增强配方 |

三类是三个紧凑数组，不需要额外 `box_type` 字段。训练 epoch 的全局数量关系固定为 `center:bias:context = 1:5:3`；validation 永久冻结一份无增强、不会逐 epoch 重抽的 `1:5:3` 清单。预定位只负责“先把大致位置准备好”，不携带正负语义；监督始终从增强后的真实裁剪现场取得。

### 9.2 bias 偏移配方（候选池预生成）

```text
1. 采样概率场 = 高斯衰减(从 GT ligand-area 中心) ∩ ligand-area（区域外为 0）
2. 在该场里采一点，取其相对中心的位移 d
3. 偏移 = 比例 × d + floor
   - 比例项随配体尺寸自适应（支撑集就是配体区域，截断保证偏移点落在配体内）
   - floor ~ 某【全局】固定分布的随机量（保证小配体也有非平凡偏移；不再对配体自适应——采样场已适应过一次）
4. clamp 保证配体仍在 box 内
```

> 比例、floor 分布、阈值的具体数值待标定（可对着 Find 实际定心误差校准）。

### 9.3 推理物化角色（2B）

| `materialization_role` | 来源 | 用途 |
|---|---|---|
| `CLG_group_parent` | `CLG_run_id + CLG_id` | selector 的共享局部特征与候选 membership |
| `f1_baseline` | `proposal_run_id + tree_id + node_id` | 粗糙单阈值基线与同源局部特征 |
| `selected_final` | `refinement_run_id` 及其完整来源字段 | 可选的局部形状精修；不覆盖 Global Proposal |

这些角色共享同一推理物化描述子和 addon 接口，但不是训练预定位池的一部分。增加新 addon 不需要增加新角色；只有确实出现新的局部物化生命周期时，才扩展 `materialization_role`。

---

## §10 与 featurizer / 模型输入契约的接缝

三层逻辑必须分开（"算子与数据输入分离"）：

1. **盘上数据契约**（本文）：BOX 存按来源分开的块。
2. **模型输入契约 / featurizer**（见 `文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md §4`）：按“某模型 + 某档”的配方，把块拼成模型张量视图（含 §6 矩阵装配）。
3. **模型算子**（见同一迭代运算文档）：只看拼好的张量，不知盘上长什么样。

**继承的原则与可复用叶子**（代码可重写、原则/叶子保留）：

- **原则**：训练侧与推理侧严格共用同一个 crop/builder/collate 处理路径，靠同一条实际调用链强制两边契约一致。差别只在起点来源和 sampler：训练读取 2A 的 center/bias/context 紧凑数组；整图推理按 map shape、window size、stride 和样本索引公式产生窗口起点。
- **可直接当库用的纯叶子**（与配体种类零耦合）：`box_geometry`（选框内+buffer 原子、三套坐标、hardmask、按索引切特征）、`density_channel_builder`（按 model recipe 在线构造；`unet_c1` 只有 1 通道 `exp_clipnorm_nopost`，Find 沿用当前成熟配方）。
- **要重写的耦合层**：旧 `box_point_dataset` 按配体种类分文件夹/分 split/平衡采样那一套改为读取 §3.1 训练预定位池；推理滑窗按索引公式即时解析请求，不预先构造完整 `box_dicts` 列表。
- **流水线职责**：DataLoader worker 负责整图读取、BOX 裁剪和按 model recipe 构造输入通道；概率 BOX 合并与完整图后处理使用独立可配置 worker/有界队列，以便与 GPU forward 或下一张图的处理重叠。不得让多个进程无协调地写同一张概率 accumulator。
- **非依赖项**：`pin_memory` 的开关由成熟 resolved config 与 profiling 决定，不是科学契约或 CPU/GPU 重叠成立的前提；固定形状 BOX 不增加 `voxel_valid_mask` 字段；少量 voxel size 非严格等方的样本不因旋转增强增加硬门禁或抛异常。

### 10.1 冷读验证不变量

每个正式产物必须通过以下检查：

- `probability_run_id` 能解析 probability manifest 与必需的完整 `float32` 概率产物；`proposal_run_id` 能解析其上级 `probability_run_id`、组件树引用和阈值表；`CLG_run_id` 能解析其上级 `proposal_run_id`、枚举配置与 CLG 清单。
- 每个 `materialization_run_id` 只声明一种 role，并能解析直接上级、Find checkpoint/执行路径与 per-PDB index；`box_id` 必须等于当前 per-PDB 表行号。selected-final run 的 `source_materialization_run_id/box_id` 必须能回读到来源 BOX。
- 每个 per-BOX addon 都能由 `(addon_name,addon_run_id,materialization_run_id,pdb_id,box_id)` 唯一寻址；addon manifest 绑定该 materialization run，且其中的 per-PDB entry 数与内容哈希和实际压缩产物一致。
- `box_start_zyx`、派生 BOX 世界原点与完整网格几何必须通过坐标 parity 放行后的同一 materializer 一致性检查；从 BOX 与完整网格交集冷读并补零后 shape 必须恰为 `shape_zyx`，不做 clamp 或平移。
- 推理 proposal 的完整 mask 严格位于 `BOX ∩ original density grid` 内部；对每个面使用 §4.2.4 的统一边界审查规则。
- 一个 CLG 只有一个 `group_parent_candidate_index`，且该 index 的 `candidate_node_id` 等于 `group_parent_node_id`。
- 所有 candidate voxel/receptor indices 均在 parent 表范围内，同一候选内部唯一；不同候选可交叉。全部候选读取完整 P 表，盘上没有 candidate-P membership；不要求额外稳定排序。
- 每个 offsets 数组首值为 0、单调不降、末值等于对应 indices/value 数组长度：candidate offsets 长度为 `N+1`，`proposal_occurrence_offsets` 长度为 `N_proposal+1`，`atom_coverage_offsets` 长度为 `E+1`。
- 每个候选 Global Proposal Mask 都是 Group-parent Mask 的子集。
- `threshold_rank_map` 的值只属于 `0..T-1` 或 255。
- `lca_distance_from_i/j` 与原始组件树一致，且能正确恢复反链冲突。
- selector score、selection 与 refinement 都通过各自 manifest 中的上游 run ID 回指同一个 Global Proposal Node。
- selector score 的 `candidate_index` 严格为 `0..N-1`，`candidate_node_id/predicted_max_iou/selection_logit` 与基础 CLG 候选数组逐 index 对齐；`CLG_logit/CLG_valid_probability` 每个 CLG 各一个。门控未通过时 selection indices 为空；通过时必须构成非空反链且只能索引该候选数组。
- F1 baseline 没有 CLG 候选表、LCA、selector 或 selection addon，但具有完整原始 F1 mask、同源 voxel/P/receptor 特征和 overlap，可独立构造 Stage2/3 输入。
- selected-final 缺失时，多阈值路线由 Group-parent materialization + Global Proposal + selection addon 构造 Stage2/3 输入；F1 baseline 直接由自身 BOX 构造。
- `validation_selection.npz` 的所有 bias/context 引用均在对应 pool 范围内，entry 数严格为 `5*O_val` 与 `3*O_val`，重复读取顺序与内容不变。
- 所有 NPZ 产物能证明由 `np.savez_compressed` 或语义等价的压缩容器写出，且不含 object array/pickle。
- 旧字段追溯表中的每一项都能在不读取历史文件的情况下还原。

---

## §11 待定与维护

**待定（实现时定）**：

1. 第 3 层变长 membership 逻辑字段已经固定为 `offsets + indices`；第一版 NPZ 使用 `np.savez_compressed`，是否迁移到同样支持压缩的 Zarr 或其它容器待 IO benchmark。
2. bias 的比例与 floor 分布、距离-O 的 `ρ`、IoU-O 的 `τ`、覆盖条目入选阈值——先看分布再定；context 的 `500/3000/N_context_min=1000` 已冻结。
3. ~~`centroid_atom` 是否物化~~ **已定物化进 `ligand_coords.npz`**（C4 产，§2.2）。
4. voxel/P/receptor 实际导出字段的精确源码出口、通道数与 storage dtype；消费者所需字段由模型配置明确声明。
5. 推理物化 BOX 是否回填某种 occurrence 锚（默认不填，靠覆盖/距离）。
6. 默认 10 Å pocket 半径的邻近消融；候选 receptor membership 参数必须进入 manifest。
7. 轻量密度 U-Net 采用现算还是冻结缓存，由 profiling 与下游实验决定；两种方式共享 feature-source 接口。

**维护**：实现后用真实产物验证字段、dtype、shape 和不变量；发现漂移先按 `AGENTS.md` 审计并请求用户决定，再更新本文、正式 Stage1 计划、mapping 与下游指针。本文仍是 BOX 级盘上契约的唯一权威，事实只写一遍。
