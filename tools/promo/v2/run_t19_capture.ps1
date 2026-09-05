<#
.SYNOPSIS
    Records one operator-marked T19 61-card library verification take.

.DESCRIPTION
    Use either -PreparedLibrary when the current frame is already the native
    Encyclopedia/card-library screen with the white pool selected, or
    -FromMainMenu with freshly measured Encyclopedia and filter coordinates.
    SearchCleared is a required operator assertion; the script never injects a
    count or card list.  A cropped OCR hint can be requested with
    -RequireCountOcr, but the native count=61 and all 61 current IDs still
    require post-capture runtime-manifest evidence.

    After setup this script starts an already-configured OBS recording, keeps a
    clean preroll, scrolls the current grid, hovers exactly three supplied
    VIVHITE_CARD_* targets, and records a stable tail.  It writes only
    operator marks and review screenshots.  Wheel/hover marks are UI
    observations, not native action_evidence or state.before/state.after.
    Every retry needs a new AttemptId/output directory; existing media/marks
    are rejected rather than overwritten.

.EXAMPLE
    .\run_t19_capture.ps1 `
      -OutputDirectory 'G:\workspace\slay-the-spire-vivhite-mod\tools\promo\runs\run-...\capture\takes\T19\a01' `
      -AttemptId a01 -PreparedLibrary -SearchCleared `
      -GridX 960 -GridY 500 -CountRegionX 820 -CountRegionY 90 -CountRegionWidth 280 -CountRegionHeight 70 `
      -RepresentativeCard 'VIVHITE_CARD_AXIOM_RING:480:320','VIVHITE_CARD_ASTRAL_PURSUIT:820:320','VIVHITE_CARD_TRICHROMATIC_WALTZ:1160:320'

    Coordinates and IDs in this example are placeholders and must be replaced
    by current-frame observations before recording.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][ValidatePattern('^a[0-9]+$')][string]$AttemptId,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [string]$RunId = 'run-20260903T0012-director-v2-a1',
    [Parameter(Mandatory = $true)][int]$GridX,
    [Parameter(Mandatory = $true)][int]$GridY,
    [Parameter(Mandatory = $true)][int]$CountRegionX,
    [Parameter(Mandatory = $true)][int]$CountRegionY,
    [Parameter(Mandatory = $true)][int]$CountRegionWidth,
    [Parameter(Mandatory = $true)][int]$CountRegionHeight,
    [Parameter(Mandatory = $true)][string[]]$RepresentativeCard,
    [Parameter(Mandatory = $true)][switch]$SearchCleared,
    [switch]$FromMainMenu,
    [switch]$PreparedLibrary,
    [int]$EncyclopediaX = 0,
    [int]$EncyclopediaY = 0,
    [int]$FilterX = 0,
    [int]$FilterY = 0,
    [int]$ExpectedCount = 61,
    [switch]$RequireCountOcr,
    [int]$WheelNotches = 10,
    [int]$WheelDelta = -120,
    [double]$PreRollSeconds = 2.0,
    [double]$ScrollSeconds = 4.0,
    [double]$PostScrollSettleSeconds = 0.75,
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

