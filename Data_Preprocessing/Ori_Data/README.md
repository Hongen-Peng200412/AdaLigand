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
| 每个密度体素中心到最近配体原子的距离 | `density/{pdb_id}/ligand_dist.npz` |
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
python -m adaligand_preprocessing.cli.ligand_distance --help
```

服务器作业入口位于 `sbatch/`。A–G 科学计算在 `adaligand_preprocessing/stages/`，独立训练标签在 `labels/`，外部程序适配在 `external_tools/`，文件与来源身份检查在 `artifacts/`，运行状态和并发控制在 `execution/`，一次性审计或维护入口在 `ops/`，命令行参数在 `cli/`。

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
| `atom_names` | Unicode 字符串 `(M,)`，具体宽度由最长原子名决定 | 原子名，顺序与 `atoms` 完全一致；冻结样本可见 `<U2` 等 dtype |
| `atoms` | 结构化数组 `(M,)` | 重原子属性，子字段见下文 |
| `bonds` | 结构化数组 `(E,)` | 化学键，端点索引指向 `atoms` |
| `name` | 标量字符串 | 与 `object_key` 相同 |
| `residue_names` | Unicode 字符串 `(R,)`，具体宽度由最长 CCD 名称决定 | 各残基的 CCD 名称；冻结样本可见 `<U3` 等 dtype |
| `symmetries` | `float64 (0,)` | 当前未提供对称性，因此由空 Python 列表落成空数组 |
| `blobs` | `object` 标量，值为 `None` | 当前训练数据不使用的预留字段 |

`atoms` 的子字段：

| 子字段 | 类型与形状 | 含义 |
|---|---|---|
| `name` | `int8 (4,)` | 原子名字符编码；`atom_names` 已提供直接可读文本 |
| `element` | `int8` | 原子序数 |
| `charge` | `int8` | 形式电荷 |
| `coords` | `float32 (3,)` | 固定为零的占位值，不是沉积坐标 |
| `ref_pos` | `float32 (3,)` | CCD 或 RDKit 参考构象坐标，单位 Å，不是真实位置 |
| `is_present` | `bool` | 此模板文件中固定为 `False`；实际存在性见 `present_{cid}` |
| `chirality` | `bool (7,)` | 手性类别独热编码，顺序为 `CHI_OTHER`、`CHI_OCTAHEDRAL`、`CHI_TETRAHEDRAL_CW`、`CHI_TRIGONALBIPYRAMIDAL`、`CHI_UNSPECIFIED`、`CHI_TETRAHEDRAL_CCW`、`CHI_SQUAREPLANAR` |
| `in_ring` | `bool (4,)` | 是否位于 3、4、5、6 元环 |
| `residue_id` | `int32` | 所属 `components.index` |

`bonds` 的子字段：

| 子字段 | 类型与形状 | 含义 |
|---|---|---|
| `atom_1` | `int32` | 第一个端点在 `atoms` 中的位置索引 |
| `atom_2` | `int32` | 第二个端点在 `atoms` 中的位置索引 |
| `type` | `bool (5,)` | 单键、双键、三键、配位键、芳香键的独热编码 |
| `in_ring` | `bool (4,)` | 该键是否位于 3、4、5、6 元环 |

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
| `res_type` | `uint8 (N,)` | 残基类别编号；完整编号表见下文 |
| `is_backbone` | `bool (N,)` | 蛋白或核酸主链原子标记 |
| `atom_name` | `S4 (N,)` | ASCII 原子名 |
| `res_index` | `int32 (N,)` | PDB 内全局残基编号，从 0 开始 |
| `chain_index` | `int32 (N,)` | PDB 内全局链编号，从 0 开始 |
| `bond_index` | `int32 (2,E)` | 无向化学键端点，索引指向上述 `N` 个原子 |
| `bond_type` | `uint8 (E,)` | `0..6` 依次表示单键、双键、芳香键、主链键、二硫键、共价连接、三键 |
| `feat` | `float32 (N,49)` | 元素、残基、理化性质、质量和 2 Å 距离壳层计数组成的特征；完整列定义见下文 |

`res_type` 的编号固定为：`0..19 = ALA, ARG, ASN, ASP, CYS, GLN, GLU, GLY, HIS, ILE, LEU, LYS, MET, PHE, PRO, SER, THR, TRP, TYR, VAL`；`20..23 = A, C, G, U`；`24..27 = DA, DC, DG, DT`；`28 = UNK`。

`feat` 的列切片固定为：

| 列 | 含义 |
|---|---|
| `0:6` | 元素独热编码，顺序为 `C, N, O, S, P, X`；`X` 表示其他元素 |
| `6:31` | 残基独热编码，顺序为上面的 20 种氨基酸、`A, U, C, G, X`；常见修饰残基先映射到标准母体，其他残基使用 `X` |
| `31:39` | 八个残基理化标记，顺序为极性、非极性、酸性、碱性、中性、正电、负电、无电 |
| `39` | 按元素取原子质量并除以 32；未知或其他元素 `X` 使用 `14.0/32.0` |
| `40:49` | 以当前原子为中心的九个距离壳层内其他受体原子数，经 `log1p` 变换并排除当前原子自身；壳层依次为 `d <= 2`、`2 < d <= 4`、…、`16 < d <= 18` Å |

### `ligand_descriptors/{safe_object_key}.npz`

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `mol_weight` | `float32` 标量 | 分子量 |
| `n_heavy` | `int32` 标量 | 模板重原子数 |
| `n_rings` | `int32` 标量 | RDKit 环数 |
| `n_rotatable` | `int32` 标量 | RDKit 严格定义下的可旋转键数 |
| `wiener_index` | `float32` 标量 | 原子图全部无序原子对最短路长度之和 |
| `graph_energy` | `float32` 标量 | 原子邻接矩阵全部特征值绝对值之和 |
| `radius_gyration` | `float32` 标量 | `atoms.ref_pos` 相对几何中心的均方根距离，单位 Å |
| `atom_local` | `float32 (M,5)` | 依次为图偏心率、1/2/3 跳邻居数、到最近环的图距离；无环时最后一列为 `-1` |

## Stage D：受体原子标签

### `labels/{pdb_id}/atom_labels.npz`

前三个数组与 `receptor_tokens.npz` 的 `N` 个原子逐元素对齐。

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `binding_atom` | `bool (N,)` | 到任一实际存在配体重原子的最近距离不大于阈值 |
| `instance_id` | `int32 (N,)` | 结合原子对应的最近 `candidate_id`；非结合原子为 `-1` |
| `nearest_dist` | `float32 (N,)` | 到最近实际存在配体重原子的距离，单位 Å |
| `binding_threshold` | `float32` 标量 | 生成标签使用的距离阈值，正式默认值为 4.0 Å，包含等号 |
| `schema_version` | `uint16` 标量 | 文件契约版本 |
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
| `schema_version` | `uint16` 标量 | 实验密度文件契约版本 |
| `mrc_algorithm` | 字符串标量 | 当前采用的 Pocket Plus 重采样算法标识 |
| `mrc_ancestor_sha256` | 字符串标量 | 作为数值基线的 Pocket Plus 原始函数 SHA-256 |
| `mrc_vendor_sha256` | 字符串标量 | 本项目冻结副本的 SHA-256 |
| `source_origin_mode` | 字符串标量 | 读取原始 MRC 原点时采用的解释方式 |

实验图重采样复用 `geometry/legacy/mrc_pocket.py` 中冻结的 Pocket Plus 数值函数。其来源、函数摘要与允许的适配记录在同目录 `mrc_pocket.source.json`。

### `density/{pdb_id}/sim.npz`

`grid`、`voxel_size`、`origin` 必须与 `exp.npz` 的形状和物理位置一致。模拟图只使用首个模型、规范化异构位置选择和 `group_PDB=ATOM` 的受体重原子；不包含水、配体或其他 `HETATM` 原子。

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `grid` | `float32 (1,Z,Y,X)` | Chimera `molmap` 生成并对齐实验网格的受体模拟密度 |
| `voxel_size` | `float32 (3,)` | 与 `exp.npz` 相同的 XYZ 体素尺寸，单位 Å |
| `origin` | `float32 (3,)` | 与 `exp.npz` 相同的世界 XYZ 网格边界原点，单位 Å |
| `schema_version` | `uint16` 标量 | 模拟密度文件契约版本 |
| `resolution` | `float32` 标量 | `molmap` 使用的分辨率，单位 Å |
| `resolution_info_json` | 字符串标量 | `pair_list.jsonl` 中 `resolution_info` 的排序 JSON 文本 |
| `chimera_version` | 字符串标量 | 实际运行的 UCSF Chimera 版本 |
| `source_exp_identity_sha256` | 字符串标量 | 实验密度几何、来源与重采样身份的稳定 SHA-256 |
| `source_cif_sha256` | 字符串标量 | 原始 mmCIF 的 SHA-256 |
| `normalized_model_sha256` | 字符串标量 | 仅保留首模型、规范异构位置和 `group_PDB=ATOM` 重原子的模型 SHA-256 |
| `chimera_script_sha256` | 字符串标量 | 本次生成的 Chimera `molmap.py` 脚本 SHA-256 |
| `source_exp_size`、`source_exp_mtime_ns` | `int64` 标量 | `exp.npz` 的字节数和纳秒修改时间 |
| `source_cif_size`、`source_cif_mtime_ns` | `int64` 标量 | 原始 mmCIF 的字节数和纳秒修改时间 |
| `strict_hetatm_removed` | `bool` 标量 | 固定为 `True`，表示模拟图没有使用 `HETATM` |
| `model_selection` | 字符串标量 | 固定的模型、异构位置、重原子和 `group_PDB` 选择规则 |
| `generated_mrc_origin_mode` | 字符串标量 | Chimera 生成 MRC 的原点解释方式 |
| `normalized_model_n_atoms` | `int32` 标量 | 规范化受体模型中的原子数 |
| `tool_elapsed_seconds` | `float32` 标量 | 本次 Chimera 调用耗时，单位秒；属于运行信息，不参与科学计算 |
| `tool_stdout`、`tool_stderr` | 字符串标量 | 相对 `scratch` 根目录的本次工具日志路径；属于运行信息 |

模拟密度数组必须有限、非零、具有方差并在三个空间方向都有内容。

### `density/{pdb_id}/ligand_area.npz`

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `union_mask` | `bool (1,Z,Y,X)` | 所有配体实例区域的并集 |
| `mask_{cid}` | `int32 (K,3)` | 该配体区域的稀疏 `ZYX` 索引；唯一并按数组索引顺序排序 |
| `centroid_voxel_{cid}` | `float32 (3,)` | `mask_{cid}` 对应体素中心的均值，世界 XYZ，单位 Å |
| `ion_mask` | `bool (1,Z,Y,X)` | 可选升级字段；全部 `type_tag=ion` 配体区域的并集 |
| `nucleotide_like_mask` | `bool (1,Z,Y,X)` | 可选升级字段；全部 `type_tag=nucleotide_like` 配体区域的并集 |
| `peptide_like_mask` | `bool (1,Z,Y,X)` | 可选升级字段；全部 `type_tag=peptide_like` 配体区域的并集 |
| `small_molecule_mask` | `bool (1,Z,Y,X)` | 可选升级字段；全部 `type_tag=small_molecule` 配体区域的并集 |
| `sugar_mask` | `bool (1,Z,Y,X)` | 可选升级字段；全部 `type_tag=sugar` 配体区域的并集 |
| `other_mask` | `bool (1,Z,Y,X)` | 可选升级字段；全部 `type_tag=other` 配体区域的并集，仅供备用 |

每个 `occurrences.jsonl` 中的 `candidate_id` 都应有同名 `mask_{cid}` 和 `centroid_voxel_{cid}`。不同配体的区域允许重叠，`union_mask` 必须与全部稀疏索引的并集完全一致。

六个 `type_tag` 类别掩码允许全部不存在，或同时完整存在；只出现其中一部分属于契约错误。它们之间允许重叠。正式五类为 `ion`、`nucleotide_like`、`peptide_like`、`small_molecule`、`sugar`，`other_mask` 不属于五类 softmax 标签。

| 其余数组 | 类型与形状 | 含义 |
|---|---|---|
| `schema_version` | `uint16` 标量，值为 3 | 配体区域文件契约版本 |
| `source_manifest_sha256` | 字符串标量 | E1、Stage C 与所用 LigandObject 输入集合的稳定 SHA-256 |
| `grid_shape_zyx` | `int64 (3,)` | 与 `union_mask.shape[1:]` 相同的网格形状 |
| `voxel_size_xyz` | `float32 (3,)` | 与 `exp.npz.voxel_size` 相同，单位 Å |
| `origin_xyz` | `float32 (3,)` | 与 `exp.npz.origin` 相同，单位 Å |
| `origin_semantics` | 字符串标量 | `origin_xyz` 表示网格物理边界下角点 |
| `voxel_center_offset_xyz` | `float32 (3,)` | 从整数体素索引到体素中心的偏移，固定为 `(0.5,0.5,0.5)` |
| `voxel_center_formula` | 字符串标量 | 体素中心世界坐标的计算公式 |
| `voxel_center_dtype` | 字符串标量 | 计算体素中心时使用的数值类型 |
| `distance_predicate` | 字符串标量 | 体素中心是否落入原子范德华半径的包含等号判定 |
| `centroid_coordinate_system` | 字符串标量 | 固定为世界 XYZ 坐标、单位 Å |
| `mask_index_order` | 字符串标量 | 固定为 `zyx` |
| `vdw_radius_source` | 字符串标量 | 元素范德华半径的来源说明 |
| `storage_encoding` | 字符串标量 | 稀疏索引和压缩 NPZ 的存储方式 |

C/N/O/P/S 的范德华半径分别为 1.70/1.55/1.52/1.80/1.80 Å，其他有效元素使用 RDKit 周期表数值。

## 独立训练标签：`density/{pdb_id}/ligand_dist.npz`

该文件不属于 A–G 阶段状态，也不改变 `exp.npz`、`sim.npz` 或
`ligand_area.npz`。`adaligand-ligand-distance` 读取已经完成的实验密度与配体
坐标，为训练重复使用的完整实验密度网格生成一次最近距离。

| 字段 | 数据类型与形状 | 含义 |
|---|---|---|
| `distance` | `float16 (1,Z,Y,X)` | 每个实验密度体素中心到最近实际配体重原子的欧氏距离，单位 Å；没有任何 `present=True` 配体原子时全部为正无穷 |
| `schema_version` | `uint16` 标量，值为 1 | 配体距离文件契约版本 |
| `source_exp_identity_sha256` | 字符串标量 | `exp.npz` 的空间定义、来源与重采样身份摘要 |
| `source_occurrences_sha256` | 字符串标量 | `parse/{pdb_id}/occurrences.jsonl` 文件 SHA-256 |
| `source_ligand_coords_sha256` | 字符串标量 | `parse/{pdb_id}/ligand_coords.npz` 文件 SHA-256 |
| `grid_shape_zyx` | `int64 (3,)` | `distance.shape[1:]`，依次是 Z、Y、X 长度 |
| `voxel_size_xyz` | `float32 (3,)` | 与 `exp.npz.voxel_size` 完全相同的 XYZ 体素尺寸，单位 Å |
| `origin_xyz` | `float32 (3,)` | 与 `exp.npz.origin` 完全相同的网格物理边界下角点，单位 Å |
| `origin_semantics` | 字符串标量 | 固定为 `pocket_plus_corner`，表示 `origin_xyz` 是网格物理边界下角点 |
| `voxel_center_offset_xyz` | `float32 (3,)` | 固定为 `(0.5,0.5,0.5)`，用于从整数体素索引取得体素中心 |
| `voxel_center_formula` | 字符串标量 | 固定为 `origin_xyz+(index_xyz+0.5)*voxel_size_xyz` |
| `distance_unit` | 字符串标量 | 固定为 `angstrom` |

最近原子集合包含 `occurrences.jsonl` 中全部成功配体实例的实际重原子，不按
`type_tag` 排除小分子、糖、肽样配体、核苷酸样配体、离子或其他类别。每个实例
只使用 `ligand_coords.npz` 中 `present_{cid}=True` 的坐标；模板中缺失坐标的原子
不参与计算。磁盘文件不截断、不归一化，也不保存训练使用的反距离。

训练读取后可以计算 $1/(1+d/(1\,\text{Å}))$。因此正无穷距离变为有限目标 0，
不需要额外有效体素掩码。只要三个来源摘要和全部字段仍与当前输入一致，重复执行
会复用已有文件；来源变化、文件损坏或字段不合法时重新生成。

## Stage F：质量产物

### `quality_atoms/{pdb_id}.npz`

| 数组 | 类型与形状 | 含义 |
|---|---|---|
| `qscore_{cid}` | `float32 (M,)` | 与配体模板原子逐元素对齐的 Q-score；`present=False` 的位置为 `NaN` |
| `pocket_atom_site_id_{cid}` | `int64 (K,)` | 距离该配体任一实际存在重原子不大于 6 Å 的受体原子 `_atom_site.id`，按数值升序 |
| `pocket_qscore_{cid}` | `float32 (K,)` | 与 `pocket_atom_site_id_{cid}` 逐元素对齐的受体原子 Q-score |
| `pocket_radius_angstrom` | `float32` 标量 | 口袋半径，固定为 6.0 Å |
| `pocket_definition` | 字符串标量 | 口袋选择规则 |
| `schema_version` | `uint16` 标量 | 文件契约版本 |
| `source_manifest_sha256` | 字符串标量 | Stage F 输入集合的稳定摘要 |
| `mapping_method` | 字符串标量 | MapQ 原子与原始 mmCIF、配体模板的精确对应方法 |
| `mapq_sigma` | `float32` 标量 | MapQ `sigma` 参数，当前为 0.4 |
| `mapq_np` | `int16` 标量 | MapQ `numPts` 参数，当前为 8 |

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

此文件不作为训练特征。顶层字段和嵌套字段如下：

| 字段 | JSON 类型 | 含义 |
|---|---|---|
| `schema_version` | `int` | Stage F 质量产物契约版本 |
| `pdb_id` | `str` | 小写 PDB 编号 |
| `source_manifest_sha256` | `str` | Stage F 全部输入文件和关键身份的稳定 SHA-256 |
| `full_model_selection` | `str` | Chimera/MapQ 共用的首模型、异构位置和重原子选择规则 |
| `normalized_model_n_atoms` | `int` | 规范化全模型中的原子数 |
| `pocket_qscore` | `object` | 口袋 Q-score 定义，子字段见下文 |
| `cc_semantics` | `object` | `cc_contour`、`cc_contour_about_mean`、`cc_all`、`cc_all_about_mean` 四个键及其定义 |
| `cc_values` | `object` | 上述四个相关系数的实际值；推荐等高线不可用时前两个为 `null` |
| `contour` | `object` | 实验等高线从原始幅值映射到当前网格的完整信息，子字段见下文 |
| `chimera_version` | `str` | 实际运行的 UCSF Chimera 版本 |
| `mapq` | `object` | 固定 MapQ 来源、脚本摘要、适配和参数，子字段见下文 |
| `logs` | `object` | `molmap_stdout`、`molmap_stderr`、`cc_stdout`、`cc_stderr`、`mapq_stdout`、`mapq_stderr` 六个相对 `scratch` 根目录的日志路径 |
| `scratch` | `str` | 本次 Stage F 尝试相对 `scratch` 根目录的位置 |

`pocket_qscore` 包含：`definition`（选择规则）、`radius_angstrom`（6.0）、`atom_group`（受体原子集合）、`envelope`（到任一实际配体重原子的距离判定）、`raw_arrays`（对应的两个 NPZ 数组名）。

`contour` 包含：`value`、`value_space`、`native_value`、`canonical_value`、`scale_to_canonical`、`scale_method`、`resample_mode`、`status`、`path`、`source`。`value` 与 `canonical_value` 相同，`value_space` 固定说明它位于 Pocket Plus 重采样后的幅值空间；`native_value`、`canonical_value` 和 `value` 在推荐等高线不可用时为 `null`。

`mapq` 包含：`package`、`commit`、`zip_sha256`、`mapq_cmd_sha256`、`adapter_patch`、`cli_banner`、`sigma`、`np`。其中 `cli_banner` 是从工具日志提取的说明文字，可能随日志首行变化；固定包名、提交、压缩包摘要、入口脚本摘要和参数才共同标识实际 MapQ 实现。

## Stage G：分析与可选过滤

分析模式写入：

- `reports/runs/{run_id}/stage_g_analysis/candidates.pending.jsonl`：每条记录含 `pdb_id`、`candidate_id`、`type_tag`、`pocket_status`，以及 `q_score`、`q_score_median`、`q_score_min`、`pocket_q_score`、`pocket_q_score_median`、`pocket_q_score_min`、`pocket_n_atoms`、`map_resolution` 和四个 `cc_*` 字段。字段类型和空值含义与 `quality/{pdb_id}.jsonl` 相同。
- `reports/runs/{run_id}/stage_g_analysis/quality_distribution.json`：汇总全部可进入分析的质量记录，完整字段见下表。

| `quality_distribution.json` 字段 | JSON 类型 | 含义 |
|---|---|---|
| `run_id` | `str` | 本次 A–G 运行编号 |
| `input_manifest_sha256` | `str` | 配对清单、D/E/F 状态、质量文件、occurrence 和 provenance 的稳定 SHA-256 |
| `n_pair_pdb` | `int` | `pair_list.jsonl` 中的 PDB 数 |
| `n_eligible_pdb` | `int` | D/E/F 已成功且可进入 Stage G 的 PDB 数 |
| `n_known_failed_pdb` | `int` | D/E/F 中至少一个阶段为已解释失败的 PDB 数 |
| `n_raw_unknown_pdb` | `int` | Stage F 原始状态为未解释失败的 PDB 数，包含随后受控放行的样本 |
| `n_waived_controlled_failure_pdb` | `int` | 由指定受控失败清单精确放行的 PDB 数 |
| `controlled_failure_waiver_sha256` | `str \| null` | 受控失败清单 SHA-256；未使用时为 `null` |
| `n_candidate_occurrences` | `int` | 纳入分布统计的配体实例数 |
| `known_failure_reasons` | `object[str,int]` | 已解释失败原因到出现次数的映射 |
| `waived_controlled_failure_reasons` | `object[str,int]` | 受控失败分类到放行 PDB 数的映射 |
| `type_tag_counts` | `object[str,int]` | `type_tag` 到配体实例数的映射 |
| `pocket_status_counts` | `object[str,int]` | `pocket_status` 到配体实例数的映射 |
| `fields` | `object` | 12 个质量数值字段各自的计数和分位点，嵌套结构见下文 |
| `threshold_status` | `str` | 固定为 `explicit_schema_v2_filter_config_required`，表示分析结果尚未应用用户阈值 |

`fields` 的键固定为 `q_score`、`q_score_median`、`q_score_min`、`pocket_q_score`、`pocket_q_score_median`、`pocket_q_score_min`、`pocket_n_atoms`、`map_resolution`、`cc_contour`、`cc_contour_about_mean`、`cc_all`、`cc_all_about_mean`。每个键的值都是 `{"n_finite": int, "n_null": int, "quantiles": object[str,float]}`；`quantiles` 在没有有限值时为空对象，否则键固定为字符串 `0`、`0.01`、`0.05`、`0.1`、`0.25`、`0.5`、`0.75`、`0.9`、`0.95`、`0.99`、`1`。

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

- `reports/runs/{run_id}/stage_g/map_filter_diagnostics.jsonl`：每个 PDB 一条记录，含 `pdb_id`、`n_occurrences`、`n_empty_pocket_occurrences`、`cc_field`、`cc_value`、`cc_pass`、`resolution`、`resolution_pass`、`n_pair_pass`、`qualified_fraction`、`qualified_fraction_pass`、`map_pass`、`reasons`、`occurrences`。其中 `occurrences` 的每项含 `candidate_id`、`q_score`、`pocket_q_score`、`pocket_status`、`pair_pass`、`reasons`。
- `reports/runs/{run_id}/stage_g/excluded_maps.jsonl`：每个未通过 PDB 含 `pdb_id`、`reasons`、`n_occurrences`、`n_pair_pass`、`qualified_fraction`。
- `reports/runs/{run_id}/stage_g/summary.json`：过滤完成后的固定字段如下。
- `keep_list.jsonl`：每条记录只含 `pdb_id: str` 和 `candidate_id: int`，按二者升序排列。它是过滤成功后的完成标记；分析模式不会创建它。

| `summary.json` 字段 | JSON 类型 | 含义 |
|---|---|---|
| `run_id` | `str` | 本次 A–G 运行编号 |
| `input_manifest_sha256` | `str` | 与分析文件相同的输入集合 SHA-256 |
| `filter_manifest_sha256` | `str` | `input_manifest_sha256` 与过滤配置 SHA-256 组合后的稳定摘要 |
| `config_path` | `str` | 实际读取的 schema 2 过滤配置路径 |
| `config_sha256` | `str` | 过滤配置文件 SHA-256 |
| `config` | `object` | 由输入配置规范化得到的 15 个固定字段，完整结构见下文 |
| `n_input_maps` | `int` | 进入过滤判断的 PDB 数 |
| `n_passing_maps` | `int` | 通过全部 PDB 级条件的 PDB 数 |
| `n_excluded_maps` | `int` | 未通过的 PDB 数 |
| `n_input_occurrences` | `int` | 进入过滤判断的配体实例数 |
| `n_kept_occurrences` | `int` | 写入 `keep_list.jsonl` 的配体实例数 |
| `n_pair_pass_occurrences` | `int` | 同时通过配体 Q-score 与口袋 Q-score 条件的配体实例数 |
| `n_empty_pocket_occurrences` | `int` | `pocket_q_score=null` 的配体实例数 |
| `n_known_failed_pdb` | `int` | D/E/F 已解释失败的 PDB 数 |
| `n_waived_controlled_failure_pdb` | `int` | 受控放行的 Stage F PDB 数 |
| `controlled_failure_waiver_sha256` | `str \| null` | 受控失败清单 SHA-256；未使用时为 `null` |
| `map_exclusion_reason_counts` | `object[str,int]` | PDB 排除原因到出现次数的映射 |

`summary.json.config` 的字段固定为：

| 字段 | JSON 类型 | 含义 |
|---|---|---|
| `schema_version` | `int` | 固定为 2 |
| `cc_field` | `str` | 本次选择的 `cc_contour`、`cc_contour_about_mean`、`cc_all` 或 `cc_all_about_mean` |
| `cc_min` | `float` | 相关系数下限 |
| `cc_comparison` | `str` | 固定为 `inclusive`，即相关系数包含等于下限的情况 |
| `selected_cc_null` | `str` | 固定为 `fail_map`，即所选相关系数为 `null` 时该 PDB 不通过 |
| `resolution_max` | `float` | 分辨率上限，单位 Å |
| `resolution_comparison` | `str` | 固定为 `inclusive`，即分辨率包含等于上限的情况 |
| `ligand_q_min` | `float` | 配体 Q-score 严格下限 |
| `pocket_q_min` | `float` | 口袋 Q-score 严格下限 |
| `pair_q_comparison` | `str` | 固定为 `strict`，即两种 Q-score 都必须严格大于对应下限 |
| `qualified_pair_fraction_min` | `float` | 一个 PDB 内合格配体实例比例的下限 |
| `qualified_pair_fraction_comparison` | `str` | 固定为 `inclusive`，即合格比例包含等于下限的情况 |
| `empty_pocket` | `str` | 固定为 `fail_and_count_denominator`，空口袋不通过且计入比例分母 |
| `keep_only_maps_that_pass` | `bool` | 固定为 `true` |
| `keep_all_occurrences_in_passing_map` | `bool` | 固定为 `true`，通过的 PDB 保留其中全部配体实例 |

## 运行状态与诊断文件

`reports/runs/{run_id}/{stage}/status.part_*.jsonl` 保存本次运行中每个 PDB 的唯一终态。`stage` 也可以是独立标签任务 `ligand_distance`。`status` 只能是 `success`、`skipped`、`known_failed`、`unknown_failed`。明确列入代码的样本不适用原因才可使用 `known_failed`；未解释的 Python 异常、字段不匹配或外部程序异常必须保持 `unknown_failed` 并阻止发布。

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
8. `ligand_dist.npz` 的 `distance.shape[1:]`、`voxel_size_xyz` 和 `origin_xyz` 分别等于 `exp.npz` 的 `grid.shape[1:]`、`voxel_size` 和 `origin`；三个来源摘要对应当前实验密度身份、occurrence 文件和配体坐标文件。

完整自动检查位于 `tests/`。Windows 测试应使用较短的临时目录，例如：

```powershell
python -m pytest --basetemp C:\t\adaligand
```
