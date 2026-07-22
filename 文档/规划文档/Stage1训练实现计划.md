# AdaLigand Stage1 训练实现计划

> **文档角色**：本文是 `Find_0`、`Find_1` 与 `unet_c1` 的训练实施主规格。它规定冻结数据准备、统一 Dataset/Collator、模型差异、监督、五套训练、BEST 选择、CPC 接缝与训练交付物。一个没有项目上下文的实现者应能仅凭本文、本文列出的上游契约和现有 Pocket_Plus 代码完成训练主线。
>
> **并列文档**：完整图推理、阈值标定、F1/CLG 居中推理和 selector 见 `文档/规划文档/Stage1训练与多阈值推理.md`；盘上字段与目录见 `文档/讨论/BOX-level数据契约.md`。上游资产的唯一事实来源是 `Data_Preprocessing/Ori_Data/README.md`。
>
> **低权重附录**：`文档/规划文档/Stage1实现细节手册.md` 只给代码落点、伪代码、测试和 AI 实施顺序。若与本文冲突，以本文为准。
>
> **治理边界**：本文是干净的当前规格，不记录方案演变。实现漂移必须先按 `AGENTS.md` 审计，不能用现有旧代码静默覆盖本文。

---

## 1. 目标、交付物与实现边界

正式模型名只允许：

```text
stage1_model_name ∈ {Find_0, Find_1, unet_c1}
```

本轮训练五套相互独立的模型阶段：

| 训练阶段 | 初始化 | 主要训练分支 | BEST 指标 |
|---|---|---|---|
| `unet_c1` | 从头 | voxel ligand + voxel auxiliary | validation total loss 最小 |
| `Find_0/CPC1` | 从头 | voxel ligand、voxel auxiliary、A、P | validation total loss 最小 |
| `Find_0/CPC2` | 自己的 CPC1 BEST | A、P；体素分支冻结 | validation total loss 最小 |
| `Find_1/CPC1` | 从头 | voxel ligand、voxel auxiliary、A、P | validation total loss 最小 |
| `Find_1/CPC2` | 自己的 CPC1 BEST | A、P；体素分支冻结 | validation total loss 最小 |

两个 Find 是同一科学主干的受体输入消融，除 §4 明确列出的 embed/scatter 差异外，必须共用数据、采样、损失、优化器、训练时长、验证清单和主干配置。两条 CPC 链互不交叉：`Find_0/CPC2` 只能从 `Find_0/CPC1` 初始化，`Find_1/CPC2` 同理。`unet_c1` 从头独立训练。

本轮实现采用 Pocket_Plus 的 AdaLigand 专用 Git 分支。生产入口只保留当前项目需要的 Dataset、训练和推理链；在等价性证据和回归测试齐备后，可以删除被新链取代的旧 Dataset、旧推理入口及其纯编排代码。不得因本项目配置不启用某能力而删除或重构通用 model/wrapper 能力，尤其不得删除 CPC、sparse-refine、ranking、相应 loss/调度和承载它们的通用配置。五套 AdaLigand 配置只是不实例化这些当前无用模块。

训练完成必须交付：

1. 三个模型各自可解析的完整 Hydra 配置；两个 Find 各含 CPC1/CPC2。
2. 每个阶段的 `BEST.ckpt` 与同目录 resolved config。
3. 固定 validation 清单上的主指标与诊断指标。
4. 可由正式推理加载器严格恢复的完整 wrapper checkpoint。
5. `forward_voxel_probability(batch)` 和完整 forward 的等价性测试，为完整图推理交接。

---

## 2. 冻结数据准备

### 2.1 四项并列的数据工程

以下四项并列、显式且可独立验收，不得藏在训练循环或 `Dataset.__getitem__` 中；但不再建设单独的 Stage1 eligibility 工程、版本、入口或排除清单：

1. **主 split**：按 PDB 分组冻结 train/validation/calibration/held-out pool；挑选 validation 300 与 calibration 100 时直接要求完整图三轴均不小于 80。
2. **训练 BOX 池预计算与筛选**：对 train occurrence 解析真实 crop；只有无需补零且 shape 恰为 80³ 的记录进入冻结池。失败 pair/occurrence 不产生 BOX 记录，Dataset 不在取样时临时跳过或崩溃。
3. **固定 validation selection**：只从已经满足 80³ 条件的 validation PDB 生成，三个 producer 和五个训练阶段共用。
4. **held-out pool 去冗余**：论文严格测试前再做；当前只冻结其 split 身份，不检查小图、不去冗余，也不阻塞训练、calibration 或近期实验。

