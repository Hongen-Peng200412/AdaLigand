# AdaLigand Stage2 / Stage3 迭代运算设计

> **本文定位**：`模型总规划_v2.md` 的**运算模块说明书**。前者讲"匹配预测什么、损失/数据/解码怎么定义"（**是什么**）；本文讲"这些表示如何一层层算出来、用哪些算子、Stage2/Stage3 如何共用代码"（**怎么算**）。两文合起来自包含；本文在运算层面自包含（术语见 §1/§2，首次出现即定义）。
>
> **命名规则**：特征张量 `snake_case` + 后缀（`_features`/`_coords`/`_logit`/`_target`/`_probability`/`_index`/`_mask`/`_repr`）+ 标注 `[形状]`。**例外**：缩写 `PP`/`A`/`CCD` 在 `*_repr` 与码名里保持大写（如 `PP_repr`、`fine_code_recall_PP`），更易读。算子 `PascalCase`，给"签名 / 定义 / 是否用几何 / 是否等变 / 是否更新坐标 / 成本"。
>
> **核心结构（本版定稿）**：匹配分**细分支**（逐对全量 cross-attn，info-rich 但 set-blind）与**粗分支**（压缩代表向量做集合推理，提供全局先验、可分 chunk），两支的码并进打分 MLP。所有跨/自注意力统一走一个原语 `TypedAttention`（支持多类 typed Q/KV + 可选分类 softmax + 可选加性 bias）。trunk 更新（A 图、配体 PairFormer）、粗细分支、块内监督统一收进一个**可配置 Block**（§5）；Stage2 的逐对 cross-attn **只读不写回**共享表示，Stage3 写回（条件化）后接扩散。
>
> **第一版默认 vs 消融**：默认走**精简档**——细分支对 PP/A **解耦**（各自 softmax + 各自读出），粗分支默认 **2 类 rep**（`CCD_repr` + 耦合的 `blob_repr`）。其余更重的形态（粗分支 4 类、联合 softmax、粗分支不 detach、软 count 集合层深度等）一律作**消融钩子**（§14）。context 图只实现 gated 消息传递（A-only）；配体内部直接复用 Emap2lig `PairFormer`；不实现等变坐标更新 / 3D RoPE / softmax 版 context 图。

---

## §1 特征张量词典

