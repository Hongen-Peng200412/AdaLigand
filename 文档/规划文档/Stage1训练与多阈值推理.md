# AdaLigand Stage1 训练与多阈值推理计划

> **文档角色**：本文是 Stage1 完整图推理、阈值标定、组件森林、CLG、三类居中推理、selector 与结构化选择的科学和运行主规格。它面向没有上下文的实现者，规定“计算什么、结果代表什么、各集合承担什么职责”。
>
> **并列文档**：三类 producer 的 Dataset、模型与训练见 `文档/规划文档/Stage1训练实现计划.md`；盘上字段、dtype、目录和 ragged 关系见 `文档/讨论/BOX-level数据契约.md`；上游整图资产见 `Data_Preprocessing/Ori_Data/code/readme.md`。
>
> **低权重附录**：`文档/规划文档/Stage1实现细节手册.md` 只补充代码落点、伪代码、测试和续跑示例，不改变本文。
>
> **范围**：本文覆盖 `Find_0`、`Find_1`、`unet_c1` 三个 producer。F1 路线和 CLG 路线都对三者运行；不同 producer 不联合输入、联合训练或共享下游密度分支。

---

## 1. 目标、术语与不变量

### 1.1 总流程

```text
冻结 Stage1 BEST
  → calibration 100 完整图 probability_map
  → 每个 producer 冻结 t_alpha
  → 26-连通组件森林
  → F1 单阈值组件 ─────────────→ F1_centered
  → 多阈值工作树枚举 CLG ─────→ CLG_centered
                                   → selector
                                   → selected_node
                                   → Selected_Refined_Centered
```

三个正式模型名固定为：

```text
stage1_model_name ∈ {Find_0, Find_1, unet_c1}
```

三类正式居中输出名固定为：

```text
F1_centered
CLG_centered
Selected_Refined_Centered
```

这些是产物角色名，使用大写开头以区别普通程序变量。

### 1.2 核心术语

| 术语 | 唯一含义 |
|---|---|
| `probability_map` | 第一次完整图滑窗融合得到的 ligand-area 概率 `[D,H,W] float32` |
| `global_component_node` | 某个冻结阈值下、由 `probability_map` 26-连通得到的全图组件节点 |
| `global_component_mask` | 该节点在完整网格上的权威 voxel 集合 |
| component forest | 多阈值组件按包含关系连接成的有根有向森林 |
| `candidate_node` | 合法且进入某个 CLG、可被 selector 选择的组件节点 |
| CLG | Candidate Lineage Group；一组存在谱系竞争关系的 candidate nodes |
| `CLG_cover_node` | 覆盖该 CLG 全部 candidate components 的唯一最低阈值祖先节点；不是泛指 direct parent 或整树 root |
| antichain / 反链 | 任意两个节点都不存在祖先—子孙关系的候选子集；空集也是反链 |
| `selected_node` | selector 门控和反链解码后选中的原全图 candidate node |
| `refined_blob` | Selected 居中重跑后，在原阈值下重新定形得到的局部组件；它不是新树节点 |

字段、代码和文档必须直接使用 component、candidate、selected 或 refined 的实际语义。

### 1.3 全程不变量

1. F1/CLG 的候选身份与 mask 只来自第一次 `probability_map` 的组件森林。
2. F1/CLG 居中重跑只补局部概率与特征；局部额外组件不产生新候选，也不修改原全图 mask。
3. Selected 路线可以在原阈值下生成新的 `refined_blob`，但必须指回唯一来源 `selected_node`，且不得塞回组件树。
4. 组件森林原件只读；CLG 枚举只修改树专属工作副本。
5. 组件/CLG 构造不读取 GT；GT 只用于 calibration 指标、selector 监督和最终评估。
6. 三个 producer 各自使用自己的 checkpoint、`probability_map`、阈值表与下游产物，不共用概率或候选。

---

## 2. 第一次完整图推理

### 2.1 模型入口与窗口

完整图推理加载 `unet_c1` BEST 或相应 Find CPC2 BEST，使用训练计划定义的完整 wrapper loader，并调用：

```text
forward_voxel_probability(batch)
```

该入口与完整 forward 共享 density 构造、Find embed/scatter、voxel input 和固定 3 次 recycle，只跳过不会回写 voxel 分支的 P candidate、point backbone、A/P heads 和 sparse-refine。窗口形状固定 `80×80×80`，stride 固定 40。

