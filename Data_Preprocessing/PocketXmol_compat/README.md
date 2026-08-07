# PocketXMol 兼容层

本目录把 AdaLigand Stage A–G 的一个配体实例转换为 PocketXMol 官方 docking 预处理后的原生字段。一个配体实例由 `(pdb_id, candidate_id)` 唯一标识。当前 Stage3 只使用 `pocketxmol_native/`；`adaligand_extended/` 保留相同几何口袋中的 A–G 49 维受体字段，供未来扩展研究使用。

`pocketxmol_compat` 是 Stage3 中唯一读取 A–G 文件结构的包。Builder 只读取 `pocketxmol_native/`，不会识别 `adaligand_extended/`，也不会在两种契约之间切换。

逐文件字段、形状、数据类型、坐标系和清单记录见 [产物契约](README_产物契约.md)。A–G 原始字段见 [Stage A–G 数据预处理管线](../Ori_Data/README.md)。

## 输入

命令行接收三个目录和一至三份冻结实例清单：

| 参数 | 当前读取内容 |
| --- | --- |
| `--stage-c-root` | A–G 产物根目录。主适配器读取 `parse/{pdb_id}/occurrences.jsonl`、`parse/{pdb_id}/ligand_coords.npz`、`ligand_objects/*.npz`、`parse/{pdb_id}/receptor_tokens.npz` 和 `raw/rcsb_mmcif/{pdb_id}.cif`；不会读取 CCD pickle。 |
| `--pocketxmol-root` | 未修改的 PocketXMol 官方源码根目录。当前只按文件位置加载 `process/process_torsional_info.py`，预期源码提交为 `65488cf635c856101dbe703ac97e2f10f58e005c`。适配器记录这个预期提交，但不检查实际 Git 工作树。 |
| `--output-root` | 两套实例缓存、两份资格清单和审计报告的共同输出目录。 |
| `--ccd-audit` | 必需参数。指向先在 A–G 原始环境生成的版本中立 `source_chemistry_audit.json`；主适配器只读取该 JSON。 |
| `--split NAME=PATH` | 可重复传入 `train`、`validation` 或 `calibration`。`PATH` 可以是 JSONL，也可以是内容为列表的 JSON。正式 PDB 级划分条目只需包含 `pdb_id`，兼容层会从对应 `parse/{pdb_id}/occurrences.jsonl` 展开全部 `candidate_id`；显式实例级清单可以同时包含 `pdb_id` 和 `candidate_id`。 |

所有 `--split` 合并并完成 PDB 到 occurrence 的展开后，任意 `(pdb_id, candidate_id)` 只能出现一次。重复实例即使位于不同数据划分也会终止命令。适配器只从清单继承数据划分，不重新划分实例。

## 两阶段 CCD 化学审计

A–G 的 `raw/ccd_cache/*.pkl` 由较新 RDKit 写出，PocketXMol 固定环境中的较旧 RDKit 不能可靠反序列化。`adaligand-pocketxmol-ccd-audit` 必须先在产生这些 pickle 的 A–G 环境运行。它只收集冻结清单实际选中 occurrence 的 `components[].ccd_id`，重复 component 只审计一次；未选实例和未涉及 CCD 不会被扫描。

审计 JSON 为每个 CCD 保存实际 RDKit 键型名称集合、`supported` 布尔值和可读的 `error`。只有 `SINGLE`、`DOUBLE`、`TRIPLE`、`AROMATIC` 受支持；`DATIVE` 和其他未知名称属于已知不支持。pickle 缺失、版本不兼容或对象不可读属于来源化学不可验证。JSON 不保存 RDKit 对象、RDKit 版本绑定字节或内容哈希。

## 资格过滤

`reports/adaptation_audit.jsonl` 为每个正常完成审计的实例保存全部适用原因。同一实例可以有多个原因；当前正常记录的 `reasons` 为空时，`pocketxmol_eligible` 为 True。未被转换为稳定过滤原因的异常使用单独的 `internal_error` 记录，不伪装成资格过滤。

