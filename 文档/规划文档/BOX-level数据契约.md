# AdaLigand BOX 级数据契约

本文定义 AdaLigand Stage1 训练预定位、完整图概率、阈值校准、组件森林、组件谱系组、三类居中 BOX、Selector 分数和最终选择结果的磁盘契约。本文面向产物的生产者与消费者；只看本文，读者应能确定正式文件、字段、形状、坐标、空值、索引目标、完成状态和跨文件对齐关系。

Pocket Plus 仓库的 `src/artifacts/readme.md` 覆盖相同产物，并额外说明每个产物的完整生产命令、嵌套 JSON 字段和程序化校验入口。两份文档不得对同一文件给出不同定义。

## 1. 范围、术语与共同规则

### 1.1 三个身份轴

- Stage1 模型来源：对应命令参数 `--producer`，只允许 `Find_0`、`Find_1`、`Find_2`、`unet_c1`。
- 数据划分：对应命令参数 `--split`，正式推理只允许 `calibration`、`validation`、`train`。
- PDB 身份：对应 `pdb_id`，正式值为小写且非空；同一清单不得出现重复身份。

三个 Find 模型来源使用体素模态 V、点模态 P 和原子模态 A；`unet_c1` 只使用体素模态 V。本文保留目录术语 `centered`，表示为一个来源组件解析合法 80³ BOX 并在该 BOX 中重新执行模型。

“组件”表示在一个冻结概率阈值上得到的 26 邻域连通体素集合。“组件谱系组”保留字段缩写 CLG，表示从一个合格的 `t_F1` 组件沿冻结阈值谱系扩展得到的一组候选组件。“归档项”表示 centered NPZ 第一维中的一个 BOX。

`hardmask` 是受体占据位置的完整图布尔掩码；值为 `True` 的体素是受体原子所在位置。三个 Find 模型来源在完整图融合后把这些位置的配体概率置零。

### 1.2 文件格式与发布

- JSON 文件使用 UTF-8。
- NPZ 不得包含 `object` dtype，必须能由 `numpy.load(path, allow_pickle=False)` 读取。
- 正式 JSON 和 NPZ 先写临时文件，重读并校验后，再原子替换正式路径。
- NPZ 字段集合是精确集合；缺少字段或出现未声明字段都属于契约不一致。本文明确允许整组缺席的 Find P/A 字段除外。
- 文件存在不代表角色完成。PDB 级消费者还必须检查角色完成标记和异常状态。

字段名中的 `offsets` 表示变长表边界数组。第 `i` 个对象对应半开区间 `[offsets[i],offsets[i+1])`；每个具体 offsets 切分哪些值表，会在相应文件字段表中逐一写明。

### 1.3 形状记号

| 记号 | 含义 |
| --- | --- |
| `D,H,W` | 完整图 Z、Y、X 三轴长度 |
| `N_occ` | 当前 PDB 的真实配体 occurrence 数；occurrence 指一个真实配体实例 |
| `N_node` | 组件森林节点数 |
| `N_CLG` | 组件谱系组数 |
| `N_candidate` | 全部组件谱系组中的候选组件总数 |
| `N_entry` | centered NPZ 的归档项数 |
| `N_success` | Selected 归档中精修成功的归档项数 |
| `L_*` | 相应变长值表的第一维总长度 |
| `C_*` | checkpoint 实际产生的特征宽度 |

NumPy 形状写成 `(N,3)`；JSON 数组使用“长度 3”描述。

### 1.4 缺失和空值

- 不存在的模态使用字段组整体缺席，不得用全零数组伪造。
- 存在模态但某个归档项没有值时，相应 offsets 段为空。
- 没有归档项时，长度为 `N_entry+1` 的 offsets 精确为 `[0]`。
- 完全没有成功载荷且无法确定体素特征宽度时，`voxel_final.shape == (0,0)`；不得猜测 48 或其他固定通道数。
- 零 CLG PDB 仍可发布字段齐全的空 `scores.npz`，其中 `candidate_offsets == [0]`。

## 2. 完整图资产与几何

### 2.1 坐标

- 数组空间轴和离散体素索引使用 ZYX 顺序。
- 世界坐标和连续局部坐标使用 XYZ 顺序，长度单位为 Å。
- `origin_xyz` 和 `box_origin_world` 表示网格角点，不是第一个体素中心。
- `voxel_size_xyz` 和 `voxel_size_world` 使用 XYZ 顺序，单位为 Å/voxel。

完整图体素中心：

`world_xyz = origin_xyz + (index_xyz + 0.5) * voxel_size_xyz`

BOX 局部连续坐标：

`local_xyz = (world_xyz - box_origin_world) / voxel_size_xyz`

BOX 角点：

`box_origin_world = origin_xyz + box_start_xyz * voxel_size_xyz`

80³ BOX 的世界坐标中心：

`box_origin_world + 40 * voxel_size_xyz`

合法 BOX 起点逐轴满足：

`0 <= box_start_axis <= full_shape_axis - 80`

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

centered 正式推理默认把 12 个有序 BOX 放入同一次完整 wrapper forward，显存受限时可以由运行命令下调。训练同源 Collator 堆叠 dense V 输入并拼接变长 A 表；forward 后，V 网格按 batch 第 0 维拆分，A 表按模型输出的 `atom_counts` 连续段拆分，P 表按 `anchor_batch_index` 归属拆分。执行批量不得改变归档项顺序、`centered_box_index`、来源身份或 offsets/value 对齐。

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

上下文 BOX 从逐轴合法的整数起点均匀采样，不设置核心受体重原子数量门槛，也不按配体位置过滤。每个 PDB 目标为 500 个上下文 BOX，最多尝试 3000 次，因此 `N_context` 可以是 0 到 500；本次正式 train 与 validation 均没有零 context PDB。

不同 bias 随机样本解析到同一合法整数 BOX 起点时，重复起点原样保留。

训练和验证请求采用 `center:bias:context = 0:5:5`。每个 PDB 每次最多选择 50 个 occurrence；center 起点只为兼容既有字段而保留，不进入请求。上下文池不足 5 项时可以放回采样；上下文池为空时不伪造请求。

validation 使用冻结请求，不保存增强后的数组。train 的随机 90° 旋转会同步旋转密度、监督图和 Find 原子坐标；奇数次四分之一转交换空间轴时，还会交换 `voxel_size_world` 的对应 XYZ 尺度，并重新计算 BOX 中心和原子世界坐标，不能用“体素尺寸近似 1 Å”代替几何变换。

`manifest.json`：

- `schema_version: int`，当前为 `1`。
- `splits` 只含 `train` 和 `validation`。
- 每个数据划分是对象数组；每项精确包含 `pdb_id: str` 与相对 BOX 池根目录的 POSIX 风格 `path: str`。

`validation_selection.npz`：

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

命令参数 `--seed` 的默认值是 3407。`config.json` 保存以下当前规则：

