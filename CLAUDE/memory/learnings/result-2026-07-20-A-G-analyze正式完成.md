# AdaLigand A–G analyze-only 正式完成

日期：2026-07-20

正式 run `adaligand_ag_20260711T154658` 的原 DAG `316114→316115→316116→316117` 已全部 `COMPLETED 0:0`。当前可声明完成的是 A–F 科学产物与 Stage G analyze 分布，不包括需要用户显式数值配置的 G filter/`keep_list`。

最终独立验收必须同时核对调度终态、22,386 主键集合、F raw 四终态、原生 exclusion、waiver、`f_release`、G 互斥终态、候选排序唯一性、候选 PDB 集合、全部质量字段分位数以及 `keep_list` 缺失。正式独立审计 summary SHA-256 为 `3a2fa87eeea8267e9e12396910ad388ae044bc8c84f9d3e374d1c1f5e31a9d00`。

known 与 waiver 是可重叠的报告集合，不应机械相加成互斥终态。当前 `1zku/6r8n` 同时属于两者；G 状态采用 waiver-first，故分布中的 92 known PDB 对应互斥状态中的 90 known_failed，加上 45 unknown_failed 和 22,251 success 后恰为 22,386。以后重算 G 计数时必须显式建模交集。
