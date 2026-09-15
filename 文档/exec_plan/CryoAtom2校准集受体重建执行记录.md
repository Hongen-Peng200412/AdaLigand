# CryoAtom2 calibration 100 项受体重建执行记录

2026-09-14 10:54，calibration 原清单全部 100 个 PDB 已完成预测与最终验收：100 成功、0 失败，200 份最终/raw CIF 均可解析、非空、坐标有限，来源、完整序列、命令、冻结代码与统计一致。按用户 2026-09-13 最新授权，两个 50 项科学分片均由 379402 在同一单 A800/16 CPU 资源上分两次执行；379402 已回到 after_hold，379403 仍保留排队申请和专属跳过预测判断。没有释放或重新提交这两项申请。本任务完成结构生产与验收，不包含 Find_1 下游性能评估。

## 当前有效 goal（2026-09-13 修订）

完成原 calibration.json 的全部 100 个 PDB 预测与最终验收。保留 379402 已验收的分片 0 产物，使用同一 Job 的现有单 A800、16 CPU 资源，在新的执行身份下显式运行 `[1::2]` 的剩余 50 项。保留服务器脚本内 Job 379403 的 exit 0 判断，使其排到资源后只进入 after_hold/try_lock 等待，不重复预测。两项资源均不释放、不重新提交。科学输入、官方参数、产物与日志位置、最终 100 项/200 CIF 验收要求保持不变；按每轮 60 或 90 分钟、每次 300 秒静默等待，完成全量验收、日志、交接与 Git 核验后才标记完成。

goal 工具不能修改既有目标正文；本节与用户最新授权构成执行方式修订，旧“两项各预测 50 项”的描述不再作为调度要求。最终验收与本节修订目标一致，完成状态见文末。

本任务复用[测试集重建规格](../规划文档/CryoAtom2测试集受体重建.md)的科学与逐 PDB 产物契约；本次用户授权将输入改为 calibration、资源改为两个单卡 A800 任务。不重跑 test_0 的 179 项，不生成 Find_1 特征或性能指标。当前入口与字段见[代码 README](../../测评数据代码/cryoatom2原始预测结构/README.md)。

## 输入来源与落盘位置

- 清单：`/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/split/pdb_split/calibration.json`，顶层 JSON 列表，100 个不同小写 PDB，原序保留。SHA256 为 `b14c9f4413092454c34f24239f0ccb1b2d506b5105fcff9dea3e6b7e87b0fe7a`。
- 图对应：`/storage/penghongen/AdaLigand/Ori_Data/raw/pair_list.jsonl`。原始图：同数据根 `raw/emdb_maps/emd_<编号>.map.gz`，正式运行只解压，不经过 AdaLigand 重采样。
- 完整序列：`/storage/penghongen/AdaLigand/held_out/sequence_catalog.jsonl`。此目录覆盖全体原始 PDB，calibration 100 项均覆盖；共 715 条蛋白质、38 条 RNA、10 条 DNA，其中 comparable=false 的短序列分别为 6、2、4 条，全部保留。不读取真实坐标。
- 实际逐 PDB 产物：`/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/cryoatom2_artifact/<pdb_id>/<run_stamp>/`。
- 日志、统计、输入来源、FASTA、实际子进程参数与 Slurm release/launch：`/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/运行日志与统计/`。本文件同步为该目录的 `任务日志.md`。
- 程序：本地 `测评数据代码/cryoatom2原始预测结构/`，服务器 `/home/penghongen/My_Project/AdaLigand/测评数据代码/cryoatom2原始预测结构/`。环境 `/home/penghongen/anaconda3/envs/CryoAtom2`，继续使用已完成 179 项生产运行的安装包与权重。

## 正式运行命令

### 初次提交（已执行，不再重复）

在服务器项目根 `/home/penghongen/My_Project/AdaLigand` 分别执行以下命令一次。旧申请 379399_0、379401_1 已按用户最新要求取消。以下两个正式命令已于 2026-09-12 12:00:27 成功执行，分别产生 379402_0、379403_1；每个 50 项，不得重复提交。

```bash
bash 测评数据代码/cryoatom2原始预测结构/submit_calibration.sh 0 h200g4
bash 测评数据代码/cryoatom2原始预测结构/submit_calibration.sh 1 a100g2
```

该入口请求两个独立数组任务，各 1 张 A800、16 核 CPU，内存使用分区默认值、不传 --mem，`nvlink` 分区，两个必填参数分别指定分片编号与 QOS，分片 0 用 h200g4、分片 1 用 a100g2，仅 `--after_hold`，不设时间限制。`nvlinkg8`、`h200g4` 实为 QOS 名称；本次按 A800 硬件要求选择 `nvlink`。两个任务按原清单 `[0::2]`、`[1::2]` 各处理 50 项，彼此没有依赖。用户未授权释放本轮资源。

