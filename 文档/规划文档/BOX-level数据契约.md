# AdaLigand BOX 级数据契约

本文定义 AdaLigand Stage1 训练预定位、完整图概率、F1/F3 阈值校准、两类连通区域、F1 basic、F3 centered 和评估事实的磁盘契约。本文面向产物的生产者与消费者；只看本文，读者应能确定正式文件、字段、形状、坐标、空值、索引目标、完成状态和跨文件对齐关系。

Pocket Plus 仓库的 `src/inference/README.md` 覆盖相同产物，并额外说明模块职责、生产命令和并发边界。两份文档不得对同一文件给出不同定义。

## 1. 范围、术语与共同规则

### 1.1 三个身份轴

- Stage1 模型来源：对应命令参数 `--producer`，只允许 `Find_0`、`Find_1`、`Find_2`、`unet_c1`。
- 数据划分：对应命令参数 `--split`，正式推理只允许 `calibration`、`validation`、`train`。
- PDB 身份：对应 `pdb_id`，正式值为小写且非空；同一清单不得出现重复身份。

三个 Find 模型来源使用体素模态 V、点模态 P 和原子模态 A；`unet_c1` 只使用体素模态 V。本文保留目录术语 `centered`，表示为一个来源组件解析合法 80³ BOX 并在该 BOX 中重新执行模型。

“blob”表示在一个冻结概率阈值上得到的 26 邻域连通体素集合。“centered 条目”表示 centered NPZ 第一维中的一个 80³ BOX。F1 basic 使用 micro-F1 语义阈值，F3 centered 使用 micro-F3 语义阈值。

`hardmask` 是受体占据位置的 BOX 级布尔掩码；值为 `True` 的体素是受体原子所在位置。四个模型来源的配体概率都不乘 hardmask，也不在完整图融合后把受体位置置零。

### 1.2 文件格式与发布

- JSON 文件使用 UTF-8。
- NPZ 不得包含 `object` dtype，必须能由 `numpy.load(path, allow_pickle=False)` 读取。
- 正式 JSON 和 NPZ 先写同目录临时文件，写入成功后再原子替换正式路径；大型 NPZ 不做重复解压重读。
- NPZ 字段集合是精确集合；缺少字段或出现未声明字段都属于契约不一致。本文明确允许整组缺席的 Find P/A 字段除外。
- 文件存在不代表角色完成。PDB 级消费者还必须检查角色完成标记和异常状态。

字段名中的 `offsets` 表示变长表边界数组。第 `i` 个对象对应半开区间 `[offsets[i],offsets[i+1])`；每个具体 offsets 切分哪些值表，会在相应文件字段表中逐一写明。

### 1.3 形状记号

| 记号 | 含义 |
| --- | --- |
| `D,H,W` | 完整图 Z、Y、X 三轴长度 |
| `N_occ` | 当前 PDB 的真实配体 occurrence 数；occurrence 指一个真实配体实例 |
| `N_blob` | 当前 F1 或 F3 阈值下的全部 26 邻域连通区域数 |
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

训练请求采用 `center:bias:context = 0:5:5`，冻结验证请求采用 `0:1:1`。两者对每个 PDB 都最多选择 50 个 occurrence；center 起点只为兼容既有字段而保留，不进入请求。训练上下文池不足 5 项时可以放回采样；验证每个 occurrence 只选择 1 个上下文候选。上下文池为空时不伪造请求。

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
- `validation_entry_ratio={"center":0,"bias":1,"context":1}`
- `seed: int`
- `seed_rule="sha256(base_seed|split_name|pdb_id) first_uint64"`

`summary.json` 保存：

- `seed: int`
- train 的 `requested_pdb`、`published_pdb`、`zero_context_pdb_count`
- validation 的 `requested_pdb`、`published_pdb`、`zero_context_pdb_count`
- `validation_selection` 的 `pdb_count`、`center_count`、`bias_count`、`context_count`
- `manifest` 的 train 与 validation 文件数

正式结果为 train 13,717/13,717 PDB、validation 200/200 PDB，两个集合的 `zero_context_pdb_count` 都为 0。2026-08-18 按同一 seed 3407 覆盖发布的固定验证选择有 3,305 个 bias、3,305 个 context 和 0 个 center 条目；原 `0:5:5` 验证选择不再是活动产物。上述计数全部是 `int`。`_COMPLETE` 是每次完整发布最后创建的零字节文件。

### 3.3 训练消费契约

当前活动 Dataset 不提供请求比例截断参数，也不创建额外的 train 或 validation 比例请求文件。训练按 manifest 生成每个 epoch 的完整 `0:5:5` 请求；验证完整展开活动 `validation_selection.npz` 中冻结的 `0:1:1` 请求。

四个完整体数组通过只读内存映射现场裁出 80³：

| 完整图文件 | dtype 与形状 | 同目录元数据来源 |
| --- | --- | --- |
| `exp.npy` | `float32 (1,D,H,W)` | `exp.npz` |
| `sim.npy` | `float32 (1,D,H,W)` | `sim.npz` |
| `union_mask.npy` | `bool (1,D,H,W)` | `ligand_area.npz` |
| `ligand_dist.npy` | `float16 (1,D,H,W)` | `ligand_dist.npz` |

