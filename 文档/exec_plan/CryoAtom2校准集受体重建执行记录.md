# CryoAtom2 calibration 100 项受体重建执行记录

本记录实现用户 2026-09-12 授权的 calibration 原始结构预测。当前两个分片已经重新提交为 379402_0、379403_1，均在 nvlink 分区排队；正式入口不传 --mem，使用分区默认内存。验收目标是原清单 100 项完整覆盖，全部预测退出码为零，200 份最终/raw CIF 可解析、有原子且坐标有限，来源、实际命令、冻结代码与统计一致；结束后保留两张卡的 after_hold 资源。

本任务复用[测试集重建规格](../规划文档/CryoAtom2测试集受体重建.md)的科学与逐 PDB 产物契约；本次用户授权将输入改为 calibration、资源改为两个单卡 A800 任务。不重跑 test_0 的 179 项，不生成 Find_1 特征或性能指标。当前入口与字段见[代码 README](../../测评数据代码/cryoatom2原始预测结构/README.md)。

## 输入来源与落盘位置

- 清单：`/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/split/pdb_split/calibration.json`，顶层 JSON 列表，100 个不同小写 PDB，原序保留。SHA256 为 `b14c9f4413092454c34f24239f0ccb1b2d506b5105fcff9dea3e6b7e87b0fe7a`。
- 图对应：`/storage/penghongen/AdaLigand/Ori_Data/raw/pair_list.jsonl`。原始图：同数据根 `raw/emdb_maps/emd_<编号>.map.gz`，正式运行只解压，不经过 AdaLigand 重采样。
- 完整序列：`/storage/penghongen/AdaLigand/held_out/sequence_catalog.jsonl`。此目录覆盖全体原始 PDB，calibration 100 项均覆盖；共 715 条蛋白质、38 条 RNA、10 条 DNA，其中 comparable=false 的短序列分别为 6、2、4 条，全部保留。不读取真实坐标。
- 实际逐 PDB 产物：`/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/cryoatom2_artifact/<pdb_id>/<run_stamp>/`。
- 日志、统计、输入来源、FASTA、实际子进程参数与 Slurm release/launch：`/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/运行日志与统计/`。本文件同步为该目录的 `任务日志.md`。
- 程序：本地 `测评数据代码/cryoatom2原始预测结构/`，服务器 `/home/penghongen/My_Project/AdaLigand/测评数据代码/cryoatom2原始预测结构/`。环境 `/home/penghongen/anaconda3/envs/CryoAtom2`，继续使用已完成 179 项生产运行的安装包与权重。

## 正式运行命令

在服务器项目根 `/home/penghongen/My_Project/AdaLigand` 分别执行以下命令一次。旧申请 379399_0、379401_1 已按用户最新要求取消。以下两个正式命令已于 2026-09-12 12:00:27 成功执行，分别产生 379402_0、379403_1；每个 50 项，不得重复提交。

```bash
bash 测评数据代码/cryoatom2原始预测结构/submit_calibration.sh 0 h200g4
bash 测评数据代码/cryoatom2原始预测结构/submit_calibration.sh 1 a100g2
```

该入口请求两个独立数组任务，各 1 张 A800、16 核 CPU，内存使用分区默认值、不传 --mem，`nvlink` 分区，两个必填参数分别指定分片编号与 QOS，分片 0 用 h200g4、分片 1 用 a100g2，仅 `--after_hold`，不设时间限制。`nvlinkg8`、`h200g4` 实为 QOS 名称；本次按 A800 硬件要求选择 `nvlink`。两个任务按原清单 `[0::2]`、`[1::2]` 各处理 50 项，彼此没有依赖。用户未授权释放本轮资源。

## 检查命令与已完成核验

本节所有命令仅用于核验，不是正式运行命令，也不计入正式 PDB 结果。

```bash
sinfo -o '%P %a %l %D %G'
scontrol show partition nvlink
sacctmgr show assoc where user=penghongen format=User,Account,Partition,QOS -P
```

2026-09-12 只读确认 `nvlink` 两节点各 8 张 A800，分区时间限制为 UNLIMITED，用户有 `nvlinkg8` QOS。逐项读取原始图的前 1024 字节：100 项均有唯一图对应、压缩文件存在、图头可读取；合计压缩图 14,309,646,262 字节。该检查没有完整解压校验 gzip 尾部；正式解压失败会记录为失败。全部序列非空且 length 与实际序列长度相等。输出根已存在但没有文件，未发现 calibration 运行中的作业。

## 代码与审查

开始写入前，AdaLigand 位于干净 `Learn/CUMULATIVE`，提交 `1fcd70063ce0652b406ed634cd9a0f68b3e32319` 是所有引用可达提交按提交者时间的唯一最新值。本次仅适配两处清单读取、新增两个薄 shell 入口并扩充既有分片测试，采用 dual-track-git-workflow 的明显小型修改例外，改动留在累计分支工作区，不自行提交。

