# 实现并验证 AdaLigand Stage1 训练、推理与 Selector

本文是活 ExecPlan。执行期间必须持续维护 `Progress`、`Surprises & Discoveries`、`Decision Log` 与 `Outcomes & Retrospective`；任何暂停点都要让下一位没有聊天上下文的实现者仅凭当前工作树和本文继续执行。

本文实施并局部更新以下上游规格：

- `文档/规划文档/Stage1训练实现计划.md`：三个 producer 的 Dataset、模型、loss、训练配置、CPC 与 checkpoint 接缝。
- `文档/规划文档/Stage1训练与多阈值推理.md`：完整图概率、calibration、component forest、CLG、三类 centered、Selector 与精确反链 DP。
- `文档/讨论/BOX-level数据契约.md`：盘上目录、字段、shape、dtype、ragged 对齐与完成状态的唯一权威。
- `文档/规划文档/Stage1实现细节手册.md`：低权重的代码落点、测试和实施顺序，不改变前三份主规格。
- `Data_Preprocessing/Ori_Data/code/readme.md`：正在运行的 A–G 数据管线及整图资产契约。Stage1 只读消费其当前已完成产物，不修改 A–G 正式产物、状态或作业。

本文覆盖 Stage1 代码、配置、测试、服务器 smoke 和必要的一次性统计。正式全量训练、等待多日 checkpoint、正式全量完整图/centered 生产，以及 Stage2/Stage3 模型本体不在本轮执行范围。只有用户以后明确说“可以训练了”，才能提交正式训练脚本。

## Purpose / Big Picture

完成后，Pocket_Plus 的独立分支将能直接读取 AdaLigand A–G 的整图资产，用统一的 80³ Dataset/Collator 训练或 smoke `Find_0`、`Find_1`、`unet_c1`；三个模型都能用严格等价的 voxel-only 入口完成滑窗概率推理，再进行 32768 分母的 calibration、component forest/CLG 枚举、F1/CLG/Selected 三类居中推理。Selector 能从已经发布的部分 `CLG_centered` 冻结输入清单，训练 CCLN、运行精确反链 DP，并生成含完整字段语义的 score/selection 产物。

用户可以通过三类可观察结果判断实现成立：本地或服务器测试通过；一个真实 A–G PDB 能走通 producer smoke、完整图小规模 smoke 与 centered/Selector 数据冷读；所有产物都遵守固定目录、ragged schema 和 `_RUNNING/_COMPLETE/_BLOB_EXCEED` 状态约定。

## Progress

- [x] (2026-07-20 00:00+08:00) 完成新一轮 grill：四份 MD Human Review 覆盖账共 58 项全部得到去向，22 项正式决定写入 `grill_with_memory/07-19-22-17.md`。
- [x] (2026-07-20 00:00+08:00) 用户确认端到端实施方式、服务器限制和“不提交正式训练”的范围。
- [x] (2026-07-20 00:00+08:00) 读取 ExecPlan、计划治理、Pocket_Plus 与服务器交互、Python/YAML 写作规则；确认 AdaLigand 有未提交的用户工作，Pocket_Plus `大重构` 分支干净。
- [x] (2026-07-20 02:50+08:00) 局部修订四件套，消除已知的 10→8 Å、eligibility、阈值层、树命名、centered 分片、指标与 Selector 档位矛盾；完成关键词、schema offsets 与 `git diff --check` 审计。
- [x] (2026-07-20 02:42+08:00) 在 Pocket_Plus 从 `大重构@4d798c9` 创建 `codex/adaligand-stage1`，完成首轮只读依赖清点并冻结三个 agent 的互斥文件所有权；旧主线删除继续延后到新测试通过后。
- [x] (2026-07-20 03:58+08:00) 完成一次性 GT occurrence ligand-area 体素数全量统计：固定 Stage E 有效清单 22,309 个 PDB、673,364 个 occurrence，Q95=682，正式 `max_voxels=1023`；全目录 glob 超时与宽前缀 key 错误均保留为诊断证据。
- [x] (2026-07-20 06:20+08:00) 三个实现 agent 分别完成 producer-training、inference-lineage、selector 及各自单元测试；主 agent 随后统一处理跨包接缝。
- [x] (2026-07-20 07:05+08:00) 主 agent 完成跨包集成、整图 worker 缓存、三个代码旁 README 和旧主线清理；本地新链 85 tests passed，`compileall` 与 `git diff --check` 通过。完整模型测试因本地缺 `rootutils/lightning/torch_cluster` 转交服务器环境。
- [x] (2026-07-20 05:12+08:00) 在服务器现有 Pocket_Plus 完整环境完成 347 项 CPU 回归、真实 `10ad` Dataset smoke 和唯一单张 A100 的三 producer/centered/全图/Selector GPU smoke；未使用 H100/H200，也未启动正式训练。
- [x] (2026-07-20 09:10+08:00) 两个只读校验 agent 分别复核 producer/训练线与 artifact/Selector 线；主 agent 修复各向异性旋转、context 耗尽、零权重 NaN、零 CLG PDB、跨 CLG 重复节点、Selector I/O 局部性、Selected 失败特征占位和 centered 强校验，并新增 43 项相关本地回归通过。
- [x] (2026-07-20 06:18+08:00) 修复后服务器终验完成：CPU Job `320747` 为 363 passed、真实 `10ad` 三 producer Dataset smoke 通过；唯一 A100 Job `320748` 完成三 producer forward/backward、voxel-only 严格等价、完整图/centered 发布与 unet V5+D Selector 反传。
- [x] (2026-07-20 06:35+08:00) 完成四件套局部同步、代码旁 README、mapping、漂移/脚手架审计和 ExecPlan outcomes；本轮未提交正式训练或正式全量生产。
- [x] (2026-07-20 06:40+08:00) 最终全局命名审计把 Selector 内部残留的 `candidate_threshold_index` 统一为 `candidate_threshold_grid_index`；静态编译、diff 检查和 6 项 component-lineage 回归通过，提交为 `8e7eed0`。