对长度 `L≥80` 的任一轴，窗口起点是：

```text
0, 40, 80, ...
```

并强制追加最后起点 `L-80`，随后去重、升序。因此末端一定被真实 80 voxel 窗口覆盖，不做图外 padding。

### 2.2 Gaussian 融合

窗口局部坐标分别线性映射到 `[-1,1]`：

$$
u_a(i)=2\frac{i}{79}-1,
\qquad a\in\{z,y,x\}.
$$

固定权重：

$$
w(z,y,x)=
\exp\left[-\frac{u_z^2+u_y^2+u_x^2}{2\sigma^2}\right],
\qquad \sigma=0.5.
$$

对 sigmoid 后的窗口 ligand probability 累加：

$$
probability\_sum[q]\mathrel{+}=w[q]p[q],
\qquad
weight\_sum[q]\mathrel{+}=w[q],
$$

$$
probability\_map[q]=
\frac{probability\_sum[q]}{weight\_sum[q]}.
$$

两个 accumulator 和最终 `probability_map` 均为 float32。不得丢弃窗口边缘 5 voxel；不得把概率乘以 `1-hardmask`；不得在完整图阶段保存 V/P/A 中间特征。

### 2.3 per-PDB 完成语义

完整图输出按 `(stage1_model_name, split, pdb_id)` 独立、幂等地生成。只有 float32 概率图与必要几何全部原子发布后，才写 `_COMPLETE`。重复执行跳过已完成 PDB；半成品不被下游读取。具体临时目录与重扫方式见细节手册。

---

## 3. calibration 100：阈值与早期结果

### 3.1 职责

每个 producer 的训练 BEST 先由固定 validation 选定。随后各自在相同 calibration 100 上完成全图概率，独立选择 `t_alpha` 并汇报同一 calibration 上的最优阈值结果。calibration 不能反向选择 epoch/checkpoint；这些结果必须标为 calibration fitted result，不是独立测试结果。

严格去冗余测试集是论文最终汇报所需，但不是当前 Stage1 实现和近期实验的优先门槛。

### 3.2 micro-Fα 扫描

每张图的二值语义 GT 是全部 occurrence ligand-area mask 的并集。固定扫描：

$$
t_j=\frac{j}{16384},\qquad j=0,1,\ldots,16384.
$$

对 calibration 全体 PDB 和 voxel 汇总 `TP,FP,FN`：

$$
P_{micro}=\frac{TP}{TP+FP},\qquad
R_{micro}=\frac{TP}{TP+FN},
$$

$$
F_\alpha=
\frac{(1+\alpha^2)P_{micro}R_{micro}}
{\alpha^2P_{micro}+R_{micro}}.
$$

固定：

$$
\alpha\in\left\{
\frac12,\frac23,\frac45,1,\frac54,\frac32,2
\right\}.
$$

每个 alpha 取 micro-Fα 最大值对应阈值；`alpha=1` 的结果记为 `t_F1`。不同 alpha 得到相同阈值时，物理组件层只构造一次，并保存 alpha 到物理阈值下标的映射。PR-AUC/AP 始终按连续概率报告，不受上述阈值扫描影响。

第一版只选择这些阈值，不在 calibration 上额外搜索 morphology、`min_voxels`、`max_voxels`、连通性或候选排序参数。

### 3.3 组件体素上下界

`min_voxels=32` 固定。

`max_voxels` 在正式组件生产前由用户通过一次性服务器统计冻结：根据 `Data_Preprocessing/Ori_Data/code/readme.md` 读取所有 GT occurrence 的 ligand-area 体素数，求 Q95，再乘 1.5 并取整数。该任务只需把最终数值交回配置；允许只落临时文件，不建设永久统计流水线。组件代码不得在该值缺失时猜默认值。

### 3.4 calibration 报告

每个 `stage1_model_name` 都报告：

- ligand-area voxel PR-AUC；
- `t_F1` 下语义 Dice；
- coverage F1，IoU 阈值 0.3/0.5；
- one-to-one F1，IoU 阈值 0.3/0.5；
- top-3/top-4/top-5 success ratio，IoU 阈值 0.3/0.5；
- 每个 alpha 的 `t_alpha` 与 micro-Fα 曲线。

coverage F1 允许多个预测命中同一 GT；one-to-one F1 在 `IoU≥τ` 的 component–GT 二分图上做最大一对一匹配。top-K 对 `n_gt>0` 的 PDB 统计，只要前 K 个候选中任一个与任一 GT 达标即成功；无预测记失败。