if ($ExpectedCount -ne 61) { throw 'T19 is fixed to the native 61-card count; ExpectedCount must remain 61' }
if ([string]::IsNullOrWhiteSpace($GameProcessName) -or [string]::IsNullOrWhiteSpace($ObsProcessName)) {
    throw 'GameProcessName and ObsProcessName must be non-empty process names'
}
if ($RequireCountOcr -and $NoCheckpoint) {
    throw '-RequireCountOcr requires the checkpoint screenshot; remove -NoCheckpoint so the count crop can be reviewed'
}
if ($FromMainMenu -eq $PreparedLibrary -or (-not $FromMainMenu -and -not $PreparedLibrary)) {
    throw 'Pass exactly one of -FromMainMenu or -PreparedLibrary'
}
if ($FromMainMenu -and ($FilterX -le 0 -or $FilterY -le 0)) {
    throw 'FromMainMenu requires the currently observed white-card-filter coordinates via -FilterX/-FilterY'
}
if ($FromMainMenu -and ($EncyclopediaX -le 0 -or $EncyclopediaY -le 0)) {
    throw 'FromMainMenu requires the currently observed Encyclopedia-entry coordinates via -EncyclopediaX/-EncyclopediaY'
}
if ($WheelNotches -lt 1 -or $WheelNotches -gt 100) {
    throw 'WheelNotches must be between 1 and 100'
}
if ($WheelDelta -ge 0) { throw 'WheelDelta must be negative for the required downward scroll' }
if ($PreRollSeconds -ne 2.0) { throw 'PreRollSeconds is fixed at 2 seconds by the capture contract' }
if ($HoverSeconds -lt 1.5) { throw 'HoverSeconds must be at least 1.5 seconds' }
if ($ResultTailSeconds -lt 3.0 -or $ResultTailSeconds -gt 4.0) {
    throw 'ResultTailSeconds must remain within the 3-4 second contract range'
}
if ($RepresentativeCard.Count -ne 3) {
    throw 'RepresentativeCard must contain exactly three current VIVHITE_CARD_<...>:x:y entries'
}
if ($CountRegionWidth -le 0 -or $CountRegionHeight -le 0) {
    throw 'CountRegionWidth and CountRegionHeight must be positive'
}
foreach ($coordinate in @(
        @{ Name = 'GridX'; Value = $GridX; Limit = 1920 },
        @{ Name = 'GridY'; Value = $GridY; Limit = 1080 },
        @{ Name = 'CountRegionX'; Value = $CountRegionX; Limit = 1920 },
        @{ Name = 'CountRegionY'; Value = $CountRegionY; Limit = 1080 },
        @{ Name = 'EncyclopediaX'; Value = $EncyclopediaX; Limit = 1920 },
        @{ Name = 'EncyclopediaY'; Value = $EncyclopediaY; Limit = 1080 },
        @{ Name = 'FilterX'; Value = $FilterX; Limit = 1920 },
        @{ Name = 'FilterY'; Value = $FilterY; Limit = 1080 }
    )) {
    if ($coordinate.Value -lt 0 -or $coordinate.Value -ge $coordinate.Limit) {
        if ($coordinate.Name -in @('FilterX', 'FilterY') -and $PreparedLibrary) { continue }
        throw "$($coordinate.Name) is outside the 1920x1080 game surface"
    }
}
if ($GridX -le 0 -or $GridY -le 0) {
    throw 'GridX and GridY must be positive current-frame coordinates'
}
foreach ($coordinate in @(
        @{ Name = 'ObsRecordButtonX'; Value = $ObsRecordButtonX },
        @{ Name = 'ObsRecordButtonY'; Value = $ObsRecordButtonY }
    )) {
    if ($coordinate.Value -lt 0 -or $coordinate.Value -gt 10000) {
        throw "$($coordinate.Name) is outside the allowed screen coordinate range"
    }
}
if ($CountRegionX + $CountRegionWidth -gt 1920 -or $CountRegionY + $CountRegionHeight -gt 1080) {
    throw 'Count OCR region exceeds the 1920x1080 game surface'
}

function Parse-RepresentativeCard {
    param([Parameter(Mandatory = $true)][string]$Spec)
    if ($Spec -notmatch '^((?:VIVHITE_CARD_[A-Z0-9_]+)):([0-9]+):([0-9]+)$') {
        throw "RepresentativeCard must be VIVHITE_CARD_<...>:x:y; received '$Spec'"
    }
    $x = [int]$Matches[2]
    $y = [int]$Matches[3]
    if ($x -le 0 -or $x -ge 1920 -or $y -le 0 -or $y -ge 1080) {
        throw "RepresentativeCard coordinate is outside the 1920x1080 game surface: '$Spec'"
    }
    return [ordered]@{ id = $Matches[1]; x = $x; y = $y }
}

