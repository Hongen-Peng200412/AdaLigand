# AdaLigand Stage2 / Stage3 迭代运算设计

> **本文定位**：`模型总规划_v2.md` 的**运算模块说明书**。前者讲"匹配预测什么、损失/数据/解码怎么定义"（**是什么**）；本文讲"这些表示如何一层层算出来、用哪些算子、Stage2/Stage3 如何共用代码"（**怎么算**）。两文合起来自包含；本文在运算层面自包含（术语见 §1/§2，首次出现即定义）。 **命名规则**：特征张量 `snake_case` + 后缀（`_features`/`_coords`/`_logit`/`_target`/`_probability`/`_index`/`_mask`/`_repr`）+ 标注 `[形状]`；算子 `PascalCase`，给"签名 / 定义 / 是否用几何 / 是否等变 / 是否更新坐标 / 成本"。 **核心结构（本版定稿）**：匹配分**细分支**（逐对全量 cross-attn，info-rich 但 set-blind）与**粗分支**（压缩代表向量做集合推理，提供全局先验且可分 chunk），两支的码并进打分 MLP。Stage2 的逐对 cross-attn **只读不写回**共享表示；Stage3 写回（条件化）后接扩散。 **第一版实现边界**：context 图只实现 gated 消息传递（A-only）；配体内部直接复用 Emap2lig `PairFormer`；跨集合复用并适配 Emap2lig `SelectedCrossAttention`；不实现等变坐标更新 / 3D RoPE / softmax 版 context 图（皆消融或钩子）。

---

## §1 特征张量词典

| 名称 | 形状 | 含义 |
| --- | --- | --- |
| ligand_atom_features | [n_slots, max_ligand_atoms, d] | 配体原子表示（PairFormer 产出；细分支里作 query，Stage2 全程不被密度更新）。批维 = slot。 |
| ligand_pair_features | [n_slots, max_ligand_atoms, max_ligand_atoms, d_pair] | 配体原子对（化学键 / 参考距离）。 |
| ligand_atom_coords | [n_slots, max_ligand_atoms, 3] | 仅 Stage3：扩散噪声坐标。 |
| slot_index_embedding | [n_slots, d] | 身份内副本索引 e_s（身份内匈牙利，见 模型总规划_v2.md §6）。 |
| density_point_features | [n_blobs, max_density_points, d] | 密度点（PP）表示。批维 = blob。 |
| density_point_coords | [n_blobs, max_density_points, 3] | PP 的 map 帧坐标。 |
| density_point_ligand_area_probability | [n_blobs, max_density_points] | Stage1 预测的"该 PP 属于 ligand-area"的概率，作 PP 节点输入特征（对称于受体结合概率）。 |
| receptor_atom_features | [n_blobs, max_receptor_atoms, d] | 受体口袋原子（A）表示。 |
| receptor_atom_coords | [n_blobs, max_receptor_atoms, 3] | A 的 map 帧坐标。 |
| receptor_binding_probability | [n_blobs, max_receptor_atoms] | Stage1 预测的"该受体原子在配体 4Å 内"的概率（F1≈0.65 > ligand-area 0.55），作 A 节点输入特征。 |
| receptor_edge_index / receptor_edge_features | [n_blobs,2,*] / [n_blobs,*,d_edge] | A 内部稀疏图：键 ∪ radius；边特征含距离 GaussianSmearing。 |
| pp_repr | [n_blobs, d] | 粗分支：每 blob 的密度代表向量（压缩 PP，源可 detach）。 |
| a_repr | [n_blobs, d] | 粗分支：每 blob 的受体代表向量（压缩 A，源可 detach）。 |
| ccd_repr | [n_slots, d] | 粗分支：每 slot 的配体代表向量（压缩 CCD + slot_index_embedding + count 嵌入）。 |
| fine_code_recall | [n_blobs, n_slots, d] | 细分支 recall 方向码（配体当 query、配体侧读出）。 |
| fine_code_precision_pp / fine_code_precision_a | [n_blobs, n_slots, d] | 细分支 precision 方向码（PP / A 当 query、各自读出）。 |
| coarse_match_recall | [n_blobs, n_slots, d] | 粗分支 recall 匹配描述（ccd_repr × blob 全 (PP,A)）。 |
| coarse_match_precision_pp / coarse_match_precision_a | [n_blobs, n_slots, d] | 粗分支 precision 匹配描述（pp_repr / a_repr × 配对 ccd 全原子）。 |
| coverage_recall_logit | [n_blobs, n_slots] | 预测 α̂：配体被该 blob 捕获比例。 |
| coverage_precision_logit | [n_blobs, n_slots] | 预测 β̂：该 blob 被配体解释比例。 |
| coverage_recall_target / coverage_precision_target | [n_blobs, n_occurrences] | 标签 α=|b∩g|/|g|、β=|b∩g|/|b|（密度量；身份内匈牙利配 slot↔occurrence）。 |

