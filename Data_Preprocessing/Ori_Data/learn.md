# AdaLigand A–G 代码阅读指南

这是一份面向新手工程师和没有上下文的 AI agent 的代码阅读地图。它解释三个问题：

1. 一个文件主要属于哪一种实际逻辑；
2. 正式 A–G 流水线从哪个入口进入、依次调用什么；
3. 哪些代码决定科学数据，哪些代码只是工具连接、检查、事故恢复或服务器运维。

本文只描述代码结构、当前契约和代码阅读边界；本轮对 Python 文件所做的改动仅限顶部 `#` 学习注释，不改变任何运行逻辑。本文不授权连接服务器、重新运行任务或修改数据产物。仓库根目录是当前文件所在的项目根；文中路径均使用仓库相对路径。

## 1. 最重要的分类方法

代码使用五个阅读分区。前两类和科学计算/外部系统有关，第三类保护数据契约，第四类保护执行生命周期，第五类只是导航。入口代码不是新的科学逻辑；历史恢复也不是新的科学定义，而是每个文件的生命周期标签。

### 1.1 核心科学逻辑

这类代码决定数据的科学含义、坐标/距离/特征计算、质量指标或过滤规则。阅读它时要回答：输入是什么、输出数组是什么、单位和轴顺序是什么、公式或判定条件是什么。

### 1.2 工具调用和适配层

这类代码把 AdaLigand 的数据转换成 Chimera、MapQ、MRC、RCSB/EMDB 等外部系统能接受的输入，再把外部结果严格转换回来。它通常不重新发明 CC、Q-score 或 Pocket Plus 的数值算法。

### 1.3 数据契约与质量验证

这类代码控制“产物是否可信”：验证 schema、shape、dtype、主键、坐标、单位、数值范围、三维内容、状态唯一性和 provenance，并决定 unknown failure 是否阻断 release。它们不负责 Slurm 进程生命周期。

主要文件是 `contracts.py`、`qc.py`、`failures.py`、`reports.py`、`io_utils.py`、`abc_release_gate.py` 和 `stage_release_gate.py`。release gate 虽然会影响下游作业是否启动，但其核心判断对象仍然是数据状态。

### 1.4 调度、资源与恢复控制

这类代码控制“程序怎样运行、暂停、重试和退出”：afterok DAG、CPU/并发参数、run command、进程组、heartbeat、`pre_lock`/`try_lock`/`kill_lock`/`after_lock`，以及本轮事故的 source repair/rebuild、依赖 prefetch 和阶段恢复脚本。

主要文件是 `sbatch/_adaligand_job_core.sh`、`sbatch/*.sbatch`、`submit_full_pipeline.sh`、`resume_*.sh`，以及 `c_source_repair.py`、`c_source_rebuild.py`、CCD/descriptor prefetch。它们可以修复或保护产物，但不定义 CC、Q-score、口袋或标签的科学语义。

### 1.5 入口/指针层（不作为新的实际逻辑）

入口文件通常只做参数解析、环境准备、并发编排、调用模块和退出码传播。看到入口后，沿着它的 `import` 和函数调用继续跳到四类实际逻辑（核心科学、工具适配、数据契约、执行控制）。

判断一个文件是不是入口的最直接方法：如果它主要包含 `argparse`、`main()`、`sbatch`、环境变量、`joblib.Parallel`、阶段调用和 gate 调用，而不是实现数学函数，那么它就是入口/编排层。

入口层与四类实际逻辑的关系如下：

