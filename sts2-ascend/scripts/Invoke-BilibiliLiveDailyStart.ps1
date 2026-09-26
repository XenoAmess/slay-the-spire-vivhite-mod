[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2"
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
Import-Module $modulePath -Force

if (Test-IsAdministrator) {
    throw "The Bilibili daily start coordinator must run at limited integrity."
}

$auditDirectory = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) `
    "VivhiteBilibiliLiveBridge"
$auditPath = Join-Path $auditDirectory "daily-start.log"
$successMarkerPath = Join-Path $auditDirectory "daily-start.success"

function Write-DailyStartAudit {
    param([Parameter(Mandatory = $true)][string]$Message)
    try {
        if (-not (Test-Path -LiteralPath $auditDirectory)) {
            New-Item -ItemType Directory -Path $auditDirectory -Force | Out-Null
        }
        if ((Test-Path -LiteralPath $auditPath) -and
            (Get-Item -LiteralPath $auditPath).Length -gt 1048576) {
            Move-Item -LiteralPath $auditPath `
                -Destination (Join-Path $auditDirectory "daily-start.previous.log") -Force
        }
        $timestamp = [DateTimeOffset]::Now.ToString("o")
        Add-Content -LiteralPath $auditPath -Encoding UTF8 -Value "$timestamp $Message"
    }
    catch {
        # Audit I/O must never turn into permission to start a broadcast.
    }
}

$initialWindow = Get-BilibiliDailyStartWindow
if (-not $initialWindow.InWindow) {
    Write-DailyStartAudit "outside_beijing_window; no action"
    return
}
$windowId = $initialWindow.WindowStart.ToUniversalTime().ToString("o")
$alreadyConfirmedThisWindow = $false
try {
    if (Test-Path -LiteralPath $successMarkerPath -PathType Leaf) {
        $alreadyConfirmedThisWindow =
            (Get-Content -LiteralPath $successMarkerPath -Raw -ErrorAction Stop).Trim() -eq $windowId
    }
}
catch {
    Write-DailyStartAudit "slot=$($initialWindow.Slot) success_marker_read_error=$($_.Exception.Message)"
}

$state = "Unknown"
try {
    $state = Get-LivehimeStreamingState
    Write-DailyStartAudit "slot=$($initialWindow.Slot) state=$state check_started"
}
catch {
    Write-DailyStartAudit "slot=$($initialWindow.Slot) state_probe_error=$($_.Exception.Message); no action"
    throw
}

$healthWatchRunning = $false
if ($state -eq "Streaming" -and $alreadyConfirmedThisWindow) {
    try {
        $healthTask = Get-ScheduledTask -TaskPath "\Vivhite\" `
            -TaskName "BilibiliLive-HealthWatch" -ErrorAction Stop
        $healthWatchRunning = [string]$healthTask.State -eq "Running"
    }
    catch {
        Write-DailyStartAudit "slot=$($initialWindow.Slot) health_watch_probe_error=$($_.Exception.Message)"
    }
}
if ($state -eq "Streaming" -and $alreadyConfirmedThisWindow -and $healthWatchRunning) {
    Write-DailyStartAudit "slot=$($initialWindow.Slot) already_confirmed_streaming health_watch=running"
    return
}

if ($state -notin @("Streaming", "Idle", "NotRunning")) {
    Write-DailyStartAudit "slot=$($initialWindow.Slot) unsafe_transitional_state=$state; no action"
    throw "Daily Bilibili start refused while Livehime state is '$state'."
}

$preStartWindow = Get-BilibiliDailyStartWindow
if (-not $preStartWindow.InWindow) {
    Write-DailyStartAudit "deadline_reached_before_unified_start; no action"
    return
}

$startScript = Join-Path $ProjectRoot "scripts\Start-BilibiliLive.ps1"
if (-not (Test-Path -LiteralPath $startScript)) {
    Write-DailyStartAudit "unified_start_missing=$startScript; no action"
    throw "Unified Bilibili start entrypoint was not found: $startScript"
}

try {
    # This is deliberately the public entrypoint: it starts/reuses the complete
    # game + Brain stack and proves real play plus Quipper safety before Livehime.
    & $startScript -GameDir $GameDir
    $finalState = Get-LivehimeStreamingState
    if ($finalState -ne "Streaming") {
        throw "Unified start returned without confirmed Streaming state (state=$finalState)."
    }
    try {
        if (-not (Test-Path -LiteralPath $auditDirectory)) {
            New-Item -ItemType Directory -Path $auditDirectory -Force | Out-Null
        }
        Set-Content -LiteralPath $successMarkerPath -Encoding UTF8 -Value $windowId
    }
    catch {
        Write-DailyStartAudit "slot=$($initialWindow.Slot) success_marker_write_error=$($_.Exception.Message)"
    }
    Write-DailyStartAudit "slot=$($initialWindow.Slot) unified_start=confirmed_streaming"
}
catch {
    Write-DailyStartAudit "slot=$($initialWindow.Slot) unified_start_error=$($_.Exception.Message)"
    throw
}
