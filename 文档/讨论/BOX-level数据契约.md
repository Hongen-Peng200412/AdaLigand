# AdaLigand BOX 级数据契约

> **本文定位**：本文是 Stage1 训练预定位、完整图概率、组件森林/CLG、三类居中 BOX、selector score 与正式 selection 的盘上唯一权威。它只规定身份、目录、字段、shape、dtype、ragged 关系和完成语义；算法与 loss 见两份 Stage1 规划文档。
>
> **上游**：`文档/规划文档/数据处理_v2.md` 与 `Data_Preprocessing/Ori_Data/README.md` 提供整图密度、受体、标签和 occurrence 资产，到此不切 Stage1 BOX。
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
7. 下游只读取已经原子发布且具有对应 role `_COMPLETE` 标记的产物。

---

## 1. 整图资产与几何

整图资产字段、实际服务器路径和版本以 `Data_Preprocessing/Ori_Data/README.md` 为准。Stage1 依赖的逻辑内容：

| 内容 | 解码 shape / dtype | 作用 |
|---|---|---|
| experimental density | `[1,D,H,W] float32` | 三个 producer；下游 density_input |
| simulated density | `[1,D,H,W] float32` | Find 56D density recipe |
| ligand-area union mask | `[D,H,W] bool` 或等价稀疏表示 | voxel ligand target、语义评估 |
| per-occurrence ligand-area mask | ragged sparse voxel sets | center/bias、instance overlap |
| receptor coordinates | `[N_rec,3] float32` XYZ Å | Dataset 的 core+8 Å查询、centered A-pocket、hardmask |
| receptor feature | `[N_rec,49] float32` | Find raw A input |
| binding atom label | `[N_rec] bool` | A/voxel auxiliary target |
| occurrence identities/coords | ragged | overlap 与评估 |

数组轴恒为 ZYX；世界坐标恒为 XYZ Å。完整网格几何由上游 `origin_xyz` 和 `voxel_size_xyz` 给出，其中 `origin_xyz` 是网格物理下角点，`index_xyz` 处的体素中心为：

$$
origin_{xyz}+(index_{xyz}+0.5)\odot voxel\_size_{xyz}.
$$

所有 BOX 固定 `[80,80,80]`，其起点必须满足：

$$
0\le box\_start_a\le full\_shape_a-80.
$$

因此 BOX 永远是完整真实 crop，不存空间 padding mask。

令 `box_start_xyz=box_start_zyx[[2,1,0]]`、`box_shape_xyz=box_shape_zyx[[2,1,0]]`，则：

$$
box\_origin\_world=origin_{xyz}+box\_start_{xyz}\odot voxel\_size_{xyz},
$$

$$
atom\_coord\_local\_voxel=
\frac{atom\_coord\_world-box\_origin\_world}{voxel\_size_{xyz}},
$$

$$
atom\_coord\_centered\_world=atom\_coord\_world-
\left(box\_origin\_world+\frac12box\_shape_{xyz}\odot voxel\_size_{xyz}\right).
$$

---

## 2. 冻结数据准备契约

### 2.1 split 与边界筛选

推荐布局：

```text
stage1_preparation/
  split/
    train.json
    validation.json
    calibration.json
    held_out_pool.json
    summary.json
```

split 文件的每个条目至少包含 `pdb_id` 与上游 pair identity；同一 PDB 不得跨文件。train 约为总数的 `floor(0.75N)`，validation 恰为 300，calibration 恰为 100，其余进 held-out pool。挑选 validation/calibration 时直接要求完整网格三轴均不小于 80。train 不做独立全量 eligibility 扫描；只有在 BOX pool 预计算中得到真实 80³ crop 的 pair 才产生记录。held-out pool 当前不检查尺寸、不去冗余。

不得创建 `stage1_preparation/eligibility`、eligible/excluded pair 清单或对应独立入口。BOX pool 的普通 `summary.json` 可以记录未产生合法 crop 的计数，但不是另一份排除清单。

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
| `context_start_zyx` | `[N_context,3] int32` | 现有 context 生成器耗尽尝试前产出的全部合法起点；`N_context` 可为 0、1、2 |

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

每个 PDB 最多 50 个 occurrence。若该 PDB 至少有一个合法 context，center:bias:context 的名义条目数为每个入选 occurrence `1:5:3`；context 池只有 1–2 项时有放回选满 3 项，池为空时只保留 `1:5:0`，不得伪造起点或使 pool/训练失败。validation 不保存增强结果。

