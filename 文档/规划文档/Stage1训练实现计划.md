# AdaLigand Stage1 训练实现计划

> **文档角色**：本文把 Stage1 的两个基础预测器——纯密度基线 `unet_c1` 与密度+受体联合网络 `Find`——落实到可以直接实施和启动全量训练的数据路径。它规定数据划分、训练预定位池、统一 Dataset/DataLoader、Pocket_Plus 适配、CPC1/CPC2、checkpoint 选择、启动门禁与运行目录。多阈值组件树、候选谱系组、selector、首次局部物化和 selected-final 的科学设计由并列计划负责，本文只交付它们所需的正式 checkpoint 与统一 forward 接口。
>
> **上游与并列契约**：
>
> - 整图资产与 GT 来源：文档/规划文档/数据处理_v2.md。
> - BOX 几何字段与存储边界：文档/讨论/BOX-level数据契约.md。
> - Stage1 训练目标、整图推理和后续候选链：文档/规划文档/Stage1训练与多阈值推理.md。
> - 原始密度通道构造约定：Data_Preprocessing/Ori_Data/code/readme.md。
>
> **状态**：这是经审阅后的当前实施规格。实现 agent 应以本文补充并细化现有 Stage1 总计划，不得用本文删除或替换其中已经确认的 selector、addon、selected-final 等设计。

---

## 1. 范围、目标与硬边界

本轮要训练两个模型：

| 名称 | 输入 | 角色 |
|---|---|---|
| `unet_c1` | 仅一个原始实验密度通道 `exp_clipnorm_nopost` | 纯密度基线；不读取受体、sim、diff 或任何间接受体通道。 |
| `Find` | Pocket_Plus 当前成熟的密度+受体点—体素联合输入 | 正式 Stage1 网络；保留当前成熟主干、P token 与 real/P 交互，只适配新数据和二值标签。 |

训练后，二者都必须在每个 80³ BOX 上输出 ligand-area 的 voxel 级预测；`Find` 还保留当前 Pocket_Plus 的受体原子与 P 分支输出。本文不凭空新增“纯受体 Find”档。

`Find` 的正式训练分两阶段：

1. **CPC1**：从头训练主干及既有 ligand-area、受体原子、P 输出路径；排除 real/P cross-attention，并关闭已取消的 sparse-refine 第三阶段与最终 refine head。
2. **CPC2**：从 CPC1 `BEST.ckpt` 初始化，只训练当前 Pocket_Plus stage2 冻结配置允许的 cross-attention 与 real/P 尾部；CPC1 的 ligand-area 路径必须保持不变。

第一版直接使用质量过滤后的完整 train split 训练正式模型。单 batch、几何、Dataset parity 和 CPC2 保真测试只负责证明代码正确，不得改称 pilot、tiny run、center-only 阶段或“小集过拟合后再决定是否全量”。

基础训练样本只需要轻量预定位记录，加上按该位置从整图资产现场切出的原始输入与训练期标签。它**不读取**候选谱系组、Global Proposal、选择器分数、Group-parent addon 或 selected-final 产物。后者仍属于 Stage1 推理链，不能因为基础训练不读取就从总计划或 BOX 契约删除。

下列原则冻结为本计划的实现边界：

- `center`、`bias`、`context` 是基础训练预定位池的三个来源；它们不是正/负类别，也不进入 loss。全图滑窗与 `CLG_group_parent`、`f1_baseline`、`selected_final` 等推理物化请求属于另一套体系，不混进基础训练池。
- 训练与推理使用同一个 Stage1BoxDataset、同一个 Stage1BatchCollator、同一个密度通道构造器和同一个受体裁剪器。两者只在“BOX 请求从哪里来”和“是否附带 GT”上不同。
- P 是 Stage1 模型内部生成的 pseudo-atom token，不是 Stage1 Dataset 需要保存或加载的复杂 BOX 字段。
- 训练期不为了适配下游而保存 Stage1 中间特征；全图推理期中间特征的物化属于另一个计划。
- 固定 80³ 的普通训练 BOX 不引入 voxel_valid_mask。
- Pocket_Plus 的模型结构、优化器、调度器和冻结语义是成熟基线；AdaLigand 只改新 Dataset/DataLoader、动态裁剪、二值 ligand-area target、必要的 wrapper 接口与新 experiment 配置，非必要不改其它科学逻辑。

---

## 2. 术语、坐标与最小输入契约

### 2.1 坐标约定

- 网格数组空间轴恒为 ZYX，密度与 voxel 标签形状均为 [D, H, W]。
- 世界坐标恒为 XYZ，单位为 Å。
- 第一个 Stage1 版本固定 BOX 形状为 `[80,80,80]`。任何组件不得私自改变轴顺序或把 XYZ 当成 ZYX。
- 当前审计确认双方坐标主语义为：数组 ZYX、世界量 XYZ、origin 为网格下角点、voxel center 使用 `origin + (index + 0.5) * voxel_size`。实现仍不得在 Dataset 中手写第二套换算；世界坐标、完整图 voxel center、BOX 起点和局部坐标必须调用同一个 materializer/几何 helper。
- 正式训练前必须用真实 `exp.npz`、`receptor_tokens.npz`、schema v3 `ligand_area.npz` 完成 Stage1 materializer 的跨项目 BOX parity。比较的是：**给定同一个 `box_start_zyx` 后**，双方的 voxel center、BOX 与整图相交区域、受体局部坐标和直接裁出的 Ada v3 target；不要求 Pocket 以另一套统一距离阈值重新生成出相同 GT mask，也不要求新 Ada 的起点生成/两侧补零复刻旧 Pocket 的 center floor+clamp 或只在高侧 padding 的采样策略。Ada mixed-axis wrapper 的已登记兼容分支与双方共享的祖传 padding 轴风险必须作为已知边界记录，不能把审计简写成“所有实现无例外完全相同”。若给定同一起点后同一体素或原子在两边得到不同局部坐标，阻断训练并修接口，不能再加一层补偿。
- Stage1 materializer 不得调用语义错误且当前未使用的 `mrc.py::grid_world_bounds`；物理边界与局部坐标只取当前生产路径已验证的 helper。

