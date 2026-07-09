# AdaLigand Stage2 / Stage3 迭代运算设计

> **本文定位**：`模型总规划_v2.md` 的**运算模块说明书**。前者讲"匹配预测什么、损失/数据/解码怎么定义"（**是什么**）；本文讲"这些表示如何一层层算出来、用哪些算子、Stage2/Stage3 如何共用代码"（**怎么算**）。两文合起来自包含；本文在运算层面自包含（术语见 §1/§2，首次出现即定义）。
>
> **命名规则**：特征张量 `snake_case` + 后缀（`_features`/`_coords`/`_logit`/`_target`/`_probability`/`_index`/`_mask`/`_repr`）+ 标注 `[形状]`。**例外**：缩写 `PP`/`A`/`CCD` 在 `*_repr`、码名、开关名里保持大写（如 `PP_repr`、`run_A_graph`），更易读。算子 `PascalCase`，给"签名 / 定义 / 是否用几何 / 是否等变 / 是否更新坐标 / 成本"。
>
> **核心结构（本版定稿）**：匹配分**细分支**（逐对全量 cross-attn，info-rich 但 set-blind）与**粗分支**（压缩代表向量做集合推理，提供全局先验、可分 chunk），两支的码并进打分 MLP。所有跨/自注意力统一走一个原语 `TypedAttention`（多类 typed Q/KV + 可选分类 softmax + 可选 BiasMLP 偏置）。
>
> **组装分两套（共享算子与表示前导）**：**Stage2 = 可配置 Block 栈**（两相执行：相 1 整图便宜、相 2 逐对可 chunk；trunk 更新 + 粗细分支 + 块内监督）；**Stage3 = 独立 `Stage3Builder`**（外层 `[B_pairs]` 比 Stage2 少一维、无粗分支、写回 + 扩散）。底层算子（`TypedAttention` / `SparseGraphInteraction` / `LigandPairFormer` / 融合算子）与表示前导两套共用。
>
> **第一版默认 vs 实验档**：默认精简档——细分支对 PP/A **解耦**；粗分支默认 **2 类 rep**（`CCD_repr` + 耦合 `blob_repr`），**4 类 rep 为并列一等实验**（早晚都要跑，非边角消融）。Stage2 跨集合 cross-attn **只读不写回**，Stage3 写回。context 图只实现 gated 消息传递（A-only）；配体内部直接复用 Emap2lig `PairFormer`；不实现等变坐标更新 / 3D RoPE / softmax 版 context 图。
>
> **flash / eager**：无逐对 bias 的注意力走 flash-attn（已在目标老 glibc 装好）；带逐对 bias 的走 eager / torch SDPA mem-efficient（见 §2.2、§13）。两条 kernel 自动切换，并备无 flash 兜底。

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
| density_point_ligand_area_probability | [n_blobs, max_density_points] | Stage1 预测"该 PP 属 ligand-area"概率。作 PP 节点输入特征；**可选**作 bias_feat（detach，§2.2/§3）。 |
| receptor_atom_features | [n_blobs, max_receptor_atoms, d] | 受体口袋原子（A）表示。A ~256–512（k-NN/radius 截断）。 |
| receptor_atom_coords | [n_blobs, max_receptor_atoms, 3] | A 的 map 帧坐标。 |
| receptor_binding_probability | [n_blobs, max_receptor_atoms] | Stage1 预测"该受体原子在配体 4Å 内"概率（F1≈0.65 > ligand-area 0.55）。作 A 节点输入特征；作 A 图消息 bias_feat（detach）。 |
| receptor_edge_index | [2, n_receptor_edges_total] | A 内部稀疏图边（**COO 扁平**，blob 间用 `receptor_edge_batch` 切分）。键 ∪ radius。 |
| receptor_edge_features | [n_receptor_edges_total, d_edge] | 边特征：距离 GaussianSmearing（⊕ 两端结合概率，作消息 bias，§2.1）。 |
| receptor_edge_batch | [n_receptor_edges_total] | 每条边归属的 blob 索引（COO 批切分）。 |
| context_node_type | [n_blobs, max_density_points + max_receptor_atoms] | PP、A 沿 token 轴拼接后的**长整型类别标签**（PP=0 / A=1），作 `TypedAttention` 的 `keyvalue_type`。 |
| CCD_repr | [n_slots, d] | 粗分支：配体代表向量（持久残差状态；压缩源 ⊕ slot_index_embedding ⊕ count 嵌入）。 |
| blob_repr | [n_blobs, d] | 粗分支**默认**：耦合 (PP,A) 的 blob 代表向量（持久残差）。承担 blob 级 count 预算 explaining-away。 |
| PP_repr / A_repr | [n_blobs, d] | 粗分支**4 类实验**：密度级 / 口袋级两条独立 rep（与 2 类并列一等，§7/§14）。 |
| fine_code_recall[k] | list, 每个 [n_blobs, n_slots, d] | 细分支 recall 码列表（长度 = recall 侧 kv 类别数；配体当 query、各 kv 类各 softmax 各读出）。 |
| fine_code_precision[k] | list, 每个 [n_blobs, n_slots, d] | 细分支 precision 码列表（PP / A 各当 query attend 配体，各读出）。 |
| coarse_match_recall[k] | list, 每个 [n_blobs, n_slots, d] | 粗分支 recall 匹配描述（`CCD_repr` × blob 全 (PP,A)，typed + split；**rep 已是单向量，输出直接成形、无需 readout**）。 |
| coarse_match_precision | [n_blobs, n_slots, d] | 粗分支 precision 匹配描述（`blob_repr` × 配对 ccd 全原子；4 类时再加 `PP_repr/A_repr × ccd`）。 |
| coverage_recall_logit | [n_blobs, n_slots] | 预测 α̂：配体被该 blob 捕获比例。 |
| coverage_precision_logit | [n_blobs, n_slots] | 预测 β̂：该 blob 被配体解释比例。 |
| coverage_recall_target / coverage_precision_target | [n_blobs, n_occurrences] | 标签 α=\|b∩g\|/\|g\|、β=\|b∩g\|/\|b\|（密度量；身份内匈牙利配 slot↔occurrence）。 |

