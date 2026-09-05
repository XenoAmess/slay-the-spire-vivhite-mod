#requires -Version 5.1
<#!
.SYNOPSIS
    Capture-time evidence helper for a single Vivhite promo take.

.DESCRIPTION
    This file is intentionally a dot-source helper, not a recorder and not an
    action-receipt generator.  A T16/T18 runner dot-sources it in the same
    PowerShell process that performs the real GameTest mouse input.  The helper
    records operator marks immediately after the corresponding native pointer
    call, captures optional full-screen observations, snapshots process
    identity, copies only the append-only game.log window, and leaves an
    explicitly non-production raw-frame mapping for later human verification.

    It never calls /action, the Brain, the console, or an OBS/game control API.
    It never infers a state transition from pixels or from game.log and it
    never writes a strict vivhite-promo-action-evidence sidecar.  A bundle is
    therefore useful for an interruption hand-off, but it is not itself a
    production receipt.  The later archive step must inspect the closed raw
    source and fill a genuine state.before/action.receipt/state.after chain.

.NOTES
    Use a fresh attempt directory for every invocation.  Existing final or
    partial manifests are rejected.  All helper-owned JSON/event/log files are
    written through a temporary sibling and an atomic rename; an interrupted
    run remains recoverable from the partial manifest and immutable event files.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$script:PromoEvidenceSchemaVersion = 1
$script:PromoEvidenceKind = 'vivhite_promo_capture_evidence_bundle'
$script:PromoEvidenceEventKind = 'vivhite_promo_capture_event'
$script:PromoEvidenceFps = 60
$script:PromoEvidenceIdRegex = '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'

function Test-PromoEvidencePortableId {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Value)

    return (-not [string]::IsNullOrWhiteSpace($Value) -and
        $Value -match $script:PromoEvidenceIdRegex -and
        $Value.IndexOfAny([char[]]"`0`r`n") -lt 0)
}

function Assert-PromoEvidencePortableId {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not (Test-PromoEvidencePortableId -Value $Value)) {
        throw "$Name must be a non-empty portable identifier (letters, digits, '.', '_' or '-')"
    }
}

function Get-PromoEvidenceUtc {
    return [DateTime]::UtcNow.ToString('o')
}

function Get-PromoEvidenceFullPath {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or $Path.IndexOfAny([char[]]"`0`r`n") -ge 0) {
        throw 'Evidence path must be non-empty and contain no NUL/newline characters.'
    }
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-PromoEvidenceNoReparse {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing a reparse-point evidence path: $Path"
        }
    }
}

function Assert-PromoEvidenceUnderRoot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $rootFull = (Get-PromoEvidenceFullPath -Path $Root).TrimEnd('\') + '\'
    $pathFull = Get-PromoEvidenceFullPath -Path $Path
    if (-not $pathFull.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Name must remain under the evidence bundle root: $pathFull"
    }
    Assert-PromoEvidenceNoReparse -Path $pathFull
    return $pathFull
}

function Get-PromoEvidenceRelativePath {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $rootFull = (Get-PromoEvidenceFullPath -Path $Root).TrimEnd('\') + '\'
    $pathFull = Get-PromoEvidenceFullPath -Path $Path
    if (-not $pathFull.StartsWith($rootFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path is outside the evidence root: $pathFull"
    }
    return $pathFull.Substring($rootFull.Length).Replace('\', '/')
}

function Write-PromoEvidenceAtomicBytes {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [switch]$RefuseExisting
    )

    $destinationFull = Get-PromoEvidenceFullPath -Path $Destination
    Assert-PromoEvidenceNoReparse -Path $destinationFull
    $parent = Split-Path -Parent $destinationFull
    if (-not (Test-Path -LiteralPath $parent)) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    if ($RefuseExisting -and (Test-Path -LiteralPath $destinationFull)) {
        throw "Refusing to overwrite existing evidence artifact: $destinationFull"
    }

    $tmp = "$destinationFull.tmp.$PID.$([Guid]::NewGuid().ToString('N'))"
    try {
        [IO.File]::WriteAllBytes($tmp, $Bytes)
        if ($RefuseExisting -and (Test-Path -LiteralPath $destinationFull)) {
            throw "Evidence destination appeared during write: $destinationFull"
        }
        if ($RefuseExisting) {
            # .NET File.Move is the no-replace primitive on Windows PowerShell;
            # Move-Item -Force would leave a race that could overwrite an
            # immutable event if another writer wins between the checks.
            [IO.File]::Move($tmp, $destinationFull)
        }
        else {
            Move-Item -LiteralPath $tmp -Destination $destinationFull -Force | Out-Null
        }
    }
    finally {
        if (Test-Path -LiteralPath $tmp) {
            Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
        }
    }
    return $destinationFull
}

function ConvertTo-PromoEvidenceUtf8Bytes {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Text)

    $encoding = New-Object System.Text.UTF8Encoding($false)
    return $encoding.GetBytes($Text)
}

function Write-PromoEvidenceAtomicJson {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][object]$Value,
        [switch]$RefuseExisting
    )

    $json = $Value | ConvertTo-Json -Depth 40
    Write-PromoEvidenceAtomicBytes -Destination $Destination `
        -Bytes (ConvertTo-PromoEvidenceUtf8Bytes -Text $json) `
        -RefuseExisting:$RefuseExisting
}

