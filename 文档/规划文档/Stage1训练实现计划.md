# AdaLigand Stage1 训练实现计划

> **文档角色**：本文把 Stage1 Find 的基础训练落实到可实现的数据路径。它只覆盖“如何把一个轻量 BOX 描述子解析成 Stage1 训练或推理样本、如何训练 Pocket_Plus Stage1 主干、如何保证训练与整图推理共用同一 Dataset/DataLoader”。它不规定多阈值组件树、候选谱系组、候选选择器、Stage2 Match、Stage3 Build 或局部特征物化。
>
> **上游与并列契约**：
>
> - 整图资产与 GT 来源：文档/规划文档/数据处理_v2.md。
> - BOX 几何字段与存储边界：文档/讨论/BOX-level数据契约.md。
> - Stage1 训练目标、整图推理和后续候选链：文档/规划文档/Stage1训练与多阈值推理.md。
> - 原始密度通道构造约定：Data_Preprocessing/Ori_Data/code/readme.md。
>
> **状态**：这是供审阅的目标计划。未经后续确认，不修改上述文档、映射索引或代码。

---

## 1. 范围、目标与硬边界

Stage1 是密度与受体条件下的基础预测器。训练后它在每个 80³ BOX 上至少输出：

1. ligand-area 的 voxel 级预测；
2. receptor-binding 的受体原子级预测。

Stage1 训练样本只需要 BOX 的轻量几何身份，加上按该身份从整图资产切出的原始输入与训练期标签。它**不读取**候选谱系组、Global Proposal、选择器分数、候选成员关系、Group-parent 特征包、Stage2/3 addon 或 selected-final 产物。

下列原则冻结为本计划的实现边界：

- center、bias、context、infered_box 只是 BOX 原点或请求来源；它们不是正/负样本类别，也不直接进入 loss。
- 训练与推理使用同一个 Stage1BoxDataset、同一个 Stage1BatchCollator、同一个密度通道构造器和同一个受体裁剪器。两者只在“BOX 请求从哪里来”和“是否附带 GT”上不同。
- P 是 Stage1 模型内部生成的 pseudo-atom token，不是 Stage1 Dataset 需要保存或加载的复杂 BOX 字段。
- 训练期不为了适配下游而保存 Stage1 中间特征；全图推理期中间特征的物化属于另一个计划。
- 固定 80³ 的普通训练 BOX 不引入 voxel_valid_mask。

---

## 2. 术语、坐标与最小输入契约

### 2.1 坐标约定

- 网格数组空间轴恒为 ZYX，密度与 voxel 标签形状均为 [D, H, W]。
- 世界坐标恒为 XYZ，单位为 Å。
- BOX 局部 voxel 索引 [z, y, x] 的中心世界坐标为：

$$
\mathrm{world}_{xyz}
=
\mathrm{origin}_{xyz}
+
\mathrm{voxel\_size}_{xyz}\odot[x,y,z].
$$

- 第一个 Stage1 版本固定 BOX 形状为 [80, 80, 80]。任何组件不得私自改变轴顺序或把 XYZ 当成 ZYX。

### 2.2 Stage1BoxRequest：唯一的 BOX 请求对象

Stage1BoxRequest 是 Dataset 的输入身份，不是盘上大数组。它只由现有 BOX 描述子字段和运行模式构成。

| 字段 | 类型/形状 | 来源与意义 |
|---|---|---|
| pdb_id | str | 整图资产的唯一键。 |
| box_type | str | center、bias、context、infered_box 或未来开放来源；只供采样、追溯和统计。 |
| box_id | int | 在 (pdb_id, box_type) 内唯一。滑窗推理的临时请求也有稳定局部编号。 |
| box_start_zyx | int32[3] | BOX 在完整网格的整数起点。 |
| origin_xyz | float32[3] | BOX 局部 voxel [0,0,0] 的中心世界坐标。 |
| shape_zyx | uint16[3] | 第一版恒为 [80,80,80]。 |
| voxel_size_xyz | float32[3] | 完整图的实际 voxel size。 |
| provenance | JSON 可序列化对象 | bias 的偏移、context 的随机种子或滑窗枚举版本等可复现信息。 |
| require_targets | bool | 训练/验证为 True，正式整图推理为 False；不属于盘上 BOX schema。 |

除上述字段外，Stage1 不要求 BOX addon。训练样本的密度、受体和标签一律按 pdb_id 与几何字段从第 1 层整图资产解析。

