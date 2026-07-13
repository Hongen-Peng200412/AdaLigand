# AdaLigand A–G 数据流水线（Ori_Data）产物契约

> **这份文档是什么**：数据侧 Stage A–G **正式运行后产生的全部文件、字段、形状和含义**。目标是新手不读代码也能看懂每个产物。
> **不是什么**：不是实现历史/决策记录（那些在 `文档/exec_plan/数据下载与解析.md`），也不是计划书（`文档/规划文档/数据处理_v2.md`）。本文只描述**当前接口现实**。
> **当前覆盖**：Stage A（冻结清单 guard）、B（增量下载）、C（契约迁移）、D（原子标签）、E（密度）、F（CC/Q-score）和 G（分布/过滤）。服务器全量产物尚需本轮正式运行生成。

---

## 1. 一句话总览 + 运行

所有产物都落在 `--root` 指定的数据根。正式运行给整个 DAG 传同一个 `--run_id`；下列命令只展示接口，资源数和外部工具路径由 `sbatch/` 固化。

正式 CPU96 调度默认 D/E 同作业并发 `D_N_JOBS=64,E_N_JOBS=24`，F 为 12 个 PDB 外层并发；每个 F PDB 的 MapQ 固定 `np=8`，因此最多约 96 个 MapQ Chimera worker。`cpu` 分区当前 `DefaultTime=NONE, MaxTime=UNLIMITED` 且 `Cpu96` 无 MaxWall，所以 DE/F/G sbatch 不写 `--time`。已提交作业若要原地调参，可在启动前原子预置 `/home/penghongen/run_cmd_${SLURM_JOB_ID}.sh`；专用 core 拒绝 symlink，要求普通非空文件并设为 `0700`，在首次及每次 `try_lock` 重试前都执行 `bash -n` 并记录 SHA-256，不存在预置文件时才调用 sbatch 内置生成钩子。

```bash
python scripts/a_guard.py --root ${ROOT} --expected_count 22386 --run_id ${RUN_ID}
python scripts/b_download.py --root ${ROOT} --resources mmcif,meta,map --n_jobs 1 --run_id ${RUN_ID}
python scripts/c_parse.py --root ${ROOT} --n_jobs ${N_JOBS} --run_id ${RUN_ID}
python scripts/abc_release_gate.py --root ${ROOT} --run_id ${RUN_ID}
python scripts/d_atom_labels.py --root ${ROOT} --run_id ${RUN_ID} --n_jobs ${N_JOBS}
python scripts/e_density.py --root ${ROOT} --run_id ${RUN_ID} --chimera ${CHIMERA}
python scripts/f_quality.py --root ${ROOT} --run_id ${RUN_ID} --chimera ${CHIMERA} \
  --chimera_root ${CHIMERA_ROOT} --mapq_cmd ${MAPQ_CMD} --mapq_zip ${MAPQ_ZIP}
python scripts/g_filter.py --root ${ROOT} --run_id ${RUN_ID} --mode analyze
```

**贯穿全程的主键**：`(pdb_id, candidate_id)`。`pdb_id` 一律小写；`candidate_id` 是该 PDB 在**同一冻结 mmCIF source snapshot 内**按排序派生的 0 起编号，不是跨 source revision 永久不变的 accession。source 更新可能因 atom serial 或候选排序变化而重排同一 occurrence 的 `candidate_id`，因此任何 source 迁移都必须同步重建该 PDB 的全部 candidate-indexed C 产物后才能释放下游。

> **产物分两类**：`raw/`、`parse/`、`ligand_objects/` 是**核心产物**（下游训练/推理会消费）；`reports/` 下全是**统计/诊断/辅助产物**（不参与训练推理），其解释统一放在 §4 末尾的 4.7。

---

## 2. 产物目录树（正式跑会生成的全部文件）

```text
${ROOT}/
  raw/                              # 核心：下游会消费的输入件
    pair_list.jsonl                 # Stage A：样本清单(emdb_id, pdb_id, resolution, resolution_info)
    rcsb_mmcif/{pdb_id}.cif         # Stage B：RCSB 全结构 mmCIF
    emdb_maps/emd_{num}.map.gz      # Stage B：EMDB 密度图(默认下载；只跑解析可不下)
    ccd_cache/{CCD}.pkl             # Stage C 按需缓存的 CCD 分子(pickle)
  parse/{pdb_id}/                   # 核心：解析产物
    occurrences.jsonl               # 每行一个配体 occurrence（身份+组分）
    ligand_coords.npz               # 每个 occurrence 的真实沉积坐标
    receptor_tokens.npz             # 受体(聚合物)全原子 token
  ligand_objects/{safe_object_key}.npz   # 核心：去重的配体化学对象(跨 pdb 复用)
  ligand_descriptors/{safe_object_key}.npz # Stage C：去重配体描述子
  labels/{pdb_id}/atom_labels.npz        # Stage D：受体原子标签
  density/{pdb_id}/exp.npz               # Stage E1：目标 1 Å、记录实际 voxel 的 canonical 实验图
  density/{pdb_id}/sim.npz               # Stage E2：严格 ATOM-only 受体模拟图
  density/{pdb_id}/ligand_area.npz       # Stage E3：体素 union + occurrence 稀疏 mask
  quality_atoms/{pdb_id}.npz             # Stage F：配体逐原子 Q + occurrence 口袋受体原子 Q
  quality/{pdb_id}.jsonl                 # Stage F：配体/口袋 occurrence 聚合 + 四种全局 CC
  quality/{pdb_id}.provenance.json       # Stage F：工具、公式、输入和日志 provenance
  keep_list.jsonl                        # Stage G：仅显式阈值配置后生成的最终主键清单
  reports/                          # 统计/诊断/辅助（不参与训练推理）
    {pdb_id}.json                   # 单样本解析报告
    meta/{pdb_id}.meta.json         # EMDB /entry API 原样响应(辅助)
    resolution_summary.json         # 本批分辨率状态统计(统计)
    _failed_parse[.part_*].jsonl    # 若有 PDB 级解析失败才出现; SLURM array 分片时带 .part_XXXX_of_YYYY 后缀
    _failed_download[.part_*].jsonl # 若有下载失败才出现; 同上分片后缀
    runs/{run_id}/{stage}/status.part_*.jsonl # 当前运行唯一终态，不读历史失败猜状态
    runs/{repair_run_id}/stage_c_source_repair/
      audit.records.jsonl           # source-dirty 全集只读分类与冻结哈希
      audit.summary.json            # 分类计数、dirty IDs/audit records SHA-256
      apply.records.jsonl           # exact 不写；atom_name_only 原子迁移结果
      apply.summary.json            # apply 计数与所消费 audit SHA-256
    runs/{repair_run_id}/stage_c_ccd_prefetch/ # 唯一允许联网的显式 CCD cache 补足证据
    runs/{repair_run_id}/stage_c_descriptor_prefetch/ # 已有 LigandObject → descriptor 的非覆盖依赖补足证据
    runs/{repair_run_id}/stage_c_source_rebuild/ # 单次授权 full rebuild 的 staging/backup/receipt
      primary_key_migration.records.jsonl # 本轮 before/after 审计，不是 C schema 或训练字段
    runs/{run_id}/stage_g_analysis/quality_distribution.json
    runs/{run_id}/stage_g_analysis/candidates.pending.jsonl
    runs/{run_id}/stage_g/map_filter_diagnostics.jsonl
    runs/{run_id}/stage_g/excluded_maps.jsonl
    runs/{run_id}/stage_g/summary.json
  scratch/{run_id}/...              # 外部工具 attempt；成功后删除大型临时 MRC
```

---

## 3. 全局约定

