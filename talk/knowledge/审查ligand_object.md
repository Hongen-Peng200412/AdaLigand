# 审查 ligand_object

> 状态：只读审计已完成。结论仅基于 train/validation、现有语言产物和既有 Matcher v3 清单；没有读取 calibration，没有重新编码语言向量，也没有修改正式产物或处理逻辑。

## 审查目标

AdaLigand 的 Stage C 使用 `object_key` 指向一份可跨 PDB 复用的 `LigandObject` 化学模板。本次审查判断该键能否承担“配体去重身份”，并分别回答：

1. 同一个 `object_key` 是否可能对应多个缩合后化学结构；
2. 现有 train/validation 数据中，这种一对多关系涉及多少身份、occurrence 和 Matcher 候选；
3. 同一个 `object_key` 是否对应多个 `PreparedLigand.smiles`，以及这些公开接口字符串产生的已有语言向量差异有多大；
4. 当前哪些产物和模型环节把 `object_key` 当作唯一身份，哪些环节已经按 occurrence 分开处理；
5. 现有证据分别支持保留粗粒度键、增加结构变体编号、改用完整分子图身份或保留一对多表示中的哪一种后续策略。

本文所称 occurrence 是一个 PDB 中由 `(pdb_id, candidate_id)` 标识的一次具体配体出现。本文所称结构歧义是同一个 `object_key` 对应多个能够由化学证据区分的缩合后分子图；不同沉积坐标、同一模板原子的不同沉积位置以及单纯的沉积原子缺失不自动计为结构歧义。

本文使用以下术语：

- CCD 是 PDB Chemical Component Dictionary 中定义的标准化学组分；
- BRANCHED 是本项目中由多个 CCD 残基通过跨组件共价键组成的 occurrence；
- CLC 是 pdbeccdutils 从完整 mmCIF 中识别的 Covalently Linked Component，即共价连接组分；
- `present` 是 LigandObject 模板原子是否在当前 occurrence 中被观测到的布尔掩码；
- SMILES 是 Simplified Molecular Input Line Entry System 字符串；canonical non-isomeric SMILES 不保留立体标记，canonical isomeric SMILES 保留可表达的立体标记。

## 本次范围

- 只读核查 AdaLigand、Matcher、Pocket_Plus 中的当前代码、Git 历史、规划、执行记录和 handoff。
- 服务器统计仅覆盖 train 与 validation；不读取 calibration。
- 重点核查 `Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/` 已生成的 `PreparedLigand.smiles`、MoLFormer 向量和 SMI-TED Light 289M 向量。
- 可以从既有 mmCIF、CCD、Stage C occurrence、LigandObject 和 `present` 掩码恢复审计签名，但不覆盖或重建正式产物。
- 只使用 CPU，任一时刻合计不超过 16 核；不使用 GPU，不重新运行语言模型。
- 本轮不修改 `object_key`、LigandObject、语言缓存、Matcher 清单、身份监督或模型逻辑。
- 本轮不做冻结 Matcher 的输入替换、预测翻转和指标敏感性实验。

## 审计口径

### 逐 occurrence 签名

每个 occurrence 至少建立以下彼此独立的签名：

- 当前 `object_key`；
- CCD 组件序列；
- `inter_bonds` 的组分编号与两端原子名；
- 能够由 CCD 与连接证据判定时的离去原子集合；
- CLC 路径或可验证后备路径得到的 canonical non-isomeric SMILES；
- canonical isomeric SMILES；
- `PreparedLigand.smiles`，即交给语言模型公开接口的字符串；
- 同一模型与权重版本生成的 `float32 (768,)` 分子向量。

本文只用同一 `object_key` 下非空 `PreparedLigand.smiles` 的去重数定义语言模型侧歧义。模型适配器记录的 `model_smiles`、SMI-TED 长度限制诊断和向量只用于解释后续影响，不反过来定义 LigandObject 歧义。occurrence 只是定位现有字符串的记录单位；坐标与 `present` 掩码不参与该定义。

`present=False` 的模板原子集合单独记录，但不能单凭该集合不同就判定 `object_key` 有歧义。只有当额外证据能够把差异归因于缩合化学，并证明最终分子图或模型输入不同，才归入结构或表示歧义。

### 统计分母

语言侧唯一歧义判据的结果至少同时报告：

- 键加权比例：对应多个非空 `PreparedLigand.smiles` 的 `object_key` 数除以具备非空字符串证据的 `object_key` 数；
- occurrence 加权比例：属于上述键的 occurrence 数除以具备非空字符串证据的 occurrence 数；
- Matcher 候选加权比例：使用上述键的候选数除以具备有效身份目标的候选数；
- 重复键条件比例：只在至少出现两次并具备非空字符串证据的 `object_key` 中统计经验可见歧义；
- BRANCHED 条件比例：只在多残基共价配体中统计。

