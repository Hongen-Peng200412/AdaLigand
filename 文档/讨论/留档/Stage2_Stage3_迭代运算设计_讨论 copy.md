# AdaLigand Stage2 / Stage3 迭代运算设计

> **本文定位**：本文是 `模型总规划_v2.md` 的**运算模块说明书**。`模型总规划_v2.md` 讲"匹配要预测什么、损失怎么定义、数据怎么切"（**是什么**）；本文讲"这些表示如何一层层算出来、用哪些算子、Stage2/Stage3 如何共用同一套代码"（**怎么算**）。两文合起来自包含；本文在运算层面尽量自包含（术语见 §1/§2，每个首次出现即定义）。
> **命名规则**：特征张量 `snake_case` + 后缀（`_features`/`_coords`/`_logit`/`_target`/`_probability`/`_index`/`_mask`）+ 标注 `[形状]`；算子 `PascalCase`，给"签名 / 定义 / 是否用几何 / 是否等变 / 是否更新坐标 / 成本"。所有方法表达成同一组交互原语，便于与 `参照算法_迭代运算梳理_AF3_PocketXMol.md` 对照。
> **第一版实现边界**：context 图算子只实现 **gated 消息传递（PocketXMol 式）**；配体内部**直接复用 Emap2lig PairFormer**；跨集合复用并适配 Emap2lig `SelectedCrossAttention`；不实现等变坐标更新 / 3D RoPE / softmax 版 context 图（皆作消融或钩子）。

---

## §1 特征张量词典

| 名称 | 形状 | 含义 |
|---|---|---|
| `ligand_atom_features` | `[n_slots, max_ligand_atoms, d_model]` | 配体（CCD）原子表示。批维 = slot（一个身份的一个副本）。 |
| `ligand_pair_features` | `[n_slots, max_ligand_atoms, max_ligand_atoms, d_pair]` | 配体原子对表示（化学键、参考构象距离）。 |
| `ligand_atom_mask` | `[n_slots, max_ligand_atoms]` | 真实原子=True，padding=False。 |
| `ligand_atom_coords` | `[n_slots, max_ligand_atoms, 3]` | **仅 Stage3**：扩散噪声坐标。Stage2 不存在。 |
| `slot_index_embedding` | `[n_slots, d_model]` | 身份内副本索引 `e_s` 的可学习嵌入（同身份的 N_j 个 slot 互相区分；见 `模型总规划_v2.md` §6 身份内匈牙利）。 |
| `density_point_features` | `[n_blobs, max_density_points, d_model]` | 密度点（PP）表示。批维 = blob。 |
| `density_point_coords` | `[n_blobs, max_density_points, 3]` | 密度点 map 帧坐标。 |
| `receptor_atom_features` | `[n_blobs, max_receptor_atoms, d_model]` | 受体口袋原子表示。 |
| `receptor_atom_coords` | `[n_blobs, max_receptor_atoms, 3]` | 受体原子 map 帧坐标。 |
| `receptor_binding_probability` | `[n_blobs, max_receptor_atoms]` | Stage1 预测的"该受体原子在配体 4Å 内"的概率，作受体节点输入特征（F1≈0.65，比 ligand-area 0.55 更准）。 |
| `context_node_features` | `[n_blobs, max_context_nodes, d_model]` | **合并定位点集** = 拼接(密度点, 受体原子)；`max_context_nodes = max_density_points + max_receptor_atoms`。 |
| `context_node_coords` | `[n_blobs, max_context_nodes, 3]` | 合并点集坐标。 |
| `context_node_type` | `[n_blobs, max_context_nodes]` | 类型 ∈ {`density`, `receptor`}。决定算子里的类型专属投影。 |
| `context_edge_index` | `[n_blobs, 2, max_context_edges]` | 稀疏异构图的边。边集 = {密度-密度: 无；受体-受体: 共价键 ∪ radius；密度-受体: radius}。 |
| `context_edge_features` | `[n_blobs, max_context_edges, d_edge]` | 边特征：距离的 GaussianSmearing ⊕ 节点类型对 ⊕（受体键型）。 |
| `coverage_recall_logit` | `[n_blobs, n_slots]` | 预测 α̂：配体被该 blob 捕获的比例（recall 方向）。 |
| `coverage_precision_logit` | `[n_blobs, n_slots]` | 预测 β̂：该 blob 被配体解释的比例（precision 方向）。 |
| `coverage_recall_target` | `[n_blobs, n_occurrences]` | 标签 α = \|blob ∩ occ_mask\| / \|occ_mask\|。 |
| `coverage_precision_target` | `[n_blobs, n_occurrences]` | 标签 β = \|blob ∩ occ_mask\| / \|blob\|。 |
| `blob_summary_features` | `[n_blobs, d_model]` | 每 blob 的代表向量（给 level-3 全图集合层）。 |
| `slot_summary_features` | `[n_slots, d_model]` | 每 slot 的代表向量。 |
| `blob_is_real_logit` | `[n_blobs]` | 辅助头：该 blob 是否对应真实 occurrence（反假阳）。 |
| `slot_is_present_logit` | `[n_slots]` | 辅助头：该 slot 的 occurrence 是否真存在（用于 count 可能多给时的"幻影 slot"判别）。 |
| `ligand_atom_covered_logit` | `[n_blobs, n_slots, max_ligand_atoms]` | 辅助头：逐配体原子"被该 blob 密度覆盖"。 |
| `density_point_belongs_logit` | `[n_blobs, n_slots, max_density_points]` | 辅助头：逐密度点"属于该配体"。 |
| `binding_probability_logit` | `[n_blobs, max_receptor_atoms]` | 辅助头：重预测受体结合原子（反向监督 `receptor_binding_probability`）。 |

