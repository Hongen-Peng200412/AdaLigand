# AdaLigand A–G 数据预处理管线

本目录把 `(EMDB, PDB)` 样本对转换为配体化学对象、受体原子、监督标签、密度网格、质量指标和可选过滤结果。本文只说明稳定入口和正式产物；某次运行的作业编号、异常处理经过与恢复证据保存在 `reports/runs/{run_id}/` 及项目执行记录中。

## 快速定位

所有数据路径都相对于命令参数 `--root` 指定的数据根目录。

| 想找的内容 | 文件 |
|---|---|
| EMDB 与 PDB 样本清单、分辨率 | `raw/pair_list.jsonl` |
| 一个 PDB 中有哪些配体 | `parse/{pdb_id}/occurrences.jsonl` |
| 配体在沉积结构中的真实坐标 | `parse/{pdb_id}/ligand_coords.npz` |
| 受体重原子、连接与特征 | `parse/{pdb_id}/receptor_tokens.npz` |
| 去重后的配体化学结构 | `ligand_objects/{safe_object_key}.npz` |
| 去重后的配体描述子 | `ligand_descriptors/{safe_object_key}.npz` |
| 受体原子的结合位点标签 | `labels/{pdb_id}/atom_labels.npz` |
| 实验密度网格 | `density/{pdb_id}/exp.npz` |
| 受体模拟密度网格 | `density/{pdb_id}/sim.npz` |
| 配体占据的稀疏体素 | `density/{pdb_id}/ligand_area.npz` |
| 配体与受体口袋的逐原子 Q-score | `quality_atoms/{pdb_id}.npz` |
| 每个配体的聚合质量指标 | `quality/{pdb_id}.jsonl` |
| 质量指标的输入和工具身份 | `quality/{pdb_id}.provenance.json` |
| 显式过滤配置选出的最终主键 | `keep_list.jsonl` |

`pdb_id` 始终使用小写。`candidate_id` 是一个 PDB 内配体实例的稳定整数编号。下文用 `cid` 表示某个具体的 `candidate_id`，用 `M` 表示配体模板重原子数，用 `N` 表示受体重原子数，用 `Z,Y,X` 表示数组轴顺序。

## 安装与入口

在本目录执行：

```powershell
python -m pip install -e .
python -m adaligand_preprocessing.cli.stage_a --help
python -m adaligand_preprocessing.cli.stage_b --help
python -m adaligand_preprocessing.cli.stage_c --help
python -m adaligand_preprocessing.cli.stage_d --help
python -m adaligand_preprocessing.cli.stage_e --help
python -m adaligand_preprocessing.cli.stage_f --help
python -m adaligand_preprocessing.cli.stage_g --help
```

服务器作业入口位于 `sbatch/`。科学计算在 `adaligand_preprocessing/stages/`，外部程序适配在 `external_tools/`，文件与来源身份检查在 `artifacts/`，运行状态和并发控制在 `execution/`，一次性审计或维护入口在 `ops/`，命令行参数在 `cli/`。

## 全局数据约定

- 世界坐标顺序是 `XYZ`，单位是 Å；密度数组顺序是 `(通道,Z,Y,X)`。
- `origin` 是网格物理边界的下角点。索引 `(x,y,z)` 对应体素中心 `origin + (index + 0.5) * voxel_size`。
- 除 `ligand_objects/*.npz` 外，读取 NPZ 时使用 `allow_pickle=False`。配体化学对象含对象数组，因此必须使用 `allow_pickle=True`。
- NPZ 默认用 `numpy.savez` 原子写入。`ligand_area.npz` 是唯一例外：它使用 ZIP DEFLATED 压缩，写后完整重读验证，再原子替换目标文件。
- 数值缺失使用 `NaN`，JSON 缺失使用 `null`，不适用的文本和列表分别使用空字符串和空列表。具体字段的空值含义见对应表格。
- JSONL 文件的每条记录都是一个完整 JSON 对象；记录之间不共享隐含状态。

## Stage A–C：样本、配体与受体

### `raw/pair_list.jsonl`

每条记录表示一个 `(EMDB, PDB)` 样本对。

