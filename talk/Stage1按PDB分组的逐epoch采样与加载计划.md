# Stage1 按 PDB 分组的逐 epoch 采样与加载计划

> 文档状态：讨论版实施计划，尚未实施，也尚未成为 Stage1 当前主规格。
>
> 记录日期：2026-08-10。
>
> 本文只规定下一版训练请求与 DataLoader 的候选设计。正在运行的 Stage1、AUTO、H200/H100/A800 任务，现有 AUTO 冻结清单、本地 AUTO 文件和服务器正式产物均不在本计划的修改范围内。

## 1. 目标与当前结论

本计划统一 Pocket Plus 主仓库与下一版 AUTO 实验的 Stage1 训练请求组织方式。两者都直接读取第二版 BOX 池：

```text
/storage/penghongen/AdaLigand/Ori_Data/stage1_preparation_box_pool_2
```

训练周期（epoch）内的请求生成顺序概括为：

```text
cap → ratio → expand → sort
```

- `cap`：每个 PDB 从全部 occurrence 中无放回选择至多 50 个一级候选。
- `ratio`：每个 PDB 从一级候选中选择 `ceil(一级候选数 × occurrence_ratio)` 个最终 occurrence。
- `expand`：每个最终 occurrence 按可配置的 `center:bias:context = 0/1:x:y` 从第二版 BOX 池选择实际 BOX。
- `sort`：每个训练周期打乱 PDB 顺序；同一 PDB 的 BOX 连续出现，并在它占据的每个 micro-batch 片段中按实际槽位数分配前景 BOX。

首版只在下列条件同时满足后进入正式训练主线：

1. 请求身份、数量、顺序、角色比例和 DDP 行为通过契约测试。
2. 使用真实 `0:1:1`、真实短 PDB 请求块进行 CPU-only Dataset/DataLoader 验证。
3. `Find_1` 的请求吞吐相对当前随机顺序至少提高 2.5 倍；`unet_c1` 不出现吞吐回退。
4. 用户确认 DDP 训练周期尾部的补齐或丢弃规则。

## 2. 与当前规格和当前实现的关系

### 2.1 AdaLigand 当前主规格

`文档/规划文档/Stage1训练实现计划.md` 当前仍规定：

- 每个 PDB 每个训练周期最多选择 50 个 occurrence；
- 每个选中 occurrence 使用固定 `1:5:3`；
- validation 清单一次生成并冻结；
- `Stage1Dataset`、物化过程和 Collator 由训练、验证及推理共同复用。

`文档/exec_plan/Stage1第二版BOX池与Find_0重训练实施.md` 记录了第二版 BOX 池和已运行实验使用固定 `0:5:5`。该执行记录是已经发生的历史，不因本计划而改写。

因此，本计划不是对当前规格的文字澄清，而是一个需要用户批准、实现、验证后再回填主规格的行为变更。

### 2.2 Pocket Plus 当前请求比例

当前代码 `C:\Users\15919\Desktop\Pocket_Plus\src\datasets\stage1_requests.py` 中的 `box_sample_fraction` 表示：

- `box_sample_fraction == 1.0`：每个训练周期重新生成完整请求；
- `box_sample_fraction < 1.0`：先生成训练周期 0 的完整 BOX 请求，再按全局比例取 `floor`，把固定子集写入 BOX 池根目录并在后续训练周期复用。

这个含义不等于“每个 PDB 先 cap 50，再按 occurrence 比例向上取整”。下一版不得静默重新解释 `box_sample_fraction`；应使用语义明确的新字段 `occurrence_ratio`。

旧训练由冻结的代码 release、配置和产物复现。新主线不为了兼容一次旧实验，把“全局 BOX 比例冻结”和“逐 PDB occurrence 比例”混进同一套隐式分支。

### 2.3 AUTO 当前冻结契约

当前 AUTO 文件 `C:\Users\15919\Desktop\AUTO\Pocket_Plus\文档\规划文档\unet_c1-autoresearch冻结契约.md` 仍规定：

- 每个 PDB 固定选择 `ceil(0.05 × min(50, occurrence 数))` 个 occurrence；
- occurrence 与 BOX 候选前缀一次冻结，全部候选复用；
- `center + bias + context == 10`；
- 当前基线为 `0:5:5`。

