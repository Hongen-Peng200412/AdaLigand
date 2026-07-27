# Stage1 正式训练准备产物：测试、服务器核验与 Dataset 清理边界

## 本文负责什么

本文记录 `C:\Users\15919\Desktop\AdaLigand\talk\短交互.md` 中“最小修正现有 keep list 和 BOX 池”这一轮工作的测试与核验结果，并给出下一轮清理 Dataset 代码的精确边界。

本文不负责：

- 修改或中断正在运行的 Job 321107、321540、321743；
- 修改这三个任务已经保存的代码快照、配置、训练目录或数据；
- 接管另一个 AI agent 正在整理的正式训练启动脚本；
- 在未经下一次确认的情况下删除 Dataset 代码。

## 结论

服务器任务 328567 生成的正式训练准备目录符合本轮数据目标：

- 16 个待排除 PDB 编号中，5 个原本存在于源产物，已经从新产物的全部相关位置删除；
- 另外 11 个在源产物中本来就不存在；
- 新目录的最终候选配体清单、四个数据集合清单、BOX 清单、验证请求、配置、完成标记和 13,910 个 BOX 文件相互一致；
- 当前服务器上的 Dataset 读取函数可以直接读取这些产物；
- 新产物中没有残留任何一个待排除 PDB 编号；
- 本地新增测试与现有相关测试共 32 项，全部通过。

产物本身没有发现需要返工的错误。核验后的当前状态是：

1. `C:\Users\15919\Desktop\Pocket_Plus\src\datasets\readme.md` 已经补齐最终候选配体清单和四份数据划分文件的 16 个字段，也已补写 `config.json` 中的 `parallel_publisher`。
2. README 已按实际使用顺序调整：先说明训练直接读取的 BOX 池，再说明不在每个训练周期中直接读取的候选配体来源与划分清单。
3. `ops/materialize_filtered_stage1_preparation.py` 与 README 已统一为当前行为：固定排除编号原本不存在时只输出提示，不停止生成。
4. 唯一尚未完成的代码清理是删除 Dataset 的 `excluded_pdb_ids` 机制。当前三个正式训练脚本仍通过环境变量默认值指向旧训练准备目录，因此必须先切换脚本默认目录，再删除这层运行时排除。

## 正式目录

源目录：

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation/adaligand_stage1_20260721T024000
```

新目录：

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation
```

生成任务的追溯位置：

```text
/home/penghongen/SIMPLE_RUN/materialize_filtered_stage1_preparation_328567.out
/home/penghongen/SIMPLE_RUN/materialize_filtered_stage1_preparation_328567.err
```

核验时，Job 328567 已经不在 Slurm 等待或运行清单中，对应的 `try_lock` 和 `after_lock` 也已经不存在。本轮核验没有终止、重新提交或接管该任务。

## 排除的 PDB 编号

### 源产物中存在并已删除

```text
5y6p
7n6g
7z8g
9hhl
9v7i
```

这 5 个 PDB 编号一共对应：

- 最终候选配体清单中的 2,205 个候选配体实例；
- 训练数据集合清单中的 2,205 个候选配体实例；
- BOX 清单中的 5 个 PDB；
- BOX 目录中的 5 个 `.npz` 文件。

### 源产物中本来就不存在

```text
1q5c
2w49
6k0a
7cbp
7cth
7ojf
7pel
7wc2
8olc
9wqp
9yx6
```

任务 328567 的第一次执行仍采用“任意编号未命中就报错”的旧实现，因此在发现这 11 个编号不存在时退出。用户随后把该行为改为输出提示但继续执行，第二次执行成功。现有测试已经固定这一行为：待排除编号原本不存在时不报错。

## 本地测试

新增测试文件：

```text
C:\Users\15919\Desktop\Pocket_Plus\tests\datasets\test_materialize_filtered_stage1_preparation.py
```

该文件包含 4 项测试：

1. 在临时源目录中构造完整的最小产物，核对最终候选配体清单、四个数据集合清单、BOX 清单、BOX 文件、验证请求和完成标记是否一并更新。
2. 核对待排除编号原本不存在时，程序只输出提示并继续生成目标目录。
3. 核对目标目录已经存在时，程序拒绝覆盖。
4. 核对验证请求中的 PDB 位置编号非法时，程序在创建目标产物前停止。

执行结果：