依赖顺序固定为：

```text
Stage G 最终 keep-list
  → 按 PDB 分组的主 split
  → validation/calibration 选择时检查三轴 ≥80
  → train BOX pool / validation selection

冻结 held-out pool
  → 以后单独去冗余并构造严格测试集
```

split、BOX pool 与 validation selection 分别保留自己的入口、冻结清单、输入身份和普通统计；没有额外 eligibility 目录。训练启动只读取已经成功预定位的 BOX 记录，不现场生成、补零、过滤或修补。

### 2.2 唯一主划分

以 PDB–EMDB pair 为基本条目，但 **PDB 身份是不可跨 split 的分组键**：同一 PDB 的全部 EMDB、occurrence、训练位置及后续推理产物必须属于同一 split。

从 Stage G 最终 keep-list 按 PDB 分组冻结：

| split | 数量 | 当前职责 |
|---|---:|---|
| train | `floor(0.75 × N)` | 三个 Stage1 producer、selector 及后续模型训练 |
| validation | 固定 300 | 选择各训练 run 的 BEST checkpoint |
| calibration | 固定 100 | 冻结完整图阈值和少量推理参数，并汇报校准集最优结果 |
| held-out pool | 其余全部 | 以后去冗余形成严格测试集；当前不作为完成门槛 |

split 在看见模型结果前一次冻结。validation 与 calibration 的候选必须先满足三轴均不小于 80；train 的可消费集合以后由冻结 BOX pool 中实际存在的记录确定。calibration 不参与 epoch/checkpoint 选择；validation 不选择完整图阈值；当前不把未去冗余 held-out pool 冒充测试集。

### 2.3 统一 80³ 起点解析

所有实际进入训练、验证、滑窗和居中生产的请求最终都调用同一个起点解析器。调用前必须已经知道完整网格三轴均不小于 80。完整网格形状为 `full_shape_zyx=(Lz,Ly,Lx)`，请求起点为 `requested_start_zyx`，BOX 边长固定 80：

$$
resolved\_start_a=
\operatorname{clamp}(requested\_start_a,0,L_a-80),
\qquad a\in\{z,y,x\}.
$$

因此所有已发布 crop 都是完整、真实的 80³ 网格，不做图外补零，不产生空间 `voxel_valid_mask`。validation/calibration 在 split 选择时保证这一前提；train 在 BOX pool 预计算时筛掉无法得到真实 80³ crop 的记录。向内平移后，原目标不必继续严格位于 BOX 中心。

数组轴统一为 ZYX；世界坐标统一为 XYZ Å。几何换算必须对标 Pocket_Plus 已有生产 helper：先复用、做 parity 测试；若发现 bug，报告并修正共同接口，不在 Ada Dataset 中另写补偿公式。

### 2.4 occurrence、bias 与 context 池

训练预定位池对上游实际产出的每个 occurrence 都生成记录；不按 ligand 类型、体素数或单 PDB occurrence 数过滤。训练池只保存来源身份和解析后的整数起点，不保存 80³ 数组。

每个 occurrence 的 center 起点：

1. 读取该 occurrence 的 schema v3 ligand-area 稀疏 mask。
2. 对 mask 的 ZYX voxel index 求均值。
3. 调用唯一整数中心 helper 得到 requested start。
4. 经 §2.3 解析为合法 `center_start_zyx`。

每个 occurrence 预生成 30 个 bias 起点。令 `K_occ` 为该 occurrence ligand-area mask 的体素数；重采样网格约为 1 Å，因此直接令

$$
R=\left(\frac{3K_{occ}}{4\pi}\right)^{1/3}.
$$

每个 bias 向量独立地按体积均匀分布采样于半径 `R` 的球内，加到 occurrence center 后调用起点解析器。不得按 ligand 再过滤，不做 jitter、重试或去重；clamp 后相同的起点仍保留为不同候选。