> `n_slots = Σ_j N_j`。粗分支的 `*_repr` 是单向量摘要；细分支保留全量逐原子/逐点。

---

## §2 算子词典

### 2.0 导言：两族、各取一段、为何

交互分两族：**(i) 注意力 + 显式 pair**（AF3 / Emap2lig）；**(ii) 稀疏消息传递**（PocketXMol / DiffDock）。我们按子任务各取一段，且都落在**非等变标量特征**上（Stage2 预测的是覆盖**标量**——不变量，不需等变；Stage3 走 Emap2lig 非等变注意力扩散）：

| 子任务 | 用哪族 | 理由 |
| --- | --- | --- |
| A 内部图 | (ii) gated 消息传递 | 受体是稀疏键图，累加式 + 距离乘性消息是 MP 长处。 |
| 配体内部 | (i) PairFormer | 小化学图，三角更新 O(n³) 可接受；直接复用 Emap2lig。 |
| 配体↔(PP,A) 跨集合 | (i) cross-attention | 配体 Stage2 无坐标，只能特征空间；复用并适配 Emap2lig SelectedCrossAttention。 |
| 粗分支 rep-rep / rep-实体 | (i) cross/self-attention | 集合推理在压缩向量上做，便宜、可全图。 |

**PP 不做内部图 MP**（只在表示前导里初始化 + 和 P 融合）。

### 2.1 `SparseGraphInteraction`（A 内部图；第一版 = gated 消息传递）

`receptor_atom_features ← SparseGraphInteraction(receptor_atom_features, receptor_edge_index, receptor_edge_features)`

- **定义**：逐边 `msg = message_mlp(edge_mlp(edge_features) ⊙ node_mlp(neighbor))`；`gate = sigmoid(gate_mlp(edge_features, neighbor))`；`scatter_sum` 聚合（不归一化）；残差 + LayerNorm + out_transform（PocketXMol `NodeBlock`）。
- **A-only**：只在受体节点上跑，**无 PP/A typed 分支**（PP 不进此算子）。
- **用几何**：是（边含距离，间接）。**等变**：否。**更新坐标**：否。**块数 \~4**（对齐 Emap2lig `InstanceSeg` 的 `num_blocks=4`）。
- **Stage2/Stage3 通用**：context 在两阶段都固定，无坐标更新，同算子直接复用。

### 2.2 `CrossAttention`（跨集合；支持 typed K/V + 几何可选）

`query_features ← CrossAttention(query_features, keyvalue_features, keyvalue_type=None, query_coords=None, keyvalue_coords=None)`

- **定义**：query 对 keyvalue cross-attention。给坐标且同帧 → 加相对位置偏置（几何）；不给 → 纯特征空间。`keyvalue_type` 给定时用**类型专属 K/V 投影 + 装配 mask**（选项二）：`(PP,A)` 作一套 K、PP/A 各自投影；**A-only = 把 K 里 PP 段 mask 掉**（A-only 是 (PP,A)-as-K 的特例）。
- **用几何**：可选（Stage2 否 / Stage3 是）。**等变**：否。**更新坐标**：否。
- **输出路由是 Stage2/Stage3 唯一差别**：Stage2 → 喂 readout（只读、不写回）；Stage3 → 残差写回 query（条件化）。
- **复用**：适配 Emap2lig `SelectedCrossAttention`（Stage2 关配体坐标 PE）。

### 2.3 `LigandPairFormer`（= 直接复用 Emap2lig `PairFormer`，不重写）

`ligand_atom_features, ligand_pair_features ← LigandPairFormer(ligand_atom_features, ligand_pair_features, masks)`