| 字段 | 类型 | 含义 |
|---|---|---|
| `emdb_id` | `str` | 带 `EMD-` 前缀的 EMDB 编号 |
| `pdb_id` | `str` | 小写 PDB 编号 |
| `resolution` | `float \| null` | 选定的密度图分辨率，单位 Å；无法可靠选择时为 `null` |
| `resolution_info` | `object` | 分辨率候选、来源路径、选择规则和状态；用于追查 `resolution` 的来源 |

`resolution_info` 的主要字段是 `selected`、`status`、`selected_source`、`selection_rule` 和 `candidates`。每个候选包含 `source`、`value`、`units`、`method`、`path`。

原始下载件位于：

- `raw/rcsb_mmcif/{pdb_id}.cif`：RCSB 完整结构文件。
- `raw/emdb_maps/emd_{num}.map.gz`：EMDB 原始密度图，`num` 是去掉 `EMD-` 的数字部分。
- `raw/ccd_cache/{ccd_id}.pkl`：化学组分字典模板缓存。

### `parse/{pdb_id}/occurrences.jsonl`

每条记录表示一个共价连通的配体整体。单个化学组分和由多个残基连接成的糖链都各算一个配体实例。

| 字段 | 类型 | 含义 |
|---|---|---|
| `pdb_id` | `str` | 小写 PDB 编号 |
| `candidate_id` | `int` | 该 PDB 内的稳定编号，从 0 开始；解析失败的候选不会落盘，因此编号可能不连续 |
| `kind` | `str` | `CCD` 表示单残基；`BRANCHED` 表示多残基共价整体 |
| `object_key` | `str` | 跨 PDB 去重的配体化学结构键 |
| `type_tag` | `str` | `small_molecule`、`sugar`、`peptide_like`、`nucleotide_like`、`ion` 或 `other` |
| `is_covalent` | `bool` | 配体是否与受体聚合物形成共价键 |
| `polymer_length` | `int` | 组成配体的残基数；`CCD` 固定为 1 |
| `n_heavy_atoms` | `int` | 沉积结构中实际存在的重原子数 |
| `components` | `list[object]` | 组成配体的残基，按 `index` 排序 |
| `inter_bonds` | `list[list]` | 残基间共价键；`CCD` 使用空列表 |

`components` 每项包含 `index`、`ccd_id`、`label_asym_id`、`label_seq_id`、`auth_asym_id`、`auth_seq_id`、`icode`。`label_*` 是 mmCIF 内部编号，`auth_*` 是作者在 PDB 中使用的编号。`inter_bonds` 的一项 `[1,"O4",2,"C1"]` 表示第 1 个残基的 `O4` 与第 2 个残基的 `C1` 相连。

单残基的 `object_key` 形如 `CCD:NAG`。多残基的键形如 `BRANCHED:NAG-NAG-BMA:abcdef`，末尾六位十六进制字符区分相同残基序列的不同连接结构。文件名会把 `:`、`/` 等字符替换为 `_`，所得名称称为 `safe_object_key`。

### `ligand_objects/{safe_object_key}.npz`

每个 `object_key` 全局只保存一份。此文件描述化学模板，不描述配体在具体 PDB 中的位置。

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `smiles` | 标量字符串 | 单残基配体的 SMILES；多残基配体为空字符串 |
| `atom_names` | `object (M,)` | 原子名，顺序与 `atoms` 完全一致 |
| `atoms` | 结构化数组 `(M,)` | 重原子属性，子字段见下文 |
| `bonds` | 结构化数组 `(E,)` | 化学键，端点索引指向 `atoms` |
| `name` | 标量字符串 | 与 `object_key` 相同 |
| `residue_names` | `object (R,)` | 各残基的 CCD 名称 |
| `symmetries` | 空列表 | 当前未提供对称性 |
| `blobs` | `None` | 当前训练数据不使用的预留字段 |

`atoms` 的子字段：

