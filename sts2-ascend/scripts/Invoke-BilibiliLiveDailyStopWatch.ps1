[CmdletBinding()]
param(
    [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2"
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
Import-Module $modulePath -Force

if (-not (Test-IsAdministrator)) {
    throw "The protected Bilibili daily stop watch must run at high integrity."
}

$livehimeExe = "C:\Program Files\bililive\livehime\livehime.exe"
$auditDirectory = Join-Path ([Environment]::GetFolderPath("CommonApplicationData")) `
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
        $timestamp = [DateTimeOffset]::Now.ToString("o")
        Add-Content -LiteralPath $auditPath -Encoding UTF8 -Value "$timestamp $Message"
    }
    catch {
        # Audit I/O must never prevent a required Livehime state check.
    }
}

$initialWindow = Get-BilibiliDailyStopWindow
if (-not $initialWindow.InWindow) {
    Write-DailyStopAudit "outside_beijing_window; no action"
    return
}

Write-DailyStopAudit "slot=$($initialWindow.Slot) check_started"
$state = "Unknown"
try {
    $state = Get-LivehimeStreamingState
    Write-DailyStopAudit "slot=$($initialWindow.Slot) state=$state"
}
catch {
    Write-DailyStopAudit "slot=$($initialWindow.Slot) state_probe_error=$($_.Exception.Message)"
}

if (-not (Test-BilibiliDailyStopRequired -State $state)) { return }

$bridgeMutex = New-Object Threading.Mutex($false, "Global\VivhiteBilibiliLiveBridge")
$bridgeLockAcquired = $false
$stopAttempted = $false
try {
    try {
        $bridgeLockAcquired = $bridgeMutex.WaitOne(0)
    }
    catch [Threading.AbandonedMutexException] {
        $bridgeLockAcquired = $true
    }
    if (-not $bridgeLockAcquired) {
        Write-DailyStopAudit "slot=$($initialWindow.Slot) bridge_busy; next minute will retry"
        return
    }

    $lockedWindow = Get-BilibiliDailyStopWindow
    if (-not $lockedWindow.InWindow) {
        Write-DailyStopAudit "slot=$($initialWindow.Slot) deadline_reached_under_lock; no action"
        return
    }

    # Recheck under the shared GUI lock so a concurrent manual Start/Stop cannot race the click.
    $lockedState = "Unknown"
    try {
        $lockedState = Get-LivehimeStreamingState
    }
    catch {
        Write-DailyStopAudit "slot=$($initialWindow.Slot) locked_state_probe_error=$($_.Exception.Message)"
        return
    }
    if (-not (Test-BilibiliDailyStopRequired -State $lockedState)) {
        Write-DailyStopAudit "slot=$($initialWindow.Slot) locked_state=$lockedState; no action"
        return
    }

    $preStopWindow = Get-BilibiliDailyStopWindow
    if (-not $preStopWindow.InWindow) {
        Write-DailyStopAudit "slot=$($initialWindow.Slot) deadline_reached_before_stop; no action"
        return
    }

    $stopAttempted = $true
    try {
        Invoke-LivehimeStop -LivehimeExe $livehimeExe -TimeoutSeconds 30 `
            -StopBeforeUtc $preStopWindow.WindowEnd
        Write-DailyStopAudit "slot=$($initialWindow.Slot) stop=confirmed_idle"
    }
    catch {
        Write-DailyStopAudit "slot=$($initialWindow.Slot) stop_error=$($_.Exception.Message)"
        Write-Warning "Daily Bilibili stop attempt failed; the next minute will retry: $($_.Exception.Message)"
    }

    if ($stopAttempted) {
        try {
            $gameWindow = Get-SlayTheSpireWindow -GameDir $GameDir
            if ($gameWindow) {
                Set-SlayTheSpireTopMost -GameDir $GameDir -TimeoutSeconds 10
            }
        }
        catch {
            Write-DailyStopAudit "slot=$($initialWindow.Slot) game_window_restore_error=$($_.Exception.Message)"
        }

        try {
            [void](Set-AscendViewerTopMost -ProjectRoot $ProjectRoot)
        }
        catch {
            Write-DailyStopAudit "slot=$($initialWindow.Slot) viewer_restore_error=$($_.Exception.Message)"
        }
    }
}
finally {
    if ($bridgeLockAcquired) { $bridgeMutex.ReleaseMutex() }
    $bridgeMutex.Dispose()
}
