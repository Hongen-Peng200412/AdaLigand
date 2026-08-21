# Stage1 V3 推理重写实施记录

本文记录 Pocket Plus 中 Stage1 V3 推理主线的实现、验证和收口证据。规划规格位于 `C:\Users\15919\Desktop\Pocket_Plus\talk\refactor\stage1_v3_inference.md`，字段权威位于 `C:\Users\15919\Desktop\AdaLigand\文档\规划文档\BOX-level数据契约.md`。

## 范围

本轮删除活动代码树中的旧 Selector、组件森林、CLG、Li 和多 Fα 推理入口，重新建立四个 producer 共用的单一主线：

- `unet_c1`、`Find_0`、`Find_1`、`Find_2` 均生产 F1 basic 与 F3 centered。
- F1 basic 使用语义 micro-F1 阈值和最终 F1 选择目标。
- F3 centered 使用语义 micro-F3 阈值和最终 F2 选择目标；Find 使用 A 原子 Gaussian 分数，U-Net 使用来源概率均值。
- 四个 producer 的配体概率均不乘受体 hardmask。
- Matcher 首先消费 `F3_centered.npz`；F1 basic 是便捷推理产物。

本轮不提交服务器正式推理任务，也不修改 Matcher。真实 checkpoint 的全链运行必须在模型产物确定后由用户另行授权。

## 关键实现事件

### 单一生产入口

Pocket Plus 新主线位于 `src/inference/`，由 `训练与运行/sh/infer/stage1_v3.sh` 调用 `python -m src.inference.cli`。CLI 只解析 `calibrate` 或 `run` 子命令、显式路径并构造 Dataset 与 wrapper；跨 PDB 编排位于 `workflow.py`，单 PDB 发布事务位于 `pipeline.py`。

模型代码来源必须显式选择 `current_workspace` 或 `training_snapshot`。训练 resolved config 负责模型结构，当前 V3 Dataset 始终来自活动代码。2026-08-20 的可读性重做删除了 checkpoint、resolved config 与推理配置摘要；calibration 只保存 checkpoint 的规范化绝对路径。同一 checkpoint 的不同 F3/F2 目标或其他科学配置使用不同的显式 `output_root` 版本目录。

本次重做不迁移 `src/inference/` 的文件，不新增承载 Dataset、collator、wrapper、blobs 与保存开关的顶层包装函数。代码只删除一次转发、写后重复读取和摘要计算，保留线程回调、惰性生成器与原子发布事务所必需的局部函数。公开入口、科学数组和文件读写 Docstring 按字段、dtype、shape、坐标和 offsets 对齐补全。

### GPU 与 CPU 重叠

完整图阶段在唯一 GPU owner 线程中执行 H2D、前向和 D2H；CPU 线程提前物化窗口并按提交顺序融合。一个 PDB 的完整概率离开 GPU 后，概率 NPZ 压缩与 F1/F3 26 邻域连通区域提取并行执行，GPU 开始下一 PDB。

centered 阶段同样提前物化 batch，异步复制 GPU 输出并在 CPU 整理。一个 PDB 的字段齐备后，concatenate 与 NPZ 压缩进入发布线程，GPU 开始下一 PDB。两个 PDB 级待发布队列限制大数组常驻数量。

推理线程共享同一 V3 Dataset 与 mmap LRU。缓存只在 OrderedDict 和字节计数更新期间持有可重入锁，实际 NPY 裁块与密度通道构造不在锁内。

### 科学与发布收口

概率科学 NPZ 精确保留概率和世界几何三字段；窗口几何与性能分别写 JSON。blob 阶段保存阈值下全部 26 邻域连通区域，不提前应用 `min_voxels`。F3 候选数严格超出 `blob_limit` 时只写 `_BLOB_EXCEED` 事实并继续生产，不再保留跳过 PDB 的特殊终态。

F1 basic 显式关闭 V 学习特征、A/P、辅助受体概率和 48³ 稠密数组。F3 centered 保存 V 特征与三张 float32 48³ 数组；Find 另外保存 A/P 表。`A_feat_L0` 为 49 维基础特征与 `is_backbone` 拼接后的 float32 50 维数组，上游 `receptor_tokens.npz` 不改写。

大型 NPZ 使用同目录临时文件和 `os.replace` 原子发布，不再执行压缩后立即完整解压重读。读取调用点只解压明确消费的字段。第二轮审查后，冻结 `score/selected` 改为在 centered 第一次正式压缩前写入；validation/train 不再为了两个一维字段完整解压并二次压缩 F3，calibration 在最终 `min_voxels` 冻结后重新生成正式候选集合。

## 审查与验证证据

上一轮三类独立全面审查分别覆盖 Git/布局/函数边界、注释与 Docstring、科学逻辑与用户契约。审查发现并已修订的阻断包括：巨型 CLI、全 train 概率常驻内存、跨阶段不重叠、BF16 直接进入 NumPy、共享缓存竞争、不可执行的校准搜索、缺少 `centered_box_index`、偏斜 blob 的 BOX 判定错误、macro 与逐候选事实不完整、calibration 完成标记不完整，以及科学 NPZ 混入性能字段。

本地最终验证为：