```text
入口/指针
  └─ 调用核心科学逻辑
  └─ 调用工具适配层
  └─ 调用数据契约 gate / 报告逻辑
  └─ 由 sbatch/守护层控制资源、锁和退出码
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

`filter` 模式只有在显式 JSON 配置存在时才运行。当前代码的 `FILTER_CONFIG_SCHEMA_VERSION` 是 `1`，配置必须显式给出 `q_score_min`、`resolution_max`（可以为 `null`）、`resolution_policy`（`exclude` 或 `flag_only`）和 `comparison="inclusive"`。它直接使用 analyze 已扁平化的 occurrence 字段，不回到密度图、`quality_atoms` 或 MapQ 重算。

当前实现的 `apply_filter_config()` 实际只执行两类规则：配体聚合 Q-score 下限和分辨率上限；CC、口袋 Q 等字段会进入分布和 pending candidates，但尚未在这个函数中成为过滤阈值。计划书中“未来由用户同时指定分辨率、CC、配体 Q 和口袋 Q”的范围不能误读为当前代码已经实现。

G 的当前过滤单位是 occurrence 主键 `(pdb_id, candidate_id)`：它先把上游无 known failure 的 PDB 的全部 quality JSONL 读入，逐 occurrence 校验字段、口袋空值语义和四种 CC，再按显式 `q_score_min`/resolution 规则生成 `excluded.jsonl`、`flagged.jsonl`、summary 和最终 `keep_list.jsonl`。已知失败 PDB 不进入候选清单，但会在 G 状态和分布中留下原因计数。

历史计划或旧文档中出现的 `pair_pass`、map 级比例门、`schema_version=2` 配置等口径，不是当前 `code/filtering.py` 的正式实现；阅读时应以当前代码为准，并把这些旧口径标为历史差异，而不是默默混入当前算法。

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

## 5. 数据契约与质量验证代码

### 5.1 长期数据防御模块

- `code/contracts.py`：schema-aware 完成判据；不是“路径存在就算完成”。
- `code/qc.py`：数组、shape、dtype、有限性、三维性、origin、voxel 和 CC 检查。
- `code/failures.py`：区分可接受的 `known_failed` 和必须阻断 gate 的 `unknown_failed`。
- `code/reports.py`：写 run-scoped stage status、报告和终态。
- `code/io_utils.py`：原子写入、文件锁、JSONL、SHA-256。
- `code/parallel.py`：稳定分片、显式 PDB 子集和并发输入。

这些模块不改变科学目标，但决定错误能否被发现、旧失败能否污染新 run，以及半写文件能否被误认为完成。它们属于数据平面守护：关注文件内容和状态，不关注 Slurm 进程。

### 5.2 数据 gate 的边界

- `scripts/abc_release_gate.py` 读取 A/B/C 的 run-scoped 状态并逐 PDB 调用 `inspect_stage_c()`；它允许显式 B `known_failed`，但要求 C 完整且无 unknown/silent missing。
- `scripts/stage_release_gate.py` 复用 `filtering.load_stage_statuses()`，检查目标 PDB 集合是否恰好覆盖、是否有重复/额外/unknown 状态，并按 gate 名称写 summary。
- `scripts/g_filter.py` 不依赖外部调度器；它在 G 自己的分析/过滤逻辑中重新读取 D/E/F 状态，因此 G 仍有一层独立的完整性检查。
- `model_map_frame_mismatch` 是正式 E/F 数据契约：只有合法 map 和 Stage C polymer receptor token 坐标的 XYZ 包围盒完全分离时才分类为 known；NaN、坏 schema、全零和工具错误仍是 unknown。

## 6. 调度、资源与恢复控制代码

### 6.1 正式运行控制

- `sbatch/_adaligand_job_core.sh`：验证 run_cmd 是普通非 symlink 文件，记录 SHA，创建 `after_lock`，可等待 `pre_lock`，运行独立进程组，监控 `kill_lock`，每 300 秒写 heartbeat；失败时创建 `try_lock`，成功时清理本作业锁和命令文件。
- `sbatch/submit_full_pipeline.sh`：提交 ABC→DE→F→G 的 `afterok` DAG；它只连接作业，不实现阶段科学逻辑。
- `abc_full.sbatch`、`de_full.sbatch`、`f_full.sbatch`、`g_analyze.sbatch`：分别定义资源、日志、环境和 run command 生成钩子，并 source 运行控制核心。
- `after_lock` 是 allocation 的完成/占用标记，不等于数据 gate；只有 run command 和嵌入 gate 成功，核心才会自动清理它。

### 6.2 一次性 source 修复和依赖补足

- `code/c_upgrade.py`：旧 C 产物的兼容升级；当前正式路径只在旧 schema 被识别时条件性调用。
- `code/c_ccd_prefetch.py` 与 `scripts/c_ccd_prefetch.py`：一次性补足指定 CCD cache。
- `code/c_descriptor_prefetch.py` 与对应 script：从已有 LigandObject 非覆盖补 descriptor。
- `code/c_source_repair.py` 与对应 script：对 source-dirty 集合做 audit、分类和 receptor-only 迁移。
- `code/c_source_rebuild.py` 与对应 script：本轮授权的 14-PDB 5GP 完整 C 重建、before/after manifest 和事务 receipt。
- `scripts/snapshot_source_dirty.py`：按显式 mtime 窗口冻结 source-dirty ID 清单和 SHA。

这些代码的记录和 manifest 是本轮事故/迁移的审计证据，不是未来自动接受任意 source 漂移的通用许可。它们的功能分区是“恢复控制”，生命周期标签是“一次性/条件性”，不能误读为新一轮干净 A–G 必经步骤。

### 6.3 MRC 审计和 smoke

- `code/mrc_contract_audit.py` 与 `scripts/audit_mrc_contract.py`：全量 header/实现/哈希审计。
- `scripts/smoke_mrc_geometry.py`：真实 MRC 的 shape、actual voxel、origin、轴、nstart 和三维内容检查。
- `code/smoke_checks.py` 与 `scripts/smoke_negative_cc.py`：错位 map/model 的 CC 负对照。
- `scripts/stage_release_gate.py`、`scripts/abc_release_gate.py`：阻止未知失败和静默缺失向下游释放。

### 6.4 旧模板与当前主路径的区别

- `sbatch/resume_abc_316114_source_v2.sh`：本轮 316114 的阶段感知恢复入口；不是普通 C 解析入口。
- `sbatch/resume_de_316115_e_repair_v1.sh`：本轮 Stage E 工程失败恢复入口；不是普通 E 入口，且其历史注释可能落后于已批准的 frame-mismatch 契约。
- `sbatch/real_smoke.sbatch`、`sbatch/negative_cc_smoke.sbatch`、`sbatch/submit_real_smoke.sh`：真实 smoke 和负对照提交工具。
- `sbatch/a.sbatch`、`b.sbatch`、`c.sbatch`：旧的单阶段/array 模板，主要作为历史参考；不能覆盖当前正式 DAG 的资源和 B 单节点单 task 契约。

## 7. 入口/指针层索引

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

## 8. 新手推荐阅读顺序

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

## 9. 最容易混淆的几个概念

### 9.1 模板坐标和真实沉积坐标

`LigandObject.atoms["ref_pos"]` 是参考构象；`ligand_coords.npz` 的 `coords_{cid}` 才是真实结构坐标。D/E/F 不应使用参考构象代替真实 pose。

### 9.2 数组轴和空间坐标顺序

密度数组是 `(1,Z,Y,X)`；世界坐标和 `voxel_size` 是 `(X,Y,Z)`。不能把数组下标顺序直接当成 XYZ 坐标。

### 9.3 E2 和 F 的原子集合不同

- E2 receptor-only map：严格只保留 `group_PDB==ATOM`，删除全部 HETATM；
- F 的完整模型 Q-score：保留首 model/规范 altloc 的 `ATOM+HETATM`。

### 9.4 口袋 Q 不是配体 Q

配体 Q 是配体自身原子的 Q；口袋 Q 是 6 Å 包络内受体原子的 Q。二者都保留 occurrence 级原始数组和聚合值，不预先过滤。

### 9.5 known failure 和 unknown failure

`known_failed` 是明确、可解释且允许 gate 继续的样本级不适用情形；普通异常、schema 漂移、工具输出错误和静默缺失必须是 `unknown_failed`，会阻断 release gate。

### 9.6 pair 通过和 map 通过

`pair_pass` 只参与计算一张 map 的合格 occurrence 比例。它不是最终 occurrence 保留标记。只要 map 达到 CC、分辨率和合格比例三道门，该 map 内所有 occurrence 都进入 `keep_list`；空口袋或 Q 偏低的 occurrence 也随通过 map 保留。

这段规则属于旧版/计划中的历史口径，不是当前 `filtering.py` 的执行规则。保留它是为了让读者能识别旧产物或旧报告：旧逻辑会先以 `pair_pass = (q_score > ligand_q_min) AND (pocket_q_score > pocket_q_min)` 判断 occurrence，再在 map 级汇总合格比例；当前代码则按 occurrence 读取质量字段，并只应用现行 schema v1 中的 Q-score 下限和 resolution 规则。

## 10. 如何判断一个函数值不值得深入读

优先深入：

- 产生数组、坐标、距离、标签、CC、Q-score 或过滤结果的函数；
- 改变主键、行序、轴顺序、单位、mask 或阈值语义的函数；
- 选择受体/配体原子集合的函数。

可以略读：

- 只负责把参数传给另一个模块的入口函数；
- 只负责打印日志、写报告或计算文件 SHA 的函数；
- 只针对某次 source repair、MRC audit 或 smoke run 的脚本。

但防御代码不能完全跳过：至少要知道它在阻止哪一种错误，以及失败时是继续、跳过还是阻断下游。

## 11. 当前明确不属于本轮的内容

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

## 12. 逐文件阅读索引

下面的索引是“从文件跳到实际职责”的导航，不替代各模块的函数级阅读。每个项目自有 Python 文件顶部也有同样性质的 `#` 模块卡片；这些卡片只做导航，不改变程序行为。

