<#
.SYNOPSIS
    Records T20 with OBS start/stop state proven by the output media.

.DESCRIPTION
    OBS must be closed and already configured to OutputDirectory.  The runner
    launches OBS with --startrecording, requires exactly one new MKV/MP4, then
    records a clean Vivhite identity hold.  It will not report success until
    the non-empty media file is stable after an explicit stop.

    Operator marks are not native action evidence.  T20 has no formal action
    chain; a later source/probe/process/evidence/span binder decides whether
    the take is production eligible with an empty action_evidence array.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^a[0-9]+$')][string]$AttemptId,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][int]$GameProcessId,
    [string]$ObsExe = 'C:\Program Files\obs-studio\bin\64bit\obs64.exe',
    [int]$ObsRecordButtonX = 1240,
    [int]$ObsRecordButtonY = 657,
    [double]$PreRollSeconds = 2.0,
    [double]$IdentitySeconds = 12.0,
    [double]$TailSeconds = 4.0,
    [string]$RawArtifact = ''
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\..\test\GameTest.psm1') -Force
. (Join-Path $PSScriptRoot 'promo_capture_operator_common.ps1')

if ($PreRollSeconds -ne 2.0) { throw 'PreRollSeconds is fixed at 2 seconds' }
if ($IdentitySeconds -lt 12.0 -or $IdentitySeconds -gt 20.0) { throw 'IdentitySeconds must be 12-20 seconds' }
if ($TailSeconds -lt 3.0 -or $TailSeconds -gt 6.0) { throw 'TailSeconds must be 3-6 seconds' }
if (-not (Test-Path -LiteralPath $ObsExe -PathType Leaf)) { throw "OBS executable missing: $ObsExe" }
if (@(Get-Process -Name obs64 -ErrorAction SilentlyContinue).Count -ne 0) {
    throw 'OBS must be closed before verified launch; refusing to reuse an ambiguous recorder process'
}