- `box_shape_zyx=[80,80,80]`
- `bias_candidates_per_occurrence=30`
- `bias_radius_formula="R=(3*K_occ/(4*pi))**(1/3)"`
- `extra_bias_drift_max_angstrom=3.0`
- `extra_bias_drift_length_sampling="uniform_0_to_max_angstrom"`
- `context_generator` 中的均匀合法起点、目标数 500、最大尝试数 3000、核心受体重原子下限 0、`ligand_filter=false`
- `occurrence_cap_per_pdb_per_epoch=50`
- `entry_ratio={"center":0,"bias":5,"context":5}`
- `seed: int`
- `seed_rule="sha256(base_seed|split_name|pdb_id) first_uint64"`

`summary.json` 保存：

- `seed: int`
- train 的 `requested_pdb`、`published_pdb`、`zero_context_pdb_count`
- validation 的 `requested_pdb`、`published_pdb`、`zero_context_pdb_count`
- `validation_selection` 的 `pdb_count`、`center_count`、`bias_count`、`context_count`
- `manifest` 的 train 与 validation 文件数

正式结果为 train 13,717/13,717 PDB、validation 200/200 PDB，两个集合的 `zero_context_pdb_count` 都为 0；固定验证选择有 16,525 个 bias、16,525 个 context 和 0 个 center 条目。上述计数全部是 `int`。`_COMPLETE` 是最后创建的零字节文件。

### 3.3 比例请求表

训练 Dataset 或验证入口第一次以 `box_sample_fraction < 1` 构造请求时，请求层可以创建：

```text
<BOX池目录>/train_selection_{fraction}_seed{seed}.npz
<BOX池目录>/validation_selection_{fraction}_seed{seed}.npz
```

`stage1_box_pool` 命令本身不创建这些文件；比例等于 1 时也不创建。

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `pdb_id` | Unicode `(N_req,)` | 请求所属 PDB |
| `box_start_zyx` | `int32 (N_req,3)` | 完整图离散 BOX 起点 |
| `role` | Unicode `(N_req,)` | `center`、`bias` 或 `context` |
| `occurrence_id` | `int32 (N_req,)` | 真实配体实例编号；不适用时为 `-1` |
| `candidate_index` | `int32 (N_req,)` | bias 或 context 候选编号；不适用时为 `-1` |
| `require_targets` | `bool (N_req,)` | `True` 表示 Dataset 必须构造监督字段 |
| `box_sample_fraction` | `float64` 标量 | 请求保留比例 |
| `request_seed` | `int64` 标量 | 抽样种子 |
| `selection_epoch` | `int64` 标量 | 固定为 `0` |
| `source_manifest_sha256` | Unicode 标量 | 来源 `manifest.json` 摘要 |
| `source_validation_sha256` | Unicode 标量 | validation 文件中保存的来源 `validation_selection.npz` 摘要；train 文件中不存在 |
| `schema_version` | `uint16` 标量 | 当前为 `1` |

比例小于 1 时各 epoch 复用冻结请求；比例等于 1 时 train 请求可以按 epoch 重新选择。

## 4. Stage1 正式输出目录与状态

### 4.1 固定寻址

```text
<stage1_outputs>/
└── {producer}/
    ├── calibration/
    │   ├── thresholds.json
    │   ├── threshold_scan.npz
    │   ├── metrics.json
    │   └── _COMPLETE
    └── {split}/{pdb_id}/
        ├── _RUNNING/owner.json
        ├── _BLOB_EXCEED
        ├── status/
        │   ├── probability/_COMPLETE
        │   ├── components/_COMPLETE
        │   ├── F_1_2_centered/_COMPLETE
        │   ├── F_2_3_centered/_COMPLETE
        │   ├── F_4_5_centered/_COMPLETE
        │   ├── F1_centered/_COMPLETE
        │   ├── F_5_4_centered/_COMPLETE
        │   ├── F_3_2_centered/_COMPLETE
        │   ├── F_2_centered/_COMPLETE
        │   ├── CLG_centered/_COMPLETE
        │   └── Selected_Refined_Centered/_COMPLETE
        ├── probability/
        │   ├── probability_map.npz
        │   └── geometry.json
        ├── components/
        │   ├── forest.npz
        │   ├── clg.npz
        │   ├── overlap.npz
        │   └── summary.json
        ├── centered/
        │   ├── F_1_2_centered.npz
        │   ├── F_2_3_centered.npz
        │   ├── F_4_5_centered.npz
        │   ├── F1_centered.npz
        │   ├── F_5_4_centered.npz
        │   ├── F_3_2_centered.npz
        │   ├── F_2_centered.npz
        │   ├── CLG_centered.npz
        │   └── Selected_Refined_Centered.npz
        └── selector/selection.npz
```

`selector/selection.npz` 是 Selected 生产命令的默认输入位置，不由 `probability`、`components`、`F1_centered` 或 `CLG_centered` 生产命令创建。

Li 变体使用独立根目录 `/storage/penghongen/AdaLigand_stage1_LI_inference`。其 PDB 目录保持相同的 `{producer}/{split}/{pdb_id}` 身份与 `_RUNNING`、`status` 结构，但只发布 `centered/Li_centered.npz` 及 `status/Li_centered/_COMPLETE`；它读取主线已有的完整图概率，不落盘 `components/forest.npz`、`components/clg.npz`、`candidate_eligible` 或 Selector 输入。

### 4.2 PDB 租约

`_RUNNING/owner.json` 的精确字段：

| 字段 | 类型与含义 |
| --- | --- |
| `owner_token` | `str`，本次租约身份 |
| `pid` | `int`，进程号 |
| `host` | `str`，主机名 |
| `created_at_utc` | `str`，ISO 格式 UTC 时间 |

代码不会自行判断残留租约是否陈旧。已有 `_RUNNING` 时，当前 PDB 返回 `skipped_running`。

### 4.3 角色完成标记

PDB 级角色包括 `probability`、`components`、七个 Fα-centered 角色、`CLG_centered` 与 `Selected_Refined_Centered`。七个 Fα 角色按冻结顺序对应 `F_1_2_centered`、`F_2_3_centered`、`F_4_5_centered`、`F1_centered`、`F_5_4_centered`、`F_3_2_centered`、`F_2_centered`；其中 alpha 等于 1 时继续使用历史 `F1_centered` 名称。

每个 `status/{role}/_COMPLETE` 是 JSON，对象精确包含：

- `output_role: str`，必须等于目录中的角色名；
- `completed_at_utc: str`，ISO 格式 UTC 完成时间。

载荷成功发布并通过重读校验后，才发布角色完成标记。已经完成的角色再次运行时返回 `skipped_complete`。

### 4.4 组件超量终态

组件阶段的 `N_F1_eligible` 大于本次命令使用的上限时，发布 `_BLOB_EXCEED` JSON：

- `N_F1_eligible: int`
- `limit: int`

默认上限是 200，但消费者必须读取 `limit` 的实际值。生产开关 `continue_on_blob_exceed` 默认关闭，此时保持历史行为：已有 `probability` 可以保留，后续角色不发布。开关开启时仍保留 `_BLOB_EXCEED`，但照常发布本次请求的 components 与 centered 产物；正式新脚本只在 calibration 数据划分开启该开关，validation 与 train 保持默认行为。