## Surprises & Discoveries

- Observation: 本 ExecPlan 文件在本轮开始时存在但内容为空，不能承担恢复作用。
  Evidence: `Get-Content 文档/exec_plan/Stage1代码实现.md` 返回空内容。
- Observation: 当前四件套仍含上一轮重写遗留的显著矛盾，例如独立 eligibility、Dataset 10 Å 后再裁 8 Å、Find_0 无 embed、阈值分母 16384、IoU 最大匹配和 `CLG_cover_node` 等；这些均已被本轮明确决定替代。
  Evidence: 四件套当前正文与 `grill_with_memory/07-19-22-17.md` 问题 1、3、12、17、20 对照不一致。
- Observation: Pocket_Plus 模型真实消费 `box_shape_zyx` 与 `atom_coord_centered_world`，但当前训练计划字段表遗漏二者。
  Evidence: `../Pocket_Plus/src/model/stage1_model.py`、`stage1_embed_head.py` 与 `src/datasets/box_point_collate.py` 均直接读取这些键。
- Observation: 本地环境未被假定可运行完整深度学习测试；用户指定服务器 `AdaLigand_stage1_py310` 可与现有 Pocket_Plus 运行环境配合。
  Evidence: 用户于 2026-07-20 明确给出该测试环境与 GPU 限制。
- Observation: centered 的旧 `index.npz+part_*.npz` 不仅增加文件和索引层，也与用户确认的“每 PDB/role 一个聚合 NPZ”冲突；role 完成状态因此需要与 payload 文件解耦。
  Evidence: 修订后的 `文档/讨论/BOX-level数据契约.md` 固定 `centered/*.npz` 与 `status/{output_role}/_COMPLETE`，并逐项定义 ragged offsets。
- Observation: Selector 正文同时规定 `L_blob` 对正、负 CLG 全部训练，又把包含 `L_blob` 的 `L_cond` 整体乘以 `y_G/p_G`，两者在负 CLG 上矛盾。
  Evidence: `文档/规划文档/Stage1训练与多阈值推理.md` 原第 8.4 节的文字定义与紧随其后的三式不能同时成立；实现 agent 在编码前主动报告。
- Observation: MD Human Review 覆盖账已决定 overlap 使用指向 `occurrence_id` 表的局部 index，但冻结正文仍残留 `overlap_occurrence_id`，首轮实现也据此保存了 identity。
  Evidence: `.review/AI_GRILL___fd6ce8_BOX-level数据契约_1784469355496_aicmd.md` 第 10 项与当时的契约第 5.3 节不一致；在实现尚未冻结时已通知 inference/selector 两线统一纠正。
- Observation: 直接 glob 全部 `density/*/ligand_area.npz` 的 Q95 首轮作业几乎不消耗 CPU，却在共享存储读取上阻塞，40 分钟时限内未完成首批、也未落下统计摘要。
  Evidence: Job `320671` 终态 `TIMEOUT`，elapsed `00:40:29`，batch exit `0:15`；运行期 `AveCPU` 仅约 7 秒而 `AveDiskRead` 已约 10 GB。
- Observation: centered 的库级 callback 已存在，但真正端到端还要求 producer 暴露真实 V 多尺度与 Find A/P L1–L4 具名出口；仅用任意 mapping callback 会掩盖这一模型接缝。
  Evidence: inference agent 在跨包审计时发现 `unet_c1` 当前 voxel return keys 为空，Find 完整 forward 也尚无直接具名 A/P adapter，已要求 producer 线以最小改动补齐并做 shape/来源测试。