> `n_slots = Σ_j N_j`。`*_repr` 是单向量摘要（持久残差状态，§7）；细分支保留全量逐原子/逐点。粗/细各产各的码，打分 MLP 输入维自由拼接（不要求码数相等）。

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
**边特征只进 MP（§2.1），不进 TypedAttention**：后者只收"逐 token 的 bias_feat + 坐标"，内部用 BiasMLP 现算偏置，不收通用逐对 edge 张量——否则要 materialize 偏置、丢 flash kernel。

### 2.1 `SparseGraphInteraction`（A 内部图；第一版 = gated MP）

`receptor_atom_features ← SparseGraphInteraction(receptor_atom_features, receptor_edge_index, receptor_edge_features, receptor_edge_batch)`

- **定义**（COO 扁平、PocketXMol `NodeBlock` 式）：逐边 `msg = message_mlp(edge_mlp(edge_features) ⊙ node_mlp(neighbor))`；`gate = sigmoid(gate_mlp(edge_features, neighbor))`；`scatter_sum`（不归一化）；残差 + LayerNorm + out_transform。
- **A-only**：只在受体节点跑，无 PP/A typed 分支。
- **结合概率进消息 bias**：边特征拼两端 `receptor_binding_probability`（**detach**）。MP 本就逐边算消息，加概率天然、不涉 flash。
- **用几何**：是（边含距离 GaussianSmearing，间接）。**等变**：否。**更新坐标**：否。**块数 ~4**（对齐 Emap2lig `InstanceSeg` `num_blocks=4`，浅层避免过平滑）。

### 2.2 `TypedAttention`（统一跨/自注意力原语；从头写）

`out ← TypedAttention(query_features, keyvalue_features, query_type=None, keyvalue_type=None, split_type_kv=False, query_bias_feat=None, keyvalue_bias_feat=None, query_coords=None, keyvalue_coords=None)`