train-only 同步 90° 旋转若以奇数个 quarter-turn 交换两个数组轴，必须同步交换 `voxel_size_world` 的对应 XYZ 轴尺度，并以新尺度重算 BOX 中心、`atom_coord_world` 与 `atom_coord_centered_world`；不得以“近似 1 Å”替代几何一致性。

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
        _RUNNING/                    # 仅运行时暂存的 PDB 级原子 mkdir 锁
        _BLOB_EXCEED                 # 可选，与正常下游完成互斥的 JSON 终态
        status/
          {output_role}/_COMPLETE
        probability/
        components/
        centered/
          F1_centered.npz
          CLG_centered.npz
          Selected_Refined_Centered.npz
```

`stage1_model_name` 只取 `Find_0`、`Find_1`、`unet_c1`。每个居中 BOX 的逻辑键固定为：

```text
(stage1_model_name, split, pdb_id, centered_role, centered_box_index)
```

`output_role` 表示可独立原子发布和续跑的一类 Stage1 产物，只取：`probability`（完整图概率与几何）、`components`（forest、CLG、overlap 与摘要）、`F1_centered`（F1 阈值节点居中的观察结果）、`CLG_centered`（成功 CLG 的 oldest node 居中结果）、`Selected_Refined_Centered`（selector 选中节点重新定形后的结果）。没有额外概率/组件/物化 run ID。正式 producer 更换 checkpoint 时，应由执行者显式清理或归档该 producer 的旧未用输出后重跑；不能在同一正式目录混入两套 checkpoint。

### 3.2 原子完成

worker 可先只读检查目标 role；仍有工作时，对 PDB 根原子 `mkdir _RUNNING`，成功者重新检查各 role 后顺序补齐，其他 worker 立即跳过。每个 role 写独立临时文件，关闭数组并完成基本校验后以原子 rename/replace 发布，最后写 `status/{output_role}/_COMPLETE`。持有者必须在 `finally` 中移除自己的 `_RUNNING`。消费者忽略：

- 没有对应 role `_COMPLETE` 的产物；
- `_RUNNING` PDB、临时文件与任何未发布内容；
- offsets 越界或字段不完整的 role 文件。

`probability`、`components` 和三种 centered role 分别完成；因此 F1 可以早于 CLG/Selected 被消费。若正式 `N_F1_eligible>200`，保留 probability 及其 `_COMPLETE`，写 `_BLOB_EXCEED` JSON，至少含 `N_F1_eligible` 与 `limit=200`；不写 components/centered `_COMPLETE`。`_BLOB_EXCEED` 是普通重跑必须跳过、下游不得消费的明确终态。异常遗留 `_RUNNING` 或临时文件只由显式运维工具按所有者/年龄清理，不由科学 runner 猜测。

---

## 4. 完整图概率与 calibration 表

### 4.1 probability

```text
probability/
  probability_map.npz
  geometry.json
```

`probability_map.npz`：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `probability_map` | `[D,H,W] float32` | Gaussian 融合并完成 producer-specific 后处理后的正式 ligand probability；两个 Find 在 full-grid receptor hardmask 处为 0，unet 不遮蔽 |

`geometry.json` 只保存解析该数组所需的 `full_shape_zyx`、`origin_xyz`、`voxel_size_xyz`、window shape 80、stride 40、Gaussian sigma 0.5 和 `contract_version`。不复制 checkpoint 路径，不保存 full-map V/P/A。

### 4.2 thresholds

每个 producer 的 `calibration/thresholds.json`：

```text
stage1_model_name
denominator                  # 32768
alpha_values                 # [1/2,2/3,4/5,1,5/4,3/2,2]
alpha_threshold_grid_index   # [7]，逐 alpha 实际扫描整数 j
t_alpha                      # [7]，逐项等于 j/32768
t_F1
min_voxels                   # 32
max_voxels                   # 1023；全量 GT occurrence Q95=682 后乘 1.5 并向上取整
connectivity                 # 26
```

`alpha_values`、`alpha_threshold_grid_index` 与 `t_alpha` 严格逐项对齐；`t_F1` 是 alpha=1 对应项。组件 runtime 对实际 `j` 去重并按降序使用，重复 alpha 阈值自然只形成 `7-k` 层。`metrics.json` 保存 calibration-fitted 指标与扫描曲线引用。阈值表不重复写入每个 PDB，也不保存 `physical_threshold_values`、`alpha_to_threshold_index` 或另一套 R/K 映射。

---

## 5. Component forest 与 CLG

```text
components/
  forest.npz
  clg.npz
  overlap.npz                # train/validation/calibration 有 GT 时
  summary.json
