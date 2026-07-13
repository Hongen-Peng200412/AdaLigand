# AdaLigand A–G 代码阅读指南

这是一份面向新手工程师和没有上下文的 AI agent 的代码阅读地图。它解释三个问题：

1. 一个文件主要属于哪一种实际逻辑；
2. 正式 A–G 流水线从哪个入口进入、依次调用什么；
3. 哪些代码决定科学数据，哪些代码只是工具连接、检查、事故恢复或服务器运维。

本文只描述代码结构和当前契约，不修改代码，也不授权重新运行服务器任务。仓库根目录是当前文件所在的项目根；文中路径均使用仓库相对路径。

## 1. 最重要的分类方法

代码主体只分成三类。入口代码不是第四类，而是一层“导航层”：它像指针一样，把命令行参数、资源参数和 `run_id` 交给下面三类真正的逻辑。

### 1.1 核心科学逻辑

这类代码决定数据的科学含义、坐标/距离/特征计算、质量指标或过滤规则。阅读它时要回答：输入是什么、输出数组是什么、单位和轴顺序是什么、公式或判定条件是什么。

### 1.2 工具调用和适配层

这类代码把 AdaLigand 的数据转换成 Chimera、MapQ、MRC、RCSB/EMDB 等外部系统能接受的输入，再把外部结果严格转换回来。它通常不重新发明 CC、Q-score 或 Pocket Plus 的数值算法。

### 1.3 防御性、事故修复和一次性运维

这类代码负责验证、失败分类、原子写入、release gate、锁、审计、回归 smoke、source repair 和一次性恢复。它们保护核心逻辑不被错误产物污染，但通常不是训练数据的科学定义本身。

### 1.4 入口/指针层（不作为第四类）

入口文件通常只做参数解析、环境准备、并发编排、调用模块和退出码传播。看到入口后，沿着它的 `import` 和函数调用继续跳到三类实际逻辑。

判断一个文件是不是入口的最直接方法：如果它主要包含 `argparse`、`main()`、`sbatch`、环境变量、`joblib.Parallel`、阶段调用和 gate 调用，而不是实现数学函数，那么它就是入口/编排层。

入口层与三类逻辑的关系如下：

```text
入口/指针
  └─ 调用核心科学逻辑
  └─ 调用工具适配层
  └─ 调用防御性 gate / 报告 / 锁逻辑
```

因此，`scripts/f_quality.py` 是 F 阶段入口；真正的质量计算在 `code/quality.py`，Chimera/MapQ 连接在 `code/chimera.py` 和 `code/mapq.py`，质量验证在 `code/qc.py`。

## 2. 当前正式主路径

正式 A–G DAG 的入口关系是：

```text
sbatch/abc_full.sbatch
  ├─ scripts/a_guard.py
  ├─ scripts/b_download.py
  ├─ scripts/c_parse.py
  └─ scripts/abc_release_gate.py

sbatch/de_full.sbatch
  ├─ scripts/d_atom_labels.py
  ├─ scripts/e_density.py
  └─ scripts/stage_release_gate.py

sbatch/f_full.sbatch
  ├─ scripts/f_quality.py
  └─ scripts/stage_release_gate.py

sbatch/g_analyze.sbatch
  └─ scripts/g_filter.py --mode analyze
```

当前正式科学范围是 A–G；不包含 Stage 1 重训、BOX 第 2/3 层或 Stage 2/3。

一个样本的大致数据流是：

```text
A pair_list
  → B 原始 mmCIF / EMDB map / metadata
  → C occurrences + ligand_coords + receptor_tokens + LigandObject/descriptor
  → D receptor atom labels
  → E exp/sim/ligand_area density artifacts
  → F 四种 CC + ligand Q + 6 Å pocket Q
  → G quality distribution / pending candidates
```

`G --mode analyze` 不猜阈值，也不写最终 `keep_list.jsonl`。只有用户明确提供带哈希的过滤配置时，才进入正式过滤。

## 3. 核心科学逻辑：`code/`

### 3.1 Stage C：结构、配体和受体

