# 配体类型多分类标签与 Find 最小改造调研

> 文档性质：只读代码调研、设计边界汇总和后续改动计划，不是已经批准的实现规格，也不表示文中建议已经落地。
>
> 审查快照：AdaLigand `main@fcc7e8a`；Pocket_Plus `Learn/06-stage1-centered-runtime@cb74db3`。审查期间 Pocket_Plus 工作区存在用户已有或并发产生的未提交修改，涉及 `talk/`、artifact path/state 和 Stage1 Dataset/Collator/BOX request/split 等文件；本调研只读取当前内容，没有触碰这些修改。相关 Dataset 差异以中文契约和注释补充为主，关键二分类行为仍与本文陈述一致。
>
> 上游关系：本文审查 `文档/规划文档/数据处理_v2.md`、`文档/exec_plan/A-G数据流水线实现与全量运行.md`、`文档/mapping/计划执行映射.md`、`Data_Preprocessing/Ori_Data/code/readme.md`，并对照 Pocket_Plus 的 Stage1 训练、推理实现。本文只报告漂移，不回填或改写上述文档。
>
> 覆盖范围：A-G 数据流程、`type_tag` 定义、原子和体素标签合并、Pocket_Plus Dataset/模型头/loss/普通指标/CPC/推理/下游候选链、需要重跑的范围。
>
> 不在范围：本轮不改代码、配置、现有计划、mapping、README、项目记忆、远端文件，不运行正式数据生产或训练。

## 1. 先给结论

当前 AdaLigand 的“配体标签”不是五分类标签，而是把所有被 Stage C 接受的配体 occurrence，不分 `type_tag`，合成一个前景：

- 原子标签回答的是“这个受体原子是否在任意配体重原子 4 Å 内”；
- 体素标签回答的是“这个体素是否落在任意配体原子的范德华球内”；
- `type_tag` 虽然已经写在 `occurrences.jsonl` 中，但没有进入 `atom_labels.npz` 或 `ligand_area.npz` 的训练标签字段；
- Pocket_Plus 的正式 Ada Dataset 又把这些字段读成 `bool`，因此类型信息在模型入口前已经消失。

因此，规划文档中“训练时用 `class_mapping.yaml` 把 `type_tag` 映射为 class”的想法尚未成为可运行接口：仓库里没有该正式映射文件，现有标签产物也没有足够字段让 Dataset 直接恢复逐原子、逐体素类别。

用户已经确定的目标不是让整条 CPC/forest/Selector 变成五类候选系统，而是：

1. 原子头、受体体素辅助头、配体区域体素头改为六通道互斥 `softmax`；
2. 六个通道为一个背景加五种配体类型；
3. 五种前景类型都参加普通分类监督；训练模型保留六通道输出，供 loss、指标和未来接口使用；
4. 只有 `small_molecule` 进入 C、P、CPC diagnostics、当前 Find 概率图、forest、CLG、Selector 和 calibration；
5. `other` 不设第七类。在现有只读样本均低于 5% 的证据下，按背景参加监督，不使用 `ignore_index`。

这个目标可以在不重写网络主干的前提下完成，但不能只改两个 `.npz` 文件。Pocket_Plus 至少有三个会导致训练语义直接错误的接口：Dataset 把类别读成布尔值；原子头把第 0 通道当“结合概率”喂给 P；P 的二分类监督会直接抽到 2 至 5 的多类 ID。推理端也仍只接受一张单通道 sigmoid 图。

## 2. 术语的白话定义

### 2.1 occurrence

一个 occurrence 是某个 PDB 结构中实际出现的一份配体实例。两个化学组成相同、但在结构中位置不同的配体，是两个 occurrence。`candidate_id` 是这份实例在当前 PDB 内的编号。

### 2.2 `type_tag`

`type_tag` 是 Stage C 根据 mmCIF entity 类型、CCD 的 `_chem_comp.type` 和“是否为单原子金属”推出来的粗分类。它是解析规则的结果，不是完整的化学本体，也不是通过分子名称猜出来的类别。

### 2.3 原子标签、受体体素辅助标签、配体区域体素标签

- 原子标签：每个受体原子一个答案，用于原子分类头。
- 受体体素辅助标签：把受体原子的标签放到该原子所属的体素，用于 voxel auxiliary head。它只在受体原子实际占据的 home voxel 上计算 loss。
- 配体区域体素标签：整个 80³ BOX 或完整密度图中，每个体素一个答案，用于 voxel ligand head。

### 2.4 C、P 和 CPC

- C 是从配体区域概率图中挑出的候选体素集合。
- P 是围绕这些候选形成的虚拟点/锚点。
- CPC 是围绕候选 C、虚拟点 P 及其诊断、阈值缓存和稀疏交互形成的一条链。

本文中的“CPC 只处理 `small_molecule`”是严格边界：其他四类不生成 C，不生成对应 P，不占候选预算，也不进入 CPC 阈值和诊断。

## 3. A-G 当前流程

| 阶段 | 输入 | 当前主要输出 | 与类型多分类的关系 |
|---|---|---|---|
| A 枚举 | RCSB、EMDB 元数据 | PDB-EMDB 样本清单 | 不生成标签，无需因多分类重跑 |
| B 下载 | A 的样本清单 | mmCIF、map、meta、CCD 原料 | 不生成标签，无需因多分类重跑 |
| C 解析 | mmCIF、CCD | occurrence、`type_tag`、配体 present 原子坐标、受体坐标和特征 | 已经拥有重打标签所需的类型和坐标；正常情况下无需重跑 |
| D 原子标签 | C 的受体坐标和全部 occurrence 配体坐标 | `atom_labels.npz` | 当前只有“任意配体/背景”二值语义；需要重打 |
| E1 实验图 | 原始 map | canonical `exp.npz` | 密度输入，不因类别变化而重跑 |
| E2 模拟图 | 去配体受体、Chimera | receptor-only `sim.npz` | 密度输入，不因类别变化而重跑 |
| E3 体素标签 | C 的配体坐标、E 的网格几何 | 每 occurrence 稀疏 mask 和全部 occurrence 的 union | 需要增加类别标签并重建；无需重跑 E1/E2 或 Chimera |
| F 质量评估 | C/E 产物、结构和 map | 四种全局 CC、配体逐原子 Q、6 Å 口袋 Q、occurrence 聚合 | 当前不按 `type_tag` 过滤；本轮沿用现有结果，不改、不重跑 |
| G 过滤 | F 聚合和显式阈值 | PDB 级 `keep_list.jsonl` | 当前是 map-level 过滤；通过 PDB 后保留该 PDB 的全部 occurrence。本轮不改、不重跑 |

F/G 不消费新的多分类标签。把 F/G 改成 type-aware 过滤会改变样本选择的科学定义，不属于“最小改造”。用户已决定本轮直接沿用现有 F 结果和 G 过滤。

## 4. `type_tag` 到底怎样定义

权威实现是 `Data_Preprocessing/Ori_Data/code/parse.py::derive_type_tag()`。代码按下面的顺序检查，前面命中就不再看后面，因此顺序本身也是定义的一部分。

