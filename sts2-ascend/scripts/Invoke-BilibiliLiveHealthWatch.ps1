[CmdletBinding()]
param(
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [string]$ProjectRoot = "G:\workspace\slay-the-spire-vivhite-mod\sts2-ascend",
    [ValidateRange(3, 30)][int]$PollSeconds = 5,
    [ValidateRange(2, 6)][int]$ConsecutiveFailures = 3,
    [ValidateRange(12, 360)][int]$LowMotionOnlyLimit = 46,
    [ValidateRange(30, 600)][int]$GameplayStallSeconds = 90,
    [ValidateRange(60, 600)][int]$CrossRunTimeoutSeconds = 120,
    [ValidateRange(10, 120)][int]$CrossRunProofTimeoutSeconds = 30,
    [ValidateRange(5, 300)][int]$GameplayEvidenceMaxAgeSeconds = 15
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
Import-Module $modulePath -Force

if (-not (Test-IsAdministrator)) {
    throw "The protected Bilibili capture health watch must run at high integrity."
}

$livehimeExe = "C:\Program Files\bililive\livehime\livehime.exe"
$auditDirectory = Join-Path ([Environment]::GetFolderPath("CommonApplicationData")) `
    "VivhiteBilibiliLiveBridge"
$auditPath = Join-Path $auditDirectory "capture-health-watch.log"

function Write-CaptureHealthAudit {
    param([Parameter(Mandatory = $true)][string]$Message)
    try {
        if (-not (Test-Path -LiteralPath $auditDirectory)) {
            New-Item -ItemType Directory -Path $auditDirectory -Force | Out-Null
        }
        if ((Test-Path -LiteralPath $auditPath) -and
            (Get-Item -LiteralPath $auditPath).Length -gt 1048576) {
            Move-Item -LiteralPath $auditPath `
                -Destination (Join-Path $auditDirectory "capture-health-watch.previous.log") -Force
        }
        Add-Content -LiteralPath $auditPath -Encoding UTF8 -Value `
            "$([DateTimeOffset]::Now.ToString('o')) $Message"
    }
    catch { }
}

$corroboratedFailureCount = 0
$lowMotionOnlyCount = 0
$gameplayRunId = ""
$gameplayDecisionId = ""
$gameplayOutcomeAt = ""
$gameplayTransitionStartedAt = ""
$gameplayTransitionProofStartedAt = ""
$lastGameplayProgressAt = [DateTimeOffset]::UtcNow
$logOffset = Get-LivehimeLogCheckpoint
Write-CaptureHealthAudit (("watch=started gameplay_stall_seconds={0} " -f $GameplayStallSeconds) +
    "cross_run_timeout_seconds=$CrossRunTimeoutSeconds " +
    "cross_run_proof_timeout_seconds=$CrossRunProofTimeoutSeconds " +
    "gameplay_evidence_max_age_seconds=$GameplayEvidenceMaxAgeSeconds runtime_limit=none")
while ($true) {
    $state = Get-LivehimeStreamingState
    if ($state -ne "Streaming") {
        if ($state -in @("Idle", "NotRunning")) {
            try {
                $ttsRestore = Restore-AscendIndexTtsAfterBroadcast -ProjectRoot $ProjectRoot
                Write-CaptureHealthAudit ("watch=indextts_restore state={0} owner_pid={1}" -f
                    $ttsRestore.State, $ttsRestore.OwnerPid)
            }
            catch {
                Write-CaptureHealthAudit "watch=indextts_restore error=$($_.Exception.Message)"
            }
        }
        Write-CaptureHealthAudit "watch=exit state=$state"
        return
    }

    $captureBurst = Test-LivehimeDisplayCaptureStale -AfterOffset $logOffset
    $logOffset = Get-LivehimeLogCheckpoint
    $preview = Test-LivehimePreviewFreshness -SampleDelayMilliseconds 1500
    $healthDecision = Get-BilibiliCaptureHealthDecision `
        -CaptureBurst $captureBurst `
        -PreviewAvailable ([bool]$preview.Available) `
        -PreviewFresh ([bool]$preview.Fresh) `
        -CorroboratedFailureCount $corroboratedFailureCount `
        -LowMotionOnlyCount $lowMotionOnlyCount `
        -CorroboratedFailureLimit $ConsecutiveFailures `
        -LowMotionOnlyLimit $LowMotionOnlyLimit
    $corroboratedFailureCount = [int]$healthDecision.CorroboratedFailureCount
    $lowMotionOnlyCount = [int]$healthDecision.LowMotionOnlyCount

    # This semantic clock is deliberately independent of preview motion.  A
    # moving Livehime overlay or animated cursor cannot reset a stalled game;
    # only a distinct, later applied Brain receipt in the same run can do so.
    $gameplayEvidence = Get-BilibiliGameplayProgressSnapshot -ProjectRoot $ProjectRoot `
        -MaxAgeSeconds $GameplayEvidenceMaxAgeSeconds
    $gameplayDecision = Get-BilibiliGameplayHealthDecision -Evidence $gameplayEvidence `
        -PreviousRunId $gameplayRunId -PreviousDecisionId $gameplayDecisionId `
        -PreviousOutcomeAt $gameplayOutcomeAt -LastProgressAtUtc $lastGameplayProgressAt `
        -PreviousTransitionStartedAt $gameplayTransitionStartedAt `
        -PreviousTransitionProofStartedAt $gameplayTransitionProofStartedAt `
        -NowUtc ([DateTimeOffset]::UtcNow) -StallTimeoutSeconds $GameplayStallSeconds `
        -CrossRunTimeoutSeconds $CrossRunTimeoutSeconds `
        -CrossRunProofTimeoutSeconds $CrossRunProofTimeoutSeconds
    $gameplayRunId = [string]$gameplayDecision.PreviousRunId
    $gameplayDecisionId = [string]$gameplayDecision.PreviousDecisionId
    $gameplayOutcomeAt = [string]$gameplayDecision.PreviousOutcomeAt
    $gameplayTransitionStartedAt = [string]$gameplayDecision.TransitionStartedAt
    $gameplayTransitionProofStartedAt = [string]$gameplayDecision.TransitionProofStartedAt
    $lastGameplayProgressAt = [DateTimeOffset]$gameplayDecision.LastProgressAtUtc
    if ($gameplayDecision.State -in @("Baseline", "Progressed")) {
        Write-CaptureHealthAudit (("watch=gameplay_healthy state={0} run_id={1} decision_id={2} " -f
            $gameplayDecision.State, $gameplayRunId, $gameplayDecisionId) +
            "outcome_at=$gameplayOutcomeAt source=$($gameplayEvidence.ReceiptSource)")
    }
    elseif ($gameplayDecision.State -eq "HardFailure") {
        Write-CaptureHealthAudit ("watch=gameplay_hard_failure reason=$($gameplayDecision.Reason) " +
            "screen=$($gameplayEvidence.Screen) run_id=$($gameplayEvidence.RunId)")
    }
    elseif ($gameplayDecision.State -eq "Transition") {
        Write-CaptureHealthAudit (("watch=gameplay_transition reason={0} elapsed_seconds={1:N1} " -f
            $gameplayDecision.Reason, [double]$gameplayDecision.ElapsedSeconds) +
            "limit_seconds=$($gameplayDecision.TimeoutSeconds) screen=$($gameplayEvidence.Screen) " +
            "run_id=$($gameplayEvidence.RunId) baseline_run_id=$gameplayRunId " +
            "baseline_decision_id=$gameplayDecisionId")
    }
    elseif ($gameplayDecision.State -eq "Unverifiable") {
        Write-CaptureHealthAudit (("watch=gameplay_unverifiable reason={0} elapsed_seconds={1:N1} " -f
            $gameplayDecision.Reason, [double]$gameplayDecision.ElapsedSeconds) +
            "limit_seconds=$($gameplayDecision.TimeoutSeconds) screen=$($gameplayEvidence.Screen) run_id=$($gameplayEvidence.RunId)")
    }
    else {
        Write-CaptureHealthAudit (("watch=gameplay_waiting reason={0} elapsed_seconds={1:N1} " -f
            $gameplayDecision.Reason, [double]$gameplayDecision.ElapsedSeconds) +
            "limit_seconds=$($gameplayDecision.TimeoutSeconds) run_id=$gameplayRunId decision_id=$gameplayDecisionId")
    }
    if ($healthDecision.Signal -eq "CorroboratedFailure") {
        Write-CaptureHealthAudit ("watch=unhealthy corroborated_consecutive=$corroboratedFailureCount " +
            "reason=$($healthDecision.Reason) capture_burst=$captureBurst " +
            "preview=$($preview.Reason) " +
            ("changed_ratio={0:N6}" -f [double]$preview.ChangedRatio))
    }
    elseif ($healthDecision.Signal -eq "LowMotionOnly") {
        Write-CaptureHealthAudit ("watch=degraded low_motion_consecutive=$lowMotionOnlyCount " +
            "low_motion_limit=$LowMotionOnlyLimit reason=$($healthDecision.Reason) " +
            "capture_burst=$captureBurst preview=$($preview.Reason) " +
            ("changed_ratio={0:N6}" -f [double]$preview.ChangedRatio))
    }

    $shouldStop = [bool]$healthDecision.ShouldStop -or [bool]$gameplayDecision.ShouldStop
    $stopReason = if ($healthDecision.ShouldStop) {
        $healthDecision.StopReason
    }
    else {
        $gameplayDecision.StopReason
    }
    if ($shouldStop) {
        $bridgeMutex = New-Object Threading.Mutex($false, "Global\VivhiteBilibiliLiveBridge")
        $locked = $false
        try {
            try { $locked = $bridgeMutex.WaitOne([TimeSpan]::FromSeconds(15)) }
            catch [Threading.AbandonedMutexException] { $locked = $true }
            if (-not $locked) {
                Write-CaptureHealthAudit "watch=stop_deferred bridge_busy"
                if ($healthDecision.ShouldStop) {
                    if ($healthDecision.Signal -eq "CorroboratedFailure") {
                        $corroboratedFailureCount = $ConsecutiveFailures - 1
                    }
                    else {
                        $lowMotionOnlyCount = $LowMotionOnlyLimit - 1
                    }
                }
            }
            elseif ((Get-LivehimeStreamingState) -eq "Streaming") {
                Write-CaptureHealthAudit (("watch=safety_stop reason={0} capture_signal={1} " -f
                    $stopReason, $healthDecision.Signal) +
                    ("gameplay_state={0} gameplay_reason={1} gameplay_elapsed_seconds={2:N1} " -f
                        $gameplayDecision.State, $gameplayDecision.Reason,
                        [double]$gameplayDecision.ElapsedSeconds) +
                    "run_id=$gameplayRunId decision_id=$gameplayDecisionId outcome_at=$gameplayOutcomeAt")
                try {
                    Invoke-LivehimeStop -LivehimeExe $livehimeExe -TimeoutSeconds 60
                    Write-CaptureHealthAudit "watch=safety_stop result=idle"
                }
                catch {
                    Write-CaptureHealthAudit "watch=safety_stop error=$($_.Exception.Message)"
                }
                try {
                    $ttsRestore = Restore-AscendIndexTtsAfterBroadcast -ProjectRoot $ProjectRoot
                    Write-CaptureHealthAudit ("watch=indextts_restore state={0} owner_pid={1}" -f
                        $ttsRestore.State, $ttsRestore.OwnerPid)
                }
                catch {
                    Write-CaptureHealthAudit "watch=indextts_restore error=$($_.Exception.Message)"
                }
                try {
                    $game = Get-SlayTheSpireWindow -GameDir $GameDir
                    if ($game) {
                        Set-SlayTheSpireTopMost -GameDir $GameDir -TimeoutSeconds 15
                        [void](Set-AscendViewerTopMost -ProjectRoot $ProjectRoot)
                    }
                }
                catch {
                    Write-CaptureHealthAudit "watch=restoration error=$($_.Exception.Message)"
                }
                return
            }
        }
        finally {
            if ($locked) { $bridgeMutex.ReleaseMutex() }
            $bridgeMutex.Dispose()
        }
    }
    Start-Sleep -Seconds $PollSeconds
}
