# AdaLigand Stage1 实现细节手册

> **低权重定位**：本文是本轮 Stage1 三件套的特例性实现附录，只提供代码锚点、推荐落点、伪代码、测试用例和 AI 工作顺序。它不是新的项目文档范式，不拥有科学定义、公式、字段或配置值。
>
> **优先级**：`Stage1训练实现计划.md`、`Stage1训练与多阈值推理.md`、`BOX-level数据契约.md` 高于本文。本文的工作顺序不能改变三份主文档的内容或验收标准；若代码现实与主文档冲突，先报告漂移，不用本文替主文档做决定。
>
> **适用仓库**：AdaLigand 保存上游资产、冻结清单和治理文档；Pocket_Plus 保存模型侧 Dataset、训练、推理与 selector 代码。服务器正式项目路径遵守 Pocket Plus 项目工作流，不在本文复制设备相关本地绝对路径。

---

## 1. 现有 Pocket_Plus 锚点

开始实现前先读以下现有文件；复用其成熟行为，不复用旧数据契约或旧推理编排：

| 现有位置 | 可复用内容 | 不应直接继承的内容 |
|---|---|---|
| `src/datasets/density_channel_builder.py` | 56D `ALL` 展开、diff/posdiff、clipnorm、smooth | 旧 Dataset 的文件布局与 target 来源 |
| `src/datasets/box_geometry.py` | BOX/世界坐标 helper | 旧越界 padding 语义 |
| `src/datasets/box_sample_builder.py` | receptor 几何查询和局部坐标构造 | 旧样本身份、旧预切 BOX 假设 |
| `src/datasets/box_point_collate.py` | 变长 atom 拼接和 batch index | 强制存在旧 target 的分支 |
| `src/model/stage1_embed_head.py` | MLP、relative/centroid、residual、soft scatter | Find_1 中的 Transformer blocks |
| `src/model/stage1_model.py` | voxel input、recycle、point/A/P 执行链 | 旧完整图推理入口 |
| `src/model/stage1_voxel_backbone.py` | RAUNet64、ligand/aux heads、中间 V 出口 | 旧输出头额外 3×3 block 数 |
| `src/wrappers/voxel_point_stage1.py` | 训练生命周期、BEST monitor、checkpoint hook | 对 `ligand_dist_map` 的旧依赖 |
| `src/wrappers/voxel_point_stage1_losses.py` | 各分支 loss 装配 | 旧 distance-target 生成 |
| `src/train.py::_load_model_only_checkpoint` | CPC model-only 严格加载 | 未调用 `on_load_checkpoint` 的缺口 |
| `configs/experiment/CPC1/*`、`CPC2/*` | Hydra 继承结构、stage freeze 示例 | 旧数据、旧 loss、旧 batch/调度值 |
| `configs/experiment/unet_c1.yaml` | 关闭 point/A/P 的结构示例 | 旧 ligand head block 数、旧 auxiliary 关闭方式 |

实现者应先对这些锚点做一次只读调用图，确认当前分支是否已经移动模块；路径变化只更新本文，不改变主契约。

---

## 2. 推荐代码布局

不新建 `src/adaligand` 或 `configs/adaligand`，也不保留旧推理主线的兼容入口。按稳定职责放入 Pocket_Plus 现有顶层目录；每个目录控制在少量可冷读模块，避免再次把契约、执行、评估、保存和可视化混在同一个包里：

| 职责 | 目录 | 推荐模块 |
|---|---|---|
| Stage1 请求、BOX 池、Dataset/Collator | `src/datasets/` | `stage1_requests.py`、`stage1_box_pool.py`、`stage1_dataset.py`、`stage1_collate.py` |
| checkpoint、概率入口、完整图、居中、生产编排 | `src/inference/` | `checkpoint.py`、`probability.py`、`full_map.py`、`centered.py`、`runner.py` |
| 树对象、森林、CLG、overlap | `src/component_lineage/` | `structures.py`、`forest.py`、`clg.py`、`overlap.py` |
| calibration 与评估 | `src/evaluation/` | `calibration.py`、`voxel_metrics.py`、`instance_metrics.py`、`report.py` |
| 路径、状态与 NPZ IO | `src/artifacts/` | `paths.py`、`states.py`、`io.py` |
| Selector 顶层入口 | `src/selector/` | `dataset.py`、`wrapper.py`、`train.py`、`inference.py` |
| Selector 模型 | `src/selector/model/` | `input_fusion.py`、`density_munet_lite.py`、`ccln.py` |
| Selector 结构化算法 | `src/selector/structured/` | `oracle.py`、`antichain_dp.py`、`decode.py` |

