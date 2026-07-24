# 双线 Git 与学习注释重建执行记录

本记录保存 AdaLigand、Pocket_Plus 与个人代码工作 skills 的本轮整理过程。当前目标是恢复可重复使用的学习分支整合流程，补齐 Pocket_Plus Stage1 学习注释，并让 AdaLigand 的实现端点、学习端点和 `Learn/CUMULATIVE` 回到唯一且等价的最新状态。

## 范围

- 更新个人 `dual-track-git-workflow` 和 `ai-code-workflow`。
- 重建 Pocket_Plus 从 `de6a89f` 开始的 Stage1 学习历史。
- 以 `af894df` 为 AdaLigand 最新实现事实，并纳入主工作树中已经获准保留的全部修改。
- 从 `817940a` 重建 AdaLigand 完整学习历史。
- 核验实现端点与学习端点的可执行代码、配置、测试、脚本和产物契约等价。

## 不在范围内

- 不改变 A–G 数据处理或 Stage1 训练的科学定义。
- 不重新运行正式数据生产或训练作业。
- 不把任何本地 Git 改动推送到 GitHub 或其他远端。

## 已确认边界

- AdaLigand 主工作树中的已跟踪修改、删除和未跟踪文件全部保留。
- 已移除的 Codex 辅助工作树内容不作为事实来源。
- 两个同步脚本属于可执行内容，必须同时进入实现端点和学习端点。
- 学习线允许额外增加不影响运行的中文注释、Docstring 和学习文档；其余运行相关文件必须与实现端点等价。
- 学习历史最后一个提交集中保存本轮测试文件。

## 进度

- 2026-07-24：完成两个仓库、旧 skill 和现行 skills 的只读审计。
- 2026-07-24：用户授权忽略并移除全部 Codex 辅助工作树；AdaLigand 与 Pocket_Plus 均只保留主工作树登记。
- 2026-07-24：`dual-track-git-workflow` 已加入“融入目标学习分支”“重新整理目标学习分支”和“未经授权不得推送远端”的规则，`ai-code-workflow` 已加入对应触发映射；两个 skill 均通过格式校验。
- 2026-07-24：Pocket_Plus 已完成 11 个生产 Python 文件的学习型中文注释，并从 `de6a89f` 重建六个线性学习提交。`Learn/auxiliary-supervision-find1` 已指向快照恢复阶段，`Learn/stage1-consolidated` 与 `Learn/CUMULATIVE` 已指向最终核验阶段。
- 2026-07-24：AdaLigand 已把主工作树中获准保留的 19 项修改纳入最新实现分支；随后从 `817940a` 重建 A–G、配体距离辅助标签、服务器脚本、项目记忆和测试组成的十二个线性学习提交。
- 2026-07-24：两个仓库均未向 GitHub 或其他远端推送。训练作业监控仍由 `文档/exec_plan/Find辅助监督与新版Find1端到端实施.md` 独立跟踪，不因本次 Git 整理提前关闭。

## 验证证据

### Pocket_Plus

- 最新实现事实为 `codex/stage1-consolidated@ebadbeac882faea40779f31e441988b118f7c6fa`。该提交是此前 56 项工作区冲突整理后的双亲合并端点，完整保留 `aa1b9e92a95e346b9a8139270854392a981ae4d7` 与另一条实现线的有效改动。
- 本地最终学习端点为 `23761e9b510927ed8dad1dd4327dee41f875ef4a`。配置和测试与实现端点逐字一致；11 个生产 Python 文件只增加注释或 Docstring，去除 Docstring 后的抽象语法树一致。
- 两个端点对当前 Windows 环境能够加载的 15 个本轮测试文件均得到 `96 passed`。`tests/model/test_online_pdb_feature.py` 因当前环境没有 `torch_cluster` 无法收集，该限制同时作用于两个端点。
- `Learn/CUMULATIVE` 的远端仍停留在旧历史；本轮只重建本地分支，没有推送。

### AdaLigand

- 主工作树的 19 项获准修改先保存为 `3a6a92a4b066ed53c0c1daadce3c6dfd2ae5ef38`，再与 `codex/auxiliary-supervision-find1@af894df742e32855c54768bfac8a66563ef94cff` 合并为实现内容端点 `e3404dd0ed5d886bbb0ec7eed7ff7b57dfe87c48`。唯一手工冲突是 `CLAUDE/memory/learnings/gotcha-2026-07-23-CLAUDE根文件与项目记忆边界.md`，采用主工作树中已获准保留的版本；两个同步脚本和全部 Markdown 增删均保留。
- 写入本次收口记录前，完整学习候选端点为 `72e6105eb09e0e08808093c6d1fe43b89dfbb9a6`，包含十二个从 `817940a` 开始的线性提交。全部测试文件集中在最后一个提交。
- `e3404dd` 与 `72e6105` 的完整 Git 树逐字一致。两端分别运行完整测试，结果均为 `302 passed, 4 skipped`；四项跳过来自 Windows 缺少 Linux Bash 进程树或符号链接权限。
- 本文、计划映射和 CLAUDE 项目记忆属于最终收口文字，必须以相同内容进入实现端点与学习端点；纳入后再次核对完整 Git 树。

### Skill 与工作树

- `dual-track-git-workflow` 已明确支持把工作区或指定提交融入目标学习分支、重新整理指定学习分支、逻辑改动先进入实现线、全部测试文件位于学习历史最后一个提交，以及未经用户允许不得推送远端。
- `ai-code-workflow` 已增加上述两类任务的触发映射。两个 skill 的 `SKILL.md` 与 `agents/openai.yaml` 均经过结构校验。
- 用户明确要求忽略的 Codex 辅助工作树已经移除；本次重建创建的临时工作树只用于受检历史重建，正式分支推进后必须删除。
