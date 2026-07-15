# AdaLigand Stage1 训练与多阈值推理计划

> **文档角色**：本文是 Stage1 训练、整图推理、多阈值候选构造、候选选择网络、反链选择和局部特征物化的当前目标规格。它面向代码实现，不记录方案演变历史。
>
> **上游**：`文档/规划文档/数据处理_v2.md` 产出整图密度、受体、标签与 occurrence 数据；`Data_Preprocessing/Ori_Data/code/readme.md` 说明当前数据产物。
>
> **并列契约**：`文档/讨论/BOX-level数据契约.md` 规定本文产物的盘上字段、逻辑 dtype、ragged 关系和追溯方式。本文规定“怎样产生以及表示什么”，BOX 契约规定“怎样保存”。
>
> **下游**：`文档/讨论/模型总规划_v2.md` 与 `文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md` 消费选中的候选及其共享特征。
>
> **范围**：Pocket_Plus 的 Stage1 分割主干保持既有结构；本文新增或重写数据适配、训练包装、整图概率组装、组件树、候选谱系组、局部物化和候选选择器。取消的是 CPC sparse-refine 第三训练阶段及最终 refine head，不删除 C/P/P 节点或 P/real 交互路径。
>
> **治理**：本文是目标规格。若实现与本文不同，先按 `AGENTS.md` 分类说明良性、中性、恶性和未完成漂移，再由用户决定是否回填；不得用“代码优先”静默改写计划。

---

## §1 目标与不变量

Stage1 的最终职责不是只给出一张二值图，而是形成一条可重复、可标定、可供 Stage2/3 使用的候选生产链：

1. 使用新数据重新训练 Pocket_Plus 的 ligand-area 与 receptor-binding 预测。
2. 用与训练完全相同的数据处理路径进行整图滑窗推理，组装完整概率图。
3. 在多个经过标定的阈值上构造连通组件森林。
4. 从组件森林确定一组互不重叠的**候选谱系组（Candidate Lineage Group, CLG）**。
5. 每个 CLG 只做一次必要的 Group-parent 居中重跑，为整组候选补齐共享的 voxel、P 与 receptor 特征。
6. 小型候选选择网络始终对第一次整图推理产生的 **Global Proposal Mask** 打分。
7. 在每个 CLG 内求一个允许为空的最优反链，得到交给 Stage2/3 的候选 blob。
8. 可选的 selected-final 居中精修只改善最终形状，不参与候选身份建立或选择器标定。

下列不变量贯穿训练与推理：

- blob 身份只来自第一次整图概率图的组件森林；局部重跑不创造或替换候选身份。
- `center`、`bias`、`context` 只说明训练 BOX 原点的来源，不说明样本正负。
- 训练与推理使用同一个 BOX builder、Dataset `__getitem__` 主路径和 collate。
- CLG 枚举在训练、验证和推理中使用同一确定性算法，不读取 GT，也不读取选择网络输出。
- 多阈值选择和 selected-final 精修是两条独立路径；关闭精修后仍能完整运行 Stage2/3。
- Group-parent 局部重跑产生的多阈值形状只作辅助观察；网络的评分对象仍是 Global Proposal Mask。

---

## §2 术语、方向与符号

### 2.1 坐标与维度

| 符号 | 含义 |
|---|---|
| `D,H,W` | 完整概率图的 `Z,Y,X` 三轴长度。完整网格张量形状为 `[D,H,W]`。 |
| `B_z,B_y,B_x` | 局部 BOX 形状，第一版固定为 `80,80,80`。 |
| `T` | 去重后的物理阈值数，必须小于 255。 |
| `N` | 一个 CLG 中可供选择器评分的候选节点数。 |
| `K_v` | Group-parent Mask 中保存 voxel 特征的体素数。 |
| `N_P` | Group-parent 局部重跑保存的 P token 数。 |
| `R` | Group-parent pocket 中保存的受体原子数。 |
| `d` | 选择器的统一隐藏特征维度。 |

网格索引和张量空间轴统一写成 `ZYX`；世界坐标统一写成 `XYZ`，单位为 Å。任何在两者之间的转换都必须显式使用 BOX 原点与 voxel size，不能靠轴序猜测。

### 2.2 核心术语

| 术语 | 严格定义 |
|---|---|
| **全图概率图（Global Probability Map）** | Stage1 对完整密度图滑窗推理并融合后得到的 ligand-area 概率张量 `P_global[D,H,W]`。 |
| **阈值层（Threshold Level）** | 给定阈值 `t_r` 后的上水平集 `F_r={x | P_global(x) >= t_r}`。物理阈值按从高到低排列。 |
| **组件节点（Component Node）** | 某个阈值层中，按 26-连通得到的一个连通组件。一个节点对应一个确定的全图体素 mask。 |
| **组件森林（Component Forest）** | 相邻阈值层的组件按包含关系连边。边从低阈值组件指向高阈值组件；因此每个非根节点只有一个入边，每棵树是一棵向外分枝树。它是离散阈值上的 max-tree。 |
| **F1 种子（F1 Seed）** | 位于 micro-F1 最优阈值 `t_F1` 所在层、满足节点可选择条件且尚未退休的组件节点。 |
| **类种子姐妹（Seed-like Sister）** | 向低阈值扩展发生合并时，被同一合并父节点直接合并进来的其它姐妹节点。它们与原种子一样获得向高阈值分裂的预算。 |
| **候选谱系组（Candidate Lineage Group, CLG）** | 由种子、允许深度内的可选择祖先/子孙及合并姐妹组成的候选集合；这些候选在完整组件树上的最小连接闭包是一棵有根子树。一个 CLG 是选择器 Dataset 的一个样本。 |
| **组父节点（Group-parent Node）** | 一个 CLG 中阈值最低、因而 mask 最大的唯一节点。它是该 CLG 的根。 |
| **全图候选（Global Proposal Candidate）** | CLG 中一个可选择组件节点；其 **Global Proposal Mask** 是第一次整图组件森林中的原始 mask。 |
| **可行反链（Feasible Antichain）** | CLG 的候选子集 `S`，其中任意两个节点都不存在祖先—子孙关系。空集也是可行反链。 |
| **Group-parent BOX** | 以 Group-parent Mask 居中裁出的 80³ BOX；每个 CLG 只产生一个，负责整组共享特征物化。 |
| **局部阈值位次图（Threshold Rank Map）** | Group-parent 局部重跑后得到的 `uint8[80,80,80]`。它编码每个体素首次进入前景的阈值位次，255 表示在所有阈值下均为背景。 |
| **已选候选（Selected Proposal）** | 选择器打分并经反链优化后进入 `S` 的 Global Proposal Candidate。 |
| **Selected-final BOX** | 可选的最终居中精修 BOX；它保留原 Global Proposal Mask，并可额外产生 Refined Mask。 |

