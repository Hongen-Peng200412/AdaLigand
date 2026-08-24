# AdaLigand BOX 级数据契约

本文定义 AdaLigand Stage1 训练预定位、完整图概率、通用 F-alpha 阈值与连通区域、centered 特征和评估事实的磁盘契约。本文面向产物的生产者与消费者；只看本文，读者应能确定正式文件、字段、形状、坐标、空值、索引目标、完成状态和跨文件对齐关系。

Pocket Plus 仓库的 `src/inference/README.md` 覆盖相同产物，并额外说明模块职责、生产命令和并发边界。两份文档不得对同一文件给出不同定义。

## 1. 范围、术语与共同规则

### 1.1 三个身份轴

- Stage1 模型来源：对应命令参数 `--producer`；正式目录名由调用者显式提供，例如 `Find_0`、`unet_c1` 或 `unet_base`，CLI 不维护名称白名单。
- 数据划分：对应命令参数 `--split`，常用值为 `calibration`、`validation` 和 `train`。
- PDB 身份：对应 `pdb_id`，正式值为小写且非空；同一清单不得出现重复身份。

`Find_*` 模型来源使用体素模态 V、点模态 P 和原子模态 A；`unet_*` 只保存体素模态 V。本文保留目录术语 `centered`，表示为一个来源组件解析合法 80³ BOX 并在该 BOX 中重新执行模型。

“blob”表示在一个冻结概率阈值上得到的 26 邻域连通体素集合。“centered 候选”表示 centered NPZ 第一维中的一个 80³ BOX。每个正浮点 alpha 都可以独立产生 `F{alpha}_blobs.npz` 与 `F{alpha}_centered.npz`；alpha=2.0 的路径标签为 `F2`，alpha=0.5 的路径标签为 `F0p5`。

`hardmask` 是受体占据位置的 BOX 级布尔掩码；值为 `True` 的体素是受体原子所在位置。所有当前 producer 的配体概率都不乘 hardmask，也不在完整图融合后把受体位置置零。

### 1.2 文件格式与发布

- JSON 文件使用 UTF-8。
- NPZ 不得包含 `object` dtype，必须能由 `numpy.load(path, allow_pickle=False)` 读取。
- 正式 JSON 和 NPZ 先写同目录临时文件，写入成功后再原子替换正式路径；大型 NPZ 不做重复解压重读。
- NPZ 字段集合是精确集合；缺少字段或出现未声明字段都属于契约不一致。本文明确允许整组缺席的 Find P/A 字段除外。
- `_COMPLETE` 只供当前生产阶段默认跳过和外部任务编排使用。五个显式命令由调用者按阶段顺序启动；读取前一阶段 NPZ 时不重复检查其完成标记。

字段名中的 `offsets` 表示变长表边界数组。第 `i` 个对象对应半开区间 `[offsets[i],offsets[i+1])`；每个具体 offsets 切分哪些值表，会在相应文件字段表中逐一写明。

### 1.3 形状记号

| 记号 | 含义 |
| --- | --- |
| `D,H,W` | 完整图 Z、Y、X 三轴长度 |
| `N_occ` | 当前 PDB 的真实配体 occurrence 数；occurrence 指一个真实配体实例 |
| `N_blob` | 当前 F-alpha 阈值下的全部 26 邻域连通区域数 |
| `N_entry` | 当前 centered NPZ 的 80³ BOX 条目数 |
| `N_threshold` | 评估使用的双向覆盖阈值数 |
| `N_topk` | 评估使用的 top-K 设置数 |
| `L_*` | 相应变长值表的第一维总长度 |
| `C_*` | checkpoint 实际产生的特征宽度 |

NumPy 形状写成 `(N,3)`；JSON 数组使用“长度 3”描述。

### 1.4 缺失和空值

- 不存在的模态使用字段组整体缺席，不得用全零数组伪造。
- 存在模态但某个归档项没有值时，相应 offsets 段为空。
- 没有归档项时，长度为 `N_entry+1` 的 offsets 精确为 `[0]`。
- 完全没有成功载荷且无法确定体素特征宽度时，`voxel_final.shape == (0,0)`；不得猜测 48 或其他固定通道数。
- 没有 blob 或 centered 条目时仍发布字段齐全的空 NPZ；所有相应 offsets 精确为 `[0]`。

## 2. 完整图资产与几何

### 2.1 坐标

- 数组空间轴和离散体素索引使用 ZYX 顺序。
- 世界坐标和连续局部坐标使用 XYZ 顺序，长度单位为 Å。
- `origin_xyz` 和 `box_origin_world` 表示网格角点，不是第一个体素中心。
- `voxel_size_xyz` 和 `voxel_size_world` 使用 XYZ 顺序，单位为 Å/voxel。

完整图体素中心：

$$
world\_xyz = origin\_xyz + (index\_xyz + 0.5) \times voxel\_size\_xyz
$$

BOX 局部连续坐标：

$$
local\_xyz = (world\_xyz - box\_origin\_world) / voxel\_size\_xyz
$$

BOX 角点：

$$
box\_origin\_world = origin\_xyz + box\_start\_xyz \times voxel\_size\_xyz
$$

80³ BOX 的世界坐标中心：

$$
box\_origin\_world + 40 \times voxel\_size\_xyz
$$

合法 BOX 起点逐轴满足：

$$
0 \le box\_start\_axis \le full\_shape\_axis - 80
$$

训练和推理都读取真实 80³ 裁剪，不使用空间填充。

### 2.2 不重复保存的完整图资产

以下文件按 PDB 保存在数据根目录中。Stage1 产物引用它们，但不把完整数组复制到 centered NPZ。