Dataset 只复制实际裁块，不因缓存计量或数值检查读取完整体数组。实际密度裁块必须有限，距离裁块必须有限且非负，union mask 保持 bool。完整图形状、体素尺寸、世界坐标原点和 schema 来自小型 NPZ；完整数组的迁移一致性由 `reports/runs/stage1_npy_migration_20260817_v1/_COMPLETE` 及其摘要负责。

受体资产不改写：`receptor_tokens.npz:feat` 保持 `float32 (N_receptor,49)`，`is_backbone` 保持 `bool (N_receptor,)`。Dataset/Collator 分别传递两个字段；模型输入边界仅在当前模型期望 50 维时，把主链标志转为 `float32 (N_receptor,1)` 并拼到特征末尾。旧 49 维模型继续直接使用基础特征。

DataLoader 的正式口径是 `prefetch_factor=4`、`pin_memory=true`、`persistent_workers=false`。单卡使用 16 CPU/16 workers；双卡 DDP 每个 rank 使用 16 workers，总计 32 CPU/32 workers。禁止把 worker 设为常驻，因为每个 epoch 的动态训练请求由主进程重新生成。

## 4. Stage1 V3 正式输出目录与状态

### 4.1 固定寻址

```text
<stage1_outputs>/{producer}/{split}/
├── semantic_threshold_scan.npz          # 仅 split=calibration
├── stage1_v3.json                       # 仅 split=calibration
├── stage1_v3.metrics.json               # 仅 split=calibration
├── _COMPLETE                            # 仅 split=calibration
├── evaluation/
│   ├── F1_basic.jsonl
│   ├── F1_basic.metrics.json
│   ├── F3_centered.jsonl
│   └── F3_centered.metrics.json
└── {pdb_id}/
    ├── probability/
    │   ├── probability_map.npz
    │   └── geometry.json
    ├── blobs/
    │   ├── F1_blobs.npz
    │   └── F3_blobs.npz
    ├── centered/
    │   ├── F1_basic.npz
    │   └── F3_centered.npz
    ├── evaluation/
    │   ├── F1_basic.npz
    │   └── F3_centered.npz
    └── status/
        ├── probability/
        │   ├── _COMPLETE
        │   └── performance.json
        ├── F1_blobs/_COMPLETE
        ├── F3_blobs/_COMPLETE
        ├── F1_basic/
        │   ├── _COMPLETE
        │   └── performance.json
        └── F3_centered/
            ├── _COMPLETE
            ├── _BLOB_EXCEED
            └── performance.json
```

`producer` 精确为 `unet_c1`、`Find_0`、`Find_1` 或 `Find_2`。`split` 精确为 `calibration`、`validation` 或 `train`。F1 basic 与 F3 centered 是同一 producer 的两种正式使用方式，不是固定到某个模型的分支。

### 4.2 完成标记与超量事实

PDB 角色的 `_COMPLETE` 是 UTF-8 JSON，精确包含：

- `output_role: str`：对应 `probability`、`F1_blobs`、`F3_blobs`、`F1_basic` 或 `F3_centered`。
- `completed_at_utc: str`：带 UTC 偏移的 ISO 8601 时间。

概率与 blob 完成标记在相应 NPZ 已经原子替换后建立。calibration 搜索阶段可发布不带完成标记的临时候选 centered；最终 `min_voxels` 冻结后必须重新生成正式候选集合，并在第一次正式压缩前写入冻结 `score` 与 `selected`。validation/train 同样在 centered 第一次正式压缩前完成评分。正式 NPZ 原子替换后才建立 centered 完成标记，不允许只改一维字段后再次完整解压和压缩大型 F3 文件。

`status/F3_centered/_BLOB_EXCEED` 只在满足 `fits_centered_box` 且达到当前 `min_voxels` 的 F3 blob 数严格大于显式 `blob_limit` 时存在。字段精确为：

- `pdb_id: str`：当前小写 PDB 标识。
- `centered_role: str`：固定为 `F3_centered`。
- `eligible_blob_count: int`：满足 BOX 包络和当前 `min_voxels` 的候选数。
- `limit: int`：当前配置的 `blob_limit`。

该文件只记录计算量事实，不是终态；生产者仍继续生成 F3 centered，不允许静默跳过 PDB。

calibration 的 `_COMPLETE` 是 UTF-8 JSON，字段精确为：

- `checkpoint_path: str`：当前 calibration 使用的 checkpoint 规范化绝对路径。
- `result_scope: str`：固定为 `calibration_fitted`。

完整语义扫描、冻结参数和指标都发布后才建立该文件。

每次 calibration 重跑开始时必须先撤销旧 `_COMPLETE`。validation/train 同时读取 `--calibration` 显式指定的 `stage1_v3.json` 和同目录 `_COMPLETE`，要求两者的 `checkpoint_path` 与当前命令相同，并要求完成标记的 `result_scope="calibration_fitted"`；只有 JSON 而没有完成标记时不得消费冻结参数。calibration 可以来自另一输出目录，程序不比较 calibration 目录与当前 `output_root`。PDB 角色完成标记不保存 checkpoint 路径，因此正式命令总是为当前运行重新计算概率图，不跨运行复用旧 probability `_COMPLETE`。

