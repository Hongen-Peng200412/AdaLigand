# Find_1 CryoAtom2 受体适配实施记录

本文记录 CryoAtom2 最终预测受体转换为 Pocket Plus Stage1 可读 `Ori_Data` 的代码、科学边界、验证与服务器生产事实。正式推理的资源、命令、指标和完整状态由 Pocket Plus 的 `文档/exec_plan/2026-09-15_Find_1_CryoAtom2受体推理与评估.md` 记录。

## 当前状态

- 2026-09-15：任务开始。适配代码计划放在 `测评数据代码/cryoatom2_受体Adapter`，不修改成熟 A–G 主流程。
- calibration 与 `test_0` 的 CryoAtom2 最终结构已经分别完成 100/100 和 179/179 验收；正式适配也已分别完成 100/100 和 179/179。
- 候选入口已在服务器 AdaLigand 环境通过 2 项单元测试。calibration 100 项与 `test_0` 179 项共 279 个唯一真实受体已全量通过行为等价门控；十个 token 数组与 `sim.npy` 均逐位复现主 `Ori_Data`。
- 代码、自查、独立审查和双线 Git 收口已经完成；Python 环境窄修复后的 AdaLigand `Learn/CUMULATIVE` 为 `9a09c235cdff226884afeedb0693394b80e64b0f`，成功正式运行使用的冻结 release 为 `/home/penghongen/Feedback/AdaLigand/releases/AdaLigand_c209bedb1883/AdaLigand`。
- Job `368455` 第 13 次执行在写入任何正式受体资产前结束；入口的 Python 环境窄修复已经进入 AdaLigand `Learn/CUMULATIVE` 提交 `9a09c235cdff226884afeedb0693394b80e64b0f`。第 14 次执行从修复后的 release 完成正式适配，第 15 次执行完成全量只读门控；任务已停回 `try_lock_368455`，`after_lock_368455` 保留。
- 适配产物随后支持 Pocket Plus 完成 calibration 选参、179-PDB `test_0` 正式评估和 149-PDB `test_1` 保序派生；最终结果门控通过。完整指标与运行事实见 Pocket Plus 对应实验日志，本地结果文档位于 `收口の结果/Stage1/Find_1(pdb_centric_v2)/使用cryoatom2预测的受体/`。

## 科学边界

- 只把受体来源从真实受体替换为 CryoAtom2 的最终预测 CIF；实验密度、配体区域、测试清单和模型 checkpoint 不变。
- 新入口产生 `parse/<pdb_id>/receptor_tokens.npz`、`density/<pdb_id>/sim.npy` 和 `sim.npz`。正式代码不计算文件哈希；哈希只用于隔离的门控和执行追溯。
- 不复用主 `Ori_Data/labels/<pdb_id>`。其 `atom_labels.npz` 的受体原子轴对齐真实受体，与 CryoAtom2 原子轴不兼容；本入口只服务 `require_targets=False` 的推理与评估。
- CryoAtom2 坐标不执行拟合、平移或裁剪。模拟密度使用实验密度的原始网格几何。

## 正式运行命令

Job `368455` 第 13 次执行，失败且未写入正式受体资产：

```bash
exec bash "/home/penghongen/Feedback/AdaLigand/releases/AdaLigand_fe7e6d0cd64c/AdaLigand/测评数据代码/cryoatom2_受体Adapter/sh/prepare.sh"
```

Job `368455` 第 14 次执行，环境修复后的正式重跑：

```bash
exec bash "/home/penghongen/Feedback/AdaLigand/releases/AdaLigand_c209bedb1883/AdaLigand/测评数据代码/cryoatom2_受体Adapter/sh/prepare.sh"
```

这是本阶段唯一正式运行命令；测试、门控和只读核查命令不属于本节。

## 验证记录

- 服务器定向单元测试：`2 passed`。
- 真实受体等价门控：`6bgi`、`6dqn`、`6rec` 的 token 逐数组相同，`sim.npy` 均逐位相同，最大绝对误差为 `0.0`。
- 门控结果：`/storage/penghongen/tmp/find1_cryoatom2_adapter_gate_20260915/Find_1_pdb_centric_2_job368455_20260915T114442_a10/gate_result.json`。
- 全量真实受体等价门控：Job `368455` 第 11 次执行覆盖 279/279 个唯一 PDB；每个 PDB 的十个 token 数组都相同，`sim.npy` 均逐位相同，全局最大绝对误差为 `0.0`。
- 全量门控结果：`/storage/penghongen/tmp/find1_cryoatom2_adapter_gate_20260915/Find_1_pdb_centric_2_job368455_20260915T120839_a11/gate_result.json`。
- CryoAtom2 集成门控：`6bgi` 适配后可由正式 Stage1 Dataset 读取，H100 成功产生形状为 `(262, 262, 262)` 的 `probability_map`；模拟密度形状为 `(1, 262, 262, 262)`，两者空间轴一致。受体来源链接解析到 `latest.json::final_cif`，不含 `_raw.cif`。
- 正式产物门控：calibration 100 项与 `test_0` 179 项的记录顺序、三件套、十字段 token、有限值、实验网格几何、最终 CIF 来源和主真值符号链接全部通过。报告为 `/storage/penghongen/tmp/find1_cryoatom2_adapter_formal_gate_20260915/calibration.json` 与同目录 `test_0.json`；清单 SHA-256 分别为 `b14c9f4413092454c34f24239f0ccb1b2d506b5105fcff9dea3e6b7e87b0fe7a` 和 `12473392629c55338460b1111d4449e7a6a692612d7eed780b1db48011acc887`。
- 本地收口自查：三份结果文档逐项覆盖两套流水线的 112 个 P/R/F1/PRAUC 显示值和 36 个 top-K 计数/百分比，均与下载的服务器 JSON 完整精度来源一致；Markdown 标题间距、相对链接、四份 CLAUDE JSON 和两个仓库的 `git diff --check` 均通过。最终文档阶段没有修改生产代码，因此不重新扩大已经批准的代码审查范围。

已执行的服务器测试命令：

```bash
cd /storage/penghongen/tmp/find1_cryoatom2_adapter_candidate_20260915
/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python -m pytest 测评数据代码/cryoatom2_受体Adapter/tests/test_adapter.py -q
```

第 10 次 Job 执行的门控命令：

```bash
exec env PYTHONPATH="/storage/penghongen/tmp/find1_cryoatom2_adapter_candidate_20260915/测评数据代码/cryoatom2_受体Adapter:/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data" /home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python -u /storage/penghongen/tmp/find1_cryoatom2_adapter_candidate_20260915/gate_known_receptors.py
```

这两条命令均不是正式运行命令。第 11 次执行复用同一门控命令，但将脚手架的覆盖范围从三个样本扩展为全部 279 个真实受体，现已通过。

## 运行历史

- Job `368455` 第 12 次执行完成了 `6bgi` 的 CryoAtom2 适配和 probability 前向，但门控末尾错误读取 `probability_map.npz::probability`，因此返回非零值。实际字段为 `probability_map`；修正字段名后的只读验收通过，没有修改正式适配或推理代码。
- Job `368455` 第 13 次执行从首个冻结 release 启动正式适配，但 `prepare.sh` 使用裸 `python`，继承到不含 `gemmi` 的 Pocket Plus 环境，在模块导入时结束。calibration 与 `test_0` 正式目标仍为 0 份；修复只把两个适配调用固定到已验收的 `AdaLigand_stage1_py310` Python，不改变受体选择、数组或模拟密度逻辑。修复后的服务器测试为 `2 passed`。

## 计划与实现差异

- 当前未发现差异。