| 子字段 | 类型与形状 | 含义 |
|---|---|---|
| `name` | `int8 (4,)` | 原子名字符编码；`atom_names` 已提供直接可读文本 |
| `element` | `int8` | 原子序数 |
| `charge` | `int8` | 形式电荷 |
| `coords` | `float32 (3,)` | 固定为零的占位值，不是沉积坐标 |
| `ref_pos` | `float32 (3,)` | CCD 或 RDKit 参考构象坐标，单位 Å，不是真实位置 |
| `is_present` | `bool` | 此模板文件中固定为 `False`；实际存在性见 `present_{cid}` |
| `chirality` | `bool (7,)` | 手性类别的独热编码 |
| `in_ring` | `bool (4,)` | 是否位于 3、4、5、6 元环 |
| `residue_id` | `int32` | 所属 `components.index` |

`bonds` 的子字段是 `atom_1`、`atom_2`、`type`、`in_ring`。`atom_1` 和 `atom_2` 是 `atoms` 的位置索引；`type` 是单键、双键、三键、配位键、芳香键的五维独热编码。

### `parse/{pdb_id}/ligand_coords.npz`

一个 PDB 的所有配体实例共用此文件，通过数组名中的 `cid` 区分。三组数组都与对应 `ligand_objects` 的 `atoms` 逐元素对齐。

| 数组名 | 类型与形状 | 含义 |
|---|---|---|
| `coords_{cid}` | `float32 (M,3)` | 沉积结构中的世界 XYZ 坐标，单位 Å；缺失模板原子填 `NaN` |
| `present_{cid}` | `bool (M,)` | 模板原子是否出现在沉积结构中 |
| `centroid_atom_{cid}` | `float32 (3,)` | `coords_{cid}[present_{cid}]` 的几何中心，世界 XYZ，单位 Å |

`M` 是模板重原子数，可能大于 `occurrences.jsonl` 中的 `n_heavy_atoms`。需要真实配体位置时必须使用 `coords_{cid}`，不能使用 `ligand_objects` 中的 `coords` 或 `ref_pos`。

### `parse/{pdb_id}/receptor_tokens.npz`

以下数组以同一个受体重原子顺序对齐；`bond_index` 单独描述这些原子之间的连接。

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `coords` | `float32 (N,3)` | 世界 XYZ 坐标，单位 Å |
| `element` | `uint8 (N,)` | 原子序数 |
| `res_type` | `uint8 (N,)` | 残基类别编号 |
| `is_backbone` | `bool (N,)` | 蛋白或核酸主链原子标记 |
| `atom_name` | `S4 (N,)` | ASCII 原子名 |
| `res_index` | `int32 (N,)` | PDB 内全局残基编号，从 0 开始 |
| `chain_index` | `int32 (N,)` | PDB 内全局链编号，从 0 开始 |
| `bond_index` | `int32 (2,E)` | 无向化学键端点，索引指向上述 `N` 个原子 |
| `bond_type` | `uint8 (E,)` | `0..6` 依次表示单键、双键、芳香键、主链键、二硫键、共价连接、三键 |
| `feat` | `float32 (N,49)` | 元素、残基、理化性质、质量和 2 Å 邻域计数组成的特征 |

### `ligand_descriptors/{safe_object_key}.npz`

`mol_weight`、`n_heavy`、`n_rings`、`n_rotatable`、`wiener_index`、`graph_energy`、`radius_gyration` 都是标量。`atom_local` 是 `float32 (M,5)`，依次保存图偏心率、1/2/3 跳邻居数、最近环的图距离；无环时最近环距离为 `-1`。

## Stage D：受体原子标签

### `labels/{pdb_id}/atom_labels.npz`

前三个数组与 `receptor_tokens.npz` 的 `N` 个原子逐元素对齐。

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `binding_atom` | `bool (N,)` | 到任一实际存在配体重原子的最近距离不大于阈值 |
| `instance_id` | `int32 (N,)` | 结合原子对应的最近 `candidate_id`；非结合原子为 `-1` |
| `nearest_dist` | `float32 (N,)` | 到最近实际存在配体重原子的距离，单位 Å |
| `binding_threshold` | `float32` 标量 | 生成标签使用的距离阈值，正式默认值为 4.0 Å，包含等号 |
| `schema_version` | 整数标量 | 文件契约版本 |
| `source_receptor_sha256` | 字符串标量 | `receptor_tokens.npz` 的 SHA-256 |
| `source_ligand_coords_sha256` | 字符串标量 | `ligand_coords.npz` 的 SHA-256 |

