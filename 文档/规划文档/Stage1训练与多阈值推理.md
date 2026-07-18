# AdaLigand Stage1 训练与多阈值推理计划

> **文档角色**：本文是 Stage1 训练、整图推理、多阈值候选构造、候选选择网络、反链选择和局部特征物化的当前目标规格。它面向代码实现，不记录方案演变历史。
>
> **上游**：`文档/规划文档/数据处理_v2.md` 产出整图密度、受体、标签与 occurrence 数据；`Data_Preprocessing/Ori_Data/code/readme.md` 说明当前数据产物。
>
> **并列契约**：`文档/讨论/BOX-level数据契约.md` 规定本文产物的盘上字段、逻辑 dtype、ragged 关系和追溯方式。本文规定“怎样产生以及表示什么”，BOX 契约规定“怎样保存”。
>
> **下游**：`文档/讨论/模型总规划_v2.md` 与 `文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md` 消费选中的候选及其共享特征。
>
> **范围**：本文只收口 Stage1 训练与推理：`unet_c1`/Find、整图概率、组件森林、CLG、首次局部物化、selector、selection、F1 baseline 与可选 selected-final。selector 网络架构、addon 机制和 selected-final 都是现行设计，除非出现明确冲突不得整段删除。Stage2/3 只作为消费接口出现，其模型与训练由各自计划负责。
>
> **测试设定**：Stage1 候选生成本身不读取配体身份或数量；但本文提到的下游 Match、coverage/one-to-one 接口与评估只服务“已知配体身份和数量”的测试。未知身份或未知数量不在本轮设计范围。
>
> **治理**：本文是目标规格。若实现与本文不同，先按 `AGENTS.md` 分类说明良性、中性、恶性和未完成漂移，再由用户决定是否回填；不得用“代码优先”静默改写计划。

---

## §1 目标与不变量

Stage1 的最终职责不是只给出一张二值图，而是形成一条可重复、可标定、可供 Stage2/3 使用的候选生产链：

1. 按 `Stage1训练实现计划.md` 使用新数据全量训练纯密度 `unet_c1` 与密度+受体联合 Find；Find 保留 ligand-area、receptor 与 P 输出。
2. 用与训练完全相同的数据处理路径进行整图滑窗推理，组装完整概率图。
3. 在多个经过标定的阈值上构造连通组件森林。
4. 从组件森林确定一组互不重叠的**候选谱系组（Candidate Lineage Group, CLG）**。
5. 每个 CLG 只做一次必要的 Group-parent 居中重跑，为整组候选补齐共享的 voxel、P 与 receptor 特征。
6. 小型候选选择网络始终对第一次整图推理产生的 **Global Proposal Mask** 打分。
7. 选择器先判断整个 CLG 是否为假阳性；仅对判为有效的 CLG，在非空可行反链中求最优组合，得到交给 Stage2/3 的候选 blob。
8. 可选的 selected-final 居中精修只改善最终形状，不参与候选身份建立或选择器标定。
9. F1 baseline 是并行基线：直接物化 F1 层全部合法 blob 并交给 Stage2/3，不运行 CLG selector。

下列不变量贯穿训练与推理：

- blob 身份只来自第一次整图概率图的组件森林；局部重跑不创造或替换候选身份。
- `center`、`bias`、`context` 只说明训练 BOX 原点的来源，不说明样本正负。
- 训练与推理使用同一个 BOX builder、Dataset `__getitem__` 主路径和 collate。
- CLG 枚举在训练、验证和推理中使用同一算法与配置，不读取 GT，也不读取选择网络输出。
- 普通 `tree_id/node_id/CLG_id/candidate_index` 只是在一批已落盘产物内连接表格；不追求跨重跑规范编号，不为罕见同分设计自定义 tie-break 或稳定排序。
- 多阈值选择和 selected-final 精修是两条独立路径；关闭精修后仍能完整运行 Stage2/3。
- Group-parent 局部重跑产生的多阈值形状只作辅助观察；网络的评分对象仍是 Global Proposal Mask。

---

## §2 术语、方向与符号

### 2.1 坐标与维度

| 符号 | 含义 |
|---|---|
| `D,H,W` | 完整概率图的 `Z,Y,X` 三轴长度。完整网格张量形状为 `[D,H,W]`。 |
| `B_z,B_y,B_x` | 局部 BOX 形状，第一版固定为 `80,80,80`。 |
| `T` | 去重后的物理阈值数；代码与 schema 字段名使用 `num_threshold_levels`，且必须小于 255。 |
| `N` | 一个 CLG 中可供选择器评分的候选节点数；代码字段名使用 `num_candidates`。 |
| `K_v` | Group-parent Mask 中保存 voxel 特征的体素数；代码字段名使用 `num_parent_voxels`。 |
| `N_P` | Group-parent 局部重跑保存的 P token 数；代码字段名使用 `num_P_tokens`。 |
| `R` | Group-parent pocket 中保存的受体原子数；代码字段名使用 `num_receptor_atoms`。 |
| `d` | 选择器的统一隐藏特征维度；代码字段名使用 `hidden_dim`。 |

网格索引和张量空间轴统一写成 `ZYX`；世界坐标统一写成 `XYZ`，单位为 Å。任何在两者之间的转换都必须显式使用 BOX 原点与 voxel size，不能靠轴序猜测。

### 2.2 核心术语

| 术语 | 严格定义 |
|---|---|
| **全图概率图（Global Probability Map）** | Stage1 对完整密度图滑窗推理并融合后得到的 ligand-area 概率张量 `P_global[D,H,W]`。 |
| **阈值层（Threshold Level）** | 给定阈值 `t_r` 后的上水平集 `F_r={x | P_global(x) >= t_r}`。物理阈值按从高到低排列。 |
| **组件节点（Component Node）** | 某个阈值层中，按 26-连通得到的一个连通组件。一个节点对应一个确定的全图体素 mask。 |
| **组件森林（Component Forest）** | 相邻阈值层的组件按包含关系连边。边从低阈值组件指向高阈值组件；因此每个非根节点只有一个入边，每棵树是一棵有根有向树。它是离散阈值上的 max-tree。 |
| **F1 种子（F1 Seed）** | 位于 micro-F1 最优阈值 `t_F1` 所在层、满足节点可选择条件且仍存在于工作副本中的组件节点。 |
| **类种子姐妹（Seed-like Sister）** | 向低阈值扩展发生合并时，被同一合并父节点直接合并进来的其它姐妹节点。它们与原种子一样获得向高阈值分裂的预算。 |
| **候选谱系组（Candidate Lineage Group, CLG）** | 由种子、允许深度内的可选择祖先/子孙及合并姐妹组成的候选集合；这些候选在完整组件树上的最小连接闭包是一棵有根有向子树（rooted arborescence）。一个 CLG 是选择器 Dataset 的一个样本。 |
| **组父节点（Group-parent Node）** | 一个 CLG 中阈值最低、因而 mask 最大的唯一节点。它是该 CLG 的根。 |
| **全图候选（Global Proposal Candidate）** | CLG 中一个可选择组件节点；其 **Global Proposal Mask** 是第一次整图组件森林中的原始 mask。 |
| **反链（Antichain）** | CLG 的候选子集 `S`，其中任意两个节点都不存在祖先—子孙关系。反链按定义已经可行；空集也是反链。 |
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
| **ragged / 变长表** | 不同候选拥有不同数量的 voxel 或 receptor membership；盘上用 `offsets + indices` 表示，不补成固定长度。不同候选可引用相同 parent index；同一候选内部 indices 唯一，不要求额外稳定排序。P token 由 BOX 内全部候选共享，不使用 candidate-P membership。 |
| **artifact / 产物** | 一次数据处理、训练或推理正式落盘的结果，例如完整概率图、组件树、selector score 或 selection result。 |
| **artifact provenance / 产物来源链** | 记录一个产物由哪份输入、checkpoint、配置和上级产物生成，避免跨 run 错配。 |
| **manifest / 运行清单** | 描述某类产物来源、配置、字段、坐标帧和 schema 的只读结构化元数据；run ID 必须能定位对应 manifest。 |
| **calibration / 标定** | 在独立校验集上选择阈值或少量推理参数，不更新神经网络权重。 |
| **selector / 候选选择器** | 先预测 CLG 是否有效，再对 CLG 中每个 Global Proposal 预测最大 IoU 与结构化选择效用的小网络。 |
| **cross-attention / 交叉注意力** | 一组 query 从另一组 token 读取加权信息；候选 query 对 voxel/receptor 只读取自己的 membership，对 P 读取 BOX 内全部 token。 |
| **membership / 归属索引** | 某个候选在 Group-parent 共享 voxel 或 receptor 表中可以读取哪些元素；它是 parent table index 集合，不是另存一份特征。 |
| **candidate index / 候选下标** | 一个 CLG 内连续的 `0..N-1` 下标；`candidate_node_id[i]` 是该候选在原始组件树中的 `node_id`。`group_parent_candidate_index` 是 Group-parent 对应的唯一 candidate index。 |
| **运行 ID** | `probability_run_id`、`proposal_run_id`、`CLG_run_id`、`materialization_run_id`、`selector_run_id`、`selection_run_id`、`refinement_run_id` 分别标识不同不可变运行清单；selected-final 的 materialization 与 refinement 共用同一 ID。ID 可以是实现生成的短字符串或清单摘要，只需在项目内唯一并能回到 manifest；本文不要求 canonical JSON、稳定哈希或跨重跑得到相同 ID。 |
| **readout / 读出头** | 把一个节点或集合的隐藏向量映射成最终监督量的小型线性层或 MLP；本文的 CLG readout 把全局 CLG 向量映射为标量 logit `a_G`。 |
| **DP / 动态规划** | 利用组件树递推计算反链结果而不枚举全部反链；训练用 `logsumexp` 递推求条件分布分母，推理用 `max` 递推求最优非空反链。 |
| **LCA / 最近公共祖先** | 组件树上同时是两个节点祖先、且离二者最近的节点；用于表示两个候选的谱系关系。 |
| **frontier / 待扩展端点** | CLG 枚举过程中尚待继续向高阈值方向搜索的分支端点及其已用预算。 |
| **accumulator / 概率累加器** | 一张完整图的 `probability_sum` 与 `weight_sum`；所有滑窗结果在这里按坐标累加。 |
| **latent token / 隐变量 token** | 少量可学习的共享摘要向量，用于压缩 Group-parent 的整体环境；只属于进阶模型。 |
| **padding mask / 补齐掩码** | batch 中区分真实 token 与补齐位置的布尔量，不表示空间 mask。 |
| **profiling / 性能剖析** | 测量各阶段实际耗时、显存、CPU 等待和 IO，而不是凭感觉判断瓶颈。 |

