# AdaLigand v3 基础数据升级实施记录

> 对应计划：`talk/AdaLigand_v3基础数据升级计划.md`
> 当前状态：名单初始化、配体类别掩码、CPU prepared、SMI-TED 和 MoLFormer 均已完成并通过核验；MoLFormer 正式向量已使用 `deterministic_eval=True` 覆盖写入。
> 本记录范围：`all_valid.json`、`info.json` 的一次性初始化，`ligand_area.npz` 六个类别掩码升级，以及配体语言模型 CPU 准备、两套 GPU 编码和汇总入口。受体序列、受体残基映射、受体语言模型和后续清单维护脚本不在本轮实现范围内。

## 1. 已实现内容

一次性初始化文件位于 `Data_Preprocessing/Ori_Data_upgrade/tmp/`：

- `initialize_data_catalog.py` 从当前 split JSON 文件计算排序、去重后的 PDB 并集，写出 `all_valid.json`；
- 同一入口以 `raw/pair_list.jsonl` 中的全部唯一 PDB 为键，合并八类现有产物检查与可靠历史原因，写出 `info.json`；
- `initial_info_reasons.json` 保存本地证据能够逐 PDB 对应的历史原因；
- `initialize_data_catalog.sh` 通过 `训练与运行` 完整模式调用初始化入口；
- 初始化扫描前只把 `5y6p`、`7n6g`、`7z8g`、`9hhl`、`9v7i` 的 `receptor_tokens.npz` 改名为 `receptor_tokens_old.npz`。历史排除清单中的其他 11 个编号没有对应的源产物证据，因此没有扩大改名范围。

正式掩码升级文件位于 `Data_Preprocessing/Ori_Data_upgrade/`：

- `upgrade_ligand_area_masks.py` 按 `occurrences.jsonl::type_tag` 合并已有 `mask_{candidate_id}`，追加六个 `bool (1,Z,Y,X)` 掩码；
- 入口必须显式选择 `--sample-scope all_valid|all_existing`，本轮正式运行选择 `all_existing`；
- Python 入口接收 `--shard-index` 与 `--num-shards`，使用排序全局清单的交错切片选择当前任务负责的 PDB；正式 `--array 0-11` 形成 12 个互斥分片；
- 六字段完整时跳过，六字段部分存在时打印 `partial_existing_masks` 并保持文件不变，六字段全部不存在时才原子替换文件；
- 单个 PDB 的异常只进入普通日志，不更新 `info.json`，也不阻止其他 PDB 继续处理；
- `upgrade_ligand_area_masks.sh` 要求 Slurm 数组环境，从 `SLURM_ARRAY_TASK_ID`、`SLURM_ARRAY_TASK_COUNT` 和 `SLURM_CPUS_PER_TASK` 传递分片编号、分片总数和分片内 worker 数，并通过 `训练与运行` 完整模式调用正式入口。

现有 E3 校验器 `Data_Preprocessing/Ori_Data/adaligand_preprocessing/stages/stage_e/ligand_area.py` 已做最小兼容修改：旧文件合法，六字段完整文件合法，部分字段存在时报契约错误。代码旁 `Data_Preprocessing/Ori_Data/README.md` 同步说明了六个可选字段。

## 2. 名单初始化时的历史问题边界

以下数量描述 Job `339252` 首次初始化之前能够从本地资料恢复的证据，不代表服务器
补救式复核后的最终 `info.json`：

- `pair_list.jsonl` 有 22,386 个唯一 PDB；
- 当前 split 并集有 18,288 个 PDB；
- split 外共有 4,098 个 PDB；
- 本地可靠证据能够逐 PDB 对应 140 个 PDB 的 142 条历史问题；
- 剩余 3,958 个 split 外 PDB 只记录 `unknown_issue`。虽然历史汇总可分为 2,190 个几何不匹配和 1,768 个质量筛选失败，但本地没有可靠的逐 PDB 对应关系，因此没有猜测分类。

`info.json` 中是否存在问题不自动决定 PDB 是否进入 `all_valid.json`。本地执行记录
没有保存补救式复核后各类原因的精确最终数量，因此本文不推测该数量；需要分析
正式当前状态时，应直接读取服务器上的 `info.json`。

## 3. 本地验证

