# CryoAtom2 测试集受体重建执行记录

依据：[CryoAtom2 测试集受体重建规划](../规划文档/CryoAtom2测试集受体重建.md)。本记录覆盖输入核对、代码实现与审查、正式资源提交、179 个 PDB 重建验收；不覆盖 Find_1 后续评估。

## 当前状态

2026-09-12：全部 179 个 PDB 预测成功并通过最终验收，失败、运行中和未开始均为 0；179 份最终 CIF 与 179 份 raw CIF 均重新解析通过，原子非空、坐标有限。三个分片覆盖 60、60、59 项，无遗漏或重复，全部逐 PDB 退出码为 0。来源与覆盖报告为服务器日志根的 `最终来源与覆盖验收.json`，最终计数为同目录 `summary.json`。结构精度及 Find_1 下游对照未纳入本任务。

资源按用户最后指令处理：分片 2（实际 Job 374480）于 01:18:11 解除 after_lock，Slurm 确认 01:18:20 COMPLETED 0:0。分片 0（377521）和分片 1（377793）的原预测进程此前均已核实退出，作业已交其他 AI agent 接管；本任务未释放、不再追踪或操作这两个作业。最终交接见 `CLAUDE/memory/handoffs/2026-09-12-cryoatom2测试集179项验收完成.md`。

## 来源与落盘位置

| 内容 | 位置或已核实事实 |
| --- | --- |
| 测试集 | `/storage/penghongen/AdaLigand/held_out/split/held_out_06_chain/test_0.json`，179 个不同 PDB |
| PDB 与图对应关系 | `/storage/penghongen/AdaLigand/Ori_Data/raw/pair_list.jsonl`，179 个 PDB 各唯一对应一张原始图 |
| 原始密度图 | `/storage/penghongen/AdaLigand/Ori_Data/raw/emdb_maps/emd_<编号>.map.gz`，179 张存在；最大图为 11jb 的 800³ |
| 序列 | `/storage/penghongen/AdaLigand/held_out/sequence_catalog.jsonl`，385 个蛋白质、52 个 RNA、60 个 DNA entity |
| 组成 | 122 个纯蛋白质 PDB、48 个蛋白质与核酸复合物、9 个纯 RNA PDB |
| 短序列 | 3 个蛋白质、4 个 RNA、7 个 DNA entity 的 comparable=false；本任务保留 |
| 软件 | `/home/penghongen/anaconda3/envs/CryoAtom2`，CryoAtom2 2.1.1、PyTorch 2.1.0/CUDA 11.8 |
| 主权重 | 环境 site-packages/CryoAtom2/checkpoint 下 CryoNet.pth、CryoNet_no_seq.pth、RUNet.pth；文件存在 |
| RNA-FM | `/home/penghongen/.cache/torch/hub/checkpoints/RNA-FM_pretrained.pth`，1194424423 字节 |
| 逐 PDB 产物 | `/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/cryoatom2_artifact` |
| 运行记录和统计 | `/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/运行日志与统计` |
| 本地代码 | `测评数据代码/cryoatom2原始预测结构/` |

## 已确定的实验选择

全部蛋白质、RNA、DNA 都用 CryoAtom2 重建。主实验用默认最终 CIF，同时保留 raw CIF。序列中的未知字符不自行替换，接受官方读取器的处理并记录。原始结构与配体坐标不进入预测输入。日志和统计不得放入 `cryoatom2_artifact`。

## Git 与审查

开工基点为 `854e4ebcf8f467c98c5ab7315b50c3b346a444e7`。只读检查所有本地、远端跟踪分支及登记工作树后，确认该提交是按提交者时间形成的唯一最新提交，`Learn/CUMULATIVE` 指向它，工作区干净。实现分支为 `codex/cryoatom2-test0-chain06`。

主代理第一遍自查已按 `predict.py → submit.sh → sh/predict.sh → tests/test_predict.py` 检查函数职责、顺序、调用、嵌套与 Docstring：生产模块只有两个复用内部工具和两个独立入口，没有嵌套函数；修正 Python 3.9 注解兼容与已成功但结构损坏时的重试行为。Windows 测试中曾有一处默认 GBK 解码失败，已将测试读取统一为 UTF-8。