F1 路线按 component 内 `probability_map` 均值降序取 top-K；selector 路线只在结构化选择保留的 nodes 中按 `predicted_max_iou` 降序取 top-K。`selection_logit` 只服务反链能量，不冒充候选质量分。

Find_0 与 Find_1 不通过人工综合分自动决胜。用户根据完整 calibration 指标表选择正式 Find 主路线；`unet_c1` 仍完整保留自己的结果和下游路线。

---

## 4. 组件森林

### 4.1 构造

把去重后的物理阈值按高到低排列。每个阈值对 `probability_map≥t` 执行 26-连通组件划分，不做 opening、closing、dilation、erosion 或填洞。

阈值降低时，前景只扩大；每个高阈值组件因此至多属于一个相邻低阈值组件。按包含关系连接后，每个 `tree_id` 是一棵标准 arborescence：

- 每个 `node_id` 有唯一 direct parent，root 的 parent 为 `-1`；
- direct children 以 `children_offsets + children_indices` 保存；
- sisters 由共同 parent 的 children 现场派生，不重复存储；
- 节点 mask、bbox、threshold、voxel count 和概率统计属于原始只读森林。

不得用通用图对象配合散落布尔判断来代替这套树结构。

### 4.2 candidate eligibility

组件 node 只有同时满足以下条件才可成为 `candidate_node`：

1. `32 ≤ voxel_count ≤ max_voxels`；
2. 按该组件 voxel centroid 求理想 80³ 起点，再经训练计划的统一 resolver 向内 clamp；
3. 完整 `global_component_mask` 的 bbox 在解析后的真实 80³ BOX 内：

$$
start_a\le bbox\_min_a\le bbox\_max_a\le start_a+79,
\quad a\in\{z,y,x\}.
$$

等号允许，所以组件可以触碰居中 BOX 面或完整图边界。不存在 `touches_full_grid_boundary` 过滤；只要完整 bbox 能放入解析后的 BOX 就合格。非法 node 可以留在原始森林用于审计，但不能成为候选。

---

## 5. CLG 枚举

### 5.1 工作副本与扫描顺序

原始 component forest 永远只读。对每棵树建立树专属工作副本，至少包含原始 parent/children 拓扑、`active/removed` 状态及枚举所需的 frontier/CLG-membership 状态。种子、扩展和删除全是工作副本上的树操作。

扫描顺序：

1. 先处理 `t_F1` 层所有 active、eligible nodes；
2. 再逐层向更低阈值处理；
3. 每层按组件内 `probability_map` 均值降序；
4. 取当前第一个仍 active 的 node 作为本次 selected seed `g`；
5. 高于 F1 的 node 只通过向高阈值的 split 扩展进入 CLG，不另开种子。

CLG 枚举不读取 GT 或 selector 输出。

### 5.2 split/merge 事件

沿树向高阈值移动是一对多 split；向低阈值移动是多对一 merge。unary continuation 不消耗事件预算。一次多路 split/merge 的所有 direct related nodes 是不可拆分的原子事件：

- split：全部 direct children 一起加入；
- merge：低阈值 parent 与其它 direct sisters 一起加入；新 sisters 各自获得完整向高 split 预算；
- 任一必需 node 不 active 或不 eligible，则拒绝整个事件并终止该方向；
- 预算只在事件实际接受时增加。

正式 depth1：

```yaml
max_split_events: 1
max_merge_events: 1
max_nodes_per_CLG: 32
```

depth2 只作枚举消融：

```yaml
max_split_events: 2
max_merge_events: 2
max_nodes_per_CLG: 64
```

节点数加入后恰好等于上限允许；若一个原子事件会使总数 **超过** 上限，则当前 CLG 尝试整体失败：不保留部分或截断后的 CLG，不分配 `CLG_id`，不写候选表，也不做 `CLG_centered`。每个 PDB 记录 `n_CLG_rejected_by_node_cap`。

一个成功 CLG 的 candidates 在原树上的最小连接闭包必须连通。`CLG_cover_node` 是覆盖全部候选 mask 的唯一最低阈值祖先 candidate；它与任一节点的 direct parent、整树 root 明确区分。

### 5.3 统一删除算子 D(G)

枚举器只使用已经定义的一个删除算子。设本次当前选中的 active seed node 为 `g`，工作副本为 `W`：