- **统一 self / cross**：self = `keyvalue_features is query_features`；caller 决定残差写回（Stage3）还是新建张量只读（Stage2），算子本身只返回输出。
- **typed 投影（多类）**：`query_type` / `keyvalue_type` 是**长整型类别张量**（任意 K 类），按类别选类型专属 Q / K / V 投影；`None` = 单类型。
- **`split_type_kv`**（仅 `keyvalue_type` 非 None 生效）：`False` = 所有 kv 类同一 softmax（类间抢质量），返回 1 个张量；`True` = 每类各自 softmax，**返回长度 = kv 类别数的张量列表**（位置索引，2 类/4 类写法天然一致）。**不对称**：split 只在 KV 侧有意义（query 侧从不共享 softmax，多类 query 天然各算各、各自输出）。
- **偏置 = 内部 BiasMLP，不是预加张量**：`bias_ij = BiasMLP( [相对坐标编码(q_coord_i, kv_coord_j) 若给坐标] ⊕ query_bias_feat_i ⊕ keyvalue_bias_feat_j )`。`*_bias_feat` 装 detach 后的概率等逐 token 标量。这避免"概率只能整行/整列广播"。**只有 kv 概率、无坐标、无 q 概率时自然退化为 per-key 先验**（仅依赖 j），正确、非缺陷。
- **bias 是 per-attn opt-in，默认在 PP 重注意力上关闭**：PP 当 kv（~4096–8192）时材化逐对 bias 会逼 eager + 巨额显存（§13 量化），**故细分支 recall、Stage2 那些 PP 重 cross-attn 默认不开 bias、概率只作节点输入特征**；bias 仅在便宜处开（A 图 MP、Stage3 单对几何 cross-attn、rep 级）。
- **kernel 分流**：无 bias → flash-attn；带逐对 bias → torch SDPA mem-efficient（吃加性 `attn_mask`）或 eager；二者皆备**无 flash 兜底**。
- **用几何**：可选（Stage2 否 / Stage3 是）。**等变**：否。**更新坐标**：否。
- **复用边界**：**不直接 import** Emap2lig `SelectedCrossAttention`（无双侧 typed、无 split、无 BiasMLP）；借其脚手架**改写**。

### 2.3 `LigandPairFormer`（= 直接复用 Emap2lig `PairFormer`，不重写）

`ligand_atom_features, ligand_pair_features ← LigandPairFormer(ligand_atom_features, ligand_pair_features, masks)`

- **定义** = `BiasedSelfAttention`(AttentionPairBias) + `OuterProductMeanToPair` + `TrianglePairUpdate`(TriangleMul out/in + TriangleAttn start/end) + Transition，堆若干层。
- **死条件已核**：`emap2lig/model/modules/pairformer.py::PairFormer` 接口（atom/pair/mask，批维=slot）直接吃配体张量，至多改 config → **import 复用**。实测尺寸 `d_atom=128`、`d_pair=64`、`num_blocks=4`、`max_atoms` 上限 200。
- **显存**：三角注意力 O(N³) 激活是大头；开**激活检查点（PyTorch 原生 `torch.utils.checkpoint`，避开 fairscale/老 glibc）**后，50–100 slot 在 80G 从容（§13）。

### 2.4 `BiasedSelfAttention` / `OuterProductMeanToPair` / `TrianglePairUpdate`

PairFormer 组件（定义见 2.3 / AF3）。粗分支同类 rep 的 self-attn 直接用 `TypedAttention`（self、无 bias）。

### 2.5 `LearnedQueryReadout`（集合 → 码；可切均值）

`code ← LearnedQueryReadout(item_features, item_mask, mode="learned_query")`

- `mode="learned_query"`：可学习查询对 `item_features` 按 mask 池化成向量。`mode="mean"`：直接均值池化（廉价基线，对应总规划 §12 readout 消融）。
- **用处**：(1) 细分支把逐对网格的 `max_lig`/`max_dp` 维池掉；(2) 粗分支**初始 rep 压缩**（§7a）。**粗分支的 rep×实体匹配描述不用它**——rep 已是单向量、输出已成形（§7c）。

### 2.6 融合算子（同位多源 vs 空间，必须分开）

- `FuseSources(main_features, aux_source_features, probability=None)`：**同位多源融合**（同一点/原子的若干来源并成一个）。默认 **FiLM**（主 = 原始手工编码，其余源 ⊕ 概率 出 (γ,β) 调制 main）；gated-sum / S-token 小自注意作消融。PP（S 轴）、A（S 轴）各一次。
- `FusePtoPP(density_point_features, stage1_P_features)`：**空间融合**（PP 向邻近 P，KNN/radius、同帧、几何，吸收源④⑤）。内核 **cross-attn / MP**，**非 FiLM**。

---

## §3 三种实体与位置不对称

| 实体 | 主特征 | 坐标 | 内部边 |
| --- | --- | --- | --- |
| 配体原子（1 slot） | ligand_atom_features | 仅 Stage3 有坐标 | ligand_pair_features（化学） |
| 密度点 PP（1 blob） | density_point_features + ligand_area 概率 | density_point_coords | 无（不做内部图） |
| 受体原子 A（1 blob 口袋） | receptor_atom_features + binding 概率 | receptor_atom_coords | 键 ∪ radius（COO） |