评估开关 `evaluate_on_blob_exceed` 与生产开关相互独立。开启后，只要本次评估所需产物存在，带 `_BLOB_EXCEED` 的 PDB 仍进入指标；正式评估脚本始终开启。普通 Stage2/3 消费条件不因该评估开关改变。

PDB 处理汇总状态只有 `completed`、`skipped_complete`、`skipped_running`、`blob_exceed`。

## 5. 完整图概率与模型来源级校准

### 5.1 完整图概率

融合规则：

- 80³ 窗口，40³ 步长，不填充；
- 每个轴补入最后一个合法起点；
- 按 Z、Y、X 的笛卡尔积确定性枚举；
- 使用 `[-1,1]^3` 上归一化高斯权重，`sigma=0.5`；
- 概率加权和、权重和与最终除法使用 `float32`；
- 三个 Find 模型来源的概率在写盘前乘受体 hardmask，`unet_c1` 不执行该处理。

窗口起点与融合 `weight_sum` 只存在于内存。

`probability/probability_map.npz` 的精确字段只有：

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `probability_map` | `float32 (D,H,W)` | ZYX 完整图上的有限融合概率 |
| `origin_xyz` | `float32 (3,)` | 完整网格角点的世界 XYZ 坐标，单位 Å；与 `geometry.json` 的同名字段逐值一致 |
| `voxel_size_xyz` | `float32 (3,)` | 世界 XYZ 三轴的体素尺寸，单位 Å/voxel；三个值均为正，并与 `geometry.json` 的同名字段逐值一致 |

三个字段的数值都必须有限。单个 `probability_map.npz` 已包含概率分析、体素索引到世界坐标换算和可视化所需的最小完整信息；`geometry.json` 继续保存窗口、步幅和高斯参数等运行元数据。

`probability/geometry.json`：

| 字段 | 类型与含义 |
| --- | --- |
| `full_shape_zyx` | 长度 3 的 `int` 数组，必须等于 `probability_map.shape` |
| `origin_xyz` | 长度 3 的 `float` 数组，网格角点世界坐标，单位 Å；转换为 `float32` 后必须与 `probability_map.npz` 的同名字段逐值一致 |
| `voxel_size_xyz` | 长度 3 的正 `float` 数组，XYZ 体素尺寸，单位 Å/voxel；转换为 `float32` 后必须与 `probability_map.npz` 的同名字段逐值一致 |
| `window_shape_zyx` | 长度 3 的 `int` 数组，固定为 `[80,80,80]` |
| `stride_zyx` | 长度 3 的 `int` 数组，固定为 `[40,40,40]` |
| `gaussian_sigma` | `float`，固定为 `0.5` |

### 5.2 `calibration/thresholds.json`

概率 `p` 的阈值编号是 `floor(p * denominator)` 裁剪到 `[0,denominator]`。alpha 顺序固定为 `[0.5,2/3,0.8,1.0,1.25,1.5,2.0]`；并列最优时取低到高扫描中首次出现的最大值。

| 字段 | 类型与含义 |
| --- | --- |
| `stage1_model_name` | `str`，模型来源 |
| `denominator` | `int`，阈值离散分母 |
| `alpha_values` | 长度 7 的 `float` 数组 |
| `alpha_threshold_grid_index` | 长度 7 的 `int` 数组 |
| `t_alpha` | 长度 7 的 `float` 数组 |
| `t_F1` | `float`，alpha 等于 1 的冻结阈值 |
| `min_voxels` | `int`，候选组件体素数下限，包含端点 |
| `max_voxels` | `int`，候选组件体素数上限，包含端点 |
| `connectivity` | `int`，固定为 `26` |

默认 `denominator=32768`、`min_voxels=10`、`max_voxels=2046`，但消费者必须读取实际值。同一 producer 的 calibration、validation 和 train 必须复用同一份冻结 `thresholds.json`，不得按数据划分覆盖 `min_voxels`。

### 5.3 `calibration/threshold_scan.npz`

| 字段 | dtype 与形状 |
| --- | --- |
| `denominator` | `int32` 标量 |
| `alpha_values` | `float64 (7,)` |
| `f_alpha_curve` | `float64 (7,denominator+1)` |
| `tp` | `int64 (denominator+1,)` |
| `fp` | `int64 (denominator+1,)` |
| `fn` | `int64 (denominator+1,)` |

`denominator` 和 `alpha_values` 必须与 `thresholds.json` 同值同序。曲线与计数的第二维或第一维都由阈值编号直接索引。

### 5.4 `calibration/metrics.json` 与完成标记

固定字段：

- `stage1_model_name: str`
- `result_scope: str`，固定为 `"calibration_fitted"`
- `threshold_scan: str`，指向 `threshold_scan.npz` 文件名

体素指标字段：

- `voxel_average_precision_macro: float`；没有有效 PDB 时为 NaN
- `n_valid_voxel_ap_pdb: int`
- `n_total_pdb: int`
- `n_evaluated_pdb: int`；按 `evaluate_on_blob_exceed` 决定后实际进入全部拟合评估指标的 PDB 数
- `semantic_dice_micro_t_F1: float`；先汇总全部未超限 PDB 的 TP、FP、FN，再按 `2TP/(2TP+FP+FN)` 计算；总分母为 0 时为 `0.0`
- `semantic_dice_macro_t_F1: float`；逐个未超限 PDB 计算 Dice 后等权平均；单个 PDB 的分母为 0 时，该项按 `0.0` 进入平均
- `semantic_tp_t_F1: int`；全部未超限 PDB 的 micro 汇总 TP
- `semantic_fp_t_F1: int`；全部未超限 PDB 的 micro 汇总 FP
- `semantic_fn_t_F1: int`；全部未超限 PDB 的 micro 汇总 FN
- `n_blob_exceed_pdb: int`；统计 `t_F1` 合格组件数大于固定界限 200 的 PDB；是否纳入指标由独立开关决定
- `evaluate_on_blob_exceed: bool`；本次评估是否纳入具有所需产物的超限 PDB

阈值扫描仍使用 calibration 清单中的全部可读概率图。冻结 `t_F1` 后才构建单层组件；`evaluate_on_blob_exceed=false` 时，超限 PDB 不以零分代替，也不进入平均精确率、Dice、实例或 top-K 指标的分子与分母；`true` 时，只要所需产物存在便照常纳入。

实例指标包括 `n_pred_instances: int`、`n_gt_instances: int`。对 `tag` 为 `0p3`、`0p5`，保存双向覆盖匹配和一对一匹配的精确率、召回率与 F1；字段名分别使用 `coverage_*` 和 `one_to_one_*`，类型均为 `float`。对 `K` 为 3、4、5，保存 `top{K}_success_{tag}: int` 与 `top{K}_success_ratio_{tag}: float`，并保存 `n_topk_eligible_pdb: int`；这些字段统计按组件平均概率排序的前 K 个预测中是否出现达标交集。

校准 `_COMPLETE` 是 JSON，只含 `stage1_model_name: str` 和 `result_scope: str`。它在三个校准载荷全部成功发布后最后创建。

