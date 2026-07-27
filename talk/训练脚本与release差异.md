# 三个学习版训练脚本与 release 差异

本文记录 2026-07-26 用户复审后的最终 Pocket_Plus 通用任务提交实现、三个
AdaLigand Stage1 学习版训练脚本、无 GPU 配置组合结果，以及它们与第一版
release 和三个既有训练配置的差异。

本文是实施检查记录，不是训练配置权威。一次真实训练最终使用什么，仍以该次：

```text
launch.json
→ logs/.../config.yaml
→ src_snapshot/
→ checkpoint
```

为准。

## 1. 最终本地身份

Pocket_Plus 最终实现端点：

```text
codex/generic-task-runner@a6d4bf5
```

学习历史仍只有原定三段，没有增加“修复提交”：

```text
f57ea57 01 explain the portable training entry
→ 876c615 02 build the portable Slurm runtime
→ 399a357 03 add readable Stage1 task scripts
```

`Learn/generic-task-runner` 与 `Learn/CUMULATIVE` 均指向 `399a357`。
实现端点和学习端点的 tree 均为：

```text
de5d202d3e61168e2eea58c901735bf0c47eaca3
```

因此两条历史的最终文件逐字节等价。

## 2. 相对第一版实现的实际 Git diff

第一版实现端点为 `dfb0d39`。最终实现 `a6d4bf5` 相对第一版：

```text
7 files changed, 1052 insertions(+), 351 deletions(-)
```

七个变化文件为：

```text
训练与运行/README.md
训练与运行/submit_task.sh
训练与运行/sbatch/task.sbatch
训练与运行/sh/Find_0.sh
训练与运行/sh/Find_1.sh
训练与运行/sh/unet_c1.sh
与服务器交互/other/training_runtime/allocation_runner.sh
```

`create_release.sh` 与 `create_launch.sh` 的底层职责不需要变化。

核心行为差异：

| 行为 | 第一版 | 最终版 |
| --- | --- | --- |
| release 创建时点 | 调用 `sbatch` 前 | 每次真正执行 `run_cmd` 前 |
| 排队期间修改代码 | 不进入第一次运行 | 进入第一次运行 |
| `try_lock` 期间修改代码 | 重试仍使用旧 release | 重试创建或复用最新 release |
| 手工指定 release | `--release` | 删除该入口 |
| 覆盖发布源 | 无 | 简单的 `--release-source` |
| 默认 `run_cmd` | 写死第一次冻结路径 | 使用动态 `TASK_PROJECT_ROOT` |
| launch | 绑定提交时 release | 每次绑定该次刚生成的 release |
| 训练脚本 | 含旧 Job 叙述，注释较短 | 删除旧身份，逐行解释训练因果 |

完整 hunk 可直接查看：

```bash
git -C /path/to/Pocket_Plus diff dfb0d39 a6d4bf5 -- \
  训练与运行 \
  与服务器交互/other/training_runtime
```

## 3. 相对重建前共同基点的实际 Git diff

共同基点为 `eead0a7`。最终实现相对该基点：

```text
13 files changed, 2038 insertions(+), 271 deletions(-)
```

最终目录：

```text
训练与运行/
├── README.md
├── submit_task.sh
├── sbatch/
│   └── task.sbatch
└── sh/
    ├── Find_0.sh
    ├── Find_1.sh
    └── unet_c1.sh

与服务器交互/other/training_runtime/
├── allocation_runner.sh
├── create_launch.sh
└── create_release.sh
```

旧的三个根目录训练脚本已被对应的 `sh/` 学习版替代。

## 4. 第一版服务器 release 的状态

第一版实现曾同步到服务器并建立：

```text
/home/penghongen/Feedback/Pocket_Plus/releases/
└── Pocket_Plus_012952d69ed9/
    ├── manifest.json
    └── Pocket_Plus/
```

其完整内容哈希为：

```text
012952d69ed945f6a1ba4f06511344405956d143b915f2933b01cd5bbd6f0956
```

当时已用带校验和的 `rsync --dry-run` 证明服务器项目与该 release 差异为 0。
这说明它准确冻结了第一版，但第一版的 release 时序现已废止。

本轮遵守用户边界：

- 没有修改或删除该 release；
- 没有向服务器同步最终实现；
- 没有在服务器创建最终 release；
- 没有提交任何 Slurm Job；
- 没有触碰 Job `321107`、`321540`、`321743`。

因此当前不存在可以声称为“最终版正式服务器 release”的新目录。最终版与第一版
release 的代码内容差异，由上节 `dfb0d39 → a6d4bf5` 的七文件 Git diff
精确表示。以后得到用户授权并同步最终树后，新的 release 应由第一次实际运行
自动创建；不应手工复用 `Pocket_Plus_012952d69ed9`。

## 5. 最终五份无 GPU 配置输出

本轮没有给正式脚本增加 `--resolve-only`，也没有保留配置审计入口。检查使用本机
Hydra 直接组合 `configs/base.yaml`、完整 experiment 与脚本中相同的覆盖参数；
没有实例化模型、Dataset 或 Trainer，也没有访问 GPU。

### 5.1 共同输入与产物路径

五份配置均解析为：

```text
dataset.all_data_path=
  /storage/penghongen/AdaLigand/Ori_Data

dataset.box_pool_root=
  /storage/penghongen/AdaLigand/Ori_Data/
  stage1_preparation/adaligand_stage1_20260721T024000/box_pool
```

训练脚本的默认产物根为：

```text
/home/penghongen/Feedback/Pocket_Plus
```