**位置不对称**（反作弊，见 `模型总规划_v2.md` §1.4）：同帧侧（PP/A）几何可用；**跨到配体**——Stage2 `query_coords=None`（给即泄露 GT），Stage3 给配体噪声坐标。**PP 与 A 不直接耦合**（无密-受边），只经配体（细分支）与 `blob_repr`（粗分支）间接相遇。

**概率注入（统一规则）**：`ligand_area`（PP）/ `binding`（A）概率 (1) **一律拼进节点输入特征**（免费、保 flash）；(2) **可选**作 `TypedAttention` 的 `*_bias_feat` 进 BiasMLP（一律 detach；由专属辅助头负责预测，消费方不反向训练预测器）。**bias 仅在便宜处开**：A 图（边两端 2 概率 + 距离，MP 天然）、Stage3 单对几何 cross-attn（坐标 + 概率）。**PP 重注意力（细分支 recall、Stage2 跨集合）默认不开 bias**——那里只有 kv 概率、无坐标，BiasMLP 退化为 per-key 先验，增益薄而代价是丢 flash + 材化巨阵（§13），不值；概率留作节点特征足矣。

---

## §4 表示前导（迭代前，只构建三类实体初始表示）

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

产出的三类初始特征是**共享 trunk 的起点**；Stage2 Block（§5）/ Stage3Builder（§10）在其上更新、压缩、读出。

---

## §5 Stage2 可配置 Block（trunk 更新 + 粗细分支 + 块内监督；两相执行）

**不强求"统一抽象成一个 Block 跑 num_Block 次"**，做成**可配置大类**，每层独立配置：

| 逐层开关 | 取值 | 说明 |
| --- | --- | --- |
| `run_pairformer` | bool | 这层是否跑配体 PairFormer（trunk 更新）。 |
| `run_A_graph` | bool | 这层是否跑 A 图 `SparseGraphInteraction`（trunk 更新）。 |
| `big_xattn` | {none, readonly} | 这层"大型"逐对 cross-attn：不跑 / Stage2 read-only 细分支。（写回属 Stage3Builder，§10。） |
| `coarse_on` | bool | 这层是否跑粗分支（压缩/更新 rep + rep-rep，§7）。 |
| `loss_cfg` | 配置组 | 这层各损失族开关/权重/类型：粗分支损失、细分支损失、各层次（整 vs 塌缩）监督、辅助头（§8/§12）。 |

**监督隐式，不再设 `sup` 枚举**：哪个分支开了、`loss_cfg` 里相应损失开了，就监督它（read-only 细 cross-attn 若不接监督就是死代码，故"开即监督"是对的；显式监督开关至多留作核验）。

**两相执行（chunk + 全局视野同时成立的关键）**：

1. **相 1（整图、便宜、激活保留）**：trunk 更新（PairFormer per-slot、A 图 per-blob，均**非** per-pair）+ 压缩/更新 rep + rep-rep 集合推理（rep 单向量、几十~上百 token）。在**所有 blob/slot** 上算。
2. **相 2（逐对、昂贵、可 chunk）**：`big_xattn=readonly` 的细分支 + 粗分支 `rep×实体` + 块内打分，在 `[n_blobs, n_slots]` 网格上**分 chunk**、逐 chunk 回传、梯度累积。

跨层只保留相 1 的 trunk + rep 激活（per-blob/slot + 微小 rep，可控）；相 2 每 chunk 用完即释放。**因此 Block 不能作为整体一次性 chunk，但其中昂贵的相 2 可以分 chunk。** 深监督默认只放末 1–2 层（中间层 `coarse_on=true、big_xattn=none`，或全关），控算力。

**配置组织（Hydra）**：定义少数**命名 block 预设**（如 `trunk_block`=仅 trunk 更新；`coarse_block`=trunk+粗分支；`readout_block`=+readonly 细分支+全损失）+ 一个 `block_schedule` 列表引用它们 + 各自 `loss_cfg`。层大多同质，预设+排程比逐层抄整份 dict 清爽；Stage2、Stage3 各一份短排程。

---

## §6 细分支（逐对全量 cross-attn，read-only → 读出码；默认解耦 PP/A）

