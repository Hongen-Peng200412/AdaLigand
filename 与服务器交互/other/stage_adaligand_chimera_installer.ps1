<#
.SYNOPSIS
    在本地校验 Chimera/MapQ 固定包，并无删除地预置到 AdaLigand 服务器用户目录。

.DESCRIPTION
    当服务器到 UCSF 的公网链路过慢时使用。缓存写在 LOCALAPPDATA，不进入项目同步；传输复用
    项目 MSYS2/sshpass/rsync 配置，不使用 clean sync，不删除远端任何文件。
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$ExpectedSize = 149448194L
$ExpectedMd5 = "aace74cbbbb3dfc5acc7d88b2851ae44"
$LicenseEndpoint = "https://www.cgl.ucsf.edu/chimera/cgi-bin/secure/chimera-get.py"
$RemoteFile = "linux_x86_64_osmesa/chimera-1.19-linux_x86_64_osmesa.bin"
$RemoteUser = "penghongen"
$RemoteHost = "10.102.33.220"
$RemotePort = 10022
$RemoteDirectory = "/home/penghongen/.local/opt/downloads"
$FileName = "chimera-1.19-linux_x86_64_osmesa.bin"
$MapQFileName = "mapq_v2.9.7.zip"
$MapQUrl = "https://raw.githubusercontent.com/gregdp/mapq/c3bdf305677f5f9fc4b69aa404b834d9d3a75937/download/mapq_v2.9.7.zip"
$MapQExpectedSize = 537502L
$MapQExpectedSha256 = "ee004e19f0ca2bf1f439365d64b8463d2e8bd18c8827c28e9b2ccfe3a538fe55"
$PasswordFile = Join-Path $env:USERPROFILE ".ssh\pocket_plus_sshpass.txt"
$CacheDirectory = Join-Path $env:LOCALAPPDATA "AdaLigand\tool_cache"
$CachePath = Join-Path $CacheDirectory $FileName
$PartialPath = "$CachePath.partial"
$MapQCachePath = Join-Path $CacheDirectory $MapQFileName
$MapQPartialPath = "$MapQCachePath.partial"

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
            [IO.Path]::Combine($expanded, "usr", "bin")
        }
        $required = @("rsync.exe", "cygpath.exe", "sshpass.exe", "ssh.exe")
        if ([IO.Directory]::Exists($bin) -and -not ($required | Where-Object {
                    -not [IO.File]::Exists([IO.Path]::Combine($bin, $_))
                })) {
            return $bin
        }
    }
    throw "MSYS2 rsync/sshpass toolchain was not found."
}