当前 AUTO 适配器 `ops/autoresearch_unet_c1/` 是该冻结实验的任务专用实现。不得在正在进行的实验中替换它。本计划面向下一版 AUTO：下一版停止维持“总数必须为 10”的专用科学分支，改为消费与 Pocket Plus 主线相同的逐训练周期请求生成器；AUTO 只提供 PDB 清单、训练配置和运行入口。

## 3. 已有性能证据及其限制

2026-08-10 的只读 CPU-only 验证使用真实 `Stage1Dataset`、第二版 BOX 池、24 核 CPU 和随机旋转，不加载 GPU 或模型。证据位于：

```text
本地：tmp/stage1_pdb_group_loader_bench_20260810/
服务器：/storage/penghongen/tmp/stage1_pdb_group_loader_bench_20260810/
Slurm Job：339000，COMPLETED 0:0
```

主要观测如下：

| 观测项目 | 已有结果 | 能支持的结论 |
|---|---:|---|
| 当前随机顺序参考吞吐 | 约 3.36 requests/s | 用于计算分组读取的工程收益目标 |
| `Find_1`，16 workers，prefetch 2 | 9.369 requests/s | 约为参考吞吐的 2.789 倍 |
| `Find_1`，20 workers，prefetch 2 | 9.642 requests/s | 约为参考吞吐的 2.870 倍 |
| `Find_1`，24 workers，prefetch 1 | 10.982 requests/s | 约为参考吞吐的 3.269 倍 |
| `Find_1`，24 workers，prefetch 4 | 11.662 requests/s | 约为参考吞吐的 3.471 倍 |
| 冷随机 `Find_1`，20 workers，prefetch 2 | 1.464 requests/s，读取 200.7 GiB | 随机跨 PDB 请求会重复读取大型完整图资产 |
| 分组 `Find_1`，816 个请求 | 读取约 4.8–6.1 GiB | batch 内连续 PDB 请求能命中 worker 内缓存 |

这些结果证明“batch 内 PDB 连续”可以消除主要重复读取，并且 56 维密度通道实时构造在消除重复 I/O 后才成为下一层 CPU 成本。

这些结果不能直接证明下一版 `0:1:1` 仍有 2.5 倍以上收益。已有验证中的 PDB 块平均约为 54–63 个请求；下一版预计平均只有约 8 个请求。首版正式采用前必须用真实短块重新验证。

另一个独立事实是：当前请求源冷启动时串行打开 13,710 份 PDB NPZ，已有一次观测耗时约 17 分 44 秒。它影响训练启动时间，但不是训练稳定阶段 GPU 饥饿的主要原因，本计划首版不同时重写该启动过程。

## 4. 输入数据与配置契约

### 4.1 第二版 BOX 池字段

每个 PDB 的 NPZ 至少提供：

| 字段 | 形状 | 含义 |
|---|---:|---|
| `occurrence_id` | `(N_occ,)` | 当前 PDB 的 occurrence 编号 |
| `center_start_zyx` | `(N_occ, 3)` | 每个 occurrence 唯一 center BOX 的 ZYX 起点 |
| `bias_start_zyx` | `(N_occ, 30, 3)` | 每个 occurrence 的 30 个预计算 bias BOX 起点 |
| `context_start_zyx` | `(N_context, 3)` | 当前 PDB 共享的预计算 context BOX 起点 |

所有训练 BOX 必须引用这些已有起点。请求生成器不实时发明新 BOX，不修改 BOX 池，也不向 BOX 池根目录写入比例选择文件。

### 4.2 下一版训练配置

| 配置字段 | 有效范围 | 具体作用 |
|---|---:|---|
| `occurrence_cap_per_pdb` | 正整数，首版固定 50 | 每个 PDB 的一级 occurrence 候选数上限 |
| `occurrence_ratio` | `0 < ratio <= 1` | 每个 PDB 从一级候选中保留的 occurrence 比例 |
| `entry_ratio.center` | 0 或 1 | 每个最终 occurrence 是否使用唯一 center BOX |
| `entry_ratio.bias` | 0–30 的整数 | 每个最终 occurrence 选择的 bias BOX 数 |
| `entry_ratio.context` | 非负整数 | 每个最终 occurrence 选择的 context BOX 数 |
| `request_seed` | 整数 | 与训练周期编号共同决定 occurrence、BOX 和 PDB 顺序 |
| `batch_size` | 正整数 | 单个 DDP rank 的物理 micro-batch 容量；梯度累积不改变该容量 |
| `num_workers` | 非负整数 | 单个 DataLoader 的读取进程数，只影响运行效率 |
| `prefetch_factor` | 正整数 | 每个 worker 提前准备的 batch 任务数，只影响运行效率 |
| `pdb_cache_max_bytes` | 非负整数 | 每个 worker 可保留的完整 PDB 资产容量，只影响运行效率 |