### 2.3 阈值方向与树关系

物理阈值满足：

$$
t_0 > t_1 > \cdots > t_{T-1}.
$$

阈值降低时，前景只会扩大，组件可能相互合并；阈值升高时，前景只会缩小，组件可能分裂。因此：

- 沿树边方向，也就是从低阈值到高阈值，是“向高阈值、向子孙”移动。
- 逆树边方向，是“向低阈值、向祖先”移动。
- 低阈值的合并组件是父节点；高阈值的分支组件是子节点。

文中“父/子、祖先/子孙”只表示这套组件树关系，不表示神经网络层次或文件目录。

### 2.4 工程术语

| 术语 | 本文中的含义 |
|---|---|
| **occurrence** | 一张图中的一个真实配体实例，有独立 GT 原子坐标和 GT ligand-area mask。 |
| **P token** | Pocket_Plus 在 BOX 内产生的虚拟节点；它不是体素，也不是受体原子，必须保存自己的坐标、概率与特征来源。 |
| **materialization / 物化** | 把一次局部 forward 的必要结果写成可独立读取的 BOX 产物。 |
| **ragged / 变长表** | 不同候选拥有不同数量的 voxel/P/receptor 行；用 `offset + row index` 表示，不补成固定长度落盘。 |
| **manifest / 运行清单** | 记录 checkpoint、配置、阈值、特征出口、坐标帧和哈希的只读元数据，用来准确复现实验。 |
| **calibration / 标定** | 在独立校验集上选择阈值或少量推理参数，不更新神经网络权重。 |
| **selector / 候选选择器** | 对 CLG 中每个 Global Proposal 预测质量分数的小网络。 |
| **cross-attention / 交叉注意力** | 一组 query 从另一组 token 读取加权信息；本文中候选 query 只读取其 membership 指定的共享 token。 |
| **membership / 归属索引** | 某个候选在 Group-parent 共享 voxel、P 或 receptor 表中可以读取哪些行；它是行号集合，不是另存一份特征。 |
| **LCA / 最近公共祖先** | 组件树上同时是两个节点祖先、且离二者最近的节点；用于表示两个候选的谱系关系。 |
| **frontier / 待扩展端点** | CLG 枚举过程中尚待继续向高阈值方向搜索的分支端点及其已用预算。 |
| **accumulator / 概率累加器** | 一张完整图的 `probability_sum` 与 `weight_sum`；所有滑窗结果在这里按坐标累加。 |
| **latent token / 隐变量 token** | 少量可学习的共享摘要向量，用于压缩 Group-parent 的整体环境；只属于进阶模型。 |
| **padding mask / 补齐掩码** | batch 中区分真实 token 与补齐位置的布尔量，不表示空间 mask。 |
| **tie-break / 同分裁决** | 多个结果主分数完全相同时采用的固定次级排序规则，用于保证确定性。 |
| **profiling / 性能剖析** | 测量各阶段实际耗时、显存、CPU 等待和 IO，而不是凭感觉判断瓶颈。 |

---

## §3 Stage1 基础训练

### 3.1 训练输入与 BOX 来源

Stage1 训练读取 `文档/规划文档/数据处理_v2.md` 定义的整图产物：exp/sim 密度、现场构造的辅助密度通道、49 维受体特征、ligand-area mask、receptor-binding 标签及 instance 标签。

`box_index` 中每一行是一条独立训练样本身份。即使两行的空间位置重合，也不按 BOX 原点或体素内容去重。三类来源独立配置采样比例：

```yaml
stage1_train:
  box_source_weight:
    center: 1.0
    bias: 1.0
    context: 1.0
```

权重为 0 表示关闭该来源。`box_type` 不进入 loss；监督始终从该次实际裁剪到的 ligand-area 与 receptor 标签现场获得。

### 3.2 Dataset 与 DataLoader 共用路径

训练和整图推理共用以下纯处理链：

```text
整图资产引用
  → 根据 origin/shape 裁剪密度
  → density_channel_builder 构造辅助通道
  → box_geometry 选择 box+buffer 内受体并转换坐标
  → 组装 Stage1 输入
  → collate 成批
```

训练和推理只允许在“BOX 原点怎样产生”和 sampler 上不同：

- 训练从 `box_index` 读取 `center/bias/context`。
- 整图推理由 map shape、window shape、stride 和样本编号确定窗口。

固定 80³ BOX 不增加 `voxel_valid_mask`。`pin_memory` 默认关闭，它不是 CPU/GPU 并行成立的条件。少量 voxel size 非严格等方的 BOX 不因旋转增强而抛异常；若某种轴交换在数值上不精确，保留现有宽容行为并记录诊断计数。

### 3.3 GT atom envelope 的 CPU 成本

Stage2/3 无预测 blob 的试水训练使用 GT ligand atom envelope 定义口袋，不保留中心球备选。实现方式是每个 worker 为当前 PDB 缓存一棵 receptor `cKDTree`，对 ligand present atoms 批量做半径查询并合并索引。

该操作的复杂度近似为一次建树 `O(N_R log N_R)` 加少量局部查询；建树在同一 PDB 内复用。第一版现场计算，不预先物化。如果基准显示它占 Dataset 实际耗时的比例超过配置上限，再把结果提升为可选缓存，而不是改变口袋定义。

### 3.4 模型与训练头

Pocket_Plus 分割主干、candidate C、P anchor、density cube、typed P、P head 与 real/P cross-attention 保留。取消：

- sparse-refine 的第三训练阶段；
- 最终 refine head 及其 loss；
- Stage2/3 不需要的推理多分类输出。

保留的主监督至少包括：

- 体素级 ligand-area 预测；
- 受体原子级 binding 预测。

旧数据上的 ligand-area F1 约 0.55、binding F1 约 0.65，均来自无 CPC refine 的设置，只作为重训参照，不当作新数据上的硬验收阈值。

### 3.5 训练输出与检查

每次训练至少记录：