function Get-PromoEvidenceSha256 {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Evidence file is missing: $Path"
    }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Get-PromoEvidenceDescriptor {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$MediaType
    )

    $full = Assert-PromoEvidenceUnderRoot -Root $Root -Path $Path -Name 'artifact path'
    $item = Get-Item -LiteralPath $full -Force
    if (-not $item.PSIsContainer -and $item.Length -lt 0) {
        throw "Invalid evidence file length: $full"
    }
    return [ordered]@{
        path = Get-PromoEvidenceRelativePath -Root $Root -Path $full
        bytes = [int64]$item.Length
        sha256 = Get-PromoEvidenceSha256 -Path $full
        media_type = $MediaType
    }
}

function Get-PromoEvidenceProcessIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ProcessName,
        [int]$ProcessId = 0,
        [Parameter(Mandatory = $true)][string]$Role
    )

    $normalizedName = $ProcessName.Trim()
    if ($normalizedName.EndsWith('.exe', [StringComparison]::OrdinalIgnoreCase)) {
        $normalizedName = $normalizedName.Substring(0, $normalizedName.Length - 4)
    }
    if ([string]::IsNullOrWhiteSpace($normalizedName)) {
        throw "$Role process name is empty"
    }

    if ($ProcessId -gt 0) {
        $process = Get-Process -Id $ProcessId -ErrorAction Stop
        if (-not [string]::Equals($process.ProcessName, $normalizedName, [StringComparison]::OrdinalIgnoreCase)) {
            throw "$Role process $ProcessId is '$($process.ProcessName)', expected '$normalizedName'"
        }
    }
    else {
        $matches = @(Get-Process -Name $normalizedName -ErrorAction SilentlyContinue)
        if ($matches.Count -ne 1) {
            throw "Expected exactly one $Role process '$normalizedName'; found $($matches.Count). Pass an explicit process id."
        }
        $process = $matches[0]
    }
    if ($process.MainWindowHandle -eq [IntPtr]::Zero) {
        throw "$Role process $($process.Id) has no main window; refusing to create a capture bundle"
    }

    $startUtc = $null
    try { $startUtc = $process.StartTime.ToUniversalTime().ToString('o') } catch { $startUtc = $null }
    if ([string]::IsNullOrWhiteSpace($startUtc)) {
        throw "Could not read $Role process start time for PID $($process.Id)"
    }
    $executable = $null
    try { $executable = $process.Path } catch { $executable = $null }
    if ([string]::IsNullOrWhiteSpace($executable)) {
        throw "Could not read $Role executable path for PID $($process.Id)"
    }
    $exeName = [string]$process.ProcessName
    if (-not $exeName.EndsWith('.exe', [StringComparison]::OrdinalIgnoreCase)) {
        $exeName = "$exeName.exe"
    }
    # The strict v2 capture_identity grammar is a portable identifier.  Keep
    # the human-readable executable/PID/start-time composition, but replace
    # ISO-8601 time colons and use hyphens as separators.  A colon-delimited
    # value (for example `SlayTheSpire2.exe:1234:2026-09-04T12:00:00Z`) is
    # useful in ad-hoc logs but cannot be loaded by action_evidence_v2.py.
    $identityStart = $startUtc -replace ':', '-'
    $portableIdentity = "$exeName-$($process.Id)-$identityStart"
    return [ordered]@{
        pid = [int]$process.Id
        process_name = $exeName
        executable = [string]$executable
        started_utc = $startUtc
        identity = $portableIdentity
    }
}

function Get-PromoEvidencePrefixSha256 {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][long]$Length
    )

    if ($Length -lt 0) { throw 'Prefix length cannot be negative' }
    $hash = [Security.Cryptography.SHA256]::Create()
    $stream = $null
    try {
        $stream = New-Object IO.FileStream(
            $Path,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
        )
        if ($stream.Length -lt $Length) {
            throw "File is shorter than the requested prefix: $Path"
        }
        $remaining = $Length
        $buffer = New-Object byte[] 1048576
        while ($remaining -gt 0) {
            $want = [int][Math]::Min($buffer.Length, $remaining)
            $read = $stream.Read($buffer, 0, $want)
            if ($read -le 0) { throw "Unexpected EOF while hashing $Path" }
            $hash.TransformBlock($buffer, 0, $read, $buffer, 0) | Out-Null
            $remaining -= $read
        }
        $hash.TransformFinalBlock((New-Object byte[] 0), 0, 0) | Out-Null
        return ([BitConverter]::ToString($hash.Hash) -replace '-', '').ToUpperInvariant()
    }
    finally {
        if ($null -ne $stream) { $stream.Dispose() }
        $hash.Dispose()
    }
}