- `tests/inference` 与 `tests/datasets/test_stage1_dataset.py`：可读性重做后 28 项通过；删除的单项只覆盖已内联且由发布事务测试继续覆盖的 `selected` 字段包装。RTX 4060 CUDA smoke 仍覆盖 125 个真实 Conv3d 窗口。
- Python `compileall`：通过。
- `git diff --check`：通过。
- CLI `--help`、OmegaConf 配置解析和 `stage1_v3.sh` Bash 语法：通过。
- 一次合成 CUDA 利用率采样：19 个样本，GPU active ratio 0.6842，平均利用率 13.947%，P50 7%，P95 36%，墙钟 3.029 秒。该结果只证明采样工具和 CUDA 流水可执行，不替代真实 checkpoint 性能基准。

`08f30f2` 之前的端点完成过两轮全面检查，但该批准不自动覆盖本次可读性重做。新的工作区端点在代码、文档和测试冻结后，重新接受布局/Git/函数、注释与 Docstring、科学逻辑与用户契约三类独立审查；每类执行三轮全面核查，之后只复核已报告问题。

2026-08-20，主代理在暂停独立审查后重新逐名检查 `src/inference/` 的 48 个类、方法、顶层函数和局部回调。检查逐项记录在 Pocket Plus `talk/refactor/stage1_v3_inference.md` 的“主代理逐函数自查”表中，覆盖函数保留理由、冷端工具与主流程顺序、局部嵌套必要性、输入输出、数组形状、坐标、offsets、副作用和产物字段。检查期间没有新增包装层、哈希、`_valid*` 校验函数或 calibration 目录相等限制；冻结运行中两个先赋 `None` 再立即覆盖的状态和相应无效分支已经删除。此前提前启动后被中断的第三轮不计入三轮独立核查，真正的第三轮只在本次主代理自查与验证完成后重新开始。

本次主代理自查后的验证结果为：13 个正式推理 Python 文件通过现有 Black 格式检查且无需改写；`src/inference` 与 GPU 基准工具通过 `compileall`；`tests/inference` 与 `tests/datasets/test_stage1_dataset.py` 共 28 项通过；CLI 三个帮助入口、OmegaConf 配置解析和 `stage1_v3.sh` 的 Bash 语法通过；每个正式模块只有一条规定分隔线，源码没有中文标点、SHA/摘要字段或 `_valid*` 函数，`git diff --check` 没有空白错误。

真正的第 3/3 轮在上述主代理自查和验证之后执行。布局/Git/函数审查补齐跨模块入口表并统一推荐阅读顺序后批准，确认 48 个代码对象、9 个必要局部回调和每个模块唯一分隔线保持不变。科学逻辑审查只发现 `save_dense48=false` 时仍解压完整概率图的冗余 I/O；`produce_centered_role` 已改为只读取 `origin_xyz` 与 `voxel_size_xyz` 并显式传入 `full_probability=None`，现有测试覆盖该分支，窄口径复核批准。注释与文档审查逐项要求补齐嵌套配置、offsets 切分对象、Gaussian 参数、评估动态键、benchmark 对照字段和 BOX 契约；全部原问题经过两次窄口径复核后批准。三类审查均未要求新增包装层、身份对象或防御性校验。

双线共同基点为 `3cbae636f444fb6630eb505d210d7ce0586b4f76`。实现分支 `codex/stage1-inference-v3` 的科学代码端点为 `bdecd9802fdef4dcc28401411b35f31a72e5a3cc`；学习线的科学代码等价节点为 `c62de259f48da4f04962d4b68658a76a6afbafbe`，两端 tree 均为 `226b56e7ed34b44545af6236afba4653caac32b9`。学习线随后只追加最终验证与 handoff 文档，当前 `Learn/stage1-inference-v3` 和 `Learn/CUMULATIVE` 均指向 `08f30f28439925b272a11e8e3d1682b5076229ba`；与实现端点的差异仅为五个不参与运行的 Markdown/CLAUDE 记忆文件，Python、YAML 和 Shell 均无差异。该提交是仓库按提交者时间形成的唯一最新提交。

## 当前状态与剩余边界

上一轮累计学习端点为 `08f30f28439925b272a11e8e3d1682b5076229ba`。本次可读性重做的真实实现端点为 `b1294e898fdbac91951653e1ede7c3db5f75a2c4`。学习历史没有在 `08f30f2` 后追加补丁提交，而是从 `3cbae636f444fb6630eb505d210d7ce0586b4f76` 重新构造原有 8 个主题提交；新的 `Learn/stage1-inference-v3` 与 `Learn/CUMULATIVE` 均指向 `da4769991b50d3ae0a20a2f65188ef67d544c1a7`。实现端点和学习端点的 tree 都是 `db5575721a272ce682e5ce585720ede598a523bb`，`git diff --quiet` 返回 0。重建后的端点再次通过 Black、`compileall`、28 项回归、三个 CLI 帮助入口、OmegaConf 解析、Bash 语法和 `git diff --check`。最终 handoff 为 Pocket Plus `CLAUDE/memory/handoffs/2026-08-20-stage1-v3-inference-readability-rebuild.md`。`Learn/CUMULATIVE` 是本地分支按提交者时间形成的唯一最新提交；未推送或改写远端引用。正式 checkpoint smoke、真实 Dataset 的完整 F1/F3 生产和服务器 GPU 利用率基准尚未执行；它们需要可用的最终 checkpoint 和用户对服务器运行的明确授权。

本记录只在审查结论、Git 端点、真实 checkpoint 运行或正式任务提交等明确事件发生后更新，不记录轮询或逐命令流水账。
