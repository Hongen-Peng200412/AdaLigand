# AdaLigand BOX 级数据契约

> **本文定位**：本文是 Stage1 训练预定位、完整图概率、组件森林/CLG、三类居中 BOX、selector score 与正式 selection 的盘上唯一权威。它只规定身份、目录、字段、shape、dtype、ragged 关系和完成语义；算法与 loss 见两份 Stage1 规划文档。
>
> **上游**：`文档/规划文档/数据处理_v2.md` 与 `Data_Preprocessing/Ori_Data/code/readme.md` 提供整图密度、受体、标签和 occurrence 资产，到此不切 Stage1 BOX。
>
> **生产者**：`文档/规划文档/Stage1训练实现计划.md` 与 `文档/规划文档/Stage1训练与多阈值推理.md`。
>
> **消费者**：selector、Stage2、Stage3 与后续精修模型。它们不得靠猜测补出本契约中不存在的模态或层。
>
> **逻辑与物理**：本文规定解码后的逻辑数组。实现可按 PDB 分片以控制文件数，但所有 NumPy 归档统一使用 `np.savez_compressed`，禁止 object array/pickle。学习特征保存 float16；概率与几何保存 float32。

---

## 0. 总体原则

一个 BOX 不是预切好的密度大包，而是：

```text
冻结身份 + 80³ 几何 + 稀疏权威 voxel 集
+ producer 实际产生的 V/P/A 特征和概率
```

raw density、sim、GT 和 49D receptor 基础表继续整图存一次；Dataset/消费者根据 `pdb_id + box_start_zyx` 现场裁剪。完整图 `probability_map` 也每 PDB、每 producer 存一次。

契约遵守：

1. 训练预定位池与推理居中 BOX 物理分开。
2. 固定 producer/split/PDB/role 路径就是正式身份，不再叠加一层不透明的运行身份。
3. checkpoint 信息不在每个输出重复记录；调用入口选中的 checkpoint 已唯一决定 producer 输出。
4. 默认每个 producer 只有一套正式 CLG 规则，不写 `CLG_hash`。只有未来确实要让多套 CLG 规则长期并存时，才在 CLG/CLG_centered 层增加该真实区分键。
5. 字段名直接使用 component、candidate、cover、entry、index 等真实数据结构语义。
6. 缺失模态就是缺失，不用全零数组伪造。
7. 下游只读取带 `_COMPLETE` 的原子发布目录。

---

## 1. 整图资产与几何

整图资产字段、实际服务器路径和版本以 `Data_Preprocessing/Ori_Data/code/readme.md` 为准。Stage1 依赖的逻辑内容：

| 内容 | 解码 shape / dtype | 作用 |
|---|---|---|
| experimental density | `[1,D,H,W] float32` | 三个 producer；下游 density_input |
| simulated density | `[1,D,H,W] float32` | Find 56D density recipe |
| ligand-area union mask | `[D,H,W] bool` 或等价稀疏表示 | voxel ligand target、语义评估 |
| per-occurrence ligand-area mask | ragged sparse voxel sets | center/bias、instance overlap |
| receptor coordinates | `[N_rec,3] float32` XYZ Å | 10 Å查询、A 几何、hardmask |
| receptor feature | `[N_rec,49] float32` | Find raw A input |
| binding atom label | `[N_rec] bool` | A/voxel auxiliary target |
| occurrence identities/coords | ragged | overlap 与评估 |

数组轴恒为 ZYX；世界坐标恒为 XYZ Å。完整网格几何由上游 `origin_xyz` 和 `voxel_size_xyz` 给出。所有 BOX 固定 `[80,80,80]`，其起点必须满足：

$$
0\le box\_start_a\le full\_shape_a-80.
$$

因此 BOX 永远是完整真实 crop，不存空间 padding mask。

---

## 2. 冻结数据准备契约

### 2.1 eligibility 与 split

推荐布局：

```text
stage1_preparation/
  eligibility/
    eligible_pairs.json
    excluded_pairs.json
    summary.json
  split/
    train.json
    validation.json
    calibration.json
    held_out_pool.json
    summary.json
```