运行层次严格分开：

```text
Stage1 checkpoint（unet_c1 或 Find）+ 输入归一化 + 整图滑窗/融合
  → probability_run_id
  → 每个 PDB 的完整概率图 P_global

P_global + 阈值 + 连通组件/节点合法性规则
  → proposal_run_id
  → 每个 PDB 的组件森林
      tree_id
        └─ node_id

组件森林 + CLG 枚举参数
  → CLG_run_id
  → 每个 PDB 的 CLG 清单
      CLG_id
        └─ candidate_index ──引用──> (tree_id,node_id)
```

因此一张 `P_global` 在冻结阈值与组件规则后确定一片组件森林；一个 PDB 可以有 0、1 或多棵 `tree_id`。同一 proposal forest 又可以由不同 CLG 枚举配置产生多个 `CLG_run_id`。`node_id` 相对 `tree_id`，`candidate_index` 相对 `CLG_id`；二者不能混用。

---

## §3 Stage1 基础训练

### 3.1 训练输入与 BOX 来源

基础训练的完整实现只在 `文档/规划文档/Stage1训练实现计划.md` 定义，本文不复制第二套采样器。这里冻结与后续推理有关的交接事实：

- 质量过滤后先划分 train 75%、validation 固定 500 个 PDB–EMDB pair、calibration 固定 100 个 pair、其余全部进入 held-out test pool；所有 Stage1 模型沿用同一主划分。
- 训练预定位池只含 center/bias/context；每个 epoch 的全局数量为 `1:5:3`，validation 使用冻结、无增强、不重抽的同配比清单。
- `unet_c1` 只读取一个 `exp_clipnorm_nopost` 密度通道；Find 读取 Pocket_Plus 当前成熟的密度+受体点—体素输入。
- ligand-area 监督直接读取 schema v3 二值 mask，不生成 `ligand_dist_map`。
- Find 继续保留当前 receptor voxel auxiliary：`hardmask` 是 core receptor occupancy，`voxel_label` 是 binding receptor 的 home-voxel 标签；二者现场派生且不与 `voxel_valid_mask` 或 ligand-area target 混用。`unet_c1` 不读取它们。
- 第一版直接全量训练 `unet_c1`、Find CPC1、Find CPC2；代码正确性测试不是 pilot 训练。

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

训练和推理只允许在“BOX 起点怎样产生”、sampler 和是否加载 GT 上不同：

- 训练从轻量预定位池读取 `center/bias/context`。
- 整图推理由 map shape、window shape、stride 和样本编号确定窗口。

固定 80³ BOX 不增加 `voxel_valid_mask`。`pin_memory` 只是成熟训练配置中的性能开关，不是科学契约；少量 voxel size 非严格等方的 BOX 沿用当前可工作的增强语义并记录诊断，不为此重写项目。

### 3.3 GT atom envelope 的 CPU 成本

Stage2/3 无预测 blob 的试水训练使用 GT ligand atom envelope 定义口袋，不保留中心球备选。实现方式是每个 worker 为当前 PDB 缓存一棵 receptor `cKDTree`，对 ligand present atoms 批量做半径查询并合并索引。

该操作的复杂度近似为一次建树 `O(N_R log N_R)` 加少量局部查询；建树在同一 PDB 内复用。第一版现场计算，不预先物化。如果基准显示它占 Dataset 实际耗时的比例超过配置上限，再把结果提升为可选缓存，而不是改变口袋定义。

### 3.4 模型与训练头

Pocket_Plus 分割主干、candidate C、P anchor、density cube、typed P、P head 与 real/P cross-attention 保留。`unet_c1` 是独立纯密度基线。Find 取消：

- sparse-refine 的第三训练阶段；
- 最终 refine head 及其 loss；
- Stage2/3 不需要的推理多分类输出。

Find 保留的主监督包括当前 CPC 主配方实际启用的：

- 体素级 ligand-area 预测；
- 受体原子级 binding 预测；
- 受体 voxel auxiliary 预测；
- P token 的 ligand-area 归属预测。

`unet_c1` 与 Find CPC1 均按固定 validation BOX 的 ligand-area AP 选择 BEST；Find CPC2 按 P AP 选择 BEST，同时报告 receptor-atom binding AP（现有日志可仍使用 A/atom AP key）。CPC2 正式训练前必须由独立 preflight 证明 ligand-area 路径不会改变。

### 3.5 训练输出与检查

每次训练至少记录：

- 数据 split、数据 schema/version 和配置哈希；
- center/bias/context 实际采样数；
- ligand-area、binding 与 P 分支的实际启用 loss 和 AP；
- 每秒 BOX 数、DataLoader 等待时间和 GPU 利用率；
- 非严格等方样本与旋转诊断计数；
- checkpoint 校验值与 resolved config。

---

## §4 第一次整图推理：只组装概率

### 4.1 推理流水线

第一次整图推理的唯一必需模型产物是 `P_global[D,H,W] float32`。它必须正式落盘，不是可选缓存；此时不知道最终 CLG 和候选，因此不保存完整 Stage1 中间特征。

该阶段产生 `probability_run_id`。它来源于正式 Stage1 checkpoint、producer model（`unet_c1` 或 Find）、输入归一化、滑窗形状/步长、窗口权重、融合公式和上游数据 release；不包含阈值、组件树或 CLG 配置。run ID 标识跨 PDB 复用的冻结配方；每个 PDB 的实际完整网格几何、概率图引用和内容哈希写在 `(probability_run_id,pdb_id)` 结果记录中，不因图形状不同拆成多个 run。概率图以 `float32` 保存，后续所有 proposal/tree 都只能读取这份正式产物。`unet_c1` 可走到完整概率、F1 组件与指标，但不做要求 P/receptor 特征的局部物化；正式 F1 materialization 与 CLG selector 路线使用 Find。

流水线划分为三个可重叠阶段：

1. DataLoader worker 读取整图资产、裁剪滑窗、构造辅助密度通道和受体输入。
2. GPU 批量执行 Stage1 forward，输出窗口概率。
3. 独立的 CPU 组装器把窗口概率写入该 PDB 的 `float32` 概率累加器，完成融合后保存正式概率图。阈值和组件森林属于后续 `proposal_run_id`；CLG 枚举另属引用 proposal 的 `CLG_run_id`，三者不混合。

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