通用模型能力继续留在 `src/model` 和 `src/wrappers`；producer 训练继续走现有 `src/train.py`，除 CPC checkpoint hook 和本文明确要求的模型接口外不做泛化重构。新生产链通过测试后，可以删除不再被调用的旧 Dataset、旧推理/评估/可视化编排、`src/legacy` 及仅服务这些旧入口的测试；CPC、sparse-refine、ranking 等未实例化的通用模型能力仍保留。

配置沿用现有 Hydra 分组。正式 producer 实验配置固定为：

```text
configs/experiment/CPC1/Find_0.yaml
configs/experiment/CPC1/Find_1.yaml
configs/experiment/CPC2/Find_0.yaml
configs/experiment/CPC2/Find_1.yaml
configs/experiment/unet_c1.yaml
```

Selector 继续使用现有 `dataset/model/experiment/train` 配置组，不为它修改 producer 的 `src/train.py`。每个正式 config 必须 resolve 后保存完整 56D 通道名、global batch、loss、调度和 model dimensions；不要让关键值只存在于命令行 override。

每个正式 config 必须 resolve 后保存完整 56D 通道名、global batch、loss、调度和 model dimensions；不要让关键值只存在于命令行 override。

---

## 3. AI / 工程师建议工作顺序

此顺序服务于减少返工，不改变主文档内容。

### 3.1 建分支与冻结现状

1. 在 Pocket_Plus 创建 AdaLigand 专用新分支。
2. 记录当前 dirty worktree 与上游分支，先保护用户已有修改。
3. 建立旧 Dataset/推理入口清单，标记哪些是模型底层依赖、哪些只是旧编排。
4. 在新链完成等价性测试前，不删除仍被测试或当前运行使用的旧代码。

旧编排清理应在新生产链可用后单独提交；model/wrapper 能力不进入清理范围。

### 3.2 冻结数据准备

按顺序实现并运行：PDB 分组 split → validation/calibration 三轴检查 → train BOX pool → validation selection。train pool 只发布能够得到真实 80³ crop 的记录，不新建 eligibility 工程或排除清单。先用少量真实 PDB 冷读上游 `readme.md`，再实现全量入口；held-out 尺寸检查与去冗余不在本轮执行。

### 3.3 Dataset/Collator

先让一个真实请求完整经过：

```text
upstream assets
  → ResolvedStage1Crop
  → density_input
  → core+8 Å receptor table
  → core scatter mask
  → targets
  → collate
```

再依次接入 train provider、fixed validation provider、full-map provider、centered provider。四种 provider 不复制 crop 逻辑。

### 3.4 模型与五套配置

实现顺序建议：

1. `unet_c1` 单通道 + ligand/aux heads；
2. 两个 Find 共用 `[8,4,0]` point embed；
3. `Find_0` raw50 core hard scatter 与 `Find_1` 无 voxel Transformer 的非块式 embed/scatter；
4. 公共二值 target/loss 适配；
5. CPC2 model-only hook 修补；
6. batch preflight 后冻结五套 config。

完成单 BOX 梯度、validation 指标和配置 compose 后即达到训练前置条件；正式训练提交仍须用户另行授权。

### 3.5 完整图与居中推理

1. 正式 wrapper loader；
2. `forward_voxel_probability`；
3. 单 PDB滑窗融合；
4. calibration 100 全图与 `t_alpha`；
5. component forest、CLG；
6. `F1_centered`；
7. `CLG_centered`；
8. selector 与 `Selected_Refined_Centered`。

F1 路线验证通过后即可交给 Stage2/3 试跑，不必等待 selector。

---

## 4. Dataset 的最小实现提示

### 4.1 请求对象

推荐使用不可变 dataclass：

```python
@dataclass(frozen=True)
class ResolvedStage1Crop:
    """
    表示一个已完成边界解析的 Stage1 80³ 裁剪请求。

    输入参数:
        - pdb_id: str, 当前整图身份
        - box_start_zyx: tuple[int, int, int], (3,), 合法 ZYX 整数起点
        - require_targets: bool, 是否构造训练/验证监督
    """
```

