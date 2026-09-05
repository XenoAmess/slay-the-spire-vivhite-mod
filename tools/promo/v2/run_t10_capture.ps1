<#
.SYNOPSIS
    Runs one uninterrupted T10 Act 2/3 map-to-campfire-to-map capture.

.DESCRIPTION
    This is an operator-side recorder, not a state/evidence synthesizer.  The
    caller must visually inspect the clean game window immediately before
    invocation and provide the observed map point, hitbox, act, floor and HP
    values (or a preflight JSON containing those values).  Every formal input
    is then issued by this one PowerShell process; no screenshot, OCR, console
    command, window switch or interactive inspection is performed after the
    recording mark.  The event log and operator-marks.partial.json are updated
    after each event so an interrupted attempt can be resumed without guessing
    what happened.  During a live attempt the mutable checkpoint is
    `operator-marks.partial.json`; it is promoted to `operator-marks.json` only
    after a normal stop, so an interrupted attempt remains distinguishable.

    The event log is deliberately labelled operator-only.  It must not be
    loaded as native action_evidence_v2: this script has no access to the game's
    native state/action receipt API.

.EXAMPLE
    .\run_t10_capture.ps1 `
      -OutputDirectory 'G:\OBS_VIDEOS\vivhite-director-v2\run-...\T10\a04' `
      -AttemptId a04 -RunId run-20260903T0012-director-v2-a1 `
      -MapNodeId 'act2-col0-row6' -ExpectedAct 2 -ExpectedFloor 30 `
      -CurrentHpBefore 76 -MaxHpBefore 82 `
      -MapNodeX 510 -MapNodeY 270 `
      -MapHitboxLeft 480 -MapHitboxTop 240 -MapHitboxRight 540 -MapHitboxBottom 300 `
      -RestX 790 -RestY 340 -ProceedX 1730 -ProceedY 815 `
      -ObsRecordButtonX 1260 -ObsRecordButtonY 657 `
      -PreflightConfirmed

    Coordinates above are only an example.  They are intentionally not used
    as defaults; map coordinates are seed/act/camera dependent.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$OutputDirectory,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^a[0-9]+$')]
    [string]$AttemptId,

    [string]$RunId = 'run-20260903T0012-director-v2-a1',

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$MapNodeId,

    [Parameter(Mandatory = $true)]
    [ValidateSet(2, 3)]
    [int]$ExpectedAct,

    [int]$ExpectedFloor = -1,
    [int]$CurrentHpBefore = -1,
    [int]$MaxHpBefore = -1,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 1919)]
    [int]$MapNodeX,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 1079)]
    [int]$MapNodeY,

    # A live visual hitbox is required when no preflight receipt is supplied.
    [int]$MapHitboxLeft = -1,
    [int]$MapHitboxTop = -1,
    [int]$MapHitboxRight = -1,
    [int]$MapHitboxBottom = -1,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 1919)]
    [int]$RestX,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 1079)]
    [int]$RestY,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 1919)]
    [int]$ProceedX,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 1079)]
    [int]$ProceedY,

    # OBS layout is user/configuration dependent, so the record button is
    # explicit too.  Do not silently reuse an old OBS coordinate.
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 10000)]
    [int]$ObsRecordButtonX,
    [Parameter(Mandatory = $true)]
    [ValidateRange(1, 10000)]
    [int]$ObsRecordButtonY,

    [ValidateRange(1, 10000)]
    [int]$NeutralCursorX = 1800,
    [ValidateRange(1, 10000)]
    [int]$NeutralCursorY = 500,

    [int]$GameProcessId = 0,
    [int]$ObsProcessId = 0,
    [string]$PreflightReceiptPath = '',

    [ValidateRange(1, 5)]
    [double]$PreRollSeconds = 2.0,
    [ValidateRange(1.5, 3)]
    [double]$MapHoverSeconds = 1.6,
    [ValidateRange(2.5, 8)]
    [double]$MapToCampfireSeconds = 4.6,
    [ValidateRange(1.5, 3)]
    [double]$RestHoverSeconds = 1.6,
    [ValidateRange(1, 6)]
    [double]$RestResultSeconds = 2.8,
    [ValidateRange(0.5, 3)]
    [double]$ProceedHoverSeconds = 0.8,
    [ValidateRange(1.5, 8)]
    [double]$MapReturnSeconds = 3.2,
    [ValidateRange(2, 5)]
    [double]$PostMapHoldSeconds = 3.4,
    [ValidateRange(20, 500)]
    [int]$ClickHoldMilliseconds = 90,
    [ValidateRange(1, 10)]
    [int]$FileCloseTimeoutSeconds = 6,
    [ValidateRange(0.1, 5)]
    [double]$ObsStartSettleSeconds = 0.9,
    [ValidateRange(0.1, 5)]
    [double]$ObsStopSettleSeconds = 0.8,

    [switch]$PreflightConfirmed,
    [switch]$PreflightOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$gameTestPath = Join-Path $PSScriptRoot '..\..\test\GameTest.psm1'
Import-Module $gameTestPath -Force
. (Join-Path $PSScriptRoot 'promo_capture_operator_common.ps1')

function Get-ProcessIdentity {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process
    )

    $path = $null
    try { $path = $Process.MainModule.FileName } catch { $path = $null }
    $commandLine = $null
    try {
        $wmi = Get-CimInstance Win32_Process -Filter ("ProcessId={0}" -f $Process.Id)
        if ($null -ne $wmi) { $commandLine = [string]$wmi.CommandLine }
    } catch { $commandLine = $null }
    $start = $null
    try { $start = $Process.StartTime.ToUniversalTime().ToString('o') } catch { $start = $null }
    return [ordered]@{
        pid = $Process.Id
        name = $Process.ProcessName
        executable = $path
        command_line = $commandLine
        start_utc = $start
        main_window_handle = ('0x{0:X}' -f $Process.MainWindowHandle.ToInt64())
    }
}

function Resolve-UniqueProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$RequestedId
    )

    if ($RequestedId -gt 0) {
        $p = Get-Process -Id $RequestedId -ErrorAction Stop
        if ($p.ProcessName -ne $Name) {
            throw "Process $RequestedId is '$($p.ProcessName)', expected '$Name'."
        }
        return $p
    }

    $matches = @(Get-Process -Name $Name -ErrorAction SilentlyContinue)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one $Name process; found $($matches.Count). Pass an explicit process id."
    }
    return $matches[0]
}

function Assert-Executable {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][string]$ExpectedLeafName
    )

    $path = $null
    try { $path = $Process.MainModule.FileName } catch { }
    if ([string]::IsNullOrWhiteSpace($path) -or
        ([IO.Path]::GetFileName($path) -ine $ExpectedLeafName)) {
        throw "Process $($Process.Id) does not resolve to $ExpectedLeafName (path='$path')."
    }
    if ($Process.MainWindowHandle -eq [IntPtr]::Zero) {
        throw "Process $($Process.Id) has no main window; refusing to send UI input."
    }
}

function Assert-PointInRect {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][int]$X,
        [Parameter(Mandatory = $true)][int]$Y,
        [Parameter(Mandatory = $true)]$Rect
    )

    if ($X -lt $Rect.Left -or $X -ge $Rect.Right -or $Y -lt $Rect.Top -or $Y -ge $Rect.Bottom) {
        throw "$Name ($X,$Y) is outside window rect [$($Rect.Left),$($Rect.Top),$($Rect.Right),$($Rect.Bottom)]."
    }
}

function Assert-HitboxContainsPoint {
    param(
        [Parameter(Mandatory = $true)][int]$X,
        [Parameter(Mandatory = $true)][int]$Y,
        [Parameter(Mandatory = $true)][int]$Left,
        [Parameter(Mandatory = $true)][int]$Top,
        [Parameter(Mandatory = $true)][int]$Right,
        [Parameter(Mandatory = $true)][int]$Bottom
    )

    if ($Right -le $Left -or $Bottom -le $Top) {
        throw "Map hitbox is empty or inverted: [$Left,$Top,$Right,$Bottom]."
    }
    if ($X -lt $Left -or $X -ge $Right -or $Y -lt $Top -or $Y -ge $Bottom) {
        throw "Map point ($X,$Y) lies outside observed hitbox [$Left,$Top,$Right,$Bottom]."
    }
}

function Read-PreflightReceipt {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    $raw = Get-Content -LiteralPath $resolved -Raw -ErrorAction Stop
    try { $obj = $raw | ConvertFrom-Json -ErrorAction Stop } catch {
        throw "Preflight receipt is not valid JSON: $resolved"
    }

    foreach ($property in @('screen', 'act', 'current_hp', 'max_hp', 'target')) {
        if ($null -eq $obj.PSObject.Properties[$property]) {
            throw "Preflight receipt '$resolved' lacks required property '$property'."
        }
    }
    if ([string]$obj.screen -ne 'MAP') { throw "Preflight screen must be MAP, got '$($obj.screen)'." }
    if ([int]$obj.act -notin @(2, 3)) { throw "Preflight act must be 2 or 3." }
    if ([int]$obj.current_hp -ge [int]$obj.max_hp) {
        throw "Preflight requires injured player: current_hp < max_hp."
    }
    if ($null -eq $obj.target.PSObject.Properties['id'] -or
        [string]::IsNullOrWhiteSpace([string]$obj.target.id)) {
        throw 'Preflight target.id is required.'
    }
    if ($null -eq $obj.target.PSObject.Properties['reachable'] -or -not [bool]$obj.target.reachable) {
        throw 'Preflight target.reachable must be true for the selected RestSite.'
    }
    foreach ($property in @('x', 'y', 'hitbox')) {
        if ($null -eq $obj.target.PSObject.Properties[$property]) {
            throw "Preflight target lacks '$property'."
        }
    }
    $hb = $obj.target.hitbox
    foreach ($property in @('left', 'top', 'right', 'bottom')) {
        if ($null -eq $hb.PSObject.Properties[$property]) {
            throw "Preflight target.hitbox lacks '$property'."
        }
    }
    Assert-HitboxContainsPoint -X ([int]$obj.target.x) -Y ([int]$obj.target.y) `
        -Left ([int]$hb.left) -Top ([int]$hb.top) -Right ([int]$hb.right) -Bottom ([int]$hb.bottom)

    $hash = (Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash
    return [ordered]@{
        path = $resolved
        sha256 = $hash
        screen = [string]$obj.screen
        act = [int]$obj.act
        floor = if ($null -ne $obj.PSObject.Properties['floor']) { [int]$obj.floor } else { $null }
        current_hp = [int]$obj.current_hp
        max_hp = [int]$obj.max_hp
        target_id = [string]$obj.target.id
        target_x = [int]$obj.target.x
        target_y = [int]$obj.target.y
        reachable = [bool]$obj.target.reachable
        hitbox = [ordered]@{
            left = [int]$hb.left
            top = [int]$hb.top
            right = [int]$hb.right
            bottom = [int]$hb.bottom
        }
        forbidden_visuals = if ($null -ne $obj.PSObject.Properties['forbidden_visuals']) { @($obj.forbidden_visuals) } else { @() }
    }
}