### 2.2 盘上分家，运行时汇合

基础训练预定位池与推理物化产物用途不同，盘上不再强行共用一个带 `box_type` 的宽表：

- 训练池只保存 center/bias/context 的 occurrence 引用与 `box_start_zyx`；
- 全图滑窗由 map shape、window shape 与 stride 在线枚举；
- Group-parent、F1 baseline 和 selected-final 继续按 BOX 契约的推理/addon 体系保存。

三者在进入 Dataset 后都解析为同一个轻量运行时请求：

| 字段 | 类型/形状 | 来源与意义 |
|---|---|---|
| pdb_id | str | 整图资产的唯一键。 |
| box_start_zyx | int32[3] | BOX 在完整网格的整数起点。 |
| shape_zyx | uint16[3] | 第一版恒为 [80,80,80]。 |
| require_targets | bool | 训练/验证为 True，正式整图推理为 False；不属于盘上 BOX schema。 |
| source_kind | enum | `train_center/train_bias/train_context/full_map_window/materialized_box`；仅追溯，不送入模型。 |
| source_key | typed tuple | 与 BOX 契约一致：训练引用 pool 下标，滑窗引用 `(probability_run_id,window_index)`，物化引用 `(materialization_run_id,box_id)`。 |

完整图 `origin_xyz`、`voxel_size_xyz` 与局部 BOX 世界原点由 materializer 从权威整图几何派生，不在每条训练记录重复保存。训练样本的密度、受体和标签一律按 `pdb_id + box_start_zyx` 从整图资产解析。

### 2.3 需要解析的整图资产

| 资产 | 解码后形状 | Stage1 用途 |
|---|---|---|
| `density/{pdb_id}/exp.npz` | [1,D,H,W] float32 | 两个模型都读取；`unet_c1` 只从它构造 `exp_clipnorm_nopost`。 |
| `density/{pdb_id}/sim.npz` | [1,D,H,W] float32 | 只有联合 Find 的当前 Pocket_Plus 密度配方需要时才读取；`unet_c1` 禁止读取。 |
| 受体世界坐标 | [num_receptor_atoms,3] float32 | 按 BOX + buffer 选取受体原子，并构造局部坐标。 |
| 受体基础特征 | [num_receptor_atoms,49] float32 | Stage1 点分支的受体输入。 |
| `density/{pdb_id}/ligand_area.npz` | union + occurrence 稀疏 mask | `require_targets=True` 时直接裁成二值 voxel 监督；使用修复后的 schema v3 压缩产物。 |
| `labels/{pdb_id}/atom_labels.npz::binding_atom` | [num_receptor_atoms] bool | Find 训练时按选中的受体原子取监督。 |
| `labels/{pdb_id}/atom_labels.npz::instance_id` | [num_receptor_atoms] int32 | 诊断/后续兼容标签；基础 Find 不新增独立训练头。 |

资产字段的唯一权威仍是 `Data_Preprocessing/Ori_Data/code/readme.md`。密度通道、受体局部索引和训练标签都是现场派生量，不写进基础训练预定位记录。

---

## 3. 单样本输出：训练和推理同构

Stage1BoxDataset 的每次 __getitem__ 都先生成同一份输入字段；训练/验证仅额外附带 targets。禁止训练路径读取“预切 BOX 文件”而推理路径另写一套切图逻辑。

### 3.1 通用输入字段

| 字段 | 形状与 dtype | 含义 |
|---|---|---|
| voxel_grid | [num_density_channels,80,80,80] float32 | 由同一个 density_channel_builder 现场构造的密度输入。 |
| box_start_zyx | [3] int32 | 追溯与整图概率回写用的局部起点。 |
| box_origin_world | [3] float32 | 当前 BOX 左下近角点的 XYZ 世界坐标；沿用 Pocket_Plus 现有键名。 |
| voxel_size_world | [3] float32 | 当前图的实际 XYZ voxel size；沿用 Pocket_Plus 现有键名。 |
| atom_global_indices | [num_box_receptor_atoms] int64 | 所选受体原子在该 PDB 整图受体表中的索引。 |
| atom_coord_world | [num_box_receptor_atoms,3] float32 | 所选受体原子的 XYZ 世界坐标。 |
| atom_coord_local_voxel | [num_box_receptor_atoms,3] float32 | 相对 BOX 左下近角点的连续 XYZ voxel 坐标。 |
| atom_coord_centered_world | [num_box_receptor_atoms,3] float32 | 相对 BOX 几何中心的 XYZ 世界坐标。 |
| atom_feat | [num_box_receptor_atoms,49] float32 | 从整图 49 维受体表切出的基础特征。 |
| atom_is_in_core_box | [num_box_receptor_atoms] bool | 原子是否落在 80³ core；buffer 原子可作上下文但不重复计入核心指标。 |
| hardmask | [80,80,80] int64/bool | 仅 Find：沿用 Pocket_Plus `build_hardmask_from_atom_coordinates`，把全部 core receptor 原子的 home voxel 置 1。它是 receptor occupancy/geometry，不是 padding `voxel_valid_mask`。 |
| pdb_id | str | 当前完整图身份；不送入模型数值分支。 |
| source_kind | enum | 与 §2.2/BOX 契约相同的五值枚举；不送入模型。 |
| source_key | typed tuple | 与 `source_kind` 对应的固定字段组合；不使用自由字典。 |
| request_version | uint16 标量 | runtime 请求契约版本。 |