`window_weight` 固定使用历史方案的三维 Gaussian 窗。把每轴局部坐标线性映射到 `[-1,1]`，记为 `u_z,u_y,u_x`，则：

$$
window\_weight(u)=
\exp\left(-\frac{u_z^2+u_y^2+u_x^2}{2\sigma^2}\right),
\qquad \sigma=0.5.
$$

坐标归一化、`sigma`、融合公式、逻辑 dtype 与概率产物内容校验值必须写入 probability manifest。不得沿用“窗口边角 5 voxel 直接丢弃”的规则。同一 `probability_run_id` 可以被多套阈值/组件配置复用并产生不同 `proposal_run_id`；同一 proposal 又可由不同 CLG 配置产生不同 `CLG_run_id`。更换 Find checkpoint、输入归一化或任何影响 `P_global` 的推理配置必须产生新的 `probability_run_id`。

### 4.3 blob 的唯一来源

所有正式候选都来自完整 `P_global`。`center/bias/context` 不运行逐 BOX Stage1 推理，也不拥有 blob、coverage 或 Stage1 feature addon。整图推理按需建立 `CLG_group_parent`、`f1_baseline`、`selected_final` 三种 `materialization_role`；它们使用 BOX 契约中的同一推理物化描述子和 addon 接口，但不与训练预定位池混成通用 `box_type`。

---

## §5 多阈值标定

### 5.1 calibration set

calibration set 固定为主划分中的 100 个 PDB–EMDB pair。概率阈值、CLG 数量上限、selection 后处理参数（例如 `tau_G`）以及 selected-final 是否正式启用及其推理参数都只在这里完成；`lambda_count`、loss 权重、`gamma_focal` 与 selector 架构属于 train/validation 选择，不归 calibration。该集合不得参与 Find 或 selector 参数训练，也不得用 validation 或 held-out test pool 偷换 calibration 职责。

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
\left\{\frac12,\frac23,\frac45,1,\frac54,\frac32,2\right\}.
$$

对每个 $\alpha$ 独立搜索使 micro-$F_\alpha$ 最大的概率阈值，并记录完整扫描曲线。实现直接使用普通数组 `argmax`/库默认结果；完全同分不定义额外裁决，也不为它增加测试或排序代码。

不同 alpha 可能得到相同数值阈值。相同阈值只构造一个物理 Threshold Level；`alpha_to_threshold_rank[a]` 定义为第 `a` 个 `alpha_value` 对应的去重物理阈值在 `threshold_value[0..T-1]` 中的下标，因此多个 alpha 可以映射到同一 rank。独立最优阈值通常随 alpha 近似单调；第一版不做事后强制排序修正。若发生明显反序，应先报告 calibration 不稳定性，再决定是否扩大 calibration set。

F1 阈值既是旧单阈值基线，也是 CLG 枚举的初始种子层。

---

## §6 组件森林与节点可选择性

`proposal_run_id` 只由以下内容共同决定并写入 manifest：父 `probability_run_id`、冻结阈值表、26-连通规则、组件森林构造版本以及节点合法性参数。它不包含 CLG 深度、CLG cap、selector 或 selected-final 配置。

### 6.1 组件森林构造

对每个物理阈值 `t_r`：

1. 计算 `F_r = P_global >= t_r`。
2. 使用固定 26-连通提取连通组件。
3. 不执行腐蚀、膨胀、闭运算或边角裁切。
4. 在相邻阈值层间按体素包含关系连边。

一个高阈值组件只能属于一个低阈值组件，因此得到森林；一个低阈值组件可以有两个或更多高阈值子节点，算法不得假设二叉树。

每个原始组件节点至少记录：

```text
tree_id: int32                 # 在 (proposal_run_id,pdb_id) 内唯一
node_id: int32                 # 在 tree_id 内唯一
tree_parent_node_id: int32 | -1
threshold_rank: uint8
voxel_count: int32
bbox_min_zyx: int32[3]
bbox_max_zyx: int32[3]   # 闭区间
touches_full_grid_boundary: bool
probability_mean: float32
probability_max: float32
```

`tree_id/node_id` 可以直接按组件构造器本次产出的数组顺序赋值并随文件保存。它们只在当前 `proposal_run_id + pdb_id` 中有效；不要求输入置换、worker 数变化或重新运行后仍得到相同整数。

### 6.2 节点级合法性与严格截断

节点是否可以成为 Global Proposal Candidate 只由体素数与统一边界规则决定：

| 条件 | 当前节点可选择 |
|---|---:|
| `voxel_count < min_voxels` | 否 |
| `voxel_count > max_voxels` | 否 |
| 违反统一边界规则 | 否 |
| 其它正常节点 | 是 |

第一版 `min_voxels` 的推荐起点为 32，参考 Emap2lig；最终值由 calibration 统计确定。`max_voxels` 由真实 ligand-area 体积分布和候选数量曲线确定。

空间合法性只使用一条统一边界规则，不再分别设置“mask 触原图边界”“bbox 装不进 80³”或“居中 crop 越图”等互相重叠的门禁。

对轴 $a\in\{z,y,x\}$，设原始密度图该轴长度为 $L_a$，mask 体素索引均值为 $c_a$，BOX 长度为 $B_a=80$。整数起点使用固定的 half-up 舍入：

$$
s_a=\left\lfloor c_a-\frac{B_a-1}{2}+\frac{1}{2}\right\rfloor.
$$

BOX 保持该居中起点；`s_a` 可以小于 0，也可以满足 `s_a+B_a>L_a`。图外 exp/sim/GT mask 使用常数 0，图外不存在 receptor atom；世界坐标原点仍按该整数起点外推。令该轴上 BOX 与原始密度图的可观察交集为：

$$
\ell_a=\max(s_a,0),\qquad
u_a=\min(s_a+B_a-1,L_a-1).
$$

设该组件在原始密度图网格上的完整 mask（尚未投影到局部 BOX）的闭区间 bbox 为 `[bbox_min_a,bbox_max_a]`。节点满足统一边界规则，当且仅当：

$$
\ell_a<bbox\_min_a\le bbox\_max_a<u_a
$$

对三个轴都成立。也就是说：BOX 某一面位于原图内部时，检查完整 mask 是否贴着或越过该 BOX 面；BOX 某一面超出原图时，改为检查完整 mask 是否贴着原始密度图边界。该规则同时捕获 mask 被 BOX 截断、mask 被原图截断以及 mask 本身无法由 80³ 完整容纳的情况；不再用“80³ crop 是否完全在原图内”否定候选。

只有“当前节点可选择”的节点才进入 CLG 候选集合。严格枚举只从合法种子出发；沿某方向遇到第一个非法节点时立即停止该方向，不把非法节点当作桥继续穿越。每个完成 CLG 的 Group-parent 必须可选择且可物化，并且能由 `group_parent_candidate_index` 唯一定位。

第一版不计算或保存 receptor clash、碎片密度等化学启发式过滤量。

---

## §7 候选谱系组枚举

`CLG_run_id` 由父 `proposal_run_id`、split/merge 事件预算、每组候选上限、每 PDB CLG cap 及其它确实影响枚举结果的参数共同决定。它不包含 selector checkpoint、门控阈值或 selected-final 配置。

原始 proposal forest 始终只读。枚举开始时为每棵树建立一个轻量工作副本；实现可真正复制父子邻接，也可只增加 `active[node]` 布尔数组，但语义必须等同于“从副本删节点”。CLG 的种子、扩展和后续删除都只在工作副本上进行，不在原树旁边维护第二套穿越状态机。

### 7.1 事件预算

从一个种子沿组件树扩展时：

- 经过只有一个继续分支的链条不消耗事件预算。
- 向高阈值经过一次一对多分裂，消耗一次 `split_event`。
- 向低阈值经过一次多对一合并，消耗一次 `merge_event`。
- 一次三路或更多路合并仍算一个 merge event。
- 合并父节点进入 CLG 时，所有直接姐妹同时进入，并成为类种子姐妹；每个姐妹获得与原种子相同的向高阈值 split 预算。

第一版默认：

```yaml
CLG:
  max_split_events: 1
  max_merge_events: 1
  max_candidates_per_CLG: 20
```