| 名称 | 形状 | 含义 |
| --- | --- | --- |
| ligand_atom_features | [n_slots, max_ligand_atoms, d] | 配体原子表示（ConformerEmbedder 初始化、Block 内 PairFormer 更新；细分支里作 query，Stage2 全程不被密度写回）。批维 = slot。 |
| ligand_pair_features | [n_slots, max_ligand_atoms, max_ligand_atoms, d_pair] | 配体原子对（化学键 / 参考距离）。 |
| ligand_atom_coords | [n_slots, max_ligand_atoms, 3] | 仅 Stage3：扩散噪声坐标。 |
| slot_index_embedding | [n_slots, d] | 身份内副本索引 e_s（身份内匈牙利，见 `模型总规划_v2.md` §6），表示前导末尾早期注入。 |
| density_point_features | [n_blobs, max_density_points, d] | 密度点（PP）表示。批维 = blob。PP ~4096（可配 8192）。 |
| density_point_coords | [n_blobs, max_density_points, 3] | PP 的 map 帧坐标。 |
| density_point_ligand_area_probability | [n_blobs, max_density_points] | Stage1 预测的"该 PP 属于 ligand-area"概率。作 PP 节点输入特征**且**作注意力加性 bias 来源（detach，§2.2/§4）。 |
| receptor_atom_features | [n_blobs, max_receptor_atoms, d] | 受体口袋原子（A）表示。A ~256–512（k-NN/radius 截断）。 |
| receptor_atom_coords | [n_blobs, max_receptor_atoms, 3] | A 的 map 帧坐标。 |
| receptor_binding_probability | [n_blobs, max_receptor_atoms] | Stage1 预测的"该受体原子在配体 4Å 内"概率（F1≈0.65 > ligand-area 0.55）。作 A 节点输入特征**且**作 bias 来源（detach）。 |
| receptor_edge_index | [2, n_receptor_edges_total] | A 内部稀疏图边（**COO 扁平格式**，blob 间用 `receptor_edge_batch` 切分；非按 blob 稠密补齐）。键 ∪ radius。 |
| receptor_edge_features | [n_receptor_edges_total, d_edge] | 边特征：距离 GaussianSmearing（⊕ 两端结合概率，作消息 bias，§2.1）。 |
| receptor_edge_batch | [n_receptor_edges_total] | 每条边归属的 blob 索引（COO 批切分）。 |
| context_node_type | [n_blobs, max_density_points + max_receptor_atoms] | 把 PP、A 沿 token 轴拼接后的**长整型类别标签**（PP=0 / A=1），作 `TypedAttention` 的 `keyvalue_type`（PP/A 各自 K/V 投影、配合 split）。 |
| CCD_repr | [n_slots, d] | 粗分支：每 slot 配体代表向量（压缩 `ligand_atom_features` ⊕ slot_index_embedding ⊕ count 嵌入；源可 detach）。 |
| blob_repr | [n_blobs, d] | 粗分支**默认**：每 blob 的耦合代表向量（压缩 (PP,A) 联合；源可 detach）。承担 blob 级 count 预算 explaining-away。 |
| PP_repr / A_repr | [n_blobs, d] | 粗分支**消融（4 类）**：把 blob 拆成密度级 / 口袋级两条独立 rep（默认不建，§14）。 |
| fine_code_recall_PP / fine_code_recall_A | [n_blobs, n_slots, d] | 细分支 recall 码：配体当 query、attend (PP,A) 全原子（typed KV + split），PP/A 各自 softmax、配体侧各读出一码。 |
| fine_code_precision_PP / fine_code_precision_A | [n_blobs, n_slots, d] | 细分支 precision 码：PP / A 各当 query attend 配体全原子，各自读出。 |
| coarse_match_recall_PP / coarse_match_recall_A | [n_blobs, n_slots, d] | 粗分支 recall 匹配描述：`CCD_repr` × blob 全 (PP,A)（typed + split）。 |
| coarse_match_precision | [n_blobs, n_slots, d] | 粗分支 precision 匹配描述：`blob_repr` × 配对 ccd 全原子（CCD 单类型，不 split）。 |
| coverage_recall_logit | [n_blobs, n_slots] | 预测 α̂：配体被该 blob 捕获比例。 |
| coverage_precision_logit | [n_blobs, n_slots] | 预测 β̂：该 blob 被配体解释比例。 |
| coverage_recall_target / coverage_precision_target | [n_blobs, n_occurrences] | 标签 α=\|b∩g\|/\|g\|、β=\|b∩g\|/\|b\|（密度量；身份内匈牙利配 slot↔occurrence）。 |

> `n_slots = Σ_j N_j`。`*_repr` 是单向量摘要；细分支保留全量逐原子/逐点。**码数不守不变式**（§14 丙）：粗/细各产各的码，打分 MLP 输入维自由拼接。

---

## §2 算子词典

### 2.0 导言：两族、各取一段、为何

交互分两族：**(i) 注意力 + 显式 pair**（AF3 / Emap2lig）；**(ii) 稀疏消息传递（message passing, MP）**（PocketXMol / DiffDock）。按子任务各取一段，且都落在**非等变标量特征**上（Stage2 预测覆盖**标量**，不变量、不需等变；Stage3 走 Emap2lig 非等变注意力扩散）：

| 子任务 | 用哪族 | 理由 |
| --- | --- | --- |
| A 内部图 | (ii) gated MP | 受体是稀疏键图，累加式聚合 + 距离乘性消息是 MP 长处（softmax 会归一化掉"邻居越多越强"）。 |
| 配体内部 | (i) PairFormer | 小化学图，三角更新 O(n³) 可接受；直接复用 Emap2lig。 |
| 配体↔(PP,A) / 粗分支所有 attn | (i) TypedAttention | 配体 Stage2 无坐标，只能特征空间；统一原语，支持 typed Q/KV。 |

**PP 不做内部图 MP**（只在表示前导里初始化 + 同位多源融合 + 与 P 空间融合）。
**边特征只进 MP（§2.1），不进 TypedAttention**：后者只收"加性 bias"（相对坐标 ⊕ 概率），不收通用逐对 edge 张量——否则会重新引入 softmax 归一化（与密度累加诉求冲突）、且丢掉 flash kernel。

### 2.1 `SparseGraphInteraction`（A 内部图；第一版 = gated MP）

`receptor_atom_features ← SparseGraphInteraction(receptor_atom_features, receptor_edge_index, receptor_edge_features, receptor_edge_batch)`