受体原子选择规则固定为：先以 BOX 世界范围加 atom_buffer_radius 查询整图受体，再保留其全局索引。所有模式用同一个查询器；不得训练时按 GT 选原子、推理时按几何选原子。

### 3.2 训练与验证附带的监督字段

当 require_targets=True 时，Dataset 额外返回：

| 字段 | 形状与 dtype | 构造规则 |
|---|---|---|
| ligand_area_target | [80,80,80] bool | 直接裁剪 schema v3 `ligand_area.npz` 的 union mask；空 crop 合法，全部为 False。 |
| atom_label | [num_box_receptor_atoms] bool | 由 `atom_global_indices` 从整图 `binding_atom` 取值；沿用当前 atom 分支监督键。 |
| voxel_label | [80,80,80] int64/bool | 仅 Find 的既有 voxel auxiliary target：只把 core receptor 中 `atom_label=True` 的 home voxel 置 1；同 voxel 多原子时按“任一为正即为正”。不得用 ligand-area mask 代替。 |
| atom_instance_target | [num_box_receptor_atoms] int32 | 由整图 instance_id 取值；第一版只作可视化与一致性检查。 |
| target_available | bool 标量 | 恒为 True，用于统一 collate 的显式断言。 |

当 require_targets=False 时，上述五个监督字段均不构造；新 Ada collator 必须允许 target 字段缺省，不能为推理伪造全零标签。`hardmask` 是 Find 输入/几何字段，仍按真实 receptor 构造。模型输入字段、密度通道、受体筛选和坐标变换保持相同。

### 3.3 模型输出与最小 loss 接口

训练包装层将现有 Pocket_Plus 输出适配成具名语义：

| 输出 | 形状 | 监督 |
|---|---|---|
| `ligand_area_logit` | [batch_size,1,80,80,80] | 两个模型都有；对 `ligand_area_target` 计算现有 voxel 主损失。 |
| `receptor_binding_logit` | [num_batch_receptor_atoms] 或等价带 batch 索引表示 | 仅 Find；沿用当前 atom 分支并由 `atom_label` 监督。 |
| `voxel_receptor_logit` | [batch_size,1,80,80,80] 或当前等价表示 | 仅 Find；沿用当前 `voxel_logits_aux` 分支，由 `voxel_label` 监督并用 `hardmask` 限制有效 receptor home voxels。 |
| `P_ligand_logit` | [num_batch_P_tokens] 或当前等价表示 | 仅 Find；P token 在模型内部生成，监督由同一二值 `ligand_area_target` 按 P 所在 voxel 采样。 |

`unet_c1` 只保留当前 `configs/loss/unet.yaml` 的 voxel ligand loss。Find 沿用当前 CPC1/CPC2 中确实启用的 atom、voxel auxiliary、voxel ligand 与 P loss 及其权重；取消的 sparse-refine 最终分支及其 loss 必须显式关闭，不得仅靠“参数被冻结”却继续让该 loss 反传到主干。

AdaLigand 的标签已经是二值 ligand-area，不再伪造 `ligand_dist_map`。适配必须同时改通三处消费者：

1. dense voxel ligand loss 直接读取 `ligand_area_target`；
2. validation 的 `voxel_ligand_PRAUC` 直接读取同一 target；
3. Find 的 P 监督从同一 target 按 `pseudo_voxel_zyx + pseudo_batch_index` 取值。

相应 loss 配置将 `hard_label_threshold` 设为 `null`，并把 target 显式传入现有 loss；`1.7 Å` distance threshold 不再参与 AdaLigand 训练。不得只改 YAML 而留下 wrapper 对 `batch['ligand_dist_map']` 的硬依赖。

`voxel_label/hardmask` 不属于上述 distance-target 适配：它们继续服务当前 CPC 的 receptor voxel auxiliary。二者都从整图 receptor 与 `binding_atom` 现场派生，不新增盘上 BOX 标签，也不把 `hardmask` 乘到 ligand-area 概率或整图融合结果上。

---

## 4. 一个 Dataset、一个 DataLoader 路径

### 4.1 四个可替换的请求提供者

Dataset 不关心 BOX 是如何产生的，只消费 `ResolvedStage1Crop`。请求提供者可替换：

| 运行用途 | 请求提供者 | require_targets |
|---|---|---:|
| 训练 | 从训练预定位池按本计划冻结的 `1:5:3` 规则产生 center/bias/context 请求 | True |
| 验证 | 冻结且无增强、不逐 epoch 重抽的 `1:5:3` 请求清单 | True |
| 整图推理 | 由完整图 shape、window shape、stride 生成的滑窗请求列表 | False |
| 局部推理物化 | 从 2B 以 `(materialization_run_id,box_id)` 读取 Group-parent、F1 baseline 或 selected-final 请求 | False |

正式整图推理的滑窗请求可以是内存临时对象，不必写入训练预定位池；但它们必须经过同一个 materializer 和 collator。Group-parent/F1/selected-final 的正式物化身份与 addon 仍按 BOX 契约保存。

### 4.2 共享处理链

所有模式严格调用下列同一条链：

~~~text
ResolvedStage1Crop
  -> load_or_reuse_pdb_assets(pdb_id)
  -> crop_raw_density_by_geometry()
  -> select_receptor_atoms_by_geometry_and_buffer()
  -> build_density_channels(model_recipe)
  -> build_local_receptor_coordinates()
  -> optionally_materialize_targets()
  -> synchronized_augmentation_if_training()
  -> Stage1BatchCollator