function Copy-PromoEvidenceLogWindow {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][long]$StartOffset,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "Game log disappeared before finalization: $SourcePath"
    }
    $source = $null
    $memory = New-Object IO.MemoryStream
    try {
        $source = New-Object IO.FileStream(
            $SourcePath,
            [IO.FileMode]::Open,
            [IO.FileAccess]::Read,
            ([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
        )
        if ($source.Length -lt $StartOffset) {
            throw "Game log was truncated/rotated during capture: $SourcePath"
        }
        $source.Seek($StartOffset, [IO.SeekOrigin]::Begin) | Out-Null
        $source.CopyTo($memory)
        Write-PromoEvidenceAtomicBytes -Destination $Destination -Bytes $memory.ToArray() -RefuseExisting | Out-Null
    }
    finally {
        if ($null -ne $source) { $source.Dispose() }
        $memory.Dispose()
    }
}

function Write-PromoEvidenceCheckpoint {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object]$Session)

    if ($null -eq $Session -or $null -eq $Session.Document) {
        throw 'Invalid promo evidence session object'
    }
    $Session.Document.updated_utc = Get-PromoEvidenceUtc
    Write-PromoEvidenceAtomicJson -Destination $Session.PartialPath -Value $Session.Document | Out-Null
}

function New-PromoCaptureEvidenceSession {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$OutputDirectory,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$SessionId,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$RunId,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$GameRunId,
        [Parameter(Mandatory = $true)][ValidatePattern('^T[0-9]+$')][string]$TakeId,
        [Parameter(Mandatory = $true)][ValidatePattern('^a[0-9]+$')][string]$AttemptId,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$SourceVideoArtifactId,
        [Parameter(Mandatory = $true)][string]$RawArtifactPath,
        [Parameter(Mandatory = $true)][string]$GameLogPath,
        [string]$GameProcessName = 'SlayTheSpire2',
        [string]$ObsProcessName = 'obs64',
        [int]$GameProcessId = 0,
        [int]$ObsProcessId = 0
    )

    foreach ($pair in @(
        @('SessionId', $SessionId), @('RunId', $RunId), @('GameRunId', $GameRunId),
        @('TakeId', $TakeId), @('AttemptId', $AttemptId), @('SourceVideoArtifactId', $SourceVideoArtifactId)
    )) {
        Assert-PromoEvidencePortableId -Value ([string]$pair[1]) -Name ([string]$pair[0])
    }

    $root = Get-PromoEvidenceFullPath -Path $OutputDirectory
    if (Test-Path -LiteralPath $root) {
        Assert-PromoEvidenceNoReparse -Path $root
        $existing = @(Get-ChildItem -LiteralPath $root -Force -ErrorAction SilentlyContinue)
        if ($existing.Count -gt 0) {
            throw "Evidence output must be a new empty attempt directory: $root"
        }
    }
    else {
        New-Item -ItemType Directory -Force -Path $root | Out-Null
    }
    foreach ($subdir in @('events', 'screenshots', 'logs')) {
        New-Item -ItemType Directory -Force -Path (Join-Path $root $subdir) | Out-Null
    }
    $partial = Join-Path $root 'capture-evidence.partial.json'
    $final = Join-Path $root 'capture-evidence.json'
    if (Test-Path -LiteralPath $partial -or Test-Path -LiteralPath $final) {
        throw "Evidence manifest already exists; use a new attempt directory: $root"
    }

    $logFull = Get-PromoEvidenceFullPath -Path $GameLogPath
    $rawFull = Get-PromoEvidenceFullPath -Path $RawArtifactPath
    if (-not (Test-Path -LiteralPath $logFull -PathType Leaf)) {
        throw "Game log does not exist at capture start: $logFull"
    }
    Assert-PromoEvidenceNoReparse -Path $logFull
    $logItem = Get-Item -LiteralPath $logFull -Force
    $logLength = [int64]$logItem.Length
    $logPrefixSha = Get-PromoEvidencePrefixSha256 -Path $logFull -Length $logLength

    $gameIdentity = Get-PromoEvidenceProcessIdentity -ProcessName $GameProcessName -ProcessId $GameProcessId -Role 'game'
    $obsIdentity = Get-PromoEvidenceProcessIdentity -ProcessName $ObsProcessName -ProcessId $ObsProcessId -Role 'OBS'
    if ([int]$gameIdentity.pid -eq [int]$obsIdentity.pid) {
        throw 'Game and OBS process identities must be distinct'
    }

    $clockStart = [Diagnostics.Stopwatch]::GetTimestamp()
    $frequency = [long][Diagnostics.Stopwatch]::Frequency
    $marks = New-Object System.Collections.ArrayList
    $screenshots = New-Object System.Collections.ArrayList
    $events = New-Object System.Collections.ArrayList
    $document = [ordered]@{
        schema_version = $script:PromoEvidenceSchemaVersion
        kind = $script:PromoEvidenceKind
        status = 'collecting'
        production_eligible = $false
        strict_sidecar_emitted = $false
        manual_review_required = $true
        created_utc = Get-PromoEvidenceUtc
        updated_utc = Get-PromoEvidenceUtc
        session_id = $SessionId
        run_id = $RunId
        game_run_id = $GameRunId
        take_id = $TakeId
        attempt_id = $AttemptId
        source_video_artifact_id = $SourceVideoArtifactId
        capture_identity = [ordered]@{
            session_id = $SessionId
            game_run_id = $GameRunId
            run_id = $RunId
            take_id = $TakeId
            attempt_id = $AttemptId
            source_video_artifact_id = $SourceVideoArtifactId
        }
        process_identity = [ordered]@{
            game = $gameIdentity
            obs = $obsIdentity
        }
        clock = [ordered]@{
            start_tick = [long]$clockStart
            stopwatch_frequency = $frequency
            unit = 'seconds_from_helper_clock_start'
        }
        recording = [ordered]@{
            status = 'not_started'
            raw_artifact_path = $rawFull
            start_request = $null
            started_observed = $null
            stop_request = $null
            file_closed_observed = $null
            raw_media = $null
        }
        game_log = [ordered]@{
            source_path = $logFull
            baseline_bytes = $logLength
            baseline_prefix_sha256 = $logPrefixSha
            baseline_last_write_utc = $logItem.LastWriteTimeUtc.ToString('o')
            window = $null
            authority = 'order_only_no_per_line_timestamps'
        }
        marks = $marks
        screenshots = $screenshots
        events = $events
        raw_frame_mapping = [ordered]@{
            status = 'pending_manual_visual_anchor'
            authoritative = $false
            fps = $script:PromoEvidenceFps
            source_index = 'zero_based_decoded_frame'
            recording_start_frame = $null
            recording_end_frame_exclusive = $null
            events = (New-Object System.Collections.ArrayList)
            note = 'Stopwatch elapsed*60 candidates are hints only. Human frame inspection of the immutable raw/CFR source must fill verified_source_frame; no candidate may be used as a strict receipt.'
        }
        evidence_policy = [ordered]@{
            input_provenance = 'operator_mark_after_real_game_ui_pointer'
            state_provenance = 'visual_observation_only_until_human_runtime_binding'
            game_log_provenance = 'corroborative_order_only'
            strict_action_evidence = 'not_emitted'
            old_video_retrofit = 'forbidden'
        }
    }
    $session = [pscustomobject]@{
        RootPath = $root
        PartialPath = $partial
        FinalPath = $final
        EventsPath = Join-Path $root 'events'
        ScreenshotsPath = Join-Path $root 'screenshots'
        LogsPath = Join-Path $root 'logs'
        ClockStartTick = [long]$clockStart
        StopwatchFrequency = $frequency
        NextSequence = 0
        Document = $document
        Closed = $false
    }
    Write-PromoEvidenceCheckpoint -Session $session | Out-Null
    return $session
}