- 正式掩码入口通过 Python 静态编译和 shell 语法检查；
- 隔离 fixture 已覆盖新增六字段、类别重叠、旧字段保持、完整字段跳过、部分字段不改写和两种样本范围；
- 数组分片测试已覆盖 12 个交错分片两两不重叠、并集完整、各分片数量差不超过 1，以及非法分片参数报错；
- E3 隔离测试已覆盖旧文件、六字段完整文件、部分字段和错误数据类型；
- A–G 原有 `test_density_stage_e.py` 在当前 Windows 环境收集时缺少 RDKit，未进入测试函数；这是本地依赖缺失，不是测试断言失败；
- 初始化入口的静态编译、历史原因数量检查和隔离端到端测试通过。

## 4. 名单与掩码正式运行

用户已经提交并完成以下任务：

- Job `339252`：初始化 `all_valid.json` 与 `info.json`；
- Job `339277`：为现有 `ligand_area.npz` 增加六个类别掩码。

任务结果已经只读核验，可以继续后续数据升级。`info.json` 中原先无法逐 PDB
追溯的部分 `unknown_issue`，经历史质量过滤证据复核后按当时可确认的事实补充；
本地没有保留补救后各原因的精确数量，故本文只记录处理性质，不把初始化前的
3,958 条误作最终数量。补救式修改只作用于一次性初始化结果，不改变正式科学处理
管线。后续维护 `info.json` 与只缩小 `all_valid.json` 的扫描器仍未实现，也没有被
配体语言模型代码暗自加入。

当时使用的正式掩码提交命令如下；`--mem 768G` 对数组中的每个任务分别生效：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/upgrade_ligand_area_masks.sh \
  --resource cpu \
  --array 0-11 \
  --cpus 8 \
  --mem 768G \
  -- all_existing
```

## 5. 配体语言模型批量大小前探

用户提供 Job `339574` 的单张 A100-PCIE-40GB allocation；在该 Slurm allocation 中
使用本地下载后上传的官方权重进行了 FP32 吞吐和显存前探。任务完成后 Slurm 状态
为 `COMPLETED`，GPU allocation 和项目锁均已释放。

MoLFormer 的关键结果：

- 202 token 输入：batch 256 约 `621.1 occurrence/s`、峰值约 `1.67 GiB`；batch
  512 约 `630.1 occurrence/s`，吞吐只增加约 1.4%；
- 约 970 token 输入：batch 256 约 `128.7 occurrence/s`、峰值约 `10.05 GiB`；
  batch 512 约 `128.6 occurrence/s`；
- 正式默认 batch size 因此取 256。

SMI-TED 的关键结果：

- 4096 条真实 CCD 样本、传入 batch_size 参数 100 时约 `530.9 occurrence/s`；
- batch 512 及以上约 `485–488 occurrence/s`，比 100 慢约 8–9%；
- 当前分片总数少于 100 时，包装层把实际条数作为 batch_size 参数，避免把大于输入数的参数交给官方接口；
- 后续源码审计确认，冻结的官方实现把 batch_size 当作计算分块数量的参数，而不是严格的单批上限。例如总数 199、参数 100 时仍形成一个 199 项批量，总数 250 时形成两个 125 项批量；正式代码保持这个官方行为并在文档中明确说明；
- 官方 SMI-TED 代码在 `transformers==5.12.1` 下会把 `CCO` 静默分成
  `<bos><pad><eos>`，`transformers==4.57.6` 表现正确，因此正式 SMI-TED 独立
  运行时固定 4.57.6。

## 6. 配体语言模型本地实现

正式代码和字段契约位于
`Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/`。已实现：

- `prepare_smiles.py/.sh`：按 PDB 进行 CPU 数组分片，普通 CCD
  沿用 LigandObject SMILES，BRANCHED 使用 CLC 完整残基身份多重集合精确对应，
  必要时使用 LigandObject present 图后备表示；
- `encode_molformer.py/.sh`：在每个 GPU 数组任务内部跨 PDB 组成全局 batch 256，
  使用官方本地 MoLFormer 权重，不请求截断；
- `encode_smi_ted.py/.sh`：把当前 GPU 分片的全局 occurrence 列表交给官方
  `model.encode`，保留官方规范化、202 token 截断，并传入 batch_size 参数 100；
- `summarize_outputs.py/.sh`：显式重扫 prepared 或模型逐 PDB 正式
  文件，生成全局报告和最高频精确 SMILES；
- `README.md`：只解释输入、化学准备、模型行为、正式产物和完成语义；
- `产物字段参考.md`：按完整点路径集中说明 JSONL、NPZ、分片报告和最终汇总；
- `README_run.md`：集中给出稳定离线环境核对、CPU、两个 GPU 模型和三个汇总的人工命令；
- `真实样本端到端处理示例.md`：用真实 `7d3f` 的 HEM、E/F 链糖 CLC 和 present 掩码展示源字段如何逐步形成 prepared SMILES 与逐 occurrence 向量路径。

正式代码按职责分为 `ligand_preparation.py`、`clc_assembly.py`、`present_graph.py`、
`artifacts.py`、`model_results.py` 与 `run_context.py`。科学主入口保留连续处理顺序；
只服务一个调用点且没有独立科学、外部包或产物边界的短逻辑已经直接写回调用位置。

GPU 模型产物按 `(pdb_id, candidate_id)` 保存，不按 `object_key` 去重。每份模型
NPZ 只包含原始 `float32 (768,)` 分子级向量及身份和 SMILES，不包含 token 级或
原子级向量。普通化学校验、tokenizer 词表、截断、NaN/Inf 和模型失败均记录为
事实，不自动修改 `all_valid.json` 或 `info.json`，也不建立发布门控。

## 7. 配体语言模型本地验证

正式目录已通过以下只读或临时验证：

```powershell
black --check Data_Preprocessing/Ori_Data_upgrade/ligand_language_model
pyflakes Data_Preprocessing/Ori_Data_upgrade/ligand_language_model
python -m compileall -q Data_Preprocessing/Ori_Data_upgrade/ligand_language_model
```

四个正式 shell 分别通过 Git Bash 的 `bash -n`。临时端到端校验入口为：

```powershell
$env:ADALIGAND_LM_SOURCE_ROOT = "Data_Preprocessing\Ori_Data_upgrade\ligand_language_model"
$env:ADALIGAND_REAL_PROBE_ROOT = "C:\Users\15919\Desktop\AdaLigand\Data_Preprocessing\Ori_Data_upgrade\tmp\pdbe_clc_probe_20260811"
C:\Users\15919\Desktop\AdaLigand\Data_Preprocessing\Ori_Data_upgrade\tmp\pdbe_clc_probe_20260811\.venv\Scripts\python.exe `
  Data_Preprocessing\Ori_Data_upgrade\tmp\ligand_language_model_readability_validation\validate_current.py
```