- Observation: `ligand_area.npz` 除 `mask_{candidate_id}` 外还含以 `mask_` 开头的元数据 key；用宽泛 `startswith("mask_")` 会把标量元数据误当稀疏 `(K,3)` 数组。
  Evidence: Job `320704` 在 512 个定点 PDB 上均以 `IndexError: tuple index out of range` 返回；修正版改为仅接受 `key[5:].isdigit()`，Job `320706` 重新运行。
- Observation: 同一 PDB 的多个训练或滑窗请求如果每次重新 `np.load`，会反复解压完整 exp/sim/union grid，实际 I/O 和 CPU 放大远高于请求数本身。
  Evidence: 集成审查发现首版 `Stage1Dataset` 的 source loader 没有跨请求复用；现已加入每 worker、按估算字节上限淘汰的统一缓存，并用重复窗口测试验证每种整图源只打开一次。
- Observation: Stage G 最终 `keep_list.jsonl` 在本轮服务器探测时尚未发布，因此不能假装完成正式 split/BOX pool 冻结。
  Evidence: 只读探测确认 keep-list 路径不存在；真实 smoke 改用明确的已完成 Stage E PDB `10ad`，其 exp/sim/ligand-area/receptor/labels 全部存在，shape 为 274³、受体表为 27,916×49、含 16 个 occurrence。
- Observation: `AdaLigand_stage1_py310` 的嵌套激活探测会因缺少 `x86_64-conda-linux-gnu-g++` 失败；Pocket_Plus 的 `Pocket_Plus_centos7_cu121_allgpu` 已同时具备本轮所需的 PyTorch、Hydra、Lightning、rootutils 与 torch_cluster，因此测试不需要修改任何正式环境。
  Evidence: CPU Job `320737` 在测试前的多余环境探测处退出；删去该探测后，Job `320738` 实际进入全套测试。该失败只保留为环境诊断，不计作代码失败。
- Observation: Find_1 最短 voxel 入口若先裁 core 再执行 `input_proj`，数学上等价但 GPU GEMM 的矩阵形状变化会产生约 `1.19e-7` 的舍入差，不能满足已经冻结的逐元素一致契约。
  Evidence: CPU Job `320738` 仅 24 个元素不同；改为与完整 forward 相同的“先投影 core+8 Å 全表，再取 core”后，CPU 回归与 GPU BF16 三次 recycle 均得到 `max_abs_diff=0.0`。
- Observation: PyTorch BF16 tensor 不能直接调用 `.numpy()`；居中适配器必须在 CPU 桥接处先提升为 float32，再由正式 artifact 打包层压为契约规定的 float16。
  Evidence: GPU Job `320743` 在 `adapt_stage1_centered_output` 首次转换 `voxel_final` 时触发 `TypeError: Got unsupported ScalarType BFloat16`；加入专门回归后 Job `320745` 全链通过。
- Observation: 首轮同步旋转只旋转数组与坐标，却以近似各向同性检查代替轴尺度置换；A–G voxel size 可以略有轴差，这会破坏旋转后 local-voxel/world 对应关系。
  Evidence: producer 校验逐式对照 `_apply_synced_rotation` 后发现问题；修复为奇数 quarter-turn 同步置换 `voxel_size_world`，并以 `[1,2,3]` Å 人工例验证监督 voxel、原子 local/world/centered 坐标逐项一致。
- Observation: context 生成器允许尝试耗尽后得到少于三个合法起点，但首轮 pool/request 代码会因此终止整个 PDB。
  Evidence: producer 校验对照生成器返回契约与 `build_pdb_box_pool` 的硬错误发现矛盾；修复后 1–2 项有放回选满名义三项，零项仅省略 context，并分别有回归测试。
- Observation: 同一 forest node 可以合法进入多个 CLG；首轮 Selector 把跨 CLG 重复选择当作坏数据，会使校正或 Selected 生产在合法输入上失败。
  Evidence: artifact/Selector 校验构造重叠 CLG 后命中重复检查；现统一为下游有序并集，校正中同一 node 只计一次且有效 gate 取相关 CLG 的最大 `p_G`。
- Observation: 逐 CLG 冻结清单无法表达“完整发布但零 CLG”的 PDB，导致正式 validation 完整性、空 scores 和 calibration GT false negative 静默缺失。
  Evidence: artifact/Selector 校验追踪 `input_CLG_list.json → scores → calibration` 后确认 PDB 会消失；现增加固定 `pdb_ids_by_split/split_pdb_counts` inventory，并用零 CLG 回归覆盖正式完整性、空 scores 和指标路径。
- Observation: Selected 的非成功 entry 若保存四张全零固定 V grid，会把状态记录伪装成真实模型特征；同时首轮 centered validator 对多个必需字段只做可选检查。
  Evidence: artifact 校验删除关键字段和构造 mixed-status Selected 后仍能通过；现由 `feature_entry_index` 只映射 success 行，失败 ragged 段为空，validator 强制概率、V/aux、固定网格和 producer 模态契约。