- **世界坐标系**：所有坐标都是 mmCIF 沉积态的**世界坐标，单位 Å**。成功样本要求 EMDB map 与受体同框，但 source 声明不能代替实际几何检验；E/F 必须先执行确定性 model-map 包围盒检查。
- **npz 一律不压缩**（`np.savez`）并原子替换。除 `ligand_objects` 的 object 字段外均用 `allow_pickle=False`；读取 LigandObject 时才用 `allow_pickle=True`。
- **小整数编码**：`element`=原子序数；`res_type`/原子名等是编码值，解码表见 §10。
- **两套链/残基编号**：mmCIF 有 `label_*`（规范内部体系）和 `auth_*`（作者/PDB 网页体系），可能不同，两套都保留（见 §4.3 occurrences）。
- **空值约定**：空 `[]` / `""` 与 `null` 同义，都表示"无/不适用"；单残基(CCD)与 BRANCHED 在某些字段上互斥取空，详见 §4.3、§4.4。

---

## 4. 逐文件契约

### 4.1 `raw/pair_list.jsonl`（核心）

一行一个 `(EMDB, PDB)` 样本对。字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `emdb_id` | str | EMDB id，保留前缀，如 `EMD-30556` |
| `pdb_id` | str | 小写 PDB id |
| `resolution` | float \| null | 选定的 map 分辨率(Å)，供后续 Stage F/G 直接消费 |
| `resolution_info` | obj | **这是辅助性字段**：分辨率 provenance（来源/选择规则/状态/候选），仅供人工审查与 Stage F/G 诊断，不直接当训练特征 |

`resolution_info` 关键子字段：`selected`(选定值)、`status`(状态枚举，见 §10)、`selected_source`(来源)、`selection_rule`、`candidates`(全部候选，每个含 `source/value/units/method/path`)。

**例**：
```json
{"emdb_id":"EMD-76493","pdb_id":"12jt","resolution":2.4,
 "resolution_info":{"selected":2.4,"status":"multi_candidate_consistent",
   "selected_source":"emdb.final_reconstruction","n_candidates":2,"n_unique_values":1,
   "candidates":[{"source":"emdb.final_reconstruction","value":2.4,"units":"A","method":"FSC 0.143 CUT-OFF",
     "path":"structure_determination_list.structure_determination[0].image_processing[0].final_reconstruction[0].resolution.valueOf_"}]}}
```

### 4.2 原始下载件（核心）

`raw/rcsb_mmcif/{pdb_id}.cif`（RCSB 全结构 mmCIF）、`raw/emdb_maps/emd_{num}.map.gz`（EMDB 密度图，`{num}`=去掉 `EMD-` 的数字）、`raw/ccd_cache/{CCD}.pkl`（解析时按需拉取的 CCD 分子 pickle）。都是原始外部文件，不做改写，下游会消费。

Stage B 的复用判据必须保持低 I/O：既有 mmCIF 非空、去除前导空白后以 `data_` 开头，且前 1 MiB 含 `_entry.id` 即可复用；不得假设大文件的 `_atom_site.` 必定位于前 1 MiB。完整 mmCIF 结构由 Stage C 实际解析时验证。map 跳过路径只检查非空与 gzip magic，完整 CRC/MRC/三维内容由下载后校验和 Stage E 读取负责。run-scoped `known_failed` 也保存逐资源 `resources` 状态，不能只保留错误文本而丢掉本轮哪些 source 被刷新。

---

### 4.3 `parse/{pdb_id}/occurrences.jsonl` ★（核心）

一行一个**配体 occurrence**（= 一个共价连通的分子整体；单残基或整条糖链都算一个）。

| 字段 | 类型 | 含义 |
|---|---|---|
| `pdb_id` | str | 小写 PDB id |
| `candidate_id` | int | 该 PDB 内 occurrence 编号，**从 0 开始、按稳定排序赋号**（主键的一半）。⚠️ `resolve_failed` 的 occurrence 会被丢弃，所以文件里的编号**可能跳号、不保证连续** |
| `kind` | str | `CCD`(单残基) / `BRANCHED`(多残基共价连通)；决定下面若干字段的取空模式（见"空值与互斥约定"） |
| `object_key` | str | 化学对象**去重键**（详见下方"object_key 与 hash"） |
| `type_tag` | str | `small_molecule / sugar / peptide_like / nucleotide_like / ion / other` |
| `is_covalent` | bool | 是否与受体聚合物共价相连（如糖基化连到 ASN） |
| `polymer_length` | int | 该 occurrence 含几个残基；**单残基(CCD)=1；BRANCHED>1** |
| `n_heavy_atoms` | int | **沉积态**重原子数（注意：可能 < 同 CCD 模板的原子数，见 §4.5） |
| `components` | list（非空） | 每个残基一项，字段见下；单残基长度为 1 |
| `inter_bonds` | list | 残基间共价键 `[res_i, "原子名_i", res_j, "原子名_j"]`（`res_*` 指 `components.index`）；**单残基(CCD)必为 `[]`；BRANCHED 必非空** |

> **空值与互斥约定（CCD vs BRANCHED 在字段上互斥）**：
> - `kind=CCD`（单残基）：`inter_bonds=[]`、`polymer_length=1`、对应 LigandObject 的 `smiles` **有值**。
> - `kind=BRANCHED`（多残基）：`inter_bonds` **非空**、`polymer_length>1`、对应 LigandObject 的 `smiles=""`。
> - 这些空 `[]`/`""` 与 `null` 同义，表示"无/不适用"。

**`components` 每一项的七个字段是什么意思**：

| 子字段 | 含义 | 作用 |
|---|---|---|
| `index` | 该残基在本 occurrence 内的序号(从 1) | `inter_bonds` 和 LigandObject 的 `residue_id` 都用它来指代残基 |
| `ccd_id` | 该残基的 CCD 代码（化学身份），如 `NAG` | 决定用哪个 CCD 模板生成化学图 |
| `label_asym_id` | mmCIF **label**(规范内部)链 id，如 `E`、`AA` | 规范、无空洞、每个实体实例一个；内部唯一定位 |
| `label_seq_id` | mmCIF **label** 残基序号 | 非聚合物/branched 残基原本常为空，此时**回退取 `auth_seq_id` 的值填入**（所以你看到的常是 auth 值） |
| `auth_asym_id` | **author/PDB** 链 id，如 `A`、`B` | PDB 网页/论文里看到的链 |
| `auth_seq_id` | **author** 残基序号，如 `1608` | PDB 网页里看到的 residue number |
| `icode` | insertion code（插入码） | 通常为空 |

> **为什么留两套编号**：mmCIF 同时有 `label_*`(规范内部体系)和 `auth_*`(作者体系)，二者可能不同。两套都存，既能回溯到 PDB 网页(auth)，又保持内部唯一(label)。

**`object_key` 与 `<6 位 hash>`**：
- 单残基：`CCD:<CCD_ID>`，如 `CCD:NAG`、`CCD:HEM`。
- 多残基：`BRANCHED:<CCD-CCD-...>:<6位hash>`。
- **`<6位hash>` = 对 (该 occurrence 的 CCD 序列 + 残基间键集合) 做 md5、取前 6 位十六进制**，代码即 `md5(json.dumps({"ccds":[...], "bonds": sorted(inter_bonds)}))[:6]`。
- **它的作用**：同样的残基序列可能有**不同的连接拓扑**；hash 把"残基列表相同但连法不同"的糖链区分成不同对象。
- **真实例子**：本项目数据里 `NAG-NAG-BMA-MAN-MAN-MAN-MAN-MAN-MAN-MAN` 出现了 `2ae773`、`7d514b`、`e15524` **三个不同 hash**——10 个残基一字不差，但 `inter_bonds` 不同，于是是三个不同的 LigandObject。
- 落盘文件名把 `:` 等敏感字符转义为 `_`，如 `CCD:NAG → CCD_NAG.npz`、`BRANCHED:...:2ae773 → BRANCHED_..._2ae773.npz`。