$representatives = @()
foreach ($spec in $RepresentativeCard) { $representatives += ,(Parse-RepresentativeCard -Spec $spec) }
if ((@($representatives | ForEach-Object { $_.id } | Select-Object -Unique)).Count -ne 3) {
    throw 'RepresentativeCard IDs must be distinct'
}

$output = Assert-NewOperatorAttempt -OutputDirectory $OutputDirectory -AttemptId $AttemptId
$partialPath = Join-Path $output 'operator-marks.partial.json'
$finalPath = Join-Path $output 'operator-marks.json'
$rawArtifactValue = if ([string]::IsNullOrWhiteSpace($RawArtifact)) {
    "raw/takes/T19/$AttemptId.mkv"
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
    kind = 'vivhite_promo_t19_operator_marks_v1'
    status = 'prepared'
    take_id = 'T19'
    attempt_id = $AttemptId
    run_id = $RunId
    output_directory = $output
    operator_mark_only = $true
    ui_observation_only = $true
    action_evidence_emitted = $false
    action_evidence = @()
    formal_action_source = $true
    formal_action_claimed = $false
    source_plan = [ordered]@{
        owner_subshot = 'S10-01-card-library'
        raw_artifact = $rawArtifactValue
        raw_artifact_must_be_run_relative = $true
        raw_artifact_is_relative = $rawIsRelative
        planned_display_duration_seconds = 14.0
        planned_display_frames = 840
        frame_numbers = $null
        note = 'Frame numbers, source hash and the complete 61-ID list are filled only after the MKV closes and is reviewed.'
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
        screen_kind = 'card_library'
        route = if ($FromMainMenu) { 'main_menu_to_encyclopedia_then_operator_selected_filter' } else { 'operator_prepared_card_library' }
        pool_id = 'VIVHITE_CARD_POOL'
        setup_end_frame = $setupFrameValue
        search_cleared_asserted = $true
        expected_native_count = 61
        screen_precondition = 'operator must leave the current white card-pool filter selected, all search/rarity/type/cost filters cleared, and no console/overlay/loading/debug surface'
        checkpoint_review_required = $true
    }
    coordinates = [ordered]@{
        coordinate_source = 'operator_observed_current_frame'
        encyclopedia = if ($FromMainMenu) { [ordered]@{ x = $EncyclopediaX; y = $EncyclopediaY } } else { $null }
        white_filter = if ($FromMainMenu) { [ordered]@{ x = $FilterX; y = $FilterY } } else { $null }
        grid = [ordered]@{ x = $GridX; y = $GridY }
        count_region = [ordered]@{ x = $CountRegionX; y = $CountRegionY; width = $CountRegionWidth; height = $CountRegionHeight }
        representatives = $representatives
        obs_record_button = [ordered]@{ x = $ObsRecordButtonX; y = $ObsRecordButtonY }
    }
    timing_plan = [ordered]@{
        pre_roll_seconds = $PreRollSeconds
        scroll_seconds = $ScrollSeconds
        post_scroll_settle_seconds = $PostScrollSettleSeconds
        hover_seconds_each = $HoverSeconds
        result_tail_seconds = $ResultTailSeconds
        wheel_notches = $WheelNotches
        wheel_delta = $WheelDelta
    }
    count_check = [ordered]@{
        expected = 61
        method = if ($RequireCountOcr) { 'cropped_ocr_required' } else { 'cropped_ocr_optional_plus_manual_review' }
        screenshot = $null
        ocr_text = $null
        matched_expected = $null
        status = 'pending_checkpoint_review'
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
        hover_marks = @()
        result_tail_begin_mark = $null
        frame_end_mark = $null
        source_frame_begin = $null
        source_frame_end = $null
    }
    errors = @()
    next_required_steps = @(
        'Keep the raw MKV and external source immutable after OBS closes.',
        'Run ffprobe and Get-FileHash; extract frame-begin/frame-end from this same raw.',
        'Create runtime-manifest with the native count=61 and the complete 61 current VIVHITE_CARD IDs, not a source-code list.',
        'Create T19-tooltip-ocr for one current tooltip per route and bind all evidence refs; operator marks are not native action evidence.'
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
        # OBS/Windows can report a zero-length Matroska file until the muxer
        # flushes or closes it.  Creation of exactly one new media file in an
        # empty attempt directory is the reliable live-start signal here;
        # non-zero size is enforced after stop by Wait-AttemptMediaStable.
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
        } else {
            $stableSamples = 0
        }
        $previousLength = $length
        Start-Sleep -Milliseconds 350
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}

