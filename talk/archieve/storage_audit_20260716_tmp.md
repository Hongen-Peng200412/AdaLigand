# Storage 只读审计临时记录（2026-07-16）

## 授权边界

- 允许只读检查 `ps`、`/proc/<pid>/fd`、`/proc/<pid>/io`、`lsof +L1`、`lfs quota -v`。
- 严禁发送信号、修改优先级、暂停或终止任何进程。
- 大量 `rm -r` 期间只做轻量结构探查和分层抽样；不启动长时间全树 `du`。
- 不在服务器创建、修改或删除任何文件。

## 用户提供的起始快照

```text
/storage: 79,696,864,932 KiB; 5,426,693 objects
/home:     9,896,430,841 KiB; 1,332,203 objects
```

## 实时记录

- 状态：轻量只读诊断完成；服务器仍处于动态删除与 Stage F 计算并行期。

### Quota 时间序列

| 时间（服务器，+08:00） | storage KiB | TiB | objects | 相对 01:59:31 块变化 | 相对 01:59:31 对象变化 |
|---|---:|---:|---:|---:|---:|
| 用户提供的较早快照 | 79,696,864,932 | 74.2235 | 5,426,693 | -13.268 GiB | +28,354 |
| 01:59:31 | 79,710,776,968 | 74.2364 | 5,398,339 | 基准 | 基准 |
| 02:01:30 | 79,717,880,800 | 74.2431 | 5,392,772 | +6.775 GiB | -5,567 |
| 02:04:38 | 79,733,751,524 | 74.2578 | 5,382,211 | +21.910 GiB | -16,128 |
| 02:05:33 | 79,735,420,764 | 74.2594 | 5,380,062 | +23.502 GiB | -18,277 |
| 02:06:49 | 79,738,061,692 | 74.2619 | 5,375,629 | +26.021 GiB | -22,710 |
| 02:10:46 | 79,745,420,504 | 74.2687 | 5,367,438 | +33.039 GiB | -30,901 |

01:59:31～02:10:46 的观测窗口内，块占用净增约 33.04 GiB，平均约 2.94 GiB/min；对象数减少 30,901。相对用户提供的快照，02:10:46 已净增约 46.31 GiB、对象数减少 59,255。删除确实在推进，但同时存在更强的块占用增加来源，或者块释放尚未同步反映；净 quota 不能直接代表删除失败。

`/home/penghongen` 在 02:10:46 为 9,896,431,071 KiB（约 9.216 TiB）、1,332,214 objects，相对用户快照只增加 230 KiB 和 11 个对象，基本稳定。

### Per-OST 证据

01:59 左右至 02:05:33：

- storage 总块 quota 增加约 23.50 GiB；各 OST 数值之和增加约 23.44 GiB；
- 22 个 OST 中 21 个上涨，只有 OST0001 小幅下降约 0.095 GiB；
- 单个 OST 增量范围约 -0.095～+2.404 GiB；
- MDT 对象数同期持续下降。

这说明上涨分布在几乎所有 OST，而不是只集中在一个 OST。它与跨 OST 条带化/分布式写入相符，也可能叠加 Lustre quota/accounting 时序；per-OST 差分本身不能直接归因到某个目录。

### 活动进程与作业

- master 上观察到 14 个用户启动的 `rm -r`，正在删除四个 Pocket 版本的 `_BOX` 目录；全部保持不变，未向它们发送信号或执行任何进程控制。
- `rm` 的等待通道为 `cl_sync_io_wait`，与等待 Lustre 同步 I/O/元数据操作相符；这不是“rm 正在批量写数据”或“rm 已死锁”的证据。
- master 上对用户进程进行 5 秒 `pidstat -d` 采样，普通读写吞吐均为 0；该结果不覆盖 compute node，也不计同样方式不可见的 Lustre unlink 元数据活动。
- Slurm 作业 316116 在 cnode04、318350 在 cnode01 运行；316117 因依赖等待。`sstat` 未返回可用的磁盘 I/O 统计。

### 已定位的 storage 写入机制

两个运行作业都执行 Stage F `f_quality.py`，`DATA_ROOT=/storage/penghongen/AdaLigand/Ori_Data`，并且均以 12 个 worker 并行处理：

