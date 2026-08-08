# PocketXMol 兼容层产物契约

本文定义 `pocketxmol_compat` 当前实际写出的文件和字段。它不记录某次运行的实例数量、作业编号或错误处理历史。适配范围、过滤规则和命令行用法见 [PocketXMol 兼容层](README.md)。

## 记号与共同约定

| 记号 | 含义 |
| --- | --- |
| $N_L$ | 配体模板重原子数。配体数组始终沿 A–G `LigandObject.atoms` 的原子顺序对齐。 |
| $E_L$ | A–G 配体无向键数。PocketXMol 原生 `bond_index` 为双向边，因此列数是 $2E_L$。 |
| $N_P$ | 严格 PocketXMol 口袋原子数。严格口袋数组共享这一原子顺序。 |
| $N_X$ | A–G 扩展口袋原子数。扩展数组共享这一原子顺序。 |
| $E_X$ | 两个端点都位于扩展口袋内的无向受体键数。 |
| $R$ | 线性标准肽残基数，仅 `type_tag=peptide_like` 时适用。 |

`pdb_id` 在输出中转为小写。单个实例目录名为 `<pdb_id>_<candidate_id>`。所有坐标均为未中心化的世界 XYZ 笛卡尔坐标，单位为 Å；本适配器不执行口袋中心平移、旋转、密度裁剪或 batch 拼接。

正式代码不计算输入文件或缓存内容哈希。`source.json` 保存可读来源路径和预期 PocketXMol Git 提交，但不证明运行时源码工作树与该提交相等。

## `reports/source_chemistry_audit.json`

该文件必须由 A–G 原始环境中的 `adaligand-pocketxmol-ccd-audit` 生成。它是主适配器的必需输入，使 PocketXMol 固定 RDKit 环境不必反序列化由其他 RDKit 版本写出的 CCD pickle。顶层字段如下：

| 字段 | JSON 类型 | 语义 |
| --- | --- | --- |
| `schema` | string | 固定为 `adaligand.pocketxmol.source_chemistry_audit`。 |
| `schema_version` | integer | 当前固定为 `1`。 |
| `allowed_bond_type_names` | list[string] | 固定允许集合按字典序保存：`AROMATIC, DOUBLE, SINGLE, TRIPLE`。 |
| `source_stage_c_root` | string | 生成审计时 A–G 产物根目录的已解析绝对路径。 |
| `selection_manifests` | list[object] | 每项含 `split` 和已解析的 `path`；仅说明本次选择来源，不包含内容哈希。 |
| `selected_instance_count` | integer | PDB 级清单按各自 `occurrences.jsonl` 展开后，合并得到的唯一 `(pdb_id, candidate_id)` 数量。显式实例级清单不再展开。 |
| `ccd_count` | integer | `ccd_records` 数量。重复 component 和跨实例重复 CCD 只计一次。 |
| `ccd_records` | list[object] | 按 `ccd_id` 排序的逐 CCD 审计记录。 |

每个 `ccd_records` 元素具有以下字段：

| 字段 | JSON 类型 | 语义 |
| --- | --- | --- |
| `ccd_id` | string | 大写 CCD id。 |
| `bond_type_names` | list[string] | 从反序列化后的 RDKit Mol 所有键读取的实际 `BondType.name` 去重集合，按字典序保存。无键分子或读取失败时为空。 |
| `supported` | boolean | 只有读取成功且实际名称全部属于允许集合时为 True；因此无键分子读取成功时为 True。 |
| `error` | string 或 null | 读取和检查成功时为 null；否则保存 `<异常类型>: <异常文本>`，供人工定位缺文件、版本不兼容或对象损坏。 |

主适配器按 occurrence 的 `components[].ccd_id` 查询该文件。记录存在、`error=null` 且 `supported=false` 时使用 `unsupported_bond_type`；component 身份缺失、记录缺失或 `error` 非空时使用 `source_chemistry_unverifiable`。主适配器不会回退读取 `raw/ccd_cache/*.pkl`。

## `pocketxmol_native/<split>/<instance>/arrays.npz`

### 配体与化学键

