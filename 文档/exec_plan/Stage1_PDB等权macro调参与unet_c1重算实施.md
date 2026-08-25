# Stage1 PDB 等权 macro 调参与 unet_c1 重算实施

本记录实施 `文档/规划文档/BOX-level数据契约.md` 中的 Stage1 PDB 等权 macro 调参与评估契约，并以 Pocket Plus `talk/refactor/stage1_v3_inference.md` 作为函数、目录和运行入口的实现规格。

## 1. 任务目标

本次工作把 Stage1 正式调参目标从跨 PDB 汇总计数的 micro 指标切换为 PDB
等权 macro 指标，同时保留 evaluate 对 micro 与 macro 的完整报告。实现覆盖
语义概率阈值、basic 候选选择和 Find Gaussian 候选选择，不增加运行时
micro/macro 开关。

本次服务器重算只处理已经训练完成的 `unet_c1`。重算复用既有 probability
科学产物，从语义阈值开始重新生成 F1/F2 blobs、basic 参数和评估结果；不生成
centered，也不申请 GPU。

## 2. 科学契约

### 2.1 语义概率阈值

每个 calibration PDB 在共同概率网格上独立计算 F-alpha。每个网格位置对所有
calibration PDB 的局部 F-alpha 取算术平均，以该 macro 曲线选择首个最大值。
PDB 不按完整图体积或正负体素数量加权；局部指标分母为零时记为 0.0。

语义摘要以 `pdb_count` 和 `macro_f_beta` 表达正式目标。扫描 NPZ 使用
`macro_f_beta_curve`。跨 PDB 汇总的 `tp/fp/fn`、真实配体体素数和背景体素数
继续保存为诊断计数，但不参与阈值选择。

### 2.2 basic 与 Gaussian 选择参数

全部选择阶段最大化以下三项之和：

1. semantic macro F-beta；
2. coverage@0.3 macro F-beta；
3. one-to-one@0.3 macro F-beta。

三项权重均为 1，共用现有 `objective_beta`。每一项先在单个 PDB 内计算，再对
调参清单中的全部 PDB 等权平均；候选数、体素数和 ligand occurrence 数量均不
改变 PDB 权重。basic 的实际分数阈值和最终最小体素数搜索，以及 Gaussian 的
粗搜、细搜和最终最小体素数搜索，使用同一目标定义。

### 2.3 评估与超量提示

evaluate 不随调参目标收窄，继续发布 semantic、coverage 和 one-to-one 的
micro 与 macro F-beta，并额外发布完整图 `semantic_micro_prauc` 和
`semantic_macro_prauc`。两个 PRAUC 都使用 1024 阈值分箱 AP；macro 逐 PDB
计算后等权平均，micro 先合并全部体素计数。

来源 blob 数量严格大于 1000 时仍写 `_BLOB_EXCEED`。默认行为保持写标记后
跳过 centered；显式启用 `--continue-on-blob-exceed` 时，标记只作提示，当前
PDB 继续生成 centered，后续 tune/evaluate 直接消费 centered。该开关不增加
恢复、覆盖、清理或独立状态机制。

## 3. 正式产物目录

历史 micro 结果保留在：

```text
/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950——micro(old)
```

本次 F1/F2 macro 结果共同写入：

```text
/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950
```

新根目录采用后续正常推理使用的结构：

```text
unet_c1-mainchain-ligand_PRAUC_0.602950/
├── inputs/
├── artifacts/
│   └── unet_c1/
│       ├── tuning/
│       │   ├── F1_semantic.json
│       │   ├── F1_semantic_scan.npz
│       │   ├── F1_basic.json
│       │   ├── F2_semantic.json
│       │   ├── F2_semantic_scan.npz
│       │   └── F2_basic.json
│       ├── calibration/
│       │   ├── <pdb_id>/...
│       │   └── evaluation/...
│       └── validation/
│           ├── <pdb_id>/...
│           └── evaluation/...
├── monitoring/
└── feedback/
```

`tuning/` 只放生产者级调参文件。`calibration/` 和 `validation/` 只放逐 PDB
产物及各自的评估目录，不再把 `F1_basic.json` 等文件与 PDB 目录混放。
正式 CLI 的 `--output-root` 固定传入 `<新根>/artifacts`，因此 producer 实际根目录是
`<新根>/artifacts/unet_c1/`，不直接把外层新根传给 CLI。

## 4. probability 迁移与正式重算范围

