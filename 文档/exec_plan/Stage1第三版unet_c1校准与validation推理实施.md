# Stage1 第三版 unet_c1 校准与 validation 推理实施记录

本文记录主链辅助监督版 `unet_c1` 在 Stage1 第三版 calibration 与 validation 清单上的正式推理、F1/F2 连通区域生产和 basic 参数调整。当前科学与执行规格是 Pocket Plus `talk/refactor/stage1_v3_inference.md`、`src/inference/README.md`、`configs/inference/README.md` 与 `训练与运行/sh/infer/README.md`；跨项目盘上字段权威仍是 AdaLigand `文档/规划文档/BOX-level数据契约.md`。本文只保存已经发生的实现、部署、启动、监视、异常处理和验收证据，不重新定义科学字段。

## 正式范围

正式产物根固定为：

```text
/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950
```

目录职责如下：

- `inputs/`：冻结 calibration、validation、推理配置，以及 checkpoint、训练配置和部署代码身份。
- `artifacts/`：五阶段推理入口共同使用的 `--output-root`。
- `monitoring/`：GPU 15 秒采样、阶段起止时间和性能汇总。
- `feedback/`：本轮新增 CPU Slurm Job 的 release、launch、动态命令和标准输出。

本轮正式生成：

1. calibration 100 个 PDB 的完整图 probability map。
2. validation 200 个 PDB 的完整图 probability map。
3. calibration 的 F1 semantic、F1 blobs 和 F1 basic 参数；语义 `alpha=1`，选择目标 `objective_beta=1`。
4. calibration 的 F2 semantic、F2 blobs 和 F2 basic 参数；语义 `alpha=2`，选择目标 `objective_beta=2`。

本轮不生成 centered 或 evaluate，不正式运行 Gaussian 调参；Gaussian 生产代码与 basic 同步获得并行能力并通过等价测试。

## 冻结身份

| 实体 | 正式身份 |
| --- | --- |
| producer | `unet_c1` |
| checkpoint | `/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/runtime/mainchain_official_346737/logs/AdaLigand_Stage1-unet_c1-mainchain/unet_c1_mainchain____tmp_stage1_mainchain_job346737_20260818T035126_a4_formal/checkpoints/TOP_epoch_00_score_0.6030.ckpt` |
| checkpoint SHA-256 | `341c3aa1f383b3920964980bb410bd69f0c0e10e2169f417cce0cf1cf34feed6` |
| resolved config | 同一训练 run 的 `config.yaml` |
| resolved config SHA-256 | `28d0d642860f5946342e1eb2d9d506bbe16794b50ae120fc6dd2925468517884` |
| 模型代码来源 | `training_snapshot`；训练 run 的 `src_snapshot/src` 共 100 个文件 |
| calibration 原清单 | `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/split/pdb_split/calibration.json` |
| calibration 清单 SHA-256 | `b14c9f4413092454c34f24239f0ccb1b2d506b5105fcff9dea3e6b7e87b0fe7a`；100 个唯一 PDB |
| validation 原清单 | `/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_3/split/pdb_split/validation.json` |
| validation 清单 SHA-256 | `86a8e897bf7f854a377e4c879c41a55fa0aec8cb32d66743fdd935ff4b1c4cdf`；200 个唯一 PDB |
| 数据根 | `/storage/penghongen/AdaLigand/Ori_Data` |
| 语义网格分母 | `32768` |
| 调参前固定体素门槛 | `prefiltered_min_voxel=8`，包含端点 |
| 最终体素门槛范围 | `min_voxels=8..40`，包含端点 |

## 生产代码实现与审查

### 并行边界

Pocket Plus `tune_centered_selection()` 增加显式 `workers` 参数，`configs/inference/stage1_v3.yaml:calibration.workers` 固定为 16。以下阶段使用同一个外层线程池：

- 多 PDB 候选文件与 occurrence 事实加载。
- 多 PDB 校准事实和 Gaussian 距离表构造。
- basic 与 Gaussian 的最终 `min_voxels` 组合。
- Gaussian 各 tau 的 A 原子项准备。
- Gaussian 粗搜索与细搜索的独立参数组合。