| 优先级 | `type_tag` | 代码条件 | 白话含义和边界 |
|---:|---|---|---|
| 1 | `sugar` | occurrence 中任一原子所属 entity 为 `branched`；或全部 CCD type 都含 `SACCHARIDE` | 主要覆盖糖链、支化糖以及 CCD 明确标为糖的对象。它不是按名字中有没有“糖”判断 |
| 2 | `peptide_like` | 任一 CCD type 含 `PEPTIDE LINKING` | 含肽连接类型的片段。这里说的是“像多肽的连接化学类型”，不等于任意含氨基酸样基团的小分子 |
| 3 | `nucleotide_like` | 任一 CCD type 含 `NA LINKING` | 含核酸连接类型的片段，通常可理解为核苷酸/核酸片段样对象 |
| 4 | `ion` | occurrence 恰有一个原子，且元素在项目的金属元素集合中 | 实际含义是“单原子金属”，不是所有带电离子。单原子氯不会进入这里 |
| 5 | `small_molecule` | occurrence 的全部 CCD type 都严格等于 `NON-POLYMER` | 这是本项目主任务的“小分子 ligand”规则。单原子氯按当前测试锁定为这一类 |
| 6 | `other` | 上述条件全未命中 | 兜底类别。它不是垃圾的同义词，也不能仅凭分子名称删除 |

两个容易误解的事实：

- 这五个主类型确实是 `small_molecule`、`ion`、`sugar`、`peptide_like`、`nucleotide_like`；代码还存在第六个解析兜底 `other`。
- 当前 Stage C 会保留与 polymer 存在共价连接的 occurrence，并写 `is_covalent=true`。规划文档中“去掉共价修饰”的表述与当前代码存在漂移，不能在本次多分类改造中顺手假定它们已经被删除。

## 5. 当前标签怎样合并

### 5.1 Stage D：受体原子

`Data_Preprocessing/Ori_Data/code/atom_labels.py::compute_atom_labels()` 当前执行如下步骤：

1. 按 `candidate_id` 排序，把所有 occurrence 的 present 配体原子坐标拼在一起；这些是配体重原子坐标。
2. 建一棵最近邻搜索树。
3. 对每个受体原子，找到距离最近的配体原子及其 occurrence。
4. 最近距离小于或等于 4 Å 时，`binding_atom=true`；否则为背景。
5. 正样本的 `instance_id` 写最近 occurrence 的 `candidate_id`；背景写 `-1`。
6. `nearest_dist` 始终保存真实最近距离，不因是否超过 4 Å 而清空。

当前 schema v1 只有：

| 字段 | 形状和类型 | 当前含义 |
|---|---|---|
| `binding_atom` | `(N_rec,) bool` | 是否在任意 occurrence 的配体重原子 4 Å 内 |
| `instance_id` | `(N_rec,) int32` | 正样本最近 occurrence 的 `candidate_id`；背景为 `-1` |
| `nearest_dist` | `(N_rec,) float32` | 到全部 occurrence 中最近配体重原子的距离，单位 Å |

代码已经有一段“几乎完全等距时，按较小 `candidate_id` 再按拼接行号稳定决定”的旧逻辑。这是现状，不是本次新增建议。用户已明确：多分类合并只增加一层最近距离判断，不再添加“完全等距时较小 `candidate_id` 获胜”等新的业务规则。

### 5.2 Stage E3：配体区域体素

`Data_Preprocessing/Ori_Data/code/density.py::build_ligand_area_arrays()` 对每个 occurrence 独立生成 mask：

1. 对 occurrence 的每个配体原子，按该元素的范德华半径寻找球内 voxel center。
2. 同一 occurrence 内多个原子的体素取并集并去重。
3. 写成 `mask_{candidate_id}: (K,3) int32`，坐标顺序是 ZYX。
4. 各 occurrence 之间不互相裁剪，所以两个 occurrence 的 mask 可以重叠。
5. 最后把全部 `mask_{candidate_id}` 做逻辑或，得到 `union_mask: (1,Z,Y,X) bool`。

当前 `union_mask` 只回答“是否属于任意 occurrence”，没有类别 ID；重叠体素同时属于多个 occurrence 的事实只保存在各自稀疏 mask 中，union 里看不出来。

### 5.3 Pocket_Plus 怎样把它进一步变成二值

`Pocket_Plus: src/datasets/stage1_dataset.py` 当前：

- 将 `binding_atom` 强制读成 `bool`，裁成 `atom_label`；
- 用 binding 受体原子的 home voxel 构造 bool `voxel_label`；
- 将 E3 `union_mask` 裁成 bool `ligand_area_target`；
- 正式 Ada 配置把 `class_names` 固定为 `[background, foreground]`。

所以当前训练的三个目标都是二值：原子、受体体素辅助、配体区域体素。类型信息不是在 loss 中丢失，而是在 Dataset 之前就没有进入标签文件。

## 6. 用户已经冻结的目标边界

### 6.1 类别顺序

采用互斥 `softmax`，类别 ID 固定为：

| class_id | 类别名 | 训练角色 | CPC/下游角色 |
|---:|---|---|---|
| 0 | `background` | 背景类；也接收 `other` | 不生成候选 |
| 1 | `small_molecule` | 主任务前景 | 唯一进入 C、P、CPC、forest、CLG、Selector、calibration 的类别 |
| 2 | `ion` | 辅助前景 | 只做普通监督、普通指标和 W&B 损失曲线；当前推理不读取 |
| 3 | `sugar` | 辅助前景 | 只做普通监督、普通指标和 W&B 损失曲线；当前推理不读取 |
| 4 | `peptide_like` | 辅助前景 | 只做普通监督、普通指标和 W&B 损失曲线；当前推理不读取 |
| 5 | `nucleotide_like` | 辅助前景 | 只做普通监督、普通指标和 W&B 损失曲线；当前推理不读取 |

把 `small_molecule` 固定为 class 1 的实际好处是：现有大量二分类代码把“前景”写成 `[1]`，CPC 最小改造可以继续使用 `candidate_class_ids=[1]`。

### 6.2 `other` 的决定

本轮不把 `other` 设成第七类，也不使用 `ignore_index`。在标签生成时，`other` 映射为 class 0，按背景参加 softmax loss。

这不是“忽略监督”：`other` 覆盖的位置会明确告诉模型“这里不是五个目标前景类中的任何一个”。因此它会成为五个前景类的负样本，尤其会抑制 `small_molecule` 概率。

现有只读证据是：

- 一个 1,400-PDB 分片中，`other=20/57,337`，约 0.035%；
- 旧 mini-example 中，`other=16/521`，约 3.1%。

两份样本都低于用户给出的 5% 边界。它们不是全量统计，也不需要为了本轮架构结论扫描所有文件。当前决定的适用条件应写清楚：只要后续有代表性的训练清单统计仍低于 5%，就继续按背景；若后来证据明显超过 5%，再重新评估第七类或忽略监督，而不是提前把 loss 改复杂。

## 7. 建议的多分类标签契约

本节是最小改造建议，不是已经落地的用户命令。

### 7.1 原子标签建议

建议保留当前三个字段的数值语义，新增多分类字段，避免旧消费者把同名字段读出新含义：