context 直接复用项目已有的一键生成逻辑：每个合法 context 必须包含至少 1000 个 core receptor heavy atoms。context 不绑定 occurrence。生成器耗尽尝试后保留实际得到的合法起点数，不因少于 3 个而使整个 PDB 或训练启动失败。

### 2.5 每个 epoch 的固定比例

训练时，每个 PDB 每 epoch 从其全部 occurrence 中无放回抽取最多 50 个；不足 50 全取，超过 50 时用显式 epoch/采样 seed 重抽，因此长尾 occurrence 可以跨 epoch 被看到。每个入选 occurrence 产生：

```text
center : bias : context = 1 : 5 : 3
```

- center 使用唯一 center 起点；
- bias 从 30 个预生成候选中选 5 个；
- context 从该 PDB context 池选 3 个；池中只有 1–2 个合法起点时有放回抽到 3 项，池为空时该 occurrence 只产生 center/bias，不伪造 context，也不让训练崩溃。因此 `1:5:3` 是存在至少一个合法 context 时的名义比例。

训练不再施加在线平移 jitter。只保留现有同步随机 90° 空间旋转，并同时作用于密度、受体坐标、hardmask 和全部 target；若一次奇数个 90° 转动交换了两个数组轴，`voxel_size_world` 的对应 XYZ 轴尺度也必须同步交换，随后重算 BOX 中心和 world/centered 坐标，不能假设三个 voxel size 严格相等。仅 train 启用。validation、calibration 和所有推理关闭旋转。

validation 同样每 PDB 最多 50 个 occurrence，但只在 `validation_selection` 生成时抽一次；三个模型与五个阶段共用同一清单，之后不 shuffle、不增强、不逐 epoch 重抽。

calibration 与 held-out pool 的完整图评估使用全部 GT occurrences，不应用训练/validation 的每 PDB 50 occurrence 上限。

---

## 3. 唯一 Dataset、Materializer 与 Collator

### 3.1 请求与共享处理链

训练、validation、完整图滑窗及三类居中推理共用一个 AdaLigand `Stage1Dataset` 和一个 `Stage1BatchCollator`。它们只替换请求提供者：

```text
ResolvedStage1Crop
  → 读取/复用整图资产
  → 按 resolved_start 裁 80³ 原始密度
  → 直接选择 core + 8 Å receptor 原子并保留全局索引
  → 构造 core receptor hardmask / voxel_label
  → 构造模型专属 density channels
  → 可选裁剪 ligand-area target
  → train-only 同步旋转
  → Stage1BatchCollator
```

同一模型 recipe 的训练、validation、完整图和居中推理必须逐步同构。不得保留一套“旧训练 Dataset”和另一套“旧推理切图入口”作为生产路径。

### 3.2 权威整图资产

字段名、路径和上游版本以 `Data_Preprocessing/Ori_Data/README.md` 为准。Stage1 至少读取：

| 逻辑资产 | 用途 |
|---|---|
| raw experimental density | 三个模型的实验密度来源 |
| raw simulated density | Find 的 56 路配方 |
| receptor coordinates + 49D features | Find 输入；三个模型的 auxiliary target 构造 |
| `binding_atom` | A target 与 `voxel_label` |
| schema v3 ligand-area union mask | voxel ligand target 与 P target |
| per-occurrence ligand-area mask | center、bias 与评估 |

49D 受体特征必须由完整受体预计算后按 `atom_global_indices` 切片；不得在 80³ BOX 内重算其中依赖邻域的特征。

### 3.3 receptor 的 8 Å加载、point buffer 与 core scatter

统一 Dataset/Collator 直接以 80³ core BOX 加 8 Å buffer 加载 receptor atoms，并保留：

- `atom_global_indices`；
- 世界 XYZ 与 BOX 局部坐标；
- `atom_is_in_core_box`；
- 以 BOX 中心为原点的世界坐标与连续局部 voxel 坐标。

两个 Find 共用同一个 point-side `Stage1EmbedHead`：无 trunk/voxel blocks，point blocks 的 buffer 半径依次为 `[8.0,4.0,0.0]`。Dataset 已经只加载 core+8 Å，所以不再建立 `atom_is_in_find_view`、10→8 Å二次筛选或额外 context 表。最终 A 学习特征只对应当前 BOX 内的 receptor atoms。