$$
D_W(g)=Ancestors_W(g)\cup Subtree_W(g),
$$

其中两部分都包含 `g`。每次 CLG 尝试结束后——无论成功，还是因 `max_nodes_per_CLG` 超限而整体失败——都直接在当前工作副本中求并删除 `D_W(g)`。不得根据 tentative `CLG_cover_node`、导致超限的 merge parent 或其它失败细节另造删除规则。原始森林与已经发布的 CLG 不变。

### 5.4 每个 PDB 的数量保护

令 `N_F1_seed` 为删除发生前，F1 层 eligible seed 数。每个 PDB 最多完成：

$$
N_{CLG,cap}=\min\left(300,\;3\max(2,N_{F1\_seed})\right).
$$

达到上限立即停止后续 seed；F1 路线不受此 cap 限制。至少记录 `n_f1_eligible_seeds`、`n_CLG_cap`、`n_CLG_completed`、`n_CLG_rejected_by_node_cap` 和 `CLG_cap_reached`。

---

## 6. 三类居中推理

### 6.1 共同规则

三类居中推理都使用产生来源 `probability_map` 的同一 producer checkpoint，走正常完整 forward，并按来源 voxel centroid 计算请求起点、再调用统一 80³ resolver。

每个完成输出是一份可独立消费的 BOX：包含几何、来源身份、权威 voxel 集合、该 producer 实际产生的 V/P/A 特征与概率。模型没有的模态或层不以全零数组伪造。

### 6.2 F1_centered

对 `t_F1` 层每个 eligible `global_component_node` 生成一个 `F1_centered`：

- 权威 voxel 集合仍是原 `global_component_mask`；
- 居中 forward 的局部概率只在这组 voxel 上保存为 `centered_probability[K_v] float32`；
- 局部重跑出现的其它 26-连通组件全部忽略；
- 不创建 CLG、candidate membership、selector 或 selection 身份。

它是 F1 baseline 的直接训练/推理输入，可以与 CLG 路线并行供 Stage2/3 使用。

### 6.3 CLG_centered

每个成功 CLG 只生成一个 `CLG_centered`，以 `CLG_cover_node` 的 mask 居中：

- 权威 voxel 表是 `CLG_cover_node` 的原全图 mask；
- 每个 `candidate_node` 通过 offsets+indices 引用该共享 voxel 表；
- Find 保存共享 P 表、共享 A 表，以及每个 candidate 的 A membership；P 属于整个 BOX，不做人为 candidate membership；
- `centered_probability` 只对齐 cover voxel 表；
- 不保存稠密 threshold-rank map 或 auxiliary mask；
- 局部额外组件不产生候选、不修改全图 component mask。

### 6.4 Selected_Refined_Centered

selector 选择的每个 `selected_node` 携带其原全图阈值 `t_source`。Selected 路线：

1. 以 source mask voxel centroid 解析新的 80³ BOX；
2. 用同一 producer 完整 forward 得到局部 probability；
3. 在完整局部概率上按 `probability≥t_source` 二值化；
4. 做 26-连通组件划分；
5. 把 source global mask 投影到当前 BOX；若有多个局部组件，取与该 source mask IoU 最大者；
6. 该组件成为新的 `refined_blob` 和本输出的权威 voxel 集合。

局部其它组件忽略。`refined_blob` 不产生新 `tree_id/node_id`，而以

```text
stage1_model_name / split / pdb_id / source_tree_id / source_node_id
```

指回唯一来源。成功时一对一；`empty`、`no_overlap` 或执行失败时保留来源身份与 `refine_status`，形成一对零记录。来源全图 mask 可由 component forest 解析，不在 Selected 输出重复复制。

Selected 输出的 V/P/A 和 `centered_probability` 必须对齐新的 `refined_blob`，不能继续对齐旧 source mask。这正是 Selected 重跑区别于 F1/CLG 居中观察的意义。

---

## 7. 居中特征出口与精度

### 7.1 通用精度

- 学习特征落盘 `float16`；
- probability、坐标和几何值落盘 `float32`；
- indices、offsets、bool 使用自然整数/布尔 dtype；
- NumPy 容器使用 `np.savez_compressed`；
- raw density crop 不在每个 BOX 重复保存，由 BOX 几何从整图读取。

目标磁盘预算为 A–G 之外约 25 TB；30–35 TB 或更高可以后续人工接受，但不是第一版默认。完整图只存概率，不存 V。