`excluded_pairs.json` 对小图记录 `reason="grid_axis_lt_80"` 和 `full_shape_zyx`。split 文件的每个条目至少包含 `pdb_id` 与上游 pair identity；同一 PDB 不得跨文件。validation 恰为 300，calibration 恰为 100，train 为 eligible 总数的 `floor(0.75N)`，其余进 held-out pool。

### 2.2 训练预定位池

```text
stage1_preparation/box_pool/
  config.json
  train/{pdb_id}.npz
  validation/{pdb_id}.npz
  validation_selection.npz
  _COMPLETE
```

每个 PDB 的 pool：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `occurrence_id` | `[N_occ] int32` | 上游 occurrence identity |
| `center_start_zyx` | `[N_occ,3] int32` | 每 occurrence 唯一解析起点 |
| `bias_start_zyx` | `[N_occ,30,3] int32` | 球内均匀 bias 后的解析起点；重复保留 |
| `context_start_zyx` | `[N_context,3] int32` | 现有 context 生成器产出的合法起点 |

`config.json` 至少记录 BOX shape、bias 30 及半径公式、每 epoch 选 5、context generator 配置、每 PDB occurrence cap 50、比例 `1:5:3`、旋转开关和随机 seed 规则。不保存实际 density/target crop。

`validation_selection.npz` 冻结 validation 真实读取项；指向固定 PDB 表的字段统一使用 `*_pdb_index`：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `validation_pdb_id` | `[N_val_pdb]` fixed-width string | 固定 PDB 表 |
| `center_pdb_index` | `[N_center] int32` | 指向上述 PDB 表 |
| `center_occurrence_id` | `[N_center] int32` | 固定 occurrence |
| `bias_pdb_index` | `[N_bias] int32` | 指向 PDB 表 |
| `bias_occurrence_id` | `[N_bias] int32` | occurrence identity |
| `bias_candidate_index` | `[N_bias] int16` | `0..29` |
| `context_pdb_index` | `[N_context_selected] int32` | 指向 PDB 表 |
| `context_candidate_index` | `[N_context_selected] int32` | 指向对应 context pool |

每个 PDB 最多 50 个 occurrence；center:bias:context 的条目数严格为每个入选 occurrence `1:5:3`。validation 不保存增强结果。

---

## 3. 正式 Stage1 输出目录

### 3.1 固定寻址

核心根目录：

```text
stage1_outputs/
  {stage1_model_name}/
    calibration/
      thresholds.json
      metrics.json
      _COMPLETE
    {split}/
      {pdb_id}/
        probability/
        components/
        centered/
          F1_centered/
          CLG_centered/
          Selected_Refined_Centered/
```

`stage1_model_name` 只取 `Find_0`、`Find_1`、`unet_c1`。每个居中 BOX 的逻辑键固定为：

```text
(stage1_model_name, split, pdb_id, centered_role, centered_box_index)
```

没有额外概率/组件/物化 run ID。正式 producer 更换 checkpoint 时，应由执行者显式清理或归档该 producer 的旧未用输出后重跑；不能在同一正式目录混入两套 checkpoint。

### 3.2 原子完成

每个 per-PDB 子目录先写同级临时目录，全部数组关闭并完成基本校验后原子发布，最后写 `_COMPLETE`。消费者忽略：

- 没有 `_COMPLETE` 的目录；
- 临时目录；
- index 引用越界或分片缺失的目录。

`probability`、`components` 和三种 centered role 分别完成；因此 F1 可以早于 CLG/Selected 被消费。

---

## 4. 完整图概率与 calibration 表

### 4.1 probability

```text
probability/
  probability_map.npz
  geometry.json
  _COMPLETE
```

`probability_map.npz`：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `probability_map` | `[D,H,W] float32` | Gaussian 融合后的正式 ligand probability |

`geometry.json` 只保存解析该数组所需的 `full_shape_zyx`、`origin_xyz`、`voxel_size_xyz`、window shape 80、stride 40、Gaussian sigma 0.5 和 `contract_version`。不复制 checkpoint 路径，不保存 full-map V/P/A。