它由 `EXPERIMENT_FEEDBACK_ROOT` 进入 `src/train.py`，最终写到其 `logs/` 下。

### 5.2 关键训练参数

| 配置 | devices | 每卡 batch | 全局 batch | workers | lr | warmup | patience | 降 LR 后停止 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Find_0 CPC1 | 2 | 8 | 48 | 10 | `5e-5` | `0.005` | 2 | 4 |
| Find_0 CPC2 | 2 | 8 | 48 | 10 | `5e-5` | `0.0` | 1 | 1 |
| Find_1 CPC1 | 2 | 6 | 48 | 10 | `5e-5` | `0.005` | 3 | 4 |
| Find_1 CPC2 | 2 | 6 | 48 | 10 | `5e-5` | `0.005` | 1 | 1 |
| unet_c1 | 1 | 6 | 48 | 20 | `1e-4` | `0.005` | 3 | 4 |

Find_0/Find_1 的模型性能参数：

| 字段 | Find_0 | Find_1 |
| --- | ---: | ---: |
| `real_atom_density_cube_size` | 11 | 11 |
| `real_density_cube_cfg.cube_size` | 11 | 11 |
| `density_cube_cfg.chunk_size` | experiment 的 2048 | 显式恢复 1024 |
| `real_density_cube_cfg.chunk_size` | experiment 的 4096 | 显式恢复 2048 |

Find_1 和 unet_c1 的五项损失权重仍由 experiment 引用的损失 YAML 提供：

```text
ligand_area=1.0
ligand_distance=0.3
binding_area=0.1
protein_mainchain=0.05
nucleic_mainchain=0.05
```

三个 shell 没有重复声明这些损失权重。

## 6. 与三个既有服务器任务的预期差异

下述比较以此前已经保存的服务器 resolved config 字段级结果为依据。本轮没有
重新访问或修改服务器。

### 6.1 Find_0 CPC1 对 Job 321743

最终脚本显式恢复：

- 真实原子 cube 边长 11；
- 两张 GPU；
- 每卡 batch 8、全局 batch 48；
- worker 10；
- 学习率 `5e-5`；
- warmup `0.005`；
- patience 2；
- 第 4 次实际降学习率后停止。

因此第一版披露的真实 cube `11→9` 行为差异已消失。当前配置仍可能比旧 runtime
多出以下等价显式字段：

- `dataset.box_sample_fraction=1.0`；
- `dataset.excluded_pdb_ids=[]`；
- `voxel_backbone.enable_multiscale_output=true`；
- `voxel_backbone.enable_structure_heads=false`。

它们把旧默认行为写成显式值，不改变 Find_0 科学行为。

Job `321743` 没有可作为历史事实的 Find_0 CPC2 resolved config。最终脚本确认
CPC2 能完成 Hydra 组合，并明确从本轮 CPC1 BEST 初始化，但不声称与不存在的
历史 CPC2 文件逐字段相同。

### 6.2 Find_1 CPC1/CPC2 对 Job 321540

最终脚本显式恢复：

- 伪原子 chunk 1024；
- 真实原子 chunk 2048；
- 真实原子 cube 边长 11；
- CPC1 patience 3；
- 学习率 `5e-5`；
- CPC1/CPC2 warmup `0.005`；
- 每卡 batch 6、全局 batch 48、worker 10。

因此第一版披露的两个 chunk、cube 和 CPC1 patience 差异均已消失。

当前实现可能仍多出
`model.backbone.embed_head.voxel_embed_as_tune=false`，这是旧实现固定 false
行为的显式化，不改变输入拼接或科学结果。CPC2 的 `init_from` 必然指向新一轮
CPC1 BEST，而不是 Job `321540` 的旧 checkpoint；这是运行身份差异。

### 6.3 unet_c1 对 Job 321107

最终脚本把 patience 显式恢复为 3，并保留：

- 一张 GPU；
- 每卡 batch 6、全局 batch 48；
- worker 20；
- 学习率 `1e-4`；
- warmup `0.005`；
- 第 4 次实际降学习率后停止；
- online W&B。

第一版披露的 patience `3→2` 差异已消失。模型、Dataset、五项损失和权重继续
由 `+experiment=unet_c1` 提供。

## 7. release、launch 和 logs 是否重复

最终实现中的三者不重复：

```text
release
  回答：本次执行可以读取哪些代码与配置文件？

launch
  回答：这个 Job 的这一次尝试用了哪个 release、哪条动态命令和哪些资源？

logs
  回答：src/train.py 最终解析了什么配置、实际运行了什么代码、产生了哪些模型？
```

一个 Job 的两次尝试可以是：

```text
launch a1 → release A → logs A
launch a2 → release B → logs B
```

这正是 `try_lock` 修复代码但不释放 GPU 时需要保存的关系。

## 8. 无卡验证结论

已通过：

- 八个正式 shell/sbatch 文件的 `bash -n`；
- H200、节点数、GPU 数、CPU 数、`--array`、`--hold`、
  `--release-source` 与一次性 Hydra 覆盖的假 `sbatch` 捕获；
- 提交阶段没有建立 release；
- 第一次运行使用 release A，`try_lock` 后重试使用 release B；
- 两次 launch 分别绑定两个 release；
- 五份 Hydra 配置组合与关键值断言；
- 无 BOM UTF-8 与 `git diff --check`；
- 实现端点和三段学习端点 Git tree 完全一致。

未执行：

- 没有真实 `sbatch`；
- 没有 CPU/GPU allocation；
- 没有训练 smoke；
- 没有服务器同步或最终服务器 release；
- 没有 ShellCheck。