basic 的全局实际 float32 分数阈值扫描保持串行，因为该阶段按降序累计候选并增量执行一对一匹配。所有并行结果按原配置顺序读取，最优项仍只在目标值严格提升时替换，因此端点、同分候选和同分参数的首项获胜语义保持不变。`stage1_v3.sh` 无条件把 OMP、MKL 和 OpenBLAS 线程数设为 1，避免外层 16 个任务再次嵌套数值库线程。

H100 完整图配置为窗口 batch 16、物化 worker 12、预取 batch 12、待融合 batch 8；CPU 配置为 blob worker 16、calibration worker 16。

### Git 与验证证据

Pocket Plus 从 `Learn/CUMULATIVE@1315d301c867c99e2dc0736feffde86e9cd7fa0a` 建立实现分支 `codex/unet-c1-calibration-parallel-tune`。实现端点为 `5476a33327ccee0946daf43cca22f7b928ea562e`；学习端点与当前 `Learn/CUMULATIVE` 为 `4e5325da1e36453586bf12eade0e7a6df44cd106`。两端 tree 均为 `ca21a939dc59d2b907fb30299611af63457fd1f5`，`git diff 5476a33..4e5325d` 为空。

本地正式相关回归：

```text
pytest -q tests/inference tests/datasets/test_stage1_dataset.py
44 passed

pytest -q tests/inference/test_calibration_parallel.py
4 passed；修订期间连续运行 5 次，学习端点再连续运行 3 次

python -m compileall -q src tests
通过

bash -n 训练与运行/sh/infer/stage1_v3.sh
通过
```

逻辑审查以旧串行提交为对照，对 25 个随机 basic/Gaussian 样例比较 `workers=1/4`，50 组结果逐字段完全一致。完整审查只执行一轮；随后两位审查者只复核已报告问题。最终结论为：BLAS 固定、阶段计时、多线程与乱序测试、正式 `run_tune_stage()` 覆盖、README、Docstring 和代码排版全部通过。

## 执行事件

本节只在代码冻结、部署、正式启动、阶段完成、故障恢复和最终验收等明确事件后更新，不记录无变化的轮询。

