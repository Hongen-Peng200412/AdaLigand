# AdaLigand Stage1 训练与多阈值推理计划

> **文档角色**：本文是 Stage1 完整图推理、阈值标定、组件森林、CLG、三类居中推理、selector 与结构化选择的科学和运行主规格。它面向没有上下文的实现者，规定“计算什么、结果代表什么、各集合承担什么职责”。
>
> **并列文档**：三类 producer 的 Dataset、模型与训练见 `文档/规划文档/Stage1训练实现计划.md`；盘上字段、dtype、目录和 ragged 关系见 `文档/讨论/BOX-level数据契约.md`；上游整图资产见 `Data_Preprocessing/Ori_Data/README.md`。
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
| `CLG_seed_node` | 一次 CLG 尝试开始时，从工作树扫描顺序选中的唯一 active candidate node |
| `CLG_oldest_node` | CLG 中沿低阈值祖先方向最老、且其组件 mask 覆盖全部 candidate masks 的唯一 candidate node；不是泛指 direct parent 或整树 root |
| antichain / 反链 | 任意两个节点都不存在祖先—子孙关系的候选子集；空集也是反链 |
| `selected_node` | selector 门控和反链解码后选中的原全图 candidate node |
| `refined_blob` | Selected 居中重跑后，在原阈值下重新定形得到的局部组件；它不是新树节点 |
| `output_role` | 可独立原子发布和续跑的一类 Stage1 产物：`probability` 是完整图概率/几何，`components` 是 forest/CLG/overlap，`F1_centered` 与 `CLG_centered` 分别是 F1 节点和 CLG oldest 居中的观察结果，`Selected_Refined_Centered` 是 selector 选中节点的重新定形结果 |

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

该入口复现完整 forward 中最短的 voxel 构造和固定 3 次 recycle，但保持训练 `forward` 原样、不抽共享分支。`unet_c1` 只运行 density→voxel backbone；`Find_0` 直接做 raw49 core hard scatter；`Find_1` 只运行无 Transformer 的 voxel MLP/centroid/residual/soft-splat。两个 Find 都跳过 `[8,4,0]` point blocks、P candidate、point backbone、A/P heads 和 sparse-refine。窗口形状固定 `80×80×80`，stride 固定 40。

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

两个 accumulator 和融合结果均为 float32。不得丢弃窗口边缘 5 voxel；不得在完整图阶段保存 V/P/A 中间特征。融合完成后，在 calibration、组件构造和落盘之前执行 producer-specific 后处理：

$$
p_{Find}=p_{fused}(1-hardmask_{full}),\qquad
p_{unet}=p_{fused}.
$$

`hardmask_full` 只包含完整图 core receptor 原子的唯一 home voxels，不膨胀。相同规则用于两个 Find 的三类 centered 概率；unet_c1 始终不使用 receptor hardmask。

### 2.3 per-PDB 完成语义

完整图输出按 `(stage1_model_name, split, pdb_id)` 独立、幂等地生成。`probability`、`components`、`F1_centered`、`CLG_centered`、`Selected_Refined_Centered` 是五个独立 role；各 role 只有正式 NPZ/JSON 已校验并原子发布后才写自己的 `_COMPLETE`。PDB 级原子目录 `_RUNNING` 只表示某个 worker 正在补齐 role，其他 worker 见到后跳过，并由持有者在正常完成、无需工作、主动 continue 或写出异常终态时立即释放。

在 `t_F1` 上预计算正式 eligibility 后，若 `N_F1_eligible>200`，保留已完成的 `probability`，写互斥终态 `_BLOB_EXCEED`，不生成 forest、CLG、overlap 或任何 centered 产物。普通续跑同时跳过 `_COMPLETE` 所覆盖的 role 与 `_BLOB_EXCEED` PDB；半成品和 `_RUNNING` 本身都不可被下游读取。

---

## 3. calibration 100：阈值与早期结果

### 3.1 职责

每个 producer 的训练 BEST 先由固定 validation 选定。随后各自在相同 calibration 100 上完成全图概率，独立选择 `t_alpha` 并汇报同一 calibration 上的最优阈值结果。calibration 不能反向选择 epoch/checkpoint；这些结果必须标为 calibration fitted result，不是独立测试结果。

严格去冗余测试集是论文最终汇报所需，但不是当前 Stage1 实现和近期实验的优先门槛。

### 3.2 micro-Fα 扫描

每张图的二值语义 GT 是全部 occurrence ligand-area mask 的并集。固定扫描：

