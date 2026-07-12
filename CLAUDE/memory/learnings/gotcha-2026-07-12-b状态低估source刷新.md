# B 状态可能低估已刷新的 source

Type: gotcha
Date: 2026-07-12
Tags: AdaLigand, Stage B, provenance, mmCIF, run-scoped status

## Context

初次只统计 Stage B `success` 记录中的 `resources.mmcif=downloaded`，得到 400 份刷新 mmCIF；对同一 Slurm job mtime 窗口做文件系统扫描后，真实数量是 2,156。原因是旧 `known_failed` 状态没有保存逐资源 `resources`，即使 mmCIF 已下载、其他资源失败，也无法从状态行看出。

## Memory

- 不能仅从成功状态推断某类资源的写入集合；多资源 stage 的失败行也必须保留每个资源的最终状态。
- source-dirty 集合要用可复核的文件系统证据冻结：显式带 UTC offset 的 mtime 窗口、预期数量、ID 清单和 SHA-256。
- 当前 B 已修复为 `known_failed` 同样保存 `resources`；历史 run 仍须以文件系统证据为准。
- 本轮窗口是 `2026-07-11T15:46:58+08:00 < st_mtime <= 2026-07-12T05:30:00+08:00`，预期 2,156；实际清单 SHA 必须在服务器快照后记录，不能预猜。

## When To Use

审计下载增量、追踪 raw source provenance、设计多资源 stage 状态或解释为什么状态计数与文件 mtime 不一致时使用。

## Related Files

- `Data_Preprocessing/Ori_Data/scripts/b_download.py`
- `Data_Preprocessing/Ori_Data/scripts/snapshot_source_dirty.py`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
