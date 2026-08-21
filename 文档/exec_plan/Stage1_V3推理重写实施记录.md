# Stage1 V3 推理重写实施记录

本文记录 Pocket Plus Stage1 V3 推理主线的实现、验证、独立审查和双线 Git 收口证据。当前规格是 Pocket Plus `talk/refactor/stage1_v3_inference.md`，跨项目字段权威是 AdaLigand `文档/规划文档/BOX-level数据契约.md`。本记录保存已经发生的过程与证据，不替代两份当前规格。

## 本轮覆盖范围

2026-08-21，用户批准把上一版固定 F1/F3 的 `calibrate/run` 改为五个可独立提交的阶段：

1. `probability` 生成完整图概率。
2. `blobs` 拟合或读取一个正浮点 alpha 的语义阈值，并生成 `F{alpha}_blobs.npz`。
3. `centered` 从 blobs 生成 `F{alpha}_centered.npz`，或用 score-only 只更新 `score/selected`。
4. `tune` 从 blobs 调整 basic 选择参数，或从 centered 调整 Gaussian 选择参数。
5. `evaluate` 独立评估 blobs 或 centered。

本轮不修改 Stage1 Dataset、训练代码、模型定义或 Matcher，不提交服务器正式推理任务。完整图配体概率继续不乘受体 hardmask。

## Git 共同基点

首次正式写入前完成只读检查：

| 仓库 | 共同基点 | 实现分支 | 开始状态 |
| --- | --- | --- | --- |
| Pocket Plus | `Learn/CUMULATIVE@916dced93b5c0f19418ddba0077f5504faa1ffd7` | `codex/stage1-inference-falpha` | 工作区干净；该提交是全部本地、远端跟踪引用和登记 worktree 按提交者时间形成的唯一最新提交 |
| AdaLigand | `Learn/CUMULATIVE@4bce2a38f0aba721b7f582e21aa59a862933cd79` | `codex/stage1-inference-falpha-contracts` | 工作区干净；该提交是全部本地引用和登记 worktree 按提交者时间形成的唯一最新提交 |

未修改或推送远端引用。

## 已完成实现事件

### 五阶段入口与动态路径

Pocket Plus `src/inference/workflow.py` 已从活动树删除。`src/inference/pipeline.py` 直接提供五个 `run_*_stage()` 入口，`src/inference/cli.py` 只解析参数、读取 JSON 清单，并在 probability 或正常 centered 阶段恢复 wrapper 与构造 Dataset。

`src/inference/artifacts.py::f_alpha_tag()` 把 2.0、0.5、1.5 分别编码为 `F2`、`F0p5`、`F1p5`。同一 `output_root` 可以复用 probability，并逐次增加多个 alpha 的 blobs 和 centered。正式代码不计算 checkpoint、配置或代码摘要，不建立 `_valid*` 身份层。

PDB 清单改为顶层字符串列表 JSON。可分片生产阶段使用固定 seed 3407 打乱完整列表，再按 `[shard_index::shard_count]` 选择 0-based 分片；语义拟合、tune 与 evaluate 不分片。

### centered 字段与评分边界

所有 producer 都执行完整 forward 并保存 `voxel_final`。`unet_*` 只保存共同字段与 V 特征；`Find_*` 另外保存 auxiliary、A/P 和三张 float32 48³ 稠密数组。alpha 不再决定前向模式或字段集合。

`forward_min_voxels` 只决定哪些 `fits_centered_box=true` 的来源 blob 进入 GPU。选择 JSON 中的 `min_voxels` 只决定 `selected`。未评分 centered 不含 `score/selected`；score-only 只增加或替换这两个数组。

basic tune 使用全部 blobs，包括 `fits_centered_box=false` 的区域。Gaussian tune 继续使用 A 原子 5 Å 截断分数，并保留粗搜索、细搜索和最终最小体素数三个阶段。alpha 与 `objective_beta` 独立，配置推荐值均为 2.0。

### 最小 `_BLOB_EXCEED` 改正

用户在计划批准后补充最小规则：centered 开始时，若来源 blobs 的 `blob_index` 长度严格大于全局常量 1000，立即写 `status/F{alpha}_centered/_BLOB_EXCEED` 并跳过当前 PDB。

实现只保存 `pdb_id`、`centered_role`、`source_blob_count` 和 `limit`。没有新增覆盖、恢复、自动删除、独立完成标记或重试状态机。tune/evaluate 只在原本清单读取位置识别该原因并输出说明。

