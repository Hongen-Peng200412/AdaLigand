# CryoAtom2 测试集受体重建执行记录

依据：[CryoAtom2 测试集受体重建规划](../规划文档/CryoAtom2测试集受体重建.md)。本记录覆盖输入核对、代码实现与审查、正式资源提交、179 个 PDB 重建验收；不覆盖 Find_1 后续评估。

## 当前状态

2026-09-08：实现及两轮独立代码审查通过；任务目录已上传，正在进行独立 GPU 门控。尚未提交正式预测作业。

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

第二轮三个方向的全面审查均通过，逻辑代理再次独立运行 7 项测试通过。README 官方中间目录编号已按安装源码的 i+1 校正为 1、2、3，逻辑审查代理窄口径复核关闭。后续只对提出的问题进行窄口径复核。当前实现提交为 `056d48055ea24e69ca7aa4ac0fcca1bf21c0d3a5`，双线端点等价待实现端点稳定后执行。

## 正式运行命令

实际工作目录：/home/penghongen/My_Project/AdaLigand。唯一正式提交命令如下；当前尚未执行，作业编号待提交后记录。此入口不调用任何测试或门控。

```bash
bash 测评数据代码/cryoatom2原始预测结构/submit.sh
```

## 测试与门控命令

本节仅保存测试和只读检查，不是正式运行入口。

- 开工 Git 检查：`git status --short --branch`、`git worktree list --porcelain`、`git for-each-ref --sort=-committerdate`、`git log --all --format='%ct %H'`。
- 服务器只读验收：测试清单、序列目录、原始图头、安装模块、权重存在性、CLI 帮助、`pip check` 与 GPU 可见性均已检查；真实模型加载尚待检查。
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

- 2026-09-08：接受 3 个单卡 A100 数组任务、每个 8 核 CPU、不传时间限制、运行后保留资源的授权。启动实现；handoff 只在正式提交与最终完成等有意义事件更新。
- 2026-09-08：服务器确认 a100 分区 `MaxTime=UNLIMITED`，a100g2 QOS 每用户最多 16 张 A100，本次 3 张资源请求可表达；缓存中 ESM2 主权重 2604537549 字节、回归权重 3687 字节、RNA-FM 1194424423 字节。官方推理依赖 `.map/.mrc` 后缀，已采用仅解压的临时 `.map` 输入。
- 2026-09-08：CryoAtom 源码提交为 `856e250df7b784b854b892f1b619d32d51188cef`；已装源码确认 getp 的 temp.log 和默认配置读取语义。A100 节点均处于共享状态，每节点报告 740000 MiB 内存，正式入口选择每任务 `--mem 96G` 以避免默认整节点内存阻塞；总请求仍为 3 张 A100、24 核 CPU、不传时间限制。
- 2026-09-08：首次编码传输命令被自动审批阻止，未执行；随后用严格主机密钥校验的 rsync 无删除传输，仅上传本任务目录到 `/home/penghongen/My_Project/AdaLigand/测评数据代码/cryoatom2原始预测结构/`，成功。
- 2026-09-08：门控 374469 最初为 PENDING(Priority)，调度预估 9 月 13 日开始。针对短时门控执行 `scontrol update JobId=374469 TimeLimit=00:20:00`，缩短其资源预约以允许回填调度；此命令只调整门控，不是正式预测命令，正式 3 卡入口继续不传时间限制。
