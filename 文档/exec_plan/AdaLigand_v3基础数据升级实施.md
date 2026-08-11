# AdaLigand v3 基础数据升级实施记录

> 对应计划：`talk/AdaLigand_v3基础数据升级计划.md`
> 当前状态：名单初始化和配体类别掩码已经正式运行并验收；配体语言模型 occurrence 级管线已完成本地实现，尚未运行正式语言模型数据。
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

用户提供 Job `339574` 的单张 A100-PCIE-40GB allocation，子代理在该 allocation 中
使用本地下载后上传的官方权重进行了 FP32 吞吐和显存前探。任务完成后 Slurm 状态
为 `COMPLETED`，GPU allocation 和项目锁均已释放。

MoLFormer 的关键结果：

- 202 token 输入：batch 256 约 `621.1 occurrence/s`、峰值约 `1.67 GiB`；batch
  512 约 `630.1 occurrence/s`，吞吐只增加约 1.4%；
- 约 970 token 输入：batch 256 约 `128.7 occurrence/s`、峰值约 `10.05 GiB`；
  batch 512 约 `128.6 occurrence/s`；
- 正式默认 batch size 因此取 256。

SMI-TED 的关键结果：

- 4096 条真实 CCD 样本、官方 batch size 100 时约 `530.9 occurrence/s`；
- batch 512 及以上约 `485–488 occurrence/s`，比 100 慢约 8–9%；
- 当前分片总数少于 100 时，直接把实际条数作为 batch size；64 条样本若仍传 100，
  官方分片公式会退化成 64 次单样本前向，实测约慢 12.1 倍；
- 官方 SMI-TED 代码在 `transformers==5.12.1` 下会把 `CCO` 静默分成
  `<bos><pad><eos>`，`transformers==4.57.6` 表现正确，因此正式 SMI-TED 独立
  运行时固定 4.57.6。

## 6. 配体语言模型本地实现

正式代码和字段契约位于
`Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/`。已实现：

- `prepare_ligand_language_inputs.py/.sh`：按 PDB 进行 CPU 数组分片，普通 CCD
  沿用 LigandObject SMILES，BRANCHED 使用 CLC 完整残基身份多重集合精确对应，
  必要时使用 LigandObject present 图后备表示；
- `encode_molformer.py/.sh`：在每个 GPU 数组任务内部跨 PDB 组成全局 batch 256，
  使用官方本地 MoLFormer 权重，不请求截断；
- `encode_smi_ted_289m.py/.sh`：把当前 GPU 分片的全局 occurrence 列表交给官方
  `model.encode`，保留官方规范化、202 token 截断与 batch size 100；
- `summarize_ligand_language_outputs.py/.sh`：显式重扫 prepared 或模型逐 PDB 正式
  文件，生成全局报告和最高频精确 SMILES；
- `README.md`：记录输入、化学准备、输出字段、续跑、模型行为、独立运行时和提交
  命令。

GPU 模型产物按 `(pdb_id, candidate_id)` 保存，不按 `object_key` 去重。每份模型
NPZ 只包含原始 `float32 (768,)` 分子级向量及身份和 SMILES，不包含 token 级或
原子级向量。普通化学校验、tokenizer 词表、截断、NaN/Inf 和模型失败均记录为
事实，不自动修改 `all_valid.json` 或 `info.json`，也不建立发布门控。

## 7. 配体语言模型本地验证

正式目录已通过以下只读或临时验证：

```powershell
python -m black --check Data_Preprocessing/Ori_Data_upgrade/ligand_language_model
python -m pyflakes Data_Preprocessing/Ori_Data_upgrade/ligand_language_model
python -m compileall -q Data_Preprocessing/Ori_Data_upgrade/ligand_language_model
```

四个正式 shell 分别通过 Git Bash 的 `bash -n`。临时端到端校验入口为：

```powershell
Data_Preprocessing\Ori_Data_upgrade\tmp\pdbe_clc_probe_20260811\.venv\Scripts\python.exe `
  Data_Preprocessing\Ori_Data_upgrade\tmp\ligand_language_model_validation\validate_ligand_language_model.py
```

临时校验通过，覆盖分片选择、CCD 正常规范化、CCD 非法原文宽口径回退、LigandObject
present 图过滤、完整残基身份多重集合比较、真实缓存 `7d3f` 的两个 CLC、`other`
排除、跨 PDB 全局模型工作列表、孤立 NPZ 重算、NaN 保存、错误输出形状、最终汇总、
PDB 身份漂移记录、CLC 意外异常后的 present 图回退、后备图 one-hot 漂移事实，
以及重复 `candidate_id` 不覆盖同名 NPZ。临时校验代码位于
`Data_Preprocessing/Ori_Data_upgrade/tmp/`，不属于正式管线，也不会随正式目录交付。

本轮没有重新运行真实 GPU 推理。官方权重、FP32 模型前向和批量大小已由 Job
`339574` 前探验证；正式 GPU 数据任务仍须由用户提交。

## 8. 尚未执行

- 没有提交配体语言模型 CPU 准备、MoLFormer、SMI-TED 或最终汇总任务；
- 没有在正式服务器输出根生成 `ligand_language_models/` 产物；
- 没有实现后续维护 `info.json` 与只缩小 `all_valid.json` 的扫描器；
- 没有实现受体序列、受体残基映射、50 维原子特征或受体语言模型产物。

正式配体语言模型任务必须由用户依次提交并验收；CPU 准备通过后才能运行两套 GPU
编码，模型完成后再显式运行各自最终汇总。代码不会自动启动后一阶段。