| 字段 | 形状和类型 | 建议含义 |
|---|---|---|
| `binding_atom` | `(N_rec,) bool` | 兼容字段，仍表示离任意 occurrence 不超过 4 Å，包括 `other` |
| `instance_id` | `(N_rec,) int32` | 兼容字段，仍是当前最近 occurrence；背景为 `-1` |
| `nearest_dist` | `(N_rec,) float32` | 兼容字段，仍是到全部 occurrence 最近配体重原子的距离 |
| `atom_class_id` | `(N_rec,) uint8` | 新的六分类标签，值域 0..5；先沿用现有最近 occurrence，再把其 `type_tag` 映射为 class ID；超过 4 Å 或 `other` 均为 0 |
| `class_mask_small_molecule` 等五项 | 各 `(N_rec,) bool` | `atom_class_id == 对应 class_id`，便于检查和直接消费 |
| `supervised_binding_atom` | `(N_rec,) bool` | `atom_class_id > 0`，即五个受监督前景类的并集 |

这种做法只复用现有一次最近邻结果并增加一次 `type_tag→class_id` 映射，不引入第二套 tie 规则。它也明确保留了一个后果：如果最近 occurrence 是 `other`，即使稍远处还有已知类型，`atom_class_id` 仍为背景。这与“`other` 当背景”一致，且实现最小；若未来不接受这个科学语义，再单独讨论“从最近已知类型中选择”，不能在本轮静默改变。

### 7.2 配体区域体素标签建议

建议不改写现有 `union_mask` 的含义，因为它已经被 E3 validator、BOX pool 和推理 GT loader 用作“全部 occurrence 并集”。在 schema v4 中保留旧字段并新增：

| 字段 | 形状和类型 | 建议含义 |
|---|---|---|
| `mask_{candidate_id}` | `(K_occ,3) int32` | 原 occurrence 稀疏 ZYX mask，继续保留全部类型，包括 `other` |
| `centroid_voxel_{candidate_id}` | `(3,) float32` | 原 occurrence mask 的世界 XYZ 质心，语义不变 |
| `union_mask` | `(1,Z,Y,X) bool` | 原语义：全部 occurrence 的并集，包括 `other` |
| `class_id_map` | `(1,Z,Y,X) uint8` | 新的最终互斥六分类标签，值域 0..5 |
| `class_mask_small_molecule` 等五项 | 各 `(K_type,3) int32` | 每类最终获胜体素的稀疏 ZYX 坐标；它们互不重叠 |
| `supervised_union_mask` | `(1,Z,Y,X) bool` | `class_id_map > 0`，即五类最终前景的并集 |
| `class_names` | `(6,)` 字符串数组 | class ID 的固定名称和顺序 |
| `other_policy` | 标量字符串 | 固定记录 `background`，防止消费者猜测 |
| schema/source 字段 | 标量或哈希字符串 | 新 schema 版本、来源 occurrence/type/坐标哈希和几何身份 |

使用一个 `uint8 class_id_map` 作为权威训练标签，比保存六张完整 bool 图更不容易产生互相矛盾的结果；五个稀疏 class mask 则满足“每个 type 原生有 mask”并延续 E3 的稀疏存储风格。

### 7.3 跨类型重叠只使用一层规则

对落入多个不同 `type_tag` occurrence mask 的体素：

1. 计算该 voxel center 到每个相关 occurrence 的 present 配体重原子的最小距离；
2. 哪个 occurrence 的最小距离更小，就采用它映射后的 class ID；
3. 如果获胜 occurrence 是 `other`，最终 class ID 为 0；
4. 不新增“完全等距时较小 `candidate_id` 获胜”等业务分支。

同类型 occurrence 互相重叠时，类别本来相同，不需要为类别标签再决定 instance。原来的逐 occurrence `mask_{candidate_id}` 继续保存 instance 信息。

“不写完全等距分支”不代表程序可以输出两个类别；实现仍会由底层数组遍历或最小值操作产生一个确定结果，但不把那个偶然顺序上升为新的科学规则。测试应只验证结果合法、可复现且没有新增 candidate-ID 优先规则。

### 7.4 受体 home voxel 冲突

`voxel_label` 是由原子标签投影出的辅助监督。若多个受体原子落在同一个 home voxel 且类别不同，建议复用同一条规则：比较这些受体原子各自的 `nearest_dist`，更接近配体的原子类别获胜。这里不再设计第二套类别优先级或 candidate-ID 规则。

`hardmask` 仍只表示“这里有受体原子的 home voxel”，是 auxiliary loss 的有效位置；它不是类别标签，也不应与 `class_id_map` 混用。

## 8. Pocket_Plus 当前能力和必须改的接口

### 8.1 不需要重写的部分

Pocket_Plus 已有通用多分类基础：

- real atom head 支持多通道 logits 和 softmax prior；
- voxel auxiliary head、voxel ligand head 支持多通道；
- `AdaptiveClassificationCompositeLoss` 支持 `num_classes>2`；
- 普通 validation 指标能对每个前景类计算 one-vs-rest AP，再给出前景 macro；
- candidate builder 能对多通道 logits 做 softmax，并只抽 `candidate_class_ids` 指定的类别。

仓库中还有历史三分类 `[background, metal_ion, small_molecule]`。它证明通用组件可以多分类，但类别顺序、任务边界和 Ada 正式配置都不同，不能直接把历史 tri preset 当本次六分类配置。

### 8.2 Dataset/Collator 必改

`Pocket_Plus: src/datasets/stage1_dataset.py` 当前把三类 target 全部变成 bool。后续需要：

- `atom_label` 从 `atom_class_id` 读取并保持整数类别 ID；
- `ligand_area_target` 从 `class_id_map` 裁剪并保持整数类别 ID；
- `voxel_label` 在受体 home voxel 上写整数类别 ID；
- 旋转增强必须同步旋转整数 label，但不能把它转回 bool；
- Collator 保持 target 为 `torch.long`，形状仍与现有 loss 接口一致；
- `class_names` 改为六个固定名称，并校验顺序。

BOX pool 当前从全部非空 `mask_{candidate_id}` 生成 center/bias BOX。这个行为可以保留：五个类型都要参与普通辅助监督，BOX 来源不等于 CPC 候选类别。因为建议保留原 occurrence mask，所以已有 BOX pool 的科学定义不必随标签类别改变。

### 8.3 三个分类头改为六通道，P 保持单通道

建议新增 Ada 专用六分类 task preset，而不是改写历史 binary/tri preset：

| 头 | 目标通道数 | 概率解释 |
|---|---:|---|
| real atom head | 6 | 对六通道做 softmax |
| voxel auxiliary head | 6 | 对六通道做 softmax |
| voxel ligand head | 6 | 对六通道做 softmax |
| pseudo/P ligand head | 1 | 继续 sigmoid，只回答“是否属于 small molecule” |

对应地，atom、voxel auxiliary、voxel ligand loss 使用 `num_classes=6`；P loss 继续二分类 `num_classes=2`。

### 8.4 必修问题一：atom 到 P 的概率语义反了

`Pocket_Plus: src/model/stage1_atom_head.py` 当前写法是：