临时校验通过，覆盖分片选择、CCD 正常规范化、CCD 非法原文宽口径回退、LigandObject
present 图过滤、完整残基身份多重集合与两种插入码字段、真实缓存 `7d3f` 的两个 CLC、
有效 CLC 在 LigandObject 与 ligand_coords 缺失时仍可使用、`other` 排除、跨 PDB 全局
模型工作列表、MoLFormer 的 `2+1` 尾块、SMI-TED 的一次全局 `encode`、逐位置向量写回、
覆盖重算时 `encoded→no_smiles`、`encoded→model_failed`、prepared 删除 candidate 的旧 NPZ
清理、NaN 保存、错误输出形状、最终汇总、PDB 身份漂移、CLC 异常后的 present 图回退、
后备图 one-hot 漂移事实，以及重复 `candidate_id` 不覆盖同名 NPZ。临时校验代码位于
`Data_Preprocessing/Ori_Data_upgrade/tmp/`，不属于正式管线，也不会随正式目录交付。

本地验证阶段没有重新运行真实 GPU 推理。官方权重、FP32 模型前向和批量大小已由 Job
`339574` 前探验证；正式全量 GPU 数据任务在 CPU prepared 与汇总核验后由 Codex 按用户
授权依次提交。

## 8. 本轮未实现范围

- 没有实现后续维护 `info.json` 与只缩小 `all_valid.json` 的扫描器；
- 没有实现受体序列、受体残基映射、50 维原子特征或受体语言模型产物。

用户已授权本轮由 Codex 依次提交并监控正式任务：CPU 准备使用 `--array 0-11` 与每任务
8 核，共 96 核；prepared 汇总与核验稳定后，先以 4 卡数组运行 SMI-TED 并汇总核验，
再以 4 卡数组运行 MoLFormer 并汇总核验。代码自身不会自动启动后一阶段；每次实际
提交命令、Job ID、状态变化、异常与处理决定继续追加到本执行记录和 handoff。

## 9. Job 339574 探针环境的一次性迁移

Job 339574 使用的官方权重与 Python 依赖位于临时探针目录。首次正式提交 GPU 任务前，
由用户在服务器 shell 中把它们复制到正式脚本固定读取的稳定位置。以下命令只适用于
稳定位置尚不存在的首次迁移；如果 `test ! -e "$stable"` 失败，应停止并人工检查已有目录，
不得把两个版本直接混合：