连接端点、离去原子、isomeric SMILES、模型适配字符串和向量使用各自独立的诊断分母；它们不改变上述语言歧义判据。无法得到可靠连接或离去原子证据的键和 occurrence 另行计数。

同一身份只出现一次时，只能写“没有重复 occurrence 可用于经验检验”，不能写成已经证明唯一。

## 已核实的实现事实

### `object_key` 保存了什么

`Data_Preprocessing/Ori_Data/adaligand_preprocessing/stages/stage_c/pipeline.py::build_object_key()` 对单残基对象写出 `CCD:<ccd_id>`。BRANCHED 对象先按 Stage C 的残基顺序形成 CCD 序列，再把 CCD 序列和排序后的 `inter_bonds` 序列化；每条 `inter_bond` 含两个组分编号和两端原子名。键及安全文件名保留有序 CCD 序列，并用完整 `{ccds,bonds}` payload 的 6 位 MD5 前缀区分连接定义。

因此，当前键并非完全忽略跨残基连接端点；但它不保存连接键级，也不直接保存连接后应删除的 CCD 模板原子。`LigandObject` 本身把各 CCD 模板去氢后拼接，并为每条 `inter_bond` 添加一条单键；BRANCHED 的 `smiles` 字段为空字符串。

### 语言模型管线如何避开“一键一个向量”

`Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/` 的正式处理单位是 occurrence，而不是 `object_key`。BRANCHED 先从完整 mmCIF 读取 pdbeccdutils 组装的 CLC，并按 `(ccd_id, auth_asym_id, auth_seq_id, insertion_code)` 的残基身份多重集合选择唯一候选。连接端点比较只写入诊断，不参与 CLC 选择。

唯一 CLC 不能产生非空 SMILES 时，管线才从 LigandObject 删除 `present=False` 的模板原子，并保留两端都存在的模板键。该后备过程不猜测离去反应，也明确不把结果宣称为唯一化学真值。

正式 MoLFormer 与 SMI-TED 产物按 `(pdb_id, candidate_id)` 分别保存。共享一个 `object_key` 的 occurrence 不会互相覆盖。`文档/exec_plan/AdaLigand_v3基础数据升级实施.md` 记录的既有全量 prepared 运行曾有 636,299 个 CCD 来源、41,532 个 CLC 来源和 4 个 present-graph 后备来源；这里只把它们作为历史背景抄录，本轮没有重新扫描全量范围，它们也不参与 train/validation 的分组、比例或结论。

### “随机取一个”实际发生在哪里

Stage C、配体语言模型和 Matcher 的选择语义并不相同：

- Stage C 对同一个 `object_key` 只物化一份 LigandObject；`overwrite=False` 时，正常批处理保留第一个已经成功写出的有效文件。
- 配体语言模型不按 `object_key` 选择一个 occurrence，而是逐 occurrence 准备和编码。
- Matcher 才会在同一 PDB 内把 `(class_name, object_key)` 合并成一个身份，并从具备有效语言表示的 occurrence 中选择一个。该选择不是运行时随机抽样，而是先按 `candidate_id` 排序，再用 `selection_seed` 与 `pdb_id|object_key|language_family` 的 UTF-8 字节加权和计算确定性下标。相同清单和种子会得到相同结果。

因此，后文将分别使用“Stage C 首个有效写入者”“语言模型逐 occurrence 产物”和“Matcher 确定性选择”三个名称，不把它们统称为随机选择。

## 问题分类

### 同一键对应多个结构

这是本次问题的核心。当前键已经编码跨残基连接端点，但没有编码键级、离去原子集合和缩合后的最终分子图。若固定 `object_key` 的 occurrence 得到多个能够由缩合化学证据支持的规范分子图，才说明该键不足以充当唯一化学身份。

同一键出现多个语言输入只是需要解释的观测现象，不自动等于 LigandObject 缺陷。若差异只能归因于普通沉积原子缺失，则记为“沉积缺失相关的表示变化”，不计入本次缺陷分子。

### 键摘要碰撞

BRANCHED 可见键及安全文件名保留有序 CCD 序列，但完整 `{ccds,bonds}` 定义只以 6 位十六进制 MD5 前缀表示，即 24 bit。因此，实碰撞只需在相同可见 CCD 序列内检查。审计会重建未截断的 `{ccds,bonds}` 序列化内容；只有同一可见键对应多个完整定义时才报告实碰撞。

### 多个键对应同一结构

组件编号来自 PDB 实例的链与序号排序，不是分子图规范化编号。因此，结构相同但实例排序不同的对象可能生成不同键。这属于去重没有完全合并，不属于“一键压入多个结构”，需要单独统计。

## 消费者影响边界

