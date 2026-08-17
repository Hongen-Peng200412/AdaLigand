# Stage1 第三版训练 I/O 与入口实施记录

本文依据 `文档/规划文档/Stage1第三版训练IO实施计划.md`，记录第三版数据准备完成后对 Pocket_Plus 训练入口进行的只读审计、已经冻结的实施决定和后续实现证据。当前停点是“实现前审计完成”；Dataset、Loader、模型和训练脚本尚未修改。

推理算法重构、正式全量训练、正式训练监视和第二版数据清理不属于本记录当前阶段。

## 当前代码与 Git 坐标

- Pocket_Plus 当前累计分支：`Learn/CUMULATIVE`。
- 当前唯一最新提交：`186bfd05b90f6cbe3fe165e16068ac4bcdc39c7f`，提交说明为“V3: split & box_pool”。
- 第三版数据准备实现端点：`codex/stage1-v3-data-preparation@bbaebe008d42e89923375eeaad98d055b43e030f`。
- 第三版数据准备学习端点：`Learn/stage1-v3-data-preparation@da659b999eaa70aac26a9ead221a129e4434dd04`。
- 2026-08-17 只读检查时 Pocket_Plus 主工作树干净。正式首次写入前必须重新核对，不沿用本条历史判断。
- 当前基线测试为 87 项通过、2 项第三方警告；旧式测试夹具没有覆盖迁移后 NPY 的真实服务器读取。

## 已完成前置产物

- 完整体数组迁移、严格日期/质量/资产划分和第三版 `0:5:5` BOX 池已经完成并通过独立验收。
- 正式 Job `343572/343835/345237/346035/346063` 均为 `COMPLETED 0:0`。
- train、validation、calibration 分别为 13,717、200、100 个 PDB；固定 validation 请求为 16,525 个 bias 和 16,525 个 context。
- 第二版 `stage1_preparation_box_pool_2` 和现有冻结 release 没有被本轮数据准备读取、改写或删除。
- 代表性 PDB `3j6b` 的 `exp.npy` 与 `sim.npy` 为 `float32 (1,482,482,482)`，`union_mask.npy` 为同形状 `bool`，`ligand_dist.npy` 为同形状 `float16`。`receptor_tokens.npz` 保存 `coords float32 (111206,3)`、`feat float32 (111206,49)` 和 `is_backbone bool (111206,)`。

## 实施前代码审计

- 当前 `Stage1Dataset` 仍读取 `exp.npz:grid`、`sim.npz:grid`、`ligand_area.npz:union_mask` 和 `ligand_dist.npz:distance`。这些字段已从正式 NPZ 移出，因此当前生产 Dataset 不能直接消费第三版数据。
- 当前读取路径会对完整密度或距离数组执行有限性、无穷值和非负性扫描；如果直接套在 mmap 上，缓存未命中仍会把完整图读入，不能达到减少 I/O 的目标。
- 当前 Dataset 已在内部把 49 维 `feat` 与 `is_backbone` 拼接。用户决定把该操作移到模型输入边界，Dataset/Collator 改为分别传递两个字段。
- 体素分支和点分支目前已经各自拥有独立 `input_proj`，不需要再次重写该结构。
- 当前结构预测使用一个总开关同时创建 protein、nucleic 和 distance 三个 head。双卡无主链配置若只把 protein/nucleic 损失置零，会与 `ddp_find_unused_parameters=false` 冲突。
- 当前请求模块仍包含 `box_sample_fraction`、旧 split/BOX 构建逻辑和历史兼容分支；删除时必须保留裁块和推理仍调用的通用请求类型。
- `训练与运行/sh/infer/prepare_inference_pdb_lists.sh` 仍从旧 `stage1_box_pool.py` 导入 `_load_split_pdb_ids`。旧构建器不能在迁移该只读依赖前删除。
- 每轮请求源由主进程更新，因此 DataLoader 必须保持 `persistent_workers=False`，否则常驻 worker 会继续使用旧 epoch 的请求副本。

## 已冻结决定

- 只保留同一个生产 `Stage1Dataset`，不并存 V2/V3 Dataset。旧代码直接删除，由 Git 保存历史。
- 训练仍采用全局 BOX 打散，不按 PDB 分组。
- `unet_c1/no_mainchain` 只关闭 protein/nucleic 主链预测与损失，保留 binding receptor voxel 辅助损失和 ligand-distance 预测/损失。
- 结构 head 拆成 protein、nucleic、distance 三个独立开关；两套 U-Net 分别使用 `true/true/true` 与 `false/false/true`。
- 本轮 Find_0 与 Find_1 只提供 CPC1，不自动串联 CPC2。
- 正式训练由用户复制出的任务提交和监视；当前任务只实现并验证入口。完成时间节点 1 后，当前任务继续新版推理程序。
- 监视不使用 heartbeat；稳定运行后用命令自然等待，每 10 或 20 分钟检查一次。

## 严格审查

独立严格审查者最初指出 mmap 整图扫描、双卡未使用参数、推理清单依赖、fraction 删除不完整、常驻 worker、误删推理脚本和验证覆盖不足七项阻断。修订计划逐项纳入后，审查者最终回复 `APPROVED`。

审查批准只覆盖实施方案，不代表代码已经实现，也不授权正式全量训练。

## 下一步实施顺序

1. 重新核对 Pocket_Plus Git 唯一最新端点和工作树，建立独立双线工作树。
2. 替换统一 Dataset/Loader 的第三版读取路径，并删除完整 `fraction` 功能。
3. 把 49+1 特征拼接迁移到模型输入边界，拆分三类结构 head 开关。
4. 迁移推理清单读取依赖，再删除旧 split/BOX 构建器和旧训练脚本。
5. 建立四套配置及整洁的一键提交入口，执行单卡与双卡短程 smoke。
6. 严格审查实现、同步服务器验证、回填本记录和当前契约；不提交正式全量训练。

## 计划与实现差异

- 有益差异：尚未进入代码实现，暂无。
- 中性差异：尚未进入代码实现，暂无。
- 有害差异：尚未进入代码实现，暂无。
- 未完成范围：`文档/规划文档/Stage1第三版训练IO实施计划.md` 中的全部 Dataset、Loader、模型接缝、配置、脚本和 smoke 工作仍待实现。
