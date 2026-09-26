[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Start", "Stop")]
    [string]$Action,
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [string]$ProjectRoot = "G:\workspace\slay-the-spire-vivhite-mod\sts2-ascend"
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
Import-Module $modulePath -Force

if (-not (Test-IsAdministrator)) {
    throw "The protected Bilibili Livehime worker must run at high integrity."
}

$livehimeExe = "C:\Program Files\bililive\livehime\livehime.exe"
$auditDirectory = Join-Path ([Environment]::GetFolderPath("CommonApplicationData")) `
    "VivhiteBilibiliLiveBridge"
$auditPath = Join-Path $auditDirectory "bridge-worker.log"

function Write-BridgeAudit {
    param([Parameter(Mandatory = $true)][string]$Message)
    try {
        if (-not (Test-Path -LiteralPath $auditDirectory)) {
            New-Item -ItemType Directory -Path $auditDirectory -Force | Out-Null
        }
        if ((Test-Path -LiteralPath $auditPath) -and
            (Get-Item -LiteralPath $auditPath).Length -gt 1048576) {
            Move-Item -LiteralPath $auditPath `
                -Destination (Join-Path $auditDirectory "bridge-worker.previous.log") -Force
        }
        $timestamp = [DateTimeOffset]::Now.ToString("o")
        Add-Content -LiteralPath $auditPath -Encoding UTF8 -Value "$timestamp $Message"
    }
    catch {
        # Audit I/O must never change the Livehime control result.
    }
}