```python
# 批量在 [n_blobs, n_slots] 网格；输出是【新建逐对 grid 张量】，绝不写回共享 trunk

# recall：配体当 query attend (PP,A)；typed KV + split → 返回"和 kv 类别同数"的张量列表
fine_probe_recall = TypedAttention(                          # split=True → list（2 类即 [对PP, 对A]，4 类同理）
        query_features    = ligand_atom_features,
        keyvalue_features = stack(density_point_features, receptor_atom_features),
        keyvalue_type     = context_node_type,
        split_type_kv     = True,                            # 默认解耦：避免 PP(~4096) 在联合 softmax 淹没 A(~512)
        query_coords      = None)                            # Stage2 无几何；PP 重注意力默认不开 bias（§3）
fine_code_recall = [LearnedQueryReadout(p, ligand_atom_mask) for p in fine_probe_recall]

# precision：PP、A 各当 query attend 配体（query 侧天然分离，不需 split）
fine_code_precision = [
    LearnedQueryReadout(TypedAttention(density_point_features,  ligand_atom_features, query_coords=None), density_point_mask),
    LearnedQueryReadout(TypedAttention(receptor_atom_features,  ligand_atom_features, query_coords=None), receptor_atom_mask)]
```

**read-only 是 Stage2 硬约束**：`fine_probe_*` 是逐对网格新建张量，绝不回灌共享 `ligand_atom_features`/`density_point_features`——网格里绝大多数错配对，回灌等于用噪声污染被全图复用的共享表示。要多层逐对精炼可在**网格内部链式**（下层 query = 上层 grid 输出，仍逐对、不碰共享），末端读出。

> **Stage3 相反**：单对正确配对，`TypedAttention` 残差**写回**配体（§10）。

---

## §7 粗分支（集合推理；默认 2 类 / 4 类并列；持久残差 rep；可分 chunk）

```python
# 约定：粗分支每次读共享 trunk / 细分支侧变量，默认 detach（开关 coarse_detach，§7 末）

# (a) 初始压缩成代表向量（持久残差状态的起点）
CCD_repr  = LearnedQueryReadout(detach(ligand_atom_features), ligand_atom_mask) + count_embedding   # [n_slots, d]
blob_repr = LearnedQueryReadout(detach(stack(density_point_features, receptor_atom_features)), ctx_mask)  # [n_blobs, d]，耦合 (PP,A)
# 4 类实验：额外 PP_repr / A_repr = LearnedQueryReadout(detach(PP)/detach(A))（与 2 类并列一等，§14）

# (b) 重复 L_coarse；Order B：先跨类 cross-attn、后同类 self-attn；持久残差
for layer in coarse_layers:
    # trunk 更新过的层额外回吸当前 trunk（per-blob/slot、相 1 内、便宜）
    if layer.trunk_updated:
        blob_repr = blob_repr + TypedAttention(blob_repr, keyvalue=detach(stack(density_point_features, receptor_atom_features)))
        CCD_repr  = CCD_repr  + TypedAttention(CCD_repr,  keyvalue=detach(ligand_atom_features))
    # 跨类 rep-rep（KV=reps，平衡，默认不 split）
    CCD_repr  = CCD_repr  + TypedAttention(CCD_repr,  keyvalue=blob_repr)
    blob_repr = blob_repr + TypedAttention(blob_repr, keyvalue=CCD_repr)
    # 同类 self-attn（blob 级竞争 → count 预算 explaining-away）
    CCD_repr  = CCD_repr  + TypedAttention(CCD_repr,  CCD_repr)
    blob_repr = blob_repr + TypedAttention(blob_repr, blob_repr)

# (c) 末尾：rep × 跨类未塌缩实体（detach 实体）→ 匹配描述（rep 已单向量，输出直接成形，无 readout）
coarse_match_recall    = TypedAttention(CCD_repr,  keyvalue=detach(stack(density_point_features, receptor_atom_features)),
                                        keyvalue_type=context_node_type, split_type_kv=True)   # list（2/4 类一致）
coarse_match_precision = TypedAttention(blob_repr, keyvalue=detach(ligand_atom_features))       # [n_blobs, n_slots, d]
```

