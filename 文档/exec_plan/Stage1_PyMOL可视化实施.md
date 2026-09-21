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

## 2026-09-21：七模式合并会话扩展

### 基线与输入来源

- 扩展开始前，`Learn/CUMULATIVE@ca552b2a7b3850e3ea94c093d8b3548774b146c3` 是按提交者时间形成的唯一最新提交，主工作树干净。
- 真实实现分支为 `codex/stage1-pymol-7mode`，工作树为 `C:\Users\15919\Desktop\AdaLigand_worktrees\stage1_pymol_7mode`。
- `unet_c1` 只读取 pdb-centric-v2 的 F1/F2 basic；`Find_1` 分别读取真实受体和 CryoAtom2 受体下的 F1 basic 与 F2 Gaussian；Emap2lig 读取 official Find-Li 的 `official_blobs + per_pdb evaluation`。
- 正式 `test_0` 清单为 `/storage/penghongen/AdaLigand/held_out/split/held_out_06_chain/test_0.json`，包含 179 个 PDB；`test_1` 是其子集，不重复生成会话。

### 体积与压缩预检

本地对既有 `9hjx_fixed.pse` 使用 PyMOL 二进制 dump 和内部 session compression 复测：79,310,478 字节的未压缩会话缩至约 21.3 MB，重新加载后平级组仍完整。179 个 PDB 的实验密度原始数组总量约 27.94 GB；结合完整密度在 `.pse` 中的实测压缩比，七模式共享密度后的本地总量预计为 70–100 GiB。该估算只用于磁盘准备，不替代服务器实际输出大小门控。

### 实现

- `prediction_sources.py` 提供唯一归一化候选入口，在内部隔离 Pocket Plus 与 Emap2lig 两种盘上格式。
- `build_comparison_sessions.py` 生成七种预测平级组、两个受体和七个 scene；默认按源概率均值排序，Gaussian 开关只影响两个 Gaussian 模式。
- Pocket Plus 写入全部 evaluation 候选；Emap2lig 默认稳定截取前 100，并支持 `all`。运行清单逐模式记录源候选总数、装入数、入选数和实际排序字段。
- 每个 `.pse` 压缩保存到同目录临时文件后原子替换；批量入口通过独立子进程隔离 PyMOL 全局状态，并只复用配置一致的完整结果。
- 新增无删除行为的 MSYS2 `rsync` 下载入口；下载前要求 D 盘剩余空间不少于服务器实际输出大小加 50 GiB。

### 本地门控命令

```powershell
& 'D:\Pymol\python.exe' -m unittest discover -s 可视化套件\Stage1\tests -v
& 'D:\Anaconda\Scripts\black.exe' --check 可视化套件\Stage1\build_session.py 可视化套件\Stage1\prediction_sources.py 可视化套件\Stage1\build_comparison_sessions.py 可视化套件\Stage1\tests\test_build_session.py 可视化套件\Stage1\tests\test_prediction_sources.py
& 'D:\Anaconda\Scripts\flake8.exe' --max-line-length 160 可视化套件\Stage1\build_session.py 可视化套件\Stage1\prediction_sources.py 可视化套件\Stage1\build_comparison_sessions.py 可视化套件\Stage1\tests\test_build_session.py 可视化套件\Stage1\tests\test_prediction_sources.py
& 'C:\Program Files\Git\bin\bash.exe' -n 可视化套件/Stage1/sh/build_session.sh
& 'C:\Program Files\Git\bin\bash.exe' -n 可视化套件/Stage1/sh/build_comparison_sessions.sh
git diff --check
```

### 正式运行命令

`9hjx` 先导任务只使用以下提交命令：

```bash
bash 训练与运行/submit_task.sh --sh 可视化套件/Stage1/sh/build_comparison_sessions.sh --resource cpu --cpus 16 --mem 256G --after_hold -- --pdb-id 9hjx
```

Windows PyMOL 3.1.6.1 通过先导验收后，在同一个保留 allocation 中把动态命令改为：

```bash
exec bash "${TASK_PROJECT_ROOT}/可视化套件/Stage1/sh/build_comparison_sessions.sh" --pdb-list /storage/penghongen/AdaLigand/held_out/split/held_out_06_chain/test_0.json --workers 16
```

正式输出根为 `/storage/penghongen/AdaLigand_stage1_visualization/stage1_7mode_pcv2_test0_probability_mean`。本节只记录正式生产命令；单元测试、静态门控和验收脚本不混入正式命令。

### 当前状态

代码、profile、测试、README、规划与运维下载入口已在实现工作树完成首轮实现，合成测试为 5 项通过。服务器只读预检逐一核对 179 个 PDB 的六套 Pocket Plus evaluation、Emap2lig 映射和两套受体文件；七种模式的 evaluation 候选总数依次为 `2196/2670/1939/2251/2097/2407/63342`，源 blob 编号映射均闭合。Emap2lig 的原点、体素尺寸与网格形状逐 PDB 同实验密度一致。服务器先导、Windows 跨版本回载、179-PDB 全量生产、三项真实样本抽查、源文件只读核验和服务器/本地 SHA-256 一致性仍待双线等价核验并推进 `Learn/CUMULATIVE` 后执行。