两种清单格式直接读取用户给定文件，不生成替代清单；不新增 Python 函数、不改变模型参数、FASTA、图处理与 CIF 判定。主代理自查、独立审查及实际检查结果将在执行后追加。

## 等待与交接

提交和启动状态确认后，稳定排队、正常计算或长时间加载均每轮静默等待 60 或 90 分钟，由多次 `Start-Sleep -Seconds 300` 构成，不使用 heartbeat。只在提交、失败处置或全部验收等有意义事件更新 handoff；常规检查不另写交接。

## 计划与实现差异

- 中性差异：沿用既有科学契约，按本次用户授权切换 calibration 清单、两分片和 A800/16 CPU/仅 after_hold；资源名称经实际 Slurm 配置落实为 partition=nvlink；分片 0 使用 h200g4，分片 1 按用户对其他 QOS 的明确授权使用 a100g2。
- 有益或有害差异：目前未发现。
- 未完成范围：100 项预测、最终结构和来源验收、完成交接。

2026-09-12 主代理已完成两遍自查：第一遍按 predict.py、submit_calibration.sh、sh/predict_calibration.sh、tests/test_predict.py 的文件顺序检查修改函数职责、位置、调用、嵌套和 Docstring；只保留既有 run_shard/summarize 两个入口，没有新增包装函数。第二遍按中文注释 skill 和示例检查清单容器、原序切片、线程资源、输入输出与科学边界，将 list[str] 注释移到实际 pdb_ids 赋值前，修正旧注释中固定“三个分片”的表述。独立审查尚待完成。
## 提交前验证结论

本节记录入口参数化前的历史检查，包含旧双元素数组和旧脚本摘要；参数化后的当前证据见后面的 QOS 提交额度与入口修订。

2026-09-12 独立审查者完成两轮全面核查，均 APPROVED，明确批准 run_shard/summarize 布局及两处内联清单读取；无待修问题，后续不扩大审查。8 项契约测试通过，包括旧三分片 JSON object 与新两分片 JSON 列表的完整覆盖、保序、完整序列、原图字节、失败恢复与 CIF 复核。

以下为检查命令，未调用真实 sbatch：

```powershell
D:/Anaconda/python.exe -m pytest 测评数据代码/cryoatom2原始预测结构/tests/test_predict.py -q -p no:cacheprovider
```

```bash
bash -n 测评数据代码/cryoatom2原始预测结构/submit_calibration.sh
bash -n 测评数据代码/cryoatom2原始预测结构/sh/predict_calibration.sh
SBATCH_BIN="$check_dir/fake_sbatch" bash 测评数据代码/cryoatom2原始预测结构/submit_calibration.sh
```

`check_dir` 为本次由 mktemp 创建的 `/storage/penghongen/tmp/calibration-submit-check.*` 临时目录；fake_sbatch 只打印参数、不申请资源。实际参数检查结果保存在服务器日志根 `无卡提交参数检查.txt`，确认 `--gres=gpu:a800:1`、`--cpus-per-task=16`、`--array=0-1`、`--mem=96G`、pre_hold=0、after_hold=1，无时间参数。Python AST 按 3.9 语法解析通过。默认本机 Python 与捆绑 Python 缺少 pytest，最终使用既有 D:/Anaconda 环境，未安装或修改依赖；服务器 CryoAtom2 环境也未安装 pytest，因此不在生产环境运行测试。

生产文件已定向上传，不做整仓库同步，不删除远端内容。服务器日志根 `提交前代码摘要.json` 保存实际上传的三个生产文件 SHA256：predict.py=`4a5a1eed1c97bc3b51bf05d4a1ab6c128241a1437d0397ef0de78281213b2e30`；submit_calibration.sh=`5ebba2e2cd471d6be8d4a6b150ecab83f7b2baa775f86b4a385b5b340c8689f4`；sh/predict_calibration.sh=`18184a8feb4ebeb99c350bb90bd537b158c63d53b38b1dec74a5eb1f33175692`。没有提交独立 GPU 门控。

## QOS 提交额度与入口修订

2026-09-12 11:51 原双元素数组正式提交被 QOSGrpSubmitJobsLimit 拒绝，没有产生作业。此前一次 helper RetryCount=0 在本机参数检查阶段即被拒绝，没有连接服务器。只读查询发现 nvlinkg8 的全组 GrpSubmitJobs 上限为 4，已经占满；h200g4 上限为 2，只剩一个名额。h200g4 双元素数组的 sbatch --test-only 也被拒绝，单任务 test-only 则通过（其显示的模拟 Job 编号不是真实提交）。

为先让一个 50 项任务入队，正式入口改为两个必填参数 shard_index、qos，每次提交一个单元素数组任务；GPU/CPU/内存/分区/科学行为均不变。正式命令区已更新为每分片一个短命令。第二个是否允许用账户其他 QOS 已向用户询问，未得到答复前只使用已授权的 nvlinkg8/h200g4。此修订不串行依赖预测完成；第二个只等待调度额度。主代理已逐行复核两个必填参数传递，并按注释规则检查资源与分片语义；交独立审查者仅窄查此额度处置。