事件深度 2 只用于树枚举消融，并用 GT 标签计算可达到的理论上限；其初始 `max_candidates_per_CLG=40`。若 calibration 上事件被候选上限原子拒绝的比例过高，可分别升至 32/64。

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
2. 向高阈值经过 unary continuation：目标节点可选择时加入且 `split_used` 不变；目标非法时停止该 frontier。
3. 向高阈值经过多路 split：只有 `split_used < max_split_events` 才能接受；全部直接子分支原子加入，并把各自 `split_used` 设为旧值加 1。
4. 向低阈值经过 unary continuation：目标节点可选择时加入、`merge_used` 不变并更新当前最低阈值节点；目标非法时停止该方向。
5. 向低阈值经过多路 merge：只有共享的 `merge_used < max_merge_events` 才能接受；合并父节点与全部直接姐妹原子加入，随后 `merge_used += 1`。
6. 每个新姐妹获得新的 `lineage_seed_id`，其向高阈值 `split_used=0`，因此拥有与原始种子相同的完整 split 预算；所有分支共享已经消耗的 `merge_used`，不能通过加入姐妹重置向低阈值预算。
7. 任一原子事件触发候选数上限时，整个事件不进入状态队列。

一次事件要求加入的任一节点不可选择时，整次事件拒绝且不消耗预算：split 事件任一直接子分支非法，则该 frontier 的向高阈值扩展终止；merge 父节点或任一直接姐妹非法，则整个向低阈值 merge 事件拒绝并终止该方向。这里的“可加入”同时要求节点仍存在于工作副本中且合法；已删除或非法节点都不加入、也不被穿过。预算只在真正接受的 split/merge 事件处变化。

### 7.2 同层处理顺序

每个阈值层的全部 active、可选择节点按 mask 内整图 ligand-area 概率均值降序处理。完全同值时沿用所用排序库的普通结果；不再按 `tree_id/node_id` 加次级排序，也不要求 stable sort。

随后严格依次处理：

1. 取当前排序中第一个仍 active 的节点作为种子。
2. 按 §7.1 的 split/merge 预算完整构造该 CLG；接受 merge 时，合并父节点及全部直接姐妹作为一个原子事件加入。
3. CLG 完成后立即按 §7.4 从工作副本删除对应谱系。
4. 回到同层序列，跳过已从工作副本删除的节点，继续下一个种子。

同层顺序决定本次枚举与 `N_cap` 截断顺序。完全同分时，库的普通返回顺序可能改变 `CLG_id` 排列、实际生成的 CLG 或达到 cap 时保留的子集；允许如此，不增加自定义 tie-break 或 stable sort，也不承诺跨重跑一致。

### 7.3 层次扫描顺序

1. 首轮按 §7.2 处理 F1 阈值层的全部有效种子。
2. 随后依次向更低阈值层扫描，并在每层重新按 §7.2 处理仍 active、可选择的节点。
3. 不从高于 F1 的层单独开启新组；高阈值节点通过种子或类种子的向上分裂扩展进入 CLG。

每个完成的 CLG 在完整原始组件树上的最小连接闭包必须是一棵连通有根有向子树，并且只有一个 Group-parent Node。不可选择节点可以存在于用于审计的原始树中，但严格扩展不会穿越它继续收集候选。

### 7.4 在工作树中删除已处理谱系

CLG `G` 形成后，从工作副本一次删除与该组可比较的谱系：

$$
D(G)=Ancestors(group\_parent)\cup Subtree(group\_parent).
$$

`Subtree(group_parent)` 包含 Group-parent 自身。因为 Group-parent 是本 CLG 全部候选的祖先，该式等价于删除 `G` 及其全部可比较祖先/子孙。实现只需一次向上、一次向下遍历并令这些节点在工作副本中不存在；原始 proposal forest 和已完成 CLG 产物不改。

删除集合依赖 Group-parent，不依赖网络最后选出的反链 `S`。后续枚举只在剩余工作树上运行，删掉的节点自然既不能成为种子，也不能被扩展穿过；不需要另写删除节点穿越状态分支。

### 7.5 事件原子性与候选数上限

一次 split 或 merge 事件涉及的全部直接姐妹是一个原子单元。如果加入整个事件会使候选数超过 `max_candidates_per_CLG`，拒绝整次事件；不得只保留分数最高的前 K 个姐妹。

同样地，事件内任一必选节点不可选择时，拒绝整次事件；不得只删除非法姐妹后接受其余部分。事件因候选上限或非法节点被拒绝时，都终止该 frontier 对应方向的扩展。

### 7.6 每个 PDB 的 CLG 数量保护

令 `N_F1_seed` 为任何工作树删除发生前，F1 层全部合法、可作为种子的节点数。每个 PDB 的在线上限为：

$$
N_{cap}=\min\left(
N_{abs},\;N_{multi}\max(2,N_{\mathrm{F1\ seed}})
\right).
$$

第一轮默认 `N_abs=300`、`N_multi=3`；因此 F1 层为 0 或 1 个合法种子时，多阈值路线仍最多允许 6 个低阈值补救 CLG。CLG 仍由“F1 层优先、随后逐层向低阈值、同层按 mask 内整图 ligand-area 概率均值排序”的严格算法产生；完成数达到任一上限时立即停止，不先生成全部 CLG 再二次筛选。该上限只约束多阈值路线，F1 baseline 仍保存全部合法 F1 blob。

每个 PDB 必须记录 `n_f1_legal_seeds`、`n_CLG_cap`、`n_CLG_completed`、`CLG_cap_reached` 和 `next_eligible_seed_exists_at_stop`。在线停止不会继续构造未保留 CLG，因此不记录虚构的 `n_CLG_before_cap`。

---

## §8 局部重跑与特征物化

`materialization_run_id` 标识一种物化角色及其冻结输入：`materialization_role`、直接上级 `CLG_run_id/proposal_run_id/selection_run_id`、Find checkpoint/执行路径、BOX 裁剪与 feature-export 配置。一个 materialization run 只服务一种角色；每个 PDB 的 `box_id` 只在该 run 内有效。selected-final 的 `materialization_run_id` 与 `refinement_run_id` 共用同一字符串。

### 8.1 三种物化角色

| 角色 | 是否必需 | 一次对应什么 | 用途 |
|---|---|---|---|
| **F1 baseline materialization** | 基线实验必需 | F1 层的一个合法 blob | 以该 blob 居中重跑一次 Stage1 并物化与主路线同源的 voxel/P/receptor 特征；不运行 CLG selector，直接训练/运行 Stage2/3。 |
| **CLG Group-parent materialization** | 多阈值路线必需 | 一个 CLG，只运行一次 | 为整组 Global Proposal 候选保存共享 voxel/P/receptor 特征与局部多阈值形状。 |
| **Selected-final materialization** | 可选 | 一个已选 Global Proposal | 用原阈值做最终居中形状精修并生成独立完整 BOX。 |

三种角色都使用 BOX 契约中的同一推理物化描述子，通过 `materialization_role` 区分，不另造通用 `box_type`。F1 baseline 保存 F1 层的全部合法 blob，不受多阈值路线 CLG 数量上限限制；它不伪造 CLG、LCA、selector run 或 selection run。其 blob 身份仍来自第一次全图概率图，居中重跑只补特征，不替换原 mask。

三种物化角色中属于 Stage1-Find 主路径的概率与 voxel/P/receptor 特征，都必须使用产生上级 `probability_run_id` 的同一 Find checkpoint 和模型执行路径。可选 `unet_c1`/密度调制器只能作为独立 feature source 记录，不能冒充或替换 Find 主路径特征。

### 8.2 Group-parent 居中重跑

对一个 CLG：

1. 按 §6.2 的统一公式从 Group-parent Mask 体素质心确定 `box_start_zyx`；允许 BOX 越出原图并按统一补零契约读取。
2. 使用产生该 `probability_run_id` 的同一 Stage1 checkpoint 与模型路径，在该 BOX 上运行一次 Stage1；不得用另一套 Stage1-Find 权重给旧概率图/组件树补特征。
3. 物化原始 Group-parent Global Proposal Mask 对应的 voxel 特征、该次局部 forward 的全部 P token，以及 Group-parent pocket 的 receptor 特征。
4. 每个 Global Proposal Candidate 保存自己的 voxel membership 和 receptor-pocket membership；不同候选的 membership 允许交叉。P token 属于整个 BOX，所有候选读取全部 P。
5. 从局部 ligand-area 概率生成 threshold rank map。

Group-parent Mask 包含 CLG 内所有候选 mask，因此不另造 `union_pred_mask`。同一份 parent voxel、P 和 receptor 特征只物化一次。具体字段、dtype、offset/indices 和 feature-source manifest 只由 `文档/讨论/BOX-level数据契约.md` 定义，本文不重复盘上 schema。