$$
t_j=\frac{j}{32768},\qquad j=0,1,\ldots,32768.
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

实现按连续概率一次构造长度 32769 的 int64 正/负直方图，再用反向累积量求全部 `TP/FP/FN`；禁止物化 voxel×threshold 矩阵。每个 alpha 取扫描顺序中第一个 micro-Fα 最大值对应的整数 `j`；`alpha=1` 的结果记为 `t_F1`。`thresholds.json` 保存 `denominator=32768`、七个 `alpha_values`、逐 alpha 的 `alpha_threshold_grid_index`、`t_alpha` 与 `t_F1`。

组件 runtime 层只使用七个实际 `j` 的去重集合，并按 `threshold_grid_index` 从大到小构造；若 `k` 对 alpha 得到重复 `j`，自然只生成 `7-k` 层，不伪造层，也不再维护另一套 R/K 或物理阈值下标映射。forest 与 candidate 字段统一使用 `threshold_grid_index`、`candidate_threshold_grid_index`，并保留 `threshold_value=j/32768` 供冷读。PR-AUC/AP 始终按连续概率报告，不受阈值扫描影响。

第一版只选择这些阈值，不在 calibration 上额外搜索 morphology、`min_voxels`、`max_voxels`、连通性或候选排序参数。

### 3.3 组件体素上下界

`min_voxels=32` 固定。

`max_voxels` 在正式组件生产前通过一次性服务器统计冻结：根据 `Data_Preprocessing/Ori_Data/README.md` 读取 GT occurrence 的 ligand-area 体素数，求 Q95，再乘 1.5 并向上取整。当前全量有效 Stage E 清单覆盖 22,309 个 PDB、673,364 个 occurrence，得到 `Q95=682`，因此正式第一版固定 `max_voxels=ceil(682×1.5)=1023`。格点已经重采样到约 1 Å，不引入实际 voxel volume 换算。该任务只把最终数值交回配置，临时文件不构成永久统计流水线；组件代码不得在该值缺失时猜默认值。

### 3.4 calibration 报告

每个 `stage1_model_name` 都报告：

- ligand-area voxel PR-AUC/AP；
- `t_F1` 下语义 Dice；
- coverage F1，双向 coverage 阈值 0.3/0.5；
- one-to-one F1，双向 coverage 阈值 0.3/0.5；
- top-3/top-4/top-5 success ratio，双向 coverage 阈值 0.3/0.5；
- 每个 alpha 的 `t_alpha` 与 micro-Fα 曲线。

对预测组件 `P` 与 occurrence GT `G`，先定义：

$$
c_{pred}(P,G)=\frac{|P\cap G|}{|P|},\qquad
c_{GT}(P,G)=\frac{|P\cap G|}{|G|},
$$

$$
s(P,G)=\sqrt{c_{pred}(P,G)c_{GT}(P,G)}.
$$

在阈值 `τ∈{0.3,0.5}` 下，pair 只有同时满足 `c_pred≥τ` 与 `c_GT≥τ` 才算命中。coverage precision 独立检查每个预测是否命中任一 GT，coverage recall 独立检查每个 GT 是否被任一预测命中，因此允许多对一。one-to-one 先对每个 PDB 的连续 `s(P,G)` 矩阵做一次 Hungarian 最大权匹配；该匹配对两个 `τ` 固定不变，再分别统计已匹配 pair 中双向 coverage 达标者。不得针对每个 `τ` 在达标边图上重做最大基数匹配。

top-K 不做 Hungarian；对 `n_gt>0` 的 PDB，只要前 K 个候选中任一个与任一 GT 双向达标即成功，无预测记失败。F1 路线按 component 内 `probability_map` 均值降序取 top-K；selector 路线只在结构化选择保留的 nodes 中按 `predicted_max_iou` 降序取 top-K。`selection_logit` 只服务反链能量，不冒充候选质量分。

voxel PR-AUC 使用科研中常见的 average precision：对每个有效 PDB 在完整 `[D,H,W]` 网格上以连续 probability 与 union ligand-area GT 计算 AP，区域包含 hardmask voxel；再对有效 PDB 做 macro 平均并报告有效 PDB 数。这里不把所有 PDB voxel 拼成一个 micro AP，也不因 Find 的推理后处理而从评价区域排除 hardmask。

Find_0 与 Find_1 不通过人工综合分自动决胜。用户根据完整 calibration 指标表选择正式 Find 主路线；`unet_c1` 仍完整保留自己的结果和下游路线。

---

## 4. 组件森林

