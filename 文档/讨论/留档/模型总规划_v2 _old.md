# AdaLigand 模型总规划 v2 — Stage2(Matcher)详案与共享表示基建

> **定位**：本文承接 `模型总规划.md`（v1，Find / Match / Build / BOX 总览），把 **Stage2（Match）** 的设计从"指派/分类头"一句话细化到可写代码的程度，并固化 Stage2 与 Stage3 **共享的表示基建**（tokenizer、预训练化学 UNet、PP/P 融合、落盘契约）。Find（Stage1）与 Build 扩散内部细节凡未改动的，仍以 v1 与实际代码为准。
> **权威层级**：实际代码 > Hydra 配置 / checkpoint > 真实产物与日志 > 本文。
> **状态**：迭代草案（"未成熟或过时的讨论"），非最终规格；信息密度对齐一轮 grill 收敛，逐条可追。

---

## §0 范围与一句话结论

- **范围**：Stage2 匹配器全链路（输入 → 表示 → 匹配 → 损失 → 解码）；Stage2/Stage3 共享的 blob/CCD tokenizer、预训练化学特征、PP 采样与 P 融合；Stage2 训练数据与成本。
- **不在范围（沿用 v1）**：Find 训练与后处理、Build 扩散内部、BOX 家族切分标准。
- **一句话结论**：Stage2 = 在 Stage1 落盘的 blob 特征包 × 候选 CCD 集合上，**预测两张有向覆盖矩阵 A/B（per-cell sigmoid，非 DETR 匹配损失）**；blob 有位置、CCD 无位置（反作弊核心不对称）；count 走"身份 token + 数量嵌入 + 解码期硬约束"；三阶段训练独立、仅推理串联。

---

## §1 决策记录 v2（grill 收敛，M 前缀）

| ID | 决策 | 依据 / 出处 |
|---|---|---|
| **M1** | Stage2 **不用 DETR/Mask3D 式匹配损失**：训练时 blob↔occurrence 的 GT 对应已知（`gt_candidate_id`），不存在"给匿名预测分派目标"的需求 | §2；Mask3D 匹配前提是匿名可漂移 query |
| **M2** | 匈牙利/OT 仅作为**可选的推理期 count 受限解码器**；与"训练用不用匹配损失"是两个独立问题 | §9 |
| **M3** | 预测中心对象 = **两张有向覆盖矩阵**：`A`=配体被 blob 捕获比例(recall 向)、`B`=blob 被配体解释比例(precision 向)；**不用 IoU**（会抹掉 merge/split 的方向区分） | §6 |
| **M4** | 损失 = **per-cell sigmoid**：A/B 软覆盖回归 + A'/B'（A/B 阈值截断成 0/1）focal/CE 分类；逐 cell 独立 → 训练可任意分块 | §7 |
| **M5** | **blob 有 map 位置（含 blob 间相对几何），CCD 无任何 map 位置（只有内部构象）**；跨 blob↔CCD 注意只在特征空间做，绝不给 CCD 位置（否则泄露 GT） | §6 |
| **M6** | 三阶段**训练独立**：Stage2 只吃 Stage1 落盘产物；Stage3(Build)用 GT 配对独立训练；仅推理串联 | §10、§13 |
| **M7** | 三层注意力：**level-1 簇内** / **level-2 blob↔CCD 匹配** / **level-3 跨 blob 集合**；每个实体(CCD/PP 簇/A 结构)各有 level-1 图 | §4 |
| **M8** | level-1：几何自注意 + **S 源栈 node 特征**；A 额外带**稀疏键+radius 图**（新写、不复用 atom_head）；PP **不带** CryoAtom 式构造边(v1) | §4、§5 |
| **M9** | **特征源做成 S 轴**（AF3-MSA 式约定，但用轻量 fusion、且 tokenizer 内尽早归约 `[S,N,d]→[N,d]`）；`S=1 且关 A` = Emap2lig 式消融 | §5.1 |
| **M10** | PP 特征 = **网格采样基特征(源①，复用 Emap2lig `select_top_k_points`) + P 融合(吸收源④⑤交互特征)**；不融 P = Emap2lig 消融；该融合代码与 Stage3 **逐字共用** | §5.2 |
| **M11** | count：**身份 token + 整数数量 N 的可学习嵌入(轴一-A)**；**不**展开成 slot/不给副本编号 k(ill-posed)；硬 count 在**解码期** top-k 兜 | §8 |
| **M12** | 缝③ target 组装器提供两种 count target 模式：默认 `max-over-occurrence`(必实现)；可选 **身份内匈牙利**(count>1 时给冗余 blob 正确的 0 监督) | §7.3 |
| **M13** | level-3 **集合层进 v1**，但**带开关可关**(关=退回逐对+解码硬约束) | §8 |
| **M14** | 预训练**化学特征 UNet**：独立小网、从头训、**特征落盘**(不现算)；Stage2/3 共用、冻结 | §11 |
| **M15** | **同样本成批(same-sample batching)**：一个 batch 的 blob 与 CCD 同源，贴近推理；跨样本配对是永不出现的假负，排除 | §10 |
| **M16** | FP 来源**可换**：v1 用预切 box(center/bias 正样本、context 假阳)即推即用；全图划窗自然假阳作为后续(与 Stage3 训练并行跑)；落盘 schema **来源无关** | §10 |
| **M17** | 推理期可用 **Build 的 fit/密度相关性反向重排**（EMERALD-ID 式）；**训练不掺**；拒绝"InstanceSeg-as-scorer"(负目标 ill-posed) | §9、§13 |
| **M18** | one-shot 整图前向+回传在 A800/H200 **可行**；**PP 数目是显存旋钮**；A 方向 K/V 按 blob 共享；pair-chunking 是免费兜底 | §12 |