| 文件 | 核心问题 | 主要输入 | 主要输出 |
|---|---|---|---|
| `code/parse.py` | 如何从 mmCIF 得到一次 PDB 的结构视图 | `raw/rcsb_mmcif/{pdb}.cif`、CCD cache | `occurrences.jsonl`、`ligand_coords.npz`、受体数组、报告 |
| `code/ligand_object.py` | 如何得到去重的化学对象 | CCD 模板、结构中的配体身份 | `ligand_objects/{object_key}.npz` |
| `code/ligand_descriptors.py` | 如何从化学图计算描述子 | LigandObject 的原子和键 | `ligand_descriptors/{object_key}.npz` |
| `code/receptor.py` | 如何构造受体原子、键和特征 | polymer 原子、CCD/`_struct_conn` | 受体 token、`bond_index`、`bond_type`、`feat(N,49)` |
| `code/constants.py` | 所有编码和固定数值是什么 | 无 | 元素、残基、键类型、半径和 schema 常量 |

`parse.py` 的关键概念：

- `occurrence` 是结构中一次实际出现的配体整体；同一个 CCD 可以在同一个 PDB 中出现多次。
- `candidate_id` 是该 PDB 在当前冻结 mmCIF source 中按稳定排序得到的 0 起编号，不是跨 source 永久不变的 accession。
- `ligand_objects` 保存去重化学模板；`ligand_coords.npz` 保存这一次 occurrence 的真实沉积坐标。
- 配体模板原子行序、`coords_{cid}`、`present_{cid}` 必须严格对齐。
- `coords` 是世界坐标 XYZ Å；缺失模板原子为 `NaN`，由 `present=False` 标记。

`ligand_object.py` 中要特别区分三套坐标：

1. `atoms["coords"]`：占位字段，通常是零，不是真实 pose；
2. `atoms["ref_pos"]`：CCD/RDKit 参考构象；
3. `ligand_coords.npz` 的 `coords_{candidate_id}`：结构中的真实沉积坐标，后续 D/E/F 使用这一套。

受体键类型的当前编码保留旧值 `0–5`，并向后兼容追加合法三键 `triple=6`；不能把未知键型默默映射成普通键。

### 3.2 Stage D：原子标签

文件：`code/atom_labels.py`

输入：

- C 的受体原子数组；
- 每个 occurrence 的真实配体坐标；
- `present=True` 的配体重原子；
- 默认距离阈值 `4.0 Å`。

对每个受体原子，代码计算它到所有 present 配体重原子的最近距离：

$$
d_i = \min_j \lVert r_i - l_j \rVert_2
$$

当 $d_i \le 4.0$ 时，`binding_atom=True`；否则为背景。最近的 occurrence 得到 `instance_id`，背景为 `-1`。完全等距时按较小 `candidate_id` 和稳定行号决胜。

输出 `labels/{pdb_id}/atom_labels.npz`：

- `binding_atom (N_rec,) bool`；
- `instance_id (N_rec,) int32`；
- `nearest_dist (N_rec,) float32`；
- 输入哈希、阈值和 schema 信息。

这里的标签是受体原子级标签，不是体素标签，也不是候选样本过滤结果。

### 3.3 Stage E：密度和体素区域

主要文件：`code/density.py`。它是“核心科学编排 + 外部 Chimera 调用”的混合模块。

#### E1：实验密度图

输入：原始 EMDB MRC map。

处理：使用 Pocket Plus 祖传 MRC 原语生成 canonical grid，正式目标体素大小为 `1.0 Å`，但输出网格必须保存函数实际返回的 XYZ voxel；不能强行把实际 voxel 声明成精确 `1.0`。

输出 `density/{pdb_id}/exp.npz`：

- `grid (1,Z,Y,X) float32`；
- `voxel_size (3,)`，顺序是 XYZ；
- `origin (3,)`，世界坐标 XYZ Å；
- native/even/canonical shape；
- contour、幅值缩放和 MRC lineage provenance。

数组轴是 ZYX，但空间坐标和 voxel 元数据是 XYZ。这是阅读 MRC 代码时最容易混淆的地方。

#### E2：受体模拟密度图

输入：规范化后的结构模型和 E1 canonical grid。