### 4.1 构造

把去重后的实际 `threshold_grid_index` 按高到低排列。每层用 `t=threshold_grid_index/32768` 对 `probability_map≥t` 执行 26-连通组件划分，不做 opening、closing、dilation、erosion 或填洞。

阈值降低时，前景只扩大；每个高阈值组件因此至多属于一个相邻低阈值组件。按包含关系连接后，每个 `tree_id` 是一棵标准 arborescence：

- 每个 `node_id` 有唯一 direct parent，root 的 parent 为 `-1`；
- direct children 以 `children_offsets + children_node_id` 保存；
- sisters 由共同 parent 的 children 现场派生，不重复存储；
- 节点 mask、bbox、threshold、voxel count 和概率统计属于原始只读森林。

不得用通用图对象配合散落布尔判断来代替这套树结构。

盘上 forest/CLG 使用不含 object array/pickle 的数值 ragged；加载后立即重建 `ComponentForest → ComponentTree → ComponentNode` 对象，node 直接持有 `parent` 与 `children:list[ComponentNode]`。`CLG` 对象直接持有唯一 `seed_node`、唯一 `oldest_node` 与 `candidate_nodes:list[ComponentNode]`。枚举所用 `WorkingTree` 只复制拓扑和 active 状态、回指原只读 node，不复制 voxel payload；ancestors、subtree、sisters、LCA 与 `D(g)` 都经这些对象接口执行。

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

一个成功 CLG 的 candidates 在原树上的最小连接闭包必须连通。`CLG_seed_node` 是本次扫描开始时唯一选中的 `g`；后续事件加入的 sisters 不是额外 seed。`CLG_oldest_node` 是候选中沿低阈值祖先方向最老、且 mask 覆盖全部 candidate masks 的唯一 node；它与任一节点的 direct parent、整树 root 明确区分。

### 5.3 统一删除算子 D(g)

枚举器只使用已经定义的一个删除算子。设本次当前选中的 active seed node 为 `g`，工作副本为 `W`：

$$
D_W(g)=Ancestors_W(g)\cup Subtree_W(g),
$$

其中两部分都包含 `g`。每次 CLG 尝试结束后——无论成功，还是因 `max_nodes_per_CLG` 超限而整体失败——都直接在当前工作副本中求并删除 `D_W(g)`。不得根据 tentative oldest node、导致超限的 merge parent 或其它失败细节另造删除规则。原始森林与已经发布的 CLG 不变。

### 5.4 每个 PDB 的数量保护

令 `N_F1_seed` 为删除发生前，F1 层 eligible seed 数。每个 PDB 最多完成：

$$
N_{CLG,cap}=\min\left(300,\;3\max(2,N_{F1\_seed})\right).
$$

达到上限立即停止后续 seed；F1 路线不受此 cap 限制。至少记录：`n_f1_eligible_seeds`（初始合法 seed 数）、`n_CLG_cap`（上式给出的成功 CLG 上限）、`n_CLG_completed`（实际成功发布数）、`n_CLG_rejected_by_node_cap`（因一次原子扩展会超过当前 depth 节点上限而整次拒绝的尝试数）、`mean_candidates_per_completed_CLG`（成功 CLG 的平均 candidate 数）和 `CLG_cap_reached`。`n_CLG_completed` 等于实际成功 CLG 数；没有成功 CLG 时 mean 固定为 0.0。只有因仍有 active seeds 而被 cap 提前截停，且 `n_CLG_completed=n_CLG_cap` 时，`CLG_cap_reached=true`；自然恰好完成相同数量不算 reached。

---

## 6. 三类居中推理

### 6.1 共同规则

三类居中推理都使用产生来源 `probability_map` 的同一 producer checkpoint，走正常完整 forward，并按来源 voxel centroid 计算请求起点、再调用统一 80³ resolver。

每个完成输出是一份可独立消费的 BOX：包含几何、来源身份、权威 voxel 集合、该 producer 实际产生的 V/P/A 特征与概率。两个 Find 的 centered ligand probability 均在 sigmoid 后乘当前 BOX hardmask 的补集；unet_c1 不乘。模型没有的模态或层不以全零数组伪造。每个 producer/split/PDB 的同类 BOX 用一个 role 级聚合 NPZ 保存，而不是一 BOX 一文件或 `index+parts`。

### 6.2 F1_centered

对 `t_F1` 层每个 eligible `global_component_node` 生成一个 `F1_centered`：