第二遍自查已按 code-comment-style-cn 示例逐项核对：补齐运行身份、完整 entity、状态 JSON 的嵌套字段；注明原子 XYZ/Å、分片列表、类别 FASTA、未知字符位置、命令参数边界和状态转换。正式代码不计算哈希；暂未加入未使用入口或参数回退。

第一轮三方向独立审查已完成。布局审查代理批准 `_write_json`、`_inspect_cif`、`run_shard`、`summarize`，其中两个独立入口的单次 CLI 调用例外已按用户委托批准。逻辑审查独立运行 7 项测试通过，指出官方失败时残留的 `see_alpha_output/temp.log` 必须归档；已在每次尝试结束时将残留 `.log` 迁入 `official_logs/`，并加失败情形断言。注释审查提出的 latest 状态表述、嵌套字段逐项说明和完整状态示例也已修正。

第二轮三个方向的全面审查均通过，逻辑代理再次独立运行 7 项测试通过。README 官方中间目录编号已按安装源码的 i+1 校正为 1、2、3，逻辑审查代理窄口径复核关闭。后续只对提出的问题进行窄口径复核。第二轮审查对应实现提交 `056d48055ea24e69ca7aa4ac0fcca1bf21c0d3a5`。

首次实现收口端点为 `54201da290e739f57b6eb8a2f53e2821d0585e2c`，学习端点为 `34a64815340246a0ef17da6ccb6130d158f99e14`，共同基点不变。学习历史依次为全部 Markdown 契约、预测与汇总实现、两个 Shell 入口、全部测试；没有合并提交。布局审查代理已独立完成端点窄口径验收，确认通过。`git diff --exit-code codex/cryoatom2-test0-chain06 Learn/cryoatom2-test0-chain06` 无差异，两端树均为 `973f03d9b996f62e283e60257d5081d61abc80ce`，两端分别运行相同 7 项测试并通过。`Learn/CUMULATIVE` 已通过快进到达学习端点，所有分支可达提交中按提交者时间唯一最新。后续运行事件属于纯记录更新，按项目对文档与明显小型修改的例外留在累计分支工作区，不反复重建稳定代码历史。

## 正式运行命令

实际工作目录：/home/penghongen/My_Project/AdaLigand。唯一正式提交命令已执行一次，Slurm 于 2026-09-08 17:07:48 接收并返回数组编号 `374480`；不重复提交。此入口不调用任何测试或门控。

```bash
bash 测评数据代码/cryoatom2原始预测结构/submit.sh
```

## 测试与门控命令

本节仅保存测试和只读检查，不是正式运行入口。

- 开工 Git 检查：`git status --short --branch`、`git worktree list --porcelain`、`git for-each-ref --sort=-committerdate`、`git log --all --format='%ct %H'`。
- 服务器只读验收：测试清单、序列目录、原始图头、安装模块、权重存在性、CLI 帮助、`pip check` 与 GPU 可见性均已检查；真实模型加载随后由独立 GPU 门控 374469 验证通过，见启动事件。
- 本地契约测试：`D:/Anaconda/python.exe -m pytest 测评数据代码/cryoatom2原始预测结构/tests/test_predict.py -q -p no:cacheprovider`；第一轮修正测试 UTF-8 读取后为 6 passed，随后增加混合复合物三类序列覆盖。
- Bash 语法检查：对 `submit.sh` 与 `sh/predict.sh` 分别执行 `bash -n`，均通过。
- 提交参数检查：临时假 sbatch 捕获实际参数，确认 `--gres=gpu:a100:1`、`--cpus-per-task=8`、`--array=0-2`、`--after_hold 1`，没有 `--time`，不申请资源；本地首次检查因 MSYS2 的 PATH 缺 dirname 而失败，给测试进程前置 MSYS2 bin 后通过。
- 独立 GPU 门控程序为 `tests/check_runtime.py`，只读取三份主模型权重并执行 ESM2、RNA-FM 的短序列前向，不生成正式 PDB 结构；实际门控提交命令将在执行时单列。

### 独立 GPU 门控（不是正式预测）

实际提交作业为 `374469`，仅申请 1 张 A100、8 核 CPU、96 GiB 内存，门控结束即释放，不使用 after_hold，不生成测试集 PDB 结构。以下为实际执行的完整门控命令：

