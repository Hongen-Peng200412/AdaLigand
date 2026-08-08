# Stage3 PocketXMol Phase 1 适配与复现

本文规定 Stage3 在引入密度模块和开始微调之前必须完成的 PocketXMol docking 适配、官方行为复现和验收范围。本文是当前行为规格，不记录逐次命令、服务器作业编号或调试过程；实际执行事实记录在 `文档/exec_plan/Stage3_PocketXMol_Phase1实施.md`。

## 目标与仓库职责

Phase 1 的目标是让 Builder 使用官方 `pxm` checkpoint 和官方 docking 计算路径，在四种 docking 组合上复现 PocketXMol。Phase 1 不实现密度模块，不训练或微调模型，也不决定未来微调时 free/flexible 样本比例。

- `C:\Users\15919\Desktop\PocketXMol`：官方真值仓库，固定读取官方提交 `65488cf635c856101dbe703ac97e2f10f58e005c`，不修改源码。
- `C:\Users\15919\Desktop\AdaLigand\Data_Preprocessing\PocketXmol_compat`：唯一理解 A–G 文件结构的兼容层，负责审计、过滤和生成 PocketXMol 原生契约。
- `C:\Users\15919\Desktop\Builder`：保存挑选式复用的官方 docking 实现、官方配置、测试和学习说明。Builder 不读取 `occurrences.jsonl`、`ligand_coords.npz`、`ligand_objects` 或 `receptor_tokens.npz`，也不知道扩展受体缓存的存在。

## Phase 1 的四个连续验收阶段

四个阶段必须依次通过；前一阶段没有通过时，不开始后一阶段。

1. 小分子 free：`configs/sample/examples/dock_smallmol.yml`。
2. 小分子 flexible：`configs/sample/examples/dock_smallmol_flex.yml`。
3. 肽 free：`configs/sample/examples/dock_pep.yml` 与 `configs/sample/test/dock_pepbdb/base.yml`。
4. 肽 flexible：`configs/sample/test/dock_pepbdb/base_flex.yml`。

官方 PepBDB 数据形成官方肽复现证据。A–G `peptide_like` 样本可以验证相同的原生字段和 PepBDB 代码路径，但必须标记为 `ag_contract_path_validation`，不得写成 `official_pepbdb_reproduction`。

## A–G 配体实例的准入规则

兼容性审计覆盖 `small_molecule`、`sugar`、`peptide_like`、`nucleotide_like`、`ion` 和 `other` 六种 `type_tag`。当前 Stage3 只接纳能够无损进入官方 docking 契约的 `small_molecule` 和 `peptide_like`；每个实例保存全部适用的过滤原因，任一过滤原因存在时 `eligible=false`。

| 固定原因 | 判定条件 |
| --- | --- |
| `excluded_type_tag_ion` | `type_tag=ion`；所有离子均排除，不区分金属与非金属 |
| `unsupported_type_tag` | `sugar`、`nucleotide_like` 或 `other`；当前只接纳 `small_molecule` 与无损 `peptide_like` |
| `covalent_ligand_without_attachment_condition` | `is_covalent=true`；官方 docking 没有受体—配体共价端点条件 |
| `incomplete_heavy_atom_coordinates` | LigandObject 中任一模板重原子的 `present_{candidate_id}=false`，或对应坐标不是有限数值 |
| `unsupported_element` | 配体包含官方11种元素以外的原子；官方顺序是 C、N、O、F、P、S、Cl、B、Br、I、Se |
| `unsupported_bond_type` | 配体存在不能唯一映射为单键、双键、三键或芳香键的键，包括配位键 |
| `peptide_contract_not_lossless` | `peptide_like` 不能无歧义重建官方肽原子名、残基编号、主链标记、氨基酸类型、序列和化学图 |

缺失原子不使用 CCD 或 RDKit 参考构象补齐。非标准、支化、环化或修饰肽只有在全部官方字段能够无损重建时才可进入当前严格契约。

## 训练口袋与双受体产物

口袋选择固定采用官方训练定义：以真实结合配体的每个重原子为参考，选择残基质心到任一配体原子严格小于 10 Å 的完整受体聚合物残基。距离比较是 `<10 Å`，不是 `<=10 Å`。

选择时先读取原始 mmCIF 的真实残基身份，并对全部受体聚合物残基执行同一距离规则；不得先删掉 PocketXMol 不支持的残基再选择口袋。