- **定义** = `BiasedSelfAttention`(AttentionPairBias) + `OuterProductMeanToPair` + `TrianglePairUpdate`(TriangleMul out/in + TriangleAttn start/end) + Transition，堆若干层。
- **死条件已核**：`emap2lig/model/modules/pairformer.py::PairFormer` 接口直接吃配体张量（批维=slot），至多改 config → **import 复用**。

### 2.4 `BiasedSelfAttention` / `OuterProductMeanToPair` / `TrianglePairUpdate`

PairFormer 组件（定义见 2.3 / AF3）。`BiasedSelfAttention(node_features, bias=None)`：自注意力 + 可选 pair/几何偏置；粗分支的 rep 同类 self-attn 也用它（`bias=None`）。

### 2.5 `LearnedQueryReadout`（集合 → 标量码）

`code ← LearnedQueryReadout(item_features, item_mask)`：一个可学习查询对 `item_features` 池化成向量。recall 方向在配体侧读出（1 个查询）；precision 方向在 PP、A 侧各读出（2 个查询）。

---

## §3 三种实体与位置不对称

| 实体 | 主特征 | 坐标 | 内部边 |
| --- | --- | --- | --- |
| 配体原子（1 slot） | ligand_atom_features | 仅 Stage3 有坐标 | ligand_pair_features（化学） |
| 密度点 PP（1 blob） | density_point_features + density_point_ligand_area_probability | density_point_coords | 无（不做内部图） |
| 受体原子 A（1 blob 口袋） | receptor_atom_features + receptor_binding_probability | receptor_atom_coords | 键 ∪ radius |

**位置不对称**（反作弊，见 `模型总规划_v2.md` §1.4）：同帧侧（PP/A）几何可用；**跨到配体**——Stage2 `query_coords=None`（无坐标，给即泄露 GT），Stage3 给配体噪声坐标。**PP 与 A 之间不直接耦合**（无密-受边），只经配体（细分支）与 `ccd_repr`（粗分支）间接相遇。

---

## §4 表示前导（迭代前，先把三类实体表示建好）

```python
# (1) PP 初始化 + 与 P 融合（不做 PP 内部图）
density_point_features = gather(voxel_feature_grid, sampled_pp_voxels)        # = Emap2lig select_top_k_points
density_point_features = concat_feature(density_point_features, density_point_ligand_area_probability)
density_point_features = FusePtoPP(density_point_features, stage1_P_features)  # 吸收 P 的源④⑤（同帧 KNN/radius，一次）

# (2) A 内部消化（gated 消息传递 ~4 块）
receptor_atom_features = concat_feature(receptor_atom_features, receptor_binding_probability)
for _ in range(num_A_graph_blocks):   # ~4
    receptor_atom_features = SparseGraphInteraction(receptor_atom_features, receptor_edge_index, receptor_edge_features)

# (3) CCD 编码（复用 Emap2lig conf 路 + PairFormer）
ligand_atom_features, ligand_pair_features = ConformerEmbedder(ccd)
for _ in range(num_pairformer_blocks):
    ligand_atom_features, ligand_pair_features = LigandPairFormer(ligand_atom_features, ligand_pair_features, masks)
ligand_atom_features += slot_index_embedding   # 早期注入 e_s（方案 1）
```

这三段产出的 `density_point_features` / `receptor_atom_features` / `ligand_atom_features` 是**共享 trunk**：细分支只读它们、绝不写回（§5）；粗分支压缩它们（§6，源可 detach）。

---

## §5 细分支（逐对全量 cross-attn，read-only → 读出码）

```python
# 批量在 [n_blobs, n_slots] 网格；输出是【新建的逐对 grid 张量】，不写回共享 trunk
# recall 方向：配体当 query attend (PP,A) typed K/V
fine_probe_recall = CrossAttention(                         # [n_blobs, n_slots, max_lig, d]
        query_features    = ligand_atom_features,
        keyvalue_features = stack(density_point_features, receptor_atom_features),
        keyvalue_type     = context_node_type,              # PP/A 各自 K/V 投影；A-only 可由 mask 得到
        query_coords      = None)                            # Stage2 无几何
fine_code_recall = LearnedQueryReadout(fine_probe_recall, ligand_atom_mask)   # 配体侧池化 → 1 码

# precision 方向：PP、A 各当 query attend 配体（PP 只 attn CCD、A 只 attn CCD，互不 attn）
fine_probe_precision_pp = CrossAttention(query_features=density_point_features,  keyvalue_features=ligand_atom_features, query_coords=None)
fine_probe_precision_a  = CrossAttention(query_features=receptor_atom_features, keyvalue_features=ligand_atom_features, query_coords=None)
fine_code_precision_pp = LearnedQueryReadout_pp(fine_probe_precision_pp, density_point_mask)   # PP 侧池化
fine_code_precision_a  = LearnedQueryReadout_a (fine_probe_precision_a,  receptor_atom_mask)   # A 侧池化
```

