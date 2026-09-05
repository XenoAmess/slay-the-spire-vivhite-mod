<#
Records a clean T20 character-select/idle visual candidate.  This runner only
writes operator marks and screenshots; it never fabricates native action/state
evidence.  Use a fresh attempt directory for every retry.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^a[0-9]+$')][string]$AttemptId,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [int]$GameProcessId = 0,
    [int]$ObsProcessId = 0,
    [int]$ObsRecordButtonX = 1240,
    [int]$ObsRecordButtonY = 657,
    [double]$PreRollSeconds = 2.0,
    [double]$IdentitySeconds = 8.0,
    [double]$TailSeconds = 3.5,
    [string]$RawArtifact = ''
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\..\test\GameTest.psm1') -Force
. (Join-Path $PSScriptRoot 'promo_capture_operator_common.ps1')
if ($PreRollSeconds -ne 2.0) { throw 'PreRollSeconds is fixed at 2 seconds' }
if ($IdentitySeconds -lt 6.0 -or $IdentitySeconds -gt 12.0) { throw 'IdentitySeconds must be 6-12 seconds' }
if ($TailSeconds -lt 3.0 -or $TailSeconds -gt 4.0) { throw 'TailSeconds must be 3-4 seconds' }
$output = Assert-NewOperatorAttempt -OutputDirectory $OutputDirectory -AttemptId $AttemptId
$partialPath = Join-Path $output 'operator-marks.partial.json'
$finalPath = Join-Path $output 'operator-marks.json'
$rawValue = if ([string]::IsNullOrWhiteSpace($RawArtifact)) { "raw/takes/T20/$AttemptId.mkv" } else { $RawArtifact.Replace('\','/') }
$game = Resolve-UniqueOperatorProcess -ProcessName 'SlayTheSpire2' -ProcessId $GameProcessId
$obs = Resolve-UniqueOperatorProcess -ProcessName 'obs64' -ProcessId $ObsProcessId
$marks = [ordered]@{
    schema_version = 1
    kind = 'vivhite_promo_t20_operator_marks_v1'
    status = 'prepared'
    take_id = 'T20'
    attempt_id = $AttemptId
    run_id = 'run-20260903T0012-director-v2-a1'
    raw_artifact = [ordered]@{ path = $rawValue; provenance = 'operator_marked_visual_candidate' }
    game_process = Get-OperatorProcessRecord -Process $game
    recorder_process = Get-OperatorProcessRecord -Process $obs
    checkpoints = @()
    display = [ordered]@{ frame_begin_mark=$null; identity_begin_mark=$null; identity_end_mark=$null; frame_end_mark=$null }
    recording = [ordered]@{ start_request=$null; media_started=$null; stop_request=$null; media_stopped=$null }
    errors = @()
    native_action_evidence = $false
    production_eligible = $false
    note = 'Character-select identity/idle operator marks. T20 has no formal_action_chain, so action_evidence remains empty; production eligibility is decided later by the source/probe/process/evidence/span binder.'
}
$recordingStarted = $false
$completed = $false
function Save-Marks {
    Write-OperatorMarksAtomic -Marks $marks -PartialPath $partialPath
}

function Get-NewAttemptMedia {
    param([Parameter(Mandatory = $true)][string]$Directory)

    return @(Get-ChildItem -LiteralPath $Directory -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -match '(?i)^\.(mkv|mp4)$' } |
        Sort-Object LastWriteTimeUtc)
}

function Wait-AttemptMediaStarted {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [int]$TimeoutMilliseconds = 5000
    )

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    do {
        $media = @(Get-NewAttemptMedia -Directory $Directory)
        if ($media.Count -eq 1) { return $media[0] }
        if ($media.Count -gt 1) {
            throw "OBS created more than one media file in the new attempt directory: $Directory"
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

function Wait-AttemptMediaStable {
    param(
        [Parameter(Mandatory = $true)][System.IO.FileInfo]$Media,
        [int]$TimeoutMilliseconds = 10000
    )

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    $previousLength = -1L
    $stableSamples = 0
    do {
        $Media.Refresh()
        $length = [long]$Media.Length
        if ($length -gt 0 -and $length -eq $previousLength) {
            $stableSamples++
            if ($stableSamples -ge 3) { return $true }
        }
        else {
            $stableSamples = 0
        }
        $previousLength = $length
        Start-Sleep -Milliseconds 350
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}
try {
    Set-WindowForeground -ProcessId $game.Id
    Start-Sleep -Milliseconds 800
    $prePath = Join-Path $output 'checkpoint-before-mark.png'
    $pre = Save-Screenshot -Path $prePath
    $marks.checkpoints += ,[ordered]@{ purpose='character_select_identity_checkpoint'; descriptor=Get-OperatorFileDescriptor -Path $pre; review_status='operator_review_required'; note='Confirm white-hair Vivhite panel reads 白绮, 78/78, 99, 孤高冠冕 before mark.' }
    Save-Marks -Marks $marks -PartialPath $partialPath
    Set-WindowForeground -ProcessId $obs.Id
    Start-Sleep -Milliseconds 800
    $marks.recording.start_request = Get-OperatorMark
    $recordingStarted = $true
    Invoke-ObsRecordToggle -Process $obs -ExpectedAction start
    if (-not (Wait-ObsRecordState -Process $obs -ExpectedState recording)) {
        throw 'OBS UI Automation start did not reach the recording button state'
    }
    Start-Sleep -Milliseconds 500
    $startedMedia = Wait-AttemptMediaStarted -Directory $output
    if ($null -eq $startedMedia) {
        $recordingStarted = $false
        throw "OBS start was not confirmed: no MKV/MP4 appeared in $output"
    }
    $startCheckPath = Join-Path $output 'obs-recording-confirmed.png'
    $startCheck = Save-Screenshot -Path $startCheckPath
    $marks.checkpoints += ,[ordered]@{ purpose='obs_recording_confirmed_after_start'; descriptor=Get-OperatorFileDescriptor -Path $startCheck; review_status='operator_review_required' }
    $marks.recording.media_started = Get-OperatorFileDescriptor -Path $startedMedia.FullName
    $marks.status = 'recording'
    Save-Marks -Marks $marks -PartialPath $partialPath
    Set-WindowForeground -ProcessId $game.Id
    Sleep-OperatorSeconds -Seconds $PreRollSeconds
    $marks.display.frame_begin_mark = Get-OperatorMark
    $marks.display.identity_begin_mark = $marks.display.frame_begin_mark
    $beginPath = Join-Path $output 'operator-frame-begin.png'
    $begin = Save-Screenshot -Path $beginPath
    $marks.checkpoints += ,[ordered]@{ purpose='post_mark_character_select_frame_begin'; descriptor=Get-OperatorFileDescriptor -Path $begin; review_status='operator_review_required' }
    Save-Marks -Marks $marks -PartialPath $partialPath
    Sleep-OperatorSeconds -Seconds $IdentitySeconds
    $marks.display.identity_end_mark = Get-OperatorMark
    Sleep-OperatorSeconds -Seconds $TailSeconds
    $marks.display.frame_end_mark = Get-OperatorMark
    $endPath = Join-Path $output 'operator-frame-end.png'
    $end = Save-Screenshot -Path $endPath
    $marks.checkpoints += ,[ordered]@{ purpose='pre_stop_character_select_frame_end'; descriptor=Get-OperatorFileDescriptor -Path $end; review_status='operator_review_required' }
    Save-Marks -Marks $marks -PartialPath $partialPath
    Set-WindowForeground -ProcessId $obs.Id
    Start-Sleep -Milliseconds 800
    $marks.recording.stop_request = Get-OperatorMark
    Invoke-ObsRecordToggle -Process $obs -ExpectedAction stop
    if (-not (Wait-ObsRecordState -Process $obs -ExpectedState stopped)) {
        throw 'OBS UI Automation stop did not reach the stopped button state'
    }
    Start-Sleep -Milliseconds 500
    if (-not (Wait-AttemptMediaStable -Media $startedMedia)) {
        throw "OBS stop was not confirmed: media did not become a stable non-empty file: $($startedMedia.FullName)"
    }
    $stopCheckPath = Join-Path $output 'obs-stopped-confirmed.png'
    $stopCheck = Save-Screenshot -Path $stopCheckPath
    $marks.checkpoints += ,[ordered]@{ purpose='obs_stopped_confirmed_after_stop'; descriptor=Get-OperatorFileDescriptor -Path $stopCheck; review_status='operator_review_required' }
    $marks.recording.media_stopped = Get-OperatorFileDescriptor -Path $startedMedia.FullName
    $recordingStarted = $false
    $marks.status = 'operator_marks_complete_media_review_pending'
    Save-Marks -Marks $marks -PartialPath $partialPath
    Complete-OperatorMarks -PartialPath $partialPath -FinalPath $finalPath
    $completed = $true
    Write-Output "T20 operator marks written: $finalPath"
}
catch {
    $marks.status = 'operator_script_failed'
    $marks.errors += ,[ordered]@{ utc=[DateTime]::UtcNow.ToString('o'); message=$_.Exception.Message; category=[string]$_.CategoryInfo }
    if ($recordingStarted) {
        try { Set-WindowForeground -ProcessId $obs.Id; Start-Sleep -Milliseconds 350; Invoke-ObsRecordToggle -Process $obs -ExpectedAction stop; $recordingStarted=$false } catch { $marks.errors += ,[ordered]@{ utc=[DateTime]::UtcNow.ToString('o'); message="Unable to issue best-effort OBS stop: $($_.Exception.Message)"; category='stop_failed' } }
    }
    Save-Marks -Marks $marks -PartialPath $partialPath
    throw
}
finally { if (-not $completed) { Save-Marks -Marks $marks -PartialPath $partialPath } }
