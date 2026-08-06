# Handoff: AdaLigand 调度保留开关

Date: 2026-08-03

## Current State

AdaLigand 的 `训练与运行` 已与 Pocket_Plus 的通用调度核心同步。默认行为是获得资源后立即执行一次任务，随后自动退出并释放 allocation。所有改动留在当前工作区，未暂存、未提交；本轮没有切换分支、修改 Git 索引或提交真实 Slurm 作业。

## Completed

- `训练与运行/submit_task.sh` 新增独立的 `--pre_hold` 与 `--after_hold`，删除旧 `--hold`。
- `--pre_hold` 只在第一次执行前创建 `pre_lock`；删除后开始执行，任务结束后仍默认释放。
- `--after_hold` 在任务结束后创建 `try_lock` 并保留 allocation；省略时不创建 `try_lock`。
- `训练与运行/sbatch/task.sbatch` 和 `训练与运行/runtime/allocation_runner.sh` 已同步新参数与默认释放行为。
- `训练与运行/README.md` 已说明两个开关、四种锁文件的条件和 simple 模式的相同行为。

## Decisions

- 不保留 `--hold` 兼容别名。旧命令必须显式改为 `--pre_hold`。
- 是否在任务结束后保留资源由用户通过 `--after_hold` 自由决定，默认释放。
- 已经启动的 allocation 控制器不会被热替换。尚未启动且仍携带旧 `--hold` 参数的排队 Job 不属于兼容范围，正式使用前应核对并用新入口重新提交。

## Validation

- 两个仓库的调度核心文件保持逐字一致。
- AdaLigand 调度目录通过 Pocket_Plus 的 9 项通用契约测试。
- shell 语法检查通过；没有服务器写入或真实资源申请。

## Next Actions

1. 后续任务若需要先占卡再开始，提交时使用 `--pre_hold`。
2. 后续任务若需要运行结束后保留卡，提交时使用 `--after_hold`。
3. 若两种保留都不需要，不填写任何保留参数。

## Files To Reopen

- `训练与运行/submit_task.sh`
- `训练与运行/sbatch/task.sbatch`
- `训练与运行/runtime/allocation_runner.sh`
- `训练与运行/README.md`