### 12.1 `code/` 正式主路径模块

| 文件 | 主分区 | 生命周期 | 先看什么 |
|---|---|---|---|
| `constants.py` | 核心科学逻辑 | 正式主路径 | 元素、残基、键类型、半径和 schema 常量；它是多个模块共享的语义词典 |
| `parse.py` | 核心科学逻辑 | 正式主路径 | `build_stage_c_source_view()`、`parse_one_pdb()`、component/occurrence 分组和真实坐标对齐 |
| `ligand_object.py` | 核心科学逻辑 | 正式主路径 | CCD/BRANCHED 模板、原子/键行序、`ref_pos` 与占位坐标 |
| `ligand_descriptors.py` | 核心科学逻辑 | 正式主路径 | 从化学图生成去重 descriptor，输入是 LigandObject，不是沉积 pose |
| `receptor.py` | 核心科学逻辑 | 正式主路径 | 受体基础七数组、`bond_index/bond_type` 和 `(N,49)` 特征 |
| `atom_labels.py` | 核心科学逻辑 | 正式主路径 | 最近配体重原子距离、4 Å binding 标签、instance tie-break |
| `density.py` | 核心科学 + 工具编排 | 正式主路径 | E1/E2/E3 三个 builder；它连接 `mrc.py`、`model_cif.py` 和 `ChimeraRunner` |
| `quality.py` | 核心科学 + 工具编排 | 正式主路径 | 四 CC、MapQ 身份 join、配体 Q 和 6 Å occurrence pocket Q |
| `filtering.py` | 核心科学 + 数据守护 | 正式主路径 | G 状态读取、分布、pending candidates 和当前实际 filter config |