~~~

`model_recipe=unet_c1` 时，密度构造器只输出 `exp_clipnorm_nopost`，且受体查询可以完全跳过；`model_recipe=Find` 时，密度通道、受体 buffer 与点—体素输入严格沿用当前 Pocket_Plus CPC 主配方。任何“训练专用归一化”“推理专用 atom filter”“仅推理才有的 density channel”均为禁止行为。

### 4.3 Batch 表示与 collate

voxel_grid 形状固定，因此 batch 直接堆叠。受体原子数可变，但不把底层变长存储细节泄漏到模型接口；collator 采用“拼接实体表 + batch 归属索引”的张量表示：

| 字段 | 形状与 dtype |
|---|---|
| voxel_grid | [batch_size,num_density_channels,80,80,80] float32 |
| ligand_area_target | [batch_size,80,80,80] bool，仅训练/验证 |
| hardmask | [batch_size,80,80,80] int64/bool，仅 Find；训练、验证、推理都按 receptor 现场构造 |
| voxel_label | [batch_size,80,80,80] int64/bool，仅 Find 训练/验证 |
| atom_coord_world / atom_coord_local_voxel / atom_coord_centered_world | [num_batch_receptor_atoms,3] float32；`unet_c1` 不提供 |
| atom_feat | [num_batch_receptor_atoms,49] float32；`unet_c1` 不提供 |
| atom_global_indices | [num_batch_receptor_atoms] int64；`unet_c1` 不提供 |
| atom_batch_index | [num_batch_receptor_atoms] int64；`unet_c1` 不提供 |
| atom_counts / atom_offsets | [batch_size] int64；`unet_c1` 不提供 |
| atom_is_in_core_box | [num_batch_receptor_atoms] bool；`unet_c1` 不提供 |
| atom_label | [num_batch_receptor_atoms] bool，仅 Find 训练/验证 |
| box_start_zyx / box_origin_world / voxel_size_world | 各为 [batch_size,3] |

collator 不填充受体原子到固定最大长度，不制造 voxel_valid_mask。模型按现有 `atom_batch_index/atom_counts/atom_offsets` 分段。

### 4.4 Dataset/DataLoader 的配置纪律

一个 Stage1DataModule 或等价构造函数同时创建 train、validation、predict DataLoader。三者共享：

- 数据 schema 版本与 PDB 资产读取器；
- density_channel_builder 配置；
- atom_buffer_radius；
- 坐标转换函数；
- collator；
- worker 缓存策略；
- 输入字段名与 dtype。

三者仅允许差异为：请求提供者、`require_targets`、augmentation、shuffle、drop_last、每 epoch 抽样数量和输出组装器。`unet_c1` 与 Find 可以使用不同的模型输入 recipe，但同一 recipe 的训练、验证和推理必须完全一致。`pin_memory` 是性能配置，不是契约；沿用成熟训练配置的实际值并以 profiling 调整，不把开或关写成科学语义。

---

## 5. 采样、标签与数据划分

### 5.1 唯一主划分

最终 Stage G 质量过滤完成后，以 **PDB–EMDB pair** 为划分单元，先冻结四个互不相交的原始集合：

| 集合 | 数量/比例 | 用途 |
|---|---:|---|
| train | 最终合格 pair 的 75% | `unet_c1`、Find CPC1/CPC2 及 Stage1 selector 的参数训练；后续模型沿用同一主划分。 |
| validation | 固定 500 pair | 选神经网络 checkpoint；不选概率阈值。 |
| calibration | 固定 100 pair | 选 `t_F1`、多阈值、selector gate 和少量推理参数；不更新网络权重。 |
| held-out test pool | 扣除前三者后的全部剩余 pair | 以后做序列去冗余和多个测试子集；任何结果不得回调模型、checkpoint 或阈值。 |

第一版生成方法固定为：对最终合格 pair 清单按 ID 排序并记录清单哈希，再用一个写入 manifest 的 `split_seed` 做一次随机排列；前 `floor(0.75*N)` 个进入 train，随后 500 个进入 validation、再随后 100 个进入 calibration，其余全部进入 held-out test pool。该确定只用于冻结数据划分，不扩展成模型后处理的稳定排序系统。

当前一个 PDB 只关联一个主 EMDB；未来若同一 PDB 有多个 EMDB，它们必须继承同一 split。一个 pair 的 occurrence、训练位置、滑窗、proposal、CLG、addon 与 selected-final 也全部继承该 split。

train/validation/calibration 的选择必须在看模型表现前一次冻结。train、validation 和 calibration 内部不因序列相似而删样本；随后只从 held-out test pool 反向选择测试子集，使测试样本既与前三者去冗余、又在各测试子集内部去冗余。该过程不反向改前三个集合，也不使用模型表现、checkpoint 或阈值筛样本。

### 5.2 轻量训练预定位池

训练池只记录 ID 和整数起点，不提前切 80³ 数组。每个 PDB 预计算：

```text
occurrence_id:        int32[O]
center_start_zyx:     int32[O,3]
bias_start_zyx:       int32[O,N_bias_pool,3]
context_start_zyx:    int32[C,3]
```

冻结规则：

