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
- [ ] Pocket_Plus 与 AdaLigand 双线历史完成等价核验。
- [ ] probability 复制和两项正式 CPU 作业提交完成。
- [ ] calibration/validation 正式产物与 macro 指标完成验收。
- [ ] BOX 契约、执行记录、映射索引和 handoff 完成收口。

本节只在出现明确事件时更新，不记录固定间隔的监视流水账。