- 权威 voxel 集合仍是原 `global_component_mask`；
- 居中 forward 的局部概率只在这组 voxel 上保存为 `centered_probability[K_v] float32`；
- 局部重跑出现的其它 26-连通组件全部忽略；
- 不创建 CLG、candidate membership、selector 或 selection 身份。

它是 F1 baseline 的直接训练/推理输入，可以与 CLG 路线并行供 Stage2/3 使用。

### 6.3 CLG_centered

每个成功 CLG 只生成一个 `CLG_centered`，以 `CLG_oldest_node` 的 mask 居中：

- 权威 voxel 表是 `CLG_oldest_node` 的原全图 mask；
- 每个 `candidate_node` 通过 offsets+indices 引用该共享 voxel 表；
- Find 保存共享 P 表、共享 A 表，以及每个 candidate 的 A membership；P 属于整个 BOX，不做人为 candidate membership；
- `centered_probability` 只对齐 oldest voxel 表；
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

指回唯一来源。`refine_status uint8` 固定为：`0=success`，表示至少一个局部组件与投影后的 source mask 有正交集并已选出 IoU 最大者；`1=empty`，表示按 `t_source` 二值化后没有局部组件；`2=no_overlap`，表示存在局部组件但它们与 source mask 的交集全为 0；`3=failed`，表示该 source 的 forward、组件构造或必要校验执行失败。后三者只保留来源身份、BOX 几何与状态，形成一对零记录，不伪造权威 voxel 或特征 payload。来源全图 mask 可由 component forest 解析，不在 Selected 输出重复复制。

Selected 聚合文件用 `feature_entry_index[N_feature] int32` 严格列出 `refine_status=success` 的 entry 行；四张固定 V grid 的第一维是 `N_feature`，按该索引与成功 entry 对齐，而不是为失败 entry 保存全零占位。voxel/aux/P/A 的 offsets 仍按全部 `N_entry+1` 切分，失败 entry 对应空段。

Selected 输出的 V/P/A 和 `centered_probability` 必须对齐新的 `refined_blob`，不能继续对齐旧 source mask；Find 的 A 表仍按该 refined blob 的 10 Å包络与当前 BOX 的交集定义。这正是 Selected 重跑区别于 F1/CLG 居中观察的意义。

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

Find 的 centered A 表固定为“来源 blob 的 10 Å包络 ∩ 当前 80³ BOX”中的 receptor atoms；它不是 Dataset 的加载 buffer，也不读取 BOX 外原子。A 表保存 `A_global_index`、坐标、`A_probability` 和两个 Find 都真实具有的学习特征：

- `A_feat_L1`：point-side embed 完成、进入 density/point backbone 前的表示；
- `A_feat_L2`：embed 表示与 point density 表示完成组合后，实际送入 point backbone 的表示；
- `A_feat_L3`：A/P interaction 之前的表示；
- `A_feat_L4`：interaction 之后、A head 输入的表示。

正式消费输入还包含 `A_feat_L0[N_A,49] float32`，它由 `A_global_index` 从每 PDB 唯一的整图 receptor 49D 基础表无损索引得到，不在每个 centered BOX 重复落盘。`A_probability=sigmoid(A_logit)`。

Find 的 P 表保存坐标、`P_probability=sigmoid(P_logit)` 与：

- `P_feat_L2`：pseudo-density feature 经过 density/class/interface normalization 后的表示；
- `P_feat_L3`：A/P interaction 之前的表示；
- `P_feat_L4`：interaction 之后、P head 输入的表示。

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
- `c`：消费模型自己的 `DensityMUNetLite` 读取 `density_input`，现场产生任务专属密度上下文 value。

密度输入固定为：

```text
density_input[B,1,80,80,80] = exp_clipnorm_nopost
density_context_feature = DensityMUNetLite(density_input)
```

它不是新的盘上 density artifact。`DensityMUNetLite` 使用四层 80³→40³→20³→10³、通道 `[32,64,64,128]`，每层一个 residual convolution block；encoder/decoder 不用 Transformer，只在 10³ bottleneck 使用 4-head、1-layer Transformer。decoder 的 full-resolution 32D 特征只在实际 V voxel 坐标 gather，再线性投影 32→48 得到 `c`，不生成或落盘 dense48。selector、Stage2、Stage3 各自拥有随机初始化、端到端训练的独立参数，不依赖 Emap2lig 运行时或 checkpoint。

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

