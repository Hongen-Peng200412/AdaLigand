# SSH 主机密钥轮换必须先固定证据再恢复认证

Type: gotcha
Date: 2026-07-15
Tags: ssh, host-key, server-interaction, security, continuity

## Context

AdaLigand 低噪声监控连接 `penghongen@10.102.33.220:10022` 时，ED25519、ECDSA 和 RSA 主机密钥同时变化。旧 `known_hosts` 中的 ED25519/ECDSA pin 与当前握手不一致；密码仍可用，但密码本身不能证明远端身份。

## Memory

不要用 `StrictHostKeyChecking=no` 或直接删除全部 `known_hosts`。本次恢复顺序是：

1. 冻结旧 `known_hosts` 的 SHA-256 并创建带时间戳备份；只处理精确 endpoint。
2. 用三次独立 `ssh-keyscan` 采样确认当前网络路径下三种公钥稳定一致。
3. 用户确认 endpoint、账号和密码未变，并明确授权恢复；密码不写入仓库或命令输出。
4. 精确替换该 endpoint 的三条 pin；使用严格主机校验登录。
5. 在任何远端写入前，核对 `master` 主机名、账号、AdaLigand 固定目录、正式 run、Slurm Job ID 与历史时间线；全部连续后才恢复只读监控。

2026-07-15 冻结的当前指纹为：

- ED25519：`SHA256:wRrXzA2Yf/RD2+C0KnLOhdpg7pVNPLo9XnCCIlNP8yg`
- ECDSA：`SHA256:/B9db9yFvST5K4l+yW7UznZnghbtt4XGSSuhAD0dXPE`
- RSA：`SHA256:jWyUeF87w5UXCkurG/m1vwjBTjiOS8hQb7GTVFwozJo`

更新后的本机 `known_hosts` SHA-256 为 `bc8a377526f81c42b7c69ab47ff3619c80191890d7fb6bba876054c3bdcbc4c4`。这些值现在是项目内未来核验的 pin；若再次变化，必须重新停机取证与授权，不能把本次授权外推。

## When To Use

任何 AdaLigand/Pocket Plus agent 在 SSH 报 `REMOTE HOST IDENTIFICATION HAS CHANGED`、服务器重装/轮换密钥、或远程 helper 突然拒绝连接时。

## Related Files

- `与服务器交互/other/readme.md`
- `与服务器交互/other/Invoke-PasswordSsh.ps1`
- `文档/exec_plan/A-G数据流水线实现与全量运行.md`
