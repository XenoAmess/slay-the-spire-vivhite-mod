[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [int]$GameProcessId = 0,
    [int]$ObsProcessId = 0,
    [string]$GameProcessName = 'SlayTheSpire2',
    [string]$ObsProcessName = 'obs64',
    # Coordinates are the latest verified 1920x1080 hand positions; override
    # them whenever the current window/layout places a card elsewhere.
    [ValidateRange(0, 10000)][int]$RitualX = 1222,
    [ValidateRange(0, 10000)][int]$RitualY = 950,
    [ValidateRange(0, 10000)][int]$RitualDropX = 1260,
    [ValidateRange(0, 10000)][int]$RitualDropY = 580,
    [ValidateRange(0, 10000)][int]$LuminousX = 750,
    [ValidateRange(0, 10000)][int]$LuminousY = 950,
    [ValidateRange(0, 10000)][int]$TargetX = 1200,
    [ValidateRange(0, 10000)][int]$TargetY = 620,
    [ValidateRange(0, 10000)][int]$EndTurnX = 1720,
    [ValidateRange(0, 10000)][int]$EndTurnY = 900,
    [ValidateRange(0, 10000)][int]$ObsToggleX = 1260,
    [ValidateRange(0, 10000)][int]$ObsToggleY = 657,
    [ValidateRange(0, 10000)][int]$CardLiftY = 840,
    [ValidateRange(0, 10000)][int]$CardMidY = 720,
    [ValidateRange(0, 10000)][int]$HoverMilliseconds = 1800,
    [ValidateRange(0, 10000)][int]$DragStepMilliseconds = 120,
    [ValidateRange(0, 10000)][int]$ClickHoldMilliseconds = 80,
    [ValidateRange(0, 120)][double]$PreRollSeconds = 2.0,
    [ValidateRange(0, 120)][double]$Phase0WaitSeconds = 4.0,
    [ValidateRange(0, 120)][double]$AfterEndTurnWaitSeconds = 7.0,
    [ValidateRange(0, 120)][double]$LuminousSettleSeconds = 6.0,
    [ValidateRange(0, 120)][double]$PostResultSeconds = 4.0,
    [ValidateRange(0, 30)][double]$ObsStartSettleSeconds = 1.0,
    [ValidateRange(0, 30)][double]$ObsStopSettleSeconds = 3.0
)

# T16 is one uninterrupted source: ritual -> phase 0 -> end turn -> phase 1 ->
# Luminous Projection.  All setup belongs outside this script and outside the
# recording mark.  This script intentionally does not capture images or run OCR.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\..\test\GameTest.psm1')

$script:ClockStart = [Diagnostics.Stopwatch]::GetTimestamp()
$script:Marks = $null
$script:MarksPath = $null
$script:RecordingActive = $false
$script:StopRequested = $false

function Wait-Seconds([double]$Seconds) {
    if ($Seconds -le 0) { return }
    $milliseconds = [int][Math]::Round($Seconds * 1000.0)
    if ($milliseconds -gt 0) { Start-Sleep -Milliseconds $milliseconds }
}

function Get-MonotonicSeconds {
    $ticks = [Diagnostics.Stopwatch]::GetTimestamp() - $script:ClockStart
    return [Math]::Round(([double]$ticks / [double][Diagnostics.Stopwatch]::Frequency), 6)
}

