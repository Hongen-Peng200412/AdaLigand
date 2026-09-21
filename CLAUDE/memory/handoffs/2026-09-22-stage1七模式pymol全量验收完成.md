# Handoff: Stage1 七模式 PyMOL 全量验收完成

Date: 2026-09-22

## Current State

Stage1 七模式 PyMOL 合并会话已经完成 179/179 个 `test_0` PDB 的服务器生成、只读门控、代表样本回载和 Windows 完整下载。服务器根为 `/storage/penghongen/AdaLigand_stage1_visualization/stage1_7mode_pcv2_test0_probability_mean`，本地根为 `D:\AdaLigand_Stage1_PyMOL\stage1_7mode_pcv2_test0_probability_mean`。

A800 Job `379402_0` 当前处于 `try_lock`，`after_lock_379402` 保留；未经用户明确授权不要释放。H100 Job `378587` 已不再执行本任务，当前由另一套 PocketXMol 命令使用，不应由本任务操作。

## Completed

- 179 个 `.pse` 和 179 行 `manifest.jsonl` 顺序严格匹配 `test_0`，无临时会话。
- 七种模式的候选总数与源 evaluation NPZ 一致；Emap2lig 装入数为 `min(100,N)`；默认排序均为 `probability_mean`。
- 10,173 个来源文件在生成前后大小与纳秒修改时间一致，正式 Stage1 产物保持只读。
- 服务器 PyMOL 3.1.0 回载 `9hjx`、`11jb`、`30yu`、`9gjg`，平级组、scene、默认显隐、世界坐标、`isolevel` 和局部 mesh 全部通过。
- 服务器输出为 66,436,749,133 字节；179 个会话合计 66,436,365,577 字节。
- 本地 179 个会话与服务器 SHA-256 清单逐项一致：`Missing=0`、`Extra=0`、`Mismatch=0`。
- Windows PyMOL 3.1.6.1 回载 `9hjx.pse` 通过。Windows 当前内存不足，未强行回载 4.89 GB 的 `11jb.pse`。
- 完整执行、阻塞诊断和验收记录已写入 `文档/exec_plan/Stage1_PyMOL可视化实施.md`，规划回填与映射同步完成。

## Decisions

- 用户指定把本任务从 H100 Job `378587` 切换到 A800 Job `379402_0`。A800 allocation 为 16 CPU，因此最后一轮使用 8 个独立 worker。
- `9gjg` 首次运行 60 分钟未完成，被判定为阻塞。只读堆栈证明原因是直接在 Lustre mmap 上进行 ZYX→XYZ 跨页转置，不是 PyMOL mesh 或 `.pse` 压缩。
- `load_density()` 先按 ZYX 连续顺序读入内存，再执行相同转置。该修复不改变密度值、分块、坐标或对象契约。实现提交为 `5dcbde1`，学习提交及 `Learn/CUMULATIVE` 为 `eac9ce2`。

## Open Questions

- 是否释放 `379402_0` 的 A800 allocation 必须由用户明确决定；当前不要删除 `after_lock_379402`。
- 若用户希望在 Windows 本机回载 `11jb.pse`，应先自行释放足够内存或在更大内存机器上操作；不要关闭用户程序来腾挪内存。

## Next Actions

1. 用户可直接从本地交付根打开任意 PDB 的 `.pse`。
2. 如需释放 A800，先再次核对 `try_lock`、无活动验证进程和精确 `after_lock` 路径，再等待用户明确授权。
3. 后续若增加局部密度或新预测模式，继续通过 profile 扩展，不在读取逻辑中按模型名猜路径。

## Files To Reopen

- `可视化套件/Stage1/README.md`
- `可视化套件/Stage1/build_session.py`
- `可视化套件/Stage1/build_comparison_sessions.py`
- `可视化套件/Stage1/profiles/stage1_7mode_pcv2_test0.json`
- `文档/规划文档/Stage1_PyMOL可视化会话.md`
- `文档/exec_plan/Stage1_PyMOL可视化实施.md`
- `文档/mapping/计划执行映射.md`