| 测试范围 | 结果 |
|---|---:|
| 新增的正式目录生成测试 | 4 passed |
| 现有 Stage1 Dataset 测试 | 18 passed |
| 现有 AdaLigand Stage1 配置测试 | 10 passed |
| 合计 | 32 passed |

第一次尝试使用本机名为 `Pocket_Plus_windows` 的 Conda 环境，但该环境在当前 `D:\Anaconda` 中不存在。随后使用当前工作区可用的 `D:\Anaconda\python.exe` 执行测试；该解释器使用 NumPy 1.26.4 和 pytest 7.4.4。不存在的 Conda 环境没有被计入测试结果。

本轮没有暂存或提交新增测试，也没有把它与 Pocket_Plus 工作区内其他任务已经存在的修改混在一起。

## 服务器端到端核验

用户允许使用最多 16 个 CPU 核进行短时服务器核验。正式核验使用独立的只读 Slurm 任务完成；核验脚本只读取源目录和新目录，没有修改正式产物。

### 产物整体核验

任务：

```text
Job 328936
```

结果：

```text
COMPLETED
运行时间 57 秒
ExitCode 0:0
```

证据：

```text
/home/penghongen/My_Project/tmp/adaligand_stage1_verify_20260727/verify_328936.out
/home/penghongen/My_Project/tmp/adaligand_stage1_verify_20260727/verify_328936.err
```

核验内容：

- 完整比较最终候选配体清单与四个数据集合清单，确认新文件等于源文件按 PDB 编号过滤后的结果，而且原有顺序没有改变；
- 完整比较 BOX 清单中的 PDB 编号和文件路径；
- 检查全部 13,910 个目标 BOX 文件，确认文件集合与 BOX 清单完全一致，并确认复制前后的文件大小和纳秒级修改时间一致；
- 均匀抽取 512 个训练 BOX，并检查全部 200 个验证 BOX，共对 712 个 `.npz` 文件计算 SHA-256，同时比较字段名称、数组形状和数据类型；
- 完整核对验证请求中的 PDB 编号重排和所有位置编号；
- 核对配置文件内容不变；
- 核对 `_COMPLETE` 是零字节完成标记；
- 核对目标根目录没有意外文件；
- 核对 16 个待排除 PDB 编号没有出现在任何目标清单或 BOX 文件名中。

SHA-256 只用于本次外部核验，没有进入正式生成代码或正式产物。

### 产物数量

| 产物 | 源目录数量 | 新目录数量 | 删除数量 |
|---|---:|---:|---:|
| 最终候选配体清单 | 579,688 | 577,483 | 2,205 |
| 训练数据集合清单 | 437,392 | 435,187 | 2,205 |
| 验证数据集合清单 | 5,942 | 5,942 | 0 |
| 校准数据集合清单 | 3,532 | 3,532 | 0 |
| 保留评估池清单 | 132,822 | 132,822 | 0 |
| BOX 清单 | 13,915 | 13,910 | 5 |

验证请求的目标数量：

| 请求类别 | 数量 |
|---|---:|
| 验证 PDB | 200 |
| 以候选配体为中心的 BOX | 3,281 |
| 带位置偏移的 BOX | 16,405 |
| 不要求包含配体的背景 BOX | 9,843 |
| BOX 请求合计 | 29,529 |

### 使用当前 Dataset 代码读取

任务：

```text
Job 328939
```

结果：

```text
COMPLETED
运行时间 10 秒
ExitCode 0:0
```

证据：

```text
/home/penghongen/My_Project/tmp/adaligand_stage1_verify_20260727/consume_328939.out
/home/penghongen/My_Project/tmp/adaligand_stage1_verify_20260727/consume_328939.err
```

该任务直接调用服务器当前代码中的：

```text
src.datasets.stage1_requests._load_manifest_pool_paths
src.datasets.stage1_requests.load_validation_selection
```

读取结果：

- 训练 BOX 清单包含 13,710 个 PDB；
- 验证 BOX 清单包含 200 个 PDB；
- 验证请求共 29,529 个；
- 当前 Dataset 实际读取到的输入中，16 个待排除 PDB 编号的命中数量为 0。

因此，新目录不仅在文件层面自洽，也能被当前训练数据读取代码直接使用。

## 字段级核验与已经完成的 README 修正