起点 resolver 只接受三轴不小于 80 的 full shape；调用者在请求生成后立即解析，Dataset 不再决定 padding 或 skip。对同一个 `pdb_id + box_start_zyx`，`require_targets=True/False` 只能改变监督字段是否存在，全部模型输入必须逐元素一致。

### 4.2 8 Å加载与 core

Dataset 直接返回 core+8 Å 的 atom 表与一个 bool mask：

```text
atom_is_in_core_box[N_A]
```

模型入口据此构造：

```text
scatter atoms = atoms[atom_is_in_core_box]
point atoms   = all loaded atoms
```

不建立 `atom_is_in_find_view` 或 10→8 Å 二次对齐。保留原始 `atom_global_indices`；旋转同步改变 density、targets 和局部几何，但不改变全局 identity。下游 centered 的 A-pocket 另按“来源 blob 的 10 Å包络 ∩ 当前 80³ BOX”从这些 BOX 内原子中选取，不再读取 BOX 外 receptor。

### 4.3 hardmask 与 target

先对 core atoms 计算唯一 home voxel；`hardmask` 是这些 voxel 的 bool 并集。`voxel_label` 只在同一 home-voxel 集合上把任一 `binding_atom=True` 的位置置正。auxiliary loss 的有效位置为 hardmask；训练 target/loss 不把它当 ligand mask。新推理层则在 sigmoid 之后遮蔽两个 Find 的 ligand probability；unet_c1 不遮蔽。

unet Dataset recipe 可省去 Find 的 56D 构造和 model-view features，但不能省去生成 auxiliary target 所需的 core receptor 查询。

### 4.4 缓存

worker 缓存优先保留轻量点对象和已打开的只读索引，例如 receptor coordinates、49D features、atom labels 与 occurrence sparse indices。不要把多张完整 density/voxel label 数组作为默认高优先级缓存；实际容量按总字节数限制并通过 profiling 调整。完整图 worker 使用有界的“读取/前处理 → GPU forward → float32 融合/写盘”队列，不让待写整图或窗口 batch 无界堆积；记录 Dataset wait、GPU utilization、吞吐、峰值内存和磁盘速率。

---

## 5. Find_0 / Find_1 的最小修改

### 5.1 Find_0

Find_0 与 Find_1 都实例化同一 point-side `Stage1EmbedHead`：模型输入边界先把 `receptor_tokens.npz:feat[49]` 与同一原子的 `is_backbone[1]` 拼成 raw50；atom MLP 为 `50→128→128`，point value 为 `Linear(128→64)+Linear(50→64)`，trunk/voxel block 数为 0，point block radii 为 `[8.0,4.0,0.0]`。Find_0 只在 voxel receptor grid 构造处使用 raw50：

```text
voxel_receptor = hard_scatter_sum(raw_core_atom_feat_50)
```

point path 仍运行共同 embed 并提供 A_feat_L1–L4；voxel path 不消费这些 learned point features。不要为了 raw50 voxel 基线删除或绕过 point path。

### 5.2 Find_1

现有 `Stage1EmbedHead` 已有 MLP/residual/centroid/soft scatter 结构。应允许 `num_trunk_blocks=num_voxel_blocks=0` 后仍执行 voxel 的非块式投影，并保留共同 `num_point_blocks=3` 与 `point_buffer_radii=[8.0,4.0,0.0]`。Dataset 已直接限定输入为 core+8 Å；三个 radius 表示 point blocks 的逐层 buffer，不再承担第二次 model-view 筛选。

### 5.3 core-only scatter 的落点

最小改动优先放在 `stage1_model.py` 构造 voxel receptor grid 之前：从 core+8 Å atom 表按 `atom_is_in_core_box` 筛出 scatter 输入，再调用 Find_0 hard scatter 或 Find_1 soft splat。该行为是 AdaLigand Find 的固定默认，不增加配置开关。point path 直接消费 Dataset 的全 atom 表；两条路径都保留对应的 batch index 和 global index。

---

## 6. Loss 与 CPC 接缝

### 6.1 二值 target

`compute_voxel_ligand_loss_term` 应优先明确接收 `batch["ligand_area_target"]`，不再让 loss module从 `ligand_dist_map` 隐式生成 target。P target 从相同 tensor 按 P 的 batch index 和 home-voxel ZYX gather。

