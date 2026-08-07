# Stage3 PocketXMol Phase 1 实施记录

本文记录 `文档/规划文档/Stage3_PocketXMol_Phase1适配与复现.md` 的实际实施、验证证据、意外发现和计划差异。当前任务只覆盖官方 docking 适配与四种组合复现，不实现密度模块或微调。

## 当前状态

- 状态：实施中。
- Builder 共同基点：`Learn/CUMULATIVE@215def8de77c681d5116d0d4ce67cd4b00054242`。
- Builder 实现分支：`codex/stage3-pocketxmol-phase1`；当前实现端点为 `de0c4851b45662e7e8dc686ff9a029a91c046105`。
- AdaLigand 共同基点：`Learn/CUMULATIVE@0e5ae21bce9080ba5c404485b32f5603c1d58947`。
- AdaLigand 实现分支：`codex/stage3-pocketxmol-compat`；当前实现端点为 `ccc7aaffff7e76af0da79dba1cd620f66b8cf4c5`。
- PocketXMol 官方真值：`master@65488cf635c856101dbe703ac97e2f10f58e005c`；源码工作树未修改，存在用户已下载的未跟踪 `model_weights.tar.gz`。
- 四种 docking 组合中，小分子 free 与小分子 flexible 已在确定性 CPU 主验收中通过输入、100 步轨迹和重建后产物的逐位比较。肽 free 只通过官方示例路径比较，尚未用 PepBDB base 完成正式验收；肽 flexible 尚未正式验收。

## 已完成事实

### 2026-08-07：实施启动与 Git 基线

- 只读检查确认 Builder 和 AdaLigand 工作树均干净，当前分支均为各自的 `Learn/CUMULATIVE`。
- 两个 `Learn/CUMULATIVE` 都是各自仓库按提交者时间形成的唯一最新提交。
- 从两个累计基点分别建立本轮实现分支；没有修改或推动任何远端分支。
- 冻结 Phase 1 的四阶段顺序、双受体契约、配体过滤原因、官方 `pxm` 锚点和 `is_peptide=0` 复现边界。

### 2026-08-07：AdaLigand A–G 兼容包

- 提交 `61ad49278a71ae66bb65fffc89efc415d2d0c3f7` 在 `Data_Preprocessing/PocketXmol_compat/` 建立独立 Python 包。`pocketxmol_compat.adapter.adapt_occurrence` 以一个 `(pdb_id, candidate_id)` 为单位，连接 A–G occurrence、沉积配体坐标、LigandObject、原始 CCD 模板、原始 mmCIF 与 `receptor_tokens.npz`。
- 配体适配已经实现 `type_tag`、共价实例、沉积重原子完整性、官方 11 种元素、四种官方键和线性标准肽无损重建审计。受体适配先用原始 mmCIF 身份选择残基质量中心到任一真实配体重原子严格小于 `10 Å` 的完整残基，再分别生成 `pocketxmol_native` 的官方 25 维严格字段和 `adaligand_extended` 的 A–G 49 维切片。
- `pocketxmol_compat.official_motion` 按文件位置调用官方 `process/process_torsional_info.py::get_torsional_info_mol`。离线缓存保存 `fixed_dist_torsion`、`path_mat`、`nbh_dict`、`tor_bond_mat`、`tor_twisted_pairs` 和分子对称性字段；带随机根节点选择的三种 `*_anno` 字段继续留给官方 `ConfTransform` 现场生成。
- 适配包同时生成严格资格清单、扩展资格清单、全量审计记录、原因汇总以及每实例来源/完成记录。正式代码没有内容哈希；`source.json` 只保存可读路径、A–G 身份和预期官方 Git 提交。
- 提交 `a192cb983ff4d227c6ef2bacfc9ed049bf1ec101` 增加 `records/<split>/<pdb_id>_<candidate_id>.json` 单实例结果缓存。未指定 `--overwrite` 时，过滤实例也可从记录恢复；声称生成实例目录的缓存必须同时存在对应 `complete.json`，否则立即报错。指定 `--overwrite` 时重新执行该实例。
- `tests/test_ligand_contract.py`、`tests/test_receptor_contract.py` 和 `tests/test_cache_semantics.py` 共 9 项针对性测试已经通过，覆盖配体双向键、标准线性肽、官方氨基酸顺序、严格 `<10 Å`、原始残基分类、扩展受体切片和三种缓存恢复边界。这些单元测试不等于真实 A–G 全量适配或四种 docking 验收。
- 首次 A–G smoke 直接在 PocketXMol 固定环境中反序列化由较新 RDKit 生成的 `raw/ccd_cache/*.pkl`。跨 RDKit 版本反序列化不可靠，因此该次 smoke 的过滤与资格统计作废，不能作为契约证据。
- 提交 `927fe0421b5ac9f059a81a15add57fa3eea616a5` 把来源化学审计改为两个阶段：先在生成 CCD pickle 的 A–G 环境中读取实际键型并输出不含 RDKit 对象的 `source_chemistry_audit.json`，再在 PocketXMol 环境中运行主适配器；主适配器只读取审计 JSON，不再打开 CCD pickle。该提交同时补充清单展开、来源化学审计和缓存失效边界测试。
- 提交 `ccc7aaffff7e76af0da79dba1cd620f66b8cf4c5` 允许冻结的 PDB 级 train、validation、calibration 清单展开为该 PDB 的全部 A–G occurrence，同时继续支持显式 `(pdb_id, candidate_id)` 实例清单。这使正式三划分适配覆盖实际 occurrence，而不把一个 PDB 错当成一个配体实例。