### 7.2 V、P、A 的真实出口

V 对三个 producer 都存在：

```text
voxel_final[K_v,48]
voxel_ds_2[256,20,20,20]
voxel_ds_3[256,10,10,10]
voxel_ds_4[256,5,5,5]
voxel_c4[256,5,5,5]
```

`voxel_final` 只在权威 voxel 集合上稀疏保存；四张低分辨率原生网格每 BOX 各存一次。不得保存完整 `[48,80,80,80]` final grid，也不得把四张网格预采样并复制成每 voxel 的高维行。低分辨率特征的三线性采样属于消费模型 forward。

Find 的 P 出口保存：P 坐标、P probability、`P_feat_L2`（density）、`P_feat_L3`（interaction 前）和 `P_feat_L4`（interaction 后）。A 出口保存：实际 8 Å model view 的全局原子索引、坐标、A probability，以及 `receptor_feat_L2/L3/L4`。`Find_1` 另保存真实 `receptor_feat_L1`；`Find_0` 没有 L1，不保存全零占位。外侧 8–10 Å 原子可由上游整图 receptor 表和全局索引恢复，但不伪造成模型 A feature。

`unet_c1` 只保存其真实 V 与 voxel probability，不伪造 P/A。

两个 Find 和 unet_c1 都真实启用 voxel auxiliary head。只保存 hardmask 中唯一 receptor home voxels 的：

```text
voxel_aux_index_local_zyx[K_aux,3]
voxel_aux_probability[K_aux] float32
```

该输出当前不被 selector、Stage2 或 Stage3 默认消费；保存它不扩大下游输入契约。

### 7.3 统一 residual_swiglu 输入融合器

所有实际消费 Stage1 多源特征的模型——selector、Stage2、Stage3 及以后的精修模型——都在任何主干、图/树网络或跨实体交互之前先融合实际存在的来源。

对来源 `s`：

$$
e_s=W_sLN(x_s).
$$

按冻结的来源顺序把全部 `e_s` 与基础 meta 拼接为 `h`。统一融合器：

$$
r=W_{skip}h,
\qquad [a,b]=W_{gate}h,
$$

$$
Fuse(h)=LN\left(r+W_{out}[SiLU(a)\odot b]\right).
$$

每个消费模型拥有自己的 adapter 参数。缺失来源直接不进入该 producer 对应的 adapter 配置，不补零；adapter 的有序来源清单属于该消费模型配置。

### 7.4 V5+D

V 分支默认先实现可严格退化的 V5+D：

- `b`：`voxel_final` 经投影形成完整 V48 基线；
- `m`：在模型内部按目标 voxel 中心三线性采样四张低分辨率网格，经 `residual_swiglu` 融合；
- `c`：消费模型自己的小型密度 U-Net 读取 `density_input`，现场产生任务专属密度上下文 value。

密度输入固定为：

```text
density_input[B,1,80,80,80] = exp_clipnorm_nopost
density_context_feature = SmallDensityUNet(density_input)
```

它不是新的盘上 density artifact。selector、Stage2、Stage3 各自拥有独立 SmallDensityUNet 参数并随各自 checkpoint 端到端训练。

由 `[b,m,c,meta]` 产生两个独立逐通道 gate：

$$
g_m=\sigma(MLP_m[b,m,c,meta]),\qquad
g_c=\sigma(MLP_c[b,m,c,meta]),
$$

$$
v_{out}=LN(b+g_m\odot m+g_c\odot c).
$$

关闭 `m` 与 `c` 时必须严格退化为 V48，而不是另一套基线。全量居中特征生产前，允许小规模比较 V48、V5 和 V5+D；实操默认先尝试 V5+D。若以后真实训练速度不可接受，可以人工改试 V48 等 mini 版本；“H100 上约三天”只是一条运行体验参考，不是当前自动回退规则。

---

## 8. Selector Dataset、模型与结构化目标

### 8.1 一个 CLG 是一个样本

selector run 启动前扫描一次所有已完整发布的 `CLG_centered`，冻结本次实际 train PDB/CLG 清单并保存清单与数量。运行中新增样本不进入当前 Dataset；以后另启 run 才可使用更多数据。固定 validation 300 全部可读前只能试跑，不能产生正式 BEST。

一个样本读取：