| 时间（Asia/Shanghai） | 事件 | 证据与结果 |
| --- | --- | --- |
| 2026-08-24 02:39 | 建立持续目标 | 目标覆盖代码改造、部署、calibration/validation probability、F1/F2 semantic/blobs/basic、严格日志、故障恢复与最终验收；Job `346737` 完成后仍保留资源。 |
| 2026-08-24 03:13 | 并行代码与双线历史冻结 | Pocket Plus 实现端点 `5476a33`、学习与累计端点 `4e5325d`，tree `ca21a939`；44 项相关回归与重复并发测试通过。 |
| 2026-08-24 03:16 | 部署前只读资源核验 | Job `346737` 在 `hnode02` 为 `RUNNING`，16 CPU、1×H100；GPU 显存 1 MiB、利用率 0%、功耗 45.49 W。`try_lock_346737` 与 `after_lock_346737` 均存在，未发现 `kill_lock`；正式产物根尚不存在。 |
| 2026-08-24 03:28 | AdaLigand 日志隔离 | 主工作区存在另一项 Find1 监视的 3 个修改与 1 个新 handoff。为避免混入，本文从 `70a4ffe` 建立独立工作树分支 `codex/unet-c1-calibration-inference-log`；原改动保持原样。 |
| 2026-08-24 03:34 | 隔离代码部署完成 | 对已验证的隔离任务根执行删除式同步，删除旧快照中的 1,748 个文件和 223 个目录。最终保留 458 个 Pocket Plus `4e5325d` 文件与 1 个 runner 兼容脚本；反向 `rsync` 差异为 0，四个关键文件 SHA-256 与本地一致。共享 `/home/penghongen/My_Project/Pocket_Plus` 未修改。 |
| 2026-08-24 03:35 | 正式根与输入冻结 | 建立 `inputs/`、`artifacts/`、`monitoring/` 与 `feedback/`。`production_contract.json` 记录 checkpoint、训练配置、两份清单、代码、参数与资源身份；六个 inputs 文件均设为只读。 |
| 2026-08-24 03:35--03:36 | Linux 与 H100 smoke | 在 Job `346737` allocation 内用 `srun --overlap` 执行；44 项 CPU 回归、配置解析、编译、Shell 语法和 2 项真实 H100 CUDA smoke 全部通过。`try_lock` 与 `after_lock` 未改变，尚未触发 a5。 |
| 2026-08-24 03:39 | a5 正式启动 | 动态命令 SHA-256 为 `be15872dd24b431569f15fe71536d4cbbc76d1ac803a220651ddf3ca5e69a8d8`；只删除 `try_lock_346737`。runner 建立 release `Pocket_Plus_38edc6467116` 与 launch `tmp_stage1_mainchain_job346737_20260824T033950_a5`，`after_lock` 保持不变。 |
| 2026-08-24 03:41--03:47 | 首项产物验收 | `6bgi` 与 `6dqn` 已完成；首个 `6bgi` 的概率 NPZ、几何、性能与完成标记逐项通过。H100 快照利用率 98%、显存 43,924 MiB、功耗 344.75 W，a5 进入稳定计算。 |
| 2026-08-24 07:49--08:00 | a5 完成与全量验收 | a5 以退出码 0 完成，墙钟 14,998 秒；calibration 为 100/100，完整图概率共 14,459,386,630 字节。全量审计确认没有缺项、额外项、临时项、非有限值或几何漂移；100 个 PDB 合计 112,070 个窗口。GPU 回填统计的 984 个活跃样本平均利用率 99.112%，峰值显存 43,930 MiB。 |
| 2026-08-24 07:59--08:02 | F1/F2 blobs 与 a6 启动 | 提交 CPU16 Job `353620/353621`，分别生成 `alpha=1/2` 的 calibration semantic 与 blobs；两者于 Slurm 控制器时间 08:01:36 同时开始。a6 于 hnode02 时间 08:02:11 开始生成 validation 200 个 probability map；只移除 `try_lock_346737`，`after_lock_346737` 保留。三条支线均进入正常加载或计算。 |
| 2026-08-24 08:09 | F1/F2 blobs 完成 | Job `353620/353621` 分别以 `COMPLETED 0:0` 结束，墙钟为 7 分 57 秒和 7 分 54 秒；两套 semantic、scan、100/100 blobs 和完成标记并存。每条 Job 读取约 17,978.6 MiB，确认该阶段由共享存储读取主导。 |
| 2026-08-24 08:11--08:16 | F1/F2 basic 完成并全量验收 | Job `353646/353647` 分别在 17 秒和 20 秒内 `COMPLETED 0:0`。F1 得到 `score_threshold=0.9048807621, min_voxels=24`；F2 得到 `score_threshold=0.4806580544, min_voxels=15`。全量审计覆盖两套 semantic 扫描、200 份 blobs、完成标记和 basic JSON，全部通过。 |
| 2026-08-24 08:03--08:18 | validation 首项验收 | 首个 `5irx` 的概率为 float32 `(234,234,234)`，全部有限且范围合法；shape、origin 和 voxel size 与 `exp.npy`、`exp.npz` 和 `ligand_area.npz` 完全一致。a6 的 GPU 采样连续处于 98--100%，`after_lock_346737` 保留。 |

## 部署与服务器 smoke 命令

删除式部署只在已经解析并精确核对的隔离任务根内执行。同步源是远端暂存目录 `/storage/penghongen/tmp/stage1_v3_inference_deploy_4e5325d`；同步命令保留固定 `TASK_PATH` 兼容文件：

```bash
rsync -a --delete \
  --exclude='训练与运行/sh/tmp_stage1_mainchain.sh' \
  /storage/penghongen/tmp/stage1_v3_inference_deploy_4e5325d/ \
  /storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/task_root/Pocket_Plus/
```

服务器验证由以下命令启动：

```bash
srun --jobid=346737 --overlap --nodes=1 --ntasks=1 --cpus-per-task=16 bash -lc '
source "$HOME/anaconda3/etc/profile.d/conda.sh"
conda activate Pocket_Plus_centos7_cu121_allgpu
cd /storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/task_root/Pocket_Plus
export PYTHONPATH="$PWD:${PYTHONPATH:-}"
pytest -q tests/inference tests/datasets/test_stage1_dataset.py
python -m compileall -q src tests
python -c "from omegaconf import OmegaConf; c=OmegaConf.load(\"configs/inference/stage1_v3.yaml\"); assert (c.blob_workers,c.window.workers,c.window.prefetch_batches,c.window.pending_fusion_batches,c.window.batch_size,c.calibration.workers)==(16,12,12,8,16,16)"
bash -n 训练与运行/sh/infer/stage1_v3.sh
pytest -q tests/inference/test_stage1_cuda.py
'
```

