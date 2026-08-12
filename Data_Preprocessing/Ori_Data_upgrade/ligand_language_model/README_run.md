# 配体语言模型运行说明

本文给出正式运行的顺序和可直接复制的命令。所有命令都由用户手动执行；代码不会自动提交下一阶段，也不会自动决定产物是否发布。

PDB 是一份生物大分子三维结构记录；occurrence 是一个 PDB 中的一次配体出现，由
`(pdb_id, candidate_id)` 唯一标识；SMILES 是用一行字符表示分子原子、化学键、分支和
电荷的文本。CPU 阶段先为每个 occurrence 写出 prepared SMILES，即实际准备交给模型的
字符串；GPU 阶段用 tokenizer 把 SMILES 拆成模型词表片段并转换成编号。batch 是模型
一次共同计算的一组 occurrence。成功结果写成 NPZ，即按名称保存多个 NumPy 数组的压缩
文件；本管线的 NPZ 只含分子级 `float32 (768,)` 向量及其身份，不含词表片段级向量。

以下命令默认处理 `all_existing`。若只处理 `all_valid.json` 内的 PDB，把命令末尾的 `all_existing` 改成 `all_valid`。

## 1. 核对稳定离线环境

正式 GPU 脚本只从
`/storage/penghongen/AdaLigand/model_weights/ligand_language_models` 读取模型权重和
补充 Python 包。CPU 准备与汇总使用
`/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python`；两个 GPU 入口使用
`/home/penghongen/anaconda3/envs/Pocket_Plus_centos7_cu121_allgpu/bin/python`，该环境提供
PyTorch `2.4.1+cu121`。提交 CPU 或
GPU 任务前，在服务器 shell 中执行：

```bash
set -euo pipefail

stable=/storage/penghongen/AdaLigand/model_weights/ligand_language_models
cpu_python=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python
gpu_python=/home/penghongen/anaconda3/envs/Pocket_Plus_centos7_cu121_allgpu/bin/python

test -x "$cpu_python"
test -x "$gpu_python"
test -d "$stable/models/molformer"
test -f "$stable/models/smi_ted_289m/smi-ted/inference/smi_ted_light/load.py"
test -f "$stable/models/smi_ted_289m/smi-ted-Light_40.pt"
test -f "$stable/models/smi_ted_289m/bert_vocab_curated.txt"
test -d "$stable/runtime/molformer"
test -d "$stable/runtime/smi_ted_289m/common"
test -d "$stable/runtime/smi_ted_289m/transformers4"

"$cpu_python" -c 'import gemmi, numpy, pdbeccdutils, rdkit'
"$gpu_python" -c 'import torch; assert torch.__version__ == "2.4.1+cu121"'
```

上述命令只核对正式脚本依赖的稳定位置，不启动 CPU 或 GPU 任务。正式脚本在服务器
运行时启用离线模式，不会联网下载权重。稳定位置尚未建立时，先按
[项目执行记录中的一次性迁移说明](../../../文档/exec_plan/AdaLigand_v3基础数据升级实施.md)
准备权重与依赖；该迁移不属于每轮都要重复的正式运行步骤。

## 2. 提交 CPU SMILES 准备

在服务器项目根目录执行：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/prepare_smiles.sh \
  --resource cpu \
  --array 0-11 \
  --cpus 8 \
  --mem 768G \
  -- all_existing
```

数组必须从 0 开始且连续。十二个数组任务先在全局 PDB 列表上分片，每个任务再使用八个进程；一个进程始终独占一个 PDB。

CPU 数组全部结束后，提交 prepared 汇总：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/summarize_outputs.sh \
  --resource cpu \
  -- prepared all_existing
```

先由用户核验 `prepared/reports/final_summary.json`、分片报告和需要抽查的 `prepared_smiles.jsonl`，再决定是否进入 GPU 阶段。

## 3. 提交 SMI-TED Light 289M

以下命令使用四个独立数组任务，每个任务占一张 A100：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_smi_ted.sh \
  --resource a100 \
  --gpus 1 \
  --array 0-3 \
  -- all_existing
```

每个数组任务先用官方 `normalize_smiles` 记录规范化事实。得到非空规范字符串的 occurrence
组成一个完整跨 PDB 列表：列表不少于 100 项时向官方 `model.encode` 传入
`batch_size=100`，少于 100 项时传入实际项数；冻结的官方源码再自行分块，实际内部批量
可能超过传入值。官方规范化返回空值或异常的 occurrence 不被筛掉，仍以
`batch_size=1` 逐条调用公开接口，避免官方产生的 `None` 让 tokenizer 拒绝整个有效列表。
规范化成功组的全局调用若发生普通异常，也逐 occurrence 重试。

SMI-TED 数组全部结束后提交汇总：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/summarize_outputs.sh \
  --resource cpu \
  -- smi_ted_289m all_existing
```

## 4. 提交 MoLFormer

SMI-TED 产物通过用户验收后，再提交四个独立 MoLFormer A100 数组任务：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_molformer.sh \
  --resource a100 \
  --gpus 1 \
  --array 0-3 \
  -- all_existing
```

每个数组任务将自己负责的全部 occurrence 跨 PDB 展平，再按最多 256 项调用一次
MoLFormer batch；batch 边界不按 PDB 切分。模型加载显式使用官方特征提取示例的
`deterministic_eval=True`：同一 SMILES 不会因为前向次数、batch 边界或逐 occurrence
重试而重新抽取随机特征映射权重。

MoLFormer 数组全部结束后提交汇总：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/summarize_outputs.sh \
  --resource cpu \
  -- molformer all_existing
```

两套模型在数据上互不依赖；正式运行顺序固定为 SMI-TED 验收后再运行 MoLFormer，
避免同时占用 GPU 并便于逐阶段核验。

## 5. 显式覆盖重算

CPU 或任一模型脚本的第二个位置参数可以是 `--overwrite`：

```bash
bash 训练与运行/submit_task.sh \
  --sh Data_Preprocessing/Ori_Data_upgrade/ligand_language_model/encode_molformer.sh \
  --resource a100 \
  --gpus 1 \
  --array 0-3 \
  -- all_existing --overwrite
```

不提供 `--overwrite` 时，逐 PDB 完成文件已经存在的样本会被跳过。模型阶段覆盖重算或发现上次只有未完成 NPZ 时，会先删除该 PDB 的旧 `candidate_*.npz`，防止旧向量与新状态混在一起。

汇总脚本没有覆盖参数；它每次重新扫描正式逐 PDB 文件，并原子替换对应的 `reports/final_summary.json`。

## 6. 正式产物位置

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2/ligand_language_models
```

三个需要分别验收的汇总文件是：

```text
prepared/reports/final_summary.json
molformer/reports/final_summary.json
smi_ted_289m/reports/final_summary.json
```

字段解释见 [产物字段参考.md](产物字段参考.md)，处理逻辑见 [README.md](README.md)。