**例①（残基数=1，small molecule HEM；真实数据 7d3f cand 8）**：
```json
{"pdb_id":"7d3f","candidate_id":8,"kind":"CCD","object_key":"CCD:HEM","type_tag":"small_molecule",
 "is_covalent":false,"polymer_length":1,"n_heavy_atoms":43,
 "components":[{"index":1,"ccd_id":"HEM","label_asym_id":"G","label_seq_id":1601,
   "auth_asym_id":"A","auth_seq_id":1601,"icode":""}],
 "inter_bonds":[]}
```

**例②（残基数=1，单糖 NAG，且共价连到受体；真实数据 7d3f cand 0）**：
```json
{"pdb_id":"7d3f","candidate_id":0,"kind":"CCD","object_key":"CCD:NAG","type_tag":"sugar",
 "is_covalent":true,"polymer_length":1,"n_heavy_atoms":14,
 "components":[{"index":1,"ccd_id":"NAG","label_asym_id":"AA","label_seq_id":1608,
   "auth_asym_id":"C","auth_seq_id":1608,"icode":""}],
 "inter_bonds":[]}
```

**例③（BRANCHED 10 糖链；真实数据 7d3f cand 4，节选）**：
```json
{"pdb_id":"7d3f","candidate_id":4,"kind":"BRANCHED",
 "object_key":"BRANCHED:NAG-NAG-BMA-MAN-MAN-MAN-MAN-MAN-MAN-MAN:2ae773",
 "type_tag":"sugar","is_covalent":true,"polymer_length":10,"n_heavy_atoms":116,
 "components":[{"index":1,"ccd_id":"NAG","label_asym_id":"E","label_seq_id":1,"auth_asym_id":"E","auth_seq_id":1,"icode":""},
   {"index":2,"ccd_id":"NAG","label_asym_id":"E","label_seq_id":2,"auth_asym_id":"E","auth_seq_id":2,"icode":""},
   {"index":3,"ccd_id":"BMA","label_asym_id":"E","label_seq_id":3,"auth_asym_id":"E","auth_seq_id":3,"icode":""}, "… 共 10 项"],
 "inter_bonds":[[1,"O4",2,"C1"],[2,"O4",3,"C1"],[3,"O3",4,"C1"],[3,"O6",7,"C1"],
   [4,"O2",5,"C1"],[5,"O2",6,"C1"],[7,"O6",8,"C1"],[8,"O2",9,"C1"],[7,"O3",10,"C1"]]}
```
> 读 `inter_bonds`：`[1,"O4",2,"C1"]` = 第 1 个残基的 `O4` 原子 与 第 2 个残基的 `C1` 原子 之间有一条共价键。

---

### 4.4 `ligand_objects/{safe_object_key}.npz` ★（核心）

**去重的配体化学对象**（同一 `object_key` 全局只存一份，跨所有 PDB 复用）。沿用 Emap2lig 的 `LigandObject` 血统。`np.load(..., allow_pickle=True)` 后包含：

| key | 类型/shape | 含义 |
|---|---|---|
| `smiles` | str | SMILES；**单 CCD 有值；BRANCHED 必为空串 `""`**（与 occurrences 的 `inter_bonds` 非空互斥呈现） |
| `atom_names` | object[M] | 每个原子的字符串名（如 `"C1"`），行序与 `atoms` 一致 |
| `atoms` | 结构化数组[M] | 每个重原子一行，子字段见下 |
| `bonds` | 结构化数组[E] | 每条键一行，子字段见下 |
| `name` | str | = `object_key`（如 `CCD:NAG`） |
| `residue_names` | object[R] | 每个残基的**真实 CCD 名**，如 `["NAG"]` 或 `["NAG","NAG","BMA","MAN",...]` |
| `symmetries` | list | 当前恒为空 `[]`（与 `null` 同义：暂不提供对称性） |
| `blobs` | None | 推理期字段，训练数据恒 `None` |

**`atoms` 结构化数组的每个子字段**（最容易劝退新手，逐个解释）：

| 子字段 | dtype·shape | 含义 | 怎么解码 |
|---|---|---|---|
| `name` | int8 × 4 | 原子名编码 | 每个数 `=ord(字符)-32`，右补 0。例：`[35,16,17,0]` → `35→'C', 16→'0', 17→'1'` → `"C01"` |
| `element` | int8 | 元素 | **原子序数**：C=6, N=7, O=8 |
| `charge` | int8 | 形式电荷 | 如 -1/0/+1 |
| `coords` | float32 × 3 | **占位，恒为 (0,0,0)** | ⚠️ 不是坐标，别用 |
| `ref_pos` | float32 × 3 | **参考构象坐标(Å)** | CCD/RDKit 理想构象，几何先验，**不是真实 pose** |
| `is_present` | bool | 占位（本文件内恒 False） | 真实存在与否看 `ligand_coords` 的 `present_` |
| `chirality` | bool × 7 | 手性 one-hot | 顺序见 §10 |
| `in_ring` | bool × 4 | 是否在 3/4/5/6 元环 | |
| `residue_id` | int32 | 属于第几个残基(从 1) | 对应 `components.index`；单残基恒 1 |

**`bonds` 结构化数组的子字段**：`atom_1`,`atom_2`(int32，`atoms` 里的行下标)、`type`(bool×5 one-hot：SINGLE/DOUBLE/TRIPLE/DATIVE/AROMATIC)、`in_ring`(bool×4)。

**例（真实数据 `CCD:9Z9` 的 `atoms[0]`）**：
```python
atoms[0] = ([35,16,17,0], 6, 0, [0.,0.,0.], [-3.57,-0.78,1.002], False,
            [F,F,F,F,T,F,F], [F,F,F,F], 1)
# name=[35,16,17,0]→"C01"; element=6→碳; charge=0; coords=占位0; ref_pos=(-3.57,-0.78,1.002);
# is_present=False(占位); chirality 第4位=CHI_UNSPECIFIED; 不在小环; residue_id=1
atom_names[0] = "C01"
bonds[0] = (24, 25, [T,F,F,F,F], [F,F,F,F])   # 第24与第25个原子之间一条单键
```
**BRANCHED 例（真实数据 `BRANCHED:...:2ae773`）**：`atoms` 长度 126；`atoms[0].name=[35,17,0,0]→"C1"`，`residue_id=1`，`in_ring=[F,F,F,T]`(6 元环)；`residue_names=["NAG","NAG","BMA","MAN","MAN","MAN","MAN","MAN","MAN","MAN"]`；`smiles=""`。

> **⚠️ 配体有三套坐标，别拿错**：`atoms["coords"]`=占位 0；`atoms["ref_pos"]`=参考构象(先验)；**真正的沉积态真实坐标在 `ligand_coords.npz` 的 `coords_{candidate_id}`**（见 §4.5）。要"配体在密度图里的真实位置"，永远用后者。

---

### 4.5 `parse/{pdb_id}/ligand_coords.npz` ★（核心）

> **一个 pdb 只有一个 `ligand_coords.npz`**，里面用 key 后缀 = `candidate_id` 区分该 pdb 的各 occurrence：`coords_0/present_0, coords_1/present_1, …`。**对应关系靠 key 里的 `candidate_id`，不是靠分文件。**

每个**通过解析的** occurrence 一组数组，行序与该 occurrence 的 `LigandObject.atoms`（§4.4）**逐行对齐**：

| key 模式 | dtype·shape | 含义 |
|---|---|---|
| `coords_{cid}` | float32 (M,3) | 第 `cid` 个 occurrence 的沉积态真实坐标(Å)；**缺失原子填 `nan`** |
| `present_{cid}` | bool (M,) | 第 i 个模板原子是否真在沉积结构里 |
| `centroid_atom_{cid}` | float32 (3,) | `coords[present]` 的重原子几何中心，世界 XYZ Å；下游不得另行换口径 |