### 2.3 需要解析的整图资产

| 资产 | 解码后形状 | Stage1 用途 |
|---|---|---|
| exp 密度 | [1,D,H,W] float32 | 必需原始密度输入。 |
| sim 密度 | [1,D,H,W] float32，可缺 | 仅当密度通道配置启用 sim/diff 类通道时读取。 |
| 受体世界坐标 | [num_receptor_atoms,3] float32 | 按 BOX + buffer 选取受体原子，并构造局部坐标。 |
| 受体基础特征 | [num_receptor_atoms,49] float32 | Stage1 点分支的受体输入。 |
| ligand_area | [1,D,H,W] bool | require_targets=True 时裁成 voxel 监督。 |
| binding_atom | [num_receptor_atoms] bool | require_targets=True 时按选中的受体原子取监督。 |
| instance_id | [num_receptor_atoms] int32 | 可保留为诊断/后续兼容标签；第一版不新增独立训练头。 |

密度通道、受体局部索引和训练标签都是现场派生量，不写进基础 BOX 描述子。

---

## 3. 单样本输出：训练和推理同构

Stage1BoxDataset 的每次 __getitem__ 都先生成同一份输入字段；训练/验证仅额外附带 targets。禁止训练路径读取“预切 BOX 文件”而推理路径另写一套切图逻辑。

### 3.1 通用输入字段

| 字段 | 形状与 dtype | 含义 |
|---|---|---|
| voxel_grid | [num_density_channels,80,80,80] float32 | 由同一个 density_channel_builder 现场构造的密度输入。 |
| box_start_zyx | [3] int32 | 追溯与整图概率回写用的局部起点。 |
| box_origin_xyz | [3] float32 | 当前 BOX 的世界坐标原点。 |
| voxel_size_xyz | [3] float32 | 当前图的实际 XYZ voxel size。 |
| receptor_global_index | [num_box_receptor_atoms] int64 | 所选受体原子在该 PDB 整图受体表中的索引。 |
| receptor_coordinates_world | [num_box_receptor_atoms,3] float32 | 所选受体原子的 XYZ 世界坐标。 |
| receptor_coordinates_local_voxel | [num_box_receptor_atoms,3] float32 | 相对当前 BOX 的连续 XYZ voxel 坐标。 |
| receptor_features | [num_box_receptor_atoms,49] float32 | 从整图 49 维受体表切出的基础特征。 |
| receptor_is_in_core_box | [num_box_receptor_atoms] bool | 原子是否落在 80³ core；buffer 原子可作上下文但不重复计入核心指标。 |
| box_metadata | Python 标量/短字典 | pdb_id、box_type、box_id、provenance 和请求版本；不送入模型数值分支。 |

受体原子选择规则固定为：先以 BOX 世界范围加 atom_buffer_radius 查询整图受体，再保留其全局索引。所有模式用同一个查询器；不得训练时按 GT 选原子、推理时按几何选原子。

### 3.2 训练与验证附带的监督字段

当 require_targets=True 时，Dataset 额外返回：

| 字段 | 形状与 dtype | 构造规则 |
|---|---|---|
| ligand_area_target | [80,80,80] bool | 直接裁剪整图 ligand_area；空 crop 合法，全部为 False。 |
| receptor_binding_target | [num_box_receptor_atoms] bool | 由 receptor_global_index 从整图 binding_atom 取值。 |
| receptor_instance_target | [num_box_receptor_atoms] int32 | 由整图 instance_id 取值；第一版只作可视化与一致性检查。 |
| target_available | bool 标量 | 恒为 True，用于统一 collate 的显式断言。 |

当 require_targets=False 时，上述四个字段均不构造。模型输入字段、密度通道、受体筛选、坐标变换与 collate 行为仍完全相同。

### 3.3 模型输出与最小 loss 接口

训练包装层将现有 Pocket_Plus Stage1 输出适配成下列语义：

| 输出 | 形状 | 监督 |
|---|---|---|
| ligand_area_logit | [batch_size,1,80,80,80] | 对 ligand_area_target 计算现有 voxel 主损失。 |
| receptor_binding_logit | [num_batch_receptor_atoms] 或等价带 batch 索引表示 | 对 receptor_binding_target 计算现有受体原子主损失。 |

第一版总损失保持最小形式：