旧根目录的 calibration 100 个 PDB 和 validation 200 个 PDB 已有完整
probability 产物。本次把每个 PDB 的 `probability/` 目录及对应
`status/probability/` 真实复制到新根目录，不使用硬链接；新结果因此不依赖旧
目录的后续保留位置。
精确目标为 `<新根>/artifacts/unet_c1/<split>/<pdb_id>/probability/` 和
`<新根>/artifacts/unet_c1/<split>/<pdb_id>/status/probability/`，其中 `split` 为
`calibration` 或 `validation`。

F1 使用 `alpha=1` 和 `objective_beta=1`；F2 使用 `alpha=2` 和
`objective_beta=2`。两项 CPU 作业分别执行：

1. 用 calibration 清单拟合 semantic macro 阈值并生成 calibration blobs；
2. 用冻结语义阈值生成 validation blobs；
3. 用 calibration blobs 调整 basic 参数；
4. 评估 calibration blobs；
5. 评估 validation blobs。

评估名称分别使用 `f1_blobs_basic_macro_selected` 和
`f2_blobs_basic_macro_selected`。同一名称可在 calibration 与 validation 的
独立评估目录重复使用。

## 5. 验收条件

- 构造 PDB 规模不均衡的测试，证明 macro 目标不被大体积 PDB 主导；
- basic 与 Gaussian 的全部搜索阶段使用相同 macro 三项目标；
- 串行与并行参数搜索得到逐字段相同结果；
- evaluate 同时发布 semantic、coverage 和 one-to-one 的 micro/macro F-beta，以及完整图 semantic micro/macro PRAUC；
- 超量 PDB 留下 `_BLOB_EXCEED`，提示模式仍完成 centered、tune 和 evaluate；
- 新服务器根目录具有正常推理结构，tuning 文件不与逐 PDB 结果混放；
- calibration 与 validation 分别完成 100 和 200 个 PDB 的 F1/F2 blobs 与评估；
- 正式运行没有 centered 产物，也没有申请 GPU。

## 6. 执行进度

- [x] 用户确认 macro 科学目标、提示模式和目录优化。
- [x] 双仓库 `Learn/CUMULATIVE` 前置状态核验通过。
- [x] 服务器旧根目录与空的新根目录只读核对完成。
- [x] Pocket_Plus 实现、测试和三轮独立审查完成：定向回归 54 项通过，完整回归 354 项通过；唯一既有失败来自本轮范围外的 `Find_1.sh` worker 断言。代码布局、注释文档和科学逻辑第三轮全面审查及后续窄口径复核均已批准。
- [x] Pocket_Plus 与 AdaLigand 双线历史完成等价核验。
- [x] probability 复制和两项正式 CPU 作业完成：复制 Job `356881`、F1 Job `356883` 与 F2 Job `356884` 均为 `COMPLETED/0:0`。
- [x] calibration/validation 正式产物与 macro 指标完成验收。
- [x] BOX 契约、执行记录、映射索引和 handoff 完成收口。

本节只在出现明确事件时更新，不记录固定间隔的监视流水账。

## 7. 正式执行记录

### 7.1 产物来源

本次不重新执行模型前向。calibration 100 个 PDB 与 validation 200 个 PDB 的
完整图 probability 来自：

```text
/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950——micro(old)
```

这些 probability 由以下 checkpoint 生成：

```text
/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/runtime/mainchain_official_346737/logs/AdaLigand_Stage1-unet_c1-mainchain/unet_c1_mainchain____tmp_stage1_mainchain_job346737_20260818T035126_a4_formal/checkpoints/TOP_epoch_00_score_0.6030.ckpt
```

当时解析后的训练配置是同一运行目录的 `config.yaml`，模型代码来源是该运行目录的
`src_snapshot/src`。新根目录只复制 `calibration.json`、`validation.json`、
`training_config.yaml` 和本次 `stage1_v3.yaml`；不复制旧目录中用于历史审计的
校验和与身份文件。

### 7.2 代码同步与本地验收

Pocket Plus 与 AdaLigand 的实现分支和 Learn 分支已经通过树等价核验，两个
`Learn/CUMULATIVE` 均推进到本次学习端点。Pocket Plus 学习端点再次运行
`tests/inference/test_stage1_v3.py`、`tests/inference/test_calibration_parallel.py`
和 `tests/datasets/test_stage1_dataset.py`，结果为 `54 passed`。

服务器只同步以下三个推理范围，不覆盖 `Find_1.sh`、`unet_c1.sh` 或其他训练入口：

```text
src/inference/
configs/inference/
训练与运行/sh/infer/
```