- Observation: Selector 全局 CLG shuffle 配合每 worker 仅一 PDB cache，会反复解压大型聚合 NPZ，训练吞吐可能由 I/O 而非模型决定。
  Evidence: Selector 校验按 DataLoader 访问顺序审计发现相邻 CLG 大量跨 PDB；现使用确定性 PDB-grouped batch sampler，单 batch 不跨 PDB，仍在 epoch 间打乱 PDB 与 PDB 内 CLG。
- Observation: 本地 Windows 环境在 Selector Dataset 的 `np.linalg.eigvalsh` 处会由 NumPy/MKL 原生中止，设置单线程仍不能规避；它不是 Python 断言失败。
  Evidence: 最终聚合复测在同一行两次 `Fatal Python error: Aborted`；相同 Dataset 路径此前已在服务器 CPU Job `320747` 的 363 项回归中通过。最后一笔仅重命名局部变量，另由 `py_compile`、`git diff --check` 与 6 项不触发该本地原生问题的 component-lineage 测试覆盖。

## Decision Log

- Decision: 四件套采用局部、可审计修订，不整篇替换；公式和关键科学定义保留在主计划，测试与 AI 顺序才放低权重手册。
  Rationale: 用户明确认为现有结构大体可用，目标是修复契约和遗漏，而不是再次制造重写回归。
  Date/Author: 2026-07-20，用户与 Codex。
- Decision: 冻结文档后使用三个实现 agent，分别独占 producer-training、inference-lineage、selector；共享配置、Git、跨包 glue 和删除由主 agent 处理。
  Rationale: 三条代码线职责自然分离，三 agent 是当前四并发槽位下既能提速又能控制共享工作树冲突的最大必要数量。
  Date/Author: 2026-07-20，用户确认 Codex 建议。
- Decision: 实现完成后使用两个只读校验 agent；主 agent 同时做第三路集成验证。
  Rationale: 训练/模型与 artifact/结构化算法的风险面不同，需要独立复核，且校验阶段不允许并发修改。
  Date/Author: 2026-07-20，用户确认 Codex 建议。
- Decision: 本轮不提交正式训练；只做真实 smoke。服务器测试最多申请一张 A100 或 A800，禁止 H100/H200。
  Rationale: 用户保留正式训练提交时机，并为本轮测试设定明确资源上限。
  Date/Author: 2026-07-20，用户。
- Decision: 服务器除本作业自己的四类锁外，只允许写 `/home/penghongen/My_Project/AdaLigand/tmp/`；现有 Pocket_Plus、AdaLigand 正式目录、A–G 作业及其它作业只读。
  Rationale: 防止测试污染正在运行的数据处理和既有项目环境。
  Date/Author: 2026-07-20，用户。
- Decision: Stage2/Stage3 本体不在本轮实现；本轮只完成它们未来消费所需的 Stage1 artifact 与 `residual_swiglu` 输入接口。
  Rationale: 四件套已冻结 Stage1 生产/选择，但未充分冻结 Stage2/3 模型本体。
  Date/Author: 2026-07-20，用户确认的实施边界。
- Decision: per-PDB 正式 payload 与完成标志解耦：五个 role 的完成标志统一位于 `status/{output_role}/_COMPLETE`，PDB 根只承担 `_RUNNING` 互斥锁和可选 `_BLOB_EXCEED` 终态。
  Rationale: centered 目录可以严格只含三个聚合 NPZ，同时 probability/components/centered 仍共享一个明确、可扫描的 role 状态约定。
  Date/Author: 2026-07-20，Codex 按用户已确认的 role 独立完成语义落地。
- Decision: `L_blob` 始终对正、负 CLG 训练；oracle/detached/joint 的条件权重只作用于正 CLG 的 `L_antichain`。
  Rationale: 这是此前决定中更具体、可直接检验的监督语义；若把整个 `L_cond` 加权，oracle 方案会静默丢掉全部负 CLG 的候选质量监督。
  Date/Author: 2026-07-20，Codex 消解冻结正文内部矛盾。
- Decision: 新链通过 85 项本地测试后，从目标分支删除 `src/legacy`、旧 `src/inference` 生产/评估/可视化编排、`configs/infer_or_eval` 及其八个专属测试；保留仍被制图代码调用的 `src/inference/utils/receptor_strip.py`，并保留全部通用 model/wrapper、CPC、sparse-refine、ranking 能力与实验配置。
  Rationale: 这是用户要求的“用 Git 备份而让当前项目工作树保持干净”，同时避免把未实例化能力误删成模型重构。
  Date/Author: 2026-07-20，用户授权，Codex 在回归证据后执行。
- Decision: 首次 A800 smoke Job `320742` 尚处于 `PENDING/Priority` 且前方已有五个单卡任务时，精确取消该未启动作业，确认终态后改投单张 A100。
  Rationale: 用户允许按实际排队选择 A100/A800；A100 容量更大，切换期间任一时刻至多只有一个本轮 GPU 请求。
  Date/Author: 2026-07-20，Codex 按服务器资源约束执行。