| 数组 | 数据类型与形状 | 语义与对齐 |
| --- | --- | --- |
| `element` | `int64 ($N_L$,)` | 原子序数。取值只来自 `6,7,8,9,15,16,17,5,35,53,34`，顺序分别对应 `C,N,O,F,P,S,Cl,B,Br,I,Se`。 |
| `bond_index` | `int64 (2,2$E_L$)` | 有向键端点，索引指向 `element`。每条 A–G 无向键展开成两个方向，再按 `source * $N_L$ + target` 升序排列；无键分子使用 `(2,0)` 空数组。 |
| `bond_type` | `int64 (2$E_L$,)` | 与 `bond_index` 每列对齐。`1,2,3,4` 分别表示单键、双键、三键和芳香键；无键分子使用 `(0,)` 空数组。 |
| `pos_all_confs` | `float32 (1,$N_L$,3)` | 唯一沉积构象。最后一维依次为世界 `X,Y,Z`；不使用 CCD/RDKit 参考构象补坐标。 |

### 官方静态运动学字段

这些字段由固定官方源码中的 `get_torsional_info_mol` 生成，适配器只把返回值拆成 NPZ 数组和 JSON 元数据。

| 数组 | 当前数据类型与形状 | 语义与对齐 |
| --- | --- | --- |
| `bond_rotatable` | `int64 (2$E_L$,)` | 与 `bond_index` 的每条有向边对齐；`1` 表示该边对应可旋转键，`0` 表示不可旋转。 |
| `fixed_dist_torsion` | `float64 ($N_L$,$N_L$)` | `1` 表示该原子对的距离在转动键运动中固定，`0` 表示位于某条转动键两侧、距离可变化。 |
| `tor_bond_mat` | 平台默认 NumPy 有符号整数 `($N_L$,$N_L$)` | 对称可旋转键邻接矩阵。当前适配器保留官方 `dtype=int`，未固定为跨平台相同位宽。 |
| `path_mat` | `float64 ($N_L$,$N_L$)` | RDKit 化学图最短路径长度矩阵。 |
| `matches_graph` | 平台默认 NumPy 有符号整数 `($M_G$,$K_G$)` | 忽略手性时的分子自同构匹配，只保留在匹配间不一致的原子列。$M_G$ 是保留的匹配数，$K_G$ 是会随匹配改变的原子数。 |
| `matches_iso` | 平台默认 NumPy 有符号整数 `($M_I$,$K_I$)` | 考虑手性时的分子自同构匹配；两个维度含义与 `matches_graph` 相同。 |

`tor_bond_mat`、`matches_graph` 和 `matches_iso` 的整数位宽取决于运行平台，因为官方函数使用 NumPy 默认整数且适配器没有再次转换。消费端不得假定它们必为 `int32` 或 `int64`；进入 PyTorch 前应沿用官方 transform 的转换方式。

### 严格受体字段

| 数组 | 数据类型与形状 | 语义与对齐 |
| --- | --- | --- |
| `pocket_element` | `int64 ($N_P$,)` | 口袋原子序数，只允许 `6,7,8,16`，分别对应 `C,N,O,S`。 |
| `pocket_pos` | `float32 ($N_P$,3)` | 与 `pocket_element` 对齐的世界 XYZ 坐标，单位 Å。 |
| `pocket_is_backbone` | `bool ($N_P$,)` | True 表示原子名属于 `CA,C,N,O`。 |
| `pocket_atom_to_aa_type` | `int64 ($N_P$,)` | 每个口袋原子所属氨基酸编号。编号 `0..19` 依次为 `ALA,CYS,ASP,GLU,PHE,GLY,HIS,ILE,LYS,LEU,MET,ASN,PRO,GLN,ARG,SER,THR,VAL,TRP,TYR`。 |
| `pocket_atom_feature_audit` | `float32 ($N_P$,25)` | 25维受体特征审计副本。`0:4` 是 `C,N,O,S` 独热编码，`4:24` 是上述20种氨基酸独热编码，索引 `24` 是主链标记。正式 FeaturizePocket 仍可从前四个原始字段重建这一特征。 |

### `peptide_like` 条件字段

以下数组只在通过无损肽审计的 `peptide_like` 实例中出现：