function Assert-PromoEvidenceSessionOpen {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object]$Session)

    if ($null -eq $Session -or $null -eq $Session.Document -or $Session.Closed) {
        throw 'Promo evidence session is closed or invalid'
    }
}

function Get-PromoCaptureMonotonic {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][object]$Session)

    Assert-PromoEvidenceSessionOpen -Session $Session
    $tick = [long][Diagnostics.Stopwatch]::GetTimestamp()
    $seconds = ([double]($tick - $Session.ClockStartTick)) / ([double]$Session.StopwatchFrequency)
    return [pscustomobject]@{
        tick = $tick
        seconds = [Math]::Round($seconds, 7)
        utc = Get-PromoEvidenceUtc
    }
}

function Get-PromoEvidenceRecordingStartSeconds {
    param([Parameter(Mandatory = $true)][object]$Session)

    $observed = $Session.Document.recording.started_observed
    if ($null -ne $observed) { return [double]$observed.monotonic_seconds }
    $request = $Session.Document.recording.start_request
    if ($null -ne $request) { return [double]$request.monotonic_seconds }
    return $null
}

function ConvertTo-PromoEvidenceSafeLabel {
    param([Parameter(Mandatory = $true)][string]$Label)

    $safe = $Label -replace '[^A-Za-z0-9._-]+', '_'
    $safe = $safe.Trim('_')
    if ([string]::IsNullOrWhiteSpace($safe)) { $safe = 'event' }
    if ($safe.Length -gt 80) { $safe = $safe.Substring(0, 80) }
    return $safe
}