### 配置与文档

`configs/inference/stage1_v3.yaml` 删除固定 `roles`、`blob_limit`、`forward` 和保存开关，增加通用 `alpha`、`objective_beta`、Gaussian 网格和 centered 共同并行参数；`stride_zyx` 从 `[50,50,50]` 改为 `[30,30,30]`。

三份 Human MD Review 源 README 已按批注重写：

- Pocket Plus `训练与运行/sh/infer/README.md`
- Pocket Plus `configs/inference/README.md`
- Pocket Plus `src/inference/README.md`

AdaLigand `文档/规划文档/BOX-level数据契约.md` 的推理章节已整体替换为通用 F-alpha 当前契约；旧固定 F1/F3 字段和 calibration 身份规则不留在活动契约中。

### tune 前固定体素数门槛

2026-08-22，用户补充 `prefiltered_min_voxel`：`tune` 命令必须显式提供该整数，basic 与 Gaussian 在尝试任何评分或选择参数前共同固定该门槛。体素数不足的候选不从 PDB 事实中删除，而是在全部参数组合中保持未入选；真实 occurrence 因此仍可贡献 FN。

选择 JSON 分别保存固定 `prefiltered_min_voxel` 和搜索所得 `min_voxels`。两者互不限制：即使前者大于配置列表中的某些后者，也只会产生冗余参数尝试，不构成契约错误。centered 首次评分、score-only 与 evaluate 同时应用分数阈值和两个体素数门槛。

### 显式评估变体

2026-08-23，用户要求同一候选产物能够同时保留未经过二次打分的对照评估和一组或多组参数过滤评估。`evaluate` 因此增加必填 `evaluation_name`，并要求 `--selection-parameters` 与 `--all-candidates` 二选一。

参数过滤路径沿用既有 basic/Gaussian 重打分和三个选择门槛。全候选路径不调用评分函数，直接使用 `source_probability_mean` 排序并把当前 blobs 或 centered 产物中的全部候选设为已选。该改动没有增加评分产物副本、身份校验或摘要；每 PDB NPZ、数据划分 JSONL 和 metrics JSON 只以用户给出的名称区分并存结果。

同一次收口把用户已经在主工作树更新的推理 batch 配置融入原有配置历史：A800/H100 的完整图窗口 batch 为 16、centered batch 为 8；A100 对应值分别为 8 和 4。YAML 当前正式值按 A800/H100 写为 16 和 8，README 同时说明两类 GPU 的取值。

## 当前验证证据

改写前基线：

```text
python -m pytest tests/inference tests/datasets/test_stage1_dataset.py -q
30 passed in 12.15s
```

五阶段核心代码、动态路径、分片、score-only 和 `_BLOB_EXCEED` 测试加入后的阶段性回归：

```text
python -m pytest tests/inference tests/datasets/test_stage1_dataset.py -q
33 passed in 5.44s
```

主代理完成逐文件逐函数自查并补齐 Docstring、注释、测试端点和 centered Find 分支早返回后的当前回归：

```text
python -m pytest tests/inference/test_stage1_v3.py tests/datasets/test_stage1_dataset.py -q
33 passed in 9.14s

python -m pytest tests/inference/test_stage1_cuda.py -q
2 passed in 7.68s
```

Windows RTX CUDA smoke 同时覆盖 probability 与 centered。新增 centered smoke 发现 `voxel_final` 在 NumPy 高级索引后已经是 `(K_source,C_voxel)`，旧代码再次转置会错误保存为 `(C_voxel,K_source)`；实现已删除该多余转置，并在 CPU 与 CUDA 测试中同时断言正式 shape。`src/inference` 已通过 `compileall`；OmegaConf 能解析新 YAML，读取到 `alpha=2.0` 与 `stride_zyx=[30,30,30]`；五个 CLI 子命令的 `--help` 均正常；MSYS2 Bash 对 `训练与运行/sh/infer/stage1_v3.sh` 的语法检查通过；Black 格式检查与两个仓库的 `git diff --check` 通过。

第二轮独立审查发现 SciPy `cKDTree.query(distance_upper_bound=...)` 对上界采用严格小于，导致恰好 5 Å 的 Gaussian A 原子和恰好 10 Å 的 Find centered A 原子被排除。正式实现改为先查询最近距离，再分别显式应用 `distance <= 5.0` 与 `distance <= 10.0`；没有增加包装层或校验框架。两个端点都进入真实科学路径测试，修订后的当前回归为：