function New-OutputDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    $full = [IO.Path]::GetFullPath($Path)
    if (Test-Path -LiteralPath $full) {
        $items = @(Get-ChildItem -LiteralPath $full -Force -ErrorAction Stop)
        if ($items.Count -gt 0) {
            throw "OutputDirectory must be new or empty; refusing to mix attempts: $full"
        }
    } else {
        New-Item -ItemType Directory -Force -Path $full | Out-Null
    }
    return $full
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )

    # The attempt directory is private to this run.  A short-lived sibling
    # avoids readers observing half-written JSON while recovery tooling polls.
    $tmp = "$Path.tmp"
    $json = $Value | ConvertTo-Json -Depth 20
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($tmp, $json, $utf8)
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

$fullOutputDirectory = $null
$eventPath = $null
$marksPath = $null
$partialMarksPath = $null
$state = [ordered]@{
    status = 'initializing'
    schema = 'vivhite-promo-t10-operator-marks-v1'
    take_id = 'T10'
    attempt_id = $AttemptId
    run_id = $RunId
    output_directory = $null
    started_utc = [DateTime]::UtcNow.ToString('o')
    finished_utc = $null
    game = $null
    obs = $null
    timing = [ordered]@{
        stopwatch_frequency = [Diagnostics.Stopwatch]::Frequency
        clock_start_monotonic_tick = $null
        obs_start_settle_seconds = $ObsStartSettleSeconds
        obs_stop_settle_seconds = $ObsStopSettleSeconds
        recording_start_request_utc = $null
        recording_mark_utc = $null
        recording_stop_request_utc = $null
    }
    preflight = $null
    last_write_error = $null
    coordinates = [ordered]@{
        coordinate_space = 'screen_physical_px'
        map_node = [ordered]@{ id = $MapNodeId; x = $MapNodeX; y = $MapNodeY }
        rest = [ordered]@{ x = $RestX; y = $RestY }
        proceed = [ordered]@{ x = $ProceedX; y = $ProceedY }
        obs_record_button = [ordered]@{ x = $ObsRecordButtonX; y = $ObsRecordButtonY }
        neutral_cursor = [ordered]@{ x = $NeutralCursorX; y = $NeutralCursorY }
    }
    events = @()
    recording = [ordered]@{
        source_file = $null
        source_bytes = $null
        source_sha256 = $null
        native_receipts_exported = $false
        receipt_status = 'operator_marks_only_not_native_action_evidence'
        transition_policy = 'preserve_native_transition_in_raw; archive blackdetect before deciding display span'
    }
}
$clockStartTick = [Diagnostics.Stopwatch]::GetTimestamp()
$state.timing.clock_start_monotonic_tick = [long]$clockStartTick
$recordingMayBeActive = $false
$stopAttempted = $false
$finalMarksPromoted = $false
$game = $null
$obs = $null