参数化后，独立窄查批准 shell 的单分片/QOS 参数传递；指出的当前 QOS 文档表述已修正。新的两个假 sbatch 检查保存为 `单分片提交参数检查.txt`，两个命令均通过单 A800、16 CPU、独立数组编号、仅 after_hold、无 time/dependency 的断言。`提交前输入核验.json` 保存 100 项原图大小/修改时间/图对应/序列类别数、完整原序两分片，以及原清单、图对应、完整序列目录三文件的 SHA256。`提交前代码摘要.json` 已刷新为实际参数化入口摘要，预测 Python 与执行 shell 未再修改。


## 第一个正式分片已提交

2026-09-12 11:56:01，正式命令 `bash 测评数据代码/cryoatom2原始预测结构/submit_calibration.sh 0 h200g4` 成功返回 Job 379399。Slurm 确认 ArrayTaskId=0、partition=nvlink、QOS=h200g4、gres/gpu:a800=1、NumCPUs=16、mem=96G、TimeLimit=UNLIMITED、Dependency=null、pre_hold=0、after_hold=1。11:56:20 状态 PENDING，原因 Priority；此时还未获得计算节点，release/launch 在真正执行前才创建。第一个分片不再重新提交。第二个分片尚未提交；a100g2 的单 A800/16 CPU/96G `sbatch --test-only` 已通过，但使用该 QOS 的用户答复仍待定，未将其作为默认授权。

参数化后的 submit_calibration.sh SHA256 为 `370915ae2ac454d518b7901af3cd143c1db1b28dd7cf4735d759dbe206032384`。预测 Python 和执行 shell 仍为 4a5a1eed...、18184a8f...。本轮提交交接见 `CLAUDE/memory/handoffs/2026-09-12-cryoatom2校准集首分片已提交.md`。

2026-09-12 用户明确允许第二个任务使用账户其他 QOS，例如 cpu96/h200g2。采用此前同硬件 test-only 已通过的 a100g2；正式命令区据此更新第二分片命令。a100g2 仅为调度 QOS，硬件仍由 --resource a800 指定，CPU、内存、分片与 after_hold 均不变。


## 用户要求取消旧申请并移除内存参数

2026-09-12 分片 1 曾以 `1 a100g2` 正式提交为 379401_1。随后用户报告自行 scancel 379399_[0]，要求不加 96G、使用默认内存并重新提交两个任务。只读核对 379399_0 已 CANCELLED by 1351，379401_1 仍 PENDING(Priority)，尚未开始预测。按此重提交授权，主代理执行 `scancel 379401_1` 撤销第二个旧申请。两个旧申请均不计作正式成功结构，不能再作为当前跟踪对象。

submit_calibration.sh 只删除 --mem 96G，其余单卡 A800、16 CPU、无时间限制、after_hold、分片编号及 QOS 保持不变。README 与当前正式命令说明同步更新；前文含 96G 的内容为撤销前历史。新申请不传 --mem，让 Slurm 按分区默认值处理。


## 当前两个正式任务与等待状态

2026-09-12 12:00:27，正式命令区的两个短命令分别成功返回 379402、379403。12:00:49 核对为 379402_0 / h200g4、379403_1 / a100g2，均 PENDING(Priority)。两个独立单元素数组的 ArrayTaskId 分别为 0、1，均 partition=nvlink、1 张 A800、16 CPU、TimeLimit=UNLIMITED、Dependency=null、pre_hold=0、after_hold=1。没有 --mem 参数，Slurm 显示 MinMemoryNode=0，并按分区默认记录 TRES mem=1000000M；没有把该默认值改写成 96G。尚未分配节点、尚未产生 release/launch。

`正式提交资源核验.txt` 保存两个 Job 的完整 scontrol 结果。最终无卡检查保存为 `默认内存提交参数检查.txt`，检查两个分片的单卡/16 CPU/after_hold，以及没有 mem/time/dependency 参数。最后 submit_calibration.sh SHA256=`3dd07f08ab9265a510873e0e1e56f95c1b5784809727a97e2ba5d6bb29f48d3a`，另两份生产文件不变；日志根提交前代码摘要.json 是当前完整摘要。移除内存参数后主代理已核对一行差异、参数检查和实际 Slurm 结果，不重复已有 Python 回归或扩大独立审查范围。

新有效交接为 `CLAUDE/memory/handoffs/2026-09-12-cryoatom2校准集双A800重新提交.md`，取代首分片交接中的待提交/旧 Job 状态。12:00 后开始按每轮 60 分钟、12 次 Start-Sleep -Seconds 300 的命令静默等待。goal 保持 active，尚无结构完成，不释放 after_hold。Git 仍为 Learn/CUMULATIVE 的原起点且按提交者时间唯一最新，本轮改动留工作区。