auxiliary loss 接收 `hardmask` 作为 validity mask；wrapper 的 loss adapter 先 gather hardmask 内的 logits/target，再调用通用分类 loss，避免改变该 loss 的数学定义。

### 6.2 CPC2 最小修补

现有 `src/train.py::_load_model_only_checkpoint` 在 strict state_dict 成功后增加既有生命周期调用，语义近似：

```python
checkpoint = torch.load(ckpt_path, map_location="cpu")
model.load_state_dict(checkpoint["state_dict"], strict=True)
model.on_load_checkpoint(checkpoint)
```

不要恢复 trainer state，也不要抽新 threshold helper。

---

## 7. 正式 checkpoint loader 与 voxel-only forward

### 7.1 loader 伪代码

```text
load_stage1_wrapper(checkpoint_path):
    resolved_cfg = read_resolved_config_next_to_checkpoint()
    wrapper = instantiate_full_wrapper(resolved_cfg)
    initialize_lazy_modules_if_required()
    checkpoint = load_checkpoint_cpu()
    wrapper.load_state_dict(checkpoint.state_dict, strict=True)
    wrapper.on_load_checkpoint(checkpoint)
    wrapper.eval()
    return wrapper
```

它不调用旧 `get_pred.load_model`，不只返回 backbone，不另算 hash。

### 7.2 voxel-only 伪代码

严格保持现有训练 `forward` 原样；不要抽共享 `_forward_voxel_branch`，也不要借此重排 model/wrapper。新增独立入口，只复制得到最终 ligand logits 所需的短 voxel 构造与三次 recycle：

```text
forward_voxel_probability(batch):
    if unet_c1:
        voxel_input = density_input
    if Find_0:
        receptor_grid = hard_scatter_sum(raw50[core])
        voxel_input = concat(density56, receptor_grid)
    if Find_1:
        receptor_grid = voxel_mlp_centroid_residual_soft_splat(raw50[core])
        voxel_input = concat(density56, receptor_grid)
    run exactly three voxel recycles
    return final ligand logits
```

如果当前 `Stage1EmbedHead` 的 API 会无条件运行 point blocks，可增加一个默认保持旧行为的内部 branch 参数，使 voxel-only 调用只执行 Find_1 voxel MLP/centroid/residual/soft-splat 所需部分。普通训练不传该参数。等价性测试不仅比较数值，还用调用计数或 hook 证明两个 Find 的 `[8,4,0]` point blocks、point backbone、P candidate、A/P heads 与 sparse-refine 均未执行；另覆盖空原子、边界原子、checkpoint 恢复和 batch>1。

---

## 8. 可续跑推理的最小编排

### 8.1 任务扫描

不要建立数据库。每次启动先只读快速判断 PDB 是否已经满足本次目标；仍有工作时，对 `(stage1_model_name, split, pdb_id)` 的目录原子 `mkdir _RUNNING`。抢占成功后重新检查各 role，并在同一个 `try/finally` 中顺序补齐缺失项：

```text
enumerate expected (model, split, pdb)
  → skip if requested roles already complete or PDB is _BLOB_EXCEED
  → atomically mkdir pdb/_RUNNING; failure means another worker owns it
  → recheck probability/components/F1_centered/CLG_centered/Selected role states
  → write each missing role to its own temporary file
  → validate, atomically replace the formal role NPZ, write role _COMPLETE last
  → finally remove only the _RUNNING created by this worker
```

其它 GPU 看到 `_RUNNING` 立即跳过。异常终止留下的锁与临时文件只由显式、低权重且能核对锁年龄/所有者的运维入口清理；科学 runner 不猜 stale。若 `N_F1_eligible>200`，保留 probability 的 `_COMPLETE`，写 `_BLOB_EXCEED`，不发布 components 或 centered，并在 finally 释放 `_RUNNING`。卡数变化时停止旧 worker、重新扫描和重分尚未完成 PDB 即可。

### 8.2 两阶段入口

推荐三个明确生产入口，共用同一底层 runner：

```text
calibrate-full-map-and-freeze-thresholds
cal-produce-F1-CLG
val-produce-Prob-F1-CLG / train-produce-Prob-F1-CLG
```