- Decision: `input_CLG_list.json` 同时冻结 PDB inventory 和非空 CLG items；零 CLG PDB 不产生训练样本，但必须产生空 score/selection 并进入校正指标。
  Rationale: “没有候选”是模型/组件链的有效负结果，不等价于 PDB 未完成或可从分母删除。
  Date/Author: 2026-07-20，Codex 根据独立校验修复契约闭包。
- Decision: 同一 forest node 跨 CLG 被重复选中时，不修改各 CLG 的 selection；消费端按首次来源顺序有序去重，校正端以最大 `p_G` 作为该唯一预测的 gate。
  Rationale: CLG 是局部竞争组而不是 node 的全局唯一归属；保留逐 CLG 解码证据，同时避免 Selected 重跑和 instance 计数重复。
  Date/Author: 2026-07-20，Codex 根据独立校验统一实现与四件套。
- Decision: Selected 非成功 entry 不保存全零固定特征；以 `feature_entry_index` 映射仅 success 的 V grids，ragged offsets 仍覆盖全部 entry。
  Rationale: 一对零状态必须与真实模型特征可机械区分，同时保留一个 PDB/role 单 NPZ 和无 object array 的契约。
  Date/Author: 2026-07-20，Codex 根据独立校验补全存储语义。

## Outcomes & Retrospective

本轮目标已经在代码与可观察验证层完成。Pocket_Plus 的 `codex/adaligand-stage1` 分支从 `4d798c9` 建立，五个提交实现了统一 Stage1 Dataset/Collator、五套 producer 配置、CPC 接缝、严格 voxel-only 推理、完整图概率与阈值、component forest/CLG、三类 centered artifact、CCLN/V5+D Selector、精确反链 DP、score/selection 及可续跑状态机。旧混合推理/评估/可视化主线仅在该分支 Git 可恢复地删除；通用 model/wrapper、CPC、sparse-refine、ranking 能力继续存在。

验收证据分三层：本地边界回归和静态检查通过；服务器完整 CPU suite 为 363 passed；真实 `10ad` 在一张 A100 上完成三 producer 有限 loss/非零梯度、voxel-only `max_abs_diff=0.0`、完整图原子发布、centered V/P/A 出口与 unet V5+D Selector 反传。一次性全量统计覆盖 22,309 个有效 PDB、673,364 个 occurrence，得到 Q95=682，因此正式 `max_voxels=1023`。这些结果证明代码已具备正式训练前 smoke 水平，但不等价于已有训练 checkpoint 或全量 Stage1 artifact。

两个独立校验暴露的主要价值在边界闭包，而非主算法返工：零 CLG PDB 必须保留在 inventory/指标中；同一 forest node 跨 CLG 重复是合法关系；Selected 失败状态不能伪造零特征；近似 1 Å 不意味着增强可以忽略轴尺度。这些规则已同时进入测试、代码旁 README 与四件套，避免再次只修实现而让冷读文档漂移。

本轮脚手架收口如下：

- **长生命周期生产代码**：`src/datasets/stage1_*`、`src/inference/` 新链、`src/evaluation/`、`src/component_lineage/`、`src/artifacts/`、`src/selector/`、AdaLigand 配置与三份代码旁 README；它们是默认生产/训练接口并由完整 suite 覆盖。
- **可复用运维工具**：仓库现有通用 sbatch core/模板继续保留；两个 A800 双卡模板中会实际调用已删除旧入口的专属 hook 已移除，恢复为通用训练模板。`src/inference/utils/receptor_strip.py` 因现有制图代码仍有真实 import 而保留，但不属于 Stage1 默认入口。
- **run-specific scaffolding**：Q95、CPU/GPU smoke 脚本、源码快照、日志和产物只位于 `/home/penghongen/My_Project/AdaLigand/tmp/stage1_*`；其 scope 是本轮统计/验证，完成标志与 Job 终态已冻结，不是正式生产入口。按用户写入边界保留为证据，不移动进活跃仓库，也不主动删除。

明确未完成项是外部/后续工作：Stage G 最终 keep-list 尚未发布，故正式 split/BOX pool/validation selection 未冻结；三个 producer 没有获准开始正式训练；calibration 100、validation/train 全量 probability/F1/CLG、真实 Selector 训练和 Selected 全量生产均未运行；正式 batch size 仍需在训练硬件上 preflight 后冻结；held-out 去冗余、严格 test、Stage2/Stage3 本体和磁盘总量实测仍待后续计划或授权。

## Context and Orientation