完整字段核验先发现现有 README 对 JSONL 文件的描述不完整。随后任务 328946 对新目录中的全部 577,483 个最终候选配体实例和四个数据集合清单进行了字段扫描。

任务 328946：

```text
COMPLETED
运行时间 25 秒
ExitCode 0:0
```

证据：

```text
/home/penghongen/My_Project/tmp/adaligand_stage1_verify_20260727/schema_328946.out
/home/penghongen/My_Project/tmp/adaligand_stage1_verify_20260727/schema_328946.err
```

每个候选配体实例均包含以下 16 个字段：

| 字段 | 实际类型 |
|---|---|
| `pdb_id` | 字符串 |
| `candidate_id` | 整数 |
| `type_tag` | 字符串 |
| `map_resolution` | 浮点数 |
| `cc_all` | 浮点数 |
| `cc_all_about_mean` | 浮点数 |
| `cc_contour` | 浮点数 |
| `cc_contour_about_mean` | 浮点数 |
| `q_score` | 浮点数 |
| `q_score_median` | 浮点数 |
| `q_score_min` | 浮点数 |
| `pocket_n_atoms` | 整数 |
| `pocket_status` | 字符串 |
| `pocket_q_score` | 浮点数或 `null` |
| `pocket_q_score_median` | 浮点数或 `null` |
| `pocket_q_score_min` | 浮点数或 `null` |

三个允许为 `null` 的口袋 Q-score 字段具有相同的空值数量：

| 清单 | 每个字段的 `null` 数量 |
|---|---:|
| 最终候选配体清单 | 3,077 |
| 训练数据集合清单 | 2,570 |
| 验证数据集合清单 | 3 |
| 校准数据集合清单 | 3 |
| 保留评估池清单 | 501 |

所有 577,483 个最终候选配体实例使用同一组字段。四个数据集合清单中的实例字段与最终候选配体清单一致。

核验时，README 只把 `pdb_id` 和 `candidate_id` 写成了上述 JSONL 文件的字段，遗漏另外 14 个字段及三个口袋 Q-score 字段允许为 `null` 的事实。本轮已经补齐全部 16 个字段、类型、含义、空值关系和四份数据集合中的空值数量。

配置文件的实际内容还包含 README 未说明的字段：

```yaml
parallel_publisher:
  script: tmp/stage1_parallel_box_pool.py
  workers: 32
  single_pdb_builder: src.datasets.stage1_box_pool.build_pdb_box_pool
```

README 和生成脚本原本还保留“待排除编号未命中时立即报错”的旧说法，但当前代码和测试已经采用“输出提示并继续”的行为。本轮已经同步说明，并删除生成脚本中被注释掉的旧报错语句。

任务 328945 因最初按照 README 的不完整字段说明检查数据而退出。它没有发现产物损坏，反而证明 README 不能作为当前产物的完整字段契约。任务 328946 改为从实际文件归纳字段集合后通过。

## Dataset 清理的依赖关系

只读审计确认，当前正式启动脚本仍默认使用旧目录：

```text
C:\Users\15919\Desktop\Pocket_Plus\训练与运行\sh\Find_0.sh
C:\Users\15919\Desktop\Pocket_Plus\训练与运行\sh\Find_1.sh
C:\Users\15919\Desktop\Pocket_Plus\训练与运行\sh\unet_c1.sh
```

三个文件中的默认 `ADALIGAND_STAGE1_PREPARATION_ROOT` 仍指向：

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation/adaligand_stage1_20260721T024000
```

而本轮核验通过的新目录是：

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation
```

因此，不能现在就单独删除 Dataset 的 `excluded_pdb_ids` 机制。否则，尚未切换目录的正式启动脚本会读取含有那 5 个 PDB 的旧清单，同时失去训练时排除它们的保护。

这不是三个正在运行的训练任务的风险：它们各自使用已经固定的服务器代码和运行目录，本地后续清理不会改变它们。这里约束的是今后通过正式启动脚本创建的新训练。

## 后续工作安排：两个有先后关系的短任务

两个短任务不能颠倒。短任务一把今后的正式训练入口切换到已经排除缺失辅助标签 PDB 的新目录；短任务二再删除 Dataset 内部的重复排除能力。短任务一完成后，即使短任务二尚未开始，重复排除也只会再次过滤一个已经不存在的集合，不会改变训练样本；反过来先删除 Dataset 排除能力，则旧脚本可能重新读入 `5y6p`、`7n6g`、`7z8g`、`9hhl` 和 `9v7i`。