- Matcher 身份清单把同一 PDB 内的 `(class_name, object_key)` 合并为一个身份；身份标签查找也只使用类别和 `object_key`。因此，同一 PDB 内的一键多语言输入会被折叠，并由一个确定性选中的 occurrence 代表。
- Matcher 配体图缓存严格按 `object_key` 加载一份全局 LigandObject 图。若同一键确有多个缩合后图，它们仍共享包含完整 CCD 模板原子的粗粒度图。
- AdaLigand 配体描述子按 `object_key` 和 LigandObject 一键一份，因此也共享模板级描述子。
- Stage E、Stage F 与 PocketXmol 适配同时使用一键一模板和 occurrence 级坐标、`present` 掩码；它们没有完全丢掉 occurrence 差异。沉积坐标差异本身仍不属于本次 LigandObject 缺陷。
- Pocket_Plus 当前没有发现直接把 `object_key` 当身份键的消费者。

## 离去原子核验规则

CCD 缓存中的 RDKit 原子可以保留 `pdbx_leaving_atom_flag` 派生的 `leaving_atom` 属性，但 LigandObject 结构化数组没有保存该属性。审计不会把“某个 CCD 有多个 leaving 标志”直接判为歧义，而是对每个跨残基连接端点执行以下规则：

1. 在固定 CCD 图中取 `leaving_atom=True` 原子形成的诱导子图；
2. 找出与连接端点直接相邻的 leaving 原子连通组；
3. 没有相邻组时记为 CCD 标志不足；
4. 恰有一个相邻组时记为按当前规则可唯一推导；
5. 存在多个相邻组，或多个连接端点竞争同一组时，记为需要额外核验。

本地 NAG 例子中，`C1` 端点唯一邻接 `{O1, HO1}`，`O4` 端点唯一邻接 `{HO4}`。这证明连接端点有可能消除 CCD 全局 leaving 标志的表面多义性，不能在全量统计前预设所有 BRANCHED 键都有缺陷。

## 数据范围与完整性

本次服务器统计读取 13,714 个 train PDB 和 200 个 validation PDB，共 441,129 个唯一 occurrence；其中 CCD occurrence 为 414,305 个，BRANCHED occurrence 为 26,824 个。去重后共有 2,931 个 `object_key`，包括 2,441 个 CCD 键和 490 个 BRANCHED 键。

441,129 个 occurrence 中有 82 个没有 prepared 记录。它们全部属于 `type_tag=other`，其中 train 80 个、validation 2 个；59 个是 CCD，23 个是 BRANCHED，分布于 53 个 PDB。核心扫描分别在 prepared、SMI-TED 和 MoLFormer 三层记录它们，因此原始错误表共有 `82 × 3 = 246` 条。它们不属于五类前景配体的正式语言准备范围，不是 246 次模型失败，也不进入后文的歧义计数。

具备非空 `PreparedLigand.smiles` 的 occurrence 共 441,047 个，涉及 2,901 个 `object_key`。BRANCHED 中有 26,801 个 occurrence、474 个键具备非空字符串；其中 246 个 BRANCHED 键至少有两个可供经验比较的 occurrence。

## 核心结果：一键多公开字符串确实存在

### 身份与 occurrence 比例

按本次语言表示侧的操作性判据“同一 `object_key` 对应多个非空 `PreparedLigand.smiles`”，发现 18 个公开字符串歧义键，全部是 BRANCHED：

- 占全部 2,931 个键的 0.6141%；若只以具备非空字符串的 2,901 个键为分母，则为 0.6205%；
- 占全部 490 个 BRANCHED 键的 3.6735%；若只以具备非空字符串的 474 个 BRANCHED 键为分母，则为 3.7975%；
- 在至少有两个可比较 occurrence 的 246 个 BRANCHED 键中占 7.3171%；
- 18 个键覆盖 20,516 个 occurrence，占全部 BRANCHED occurrence 的 76.4837%，占具备非空字符串的 BRANCHED occurrence 的 76.5494%；
- 按键计数为 sugar 13 个、peptide_like 3 个、small_molecule 2 个；按 occurrence 计数为 sugar 20,495 个、peptide_like 10 个、small_molecule 11 个。

这里的 76% 不能解释为 76% 的 BRANCHED occurrence 都采用了少见或错误字符串。它主要由两个极高频糖链键造成。对每个键取出现次数最多的字符串作为描述性参照；最高频并列时只为计数而固定取字典序最前的一项。该参照不代表已经证明它在化学上正确。按此口径，18 个键内只有 50 个 occurrence 使用其他字符串：

- 占公开字符串歧义键所覆盖 occurrence 的 0.2437%；
- 占全部 BRANCHED occurrence 的 0.1864%；
- 占全部具备非空 `PreparedLigand.smiles` 的 occurrence 的 0.0113%。

因此应同时保留两个事实：一方面，`object_key → PreparedLigand.smiles` 的函数关系确实被数据反例推翻；另一方面，非主导公开字符串记录很稀疏，不能只用“公开字符串歧义键覆盖 76%”描述实际变体频率。

### 18 个键的分布