- 每个 occurrence 恰有一个 center；
- `N_bias_pool` 第一版取 15，供每个 epoch 从中选 5 个；如果正式实现选择更大的池，只改配置和 manifest，不改 schema；
- 每个 PDB 的 context 目标为 500 个合法位置，最多尝试 3000 次；
- context 合法条件中的受体重原子下限 `N_context_min=1000`；
- 同一 PDB 完全相同的 context 起点只保留一条；3000 次后不足 500 则保留实际合法数量并记录计数，不伪造、不无限重试；
- 起点生成调用坐标 parity 放行后的统一 helper；pool manifest 固定其版本与 rounding policy，不在 Dataset 里另算第二套 center 公式；
- 所有 NPZ 用 `np.savez_compressed`；增强后的坐标不落盘。

训练预定位池与推理 addon 分家，但共用同一个 materializer。不要为每条训练记录重复保存 `origin_xyz`、voxel size、shape、JSON provenance 或 `box_type` 字符串。

### 5.3 每个 epoch 的 `1:5:3`

令 train split 的 occurrence 总数为 `N_occ`。每个正式 epoch 恰好组织：

```text
center  = 1 * N_occ    # 全部 center
bias    = 5 * N_occ    # 每 occurrence 从自己的 pool 选 5 个
context = 3 * N_occ    # 全局数目，不是每 PDB 或每 occurrence 各 3 个
```

因此 `center:bias:context = 1:5:3`。bias 按 occurrence 从各自候选池抽取；context 把 train split 的 `(pdb_id,context_candidate_id)` 展平成一个全局池再抽取 `3*N_occ`，池走完时允许重排后循环使用。三个来源都应用同一套在线小幅平移与旋转增强，bias 的在线增强是在已选 bias 起点上继续施加，不替代 bias pool。

validation 永久冻结一份无增强、不 shuffle、不逐 epoch 重抽的 `1:5:3` 清单：全 center、每 occurrence 固定 5 个 bias、全局固定 `3*N_occ_val` 个 context。其 bias/context candidate indices 按 BOX 契约写入 `validation_selection.npz`；`unet_c1`、Find CPC1 与 CPC2 共用这份清单，保证 checkpoint 比较面对同一输入。

### 5.4 标签的唯一来源

voxel 标签只来自当前裁剪位置的 schema v3 ligand-area union mask；受体标签只来自同一 PDB 的 `binding_atom`。一个 BOX 没有 ligand-area 或没有 binding 原子都是合法样本。不存在按 center/bias/context 名称决定正负的第二套规则，也不生成假 `ligand_dist_map`。

### 5.5 可复现性的实际目标

固定并记录 Python、NumPy、PyTorch、DataLoader worker、sampler、增强和 recycle 等显式随机源的 seed；validation 与正式 inference 关闭无意义随机。记录 GPU 型号/数量、batch size、梯度累积、precision、PyTorch/CUDA/cuDNN 版本和确定性开关。

目标是让随机种子尽可能引导现有随机操作并提高复查能力，不承诺不同实验、不同卡数或不同并行时序得到 bitwise 相同的抽样序列、recycle 统计或权重。不得为此大改成熟训练框架或引入稳定排序/规范编号系统。

---

## 6. 增强与边界处理

### 6.1 同步空间增强

center、bias、context 使用同一 augmentation recipe，但平移和旋转的阶段必须分开：

1. **整数平移 jitter**：先改变 runtime `box_start_zyx`，再由 materializer 重新派生 `box_origin_world`、裁剪密度/label 并查询 receptor；不能在已经裁好的 BOX 上只挪 target 或原子。
2. **Pocket_Plus 同步 90° 旋转**：裁剪后围绕固定 BOX 几何中心旋转 `voxel_grid`、`ligand_area_target`、`hardmask`、`voxel_label`、`atom_coord_local_voxel` 和 `atom_coord_centered_world`，再由固定 BOX 中心重建 `atom_coord_world`。`box_start_zyx`、`box_origin_world`、`voxel_size_world` 保持不变，不能把 origin 或 voxel size 当向量一起旋转。

推理与验证关闭随机增强。对极少数超过当前各向同性容差的 voxel size，第一版沿用 Pocket_Plus 当前“记录诊断后继续”的行为，记录次数、样本 ID 和所用变换；不为此终止全量训练、单独 skip 样本或重写坐标系统。

### 6.2 BOX 边界

普通 80³ 训练 BOX、整图边缘滑窗和局部物化 BOX 必须由同一个裁剪器生成。BOX 起点保持原值，不 silent clamp 或平移；与完整图相交部分按原值读取，图外密度与 ligand-area target 补 0，图外没有 receptor atom。固定形状仍不增加 `voxel_valid_mask`。这是 AdaLigand 的明确扩展；不得复用旧 Pocket `split_and_select_box` 的 center floor+clamp 作为新起点生成器。

该行为必须在训练/推理 parity 测试中覆盖：同一个 `pdb_id + box_start_zyx` 无论来自训练池、滑窗还是物化请求，都得到逐元素相同的输入和同一世界坐标。候选是否允许靠近边界是多阈值计划的 proposal 合法性问题，不在基础 Dataset 内偷偷过滤。

---

## 7. 训练、验证与整图推理流水线

### 7.1 Pocket_Plus 复用边界

实现位于 Pocket_Plus 的新开发分支；成熟配置保留为只读基线，新建 AdaLigand 专用 Dataset、loss adapter 与 experiment 配置，不把旧预切 BOX、旧 split/path 或 `ligand_dist_map` 兼容逻辑继续带进新路径。

当前真实基线及 AdaLigand 覆盖如下：