- 数据 split、数据 schema/version 和配置哈希；
- 三类 BOX 实际采样数；
- ligand-area 与 binding 的 loss、precision、recall、F1；
- 每秒 BOX 数、DataLoader 等待时间和 GPU 利用率；
- 非严格等方样本与旋转诊断计数；
- checkpoint 哈希。

---

## §4 第一次整图推理：只组装概率

### 4.1 推理流水线

第一次整图推理的唯一必需产物是 `P_global[D,H,W]`。此时不知道最终 CLG 和候选，因此不保存完整 Stage1 中间特征。

流水线划分为三个可重叠阶段：

1. DataLoader worker 读取整图资产、裁剪滑窗、构造辅助密度通道和受体输入。
2. GPU 批量执行 Stage1 forward，输出窗口概率。
3. 独立的 CPU 组装器把窗口概率写入该 PDB 的概率累加器，并在完整概率图完成后执行阈值与组件树处理。

多个进程不能无协调地写同一个概率累加器。推荐每张图只有一个逻辑写者，GPU 结果通过有界队列送给它；组装器可以与下一批 GPU forward 或下一张图的预处理重叠。

### 4.2 滑窗融合

对每个完整图至少维护：

```text
probability_sum[D,H,W]
weight_sum[D,H,W]
```

每个窗口把 `window_probability * window_weight` 累加到前者，把 `window_weight` 累加到后者：

$$
P_{global}(x)=
\frac{\operatorname{probability\_sum}(x)}
{\max(\operatorname{weight\_sum}(x),\epsilon)}.
$$

`window_weight` 可以是常数 1 或固定的中心加权窗，但必须写入推理 manifest。不得沿用“窗口边角 5 voxel 直接丢弃”的规则。

### 4.3 blob 的唯一来源

所有正式候选都来自完整 `P_global`。`center/bias/context` 不运行逐 BOX Stage1 推理，也不拥有 blob、coverage 或 Stage1 feature addon。整图推理产生的 BOX 类型统一为 `infered_box`，不兼容其它拼写。

---

## §5 多阈值标定

### 5.1 calibration set

阈值、CLG 数量上限、候选选择参数和可选精修比较都在独立 calibration set 上完成。该集合不得参与 Stage1 或候选选择器参数训练，也不得用测试集调参。

### 5.2 micro-$F_\alpha$ 与 macro-$F_\alpha$

每张图的二值 GT 是该图全部 occurrence ligand-area mask 的并集。对 calibration set 的所有 PDB 和所有体素先累计 `TP,FP,FN`：

$$
P_{micro}=\frac{\sum TP}{\sum TP+\sum FP},\qquad
R_{micro}=\frac{\sum TP}{\sum TP+\sum FN},
$$

$$
F_{\alpha,micro}=
\frac{(1+\alpha^2)P_{micro}R_{micro}}
{\alpha^2P_{micro}+R_{micro}}.
$$

**micro-$F_\alpha$** 用于选择阈值。**macro-$F_\alpha$** 是先对每个 PDB 单独计算 $F_\alpha$，再对 PDB 取平均，只作为样本间稳定性诊断并在论文中报告。

这里是使用有监督 calibration set 选择多组阈值，不是 Li、Otsu 等单张图自动阈值算法。正式推理对所有 PDB 使用 calibration 后冻结的同一组阈值。

### 5.3 第一版 alpha 集合

第一版使用互为倒数的偏好对，并包含标准 F1：

$$
\alpha\in
\left\{0.4,0.5,\frac{2}{3},1,1.5,2,2.5\right\}.
$$

对每个 $\alpha$ 独立搜索使 micro-$F_\alpha$ 最大的概率阈值。若多个阈值同分，采用固定 tie-break，并记录完整扫描曲线。推荐 tie-break 选择更接近 0.5 的阈值；若仍相同，选择较高阈值，避免无意增加候选数量。

不同 alpha 可能得到相同数值阈值。相同阈值只构造一个物理 Threshold Level，但 `alpha_to_threshold_rank` 保留所有语义映射。独立最优阈值通常随 alpha 近似单调；第一版不做事后强制排序修正。若发生明显反序，应先报告 calibration 不稳定性，再决定是否扩大 calibration set。

F1 阈值既是旧单阈值基线，也是 CLG 枚举的初始种子层。

---

## §6 组件森林与节点可选择性

### 6.1 组件森林构造

对每个物理阈值 `t_r`：

1. 计算 `F_r = P_global >= t_r`。
2. 使用固定 26-连通提取连通组件。
3. 不执行腐蚀、膨胀、闭运算或边角裁切。
4. 在相邻阈值层间按体素包含关系连边。

一个高阈值组件只能属于一个低阈值组件，因此得到森林；一个低阈值组件可以有两个或更多高阈值子节点，算法不得假设二叉树。

每个原始组件节点至少记录：

```text
tree_id: int32
node_id: int32
tree_parent_node_id: int32 | -1
threshold_rank: uint8
voxel_count: int32
bbox_min_zyx: int32[3]
bbox_max_zyx: int32[3]   # 闭区间
touches_full_grid_boundary: bool
probability_mean: float32
probability_max: float32
```

### 6.2 节点级合法性与方向剪枝

节点是否可以成为 Global Proposal Candidate，与能否继续向某方向搜索分开判断。

| 条件 | 当前节点可选择 | 向高阈值/子孙继续 | 向低阈值/祖先继续 |
|---|---:|---:|---:|
| `voxel_count < min_voxels` | 否 | 否 | 是 |
| `voxel_count > max_voxels` | 否 | 是 | 否 |
| 触碰完整图最外层 voxel | 否 | 是 | 否 |
| 居中后 bbox 任一轴装不进 80³ | 否 | 是 | 否 |
| 按质心计算的 80³ BOX 越出完整网格 | 否 | 是 | 否 |
| 其它正常节点 | 是 | 是 | 是 |

第一版 `min_voxels` 的推荐起点为 32，参考 Emap2lig；最终值由 calibration 统计确定。`max_voxels` 由真实 ligand-area 体积分布和候选数量曲线确定。

空间 fit 直接由 `box_shape_zyx=(80,80,80)`、节点 bbox、体素质心和完整网格形状推导，不增加 `max_bbox_extent_zyx`。不为 mask 预留额外 margin。

对轴 $a\in\{z,y,x\}$，设 mask 体素索引均值为 $c_a$，BOX 长度为 $B_a=80$。整数起点使用固定的 half-up 舍入：