实际结果为 `44 passed in 11.17s` 与 `2 passed in 3.35s`，设备为 NVIDIA H100 PCIe 80 GB。

## 正式启动记录

本节保存每次正式启动的完整科学命令、开始与结束时间、Slurm Job、attempt、release、launch、动态命令 SHA-256、日志和产物地址。cnode02 的文件时间比 Slurm 控制器记录约早 2 分钟；CPU Job 同时保留控制器的 Submit/Start/End 时间与执行节点生成的 launch 名称，不用其中一套时间改写另一套。

### Job 346737 attempt a5：calibration probability

开始时间：2026-08-24 03:39:50+08:00。结束时间：2026-08-24 07:49:48+08:00。退出码为 0，阶段墙钟为 14,998 秒。

- Slurm Job：`346737`，`hnode02`，1×NVIDIA H100 PCIe，16 CPU。
- release：`Pocket_Plus_38edc6467116`；内容 SHA-256 `38edc6467116c76b42aeb2382cc3627912b9298e175e949054b1b0128f0081da`；manifest SHA-256 `25dfdb4cfc101c80a6d7afa009742a6043e897f160ecf81aca5c49e082c9586a`。
- launch：`tmp_stage1_mainchain_job346737_20260824T033950_a5`；`launch.json` SHA-256 `dc4fd1b76a1f72ba486c91d44afa6e24814dd1633e32c6ef10b334af101d67b3`。
- 动态命令与 launch 冻结副本 SHA-256：`be15872dd24b431569f15fe71536d4cbbc76d1ac803a220651ddf3ca5e69a8d8`。
- allocation 输出：`/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/feedback/allocations/346737/out` 与 `err`。
- 阶段日志：`monitoring/tmp_stage1_mainchain_job346737_20260824T033950_a5_stage.log`。

触发命令先逐项核对动态命令哈希、`try_lock`、`after_lock` 和无 `kill_lock`，再只删除：

```bash
rm -f -- /storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/feedback/allocations/try_lock_346737
```

正式科学命令为：

```bash
bash "${TASK_PROJECT_ROOT}/训练与运行/sh/infer/stage1_v3.sh" probability \
  --producer unet_c1 \
  --checkpoint /storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/runtime/mainchain_official_346737/logs/AdaLigand_Stage1-unet_c1-mainchain/unet_c1_mainchain____tmp_stage1_mainchain_job346737_20260818T035126_a4_formal/checkpoints/TOP_epoch_00_score_0.6030.ckpt \
  --resolved-config /storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/runtime/mainchain_official_346737/logs/AdaLigand_Stage1-unet_c1-mainchain/unet_c1_mainchain____tmp_stage1_mainchain_job346737_20260818T035126_a4_formal/config.yaml \
  --model-code-source training_snapshot \
  --pdb-json /storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950/inputs/calibration.json \
  --split calibration \
  --output-root /storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950/artifacts
```

启动后发现 a5 的 GPU 采样循环没有把数据行重定向到预建 CSV；时间戳、利用率、显存与功耗样本仍每 15 秒进入 allocation `out`，推理与科学产物不受影响。a5 完成后从本次 launch 起始时间回填 `monitoring/*_gpu.csv`；a6 动态命令直接修正重定向。该问题不触发 a5 重试。

第一次全量审计命令在临时远端脚本尚未落盘前，因嵌套 shell 引号剥离 Python 字典键而以 `NameError` 退出。该命令没有写入科学目录；随后把同一只读审计写成独立脚本 `/storage/penghongen/tmp/stage1_v3_inference_346737/audit_calibration_a5.py`，SHA-256 为 `36255db2d2ecaab79af368f0e49a0074927d823ec93a828e123f134a7b0cd9fe`，重跑成功。该重试只修复执行表达，不改变数据、代码或科学契约。

首个完成项 `6bgi` 的正式审计结果：