**read-only 是 Stage2 的硬约束**：`fine_probe_*` 是逐对网格里**新建**的张量,绝不回灌共享的 `ligand_atom_features`/`density_point_features`——因为网格里绝大多数是错配对,回灌等于用噪声污染被全图复用的共享表示。若想多层逐对精炼,可在**网格内部链式**（第 2 层 query = 第 1 层 grid 输出，仍逐对、不碰共享）,末端读出;深监督可选。

> Stage3 相反：单对正确配对，`CrossAttention` 残差**写回**配体（条件化），接扩散（§9）。

---

## §6 粗分支（3 类 rep 的集合推理；提供全局先验、可分 chunk）

```python
# (a) 压缩成 3 类代表向量（源可 detach）
pp_repr  = Compress_pp(detach(density_point_features))     # [n_blobs, d]
a_repr   = Compress_a (detach(receptor_atom_features))     # [n_blobs, d]
ccd_repr = Compress_ccd(detach(ligand_atom_features)) + count_embedding   # [n_slots, d]

# (b) 重复 L_coarse 层；Order B：先跨类、后同类
for _ in range(L_coarse):
    # 跨类 rep-rep cross-attn（ccd ↔ {pp, a}；PP 与 A 不直接 attn）
    ccd_repr = CrossAttention(ccd_repr, keyvalue=stack(pp_repr, a_repr), keyvalue_type=...)   # typed K/V，与细分支同构
    pp_repr  = CrossAttention(pp_repr,  keyvalue=ccd_repr)
    a_repr   = CrossAttention(a_repr,   keyvalue=ccd_repr)
    # 同类 self-attn（3 类各自做）—— 拿到“这张图的 PP-blobs / A-口袋 / ligands+count”
    pp_repr  = BiasedSelfAttention(pp_repr)
    a_repr   = BiasedSelfAttention(a_repr)
    ccd_repr = BiasedSelfAttention(ccd_repr)

# (c) 末尾一次：rep × 跨类未塌缩实体（detach 实体）→ 匹配描述
coarse_match_recall       = LearnedQueryReadout(CrossAttention(ccd_repr, keyvalue=detach(stack(density_point_features, receptor_atom_features)), keyvalue_type=...))  # [n_blobs, n_slots, d]
coarse_match_precision_pp = LearnedQueryReadout(CrossAttention(pp_repr,  keyvalue=detach(ligand_atom_features)))
coarse_match_precision_a  = LearnedQueryReadout(CrossAttention(a_repr,   keyvalue=detach(ligand_atom_features)))
```

- **Order B 的理由（结构性）**：explaining-away 的"竞争"必须 match-aware——blob 要先在跨类 cross-attn 里拿到"我对各 ligand 的匹配强度"，**再**在同类 self-attn 里和其他 blob 竞争。故跨类先于同类。
- **3 类、各自 self-attn**：`pp_repr`/`a_repr`/`ccd_repr` 三个独立同类自注意力；PP-rep 与 A-rep 不互 attn（无密-受耦合）。
- **detach 默认**：压缩源 detach、末尾 cross-attn 的实体 detach → 粗分支是**只读集合推理器**，不反向污染 trunk，且不必为它保留 trunk 激活（这正是 chunk 便宜的前提，§10）。
- **计数自然对齐**：recall 1 个、precision 2 个匹配描述，正好对上细分支的 1 码 / 2 码；即便不齐也不死守（打分 MLP 调维即可）。

### §6.1 两个还没拍死的选择（丙：不死守不变式；耦合互补：粗分支要不要 detach）

**（丙）不死守码数不变式。** 粗、细两支各产各的码，逐方向计数不必相等；打分 MLP 输入维自由拼接（§7）。3 类 rep 下其实自然对齐（recall 1、precision 2），所以丙只是安全垫；但保留它意味着将来某支加/减码、或加额外辅助匹配描述时，不必回头改架构。

