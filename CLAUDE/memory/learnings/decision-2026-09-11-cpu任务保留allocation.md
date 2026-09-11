# CPU 任务默认保留 allocation

Type: decision
Date: 2026-09-11
Tags: slurm, cpu, after-hold

## Context

AdaLigand 的 CPU 队列可能需要较长时间才能获得资源。同一件工作通常还需要在首个 CPU 任务后运行真实样本、补充验收或修正后复测。

## Memory

后续提交 AdaLigand CPU 任务时加上 `--after_hold`。任务脚本结束后保留当前 allocation，然后通过该 Job 的动态命令执行后续 CPU 任务，避免每个步骤重新排队。未经用户明确指示，不删除 `after_lock_<job_id>` 以释放该 allocation。

## When To Use

用 `训练与运行/submit_task.sh` 提交 CPU 环境建立、数据处理、结果汇总、可视化产物生成或验收任务时应用这条约定。

## Related Files

- `训练与运行/submit_task.sh`
- `训练与运行/runtime/allocation_runner.sh`
