# AdaLigand Stage2 / Stage3 迭代运算设计

> **本文定位**：`模型总规划_v2.md` 的**运算模块说明书**。前者讲"匹配预测什么、损失/数据/解码怎么定义"（**是什么**）；本文讲"这些表示如何一层层算出来、用哪些算子、Stage2/Stage3 如何共用代码"（**怎么算**）。两文合起来自包含；本文在运算层面自包含（术语见 §1/§2，首次出现即定义）。**盘上数据怎么存/拆/添油见 `BOX-level数据契约.md`（数据契约唯一权威）；本文 §4 只讲"块怎么拼成张量"。**
>
> **命名规则**：特征张量 `snake_case` + 后缀（`_features`/`_coords`/`_logit`/`_target`/`_probability`/`_index`/`_mask`/`_repr`）+ 标注 `[形状]`。**例外**：缩写 `PP`/`A`/`CCD` 在 `*_repr`、码名、开关名里保持大写（如 `PP_repr`、`run_A_graph`），更易读。算子 `PascalCase`，给"签名 / 定义 / 是否用几何 / 是否等变 / 是否更新坐标 / 成本"。
>
> **核心结构**：匹配分**细分支**（逐对全量 cross-attn，info-rich 但 set-blind）与**粗分支**（压缩代表向量做集合推理，提供全局先验、极廉价、默认不分 chunk），两支的码并进打分 MLP。所有跨/自注意力统一走一个原语 `TypedAttention`（多类 typed Q/KV + 可选分类 softmax + 可选 BiasMLP 偏置）。
>
> **组装分两套（共享算子与表示前导）**：**Stage2 = 可配置 Block 栈**（两相执行：相 1 整图便宜、相 2 逐对默认不分 chunk、超规模再分 chunk §11；trunk 更新 + 粗细分支 + 块内监督）；**Stage3 = 独立 `Stage3Builder`**（外层 `[B_pairs]` 比 Stage2 少一维、无粗分支、写回 + 扩散）。底层算子（`TypedAttention` / `SparseGraphInteraction` / `LigandPairFormer` / 融合算子）与表示前导两套共用。
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
| slot_index_embedding | [n_slots, d] | 身份内副本索引 e_s（身份内匈牙利，见 模型总规划_v2.md §6），表示前导末尾早期注入。 |
| density_point_features | [n_blobs, max_density_points, d] | 密度点（PP）表示。批维 = blob。PP ~4096（可配 8192）。 |
| density_point_coords | [n_blobs, max_density_points, 3] | PP 的 map 帧坐标。 |
| density_point_ligand_area_probability | [n_blobs, max_density_points] | Stage1 预测"该 PP 属 ligand-area"概率。作 PP 节点输入特征；可选作 bias_feat（detach，§2.2/§3）。 |
| receptor_atom_features | [n_blobs, max_receptor_atoms, d] | 受体口袋原子（A）表示。A ~256–512（k-NN/radius 截断）。 |
| receptor_atom_coords | [n_blobs, max_receptor_atoms, 3] | A 的 map 帧坐标。 |
| receptor_binding_probability | [n_blobs, max_receptor_atoms] | Stage1 预测"该受体原子在配体 4Å 内"概率（F1≈0.65 > ligand-area 0.55）。作 A 节点输入特征；作 A 图消息 bias_feat（detach）。 |
| receptor_edge_index | [2, n_receptor_edges_total] | A 内部稀疏图边（COO 扁平，blob 间用 receptor_edge_batch 切分）。键 ∪ radius。 |
| receptor_edge_features | [n_receptor_edges_total, d_edge] | 边特征：距离 GaussianSmearing（⊕ 两端结合概率，作消息 bias，§2.1）。 |
| receptor_edge_batch | [n_receptor_edges_total] | 每条边归属的 blob 索引（COO 批切分）。 |
| context_node_type | [n_blobs, max_density_points + max_receptor_atoms] | PP、A 沿 token 轴拼接后的长整型类别标签（PP=0 / A=1），作 TypedAttention 的 keyvalue_type。 |
| ligand_atom_mask | [n_slots, max_ligand_atoms] | 配体原子合法性（pad=0）。PairFormer、CCD_repr 压缩、recall probe 读出消费。 |
| density_point_mask | [n_blobs, max_density_points] | PP 合法性（pad=0）。 |
| receptor_atom_mask | [n_blobs, max_receptor_atoms] | A 合法性（pad=0）。 |
| context_mask | [n_blobs, max_density_points + max_receptor_atoms] | PP、A 拼接轴合法性（= 代码里的 ctx_mask；blob_repr 压缩、跨集合 cross-attn 消费）。 |
| CCD_repr | [n_slots, d] | 粗分支：配体代表向量（持久残差状态；压缩源 ⊕ slot_index_embedding ⊕ count 嵌入）。 |
| blob_repr | [n_blobs, d] | 粗分支默认：耦合 (PP,A) 的 blob 代表向量（持久残差）。承担 blob 级 count 预算 explaining-away。 |
| PP_repr / A_repr | [n_blobs, d] | 粗分支4 类实验：密度级 / 口袋级两条独立 rep（与 2 类并列一等，§7/§14）。 |
| fine_probe_recall[k] | list（k=kv 类别；默认 2 类 k∈{0,1}=PP/A，4 类 k∈{0,1,2,3}），每个 [n_blobs, n_slots, max_ligand_atoms, d] + ligand_atom_mask | 细分支 recall 读出前逐对 probe（配体当 query attend 各 kv 类）。逐配体原子辅助损失（§12）挂这里。 |
| fine_code_recall[k] | list, 每个 [n_blobs, n_slots, d] | recall probe 经 LearnedQueryReadout 池掉 max_ligand_atoms 轴得码（各 kv 类各 softmax 各读出）。 |
| fine_code_precision[k] | list（k=query 实体，2 类即 PP-query / A-query），每个 [n_blobs, n_slots, d] | 细分支 precision 码（PP / A 各当 query attend 配体）。precision 走融合 readout：PP 当 query 流式累加直接出码、不材化整张逐点 probe（§11），故无 fine_probe_precision 落地张量。 |
| coarse_match_recall[k] | list（k 同上，2/4 类一致），每个 [n_blobs, n_slots, d] | 粗分支 recall 匹配描述（CCD_repr × blob 全 (PP,A)，typed + split）。无 max_len 轴——rep 已是单向量、attend 完直接成形、无需 readout（与细分支 probe 的关键不对称）。 |
| coarse_match_precision | [n_blobs, n_slots, d] | 粗分支 precision 匹配描述（blob_repr × 配对 ccd 全原子；4 类时再加 PP_repr/A_repr × ccd）。 |
| coverage_recall_logit | [n_blobs, n_slots] | 预测 α̂：配体被该 blob 捕获比例。**A/B 回归头，密度档才开**（§8）。 |
| coverage_precision_logit | [n_blobs, n_slots] | 预测 β̂：该 blob 被配体解释比例。**A/B 回归头，密度档才开**。 |
| coverage_O_logit | [n_blobs, n_slots] | 预测对称 Ô（跨档统一分类目标）。其打分头吃**两方向拼接**的码（§8）。 |
| coverage_recall_target / coverage_precision_target | [n_blobs, n_occurrences] | 连续标签 α=|b∩g|/|g|、β=|b∩g|/|b|（密度量；身份内匈牙利配 slot↔occurrence）。 |
| coverage_O_target | [n_blobs, n_occurrences] | 对称二值标签 O：密度档 = IoU(b,g)>τ；纯受体档 = dist(box 中心, occ 质心)<ρ（见 `模型总规划 §5.3`）。 |