**（耦合互补）粗分支 detach 与否——一个有明确理由的可选项，不只是消融。** 先看两支天生的耦合性:

- **细分支天生"不耦合"**:逐对 read-only、各 (blob, slot) 独立算，给的是**干净的逐对细节、但 set-blind**。
- **粗分支天生"耦合"**:rep 在跨类 + 同类 attn 里跨整图相互作用，给的是**全局/集合信号**。
- 二者**信息互补**（逐对细节 ↔ 跨集合全局），这正是两支都要的根本原因。

在此之上,"粗分支要不要 detach"是真选择:

- **detach（当前默认）**:粗分支是只读集合推理器，不反向塑造 trunk;chunk 最省（不必为粗分支保留 trunk 激活，§10）。
- **不 detach（可选，信息更互补）**:让粗分支梯度回到压缩源乃至 trunk——**既然细分支已"不耦合"地提供干净细节，就放粗分支"耦合"地去塑造 trunk 表示**，正好补上"全局先验如何反哺逐原子/逐点表示"这一环（你朋友说的"细不耦合、粗耦合一下、信息正好互补"）。代价:粗分支 backward 要保留 trunk（per-blob/per-slot，**非**逐对网格）激活，显存比 detach 多一档，但昂贵的逐对部分照常 chunk，仍可控。

**取舍结论**:默认仍 detach（稳、省）;但把"不 detach"从单纯消融**升格为一条有明确理由的可选主线**——想要"全局反哺细节"时直接开。两者一个开关切换（`coarse_detach: bool`），不改其余结构。

---

## §7 打分（粗 + 细 → 覆盖矩阵）

```python
coverage_recall_logit    = sigmoid(MLP_recall   (concat(fine_code_recall,       coarse_match_recall)))                     # [n_blobs, n_slots]
coverage_precision_logit = sigmoid(MLP_precision (concat(fine_code_precision_pp, fine_code_precision_a,
                                                         coarse_match_precision_pp, coarse_match_precision_a)))             # [n_blobs, n_slots]
```

两个头分参数；MLP 输入维随粗/细码数自由拼接。损失 = 覆盖软回归 + 阈值 focal，slot↔occurrence 走身份内匈牙利（`模型总规划_v2.md` §6/§8）。

---

## §8 Stage2 批量前向（整图、无循环）

```python
# 1. 表示前导（§4）：PP/A/CCD 各自批量算好共享 trunk
# 2. 粗分支全局部分（§6 a,b）：压缩 + rep-rep（整图所有 blob/slot，便宜，不 chunk，激活保留）
# 3. 逐对部分（§5 细分支 + §6c 末尾 rep×全实体）：在 [n_blobs, n_slots] 网格上 —— 可 chunk（§10）
# 4. 打分（§7）→ coverage_*_logit → 身份内匈牙利损失 + 辅助损失（§11）
```

无 Python 逐对循环；"逐对"是张量前置批维 `[n_blobs, n_slots]`。

## §9 Stage3 批量前向（\[B_pairs\] × 扩散步；context 缓存；写回 + 无粗分支）

```python
# 堆多个独立正确配对 (blob, ligand) 成 batch [B_pairs]；无粗分支（单对无集合可推理）
# 表示前导一次（context 不依赖配体噪声坐标，跨扩散步缓存）
for t in diffusion_steps:
    h = ligand_atom_features
    for _ in range(couple):    # couple=int：写回式逐对耦合层数
        h = CrossAttention(h, keyvalue=stack(density_point_features, receptor_atom_features), keyvalue_type=...,
                           query_coords=ligand_atom_coords_t, keyvalue_coords=context_coords)   # 几何开 + 残差写回 h
    ligand_atom_coords_t = DiffusionDenoiseHead(h, ligand_atom_coords_t, context_cache)          # 复用 Emap2lig AtomDiffusion
# use_receptor=False ⇒ context 只剩 PP ⇒ 精确退回 Emap2lig
```

**Stage2 / Stage3 的四处差别**：① 细分支输出（只读→readout / 写回→扩散）；② 粗分支（Stage2 有 / Stage3 无）；③ 几何（无 / 有）；④ 批量（`[n_blobs,n_slots]` 网格 / `[B_pairs]`×扩散步）。算子全部同一套。