function Save-Marks {
    if ([string]::IsNullOrWhiteSpace($partialMarksPath)) { return }
    $state.finished_utc = if ($state.status -in @('completed', 'failed', 'preflight_passed')) { [DateTime]::UtcNow.ToString('o') } else { $null }
    Write-JsonAtomic -Path $partialMarksPath -Value $state
}

function Add-OperatorEvent {
    param(
        [Parameter(Mandatory = $true)][string]$Event,
        [System.Collections.IDictionary]$Data = @{}
    )

    $nowTick = [Diagnostics.Stopwatch]::GetTimestamp()
    $entry = [ordered]@{
        event = $Event
        utc = [DateTime]::UtcNow.ToString('o')
        elapsed_s = [Math]::Round((($nowTick - $clockStartTick) / [double][Diagnostics.Stopwatch]::Frequency), 3)
        monotonic_tick = [long]$nowTick
        stopwatch_frequency = [long][Diagnostics.Stopwatch]::Frequency
    }
    foreach ($key in $Data.Keys) { $entry[$key] = $Data[$key] }
    $state.events += ,$entry
    if ($null -ne $eventPath) {
        try {
            $line = ($entry | ConvertTo-Json -Compress -Depth 10) + [Environment]::NewLine
            $utf8 = New-Object System.Text.UTF8Encoding($false)
            [IO.File]::AppendAllText($eventPath, $line, $utf8)
        } catch {
            # Logging must never interrupt the one-take input chain.  Keep the
            # write error in the in-memory handoff and retry on the next mark.
            $state.last_write_error = $_.Exception.Message
        }
    }
    try { Save-Marks } catch { $state.last_write_error = $_.Exception.Message }
    return $entry
}

