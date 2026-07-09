# 参照算法迭代运算梳理：AF3 / PocketXMol / DiffDock / Emap2lig

> **本文目的**：用**与本项目设计文档完全相同**的算子词典，把几个参照方法"内部怎么一层层迭代、配体与受体如何互相更新"写成同一套语言，便于和 `Stage2_Stage3_迭代运算设计_讨论.md` 横向对照。
> **命名规则**：同配套文档（特征 `snake_case` + 形状；算子 `PascalCase` + 签名/定义/几何/等变）。算子全名定义见配套文档 §2，本文 §0 给一行速查。
> **核对来源**：AF3（AlphaFold3 论文结构）；PocketXMol（其 `models/graph.py::NodeEdgeNet` 源码已读）；DiffDock（论文，e3nn 异构图）；Emap2lig（其 `conditioning.py`/`instance_seg.py`/`pairformer.py` 源码已读）。

---

## §0 算子速查（与配套文档一致）

| 算子 | 一句话定义 | 用几何 | 等变 |
|---|---|---|---|
| `GeometricSelfAttention` | 定位点集内自注意力 + 相对位置偏置（可稀疏边） | 是 | 否 |
| `FeatureSpaceCrossAttention` | 两集合 cross-attention，**纯特征、无坐标** | 否 | — |
| `GeometricCrossAttention` | 两集合 cross-attention + 相对位置偏置（须同帧） | 是 | 否 |
| `PairBiasedSelfAttention` | 节点自注意力，pair 特征作逐对偏置 | 否 | 否 |
| `OuterProductMeanToPair` | 节点外积均值 → 写回 pair | 否 | — |
| `TrianglePairUpdate` | 三角乘法 + 三角注意力更新 pair（O(n³)） | 间接 | 否 |
| `GatedMessagePassing` | 逐边门控消息 + scatter 聚合（无 softmax） | 间接（边含距离） | 否（节点标量） |
| `EdgeUpdateFromNodes` | 由两端节点更新边特征 | 间接 | — |
| `EquivariantCoordinateUpdate` | 边标量权重 × 相对向量求和 → Δ坐标 | 是 | **是** |
| `LearnedQueryReadout` | 可学习 query 池化集合 → 向量/标量 | 否 | — |

> 两大族：**(i) 注意力 + 显式 pair**（AF3、Emap2lig、本项目）；**(ii) 等变 message passing**（PocketXMol、DiffDock）。

---

## §1 AlphaFold3 / Boltz —— 注意力 + 显式 pair（无受体/配体之分，全是 token）

**表示**：`token_features [n_tokens, d_model]`（聚合物按残基、配体按原子）、`pair_features [n_tokens, n_tokens, d_pair]`。**配体原子与受体残基/原子都是同一套 token**，没有单独的受体编码器。

**Trunk 迭代块（Pairformer）**，每块：

```python
# 单轨（token）：用 pair 作偏置更新 token
token_features = PairBiasedSelfAttention(token_features, pair_features)
# 对轨（pair）：三角更新（用第三个 token k 更新对 (i,j)）
pair_features  = TrianglePairUpdate(pair_features)
# （MSA 模块里另有）pair_features += OuterProductMeanToPair(msa_features)
```

**扩散模块**：原子级注意力（AtomAttention 编/解码 + token 级 DiffusionTransformer），以 trunk 的 `token_features`/`pair_features` 为条件，预测去噪坐标。

**配体↔受体如何互相更新**：**全部经由共享的 `pair_features`**——任意两 token（含配体-受体跨对）都有一条 pair 项，被 `TrianglePairUpdate` 反复更新，`PairBiasedSelfAttention` 再把 pair 读回 token。**双向更新 = pair 中介的注意力**，没有显式 message passing。**非等变**（靠数据增强 + 在原始坐标上扩散）。

---

## §2 PocketXMol —— 节点 + 边图 + 等变坐标更新（message passing 族）