| 数组 | 数据类型与形状 | 语义与对齐 |
| --- | --- | --- |
| `peptide_pos` | `float32 ($N_L$,3)` | 与 `pos_all_confs[0]` 相同的世界 XYZ 坐标。 |
| `peptide_res_index` | `int64 ($N_L$,)` | 每个配体原子所属残基的从0开始编号，取值范围为 `0..$R$-1`。 |
| `peptide_is_backbone` | `bool ($N_L$,)` | True 表示配体原子名属于 `N,CA,C,O`。 |
| `peptide_atom_to_aa_type` | `int64 ($N_L$,)` | 每个配体原子的氨基酸类型；使用与 `pocket_atom_to_aa_type` 相同的官方20类编号。 |

## `pocketxmol_native/<split>/<instance>/metadata.json`

| 字段 | JSON 类型 | 语义 |
| --- | --- | --- |
| `data_id` | string | `<pdb_id>_<candidate_id>`。 |
| `pdbid` | string | 小写 PDB 标识。 |
| `smiles` | string | A–G `LigandObject` 保存的 SMILES。 |
| `num_atoms` | integer | $N_L$。 |
| `num_bonds` | integer | $E_L$，即展开为双向边之前的无向键数。 |
| `num_confs` | integer | 固定为 `1`。 |
| `i_conf_list` | list[integer] | 固定为 `[0]`；与 NPZ 中同名数组语义相同。 |
| `pocket_atom_name` | list[string] | 长度为 $N_P$，与全部 `pocket_*` 数组逐原子对齐。 |
| `nbh_dict` | object | 键是十进制原子索引字符串 `"0".."$N_L$-1"`，值是该配体原子在化学图中的直接邻居索引列表。 |
| `tor_twisted_pairs` | list[object] | 每个元素包含 `bond=[left,right]`、`left_nodes` 和 `right_nodes`。两侧节点列表不含转动键的两个端点，并按整数升序保存。 |
| `is_peptide_expected_from_official_featurizer` | integer | 固定为 `0`，记录当前官方 docking `FeaturizeMol` 最终写入模型批次的观察行为；该字段不把肽输入改成小分子。 |
| `motion_runtime_fields` | list[string] | 固定列出 `tor_bonds_anno`、`twisted_nodes_anno`、`dihedral_pairs_anno`，提醒消费端这些字段必须由官方 transform 现场生成。 |

通过肽审计的实例还包含：

| 字段 | JSON 类型 | 语义 |
| --- | --- | --- |
| `peptide_atom_name` | list[string] | 长度为 $N_L$，与配体原子数组逐原子对齐。 |
| `peptide_seq` | string | 长度为 $R$ 的单字母标准氨基酸序列。 |
| `peptide_pep_len` | integer | $R$。 |

## 原生目录中的其余文件

### `source.json`

| 字段 | JSON 类型 | 语义 |
| --- | --- | --- |
| `source_stage_c_root` | string | 运行时 `--stage-c-root` 的已解析绝对路径。 |
| `source_chemistry_audit` | string | 运行时 `--ccd-audit` 的已解析绝对路径。它是可读来源位置，不是内容哈希。 |
| `source_split` | string | `train`、`validation` 或 `calibration`。 |
| `pdb_id` | string | 小写 PDB 标识。 |
| `candidate_id` | integer | A–G occurrence 编号。 |
| `object_key` | string | 指向 A–G `ligand_objects` 化学身份的键。 |
| `type_tag` | string | A–G 配体类型。当前原生产物只可能来自 `small_molecule` 或 `peptide_like`。 |
| `pocketxmol_commit` | string | 兼容代码预期的官方源码提交，固定为 `65488cf635c856101dbe703ac97e2f10f58e005c`；它不是运行时仓库验证结果。 |
| `active_for_stage3` | boolean | 原生目录固定为 True。 |

### `ligand_reference.sdf`

一个 RDKit Mol 文件，按 A–G 配体原子顺序保存重原子化学图和唯一沉积构象。它用于化学图检查和官方原始 SDF 入口对照；Builder 正式 Dataset 应读取 `arrays.npz` 与 `metadata.json`，不能以重新解析 SDF 代替原生字段契约。