$output = Assert-NewOperatorAttempt -OutputDirectory $OutputDirectory -AttemptId $AttemptId
$partialPath = Join-Path $output 'operator-marks.partial.json'
$finalPath = Join-Path $output 'operator-marks.json'
$rawValue = if ([string]::IsNullOrWhiteSpace($RawArtifact)) { "raw/takes/T20/$AttemptId.mkv" } else { $RawArtifact.Replace('\','/') }
$game = Resolve-UniqueOperatorProcess -ProcessName 'SlayTheSpire2' -ProcessId $GameProcessId
$gameRecord = Get-OperatorProcessRecord -Process $game

function Get-AttemptMedia {
    return @(Get-ChildItem -LiteralPath $output -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -match '(?i)^\.(mkv|mp4)$' } |
        Sort-Object LastWriteTimeUtc)
}

function Wait-ForSingleMedia {
    param([int]$TimeoutMilliseconds = 15000)
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    do {
        $media = @(Get-AttemptMedia)
        if ($media.Count -eq 1) { return $media[0] }
        if ($media.Count -gt 1) { throw 'OBS created multiple media files in a fresh attempt' }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

function Wait-ForStableMedia {
    param([Parameter(Mandatory=$true)][System.IO.FileInfo]$Media, [int]$TimeoutMilliseconds = 12000)
    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    $previous = -1L
    $stable = 0
    do {
        $Media.Refresh()
        if ($Media.Length -gt 0 -and $Media.Length -eq $previous) {
            $stable++
            if ($stable -ge 4) { return $true }
        }
        else {
            $stable = 0
        }
        $previous = $Media.Length
        Start-Sleep -Milliseconds 350
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

function Save-Marks {
    Write-OperatorMarksAtomic -Marks $marks -PartialPath $partialPath
}

$marks = [ordered]@{
    schema_version = 1
    kind = 'vivhite_promo_t20_verified_operator_marks_v1'
    status = 'prepared'
    take_id = 'T20'
    attempt_id = $AttemptId
    run_id = 'run-20260903T0012-director-v2-a1'
    raw_artifact = [ordered]@{ path=$rawValue; provenance='operator_marked_verified_obs_source' }
    game_process = $gameRecord
    recorder_process = $null
    checkpoints = @()
    display = [ordered]@{
        frame_begin_mark = $null
        identity_begin_mark = $null
        identity_end_mark = $null
        frame_end_mark = $null
    }
    recording = [ordered]@{
        launch_request = $null
        media_started = $null
        stop_request = $null
        media_stopped = $null
    }
    native_action_evidence = $false
    action_evidence = @()
    production_eligible = $false
    note = 'T20 has no formal_action_chain. These marks prove recorder boundaries and visual timing; production eligibility remains pending the byte/probe/process/evidence/span binder.'
    errors = @()
}

$obs = $null
$media = $null
$recordingStarted = $false
$recordingStopped = $false
try {
    Set-WindowForeground -ProcessId $game.Id
    Start-Sleep -Milliseconds 800
    $checkpointPath = Join-Path $output 'checkpoint-before-mark.png'
    $checkpoint = Save-Screenshot -Path $checkpointPath
    $marks.checkpoints += ,[ordered]@{
        purpose = 'vivhite_character_select_identity_precondition'
        descriptor = Get-OperatorFileDescriptor -Path $checkpoint
        review_status = 'operator_review_required'
        note = 'Confirm 白绮, 78/78, 99, 孤高冠冕 and no forbidden surface.'
    }
    Save-Marks

    $marks.recording.launch_request = Get-OperatorMark
    $obs = Start-Process -FilePath $ObsExe -WorkingDirectory (Split-Path -Parent $ObsExe) -ArgumentList '--startrecording' -WindowStyle Normal -PassThru
    $windowDeadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 300
        $obs.Refresh()
    } while ($obs.MainWindowHandle -eq 0 -and -not $obs.HasExited -and [DateTime]::UtcNow -lt $windowDeadline)
    if ($obs.HasExited -or $obs.MainWindowHandle -eq 0) { throw 'OBS did not present a live main window' }
    $marks.recorder_process = Get-OperatorProcessRecord -Process $obs
    $media = Wait-ForSingleMedia
    if ($null -eq $media) { throw 'OBS --startrecording did not create exactly one media file' }
    $recordingStarted = $true
    Start-Sleep -Milliseconds 1000
    $media.Refresh()
    # OBS/Windows may keep a live Matroska file at length zero until the muxer
    # flushes or closes.  Exactly one newly-created media path proves start;
    # the stop gate below requires stable, non-empty bytes and records the
    # authoritative final descriptor.
    $marks.recording.media_started = [ordered]@{
        path = $media.FullName.Replace('\','/')
        observed_live_bytes = [long]$media.Length
        status = 'exactly_one_new_media_path_created_live'
    }
    Set-WindowForeground -ProcessId $obs.Id
    Start-Sleep -Milliseconds 500
    $obsStartedPath = Join-Path $output 'obs-recording-confirmed.png'
    $obsStarted = Save-Screenshot -Path $obsStartedPath
    $marks.checkpoints += ,[ordered]@{ purpose='obs_recording_confirmed_after_command_line_start'; descriptor=Get-OperatorFileDescriptor -Path $obsStarted; review_status='operator_review_required' }
    $marks.status = 'recording_verified'
    Save-Marks

    Set-WindowForeground -ProcessId $game.Id
    Sleep-OperatorSeconds -Seconds $PreRollSeconds
    $marks.display.frame_begin_mark = Get-OperatorMark
    $marks.display.identity_begin_mark = $marks.display.frame_begin_mark
    $beginPath = Join-Path $output 'operator-frame-begin.png'
    $begin = Save-Screenshot -Path $beginPath
    $marks.checkpoints += ,[ordered]@{ purpose='post_mark_character_select_frame_begin'; descriptor=Get-OperatorFileDescriptor -Path $begin; review_status='operator_review_required' }
    Save-Marks

    Sleep-OperatorSeconds -Seconds $IdentitySeconds
    $marks.display.identity_end_mark = Get-OperatorMark
    $identityEndPath = Join-Path $output 'operator-identity-end.png'
    $identityEnd = Save-Screenshot -Path $identityEndPath
    $marks.checkpoints += ,[ordered]@{ purpose='character_select_identity_hold_end'; descriptor=Get-OperatorFileDescriptor -Path $identityEnd; review_status='operator_review_required' }
    Save-Marks

    Sleep-OperatorSeconds -Seconds $TailSeconds
    $marks.display.frame_end_mark = Get-OperatorMark
    $endPath = Join-Path $output 'operator-frame-end.png'
    $end = Save-Screenshot -Path $endPath
    $marks.checkpoints += ,[ordered]@{ purpose='pre_stop_character_select_frame_end'; descriptor=Get-OperatorFileDescriptor -Path $end; review_status='operator_review_required' }
    Save-Marks

    Set-WindowForeground -ProcessId $obs.Id
    Start-Sleep -Milliseconds 800
    $beforeStopPath = Join-Path $output 'obs-before-stop.png'
    $beforeStop = Save-Screenshot -Path $beforeStopPath
    $marks.checkpoints += ,[ordered]@{ purpose='obs_before_explicit_stop'; descriptor=Get-OperatorFileDescriptor -Path $beforeStop; review_status='operator_review_required' }
    $marks.recording.stop_request = Get-OperatorMark
    Invoke-ObsRecordToggle -Process $obs -ExpectedAction stop
    if (-not (Wait-ObsRecordState -Process $obs -ExpectedState stopped)) {
        throw 'OBS UI Automation stop did not reach the stopped button state'
    }
    Start-Sleep -Milliseconds 500
    if (-not (Wait-ForStableMedia -Media $media)) { throw 'OBS stop was not confirmed by stable non-empty media' }
    $recordingStopped = $true
    $recordingStarted = $false
    $marks.recording.media_stopped = Get-OperatorFileDescriptor -Path $media.FullName
    $afterStopPath = Join-Path $output 'obs-stopped-confirmed.png'
    $afterStop = Save-Screenshot -Path $afterStopPath
    $marks.checkpoints += ,[ordered]@{ purpose='obs_stopped_confirmed_after_stop'; descriptor=Get-OperatorFileDescriptor -Path $afterStop; review_status='operator_review_required' }
    $marks.status = 'operator_marks_complete_media_sealed_review_pending'
    Save-Marks
    Complete-OperatorMarks -PartialPath $partialPath -FinalPath $finalPath
    Write-Output "T20 verified operator marks written: $finalPath"
}
catch {
    $marks.status = 'operator_script_failed'
    $marks.errors += ,[ordered]@{ utc=[DateTime]::UtcNow.ToString('o'); message=$_.Exception.Message; category=[string]$_.CategoryInfo }
    if ($recordingStarted -and -not $recordingStopped -and $null -ne $obs -and -not $obs.HasExited) {
        try {
            Set-WindowForeground -ProcessId $obs.Id
            Start-Sleep -Milliseconds 350
            Invoke-ObsRecordToggle -Process $obs -ExpectedAction stop
            if ($null -ne $media) { [void](Wait-ForStableMedia -Media $media) }
        }
        catch {
            $marks.errors += ,[ordered]@{ utc=[DateTime]::UtcNow.ToString('o'); message="Best-effort OBS stop failed: $($_.Exception.Message)"; category='stop_failed' }
        }
    }
    Save-Marks
    throw
}