selector run 启动前扫描一次所有已完整发布的 `CLG_centered`，按固定顺序冻结 `input_CLG_list.json`。清单同时保存逐 split 的完整 PDB inventory 与逐 `(split,pdb_id,CLG_id)` 项：一个合法但 `N_CLG=0` 的 PDB 仍保留在 PDB inventory 中，只是不产生 Selector 训练样本。运行中新增样本不进入当前 Dataset；以后另启 run 才可使用更多数据。可选 `input_CLG_list_path` 必须来自同一 `stage1_model_name`；指定后逐 PDB、逐 CLG 要求完整存在，不静默取交集。固定 validation 300 的完整性按 PDB inventory 判断，全部可读前只能试跑，不能产生正式 BEST。一个 `selector_seed` 统一控制初始化、按 PDB 分组的 batch sampler 与 DataLoader worker 随机性；sampler 以确定性顺序打乱 PDB 和 PDB 内 CLG，单个 batch 不跨 PDB，以免反复解压同一 PDB 聚合归档。

一个样本读取：

- CLG 原树身份、候选 node IDs 与 tree relationships；
- oldest voxel 表及 candidate voxel memberships；
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

第一版只实现 Candidate-Conditioned Lineage Network（CCLN）：candidate-conditioned 多源读取 + tree-relative Transformer。Nodewise pooled baseline 与 BOX-wide learned latents 不属于本轮实现或完成标准。

CCLN 是项目内部模块名。模型先对每个实际来源执行 §7.3 adapter，V 再执行 §7.4；缺失模态不进入 adapter。每个 voxel/P/A token 的 value 表示至少包含

$$
probability\_features=
\left[p,\log\frac{clip(p,\epsilon,1-\epsilon)}{1-clip(p,\epsilon,1-\epsilon)}\right].
$$

第 `i` 个 candidate 的属性 `A_i` 固定包含：`threshold_grid_index`/value、`log(1+voxel_count)`、相对 oldest mask 体积、mask 内 full-map probability 的 mean/max/分位数、归一化质心、三个排序后的 mask 坐标协方差特征值，以及到 `CLG_oldest_node` 的树距离。属性由 Dataset worker 从 forest/membership 现场计算，不重复落盘。

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

unet_c1 的式子只有 V。空 P/A 子集在模型内用 learned null token 和 `modality_present` 表示，不落伪 token。不得让 V/P/A 三组原始 tokens 彼此做无条件全量 cross-attention。

candidate–token attention 的位置/概率 bias 对每个模态 `m∈{V,P,A}` 单独实现。设 BOX 各轴物理半边长为 `s`，token 坐标为 `x_j`，BOX 中心为 `c_box`。固定 10D 输入：

$$
r_{ij}^{m}=\left[
\frac{x_j-c_i^m}{s},
\frac{x_j-c_{oldest}^m}{s},
\frac{x_j-c_{box}}{s},
p_j
\right]\in\mathbb R^{10}.
$$

不在该 10D 向量进入 bias MLP 前做 Fourier 展开。每个模态有独立 `MLP_bias^m`，输出各 attention head 的 bias；另广播加入 `b_m p_j`，其中 `b_m` 是该模态跨 head 共享、初始化为 0 的可学习标量。V 的 `p_j=centered_probability`，两个中心分别取 candidate voxel membership 与 oldest voxel 集中心；A 使用 `A_probability` 和 candidate/oldest A-pocket 中心，空 A 走 null token且不伪造中心；P 使用 `P_probability`、读取完整 P 表，几何锚使用 candidate/oldest 的 V 中心，不建立 candidate-P membership。

每个模态另对当前 BOX 的实际 token 做共享 AttentionPool，得到 `g_V/g_P/g_A`；缺失模态省略。把 `Q_i^(0)`、实际存在的 `Z_i^V/Z_i^P/Z_i^A` 与 `g_V/g_P/g_A` 拼接并经内容 MLP，得到 `E_i^content`。立即从内容表示预测候选自身的最大 IoU：

$$
\hat q_i=\sigma(MLP_{blob}(E_i^{content})).
$$

`E_i^content` 随后才进入 tree-relative Transformer，得到 `E_i^tree`。对候选 `i,j`，令 `l=LCA(i,j)`：

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

CCLN 遵守：

1. V/P/A 各自先用 §7.3 的 adapter 融合各层真实来源；V 使用 §7.4。
2. 每个 candidate query 只对自己的 V membership、自己的 A membership 和 BOX 全部 P 做 masked cross-attention。
3. attention 使用相对 BOX 坐标、候选质心相对坐标和距离；不对三种模态做无条件全量互相 cross-attention。
4. 候选读出后才运行 tree-relative Transformer，编码 LCA 上下距离、阈值差、质心相对坐标和 log 体积比。
5. producer embed 前禁止 Transformer 与 selector 内的 tree Transformer 是不同边界；后者被允许。