### 2026-08-07：Builder 官方 docking 闭包与严格权重入口

- 提交 `cbe3b46f` 从固定官方提交挑选复制 docking 所需的 `models/`、`utils/`、`process/`、`scripts/`、五份 docking 验收配置、共同 `configs/sample/pxm.yml`、官方示例输入和 `pxm` 相邻训练配置。复制代码保持官方相对位置、类、函数和签名；根 `LICENSE`、`NOTICE.md` 与 `talk/readme_PocketXMol来源映射.md` 保存 MIT 许可和逐文件来源关系。
- 提交 `9f3eb97a` 增加 `utils/native_cache.py`，只读取 AdaLigand 已生成的 PocketXMol 原生缓存；Builder 没有 `adaligand_extended` 名称或分支。该提交同时增加 `models/checkpoint.py::load_official_model_state`：只提取 checkpoint 的全部 `model.*` 参数，去掉前缀后调用 `model.load_state_dict(..., strict=True)`；缺失键、额外键和形状不一致均不被忽略。
- 授权下载的严格锚点文件为 `data/trained_models/pxm/checkpoints/pocketxmol.ckpt`，当前本地大小为 `243,496,215` 字节；相邻的 `data/trained_models/pxm/train_config/train.yml` 已进入 Builder。Job `338293` 已用完整模型实例严格加载 checkpoint 的 `1128/1128` 个 `model.*` 张量，缺失键和额外键均为零。
- Builder 已增加独立轨迹捕获与比较闭包。它从指定源码根导入官方模型、`sample_loop3`、noiser、`outputs2batch`、拆批、解码和重建函数，保存变换后批次、首次模型输入、100 个采样步、最终采样构象、置信度与 `postprocessed.pt`。比较器对张量执行 `torch.equal`，并逐元素比较重建后的分子或肽结构记录。
- 提交 `e0fb644a44f0df2a0429a4eaa7f12cc641c6fd48` 补齐官方重建产物比较；提交 `de0c4851b45662e7e8dc686ff9a029a91c046105` 明确把同一软件环境中的确定性 CPU 逐位比较作为主复现证据，GPU 官方自比较只用于识别 CUDA 非确定性。
- `C:\Users\15919\Desktop\PocketXMol` 的只读复核仍为官方 `master@65488cf635c856101dbe703ac97e2f10f58e005c`；没有 tracked 修改，只有用户下载的未跟踪 `model_weights.tar.gz`。Builder 的复制和后续运维修改没有写回官方仓库。

### 2026-08-07：服务器环境从失败到闭合