function Test-Installer([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    if ((Get-Item -LiteralPath $Path).Length -ne $ExpectedSize) {
        return $false
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm MD5).Hash.ToLowerInvariant() -eq $ExpectedMd5
}

function Test-MapQArchive([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $false
    }
    if ((Get-Item -LiteralPath $Path).Length -ne $MapQExpectedSize) {
        return $false
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -eq `
        $MapQExpectedSha256
}

New-Item -ItemType Directory -Force -Path $CacheDirectory | Out-Null
if (-not (Test-Installer $CachePath)) {
    Remove-Item -LiteralPath $PartialPath -Force -ErrorAction SilentlyContinue
    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $notice = Invoke-WebRequest -UseBasicParsing -WebSession $session -Method Post `
        -Uri $LicenseEndpoint `
        -Body @{ file = $RemoteFile; choice = "Accept" } `
        -TimeoutSec 60
    $match = [regex]::Match($notice.Content, 'url=([^"\s]+)')
    if (-not $match.Success) {
        throw "Chimera temporary download URL was not present in the license response."
    }
    $downloadUri = [uri]::new([uri]$notice.BaseResponse.ResponseUri, $match.Groups[1].Value)
    Write-Host "[Download] $downloadUri" -ForegroundColor Yellow
    Invoke-WebRequest -UseBasicParsing -WebSession $session -Uri $downloadUri.AbsoluteUri `
        -OutFile $PartialPath -TimeoutSec 600
    if (-not (Test-Installer $PartialPath)) {
        throw "Downloaded Chimera installer failed official size/MD5 validation."
    }
    Move-Item -LiteralPath $PartialPath -Destination $CachePath -Force
}
Write-Host "[Verified] local installer size=$ExpectedSize md5=$ExpectedMd5" -ForegroundColor Green

if (-not (Test-MapQArchive $MapQCachePath)) {
    Remove-Item -LiteralPath $MapQPartialPath -Force -ErrorAction SilentlyContinue
    Invoke-WebRequest -UseBasicParsing -Uri $MapQUrl -OutFile $MapQPartialPath -TimeoutSec 120
    if (-not (Test-MapQArchive $MapQPartialPath)) {
        throw "Downloaded MapQ archive failed fixed size/SHA-256 validation."
    }
    Move-Item -LiteralPath $MapQPartialPath -Destination $MapQCachePath -Force
}
Write-Host "[Verified] local MapQ size=$MapQExpectedSize sha256=$MapQExpectedSha256" `
    -ForegroundColor Green

$msysBin = Resolve-MsysBin
$cygpath = Join-Path $msysBin "cygpath.exe"
$sshpass = Join-Path $msysBin "sshpass.exe"
$ssh = Join-Path $msysBin "ssh.exe"
$rsync = Join-Path $msysBin "rsync.exe"
if (-not (Test-Path -LiteralPath $PasswordFile -PathType Leaf)) {
    throw "SSH password file not found: $PasswordFile"
}
$cachePathPosix = (& $cygpath -u $CachePath).Trim()
$mapQCachePathPosix = (& $cygpath -u $MapQCachePath).Trim()
$passwordFilePosix = (& $cygpath -u $PasswordFile).Trim()
$sshOptions = @(
    "-p", $RemotePort.ToString(),
    "-o", "StrictHostKeyChecking=accept-new",
    "-o", "WarnWeakCrypto=no",
    "-o", "PreferredAuthentications=password",
    "-o", "PubkeyAuthentication=no",
    "-o", "NumberOfPasswordPrompts=1"
)
$env:Path = "$msysBin;$env:Path"
$env:MSYS2_ARG_CONV_EXCL = "*"

& $sshpass -f $passwordFilePosix $ssh @sshOptions "$RemoteUser@$RemoteHost" `
    "mkdir -p '$RemoteDirectory'"
if ($LASTEXITCODE -ne 0) {
    throw "Unable to create the remote user download directory."
}

$remoteShell = "sshpass -f $passwordFilePosix ssh -p $RemotePort " +
    "-o StrictHostKeyChecking=accept-new -o WarnWeakCrypto=no " +
    "-o PreferredAuthentications=password -o PubkeyAuthentication=no " +
    "-o NumberOfPasswordPrompts=1"
& $rsync -av --partial --append-verify -e $remoteShell `
    $cachePathPosix "${RemoteUser}@${RemoteHost}:${RemoteDirectory}/${FileName}"
if ($LASTEXITCODE -ne 0) {
    throw "Rsync failed while staging the Chimera installer."
}
& $rsync -av --partial --append-verify -e $remoteShell `
    $mapQCachePathPosix "${RemoteUser}@${RemoteHost}:${RemoteDirectory}/${MapQFileName}"
if ($LASTEXITCODE -ne 0) {
    throw "Rsync failed while staging the MapQ archive."
}

$verifyCommand = "test `$(wc -c <'$RemoteDirectory/$FileName') -eq $ExpectedSize " +
    "&& test `$(md5sum '$RemoteDirectory/$FileName' | awk '{print `$1}') = '$ExpectedMd5' " +
    "&& test `$(wc -c <'$RemoteDirectory/$MapQFileName') -eq $MapQExpectedSize " +
    "&& test `$(sha256sum '$RemoteDirectory/$MapQFileName' | awk '{print `$1}') = '$MapQExpectedSha256' " +
    "&& echo ADALIGAND_TOOL_ARCHIVES_REMOTE_VERIFIED"
& $sshpass -f $passwordFilePosix $ssh @sshOptions "$RemoteUser@$RemoteHost" $verifyCommand
if ($LASTEXITCODE -ne 0) {
    throw "Remote Chimera installer failed size/MD5 validation."
}