---

## §2 核心范式：为什么 Stage2 不用匹配损失

DETR / Mask3D 的匈牙利匹配，前提是模型吐出 **匿名、可互换、随训练漂移的 query**——匹配的职责是给这些无身份的预测**分派 GT 目标**以便算 loss，且每步重解因为"哪个 query 专精哪个 GT"在变。

Stage2 两边都不匿名：blob 来自 Stage1（给定、有空间身份），CCD 来自候选表（给定的化学身份 + count）。更关键：**训练时 blob↔occurrence 的 GT 对应已知**（落盘 `gt_candidate_id` + per-occurrence GT mask）。既然对应已知，就不需要"先解指派再算 loss"——loss 直接监督在已知对上即可（M1）。

匈牙利保留**唯一一处正当用途**：

1. **推理期解码器**（M2/M9）：给定 count 预算把软矩阵转成离散 `(blob, CCD, prompt)`。
2. **同身份 occurrence 之间**（M12）：同身份的 N 个副本先验不可分，是唯一残留的真匹配模糊，可用一个**身份内**小匈牙利解决 target 分派。

> 文献佐证：cryo-EM 配体识别走的是分类(blob→ligand-group)或 fit 打分(EMERALD-ID)，无人用 DETR 式匿名匹配——侧证"别上匹配损失"。详 §16。

---

## §3 四条缝（模块化 / 可拆卸的支点）

把所有可变选项关进互不相扰的缝里，**matcher 核心永远只见 (两个 token 集, mask) → blob×列 logits，对一切上游选择免疫**。