| 原因 | 触发条件 |
| --- | --- |
| `excluded_type_tag_ion` | `occurrences.jsonl` 中的 `type_tag` 为 `ion`。 |
| `unsupported_type_tag` | `type_tag` 不是 `small_molecule`、`peptide_like` 或 `ion`；`ion` 使用上一项专门原因。 |
| `covalent_ligand_without_attachment_condition` | `is_covalent=true`，而 PocketXMol docking 输入没有受体—配体共价端点条件。 |
| `ligand_atom_alignment_mismatch` | `LigandObject.atoms`、`coords_{candidate_id}` 与 `present_{candidate_id}` 的原子数或形状不一致。 |
| `incomplete_heavy_atom_coordinates` | 任一 A–G 模板原子的 `present` 为 False，或沉积 XYZ 坐标包含非有限值。适配器不从 CCD 或 RDKit 参考构象补坐标。 |
| `unsupported_element` | 配体含官方 11 种元素以外的元素。允许顺序为 `C, N, O, F, P, S, Cl, B, Br, I, Se`，对应原子序数 `6,7,8,9,15,16,17,5,35,53,34`。 |
| `unsupported_bond_type` | A–G 键不是唯一的单键、双键、三键或芳香键，或者原始 CCD RDKit 模板包含其他键型。配位键不会猜测为单键。 |
| `source_chemistry_unverifiable` | occurrence 的 component 缺少 CCD id、审计 JSON 缺少对应 CCD 记录，或记录包含 pickle 缺失、版本不兼容等可读错误。该原因不同于已经确认存在不支持键型。 |
| `peptide_contract_not_lossless` | `peptide_like` 不能无歧义重建官方肽字段。当前只接纳单链、20 种标准氨基酸、残基编号连续、每个残基具有唯一 `N/CA/C/O` 原子名，并且相邻残基间仅存在顺序 `C—N` 连接的线性肽。 |
| `official_motion_preprocess_failed` | 官方 `get_torsional_info_mol` 调用抛出异常。该原因表示两套实例产物都不生成。 |
| `nucleic_acid_in_official_training_pocket` | 按 `<10 Å` 规则选中的完整受体残基中含核酸。 |
| `modified_residue_in_official_training_pocket` | 选中范围含修饰氨基酸或其他 peptide-like 非标准残基。 |
| `nonstandard_residue_in_official_training_pocket` | 选中范围含既非20种标准氨基酸、也未被判为核酸或修饰残基的聚合物残基。 |
| `empty_official_protein_pocket` | `<10 Å` 范围没有受体聚合物残基，或范围内没有任何标准蛋白残基。前一种情况也不会生成扩展受体产物。 |
| `unsupported_receptor_element` | 完全由标准氨基酸组成的选中口袋仍出现官方口袋元素 `C, N, O, S` 之外的原子。 |

受体口袋从原始 mmCIF 恢复真实残基身份。对每个受体聚合物残基，先用原子质量计算完整残基的质量中心；只要该中心到任一真实配体原子的欧氏距离严格小于 `10 Å`，便选择该完整残基。核酸、修饰残基和非标准残基是在删除任何原子之前分类的，因此严格分支不会先丢弃不支持的残基再伪装成纯蛋白口袋。

## 两套输出

输出目录的主体为：

```text
<output-root>/
├── pocketxmol_native/<split>/<pdb_id>_<candidate_id>/
│   ├── arrays.npz
│   ├── metadata.json
│   ├── source.json
│   ├── ligand_reference.sdf
│   └── complete.json
├── adaligand_extended/<split>/<pdb_id>_<candidate_id>/
│   ├── receptor.npz
│   ├── source.json
│   └── complete.json
├── manifests/
│   ├── pocketxmol_eligible.jsonl
│   └── extended_contract_eligible.jsonl
├── records/<split>/<pdb_id>_<candidate_id>.json
└── reports/
    ├── source_chemistry_audit.json
    ├── adaptation_audit.jsonl
    └── summary.json
```

- `pocketxmol_native` 同时保存配体、严格25维受体字段、官方静态运动学字段和可选肽字段；`active_for_stage3=true`。
- `adaligand_extended` 只保存同一 `<10 Å` 几何范围内从 `receptor_tokens.npz` 原样切出的 A–G 受体字段；`active_for_stage3=false`。配体资格未通过、官方运动学预处理失败或几何范围为空时，这一目录也不会生成。
- `complete.json` 是单个实例目录的最后一个 JSON 写入。当前没有 `output-root` 级完成标记；批量调用是否有内部错误还必须结合进程退出码和 `reports/summary.json` 判断。
- `records` 中的单实例 JSON 在相应实例目录完成后写入；被过滤实例也有记录。未传 `--overwrite` 时，适配器复用该记录并核对它声称存在的目录具有 `complete.json`。

## 官方运动学的离线与运行时边界

离线适配器直接调用官方 `process.process_torsional_info.get_torsional_info_mol`，不重写转动键、图距离、固定距离矩阵或分子对称性算法。`arrays.npz` 保存以下静态结果：

