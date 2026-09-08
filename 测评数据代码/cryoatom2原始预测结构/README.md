# CryoAtom2 测试集原始预测结构

本目录根据原始 EMDB 密度图与完整蛋白质、RNA、DNA 序列，逐 PDB 调用已安装的 CryoAtom2。主产物是官方默认最终 CIF，同时保存官方 raw CIF。本程序不生成 Find_1 的原子特征或模拟密度，不读取真实受体或配体坐标。

## 输入与输出根

正式任务使用 `/storage/penghongen/AdaLigand/held_out/split/held_out_06_chain/test_0.json` 的 `pdb_ids`；原始图对应关系取自 `/storage/penghongen/AdaLigand/Ori_Data/raw/pair_list.jsonl`，图文件取自同数据根 `raw/emdb_maps/emd_<编号>.map.gz`。例如 `EMD-52935` 对应 `emd_52935.map.gz`，此编号仅用于解释命名规则。

完整序列取自 `/storage/penghongen/AdaLigand/held_out/sequence_catalog.jsonl`。一个 entity 表示一种聚合物分子，它可以在结构中有多个链副本。每个 entity 导出一条完整 FASTA；不按 `comparable` 删除短序列，不按坐标截断或修复未知字符。RNA/DNA 的 `X` 会被官方统一序列读取器忽略，本程序记录这些字符，不自行替换。

输出根固定为 `/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06`。以下为生成代码定义的预期结构，初始服务器检查时产物目录为空。两段展示同一个物理实验根。`<pdb_id>` 来自测试清单，如 `9ter`；`<run_stamp>` 来自提交系统的唯一执行名，例如构造值 `predict_job123_20260908T160000_a1`，重试生成不同名称。

```text
## <科学产物>
/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/
└── cryoatom2_artifact/
    └── <pdb_id>/<run_stamp>/
        ├── <run_stamp>.cif       # 官方默认最终结构，后续主实验使用
        └── <run_stamp>_raw.cif   # 官方 raw 结构，保留供分析

## <其他文件>
/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/
└── 运行日志与统计/
    ├── 任务日志.md               # 本地执行记录的服务器副本（运行诊断）
    ├── runs/<run_stamp>.json     # 软件、权重位置、配置、清单和分片身份（运行诊断）
    ├── summary.json              # 全测试集最近一次状态汇总（运行统计）
    ├── pdb/<pdb_id>/
    │   ├── latest.json           # 最近一次实际预测状态及结构位置（运行完成标记）
    │   └── <run_stamp>/
    │       ├── inputs.json       # 原始图与完整序列来源，未知字符记录（运行诊断）
    │       ├── protein.fasta     # 存在蛋白质时导出全部蛋白质 entity（可再生工具输入）
    │       ├── rna.fasta         # 存在 RNA 时导出全部 RNA entity（可再生工具输入）
    │       ├── dna.fasta         # 存在 DNA 时导出全部 DNA entity（可再生工具输入）
    │       ├── command.json      # 实际 CryoAtom2 参数列表（运行诊断）
    │       ├── stdout.log        # CryoAtom2 标准输出（运行诊断）
    │       ├── stderr.log        # CryoAtom2 标准错误（运行诊断）
    │       ├── official_logs/    # 失败等情况下官方残留的日志，保留其相对目录（运行诊断）
    │       └── status.json       # 本次执行状态（运行完成标记）
    └── slurm/
        ├── allocations/         # 各 Job 的 out、err、动态命令与四种锁（运行诊断）
        ├── launches/            # 每次启动的 launch.json 与 run_cmd.sh（运行诊断）
        └── releases/            # 项目冻结副本与 manifest.json（运行诊断）
```

失败或正在执行的官方输出目录还可能包含 `see_alpha_output/` 和 `CryoNet_round_<0|1|2>/` 等实际计算中间产物；它们仍归属对应 PDB，不当成成功结构。默认成功运行由官方代码清理这些中间目录。输入检查失败时可以没有产物目录或子进程日志，失败原因仍写入状态 JSON。

## 结构产物

### `<run_stamp>.cif` 与 `<run_stamp>_raw.cif`

