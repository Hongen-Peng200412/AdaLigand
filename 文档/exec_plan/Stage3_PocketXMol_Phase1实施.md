# Stage3 PocketXMol Phase 1 实施记录

本文记录 `文档/规划文档/Stage3_PocketXMol_Phase1适配与复现.md` 的实际实施、验证证据、意外发现和计划差异。当前任务只覆盖官方 docking 适配与四种组合复现，不实现密度模块或微调。

## 当前状态

- 状态：实施中。
- Builder 共同基点：`Learn/CUMULATIVE@215def8de77c681d5116d0d4ce67cd4b00054242`。
- Builder 实现分支：`codex/stage3-pocketxmol-phase1`。
- AdaLigand 共同基点：`Learn/CUMULATIVE@0e5ae21bce9080ba5c404485b32f5603c1d58947`。
- AdaLigand 实现分支：`codex/stage3-pocketxmol-compat`。
- PocketXMol 官方真值：`master@65488cf635c856101dbe703ac97e2f10f58e005c`；源码工作树未修改，存在用户已下载的未跟踪 `model_weights.tar.gz`。

## 已完成事实

### 2026-08-07：实施启动与 Git 基线

- 只读检查确认 Builder 和 AdaLigand 工作树均干净，当前分支均为各自的 `Learn/CUMULATIVE`。
- 两个 `Learn/CUMULATIVE` 都是各自仓库按提交者时间形成的唯一最新提交。
- 从两个累计基点分别建立本轮实现分支；没有修改或推动任何远端分支。
- 冻结 Phase 1 的四阶段顺序、双受体契约、配体过滤原因、官方 `pxm` 锚点和 `is_peptide=0` 复现边界。

## 待完成范围

- 建立 A–G 全量兼容性审计与两份实例清单。
- 实现配体、严格受体、扩展受体、肽字段和官方静态运动学缓存。
- 在 Builder 复制官方 docking 最小源码闭包并建立来源映射。
- 依次完成小分子 free、小分子 flexible、肽 free、肽 flexible 的五层验收。
- 重建两个仓库的学习分支，核验端点等价并推进 `Learn/CUMULATIVE`。

## 计划与实现差异

当前尚未产生实现差异。