两个 Find 的 voxel scatter **始终只使用 core 原子**。这是 AdaLigand Find 的默认语义，不增加 `voxel_scatter_core_only` 开关。point 分支的 8 Å view 和 voxel scatter 的 core-only mask 是两个不同筛选，不能混用。

`unet_c1` 不把 receptor、hardmask 或 voxel_label 作为模型输入；Dataset 仍需利用 core receptor 和 `binding_atom` 构造 auxiliary 监督。hardmask 在 unet 中只限定 auxiliary loss 的有效 home voxel。

下游 centered A-pocket 不是 Dataset 的加载 buffer：它固定定义为“来源 blob 的 10 Å包络与当前 80³ BOX 的交集”。这个集合只从已加载表中的 core atoms 按几何关系选出；不读取 BOX 外原子。

### 3.4 密度通道

`unet_c1` 只读取一个通道：

```text
exp_clipnorm_nopost[1,80,80,80]
```

必须先按 resolved BOX 裁 raw experimental density，再对该 crop 执行现有 clip-normalize，不做任何空间后处理；不得读取 sim、diff、receptor mask 或 Find 学习特征。

两个 Find 使用最强的 56 维 `ALL` 配方。`ALL` 的权威顺序是以下三重循环的展开顺序：

```text
OPS   = [exp, sim, diff, posdiff]
NORMS = [nonorm, clipnorm]
POSTS = [nopost, gauss1, gauss2, DoG1, DoG2, smooth1, smooth2]

for op in OPS:
    for norm in NORMS:
        for post in POSTS:
            channel = f"{op}_{norm}_{post}"
```

运行时必须把 `ALL` 解析为按上述顺序排列的显式 56 个名称，并把该 resolved list 写入 resolved config；不得只靠字符串 `ALL` 猜测 checkpoint 的输入顺序。`diff/posdiff`、scale fit、smooth 和 clipnorm 均复用 Pocket_Plus `density_channel_builder` 的既有定义。

### 3.5 单样本与 batch 字段

三个模型共用的最小字段：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `pdb_id` | string | PDB 身份，不送入数值分支 |
| `box_start_zyx` | `[3] int32` | 已解析的整图起点 |
| `box_shape_zyx` | `[3] int64` | 固定 `[80,80,80]`，数组顺序 ZYX |
| `box_origin_world` | `[3] float32` | BOX 世界 XYZ 原点 |
| `voxel_size_world` | `[3] float32` | XYZ voxel size |
| `density_input` | `[C,80,80,80] float32` | C=56（Find）或 1（unet） |
| `hardmask` | `[80,80,80] bool` | core receptor 的唯一 home-voxel 集合；训练时限定 auxiliary loss，推理层还按并列计划遮蔽两个 Find 的 ligand probability |
| `ligand_area_target` | `[80,80,80] bool` | 仅 train/validation；直接裁 union mask |
| `voxel_label` | `[80,80,80] bool` | 仅 train/validation；binding core receptor home voxel 并集 |

Find 额外字段：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `atom_global_indices` | `[N_A] int64` | core+8 Å加载集合在整图 receptor 表中的索引 |
| `atom_feat` | `[N_A,49] float32` | 49D 基础特征 |
| `atom_coord_world` | `[N_A,3] float32` | 世界 XYZ |
| `atom_coord_local_voxel` | `[N_A,3] float32` | BOX 内连续 XYZ voxel 坐标 |
| `atom_coord_centered_world` | `[N_A,3] float32` | 以 BOX 物理中心为原点的 XYZ Å坐标 |
| `atom_is_in_core_box` | `[N_A] bool` | core-only scatter/监督 mask |
| `atom_label` | `[N_A] bool` | 仅 train/validation；binding label |

上游 `origin_xyz` 是完整网格物理下角点；索引为 `index_xyz` 的体素中心固定为

$$
origin_{xyz}+(index_{xyz}+0.5)\odot voxel\_size_{xyz}.
$$

令 `box_start_xyz=box_start_zyx[[2,1,0]]`、`box_shape_xyz=box_shape_zyx[[2,1,0]]`，则

$$
box\_origin\_world=origin_{xyz}+box\_start_{xyz}\odot voxel\_size_{xyz},
$$