```bash
set -euo pipefail

probe=/storage/penghongen/tmp/adaligand_lm_batch_probe_339574_20260811
stable=/storage/penghongen/AdaLigand/model_weights/ligand_language_models

test -d "$probe/models/molformer"
test -d "$probe/models/smi_ted_289m"
test -d "$probe/pydeps"
test -d "$probe/pydeps_smi_v4"
test ! -e "$stable"

mkdir -p \
  "$stable/models/molformer" \
  "$stable/models/smi_ted_289m" \
  "$stable/runtime/molformer" \
  "$stable/runtime/smi_ted_289m/common" \
  "$stable/runtime/smi_ted_289m/transformers4"

cp -a "$probe/models/molformer/." "$stable/models/molformer/"
cp -a "$probe/models/smi_ted_289m/." "$stable/models/smi_ted_289m/"
cp -a "$probe/pydeps/." "$stable/runtime/molformer/"
cp -a "$probe/pydeps/." "$stable/runtime/smi_ted_289m/common/"
cp -a "$probe/pydeps_smi_v4/." "$stable/runtime/smi_ted_289m/transformers4/"

test -d "$stable/models/molformer"
test -f "$stable/models/smi_ted_289m/smi-ted/inference/smi_ted_light/load.py"
test -f "$stable/models/smi_ted_289m/smi-ted-Light_40.pt"
test -f "$stable/models/smi_ted_289m/bert_vocab_curated.txt"
test -d "$stable/runtime/molformer"
test -d "$stable/runtime/smi_ted_289m/common"
test -d "$stable/runtime/smi_ted_289m/transformers4"
```

迁移完成后，每次正式运行只需要按照 `README_run.md` 核对稳定位置，不再读取 Job 339574
临时目录。该迁移不会启动 Slurm 任务。

## 10. 可读性重构独立核验

候选版本先后接受四个相互独立的只读核验：

- 科学契约核验确认 occurrence 身份、CLC 精确多重集合、present 后备、宽口径模型输入、
  跨 PDB batch、分子级向量和旧 NPZ 清理均未发生隐性漂移；
- Python 结构核验确认低调用次数函数只保留用户逐项授权的边界，科学主线没有再次被
  单次调用薄函数切碎，模块依赖无循环；
- 中文注释与文档核验逐项对照正式写入函数、读取函数和模型入口；首次核验确认模块入口、
  数组形状、条件字段、嵌套路径、运行顺序和稳定环境说明均已通过，并要求确定性重跑后
  替换真实示例中的 MoLFormer 数值；该数值替换已在第 11.5 节记录；
- Git 核验确认旧学习区间可从共同基点重建。最终学习线按“文档契约与运行记录 → CPU
  化学准备与共享产物层 → GPU 编码、汇总与 release 支撑”重建为三个线性提交；候选工作树
  与第三个提交的完整 tree 哈希相同。`Learn/CUMULATIVE` 与
  `Learn/ligand-language-model` 同步指向第三个提交；旧 `codex/ligand-language-model`
  分支保持原样。主工作树仍只有开始本任务前的五项用户修改，暂存区为空且五个文件内容
  哈希未变；本轮没有 push、reflog 清理或 Git 对象回收。

最后一次本地验证结果为：Black 10/10、Pyflakes 10/10、`compileall` 10/10、shell
`bash -n` 4/4、Markdown 本地链接通过、完整临时端到端回归通过。端到端回归中的
`not-a-smiles` RDKit 日志来自专门构造的非规范原文宽口径测试，不是未处理异常。

本轮存在一项用户明确授权的双线历史例外：新候选包含重写后的 Python 与 shell，而旧
实现分支必须保持原样。因此最终只能证明新学习端点与当前候选工作树完全等价，不能
宣称新学习端点仍与旧实现端点等价；收口报告必须继续显式保留这一事实。

## 11. 配体语言模型正式服务器运行记录

### 11.1 离线环境迁移与预检

2026-08-12 正式提交前，已把 Job 339574 探针目录中的两套官方模型和补充 Python 包复制到：

```text
/storage/penghongen/AdaLigand/model_weights/ligand_language_models
```

五组源目录与稳定目录均使用 `rsync -rclni --delete` 做逐文件内容比较，结果无差异。Job
339574 的 allocation 日志记录其实际使用
`Pocket_Plus_centos7_cu121_allgpu`；探针环境为 Python 3.10.13、PyTorch
2.4.1+cu121，并在 A100-PCIE-40GB 上报告 `cuda_available=true`。正式预检进一步确认：

