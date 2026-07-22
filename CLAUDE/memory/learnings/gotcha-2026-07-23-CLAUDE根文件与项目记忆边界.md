# 根目录 CLAUDE 文件与项目记忆不是同一机制

Type: gotcha
Date: 2026-07-23
Tags: CLAUDE, project-memory, governance

## Context

AdaLigand 根目录中的 `CLAUDE.md` 已经删除。这个文件的删除容易被错误理解成整个 `CLAUDE` 项目记忆机制已经废弃。

## Memory

删除并停止使用的只有仓库根目录 `CLAUDE.md`。`CLAUDE/memory/` 仍是有效的项目级外置记忆位置，其中现有的 `index.json`、`projects/`、`handoffs/` 和 `learnings/` 均继续有效，也允许按照对应 skill 增加新记录。

规划文档、ExecPlan、执行记录与映射索引继续放在 `文档/` 的既有目录中；需要跨任务恢复当前状态时，可以另外写入 `CLAUDE/memory/handoffs/`，但不得重新创建根目录 `CLAUDE.md`，也不得把两类文档的职责混在一起。

## When To Use

当任务需要保存长期决定、项目状态、阶段交接或下一次任务的恢复说明时，继续使用 `CLAUDE/memory/`。当清理旧入口文件或检查项目治理方式时，不得因为根目录缺少 `CLAUDE.md` 而删除、忽略或判定 `CLAUDE/memory/` 已失效。

## Related Files

- `AGENTS.md`
- `CLAUDE/memory/index.json`
- `CLAUDE/memory/projects/adaligand.json`
- `CLAUDE/memory/handoffs/`