- CLG 原树身份、候选 node IDs 与 tree relationships；
- cover voxel 表及 candidate voxel memberships；
- Find 的 P/A 表与 candidate A memberships，或 unet 的 V-only 表；
- `probability_map`/`centered_probability`、候选阈值、体积、质心等基础属性；
- candidate–GT occurrence 的基础 overlap；
- raw experimental density，由 BOX 几何现场裁剪并构造 `exp_clipnorm_nopost`。

不同 producer 使用各自可用模态配置；不填假模态。

### 8.2 online oracle

第 `i` 个 candidate 全图 mask 为 `M_i`，同一 PDB 的 GT occurrence masks 为 `G_j`：

$$
q_i=\max_j IoU(M_i,G_j),
$$

无 GT 时定义 `q_i=0`。记 `A(G)` 为包括空集的全部反链，

$$
Q_{GT}(S)=\sum_{i\in S}q_i-\lambda_{count}|S|,
\qquad S\in A(G),
$$

$$
S^*=\arg\max_{S\in A(G)}Q_{GT}(S),
\qquad y_G=\mathbf 1[S^*\ne\varnothing].
$$

Dataset worker 从已保存的基础 overlap 与当前 `lambda_count` 现场计算 `q_i/S^*/y_G`；不得落盘 oracle 标签或 antichain cache，因为改变 lambda 会改变 oracle。

### 8.3 Candidate-Conditioned Lineage Network

模型档位保留：

1. **Nodewise pooled baseline**：对 candidate 自身的 V/P/A 做 mean/max 或 attention pooling，拼接属性后由共享 MLP 输出；用于判断复杂谱系模型是否真的有增益。
2. **主模型 Candidate-Conditioned Lineage Network（CCLN）**：candidate-conditioned 多源读取 + tree-relative Transformer。
3. **CCLN + cover latents**：用 16 或 32 个 learned latents 读取整个 cover BOX 的共享 token，再让 candidate 读取 latents；它只补充 candidate mask 外与姐妹间上下文，不能替代 candidate 自身的 masked 读取。

CCLN 是项目内部模块名。主模型先对每个实际来源执行 §7.3 adapter，V 再执行 §7.4；缺失模态不进入 adapter。每个 voxel/P/A token 的概率输入至少包含

$$
probability\_features=
\left[p,\log\frac{clip(p,\epsilon,1-\epsilon)}{1-clip(p,\epsilon,1-\epsilon)}\right].
$$

坐标使用相对 BOX/候选质心的低频位置编码。第 `i` 个 candidate 的属性 `A_i` 固定包含：threshold index/value、`log(1+voxel_count)`、相对 cover 体积、mask 内 full-map probability 的 mean/max/分位数、归一化质心、三个排序后的 mask 坐标协方差特征值，以及到 `CLG_cover_node` 的树距离。属性由 Dataset worker 从 forest/membership 现场计算，不重复落盘。

候选初始 query：

$$
Q_i^{(0)}=MLP(A_i).
$$

令 `I_i^V/I_i^A` 为 candidate 的 V/A membership。candidate 只读取自己的 V/A 与 BOX 全部 P：

$$
Z_i^V=Attn(Q_i^{(0)},H_V[I_i^V],H_V[I_i^V]),
$$

$$
Z_i^P=Attn(Q_i^{(0)},H_P,H_P),\qquad
Z_i^A=Attn(Q_i^{(0)},H_A[I_i^A],H_A[I_i^A]).
$$

unet_c1 的式子只有 V。空 P/A 子集在模型内用 learned null token 和 `modality_present` 表示，不落伪 token。每个 attention logit 可以加入 candidate–token 相对坐标 bias，以及零初始化、可学习强度的 token probability prior；不得因此让 V/P/A 三组原始 tokens 彼此做无条件全量 cross-attention。

每个模态另对 cover 范围做共享 AttentionPool，得到 `g_V/g_P/g_A`；缺失模态省略。candidate 内容表示由 `Q_i/Z_i^*/g_*` 拼接后经 MLP 得到。随后才运行 tree-relative Transformer。对候选 `i,j`，令 `l=LCA(i,j)`：

$$
u_{ij}=depth(i)-depth(l),\qquad
d_{ij}=depth(j)-depth(l).
$$

相对特征至少包含 `(u_ij,d_ij)`、threshold 差、质心相对坐标/距离和 log 体积比。第 `h` 个 attention head：