至少一种 BOX 角色必须启用：

$$
center + bias + context > 0.
$$

若要求“每个非空 PDB 一定产生训练请求”，还必须满足以下任一条件：

- `center + bias > 0`；或
- 该 PDB 的 `context_start_zyx` 非空。

计划中的主要 AUTO 配置 `0:1:1` 具有一个 bias，因此不受空 context 池影响。

## 5. 每个训练周期的请求算法

### 5.1 随机数边界

主进程为训练周期 `epoch` 建立一个随机数生成器：

```python
np.random.default_rng(np.random.SeedSequence([request_seed, epoch]))
```

以下操作只在主进程发生：

1. PDB 顺序打乱；
2. occurrence 一级候选与最终候选选择；
3. bias、context 候选选择；
4. PDB 内前景与背景 BOX 的排列；
5. micro-batch 请求下标的生成。

Dataset worker 不决定 BOX 身份或出现顺序。worker-local 随机数仍可服务现有同步 90° 空间旋转，但不进入请求选择。

### 5.2 cap：每个 PDB 建立一级候选池

设 PDB `p` 具有 `n_p` 个 occurrence。空 PDB 不产生训练请求。非空 PDB 的一级候选数为：

$$
c_p = \min(50, n_p).
$$

先随机排列该 PDB 的全部 occurrence，再取前 `c_p` 个，形成当前训练周期的一级候选池。不同训练周期重新排列，因此 occurrence 身份可以变化。

### 5.3 ratio：每个 PDB 选择最终 occurrence

设 `r` 为 `occurrence_ratio`。最终 occurrence 数为：

$$
m_p = \left\lceil c_p r \right\rceil.
$$

因为 `c_p > 0` 且 `0 < r <= 1`，`m_p` 自然至少为 1，不需要：

```python
max(1, ceil(capped_count * occurrence_ratio))
```

保留一级候选排列的前 `m_p` 个 occurrence。该规则有以下明确科学后果：

- 同一 PDB 内无放回选择，occurrence 的出现不独立；
- 每个非空 PDB 至少选择一个 occurrence，小 PDB 的单个 occurrence 入选概率通常高于大 PDB；
- PDB 之间不再按 occurrence 总数形成全局独立同分布样本；
- 不同训练周期允许出现相同 occurrence，不保证逐项排斥上一周期。

这些后果是本计划接受的训练契约变化。

### 5.4 expand：从第二版 BOX 池选择角色

对每个最终 occurrence：

1. `center == 1` 时加入唯一 center BOX；`center == 0` 时不加入。
2. 从该 occurrence 的 30 个 bias 候选中无放回选择 `bias` 个。
3. context 池数量不少于 `context` 时无放回选择。
4. context 池非空但数量不足时，沿用当前行为，有放回选择到要求数量。
5. context 池为空时不伪造 context BOX，该 occurrence 只产生 center 和 bias。

设 `q_p` 表示 PDB `p` 的 context 池是否非空，非空为 1，空为 0。该 PDB 当前训练周期的实际 BOX 数为：

$$
B_p = m_p\left(center + bias + q_p \cdot context\right).
$$

因此，在固定 BOX 池、`occurrence_ratio` 和角色配置下，每个训练周期的请求总数固定；变化的是 occurrence 身份、bias/context 候选身份以及出现顺序。

为了让下一版 AUTO 每个训练周期的 BOX 数接近旧 5% 实验，应在 Dataset 外根据上式评估少量 `occurrence_ratio` 候选。当前粗估约为 0.20–0.23，但正式值必须用目标清单和实际空 context PDB 重新计算。本计划不引入精确 `target_boxes_per_epoch`，也不要求与旧数量逐项相等。

### 5.5 sort：PDB 连续与 micro-batch 前景分配

每个训练周期先随机排列 PDB。一个 PDB 的全部实际请求在逻辑序列中连续；当前 PDB 结束后才开始下一个 PDB。PDB 边界可以出现在 micro-batch 内，因此一个 micro-batch 可以包含两个或更多很小的 PDB，但每个 PDB 自身不被其他 PDB 插入打断。

