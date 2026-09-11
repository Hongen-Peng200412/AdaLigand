# Stage1 PyMOL 可视化实施

## 记录责任

本文档记录 `文档/规划文档/Stage1_PyMOL可视化会话.md` 的实施、验证、正式运行和 Git 双线证据。当前用法由 `可视化套件/Stage1/README.md` 说明；本文档不重复定义底层数据字段。

## 基线与分支

- 实施开始时，AdaLigand `Learn/CUMULATIVE` 为按提交者时间的唯一最新提交 `2c2c9c9a1f8a2926e36faa132b0d39fda2095dd7`，主工作树干净。
- 真实实现分支为 `codex/stage1-pymol-visualization`，独立工作树为 `C:\Users\15919\Desktop\AdaLigand_worktrees\stage1_pymol_visualization`。
- 本轮不修改 Pocket Plus 仓库。

## 已核实的输入事实

- AdaLigand `density/{pdb_id}/exp.npy` 是 `(1,Z,Y,X)` 实验密度；`exp.npz` 提供 `origin`、`voxel_size` 和 `contour_canonical`。
- `receptor_tokens.npz` 提供受体原子世界 XYZ 坐标、元素、稳定索引和键表，不提供作者链号或残基号。
- `occurrences.jsonl`、`ligand_coords.npz` 和 `ligand_objects/*.npz` 可共同恢复每个 GT 配体的沉积坐标、元素和化学键。
- `unet_c1` 与 `Find_*` 评估都使用公共 `F{alpha}_blobs.npz` 和 evaluation NPZ。evaluation 候选轴已按冻结分数稳定降序，`source_blob_index` 可映射回 blobs 文件。
- Windows PyMOL `3.1.6.1` 可以通过 `chempy.models.Indexed` 加载分子对象，并通过 `chempy.brick.Brick` 加载内存密度数组。

## 实施记录

### 2026-09-11：本地首版

- 新增 `可视化套件/Stage1/build_session.py`，以单个 PDB 为单位创建密度、受体、GT 和全部评估候选对象，再原子写入 `.pse`。
- 新增独立 `environment.yml`、幂等环境创建脚本和极简会话生成 shell，不使用 Pocket Plus 训练环境。
- 新增合成数据测试，已在 Windows PyMOL Python 中完成首次运行。测试发现 PyMOL 不接受对 map、mesh 和 group 调用 `set_title`；已删除这三处无效元数据写入，分子对象的 title 保留。

## 验证记录

### 本地测试命令

```powershell
& 'D:\Pymol\python.exe' -m unittest discover -s 可视化套件\Stage1\tests -v
```

首次结果为 `1 test OK`。该次运行同时暴露并已修复上述 `set_title` 对象类型问题。随后根据 AdaLigand 契约把 GT 模板的 `residue_id` 修正为一基索引，并在测试中增加密度 map 范围、顶层分组和插入码路径。修复后重跑为 `1 test OK`，运行期无 PyMOL 错误输出。

静态门控为：

```powershell
& 'D:\Anaconda\Scripts\black.exe' --check 可视化套件\Stage1\build_session.py 可视化套件\Stage1\tests\test_build_session.py
& 'D:\Anaconda\Scripts\flake8.exe' --max-line-length 160 可视化套件\Stage1\build_session.py 可视化套件\Stage1\tests\test_build_session.py
& 'C:\Program Files\Git\bin\bash.exe' -n 可视化套件/Stage1/sh/create_environment.sh
& 'C:\Program Files\Git\bin\bash.exe' -n 可视化套件/Stage1/sh/build_session.sh
git diff --check
```

五项门控全部通过。服务器真实产物和 Windows 回载结果待补。

## 正式运行

### 独立 PyMOL 环境

正式命令：

```bash
bash 训练与运行/submit_task.sh --sh 可视化套件/Stage1/sh/create_environment.sh --resource cpu --cpus 4 --mem 16G --time 01:00:00 --job-name stage1_pymol_env
```

Job `378429` 于 2026-09-11 在 `cnode02` 运行 7 分 29 秒并以 `COMPLETED 0:0` 退出。release 为 `/home/penghongen/Feedback/AdaLigand/releases/AdaLigand_f2f7bbb58f71/AdaLigand`，launch 为 `/home/penghongen/Feedback/AdaLigand/launches/378429/create_environment_job378429_20260911T151847_a1`。最终环境为 `/home/penghongen/anaconda3/envs/AdaLigand_stage1_pymol`，实测 PyMOL `3.1.0`、NumPy `1.26.4`。该环境与 Pocket Plus 训练环境分离。

### occurrence-centric `unet_c1` 真实会话

正式命令：