```bash
set -euo pipefail
log_root=/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/运行日志与统计/门控
mkdir -p "$log_root" /storage/penghongen/tmp/cryoatom2/runtime_gate
cd "$log_root"
sbatch --job-name=cryoatom2_gate --partition=a100 --qos=a100g2 --gres=gpu:a100:1 --cpus-per-task=8 --mem=96G --output="$log_root/%j.out" --error="$log_root/%j.err" --wrap='export PATH=/home/penghongen/anaconda3/envs/CryoAtom2/bin:$PATH PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8 OPENBLAS_NUM_THREADS=8 TMPDIR=/storage/penghongen/tmp/cryoatom2/runtime_gate; exec /home/penghongen/anaconda3/envs/CryoAtom2/bin/python -u /home/penghongen/My_Project/AdaLigand/测评数据代码/cryoatom2原始预测结构/tests/check_runtime.py'
```

## 事件记录

### 已执行的锁操作（不是正式提交命令）

门控通过后，分别核实 Slurm 数组身份、单卡资源、计算节点进程、动态命令和 pre_lock 归属，再执行下列精确删除。after_lock 保留。动态命令均为执行该次冻结副本中的 `测评数据代码/cryoatom2原始预测结构/sh/predict.sh`，不包含测试或门控。

```bash
# 2026-09-11 01:19:12，374480_0 对应实际 Job 377521，gnode08，GPU IDX:5。
rm -- /storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/运行日志与统计/slurm/allocations/pre_lock_377521
# 2026-09-11 01:20:55，374480_1 对应实际 Job 377793，gnode05，GPU IDX:5。
rm -- /storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/运行日志与统计/slurm/allocations/pre_lock_377793
# 2026-09-11 02:59:25，374480_2 对应实际 Job 374480，gnode07，GPU IDX:4。
rm -- /storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/运行日志与统计/slurm/allocations/pre_lock_374480
```

### 统计与结构复核命令（不是正式提交命令）

2026-09-11 03:00 执行以下独立统计命令，覆盖完整 179 项，并重新解析已有成功项的最终和 raw CIF、检查原子非空及坐标有限。输出位于 `运行日志与统计/summary.json`。本次结果为成功 6、运行中 2、尚未开始 171、失败 0；这是运行中快照，后续必须按最新产物更新。

```bash
PYTHONDONTWRITEBYTECODE=1 /home/penghongen/anaconda3/envs/CryoAtom2/bin/python /storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/运行日志与统计/slurm/releases/AdaLigand_9a152cd14d18/AdaLigand/测评数据代码/cryoatom2原始预测结构/predict.py summarize --split-file /storage/penghongen/AdaLigand/held_out/split/held_out_06_chain/test_0.json --output-root /storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06
```

### 按时间记录

本次三项实际使用同一冻结副本：`运行日志与统计/slurm/releases/AdaLigand_9a152cd14d18/AdaLigand`，完整内容 SHA256 为 `9a152cd14d1810bcc6c8aa1c12f4b933ef92ac6d2bf08d959597fed51b0782ad`。服务器项目没有可记录的 Git 身份，因此 release manifest 的 Git 字段为空；本地双线提交及预测文件一致性证据见本文 Git 节和启动事件，不将空字段误报为已记录 Git 提交。

| 实际 Job | launch 与运行名 | 启动记录 | 分片与首次 PDB |
| --- | --- | --- | --- |
| 377521 | predict_job377521_20260911T011918_a1 | `运行日志与统计/slurm/launches/377521/predict_job377521_20260911T011918_a1/launch.json` | 0/3，60 项，9ter |
| 377793 | predict_job377793_20260911T011942_a1 | `运行日志与统计/slurm/launches/377793/predict_job377793_20260911T011942_a1/launch.json` | 1/3，60 项，30yu |
| 374480 | predict_job374480_20260911T030130_a1 | `运行日志与统计/slurm/launches/374480/predict_job374480_20260911T030130_a1/launch.json` | 2/3，59 项，9lfa |

运行名、launch 时间和逐 PDB 时间戳按计算节点原值保留。已观察到计算节点时钟与 master 存在数分钟差异；本记录的锁操作回执使用 master 时间，不据跨节点绝对时间戳计算等待时长或推断操作先后。