| 缝 | 职责 | 关进来的可变项 | 不变量 |
|---|---|---|---|
| **① blob 特征包(落盘 schema)** | Stage1 与下游唯一契约 | 假阳来源(center/bias/context/全图)只是 provenance 标签 + 覆盖标注差异 | **来源无关**：四种来源形状字段完全一致 |
| **② tokenizer(blob、CCD 各一)** | 包 → 变长 token 集 + mask | 伪原子加不加/扩不扩/怎么扩、PP↔P 融合开关、S 源选取与归约、A 边开关、pooled vs 原子级、count 表示 | token 是**带 mask 的变长集合** → matcher 对数目不敏感 |
| **③ 覆盖计算 + target 组装** | 几何 → 监督张量 | A/B 阈值、focal 参数、count target 模式(max-over-occ / 身份内匈牙利)、列粒度 | 所有 target 源自**一张缓存的 per-(blob,occurrence) 覆盖张量** |
| **④ 解码器(仅推理)** | 软矩阵 + count → 离散调用 | greedy / 匈牙利 / OT；Build fit 反向重排 | 输入只是分数矩阵 + count |

Stage2 与 Stage3 **共用缝①②**（同一份 blob 包、同一套 tokenizer），这是"预训练特征/ PP 融合代码共用"的落地点（M10/M14）。

---

## §4 三层注意力层级（M7）

```text
样本(整图)
 ├─ 多个 blob：每个 = 单个 PP 簇(密度点) + 其 pocket A(受体原子，按到 blob 的 k-NN/半径截断)
 └─ 候选 CCD 集合：每个身份一个对象(原子图 + 数量 N)

level-1  簇内(各实体内部)：点-边图
   CCD : ConformerEmbedder + PairFormer(化学键)          —— 复用 Emap2lig，已有
   PP  : 几何自注意(相对位置偏置) + S 栈 node 特征；构造边 v1 关
   A   : 稀疏(共价键 ∪ radius 邻接)几何注意 + 边特征      —— 新写小模块
level-2  blob↔CCD 匹配：双向 A/B 特征空间 cross-attn → 双覆盖矩阵
level-3  跨 blob 集合：blob/CCD summary token 自注意(吃 count 嵌入) → explaining-away；带开关
```

判据（决定要不要给某层加显式边）：**边只有在携带 node+相对几何恢复不出、且对"身份判别"(而非 Build 相互作用)有用时才加**。据此 PP 构造边 v1 关；A 受体键因稀疏后成本不再是障碍（§12）、且 PocketXMol 证其对受体建模有用，列为 v1 可带、随手可关的开关（M8）。

---

## §5 表示层

### 5.1 S 轴（特征源）约定（M9）

每个 PP 点 / A 原子的输入是 `[S, d]` 源栈 + source-type 嵌入。S 源（Pocket_Plus Stage1 可拼凑至多 5 套）：

| 源 | 含义 | P 上的情况 |
|---|---|---|
| ① | 初始编码特征 | P 为 0 |
| ② | Stage1 density-box 原始特征（`DensityCubeEncoder` 输出） | 与③几乎相同；与网格 gather 高度重叠 |
| ③ | embed head + density-box 调制特征 | 同上 |
| ④ | 分类头 cross-attn **之前**特征（`*_feat_before_interaction`） | **融合真正载荷** |
| ⑤ | 分类头 cross-attn **之后**特征（`*_feat_after_interaction`） | **融合真正载荷** |

- **轻量 fusion、尽早归约**：对 ~5 个**异构**源，用 gated-sum 或 5-token 小自注意把 `[S,d]→[d]`，**不上真 MSA/triangle**（那是为成百上千条可交换同源序列设计，O(N²·S)，且会抹平 provenance）。归约在 tokenizer 内（缝②），matcher 之后只见单向量 token。
- **消融**：`S=1 且关 A` ≡ Emap2lig 式（M9）。
- 注：现 Emap2lig PairFormer 是**单序列 trunk（S=1）**，OPM 算子虽是 MSA 形状但被喂 `unsqueeze(1)`；真正维持 S 的 MSA 行/列注意它没有。故 S 轴是我们**新建约定**，非照搬。

### 5.2 PP 采样 + P 融合（M10）