| 运行 | 继承的当前入口 | AdaLigand 必改 | 第一版显式训练值 |
|---|---|---|---|
| `unet_c1` | `../Pocket_Plus/configs/experiment/unet_c1.yaml` | 新 Dataset/split；直接二值 target | per-device batch 10，global batch 40，20 epochs，bf16-mixed，clip 0.5，AdamW `3e-5/0.01`，每 epoch 验证 5 次 |
| Find CPC1 | `../Pocket_Plus/configs/experiment/CPC1/trunk_main.yaml` | 新 Dataset/split；二值 target；关闭 sparse-refine；BEST 从 P AP 改为 voxel ligand AP | per-device batch 6，global batch 42，20 epochs，bf16-mixed，clip 0.5，AdamW `3e-5/0.01`，每 epoch 验证 1 次 |
| Find CPC2 | `../Pocket_Plus/configs/experiment/CPC2/heads_trunk_main.yaml` | 显式 `init_from` CPC1 BEST；新 Dataset/split；二值 target；运行保真 preflight | per-device batch 6，global batch 42，20 epochs，bf16-mixed；small-increment scheduler：无 warmup、patience 1、两次实际降 LR 后停止 |

CPC2 必须在自己的 experiment 文件里显式写出最终 batch/global batch/scheduler，不能依赖 Hydra 继承优先级造成“`small_increment.yaml` 注释是 1/1，而最终 compose 实际是 6/42”的错觉。三个入口在启动前都运行 `--cfg job` 或等价 compose 检查，把最终解析配置存入 run 目录。

### 7.2 `unet_c1` 全量训练

1. 读取完整 train split 的 `1:5:3` 训练流；
2. Dataset 只构造 `exp_clipnorm_nopost` 一个通道，不加载 receptor/sim/diff；
3. 使用当前 U-Net backbone 与 voxel ligand loss，target 直接为二值 `ligand_area_target`；
4. 在固定 validation BOX 上计算 `val_score/global/voxel_ligand_PRAUC`；
5. 该指标最大者写 `checkpoints/BEST.ckpt`。

这里 `PRAUC` 在当前 Pocket_Plus wrapper 中由 binary average precision 实现；文档中统一称为 ligand-area AP，日志 key 保留现有名字。

### 7.3 Find CPC1 全量训练

1. 使用当前 `CPC1/trunk_main` 的点—体素主干、P token、atom/voxel/P 监督和 stage1 冻结语义；
2. real/P cross-attention 与取消的 sparse-refine 路径不训练；
3. dense voxel loss、voxel AP 与 P target 都从同一个二值 `ligand_area_target` 获得；
4. 固定 validation BOX 上的 `val_score/global/voxel_ligand_PRAUC` 是唯一 BEST 选择指标；
5. P AP、receptor-atom binding AP（沿用现有日志 key 时可仍写 A/atom AP）及各分支 loss 继续报告，但不替代 CPC1 的 BEST 标准。

### 7.4 CPC2 训练前保真 preflight

这是与正式 Trainer 解耦的独立测试程序，在 CPC2 正式训练前运行；不是训练后的验收 callback。它用固定小 batch 精确但短暂地模拟真实 CPC2：

1. 加载 CPC1 `BEST.ckpt`，应用与正式 CPC2 相同的 stage2 freeze；
2. 保存 ligand-area 路径全部参数与 buffer 状态，并在固定输入、`eval` 模式和相同 forward 设置下记录原始 ligand-area logits；
3. 执行真实 CPC2 forward、loss、backward 和一次 optimizer step；
4. 断言至少一个应训练的 cross-attention/尾部参数发生改变；
5. 断言 ligand-area 路径的参数与 buffer 未变；
6. optimizer step 后再次切回相同 `eval` forward 设置，对同一固定输入比较 ligand-area logits；差异只允许处于同一模型重复运行已有的微小数值误差范围。

任何一项失败都阻断 CPC2，先修 freeze 或计算路径。该程序放在独立 tests/acceptance 或等价目录，不把哈希、逐层比较和诊断代码塞进正式训练循环。

### 7.5 Find CPC2 全量训练

1. 从 CPC1 `BEST.ckpt` model-only 初始化；
2. 使用当前 `frozen_module/stage2.yaml` 的冻结集合，只训练 real/P cross-attention 与相应尾部；
3. BEST 使用 `val_score/global/pseudo_PRAUC`，即 P AP；
4. receptor-atom binding AP（现有日志中的 A/atom AP）、voxel ligand AP 和所有 loss 同时报告；
5. CPC2 运行目录与 CPC1 完全分开；CPC2 manifest 记录其来源 CPC1 run 与 `BEST.ckpt` 校验值。

CPC2 的核心约束不是“允许 voxel ligand AP 小幅下降”，而是 ligand-area 路径根本不应被 CPC2 改动。preflight 证明实现正确，正式训练只保留普通指标监控，不在 Trainer 内重复整套验收逻辑。

### 7.6 通用 train/validation step

train 与 validation 都走同一个 batch 构造；validation 关闭增强、shuffle 和逐 epoch 重抽。训练记录实际 center/bias/context 数量、每项启用 loss、AP、吞吐、DataLoader wait、显存和异常样本计数。来源分层统计只用于诊断，不把来源输入网络。

### 7.7 整图推理交接

1. WindowRequestProvider 枚举完整图滑窗；
2. predict DataLoader 通过同一个 Dataset/Collator 生成 Stage1Batch；
3. GPU 输出窗口 ligand-area 概率及所需 receptor 概率；
4. CPU 概率组装器按 box_start_zyx 和固定 window weight 写入完整图累加器；
5. 后续组件森林与多阈值流程由 Stage1训练与多阈值推理.md 负责。

第一次整图推理正式保存完整 `P_global`；此时不保存每个滑窗的完整中间特征。组件森林、CLG、Group-parent 首次居中推理、selector addon、selection addon 与 selected-final 继续由 `Stage1训练与多阈值推理.md` 和 BOX 契约规定，本文没有取消它们。