`M` = 该 occurrence 对应 LigandObject 的原子数（来自 **CCD 模板**）。

> **新手陷阱：模板 vs 沉积**。`occurrences.n_heavy_atoms` 是**沉积态**重原子数；LigandObject 的 `M` 是 **CCD 模板**原子数；二者可能不同——沉积里没建出来的模板原子，`present=False`、`coords=nan`。（小分子常相同；糖/柔性配体常因 leaving atom 或密度未解析而少几个原子。）

**例（真实数据 7d3f `coords_0`，即 NAG occurrence 0）**：
```python
coords_0.shape  == (15, 3)        # NAG 的 CCD 模板有 15 个重原子
present_0.sum() == 14             # 沉积里只建出 14 个 → 1 个模板原子缺失(nan)
coords_0[0]     == [75.919, 74.287, 27.503]   # 真实世界坐标(Å)
# 对照 occurrences cand 0 的 n_heavy_atoms=14，正好对上"沉积 14 / 模板 15"
```

---

### 4.6 `parse/{pdb_id}/receptor_tokens.npz`（核心）

受体（所有 `entity.type==polymer` 的蛋白/核酸重原子）的全原子 token，逐数组并列、长度均为 N：

| key | dtype·shape | 含义 |
|---|---|---|
| `coords` | float32 (N,3) | 世界坐标(Å) |
| `element` | uint8 (N,) | 原子序数 |
| `res_type` | uint8 (N,) | 残基类型 id（索引进 `RES_VOCAB`，见 §10；修饰残基映射到母体，未知→`UNK`） |
| `is_backbone` | bool (N,) | 是否主链原子（蛋白 N/CA/C/O；核酸 P/O5'/C5'/C4'/C3'/O3'） |
| `atom_name` | S4 (N,) | 原子名（ascii 字节串，如 `b'CA'`） |
| `res_index` | int32 (N,) | 所属残基的全局序号(0 起) |
| `chain_index` | int32 (N,) | 所属链的全局序号(0 起) |
| `bond_index` | int32 (2,E) | 无向唯一 COO，两端是本文件原子行下标，端点按小→大并字典序排序 |
| `bond_type` | uint8 (E,) | `single=0,double=1,aromatic=2,backbone=3,disulfide=4,covale=5,triple=6`；6 为向后兼容追加，0–5 不变 |
| `feat` | float32 (N,49) | 6 元素 + 25 残基 + 8 理化 + 1 质量 + 9 个 2 Å 邻居壳层 |

**例（schema 示意，取自蛋白 ALA 的 CA）**：`coords=[12.3,4.5,6.7]`，`element=6`(C)，`res_type=0`(ALA)，`is_backbone=True`，`atom_name=b'CA'`，`res_index=37`，`chain_index=0`。

> `feat` 的 25 类残基通道与 29 类 `res_type` 是两套编码：前者为 20 AA + A/U/C/G + X，DNA 映射到 RNA 母体；后者继续区分 DA/DC/DG/DT。局部密度是结构邻居计数，不是电子密度图。

### 4.7 `ligand_descriptors/{safe_object_key}.npz`（核心）

每个 `object_key` 全局一份：`mol_weight/n_heavy/n_rings/n_rotatable/wiener_index/graph_energy/radius_gyration` 均为 scalar；`atom_local (M,5) float32` 依次为图偏心率、1/2/3-hop 邻居数、最近环 hop。无环的最近环距离为 `-1`；回转半径是 `ref_pos` 的非质量加权几何 Rg；图能量使用无权邻接矩阵。

描述子临时 RDKit Mol 保留 LigandObject 的完整 CCD 模板和未出现 leaving atom，因此允许表观高价态：先 `UpdatePropertyCache(strict=False)`，再执行除 `SANITIZE_PROPERTIES` 外的全部 sanitize。该放宽只关闭严格价态检查；芳香性、kekulize、成环等剩余失败仍显式阻断，不会静默吞错或改写 LigandObject。

---

### 4.8 统计 / 诊断 / 辅助产物（不参与训练推理）

以下文件**绝不**作为训练/推理字段使用，仅供人工审查、体检和失败诊断；放在这里以免干扰核心产物。

- `reports/{pdb_id}.json`：**这是诊断性文件**。`{pdb_id, status, counts:{atoms, het_atoms, receptor_atoms, occurrences}, warnings:[...], failed_occurrences:[{candidate_id, reason:"resolve_failed", unmatched_deposited:[...]}]}`。`failed_occurrences` 里的 occurrence **不会**写入主产物。
- `reports/meta/{pdb_id}.meta.json`：**这是辅助性文件**——EMDB `/entry/{emdb_id}` 的原样 JSON（外部 schema，体量大）。蒸馏后的分辨率已进 `pair_list` 的 `resolution_info`，一般无需直接读它。
- `reports/resolution_summary.json`：**这是统计性文件**——本批样本的分辨率状态计数（`single_unique / multi_candidate_consistent / ambiguous_emdb / fallback_rcsb / rcsb_disagree / missing / emdb_metadata_error`）+ 少量示例。
- `reports/_failed_parse.jsonl`：PDB 级解析失败（每行 `{pdb_id, stage:"parse_failed", error}`）。**SLURM array 分片运行时**文件名带后缀，形如 `_failed_parse.part_0000_of_0006.jsonl`。
- `reports/_failed_download.jsonl`：下载失败（每行 `{pdb_id, emdb_id, resource, error}`）。同上，分片时为 `_failed_download.part_XXXX_of_YYYY.jsonl`。
- legacy `_failed_*` 只供诊断；当前分片即使无失败也会原子写空文件以清除旧污染。release gate 只消费 `reports/runs/{run_id}/...`，不根据 legacy 文件是否存在判断本轮成败。

#### Stage C source-dirty audit/apply

`scripts/snapshot_source_dirty.py` 用带 UTC offset 的显式 mtime 窗口冻结 dirty PDB 清单，要求预期数量完全一致，并把清单 SHA-256 写入 summary。`scripts/c_ccd_prefetch.py` 是 source 迁移中唯一允许联网补足 CCD cache 的阶段，完成后 audit/apply 均强制 cache-only。若 current source 新增了此前 `resolve_failed` 的 occurrence，且其 LigandObject 已存在但描述符尚未物化，`scripts/c_descriptor_prefetch.py` 可在最终 audit 前按冻结 object-key 清单以 `overwrite=False` 补齐 `ligand_descriptors/`；run-scoped records 必须同时绑定输入清单、源 LigandObject、实现和最终 descriptor 的 SHA-256。它不写 canonical `parse/`、不改变科学 schema，成功证据不可被失败或新实现静默覆盖。`scripts/c_source_repair.py` 必须使用独立 `repair_run_id`，分两次调用：先 `--mode audit`，仅当全集合都是 `exact` 或 `atom_name_only` 时才能 `--mode apply`。

- `exact`：基础数组和 ligand-side 均一致；若旧 receptor 已含完整新字段，`bond_index/bond_type/feat` 也须与当前 source 重建逐位一致。不写任何 C 文件。
- `atom_name_only`：occurrence、配体核心 `coords/present` 和六个其余受体基础数组逐位不变；当前 atom name 还必须非空、残基内唯一。严格 CCD 身份、atom-name 唯一性/覆盖和元素一致性只约束实际发生改名的 residue，不能被无关 `N/UNK` 占位 residue 误伤。旧 receptor 缺少 `bond_index/bond_type/feat` 时没有派生比较基线，但这不能豁免任何 ligand/base 漂移；当前完整重建通过后，apply 一次性补齐三项派生字段。旧 receptor 已完整时仍执行 feat 全局不变和未改名子图 bond 不变门禁。只更新 `receptor_tokens.npz` 的 `atom_name/bond_index/bond_type/feat`，额外 provenance key 原样保留。
- `blocked/failed`：任一即阻止全局 apply。

