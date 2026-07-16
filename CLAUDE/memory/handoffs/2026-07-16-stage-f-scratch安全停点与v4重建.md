# AdaLigand Stage F scratch 安全停点与 v4 重建交接

Date: 2026-07-16 13:22+08:00
Status: active；A–G 尚未完成，Stage F writer 已安全停止

## 当前结论

正式流程仍处于 Stage F。`316116` 与独立补算 `318350` 都保留原 CPU96 allocation，但已进入 `after+try` 停点；没有 F/Loky/Chimera/MapQ 子进程。`316117` 仍为 `afterok:316116` dependency waiting，只允许未来运行 G analyze。

Stage F 的科学计算契约没有改变。插曲只修复 scratch 生命周期，并在硬中断后按冻结 manifest 回收可重建的 MRC/MAP/CIF；四 CC、MapQ sigma=0.4/np=8、配体 Q、6 Å occurrence 口袋 Q、schema v3 空口袋、质量三件套及 run-only exclusion 均保持不变。

## 冻结身份与停点

- 正式 run/job：`adaligand_ag_20260711T154658` / `316116`，停于 `8821/22386`。
- 补算 run/job：`adaligand_ag_20260711T154658_fsupp96_v1` / `318350`，停于 `2426/2990`。
- 两项锁：各自只有 regular `after_lock + try_lock`；`kill/pre/child_pgid` 均无。
- `316117`：PENDING(Dependency)、UNLIMITED，精确锁均无。
- Stage F exclusions：共享四条加 `6kgx`，SHA-256 `3b10abb5cc69bca0689cb89cdb6e0bde21620504c11479edcbfb51c83ec68ee8`。

## 已完成实现与测试

- `a9d9e30`：`build_quality()` exact-attempt 异常安全清理。
- `39e5185`：bundle-bound audit/apply、逐文件 fsync journal、硬杀续跑。
- `d4849fc`：原子临时文件与 pre-attempt known failure 生命周期回归。
- `d53d190`：master+allocation 的真实 schema v2 进程门；识别裸/`python -`，绑定 argv/stdout/stderr/node/job/time/实现 SHA。
- `ceb7d2e`：README、ExecPlan 与 gotcha 记忆回填。
- Windows：专项 `48 passed, 2 skipped`；全套 `272 passed, 4 skipped`。
- Linux cnode01：专项 `50 passed`；全套 `276 passed`。
- 五个代码/测试文件已精确 rsync，远端 SHA 与本地一致；没有 clean sync。

## 事故边界

旧 v3 inventory 有 141,437 条 raw file、11,445 attempts；零删除 audit 命中 5,838 个 transient、预计分配约 2.22 TB。但 master 上 03:03 起遗留的旧 SSH/stdin v1 `python -` 在 v3 audit 后进入无 journal cleanup，精确删除 1,497 个 transient（570 CIF+927 MRC），冻结清单预计约 1.085 TiB。

受影响 attempt 的小证据与公开质量三件套没有存在性、大小、mtime 或哈希漂移。v1/v3 证据必须保留，但 **v3 bundle 永久无效，绝不能 apply**。旧进程来源由父 bash/stdin/时间线高度支持；由于系统账本权限不足，只能记录为高可信推断。

另有 PID `54412` / PPID `53972` 是不归属本任务的只读容量扫描：从 SSH notty 以 `python3 -` 扫描 `C_a的baseline/CIF_Ligand/CryAtom`，无删除/写入逻辑。它会争用 Lustre metadata，并被新 process gate 保守识别；未经单独授权不得信号。

v4 inventory 已于 10:35:05 闭合：step `316116.43` 为 `COMPLETED 0:0`，`raw_inventory.tsv` 为 139,940 行、`attempts.tsv` 为 11,445 行，SHA-256 分别为 `e5f3075c7162fbe227d03e0de44f98ae6a7f26c085129d3563491e6f9d2c502a` 与 `3f9f20960b883d645aa966f8e4c60981aa98131b778508a16601fbc209a3a863`；`sha256sum -c inventory.sha256` 两项均为 `OK`。PID `54412` 在 13:32 仍存活；用户随后明确决定它不应阻塞本轮。process gate 已升级为 schema v3，只允许 controller 上最多一个 `node+PID+PPID+start_ticks+argv SHA` 完全匹配的一次性例外，保留原始 opaque 行；任何第二进程或身份漂移仍阻断。尚未运行 audit/apply，也未改动任何 try/after lock。

## 唯一允许的继续路径

1. v4 inventory 已闭合；不要启动第二棵全树扫描。有效目录为服务器绝对路径：
   `/storage/penghongen/AdaLigand/Ori_Data/reports/runs/adaligand_ag_20260711T154658/stage_f_scratch_recovery_20260716_v4/`
2. 不等待、也不信号 PID54412。先以其当前 `PID+PPID+start_ticks+argv SHA` 生成一次性 controller 例外，再用 canonical `scripts/stage_f_process_audit.py capture --controller_node master --allow_controller_opaque ...` 生成新的 `process_audit.before_audit.json`；master/cnode04/cnode01 必须 F/recovery/blocking opaque=0、scan_error=0、stderr为空。PID 消失或身份漂移时不得伪造匹配。
3. 用 v4 inventory 运行零删除 audit；独立核验 delete/nontransient/public-trio manifest、summary、bundle SHA。旧 v3 数据不能混入。
4. 记录 apply 前 quota，再生成另一份新鲜 `process_audit.before_apply.json`；按 v4 bundle 逐文件 journal/fsync apply。验收 `failures=0`、postscan transient=0、公开质量三件套逐字节不变；普通 nontransient 证据以路径、类型、大小、mtime 和已有/必要哈希证明实质内容未变，不再为全部超大日志补做全量哈希，并记录 quota 后快照。
5. 先只删除精确 `try_lock_318350`，完成补算与独立审计；再删除 `try_lock_316116`，让正式 F 复用三件套并完成正式 status/release。不得同时盲放。
6. F 全量四终态和质量契约独立审计通过后才接受 `316117`。G 只 analyze，不执行示例阈值、不写或删除 `keep_list`。

## 权威文档

- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
- `Data_Preprocessing/Ori_Data/code/readme.md`
- `CLAUDE/memory/learnings/gotcha-2026-07-16-stage-f-scratch生命周期.md`
- automation `adaligand-a-g` 已更新为本安全停点。