```python
atom_logits = self.real_atom_head(real_after)
real_bind_prob = torch.sigmoid(atom_logits[:, :1]).detach()
```

二分类单通道时，第 0 通道就是前景 logit；六分类后，第 0 通道固定为背景。若只把 head 改成六通道，这段代码会把“背景概率”当成“结合概率”喂给 `real_to_pseudo`，方向完全相反。

最小正确语义是：对六通道做 softmax，只取 class 1，也就是 `small_molecule` 的概率，再 detach 后供 P 交互使用。这里不能取五类前景之和，因为 P/CPC 已被用户限定为 small molecule 专用。

### 8.5 必修问题二：P target 不能直接抽多类 ID

`Pocket_Plus: src/wrappers/voxel_point_stage1.py::_sample_ligand_pseudo_supervision()` 当前用 P 的 home voxel 直接索引 dense target。六分类后会得到 0..5，但 P head 和 P loss 仍是单通道二分类；把 2..5 交给它是非法且语义错误的。

P target 必须显式变成：

```text
P_target = (dense_class_id == 1)
```

也就是说，small molecule 为 1，背景、`other` 及其余四类全为 0。P 的有效 mask 可以继续覆盖全部 P 行。

### 8.6 必修问题三：P 普通指标不能共用六类名称

当前 wrapper 给 atom、pseudo、receptor、voxel ligand 四个普通指标分支共用同一个 `class_names`。指标管理器要求 `len(class_names) == num_classes`。

六分类主任务配上二分类 P loss 后，pseudo 分支会出现“6 个名称对应 2 类”的直接报错。建议只给 pseudo/P 指标使用 `[background, small_molecule]`；其他三个分支使用六类名称。

普通指标可以报告 atom、voxel auxiliary、voxel ligand 的五个前景 one-vs-rest AP 和前景 macro。这些是普通分类指标，不是五类 CPC 指标，也不意味着五类候选生成。

### 8.7 loss 与主辅任务权重

`other` 既然映射背景，现有 loss 不需要 `ignore_index` 改造。所有有效位置的 target 都在 0..5 内。

现有多分类 Tversky 会对五个前景类别做简单平均，focal 可以按类配置权重。用户的任务优先级是 small molecule 为主、其余四类为辅助，因此后续配置应显式体现主辅权重，否则四个辅助类合计可能主导梯度。

具体权重不在本轮拍数。建议先从新标签的训练 split 统计每类原子和体素数量，再决定 focal alpha、Tversky 权重或分支总权重。这里需要的是一个有意选择的策略，不是预先塞入未经统计的数值。

现有 voxel auxiliary 和 voxel ligand 多分类头会共用一份 `prior_probs`，但二者的类别分布通常不同。第一版可以选择关闭 prior bias 初始化，或把两个头的先验拆开；不建议把同一组六类频率同时假定为两种标签的真实先验。

### 8.8 W&B 只增加四条辅助类型损失曲线

这是用户明确增加的日志要求。W&B 不需要展示所有类别、所有 head 的组合矩阵；只增加四个非 ligand 前景类型的简洁曲线：

```text
ion
sugar
peptide_like
nucleotide_like
```

建议的日志契约是：

- `train_loss/class/ion`、`train_loss/class/sugar`、`train_loss/class/peptide_like`、`train_loss/class/nucleotide_like`；
- 对应的 `val_loss/class/...` 四条验证曲线；
- 每个 class 只保留一条跨已启用六分类 head 聚合后的曲线，不拆成 atom、voxel_aux、voxel_ligand 三套 panel；
- 聚合时使用现有 head loss weight，计算来自 detached logits 的诊断值，不改变反向传播的 total loss；
- 背景和 `small_molecule` 不新增这组曲线，P 头也不新增，因为 P 本身是 small-molecule 二分类；
- 现有 `train_loss/global/*`、`val_loss/global/*` 和 total loss 日志保持不变，不用 W&B table、histogram 或额外 per-class AP 替代这四条曲线。

“按类损失”必须沿用当前 `AdaptiveClassificationCompositeLoss` 的 focal/Tversky 配置计算，并按 epoch 的有效样本数聚合；一个 batch 没有某类别时不写假装为 0 的值。它是监控辅助任务是否在学习的诊断，不是新的优化目标，也不改变四类辅助任务的 loss 权重。

## 9. CPC 和下游严格只看 small molecule

配置边界应保持：

```yaml
candidate_class_ids: [1]
```

因此所有“按候选类别排列”的数组长度仍为 1，包括：

- warmup top-C；
- adaptive expand factor；
- 每类最小/最大候选体素数；
- 每类最大 anchor 数；
- `p_best`、`p_sampling` 阈值缓存；
- C、P 和 CPC diagnostics 的逐类统计。

当前 candidate builder 已能对六通道 softmax 后只取 class 1，没必要为其他四类各建一份候选链。forest、CLG、Selector 和 calibration 继续读取 small-molecule 概率即可。

推理真值侧有一个必须同步收窄的接口：`Pocket_Plus: src/inference/assembly.py::AGOccurrenceVoxelLoader` 当前读取全部 `mask_{candidate_id}`，验证它们的并集等于 `union_mask`，然后把全部 occurrence 返回给 calibration、candidate-GT overlap 和实例指标。多分类后应：

1. 继续用全部 occurrence mask 验证原 `union_mask`，保留 E3 完整性检查；
2. 读取同一 PDB 的 `parse/{pdb_id}/occurrences.jsonl`；
3. 对外只返回 `type_tag == small_molecule` 的 occurrence mask；
4. forest/CLG/Selector、candidate-GT overlap、实例 calibration 因而只看到 small-molecule 真值。

这不是“逐类候选生成”，而是把唯一候选任务的真值口径从“所有配体”纠正为“small molecule”。

## 10. 推理和概率图发布的最小兼容方案

### 10.1 当前二分类断点

- `src/inference/probability.py` 只接受单通道 logits 并做 sigmoid；
- `src/inference/full_map.py` 只融合一张 `(D,H,W)` 概率图，只发布 `probability_map`；
- `src/inference/centered.py` 对 ligand、aux、A 都使用单通道 sigmoid；
- 完整图后续直接读取 `probability_map` 生成组件森林。

### 10.2 当前 Find 的 class-1-only 推理边界

训练模型的三个分类头仍输出六个 logits，并在训练 loss/指标中计算六类 softmax。这是辅助任务和未来接口，不等于当前推理要消费六类概率。

当前 Find 推理只对 `small_molecule` 对应的 class 1 生成和读取概率：

| 字段 | 形状 | 当前消费者 |
|---|---|---|
| `probability_map` | `(D,H,W) float32` | C、P、CPC、forest、CLG、Selector、calibration；严格代表 class 1 |
| `class_names` | 可选元数据 | 记录 class 1 的固定含义，避免旧字段被误解释 |

推理运行时不为 `ion`、`sugar`、`peptide_like`、`nucleotide_like` 计算、融合或发布全图概率；它们的四个通道在模型输出后直接丢弃。未来若确实需要这些概率，应另开明确的诊断/发布入口，不改变当前 Find 的下游契约。