受体-only 模拟图严格删除全部 `HETATM`，只保留 `group_PDB==ATOM` 的受体重原子。Chimera 使用 `molmap ... onGrid` 在 E1 网格上直接生成模拟图，不进行第二次独立重采样。

必须验证：

- `exp.grid.shape == sim.grid.shape == (1,Z,Y,X)`；
- sim 读取后是真正三维，不是二维切片；
- shape、实际 voxel、origin 逐项匹配 E1；
- 数组有限、非零、有方差；
- 网格世界范围与受体坐标包围盒相交。

#### E3：ligand-area

输入：E1 网格和每个 occurrence 的真实配体原子坐标。

代码用逐原子局部 voxel stencil 生成 mask，不构造整个大网格的世界坐标 KD-tree。不同元素使用不同 vdW 半径；输出包含：

- `union_mask (1,Z,Y,X) bool`；
- `mask_{cid} (K,3) int32`，索引轴为 ZYX；
- `centroid_voxel_{cid} (3,) float32`，数值是世界 XYZ Å。

### 3.4 Stage F：CC、配体 Q 和口袋 Q

主要文件：`code/quality.py`。

#### 四种 CC

四个原始量必须全部保存：

| 字段 | mask | 是否在 mask 内减均值 |
|---|---|---|
| `cc_contour` | 实验图高于 canonical contour 的点 | 否 |
| `cc_contour_about_mean` | 同一 contour mask | 是 |
| `cc_all` | 实验图非零点 | 否 |
| `cc_all_about_mean` | 同一非零 mask | 是 |

这些数值由 Chimera 的官方 correlation API 计算；AdaLigand 负责构造输入、选择 mask、解析高精度结果和 QC。四个非空值必须有限且在 `[-1,1]`。contour 缺失时只允许两个 contour 指标为 `null`，不能猜 contour。

#### 配体逐原子 Q

MapQ 使用原始 native map 和完整首 model/规范 altloc 的 `ATOM+HETATM` 模型。正式参数固定为 `sigma=0.4`、`np=8`。

MapQ 输出先按原始 `_atom_site.id` 严格 join，再按 component/atom name 投影回 LigandObject 行序。不能按输出行序、残基遍历顺序或坐标最近邻猜映射。

`quality_atoms/{pdb_id}.npz` 的 `qscore_{cid}` 形状为 `(M,)`，与 LigandObject 模板行序一致；`present=False` 的位置固定为 `NaN`。

#### 6 Å occurrence 口袋 Q

对每个 occurrence，取首 model、规范 altloc、`group_PDB==ATOM` 的受体重原子中，距离任一 present 配体重原子不超过 `6.0 Å` 的原子并集：

$$
P_c = \{r_i : \min_j \lVert r_i-l_{c,j} \rVert_2 \le 6.0\,\text{Å}\}
$$

保存：

- 按数值升序排列的 `pocket_atom_site_id_{cid}`；
- 同序的 `pocket_qscore_{cid}`；
- mean/median/min/count/radius/status。

如果口袋为空，occurrence 仍保留，数组是 typed empty，聚合值为 `null`，状态为 `no_receptor_atoms_within_radius`；不能因为单个 occurrence 没有口袋就淘汰整个 PDB。

### 3.5 Stage G：分布和过滤

文件：`code/filtering.py`

`analyze` 模式：

- 检查 D/E/F 每个适用 PDB 恰好有一个终态；
- 拒绝 unknown、重复、额外或 silent missing；
- 输出四 CC、配体 Q、口袋 Q 和 resolution 的分布；
- 输出 `quality_distribution.json` 和 `candidates.pending.jsonl`；
- 不写 `keep_list.jsonl`。

`filter` 模式只有在显式 `schema_version=2` 配置存在时才运行；没有 v1 兼容分支。它直接使用 analyze 已扁平化的 occurrence 字段，不回到密度图、`quality_atoms` 或 MapQ 重算。

G 的过滤单位是 PDB/map，不是 occurrence。每个 occurrence 先按严格阈值计算：

```text
pair_pass = (q_score > ligand_q_min) AND (pocket_q_score > pocket_q_min)
```