function Add-PromoCaptureEvidenceMark {
    <#
      Record an observation only.  The caller must perform the real game UI
      pointer operation before calling this function for pointer_down/up.  No
      input is sent by this helper.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Session,
        [Parameter(Mandatory = $true)][string]$Label,
        [ValidateSet('operator_mark','hover','pointer_down','pointer_up','settled','recording_boundary','observation')]
        [string]$Kind = 'operator_mark',
        [int]$X = -1,
        [int]$Y = -1,
        [string]$TargetKind = '',
        [string]$TargetId = '',
        [string]$ActionId = '',
        [string]$Note = ''
    )

    Assert-PromoEvidenceSessionOpen -Session $Session
    if ([string]::IsNullOrWhiteSpace($Label)) { throw 'Evidence mark label cannot be empty' }
    foreach ($existing in $Session.Document.events) {
        if ([string]$existing.label -eq $Label) {
            throw "Evidence mark label already exists in this bundle: $Label"
        }
    }
    if (($Kind -eq 'pointer_down' -or $Kind -eq 'pointer_up') -and ($X -lt 0 -or $Y -lt 0)) {
        throw "$Kind marks require non-negative game-client coordinates"
    }
    if ($X -ge 1920 -or $Y -ge 1080) {
        throw 'Pointer coordinates must be inside the 1920x1080 game client'
    }
    if ($Kind -in @('pointer_down','pointer_up') -and [string]::IsNullOrWhiteSpace($TargetId)) {
        throw "$Kind marks require the observed target id"
    }

    $clock = Get-PromoCaptureMonotonic -Session $Session
    $seq = [int]$Session.NextSequence + 1
    $Session.NextSequence = $seq
    $relative = Get-PromoEvidenceRecordingStartSeconds -Session $Session
    $relativeSeconds = $null
    $candidateFrame = $null
    if ($null -ne $relative) {
        $relativeSeconds = [Math]::Round(([double]$clock.seconds - [double]$relative), 7)
        if ($relativeSeconds -ge 0) {
            $candidateFrame = [int][Math]::Round($relativeSeconds * $script:PromoEvidenceFps)
        }
    }
    $event = [ordered]@{
        schema_version = $script:PromoEvidenceSchemaVersion
        kind = $script:PromoEvidenceEventKind
        status = 'operator_observation_only'
        sequence = $seq
        label = $Label
        event_kind = $Kind
        action_id = if ([string]::IsNullOrWhiteSpace($ActionId)) { $null } else { $ActionId }
        target = if ([string]::IsNullOrWhiteSpace($TargetId)) { $null } else {
            [ordered]@{ kind = $TargetKind; id = $TargetId }
        }
        pointer = if ($X -ge 0 -and $Y -ge 0) {
            [ordered]@{ x = $X; y = $Y; coordinate_space = 'screen_physical_px' }
        } else { $null }
        utc = $clock.utc
        monotonic_tick = [long]$clock.tick
        monotonic_seconds = [double]$clock.seconds
        relative_to_recording_start_seconds = $relativeSeconds
        stopwatch_frame_candidate = $candidateFrame
        stopwatch_frame_candidate_authoritative = $false
        note = if ([string]::IsNullOrWhiteSpace($Note)) { $null } else { $Note }
    }
    $safe = ConvertTo-PromoEvidenceSafeLabel -Label $Label
    $eventPath = Join-Path $Session.EventsPath (('{0:D6}-{1}.json' -f $seq, $safe))
    Write-PromoEvidenceAtomicJson -Destination $eventPath -Value $event -RefuseExisting | Out-Null
    $eventDescriptor = Get-PromoEvidenceDescriptor -Root $Session.RootPath -Path $eventPath -MediaType 'application/json'
    $eventRecord = [ordered]@{
        sequence = $seq
        label = $Label
        kind = $Kind
        artifact = $eventDescriptor
        monotonic_seconds = [double]$clock.seconds
        relative_to_recording_start_seconds = $relativeSeconds
        candidate_source_frame = $candidateFrame
        candidate_authoritative = $false
    }
    $Session.Document.events.Add($eventRecord) | Out-Null
    $Session.Document.raw_frame_mapping.events.Add([ordered]@{
        sequence = $seq
        label = $Label
        relative_seconds = $relativeSeconds
        candidate_source_frame = $candidateFrame
        verified_source_frame = $null
        verification = 'pending_human_raw_frame_review'
    }) | Out-Null
    $Session.Document.marks.Add($eventRecord) | Out-Null
    Write-PromoEvidenceCheckpoint -Session $Session | Out-Null
    return $eventRecord
}