- `probability_map.npz` 精确包含 `probability_map`、`origin_xyz`、`voxel_size_xyz`。
- 概率为 float32 `(262,262,262)`，与 `exp.npy` 和 `ligand_area.npz:grid_shape_zyx` 一致；全部有限，最小值 `2.9331204e-11`，最大值 `1.0`，均值约 `0.000300645`。
- `origin_xyz=[0,0,0]`，`voxel_size_xyz=[0.9966412,0.9966412,0.9966412]`，与数据根几何逐元素相同。
- `geometry.json` 记录 80³ 窗口、`stride_zyx=[30,30,30]` 和 512 个窗口。
- `performance.json` 的墙钟、物化等待和融合等待分别约为 `68.563`、`0.625` 和 `0.615` 秒，均为有限非负值。
- `_COMPLETE` 的角色为 `probability`，发布时间为 `2026-08-23T19:41:31.386615+00:00`。

100 个 calibration PDB 的最终审计结果：

- 预期项、完成项与磁盘目录均为 100，未发现缺失、额外、临时或部分发布目录。
- 概率全局最小值约 `5.9952e-15`、最大值 `1.0`；所有概率与几何值均有限，概率范围合法。
- 100 份 NPZ 共 14,459,386,630 字节；合计 112,070 个窗口，逐 PDB 墙钟合计约 14,948.65 秒，中位数约 97.39 秒，最大值约 651.73 秒。
- 吞吐约为每秒 7.497 个窗口；物化等待与融合等待分别占逐 PDB 墙钟总和的约 0.00643 与 0.00280。
- `monitoring/calibration_probability_audit.json` SHA-256 为 `2ed25d02d1a2f83c12882511cf06aae2a73f51b79f5af788df2f9fb3d8bd8eba`。
- 从 allocation 输出回填的 `monitoring/tmp_stage1_mainchain_job346737_20260824T033950_a5_gpu.csv` SHA-256 为 `92af310449160e2b3cfcbc4542606f2860ab95e6b786653553fc6e7b21eb96b4`。共 998 个样本，其中 984 个活跃样本；全部样本平均 GPU 利用率 97.721%，活跃样本平均 99.112%，峰值显存 43,930 MiB，活跃样本平均功耗约 341.61 W。

### Job 346737 attempt a6：validation probability

开始时间：2026-08-24 08:02:11+08:00。当前正在运行。

- Slurm Job：继续复用 `346737`，`hnode02`，1×NVIDIA H100 PCIe，16 CPU。
- release：继续使用 `Pocket_Plus_38edc6467116`。
- launch：`tmp_stage1_mainchain_job346737_20260824T080211_a6`；`launch.json` SHA-256 为 `8a0f75e0e85bafb92adecd28b24b5833c95baf3469b5ef50d11ad337bc9eb691`。
- 动态命令与 launch 冻结副本 SHA-256：`eb986013b3ba221346445bc2c17ec1a5bdbae41b260c5a2b3069eed48e846919`。
- 阶段日志：`monitoring/tmp_stage1_mainchain_job346737_20260824T080211_a6_stage.log`。
- GPU 采样：`monitoring/tmp_stage1_mainchain_job346737_20260824T080211_a6_gpu.csv`；a5 的重定向缺口已经修复，表头与数据行都直接写入该文件。
- 产物：`artifacts/unet_c1/validation/<pdb_id>/probability/` 及对应 `status/probability/_COMPLETE`。

触发前核对动态命令 SHA-256、`try_lock_346737` 与 `after_lock_346737`，随后只删除 `try_lock_346737`。正式科学命令为：

```bash
bash "${TASK_PROJECT_ROOT}/训练与运行/sh/infer/stage1_v3.sh" probability \
  --producer unet_c1 \
  --checkpoint /storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/runtime/mainchain_official_346737/logs/AdaLigand_Stage1-unet_c1-mainchain/unet_c1_mainchain____tmp_stage1_mainchain_job346737_20260818T035126_a4_formal/checkpoints/TOP_epoch_00_score_0.6030.ckpt \
  --resolved-config /storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/runtime/mainchain_official_346737/logs/AdaLigand_Stage1-unet_c1-mainchain/unet_c1_mainchain____tmp_stage1_mainchain_job346737_20260818T035126_a4_formal/config.yaml \
  --model-code-source training_snapshot \
  --pdb-json /storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950/inputs/validation.json \
  --split validation \
  --output-root /storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950/artifacts
```

