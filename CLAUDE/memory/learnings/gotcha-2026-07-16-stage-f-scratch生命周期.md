# Stage F scratch 必须由 attempt 生命周期显式拥有

Type: gotcha
Date: 2026-07-16
Tags: AdaLigand, Stage F, scratch, MRC, MapQ, Chimera, cleanup, Lustre

## When To Use

在 Stage F 新增或改名大型临时文件、调整 `build_quality()` 的异常点、修改 Chimera/MapQ runner 调用方式、改变正式 writer/skip 路径，或处理 `SIGKILL`、节点掉电、超时截断后的 stale scratch 时，必须应用本规则。日常 heartbeat 只做浅层增量监控；没有精确停写证据时不得把本规则误用成在线清理器。

## Problem

`build_quality()` 会在 `scratch/{run_id}/stage_f/{pdb_id}/{attempt_id}/` 生成规范化 CIF、canonical/native/simulated MRC 和 MapQ 输出 CIF。旧实现只在成功末尾 unlink 五个最终路径，任何 canonical、molmap、correlation、native 解压、MapQ、QC、provenance 或正式 writer 异常都会绕过清理；原子写临时文件也不在旧清单内。

真实全量运行已证明这不是理论风险：早已完成的 attempt 仍可保留实际分配数百 MiB，在途单样本可占数 GiB；账号分配块曾以约 3.47 GiB/min 净增长。Lustre 上必须使用 `st_blocks×512` 或 `du` 看实际分配，不能只看逻辑大小。

## Durable Rule

- 生命周期所有者是 `quality.py::build_quality()`，不是通用 `ChimeraRunner`/`MapQRunner`；后两者还服务其他 stage，不能擅自删除调用方文件。
- attempt 创建后、第一次大型写入前就进入异常安全边界。成功和可捕获异常都只在当前 UUID attempt 内递归删除 MRC/MAP/CIF及原子临时文件。
- 保留 stdout/stderr、生成脚本、MapQ 兼容脚本和 run-scoped 结构化失败；默认不保留大型 debug 文件。未来若需要 debug retention，必须显式 opt-in，并同时具备 run 级硬空间上限和并发互斥。
- 禁止 `rmtree` attempt，禁止扫描或清理兄弟 PDB、attempt、run。越界 symlink 或 unlink 失败必须 fail-closed，并写小型 `cleanup_errors.json`。
- 已有合法质量三件套的 skip 在 scratch 创建之前返回，不得回扫历史 attempt。
- `SIGKILL`、节点掉电不会执行 Python `finally`。使用 kill-lock 后，必须先确认精确 job 进入 try-lock、子进程组消失，再冻结 run-scoped before manifest，回收 stale 大文件并验证小日志不变；不能把硬杀恢复责任假设成 finally 能解决。
- routine heartbeat 不做全树 scratch 扫描。全树 Lustre metadata inventory 可能超过 30 分钟；常规监控采用浅层增量，只有停写恢复时才做一次受检 inventory。
- 硬中断回收必须分成 `audit` 与 `apply` 两步：前者零删除并冻结 delete/nontransient/public-trio manifest，后者显式绑定完整 audit bundle SHA。不能把 raw inventory 直接喂给 `find -delete`，也不能预检后再调用会扩大集合的 live-tree cleanup。
- `apply` 逐文件先 fsync `intent`，再即时复核精确锁和 lstat 身份，只 unlink manifest 路径，最后 fsync `deleted`。最后一条无换行 journal 尾部必须先固化原始 bytes/hash 后才可受检截断；中间坏行一律阻断。这样硬杀后才能区分“尚未授权删除”“已授权但结果未记完”和“已完成”。
- 零进程证据不能只存一个看起来像 SHA 的字符串，也不能只探测 allocation。必须由登录节点上的正式脚本生成 schema v2 证据：逐 allocation probe、scheduler/四锁快照、最后一次 master probe；保存 argv、stdout/stderr、逐 job/node exit code、三类 active count/list、scan errors、最早开始时间和 canonical 脚本/模块 SHA，并由消费者逐字段重算与闭合。
- 同 UID 的裸 `python`、`python -u -`、`python -` 一律视为不透明 stdin Python 并阻断回收；`python -c`、`python -m` 和 `python script.py -` 不按该规则误报。禁止用 SSH stdin 脚本执行长 inventory/cleanup。controller 必须显式为 `master` 且不能与 allocation node 重合。
- audit 前和 apply 前各生成一次新的 process-audit；旧 schema、复用超过步骤边界的 zero 文件或只含手填文本 marker 的证据均无效。

## Validation Baseline

- 实现提交：`a9d9e30`
- 专项测试：16 项，覆盖成功、各阶段异常、三种正式 writer、skip、跨 run/PDB/attempt 和并发隔离，以及清理自身失败。
- Windows 全套：240 passed、2 个 POSIX-only skipped。
- Linux 全套：242 passed。
- 科学计算主体经 whitespace-insensitive diff 独立审查为零变化；四 CC、MapQ、配体/6 Å 口袋 Q、schema v3 与正式三件套契约不变。
- 硬中断回收提交：`39e5185`；跨节点真实进程守卫提交：`d53d190`。当前 Windows 进程/回收/生命周期专项 48 passed、2 skipped，全套 272 passed、4 skipped；Linux 专项 50 passed，全套 276 passed。
- 2026-07-16 事故证据：旧 SSH/stdin v1 进程在无 journal 的情况下删除了精确 transient matcher 命中的 1,497 个 MRC/CIF，按冻结 manifest 预计回收约 1.085 TiB；受影响 attempt 的小证据与公开质量三件套未漂移。旧 v3 bundle 因 live-tree 漂移永久作废，必须重建 v4 inventory/audit。该时间线高度支持旧内联脚本来源，但系统账本权限不足，来源只能写为高可信推断而非绝对归因。

## Related Files

- `Data_Preprocessing/Ori_Data/code/quality.py`
- `Data_Preprocessing/Ori_Data/tests/test_quality_scratch_lifecycle.py`
- `Data_Preprocessing/Ori_Data/code/stage_f_scratch_recovery.py`
- `Data_Preprocessing/Ori_Data/code/stage_f_process_audit.py`
- `Data_Preprocessing/Ori_Data/scripts/stage_f_scratch_recovery.py`
- `Data_Preprocessing/Ori_Data/scripts/stage_f_process_audit.py`
- `Data_Preprocessing/Ori_Data/tests/test_stage_f_scratch_recovery.py`
- `Data_Preprocessing/Ori_Data/tests/test_stage_f_process_audit.py`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