| `object_key` | 类型 | occurrence 数 | 字符串数 | 非主导 occurrence 数 |
| --- | --- | ---: | ---: | ---: |
| `BRANCHED:NAG-NAG:547a2a` | sugar | 16,537 | 7 | 21 |
| `BRANCHED:NAG-NAG-BMA:97d8a6` | sugar | 3,452 | 4 | 3 |
| `BRANCHED:NAG-NAG-MAN:62a061` | sugar | 359 | 2 | 1 |
| `BRANCHED:NAG-NAG-NAG:3bc5a7` | sugar | 80 | 2 | 2 |
| `BRANCHED:GLC-GLC:cca284` | sugar | 22 | 2 | 1 |
| `BRANCHED:NAG-NAG:193493` | sugar | 9 | 2 | 1 |
| `BRANCHED:GAL-SIA:be3b94` | sugar | 8 | 2 | 3 |
| `BRANCHED:KC2-LMG:7b2b67` | small_molecule | 7 | 2 | 4 |
| `BRANCHED:NAG-NAG-BMA-BMA:379038` | sugar | 6 | 2 | 1 |
| `BRANCHED:NAG-NAG-MAN:2d6d6c` | sugar | 6 | 2 | 1 |
| `BRANCHED:FME-PRO:12aefc` | peptide_like | 5 | 2 | 1 |
| `BRANCHED:GAL-SIA:1001ec` | sugar | 5 | 2 | 2 |
| `BRANCHED:SGN-IDS-SGN-IDS-SGN-IDS:49773a` | sugar | 5 | 2 | 2 |
| `BRANCHED:LMG-KC2:901f60` | small_molecule | 4 | 2 | 2 |
| `BRANCHED:NAG-NAG-BMA-BMA-BMA:e370f6` | sugar | 4 | 2 | 2 |
| `BRANCHED:PHE-FME:bbd4a6` | peptide_like | 3 | 2 | 1 |
| `BRANCHED:FME-PHE:63b870` | peptide_like | 2 | 2 | 1 |
| `BRANCHED:NAG-NAG-BMA-BMA:313071` | sugar | 2 | 2 | 1 |

四个最高频键通过另一份脚本直接重读 split、occurrence 和 prepared 产物独立复算，得到完全相同的 occurrence 总数、字符串计数与代表记录，且没有缺失。该复算没有复用核心扫描的聚合结果。

`BRANCHED:NAG-NAG-MAN:62a061` 的 359 个 occurrence 中，有 1 个公开字符串由大量以点号分隔的孤立原子片段组成，其余 358 个使用同一个连通糖链字符串。这是后文建议隔离明显断裂字符串的直接实例；它仍不能单凭少数性判为化学错误。

18 个键的 20,516 个 occurrence 均来自 CLC 路径，而不是 `present` 掩码后备路径。完整 AdaLigand train/validation 中只有 6 个 `(PDB, object_key)` 组在同一个 PDB 内出现多个公开字符串；多数差异只在跨 PDB 比较时可见。

## 原因核验：没有观察到“一个端点对应多个离去基团”

对全部 490 个 BRANCHED 键、161 种 CCD 和 471 个不同连接端点执行了前述 leaving 连通组规则。端点级结果为：

- 138 个端点唯一邻接一个标记离去连通组；
- 264 个端点没有邻接标记离去连通组，只能判为证据不足；
- 69 个端点的原子名在 CCD 中不能唯一解析；
- 0 个端点邻接多个不同的标记离去连通组。

键级结果为：

- 282/490 个键的全部端点均可唯一指出相邻离去组，覆盖 26,144/26,824 个 BRANCHED occurrence；
- 208/490 个键至少有一个端点证据不足，覆盖 680 个 occurrence；
- 0 个键出现“同一端点有多个相邻离去组”；
- 7 个键存在多个端点共享同一离去连通组，需单独解释，但不等同于同一端点多解。

18 个公开字符串歧义键中，16 个的所有端点都能唯一指出离去组；另外两个 `KC2-LMG` 方向键的 4 个端点均没有相邻标记组，属于证据不足。18 个键中没有同一端点多解，也没有多个端点共享同一离去组。

这项结果不支持“现有 18 个分叉普遍由同一连接端点无法唯一决定离去原子造成”。它也不能反向证明最终化学身份唯一：当前规则依赖外部 CCD 版本与 `leaving_atom` 标志，证据不足的端点仍存在。实际 PDB CLC 图由沉积 `_atom_site` 原子与连接信息构造，并不由 CCD 的 `pdbx_leaving_atom_flag` 推导；这里的 leaving 规则只是与 CLC 生成链独立的诊断。更准确的结论是：最初担心的直接机制在本次 train/validation 中没有观测到实例；现有证据只把 18 个分叉定位为 occurrence 级 CLC 输出差异，不能继续区分沉积缺失、CLC 图构造或解析因素，其中两个复杂辅因子键仍无法凭现有证据定因。

另有 3 个键、15 个 occurrence 的已选 CLC 连接与 occurrence 声明不一致：

