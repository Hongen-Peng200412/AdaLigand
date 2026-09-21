# Stage1 七模式 PyMOL 合并会话

## 文档责任

本文定义 `test_0` 的 Stage1 七模式 PyMOL 合并会话、候选排序、输出组织和验收边界。对象名、交互命令及正式入口由 `可视化套件/Stage1/README.md` 说明；实施、服务器 Job、release、launch 和验收事实由 `文档/exec_plan/Stage1_PyMOL可视化实施.md` 记录。本文不改变 AdaLigand 数据契约、Pocket Plus 推理契约或正式评估结果。

## 目标与范围

为 `test_0` 的 179 个 PDB 各生成一个自包含 `.pse`。每个会话共享一份完整实验密度和 GT，并同时包含以下七种模式：

1. `unet_c1` pdb-centric-v2 / F1-F1 basic。
2. `unet_c1` pdb-centric-v2 / F2-F1 basic。
3. `Find_1` / 真实受体 / F1-F1 basic。
4. `Find_1` / 真实受体 / F2-F1 Gaussian。
5. `Find_1` / CryoAtom2 受体 / F1-F1 basic。
6. `Find_1` / CryoAtom2 受体 / F2-F1 Gaussian。
7. Emap2lig / official Find-Li。

`test_1` 是 `test_0` 的子集，不重复生成会话。正式 Stage1 输入始终只读。

## 会话契约

- 只使用 `density`、`receptors`、`ground_truth` 和七个 `pred_*` 平级组，不建立外层 `stage1`。
- `receptors` 直接包含可独立显隐的真实受体和 CryoAtom2 受体。
- 七个命名 scene 各自只启用相应预测组，以及该方法实际使用的受体；无受体方法不在 scene 中显示受体。
- 首次打开时显示密度 mesh、GT 与真实受体，隐藏密度 map、CryoAtom2 受体和所有预测组。
- Pocket Plus 写入当前 evaluation 中的全部候选，组内默认显隐继续由 `candidate_selected` 决定。
- Emap2lig 默认按 rank 写入前 100 个实例，同时支持显式写入全部实例；运行清单保存截断前总数和实际装入数。
- 会话保留完整实验密度 map，允许调整 `isolevel` 或围绕任意 GT、受体与预测对象创建局部密度 mesh。

## 排序契约

默认 `rank_by=probability_mean`，七种模式均按 `source_probability_mean` 降序稳定排序。选择 `rank_by=gaussian` 时，只有两个 F2-F1 Gaussian 模式改按其 evaluation `candidate_score` 排序，其余模式仍使用源概率均值。同分保持 evaluation 原始顺序。

排序只改变对象顺序、名称和 state title 中的 rank，不改变候选集合、`candidate_selected` 或正式评估指标。state title 同时保存源 blob 编号、源概率均值、evaluation/Gaussian 分数及正式入选状态。

## 输入与输出

固定路径、producer、F-alpha、evaluation 名和受体来源由独立 profile 指定。正式归一化读取入口只隔离 Pocket Plus `blobs + evaluation` 与 Emap2lig `official_blobs + per_pdb evaluation` 两种盘上格式，不按模型名猜测字段或路径。

正式服务器输出为：

```text
/storage/penghongen/AdaLigand_stage1_visualization/stage1_7mode_pcv2_test0_probability_mean/
├── sessions/<pdb_id>.pse
├── manifest.jsonl
└── run_summary.json
```

完整结果续传到 `D:\AdaLigand_Stage1_PyMOL\stage1_7mode_pcv2_test0_probability_mean\`。下载前，目标盘可用空间必须至少为服务器实际输出大小加 50 GiB。

## 生成与续跑

- 保存前启用 `pse_binary_dump` 和 PyMOL 内部 session compression。
- 每个 `.pse` 先写同目录临时文件，再通过原子替换发布。
- 批量生成使用 16 个独立进程；每个子进程只处理一个 PDB，避免共享 PyMOL 全局状态。
- 重启只复用已经原子发布、具备清单记录且排序与截断配置一致的最终文件。
- 下载使用可续传、无删除行为的 MSYS2 `rsync` 入口，凭据只读取本机私有密码文件。

## 验收条件

1. 单元测试覆盖两种盘上格式、F1/F2 basic 和 Gaussian 字段、两种 rank 的顺序差异、候选与 `candidate_selected` 不变、Emap2lig Top 100/`all`、平级分组、两个受体、七个 scene、默认无预测、世界坐标及压缩会话回载。
2. 服务器 PyMOL 3.1.0 先生成 `9hjx`，Windows PyMOL 3.1.6.1 能直接加载并保持对象组与 scene。
3. 全量输出恰为 179 个成功会话；七种 Pocket Plus 候选数与源 evaluation 一致，Emap2lig 装入数为 `min(100,N)`。
4. 抽查 `9hjx`、最大密度样本 `11jb` 和 Emap2lig 最大预测体素样本 `30yu` 的对象、scene、默认画面与坐标。
5. 生成前后 Stage1 probability、blobs、evaluation 和数据源文件大小、修改时间不变。
6. 服务器与 Windows 本地的 179 个会话 SHA-256 清单逐项一致。

## 非目标

本轮不增加 PyMOL GUI 插件，不加载模拟或差分密度，不恢复嵌套分组，不生成 GT 体素掩码，不把预测 blob 解释成化学结构，也不重新运行 Stage1 推理或评估。

## 2026-09-22 实施回填

七模式 `test_0` 已按本文契约生成并验收 179/179 个会话。正式服务器根为 `/storage/penghongen/AdaLigand_stage1_visualization/stage1_7mode_pcv2_test0_probability_mean`，本地完整副本为 `D:\AdaLigand_Stage1_PyMOL\stage1_7mode_pcv2_test0_probability_mean`。服务器与本地 179 个 `.pse` 的 SHA-256 逐项一致。

实际最后一轮使用用户指定的 A800 Job `379402_0`，该 allocation 提供 16 CPU，因此批量入口使用 8 个独立 worker，而不是最初为 32 CPU 资源拟定的 16 个 worker。剩余 178 个原子发布会话被复用，只生成缺失的 `9gjg`；该调整不改变任何会话内容或科学契约。

真实运行发现，在 Lustre 内存映射上直接把 `(Z,Y,X)` 密度转为 XYZ 连续数组会产生跨页次序读取。`load_density()` 已改为先按 ZYX 连续顺序读入内存，再执行相同转置；六项合同测试、三项独立窄复核、四个代表会话的服务器回载、10,173 个来源文件只读核验和完整 SHA-256 门控均通过。完整命令、release、launch、阻塞诊断和验收数字见 `文档/exec_plan/Stage1_PyMOL可视化实施.md`。