```

### 5.1 forest.npz

设总 node 数为 `N_node`，全部 node voxel index 拼接长度为 `L_voxel`，children 拼接长度为 `L_child`：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `tree_id` | `[N_node] int32` | 当前 PDB 内树 identity |
| `node_id` | `[N_node] int32` | 对应 tree 内 node identity |
| `threshold_grid_index` | `[N_node] int32` | 实际扫描整数 `j∈[0,32768]`；同一层相同 |
| `threshold_value` | `[N_node] float32` | `threshold_grid_index/32768`，便于冷读 |
| `parent_node_id` | `[N_node] int32` | direct parent；root 为 `-1` |
| `children_offsets` | `[N_node+1] int64` | 切分 `children_node_id`；第 i 个 node 的 direct children 为对应半开区间 |
| `children_node_id` | `[L_child] int32` | 与本 node 同 tree 的 child IDs |
| `node_voxel_offsets` | `[N_node+1] int64` | 切分 `node_voxel_global_linear_index`；每段是一个 node mask |
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

设成功 CLG 数 `N_CLG`，flatten 后 candidate 数 `N_candidate`：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `CLG_id` | `[N_CLG] int32` | 当前 PDB 内连续本地 identity；即来源顺序 |
| `tree_id` | `[N_CLG] int32` | 所属原树 |
| `CLG_seed_node_id` | `[N_CLG] int32` | 本次枚举开始时唯一 selected seed 的 forest node ID |
| `CLG_oldest_node_id` | `[N_CLG] int32` | 候选中沿低阈值方向最老、mask 覆盖全部候选的唯一 node ID |
| `candidate_offsets` | `[N_CLG+1] int64` | 切分 `candidate_node_id` 与 `candidate_threshold_grid_index`；第 g 个 CLG 对应 `[offsets[g],offsets[g+1])` |
| `candidate_node_id` | `[N_candidate] int32` | 原 forest node identity |
| `candidate_threshold_grid_index` | `[N_candidate] int32` | 对应 forest node 的扫描整数 `j`，便于批读取 |

失败或因 node cap 拒绝的尝试不进入该文件。`summary.json` 至少保存 depth 配置和以下字段：

| 字段 | 语义 |
|---|---|
| `n_f1_eligible_seeds` | `t_F1` 层满足 candidate 资格、进入工作树初始 seed 集的节点数 |
| `n_CLG_cap` | 本 PDB 允许成功发布的 CLG 上限 `min(300,3*max(2,n_f1_eligible_seeds))` |
| `n_CLG_completed` | 实际成功发布的 CLG 数，必须等于 `N_CLG` |
| `n_CLG_rejected_by_node_cap` | 因一次原子扩展会超过当前 depth 节点上限而整次拒绝的 CLG 尝试数 |
| `mean_candidates_per_completed_CLG` | 全部成功 CLG 的 candidate 数均值；没有成功 CLG 时为 0.0 |
| `CLG_cap_reached` | 仅当仍有 active seeds，却因 `n_CLG_completed=n_CLG_cap` 提前停止时为 true；自然恰好完成相同数量不算 reached |

祖先、LCA、姐妹和 antichain conflict 从 `forest.npz` 现场计算，不重复保存 NxN 关系表。

### 5.3 overlap.npz

这是 selector online oracle 的基础事实，不是持久 oracle。按 `clg.npz` flatten 后的 candidate 顺序，保存 candidate 与 occurrence 的非零交集：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `candidate_occurrence_offsets` | `[N_candidate+1] int64` | 同时切分 `overlap_occurrence_index` 与 `intersection_voxel_count`；每段是一个 candidate 的非零相交 occurrence |
| `overlap_occurrence_index` | `[N_overlap] int32` | 指向下述 `occurrence_id[N_gt]` 的当前 PDB 局部行号，取值范围 `[0,N_gt)`；不是 occurrence identity 本身 |
| `intersection_voxel_count` | `[N_overlap] int32` | 全图 candidate mask 与 GT mask 交集 |
| `occurrence_id` | `[N_gt] int32` | 当前 PDB 全部 GT identities |
| `occurrence_voxel_count` | `[N_gt] int32` | 各 GT mask 大小 |

candidate voxel count 从 forest 读取，因此可现场求 IoU。`q_i`、`S*`、`y_G`、lambda 专属标签和反链结果不得写入本文件。

---

## 6. Centered BOX 的物理组织

### 6.1 每 role 一个聚合文件

每个 producer/split/PDB 的 `centered/` 最终只保存：

```text
F1_centered.npz
CLG_centered.npz
Selected_Refined_Centered.npz
```

三者是时间上独立的原子发布单元；没有 `index.npz+part_*.npz`，也不按 BOX 生成小文件。每个文件以 entry 主表加 ragged value 表容纳当前 PDB 的全部同类 BOX。共同 entry 字段：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `centered_box_index` | `[N_entry] int32` | 文件内连续 `0..N_entry-1` |
| `box_start_zyx` | `[N_entry,3] int32` | 已解析合法起点，数组顺序 ZYX |
| `box_shape_zyx` | `[N_entry,3] uint8` | 固定 `[80,80,80]` |
| `box_origin_world` | `[N_entry,3] float32` | 当前 BOX 物理下角点，XYZ Å |
| `voxel_size_world` | `[N_entry,3] float32` | XYZ Å/voxel |
| `source_tree_id` | `[N_entry] int32` | 来源 forest tree |
| `source_node_id` | `[N_entry] int32` | F1 source、CLG oldest 或 Selected source node |
| `source_threshold_grid_index` | `[N_entry] int32` | 来源 node 的扫描整数 `j` |
| `source_threshold_value` | `[N_entry] float32` | `j/32768` |

`CLG_centered.npz` 另有 `CLG_id[N_entry] int32`、`CLG_seed_node_id[N_entry] int32`、`CLG_oldest_node_id[N_entry] int32`。F1 不伪造 CLG 字段。Selected 另有 `refine_status[N_entry] uint8` 与 `feature_entry_index[N_feature] int32`；前者固定映射为 `0=success`、`1=empty`、`2=no_overlap`、`3=failed`，后者必须逐项等于 `refine_status=0` 的 entry 行号，不另造每 BOX 状态文件。各值的行为定义见 §7.5。

### 6.2 通用 ragged 编码

每个聚合 NPZ 的每类变长实体都使用 `offsets + values`：

```text
voxel_offsets[N_entry+1]                    # 同时切分 voxel_index/centered_probability/voxel_final
voxel_index_local_zyx[L_voxel,3]