- 2026-09-08：接受 3 个单卡 A100 数组任务、每个 8 核 CPU、不传时间限制、运行后保留资源的授权。启动实现；handoff 只在正式提交与最终完成等有意义事件更新。
- 2026-09-08：服务器确认 a100 分区 `MaxTime=UNLIMITED`，a100g2 QOS 每用户最多 16 张 A100，本次 3 张资源请求可表达；缓存中 ESM2 主权重 2604537549 字节、回归权重 3687 字节、RNA-FM 1194424423 字节。官方推理依赖 `.map/.mrc` 后缀，已采用仅解压的临时 `.map` 输入。
- 2026-09-08：CryoAtom 源码提交为 `856e250df7b784b854b892f1b619d32d51188cef`；已装源码确认 getp 的 temp.log 和默认配置读取语义。A100 节点均处于共享状态，每节点报告 740000 MiB 内存，正式入口选择每任务 `--mem 96G` 以避免默认整节点内存阻塞；总请求仍为 3 张 A100、24 核 CPU、不传时间限制。
- 2026-09-08：首次编码传输命令被自动审批阻止，未执行；随后用严格主机密钥校验的 rsync 无删除传输，仅上传本任务目录到 `/home/penghongen/My_Project/AdaLigand/测评数据代码/cryoatom2原始预测结构/`，成功。
- 2026-09-08：门控 374469 最初为 PENDING(Priority)，调度预估 9 月 13 日开始。针对短时门控执行 `scontrol update JobId=374469 TimeLimit=00:20:00`，缩短其资源预约以允许回填调度；此命令只调整门控，不是正式预测命令，正式 3 卡入口继续不传时间限制。
- 2026-09-08：服务器 Python 3.9 执行预测入口 `--help` 通过，Bash 语法通过；服务器三个生产脚本的 SHA256 与本地上传前值一致。无卡提交参数检查再次通过，确认每卡 96G、8 CPU、3 个单卡分片、after_hold=1，正式提交没有 `--time`。这些均为门控证据，尚不代表真实整图预测成功。

- 2026-09-08：用户指定稳定排队、正常计算或长时间加载时，每轮等待 60 或 90 分钟，以多次 300 秒睡眠组成；期间不发消息，不设置 heartbeat，不因稳定排队停止目标。本次采用每轮 12 次 300 秒睡眠，终端会话以不超过 60 秒的非终止观察接收新消息。正式入口已再次核实为 --array 0-2、--gpus 1、--cpus 8：三个独立任务分别处理 60、60、59 项，无分片间依赖。

- 2026-09-08：用户明确追加授权：不等待独立门控完成，立即额外提交 3 个正式单卡 A100 任务，同时启用 pre_hold 与 after_hold，提前进入队列。submit.sh 只新增 pre_hold 开关，无卡参数检查已确认两个 hold=1，GPU/CPU/内存/数组/无时间限制均保持。正式命令已发送，正在等待 Slurm 返回编号，不重复提交。获得资源后先保留 pre_lock，放行与门控验收作为后续独立动作。

- 2026-09-08：正式提交成功：`Submitted batch job 374480`。提交回执为 full 模式、任务根 `/home/penghongen/My_Project/AdaLigand`、任务 `测评数据代码/cryoatom2原始预测结构/sh/predict.sh`、每任务 A100×1/CPU×8、pre_hold=1/after_hold=1。此数组与独立门控 374469 无 Slurm 依赖；先申请资源，再由 pre_lock 控制第一次预测。此次新增 pre_hold 及注释属于项目允许的小型修改，暂留累计分支工作区，未修改 Python 科学行为。

- 2026-09-08 17:10：Slurm 独立核实 `374480_0`、`374480_1`、`374480_2` 均为 PENDING(Priority)，各 `gres:gpu:a100:1`、8 CPU、96G、`TimeLimit=UNLIMITED`；保存的 Command 同时含 `--pre_hold 1 --after_hold 1`，`Dependency=(null)`。当前预计 9 月 13 日 13:31:48 开始，时间可随调度变化。排队期间尚无 allocation/release/launch，待获得资源后核对。

- 2026-09-08 18:16：一轮 60 分钟睡眠后，门控 374469 与正式 374480_0/1/2 均仍 PENDING(Priority)，无节点分配。随后只将用户追加的 pre_hold 开关及对应注释补入两条历史：实现端点 `495a4de2cc0a3c528c5a397d3d25d38bdc49c35b`，学习/累计端点 `cfc9ef56d5e4900baec1b36459ddf49740f41cb9`。两端完整树均 `7df8644353b68f3b99f91d33fa7fbe69a2abef4a`，端点 diff 为空；从两端各提取正式提交链到临时目录，独立无卡参数检查均通过。累计已快进且再次为按提交者时间唯一最新提交；运行记录、README、规划及外置记忆等文字修改继续保留在工作区，没有混入代码提交。

