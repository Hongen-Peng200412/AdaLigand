# CryoAtom2 受体 Adapter

本目录提供一个长期入口，把外部最终受体 mmCIF 转换成 Pocket Plus Stage1 可直接读取的 `receptor_tokens.npz` 和同网格模拟密度。推荐先读 `adapter.py::prepare_receptor_dataset()` 理解数据变换，再读 `run.py` 和 `sh/prepare.sh` 了解命令行与本次两个正式数据集。

本入口只替换受体结构及其模拟密度。实验密度、配体区域、配体距离和测试清单继续使用 AdaLigand 主 `Ori_Data` 的既有产物，不重新计算，也不把真实受体坐标输入 CryoAtom2 受体分支。

## 输入与稳定入口

`run.py` 接收一个 PDB 清单、CryoAtom2 结果根、参考 `Ori_Data` 根、目标 `Ori_Data` 根、Chimera 临时目录和并行参数。`sh/prepare.sh` 是 Find_1 CryoAtom2 受体实验的极简正式入口，依次生成 calibration 100 项和 `test_0` 179 项。当前入口固定同时处理 32 个 PDB，并把 BLAS 线程数固定为 1；若要在其他 CPU 规模上复用，应显式调整 `--workers`。

CryoAtom2 来源必须是每个 PDB 的 `运行日志与统计/pdb/<pdb_id>/latest.json::final_cif`，也就是该次成功运行的 `<run_stamp>.cif`，而不是同目录的 `<run_stamp>_raw.cif`。

## 目标目录

下面两棵树描述同一个目标 `Ori_Data`。第一棵集中列出长期科学输入，第二棵列出运行记录。

```text
## <科学产物>
<output_root>/
├── raw/
│   ├── pair_list.jsonl                       # 指向主 Ori_Data 的 PDB 几何与分辨率记录
│   ├── ccd_cache/                            # 指向主 Ori_Data 的 CCD 分子缓存
│   └── rcsb_mmcif/<pdb_id>.cif              # 指向当前 PDB CryoAtom2 最终受体结构
├── parse/<pdb_id>/
│   ├── receptor_tokens.npz                 # 由最终受体重新生成的十字段原子表
│   ├── occurrences.jsonl                   # 指向主 Ori_Data 的配体 occurrence 真值
│   └── ligand_coords.npz                   # 指向主 Ori_Data 的配体原子坐标真值
├── density/<pdb_id>/
│   ├── sim.npy                             # CryoAtom2 受体在实验图网格上的模拟密度
│   ├── sim.npz                             # 模拟密度的网格与生成参数
│   ├── exp.npy、exp.npz                    # 指向主 Ori_Data 的实验密度及几何
│   ├── ligand_area.npz、union_mask.npy     # 指向主 Ori_Data 的实例掩码与语义并集
│   └── ligand_dist.npy、ligand_dist.npz    # 指向主 Ori_Data 的最近配体距离监督
├── ligand_objects/                         # 指向主 Ori_Data 的去重配体对象
└── ligand_descriptors/                     # 指向主 Ori_Data 的配体描述子

## <其他文件>
<output_root>/
└── 受体适配记录.jsonl                      # 有序来源、原子数与模拟图形状（运行统计）
```

calibration 的 `output_root` 是 `/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/Ori_Data`；`test_0` 是 `/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/Ori_Data`。

除 `raw/rcsb_mmcif/<pdb_id>.cif` 指向 CryoAtom2 最终受体外，上述其他符号链接均指向参考主 `Ori_Data`。适配器不改写任何链接目标，也不链接 `labels/<pdb_id>`：该目录的受体原子轴属于真实受体，与 CryoAtom2 原子轴不兼容。

## 主要产物

### 受体原子与特征

#### `parse/<pdb_id>/receptor_tokens.npz`

一个文件对应一个预测受体。含 `_entity` 的结构沿用 Stage C polymer 选择；CryoAtom2 最终 CIF 不含 `_entity`，因此使用首个模型、规范异构位置、去除 H/D 后的 `group_PDB=ATOM` 原子。坐标不拟合、不平移、不裁剪。

| 字段 | 数据类型与形状 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `coords` | `float32`, `(N, 3)` | N 个受体重原子的世界 XYZ 坐标，单位 Å | `[[12.3,-4.5,18.9]]` |
| `element` | `uint8`, `(N,)` | 原子序数，与 `coords` 第一维逐原子对齐 | `[6]` 表示碳 |
| `res_type` | `uint8`, `(N,)` | 0–19 依次为 `ALA,ARG,ASN,ASP,CYS,GLN,GLU,GLY,HIS,ILE,LEU,LYS,MET,PHE,PRO,SER,THR,TRP,TYR,VAL`，20–27 依次为 `A,C,G,U,DA,DC,DG,DT`，28 为 `UNK` | `[0]` 表示 `ALA` |
| `is_backbone` | `bool`, `(N,)` | True 表示蛋白质或核酸主链原子 | `[true]` |
| `atom_name` | `S4`, `(N,)` | mmCIF 原子名，最长四个 ASCII 字节 | `["CA"]` |
| `res_index` | `int32`, `(N,)` | 结构内紧凑残基编号；相同数值表示同一链中的同一残基 | `[0,0,1]` 表示前两个原子同残基 |
| `chain_index` | `int32`, `(N,)` | 结构内紧凑链编号；相同数值表示属于同一条受体链 | `[0,0,1]` 表示前两个原子同链 |
| `bond_index` | `int32`, `(2, E)` | 第 0、1 轴分别保存键的两个 `coords` 原子索引，每条无向键只保存一次；无键时为 `(2, 0)` | `[[0],[1]]` 表示原子 0—1 的一条键 |
| `bond_type` | `uint8`, `(E,)` | 与 `bond_index` 第二维逐键对齐；0–6 依次为 `single,double,aromatic,backbone,disulfide,covale,triple` | `[0]` 表示单键 |
| `feat` | `float32`, `(N, 49)` | 与 `coords` 逐原子对齐；维度依次为元素 one-hot 6、残基 one-hot 25、理化性质 8、归一化质量 1、0–18 Å 九个 2 Å 壳层的 `log1p` 局部原子数 9 | 碳原子的元素分组为 `[1,0,0,0,0,0]` |