## 5. 完整图概率与 blobs

### 5.1 `probability/probability_map.npz`

字段集合精确为：

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `probability_map` | `float32 (D,H,W)` | 完整图配体概率；不乘受体 hardmask |
| `origin_xyz` | `float32 (3,)` | 完整图网格角点的世界 XYZ 坐标，单位 Å |
| `voxel_size_xyz` | `float32 (3,)` | 世界 XYZ 体素尺寸，单位 Å/voxel |

完整图使用无 padding 80³ 滑窗。每轴起点从 0 开始，末窗口强制落在 `axis_length-80`，确保覆盖边界。窗口重叠区使用 float32 Gaussian 权重按固定窗口顺序融合。stride 必须由配置或命令显式传入，Python 不设默认值；当前推荐配置为 ZYX `[50,50,50]`。Gaussian `sigma=0.5` 使用每轴归一化到 `[-1,1]` 的坐标。

`probability/geometry.json` 字段精确为：

- `full_shape_zyx: int[3]`：完整图 Z/Y/X 轴长。
- `origin_xyz: float[3]`：完整图网格角点的世界 XYZ 坐标，单位 Å。
- `voxel_size_xyz: float[3]`：世界 XYZ 体素尺寸，单位 Å/voxel。
- `window_shape_zyx: int[3]`：固定为 `[80,80,80]`。
- `stride_zyx: int[3]`：当前无 padding 滑窗的显式 ZYX 步长。
- `gaussian_sigma: float`：每轴归一化到 `[-1,1]` 坐标后的 Gaussian 标准差。
- `window_count: int`：当前 PDB 实际执行的窗口数。

`status/probability/performance.json` 字段精确为：

- `wall_seconds: float`：完整图推理总墙钟秒数。
- `materialize_wait_seconds: float`：等待 CPU 请求物化的累计秒数。
- `fusion_wait_seconds: float`：等待 CPU 融合线程的累计秒数。

性能字段不得混入科学 NPZ。

### 5.2 `blobs/F1_blobs.npz` 与 `blobs/F3_blobs.npz`

两份文件字段相同，差别只在来源语义阈值。F1 阈值最大化 calibration 全集的语义 micro-F1；F3 阈值最大化语义 micro-F3。

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `blob_index` | `int32 (N_blob,)` | 当前文件内从 0 开始的连续 blob 编号 |
| `voxel_offsets` | `int64 (N_blob+1,)` | 以半开区间切分 `voxel_index_global_zyx` 与 `source_probability`；首值 0，末值 L_voxel |
| `voxel_index_global_zyx` | `int32 (L_voxel,3)` | 完整图离散 ZYX 体素索引 |
| `source_probability` | `float32 (L_voxel,)` | 同一来源体素在完整概率图中的概率 |
| `source_probability_mean` | `float32 (N_blob,)` | 每个 blob 的来源概率均值 |
| `voxel_count` | `int32 (N_blob,)` | 每个 blob 的体素数 |
| `fits_centered_box` | `bool (N_blob,)` | blob 包围盒是否存在一个合法 80³ BOX 可完整容纳 |
| `centered_box_start_zyx` | `int32 (N_blob,3)` | 合法 BOX 起点；不可容纳时三个分量均为 -1 |
| `source_threshold_value` | `float32 (1,)` | 当前 F1 或 F3 冻结语义阈值 |

连通区域使用 26 邻域，保存阈值下的全部 blob，不在本阶段应用 `min_voxels`。排序键依次为来源概率均值降序和最小完整图 C-order 线性索引升序。

## 6. centered 共同字段

`F1_basic.npz` 与 `F3_centered.npz` 的共同字段集合如下。

### 6.1 条目身份、几何和选择

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `centered_box_index` | `int32 (N_entry,)` | 当前 NPZ 内从 0 开始的连续 centered 编号 |
| `source_blob_index` | `int32 (N_entry,)` | 索引同一角色 blobs 文件的 `blob_index` |
| `box_start_zyx` | `int32 (N_entry,3)` | 80³ BOX 在完整图中的 ZYX 起点 |
| `box_shape_zyx` | `uint8 (N_entry,3)` | 每项均为 `[80,80,80]` |
| `box_origin_world` | `float32 (N_entry,3)` | BOX 网格角点的世界 XYZ 坐标，单位 Å |
| `voxel_size_world` | `float32 (N_entry,3)` | 世界 XYZ 体素尺寸，单位 Å/voxel |
| `source_probability_mean` | `float32 (N_entry,)` | 来源 blob 的完整图平均概率 |
| `source_threshold_value` | `float32 (N_entry,)` | 来源 F1 或 F3 语义阈值 |
| `score` | `float32 (N_entry,)` | 当前角色冻结后的最终候选分数 |
| `selected` | `bool (N_entry,)` | 同时达到冻结分数阈值与冻结 `min_voxels` |