### 12.2 `code/` 工具适配模块

| 文件 | 作用 | 外部边界 |
|---|---|---|
| `rcsb.py` | 搜索 PDB、选择 EMDB、提取 resolution 和构造 URL | RCSB Search/Entry 与 EMDB metadata API |
| `download.py` | 临时下载、gzip/非空检查、原子提升和资源级失败 | RCSB mmCIF、EMDB metadata/map |
| `model_cif.py` | 首 model/规范 altloc/重原子筛选和标准化 mmCIF | Chimera/MapQ 的结构输入 |
| `chimera.py` | 启动 classic Chimera、molmap onGrid、correlation、日志/超时 | Chimera 可执行文件与 scratch |
| `mapq.py` | 生成兼容 MapQ CLI、运行 MapQ、解析 Q-score CIF | MapQ 固定包、native MRC、完整模型 |
| `mrc.py` | 统一 `MapGrid`、调用 Pocket Plus 原语、写标准 MRC、几何闭合 | MRC/CCP4 输入输出 |
| `mrc_pocket_legacy.py` | Pocket Plus 六函数可信快照 | 冻结祖传数值代码；禁止本轮头部注释修改 |

### 12.3 `code/` 数据守护与基础设施

| 文件 | 作用 | 是否定义科学量 |
|---|---|---|
| `contracts.py` | C/E/F artifact schema 和完成判定 | 不定义科学指标，只检查是否满足契约 |
| `qc.py` | shape、dtype、有限性、几何、CC 和 frame 检查 | 不计算最终科学分数，负责拒绝非法结果 |
| `failures.py` | stable known/tool failure 枚举和异常类型 | 定义失败分类语义，不生成训练特征 |
| `reports.py` | run-scoped status、JSONL 报告和终态写入 | 不改变核心数组 |
| `io_utils.py` | SHA、manifest、原子 NPZ/JSONL、文件锁 | 保证写入和证据可追溯 |
| `parallel.py` | PDB 过滤、稳定分片和显式子集 | 不改变单样本数学逻辑 |

