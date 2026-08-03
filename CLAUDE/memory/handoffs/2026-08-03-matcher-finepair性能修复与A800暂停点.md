# Handoff: Matcher FinePair 性能修复与 A800 暂停点

Date: 2026-08-03

## Current State

Matcher 的科学契约未改，FinePair 已从 chunk 内逐配对 Python 调用改成完整候选框×occurrence 网格的联合批处理，并为适用调用加入显式 varlen Flash 后端。隔离实现工作树是 `C:\Users\15919\Desktop\AdaLigand_matcher_finepair_perf`，分支为 `codex/matcher-finepair-throughput`，工作区除被 Git 忽略的临时远端脚本外清洁。

无限时 A800 工作台是 Slurm Job `335261`，申请时位于 `gnode10`，资源为一张 A800 80G、16 CPU、QOS `cpu96`，`TimeLimit=UNLIMITED`。最后一次成功远端交互时，Job 由 `/home/penghongen/SIMPLE_RUN/pre_lock_335261` 阻止执行，`after_lock_335261` 存在，旧画像脚本尚未运行。此后登录节点持续在 SSH 密钥交换前主动断开，无法刷新 `squeue`；本轮没有删除 pre-lock、修改 after-lock、提交第二个 GPU Job 或运行远端命令。

## Completed

- 提交 `20702bf`：chunk 内全部候选框—occurrence 配对一次批量执行；标签在 checkpoint 外按候选框—真实 occurrence 批量构造；保持 `[C,S_pred,S_gt]`、完整 C×S、空 A 与原损失契约。
- 提交 `20702bf` 同时加入可选 `flash_attn_varlen_func`。只有 CUDA BF16/FP16、单 context、无 attention bias、带真实 token 掩码时启用；其它情况回退到 PyTorch scaled-dot-product attention。
- 本地完整 Matcher 回归为 40 passed、1 skipped。跳过项仅为必须在 CUDA 上执行的 Flash↔SDPA 输出与参数梯度等价测试。
- 契约审查确认同身份多个真实 occurrence 构成完整 `[S_pred,S_gt]` 笛卡尔关系；已有 objectives 测试继续覆盖 Hungarian 槽位交换后的第三轴选择。
- 可读性审查确认没有新增后端类或通用多模态框架；生产代码只新增一个补齐函数，`_run_fine_pairs` 只保留 chunk 循环。
- 提交 `fcb6e75`：新增 `ops/profile_matcher_throughput.py`，限时测量普通 Phase2 Dataset 的 batch、PDB、occurrence、优化和数据等待时间，并记录峰值显存与 OOM 阶段。
- 提交 `16340fa`：将 Job `334868` 超时、性能根因、等价优化、测试证据和 Job `335261` 暂停点写入 Matcher 执行记录。
- 项目安全同步曾成功上传 `20702bf` 的模型和 CUDA 测试文件；随后增加的吞吐脚本与执行记录尚未在 SSH 故障后重新同步。

## Decisions

- 不通过候选过滤、top-k、减少配对、改变图或损失来换取速度；这些都会改变训练分布或科学定义。
- `fine_pair_chunk_size` 的单位是一次联合 FinePair forward 中的候选框—occurrence 配对数，不是原子配对数。
- `torch.nn.functional.scaled_dot_product_attention` 不妨碍 Flash；当前显式 varlen Flash 只解决 padding mask 导致的 dense fallback 与 padded Q/K/V 开销。
- 性能验收分两类：先单独测 `9cpk` 极端样本，再用普通 Dataset 连续运行约一小时，报告平均 PDB 时间。正式训练仍需用户审阅最终 YAML 与 shell 后另行授权。
- 后续 GPU 作业不设置 Slurm 时限；当前 Job `335261` 已按此规则申请。

## Open Questions

- SSH 恢复后需要重新确认 Job `335261` 是否仍为 RUNNING，以及三个锁的实际状态。当前不能用连接故障推断 Job 已失败或仍在运行。
- CUDA 等价测试与新 `9cpk` 步耗时尚无服务器结果；通道数仍不能冻结。

## Next Actions

1. 恢复 SSH 后只读检查 `squeue -j 335261`、`pre_lock/try_lock/after_lock` 和远端两个文件的 SHA-256。
2. 使用被忽略的临时脚本 `tmp/matcher_finepair_perf_20260803/launch_cuda_equivalence.sh`。该脚本只有在 Job RUNNING、锁状态正确且远端 SHA 精确匹配时，才原子替换动态命令并删除 pre-lock。
3. 等 CUDA 测试结束并出现 try-lock，读取 Job out/err；必须确认测试实际调用 Flash 且输出、损失相关输出和参数梯度与 SDPA 在既定容差内一致。
4. 在同一 allocation 上运行修复后的 `9cpk` 双步画像，记录优化步秒数、allocated/reserved、OOM 与 Flash 实际调用。
5. 同一 allocation 上运行普通 Dataset 一小时吞吐画像。该画像不含周期性验证和 checkpoint 时间，结论中必须明确口径。
6. 根据两类画像调整 U-Net 通道或执行 chunk；不得改变科学契约。随后向用户展示最终 YAML 与正式 shell，请求正式长训练授权。
7. 完成双线 Git 学习历史与 `Learn/CUMULATIVE` 收口；当前三个实现提交尚未进入学习历史。

## Files To Reopen

- `matcher/model.py`
- `matcher/tests/test_model.py`
- `ops/profile_matcher_memory.py`
- `ops/profile_matcher_throughput.py`
- `configs/matcher/anchor_O_O_prime_phase2.yaml`
- `文档/exec_plan/Matcher_Anchor_OOPrime端到端实施.md`
- `grill_with_memory/07-28-17-50.md`
- `tmp/matcher_finepair_perf_20260803/launch_cuda_equivalence.sh`