- Builder 已把安全同步和通用 Slurm 提交入口改为项目自身的 `/home/penghongen/My_Project/Builder` 与 `/home/penghongen/Feedback/Builder`。环境任务使用 `训练与运行/sh/setup_pxm_phase1_env.sh`，只建立 `/home/penghongen/anaconda3/envs/pxm_phase1`，不运行 docking。
- Job `338280` 使用 simple 模式申请 16 CPU。它直接解析官方 `environment_cu128_base.yml`，于 `2026-08-07 19:06:18 +08:00` 启动，并在 44 秒后以 `FAILED 1:0` 结束。`LibMambaUnsatisfiableError` 明确表明官方 YAML 同时固定 `python=3.10` 与 `python-lmdb=1.2.1`，而当前 conda 仓库中的该 LMDB 构建只支持 Python 3.7、3.8 或 3.9，不能形成 Python 3.10 环境。日志位于 `/home/penghongen/SIMPLE_RUN/setup_pxm_phase1_env_338280.out` 和同名 `.err`。
- 提交 `6b86e91c19d178595e6fdc1a1804fe501b0f1f3d` 保留官方 YAML 的其余版本约束，但去掉 conda `python-lmdb=1.2.1`，改用官方 `docs/setup.md` 手动安装段允许的 pip `lmdb=1.7.5`。这项改动只解决包管理器冲突，不改变 PocketXMol 模型、数据或采样逻辑。
- Job `338281` 于 `2026-08-07 19:11:03 +08:00` 在 `cnode01` 使用 16 CPU、64 GB 内存启动。Conda 基础环境创建成功，`PeptideBuilder 1.1.0` 与 pip `lmdb 1.7.5` 安装成功；随后 `pip install torch==2.7.0 --index-url https://download.pytorch.org/whl/cu128` 返回 `No matching distribution found for torch==2.7.0`。作业于 `19:14:24 +08:00` 以 `FAILED 1:0` 结束并释放 allocation。日志位于 `/home/penghongen/SIMPLE_RUN/setup_pxm_phase1_env_338281.out` 和同名 `.err`。
- 节点的 glibc 为 `2.17`，官方 CUDA 12.8 与文档中的 CUDA 12.6 wheel 均要求更高的 glibc。环境脚本依照官方 `docs/setup.md` 允许按平台选择 PyTorch/PyG 版本的边界，改用仍提供兼容 wheel 的 PyTorch `2.6.0+cu124`。
- Job `338284` 于 `2026-08-07 19:23:47 +08:00` 启动，运行 19 分 15 秒后 `COMPLETED 0:0`，完成基础环境、PyTorch、PyTorch Geometric 和三个编译扩展安装。Job `338290` 补装测试入口并在 `2026-08-07 20:00:49 +08:00` `COMPLETED 0:0`。最终环境的关键版本为 Python `3.10.20`、PyTorch `2.6.0+cu124`、CUDA build `12.4`、PyTorch Lightning `2.6.0`、PyTorch Geometric `2.6.1`、`torch_cluster 1.6.3+pt26cu124`、`torch_scatter 2.1.2+pt26cu124`、`torch_sparse 0.6.18+pt26cu124`、RDKit `2023.09.3`、NumPy `1.24.4`、SciPy `1.10.1` 和 LMDB `1.7.5`。
- Job `338293` 在 CPU 上运行 Builder 全套测试和严格 checkpoint 验证：`25 passed in 6.45s`，checkpoint 与实例化模型均为 `1128` 个张量，`strict_load=true`；模型名、附加节点特征和输入维数分别核对为 `pm_asym_denoiser`、`[is_peptide]`、`num_node_types=12`、`num_edge_types=6` 和 `pocket_in_dim=25`。该作业于 `2026-08-07 20:07:34 +08:00` `COMPLETED 0:0`。
- 加入重建产物比较测试后，Job `338308` 再次运行 CPU 回归与严格加载，于 `2026-08-07 20:49:58 +08:00` `COMPLETED 0:0`。结果为 `27 passed in 32.52s`，checkpoint 与实例化模型仍为 `1128/1128` 个张量，`strict_load=true`，模型名称、附加特征和输入维数均未变化。

### 2026-08-07：二阶段 CCD 修复后的 A–G smoke

- Job `338300` 使用 AdaLigand 提交 `927fe04` 的二阶段入口和 96 个 worker 处理固定的 18 个 calibration 实例，于 `2026-08-07 20:27:10 +08:00` `COMPLETED 0:0`。结果为 `18/18` 完成、`internal_errors=0`、PocketXMol 严格契约可用 1 个、A–G 扩展契约可用 2 个；扩展集合包含该严格实例。
- 过滤原因计数为：`covalent_ligand_without_attachment_condition=3`、`excluded_type_tag_ion=4`、`incomplete_heavy_atom_coordinates=10`、`nucleic_acid_in_official_training_pocket=1`、`unsupported_element=4`、`unsupported_type_tag=4`。同一实例可以同时具有多个原因，所以原因总数不等于实例数。
- 有效证据位于 `/storage/penghongen/AdaLigand/PocketXMol_compat_phase1_smoke_v2/`；旧 smoke 只保留为问题发现过程，不参与当前资格统计。

### 2026-08-07：calibration 完整适配与三划分全量适配