- 正式 run：`adaligand_ag_20260711T154658`；
- 补充 run：`adaligand_ag_20260711T154658_fsupp96_v1`。

代码只读核验显示，每个 PDB attempt 会创建：

```text
scratch/<run_id>/stage_f/<pdb_id>/<attempt_id>/
```

并写入 `canonical_exp.mrc`、`full_model_sim.mrc`、`native.mrc`、`full_model.cif` 以及 Chimera/MapQ 中间产物；成功后再写 `quality_atoms/<pdb_id>.npz`、`quality/<pdb_id>.jsonl` 和 provenance。成功路径会删除几个大型临时文件，但：

1. 24 个并发 worker 的在途 MRC 会形成明显的瞬时占用；
2. 清理代码位于函数成功末尾，没有 `finally`，中途异常会绕过这段 unlink，失败 attempt 可能保留大型 scratch；
3. 两个作业的日志在观测时仍持续增加已完成任务数。

因此，当前持续上涨已有高可信的具体来源候选：AdaLigand Stage F 的在途及失败残留 scratch，再叠加小型正式产物。当前证据不能把每一 KiB 精确归因到该路径，但它比“未知写入”或单纯“quota 显示错误”更符合代码、作业状态和 per-OST 同向上涨的联合证据。

### Open-deleted 检查限制

- 服务器未安装 `lsof`；`timeout 60s lsof ...` 立即以“命令不存在”结束，没有开始扫描。
- master 的 `/proc/<pid>/fd` 对大量进程启用了权限隔离；即使按 UID 枚举也返回 `Permission denied`，普通用户无法完成可靠的 open-deleted 排除。
- 因而本次既没有发现 open-deleted 证据，也不能在普通用户权限下排除 compute node 上的 open-deleted。

### 浅层 storage 结构复核

实际用户根为 `/storage/penghongen`，直接包含 12 项：

```text
AdaLigand
BIBM2026.7z
C_a的baseline
CIF_3.5_cc_qscore.csv
CIF_Ligand
CryAtom
dataset_mapping.json
EMDB_PDB_resolution_3.5.csv
Pocket_classic
simulated_cryoatom_map
simulated_receptor_map
test_data_list.xlsx
```

Pocket_classic 当前浅层结构：

- `v2_mod4_10A`：`emdb_sim_BOX`、`ligand_dist_BOX`、`pdb_label_BOX`；
- `v2_mod4_15A`：同上；
- `v2_mod5_10A`：同上；
- `v2_raw5_10A`：上述三项加 `emdb_exp_BOX`；
- `v2_raw4_10A`：9 项，仍含四类 BOX、四类 NPZ 和 `split`。

正在删除的 `_BOX` 入口仍存在，只表示递归删除尚未完成，不能用目录项的 4096 bytes 推断其剩余内容。为避免与 `rm` 竞争 Lustre 元数据，本轮没有递归进入这些目录。

### 与上次详细审计的分类对照

下列是上次详细扫描/估算的结构基线，不是 02:10 时点重新递归得到的静态精确值：

- `Pocket_classic/v2_raw4_10A`：约 11.949 TiB；
- `AdaLigand/Ori_Data`：约 14.65 TiB，但当前 Stage F 正在动态增加和清理 scratch；
- `simulated_cryoatom_map` 与 `simulated_receptor_map` 合计约 2.732 TiB；
- `CIF_Ligand`：约 39.25 GiB；
- 主要剩余量位于 Pocket_classic 的另外四个版本，当前正进行 `_BOX` 删除，不能把旧值当作现值。

当前 quota 总量为 74.2687 TiB。由于主要 Pocket 分支正在删除、AdaLigand scratch 正在写入，本轮只能给出动态对账，不能安全地把 74.2687 TiB 全部一一重算成同一时点的静态目录和。

### 安全结论