$recordingStarted = $false
$completed = $false
try {
    Set-WindowForeground -ProcessId $game.Id
    Start-Sleep -Milliseconds 800
    if ($FromMainMenu) {
        Invoke-MouseClick -X $EncyclopediaX -Y $EncyclopediaY
        Start-Sleep -Seconds 2
        Invoke-MouseClick -X $FilterX -Y $FilterY
        Start-Sleep -Seconds 1
    }

    if (-not $NoCheckpoint) {
        $checkpointPath = Join-Path $output 'checkpoint-before-mark.png'
        $saved = Save-Screenshot -Path $checkpointPath
        $descriptor = Get-OperatorFileDescriptor -Path $saved
        $marks.checkpoints += ,[ordered]@{
            purpose = 'staged_setup_card_library_count_checkpoint'
            descriptor = $descriptor
            review_status = 'operator_review_required'
            note = 'Confirm the white filter is selected, search is empty, all current filters are clear and native count reads 61 before recording.'
        }
        $countPath = Join-Path $output 'count-label-checkpoint.png'
        $countSaved = Save-Screenshot -Path $countPath -X $CountRegionX -Y $CountRegionY -Width $CountRegionWidth -Height $CountRegionHeight
        $countDescriptor = Get-OperatorFileDescriptor -Path $countSaved
        $marks.count_check.screenshot = $countDescriptor
        if ($RequireCountOcr) {
            try {
                $ocr = [string](Get-OcrText -Path $countSaved -Language 'zh-Hans')
                $marks.count_check.ocr_text = $ocr
                $matchesCount = $ocr -match '(?<!\d)61(?!\d)'
                $marks.count_check.matched_expected = [bool]$matchesCount
                if (-not $matchesCount) {
                    $marks.count_check.status = 'failed_ocr_expected_61_not_found'
                    throw "Count OCR did not contain the expected native count 61; OCR text was '$ocr'"
                }
                $marks.count_check.status = 'ocr_hint_passed_manual_review_required'
            }
            catch {
                if ($marks.count_check.status -eq 'pending_checkpoint_review') {
                    $marks.count_check.status = 'ocr_unavailable_manual_review_required'
                }
                if ($marks.count_check.status -eq 'failed_ocr_expected_61_not_found') { throw }
            }
        } else {
            $marks.count_check.status = 'manual_review_required'
        }
        Save-Marks
    } else {
        # A no-checkpoint run is still useful for timing rehearsal, but it
        # cannot establish the native count gate; preserve that distinction in
        # the handoff rather than leaving a misleading pending status.
        $marks.count_check.status = 'checkpoint_skipped_manual_review_required'
        Save-Marks
    }

    Set-WindowForeground -ProcessId $obs.Id
    Start-Sleep -Milliseconds 800
    $start = Get-OperatorMark
    $marks.recording.start_request = $start
    # Set the guard before the toggle input.  If the operator aborts during a
    # mouse-down/up sequence, catch/finally still attempts to stop OBS.
    $recordingStarted = $true
    Invoke-ObsRecordToggle -Process $obs -ExpectedAction start
    if (-not (Wait-ObsRecordState -Process $obs -ExpectedState recording)) {
        throw 'OBS UI Automation start did not reach the recording button state'
    }
    Start-Sleep -Milliseconds 500
    $startedMedia = Wait-AttemptMediaStarted -Directory $output
    if ($null -eq $startedMedia) {
        $recordingStarted = $false
        throw "OBS start was not confirmed: no non-empty MKV/MP4 appeared in $output"
    }
    if (-not $NoCheckpoint) {
        $obsRecordingPath = Join-Path $output 'obs-recording-confirmed.png'
        $obsRecordingSaved = Save-Screenshot -Path $obsRecordingPath
        $marks.checkpoints += ,[ordered]@{
            purpose = 'obs_recording_confirmed_after_start'
            descriptor = Get-OperatorFileDescriptor -Path $obsRecordingSaved
            review_status = 'operator_review_required'
        }
    }
    $marks.recording.media_started = Get-OperatorFileDescriptor -Path $startedMedia.FullName
    $marks.status = 'recording'
    Save-Marks

    Set-WindowForeground -ProcessId $game.Id
    Sleep-OperatorSeconds -Seconds $PreRollSeconds
    $marks.display.frame_begin_mark = Get-OperatorMark
    if (-not $NoCheckpoint) {
        $beginPath = Join-Path $output 'operator-frame-begin.png'
        $beginSaved = Save-Screenshot -Path $beginPath
        $marks.checkpoints += ,[ordered]@{
            purpose = 'post_mark_frame_begin_reference'
            descriptor = Get-OperatorFileDescriptor -Path $beginSaved
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
    Sleep-OperatorSeconds -Seconds $PostScrollSettleSeconds
    Save-Marks

    foreach ($card in $representatives) {
        Move-Mouse -X $card.x -Y $card.y
        $hoverBegin = Get-OperatorMark
        Sleep-OperatorSeconds -Seconds $HoverSeconds
        $hoverEnd = Get-OperatorMark
        $marks.display.hover_marks += ,[ordered]@{
            card_id_claimed = $card.id
            x = $card.x
            y = $card.y
            begin_mark = $hoverBegin
            end_mark = $hoverEnd
            native_action_evidence = $false
            runtime_title = $null
            note = 'Runtime title must be copied from the actual tooltip during post-capture review.'
        }
        Add-MarkEvent ([ordered]@{
            kind = 'ui_observation_mark'
            action = 'hover'
            claimed_card_id = $card.id
            x = $card.x
            y = $card.y
            begin_mark = $hoverBegin
            end_mark = $hoverEnd
            native_action_evidence = $false
        })
        Start-Sleep -Milliseconds 250
    }

    $marks.display.result_tail_begin_mark = Get-OperatorMark
    Sleep-OperatorSeconds -Seconds $ResultTailSeconds
    $marks.display.frame_end_mark = Get-OperatorMark
    if (-not $NoCheckpoint) {
        $endPath = Join-Path $output 'operator-frame-end.png'
        $endSaved = Save-Screenshot -Path $endPath
        $marks.checkpoints += ,[ordered]@{
            purpose = 'pre_stop_frame_end_reference'
            descriptor = Get-OperatorFileDescriptor -Path $endSaved
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
    if (-not (Wait-AttemptMediaStable -Media $startedMedia)) {
        throw "OBS stop was not confirmed: media did not become stable within the timeout: $($startedMedia.FullName)"
    }
    if (-not $NoCheckpoint) {
        $obsStoppedPath = Join-Path $output 'obs-stopped-confirmed.png'
        $obsStoppedSaved = Save-Screenshot -Path $obsStoppedPath
        $marks.checkpoints += ,[ordered]@{
            purpose = 'obs_stopped_confirmed_after_stop'
            descriptor = Get-OperatorFileDescriptor -Path $obsStoppedSaved
            review_status = 'operator_review_required'
        }
    }
    $marks.recording.media_stopped = Get-OperatorFileDescriptor -Path $startedMedia.FullName
    $marks.status = 'operator_marks_complete_media_review_pending'
    Save-Marks
    Complete-OperatorMarks -PartialPath $partialPath -FinalPath $finalPath
    $completed = $true
    Write-Output "T19 operator marks written: $finalPath"
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
    if (-not $completed) { Save-Marks }
}