- `AdaLigand_stage1_py310` 可以导入 `gemmi`、NumPy、`pdbeccdutils` 和 RDKit；
- `Pocket_Plus_centos7_cu121_allgpu` 配合稳定目录可以导入 MoLFormer 所需的
  Transformers 5.12.1 和 SMI-TED 所需的 Transformers 4.57.6；两者都使用 PyTorch
  2.4.1+cu121；
- 服务器正式代码通过 Python 静态编译、shell 语法检查和临时核心端到端回归；回归中的
  `not-a-smiles` RDKit 输出来自故意构造的宽口径输入；
- 服务器正式代码目录与本地候选目录经过 `rsync -rclni --delete` 内容比较，结果无差异。

一次统计预检误查了 `stage1_preparation_box_pool_2/parse`，因此得到 0；正式代码始终读取
`Ori_Data/parse/{pdb_id}/occurrences.jsonl`。随后已直接确认该正式目录存在真实文件，例如
`parse/5a63/occurrences.jsonl`。这项临时预检错误没有进入正式代码，也没有改变提交命令。

### 11.2 CPU prepared 数组

2026-08-12 02:49（Asia/Shanghai）执行 README 中的正式命令：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/prepare_smiles.sh \
  --resource cpu \
  --array 0-11 \
  --cpus 8 \
  --mem 768G \
  -- all_existing
```

Slurm 返回 Job `339800`。提交入口记录 `cpus_per_task=8`、`pre_hold=0`、
`after_hold=0`；十二个数组任务合计请求 96 个 CPU 核。任务开始后，十二个数组元素均在
进入 Python 前失败，错误是旧版 Bash 在 `set -u` 下展开空数组
`overwrite_args[@]` 时把它判为未绑定变量。该错误没有产生 CPU 科学产物。

随后把 `prepare_smiles.sh`、`encode_smi_ted.sh` 和 `encode_molformer.sh` 的 Python
参数改为始终非空的 `python_args`：数组第一个元素固定为 Python 入口路径，只在用户明确
传入 `--overwrite` 时追加该选项。服务器上的旧版 Bash 参数探针确认：普通模式不会传入
覆盖参数，覆盖模式恰好传入一个 `--overwrite`。

一次监控脚本只按 `339800*` 搜索 allocation 目录，因而错误推断数组元素共享控制目录。
Job `339816` 的双元素实测确认，Slurm 为数组元素提供不同的 `SLURM_JOB_ID`，现有调度系统
本来就按该标识隔离 allocation；相关试验性身份改动已全部撤回。独立审计同时发现
`create_release.sh` 在多个任务同时创建同一 release 时存在先检查、后移动的竞态。最初尝试
使用 `flock`，单节点并发测试通过，但跨 cnode01 与 cnode04 的正式任务证明共享文件系统上的
该锁不能可靠互斥，因此没有保留这一实现。最终实现改用原子 `mkdir` 创建
`.release-id.lockdir`：只有锁所有者可以创建 release 和清理自己的锁；等待者最多等待
30 分钟，超时或发现不完整 release 时只报错，不删除所有者未知的状态。32 进程单节点测试
与跨节点 Job `339835`、`339836` 均通过；跨节点测试恰好记录一次创建、一次复用，两个任务
均为 `COMPLETED`，没有残留锁目录。

修复后于 2026-08-12 再次执行同一条 README 命令，Slurm 返回 Job `339823`。十二个数组
元素均以退出码 0 完成，单个元素耗时 5 分 19 秒至 9 分 09 秒。十二份分片报告的结构与
全局分片关系核验结果为：

- `all_existing` 中 22,386 个 PDB 恰好各出现一次，全部为 `completed`；
- 五类正式 occurrence 共 677,835 个，全部获得非空 SMILES；另有 166 个 `other`
  occurrence 只计数、不进入正式语言模型输入；
- SMILES 来源为 CCD 636,299、CLC 41,532、present-graph 后备 4；
- 没有 PDB 级失败、缺失完成文件或临时写入文件残留；
- 十二个任务记录的依赖版本一致：NumPy 2.2.6、RDKit 2026.3.3、
  pdbeccdutils 1.0.3、gemmi 0.7.5。

以上计数是宽口径运行事实，不替代 prepared 全局报告中的逐记录字段，也不自动决定数据
是否发布。

### 11.3 prepared 全局汇总

CPU 分片核验通过后，执行 README 中的正式命令：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/summarize_outputs.sh \
  --resource cpu \
  -- prepared all_existing
```