### 短任务一：把三个正式训练脚本的默认目录切换到新产物

这项工作由正在整理正式启动脚本的 AI agent 负责；本文件只给出它必须达到的接口和验收标准。

#### 当前事实

两个 Dataset Hydra 配置已经把新目录作为环境变量缺失时的默认值：

```text
configs/dataset/stage1_find.yaml
configs/dataset/stage1_unet_c1.yaml
```

其中 `box_pool_root` 的默认结果是：

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation/box_pool
```

但是以下三个脚本会先设置 `ADALIGAND_STAGE1_PREPARATION_ROOT`，从而覆盖 Hydra 的新默认值：

```text
训练与运行/sh/Find_0.sh
训练与运行/sh/Find_1.sh
训练与运行/sh/unet_c1.sh
```

三个脚本当前设置的旧目录是：

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation/adaligand_stage1_20260721T024000
```

#### 允许修改的内容

只把三个脚本中 `ADALIGAND_STAGE1_PREPARATION_ROOT` 的缺省值改为：

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation
```

继续保留 `${ADALIGAND_STAGE1_PREPARATION_ROOT:-<缺省值>}` 这种写法，使用户显式提供环境变量时仍可选择其他经过核验的训练准备目录。

#### 不应混入的内容

- 不修改模型结构、损失权重、学习率、warmup、批量大小或随机种子。
- 不修改 Job 321107、321540、321743 已保存的运行时代码和最终配置。
- 不提交新的 Slurm 训练任务，不使用 `kill_lock`，不重新生成 BOX 池。
- 不在这一短任务中删除 `excluded_pdb_ids`；目录切换和 Dataset 清理应保留为两个可分别审阅的改动。

#### 验证方式

1. 三个 shell 文件通过 `bash -n`。
2. 对 Find_0、Find_1 CPC1、Find_1 CPC2 和 unet_c1 分别解析 Hydra 最终配置。
3. 每份最终配置中的 `dataset.box_pool_root` 必须等于：

   ```text
   /storage/penghongen/AdaLigand/Ori_Data/stage1_preparation/box_pool
   ```

4. `dataset.split_train` 必须指向新目录的 `box_pool/train`；`dataset.split_val` 必须指向新目录的 `box_pool/validation_selection.npz`。
5. 服务器只读检查新目录中的 `box_pool/_COMPLETE`、`manifest.json` 和 `validation_selection.npz` 仍然存在。已有 Job 328936 与 328939 的核验结果可以作为数据内容证据，不需要重跑数据生产。
6. 比较修改前后的最终配置，除训练准备目录及短任务二仍待删除的 `excluded_pdb_ids` 外，不得出现其他字段变化。

#### 完成标准

- 三个脚本在不额外设置环境变量时都解析到新目录。
- 显式设置 `ADALIGAND_STAGE1_PREPARATION_ROOT` 时仍能覆盖缺省值。
- 没有启动或中断任何训练。
- 负责该任务的 AI agent 在交接记录中写明修改的三个文件、最终目录和配置解析结果。

### 短任务二：删除 Dataset 的运行时 PDB 排除机制

开始条件：短任务一已经完成，并有证据证明 Find_0、Find_1 和 unet_c1 的默认最终配置都读取新目录。

这一短任务的目标是让训练样本集合只由正式 `manifest.json` 和 `validation_selection.npz` 决定。`excluded_pdb_ids` 不再是 Dataset 接口、Hydra 配置字段或比例抽样文件身份的一部分。

#### 第一步：收窄 `Stage1Dataset` 的接口

文件：

```text
src/datasets/stage1_dataset.py
```

需要完成：

1. 从 `Stage1Dataset.__init__` 的参数和 Docstring 删除 `excluded_pdb_ids`。
2. 当 `split_file` 是内存中的 `ResolvedStage1Crop` 序列时，直接保存该非空序列，不再根据 PDB 编号建立第二份筛选结果。
3. 保留内存请求序列必须非空的检查，但错误信息只描述“输入请求序列为空”，不再提“排除后为空”。
4. 调用 `build_request_source` 时不再传递 `excluded_pdb_ids`。
5. 不改动密度通道、标签构造、随机旋转、缓存或 `split_train`、`split_val` 兼容参数。

#### 第二步：删除请求构造层的重复过滤

文件：

```text
src/datasets/stage1_requests.py
```

需要作为一个整体删除：

1. `_normalize_excluded_pdb_ids`。
2. `_fraction_filename` 的 `excluded_pdb_ids` 参数、排除集合摘要和 `_exclude<12位摘要>` 文件名后缀。
3. `Stage1TrainingRequestSet.__init__` 的 `excluded_pdb_ids` 参数、`self.excluded_pdb_ids` 和读取 `manifest.json` 后的 PDB 过滤。
4. `build_request_source` 的 `excluded_pdb_ids` 参数与标准化步骤。
5. 读取 `validation_selection.npz` 后按 PDB 编号过滤请求的列表推导式。
6. 读取普通冻结请求文件后按 PDB 编号过滤请求的列表推导式。
7. “排除后没有可读取请求”一类错误信息；保留清单、请求或 BOX 池本身为空时的明确错误。

删除后，三类输入分别保持以下行为：

- 训练 BOX 目录：读取 `manifest.json` 中列出的全部训练 PDB，再按现有 `seed` 和 `epoch` 构造请求。
- `validation_selection.npz`：读取文件中列出的全部验证请求，再执行既有的 `box_sample_fraction` 逻辑。
- 普通冻结请求文件：按文件内容完整返回请求，不额外删除 PDB。

#### 第三步：删除 Hydra 中已经失效的字段

从以下 Dataset 基础配置删除空列表：

```text
configs/dataset/stage1_find.yaml
configs/dataset/stage1_unet_c1.yaml
```

从以下实验配置删除 16 个 PDB 编号及其“只过滤本次训练请求”的旧注释：

```text
configs/experiment/CPC1/Find_1.yaml
configs/experiment/unet_c1.yaml
```

Find_1 CPC2 继承 CPC1 的 Dataset 设置，不应新增一份重复字段。Find_0 本来没有这 16 个编号，不需要制造无意义的空配置。

#### 第四步：更新测试，使测试目标变成正式产物契约

文件：

```text
tests/datasets/test_stage1_dataset.py
tests/test_adaligand_stage1_configs.py
tests/datasets/test_materialize_filtered_stage1_preparation.py
```

具体处理：

1. 删除或改写 `test_dataset_excludes_pdb_without_rewriting_request_file`。新的断言应证明内存请求序列按调用者提供的内容完整保留。
2. 删除 `test_training_pool_excludes_pdb_before_fraction_selection`。用现有比例抽样测试继续证明：
   - `box_sample_fraction=1.0` 不创建比例请求文件，并随 epoch 重新选择；
   - `box_sample_fraction<1.0` 创建并复用固定请求文件；
   - 相同 manifest、比例和 seed 得到相同请求。
3. 比例请求文件名只包含数据划分名称、比例和 seed，不再出现 `_exclude<摘要>`。
4. 删除配置测试中比较 Find_1 与 unet_c1 排除编号列表的断言；改为断言最终配置不存在 `dataset.excluded_pdb_ids`。
5. 保留 `test_materialize_filtered_stage1_preparation.py` 中的固定排除测试。它验证的是正式产物生成规则，不属于 Dataset 运行时排除机制。

#### 必须保持不变的行为

- `box_sample_fraction=1.0` 时，每个 epoch 继续使用 `request_seed + epoch` 选择 BOX。
- `box_sample_fraction<1.0` 时，继续生成并复用同一份固定比例请求文件；DataLoader 顺序仍由训练随机种子和 epoch 控制。
- center、bias、context 请求数量关系继续为 `1:5:3`。
- `manifest.json` 的文件存在性、PDB 身份和相对路径检查继续生效。
- `validation_selection.npz` 的 PDB 编号、候选配体编号和 BOX 编号重建继续生效。
- `_sha256_file` 继续用于确认比例请求文件对应的源 manifest 和验证请求；不能因为删除排除集合摘要而删除该函数或 `hashlib` 导入。
- 旧的 `_exclude<摘要>.npz` 比例请求文件如果存在，只是不再被新代码引用；这一短任务不在服务器删除它们。
- `BoxPointDataset`、推理装配、密度通道、辅助标签、模型、损失和训练调度均不在本次修改范围内。

#### 本地验证

至少执行：

```text
python -m pytest tests/datasets/test_materialize_filtered_stage1_preparation.py -q
python -m pytest tests/datasets/test_stage1_dataset.py -q
python -m pytest tests/test_adaligand_stage1_configs.py -q
```

还需要：

1. 解析 Find_0、Find_1 CPC1、Find_1 CPC2 和 unet_c1 的最终 Hydra 配置，确认 `dataset.excluded_pdb_ids` 不存在。
2. 在 `src/datasets/`、上述四份配置和相关 Dataset 测试中搜索 `excluded_pdb_ids`、`_normalize_excluded_pdb_ids` 与 `_exclude<摘要>`，结果必须为空。
3. 不把 `ops/materialize_filtered_stage1_preparation.py` 中的大写 `EXCLUDED_PDB_IDS` 当成残留。该常量属于正式产物生成规则，必须保留。

#### 服务器只读验收

不提交训练，只用当前 Dataset 代码读取新正式目录，确认：

- 训练 manifest 仍有 13,710 个 PDB；
- 验证 manifest 仍有 200 个 PDB；
- 完整验证请求仍有 29,529 个；
- 16 个缺少完整辅助标签的 PDB 在训练与验证输入中的命中数量仍为 0；
- 不依赖 `excluded_pdb_ids` 也能得到上述结果。

如果本地测试已经覆盖读取行为，服务器验收可以复用 Job 328939 的读取方式，但必须使用删除运行时排除后的代码。

#### 停止条件

出现以下任一情况时停止修改并保留证据，不继续扩大范围：

- 三个正式训练脚本中仍有任意一个默认读取旧目录；
- Hydra 最终配置仍把旧目录写入 `dataset.box_pool_root`；
- 删除参数后发现仓库中还有训练或推理调用者必须依赖临时排除 PDB；
- 新正式目录缺少 `_COMPLETE`、manifest、验证请求或其引用的 BOX 文件；
- 不使用运行时排除时，16 个 PDB 中任意一个重新出现在 Dataset 实际读取结果里；
- `box_sample_fraction` 的两种行为、`1:5:3` 请求数量关系或相同 seed 的复现性发生变化。

#### 完成标准

- 正式训练脚本默认读取新目录。
- Dataset、请求构造和 Hydra 中不存在运行时 PDB 排除接口。
- 正式产物生成脚本仍保留固定排除集合和相应测试。
- 本地相关测试全部通过，服务器只读验收通过。
- 没有修改或中断三个基线训练，也没有重新生成正式数据。

## 计划与实际执行的差异

### 有益差异

原计划要求 16 个排除编号全部在源目录中命中。实际源目录只包含其中 5 个。用户把“未命中即报错”改为“输出提示并继续”，使程序能表达真实情况，也避免为了重复排除已经不存在的编号而阻断正式目录生成。测试已按这个决定更新。

### 中性差异

没有对 13,910 个 BOX 文件全部计算 SHA-256。核验改为：

- 全部文件比较路径、大小和纳秒级修改时间；
- 对 512 个训练 BOX 和全部 200 个验证 BOX 比较 SHA-256、字段、数组形状和数据类型。

结合生成代码使用逐文件复制、清单完全一致和实际 Dataset 读取成功，这一范围足以在 30 分钟限制内给出可靠结论。

### 有害差异

未发现已经写入正式产物且需要回滚的有害差异。

### 未完成范围

- 正式启动脚本仍默认引用旧训练准备目录，因此 Dataset 运行时排除代码暂时不能安全删除。
- 启动目录切换后，仍需按上文短任务二删除 Dataset、请求构造、Hydra 和相关测试中的运行时排除机制。

## 当前工作区边界

Pocket_Plus 工作区在本轮开始前已经包含其他任务暂存或未提交的修改。本轮没有暂存、提交、移动或丢弃这些内容。

本轮新增但尚未暂存的文件只有：

```text
C:\Users\15919\Desktop\Pocket_Plus\tests\datasets\test_materialize_filtered_stage1_preparation.py
```

本轮写入的反馈文件是：

```text
C:\Users\15919\Desktop\AdaLigand\talk\短交互\process_1.md
```

下一步继续采用短交互方式：先等待负责正式训练脚本的 AI agent 完成短任务一并提供最终配置证据；用户审阅该证据后，再单独批准短任务二。本文件的修改不代表已经授权删除 Dataset 代码。