function Set-GameForegroundChecked {
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        Set-WindowForeground -ProcessId $game.Id
        Start-Sleep -Milliseconds 80
        $foreground = [GameInputNative]::GetForegroundWindow()
        if ($foreground -eq $game.MainWindowHandle) { return }
        Start-Sleep -Milliseconds 80
    }
    throw "Game window did not become foreground (pid=$($game.Id))."
}

function Set-ObsForegroundChecked {
    for ($attempt = 0; $attempt -lt 3; $attempt++) {
        Set-WindowForeground -ProcessId $obs.Id
        Start-Sleep -Milliseconds 80
        $foreground = [GameInputNative]::GetForegroundWindow()
        if ($foreground -eq $obs.MainWindowHandle) { return }
        Start-Sleep -Milliseconds 80
    }
    throw "OBS window did not become foreground (pid=$($obs.Id))."
}

function Invoke-StampedClick {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][int]$X,
        [Parameter(Mandatory = $true)][int]$Y,
        [Parameter(Mandatory = $true)][double]$HoverSeconds,
        [Parameter(Mandatory = $true)][double]$SettleSeconds,
        [switch]$FocusGame
    )

    if ($FocusGame) { Set-GameForegroundChecked }
    Move-Mouse -X $X -Y $Y
    Add-OperatorEvent -Event "${Label}_hover_start" -Data @{ x = $X; y = $Y } | Out-Null
    Start-Sleep -Milliseconds ([int][Math]::Round($HoverSeconds * 1000))
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    # Mark immediately after the native DOWN call so the receipt cannot claim
    # a pointer event that happened before the actual input was delivered.
    Add-OperatorEvent -Event "${Label}_pointer_down" -Data @{ x = $X; y = $Y } | Out-Null
    Start-Sleep -Milliseconds $ClickHoldMilliseconds
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    Add-OperatorEvent -Event "${Label}_pointer_up" -Data @{ x = $X; y = $Y } | Out-Null
    if ($SettleSeconds -gt 0) {
        Add-OperatorEvent -Event "${Label}_settlement_wait_begin" -Data @{ seconds = $SettleSeconds } | Out-Null
        Start-Sleep -Milliseconds ([int][Math]::Round($SettleSeconds * 1000))
        Add-OperatorEvent -Event "${Label}_settlement_wait_end" -Data @{ seconds = $SettleSeconds } | Out-Null
    }
    Add-OperatorEvent -Event "${Label}_settled" -Data @{ x = $X; y = $Y } | Out-Null
}