对当前 PDB，把 center 和 bias 合并为前景列表，把 context 作为背景列表。设：

- `F_left`：尚未放入请求序列的前景 BOX 数；
- `N_left`：尚未放入请求序列的全部 BOX 数；
- `s`：当前 PDB 在当前 micro-batch 片段实际占据的槽位数。

该片段应放入的前景数使用一个明确的非负数最近整数规则：

$$
f = \left\lfloor \frac{s F_{left}}{N_{left}} + \frac{1}{2} \right\rfloor.
$$

完成片段后更新：

$$
F_{left} \leftarrow F_{left} - f,
$$

$$
N_{left} \leftarrow N_{left} - s.
$$

最后一个片段满足 `s == N_left`，因此会接收全部剩余前景 BOX。该规则具有以下边界：

- 只按当前 PDB 在该 micro-batch 中实际填入的槽位数分配；
- 完整片段和不完整片段使用同一公式；
- 不复制 BOX，不把 PDB 片段假装成完整 micro-batch；
- 不修改 loss 或样本权重；
- center 与 bias 只保留各自请求身份，不分别追求 micro-batch 比例。

前景列表和背景列表分别打乱。每个片段随机选择 `f` 个相对位置填前景，其余位置填背景。PDB 结束后的剩余 micro-batch 槽位由下一个 PDB 继续填入。

## 6. DDP、worker 与预取边界

### 6.1 BatchSampler 必须拥有批次顺序

当前按单个样本下标随机打乱的 `DistributedSampler` 会破坏 PDB 连续性，不能直接叠加在新请求顺序上。下一版需要一个 Stage1 专用 BatchSampler：它直接产出一个 micro-batch 的完整请求下标列表，再以完整 micro-batch 为单位分配给 DDP rank。

首版不实现：

- 把一个 PDB 永久绑定到某个 worker；
- 活跃 PDB 窗口和轮转调度；
- 跨训练周期保留 PDB–worker 亲和关系；
- 为了减少极少数跨 batch PDB 重载而建立额外进程间通信。

普通 PyTorch DataLoader 会把一个完整 batch 的请求下标作为一个 worker 任务。因此，即使没有硬亲和，同一 micro-batch 内的首个请求加载完整 PDB 资产后，其余同 PDB 请求仍可复用该 worker 的缓存。这是已有性能验证证明的主要收益来源。

### 6.2 DDP 训练周期尾部仍待决定

所有 rank 必须具有相同的反向传播步数。若 micro-batch 总数不能被 DDP rank 数整除，需要在以下两种简单行为中选择一种：

1. **补齐**：沿用当前 `DistributedSampler` 的方向，重复极少量请求或 batch，使每个 rank 的步数相同。优点是不丢选择结果；缺点是训练周期尾部存在重复样本。
2. **丢弃**：丢弃最后一个不完整 DDP 物理步。优点是不重复；缺点是实际消费的请求少于 `cap-ratio-expand` 生成的请求，并可能使最后几个 PDB 本周期未被完整消费。

首版实现前必须由用户选择，不能在代码中静默采用。这个问题与“一个 PDB 在 micro-batch 中只占部分槽位”不同；§5.5 已经解决后者。

### 6.3 `persistent_workers` 首版关闭

训练请求会在每个训练周期由主进程替换。若开启 `persistent_workers=True`，worker 进程可能继续持有上一训练周期的 Dataset 副本，导致新请求身份没有传播。

因此首版固定：

```text
persistent_workers = false
```

只有在独立测试证明 worker 可以读取当前训练周期请求、且不依赖隐式进程复制后，才单独讨论启用持久 worker。`num_workers`、`prefetch_factor` 和 worker-local PDB 缓存容量仍可在不改变请求契约的前提下调优。

## 7. 计划中的代码职责

正式实现预计只涉及 Pocket Plus 主仓库及下一版 AUTO 的配置接入。AdaLigand 继续保存规划、执行证据和当前规格，不承载训练运行代码。

### 7.1 Pocket Plus 主仓库