## 2026-09-22：七模式全量生产与验收完成

### 正式执行

H100 Job `378587` 先把 canonical 输出推进到 178/179。用户随后指定改用 A800 Job `379402_0` 的 16 CPU；H100 上本任务的进程组被精确停止，`after_lock_378587` 保留，未结束该 Job。A800 接管后使用的正式生产命令为：

```bash
exec bash "${TASK_PROJECT_ROOT}/可视化套件/Stage1/sh/build_comparison_sessions.sh" --pdb-list /storage/penghongen/AdaLigand/held_out/split/held_out_06_chain/test_0.json --workers 8
```

`379402_0` 的第 35 次执行冻结 release `/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/运行日志与统计/slurm/releases/AdaLigand_8c57e30b4f93/AdaLigand`；allocation launch 为 `/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/运行日志与统计/slurm/launches/379402/predict_calibration_job379402_20260922T005930_a35`，可视化 launch 为 `/home/penghongen/Feedback/AdaLigand/launches/379402/stage1_7mode_full_resume8_job379402_20260922T0058`。运行结果为 `created=1`、`reused=178`、`success=179`。验收结束后 `379402_0` 回到 `try_lock`，`after_lock_379402` 保留，未释放 A800 allocation。

### `9gjg` 性能阻塞与窄修复

最后缺失样本 `9gjg` 的首次 A800 尝试持续 60 分钟仍未产生临时 `.pse`。进程采样显示单个 NumPy 线程长期停在 `_aligned_strided_to_contig_size4`：旧实现直接在 Lustre 的 `(1,Z,Y,X)` 内存映射上执行 XYZ 转置，导致跨页次序读取；60 分钟只读取约 455 MB。该尝试通过本 Job 的 `kill_lock` 精确停止，未留下临时会话，`after_lock` 未动。

`load_density()` 随后改为先按源文件的 ZYX C 连续顺序把只读密度复制到内存，再执行原有 ZYX→XYZ 转置。该修复不改变体素值、分块边界、重叠层、世界坐标、对象名或会话契约。Windows PyMOL 六项合同测试、Black、Flake8、两遍主代理自查和代码布局、中文注释、科学契约三项独立窄复核全部通过。实现提交为 `5dcbde1`，学习提交及 `Learn/CUMULATIVE` 为 `eac9ce2`。修复后 `9gjg.pse` 约 5 分钟完成，文件大小为 1,725,395,749 字节。

### 门控与产物

以下为只读门控命令，不是正式生产命令：

```bash
/home/penghongen/anaconda3/envs/AdaLigand_stage1_pymol/bin/python /storage/penghongen/tmp/stage1_pymol_7mode_20260921/diagnostics/validate_full_output.py
/home/penghongen/anaconda3/envs/AdaLigand_stage1_pymol/bin/python /storage/penghongen/tmp/stage1_pymol_7mode_20260921/diagnostics/verify_representative_sessions.py
```

完整门控结果为：

- canonical 根含 179 个 `.pse` 和 179 行 `manifest.jsonl`，顺序严格匹配 `test_0`；无隐藏临时会话。
- 七种模式的源候选数与各自 evaluation NPZ 一致；Emap2lig 装入数均为 `min(100,N)`；全部模式的实际排序字段为 `probability_mean`。
- 生成前记录的 10,173 个 AdaLigand 与 Stage1 来源文件在生成后均存在，大小和纳秒修改时间零变化。
- 服务器 PyMOL 3.1.0 顺序回载 `9hjx`、`11jb`、`30yu` 和 `9gjg`；十个平级组、七个 scene、默认显隐、双受体、完整密度范围、`isolevel` 和局部 mesh 全部通过。
- 最终服务器输出为 66,436,749,133 字节，其中 179 个会话合计 66,436,365,577 字节。SHA-256 清单位于 `/storage/penghongen/tmp/stage1_pymol_7mode_20260921/diagnostics/stage1_7mode_pcv2_test0_probability_mean.sha256`。

正式下载命令为：

```powershell
& '.\可视化套件\Stage1\ops\download_sessions.ps1'
```

本地交付根为 `D:\AdaLigand_Stage1_PyMOL\stage1_7mode_pcv2_test0_probability_mean`。续传下载退出码为 0；本地 179 个会话与服务器清单逐项比较结果为 `Missing=0`、`Extra=0`、`Mismatch=0`。Windows PyMOL 3.1.6.1 已回载 `9hjx.pse`，平级组、scene 和默认显隐全部通过。由于 Windows 当前仅剩约 4.8 GiB 物理内存和 1.21 GiB 虚拟内存，未在本机强行回载 4.89 GB 的 `11jb.pse`；服务器回载和本地逐文件哈希已经验证该文件完整性。