首个完成项 `5irx` 的正式审计结果：

- `probability_map.npz` 精确包含 `probability_map`、`origin_xyz`、`voxel_size_xyz`；概率为 float32 `(234,234,234)`，全部有限，最小值约 `7.6669e-11`，最大值 `1.0`。
- shape、`origin_xyz=[0,0,0]` 和 `voxel_size_xyz=[0.9974154,0.9974154,0.9974154]` 与数据根的 `exp.npy`、`exp.npz` 和 `ligand_area.npz` 逐元素一致。
- `geometry.json` 记录 80³ 窗口、`stride_zyx=[30,30,30]` 与 343 个窗口；墙钟、物化等待和融合等待分别约为 `46.612`、`0.680` 和 `0.261` 秒。
- `_COMPLETE` 的角色为 `probability`；`monitoring/validation_first_probability_audit.json` SHA-256 为 `8651c82942b817750dba7260dd4eb7737e5f90a91ce44437fd31b4abe25d5f50`。
- 首次只读审计对 `performance.json` 使用了旧路径 `probability/performance.json`，因此在未写文件的情况下以 `FileNotFoundError` 退出；按实际契约路径 `status/probability/performance.json` 重跑后通过，科学产物未修改。

### F1 semantic 与 blobs CPU16

Slurm Job `353620` 于控制器时间 2026-08-24 08:01:36+08:00 提交并开始，08:09:33 以 `COMPLETED 0:0` 结束，墙钟为 7 分 57 秒。执行节点建立 launch `stage1_v3_job353620_20260824T075953_a1`；`launch.json` SHA-256 为 `6829ed1efdeed8ad45505f5a48a18cced6c4af421fea1af9a94f33cee7ec2ff7`，动态命令与 launch 副本 SHA-256 为 `83ddd253751085473b0c7d91804580e8977786f1a10d177382348e716d3a9a16`。release 为正式根 `feedback/releases/Pocket_Plus_38edc6467116/Pocket_Plus`，manifest SHA-256 为 `aa4e77255d8866fd0716ae524a5308197ca1dbb6d412e280b548b1b4527567af`。标准输出与错误分别位于 `feedback/allocations/353620/out` 和 `err`。

完整提交命令为：

```bash
task_root=/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/task_root/Pocket_Plus
formal_root=/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950
bash "$task_root/训练与运行/submit_task.sh" \
  --task-root "$task_root" \
  --feedback-root "$formal_root/feedback" \
  --sh 训练与运行/sh/infer/stage1_v3.sh \
  --resource cpu --cpus 16 \
  --job-name unet_c1_calibration_f1_blobs \
  -- blobs \
  --producer unet_c1 \
  --pdb-json "$formal_root/inputs/calibration.json" \
  --split calibration \
  --output-root "$formal_root/artifacts" \
  --alpha 1 \
  --fit-semantic \
  --data-root /storage/penghongen/AdaLigand/Ori_Data
```

正式结果为：语义阈值网格索引 27,087、阈值 `0.826629638671875`、全局 micro-F1 `0.5809896387895521`；100 份 F1 blobs 共 2,619 个 blob、576,101 个体素和 3,179,298 个 NPZ 字节。

### F2 semantic 与 blobs CPU16

Slurm Job `353621` 与 Job `353620` 在同一控制器时间提交并开始，08:09:30 以 `COMPLETED 0:0` 结束，墙钟为 7 分 54 秒。执行节点建立 launch `stage1_v3_job353621_20260824T075954_a1`；`launch.json` SHA-256 为 `c1dc4c6a011ed0fc7ba42abc8a8dbd6d43f670a5c36373d4340a5de0596cb2b2`，动态命令与 launch 副本 SHA-256 为 `4972152578b3ed3638bad34ff9b20a01c6a6c2252d29f8a75f3bec3f5debe0fa`。release、manifest 与日志根和 F1 相同；标准输出与错误分别位于 `feedback/allocations/353621/out` 和 `err`。

完整提交命令为：