```bash
bash 训练与运行/submit_task.sh --sh 可视化套件/Stage1/sh/build_session.sh --resource cpu --cpus 4 --mem 32G --time 01:00:00 --job-name stage1_pymol_9hjx -- --data-root /storage/penghongen/AdaLigand/Ori_Data --inference-root /storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950/artifacts --producer unet_c1 --split held_out_test_0 --pdb-id 9hjx --alpha 1 --evaluation-name f1_blobs_basic_macro_selected --output /storage/penghongen/AdaLigand_stage1_visualization/unet_c1/held_out_test_0/9hjx.pse
```

Job `378562` 于 2026-09-11 在 `cnode02` 运行 1 分 30 秒并以 `COMPLETED 0:0` 退出。它复用 release `AdaLigand_f2f7bbb58f71`，launch 为 `/home/penghongen/Feedback/AdaLigand/launches/378562/build_session_job378562_20260911T170212_a1`。输出 `/storage/penghongen/AdaLigand_stage1_visualization/unet_c1/held_out_test_0/9hjx.pse` 为 79,311,938 字节，SHA-256 为 `daf6859fdbf66dd9b7d2620ca6bcd3f1e36838f1754e28065c6f17f0eb3d7749`。

注：上述两个 Job 在用户新增 CPU 资源保留约定前已经提交，因此未带 `--after_hold`。从本次指示起，后续 AdaLigand CPU 任务默认带 `--after_hold`，且未经用户明确指示不释放对应 allocation。该约定同时保存在 `CLAUDE/memory/learnings/decision-2026-09-11-cpu任务保留allocation.md`。

## 真实会话验收

服务器源产物与 Windows PyMOL 回载结果一致：

| 实体 | 源产物 | Windows `.pse` |
| --- | ---: | ---: |
| 受体原子 | 13,099 | 13,099 |
| GT occurrence | 1 | 1 |
| GT 沉积原子 | 48 | 48 |
| 预测 blob | 2 | 2 |
| 默认入选预测 | 1 | 1 |
| 默认隐藏预测 | 1 | 1 |
| 预测 blob 体素 | 198 | 198 |

密度 map 的服务器理论世界范围为 `[[67.70148945, 92.05999753, 90.38128757], [201.09849453, 217.05999008, 213.69870663]]`，Windows PyMOL 回载值为 `[[67.70149231, 92.05999756, 90.38128662], [201.09849548, 217.05999756, 213.69869995]]`。差异仅为 PyMOL map 保存后的 float32 表示误差。

会话由 Windows PyMOL `3.1.6.1` 直接打开，实测存在 `stage1`、`density`、`ground_truth`、`predictions`、`predictions_selected` 和 `predictions_unselected` 六个 group。`isolevel density_exp_mesh, 1.0` 成功；围绕唯一 GT 和第一个预测 blob 分别以 `carve=8.0` 创建局部 `isomesh` 成功。下载文件 SHA-256 与服务器完全一致。

## `Find_*` 契约边界

生成器只按 `{inference_root}/{producer}/{split}/{pdb_id}` 寻址，不包含 `unet_c1` 白名单或模型分支，因此对使用当前公共 `blobs` 与 `evaluation` 契约的 `Find_*` 行为相同。但服务器现有 `/storage/penghongen/AdaLigand_stage1_inference/Find_0-CPC1-ligand_PRAUC_0.675477/artifacts/Find_0` 是旧版产物，样本目录只有 `centered`、`components` 和 `probability`，没有本任务冻结的 `blobs/F{alpha}_blobs.npz` 和 `evaluation/{evaluation_name}.npz`。本轮不在可视化层猜测旧 forest 选择语义，也不修改旧产物；真实 `Find_*` 会话验收等待相应冻结模型生成当前公共契约产物。

## Git 双线与待完成项

实现线从共同基点 `2c2c9c9a1f8a2926e36faa132b0d39fda2095dd7` 到达 `codex/stage1-pymol-visualization@1b621cae3f8e09d881c13e16b98cfc70a641ae2d`。学习线按文档、核心实现、测试的顺序到达 `Learn/stage1-pymol-visualization@b3743e6eb15af7ed70014a8b5aea0ba2cdbf1507`。两端只差学习线的数组形状、坐标和索引注释；Python AST 可执行语句和 Docstring 相同，其他文档、配置、shell 和测试逐字节相同，两端合成 PyMOL 测试均为 `1 test OK`。`Learn/CUMULATIVE` 已快进到学习端点，随后用户要求保存 CPU `--after_hold` 约定，累计学习端点前进到 `4fa8413`。

本轮实现、`unet_c1` 真实会话和 Windows 回载已完成。唯一剩余验收项是在某个 `Find_*` 冻结模型产生当前公共 blobs 与 evaluation 产物后，用同一入口生成一个真实会话。该项不是可视化代码前置的未完成逻辑，也不授权重跑 Find 推理。