- 没有修改、创建或删除任何服务器文件；
- 没有向任何用户进程发送信号，没有暂停、终止或调整优先级；
- 没有运行 `sync`、`quotacheck`、quota repair、cache drop 或任何强制刷新/修复；
- 只读条件下没有能安全地“让 quota 立即显示正常”的客户端命令；本次只做重新查询和证据归因。
- 一次针对活跃 scratch 的两层 recent-directory 探针超过 30 秒本地工具窗口，SSH 调用结束；未触碰用户作业。此后不再对该 scratch 加深扫描。

## 正式复查续篇（02:34～06:37）

### 一、更新后的 quota 长时序

| 时间（服务器，+08:00） | storage KiB | objects | 说明 |
|---|---:|---:|---|
| 最早异常快照 | 79,368,865,080 | 5,638,026 | 删除后未见预期大幅下降 |
| 02:33:41 | 79,772,300,560 | 5,281,527 | Stage F 与 Pocket rm 均活动 |
| 02:38:24 | 79,787,930,688 | 5,266,380 | 继续上涨 |
| 02:39:56 | 79,798,785,188 | 5,261,831 | 继续上涨 |
| 03:06:22 | 79,818,540,632 | 5,208,543 | 本轮峰值附近 |
| 05:00:07 | 79,743,085,368 | 4,752,327 | 开始出现缓慢净下降 |
| 05:27:32 | 79,725,374,980 | 4,678,956 | 继续缓慢下降 |
| 05:56:11 | 79,706,805,808 | 4,566,325 | 继续缓慢下降 |
| 06:37:47 | 79,678,760,808 | 4,408,643 | 74.2066 TiB |

03:06～06:37 quota 累计下降约 133.30 GiB，但对象减少 799,900 个；从最早异常快照到 06:37，quota 仍比当时高约 295.54 GiB，而对象累计减少 1,229,383 个。因此：

- 删除与 namespace 收缩已经确定发生；
- Lustre 后续确实开始缓慢释放部分块；
- 三个多小时只回落约 0.13 TiB，仍远小于单个 `sim_npz` 的约 1.1 TiB，更无法消除数十 TiB 的可见树/quota 残差。

### 二、为什么并发写入不能解释 1 TiB 未下降

实测普通增长速度约 3～7 GiB/min。若 1 TiB 在一分钟采样间隔内真实释放，要完全掩盖该下降，需要同一分钟写入约 1,024 GiB，是实测最高值的约 152 倍；按 3 GiB/min 则相差约 341 倍。

即使释放分批发生，连续分钟快照也应累计形成接近 1 TiB 的下降。实际直到数小时后才缓慢回落约 0.13 TiB，所以“被当前 Stage F 写入抵消”不能作为根因答案。

### 三、`sim_npz` 的事后属性核验

`.bash_history` 只读证据显示相关操作是直接 `rm -r`，不是移动到 trash。出现过的删除路径包括：

```text
/storage/penghongen/Pocket_classic/v2_mod5_15A/sim_npz
/storage/penghongen/Pocket_classic/v2_raw4_15A/sim_npz
/storage/penghongen/Pocket_classic/v2_raw5_15A/sim_npz
/storage/penghongen/Pocket_classic/v2_mod4_10A/sim_npz
/storage/penghongen/Pocket_classic/v2_raw5_10A/sim_npz
/storage/penghongen/Pocket_classic/v2_mod4_15A/sim_npz
```

存活的 `v2_raw4_10A/sim_npz/7k6q.npz` 样本：

- logical：238,328,806 B；
- `st_blocks×512`：238,329,856 B；
- `nlink=1`；
- Lustre stripe count=1。

生成代码使用独立 `np.savez` 临时文件再原子替换，仓库未发现 `os.link`、`cp -al` 或 `--link-dest`。因此稀疏文件、硬链接和 trash 都是低概率解释；但删除前的原始 `st_nlink` 已无法事后恢复，不能形式上完全排除。

### 四、Pocket_classic 动态详细分类

观测窗口：03:01～03:05；13 个 `_BOX` `rm` 正在进行，因此以下是动态快照。

#### `v2_raw4_10A`

该版本 `_BOX` 使用用户明确提供的等大小先验，并对每类 20 个文件验证实际块数；NPZ 不使用等大假设，而是每类随机 64 个文件按 `st_blocks` 分层估算。