> `n_slots = Σ_j N_j`。`*_repr` 是单向量摘要（持久残差状态，§7）；细分支 recall 保留全量逐原子 probe，precision 走融合 readout、不材化逐点（§11）。粗/细各产各的码，打分 MLP 输入维自由拼接（不要求码数相等）。
> **监督口径（与 `模型总规划 §5.3/§6.6` 对齐）**：O 是跨档统一的分类目标，A/B 是密度档才开的连续回归。**凡损失含 O，O 头拼接两方向（recall+precision，粗+细）的码**；最终（密度档）A/B/O 同时上。

---

## §1.5 前导 / trunk / 粗分支 / 细分支 参数归属（地基）

> 两阶段冻结/门控的一切都挂在"哪些算子和参数归谁"上，故先把归属定死。**关键：把"全前向只跑一次的前导"与"每个 Block 内重复的 trunk 更新"分开**——前者是 Block 外的一次性词干，后者才是单 Block 内的角色。本表是后续 §5/§7/§8/§11 的前提。

| 归属 | 含哪些算子/状态 | 参数训练时机 |
|---|---|---|
| **前导（once，全前向一次、Block 外）** | embedding + PP 表示前导（采样/`FuseSources`/`FusePtoPP`，§4）+ A 同位融合 + CCD 构象编码 + **代表向量 repr 的 seed 初始化**（`LearnedQueryReadout`，§7a） | phase-aware（见下）：阶段一训；阶段二**冻结**这套前导 |
| **trunk（per-Block 更新）** | 配体 `LigandPairFormer`（§2.3）+ 受体 A 图 `SparseGraphInteraction`（§2.1），每个 Block 跑一次 | 阶段一训前 m 段；阶段二冻前 m、**从头训后 n** |
| **粗分支** | repr 的**后续更新**：rep-rep（跨类/同类 self-attn）+ **实体回吸**（rep×实体，§7）+ 粗匹配描述 + 粗打分 | 阶段一训全部 m+n（后 n 不开回吸）；阶段二冻前 m、训后 n（回吸带零初始化门） |
| **细分支** | 逐对全量 cross-attn（read-only）+ readout 成码 + 细打分（§6/§8） | 阶段二训（仅末块/末段，§5） |

**前导是 phase-aware 的，别当铁板一块**：阶段一的整套前导（含 repr seed）在阶段二**冻结**；但阶段二后段 trunk 走"从头原始重嵌"（§5.1），那是阶段二**新训**的一套重嵌入（如 CCD 嵌入），与阶段一前导是两套东西。**repr seed 偏偏不重做**——它绑定阶段一前导、随之冻，因为粗分支的 rep 是从阶段一一路带过来的持久状态。

**seed 的来源**：repr seed 在前导层（所有 Block 之前）readout，故它压的是**只 embed、还没过 PairFormer / A 图的原始嵌入级实体**；rep 之后靠每个 Block 末尾的实体回吸（§7 b'）把 trunk 演化的信息吸进来。

**切法要点**：repr 的 **seed 归前导、更新归粗分支**；PP 全程冻结（被动 K/V，§3），不属任何可训分支的更新对象。模块命名须留 pattern 钩子（`stem.*` / `trunk.block.{i}.*` / `coarse.block.{i}.*` / `fine.*`），供 §11 的 pattern 冻结精准命中。

---

## §2 算子词典

### 2.0 导言：两族、各取一段、为何

交互分两族：**(i) 注意力 + 显式 pair**（AF3 / Emap2lig）；**(ii) 稀疏消息传递（message passing, MP）**（PocketXMol / DiffDock）。按子任务各取一段，且都落在**非等变标量特征**上（Stage2 预测覆盖**标量**，不变量、不需等变；Stage3 走 Emap2lig 非等变注意力扩散）：

| 子任务 | 用哪族 | 理由 |
| --- | --- | --- |
| A 内部图 | (ii) gated MP | 受体是稀疏键图，累加式聚合 + 距离乘性消息是 MP 长处（softmax 会归一化掉"邻居越多越强"）。 |
| 配体内部 | (i) PairFormer | 小化学图，三角更新 O(n³) 可接受；直接复用 Emap2lig。 |
| 配体↔(PP,A) / 粗分支所有 attn | (i) TypedAttention | 配体 Stage2 无坐标，只能特征空间；统一原语，支持 typed Q/KV。 |

**PP 不做内部图 MP**（只在表示前导里初始化 + 同位多源融合 + 与 P 空间融合）。 **边特征只进 MP（§2.1），不进 TypedAttention**：后者只收"逐 token 的 bias_feat + 坐标"，内部用 BiasMLP 现算偏置，不收通用逐对 edge 张量——否则要 materialize 偏置、丢 flash kernel。

### 2.1 `SparseGraphInteraction`（A 内部图；第一版 = gated MP）

`receptor_atom_features ← SparseGraphInteraction(receptor_atom_features, receptor_edge_index, receptor_edge_features, receptor_edge_batch)`

- **定义**（COO 扁平、PocketXMol `NodeBlock` 式）：逐边 `msg = message_mlp(edge_mlp(edge_features) ⊙ node_mlp(neighbor))`；`gate = sigmoid(gate_mlp(edge_features, neighbor))`；`scatter_sum`（不归一化）；残差 + LayerNorm + out_transform。
- **A-only**：只在受体节点跑，无 PP/A typed 分支。
- **结合概率进消息 bias**：边特征拼两端 `receptor_binding_probability`（**detach**）。MP 本就逐边算消息，加概率天然、不涉 flash。
- **用几何**：是（边含距离 GaussianSmearing，间接）。**等变**：否。**更新坐标**：否。**块数 \~4**（对齐 Emap2lig `InstanceSeg` `num_blocks=4`，浅层避免过平滑）。

### 2.2 `TypedAttention`（统一跨/自注意力原语；从头写）

`out ← TypedAttention(query_features, keyvalue_features, query_type=None, keyvalue_type=None, split_type_kv=False, query_bias_feat=None, keyvalue_bias_feat=None, query_coords=None, keyvalue_coords=None)`

- **统一 self / cross**：self = `keyvalue_features is query_features`；caller 决定残差写回（Stage3）还是新建张量只读（Stage2），算子本身只返回输出。
- **typed 投影（多类）**：`query_type` / `keyvalue_type` 是**长整型类别张量**（任意 K 类），按类别选类型专属 Q / K / V 投影；`None` = 单类型。
- **`split_type_kv`**（仅 `keyvalue_type` 非 None 生效）：`False` = 所有 kv 类同一 softmax（类间抢质量），返回 1 个张量；`True` = 每类各自 softmax，**返回长度 = kv 类别数的张量列表**（位置索引，2 类/4 类写法天然一致）。**不对称**：split 只在 KV 侧有意义（query 侧从不共享 softmax，多类 query 天然各算各、各自输出）。
- **偏置 = 内部 BiasMLP，不是预加张量**：`bias_ij = BiasMLP( [相对坐标编码(q_coord_i, kv_coord_j) 若给坐标] ⊕ query_bias_feat_i ⊕ keyvalue_bias_feat_j )`。`*_bias_feat` 装 detach 后的概率等逐 token 标量。这避免"概率只能整行/整列广播"。**只有 kv 概率、无坐标、无 q 概率时自然退化为 per-key 先验**（仅依赖 j），正确、非缺陷。
- **bias 是 per-attn opt-in，默认在 PP 重注意力上关闭**：PP 当 kv（\~4096–8192）时材化逐对 bias 会逼 eager + 巨额显存（§13 量化），**故细分支 recall、Stage2 那些 PP 重 cross-attn 默认不开 bias、概率只作节点输入特征**；bias 仅在便宜处开（A 图 MP、Stage3 单对几何 cross-attn、rep 级）。
- **kernel 分流**：无 bias → flash-attn；带逐对 bias → torch SDPA mem-efficient（吃加性 `attn_mask`）或 eager；二者皆备**无 flash 兜底**。
- **用几何**：可选（Stage2 否 / Stage3 是）。**等变**：否。**更新坐标**：否。
- **复用边界**：**不直接 import** Emap2lig `SelectedCrossAttention`（无双侧 typed、无 split、无 BiasMLP）；借其脚手架**改写**。