Slurm 返回 Job `339847`，任务在 cnode01 运行 7 分 51 秒后以退出码 0 完成。
`prepared/reports/final_summary.json` 与十二份分片报告的总数一致：

- 期望、实际存在的 PDB 均为 22,386，没有缺失 PDB；
- 共读取 677,835 条正式 occurrence，全部具有非空 SMILES；
- 类别计数为 ion 341,567、small_molecule 219,216、sugar 109,267、
  nucleotide_like 6,155、peptide_like 1,630；
- SMILES 来源仍为 CCD 636,299、CLC 41,532、present-graph 4；
- 共有 3,588 种精确 SMILES；最高频字符串为 `[Mg+2]`，出现 280,916 次且没有并列。

最高频字符串只用于报告，不参与模型输入选择。prepared 阶段据此完成运行核验，可以进入
SMI-TED。

### 11.4 SMI-TED Light 289M

prepared 汇总核验通过后，执行 README 中的正式命令：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_smi_ted.sh \
  --resource a100 \
  --gpus 1 \
  --array 0-3 \
  -- all_existing
```

Slurm 返回 Job `339853`。四个数组元素均在 gnode02 运行，各占一张 A100。四片读取到的
模型输入分别为 163,119、172,598、169,796、172,322，总和与 prepared 的 677,835 条
记录完全一致；对应 PDB 数为 5,597、5,597、5,596、5,596。

首次全量调用暴露一个共同问题。冻结的官方 `encode` 会先对列表中的每个字符串调用
`normalize_smiles`；解析失败时该函数返回 `None`，任一 `None` 混入列表都会使 tokenizer
拒绝整个批量。四个分片因此都进入逐 occurrence 后备路径。该路径不丢样本，但会把全部
67.8 万条输入退化为单条调用，明显违背本轮使用全局 batch 的性能目标。监控确认这是共同
问题后，为四个 allocation 创建各自的 `kill_lock`，由项目运行系统终止进程组并释放
资源；Job `339853` 的四个数组元素随后以人工终止对应的失败状态退出，没有写出分片报告。
中断前只写出的少量孤立 NPZ 不构成完成标志；下一次进入这些 PDB 时，
`load_model_work` 会先删除没有 `results.jsonl` 对应的旧向量。

修复没有用诊断结果筛除 occurrence。最新逻辑为：

1. 仍用同一个官方 `normalize_smiles` 记录每条输入的规范化事实；
2. 规范化成功项组成一个跨 PDB 全局列表，交给官方 `model.encode`；
3. 规范化失败项仍逐条调用同一公开接口，使官方错误或返回向量都能按 occurrence 记录；
4. 只有规范化成功组的全局调用再次发生普通异常时，才对该组逐条重试；CUDA 致命异常
   仍立即终止分片。

本地端到端回归通过，专门验证规范化失败项仍被公开接口调用。随后用一张真实 A100 提交
临时 Job `339858`：`C` 与 `CC` 在同一批量中成功得到两个 `(768,) float32` 向量，
`not-a-smiles` 被单独调用并按官方异常记录为 `model_failed`；探针以退出码 0 完成。这证明
隔离只避免 `None` 污染有效批量，不把诊断变成筛选条件。

科学契约与注释文档分别通过独立复核后，使用覆盖参数重提正式四卡任务：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_smi_ted.sh \
  --resource a100 \
  --gpus 1 \
  --array 0-3 \
  -- all_existing --overwrite
```

Slurm 返回 Job `339861`。元素 0 位于 gnode01，元素 1-3 位于 gnode02；四个任务跨节点
同时请求新 release 时恰好一个创建、三个复用。四个元素均已进入规范化成功组的全局批量
前向，分别隔离 237、79、106、153 个规范化失败 occurrence，共 575 个，供后续单条公开
调用。四个元素均完成全局批量前向，并逐条实际调用这 575 个隔离输入。四个数组元素分别
运行约 27.7、22.7、22.1、23.3 分钟，最终全部以 `COMPLETED 0:0` 退出并写出分片报告；
没有再次出现成功组全局 `encode` 失败或 CUDA 错误。

随后把只读分片核验作为 CPU Job `339894` 提交，避免在登录连接上执行长时间元数据扫描。
Job `339894` 以 `COMPLETED 0:0` 退出，确认：

- 22,386 个 PDB 在四个分片中恰好覆盖一次，677,835 条模型输入全部产生状态；
- 677,260 条状态为 `encoded`，575 条为 `model_failed`；后者正好等于隔离输入总数，说明
  它们被公开接口实际尝试并如实保存失败，而不是被预检筛除；