AdaLigand 仓库位于当前工作树；Pocket_Plus 是相邻仓库 `../Pocket_Plus`。代码在 Pocket_Plus 实现，规格、执行日志、mapping 与 A–G 契约在 AdaLigand 维护。Pocket_Plus 当前干净分支为 `大重构`，冻结起点为 commit `4d798c9`；目标分支固定为 `codex/adaligand-stage1`。

三个 producer 是 `Find_0`、`Find_1` 与 `unet_c1`。Find 两阶段训练称 CPC1/CPC2；CPC2 只从同名 Find 的 CPC1 BEST 做 model-only 初始化。`probability_map` 是第一次完整图滑窗融合得到的 ligand-area 概率。component forest 是多个阈值的 26-连通组件按包含关系组成的树森林。CLG（Candidate Lineage Group）是一组存在谱系竞争关系的候选节点。Selector 对 CLG 做门控，并在树祖先冲突下选择非空反链。F1/CLG/Selected 是三种 centered artifact 角色，不是普通局部变量名。

服务器是 `penghongen@10.102.33.220:10022`。所有测试代码副本、日志和结果必须位于 `/home/penghongen/My_Project/AdaLigand/tmp/`。远端正式 A–G 资产可只读消费；不得修改其状态、release、锁或作业。重型测试必须通过本项目 `与服务器交互/sbatch` 模板适配后提交，最多单张 A100/A800。轻量 SSH helper 只做探测和小文件编排，不直接跑模型。

## Plan of Work

第一个里程碑是规格冻结。主 agent 逐节修订四件套，把 grill 的 22 项决定落到原有章节；保留仍正确的段落和公式。随后运行术语首见、schema 语义、offset 切分、字段命名和跨文档关键词检查。mapping 从“未开工”改为“实施中”，并链接本文。

第二个里程碑是分支与接口冻结。主 agent 在 Pocket_Plus 创建目标分支，只读追踪 `src/model`、`src/wrappers`、`src/train.py`、Hydra 配置与测试的依赖。删除动作延后到新实现与回归证据齐备后。主 agent给三个实现 agent 分配互斥路径，并规定任何共享文件只提交建议、由主 agent落盘。

第三个里程碑由三个 agent 并行完成。producer-training 负责 AdaLigand Dataset/Collator、producer 配置、loss/CPC 和最小 voxel-only 入口。inference-lineage 负责 artifact 状态/IO、完整图、calibration/evaluation、component forest/CLG 和 centered runner。selector 负责 Selector Dataset、V5+D、DensityMUNetLite、CCLN、oracle、精确反链 DP、训练与 score/selection。每个 agent 必须带测试交付，不得仅写接口桩。

第四个里程碑是主 agent 集成。主 agent核对全部共享字段和调用链，补跨包测试与代码旁契约 README；在依赖审计后删除已经被替换的旧 Dataset/inference/legacy 主线，同时保留 `src/model`、`src/wrappers`、CPC、sparse-refine、ranking 等通用能力。所有删除只发生在 Git 分支内。

第五个里程碑是验证。先运行本地能够运行的静态、纯 NumPy 和轻量 PyTorch 测试；再把测试副本安全上传到服务器授权 tmp，运行 CPU suite 和最多单卡 GPU smoke。GPU 优先根据排队情况选择 A100 或 A800，绝不提交 H100/H200。smoke 使用 A–G 当前已经完成且通过上游契约的真实小样本，不等待整个 A–G 全量结束，也不写正式训练或正式 Stage1 输出根。

第六个里程碑是独立复核与收口。两个验证 agent只读检查代码、配置、测试和文档；主 agent处理问题并重跑验证。最终更新 ExecPlan、mapping 和代码旁 README，列出任何真正未完成的外部依赖。不得要求用户发送 `Continue` 才恢复内部工作。

## Concrete Steps

所有本地文档命令在 AdaLigand 根执行，代码命令在 `../Pocket_Plus` 执行。预期的关键动作是：

    git -C ../Pocket_Plus switch -c codex/adaligand-stage1 4d798c9
    python -m pytest <新增的纯 CPU/轻量测试集合>
    python -m pytest <producer 与 selector 集成测试集合>

Hydra 配置必须实际 compose，不能只读取 YAML 文本。服务器 smoke 的确切 sbatch 脚本、Job ID、分区、环境、命令和结果将在执行时回填本文；脚本必须把 stdout/stderr、测试副本和所有产物定向到：

    /home/penghongen/My_Project/AdaLigand/tmp/stage1_<run_id>/

提交前先只读查看 A100/A800 队列，再选择一个单卡模板；任何时刻本轮测试最多持有一张 GPU。自己的 `pre_lock/try_lock/after_lock/kill_lock` 必须能由 Job ID 精确归属，不能枚举或操作其它 Job 的锁。

## Validation and Acceptance

文档验收要求四件套中不存在已知旧名或旧语义，所有 schema 字段都有 shape、dtype、对齐对象和解释；主计划中的公式不依赖低权重手册才能理解。