同步后，服务器上的 `stage1_v3.sh` 通过 `bash -n`，活动代码同时包含
`semantic_macro_prauc` 与 `--continue-on-blob-exceed` 入口。

### 7.3 probability 复制 Job

第一次构造复制任务时，本机 PowerShell 在生成 Base64 载荷前发生参数括号错误；
`sbatch` 返回 `Batch script is empty`，没有生成 Job，也没有远端副作用。修正后把
以下脚本交给 Slurm，正式 Job 为 `356881`：

```bash
sbatch --parsable \
  --job-name=stage1_macro_copy \
  --partition=cpu \
  --qos=Cpu96 \
  --nodes=1 \
  --ntasks=1 \
  --cpus-per-task=4 \
  --mem=16G \
  --output='<新根>/monitoring/probability_copy_%j.out' \
  --error='<新根>/monitoring/probability_copy_%j.err'
```

Job 脚本在新根建立 `inputs/`、`artifacts/unet_c1/tuning/`、两个数据划分目录、
`monitoring/` 和 `feedback/`。它逐 PDB 使用 `rsync -a` 真实复制
`probability/` 与 `status/probability/`，不复制旧 blobs、调参或评估结果；结束前
要求两个数据划分的 `_COMPLETE` 数量分别等于 100 和 200。

### 7.4 F1 与 F2 首次提交

F1 使用 Job `356883`。首次命令是：

```bash
bash /home/penghongen/My_Project/Pocket_Plus/训练与运行/submit_task.sh \
  --task-root /home/penghongen/My_Project/Pocket_Plus \
  --sh 训练与运行/sh/infer/stage1_v3.sh \
  --resource cpu \
  --cpus 16 \
  --mem 64G \
  --after_hold \
  --job-name unet_c1_macro_f1 \
  -- blobs \
  --producer unet_c1 \
  --pdb-json '<新根>/inputs/calibration.json' \
  --split calibration \
  --output-root '<新根>/artifacts' \
  --alpha 1 \
  --fit-semantic \
  --data-root /storage/penghongen/AdaLigand/Ori_Data
```

F2 使用 Job `356884`，命令只把 `--job-name` 改为 `unet_c1_macro_f2`，并把
`--alpha` 改为 2。两项都使用 16 CPU、64 GiB 内存、0 GPU 和 `after_hold`；
后续阶段将在同一 allocation 的 `try_lock` 中明确改写动态命令。

提交时尝试用 `SBATCH_DEPENDENCY=afterok:356881` 约束复制先行，但服务器上的
两个正式 Job 没有保留该依赖并直接启动。检查时新目录只有 65/100 个
calibration probability，因此立即对 `356883` 与 `356884` 写入 `kill_lock`。
两个命令均已停止并进入 `try_lock`，没有把本轮视为正式结果。待 Job `356881`
完成 100/200 计数核验后，删除两个 `try_lock`，从上述原始命令重新执行。

Job `356881` 最终运行 7 分 40 秒并输出：

```text
calibration_probability_complete=100
validation_probability_complete=200
```

错误日志为空。抽查 `6bgi/probability/probability_map.npz` 时，新旧文件大小均为
64,130,848 字节，但 inode 不同，确认新目录保存的是独立文件，不是硬链接。
随后释放两个 `try_lock`，F1/F2 的 calibration 语义拟合从原命令重新运行并成功。

### 7.5 后续动态命令

下列命令中的 `NEW` 为正式结果根，`STAGE1` 为当前 release 内的推理入口：

```bash
NEW=/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950
STAGE1="${TASK_PROJECT_ROOT}/训练与运行/sh/infer/stage1_v3.sh"
```

F1 validation blobs 使用 calibration 阶段冻结的语义阈值：

```bash
bash "$STAGE1" blobs \
  --producer unet_c1 \
  --pdb-json "$NEW/inputs/validation.json" \
  --split validation \
  --output-root "$NEW/artifacts" \
  --alpha 1 \
  --semantic-parameters "$NEW/artifacts/unet_c1/tuning/F1_semantic.json"
```

F1 basic 调参命令是：

```bash
bash "$STAGE1" tune \
  --producer unet_c1 \
  --pdb-json "$NEW/inputs/calibration.json" \
  --split calibration \
  --output-root "$NEW/artifacts" \
  --alpha 1 \
  --objective-beta 1 \
  --score-mode basic \
  --prefiltered-min-voxel 8 \
  --data-root /storage/penghongen/AdaLigand/Ori_Data
```

F1 calibration 评估命令是：

