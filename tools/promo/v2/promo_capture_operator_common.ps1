# Shared helpers for the T17/T19 operator-side capture runners.
#
# These helpers only record operator marks and screenshots.  They intentionally
# do not create native action-evidence documents, state.before/after files, or
# any claim about what the game rendered.  Those artifacts must be produced and
# verified after the raw MKV is closed.

Set-StrictMode -Version Latest

if ($null -eq ('PromoCaptureNative' -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class PromoCaptureNative {
    [DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, int extraInfo);
    public const uint MOUSEEVENTF_WHEEL = 0x0800;
}
"@ -ErrorAction Stop
}

function Assert-NewOperatorAttempt {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$OutputDirectory,
        [Parameter(Mandatory = $true)][string]$AttemptId
    )

    if ([string]::IsNullOrWhiteSpace($AttemptId) -or $AttemptId -notmatch '^a[0-9]+$') {
        throw "attempt_id must match a<number>; received '$AttemptId'"
    }
    $full = [System.IO.Path]::GetFullPath($OutputDirectory)
    if (-not (Test-Path -LiteralPath $full)) {
        New-Item -ItemType Directory -Force -Path $full | Out-Null
    }
    $existingMedia = @(Get-ChildItem -LiteralPath $full -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -match '(?i)^\.(mkv|mp4)$' })
    if ($existingMedia.Count -gt 0) {
        throw "OutputDirectory already contains media; use a new attempt_id/output directory: $full"
    }
    foreach ($name in @('operator-marks.json', 'operator-marks.partial.json')) {
        $candidate = Join-Path $full $name
        if (Test-Path -LiteralPath $candidate) {
            throw "Refusing to overwrite existing operator marks: $candidate; use a new attempt_id/output directory"
        }
    }
    return $full
}

function Get-OperatorMark {
    [CmdletBinding()]
    param()

    $stamp = [System.Diagnostics.Stopwatch]::GetTimestamp()
    return [ordered]@{
        utc = [DateTime]::UtcNow.ToString('o')
        monotonic_tick = [long]$stamp
        stopwatch_frequency = [long][System.Diagnostics.Stopwatch]::Frequency
    }
}

function Get-OperatorProcessRecord {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process)

    $started = $null
    try { $started = $Process.StartTime.ToUniversalTime().ToString('o') } catch { $started = $null }
    $exe = $null
    try { $exe = $Process.MainModule.FileName } catch { $exe = $null }
    $name = [string]$Process.ProcessName
    if ($name -notmatch '\.exe$') { $name = "$name.exe" }
    $identity = $null
    if ($null -ne $started) {
        # Keep the process identity consumable by strict v2 capture IDs.  The
        # older colon-delimited form was useful as a log label but is not a
        # portable identifier for action_evidence_v2.py.
        $identityStart = $started -replace ':', '-'
        $identity = "$name-$($Process.Id)-$identityStart"
    }
    return [ordered]@{
        pid = [int]$Process.Id
        process_name = $name
        executable = $exe
        started_utc = $started
        identity = $identity
    }
}

function Resolve-UniqueOperatorProcess {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ProcessName,
        [int]$ProcessId = 0
    )

    if ($ProcessId -gt 0) {
        $explicit = Get-Process -Id $ProcessId -ErrorAction Stop
        if ($explicit.ProcessName -ne $ProcessName) {
            throw "Process $ProcessId is '$($explicit.ProcessName)', expected '$ProcessName'."
        }
        if ($explicit.MainWindowHandle -eq [IntPtr]::Zero) {
            throw "Process $ProcessId ($ProcessName) has no main window; refusing to send UI input."
        }
        return $explicit
    }
    $found = @(Get-Process -Name $ProcessName -ErrorAction SilentlyContinue)
    if ($found.Count -ne 1) {
        throw "Expected exactly one $ProcessName process; found $($found.Count). Pass an explicit process id."
    }
    if ($found[0].MainWindowHandle -eq [IntPtr]::Zero) {
        throw "Process $($found[0].Id) ($ProcessName) has no main window; refusing to send UI input."
    }
    return $found[0]
}