- prepared 不可用 PDB、跳过 PDB、残留临时文件均为 0；
- 四片均使用 PyTorch 2.4.1+cu121、Transformers 4.57.6、CUDA 12.1 与一张
  NVIDIA A100-PCIE-40GB，依赖和硬件事实一致。

分片核验通过后提交正式汇总：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/summarize_outputs.sh \
  --resource cpu \
  -- smi_ted_289m all_existing
```

Slurm 返回 Job `340175`。该任务从逐 PDB `results.jsonl` 独立重算全局计数，并逐一核对
encoded 状态指向的 NPZ 是否存在。Job `340175` 以 `COMPLETED 0:0` 退出，正式
`final_summary.json` 确认：

- 22,386 个预期 PDB 全部存在，没有缺失 PDB；
- 共 677,835 条记录，其中 `encoded=677260`、`model_failed=575`；
- 677,260 个成功向量的 NPZ 文件全部存在，且有限性诊断均为 `all_finite`；
- 模型实际输入共有 3,491 种精确 SMILES，最高频字符串仍为 `[Mg+2]`，出现
  280,916 次且没有并列。

### 11.5 MoLFormer

SMI-TED 正式汇总通过后，按运行说明提交 MoLFormer：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_molformer.sh \
  --resource a100 \
  --gpus 1 \
  --array 0-3 \
  -- all_existing
```

Slurm 返回数组 Job `340231`。四个数组元素分别分配 163,119、172,598、169,796、
172,322 条 occurrence，合计 677,835 条；每个数组元素都把各自 PDB 的 occurrence
汇入跨 PDB 的全局工作列表，再以 256 为批量大小执行官方模型。任务运行期间出现的
`lm_head.* UNEXPECTED` 是 `AutoModel` 从带掩码语言建模预测头的官方检查点加载基础模型时
丢弃预测头参数的官方提示；正式产物读取基础模型的 `pooler_output`，没有读取被丢弃的
`lm_head`。四个元素分别运行约 30.0、32.1、35.5、38.9 分钟，底层 allocation
`340232`、`340233`、`340234`、`340231` 均以 `COMPLETED 0:0` 退出并写出分片报告。

随后提交只读分片核验 Job `340265`。该任务以 `COMPLETED 0:0` 退出，确认：

- 22,386 个 PDB 在四个分片中恰好覆盖一次；
- 677,835 条模型输入全部为 `encoded`，没有 `model_failed` 或 `no_smiles`；
- prepared 不可用 PDB、跳过 PDB、残留临时文件均为 0；
- 四片依赖均为 PyTorch 2.4.1+cu121、Transformers 5.12.1，硬件均为
  NVIDIA A100-PCIE-40GB、CUDA 12.1、cuDNN 90100；
- 四片实际吞吐依次约为 90.56、89.50、79.75、73.84 个向量/秒。

分片核验通过后，按运行说明提交正式汇总：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/summarize_outputs.sh \
  --resource cpu \
  -- molformer all_existing
