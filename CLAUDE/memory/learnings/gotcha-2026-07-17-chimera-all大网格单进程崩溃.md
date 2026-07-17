# Chimera ALL 大网格崩溃不能靠并发或静默改公式掩盖

Type: gotcha
Date: 2026-07-17
Tags: AdaLigand, Stage F, Chimera, cc_all, SIGSEGV, numerical-equivalence

## Context

Stage F 的确定性 MapQ/Chimera 适配修复后，补算 v1 仅余 `9bw7/9c1k/9dgr/9fkb/9mxv/9nw3` 六个大网格 unknown。六者在 `n_jobs=1` shadow 中仍 6/6 fail；有效 ALL-only fresh-process v2 用 `9hhl` 证明两个 ALL 值可以逐位复现 canonical，却在 `9fkb` 上再次得到 signal 11。运行节点约 2 TB RAM，且没有节点或 cgroup OOM 证据。

## Memory

- 先验证诊断入口真的执行了科学计算。`stage_f_cc_all_fresh_process_shadow_20260717_v1` 因 harness `ImportError` 零科学计算，只能保留为失败证据，不能推导 CC 或样本结论。v2 的成功控制和失败样本必须同时存在。
- classic Chimera 1.19 的 ALL 路径会把实验图全部非零 grid 点先物化为 `float32 (N,3)` 坐标，再生成权重与模拟图三线性插值向量；超大图可能在单 PDB、单进程下触发 legacy 内部 signal 11。`n_jobs=1` 失败说明外层 Loky 并发不是唯一原因，约 2 TB 宿主无 OOM 说明盲目增加 RAM/worker 没有证据支持。
- 四 CC 契约不能因该故障静默改变。禁止裁图、降采样、改非零 mask、换均值或归约精度、用 contour CC 代替 ALL，或换工具后仍把结果称为原 `cc_all*`。
- 若用户批准有界内存适配，最窄路径是按祖传 C-ravel 顺序分块生成 float32 点，复用原世界变换与 `interpolated_values`，把完整 `w1/w2` 按原顺序写入 memmap，最终仍调用原 `FitMap.overlap_and_correlation`。控制样本应要求向量和最终 packed float64 逐位相同。只流式累加 sufficient statistics 会改变浮点归约顺序，不能默认宣称祖传数值等价。
- 在旧上限下，当前 5 项再加六者会达到 11，违反严格 `<10` 并呈系统性趋势，因此 Agent 必须先停下请求用户。用户随后显式选择仅在本 run 排除六者，并把本 run 上限放宽到 30；累计 11/22,386（约 0.049138%）。这不授权生产 PDB allowlist、未来 run 自动排除或修改四 CC，长期边界见 `decision-2026-07-17-stage-f六大图run-only排除与上限30.md`。

## When To Use

当 Stage F 的 `cc_all` 或 `cc_all_about_mean` 在大网格上 signal 11、单进程仍失败，或有人提议通过裁图、换相关函数、增加 worker、直接排除样本来绕过时使用。在取得显式 run-scoped 授权前先保留 unknown 和精确 `after+try` 停点，再核验 fresh 正控制与外部工具路径；授权后仍须通过 manifest 而不是生产 allowlist 实施。

## Related Files

- `Data_Preprocessing/Ori_Data/code/quality.py`
- `Data_Preprocessing/Ori_Data/code/chimera.py`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `CLAUDE/memory/learnings/decision-2026-07-14-stage-f长尾与阶段专属排除.md`