$$
atom\_coord\_local\_voxel=
\frac{atom\_coord\_world-box\_origin\_world}{voxel\_size_{xyz}},
$$

$$
atom\_coord\_centered\_world=atom\_coord\_world-
\left(box\_origin\_world+\frac12 box\_shape_{xyz}\odot voxel\_size_{xyz}\right).
$$

这些字段必须调用通过 parity 的现有 helper 产生，公式用于定义与测试，不授权在 Dataset 另写数值分支。Collator 堆叠 dense voxel 字段；变长原子表按拼接后的 `atom_batch_index[N_A_total]`、`atom_offsets[B+1]` 和 `atom_counts[B]` 组织，不 pad 到固定原子数。推理时不伪造全零 targets。

---

## 4. 三个 producer 的精确模型配置

### 4.1 共同主干

三个 producer 均使用 Pocket_Plus 当前 RAUNet64 voxel backbone，启用 voxel ligand head 与 voxel auxiliary head；训练时随机 1–3 次 recycle，validation/calibration/推理固定 3 次，跨 recycle state detach。

两个 Find 还共用同一个 point-side `Stage1EmbedHead` 和 point backbone。配置固定为无 trunk block、无 voxel block、三个 point blocks，buffer 依次裁为 8 Å、4 Å、0 Å；共享 atom MLP 为 `49→128→128`，最终 point value 投影为 64D 并加 `Linear(49→64)` raw residual。两个 Find 都能导出 A_feat_L1–L4；下游另以 `atom_global_indices/A_global_index` 从每 PDB 唯一 receptor 表读取 raw49，作为 `A_feat_L0 float32`，不在每个 BOX 重复保存。两个 Find 的科学差异只在 voxel 分支进入 RAUNet 前的 receptor grid 构造。

所有 ligand/auxiliary 输出头前的额外 3×3 Conv3d block 数固定为 0：

```yaml
num_conv3d_ligand: 0
num_conv3d_aux: 0
```

两个 head 均由最终 voxel feature 直接接各自 1×1 输出层。这里删除的是当前配置中的额外输出前卷积，不删除通用 head 代码。

### 4.2 Find_0：raw49 voxel hard scatter

`Find_0` 保留 §4.1 的共同 point-side `Stage1EmbedHead`，因此能导出与 Find_1 同类的 A_feat_L1–L4。它只在 voxel 分支采用最简单的 raw49 基线：

- core receptor 按原子局部连续坐标 floor 到唯一 home voxel；
- 同 voxel 采用 sum，得到 49D raw receptor grid；
- 不使用 MLP、residual、occupancy、centroid encoding 或 soft splat；
- voxel backbone 输入为 56D density + 49D receptor = **105 channels**。

验收标准是 point 分支确实运行共同的 `[8,4,0]` blocks，而 voxel 分支不消费 point-side learned embedding，hard floor/sum scatter 的 value 恰为 raw49。

### 4.3 Find_1：无 Transformer 的非块式 embed/scatter

`Find_1` 新建 AdaLigand 配置，复用现有 `Stage1EmbedHead` 的代码结构和已实现的相对/centroid、residual、soft scatter 算子，但不复用某个旧实验配置的科学取值。

禁止 trunk/voxel Transformer block；point 分支保留已经验证更好的 buffer blocks：

```yaml
num_trunk_blocks: 0
num_voxel_blocks: 0
num_point_blocks: 3
trunk_buffer_radii: []
voxel_buffer_radii: []
point_buffer_radii: [8.0, 4.0, 0.0]
```

Dataset 直接加载 core+8 Å；point blocks 按上述半径逐层裁剪。voxel 分支在任何 Transformer 前完成的非块式编码固定为：

1. 共享 atom MLP：`h=MLP(49 → 128 → 128)`。
2. voxel value：把 `h` 与既有 6D relative/centroid encoding 送入 voxel projection 得到 49D；与 raw 49D identity residual 相加，residual gate 固定为 1。
3. 只对 core atoms 做三线性 soft splat，聚合为 sum；追加现有 2D occupancy，得到 51D receptor voxel grid。
4. point value 与共同 point branch 完全遵守 §4.1，不构成 Find_1 独有差异。
5. voxel backbone 输入为 56D density + 51D receptor = **107 channels**；point backbone 输入为 64D。