centered 输出也可保持旧字段名和下游形状：

- `ligand_probability` = voxel ligand softmax 的 class 1；
- `voxel_aux_probability_grid` = voxel auxiliary softmax 的 class 1；
- `A_probability` = atom softmax 的 class 1；
- `P_probability` 仍由单通道 sigmoid 得到。

如果需要保留其他类 centered 概率，应放在独立多类字段中，不能让旧字段突然从一维变六维。

### 10.3 Find receptor hardmask

当前 Find 仍只对 class 1 的 `probability_map` 应用 receptor home voxel hardmask，并把这些 voxel 清零。由于其他四类当前不进入推理，也不需要为它们设计全图 hardmask 或重新归一化规则。

## 11. checkpoint 影响

- CPC2 当前会 strict 加载 CPC1 的同名 BEST checkpoint。只要 CPC1、CPC2 都从新的六分类配置训练，结构一致，strict 加载没有问题。
- 旧二分类 checkpoint 的 atom/voxel head shape 与六分类不同，无法 strict 加载到新模型。
- 正式推理 loader 同样使用 `strict=True`，因此不能把旧二分类 checkpoint 假装成六分类 checkpoint。
- 当前正式训练尚未开始时，最小方案是直接从新的六分类 CPC1 开始，不做旧 checkpoint 权重迁移。

## 12. 精确重跑范围

### 12.1 AdaLigand 数据侧

| 内容 | 是否重跑 | 原因 |
|---|---|---|
| Stage A/B | 否 | 与标签类型无关 |
| Stage C | 通常否 | 已有 occurrence、`type_tag`、配体 present 坐标和受体坐标 |
| Stage D | 是 | 需要生成 `atom_class_id` 和逐类原子 mask |
| Stage E1/E2 | 否 | 实验图和 receptor-only 模拟图不因类别变化改变 |
| Stage E3 | 是，仅标签部分 | 需要生成 `class_id_map`、逐类 mask 和 supervised union |
| Stage F/G | 否 | 用户决定沿用现有 F 结果和 G 过滤，不改科学逻辑 |
| BOX pool | 若原 occurrence mask 保持字节/语义一致，可不重建 | BOX 中心仍来自全部 occurrence；训练 Dataset 改读新标签即可 |

旧 `stage_e3_repair` 是一次性迁移/修复脚手架，不能直接冒充长期默认的“只重打标签”入口。后续实现可以新增一个明确的 label-only 生产入口，或把现有长期 E3 入口收敛为可独立运行且有正式 validator/release 的标签生产路径。

新 D/E3 标签与旧 F/G 结果组合使用时，应在新 release/manifest 中记录两者 lineage，说明“标签来自新 schema，质量过滤沿用旧 F/G release”。不能通过覆盖旧 run 身份，把它们伪装成同一轮原始 A-G 产物。

### 12.2 D/E3 重算时顺便生成类型统计

这是用户明确要求的生产伴随统计，不是重新扫描一遍数据的独立任务。D 和 E3 已经逐 PDB 读取 occurrence、`type_tag`、坐标和网格，因此在同一轮 label-only 重算中顺便累计每种 `type_tag` 的简单统计。

每个 occurrence 至少记录以下两个原始量：

- `raw_ligand_area_voxel_count`：该 occurrence 的原始 `mask_{candidate_id}` 体素数。它表示该 occurrence 按现有 vdW stencil 实际占了多少 ligand-area 体素；重叠 occurrence 各自计数，不能拿 union 体素数代替。
- `raw_binding_atom_count`：当前 Stage D 最近 occurrence 语义下，满足 `binding_atom=true` 且 `instance_id==candidate_id` 的受体原子数。

按 `type_tag` 聚合并输出：

| 统计量 | 定义 |
|---|---|
| occurrence 数 | 该类 occurrence 的总数 |
| 平均 ligand-area 体素数 | 该类 occurrence 的 `raw_ligand_area_voxel_count` 平均值；没有该类 occurrence 时写 `null`，不写 0 |
| 平均 binding atom 数 | 该类 occurrence 的 `raw_binding_atom_count` 平均值；没有该类 occurrence 时写 `null` |
| 每 PDB 平均 occurrence 数 | 该类 occurrence 总数 / 本轮纳入统计的 PDB 总数，分母固定并写入报告 |
| PDB 出现率 | 含至少一个该类 occurrence 的 PDB 数 / 本轮纳入统计的 PDB 总数 |

其中“每 PDB 平均 occurrence 数”是“平均在每个 PDB 中出现几次”的可复算定义；同时保留 PDB 出现率，避免把“一个 PDB 中出现 5 次”和“5 个 PDB 各出现 1 次”混成同一个事实。

统计应覆盖六个 `type_tag`，包括最终映射为背景的 `other`。对 `other` 仍报告它的原始 area 和原始 binding 数，这样可以观察“被当背景的真实对象”规模；训练标签另外可从 `class_id_map` 派生 `supervised_*` 统计，但不替代上述原始统计。

建议的落盘位置是每个 PDB 的 D/E3 状态报告和本轮 run 的聚合 JSON/JSONL；统计字段必须带 `type_tag`、PDB 分母、样本数、输入 release/source hash 和标签 schema 版本。它不进入 W&B，也不改变 F/G 过滤。

### 12.3 Pocket_Plus 训练和推理侧

需要重新训练新的六分类模型。旧概率图、阈值、组件森林、CLG、Selector 产物都绑定旧二分类 checkpoint，不能直接代表新模型结果。

数据标签只需重做 D/E3；模型产物则从六分类 CPC1 开始重新产生，CPC2、完整图 probability、阈值、forest/CLG/Selector 按现有依赖顺序重新生成，但这些下游仍只有 small-molecule 一条候选链。

## 13. 预计改动面

下面是实现阶段的文件级计划，不表示本轮已经修改。

### 13.1 AdaLigand

- `Data_Preprocessing/Ori_Data/code/atom_labels.py`：生成、校验和发布原子多分类字段。
- `Data_Preprocessing/Ori_Data/code/density.py`：生成、校验和发布 E3 多分类字段及跨类型最近距离合并。
- `Data_Preprocessing/Ori_Data/scripts/d_atom_labels.py`、`Data_Preprocessing/Ori_Data/scripts/e_density.py`：把 occurrence `type_tag` 传入核心生成函数，更新 label-only 运行身份和报告。
- 对应 D/E3 tests：类别优先顺序、`other→0`、跨类型重叠、原 union 兼容、source hash、原子/home-voxel 冲突。
- 实现获批后再按治理流程更新 `数据处理_v2.md`、执行日志、mapping 和 code-near README；本轮不回填。

### 13.2 Pocket_Plus