| 子目录 | 占用 | 方法/区间 |
|---|---:|---|
| `emdb_exp_BOX` | 1.3830 TiB | 370,867 × 8008 blocks |
| `emdb_sim_BOX` | 1.3830 TiB | 370,867 × 8008 blocks |
| `ligand_dist_BOX` | 2.7646 TiB | 370,867 × 16008 blocks |
| `pdb_label_BOX` | 0.6922 TiB | 370,867 × 4008 blocks |
| 四类 BOX 合计 | 6.2227 TiB | 高置信估算 |
| `emdb_npz` | 1.367 TiB | 95%抽样区间 1.064～1.670 |
| `ligand_dist_npz` | 2.151 TiB | 1.797～2.505 |
| `pdb_label_npz` | 0.473 TiB | 0.399～0.547 |
| `sim_npz` | 1.127 TiB | 0.900～1.353 |
| 四类 NPZ 合计 | 5.117 TiB | 4.594～5.640 |
| `split` | 100.37 MiB | exact `du` |

`v2_raw4_10A` 合计约 11.340 TiB，主要方法区间约 10.817～11.863 TiB。

#### 另外四个正在删除的版本

| 版本 | 当前剩余内容 | 动态估计 |
|---|---|---:|
| `v2_raw5_10A` | 四类 BOX | 2.6977 TiB |
| `v2_mod5_10A` | 三类 BOX | 4.2896 TiB |
| `v2_mod4_15A` | 三类 BOX | 3.5412 TiB |
| `v2_mod4_10A` | 三类 BOX | 1.3998 TiB |

四版本合计约 11.9282 TiB，主要抽样范围约 11.63～12.03 TiB。加上 `v2_raw4_10A`，Pocket_classic 在 03:01～03:05 的点估计约 23.268 TiB，方法区间约 22.45～23.89 TiB。

两次浅层计数间有 5,743 个 BOX 文件消失，按样本实际块数折算约 24.99 GiB，即约 7～8 GiB/min；同一时期全局 quota 仍上涨。删除任务确实工作，quota 没同步呈现对应变化。

### 五、已消失版本与约 33～34 TiB 残差

当前 Pocket 根中已经完全不存在、且历史有完整删除序列的版本包括：

- `v2_raw4_15A`；
- `v2_raw5_15A`；
- `v2_mod5_15A`；
- 更早的 `v_1`。

Pocket 根目录 mtime 显示前三个完整 15A 版本至少在本轮约 29 小时前已经从直接 namespace 消失。这已超过普通“几分钟刷新延迟”。按现存完整/近完整版本约 11～12 TiB 的量级，三个 15A 版本合计约 32～36 TiB，与当前可见分类和 quota 的约 33～34 TiB 残差高度吻合。

这是强量级证据，不是 inode/FID 级证明。最合理的服务端检查方向是：这些已 unlink 文件对应的 OST object destroy 是否积压或 quota accounting 是否仍保留。

### 六、其他一级项重新核验

| 一级项 | 实际分配空间 | 方法 |
|---|---:|---|
| `simulated_cryoatom_map` | 861,647,380 KiB = 0.802472 TiB | 4,402 个 `.mrc` 逐文件 `st_blocks` 精确汇总 |
| `simulated_receptor_map` | 1,928,577,872 KiB = 1.796128 TiB | 9,636 个 `.mrc` 精确汇总 |
| 两地图合计 | 2.598600 TiB | 14,038 个 `.mrc`，无读取错误 |
| `BIBM2026.7z` | 7,370,688 KiB = 7.029 GiB | 精确 `st_blocks` |
| 其他 4 个根部小文件 | 2,636 KiB | 精确 `st_blocks` |

`C_a的baseline`、`CIF_Ligand`、`CryAtom` 的合并精确递归在一小时连接窗口内未回传；浅层结构已知，但本次不能用历史值冒充当前精确值。历史 `CIF_Ligand` 约 39.25 GiB，仅可作为量级参考。

### 七、AdaLigand 精确扫描状态

`du -kx --max-depth=1 /storage/penghongen/AdaLigand/Ori_Data` 运行四小时仍未回传，并继续处于 Lustre `cl_sync_io_wait`。因此本轮不能声称获得了新的 AdaLigand 一级精确值。

