# 通用任务提交与 Stage1 学习版脚本重建执行记录

本文件记录 Pocket_Plus 通用 Slurm 任务提交体系与三份 AdaLigand Stage1
学习版训练脚本的实施、用户复审后的纠正、无卡验证和 Git 双线收口。设计讨论来自
`grill_with_memory/07-25-23-40.md`；训练科学基线来自
`talk/三个训练的检查记录.md` 与三个既有服务器任务的最终解析配置。

本任务覆盖：

- 把 `Pocket_Plus/训练与运行/` 建成可整体复制、用相对目录定位文件的通用入口。
- 保留 `pre_lock`、`try_lock`、`after_lock`、`kill_lock`、动态 `run_cmd`
  和同一 Slurm allocation 多次执行。
- 明确区分 release、launch、`src/train.py` 的 `logs/` 和 allocation 控制文件。
- 把 `Find_0.sh`、`Find_1.sh`、`unet_c1.sh` 改写为可独立阅读的正式训练脚本。
- 在不申请 GPU、不运行训练 smoke 的条件下检查 Slurm 参数、release 时序、
  重试换版和五份 Hydra 配置。

本任务不覆盖：

- 不修改 Stage1 模型、Dataset、损失、训练入口或推理实现。
- 不提交 Slurm Job，不终止或接管 Job `321107`、`321540`、`321743`。
- 不向服务器同步本轮纠正后的文件，不创建新的服务器正式 release。
- 不迁移或覆盖三个既有任务位于
  `/home/penghongen/My_Project/feedback_plus/logs/` 的历史产物。

## 最终行为

日常入口为：

```text
Pocket_Plus/训练与运行/README.md
→ Pocket_Plus/训练与运行/submit_task.sh
→ Pocket_Plus/训练与运行/sbatch/task.sbatch
→ Pocket_Plus/训练与运行/sh/<具体训练>.sh
```

release 的最终时序是：

```text
submit_task.sh 调用一次 sbatch，此时不创建 release
→ Job 获得资源
→ 可选 pre_lock
→ 每次即将执行 run_cmd
→ 对当时最新的发布源创建或复用 release
→ 为该次执行创建绑定该 release 的 launch
→ 从 release 运行任务
→ 成功、失败或 kill 后进入 try_lock
→ 删除 try_lock 后再次从最新发布源创建或复用 release
```

因此，排队期间的代码修改会进入第一次运行，`try_lock` 期间的代码修改会进入
下一次运行。训练任务脚本不包含 release 逻辑，也没有额外递归保护协议。

`submit_task.sh` 默认把自身上一层作为发布源；`--release-source` 可以直接覆盖。
通用脚本未硬编码 Pocket_Plus 项目路径。

## 实施与纠正过程

- 2026-07-26：完成 grill 决策收敛和三个历史命令、Slurm 模板、四锁循环、
  experiment 配置、服务器检查记录的只读审计。
- 2026-07-26：第一版实现错误地在 `submit_task.sh` 调用 `sbatch` 前创建
  release。该行为会冻结排队时的代码，也会使 `try_lock` 后的重试继续使用旧代码。
- 2026-07-26：用户复审后纠正为“每次实际执行前生成 release”。提交阶段只传递
  发布源、任务相对路径和资源参数。
- 2026-07-26：三个训练脚本补全逐行中文说明，尤其解释
  `ADALIGAND_DATA_ROOT`、`ADALIGAND_STAGE1_PREPARATION_ROOT`、
  `EXPERIMENT_FEEDBACK_ROOT` 到 Hydra、Dataset、BOX 请求和训练产物的真实链路。
- 2026-07-26：用 shell 显式覆盖恢复既有正式任务的运行数值，但模型、Dataset
  与损失仍由完整 experiment 提供。Find_0 使用 `CPC1/Find_0` 与
  `CPC2/Find_0`；Find_1 使用 `CPC1/Find_1` 与 `CPC2/Find_1`；
  unet 使用 `unet_c1`。
- 2026-07-26：实现提交在原位置 amend 为 `a6d4bf5`；没有增加实现提交数量。
- 2026-07-26：原三段学习历史按相同阅读顺序重建为：
  - `f57ea57 01 explain the portable training entry`
  - `876c615 02 build the portable Slurm runtime`
  - `399a357 03 add readable Stage1 task scripts`