空口袋的 `pocket_q_score=null` 固定失败，并计入分母。map 只有在 selected CC 含等号达标、resolution 含等号不高于上限、合格 occurrence 比例含等号达标时才通过。通过后把该 map 的全部 occurrence 写入 `keep_list`，包括 `pair_pass=false` 的行；pair 规则评价 map 整体质量，不是 map 内二次删样本。每个 PDB 的 CC/resolution 必须先验证为唯一一致值，配置和输入 manifest 均保存 hash。

## 4. 工具调用和适配层：`code/`

### 4.1 Chimera：`code/chimera.py`

输入通常是：

- Chimera 可执行文件路径；
- 临时目录中的 MRC、mmCIF 和命令脚本；
- 要执行的 Midas/Chimera 命令。

输出是：

- 退出码；
- stdout/stderr；
- 日志路径；
- 输入和工具版本 provenance。

`ChimeraRunner` 不定义 CC 或 molmap 的科学公式，只负责可靠启动、超时/进程组处理、日志留存和结果返回。

### 4.2 MapQ：`code/mapq.py`

输入是 native EMDB map、规范化完整模型、MapQ 固定包和 `sigma=0.4,np=8`。输出是带原子身份的 Q-score mmCIF 和解析后的逐原子 Q。

AdaLigand 还会在每个 PDB scratch 目录生成一次性兼容副本，补上 classic Chimera 1.19 中 `ReadMol` 后缺少 `openModels.add` 的调用；固定安装包本身不被修改。

### 4.3 MRC/Pocket Plus：`code/mrc.py` 与 `code/mrc_pocket_legacy.py`

`mrc_pocket_legacy.py` 保存 Pocket Plus 的六个祖传函数：

- `load_map`；
- `make_cubic`；
- `normalize_voxel_size`；
- `rescale_real`；
- `rescale_fourier`；
- `make_model_grid`。

这六个函数是可信数值基线，代码保持近零差异。`mrc.py` 只做 Path、句柄所有权、`MapGrid`/float32、origin mode、标准 writer 和 QC 所需的薄适配。

核心坐标契约：

- 网格数组轴为 ZYX；
- world coordinate 和 voxel metadata 为 XYZ Å；
- native EMDB map 使用 Pocket Plus 的 native origin 语义；
- Ada/Chimera 写出的 canonical MRC 使用标准轴、`nstart=0` 和 Å 级 header origin；
- 所有下游消费实际返回的 voxel，不硬编码精确 1 Å。

`mrc_pocket_legacy.source.json` 是来源、函数哈希、AST parity 和允许适配差异的证据清单，不是运行时算法。

### 4.4 模型和网络输入适配

- `code/model_cif.py`：选择首 model/规范 altloc、规范化 atom identity，生成 Chimera/MapQ 输入模型。
- `code/rcsb.py`：RCSB/EMDB API 请求、EMDB-PDB 关系和 resolution 提取。
- `code/download.py`：下载 mmCIF、metadata、EMDB map，处理临时文件和资源级失败。

## 5. 防御、修复和一次性运维代码

### 5.1 长期防御性模块

- `code/contracts.py`：schema-aware 完成判据；不是“路径存在就算完成”。
- `code/qc.py`：数组、shape、dtype、有限性、三维性、origin、voxel 和 CC 检查。
- `code/failures.py`：区分可接受的 `known_failed` 和必须阻断 gate 的 `unknown_failed`。
- `code/reports.py`：写 run-scoped stage status、报告和终态。
- `code/io_utils.py`：原子写入、文件锁、JSONL、SHA-256。
- `code/parallel.py`：稳定分片、显式 PDB 子集和并发输入。

这些模块不改变科学目标，但决定错误能否被发现、旧失败能否污染新 run，以及半写文件能否被误认为完成。

### 5.2 一次性 source 修复和依赖补足