| 计划位置 | 计划职责 |
|---|---|
| `src/datasets/stage1_requests.py` | 实现逐训练周期 `cap-ratio-expand`，返回具有明确 PDB、occurrence、角色和候选下标的请求 |
| `src/datasets/stage1_batch_sampler.py` | 新增小型、独立、可单元测试的 PDB 分组 BatchSampler；只负责 PDB 顺序、前景槽位分配、micro-batch 和 DDP 下标 |
| `src/datasets/stage1_dataset.py` | 继续物化一个明确请求；不得加入 occurrence 选择、角色配额或 PDB 排序 |
| `src/train.py` | Stage1 训练使用专用 BatchSampler；普通 Dataset 和非 Stage1 入口保持原行为 |
| `configs/dataset/stage1_find.yaml` | 用 `occurrence_ratio` 取代新主线中的 `box_sample_fraction` 语义 |
| `configs/dataset/stage1_unet_c1.yaml` | 与 Find 使用同一 occurrence 选择字段和请求顺序契约 |
| `configs/train/stage1_cpc1.yaml` | 显式保存 workers、prefetch、缓存和 `persistent_workers=false` |

`Stage1Dataset.__getitem__` 和 56 维密度通道构造不因本计划改变数值算法。相同 `ResolvedStage1Crop` 请求在改造前后必须产生相同字段、形状、数据类型和数值；变化只发生在训练请求集合及其顺序。

### 7.2 下一版 AUTO

下一版 AUTO 不再另外维护“固定总数 10”的 Dataset 科学分支。它应：

1. 使用与 Pocket Plus 主线相同的请求生成器和 BatchSampler；
2. 只通过 PDB 清单、`occurrence_ratio`、`entry_ratio`、训练周期数和运行参数描述实验；
3. 仍从共享第二版 BOX 池只读取 BOX；
4. 不向共享 BOX 池写 selection、缓存或实验产物；
5. 用新的实验根保存自身配置、日志和 checkpoint。

正在进行的 AUTO 冻结实验及其 `ops/autoresearch_unet_c1/` 适配器保持不变。只有新版本获得用户明确授权后，才更新 AUTO 的冻结契约和执行计划。

## 8. 实施顺序

### 阶段 0：冻结未决边界

实施前确认：

1. DDP 尾部采用补齐还是丢弃；
2. 下一版 AUTO 的目标 `entry_ratio` 和训练周期数；
3. 目标 DDP 卡数与单卡物理 `batch_size`；
4. 用于接近旧 5% BOX 总数的正式 `occurrence_ratio`。

`occurrence_ratio` 只需接近目标 BOX 总数，不建立精确目标求解器。

### 阶段 1：实现纯请求算法

先实现并测试不读取 Dataset 张量的纯逻辑：

1. 读取 PDB BOX 池元数据；
2. cap 与 ratio 选择；
3. 通用 `0/1:x:y` 展开；
4. PDB 顺序与请求身份复现；
5. context 空池和不足池行为。

### 阶段 2：实现分组 BatchSampler

实现：

1. PDB 连续请求块；
2. micro-batch 槽位片段；
3. center+bias 前景分配公式；
4. 片段内随机位置；
5. 用户选择的 DDP 尾部行为；
6. `set_epoch(epoch)` 后的确定性重建。

### 阶段 3：接入统一训练入口

把 BatchSampler 接到 `src/train.py`，并确保：

- Find 与 unet 使用相同请求身份和顺序规则；
- validation 清单、validation 不增强和完整图推理保持现状；
- worker 不执行 BOX 身份选择；
- `persistent_workers` 首版关闭；
- 当前普通 Dataset 和 Selector BatchSampler 不受影响。

### 阶段 4：临时 CPU-only 性能验证

性能验证不训练模型，不启动 GPU，不修改或暂停任何现有任务。代码、日志和产物只放在新的临时目录，例如：

```text
本地：C:\Users\15919\Desktop\AdaLigand\tmp\stage1_grouped_loader_shortblock_<日期>/
服务器：/storage/penghongen/tmp/stage1_grouped_loader_shortblock_<日期>/
```

验证结束后保留自包含日志和摘要；临时代码不得被正式包导入，也不得写入 Pocket Plus、AUTO 或共享 BOX 池。

### 阶段 5：用户放行与正式回填

性能和正确性证据提交用户审核。用户批准后再：

