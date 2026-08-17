# Matcher 单候选闭集配体身份分类新方案

> 文档类型：当前有效的科学与首轮实验计划。
>
> 适用范围：Matcher 独立仓库从提交 `6220ece3595e48dae9ee1ef749146efa1048305c` 开始的单候选重写。
>
> 执行证据：`C:/Users/15919/Desktop/Matcher/文档/exec_plan/Matcher_单候选闭集身份分类重写执行记录.md`。
>
> 本文只规定目标行为、实验矩阵和完成判据；具体提交命令、作业编号、阶段发现与临时处置只写入执行记录。

除明确标记为“暂定”或“待复核”的内容外，本文中的任务、数据、模型、损失、首轮实验和资源边界均作为首轮冻结契约执行。

## 1. 目标、任务和不在范围内的内容

新 Matcher 处理 Stage1 Find_0 产生的单个候选，不再把一个 PDB 的全部候选与全部真实配体组成匹配矩阵，也不使用匈牙利算法建立一一分配。第一轮包含两个相互关联但分别评估的任务。

1. **候选六分类**：对全部 Find_0 候选预测 `background`、`ion`、`nucleotide_like`、`peptide_like`、`small_molecule`、`sugar`。这一任务不读取配体语言表示或配体图。
2. **小分子闭集身份分类**：在同一候选编码器后，从当前 PDB 的去重小分子身份清单中选择身份。多个候选可以选择同一身份，不施加 PDB 级计数或一一对应约束。

完整 Matcher 不建立“假阳性身份槽”。候选是否为背景或非小分子由六分类头判断；身份头只在真实类别为 `small_molecule` 且当前语言模型存在有效目标时接受监督。因而，本文所称“闭集”只表示从当前 PDB 已知的小分子身份清单中选择，不能表述为从整个化学空间识别未知配体。

第一轮不包含以下内容：

- 不依赖 Stage1 推理产物的 `ground_truth_context` 数据模式；
- 旧 O/O′、匈牙利匹配或额外几何回归辅助头；
- 受体残基语言模型 token；
- PDB 级全局后处理、配体 occurrence 定位和 Stage3 结构生成；
- 在首个完整训练超过 16 小时后继续追加随机种子。

旧 Anchor O/O′、双模式 ABO 和上一轮 Matcher 的代码与文档只作为 Git 历史和实验依据保留，不再定义活动科学入口。

## 2. 数据与监督契约

### 2.1 正式输入与划分

Find_0 候选来自：

`/storage/penghongen/AdaLigand_stage1_inference/Find_0-CPC1-ligand_PRAUC_0.675477/artifacts/Find_0`

配体 occurrence、受体、密度、配体图和冻结语言表示来自：

`/storage/penghongen/AdaLigand/Ori_Data`

train、validation 和 calibration 按 PDB 互斥。训练与模型选择只读取 train 和 validation；calibration 在首轮方案选定后才允许做一次保留评估。由于 `blob_exceed` 而没有 Find_0 推理产物的 PDB 直接跳过，记录排除原因，不视为数据错误，也不进入任何指标分母。

### 2.2 六分类标签

令候选完整全局体素集合为 $C$，真实配体 occurrence 的全局体素集合为 $O_j$。定义双向覆盖率：

$$
r_{C,j}=\frac{|C\cap O_j|}{|C|},
\qquad
r_{O,j}=\frac{|C\cap O_j|}{|O_j|}.
$$

当且仅当 $r_{C,j}\ge 0.30$ 且 $r_{O,j}\ge 0.30$ 时，occurrence $j$ 命中候选。存在多个命中时，选择

$$
q_j=\sqrt{r_{C,j}r_{O,j}}
$$

最大的 occurrence；分数并列时按稳定的 occurrence 编号顺序选择。候选继承该 occurrence 的类型类别，`other` 映射为 `background`；没有命中时也标记为 `background`。

这项监督始终使用完整全局候选 $C$。模型输入中的 V、PP 和体素网格即使裁剪到候选中心 `48³`，也不能反向改变标签。

### 2.3 小分子身份与 occurrence 级语言表示

MoLFormer 与 SMI-TED Light 289M 的冻结表示已经按 `(pdb_id, occurrence)` 粒度生成；首轮 Matcher 只读取这些产物，不重新训练或在线运行语言模型。