P_offsets[N_entry+1]                        # 同时切分全部 P_* values
P_...

A_offsets[N_entry+1]                        # 同时切分全部 A_* values
A_...
```

同一 entry 内 index 唯一。offsets 为 int64、首项为 0、末项等于所切分 value 表长度并单调不减。`voxel_index_local_zyx` 是当前 role 的权威 voxel 集，结合对应 entry 的 `box_start_zyx` 可恢复全图 ZYX。固定 shape 的低分辨率 V grid 不使用 offsets：F1/CLG 直接以 `N_entry` 为第一维；Selected 以 `N_feature` 为第一维，并由 `feature_entry_index` 映射到成功 entry，不能为失败状态伪造全零网格。

---

## 7. 三类 Centered payload

### 7.1 共同 voxel 字段

设 `voxel_offsets` 的末项为 `L_voxel`，`voxel_aux_offsets[N_entry+1]` 切分两个 `voxel_aux_*` value 表且末项为 `L_aux`。令 `N_Ventry=N_entry`（F1/CLG），而 Selected 的 `N_Ventry=N_feature`。所有成功 entry 的共同字段：

| 字段 | shape / dtype | 对齐对象 |
|---|---|---|
| `voxel_offsets` | `[N_entry+1] int64` | 同时切分下面三个长度 `L_voxel` 的 value 表 |
| `voxel_index_local_zyx` | `[L_voxel,3] int16` | 各 entry 当前权威 voxel 集 |
| `centered_probability` | `[L_voxel] float32` | 居中 forward 在相同 voxel 行的 ligand probability |
| `voxel_final` | `[L_voxel,48] float16` | 与相同 voxel 行对齐的 producer final feature |
| `voxel_ds_2` | `[N_Ventry,256,20,20,20] float16` | 每个成功 feature entry 一张 native low-resolution grid |
| `voxel_ds_3` | `[N_Ventry,256,10,10,10] float16` | 每个成功 feature entry 一张 native low-resolution grid |
| `voxel_ds_4` | `[N_Ventry,256,5,5,5] float16` | 每个成功 feature entry 一张 native low-resolution grid |
| `voxel_c4` | `[N_Ventry,256,5,5,5] float16` | 每个成功 feature entry 一张 native bottleneck grid |
| `voxel_aux_offsets` | `[N_entry+1] int64` | 同时切分两个长度 `L_aux` 的 auxiliary value 表 |
| `voxel_aux_index_local_zyx` | `[L_aux,3] int16` | hardmask 唯一 receptor home voxels |
| `voxel_aux_probability` | `[L_aux] float32` | 与相同 auxiliary voxel 行对齐的 sigmoid probability |

不保存 dense final 48D grid、稠密 centered ligand probability、threshold rank map 或按 K_v 重复的低分辨率预采样特征。

`centered_probability` 已完成与完整图相同的 producer-specific 后处理：两个 Find 在当前 BOX hardmask home voxels 为 0，unet_c1 不使用 receptor hardmask。该字段不能再由消费者二次遮蔽。

### 7.2 Find 的 P 与 A 字段

设 `P_offsets[N_entry+1]` 切分全部 P value 表，末项为 `L_P`。Find 的 P 表：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `P_offsets` | `[N_entry+1] int64` | 同时切分本表全部 `P_*` value 数组；第 e 段是 entry e 的完整 P 表 |
| `P_coord_local_xyz` | `[L_P,3] float32` | 当前 80³ BOX 内连续 XYZ voxel 坐标 |
| `P_probability` | `[L_P] float32` | `sigmoid(P_logit)`，与 P 行逐项对齐 |
| `P_feat_L2` | `[L_P,C_P2] float16` | density/class/interface normalization 后、进入 point backbone 的 P 初始表示 |
| `P_feat_L3` | `[L_P,C_P3] float16` | A/P interaction 前的 P 表示 |
| `P_feat_L4` | `[L_P,C_P4] float16` | interaction 后且送入 P head 的 P 表示 |

P 字段语义固定为：L2 是 pseudo-density feature 完成 density/class/interface normalization 后的表示；L3 是 A/P interaction 前表示；L4 是 interaction 后、P head 输入；`P_probability=sigmoid(P_logit)`。

设 `A_offsets[N_entry+1]` 切分全部 A value 表，末项为 `L_A`。每个 entry 的 A 集合是“该 entry 来源 blob 的 10 Å包络 ∩ 当前 80³ BOX”内的 receptor atoms；不含 BOX 外原子。两个 Find 都保存：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `A_offsets` | `[N_entry+1] int64` | 同时切分本表全部 `A_*` value 数组；第 e 段是 entry e 的 A-pocket |
| `A_global_index` | `[L_A] int64` | 指向当前 PDB 唯一 receptor 表的原子行，用于无损恢复 49D `A_feat_L0` |
| `A_coord_local_xyz` | `[L_A,3] float32` | 当前 80³ BOX 内连续 XYZ voxel 坐标 |
| `A_coord_centered_world` | `[L_A,3] float32` | 以当前 BOX 物理中心为原点的 XYZ Å 坐标 |
| `A_probability` | `[L_A] float32` | `sigmoid(A_logit)`，与 A 行逐项对齐 |
| `A_feat_L1` | `[L_A,C_A1] float16` | point-side embed 后、real-atom density-cube 调制前的 A 表示 |
| `A_feat_L2` | `[L_A,C_A2] float16` | L1 与原子 density-cube 编码 combine 后、进入 point backbone 的 A 表示 |
| `A_feat_L3` | `[L_A,C_A3] float16` | A/P interaction 前的 A 表示 |
| `A_feat_L4` | `[L_A,C_A4] float16` | interaction 后且送入 A head 的 A 表示 |

`A_feat_L1` 是 point-side embed 后、进入 density/point backbone 前的表示；L2 是 embed 与 point density 组合后、实际送入 point backbone的表示；L3 是 A/P interaction 前表示；L4 是 interaction 后、A head 输入；`A_probability=sigmoid(A_logit)`。正式消费时另按 `A_global_index` 从每 PDB 唯一 receptor 49D 表读取 `A_feat_L0[L_A,49] float32`；L0 不在 centered NPZ 重复落盘。`unet_c1` 不保存任何 P/A 字段。

### 7.3 F1_centered

每个 entry 对应一个 eligible F1 component：

- `source_tree_id/source_node_id` 唯一指向 forest；
- `voxel_index_local_zyx` 等于 source `global_component_mask` 投影到 BOX；
- Find 保存 §7.2 的完整 P/A；unet 只保存 §7.1；
- 不保存 candidate membership、CLG identity 或 selector 字段。

### 7.4 CLG_centered

每个 entry 对应一个成功 CLG，`source_node_id=CLG_oldest_node_id`。除共同 entry 字段及 `CLG_id/CLG_seed_node_id/CLG_oldest_node_id` 外，设当前文件所有 candidates flatten 后为 `N_candidate`：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `candidate_offsets` | `[N_entry+1] int64` | 切分 `candidate_node_id` 与 `candidate_threshold_grid_index`；每个 entry 对应一段 candidates |
| `candidate_node_id` | `[N_candidate] int32` | 与来源 `clg.npz` 同顺序的 forest node ID |
| `candidate_threshold_grid_index` | `[N_candidate] int32` | 每个 candidate 的实际扫描整数 `j` |
| `candidate_voxel_offsets` | `[N_candidate+1] int64` | 切分 `candidate_voxel_index`；每段是该 candidate 对其 entry voxel 段的局部 membership |
| `candidate_voxel_index` | `[L_cv] int32` | 指向所属 entry 的 `voxel_index_local_zyx` 局部行 |
| `candidate_A_offsets` | `[N_candidate+1] int64` | Find only；切分 `candidate_A_index` |
| `candidate_A_index` | `[L_ca] int32` | Find only；指向所属 entry A 段的局部行 |

所有 candidate 共享完整 P 表，不保存 `candidate_P_membership`。不同 candidate 可以交叉引用同一个 voxel/A index；同一 candidate 内 index 唯一。`unet_c1` 只有 voxel membership。

### 7.5 Selected_Refined_Centered

每个 entry 指向一个 source `selected_node`。成功时：

- `voxel_index_local_zyx` 是新的 `refined_blob`；
- `centered_probability`、`voxel_final`、P/A 均来自此次 Selected forward，并与新 blob/当前 BOX 对齐；
- source mask 由 forest 解析，不重复保存；
- 不分配新 tree/node identity。

每个状态的数值与语义固定为：

- `0=success`：阈值化后至少有一个局部组件与投影后的 source mask 具有正交集；选取 IoU 最大者作为新的 `refined_blob` 并保存完整 payload。
- `1=empty`：阈值化后没有任何局部组件；保留来源与 BOX 几何，全部变长 payload 为空。
- `2=no_overlap`：存在局部组件，但它们与投影后的 source mask 交集全为 0；不把无关局部组件误认作精修结果，变长 payload 为空。
- `3=failed`：该 source 的 forward、组件构造或必要校验执行失败；保留来源与 BOX 几何，变长 payload 为空，错误细节写当前运行日志/汇总而不是 object array。

一个 source node 在正式 Selected 目录中最多出现一次。

`feature_entry_index` 必须严格升序且精确等于全部 `refine_status=0` 的 entry 行。四张固定 V grid 逐行与它对齐；后三种非成功状态不得占固定网格行。全部 ragged offsets 仍保持 `[N_entry+1]`，非成功 entry 的 voxel/aux/P/A 段都为空。

---

## 8. Selector score 与 selection

实验 selector 输出与正式 centered 产物分开：

```text
selector_outputs/
  {stage1_model_name}/
    {selector_variant}/
      {selector_run_dir}/
        input_CLG_list.json
        calibration.json
        {split}/{pdb_id}/scores.npz
        {split}/{pdb_id}/selection.npz
