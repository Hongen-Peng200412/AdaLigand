# Stage1 PyMOL 可视化会话

本目录把单个 PDB 的 AdaLigand 原始数据与 Pocket Plus Stage1 推理产物组装为自包含的 PyMOL `.pse` 会话。程序只读源产物，只写指定的会话文件，不修改 Stage1 推理主流程、命令行入口或盘上契约。

## 输入与寻址

`build_session.py` 要求以下参数：

- `--data-root`：AdaLigand 数据根，例如 `/storage/penghongen/AdaLigand/Ori_Data`。
- `--inference-root`：直接包含 producer 目录的 Stage1 `artifacts` 根，例如 `/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950/artifacts`。
- `--producer`：推理根下的生产者目录名，例如 `unet_c1` 或 `Find_0`。程序不按模型类型分支。
- `--split`：生产者目录下的数据划分名，例如 `held_out_test_0`。
- `--pdb-id`：单个 PDB 编号；内部统一转为小写。
- `--alpha`：选择 `blobs/F{alpha}_blobs.npz` 的 F-alpha 值，例如 `1`。
- `--evaluation-name`：不带 `.npz` 的评估文件名，例如 `f1_blobs_basic_macro_selected`。
- `--output`：要写入的 `.pse` 文件。程序先写同目录临时文件，成功后再原子替换目标。

预测候选统一从以下两个公共 Stage1 文件读取，因此同一套实现同时适用于 `unet_c1` 和 `Find_*`：

```text
{inference_root}/{producer}/{split}/{pdb_id}/blobs/F{alpha}_blobs.npz
{inference_root}/{producer}/{split}/{pdb_id}/evaluation/{evaluation_name}.npz
```

## 会话对象

`.pse` 内的顶层组为 `stage1`，其下包含：

- `density`：`density_exp_map` 保存完整实验密度，`density_exp_mesh` 是用 `contour_canonical` 创建的全图等值面。
- `receptor`：从 `receptor_tokens.npz` 生成的独立受体分子对象。该源文件不保存作者链号和残基号，因此会话使用 `C{chain_index}` 与 `res_index + 1` 作为稳定的合成标识。
- `ground_truth`：每个沉积配体实例是一个 `gt_occ_*` 分子对象，坐标来自 `ligand_coords.npz`，元素和化学键来自对应 `ligand_objects/*.npz`。
- `predictions`：每个评估候选是一个 `pred_r*_b*_s*_{selected|unselected}` 对象。对象内每个体素中心是一个无键伪原子，以球面显示。`predictions_selected` 默认可见，`predictions_unselected` 已写入会话但默认隐藏。

预测对象名中的 `r`、`b`、`s` 分别是按冻结分数稳定降序的一基 rank、`source_blob_index` 和 `candidate_score`。完整精度的分数、rank 和 `candidate_selected` 同时写在该分子对象的 state title 中。

## 坐标契约

AdaLigand 密度元数据的 `origin` 是体素边界下角的世界 XYZ 坐标。全图 ZYX 整数索引 `index_zyx` 对应的体素中心为：

```text
center_xyz = origin_xyz + (index_xyz + 0.5) * voxel_size_xyz
```

密度 Brick 的首个采样点与预测伪原子都使用这一体素中心。受体与 GT 配体已是世界 XYZ 坐标，不再变换。

## PyMOL 中的交互

调整全图等值面阈值：

```pml
isolevel density_exp_mesh, 1.25
```

围绕任意 GT 配体创建 8 Å 局部等值面：

```pml
isomesh density_near_gt, density_exp_map, 1.25, gt_occ_0000_CCD_ATP, carve=8
group density, density_near_gt
```

围绕任意预测 blob 创建局部等值面：

```pml
isomesh density_near_prediction, density_exp_map, 1.25, pred_r0001_b000004_s0p812345_selected, carve=8
group density, density_near_prediction
```

命令中的对象名和阈值应替换为当前会话中的实际值。局部等值面是 PyMOL 会话内的新对象，不会回写 Stage1 产物。

## 环境与运行

独立环境由 `environment.yml` 描述，默认服务器路径为 `$HOME/anaconda3/envs/AdaLigand_stage1_pymol`。如需其他路径，在提交前设置 `ADALIGAND_STAGE1_PYMOL_ENV`。`sh/create_environment.sh` 只在环境不存在时创建它；已存在时只验证 PyMOL 和 NumPy 可导入。

正式生成入口为 `sh/build_session.sh`。一个完整示例如下：

```bash
bash 训练与运行/submit_task.sh \
  --sh 可视化套件/Stage1/sh/build_session.sh \
  --resource cpu \
  --cpus 4 \
  --mem 32G \
  -- \
  --data-root /storage/penghongen/AdaLigand/Ori_Data \
  --inference-root /storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950/artifacts \
  --producer unet_c1 \
  --split held_out_test_0 \
  --pdb-id 9hjx \
  --alpha 1 \
  --evaluation-name f1_blobs_basic_macro_selected \
  --output /storage/penghongen/AdaLigand_stage1_visualization/9hjx.pse
```

下载 `.pse` 后可直接用 Windows PyMOL 打开，不需要保留服务器输入文件。

## 当前边界

- 首版只加载实验密度 `exp`；对 `sim`、`diff` 和 `posdiff` 不做隐式降级或猜测。
- GT 只显示沉积原子结构，不额外生成 GT 体素掩码。
- 预测 blob 是体素几何对象，不伪造原子类型、化学键或配体身份。
- 程序始终写入评估 NPZ 中的全部候选，不提供第二套 top-N 选择逻辑。
- `Find_*` 必须已经生成当前公共 `blobs/F{alpha}_blobs.npz` 和 `evaluation/{evaluation_name}.npz` 契约。旧运行若只有 `centered/`、`components/` 和 `probability/`，需先用对应冻结模型的 Stage1 推理流程生成公共 blobs 与 evaluation；本可视化生成器不会猜测或改写旧产物。