$$
\mathcal L_{\mathrm{Stage1}}
=
\lambda_{\mathrm{voxel}}\mathcal L_{\mathrm{voxel}}
+
\lambda_{\mathrm{receptor}}\mathcal L_{\mathrm{receptor}}.
$$

具体 voxel/receptor loss 种类、类别权重与两个系数必须由现有可复现实验配置冻结，并写入训练 manifest；本计划不凭空替换为新的损失。CPC sparse-refine 第三训练阶段与最终 refine head 不属于本训练计划。

---

## 4. 一个 Dataset、一个 DataLoader 路径

### 4.1 三个可替换的请求提供者

Dataset 不关心 BOX 是如何产生的，只消费 Stage1BoxRequest。请求提供者可替换：

| 运行用途 | 请求提供者 | require_targets |
|---|---|---:|
| 训练 | 按 source weights 从 box_index 的 center/bias/context/infered_box 请求中抽取 | True |
| 验证 | 固定验证集的 BOX 请求列表 | True |
| 整图推理 | 由完整图 shape、window shape、stride 生成的滑窗请求列表 | False |

正式整图推理的滑窗请求可以是内存临时对象，不必先写入 box_index；但它们必须经过同一个 Dataset 解析函数。若需要落盘追溯，才把相同字段写成正式描述子。

### 4.2 共享处理链

所有模式严格调用下列同一条链：

~~~text
Stage1BoxRequest
  -> load_or_reuse_pdb_assets(pdb_id)
  -> crop_raw_density_by_geometry()
  -> select_receptor_atoms_by_geometry_and_buffer()
  -> build_density_channels(exp, sim, receptor occupancy)
  -> build_local_receptor_coordinates()
  -> optionally_materialize_targets()
  -> synchronized_augmentation_if_training()
  -> Stage1BatchCollator
~~~

任何“训练专用归一化”“推理专用 atom filter”“仅推理才有的 density channel”均为禁止行为。若将来发现确有需要，必须以显式配置字段、训练/推理双端测试和用户确认引入。

### 4.3 Batch 表示与 collate

voxel_grid 形状固定，因此 batch 直接堆叠。受体原子数可变，但不把底层变长存储细节泄漏到模型接口；collator 采用“拼接实体表 + batch 归属索引”的张量表示：

| 字段 | 形状与 dtype |
|---|---|
| voxel_grid | [batch_size,num_density_channels,80,80,80] float32 |
| ligand_area_target | [batch_size,80,80,80] bool，仅训练/验证 |
| receptor_coordinates_world | [num_batch_receptor_atoms,3] float32 |
| receptor_coordinates_local_voxel | [num_batch_receptor_atoms,3] float32 |
| receptor_features | [num_batch_receptor_atoms,49] float32 |
| receptor_global_index | [num_batch_receptor_atoms] int64 |
| receptor_batch_index | [num_batch_receptor_atoms] int64，取值为 0 到 batch_size-1 |
| receptor_is_in_core_box | [num_batch_receptor_atoms] bool |
| receptor_binding_target | [num_batch_receptor_atoms] bool，仅训练/验证 |
| box_start_zyx / box_origin_xyz / voxel_size_xyz | 各为 [batch_size,3] |

collator 不填充受体原子到固定最大长度，不制造 voxel_valid_mask。模型若需要按样本分段，使用 receptor_batch_index。

### 4.4 Dataset/DataLoader 的配置纪律

一个 Stage1DataModule 或等价构造函数同时创建 train、validation、predict DataLoader。三者共享：

- 数据 schema 版本与 PDB 资产读取器；
- density_channel_builder 配置；
- atom_buffer_radius；
- 坐标转换函数；
- collator；
- worker 缓存策略；
- 输入字段名与 dtype。

三者仅允许差异为：请求提供者、require_targets、augmentation、shuffle、drop_last、每 epoch 抽样数量和输出组装器。pin_memory 默认关闭；它不是训练/推理同构或 CPU/GPU 并行的必要条件。

---

## 5. 采样、标签与数据划分

### 5.1 来源比例开关

训练采样只由显式权重控制：

~~~yaml
stage1_training:
  box_source_weight:
    center: 1.0
    bias: 1.0
    context: 1.0
    infered_box: 0.0
~~~

权重为 0 表示关闭。每个 epoch 根据全局 seed、epoch、rank 和权重确定来源序列；同一配置必须在单卡/多卡下可复现。推荐按权重先确定每种来源的整数配额，再在该来源的 BOX 列表内无放回循环抽取；这避免纯随机波动掩盖来源比例。