### 12.4 条件、历史和审计模块

| 文件 | 功能分区 | 生命周期 | 正式新运行是否必经 |
|---|---|---|---|
| `c_upgrade.py` | 条件性 C 兼容迁移 | 旧 schema 条件分支 | 只有发现旧 C artifact 时调用 |
| `c_ccd_prefetch.py` | CCD cache 补足 | 本轮一次性恢复 | 否 |
| `c_descriptor_prefetch.py` | descriptor 非覆盖补足 | 本轮一次性恢复 | 否 |
| `c_source_repair.py` | source-dirty receptor-only audit/apply | 本轮一次性恢复 | 否 |
| `c_source_rebuild.py` | 14-PDB 特定 C 重建和迁移审计 | 本轮一次性恢复 | 否 |
| `mrc_contract_audit.py` | MRC header/实现/哈希审计 | 一次性审计 | 否 |
| `smoke_checks.py` | 负对照和工具输出辅助检查 | 测试/审计 | 否 |

### 12.5 `scripts/` 入口与 gate

| 入口 | 调用的实际模块 | 生命周期 |
|---|---|---|
| `a_enumerate.py` | `rcsb.py`、`io_utils.py` | bootstrap；生成 pair_list，不是当前冻结清单的正式起点 |
| `a_guard.py` | `reports.py`、`io_utils.py` | 正式 A guard；无网络复用冻结 pair_list |
| `b_download.py` | `download.py`、`rcsb.py`、`parallel.py` | 正式 B |
| `c_parse.py` | `parse.py`、`contracts.py`、`parallel.py` | 正式 C；filtered 子集必须使用隔离 run |
| `d_atom_labels.py` | `atom_labels.py` | 正式 D |
| `e_density.py` | `density.py`、`chimera.py`、`mrc.py` | 正式 E |
| `f_quality.py` | `quality.py`、`chimera.py`、`mapq.py` | 正式 F |
| `g_filter.py` | `filtering.py` | 正式 G analyze/filter |
| `abc_release_gate.py` | `contracts.py`、`filtering.py`、`reports.py` | A–C 数据 gate |
| `stage_release_gate.py` | `filtering.py`、`reports.py` | D/E/F 通用数据 gate |

其余 `scripts/c_*`、`audit_mrc_contract.py`、`smoke_*`、`snapshot_source_dirty.py` 是恢复、审计或测试入口。它们可以调用正式模块，但不能反过来证明自己就是正式科学主路径。

## 13. Guard、gate 与主流程的关系

### 13.1 Guard 不是第五种科学逻辑

Guard 的共同目的都是阻止“看起来有文件、实际上不满足契约”的状态继续传播。应按控制对象区分：

```text
数据契约与质量验证：控制数据状态
调度、资源与恢复控制：控制执行状态
```

例如：

