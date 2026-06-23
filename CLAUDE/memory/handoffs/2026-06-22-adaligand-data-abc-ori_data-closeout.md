# Handoff: AdaLigand 数据侧 Stage A–C（Ori_Data）收口 + 服务器全量上线

Date: 2026-06-22

## Current State

- AdaLigand **数据侧 Stage A–C（枚举/下载/解析）已实现并本地验证通过**：`pytest` 19 passed；`mini-example-reorg` 上 A/B/C 跑通；产物布局（reorg 后）已核验。
- 代码现位于 **`Data_Preprocessing/Ori_Data/`**（`code/` 扁平模块包 + `scripts/` 入口 + `sbatch/`）；原 `Stage1/adaligand_stage1/` 已删。产物契约 README 在 **`Ori_Data/code/readme.md`**。
- **全量运行已在服务器链式提交、正在运行**：`A=$(sbatch --parsable a.sbatch)` → `B=$(sbatch --dependency=afterok:$A b.sbatch)` → `C=$(sbatch --dependency=afterok:$B c.sbatch)`。
  - env `AdaLigand_stage1_py310`；代码 `/home/penghongen/My_Project/AdaLigand/Data_Preprocessing/Ori_Data`；产物 root `/storage/penghongen/AdaLigand/Ori_Data`；日志 `…/Ori_Data/logs/{a,b,c}/`。
  - A = 单任务全局枚举(1 核，不分片)；B/C = `--array=0-5`、`--cpus-per-task=8`、`--total_parts 6 --n_jobs 7`。
- 治理四件套（计划/日志/契约/mapping）已全部对齐到 `Ori_Data` 与本轮并发改动。

## Completed（本会话主要动作，跨多轮）

- 收敛并落盘数据计划 `文档/规划文档/数据处理_v2.md`（Stage A–G，A–C 已实现并回填）与模型计划 `文档/other/模型总规划.md`（草稿）。
- 审查另一 agent 的 A–C 实现：发现并跟踪 U1（CCD 来源 / ref_pos provenance，已记录为有意差异）、U3（分辨率 provenance，已重做修复）、U2（跨进程去重竞态，Linux 上良性）。
- **reorg**：诊断/辅助件（`meta` / `resolution_summary` / `_failed_*`）从 `raw/` 移到 `reports/`；`raw/` 只留下游消费的原始件；本地验证通过。
- 建立治理体系：`AGENTS.md` / `CLAUDE.md` / `plan-log-governance` skill / `文档/mapping/计划执行映射.md`，并据其多轮 closeout。
- 写产物契约 README（逐字段 + dtype/shape + 单残基与 BRANCHED 真实例子 + "三套坐标辨析" + 编码速查）。
- 本轮：给 `code/*.py` + `scripts/*.py` 每个文件加"这个文件干什么"的多行头部 docstring；把治理文档 `Stage1`→`Ori_Data`、报告文件名同步为分片形式；记录代码迁移与 **SLURM array 并发加固**（`reports.sharded_report_path` 分片报告 + `io_utils.append_jsonl` 文件锁 + 下载失败分片）。

## Decisions（须延续的关键约定）

- 配体单元 = 共价连通整体；`candidate_id` 组分级、**0 起、resolve_failed 会跳号**；寡聚体 = `List[CCD]` + 残基间键。
- `LigandObject` 沿用 Emap2lig 血统、**只带 ref_pos（参考构象）**；真实坐标单独存 `ligand_coords.npz`（**一个 pdb 一个文件、按 `candidate_id` 索引**）。三套坐标（atoms.coords 占位 / ref_pos / 真实）别拿错。
- union-find **无距离兜底**、C4 **无图同构兜底**（fail-loud）；CCD 来源 = RCSB ligand-CIF（ref_pos provenance 与 Emap2lig bulk 可能不同，有意为之）。
- 产物布局：`raw/` = 下游消费的原始件；`reports/` = 诊断/辅助（不参与训练推理）；SLURM array 下失败报告带 `.part_XXXX_of_YYYY` 后缀。
- 治理：`plan-log-governance`（四类文档=规划/日志/契约/mapping；漂移先问后改；计划保持干净，历史在 git + 日志）。

## Open Questions

- 服务器全量 A 枚举出多少样本？B/C 在全量下的失败率与 `resolve_failed` 率如何？（待跑完核验）
- `文档/other/模型总规划.md` 仍是草稿，且**仍游离在 mapping 之外**（未开工的未来计划，应补一行 mapping 条目，已提示三次未做）。
- Stage F 的 Q-score 阈值 / 全局分辨率门、ligand 类型范围等待定参数（见 plan §11）。
- 模型侧涉及的问题：Build 主干优先 **Emap2lig**（已有密度条件化）吗?借 PocketXMol 的统一全原子表示思想吗?**Build 与 Match 独立训练**、**两个 Build 模型**（受体+密度 / 密度-only）；BOX = 48³ recrop?中心 = ligand-area mask 质心?

## Next Actions

1. 等服务器 A→B→C 跑完，核验：`raw/pair_list.jsonl` 规模、`reports/_failed_*.part_*` 与 `resolve_failed` 分布、产物完整性（occurrences/ligand_coords/receptor_tokens/ligand_objects 对齐）。
2. 给 `模型总规划.md` 在 mapping 补"模型域 / 草稿 / 未开工"一行，关闭 orphan。
3. 开工 **Stage D–G**：原子标签 / 密度重采样 + 模拟图(Chimera molmap) + 差异图 / Q-score 质量(MapQ) / 过滤；开工前建或续 exec_plan、定契约边界。

## Files To Reopen

- `Data_Preprocessing/Ori_Data/code/readme.md` — 产物契约（冷读入口）。
- `Data_Preprocessing/Ori_Data/{code,scripts,sbatch}/` — 当前代码与启动脚本。
- `文档/规划文档/数据处理_v2.md` — 数据计划（§11 待定参数、§5–§8 D–G）。
- `文档/other/模型总规划.md` — 模型计划草稿（Find/Match/Build）。
- `文档/exec_plan/数据下载与解析.md` — 执行日志（最新见 `Update 2026-06-22 (c)`）。
- `文档/mapping/计划执行映射.md` — 计划-执行索引。