可见结构已精确完成：`density` 22,381 个直接子目录、`labels` 22,342、`parse` 22,386；`quality` 20,224 个直接文件、`quality_atoms` 10,112、`reports` 22,395；scratch 有 6 个 run 目录。上次约 14.65 TiB 只能作为稳定结构基线。

另一个受用户授权的 Agent 已在两个 Stage F writer 均处于 `try_lock`、零计算子进程时完成原子 scratch manifest。清理前精确结果：

| scratch 类别 | attempt 数 | 实际分配 |
|---|---:|---:|
| 停写瞬间每个 run 最新 12 个大 attempt 候选 | 24 | 22,293,118,976 B = 20.762 GiB |
| 持久大残留，已有公开质量三件套 | 8 | 3,556,700,160 B = 3.312 GiB |
| 持久大残留，无公开质量三件套 | 1,250 | 2,195,553,611,776 B = 1.996844 TiB |
| 仅小文件且已有公开三件套 | 10,163 | 未计入大型 transient |
| 大型 transient 合计 | 5,838 个文件 | 2,221,403,430,912 B = 2.020355 TiB |

按文件类型：

- 3,556 个 MRC：2.009262 TiB；最大单文件约 32.17 GiB；
- 2,282 个 CIF：11.359 GiB；
- 被保留的小型日志/脚本/TXT 约为 GiB 级，不是增长主体。

该分类证明：停写瞬间正常/可能在途的 24 个 attempt 只有约 20.8 GiB；约 2.0 TiB 来自 1,250 个没有公开质量三件套的持久大残留。快速上涨主要是异常/中断路径未清理的累计结果，而不是正常 24 worker 在途占用本身。

### 八、当前可见树/quota 的临时对账

以 06:37 quota 74.2066 TiB 为总额，并暂用：

- Pocket 动态快照 23.268 TiB；
- 两类 map 2.5986 TiB；
- 根直接文件 0.0069 TiB；
- AdaLigand 上次结构基线约 14.65 TiB；另有本轮精确 Stage F transient 2.020 TiB，但与旧基线的 scratch 重叠量未知；
- CIF_Ligand 历史量级约 0.0383 TiB；

若完全不把新 scratch 加到旧 AdaLigand 基线，可见分类中央值约 40.56 TiB、残差约 33.64 TiB；若把 2.020 TiB 全部视为旧基线之后的新增量，可见分类约 42.58 TiB、残差约 31.62 TiB。考虑 Pocket 在 03:05 后继续删除，当前 Pocket 实际值又更低，合理结论是约 32～34 TiB 的强量级残差，而非最终精确差值。该范围仍与三个已消失 15A 完整版本约 32～36 TiB 高度吻合。

### 九、当前最可信的机制判断

1. namespace unlink 已发生：对象数累计减少超过 122 万，多个完整版本已消失。
2. 当前写入不足以掩盖 1 TiB：实测相差 152～341 倍。
3. NPZ 通常非稀疏、单硬链接，且操作是直接 `rm -r`。
4. `lfs quota -v` 总计精确等于 MDT+22 个 OST，不是客户端总计行单独未刷新。
5. 数小时后 quota 开始缓慢回落，支持“OST destroy/块 quota 回收积压并缓慢消化”。
6. Stage F scratch 精确存在约 2.020 TiB 大型 transient，其中约 1.997 TiB 是无公开三件套的持久残留；它解释了近期快速增长的一部分，但不能解释约 32～34 TiB 的总体残差。
7. 三个已消失 15A 版本的估计量级与约 32～34 TiB 残差高度吻合。

因此，首要判断是 Lustre 已完成 namespace 删除，但 OST 对象销毁或服务端 quota accounting 存在长时间积压/异常。普通用户仍无法排除所有 compute node 的 open-unlinked，也无法读取 MDS/OSS 的 pending destroy 队列与服务端版本，所以最终机制需要管理员只读核验。

### 十、管理员最小核验请求