### `complete.json`

固定为 `{"complete": true}`。适配器在该实例的其他文件写入后才写它。它只表示该目录的当前写入过程到达末尾，不表示整个批量命令零内部错误，也不验证文件集合、字段或源码提交。

## `adaligand_extended/<split>/<instance>/receptor.npz`

扩展口袋与严格口袋使用同一个 `<10 Å` 完整残基选择范围。若范围内含核酸、修饰残基或非标准残基，扩展产物仍可存在，而严格产物不会生成。扩展数组从完整 `receptor_tokens.npz` 按原受体原子顺序切片，不重新计算49维特征。

| 数组 | 数据类型与形状 | 语义与对齐 |
| --- | --- | --- |
| `coords` | `float32 ($N_X$,3)` | 世界 XYZ 坐标，单位 Å。 |
| `element` | `uint8 ($N_X$,)` | 原子序数。 |
| `res_type` | `uint8 ($N_X$,)` | A–G 29类残基编号，含标准蛋白、核酸和未知类。 |
| `is_backbone` | `bool ($N_X$,)` | A–G 蛋白或核酸主链标记。 |
| `atom_name` | `S4 ($N_X$,)` | ASCII 原子名。 |
| `res_index` | `int32 ($N_X$,)` | 原 PDB 受体数组中的从0开始残基编号；切片后不重新编号。 |
| `chain_index` | `int32 ($N_X$,)` | 原 PDB 受体数组中的从0开始链编号；切片后不重新编号。 |
| `feat` | `float32 ($N_X$,49)` | A–G 49维受体特征的原值切片。完整列定义由 `../Ori_Data/README.md` 管理。 |
| `bond_index` | `int32 (2,$E_X$)` | 两个端点都在扩展口袋内的无向受体键。端点已经重编号为 `0..$N_X$-1`，指向本文件的原子数组。无口袋内部键时形状为 `(2,0)`。 |
| `bond_type` | `uint8 ($E_X$,)` | 与 `bond_index` 每列对齐；沿用 A–G 受体键类别。 |

扩展目录的 `source.json` 字段与原生目录相同，但 `active_for_stage3=false`。`complete.json` 的语义也相同。扩展目录不保存配体副本；通过相同 `<split>/<instance>` 身份与原生目录或审计清单对齐。

## 资格清单与审计报告

### `records/<split>/<instance>.json`

单实例记录使用下述“正常适配记录”schema，并额外含整数 `record_schema_version=2`。版本 `2` 表示配体来源化学资格来自外部 CCD 审计 JSON；缺少该字段的旧记录不会成为缓存命中。记录在该实例的严格/扩展目录完成标记之后原子写入；被过滤而不生成实例目录的记录也会写入。未传 `--overwrite` 时，记录是续跑判据：若它声称某套产物可用，对应相对目录必须仍有 `complete.json`，否则适配器以内部错误停止该实例，不把不完整目录静默当成缓存命中。

### 正常适配记录

`reports/adaptation_audit.jsonl`、`manifests/pocketxmol_eligible.jsonl` 和 `manifests/extended_contract_eligible.jsonl` 中的正常记录使用相同 schema：

| 字段 | JSON 类型 | 语义 |
| --- | --- | --- |
| `pdb_id` | string | 小写 PDB 标识。 |
| `candidate_id` | integer | A–G occurrence 编号。 |
| `split` | string | 继承自输入清单的 `train`、`validation` 或 `calibration`。 |
| `object_key` | string | A–G 配体化学身份键。 |
| `type_tag` | string | A–G 配体类型。审计文件保留全部输入类型。 |
| `pocketxmol_eligible` | boolean | True 表示 `pocketxmol_native/<split>/<instance>` 已生成。 |
| `extended_contract_eligible` | boolean | True 表示 `adaligand_extended/<split>/<instance>` 已生成。 |
| `active_for_stage3` | boolean | 审计记录与严格清单中等于 `pocketxmol_eligible`；扩展资格清单写出时强制为 False。 |
| `reasons` | list[string] | 全部已识别过滤原因。严格产物可用时为空；仅扩展产物可用时可包含严格受体原因。 |
| `native_path` | string 或 null | 相对 `output-root` 的正斜杠路径；无严格产物时为 null。 |
| `extended_path` | string 或 null | 相对 `output-root` 的正斜杠路径；无扩展产物时为 null。 |

