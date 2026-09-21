<#
.SYNOPSIS
    续传下载 Stage1 七模式 PyMOL 会话，不删除服务器或本地文件。

.DESCRIPTION
    脚本先读取服务器输出目录实际字节数，并要求目标盘剩余空间至少为该大小加 50 GiB；
    随后使用 MSYS2 rsync 的 --partial 与 --append-verify 续传。SSH 密码只从用户私有文件读取。
#>

param(
    [string]$RemotePath = "/storage/penghongen/AdaLigand_stage1_visualization/stage1_7mode_pcv2_test0_probability_mean",
    [string]$LocalPath = "D:\AdaLigand_Stage1_PyMOL\stage1_7mode_pcv2_test0_probability_mean"
)

$ErrorActionPreference = "Stop"
$RemoteUser = "penghongen"
$RemoteHost = "10.102.33.220"
$RemotePort = "10022"
$PasswordFile = Join-Path $env:USERPROFILE ".ssh\pocket_plus_sshpass.txt"

function Resolve-MsysBin {
    $candidates = @(
        $env:PROJECT_MSYS_ROOT,
        $env:MSYS2_ROOT,
        "C:\msys64",
        "D:\msys64"
    ) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    foreach ($root in $candidates) {
        $expanded = [Environment]::ExpandEnvironmentVariables($root.Trim())
        $bin = if ($expanded.EndsWith("\usr\bin", [StringComparison]::OrdinalIgnoreCase)) {
            $expanded
        }
        else {
            Join-Path $expanded "usr\bin"
        }
        $required = @("rsync.exe", "cygpath.exe", "sshpass.exe", "ssh.exe")
        $missing = $required | Where-Object { -not (Test-Path (Join-Path $bin $_)) }
        if (-not $missing) {
            return $bin
        }
    }
    throw "MSYS2 rsync/sshpass toolchain was not found."
}

if (-not (Test-Path $PasswordFile)) {
    throw "SSH password file not found: $PasswordFile"
}
$msysBin = Resolve-MsysBin
$rsync = Join-Path $msysBin "rsync.exe"
$cygpath = Join-Path $msysBin "cygpath.exe"
$sshpass = Join-Path $msysBin "sshpass.exe"
$ssh = Join-Path $msysBin "ssh.exe"
$passwordFilePosix = (& $cygpath -u $PasswordFile).Trim()
$sshOptions = @(
    "-p", $RemotePort,
    "-o", "StrictHostKeyChecking=yes",
    "-o", "WarnWeakCrypto=no",
    "-o", "PreferredAuthentications=password",
    "-o", "PubkeyAuthentication=no",
    "-o", "NumberOfPasswordPrompts=1"
)

$remoteBytesText = & $sshpass -f $passwordFilePosix $ssh @sshOptions "$RemoteUser@$RemoteHost" `
    "du -sb '$RemotePath' | awk '{print `$1}'"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to read remote output size: $RemotePath"
}
$remoteBytes = [int64]$remoteBytesText.Trim()
$targetRoot = [System.IO.Path]::GetPathRoot([System.IO.Path]::GetFullPath($LocalPath))
$freeBytes = (Get-PSDrive -Name $targetRoot.Substring(0, 1)).Free
$requiredBytes = $remoteBytes + 50GB
if ($freeBytes -lt $requiredBytes) {
    throw "Insufficient disk space: free=$freeBytes required=$requiredBytes"
}

New-Item -ItemType Directory -Force -Path $LocalPath | Out-Null
$localPathPosix = (& $cygpath -u ([System.IO.Path]::GetFullPath($LocalPath))).Trim()
$remoteShell = "sshpass -f $passwordFilePosix ssh -p $RemotePort " +
    "-o StrictHostKeyChecking=yes -o WarnWeakCrypto=no " +
    "-o PreferredAuthentications=password -o PubkeyAuthentication=no " +
    "-o NumberOfPasswordPrompts=1"
$env:MSYS2_ARG_CONV_EXCL = "*"
$env:Path = "$msysBin;$env:Path"
& $rsync -av --partial --append-verify -e $remoteShell `
    "${RemoteUser}@${RemoteHost}:${RemotePath}/" "${localPathPosix}/"
if ($LASTEXITCODE -ne 0) {
    throw "rsync download failed with exit code $LASTEXITCODE"
}