每条 audit 冻结 mmCIF、旧 receptor、occurrences、ligand_coords、单样本 report 五个直接输入，以及所引用 LigandObject/CCD cache 依赖闭包；summary 还冻结全部 `code/*.py` 与 repair CLI 的实现哈希。ID 清单和 audit JSONL 从各自同一份已哈希字节解析，apply 拒绝实现漂移。apply 先做全集合 preflight，再在 per-PDB artifact lock 内复核、cache-only 重建和 commit 前 CAS。中断时可能已有一部分 receptor 完成原子替换，因此**幂等恢复单位是重新运行完整 audit→apply**，不是单独重放旧 apply records。

本轮冻结的 14-PDB ligand-side source revision 由用户单独授权走 `scripts/c_source_rebuild.py`，不放宽上述通用分类。专用 audit 先把完整 `occurrences/ligand_coords/receptor/report` 写入 run-scoped staging，精确核对新增/删除/reassigned 计数及所有匹配 occurrence 的 coords/present/centroid；联合 2,156 条 pre-apply gate 把这些记录标成 `delegated_full_rebuild_ready` 后仍必须做到 blocked=0、failed=0，才允许 canonical 写入。apply 在首个 commit 前完成全部 before backup 和二次全局 CAS，每个 PDB 用 durable transaction receipt、原子单文件替换及异常 rollback 收敛。`primary_key_migration.records.jsonl` 只用于本次审计与恢复，不是 Stage C 主产物、训练字段、stable occurrence id、跨 source 永久映射或未来自动 rebuild 许可。

带 `--pdb_ids_file` 的 `c_parse.py` 会拒绝复用已有正式 A guard 或任何 Stage C status 的 run id；filtered smoke/repair 必须使用全新独立 run id。正式 run 的 C 状态只能由无过滤全量命令刷新，防止把 22,386 行状态覆盖成子集。

---

## 5. Stage D：`labels/{pdb_id}/atom_labels.npz`

| key | dtype·shape | 含义 |
|---|---|---|
| `binding_atom` | bool (N_rec,) | 最近 present ligand 重原子距离 `<= binding_threshold` |
| `instance_id` | int32 (N_rec,) | binding 原子取最近 occurrence cid，背景固定 `-1` |
| `nearest_dist` | float32 (N_rec,) | 每个受体原子的真实最近距离，背景也保留 |
| `binding_threshold` | float32 scalar | 正式默认 4.0 Å，含等号 |

还保存 schema version、受体/配体坐标输入 SHA-256。完全等距时按较小 `candidate_id`、再按拼接行号稳定决胜。

## 6. Stage E：密度与体素标签

### 6.0 Pocket Plus MRC 祖传基线与全部适配差异

MRC 数值原语的可信祖先是 `Pocket_Plus/processedPDB_EMDB_binder/utils/mrc_tools.py`；vendoring 时仓库 HEAD 为 `f4c3e5ce3c706f8d52fed7fa3cc40570cfb5b4b5`，该文件最后修改 commit 为 `a8380721fb555d42408a5ab558a675caa537ed80`，完整源文件 SHA-256 为 `d8e543e4c6763a44cde3d350434c51506d794ecf1c2143db2ce304419bc06ca8`。`mrc_pocket_legacy.py` 原样保存 `load_map`、`make_cubic`、`normalize_voxel_size`、`rescale_real`、`rescale_fourier`、`make_model_grid` 六个函数，副本 SHA-256 为 `acf74c256e6d88f9e40e972c0d86d35262aa9ac6ac790346adbd54e3109e8a45`；六个函数的源码片段和标准化 AST 均为零差异。机器可读来源、逐函数哈希和模块级差异在 `mrc_pocket_legacy.source.json`，回归在 `tests/test_mrc_pocket_legacy_parity.py`。Git 提交 `6de3fb8` 冻结该快照，`.gitattributes` 强制副本使用 LF，避免 Windows/Linux checkout 改变字节哈希。

祖传函数体之外只有以下适配，其他数值逻辑不得在 AdaLigand 内另写一套：

| 位置 | 与祖先的差异 | 必要性与行为影响 | 回归证据 |
|---|---|---|---|
| `mrc_pocket_legacy.py` 模块层 | 只选六个相关函数；imports 缩为 `mrcfile/numpy`；增加来源 Docstring | 隔离无关的 class-weight、B-factor、padding/save helper 及其依赖；六个函数体不变 | manifest + 逐函数源码/AST hash |
| `mrc.py::load_map` | `Path→str`；显式暴露祖传 `multiply_global_origin`；返回值包成 `MapGrid`；网格实体化并转 float32；只做 shape/finite/positive 验收 | 适配 AdaLigand 接口、关闭 MRC handle 后不保留悬空 memmap，并满足 artifact dtype；不改祖传轴/origin 数值 | 六轴、gzip、OWNDATA、两种 origin mode parity |
| `mrc.py::make_canonical_grid` | 校验正 target；调用祖传 `make_model_grid`；返回值包成 `MapGrid` 并转 float32；核对 padded 输入与输出物理长度闭合 | AdaLigand 参数/落盘 dtype 适配；普通 `all_equal/all_diff` 的 shape、padding、Fourier、origin 与实际 voxel 全由祖传函数决定 | wrapper 与祖传函数逐值 parity、偶数 shape、actual voxel、物理闭合 |
| `mrc.py::_rescale_real_mixed_axis_compat` | 代码与祖传 `rescale_real` 相同，唯一行为差异是条件由 `np.all(out_sz != box.shape)` 改为 `np.any(...)`；仍调用祖传 `rescale_fourier`，并直接复用祖传已经返回的补偶 grid | 全量 header 审计只发现 EMD-11978/12465 两张 mixed-axis 图；祖传分支会跳过全部 resize 却返回拟输出 voxel。本兼容只在物理闭合失败且严格满足 mixed 关系时触发，模式显式落盘；复用补偶结果避免奇数输入重复分配大型数组 | mixed 常数/odd-shape/幅值/shape/闭合回归；全量审计 2/22,269；两张真实图 smoke |
| native 与 generated 调用点 | native EMDB 使用祖传默认 `multiply_global_origin=True`；AdaLigand/Chimera 写出的 `nstart=0`、header.origin 为 Å 的图使用 `False` | 保留 Pocket native-map 语义，同时让非单位 voxel 的 canonical MRC→Chimera→读取闭合 | 非单位 voxel+非零 origin 往返、合成 C→G smoke；真实 Chimera smoke 的两图 header/重载几何闭合 |
| `write_canonical_mrc` | AdaLigand 自有原子 writer，标准轴、`nstart=0`、header.origin 直接写 Å | 为 Chimera `onGrid` 提供显式几何；它不是祖传六函数的修改 | 标准 header 与非单位 voxel 往返 |
| E/F artifact/QC | E1/E2/E3 schema 由 v1 升 v2；E1 保存 target、actual voxel、祖先/副本/算法/origin-mode、native/even/canonical shape 与 resample mode；不再要求 actual voxel 精确等于 1，仍要求 exp/sim shape、actual voxel、origin 严格相同 | 阻止旧 Ada 独立重采样产物被复用，并让下游消费祖传返回的真实几何 | 旧 schema/算法拒绝、identity 精确匹配、非单位 voxel pair QC |
| recommended contour | Pocket grid 逐值不变；保存 `contour_native`、`contour_scale_to_canonical=prod(even_input)/prod(actual_output)`、`contour_canonical`，F 只把 canonical 值传给 Chimera；F provenance 与当前 E1 的三值/scale/mode/path/source 逐项绑定 | 祖传 FFT 不做点数幅值补偿；Ada 新增的 canonical-map contour CC 必须迁移 threshold 单位，但不能因此改 Pocket 训练输入；单独破坏 provenance 不能被幂等 skip 接受 | 常数 up/down、odd padding、随机 mask 0 mismatch、缺 contour 三 null、provenance 腐败重建、合成 C→G correlation 脚本 |

