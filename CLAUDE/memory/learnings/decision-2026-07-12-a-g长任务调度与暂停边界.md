# A–G 长任务调度与暂停边界

Type: decision
Date: 2026-07-12
Tags: AdaLigand, Slurm, A-G, 并发, hold, MapQ
Status: superseded by `decision-2026-07-12-a-g原地调度已确认.md`

## Context

AdaLigand 当前近期目标仅为完成 Stage A–G 并取得正式质量分布；G 只运行 `analyze`，不猜阈值、不写最终 `keep_list`，Stage1 重训留到 A–G 完成之后。全量 run 为 `adaligand_ag_20260711T154658`，原依赖链是 `316114 (ABC) → 316115 (DE) → 316116 (F) → 316117 (G analyze)`。

## Memory

- 本条记录的是 2026-07-12 参数讨论期间的临时 hold 边界，不再代表当前控制面。
- 当前权威决策是保留完整原 Job ID 链；`316115` 已 release，仅等待 `afterok:316114`，不得重新 hold、取消或重提。
- DE 已通过受检预置命令固定为 D64/E24，F 固定为 12 个 PDB 外层并发且 MapQ 仍为 `np=8`；`316115/316116/316117` 均已原地设为 `UNLIMITED`。
- DE/F run_cmd SHA-256 分别为 `54658b7a4c2819793a22282ac21a005bfdc6fe1f6c48d4a006c760be2cd380b0`、`8399d571bab44881facbeaa9dd1e738594255a4b4212605cfe418878744f7d13`；远端 core SHA-256 为 `2b811ce9c59ef8f9b5c2484b332b42b3f80204a1573c283412ebc10a5cb666b4`。
- ABC 的 B 仍保持单节点、单 task、`n_jobs=1` 并复用已有文件；不得运行 clean sync。F 科学契约没有变化。

## When To Use

恢复 A–G 全量运行、修改下游 sbatch、处理 heartbeat 或审计 F 资源利用率时，直接使用 `decision-2026-07-12-a-g原地调度已确认.md` 与 ExecPlan；本条只用于解释为何曾短暂 hold。

## Related Files

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `文档/规划文档/数据处理_v2.md`
- `Data_Preprocessing/Ori_Data/sbatch/submit_full_pipeline.sh`
- `Data_Preprocessing/Ori_Data/sbatch/_adaligand_job_core.sh`
- `Data_Preprocessing/Ori_Data/sbatch/de_full.sbatch`
- `Data_Preprocessing/Ori_Data/sbatch/f_full.sbatch`
- `Data_Preprocessing/Ori_Data/sbatch/g_analyze.sbatch`
- `Data_Preprocessing/Ori_Data/code/readme.md`
