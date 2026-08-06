# Matcher 独立仓库迁移与 AdaLigand 收口

本文记录把 Stage2 Matcher 的可执行工程迁移到 `C:\Users\15919\Desktop\Matcher`、整理 AdaLigand 双线 Git 历史并建立独立服务器代码目录的实际过程。当前 Matcher 科学规格依据 `文档/规划文档/Matcher_双模式ABO实施计划.md` 与 `文档/规划文档/Matcher_双模式数据契约.md`；跨 Stage2/Stage3 的总体设计仍由 `文档/讨论/模型总规划_v2.md` 和 `文档/讨论/Stage2_Stage3_迭代运算设计_讨论.md` 管理。

本次工作覆盖代码、配置、测试、训练入口、服务器交互入口、项目文档和 Git 双线历史的迁移。A–G 数据处理、BOX-level 产物契约、Stage1 生产任务、服务器历史 checkpoint 与旧 W&B 运行不在迁移范围内；这些内容继续由 AdaLigand 或 Pocket_Plus 管理。

## 已确认边界

- 新仓库最终只保留一个 Python 包 `matcher`；迁移中可以临时导入旧 `matcher` 与 `matcher_v2`，随后在不改变科学行为的前提下合并。
- AdaLigand 保留 A–G、BOX-level 契约、模型总规划、Stage2/Stage3 迭代设计、Stage1 产物事实、项目级记忆和旧训练证据。
- 新仓库服务器代码目录固定为 `/home/penghongen/My_Project/Matcher`，不得覆盖或混入 `/home/penghongen/My_Project/AdaLigand`。
- 新仓库 release、launch 和锁使用 `/home/penghongen/Feedback/Matcher`；新实验结果使用 `/storage/penghongen/Matcher/Results`。输入数据继续只读使用 AdaLigand 正式数据和 Stage1 产物。
- 不改写 AdaLigand 已有历史，不推送远端 Git，不运行删除式服务器同步，不干预正在运行的 Stage1 Job。
- 旧 Matcher F1 小于 0.2 的训练只作为诊断证据，不原样恢复或重提。

## 进度

- 2026-08-06：删除旧 Matcher heartbeat；确认 Job `335493` 已由 Stage1 Find_0 使用。
- 2026-08-06：确认 `codex/matcher-v2-dual-context@7418cc5` 与 `Learn/CUMULATIVE@a4b4570` 的 tree 均为 `5aa5053e261314c233a41c8cb7a4b668477e75db`。
- 2026-08-06：用户授权完整迁移、AdaLigand Git 收口、独立服务器目录、安全同步和后续低 F1 诊断；正式重训仍需展示最终 YAML 与 shell 后获得授权。
- 2026-08-06：临时暂停两个 Stage1 heartbeat；服务器训练任务保持不变。
- 2026-08-06：建立 `codex/adaligand-workspace-reconciliation`。通用调度器的 `--pre_hold/--after_hold` 改造通过 Pocket_Plus 9 项契约测试；统一 SSH 薄入口通过 PowerShell 语法和本机统一入口存在性检查。

## 后续步骤

1. 把当前工作区的契约、执行记录、mapping 和项目记忆完整纳入 AdaLigand 实现线与学习线。
2. 建立独立 Matcher 仓库，迁移当前实现并合并为单一 `matcher` 包。
3. 运行路径级等价、单元测试、真实小样本和服务器隔离 smoke。
4. 从 AdaLigand 活跃文件树移除 Matcher 可执行工程，更新跨仓库索引并归档旧工作树和本地分支。
5. 恢复两个 Stage1 heartbeat。
6. 诊断旧 Matcher 低 F1；科学契约变化在实现前单独请求决定。

## 计划与实现差异

- 有益差异：尚未形成最终结论。
- 中性差异：尚未形成最终结论。
- 有害差异：尚未发现。
- 未完成范围：独立仓库、单包整合、AdaLigand 删除、服务器隔离 smoke 与低 F1 诊断仍待执行。