- `code/c_upgrade.py`：旧 C 产物的兼容升级；当前正式路径只在旧 schema 被识别时条件性调用。
- `code/c_ccd_prefetch.py` 与 `scripts/c_ccd_prefetch.py`：一次性补足指定 CCD cache。
- `code/c_descriptor_prefetch.py` 与对应 script：从已有 LigandObject 非覆盖补 descriptor。
- `code/c_source_repair.py` 与对应 script：对 source-dirty 集合做 audit、分类和 receptor-only 迁移。
- `code/c_source_rebuild.py` 与对应 script：本轮授权的 14-PDB 5GP 完整 C 重建、before/after manifest 和事务 receipt。
- `scripts/snapshot_source_dirty.py`：按显式 mtime 窗口冻结 source-dirty ID 清单和 SHA。

这些代码的记录和 manifest 是本轮事故/迁移的审计证据，不是未来自动接受任意 source 漂移的通用许可。

### 5.3 MRC 审计和 smoke

- `code/mrc_contract_audit.py` 与 `scripts/audit_mrc_contract.py`：全量 header/实现/哈希审计。
- `scripts/smoke_mrc_geometry.py`：真实 MRC 的 shape、actual voxel、origin、轴、nstart 和三维内容检查。
- `code/smoke_checks.py` 与 `scripts/smoke_negative_cc.py`：错位 map/model 的 CC 负对照。
- `scripts/stage_release_gate.py`、`scripts/abc_release_gate.py`：阻止未知失败和静默缺失向下游释放。

### 5.4 服务器锁和调度运维

- `sbatch/_adaligand_job_core.sh`：`run_cmd` 校验、`pre_lock`、`try_lock`、`kill_lock`、`after_lock`、心跳、进程组清理和退出码传播。
- `sbatch/resume_abc_316114_source_v2.sh`：本轮 316114 的阶段感知恢复入口；不是普通 C 解析入口。
- `sbatch/submit_full_pipeline.sh`：提交 A–G `afterok` DAG。
- `sbatch/real_smoke.sbatch`、`sbatch/negative_cc_smoke.sbatch`、`sbatch/submit_real_smoke.sh`：真实 smoke 和负对照提交工具。
- `sbatch/a.sbatch`、`b.sbatch`、`c.sbatch`：旧的单阶段/array 模板，主要作为历史参考；不能覆盖当前正式 DAG 的资源和 B 单节点单 task 契约。

## 6. 入口/指针层索引

入口代码不需要先读内部实现。先用下面的表找到目标模块，再回到第三、四、五节。

| 入口 | 指向的实际逻辑 | 阅读重点 |
|---|---|---|
| `scripts/a_enumerate.py` | `rcsb.py`、`io_utils.py` | 如何生成 A 清单 |
| `scripts/a_guard.py` | `reports.py`、`io_utils.py` | A 清单是否固定 |
| `scripts/b_download.py` | `download.py`、`rcsb.py` | 外部下载和资源级失败 |
| `scripts/c_parse.py` | `parse.py`、`receptor.py`、`ligand_object.py`、`ligand_descriptors.py` | C 的结构和化学产物 |
| `scripts/d_atom_labels.py` | `atom_labels.py` | D 标签计算 |
| `scripts/e_density.py` | `density.py`、`chimera.py`、`mrc.py` | E 三类产物和工具调用 |
| `scripts/f_quality.py` | `quality.py`、`chimera.py`、`mapq.py` | CC/Q/口袋 Q |
| `scripts/g_filter.py` | `filtering.py` | analyze 与显式 filter 的边界 |
| `scripts/abc_release_gate.py` | `contracts.py`、`reports.py` | A–C 是否允许释放 |
| `scripts/stage_release_gate.py` | `contracts.py`、`qc.py`、`reports.py` | D/E/F 是否允许下游运行 |

当前正式 sbatch 入口：

- `abc_full.sbatch`：写入并执行 A/B/C/ABC gate 的 run command；
- `de_full.sbatch`：并行执行 D 和 E，再执行 DE gate；
- `f_full.sbatch`：执行 F，再执行 F gate；
- `g_analyze.sbatch`：只执行 G analyze；
- `_adaligand_job_core.sh`：被这些 sbatch 包装器 source 的运维核心。

## 7. 新手推荐阅读顺序

### 第一遍：只看数据流

先读：

1. 本文件第 2 节；
2. `code/readme.md` 的产物树；
3. `scripts/c_parse.py`、`scripts/d_atom_labels.py`、`scripts/e_density.py`、`scripts/f_quality.py`、`scripts/g_filter.py` 的入口调用；
4. 本文件第 3 节对应的核心模块。