### 复用 379402 执行原分片 1（本轮正式入口）

2026-09-13 用户明确授权把原分片 1 的剩余 50 项交给已经完成分片 0 的 379402 执行，并保留 379402、379403 两项资源。379403 的服务器任务脚本已由侧对话加入专属 exit 0 判断；本任务不覆盖该判断，不再等待它承担预测。

工作目录为 `/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/运行日志与统计/slurm/allocations`。在 379402 空闲且其动态命令已改为显式 `--shard-index 1 --shard-count 2` 后，以下正式启动命令已经执行一次，17:15 只读确认 try_lock 消失、after_lock 保留，控制器进入创建 release 的阶段；不得重复执行：

```bash
rm -- try_lock_379402
```

该命令仅触发已有控制器的下一次执行；不删除 `379402/after_lock_379402`，不重新申请 GPU。完整动态命令保存在日志根 `分片1复用动态命令.sh`，控制器还会在新的 launch 中保存相同内容。语法检查、状态检查和命令准备均不属于以上正式运行命令。

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

- 中性差异：沿用既有科学契约，输入改为 calibration 的 100 项列表，申请单 A800/16 CPU/after_hold，partition=nvlink，QOS 为 h200g4、a100g2。用户随后明确授权让 379402 通过两次执行分别完成两个 50 项科学分片，379403 排到资源后只跳过预测并等待；该变更已落盘并通过身份核对，不改变样本集合或科学参数。
- 有益或有害差异：未发现偏离最新用户授权的科学或产物行为。
- 未完成范围：本轮结构生产、100 项覆盖与来源/CIF 验收已完成。379403 尚未获得资源，保留其排队申请与专属退出判断；它不再承担预测，其排队不阻塞本轮结构验收。

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


## 分片 0 已实际启动

2026-09-12 21:34 核对 379402_0 已在 gnode09 运行约48分钟，379403_1 仍 PENDING(Resources)。分片0的执行名为 predict_calibration_job379402_20260912T204608_a1，release 为 `slurm/releases/AdaLigand_d044b39abc20/AdaLigand`，完整内容摘要 d044b39abc20c794dc87a188e12771ac321303811d943c6609e9d880571166b0。launch 位于 `slurm/launches/379402/predict_calibration_job379402_20260912T204608_a1/launch.json`，确认 a800/1 GPU/16 CPU/array_spec=0。服务器 release manifest 的 Git 字段为空，不能声称它保存了 Git 提交；三个生产文件 SHA256 均与提交前代码摘要一致。

运行身份 runs JSON 完整保存100项清单，shard_index=0、shard_count=2、CryoAtom2=2.1.1。节点实际进程读取冻结 release 的 predict.py，子进程使用原始图解压临时文件及日志目录的完整 FASTA。此时6bgi已成功（最终9602原子、1174残基；raw13029原子、1591残基），6rec正常计算，合计1成功/1运行/98未开始。输入源分别为emd_7095.map.gz、emd_4849.map.gz，序列entity分别1、18；进程与白名单线程环境另记服务器日志根分片0启动核验.json。此处是启动来源留证，不因首样本完成另写handoff。常规低频检查保存在日志根轮询记录.jsonl。

## 分片 0 完成与局部验收

2026-09-13 14:18 检查发现 379402_0 的 50 项全部 success，批处理输出“第 1 次执行成功”，提交系统已创建 `slurm/allocations/try_lock_379402`。`slurm/allocations/379402/after_lock_379402` 仍存在，Slurm RUNNING 此时表示保留资源，不再表示仍有预测计算。379403_1 仍 PENDING(Resources)，其 50 项尚未开始。没有释放、重启或借用已完成任务的资源。

14:24 的独立检查逐一重新解析分片 0 的 100 份最终/raw CIF，全部非空、坐标有限，原子和残基计数与逐 PDB 状态一致。50 项 latest.json 与对应 status.json 完全一致，退出码均为零、error 均为 null。三份源文件 SHA256 与提交前核验一致；逐 PDB 原始压缩图路径、大小和修改时间一致；全部实体、FASTA 序列及含链副本的标题与源目录一致；实际命令只使用解压图、完整 FASTA 和既定官方参数，解压临时图均已清理，产物目录未残留 .log。

本次是通过 SSH helper 执行环境 Python 的内联只读产物检查，仅新增 `运行日志与统计/分片0完成验收.json` 作为证据；不是正式预测命令。检查脚本初次把 FASTA 的解析 id 当成 sequence_id，遇到实际标题 `6BGI_1|Chains A, B` 停止；改为逐字核对完整 description 与链副本后通过，没有修改任何输入、生产代码或结构。