- Job `338305` 使用 96 个 worker 展开 calibration 冻结 PDB 清单，于 `2026-08-07 20:42:49 +08:00` `COMPLETED 0:0`。它请求并完成 `3532/3532` 个 occurrence，`internal_errors=0`；PocketXMol 严格契约可用 326 个，A–G 扩展契约可用 340 个。
- calibration 的过滤原因计数为：`covalent_ligand_without_attachment_condition=586`、`empty_official_protein_pocket=1`、`excluded_type_tag_ion=2296`、`incomplete_heavy_atom_coordinates=818`、`modified_residue_in_official_training_pocket=3`、`nucleic_acid_in_official_training_pocket=12`、`unsupported_element=2359`、`unsupported_type_tag=618`。同一 occurrence 可以同时具有多个原因，所以原因总数不等于 3532。
- calibration 证据位于 `/storage/penghongen/AdaLigand/PocketXMol_compat_phase1_calibration_v1/`；`pocketxmol_eligible.jsonl` 与 `extended_contract_eligible.jsonl` 分别为 326 和 340 条。
- Job `338306` 同时展开 train、validation、calibration 三份冻结 PDB 清单，来源化学审计确认总数为 `444661` 个 occurrence。运行约 1 小时 32 分时已有约 97125 份实例记录；截至 `2026-08-07 22:18:19 +08:00` 的只读复核为 98635 份 `records/**/*.json`，作业仍在 `cnode04` 运行。最终 `summary.json` 尚未生成，不能宣告全量完成、资格数量或内部错误数量。

### 2026-08-07：小分子 free 采样轨迹比较

- 三次比较均使用 `configs/sample/examples/dock_smallmol.yml`、seed `2024`、batch size `1`、`num_workers=0` 和同一 `pxm` checkpoint。GPU Job `338296` 的 Builder 对官方比较从采样步 0 开始不相等；步 0 的 `pos_in` 逐位相等，但 `pred_pos` 最大绝对差为 `0.009524345 Å`。比较器因严格不等返回 1，Slurm 因此记录为 `FAILED 1:0`，不是运行崩溃。
- 为排除 Builder 移植差异，GPU Job `338298` 连续运行两次官方源码。官方对官方也从采样步 0 开始不相等：步 0 的 `pos_in` 逐位相等，`pred_pos` 最大绝对差为 `0.009795189 Å`。该对照说明 Job `338296` 的 GPU 逐位差异不能单独归因于 Builder；GPU 数值差异仍需单独报告，不能替代正式主验收。
- CPU Job `338302` 在同一软件环境中比较官方源码与 Builder，`transformed_batch.pt`、首次模型输入、100 个采样步中的原始预测与 `outputs2batch` 更新值、最终采样构象及置信度全部逐位相等，`comparison.json` 为 `equal=true`。作业于 `2026-08-07 20:32:29 +08:00` `COMPLETED 0:0`，证据位于 `/storage/penghongen/PocketXMol_phase1_evidence/smallmol_free_cpu_seed2024_v1/`。
- Job `338309` 使用补齐重建比较后的 Builder 端点重新运行小分子 free。官方与 Builder 的 `transformed_batch.pt`、首次模型输入、100 步完整轨迹、最终采样构象、置信度和小分子 `postprocessed.pt` 全部逐位相等，`comparison.json` 为 `equal=true`；作业于 `2026-08-07 20:52:34 +08:00` `COMPLETED 0:0`。证据位于 `/storage/penghongen/PocketXMol_phase1_evidence/smallmol_free_cpu_seed2024_v2/`，小分子 free 五层正式验收通过。
- Job `338310` 使用 `configs/sample/examples/dock_smallmol_flex.yml` 完成小分子 flexible 的同等比较，轨迹与重建后 `postprocessed.pt` 均逐位相等，`comparison.json` 为 `equal=true`；作业于 `2026-08-07 20:55:09 +08:00` `COMPLETED 0:0`。证据位于 `/storage/penghongen/PocketXMol_phase1_evidence/smallmol_flexible_cpu_seed2024_v1/`，小分子 flexible 五层正式验收通过。

### 2026-08-07：肽 free 官方示例路径比较

- Job `338311` 使用 `configs/sample/examples/dock_pep.yml` 比较官方源码与 Builder。两侧的变换后批次、100 步轨迹和肽 `postprocessed.pt` 全部逐位相等，`comparison.json` 为 `equal=true`；作业于 `2026-08-07 20:57:58 +08:00` `COMPLETED 0:0`，证据位于 `/storage/penghongen/PocketXMol_phase1_evidence/peptide_free_example_cpu_seed2024_v1/`。
- 该作业使用官方仓库自带的肽示例，不是 PepBDB base 正式样本。日志还记录 `data/use/files/peptides/dockpep_3bik_pep.pdb` 不存在，官方重建函数随后使用自身的回退路径。因此它只证明肽示例代码路径的 Builder 复现，不满足 Phase 3 的 PepBDB base 正式验收。
- 官方源码生成的 `transformed_batch.pt["is_peptide"]` 为形状 `(87,)` 的张量，87 个值全部为 0；Builder 对应张量也逐位相等。Phase 1 先如实记录并复现该官方行为，不在兼容层或 Builder 中把它改为 1；是否属于官方缺陷留待 Phase 1 之后另行判断。