```text
1. 采样+取基特征(= Emap2lig select_top_k_points，可逐字复用)：
   voxel 特征网格 = 冻结化学 UNet 特征 ⊕ Stage1 voxel 特征
   按 ligand-area / instance 概率 top-k 采 PP(~4096，可配) → gather 网格特征 = PP 源①基特征
2. PP↔P 融合(同帧 → 几何可用)：
   PP(密,~4096) 与 P(疏,~512–1024) KNN/radius 建图
   PP 当 query 向邻近 P 做 cross-attn / 图消息 → PP 吸收 P 的源④⑤(交互特征)
   * 融合真正载荷 = 源④⑤(网格里没有)；源②③与网格 gather 高度重叠
   * 不做此步 = Emap2lig 式消融
3. 该融合模块与 Stage3 逐字共用(缝②)
```

### 5.3 A（受体 pocket）侧（M8）

- 取 A = 该 blob pocket：按"到 blob 的 k-NN / 半径"从受体原子集合截断（一个 80³ BOX 约 3000 原子必须启发式截断；Stage2/3 用 48³/64³ 更少）。
- level-1：**新写**一个小模块——建稀疏边（共价键 ∪ radius 邻接）+ 一层带边特征的几何注意。逻辑简单，不复用 `atom_head`（避免背上其 real/pseudo 双向、零初始化残差等 Stage1 包袱）；PocketXMol（图式几何网络、非 AF3、开源）仅作思路参照、不当依赖。
- 显存：稀疏键+radius ≈ `N×k×d_edge` ~ 数 MB/簇/层（稠密 pair `N²×d` ~ 134MB/簇/层，出局）。详 §12。

### 5.4 CCD 侧

- ConformerEmbedder + PairFormer（复用 Emap2lig conf 路）→ `ccd_atom_feats [N_ccd, d]`，化学键在 PairFormer 内部消化，输出已含化学环境的**原子节点特征**。
- 无 map 位置（M5），只有内部构象（已进特征）。
- 每身份附一个 object token，挂**数量 N 的可学习嵌入**（M11）。
- 可选：pooled 辅助头（预测 MW / 原子数 / 回转半径），防 pooled 路径特征塌缩。

---

## §6 匹配层：双向 A/B = 双覆盖矩阵（M3/M5）

**几何摆正（反作弊核心）**：blob 点按 blob 质心中心化（平移不变）；CCD 无 map 位置。**跨 blob↔CCD 只做特征空间注意，不加跨帧位置偏置**（既不知 CCD 在 blob 里的朝向，也不准给它位置）。

**两个方向 = 两张矩阵**：

| 方向 | query / K,V | readout | 矩阵 | 语义 |
|---|---|---|---|---|
| A 方向 | CCD 原子 / blob 点 | 池化 query 侧(CCD) | `A_ij` | 配体被 blob 捕获比例（recall）；分母=已知原子数，**强制从化学估"该多大"** |
| B 方向 | blob 点 / CCD 原子 | 池化 query 侧(blob) | `B_ij` | blob 被配体解释比例（precision）；分母=blob 体积 |

- cross-attn 本身**满的、不池化**；池化只在 **readout**（把 query 侧 `[N,d]` 塌成标量；mean 或 learned-query）——即"半侧池化"。
- readout 前的**逐 CCD 原子 / 逐 PP 点信号有意义、可监督**（逐原子"被覆盖没"≈ Emap2lig present mask；逐点"属不属于"），标量 A/B 是其汇总。
- 自然副产物：错配 CCD 原子找不到一致密度 → A 低；blob 余密度无人解释 → B 低；merge（blob 含 ATP+Mg）→ A_ATP 高但 B_ATP<1；split（配体散两 blob）→ A<1 但 B 高。这些**无需额外打标**。
- 跨 blob↔CCD **不加任何几何边**（M5）。

---

## §7 损失（M4）

### 7.1 覆盖计算（缝③，一次性缓存）