```

Slurm 返回 Job `340273`。该任务以 `COMPLETED 0:0` 退出；正式
`molformer/reports/final_summary.json` 确认：

- 22,386 个预期 PDB 全部存在，没有缺失 PDB；
- 677,835 条记录全部为 `encoded`，五类数量与 prepared 完全相同；
- 677,835 个成功向量的 NPZ 路径全部存在，有限性诊断均为 `all_finite`；
- 模型输入保留 prepared 的 3,588 种精确 SMILES，最高频字符串为 `[Mg+2]`，出现
  280,916 次且没有并列。

另提交临时只读的 NPZ 内容抽样核验。首次 Job `340266` 冻结了修正前的临时脚本，其中
SMI-TED 模型名称字符串与正式常量拼写不同；确认后使用项目 `kill_lock_340266` 终止该
无效扫描，没有修改任何正式产物。修正后的 Job `340277` 以 `COMPLETED 0:0` 退出：
对两套模型各稳定抽取 1,000 个 encoded occurrence，逐个解压并核对 NPZ 字段、身份、
模型名、SMILES、`float32 (768,)` 向量和有限性诊断，2,000 个样本全部通过且向量全部
有限。该脚本位于已忽略的 `tmp` 目录，不属于正式管线。

为分析 SMI-TED 的 575 条 `model_failed`，另提交临时只读归因 Job `340353`。该任务以
`COMPLETED 0:0` 退出，确认失败分布为：138 个 PDB、91 种精确 prepared SMILES；类别
为 `small_molecule=564`、`sugar=9`、`ion=1`、`nucleotide_like=1`，来源为
`ccd=458`、`clc=117`。575 条均是独立官方规范化没有得到非空字符串，随后仍逐条调用
公开接口，再由 tokenizer 对官方产生的空值报同一种输入类型异常；它们不是预检删除、
prepared 缺失或向量写入失败。

最终科学独立审计发现，MoLFormer 官方 checkpoint 的
`config.json::deterministic_eval=false` 会使模型在 `eval()` 状态的每次前向重新抽取线性
注意力随机特征映射，而官方特征提取示例使用 `deterministic_eval=true`。现有正式向量
全部有限且路径完整，但同一输入在重跑或改变 batch 边界时可能逐值不同。

为量化影响，先提交不写正式目录的 A100 探针 Job `340358`。由于该任务最初等待 A100，
又使用同一脚本提交 CPU 探针 Job `340362`，后者先以 `COMPLETED 0:0` 退出。它对三个
SMILES 连续执行四次前向：checkpoint 默认模式的后续三次均不等于第一次，最大绝对差
依次为 6.2211、5.7869、2.0226；官方特征提取模式 `deterministic_eval=true` 的后续三次
均与第一次逐元素完全相同，最大绝对差均为 0。冻结 checkpoint 还实际保存了十二层
`feature_map.weight`，因此确定性模式使用随权重保存的特征映射，不依赖每个进程初始化时
临时抽取的新矩阵。A100 探针随后获得 `gnode02`，Job `340358` 以 `COMPLETED 0:0`
退出；其确定性模式同样连续四次逐元素完全相同，最大绝对差和逐 occurrence L2 差均为 0。

正式入口据此在 `AutoModel.from_pretrained` 中显式传入 `deterministic_eval=True`，并在
模型前向前核对 `model.config.deterministic_eval is True`。该修正不改变样本、SMILES、
batch size、向量形状或正式字段，只消除前向次数、batch 边界和逐 occurrence 重试路径
造成的随机特征映射漂移。修正后重新执行 Python 静态编译、四个 shell 的 `bash -n` 和
服务器临时端到端回归，结果均通过。

2026-08-12 14:49（Asia/Shanghai）按运行说明提交全量覆盖重跑：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_molformer.sh \
  --resource a100 \
  --gpus 1 \
  --array 0-3 \
  -- all_existing --overwrite
```

Slurm 返回数组 Job `340367`。四个数组元素对应的实际 Job 为 `340473`、`340501`、
`340505` 和 `340367`，分别运行约 34.8、46.6、34.2 和 37.6 分钟，均以
`COMPLETED 0:0` 退出。四片分别处理 163,119、172,598、169,796 和 172,322 条
occurrence，合计 677,835 条。

只读分片核验 Job `340560` 以 `COMPLETED 0:0` 退出，确认 22,386 个 PDB 在四片中
恰好覆盖一次，677,835 条模型输入全部为 `encoded`，prepared 不可用、跳过已有和残留
临时文件的数量均为 0。四片都使用 PyTorch 2.4.1+cu121、Transformers 5.12.1、
CUDA 12.1 和 NVIDIA A100-PCIE-40GB；实际吞吐约为 80.52、66.35、85.35 和
78.51 个向量/秒。

随后按运行说明提交正式汇总 Job `340564`。该任务以 `COMPLETED 0:0` 退出，写入
`molformer/reports/final_summary.json`：22,386 个预期 PDB 全部存在，677,835 条记录
全部为 `encoded`，有限性诊断全部为 `all_finite`，缺失 NPZ 数量为 0；模型输入包含
3,588 种精确 SMILES，最高频字符串仍为 `[Mg+2]`，出现 280,916 次且没有并列。

最后提交只读 NPZ 抽样核验 Job `340594`。该任务以 `COMPLETED 0:0` 退出：对 SMI-TED
和 MoLFormer 各用稳定哈希抽取 1,000 个成功 occurrence，逐个解压核对身份、模型名、
SMILES、`float32 (768,)` 向量和有限性诊断，2,000 个样本全部通过。覆盖后的真实
`molformer/7d3f/candidate_4.npz` 前八项为
`[0.908486, 0.125456, 0.649888, 1.458286, -0.928027, -0.351891, 0.493155, 0.683636]`，
最小值为 `-2.162898`，最大值为 `5.275097`，L2 范数为 `17.576006`；这些实值已回填到
`Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/真实样本端到端处理示例.md`。