第一轮在每个 PDB 内暂时把 `object_key` 当作已经去重的小分子身份键。同一 `object_key` 的不同 occurrence 可能因为缩合原子等差异对应不同 SMILES；因此，occurrence 级冻结语言表示不被视为必然冗余。

对每个 `(pdb_id, object_key, language_family)`，清单从通过验证的 occurrence 表示中按固定种子选择一个，并保存候选 occurrence、模型实际使用的 SMILES、失败原因和最终选择证据。第一轮不做多表示 `logmeanexp`。后续可以修复 `object_key`，但不能在首轮清单构造过程中静默合并有差异的输入。

身份清单只包含同时具备配体图和当前语言表示的小分子身份。某个 SMI-TED Light 289M occurrence 缺失时，只移除这个表示候选，不排除整个 PDB；若同一身份仍有其它有效 occurrence，继续固定选择。真实小分子候选若没有当前语言模型的有效身份目标，仍参加六分类与区域辅助监督，但不参加身份损失或身份指标。

seen/unseen 必须按语言模型分别冻结：只有某个 `object_key` 在 train 中实际作为可监督小分子正目标出现过，validation 中对应身份才算 seen。

## 3. 候选编码器

### 3.1 `48³` RAUNet 与四种点模态

候选中心的三维 RAUNet 输入为 `(105,48,48,48)`：56 个 Find_0 密度通道与 49 个受体原子 hard-floor/sum 通道。第一版沿用 Stage1 RAUNet 的结构宽度、瓶颈注意力和回收结构，并产生：

- 候选级三维摘要，用于六分类和多模态融合；
- 配体区域与受体结合区域的逐体素二分类分数；
- 供 V、PP 读取的局部三维特征。

四种点模态的职责如下。

| 模态 | 当前实体 | 空间与调制边界 |
|---|---|---|
| A | 候选附近的受体原子 token | 保留 Stage1 `80³` 上下文；不接受 RAUNet 调制 |
| P | 代表受体局部结构的伪原子 token | 保留 Stage1 `80³` 上下文；不接受 RAUNet 调制 |
| V | Find_0 候选组件的点 token | 截断到中心 `48³`；读取对应位置的 RAUNet 增量 |
| PP | 从 Find_0 概率场采样的点 token | 只在中心 `48³` 采样；读取对应位置的 RAUNet 增量 |

A 与 P 原有的多组特征先分别通过显式输入投影融合。A、P、V、PP 在候选聚合前保留原始 token 轴，不预先压缩为少量 latent token。空模态必须通过掩码产生严格零贡献。

### 3.2 两种候选聚合

第一轮保留两种可直接比较的聚合方式。

- **弱聚合 `mean_max`**：分别对 A、P、V、PP 做带掩码的 mean/max pooling，再与三维候选摘要融合。完整 Matcher 的首轮正式对照统一采用该方式，以降低身份损失比较中的优化不确定性。
- **强聚合 `candidate_cross_attention`**：以三维候选摘要为 query，分别读取 A、P、V、PP 的未压缩 token，再融合四个候选条件增量。PP 分支的输出层权重和偏置必须初始化为严格零，使训练开始时 PP 的交叉注意力增量精确为零，同时保留首次反向传播的学习能力。

两种聚合先在候选六分类任务上独立从零训练。它们的结论与三种完整 Matcher 身份损失的结论暂时视为互补，不要求完整 Matcher 等待候选预训练完成。

## 4. 小分子身份编码与打分

对当前语言模型可用的第 $i$ 个小分子身份，构造三种表示。

1. **native**：冻结的 768 维 MoLFormer 或 SMI-TED Light 289M 表示经过可训练投影，作为稳定基线。
2. **graph**：native 表示查询自身未池化的配体原子图 token。配体图在查询前不能先池化成单个向量。
3. **inventory**：native 表示查询同一 PDB 中其它 native 身份，查询集合明确排除自身；清单只有一个身份时返回严格零。

候选表示分别与 native、graph、inventory 计算身份相容性。native 分支始终参与；graph 和 inventory 在完整分支出口使用从严格零开始的可学习门控。有效身份之外的分数由清单掩码隔离。

完整 Matcher 同时返回六分类分数、两个区域分数和当前 PDB 的小分子身份分数。非小分子候选可以经过身份前向以保持批量接口统一，但身份结果不形成监督。

### 4.1 BRANCHED 多残基图的暂定坐标处理