### 2.3 `LigandPairFormer`（= 直接复用 Emap2lig `PairFormer`，不重写）

`ligand_atom_features, ligand_pair_features ← LigandPairFormer(ligand_atom_features, ligand_pair_features, masks)`

- **定义** = `BiasedSelfAttention`(AttentionPairBias) + `OuterProductMeanToPair` + `TrianglePairUpdate`(TriangleMul out/in + TriangleAttn start/end) + Transition，堆若干层。
- **死条件已核**：`emap2lig/model/modules/pairformer.py::PairFormer` 接口（atom/pair/mask，批维=slot）直接吃配体张量，至多改 config → **import 复用**。实测尺寸 `d_atom=128`、`d_pair=64`、`num_blocks=4`、`max_atoms` 上限 200。
- **显存**：三角注意力 O(N³) 激活是大头；开\*\*激活检查点（PyTorch 原生 `torch.utils.checkpoint`，避开 fairscale/老 glibc）\*\*后，50–100 slot 在 80G 从容（§13）。

### 2.4 `BiasedSelfAttention` / `OuterProductMeanToPair` / `TrianglePairUpdate`

PairFormer 组件（定义见 2.3 / AF3）。粗分支同类 rep 的 self-attn 直接用 `TypedAttention`（self、无 bias）。

### 2.5 `LearnedQueryReadout`（集合 → 码；可切均值）

`code ← LearnedQueryReadout(item_features, item_mask, mode="learned_query")`

- `mode="learned_query"`：可学习查询对 `item_features` 按 mask 池化成向量。`mode="mean"`：直接均值池化（廉价基线，对应总规划 §12 readout 消融）。
- **用处**：(1) 细分支把逐对网格的 `max_lig`/`max_dp` 维池掉；(2) 粗分支**初始 rep 压缩**（§7a）。**粗分支的 rep×实体匹配描述不用它**——rep 已是单向量、输出已成形（§7c）。
- **融合/流式变体（precision 方向 PP 当 query）**：边 attend 边在线累加 readout（跑动加权和+归一化分母，flash 式），不材化逐对逐点 probe `[n_blobs, n_slots, max_dp, d]`，把 precision 显存承重项从 `O(n_blobs·n_slots·max_dp·d)` 压到 `O(tile)`（§11）。仅在 precision 用；recall（配体当 query、`max_lig` 小）保留普通 readout 以留 probe 给逐配体原子辅助损失。

### 2.6 融合算子（同位多源 vs 空间，必须分开）

- `FuseSources(main_features, aux_source_features, probability=None)`：**同位多源融合**（同一点/原子的若干来源并成一个）。默认 **FiLM**（主 = 原始手工编码，其余源 ⊕ 概率 出 (γ,β) 调制 main）；gated-sum / S-token 小自注意作消融。PP（S 轴）、A（S 轴）各一次。
- `FusePtoPP(density_point_features, stage1_P_features, probability=None)`：**空间融合**（PP 向 KNN/radius 邻近 P，同帧、几何，吸收源④⑤）。**可以考虑: Pock_Plus 分类头式截断 cross-attn + MLP(可默认) 或 SparseGraphInteraction(只更新PP)**，若是前者, 用相对坐标 + 两侧 `ligand_area` 概率进 BiasMLP（截断后材化 bias 便宜、不涉位置泄露）；**非 FiLM**。套1 全局 flash 无 bias 作消融、暂不写（§4/§14）。

### 2.7 批维契约（Stage2 网格 / Stage3 对批 / COO 切分；统一约定，落地前必须钉死）

> 收口一条长期张力：算子的**运算方式**前文都定了，但**怎么划 batch**没写明。本节把"批维"做成显式契约——算子签名只认 `[*batch, n_tokens, d]` + 模式 + mask，Stage2 与 Stage3 的差别**全部**落在 `*batch` 取值与模式选择上，算子本体不分叉。这是"底层算子全部同一套"（§10）能成立的前提。

所有 token 级算子（`TypedAttention` / `LigandPairFormer` / `LearnedQueryReadout` / `FuseSources` / `FusePtoPP`）输入统一为 `[*batch, n_tokens, d]`，`*batch` 是一个或多个前导批维，算子在 `*batch` 上彼此独立、不跨 batch 混合。各处 `*batch` 取值固定如下：

| 运算 | *batch | 说明 |
| --- | --- | --- |
| Stage2 per-slot trunk（配体 PairFormer、CCD_repr 压缩） | (n_slots,) | 每身份副本一条，互不相干。 |
| Stage2 per-blob trunk（A 图、blob 实体、blob_repr 压缩） | (n_blobs,) | 每 blob 一条。 |
| Stage2 逐对（细分支、rep×实体、打分） | (n_blobs, n_slots) | 覆盖网格，每对一条。 |
| Stage3 单对（写回 cross-attn、扩散去噪） | (B_pairs,) | 每个正确配对一条。 |

**`TypedAttention` 的两种批维模式（Stage2/Stage3 共用同一算子的关键，两种都必须实现）**：

- **aligned（对齐，1:1）**：`query` 与 `keyvalue` 前导批维相同，标准批注意力，输出 `[*batch, n_q, d]`。**Stage3 用这个**——`(B_pairs,)` 配体对自己 blob 的 `(B_pairs,)` 实体，逐对一一对应。
- **outer（外积网格）**：`query` 批维 `(n_slots,)` 与 `keyvalue` 批维 `(n_blobs,)` 相互独立，输出取两者外积 `[n_blobs, n_slots, n_q, d]`。**Stage2 逐对用这个**——每 slot 配体对每 blob 实体各算一份覆盖。
  - **KV 沿 slot 轴共享、绝不复制**（= 模型总规划 §11.1「K/V 按 blob 共享」的算子级落地）：outer 模式下同一 blob 的 `~4600` 个实体 token 在 `n_slots` 个 slot 间复用，按 blob 成批。**若反过来把 KV 展平成 `[n_blobs×n_slots, 4600, d]`（每 slot 复制一份 KV），仅 KV 输入就是 `100×50×4600×256×2B ≈ 12 GB`、PP=8192 时翻倍**——这是"不分 chunk 也扛得住"成立与否的命门（§11/§13）。

**COO / 稀疏张量**（`receptor_edge_index` / `receptor_edge_features` / `receptor_edge_batch`）：batch 由 `receptor_edge_batch`（每条边归属哪个 blob/样本）编码；`SparseGraphInteraction` 始终吃 COO 扁平形式，不退化成逐 batch 的 dense 循环。**Stage2 same-sample（模型总规划 §11.5，一个 batch 的 blob/CCD 同源一张图）下 `receptor_edge_batch` 只用来"区分 blob"**——不跨样本、用它时也不分 chunk；**Stage3 下 `receptor_edge_batch` 区分 `B_pairs`**。

