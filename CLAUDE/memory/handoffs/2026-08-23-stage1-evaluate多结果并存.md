# Handoff: Stage1 evaluate 多结果并存

Date: 2026-08-23

## Current State

Stage1 V3 的 `evaluate` 入口已经完成最小接口修订。命令必须显式提供 `--evaluation-name`，并在 `--selection-parameters` 与 `--all-candidates` 之间二选一。不同参数过滤结果和未经过二次打分的全候选对照可以使用不同名称保存在同一输出目录中；本轮没有启动服务器推理任务。

handoff 写入前的内容端点为：Pocket Plus 实现 `11aaff6`、学习候选 `7e7971d`，tree 均为 `c07013fb2a3cac33c2105749a43f20470efd6ebc`；AdaLigand 实现 `90a0fd6`、学习候选 `047786d`，tree 均为 `a7070a3361a860ecc4f824c179b98ad84e906155`。

## Completed

- `--selection-parameters <json>` 沿用 basic 或 Gaussian 重打分，并同时应用 `score_threshold`、`prefiltered_min_voxel` 和 `min_voxels`。
- `--all-candidates` 不调用二次评分函数，使用 `source_probability_mean` 稳定排序，并把当前候选文件中的全部候选设为已选。
- blobs 全候选指 `F{alpha}_blobs.npz` 中的全部连通区域；centered 全候选只指已经写入 `F{alpha}_centered.npz` 的候选。
- 每 PDB NPZ、数据划分 JSONL 和 metrics JSON 共同使用显式评估名称，因此多组参数结果不会互相覆盖。
- Pocket Plus 原暂存区中的 `calibration.py`、`evaluation.py` 和 `scoring.py` 修改已经一并进入实现与学习历史；原工作区的未暂存修改没有进入任何提交。
- CPU 回归 37 项、Windows RTX CUDA smoke 2 项通过；编译检查、evaluate CLI 帮助和两个仓库的差异检查通过。

## Decisions

- 不生成参数摘要、SHA、身份对象或额外完成状态；结果区分完全由用户给出的可读评估名称承担。
- 不为全候选模式复制 blobs 或 centered 文件；只发布独立评估事实与汇总。
- 不修改 `evaluation.py` 的指标公式。全候选模式通过把 `candidate_selected` 全部设为 True 复用同一评估核心。
- 不补回没有进入 centered 文件的 blobs；需要评估全部连通区域时应选择 `--artifact blobs --all-candidates`。

## Next Actions

1. 用户检查正式评估代码和 README 的科学含义。
2. 正式运行时为每组选择参数指定不同的 `--evaluation-name`；未打分对照使用 `--all-candidates`。
3. 服务器提交仍需单独确定 producer、alpha、候选文件、PDB 清单和可读结果名称，本 handoff 不预设这些值。

## Files To Reopen

- `C:/Users/15919/Desktop/Pocket_Plus/src/inference/cli.py`
- `C:/Users/15919/Desktop/Pocket_Plus/src/inference/pipeline.py`
- `C:/Users/15919/Desktop/Pocket_Plus/训练与运行/sh/infer/README.md`
- `C:/Users/15919/Desktop/Pocket_Plus/src/inference/README.md`
- `C:/Users/15919/Desktop/AdaLigand/文档/规划文档/BOX-level数据契约.md`
- `C:/Users/15919/Desktop/AdaLigand/文档/exec_plan/Stage1_V3推理重写实施记录.md`