## 6. 组件森林与组件谱系组

### 6.1 `components/forest.npz`

主节点表按 `(tree_id,node_id)` 升序排列，两者共同构成全局节点身份。每棵树的 `node_id` 从 0 开始连续编号。父节点位于相邻的较低阈值层，子节点位于相邻的较高阈值层。

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `tree_id` | `int32 (N_node,)` | 组件树编号 |
| `node_id` | `int32 (N_node,)` | 当前树内节点编号 |
| `threshold_grid_index` | `int32 (N_node,)` | 阈值编号 |
| `threshold_value` | `float32 (N_node,)` | 阈值编号除以 `denominator` |
| `parent_node_id` | `int32 (N_node,)` | 同一树中的父节点编号；根为 `-1` |
| `children_offsets` | `int64 (N_node+1,)` | 切分 `children_node_id` |
| `children_node_id` | `int32 (L_child,)` | 同一树中的子节点编号 |
| `node_voxel_offsets` | `int64 (N_node+1,)` | 切分 `node_voxel_global_linear_index` |
| `node_voxel_global_linear_index` | `int64 (L_voxel,)` | 来源完整图 `(D,H,W)` 的全局 C-order 线性体素编号，等价于 `np.ravel_multi_index((z,y,x),(D,H,W))`；不是 BOX 内坐标，需用完整图形状反解为全局 ZYX |
| `voxel_count` | `int32 (N_node,)` | 必须等于相应节点体素段长度 |
| `bbox_min_zyx` | `int32 (N_node,3)` | 包围盒最小体素索引，端点包含 |
| `bbox_max_zyx` | `int32 (N_node,3)` | 包围盒最大体素索引，端点包含 |
| `centroid_zyx` | `float32 (N_node,3)` | 连续体素索引空间中的质心 |
| `probability_mean` | `float32 (N_node,)` | 节点平均概率 |
| `probability_max` | `float32 (N_node,)` | 节点最大概率 |
| `candidate_eligible` | `bool (N_node,)` | `True` 表示可作为正式候选 |
| `ineligible_reason_code` | `uint8 (N_node,)` | 候选资格原因码 |
| `gauss_score` | `float32 (N_node,)`，可选 | 独立 Gauss scorer 的节点分数；只对具有本次指定 Fα-centered A 原子表的来源节点为有限值，其余节点为 `NaN` |
| `gauss_selected` | `bool (N_node,)`，可选 | 独立 Gauss scorer 的保留决定；没有有限 `gauss_score` 的节点固定为 `False` |

`children_offsets[i:i+2]` 给出节点 `i` 在 `children_node_id` 中的半开区间；首值为 0，末值为 `L_child`。`node_voxel_offsets` 同理切分节点体素表，首值为 0，末值为 `L_voxel`。每个节点的体素编号在自己的段内升序且不重复。

`gauss_score` 与 `gauss_selected` 必须同时存在或同时缺席。它们是指定 Fα-centered 完成后的独立降级打分结果，不改写 `candidate_eligible`，也不改变 `clg.npz`、CLG-centered 或 Selector 的有效节点与候选集合。Gauss scorer 的四个正参数与固定 5 Å 截断保存在 producer 级 `gauss_scorer` 目录，不重复写入每个 PDB。

对具有指定 centered A 表的来源节点 `j`，令 `d_ji` 为 A 原子 `i` 到来源预测 blob 最近体素中心的世界坐标距离，`p_i` 为 `A_probability`。当 `d_ji <= 5 Å` 时，`w_ji=exp(-d_ji²/(2*tau_angstrom²))`，否则权重为 0。正负项分别是 `sum_i(w_ji*p_i)` 与 `sum_i(w_ji*(1-p_i))`，均直接求和、不归一化；`gauss_score` 等于 `probability_mean + lambda_positive*positive_sum - lambda_negative*negative_sum`，`gauss_selected` 等于该分数不小于 `gauss_score_min`。

Gauss scorer 使用与 GPU 主线相同的 PDB 根目录 `_RUNNING` 租约，并对每个 PDB 独立原子替换目标 NPZ。前置角色尚未完成时，该 PDB 只记为待补；租约已被其他生产者持有时只记为跳过。两种情况都不改变现有文件，CPU 任务继续处理清单中的其他静止 PDB。以后按相同清单和分片重复执行即可增量补齐。正式入口默认强制刷新：已有完整 Gauss 字段对时只替换 `gauss_score` 与 `gauss_selected`，其他字段不变；关闭强制刷新时，只有逐值相同的结果才视为幂等。只存在一个 Gauss 字段始终视为损坏并拒绝覆盖。

第一阶段保留粗网格；第二阶段固定第一阶段选出的 `tau_angstrom` 与 5 Å 截断，围绕最优 `lambda_positive`、`lambda_negative` 各取中心值的 0.8、0.9、1.0、1.1、1.2 倍，围绕 `gauss_score_min` 取中心值的 0.3 至 1.7 倍、步长 0.1，共形成 375 组严格正参数。历史 F1 参数路径继续是 `{output_root}/Find_0/gauss_scorer/calibration.json`；其他 Fα 或 Li 策略使用 `{output_root}/Find_0/gauss_scorer/{centered_role}/calibration.json`。同一 centered 策略的 calibration、validation 与 train 必须复用第二阶段冻结的 `selected_parameters`。参数搜索明细、验收哈希和 Slurm 运行记录不属于 PDB 产物契约，不能写入 PDB NPZ。

原因码：

| 值 | 含义 |
| --- | --- |
| `0` | 合格 |
| `1` | 体素数小于 `min_voxels` |
| `2` | 体素数大于 `max_voxels` |
| `3` | 节点包围盒不能被合法 80³ BOX 完整包含 |

### 6.2 `components/clg.npz`

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `CLG_id` | `int32 (N_CLG,)` | 从 0 开始连续编号 |
| `tree_id` | `int32 (N_CLG,)` | 所属组件树 |
| `CLG_seed_node_id` | `int32 (N_CLG,)` | `t_F1` 合格种子节点在 `tree_id` 指定 forest 树内的局部编号 |
| `CLG_oldest_node_id` | `int32 (N_CLG,)` | 解析 centered BOX 的最老节点在 `tree_id` 指定 forest 树内的局部编号 |
| `candidate_offsets` | `int64 (N_CLG+1,)` | 同时切分下面两个候选值表 |
| `candidate_node_id` | `int32 (N_candidate,)` | 当前树内的候选节点编号 |
| `candidate_threshold_grid_index` | `int32 (N_candidate,)` | 与候选节点同序的阈值编号 |

第 `i` 个组件谱系组的候选段是 `[candidate_offsets[i],candidate_offsets[i+1])`。首值为 0，末值同时等于两个候选值表长度。

组件谱系组数量上限：

`min(300, 3 * max(2, N_F1_eligible))`

### 6.3 `components/overlap.npz`

只保存候选组件与真实配体实例的正交集；零交集不写入。

