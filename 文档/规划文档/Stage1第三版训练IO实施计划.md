# Stage1 第三版训练 I/O 与入口实施计划

本文是第三版 split、BOX pool 和迁移后 NPY 的训练消费主规格。它只覆盖统一 Dataset/Loader、模型输入接缝、四套训练配置、一键提交脚本和短程验证；正式全量训练与新版推理程序不在本轮实施范围内。

## 已冻结前提

- 正式数据根为 `/storage/penghongen/AdaLigand/Ori_Data`，第三版准备根为 `stage1_preparation_box_pool_3`。
- split 使用首次 EMDB 发布时间 `< 2026-01-01`、`map_resolution < 4.0`、`cc_contour > 0.65` 和完整资产门禁；train、validation、calibration 分别为 13,717、200、100 个 PDB。
- BOX 请求比例为 `center:bias:context = 0:5:5`。第二版 `stage1_preparation_box_pool_2` 保留，不改写、不删除。
- 完整体数组已经从 NPZ 迁移到同目录 `exp.npy`、`sim.npy`、`union_mask.npy` 和 `ligand_dist.npy`。NPZ 只保留小型元数据。
- 训练继续使用全局打散的 BOX 请求。按 PDB 分组加载已被实验证明会降低模型性能，只保留在 Git 历史中。

## 唯一生产数据入口

- 活动代码只保留 `Stage1Dataset` 和 `Stage1BatchCollator`，不增加并存的 `Stage1V3Dataset`。训练、验证、完整图和指定中心裁块共享同一套裁块与字段构造逻辑。
- `.npy` 使用只读 `np.load(..., mmap_mode="r", allow_pickle=False)`。每个分布式 rank 和 DataLoader worker 在首次需要时自行打开句柄；Dataset 构造阶段不打开 mmap。
- 运行时只核验小型 NPZ 元数据、数组形状、数据类型和实际读取的 80³ 裁块。禁止在 mmap 缓存未命中时对完整数组执行 `isfinite`、`isnan`、`isinf` 或非负性扫描；完整数组的逐值正确性由第三版迁移验收和 `_COMPLETE` 标记负责。
- 小型元数据/受体表缓存与 mmap 句柄缓存分开管理。mmap 的逻辑 `nbytes` 不计作常驻内存，也不得为了缓存计量遍历整图。
- 批次保留 `atom_feat float32 (N,49)` 与 `atom_is_backbone bool (N,)`。模型输入边界把后者转为 `float32 (N,1)` 并拼到 `atom_feat` 末尾，形成新模型使用的 50 维输入；不修改 `receptor_tokens.npz`。
- 模型边界根据配置兼容旧 49 维检查点。兼容发生在模型输入组装处，不保留第二套旧 Dataset。
- 旧检查点兼容至少覆盖时间节点 2 要评估的 W&B 运行 `pencounkdual-111/AdaLigand_Stage1/es683hq5`；该检查点只用于之后的推理实战，不作为本轮新训练的初始化权重。
- 完整删除 `box_sample_fraction`：覆盖 Dataset 构造参数、请求选择与持久化、Hydra 配置、测试和文档。`stage1_requests.py` 中仍被裁块和推理使用的通用请求类型与解析函数继续保留并整理。
- DataLoader 固定 `pin_memory=True`、`prefetch_factor=2`、`persistent_workers=False`。单卡 16 CPU 使用 14 workers；双卡共 32 CPU 时每个 rank 使用 14 workers。

## 模型与训练入口

- `protein`、`nucleic` 和 `distance` 三类结构预测头使用独立开关，避免关闭主链损失后在双卡 DDP 中留下未参与反向传播的参数。
- 四套当前配置为：
  - `unet_c1/mainchain`：`protein=true`、`nucleic=true`、`distance=true`，单卡 H100、16 CPU 正式入口。
  - `unet_c1/no_mainchain`：`protein=false`、`nucleic=false`、`distance=true`，双卡 H100、共 32 CPU 正式入口；binding receptor voxel 辅助损失和 ligand-distance 损失保持启用。
  - `Find_0/CPC1`：只提供 CPC1 正式入口。
  - `Find_1/CPC1`：只提供 CPC1 正式入口。
- 四套配置沿用当前代码中实际生效的优化器、损失权重、训练时长和配体区域 PR-AUC BEST 口径。本轮不按旧规划恢复 CPC2，也不以旧文档中的 total loss 替换当前 BEST 指标。
- 新脚本集中放入一个 Stage1 第三版训练目录。被替代的旧训练脚本在新入口通过验证后从活动树删除；`训练与运行/sh/infer/` 完整保留。
- 删除旧 `src/datasets/ops/stage1_box_pool.py` 前，先把 `prepare_inference_pdb_lists.sh` 使用的 split 清单读取逻辑迁移到新的只读 `load_split_pdb_ids` 接口。

## 验证与放行

- 实现前确认 Pocket_Plus `Learn/CUMULATIVE` 仍指向唯一最新提交且主工作树干净，再从该端点建立独立实现工作树和双线分支。
- 当前代码基线为 87 项测试通过；这些测试使用旧式夹具，只是回归基线，不代表第三版服务器数据已经可被 Dataset 读取。
- 新增第三版 split/BOX 请求、mmap 延迟打开、缓存边界、80³ 裁块数值校验、49+1→50 维输入、旧 49 维检查点和推理清单读取回归。
- 四套配置均执行一次单卡功能 smoke 和一次双卡 DDP smoke，限制训练与验证批次数并运行一轮，使前向、反向、指标和 checkpoint 路径都被执行。
- `unet_c1/no_mainchain` 的双卡 smoke 必须在 `ddp_find_unused_parameters=false` 下确认没有未使用参数。
- 严格审查通过后才能同步服务器和运行 smoke；本轮不得提交正式全量训练。

## 删除与后续边界

- 旧 Dataset 实现、旧 split/BOX 构建器和被替代的训练脚本直接从活动树删除，只通过 Git 历史阅读。删除不扩展到推理脚本、冻结 release、现有服务器作业或第二版数据目录。
- 时间节点 1 验收后，用户会复制任务负责正式训练提交与低频监视；当前任务随后从更新后的 `Learn/CUMULATIVE` 开始推理程序重构。
- 已存在任务 `codex://threads/019fdca0-937e-7292-a671-48dc6bcab13d`。所有实现继续使用独立工作树和独立分支，不能因另一任务存在而修改其工作树、冻结 release 或运行目录。
- 监视不得建立 heartbeat。人物稳定后使用命令自然等待，每 10 或 20 分钟检查一次；没有状态变化时不重复写日志。
- 新版推理中的 hardmask、F-alpha、高斯打分、最低体素阈值、selector 和 CLG 精简属于时间节点 2，另行确定科学契约。