> `n_slots = Σ_j N_j`（总副本数 = 总 occurrence 数）。所有张量都按"整图一个样本"批量；多图再加一层 batch 维（略）。

---

## §2 算子词典（交互原语）

### 2.0 导言：两大族、我们各取一段、为什么

把"两个集合内部/之间如何交换信息"分两族：

- **(i) 注意力 + 显式 pair**（AF3 / Emap2lig）：`softmax(query·key + 偏置)` 加权求和；pair/几何作偏置。
- **(ii) 稀疏消息传递**（PocketXMol / DiffDock）：逐边算消息、门控或张量场、`scatter_sum` 聚合；可更新边、可更新坐标。

**我们的分工不是二选一，而是按子任务各取最合适的一段，且都落在"非等变标量特征"上**（因为 Stage2 预测的是覆盖**标量**——旋转/平移不变量，**不需要等变机制**；Stage3 也走 Emap2lig 的非等变注意力扩散）：

| 子步骤 | 用哪族 | 理由 |
|---|---|---|
| **context 图（PP∪A 内部 + 跨边）** | (ii) **gated 消息传递** | 密度点云要"点越多=密度越强"的**累加式**聚合（softmax 会归一化掉密度），且距离应**乘性**塑造消息——两者都是 MP 的长处；受体稀疏键图也天然是 MP。 |
| **配体内部** | (i) **PairFormer** | 配体是小的化学图，三角更新 O(n³) 可接受；**直接复用 Emap2lig**。 |
| **配体 ↔ context（跨集合）** | (i) **cross-attention** | 配体在 Stage2 无坐标，只能特征空间注意力；**复用并适配 Emap2lig `SelectedCrossAttention`**。 |

**第一版只实现上表用到的算子**。softmax 版 context 图、等变坐标更新、3D RoPE、DiffDock 张量场，均作消融或钩子（§10）。

### 2.1 `SparseGraphInteraction`（context 图算子；第一版 = gated 消息传递）

`context_node_features ← SparseGraphInteraction(context_node_features, context_edge_index, context_edge_features, context_node_type)`

- **定义**（逐边消息 + 门控 + 求和聚合，PocketXMol `NodeBlock` 式）：
  ```
  对每条边 (i←j)：
    msg_ij   = message_mlp( edge_mlp(context_edge_features_ij) ⊙ node_mlp[type_j](context_node_features_j) )
    gate_ij  = sigmoid( gate_mlp(context_edge_features_ij, context_node_features_j) )
  aggregated_i = scatter_sum_j( gate_ij * msg_ij )            # 不归一化：邻居越多累加越强
  out_i = context_node_features_i + out_transform( layer_norm( centroid_lin[type_i](context_node_features_i) + aggregated_i ) )
  ```
  `node_mlp[type]` / `centroid_lin[type]`：**按 `context_node_type`（密度/受体）用不同投影参数**（=类型专属投影，处理 PP/A 异构）。