- **Order B 理由（结构性）**：explaining-away 竞争须 match-aware——blob 先在跨类 cross-attn 拿到"我对各 ligand 的匹配强度"，**再**在同类 self-attn 与其他 blob 竞争。故跨类先于同类。
- **持久残差 rep**：`rep_l = rep_{l-1} + Δ`，让全局推理逐层累积（胜过每层从头重压）；初始压缩 = `LearnedQueryReadout`（可切均值，§2.5）；trunk 冻结后不再回吸。
- **粗分支极廉价**：rep×实体的 query 是单向量，比细分支全×全省掉 K 侧 ~4096 那档；flash 不材化 scores + chunk，100×200×（4 类）量级毫无压力。故 2 类 vs 4 类**不是算力问题、纯建模选择**：2 类（耦合 blob_repr）契合 blob 级 explaining-away 粒度，4 类多给密度级/口袋级两条独立竞争通道——两者并列一等、早晚都跑。
- **split 分位置**：rep×**实体**（KV=全 PP+A 点，失衡）→ `split=True`；rep-rep（KV=reps，平衡）→ 默认不 split。
- **detach 默认（`coarse_detach=True`）**：粗分支每次读 trunk/实体都 detach → 只读集合推理器，不反向塑造 trunk，且不必为它保留 trunk 激活（chunk 便宜前提，§11）。**注意**：detach 不影响粗分支自身参数受训——其码拼进 §8 MLP、被覆盖损失直接监督。`coarse_detach=False` 是"让全局反哺 trunk"的有理由可选档（§14）。

---

## §8 打分（粗 + 细 → 覆盖矩阵；逐支损失各自可配）

```python
coverage_recall_logit    = sigmoid(MLP_recall   (concat(*fine_code_recall,    *coarse_match_recall)))      # [n_blobs, n_slots]
coverage_precision_logit = sigmoid(MLP_precision (concat(*fine_code_precision,  coarse_match_precision)))   # [n_blobs, n_slots]
```

- 两头分参数；输入维随粗/细码数自由拼接（码数不必相等）。
- **损失分工（`loss_cfg` 逐层/逐支可配权重/类型）**：覆盖标签既有**回归**（smooth-L1/MSE vs α/β）又有**分类**（阈值二值化 A'/B' + focal/CE）。
  - **粗分支中间监督**：着重 **A'/B' 分类**（粗 rep 细节盲、宜判"匹不匹配"，恰是 explaining-away 处）。
  - **细分支中间监督**：着重**回归**（逐对细节足以拟合精确覆盖值）。
  - **末端监督**：拼全源、**回归+分类都做**——粗分支即使中间只挂分类，也经末端 MLP 吃回归梯度，不饿死。
  - 各层次（整 vs 塌缩）、逐原子/逐点辅助等都在 `loss_cfg` 里逐层开关。
- slot↔occurrence 走身份内匈牙利（`模型总规划_v2.md` §6/§8）。

---

## §9 Stage2 整图前向（整图、无逐对循环）

```python
# 1. 表示前导（§4）：PP/A/CCD 各自批量构建初始表示
# 2. Block 栈（§5）逐层：相 1 整图（trunk 更新 + 粗分支压缩/rep-rep，便宜、激活保留、不 chunk）
#                        相 2 逐对（big_xattn=readonly 的细分支 / rep×实体 / 打分，[n_blobs,n_slots] 网格、可 chunk）
# 3. 末端打分（§8）→ coverage_*_logit → 身份内匈牙利损失 + 块内深监督 + 辅助损失（§12）
```

"逐对"是张量前置批维 `[n_blobs, n_slots]`，非 Python 循环。

## §10 Stage3Builder（独立组装；[B_pairs] × 扩散步；trunk 缓存；写回 + 无粗分支）

Stage3 外层是 `[B_pairs]`（比 Stage2 少一维）、无集合可推理（单对）、写回 + 扩散——**不塞进 Block，单独组装，只共用算子与表示前导**。

```python
# 堆多个独立正确配对 (blob, ligand) 成 batch [B_pairs]
# 表示前导 + trunk 更新（PairFormer/A 图）算一次（不依赖噪声坐标，跨扩散步缓存）
trunk_cache = build_and_update_trunk(...)          # 复用 §2 算子；无粗分支、无 read-only 细分支
for t in diffusion_steps:
    h = ligand_atom_features
    for _ in range(couple):    # couple=int：写回式逐对耦合层数
        h = TypedAttention(h, keyvalue=stack(density_point_features, receptor_atom_features),
                           keyvalue_type=context_node_type, split_type_kv=True,
                           query_coords=ligand_atom_coords_t, keyvalue_coords=context_coords)  # 几何开（可带几何 bias）+ 残差写回 h
    ligand_atom_coords_t = DiffusionDenoiseHead(h, ligand_atom_coords_t, trunk_cache)          # 复用 Emap2lig AtomDiffusion
# use_receptor=False ⇒ context 只剩 PP ⇒ 精确退回 Emap2lig
```

