# 任务脚本目录

## Stage3 PocketXMol Phase 1

- `adapt_pocketxmol_phase1.sh`：分两阶段执行 A–G 到 PocketXMol 原生缓存的离线适配。脚本先在 `AdaLigand_stage1_py310` 环境中读取与该 A–G 版本匹配的 CCD pickle，只落盘版本中立的键型审计 JSON；随后切换到固定的 `pxm_phase1` 环境，主适配器只读取该 JSON，不再反序列化 CCD pickle。第一个参数是输出根目录，其后可传一至三项 `数据划分名称=冻结清单路径`，并可额外传一个正整数覆盖 worker 数量；默认使用本次 Slurm allocation 的 `SLURM_CPUS_PER_TASK`。脚本固定读取服务器 A–G 数据根目录和未修改的官方 PocketXMol 真值仓库，不运行 Builder docking。

本目录保存 AdaLigand 正式任务的人类入口脚本。每个脚本应自包含地说明所用项目入口、配置、数据位置、结果位置和必要环境变量；不要把某次作业编号或临时目录固化为默认值。

完整使用说明见 [训练与运行说明](../README.md)。