```text
python -m pytest tests/inference/test_stage1_v3.py tests/datasets/test_stage1_dataset.py -q
34 passed in 3.44s

python -m pytest tests/inference/test_stage1_cuda.py -q
2 passed in 2.79s
```

`prefiltered_min_voxel` 与主工作树 batch 参数融入后的回归为：

```text
python -m pytest tests/inference/test_stage1_v3.py tests/datasets/test_stage1_dataset.py -q
35 passed in 4.01s

python -m pytest tests/inference/test_stage1_cuda.py -q
2 passed in 3.40s
```

同一端点通过 `src/inference` 与 `tests/inference` 编译检查、五个 CLI 子命令帮助、OmegaConf 解析和 `git diff --check`。OmegaConf 实际读取 `window.batch_size=16`、`centered.batch_size=8`。当前 Windows 环境没有安装 Black，因此本次没有追加伪造的 Black 结果；修改函数已经由主代理按文件与调用顺序逐一检查职责、位置、嵌套、Docstring 和行内注释。

显式评估名称与全候选模式加入后的 2026-08-23 回归为：

```text
python -m pytest tests/inference/test_stage1_v3.py tests/datasets/test_stage1_dataset.py -q
37 passed in 4.78s

python -m pytest tests/inference/test_stage1_cuda.py -q
2 passed in 3.45s
```

同一端点再次通过 `src/inference` 与 `tests/inference` 编译检查、evaluate CLI 帮助和两个仓库的 `git diff --check`。帮助文本明确显示 `--evaluation-name` 必填，并要求 `--selection-parameters` 与 `--all-candidates` 二选一。主代理按文件顺序复核了本轮涉及的类、正式函数、测试函数和两个测试回调，没有新增包装函数或评分身份机制。

## 独立审查结论

布局/Git、注释/文档与逻辑三类独立审查都完成了三轮全面只读核查。第三轮之后，各审查者只复核自己已经报告的问题，不再扩大范围；三份窄口径复核最终均为 `APPROVED`。

审查过程中修正的实质问题只有两项：centered `voxel_final` 的候选轴与通道轴曾被多余转置，以及 SciPy 最近邻上界曾漏掉恰好 5 Å/10 Å 的端点。其余修订是函数位置、嵌套、Docstring、字段名、shape/dtype/坐标、README 自包含性与验证记录对齐。正式代码没有增加 SHA、`_valid*`、身份框架或扩展 `_BLOB_EXCEED` 状态机。

主代理自查逐项记录在 Pocket Plus `talk/refactor/stage1_v3_inference.md`。本次检查覆盖所有新增或修改的正式函数、局部线程回调、测试函数和测试内最小假对象；`centered.py:arrange_batch()` 使用 U-Net 早 `continue`，把 Find 专用 48³、A/P 和 auxiliary 整理从两层条件块改成顺序代码，没有增加顶层包装函数。

## 计划与实现差异

### 有益差异

- 用户在原计划上补充来源 blob 总数严格大于 1000 的 centered 跳过规则；实现采用单一全局常量和单一原因标记，没有恢复状态机。
- basic tune 直接使用全部 blobs，因此不需要为了 `fits_centered_box` 建立第二个候选筛选路径。
- 主代理自查时补充端点两侧测试：1000 个来源 blob 继续生成空候选 centered，1001 个来源 blob 只写 `_BLOB_EXCEED`。
- 第 1 轮逻辑审查要求补充 centered 真实 CUDA 证据；新增测试随即发现并修复 `voxel_final` 来源体素轴与通道轴颠倒问题。
- 后续 `prefiltered_min_voxel` 没有裁剪候选 ragged 数组或建立适配层，只在既有校准事实增加一个布尔候选轴，并在三个既有 `selected` 写入位置并列应用固定预过滤与最终 `min_voxels`。

### 中性差异

- 上一版 `pipeline.py` 只承担单 PDB 发布；删除 `workflow.py` 后，`pipeline.py` 直接承担五个跨 PDB 阶段。科学核函数仍位于原有模块。

### 有害差异

当前阶段未发现。

### 未完成范围

- 重建 Pocket Plus 与 AdaLigand 学习线，验证实现端点与学习端点等价，并快进两个 `Learn/CUMULATIVE`。
- 写最终 CLAUDE handoff；不在本任务启动服务器正式推理。

本记录只在实现冻结、审查结论、Git 端点或正式运行等明确事件后更新，不保存逐命令流水账。