### 8.3 threshold rank map

设 `threshold_value[0]` 为最高阈值。对局部概率 `P_local[z,y,x]`：

$$
rank(z,y,x)=
\min\{r\mid P_{local}(z,y,x)\ge t_r\},
$$

若不存在这样的 `r`，存 255。`rank_at_parent_voxel[k]` 表示在第 `k` 个 Group-parent voxel 的 BOX 局部 ZYX 位置查询上述 rank；该位置在全部阈值下均为背景时同样为 255。第 `r` 个阈值的完整局部前景可由：

$$
M^{local}_r = [rank\le r]
$$

精确重建。该表达允许某层前景为空或包含多个互不连通组件。rank map 如何进入 selector 属于 §10 的模型设计；本节只定义其语义与可重建性。

### 8.4 Global Proposal 与局部观察的边界

`candidate_voxel_membership` 描述 Global Proposal Mask 在 parent voxel 集合中的成员关系；`threshold_rank_map` 描述 Group-parent 居中重跑。两者可以不完全重合。局部位次图不再运行连通组件匹配，不产生新的候选身份，也不改变 `tree_id/node_id`。局部重跑在 BOX 内产生、但位于 Group-parent/CLG 之外的组件只保留在完整 rank map 中；候选读取、rank 统计和体积统计必须限制在 parent/candidate membership 内，不能让这些额外组件成为候选或泄漏到候选属性。

### 8.5 共享 pocket

Group-parent pocket 由 Group-parent Mask 的体素包络和统一半径确定，第一轮默认半径为 10 Å。保存：

- 一份 parent pocket 受体原子全局索引及其局部重跑特征；
- 每个候选自己的 pocket 原子在 parent pocket 集合中的 membership indices。

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

P_feature_fields:             上游 Stage1 本次实际导出的具名 P 特征表
P_pos_box_xyz:               [N_P, 3]
P_probability:               [N_P]

receptor_feature_fields:      上游 Stage1 本次实际导出的具名 receptor 特征表
receptor_coords:             [R, 3]
receptor_binding_probability:[R]