Write-BridgeAudit "action=$Action started"
$bridgeMutex = New-Object Threading.Mutex($false, "Global\VivhiteBilibiliLiveBridge")
$bridgeLockAcquired = $false
try {
    try {
        $bridgeLockAcquired = $bridgeMutex.WaitOne([TimeSpan]::FromSeconds(45))
    }
    catch [Threading.AbandonedMutexException] {
        $bridgeLockAcquired = $true
    }
    if (-not $bridgeLockAcquired) {
        throw "Timed out waiting for another protected Livehime action to finish."
    }

    $actionError = $null
    try {
        if ($Action -eq "Start") {
            $initialState = Get-LivehimeStreamingState
            if ($initialState -in @("Idle", "NotRunning")) {
                $recordingResult = Disable-LivehimeSynchronizedRecording
                $lastRenderLag = Get-LivehimeLastRenderLagPercent
                $restartReasons = @()
                if ($recordingResult.Changed) { $restartReasons += "recording_sync_was_enabled" }
                if ($null -ne $lastRenderLag -and $lastRenderLag -ge 10.0) {
                    $restartReasons += ("previous_render_lag={0:N1}%" -f $lastRenderLag)
                }
                if (Test-LivehimeDisplayCaptureStale) {
                    $restartReasons += "display_capture_failures"
                }
                if ($restartReasons.Count -gt 0) {
                    Write-BridgeAudit ("action=Start cold_capture_rebuild=" +
                        ($restartReasons -join ','))
                    [void](Restart-LivehimeIdle -LivehimeExe $livehimeExe -TimeoutSeconds 20 `
                        -DisableSynchronizedRecording -RemoveDuplicateBrowserSource)
                    Write-BridgeAudit "action=Start cold_capture_rebuild=ready"
                }
            }
            $captureCheckpoint = Get-LivehimeLogCheckpoint
            try {
                Invoke-LivehimeStart -LivehimeExe $livehimeExe -TimeoutSeconds 30
            }
            catch {
                $firstStartError = $_
                $stateAfterFailure = Get-LivehimeStreamingState
                $endedDialogRejected = $firstStartError.Exception.Message -match
                    'reopened the ended/violation dialog after Start'
                $startProducedNoTransition = $firstStartError.Exception.Message -match
                    'state did not become \[Streaming\].*current state is Idle'
                if ($stateAfterFailure -ne "Idle" -or
                    (-not $endedDialogRejected -and -not $startProducedNoTransition -and
                     -not (Test-LivehimeDisplayCaptureStale))) {
                    throw $firstStartError
                }
                $restartReason = if ($endedDialogRejected) {
                    "ended_or_violation_dialog_reopened"
                }
                elseif ($startProducedNoTransition) {
                    "start_produced_no_livehime_transition"
                }
                else {
                    "display_capture_stale"
                }
                Write-BridgeAudit "action=Start $restartReason=restarting_livehime_normally"
                [void](Restart-LivehimeIdle -LivehimeExe $livehimeExe -TimeoutSeconds 20 `
                    -DisableSynchronizedRecording -RemoveDuplicateBrowserSource)
                Write-BridgeAudit "action=Start livehime_restart=ready"
                $captureCheckpoint = Get-LivehimeLogCheckpoint
                Invoke-LivehimeStart -LivehimeExe $livehimeExe -TimeoutSeconds 30
            }
            Start-Sleep -Seconds 5
            if (Test-LivehimeDisplayCaptureStale -AfterOffset $captureCheckpoint) {
                try { Invoke-LivehimeStop -LivehimeExe $livehimeExe -TimeoutSeconds 45 }
                catch {
                    throw ("Post-start display capture failed and safety stop also failed: " +
                        $_.Exception.Message)
                }
                throw "Post-start display capture produced a fresh 887A0001 failure burst; stream was stopped."
            }
            $healthTask = Get-ScheduledTask -TaskPath "\Vivhite\" `
                -TaskName "BilibiliLive-HealthWatch" -ErrorAction SilentlyContinue
            if (-not $healthTask) {
                try { Invoke-LivehimeStop -LivehimeExe $livehimeExe -TimeoutSeconds 45 }
                catch {
                    throw ("Protected capture health task is missing and safety stop failed: " +
                        $_.Exception.Message)
                }
                throw "Protected capture health task is missing; stream was stopped."
            }
            Start-ScheduledTask -TaskPath "\Vivhite\" -TaskName "BilibiliLive-HealthWatch"
            Write-BridgeAudit "action=Start capture_health_watch=started"
        }
        else {
            Invoke-LivehimeStop -LivehimeExe $livehimeExe -TimeoutSeconds 30
            $ttsRestore = Restore-AscendIndexTtsAfterBroadcast -ProjectRoot $ProjectRoot
            Write-BridgeAudit ("action=Stop indextts_restore={0} owner_pid={1}" -f
                $ttsRestore.State, $ttsRestore.OwnerPid)
        }
        Write-BridgeAudit "action=$Action livehime_state=$(Get-LivehimeStreamingState)"
    }
    catch {
        $actionError = $_
        Write-BridgeAudit "action=$Action action_error=$($_.Exception.Message)"
    }

    $restoreError = $null
    $gameWindow = $null
    try {
        $gameWindow = Get-SlayTheSpireWindow -GameDir $GameDir
        if ($gameWindow) {
            Set-SlayTheSpireTopMost -GameDir $GameDir -TimeoutSeconds 15
            [void](Set-AscendViewerTopMost -ProjectRoot $ProjectRoot)
            Write-BridgeAudit "action=$Action restoration=confirmed"
        }
        else {
            Write-BridgeAudit "action=$Action restoration=game_window_absent"
        }
    }
    catch {
        $restoreError = $_
        Write-BridgeAudit "action=$Action restoration_error=$($_.Exception.Message)"
    }

    if ($actionError -and $restoreError) {
        throw "Livehime $Action failed: $($actionError.Exception.Message) Game/viewer restoration also failed: $($restoreError.Exception.Message)"
    }
    if ($actionError) { throw $actionError }
    if ($restoreError) { throw $restoreError }
    if ($gameWindow) {
        Write-Host "Protected Livehime worker restored Slay the Spire 2 with ASCEND-VISION above it."
    }
    Write-BridgeAudit "action=$Action completed"
}
finally {
    if ($bridgeLockAcquired) { $bridgeMutex.ReleaseMutex() }
    $bridgeMutex.Dispose()
}