### 4.2 thresholds

每个 producer 的 `calibration/thresholds.json`：

```text
stage1_model_name
alpha_values                 # [1/2,2/3,4/5,1,5/4,3/2,2]
t_alpha                      # 与 alpha 一一对应
physical_threshold_values    # 去重，按高到低
alpha_to_threshold_index
t_F1
min_voxels                   # 32
max_voxels                   # 用户冻结的 Q95×1.5 整数
connectivity                 # 26
```

`metrics.json` 保存 calibration fitted 指标与扫描曲线引用。阈值表不重复写入每个 PDB。

---

## 5. Component forest 与 CLG

```text
components/
  forest.npz
  clg.npz
  overlap.npz                # train/validation/calibration 有 GT 时
  summary.json
  _COMPLETE
```

### 5.1 forest.npz

设总 node 数为 `N_node`，全部 node voxel index 拼接长度为 `L_voxel`，children 拼接长度为 `L_child`：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `tree_id` | `[N_node] int32` | 当前 PDB 内树 identity |
| `node_id` | `[N_node] int32` | 对应 tree 内 node identity |
| `threshold_index` | `[N_node] uint8/uint16` | 物理阈值下标 |
| `threshold_value` | `[N_node] float32` | 便于冷读的实际阈值 |
| `parent_node_id` | `[N_node] int32` | direct parent；root 为 `-1` |
| `children_offsets` | `[N_node+1] int64` | direct children 区间 |
| `children_node_id` | `[L_child] int32` | 与本 node 同 tree 的 child IDs |
| `node_voxel_offsets` | `[N_node+1] int64` | 每个 mask 的 voxel 区间 |
| `node_voxel_global_linear_index` | `[L_voxel] int64` | ZYX C-order 全图线性 index；node 内唯一 |
| `voxel_count` | `[N_node] int32` | mask 大小 |
| `bbox_min_zyx` | `[N_node,3] int32` | 完整 mask bbox |
| `bbox_max_zyx` | `[N_node,3] int32` | 闭区间 bbox |
| `centroid_zyx` | `[N_node,3] float32` | mask voxel-index centroid |
| `probability_mean` | `[N_node] float32` | mask 内 full-map probability mean |
| `probability_max` | `[N_node] float32` | mask 内 max |
| `candidate_eligible` | `[N_node] bool` | 体积与 centered bbox 规则是否通过 |
| `ineligible_reason_code` | `[N_node] uint8` | 0=eligible；其它值由 summary 解释 |

`parent_node_id` 与 children 必须互相一致。sisters 现场从 children 派生，不落重复 sister 表。森林是只读原件；工作副本状态不得写回。

### 5.2 clg.npz

设成功 CLG 数 `N_clg`，flatten 后 candidate 数 `N_candidate`，seed candidate 下标总数 `L_seed`：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `clg_id` | `[N_clg] int32` | 当前 PDB 内连续 identity |
| `tree_id` | `[N_clg] int32` | 所属原树 |
| `clg_cover_node_id` | `[N_clg] int32` | 唯一 cover node |
| `candidate_offsets` | `[N_clg+1] int64` | 每个 CLG 的 candidate 区间 |
| `candidate_node_id` | `[N_candidate] int32` | 原 forest node identity |
| `candidate_threshold_index` | `[N_candidate] uint8/uint16` | 冗余小字段，便于批读取 |
| `seed_candidate_offsets` | `[N_clg+1] int64` | 每个 CLG 的 seed-like candidate 区间 |
| `seed_candidate_index` | `[L_seed] int16` | CLG 内 candidate index |

失败或因 node cap 拒绝的尝试不进入该文件。`summary.json` 至少保存 depth 配置、`n_f1_eligible_seeds`、`n_CLG_cap`、`n_CLG_completed`、`n_CLG_rejected_by_node_cap` 与 `CLG_cap_reached`。