- `inspect_stage_c()` 控制 C artifact 是否完整；
- `density_artifact_errors()` 控制 E1/E2/E3 内容是否可消费；
- `load_stage_statuses()` 控制每个 PDB 是否恰好一个终态；
- `stage_release_gate.py` 把数据判定转换成作业退出码；
- `_adaligand_job_core.sh` 根据退出码决定成功退出、创建 `try_lock` 或等待人工/agent 重试。

因此 gate 在数据层有主要归属，在调度层有次级效果；学习文档不把同一个文件复制到两个列表，而是在文件卡片中写“主分区/次级影响”。

### 13.2 删除 guard 后能否复现

需要区分三个目标：

1. **调用数学函数**：有可信输入时，部分核心函数仍可被直接调用。
2. **生成一批文件**：可以手动串联脚本，但必须自己承担顺序、完整性、失败隔离和原子写入责任。
3. **复现可信训练数据集**：不能省略 guard、release gate、provenance、原子写入和固定 source snapshot，否则无法证明没有 silent missing、stale artifact 或 unknown failure 混入。

从冻结 raw snapshot 开始，当前核心路径可以重现；从公开网络“从零”开始时，`a_enumerate.py`、下载、CCD cache 和外部工具版本都可能改变结果，不能承诺得到同一 pair_list 或同一 candidate_id。

## 14. 当前代码现实与旧文档口径的差异

这些差异在本轮学习文档中明确标注，不回写 `readme.md` 或计划书：

1. 当前 `filtering.py` 的 filter 配置版本是 `1`，实际阈值只有 `q_score_min` 和 resolution；CC/口袋 Q 已进入分布，但尚未成为 filter 参数。
2. 旧文档中出现的 PDB/map 级 `pair_pass` 和 occurrence 比例门，不是当前实现；它们只能作为历史计划口径阅读。
3. `a_enumerate.py` 是 bootstrap；正式冻结样本从 `a_guard.py` 开始。
4. `resume_de_316115_e_repair_v1.sh` 是本轮恢复入口，不应当被当成普通 E 入口；其历史注释可能落后于当前已批准的 frame-mismatch 契约。
5. `mrc_pocket_legacy.py` 的源码与哈希证据是冻结边界；本轮仅在 `learn.md` 和其他项目自有模块顶部添加学习注释。

## 15. 推荐的无上下文 AI 阅读顺序

1. 先读本文第 2 节，建立 A→G 方向和正式入口。
2. 读本文第 3 节和第 12 节，建立 C/D/E/F/G 的字段、shape、单位和模块映射。
3. 按 `parse.py → ligand_object.py → receptor.py` 理解 C 的身份、行序和三套坐标。
4. 读 `atom_labels.py`，确认距离阈值和 tie-break。
5. 读 `density.py → mrc.py → mrc_pocket_legacy.py`，重点区分 ZYX 数组与 XYZ 世界坐标。
6. 读 `model_cif.py → chimera.py`，理解 E2 的 ATOM-only 输入和 F 的完整模型输入。
7. 读 `mapq.py → quality.py`，理解 atom_site.id join、配体 Q 和口袋 Q。
8. 读 `filtering.py`，以当前代码为准理解 G analyze 和实际 filter，而不是沿用旧 pair_pass 描述。
9. 最后读 `contracts.py`、`qc.py`、release gate、`_adaligand_job_core.sh`，理解为什么错误会被阻断或暂停。
10. 最后才读 source repair、MRC audit、smoke 和 resume 脚本，避免把一次性事故路径误认为主算法。

## 16. 仍需后续指定或保持开放的问题

- G 最终是否增加 CC、配体 Q、口袋 Q 的正式过滤字段，以及这些字段的比较符号和空口袋策略，仍需显式配置，不应在当前数值代码中猜测。
- Stage 1 重训、BOX 第 2/3 层和 Stage 2/3 不属于本轮代码阅读主路径。
- `candidate_id` 只在同一冻结 mmCIF source snapshot 内稳定；任何 source revision 都必须重新审计 occurrence 和 candidate-indexed 文件。
- before/after migration manifest 是一次性、run-scoped 审计证据，不是跨 source 永久主键映射。