candidate_voxel_membership:  [N,K_v] bool 逻辑视图
candidate_receptor_membership:[N,R] bool 逻辑视图
candidate_attributes:        [N, C_s]
lca_up_distance:             [N, N]
lca_down_distance:           [N, N]
```

盘上 voxel/receptor membership 使用 `offsets + indices`，collate 后可转成上述 bool/padding 视图；不同候选允许共享同一个 parent index。所有候选读取 BOX 内全部 P，不存在 `candidate_P_membership`。上游运行清单直接列出本次实际导出的具名特征字段、模块出口、checkpoint、通道数、dtype 与坐标帧；selector 配置直接声明自己要求读取的字段。缺少任一必需字段即判定输入契约不兼容，不用全零数组伪造缺失网络层。

`P_pos_box_xyz` 是 P token 相对 BOX 原点的直接 XYZ 坐标，单位 Å，不是位置 embedding 或全局坐标。

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

这是 Stage1 selector 的 **independent-max oracle**：每个候选各自取与任一 GT occurrence 的最大 IoU，允许多个候选分别以同一个 GT 取得最大值。Stage1 不构造 Stage2 的 A/B/O 覆盖矩阵，也不做 Hungarian；one-to-one 只在最终 evaluator 里计算。

这是逐 blob 的连续软标签；若该 PDB 没有真实 occurrence，定义 `q_i=0`。CLG 的组合监督在反链集合上定义。记 `A(G)` 为 CLG `G` 的全部反链，包括空集。对任意 `S∈A(G)`，定义 oracle 质量：

$$
Q_{GT}(S)=
\sum_{i\in S}q_i
-\lambda_{count}|S|,
\qquad Q_{GT}(\varnothing)=0.
$$

第一轮 `lambda_count=0.05`，紧邻消融为 `0.03`。Dataset worker 从基础 proposal–occurrence overlap 在线构造小型 IoU 矩阵，并在 CPU 上现场计算 `q_i`、`S^*` 与 `y_CLG`；不建立持久 oracle 标签缓存。`lambda_count` 必须进入 selector 训练配置和 manifest，改变它意味着训练目标改变。若多个反链得分完全相同，使用当前 DP 实现自然返回的一个最优解；不定义额外裁决，也不测试跨重跑选择同一个解。

$$
S^*=\arg\max_{S\in A(G)}Q_{GT}(S),
\qquad
y_{CLG}=\mathbf 1[S^*\ne\varnothing].
$$

网络输出三个明确的监督对象：逐候选最大 IoU `q_hat_i`、逐候选未归一化选择效用 `z_i`，以及独立 CLG logit `a_G`。CLG 标签定义为 oracle 最优反链是否非空：

$$
p_G=\sigma(a_G),\qquad y_G=y_{CLG}=\mathbf 1[S^*\ne\varnothing].
$$

令 `A_+(G)=A(G)\setminus\{\varnothing\}`。仅当 `y_G=1` 时定义条件非空反链分布；其分数和分布详见 §11。第一版三项损失默认等权：

当 `gamma_focal=0` 时：

$$
L_{CLG}=\operatorname{BCEWithLogits}(a_G,y_G).
$$

为了与 focal 统一，令 $p_{G,t}=y_Gp_G+(1-y_G)(1-p_G)$，则一般形式为：

$$
L_{CLG}^{focal}=-(1-p_{G,t})^{\gamma_{focal}}\log p_{G,t}.
$$

$$
L_{blob}=\operatorname{mean}_{i\in G}
\operatorname{SmoothL1}(\hat q_i,q_i),
$$

`L_blob` 对正负 CLG 都计算；按 CLG 内候选数取平均，避免候选较多的 CLG 仅因节点数获得更大权重。

令 $p_*=p_\theta(S^*\mid G\text{ 有效})$：

$$
L_{antichain}=-y_G(1-p_*)^{\gamma_{focal}}\log p_*.
$$

当 `gamma_focal=0` 时，它等价于：

$$
L_{antichain}=y_G\left[
-score_\theta(S^*)+
\log\sum_{S\in A_+(G)}\exp(score_\theta(S))
\right].
$$

$$
L=w_{CLG}L_{CLG}+w_{blob}L_{blob}
+w_{antichain}L_{antichain},
$$

第一轮 `w_CLG=w_blob=w_antichain=1`。

`gamma_focal=0` 等价于 BCE 与结构化 CE，第一轮默认 0；`gamma_focal=2` 是紧邻标准 focal 实验。主实现中负 CLG 的 `L_antichain` 由 `y_G` 严格抑制为 0，`a_G` 不进入反链能量，selection loss 也不向 CLG readout 的专属参数传播。第一版不实现反链软分布 KL，也不增加独立的反链绝对质量回归 head。

selector 第一版按固定 validation CLG 上的总损失 `L`（全部 validation CLG 等权平均）最小选择 `BEST.ckpt`；同时报告三项分量、`q` 回归、CLG AP 与反链指标，但不另造复合 checkpoint 分数。`tau_G` 只在 BEST 冻结后由 calibration 100 选择，不能反过来参与 checkpoint 选择。

受 Mask3D 启发的下游概率抑制只作为隔离消融，配置默认必须关闭：

$$
L_{ablation}=L_{CLG}+\operatorname{stopgrad}(p_G)
(L_{blob}+L_{antichain}).
$$

不 `detach` 的版本只作第二级消融。关闭开关时，代码路径、主损失、负 CLG 的反链抑制和推理必须与没有该消融功能时完全等价。

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

这里 `v/P/R` 分别表示 voxel、P pseudoatom 与 receptor atom，`m` 是三者之一的模态索引。`E_v/E_P/E_R` 是模态专属的浅层可学习 token encoder，第一版使用 `LayerNorm → Linear → SiLU/GELU → Linear` 投影到共同维度 `d`；它们不是新的 dense backbone。

`X_v` 至少包含：

- 已命名的 Stage1 voxel/UNet 多尺度特征；
- 归一化 BOX 坐标；
- 第一次全图概率；
- 局部 `rank_at_parent_voxel` embedding。

`X_P` 使用 selector 配置明确要求、且由同一上游 Stage1 运行实际导出的具名 P 特征，并包含 `P_pos_box_xyz` 与 `P_probability`。`X_R` 同理使用具名 receptor 特征，并包含受体坐标与 `receptor_binding_probability`。例如未执行第二阶段 cross-attention 的上游路径不会产生 cross-attention 后特征；消费者不得用全零数组伪造。每个实际字段的层次语义必须固定，feature-source manifest 写出生产模块、checkpoint、通道数、dtype 与坐标帧。

每种模态的概率使用：

$$
\tilde p=clip(p,\epsilon,1-\epsilon),\qquad
probability\_features=[p,\log(\tilde p/(1-\tilde p))].
$$

`raw probability + clipped logit` 进入模态专属 token encoder。归一化 BOX 坐标使用低频 Fourier 编码；概率不使用扩散 timestep 式高维 Fourier。第一版同时把概率作为显式、可学习强度的 attention prior。对模态 $m\in\{v,P,R\}$、注意力头 `h`、候选 query `i` 和 key token `j`：

$$
\ell_{ij}^{(m,h)}=
\frac{\mathbf q_i \mathbf k_j^\top}{\sqrt d}
+b_{ij}^{(m,h)}
+\beta_{m,h}\log(\operatorname{clamp}(p_j,\epsilon,1))
+M_{ij}.
$$

`mathbf q_i`/`mathbf k_j` 是 attention 的 query/key 向量，与监督标签 `q_i` 无关；`b_ij` 是已有的坐标/模态关系 bias，`M_ij` 是 membership/padding mask。`beta_mh` 可学习并零初始化；因此初始模型不预先压制低概率 token，训练后才决定显式 prior 的强度。Tree-Relative Transformer 的候选间 bias 不重复塞入原始 token 概率；候选概率已经通过多模态内容进入节点表示。

每个候选的初始 query：

$$
Q_i^{(0)}=\operatorname{MLP}(A_i)\in\mathbb R^d.
$$

候选属性 `A_i` 第一版包含：threshold rank/value、`log(1+voxel_count)`、相对 Group-parent 体积、候选 mask 内整图概率的均值/最大值/分位数、归一化质心、三个排序后的 mask 坐标协方差特征值，以及到 Group-parent 的树距离。协方差特征值描述形状尺度且不依赖坐标轴顺序。这些量由 Dataset worker 从 Global Proposal mask、概率、树属性和 membership 在 CPU 上向量化派生，不进入核心 BOX 落盘契约；selector manifest 记录有序属性名、归一化统计和 recipe 版本。定义尚不稳定的 rank histogram 与局部体积曲线不进入第一版。

### 10.3 Global Proposal mask-conditioned 读取

候选 `i` 对 voxel 和 receptor 只读取自己的 membership，对 P 读取 BOX 内全部 token：

$$
Z_i^v=Attn(Q_i^{(0)},H_v[I_i^v],H_v[I_i^v]),
$$

$$
Z_i^P=Attn(Q_i^{(0)},H_P,H_P),
\qquad
Z_i^R=Attn(Q_i^{(0)},H_R[I_i^R],H_R[I_i^R]).
$$

等价的 padded 实现是在 voxel/receptor attention logit 上加 membership mask：属于候选的 token 加 0，其余加负无穷。parent token 只编码一次，候选之间共享，不复制特征表；不同候选的 membership 可以交叉。

P token 是 BOX 级伪原子集合，不按 blob 划分。空 P 集合或空 receptor 子集在模型内使用一个可学习 null token，并提供 `modality_present` 标志；伪 token 不写入磁盘。

### 10.4 Group-parent 共享摘要

只看候选内部可能忽略姐妹分支和连接区。每个模态额外生成一个 parent 摘要：`g_v` 池化 Group-parent voxel 表，`g_P` 池化 BOX 内全部 P token，`g_R` 池化 Group-parent pocket receptor 表；它们不是某个祖先节点的 embedding。

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

有序对 `(u_ij,d_ij)` 可区分 self、祖先、子孙、姐妹及其它分支。另构造相对特征 `r_ij`，至少包含 LCA 上下距离、阈值差、候选质心相对坐标/距离和 log 体积比。第 `h` 个注意力头使用：

$$
A_{ij}^{h}=
\frac{(W_Q^hE_i)(W_K^hE_j)^\top}{\sqrt{d_h}}
+MLP_{bias}^{h}(r_{ij})
+M_{ij}.
$$

`M_ij` 是 batch padding mask。`MLP_bias` 每个有序候选对输出逐头标量 bias；第一版不把完整 `E_i/E_j` 再拼入 bias MLP，避免与 QK 内容打分重复，该变体只留作消融。该编码不使用任意 child index，因此姐妹顺序变化时输出只做相同排列，保持集合顺序无关。

第一版推荐起点：`d=128`、4 个注意力头、2 层、前馈子层隐藏维度 256、每个子层计算前执行 LayerNorm、dropout 0.1。它们是可配置起点，不是科学常数。

Tree-Relative Transformer 输出最终节点表示 `E_i`。逐节点输出头为：

$$
\hat q_i=\sigma(MLP_q(E_i)),\qquad
z_i=MLP_{selection}(E_i).
$$

其中 `q_hat_i` 回归该 blob 对任一 GT 的最大 IoU；`z_i` 是只在条件反链能量中使用的未归一化节点选择效用，不是独立概率。

CLG 真假判别使用独立的全节点汇聚机制。先融合 Group-parent 摘要并初始化唯一的 CLG query：

$$
g_G=MLP_{parent}[g_v\Vert g_P\Vert g_R],\qquad
q_G^{(0)}=q_G^{learned}+W_Gg_G.
$$

随后使用两层专属 cross-attention block；每层让该 query 读取全部节点 `E={E_1,...,E_N}`，再做残差、LayerNorm 和 FFN：

$$
\bar q_G^{(l)}=LN\left(q_G^{(l-1)}+
MHA_G(q_G^{(l-1)},E,E;M_{padding})\right),
$$

$$
q_G^{(l)}=LN\left(\bar q_G^{(l)}+FFN_G(\bar q_G^{(l)})\right).
$$

最后由两层 MLP readout 产生独立 CLG logit：

$$
a_G=MLP_{CLG}[q_G^{(2)}\Vert g_G],\qquad p_G=\sigma(a_G).
$$

CLG query 数固定为 1；它读取全部节点，不使用 raw `node_id`、oracle 反链节点集合、`z_i` 或 DP 输出。CLG 与 selection 分支共享昂贵的节点主干，但 readout 参数独立。`a_G` 不进入反链能量，因此 selection loss 不向 CLG cross-attention/readout 的专属参数传播；若以后观察到共享主干梯度冲突，再把 task adapter 或独立末层作为消融，不复制第一版完整多模态主干。

### 10.6 计算复杂度

令 `K=K_v+N_P+R`。padded masked attention 的主要复杂度为：

$$
O(NKd)+O(N^2d).
$$

当 `N≤20` 或 `N≤40` 时，树内 `N²` 项很小；H100/A800 上第一版直接使用标准 padded attention，不以 FlashAttention 为前提，也不增加自定义 ragged 底层算子。仍需记录峰值显存，避免把 padding 的内存问题误判成 FLOPs 问题。

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

第一版只让 voxel/密度点按自身网格位置 gather 对应尺度特征；P 与 receptor 不做三线性插值调制，Stage2/3 同样如此。点对象调制只保留为后续消融，不进入主规格；所有路径都不更新对象坐标。

对对象表示 `h[n,d]` 与采样上下文 `c[n,C]`，第一版推荐门控残差调制：

$$
g=\sigma(W_gc),\qquad
h'=LayerNorm(h+g\odot W_cc).
$$

这比直接拼接更容易保持关闭模块时的主干行为。三阶段共享相同输入归一化、特征出口命名和 checkpoint。第一版优先从现有预训练化学特征 U-Net 的基础权重初始化，以零初始化门控残差接入，并默认冻结；若某阶段单独微调，必须产生新的 checkpoint 身份，不能再声称三阶段共享同一组最终权重。

现有“预训练化学特征 U-Net”是该接口的默认初始化来源，不强制再造第二个 dense backbone。若另训更轻版本，两者通过不同 feature-source manifest 区分。第一版主模型必须在该模块关闭时完整可运行。

---

## §11 CLG 门控与条件结构化反链选择

### 11.1 两阶段概率分解

对一个 CLG `G`，记 `A(G)` 为包括空集的全部反链，`A_+(G)=A(G)\setminus\{\varnothing\}` 为全部非空可行反链。独立 CLG readout 预测：

$$
p_G=\sigma(a_G)=p(G\text{ 有效}).
$$

当 `G` 有效时，selector 为候选输出未归一化选择效用 `z_i`，反链能量显式包含与 oracle 相同的单位节点数惩罚：

$$
score_\theta(S)=\sum_{i\in S}z_i
-\lambda_{count}|S|,
\qquad S\in A_+(G).
$$

Tree-Relative Transformer 已使每个 `z_i` 感知整个 CLG，因此可加解码不等于候选独立建模。条件结构化分布为：

$$
p_\theta(S\mid G\text{ 有效})=
\frac{\exp(score_\theta(S))}
{\sum_{T\in A_+(G)}\exp(score_\theta(T))}.
$$

完整决策语义是：

$$
p(S=\varnothing)=1-p_G,
$$

$$
p(S)=p_Gp_\theta(S\mid G\text{ 有效}),
\qquad S\in A_+(G).
$$

这里的完整分解只解释两阶段决策，不把 `a_G` 加进任何非空反链能量。

推理先以 CLG 门控阈值 `tau_G` 判断真假。第一轮未校准基线为 `tau_G=0.5`：

$$
\hat S=\begin{cases}
\varnothing,&p_G<\tau_G,\\
\displaystyle\arg\max_{S\in A_+(G)}
\left[\sum_{i\in S}z_i-\lambda_{count}|S|\right],
&p_G\ge\tau_G.
\end{cases}
$$

反链能量完全同分时，接受 DP 自然返回的任一最优解。空结果只由第一阶段 CLG 门控产生；通过门控后第二阶段必须返回非空反链。

### 11.2 原始树上的精确 DP

祖先冲突始终沿完整原始组件树判断。对当前 CLG `G`，实现只在 `G` 于原树上的最小连接闭包运行树形动态规划：只有 `i∈G` 的节点可以被选择，闭包内其它节点只传递子树状态；同一原树中其它 CLG 的候选不进入本样本。选择某节点时排除其全部候选子孙；不选择时合并各直接子树。

训练 forward 中，对 `y_G=1` 的 CLG 立即使用 `logsumexp` 半环计算 `A_+(G)` 上的条件 softmax 分母并反向传播；`y_G=0` 时 `L_antichain=0`。冻结 selector checkpoint 后，推理使用同一树递推的 `max` 半环求非空 MAP 反链。实现可以在递推状态中显式区分“尚未选择节点”和“已经形成非空集合”，但不能枚举全部反链。

不建立新的候选身份或盘上 Candidate-induced Tree。若实现为减少遍历而临时把候选连接到最近候选祖先，这只是内存邻接缓存，必须与原树 DP 逐值一致，不能写入 schema 或 provenance。

### 11.3 selector 推理、selection 解码与实例指标

生命周期固定为：

1. **训练**：Dataset worker 从基础 overlap 在线计算 `q_i/S^*/y_G`；GPU forward 输出 `q_hat_i/z_i/a_G`；正 CLG 在同一步执行可微 `logsumexp` DP。训练过程不逐 epoch 落盘 oracle 或预测。
2. **冻结 checkpoint 后的 selector 推理**：对每个已物化 CLG 运行一次网络，按 `selector_run_id` 保存 `predicted_max_iou`、`selection_logit`、`CLG_logit` 与 `CLG_valid_probability`。
3. **selection 解码**：读取上述 score 与原始组件树，先按 `tau_G` 门控，再对通过者运行非空 `max`-DP；按 `selection_run_id` 保存门控结果和 `selected_candidate_indices`。

`lambda_count`、损失权重、`gamma_focal`、概率编码、模型结构、输入字段配方和候选属性 recipe 进入 selector manifest；该 manifest 还必须引用唯一的 `CLG_run_id`、`materialization_run_id` 和所需 feature addon manifests。相同 checkpoint 若用于另一套 CLG/物化输入，必须产生新的 selector inference run。`tau_G` 与解码规则进入 selection manifest。

calibration set 报告：

$$
M_{instance}=\frac{1}{4}(
F^{coverage}_{0.3}+F^{coverage}_{0.5}
+F^{1to1}_{0.3}+F^{1to1}_{0.5}).
$$

对 IoU 阈值 `tau`：

- **coverage F1**：候选只要与任一 GT 的 IoU 不低于 `tau` 就计作命中候选；GT 只要被任一候选命中就计作已覆盖。由命中候选比例与已覆盖 GT 比例计算 F1，允许多个候选覆盖同一 GT。
- **one-to-one F1**：在 `IoU>=tau` 的候选—GT 二分图上做最大一对一匹配。匹配数 `m` 给出 `precision=m/n_pred`、`recall=m/n_gt`，再计算 F1。

四项及其等权平均都必须分别报告。选择 `tau_G` 时，四项均由 calibration 全体 PDB 的汇总计数计算成 micro/global 指标；逐 PDB macro 只作诊断。第一轮同时报告未校准 `tau_G=0.5` 基线；随后在 calibration set 上按实际 `p_G` 分布灵活扫描门控阈值，默认可从 `0.00:0.01:1.00` 起步，也可先粗扫再局部细化。最终选择使完整两阶段输出的 `M_instance` 最大的 `tau_G^*`；相同最大值直接接受扫描数组 `argmax` 的普通结果，不增加次级规则。扫描规则、完整曲线和所选值写入 selection manifest；不得使用测试集调参。选择器训练、oracle 标签和结构化解码都只使用 Global Proposal Mask，不使用 Refined Mask。

### 11.4 计算预算

反链的条件 log-partition、非空 MAP 和 oracle 都只处理小树、小型 occurrence 集合与已保存 overlap 标量，远低于 Stage1 forward 成本。实现必须对小型穷举树验证 `A_+(G)` 条件分母、非空 MAP 和梯度，并记录 CPU 耗时。

---

## §12 可选 Selected-final 精修

### 12.1 独立性

多阈值候选选择在 Group-parent materialization 后已经完整结束。Stage2/3 的默认输入是：

```text
已选 Global Proposal Mask
+ Group-parent 共享 voxel/P/receptor 特征
+ 候选自己的 voxel/receptor membership indices
+ BOX 级共享的全部 P token
```

Selected-final 精修关闭时不得缺少任何 Stage2/3 必需字段。

### 12.2 固定原阈值重跑

若启用精修：

1. 以已选 Global Proposal 的体素质心裁 80³ BOX。
2. 允许 BOX 越出原图，并按 §6.2 的同一补零和坐标外推规则运行 Stage1 得到局部概率。
3. 使用该 Global Proposal 原来的 `threshold_rank` 与阈值，不搜索新阈值。
4. 若该阈值下产生多个局部连通组件，选择与投影进 BOX 的 Global Proposal Mask IoU 最大的组件；完全同分时接受连通组件实现普通 `argmax` 返回的结果，不增加额外裁决。
5. 同时保存 `proposal_mask` 与 `refined_mask`。

选择原阈值使精修保留候选的置信层语义；“寻找与旧 mask IoU 最大的阈值”会把精修退化为复制原形状，因此不作为默认。

### 12.3 失败和截断

必须记录：

- 原 Global Proposal 总体素数；
- 进入 `final BOX ∩ original density grid` 的体素数；
- `proposal_outside_observable_region_voxel_count`；按候选合法性不变量应为 0，非 0 必须记为契约错误而不是静默裁剪；
- `refine_status`，至少区分 `success`、`empty`、`no_overlap_component`；
- 直接记录 `source_route/source_materialization_run_id/source_materialization_box_id/tree_id/node_id`，由来源 materialization manifest 唯一解析 `proposal_run_id`，再由 proposal manifest 解析上级 `probability_run_id`；多阈值路线再直接记录 `CLG_run_id/CLG_id/candidate_index/selection_run_id`，F1 baseline 不伪造这些身份。

精修失败不得静默伪装成成功。下游可以显式回退使用原 Global Proposal。Selected-final BOX 使用与 Group-parent BOX 相同的完整 voxel/P/receptor/rank-map 契约，但它自己的特征不能默认与 Group-parent 的 Refined Mask 混用。

---

## §13 产物关系与 BOX 接缝

### 13.1 追溯链

多阈值路线的每个最终候选必须能沿 run manifest 与局部连接字段追溯：

```text
Stage1 checkpoint + full-map inference manifest
  → probability_run_id: full float32 probability asset
  → proposal_run_id: thresholds/component forest/node legality
  → component tree: tree_id/node_id
  → CLG_run_id: CLG enumeration config
  → CLG: CLG_id/group_parent_node_id
  → Group-parent materialization: materialization_run_id/box_id
  → selector_run_id: predicted_max_iou/selection_logit/CLG_logit/CLG_valid_probability
  → selection_run_id: CLG_gate_pass/selected_candidate_indices（门控未通过时为空）
  → optional refinement_run_id: selected-final box/refined mask