第一遍不要深入 lock、manifest 或异常分支。

### 第二遍：深入科学逻辑

推荐顺序：

1. `parse.py`：明确 occurrence、candidate_id 和三套配体数据；
2. `receptor.py`：明确受体行序、键类型和 49 维特征；
3. `atom_labels.py`：明确距离和 tie-break；
4. `density.py` + `mrc.py`：明确 ZYX/XYZ、实际 voxel 和受体-only map；
5. `quality.py`：明确四 CC、MapQ join 和 6 Å pocket；
6. `filtering.py`：明确分布、状态和阈值边界。

### 第三遍：工具和安全边界

再读：

- `chimera.py`、`mapq.py`、`model_cif.py`；
- `contracts.py`、`qc.py`、`failures.py`、`reports.py`；
- `abc_release_gate.py`、`stage_release_gate.py`；
- `_adaligand_job_core.sh` 和正式 sbatch。

最后再读 source repair、MRC audit、smoke 和一次性恢复脚本。

## 8. 最容易混淆的几个概念

### 8.1 模板坐标和真实沉积坐标

`LigandObject.atoms["ref_pos"]` 是参考构象；`ligand_coords.npz` 的 `coords_{cid}` 才是真实结构坐标。D/E/F 不应使用参考构象代替真实 pose。

### 8.2 数组轴和空间坐标顺序

密度数组是 `(1,Z,Y,X)`；世界坐标和 `voxel_size` 是 `(X,Y,Z)`。不能把数组下标顺序直接当成 XYZ 坐标。

### 8.3 E2 和 F 的原子集合不同

- E2 receptor-only map：严格只保留 `group_PDB==ATOM`，删除全部 HETATM；
- F 的完整模型 Q-score：保留首 model/规范 altloc 的 `ATOM+HETATM`。

### 8.4 口袋 Q 不是配体 Q

配体 Q 是配体自身原子的 Q；口袋 Q 是 6 Å 包络内受体原子的 Q。二者都保留 occurrence 级原始数组和聚合值，不预先过滤。

### 8.5 known failure 和 unknown failure

`known_failed` 是明确、可解释且允许 gate 继续的样本级不适用情形；普通异常、schema 漂移、工具输出错误和静默缺失必须是 `unknown_failed`，会阻断 release gate。

### 8.6 pair 通过和 map 通过

`pair_pass` 只参与计算一张 map 的合格 occurrence 比例。它不是最终 occurrence 保留标记。只要 map 达到 CC、分辨率和合格比例三道门，该 map 内所有 occurrence 都进入 `keep_list`；空口袋或 Q 偏低的 occurrence 也随通过 map 保留。

## 9. 如何判断一个函数值不值得深入读

优先深入：

- 产生数组、坐标、距离、标签、CC、Q-score 或过滤结果的函数；
- 改变主键、行序、轴顺序、单位、mask 或阈值语义的函数；
- 选择受体/配体原子集合的函数。

可以略读：

- 只负责把参数传给另一个模块的入口函数；
- 只负责打印日志、写报告或计算文件 SHA 的函数；
- 只针对某次 source repair、MRC audit 或 smoke run 的脚本。

但防御代码不能完全跳过：至少要知道它在阻止哪一种错误，以及失败时是继续、跳过还是阻断下游。

## 10. 当前明确不属于本轮的内容

- Stage 1 重训；
- BOX 第 2/3 层；
- Stage 2/3；
- 未经正式 schema v2 数值配置执行的最终 `keep_list.jsonl`；
- 任何将 before/after migration manifest 当作永久科学主键映射的做法。

当你阅读某个函数时，最有效的提问格式是：

```text
这个函数属于哪一类？
入口传给它什么？
它返回哪些字段/数组，形状和单位是什么？
哪些部分是科学计算，哪些部分是外部工具或防御检查？
它是否仍在正式 A–G 主路径中？
```

只要这五个问题能回答，新手或没有上下文的 AI agent 就能判断该函数是否需要深入，以及应该沿着哪一个入口指针继续阅读。
