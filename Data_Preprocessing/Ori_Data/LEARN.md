# AdaLigand A–G 数据管线阅读指南

本文件只存在于学习分支，用来安排阅读顺序。正式产物字段以同目录 `README.md` 为准，科学定义以 `文档/规划文档/数据处理_v2.md` 为准，维护经过与验证证据以 `文档/exec_plan/A-G数据管线维护与行为等价整理.md` 为准。

## 先建立一张最小地图

数据根由命令参数 `--root` 指定。七个阶段的主要结果是：

1. Stage A 写 `raw/pair_list.jsonl`，确定 `(EMDB, PDB)` 样本及分辨率。
2. Stage B 下载 `raw/rcsb_mmcif/*.cif`、`raw/emdb_maps/*.map.gz` 和 EMDB 元数据。
3. Stage C 写配体实例、真实配体坐标、受体原子和去重配体化学对象。
4. Stage D 写与受体原子逐元素对齐的结合位点标签。
5. Stage E 写实验密度、受体模拟密度和各配体的稀疏体素区域。
6. Stage F 写四种密度相关系数，以及配体和 6 Å 受体口袋的 Q-score。
7. Stage G 先生成质量分布和待筛选候选；只有显式提供阈值配置才生成 `keep_list.jsonl`。

开始读代码前，先打开 `README.md` 的“快速定位”和“跨文件对齐检查”。它们给出文件名、字段、形状、单位、空值和数组对应关系，能避免把模板坐标、沉积坐标、世界坐标和体素索引混在一起。

## 第一遍：只读正式阶段

入口目录是 `adaligand_preprocessing/stages/`。推荐顺序如下：

### A 与 B：样本从哪里来

- `stages/stage_a.py`：检索并选择 EMDB/PDB 样本与分辨率。
- `stages/stage_b.py`：下载、校验和复用原始 mmCIF、密度图与元数据。

读完后，对照 `README.md` 中的 `raw/pair_list.jsonl` 和原始下载件。此时只需理解样本身份和外部输入，不需要读并发、报告或服务器调度代码。

### C：一个结构怎样拆成配体与受体

按以下顺序阅读 `stages/stage_c/`：

1. `constants.py`：元素、残基和配体类别的固定编码。
2. `contracts.py`：Stage C 四类正式产物的完整性条件和读取方式。
3. `ligand_objects.py`：把 CCD 模板构造成可跨 PDB 复用的配体化学对象。
4. `receptor.py`：构造受体重原子、化学键和 49 维特征。
5. `descriptors.py`：生成每个去重配体的全局与逐原子描述子。
6. `upgrades.py`：把仍可识别的旧契约升级到当前字段。
7. `pipeline.py`：把以上步骤连接成单个 PDB 和批量 Stage C。

每读完一个构造函数，就回到 `README.md` 核对它落盘的数组。尤其要确认：

- `candidate_id` 同时连接 `occurrences.jsonl`、`ligand_coords.npz`、Stage D、Stage E3 和 Stage F。
- `ligand_objects` 保存化学模板；`coords_{cid}` 才是沉积结构中的真实位置。
- `receptor_tokens.npz` 的多个长度为 `N` 的数组逐元素对应；`bond_index` 的端点引用这同一组原子。

### D 与 E：从原子坐标得到监督标签和密度网格

- `stages/stage_d.py`：计算每个受体原子到实际存在配体重原子的最近距离，生成 `binding_atom` 和 `instance_id`。
- `stages/stage_e/common.py`：E1/E2/E3 共用的坐标系、等高线和范德华半径规则。
- `stages/stage_e/experimental.py`：生成并验证 `exp.npz`。
- `stages/stage_e/simulated.py`：用 Chimera 在实验图网格上生成 `sim.npz`。
- `stages/stage_e/ligand_area.py`：生成并验证 `ligand_area.npz`。

这里必须始终区分：密度数组是 `ZYX`，世界坐标是 `XYZ Å`；`origin` 是网格物理边界下角点，不是第一个体素中心。`geometry/mrc.py` 负责这套换算，`geometry/legacy/` 保存逐字节冻结的 Pocket Plus 数值函数。

