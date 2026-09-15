# Find_1 CryoAtom2 受体适配实施记录

本文记录 CryoAtom2 最终预测受体转换为 Pocket Plus Stage1 可读 `Ori_Data` 的代码、科学边界、验证与服务器生产事实。正式推理的资源、命令、指标和完整状态由 Pocket Plus 的 `文档/exec_plan/2026-09-15_Find_1_CryoAtom2受体推理与评估.md` 记录。

## 当前状态

- 2026-09-15：任务开始。适配代码计划放在 `测评数据代码/cryoatom2_受体Adapter`，不修改成熟 A–G 主流程。
- calibration 与 `test_0` 的 CryoAtom2 最终结构已经分别完成 100/100 和 179/179 验收；正式适配尚未启动。
- 候选入口已在服务器 AdaLigand 环境通过 2 项单元测试。calibration 100 项与 `test_0` 179 项共 279 个唯一真实受体已全量通过行为等价门控；十个 token 数组与 `sim.npy` 均逐位复现主 `Ori_Data`。
- Job `368455` 已停在 `try_lock_368455`。代码、自查、独立审查和双线收口完成前不触发该锁。

## 科学边界

- 只把受体来源从真实受体替换为 CryoAtom2 的最终预测 CIF；实验密度、配体区域、测试清单和模型 checkpoint 不变。
- 新入口产生 `parse/<pdb_id>/receptor_tokens.npz`、`density/<pdb_id>/sim.npy` 和 `sim.npz`。正式代码不计算文件哈希；哈希只用于隔离的门控和执行追溯。
- 不复用主 `Ori_Data/labels/<pdb_id>`。其 `atom_labels.npz` 的受体原子轴对齐真实受体，与 CryoAtom2 原子轴不兼容；本入口只服务 `require_targets=False` 的推理与评估。
- CryoAtom2 坐标不执行拟合、平移或裁剪。模拟密度使用实验密度的原始网格几何。

## 正式运行命令

尚未执行。正式命令将在冻结 AdaLigand `Learn/CUMULATIVE` release 后补入；测试、门控和只读核查命令不会混入本节。

## 验证记录

- 服务器定向单元测试：`2 passed`。
- 真实受体等价门控：`6bgi`、`6dqn`、`6rec` 的 token 逐数组相同，`sim.npy` 均逐位相同，最大绝对误差为 `0.0`。
- 门控结果：`/storage/penghongen/tmp/find1_cryoatom2_adapter_gate_20260915/Find_1_pdb_centric_2_job368455_20260915T114442_a10/gate_result.json`。
- 全量真实受体等价门控：Job `368455` 第 11 次执行覆盖 279/279 个唯一 PDB；每个 PDB 的十个 token 数组都相同，`sim.npy` 均逐位相同，全局最大绝对误差为 `0.0`。
- 全量门控结果：`/storage/penghongen/tmp/find1_cryoatom2_adapter_gate_20260915/Find_1_pdb_centric_2_job368455_20260915T120839_a11/gate_result.json`。

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

## 计划与实现差异

- 当前未发现差异。