| 文件 | 关键字段 | Stage1 用途 |
| --- | --- | --- |
| `density/{pdb_id}/exp.npy` + `exp.npz` | NPY 为 `float32 (1,D,H,W)` 实验密度；NPZ 为 `voxel_size`、`origin`、`canonical_shape_zyx` 等元数据 | 所有模型来源的实验密度和完整图几何 |
| `density/{pdb_id}/sim.npy` + `sim.npz` | NPY 为 `float32 (1,D,H,W)` 模拟密度；NPZ 为 `voxel_size`、`origin` 等元数据 | Find 额外使用的模拟密度；几何必须与实验密度一致 |
| `density/{pdb_id}/union_mask.npy` + `ligand_area.npz` | NPY 为 `bool (1,D,H,W)` 并集；NPZ 为 `grid_shape_zyx`、`mask_{occurrence_id}` 等稀疏实例与元数据 | 训练目标、校准真值和候选组件与真实配体的交集 |
| `density/{pdb_id}/ligand_dist.npy` + `ligand_dist.npz` | NPY 为 `float16 (1,D,H,W)` 最近距离；NPZ 为几何和来源元数据 | 最近配体原子距离；训练时转换为 `1 / (1 + distance_Å)` |
| `parse/{pdb_id}/receptor_tokens.npz` | `coords`、49 维 `feat`、`is_backbone`、`res_type`、`atom_name` | Find 原子输入、受体辅助目标和 hardmask；模型内部把 `feat` 与 `is_backbone` 拼成 50 维运行时输入 |
| `labels/{pdb_id}/atom_labels.npz` | `binding_atom` | 与完整受体原子表对齐的结合区域标签 |

`union_mask.npy` 是 `bool (1,D,H,W)`；`True` 表示至少一个真实配体实例占据该体素，`False` 表示未占据。每个 `ligand_area.npz:mask_{occurrence_id}` 是整数 `(K_occ,3)` ZYX 稀疏坐标表。

`receptor_tokens.npz` 继续保存 `feat (N,49) float32` 与 `is_backbone (N,) bool` 两个独立数组，不修改上游 schema。Dataset 按同一原子行序切片后，把 `is_backbone` 转成 `float32 (N,1)` 并在模型输入边界拼到 `feat` 末尾，得到 50 维 `atom_feat`。Find centered 产物中的 `A_global_index` 指向 `receptor_tokens.npz` 第一维，用于原子身份追踪。

### 2.3 80³ BOX 的运行时物化

BOX 池和 centered 几何都不保存实际密度裁剪。Dataset 或推理运行时使用 `pdb_id + box_start_zyx` 从完整图现场裁出精确 `80×80×80` 数组。

centered 正式推理的 batch size 必须由配置显式提供，Python 不设默认值。训练同源 Collator 堆叠 dense V 输入并拼接变长 A 表；forward 后，V 网格按 batch 第 0 维拆分，A 表按模型输出的 `atom_counts` 连续段拆分，P 表按 `anchor_batch_index` 归属拆分。执行批量不得改变 centered 条目顺序、`centered_box_index`、`source_blob_index` 或 offsets/value 对齐。

- 三个 Find 模型来源按固定顺序构造全部 56 个密度通道；通道来自 `exp`、`sim`、`diff`、`posdiff` 四种基础运算，两个归一化方案和七个后处理方案。
- `unet_c1` 的密度输入精确为单通道 `exp_clipnorm_nopost`。
- Find 从完整受体表选择 80³ 核心及其外侧 8 Å 缓冲范围内的原子，并保留这些原子在完整受体表中的编号；`unet_c1` 不构造原子输入表。
- 需要监督时，Dataset 现场构造配体体素标签、配体区域并集、蛋白主链类别、核酸主链类别、配体反距离和受体原子结合标签；这些训练数组不写入 BOX 池或 centered 推理产物。

## 3. 冻结数据准备产物

数据准备产物位于调用方指定的准备目录，不属于 `stage1_outputs`。

### 3.1 冻结数据划分