```text
对每个 (blob_i, occurrence_o)：
  A_io = |blob_i ∩ mask(o)| / |mask(o)|     # recall 向；mask(o)=该 occurrence 的 GT ligand-area
  B_io = |blob_i ∩ mask(o)| / |blob_i|      # precision 向；blob_i=Stage1 预测 blob mask
缓存为 per-(blob,occurrence) 张量，所有 target 由此派生。
```

### 7.2 损失项（per-cell sigmoid，逐 cell 独立 → 可任意分块）

- `A/B` 软覆盖回归（如 MSE / smooth-L1）。
- `A'/B'` = A/B 按固定阈值截断成 0/1，对原始 logit 施 **focal / CE**（处理 0 占绝大多数的不平衡；阈值附近 cell 标签有噪，focal 缓解）。
- 可选：readout 前的逐原子/逐点辅助监督。

### 7.3 列粒度与 count target（缝③ 可换模式，M12）

列 = **身份**（非 occurrence）。count>1 时把 per-occurrence target 聚合到身份列，两种模式：

- **`max-over-occurrence`（默认，必实现）**：`A_{i,j} = max_{o∈identity j} A_io`。简单；但"占用过的 occurrence 旁冗余 blob"会拿到中等正目标（双计）。
- **身份内匈牙利（可选，count>1）**：以覆盖为 cost，对该身份的 blobs ↔ N_j 个 occurrence 解 `linear_sum_assignment`；未匹配 blob 的 target = 0。计算极小（N_j 多为 1~few，count=1 退化 argmax），有大量参考代码；**只活在缝③**，把 explaining-away 的真值直接喂进去。

---

## §8 count 与集合层（M11/M13）

- **轴一（count 表示）= A**：每身份一个 token + **数量 N 的可学习嵌入**；**不**展开 slot、**不**给副本编号 k（同身份副本先验不可分，k 索引 ill-posed、且复活身份内匹配、在 sigmoid 覆盖下冗余）。硬 count 在解码期 top-k 兜（§9）。
- **轴二（集合层 level-3）= 放，带开关**：blob/CCD summary token 上一层自注意（吃 N 嵌入）→ `A_ij` 从 `f(blob_i,CCD_j)` 变 `f(blob_i,CCD_j | 其它 blob, count)`，做软 explaining-away。**几十 token、便宜**；定位为**校准 refinement 而非命门**（硬 count 已由解码兜），故可消融、可关（关=退回逐对 + 解码硬约束）。

---

## §9 解码器（仅推理，M2/M17）

```text
输入：A/B 分数矩阵 + 每身份 count 预算
步骤：
  1. 由 A/B 合成每 (blob, 身份) 的匹配分（如 A 与 B 的组合 / 学到的小头）
  2. count 受限指派：greedy(软先验) 或 匈牙利/OT(硬容量) → 选出 (blob, 身份) 对
  3. merge 处理：一 blob 命中多身份 → 对该 blob 按不同 CCD 各调一次 Stage3
     split 处理：一身份散多 blob → 解码期先并 blob 再交 Build
  4. 为每对给 prompt 点(blob ligand-area mask 质心) → 交 Stage3
  5. (可选)Build 生成 pose 后用密度相关性 / fit 反向重排 (EMERALD-ID 式)
```

> Stage3 自始至终只收 `(blob, CCD, prompt)`，**不收 merge 标志、不收 Stage2 矩阵**——矩阵只被**解码编排器**消费，Stage3 训练独立性不破（M6）。

---

## §10 训练与数据

