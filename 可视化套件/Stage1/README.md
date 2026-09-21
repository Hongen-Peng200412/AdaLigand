# Stage1 PyMOL 可视化会话

本目录把 AdaLigand 数据和既有 Stage1 评估产物组装为自包含的 PyMOL `.pse`。生成器只读源产物，不运行模型前向，不改变 blob 集合、`candidate_selected` 或正式评估结果。

## 两个入口

`build_session.py` 保留原有单模式入口。它读取一套 Pocket Plus `blobs + evaluation`，生成 `density`、`ground_truth`、`predictions` 三个平级组和独立 `receptor` 对象；既有调用参数不变。

`build_comparison_sessions.py` 是七模式正式入口。它让一个 PDB 的七套预测共享实验密度和 GT，可处理单个 `--pdb-id`，也可按 `--pdb-list` 批量处理。固定服务器路径、评估名称、F-alpha 和受体来源集中保存在 `profiles/stage1_7mode_pcv2_test0.json`，候选读取逻辑不根据模型名猜测路径。

## 七种模式

| scene | 训练或方法 | 评估模式 | scene 中显示的受体 |
| --- | --- | --- | --- |
| `unet_pcv2_f1_basic` | `unet_c1` pdb-centric-v2 | F1-F1 basic | 无受体输入 |
| `unet_pcv2_f2_basic` | `unet_c1` pdb-centric-v2 | F2-F1 basic | 无受体输入 |
| `find1_real_f1_basic` | `Find_1` 真实受体 | F1-F1 basic | `receptor_real` |
| `find1_real_f2_gaussian` | `Find_1` 真实受体 | F2-F1 Gaussian | `receptor_real` |
| `find1_cryoatom2_f1_basic` | `Find_1` CryoAtom2 受体 | F1-F1 basic | `receptor_cryoatom2` |
| `find1_cryoatom2_f2_gaussian` | `Find_1` CryoAtom2 受体 | F2-F1 Gaussian | `receptor_cryoatom2` |
| `emap2lig_official_find_li` | Emap2lig | official Find-Li | 无受体输入 |

`test_1` 是 `test_0` 的子集，因此不重复生成会话。正式批量入口只读取 `test_0` 的 179 个 PDB。

## 合并会话对象

会话只使用平级分组，不建立外层 `stage1`：

```text
density
receptors
ground_truth
pred_unet_pcv2_f1_basic
pred_unet_pcv2_f2_basic
pred_find1_real_f1_basic
pred_find1_real_f2_gaussian
pred_find1_cryoatom2_f1_basic
pred_find1_cryoatom2_f2_gaussian
pred_emap2lig_official_find_li
```

- `density` 包含完整实验密度 map 和按 `contour_canonical` 创建的 mesh。普通样本使用 `density_exp_map` 和 `density_exp_mesh`；若单个 float32 Brick 超过本管线的 1,500,000,000-byte 工程边界，则按物理 Z 顺序生成 `density_exp_map_####` 和 `density_exp_mesh_####`。相邻块共享一层 Z 采样点，因此保留跨分块边界的等值面；不裁剪、不降采样。
- `receptors` 直接包含 `receptor_real` 和 `receptor_cryoatom2`，二者可独立显隐。
- `ground_truth` 直接包含逐 occurrence 的 `gt_occ_*` 分子对象；坐标、元素和化学键来自沉积结构产物。
- 每个 `pred_*` 组直接包含当前模式的逐 blob 对象。Pocket Plus 写入 evaluation 中的全部候选；Emap2lig 默认只写入 rank 前 100 个候选。

首次打开时显示实验密度 mesh、全部 GT 和真实受体，隐藏密度 map、CryoAtom2 受体和全部预测组。调用七个命名 scene 时，只切换相应预测组和该方法实际使用的受体；密度与 GT 保持可见。scene 切换依赖父组显隐，不改写组内由 `candidate_selected` 决定的对象状态。

## rank 与对象名称

`--rank-by probability_mean` 是默认值，七种模式都按 `source_probability_mean` 降序稳定排序。`--rank-by gaussian` 只让两个 F2-F1 Gaussian 模式改按 `candidate_score` 排序；其余五种模式仍按 `source_probability_mean`。同分候选保留 evaluation 中的原始顺序。

rank 只决定 PyMOL 对象顺序和名称，不改变候选集合、`candidate_selected` 或正式结果。对象名称形如：

```text
find1_real_f2_gaussian_r0001_b000123_selected
```

对象 state title 保存模式、rank、实际排序字段、`source_blob_index`、`source_probability_mean`、evaluation/Gaussian 分数和 `candidate_selected`。`_selected` 对象在预测组启用时默认显示，`_unselected` 默认隐藏。

Emap2lig 使用 `--emap-limit 100` 时先完成稳定排序，再装入前 100 个候选；`--emap-limit all` 装入全部候选。`manifest.jsonl` 对每个模式同时记录源候选总数和实际装入数。

## 两种盘上预测契约

`prediction_sources.py::load_predictions()` 是正式归一化入口，只隔离以下两种格式：