祖先、LCA、姐妹和 antichain conflict 从 `forest.npz` 现场计算，不重复保存 NxN 关系表。

### 5.3 overlap.npz

这是 selector online oracle 的基础事实，不是持久 oracle。按 `clg.npz` flatten 后的 candidate 顺序，保存 candidate 与 occurrence 的非零交集：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `candidate_occurrence_offsets` | `[N_candidate+1] int64` | 每个 candidate 的相交 occurrence 区间 |
| `overlap_occurrence_id` | `[N_overlap] int32` | GT identity |
| `intersection_voxel_count` | `[N_overlap] int32` | 全图 candidate mask 与 GT mask 交集 |
| `occurrence_id` | `[N_gt] int32` | 当前 PDB 全部 GT identities |
| `occurrence_voxel_count` | `[N_gt] int32` | 各 GT mask 大小 |

candidate voxel count 从 forest 读取，因此可现场求 IoU。`q_i`、`S*`、`y_G`、lambda 专属标签和反链结果不得写入本文件。

---

## 6. Centered BOX 的物理组织

### 6.1 index 与分片

每个 role 目录：

```text
{centered_role}/
  index.npz
  part_00000.npz
  part_00001.npz
  ...
  _COMPLETE
```

一个 part 可以包含多个 BOX，避免每 BOX 一个小文件。`index.npz`：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `centered_box_index` | `[N_box] int32` | `0..N_box-1` |
| `part_index` | `[N_box] int32` | 所在 part |
| `entry_index_in_part` | `[N_box] int32` | part 内 entry 下标 |
| `box_start_zyx` | `[N_box,3] int32` | 已解析合法起点 |
| `shape_zyx` | `[N_box,3] uint8` | 固定 `[80,80,80]` |
| `source_tree_id` | `[N_box] int32` | 来源 forest tree |
| `source_node_id` | `[N_box] int32` | F1 source、CLG cover 或 Selected source |
| `source_threshold_value` | `[N_box] float32` | 来源 node 阈值 |

`CLG_centered/index.npz` 另有 `clg_id[N_box] int32`。F1 不伪造 `clg_id`。Selected 另有 `refine_status[N_box] uint8`，状态名称映射写在 role 的 `status.json`。

### 6.2 通用 ragged 编码

每个 part 的每类变长实体都使用 `offsets + values`：

```text
voxel_offsets[N_entry+1]
voxel_index_local_zyx[L_voxel,3]

P_offsets[N_entry+1]
P_...

A_offsets[N_entry+1]
A_...
```

同一 entry 内 index 唯一。offsets 为 int64。`voxel_index_local_zyx` 是当前 role 的权威 voxel 集，结合 `box_start_zyx` 可恢复全图 ZYX。

---

## 7. 三类 Centered payload

### 7.1 共同 voxel 字段

所有成功 entry：

| 字段 | shape / dtype | 对齐对象 |
|---|---|---|
| `voxel_index_local_zyx` | `[K_v,3] int16` | 当前权威 voxel 集 |
| `centered_probability` | `[K_v] float32` | 居中 forward 在这些 voxel 的 ligand probability |
| `voxel_final` | `[K_v,48] float16` | producer final voxel feature |
| `voxel_ds_2` | `[256,20,20,20] float16` per entry | native low-resolution grid |
| `voxel_ds_3` | `[256,10,10,10] float16` per entry | native low-resolution grid |
| `voxel_ds_4` | `[256,5,5,5] float16` per entry | native low-resolution grid |
| `voxel_c4` | `[256,5,5,5] float16` per entry | native bottleneck grid |
| `voxel_aux_index_local_zyx` | `[K_aux,3] int16` | hardmask 唯一 receptor home voxels |
| `voxel_aux_probability` | `[K_aux] float32` | auxiliary probability |

不保存 dense final 48D grid、稠密 centered ligand probability、threshold rank map 或按 K_v 重复的低分辨率预采样特征。

### 7.2 Find 的 P 与 A 字段

Find entry 的 P 表：