完全等距时先选择较小的 `candidate_id`，再用配体原子在拼接数组中的稳定位置决定。

## Stage E：密度与配体区域

### `density/{pdb_id}/exp.npz`

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `grid` | `float32 (1,Z,Y,X)` | 实验密度；保持原始幅值，不归一化 |
| `voxel_size` | `float32 (3,)` | 实际 XYZ 体素尺寸，单位 Å；接近但不保证严格等于 1.0 |
| `origin` | `float32 (3,)` | 网格物理边界下角点，世界 XYZ，单位 Å |
| `target_voxel_size` | `float32` 标量 | 重采样目标，当前为 1.0 Å |
| `contour_native`、`contour` | `float32` 标量 | EMDB 主图推荐等高线；无法唯一选择时为 `NaN` |
| `contour_scale_to_canonical` | `float64` 标量 | 原始图到当前网格的幅值比例 |
| `contour_canonical` | `float32` 标量 | `contour_native * contour_scale_to_canonical`；Stage F 实际使用的阈值 |
| `contour_present` | `bool` 标量 | 推荐等高线是否可用 |
| `contour_status` | 字符串标量 | 等高线选择结果 |
| `contour_path`、`contour_source` | 字符串标量 | EMDB 元数据中的字段位置和来源文本 |
| `native_shape_zyx` | `int64 (3,)` | 原始密度数组形状 |
| `even_input_shape_zyx` | `int64 (3,)` | 补成偶数后的输入形状 |
| `canonical_shape_zyx` | `int64 (3,)` | 与 `grid.shape[1:]` 相同的输出形状 |
| `resample_mode` | 字符串标量 | 各轴体素是否需要重采样的模式 |
| `source_map_sha256`、`source_meta_sha256` | 字符串标量 | 原始图和 EMDB 元数据的 SHA-256 |
| `source_map_size`、`source_meta_size` | `int64` 标量 | 原始文件字节数 |
| `source_map_mtime_ns`、`source_meta_mtime_ns` | `int64` 标量 | 原始文件修改时间，纳秒 |
| `schema_version` 与 MRC 身份字段 | 标量 | 契约版本、Pocket Plus 算法来源和原点解释方式 |

实验图重采样复用 `geometry/legacy/mrc_pocket.py` 中冻结的 Pocket Plus 数值函数。其来源、函数摘要与允许的适配记录在同目录 `mrc_pocket.source.json`。

### `density/{pdb_id}/sim.npz`

`grid`、`voxel_size`、`origin` 必须与 `exp.npz` 的形状和物理位置一致。模拟图只使用首个模型、规范化异构位置选择和 `group_PDB=ATOM` 的受体重原子；不包含水、配体或其他 `HETATM` 原子。

除三个网格数组外，文件保存：`schema_version`、`resolution`、`chimera_version`、`source_exp_identity`、`source_cif_sha256`、`normalized_model_sha256`、`chimera_script_sha256`、输入文件大小和修改时间、`strict_hetatm_removed=True`、`generated_mrc_origin_mode`。数组必须有限、非零、具有方差并在三个空间方向都有内容。

### `density/{pdb_id}/ligand_area.npz`

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `union_mask` | `bool (1,Z,Y,X)` | 所有配体实例区域的并集 |
| `mask_{cid}` | `int32 (K,3)` | 该配体区域的稀疏 `ZYX` 索引；唯一并按数组索引顺序排序 |
| `centroid_voxel_{cid}` | `float32 (3,)` | `mask_{cid}` 对应体素中心的均值，世界 XYZ，单位 Å |

每个 `occurrences.jsonl` 中的 `candidate_id` 都应有同名 `mask_{cid}` 和 `centroid_voxel_{cid}`。不同配体的区域允许重叠，`union_mask` 必须与全部稀疏索引的并集完全一致。

文件还保存 `schema_version=3`、`source_manifest_sha256`、`grid_shape_zyx`、`voxel_size_xyz`、`origin_xyz`、`origin_semantics`、`voxel_center_offset_xyz`、`voxel_center_formula`、`voxel_center_dtype`、`distance_predicate`、`centroid_coordinate_system`、`mask_index_order`、`vdw_radius_source`、`storage_encoding`。C/N/O/P/S 的范德华半径分别为 1.70/1.55/1.52/1.80/1.80 Å，其他有效元素使用 RDKit 周期表数值。

