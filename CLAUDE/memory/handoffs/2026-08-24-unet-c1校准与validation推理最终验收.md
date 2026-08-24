# Handoff: unet_c1 校准与 validation 推理最终验收

Date: 2026-08-24

## Current State

主链辅助监督版 `unet_c1` 的本轮正式范围已经全部完成并验收。正式根为 `/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950`，总占用约 44 GiB。

Job `346737` 仍在 hnode02 保留 1×H100 和 16 CPU；当前没有推理进程，GPU 空闲。`try_lock_346737` 与 `after_lock_346737` 均存在，没有删除锁或执行 `scancel`。

## Completed

- a5 calibration probability 于 03:39:50 开始、07:49:48 以退出码 0 完成，100/100；墙钟 14,998 秒。
- a6 validation probability 于 08:02:11 开始、17:25:15 以退出码 0 完成，200/200；墙钟 33,784 秒。
- calibration 的 F1/F2 semantic、各 100 份 blobs 和两份 basic JSON 全部完成。F1 basic 为 `score_threshold=0.9048807621002197, min_voxels=24`；F2 basic 为 `score_threshold=0.48065805435180664, min_voxels=15`。
- CPU Job `353620/353621/353646/353647` 全部 `COMPLETED 0:0`，并在完成后自动释放。
- validation 全量审计读取 32,374,635,283 字节、9,073,709,336 个概率体素；200 份文件的字段、float32、有限性、范围、`exp.npy`/`exp.npz`/`ligand_area.npz` 几何、性能和完成标记全部通过。
- 本轮产物没有 centered 或 evaluate；正式根没有 `.tmp`、`_RUNNING`、缺失项或额外 PDB 目录。
- a6 GPU 共 2,247 个采样，2,223 个活跃样本平均利用率 99.345%，峰值显存 43,930 MiB，活跃样本平均功耗约 342.31 W。

## Formal Evidence

- calibration probability 审计：`monitoring/calibration_probability_audit.json`，SHA-256 `2ed25d02d1a2f83c12882511cf06aae2a73f51b79f5af788df2f9fb3d8bd8eba`。
- calibration semantic/blobs/basic 审计：`monitoring/calibration_semantic_blobs_basic_audit.json`，SHA-256 `88888d32f9d6d74e44b0d8b6c878cd5d18ad81e8be4b50b25c937ebdc1b133f4`。
- validation 首项审计：`monitoring/validation_first_probability_audit.json`，SHA-256 `8651c82942b817750dba7260dd4eb7737e5f90a91ce44437fd31b4abe25d5f50`。
- validation 全量审计：`monitoring/validation_probability_audit.json`，SHA-256 `31e81efdaf1ef30a42373a003b81e83c362daf9756ee25d1ef0a64dda7f2615d`。
- a6 GPU CSV 与汇总 SHA-256：`a03d77cd5ed02c012bd087fa0e205e60fb060ea000a4917b403d8414a079068c`、`b0bbb69219610d6ef160d336f895217c741180887ad46b930302285e77f838cb`。
- 完整命令、release、launch、动态命令哈希、CPU I/O、审计重试和产物统计见 `文档/exec_plan/Stage1第三版unet_c1校准与validation推理实施.md`。

## Decisions

- 本轮科学范围到 probability、calibration F1/F2 semantic/blobs/basic 为止，不追加 centered 或 evaluate。
- Gaussian 正式调参不运行；其生产代码并行能力与 basic 同步实现，并已通过串行等价、乱序与首项获胜测试。
- a5 采样回填、三次只读审计路径/表达修正和一次 GPU 时间格式修正均已明确记录；这些事件没有改变 checkpoint、清单、推理参数或科学 NPZ/JSON。
- Job `346737` 继续保留。未来若要复用，必须基于新的明确命令操作 `try_lock`；不得删除 `after_lock`，除非用户另行授权释放资源。

## Repository State

- Pocket Plus 正式部署身份仍为学习累计端点 `4e5325da1e36453586bf12eade0e7a6df44cd106`，实现等价端点为 `5476a33327ccee0946daf43cca22f7b928ea562e`，tree 为 `ca21a939dc59d2b907fb30299611af63457fd1f5`。
- AdaLigand 本轮日志位于隔离工作树分支 `codex/unet-c1-calibration-inference-log`。主工作区仍含另一项 Find1 的未提交文档和 handoff，不能覆盖；最终合并状态须查看执行记录末尾的 Git 收口段落。

## Next Actions

本轮没有未完成事项。后续 centered/evaluate、实战推理或复用 Job `346737` 都属于新任务，需要新授权和新的正式命令记录。

## Files To Reopen

- `C:\Users\15919\Desktop\AdaLigand_unet_c1_calibration_log\文档\exec_plan\Stage1第三版unet_c1校准与validation推理实施.md`
- `C:\Users\15919\Desktop\AdaLigand_unet_c1_calibration_log\文档\mapping\计划执行映射.md`
- `C:\Users\15919\Desktop\AdaLigand_unet_c1_calibration_log\CLAUDE\memory\projects\adaligand.json`
- `/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950/monitoring/validation_probability_audit.json`
