<#
.SYNOPSIS
    Sync all AdaLigand Stage1 offline W&B runs from the formal run scope.

.DESCRIPTION
    This is a fixed-scope wrapper around sync_wandb_remote.ps1. It scans only
    the formal AdaLigand Stage1 allocation root, selects every offline-run-*
    directory, and preserves each run's original W&B entity and project.

    Remote files are read only. Downloaded snapshots are synced with
    --no-mark-synced by the shared implementation, so neither the remote logs
    nor their sync state are changed.
#>

param(
    [switch]$DryRun,
    [switch]$KeepTemp,
    [string]$WandbExe
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$stage1RemoteRoot = "/home/penghongen/My_Project/tmp/adaligand_stage1_20260721T024000/allocations"
$sharedSyncScript = Join-Path $PSScriptRoot "sync_wandb_remote.ps1"

if (-not (Test-Path -LiteralPath $sharedSyncScript -PathType Leaf)) {
    Write-Host "Error: shared W&B sync script not found: $sharedSyncScript" -ForegroundColor Red
    exit 1
}

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " AdaLigand Stage1 offline W&B one-click sync" -ForegroundColor Cyan
Write-Host " Scope: $stage1RemoteRoot" -ForegroundColor Cyan
Write-Host " Producers: unet_c1, Find_0, Find_1, Find_2" -ForegroundColor Cyan
Write-Host " Runs: all offline-run-* under the fixed Stage1 scope" -ForegroundColor Cyan
Write-Host " Safety: remote read-only; W&B --no-mark-synced" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$syncArguments = @{
    RemoteRoot = $stage1RemoteRoot
    AllRuns    = $true
    DryRun     = $DryRun.IsPresent
    KeepTemp   = $KeepTemp.IsPresent
}
if (-not [string]::IsNullOrWhiteSpace($WandbExe)) {
    $syncArguments.WandbExe = $WandbExe
}

& $sharedSyncScript @syncArguments