---

## 8. CPU/GPU 流水线与缓存

每个 DataLoader worker 可以维护一个按 `pdb_id` 键控、以**总字节数**为上限的 LRU 缓存，缓存整图 exp/sim、受体坐标、49 维受体特征和训练标签的已打开只读对象。不同 PDB 体积差异很大，不能只按“缓存多少个 PDB”控制内存。缓存只减少重复读取，不改变数据值或坐标。

推荐的流水线是：

~~~text
CPU worker: 读取整图资产 -> 裁剪 -> 受体几何查询 -> density channel
GPU:        Stage1 forward + loss 或窗口概率
CPU writer: 仅整图推理时组装概率
~~~

训练不缓存逐 BOX 中间特征。整图推理中 GPU 与概率组装器之间使用有界队列，保证一个完整图的概率累加器只有一个逻辑写者。模型 batch size 使用 §7 已冻结的首版值；worker、prefetch、缓存字节数和推理 batch 可在不改变数值语义的前提下 profiling 调整。

容量按已确认预算执行：质量过滤后基础压缩资产可按约 1 TB 规划，完整 `P_global` 与 blob 内中间特征合计可按最高约 15 TB 规划。所有 NPZ 使用压缩写盘并记录实测体量；该容量不是把首版降成 pilot、跳过全量 Find 训练或删除 addon/selected-final 接口的理由。

---

## 9. 运行清单与可追溯性

每次 Stage1 训练写入不可变 manifest，至少包含：

- Pocket_Plus commit/工作树状态、数据 release、四集合 split manifest 和训练预定位池版本；
- density_channel_builder 全量配置及输出通道名称；
- atom_buffer_radius、坐标约定、增强开关与边界策略版本；
- center/bias/context 的 pool 参数、`1:5:3` 配额和实际抽样数量；
- loss 配置、优化器、调度器、随机种子和 checkpoint 哈希；
- compose 后的完整 Hydra 配置与输入/输出字段 schema。

运行目录沿用 Pocket_Plus `ExperimentManager`，但各阶段必须天然分开：

```text
logs/unet000/unet_c1____{run_stamp}/
logs/CPC1/trunk_main____{run_stamp}/
logs/CPC2/heads_trunk_main____{run_stamp}/
```

或使用同构的 Ada 专用 group/tag；每个目录独立拥有 `checkpoints/BEST.ckpt`、resolved config、manifest 和日志。不得把 CPC2 产物覆盖进 CPC1 目录。

每次正式整图推理写入 inference manifest，至少包含：

- 使用的 Stage1 checkpoint 哈希；
- 与训练一致的密度通道、原子筛选和 collator 配置哈希；
- 滑窗 shape、stride、window weight 和概率输出定义；
- 输入 PDB 资产版本与输出概率文件哈希。

若训练 manifest 与推理 manifest 的共享数据 recipe 不一致，推理程序必须拒绝把结果标为同一 `probability_run_id`。这里的 ID 只负责区分实际配方；不要求为它开发 canonical JSON、跨重跑规范编号或稳定排序框架。

---

## 10. 验证清单

实现完成前必须通过以下检查：

1. **跨项目 BOX parity**：给定同一个 `box_start_zyx`，修改后的 AdaLigand A–G 与当前 Pocket_Plus 对真实 map 和 receptor 给出相同 voxel center、相交区域输入 crop 与局部坐标；同一 ZYX slice 从 Ada schema v3 直接裁出的 `ligand_area_target` 必须与原 union mask 对齐。该测试验证共同坐标帧与 materializer，不要求两边采用相同的起点采样/clamp 策略，也不把不同的 GT mask 生成科学语义强行判成相同。
2. **模式同构**：同一 `ResolvedStage1Crop` 在 targets 开/关时，所有模型输入张量逐元素一致。
3. **裁剪一致性**：训练请求与推理滑窗请求对相同几何位置生成完全相同的 voxel_grid 和受体输入。
4. **二值 target 接通**：`ligand_area_target` 等于 schema v3 mask 直接裁剪；dense loss、voxel AP 和 P 监督都读取它，batch 中无需 `ligand_dist_map`。
5. **collate 一致性**：单样本 batch 与多样本 batch 中每个样本的受体 batch 归属、坐标和 target 不变。
6. **增强一致性**：增强后密度、voxel 标签和受体局部坐标仍表示同一个物理变换。
7. **采样配额**：一个合成 epoch 的 center/bias/context 数量严格为 `1:5:3`；validation 清单两次读取完全相同且无增强。
8. **纯密度隔离**：`unet_c1` batch 只有一个 `exp_clipnorm_nopost` 通道，移除 receptor/sim 后前向仍成立。
9. **CPC receptor voxel auxiliary**：Find 的 `hardmask` 等于全部 core receptor home voxel 并集，`voxel_label` 等于其中 binding 原子 home voxel 并集；它们与 `voxel_valid_mask`、`ligand_area_target` 两两不混用，推理 batch 无伪 target。
10. **配置 compose**：三个 experiment 的最终 batch/global batch、monitor、loss、freeze 与 scheduler 等于 §7；不得只检查父 YAML。
11. **一步真实反传**：三个阶段各用一个真实 batch 完成 forward/loss/backward/optimizer step，所有应训练分支有有限梯度，已取消分支不进入 loss。
12. **CPC2 保真 preflight**：按 §7.4 证明应训练参数会变、ligand-area 参数/buffer/logits不变。
13. **整图 smoke test**：predict DataLoader 可从一张 PDB 完成滑窗、概率融合并生成可读取的全图概率。
14. **性能记录**：报告每秒 BOX、worker wait、GPU 利用率、host RAM 与峰值显存；只优化测得的瓶颈。