| 字段 | dtype 与形状 | 含义与索引目标 |
| --- | --- | --- |
| `candidate_occurrence_offsets` | `int64 (N_candidate+1,)` | 同时切分下面两个交集值表 |
| `overlap_occurrence_index` | `int32 (N_overlap,)` | 索引 `occurrence_id` 与 `occurrence_voxel_count` 第一维 |
| `intersection_voxel_count` | `int32 (N_overlap,)` | 正交集体素数 |
| `occurrence_id` | `int32 (N_occ,)` | 升序真实配体实例身份表 |
| `occurrence_voxel_count` | `int32 (N_occ,)` | 与身份表同序的真实体素数 |

第 `j` 个候选组件的交集段是 `[candidate_occurrence_offsets[j],candidate_occurrence_offsets[j+1])`。首值为 0，末值同时等于两个交集值表长度。候选组件自身的体素数从 `forest.npz` 对应节点读取。

### 6.4 `components/summary.json`

森林部分保存 `denominator`、`threshold_grid_indices_descending`、`connectivity`、`min_voxels`、`max_voxels`、`n_trees`、`n_nodes`、原因码映射和 `layers`。

原因名精确映射为 `"0":"eligible"`、`"1":"below_min_voxels"`、`"2":"above_max_voxels"`、`"3":"bbox_not_contained_by_resolved_box"`。

每个阈值层包含 `threshold_grid_index`、`n_nodes`、`n_eligible`、`n_below_min_voxels`、`n_above_max_voxels`、`n_bbox_not_contained_by_resolved_box`，类型均为 `int`。

组件谱系组部分保存：

- `max_split_events: int`
- `max_merge_events: int`
- `max_nodes_per_CLG: int`
- `n_f1_eligible_seeds: int`
- `n_CLG_cap: int`
- `n_CLG_completed: int`
- `n_CLG_rejected_by_node_cap: int`
- `mean_candidates_per_completed_CLG: float`
- `CLG_cap_reached: bool`

`CLG_cap_reached` 只有在完成数等于 `n_CLG_cap` 且仍有未消费的活跃种子时为 `true`。

## 7. centered NPZ 的共同契约

本节定义七个 Fα-centered、独立 `Li_centered`、`CLG_centered` 和 `Selected_Refined_Centered` 共用的字段、数据类型和 offsets；第 8 节在共同结构上补充各角色如何决定权威体素成员。消费任一 centered NPZ 时必须同时应用这两节。一个 PDB 的同一 centered 角色只发布一个 NPZ。来源组件必须能被合法 80³ BOX 完整包含。

### 7.1 共同归档项字段

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `centered_box_index` | `int32 (N_entry,)` | 严格等于 `0..N_entry-1` |
| `box_start_zyx` | `int32 (N_entry,3)` | 完整图中的离散 BOX 起点 |
| `box_shape_zyx` | `uint8 (N_entry,3)` | 每项固定为 `[80,80,80]` |
| `box_origin_world` | `float32 (N_entry,3)` | BOX 角点世界 XYZ，单位 Å |
| `voxel_size_world` | `float32 (N_entry,3)` | XYZ 体素尺寸，单位 Å/voxel |
| `source_tree_id` | `int32 (N_entry,)` | 来源 `components/forest.npz` 的组件树编号 |
| `source_node_id` | `int32 (N_entry,)` | 来源节点在 `source_tree_id` 指定树内的局部编号；二者共同组成 forest 节点身份 |
| `source_threshold_grid_index` | `int32 (N_entry,)` | 来源 forest 节点所在阈值层的整数网格编号 `j`，不是体素索引 |
| `source_threshold_value` | `float32 (N_entry,)` | 来源节点的二值化阈值 `j/denominator`；不是该条目任一体素的预测概率 |

### 7.2 共同体素表

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `voxel_offsets` | `int64 (N_entry+1,)` | 同时切分下面三个权威体素值表 |
| `voxel_index_local_zyx` | `int16 (L_voxel,3)` | 当前角色权威成员体素在本条目 80³ BOX 内的离散 ZYX 坐标，各轴范围 `0..79`；不是完整图索引，成员集合由第 8 节定义 |
| `centered_probability` | `float32 (L_voxel,)` | 当前 centered BOX 重跑完整模型后，经 sigmoid 和模型专属后处理得到的概率，再按 `voxel_index_local_zyx` 逐行取值；不是原始滑窗完整图概率 |
| `voxel_final` | `float16 (L_voxel,C_voxel)` | 与体素同序的最终体素特征 |
| `voxel_aux_offsets` | `int64 (N_entry+1,)` | 同时切分下面两个辅助体素值表 |
| `voxel_aux_index_local_zyx` | `int16 (L_aux,3)` | 当前 centered 输入 `hardmask == True` 的位置在本条目 80³ BOX 内的离散 ZYX 坐标；不是完整图索引或权威配体成员集合 |
| `voxel_aux_probability` | `float32 (L_aux,)` | 当前 centered 前向的受体辅助头经 sigmoid 后，按 `voxel_aux_index_local_zyx` 逐行取出的概率 |

`voxel_offsets` 首值为 0，末值同时等于三个权威体素值表的第一维长度。`voxel_aux_offsets` 首值为 0，末值同时等于两个辅助体素值表长度。

`C_voxel` 由 checkpoint 决定。`voxel_aux_probability` 不是 Find 完整图融合使用的 hardmask。模型可能还返回蛋白主链、核酸主链和配体反距离辅助 logits，但当前 centered NPZ 不保存这些值。

### 7.3 Find P 点表

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `P_offsets` | `int64 (N_entry+1,)` | 同时切分下面四个 P 值表 |
| `P_coord_local_xyz` | `float32 (L_P,3)` | BOX 局部连续 XYZ |
| `P_probability` | `float32 (L_P,)` | P 点概率 |
| `P_feat_L2` | `float16 (L_P,C_L2)` | `outputs["pseudo_density_feat"]`；密度、伪原子类别与界面归一化共同形成的 P 初始表示，也是点骨干网络接收的 P 输入 |
| `P_feat_L3` | `float16 (L_P,C_L3)` | `outputs["pseudo_feat_before_interaction"]`；点骨干网络处理完成、A↔P 交叉注意力发生之前的 P 最终表示 |

`P_offsets` 首值为 0，末值等于四个 P 值表长度。P 表保存当前 BOX 的全部 P 点，不表示 CLG 候选成员关系。

### 7.4 Find A 原子表