两份都是官方写出的 PDBx/mmCIF 文本。文件名由官方的输出目录 basename 决定，本程序不改名或改写结构内容。`_atom_site` 保存原子名、元素、残基与链编号、世界 XYZ 坐标 `Cartn_x/y/z`（单位 Å）和 `B_iso_or_equiv`（官方输出的预测置信度字段）。预测链编号不承诺与沉积真实结构一致。

最终 CIF 经过官方序列匹配、修剪和默认链置信度过滤；raw CIF 是官方另存的较完整结构，也不能理解为完全未经处理的神经网络输出。失败、无原子、坐标非有限或缺任一最终文件都不能记为成功。此检查仅证明格式与基本可用性，不证明结构精度或与 Find_1 网格对齐。

`pdb/<pdb_id>/latest.json` 指向最近一次实际尝试，可能为 running 或 failed。后续消费者必须确认 `status=success` 且两份 CIF 复核通过，再消费其中的结构路径。不从目录名排序猜测最新结果，也不把失败时残留的 CIF 当作成功结果。

## 输入与运行身份

### `{protein,rna,dna}.fasta`

只有当前 PDB 存在的类别才生成对应文件并传入命令。FASTA header 为 `><sequence_id>|Chains <链名列表>`，如 `>9TER_1|Chains A, B`；下一行是完整的源 `sequence`。一条 entity 序列只写一次，不因有多个链副本而重复。链名只用于来源标识，预测过程仍由 CryoAtom2 决定结构链。

### `inputs.json`

每次实际预测对应一个 JSON object。

| 字段 | 类型与含义 | 示例 |
| --- | --- | --- |
| `map_path` | string，原始压缩图绝对位置 | `/storage/penghongen/AdaLigand/Ori_Data/raw/emdb_maps/emd_52935.map.gz` |
| `map_size_bytes` | int，压缩文件字节数 | `82462170` |
| `map_mtime_ns` | int，压缩文件修改时间，Unix 纳秒 | `1782410409000000000` |
| `entities` | list[object]，该 PDB 在源目录中的全部 entity，保留原字段 | 见下文 |
| `ignored_characters` | list[object]，官方统一序列读取器不接受的字符 | `[{"sequence_id":"1ABC_2","index":2,"character":"X"}]` |

每个 entity 的 `pdb_id` 是小写 PDB 标识；`entity_id` 是该 PDB 内聚合物编号；`sequence_id` 是大写 PDB 加 entity 编号；`polymer_type` 是沉积聚合物类别；`sequence_class` 为本任务接受的 `protein/rna/dna`；`sequence` 为完整规范序列；`length` 为字符数；`label_asym_ids` 为链副本名列表；`comparable` 是既有去冗余比较资格，在本任务不作筛选。构造示例：

```json
{"pdb_id":"1abc","entity_id":"2","sequence_id":"1ABC_2","polymer_type":"polyribonucleotide","sequence_class":"rna","sequence":"AUXG","length":4,"label_asym_ids":["A"],"comparable":false}
```

`ignored_characters[*].index` 从零开始，指向对应 entity 的源 `sequence`，上述例子的 `X` 位于 2。这里只描述官方统一序列读取器的忽略规则，不宣称替代所有语言模型内部编码规则。未知或杂合类别报错，不静默删除实体。

### `command.json`

顶层为 `list[string]`，保存实际传给子进程的参数边界。包含解释器、`-u -m CryoAtom2 build`、解压图路径、输出目录、`cuda:0` 和实际存在的类别 FASTA 参数。使用 `shlex.join()` 可以还原可复制的 Bash 命令。

`.map.gz` 只在 `/storage/penghongen/tmp/cryoatom2/<Slurm Job 编号>/` 下解压，不改变图头、轴顺序或体素值；官方程序自行进行所需的重采样。每个 PDB 的解压临时目录在本次子进程结束后清理，因此复现 `command.json` 前须重新解压图文件。原始压缩图一直保留。

### `runs/<run_stamp>.json`