- **用几何**：是（通过 `context_edge_features` 里的距离 GaussianSmearing，间接）。
- **等变**：否（节点是标量特征）。**更新坐标**：**否**（context 点位置固定）。
- **成本**：O(n_edges)。
- **Stage2/Stage3 通用**：两阶段的 context 都是固定的密度+受体，无坐标更新，故**同一算子、同一权重结构**直接服务两阶段（满足"算子可用于 Stage3"）。
- **消融钩子**：把"门控求和"换成"softmax 注意力"即 (i) 族版本（同一图、同一边）；不在第一版。

### 2.2 `BiasedSelfAttention`（配体内部自注意力组件）

`node_features ← BiasedSelfAttention(node_features, attention_bias=None)`

- **定义**：节点自注意力，`attention_bias` 由 {pair 特征投影、相对坐标投影} 组装后加到注意力 logit；`None` 则为普通自注意力。
- **用几何**：可选（若 bias 含相对坐标）。**等变**：否。**更新坐标**：否。成本：O(n²)。
- **说明**：它是 Emap2lig PairFormer 里 `AttentionPairBias` 的抽象；我们**不单独重写它**，见 §2.5。

### 2.3 `CrossAttention`（配体 ↔ context 跨集合）

`query_features ← CrossAttention(query_features, keyvalue_features, query_coords=None, keyvalue_coords=None)`

- **定义**：query 集合对 keyvalue 集合 cross-attention。**给坐标且同帧 → 加相对位置偏置（几何）；不给 → 纯特征空间**。残差更新 query。
- **用几何**：可选（Stage2 不给坐标=否；Stage3 给配体噪声坐标=是）。**等变**：否。**更新坐标**：否。成本：O(n_query · n_keyvalue)。
- **说明**：**复用并适配 Emap2lig `SelectedCrossAttention`**——它本是"配体原子 attend 选中密度点"，Stage2 把它对配体坐标的位置编码关掉（`query_coords=None`），Stage3 留开。

### 2.4 `OuterProductMeanToPair` / `TrianglePairUpdate`（配体 pair 轨）

- `pair_update ← OuterProductMeanToPair(node_features)`：节点外积均值 → 写回 pair。
- `pair_features ← TrianglePairUpdate(pair_features)`：三角乘法 + 三角注意力，用第三节点 k 更新对 (i,j)。成本 O(n³)，仅配体（小）划算。
- **说明**：也是 PairFormer 组件，不单独重写，见 §2.5。

### 2.5 `LigandPairFormer`（= 直接复用 Emap2lig `PairFormer`）

`ligand_atom_features, ligand_pair_features ← LigandPairFormer(ligand_atom_features, ligand_pair_features, ligand_atom_mask, ligand_pair_mask)`

- **定义**：`BiasedSelfAttention`(=AttentionPairBias) + `OuterProductMeanToPair` + `TrianglePairUpdate`(=TriangleMultiplication out/in + TriangleAttention start/end) + Transition，堆 `num_blocks` 层。
- **复用边界（死条件已核）**：`emap2lig/model/modules/pairformer.py::PairFormer` 的接口 `(atom_feats, pair_feats, atom_mask, pair_mask)` 直接吃我们的配体张量（批维=slot），**至多改 config（维度/层数）**。→ **直接 import，不重写**。

### 2.6 `LearnedQueryReadout`（集合 → 向量/标量）

`vector ← LearnedQueryReadout(item_features, item_mask)`（再接 `scalar ← Sigmoid(MLP(vector))`）

- **定义**：一个可学习查询向量对 `item_features`（按 mask）cross-attention 池化成 1 向量；接 MLP 出标量。即学出来的加权池化。

---

## §3 三种实体与位置不对称

