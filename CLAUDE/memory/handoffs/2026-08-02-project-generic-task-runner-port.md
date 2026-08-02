# AdaLigand 项目通用任务提交系统移植

## Current State

AdaLigand 项目根目录已经新增 `训练与运行/`。该目录包含可以独立复制的 Slurm 提交入口、通用 sbatch、release/launch 留证、四锁运行组件和冷读说明。所有新增文件按用户要求保持未暂存、未提交。

仓库在本任务开始前已有其他已暂存和未暂存修改。本任务没有暂存、提交、移动或丢弃这些内容，也没有修改已经被其他工作暂存的 `CLAUDE/memory/projects/adaligand.json`。

## Completed

- 新增 `训练与运行/submit_task.sh`，默认任务根目录是 `训练与运行` 的上一层，即 AdaLigand 项目根目录。
- 新增 `训练与运行/sbatch/task.sbatch` 和 `训练与运行/runtime/` 三个运行组件。
- 新增 `训练与运行/README.md`，用 13 个编号章节说明命令、目录、release、launch、四锁、资源参数、simple 模式、复制方式和旧提交系统边界。
- 新增 `训练与运行/sh/README.md`，说明正式任务脚本的职责；本轮没有编造具体训练或数据处理任务脚本。
- `.gitattributes` 新增 `训练与运行` 下 Bash 与 sbatch 文件的 LF 换行约束。
- 个人 `project-server-interaction` skill 已把项目根目录下的 `训练与运行` 设为正式入口；`与服务器交互/sbatch` 仅用于旧任务兼容和历史参考。

## Validation

- AdaLigand 五个核心 Bash 文件全部通过 `bash -n`。
- AdaLigand 的五个核心文件与 Pocket_Plus 通用来源按 UTF-8 文本逐字相同，防止复制后形成第二套实现。
- 使用 Pocket_Plus 中的通用契约测试，把待测目录明确指向 `C:\Users\15919\Desktop\AdaLigand\训练与运行`，结果为 `5 passed`。
- 测试覆盖默认项目根目录、绝对与相对任务路径等价、项目外脚本拒绝、完整 release/launch 留证和 simple 模式四锁执行。
- 完整模式测试在临时项目内真实创建 release 和 launch，并确认 `task_run_stamp`、release 项目名和任务相对路径一致；测试产物位于 pytest 临时目录，不留在 AdaLigand。
- 未提交真实 Slurm 作业，未触碰服务器、现有训练和旧任务产物。
- Pocket_Plus 通用来源已于 2026-08-03 从隔离实现位置迁入常用 `C:\Users\15919\Desktop\Pocket_Plus` 的 `Learn/CUMULATIVE` 工作区；隔离工作树和无独有提交的临时分支已经删除。

## Decisions

- 新正式任务优先使用 `训练与运行/submit_task.sh`。
- 任务脚本必须位于所选任务根目录内；绝对路径不会降级为不冻结的外部任务。
- 原 `与服务器交互/sbatch` 不删除，不影响仍依赖旧代码的任务，但不再作为新正式任务的首选模板。
- 本轮不创建 commit；后续提交者必须将本任务新增目录与仓库中其他工作分开审阅。

## Open Questions

- 哪一项 AdaLigand 正式任务最先迁入 `训练与运行/sh/`，需要由用户在对应任务设计确定后决定。

## Next Actions

1. 为具体任务编写可冷读的 `训练与运行/sh/*.sh`，明确环境、配置、输入和产物目录。
2. 在真实提交前核对服务器上的分区、QOS 和运行组件依赖。
3. 用户审阅并自行决定何时暂存或提交本轮文件。

## Files To Reopen

- `训练与运行/README.md`
- `训练与运行/submit_task.sh`
- `训练与运行/sbatch/task.sbatch`
- `训练与运行/runtime/allocation_runner.sh`
- `训练与运行/runtime/create_release.sh`
- `训练与运行/runtime/create_launch.sh`
- `C:\Users\15919\.codex\skills\project-server-interaction\SKILL.md`
- `C:\Users\15919\Desktop\Pocket_Plus\tests\test_project_task_runner.py`