residual、occupancy、centroid encoding、MLP 和 soft splat 可用于 voxel 前处理；trunk/voxel Transformer 明确不允许。point Transformer 只限共同的 `[8,4,0]` 三层。`Stage1EmbedHead` 必须以最小修改支持 voxel block 数为 0 时仍执行既有非块式 voxel 投影，不另造第二个 embed subsystem。

### 4.4 unet_c1

`unet_c1`：

- voxel backbone 输入恰为 `[B,1,80,80,80] exp_clipnorm_nopost`；
- 不构造 point backbone、embed head、A/P head、fusion、sim/diff/receptor 输入；
- voxel ligand 与 voxel auxiliary 两个 head 都启用；
- auxiliary head 读取 RAUNet feature，但其 target/validity 来自 `voxel_label/hardmask`；这些张量不拼进模型输入；
- 从头训练，不从 Find 或旧 unet checkpoint 初始化。

### 4.5 两个 Find 的 CPC 冻结边界

两个 Find 使用完全相同的现有 CPC 两阶段语义：

- **CPC1**：从头训练 embed/scatter、voxel/point trunk 及当前 A/P 最终分类路径；real/P interaction cross-attention 保持现有 stage1 冻结/排除状态。当前配置不实例化 sparse-refine。
- **CPC2**：从自己的 CPC1 BEST model-only 初始化；冻结 embed/scatter 与 voxel ligand/auxiliary 路径，使第一次更新前及后续训练中的 voxel 分支保持 CPC1 结果；训练现有 stage2 允许的 real/P interaction 与 A/P 尾部。

优先直接复用 Pocket_Plus `frozen_module=stage1/stage2` 的成熟参数分组，并用可训练参数清单测试确认上述科学边界；不要为 AdaLigand 另写一套冻结状态机。

---

## 5. 监督与 loss

### 5.1 唯一 target 来源

- `L_voxel_ligand`：直接使用 schema v3 ligand-area union mask 的 80³ 二值 crop。
- `L_P`：按 P token 的 home voxel 从同一 `ligand_area_target` 取样。
- `L_atom`：按 `atom_global_indices` 读取 `binding_atom`；只对实际 Find model view 中相应的 A 输出监督。
- `L_voxel_aux`：target 为 `voxel_label`，只在 `hardmask` 指定的唯一 receptor home voxels 上计算；Find 与 unet_c1 相同。

不得再生成或读取 `ligand_dist_map`，不得用 1.7 Å 阈值派生 ligand target。训练 loss 与 target 不乘 hardmask；推理层必须按并列计划对 Find 的 sigmoid ligand probability 使用 hardmask，unet 不使用该遮蔽。

### 5.2 分类损失

所有启用的四类监督统一使用：

$$
L_{cls}=0.7L_{focal}+0.3L_{Tversky}.
$$

参数固定为：

```yaml
focal_gamma: 2.0
focal_alpha_neg: 0.5
focal_alpha_pos: 0.5
tversky_alpha: 0.5
tversky_beta: 0.5
tversky_smooth: 1.0
w_focal: 0.7
w_tversky: 0.3
w_mse: 0.0
hard_label_threshold: null
```

### 5.3 各阶段总损失

$$
L_{unet\_c1}=L_{voxel\_ligand}+0.1L_{voxel\_aux}.
$$

$$
L_{Find\ CPC1}=L_{atom}+0.1L_{voxel\_aux}
+L_{voxel\_ligand}+0.1L_P.
$$

$$
L_{Find\ CPC2}=L_{atom}+0.1L_P.
$$

CPC2 中冻结 voxel ligand/auxiliary 分支的 loss 可以继续计算并记录为诊断，但不得进入 total loss。AdaLigand 五套配置不实例化 sparse-refine head、sparse-refine loss、ranking loss 或相应权重调度；这不授权删除它们的通用实现。

---

## 6. 统一训练制度

### 6.1 优化器、精度与验证频率

| 项目 | 固定值 |
|---|---|
| precision | `bf16-mixed` |
| optimizer | AdamW |
| learning rate | `3e-5` |
| weight decay | `0.01` |
| gradient clip | `0.5` |
| max epochs | `20` |
| full validation loops | `val_per_epoch=10`，即每 epoch 10 次 |
| batch-size auto tuning | 关闭 |