**mask**：每个变长轴都配一个合法性张量 `*_mask [*batch, max_*]`（pad 位为 0）；算子在 softmax（masked logit 置 `-inf`）与 readout/池化（排除 pad）两处统一消费。各实体的 mask 条目在 §1 词典补全。

---

## §3 三种实体与位置不对称

| 实体 | 主特征 | 坐标 | 内部边 |
| --- | --- | --- | --- |
| 配体原子（1 slot） | ligand_atom_features | 仅 Stage3 有坐标 | ligand_pair_features（化学） |
| 密度点 PP（1 blob） | density_point_features + ligand_area 概率 | density_point_coords | 无（不做内部图） |
| 受体原子 A（1 blob 口袋） | receptor_atom_features + binding 概率 | receptor_atom_coords | 键 ∪ radius（COO） |

**位置不对称**（反作弊，见 `模型总规划_v2.md` §1.4）：同帧侧（PP/A）几何可用；**由同帧侧跨集合到配体侧时只在特征空间做**——Stage2 `query_coords=None`（给即泄露 GT），Stage3 给配体噪声坐标。**PP 与 A 不直接耦合**（无密-受边），只经配体（细分支）与 `blob_repr`（粗分支）间接相遇。

**PP 全程冻结（共享不变量）**：PP 在表示前导（§4）里一次构建后**不再更新**，自始至终是被动 K/V——Stage2 由设计（细分支 read-only、PP 无内部图）；Stage3 由 Emap2lig `PointConditioner` / `SelectedCrossAttention` 实测（残差只回写 atom、点恒只读，§13）。两个推论：逐 PP 监督无意义（§12 已删），precision 方向 readout 可融合、不材化逐点 probe（§11）。若未来某 Stage3 变体要让 PP 随扩散更新，需另加写回路、属偏离 Emap2lig 的分叉，非第一版。

**概率注入（统一规则）**：`ligand_area`（PP）/ `binding`（A）概率 (1) **可选拼进节点输入特征**（免费、保 flash）；(2) **可选**作 `TypedAttention` 的 `*_bias_feat` 进 BiasMLP（一律 detach；由专属辅助头负责预测，消费方不反向训练预测器）。**bias 仅在便宜处开**：A 图（边两端 2 概率 + 距离，MP 天然）、Stage3 单对几何 cross-attn（坐标 + 概率）。**PP 重注意力（细分支 recall、Stage2 跨集合）默认不开 bias**——那里只有 kv 概率、无坐标，BiasMLP 退化为 per-key 先验，增益薄而代价是丢 flash + 材化巨阵（§13），不值；概率留作节点特征足矣。**Stage3 反向，照常开 bias**：其 CCD×(PP&A) 单对几何 cross-attn 把相对坐标 + 两侧概率送 BiasMLP，因为它只跑 `[B_pairs]`、不跑 `[n_blobs, n_slots]` 网格——材化 `[n_lig×n_PP]` 偏置只乘 B_pairs（几十）、可承受（代价随 `B_pairs×n_PP` 线性涨，PP=8192 且 B_pairs 大时留意），与 Stage2 在整张网格上材化 ~80GB 的局面不同。可以考虑用一个或少量开关来控制上述可行范围内的概率是否纳入计算。

---

## §4 表示前导（迭代前，只构建三类实体初始表示）

```python
# 只做"特征构建"，不含 A 图迭代 / PairFormer 迭代（那两个在 Block 内，§5）

# (1) PP：采样 + 同位多源融合 + 与 P 空间融合
density_point_features = gather(voxel_feature_grid, sampled_pp_voxels)            # = Emap2lig select_top_k_points（体素中心、1Å、ligand_area 概率 top-k；始终保留为默认）
density_point_features = FuseSources(density_point_features, pp_S_sources,        # 同位多源 → FiLM
                                     probability=density_point_ligand_area_probability)
density_point_features = FusePtoPP(density_point_features, stage1_P_features,         # 截断 cross-attn+MLP（Pock_Plus 分类头式）
                                   probability=(density_point_ligand_area_probability, # 相对坐标 + 两侧 ligand_area 概率 → BiasMLP
                                                stage1_P_ligand_area_probability))     # 吸收 P 源④⑤；套1 全局 flash 暂不写

# (2) A：同位多源融合（含结合概率）
receptor_atom_features = FuseSources(receptor_atom_features, a_S_sources,
                                     probability=receptor_binding_probability)

# (3) CCD：构象编码（A 图迭代与 PairFormer 迭代都在 Block 内）
ligand_atom_features, ligand_pair_features = ConformerEmbedder(ccd)               # 复用 Emap2lig conf 路
ligand_atom_features = ligand_atom_features + slot_index_embedding               # 早期注入 e_s（方案 1）
```

产出的三类初始特征是**共享 trunk 的起点**；Stage2 Block（§5）/ Stage3Builder（§10）在其上更新、压缩、读出。

> **PP 采样粒度（`select_top_k_points`）**：Emap2lig 默认是「体素打平 `[B, D·H·W, C]` → 按 `ligand_area` 概率 top-k → gather」，坐标 = `整数体素索引 × voxel_size + origin`，即**体素中心、1Å 量化、top-k 索引天然去重**（§13 已核）。这对 Stage2 覆盖（α/β 本就是数体素的标量）无所谓，但对 Stage3 几何 cross-attn 的位置 bias 是精度地板。两个注意：(1) **可以考虑 PP 预算按真实正类体素分布定**——实测 1.7Å 包络平均 ~3000 正类体素/配体，故 `PP=4096/8192` 已越过正类、必然掺进低概率背景，盲目上 8192 多半灌背景而非加信号；(2) **始终保留 Emap2lig 默认实现可用**，更细采样（不固定体素中心 / 亚体素峰值插值 / 比 1Å 更密）只作未来钩子，不替换默认。

> **`FusePtoPP` 默认实现**：Pock_Plus 分类头式的**截断 cross-attn + MLP**（对应 `stage1_atom_head` 的 radius-graph 几何 cross-attn），PP 当 query 向 KNN/radius 邻近 P，把相对坐标 + 两侧 `ligand_area` 概率送 BiasMLP（同帧、几何合法、不涉位置泄露，故 bias 可开）。截断后分数矩阵小，材化 bias 便宜。**套1（全局 flash、无 bias、不截断）暂不写**，列为消融钩子（§14）：担心截断漏掉本该用的稀疏 P 时，先调大 K/半径，而非另接全局路。

---

## §5 Stage2 可配置 Block（trunk 更新 + 粗细分支 + 块内监督；两相执行）

**不强求"统一抽象成一个 Block 跑 num_Block 次"**，做成**可配置大类**，每层独立配置：

| 逐层开关 | 取值 | 说明 |
| --- | --- | --- |
| run_pairformer | bool | 这层是否跑配体 PairFormer（trunk 更新）。 |
| run_A_graph | bool | 这层是否跑 A 图 SparseGraphInteraction（trunk 更新）。 |
| big_xattn | {none, readonly} | 这层"大型"逐对 cross-attn：不跑 / Stage2 read-only 细分支。（写回属 Stage3Builder，§10。） |
| coarse_on | bool | 这层是否跑粗分支（压缩/更新 rep + rep-rep，§7）。 |
| loss_cfg | 配置组 | 这层各损失族开关/权重/类型：粗分支损失、细分支损失、各层次（整 vs 塌缩）监督、辅助头（§8/§12）。 |