```

`selector_variant` 是真实网络/条件损失配置名；`selector_run_dir` 是一次训练的独立输出目录，不允许通过共享 `latest` 清单改变其输入。`input_CLG_list.json` 按固定顺序至少记录 `stage1_model_name`、`split_order`、`pdb_ids_by_split`、`split_pdb_counts`、逐 `(split,pdb_id,CLG_id)` 的 `items` 和对应 `split_counts`。`pdb_ids_by_split` 是完整已发布 PDB inventory；合法的零 CLG PDB 保留在这里但不伪造 item。只允许同一 producer 的其它 selector 方案显式复用。指定清单中的任一 PDB、CLG 缺失或未完成都必须在训练前报告，不能静默取交集；正式 validation 完整性按 PDB inventory 而不是非空 CLG item 判断。

`scores.npz` 按 `clg.npz` 顺序保存：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `CLG_id` | `[N_CLG] int32` | 当前 producer/split/PDB 内的 CLG 本地身份；值和顺序与来源 `clg.npz` 逐项一致 |
| `CLG_logit` | `[N_CLG] float32` | Selector 对“该 CLG 是否含值得结构化选择的候选”的未归一化 readout `a_G` |
| `CLG_valid_probability` | `[N_CLG] float32` | `sigmoid(CLG_logit)=p_G`；只用于 CLG 门控与 `tau_G` 扫描 |
| `candidate_offsets` | `[N_CLG+1] int64` | 逐元素复制来源 offsets，同时切分 `predicted_max_iou` 与 `selection_logit` |
| `predicted_max_iou` | `[N_candidate] float32` | `qhat_i∈[0,1]`；由 `E_i^content` 回归的候选最大 GT IoU，用于 `L_blob`、top-K 与质量报告 |
| `selection_logit` | `[N_candidate] float32` | `z_i`；由 `E_i^tree` 产生的结构化选择能量，只进入反链 DP，不是概率或候选质量分 |

`CLG_id` 必须与来源 `clg.npz` 完全同序；`CLG_logit=a_G` 是 CLG readout 原始值，`CLG_valid_probability=sigmoid(a_G)=p_G` 用于门控与 `tau_G` 扫描。`candidate_offsets` 必须逐元素复制来源 offsets，同时切分两个 candidate value 表。`predicted_max_iou=qhat_i∈[0,1]` 由 tree Transformer 前的 `E_i^content` 产生，用于 `L_blob`、top-K 与质量报告；`selection_logit=z_i` 由 `E_i^tree` 产生，只用于反链能量，不是概率或质量分。

`selection.npz`：

| 字段 | shape / dtype | 语义 |
|---|---|---|
| `CLG_id` | `[N_CLG] int32` | 与同 PDB `scores.npz` 和来源 `clg.npz` 完全同序的 CLG 本地身份 |
| `CLG_gate_pass` | `[N_CLG] bool` | 冻结阈值下 `CLG_valid_probability≥tau_G`；通过才允许非空预测 MAP |
| `selected_candidate_offsets` | `[N_CLG+1] int64` | 切分 `selected_candidate_index`；第 g 段是该 CLG 的最终选择 |
| `selected_candidate_index` | `[N_selected] int16` | 所属 CLG candidate 段内的局部下标；按来源 candidate 原顺序保存，不是 forest node ID |

`CLG_gate_pass` 表示 `CLG_valid_probability≥tau_G`；通过时必须保存精确 DP 的非空预测 MAP 反链，失败时该 CLG 对应空段。`selected_candidate_offsets` 切分 `selected_candidate_index`；每个 selected index 是所属 CLG candidate 段内的局部下标，按来源 candidate 原始顺序保存。对 CLG 行 `g` 的局部下标 `k`，绝对 candidate 行为 `candidate_offsets[g]+k`，再由该行 `candidate_node_id` 恢复 forest node。

零 CLG PDB 仍发布 `CLG_id.shape=(0,)`、`candidate_offsets=[0]` 的空 `scores.npz`，以及相应字段完整的空 `selection.npz`。同一 `(tree_id,node_id)` 可以出现在多个 CLG 的 selection 段；恢复下游 Selected source 时按 CLG/来源顺序有序去重。校正统计对该 node 只计一次，门控概率取所有选中它的 CLG 的最大 `CLG_valid_probability`。

`calibration.json` 保存 validation total loss 选出的 selector BEST 对应的 `tau_G`、从该 run `resolved_config.yaml` 读取的 `lambda_count` 与 calibration-fitted 指标。顺序固定为 BEST → calibration scores/`tau_G` → 所需 split selections；calibration 不另收一份 lambda 参数，也不反选 checkpoint 或方案。零 CLG PDB 以零预测和真实 GT 进入指标。

只有用户选定的正式 selector variant 才生产核心目录中的 `Selected_Refined_Centered`；其它消融只保留各自 score/selection 结果。

---

## 9. Runtime 装配边界

Dataset/消费者按模型配置声明的有序 source list 读取字段：

- Find_0：V + P(L2/L3/L4) + A(L0/L1/L2/L3/L4)；
- Find_1：V + P(L2/L3/L4) + A(L0/L1/L2/L3/L4)；
- unet_c1：V only；
- `voxel_aux_probability` 当前不在默认 source list；
- `A_feat_L0` 按 `A_global_index` 从每 PDB 49D receptor 表读取，其余 A/P learning features 来自 centered NPZ；
- DensityMUNetLite 从整图 experimental density 现场构造 `exp_clipnorm_nopost`，不读取新的 density-context 文件；
- 四张低分辨率 V 网格在消费模型内部按目标 voxel center 三线性采样；
- residual_swiglu 和 V5+D 的数学定义由推理计划负责，本文只保证字段可读。

缺字段时，如果该 producer 本来不产生该字段，则应选择对应 producer adapter；如果配置声称需要而文件缺失，则输入不完整，不能补零继续。

---

## 10. 冷读不变量与验收

一个不读取训练/推理代码的检查器必须能仅凭目录和本契约验证：

1. split 数量正确、同 PDB 不跨 split；validation/calibration 三轴均不小于 80，train pool 只有真实 80³ crop，且不存在独立 eligibility 目录。
2. 每个 pool 起点都在合法范围，bias 第二维为 30，validation 字段使用 `*_pdb_index`。
3. 三个 producer 只使用固定路径寻址，不叠加不透明 Stage1 运行身份，也不重复保存 checkpoint 信息。
4. `probability_map` shape 与 geometry 一致、dtype float32，对应 role 有 `_COMPLETE`；Find 已做 hardmask 后处理，unet 未做。
5. forest 的 parent/children 双向一致、node mask index 不越界且 node 内唯一。
6. CLG candidates 均能回到同 tree 的 eligible nodes；唯一 seed/oldest node 可恢复，oldest mask 覆盖全部 candidate masks；candidate 数不超过 32（depth1）或 64（depth2）。
7. `n_CLG_rejected_by_node_cap` 只记统计，失败 CLG 不出现在 `clg.npz`。
8. F1/CLG 的权威 voxel 集能回到来源 component；Selected 成功 voxel 集代表 refined blob，失败 entry payload 可为空。
9. `centered_probability`、`voxel_final` 与权威 voxel 数严格相等。
10. 三个 role 都是单个聚合 NPZ；所有 offsets 明确切分的 value 表且合法；四张低分辨率 V grid shape 固定，feature dtype float16，概率/坐标 float32。
11. Find P/A ragged offsets 合法；两个 Find 均有 A_feat_L1–L4 且 A_global_index 可恢复 L0；unet 无 P/A；BOX 外无伪学习特征。
12. CLG candidate memberships 不越界、候选内唯一；P 没有 candidate membership。
13. Selected source tree/node 存在，成功一对一、失败一对零，无新 node ID。
14. selector online oracle 所需的 overlap 足够，但盘上不存在 `q_i/S*/y_G` 缓存。
15. 下游扫描只纳入完整 role；`_RUNNING` 不可读，`_BLOB_EXCEED` 不可训练/普通重跑；新增未完成 PDB 不会污染已经冻结 `input_CLG_list.json` 的 selector run。

---

## 11. 磁盘预算与未来容器变化

第一版以 `np.savez_compressed`、FP16 learning features、FP32 probabilities/geometries 为正式选择。25 TB 是 A–G 之外的目标预算；若实测需要 30–35 TB，必须由用户根据效果/吞吐另行接受，不能通过静默改成 FP16 probability、丢源或预先三线性采样来凑预算。

未来若文件数、随机读取或压缩性能要求改用 Zarr/其它容器，只能更换物理包装；本契约的固定身份、字段、解码 shape/dtype、offsets+indices、缺失模态语义和 `_COMPLETE` 原子完成规则不得改变。