function Set-PromoCaptureRecordingBoundary {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Session,
        [Parameter(Mandatory = $true)][ValidateSet('start_request','started_observed','stop_request','file_closed_observed')][string]$Boundary,
        [string]$RawArtifactPath = ''
    )

    Assert-PromoEvidenceSessionOpen -Session $Session
    $clock = Get-PromoCaptureMonotonic -Session $Session
    $row = [ordered]@{
        utc = $clock.utc
        monotonic_tick = [long]$clock.tick
        monotonic_seconds = [double]$clock.seconds
    }
    $Session.Document.recording[$Boundary] = $row
    if (-not [string]::IsNullOrWhiteSpace($RawArtifactPath)) {
        $Session.Document.recording.raw_artifact_path = $RawArtifactPath
    }
    if ($Boundary -eq 'start_request' -or $Boundary -eq 'started_observed') {
        $Session.Document.recording.status = 'recording'
    }
    if ($Boundary -eq 'file_closed_observed') {
        $Session.Document.recording.status = 'closed'
    }
    Add-PromoCaptureEvidenceMark -Session $Session -Label ("recording_$Boundary") -Kind 'recording_boundary' -Note 'Boundary mark only; encoded source frame mapping remains pending.' | Out-Null
}

function Save-PromoCaptureEvidenceScreenshot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Session,
        [Parameter(Mandatory = $true)][ValidateSet('state.before','state.after','phase0','phase1','result','clean_hud','operator_observation')][string]$Role,
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$Note = ''
    )

    Assert-PromoEvidenceSessionOpen -Session $Session
    if (-not (Get-Command Save-Screenshot -ErrorAction SilentlyContinue)) {
        throw 'Save-Screenshot is unavailable; import tools/test/GameTest.psm1 before capturing observations.'
    }
    $safe = ConvertTo-PromoEvidenceSafeLabel -Label $Label
    $seq = [int]$Session.NextSequence + 1
    # Reserve the sequence before touching the screen.  A screenshot is itself
    # an event and must never reuse the previous screenshot's filename when two
    # observations are taken without an intervening pointer mark.  The
    # follow-up observation mark intentionally receives the next sequence.
    $Session.NextSequence = $seq
    $destination = Join-Path $Session.ScreenshotsPath (('{0:D6}-{1}.png' -f $seq, $safe))
    $temporary = "$destination.tmp.$PID.$([Guid]::NewGuid().ToString('N')).png"
    $before = Get-PromoCaptureMonotonic -Session $Session
    try {
        Save-Screenshot -Path $temporary | Out-Null
        if (-not (Test-Path -LiteralPath $temporary -PathType Leaf)) {
            throw "Save-Screenshot did not produce an image: $temporary"
        }
        if (Test-Path -LiteralPath $destination) {
            throw "Refusing to overwrite existing screenshot artifact: $destination"
        }
        [IO.File]::Move($temporary, $destination)
    }
    finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
        }
    }
    $after = Get-PromoCaptureMonotonic -Session $Session
    $descriptor = Get-PromoEvidenceDescriptor -Root $Session.RootPath -Path $destination -MediaType 'image/png'
    $row = [ordered]@{
        role = $Role
        label = $Label
        artifact = $descriptor
        capture_started_utc = $before.utc
        capture_started_monotonic_seconds = [double]$before.seconds
        capture_completed_utc = $after.utc
        capture_completed_monotonic_seconds = [double]$after.seconds
        source_frame = $null
        status = 'visual_observation_only_pending_frame_review'
        note = if ([string]::IsNullOrWhiteSpace($Note)) { $null } else { $Note }
    }
    $Session.Document.screenshots.Add($row) | Out-Null
    Add-PromoCaptureEvidenceMark -Session $Session -Label ("screenshot_$safe") -Kind 'observation' -Note 'Screenshot is visual support only; it is not a runtime state snapshot.' | Out-Null
    Write-PromoEvidenceCheckpoint -Session $Session | Out-Null
    return $row
}