**监督隐式，不再设 `sup` 枚举**：哪个分支开了、`loss_cfg` 里相应损失开了，就监督它（read-only 细 cross-attn 若不接监督就是死代码，故"开即监督"是对的；显式监督开关至多留作核验）。

**两相执行（chunk + 全局视野同时成立的关键）**：

1. **相 1（整图、便宜、激活保留）**：trunk 更新（PairFormer per-slot、A 图 per-blob，均**非** per-pair）+ 压缩/更新 rep + rep-rep 集合推理（rep 单向量、几十\~上百 token）。在**所有 blob/slot** 上算。
2. **相 2（逐对；默认靠 flash + precision 融合 readout【不分 chunk】，超规模再分 chunk，§11）**：`big_xattn=readonly` 的细分支 + 粗分支 `rep×实体` + 块内打分，在 `[n_blobs, n_slots]` 网格上算。

跨层只保留相 1 的 trunk + rep 激活（per-blob/slot + 微小 rep，可控）。**默认相 2 不分 chunk（flash + precision 融合 readout 已把承重项压下，§11）；超规模时相 2 可分 chunk、各 chunk 用完即释放（Block 不能整体一次性 chunk，但相 2 可以）。** 深监督默认只放末 1–2 层（中间层 `coarse_on=true、big_xattn=none`，或全关），控算力。

**配置组织（Hydra）**：定义少数**命名 block 预设**（如 `trunk_block`=仅 trunk 更新；`coarse_block`=trunk+粗分支；`readout_block`=+readonly 细分支+全损失）+ 一个 `block_schedule` 列表引用它们 + 各自 `loss_cfg`。层大多同质，预设+排程比逐层抄整份 dict 清爽；Stage2、Stage3 各一份短排程。

### 5.1 两阶段 Block 布局（m+n；课程见 `模型总规划 §6.6`）

共 **m+n 个全量 Block**（暂定 **m=2、n=4**，可调）。两阶段课程在 Block 上的落法：

| | 前 m 段 Block | 后 n 段 Block |
| --- | --- | --- |
| **阶段一（O 监督）** | trunk 更新 + 粗分支（含 per-Block 回吸，§7） | 无 trunk 更新；粗分支 rep-rep 可走，但**回吸不开**（参数留给阶段二） |
| **阶段二（A/B/O 监督）** | **冻结**（trunk + 粗分支，含其回吸） | trunk **从头训** + 粗分支回吸**新训**（零初始化门压早期噪声）+ 细分支训练 |

- **`big_xattn` 只放末块 = 临时权宜**。它是当前为控显存/算力的妥协；**未来"分 chunk + 全局视野"做实可交付后（§11），此约束作废、big_xattn 可上多层**。当前默认：仅末块（或末几块）`big_xattn=readonly`，其余 `none`。
- **逐 phase 的 run 开关**：上表的"跑/不跑/冻结"通过 §5 的逐层开关 + §11 的 pattern 冻结组合实现；后 n 段在阶段一把 `run_pairformer/run_A_graph=false`、回吸关，阶段二打开。
- **后段 trunk 的来源（§4 表示前导的变体）**：第 m+1 块 trunk **默认 = 纯从头原始重嵌**（像 Block_0 那样消化最原始特征）；**可选开关**把第 m 块（冻结）trunk 当**零初始化 condition** 注入（默认关、最稳）。零初始化保证阶段二开局是 no-op、不破坏阶段一表示，有用才长出来。注意"从头随机初始化"（新容量）与"零初始化"（注入连接）是相反两件事，别混。

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
# PP 当 query 走【融合 readout】：按 PP tile 流式 attend + 在线累加直接出码，不材化整张逐点 probe（§11）；
# 逐 PP 监督已砍（PP 全程冻结，§3/§12），故融合对主路径无损。A 当 query 便宜，正常 readout。
fine_code_precision = [
    FusedReadoutAttention(density_point_features, ligand_atom_features, density_point_mask, query_coords=None),     # PP→配体，融合/流式
    LearnedQueryReadout(TypedAttention(receptor_atom_features, ligand_atom_features, query_coords=None), receptor_atom_mask)]
```

**read-only 是 Stage2 硬约束**：`fine_probe_*` 是逐对网格新建张量，绝不回灌共享 `ligand_atom_features`/`density_point_features`——网格里绝大多数错配对，回灌等于用噪声污染被全图复用的共享表示。要多层逐对精炼可在**网格内部链式**（下层 query = 上层 grid 输出，仍逐对、不碰共享），末端读出。

> **Stage3 相反**：单对正确配对，`TypedAttention` 残差**写回**配体（§10）。

---

## §7 粗分支（集合推理；默认 2 类 / 4 类并列；持久残差 rep；极廉价、默认不分 chunk）

```python
# 约定：粗分支每次读共享 trunk / 细分支侧变量，默认 detach（开关 coarse_detach，§7 末）

# (a) seed：初始压缩成代表向量（整个 Stage2 前向【只跑一次】；之后持久残差累积、不再重压。
#     seed 必须用 readout——此时还没有 rep 可拿来当 query）
CCD_repr  = LearnedQueryReadout(detach(ligand_atom_features), ligand_atom_mask) + count_embedding   # [n_slots, d]
blob_repr = LearnedQueryReadout(detach(stack(density_point_features, receptor_atom_features)), ctx_mask)  # [n_blobs, d]，耦合 (PP,A)
# 4 类实验：额外 PP_repr / A_repr = LearnedQueryReadout(detach(PP)/detach(A))（与 2 类并列一等，§14）

# (b) 重复 L_coarse；每层只做廉价 rep-rep（KV=reps，几十~上百 token）；Order B：先跨类、后同类；持久残差
for layer in coarse_layers:
    # 跨类 rep-rep（KV=reps，平衡，默认不 split）
    CCD_repr  = CCD_repr  + TypedAttention(CCD_repr,  keyvalue=blob_repr)
    blob_repr = blob_repr + TypedAttention(blob_repr, keyvalue=CCD_repr)
    # 同类 self-attn（blob 级竞争 → count 预算 explaining-away）
    CCD_repr  = CCD_repr  + TypedAttention(CCD_repr,  CCD_repr)
    blob_repr = blob_repr + TypedAttention(blob_repr, blob_repr)

# (b') 实体回吸（rep 自己当 query 读 trunk 实体，B 形）：每个 Block 末尾做【一次】。
#      "不逐层"指上面 (b) 的内 coarse_layers 循环不要每圈都回吸，【不是 Block 级】——per-Block 一次反而更
#      state-relevant：每个 Block 的 reps 读的是该 Block 刚更新过的 trunk。成本可控：rep×实体的 query 是
#      单向量（flash 不材化分数），~ n_reps×4600×d 近线性，per-Block 累计仍便宜。
#      （A 经 A 图更新；PP 冻结，故回吸主要刷新 A 侧。）用 rep×实体而非再 readout——状态相关、更强。
#      两阶段（§5.1）：阶段一前 m 段各 Block 做回吸；后 n 段【不做】（参数留阶段二）。
#      阶段二后 n 段新训回吸，开局硬冻 k 个 epoch（如 1）让新鲜 trunk 先稳，再用零初始化门 ramp 放开；前 m 段回吸冻结。
blob_repr = blob_repr + gate * TypedAttention(blob_repr, keyvalue=detach(stack(density_point_features, receptor_atom_features)))  # gate: 后n段阶段二零初始化门
CCD_repr  = CCD_repr  + gate * TypedAttention(CCD_repr,  keyvalue=detach(ligand_atom_features))

