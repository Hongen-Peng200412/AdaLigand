# AdaLigand Agent Rules

This file is the primary project governance source for AI agents. `CLAUDE.md` is only a thin compatibility entry point. If the two conflict, follow this file.

## Default Governance Workflow

For non-trivial work, agents MUST check whether the task relates to existing planning documents, execution logs, mapping indexes, or code-near contract README files.

Use the `plan-log-governance` skill whenever a task involves plans, execution logs, mapping, contract README files, drift review, closeout, or plan backfill. The English skill text is authoritative. Any Chinese translation bundled with the skill is for human review only.

Use the `execplan` skill for long-running implementation logs or when the user explicitly requests ExecPlan-style work. If an upstream plan/spec/design document exists, record its path, relationship, covered scope, and known out-of-scope areas near the top of the execution log.

Small bug fixes do not need a new plan, mapping entry, or contract README unless they change documented behavior or artifact interfaces.

## Project Document Roles

- Planning documents live under `文档/规划文档/`. They are clean current specifications, not changelogs.
- Execution logs live under `文档/exec_plan/`. They record progress, decisions, surprises, validation, and outcomes.
- Mapping indexes live under `文档/mapping/`. They link plans to logs, code, contracts, coverage status, and open threads.
- Code-near contract README files may live beside code or artifacts when the current interface, output schema, or run contract should be readable without inspecting all code.

## Drift And Closeout

Agents MUST NOT silently rewrite a planning document after discovering implementation drift. First summarize beneficial, neutral, harmful, and unfinished differences, then ask the user which changes should update the clean specification.

When the user says "收口", "回填计划", "reconcile", "audit drift", or equivalent language, follow the `plan-log-governance` closeout flow before editing plans or mapping files.

Keep detailed history in execution logs and Git history. Keep planning documents clean and current.

## Run-Scoped Scaffolding And Maintenance Closeout

One-off repair, cutoff, supplement, migration, recovery, resource-override, and dynamic run-command code MUST remain visibly separated from the long-lived artifact-production path. Run-scoped tooling needs an explicit scope, evidence location, exit condition, and statement of whether it is safe as a default production entry point.

This rule is retrospective across the whole project. At final closeout, agents MUST inventory both new and pre-existing scaffolding and classify it as long-lived production code, reusable operations tooling, or run-specific scaffolding. A tool may remain only after review documents its continuing value, boundaries, default-call policy, tests, and archive or retirement condition; otherwise remove it or move it out of the active production path.

Do not clean up code that is still required by a running job, unfinished recovery, open audit, or unclosed migration. Before removing scaffolding, freeze its evidence and Git checkpoint. After removal, rerun contract tests, the relevant full suite, and any necessary real smoke test to prove that scientific artifact behavior remains unchanged.

## Path Rules

Use repository-relative paths for local project files in project documents, such as `文档/规划文档/数据处理_v2.md`.

Do not write local machine absolute paths into reusable project governance documents. Server paths that are part of execution, synchronization, or artifact contracts MUST be absolute.

## Current Project Index

The current plan-centric mapping index is `文档/mapping/计划执行映射.md`.