```bash
task_root=/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/task_root/Pocket_Plus
formal_root=/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950
bash "$task_root/训练与运行/submit_task.sh" \
  --task-root "$task_root" \
  --feedback-root "$formal_root/feedback" \
  --sh 训练与运行/sh/infer/stage1_v3.sh \
  --resource cpu --cpus 16 \
  --job-name unet_c1_calibration_f2_blobs \
  -- blobs \
  --producer unet_c1 \
  --pdb-json "$formal_root/inputs/calibration.json" \
  --split calibration \
  --output-root "$formal_root/artifacts" \
  --alpha 2 \
  --fit-semantic \
  --data-root /storage/penghongen/AdaLigand/Ori_Data
```

正式结果为：语义阈值网格索引 9,867、阈值 `0.301116943359375`、全局 micro-F2 `0.636146007126712`；100 份 F2 blobs 共 3,491 个 blob、798,418 个体素和 4,486,631 个 NPZ 字节。

### F1 basic tune CPU16

Slurm Job `353646` 于控制器时间 2026-08-24 08:11:29+08:00 提交并开始，08:11:46 以 `COMPLETED 0:0` 结束，墙钟 17 秒。执行节点建立 launch `stage1_v3_job353646_20260824T080925_a1`；`launch.json` SHA-256 为 `b0e0ffc585376ea03c3c98a4f24f5f099b0fb2c98579b76ac699ca77f6916206`，动态命令与 launch 副本 SHA-256 为 `fe0e9c829a6ad2213a5e4e24c1c5803bd964f9a48a71826efa51f82f409ea338`。正式结果 `F1_basic.json` SHA-256 为 `721a302367e9b06c829ea6932ebf49e76fa34c0ee5df0eb0b420e2432bc3df87`；参数为 `alpha=1`、`objective_beta=1`、`prefiltered_min_voxel=8`、`score_threshold=0.9048807621002197`、`min_voxels=24`，最终目标值为 `1.5192947900233444`。

完整提交命令为：

```bash
task_root=/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/task_root/Pocket_Plus
formal_root=/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950
bash "$task_root/训练与运行/submit_task.sh" \
  --task-root "$task_root" \
  --feedback-root "$formal_root/feedback" \
  --sh 训练与运行/sh/infer/stage1_v3.sh \
  --resource cpu --cpus 16 \
  --job-name unet_c1_calibration_f1_basic \
  -- tune \
  --producer unet_c1 \
  --pdb-json "$formal_root/inputs/calibration.json" \
  --split calibration \
  --output-root "$formal_root/artifacts" \
  --alpha 1 \
  --objective-beta 1 \
  --score-mode basic \
  --prefiltered-min-voxel 8 \
  --data-root /storage/penghongen/AdaLigand/Ori_Data
```

### F2 basic tune CPU16

Slurm Job `353647` 与 F1 在同一控制器时间提交并开始，08:11:49 以 `COMPLETED 0:0` 结束，墙钟 20 秒。执行节点建立 launch `stage1_v3_job353647_20260824T080927_a1`；`launch.json` SHA-256 为 `0611dfa33b19a1fadb5f0081988922f78ae25afe6c46f5e9ca93b12385fa62d7`，动态命令与 launch 副本 SHA-256 为 `46c4dd3fd7d24bc93736742b98fbdfdbbf97dfe72c935e478e6c0144503e3bd2`。正式结果 `F2_basic.json` SHA-256 为 `093b5372248f2277b1873bfaaa5dd20c10ea30260e26c6d78ad9b90e43448922`；参数为 `alpha=2`、`objective_beta=2`、`prefiltered_min_voxel=8`、`score_threshold=0.48065805435180664`、`min_voxels=15`，最终目标值为 `1.6342244192773876`。

完整提交命令为：

```bash
task_root=/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/task_root/Pocket_Plus
formal_root=/storage/penghongen/AdaLigand_stage1_inference/UNET/unet_c1-mainchain-ligand_PRAUC_0.602950
bash "$task_root/训练与运行/submit_task.sh" \
  --task-root "$task_root" \
  --feedback-root "$formal_root/feedback" \
  --sh 训练与运行/sh/infer/stage1_v3.sh \
  --resource cpu --cpus 16 \
  --job-name unet_c1_calibration_f2_basic \
  -- tune \
  --producer unet_c1 \
  --pdb-json "$formal_root/inputs/calibration.json" \
  --split calibration \
  --output-root "$formal_root/artifacts" \
  --alpha 2 \
  --objective-beta 2 \
  --score-mode basic \
  --prefiltered-min-voxel 8 \
  --data-root /storage/penghongen/AdaLigand/Ori_Data
```

