# Handoff: Stage1 V3 通用 F-alpha 推理完成

Date: 2026-08-22

## Current State

Stage1 V3 推理已经重写为 `probability`、`blobs`、`centered`、`tune`、`evaluate` 五个独立阶段。Pocket Plus 与 AdaLigand 的代码、配置、BOX-level 权威契约、执行记录和映射索引均已完成；本轮没有启动服务器正式推理。

handoff 写入前的最终双线端点为：Pocket Plus 实现 `916175d`、学习与累计 `11271aa`，tree 均为 `ba5a7e71a2654ac130cb18e664486957e8cda550`；AdaLigand 实现 `a13d697`、学习与累计 `f219858`，tree 均为 `63650ab4b947ff51ba727fb8702e2d1a623c01f3`。两个仓库的 `Learn/CUMULATIVE` 都是按提交者时间形成的唯一最新提交，工作区干净。

## Completed

- 删除活动树中的旧 `src/inference/workflow.py`，由 `src/inference/pipeline.py` 直接提供五个阶段入口。
- 支持任意正浮点 alpha 的 `F{alpha}_blobs.npz` 与 `F{alpha}_centered.npz`；alpha 不决定模型前向或字段集合。
- 所有 producer 的 centered 都执行完整 forward 并保存 `voxel_final`；Find 额外保存 auxiliary、A/P 与三张 float32 48³ 数组。
- `forward_min_voxels` 只控制进入 GPU 的候选；选择 JSON 的 `min_voxels` 只控制 `selected`；score-only 只替换 `score/selected`。
- centered 来源 blob 数严格大于 1000 时只写最小 `_BLOB_EXCEED` 并跳过，不建立恢复或覆盖状态机。
- Gaussian 纳入距离恰好 5 Å 的 A 原子；Find A 表保留距离恰好 10 Å 的原子。
- CPU 科学/Dataset 回归 34 项、Windows RTX CUDA smoke 2 项通过；Black、compileall、YAML、五个 CLI 帮助入口、Bash 与差异检查通过。
- 布局/Git、注释/文档与逻辑三类独立审查各完成三轮全面核查，第三轮问题均经窄口径复核批准。

## Decisions

- 正式代码不计算 checkpoint、配置或代码 SHA，不建立 `_valid*` 或身份框架。checkpoint 只以用户显式路径使用；同 checkpoint 的不同科学结果由用户可读的 `output_root` 目录区分。
- 显式 `--calibration` 可以跨 `output_root` 复用；用户已裁决无需强制目录相等。
- 完成标记只控制同阶段默认跳过并供外部调度观察；消费者不重复建立前置阶段完成标记校验链。
- 完整图配体概率和 Find 融合结果都不乘受体 hardmask。
- PDB 清单使用 JSON 顶层字符串列表；生产分片固定 seed 3407，再取 `[shard_index::shard_count]`。
- 完整图 stride 必须从配置显式读取；当前正式值为 `[30,30,30]`。

## Open Questions

- 用户尚未完成对正式代码逻辑的人工验收。
- 三份推理 README 已修改，需要用户重新运行 Human MD Review。
- 推理验收后的服务器实战、checkpoint、producer、alpha、评分模式和输出版本目录仍由用户另行决定。

## Next Actions

1. 对 Pocket Plus `训练与运行/sh/infer/README.md`、`configs/inference/README.md`、`src/inference/README.md` 重新运行 Human MD Review。
2. 用户按五阶段接口检查科学契约与代码逻辑；如有批注，只在已点名范围内修订，继续控制复杂度预算。
3. 用户验收后，再为指定 checkpoint 与版本目录生成正式服务器命令并提交实战推理；提交前确认所需科学参数，不在当前 handoff 中预设。

## Files To Reopen

- `C:/Users/15919/Desktop/Pocket_Plus/talk/refactor/stage1_v3_inference.md`
- `C:/Users/15919/Desktop/Pocket_Plus/src/inference/README.md`
- `C:/Users/15919/Desktop/Pocket_Plus/configs/inference/README.md`
- `C:/Users/15919/Desktop/Pocket_Plus/训练与运行/sh/infer/README.md`
- `C:/Users/15919/Desktop/AdaLigand/文档/规划文档/BOX-level数据契约.md`
- `C:/Users/15919/Desktop/AdaLigand/文档/exec_plan/Stage1_V3推理重写实施记录.md`