- **定义**（COO 扁平、PocketXMol `NodeBlock` 式）：逐边 `msg = message_mlp(edge_mlp(edge_features) ⊙ node_mlp(neighbor))`；`gate = sigmoid(gate_mlp(edge_features, neighbor))`；`scatter_sum`（不归一化）；残差 + LayerNorm + out_transform。
- **A-only**：只在受体节点跑，无 PP/A typed 分支（PP 不进此算子）。
- **结合概率进消息 bias**：边特征拼接两端 `receptor_binding_probability`（**detach**），作乘性/加性消息塑造（§3 概率注入）。
- **用几何**：是（边含距离 GaussianSmearing，间接）。**等变**：否。**更新坐标**：否。**块数 ~4**（对齐 Emap2lig `InstanceSeg` 的 `num_blocks=4`，图运算浅层即可，避免过平滑）。

### 2.2 `TypedAttention`（统一跨/自注意力原语；从头写）

`out ← TypedAttention(query_features, keyvalue_features, query_type=None, keyvalue_type=None, split_type_kv=False, attn_bias=None, query_coords=None, keyvalue_coords=None)`

- **统一 self / cross**：self-attn = `keyvalue_features is query_features` 的特例；caller 决定残差写回（Stage3）还是新建张量只读（Stage2），算子本身只返回注意力输出。
- **typed 投影（多类）**：`query_type` / `keyvalue_type` 是**长整型类别张量**（任意 K 类，取值同域），按类别选**类型专属 Q / K / V 投影**。`None` = 单类型。
- **`split_type_kv`**（仅当 `keyvalue_type` 非 None 生效）：
  - `False`：所有 kv 类别落在**同一个 softmax**（类间抢注意力质量），出 1 个对象。
  - `True`：**每个 kv 类别各自 softmax**，出"每类一个"对象（多输出）。
  - **不对称提醒**：split 只在 KV 侧有意义；query 侧从不共享 softmax，多类 query 天然各算各、各自输出，无需对称的 `split_type_q`。
- **加性 bias**：`attn_bias`（可选）= 相对坐标编码（给坐标且同帧）⊕ 概率（detach）拼出的加性项，加到注意力 logit。**不收通用 edge 张量**（见 §2.0）。
- **用几何**：可选（Stage2 不给坐标=纯特征空间；Stage3 给配体噪声坐标=几何）。**等变**：否。**更新坐标**：否。flash-attn + mask，无 Python 逐对循环。
- **复用边界**：**不直接 import Emap2lig `SelectedCrossAttention`**（它无双侧 typed mask、无 split）。借其几何 bias 与 flash 脚手架，但 typed 投影 + 双 mask + split 是新增，需**改写**。

### 2.3 `LigandPairFormer`（= 直接复用 Emap2lig `PairFormer`，不重写）

`ligand_atom_features, ligand_pair_features ← LigandPairFormer(ligand_atom_features, ligand_pair_features, masks)`

- **定义** = `BiasedSelfAttention`(AttentionPairBias) + `OuterProductMeanToPair` + `TrianglePairUpdate`(TriangleMul out/in + TriangleAttn start/end) + Transition，堆若干层。
- **死条件已核**：`emap2lig/model/modules/pairformer.py::PairFormer` 接口（atom/pair/mask，批维=slot）直接吃配体张量，至多改 config → **import 复用**。实测尺寸 `d_atom=128`、`d_pair=64`、`num_blocks=4`、`max_atoms` 上限 200。
- **显存**：三角注意力 O(N³) 激活是大头；开**激活检查点**（用 PyTorch 原生 `torch.utils.checkpoint`，避开 fairscale 在老 glibc 上的安装难题）后，50–100 个 slot 在 80G 上从容（§13）。

### 2.4 `BiasedSelfAttention` / `OuterProductMeanToPair` / `TrianglePairUpdate`

PairFormer 组件（定义见 2.3 / AF3）。粗分支同类 rep 的 self-attn 可直接用 `TypedAttention`（self 模式、`attn_bias=None`）。

### 2.5 `LearnedQueryReadout`（集合 → 码）

`code ← LearnedQueryReadout(item_features, item_mask)`：可学习查询对 `item_features` 按 mask 池化成向量。**约定**：查询向量个数 = 接码向量个数 = 匹配描述个数（§5/§7 计数自洽）。

### 2.6 融合算子（同位多源 vs 空间，两类必须分开）