### F 与 G：质量评价怎样变成候选

- `stages/stage_f.py`：生成 `quality_atoms/{pdb_id}.npz`、`quality/{pdb_id}.jsonl` 和对应来源说明。
- `stages/stage_g.py`：检查 A–F 终态，生成分布、候选和可选过滤结果。

先追踪一个 `candidate_id`：从 `present_{cid}` 和配体模板，到 `qscore_{cid}`、`pocket_qscore_{cid}`，再到 JSONL 中的均值、中位数、最小值和计数。随后再看四种相关系数如何在同一 PDB 的所有配体记录中重复保存。

Stage G 的分析模式不会写 `keep_list.jsonl`。过滤发生在 PDB 层：单个配体的 Q-score 判断先形成通过比例，PDB 同时满足相关系数、分辨率和比例阈值后，才保留该 PDB 的全部配体实例。

## 第二遍：理解阶段依赖的公共边界

正式阶段看懂后，再读以下目录：

- `artifacts/`：失败分类、报告落盘和跨阶段产物验证。
- `external_tools/`：Chimera、MapQ 和模型 mmCIF 的唯一适配边界。
- `geometry/`：MRC 读取、重采样、写入与世界坐标换算。
- `execution/`：样本分片、并行执行、运行专属排除和受控失败说明。
- `utils/io.py`、`utils/hashing.py`、`utils/locking.py`：不拥有科学字段的原子写入、稳定摘要和文件锁。

依赖方向应当是阶段模块调用这些具体边界；公共边界不反向调用 Stage A–G 命令入口。科学阈值、产物字段和外部程序命令不能因为“多个文件都用到”就移入 `utils/`。

## 第三遍：最后读命令、维护与调度

- `cli/` 只解析参数、选择阶段函数、汇总状态；科学计算不应写在命令入口中。
- `ops/` 保存默认关闭但仍可复用的审计、来源修复、依赖补足和临时目录回收工具。
- `sbatch/` 保存当前正式调度模板和小规模真实检查入口。

不要从 `ops/` 或 `sbatch/` 开始理解科学主线。它们解释“怎样安全执行、审计或恢复”，不是“配体、密度和质量指标怎样定义”。已经结束且绑定具体作业编号的一次任务脚本已从当前树删除；需要追查时使用 Git 历史和原有 A–G 执行记录。

## 用测试验证自己的理解

推荐按以下顺序读测试：

1. `test_stage1_semantics.py`、`test_stage_c_contract_extensions.py`：Stage C 字段与训练侧需要的语义。
2. `test_atom_labels.py`：Stage D 的距离、阈值和编号。
3. `test_density_stage_e.py`、`test_mrc_contract.py`：网格、原点、体素和稀疏配体区域。
4. `test_quality_projection.py`、`test_chimera_adapter.py`、`test_mapq_adapter.py`：Stage F 的原子对应和外部工具命令。
5. `test_filtering_stage_g.py`：PDB 层过滤与空口袋规则。
6. `test_pipeline_smoke.py`：合成样本从 Stage C 到 Stage G 的完整衔接。

Windows 完整检查使用短临时目录：

```powershell
python -m pytest --basetemp C:\t\adaligand-learn
```

当某条说明与可执行测试或产物验证器不一致时，先把差异记录到维护 ExecPlan；不要为了让学习文字成立而直接修改科学行为。

## 本学习线的提交顺序

从共同起点 `817940a` 开始，本轮关键学习提交为：

1. `01 establish shared artifact and tool boundaries`
2. `02 expose sample download and structure stages`
3. `03 trace labels and density artifacts`
4. `04 connect quality metrics and filtering`
5. `05 separate maintenance operations from production`
6. `06 retire duplicate and run-specific paths`

随后提交继续拆分通用哈希与文件锁、拆分 Stage E 三类产物、重写产物 README、修复真实 Chimera 临时脚本导入并记录双平台与真实工具验证。沿提交顺序阅读，可以先看到稳定边界和正式产物，再看到维护入口与历史脚本退出理由。