function Set-PromoCaptureRawFrameAnchor {
    <#
      Human-only post-capture operation.  Requiring an existing evidence image
      and a written note makes it explicit that this is a reviewed anchor, not
      a stopwatch-derived guess.  This still does not create a strict receipt.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Session,
        [Parameter(Mandatory = $true)][string]$EventLabel,
        [Parameter(Mandatory = $true)][ValidateRange(0,2147483647)][int]$SourceZeroBasedFrame,
        [Parameter(Mandatory = $true)][string]$EvidencePath,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$VerificationNote
    )

    if ($null -eq $Session -or $null -eq $Session.Document) { throw 'Invalid promo evidence session object' }
    # Manifest artifact paths are root-relative (for hand-off portability),
    # while callers may also pass the absolute path returned by a tool. Resolve
    # both forms under the bundle before applying the root/reparse guard.
    $evidenceCandidate = $EvidencePath
    if (-not [IO.Path]::IsPathRooted($evidenceCandidate)) {
        $evidenceCandidate = Join-Path $Session.RootPath $evidenceCandidate
    }
    $evidenceFull = Assert-PromoEvidenceUnderRoot -Root $Session.RootPath -Path $evidenceCandidate -Name 'frame anchor evidence'
    if (-not (Test-Path -LiteralPath $evidenceFull -PathType Leaf)) { throw "Frame anchor evidence is missing: $evidenceFull" }
    $evidenceDescriptor = Get-PromoEvidenceDescriptor -Root $Session.RootPath -Path $evidenceFull -MediaType 'image/png'
    $found = $false
    foreach ($entry in $Session.Document.raw_frame_mapping.events) {
        if ([string]$entry.label -eq $EventLabel) {
            $entry.verified_source_frame = $SourceZeroBasedFrame
            $entry.verification = 'human_verified_against_immutable_source'
            $entry.evidence = $evidenceDescriptor
            $entry.verification_note = $VerificationNote
            $found = $true
        }
    }
    if (-not $found) { throw "No capture event named '$EventLabel' exists in this bundle" }
    foreach ($shot in $Session.Document.screenshots) {
        if ([string]$shot.artifact.path -eq [string]$evidenceDescriptor.path) {
            $shot.source_frame = $SourceZeroBasedFrame
            $shot.frame_verification = 'human_verified_against_immutable_source'
            $shot.frame_verification_note = $VerificationNote
        }
    }
    Write-PromoEvidenceCheckpoint -Session $Session | Out-Null
}

function Set-PromoCaptureRecordingFrameBounds {
    <#
      Human-only post-capture operation for the complete CFR source.  The
      helper's stopwatch candidates are never promoted here: callers must
      provide a reviewed zero-based start frame, an exclusive end frame, and
      a written note explaining how the immutable raw file was inspected.
      This updates only the evidence hand-off manifest and never emits a
      strict action/state sidecar.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Session,
        [Parameter(Mandatory = $true)][ValidateRange(0,2147483647)][int]$StartZeroBasedFrame,
        [Parameter(Mandatory = $true)][ValidateRange(1,2147483647)][int]$EndExclusiveFrame,
        [Parameter(Mandatory = $true)][ValidateNotNullOrEmpty()][string]$VerificationNote,
        [string]$StartEvidencePath = '',
        [string]$EndEvidencePath = ''
    )

    Assert-PromoEvidenceSessionOpen -Session $Session
    if ($null -eq $Session.Document.recording.file_closed_observed) {
        throw 'Mark file_closed_observed before verifying recording frame bounds'
    }
    if ($EndExclusiveFrame -le $StartZeroBasedFrame) {
        throw 'Recording end frame must be strictly after recording start frame'
    }
    $rawPath = [string]$Session.Document.recording.raw_artifact_path
    if ([string]::IsNullOrWhiteSpace($rawPath) -or -not (Test-Path -LiteralPath $rawPath -PathType Leaf)) {
        throw 'A closed raw artifact is required before recording frame bounds can be verified'
    }
    Assert-PromoEvidenceNoReparse -Path (Get-PromoEvidenceFullPath -Path $rawPath)

    $row = [ordered]@{
        start_frame = $StartZeroBasedFrame
        end_frame_exclusive = $EndExclusiveFrame
        verification = 'human_verified_against_immutable_source'
        verification_note = $VerificationNote
        verified_utc = Get-PromoEvidenceUtc
    }
    foreach ($pair in @(
        @('start_evidence', $StartEvidencePath),
        @('end_evidence', $EndEvidencePath)
    )) {
        $label = [string]$pair[0]
        $candidate = [string]$pair[1]
        if ([string]::IsNullOrWhiteSpace($candidate)) { continue }
        if (-not [IO.Path]::IsPathRooted($candidate)) {
            $candidate = Join-Path $Session.RootPath $candidate
        }
        $full = Assert-PromoEvidenceUnderRoot -Root $Session.RootPath -Path $candidate -Name "$label path"
        if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { throw "$label evidence is missing: $full" }
        $row[$label] = Get-PromoEvidenceDescriptor -Root $Session.RootPath -Path $full -MediaType 'image/png'
    }
    $Session.Document.recording.raw_frame_bounds = $row
    $Session.Document.raw_frame_mapping.recording_start_frame = $StartZeroBasedFrame
    $Session.Document.raw_frame_mapping.recording_end_frame_exclusive = $EndExclusiveFrame
    $Session.Document.raw_frame_mapping.recording_verification = 'human_verified_against_immutable_source'
    $Session.Document.raw_frame_mapping.recording_verification_note = $VerificationNote
    Write-PromoEvidenceCheckpoint -Session $Session | Out-Null
    return $row
}