- `src/datasets/stage1_dataset.py`、`src/datasets/stage1_collate.py`：读取和拼接整数多分类 target。
- 新的 Ada 六分类 dataset/model/loss/experiment presets：固定 class 顺序、三个六通道头、P 单通道、`candidate_class_ids=[1]`。
- `src/model/stage1_atom_head.py`：atom 到 P 改取 small-molecule softmax 概率。
- `src/wrappers/voxel_point_stage1.py`：P target 二值化、P 指标类别名分离；CPC 仍只 class 1。
- `src/wrappers/voxel_point_stage1_metrics.py`：确认普通五前景 AP/macro 和二分类 P 分支可同时工作；不扩展 CPC 类别。
- `src/inference/probability.py`、`src/inference/full_map.py`、`src/inference/centered.py`：从六分类头只提取 class 1，保持当前单通道 Find 概率图；不为其他四类做全图融合。
- `src/inference/assembly.py`：全部 mask 做完整性验证，对下游只返回 small-molecule occurrence GT。
- artifact schema/validator/tests：冻结 `probability_map` 的 class-1 语义，并验证推理不读取其他四类概率；六类训练输出作为未来接口另行保留。
- checkpoint/config tests：六分类 CPC1→CPC2 strict 成功、旧二分类→六分类 strict 明确失败。

## 14. 测试与验收计划

### 14.1 数据标签

1. 用合成 CCD/entity 输入逐条验证 `type_tag` 的六条优先顺序，特别覆盖 branched、糖、肽、核酸、单原子金属、单原子氯和 `other`。
2. 验证原子 `atom_class_id` 值域为 0..5，五个 class mask 互斥，`supervised_binding_atom == atom_class_id>0`。
3. 验证 `other` 在 4 Å 内时得到 class 0，而兼容 `binding_atom` 仍按旧定义为 true；把这个差异写进契约测试，避免消费者误用。
4. 构造两种已知类型重叠的体素，只用“到 present 重原子的最小距离”决定类别。
5. 构造 `other` 与已知类型重叠，验证 `other` 距离更近时 class 0。
6. 验证不新增 candidate-ID tie 业务分支；同类型重叠不影响最终类别。
7. 验证五个 class mask 互斥且并集等于 `supervised_union_mask`；原 `union_mask` 仍等于全部 occurrence mask 的并集。
8. 验证 E3 网格中心、ZYX/XYZ 轴顺序、范德华半径和原 schema v3 的几何数值不因类别改造漂移。

### 14.2 训练接口

1. Dataset/Collator 输出 `torch.long` 的 atom、voxel auxiliary、voxel ligand target，值域 0..5。
2. 三个分类头输出 6 通道；P 输出 1 通道。
3. atom 到 P 的权重精确等于 atom softmax class 1，不是背景概率，也不是五类前景和。
4. P target 对 dense class 1 为 1，对 0、2、3、4、5 均为 0。
5. 三个多类普通指标产生五个前景 AP 和 macro；P 只产生二分类 small-molecule 指标。
6. CPC diagnostics、阈值缓存和候选预算的类别轴长度始终为 1，类别 ID 始终为 `[1]`。
7. 其他四类概率变化不能生成额外 C/P 或改变其候选预算。

### 14.3 推理和下游

1. 训练 forward 的每个 voxel/原子位置六类 softmax 概率和约为 1；Find 推理只提取 class 1，并沿用单通道 hardmask。
2. `probability_map` 数值严格等于模型输出的 class 1 概率。
3. forest、CLG、Selector 只读取 `probability_map`，推理过程不扫描、不融合其他四类概率。
4. `AGOccurrenceVoxelLoader` 仍用全部 occurrence 验证 E3 union，但返回的 GT 只含 `small_molecule`。
5. calibration、candidate-GT overlap、实例指标只对 small-molecule occurrence 计数。
6. 以一个真实 PDB 做 D/E3→Dataset→forward→class-1 概率图→small-only overlap 的小型贯通测试，再考虑正式批量生产。

## 15. 规划与实现漂移分类

### 15.1 有益漂移

Pocket_Plus 的通用头、loss、普通多类指标和 candidate builder 已具备多分类能力，比现有 Ada 二值计划预设的基础更强。这使本次不需要重写网络主干。

### 15.2 中性漂移

历史 tri 任务已经验证 softmax 多类路径，但它使用 `[background, metal_ion, small_molecule]`，与本次六类顺序不同。它可作为实现参考，不能作为正式配置直接复用。

### 15.3 有害漂移

- `数据处理_v2.md` 写有 `class_mapping.yaml` 训练映射意图，但仓库没有可消费的正式映射和多类标签产物。
- Ada Dataset 强制把标签读成 bool，类型信息无法进入 loss。
- 六分类后若不改 atom→P，背景概率会被当成结合概率。
- 六分类后若不改 P target，2..5 会被送入二分类 P loss。
- 推理仍发布唯一的 small-molecule 单通道概率图；模型训练头虽为六分类，其他四类当前不形成概率图产物。
- GT loader 当前把全部 occurrence 交给本应只服务 small molecule 的候选和实例评价。

### 15.4 未完成范围

- 多类 D/E3 artifact schema 和长期 label-only 生产入口；
- Ada 专用六分类 task/loss/dataset preset；
- 六类训练输出的未来诊断接口（当前推理不发布）；
- small-molecule-only GT loader；
- 主任务与四个辅助类的具体 loss 权重；
- voxel auxiliary 与 voxel ligand 是否拆分 prior；
- 新标签 release 与旧 F/G release 的组合 lineage。

本轮只报告这些漂移。是否回填现有三份 Stage1 计划、BOX 契约、mapping 和 README，应在实现方案获批后按治理流程单独决定。

## 16. 风险和仍需保留的未来议题

### 16.1 `other` 当背景的风险边界

低比例时，把 `other` 当背景能避免第七类和 `ignore_index` 链路，符合最小改造目标。代价是模型会被训练为压低 `other` 区域的五类前景概率；其中若混有有意义但解析规则未覆盖的配体，它们会成为有噪声的负样本。

本轮不需要全量枚举才能作出设计选择。后续只需在新训练清单自然生成统计时复核比例是否仍低于 5%；这是一项发布证据，不是启动本次设计的前置大扫描。

### 16.2 F/G 是否未来按类型过滤

本轮决定是直接沿用现有 F 结果和 G map-level 过滤：通过一个 PDB 就保留它的全部 occurrence，不根据 `type_tag` 二次删除。

未来若发现某一辅助类型的 Q-score/口袋 Q 分布与 small molecule 差异很大，可以另开设计讨论“F/G 是否需要 type-aware 阈值”。这会改变训练样本选择和质量定义，必须基于分布单独批准，不能塞进当前标签重打或 CPC 小改。

### 16.3 `other` 与已知类别相邻

建议的最小原子规则会复用“全 occurrence 最近实例”，因此 `other` 更近时标签为背景。建议的体素重叠规则也允许 `other` 以距离获胜后映射背景。这一点必须用测试锁定；若以后希望 `other` 只填空、不压过已知类别，那是另一种科学定义，需要显式改计划。

## 17. 建议实施顺序