祖传 `make_model_grid` 的契约是“目标体素 + 偶数网格 + 物理长度决定实际 voxel”，不是把 header 强制声明为精确 1.0 Å。正式 target 仍为 `1.0`，但所有消费者必须读取 artifact 的 `voxel_size`。

正式 header-only 审计 run `adaligand_mrc_contract_audit_20260712T192000_v2` 覆盖 pair list 22,386 行、22,274 张唯一 EMDB 图：22,269 张 header 可读，其中 `all_diff=21,941`、`all_equal=326`、`mixed_equality=2`；5 张缺图与 B known failure 一致。mixed 仅为 EMD-11978/12465。22,267 张几何闭合图的 contour scale 分布为 min `0.000354`、median `0.943052`、p95 `3.152994`、max `56.895767`，证明 raw contour 不能原样用于 canonical 图。summary/risk SHA-256 分别为 `a9300d2d…44a7fe8` / `81784ee1…3a6712`；完整证据保留在服务器 run-scoped reports，不进入科学主键或训练字段。

真实 geometry smoke run `adaligand_mrc_geometry_smoke_20260712T200227` 直接使用两张 mixed 图和真实 Chimera 1.19：7b14 从 native `91×48×47` 得到 canonical/sim `94×48×48`，7nll 从 `101×55×88` 得到 `104×56×88`；两者 actual voxel 均非精确 1 Å、origin 均非零，canonical 与 sim 的 shape/voxel/origin 完全一致，两个 MRC 都是 `mapc/mapr/maps=1/2/3`、`nstart=0`，三维内容与受体包围盒 QC 零错误。机器 summary 和 Markdown SHA-256 分别为 `0e40d866…96957` / `451a6dce…de5`，完整 MRC、CIF、Chimera 脚本和日志保留在 `/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_mrc_geometry_smoke_20260712T200227/mrc_geometry_smoke/`。同一代码在本地与服务器 Python 3.10 均为 172 tests passed。

### 6.1 `exp.npz`

- `grid (1,Z,Y,X) float32`：native EMDB map 经 Pocket Plus 祖传函数按 **target=1.0 Å** 重采样得到的原始幅值；不归一化。
- `target_voxel_size float32 scalar=1.0`；`voxel_size (3,) float32` 是祖传函数按偶数输出 shape 返回的**实际 XYZ voxel**，通常接近但不强制逐轴等于 1.0；`origin (3,) float32` 是 `grid[0,0,0]` 体素中心的世界 XYZ 坐标。
- `contour` 与 `contour_native`（float32 scalar）保存主图 `map.contour_list.contour[*]` 中唯一 `primary=true` 的原始 level；`contour_scale_to_canonical float64` 保存祖传幅值比例；`contour_canonical float32 = float32(contour_native × scale)` 是 F 实际传给 Chimera 的 threshold。缺失/歧义时 native/canonical 均为 `NaN`、`contour_present=False`，scale 和 geometry provenance 仍保存；不递归误取 additional map，也不猜 fallback。
- `native_shape_zyx/even_input_shape_zyx/canonical_shape_zyx int64(3,)` 与 `resample_mode` 记录普通祖传或 mixed-axis 薄兼容路径。
- `schema_version=2`；`mrc_algorithm/mrc_ancestor_sha256/mrc_vendor_sha256/source_origin_mode` 冻结祖传 lineage。任何 v1 或旧 `scipy.signal.resample` identity 都必须重建，不能 skip。

### 6.2 `sim.npz`

在复用旧 `sim.npz` 或启动 Chimera 之前，E2 以 E1 `origin_xyz`为 map 下界，以 `origin_xyz+(shape_zyx[::-1]-1)*voxel_size_xyz` 为上界，并与 Stage C `receptor_tokens.coords` 的 XYZ 最小/最大值比较。对合法、有限、非空输入，任一轴超过 `1e-5 Å` 容差后仍完全分离时，状态固定为 `known_failed:model_map_frame_mismatch`，不运行 `molmap`、不写伪 `sim.npz`、不猜平移或 fitmap。坐标/map 自身的 dtype、shape、空值或非有限错误仍是 unknown。

专用于 receptor-only 模拟图：从首 model、与 C 同款 altloc 选择的重原子中**严格只留 `group_PDB==ATOM`**，所有 HETATM（含水、配体和共价修饰）均删除。标准模型写成只含 `_entry.id`（若源存在）与逐字段原样筛选 `_atom_site` 的最小独立 mmCIF；不复制会引用已删除 model/altloc/HETATM/H 原子的 `_atom_site_anisotrop`、`_struct_conn` 等类别。F 的完整模型沿用同一最小文档规则，但其 `_atom_site` 保留首 model 的 ATOM+HETATM 重原子。Chimera 在 E1 canonical MRC 上显式 `region all step 1 limitVoxelCount false`，再 `molmap ... onGrid`；不做第二次独立重采样。缺 resolution 时该样本记 `known_failed`，不猜默认值。

正式字段仍为 `grid/voxel_size/origin`，并保存 `schema_version=2`、resolution、Chimera 版本、输入 hash、`strict_hetatm_removed=True` 和 `generated_mrc_origin_mode=header_origin_angstrom_nstart_zero`。验收要求：`sim.grid.shape == exp.grid.shape == (1,Z,Y,X)`；两图实际 voxel 与 origin 相同，并且 sim 精确绑定当前 E1 identity；数组有限、非零、有方差且 X/Y/Z 每轴至少两个切片有内容；受体包围盒与网格相交。只有单平面的“伪三维图”会失败。

`e_density.py --timeout_seconds` 显式控制每次 Chimera `molmap` 的最长运行时间；正式默认仍为 3600 秒，超大 map/model 的受检恢复可显式延长，不能把超时降级成成功。Classic Chimera 1.19 对部分金属配位连接会在已经生成完整 MRC 后打印固定两行 `Error processing trigger "monitor changes":` / `KeyError: '?'`；外部工具层只豁免这一精确序列，同一日志中的其他 `Error`、Traceback、缺文件或无原子错误仍阻断，且豁免后必须继续通过输出存在、shape/voxel/origin、三维内容和受体包围盒全部 QC。

带 `--pdb_ids_file` 的 Stage E smoke/repair 必须使用没有正式 A guard、也没有既有 Stage E status 的独立新 `run_id`。正式 run 的 22,386 行 E 状态只能由无过滤、无 `--overwrite` 的全量命令刷新；子集修复只负责原子补齐公共 artifact，不能覆盖正式状态证据。

### 6.3 `ligand_area.npz`

- `union_mask (1,Z,Y,X) bool`。
- `mask_{cid} (K,3) int32`：唯一且字典序排序的稀疏 **ZYX** voxel 索引。
- `centroid_voxel_{cid} (3,) float32`：字段名沿用计划，但数值明确是 mask 体素中心均值的**世界 XYZ Å**。

球半径按原子元素：C/N/O/P/S 使用计划锁定的 1.70/1.55/1.52/1.80/1.80 Å；其他有效元素调用 RDKit `PeriodicTable.GetRvdw`，绝不使用统一默认半径。实现只枚举逐原子局部 bbox/stencil，不构造 `D*H*W` 世界坐标 KD-tree。

## 7. Stage F：四种 CC、配体 Q 与口袋 Q

