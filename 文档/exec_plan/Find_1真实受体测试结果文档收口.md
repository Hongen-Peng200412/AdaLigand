# Find_1 真实受体测试结果文档收口

本文只记录 `Find_1` PDB-centric-v2 模型在真实受体上已完成测评的本地文档收口。它不拥有 Pocket Plus 推理实现、Job `368455` 的当前资源状态或后续 calibration/validation scored-centered 任务；这些仍由 Pocket Plus 的 `文档/exec_plan/2026-09-12_Find_1真实受体推理与评估.md` 记录。

## 来源与目标

- 正式结果根：`/storage/penghongen/AdaLigand_stage1_inference/Find_1/真实受体/artifacts/Find_1`。
- 模型：`Find_1`，训练采样为 `pdb_centric_2`，固定使用 W&B 已完成步编号 `38622` 对应的 checkpoint。
- 测试：179-PDB `test_0` 为独立推理；149-PDB `test_1` 为从 `test_0` 逐 PDB 事实派生的保序子集。
- 本地交付：`主要结果.md` 汇报 `test_0` 语义及 0.3/0.5 实例主指标；`补充结果.md` 汇报 `test_0` 0.6/top-K 与 `test_1` 完整结果；`说明.md` 保存可追溯路径与契约。

## 完成记录

- [x] 2026-09-13：确认本地三份目标文档原为 U-Net pdb-centric-v2 副本，不复用其数值或路径。
- [x] 2026-09-13：通过只读 SSH 核对四份正式 metrics JSON、四份 JSONL 字段、两份 `test_1` provenance、四份 tuning JSON 与十份结果哈希。
- [x] 2026-09-13：按用户指定的主要/补充边界重写三份本地文档，basic 与 Gaussian 在同表内并列。
- [x] 2026-09-13：文档门控通过：228 个六位小数指标皆位于 `[0,1]`，36 个 top-K 单元格的成功数、分母和百分比相互一致，Markdown 表格列数一致，无 U-Net 身份残留，`git diff --check` 通过。
- [ ] 用户审阅后，再决定是否把三份 Markdown 同步到服务器实验根。

## 正式运行命令

本轮文档收口没有新的正式服务器运行。结果来自已完成的两条命令：

```bash
exec bash "${TASK_PROJECT_ROOT}/训练与运行/sh/infer/find1_real_receptor_evaluation.sh"
```

```bash
exec env PYTHONPATH="${TASK_PROJECT_ROOT}" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 /home/penghongen/anaconda3/envs/Pocket_Plus_centos7_cu121_allgpu/bin/python -u "${TASK_PROJECT_ROOT}/tmp/find1_real_receptor_evaluation_20260912/derive_test1.py"
```

第一条产生 `test_0`，第二条只派生 `test_1` 汇总。详细 release、launch、参数和 SHA-256 见 `收口の结果/Stage1/Find_1(pdb_centric_v2)/使用真实的受体/说明.md`。

## 门控与文档验收

本轮只执行只读核对和本地 Markdown 检查，不属于正式运行命令。验收要求为：

- 六位小数表格值与服务器 metrics JSON 按四舍五入一致。
- top-K 的成功数、分母和百分比相互一致。
- `test_0/test_1` 数量分别为 179/149，且不把派生 `test_1` 表述为独立推理或独立统计样本。
- 三份文档不引用复制来的 U-Net checkpoint、Job、指标、路径或哈希。
- 服务器科学产物和当前运行中的 Job `368455` 不受本轮文档写入影响。

## 待审交付

- `收口の结果/Stage1/Find_1(pdb_centric_v2)/使用真实的受体/主要结果.md`
- `收口の结果/Stage1/Find_1(pdb_centric_v2)/使用真实的受体/补充结果.md`
- `收口の结果/Stage1/Find_1(pdb_centric_v2)/使用真实的受体/说明.md`