### 6.2 来源 blob 体素值表

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `voxel_offsets` | `int64 (N_entry+1,)` | 以半开区间切分 `voxel_index_local_zyx`、`source_probability`、`centered_probability` 和 F3 的 `voxel_final`；首值 0，末值 L_voxel |
| `voxel_index_local_zyx` | `int16 (L_voxel,3)` | 来源 blob 体素在当前 80³ BOX 中的局部 ZYX 索引 |
| `source_probability` | `float32 (L_voxel,)` | 来源完整图概率 |
| `centered_probability` | `float32 (L_voxel,)` | centered 80³ 前向在相同来源体素位置的重算概率 |

`F1_basic.npz` 的字段集合精确为 6.1 与 6.2 的字段。它执行 voxel-only centered 前向，不保存辅助受体概率、V 学习特征、A/P 表或 48³ 稠密数组。`unet_c1` 和三个 Find producer 都生成 F1 basic。

## 7. F3 centered 扩展字段

所有 producer 的 `F3_centered.npz` 在第 6 节共同字段上增加本节字段。

### 7.1 辅助受体体素与 V 特征

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `voxel_aux_offsets` | `int64 (N_entry+1,)` | 以半开区间切分 `voxel_aux_index_local_zyx` 与 `voxel_aux_probability`；首值 0，末值 L_aux |
| `voxel_aux_index_local_zyx` | `int16 (L_aux,3)` | 当前 BOX hardmask 为真的局部 ZYX 体素 |
| `voxel_aux_probability` | `float32 (L_aux,)` | 完整 wrapper 的受体辅助预测概率 |
| `voxel_final` | `float16 (L_voxel,C_voxel)` | 来源 blob 体素处的最终 V 学习特征；由 `voxel_offsets` 切分 |

辅助受体预测是独立输出，不参与配体概率 hardmask。

### 7.2 V-centered 48³ 稠密数组

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `v_centroid_local_zyx` | `float32 (N_entry,3)` | 来源 blob 的局部整数 ZYX 体素下标算术平均，单位 voxel |
| `crop_start_local_zyx` | `int16 (N_entry,3)` | 48³ 裁块在 80³ BOX 中的局部 ZYX 起点 |
| `crop_center_offset_zyx` | `float32 (N_entry,3)` | blob 中心相对 48³ 裁块中心的 ZYX 偏移，单位 voxel |
| `crop_clipped_axis_mask` | `bool (N_entry,3)` | 请求起点是否在相应轴被限制到 `[0,32]` |
| `experimental_density_48` | `float32 (N_entry,48,48,48)` | 实验密度，后三轴按 ZYX 排列 |
| `simulated_density_48` | `float32 (N_entry,48,48,48)` | 模拟密度，后三轴按 ZYX 排列 |
| `source_probability_48` | `float32 (N_entry,48,48,48)` | 完整图来源概率，后三轴按 ZYX 排列 |

三张稠密数组不使用 float16；它们保持 float32。48³ 起点按来源 blob 中心计算，再逐轴限制到 `[0,32]`，不得通过空间 padding 伪造。

### 7.3 Find A 原子表

只有 `Find_0`、`Find_1` 和 `Find_2` 出现以下整组字段；`unet_c1` 整组缺席。

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `A_offsets` | `int64 (N_entry+1,)` | 以半开区间切分 `A_global_index`、`A_coord_local_xyz`、`A_coord_centered_world`、`A_probability`、`A_feat_L0`、`A_feat_L1`、`A_feat_L2` 和 `A_feat_L3`；首值 0，末值 L_A |
| `A_global_index` | `int64 (L_A,)` | 索引 `receptor_tokens.npz` 的原子第一维 |
| `A_coord_local_xyz` | `float32 (L_A,3)` | BOX-local 连续 voxel XYZ 坐标 |
| `A_coord_centered_world` | `float32 (L_A,3)` | 相对 80³ BOX 世界中心的 XYZ 坐标，单位 Å |
| `A_probability` | `float32 (L_A,)` | 受体原子结合概率 |
| `A_feat_L0` | `float32 (L_A,50)` | 49 维基础特征与同一原子 `is_backbone` 的拼接 |
| `A_feat_L1` | `float16 (L_A,C_A1)` | 第 1 个命名 A 学习层特征 |
| `A_feat_L2` | `float16 (L_A,C_A2)` | 第 2 个命名 A 学习层特征 |
| `A_feat_L3` | `float16 (L_A,C_A3)` | interaction 前的 A 学习特征 |

A 表只保留落在核心 80³ BOX 内且到来源 blob 最近体素中心不超过 10 Å 的原子。

### 7.4 Find P 点表

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `P_offsets` | `int64 (N_entry+1,)` | 以半开区间切分 `P_coord_local_xyz`、`P_probability`、`P_feat_L2` 和 `P_feat_L3`；首值 0，末值 L_P |
| `P_coord_local_xyz` | `float32 (L_P,3)` | BOX-local 连续 voxel XYZ 坐标 |
| `P_probability` | `float32 (L_P,)` | P 点配体概率 |
| `P_feat_L2` | `float16 (L_P,C_P2)` | density/class/interface normalization 后的 P 特征 |
| `P_feat_L3` | `float16 (L_P,C_P3)` | interaction 前的 P 特征 |