结构化选择能量只从树表示产生：

$$
z_i=MLP_{select}(E_i^{tree}).
$$

独立 CLG readout 也只读取全部 `E_i^tree`：以共享 BOX 摘要初始化一个 CLG query，让它 cross-attend 最终 candidate representations，再输出：

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
Z_+(G)=\sum_{T\in A_+(G)}\exp(score_\theta(T)),\qquad
p_\theta(S\mid G\ valid)=\frac{\exp(score_\theta(S))}{Z_+(G)}.
$$

`Z_+(G)` 称为 `partition`：它是该 CLG 全部**非空**预测反链能量 `exp(score)` 的和，用于训练期归一化。预测 MAP（Maximum A Posteriori；此处指模型能量最大的候选反链）是门控通过后在同一个 `A_+(G)` 上最大化 `score_theta(S)` 得到的非空反链；门控失败时才返回空集。

`L_CLG,G` 为 `a_G` 对 `y_G` 的 BCE/focal。`L_blob,G` 为 `q_hat_i` 对 `q_i` 的 SmoothL1，对正、负 CLG 的全部 candidates 计算并先在该 CLG 内按 candidate 数平均。正 CLG 的 `L_antichain,G` 为 `S*` 在上述非空条件分布下的 CE/focal；负 CLG 不构造该分布，并在下式中把这一项记为 0。每种总损失最后都对 batch 中 CLG 平均，避免大 CLG 仅因节点多而占更大权重。

默认 `w_CLG=w_blob=w_antichain=1`。`L_blob,G` 始终独立参与训练，不得被 `y_G` 或 `p_G` 关闭；三种条件损失加权方式只改变正 CLG 的反链损失权重。第一梯队必须在相同输入清单、`lambda_count=0.05`、`gamma_focal=0` 下运行：

$$
L_{oracle,G}=w_{CLG}L_{CLG,G}+w_{blob}L_{blob,G}
+\mathbf{1}[y_G=1]w_{antichain}L_{antichain,G},
$$

$$
L_{detached,G}=w_{CLG}L_{CLG,G}+w_{blob}L_{blob,G}
+\mathbf{1}[y_G=1]stopgrad(p_G)w_{antichain}L_{antichain,G},
$$

$$
L_{joint,G}=w_{CLG}L_{CLG,G}+w_{blob}L_{blob,G}
+\mathbf{1}[y_G=1]p_G\,w_{antichain}L_{antichain,G}.
$$

oracle-label 条件损失加权是默认参考；联合预测有效性条件损失加权必须报告通过降低 `p_G` 来减轻条件损失的退化风险；中间一式称为停止梯度的预测有效性条件损失加权。第一梯队胜出后，第二梯队只分别测试 `lambda_count=0.03` 和 `gamma_focal=2`，不做完整笛卡尔积。

每个 selector run 以固定 validation 300 上、与上述条件损失加权公式完全一致的 total loss 最小选择 BEST。BEST 冻结后，令

$$
M_{instance}=\frac14\left(
F^{coverage}_{0.3}+F^{coverage}_{0.5}+
F^{1to1}_{0.3}+F^{1to1}_{0.5}
\right).
$$

在 calibration 100 的实际 `p_G` 上扫描门控阈值，选择使全体 PDB micro/global `M_instance` 最大的 `tau_G`；保存完整曲线和最终值，并同时报告四个组成项。`lambda_count` 必须从该 BEST 所属 selector run 的 `resolved_config.yaml` 读取，校正入口不得另收一个可能漂移的命令行值。逐 PDB macro 只作诊断。PDB 即使没有 CLG，也必须以零预测和其真实 GT 进入 global/macro 统计；若全部 calibration PDB 都没有有限 `p_G`，则明确报告无法冻结 `tau_G`。当前 calibration 结果用于快速判断方案苗头，必须明确不是严格 test。

### 8.5 精确树 DP

祖先冲突沿完整原始 component tree 判断。DP 使用当前 CLG candidates 的最小连接闭包和树专属结构。

- 训练：用 `logsumexp` 半环计算非空反链 partition；
- oracle 与推理：用 `max` 半环求最优反链；
- 状态显式区分空/非空，不能枚举全部反链；
- 推理先以 `p_G≥tau_G` 门控，通过后必须返回非空反链；未通过返回空集。