```bash
bash "$STAGE1" evaluate \
  --producer unet_c1 \
  --pdb-json "$NEW/inputs/calibration.json" \
  --split calibration \
  --output-root "$NEW/artifacts" \
  --alpha 1 \
  --artifact blobs \
  --evaluation-name f1_blobs_basic_macro_selected \
  --selection-parameters "$NEW/artifacts/unet_c1/tuning/F1_basic.json" \
  --data-root /storage/penghongen/AdaLigand/Ori_Data
```

F1 validation 评估把上述命令的 PDB 清单和 `--split` 改为 validation，其余参数
保持不变。F2 的四条命令把 alpha、objective beta、文件标签和评估名称从 F1
分别改为 F2；即 `alpha=2`、`objective_beta=2`、`F2_*.json` 和
`f2_blobs_basic_macro_selected`。每次只在 `try_lock` 存在且任务未运行时原子替换
动态命令，随后删除 `try_lock`。全部实际命令由 Job `356883` 和 `356884` 的
六次 launch 保存。

### 7.6 语义阈值与 basic 参数

| 参数 | F1 | F2 |
| --- | ---: | ---: |
| semantic threshold | 0.607086181640625 | 0.230712890625 |
| semantic macro F-alpha | 0.4062998499060799 | 0.45911927157260446 |
| basic score threshold | 0.8210563659667969 | 0.3140856623649597 |
| min voxels | 16 | 21 |
| macro 三项目标和 | 1.2707055168659867 | 1.3726212235136972 |

两个 basic 目标分别严格等于 calibration 上对应 beta 的 semantic、coverage@0.3
与 one-to-one@0.3 三项 macro F-beta 之和。

### 7.7 calibration 与 validation 结果

下表只摘录本次调参 beta 对应的 0.3 指标。正式 metrics JSON 还完整保存另一种
beta、0.5/0.6 阈值、precision、recall、top-K、计数和逐 PDB JSONL。

| 数据划分与参数 | semantic macro | coverage@0.3 macro | one-to-one@0.3 macro | semantic micro | coverage@0.3 micro | one-to-one@0.3 micro | semantic macro PRAUC | semantic micro PRAUC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| calibration F1 | 0.3935815298 | 0.4394514584 | 0.4376725286 | 0.5774583328 | 0.4816014539 | 0.4762110727 | 0.4096417393 | 0.5433163278 |
| calibration F2 | 0.4593730732 | 0.4592939075 | 0.4539542427 | 0.6372097188 | 0.5045253840 | 0.4959860107 | 0.4096417393 | 0.5433163278 |
| validation F1 | 0.4555574170 | 0.5098829900 | 0.5025159453 | 0.5556350429 | 0.5175604668 | 0.5050661171 | 0.4572529597 | 0.5080070029 |
| validation F2 | 0.5055086160 | 0.4932014093 | 0.4853090575 | 0.5928843949 | 0.5216075680 | 0.5044018807 | 0.4572529597 | 0.5080070029 |

PRAUC 只由同一数据划分的完整图 probability 与 `union_mask` 决定，因此同一数据
划分的 F1/F2 值相同；candidate 选择参数不会改变 PRAUC。

### 7.8 最终产物与资源状态

最终计数如下：

| 产物 | calibration | validation |
| --- | ---: | ---: |
| probability `_COMPLETE` | 100 | 200 |
| F1 blobs `_COMPLETE` | 100 | 200 |
| F2 blobs `_COMPLETE` | 100 | 200 |
| F1 逐 PDB evaluation NPZ / JSONL 行数 | 100 / 100 | 200 / 200 |
| F2 逐 PDB evaluation NPZ / JSONL 行数 | 100 / 100 | 200 / 200 |

`centered_files=0`，符合本轮 basic-only 范围。producer 级六个调参文件均位于
`artifacts/unet_c1/tuning/`；数据划分级 JSONL 与 metrics JSON 位于各自的
`evaluation/`，没有与逐 PDB 目录混放。

Job `356881`、`356883` 和 `356884` 最终均为 `COMPLETED/0:0`。F1/F2 使用
16 CPU、64 GiB 内存与 0 GPU；其 allocation 总历时分别为 1:52:43 和 1:52:50，
其中包含人为安排的 `try_lock` 休眠。最后两项 validation evaluate 成功后删除
两个 `after_lock` 正常释放资源，没有使用 `scancel`。

Job 错误日志中保留一次退出码 137，它对应 probability 尚未复制完整时主动写入
`kill_lock` 的第一轮命令，不是后续正式阶段失败。第二至第六次执行均成功，且
最终 Slurm 状态为 0:0。