- 2026-09-09 07:53：按每轮 90 分钟、18 次 300 秒睡眠持续等待并核查。自昨晚至今晨各次 Slurm 检查均确认门控 374469 与正式 374480_0/1/2 为 PENDING(Priority)，尚无节点分配；门控仍为 20 分钟，正式各单卡 A100/8 CPU/无时间限制。现有排队作业继续保留，尚未进入真实预测。此次合并记录夜间等待情况，不新增 handoff。

- 2026-09-09 18:28：继续按每轮 90 分钟、18 次 300 秒睡眠等待。15:48、16:58 和 18:28 的 Slurm 查询均确认门控 374469 与正式 374480_0/1/2 为 PENDING(Priority)，没有节点分配；门控仍为 20 分钟，三个正式任务各 A100×1、8 CPU、无时间限制。尚无门控通过证据或可放行的正式 allocation。未重复提交、未操作任何锁；本条合并记录排队检查，不新增 handoff。

- 2026-09-10 09:31：昨晚及今晨 00:48、02:19、03:49 的检查均为四个作业 PENDING(Priority)。03:49 后启动的本地分段睡眠提前退出，退出码为 1073807364，未收到本轮睡眠完成标记；不据此判断服务器作业结束。09:31 重新查询 Slurm，确认门控 374469 和正式 374480_0/1/2 仍 PENDING(Priority)，没有节点分配，资源请求及时间限制不变。继续等待原有作业，未重复提交或放行锁；不为普通排队检查新增 handoff。

- 2026-09-10 22:15：11:02、12:33、14:04、15:35、17:05 的查询均为四个作业 PENDING(Priority)。17:05 后等待期间观察工具连接失效，重新观察同一本地睡眠会话 25708，确认它仍存活并最终收到完成标记，没有另起重复睡眠或服务器作业。22:15 查询确认门控 374469 为 PENDING(Resources)，正式 374480_0/1/2 仍为 PENDING(Priority)，均未分配节点；尚无门控通过证据。继续保留原有队列与资源请求，不新增 handoff。

- 2026-09-11 01:17—01:21：门控 374469 在 gnode08 执行 38 秒并以 0:0 完成；日志含三份 CHECKPOINT_READ_OK、ESM2 与 RNA-FM 的 LANGUAGE_FORWARD_OK，以及 RUNTIME_GATE_PASSED。此证据不代表整图预测已通过。正式 374480_0 实际 Job 为 377521，于 9 月 10 日 23:52:41 获得 gnode08 资源；374480_1 实际 Job 为 377793，于 9 月 11 日 01:18:55 获得 gnode05 资源。分别核实 GPU×1/CPU×8/96G/UNLIMITED、数组编号、项目根、动态命令、pre_lock 和 after_lock 及本 Job 进程后放行；精确命令与时间单列于锁操作节。服务器 predict.py 与本地审查版本统一 LF 后 SHA256 均为 8c18b2a0792ae4b8fafabbacbac82f19eb9f9a83f262b0dda8d82832c0dbc217，原始字节差异仅来自本地 CRLF。Job377521 已观察到 create_release.sh 进程；01:21 两项均尚无 launch.json，第三分片仍 PENDING(Resources)。此次为正式任务放行里程碑，更新 handoff 和项目记忆。

- 2026-09-11 01:24—01:25：两项 launch、runs 来源清单和首次 PDB 的 inputs/command/status 均已产生。377521 的 9ter 使用原始 emd_55834.map.gz，仅解压为临时 map，输入蛋白质和 DNA FASTA；377793 的 30yu 使用原始 emd_58151.map.gz，仅解压后输入蛋白质 FASTA。各自 CryoAtom2 子进程 PID46554、249342 出现在对应 Job 的 scontrol listpids 与 GPU 进程列表中，显存分别约 13.0、10.1 GiB；已进入官方结构构建和密度图预测步骤，stderr 为空。冻结副本内 predict.py 的 SHA256 与上述已审查版本一致。当前两项为运行中证据，尚无最终成功验收；第三分片仍 PENDING(Resources)。