- `FuseSources(main_features, aux_source_features, probability=None)`：**同位多源融合**——同一点/原子的若干来源特征（PP 的 S 轴 5 源、A 的 S 源）并成一个。默认 **FiLM**（主特征 = 原始手工编码，其余源 ⊕ 概率 出 (γ,β) 调制 main）；gated-sum / S-token 小自注意作消融。
- `FusePtoPP(density_point_features, stage1_P_features)`：**空间融合**——PP 向邻近 P（KNN/radius、同帧、几何）吸收源④⑤。内核是 **cross-attn / MP**，**不是 FiLM**（FiLM 无空间 gather；要先聚合才有 conditioning 向量）。

---

## §3 三种实体与位置不对称

| 实体 | 主特征 | 坐标 | 内部边 |
| --- | --- | --- | --- |
| 配体原子（1 slot） | ligand_atom_features | 仅 Stage3 有坐标 | ligand_pair_features（化学） |
| 密度点 PP（1 blob） | density_point_features + ligand_area 概率 | density_point_coords | 无（不做内部图） |
| 受体原子 A（1 blob 口袋） | receptor_atom_features + binding 概率 | receptor_atom_coords | 键 ∪ radius（COO） |

**位置不对称**（反作弊，见 `模型总规划_v2.md` §1.4）：同帧侧（PP/A）几何可用；**跨到配体**——Stage2 `query_coords=None`（无坐标，给即泄露 GT），Stage3 给配体噪声坐标。**PP 与 A 不直接耦合**（无密-受边），只经配体（细分支）与 `blob_repr`（粗分支）间接相遇。

**概率注入（统一规则）**：`ligand_area`（PP）/ `binding`（A）概率 (1) 拼进节点输入特征；(2) 作注意力/消息**加性 bias 来源，且一律 detach**——概率由专属辅助头负责预测（§12），消费方只当"提示值"用，不反向训练预测器（与粗分支 detach 同哲学）。bias 取几个概率随场景：**边 bias 取两端 2 个**（A 图），**节点/key bias 取 1 个**（cross-attn key 侧）；Stage2 无坐标时概率仍可作无坐标 key 加性 logit bias。**带开关**可关。

---

## §4 表示前导（迭代前，只构建三类实体的初始表示）

```python
# 只做"特征构建"，不含 A 图迭代 / PairFormer 迭代（那两个在 Block 内，§5）

# (1) PP：采样 + 同位多源融合 + 与 P 空间融合
density_point_features = gather(voxel_feature_grid, sampled_pp_voxels)            # = Emap2lig select_top_k_points
density_point_features = FuseSources(density_point_features, pp_S_sources,        # 同位多源 → FiLM
                                     probability=density_point_ligand_area_probability)
density_point_features = FusePtoPP(density_point_features, stage1_P_features)     # 空间 cross-attn/MP，吸收 P 源④⑤

# (2) A：同位多源融合（含结合概率）
receptor_atom_features = FuseSources(receptor_atom_features, a_S_sources,
                                     probability=receptor_binding_probability)

# (3) CCD：构象编码（A 图迭代与 PairFormer 迭代都在 Block 内）
ligand_atom_features, ligand_pair_features = ConformerEmbedder(ccd)               # 复用 Emap2lig conf 路
ligand_atom_features = ligand_atom_features + slot_index_embedding               # 早期注入 e_s（方案 1）
```

产出的三类初始特征是**共享 trunk 的起点**；Block（§5）在其上逐层更新（A 图、PairFormer）、压缩（粗分支）、读出（细分支）。

---

## §5 可配置 Block（trunk 更新 + 粗细分支 + 块内监督；两相执行）

**不强求"统一抽象成一个 Block 跑 num_Block 次"**，而是做成**可配置大类**：每层独立配置以下开关，Stage2/Stage3 共用同一套。

| 逐层开关 | 取值 | 说明 |
| --- | --- | --- |
| `run_pairformer` | bool | 这层是否跑配体 PairFormer（trunk 更新）。 |
| `run_a_graph` | bool | 这层是否跑 A 图 `SparseGraphInteraction`（trunk 更新）。 |
| `run_coarse` | bool / 配置 | 这层是否跑粗分支（压缩 + rep-rep，§7）。 |
| `sup`（Stage2） | {none, coarse, full} | 这层监督什么，**派生**跑哪种逐对 cross-attn（见下）。 |
| `xattn_writeback`（Stage3） | bool（couple int 控层数） | 写回式几何 cross-attn（§10）。 |