| 字段 | dtype 与形状 | 含义与索引目标 |
| --- | --- | --- |
| `A_offsets` | `int64 (N_entry+1,)` | 同时切分下面八个 A 值表 |
| `A_global_index` | `int64 (L_A,)` | 索引完整 `receptor_tokens.npz` 第一维，仅用于原子身份和来源追踪 |
| `A_coord_local_xyz` | `float32 (L_A,3)` | BOX 局部连续 XYZ |
| `A_coord_centered_world` | `float32 (L_A,3)` | 相对 BOX 中心的世界 XYZ，单位 Å |
| `A_probability` | `float32 (L_A,)` | A 原子概率 |
| `A_feat_L0` | `float32 (L_A,50)` | 当前 centered 输入 `batch["atom_feat"]` 中、按 `A_global_index` 对齐到模型输出 A 行序的运行时受体特征；前 49 维来自 `feat`，最后 1 维来自 `is_backbone`，位于点侧嵌入层之前并保留 float32 精度 |
| `A_feat_L1` | `float16 (L_A,C_L1)` | `outputs["A_feat_L1"]`；点侧嵌入与界面归一化完成、真实原子密度调制发生之前的 A 表示 |
| `A_feat_L2` | `float16 (L_A,C_L2)` | `outputs["A_feat_L2"]`；真实原子密度调制完成后送入点骨干网络的 A 输入表示 |
| `A_feat_L3` | `float16 (L_A,C_L3)` | `outputs["real_feat_before_interaction"]`；点骨干网络处理完成、A↔P 交叉注意力发生之前的 A 最终表示 |

`A_offsets` 首值为 0，末值等于八个 A 值表长度。这里的来源组件是当前 centered 条目对应的预测 blob：Fα 使用对应冻结阈值层节点，Li 使用自身逐图阈值形成的局部 blob，CLG 使用最老来源节点，Selected 使用被选中的来源节点。A 表保存完整受体原子表中同时位于 80³ 核心内并落入该预测 blob 体素集合 10 Å 包络的原子。Selector 直接读取已持久化的 `A_feat_L0`；`A_global_index` 继续承担身份追踪，不再用于二次加载原始特征。

Stage1-Find 前向计算仍可产生交叉注意力后的 `A_feat_L4` 与 `P_feat_L4`，但 centered 归档不保存这两组张量。Selector 只读取本节列出的 L3 及以前特征；A/P 分类概率仍使用 Stage1-Find 原有分类头结果。

`unet_c1` 不得出现 P/A 字段。Find 中 P/A 必须整组出现；完全为空的 F1 或 CLG 归档无法确定特征宽度时，两组可以同时整体缺席。Selected 至少有一个成功项产生相应模态时才保存整组字段；未成功项的 P/A 段为空。

## 8. centered 角色的权威成员语义

所有角色都重新执行当前 80³ BOX 的完整模型前向，所以 `centered_probability`、`voxel_final` 和适用的 P/A 表都来自本次 centered 前向。角色差异只在 `voxel_index_local_zyx` 所代表的权威体素集合如何确定。

### 8.1 `centered/F1_centered.npz`

- 每个归档项对应 `t_F1` 层一个合格组件。
- 排序键依次是 `probability_mean` 降序、`tree_id` 升序、`node_id` 升序。
- 权威体素集合是原始滑窗融合 `probability_map` 在 `t_F1` 上形成的来源 forest 组件成员，完整图成员由 `node_voxel_global_linear_index` 给出后换算为当前 BOX 内 ZYX 坐标。
- 这些坐标上的 `centered_probability` 与 `voxel_final` 来自当前 centered 重算，不复用滑窗融合概率或滑窗特征。
- 没有合格组件时可以发布 `N_entry == 0` 的空归档。
- 除第 7 节共同字段和适用模态字段外，没有角色专属字段。

### 8.2 其余 Fα-centered 文件

`F_1_2_centered.npz`、`F_2_3_centered.npz`、`F_4_5_centered.npz`、`F_5_4_centered.npz`、`F_3_2_centered.npz` 与 `F_2_centered.npz` 和 `F1_centered.npz` 完全同构。每个文件直接读取 `thresholds.json` 中对应 alpha 的既有冻结阈值层，只选择该层 `candidate_eligible == True` 的 forest 节点，并按与 F1 相同的排序、BOX 解析、完整前向和字段规则添油式发布；不重建 forest 或 CLG，也不覆盖其他 centered 文件。

### 8.3 `centered/Li_centered.npz`

Li 角色从主线已完成的 `probability_map.npz` 逐图计算 Li 最小交叉熵阈值，再向上量化到相同的 32768 分母整数网格。它使用 `min_voxels=10`、`max_voxels=2046` 和 26 邻域连通组件，仅在内存中构造自身 blob 后执行同构的 80³ centered 前向；不持久化 forest 或 CLG。

除第 7 节共同字段和适用模态字段外，Li 归档增加：

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `source_probability_mean` | `float32 (N_entry,)` | 每个 Li blob 在来源完整图上的平均概率 |
| `li_threshold_raw` | `float32 (1,)` | 逐图 Li 算法得到的原始阈值 |
| `li_threshold_grid_index` | `int32 (1,)` | 向上量化后的整数网格编号 |
| `li_threshold_applied` | `float32 (1,)` | 实际应用阈值，等于网格编号除以分母 |
| `threshold_denominator` | `int32 (1,)` | 阈值网格分母，正式值为 32768 |
| `gauss_score` | `float32 (N_entry,)`，可选 | Li blob 的独立 Gauss 得分 |
| `gauss_selected` | `bool (N_entry,)`，可选 | Li blob 是否达到冻结的 Gauss 选择阈值 |

Li 的两个 Gauss 字段必须同时存在或同时缺席。它们不产生 Selector 输入，也不改变 Stage2/3 的主线消费契约。

### 8.4 `centered/CLG_centered.npz`

每个组件谱系组使用 `CLG_oldest_node_id` 解析 80³ BOX。权威体素集合是该最老 forest 节点的完整图组件成员换算到当前 BOX 后的坐标；概率和特征仍来自当前 centered 重算。归档额外保存：

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `CLG_id` | `int32 (N_entry,)` | 与 `components/clg.npz` 同序 |
| `CLG_seed_node_id` | `int32 (N_entry,)` | 种子节点在 `source_tree_id` 指定 forest 树内的局部编号 |
| `CLG_oldest_node_id` | `int32 (N_entry,)` | 最老节点在 `source_tree_id` 指定 forest 树内的局部编号，并决定本条目的 BOX 与权威体素集合 |
| `candidate_offsets` | `int64 (N_entry+1,)` | 同时切分候选节点和候选阈值编号 |
| `candidate_node_id` | `int32 (N_candidate,)` | 候选节点在所属条目 `source_tree_id` 指定 forest 树内的局部编号 |
| `candidate_threshold_grid_index` | `int32 (N_candidate,)` | 候选 forest 节点所在阈值层的整数网格编号 `j` |
| `candidate_voxel_offsets` | `int64 (N_candidate+1,)` | 切分 `candidate_voxel_index` |
| `candidate_voxel_index` | `int32 (L_candidate_voxel,)` | 所属条目权威体素值表的局部行号；既不是 BOX 内 ZYX 坐标，也不是完整图线性索引 |
| `candidate_A_offsets` | `int64 (N_candidate+1,)` | 切分 `candidate_A_index`；只在 Find A 组存在时出现 |
| `candidate_A_index` | `int32 (L_candidate_A,)` | 所属归档项 A 原子段内的局部值表编号 |

`candidate_offsets` 首值为 0，末值等于两个候选值表长度。`candidate_voxel_offsets` 首值为 0，末值等于 `candidate_voxel_index` 长度。Find A 组存在时，`candidate_A_offsets` 首值为 0，末值等于 `candidate_A_index` 长度。

