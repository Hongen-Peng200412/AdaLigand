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

新生产代码集中到 AdaLigand 命名空间，减少与旧推理主线混杂：

```text
Pocket_Plus/
  src/adaligand/
    stage1/
      data_preparation.py
      dataset.py
      collate.py
      requests.py
      checkpoint_loader.py
      full_map.py
      calibration.py
      component_forest.py
      clg.py
      centered.py
      artifact_io.py
    selector/
      dataset.py
      input_adapter.py
      v5d.py
      ccln.py
      antichain_dp.py
      train.py
      decode.py
  configs/adaligand/
    dataset/
    model/
    experiment/
    inference/
    selector/
```

这不是强制文件树；如果 Pocket_Plus 当前包结构要求把文件放进既有 `src/datasets` 或 `src/inference`，可以调整路径，但应保留一个清晰的 AdaLigand 生产入口。模型通用能力仍留在 `src/model` 和 `src/wrappers`，不要复制一套模型。

建议配置文件：

```text
configs/adaligand/dataset/stage1.yaml
configs/adaligand/model/find0.yaml
configs/adaligand/model/find1.yaml
configs/adaligand/model/unet_c1.yaml
configs/adaligand/experiment/find0_cpc1.yaml
configs/adaligand/experiment/find0_cpc2.yaml
configs/adaligand/experiment/find1_cpc1.yaml
configs/adaligand/experiment/find1_cpc2.yaml
configs/adaligand/experiment/unet_c1.yaml
```

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

按顺序实现并运行：eligibility → split → train pool → validation selection。先用少量真实 PDB 冷读上游 `readme.md`，再实现全量入口。held-out 去冗余不在本轮执行。

### 3.3 Dataset/Collator

先让一个真实请求完整经过：

```text
upstream assets
  → ResolvedStage1Crop
  → density_input
  → 10 Å receptor table
  → 8 Å Find view + core scatter mask
  → targets
  → collate
```

再依次接入 train provider、fixed validation provider、full-map provider、centered provider。四种 provider 不复制 crop 逻辑。

### 3.4 模型与五套配置

实现顺序建议：

1. `unet_c1` 单通道 + ligand/aux heads；
2. `Find_0` 无 embed + core hard scatter；
3. `Find_1` block=0 的非块式 embed/scatter；
4. 公共二值 target/loss 适配；
5. CPC2 model-only hook 修补；
6. batch preflight 后冻结五套 config。