| 实体 | 主特征 | 坐标 | 内部边 |
|---|---|---|---|
| 配体原子（1 slot） | `ligand_atom_features` | 仅 Stage3 有 `ligand_atom_coords` | `ligand_pair_features`（化学） |
| 密度点（1 blob） | `density_point_features` | `density_point_coords`（map 帧） | 无（默认） |
| 受体原子（1 blob 口袋） | `receptor_atom_features` + `receptor_binding_probability` | `receptor_atom_coords`（map 帧） | 键 ∪ radius |

**位置不对称（反作弊，见 `模型总规划_v2.md` §1.4）**：密度↔密度/密度↔受体/受体↔受体**同帧**（`context_edge_features` 含相对几何）；**跨到配体**——Stage2 配体无坐标 ⇒ `CrossAttention(query_coords=None)`（纯特征空间，给坐标即泄露 GT）；Stage3 配体有噪声坐标 ⇒ `CrossAttention(query_coords=ligand_atom_coords)`（几何）。

---

## §4 共享迭代块（批量、无 Python 循环）

把密度点与受体原子拼成异构定位点集 `context_node_features`（类型 `density`/`receptor`，边集 {密-密无 / 受-受键∪radius / 密-受radius}）。一个迭代块：

```python
# 开关：stage ∈ {"Stage2","Stage3"}; use_receptor ∈ {True,False}; couple ∈ {"decoupled","light","full"}

# 步骤 1：context 图更新（gated 消息传递；批维 = n_blobs；不动坐标）
#   use_receptor=False ⇒ context 只含密度点 ⇒ 退化为密度点 radius 图 ⇒ 接近 Emap2lig
context_node_features = SparseGraphInteraction(
        context_node_features, context_edge_index, context_edge_features, context_node_type)

# 步骤 2：配体内部更新（复用 Emap2lig PairFormer；批维 = n_slots）
ligand_atom_features, ligand_pair_features = LigandPairFormer(
        ligand_atom_features, ligand_pair_features, ligand_atom_mask, ligand_pair_mask)

# 步骤 3：配体吸收 context（cross-attention；逐 (blob, slot) 对 —— 批量在 [n_blobs, n_slots] 网格上）
ligand_atom_features = CrossAttention(
        query_features    = ligand_atom_features,                      # [n_slots, max_lig, d]
        keyvalue_features = context_node_features if use_receptor else density_point_features,  # [n_blobs, *, d]
        query_coords      = (ligand_atom_coords if stage=="Stage3" else None),
        keyvalue_coords   = (context_node_coords if stage=="Stage3" else None))
# 实现：在 [n_blobs, n_slots] 两个前置批维上做一次批量注意力，scores [n_blobs, n_slots, max_lig, max_ctx]，
#       flash-attn + mask，无循环。

# 步骤 4：context 反向吸收配体（可选；couple != "decoupled"；逐对）
if couple != "decoupled":
    context_node_features = CrossAttention(
            query_features = context_node_features, keyvalue_features = ligand_atom_features)
```

- **步骤 1 批维 = n_blobs，步骤 2 批维 = n_slots，步骤 3/4 批维 = `[n_blobs, n_slots]` 网格**。所谓"逐对"只是张量前置批维（如 25×45 → `[25,45,...]`），**不是 Python 循环**。
- 步骤 1、2 跨对复用（context per-blob、ligand per-slot 各算一次）；步骤 3、4 是承重逐对项。
- **`couple` 决定逐对耦合深度**：`decoupled`（只末端一次 step3 读出）/`light`（末端几层 step3+step4）/`full`（每块 step1~4，单对，Stage3 用）。

---

## §5 Stage2 前向（批量 `[n_blobs, n_slots]`）