**表示**：`node_features [n_atoms, d_model]`（蛋白 + 配体**所有原子**，带 `is_mol` 标志）、`edge_features [n_edges, d_edge]`、`node_coords [n_atoms, 3]`。口袋先被编码成**固定 context**，配体原子被去噪。

**去噪主干 `NodeEdgeNet`**，每块（已读源码 `models/graph.py`）：

```python
# 1) 由当前坐标构造边的距离特征（GaussianSmearing），并入边特征
edge_features = concat(edge_features, GaussianSmearing(pairwise_distance(node_coords, edge_index)))
edge_features = Linear(edge_features)
# 2) 节点更新：门控消息传递（NodeBlock）
node_features = node_features + GatedMessagePassing(node_features, edge_index, edge_features)
# 3) 边更新：由两端节点更新边（EdgeBlock）
edge_features = edge_features + EdgeUpdateFromNodes(edge_features, edge_index, node_features)
# 4) 坐标更新：等变（PosUpdate）—— 每边算标量权重 × 相对向量 求和
node_coords   = node_coords + EquivariantCoordinateUpdate(node_features, edge_features, edge_index,
                                                          relative_vectors, distances)
```

**配体↔受体如何互相更新**：**同一张异构图**，配体原子与蛋白原子在 cutoff 内连边（边特征里 `is_mol` 标志区分来源），消息沿跨边双向流动；口袋节点作固定 context。**双向更新 = 跨边的门控 message passing + 配体坐标的等变更新**。**等变**（坐标沿相对向量更新）。

> 对比 §1：PocketXMol 不维护稠密 pair 张量，而是**稀疏边 + 边特征**，且**直接更新坐标**；AF3 维护稠密 pair、用三角注意力、坐标只在扩散头出。

---

## §3 DiffDock / DiffBindFR —— SE(3) 等变张量场 message passing（message passing 族）

**表示**：蛋白节点（Cα + ESM2 语言模型嵌入）、配体原子节点；**异构图**，边按距离 cutoff（且依赖节点类型与扩散时间）。

**迭代**：用 **e3nn 张量场网络**做 **SE(3)-等变 message passing**——消息是球谐展开的高阶张量（标量 + 向量 + 更高阶 irreps），可写成 `EquivariantCoordinateUpdate` 的高阶推广（`TensorFieldMessagePassing`）。预测在**降维位姿空间**（平移 + 旋转 + 扭转角 + 邻近侧链扭转）的得分，反向扩散更新位姿。

**配体↔受体如何互相更新**：跨边等变消息；**严格 SE(3) 等变**（比 PocketXMol 的 EGNN 式更高阶）。

---

## §4 Emap2lig —— cross-attention（注意力族；本项目 Stage3 的下限）

**表示**：`ligand_atom_features`、`ligand_pair_features`、以及 `select_top_k_points` 选出的**密度点（被动 K/V，从不更新）**。**无受体**。

**条件块（`PointConditioner`）**，每块（已读源码）：

```python
# 配体内部 pair-bias 自注意力
ligand_atom_features = PairBiasedSelfAttention(ligand_atom_features, ligand_pair_features)
# 配体原子 attend 选中密度点（SelectedCrossAttention，对 atom/point 坐标都加位置编码）
ligand_atom_features = GeometricCrossAttention(
        query_features = ligand_atom_features, query_coords = ligand_atom_coords,   # 扩散中的噪声坐标
        keyvalue_features = selected_density_point_features, keyvalue_coords = selected_density_point_coords)
# 末端：原子扩散去噪头
```

**配体↔环境如何互相更新**：**单向**——配体 attend 密度点，密度点不更新（被动）。无受体、无坐标-MP。

> **本项目 Stage3 = Emap2lig + 受体**：在上面块里加入 `use_receptor=True`（密度点与受体合并成 context，配体也 attend 受体），即配套文档 §6；`use_receptor=False` 精确退回这里。

---