若候选属于条目 `i`，`voxel_offsets[i] + candidate_voxel_index[k]` 才是它在归档级 `voxel_index_local_zyx` 中的实际行号，随后从该行读取 BOX 内离散 ZYX 坐标。`candidate_A_index` 同理引用所属条目 `A_offsets` 段内的局部 A 行。两者都不是坐标或完整图全局索引。

### 8.5 `centered/Selected_Refined_Centered.npz`

Selector 选择先恢复到 forest 来源节点，再重新执行当前 80³ BOX 的模型前向，使用该节点自己的 `source_threshold_value` 对当前 centered 概率二值化并重建 26 邻域连通组件。存在多个局部组件时，只在与原始来源组件相交的组件中保留交并比最大的一个；多个 CLG 选择同一来源节点时只发布一次。因此成功条目的权威体素集合是新精修结果，可能与原始滑窗来源组件不同。

归档项按 CLG 顺序和各 CLG 内的来源候选顺序处理；同一来源节点重复出现时保留第一次。

专属字段：

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `refine_status` | `uint8 (N_entry,)` | 精修状态码 |
| `refine_status_names` | Unicode `(3,)` | 固定为 `["success","empty","no_overlap"]` |

状态：

| 值 | 名称 | 含义 |
| --- | --- | --- |
| `0` | `success` | 至少一个局部组件与来源组件相交；保存最大交并比组件及模型载荷 |
| `1` | `empty` | 阈值化后没有局部组件 |
| `2` | `no_overlap` | 有局部组件，但都不与来源组件相交 |

只有成功项可以携带体素和 P/A 载荷。部分成功时，所有 `voxel_final` 值使用成功载荷的统一 `C_voxel`；未成功项的变长段为空。完全没有成功项时 `voxel_final.shape == (0,0)`。

模型 forward、字段读取或精修实现异常不属于 `refine_status`。异常会阻止当前 role 发布 `_COMPLETE`，修复后由续跑流程重新生产。

## 9. Selector 产物

### 9.1 目录

Selector 运行目录由调用方显式指定：

```text
<selector_run_dir>/
├── input_CLG_list.json
├── calibration.json
└── {split}/{pdb_id}/scores.npz
```

代码不强制运行目录的外层实验命名。`selection.npz` 的位置由命令参数决定；若 Selected 生产命令使用默认寻址，调用方必须把它发布到 Stage1 PDB 目录的 `selector/selection.npz`。

### 9.2 `input_CLG_list.json`

Selector 训练启动时扫描一次可消费的 `CLG_centered` 并冻结清单。同一运行目录后续只允许严格复用相同清单。

| 字段 | 类型与含义 |
| --- | --- |
| `schema_version` | `int`，当前为 `1` |
| `stage1_model_name` | `str`，模型来源 |
| `split_order` | `list[str]`，数据划分顺序 |
| `split_counts` | 对象，数据划分名到 CLG 数 |
| `split_pdb_counts` | 对象，数据划分名到 PDB 数 |
| `pdb_ids_by_split` | 对象，数据划分名到完整 PDB 身份数组；包含零 CLG PDB |
| `items` | 对象数组，每项精确包含 `split: str`、`pdb_id: str`、`CLG_id: int` |

`items` 依次按 `split_order`、PDB 身份和来源 `CLG_id` 排列；同一 PDB 的项目完整复制来源 CLG 顺序。

### 9.3 `{split}/{pdb_id}/scores.npz`

| 字段 | dtype 与形状 | 对齐关系 |
| --- | --- | --- |
| `CLG_id` | `int32 (N_CLG,)` | 与来源 `components/clg.npz` 同序同值 |
| `CLG_logit` | `float32 (N_CLG,)` | 有限的 CLG 未归一化门控分数；字段名保留 `logit` |
| `CLG_valid_probability` | `float32 (N_CLG,)` | `sigmoid(CLG_logit)`，有限且位于 `[0,1]` |
| `candidate_offsets` | `int64 (N_CLG+1,)` | 逐值复制来源 CLG，同步切分下面两个候选值表 |
| `predicted_max_iou` | `float32 (N_candidate,)` | 有限且位于 `[0,1]` 的候选最大交并比预测 |
| `selection_logit` | `float32 (N_candidate,)` | 有限的候选未归一化结构选择分数；只用于精确反链选择，不是概率或候选质量 |

`candidate_offsets` 首值为 0，末值同时等于两个候选值表长度。零 CLG PDB 仍发布字段齐全的空表。

“反链”表示同一组件树中任意两个选中节点都不存在祖先与后代关系。`selection_logit` 只为这种结构化选择提供能量，不应解释为概率。

### 9.4 `calibration.json`

Selector 校准汇集 calibration PDB 的有限 `CLG_valid_probability`，按实际出现概率的升序唯一值扫描门控阈值，以全局 `M_instance` 首个最大值对应的阈值作为 `tau_G`。没有任何有限 CLG 概率时命令失败，不发布伪校准。

根字段：

- `schema_version: int`，当前为 `1`
- `stage1_model_name: str`
- `split: str`，正式值为 `"calibration"`
- `calibration_fitted: bool`，固定为 `true`
- `lambda_count: float`
- `coverage_thresholds: list[float]`，固定为 `[0.3,0.5]`
- `scan_definition: str`，固定为 `"ascending_unique_actual_CLG_valid_probability"`
- `pdb_count: int`，包含零 CLG PDB
- `tau_G: float`
- `best_curve_index: int`
- `metrics: object`
- `macro_diagnostic: object`
- `curve: list[object]`

`metrics` 和每个曲线项的 `global` 保存 `n_pred_instances`、`n_gt_instances`，以及 `0p3`、`0p5` 下双向覆盖匹配和一对一匹配的精确率、召回率与 F1，并保存四个 F1 的算术均值 `M_instance`。

`macro_diagnostic` 和每个曲线项的同名对象只保存四个逐 PDB 算术平均 F1 与 `M_instance`。每个曲线项还保存 `tau_G: float`。

### 9.5 `selection.npz`

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `CLG_id` | `int32 (N_CLG,)` | 与来源 CLG 同序同值 |
| `CLG_gate_pass` | `bool (N_CLG,)` | `True` 表示 `CLG_valid_probability >= tau_G` |
| `selected_candidate_offsets` | `int64 (N_CLG+1,)` | 切分 `selected_candidate_index` |
| `selected_candidate_index` | `int16 (N_selected,)` | 所属 CLG 候选段内的局部编号，段内严格递增且无重复 |

第 `i` 个 CLG 的选择段是 `[selected_candidate_offsets[i],selected_candidate_offsets[i+1])`。首值为 0，末值等于 `N_selected`。局部编号必须小于来源 `candidate_offsets[i+1] - candidate_offsets[i]`。

`CLG_gate_pass == False` 时选择段为空；`CLG_gate_pass == True` 时，精确且非空的最大后验选择至少产生一个候选编号。