producer 验收要求三个模型配置 compose；真实或严格构造 batch 能 forward/backward；Find_0/Find_1 输入差异、unet 单通道、hardmask loss/推理语义、CPC1→CPC2 hook 均被测试。`forward_voxel_probability` 在 eval、固定三次 recycle 下与完整 forward 的 ligand voxel logits 逐元素一致，并证明 point/P/A/sparse 分支未调用。

推理验收要求 80³/stride40/Gaussian 融合覆盖完整图；32769-bin histogram 正确选择七个 alpha 的扫描整数；旧 coverage/Hungarian/top-K 定义与 macro AP 被穷举小例验证；forest 是合法树，CLG 使用对象树与 `D(g)`，重复阈值不制造层。

artifact 验收要求每 PDB/role 原子发布；PDB `_RUNNING` 与 role `_COMPLETE/_BLOB_EXCEED` 的续跑测试通过；三个 centered NPZ 的 ragged offsets、V/P/A、A_feat_L0–L4/P_feat_L2–L4、score/selection 字段能被冷读检查器恢复。

Selector 验收要求 DensityMUNetLite、`residual_swiglu`、V5+D、CCLN attention bias、内容/树表示分离、online oracle 与精确 DP 有数值测试。小树枚举必须逐值验证 partition、预测 MAP、GT oracle、梯度和 gate 失败空集。

服务器验收至少包含：CPU 测试成功；一个真实 A–G 样本完成 Dataset→三个 producer smoke；若单卡排队可接受，再完成一张 A100/A800 上的 forward/backward、voxel-only equivalence 与最小完整图/centered/Selector smoke。没有正式训练提交。

## Idempotence and Recovery

所有正式代码修改由 Git 记录。主 agent在每个里程碑前检查工作树，不覆盖用户原有改动；Pocket_Plus 删除只在目标分支发生。三个实现 agent使用互斥目录，完成后停止写入；若需修复，主 agent定向重新唤醒原 agent，避免新 agent重复实现。

服务器测试使用唯一 run_id 的 tmp 子目录，可重复提交新的 run_id，不覆盖历史结果。失败 job 只操作自己的四类锁。不得删除服务器正式项目、A–G 产物或其它作业文件；测试结束后也不主动清理 tmp，除非用户另行授权。

## Artifacts and Notes

本节随执行记录关键证据：Pocket_Plus 分支/commit、测试命令与摘要、服务器 Job ID、Q95 统计、真实 smoke PDB、产物路径及失败诊断。只保存能够证明验收的短摘要，不复制大段日志。

- Pocket_Plus 工作分支：`codex/adaligand-stage1`，基点 `4d798c9`。
- Q95 首轮：CPU Job `320671`，8 CPU，`cpu/Cpu96`；唯一写入目录 `/home/penghongen/My_Project/AdaLigand/tmp/stage1_q95_20260720_025707/`，输入 `/storage/penghongen/AdaLigand/Ori_Data/density` 只读；因共享存储 I/O 于 `00:40:29` 超时，无有效摘要。
- Q95 增量抽样：CPU Job `320704`，4 CPU，`cpu/Cpu96`；从固定 Stage E status JSONL 等距选择至多 512 个完成/复用 PDB，定点读取而不扫描 density 目录，并每 5 个结果原子更新 `/home/penghongen/My_Project/AdaLigand/tmp/stage1_q95_incremental_20260720_034100/summary.json`。
- Q95 增量抽样修正：Job `320704` 因把 `mask_candidate_ids` 一类元数据错误计作 occurrence 而得到 512 个无效错误；Job `320706` 使用严格 `mask_{整数}` key，写入 `/home/penghongen/My_Project/AdaLigand/tmp/stage1_q95_incremental_v2_20260720_034700/`。
- Q95 全量：Job `320711` 直接读取固定 Stage E 状态清单中的 22,309 个有效 PDB，不扫描 density 目录；673,364 个 occurrence 全部成功、0 错误，`Q95=682`、median `91`、min `8`、max `9093`，因此正式 `max_voxels=ceil(682×1.5)=1023`。摘要位于 `/home/penghongen/My_Project/AdaLigand/tmp/stage1_q95_full_status_20260720_035000/summary.json`。
- Pocket_Plus 实现提交：`81aad97`（Stage1 主实现与首轮旧主线 Git 可恢复清理）、`2eb6ab9`（Find_1 voxel-only 严格等价）、`cf8ff70`（BF16→NumPy 居中桥接）、`859bdd6`（独立校验边界修复、旧总管线/文档收口与专门回归）、`8e7eed0`（阈值网格字段内部命名全局统一）。
- 服务器 smoke 唯一根目录：`/home/penghongen/My_Project/AdaLigand/tmp/stage1_smoke_20260720_0715_81aad97/`。所有源码快照、脚本、stdout/stderr、summary 与 smoke artifact 均位于该目录；正式项目和 A—G 资产只读。
- CPU Job `320738` 暴露 1 个数值等价实现问题与 3 个测试断言问题；修复后 Job `320741` 为 346 passed。BF16 修复后的最终 CPU Job `320744` 为 347 passed、17 warnings，并再次通过真实 `10ad` Dataset smoke。
- GPU：A800 Job `320742` 未启动即因队列切换被精确取消；A100 Job `320743` 暴露 BF16 NumPy 桥接问题；最终 A100 Job `320745` 在 31 秒内完成。三个 producer 的 loss 有限、均有非零梯度、voxel-only `max_abs_diff=0.0`，centered 字段与 48×80³ final feature 成功恢复，单窗口完整图原子发布成功；真实 unet V5+D Selector loss 有限且 213 个梯度 tensor 非零。峰值显存约 Find_0 9.64 GiB、Find_1 9.75 GiB、unet_c1 7.19 GiB；这些只表示 batch=1 smoke，不冻结正式 batch size。
- 独立校验修复后的唯一终验根：`/home/penghongen/My_Project/AdaLigand/tmp/stage1_validator_20260720_0605_859bdd6/`，源码归档 SHA-256 为 `a79baf0a5402883de669bd89ca71c2fcab6a81bd5a24f578f4ee90e6faaa6741`。CPU Job `320747` 为 363 passed、17 warnings，并再次通过真实 `10ad` 三 producer Dataset smoke；A100 Job `320748` 为 `COMPLETED 0:0`、32 秒，三个 producer loss/梯度有限、voxel-only `max_abs_diff=0.0`，完整图/centered 正常，unet V5+D Selector loss `1.3529694` 且 213 个梯度 tensor 非零。未申请 H100/H200，未启动正式训练。