**Stage2 / Stage3 四处差别**：① 细分支输出（只读→readout / 写回→扩散）；② 粗分支（Stage2 有 / Stage3 无）；③ 几何（无 / 有）；④ 批量与组装（`[n_blobs,n_slots]` 网格 Block 栈 / `[B_pairs]`×扩散步 Stage3Builder）。**底层算子全部同一套**。

---

## §11 chunk 训练策略（全局视野 + 显存可控）

- **整图、便宜、保留**（相 1）：表示前导 + 每层 trunk 更新 + 粗分支压缩/rep-rep，在所有 blob/slot 上算（trunk 是 per-blob/slot、rep 单向量），给每 rep 注入全局先验。
- **逐对、昂贵、chunk**（相 2）：细分支 + 粗分支 `rep×实体` 在 `[n_blobs, n_slots]` 网格分 chunk、各 chunk 独立回传、梯度累积。
- 每 chunk 用到的 rep **已全局感知**（相 1 跑过），故分 chunk 仍有全图视野。`coarse_detach` 让粗分支不必保留 trunk 激活，chunk 显存再省。
- **PairFormer 显存**：开 PyTorch 原生激活检查点后，50–100 slot 的相 1 在 80G 从容（§13）。

---

## §12 监督全清单（两级辅助 + 覆盖；预期有效性已标）

| 损失 | 挂在哪 | 说明 / 预期有效性 |
| --- | --- | --- |
| Loss_coverage（主） | coverage_recall/precision_logit | 软回归 + 阈值 focal + 身份内匈牙利。 |
| 粗分支块内深监督 | 粗分支专属 MLP（逐层 `loss_cfg`） | **着重 A'/B' 分类**；末几层廉价深监督，推动 rep 全局推理早对齐。 |
| 粗 rep 全局属性 | CCD_repr / blob_repr（/ PP_repr,A_repr） | 预测口袋/PP/配体的大小、形状、分子量、原子数 → **正则/防 rep 塌缩**（非供梯度，粗分支本就有梯度）。 |
| 细 ligand 逐原子/键属性 | ligand_atom_features / ligand_pair_features | 复用 Emap2lig `AuxiliaryModule`（元素/手性/环 + 键类型/环/存在 + pair 距离，可选）→ 防配体表示塌缩。 |
| Loss_binding | binding 概率重预测头（A 上） | 反向监督受体结合概率；也支撑"概率作 bias 时已 detach"的解耦（§3）。 |
| ligand_area 辅助 | ligand_area 概率重预测头（PP 上） | 对称于结合概率，可选。 |
| 逐原子/逐点覆盖辅助 | fine_probe_* 读出前 | 逐配体原子"被覆盖" / 逐 PP"属于"，可选细粒度深监督。 |

> **去掉 `slot_is_present`**（假定 count 正确）。每个辅助头标了预期作用；上线前评估，不无脑堆。所有损失项的开关/权重/类型挂在逐层 `loss_cfg`（§5/§8）。

---

## §13 Emap2lig 复用映射 + 环境依赖与计算效率

| 我们的部件 | Emap2lig 来源 | 复用方式 |
| --- | --- | --- |
| LigandPairFormer（配体内部） | modules/pairformer.py::PairFormer | import 复用，至多改 config |
| 细 ligand 辅助头 | modules/pairformer.py::AuxiliaryModule | 复用（可选） |
| PP 初始化 gather | modules/instance_seg.py::select_top_k_points | 复用 |
| Stage3 扩散头 | modules/diffusion.py::AtomDiffusion | 复用（受体作额外条件） |
| TypedAttention（跨/自集合） | layers/selected_attention.py::SelectedCrossAttention | **改写**：借脚手架，新增 typed 双 mask + split + BiasMLP + flash/eager 分流 |
| SparseGraphInteraction（A 图） | 无（参照 PocketXMol NodeBlock，去坐标更新、COO） | 自写小模块 |
| FuseSources / FusePtoPP / 粗细分支 / 打分 MLP | 无 | 自写 |