## Stage F：质量产物

### `quality_atoms/{pdb_id}.npz`

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `qscore_{cid}` | `float32 (M,)` | 与配体模板原子逐元素对齐的 Q-score；`present=False` 的位置为 `NaN` |
| `pocket_atom_site_id_{cid}` | `int64 (K,)` | 距离该配体任一实际存在重原子不大于 6 Å 的受体原子 `_atom_site.id`，按数值升序 |
| `pocket_qscore_{cid}` | `float32 (K,)` | 与 `pocket_atom_site_id_{cid}` 逐元素对齐的受体原子 Q-score |
| `pocket_radius_angstrom` | `float32` 标量 | 口袋半径，固定为 6.0 Å |
| `pocket_definition` | 字符串标量 | 口袋选择规则 |
| `schema_version` | 整数标量 | 文件契约版本 |
| `source_manifest_sha256` | 字符串标量 | Stage F 输入集合的稳定摘要 |
| `mapping_method` | 字符串标量 | MapQ 原子与原始 mmCIF、配体模板的精确对应方法 |
| `mapq_sigma`、`mapq_np` | 标量 | MapQ 参数，当前分别为 0.4 和 8 |

没有受体原子落入 6 Å 范围时，两项口袋数组均为形状 `(0,)` 的对应类型空数组，不删除该配体实例。

### `quality/{pdb_id}.jsonl`

每条记录对应一个 `candidate_id`。

| 字段 | 类型 | 含义 |
|---|---|---|
| `pdb_id`、`candidate_id` | `str`、`int` | 与 `occurrences.jsonl` 的复合主键一致 |
| `q_score` | `float` | 实际存在配体原子 Q-score 的均值 |
| `q_score_median`、`q_score_min` | `float` | 配体原子 Q-score 的中位数和最小值 |
| `n_valid`、`n_present` | `int` | 有效 Q-score 数与实际存在原子数；成功产物中二者相等 |
| `pocket_q_score` | `float \| null` | 口袋受体原子 Q-score 均值；空口袋为 `null` |
| `pocket_q_score_median`、`pocket_q_score_min` | `float \| null` | 口袋中位数和最小值；空口袋为 `null` |
| `pocket_n_valid`、`pocket_n_atoms` | `int` | 有效口袋 Q-score 数与口袋原子数 |
| `pocket_status` | `str` | `ok` 或 `no_receptor_atoms_within_radius` |
| `pocket_radius_angstrom` | `float` | 6.0 |
| `map_resolution` | `float` | `pair_list.jsonl` 中选定的分辨率，单位 Å |
| `contour_status` | `str` | 实验图推荐等高线状态 |
| `cc_contour` | `float \| null` | 推荐等高线以上体素的未减均值相关系数 |
| `cc_contour_about_mean` | `float \| null` | 同一区域内两图分别减均值后的相关系数 |
| `cc_all` | `float` | 实验图非零体素的未减均值相关系数 |
| `cc_all_about_mean` | `float` | 实验图非零体素内两图分别减均值后的相关系数 |
| `livq` | `null` | 当前未提供的预留字段 |

推荐等高线不可用时，两个 `cc_contour*` 字段为 `null`；两个 `cc_all*` 字段仍必须存在。所有非空相关系数和 Q-score 都必须有限并位于 `[-1,1]`。

### `quality/{pdb_id}.provenance.json`

此文件不作为训练特征。它保存 `schema_version`、`pdb_id`、`source_manifest_sha256`、完整模型选择规则、规范化模型原子数、口袋定义、四种相关系数的精确定义和值、推荐等高线映射、Chimera 版本、MapQ 包版本与摘要、固定参数、适配标识和各外部程序日志路径，用于证明两个质量文件来自哪些输入和工具。

## Stage G：分析与可选过滤

分析模式写入：

- `reports/runs/{run_id}/stage_g_analysis/quality_distribution.json`：四种相关系数、配体 Q-score、口袋 Q-score 和分辨率的分布统计。
- `reports/runs/{run_id}/stage_g_analysis/candidates.pending.jsonl`：尚未应用用户阈值的配体候选，字段来自 `quality/*.jsonl`。