function Finalize-PromoCaptureEvidenceSession {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Session,
        [switch]$Failed,
        [string]$FailureMessage = ''
    )

    Assert-PromoEvidenceSessionOpen -Session $Session
    $Session.Document.status = if ($Failed) { 'failed_evidence_bundle_preserved' } else { 'closed_evidence_only_non_production' }
    if ($Failed) {
        $Session.Document.failure = [ordered]@{
            message = if ([string]::IsNullOrWhiteSpace($FailureMessage)) { 'capture interrupted or helper failed' } else { $FailureMessage }
            utc = Get-PromoEvidenceUtc
        }
    }

    $logSource = [string]$Session.Document.game_log.source_path
    $logBaseline = [int64]$Session.Document.game_log.baseline_bytes
    $logWindowDestination = Join-Path $Session.LogsPath 'game-log-window.txt'
    try {
        if (-not (Test-Path -LiteralPath $logSource -PathType Leaf)) {
            throw "Game log is missing at finalization: $logSource"
        }
        $currentItem = Get-Item -LiteralPath $logSource -Force
        $prefixNow = Get-PromoEvidencePrefixSha256 -Path $logSource -Length $logBaseline
        if ($prefixNow -ne [string]$Session.Document.game_log.baseline_prefix_sha256) {
            throw 'Game log prefix changed; rotation or mutation detected'
        }
        Copy-PromoEvidenceLogWindow -SourcePath $logSource -StartOffset $logBaseline -Destination $logWindowDestination
        $Session.Document.game_log.window = Get-PromoEvidenceDescriptor -Root $Session.RootPath -Path $logWindowDestination -MediaType 'text/plain'
        $Session.Document.game_log.window_start_offset = $logBaseline
        $Session.Document.game_log.window_end_offset = [int64]$currentItem.Length
        $Session.Document.game_log.window_status = 'captured_order_only'
    }
    catch {
        $Session.Document.game_log.window_status = 'unavailable_or_rotated'
        $Session.Document.game_log.window_error = $_.Exception.Message
    }

    $rawPath = [string]$Session.Document.recording.raw_artifact_path
    if (-not [string]::IsNullOrWhiteSpace($rawPath)) {
        try {
            $rawFull = Get-PromoEvidenceFullPath -Path $rawPath
            if (Test-Path -LiteralPath $rawFull -PathType Leaf) {
                $item = Get-Item -LiteralPath $rawFull -Force
                $Session.Document.recording.raw_media = [ordered]@{
                    source_path = $rawFull
                    bytes = [int64]$item.Length
                    sha256 = Get-PromoEvidenceSha256 -Path $rawFull
                    frame_mapping = 'pending_manual_visual_anchor'
                }
            }
            else {
                $Session.Document.recording.raw_media_status = 'not_found_at_finalize'
            }
        }
        catch {
            $Session.Document.recording.raw_media_status = 'descriptor_failed'
            $Session.Document.recording.raw_media_error = $_.Exception.Message
        }
    }

    # Consolidate immutable event files into a review-friendly NDJSON copy.
    $eventFiles = @(Get-ChildItem -LiteralPath $Session.EventsPath -Filter '*.json' -File | Sort-Object Name)
    $ndjson = New-Object Text.StringBuilder
    foreach ($eventFile in $eventFiles) {
        # Event files are intentionally human-readable pretty JSON. Re-encode
        # each object as one compact line so `events.ndjson` is actually valid
        # NDJSON and remains deterministic for downstream reviewers.
        $eventObject = [IO.File]::ReadAllText($eventFile.FullName) | ConvertFrom-Json
        [void]$ndjson.AppendLine(($eventObject | ConvertTo-Json -Compress -Depth 40))
    }
    $ndjsonPath = Join-Path $Session.RootPath 'events.ndjson'
    Write-PromoEvidenceAtomicBytes -Destination $ndjsonPath -Bytes (ConvertTo-PromoEvidenceUtf8Bytes -Text $ndjson.ToString()) -RefuseExisting | Out-Null
    $Session.Document.event_stream = Get-PromoEvidenceDescriptor -Root $Session.RootPath -Path $ndjsonPath -MediaType 'application/x-ndjson'

    $Session.Document.updated_utc = Get-PromoEvidenceUtc
    Write-PromoEvidenceCheckpoint -Session $Session | Out-Null
    if (Test-Path -LiteralPath $Session.FinalPath) {
        throw "Refusing to overwrite final evidence manifest: $($Session.FinalPath)"
    }
    Write-PromoEvidenceAtomicJson -Destination $Session.FinalPath -Value $Session.Document -RefuseExisting | Out-Null
    $Session.Closed = $true
    return $Session.Document
}

function Mark-PromoCaptureEvidenceFailure {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Session,
        [Parameter(Mandatory = $true)][string]$Message
    )

    if ($null -eq $Session -or $null -eq $Session.Document) { return }
    try {
        $Session.Document.status = 'failed_evidence_bundle_preserved'
        $Session.Document.failure = [ordered]@{ message = $Message; utc = Get-PromoEvidenceUtc }
        Write-PromoEvidenceCheckpoint -Session $Session | Out-Null
    }
    catch {
        # Never hide the original capture failure because a checkpoint write
        # also failed.  Immutable event files remain available for salvage.
    }
}