| 字段 | shape / dtype |
|---|---|
| `P_coord_local_xyz` | `[N_P,3] float32` |
| `P_probability` | `[N_P] float32` |
| `P_feat_L2` | `[N_P,C_P2] float16` |
| `P_feat_L3` | `[N_P,C_P3] float16` |
| `P_feat_L4` | `[N_P,C_P4] float16` |

Find entry 的 A 表只包含实际进入 8 Å model view 并获得学习特征的原子：

| 字段 | shape / dtype |
|---|---|
| `A_global_index` | `[N_A] int64` |
| `A_coord_local_xyz` | `[N_A,3] float32` |
| `A_is_in_core_box` | `[N_A] bool` |
| `A_probability` | `[N_A] float32` |
| `receptor_feat_L2` | `[N_A,C_A2] float16` |
| `receptor_feat_L3` | `[N_A,C_A3] float16` |
| `receptor_feat_L4` | `[N_A,C_A4] float16` |

`Find_1` 另有 `receptor_feat_L1[N_A,C_A1] float16`；`Find_0` 不得出现该字段。为恢复统一 10 Å raw receptor context，另存：

```text
receptor_context10_offsets[N_entry+1]
receptor_context10_global_index[L_context] int64
```

外侧 8–10 Å 原子只有上游 raw feature/geometry，不伪造 A learning feature。`unet_c1` 不保存任何 P/A 字段或 context10 索引。

### 7.3 F1_centered

每个 entry 对应一个 eligible F1 component：

- `source_tree_id/source_node_id` 唯一指向 forest；
- `voxel_index_local_zyx` 等于 source `global_component_mask` 投影到 BOX；
- Find 保存 §7.2 的完整 P/A；unet 只保存 §7.1；
- 不保存 candidate membership、CLG identity 或 selector 字段。

### 7.4 CLG_centered

每个 entry 对应一个成功 CLG，`source_node_id=clg_cover_node_id`。除共同字段外：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `candidate_node_id` | `[N] int32` | 与 `clg.npz` 一致 |
| `candidate_voxel_offsets` | `[N+1] int64` | candidate 对共享 voxel 表的 membership |
| `candidate_voxel_index` | `[L_cv] int32` | 指向 `voxel_index_local_zyx` |
| `candidate_A_offsets` | `[N+1] int64` | Find only；candidate 对共享 A 表的 membership |
| `candidate_A_index` | `[L_ca] int32` | Find only；指向 A 表 |

所有 candidate 共享完整 P 表，不保存 `candidate_P_membership`。不同 candidate 可以交叉引用同一个 voxel/A index；同一 candidate 内 index 唯一。`unet_c1` 只有 voxel membership。

### 7.5 Selected_Refined_Centered

每个 entry 指向一个 source `selected_node`。成功时：

- `voxel_index_local_zyx` 是新的 `refined_blob`；
- `centered_probability`、`voxel_final`、P/A 均来自此次 Selected forward，并与新 blob/当前 BOX 对齐；
- source mask 由 forest 解析，不重复保存；
- 不分配新 tree/node identity。

失败时 entry 仍保留 `centered_box_index`、source tree/node、source threshold、BOX geometry 和 `refine_status`；变长 payload 可为空。至少支持：

```text
success
empty
no_overlap
failed
```

一个 source node 在正式 Selected 目录中最多出现一次。

---

## 8. Selector score 与 selection

实验 selector 输出与正式 centered 产物分开：

```text
selector_outputs/
  {stage1_model_name}/
    {selector_variant}/
      input_pdb_list.json
      calibration.json
      {split}/{pdb_id}/scores.npz
      {split}/{pdb_id}/selection.npz
```

`selector_variant` 是真实配置名，例如 gate/网络消融名，不是无语义 run ID。

`scores.npz` 按 `clg.npz` 顺序保存：

| 字段 | shape / dtype |
|---|---|
| `clg_id` | `[N_clg] int32` |
| `clg_logit` | `[N_clg] float32` |
| `clg_valid_probability` | `[N_clg] float32` |
| `candidate_offsets` | `[N_clg+1] int64` |
| `predicted_max_iou` | `[N_candidate] float32` |
| `selection_logit` | `[N_candidate] float32` |