## §5 横向对照表

| 方法 | token/node 轨 | pair/edge 轨 | 坐标更新 | 配体↔受体耦合机制 | 几何 | 等变 | 族 |
|---|---|---|---|---|---|---|---|
| **AF3/Boltz** | `PairBiasedSelfAttention` | 稠密 pair，`TrianglePairUpdate` + `OuterProductMeanToPair` | 仅扩散头 | **共享 pair 中介**（统一 token） | 编进 pair | 否 | 注意力+pair |
| **PocketXMol** | `GatedMessagePassing` | 稀疏 `edge_features`，`EdgeUpdateFromNodes` | **每块等变** `EquivariantCoordinateUpdate` | 异构图跨边 MP | 边含距离 | **是** | 等变 MP |
| **DiffDock** | 等变 MP（张量场） | 距离 cutoff 异构边 | 降维位姿（平移/旋转/扭转）等变 | 异构图跨边等变 MP | 张量场 | **是（高阶）** | 等变 MP |
| **Emap2lig** | `PairBiasedSelfAttention`（配体） | `ligand_pair_features` | 仅扩散头 | **单向** 配体→密度点（无受体） | `GeometricCrossAttention` | 否 | 注意力 |
| **本项目 Stage3** | `PairBiasedSelfAttention`（配体） | `ligand_pair_features` | 仅扩散头 | 配体↔(密度∪受体) cross-attn + 同帧 `GeometricSelfAttention` | 几何 cross | 否 | 注意力 |
| **本项目 Stage2** | 同上 | 同上 | 无（配体无坐标） | **特征空间** 配体↔(密度∪受体) | 仅同帧侧用几何 | 否 | 注意力 |

---

## §6 我们的取向与各家的关系

1. **族选择**：我们建在 Emap2lig 上，全程走**注意力 + pair**族（与 AF3 同族），**不引入等变 message passing**（DiffDock/PocketXMol 那族）——为的是最大化复用 Emap2lig 的现成模块、并和 AF3 血统一致。代价：放弃严格 SE(3) 等变，靠"密度/受体同帧 + 相对位置偏置 + 数据增强"。
2. **与 Emap2lig 的关系**：本项目 Stage3 = Emap2lig 的"加受体"超集（`use_receptor` 开关）；Stage2 = 把同一套换成"配体无坐标的特征空间 cross-attn + 覆盖读出"。两者塌缩到 `use_receptor=False` 都退回 Emap2lig。
3. **从 AF3 借**：配体内部 pair 轨（`PairBiasedSelfAttention` + `TrianglePairUpdate`）直接对应 Emap2lig 的 PairFormer，可加深。但**不把受体也塞进稠密 pair**（受体原子多、稠密 pair 爆 O(n²)），受体走**稀疏图 + cross-attn**（取 PocketXMol 的"稀疏边"思想，但用注意力实现而非 MP）。
4. **从 PocketXMol/DiffDock 借**：受体口袋的**点-边稀疏表示**与"配体↔口袋跨边迭代"思想（配套文档 §3 的 `receptor_edge_*` + 步骤 1/3）。差别：它们做几何 MP + 等变坐标更新（Stage3 才有配体坐标，可部分借鉴）；我们 Stage2 配体无坐标，只能特征空间，故这块**主要参照进 Stage3**。

---

## §7 一句话小结

- **AF3**：万物皆 token，配体-受体交互全在稠密 pair 里用三角注意力反复更新。
- **PocketXMol/DiffDock**：稀疏异构图，门控/等变 message passing，**直接更新坐标**（等变族）。
- **Emap2lig**：配体 attend 被动密度点，单向，无受体。
- **本项目**：注意力族；Stage3 = Emap2lig + 受体（几何 cross-attn）；Stage2 = 配体无坐标的特征空间 cross-attn + 双覆盖读出；受体一律"稀疏图 + cross-attn"，`use_receptor` 关即塌缩成 Emap2lig。