1. 把新行为写入 `文档/规划文档/Stage1训练实现计划.md` 的训练请求与 DataLoader 章节；
2. 建立或更新对应执行记录；
3. 更新 `文档/mapping/计划执行映射.md` 的覆盖状态；
4. 更新 Pocket Plus Dataset 当前契约文档和配置说明；
5. 为下一版 AUTO 单独更新冻结契约，不回写正在进行的旧实验。

本文在上述步骤完成前保持“讨论版”，不进入映射索引的已完成状态。

## 9. 正确性验收

### 9.1 请求选择测试

- `occurrence_ratio` 拒绝 0、负数和大于 1 的值。
- 空 occurrence PDB 产生 0 个请求。
- 每个非空 PDB 的最终 occurrence 数严格等于 `ceil(min(50,n_p) × ratio)`。
- occurrence 一级候选和最终候选均无放回。
- `0:1:1`、`1:2:3`、`0:5:5`、纯前景和纯 context 配置均有覆盖。
- bias 数量限制为 0–30，并保持无放回。
- context 足够、不足但非空、完全为空三种情况与当前契约一致。
- 所有 `resolved_start_zyx` 都来自第二版 BOX 池已有数组。

### 9.2 顺序与 batch 测试

- 每个训练周期的 PDB 主键顺序是一个随机排列。
- 同一 PDB 的逻辑请求区间连续。
- PDB 边界 micro-batch 可以由下一个 PDB 填满，不额外 padding。
- 每个 PDB 的前景 BOX 总数保持不变。
- 每个 micro-batch 片段的前景数严格符合 §5.5 公式。
- 片段内部前景位置可复现且不是固定前缀。
- DDP 各 rank 的训练步数相同，并符合用户选择的尾部规则。

### 9.3 弱确定性目标

在以下条件全部相同时：

```text
BOX 池 manifest
PDB 清单
request_seed
epoch
DDP 卡数与 rank
单卡 batch_size
num_workers
prefetch_factor
```

必须得到相同的 BOX 身份和 sampler 顺序。改变 DDP 卡数、batch size、workers 或 prefetch 后，不承诺跨配置保持同一顺序。

该保证只覆盖请求身份和顺序。训练增强后的张量逐元素相等仍取决于现有 worker 随机种子和旋转实现，不在本计划中通过每 BOX 哈希身份解决。

### 9.4 Dataset 数值等价

从新旧入口取同一个明确 `ResolvedStage1Crop`，分别验证：

- 原始密度 BOX；
- hardmask 与 voxel target；
- receptor 原子身份、坐标与特征；
- `unet_c1` 输入通道；
- `Find_0` 与 `Find_1` 的 56 维密度通道；
- Collator 生成的 dense 和 ragged 字段。

除现有随机旋转外，字段、形状、数据类型和数值必须一致。BatchSampler 不得改变 Dataset 的科学计算。

## 10. 短 PDB 块性能验证

### 10.1 验证对象

必须同时覆盖：

1. `unet_c1`：不实时构造 Find 的 56 维密度通道；
2. `Find_1`：实时构造 56 维密度通道，是主要性能放行对象。

请求配置使用下一版真实 `0:1:1` 和正式候选 `occurrence_ratio`，使 PDB 块长度与计划训练一致。不能继续用平均 54–63 个请求的长块代替。

### 10.2 对照方式

对同一批明确请求建立两种顺序：

- 随机顺序：模拟当前跨 PDB 读取；
- PDB 分组顺序：使用本文 BatchSampler。

两组必须保持相同的 BOX 身份、角色数量、随机旋转开关、Dataset 配置、CPU allocation 和缓存上限。只允许顺序、workers 和 prefetch 作为实验变量。

优先测试：

```text
num_workers ∈ {16, 20, 24}
prefetch_factor ∈ {1, 2, 4}
```

无需人为限速。每个试验记录真实节点、开始和结束时间、缓存状态、请求数及失败原因；不能只保留最好的一项。

### 10.3 实时指标

至少记录：

- requests/s；
- batch 获取时间的 p50、p95、p99 和最大值；
- 进程读取字节增量；
- PDB 资产缓存 hit、miss 和 reload 次数；
- 各 worker CPU 时间和主存峰值；
- Find 56 维密度通道构造耗时；
- sampler 生成耗时与训练周期请求总数。

### 10.4 放行门槛

`Find_1` 是主门槛：

$$
\frac{\text{PDB 分组 requests/s}}{\text{同请求随机顺序 requests/s}} \ge 2.5.
$$