分析模式不会创建 `keep_list.jsonl`。过滤模式需要显式提供 schema 2 配置：

```json
{
  "schema_version": 2,
  "cc_field": "cc_all_about_mean",
  "cc_min": 0.6,
  "resolution_max": 5.0,
  "resolution_comparison": "inclusive",
  "ligand_q_min": 0.7,
  "pocket_q_min": 0.65,
  "qualified_pair_fraction_min": 0.8,
  "empty_pocket": "fail_and_count_denominator",
  "keep_only_maps_that_pass": true,
  "keep_all_occurrences_in_passing_map": true
}
```

以上数值仅演示字段，不是默认筛选标准。对每个配体，`q_score` 和 `pocket_q_score` 必须严格大于配置阈值；空口袋固定判为不通过。随后按 PDB 计算通过比例。选定相关系数不小于 `cc_min`、分辨率不大于 `resolution_max`、配体通过比例不小于 `qualified_pair_fraction_min` 时，该 PDB 通过。一旦 PDB 通过，`keep_list.jsonl` 保留它的全部配体实例。

过滤模式还写入：

- `reports/runs/{run_id}/stage_g/map_filter_diagnostics.jsonl`：每个 PDB 的相关系数、分辨率、通过比例、布尔判断和具体原因。
- `reports/runs/{run_id}/stage_g/excluded_maps.jsonl`：未通过的 PDB 及精简原因。
- `reports/runs/{run_id}/stage_g/summary.json`：配置摘要、输入摘要和计数。
- `keep_list.jsonl`：按 `(pdb_id,candidate_id)` 排序的最终主键记录。

## 运行状态与诊断文件

`reports/runs/{run_id}/{stage}/status.part_*.jsonl` 保存本次运行中每个 PDB 的唯一终态。`status` 只能是 `success`、`skipped`、`known_failed`、`unknown_failed`。明确列入代码的样本不适用原因才可使用 `known_failed`；未解释的 Python 异常、字段不匹配或外部程序异常必须保持 `unknown_failed` 并阻止发布。

以下文件用于诊断或审计，不是训练与推理输入：

- `reports/{pdb_id}.json`：Stage C 解析计数、警告和未能解析的配体候选。
- `reports/meta/{pdb_id}.meta.json`：EMDB 接口的原始元数据。
- `reports/resolution_summary.json`：分辨率选择状态计数。
- `reports/_failed_download*.jsonl`、`reports/_failed_parse*.jsonl`：便于人工排查的兼容失败清单；正式发布判断读取本次运行的状态文件。
- `reports/runs/{run_id}/...`：一次运行的状态、输入摘要、发布门和维护证据。
- `scratch/{run_id}/...`：Chimera、MapQ 等外部程序的隔离临时目录；正式质量产物不位于此目录。

## 跨文件对齐检查

对任一 `pdb_id` 和 `candidate_id=cid`，以下关系必须同时成立：

1. `occurrences.jsonl` 中存在该 `cid`，并给出唯一 `object_key`。
2. `ligand_objects/{safe_object_key}.npz` 的 `atoms` 长度等于 `coords_{cid}`、`present_{cid}` 和 `qscore_{cid}` 的长度。
3. `present_{cid}.sum()` 等于 `occurrences.jsonl` 的 `n_heavy_atoms`；`coords_{cid}[~present_{cid}]` 全为 `NaN`。
4. `mask_{cid}` 的三列顺序为 `ZYX`，其索引都落在 `exp.npz` 的 `grid.shape[1:]` 内。
5. `quality/{pdb_id}.jsonl` 中 `n_present == n_valid == present_{cid}.sum()`。
6. `receptor_tokens.npz`、`atom_labels.npz` 的受体数组长度一致；`binding_atom` 等价于 `nearest_dist <= binding_threshold`。
7. `exp.npz` 与 `sim.npz` 的 `grid` 形状、`voxel_size` 和 `origin` 完全一致。

完整自动检查位于 `tests/`。Windows 测试应使用较短的临时目录，例如：

```powershell
python -m pytest --basetemp C:\t\adaligand
```