- 2026-09-11 02:58—03:00：第三项 374480_2 的实际 Job ID 为 374480，于 02:22:21 获得 gnode07 资源。核实数组编号 2、GPU IDX:4、8 CPU/96G/UNLIMITED、项目根、动态命令、预测文件一致性及对应计算节点进程后，于 master 时间 02:59:25 删除其 pre_lock，after_lock 保留。前两项已成功完成 9ter、9k9g、9q33、23xk、9r7l、9wfu，独立统计命令重新解析这 6 项的两种 CIF 并通过；30yu、9nc9 正在计算。03:00 第三项仍在准备冻结副本，尚无 launch，不能将该项的 Slurm RUNNING 状态当作预测已启动。

- 2026-09-11 03:01—03:02：第三项已复用同一 release，并生成 launch `predict_job374480_20260911T030130_a1`。计算节点 scontrol listpids 与 ps 确认分片 2 的 predict.py 进程 PID32340；runs 清单确认 59 个 PDB，首次 9lfa 的输入、命令与状态已落盘，读取原始 emd_63043.map.gz，仅解压为临时 map，输入完整蛋白质 FASTA。三个正式分片均已进入实际执行，保留全部 after_lock。更新启动里程碑 handoff 与项目记忆，随后按约定静默等待。

- 2026-09-11 04:35：90 分钟静默等待后，三个 Slurm 元素均 RUNNING，各仅保留 after_lock。逐 PDB 最新状态统计为成功 26、运行中 3、尚未开始 150、失败 0，合计 179；当前计算 9r3d、9dei、9qgy，日志显示正常推进，三项当前 stderr 为空。该计数来自各次运行内的结构校验状态，全集独立复核仍待最终验收；03:00 的 summary.json 保留为此前快照。普通进度不更新 handoff。

- 2026-09-11 07:37：继续按 90 分钟分段睡眠观察。06:06 的逐 PDB 状态为成功 54、运行中 3、未开始 122、失败 0；07:37 为成功 74、运行中 3、未开始 102、失败 0。三个作业均 RUNNING，仅保留 after_lock；当前处理 9wmh、9hyu、11jb，日志正常推进，当前 stderr 为空。11jb 为已知最大原始图，对应步骤工作量较大，尚无失败证据；继续原参数运行，不缩小输入或跳过样本。普通进度不更新 handoff。

- 2026-09-11 10:40：08:37 恢复目标时读取执行记录和启动 handoff，并核查已有作业；当时成功 89、运行中 3、未开始 87、失败 0。确认此前本地睡眠会话仍存活后继续等待，同一会话正常结束；09:09 为成功 92、运行中 3、未开始 84、失败 0。再经过完整 90 分钟分段睡眠，10:40 为成功 106、运行中 3、未开始 70、失败 0，合计 179。三个 Slurm 元素均 RUNNING，各仅保留 after_lock；当前处理 9lqj、9vap、11jb，stderr 为空。11jb 当前步骤推进至 220619/222288，尚未完成整次预测。上述成功计数来自逐 PDB 运行内校验，最终独立全集复核仍未完成，summary.json 仍为 03:00 快照。未重复提交、未修改正式代码或科学参数，不为普通进度新增 handoff。

- 2026-09-11 14:19—14:24：12:11 检查为成功 121、运行中 3、未开始 55、失败 0。此后分段睡眠观察连接失效，重新观察同一终端会话 51422，确认仍存活并收到完成标记；没有重启睡眠或服务器作业。14:19 为成功 133、运行中 2、未开始 44、失败 0。分片 0 的 allocation/out 报告第 1 次执行成功，已建立 try_lock_377521；gnode08 的 scontrol listpids 和 ps 确认该 Job 仅剩资源保留进程，没有预测 Python 进程。将 runs 清单与原始 split 比较，分片 0 恰好覆盖 split[0::3] 的 60 个 PDB，均为同一运行名、returncode=0、无 error、有结束时间，latest.json 与本次 status.json 一致，无遗漏或额外 PDB。另两分片分别为成功 44/60 和 29/59，正在处理 9u7j、11jb，日志继续推进、stderr 为空。随后再次执行本文“统计与结构复核命令”中的同一 summarize 命令，进程正常退出 0，重新解析 133 项的最终和 raw CIF，通过非空与有限坐标检查；summary.json 更新为成功 133、运行中 2、未开始 44、失败 0。此为运行中快照，仍需等待其余样本并完成最终来源、产物和全集验收。三个 after_lock 和分片 0 的 try_lock 均保留。