已核实的去重配体图中存在少量由两个 CCD 残基组成的 BRANCHED 图。不同 CCD 组件的 `ref_pos` 属于独立参考坐标系，跨残基原子距离没有物理意义。首轮训练前暂按以下规则处理，并在执行记录中保留原因和审计证据：

- `ref_pos` 按 `residue_id` 分别中心化；
- 同一残基内的化学键保留距离特征；
- 跨残基化学键保留拓扑与键型，但距离特征置零。

这是为了避免把无意义的参考坐标距离送入模型而作出的暂定边界，仍需用户复核；它不能被写成已验证的真实三维构象。

## 5. 损失函数

令候选 $c$ 的六分类交叉熵、配体区域损失和受体结合区域损失分别为 $L_{\mathrm{cls},c}$、$L_{\mathrm{lig},c}$ 和 $L_{\mathrm{bind},c}$。两个区域损失使用正负体素平衡的二元交叉熵与软 Dice。候选基础损失为

$$
L_{\mathrm{base},c}
=w_{\mathrm{cls}}L_{\mathrm{cls},c}
+w_{\mathrm{lig}}L_{\mathrm{lig},c}
+w_{\mathrm{bind}}L_{\mathrm{bind},c}.
$$

对 global batch $G$，令 $\mathcal E_G$ 是“真实类别为 `small_molecule` 且当前语言模型身份目标有效”的候选集合，$L_{\mathrm{id},c}$ 是身份交叉熵，$p_{\mathrm{small},c}$ 是六分类头预测小分子的概率。三种身份损失定义为

$$
L_{\mathrm{id},G}^{\mathrm{oracle}}
=\frac{1}{|\mathcal E_G|}
\sum_{c\in\mathcal E_G}L_{\mathrm{id},c},
$$

$$
L_{\mathrm{id},G}^{\mathrm{detached}}
=\frac{1}{|\mathcal E_G|}
\sum_{c\in\mathcal E_G}
\operatorname{stopgrad}(p_{\mathrm{small},c})L_{\mathrm{id},c},
$$

$$
L_{\mathrm{id},G}^{\mathrm{joint}}
=\frac{1}{|\mathcal E_G|}
\sum_{c\in\mathcal E_G}
p_{\mathrm{small},c}L_{\mathrm{id},c}.
$$

三种变体的分母都是同一个真实有效候选数 $|\mathcal E_G|$，不能改成概率权重和。`detached` 不把身份梯度传入六分类概率，`joint` 允许传入；非小分子和身份目标缺失的候选不受身份错误惩罚。$|\mathcal E_G|=0$ 时，身份项返回保留计算图的严格零。

global batch 总损失为基础损失的候选平均值加相应身份项：

$$
L_G=\frac{1}{|G|}\sum_{c\in G}L_{\mathrm{base},c}
+w_{\mathrm{id}}L_{\mathrm{id},G}.
$$

## 6. 训练、模型选择与评估

### 6.1 共同训练规则

- 候选在整个划分上确定性随机打乱，不按 PDB 排序或分组。不同硬件必须使用相同 global batch 32 的候选序列。
- A100 初始物理批量为 8、梯度累积为 4；A800 初始物理批量为 16、梯度累积为 2。
- 初始学习率为 `1e-4`。可以在后续单独运行学习率范围测试，但不能把未经记录的自动调参混入首轮对照。
- 每个 epoch 在完整 validation 上评估；指标严格改善才更新 `BEST.pt`，每轮更新 `LAST.pt`。连续两个 validation epoch 没有改善后结束。
- 不设置 Slurm 时限、程序墙钟上限或最大 epoch 数。首个完整训练若超过 16 小时，只取消后续随机种子，不中止当前训练。
- 初始使用原 Stage1 RAUNet 通道宽度。若真实前向因显存不足失败，先把 RAUNet 通道降到原宽度的四分之三；仍不足时再降低物理批量并增加梯度累积，始终保持 global batch 32。
- 数值检查采用 fail-fast：模型输出、损失、反向损失或裁剪前梯度出现 NaN/Inf 时立即失败，不保存新的最佳 checkpoint。

### 6.2 指标与模型选择

候选六分类至少报告 accuracy、macro-F1、逐类 precision/recall/F1 和混淆矩阵，并分别报告配体区域与受体结合区域的微平均 Dice。

完整 Matcher 额外报告三组身份结果：