---

## §10 chunk 训练策略（全局视野 + 显存可控）

- **整图、便宜、保留**：表示前导 + 粗分支压缩 + rep-rep（§6 a,b）在**所有 blob/slot** 上算一次（rep 是单向量，几十\~上百 token，装得下），给每个 rep 注入全局先验。
- **逐对、昂贵、chunk**：细分支（§5）+ 粗分支末尾 `rep×全实体`（§6c）在 `[n_blobs, n_slots]` 网格上**分 chunk**、各 chunk 独立回传、梯度累积。
- 每个 chunk 用到的 rep **已是全局感知**（rep-rep 算过），所以**分 chunk 仍有全图视野**。detach（§6）让粗分支不需保留 trunk 激活，chunk 显存进一步省。
- 这就是早先反复要的"全局视野 + 分 chunk 适配显存"——**粗分支是它的实现机制**。

---

## §11 监督全清单（两级辅助 + 覆盖）

| 损失 | 挂在哪 | 说明 / 预期有效性 |
| --- | --- | --- |
| Loss_coverage | coverage_recall/precision_logit | 主损失；软回归 + 阈值 focal + 身份内匈牙利。 |
| 粗 rep 全局属性 | pp_repr / a_repr / ccd_repr | 预测口袋/PP/配体的大小、形状、分子量、原子数 → 防 rep 塌缩、给粗分支"听得懂全局"的信号。 |
| 细 ligand 逐原子/键属性 | ligand_atom_features / ligand_pair_features | 复用 Emap2lig AuxiliaryModule（元素/手性/环 + 键类型/环/存在 + pair 距离，可选）→ 防配体表示塌缩。 |
| Loss_binding | binding_probability_logit（A 上） | 反向监督受体结合概率；近零成本正则。 |
| density_point_ligand_area 辅助 | PP 上 | 对称于结合概率，可选辅助。 |
| 逐原子/逐点覆盖辅助 | fine_probe_* 读出前 | 逐配体原子"被覆盖" / 逐 PP"属于"，可选深监督。 |

> **去掉 `slot_is_present`**（假定 count 正确，不需要）。每个辅助头都标了预期作用（防塌缩 / 正则 / 细粒度对齐）；上线前按此评估，不无脑堆。

---

## §12 Emap2lig 复用映射表

| 我们的部件 | Emap2lig 来源 | 复用方式 |
| --- | --- | --- |
| LigandPairFormer（配体内部） | modules/pairformer.py::PairFormer | import 复用，至多改 config |
| CrossAttention（跨集合） | layers/selected_attention.py::SelectedCrossAttention | 适配：Stage2 关配体坐标 PE；加 typed K/V + mask |
| 细 ligand 辅助头 | modules/pairformer.py::AuxiliaryModule | 复用（可选） |
| PP 初始化 gather | modules/instance_seg.py::select_top_k_points | 复用 |
| Stage3 扩散头 | modules/diffusion.py::AtomDiffusion | 复用（受体作额外条件） |
| SparseGraphInteraction（A 图） | 无（参照 PocketXMol models/graph.py::NodeBlock，去坐标更新） | 自写小模块 |
| 粗分支 / 细分支读出 / 打分 MLP | 无 | 自写 |

---

## §13 工程形态与待定旋钮

**不强求统一 Block**：做成**可配置大类**——`num_pairformer_blocks` / `num_A_graph_blocks(~4)` / `L_coarse` / `couple(int)` / 粗分支开关 / cross-attn 种类与次数 / 各辅助头开关与权重 独立可调。

**可选项 / 消融 / 钩子（非第一版）**：粗分支不 detach（`coarse_detach=False`，已在 §6.1 升格为有理由的可选主线、非纯消融）；不死守码数不变式（§6.1 丙）；context 图 softmax 版；选项一（PP/A 分两次 attn、不同归一化）；2 类 rep 打包；PP 升级（短卷积/插值 + 构造边）；3D RoPE；等变坐标更新 / DiffDock 张量场（排除）；粗分支跨类层数 / Order A 对照。

> 横向对照（AF3 / PocketXMol / DiffDock / Emap2lig 用同一套算子）见 `参照算法_迭代运算梳理_AF3_PocketXMol.md`。