三份文件的成员关系是：

- `adaptation_audit.jsonl` 包含所有正常返回的 `AdaptResult`，并在末尾追加内部错误记录；
- `pocketxmol_eligible.jsonl` 只包含 `pocketxmol_eligible=true` 的正常记录；
- `extended_contract_eligible.jsonl` 只包含 `extended_contract_eligible=true` 的正常记录，并把每条记录的 `active_for_stage3` 强制写成 False。

正常记录按 `(split, pdb_id, candidate_id)` 排序。内部错误记录也先按相同身份排序，再统一追加到正常记录之后。

### 内部错误记录

worker 抛出未转化为资格原因的异常时，`adaptation_audit.jsonl` 追加另一种记录：

| 字段 | JSON 类型 | 语义 |
| --- | --- | --- |
| `pdb_id` | string | 小写 PDB 标识。 |
| `candidate_id` | integer | A–G occurrence 编号。 |
| `split` | string | 输入数据划分。 |
| `error_type` | string | Python 异常类名。 |
| `error` | string | 异常文本。 |
| `status` | string | 固定为 `internal_error`。 |

内部错误记录没有 `object_key`、资格布尔值、`reasons` 或产物路径，也不会进入两份资格清单。

### `reports/summary.json`

| 字段 | JSON 类型 | 语义 |
| --- | --- | --- |
| `requested` | integer | 输入清单合并后的实例数。 |
| `completed` | integer | 正常返回 `AdaptResult` 的实例数，包括被过滤的实例。 |
| `internal_errors` | integer | 未转换为过滤原因的异常数。恒有 `requested = completed + internal_errors`。 |
| `pocketxmol_eligible` | integer | 严格资格清单记录数。 |
| `extended_contract_eligible` | integer | 扩展资格清单记录数。 |
| `filter_reason_counts` | object | 正常记录中各 `reasons` 字符串出现次数；同一实例的多个原因分别计数。内部错误不计入。 |
| `workers` | integer | 本次 `ProcessPoolExecutor` 使用的最大 worker 数。 |

## 跨文件对齐与消费边界

- `arrays.npz` 中所有配体数组、肽数组和运动学原子索引均指向同一个 A–G 配体原子顺序。
- `pocket_*` 数组和 `metadata.json::pocket_atom_name` 共享严格口袋原子顺序。
- 扩展 `receptor.npz` 的原子数组共享同一切片顺序；`bond_index` 已重编号，只能索引扩展口袋数组，不能再索引完整 `receptor_tokens.npz`。
- `pocketxmol_native` 与 `adaligand_extended` 通过相同的 `split` 和实例目录名对应。两者不是总能同时存在：严格资格蕴含扩展资格，但扩展资格不蕴含严格资格。
- `tor_bonds_anno`、`twisted_nodes_anno` 和 `dihedral_pairs_anno` 不在任何落盘文件中。它们由官方 `ConfTransform` 现场生成；推理态的 free 模式同样会选择随机根并生成这些注释，虽然后续 free 位置更新不使用它们，但不能省略其随机数消费。
- Builder 当前只消费 `pocketxmol_native`。`adaligand_extended` 没有 Builder 入口、回退逻辑或模式标记。

## 写入与完成语义

NPZ、JSON 和 JSONL 使用同目录临时文件与 `os.replace` 原子替换。`ligand_reference.sdf` 由 RDKit 直接写入，不使用同一原子替换封装。每个实例目录最后写 `complete.json`；批量清单和汇总在所有 worker 结束后写入。

默认续跑读取 `records/<split>/<instance>.json`，并核对其中所有 `eligible=true` 的相对目录仍有 `complete.json`。`--overwrite` 会忽略该记录并重新处理实例；NPZ、JSON 和 SDF 同名文件会被替换，但不会先递归删除整个输出根。批量命令在存在内部错误时仍写清单和报告并返回退出码 `2`；只有返回码 `0` 且 `summary.json::internal_errors=0` 才表示本次输入没有内部错误。