完成单 BOX 梯度和 validation 指标后再启动全量训练。

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
        - source_kind: str, 请求来源类别
        - source_index: tuple[int, ...], 可变长度, 来源内部身份
    """
```

起点 resolver 只接受 eligible full shape；调用者在请求生成后立即解析，Dataset 不再决定 padding 或 skip。

### 4.2 10 Å、8 Å与 core

建议 Dataset 一次返回所有 10 Å atoms 与两个 bool mask：

```text
atom_is_in_core_box[N_A]
atom_is_in_find_view[N_A]
```

模型入口据此构造：

```text
scatter atoms = atoms[atom_is_in_core_box]
point atoms   = atoms[atom_is_in_find_view]
```

`atom_is_in_find_view` 应包含 core 且最多扩展 8 Å；它不能简单等于“Dataset 已加载”。保留原始 `atom_global_indices`，旋转只改变局部坐标，不改变全局 identity。

### 4.3 hardmask 与 target

先对 core atoms 计算唯一 home voxel；`hardmask` 是这些 voxel 的 bool 并集。`voxel_label` 只在同一 home-voxel 集合上把任一 `binding_atom=True` 的位置置正。auxiliary loss 的有效位置为 hardmask；不要把 hardmask 当密度通道或 ligand mask。

unet Dataset recipe 可省去 Find 的 56D 构造和 model-view features，但不能省去生成 auxiliary target 所需的 core receptor 查询。

### 4.4 缓存

worker 缓存优先保留轻量点对象和已打开的只读索引，例如 receptor coordinates、49D features、atom labels 与 occurrence sparse indices。不要把多张完整 density/voxel label 数组作为默认高优先级缓存；实际容量按总字节数限制并通过 profiling 调整。

---

## 5. Find_0 / Find_1 的最小修改

### 5.1 Find_0

若现有 `VolumePointStage1Model` 强制实例化 `Stage1EmbedHead`，最小修改是允许 `embed_head=None`，并让：

```text
point_input = raw_atom_feat_49
voxel_receptor = hard_scatter_sum(raw_core_atom_feat_49)
```

不要通过创建一个全零输出的 embed 模块来伪装“无 embed”。测试参数名中不应出现 embed head 参数。

### 5.2 Find_1

现有 `Stage1EmbedHead` 已有 MLP/residual/centroid/soft scatter 结构。应允许 `num_trunk_blocks=num_voxel_blocks=num_point_blocks=0` 后仍执行非块式投影。不要把 `point_buffer_radii=[8.0]` 当作 8 Å model view；block list 为空，8 Å由输入 mask 实现。

### 5.3 core-only scatter 的落点

最小改动优先放在 `stage1_model.py` 构造 voxel receptor grid 之前：从 batch 的 10 Å atom 表按 `atom_is_in_core_box` 筛出局部视图，再调用现有 hard/soft scatter。这样 Find_0 与 Find_1 自动共用 core-only 语义，也不会给 config 增加开关。

point path 在进入 embed point projection/point backbone 前按 `atom_is_in_find_view` 筛选；两次筛选都保留对应的 batch index 和 global index。

---

## 6. Loss 与 CPC 接缝

### 6.1 二值 target

`compute_voxel_ligand_loss_term` 应优先明确接收 `batch["ligand_area_target"]`，不再让 loss module从 `ligand_dist_map` 隐式生成 target。P target 从相同 tensor 按 P 的 batch index 和 home-voxel ZYX gather。

auxiliary loss 应接收 `hardmask` 作为 validity mask；若现有 loss API 不能限定位置，在 wrapper 的 loss adapter 处先 gather 有效 logits/target，避免改变通用分类 loss 数学定义。

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

建议把共享 voxel 链抽成模型内部私有方法，而不是复制 forward：

```text
_forward_voxel_branch(batch, recycle_passes):
    receptor_grid / point_seed = build_embed_and_scatter(batch)
    voxel_input = build_voxel_input(batch.density_input, receptor_grid)
    voxel_state, voxel_exports = run_voxel_recycles(voxel_input, recycle_passes)
    voxel_logits_ligand, voxel_logits_aux = run_voxel_heads(voxel_state)
    return voxel_state, voxel_exports, logits

forward_voxel_probability(batch):
    _, _, logits = _forward_voxel_branch(batch, recycle_passes=3)
    return logits.voxel_ligand

forward(batch):
    voxel_state, exports, logits = _forward_voxel_branch(...)
    ... point / A / P ...
```

如果 Find embed 的 point projection 与 voxel scatter 共用 MLP，可以执行产生 voxel grid 所需的共享部分，但不得继续跑 point backbone/A/P heads。

---

## 8. 可续跑推理的最小编排

### 8.1 任务扫描

不要建立数据库。每次启动：

```text
enumerate expected (model, split, pdb, role)
  → remove units whose target directory has valid _COMPLETE
  → sort/repartition remaining units for current cards
  → run each unit into sibling temporary directory
  → validate
  → atomically publish
  → write _COMPLETE last
```

卡数变化时停止旧 worker、重新扫描并提交未完成单元即可。一个 PDB 的重复 attempt 只能有一个最终原子发布者；其它 attempt 发现目标已完成后丢弃自己的临时目录。

### 8.2 两阶段入口

推荐两个明确子命令：

```text
calibration-full-map-and-freeze-thresholds
val-train-produce-centered
```

第二阶段 worker 取得一个 PDB 后依次尝试 probability → components → F1 → CLG；每一步完成即发布。它不要求所有卡具有固定编号。validation 份额优先，但每张卡也带 train 份额，资源减少后剩余任务可重新分配。

### 8.3 selector 输入冻结

selector Dataset 构造时扫描一次 `CLG_centered/_COMPLETE`，把 PDB 清单写入当前 selector 输出目录，然后在整个 run 中只使用该清单。不要在 epoch 中途重扫。

---

## 9. Component forest 与 CLG 的实现提示

### 9.1 树对象

推荐一个专属结构：

```text
ComponentArborescence:
    node arrays
    parent_node_id[N]
    children_offsets[N+1]
    children_node_id[L]

WorkingArborescence:
    original tree reference
    active[N]
    frontier state
    current CLG membership
```

所有 ancestor/subtree/sister/LCA 操作集中在该结构中。不要在 CLG 枚举器各处手写 parent while-loop 与“不能穿过”布尔组合。

### 9.2 cap 与 D(G)

原子事件先在临时 candidate list 上计算加入后节点数。若 `new_count>cap`：

```text
reject entire current CLG attempt
increment n_CLG_rejected_by_node_cap
do not allocate clg_id
do not write candidate arrays
apply D(G) to current selected seed on WorkingArborescence
continue scan
```

不要为失败尝试计算 tentative `CLG_cover_node`；成功后才从候选集合验证唯一 cover node。

成功 CLG 完成发布后，也对本次当前 selected seed 在同一 `WorkingArborescence` 上执行同一个 D(G)；成功与 node-cap 失败不得使用两套删除函数。

---

## 10. Centered 导出与 V5+D

### 10.1 feature hooks

V/P/A 的 hook 应位于主文档定义的真实层出口，具名返回 dict。每个字段在 Docstring 中写清 `torch.Tensor` shape、实体对齐和层语义。Find_0 的返回 dict 不应含 `receptor_feat_L1` key；unet 不应含 P/A key。

四张低分辨率 V grid 在 forward 中各保留一份 native tensor；`voxel_final` 只按权威 voxel index gather。概率在 sigmoid 后转 float32；learning features 转 float16 后写盘。

### 10.2 residual_swiglu

建议实现一个接收有序 `dict[str, Tensor]` 的 adapter。初始化时根据 producer/consumer 配置创建实际来源投影；forward 不接受“缺失 source 自动补零”。config 测试应断言 source 顺序和输入通道。

### 10.3 V5+D

低分辨率 grid sampling 使用 `grid_sample` 或等价可微三线性采样，在消费模型内部把 BOX voxel centers 映射到各层规范化坐标。SmallDensityUNet 只读取现场构造的 `exp_clipnorm_nopost`，其参数属于当前 selector/Stage2/Stage3 checkpoint。

V48、V5、V5+D 应共用同一 V adapter 接口；通过显式 branch config 关闭 `m/c`，测试关闭后输出逐元素等于 V48 路径。

---

## 11. 建议测试文件与用例

测试名仅是推荐落点；测试内容不能反向改变主规格。

### 11.1 数据与几何

```text
tests/adaligand/test_stage1_eligibility_split.py
tests/adaligand/test_stage1_pool.py
tests/adaligand/test_stage1_geometry_parity.py
tests/adaligand/test_stage1_dataset_modes.py
tests/adaligand/test_stage1_receptor_views.py
tests/adaligand/test_stage1_rotation.py
```

覆盖：小图训练前排除、同 PDB 不跨 split、bias 30/重复保留、起点 clamp、同一 crop parity、10 Å/8 Å/core 集合包含关系、旋转同步、validation 确定性。

### 11.2 模型与训练

```text
tests/adaligand/test_find0_contract.py
tests/adaligand/test_find1_contract.py
tests/adaligand/test_unet_c1_contract.py
tests/adaligand/test_stage1_binary_losses.py
tests/adaligand/test_cpc_model_only_restore.py
tests/adaligand/test_voxel_probability_forward.py
```

覆盖：105/107/1 输入通道、Find_0 无 embed 参数、Find_1 block 全 0、core-only scatter、direct 1×1 heads、aux hardmask、总损失权重、CPC1→CPC2 state、voxel-only 逐元素等价。

### 11.3 推理与树

```text
tests/adaligand/test_full_map_fusion.py
tests/adaligand/test_threshold_calibration.py
tests/adaligand/test_component_arborescence.py
tests/adaligand/test_clg_enumerator.py
tests/adaligand/test_clg_node_cap.py
tests/adaligand/test_centered_roles.py
tests/adaligand/test_atomic_resume.py
```

重点构造极小人工树验证：

- parent/children/sisters/LCA；
- unary、split、merge 预算；
- 32/64 恰好允许，超过后整组失败；
- 失败没有 CLG ID/半成品；
- 当前 seed 的 D(G) 从工作副本计算；
- 原始树不变；
- F1/CLG 忽略局部额外组件；
- Selected 原阈值与 max-IoU source 匹配。

### 11.4 Selector 与存储

```text
tests/adaligand/test_box_contract_roundtrip.py
tests/adaligand/test_residual_swiglu.py
tests/adaligand/test_v5d.py
tests/adaligand/test_antichain_dp.py
tests/adaligand/test_selector_input_freeze.py
```

覆盖：ragged round-trip、dtype/shape、缺模态不补零、V5+D→V48 退化、DP 与穷举 partition/MAP/gradient、启动后 Dataset 不增长。

---

## 12. 最小真实 smoke 与清理时点

单元测试后至少做：

1. 一个真实 PDB 的三个 Dataset recipe 冷读与单步 forward/backward；
2. 一个 Find 的 CPC1 checkpoint → CPC2 第一次更新前对照；
3. 一个真实 PDB 的完整图融合、component forest、F1/CLG centered round-trip；
4. 一个小型 selector batch 的 online oracle、forward、DP 和 selection；
5. 中断一次 per-PDB 推理，再重扫续跑，确认半成品不被读取。

新链通过这些检查并完成科学等价性证据后，才清理旧 Dataset/推理编排。清理前确认没有运行任务、恢复任务或审计仍依赖旧入口；清理后重跑相关单元、全套测试和真实 smoke。通用 model/wrapper、CPC、sparse-refine、ranking 能力继续保留。