$$
s_a=\left\lfloor c_a-\frac{B_a-1}{2}+\frac{1}{2}\right\rfloor.
$$

只有同时满足下式才可物化：

$$
0\le s_a,\qquad s_a+B_a\le L_a,
$$

其中 $L_a$ 是完整网格该轴长度。失败时不 clamp、不 padding。触碰完整图边界、bbox 装不进 80³ 或居中 crop 越界，都属于“当前节点不可选且禁止继续向低阈值扩大”的空间非法条件。

只有“当前节点可选择”的节点才进入 CLG 候选集合。遇到不可选择节点时，该节点本身不加入 `G`；算法只按上表允许的方向把它当作结构桥继续搜索，或在被禁止的方向停止。因此每个完成 CLG 的 Group-parent 必须可选择且可物化，并且能在候选表中找到 `group_parent_candidate_row`。

第一版不计算或保存 receptor clash、碎片密度等化学启发式过滤量。

---

## §7 候选谱系组枚举

### 7.1 事件预算

从一个种子沿组件树扩展时：

- 经过只有一个继续分支的链条不消耗事件预算。
- 向高阈值经过一次一对多分裂，消耗一次 `split_event`。
- 向低阈值经过一次多对一合并，消耗一次 `merge_event`。
- 一次三路或更多路合并仍算一个 merge event。
- 合并父节点进入 CLG 时，所有直接姐妹同时进入，并成为类种子姐妹；每个姐妹获得与原种子相同的向高阈值 split 预算。

第一版默认：

```yaml
clg:
  max_split_events: 1
  max_merge_events: 1
  max_candidates_per_clg: 20
```

事件深度 2 只用于树枚举消融，并用 GT 标签计算可达到的理论上限；其初始 `max_candidates_per_clg=40`。若 calibration 上事件被候选上限原子拒绝的比例过高，可分别升至 32/64。

为保证 depth=2 也只有一种实现，扩展状态固定为：

```text
CLG 共享状态:
  merge_used                 # 从当前种子层向低阈值走过的合并事件数

每条向高阈值分支的 frontier:
  node_id
  lineage_seed_id            # 原始种子或某个类种子姐妹的身份
  split_used                 # 该谱系分支已走过的分裂事件数
```

状态转移：

1. 原始种子初始化 `merge_used=0, split_used=0`。
2. 向高阈值经过 unary continuation：`split_used` 不变。
3. 向高阈值经过多路 split：只有 `split_used < max_split_events` 才能接受；全部直接子分支原子加入，并把各自 `split_used` 设为旧值加 1。
4. 向低阈值经过 unary continuation：`merge_used` 不变，并更新当前最低阈值节点。
5. 向低阈值经过多路 merge：只有共享的 `merge_used < max_merge_events` 才能接受；合并父节点与全部直接姐妹原子加入，随后 `merge_used += 1`。
6. 每个新姐妹获得新的 `lineage_seed_id`，其向高阈值 `split_used=0`，因此拥有与原始种子相同的完整 split 预算；所有分支共享已经消耗的 `merge_used`，不能通过加入姐妹重置向低阈值预算。
7. 任一原子事件触发候选数上限时，整个事件不进入状态队列。

不可选择结构节点不加入候选集合；若 §6.2 允许穿过该方向，则 frontier 只穿过它寻找下一个合法节点，预算只在真正的 split/merge 事件处变化。

### 7.2 同层同时处理

不得按 Python `for` 循环顺序贪心构组。同一阈值层的全部未退休种子按以下流程同时处理：

1. 为每个种子独立计算在 split/merge 预算和方向剪枝下的可达边界。
2. 找出共享同一个首次合并事件的种子。
3. 将这些种子、合并父节点和全部直接姐妹统一闭包成一个组。
4. 对新加入的类种子姐妹按相同 split 预算向高阈值展开。
5. 所有组形成后，再统一标记节点归属和退休状态。

相同输入、配置和 threshold manifest 必须产生相同 CLG，不受 worker 数、哈希表顺序或节点遍历顺序影响。tie-break 统一使用 `(threshold_rank, tree_id, node_id)`。

### 7.3 层次扫描顺序

1. 首轮处理 F1 阈值层的全部有效种子。
2. 随后依次向更低阈值层扫描尚未退休、可选择的节点。
3. 不从高于 F1 的层单独开启新组；高阈值节点通过种子或类种子的向上分裂扩展进入 CLG。

每个完成的 CLG 在候选诱导关系下必须是一棵连通有根树，并且只有一个 Group-parent Node；完整原始树路径允许包含仅用于连接的不可选择结构节点。

### 7.4 整组退休

CLG `G` 形成后，训练和推理都按整个 `G` 退休可比较谱系：

$$
D(G)=G\cup Ancestors(G)\cup Descendants(G).
$$

这里 `Ancestors(G)` 与 `Descendants(G)` 是原始组件森林中与 `G` 任一节点存在祖先—子孙关系的节点。退休只影响后续 CLG 枚举；不会从原始树缓存或已落盘 CLG 中删除数据。

退休集合依赖 `G`，不依赖网络最后选出的反链 `S`。因此训练样本构造和推理进程完全一致，且 `S=∅` 时仍会正常结束该谱系。

### 7.5 事件原子性与候选数上限

一次 split 或 merge 事件涉及的全部直接姐妹是一个原子单元。如果加入整个事件会使候选数超过 `max_candidates_per_clg`，拒绝整次事件；不得只保留分数最高的前 K 个姐妹。

### 7.6 每个 PDB 的 CLG 数量保护

设 `N_F1_valid` 为该 PDB 在 F1 层的有效种子数：

$$
N_{cap}=\min\left(
N_{abs},
\max\left(N_{floor},\lceil5N_{F1\_valid}\rceil\right)
\right).
$$

`N_abs` 与 `N_floor` 根据 calibration set 的 CLG 数量分布确定。触发上限时按以下顺序保留：

1. F1 种子产生的 CLG；
2. 种子阈值离 F1 更近的 CLG；
3. 组内 Global Proposal probability 的最大值、均值；
4. 固定的 `tree_id,node_id` tie-break。

每个 PDB 必须记录 `n_clg_before_cap`、`n_clg_after_cap` 和 `clg_truncated`。

---

## §8 局部重跑与特征物化

### 8.1 三种物化角色