第三版正式产物位于 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/split`，生产入口由 Pocket_Plus 的 `ops/stage1_data_preparation/freeze_split.py` 和 `run/fetch_and_freeze_split.sh` 提供。输出：

```text
<数据划分目录>/
├── train.json
├── validation.json
├── calibration.json
├── held_out.json
├── quarantine_missing_release.json
├── pdb_audit.jsonl
├── emdb_release_dates.jsonl
├── config.json
├── summary.json
└── _COMPLETE
```

五个数据划分文件都是 JSON 对象数组。每项保留 Stage G `candidates.pending.jsonl` 的原始字段，并且至少包含 `pdb_id: str`。同一个 PDB 不得跨 train、validation、calibration；held-out 与缺日期隔离集合也不进入前三者。

选择规则：

- 一个 PDB 对应多个 EMDB 时，以 `raw/pair_list.jsonl` 所列 EMDB 的最早非空 `admin.key_dates.map_release` 为首次发布时间。
- 首次发布时间严格早于 `2026-01-01` 才能进入非留出候选；等于或晚于该日期的 PDB 连同全部 Stage G 候选进入 `held_out.json`。缺少首次发布时间的 PDB 进入 `quarantine_missing_release.json`。
- 非留出候选必须至少有一条记录同时满足 `map_resolution < 4.0` 与 `cc_contour > 0.65`；边界值不通过。进入 train、validation 或 calibration 的清单只保留逐条满足这两个质量条件的记录。
- 质量通过后还必须具备四个迁移后 NPY、四个元数据 NPZ、`receptor_tokens.npz` 与 `atom_labels.npz`，并通过 dtype、shape、几何和原子标签长度核对；完整图 Z、Y、X 三轴还必须均不小于 80。
- 合格 PDB 按 `sha256(3407|eval|pdb_id)` 升序排列；前 200 个属于 validation，随后 100 个属于 calibration，其余全部属于 train。
- `pdb_audit.jsonl` 为每个来源 PDB 保存首次发布时间、最终状态、完整图形状和失败细节；`emdb_release_dates.jsonl` 是可续传的权威日期缓存。

命令参数 `--seed` 的默认值是 3407。`config.json` 字段：

| 字段 | 类型与含义 |
| --- | --- |
| `schema_version` | `int`，当前为 `1` |
| `release_cutoff` | `str`，当前为 `2026-01-01` |
| `release_rule` | `str`，最早 EMDB map release 严格早于界线才进入非留出候选 |
| `map_resolution_exclusive_max` | `float`，当前为 `4.0` |
| `cc_contour_exclusive_min` | `float`，当前为 `0.65` |
| `minimum_grid_shape_zyx` | 长度 3 的 `int` 数组，当前为 `[80,80,80]` |
| `validation_pdb_count` | `int`，请求的 validation PDB 数 |
| `calibration_pdb_count` | `int`，请求的 calibration PDB 数 |
| `seed` | `int`，当前为 `3407` |
| `eval_assignment` | `str`，当前为 `"sha256(seed|eval|pdb_id) ascending; first 200 validation, next 100 calibration"` |
| `candidates_path`、`pair_list_path`、`release_cache_path` | `str`，本次冻结读取的三个正式输入路径 |

正式 `summary.json` 记录 22,251 个来源 PDB 和 662,078 条来源候选。审计状态为：eligible 14,017、held_out 2,497、missing_release_date 357、quality_rejected 3,718、invalid 1,655、missing_file 4、short_map 3。正式划分为 train 13,717 PDB/451,505 条候选，validation 200/6,104，calibration 100/2,426，held-out 2,497/81,922，缺日期隔离 357/11,327。

`_COMPLETE` 是零字节文件，在其他文件全部成功发布后最后创建。

### 3.2 训练预定位 BOX 池

第三版正式产物位于 `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/box_pool`，生产入口由 Pocket_Plus 的 `ops/stage1_data_preparation/build_box_pool_3.py`、`run/build_box_pool_3.sh` 和 `run/finalize_box_pool_3.sh` 提供。输出：

```text
<BOX池目录>/
├── train/{pdb_id}.npz
├── validation/{pdb_id}.npz
├── manifest.json
├── validation_selection.npz
├── validation_selection_pdb_centric.npz
├── config.json
├── summary.json
└── _COMPLETE
```

每个 PDB NPZ 的精确字段：

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `pdb_id` | Unicode 标量 | 当前 PDB 身份 |
| `occurrence_id` | `int32 (N_occ,)` | 真实配体实例编号 |
| `center_start_zyx` | `int32 (N_occ,3)` | 与 `occurrence_id` 同序的兼容字段；第三版请求比例为 0，不抽取 center 条目 |
| `bias_start_zyx` | `int32 (N_occ,30,3)` | 每个真实配体实例的 30 个偏置正样本 BOX 起点；包含经验半径偏移和额外 0–3 Å 独立漂移 |
| `context_start_zyx` | `int32 (N_context,3)` | 与真实配体实例无关的受体上下文 BOX 起点 |

上下文 BOX 从逐轴合法的整数起点均匀采样，不设置核心受体重原子数量门槛，也不按配体位置过滤。每个 PDB 目标为 500 个上下文 BOX，最多尝试 3000 次，因此构建器允许 `N_context` 为 0 到 500；本次正式 train 与 validation 的每个 PDB 都有超过 25 个 context 候选。

不同 bias 随机样本解析到同一合法整数 BOX 起点时，重复起点原样保留。

V3 逐 PDB NPZ 只定义几何候选，不再隐含活动训练比例。当前训练参数为 `pdb_foreground_box_num=25`、`pdb_foreground_fraction_target=0.5` 和 `pdb_occurrence_foreground_box_cap=5`；foreground 在这三个字段中专指 bias BOX，context 仍是独立角色。设一个 PDB 含 `O` 个 occurrence，则一个 epoch 的实际 bias 数量为 `min(25, 5O)`。这些 bias 先按整除结果分给全部 occurrence，余数沿由 seed 与该 PDB 在 manifest 中的顺序编号确定的稳定排列逐 epoch 轮转；每个 occurrence 再从自己的 30 个 bias 候选中无放回选择。context 目标数量为 `round(25 × (1 - 0.5) / 0.5) = 25`，不随实际 bias 数量不足而减少，并从该 PDB 的 context 候选中无放回选择。center 起点只为兼容 V3 字段而保留，不进入活动请求。

validation 使用冻结请求，不保存增强后的数组。train 的随机 90° 旋转会同步旋转密度、监督图和 Find 原子坐标；奇数次四分之一转交换空间轴时，还会交换 `voxel_size_world` 的对应 XYZ 尺度，并重新计算 BOX 中心和原子世界坐标，不能用“体素尺寸近似 1 Å”代替几何变换。

`manifest.json`：

- `schema_version: int`，当前为 `1`。
- `splits` 只含 `train` 和 `validation`。
- 每个数据划分是对象数组；每项精确包含 `pdb_id: str` 与相对 BOX 池根目录的 POSIX 风格 `path: str`。

原 `validation_selection.npz` 与当前 `validation_selection_pdb_centric.npz` 共用以下索引字段：

| 字段 | dtype 与形状 | 索引目标 |
| --- | --- | --- |
| `validation_pdb_id` | 固定宽度 bytes `(N_pdb,)` | validation PDB 身份表 |
| `center_pdb_index` | `int32 (N_center,)` | 索引 `validation_pdb_id` 第一维 |
| `center_occurrence_id` | `int32 (N_center,)` | 在相应 PDB 的 `occurrence_id` 中按值查找 |
| `bias_pdb_index` | `int32 (N_bias,)` | 索引 `validation_pdb_id` 第一维 |
| `bias_occurrence_id` | `int32 (N_bias,)` | 在相应 PDB 的 `occurrence_id` 中按值查找 |
| `bias_candidate_index` | `int16 (N_bias,)` | 索引相应真实配体实例的 `bias_start_zyx` 第二维，范围 `0..29` |
| `context_pdb_index` | `int32 (N_context_selected,)` | 索引 `validation_pdb_id` 第一维 |
| `context_candidate_index` | `int32 (N_context_selected,)` | 索引相应 PDB 的 `context_start_zyx` 第一维 |

`validation_selection_pdb_centric.npz` 冻结相同 seed 3407 下的 validation epoch 0，并在上述八类索引字段之外精确增加三个标量：

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `pdb_foreground_box_num` | `int32 ()` | 每个 PDB 的目标 bias BOX 数量，固定为 25 |
| `pdb_foreground_fraction_target` | `float64 ()` | bias 占目标 bias 与 context 总数的比例，固定为 0.5 |
| `pdb_occurrence_foreground_box_cap` | `int32 ()` | 单个 occurrence 每个 epoch 的 bias BOX 数量上限，固定为 5 |

该文件不复制 BOX 起点，不增加 schema、策略字符串、冗余计数或完成标记。它由 Pocket_Plus 的硬编码脚本 `ops/stage1_data_preparation/freeze_validation_selection_pdb_centric.py` 一次性生成；脚本没有参数化命令行，准确运行命令为 `python -m ops.stage1_data_preparation.freeze_validation_selection_pdb_centric`。原 `validation_selection.npz` 不改写，保留为历史请求产物。

V3 候选池构建命令的 `--seed` 默认值是 3407。`config.json` 保存以下历史构建规则，不再作为活动 Dataset 的采样参数来源：

- `box_shape_zyx=[80,80,80]`
- `bias_candidates_per_occurrence=30`
- `bias_radius_formula="R=(3*K_occ/(4*pi))**(1/3)"`
- `extra_bias_drift_max_angstrom=3.0`
- `extra_bias_drift_length_sampling="uniform_0_to_max_angstrom"`
- `context_generator` 中的均匀合法起点、目标数 500、最大尝试数 3000、核心受体重原子下限 0、`ligand_filter=false`
- `occurrence_cap_per_pdb_per_epoch=50`
- `entry_ratio={"center":0,"bias":5,"context":5}`
- `validation_entry_ratio={"center":0,"bias":1,"context":1}`
- `seed: int`
- `seed_rule="sha256(base_seed|split_name|pdb_id) first_uint64"`

`summary.json` 保存：

- `seed: int`
- train 的 `requested_pdb`、`published_pdb`、`zero_context_pdb_count`
- validation 的 `requested_pdb`、`published_pdb`、`zero_context_pdb_count`
- `validation_selection` 的 `pdb_count`、`center_count`、`bias_count`、`context_count`
- `manifest` 的 train 与 validation 文件数

V3 候选池的正式结果为 train 13,717/13,717 PDB、validation 200/200 PDB，两个集合的 `zero_context_pdb_count` 都为 0。2026-08-18 按历史 `0:1:1` 规则覆盖发布的 `validation_selection.npz` 有 3,305 个 bias、3,305 个 context 和 0 个 center 条目；该文件不再是活动验证入口。`_COMPLETE` 是 V3 候选池完整发布时最后创建的零字节文件，新 selection 不改变它。

### 3.3 训练消费契约

当前活动 Dataset 不提供请求比例截断参数。训练按 manifest 和三个 PDB 中心采样参数动态生成每个 epoch 的请求，不把训练选择落盘；验证完整展开 `validation_selection_pdb_centric.npz`，不重新抽样。原 `config.json::entry_ratio`、`validation_entry_ratio` 与 `validation_selection.npz` 只说明 V3 几何池的历史构建，不参与当前请求生成。

四个完整体数组通过只读内存映射现场裁出 80³：

| 完整图文件 | dtype 与形状 | 同目录元数据来源 |
| --- | --- | --- |
| `exp.npy` | `float32 (1,D,H,W)` | `exp.npz` |
| `sim.npy` | `float32 (1,D,H,W)` | `sim.npz` |
| `union_mask.npy` | `bool (1,D,H,W)` | `ligand_area.npz` |
| `ligand_dist.npy` | `float16 (1,D,H,W)` | `ligand_dist.npz` |

Dataset 只复制实际裁块，不因缓存计量或数值检查读取完整体数组。实际密度裁块必须有限，距离裁块必须有限且非负，union mask 保持 bool。完整图形状、体素尺寸、世界坐标原点和 schema 来自小型 NPZ；完整数组的迁移一致性由 `reports/runs/stage1_npy_migration_20260817_v1/_COMPLETE` 及其摘要负责。

受体资产不改写：`receptor_tokens.npz:feat` 保持 `float32 (N_receptor,49)`，`is_backbone` 保持 `bool (N_receptor,)`。Dataset/Collator 分别传递两个字段；模型输入边界仅在当前模型期望 50 维时，把主链标志转为 `float32 (N_receptor,1)` 并拼到特征末尾。旧 49 维模型继续直接使用基础特征。

DataLoader 的正式口径是 `prefetch_factor=4`、`pin_memory=true`、`persistent_workers=false`。`Find_1.sh` 的双卡任务申请 64 CPU，每个 rank 使用 30 workers；其他当前 Stage1 入口每个 rank 使用 16 workers。禁止把 worker 设为常驻，因为每个 epoch 的动态训练请求由主进程重新生成。

## 4. Stage1 V3 正式输出目录与状态

### 4.1 固定目录与动态 F-alpha 文件名

producer 级 calibration 目录：

```text
<output_root>/<producer>/calibration/
├── F{alpha}_semantic.json
├── F{alpha}_semantic_scan.npz
├── F{alpha}_basic.json
└── F{alpha}_gaussian.json
```

四个文件相互独立。一个推理版本可以只拟合语义阈值、只调整 basic、只调整 Gaussian，或逐步补齐；这些文件不保存 checkpoint、resolved config、代码摘要或哈希。

逐 PDB 目录：

```text
<output_root>/<producer>/<split>/<pdb_id>/
├── probability/
│   ├── probability_map.npz
│   └── geometry.json
├── blobs/F{alpha}_blobs.npz
├── centered/F{alpha}_centered.npz
├── evaluation/<evaluation-name>.npz
└── status/
    ├── probability/
    │   ├── performance.json
    │   └── _COMPLETE
    ├── F{alpha}_blobs/_COMPLETE
    └── F{alpha}_centered/
        ├── performance.json
        ├── _COMPLETE
        └── _BLOB_EXCEED