本次只验收 50 项，尚未生成表示全量完成的结论。新交接为 `CLAUDE/memory/handoffs/2026-09-13-cryoatom2校准集分片0验收完成.md`。等待分片 1 时继续每轮 60 或 90 分钟、每次 300 秒静默睡眠。当前本地 Learn/CUMULATIVE 已由其他工作推进至 `4f55abe988775a427839d52b33b94946628092e5`；本任务不改写历史，文档更新留在工作区，最终收口时再核验 Git。

## 用户授权复用 379402 执行剩余 50 项

2026-09-13 用户告知侧对话已在服务器 `sh/predict_calibration.sh` 的 set -euo pipefail 后加入 Job 379403 专属 exit 0 判断，要求本任务保留该判断，并让已完成分片 0 的 379402 执行原分片 1。主代理只读核对 379403 仍排队，50 项 `[1::2]` 全部尚无 latest.json，379402 的控制器在 gnode09 存活、无预测子进程、try_lock 与 after_lock 均存在。

本次不改生产 Python 或服务器任务脚本；只在 379402 的动态命令中直接调用新 release 的 predict.py，显式写入 shard_index=1、shard_count=2，线程上限保持 16，Slurm 实际数组身份仍为 0。一次任务草稿在本地 `tmp/cryoatom2-calibration-shard1-reuse/run_cmd_379402.sh`，运行证据在服务器日志根 `分片1复用动态命令.sh`。完整命令 SHA256 为 `deaf0eeb9d0b5afc9a5ed0930a2b1b47885d702ac271d3c79a16ca3477bfb1f6`。旧控制命令另存 `379402首次执行动态命令.sh`。

主代理先按职责与调用、再按注释与数据语义完成两遍自查；没有新增或修改 Python 函数。独立审查代理随后完成两轮全面核查并批准，未发现待修问题。Bash 语法检查通过，远端代码与输入检查记录在 `分片1复用前核验.json`。服务器 predict.py 摘要仍为 `4a5a1eed1c97bc3b51bf05d4a1ab6c128241a1437d0397ef0de78281213b2e30`；包含 379403 跳过判断的服务器任务脚本摘要为 `6714c320e17d0ed6d4d7598cde5b4c808079aada973a4c6ad9a4ab16a7472718`，本地对应文件仍未同步，禁止用本地旧文件覆盖它。

正式命令区的 rm 已执行成功。17:15 检查确认 try_lock 已移除、after_lock 未动；节点进程显示现有控制器正在执行 create_release.sh 和 sha256sum，为第二次执行冻结当前服务器项目。release 完成后会由控制器自动生成新的 launch 与 TASK_RUN_STAMP；不能把原分片 0 的第一次执行身份套到剩余 50 项。379403 排到资源后需要核实专属跳过分支成功进入等待，不能以其 Slurm RUNNING 状态推断它正在预测。

17:20 已核实第二次执行实际启动：run_stamp=`predict_calibration_job379402_20260913T171444_a2`，release=`slurm/releases/AdaLigand_f5c87447d578/AdaLigand`，完整内容摘要 `f5c87447d57824641e51b4a96bd2c2787d9203d75de475ff61301bd43a238eab`。launch 中 Slurm array_spec=0，与真实分配身份一致；runs 中科学分片 shard_index=1、shard_count=2，与显式命令一致。软件版本、配置、权重及三项输入路径与分片 0 的 runs 记录一致，冻结 predict.py 与上述原摘要一致，动态命令与审查稿摘要一致，冻结任务脚本保留 379403 专属判断。

节点检查确认父进程 35978 显式运行 shard-index 1，子进程 37090 正在重建首项 6dqn，读取原始 emd_7981 解压图与完整蛋白 FASTA。线程变量均为 16，GPU UUID 为 `GPU-adbf8fc8-5a4a-87e3-853b-c9cadcbdf74b`，此时使用显存 13362 MiB。证据为日志根 `分片1复用启动核验.json` 和 `分片1复用进程核验.json`。计算节点时钟比 master 约慢 3 分钟，执行名采用节点时间；本段观测时间采用 master，不用时间差判断重启。

## 最终检查命令（不属于正式预测命令）