**`sup` 派生逐对运算（消除非法组合，不靠运行时报错）**：

- `none`：只跑 trunk 更新 + （可选）粗分支全局部分，**不出逐对、不出损失**。
- `coarse`：只跑粗分支末端 `rep×实体`（K 侧轻）+ **粗分支专属小 MLP** → 块内分类深监督（便宜，§12）。
- `full`：跑细分支 read-only cross-attn + 粗分支 `rep×实体`，拼全源 MLP → 块内全监督（贵）。

**两相执行（chunk + 全局视野同时成立的关键）**：一个 Block 层内部天然两相——

1. **相 1（整图、便宜、激活保留）**：trunk 更新（PairFormer per-slot、A 图 per-blob，均**非** per-pair）+ 压缩 rep + rep-rep 集合推理（rep 是单向量、几十~上百 token）。在**所有 blob/slot** 上算。
2. **相 2（逐对、昂贵、可 chunk）**：`sup∈{coarse,full}` 时的逐对 cross-attn + `rep×实体` + 块内打分，在 `[n_blobs, n_slots]` 网格上**分 chunk**、逐 chunk 回传、梯度累积。

跨层只保留相 1 的 trunk + rep 激活（per-blob/slot + 微小 rep，可控）；相 2 每 chunk 用完即释放。**故 Block 不是"原子可 chunk"的，但它昂贵的那一相是。** 深监督默认只放末尾 1–2 层（中间层 `sup=none` 或 `coarse`），控算力。

> **Stage3 缓存契约**：扩散循环里的 Block，`run_pairformer=run_a_graph=False`（trunk 不依赖噪声坐标、循环外缓存一次），只留 `xattn_writeback` + 去噪头逐步重算。否则会每扩散步白重算 trunk。

---

## §6 细分支（逐对全量 cross-attn，read-only → 读出码；默认解耦 PP/A）

```python
# 批量在 [n_blobs, n_slots] 网格；输出是【新建逐对 grid 张量】，绝不写回共享 trunk

# recall：配体当 query attend (PP,A)；typed KV + split（PP/A 各自 softmax，各读一码）
fine_probe_recall = TypedAttention(                          # split → (对PP, 对A) 两路
        query_features    = ligand_atom_features,
        keyvalue_features = stack(density_point_features, receptor_atom_features),
        keyvalue_type     = context_node_type,               # PP/A typed K/V
        split_type_kv     = True,                            # 默认解耦：避免 PP(~4096) 在联合 softmax 淹没 A(~512)
        query_coords      = None)                            # Stage2 无几何
fine_code_recall_PP = LearnedQueryReadout(fine_probe_recall.PP, ligand_atom_mask)
fine_code_recall_A  = LearnedQueryReadout(fine_probe_recall.A,  ligand_atom_mask)

# precision：PP、A 各当 query attend 配体（query 侧天然分离，不需 split）
fine_code_precision_PP = LearnedQueryReadout(
        TypedAttention(density_point_features,  ligand_atom_features, query_coords=None), density_point_mask)
fine_code_precision_A  = LearnedQueryReadout(
        TypedAttention(receptor_atom_features,  ligand_atom_features, query_coords=None), receptor_atom_mask)
```

**read-only 是 Stage2 硬约束**：`fine_probe_*` 是逐对网格里新建的张量，绝不回灌共享 `ligand_atom_features`/`density_point_features`——网格里绝大多数是错配对，回灌等于用噪声污染被全图复用的共享表示。要多层逐对精炼可在**网格内部链式**（下层 query = 上层 grid 输出，仍逐对、不碰共享），末端读出。

> **Stage3 相反**：单对正确配对，`TypedAttention` 残差**写回**配体（条件化），接扩散（§10）。

---

## §7 粗分支（集合推理；默认 2 类 rep；提供全局先验、可分 chunk）

