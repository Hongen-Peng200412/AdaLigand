# Handoff: Stage1 PDB 等权 macro 重算完成

Date: 2026-08-26

## Current State

Stage1 调参目标已经从 micro 全面切换为 PDB 等权 macro，evaluate 继续同时发布
semantic、coverage 与 one-to-one 的 micro/macro 指标，并新增
`semantic_micro_prauc` 与 `semantic_macro_prauc`。Pocket Plus 与 AdaLigand 的
实现线、学习线已经通过树等价核验，两个 `Learn/CUMULATIVE` 均已推进。

unet_c1 F1/F2 正式 CPU 重算已经完成。正式根是：

```text
/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950
```

Job `356881`、`356883` 和 `356884` 均为 `COMPLETED/0:0`，相关 allocation 已通过
`after_lock` 正常释放，没有使用 `scancel`，也没有操作其他 Job。

## Completed

- evaluate 新增两项 PRAUC，使用训练同款 1024 个 `torch.float32` 阈值；macro
  按 PDB 等权，micro 合并体素计数。相邻 1 ULP 边界测试与 TorchMetrics 对齐。
- semantic 阈值、basic 和 Gaussian 的全部调参阶段统一最大化 semantic、
  coverage@0.3 与 one-to-one@0.3 三项 macro F-beta 之和。
- `_BLOB_EXCEED` 继续默认跳过 centered；显式提示模式保留标记但继续生成，
  tune/evaluate 直接消费已存在的 centered。
- 本地定向回归 54 项通过；完整回归 354 项通过，唯一失败是本轮范围外的
  `Find_1.sh` worker 基线断言。代码布局、注释文档与科学逻辑三类第三轮独立审查
  及后续窄口径复核均批准。
- Job `356881` 从 `micro(old)` 根真实复制 calibration 100 个与 validation 200 个
  probability 及完成标记；抽查新旧文件 inode 不同，确认不是硬链接。
- Job `356883/356884` 分别完成 F1/F2 的 calibration semantic+blobs、validation
  blobs、basic tune、calibration evaluate 和 validation evaluate。两项均使用
  16 CPU、64 GiB 内存、0 GPU；没有生成 centered。
- F1 semantic threshold 为 `0.607086181640625`，basic score threshold 为
  `0.8210563659667969`，`min_voxels=16`。
- F2 semantic threshold 为 `0.230712890625`，basic score threshold 为
  `0.3140856623649597`，`min_voxels=21`。
- validation F1 的 semantic/coverage@0.3/one-to-one@0.3 macro F1 分别为
  `0.4555574170/0.5098829900/0.5025159453`。
- validation F2 的 semantic/coverage@0.3/one-to-one@0.3 macro F2 分别为
  `0.5055086160/0.4932014093/0.4853090575`。
- validation 的 semantic macro/micro PRAUC 分别为
  `0.4572529597/0.5080070029`。同一 probability 下 F1/F2 的 PRAUC 相同。
- calibration 与 validation 的 F1/F2 逐 PDB evaluation NPZ 和 JSONL 分别为
  100 与 200；六个调参文件位于 producer 级 `artifacts/unet_c1/tuning/`。

## Decisions

- 不复制旧目录的 blobs、调参、评估、校验和或身份文件；只复用原 probability、
  split JSON 和训练配置。不同科学版本继续用可读目录区分。
- probability 来源 checkpoint 是：
  `/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/runtime/mainchain_official_346737/logs/AdaLigand_Stage1-unet_c1-mainchain/unet_c1_mainchain____tmp_stage1_mainchain_job346737_20260818T035126_a4_formal/checkpoints/TOP_epoch_00_score_0.6030.ckpt`。
- F1/F2 提交时 Slurm 没有保留预期的 `SBATCH_DEPENDENCY`。发现新目录只有
  65/100 个 calibration probability 后，立即只对自己的 Job 写入 `kill_lock`；
  两项进入 `try_lock` 后等待复制完成，再从原命令重跑。错误日志中的首次退出码
  137 是该主动恢复事件，第二至第六次执行均成功。
- 本轮只运行 basic，不运行 centered 或 Gaussian 实战。后者属于后续独立任务。

## Open Questions

- 后续 centered/Gaussian 实战使用哪个 producer、alpha、objective beta、
  `forward_min_voxels` 与 `_BLOB_EXCEED` 模式，仍需用户按新任务明确授权。

## Next Actions

本轮没有未完成运行。后续若执行 centered 或 Gaussian，应直接复用本次正常目录、
producer 级 tuning 布局与执行记录格式，不恢复旧 micro 调参文件，也不增加哈希或
身份验证机制。

## Files To Reopen

- `C:\Users\15919\Desktop\AdaLigand\文档\exec_plan\Stage1_PDB等权macro调参与unet_c1重算实施.md`
- `C:\Users\15919\Desktop\AdaLigand\文档\规划文档\BOX-level数据契约.md`
- `C:\Users\15919\Desktop\AdaLigand\文档\mapping\计划执行映射.md`
- `C:\Users\15919\Desktop\Pocket_Plus\talk\refactor\stage1_v3_inference.md`
- `C:\Users\15919\Desktop\Pocket_Plus\src\inference\evaluation.py`
- `/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950/feedback/Stage1_PDB等权macro重算执行记录.md`