- 2026-07-26：`Learn/generic-task-runner` 与 `Learn/CUMULATIVE` 均移动到
  `399a357`。实现端点与学习端点的 Git tree 均为
  `de5d202d3e61168e2eea58c901735bf0c47eaca3`。

第一版曾同步到服务器并创建：

```text
/home/penghongen/Feedback/Pocket_Plus/releases/Pocket_Plus_012952d69ed9
```

该 release 完整记录了第一版内容，但它包含已经废止的“提交时发布”行为，不能作为
本轮最终实现启动新任务。它没有被删除或覆盖；本轮也没有向服务器发布替代版本。

## 无卡验证

已完成：

- 八个正式 shell/sbatch 文件通过 `bash -n`。
- 假 `sbatch` 捕获并核对 H200、节点数、GPU 数、CPU 数、`--array`、
  `--hold`、`--release-source` 和一次性 Hydra 覆盖。
- 假提交确认 `submit_task.sh` 不创建 `releases/`。
- 临时 allocation 验证：
  - 第一次执行从版本 A 建立 release；
  - 成功后进入 `try_lock`；
  - 发布源改为版本 B；
  - 删除 `try_lock` 后第二次执行建立新 release；
  - 两个 launch 的 `release_project_root` 不同；
  - out 中分别出现 `PROBE_VERSION=A` 与 `PROBE_VERSION=B`。
- 本机 Hydra 成功组合 Find_0 CPC1/CPC2、Find_1 CPC1/CPC2 和 unet_c1
  五份配置。关键结果为：

| 配置 | GPU | 每卡 batch | 全局 batch | worker | 学习率 | warmup | patience |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Find_0 CPC1 | 2 | 8 | 48 | 10 | `5e-5` | `0.005` | 2 |
| Find_0 CPC2 | 2 | 8 | 48 | 10 | `5e-5` | `0.0` | 1 |
| Find_1 CPC1 | 2 | 6 | 48 | 10 | `5e-5` | `0.005` | 3 |
| Find_1 CPC2 | 2 | 6 | 48 | 10 | `5e-5` | `0.005` | 1 |
| unet_c1 | 1 | 6 | 48 | 20 | `1e-4` | `0.005` | 3 |

- Find_0/Find_1 的真实原子密度 cube 已显式恢复为边长 11；Find_1 的伪原子
  与真实原子 chunk 分别恢复为 1024 和 2048。
- `git diff --check` 通过；所有修改文件均为无 BOM UTF-8，未发现替换字符。
- 实现端点与学习端点通过完全相同 Git tree 的等价核验。

未执行：

- 没有调用真实 `sbatch`。
- 没有申请 CPU/GPU allocation。
- 没有运行训练 smoke。
- 没有同步服务器或创建最终服务器 release。
- 当前环境没有 ShellCheck，因此没有声称通过 ShellCheck。

## 最终差异

相对第一版实现 `dfb0d39`，本轮纠正的核心是：

- 删除提交时 release 创建和 `--release` 入口。
- 增加简单的 `--release-source` 覆盖。
- `task.sbatch` 接收发布源；allocation 控制器每次执行前重新冻结。
- 默认 `run_cmd` 使用动态 `TASK_PROJECT_ROOT`，因此重试会指向本次新 release。
- README 从 312 行扩展为可独立阅读的 643 行说明，加入 A→B→C 的具体时序、
  Job 400001 目录示例、批量计算和数据/产物路径因果链。
- 三个训练脚本删除旧 Job 身份和旧路径，补全正式参数与逐行说明。
- shell 显式恢复旧训练相对当前 experiment 的 cube、chunk 和 patience 差异。

完整文件与配置差异见 `talk/训练脚本与release差异.md`。

## 收口状态

本地实现和学习历史已收口，Pocket_Plus 当前工作区位于
`Learn/CUMULATIVE@399a357` 且干净。没有推送远端。

若以后正式使用，必须先把最终树同步到服务器，再由新体系的
`submit_task.sh` 提交。同步与提交均需要用户另行授权；不得把第一版服务器
release `Pocket_Plus_012952d69ed9` 当作最终实现。