| 角色 | 是否必需 | 一次对应什么 | 用途 |
|---|---|---|---|
| **F1 baseline materialization** | 基线实验必需 | 一个有效 F1 节点 | 复现单阈值候选输入，直接训练/运行 Stage2/3 基线。 |
| **CLG Group-parent materialization** | 多阈值路线必需 | 一个 CLG，只运行一次 | 为整组 Global Proposal 候选保存共享 voxel/P/receptor 特征与局部多阈值形状。 |
| **Selected-final materialization** | 可选 | 一个已选 Global Proposal | 用原阈值做最终居中形状精修并生成独立完整 BOX。 |

三种角色都使用 `box_type=infered_box`，通过 `materialization_role` 区分，不新增 box_type。

### 8.2 Group-parent 居中重跑

对一个 CLG：

1. 按 §6.2 的统一公式从 Group-parent Mask 体素质心确定 `box_start_zyx`；该 BOX 已通过完整网格范围检查。
2. 在该 BOX 上运行一次 Stage1。
3. 只为原始 Group-parent Global Proposal Mask 覆盖的 voxel 保存 Stage1 多尺度特征。
4. 保存该次局部 forward 的 P token、多尺度 P 特征、Group-parent pocket 的受体概率和多尺度受体特征。
5. 对每个 Global Proposal Candidate 保存它在父 voxel、P 和 receptor 共享表中的行索引。
6. 从局部 ligand-area 概率生成 threshold rank map。

Group-parent Mask 包含 CLG 内所有候选 mask，因此不另造 `union_pred_mask`。同一份 parent voxel 表和 parent pocket 只存一次。

### 8.3 threshold rank map

设 `threshold_value[0]` 为最高阈值。对局部概率 `P_local[z,y,x]`：

$$
rank(z,y,x)=
\min\{r\mid P_{local}(z,y,x)\ge t_r\},
$$

若不存在这样的 `r`，存 255。第 `r` 个阈值的完整局部前景可由：

$$
M^{local}_r = [rank\le r]
$$

精确重建。该表达允许某层前景为空或包含多个互不连通组件。第一版 selector 不给完整 80³ rank map 增加 dense 3D CNN，而是：

- 在 parent voxel 坐标处查询 rank embedding；
- 为每个 Global Proposal 派生 rank histogram 与局部体积变化曲线；
- 保留完整 rank map 供 Stage3 和后续消融使用。

### 8.4 Global Proposal 与局部观察的边界

`candidate_voxel_row` 描述 Global Proposal Mask；`threshold_rank_map` 描述 Group-parent 居中重跑。两者可以不完全重合。局部位次图不再运行连通组件匹配，不产生新的候选身份，也不改变 `tree_id/node_id`。

### 8.5 共享 pocket

Group-parent pocket 由 Group-parent Mask 的体素包络和统一半径确定。保存：

- 一份 parent pocket 受体原子全局索引及其局部重跑特征；
- 每个候选自己的 pocket 原子在 parent pocket 表中的行索引。

同一半径定义下，候选 mask 是 Group-parent Mask 的子集，所以候选 pocket 应是 parent pocket 的子集。实现必须检查这一不变量。

---

## §9 候选选择器 Dataset 与监督

### 9.1 一个 CLG 是一个样本

选择器 Dataset 的最小样本单位是一个 CLG。单样本逻辑输入：

```text
parent_voxel_features:       [K_v, C_v]
parent_voxel_coords:         [K_v, 3]
parent_voxel_probability:    [K_v]
rank_at_parent_voxel:        [K_v]

P_features:                  [N_P, C_P]
P_coords:                    [N_P, 3]
P_probability:               [N_P]

receptor_features:           [R, C_R]
receptor_coords:             [R, 3]
receptor_binding_probability:[R]

candidate_voxel_membership:  N 个 ragged row-index 集合
candidate_P_membership:      N 个 ragged row-index 集合
candidate_receptor_membership:N 个 ragged row-index 集合
candidate_attributes:        [N, C_s]
lca_up_distance:             [N, N]
lca_down_distance:           [N, N]
```

batch 后使用 padding：

```text
candidate_padding_mask:      [B, N_max] bool
voxel_token_padding_mask:    [B, K_v_max] bool
P_token_padding_mask:        [B, N_P_max] bool
receptor_token_padding_mask: [B, R_max] bool
```

这些字段只区分真实 token 与 batch padding，不表示空间有效区域，也不进入 BOX 盘上契约。Stage1 固定 80³ 训练仍不使用 `voxel_valid_mask`。

只有可供选择的 Global Proposal Nodes 进入 `N`。不可选择的边界节点保留在组件树审计表中；LCA 距离沿完整原始树计算，即使路径经过未物化节点也要计数。

### 9.2 监督标签

设第 `i` 个 Global Proposal Mask 为 `M_i^{global}`，GT occurrence mask 为 `G_j`：

$$
q_i=\max_j IoU(M_i^{global},G_j).
$$

这是主连续标签，表示候选与任一真实 occurrence 的最佳 IoU。辅助二分类标签为：

$$
y_i=\mathbf 1[q_i\ge\theta_{valid}].
$$

`theta_valid` 是训练配置，不固化到基础数据契约。任何接触但低 IoU 的候选可作为诊断，不作为第一版主硬标签。

网络输出：

```text
predicted_max_iou: [B,N_max] float in [0,1]
valid_logit:       [B,N_max] float
```

第一版损失推荐：

$$
L_q=\operatorname{SmoothL1}(\hat q_i,q_i),\qquad
L_y=\operatorname{BCEWithLogits}(\hat y_i,y_i),
$$

$$
L=\operatorname{mean}_{CLG}
\left[
\operatorname{mean}_{i\in CLG}(L_q+\gamma L_y)
\right].
$$

先在每个 CLG 内取均值，再在 batch 内取均值，避免候选多的 CLG 自动获得更大权重。反链选择只使用 `predicted_max_iou`；`valid_logit` 不相乘、不硬门控。

训练不使用 Hungarian matching、可微反链 loss 或强化学习。候选集合和树关系均由确定性 CLG 枚举给出。

---

## §10 候选选择器模型

### 10.1 第一版需要实现的三档

| 档位 | 内容 | 目的 |
|---|---|---|
| **Nodewise pooled baseline** | 候选内部 mean/max 或可学习加权池化，拼接候选属性后用共享 MLP 独立打分。 | 验证复杂模型是否真正必要。 |
| **主模型：Proposal-Conditioned Lineage Network, PCLN** | Global Proposal mask-conditioned 多源 cross-attention，加 Tree-Relative Transformer。 | 同时读取候选内容、parent 上下文和谱系关系。 |
| **进阶模型：PCLN + parent latent** | 主模型外加 16 或 32 个共享 parent latent token。 | 补充候选 mask 外、姐妹分支之间和连接区的全局环境。 |

