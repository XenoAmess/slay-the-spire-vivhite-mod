<#
.SYNOPSIS
    Records one operator-marked T17 deck-view montage.

.DESCRIPTION
    The caller completes all staged setup before invocation: a real Vivhite run
    is open on NDeckViewScreen, the current grid and a route-card target have
    been measured, and console/search/sort/debug surfaces are closed.  This
    script starts an already-configured OBS recording, leaves a clean preroll,
    sends real wheel input, hovers one current VIVHITE_CARD_* target, and keeps
    a result tail.  It writes only operator marks (with UTC/Stopwatch ticks)
    and optional review screenshots.  It never creates native action evidence,
    state.before/state.after, or a claim that a tooltip was actually visible.

    The source frame numbers, hashes, runtime card titles and clean-surface
    verdict must be filled from the closed MKV by the archive workflow.  Use a
    new AttemptId/output directory for every retry; existing media/marks are
    rejected rather than overwritten.

.EXAMPLE
    .\run_t17_capture.ps1 `
      -OutputDirectory 'G:\workspace\slay-the-spire-vivhite-mod\tools\promo\runs\run-...\capture\takes\T17\a01' `
      -AttemptId a01 -SessionId '<session>' -GameRunId '<native-run>' `
      -TargetCardId VIVHITE_CARD_TRICHROMATIC_WALTZ -TargetCardX 1220 -TargetCardY 680 `
      -GridX 960 -GridY 500 -GameProcessId 1234 -ObsProcessId 5678

    Coordinates and IDs in this example are placeholders and must be replaced
    by the current-frame observations before the script is run.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^a[0-9]+$')][string]$AttemptId,
    [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$OutputDirectory,
    [string]$RunId = 'run-20260903T0012-director-v2-a1',
    [Parameter(Mandatory = $true)][ValidatePattern('^VIVHITE_CARD_[A-Z0-9_]+$')][string]$TargetCardId,
    [Parameter(Mandatory = $true)][int]$TargetCardX,
    [Parameter(Mandatory = $true)][int]$TargetCardY,
    [Parameter(Mandatory = $true)][int]$GridX,
    [Parameter(Mandatory = $true)][int]$GridY,
    [int]$WheelNotches = 8,
    [int]$WheelDelta = -120,
    [double]$PreRollSeconds = 2.0,
    [double]$ScrollSeconds = 4.0,
    [double]$HoverSeconds = 2.0,
    [double]$ResultTailSeconds = 3.5,
    [int]$ObsRecordButtonX = 1260,
    [int]$ObsRecordButtonY = 657,
    [string]$GameProcessName = 'SlayTheSpire2',
    [string]$ObsProcessName = 'obs64',
    [int]$GameProcessId = 0,
    [int]$ObsProcessId = 0,
    [string]$SessionId = '',
    [string]$GameRunId = '',
    [long]$SetupEndFrame = -1,
    [string]$RawArtifact = '',
    [switch]$NoCheckpoint
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$gameTest = Join-Path $PSScriptRoot '..\..\test\GameTest.psm1'
Import-Module $gameTest -Force -ErrorAction Stop
. (Join-Path $PSScriptRoot 'promo_capture_operator_common.ps1')

if ([string]::IsNullOrWhiteSpace($GameProcessName) -or [string]::IsNullOrWhiteSpace($ObsProcessName)) {
    throw 'GameProcessName and ObsProcessName must be non-empty process names'
}

if ($WheelNotches -lt 1 -or $WheelNotches -gt 100) {
    throw 'WheelNotches must be between 1 and 100'
}
if ($WheelDelta -ge 0) { throw 'WheelDelta must be negative for the required downward scroll' }
foreach ($coordinate in @(
        @{ Name = 'TargetCardX'; Value = $TargetCardX },
        @{ Name = 'TargetCardY'; Value = $TargetCardY },
        @{ Name = 'GridX'; Value = $GridX },
        @{ Name = 'GridY'; Value = $GridY },
        @{ Name = 'ObsRecordButtonX'; Value = $ObsRecordButtonX },
        @{ Name = 'ObsRecordButtonY'; Value = $ObsRecordButtonY }
    )) {
    if ($coordinate.Name -match 'ObsRecordButton') {
        if ($coordinate.Value -lt 0 -or $coordinate.Value -gt 10000) {
            throw "$($coordinate.Name) is outside the allowed screen coordinate range"
        }
    } elseif ($coordinate.Name -match 'X') {
        if ($coordinate.Value -le 0 -or $coordinate.Value -ge 1920) {
            throw "$($coordinate.Name) is outside the 1920px game surface"
        }
    } elseif ($coordinate.Name -match 'Y') {
        if ($coordinate.Value -le 0 -or $coordinate.Value -ge 1080) {
            throw "$($coordinate.Name) is outside the 1080px game surface"
        }
    }
}
foreach ($duration in @(
        @{ Name = 'PreRollSeconds'; Value = $PreRollSeconds },
        @{ Name = 'ScrollSeconds'; Value = $ScrollSeconds },
        @{ Name = 'HoverSeconds'; Value = $HoverSeconds },
        @{ Name = 'ResultTailSeconds'; Value = $ResultTailSeconds }
    )) {
    if ($duration.Value -lt 0) { throw "$($duration.Name) cannot be negative" }
}
if ($PreRollSeconds -ne 2.0) { throw 'PreRollSeconds is fixed at 2 seconds by the capture contract' }
if ($HoverSeconds -lt 1.5) { throw 'HoverSeconds must be at least 1.5 seconds' }
if ($ResultTailSeconds -lt 3.0 -or $ResultTailSeconds -gt 4.0) {
    throw 'ResultTailSeconds must remain within the 3-4 second contract range'
}

$output = Assert-NewOperatorAttempt -OutputDirectory $OutputDirectory -AttemptId $AttemptId
$partialPath = Join-Path $output 'operator-marks.partial.json'
$finalPath = Join-Path $output 'operator-marks.json'
$rawArtifactValue = if ([string]::IsNullOrWhiteSpace($RawArtifact)) {
    "raw/takes/T17/$AttemptId.mkv"
} else {
    $RawArtifact.Replace('\', '/')
}
$rawIsRelative = -not [System.IO.Path]::IsPathRooted($rawArtifactValue)
$setupFrameValue = if ($SetupEndFrame -ge 0) { $SetupEndFrame } else { $null }

$game = Resolve-UniqueOperatorProcess -ProcessName $GameProcessName -ProcessId $GameProcessId
$obs = Resolve-UniqueOperatorProcess -ProcessName $ObsProcessName -ProcessId $ObsProcessId
$gameRecord = Get-OperatorProcessRecord -Process $game
$obsRecord = Get-OperatorProcessRecord -Process $obs

$marks = [ordered]@{
    schema_version = 1
    kind = 'vivhite_promo_t17_operator_marks_v1'
    status = 'prepared'
    take_id = 'T17'
    attempt_id = $AttemptId
    run_id = $RunId
    output_directory = $output
    operator_mark_only = $true
    action_evidence_emitted = $false
    action_evidence = @()
    formal_action_source = $true
    formal_action_claimed = $false
    source_plan = [ordered]@{
        owner_subshot = 'S10-04-crimson-route'
        raw_artifact = $rawArtifactValue
        raw_artifact_must_be_run_relative = $true
        raw_artifact_is_relative = $rawIsRelative
        planned_display_duration_seconds = 12.0
        planned_display_frames = 720
        frame_numbers = $null
        note = 'Frame numbers and source hash are filled only after the MKV closes and is probed.'
    }
    session = [ordered]@{
        session_id = if ([string]::IsNullOrWhiteSpace($SessionId)) { $null } else { $SessionId }
        game_run_id = if ([string]::IsNullOrWhiteSpace($GameRunId)) { $null } else { $GameRunId }
        game_process_name = $GameProcessName
        recorder_process_name = $ObsProcessName
        game = $gameRecord
        recorder = $obsRecord
    }
    setup = [ordered]@{
        provenance = 'staged_setup'
        screen_kind = 'deck_view_or_current_card_library'
        route = 'operator_prepared_current_vivhite_deck_view'
        setup_end_frame = $setupFrameValue
        screen_precondition = 'operator must have a clean NDeckViewScreen deck view open; no console, sorting, search, overlay, loading or system cursor capture'
        checkpoint_review_required = $true
    }
    coordinates = [ordered]@{
        coordinate_source = 'operator_observed_current_frame'
        grid = [ordered]@{ x = $GridX; y = $GridY }
        target_card = [ordered]@{ claimed_id = $TargetCardId; x = $TargetCardX; y = $TargetCardY }
        obs_record_button = [ordered]@{ x = $ObsRecordButtonX; y = $ObsRecordButtonY }
    }
    timing_plan = [ordered]@{
        pre_roll_seconds = $PreRollSeconds
        scroll_seconds = $ScrollSeconds
        hover_seconds = $HoverSeconds
        result_tail_seconds = $ResultTailSeconds
        wheel_notches = $WheelNotches
        wheel_delta = $WheelDelta
    }
    checkpoints = @()
    events = @()
    recording = [ordered]@{
        start_request = $null
        stop_request = $null
        authoritative_boundary = 'OBS toggle request marks; source frame count and media timestamps are verified later'
    }
    display = [ordered]@{
        frame_begin_mark = $null
        scroll_begin_mark = $null
        scroll_end_mark = $null
        hover_begin_mark = $null
        hover_end_mark = $null
        result_tail_begin_mark = $null
        frame_end_mark = $null
        source_frame_begin = $null
        source_frame_end = $null
    }
    errors = @()
    next_required_steps = @(
        'Keep the raw MKV and external source immutable after OBS closes.',
        'Run ffprobe and Get-FileHash; extract frame-begin/frame-end from this same raw.',
        'Create runtime-manifest and lineage with observed card IDs/titles and clean-surface review.',
        'Write take-row.production.json with action_evidence=[] and exact 720-frame span; never promote these operator marks as native action evidence.'
    )
}

function Save-Marks {
    $marks.updated_utc = [DateTime]::UtcNow.ToString('o')
    Write-OperatorMarksAtomic -Marks $marks -PartialPath $partialPath
}

function Add-MarkEvent {
    param([Parameter(Mandatory = $true)][object]$Event)
    $marks.events += ,$Event
    Save-Marks
}

$recordingStarted = $false
$completed = $false
try {
    Set-WindowForeground -ProcessId $game.Id
    Start-Sleep -Milliseconds 350
    if (-not $NoCheckpoint) {
        $checkpointPath = Join-Path $output 'checkpoint-before-mark.png'
        $saved = Save-Screenshot -Path $checkpointPath
        $marks.checkpoints += ,[ordered]@{
            purpose = 'staged_setup_clean_checkpoint'
            descriptor = Get-OperatorFileDescriptor -Path $saved
            review_status = 'operator_review_required'
            note = 'This checkpoint is recovery evidence only and is not a production frame/evidence ref.'
        }
        Save-Marks
    }

    Set-WindowForeground -ProcessId $obs.Id
    Start-Sleep -Milliseconds 350
    $start = Get-OperatorMark
    $marks.recording.start_request = $start
    # Treat the toggle as an uncertain boundary: if the click throws or the
    # operator aborts between mouse-down/up, the catch path still attempts a
    # stop so OBS is not left recording unattended.
    $recordingStarted = $true
    Invoke-ObsRecordToggle -Process $obs -ExpectedAction start
    if (-not (Wait-ObsRecordState -Process $obs -ExpectedState recording)) {
        throw 'OBS UI Automation start did not reach the recording button state'
    }
    $marks.status = 'recording'
    Save-Marks

    Set-WindowForeground -ProcessId $game.Id
    Sleep-OperatorSeconds -Seconds $PreRollSeconds
    $marks.display.frame_begin_mark = Get-OperatorMark
    if (-not $NoCheckpoint) {
        $beginPath = Join-Path $output 'operator-frame-begin.png'
        $saved = Save-Screenshot -Path $beginPath
        $marks.checkpoints += ,[ordered]@{
            purpose = 'post_mark_frame_begin_reference'
            descriptor = Get-OperatorFileDescriptor -Path $saved
            review_status = 'operator_review_required'
        }
    }
    Save-Marks

    Move-Mouse -X $GridX -Y $GridY
    $scrollBegin = Get-OperatorMark
    $marks.display.scroll_begin_mark = $scrollBegin
    Save-Marks
    $intervalMs = [Math]::Max(50, [int][Math]::Round(($ScrollSeconds * 1000.0) / $WheelNotches))
    for ($index = 0; $index -lt $WheelNotches; $index++) {
        Invoke-OperatorWheel -X $GridX -Y $GridY -Delta $WheelDelta
        $wheelMark = Get-OperatorMark
        Add-MarkEvent ([ordered]@{
            kind = 'ui_observation_mark'
            action = 'wheel'
            direction = 'down'
            delta = $WheelDelta
            ordinal = $index + 1
            x = $GridX
            y = $GridY
            mark = $wheelMark
            native_action_evidence = $false
        })
        if ($index -lt $WheelNotches - 1) { Start-Sleep -Milliseconds $intervalMs }
    }
    $marks.display.scroll_end_mark = Get-OperatorMark
    Save-Marks

    Move-Mouse -X $TargetCardX -Y $TargetCardY
    $hoverBegin = Get-OperatorMark
    $marks.display.hover_begin_mark = $hoverBegin
    Add-MarkEvent ([ordered]@{
        kind = 'ui_observation_mark'
        action = 'hover_begin'
        claimed_card_id = $TargetCardId
        x = $TargetCardX
        y = $TargetCardY
        mark = $hoverBegin
        native_action_evidence = $false
    })
    Sleep-OperatorSeconds -Seconds $HoverSeconds
    $hoverEnd = Get-OperatorMark
    $marks.display.hover_end_mark = $hoverEnd
    Add-MarkEvent ([ordered]@{
        kind = 'ui_observation_mark'
        action = 'hover_end'
        claimed_card_id = $TargetCardId
        x = $TargetCardX
        y = $TargetCardY
        mark = $hoverEnd
        native_action_evidence = $false
    })

    $marks.display.result_tail_begin_mark = Get-OperatorMark
    Sleep-OperatorSeconds -Seconds $ResultTailSeconds
    $marks.display.frame_end_mark = Get-OperatorMark
    if (-not $NoCheckpoint) {
        $endPath = Join-Path $output 'operator-frame-end.png'
        $saved = Save-Screenshot -Path $endPath
        $marks.checkpoints += ,[ordered]@{
            purpose = 'pre_stop_frame_end_reference'
            descriptor = Get-OperatorFileDescriptor -Path $saved
            review_status = 'operator_review_required'
        }
    }
    Save-Marks

    Set-WindowForeground -ProcessId $obs.Id
    Start-Sleep -Milliseconds 350
    $stop = Get-OperatorMark
    $marks.recording.stop_request = $stop
    Invoke-ObsRecordToggle -Process $obs -ExpectedAction stop
    if (-not (Wait-ObsRecordState -Process $obs -ExpectedState stopped)) {
        throw 'OBS UI Automation stop did not reach the stopped button state'
    }
    $recordingStarted = $false
    $marks.status = 'operator_marks_complete_media_review_pending'
    Save-Marks
    Complete-OperatorMarks -PartialPath $partialPath -FinalPath $finalPath
    $completed = $true
    Write-Output "T17 operator marks written: $finalPath"
}
catch {
    $marks.status = 'operator_script_failed'
    $marks.errors += ,[ordered]@{
        utc = [DateTime]::UtcNow.ToString('o')
        message = $_.Exception.Message
        category = [string]$_.CategoryInfo
    }
    if ($recordingStarted) {
        try {
            Set-WindowForeground -ProcessId $obs.Id
            Start-Sleep -Milliseconds 250
            $stopOnError = Get-OperatorMark
            $marks.recording.stop_request = $stopOnError
            Invoke-ObsRecordToggle -Process $obs -ExpectedAction stop
            $recordingStarted = $false
        }
        catch {
            $marks.errors += ,[ordered]@{
                utc = [DateTime]::UtcNow.ToString('o')
                message = "Unable to issue best-effort OBS stop: $($_.Exception.Message)"
                category = 'stop_failed'
            }
        }
    }
    Save-Marks
    throw
}
finally {
    if (-not $completed) {
        Save-Marks
    }
}