2026-09-14 全部 100 项运行结束后，执行以下汇总检查。它使用冻结的生产程序重新解析全部成功结构，只写 summary.json，不重新预测。该命令已返回 pending=0、running=0、success=100、failed=0。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/penghongen/anaconda3/envs/CryoAtom2/bin/python '/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/运行日志与统计/slurm/releases/AdaLigand_f5c87447d578/AdaLigand/测评数据代码/cryoatom2原始预测结构/predict.py' summarize --split-file '/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/split/pdb_split/calibration.json' --output-root '/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration'
```

独立逐 PDB 来源与结构审计使用一次性脚本，源代码不进入生产入口，检查命令为：

```bash
PYTHONDONTWRITEBYTECODE=1 /home/penghongen/anaconda3/envs/CryoAtom2/bin/python -u /storage/penghongen/tmp/cryoatom2-calibration-final-audit/verify.py
```

脚本 SHA256 为 `47d7ed0a2f62a4a6b45ea1a4ceeeec069365e486c0ad035b085338fe25727051`，逐项核对原清单覆盖、两次执行身份、来源文件摘要、完整序列和链副本、原始图来源、实际命令、临时图清理、两份 CIF 的原子/残基与坐标、summary 一致性及资源保留状态，输出日志根 `最终来源与覆盖验收.json`。本地临时稿位于 `tmp/cryoatom2-calibration-final-audit/verify.py`。

另有无卡分支检查确认服务器脚本在 SLURM_JOB_ID=379403 时直接打印跳过说明、返回 0，证据为 `379403跳过分支检查.json`。它是检查进程，不是实际 Slurm 379403 的执行；截至此时该 Job 仍 PENDING(Resources)，没有声称它已实际获得 GPU 或进入 after_hold。`最终资源保留状态.json` 保存实时 scontrol 留证。379402 的第二次执行已成功并重新创建 try_lock，两项申请均未释放或重新提交。

## 全部 100 项最终验收结果

2026-09-14 10:44 只读发现最后一项 9yq0 已成功，379402 的 out 明确记录“第 2 次执行成功”，try_lock 已重新创建、after_lock 保留。10:54 完成生产汇总与独立全量审计，最终为 success=100、failed=0、running=0、pending=0；输出目录和日志目录的 PDB 集合均与原清单精确相等，没有遗漏或额外 PDB。每个 PDB 只有本次对应的一个执行目录，两个科学分片各 50 项、不重叠，全部 latest/status 退出码为零且无错误。

全部 200 份最终/raw CIF 独立重新解析通过，非空且坐标有限，原子/残基数与生产统计一致；审计保存每份 CIF 的路径、大小和 SHA256。三份源文件摘要与提交前一致，100 项原始图的路径、大小和修改时间一致；完整序列目录中的蛋白质 715 条、RNA 38 条、DNA 10 条全部逐字保留，包含 comparable=false 的 6/2/4 条短序列。实际 FASTA 标题和链副本、忽略字符记录与输入实体一致，所有命令只使用规定的解压图和完整序列，临时解压目录均已删除，实际产物目录未残留 .log。

两个 runs 的科学分片为 0、1，job_id 均为 379402，分别对应第一次和第二次执行的唯一 run_stamp。冻结代码、launch 动态命令、官方配置、三轮预测和 filter_threshold=50、全部权重位置与大小核对通过，软件/科学参数与第一次执行一致。没有通过真实受体坐标衡量结构精度；本次验收证明结构文件和来源契约正确，不代表 Find_1 性能结果。

权威结果位于 `/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/calibration/运行日志与统计/summary.json` 和同目录 `最终来源与覆盖验收.json`。实际逐 PDB 结构位于同级 `cryoatom2_artifact/<pdb_id>/<run_stamp>/`，名称分别为 `<run_stamp>.cif` 与 `<run_stamp>_raw.cif`。

资源保留状态：379402_0 仍在 gnode09、单 A800/16 CPU、TimeLimit=UNLIMITED，当前是预测结束后的 after_hold；379403_1 仍 PENDING(Resources)，尚未实际执行任务脚本。服务器专属 379403 exit 0 判断与已核验摘要一致，无卡分支检查返回 0；本地任务脚本尚未同步该判断，禁止覆盖服务器版本。没有删除任何 after_lock，也没有取消或新增任务。后续使用或释放资源由用户另行授权。

最终 Git 核验：Learn/CUMULATIVE 为 `4f55abe988775a427839d52b33b94946628092e5`，仍是全部引用及登记工作树可达提交按提交者时间的唯一最新值。本任务没有改写 Git 历史；当前运行记录、映射和记忆更新留在累计分支工作区。生产 Python 与提交入口摘要未变化，已有 8 项回归、实现的两轮独立审查及资源复用的两轮独立审查均通过，后续没有需要重新测试的生产代码变更。最终交接见 `CLAUDE/memory/handoffs/2026-09-14-cryoatom2校准集100项验收完成.md`。