#### `density/<pdb_id>/sim.npy`

`float32 (1, Z, Y, X)`。第一维是单通道轴，后三维与同目录 `exp.npy` 逐体素对齐。Chimera 使用 `molmap <ATOM-only receptor> <resolution> onGrid <experimental grid>`，因此不会改变实验图的 shape、voxel size 或 origin。

#### `density/<pdb_id>/sim.npz`

| 字段 | 数据类型与形状 | 含义 | 示例值 |
| --- | --- | --- | --- |
| `voxel_size` | `float32`, `(3,)` | 世界 XYZ 三轴体素尺寸，单位 Å | `[1.0,1.0,1.0]` |
| `origin` | `float32`, `(3,)` | voxel-grid corner 的世界 XYZ 原点，单位 Å | `[-40.0,-40.0,-40.0]` |
| `schema_version` | `uint16` 标量 | Pocket Plus 密度元数据契约版本 | `2` |
| `resolution` | `float32` 标量 | 当前 PDB 的 `pair_list.jsonl` 分辨率，单位 Å | `3.2` |
| `resolution_info_json` | 字符串标量 | `pair_list.jsonl` 中分辨率来源对象的 JSON 文本 | `{"source":"emdb"}` |
| `chimera_version` | 字符串标量 | 实际探测到的 UCSF Chimera 版本 | `UCSF Chimera 1.19` |
| `strict_hetatm_removed` | `bool` 标量 | True 表示模拟密度未使用 HETATM | `true` |
| `model_selection` | 字符串标量 | 首模型、Stage C 异构位置、重原子与 ATOM-only 选择规则 | `first_model_stage_c_altloc_heavy_group_PDB_ATOM` |
| `generated_mrc_origin_mode` | 字符串标量 | 生成 MRC 的原点约定 | `header_origin_angstrom_nstart_zero` |
| `normalized_model_n_atoms` | `int32` 标量 | 实际传给 Chimera 的重原子数 | `9602` |

正式适配代码不保存哈希、文件修改时间或运行专属日志路径。与主 A–G `sim.npz` 相比，这些追溯字段有意缺省；Pocket Plus Stage1 使用 `schema_version`、`voxel_size`、`origin` 和独立 `sim.npy`，科学网格契约保持相同。哈希身份只在隔离门控与执行记录中核对。

### 运行统计

#### `受体适配记录.jsonl`

每行对应清单中的一个 PDB，保持原清单顺序。字段包括 `pdb_id`、`status`、`source_cif`、`receptor_atom_count`、`sim_shape_zyx`、`receptor_tokens`、`simulated_density` 和 `simulated_metadata`。例如：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `pdb_id` | `str` | 当前小写 PDB 标识 |
| `status` | `str` | `success` 表示本次生成，`skipped` 表示复用已存在的完整三件套 |
| `source_cif` | `str` | CryoAtom2 `latest.json::final_cif` 绝对路径 |
| `receptor_atom_count` | `int` | `receptor_tokens.npz::coords` 的原子轴长度 N |
| `sim_shape_zyx` | `list[int]` | `sim.npy` 的 Z、Y、X 三个空间尺寸，不含通道轴 |
| `receptor_tokens` | `str` | 相对 `output_root` 的受体 token 路径 |
| `simulated_density` | `str` | 相对 `output_root` 的 `sim.npy` 路径 |
| `simulated_metadata` | `str` | 相对 `output_root` 的 `sim.npz` 路径 |

```json
{"pdb_id":"6bgi","status":"success","source_cif":"/storage/example/6bgi/final.cif","receptor_atom_count":9602,"sim_shape_zyx":[240,280,300],"receptor_tokens":"parse/6bgi/receptor_tokens.npz","simulated_density":"density/6bgi/sim.npy","simulated_metadata":"density/6bgi/sim.npz"}
```

这是说明格式的构造示例，不是正式运行观测。`status=skipped` 表示三份受体资产已经存在并被本次复用，不表示跳过清单成员。

## 验证边界

正式生产前，隔离门控使用同一入口处理已知真实受体：十个 `receptor_tokens` 数组必须逐项相同；`sim.npy` 优先逐位相同，否则只允许预先冻结的绝对误差 `1e-6`。该门控可以计算哈希，但不能被正式模块导入，也不能改变主 `Ori_Data`。