### 7.5 centered 性能 JSON

`status/F1_basic/performance.json` 与 `status/F3_centered/performance.json` 字段相同：

- `wall_seconds: float`：当前角色 centered 推理总墙钟秒数。
- `materialize_wait_seconds: float`：等待 CPU 请求物化的累计秒数。
- `cpu_arrange_wait_seconds: float`：等待 CPU 整理完成的累计秒数。
- `batch_count: int`：实际执行的 centered batch 数。
- `entry_count: int`：实际进入 centered 推理的候选数。

## 8. 校准参数与版本目录

### 8.1 语义阈值扫描

`calibration/semantic_threshold_scan.npz` 的字段集合精确为：

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `denominator` | `int32` 标量 | 阈值网格分母，当前为 32768 |
| `beta_values` | `float64 (2,)` | 精确为 `[1.0,3.0]` |
| `threshold_grid_index` | `int32 (denominator+1,)` | `0..denominator` |
| `f_beta_curve` | `float64 (2,denominator+1)` | calibration 全集的语义 micro-F1 与 micro-F3 |
| `tp` | `int64 (denominator+1,)` | 每个阈值的 micro TP |
| `fp` | `int64 (denominator+1,)` | 每个阈值的 micro FP |
| `fn` | `int64 (denominator+1,)` | 每个阈值的 micro FN |

概率按 `floor(clip(p,0,1) * denominator)` 量化。并列最大值取最小网格下标，即最低阈值。

### 8.2 `calibration/stage1_v3.json`

顶层与嵌套共同字段精确为：

- `checkpoint_path: str`：当前命令使用的 checkpoint 规范化绝对路径。正式代码不计算 checkpoint、resolved config、推理配置或代码摘要，也不建立额外身份对象。
- `semantic.denominator: int`：语义阈值网格分母。
- `semantic.positive_voxel_count: int`：calibration 全集真实配体体素数。
- `semantic.negative_voxel_count: int`：calibration 全集真实背景体素数。
- `semantic.thresholds.F1.grid_index: int`：micro-F1 首个最大值的整数网格编号。
- `semantic.thresholds.F1.value: float`：F1 阈值，等于 `grid_index/denominator`。
- `semantic.thresholds.F1.micro_f_beta: float`：获胜阈值的 micro-F1。
- `semantic.thresholds.F1.tp: int`：获胜 F1 阈值的跨 PDB TP。
- `semantic.thresholds.F1.fp: int`：获胜 F1 阈值的跨 PDB FP。
- `semantic.thresholds.F1.fn: int`：获胜 F1 阈值的跨 PDB FN。
- `semantic.thresholds.F3.grid_index: int`：micro-F3 首个最大值的整数网格编号。
- `semantic.thresholds.F3.value: float`：F3 阈值，等于 `grid_index/denominator`。
- `semantic.thresholds.F3.micro_f_beta: float`：获胜阈值的 micro-F3。
- `semantic.thresholds.F3.tp: int`：获胜 F3 阈值的跨 PDB TP。
- `semantic.thresholds.F3.fp: int`：获胜 F3 阈值的跨 PDB FP。
- `semantic.thresholds.F3.fn: int`：获胜 F3 阈值的跨 PDB FN。
- `roles.F1_basic.source_threshold: float`：F1 blobs 使用的完整图概率阈值。
- `roles.F1_basic.selection.objective: float`：F1 basic 三项 micro-F1 目标之和。
- `roles.F1_basic.selection.objective_beta: float`：固定为 1.0。
- `roles.F1_basic.selection.score_mode: str`：固定为 `source_mean`。
- `roles.F1_basic.selection.score_parameters: object`：空对象。
- `roles.F1_basic.selection.score_threshold: float`：包含端点的来源均值分数下限。
- `roles.F1_basic.selection.min_voxels: int`：包含端点的来源 blob 最小体素数。
- `roles.F1_basic.selection.stages: object`：包含 `score_threshold` 与 `min_voxels` 两个阶段，子字段在下文展开。
- `roles.F3_centered.source_threshold: float`：F3 blobs 使用的完整图概率阈值。
- `roles.F3_centered.selection.objective: float`：F3 centered 三项 micro-F2 目标之和。
- `roles.F3_centered.selection.objective_beta: float`：固定为 2.0。
- `roles.F3_centered.selection.score_mode: str`：U-Net 为 `source_mean`，Find 为 `find_gaussian`。
- `roles.F3_centered.selection.score_parameters: object`：U-Net 为空对象，Find 子字段在下文展开。
- `roles.F3_centered.selection.score_threshold: float`：包含端点的最终分数下限。
- `roles.F3_centered.selection.min_voxels: int`：包含端点的来源 blob 最小体素数。
- `roles.F3_centered.selection.stages: object`：U-Net 使用 `score_threshold` 与 `min_voxels`，Find 使用 `coarse`、`refined` 与 `min_voxels`；子字段在下文展开。

