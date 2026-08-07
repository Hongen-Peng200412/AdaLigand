# Find_0 Fα、Li、Gauss 第二阶段与 Git 重整交接

## 当前目标

在不影响正在运行的 Find_0 validation/train F1-centered 冻结任务的前提下，为下一版 Pocket_Plus 推理管线增加三项能力：添油式 Fα-centered、独立 Li-centered、Gauss scorer 第二阶段局部精修。实现完成后，按 `dual-track-git-workflow` 把 2026-08-03 以来混杂的推理与 box_pool 历史重建为两段紧凑 Learn 历史。

## 已冻结的科学与产物边界

- Fα 直接复用 `thresholds.json` 中七个既有 `t_alpha` 阈值层，不重建 forest 或 CLG。新增 centered 文件为 `F_1_2_centered.npz`、`F_2_3_centered.npz`、`F_4_5_centered.npz`、历史 `F1_centered.npz`、`F_5_4_centered.npz`、`F_3_2_centered.npz`、`F_2_centered.npz`，字段完全同构。
- Li 从主线已有 `probability_map.npz` 逐图计算阈值并向上量化到 32768 分母网格，固定 `min_voxels=10`，结果写入 `/storage/penghongen/AdaLigand_stage1_LI_inference` 下的 `Li_centered.npz`。Li 不落盘 forest、CLG、`candidate_eligible` 或 Selector 输入。
- `_BLOB_EXCEED` 使用两个独立开关。`continue_on_blob_exceed` 只决定生产是否继续；正式新脚本仅 calibration 开启，validation/train 关闭。`evaluate_on_blob_exceed` 只决定已有产物是否进入评估；正式评估脚本始终开启。
- Gauss 第二阶段固定第一阶段最优的 `tau_angstrom` 与 5 Å 截断，两个 lambda 各取中心值的 0.8、0.9、1.0、1.1、1.2 倍，`gauss_score_min` 取 0.3 至 1.7 倍、步长 0.1，共 375 组正参数。
- Gauss 回填默认强制刷新，但只能替换 `gauss_score` 与 `gauss_selected`。只存在一个字段时始终视为损坏。Fα 结果写回主线 forest；Li 结果写回独立 `Li_centered.npz`。两者都不改 `candidate_eligible`，不限制 CLG/Selector 候选。

## 本地实现与双线状态

Pocket_Plus 真实实现保存在 `codex/find0-inference-flexible-gauss-v2@5b014d6`。学习历史从共同基点 `ad4dde8` 重建为两个连续子段：推理灵活化与 Gauss 的端点为 `Learn/find0-inference-flexible@d54ec20`，第二版 BOX 池与训练入口的端点为 `Learn/stage1-box-pool-2@0976f64`；`Learn/CUMULATIVE` 已推进到同一最终端点 `0976f64`。实现端与学习端的 Git tree 均为 `a8157b3a084770fcc615b0a8035c82be15167fed`，可执行代码、配置、脚本、测试和文档逐路径等价。

旧 `Learn/find0-inference-f1` 与 `Learn/find0-gauss-scorer` 已分别改名为 `archive/Learn-find0-inference-f1-pre-rebuild` 与 `archive/Learn-find0-gauss-scorer-pre-rebuild`，保留旧提交供追溯，但不再占用正式 Learn 名称。真实实现分支和远端引用均未删除或改写，也没有 push。

Pocket_Plus 主工作树只剩用户 staged 的 `talk/global.md` 和明确要求暂留的未跟踪 `训练与运行/sh/infer/Find_0_train_F1_shard_01.sh`。原 staged 的 `train_2/Find_1.sh` 与 `train_2/unet_c1.sh` 已按授权进入第二版 BOX 池学习段；其中 `Find_1.sh` 最终 blob 与用户原索引 blob 精确相同。

实现覆盖 `src/inference`、`src/artifacts`、`src/evaluation`、`ops/Gauss_Scorer`、正式 infer shell、测试与 Pocket_Plus 三份说明文档。推理、产物与评估相关的 64 项回归测试通过，BOX、数据集、配置与任务调度相关的另外 54 项测试通过，`python -m compileall -q src ops/Gauss_Scorer ops/box_pool_2` 及全部相关 shell 的 `bash -n` 通过。训练侧 `tests/model/test_density_cube.py` 在收集阶段因当前 Windows 环境缺少 `torch_cluster` 而停止；完整测试还缺少 `rootutils`、`lightning` 与 `addict`，这属于环境依赖缺口，没有出现本轮相关测试失败。AdaLigand 已同步更新 BOX-level 契约、两个 ExecPlan、两份检查记录、mapping 与本交接；这些改动留在 `Learn/CUMULATIVE` 工作树，不提交、不修改索引。

## 当前服务器边界

现有 Job 335115 validation、Job 335116 train 0/50、Job 335493 train 1/50 继续使用冻结 release `Pocket_Plus_c65e77b0b031`。本次新代码没有同步到服务器，没有改动态命令、锁或正式产物。历史第一阶段 Gauss 参数、Job 335572 的 calibration 回填及其产物继续有效；新的第二阶段搜索尚未运行。

## 下一步

1. 不向当前 Job 335115、335116、335493 的冻结 release 部署本轮代码，继续按既有 heartbeat 监控正式 F1 产物。
2. 需要启动下一版 Fα、Li 或 Gauss 第二阶段实验时，从 `Learn/CUMULATIVE@0976f64` 使用正式入口建立新 release；不得覆盖历史第一阶段参数与产物。
3. 若要执行训练侧完整测试，改用具备 `rootutils`、`lightning`、`torch_cluster` 与 `addict` 的既有 Linux 环境。
4. 不 push；远端更新仍需用户另行授权。