## Interfaces and Dependencies

最终代码至少提供以下稳定接口；精确字段由四件套 schema 约束：

    Stage1Dataset / Stage1BatchCollator
    Stage1 model.forward_voxel_probability(batch) -> voxel_logits_ligand
    load_stage1_wrapper(checkpoint_path, resolved_config_path)
    produce_full_map(...)
    calibrate_thresholds(...)
    ComponentForest / ComponentTree / ComponentNode / CLG / WorkingTree
    produce_F1_centered(...) / produce_CLG_centered(...)
    SelectorDataset / SelectorWrapper / selector train/inference entry
    exact_antichain_log_partition(...) / exact_antichain_map(...)

首版使用现有 Pocket_Plus/PyTorch/Lightning/Hydra/NumPy/SciPy 能力，不新增大型第三方框架。连通组件与 Hungarian 优先复用现有依赖的稳定实现。NPZ 使用 `np.savez_compressed`，禁止 object array/pickle；学习特征 float16，概率/几何 float32。

## Plan Drift / Reconciliation

### Beneficial drift

- `Stage1Dataset` 增加每 worker 的统一受控整图缓存。这不改变字段或数值语义，却避免训练/滑窗时对同一 PDB 重复解压完整 grid；属于为真实数据规模补上的必要性能保障。
- 推理包增加 `assembly.py` 与 `cli.py` 两个很薄的装配层；科学实现仍分离在 checkpoint/probability/full_map/centered/runner 中，但无上下文使用者得到一个可执行、可测试的六阶段入口。
- Selector 增加 PDB-grouped batch sampler；这不改变冻结样本集合或优化目标，只把同一 PDB 的 CLG 聚在相邻 batch，避免小缓存下重复解压大型 NPZ。
- `input_CLG_list.json` 增加 PDB inventory，Selected 增加 `feature_entry_index`。两者都是为表示原规格已允许的零 CLG/一对零状态补齐最小磁盘信息，而不是新增科学分支。

### Neutral drift

- 细节手册示意 `src/inference/` 约五个模块，实际为七个实现模块加 README。新增两文件只承载 runtime 装配与参数解析，没有把契约、科学算法、保存和评估重新混入同一大文件。

### Harmful drift

首轮实现曾有四类有害漂移：各向异性旋转未置换 voxel size、context 少于 3 会终止、跨 CLG 重复 node/零 CLG PDB 被错误拒绝或丢失、Selected 失败 entry 伪造固定 V grid。这些均由两位只读校验者在最终提交前发现，已修复并纳入 363 项全套回归；当前没有已知未修复的有害漂移。

### Unfinished scope

正式 split/BOX pool 依赖 Stage G keep-list；正式训练、正式全量推理、真实 Selector 方案比较、严格 held-out test 与 Stage2/Stage3 本体明确留待后续用户授权/计划。当前 smoke 的 batch=1 显存不能冒充正式 batch-size 决定。

---

2026-07-20：初始化本文。原因是用户批准以指定文件作为本轮外部记忆，并要求端到端实施、服务器 smoke、无需用户输入 `Continue`；同时明确取消本轮正式训练提交。