同一 checkpoint 采用不同 F3/F2 目标、阈值范围、模型代码来源或其他科学配置时，调用者使用不同的 `output_root` 版本目录区分本次产物。目录名由调用者显式决定，程序不解析目录名，也不自动生成版本标识。`run` 的 calibration 来源由 `--calibration` 显式指定，可以来自另一输出目录；程序只要求 calibration JSON、同目录完成标记和当前命令的 `checkpoint_path` 直接相等。

`score_mode="source_mean"` 时的子字段精确为：

- `score_parameters: object`：空对象。
- `stages.score_threshold.objective: float`：实际来源均值阈值扫描的最优目标值。
- `stages.score_threshold.score_threshold: float`：实际来源均值中冻结的分数阈值。
- `stages.min_voxels.objective: float`：最小体素数阶段的最优目标值。
- `stages.min_voxels.min_voxels: int`：最终冻结的最小体素数。

`score_mode="find_gaussian"` 时的子字段精确为：

- `score_parameters.tau_angstrom: float`：第二阶段冻结的 Gaussian 距离参数，单位 Å。
- `score_parameters.lambda_positive: float`：第二阶段冻结的正项系数。
- `score_parameters.lambda_negative: float`：第二阶段冻结的负项系数。
- `stages.coarse.objective: float`：粗网格最优目标值。
- `stages.coarse.tau_angstrom: float`：粗网格最优距离参数。
- `stages.coarse.lambda_positive: float`：粗网格最优正项系数。
- `stages.coarse.lambda_negative: float`：粗网格最优负项系数。
- `stages.coarse.score_threshold: float`：粗网格最优分数阈值。
- `stages.refined.objective: float`：细网格最优目标值。
- `stages.refined.tau_angstrom: float`：沿用粗网格最优距离参数。
- `stages.refined.lambda_positive: float`：细网格最优正项系数。
- `stages.refined.lambda_negative: float`：细网格最优负项系数。
- `stages.refined.score_threshold: float`：细网格最优分数阈值。
- `stages.min_voxels.objective: float`：最小体素数阶段的最优目标值。
- `stages.min_voxels.min_voxels: int`：最终冻结的最小体素数。

F1 basic 与 U-Net F3 使用 `score_mode="source_mean"`。它们先扫描实际出现的来源平均概率阈值，再冻结阈值并扫描 `min_voxels=8..40`。Find F3 使用：

$$
score = source\_probability\_mean + \lambda_{positive} G_{positive} - \lambda_{negative} G_{negative}
$$

$G_{positive}$ 与 $G_{negative}$ 分别对 5 Å 内 A 原子累加 $\exp(-d^2/(2\tau^2))p$ 与 $\exp(-d^2/(2\tau^2))(1-p)$，不归一化。搜索顺序固定为：

1. 5 个 tau、5 个正 lambda、5 个负 lambda 和 4 个分数下限，共 500 组粗网格。
2. 固定第一阶段 tau，扫描两个 lambda 的 5×5 乘数和分数下限的 15 个乘数，共 375 组。
3. 冻结 Gaussian 参数，扫描 `min_voxels=8..40`。

F1 basic 最大化 semantic、coverage@0.3 和 one-to-one@0.3 三个 micro-F1 之和。F3 centered 最大化对应三个 micro-F2 之和。

### 8.3 `calibration/stage1_v3.metrics.json`

顶层字段精确为：

- `checkpoint_path: str`：当前 calibration 使用的 checkpoint 规范化绝对路径。
- `roles.F1_basic: object`：第 9.2 节定义的 F1 basic 跨 PDB 指标映射。
- `roles.F3_centered: object`：第 9.2 节定义的 F3 centered 跨 PDB 指标映射。

## 9. 评估事实与汇总

### 9.1 每 PDB 评估 NPZ

`evaluation/F1_basic.npz` 与 `evaluation/F3_centered.npz` 字段相同：