- 2026-09-11 17:34—17:35：16:03 从服务器核实成功 147、运行中 2、未开始 30、失败 0；此前本地睡眠会话 30790 已不存在，因此重新核查原有服务器作业后再等待，未因观察失效重提任务。用户随后先要求分片 1、2 完成后释放资源，继而明确修改为三个作业运行及验收完成后均暂不释放；以最后修订为准，期间没有解除任何 after_lock。分片 0 的作业控制交给另一位 AI agent，本任务停止主动追踪它的作业状态，已有产物仍纳入全集验收。17:34 仅查询分片 1、2 的作业状态和控制记录，总计成功 149、运行中 1、未开始 29、失败 0。分片 1 已报告第 1 次执行成功并创建 try_lock_377793；gnode05 的 scontrol listpids 和 ps 确认没有本次预测 Python 进程。runs 与原始 split 核对通过，split[1::3] 的 60 项全部为同一运行名、returncode=0、无 error、有结束时间，latest.json 与 status.json 一致，无遗漏或额外 PDB。分片 2 的 11jb 继续推进至当前步骤 203985/204303，stderr 为空。summary.json 保留 14:24 的独立结构复核快照，新增成功项待最终统一复核。

- 2026-09-11 19:06：用户进一步授权分片 2 完成后释放 after_lock，并将分片 1 的作业交由其他 AI agent 接管、不再主动追踪；分片 0 的接管安排保持。本次仅查询 374480_2 的 Slurm 状态与控制记录；它仍 RUNNING，after_lock 存在，尚无 try_lock。全部 PDB 产物状态计数为成功 155、运行中 1、未开始 23、失败 0，当前 30ga 日志持续推进、stderr 为空；11jb 已结束，分片 2 已继续处理后面的样本。未操作其他 agent 接管的作业，未释放任何锁。最终全集结构与来源核查仍待全部运行结束。

- 2026-09-11 22:08：仅继续追踪分片 2。20:37 为成功 162、运行中 1、未开始 16、失败 0；22:08 为成功 174、运行中 1、未开始 4、失败 0。当前 9ylu 日志持续推进、stderr 为空，374480_2 仍 RUNNING，after_lock 存在、尚无 try_lock。分片 0、1 的作业不再查询或操作，其既有产物仍纳入全部 179 项最终验收。后续采用一轮 60 分钟分段睡眠，结束后核查剩余预测与分片 2 的释放条件。

## 最终验收与资源处理

2026-09-12 01:11 核查时，最后一项 9ygu 已成功，分片 2 报告第 1 次执行成功。其原预测进程在 gnode07 的 scontrol listpids 与 ps 中已不存在。23:09 的本地睡眠观察连接曾失效，但 Windows 进程 27612 仍执行原有 12 次 300 秒睡眠；随后只等待该进程结束，没有再启动重复睡眠或正式作业。此后 00:11 的 9ygu 日志正常推进至后续轮次，01:11 全部结束。

### 验收证据

再次独立执行本文“统计与结构复核命令”中的 summarize，命令正常退出 0，返回 `pending=0, running=0, success=179, failed=0`。该命令逐项重新读取全部 358 份 CIF，检查可解析、原子非空和坐标有限，写出最终 `运行日志与统计/summary.json`。这只是文件与数值有效性验收，不是结构精度评估。

另用独立 Python 读取核对输入和运行证据，生成 `运行日志与统计/最终来源与覆盖验收.json`（178451 字节）。该报告的 `verified_at_unix` 为核查时间；`checks` 保存各检查的通过数量；`source_sha256` 保存三个输入清单当前摘要；`production_sha256` 保存三个实际冻结生产脚本摘要；`pdbs` 按原始 split 顺序保存 179 项身份、作业、运行名、源图、序列数量、忽略字符数量、耗时、CIF 路径和运行内原子/残基统计。报告中的原子/残基统计取自逐项 status，全集 CIF 的再次解析由独立 summarize 完成。