第一入口只对 calibration 100 生成完整图 probability、冻结阈值并汇报；阈值冻结后第二入口复用这些 probability 回填 calibration 的 components/F1/CLG。其后的每个 worker 分配 validation、calibration 尚缺 role 的份额以及 train 份额，先消费自己的 validation 与 calibration，再消费 train。worker 数和份额不写死；资源增减时重扫状态后重新分配即可。

### 8.3 selector 输入冻结

selector Dataset 构造时扫描一次 `CLG_centered/_COMPLETE`，按固定顺序同时冻结逐 split 的 PDB inventory 和逐 `(split,pdb_id,CLG_id)` items，并写入当前 selector run 的独立 `input_CLG_list.json`，然后在整个 run 中只使用该清单。零 CLG PDB 保留在 inventory 中但不产生 Dataset item。若显式提供既有清单，逐 PDB、逐 CLG 要求同一 producer 的来源存在且完整，不取交集、不使用共享“latest”，也不在 epoch 中途重扫。训练 loader 用确定性的 PDB-grouped batch sampler：先打乱 PDB，再打乱该 PDB 内 CLG，单 batch 不跨 PDB；这使每 worker 的小型 PDB bundle cache 不会在相邻 CLG 间反复解压。

---

## 9. Component forest 与 CLG 的实现提示

### 9.1 树对象

盘上仍是纯数值 ragged，加载后立即重建专属对象：

```text
ComponentNode(parent, children, read_only_voxel_payload)
ComponentTree(nodes, roots)
ComponentForest(trees)
CLG(seed_node, oldest_node, candidate_nodes)
WorkingTree(original_tree, topology_only_nodes, active_state)
```

`ComponentNode.parent` 与 `children:list[ComponentNode]` 直接表达拓扑；`WorkingTree` 只复制拓扑/状态并回指原只读 node，不复制 voxel payload。所有 ancestors/subtree/sisters/LCA/D(g) 操作集中在对象接口中；CLG 枚举业务逻辑不直接操纵 offsets，也不散落 parent while-loop。

### 9.2 cap 与 D(g)

原子事件先在临时 candidate list 上计算加入后节点数。若 `new_count>cap`：

```text
reject entire current CLG attempt
increment n_CLG_rejected_by_node_cap
do not allocate clg_id
do not write candidate arrays
apply D(g) to current selected seed on WorkingTree
continue scan
```

不要为失败尝试计算 tentative oldest node；成功后才从候选集合验证唯一 `CLG_oldest_node`。每个成功 CLG 只保存本次唯一 `CLG_seed_node_id`；事件中加入的 sisters 只是普通 candidates。

成功 CLG 完成发布后，也对本次当前 selected seed 在同一 `WorkingTree` 上执行同一个 D(g)；成功与 node-cap 失败不得使用两套删除函数。

---

## 10. Centered 导出与 V48+D

### 10.1 feature hooks

V/P/A 的 hook 应位于主文档定义的真实层出口，具名返回 dict。每个字段在 Docstring 中写清 `torch.Tensor` shape、实体对齐和层语义。两个 Find 的模型前向仍返回 A/P 交叉注意力前后的特征，但 centered 归档只保存 A_feat_L1–L3 与 P_feat_L2–L3；`A_feat_L0` 从当前 centered 输入 `atom_feat` 按 `A_global_index` 对齐到模型输出行序后，以 float32 直接落盘。Selector 不再二次读取 receptor 基础表；`A_global_index` 只保留身份追踪。unet 不含 P/A key。

Stage1 模型内部可以继续保留低分辨率 V 张量供 Find 点—体素融合使用；centered 归档只把 `voxel_final` 按权威 voxel index gather，不保存固定多尺度 V 网格。概率在 sigmoid 后转 float32；落盘学习特征转 float16。Selected 非 success 归档项的变长数据段为空。

### 10.2 residual_swiglu

建议实现一个接收有序 `dict[str, Tensor]` 的 adapter。初始化时根据 producer/consumer 配置创建实际来源投影；forward 不接受“缺失 source 自动补零”。config 测试应断言 source 顺序和输入通道。

### 10.3 V48+D

`DensityMUNetLite` 只读取现场构造的 `exp_clipnorm_nopost[B,1,80,80,80]`，使用 80→40→20→10、通道 `[32,64,64,128]`、每层一个 residual convolution block；encoder/decoder 无 Transformer，只在 10³ bottleneck 使用 4-head、1-layer Transformer。decoder 的 32D 全分辨率结果仅在实际 V 坐标 gather 后投影 32→48，不生成或落盘 dense48；参数属于当前 Selector、Stage2 或 Stage3 checkpoint。