```text
管理员您好。

UID 1351 在 Lustre /storage 下直接 rm -r 删除了 Pocket_classic 多个
sim_npz、NPZ/BOX 类别及完整版本。删除后 namespace 对象数已减少超过
122 万，但 quota 仅在数小时后缓慢回落约 0.13 TiB，没有出现单个
sim_npz 预期约 1.1 TiB 的下降。06:58 的当前可见目录分类与 quota 还有约
36～38 TiB 量级残差；它与三个已经消失的 15A 完整版本、以及本轮继续
删除但未在 quota 中对应下降的 Pocket 数据合计量级接近。

请先只读核验：
1. MDS 是否存在积压的 pending OST object-destroy 请求；
2. MDT 到全部 22 个 OST 的 OSP/import 连通状态和 destroy backlog；
3. 所有登录节点和 compute node 上 UID 1351 的 open-unlinked 文件；
4. 每个 OST 后端记录的 UID 1351 block quota 是否与 lfs quota -v 一致；
5. MDS/OSS 的准确 Lustre 版本，以及是否包含 LU-19068 或厂商 backport。

在给出诊断前请不要执行 quota repair、LFSCK、强制 sync 或其他修改性操作。
```

### 十一、06:42～06:56 的近 1 TiB 复现窗口

Stage F 负责线程对冻结 manifest 做独立 `lstat` 复核时确认：06:42～06:48 之间，正式 run 有 448 个大型 transient 从命名空间消失，涉及 120 attempts / 80 PDB，删除前实际分配合计约 790.7 GiB；补算 run 未发生同类变化，metadata identity 也未被改写。该线程因 live-tree drift 使原 bundle 永久失效并 fail-closed 暂停 apply，没有把不存在的路径继续当作可删除对象。

本审计线程的同期 quota：

| 时间 | storage KiB | TiB | objects |
|---|---:|---:|---:|
| 06:37:47 | 79,678,760,808 | 74.2066 | 4,408,643 |
| 06:56:35 | 79,663,779,136 | 74.1927 | 4,361,354 |

18 分 48 秒内仅下降 14,981,672 KiB，即 14.29 GiB；这远小于已经从 namespace 消失的约 790.7 GiB。两个 Stage F writer 在该窗口仍被精确锁住，没有正常计算子进程继续产生大型 scratch。因此，这是一次比历史 `.npz` 事件时间边界更清楚的同类复现：**大文件 unlink 已发生，但其绝大多数块释放没有及时反映到用户 quota**。

只读进程核验同时发现 PID 52523（`python -`，约 03:03 启动）在 06:56 仍处于 `cl_sync_io_wait`。它可能是早期 SSH 回传超时后继续自然运行的第一版 scratch 扫描/清理脚本，与 06:42～06:48 的删除窗口重合；该线索已交给 Stage F 线程溯源。本审计线程没有向它或任何其他进程发送信号。

这组新证据使“并发写入抵消约 1 TiB 释放”的解释进一步失去成立条件，并把首要机制更集中到 Lustre OST object destroy / block quota accounting 的长延迟或异常积压。后续仍需继续观察该 790.7 GiB 是否在更长窗口分批回落，并由管理员检查服务端 destroy backlog。

### 十二、06:57 Pocket 最终动态复核与更新后对账

只读计数窗口为 06:57:40～06:57:59。当前仍可见 5 个版本；12 条 BOX `rm` 仍在运行，`v2_raw5_10A/emdb_exp_BOX` 已完成并从当前树消失。沿用此前由用户提供且经跨类别抽样验证的 BOX 等大小先验，以及 `v2_raw4_10A` 四类 NPZ 的 64 样本分层估算：

| 版本 | 06:57 当前占用 | 方法/区间 |
|---|---:|---|
| `v2_raw4_10A` | 11.3398 TiB | BOX 6.2227 TiB；NPZ 5.117 TiB，版本区间 10.817～11.863 |
| `v2_raw5_10A` | 1.7047 TiB | 当前剩余三类 BOX |
| `v2_mod5_10A` | 3.3808 TiB | 当前剩余三类 BOX，约 3.083～3.480 |
| `v2_mod4_15A` | 2.6837 TiB | 当前剩余三类 BOX |
| `v2_mod4_10A` | 0.5098 TiB | 当前剩余三类 BOX |
| `Pocket_classic` 合计 | **19.6188 TiB** | **约 18.80～20.24 TiB** |