```

F1 baseline 走独立的直接分支：

```text
Stage1 checkpoint + full-map inference manifest
  → probability_run_id: full float32 probability asset
  → proposal_run_id: thresholds/component tree/F1 level
  → F1 component: tree_id/node_id
  → F1 baseline materialization: materialization_run_id/box_id
  → Stage2/3
  → optional refinement_run_id: selected-final box/refined mask（仍不创建 CLG/selector/selection）
```

它不创建占位 `CLG_id`、`selector_run_id` 或 `selection_run_id`。一个 `probability_run_id` 可以被多个 `proposal_run_id` 引用，一个 `proposal_run_id` 可以被多个 `CLG_run_id` 引用。`tree_id` 在 `(proposal_run_id,pdb_id)` 内唯一，`node_id` 在 `tree_id` 内唯一，`CLG_id` 在 `(CLG_run_id,pdb_id)` 内唯一，`candidate_index` 在 `CLG_id` 内连续；`box_id` 在 `(materialization_run_id,pdb_id)` 内唯一。所有这些整数只要求在已落盘产物内唯一并可 join，不承诺跨重跑相同，也不依赖它们进行同分裁决。

### 13.2 共享表原则

一个 CLG 的 Group-parent BOX 保存：

- Group-parent Mask voxel 表一份；
- P token 表一份；
- Group-parent pocket receptor 表一份；
- `threshold_rank_map[80,80,80]` 一份；
- `N` 个候选在 parent voxel 表和 receptor 表中的 `offsets + indices` membership；不同候选可以交叉，同一候选内部 indices 唯一，不要求额外稳定排序；
- 全部候选共享 BOX 内完整 P token 表，不保存 candidate-P membership；
- 候选树身份、阈值、LCA 距离、Global Proposal overlap 与 provenance。

旧契约中的 `blob_mask`、`blob_voxel_prob`、`blob_voxel_feat`、P/receptor 多尺度特征、pocket atom index、coverage、atom coverage、scores 与 prompt 都必须能从新字段直接取得或直接派生。详细字段见 `文档/讨论/BOX-level数据契约.md`。

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
  probability_artifact.py     # float32 正式概率产物与 probability manifest
  threshold_calibration.py
  component_forest.py
  CLG_enumerator.py
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
CLG: ...
materialization: ...
proposal_selector: ...
structured_selection: ...
selected_final_refinement: ...
density_context_modulator: ...
```

