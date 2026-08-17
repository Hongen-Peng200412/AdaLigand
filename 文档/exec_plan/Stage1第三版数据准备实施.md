# Stage1 第三版数据准备实施记录

本文记录 2026-08-17 完成的一次性完整体数组迁移、按日期与质量冻结的数据划分，以及第三版 `0:5:5` BOX 池生产。实现只位于 Pocket_Plus 独立工作树的 `ops/stage1_data_preparation/`；Pocket_Plus 的 Dataset、模型、训练和推理主代码均未修改。

## 实现与隔离边界

- Pocket_Plus 共同实现基点：`f2216171f8279dcee4bb09cba168540e340d67f4`。
- Pocket_Plus 实现分支：`codex/stage1-v3-data-preparation`。
- Pocket_Plus 实现端点：`bbaebe008d42e89923375eeaad98d055b43e030f`。
- Pocket_Plus 学习分支：`Learn/stage1-v3-data-preparation`，端点为 `da659b999eaa70aac26a9ead221a129e4434dd04`。
- 用户验收后的 Pocket_Plus 累计端点：`Learn/CUMULATIVE@186bfd05b90f6cbe3fe165e16068ac4bcdc39c7f`。该提交只增加用户对代码复杂度的批注，没有改变正式数据。
- 独立工作树：`C:\Users\15919\.codex\worktrees\stage1-v3-data-preparation\Pocket_Plus`。
- 服务器工具目录：`/home/penghongen/My_Project/Pocket_Plus/ops/stage1_data_preparation/`。
- 正式数据根：`/storage/penghongen/AdaLigand/Ori_Data`。
- 第三版准备根：`/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3`。
- 第二版 `stage1_preparation_box_pool_2` 未被改写；其目录和完成标志时间均早于本轮运行。

## 一次性完整体数组迁移

迁移把 `exp.npz:grid`、`sim.npz:grid`、`ligand_dist.npz:distance` 和 `ligand_area.npz:union_mask` 分别移动到同目录 `exp.npy`、`sim.npy`、`ligand_dist.npy` 和 `union_mask.npy`。原 NPZ 的其余字段逐值保留，迁移采用 NPY 先发布、NPZ 后替换的可重试原子事务。

- Slurm 数组 Job `343572`：12 个数组元素，每个 9 CPU，总并发 108 CPU；全部 `COMPLETED 0:0`。
- 最终复核 Job `343835`：`COMPLETED 0:0`。
- 检查 22,381 个密度目录和 89,524 个目标位置。
- 89,442 个来源字段成功迁移；82 个目标位置没有来源文件并记录为 `source_absent`。
- 正式 NPY 总字节数为 13,813,200,929,408。
- 权威摘要：`reports/runs/stage1_npy_migration_20260817_v1/summary.json`。

## 冻结划分

划分以 PDB 为不可跨集合的身份键。一个 PDB 对应多个 EMDB 时，使用最早非空 `admin.key_dates.map_release`。首次发布时间严格早于 `2026-01-01` 才能进入非留出候选；非留出记录还必须满足 `map_resolution < 4.0`、`cc_contour > 0.65`，并通过迁移后资产、几何、形状和标签长度核对。

Job `345237` 为 `COMPLETED 0:0`。来源为 22,251 个 PDB、662,078 条 Stage G 候选。审计结果为：

| 状态 | PDB 数 |
| --- | ---: |
| 可训练 | 14,017 |
| 日期留出 | 2,497 |
| 缺日期隔离 | 357 |
| 质量淘汰 | 3,718 |
| 资产无效 | 1,655 |
| 缺文件 | 4 |
| 完整图任一轴小于 80 | 3 |

合格 PDB 按 `sha256(3407|eval|pdb_id)` 排名，前 200 个进入 validation，随后 100 个进入 calibration，其余进入 train。正式集合为：

| 集合 | PDB 数 | 候选记录数 |
| --- | ---: | ---: |
| train | 13,717 | 451,505 |
| validation | 200 | 6,104 |
| calibration | 100 | 2,426 |
| held-out | 2,497 | 81,922 |
| 缺日期隔离 | 357 | 11,327 |

## 第三版 BOX 池

第三版 BOX 池从 `exp.npz:canonical_shape_zyx` 读取完整图形状，不依赖已迁出的 `grid`。每个 occurrence 保留 30 个 bias 候选；偏移由经验体积半径与额外 0–3 Å 独立漂移组成。context 从合法整数起点均匀采样，目标 500、最大尝试 3000、核心受体原子数量下限为 0。正式请求比例为 `center:bias:context = 0:5:5`。

- 108 CPU 数组 Job `346035`：12 个数组元素全部 `COMPLETED 0:0`。
- 最终复核 Job `346063`：`COMPLETED 0:0`。
- train 发布 13,717 个 PDB；validation 发布 200 个 PDB。
- 两个集合的零 context PDB 数均为 0。
- 固定验证选择包含 16,525 个 bias、16,525 个 context 和 0 个 center 条目。
- 最终目录已发布 `manifest.json`、`validation_selection.npz`、`config.json`、`summary.json` 与 `_COMPLETE`。

## 验证与审查

- Windows `Pocket_Plus_windows` 环境：5 项测试通过。
- 服务器 Pocket_Plus 环境：5 项测试通过；全部 shell 入口通过 `bash -n`。
- PowerShell 5.1 同步入口通过解析检查，文件使用 UTF-8 BOM。
- 独立严格审查结论为 `APPROVED`；同步只覆盖 `ops/stage1_data_preparation/`，没有删除参数，也没有同步 Pocket_Plus 主代码。

## 后续边界

本记录到可供训练读取的数据准备产物为止。Dataset 对迁移后 NPY 的读取、`feat[49] + is_backbone[1]` 的模型内 50 维拼接、训练启动和推理程序由后续任务完成；本轮没有提前修改这些主代码。

后续工作的当前规格为 `文档/规划文档/Stage1第三版训练IO实施计划.md`，实施前代码审计与停点为 `文档/exec_plan/Stage1第三版训练IO与入口实施.md`。未来任务应从这两份文档继续，不应把本记录中的“数据准备已完成”误读为 Dataset、Loader 或训练入口也已完成。