- `BRANCHED:NAG-NAG-BMA-MAN-MAN-MAN-MAN:d03f60`；
- `BRANCHED:NAG-NAG-BMA-MAN:3ac598`；
- `BRANCHED:NAG-NAG:193493`。

只有最后一个属于 18 个公开字符串歧义键。连接诊断不参与 CLC 选择，因此应把这 15 个 occurrence 作为 CLC 可靠性问题单独追踪，不能把它们全部当成公开字符串分叉的共同根因。

## 键摘要与反向去重

审计按 CCD 序列和完整 `inter_bonds` 重建未截断 payload，得到：

- 0 个 6 位 MD5 前缀实碰撞；
- 0 个可见键与重建 payload 不一致。

24 bit 摘要仍然不是适合长期扩展的强身份摘要，但它不是当前观测歧义的来源，因而不应成为第一修复优先级。

反方向上，有 124 个非空 `PreparedLigand.smiles` 同时对应至少两个 `object_key`，涉及 276 个键：

- 占全部 2,931 个键的 9.4166%，占具备非空字符串的 2,901 个键的 9.5140%；
- 涉及 119 个 BRANCHED 键，占全部 BRANCHED 键的 24.2857%，占具备非空字符串的 BRANCHED 键的 25.1055%；
- 另涉及 157 个 CCD 键。

这说明当前键在语言模型公开字符串层面还存在明显的“多个键未合并”现象。但 `PreparedLigand.smiles` 是 non-isomeric 字符串；相同字符串不足以证明立体化学、质子化、形式电荷及完整化学身份相同，因此不能据此自动合并键。另有 31 个键、2,999 个 occurrence 只在 CLC isomeric SMILES 上变化，而公开的 non-isomeric `PreparedLigand.smiles` 相同；按本次用户指定的定义，它们不属于语言模型侧歧义，但说明公开字符串本身也会隐藏立体差异。

## 已有语言向量受到的影响

向量比较只解释同一公开字符串分叉传到既有模型后的影响，不用于定义公开字符串歧义。18 个公开字符串歧义键在两套模型产物中都没有出现“公开字符串种数与非空 `model_smiles` 种数不相等”的情况；这只是种数核对，不声称两类字符串逐字相同。每套模型先按精确 `model_smiles` 分组，再从按 `pdb_id`、`candidate_id` 稳定排序的已有路径中取第一份向量作为该模型适配字符串的代表；随后计算同一键内代表向量的全部无序字符串对。每个模型得到 52 对，两套模型合计 104 对，全部向量可读取。该规则不是对 occurrence 向量求均值，也不是 Matcher 的身份选择规则。

相对 L2 距离定义为：

\[
d_{\mathrm{rel}}(x,y)=\frac{\lVert x-y\rVert_2}{(\lVert x\rVert_2+\lVert y\rVert_2)/2}.
\]

| 模型 | 指标 | 中位数 | P95 | 最大值 | 不同 `object_key` 参照中位数 |
| --- | --- | ---: | ---: | ---: | ---: |
| SMI-TED Light 289M | 相对 L2 | 0.06832 | 0.23528 | 0.24208 | 0.16234 |
| SMI-TED Light 289M | cosine distance | 0.002333 | 0.027446 | 0.029069 | 0.013096 |
| MoLFormer | 相对 L2 | 0.24396 | 1.12453 | 1.18222 | 0.79595 |
| MoLFormer | cosine distance | 0.029329 | 0.625982 | 0.689391 | 0.310914 |

不同键参照各模型固定抽取 20,000 对不同 `object_key` 的向量。复现规则为：固定随机种子 3407；每个模型先按 `SHA-256(model_stage + "\0" + object_key)` 排序保留最多 512 个键；每个键取字典序最前的 `model_smiles` 及其首个稳定排序向量；排除两个键具有相同 `model_smiles` 的组合后，再无放回抽取 20,000 对。不同键不等同于已经证明的不同化学身份，因此该参照只提供现有向量空间尺度，不承担身份真值。相同模型适配字符串 `model_smiles` 的重复向量对用作数值噪声基线：MoLFormer 1,929 对、SMI-TED 1,906 对的各项中位数均为 0；相对 L2 最大值分别为 `4.69×10^-7` 和 `1.70×10^-6`。因此不同 `model_smiles` 的非零距离不是重复写出噪声。总体上，同键不同 `model_smiles` 的距离中位数小于不同键参照中位数，但个别差异已经接近或超过该参照的典型尺度。

SMI-TED 的 `diagnostic_token_prefix_within_length` 仅作为长度限制后的文本前缀代理，不是模型公开的 `input_ids`。52 对不同 `model_smiles` 全部具有不同代理前缀，且没有相对 L2 小于等于 `10^-6` 的向量对；这只说明现有适配结果没有把这些输入压成相同向量，不能把代理前缀解释为模型内部 token 真值。