**环境依赖（计划须提）**：
- `flash-attn`：已在目标老 glibc 装好（✓）。
- **激活检查点用 PyTorch 原生 `torch.utils.checkpoint`，不依赖 fairscale**（其 `checkpoint_wrapper` 走 fairscale，老 glibc<2.17 装轮子困难）。
- **eager / SDPA 路径无额外安装门槛**：纯 PyTorch（`F.scaled_dot_product_attention` 的 mem-efficient 后端 + `nn.Linear` BiasMLP），与 glibc 无关；老 glibc 上可直接用。
- 版本契约（CUDA / torch / flash-attn / glibc 下限）落盘。

**flash vs eager 计算效率（为何 bias 默认不上 PP 重注意力）**：
- flash-attn 不材化 `[n_q, n_kv]` 分数矩阵，显存 O(n_q·n_kv)→O(n_q·d)、速度因省 HBM 读写常见快 2–4×；n_kv 越大增益越高。
- **细分支 PP 重 cross-attn 若 eager 材化分数**：约 `n_q(=max_lig≈64) × n_kv(=PP≈4096) × heads(≈8) × 2B ≈ 4 MB / (blob,slot) 对`，整张 100×200 网格 ≈ **80 GB 仅分数**——故这里 **flash 是刚需、非可选**。
- **带逐对 BiasMLP 偏置必须材化 `[n_q,n_kv]` 偏置张量**（无法塞进 flash kernel），等于丢掉上面的 flash 增益。所以**绝不在 PP 重注意力上挂逐对 bias**；bias 只用于 n_kv 小处（A 图 ~512、Stage3 单对几何、rep 级 几十~上百），那里材化偏置便宜、flash 不关键，eager/SDPA 即可。

---

## §14 默认值表 + 消融钩子

| 旋钮 | 默认值 | 触发/作用条件 | 对应实验/消融 |
| --- | --- | --- | --- |
| 细分支 PP/A 解耦 | **解耦**（recall `split_type_kv=True`、precision 分两 query） | 全程；recall 因 PP≫A 失衡须分 softmax | 联合 softmax |
| 粗分支 rep 类数 | **2 类**（CCD + 耦合 blob） | 全程 | **4 类（+PP_repr/A_repr）——并列一等、早晚跑** |
| 粗分支 rep-rep 是否 split | 不 split（reps 平衡） | rep-rep 跨类 | split |
| 粗分支 detach | **detach**（`coarse_detach=True`，只读推理器） | 全程；省 chunk 显存 | `coarse_detach=False`（全局反哺 trunk，显存多一档） |
| rep 更新 | **持久残差 + trunk 回吸（仅更新层）** | §7b | 每层从头重压（对照） |
| 概率作 attn bias | **PP 重注意力关、A 图/Stage3 几何开** | 仅 n_kv 小处材化偏置 | PP 注意力也开 bias（需评估 flash 损失） |
| 概率作节点特征 | **开** | 全程（免费、保 flash） | 关 |
| readout 模式 | **learned_query** | 细分支池化 / 初始 rep 压缩 | mean |
| big_xattn | 末 1–2 层 readonly，中间 none | 控深监督算力 | 全层 readonly |
| 同位多源融合 | **FiLM** | PP/A 各一次 | gated-sum / S-token 小自注意 |
| PP↔P 融合 | **cross-attn/MP**（空间） | 表示前导一次 | 关（= Emap2lig 式消融，无 P） |
| A 图块数 | ~4 | 对齐 Emap2lig | softmax 版 context 图 |
| 激活检查点 | **开（torch 原生）** | PairFormer 相 1 | 关（显存够时） |
| attn kernel | **无 bias→flash / 有 bias→SDPA-eager**，备无 flash 兜底 | 自动分流 | 全 eager（调试） |
| couple（Stage3） | int（写回耦合层数） | Stage3Builder | full（每块写回） |
| PP 数目 | 4096 | 显存旋钮 | 512 / 8192 |

**钩子（非第一版）**：3D RoPE、等变坐标更新 / DiffDock 张量场（排除）；粗分支 Order A 对照；难负身份配额；全图自然假阳 vs context-box 假阳。

> 横向对照（AF3 / PocketXMol / DiffDock / Emap2lig 用同一套算子）见 `参照算法_迭代运算梳理_AF3_PocketXMol.md`。