$$
A_{ij}^{h}=\frac{(W_Q^hE_i)(W_K^hE_j)^T}{\sqrt{d_h}}
+MLP_{bias}^{h}(r_{ij})+M_{ij}.
$$

`M_ij` 只处理 batch padding；不使用任意 child 顺序。第一版起点为 hidden dim 128、4 heads、2 layers、FFN hidden 256、pre-norm、dropout 0.1；这些进入配置。

主模型遵守：

1. V/P/A 各自先用 §7.3 的 adapter 融合各层真实来源；V 使用 §7.4。
2. 每个 candidate query 只对自己的 V membership、自己的 A membership 和 BOX 全部 P 做 masked cross-attention。
3. attention 使用相对 BOX 坐标、候选质心相对坐标和距离；不对三种模态做无条件全量互相 cross-attention。
4. 候选读出后才运行 tree-relative Transformer，编码 LCA 上下距离、阈值差、质心相对坐标和 log 体积比。
5. producer embed 前禁止 Transformer 与 selector 内的 tree Transformer 是不同边界；后者被允许。

主模型输出：

$$
\hat q_i=\sigma(MLP_q(E_i)),\qquad
z_i=MLP_{select}(E_i),
$$

以及独立 CLG readout。以共享 cover 摘要初始化一个 CLG query，让它 cross-attend 全部最终 candidate representations，再输出：

$$
p_G=\sigma(a_G).
$$

`z_i` 是反链能量，不是独立概率；CLG readout 不读取 oracle、DP 输出或 raw node ID。

### 8.4 条件反链分布

令 `A_+(G)=A(G)\setminus\{\varnothing\}`：

$$
score_\theta(S)=\sum_{i\in S}z_i-\lambda_{count}|S|,
$$

$$
p_\theta(S\mid G\ valid)=
\frac{\exp(score_\theta(S))}
{\sum_{T\in A_+(G)}\exp(score_\theta(T))}.
$$

`L_CLG` 为 `a_G` 对 `y_G` 的 BCE/focal；`L_blob` 为 `q_hat_i` 对 `q_i` 的 SmoothL1；正 CLG 的 `L_antichain` 为 `S*` 在上述非空条件分布下的 CE/focal。定义：

$$
L_{cond}=w_{blob}L_{blob}+w_{antichain}L_{antichain}.
$$

默认 `w_CLG=w_blob=w_antichain=1`。第一梯队必须在相同输入清单、`lambda_count=0.05`、`gamma_focal=0` 下运行三种 gate：

$$
L_{oracle}=w_{CLG}L_{CLG}+\mathbf{1}[y_G=1]L_{cond},
$$

$$
L_{detached}=w_{CLG}L_{CLG}+stopgrad(p_G)L_{cond},
$$

$$
L_{joint}=w_{CLG}L_{CLG}+p_G L_{cond}.
$$

oracle gate 是默认参考；joint gate 必须报告通过降低 `p_G` 来减轻条件损失的退化风险。第一梯队胜出后，第二梯队只分别测试 `lambda_count=0.03` 和 `gamma_focal=2`，不做完整笛卡尔积。

每个 selector run 以固定 validation 300 上、与本 gate 公式完全一致的 total loss 最小选择 BEST。BEST 冻结后，令

$$
M_{instance}=\frac14\left(
F^{coverage}_{0.3}+F^{coverage}_{0.5}+
F^{1to1}_{0.3}+F^{1to1}_{0.5}
\right).
$$

在 calibration 100 的实际 `p_G` 上扫描门控阈值，选择使全体 PDB micro/global `M_instance` 最大的 `tau_G`；保存完整曲线和最终值，并同时报告四个组成项。逐 PDB macro 只作诊断。当前 calibration 结果用于快速判断方案苗头，必须明确不是严格 test。

### 8.5 精确树 DP

祖先冲突沿完整原始 component tree 判断。只在当前 CLG candidates 的最小连接闭包上运行 DP；闭包中的非 candidate nodes 只传递状态，不能被选择。

- 训练：用 `logsumexp` 半环计算非空反链 partition；
- oracle 与推理：用 `max` 半环求最优反链；
- 状态显式区分空/非空，不能枚举全部反链；
- 推理先以 `p_G≥tau_G` 门控，通过后必须返回非空反链；未通过返回空集。

小树穷举必须逐值验证 partition、MAP、oracle 和梯度。

---

## 9. 两阶段生产、部分可用与资源变化

### 9.1 阶段一：calibration first