```python
# (a) 压缩成代表向量（源可 detach；默认 2 类：CCD_repr + 耦合 blob_repr）
CCD_repr  = Compress_ccd(detach(ligand_atom_features)) + count_embedding          # [n_slots, d]
blob_repr = Compress_blob(detach(stack(density_point_features, receptor_atom_features)))  # [n_blobs, d]，耦合 (PP,A)

# (b) 重复 L_coarse；Order B：先跨类 cross-attn、后同类 self-attn
for _ in range(L_coarse):
    CCD_repr  = TypedAttention(CCD_repr,  keyvalue=blob_repr)     # 跨类（KV=reps，平衡，默认不 split）
    blob_repr = TypedAttention(blob_repr, keyvalue=CCD_repr)
    CCD_repr  = TypedAttention(CCD_repr,  CCD_repr)               # 同类 self-attn
    blob_repr = TypedAttention(blob_repr, blob_repr)             # blob 级竞争 → count 预算 explaining-away

# (c) 末尾：rep × 跨类未塌缩实体（detach 实体）→ 匹配描述
#     recall：CCD_repr × 全 (PP,A)，KV=全原子点（PP≫A 失衡）→ typed + split
coarse_match_recall_PP, coarse_match_recall_A = LearnedQueryReadout(
        TypedAttention(CCD_repr, keyvalue=detach(stack(density_point_features, receptor_atom_features)),
                       keyvalue_type=context_node_type, split_type_kv=True))      # [n_blobs, n_slots, d] ×2
#     precision：blob_repr × 配对 ccd 全原子，KV=CCD 单类型 → 不 split
coarse_match_precision = LearnedQueryReadout(
        TypedAttention(blob_repr, keyvalue=detach(ligand_atom_features)))         # [n_blobs, n_slots, d]
```

- **Order B 的理由（结构性）**：explaining-away 的竞争必须 match-aware——blob 先在跨类 cross-attn 拿到"我对各 ligand 的匹配强度"，**再**在同类 self-attn 与其他 blob 竞争。故跨类先于同类。
- **默认 2 类的理由**：粗分支本职是 **blob 级**的 count 预算 / 指派 explaining-away，自然要"一个 blob 一个 rep"；耦合 `blob_repr` 同时带形状(PP)+口袋(A)供指派判断，且比 3/4 类**更简化**（rep-rep 少类、匹配描述少）。与细分支的"全解耦"互补（细给干净逐对细节、粗给耦合全局信号）。
- **split 分位置**：rep×**实体**（KV=全 PP+A 点，失衡）→ `split=True`；rep-rep（KV=reps，每类每 blob 一个、平衡）→ 默认**不 split**（联合 softmax 反而让 CCD 横向比较）。
- **detach 默认**：压缩源 detach、末端实体 detach → 粗分支是**只读集合推理器**，不反向塑造 trunk，且不必为它保留 trunk 激活（chunk 便宜的前提，§11）。**注意**：detach 不影响粗分支自身参数受训——其码拼进 §8 的 MLP、被覆盖损失直接监督。

---

## §8 打分（粗 + 细 → 覆盖矩阵；逐支损失各自可调）

```python
coverage_recall_logit = sigmoid(MLP_recall(concat(
        fine_code_recall_PP, fine_code_recall_A,
        coarse_match_recall_PP, coarse_match_recall_A)))                          # [n_blobs, n_slots]

coverage_precision_logit = sigmoid(MLP_precision(concat(
        fine_code_precision_PP, fine_code_precision_A,
        coarse_match_precision)))                                                # [n_blobs, n_slots]
```

- 两头分参数；输入维随粗/细码数自由拼接（码数不守不变式，§14 丙）。
- **损失分工（各自可配权重/类型）**：覆盖标签既有**回归**（smooth-L1/MSE vs α/β）又有**分类**（阈值二值化 A'/B' + focal/CE）。
  - **粗分支中间监督**：着重 **A'/B' 分类**（粗 rep 细节盲、宜判"匹不匹配"，恰是 explaining-away 发生处；用 §5 `sup=coarse` 的专属小 MLP）。
  - **细分支中间监督**：着重**回归**（逐对细节足以拟合精确覆盖值）。
  - **末端监督**：拼全源、**回归+分类都做**——粗分支即使中间只挂分类，也通过末端 MLP 吃到回归梯度，不被饿死。
- slot↔occurrence 走身份内匈牙利（`模型总规划_v2.md` §6/§8）。

---

## §9 Stage2 整图前向（整图、无逐对循环）

```python
# 1. 表示前导（§4）：PP/A/CCD 各自批量构建初始表示
# 2. Block 栈（§5）逐层：相 1 整图（trunk 更新 + 粗分支压缩/rep-rep，便宜、激活保留、不 chunk）
#                        相 2 逐对（sup∈{coarse,full} 的细分支/rep×实体/打分，[n_blobs,n_slots] 网格、可 chunk）
# 3. 末端打分（§8）→ coverage_*_logit → 身份内匈牙利损失 + 块内深监督 + 辅助损失（§12）
```