```

`F{alpha}` 使用 Python float 的最短可往返十进制：整数不保留 `.0`，小数点改为 `p`。例如 2.0、0.5、1.5 分别写成 `F2`、`F0p5`、`F1p5`；不同 Python float 不因六位格式化而碰撞。同一 PDB 目录可以共同复用 probability，并同时保存多个 alpha 的 blobs 与 centered。

数据划分级评估目录为 `<output_root>/<producer>/<split>/evaluation/`。每个评估名称同时保存 JSONL 和 metrics JSON；名称中的 `artifact` 为 `blobs` 或 `centered`，`score_mode` 为 `basic` 或 `gaussian`。

### 4.2 `_COMPLETE`

每个 PDB 角色完成标记是 UTF-8 JSON：

| 字段 | 类型与含义 |
| --- | --- |
| `output_role` | 字符串，对应 `probability`、动态 `F{alpha}_blobs` 或动态 `F{alpha}_centered` |
| `completed_at_utc` | 带时区 ISO 8601 字符串，表示正式 NPZ 已原子替换后的发布时间 |

默认生产命令遇到当前角色 `_COMPLETE` 就跳过该 PDB。`--overwrite` 只撤销并重跑当前阶段，不删除同一 PDB 的 probability、其他 alpha 或评估文件。完成标记不保存生产身份，程序不比较 checkpoint、配置、模型代码或摘要。

### 4.3 `_BLOB_EXCEED`

centered 阶段读取来源 blobs 后，立即检查 `blob_index` 第一维长度。长度严格大于全局常量 1000 时，不构造 Dataset 请求、不进入 GPU，也不写 centered NPZ 或 centered `_COMPLETE`；只写 `status/F{alpha}_centered/_BLOB_EXCEED`：

| 字段 | 类型与含义 |
| --- | --- |
| `pdb_id` | 字符串，当前小写 PDB 标识 |
| `centered_role` | 字符串，例如 `F2_centered` |
| `source_blob_count` | 整数，来源 blobs 文件的总连通区域数 |
| `limit` | 整数，固定为 1000 |

该文件只解释本次 centered 缺失原因，不拥有覆盖、恢复、自动清理或独立完成状态。tune/evaluate 在原本读取完整 PDB 清单时，可以识别“centered 缺失且 `_BLOB_EXCEED` 存在”，在标准输出说明原因并跳过该 PDB；不得另建复杂跳过系统。

## 5. 完整图 probability 与动态 blobs

### 5.1 `probability/probability_map.npz`

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `probability_map` | `float32 (D,H,W)` | 完整图 ZYX 配体概率，不乘受体 hardmask |
| `origin_xyz` | `float32 (3,)` | 完整网格角点的世界 XYZ 坐标，单位 Å |
| `voxel_size_xyz` | `float32 (3,)` | 世界 XYZ 体素尺寸，单位 Å/voxel |

`probability/geometry.json` 精确字段为：`full_shape_zyx` 是长度 3 的整数列表；`origin_xyz` 与 `voxel_size_xyz` 是长度 3 的浮点数列表；`window_shape_zyx` 是固定 `[80,80,80]` 的整数列表；`stride_zyx` 是长度 3 的显式整数列表；`gaussian_sigma` 是浮点数；`window_count` 是整数。`status/probability/performance.json` 的 `wall_seconds`、`materialize_wait_seconds` 与 `fusion_wait_seconds` 均为浮点秒数；性能字段不得混入科学 NPZ。

### 5.2 `blobs/F{alpha}_blobs.npz`

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `blob_index` | `int32 (N_blob,)` | 当前文件内从 0 开始的稳定连续 blob 编号 |
| `voxel_offsets` | `int64 (N_blob+1,)` | 半开区间同步切分 `voxel_index_global_zyx` 与 `source_probability`；首值 0，末值 L_voxel |
| `voxel_index_global_zyx` | `int32 (L_voxel,3)` | 完整图 ZYX 体素索引 |
| `source_probability` | `float32 (L_voxel,)` | 与体素索引逐项对齐的完整图概率 |
| `source_probability_mean` | `float32 (N_blob,)` | 每个 blob 的正式平均概率和第一排序键 |
| `voxel_count` | `int32 (N_blob,)` | 每个 blob 的体素数 |
| `fits_centered_box` | `bool (N_blob,)` | blob 包围盒是否能由完整图内合法 80³ BOX 容纳 |
| `centered_box_start_zyx` | `int32 (N_blob,3)` | 可容纳时为选定 80³ BOX 的完整图 ZYX 起点；不可容纳时三个值均为 -1 |
| `source_threshold_value` | `float32 (1,)` | 当前 F-alpha 使用的包含端点概率阈值 |

连通区域使用 26 邻域。区域先按归档后的 float32 平均概率降序，再按区域最小完整图 C-order 线性索引升序。blobs 阶段保存阈值下全部区域，不应用 `min_voxels`，也不删除 `fits_centered_box=false` 的区域。

## 6. 动态 F-alpha centered

### 6.1 候选集合与选择边界

正常 centered 命令必须显式提供 `forward_min_voxels`。来源 blob 进入模型前向的条件为：

$$
fits\_centered\_box = True
\quad\land\quad
voxel\_count \ge forward\_min\_voxels
$$

选择参数 JSON 中的 `prefiltered_min_voxel` 与 `min_voxels` 只参与 `selected`，不能删除已前向候选，也不能改变 offsets。前者由 tune 命令在任何参数尝试前固定，后者从配置的搜索列表中选出；两者互不限制。所有 producer 都执行完整 forward，并保存 `voxel_final`、auxiliary、V-centered 48³ 几何、实验密度裁块、模拟密度裁块与完整图概率裁块；`Find_*` 另外保存 A/P 表。alpha 不决定字段集合。

### 6.2 共同字段

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `centered_box_index` | `int32 (N_entry,)` | 当前文件内从 0 开始的连续 centered 编号 |
| `source_blob_index` | `int32 (N_entry,)` | 指向同 alpha blobs 文件 `blob_index` 第一维 |
| `box_start_zyx` | `int32 (N_entry,3)` | 80³ BOX 在完整图中的 ZYX 起点 |
| `box_shape_zyx` | `uint8 (N_entry,3)` | 每项固定为 `(80,80,80)` |
| `box_origin_world` | `float32 (N_entry,3)` | BOX 角点世界 XYZ 坐标，单位 Å |
| `voxel_size_world` | `float32 (N_entry,3)` | 世界 XYZ 体素尺寸，单位 Å/voxel |
| `source_probability_mean` | `float32 (N_entry,)` | 来源 blob 的完整图平均概率 |
| `source_threshold_value` | `float32 (N_entry,)` | 来源 blobs 文件的语义概率阈值 |
| `voxel_offsets` | `int64 (N_entry+1,)` | 同步切分 `voxel_index_local_zyx`、`source_probability`、`centered_probability` 和 `voxel_final`；首值 0，末值 L_voxel |
| `voxel_index_local_zyx` | `int16 (L_voxel,3)` | 来源 blob 体素在 80³ BOX 内的 ZYX 索引 |
| `source_probability` | `float32 (L_voxel,)` | 与来源局部体素逐项对齐的完整图概率 |
| `centered_probability` | `float32 (L_voxel,)` | 同一体素的 centered 重算概率 |
| `voxel_final` | `float16 (L_voxel,C_voxel)` | 与来源局部体素逐项对齐的最终 V 学习特征 |
| `voxel_aux_offsets` | `int64 (N_entry+1,)` | 同步切分 `voxel_aux_index_local_zyx` 与 `voxel_aux_probability`；首值 0，末值 L_aux |
| `voxel_aux_index_local_zyx` | `int16 (L_aux,3)` | hardmask 内辅助受体体素的 BOX-local ZYX 索引 |
| `voxel_aux_probability` | `float32 (L_aux,)` | 与辅助受体体素逐项对齐的独立概率，不改变配体概率 |
| `v_centroid_local_zyx` | `float32 (N_entry,3)` | 来源 blob 的 BOX-local ZYX 整数体素下标算术平均，单位 voxel |
| `crop_start_local_zyx` | `int16 (N_entry,3)` | 48³ 裁块在 80³ BOX 内的 ZYX 起点 |
| `crop_center_offset_zyx` | `float32 (N_entry,3)` | 来源 blob 质心相对 48³ 裁块中心的 ZYX 偏移，单位 voxel |
| `crop_clipped_axis_mask` | `bool (N_entry,3)` | True 表示对应轴的裁块起点受 80³ 边界限制 |
| `experimental_density_48` | `float32 (N_entry,48,48,48)` | 实验密度裁块，后三轴按 ZYX 排列 |
| `simulated_density_48` | `float32 (N_entry,48,48,48)` | 模拟密度裁块，后三轴按 ZYX 排列 |
| `source_probability_48` | `float32 (N_entry,48,48,48)` | 完整图概率裁块，后三轴按 ZYX 排列 |
| `score` | `float32 (N_entry,)`，条件字段 | 只在提供选择参数或执行 score-only 后存在 |
| `selected` | `bool (N_entry,)`，条件字段 | 只与 `score` 同时存在；True 表示同时达到分数阈值、固定 `prefiltered_min_voxel` 和最终 `min_voxels`，三个门槛均包含端点 |

未评分 centered 不含 `score/selected`。score-only 只能增加或替换这两个字段；`centered_box_index`、`source_blob_index`、几何、概率、特征、offsets 和候选顺序必须逐元素保持。

### 6.3 Find A/P 扩展字段

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `A_offsets` | `int64 (N_entry+1,)` | 同步切分 `A_global_index`、`A_coord_local_xyz`、`A_coord_centered_world`、`A_probability` 与 `A_feat_L0/L1/L2/L3`；首值 0，末值 N_A |
| `A_global_index` | `int64 (N_A,)` | 指向 `receptor_tokens.npz` 第一维的原子编号 |
| `A_coord_local_xyz` | `float32 (N_A,3)` | A 原子的 BOX-local XYZ 体素坐标 |
| `A_coord_centered_world` | `float32 (N_A,3)` | A 原子相对 80³ BOX 世界中心的 XYZ 位移，单位 Å |
| `A_probability` | `float32 (N_A,)` | A 原子配体概率 |
| `A_feat_L0` | `float32 (N_A,50)` | 49 维 receptor token 与同原子 `is_backbone` 拼接结果 |
| `A_feat_L1/L2/L3` | `float16 (N_A,C_A*)` | 三层 A 学习特征，与 A 原子轴逐项对齐 |
| `P_offsets` | `int64 (N_entry+1,)` | 同步切分 `P_coord_local_xyz`、`P_probability` 与 `P_feat_L2/L3`；首值 0，末值 N_P |
| `P_coord_local_xyz` | `float32 (N_P,3)` | P 点的 BOX-local XYZ 体素坐标 |
| `P_probability` | `float32 (N_P,)` | P 点配体概率 |
| `P_feat_L2/L3` | `float16 (N_P,C_P*)` | 两层 P 学习特征，与 P 点轴逐项对齐 |

A 表只保留核心 80³ BOX 内且到来源 blob 最近体素中心不超过 10 Å 的原子。Gaussian 评分固定只使用 5 Å 内 A 原子。学习特征使用 float16；概率、几何、密度和 `A_feat_L0` 使用 float32。

### 6.4 centered 性能

`status/F{alpha}_centered/performance.json` 精确包含 `wall_seconds`、`materialize_wait_seconds`、`cpu_arrange_wait_seconds` 三个浮点秒数，以及 `batch_count`、`entry_count` 两个整数。

## 7. calibration 参数

### 7.1 `F{alpha}_semantic.json` 与扫描 NPZ

JSON 精确字段：

| 字段 | 类型与含义 |
| --- | --- |
| `alpha` | 浮点数，当前语义 F-alpha 参数 |
| `denominator` | 整数，概率阈值网格分母 |
| `positive_voxel_count` | 整数，calibration 全集真实配体体素数 |
| `negative_voxel_count` | 整数，calibration 全集真实背景体素数 |
| `threshold_grid_index` | 整数，首个达到最大 micro F-alpha 的网格编号 |
| `threshold_value` | 浮点数，`threshold_grid_index/denominator` |
| `micro_f_beta` | 浮点数，获胜阈值的 micro F-alpha |
| `tp/fp/fn` | 整数，获胜阈值的跨 PDB 体素计数 |

扫描 NPZ 精确包含 `denominator` int32 标量、`alpha` float64 标量、`threshold_grid_index` int32 `(denominator+1,)`、`f_beta_curve` float64 `(denominator+1,)` 和同形 int64 `tp/fp/fn`。概率先量化为 `floor(clip(p,0,1)*denominator)`；`np.argmax` 在并列时选择最低网格编号。

每个阈值的指标为：

$$
F_{\alpha}=\frac{(1+\alpha^2)TP}{(1+\alpha^2)TP+\alpha^2 FN+FP}
$$

当 alpha 大于 1 时，漏检 FN 的权重高于误检 FP，因此相对偏重召回。

### 7.2 `F{alpha}_basic.json` 与 `F{alpha}_gaussian.json`

| 字段 | 类型与含义 |
| --- | --- |
| `alpha` | 浮点数，文件标签对应的语义 F-alpha 参数 |
| `objective` | 浮点数，最终 semantic、coverage@0.3 与 one-to-one@0.3 三项 micro F-beta 之和 |
| `objective_beta` | 浮点数，上述三项目标共同使用的 beta；与 alpha 独立 |
| `score_mode` | 字符串，`basic` 或 `gaussian` |
| `score_parameters` | JSON 对象；basic 为空对象，Gaussian 含三个下述浮点字段 |
| `score_threshold` | 浮点数，包含端点的候选分数下限 |
| `prefiltered_min_voxel` | 整数，tune 开始前固定的来源 blob 体素数下限；小于该值的候选在全部参数组合中保持未入选 |
| `min_voxels` | 整数，包含端点的选择来源体素数下限 |
| `stages` | JSON 对象，保存实际搜索阶段的最优参数和目标值 |

Gaussian `score_parameters` 精确包含 `tau_angstrom`、`lambda_positive` 和 `lambda_negative`。basic 分数为 `source_probability_mean`。Gaussian 分数为：

$$
s = \bar{p}_{blob} + \lambda_{+}\sum_i w_i p_i - \lambda_{-}\sum_i w_i(1-p_i),
\qquad
w_i = \exp\left(-\frac{d_i^2}{2\tau^2}\right)
$$

$d_i$ 是 A 原子到同候选来源 blob 最近体素中心的世界距离，单位 Å；仅 $d_i\le 5$ Å 的原子参与求和。basic 调参事实包含全部 blobs，包括 `fits_centered_box=false` 的区域；Gaussian 调参事实使用已经完成 forward 的 centered 候选。两种模式都先应用显式 `prefiltered_min_voxel`：候选及其所属 PDB 不被删除，但体素数不足的候选在所有参数组合中固定为未入选，因此真实 occurrence 仍可贡献 FN。

basic 按预过滤合格候选实际出现的 float32 来源平均概率降序扫描，只在目标值严格提升时替换阈值；非空候选的最佳目标仍为 0 时，保留高于最高分的空选择阈值。basic 的 `stages.score_threshold` 含 `objective` 与 `score_threshold`，`stages.min_voxels` 含 `objective` 与 `min_voxels`。Gaussian 的 `stages.coarse` 与 `stages.refined` 都含 `objective`、`tau_angstrom`、`lambda_positive`、`lambda_negative` 和 `score_threshold`；`stages.min_voxels` 同样只含 `objective` 与 `min_voxels`。最终 `min_voxels` 仍扫描完整配置列表，不要求大于或等于 `prefiltered_min_voxel`；score-only 与 evaluate 同时应用两个独立门槛。

## 8. 评估事实与汇总

### 8.1 每 PDB 评估 NPZ

`evaluate` 命令必须显式提供 `evaluation_name`，并在两种候选范围中选择一种：

- 参数过滤：提供选择 JSON，按 basic 或 Gaussian 参数重算 `score`，同时应用 `score_threshold`、`prefiltered_min_voxel` 和 `min_voxels`，只有 `selected=true` 的候选进入正式指标。
- 全候选：不执行 basic 或 Gaussian 二次打分，以 `source_probability_mean` 排序，并把当前 blobs 或 centered 产物中全部候选的 `selected` 设为 True。blobs 模式纳入 `F{alpha}_blobs.npz` 的全部连通区域；centered 模式只纳入已经写入 `F{alpha}_centered.npz` 的候选，不补回未通过 `forward_min_voxels`、80³ 容纳条件或 `_BLOB_EXCEED` 的 blobs。

显式名称直接决定 `evaluation/<evaluation-name>.npz`。不同评分参数或全候选对照使用不同名称，即可在同一 PDB 目录并存；程序不从参数内容生成摘要或身份标识。

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `coverage_thresholds` | `float32 (N_threshold,)` | 双向覆盖阈值轴 |
| `topk_values` | `int32 (N_topk,)` | top-K 数量轴 |
| `occurrence_id` | `int32 (N_occ,)` | 真实 ligand occurrence 标识轴 |
| `source_blob_index` | `int32 (N_pred,)` | 按分数稳定降序的来源 blob 编号 |
| `candidate_score` | `float32 (N_pred,)` | 与候选轴对齐；参数过滤模式保存重算分数，全候选模式保存 `source_probability_mean` |
| `candidate_selected` | `bool (N_pred,)` | 与候选轴对齐；参数过滤模式表示是否达到三个门槛，全候选模式全部为 True |
| `intersections` | `int64 (N_pred,N_occ)` | 每对候选与 occurrence 的体素交集数 |
| `pred_sizes` | `int64 (N_pred,)` | 每个候选的来源体素数 |
| `gt_sizes` | `int64 (N_occ,)` | 每个 occurrence 的体素数 |
| `candidate_semantic_tp` | `int64 (N_pred,)` | 每个候选与真实 occurrence 并集的体素交集数 |
| `semantic_tp/fp/fn` | `int64` 标量 | 已选候选体素并集的语义计数 |
| `coverage_pred_hit_mask` | `bool (N_threshold,N_pred)` | 每个完整候选是否双向覆盖至少一个 occurrence，与 selected 无关 |
| `coverage_gt_hit_mask` | `bool (N_threshold,N_occ)` | 每个 occurrence 是否被至少一个已选候选双向覆盖 |
| `one_to_one_match_offsets` | `int64 (N_threshold+1,)` | 按阈值同步切分 `one_to_one_match_pred_index` 与 `one_to_one_match_gt_index`；首值 0，末值 L_match |
| `one_to_one_match_pred_index` | `int32 (L_match,)` | 指向分数排序后完整候选轴 |
| `one_to_one_match_gt_index` | `int32 (L_match,)` | 与前项逐项对齐的 occurrence 轴下标 |
| `topk_winning_candidate_rank` | `int32 (N_topk,N_threshold)` | 已选候选序列中首个获胜名次；未命中为 -1 |
| `topk_winning_occurrence_index` | `int32 (N_topk,N_threshold)` | 与获胜名次对齐的 occurrence 轴下标；未命中为 -1 |

### 8.2 数据划分汇总

`evaluation/<evaluation-name>.jsonl` 每个已评估 PDB 保存 `pdb_id` 加指标映射；`evaluation/<evaluation-name>.metrics.json` 保存相同公式的跨 PDB 汇总。两者与逐 PDB NPZ 使用同一个显式名称。固定键是 `pdb_count`、`semantic_tp`、`semantic_fp`、`semantic_fn`、`semantic_micro_f1`、`semantic_micro_f2`、`semantic_macro_f1`、`semantic_macro_f2` 与 `topk_eligible_pdb_count`。每个覆盖阈值标签 `{t}` 生成 `coverage_micro_precision_{t}`、`coverage_micro_recall_{t}`、`coverage_micro_f1_{t}`、`coverage_micro_f2_{t}`、`coverage_macro_f1_{t}`、`coverage_macro_f2_{t}`，以及同样六个 `one_to_one_*_{t}` 键。每个 top-K 值 `{k}` 与阈值标签 `{t}` 生成 `top{k}_success_count_{t}` 和 `top{k}_success_ratio_{t}`。阈值标签把小数点改为 `p`，例如 0.3 写成 `0p3`；任一分母为零时保存 0.0。

blobs 评估使用完整图稀疏坐标，centered 评估使用 `box_start_zyx + voxel_index_local_zyx` 恢复完整图坐标。参数过滤模式的有效组合是 blobs+basic、centered+basic 和 Find centered+Gaussian；Gaussian 需要 centered A 原子字段，不能用于 blobs。全候选模式可用于 blobs 或 centered。所有组合使用相同交集和指标公式。

## 9. 正式命令、分片与并发

唯一 shell 入口是 Pocket Plus `训练与运行/sh/infer/stage1_v3.sh`。正式子命令为 `probability`、`blobs`、`centered`、`tune` 和 `evaluate`。PDB 清单是顶层字符串列表 JSON。evaluate 必须显式提供 `--evaluation-name`，并在 `--selection-parameters` 与 `--all-candidates` 之间二选一。

probability、显式阈值 blobs 与 centered 提供分片时，程序以固定 seed 3407 打乱完整列表，再取 `[shard_index::shard_count]`；`shard_index` 从 0 开始。相同 JSON 和两个分片参数必须得到相同子序列。语义拟合、tune 与 evaluate 不分片。

完整图 `stride_zyx` 由 YAML 显式提供，Python 不设默认值；当前正式配置为 `[30,30,30]`。完整图内部重叠 CPU 请求物化、GPU 前向、异步 D2H 与有序融合。centered 内部重叠 CPU 请求物化、完整 GPU forward、异步 D2H 与 CPU 字段整理。跨 PDB 时，NPZ 打包和压缩与下一个 PDB 的 GPU 前向重叠；pending 队列限制尚未发布的大数组数量。

## 10. 跨文件对齐与冷读验收

### 10.1 跨文件对齐

- probability 到 blobs：`voxel_index_global_zyx` 直接索引 `probability_map`；`source_probability` 等于这些位置的 probability。
- blobs 到 centered：`source_blob_index` 指向同 alpha blobs 的 `blob_index`；`voxel_offsets` 分段对应同一来源 blob。
- centered 局部坐标到完整图：`global_zyx = box_start_zyx + voxel_index_local_zyx`。
- Find A 身份：`A_global_index` 指向 `receptor_tokens.npz` 原子轴；`A_feat_L0` 前 49 维来自同原子 `feat`，最后一维来自 `is_backbone`。
- centered 到选择：`score/selected` 与 `centered_box_index` 第一维逐项对齐；score-only 不改变其他字段。
- 候选到评估：评估 `source_blob_index` 先按 score 稳定降序；`one_to_one_match_pred_index` 指向该排序后的完整候选轴，`topk_winning_candidate_rank` 保存已选候选序列中的获胜名次。

### 10.2 冷读验收

1. 任意 alpha 的 probability、blobs、centered 路径和字段能由本文唯一确定。
2. `F2`、`F0p5`、`F1p5` 标签规则没有歧义。
3. `forward_min_voxels`、固定 `prefiltered_min_voxel` 与搜索所得 `min_voxels` 的职责分离；后两者只共同决定 `selected`，不改变前向候选集合，也互不限制。
4. 未评分 centered 不含 `score/selected`；score-only 只改变这两个字段。
5. `unet_*` 与 `Find_*` 的 centered 字段组可以由 producer 前缀确定。
6. 来源 blob 数大于 1000 时只有 `_BLOB_EXCEED`，没有 centered `_COMPLETE` 或额外状态机。
7. basic tune 事实包含 `fits_centered_box=false` 的 blobs，Gaussian tune 事实只使用已前向 centered；两种模式在参数搜索前应用同一个显式 `prefiltered_min_voxel`。
8. 语义、basic、Gaussian calibration 文件互相独立且不含 checkpoint 或哈希。
9. probability、blobs、centered 的 `_COMPLETE` 只控制同阶段默认跳过；`--overwrite` 不扩散到其他阶段。
10. 分片使用固定 seed 3407 和 `[index::count]`，语义拟合、tune、evaluate 使用完整清单。

## 11. 契约边界

本文负责定义训练预定位池、Stage1 推理产物路径、字段、shape、dtype、坐标、offsets、选择语义和完成状态。本文不负责定义网络结构、训练 loss、Slurm 资源或 Matcher batch 装配。

Matcher 消费调用者选定的 `F{alpha}_centered.npz`。Matcher 可以自行决定是否使用 `selected`，但必须按 `centered_box_index`、`source_blob_index` 和 offsets 读取候选。基础便捷推理可以直接消费 `F{alpha}_blobs.npz`，不要求先生成 centered。