```text
# Pocket Plus
{artifact_root}/{producer}/{split}/{pdb_id}/blobs/F{alpha}_blobs.npz
{artifact_root}/{producer}/{split}/{pdb_id}/evaluation/{evaluation_name}.npz

# Emap2lig
{result_root}/mapped/{pdb_id}/official_blobs.npz
{result_root}/evaluation/per_pdb/{pdb_id}.npz
```

两种格式都归一化为稳定源编号、源概率均值、评估分数、正式入选状态和全图 ZYX 体素索引。增加新的模型结果时，应先明确其盘上契约并新增 profile；不得通过模型名推断文件。

## 坐标与密度交互

AdaLigand 密度元数据中的 `origin` 是体素边界下角。全图 ZYX 索引 `index_zyx` 的世界坐标为：

```text
center_xyz = origin_xyz + (index_xyz + 0.5) * voxel_size_xyz
```

密度 Brick 的首个采样点、Pocket Plus blob 和 Emap2lig blob 共用这一变换。受体与 GT 已是世界 XYZ 坐标，不再平移、缩放或旋转。

调整完整密度等值面。下列 PyMOL Python 片段同时适用于单 map 和分块 map：

```pml
python
for name in cmd.get_names("objects"):
    if name.startswith("density_exp_mesh"):
        cmd.isolevel(name, 1.25)
python end
```

围绕任意 GT 或预测对象创建 8 Å 局部密度。每个相交分块生成一个独立局部 mesh；不相交分块会生成空 mesh，不影响密度值或坐标：

```pml
python
target = "gt_occ_0000_CCD_ATP"
map_names = [
    name for name in cmd.get_names("objects") if name.startswith("density_exp_map")
]
for index, map_name in enumerate(map_names):
    mesh_name = f"density_near_target_{index:04d}"
    cmd.isomesh(mesh_name, map_name, 1.25, target, carve=8)
    cmd.group("density", mesh_name)
python end
```

目标对象可替换为任一模式下的预测对象。局部 mesh 只存在于当前会话，不回写 Stage1 源产物。

## 环境、测试与正式运行

独立 PyMOL 环境由 `environment.yml` 描述，默认位于 `$HOME/anaconda3/envs/AdaLigand_stage1_pymol`，不修改 Pocket Plus 训练环境。

本地门控命令：

```powershell
& 'D:\Pymol\python.exe' -m unittest discover -s 可视化套件\Stage1\tests -v
```

服务器 `9hjx` 正式先导命令：

```bash
bash 训练与运行/submit_task.sh --sh 可视化套件/Stage1/sh/build_comparison_sessions.sh --resource cpu --cpus 16 --mem 256G --after_hold -- --pdb-id 9hjx
```

先导通过后，在同一个保留 allocation 的动态命令中执行 179-PDB 全量任务：

```bash
exec bash "${TASK_PROJECT_ROOT}/可视化套件/Stage1/sh/build_comparison_sessions.sh" --pdb-list /storage/penghongen/AdaLigand/held_out/split/held_out_06_chain/test_0.json --workers 16
```

批量入口使用 16 个独立进程并令每个子进程只处理一个 PDB，避免共享 PyMOL 全局状态。每个 `.pse` 先写同目录临时文件，再原子替换最终路径。重启时仅复用同时存在最终 `.pse`、清单记录且 `rank_by`、Emap2lig 截断值相同的结果。

正式输出：

```text
/storage/penghongen/AdaLigand_stage1_visualization/stage1_7mode_pcv2_test0_probability_mean/
├── sessions/<pdb_id>.pse
├── manifest.jsonl
└── run_summary.json
```

会话保存前启用 PyMOL `pse_binary_dump` 和内部 session compression，再使用 Python pickle protocol 4（对象序列化协议）写入 `.pse`，以支持已压缩字节串超过 4 GiB 的超大会话。PyMOL 的会话加载器直接解码该协议；压缩和序列化都不会移除完整密度 map，Windows PyMOL 仍可重新调整等值面和创建局部 mesh。

## 下载到 Windows

下载入口为 `ops/download_sessions.ps1`。它先要求 D 盘可用空间不少于服务器实际输出大小加 50 GiB，再用 `--partial --append-verify` 续传；命令不带 `--delete`，不会删除服务器或本地文件。密码只读取 `%USERPROFILE%\.ssh\pocket_plus_sshpass.txt`。

```powershell
powershell -ExecutionPolicy Bypass -File 可视化套件\Stage1\ops\download_sessions.ps1
```

默认本地目录为：

```text
D:\AdaLigand_Stage1_PyMOL\stage1_7mode_pcv2_test0_probability_mean\
```

下载完成后以服务器和本地 `sessions/*.pse` 的 SHA-256 清单逐项核对；该校验属于运行验收，不写入会话生成公式。

## 边界

- 只加载实验密度 `exp`；不自动加入 `sim`、`diff` 或 `posdiff`。
- GT 只显示沉积原子结构，不生成 GT 体素掩码。
- 预测 blob 是体素几何对象，不伪造原子类型、化学键或配体身份。
- 不修改 Pocket Plus `pipeline.py`、推理命令或任何既有 Stage1 产物。
- `rank_by` 是视觉浏览顺序，不是新的评估或候选选择规则。