“动态感知”仅表示注意力权重随候选内容、parent 环境和姐妹谱系改变；它不表示网络动态修改组件树或候选 mask。

PCLN 是本文为代码模块使用的内部名称，不声称它是已有论文中的模型名称；其组成算子与文献关系在 §16 分别说明。

### 10.2 多源共享 token 编码

三个实体分别投影到 `d` 维：

$$
H_v=E_v(X_v)\in\mathbb R^{K_v\times d},\quad
H_P=E_P(X_P)\in\mathbb R^{N_P\times d},\quad
H_R=E_R(X_R)\in\mathbb R^{R\times d}.
$$

`X_v` 至少包含：

- 已命名的 Stage1 voxel/UNet 多尺度特征；
- 归一化 BOX 坐标；
- 第一次全图概率；
- 局部 `rank_at_parent_voxel` embedding。

`X_P` 与 `X_R` 分别包含已命名多尺度特征、坐标、P probability 或 receptor-binding probability。特征来源必须在 BOX manifest 中写出生产模块、checkpoint、通道数和坐标帧，不能只叫 `L1/L2/L3`。

每个候选的初始 query：

$$
Q_i^{(0)}=\operatorname{MLP}(A_i)\in\mathbb R^d.
$$

候选属性 `A_i` 推荐包含：threshold rank/value、`log(1+voxel_count)`、相对 Group-parent 体积、全图概率的均值/最大值/分位数、归一化质心、三个排序后的 mask 坐标协方差特征值、到 Group-parent 的树距离、rank histogram 与局部体积曲线。协方差特征值用于描述形状尺度，不依赖坐标轴顺序。

### 10.3 Global Proposal mask-conditioned 读取

对模态 `m∈{v,P,R}`，候选 `i` 只从自己的 membership 行读取 token：

$$
Z_i^m=\operatorname{MultiHeadAttention}
(Q_i^{(0)},H_m[I_i^m],H_m[I_i^m]).
$$

等价的 padded 实现是在 attention logit 上加 mask：属于候选的 token 加 0，其余加负无穷。parent token 只编码一次，候选之间共享，不复制特征表。

P token 与候选的 membership 由固定空间规则产生并随产物保存；消费方不得自行猜测。空 P 或空 receptor 子集在模型内使用一个可学习 null token，并提供 `modality_present` 标志；伪 token 不写入磁盘。

### 10.4 Group-parent 共享摘要

只看候选内部可能忽略姐妹分支和连接区。每个模态额外生成一个 parent 摘要：

$$
g_m=\operatorname{AttentionPool}(H_m)\in\mathbb R^d.
$$

候选初始表示为：

$$
E_i^{(0)}=\operatorname{MLP}
[Q_i^{(0)}\Vert Z_i^v\Vert Z_i^P\Vert Z_i^R
\Vert g_v\Vert g_P\Vert g_R].
$$

进阶 parent-latent 版本把全部 parent token 交给 16/32 个 learned latent 做一次 cross-attention 和少量 latent self-attention；候选再读取这些 latent。该路径只补充共享上下文，不能替代候选自己的 masked 读取。

### 10.5 Tree-Relative Transformer

对候选 `i,j`，令 `l=LCA(i,j)`，并令 $r_i,r_j$ 为两者的阈值位次：

$$
u_{ij}=depth(i)-depth(l),\qquad
d_{ij}=depth(j)-depth(l),\qquad
\Delta r_{ij}=r_j-r_i.
$$

有序对 `(u_ij,d_ij)` 可区分 self、祖先、子孙、姐妹及其它分支。第 `h` 个注意力头使用：

$$
A_{ij}^{h}=
\frac{(W_Q^hE_i)(W_K^hE_j)^\top}{\sqrt{d_h}}
+B_h[u_{ij},d_{ij}]
+C_h[\Delta r_{ij}]
+M_{ij}.
$$

`M_ij` 是 batch padding mask。该编码不使用任意 child index，因此姐妹顺序变化时输出只做相同排列，保持集合顺序无关。

第一版推荐起点：`d=128`、4 个注意力头、2 层、前馈子层隐藏维度 256、每个子层计算前执行 LayerNorm、dropout 0.1。它们是可配置起点，不是科学常数。

输出头：

$$
\hat q_i=\sigma(MLP_q(E_i)),\qquad
\hat y_i=MLP_{valid}(E_i).
$$

### 10.6 计算复杂度

令 `K=K_v+N_P+R`。padded masked attention 的主要复杂度为：

$$
O(NKd)+O(N^2d).
$$

当 `N≤20` 或 `N≤40` 时，树内 `N²` 项很小。若性能剖析发现 `N*K` 的补齐浪费显著，再按变长行索引执行不补齐注意力；第一版不为此增加自定义底层算子。

### 10.7 可选公共轻量密度 U-Net 调制器

Stage1 候选选择器、Stage2 和 Stage3 可以共享一个可关闭的 **密度上下文调制器（Density Context Modulator）**。它是进阶附加模块，不参与 Global Proposal 身份、CLG 枚举、标签或反链约束。

输入是从第 1 层裁出的原始 exp 密度：

```text
raw_density: [B,1,Z,Y,X]
```

轻量 U-Net 输出多尺度特征：

```text
density_context_l: [B,C_l,Z_l,Y_l,X_l]
```

消费方式：

- voxel 对象按自身网格位置 gather 对应尺度特征；
- P、receptor atom 或其它点对象按 BOX 内连续坐标做三线性插值；
- 不更新对象坐标。

对对象表示 `h[n,d]` 与采样上下文 `c[n,C]`，第一版推荐门控残差调制：

$$
g=\sigma(W_gc),\qquad
h'=LayerNorm(h+g\odot W_cc).
$$

这比直接拼接更容易保持关闭模块时的主干行为。三阶段共享相同输入归一化、特征出口命名和 checkpoint。默认使用独立预训练、冻结的 checkpoint；若某阶段单独微调，必须产生新的 checkpoint 身份，不能再声称三阶段共享同一组权重。