| 核查范围 | 实际证据与结果 |
| --- | --- |
| 全集与分片 | split 的 179 项唯一，三份 runs 均保存同一清单；分片分别恰好覆盖 split[0::3]、split[1::3]、split[2::3]，数量 60/60/59；实际尝试目录与所分配 PDB 集合一致 |
| 逐项结束记录 | 179 项均 success、returncode=0、error=null，有有效结束时间；latest.json 与对应 status.json 完全相同 |
| 原始图 | 每个 PDB 恰好对应 pair_list 的一张原始 map.gz；inputs 的源路径、字节数与纳秒修改时间均匹配当前文件；command 使用本 Job 临时目录中的对应解压 map，179 个临时 map 均已清理 |
| 完整序列 | inputs 的全部 entity 与 sequence_catalog 逐项完全一致；实际 FASTA 的 header、链副本列表和完整序列逐字匹配；385 蛋白质、52 RNA、60 DNA entity 均保留，其中短序列分别为 3/4/7 |
| 字符与命令 | 按官方字符表逐个核对忽略字符位置；179 份 command 参数列表精确匹配固定 CryoAtom2 build、原始解压图、输出目录、cuda:0 与存在的序列类别；没有真实结构输入或额外科学参数 |
| 软件与冻结副本 | 三份 runs 软件信息一致、配置与已安装官方 config 相同，保持三轮及阈值 50；权重位置与文件大小匹配；三份 launch 与 runs 的 Job、分片、release 和单卡/8 CPU 身份对应 |
| 实际产物 | artifact 根恰好包含 179 个 PDB，各只有本次运行目录；全部文件为 358 份 CIF，没有残留 .log；逐 PDB stderr 全部为空，无失败或失败中间产物 |
| 代码对应 | 本地三个生产脚本统一 LF 后的 SHA256 与报告中的冻结脚本逐项一致；predict.py 摘要仍为 8c18b2a0792ae4b8fafabbacbac82f19eb9f9a83f262b0dda8d82832c0dbc217 |

最长三项逐 PDB 总耗时为 11jb 37383.27 秒、9ygu 9242.41 秒、28lu 9120.77 秒；来自 status 的 elapsed_seconds，包含解压、官方预测与运行内验收，不用跨节点时钟差计算。

### 最后一次锁操作（不是正式提交或统计命令）

按用户最后授权，只释放分片 2。操作前再次核实 Job374480 的 gnode07 进程、动态命令、对应 release/launch、try_lock、after_lock、无 kill_lock，以及最终统计全部成功。2026-09-12 01:18:11 在 master 执行：

```bash
rm -- /storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/运行日志与统计/slurm/allocations/374480/after_lock_374480
```

`sacct -j 374480_2 --format=JobIDRaw,JobID,State,ExitCode,End -n -P` 确认 Job374480 及 batch 均于 01:18:20 COMPLETED 0:0；allocation/out 记录 Job 已退出并清理活动锁与动态命令。未使用 scancel，未操作 377521、377793 的锁或接管后进程。

### 最终 Git 核验

本任务实现端点 `495a4de2cc0a3c528c5a397d3d25d38bdc49c35b` 与学习端点 `cfc9ef56d5e4900baec1b36459ddf49740f41cb9` 的完整树均为 `7df8644353b68f3b99f91d33fa7fbe69a2abef4a`；`git diff --quiet codex/cryoatom2-test0-chain06 Learn/cryoatom2-test0-chain06` 返回 0。当前 Learn/CUMULATIVE 已由其他任务推进至 `9f95ede38dd59783f871837c79dd8e42d496a680`，按所有可达提交的提交者时间仍为唯一最新；另两个登记工作树均指向更早的可视化分支提交。本任务生产代码与测试相对原学习端点无差异，README 仅补充此前授权的 pre_hold 说明。未重复运行未改变代码的测试；已有两端 7 项测试与双线核验证据仍适用。

本次只更新最终记录、映射和项目记忆，按项目文档例外留在累计分支工作区，不创建新实现历史、不触碰其他 agent 的可视化修改、不推送远端。

## 计划与实现差异

- 有益差异：未发现需要改变科学契约的差异。
- 中性差异：明确请求每卡 96G 内存用于共享节点调度；资源接管与最终释放按用户逐次授权处理，均不改变预测输入或产物。
- 有害差异：最终核查未发现遗漏输入、真实结构泄漏、非默认科学参数或缩小分母。
- 未完成范围：本轮 179 项原生结构生成与验收无剩余事项。Find_1 受体特征、模拟密度替换和性能对照属于后续任务，不据本次文件有效性验收推断预测结构精度。