```python
# ---- 共享前段（trunk，无循环） ----
for _ in range(L_context):  # 对所有 blob 批量
    context_node_features = SparseGraphInteraction(context_node_features, context_edge_index,
                                                   context_edge_features, context_node_type)
for _ in range(L_ligand):   # 对所有 slot 批量
    ligand_atom_features, ligand_pair_features = LigandPairFormer(...)
for _ in range(L_pair):     # couple="light"：末端几层逐对（[n_blobs, n_slots] 网格批量）
    ligand_atom_features_grid = CrossAttention(ligand_atom_features, context_node_features,
                                               query_coords=None, keyvalue_coords=None)

# ---- 覆盖读出（两条分参数、分方向的头；批量网格） ----
ligand_after_density = CrossAttention(ligand_atom_features, density_point_features, query_coords=None)  # 只用密度点
coverage_recall_logit = Sigmoid(MLP_recall(LearnedQueryReadout(ligand_after_density, ligand_atom_mask)))     # [n_blobs, n_slots]，配体侧池化 → α̂
density_after_ligand = CrossAttention(density_point_features, ligand_atom_features)
coverage_precision_logit = Sigmoid(MLP_precision(LearnedQueryReadout(density_after_ligand, density_point_mask)))  # [n_blobs, n_slots]，密度侧池化 → β̂

# ---- 逐原子/逐点辅助头（读出池化之前） ----
ligand_atom_covered_logit  = Sigmoid(MLP_cov(ligand_after_density))   # [n_blobs, n_slots, max_lig]
density_point_belongs_logit = Sigmoid(MLP_bel(density_after_ligand))  # [n_blobs, n_slots, max_dp]
binding_probability_logit  = Sigmoid(MLP_bind(receptor_atom_features))# [n_blobs, max_ra]  反向监督受体结合概率

# ---- level-3 全图视野（explaining-away；几十 token，便宜） ----
blob_summary_features = LearnedQueryReadout(context_node_features, context_node_mask)   # [n_blobs, d]
slot_summary_features = LearnedQueryReadout(ligand_atom_features, ligand_atom_mask) + slot_index_embedding  # [n_slots, d]
set_tokens = concat(blob_summary_features, slot_summary_features)                       # 整图所有 blob+slot
for _ in range(L_set):
    set_tokens = BiasedSelfAttention(set_tokens)        # 全图自注意 → 软 explaining-away
blob_summary_features, slot_summary_features = split(set_tokens)
# 用更新后的 summary 给覆盖 logit 加偏置修正：
coverage_recall_logit    += BiasHead_recall(blob_summary_features[:,None,:], slot_summary_features[None,:,:])
coverage_precision_logit += BiasHead_precision(blob_summary_features[:,None,:], slot_summary_features[None,:,:])

# ---- summary 实质参与监督（不是只 feed-forward） ----
blob_is_real_logit    = MLP_blob(blob_summary_features)   # [n_blobs]  反假阳
slot_is_present_logit = MLP_slot(slot_summary_features)   # [n_slots]  幻影 slot 判别
```

**B（precision）的来路**：密度点当 query、密度侧池化的 `coverage_precision_logit`，与 A（配体当 query、配体侧池化）分参数、分方向，对称对应标签 `α/β`。受体不进覆盖读出（覆盖是密度量），只在 trunk 富集表示 + 出 `binding_probability_logit`。

---

## §6 Stage3 前向（批量 `[B_pairs]` × 扩散步；context 缓存）

```python
# Stage3 训练/采样：堆叠多个独立 (blob, ligand) 对成 batch [B_pairs]，外层循环扩散步
# ---- context 与配体内部：不依赖配体噪声坐标，跨扩散步缓存一次 ----
for _ in range(L_context):
    context_node_features = SparseGraphInteraction(...)            # 同 §2.1，同算子，批维 = B_pairs
for _ in range(L_ligand):
    ligand_atom_features, ligand_pair_features = LigandPairFormer(...)
context_cache = (context_node_features, ligand_pair_features)      # 缓存

# ---- 扩散循环（每步重算依赖噪声坐标的部分） ----
for t in diffusion_steps:
    h = ligand_atom_features
    for _ in range(L_pair):
        h = CrossAttention(h, context_node_features,
                           query_coords=ligand_atom_coords_t, keyvalue_coords=context_node_coords)  # 几何开
    ligand_atom_coords_t = DiffusionDenoiseHead(h, ligand_atom_coords_t, context_cache)  # 复用 Emap2lig 扩散头
# use_receptor=False ⇒ context 只剩密度点 ⇒ 精确退回 Emap2lig
```