不同来源空间重合时也保留为不同采样记录。不得按 BOX 坐标去重，不得因为 center/bias/context 名称推断标签。

### 5.2 infered_box 的训练开关

infered_box 也是一个可选请求来源，而非特殊类别。第一版默认权重为 0。若后续启用，配置必须同时固定 proposal_run_id、BOX 索引版本和数据 split；不能让训练集读取由验证/测试信息调过的推理产物。是否把它用于 Stage1 重训属于显式实验决定，不是基础训练的隐含步骤。

### 5.3 标签的唯一来源

voxel 标签只来自裁剪后的整图 ligand_area；受体标签只来自同一 PDB 的 binding_atom。一个 BOX 内没有 ligand-area 或没有 binding 原子都是合法监督样本。不存在“按 box_type 决定正负”的第二套规则。

数据 split 以 PDB 为最小单位。一个 PDB 的任何 BOX、滑窗、occurrence 与派生 infered_box 只能落入同一 split。阈值 calibration 集与 Stage1 训练/验证集分离，避免把推理阈值选择混进模型早停或参数更新。

---

## 6. 增强与边界处理

### 6.1 同步空间增强

训练期的离散旋转或轴交换必须同步作用于：

- voxel_grid；
- ligand_area_target；
- receptor_coordinates_local_voxel；
- receptor_coordinates_world 的相对 BOX 表达；
- box_origin_xyz、voxel_size_xyz 和相关几何元数据。

推理与验证关闭随机增强。实现不得因极少数非严格等方 voxel size 直接终止训练；保留既有宽容行为，并记录发生次数、样本 ID 和所用变换。需要在实现前确认“物理世界坐标如何随非等方轴交换表示”的数值细节，但这个诊断不应把少量样本变成训练崩溃点。

### 6.2 BOX 边界

普通 80³ 训练 BOX 必须由同一个裁剪器生成。当前计划不把“补齐区域”作为模型输入语义，也不恢复 voxel_valid_mask。

以下情况尚需与 Stage1 整图推理计划统一后再编码：

1. 完整密度图任一轴短于 80 时，是否允许常数扩展；
2. 局部居中 BOX 越出整图时，扩展值、受体查询范围与世界坐标如何定义；
3. 若允许扩展，如何保证训练与推理完全一致而不把扩展区域误当真实背景。

在该口径冻结前，数据枚举器只能提供能完整解析的训练请求，并把异常请求记为诊断；不得由 Dataset 静默 clamp。

---

## 7. 训练、验证与整图推理流水线

### 7.1 训练 step

1. train DataLoader 输出 Stage1Batch；
2. GPU 执行 Stage1 前向，P 由模型内部产生；
3. 训练包装层计算 voxel 与 receptor 两个主损失；
4. 记录源比例、loss、有效 voxel/原子数、吞吐、DataLoader 等待时间和 GPU 利用率；
5. 按配置保存 checkpoint 与训练 manifest。

### 7.2 验证 step

validation DataLoader 走完全相同的 batch 构造，关闭随机增强与 shuffle。至少报告 ligand-area 与 receptor-binding 的 loss、precision、recall、F1，以及按 box_type 分层的诊断。分层指标只用于检查采样覆盖，不把 box_type 输入网络。

### 7.3 整图推理 step

1. WindowRequestProvider 枚举完整图滑窗；
2. predict DataLoader 通过同一个 Dataset/Collator 生成 Stage1Batch；
3. GPU 输出窗口 ligand-area 概率及所需 receptor 概率；
4. CPU 概率组装器按 box_start_zyx 和固定 window weight 写入完整图累加器；
5. 后续组件森林与多阈值流程由 Stage1训练与多阈值推理.md 负责。

第一遍整图推理只保存需要组装的概率，不在这个训练计划中加入候选特征缓存。

---

## 8. CPU/GPU 流水线与缓存

每个 DataLoader worker 可以维护一个按 pdb_id 键控的小型 LRU 缓存，缓存整图 exp/sim、受体坐标、49 维受体特征和训练标签的已打开只读对象。缓存只减少重复读取，不改变数据值或坐标。

推荐的流水线是：

~~~text
CPU worker: 读取整图资产 -> 裁剪 -> 受体几何查询 -> density channel
GPU:        Stage1 forward + loss 或窗口概率
CPU writer: 仅整图推理时组装概率
~~~

