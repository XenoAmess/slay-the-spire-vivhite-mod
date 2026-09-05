[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [int]$GameProcessId = 0,
    [int]$ObsProcessId = 0,
    [string]$RunId = "run-20260903T0012-director-v2-a1",
    [string]$AttemptId = "",

    # These coordinates are deliberately parameters.  Reward cards and map
    # nodes move with the current 1920x1080 map payload; do not assume that a
    # coordinate from an earlier attempt is still a reachable node.
    [ValidateRange(0, 1920)][int]$RewardCardX = 960,
    [ValidateRange(0, 1080)][int]$RewardCardY = 600,
    [ValidateRange(0, 1920)][int]$SkipX = 1720,
    [ValidateRange(0, 1080)][int]$SkipY = 820,
    [ValidateRange(0, 1920)][int]$MapNodeX = 1098,
    [ValidateRange(0, 1080)][int]$MapNodeY = 529,
    [string]$RewardCardLabel = "offered_vivhite_reward_card",
    [string]$MapNodeLabel = "reachable_map_node",
    [string]$RewardCardId = "",
    [string]$MapNodeId = "",

    [ValidateRange(1.5, 4.0)][double]$PreRollSeconds = 2.0,
    [ValidateRange(1.5, 3.0)][double]$RewardHoverSeconds = 1.8,
    [ValidateRange(0.5, 8.0)][double]$RewardSettlementSeconds = 2.4,
    [ValidateRange(0.3, 3.0)][double]$SkipHoverSeconds = 0.8,
    [ValidateRange(0.5, 5.0)][double]$MapSettleSeconds = 1.8,
    [ValidateRange(1.5, 3.0)][double]$MapNodeHoverSeconds = 1.8,
    [ValidateRange(0.2, 8.0)][double]$NodeTransitionSeconds = 1.2,
    [ValidateRange(2.0, 6.0)][double]$ResultHoldSeconds = 3.2,
    [ValidateRange(20, 500)][int]$ClickHoldMilliseconds = 90,
    [ValidateRange(0.1, 5.0)][double]$ObsStartSettleSeconds = 0.9,
    [ValidateRange(0.1, 5.0)][double]$ObsStopSettleSeconds = 0.8,
    [ValidateRange(1, 30)][int]$FileCloseTimeoutSeconds = 8,

    [ValidateRange(0, 1920)][int]$ObsControlX = 1260,
    [ValidateRange(0, 1080)][int]$ObsControlY = 657,
    [ValidateRange(0, 1920)][int]$NeutralCursorX = 1800,
    [ValidateRange(0, 1080)][int]$NeutralCursorY = 500
)

<#
.SYNOPSIS
    Records one uninterrupted T07 reward-to-map take.

.DESCRIPTION
    This helper is intentionally a single-process input sequence.  It starts
    an already-configured OBS recording, keeps the game in the foreground, and
    performs only game-UI hover/click operations:

      clean reward page -> hover/click the actual offered card -> wait for the
      reward result -> open the map through the game's Skip/map control ->
      hover/click one pre-verified reachable node -> hold the resulting scene.

    There is no OCR, screenshot, console, API/Brain action, pause, or mid-take
    reconfiguration.  Coordinates must be checked against the current frame
    before invoking the script.  When known, pass the exact current
    -RewardCardId (`VIVHITE_CARD_*`) and -MapNodeId for the pre-verified
    payload; the script records them but does not infer them.  The generated
    operator-marks JSON contains UTC and monotonic timestamps for handoff; a
    partial checkpoint and append-only NDJSON event log are updated after each
    mark so a process interruption can be resumed without guessing.  These
    files are not native game receipts and must not be promoted to
    action_evidence_v2 by themselves.

    OBS must be idle before invocation and already configured to write MKV to
    OutputDirectory.  The output directory is never overwritten when it
    already contains an MKV, operator-marks file, or event log.
    After the stop settle window the helper waits for the new MKV, records its
    byte count/SHA-256, and fails the handoff if OBS did not write under the
    requested directory.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$modulePath = Join-Path $PSScriptRoot "..\..\test\GameTest.psm1"
Import-Module $modulePath -ErrorAction Stop