顶层为 JSON object，`split_file/data_root/sequence_catalog` 是三个输入位置；`pdb_ids` 是完整清单；`shard_index/shard_count` 是零起始分片编号和总数，如 `0/3` 表示读取清单位置 0、3、6。`release_root` 是实际运行项目副本；`job_id` 是 Slurm Job 编号字符串，非 Slurm 测试时可为 `null`。

`software.version` 是安装包版本，如 `2.1.1`；`software.package_root` 是实际包目录；`software.config` 完整保存官方 `config.json`，包括 `RUNet_args/CryoNet_args/HMM_search`；`software.weights` 为 `list[object]`，每项 `path` 是权重绝对位置、`size_bytes` 是文件大小。运行期间保持该 Conda 环境与官方权重不变；本程序不下载或修改模型。

配置快照中的字段保持官方名称和取值，当前已安装版本的含义如下。本程序只记录这些参数，不重新定义或调参。

| 配置字段 | 当前值 | 在官方程序中的用途 |
| --- | --- | --- |
| `RUNet_args.batch_size` | `4` | 每设备同时处理的小图数量 |
| `RUNet_args.stride` | `50` | 小图滑动步幅，单位为模型网格体素 |
| `RUNet_args.windows_size` | `65` | 小图边长，单位为模型网格体素 |
| `RUNet_args.ca_threshold` | `0.6` | 从蛋白 C-alpha 概率图取点的阈值 |
| `RUNet_args.p_threshold` | `0.465` | 从核酸 P 概率图取点的阈值 |
| `CryoNet_args.num_rounds` | `3` | 全原子重建轮数 |
| `CryoNet_args.repeat_per_residue` | `3` | 每轮对每个残基重复覆盖预测的目标次数 |
| `CryoNet_args.crop_length` | `300` | 单次局部重建所取的残基数量参数 |
| `CryoNet_args.aggressive_repeat` | `true` | 累计局部预测时提前使用末轮模式 |
| `CryoNet_args.raw_filter` | `false` | 不额外对 raw 结构执行链置信度过滤 |
| `CryoNet_args.filter_threshold` | `50` | 最终蛋白链平均预测置信度门槛；不表示物理 B 因子 |
| `CryoNet_args.mask_threshold` | `0.3` | 预测残基存在概率的保留门槛 |
| `CryoNet_args.seq_attention_batch_size` | `-1` | 非正值由官方 build 替换成 crop_length |
| `HMM_search.confidence_threshold` | `25` | 可选序列库搜索的置信度筛选参数 |
| `HMM_search.Evalue` | `1` | 可选序列库搜索的 E-value 门槛 |
| `HMM_search.cpus` | `4` | 可选序列库搜索的线程数 |

本任务没有提供额外 FASTA 数据库，因此不执行 `HMM_search` 对应的序列库搜索。

## 状态与统计

### `status.json` 和 `latest.json`

每个实际预测保存一份 `status.json`，同时将同一内容写到所属 PDB 的 `latest.json`。新执行使用新的 `run_stamp`，不覆盖旧尝试。重跑分片时，已有 success 且两份结构重新检查通过的 PDB 被跳过，其 latest 保持原执行身份。

| 字段 | 类型与含义 | 示例 |
| --- | --- | --- |
| `pdb_id/run_stamp` | string，样本与实际执行标识 | `9ter`、`predict_job123_20260908T160000_a1` |
| `status` | string，`running/success/failed` | `success` |
| `started_at_unix/finished_at_unix` | float，Unix 秒；未结束时后者为 null | `1788854400.0` |
| `elapsed_seconds` | float，包含解压、预测和检查的秒数；未结束为 null | `120.5` |
| `returncode` | int 或 null，子进程退出码；尚未执行或结束前失败为 null | `0`、`17` |
| `error` | string 或 null，失败原因；成功或进行中为 null | `RuntimeError: CryoAtom2 退出码 17` |
| `final_cif/raw_cif` | string，两份预期结构的绝对路径；失败时文件可能不存在 | 路径形状见目录树 |
| `cif_statistics` | object，成功时含 final/raw 两项；每项含 int atom_count/residue_count | `{"final":{"atom_count":100,"residue_count":20},"raw":{"atom_count":120,"residue_count":24}}` |