1. 先冻结 D/E3 新 schema、六类顺序、`other→background` 和唯一距离合并规则。
2. 实现并验证 D/E3 label-only 生产；在同一轮按 `type_tag` 生成 occurrence 面积、binding atom、每 PDB 平均次数和 PDB 出现率统计，保留原 occurrence mask/union 和旧 F/G lineage。
3. 在 Pocket_Plus 新建 Ada 六分类 preset，改 Dataset/Collator 和三个必修接口：atom→P、P target、P metric names。
4. 先跑不含 CPC 扩展的普通六分类单元测试，确认三个 head 和 loss 端到端合法；训练日志另外只增加 `ion`、`sugar`、`peptide_like`、`nucleotide_like` 四条辅助损失曲线。
5. 固定 `candidate_class_ids=[1]`，验证 CPC 的所有类别轴仍只有 small molecule。
6. 改多分类推理接口但只提取 class 1，同时保留 `probability_map`、`A_probability` 等 class-1 字段；不计算或融合其他四类全图概率。
7. 收窄 occurrence GT loader，验证 forest/CLG/Selector/calibration 只消费 small molecule。
8. 用真实小样本贯通后，再生成正式新标签 release 和训练产物。

这个顺序的核心不是把系统扩成“五套候选链”，而是先让标签和普通分类原生支持五种前景，再把原有 small-molecule 二分类下游稳定地接到六类 softmax 的 class 1 上。

## 18. 外部调研：扩散/流匹配模型通常把 ligand 当什么

本节回答的是“现有论文和公开实现怎么做”，不是把外部模型直接当成 AdaLigand 的规格。判断时分开三层：

1. **接口能不能表达**：例如能否读 SMILES、CCD、核酸或离子；
2. **训练集是否覆盖**：训练数据是否真的包含该类对象，而不是理论上可以编码；
3. **论文是否验证过**：有没有对这类对象报告结果。

把这三层混在一起，会把“能读一个字符串”误报成“已经学会广谱配体”。

### 18.1 主流药物 docking/SBDD：确实以小分子为中心

| 模型/论文 | 方法 | 对配体范围的直接证据 | 对本项目问题的解释 |
|---|---|---|---|
| DiffDock / DiffDock-L | 扩散模型，在平移、旋转、扭转自由度上生成 docking pose | 官方 README 的 FAQ 明确说模型只为蛋白质上的 small-molecule docking 设计、训练和测试；输入虽可为 SMILES、SDF、MOL2，但不建议用于大生物分子 | “接口能读文件”不等于支持糖链、金属离子；主训练语义是 drug-like small molecule |
| DiffSBDD | SE(3) 等变扩散，口袋条件下从零生成配体 | 论文摘要直接把任务称为生成 small-molecule ligands / drug candidates | 典型 de novo 小分子生成，不是广谱配体生成器 |
| TargetDiff、Pocket2Mol、DecompDiff | 3D 口袋条件分子生成/药物设计 | 公开摘要和 GenBench3D 评测都以 molecules、drug candidates、CrossDocked/PDB 口袋为对象 | 训练和评价的中心是有机小分子，糖链、单原子金属、长肽不是默认任务 |
| DiffPepBuilder | SE(3) 扩散的肽 binder 设计 | 单独用蛋白-肽复合物和专门的 PepPC-F 数据集训练 | 这是“肽单独做一个模型”的例子，反而说明广谱对象通常被拆成专门任务 |
| FlowDock | 条件 flow matching，生成 apo→holo 蛋白-配体复合物 | 论文/官方 README 的训练与评测包括 PDBBind、BindingMOAD、DockGen、PDB-sidechain 和 PLINDER；输入是 ligand SMILES，可生成任意数量的 ligand。README 还给出一个多糖样 SMILES 的 T1152 示例 | 它的输入接口比 DiffDock 更宽，至少不能简单说“只能小分子”；但公开训练/评测仍不是按金属、糖链、肽、核酸四类系统验证的广谱任务 |

因此，对问题 1 的准确回答是：**如果“现有模型”指主流基于蛋白口袋的药物 docking 和 de novo SBDD，那么大多数确实把 ligand 设计成 drug-like small molecule；糖链和金属等不是默认覆盖范围。但不能说所有扩散/流匹配模型都忽略它们，FlowDock 的 SMILES 接口和后面的统一生物分子模型是例外或边界案例。**

几个具体来源：

