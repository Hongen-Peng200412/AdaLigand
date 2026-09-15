# Handoff: Find_1 CryoAtom2 受体评估完成

Date: 2026-09-16

## Current State

CryoAtom2 最终预测受体的独立适配、`Find_1` Stage1 calibration、179-PDB `test_0` 正式评估、149-PDB `test_1` 保序派生和 calibration Gaussian score-only 回填均已完成。Job `368455` 已停回 `try_lock_368455`，`after_lock_368455` 保留，双 H100 未释放。

正式结果根为 `/storage/penghongen/AdaLigand_stage1_inference/Find_1/CryoAtom2受体/artifacts/Find_1`。最终门控 `/storage/penghongen/tmp/find1_cryoatom2_final_gate_20260916/result.json` 的状态为 `passed`。

## Completed

- 适配入口位于 `测评数据代码/cryoatom2_受体Adapter/`。它从 CryoAtom2 `latest.json::final_cif` 产生 `receptor_tokens.npz`、`sim.npy` 和 `sim.npz`；正式代码不计算哈希。
- calibration 与 `test_0` 共 279 个唯一真实受体通过全量等价门控：十个 token 数组与 `sim.npy` 均逐位相同，最大绝对误差为 `0.0`。
- CryoAtom2 正式适配完成 calibration 100/100 与 `test_0` 179/179，并通过记录顺序、字段、有限值、实验网格和最终 CIF 来源门控。
- F1 basic 参数为语义阈值 `0.7274169921875`、分数阈值 `0.75816810131073`、`prefiltered_min_voxel=8`、`min_voxels=20`。
- F2 Gaussian 参数为语义阈值 `0.527618408203125`、分数阈值 `0.9171097278594971`、`prefiltered_min_voxel=8`、`min_voxels=28`、`tau_angstrom=0.75`、`lambda_positive=0.2816`、`lambda_negative=0.0`。
- `test_0` 两套评估各有 179 份逐 PDB NPZ 和 179 行 JSONL；`test_1` 两套 JSONL 各 149 行，且没有重复生成 probability、blobs、centered 或逐 PDB 评估。
- calibration 100 份 `F2_centered.npz` 均已非破坏性写入形状对齐的 `score/selected`。
- 三份本地收口文档位于 `收口の结果/Stage1/Find_1(pdb_centric_v2)/使用cryoatom2预测的受体/`。

## Decisions

- checkpoint 固定为 W&B 已完成步编号 `38622` 对应的 `TOP_epoch_04_score_0.6654.ckpt`。
- basic 与 Gaussian 分别在 CryoAtom2 calibration 上独立选择 F1/F2 语义阈值，候选参数都使用 `objective_beta=1`。
- `test_1` 是 `test_0` 的保序子集，不是独立推理或独立统计样本。
- 超过 1,000 个候选的 PDB 不过滤，只保留 `_BLOB_EXCEED` 标记并继续运行。

## Next Actions

- 未经用户明确授权，不删除 `after_lock_368455`，不释放或改作其他任务。
- 如需比较真实受体与 CryoAtom2 受体，使用两边各自在自身 calibration 上冻结的完整流水线结果，并明确这不是只替换受体结构的单因素消融。

## Files To Reopen

- `文档/exec_plan/Find_1_CryoAtom2受体适配实施.md`
- `文档/mapping/计划执行映射.md`
- `收口の结果/Stage1/Find_1(pdb_centric_v2)/使用cryoatom2预测的受体/说明.md`
- Pocket Plus `文档/exec_plan/2026-09-15_Find_1_CryoAtom2受体推理与评估.md`