若同节点重新得到约 3.36 requests/s 的当前参考吞吐，则 PDB 分组绝对吞吐应至少达到约 8.4 requests/s。

`unet_c1` 的 PDB 分组吞吐不得低于同请求随机顺序。若结果波动跨越门槛，应重复交叉顺序试验，不能只选择受页缓存预热帮助的一次运行。

通过 Dataset/DataLoader 门槛只能证明 CPU 请求供给提速，不能自动等同于端到端训练速度提高 2.5 倍。端到端收益还受 GPU 前向、反向和优化器时间限制；本计划不借 CPU-only 结果承诺未经测量的训练倍数。

## 11. 首版明确不做的内容

- 不建立精确 `target_boxes_per_epoch` 或为一次 AUTO 实验服务的目标数量求解器。
- 不为每个 BOX 设计哈希随机键、`duplicate_ordinal` 或跨配置稳定身份。
- 不保证改变 DDP 卡数、batch size、workers 或 prefetch 后仍得到相同顺序。
- 不保证相邻训练周期完全没有重复 occurrence 或 BOX。
- 不实时生成第二版 BOX 池之外的新 BOX。
- 不改变 Find 的 56 维密度通道算法、模型、loss、优化器或训练增强。
- 不实现 PDB–worker 硬亲和、活跃 PDB 窗口或进程间共享完整 PDB 数组。
- 不在首版解决 13,710 份 PDB NPZ 的串行冷启动耗时。
- 不修改 validation occurrence 身份、冻结 validation 清单或完整图推理入口。
- 不触碰正在运行的训练任务、冻结 release、AUTO 旧实验、本地 AUTO 文件或服务器正式数据。

## 12. 风险与未决问题

### 12.1 已接受的科学变化

按 PDB cap、向上取整和分组顺序会改变 occurrence 的边际概率与相邻样本相关性。它不再等价于从全局 occurrence 或 BOX 请求中独立抽样。用户已接受这一方向，但正式回填主规格时仍必须明确记录。

### 12.2 尚未证明的性能外推

长 PDB 块验证达到 2.8–3.47 倍，不代表平均约 8 个请求的短块必然达到 2.5 倍。若短块未过门槛，应先量化：

- PDB 是否频繁跨 micro-batch；
- 同一 PDB 是否被多个 worker 各自重载；
- 56 维通道是否已成为主耗时；
- worker 数和 prefetch 是否造成主存或调度竞争。

只有证据表明跨 worker 重载仍是主要瓶颈时，才重新讨论硬亲和；首版不预先实现。

### 12.3 DDP 尾部行为

补齐会带来极少量重复，丢弃会破坏“所有已生成请求都被消费”。这是当前唯一必须在实现前由用户选择的算法边界。

### 12.4 context 空池

当前规则允许 context 池为空，因此纯 context 配置可能使某个非空 PDB 不产生请求。主要配置 `0:1:1` 不受影响。若未来允许 `0:0:y`，必须把“空 context PDB 跳过”明确写入该实验契约，不能继续声称每个非空 PDB 都有训练样本。

### 12.5 持久 worker

`persistent_workers=True` 可能让 worker 使用上一训练周期的请求副本。首版关闭它的代价是每个训练周期重新创建 worker；若该启动成本后来成为主要问题，应作为独立、可验证的优化处理。

## 13. 本计划的完成定义

只有满足以下全部条件，本计划才可从“讨论版”转为当前实施规格：

1. 用户选择 DDP 尾部规则并确认最终配置字段。
2. Pocket Plus 实现通过请求、batch、DDP、Dataset 数值等价和现有 Stage1 回归测试。
3. 下一版 AUTO 使用同一请求生成器，不保留新的任务专用 Dataset 科学分支。
4. 真实 `0:1:1` 短块 CPU-only 验证达到 `Find_1 >= 2.5×` 门槛，且 `unet_c1` 不回退。
5. 实验代码、日志和产物全部位于明确临时目录，没有污染共享 BOX 池、Pocket Plus 正式产物或 AUTO 旧实验。
6. 用户审核性能与科学后果后明确批准主线采用。
7. AdaLigand 当前规划、执行记录、映射索引和 Pocket Plus Dataset 契约完成一致回填。

在此之前，本文只是一份可以审核和修改的候选实施计划，不授权启动服务器作业、修改训练代码或接管任何运行任务。