# (c) 末尾：rep × 跨类未塌缩实体（detach 实体）→ 匹配描述（rep 已单向量，输出直接成形，无 readout）
coarse_match_recall    = TypedAttention(CCD_repr,  keyvalue=detach(stack(density_point_features, receptor_atom_features)),
                                        keyvalue_type=context_node_type, split_type_kv=True)   # list（2/4 类一致）
coarse_match_precision = TypedAttention(blob_repr, keyvalue=detach(ligand_atom_features))       # [n_blobs, n_slots, d]
```

- **Order B 理由（结构性）**：explaining-away 竞争须 match-aware——blob 先在跨类 cross-attn 拿到"我对各 ligand 的匹配强度"，**再**在同类 self-attn 与其他 blob 竞争。故跨类先于同类。
- **持久残差 rep**：`rep_l = rep_{l-1} + Δ`，让全局推理逐层累积（胜过每层从头重压）。**seed = `LearnedQueryReadout`，整个前向只一次**（此时无 rep 可当 query，只能 readout，可切均值 §2.5）；**rep-rep 在内 `coarse_layers` 循环里每圈做**；**实体回吸（rep×实体，B 形）每个 Block 末尾做一次**——"不逐层"是指内循环不逐圈做，**不是 Block 级**（per-Block 反而读到该 Block 最新 trunk、更 state-relevant；query 单向量、便宜，见 (b') 注释）。PP 冻结、A 才是回吸刷新的对象（指令 2/3）。两阶段下回吸的开/冻/门见 §5.1。
- **粗分支极廉价**：rep×实体的 query 是单向量，比细分支全×全省掉 K 侧 \~4096 那档；flash 不材化 scores + chunk，100×200×（4 类）量级毫无压力。故 2 类 vs 4 类**不是算力问题、纯建模选择**：2 类（耦合 blob_repr）契合 blob 级 explaining-away 粒度，4 类多给密度级/口袋级两条独立竞争通道——两者并列一等、早晚都跑。
- **split 分位置**：rep×**实体**（KV=全 PP+A 点，失衡）→ `split=True`；rep-rep（KV=reps，平衡）→ 默认不 split。
- **detach 默认（`coarse_detach=True`）**：粗分支每次读 trunk/实体都 detach → 只读集合推理器，不反向塑造 trunk，且不必为它保留 trunk 激活（chunk 便宜前提，§11）。**注意**：detach 不影响粗分支自身参数受训——其码拼进 §8 MLP、被覆盖损失直接监督。`coarse_detach=False` 是"让全局反哺 trunk"的有理由可选档（§14）。

---

## §8 打分（粗 + 细 → 覆盖矩阵；逐支损失各自可配）

```python
# O 头（跨档统一分类）：吃【两方向】（recall+precision，粗+细）的码拼接
coverage_O_logit         = sigmoid(MLP_O(concat(*fine_code_recall, *fine_code_precision,
                                                *coarse_match_recall, coarse_match_precision)))            # [n_blobs, n_slots]