### 6.2 有效 global batch

两个 Find 必须使用相同物理 batch 和相同有效 global batch。先在实际硬件、实际 80³ 输入上做稳定性 preflight：

- 若 `Find_0` 与 `Find_1` 都能稳定使用 per-device batch 8，则统一 `global_batch_size=64`；
- 若任一模型只能稳定使用 per-device batch 6，则两个 Find 都使用 6，并统一 `global_batch_size=66`。

`unet_c1` 也凑到同一个 64 或 66。优先直接使用 64/66；否则选择该 global batch 的最大稳定因子作为物理 batch，以整数 gradient accumulation 补足。所有值显式写入配置，不启用运行时自动 batch 搜索。

### 6.3 warmup、plateau 与停止

| 阶段 | warmup | plateau patience | 停止条件 |
|---|---|---:|---|
| `unet_c1` | ratio `0.025`，start factor `0.33` | 3 | 第 3 次实际 LR reduction 后停止 |
| 两个 CPC1 | ratio `0.025`，start factor `0.33` | 3 | 第 3 次实际 LR reduction 后停止 |
| 两个 CPC2 | `warmup_steps=0`，factor `1.0` | 1 | 第 1 次实际 LR reduction 后停止 |

所有阶段的 `ReduceLROnPlateau`：

```yaml
factor: 0.3
threshold: 0.001
threshold_mode: abs
cooldown: 0
```

达到 `max_epochs=20` 也结束。patience 作用于各阶段自己的 monitor；“实际 LR reduction 次数”不把 warmup 结束计作一次 reduction。

### 6.4 BEST 与 validation 职责

五个训练阶段都最小化自己训练公式对应的 `validation total loss` 选择 BEST；CPC2 的 total loss 只包含其实际训练的 A/P 项，冻结 voxel 项即使记录为诊断也不进入 monitor。voxel ligand AP、voxel auxiliary AP、A/P AP、Dice、各分项 loss 和运行诊断必须同时报告，但不拼成另一个 BEST 分数。

固定 validation 只选择 checkpoint及比较同类训练/Selector 方案；calibration 100 只在 checkpoint 冻结后选择完整图阈值或 Selector `tau_G` 并汇报 calibration-fitted 结果，不能反向选择 epoch、checkpoint 或模型方案。

---

## 7. CPC、checkpoint 与正式加载

### 7.1 CPC1 → CPC2

CPC2 保持 Pocket_Plus 现有 model-only 初始化语义：严格加载同名 CPC1 BEST 的 model `state_dict`，不恢复 optimizer、scheduler、epoch 或 global step。现有 wrapper 已通过 `on_save_checkpoint/on_load_checkpoint` 保存和恢复自适应 P 候选状态 `p_best_by_class/p_sampling_by_class`。

唯一必要修补是：现有 `_load_model_only_checkpoint` 在 `state_dict` 加载完成后，调用现有 `model.on_load_checkpoint(checkpoint)`。不得围绕这两个字段新建公共 helper、状态层、registry 或重复校验框架。

为每条 CPC 链写普通模拟测试：CPC2 第一次参数更新前，其全部输出、P 候选阈值及 runtime 状态应与来源同名 CPC1 BEST 一致。它与其它 `test_*.py` 等地位，不是训练前的特殊人工 gate。

### 7.2 正式推理加载器

不得复用旧 `get_pred.load_model` 的裸 backbone 加载路径。AdaLigand 正式推理加载器必须：

1. 接收调用者选定的 checkpoint；
2. 读取其相邻 resolved config；
3. 实例化完整 Stage1 wrapper；
4. strict 加载完整 `state_dict`；
5. 走标准 `on_load_checkpoint` 生命周期；
6. 统一支持三个 `stage1_model_name`。

不为 checkpoint 额外计算 hash，不复制路径到每个输出，不另建 checkpoint registry。调用入口选中的 checkpoint 就是该次运行身份。

### 7.3 完整图 voxel-only 入口

三个模型新增公共入口：

```text
forward_voxel_probability(batch) → voxel_logits_ligand
```