function Find-NewRecordingFile {
    param([datetime]$SinceUtc)

    $deadline = [DateTime]::UtcNow.AddSeconds($FileCloseTimeoutSeconds)
    do {
        $files = @(Get-ChildItem -LiteralPath $fullOutputDirectory -File -Filter '*.mkv' -ErrorAction SilentlyContinue |
            Where-Object { $_.LastWriteTimeUtc -ge $SinceUtc.AddSeconds(-2) } |
            Sort-Object LastWriteTimeUtc -Descending)
        if ($files.Count -gt 0) { return $files[0] }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    return $null
}

try {
    $fullOutputDirectory = New-OutputDirectory -Path $OutputDirectory
    $eventPath = Join-Path $fullOutputDirectory 'operator-events.ndjson'
    $partialMarksPath = Join-Path $fullOutputDirectory 'operator-marks.partial.json'
    $marksPath = Join-Path $fullOutputDirectory 'operator-marks.json'
    $state.output_directory = $fullOutputDirectory

    $game = Resolve-UniqueProcess -Name 'SlayTheSpire2' -RequestedId $GameProcessId
    $obs = Resolve-UniqueProcess -Name 'obs64' -RequestedId $ObsProcessId
    Assert-Executable -Process $game -ExpectedLeafName 'SlayTheSpire2.exe'
    Assert-Executable -Process $obs -ExpectedLeafName 'obs64.exe'
    $state.game = Get-ProcessIdentity -Process $game
    $state.obs = Get-ProcessIdentity -Process $obs

    $gameRect = Get-WindowRect -ProcessId $game.Id
    $obsRect = Get-WindowRect -ProcessId $obs.Id
    if (($gameRect.Right - $gameRect.Left) -lt 1920 -or ($gameRect.Bottom - $gameRect.Top) -lt 1080) {
        throw "Game window is smaller than the required 1920x1080 capture surface."
    }
    Assert-PointInRect -Name 'map node' -X $MapNodeX -Y $MapNodeY -Rect $gameRect
    Assert-PointInRect -Name 'rest button' -X $RestX -Y $RestY -Rect $gameRect
    Assert-PointInRect -Name 'proceed button' -X $ProceedX -Y $ProceedY -Rect $gameRect
    Assert-PointInRect -Name 'neutral cursor' -X $NeutralCursorX -Y $NeutralCursorY -Rect $gameRect
    # OBS recording is toggled through the record button's stable UI
    # AutomationId.  Screen coordinates are retained in the operator marks for
    # backward-compatible handoff only; they are not used to control OBS.

    $receipt = Read-PreflightReceipt -Path $PreflightReceiptPath
    if ($null -ne $receipt) {
        if ($receipt.act -ne $ExpectedAct) { throw "Preflight act $($receipt.act) does not match ExpectedAct $ExpectedAct." }
        if ($ExpectedFloor -ge 0 -and $null -ne $receipt.floor -and $receipt.floor -ne $ExpectedFloor) {
            throw "Preflight floor $($receipt.floor) does not match ExpectedFloor $ExpectedFloor."
        }
        if ($receipt.target_id -ne $MapNodeId) { throw "Preflight target '$($receipt.target_id)' does not match MapNodeId '$MapNodeId'." }
        if ($receipt.target_x -ne $MapNodeX -or $receipt.target_y -ne $MapNodeY) {
            throw 'Map point does not match the point in the preflight receipt.'
        }
        Assert-HitboxContainsPoint -X $MapNodeX -Y $MapNodeY `
            -Left $receipt.hitbox.left -Top $receipt.hitbox.top -Right $receipt.hitbox.right -Bottom $receipt.hitbox.bottom
        if ($CurrentHpBefore -gt 0 -and $CurrentHpBefore -ne $receipt.current_hp) { throw 'CurrentHpBefore differs from preflight receipt.' }
        if ($MaxHpBefore -gt 0 -and $MaxHpBefore -ne $receipt.max_hp) { throw 'MaxHpBefore differs from preflight receipt.' }
        if ($receipt.forbidden_visuals.Count -gt 0) { throw 'Preflight receipt reports forbidden visual/overlay content.' }
        $CurrentHpBefore = $receipt.current_hp
        $MaxHpBefore = $receipt.max_hp
        $state.preflight = $receipt
    } else {
        if (-not $PreflightConfirmed -and -not $PreflightOnly) {
            throw 'Pass -PreflightConfirmed only after visually confirming a clean Act 2/3 MAP, injured HP, and a reachable RestSite.'
        }
        if ($CurrentHpBefore -lt 1 -or $MaxHpBefore -lt 1 -or $CurrentHpBefore -ge $MaxHpBefore) {
            throw 'Without a receipt, -CurrentHpBefore and -MaxHpBefore must be supplied and current_hp must be lower.'
        }
        if ($MapHitboxLeft -lt 0 -or $MapHitboxTop -lt 0 -or $MapHitboxRight -lt 0 -or $MapHitboxBottom -lt 0) {
            throw 'Without a receipt, all four observed map hitbox parameters are required.'
        }
        Assert-HitboxContainsPoint -X $MapNodeX -Y $MapNodeY -Left $MapHitboxLeft -Top $MapHitboxTop -Right $MapHitboxRight -Bottom $MapHitboxBottom
        $state.preflight = [ordered]@{
            source = 'operator_confirmation_not_native_state'
            confirmed = [bool]$PreflightConfirmed
            screen = 'MAP'
            act = $ExpectedAct
            floor = if ($ExpectedFloor -ge 0) { $ExpectedFloor } else { $null }
            current_hp = $CurrentHpBefore
            max_hp = $MaxHpBefore
            target_id = $MapNodeId
            target_x = $MapNodeX
            target_y = $MapNodeY
            reachable = $true
            hitbox = [ordered]@{ left = $MapHitboxLeft; top = $MapHitboxTop; right = $MapHitboxRight; bottom = $MapHitboxBottom }
            forbidden_visuals = @('operator visually confirmed only; no pixel/OCR proof exported')
        }
    }

    Add-OperatorEvent -Event 'preflight_passed' -Data @{
        act = $state.preflight.act
        floor = $state.preflight.floor
        current_hp = $state.preflight.current_hp
        max_hp = $state.preflight.max_hp
        target_id = $MapNodeId
        target_x = $MapNodeX
        target_y = $MapNodeY
    } | Out-Null

    if ($PreflightOnly) {
        $state.status = 'preflight_passed'
        Save-Marks
        if (Test-Path -LiteralPath $marksPath) { throw "Refusing to overwrite final marks: $marksPath" }
        Move-Item -LiteralPath $partialMarksPath -Destination $marksPath
        $finalMarksPromoted = $true
        Write-Output ($state | ConvertTo-Json -Depth 20 -Compress)
        return
    }

    $state.status = 'recording'
    $recordingSince = [DateTime]::UtcNow
    Add-OperatorEvent -Event 'recording_start_request' -Data @{
        method = 'uia_invoke'
        automation_id = 'OBSApp.OBSBasic.controlsDock.OBSBasicControls.controlsFrame.recordButton'
    } | Out-Null
    $state.timing.recording_start_request_utc = [DateTime]::UtcNow.ToString('o')
    Invoke-ObsRecordToggle -Process $obs -ExpectedAction start
    $recordingMayBeActive = $true
    if (-not (Wait-ObsRecordState -Process $obs -ExpectedState recording -TimeoutMilliseconds 5000)) {
        throw 'OBS did not enter recording state after UI Automation invoke.'
    }
    Add-OperatorEvent -Event 'recording_start_confirmed' -Data @{ method = 'uia_button_state' } | Out-Null
    Start-Sleep -Milliseconds ([int][Math]::Round($ObsStartSettleSeconds * 1000))

    Set-GameForegroundChecked
    Add-OperatorEvent -Event 'game_focus_after_recording_start' -Data @{ pid = $game.Id } | Out-Null
    Start-Sleep -Milliseconds ([int][Math]::Round($PreRollSeconds * 1000))
    $state.timing.recording_mark_utc = [DateTime]::UtcNow.ToString('o')
    Add-OperatorEvent -Event 'recording_mark' -Data @{
        reason = 'first_clean_game_only_frame_after_preroll'
        pre_roll_seconds = $PreRollSeconds
    } | Out-Null

    # Formal chain: map -> campfire -> REST/heal -> Proceed -> map.  There is
    # deliberately no screenshot or operator inspection between these calls.
    Invoke-StampedClick -Label 'map_node' -X $MapNodeX -Y $MapNodeY `
        -HoverSeconds $MapHoverSeconds -SettleSeconds $MapToCampfireSeconds
    Add-OperatorEvent -Event 'campfire_animation_settled' -Data @{ expected_act = $ExpectedAct } | Out-Null

    Invoke-StampedClick -Label 'rest' -X $RestX -Y $RestY `
        -HoverSeconds $RestHoverSeconds -SettleSeconds $RestResultSeconds
    Add-OperatorEvent -Event 'rest_result_settled' -Data @{
        expected_hp_before = $CurrentHpBefore
        expected_max_hp = $MaxHpBefore
        visual_check_required = 'actual_native_HP_increase_and_fire_extinguished'
    } | Out-Null

    Invoke-StampedClick -Label 'proceed' -X $ProceedX -Y $ProceedY `
        -HoverSeconds $ProceedHoverSeconds -SettleSeconds $MapReturnSeconds
    Add-OperatorEvent -Event 'map_return_settled' -Data @{ expected_act = $ExpectedAct } | Out-Null
    Move-Mouse -X $NeutralCursorX -Y $NeutralCursorY
    Start-Sleep -Milliseconds ([int][Math]::Round($PostMapHoldSeconds * 1000))
    Add-OperatorEvent -Event 'frame_end_hold_complete' -Data @{ post_map_hold_seconds = $PostMapHoldSeconds } | Out-Null

    $state.timing.recording_stop_request_utc = [DateTime]::UtcNow.ToString('o')
    Add-OperatorEvent -Event 'recording_stop_request' -Data @{
        method = 'uia_invoke'
        automation_id = 'OBSApp.OBSBasic.controlsDock.OBSBasicControls.controlsFrame.recordButton'
    } | Out-Null
    Invoke-ObsRecordToggle -Process $obs -ExpectedAction stop
    $stopAttempted = $true
    if (-not (Wait-ObsRecordState -Process $obs -ExpectedState stopped -TimeoutMilliseconds 5000)) {
        throw 'OBS did not enter stopped state after UI Automation invoke.'
    }
    Add-OperatorEvent -Event 'recording_stop_confirmed' -Data @{ method = 'uia_button_state' } | Out-Null
    Start-Sleep -Milliseconds ([int][Math]::Round($ObsStopSettleSeconds * 1000))

    $file = Find-NewRecordingFile -SinceUtc $recordingSince
    if ($null -eq $file) {
        throw "OBS stopped but no new MKV appeared under $fullOutputDirectory. Check OBS output path before retrying."
    }
    $state.recording.source_file = $file.FullName
    $state.recording.source_bytes = $file.Length
    $state.recording.source_sha256 = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    Add-OperatorEvent -Event 'recording_file_closed' -Data @{
        path = $file.FullName
        bytes = $file.Length
        sha256 = $state.recording.source_sha256
    } | Out-Null
    $state.status = 'completed'
    Save-Marks
    if (Test-Path -LiteralPath $marksPath) { throw "Refusing to overwrite final marks: $marksPath" }
    Move-Item -LiteralPath $partialMarksPath -Destination $marksPath
    $finalMarksPromoted = $true
    Write-Output ($state | ConvertTo-Json -Depth 20 -Compress)
}
catch {
    $state.status = 'failed'
    try {
        Add-OperatorEvent -Event 'capture_failed' -Data @{ error = $_.Exception.Message } | Out-Null
    } catch { }
    throw
}
finally {
    # If anything failed after the OBS start click, make one best-effort stop
    # click.  Never issue a second stop after a normal completion.
    if ($recordingMayBeActive -and -not $stopAttempted -and $null -ne $obs) {
        try {
            Add-OperatorEvent -Event 'recording_stop_recovery_request' -Data @{ method = 'uia_invoke' } | Out-Null
            Invoke-ObsRecordToggle -Process $obs -ExpectedAction stop
            $stopAttempted = $true
            if (-not (Wait-ObsRecordState -Process $obs -ExpectedState stopped -TimeoutMilliseconds 5000)) {
                throw 'OBS recovery stop did not reach stopped state.'
            }
            Add-OperatorEvent -Event 'recording_stop_recovery_confirmed' -Data @{ method = 'uia_button_state' } | Out-Null
            Start-Sleep -Milliseconds ([int][Math]::Round($ObsStopSettleSeconds * 1000))
        } catch {
            try { Add-OperatorEvent -Event 'recording_stop_recovery_failed' -Data @{ error = $_.Exception.Message } | Out-Null } catch { }
        }
    }
    if ($state.status -eq 'recording') { $state.status = 'failed' }
    try {
        if (-not $finalMarksPromoted) {
            Save-Marks
        }
    } catch { }
}
