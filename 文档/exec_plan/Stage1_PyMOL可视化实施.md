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

正式环境创建和真实会话生成尚未提交。本节将分别记录极短的正式命令、Job、release、launch、输入路径和输出 `.pse` 路径；不与测试或诊断命令混写。

## 待完成

- 完成本地代码自查和无错合成数据回归。
- 建立服务器独立 PyMOL 环境，保留 release 和 launch 证据。
- 各选一个真实 `unet_c1` 和 `Find_*` 样本生成会话，核对对象数、默认可见性、坐标和局部 mesh。
- 下载至 Windows PyMOL 回载并交互验收。
- 完成实现分支、学习分支和 `Learn/CUMULATIVE` 的等价收口。
