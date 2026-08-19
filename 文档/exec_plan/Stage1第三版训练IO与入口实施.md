# Stage1 第三版训练 I/O 与入口实施记录

本文记录 `文档/规划文档/Stage1第三版训练IO实施计划.md` 的实际实现。当前范围到代码、测试、审查、说明和 Git 双线收口为止；正式训练、训练监视与新版推理算法不属于本阶段。

## Git 与实现边界

- 实现基点：`8ff69abd608192d85686f73da2d1f9f15fe67a1e`。
- 实现分支：`codex/stage1-v3-training-io`。
- 用户后续决定不另建工作树，因此本轮从上述基点在现有 Pocket_Plus 工作区实现。
- 实现端点：`codex/stage1-v3-training-io@1df3ce2f188bc10aed7c3c1daa3588779cb0a9da`。
- 学习端点：`Learn/stage1-v3-training-io@850011c722d24203ff896c51d78b9deb6269229e`。
- 累计学习端点：`Learn/CUMULATIVE@850011c722d24203ff896c51d78b9deb6269229e`；收口时为按提交者时间形成的唯一最新本地分支端点。
- 实现端点与学习端点的 Git tree 均为 `291278f3d1571ece12aa104e0c14c9a1c9033d3c`，逐文件等价。
- 本轮不检查、不记录、不操作其他任务或服务器 allocation；任何训练启动都必须等待用户另行明确许可。

## 已完成实现

- `Stage1Dataset` 改为内存映射 `exp.npy`、`sim.npy`、`union_mask.npy` 与 `ligand_dist.npy`；只对实际 80³ 裁块执行有限值和距离非负检查。
- `Stage1TrainingRequestSet` 只解释 V3 manifest 与 pool，每个 epoch、每个 PDB 至多选择 50 个 occurrence，每个 occurrence 生成 5 个 bias 和 5 个 context 请求。
- `box_sample_fraction` 已从 Dataset、请求层、Hydra 配置、测试和活动文档删除。
- Dataset/Collator 返回 49 维 `atom_feat` 和独立 `atom_is_backbone`；模型输入边界按 `embed_head → point_backbone → online_pdb_feature_dim` 的顺序确定期望维数，需要时拼成 50 维。
- DataLoader 使用 `prefetch_factor=4`、`pin_memory=true` 与 `persistent_workers=false`。正式资源口径为单卡 16 CPU/16 workers，双卡总计 32 CPU、每 rank 16 workers。
- `unet_c1` 主链版保留 `0.05/0.05/0.3` 三项结构损失；无主链版保留三个结构头，使用 `0/0/0.3` 与双卡 `ddp_find_unused_parameters=true`。
- `Find_0.sh` 与 `Find_1.sh` 只执行 CPC1；`unet_c1_no_mainchain.sh` 是复用共同入口的薄包装。四个入口均指向第三版数据。
- V3 构建仍需的 occurrence、seed、bias/context 和 validation 冻结函数已集中到 `ops/stage1_data_preparation/utils/`。
- 推理 PDB 清单入口改读第三版 split，并按首次出现顺序去重候选记录中的 PDB 身份。
- 第二版 split/BOX 构建器、旧 materializer、重复训练脚本和已退出主线的历史目录从活动树删除；tracked 内容保留在 Git 历史中。

## 验证与审查

- 本轮开始前的相关基线为 87 项测试通过。实现后使用 `Pocket_Plus_windows` 环境运行针对性测试，74 项通过、2 项第三方警告；全量 pytest 为 407 项通过、10 项第三方或依赖弃用警告。四个正式 shell 入口均通过 MSYS2 `bash -n`。
- 逻辑与科学契约独立审查已给出 `APPROVED`，确认 V3 请求、NPY mmap、49+1 模型边界、DataLoader epoch 语义、U-Net 两种损失配置和 Find CPC1 入口一致。
- 技术表达与函数布局独立审查第一轮指出逐文件整理清单、旧文档、Docstring 与模型维数回退测试不足；修订后执行同问题窄口径复核，最终结论为 `APPROVED`。
- 本轮没有以服务器吞吐、首批等待、RSS 或缓存命中率作为放行条件，也没有启动训练。

## 计划与实现差异

- 有益差异：推理清单解析器不仅迁出已删除模块，还按候选记录级 split 的真实语义稳定去重 PDB，避免相同 PDB 导致清单脚本失败。
- 中性差异：初版计划要求独立工作树，用户后续明确改为从指定提交在现有工作区建立实现分支；Git 基点和双线等价要求未改变。
- 中性差异：初版计划写 `prefetch_factor=2` 和每 rank 14 workers，用户根据 NPY I/O 探查最终改为预取 4、每 rank 16 workers。
- 中性差异：初版计划拆分三个结构 head 开关，用户最终决定保留总开关，以 protein/nucleic 损失权重 0 和双卡 unused-parameter 配置实现无主链变体。
- 中性差异：初版计划要求四套服务器 smoke；用户后续明确要求先让基本代码就绪，不把吞吐退化或服务器 smoke 作为本轮前置条件。
- 有益差异：在用户允许删除无用历史文件后，实际清理范围扩展到旧 materializer、历史数据生成目录与重复训练脚本；每个 tracked 文件均在 Pocket_Plus `talk/refactor/stage1_v3_training_io.md` 逐项留痕。
- 有害差异：尚未发现。
- 未完成范围：正式训练、训练监视、新版推理程序和时间节点 2 的科学契约均未开始；训练启动仍需用户明确授权。