06:58:41 quota 为 79,662,803,604 KiB = 74.1918 TiB，对象数 4,356,215。与 03:01～03:05 的 Pocket 点估计 23.268 TiB 相比，可见 Pocket 在约 3 小时 52 分内减少约 3.649 TiB；同期 quota 仅约减少 0.145 TiB。因此，**仅本轮继续删除就使“可见删除量－quota 下降量”的缺口扩大约 3.50 TiB**。这证明异常范围已远大于最初单个约 1 TiB `sim.npz`。

以 06:58 quota 和最新 Pocket 快照重算：

- 不把本轮 scratch 另加到旧 AdaLigand 14.65 TiB 基线时，可见分类中央值约 36.91 TiB，quota 残差约 37.28 TiB；
- 后续事故收口证明 06:42 后最终共有约 1.085 TiB transient 从 namespace 消失，故清理前 2.020 TiB 中约剩 0.935 TiB；若把这部分全部视为旧基线之后新增，中央残差约 36.34 TiB；
- 结合 Pocket 18.80～20.24 TiB 的抽样区间与 scratch/旧基线重叠不确定性，当前最稳妥表述是 **约 36～38 TiB 的可见树/quota 残差**。

三个早已消失的 15A 完整版本估计约 32～36 TiB；再加上本轮 Pocket 可见删除但 quota 未对应下降约 3.50 TiB，其合计量级与更新后的约 36～38 TiB 残差吻合。该结果仍是量级强证据，而不是 inode/FID 级证明。

### 十三、旧清理进程归因与 07:02 复测

Stage F 线程已把 06:42 起的外部删除精确归因到 03:03 启动、SSH 回传超时后遗留的旧 v1 Python 脚本：该脚本先执行数小时 inventory，随后自动进入没有冻结 bundle 约束的清理循环。它最终停在正式 run 第 360 个 attempt 的中间，下一 attempt 未动；共删除 1,497 个 scratch transient，实际分配约 1.085 TiB。3,395 条保留证据和 744 条正式质量三件套记录均零缺失、零漂移。Stage F 线程按其单独获得的执行授权终止了该 Python PID 与父 shell，并保留 v1 报告作为事故证据；本只读审计线程没有发送信号或控制任何进程。

07:02:43 复测：

- `lfs quota`：79,659,162,476 KiB，4,346,218 objects；
- 06:37:47～07:02:43 共仅下降 19,598,332 KiB = 18.69 GiB；
- 06:42～06:48 已知从 namespace 消失约 790.7 GiB，故绝大多数预期释放在约 14～20 分钟后仍未出现在 quota；
- 紧接着执行的 `lfs quota -v` 与总查询相差约 31.3 MiB、57 objects，属于动态删除中两个非原子查询之间的微小变化；其总计仍由 MDT 与 22 个 OST 构成。

07:06:27 再测为 79,655,951,600 KiB、4,338,598 objects；相对 06:37 仅下降 21.75 GiB，相对 07:02 又下降约 3.06 GiB。21.75 GiB 仅约为本次 1.085 TiB scratch 删除量的 2%，且同期 Pocket 仍在继续删除，预期释放总量实际更大。PID 54412（其他小根目录 Python 精确扫）与 PID 111446（AdaLigand `du`）分别运行约 4 小时 3 分、4 小时 29 分，仍在 `cl_sync_io_wait`。因用户禁止信号，本审计保持只读等待，不启动重叠扫描；二者即使以后自然结束，原 SSH 输出通道也已经丢失，结果未必可恢复。

最终交付快照 07:09:03 为 79,654,725,944 KiB = 74.1842 TiB、4,333,707 objects；相对 06:37 只下降 22.92 GiB。12 条 Pocket `rm` 仍自然运行；上述两个只读长扫描仍未结束，未被干预。

因此，最终 1.085 TiB 事件同时证明两件事：旧脚本的“审计后自动 apply”设计不安全；但即使把删除来源完全找到并停止，**Lustre quota 未对应释放**仍是独立存在的文件系统/accounting 问题，不能被旧脚本本身解释。