## Matcher v3 的实际暴露

当前冻结的 `closed_set_v3` 清单只读取 train/validation。这里的“受影响”表示身份使用了上述 18 个公开字符串歧义键之一，不表示该身份必然选中了非主导字符串。

| split | 全部身份 | 受影响身份 | 全部候选 | 有效前景身份候选 | 受影响候选 | 受影响身份比例 | 受影响前景候选比例 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| train | 1,477 | 138 | 14,312 | 4,192 | 423 | 9.3433% | 10.0906% |
| validation | 536 | 37 | 6,495 | 1,472 | 100 | 6.9030% | 6.7935% |

train 命中 6 个公开字符串歧义键，validation 命中 3 个；两者受影响身份全部是 sugar。SMI-TED validation 因已有 2 个身份表示缺失，以 1,466 个受监督候选为语言家族分母时，100 个受影响候选占 6.8213%。

更关键的是，当前 v3 的 train 和 validation 都有 0 个同 PDB 身份组包含多个 `PreparedLigand.smiles`，也有 0 个同 PDB 身份组包含多个模型适配字符串。也就是说，当前 Matcher 清单中的确定性 occurrence 选择没有实际面对“同一 PDB 身份有多个公开字符串可选”的情况。跨 train/validation 合计 175 条受影响身份记录中，每个语言家族只有 2 条选中了相对于该键全局众数的非主导字符串。

因此，现有 Matcher 的直接语言选择噪声明显小于 20,516 个 occurrence 的表面覆盖量；但跨 PDB 的同一 `object_key` 仍可能携带不同 occurrence 级向量，而配体图、描述子和 train/validation seen 身份仍按键折叠。这是身份语义近似，不应被描述成已经证明的一键一化学实体。

本轮没有做冻结 Matcher 的输入替换、预测翻转、重新训练或指标敏感性试验，不能把上述暴露数量换算成 validation 分数损失。

## 严重程度判断

综合判断如下：

1. **这是真问题。** 18 个直接反例已经证明当前 `object_key` 不能严格充当 `PreparedLigand.smiles` 的唯一键，也就不能在没有附加规则时直接支持“一键只算一个语言向量”。
2. **非主导公开字符串 occurrence 比例很低。** 18 个键覆盖很多 occurrence，主要因为两个常见糖链键极高频；偏离键内描述性众数字符串的 occurrence 只有 50 个，占全部具备语言字符串 occurrence 的 0.0113%。这不说明众数字符串正确或少数字符串错误，只说明观测分布高度偏斜。
3. **最初怀疑的 leaving 多解不是本批数据中的实证根因。** 0 个端点出现多个相邻标记离去组，18 个公开字符串歧义键中 16 个反而具有完整的唯一端点证据。不能再把全部公开字符串歧义概括为“BRANCHED 无法唯一决定离去原子”。
4. **语言模型管线的逐 occurrence 设计是正确的保护措施。** 它保存了差异，没有让共享键的 occurrence 相互覆盖；问题主要出现在后续试图把粗粒度键提升为全局唯一身份时。
5. **按当前 Matcher v3 的确定性选择规则，直接暴露数量较少但不为零。** 同 PDB 多输入身份为 0，只有极少数已选身份使用非主导字符串；然而跨 PDB 的身份折叠和一键一图仍建立在未经证明的唯一性假设上。没有模型敏感性实验时，不能把该数量表述成性能风险大小。
6. **反向去重不完整比哈希碰撞更值得关注。** 没有观察到 24 bit 实碰撞，却有约四分之一的 BRANCHED 键在公开字符串层面与其他键重合。它提示“模板拓扑键”和“语言表示身份”本来就不是同一个概念。

最合适的总体定级是：**中等程度的身份建模与产物契约问题；当前非主导公开字符串 occurrence 比例低，但对未来按键缓存语言表示、跨 PDB 身份监督和一键一图解释具有不可忽视的结构性风险。** 现有证据不要求立即停掉 Matcher validation 实验，却要求停止把 `object_key` 无条件称为唯一化学身份。

## 建议的后续策略

### 立即可执行而不改变科学标签

1. 继续保持语言准备与向量产物按 `(pdb_id, candidate_id)` 保存，不改成按 `object_key` 只留一个向量。
2. 在清单或审计元数据中保留 `distinct_prepared_smiles`、每个字符串的 occurrence 数和所选 occurrence，明确区分“粗粒度模板键”和“公开字符串变体”。
3. 如果未来同一 PDB 身份组出现多个非空 `PreparedLigand.smiles`，构建 Matcher 清单时应显式报告或拒绝静默选择；本次 v3 的 0 例不能作为长期保证。
4. 对断裂成原子散点的字符串、CLC 连接不一致和证据不足的 `KC2-LMG` 两个方向键建立隔离清单，先复核生成路径，不把键内众数自动当化学真值。

### 身份模型的结构化修订方向