小树穷举必须逐值验证 partition、MAP、oracle 和梯度。

### 8.6 score、selection 与执行顺序

每个 PDB 的 `scores.npz` 严格按来源 `clg.npz` 的 CLG/candidate 顺序保存：

| 字段 | shape | 语义与使用位置 |
|---|---|---|
| `CLG_id` | `[N_CLG] int32` | 当前 PDB 内来源 CLG 的连续本地 ID；顺序必须与 `clg.npz` 完全一致 |
| `CLG_logit` | `[N_CLG] float32` | 独立 CLG readout 的原始 logit `a_G`，用于 `L_CLG` 与校正 |
| `CLG_valid_probability` | `[N_CLG] float32` | `sigmoid(CLG_logit)=p_G`，只用于门控和 `tau_G` 扫描 |
| `candidate_offsets` | `[N_CLG+1] int64` | 切分 `predicted_max_iou` 与 `selection_logit`；必须逐元素复制来源 CLG candidate offsets |
| `predicted_max_iou` | `[N_candidate] float32` | `qhat_i∈[0,1]`，由 `E_i^content` 预测候选与任一 GT 的最大 IoU；用于 `L_blob`、top-K 与质量报告 |
| `selection_logit` | `[N_candidate] float32` | `z_i`，由 `E_i^tree` 产生，只作为反链能量，不解释为概率或候选质量 |

每个 PDB 的 `selection.npz` 保存冻结门控和精确 DP 的结果：

| 字段 | shape | 语义与恢复关系 |
|---|---|---|
| `CLG_id` | `[N_CLG] int32` | 与同 PDB `scores.npz` 一致 |
| `CLG_gate_pass` | `[N_CLG] bool` | `CLG_valid_probability≥tau_G`；通过时解码非空 MAP，失败时为空选择 |
| `selected_candidate_offsets` | `[N_CLG+1] int64` | 切分 `selected_candidate_index` |
| `selected_candidate_index` | `[N_selected] int16` | 每项是所属 CLG candidate 区间内的局部下标，按来源 candidate 原始顺序保存 |

对 CLG 行 `g` 的局部下标 `k`，绝对 candidate 行为 `candidate_offsets[g]+k`，再从该行 `candidate_node_id` 恢复 forest node；不得把 `k` 直接当 node ID。

同一 `(tree_id,node_id)` 可以合法地出现在多个 CLG，也可能被多个通过门控的 CLG 同时选中。`selection.npz` 保留各 CLG 自己的解码结果；恢复下游 selected nodes 时按 CLG/来源 candidate 顺序做有序并集，同一 forest node 只生产一次 `Selected_Refined_Centered`。校正 `tau_G` 时该 node 也只计一个预测，其有效门控概率取所有选中它的 CLG 的最大 `p_G`；第一次出现的 candidate 行提供来源顺序和 overlap 身份。不得把这种跨 CLG 重复视为坏数据。

PDB inventory 中 `N_CLG=0` 的 PDB 仍发布字段完整、长度为零的 `scores.npz` 和后续空 `selection.npz`，使续跑、完整性检查及校正统计都不会把它静默丢失。

时间顺序固定为：先以固定 validation 的 selector total loss 最小选择 BEST；再用该 BEST 对 calibration 清单生成 scores 并冻结 `tau_G`；随后在冻结阈值下为所需 split 生成 selection；只有最终人工选定的 selector 方案继续生产 `Selected_Refined_Centered`。calibration 不反选 epoch、checkpoint 或 selector 方案。

---

## 9. 两阶段生产、部分可用与资源变化

### 9.1 阶段一：calibration first

对三个 producer 分别先完成 calibration 100 的 `probability_map`，冻结各自 `t_alpha`。这是其它 split 开始 F1/CLG 构造的前置条件。这一阶段只做完整图 probability、阈值冻结和 calibration-fitted 指标汇报，不把第一次扫描顺手扩展为组件/centered 生产；阈值冻结后，calibration 的 F1/CLG 由阶段二普通入口回填。

### 9.2 阶段二：validation + calibration + train

阈值冻结后，提供 `cal-produce-F1-CLG`、`val-produce-Prob-F1-CLG` 与 `train-produce-Prob-F1-CLG` 三个明确入口，它们共用同一底层 runner。每个 worker 获得一部分尚缺 role 的 validation 与 calibration 份额，再获得一部分 train；先消费自己的 validation、calibration 份额，再持续处理 train。第一次 calibration 已有 probability，因此 cal 入口从 components 开始；val/train 入口从 probability 开始。对一张 PDB，按缺失情况连续完成并分别发布：

