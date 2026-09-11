# CryoAtom2 测试集受体重建

本任务为 Find_1 的受体来源对照实验生成预测结构。本轮只运行 CryoAtom2，不修改 Find_1、不生成受体特征或模拟密度、不计算配体预测指标。

## 输入与科学边界

- 测试清单：`/storage/penghongen/AdaLigand/held_out/split/held_out_06_chain/test_0.json` 的 `pdb_ids`，本次为 179 个不同 PDB。
- 原始图：根据 `/storage/penghongen/AdaLigand/Ori_Data/raw/pair_list.jsonl` 的 `pdb_id/emdb_id` 对应关系，读取 `raw/emdb_maps/emd_<编号>.map.gz`，不使用 AdaLigand 已重采样图，也不根据真实结构裁剪或对齐。
- 序列：从 `/storage/penghongen/AdaLigand/held_out/sequence_catalog.jsonl` 提取每个 PDB 的全部蛋白质、RNA、DNA entity。每个 entity 一条完整序列，不按 `comparable` 删除短链，不按坐标截断。保留未知字符，沿用 CryoAtom2 的默认读取行为，并记录忽略字符。
- 使用已安装的 CryoAtom2 2.1.1 和官方默认配置，重建全部蛋白质与核酸。后续主实验消费官方默认最终 CIF，保留官方 raw CIF。不使用真实受体坐标、配体坐标、结构掩码或真值驱动的修正。

## 输出与执行

输出根为 `/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06`。`cryoatom2_artifact` 只保存实际运行的逐 PDB 产物；输入副本、日志、来源记录、状态、统计及 Slurm 控制证据统一放入 `运行日志与统计`。代码位于 `测评数据代码/cryoatom2原始预测结构/`。

三个 Slurm 数组任务各申请一张 A100 和 8 核 CPU，以测试清单中 `pdb_ids[分片编号::3]` 分配 PDB。使用项目已有提交系统，同时启用 `--pre_hold` 与 `--after_hold`，不传 `--time`。失败 PDB 记录原因后继续同分片其他 PDB；不换回真实受体、不静默缩小测试集。已验收成功的产物可以跳过，失败重试必须保留先前运行证据。

正式提交入口应为一个固定短命令。验证命令和正式命令分别记录，不把验证、条件判断或临时脚本拼进正式提交命令。

## 验收

- 179 个 PDB 都有明确状态，统计区分未运行、执行中、成功与失败。
- 成功要求官方进程正常退出，最终与 raw CIF 可解析、含原子且坐标有限；记录原子和残基数。此验收不等于结构精度评估。
- 来源包含测试清单、原始图、序列 entity、配置、权重位置、软件版本及实际命令；输入和输出通过 `pdb_id` 对应。
- 主代理先按文件顺序自查函数职责、位置、调用关系和 Docstring，再按注释示例补齐变量语义与科学步骤。之后进行两轮 Git/布局、注释和逻辑独立审查；再只核查已提出的问题。
- 保留实现与学习双线历史并验证端点等价。提交任务和最终完成时更新 handoff 与项目记忆；普通检查只维护执行记录。

具体运行进度与命令见 [执行记录](../exec_plan/CryoAtom2测试集受体重建执行记录.md)。
