# AdaLigand Stage1（数据下载与解析）产物契约

> **这份文档是什么**：Stage1（数据侧 Stage A–C）**正式运行后产生的全部文件、字段、形状、含义和真实例子**。目标是新手不读代码也能看懂每个产物。
> **不是什么**：不是实现历史/决策记录（那些在 `文档/exec_plan/数据下载与解析.md`），也不是计划书（`文档/规划文档/数据处理_v2.md`）。本文只描述**当前接口现实**。
> **当前覆盖**：Stage A（枚举）、B（下载）、C（解析）。Stage D–G（标签/密度/质量/过滤）尚未实现，不产出。

---

## 1. 一句话总览 + 运行

三个脚本，依次产出 `raw/ → parse/ + ligand_objects/ + reports/`。所有产物都落在你用 `--root` 指定的根目录下（服务器正式跑时是一个绝对路径，例如 `/storage/.../AdaLigand/run1`）。

```bash
python scripts/a_enumerate.py --root ${ROOT} --part_id 0 --total_parts 1 --n_jobs -1
python scripts/b_download.py  --root ${ROOT} --resources mmcif,meta,map --n_jobs -1
python scripts/c_parse.py     --root ${ROOT} --n_jobs -1
```

**贯穿全程的主键**：`(pdb_id, candidate_id)`。`pdb_id` 一律小写；`candidate_id` 是该 PDB 内配体 occurrence 的稳定 0 起编号。

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
  reports/                          # 统计/诊断/辅助（不参与训练推理）
    {pdb_id}.json                   # 单样本解析报告
    meta/{pdb_id}.meta.json         # EMDB /entry API 原样响应(辅助)
    resolution_summary.json         # 本批分辨率状态统计(统计)
    _failed_parse.jsonl             # 若有 PDB 级解析失败才出现
    _failed_download.jsonl          # 若有下载失败才出现
```

---

## 3. 全局约定

- **世界坐标系**：所有坐标都是 mmCIF 沉积态的**世界坐标，单位 Å**；EMDB 密度图与之天然同框。
- **npz 一律不压缩**（`np.savez`），读快；用 `np.load(path, allow_pickle=True)` 打开。
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

**例（schema 示意，取自蛋白 ALA 的 CA）**：`coords=[12.3,4.5,6.7]`，`element=6`(C)，`res_type=0`(ALA)，`is_backbone=True`，`atom_name=b'CA'`，`res_index=37`，`chain_index=0`。

> 提示：本文件足以**无损复现 Pocket_Plus 的 49 维原子特征**——其"局部密度"是结构邻居计数（由 `coords` 重算），不是电子密度图，故**密度图非必需**；只需把 `element`/`res_type` 经查表展开、再跑邻居计数即可。

---

### 4.7 统计 / 诊断 / 辅助产物（不参与训练推理）

以下文件**绝不**作为训练/推理字段使用，仅供人工审查、体检和失败诊断；放在这里以免干扰核心产物。

- `reports/{pdb_id}.json`：**这是诊断性文件**。`{pdb_id, status, counts:{atoms, het_atoms, receptor_atoms, occurrences}, warnings:[...], failed_occurrences:[{candidate_id, reason:"resolve_failed", unmatched_deposited:[...]}]}`。`failed_occurrences` 里的 occurrence **不会**写入主产物。
- `reports/meta/{pdb_id}.meta.json`：**这是辅助性文件**——EMDB `/entry/{emdb_id}` 的原样 JSON（外部 schema，体量大）。蒸馏后的分辨率已进 `pair_list` 的 `resolution_info`，一般无需直接读它。
- `reports/resolution_summary.json`：**这是统计性文件**——本批样本的分辨率状态计数（`single_unique / multi_candidate_consistent / ambiguous_emdb / fallback_rcsb / rcsb_disagree / missing / emdb_metadata_error`）+ 少量示例。
- `reports/_failed_parse.jsonl`：PDB 级解析失败（每行 `{pdb_id, stage:"parse_failed", error}`）。
- `reports/_failed_download.jsonl`：下载失败（每行 `{pdb_id, emdb_id, resource, error}`）。
- 三个失败文件**仅在确有失败时出现**。

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

- 覆盖 **Stage A–C**。Stage D–G（原子标签、密度重采样、质量 Q-score、过滤）**未实现、无产出**。
- `raw/emdb_maps/` 是否生成取决于 `b_download.py --resources` 是否含 `map`（默认含）。Stage C 不消费 map。
- 解析失败的 occurrence 记 `resolve_failed` 入 `reports`，**不**进主产物；严格依赖 `_atom_site.label_atom_id` 与 CCD 原子名精确对齐（无图同构兜底）。
- 实现历史、决策、漂移收口见 `文档/exec_plan/数据下载与解析.md`；当前规格见 `文档/规划文档/数据处理_v2.md`。