| 字段 | dtype 与形状 | 含义 |
| --- | --- | --- |
| `coverage_thresholds` | `float32 (N_threshold,)` | 当前精确为 `[0.3,0.5,0.6]` |
| `topk_values` | `int32 (N_topk,)` | 当前精确为 `[3,4,5]` |
| `occurrence_id` | `int32 (N_occ,)` | 真实配体 occurrence 标识 |
| `source_blob_index` | `int32 (N_entry,)` | 按 score 稳定降序后的来源 blob 编号 |
| `candidate_score` | `float32 (N_entry,)` | 同一排序下的分数 |
| `candidate_selected` | `bool (N_entry,)` | 同一排序下的最终选择标志 |
| `intersections` | `int64 (N_entry,N_occ)` | 候选与 occurrence 的体素交集数 |
| `pred_sizes` | `int64 (N_entry,)` | 候选体素数 |
| `gt_sizes` | `int64 (N_occ,)` | occurrence 体素数 |
| `candidate_semantic_tp` | `int64 (N_entry,)` | 每个候选与真实并集的交集数 |
| `semantic_tp` | `int64` 标量 | selected 候选并集的 TP |
| `semantic_fp` | `int64` 标量 | selected 候选并集的 FP |
| `semantic_fn` | `int64` 标量 | selected 候选并集的 FN |
| `coverage_pred_hit_mask` | `bool (N_threshold,N_entry)` | 每个候选是否存在双向覆盖达标的 occurrence |
| `coverage_gt_hit_mask` | `bool (N_threshold,N_occ)` | 是否被至少一个 selected 候选双向覆盖 |
| `one_to_one_match_offsets` | `int64 (N_threshold+1,)` | 以半开区间同时切分 `one_to_one_match_pred_index` 与 `one_to_one_match_gt_index`；首值 0，末值 L_match |
| `one_to_one_match_pred_index` | `int32 (L_match,)` | score 排序后的候选轴下标 |
| `one_to_one_match_gt_index` | `int32 (L_match,)` | `occurrence_id` 轴下标 |
| `topk_winning_candidate_rank` | `int32 (N_topk,N_threshold)` | 已选候选序列中从 0 开始的首个获胜名次，不是完整候选轴下标；未命中为 -1 |
| `topk_winning_occurrence_index` | `int32 (N_topk,N_threshold)` | 对应 `occurrence_id` 轴下标；未命中为 -1 |

双向覆盖要求 `intersection/prediction >= threshold` 且 `intersection/occurrence >= threshold`。one-to-one 使用 selected 候选上的最大二分匹配。top-K 只在 selected 候选的 score 顺序内取前 K。

### 9.2 数据划分汇总

`{producer}/{split}/evaluation/{role}.jsonl` 每行包含 `pdb_id` 与该 PDB 的完整汇总指标。`{role}.metrics.json` 保存跨 PDB 汇总。

汇总固定字段精确为：

- `pdb_count: int`：参与汇总的 PDB 数。
- `semantic_tp: int`：全部 PDB 已选候选体素并集与真实体素并集的交集数。
- `semantic_fp: int`：全部 PDB 已选候选体素并集落在真实体素并集外的体素数。
- `semantic_fn: int`：全部 PDB 真实体素并集未被已选候选覆盖的体素数。
- `semantic_micro_f1: float`：先汇总 TP、FP、FN 后计算的语义 F1。
- `semantic_micro_f2: float`：先汇总 TP、FP、FN 后计算的语义 F2。
- `semantic_macro_f1: float`：逐 PDB 语义 F1 的算术平均。
- `semantic_macro_f2: float`：逐 PDB 语义 F2 的算术平均。
- `topk_eligible_pdb_count: int`：至少含一个真实 occurrence 的 PDB 数，作为 top-K 成功率分母。

对每个 coverage 阈值 `<t>`，动态字段精确为：

- `coverage_micro_precision_<t>: float`：全部已选候选中的多对多覆盖命中比例。
- `coverage_micro_recall_<t>: float`：全部 occurrence 中的多对多覆盖命中比例。
- `coverage_micro_f1_<t>: float`：由全局 coverage precision 和 recall 计算的 F1。
- `coverage_micro_f2_<t>: float`：由全局 coverage precision 和 recall 计算的 F2。
- `coverage_macro_f1_<t>: float`：逐 PDB coverage F1 的算术平均。
- `coverage_macro_f2_<t>: float`：逐 PDB coverage F2 的算术平均。
- `one_to_one_micro_precision_<t>: float`：全部最大一对一匹配数除以已选候选数。
- `one_to_one_micro_recall_<t>: float`：全部最大一对一匹配数除以 occurrence 数。
- `one_to_one_micro_f1_<t>: float`：由全局 one-to-one precision 和 recall 计算的 F1。
- `one_to_one_micro_f2_<t>: float`：由全局 one-to-one precision 和 recall 计算的 F2。
- `one_to_one_macro_f1_<t>: float`：逐 PDB one-to-one F1 的算术平均。
- `one_to_one_macro_f2_<t>: float`：逐 PDB one-to-one F2 的算术平均。
- `top<K>_success_count_<t>: int`：前 K 个已选候选至少覆盖一个 occurrence 的 PDB 数。
- `top<K>_success_ratio_<t>: float`：前述数量除以 `topk_eligible_pdb_count`。

阈值后缀把小数点替换为 `p`，例如 0.3 写成 `0p3`。JSONL 每项另外包含 `pdb_id`，其余键与仅汇总该 PDB 时的上述字段相同。

任一分母为零时对应值定义为 0。macro 先在每个 PDB 内按相同零分母规则计算，再对 PDB 等权平均。

## 10. 正式生产入口与并发边界

唯一 shell 入口是 Pocket Plus 的 `训练与运行/sh/infer/stage1_v3.sh`。它只固定项目环境和 `configs/inference/stage1_v3.yaml`，以下值必须由命令显式提供：

- 子命令 `calibrate` 或 `run`
- checkpoint 与训练 run 的 resolved config
- producer、模型代码来源、PDB 清单、数据划分和输出根目录
- `run` 使用的 calibration JSON