### 2026-08-07：官方测试数据下载

- Job `338288` 和 `338294` 均因 Zenodo 连接在传输过程中关闭而以 curl 退出码 18 失败；两次下载分别保留了可续传的部分文件。Builder 提交 `b1aded876149edabe31be82d414dd07f1b595752` 把下载器切换为 `wget --continue` 并允许连接中断后持续重试。
- 截至 `2026-08-07 22:18:19 +08:00`，Job `338303` 仍在 `cnode01` 运行。任务检查点记录已下载约 `233368096/725657460` 字节；随后的只读复核显示临时文件增长到 `235477496` 字节。官方 `data_test.tar.gz` 尚未下载完成，不能开始 PepBDB base 等依赖该归档的正式验收。

## 待完成范围

- 等待 Job `338306` 完成 A–G 三划分全量兼容性审计，再以最终 `summary.json` 冻结严格与扩展实例清单；运行中记录数不能替代最终验收。
- 等待官方测试归档下载完成，使用 PepBDB base 完成肽 free 正式五层验收，再完成 PepBDB base_flex 的肽 flexible 验收。
- A–G 肽样本若用于代码路径验证，只标为 `ag_contract_path_validation`，不替代官方 PepBDB 证据。
- 重建两个仓库的学习分支，核验端点等价并推进 `Learn/CUMULATIVE`。

## 计划与实现差异

### 有益差异

- 规划只要求两份资格清单和过滤原因；当前实现额外增加不含内容哈希的单实例结果记录，使被过滤实例和已完成实例可以安全续跑，并用实例目录 `complete.json` 防止复用部分写入。这补全了大规模 CPU 适配的恢复语义，没有改变资格判定。
- 当前实现为配体数组错位、官方运动学异常和官方口袋不支持元素增加专门原因，避免把工程不一致静默归入其他科学过滤类别。
- A–G 兼容入口增加来源环境 CCD 审计与 PocketXMol 环境主适配两个阶段，消除了 RDKit pickle 跨版本读取对资格判定的污染；审计产物只保存版本中立的键型名称、支持状态和可读错误。
- Builder 增加轨迹证据捕获、严格比较和官方对官方控制实验，使“Builder 移植差异”与“同一 GPU 上官方代码自身的非确定性”可以分别判断。
- 重建产物进入同一严格比较闭包后，小分子 free 与 flexible 可以在一份证据中同时覆盖输入、采样、`outputs2batch` 和最终化学结构，补齐了原先只比较采样轨迹的验收缺口。

### 中性差异

- 严格受体产物的规划名称已经统一为磁盘目录名 `pocketxmol_native`；它是唯一供 Builder 消费的官方原生契约，扩展目录仍与 Builder 隔离。
- 官方 YAML 的 `python-lmdb=1.2.1` 无法与 Python 3.10 求解，环境脚本改用官方 `docs/setup.md` 同样允许的 pip `lmdb=1.7.5`。这是依赖安装方式差异，不改变模型执行行为。
- 服务器 glibc `2.17` 不能安装官方 CUDA 12.8/12.6 示例 wheel，因此使用官方手动安装说明允许的 PyTorch `2.6.0+cu124` 与对应 PyG 扩展。CPU 官方对 Builder 的 100 步逐位结果已经闭合代码行为，但该环境差异仍须随 GPU 数值结果保留记录。
- GPU 上相同 seed 和输入的官方对官方运行也不能逐位相等；当前以同环境 CPU 逐位比较保存主代码复现证据，GPU 结果只作为非确定性诊断，不据此放宽正式验收标准。
- 官方肽示例的 `is_peptide` 实测全为 0。当前实现不修正这一行为，只把它作为官方契约事实记录；这不等于确认该值在科学语义上正确。

### 有害差异

- 截至当前未发现仍然存在的有害实现差异。先前缺失沉积坐标的原因命名不一致已经统一为 `incomplete_heavy_atom_coordinates`，不再是开放差异。

### 未完成范围

- 小分子 free 与小分子 flexible 已完成正式五层验收。肽 free 只有官方示例路径证据，PepBDB base 正式验收与肽 flexible 仍未完成；官方测试数据仍在下载，A–G 三划分全量适配仍在运行，双线学习历史也未完成。