- `bond_rotatable`
- `fixed_dist_torsion`
- `tor_bond_mat`
- `path_mat`
- `matches_graph`
- `matches_iso`

`metadata.json` 保存不能直接放入安全数值 NPZ 的 `nbh_dict` 和 `tor_twisted_pairs`。

下列字段不落盘：

- `tor_bonds_anno`
- `twisted_nodes_anno`
- `dihedral_pairs_anno`

它们由 PocketXMol 官方 `ConfTransform` 在每次取样时现场生成，其中包括随机根节点选择。把它们固定进训练缓存会改变官方 flexible 训练的随机过程。口袋坐标平移、口袋 k 近邻建图、批处理和 docking 加噪也不属于本离线适配器。

## 安装与运行

完整适配器依赖 A–G 的 `adaligand_preprocessing`，并因为直接加载官方运动学模块而需要 PocketXMol 的 PyTorch、PyTorch Geometric、LMDB、Pandas、RDKit、Gemmi、NetworkX 和 tqdm 依赖。CCD 审计入口不会导入这些完整适配器模块，只要求运行环境能够反序列化 A–G 自己生成的 RDKit pickle。服务器脚本通过 `PYTHONPATH` 使用同一份源码，不升级两个既有环境。

手动运行时，第一条命令必须在 A–G 原始环境执行：

```powershell
adaligand-pocketxmol-ccd-audit `
  --stage-c-root D:\data\AdaLigand\Ori_Data `
  --split train=D:\manifests\train.jsonl `
  --split validation=D:\manifests\validation.jsonl `
  --output D:\data\AdaLigand\PocketXMol_compat\reports\source_chemistry_audit.json
```

随后切换到 PocketXMol 兼容环境。若选择安装包，应先安装 A–G 包，再安装本目录：

```powershell
python -m pip install -e ..\Ori_Data
python -m pip install -e .
```

批量入口为：

```powershell
adaligand-pocketxmol-adapt `
  --stage-c-root D:\data\AdaLigand\Ori_Data `
  --output-root D:\data\AdaLigand\PocketXMol_compat `
  --pocketxmol-root C:\Users\15919\Desktop\PocketXMol `
  --ccd-audit D:\data\AdaLigand\PocketXMol_compat\reports\source_chemistry_audit.json `
  --split train=D:\manifests\train.jsonl `
  --split validation=D:\manifests\validation.jsonl `
  --split calibration=D:\manifests\calibration.jsonl `
  --workers 192
```

`--workers 0` 使用 `os.cpu_count()` 返回的全部逻辑 CPU。批量命令使用 `ProcessPoolExecutor`，结果在写入清单前按 `(split, pdb_id, candidate_id)` 排序。任一 worker 出现未转换为过滤原因的异常时，命令仍写审计和汇总文件，但退出码为 `2`；没有这类异常时退出码为 `0`。

默认行为按 `records/<split>/<instance>.json` 续跑：记录存在且它声明的实例目录都有 `complete.json` 时直接返回既有结果。`--overwrite` 忽略单实例记录并重新计算、原子替换同名 NPZ/JSON，`ligand_reference.sdf` 也会重新写入。正式代码不比较内容哈希；输入或官方源码发生改变时，调用者必须选择新输出根或显式传入 `--overwrite`。

## 测试

在依赖完整的环境中，从本目录运行：

```powershell
python -m pytest
```

当前测试覆盖：

- 清单只涉及 CCD 的去重审计，以及支持键、配位键、未知键和缺失 pickle 的分类；
- 主适配阶段只读取审计 JSON，不调用 CCD `pickle.load`；
- 线性标准肽的无损准入和环化肽拒绝；
- 无向 A–G 键转换为排序后的双向 PocketXMol 键；
- 官方氨基酸编号与肽序列重建；
- 受体残基质量中心使用严格 `<10 Å` 边界；
- 原始核酸、修饰残基和非标准残基分类；
- 扩展49维受体切片保持原数组值，并正确重编号口袋内部化学键。

当前测试尚未覆盖真实 A–G 实例的端到端适配、CLI 多进程写入、官方运动学模块调用或 Builder 消费。不能用现有单元测试替代 Phase 1 的四种 docking 复现验收。

## 相关文档

- 当前规格：`../../文档/规划文档/Stage3_PocketXMol_Phase1适配与复现.md`
- 执行记录：`../../文档/exec_plan/Stage3_PocketXMol_Phase1实施.md`
- 详细产物字段：[README_产物契约.md](README_产物契约.md)