`calibrate` 只允许 `split=calibration`。`run` 只允许 `split=validation` 或 `train`。正式依赖顺序为：

1. 使用当前 V3 Dataset 从完整 NPY/mmap 资产物化无 padding 80³ 滑窗。
2. GPU 生成当前 PDB 概率后，CPU 并行压缩概率并提取 F1/F3 blobs；GPU 开始下一 PDB。
3. 语义 calibration 冻结 F1/F3 阈值。
4. centered 阶段由 CPU 提前物化 batch，唯一主线程拥有 GPU，异步 D2H 后由 CPU 整理；前一 PDB 的 concatenate 与 NPZ 压缩和下一 PDB GPU 前向重叠。
5. calibration 冻结 score 与 min_voxels，发布评估事实、checkpoint 路径和冻结参数。
6. validation/train 使用 `--calibration` 显式指定且 checkpoint 路径相同的冻结参数；calibration 目录可以不同于当前输出目录。

`pending_probability_pdbs` 与 `pending_centered_pdbs` 是尚未发布的大数组上限，防止 train 清单把全部 PDB 常驻内存。推理物化线程共享同一 Dataset 与 mmap LRU；锁只保护 OrderedDict 和字节计数更新，不包围实际裁块或密度通道计算。

## 11. 跨文件对齐

### 11.1 完整图到 blobs

blob 的 `voxel_index_global_zyx` 直接索引 `probability_map`。第 i 个 blob 的值表切片由 `voxel_offsets[i:i+2]` 决定；`source_probability` 必须等于同一完整图坐标处的概率。

### 11.2 blobs 到 centered

`source_blob_index[j]` 索引同一角色 blobs 的 `blob_index`。`box_start_zyx[j] + voxel_index_local_zyx` 必须重建该来源 blob 的完整图 ZYX 坐标。`source_probability` 必须保持来源概率，`centered_probability` 是重算值，两者不得互相覆盖。

### 11.3 centered 到评估

评估 NPZ 的候选轴按 `score` 稳定降序重新排列；`source_blob_index`、`candidate_score`、`candidate_selected`、交集矩阵第一轴和全部候选侧事实使用同一顺序。`occurrence_id`、交集矩阵第二轴、`one_to_one_match_gt_index` 和 `topk_winning_occurrence_index` 使用同一 occurrence 轴顺序。

### 11.4 Find A 身份

`A_global_index` 索引 `receptor_tokens.npz` 第一维。`A_feat_L0[:,0:49]` 等于对应 `feat`，`A_feat_L0[:,49]` 等于对应 `is_backbone` 转成的 float32。该拼接只发生在模型输入与 centered 构造边界，不改写上游 receptor NPZ。

## 12. 冷读验收

一个正式 Stage1 V3 producer 至少满足：

1. calibration 四个文件齐全，`_COMPLETE.checkpoint_path` 与 `stage1_v3.json.checkpoint_path` 相同，且 `result_scope="calibration_fitted"`。
2. 概率 NPZ 字段精确为三项，有限且形状与 `geometry.json` 一致。
3. F1/F3 blobs 各自字段齐全，offsets 单调、首值 0、末值等于值表长度；blob 阶段没有应用 min_voxels。
4. F1 basic 只含第 6 节字段；F3 含第 6、7.1、7.2 节字段，Find 另含 7.3、7.4，U-Net 不含 A/P。
5. 所有 offsets/value 表逐项对齐；学习特征为 float16，概率、几何、原始密度和 `A_feat_L0` 为 float32。
6. completed centered 的候选集合已经应用最终 `min_voxels`，`score` 与 `selected` 在第一次正式压缩前使用 calibration 冻结参数写入。
7. 配体概率未乘 hardmask；F3 辅助受体字段不改变该规则。
8. 评估 NPZ 能独立还原候选/occurrence 交集、覆盖命中、一对一匹配下标、已选候选序列中从 0 开始的 top-K 获胜名次和 occurrence 轴下标。
9. `_BLOB_EXCEED` 只记录严格超量事实，存在时仍有正常 F3 centered 产物。
10. validation/train 的 calibration JSON、同目录完成标记和当前命令使用相同 checkpoint 路径；当前结果由显式 `output_root` 版本目录区分，不要求 calibration 位于该目录。

## 13. 契约边界

- 本文负责定义 Stage1 V3 训练预定位、推理产物、字段、dtype、shape、坐标、offsets、完成标记和跨文件身份对齐。
- Pocket Plus `src/inference/README.md` 负责说明模块职责、并发实现和程序入口，但不得改变本文字段。
- Stage1 网络结构、训练损失和 checkpoint 选择由对应训练计划与代码负责。
- Matcher 首先消费 `F3_centered.npz`；F1 basic 是所有 producer 共用的便捷模式。Matcher 的标签构造、batch 装配和模型逻辑由独立 Matcher 仓库负责。
- 旧组件森林、CLG、Fα 系列、Li、Selector、Selected 和 PDB 租约不再属于活动契约；需要考察时只通过 Git 历史读取。