$resolvedOutput = [IO.Path]::GetFullPath($OutputDirectory)
if (-not (Test-Path -LiteralPath $resolvedOutput -PathType Container)) {
    New-Item -ItemType Directory -Force -Path $resolvedOutput | Out-Null
}
$existingMedia = @(Get-ChildItem -LiteralPath $resolvedOutput -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -match "(?i)^\.(mkv|mp4)$" })
if ($existingMedia.Count -gt 0) {
    throw "OutputDirectory already contains media; use a new attempt directory: $resolvedOutput"
}
$existingMarks = @(Get-ChildItem -LiteralPath $resolvedOutput -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match "(?i)^operator-marks(?:-|\.)" })
if ($existingMarks.Count -gt 0) {
    throw "OutputDirectory already contains operator marks; use a new attempt directory: $resolvedOutput"
}
$existingEvents = Join-Path $resolvedOutput "operator-events.ndjson"
if (Test-Path -LiteralPath $existingEvents -PathType Leaf) {
    throw "OutputDirectory already contains operator events; use a new attempt directory: $resolvedOutput"
}

if ([string]::IsNullOrWhiteSpace($AttemptId)) {
    $AttemptId = "a-" + [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffZ")
}
if (-not [string]::IsNullOrWhiteSpace($RewardCardId) -and $RewardCardId -notmatch "^VIVHITE_CARD_[A-Z0-9_]+$") {
    throw "RewardCardId must be the exact current VIVHITE_CARD_* identifier when supplied"
}
if (-not [string]::IsNullOrWhiteSpace($MapNodeId) -and $MapNodeId -match "\s") {
    throw "MapNodeId must be a portable map id without whitespace when supplied"
}

function Wait-Seconds {
    param([Parameter(Mandatory = $true)][double]$Seconds)
    if ($Seconds -le 0) { return }
    $milliseconds = [int][Math]::Round($Seconds * 1000.0)
    if ($milliseconds -gt 0) {
        Start-Sleep -Milliseconds $milliseconds
    }
}

function Get-ProcessIdentity {
    param([Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process)
    $processId = $null
    try {
        $processId = [int]$Process.Id
    }
    catch {
        $processId = $null
    }
    $processName = $null
    try {
        $processName = [string]$Process.ProcessName
    }
    catch {
        $processName = $null
    }
    $startedUtc = $null
    try {
        $startedUtc = $Process.StartTime.ToUniversalTime().ToString("o")
    }
    catch {
        $startedUtc = $null
    }
    $imagePath = $null
    try {
        $imagePath = $Process.MainModule.FileName
    }
    catch {
        $imagePath = $null
    }
    return [ordered]@{
        pid = $processId
        name = $processName
        started_at_utc = $startedUtc
        image_path = $imagePath
    }
}

function Resolve-RunningProcess {
    param(
        [Parameter(Mandatory = $true)][int]$Id,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($Id -gt 0) {
        return Get-Process -Id $Id -ErrorAction Stop
    }
    $candidate = Get-Process -Name $Name -ErrorAction SilentlyContinue |
        Sort-Object Id |
        Select-Object -First 1
    if ($null -eq $candidate) {
        throw "running process not found: $Name"
    }
    return $candidate
}

$gameProcess = Resolve-RunningProcess -Id $GameProcessId -Name "SlayTheSpire2"
$obsProcess = Resolve-RunningProcess -Id $ObsProcessId -Name "obs64"
$GameProcessId = [int]$gameProcess.Id
$ObsProcessId = [int]$obsProcess.Id

$script:baseTick = [Diagnostics.Stopwatch]::GetTimestamp()
$script:events = New-Object "System.Collections.Generic.List[object]"
$script:recordingStarted = $false
$script:recordingStopped = $false
$script:marksFile = Join-Path $resolvedOutput "operator-marks.json"
$script:partialMarksFile = Join-Path $resolvedOutput "operator-marks.partial.json"
$script:eventFile = Join-Path $resolvedOutput "operator-events.ndjson"
$script:checkpointWriteError = $null
$script:failureMessage = $null
$script:stopFailureMessage = $null
$script:recordingStartUtc = $null
$script:sourceFile = $null
$script:sourceBytes = $null
$script:sourceSha256 = $null
$script:gameIdentity = Get-ProcessIdentity -Process $gameProcess
$script:obsIdentity = Get-ProcessIdentity -Process $obsProcess

function Add-Mark {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [hashtable]$Details = $null
    )
    $tick = [Diagnostics.Stopwatch]::GetTimestamp()
    $utc = [DateTimeOffset]::UtcNow
    $elapsed = ($tick - $script:baseTick) / [double][Diagnostics.Stopwatch]::Frequency
    $entry = [ordered]@{
        name = $Name
        utc = $utc.ToString("o")
        monotonic_ticks = [int64]$tick
        elapsed_seconds = [Math]::Round([double]$elapsed, 6)
    }
    if ($null -ne $Details) {
        foreach ($key in $Details.Keys) {
            $entry[[string]$key] = $Details[$key]
        }
    }
    $script:events.Add([pscustomobject]$entry)
    try {
        $eventJson = $entry | ConvertTo-Json -Depth 8 -Compress
        [IO.File]::AppendAllText($script:eventFile, $eventJson + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    }
    catch {
        $script:checkpointWriteError = $_.Exception.Message
    }
    Write-PartialCheckpoint
    return $entry
}

function Focus-Game {
    Set-WindowForeground -ProcessId $GameProcessId
    Wait-Seconds -Seconds 0.12
}

function Focus-Obs {
    Set-WindowForeground -ProcessId $ObsProcessId
    Wait-Seconds -Seconds 0.25
}

function Move-CursorTracked {
    param([Parameter(Mandatory = $true)][int]$X, [Parameter(Mandatory = $true)][int]$Y)
    [GameInputNative]::SetCursorPos($X, $Y) | Out-Null
}

function Hover-Tracked {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$X,
        [Parameter(Mandatory = $true)][int]$Y,
        [Parameter(Mandatory = $true)][double]$Seconds
    )
    Add-Mark -Name "$Name.hover_begin" -Details @{ x = $X; y = $Y } | Out-Null
    Move-CursorTracked -X $X -Y $Y
    Wait-Seconds -Seconds $Seconds
    Add-Mark -Name "$Name.hover_end" -Details @{ x = $X; y = $Y } | Out-Null
}

function Click-Tracked {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$X,
        [Parameter(Mandatory = $true)][int]$Y
    )
    Move-CursorTracked -X $X -Y $Y
    Wait-Seconds -Seconds 0.06
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    Add-Mark -Name "$Name.pointer_down" -Details @{ x = $X; y = $Y } | Out-Null
    Start-Sleep -Milliseconds $ClickHoldMilliseconds
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    Add-Mark -Name "$Name.pointer_up" -Details @{ x = $X; y = $Y } | Out-Null
}

function Find-NewRecordingFile {
    if ($null -eq $script:recordingStartUtc) { return $null }
    $deadline = [DateTime]::UtcNow.AddSeconds($FileCloseTimeoutSeconds)
    do {
        $candidates = @(Get-ChildItem -LiteralPath $resolvedOutput -File -Filter '*.mkv' -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTimeUtc -ge $script:recordingStartUtc.AddSeconds(-2) } |
            Sort-Object LastWriteTimeUtc -Descending)
        if ($candidates.Count -gt 0) { return $candidates[0] }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

function Start-ObsRecording {
    Focus-Obs
    $script:recordingStartUtc = [DateTime]::UtcNow
    Add-Mark -Name "recording.start_request" -Details @{ x = $ObsControlX; y = $ObsControlY } | Out-Null
    Click-Tracked -Name "obs_record_start" -X $ObsControlX -Y $ObsControlY
    $script:recordingStarted = $true
    Add-Mark -Name "recording.start_click_returned" | Out-Null
    Wait-Seconds -Seconds $ObsStartSettleSeconds
    Focus-Game
}

function Stop-ObsRecording {
    if (-not $script:recordingStarted -or $script:recordingStopped) { return }
    Focus-Obs
    Add-Mark -Name "recording.stop_request" -Details @{ x = $ObsControlX; y = $ObsControlY } | Out-Null
    Click-Tracked -Name "obs_record_stop" -X $ObsControlX -Y $ObsControlY
    Wait-Seconds -Seconds $ObsStopSettleSeconds
    $script:recordingStopped = $true
    Add-Mark -Name "recording.stop_click_returned" | Out-Null
    $file = Find-NewRecordingFile
    if ($null -eq $file) {
        $script:stopFailureMessage = "OBS stopped but no new MKV appeared under $resolvedOutput"
        Add-Mark -Name "recording.file_missing" -Details @{ directory = $resolvedOutput } | Out-Null
        return
    }
    $script:sourceFile = $file.FullName
    $script:sourceBytes = [int64]$file.Length
    $script:sourceSha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    Add-Mark -Name "recording.file_closed" -Details @{
        path = $file.FullName
        bytes = $script:sourceBytes
        sha256 = $script:sourceSha256
    } | Out-Null
}

function Get-OperatorMarksPayload {
    $payload = [ordered]@{
        schema_version = 1
        kind = "vivhite_promo_t07_operator_marks"
        script = "tools/promo/v2/run_t07_capture.ps1"
        script_version = "2026-09-04.single-process.1"
        generated_at_utc = [DateTimeOffset]::UtcNow.ToString("o")
        status = if ($null -ne $script:failureMessage -or $null -ne $script:stopFailureMessage) {
            "operator_sequence_failed"
        } elseif ($script:recordingStopped) {
            "completed_operator_sequence"
        } elseif ($script:recordingStarted) {
            "recording_in_progress"
        } else {
            "prepared"
        }
        run_id = $RunId
        take_id = "T07"
        attempt_id = $AttemptId
        output_directory = $resolvedOutput
        partial_marks = $script:partialMarksFile
        event_log = $script:eventFile
        director_contract = [ordered]@{
            recipe = "tools/promo/v2/T07_CAPTURE_RECIPE.md"
            storyboard = "tools/promo/v2/storyboard.json"
            single_continuous_source = $true
            playback_speed = 1
            setup_mode = "natural_navigation"
            required_owner_span_seconds = 20
            owner_subshots = @(
                [ordered]@{ subshot_id = "S04-04-card-reward"; timeline_seconds = 8 }
                [ordered]@{ subshot_id = "S04-05-map-route"; timeline_seconds = 12 }
            )
            post_result_seconds = [ordered]@{ minimum = 3; maximum = 4 }
            forbidden_during_sequence = @(
                "console", "Brain/API", "pause menu", "screenshot/OCR",
                "OBS/game window switch", "system cursor", "loading in display span"
            )
        }
        stopwatch_frequency = [int64][Diagnostics.Stopwatch]::Frequency
        game_process = $script:gameIdentity
        obs_process = $script:obsIdentity
        coordinates = [ordered]@{
            reward_card = [ordered]@{ x = $RewardCardX; y = $RewardCardY; label = $RewardCardLabel; target_id = $RewardCardId }
            reward_skip_or_map_button = [ordered]@{ x = $SkipX; y = $SkipY }
            map_node = [ordered]@{ x = $MapNodeX; y = $MapNodeY; label = $MapNodeLabel; target_id = $MapNodeId }
            obs_record_control = [ordered]@{ x = $ObsControlX; y = $ObsControlY }
        }
        timing_parameters_seconds = [ordered]@{
            pre_roll = $PreRollSeconds
            reward_hover = $RewardHoverSeconds
            reward_settlement = $RewardSettlementSeconds
            skip_hover = $SkipHoverSeconds
            map_settle = $MapSettleSeconds
            map_node_hover = $MapNodeHoverSeconds
            node_transition = $NodeTransitionSeconds
            result_hold = $ResultHoldSeconds
            obs_start_settle = $ObsStartSettleSeconds
            obs_stop_settle = $ObsStopSettleSeconds
            file_close_timeout_seconds = $FileCloseTimeoutSeconds
        }
        recording = [ordered]@{
            started = $script:recordingStarted
            stopped = $script:recordingStopped
            source_file = $script:sourceFile
            source_bytes = $script:sourceBytes
            source_sha256 = $script:sourceSha256
            source_policy = "single_uninterrupted_mkv; operator marks are not native game receipts"
        }
        error = $script:failureMessage
        stop_error = $script:stopFailureMessage
        checkpoint_write_error = $script:checkpointWriteError
        # Windows PowerShell 5.1 can throw "Argument types do not match" when
        # a generic List is wrapped directly in @(...).  Materialize it
        # through the pipeline so handoff JSON is written reliably.
        events = @($script:events | ForEach-Object { $_ })
    }
    return $payload
}

function Write-PartialCheckpoint {
    # The checkpoint is deliberately best-effort: a slow filesystem must not
    # interrupt the real pointer sequence.  Every completed mark is also
    # appended to the NDJSON event log below, so a hard process loss still
    # leaves a monotonic operator timeline.
    $temporary = "$($script:partialMarksFile).tmp.$PID"
    try {
        $payload = Get-OperatorMarksPayload
        $json = $payload | ConvertTo-Json -Depth 12
        [IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $script:partialMarksFile -Force | Out-Null
    }
    catch {
        $script:checkpointWriteError = $_.Exception.Message
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }
}

function Save-OperatorMarks {
    $payload = Get-OperatorMarksPayload
    $json = $payload | ConvertTo-Json -Depth 12
    $temporary = "$($script:marksFile).tmp.$PID"
    try {
        [IO.File]::WriteAllText($temporary, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $script:marksFile -Force | Out-Null
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }
    return $payload
}

$marksPayload = $null
try {
    # All preparation (coordinate measurement, output directory setup and
    # process resolution) is complete before this point.  Once the start mark
    # is issued there are no screenshots, OCR calls, console commands, or
    # window changes until the stop mark in finally.
    Focus-Game
    Add-Mark -Name "formal_sequence.ready" | Out-Null
    Start-ObsRecording

    Add-Mark -Name "formal_sequence.clean_preroll_begin" | Out-Null
    Wait-Seconds -Seconds $PreRollSeconds
    Add-Mark -Name "formal_sequence.clean_preroll_end" | Out-Null

    Hover-Tracked -Name "reward_card" -X $RewardCardX -Y $RewardCardY -Seconds $RewardHoverSeconds
    Click-Tracked -Name "choose_reward_card" -X $RewardCardX -Y $RewardCardY
    Add-Mark -Name "choose_reward_card.settlement_wait_begin" | Out-Null
    Wait-Seconds -Seconds $RewardSettlementSeconds
    Add-Mark -Name "choose_reward_card.settlement_wait_end" | Out-Null

    Hover-Tracked -Name "reward_skip_or_map_button" -X $SkipX -Y $SkipY -Seconds $SkipHoverSeconds
    Click-Tracked -Name "open_map" -X $SkipX -Y $SkipY
    Add-Mark -Name "open_map.settlement_wait_begin" | Out-Null
    Wait-Seconds -Seconds $MapSettleSeconds
    Add-Mark -Name "open_map.settlement_wait_end" | Out-Null

    Hover-Tracked -Name "map_node" -X $MapNodeX -Y $MapNodeY -Seconds $MapNodeHoverSeconds
    Click-Tracked -Name "choose_map_node" -X $MapNodeX -Y $MapNodeY
    Add-Mark -Name "choose_map_node.settlement_wait_begin" | Out-Null
    Wait-Seconds -Seconds $NodeTransitionSeconds
    Add-Mark -Name "choose_map_node.settlement_wait_end" | Out-Null

    Move-CursorTracked -X $NeutralCursorX -Y $NeutralCursorY
    Add-Mark -Name "formal_sequence.clean_result_hold_begin" | Out-Null
    Wait-Seconds -Seconds $ResultHoldSeconds
    Add-Mark -Name "formal_sequence.clean_result_hold_end" | Out-Null
}
catch {
    $script:failureMessage = $_.Exception.Message
    try {
        Add-Mark -Name "formal_sequence.error" -Details @{ message = $script:failureMessage } | Out-Null
    }
    catch {
        # Preserve the original failure if the mark writer itself is unable
        # to append an event.
    }
}
finally {
    try {
        Stop-ObsRecording
    }
    catch {
        $script:stopFailureMessage = $_.Exception.Message
        try {
            Add-Mark -Name "recording.stop_error" -Details @{ message = $script:stopFailureMessage } | Out-Null
        }
        catch {
        }
    }
    try {
        $marksPayload = Save-OperatorMarks
    }
    catch {
        $script:failureMessage = if ($null -eq $script:failureMessage) { $_.Exception.Message } else { $script:failureMessage }
    }
}

$result = [ordered]@{
    status = if ($null -eq $script:failureMessage -and $null -eq $script:stopFailureMessage) { "completed" } else { "failed" }
    run_id = $RunId
    take_id = "T07"
    attempt_id = $AttemptId
    output_directory = $resolvedOutput
    operator_marks = $script:marksFile
    partial_marks = $script:partialMarksFile
    event_log = $script:eventFile
    recording_started = $script:recordingStarted
    recording_stopped = $script:recordingStopped
    source_file = $script:sourceFile
    source_bytes = $script:sourceBytes
    source_sha256 = $script:sourceSha256
    error = $script:failureMessage
    stop_error = $script:stopFailureMessage
    checkpoint_write_error = $script:checkpointWriteError
    event_count = $script:events.Count
}
$result | ConvertTo-Json -Depth 8 -Compress
if ($result.status -ne "completed") {
    exit 1
}