1. **固有身份结果**：忽略六分类预测，只在真实有效小分子上报告身份 Top-1/Top-K，用于判断身份分支本身是否可学。
2. **条件身份结果**：只在六分类已正确判为小分子的真实有效候选上报告身份 Top-1/Top-K，并按当前语言模型拆分 seen/unseen。
3. **端到端身份结果**：同时要求六分类与身份正确，报告 precision、recall 和 F1。

候选六分类使用 validation macro-F1 选模。完整 Matcher 首轮暂以六分类 macro-F1、条件身份 Top-1 和端到端身份 F1 的等权平均选模；该权重是显式待复核参数，不是永久指标定义。calibration 不参与训练、早停或选模。

## 7. 首轮实验矩阵

首轮一次申请七张单卡资源，对应七个 Slurm 任务。候选六分类任务最先排队；其余六个完整 Matcher 任务不等待候选预训练结果，均从零开始，以便三种身份损失和两套冻结语言表示得到可比较的起点。

| Slurm 任务 | GPU | 顺序或语言表示 | 候选聚合 | 身份损失 | 初始化 |
|---|---|---|---|---|---|
| 候选六分类双阶段 | 1×A100 | 先弱聚合，再强聚合 | `mean_max` → `candidate_cross_attention` | 不适用 | 两阶段分别从零开始 |
| SMI-TED oracle | 1×A800 | SMI-TED Light 289M | `mean_max` | `oracle` | 完整模型从零开始 |
| SMI-TED detached | 1×A800 | SMI-TED Light 289M | `mean_max` | `detached` | 完整模型从零开始 |
| SMI-TED joint | 1×A800 | SMI-TED Light 289M | `mean_max` | `joint` | 完整模型从零开始 |
| MoLFormer oracle | 1×A100 | MoLFormer | `mean_max` | `oracle` | 完整模型从零开始 |
| MoLFormer detached | 1×A100 | MoLFormer | `mean_max` | `detached` | 完整模型从零开始 |
| MoLFormer joint | 1×A100 | MoLFormer | `mean_max` | `joint` | 完整模型从零开始 |

首轮把“候选聚合方式”和“身份损失/语言表示”视为互补证据。只有得到首轮结果后，才决定是否把最佳候选预训练权重加载到完整 Matcher、是否把强聚合用于完整 Matcher，以及是否追加随机种子或学习率搜索。

## 8. 资源、输出、锁和实验记录纪律

- 每个 GPU 任务初始申请 16 个 CPU 核；若集群 CPU 配额不足，可在不改变科学配置的前提下降低。QOS 和允许的分区只按“尽快合法提交并取得目标 GPU”选择，不作为实验变量。
- DataLoader 初始使用 16 个 worker，`prefetch_factor=2`。A100 每个 worker 的 LRU 缓存上限为 16 GiB，A800 每个 worker 为 32 GiB；这是单 worker 上限，按需增长，不是训练进程总预算，也不预分配全部内存。
- Matcher 的清单、缓存、checkpoint、指标和临时业务产物只能写入 `/storage/penghongen/tmp/Matcher/` 及其子目录。
- `/home/penghongen/Feedback/Matcher/` 下的 release、launch、Slurm 日志与锁，以及 `/home/penghongen/My_Project/Matcher` 下的正式源码不属于上述业务产物限制。
- W&B 规则从后续新 launch 开始生效；规则生效前已经运行的旧 release 保持原运行，不为补接 W&B 追溯重启。后续新 launch 默认使用 W&B online 模式，固定写入 entity `pencounkdual-111`、project `AdaLigand-Matcher` 和 group `matcher-initial-round1`。
- 每次由 32 个候选组成的 global batch 完成一次参数更新后，记录训练曲线；每个 epoch 记录完整 validation 指标及各指标的有效分母。W&B 在线握手或重试等待不构成训练时限，也不得派生 Slurm 时限、程序墙钟上限或 epoch 上限。
- W&B 在线初始化或上传失败时不得静默降级为 offline 模式。认证信息只能由运行环境注入，不得写入源码、配置、release、launch、日志或业务诊断产物。
- W&B 不改变服务器产物边界：所有在服务器落盘的业务诊断文件仍只能位于 `/storage/penghongen/tmp/Matcher/` 及其子目录。
- 七个 GPU 任务先用 `pre_lock` 排队。取得资源后，首个真实 global optimizer step 同时完成有限损失、有限梯度、参数更新和峰值显存验收；通过后继续正式训练，不让 GPU 在验收与训练之间空闲。
- 未经用户明确允许，不删除 `after_lock` 释放 allocation。任务失败时保留 allocation，先记录证据，再通过 `try_lock` 运行修订后的正式命令。
- 不设置 heartbeat。训练稳定后通常每 30 分钟检查一次；明确进入长时间无新事件的阶段时可改为每 1 小时检查。只有状态变化、异常、checkpoint、验证结果或其它有明确时间意义的事件才追加日志。
- 执行记录必须保存完整提交命令、配置快照、release/launch、Job ID、锁操作、关键标准输出、异常前因后果、临时决定、验证证据和结果位置。shell 脚本保持简洁、可读，不堆叠重复包装。
- 实现从指定基点建立普通 Git 分支，按数据、模型、训练测评和运行接线保存可回退提交。每个实验必须绑定源码提交、配置快照和 release；旧科学实现只保留在 Git 历史中。实现端点稳定后再按项目双线历史规则重建学习顺序并核对端点等价。
- 临时代码与正式包、正式脚本严格分开。阶段代码完成后分别进行科学正确性审查和代码规范/技术表达审查；审查 agent 不常驻。
- 用户可以随时中断或改变实验安排。若审查发现必须暂时调整已确认边界，为避免已取得的 GPU 空闲，可以先在执行记录中写清证据、风险和可逆决定，再继续最小可用运行，等待用户复核。