1. 将当前 `object_key` 重新解释为 `template_key`：它表示 CCD 组件与跨组件端点拓扑，用于模板复用，而不承诺唯一缩合后分子。
2. 增加 occurrence 级 `representation_variant_id`，至少绑定精确的非空 `PreparedLigand.smiles`；它负责语言输入复现，不冒充完整化学身份。
3. 只有在明确规定立体化学、形式电荷、质子化、键级、离去原子规范化及 CCD 版本后，才定义新的 `chemical_identity_key`。不能只用 non-isomeric 公开字符串替代这份契约。
4. 为多个键共享公开字符串建立只读别名索引，用来发现去重漏合并；不要仅凭相同 non-isomeric SMILES 自动合并对象。
5. 后续版本可保存完整 payload 摘要并增加 schema 版本，消除 24 bit 摘要的规模风险；由于本次实碰撞为 0，它低于身份语义拆分的优先级。

这些策略可以并存：保留现有键以兼容模板与历史产物，同时新增明确命名的表示变体和化学身份层。这样比试图让一个字段同时承担模板复用、语言输入、化学去重和监督类别四种职责更稳健。

## 证据限制

- 本轮只覆盖 train/validation；没有读取 calibration，不能外推 calibration 的比例。
- 公开 `PreparedLigand.smiles` 是本次唯一语言侧判据。模型适配字符串、token 前缀、向量、坐标和 `present` 掩码均没有被偷偷并入歧义定义。
- 多个公开字符串证明“一键一公开输入”不成立，但不自动证明每个字符串都代表正确且稳定的不同化学实体；相同 non-isomeric 字符串也不证明完整化学身份相同。
- leaving 连通组规则是对当前 CCD `leaving_atom` 标志的可重复操作性核验，不是完整的反应机理推断。证据不足的端点不能按唯一或歧义处理。
- 本轮只比较已经存在于同一正式产物根中的两个模型结果，没有重新编码，也没有额外核验模型 checkpoint revision。
- 没有执行模型输入替换、重新训练或指标影响实验，因而不对性能损失作因果结论。

## 证据索引

### 源码版本与实现位置

实现事实以以下两个本地仓库基线为准；表中关键文件在审计收口时均没有未提交修改：

- AdaLigand `Learn/CUMULATIVE`：`7c857950e6ff7122eccd79bfa956f51e8e0dca09`；
- Matcher `Learn/CUMULATIVE`：`8d6ba38cf86d6063874b83792b480341f326bb6b`。

| 事实 | 文件与入口 | 文件 SHA-256 |
| --- | --- | --- |
| `object_key` 构造、首个有效写入者语义 | `Data_Preprocessing/Ori_Data/adaligand_preprocessing/stages/stage_c/pipeline.py::build_object_key`、`materialize_ligand_objects` | `e3056b2c3615448a0298ff009d2fb2b10b7fe1ef0859a2519292a8a3b9b1ad14` |
| BRANCHED LigandObject 拼接、跨组件单键 | `Data_Preprocessing/Ori_Data/adaligand_preprocessing/stages/stage_c/ligand_objects.py::process_branched_ligand` | `423f76f30c9a4b9bcdec02e384751f9c7f9119761315c4acc7c1781750e3e719` |
| CLC 身份选择与连接只诊断 | `Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/clc_assembly.py::select_exact_clc` | `d8e01daec386cc9b681c9e6f49922380e2d6f83aa8738f95f6450f08758125a6` |
| occurrence 级公开字符串准备 | `Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/prepare_smiles.py` | `74f6f161eb297e64ff9b59dcdaf6bcc9d8a6204e92a328840de3afb1a95394c3` |
| `PreparedLigand.smiles` 字段契约 | `Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/产物字段参考.md` | `51dec689eebb3be0e5c8e789beb26c1ead2fe20e2bdb99b55a68c1a51b589609` |
| Matcher 身份合并与确定性 occurrence 选择 | `Matcher/matcher/data/manifest.py::_build_identity_records`、`_select_language_representation` | `8bb3feea2ef1a1a59493c1f99725a64856c664244e81cbb6de23000ee6c4cc07` |
| Matcher 一键一图缓存 | `Matcher/matcher/data/ligand_graph.py::LigandGraphStore.load` | `4432429d5664bc845def65be307f3f892947d05d91a54b6246085e0e28e3019f` |

其他消费者的定位如下：一键一描述子见 `Data_Preprocessing/Ori_Data/adaligand_preprocessing/stages/stage_c/descriptors.py::materialize_ligand_descriptor`；Stage E 模板元素读取见 `stages/stage_e/ligand_area.py`；Stage F 的模板与 occurrence 结合见 `stages/stage_f.py`；PocketXmol 适配见 `Data_Preprocessing/PocketXmol_compat/pocketxmol_compat/ligand.py`。

### 输入根与机器结果

本轮只读输入为：

