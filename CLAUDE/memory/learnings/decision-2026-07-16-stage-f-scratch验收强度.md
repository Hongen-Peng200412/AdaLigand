# Stage F scratch 回收的验收强度

Type: decision
Date: 2026-07-16
Tags: stage-f, scratch, recovery, evidence

## Context

Stage F 异常路径曾残留大型 MRC/CIF。受检回收工具已经冻结 attempt 清单、公开质量三件套和跨节点进程状态，但进一步要求给所有大于 16 MiB 的普通保留日志补做完整 SHA-256 会延长主线停机。

## Memory

本轮回收以“保证实质内容不变”为边界：公开质量三件套不分大小做完整 SHA-256；普通 nontransient 日志/证据冻结并复核路径、文件类型、设备/inode、大小、实际分配块和 mtime，并保留已有或必要的小文件哈希。只有在对抗性原地改写属于实际威胁模型时，才升级为所有普通大文件全量哈希；不得把额外证据加固无条件变成 A–G 的阻塞门。

该决定只适用于 scratch 工程恢复证据，不改变四种 CC、MapQ、配体/口袋 Q、质量三件套或 Stage G 的科学契约。

## When To Use

在长流水线发生临时文件回收、硬中断恢复或证据强度与恢复时效冲突时使用。先对科学公开产物做强内容校验，再按真实威胁模型确定普通调试证据的校验成本。

## Related Files

- `Data_Preprocessing/Ori_Data/code/stage_f_scratch_recovery.py`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `CLAUDE/memory/handoffs/2026-07-16-stage-f-scratch安全停点与v4重建.md`