## 9. 首轮显式待复核参数

下列内容是可追溯的首轮起点，不等于已经证明最优。

| 参数或边界 | 首轮值 | 复核依据 |
|---|---|---|
| PP 采样上限 | 每个候选 `1024` 个局部 token | 显存、吞吐与验证指标 |
| 六分类类别权重 | 不加权 | 冻结清单类别分布和逐类召回 |
| 损失权重 | 六分类 `1.0`，配体区域 `0.10`，结合区域 `0.10`，身份 `1.0` | 各分量尺度、梯度和验证指标 |
| 完整 Matcher 选模 | 三项 validation 指标等权平均 | 指标相关性与端到端目标 |
| 学习率与权重衰减 | `1e-4`、`1e-4` | 首轮收敛曲线或独立学习率范围测试 |
| `object_key` 身份近似 | 每种语言模型固定选择一个有效 occurrence 表示 | 多 SMILES 身份比例和错误分析 |
| BRANCHED 坐标 | 按残基中心化，跨残基键距离置零 | 用户复核与多残基图消融 |
| 体素缓存精度 | `float16` | 抽样量化误差和训练数值稳定性 |

## 10. 完成判据

只有同时满足以下条件，首轮才算完成。

1. **清单可审计**：train、validation、calibration 的 PDB 互斥；候选类别、覆盖率、排除原因、每种语言表示的固定选择、缺失 occurrence 和 seen/unseen 均有冻结记录。
2. **数据边界可复现**：六分类使用完整全局候选监督；A/P 与 V/PP 的 `80³`/`48³` 空间边界、105 通道体素输入、候选全局洗牌和每 worker 缓存契约均通过测试与真实产物检查。
3. **模型与损失可验证**：空模态、PP 零增量、单身份 inventory 零输出、graph/inventory 零门控、非小分子无身份惩罚、三种 global-batch 身份分母和梯度传递差异均有回归测试。
4. **真实设备验收通过**：每种实际硬件配置至少完成一个有限的 global optimizer step，记录物理批量、梯度累积、有效身份数、梯度范数、峰值显存和耗时；OOM 时按既定降级顺序处理。
5. **七个任务形成可比较结果**：候选六分类任务的两个阶段和六个完整 Matcher 实验都保存配置、`BEST.pt`、`LAST.pt`、完整 validation 指标和停止原因；失败实验也保存可诊断证据，不以缺失结果冒充零分。
6. **结果分层完整**：六分类、固有身份、条件身份、端到端身份、seen/unseen 和区域指标均按本文定义计算，不使用匈牙利匹配，也不把缺失监督样本计入身份分母。
7. **实验结论可行动**：根据候选双阶段和六个完整 Matcher 的结果明确选择或淘汰候选聚合、语言表示和身份损失，并列出下一轮只需验证的最小实验集合。首个完整训练超过 16 小时时，不追加随机种子。
8. **文档与历史收口**：执行记录保存事实和命令，映射索引把本文连接到 Matcher 活动代码与执行证据；旧计划和旧结果继续标记为历史或已被取代，不被改写。