对三个 producer 分别先完成 calibration 100 的 `probability_map`，冻结各自 `t_alpha`。这是其它 split 开始 F1/CLG 构造的前置条件。阈值冻结后，calibration 的 F1/CLG centered 可以立即回填；它们不阻塞其它卡进入阶段二。

### 9.2 阶段二：validation + train

阈值冻结后，共同处理 validation 和 train。每张可用卡获得一部分尚未完成的 validation 和一部分 train，优先推进自己的 validation 份额，再持续处理 train。对一张 PDB，原则上连续完成并分别发布：

```text
probability_map
  → component forest / CLG
  → F1_centered
  → CLG_centered
```

component forest/CLG 可读后，`F1_centered` 与 `CLG_centered` 是彼此独立的 role tasks，可以在资源允许时并行推进；二者都不等待 selector。因而 F1 下游和 selector 也不必等待全量 train 推理完成。

文档不冻结卡数、worker ID 或永久分片。任务单元由

```text
(stage1_model_name, split, pdb_id, output_role)
```

唯一确定，必须可重入、幂等。卡数增加、缩减或中断时，重新扫描 `_COMPLETE`、重分当前未完成单元并重提即可；已完成输出不被破坏。不要求第一版建设动态共享队列、永久锁服务或数据库。

同一 selector 梯队的方案应在大体相同时间扫描输入并启动，以控制可用 train 集差异；训练开始后不动态增长 Dataset。

---

## 10. 验收与报告

### 10.1 必须通过的不变量测试

1. 三个 producer 的 voxel-only 与完整 forward ligand logits 在 eval/3 recycle 下逐元素一致。
2. 滑窗覆盖完整网格，`weight_sum>0`，融合全程 float32，无边缘丢弃或 hardmask 乘法。
3. 阈值降低时 component mask 单调扩大；每个非 root node 唯一 parent；parent/children 双向一致。
4. candidate bbox 可完整放入 resolved 80³；触碰 BOX/全图边界不被误删。
5. 原始 forest 在 CLG 枚举前后逐元素不变；工作副本的 active/removed 与树操作一致。
6. split/merge 事件原子；depth1 cap=32、depth2 cap=64；超过 cap 整个 CLG 不落盘。
7. 成功和 cap-rejected 尝试都只对当前 seed 在工作副本求 `D(G)`，无 cover/merge-parent 特例。
8. 每个成功 CLG 恰有一个 `CLG_cover_node`，且覆盖全部 candidate masks。
9. F1/CLG 居中额外组件不产生 candidate；`centered_probability` 与权威 voxel 集逐项对齐。
10. Selected 使用 source 原阈值，max-IoU 匹配 source mask，并保持 source tree/node 一对一或一对零关系。
11. Find 保存真实 V/P/A，unet 只保存真实 V；Find_0 不出现 L1 占位。
12. residual_swiglu 缺失来源不补零；V5+D 关闭额外分支后严格等于 V48。
13. selector 的 logsumexp/max DP 与小树穷举逐值一致；oracle 不落盘。
14. 只有完整、原子发布并带 `_COMPLETE` 的 PDB/role 被下游扫描。

### 10.2 必须报告的运行统计

- 每个 producer 的 calibration 阈值、PR-AUC、Dice、coverage/one-to-one F1、top-3/4/5；
- 每层 component 数、eligible/invalid 原因、F1 component 数；
- 每 PDB CLG 数、candidate 数、cap reached、`n_CLG_rejected_by_node_cap`；
- F1/CLG centered 完成数、失败数、吞吐和磁盘占用；
- selector 的 `q` 回归、CLG PR-AUC/F1、反链指标、门控通过率与三类 gate 的 calibration fitted 实例结果；
- `Selected_Refined_Centered` 的 success/empty/no-overlap/failed 计数及精修前后指标；
- Dataset wait、GPU utilization、完整图与居中推理吞吐。

### 10.3 当前完成标准

Stage1 可以交给下游的最低条件是：三个 producer 完成训练与 calibration full-map；F1 路线可独立生成并读取；component forest/CLG/D(G) 通过树语义测试；CLG centered 可被 selector 冷读；selector 的 pooled baseline、CCLN、三种 gate 与精确 DP 可训练/解码；Selected 路线保持可选且不阻塞 F1/CLG 主线。

held-out strict test、最终论文数字和 Stage2/3 正式全量训练不属于本轮 Stage1 文档收口的完成门槛。