兼容层为同一实例生成两种彼此隔离的受体产物：

- `pocketxmol_native`：当前唯一可被 Builder、训练、推理和指标读取的产物。选中口袋只允许20种标准氨基酸，并按官方规则重建4维元素独热、20维氨基酸独热和1维主链标记，共25维受体原子特征。
- `adaligand_extended`：保留同一几何范围内的 A–G 受体字段和49维特征，只为未来核酸或非标准受体扩展落盘。Builder 的代码、配置和 Dataset 中不出现这一名称，也不实现识别、拒绝、自动降级或回退分支。

严格分支增加以下过滤原因：

| 固定原因 | 判定条件 |
| --- | --- |
| `nucleic_acid_in_official_training_pocket` | 选中口袋包含核酸残基 |
| `modified_residue_in_official_training_pocket` | 选中口袋包含能够映射到母体、但原始身份不是20种标准氨基酸的修饰残基 |
| `nonstandard_residue_in_official_training_pocket` | 选中口袋包含其他非标准聚合物残基 |
| `empty_official_protein_pocket` | 选中范围内没有任何可构成官方蛋白口袋的标准氨基酸原子 |

兼容层生成 `pocketxmol_eligible` 与 `extended_contract_eligible` 两份按 `train`、`validation`、`calibration` 保留身份的清单。当前正式入口只读取第一份；第二份必须明确声明 `active_for_stage3=false`。

## 官方运动学字段

静态缓存保存官方运动学预处理得到的稳定前置字段，包括 `fixed_dist_torsion`、`path_mat`、`nbh_dict`、`tor_bond_mat` 和 `tor_twisted_pairs`。带随机根节点选择的 `tor_bonds_anno`、`twisted_nodes_anno` 和 `dihedral_pairs_anno` 由官方 `ConfTransform` 在 Dataset 变换时生成。

校准夹具可以额外保存一次随机状态和最终注释，用于官方仓库与 Builder 的逐位比较；这种夹具不改变训练时的现场生成规则。

## 官方模型与推理行为

Phase 1 的严格权重锚点是官方 `pxm`，`pxm_use` 只允许作为附加兼容检查。模型必须严格加载 checkpoint 中全部 `model.*` 参数；不得忽略缺失键或额外键。

Builder 直接复用官方模型、`sample_loop3`、sample noiser、100步 advance 调度、`outputs2batch`、置信度计算和重建逻辑。实现分支尽可能保持官方文件、可执行语句、类、函数和签名原样；学习分支只增加不改变行为的中文注释、Docstring、README 和来源映射。

官方发布代码中，dock 肽样本经过共享 `FeaturizeMol` 后进入模型的 `is_peptide` 为0。Phase 1 先如实复现并记录这一行为，不在兼容或 Builder 代码中提前修正。

## 验收门

每种 docking 组合均依次通过：

1. 官方 `pxm` 权重严格加载。
2. 模型输入字段、字段顺序、形状、数据类型、设备和数值比较。
3. 同一原生批次和全部随机状态下的单次前向逐位比较。
4. 100步采样中 `pos_in`、节点与键输入、原始预测、`pred_pos`、`outputs2batch` 更新值和置信度逐步比较。
5. 最终构象、化学图、重建状态、置信度和适用指标的端到端比较。

同一软件环境和设备上的主验收使用逐位相等。只有确认差异来自跨环境 CUDA 非确定性时，才另建数值等价报告；数值等价报告不能替代主验收。

## 哈希与缓存边界

正式包、Dataset、模型、长期测试和正式产物契约不实现内容哈希，不用内容哈希决定缓存复用。Git 原生提交编号用于官方源码定位和双线历史治理。

一次性核验脚本可以位于 Builder 的 `tmp/<具体任务名>/` 并使用哈希核对官方 checkpoint 或下载件。`tmp` 不被正式包导入；任务结束时一次性脚本从最终活跃代码树删除，由实现分支历史和执行记录保存核验事实。

## 明确不在 Phase 1 的内容

- 密度模块及其任何参数。
- 密度关闭时的零残差验收。
- 全参数微调、仅新参数训练、LoRA 或其他微调策略。
- 微调阶段 free/flexible 样本比例。
- 共价 docking、缺失配体原子补全、核酸受体和非标准受体扩展。
- 缺少真实结合配体时使用 `pocket_coord + 15 Å` 等定位接口；如果这部分与 docking 主路径独立，Builder 不复制该逻辑。