现有“预训练化学特征 U-Net”可作为该接口的一种生产者，不强制再造第二个 dense backbone。若另训更轻版本，两者通过不同 feature-source manifest 区分。第一版主模型必须在该模块关闭时完整可运行。

---

## §11 CLG 内反链选择与参数标定

### 11.1 可行解与目标函数

对一个 CLG `G`，可行解 `S⊆G` 满足任意两个节点不可比较。允许：

$$
S=\varnothing,\qquad J(\varnothing)=0.
$$

第一版目标：

$$
J(S)=
a\sum_{i\in S}\hat q_i
+b\operatorname{mean}_{i\in S}(\hat q_i)
-\lambda|S|.
$$

整体正比例不改变最优解，因此固定 `a=1`，只标定 `b/a` 与 `lambda/a`。`valid_logit` 不进入该目标。

### 11.2 精确求解

由于均值项取决于 `|S|`，先对每个候选数量 `k` 求满足反链约束的最大分数和：

$$
Q_k=\max_{S:|S|=k,\ S\text{ is an antichain}}
\sum_{i\in S}\hat q_i.
$$

网络节点表只包含可选择候选，因此原始组件树路径可能经过没有进入网络的结构节点。求解前先构造**候选诱导树（Candidate-induced Tree）**：Group-parent 是根；其它候选连接到其原始树路径上最近的候选祖先。祖先冲突仍按完整原始树判断。由于一个 CLG 只有一个 Group-parent，该诱导结构仍是一棵树。

候选诱导树上的 `Q_k` 可用树形动态规划精确求得：

- 选择当前节点：只能得到 `k=1`，并排除其全部候选子孙。
- 不选择当前节点：按候选数量合并各子树的 `Q_k`；这是一个小规模背包式动态规划。

然后计算：

$$
J_k=Q_k+b\frac{Q_k}{k}-\lambda k,\quad k>0,
$$

并与 `J_0=0` 比较。选择最大者；完全同分时依次偏好更小 `k`、更高 `Q_k`、按 `node_id` 字典序更小的反链，保证确定性。

### 11.3 标定缓存与实例指标

选择器对所有候选的 `predicted_max_iou` 与 `valid_logit` 独立落盘；选择结果按 `selection_run_id` 另存。改变 `b,lambda` 不需要重跑网络。

在 calibration set 上优化 `b,lambda`，目标为：

$$
M_{instance}=\frac{1}{4}(
F^{coverage}_{0.3}+F^{coverage}_{0.6}
+F^{1to1}_{0.3}+F^{1to1}_{0.6}).
$$

对 IoU 阈值 `tau`：

- **coverage F1**：候选只要与任一 GT 的 IoU 不低于 `tau` 就计作命中候选；GT 只要被任一候选命中就计作已覆盖。由命中候选比例与已覆盖 GT 比例计算 F1，允许多个候选覆盖同一 GT。
- **one-to-one F1**：在 `IoU>=tau` 的候选—GT 二分图上做最大一对一匹配。匹配数 `m` 给出 `precision=m/n_pred`、`recall=m/n_gt`，再计算 F1。

四项等权平均用于调参，四个分量必须分别报告。选择器训练和 `b,lambda` 标定都只使用 Global Proposal Mask，不使用 Refined Mask。

### 11.4 计算预算

反链动态规划和二维 `b,lambda` 网格搜索只处理缓存的标量分数与小树，远低于 Stage1 forward 成本。16 核 CPU 在两天预算内不是风险项；第一版可以直接搜索两个参数。若以后增加第三个有效自由度，仍先复用同一缓存评估。

---

## §12 可选 Selected-final 精修

### 12.1 独立性

多阈值候选选择在 Group-parent materialization 后已经完整结束。Stage2/3 的默认输入是：

```text
已选 Global Proposal Mask
+ Group-parent 共享 voxel/P/receptor 特征
+ 候选自己的共享表行索引
```

Selected-final 精修关闭时不得缺少任何 Stage2/3 必需字段。

### 12.2 固定原阈值重跑

若启用精修：

1. 以已选 Global Proposal 的体素质心裁 80³ BOX。
2. 运行 Stage1 得到局部概率。
3. 使用该 Global Proposal 原来的 `threshold_rank` 与阈值，不搜索新阈值。
4. 若该阈值下产生多个局部连通组件，选择与投影进 BOX 的 Global Proposal Mask IoU 最大的组件。
5. 同时保存 `proposal_mask` 与 `refined_mask`。

选择原阈值使精修保留候选的置信层语义；“寻找与旧 mask IoU 最大的阈值”会把精修退化为复制原形状，因此不作为默认。

### 12.3 失败和截断

必须记录：

- 原 Global Proposal 总体素数；
- 进入 final BOX 的体素数；
- `proposal_was_clipped`；
- `refine_status`，至少区分 `success`、`empty`、`no_overlap_component`；
- 来源 `proposal_run_id/clg_id/group_parent_box_id/node_id/selection_run_id`。

精修失败不得静默伪装成成功。下游可以显式回退使用原 Global Proposal。Selected-final BOX 使用与 Group-parent BOX 相同的完整 voxel/P/receptor/rank-map 契约，但它自己的特征不能默认与 Group-parent 的 Refined Mask 混用。

---

## §13 产物关系与 BOX 接缝

### 13.1 追溯链

每个最终候选必须能沿稳定 ID 追溯：

```text
Stage1 checkpoint + full-map inference manifest
  → proposal_run_id
  → component tree: tree_id/node_id
  → CLG: clg_id/group_parent_node_id
  → Group-parent infered_box: box_id
  → selector_run_id: predicted_max_iou
  → selection_run_id: selected candidate rows
  → optional selected-final box/refined mask
```

### 13.2 共享表原则

一个 CLG 的 Group-parent BOX 保存：

- Group-parent Mask voxel 表一份；
- P token 表一份；
- Group-parent pocket receptor 表一份；
- `threshold_rank_map[80,80,80]` 一份；
- `N` 个候选在三张共享表中的 ragged 行索引；
- 候选树身份、阈值、LCA 距离、Global Proposal overlap 与 provenance。

旧契约中的 `blob_mask`、`blob_voxel_prob`、`blob_voxel_feat`、P/receptor 多尺度特征、pocket atom index、coverage、atom coverage、scores 与 prompt 都必须能从新字段直接取得或确定性派生。详细字段见 `文档/讨论/BOX-level数据契约.md`。

---

## §14 实现模块与配置边界