# A/B 回归头（仅密度档激活；纯受体档 mask 掉 B、A 退化为距离）
# 粗分支两方向匹配描述（*coarse_match_recall + coarse_match_precision）都拼进 A、B 两头——它是方向无关的
# 全局 explaining-away 上下文（某 blob 被全局解释掉 → 它对本配体的 recall 与 precision 都该降），对两头都有用；
# 细码则按方向对齐（A 拼 fine_recall、B 拼 fine_precision，不跨享）。
coverage_recall_logit    = sigmoid(MLP_recall   (concat(*fine_code_recall,    *coarse_match_recall, coarse_match_precision)))      # [n_blobs, n_slots]
coverage_precision_logit = sigmoid(MLP_precision (concat(*fine_code_precision, *coarse_match_recall, coarse_match_precision)))   # [n_blobs, n_slots]
```

- **三头分参数**；输入维随粗/细码数自由拼接（码数不必相等）。
- **三头都吃粗分支两方向的码**：粗匹配描述（recall+precision）是方向无关的全局 explaining-away 信号，O/A/B 三头都拼；细码按方向对齐（A↔fine_recall、B↔fine_precision）。凡损失含 O 就两方向都拼（`模型总规划 §5.3/§8`）。最终（密度档）A/B/O 三头同时监督；纯受体档只开 O 头（A 用距离、B mask）。课程见 §5.1 与 `模型总规划 §6.6`。
- **损失分工（`loss_cfg` 逐层/逐支可配权重/类型）**：**分类 = 对称 O**（focal/CE，跨档统一，`模型总规划 §5.3`）；**回归 = 连续 A/B**（smooth-L1/MSE vs α/β，**仅密度档**）。
  - **粗分支中间监督**：着重 **O 分类**（粗 rep 细节盲、宜判"匹不匹配"，恰是 explaining-away 处）。
  - **细分支中间监督**：着重 **A/B 回归**（逐对细节足以拟合精确覆盖值；密度档）。
  - **末端监督**：拼全源、**O 分类 + A/B 回归都做**——粗分支即使中间只挂 O 分类，也经末端 MLP 吃回归梯度，不饿死。
  - **课程（§5.1）**：阶段一只 O；阶段二 A/B/O。
  - 各层次（整 vs 塌缩）、逐配体原子辅助等都在 `loss_cfg` 里逐层开关（逐 PP 已删，§12）。
- slot↔occurrence 走身份内匈牙利（`模型总规划_v2.md` §6/§8）。

---

## §9 Stage2 整图前向（整图、无逐对循环）

```python
# 1. 表示前导（§4）：PP/A/CCD 各自批量构建初始表示
# 2. Block 栈（§5）逐层：相 1 整图（trunk 更新 + 粗分支压缩/rep-rep，便宜、激活保留、不 chunk）
#                        相 2 逐对（big_xattn=readonly 的细分支 / rep×实体 / 打分，[n_blobs,n_slots] 网格；默认不分 chunk，§11）
# 3. 末端打分（§8）→ coverage_*_logit → 身份内匈牙利损失 + 块内深监督 + 辅助损失（§12）
```

"逐对"是张量前置批维 `[n_blobs, n_slots]`，非 Python 循环。

## §10 Stage3Builder（独立组装；\[B_pairs\] × 扩散步；trunk 缓存；写回 + 无粗分支）

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

**先讲结论：第一版默认路径是「不分 chunk」。** 三件事叠起来让目标规模（`n_blobs≤200`、`n_slots≤100`、`PP=4096`）在 80G 上整图前向+回传可行：(1) PP 重注意力走 flash（不材化 `[n_q,n_kv]` 分数，§13）；(2) outer 模式 KV 按 blob 共享、不沿 slot 复制（§2.7），省掉把 `~4600` token KV 复制 `n_slots` 倍的几十 GB；(3) **precision 方向（PP 当 query）的 readout 融进注意力**（见下），把唯一的显存承重项从 `O(n_blobs·n_slots·max_dp·d)` 压到 `O(tile)`。

**两相结构（即便不分 chunk 也是这个数据流）**：

- **相 1（整图、便宜、保留）**：表示前导 + 每层 trunk 更新（PairFormer per-slot、A 图 per-blob）+ 粗分支压缩/rep-rep，在所有 blob/slot 上算，给每 rep 注入全局先验。
- **相 2（逐对、可融合/可分块）**：细分支 + 粗分支 `rep×实体` + 打分，在 `[n_blobs, n_slots]` 网格上算。

**precision 方向 readout 融合（本节定为默认；§6 的 readout 与 §12 的逐点损失在定稿时据此对齐）**：早池化是「先算整张逐点 probe `[n_blobs, n_slots, max_dp, d]`（`PP=4096` 约 10.5GB、`8192` 约 21GB、激进规模 `200×100×8192` 约 84GB）→ 再 readout 成 `[n_blobs, n_slots, d]`」。融合做法把 PP 这条 query 轴切瓦片（tile，如 512 点）流式跑、用 flash 式在线累加（跑动加权和 `S` + 归一化分母 `Z`，带最大值防溢出），算完即扔，从不同时存全部逐点向量，峰值降到一个 tile（激进规模约 5.2GB）。**唯一代价是「逐 PP 辅助损失」拿不到整张逐点 probe——而该损失本就该砍**：PP 初始化后全程不更新（Stage2 由设计；Stage3 由 Emap2lig `PointConditioner` / `SelectedCrossAttention` 实测，点恒为被动 K/V、残差只回写 atom，§13），无可防的逐点表示塌缩，且「属不属配体」已由 Stage1 `ligand_area` 概率作节点特征携带、冗余。故融合对主路径无损。recall 方向（配体当 query、`max_lig≤200`）便宜，保留正常 readout 与逐配体原子辅助损失（配体全程更新）。

**分 chunk 是兜底能力（非默认，但必须可用且测过）。** 当规模/旋钮超出上面（再叠大 PP + 大网格，或临时关掉融合）时，相 2 在 `[n_blobs, n_slots]` 网格分 chunk、各 chunk 独立回传、梯度累积。其 autograd 契约必须显式遵守：

- **相 1 算一次、缓存、所有 chunk 共享，绝不每 chunk 重算**：相 1 含 PairFormer 这种贵算子，重算 `C` 次就是 `C` 倍 trunk 浪费——这是分 chunk 最大的正确性陷阱。
- **相 1 输出 detach 成 leaf**；相 2 每个 chunk 从该 leaf 前向+回传、把 `.grad` 累加到 leaf；全部 chunk 完成后对相 1 做**一次** backward。
- **块间深监督**只是多个挂在各自相 2 输出上的 loss 站点，彼此可叠加。
- **持久残差 rep** 跨所有 coarse 层连成一条图，但 rep 是单向量、极小，保留无所谓；`coarse_detach`（§7）让粗分支不必保留 trunk 激活，chunk 显存再省。
- **算力中性**：切的是「对子」这条批维、不是 attention 内部 token 轴，前向 FLOPs 与不分块逐字相等；唯一额外开销是对相 2 开激活检查点时的约 +0.3 倍重算。**分 chunk 贵在工程正确性，不贵在算力。**

**三处风险**：(1) detach 边界写错 → 梯度漏算或重复；(2) `retain_graph` 用错 → 显存爆；(3) 多块共享 trunk 的图保留策略。

**签字前必过的验证**：搭一个「2 块 × 2 chunk 的玩具网络，对比分块与不分块的梯度逐元素相等」的测试。这个梯度等价测试是分 chunk 路径可信的必经门槛。

**PairFormer 显存（与上面网格内存正交）**：PairFormer 只跟 `(n_slots, max_lig)` 走、**不随 `n_blobs`**；三角注意力 `O(max_lig³)` 激活是大头，开 PyTorch 原生激活检查点后，`max_lig≤200`、`50–100 slot` 在 80G 从容（§13，**需实测 profile 确认**，非已验证）。

> **运行节奏**：Stage2 真负样本依赖全图划窗推理的原生数据（模型总规划 §11.3，20–30d，与 Stage3 训练并行），在它就绪前的一切 Stage2 运行本质是试跑。故第一版把「默认不分 chunk + 融合 readout」跑起来即可，分 chunk 的 autograd 契约与梯度等价测试作为已验证能力备着、不在关键路径上。

### 11.6 两阶段冻结/解冻机制（课程 §5.1 / `模型总规划 §6.6` 的落地）

机制分两类，**别混**：

- **硬阶段边界（phase1 → phase2）= pattern 冻结 + 权重接力**。阶段一跑完一个 run；阶段二开新 run、**只载权重（不载 optimizer/scheduler/step）**、按 §1.5 命名 pattern 冻结「前导 stem + 前 m trunk + 前 m 粗分支」。沿用 Pocket_Plus `train.py` 三个**已验证原语**当设计（代码可重写）：pattern 匹配设 `requires_grad`（命中 0 报错的硬保护）、完全冻结子树切 `eval`（停 BN/Dropout）、checkpoint 只载权重。**前置 = §1.5 的命名纪律**，否则 pattern 命不中。
- **软时间 ramp（同 run 内）= 模型侧带调度的零初始化门**，不动 `requires_grad`。用于：后 n 段回吸的早期抑制（§7 的 `gate`）、第 m 块 trunk condition 的零初始化注入（§5.1）。门 `g(step)`：**前 k 个 epoch 硬置 0（让从头 trunk 先稳）、之后 ramp 0→1 over warmup**，确定、对 checkpoint 友好，避开"run 内动态改 requires_grad + 重建 optimizer param group"的坑。

> **不背 Pocket_Plus `train.py` 包袱**：它写法烂、功能不全（无 run 内灵活冻结/解冻），Stage2/3 须大幅重构或重写；只继承上面三原语的**设计**，不复用其代码。**`big_xattn 只末块` 是临时权宜**（§5.1）：等本节"分 chunk + 全局视野"做实可交付，big_xattn 可上多层、此约束作废。当前暂定 m=2、n=4（可调）。

---

## §12 监督全清单（两级辅助 + 覆盖；预期有效性已标）

| 损失 | 挂在哪 | 说明 / 预期有效性 |
| --- | --- | --- |
| Loss_coverage（主） | coverage_O_logit（分类，跨档）+ coverage_recall/precision_logit（A/B 回归，密度档） | O focal/CE + A/B 软回归 + 身份内匈牙利。课程 §5.1：阶段一只 O、阶段二 A/B/O。 |
| 粗分支块内深监督 | 粗分支专属 MLP（逐层 loss_cfg） | 着重 **O 分类**（粗 rep 细节盲、宜判匹配）；末几层廉价深监督，推动 rep 全局推理早对齐。 |
| 粗 rep 全局属性 | CCD_repr / blob_repr（/ PP_repr,A_repr） | 预测口袋/PP/配体的大小、形状、分子量、原子数 → 正则/防 rep 塌缩（非供梯度，粗分支本就有梯度）。 |
| 细 ligand 逐原子/键属性 | ligand_atom_features / ligand_pair_features | 复用 Emap2lig AuxiliaryModule（元素/手性/环 + 键类型/环/存在 + pair 距离，可选）→ 防配体表示塌缩。 |
| Loss_binding | binding 概率重预测头（A 上） | 反向监督受体结合概率；也支撑"概率作 bias 时已 detach"的解耦（§3）。 |
| ligand_area 辅助 | ligand_area 概率重预测头（PP 上） | 对称于结合概率，可选。 |
| 逐配体原子覆盖辅助 | fine_probe_recall 读出前 | 逐配体原子"被覆盖"，可选细粒度深监督（配体全程更新，有意义）。**逐 PP"属于"已删**——PP 初始化后全程冻结（§3），无可防的逐点表示塌缩、且与 Stage1 ligand_area 概率冗余；precision 故走融合 readout 不材化逐点 probe（§11）。 |

> **去掉 `slot_is_present`**（假定 count 正确）。每个辅助头标了预期作用；上线前评估，不无脑堆。所有损失项的开关/权重/类型挂在逐层 `loss_cfg`（§5/§8）。

---

## §13 Emap2lig 复用映射 + 环境依赖与计算效率

| 我们的部件 | Emap2lig 来源 | 复用方式 |
| --- | --- | --- |
| LigandPairFormer（配体内部） | modules/pairformer.py::PairFormer | import 复用，至多改 config |
| 细 ligand 辅助头 | modules/pairformer.py::AuxiliaryModule | 复用（可选） |
| PP 初始化 gather | modules/instance_seg.py::select_top_k_points | 复用 |
| Stage3 扩散头 | modules/diffusion.py::AtomDiffusion | 复用（受体作额外条件） |
| TypedAttention（跨/自集合） | layers/selected_attention.py::SelectedCrossAttention | 改写：借脚手架，新增 typed 双 mask + split + BiasMLP + flash/eager 分流 |
| SparseGraphInteraction（A 图） | 无（参照 PocketXMol NodeBlock，去坐标更新、COO） | 自写小模块 |
| FuseSources / FusePtoPP / 粗细分支 / 打分 MLP | 无 | 自写 |
| 训练循环 / 两阶段冻结调度 | Pocket_Plus `src/train.py`（弃用脚手架） | **重写**；只继承三原语的设计：pattern 冻结（命中 0 报错）、冻结子树切 eval、checkpoint 只载权重（§11.6） |

**环境依赖（计划须提）**：

- `flash-attn`：已在目标老 glibc 装好（✓）。
- **激活检查点用 PyTorch 原生 `torch.utils.checkpoint`，不依赖 fairscale**（其 `checkpoint_wrapper` 走 fairscale，老 glibc<2.17 装轮子困难）。
- **eager / SDPA 路径无额外安装门槛**：纯 PyTorch（`F.scaled_dot_product_attention` 的 mem-efficient 后端 + `nn.Linear` BiasMLP），与 glibc 无关；老 glibc 上可直接用。
- 版本契约（CUDA / torch / flash-attn / glibc 下限）落盘。

**flash vs eager 计算效率（为何 bias 默认不上 PP 重注意力）**：

- flash-attn 不材化 `[n_q, n_kv]` 分数矩阵，显存 O(n_q·n_kv)→O(n_q·d)、速度因省 HBM 读写常见快 2–4×；n_kv 越大增益越高。
- **细分支 PP 重 cross-attn 若 eager 材化分数**：约 `n_q(=max_lig≈64) × n_kv(=PP≈4096) × heads(≈8) × 2B ≈ 4 MB / (blob,slot) 对`，整张 100×200 网格 ≈ **80 GB 仅分数**——故这里 **flash 是刚需、非可选**。
- **带逐对 BiasMLP 偏置必须材化 `[n_q,n_kv]` 偏置张量**（无法塞进 flash kernel），等于丢掉上面的 flash 增益。所以**绝不在 PP 重注意力上挂逐对 bias**；bias 只用于 n_kv 小处（A 图 \~512、Stage3 单对几何、rep 级 几十\~上百），那里材化偏置便宜、flash 不关键，eager/SDPA 即可。

---

## §14 默认值表 + 消融钩子

| 旋钮 | 默认值 | 触发/作用条件 | 对应实验/消融 |
| --- | --- | --- | --- |
| 细分支 PP/A 解耦 | 解耦（recall split_type_kv=True、precision 分两 query） | 全程；recall 因 PP≫A 失衡须分 softmax | 联合 softmax |
| 粗分支 rep 类数 | 2 类（CCD + 耦合 blob） | 全程 | 4 类（+PP_repr/A_repr）——并列一等、早晚跑 |
| 粗分支 rep-rep 是否 split | 不 split（reps 平衡） | rep-rep 跨类 | split |
| 粗分支 detach | detach（coarse_detach=True，只读推理器） | 全程；省 chunk 显存 | coarse_detach=False（全局反哺 trunk，显存多一档） |
| rep 更新 | 持久残差；seed readout 1 次 + 内循环每圈 rep-rep + **实体回吸每 Block 1 次**（B 形） | §7 | 每层从头重压；只打分前回吸 1 次 |
| 概率作 attn bias | PP 重注意力关、A 图/Stage3 几何开 | 仅 n_kv 小处材化偏置 | PP 注意力也开 bias（需评估 flash 损失） |
| 概率作节点特征 | 开 | 全程（免费、保 flash） | 关 |
| readout 模式 | recall=learned_query；precision=融合 readout（PP 当 query 流式、不材化逐点 probe，§11） | 细分支池化 / 初始 rep 压缩 | mean；precision 不融合（材化逐点 probe，需大显存、可挂逐 PP 损失） |
| big_xattn | 末 1–2 层 readonly，中间 none（**临时权宜**，§5.1/§11.6） | 控深监督算力；分 chunk+全局视野做实后作废 | 全层 readonly |
| 监督标签集 | O 分类（跨档）+ A/B 回归（密度档） | §5.3/§8 | 只 O；A'/B' 二值（不跑：分类有 O、回归有连续 A/B，A'/B' 三不管） |
| 两阶段课程 | 阶段一 O / 阶段二 A/B/O；冻前 m、训后 n | §5.1/§11.6 | 联合一阶段；不冻 |
| m / n 划分 | m=2、n=4 | §5.1 | 可调 |
| 后段 trunk 的 m 层 condition | 关（纯从头重嵌） | §5.1 | 开（零初始化注入冻结 trunk） |
| 后 n 段回吸零初始化门 | 开（前 k epoch 硬冻 + 之后 ramp，§11.6） | §7/§11.6 | 关（直接放开，可能早期噪声） |
| 同位多源融合 | FiLM | PP/A 各一次 | gated-sum / S-token 小自注意 |
| PP↔P 融合 | 截断 cross-attn+MLP（Pock_Plus 分类头式，相对坐标+两侧 ligand_area 概率进 BiasMLP） | 表示前导一次 | 关（无 P，= Emap2lig 式）；使用PocketSmol式的图融合; 套1 全局 flash 无 bias（暂不写） |
| A 图块数 | ~4 | 对齐 Emap2lig | softmax 版 context 图 |
| 激活检查点 | 开（torch 原生） | PairFormer 相 1 | 关（显存够时） |
| attn kernel | 无 bias→flash / 有 bias→SDPA-eager，备无 flash 兜底 | 自动分流 | 全 eager（调试） |
| couple（Stage3） | int（写回耦合层数） | Stage3Builder | full（每块写回） |
| PP 数目 | 4096 | 显存旋钮 + 正类体素统计（1.7Å 包络 ~3000 正类/配体） | 512 / 8192 |
| precision readout 融合 | 开（PP 冻结、逐 PP 损失已删，§11） | precision 方向 | 关（材化逐点 probe，需大显存） |
| 逐 PP "属于" 辅助损失 | 关（删，PP 全程冻结，§12） | — | 开（须 PP 可更新 / 不融合 readout） |
| select_top_k_points 采样 | Emap2lig 默认（体素中心、1Å、top-k） | 始终保留可用 | 亚体素峰值插值 / 比 1Å 更密（未来钩子） |

**钩子（非第一版）**：3D RoPE、等变坐标更新 / DiffDock 张量场（排除）；粗分支 Order A 对照；难负身份配额；全图自然假阳 vs context-box 假阳。

> 横向对照（AF3 / PocketXMol / DiffDock / Emap2lig 用同一套算子）见 `参照算法_迭代运算梳理_AF3_PocketXMol.md`。