`running` 表示执行开始且未写出结束记录，不独立证明进程仍活着。整个作业异常终止时需结合 Slurm 日志判断并重跑；普通子进程非零退出会记为 failed 后继续其他 PDB。重试不会改用真实受体。

下面是字段齐全的成功状态构造示例；路径中的 `example_a1` 仅用于解释格式。开始到结束间隔与 elapsed_seconds 一致。

```json
{
  "pdb_id": "9ter",
  "run_stamp": "example_a1",
  "status": "success",
  "started_at_unix": 1788854400.0,
  "finished_at_unix": 1788854520.5,
  "elapsed_seconds": 120.5,
  "returncode": 0,
  "error": null,
  "final_cif": "/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/cryoatom2_artifact/9ter/example_a1/example_a1.cif",
  "raw_cif": "/storage/penghongen/Adaligand_infered_receptor_data/cryoatom2/test_0_chain06/cryoatom2_artifact/9ter/example_a1/example_a1_raw.cif",
  "cif_statistics": {"final":{"atom_count":100,"residue_count":20},"raw":{"atom_count":120,"residue_count":24}}
}
```

失败片段 `{"status":"failed","returncode":17,"error":"RuntimeError: CryoAtom2 退出码 17","cif_statistics":{}}` 省略了身份、时间和结构路径字段，表示尚未完成任何结构验收。若最终 CIF 通过而 raw CIF 验收失败，`cif_statistics` 可以仅含 `final`。这些状态仍算 failed，不能因存在部分统计或 CIF 就计为成功。

### `summary.json`

由显式汇总命令生成，不随数组任务并发覆写。`total` 为原始清单长度；`counts` 含 `pending/running/success/failed` 四个整数；`pdbs` 按清单顺序保存 `pdb_id/status/error/final_cif/raw_cif`。没有 latest 时为 pending、后三项为 null。成功结构会重新解析；复核失败仅在本汇总中改记 failed，不改旧 status。汇总表示运行命令当时的快照，不持续刷新。

构造示例：

```json
{"total":1,"counts":{"pending":1,"running":0,"success":0,"failed":0},"pdbs":[{"pdb_id":"9ter","status":"pending","error":null,"final_cif":null,"raw_cif":null}]}
```

### `slurm/`、`stdout.log` 与 `stderr.log`

逐 PDB 的两个文本日志保存官方进程输出。每次尝试结束后，程序还将官方输出目录中残留的 `.log` 文件迁入 `official_logs/`，保持相对目录；例如失败时的 `see_alpha_output/temp.log`。成功时已被官方删除的内部临时日志无法归档。Slurm 目录保存资源与发布证据，含具体 Job 的 out/err、动态命令和锁。使用已有[提交系统](../../训练与运行/README.md)，不创建第二套资源控制实现。after_hold 会在程序结束后保留 allocation；Slurm 显示 RUNNING 不等于预测仍在进行，需结合 try_lock 与状态判断。资源只按用户后续授权释放。

## 正式入口与代码阅读

从服务器项目根 `/home/penghongen/My_Project/AdaLigand` 执行唯一正式提交命令：

```bash
bash 测评数据代码/cryoatom2原始预测结构/submit.sh
```

该入口创建 3 个数组任务，每个 1 张 A100、8 核 CPU、96 GiB 内存，使用 `--after_hold`，不传 `--time`。显式请求内存使单卡任务可以共享节点，不使用分区默认的整节点内存。线程池设置为 8 核，不按系统总 CPU 数放大。Slurm 数组编号 0、1、2 分别决定 PDB 分片，每个分片顺序运行。

阅读顺序：`submit.sh` 说明资源；`sh/predict.sh` 说明环境与输入位置；`predict.py` 的两个内部工具说明 JSON 发布与 CIF 基本检查，随后 `run_shard()` 贯穿单卡运行，`summarize()` 汇总全测试集；`tests/test_predict.py` 用文件与子进程替身覆盖失败、重试和格式验收。

测试、门控及汇总命令和实际运行事件分别记录在[执行记录](../../文档/exec_plan/CryoAtom2测试集受体重建执行记录.md)，不拼入正式提交命令。