F 在读取当前 E1 和 Stage C polymer receptor token 坐标（`receptor_tokens.coords`）后，先复用 E2 的同一 model-map 包围盒检查，然后才允许读取/复用质量产物或启动 Chimera/MapQ。该 token 坐标是 E/F 共用 frame anchor，不等同于 E2 严格 ATOM-only 模型或 F 完整 ATOM+HETATM 模型。完全不相交时 F 同样记 `known_failed:model_map_frame_mismatch`；实现不包含 PDB allowlist、坐标修复或 fitmap。前置检查不替代后续 full-model sim 的 shape/voxel/origin/三维内容 QC，其他几何或工具异常仍阻断 gate。

`quality/{pdb_id}.jsonl` 每个 occurrence 一行。配体本身保存 `q_score`（mean，兼容字段）、`q_score_median`、`q_score_min`、`n_valid`、`n_present`；对应受体口袋保存 `pocket_q_score`、`pocket_q_score_median`、`pocket_q_score_min`、`pocket_n_valid`、`pocket_n_atoms`、`pocket_radius_angstrom=6.0`。另外保存 `map_resolution`、`livq=null`，并重复以下四个 PDB 全局原始量：

| 字段 | mask | 是否减均值 |
|---|---|---|
| `cc_contour` | 实验 canonical 图高于 `contour_canonical`（native recommended contour 已按祖传幅值比例映射）的 grid 点 | 否 |
| `cc_contour_about_mean` | 同一 contour mask | 两图各自在 mask 内减自身均值 |
| `cc_all` | Chimera `aboveThreshold false`，即**实验图非零 grid 点**，不是所有 padded box 体素 | 否 |
| `cc_all_about_mean` | 同一实验图非零 mask | 两图各自在 mask 内减自身均值 |

实验图必须是 `measure correlation` 的第一张图。contour 缺失时只允许前两项为 JSON `null`；`cc_all*` 仍计算。四项非空值必须有限且在 `[-1,1]`。

Q-score 使用 native EMDB map、首 model/规范 altloc 的完整 `ATOM+HETATM` 重原子模型、MapQ 2.9.7 固定包（commit `c3bdf...`，zip SHA-256 `ee004e...fe55`）、显式 `sigma=0.4,np=8`。MapQ 输出先按原始 `_atom_site.id` join，再核对完整身份和坐标；随后用 `components.index + atom_name` 投到 LigandObject 行序。禁止按输出行序、残基遍历顺序或坐标最近邻猜测。正式 F 默认 12 个 PDB 并发，因此 MapQ 子进程上限约 96；真实 smoke 还会把 np=8 的配体/口袋子集逐 id 对照已保存的 np=1 基线，验证并行数值一致性。

固定 MapQ CLI 的 CIF 分支漏掉了 `mmcif.ReadMol` 结果的 `chimera.openModels.add`，会在 classic Chimera 1.19 中触发 `ValueError: unopen model`。适配器不修改安装目录，而是在每个 PDB 的 scratch 中生成 basename 仍为 `mapq_cmd.py` 的一次性兼容副本，只插入这一行；原始 CLI SHA、固定 zip SHA 和补丁标识 `mapq_cmd_cif_readmol_openmodels_v1` 均写入 provenance。任何上游源码 anchor 漂移会直接失败，不静默跳过补丁。

口袋定义固定为：同一首 model/altloc 选择下，`group_PDB=ATOM` 的受体重原子中，到该 occurrence **任一** `present=True` 配体重原子的距离 ≤ 6.0 Å 的原子并集。它不是配体中心球，因此长条或分支配体两端的局部受体都能进入；配体自身 HETATM 不进入口袋。若某个 occurrence 的 6 Å 包络确实没有受体原子，保留该 occurrence：写 typed empty 原子/Q 数组、`pocket_n_atoms=pocket_n_valid=0`、三个 Q 聚合为 JSON `null`、`pocket_status=no_receptor_atoms_within_radius`；不得把它升级为整 PDB 失败或预先过滤。

`quality_atoms/{pdb_id}.npz` 保存 `qscore_{cid} (M,) float32`；`present=False` 固定 `NaN`，成功 occurrence 必须 `n_valid == n_present`。同时保存数值升序的 `pocket_atom_site_id_{cid} (K,) int64` 与同序 `pocket_qscore_{cid} (K,) float32`，以及标量 `pocket_radius_angstrom` 和 `pocket_definition`；非空口袋必须 `pocket_n_valid == pocket_n_atoms == K > 0`，空口袋则两个 typed array 均为 `(0,)` 且聚合为 null。两种状态都保留 occurrence。不复制整份受体 Q 表，只保留每个 occurrence 实际口袋的可审计子集。四量公式、口袋规则、工具版本、输入 manifest 和日志位置另见 `quality/{pdb_id}.provenance.json`。

## 8. Stage G：分布与正式过滤

- `--mode analyze` 自动检查本轮 D/E/F 每个 A 样本恰有一个终态，unknown、重复、额外或 silent missing 立即失败；随后写 `reports/runs/{run_id}/stage_g_analysis/quality_distribution.json` 和 `candidates.pending.jsonl`。分布同时包含四个 CC、配体 Q 和口袋 Q 原始统计；它**不会**写 `keep_list.jsonl`。
- `--mode filter --config filter_config.json` 只接受唯一的 `schema_version=2` map-level 契约；schema 1 明确拒绝，不保留 occurrence 级旧语义。过滤直接扫描 `candidates.pending.jsonl` 同款扁平字段，不读取 `quality_atoms`、原始密度图，也不重新运行 CC、MapQ 或 Q-score。

schema v2 先按 `pdb_id` 聚合。每个 eligible PDB 必须至少有一个 occurrence；同一 PDB 重复保存的 `map_resolution` 和配置选定的 CC 必须各自唯一一致，否则视为上游契约错误。四种可选 CC 是 `cc_contour`、`cc_contour_about_mean`、`cc_all`、`cc_all_about_mean`；选中的 contour CC 若为合法 `null`，该 map 失败，不能偷换另一种 CC。

对每个 occurrence：

```text
pair_pass = (q_score > ligand_q_min) AND (pocket_q_score > pocket_q_min)
```

两个 Q 均为**严格大于**。空口袋的 `pocket_q_score=null` 固定令 `pair_pass=false`，但仍计入 occurrence 总数。随后计算：

```text
qualified_fraction = n_pair_pass / n_occurrences
map_pass = (
    selected_cc >= cc_min
    AND map_resolution <= resolution_max
    AND qualified_fraction >= qualified_pair_fraction_min
)
```

CC、分辨率和比例边界均含等号。一旦 map 通过，`keep_list.jsonl` 保留该 PDB 的**全部** occurrence，包括自身 `pair_pass=false` 的 occurrence；pair 判定只评价整张 map，不是第二次 occurrence 剪枝。

配置必须逐项显式提供以下字段；策略字符串和两个布尔量是固定契约，不是可切换回退：

```json
{
  "schema_version": 2,
  "cc_field": "cc_all_about_mean",
  "cc_min": 0.6,
  "resolution_max": 5.0,
  "resolution_comparison": "inclusive",
  "ligand_q_min": 0.7,
  "pocket_q_min": 0.65,
  "qualified_pair_fraction_min": 0.8,
  "empty_pocket": "fail_and_count_denominator",
  "keep_only_maps_that_pass": true,
  "keep_all_occurrences_in_passing_map": true
}
```

上例只展示 schema 形状和候选数值，不是 CLI 默认值，也不会被 `g_analyze.sbatch` 自动执行。正式 filter 仍须显式提供配置文件；配置原文 hash、规范化语义和输入 manifest 进入 `stage_g/summary.json`。