- **独立性（M6）**：Stage2 只吃 Stage1 落盘包；Stage3 用 GT 配对独立训练；仅推理串联。Stage1 不接 Stage2/3 的梯度。
- **same-sample 成批（M15）**：一 batch 的 blob 与 CCD 同源。
- **难负身份**：训练时给候选表掺入额外难负身份（尺寸/化学相近、实际不在场）——因推理隐藏 CCD 位置，模型只能靠化学拒绝它们；同结构真实身份太少、太易。
- **FP 来源可换（M16）**：
  - **v1（即推即用，<1d）**：预切 box 跑 Stage1 → center/bias box 给正样本与偏心，context box（受体占比 > 阈值的随机裁剪）给假阳。
  - **后续（更自然假阳，20–30d）**：全图划窗推理，给 merge/split 与"意外位置假阳"；**与 Stage3 训练并行跑**（Stage3 只需正确配对，center/bias 即可即训；Stage2 等全图或先用 context 起步）。
  - 前提：缝① 落盘/读取/BOX 接口足够一般化，两种来源无缝换。
- **调度红利**：三阶段数据需求不对称（Stage3 只要正样本→现训；Stage2 要真实负样本→全图并行），20–30d 全图推理不空转。

---

## §11 预训练化学特征 UNet（M14）

- **独立小网、从头训、特征落盘**（不现算）；Stage2/3 共用、冻结。独立的理由：与昂贵、难重训的 Stage1 解耦（对齐 Emap2lig 独立 backbone）；落盘稳住下游契约。
- **目标**：逐体素元素/部件分割（C/N/O/P/S/Metal/Ring… ≈ Emap2lig 15 通道 augment），从 GT 原子栅格化标签；可加自监督密度去噪利用无标注 map。
- **域对齐**：48³ @1.0Å exp 密度（推理只有 exp）。
- 其特征进 §5.2 的 voxel 网格，被 PP 采样 gather。

---

## §12 成本与显存（M18）

规模事实：一图真实配体 1–25，加 recall-first 假阳/merge/split，blob 几十~上百；CCD 身份几十。matcher 是最便宜的一级（贵的是 Stage1 全图推理与 Build 扩散）。

显存（flash-attn，O(N)；d=256、L=4、bf16；PP=4096）：

| 方向 | 承重项 | 估算 |
|---|---|---|
| A 方向 | K/V **按 blob 共享**(跨 CCD) → `blobs×PP×d` + 逐对小输出 | 几个 GB 封顶 |
| B 方向 | 逐对 blob 侧输出 `pairs×PP×d` | 75blob×25CCD 最坏 ≈ 16GB；几十对时单 GB |

- **结论**：one-shot 整图前向+回传在 A800(80G)/H200(141G) **可行**（最坏几十 GB），前提是 A 方向 K/V 按 blob 共享（自然实现）。
- **PP 数目是显存旋钮**（512↔4096 差 8×）。
- **pair-chunking + 梯度累积是免费兜底**（per-cell sigmoid 逐 cell 独立，切块不改 loss），留给极端样本。

---

## §13 Stage2 ↔ Stage3 共享与 Stage3 独立性

- **共享**：缝①（blob 包）、缝②（tokenizer：S 栈、PP 采样+P 融合、A 图）、冻结化学 UNet 特征。PP/P 融合代码逐字共用（M10）。
- **Stage3 独立**：Build 仿 Emap2lig，用 GT 配对 `(真实 blob 人工 BOX, 其真实 ligand, GT pose)` 训练，假设配对已正确，不依赖 Stage2 输出（v1 沿用，详 v1 §6）。
- **拒绝 InstanceSeg-as-scorer（M17）**：让条件分割模块当判别器，错配 CCD 的目标 mask 只能填"空"——但那块密度真实存在，是**几何上假的 0**，与本职冲突、训练不稳。对比覆盖矩阵的负目标 `A_{i,错}=0` 是**几何真零**，自然。"fit 即分数"的红利改到**推理期**用 Build 反向重排兑现（EMERALD-ID 式），训练不掺。

> Emap2lig 锚点：其 `InstanceSeg` 是**已知配体条件**下的分割+采点（`select_top_k_points`），全程无匹配——即 AdaLigand 的 Stage3；其 `SelectedCrossAttention` 对 atom 坐标加 PE，**Stage2 不可照抄**（CCD 无位置，M5）。