```text
probability_map
  → component forest / CLG
  → F1_centered
  → CLG_centered
```

component forest/CLG 可读后，`F1_centered` 与 `CLG_centered` 是彼此独立的 role tasks；二者都不等待 selector。PDB 级 `_RUNNING` 使同一时刻只有一个 worker 修改该 PDB，但 worker 可按请求只补一个 role。因此 F1 下游和 selector 都不必等待全量 train 推理完成。

文档不冻结卡数、worker ID 或永久分片。任务单元由

```text
(stage1_model_name, split, pdb_id, output_role)
```

唯一确定，必须可重入、幂等。卡数增加、缩减或中断时，重新扫描各 role `_COMPLETE`、PDB `_BLOB_EXCEED` 与当前 `_RUNNING`，重分未完成单元并重提即可；已完成输出不被破坏。不要求第一版建设动态共享队列、永久锁服务或数据库。

同一 selector 梯队的方案应在大体相同时间扫描输入并启动，以控制可用 train 集差异；训练开始后不动态增长 Dataset。

---

## 10. 验收与报告

### 10.1 必须通过的不变量测试

1. 三个 producer 的 voxel-only 与完整 forward ligand logits 在 eval/3 recycle 下逐元素一致。
2. 滑窗覆盖完整网格，`weight_sum>0`，融合全程 float32 且无边缘丢弃；融合后两个 Find 正确应用 hardmask，unet_c1 不应用。
3. 阈值降低时 component mask 单调扩大；每个非 root node 唯一 parent；parent/children 双向一致。
4. candidate bbox 可完整放入 resolved 80³；触碰 BOX/全图边界不被误删。
5. 原始 forest 在 CLG 枚举前后逐元素不变；工作副本的 active/removed 与树操作一致。
6. split/merge 事件原子；depth1 cap=32、depth2 cap=64；超过 cap 整个 CLG 不落盘。
7. 成功和 cap-rejected 尝试都只对当前 seed 在工作副本求 `D(g)`，无 oldest/merge-parent 特例。
8. 每个成功 CLG 恰有一个 `CLG_seed_node` 和一个 `CLG_oldest_node`，oldest mask 覆盖全部 candidate masks。
9. F1/CLG 居中额外组件不产生 candidate；`centered_probability` 与权威 voxel 集逐项对齐。
10. Selected 使用 source 原阈值，max-IoU 匹配 source mask，并保持 source tree/node 一对一或一对零关系。
11. 两个 Find 保存真实 V/P/A 与 A_feat_L1–L4，并可由 A_global_index 恢复 A_feat_L0；unet 只保存真实 V。
12. residual_swiglu 缺失来源不补零；V5+D 关闭额外分支后严格等于 V48。
13. selector 的 logsumexp/max DP 与小树穷举逐值一致；oracle 不落盘。
14. 只有完整、原子发布并带 role `_COMPLETE` 的 PDB/role 被下游扫描；`_RUNNING` 不可读，`_BLOB_EXCEED` 不被普通重跑或下游消费。

### 10.2 必须报告的运行统计

- 每个 producer 的 calibration 阈值、PR-AUC、Dice、coverage/one-to-one F1、top-3/4/5；
- 每层 component 数、eligible/invalid 原因、F1 component 数；
- 每 PDB CLG 数、candidate 数、cap reached、`n_CLG_rejected_by_node_cap`；
- F1/CLG centered 完成数、失败数、吞吐和磁盘占用；
- selector 的 `q` 回归、CLG PR-AUC/F1、反链指标、门控通过率与三种条件损失加权方式的 calibration-fitted 实例结果；
- `Selected_Refined_Centered` 的 success/empty/no-overlap/failed 计数及精修前后指标；
- Dataset wait、GPU utilization、完整图与居中推理吞吐。

### 10.3 当前完成标准

Stage1 可以交给下游的最低条件是：三个 producer 具备通过 smoke 的训练配置与 calibration full-map 链；F1 路线可独立生成并读取；component forest/CLG/D(g) 通过树语义测试；CLG centered 可被 selector 冷读；CCLN、三种条件损失加权方式与精确 DP 可训练/解码；Selected 路线保持可选且不阻塞 F1/CLG 主线。本轮不以正式训练或正式全量生产作为完成门槛，提交时机由用户另行授权。

held-out strict test、最终论文数字和 Stage2/3 正式全量训练不属于本轮 Stage1 文档收口的完成门槛。