### calibration 衍生产物与 CPU 性能验收

`monitoring/calibration_semantic_blobs_basic_audit.json` SHA-256 为 `88888d32f9d6d74e44b0d8b6c878cd5d18ad81e8be4b50b25c937ebdc1b133f4`。审计逐一读取 200 份 blob NPZ，核对数组字段、长度关系、有限性、概率范围、语义来源阈值、完成角色、PDB 集合以及 F1/F2 文件共存；同时核对 32,769 个语义阈值端点、首个最大值规则和两份 basic 参数，全部通过。

Job `353620/353621` 的 batch step 分别读取 17,978.56/17,978.57 MiB，只写 13.16/13.50 MiB；总 CPU 为 7 分 40 秒和 7 分 37 秒，接近单核墙钟，说明端到端时间由共享存储顺序读取约 18 GiB 主导，不属于“计算阶段长时间不足 8 核且非 I/O 饱和”的情形。basic 正式运行整体仅 17--20 秒：100 个输入文件加载为 1.295--1.328 秒，100 个 PDB 事实构造为 4.110--4.923 秒，串行实际阈值扫描为 0.068--0.084 秒，33 个最终 `min_voxels` 组合为 0.361--0.363 秒。由于并行阶段短于一次常规利用率采样，未伪造“持续 8 核”观测；代码层多线程、乱序与串行等价证据沿用冻结测试，正式端到端时间已消除原计划担心的调参瓶颈。

## 部署边界

Job `346737` 的固定 `TASK_PATH` 是隔离任务根中的 `训练与运行/sh/tmp_stage1_mainchain.sh`。allocation runner 在每次执行前仅用该路径建立 launch 身份，真正执行内容来自 `run_cmd_346737.sh`。当前 Pocket Plus Git tree 不包含该临时脚本，因此部署时必须保留这一份 allocation 兼容文件；其冻结 SHA-256 为 `9aab413aa85d9a420e958d741272fc311f36bfe8fcbf7a44ebf630f0851fec62`。除该文件外，隔离任务根将与 Pocket Plus `4e5325d` 的受控文件一致。正式 `run_cmd` 只调用新 `训练与运行/sh/infer/stage1_v3.sh`，不会调用临时训练脚本。

部署目标严格限定为：

```text
/storage/penghongen/tmp/stage1_v3_ablation_replacement_20260817T1845/task_root/Pocket_Plus
```

不修改共享 `/home/penghongen/My_Project/Pocket_Plus`。部署前后均核对目标绝对路径、关键文件 SHA-256、release 与 launch；只删除 `try_lock_346737` 触发已记录的正式 attempt，始终保留 `after_lock_346737`。

## 监视与恢复规则

- calibration 首个 PDB 完成后立即核对 probability 字段、shape、有限性、范围 `[0,1]`、几何、性能文件与 `_COMPLETE`。
- GPU 活跃期每 15 秒记录利用率、显存和功耗；逐 PDB 汇总窗口数、墙钟、物化等待和融合等待。
- CPU 并行阶段结合阶段计时、`sstat/sacct` 与进程线程利用率核验。长期不足约 8 核且并非存储饱和时，继续定位和优化。
- 若 H100 显存不足，窗口 batch 按 `16 → 12 → 8` 调整；已经发布 `_COMPLETE` 的 PDB 默认复用。
- 任何科学契约、性能修复、重试、release 或 launch 变化都必须写回本文和对应 handoff。
- 稳定排队、正常计算或长时间 I/O 期间，不创建 heartbeat。每个 30–60 分钟检查周期由多个独立的 300 秒命令睡眠组成，以便 5 分钟内接收用户新指令。
- validation 完成后保留 `try_lock_346737` 与 `after_lock_346737`；不删除 `after_lock`，不执行 `scancel`。

## 计划与实现差异

当前唯一执行层差异是 Job `346737` 的 allocation runner 要求原固定 `TASK_PATH` 在 release 中存在，因此部署树必须保留一份不参与正式命令的临时训练脚本。该兼容文件不进入 Pocket Plus Git，不改变推理代码或科学产物；其内容、SHA-256 和用途均在本文冻结。其余代码实现和正式参数与批准计划一致。