function Invoke-OperatorWheel {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][int]$X,
        [Parameter(Mandatory = $true)][int]$Y,
        [Parameter(Mandatory = $true)][int]$Delta
    )

    Move-Mouse -X $X -Y $Y
    $wheelData = if ($Delta -lt 0) { [uint32]([int64]$Delta + 4294967296) } else { [uint32]$Delta }
    [PromoCaptureNative]::mouse_event(
        [PromoCaptureNative]::MOUSEEVENTF_WHEEL,
        0,
        0,
        $wheelData,
        0
    )
}

function Get-OperatorFileDescriptor {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    $item = Get-Item -LiteralPath $Path
    return [ordered]@{
        path = $Path.Replace('\', '/')
        bytes = [int64]$item.Length
        sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    }
}

function Write-OperatorMarksAtomic {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Marks,
        [Parameter(Mandatory = $true)][string]$PartialPath
    )

    $tmp = "$PartialPath.$PID.tmp"
    $json = $Marks | ConvertTo-Json -Depth 20
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tmp, $json, $utf8)
    Move-Item -LiteralPath $tmp -Destination $PartialPath -Force
}

function Complete-OperatorMarks {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PartialPath,
        [Parameter(Mandatory = $true)][string]$FinalPath
    )

    if (Test-Path -LiteralPath $FinalPath) {
        throw "Refusing to overwrite existing final operator marks: $FinalPath"
    }
    Move-Item -LiteralPath $PartialPath -Destination $FinalPath
}

function Sleep-OperatorSeconds {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][double]$Seconds)

    if ($Seconds -lt 0) { throw 'Sleep duration cannot be negative' }
    if ($Seconds -gt 0) {
        Start-Sleep -Milliseconds ([int][Math]::Round($Seconds * 1000.0))
    }
}

function Get-ObsRecordButton {
    [CmdletBinding()]
    param([Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process)

    Add-Type -AssemblyName UIAutomationClient -ErrorAction Stop | Out-Null
    $Process.Refresh()
    if ($Process.HasExited -or $Process.MainWindowHandle -eq 0) {
        throw 'OBS does not have a live main window for UI Automation'
    }
    $root = [System.Windows.Automation.AutomationElement]::FromHandle($Process.MainWindowHandle)
    $condition = [System.Windows.Automation.PropertyCondition]::new(
        [System.Windows.Automation.AutomationElement]::AutomationIdProperty,
        'OBSApp.OBSBasic.controlsDock.OBSBasicControls.controlsFrame.recordButton'
    )
    $button = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
    if ($null -eq $button) { throw 'OBS record button was not found by its stable AutomationId' }
    return $button
}

function Invoke-ObsRecordToggle {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][ValidateSet('start','stop')][string]$ExpectedAction
    )

    $button = Get-ObsRecordButton -Process $Process
    $name = [string]$button.Current.Name
    $startName = -join @([char]0x5F00, [char]0x59CB, [char]0x5F55, [char]0x5236)
    $stopName = -join @([char]0x505C, [char]0x6B62, [char]0x5F55, [char]0x5236)
    $expectedNames = if ($ExpectedAction -eq 'start') { @($startName, 'Start Recording') } else { @($stopName, 'Stop Recording') }
    if ($expectedNames -notcontains $name) {
        throw "OBS record button state is '$name'; expected action '$ExpectedAction'"
    }
    $pattern = $button.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
    if ($null -eq $pattern) { throw 'OBS record button does not expose InvokePattern' }
    ([System.Windows.Automation.InvokePattern]$pattern).Invoke()
}

function Wait-ObsRecordState {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][ValidateSet('recording','stopped')][string]$ExpectedState,
        [int]$TimeoutMilliseconds = 5000
    )

    $deadline = [DateTime]::UtcNow.AddMilliseconds($TimeoutMilliseconds)
    $startName = -join @([char]0x5F00, [char]0x59CB, [char]0x5F55, [char]0x5236)
    $stopName = -join @([char]0x505C, [char]0x6B62, [char]0x5F55, [char]0x5236)
    $expectedNames = if ($ExpectedState -eq 'recording') { @($stopName, 'Stop Recording') } else { @($startName, 'Start Recording') }
    do {
        try {
            $button = Get-ObsRecordButton -Process $Process
            if ($expectedNames -contains [string]$button.Current.Name) { return $true }
        }
        catch {
            if ([DateTime]::UtcNow -ge $deadline) { throw }
        }
        Start-Sleep -Milliseconds 150
    } while ([DateTime]::UtcNow -lt $deadline)
    return $false
}