`selection.npz`：

| 字段 | shape / dtype |
|---|---|
| `clg_id` | `[N_clg] int32` |
| `clg_gate_pass` | `[N_clg] bool` |
| `selected_candidate_offsets` | `[N_clg+1] int64` |
| `selected_candidate_index` | `[N_selected] int16` |

`calibration.json` 保存该 selector BEST 的 `tau_G` 与 calibration fitted 指标。`input_pdb_list.json` 保存 run 启动时实际冻结的 PDB 清单和数量，不计算 hash。

只有用户选定的正式 selector variant 才生产核心目录中的 `Selected_Refined_Centered`；其它消融只保留各自 score/selection 结果。

---

## 9. Runtime 装配边界

Dataset/消费者按模型配置声明的有序 source list 读取字段：

- Find_0：V + P + A(L2/L3/L4)，没有 A-L1；
- Find_1：V + P + A(L1/L2/L3/L4)；
- unet_c1：V only；
- `voxel_aux_probability` 当前不在默认 source list；
- density U-Net 从整图 experimental density现场构造 `exp_clipnorm_nopost`，不读取新的 density-context 文件；
- 四张低分辨率 V 网格在消费模型内部按目标 voxel center 三线性采样；
- residual_swiglu 和 V5+D 的数学定义由推理计划负责，本文只保证字段可读。

缺字段时，如果该 producer 本来不产生该字段，则应选择对应 producer adapter；如果配置声称需要而文件缺失，则输入不完整，不能补零继续。

---

## 10. 冷读不变量与验收

一个不读取训练/推理代码的检查器必须能仅凭目录和本契约验证：

1. split 数量正确、同 PDB 不跨 split、小图不进入 eligible。
2. 每个 pool 起点都在合法范围，bias 第二维为 30，validation 字段使用 `*_pdb_index`。
3. 三个 producer 只使用固定路径寻址，不叠加不透明运行身份，也不重复保存 checkpoint 信息。
4. `probability_map` shape 与 geometry 一致，dtype float32，目录有 `_COMPLETE`。
5. forest 的 parent/children 双向一致、node mask index 不越界且 node 内唯一。
6. clg candidates 均能回到同 tree 的 eligible nodes；cover node 覆盖全部 candidate masks；candidate 数不超过 32（depth1）或 64（depth2）。
7. `n_CLG_rejected_by_node_cap` 只记统计，失败 CLG 不出现在 `clg.npz`。
8. F1/CLG 的权威 voxel 集能回到来源 component；Selected 成功 voxel 集代表 refined blob，失败 entry payload 可为空。
9. `centered_probability`、`voxel_final` 与权威 voxel 数严格相等。
10. 四张低分辨率 V grid shape 固定，feature dtype float16；概率/坐标 float32。
11. Find P/A ragged offsets 合法；Find_0 无 L1；unet 无 P/A；外侧 2 Å 无伪学习特征。
12. CLG candidate memberships 不越界、候选内唯一；P 没有 candidate membership。
13. Selected source tree/node 存在，成功一对一、失败一对零，无新 node ID。
14. selector online oracle 所需的 overlap 足够，但盘上不存在 `q_i/S*/y_G` 缓存。
15. 下游扫描只纳入完整 role；新增未完成 PDB 不会污染已经启动的 selector run。

---

## 11. 磁盘预算与未来容器变化

第一版以 `np.savez_compressed`、FP16 learning features、FP32 probabilities/geometries 为正式选择。25 TB 是 A–G 之外的目标预算；若实测需要 30–35 TB，必须由用户根据效果/吞吐另行接受，不能通过静默改成 FP16 probability、丢源或预先三线性采样来凑预算。

未来若文件数、随机读取或压缩性能要求改用 Zarr/其它容器，只能更换物理包装；本契约的固定身份、字段、解码 shape/dtype、offsets+indices、缺失模态语义和 `_COMPLETE` 原子完成规则不得改变。