V48 与 V48+D 共用同一 V adapter 接口；显式关闭密度分支 `c` 后必须逐元素退化为 V48。消费模型不读取或采样固定多尺度 V 网格。

---

## 11. 建议测试文件与用例

测试名仅是推荐落点；测试内容不能反向改变主规格。

### 11.1 数据与几何

```text
tests/datasets/test_stage1_split_pool.py
tests/datasets/test_stage1_geometry_parity.py
tests/datasets/test_stage1_dataset_modes.py
tests/datasets/test_stage1_receptor_view.py
tests/datasets/test_stage1_rotation_collate.py
```

覆盖：validation/calibration 小图选择时排除、train pool 不物化非法 crop、同 PDB 不跨 split、bias 30/重复保留、context 池为 0/1/2 时不崩且行为固定、起点 clamp、同一 crop parity、8 Å/core 集合关系、targets 开/关时模型输入逐元素一致、训练/完整图/居中模式同构、各向异性 voxel size 下旋转同步交换轴尺度、collate 同步、validation 确定性和真实一步反传。

### 11.2 模型与训练

```text
tests/model/test_find0_contract.py
tests/model/test_find1_contract.py
tests/model/test_unet_c1_contract.py
tests/wrappers/test_stage1_binary_losses.py
tests/test_cpc_model_only_restore.py
tests/model/test_voxel_probability_forward.py
```

覆盖：106/108/1 voxel 输入通道、两个 Find 的共同 point embed、Find_0 raw50 hard scatter、Find_1 trunk/voxel block 为 0 且 point radii `[8,4,0]`、core-only scatter、direct 1×1 heads、aux hardmask、总损失权重、CPC1→CPC2 state、voxel-only 逐元素等价及 skipped-branch 调用计数。

### 11.3 推理与树

```text
tests/inference/test_full_map_fusion.py
tests/evaluation/test_threshold_calibration.py
tests/component_lineage/test_structures.py
tests/component_lineage/test_clg_enumerator.py
tests/component_lineage/test_clg_node_cap.py
tests/artifacts/test_centered_roles.py
tests/artifacts/test_atomic_resume.py
```

重点构造极小人工树验证：

- parent/children/sisters/LCA；
- unary、split、merge 预算；
- 32/64 恰好允许，超过后整组失败；
- 失败没有 CLG ID/半成品；
- 当前 seed 的 D(g) 从工作副本计算；
- 原始树不变；
- F1/CLG 忽略局部额外组件；
- Selected 原阈值与 max-IoU source 匹配。

### 11.4 Selector 与存储

```text
tests/artifacts/test_box_contract_roundtrip.py
tests/selector/test_residual_swiglu.py
tests/selector/test_input_fusion.py
tests/selector/test_antichain_dp.py
tests/selector/test_input_freeze.py
```

覆盖：ragged round-trip、必需字段缺失即失败、Selected 非 success 变长数据段为空、缺模态不补零、V48+D→V48 退化、DP 与穷举 partition/MAP/gradient、启动后 Dataset 不增长、零 CLG PDB inventory/空 scores、跨 CLG 重复 node 的 max-gate 校正与有序去重、PDB-grouped sampler。

---

## 12. 最小真实 smoke 与清理时点

单元测试后至少做：

1. 一个真实 PDB 的三个 Dataset recipe 冷读与单步 forward/backward；
2. 一个 Find 的 CPC1 checkpoint → CPC2 第一次更新前对照；
3. 一个真实 PDB 的完整图融合、component forest、F1/CLG centered 聚合 NPZ round-trip；
4. 一个小型 selector batch 的 online oracle、forward、DP 和 selection；
5. 中断一次 per-PDB 推理，再重扫续跑，确认半成品不被读取。

新链通过这些检查并完成科学等价性证据后，才清理旧 Dataset/推理编排。清理前确认没有运行任务、恢复任务或审计仍依赖旧入口；清理后重跑相关单元、全套测试和真实 smoke。通用 model/wrapper、CPC、sparse-refine、ranking 能力继续保留。本轮 smoke 不提交正式训练。