推荐将代码分成下列职责单一的模块；名称可以调整，但职责不能重新混合：

```text
stage1_data/
  box_builder.py              # 训推共用裁剪和输入组装
  train_dataset.py            # center/bias/context sampler
  sliding_window_dataset.py   # 按索引产生整图窗口
  collate.py

stage1_inference/
  probability_assembler.py    # 单图唯一逻辑写者
  threshold_calibration.py
  component_forest.py
  clg_enumerator.py
  materialization.py
  refinement.py

proposal_selector/
  dataset.py
  pooled_baseline.py
  pcln.py
  tree_relative_attention.py
  antichain_dp.py
  calibration.py
```

建议配置分组：

```yaml
stage1_train: ...
full_map_inference: ...
threshold_calibration: ...
component_forest: ...
clg: ...
materialization: ...
proposal_selector: ...
selection_calibration: ...
selected_final_refinement: ...
density_context_modulator: ...
```

配置必须写入 run manifest 并参与 run ID/hash。实现不得用隐式默认回退掩盖缺失配置。

---

## §15 验证、消融与验收

### 15.1 单元不变量

- 阈值降低时组件 mask 只扩大；每个高阈值节点至多一个低阈值父节点。
- 组件森林固定 26-连通且不执行边缘 5 voxel 丢弃。
- 一个 CLG 只有一个 Group-parent Node。
- 同一输入在不同遍历顺序、worker 数下产生相同 CLG。
- 一次 split/merge 事件的姐妹要么全部加入，要么全部拒绝。
- 已退休的可比较谱系不会再次产生 CLG。
- Group-parent Mask 包含每个候选 Global Proposal Mask。
- 每个候选的 voxel/P/receptor 行索引不越界且组内不重复。
- `threshold_rank_map<=r` 能重建第 `r` 个局部阈值前景。
- 反链结果不存在祖先—子孙对；空集合法。
- 关闭 selected-final 后，Stage2/3 输入仍完整。

### 15.2 必须报告的统计

- 每个 $\alpha$ 的 micro/macro-$F_\alpha$、阈值和阈值重复映射。
- 每张图各层组件数、CLG 数、候选数、候选上限原子拒绝率、PDB cap 截断率。
- 节点因过小、过大、触边、80³ fit 失败而被剪枝的数量。
- 选择器 IoU 回归误差、辅助分类 precision/recall/F1。
- coverage/one-to-one F1 在 0.3/0.6 下的四个分量及平均值。
- F1 baseline 与 multi-threshold 的候选 recall、假阳数和 Stage2/3 下游指标。
- Dataset 等待、GPU 利用率、完整图吞吐、局部重跑吞吐和落盘体量。

### 15.3 第一轮实验矩阵

核心 2×2：

| 候选路线 | selected-final off | selected-final on |
|---|---|---|
| F1 单阈值 | 基础基线 | 只测试居中精修收益 |
| 多阈值 CLG + selector | 主路线 | 测试选择与精修是否互补 |

选择器消融：

1. pooled MLP；
2. mask-conditioned multi-source pooling；
3. 加 Tree-Relative Transformer；
4. 加 parent latent；
5. 可选 density context modulator 开/关。

树枚举消融：event depth 1 与 2。完整等变网络、PointNet++ 重建主干和 dense 80³ rank-map CNN 不进入第一轮。

### 15.4 实现完成标准

当以下条件同时满足，Stage1 多阈值推理才可交给 Stage2/3：

1. 基础 Stage1 在新数据上完成训练和完整图验证。
2. 组件森林、CLG 枚举和反链 DP 通过确定性与不变量测试。
3. F1 baseline 与 Group-parent materialization 都能按 BOX 契约落盘并冷读。
4. selector 可以从落盘数据独立训练、推理和缓存分数。
5. `b,lambda` 能仅用缓存结果重新标定。
6. 关闭 selected-final 与 density U-Net 时，Stage2/3 可直接读取选中的 Global Proposal。
7. CPU/GPU 流水没有明显串行空洞，且实际吞吐、内存与磁盘体量有记录。

---

## §16 文献依据与采用边界

- [Mask2Former](https://openaccess.thecvf.com/content/CVPR2022/html/Cheng_Masked-Attention_Mask_Transformer_for_Universal_Image_Segmentation_CVPR_2022_paper.html)：采用 mask-conditioned attention 的读取方式；本文 mask 固定为 Global Proposal，不迭代预测 mask。
- [Set Transformer](https://proceedings.mlr.press/v97/lee19d.html)：采用无序集合的 attention pooling 与共享上下文思想。
- [Graphormer](https://proceedings.neurips.cc/paper/2021/hash/f1c1592588411002af340cbaedd6fc33-Abstract.html)：采用把树结构编码为 attention bias 的原则；本文使用 LCA 有向距离而非一般图最短路。
- [Attention-based Deep Multiple Instance Learning](https://proceedings.mlr.press/v80/ilse18a.html)：gated-attention pooling 作为轻量基线；AdaLigand 有节点级标签，不把任务称为经典 MIL。
- [Perceiver IO](https://arxiv.org/abs/2107.14795) 与 [VoxSeT](https://openaccess.thecvf.com/content/CVPR2022/html/He_Voxel_Set_Transformer_A_Set-to-Set_Approach_to_3D_Object_Detection_CVPR_2022_paper.html)：少量 parent latent 只作为进阶共享上下文，不替代候选 membership。
- [EGNN](https://proceedings.mlr.press/v139/satorras21a.html)：若增加几何消息传递，只采用基于距离且不更新坐标的版本。当前上游特征不是合法的等变表示，所以第一版不使用完整 SE(3)-Transformer 或 Equiformer。

---

## §17 仍需由数据标定的配置

以下不是算法空白，而是实现后必须通过 calibration 分布冻结的数值：

- `min_voxels` 的最终值与 `max_voxels`；
- `N_abs`、`N_floor` 和候选上限升档条件；
- threshold 扫描网格和相同 micro-$F_\alpha$ 的最终 tie-break；
- `theta_valid`、辅助分类 loss 权重 `gamma`；
- selector 的 `d/heads/layers/dropout`；
- pocket 包络半径与 P membership 的确定性规则；
- density context modulator 的具体 U-Net 宽度、预训练任务与是否缓存；
- selected-final 是否进入正式生产，取决于 2×2 消融结果。

这些值一旦用于正式 run，必须进入配置、manifest 和 run ID；不得只存在于脚本局部常量中。