function Write-OperatorMarks {
    if ($null -eq $script:Marks -or [string]::IsNullOrWhiteSpace($script:MarksPath)) {
        return
    }

    $temporaryPath = "$($script:MarksPath).tmp.$PID"
    try {
        $json = $script:Marks | ConvertTo-Json -Depth 12
        $utf8 = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllText($temporaryPath, $json, $utf8)
        Move-Item -LiteralPath $temporaryPath -Destination $script:MarksPath -Force
    }
    catch {
        # A transient sidecar write must not interrupt the real game action.
        # Keep the error in memory; the final write is attempted again in finally.
        $script:Marks['last_write_error'] = $_.Exception.Message
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Set-Mark([string]$Name) {
    if ($null -eq $script:Marks) { return }
    $utc = [DateTime]::UtcNow.ToString('o')
    $monotonic = Get-MonotonicSeconds
    $script:Marks["${Name}_utc"] = $utc
    $script:Marks["${Name}_monotonic_seconds"] = $monotonic
    if ($null -eq $script:Marks['events']) {
        $script:Marks['events'] = [ordered]@{}
    }
    $script:Marks['events'][$Name] = [ordered]@{
        utc = $utc
        monotonic_seconds = $monotonic
    }
    Write-OperatorMarks
}

function Copy-Mark([string]$SourceName, [string]$TargetName) {
    if ($null -eq $script:Marks) { return }
    $sourceUtc = $script:Marks["${SourceName}_utc"]
    $sourceMonotonic = $script:Marks["${SourceName}_monotonic_seconds"]
    if ($null -eq $sourceUtc -or $null -eq $sourceMonotonic) {
        throw "Cannot alias missing mark '$SourceName'."
    }
    $script:Marks["${TargetName}_utc"] = $sourceUtc
    $script:Marks["${TargetName}_monotonic_seconds"] = $sourceMonotonic
    if ($null -eq $script:Marks['events']) {
        $script:Marks['events'] = [ordered]@{}
    }
    $script:Marks['events'][$TargetName] = [ordered]@{
        utc = $sourceUtc
        monotonic_seconds = $sourceMonotonic
        alias_of = $SourceName
    }
    Write-OperatorMarks
}

function Resolve-CaptureProcess([string]$Name, [int]$RequestedId, [string]$Role) {
    $process = $null
    if ($RequestedId -gt 0) {
        $process = Get-Process -Id $RequestedId -ErrorAction Stop
        if ($process.ProcessName -ne $Name) {
            throw "$Role process $RequestedId is '$($process.ProcessName)', expected '$Name'."
        }
    }
    else {
        $process = Get-Process -Name $Name -ErrorAction Stop | Select-Object -First 1
        if ($null -eq $process) { throw "No $Role process named '$Name' was found." }
    }

    if ($process.MainWindowHandle -eq [IntPtr]::Zero) {
        throw "$Role process $($process.Id) has no main window."
    }
    return $process
}

function Get-ProcessIdentity($Process) {
    $path = $null
    try { $path = $Process.Path } catch { $path = $null }
    $startUtc = $null
    try { $startUtc = $Process.StartTime.ToUniversalTime().ToString('o') } catch { $startUtc = $null }
    return [ordered]@{
        id = [int]$Process.Id
        name = [string]$Process.ProcessName
        start_time_utc = $startUtc
        executable = $path
    }
}

function Move-CursorAt([int]$X, [int]$Y) {
    [GameInputNative]::SetCursorPos($X, $Y) | Out-Null
}

function Click-At([int]$X, [int]$Y, [string]$ActionName) {
    Move-CursorAt -X $X -Y $Y
    Start-Sleep -Milliseconds 60
    # Set the guard before the first OBS start input so an interruption between
    # mouse-down and the next statement still reaches the stop path in finally.
    if ($ActionName -eq 'recording_start') { $script:RecordingActive = $true }
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    Set-Mark -Name "${ActionName}_pointer_down"
    Start-Sleep -Milliseconds $ClickHoldMilliseconds
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    # Keep this immediately after LEFTUP: the release mark must describe the
    # actual game-ui pointer release, not a later settled/hold timestamp.
    Set-Mark -Name "${ActionName}_release"
}

function Drag-Card([int]$FromX, [int]$FromY, [int]$DropX, [int]$DropY, [string]$ActionName) {
    Move-CursorAt -X $FromX -Y $FromY
    Set-Mark -Name "${ActionName}_hover_start"
    Start-Sleep -Milliseconds $HoverMilliseconds

    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    Set-Mark -Name "${ActionName}_pointer_down"
    Start-Sleep -Milliseconds $DragStepMilliseconds
    [GameInputNative]::SetCursorPos($FromX, $CardLiftY) | Out-Null
    Start-Sleep -Milliseconds $DragStepMilliseconds
    [GameInputNative]::SetCursorPos($FromX, $CardMidY) | Out-Null
    Start-Sleep -Milliseconds $DragStepMilliseconds
    [GameInputNative]::SetCursorPos($DropX, $DropY) | Out-Null
    Start-Sleep -Milliseconds $DragStepMilliseconds
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    # This is deliberately the first statement after LEFTUP (see Click-At).
    Set-Mark -Name "${ActionName}_release"
}

if (-not (Test-Path -LiteralPath $OutputDirectory)) {
    New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
}
$resolvedOutput = (Resolve-Path -LiteralPath $OutputDirectory).Path
$script:MarksPath = Join-Path $resolvedOutput 'operator-marks.json'

$game = Resolve-CaptureProcess -Name $GameProcessName -RequestedId $GameProcessId -Role 'game'
$obs = Resolve-CaptureProcess -Name $ObsProcessName -RequestedId $ObsProcessId -Role 'OBS'
$GameProcessId = [int]$game.Id
$ObsProcessId = [int]$obs.Id

$script:Marks = [ordered]@{
    schema = 'vivhite-promo-t16-operator-marks-v2'
    take_id = 'T16'
    output_directory = $resolvedOutput
    game_process_id = $GameProcessId
    obs_process_id = $ObsProcessId
    game_process = Get-ProcessIdentity -Process $game
    obs_process = Get-ProcessIdentity -Process $obs
    parameters = [ordered]@{
        ritual_card_id = 'VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL'
        luminous_card_id = 'VIVHITE_CARD_LUMINOUS_PROJECTION'
        ritual = @($RitualX, $RitualY)
        ritual_drop = @($RitualDropX, $RitualDropY)
        luminous = @($LuminousX, $LuminousY)
        target = @($TargetX, $TargetY)
        end_turn = @($EndTurnX, $EndTurnY)
        obs_toggle = @($ObsToggleX, $ObsToggleY)
        pre_roll_seconds = $PreRollSeconds
        phase0_wait_seconds = $Phase0WaitSeconds
        after_end_turn_wait_seconds = $AfterEndTurnWaitSeconds
        luminous_settle_seconds = $LuminousSettleSeconds
        post_result_seconds = $PostResultSeconds
    }
    status = 'initializing'
    start_request_utc = $null
    recording_start_release_utc = $null
    recording_start_release_monotonic_seconds = $null
    recording_display_begin_utc = $null
    recording_display_begin_monotonic_seconds = $null
    ritual_hover_start_utc = $null
    ritual_release_utc = $null
    phase0_wait_begin_utc = $null
    phase0_wait_end_utc = $null
    end_turn_hover_start_utc = $null
    end_turn_release_utc = $null
    phase1_wait_begin_utc = $null
    phase1_wait_end_utc = $null
    luminous_hover_start_utc = $null
    luminous_release_utc = $null
    luminous_target_release_utc = $null
    result_hold_begin_utc = $null
    stop_request_utc = $null
    recording_stop_release_utc = $null
    recording_stop_release_monotonic_seconds = $null
    events = [ordered]@{}
}
Write-OperatorMarks

try {
    # Start OBS once. No window switch or setup occurs after this point except
    # bringing the game forward; the gameplay source remains one continuous MKV.
    Set-Mark -Name 'start_request'
    Set-WindowForeground -ProcessId $ObsProcessId
    Wait-Seconds -Seconds 0.45
    Click-At -X $ObsToggleX -Y $ObsToggleY -ActionName 'recording_start'
    $script:Marks['status'] = 'recording'
    Write-OperatorMarks
    Wait-Seconds -Seconds $ObsStartSettleSeconds

    Set-WindowForeground -ProcessId $GameProcessId
    Wait-Seconds -Seconds $PreRollSeconds
    Set-Mark -Name 'recording_display_begin'

    # Formal chain: ritual -> phase 0 -> end turn -> phase 1 -> Luminous.
    Drag-Card -FromX $RitualX -FromY $RitualY -DropX $RitualDropX -DropY $RitualDropY -ActionName 'ritual'
    Set-Mark -Name 'phase0_wait_begin'
    Wait-Seconds -Seconds $Phase0WaitSeconds
    Set-Mark -Name 'phase0_wait_end'

    Move-CursorAt -X $EndTurnX -Y $EndTurnY
    Set-Mark -Name 'end_turn_hover_start'
    Start-Sleep -Milliseconds $HoverMilliseconds
    Click-At -X $EndTurnX -Y $EndTurnY -ActionName 'end_turn'
    Set-Mark -Name 'phase1_wait_begin'
    Wait-Seconds -Seconds $AfterEndTurnWaitSeconds
    Set-Mark -Name 'phase1_wait_end'

    Drag-Card -FromX $LuminousX -FromY $LuminousY -DropX $TargetX -DropY $TargetY -ActionName 'luminous'
    # The card drag release is also the target-selection release in the normal
    # STS2 card UI. Keep an explicit alias for evidence binders.
    Copy-Mark -SourceName 'luminous_release' -TargetName 'luminous_target_release'
    Wait-Seconds -Seconds $LuminousSettleSeconds
    Move-CursorAt -X 1880 -Y 1040
    Set-Mark -Name 'result_hold_begin'
    Wait-Seconds -Seconds $PostResultSeconds
    $script:Marks['status'] = 'completed'
    Write-OperatorMarks
}
catch {
    $script:Marks['status'] = 'failed'
    $script:Marks['failure'] = [ordered]@{
        message = $_.Exception.Message
        category = [string]$_.CategoryInfo.Category
    }
    Write-OperatorMarks
    throw
}
finally {
    if ($script:RecordingActive -and -not $script:StopRequested) {
        $script:StopRequested = $true
        Set-Mark -Name 'stop_request'
        try {
            Set-WindowForeground -ProcessId $ObsProcessId
            Wait-Seconds -Seconds 0.35
            Click-At -X $ObsToggleX -Y $ObsToggleY -ActionName 'recording_stop'
            $script:RecordingActive = $false
            Wait-Seconds -Seconds $ObsStopSettleSeconds
        }
        catch {
            $script:Marks['stop_error'] = $_.Exception.Message
        }
    }
    if ($script:Marks['status'] -eq 'recording') {
        $script:Marks['status'] = 'stopped_after_error'
    }
    Write-OperatorMarks
}

$script:Marks | ConvertTo-Json -Compress -Depth 12