"逐对"是张量前置批维 `[n_blobs, n_slots]`，非 Python 循环。

## §10 Stage3 前向（[B_pairs] × 扩散步；trunk 缓存；写回 + 无粗分支）

```python
# 堆多个独立正确配对 (blob, ligand) 成 batch [B_pairs]；无粗分支（单对无集合可推理）
# 表示前导 + trunk 更新（PairFormer/A 图）算一次（不依赖噪声坐标，跨扩散步缓存）
for t in diffusion_steps:
    h = ligand_atom_features
    for _ in range(couple):    # couple=int：写回式逐对耦合层数
        h = TypedAttention(h, keyvalue=stack(density_point_features, receptor_atom_features),
                           keyvalue_type=context_node_type, split_type_kv=True,
                           query_coords=ligand_atom_coords_t, keyvalue_coords=context_coords)  # 几何开 + 残差写回 h
    ligand_atom_coords_t = DiffusionDenoiseHead(h, ligand_atom_coords_t, trunk_cache)          # 复用 Emap2lig AtomDiffusion
# use_receptor=False ⇒ context 只剩 PP ⇒ 精确退回 Emap2lig
```

**Stage2 / Stage3 四处差别**：① 细分支输出（只读→readout / 写回→扩散，由 §5 `sup` vs `xattn_writeback` 派生）；② 粗分支（Stage2 有 / Stage3 无）；③ 几何（无 / 有）；④ 批量（`[n_blobs,n_slots]` 网格 / `[B_pairs]`×扩散步）。算子全部同一套（`TypedAttention` / `SparseGraphInteraction` / `LigandPairFormer`）。

---

## §11 chunk 训练策略（全局视野 + 显存可控）

- **整图、便宜、保留**（相 1）：表示前导 + 每层 trunk 更新 + 粗分支压缩/rep-rep，在**所有 blob/slot** 上算（trunk 是 per-blob/slot、rep 是单向量，装得下），给每个 rep 注入全局先验。
- **逐对、昂贵、chunk**（相 2）：细分支 + 粗分支 `rep×实体` 在 `[n_blobs, n_slots]` 网格上**分 chunk**、各 chunk 独立回传、梯度累积。
- 每个 chunk 用到的 rep **已全局感知**（相 1 跑过），故**分 chunk 仍有全图视野**。detach（§7）让粗分支不必保留 trunk 激活，chunk 显存进一步省。
- **PairFormer 显存**：开 PyTorch 原生激活检查点后，50–100 个 slot 的相 1 在 80G 从容（§13）。这就是反复要的"全局视野 + 分 chunk 适配显存"。

---

## §12 监督全清单（两级辅助 + 覆盖；预期有效性已标）

| 损失 | 挂在哪 | 说明 / 预期有效性 |
| --- | --- | --- |
| Loss_coverage（主） | coverage_recall/precision_logit | 软回归 + 阈值 focal + 身份内匈牙利。 |
| 粗分支块内深监督 | 粗分支专属 MLP（§5 sup=coarse/full） | **着重 A'/B' 分类**；逐层（默认末几层）廉价深监督，推动 rep 全局推理早对齐。 |
| 粗 rep 全局属性 | CCD_repr / blob_repr（/消融 PP_repr,A_repr） | 预测口袋/PP/配体的大小、形状、分子量、原子数 → **正则/防 rep 塌缩**（非供梯度，粗分支本就有梯度）。 |
| 细 ligand 逐原子/键属性 | ligand_atom_features / ligand_pair_features | 复用 Emap2lig `AuxiliaryModule`（元素/手性/环 + 键类型/环/存在 + pair 距离，可选）→ 防配体表示塌缩。 |
| Loss_binding | binding 概率重预测头（A 上） | 反向监督受体结合概率；也支撑"概率作 bias 时已 detach"的解耦（§3）。 |
| ligand_area 辅助 | ligand_area 概率重预测头（PP 上） | 对称于结合概率，可选。 |
| 逐原子/逐点覆盖辅助 | fine_probe_* 读出前 | 逐配体原子"被覆盖" / 逐 PP"属于"，可选细粒度深监督。 |

> **去掉 `slot_is_present`**（假定 count 正确，不需要）。每个辅助头都标了预期作用；上线前按此评估，不无脑堆。

---

## §13 Emap2lig 复用映射 + 环境依赖