- Stage C 数据根：`/storage/penghongen/AdaLigand/Ori_Data`；
- 语言产物根：`/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2/ligand_language_models`；
- split 根：`/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2/split`，只打开 `train.json` 与 `validation.json`；
- Matcher 清单：`/storage/penghongen/tmp/Matcher/manifests/closed_set_v3/manifest.json`，只使用其中已有的 train/validation 记录。

| 本文结果 | 机器可读证据 |
| --- | --- |
| 总分母、18 个公开字符串歧义键、反向去重、缺失记录 | `full_core/summary.json`、`full_core/objects.jsonl`、`full_core/many_keys_one_smiles.jsonl`、`full_core/errors.jsonl` |
| 同 PDB 多公开字符串 | `full_core/same_pdb_multi_input.jsonl` |
| leaving 端点与键级分类 | `leaving_candidates/summary.json`、`leaving_candidates/objects.jsonl`、`leaving_candidates/endpoints.jsonl` |
| 向量距离、不同键参照、重复输入基线、SMI-TED 前缀代理 | `vectors/summary.json`、`vectors/ambiguous_input_distances.jsonl`、`vectors/cross_identity_baseline_distances.jsonl`、`vectors/same_input_repeat_distances.jsonl`、`vectors/smi_ted_ambiguous_token_prefixes.jsonl` |
| Matcher v3 暴露 | `matcher_v3/summary.json`、`matcher_v3/affected_identities.jsonl` |
| 四个高频键独立复算 | `matcher_v3/high_frequency_recheck.json` |
| 汇总快照与完整输出哈希 | `final_audit_snapshot.json`、`output_sha256.tsv` |
| CPU 记账与资源释放 | `cpu_job_accounting.tsv`、`cpu_job_live_queue.txt`、`cpu_job_control_locks.txt` |

上述相对路径均位于下一节给出的服务器诊断根。

## 运行证据

服务器诊断根为：

`/storage/penghongen/tmp/Matcher/diagnostics/ligand_object_audit_20260814T1718/`

CPU 作业如下；全部为 CPU-only，没有申请 GPU，没有设置 calibration 输入：

| Slurm Job | 内容 | CPU | 结果 | 运行时间 |
| --- | --- | ---: | --- | ---: |
| `341831` | 核心 occurrence、公开字符串、payload 与反向去重扫描 | 16 | `COMPLETED/0:0` | 2:38 |
| `341837` | 向量距离与 leaving 端点核验 | 4 | `COMPLETED/0:0` | 12:02 |
| `341838` | Matcher v3 影响与高频键复算首版 | 4 | `COMPLETED/0:0` | 0:33 |
| `341841` | Matcher 两语言家族分母补充复算 | 4 | `COMPLETED/0:0` | 0:32 |

`341837` 与 `341838` 并行时合计使用 8 核，没有超过本次 16 核上限。四个作业结束后 `squeue` 为空，审计记录中的活动队列与控制锁文件均为 0 字节，没有遗留 `pre_lock`、`after_lock` 或本次任务控制文件；本次申请的 CPU 资源已经全部释放。

前三种作业的完整提交命令分别保存在 `submission_command.txt`、`secondary_submission_command.txt` 和 `matcher_recheck_submission_command.txt`；`341841` 在更新诊断脚本后使用第三个文件中的同一命令重跑。三条命令都通过 `训练与运行/submit_task.sh --simple` 提交，并显式给出诊断 `task_root`、一次性脚本、CPU 数和内存。每个作业的启动、结束、退出码与 `calibration_read=false` 另见 `execution_evidence.txt`、`secondary_execution_evidence.txt` 和 `matcher_recheck_execution_evidence.txt`。

核心机器可读快照为 `final_audit_snapshot.json`，SHA-256 为：

`f17cdac4082cf15a844cda3c7f186c5aef7d781beba1efb09e83607d784f0634`

完整输出哈希表为 `output_sha256.tsv`，该表自身 SHA-256 为：

`d5f877e9832468934ae5968d594c6578201e56208b375c95804b19473ecfb6bf`

四个一次性审计脚本的 SHA-256 为：

- `audit_core.py`：`85f8cb8676b6fd8dfeb242a383507f7623d4e62c358142b663d36c83360d4850`；
- `audit_vectors.py`：`ff1d3cb09d2c3b09208f8212fbc83bf94bbd5fea93fbcc680acd3622077654e9`；
- `audit_leaving_candidates.py`：`daeb635f3f8aa1cb67d6d0dea5d512070e2e77bab6fc2ffbe031b5c16506f43a`；
- `audit_matcher_and_recheck.py`：`d60f9a54dae42a913f479af3743610db19b2ea6dc1683d78e5f55ecbaf362d9c`。

这些脚本和结果只位于服务器诊断目录及本地忽略的 `tmp/ligand_object_audit/`，没有进入正式处理模块。本轮没有修改 AdaLigand 正式数据、语言产物、Matcher 清单或训练逻辑。