这些测试可以只处理极少真实样本，因为它们验证代码；通过后直接启动全量训练。不得再加“先用小集把模型训到收敛”作为正式训练前置阶段。

---

## 11. 建议实施顺序

以下顺序是可以直接交给实现 agent 的主线；不要求再设计一套更大的通用框架。

### 11.1 现在即可并行完成

1. 在 Pocket_Plus 新分支冻结当前成熟基线 commit/工作树证据；新建 AdaLigand 专用 experiment、Dataset 与 tests，不改老 experiment 的默认语义。
2. 定义训练预定位池、运行时 crop request 和唯一 materializer；接入 A–G 当前 schema v3 资产。
3. 完成修改后 A–G 与 Pocket_Plus 的坐标/裁剪 parity；这是坐标唯一放行门。
4. 实现 train/validation/window 三个 request provider，共用同一 materializer/collator。
5. 把二值 `ligand_area_target` 接入 dense loss、voxel AP 与 P 监督；删除 Ada 路径对 distance map 的依赖。
6. 新建 `unet_c1`、CPC1、CPC2 三个 Ada 配置并做完整 Hydra compose 断言。
7. 实现独立 CPC2 保真 preflight 与 §10 其它正确性测试。

这些工作不需要等待 Stage G 最终阈值或服务器全量 keep-list，可以在少量真实、已知合格样本上完成代码验收；这不构成 pilot 训练。

### 11.2 正式全量训练放行门

只有以下事实全部成立，才把某次训练称为正式全量训练：

1. A–G 正式 release/keep-list 已完成并冻结，E3 schema v3 全量迁移及 release gate 通过；
2. `75% / 500 / 100 / remainder` split manifest 已冻结且互不相交；
3. train 预定位池和固定 validation `1:5:3` 清单通过冷读验证；
4. §10 全部正确性测试通过；
5. Pocket_Plus 当前代码、resolved configs 与服务器环境被记录；
6. 目标输出根容量、日志和断点恢复路径已确认。

### 11.3 正式启动顺序

```text
全量 unet_c1
  -> 选 ligand-area AP BEST

全量 Find CPC1
  -> 选 ligand-area AP BEST
  -> 运行 CPC2 保真 preflight

全量 Find CPC2(init_from=CPC1 BEST)
  -> 选 P AP BEST
  -> 固定正式 Find checkpoint
```

实际入口沿用 Pocket_Plus：

```text
python src/train.py +experiment=<AdaLigand/unet_c1>
python src/train.py +experiment=<AdaLigand/CPC1/trunk_main>
python src/train.py +experiment=<AdaLigand/CPC2/heads_trunk_main> init_from=<CPC1_run_or_BEST>
```

尖括号是实现时创建的明确配置名/路径，不允许保留 `***` 自动猜来源。服务器提交必须遵守项目现有 sbatch/lock 纪律；本文不复制服务器操作脚本。

### 11.4 Find 完成后的 Stage1 推进

1. 分别用正式 `unet_c1` 与 Find checkpoint、同一 materializer 做所需集合的全图滑窗推理并落盘各自 `P_global`；`unet_c1` 用于纯密度完整图、F1 组件与指标，不做要求 P/receptor 的局部物化；Find 才承接正式 F1 materialization 与 selector 路线。训练集为 selector/后续模型准备材料时，前期可先物化一部分，但正式 validation/calibration/test 必须使用各自冻结 checkpoint 与配方。
2. calibration 100 上冻结 `t_F1` 与多阈值；从同一 `P_global` 构造 proposal forest。
3. 按工作树删除规则枚举 CLG，执行 Group-parent 第一次居中推理并写 Stage1 addon；F1 baseline 走自己的物化角色。
4. 用 train/validation 的 CLG 训练并选择 Stage1 selector；用 calibration 冻结 gate，随后运行 multi-threshold selection，可选 selected-final 继续保留。
5. 在冻结的测试子集上评估 Find/F1 baseline/multi-threshold 路线。具体算法、网络和字段仍以并列 Stage1 计划与 BOX 契约为准。

---

## 12. 实现时必须显式落定的少量配置

| 事项 | 当前处理 |
|---|---|
| Find 密度通道的精确名称、顺序和归一化参数 | 从当前 CPC1 composed config 与 builder 解析成显式有序清单；不能把 `enabled_channels: [all]` 当成字段定义。`unet_c1` 已固定只有 `exp_clipnorm_nopost`。 |
| Find 各保留 loss 的形式/权重 | 复用当前 CPC1/CPC2 中 atom、voxel auxiliary、voxel ligand、P 的真实解析值；在 Ada loss 配置中显式关闭 sparse-refine，并把 distance target 改为 binary target。 |
| `atom_buffer_radius`、core atom mask 与 receptor 指标 | 复用当前 CPC 主配方的实际值和代码语义，写进 resolved config 与测试；不在本文另造数值。 |
| bias pool 分布与在线平移/旋转幅度 | 作为训练配置落定并记录；数量规则 `15 选 5` 与全局 `1:5:3` 已冻结。 |
| 首次局部物化实际导出的 voxel/P/receptor 字段 | 由 selector 已确认的输入架构和 Pocket_Plus 真实 forward 出口共同决定；通过 BOX addon 的 feature-source manifest 接入，不删除 addon 或 selected-final。 |

这些是实现 agent 必须从当前代码和已定设计中显式解析的配置，不是重新发明科学方案的授权。主骨架已经冻结：训练池轻量化、`1:5:3`、二值 target、全量 `unet_c1 -> CPC1 -> CPC2`、训练/推理同一物化路径。
