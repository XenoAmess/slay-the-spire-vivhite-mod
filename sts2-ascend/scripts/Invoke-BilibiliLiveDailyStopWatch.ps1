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
    throw "The Bilibili daily stop coordinator must run at limited integrity."
}

$auditDirectory = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) `
    "VivhiteBilibiliLiveBridge"
$auditPath = Join-Path $auditDirectory "daily-stop-watch.log"

function Write-DailyStopAudit {
    param([Parameter(Mandatory = $true)][string]$Message)
    try {
        if (-not (Test-Path -LiteralPath $auditDirectory)) {
            New-Item -ItemType Directory -Path $auditDirectory -Force | Out-Null
        }
        if ((Test-Path -LiteralPath $auditPath) -and
            (Get-Item -LiteralPath $auditPath).Length -gt 1048576) {
            Move-Item -LiteralPath $auditPath `
                -Destination (Join-Path $auditDirectory "daily-stop-watch.previous.log") -Force
        }
        Add-Content -LiteralPath $auditPath -Encoding UTF8 -Value `
            "$([DateTimeOffset]::Now.ToString('o')) $Message"
    }
    catch {
        # Audit I/O must never become permission to operate Livehime.
    }
}

$initialWindow = Get-BilibiliDailyStopWindow
if (-not $initialWindow.InWindow) {
    Write-DailyStopAudit "outside_beijing_window; no action"
    return
}

$state = "Unknown"
try {
    $state = Get-LivehimeStreamingState
    Write-DailyStopAudit "slot=$($initialWindow.Slot) state=$state check_started"
}
catch {
    Write-DailyStopAudit "slot=$($initialWindow.Slot) state_probe_error=$($_.Exception.Message); no action"
    throw
}

if ($state -in @("Idle", "NotRunning")) {
    Write-DailyStopAudit "slot=$($initialWindow.Slot) already_stopped"
    return
}
if (-not (Test-BilibiliDailyStopRequired -State $state)) {
    Write-DailyStopAudit "slot=$($initialWindow.Slot) unsafe_transitional_state=$state; no action"
    throw "Daily Bilibili stop refused while Livehime state is '$state'."
}

$preStopWindow = Get-BilibiliDailyStopWindow
if (-not $preStopWindow.InWindow) {
    Write-DailyStopAudit "slot=$($initialWindow.Slot) deadline_reached_before_unified_stop; no action"
    return
}

$stopScript = Join-Path $ProjectRoot "scripts\Stop-BilibiliLive.ps1"
if (-not (Test-Path -LiteralPath $stopScript -PathType Leaf)) {
    Write-DailyStopAudit "slot=$($initialWindow.Slot) unified_stop_missing=$stopScript; no action"
    throw "Unified Bilibili stop entrypoint was not found: $stopScript"
}

try {
    & $stopScript -GameDir $GameDir
    $finalState = Get-LivehimeStreamingState
    if ($finalState -notin @("Idle", "NotRunning")) {
        throw "Unified stop returned without confirmed stopped state (state=$finalState)."
    }
    Write-DailyStopAudit "slot=$($initialWindow.Slot) unified_stop=confirmed_$($finalState.ToLowerInvariant())"
}
catch {
    Write-DailyStopAudit "slot=$($initialWindow.Slot) unified_stop_error=$($_.Exception.Message)"
    throw
}