配置必须完整写入对应 run manifest；实现不得用隐式默认回退掩盖缺失配置。run ID 只需能定位这份不可变 manifest，不要求为此新增规范序列化或稳定哈希框架。

---

## §15 验证、消融与验收

### 15.1 单元不变量

- 阈值降低时组件 mask 只扩大；每个高阈值节点至多一个低阈值父节点。
- 组件森林固定 26-连通且不执行边缘 5 voxel 丢弃。
- 一个 CLG 只有一个 Group-parent Node。
- CLG 枚举只在 active 工作树上运行和删除；原始 proposal forest 始终只读。每次删除后，后续 CLG 不含已删除节点，也不跨过删除位置重连。
- 一次 split/merge 事件的姐妹要么全部加入，要么全部拒绝。
- 从工作树删除的可比较谱系不会再次产生 CLG。
- Group-parent Mask 包含每个候选 Global Proposal Mask。
- 居中 BOX 越出原图时保持起点不平移；exp/sim/GT mask 的图外区域严格为 0，BOX 世界原点由通过 parity 的同一 materializer 按该起点派生。
- 每个候选的 voxel/receptor membership indices 不越界且候选内唯一；允许不同候选交叉，不要求额外稳定排序。
- 所有候选读取相同的完整 P token 表，盘上不存在 candidate-P membership。
- F1 baseline 覆盖 F1 层全部合法 blob，且不产生 `CLG_id/selector_run_id/selection_run_id` 或 singleton candidate membership。
- `threshold_rank_map<=r` 能重建第 `r` 个局部阈值前景。
- 通过 CLG 门控后得到的非空反链不存在祖先—子孙对；门控未通过时正式结果为空集。
- 关闭 selected-final 后，Stage2/3 输入仍完整。

### 15.2 必须报告的统计

- 每个 $\alpha$ 的 micro/macro-$F_\alpha$、阈值和阈值重复映射。
- 每张图各层组件数、CLG 数、候选数、候选上限原子拒绝率、PDB cap 截断率。
- 节点因过小、过大或违反统一边界规则而被剪枝的数量，并按触碰 BOX 内部面、触碰原图边界面分别统计原因。
- 选择器 IoU 回归误差、CLG BCE/focal、precision/recall/F1/PR-AUC、反链 CE/focal、门控通过率与非空 MAP 反链准确率。
- `unet_c1` 与 Find 的完整图 ligand-area voxel PR-AUC，同时给出全体体素 micro 与逐 PDB macro；checkpoint 仍只由固定 validation 规则选择。
- 每个 producer（`unet_c1` / Find）都使用自己的 `P_global` 和由 calibration 100 为该 producer 选出的 `t_F1`，与该 PDB 全部 GT ligand-area 的并集计算 Dice，同时报告逐 PDB macro 与全体体素 micro；正式主路线另单列 Find。若另报候选路线 Dice，则使用该路线输出 mask 的并集。
- coverage F1 与 one-to-one F1 在 IoU 0.3/0.5 下的四个分量及平均值；one-to-one 只属于 evaluator，不反向改变 Stage1 independent-max oracle。
- top3/top4/top5 success ratio 在 IoU 0.3/0.5 下分别报告命中数、eligible PDB 数与比例。`eligible PDB` 固定为 `n_gt>0`；无预测记失败，实际取前 `min(K,n_pred)` 个，只要其中任一候选与任一 GT 的 IoU 达标即成功；`n_gt=0` 不进入正样本 top-K/macro，另报 FP/PDB。F1 baseline 按 `probability_mean` 排序，multi-threshold 在 selector 已选候选中按 `predicted_max_iou` 排序；`selection_logit` 只服务反链结构化选择，不冒充候选质量分。
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
6. 默认关闭的 `stopgrad(p_G)` 下游损失抑制开/关；不 detach 只作第二级消融。

树枚举消融：event depth 1 与 2。完整等变网络、PointNet++ 重建主干和 dense 80³ rank-map CNN 不进入第一轮。

### 15.4 实现完成标准

当以下条件同时满足，Stage1 多阈值推理才可交给 Stage2/3：

1. 基础 Stage1 在新数据上完成训练和完整图验证。
2. 组件森林、工作树 CLG 枚举和反链 DP 通过语义与不变量测试；不测试跨重跑编号或同分结果一致。
3. F1 baseline 与 Group-parent materialization 都能按 BOX 契约落盘并冷读。
4. selector 可以从落盘数据独立训练、推理和缓存分数。
5. 原始树 DP 的条件非空 log-partition、非空 MAP 和梯度已与小树穷举逐值一致；oracle 在 Dataset worker 中由 overlap 在线生成，不存在持久标签缓存。
6. 关闭 selected-final 与 density U-Net 时，多阈值路线可直接读取选中的 Global Proposal，F1 baseline 可直接读取原始 F1 blob。
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

## §17 仍需冻结的配置及集合职责

这些项目不是算法空白，但必须按集合职责分开，不能把 calibration 当成第二个 validation。

**由 validation 500 选择，或在第一轮实验前直接冻结的训练/架构项**：

- `lambda_count=0.05` 与紧邻 `0.03` 消融的最终取舍，以及 `gamma_focal∈{0,2}`；
- selector 的 `d/heads/layers/dropout`；
- 默认 10 Å pocket 包络半径的邻近消融，以及候选 receptor membership 参数；
- density context modulator 的具体 U-Net 宽度、预训练任务与是否缓存。

这些项一旦决定，会改变训练目标、输入或模型参数；calibration 100 不得参与选择。

**只由 calibration 100 冻结的推理/后处理项**：

- `min_voxels` 的最终值与 `max_voxels`；
- `N_abs=300`、`N_multi=3` 和候选上限升档条件；
- threshold 扫描网格与各 `t_\alpha`；相同 micro-$F_\alpha$ 不设额外裁决；
- selector gate `tau_G`；
- selected-final 是否进入正式生产及其固定推理参数，取决于 2×2 消融结果。

这些值一旦用于正式 run，必须进入配置、manifest 和对应 run ID；不得只存在于脚本局部常量中。held-out test pool 不参与上述任何选择。