零 CLG PDB 的 `CLG_id` 和 `CLG_gate_pass` 形状都是 `(0,)`，`selected_candidate_offsets` 精确为 `[0]`，`selected_candidate_index` 形状为 `(0,)`。

## 10. 正式生产入口与依赖顺序

Stage1 推理入口是 `python -m src.inference.cli`：

| 子命令 | 数据划分 | 必须已经存在的输入 | 新增产物 |
| --- | --- | --- | --- |
| `cal-probability` | calibration | checkpoint、完整图输入 | probability |
| `freeze-thresholds` | calibration | 清单中全部 PDB 的可读 probability、真实配体实例 | 模型来源级校准目录 |
| `cal-produce-f1` | calibration | probability、模型来源级校准、checkpoint | components、F1 centered |
| `cal-produce-f1-clg` | calibration | probability、模型来源级校准、checkpoint | components、F1 centered、CLG centered |
| `val-produce-prob-f1` | validation | 模型来源级校准、checkpoint、完整图输入 | probability、components、F1 centered |
| `val-produce-prob-f1-clg` | validation | 模型来源级校准、checkpoint、完整图输入 | probability、components、F1 centered、CLG centered |
| `train-produce-prob-f1` | train | 模型来源级校准、checkpoint、完整图输入 | probability、components、F1 centered |
| `train-produce-prob-f1-clg` | train | 模型来源级校准、checkpoint、完整图输入 | probability、components、F1 centered、CLG centered |
| `produce-falpha` | 显式指定 | 已完成 probability/components、模型来源级校准、checkpoint | 指定的一个 Fα-centered 角色 |
| `produce-li-centered` | 显式指定 | 主线已完成 probability、checkpoint、完整图输入 | 独立根目录的 `Li_centered` |
| `selected-refined` | 显式指定 | 可读 `components` 角色、`selection.npz`、`geometry.json`、模型检查点、完整图输入 | `Selected_Refined_Centered` |

`selected-refined` 读取 `forest.npz`、`clg.npz` 和 `probability/geometry.json`，不读取 `probability_map.npz`。未指定外置选择根目录时，它读取 `{PDB正式目录}/selector/selection.npz`；指定后读取 `{selection_root}/{producer}/{split}/{pdb_id}/selection.npz`。

Selector 入口：

| 命令 | 产物 |
| --- | --- |
| `python -m src.selector.train --config <selector.yaml>` | 训练启动时冻结 `input_CLG_list.json` |
| `python -m src.selector.inference scores` | 逐 PDB `scores.npz` |
| `python -m src.selector.inference calibrate` | Selector 运行目录 `calibration.json` |
| `python -m src.selector.inference selection` | 显式输出路径的单 PDB `selection.npz` |

F1-only 命令完成后，可以在同一输出根目录运行对应的 `*-f1-clg` 命令。后者按已有 `_COMPLETE` 保持 probability、components 和 F1 centered 不变，只补充缺少的 CLG centered。

除 `freeze-thresholds` 外，Stage1 的十个 PDB 级推理子命令都按清单位置分片：

`record_index % shard_count == shard_index`

清单位置从 0 开始。checkpoint 恢复优先使用训练目录中的 `src_snapshot/src` 和解析配置；只有显式允许时才使用当前工作区源码。

## 11. 跨文件对齐

### 11.1 完整图到组件

- `probability_map.shape == full_shape_zyx`。
- `probability_map.npz` 与 `geometry.json` 的 `origin_xyz`、`voxel_size_xyz` 转换为 `float32` 后分别逐值一致。
- forest 全局线性体素编号落在 `[0,D*H*W)`。
- `threshold_value == threshold_grid_index / denominator`。
- `(tree_id,node_id)`、父子关系、体素数、包围盒和原因码相互一致。

### 11.2 组件到 centered

- F1 centered 来源节点是 `t_F1` 层合格节点。
- 其余 Fα centered 来源节点是 `thresholds.json` 中同一 alpha 冻结阈值层的合格节点；不新建 forest。
- Li centered 的来源节点只在内存中存在，`source_threshold_value` 等于逐图 Li 阈值向上量化后的 `j/denominator`，并与四个 Li 元数据字段一致。
- CLG centered 的身份、种子、最老节点和候选顺序与 `components/clg.npz` 对齐。
- `candidate_voxel_index` 落在所属归档项的体素段局部范围内。
- Find A 组存在时，`candidate_A_index` 落在所属归档项的 A 原子段局部范围内。
- `unet_c1` 不含 P/A 字段。

### 11.3 CLG 到 Selector

- `input_CLG_list.json` 覆盖冻结 PDB 清单，零 CLG PDB也保留在 `pdb_ids_by_split`。
- `scores.npz` 的 `CLG_id` 与 `candidate_offsets` 逐值复制来源 CLG。
- `selection.npz` 的 `CLG_id` 与 scores 和来源 CLG 同序。
- `selected_candidate_index` 是所属 CLG 候选段内的局部编号，不是 forest 节点编号。

### 11.4 Selector 到 Selected

- Selected 生产命令读取可消费的 `components` 角色、`selection.npz`、`geometry.json`、完整图输入和模型检查点。
- 来源节点由 `CLG_id + selected_candidate_index` 唯一恢复。
- 重复来源节点只发布一次。
- 只有成功项携带模型载荷；未成功项的变长段为空。

## 12. 冷读验收

交付或消费产物前，至少执行以下检查：

1. 路径中的模型来源、数据划分和小写 `pdb_id` 与请求一致。
2. 所需 `status/{role}/_COMPLETE` 存在，且 `output_role` 与角色名一致。
3. PDB 目录中不存在 `_RUNNING`。`_BLOB_EXCEED` 是否阻断由当前消费者的明确契约决定；正式评估在所需产物存在时允许纳入，普通 Stage2/3 消费仍按其既有条件处理。
4. NPZ 可在 `allow_pickle=False` 下读取，字段集合、dtype、维度、固定形状和有限值符合本文。
5. 每个 offsets 长度正确、首值为 0、单调不减、末值等于本文点名的全部值表长度。
6. 每个索引字段落在本文点名的目标数组或所属变长段范围内。
7. 完整图概率与几何字段相互一致，尤其是 `probability_map.npz` 与 `geometry.json` 的 `origin_xyz`、`voxel_size_xyz`；组件森林、组件谱系组、交集、居中归档、Selector 分数和选择表的身份与顺序一致。
8. `unet_c1` 不含 P/A；Find 的 P/A 整组出现，或只在本文允许的空归档条件下整组缺席。
9. Selected 只有成功项携带载荷，且未知特征宽度的全空 `voxel_final` 使用 `(0,0)`。

## 13. 契约边界

- checkpoint、优化器状态、训练日志和 Selector 外层实验目录名不属于正式推理产物。
- 滑窗起点、高斯 `weight_sum`、运行时缓存和未发布临时文件不持久化。
- 当前 centered NPZ 不保存蛋白主链、核酸主链或配体反距离辅助 logits。
- 修改字段、dtype、坐标、状态或路径规则时，必须同步修改写入器、冷读校验器、本文和 Pocket Plus 的 `src/artifacts/readme.md`。