- **Stage2 vs Stage3 算力结构**：Stage2 = `[n_blobs × n_slots]`（~25×45）网格 × **1 次前向**；Stage3 = `[B_pairs]` × **n_diffusion_steps** 次前向，且 **context+配体内部缓存一次**、每步只重算"几何 cross-attn + 去噪头"——**Stage3 主算力在扩散循环上**。两边都无"丑陋 pair 循环"（Stage2 批量网格、Stage3 本就单对成 batch）。
- **同一套算子**：`SparseGraphInteraction` / `LigandPairFormer` / `CrossAttention` 在两阶段字面相同，只切 `query_coords`（几何开关）与批量维度。

---

## §7 开关与塌缩表

| 配置 | 结果 |
|---|---|
| `use_receptor=False, stage="Stage3", couple="full", 扩散读出` | **Emap2lig（Stage3 下限）** |
| `use_receptor=False, stage="Stage2", 覆盖读出` | Emap2lig 的"无受体匹配"变体 |
| `use_receptor=True` | 加受体（结合概率 + 稀疏键图 + 跨边 radius 耦合） |

Stage2/Stage3 三处差异：① `stage`（`CrossAttention` 是否给坐标）；② 批量维度与 `couple`（网格 vs 单对×扩散步）；③ 读出头（覆盖 vs 扩散）。

---

## §8 监督全清单

| 损失 | 来源 | 说明 |
|---|---|---|
| `Loss_coverage` | `coverage_recall_logit`/`coverage_precision_logit` vs `α/β` | 软回归 + 阈值二值化 focal；slot↔occurrence 走身份内匈牙利（`模型总规划_v2.md` §6） |
| `Loss_binding` | `binding_probability_logit` vs GT 4Å | 受体结合概率反向监督（辅助、近零成本正则） |
| `Loss_blob_is_real` | `blob_is_real_logit` vs (blob 是否命中真 occurrence) | summary 反假阳 |
| `Loss_slot_is_present` | `slot_is_present_logit` | 仅当 count 可能多给（幻影 slot）时有效 |
| `Loss_atom_covered` / `Loss_point_belongs` | 逐原子/逐点辅助头 vs GT 覆盖 | 细粒度对齐（可选） |
| 深监督（可选） | 每块都接覆盖读出，折扣权重求和 | 默认只末块，留开关 |

总损失 = 加权和；权重经验定。

---

## §9 Emap2lig 复用映射表

| 我们的部件 | Emap2lig 来源 | 复用方式 |
|---|---|---|
| 步骤 2 `LigandPairFormer` | `modules/pairformer.py::PairFormer` | **直接 import**，至多改 config |
| 步骤 3 `CrossAttention` | `layers/selected_attention.py::SelectedCrossAttention` | 适配：Stage2 关配体坐标 PE，Stage3 留 |
| PP 采样 | `model/modules/instance_seg.py::select_top_k_points` | 直接复用（top-k 体素 gather） |
| Stage3 `DiffusionDenoiseHead` | `modules/diffusion.py::AtomDiffusion` | 复用（受体作额外条件） |
| 步骤 1 `SparseGraphInteraction` | 无（参照 PocketXMol `models/graph.py::NodeBlock`，**去掉坐标更新**） | 自写小模块 |

---

## §10 待定旋钮与消融（非第一版）

1. context 图算子：`softmax` 版（注意力族）对照默认 gated-MP。
2. `couple`：`light`（默认）/`decoupled`/`full`。
3. PP 升级：短卷积/3³ 插值取初始特征 + CryoAtom 式构造边（默认关）。
4. 几何注入：默认加性相对位置偏置；**3D RoPE 留钩子、不实现**。
5. 等变坐标更新 / DiffDock 张量场：**排除**（Stage2 预测不变标量、不需等变；与 Emap2lig 栈不兼容）。
6. 深监督、各辅助头权重、PP↔P 融合（见 `模型总规划_v2.md` §3）。

> 横向对照（AF3 / PocketXMol / DiffDock / Emap2lig 用同一套算子）见 `参照算法_迭代运算梳理_AF3_PocketXMol.md`。