- DiffDock 论文：[arXiv:2210.01776](https://arxiv.org/abs/2210.01776)；官方实现的 FAQ 还明确写出 small-molecule-only 的训练/测试边界：[github.com/gcorso/DiffDock](https://github.com/gcorso/DiffDock)。
- DiffSBDD：[arXiv:2210.13695](https://arxiv.org/abs/2210.13695)。
- Pocket2Mol：[arXiv:2205.07249](https://arxiv.org/abs/2205.07249)。
- DecompDiff：[arXiv:2403.07902](https://arxiv.org/abs/2403.07902)。
- DiffPepBuilder：[arXiv:2405.00128](https://arxiv.org/abs/2405.00128)。
- FlowDock：[arXiv:2412.10966](https://arxiv.org/abs/2412.10966)；官方代码和数据说明：[github.com/BioinfoMachineLearning/FlowDock](https://github.com/BioinfoMachineLearning/FlowDock)。

### 18.2 是否存在同时纳入广谱配体的扩散算法

**存在，但要先说明“纳入”是哪一种纳入。**

#### A. 统一生物分子复合物预测：有

AlphaFold 3 的论文摘要明确说它是 diffusion-based architecture，能够在一个统一框架中联合预测包含：

- 蛋白；
- 核酸；
- small molecules；
- ions；
- modified residues。

所以它回答了“是否有一个 diffusion 模型可以同时处理比 drug-like small molecule 更广的对象”：答案是有。它的目标是复合物结构预测，不是从空口袋里自由生成任意新化学结构，也不是专门为 cryo-EM ligand blob 做候选发现。

论文：[Accurate structure prediction of biomolecular interactions with AlphaFold 3](https://doi.org/10.1038/s41586-024-07487-w)，PubMed 摘要：[PMID 38718835](https://pubmed.ncbi.nlm.nih.gov/38718835/)。

Boltz-1/Boltz-2 是同一类“统一生物分子相互作用预测”路线的开源实现，但它们也不应被描述成专门的广谱 ligand de novo generator；它们的价值在于统一复合物建模和 ligand/affinity 预测。

#### B. 已知 ligand 身份下的广谱结构建模：有，Emap2lig-Build 是直接相关例子

Emap2lig-Build 是 diffusion-based 的 cryo-EM ligand structure modeling。它不是先决定“这里是什么化学物质”，而是输入已知的参考 ligand conformer，在 Find 找到的密度区域中生成该 ligand 的三维构象。它支持的广谱性来自：

- 候选输入接口可接受 `CCD`、`SMILES`、`BRANCHED`；
- `LigandObject` 保存原子序数、带电、键、环和参考坐标；
- Build 的 15 类 augment 语义包含 `C/N/O/P/S/Metal`，并把这些语义作为扩散模型的空间/化学条件；
- 论文数据集确实含有小分子、共价连接糖、多糖样对象、磷脂和含金属的 heme 等实例。

但它不是“所有五类都由模型自主识别和生成”的证明：ligand 身份由外部候选提供，Build 主要生成坐标/构象；训练集对单原子金属离子并没有与小分子同等的覆盖证据。

#### C. 没有找到的东西

截至本调研，没有找到一个与 AdaLigand 目标完全同构的公开模型：

- 输入一张 cryo-EM map；
- 在一个统一的五类 ligand-type head 中同时识别金属离子、糖链、小分子、多肽、核酸片段；
- 再让同一个下游生成/对接管线对这五类都自动产生候选。

现有工作更常见的是三种拆分：药物小分子模型、肽/核酸专门模型、或统一生物复合物预测模型。AdaLigand 采用“类型多分类作为辅助监督，候选下游只服务 small molecule”的折中，和现有文献的工程分层是相容的。

## 19. Emap2lig 第二阶段 Build 的配体范围

### 19.1 论文给出的训练集定义

对 `Emap2lig/paper.pdf` 的 Dataset Construction 原文逐段核对后，Build 的 ligand 定义是：

1. 与蛋白链或核酸链区分开的 small molecules；
2. 与蛋白侧链共价连接的 saccharides，例如 NAG、BMA、MAN；
3. 每个对象超过 3 个 heavy atoms。

这条定义意味着：

- 糖类并没有被一律排除，至少共价连接的糖和多糖样 ligand 被纳入；
- “metal”作为元素语义进入模型，但**单原子金属离子不满足“超过 3 个 heavy atoms”的训练集定义**，不能宣称 Build 已系统训练/验证单原子 ion；
- 多原子含金属 ligand（例如 HEM）可以进入，论文示例也确实展示了 HEM；
- 小离子并非全都排除，像 CO3 (carbonate) 被论文作为 4 个 heavy atoms 的小 ligand 例子，但这不等于所有离子都覆盖。

论文统计：原始数据包含 94,379 个 ligand instances、1,652 个 ligand classes；经过 Find instance-level recall ≥ 0.3 的 Build 筛选后保留 72,938 个 instances、1,293 个 classes。ligand 类型总数报告为 1,807，heavy-atom 数量范围为 4 至 200，平均 32.4。

### 19.2 论文中的实际例子

论文 Figure 6 的 Build 例子包含：

- `NAG-NAG-BMA-BMA`：明显属于糖链/多糖样对象；
- `HEM`：含金属元素的 heme ligand；
- `LHG`：磷脂；
- `FBP`：带糖/磷酸基团的代谢物；
- `GBM`、`KFL` 等普通小分子。

这些例子足以证明 Build 不只覆盖传统药物小分子，也能处理糖、脂质、代谢物和含金属复合 ligand。但它们仍然是**已知 ligand identity 的构象建模**，不是从密度图自动分类出 `small_molecule/sugar/ion/...` 后再从零生成化学结构。

### 19.3 Build 的 15 类 UNet 到底是不是“15 种配体类型”

不是。`src/emap2lig/model/modules/instance_seg.py` 的 15 类 augment 语义是：

- 6 个结构类：`ligand, backbone, sidechain, sugar, phosphate, base`；
- 6 个元素类：`C, N, O, P, S, Metal`；
- 3 个环类：`Ring4, Ring5, Ring6`。

其中前 6 类来自 Find 的结构语义；`sugar` 指核酸糖环/结构标签，不等于 AdaLigand 的 `sugar` ligand type。后 9 类是元素和环的化学辅助语义。它们被拼进 voxel features，帮助 diffusion module 摆放**已知 ligand 的原子**。

Build 主流程仍只有一个 ligand instance segmentation mask；Find 的其他结构通道不会各自形成五条 Build 候选链。

### 19.4 代码接口与论文训练范围的差异

`src/emap2lig/main.py` 的 `LigandRecord` 支持 `CCD`、`SMILES`、`BRANCHED` 三种输入，`prepare_ligand_dataset()` 将它们物化成统一 `LigandObject`。这说明推理接口能表达：

- 普通 CCD ligand；
- 任意 RDKit 可解析的 SMILES ligand；
- 由多个 residue 和 inter-residue bond 组成的 branched ligand，例如糖链。

但接口能力不自动扩大训练分布。对于某个新型金属离子、很长核酸片段或不在训练化学分布内的多肽，代码可能能构造输入，模型性能仍需单独验证。

Emap2lig 相关证据：仓库 `paper.pdf`、`src/emap2lig/main.py` 的 `parse_ligand_list()`/`prepare_ligand_dataset()`、`src/emap2lig/data/types.py` 的 `LigandObject/LigandRecord`、`src/emap2lig/model/modules/instance_seg.py` 的 15 类 `labels`。

## 20. 这组调研对 AdaLigand 简化方案的影响

调研结果支持保留当前的最小边界，而不是把整个下游扩成五类：

1. 主流 drug-like diffusion/flow docking 本来就把 small molecule 作为主任务；因此 `small_molecule` 作为 CPC 唯一候选类并不反常。
2. Emap2lig-Find 会预测多个结构语义，但真正切 blob 的只有 ligand 通道；这与“其他四类训练时存在，推理下游不消费”高度相似。
3. Emap2lig-Build 的广谱性主要来自候选 ligand 化学特征和辅助元素语义，而不是让五种 ligand type 各自产生一条后处理链。我们可以借鉴它的“辅助语义帮助共享表示”思路，但不需要复制 15 类 Build augmentation。
4. AlphaFold 3 证明统一广谱复合物 diffusion 是可行方向，但它解决的是更大的复合物结构预测问题，不能作为 AdaLigand 必须把其他四类送入 forest/CLG/Selector 的理由。
5. 因此，另外四个类别只做普通监督、普通指标、W&B 四条损失曲线和未来概率接口；不读取它们的推理概率图，不生成它们的候选，是有文献依据的工程取舍。

仍需保留的风险是：如果未来任务从“small molecule 找口袋”扩展为糖链/金属/肽的定位或结构建模，当前下游边界会成为真正的功能缺口；那时应参考 AF3 的统一复合物路线或 Emap2lig 的候选 ligand 条件路线另立任务，而不是把当前 CPC 隐式扩成多类。

## 21. 外部资料和本地证据索引

| 证据 | 用途 |
|---|---|
| DiffDock 论文与官方 README | 证明主流扩散 docking 的 small-molecule 训练/测试边界 |
| DiffSBDD、Pocket2Mol、DecompDiff 摘要 | 证明 de novo SBDD 文献把目标定义为 small-molecule/drug candidates |
| FlowDock 论文与官方 README | 证明 flow matching 支持多 ligand 和 SMILES 接口，但公开数据/评测仍以 protein-ligand 为中心 |
| DiffPepBuilder | 证明肽 binder 常被单独建模，而非自动纳入 small-molecule 模型 |
| AlphaFold 3 DOI/PubMed | 证明存在覆盖 proteins/nucleic acids/small molecules/ions/modified residues 的 diffusion 统一框架 |
| `Emap2lig/paper.pdf` | Build 数据集定义、94,379 instances、1,807 ligand types、糖/HEM/磷脂等案例、15 类 augment 语义 |
| `Emap2lig/src/emap2lig/main.py`、`data/types.py` | Build 的 `CCD/SMILES/BRANCHED` 输入接口和统一 `LigandObject` |
| `Emap2lig/src/emap2lig/model/modules/instance_seg.py` | Build 15 类 augment head 的真实标签顺序和“辅助条件而非五条候选链”语义 |