它复现与完整 forward 相同的最短 voxel 构造和固定 3 次 recycle，但不抽取共享 `_forward_voxel_branch`、不重构现有训练 forward。`unet_c1` 只运行 density→voxel backbone；`Find_0` 直接运行 raw49 core hard scatter；`Find_1` 只运行 voxel MLP/centroid/residual/soft-splat。两个 Find 都跳过 `[8,4,0]` point blocks、P candidates、point backbone、A/P heads 和 sparse-refine，也不导出居中特征。当前模型不存在 A/P 后半段回写 voxel 分支的路径，因此该入口必须与完整 forward 的 `voxel_logits_ligand` 逐元素等价，而不是近似模型。

`F1_centered`、`CLG_centered` 和 `Selected_Refined_Centered` 仍走完整 forward。代码落点与伪代码见低权重手册。

---

## 8. 实现与放行标准

正式训练前必须通过以下检查；这些检查验证实现，不创造新的科学配置：

1. **几何 parity**：同一 `pdb_id + resolved_start` 在 AdaLigand 与 Pocket_Plus helper 下得到相同 BOX 原点、voxel centers、局部 receptor 坐标和 crop。
2. **边界筛选**：validation/calibration 选择时排除任一轴 `<80` 的候选；train 只物化真实 80³ BOX，正式 Dataset 不临时 skip 或崩溃，且不存在独立 eligibility 目录。
3. **统一路径**：四种请求 provider 经过同一个 materializer/collator；推理不构造 fake target。
4. **8 Å/core 两层 receptor**：Dataset 直接加载 core+8 Å，point blocks 为 `[8,4,0]`，voxel scatter 仅 core；全局索引不丢失。
5. **Find_0**：共同 point embed 生效；voxel 仅 hard floor/sum raw49，voxel input 105D，point input 64D。
6. **Find_1**：trunk/voxel block 为 0、point blocks 为 `[8,4,0]`，voxel 非块式 MLP/residual/centroid/soft-splat 生效，voxel input 107D，point input 64D。
7. **unet_c1**：模型数值输入只有单通道 experimental density；auxiliary target 不被拼入输入。
8. **target 与 loss**：union mask、P home voxel、binding atom、hardmask 限定 auxiliary 四条路径逐项正确；没有 `ligand_dist_map` 依赖。
9. **增强**：90° 旋转同步作用于所有几何/target；validation 与推理确定性。
10. **batch/调度**：两个 Find 的 global batch 相同，unet 对齐；warmup/plateau/停止次数与 §6 一致。
11. **CPC 恢复**：同名 CPC1→CPC2 第一次更新前输出与候选状态一致。
12. **voxel-only 等价**：eval、固定 3 recycle 下，专用入口与完整 forward 的 ligand voxel logits 逐元素一致。

通过后即具备并行启动 `Find_0/CPC1`、`Find_1/CPC1` 与 `unet_c1` 的条件；实际正式提交必须由用户另行授权。每个 Find 的 CPC2 只等待自己的 CPC1 BEST，无需等待另一个 Find 或 unet。三者 BEST 冻结后，按 `Stage1训练与多阈值推理.md` 对 calibration 100 进行完整图推理、阈值标定与指标汇报。

---

## 9. 第一版禁止项

- 不把 validation 300 改成 calibration 或 test，也不让 calibration 反选 checkpoint。
- 不在训练循环中现场划 split、生成 BOX 池、过滤小图或修 target；也不新建独立 eligibility 工程。
- 不引入在线平移 jitter、图外 padding、空间 `voxel_valid_mask` 或候选相关训练样本。
- 不让 Find_1 的 voxel 前处理出现 Transformer block；共同 point branch 只使用 `[8,4,0]` 三层。
- 不让 `unet_c1` 读取 sim/diff/receptor 特征，也不取消其真实 auxiliary head。
- 不让 Find voxel scatter 看见 buffer 原子；Dataset 不加载额外 8–10 Å receptor context。
- 不用旧 checkpoint/旧推理基础设施决定新契约；也不删除通用模型和 wrapper 能力。
- 不自动搜索 global batch、loss 权重、max epoch 或 BEST 综合分。
- 不把 held-out pool 的当前结果称为严格测试结果。