训练不缓存逐 BOX 中间特征。整图推理中 GPU 与概率组装器之间使用有界队列，保证一个完整图的概率累加器只有一个逻辑写者。worker 数、prefetch 数与 batch size 由实际 profiling 决定，不把某个机器配置写死为契约。

---

## 9. 运行清单与可追溯性

每次 Stage1 训练写入不可变 manifest，至少包含：

- 代码版本、数据 schema/version、PDB split 和 box_index 版本；
- density_channel_builder 全量配置及输出通道名称；
- atom_buffer_radius、坐标约定、增强开关与边界策略版本；
- 各 box_type 的采样权重和实际抽样数量；
- loss 配置、优化器、调度器、随机种子和 checkpoint 哈希；
- 输入/输出字段 schema 哈希。

每次正式整图推理写入 inference manifest，至少包含：

- 使用的 Stage1 checkpoint 哈希；
- 与训练一致的密度通道、原子筛选和 collator 配置哈希；
- 滑窗 shape、stride、window weight 和概率输出定义；
- 输入 PDB 资产版本与输出概率文件哈希。

若训练 manifest 与推理 manifest 的共享数据路径配置不一致，推理程序必须拒绝把结果标为同一 Stage1 运行。

---

## 10. 验证清单

实现完成前必须通过以下检查：

1. **几何 round-trip**：BOX 局部 [z,y,x] 与 world XYZ 的往返误差符合 voxel-center 约定。
2. **模式同构**：同一 Stage1BoxRequest 在 targets 开/关时，所有模型输入张量逐元素一致。
3. **裁剪一致性**：训练请求与推理滑窗请求对相同几何位置生成完全相同的 voxel_grid 和受体输入。
4. **标签索引一致性**：receptor_global_index 取回的 binding 标签与整图标签一致；ligand_area_target 等于整图 mask 的直接裁剪。
5. **collate 一致性**：单样本 batch 与多样本 batch 中每个样本的受体 batch 归属、坐标和 target 不变。
6. **增强一致性**：增强后密度、voxel 标签和受体局部坐标仍表示同一个物理变换。
7. **采样可复现**：固定 seed、epoch、world size 与配置时，来源配额和 BOX 序列稳定。
8. **小集过拟合**：少量固定 BOX 可明显下降两个主损失，证明标签与模型接口可达。
9. **整图 smoke test**：predict DataLoader 可从一张 PDB 完成滑窗、概率融合并生成可读取的全图概率。
10. **性能记录**：报告每秒 BOX、worker 等待、GPU 利用率与峰值显存；只有测得瓶颈后才增加缓存或改并行策略。

---

## 11. 建议实施顺序

1. 定义 Stage1BoxRequest、整图资产读取器和唯一坐标转换函数，并完成几何 round-trip 测试。
2. 实现不含标签的统一输入构造：密度裁剪、受体几何筛选、密度通道与局部坐标。
3. 在同一 Dataset 内加入可开关的目标裁剪，不复制输入路径。
4. 实现 Stage1BatchCollator 与 train/validation/predict 三个请求提供者。
5. 接入现有 Pocket_Plus Stage1 包装层、现有两项主损失与训练 manifest。
6. 用同一 predict DataLoader 替换整图滑窗的独立样本构造路径，并做逐窗口输入 parity。
7. 在训练/验证/整图 smoke test 都稳定后，再处理多阈值概率树与任何 Stage1 后续 addon。

---

## 12. 尚待确认、不得擅自补全的事项

| 事项 | 当前处理 |
|---|---|
| 密度通道的精确名称、顺序和归一化参数 | 复用当前可验证配置；在首次实现前从基线 config 冻结到 manifest。 |
| voxel 与 receptor 两个主损失的具体形式/权重 | 复用现有基线；新实验由配置显式比较，不在 Dataset 中隐藏变更。 |
| atom_buffer_radius 与 receptor core-loss 的精确口径 | 先从现有 Pocket_Plus 训练配置追溯；确认后写入配置和测试。 |
| infered_box 是否参与 Stage1 再训练 | 默认关闭；仅作为可选采样来源，需独立实验确认。 |
| 小于 80³ 或越出整图的 BOX 扩展规则 | 等待与整图推理/BOX 边界约定统一；不以静默 clamp 或 voxel_valid_mask 代替决定。 |

这些开放点不改变本计划的主骨架：Stage1 只消费极简 BOX 几何和整图基础资产，训练与推理只走一条 Dataset/DataLoader 数据路径。