---

## §14 待定旋钮与消融清单

1. **PP 数目**（512↔4096）：显存/质量权衡。
2. **PP↔P 融合**：开/关（关=Emap2lig 式）；消融核心 = 源④⑤交互特征值不值。
3. **A 受体边**：开/关（稀疏键+radius）；第一个该试的 level-1 消融。
4. **count target 模式**：max-over-occurrence（默认）vs 身份内匈牙利（count>1）。
5. **集合层（轴二）**：开/关。
6. **A/B 方向**：共享权重 vs 分开；readout = learned-query vs mean。
7. **CCD pooled 辅助头**（MW/原子数）：开/关。
8. **解码器**：greedy(软先验) vs 匈牙利/OT(硬容量)；Build fit 反向重排开/关。
9. **A'/B' 阈值与 focal 参数**；难负身份配额。
10. **全图自然假阳 vs context-box 假阳 + 难负身份**：够不够，经验定。

---

## §15 与代码的锚点（已核对事实）

- Emap2lig `model/modules/instance_seg.py`：`select_top_k_points` 从 `voxel_projector(cat[backbone64, augment15, instance1])` 按 instance prob 采点 → 即"Find 特征 + 预训练特征"采样。
- Emap2lig `layers/instance.py` / `selected_attention.py`：InstanceSeg cross-attn(密度 query × 配体 atom 上下文)；SelectedCrossAttention 对 atom/point 坐标加 PE。
- Emap2lig `modules/pairformer.py`：单序列 trunk(S=1)，OPM 喂 `unsqueeze(1)`；无 MSA 行/列注意。
- Pocket_Plus `model/sparse_refine/density_cube.py`：`DensityCubeEncoder`(cube_size=11 → 3D conv + GAP)给 P 初始特征(源②)。
- Pocket_Plus `model/stage1_atom_head.py`：radius-graph 几何 cross-attn(零初始化纯残差)→ `*_feat_before/after_interaction`(源④⑤)。
- 数据契约：`数据处理_v2.md` —— LigandObject(`object_key` 去重、`ref_pos`)、per-occurrence GT 坐标/mask、receptor_tokens、ligand_area 质心。

---

## §16 参考

- **范式**：两阶段检测器（RPN→ROI-Align→head）、DETR 式集合匹配（Hungarian / `linear_sum_assignment`，本文论证 Stage2 **不**用其 loss 版）。
- **匹配损失前提**：Mask3D（匿名 query + bipartite matching，arXiv:2210.03105）——前提不成立故不迁移。
- **配体识别对照**：Kihara 组 blob→ligand-group 分类（Bioinformatics 2024）；EMERALD-ID 对接+密度相关性打分（Structure 2025）——均非 DETR 式匹配，侧证 M1。
- **生成式判别先例**：Diffusion Classifier（ICCV 2023，arXiv:2303.16203）——"边扩散边打分"有先例但贵、噪；故 fit 重排放推理期。
- **骨架/表示**：Emap2lig（密度条件化 + InstanceSeg + 原子扩散，Stage3 主干）；PocketXMol（图式几何网络、全原子受体带键、非 AF3、开源 github.com/pengxingang/PocketXMol，受体稀疏图思路参照）；AF3/Boltz（Pairformer + 原子扩散，经 Emap2lig 传递）。

---

## §17 维护

实现后以代码与真实产物为准回填字段与 shape。改动覆盖矩阵定义 / 损失项 / count 模式 / 集合层 / S 源选取 / PP 采样与融合 / A 边 / 解码器 / 预训练 UNet 时，同步更新 §1 决策记录与 §14 消融清单。本文与 `模型总规划.md`(v1) 并存：v1 管 Find/Build/BOX 总览，v2 管 Stage2 详案与共享表示基建。