| 我们的部件 | Emap2lig 来源 | 复用方式 |
| --- | --- | --- |
| LigandPairFormer（配体内部） | modules/pairformer.py::PairFormer | import 复用，至多改 config |
| 细 ligand 辅助头 | modules/pairformer.py::AuxiliaryModule | 复用（可选） |
| PP 初始化 gather | modules/instance_seg.py::select_top_k_points | 复用 |
| Stage3 扩散头 | modules/diffusion.py::AtomDiffusion | 复用（受体作额外条件） |
| TypedAttention（跨/自集合） | layers/selected_attention.py::SelectedCrossAttention | **改写**：借几何 bias + flash 脚手架，新增 typed 双 mask + split |
| SparseGraphInteraction（A 图） | 无（参照 PocketXMol models/graph.py::NodeBlock，去坐标更新、COO） | 自写小模块 |
| FuseSources / FusePtoPP / 粗细分支 / 打分 MLP | 无 | 自写 |

**环境依赖（单列、计划须提）**：
- `flash-attn`：已在目标老 glibc 环境装好（✓）。
- **激活检查点用 PyTorch 原生 `torch.utils.checkpoint`，不依赖 fairscale**（`checkpoint_wrapper` 走 fairscale，老 glibc<2.17 装轮子困难）；行为等价。
- 版本契约（CUDA / torch / flash-attn / glibc 下限）落盘，避免下游复现踩坑。

**显存账（PairFormer 相 1）**：满 pad N=200、`d_pair=64`，三角注意力 O(N³) 激活是大头：裸跑 ~0.1–0.5 GB/配体 → 100 slot ~10–50 GB（80G 能塞、不宽裕）；**开激活检查点后只留 block I/O（~20 MB/配体）→ 100 slot ~2 GB**，从容。再按 batch 实际最大原子数 pad（CCD 多 <100 原子）N³ 进一步缩。相 1 对 n_slots **线性**（每配体独立小图），二次项在相 2、已 chunk。长尾极端样本（占比极小）按 `max_slots` 上限**丢弃部分配体 + 记 provenance**。

---

## §14 默认值表 + 消融钩子

| 旋钮 | 默认值 | 触发/作用条件 | 对应消融钩子 |
| --- | --- | --- | --- |
| 细分支 PP/A 解耦 | **解耦**（recall `split_type_kv=True`、precision 分两 query） | 全程；recall 因 PP≫A 失衡须分 softmax | 联合 softmax（`split_type_kv=False`） |
| 粗分支 rep 类数 | **2 类**（CCD_repr + 耦合 blob_repr） | 全程 | 4 类（+ PP_repr、A_repr，各自 self-attn / 匹配描述） |
| 粗分支 rep-rep 是否 split | **不 split**（reps 平衡） | rep-rep 跨类 | split |
| 粗分支 detach | **detach**（只读集合推理器） | 全程；省 chunk 显存 | 不 detach（`coarse_detach=False`，让全局反哺 trunk，显存多一档） |
| Block `sup` | 末 1–2 层 `full`，中间 `none`/`coarse` | 控深监督算力 | 全层 `full`（每层深监督） |
| 概率作 bias | **开 + detach** | 节点 1 个 / 边 2 个 | 关 bias（只 concat 进节点特征） |
| 同位多源融合 | **FiLM**（主=原始手工编码） | PP/A 各一次 | gated-sum / S-token 小自注意 |
| PP↔P 融合 | **cross-attn/MP**（空间） | 表示前导一次 | 关（= Emap2lig 式消融，无 P） |
| A 图块数 | ~4 | 对齐 Emap2lig InstanceSeg | softmax 版 context 图（注意力族） |
| 激活检查点 | **开（torch 原生）** | PairFormer 相 1 | 关（显存够时） |
| couple（Stage3） | int（写回耦合层数） | Stage3 扩散循环 | full（每块写回） |
| PP 数目 | 4096 | 显存旋钮 | 512 / 8192 |
| 丙：码数不守不变式 | **不守**（MLP 自由拼维） | 粗/细码数不必相等 | 强制对齐（每支固定码数） |

**消融/钩子（非第一版，承 §14 表）**：3D RoPE、等变坐标更新 / DiffDock 张量场（排除）；粗分支 Order A 对照；难负身份配额；全图自然假阳 vs context-box 假阳。

> 横向对照（AF3 / PocketXMol / DiffDock / Emap2lig 用同一套算子）见 `参照算法_迭代运算梳理_AF3_PocketXMol.md`。