`stage_g/map_filter_diagnostics.jsonl` 每个 eligible PDB 一行，保存 selected CC/value/pass、resolution/pass、occurrence 总数、空口袋数、`n_pair_pass`、`qualified_fraction`、map pass/reasons 和 occurrence 判定明细；`excluded_maps.jsonl` 是未通过 map 的精简索引。`keep_list.jsonl` 稳定按 `(pdb_id,candidate_id)` 排序；known-failed PDB 明确排除；任何 unknown/silent missing 阻塞。

## 9. run-scoped 终态与失败纪律

每个 stage 分片原子写 `reports/runs/{run_id}/{stage}/status.part_XXXX_of_YYYY.jsonl`。每个 PDB 的 `status` 只允许 `success/skipped/known_failed/unknown_failed`。只有在 `failures.KnownFailureCode` 明确枚举的数据不适用情形才可继续；普通 Python 异常、schema 漂移、Chimera/MapQ 输出异常均为 unknown，最终 gate 必须阻塞。

`model_map_frame_mismatch` 是窄化的输入不适用失败：只接受“合法 map 网格 + 合法 Stage C 受体坐标 + XYZ 包围盒完全分离”，detail 保存 map/model 上下界、XYZ/ZYX 轴序、`1e-5 Å` 容差和 `no_transform_or_fitmap` 策略。密度全零、shape/origin/voxel 不同、无效坐标或任意外部工具失败均不得借此降级。

`reports/runs/{run_id}/exclusions.jsonl` 是单次正式 run 的显式排除清单，不是科学黑名单。每行必须完整给出 `schema_version/pdb_id/run_id/stages/reason/detail/authorization/decision_scope/downstream_policy/evidence`；`decision_scope` 固定为 `current_run_only`，`downstream_policy` 固定为 `exclude_from_training_and_inference`，`stages` 只能覆盖 E/F。命中项在 E/F 写 `known_failed:run_policy_excluded` 和完整 manifest/provenance，仍保留在 A 样本宇宙、状态分母与审计中；不删除 `pair_list`，不伪造 success，G 也不会把它写入候选。清单缺字段、跨 run、重复 PDB、非法 stage 或哈希漂移都必须 fail-fast。

Stage E 的完整 artifact 是同一 PDB 的 `exp.npz`、`sim.npz`、`ligand_area.npz` 三者都存在且分别通过既有校验；只有一项或两项的 partial 三件套不算完成。`scripts/stage_e_long_tail_cutoff.py` 只在用户已经为当前 run 给出明确截止授权后使用：它同时冻结 predecision/posttermination、before/after manifest 和 summary，验证补足 job 身份、时间先后、完整三件套边界与终止证据，再原子更新清单；重复运行必须字节级幂等。当前正式 run 的 cutoff code/CLI 已通过本地与远端 207 tests，最终 exclusion manifest SHA-256 为 `380844d0…325f`；这份 before/after 审计不改变通用 E 成功定义或未来 run 的科学契约。

---

## 10. 编码解码速查表

- **`element`**：原子序数（C=6, N=7, O=8, P=15, S=16, …）。
- **原子名 `name`(int8×4)**：每位 `=ord(字符)-32`，右补 0；反解 `chr(值+32)`。
- **`RES_VOCAB`（`res_type` 的索引表，0..28）**：
  `[ALA,ARG,ASN,ASP,CYS,GLN,GLU,GLY,HIS,ILE,LEU,LYS,MET,PHE,PRO,SER,THR,TRP,TYR,VAL, A,C,G,U,DA,DC,DG,DT, UNK]`。
- **`chirality`(bool×7) 顺序**：`[CHI_OTHER, CHI_OCTAHEDRAL, CHI_TETRAHEDRAL_CW, CHI_TRIGONALBIPYRAMIDAL, CHI_UNSPECIFIED, CHI_TETRAHEDRAL_CCW, CHI_SQUAREPLANAR]`。
- **`bond.type`(bool×5) 顺序**：`[SINGLE, DOUBLE, TRIPLE, DATIVE, AROMATIC]`。
- **`in_ring`(bool×4) 顺序**：3 元环 / 4 / 5 / 6。
- **`type_tag`**：`small_molecule / sugar / peptide_like / nucleotide_like / ion / other`。
- **`resolution_info.status`**：`single_unique`(唯一)、`multi_candidate_consistent`(多候选一致)、`ambiguous_emdb`(EMDB 多个不同值，取首个)、`fallback_rcsb`(EMDB 无值回退 RCSB)、`rcsb_disagree`(RCSB 与选定值不一致)、`missing`(无候选)。

---

## 11. 一个 occurrence 的三件产物如何对齐

```text
occurrences.jsonl 第 K 行  ──candidate_id = cid──┐
                                                 │ 同一个 cid 串起三件产物
ligand_objects/<object_key>.npz                  │
  atoms[i] / atom_names[i] / residue_id           │   ← 化学身份 + 参考构象(ref_pos)，去重存
parse/{pdb}/ligand_coords.npz                     │
  coords_{cid}[i] / present_{cid}[i]              ┘   ← 真实坐标，行序与 atoms[i] 完全一致
```
即：`occurrences` 给"是谁(object_key) + 组分"，`ligand_objects` 给"化学图 + 参考构象"，`ligand_coords` 给"这一份的真实坐标"。三者靠 `candidate_id` + 行序对齐。

---

## 12. 怎么读 + 怎么自检

```python
import json, numpy as np
root = "${ROOT}"; pdb = "7d3f"
occ = [json.loads(l) for l in open(f"{root}/parse/{pdb}/occurrences.jsonl", encoding="utf-8")]
co  = np.load(f"{root}/parse/{pdb}/ligand_coords.npz", allow_pickle=True)
for o in occ:
    cid = o["candidate_id"]
    if f"coords_{cid}" not in co:          # 该 occurrence 解析失败被丢弃
        continue
    lig = np.load(f"{root}/ligand_objects/{o['object_key'].replace(':','_').replace('/','_')}.npz", allow_pickle=True)
    assert co[f"coords_{cid}"].shape[0] == lig["atoms"].shape[0]      # 行数对齐
    assert co[f"present_{cid}"].sum() == o["n_heavy_atoms"]           # 沉积原子数对上
```

**自检期望**：`coords_{cid}` 行数 == 对应 LigandObject 原子数；`present_{cid}.sum()` == `occurrences.n_heavy_atoms`；`occurrences.jsonl` 里出现的 `candidate_id` 必有同号 `coords_/present_`（失败的不会出现）。

---

## 13. 当前覆盖与边界

- 代码与契约覆盖 **Stage A–G**；服务器正式全量产物以本轮 run-scoped release 报告为准，不以代码存在或历史文件计数代替完成。
- `raw/emdb_maps/` 是否生成取决于 `b_download.py --resources` 是否含 `map`（默认含）。Stage C 不消费 map。
- 解析失败的 occurrence 记 `resolve_failed` 入 `reports`，**不**进主产物；严格依赖 `_atom_site.label_atom_id` 与 CCD 原子名精确对齐（无图同构兜底）。
- 当前正式 run `adaligand_ag_20260711T154658` 已完成 Stage E 长尾 cutoff/v3 放行；2026-07-13 21:04:43 起由原 `316115` allocation 以 E24、无 filter、无 `--overwrite` 刷新正式全量状态。此运行事实不替代最终 DE release gate；F/G 仍只由原 afterok 链释放。
- G 的唯一 map-level schema v2 算法已经锁定；最终分辨率、selected CC、配体 Q、口袋 Q 和合格比例数值仍按“先看正式分布再显式配置”。当前 DAG 只运行 analyze，不自动消费示例配置，也不冒充最终科学筛选或写 `keep_list`。
- 历史 A–C 见 `文档/exec_plan/数据下载与解析.md`；当前长任务日志见 `文档/exec_plan/A-G数据流水线实现与全量运行.md`；规格见 `文档/规划文档/数据处理_v2.md`。
