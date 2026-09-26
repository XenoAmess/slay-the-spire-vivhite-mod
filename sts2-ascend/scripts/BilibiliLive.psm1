Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

if (-not ("BilibiliLiveNative" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class BilibiliLiveNative {
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT { public int X, Y; }

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool GetClientRect(IntPtr hWnd, out RECT rect);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool ClientToScreen(IntPtr hWnd, ref POINT point);

    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindowAsync(IntPtr hWnd, int command);

    [DllImport("user32.dll")]
    public static extern bool IsIconic(IntPtr hWnd);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr insertAfter,
        int x, int y, int width, int height, uint flags);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);

    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll")]
    public static extern bool GetCursorPos(out POINT point);

    [DllImport("user32.dll")]
    public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, UIntPtr extraInfo);

    [DllImport("user32.dll")]
    public static extern void keybd_event(byte virtualKey, byte scanCode, uint flags, UIntPtr extraInfo);

    [DllImport("user32.dll")]
    public static extern IntPtr WindowFromPoint(POINT point);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool PostMessage(IntPtr hWnd, uint message, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetClassName(IntPtr hWnd, System.Text.StringBuilder className, int maxCount);

    [DllImport("user32.dll")]
    public static extern uint GetDpiForWindow(IntPtr hWnd);

    [DllImport("user32.dll", EntryPoint = "GetWindowLongPtr")]
    private static extern IntPtr GetWindowLongPtr64(IntPtr hWnd, int index);

    [DllImport("user32.dll", EntryPoint = "GetWindowLong")]
    private static extern IntPtr GetWindowLong32(IntPtr hWnd, int index);

    public static IntPtr GetWindowLongPtrSafe(IntPtr hWnd, int index) {
        return IntPtr.Size == 8 ? GetWindowLongPtr64(hWnd, index) : GetWindowLong32(hWnd, index);
    }
}
"@
}

$script:LivehimeWindowTitle = [string]([char]0x54D4) + [char]0x54E9 + [char]0x54D4 + [char]0x54E9 + [char]0x76F4 + [char]0x64AD + [char]0x59EC
$script:DefaultLogPath = Join-Path $env:LOCALAPPDATA "Bililive\User Data\bililive_debug.log"
$script:HwndTopMost = [IntPtr](-1)
$script:HwndNoTopMost = [IntPtr](-2)
$script:SwRestore = 9
$script:SwpNoMove = 0x0002
$script:SwpNoSize = 0x0001
$script:SwpNoActivate = 0x0010
$script:SwpShowWindow = 0x0040
$script:MouseLeftDown = 0x0002
$script:MouseLeftUp = 0x0004
$script:KeyUp = 0x0002
$script:VkMenu = 0x12
$script:GwlExStyle = -20
$script:WsExTopMost = 0x00000008
$script:WmClose = 0x0010

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal $identity
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-WindowClassName {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)
    $builder = New-Object Text.StringBuilder 256
    [void][BilibiliLiveNative]::GetClassName($WindowHandle, $builder, $builder.Capacity)
    return $builder.ToString()
}

function Get-LivehimeWindow {
    $candidates = @(Get-Process -Name livehime -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne [IntPtr]::Zero })
    foreach ($candidate in $candidates) {
        $className = Get-WindowClassName -WindowHandle $candidate.MainWindowHandle
        if ($candidate.MainWindowTitle -eq $script:LivehimeWindowTitle -and
            $className -eq "Chrome_WidgetWin_0") {
            return $candidate
        }
    }
    return $null
}

function Wait-LivehimeWindow {
    param(
        [Parameter(Mandatory = $true)][string]$LivehimeExe,
        [ValidateRange(5, 120)][int]$TimeoutSeconds = 30
    )
    $window = Get-LivehimeWindow
    if (-not $window) {
        if (-not (Test-Path -LiteralPath $LivehimeExe)) {
            throw "Bilibili Livehime executable not found: $LivehimeExe"
        }
        Start-Process -FilePath $LivehimeExe -WorkingDirectory (Split-Path $LivehimeExe -Parent) | Out-Null
    }
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $window = Get-LivehimeWindow
        if ($window) { return $window }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "Bilibili Livehime did not expose its main window within $TimeoutSeconds seconds."
}

function ConvertTo-LivehimeState {
    param([Parameter(Mandatory = $true)][int]$StatusCode)
    switch ($StatusCode) {
        0 { return "Idle" }
        2 { return "Starting" }
        3 { return "Starting" }
        5 { return "Streaming" }
        6 { return "Stopping" }
        7 { return "Stopping" }
        default { return "Unknown" }
    }
}

function Get-LivehimeLatestStatusCode {
    param([Parameter(Mandatory = $true)][string]$LogPath)

    $stream = $null
    try {
        $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
        $stream = [IO.File]::Open(
            $LogPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
        [long]$position = $stream.Length
        $laterPrefix = ""
        $pattern = 'set_streaming_status:\s+last_status:\d+\s+set_status:(\d+)'
        while ($position -gt 0) {
            $count = [int][Math]::Min(65536, $position)
            $position -= $count
            [void]$stream.Seek($position, [IO.SeekOrigin]::Begin)
            $buffer = New-Object byte[] $count
            $read = $stream.Read($buffer, 0, $count)
            $chunk = [Text.Encoding]::ASCII.GetString($buffer, 0, $read)
            $candidate = $chunk + $laterPrefix
            $found = [Text.RegularExpressions.Regex]::Matches($candidate, $pattern)
            if ($found.Count -gt 0) {
                return [int]$found[$found.Count - 1].Groups[1].Value
            }
            $laterPrefix = if ($chunk.Length -gt 256) {
                $chunk.Substring(0, 256)
            }
            else {
                $chunk
            }
        }
    }
    catch {
        return $null
    }
    finally {
        if ($stream) { $stream.Dispose() }
    }
    return $null
}

function Get-LivehimeStreamingState {
    param([string]$LogPath = $script:DefaultLogPath)
    if (-not (Get-Process -Name livehime -ErrorAction SilentlyContinue)) {
        return "NotRunning"
    }
    if (-not (Test-Path -LiteralPath $LogPath)) { return "Unknown" }
    $latestCode = Get-LivehimeLatestStatusCode -LogPath $LogPath
    if ($null -eq $latestCode) { return "Unknown" }
    return ConvertTo-LivehimeState -StatusCode $latestCode
}

function Get-BilibiliDailyWindow {
    [CmdletBinding()]
    param(
        [DateTimeOffset]$UtcNow = [DateTimeOffset]::UtcNow,
        [ValidateRange(0, 23)][int]$BeijingHour
    )

    $beijingTimeZone = [TimeZoneInfo]::FindSystemTimeZoneById("China Standard Time")
    $beijingNow = [TimeZoneInfo]::ConvertTime($UtcNow, $beijingTimeZone)
    $startWallClock = [DateTime]::SpecifyKind(
        $beijingNow.Date.AddHours($BeijingHour),
        [DateTimeKind]::Unspecified)
    $windowStart = [DateTimeOffset]::new(
        $startWallClock,
        $beijingTimeZone.GetUtcOffset($startWallClock))
    $windowEnd = $windowStart.AddMinutes(20)
    $inWindow = $beijingNow -ge $windowStart -and $beijingNow -lt $windowEnd
    $slot = if ($inWindow) {
        [int][Math]::Floor(($beijingNow - $windowStart).TotalMinutes)
    }
    else {
        -1
    }

    return [pscustomobject]@{
        BeijingNow = $beijingNow
        WindowStart = $windowStart
        WindowEnd = $windowEnd
        InWindow = [bool]$inWindow
        Slot = [int]$slot
        CheckCount = 20
    }
}

function Get-BilibiliDailyStartWindow {
    [CmdletBinding()]
    param([DateTimeOffset]$UtcNow = [DateTimeOffset]::UtcNow)
    return Get-BilibiliDailyWindow -UtcNow $UtcNow -BeijingHour 23
}

function Get-BilibiliDailyStartSchedule {
    [CmdletBinding()]
    param([DateTimeOffset]$UtcNow = [DateTimeOffset]::UtcNow)

    $window = Get-BilibiliDailyStartWindow -UtcNow $UtcNow
    $nextStart = $window.WindowStart
    # Never back-date a newly registered daily trigger.  The installer starts
    # the task once explicitly when it is installed inside today's window.
    if ($window.BeijingNow -gt $window.WindowStart) {
        $nextStart = $window.WindowStart.AddDays(1)
    }

    return [pscustomobject]@{
        BeijingNow = $window.BeijingNow
        WindowStart = $window.WindowStart
        WindowEnd = $window.WindowEnd
        InWindow = [bool]$window.InWindow
        NextStart = $nextStart
        NextStartUtc = $nextStart.ToUniversalTime()
        NextStartLocal = $nextStart.LocalDateTime
    }
}

function Get-BilibiliDailyStopWindow {
    [CmdletBinding()]
    param([DateTimeOffset]$UtcNow = [DateTimeOffset]::UtcNow)
    return Get-BilibiliDailyWindow -UtcNow $UtcNow -BeijingHour 11
}

function Get-BilibiliDailyStopSchedule {
    [CmdletBinding()]
    param([DateTimeOffset]$UtcNow = [DateTimeOffset]::UtcNow)

    $window = Get-BilibiliDailyStopWindow -UtcNow $UtcNow
    $nextStart = $window.WindowStart
    if ($window.BeijingNow -gt $window.WindowStart) {
        $nextStart = $window.WindowStart.AddDays(1)
    }

    return [pscustomobject]@{
        BeijingNow = $window.BeijingNow
        WindowStart = $window.WindowStart
        WindowEnd = $window.WindowEnd
        InWindow = [bool]$window.InWindow
        NextStart = $nextStart
        NextStartUtc = $nextStart.ToUniversalTime()
        NextStartLocal = $nextStart.LocalDateTime
    }
}

function Test-BilibiliDailyStopRequired {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$State)
    return [string]::Equals($State, "Streaming", [StringComparison]::Ordinal)
}

function Test-BilibiliBridgeInstallSafeState {
    [CmdletBinding()]
    param([AllowEmptyString()][string]$State)
    return $State -in @("Idle", "NotRunning")
}

function Get-LivehimePreferencesPath {
    [CmdletBinding()]
    param([string]$UserDataRoot = (Join-Path $env:LOCALAPPDATA "Bililive\User Data"))
    if (-not (Test-Path -LiteralPath $UserDataRoot -PathType Container)) { return $null }
    $candidates = @(Get-ChildItem -LiteralPath $UserDataRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d+$' } |
        ForEach-Object { Join-Path $_.FullName "Preferences" } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
    if ($candidates.Count -ne 1) { return $null }
    return [IO.Path]::GetFullPath($candidates[0])
}

function Disable-LivehimeSynchronizedRecording {
    [CmdletBinding()]
    param([string]$PreferencesPath = "")
    $state = Get-LivehimeStreamingState
    if (-not (Test-BilibiliBridgeInstallSafeState -State $state)) {
        throw "Refusing to change Livehime synchronized recording while state is '$state'."
    }
    $path = if ([string]::IsNullOrWhiteSpace($PreferencesPath)) {
        Get-LivehimePreferencesPath
    }
    else {
        [IO.Path]::GetFullPath($PreferencesPath)
    }
    if ([string]::IsNullOrWhiteSpace([string]$path) -or
        -not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Could not resolve exactly one Livehime Preferences file."
    }
    $raw = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8)
    try { $parsed = $raw | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "Livehime Preferences is not valid JSON: $path" }
    if (-not $parsed.core -or -not $parsed.core.output -or
        -not $parsed.core.output.PSObject.Properties['recording_sync']) {
        throw "Livehime Preferences has no core.output.recording_sync setting."
    }
    if (-not [bool]$parsed.core.output.recording_sync) {
        return [pscustomobject]@{ Changed = $false; Enabled = $false; Path = $path; BackupPath = "" }
    }
    $pattern = '("recording_sync"\s*:\s*)true'
    $matches = [Text.RegularExpressions.Regex]::Matches(
        $raw, $pattern, [Text.RegularExpressions.RegexOptions]::IgnoreCase)
    if ($matches.Count -ne 1) {
        throw "Expected exactly one enabled recording_sync property; found $($matches.Count)."
    }
    $updated = [Text.RegularExpressions.Regex]::Replace(
        $raw, $pattern, '${1}false', [Text.RegularExpressions.RegexOptions]::IgnoreCase)
    $directory = Split-Path $path -Parent
    $tempPath = Join-Path $directory ("Preferences.vivhite-new-" + [Guid]::NewGuid().ToString("N"))
    $backupPath = Join-Path $directory (
        "Preferences.vivhite-before-recording-off-" +
        [DateTimeOffset]::Now.ToString("yyyyMMdd-HHmmssfff") + ".bak")
    try {
        [IO.File]::WriteAllText($tempPath, $updated, (New-Object Text.UTF8Encoding($false)))
        [IO.File]::Replace($tempPath, $path, $backupPath, $true)
    }
    finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
    $verify = [IO.File]::ReadAllText($path, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if ([bool]$verify.core.output.recording_sync) {
        throw "Livehime synchronized recording remained enabled after the atomic update."
    }
    return [pscustomobject]@{
        Changed = $true
        Enabled = $false
        Path = $path
        BackupPath = $backupPath
    }
}

function Remove-LivehimeDuplicateBrowserSource {
    [CmdletBinding()]
    param([string]$UserDataRoot = (Join-Path $env:LOCALAPPDATA "Bililive\User Data"))
    $state = Get-LivehimeStreamingState
    if (-not (Test-BilibiliBridgeInstallSafeState -State $state)) {
        throw "Refusing to repair Livehime browser sources while state is '$state'."
    }
    $preferencePath = Get-LivehimePreferencesPath -UserDataRoot $UserDataRoot
    if (-not $preferencePath) { throw "Could not resolve Livehime Preferences for scene repair." }
    $accountRoot = Split-Path $preferencePath -Parent
    $jsonFiles = @(Get-ChildItem -LiteralPath $accountRoot -Filter "*.json" -File -Recurse `
        -ErrorAction SilentlyContinue | Where-Object { $_.Name -notmatch '\.bak$' })
    $repairs = @()
    foreach ($file in $jsonFiles) {
        try { $payload = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { continue }
        if ($null -eq $payload -or $payload -is [Array]) { continue }
        $payloadProperties = @($payload.PSObject.Properties | ForEach-Object { $_.Name })
        if ("sources" -notin $payloadProperties -or "current_scene" -notin $payloadProperties) {
            continue
        }
        $sources = @($payload.sources)
        $browsers = @($sources | Where-Object { $_.id -eq "browser_source" })
        if ($browsers.Count -lt 2) { continue }
        $activeScene = $sources | Where-Object { $_.name -eq $payload.current_scene } | Select-Object -First 1
        if (-not $activeScene -or -not $activeScene.settings) { continue }

        for ($i = 0; $i -lt $browsers.Count - 1; $i++) {
            for ($k = $i + 1; $k -lt $browsers.Count; $k++) {
                $first = $browsers[$i]
                $second = $browsers[$k]
                try {
                    $firstUri = [Uri][string]$first.settings.url
                    $secondUri = [Uri][string]$second.settings.url
                }
                catch { continue }
                $firstQuery = @{}
                $secondQuery = @{}
                foreach ($part in $firstUri.Query.TrimStart('?') -split '&') {
                    $pair = $part -split '=', 2
                    if ($pair.Count -eq 2) {
                        $firstQuery[[Uri]::UnescapeDataString($pair[0])] = [Uri]::UnescapeDataString($pair[1])
                    }
                }
                foreach ($part in $secondUri.Query.TrimStart('?') -split '&') {
                    $pair = $part -split '=', 2
                    if ($pair.Count -eq 2) {
                        $secondQuery[[Uri]::UnescapeDataString($pair[0])] = [Uri]::UnescapeDataString($pair[1])
                    }
                }
                $sameIdentity = $firstUri.Scheme -eq $secondUri.Scheme -and
                    $firstUri.Host -eq $secondUri.Host -and
                    $firstUri.AbsolutePath -eq $secondUri.AbsolutePath -and
                    [string]$firstQuery.RoomId -eq [string]$secondQuery.RoomId -and
                    [string]$firstQuery.Mid -eq [string]$secondQuery.Mid -and
                    [string]$firstQuery.Code -eq [string]$secondQuery.Code -and
                    [int]$first.settings.width -eq [int]$second.settings.width -and
                    [int]$first.settings.height -eq [int]$second.settings.height
                if (-not $sameIdentity) { continue }

                $firstOther = [ordered]@{}
                $secondOther = [ordered]@{}
                foreach ($property in $first.settings.PSObject.Properties) {
                    if ($property.Name -notin @("url", "set_url")) { $firstOther[$property.Name] = $property.Value }
                }
                foreach ($property in $second.settings.PSObject.Properties) {
                    if ($property.Name -notin @("url", "set_url")) { $secondOther[$property.Name] = $property.Value }
                }
                if (($firstOther | ConvertTo-Json -Compress -Depth 20) -cne
                    ($secondOther | ConvertTo-Json -Compress -Depth 20)) { continue }

                $firstTimestamp = 0L
                $secondTimestamp = 0L
                [void][long]::TryParse([string]$firstQuery.Timestamp, [ref]$firstTimestamp)
                [void][long]::TryParse([string]$secondQuery.Timestamp, [ref]$secondTimestamp)
                $keep = if ($secondTimestamp -ge $firstTimestamp) { $second } else { $first }
                $remove = if ($keep -eq $second) { $first } else { $second }
                $references = @()
                foreach ($scene in @($sources | Where-Object { $_.id -eq "scene" })) {
                    foreach ($item in @($scene.settings.items)) {
                        if ($item.name -eq $remove.name) {
                            $references += [pscustomobject]@{ Scene = $scene; Item = $item }
                        }
                    }
                }
                if ($references.Count -ne 1 -or $references[0].Scene.name -ne $payload.current_scene) {
                    continue
                }
                $activeScene.settings.items = @($activeScene.settings.items |
                    Where-Object { $_.name -ne $remove.name })
                $payload.sources = @($payload.sources | Where-Object { $_.name -ne $remove.name })
                $repairs += [pscustomobject]@{
                    Path = $file.FullName
                    Payload = $payload
                    Removed = [string]$remove.name
                    Kept = [string]$keep.name
                }
            }
        }
    }
    if ($repairs.Count -eq 0) {
        return [pscustomobject]@{ Changed = $false; Removed = ""; Kept = ""; Path = ""; BackupPath = "" }
    }
    if ($repairs.Count -ne 1) {
        throw "Refusing ambiguous Livehime scene repair: found $($repairs.Count) duplicate groups."
    }
    $repair = $repairs[0]
    $path = [string]$repair.Path
    $directory = Split-Path $path -Parent
    $tempPath = Join-Path $directory ((Split-Path $path -Leaf) + ".vivhite-new-" + [Guid]::NewGuid().ToString("N"))
    $backupPath = Join-Path $directory ((Split-Path $path -Leaf) +
        ".vivhite-before-browser-dedup-" + [DateTimeOffset]::Now.ToString("yyyyMMdd-HHmmssfff") + ".bak")
    try {
        $updated = $repair.Payload | ConvertTo-Json -Compress -Depth 100
        [IO.File]::WriteAllText($tempPath, $updated, (New-Object Text.UTF8Encoding($false)))
        [void](Get-Content -LiteralPath $tempPath -Raw -Encoding UTF8 | ConvertFrom-Json)
        [IO.File]::Replace($tempPath, $path, $backupPath, $true)
    }
    finally {
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
    return [pscustomobject]@{
        Changed = $true
        Removed = [string]$repair.Removed
        Kept = [string]$repair.Kept
        Path = $path
        BackupPath = $backupPath
    }
}

function Test-LivehimeDisplayCaptureStale {
    [CmdletBinding()]
    param(
        [string]$LogPath = $script:DefaultLogPath,
        [ValidateRange(10, 5000)][int]$TailLines = 600,
        [ValidateRange(5, 1000)][int]$MinimumFailures = 30,
        [long]$AfterOffset = -1
    )
    if (-not (Test-Path -LiteralPath $LogPath)) { return $false }
    $lines = if ($AfterOffset -ge 0) {
        $chunk = Get-LivehimeLogTextAfter -LogPath $LogPath -Offset $AfterOffset
        @($chunk -split "`r?`n")
    }
    else {
        @(Get-Content -LiteralPath $LogPath -Tail $TailLines -Encoding UTF8 `
            -ErrorAction SilentlyContinue)
    }
    $failures = @($lines | Where-Object {
            $_ -match 'gs_duplicator_update_frame:\s+Failed to update frame\s+\(887A0001\)'
        })
    return $failures.Count -ge $MinimumFailures
}

function Get-LivehimeLogCheckpoint {
    [CmdletBinding()]
    param([string]$LogPath = $script:DefaultLogPath)
    try {
        if (-not (Test-Path -LiteralPath $LogPath)) { return 0L }
        return [long](Get-Item -LiteralPath $LogPath -ErrorAction Stop).Length
    }
    catch { return 0L }
}

function Get-LivehimeLogTextAfter {
    [CmdletBinding()]
    param(
        [string]$LogPath = $script:DefaultLogPath,
        [ValidateRange(0, [long]::MaxValue)][long]$Offset = 0,
        [ValidateRange(1024, 16777216)][int]$MaximumBytes = 4194304
    )
    $stream = $null
    try {
        $share = [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete
        $stream = [IO.File]::Open(
            $LogPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, $share)
        $length = [long]$stream.Length
        $start = if ($Offset -le $length) { $Offset } else { 0L }
        if ($length - $start -gt $MaximumBytes) { $start = $length - $MaximumBytes }
        [void]$stream.Seek($start, [IO.SeekOrigin]::Begin)
        $count = [int]($length - $start)
        if ($count -le 0) { return "" }
        $buffer = New-Object byte[] $count
        $read = $stream.Read($buffer, 0, $count)
        return [Text.Encoding]::UTF8.GetString($buffer, 0, $read)
    }
    catch { return "" }
    finally { if ($stream) { $stream.Dispose() } }
}

function Get-LivehimeLastRenderLagPercent {
    [CmdletBinding()]
    param(
        [string]$LogPath = $script:DefaultLogPath,
        [ValidateRange(100, 20000)][int]$TailLines = 5000
    )
    try {
        if (-not (Test-Path -LiteralPath $LogPath)) { return $null }
        $pattern = 'Number of lagged frames due to rendering lag/stalls:.*\(([0-9]+(?:\.[0-9]+)?)%\)'
        $matches = @(Get-Content -LiteralPath $LogPath -Tail $TailLines -Encoding UTF8 `
            -ErrorAction Stop | Where-Object { $_ -match $pattern })
        if ($matches.Count -eq 0) { return $null }
        [void]($matches[-1] -match $pattern)
        return [double]::Parse($Matches[1], [Globalization.CultureInfo]::InvariantCulture)
    }
    catch { return $null }
}

function Get-LivehimePrintedWindowBitmap {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)
    Add-Type -AssemblyName System.Drawing
    $rect = New-Object BilibiliLiveNative+RECT
    if (-not [BilibiliLiveNative]::GetWindowRect($WindowHandle, [ref]$rect)) {
        return $null
    }
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    if ($width -lt 1000 -or $height -lt 600) { return $null }
    $bitmap = New-Object Drawing.Bitmap $width, $height
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    $hdc = [IntPtr]::Zero
    try {
        $hdc = $graphics.GetHdc()
        if (-not [BilibiliLiveNative]::PrintWindow($WindowHandle, $hdc, 2)) {
            $bitmap.Dispose()
            return $null
        }
        return $bitmap
    }
    catch {
        $bitmap.Dispose()
        return $null
    }
    finally {
        if ($hdc -ne [IntPtr]::Zero) { $graphics.ReleaseHdc($hdc) }
        $graphics.Dispose()
    }
}

function Measure-LivehimePreviewMotion {
    param(
        [Parameter(Mandatory = $true)][Drawing.Bitmap]$First,
        [Parameter(Mandatory = $true)][Drawing.Bitmap]$Second,
        [ValidateRange(2, 64)][int]$PixelStep = 12,
        [ValidateRange(1, 255)][int]$ColorDelta = 24
    )
    if ($First.Width -ne $Second.Width -or $First.Height -ne $Second.Height) {
        return [pscustomobject]@{ Available = $false; Fresh = $false; ChangedRatio = 0.0; Samples = 0 }
    }
    # Livehime's 16:9 program preview occupies this stable central region.  It
    # excludes the scene list, chat column and bottom controls so UI counters
    # cannot masquerade as moving broadcast content.
    $left = [int][Math]::Floor($First.Width * 0.17)
    $right = [int][Math]::Ceiling($First.Width * 0.83)
    $top = [int][Math]::Floor($First.Height * 0.13)
    $bottom = [int][Math]::Ceiling($First.Height * 0.88)
    $samples = 0
    $changed = 0
    $nonBlack = 0
    for ($y = $top; $y -lt $bottom; $y += $PixelStep) {
        for ($x = $left; $x -lt $right; $x += $PixelStep) {
            $a = $First.GetPixel($x, $y)
            $b = $Second.GetPixel($x, $y)
            $samples++
            if (($a.R + $a.G + $a.B) -gt 12 -or ($b.R + $b.G + $b.B) -gt 12) {
                $nonBlack++
            }
            $delta = [Math]::Abs([int]$a.R - [int]$b.R) +
                [Math]::Abs([int]$a.G - [int]$b.G) +
                [Math]::Abs([int]$a.B - [int]$b.B)
            if ($delta -ge $ColorDelta) { $changed++ }
        }
    }
    $available = $samples -gt 0 -and $nonBlack -ge [Math]::Ceiling($samples * 0.02)
    $ratio = if ($samples -gt 0) { [double]$changed / [double]$samples } else { 0.0 }
    return [pscustomobject]@{
        Available = [bool]$available
        Fresh = [bool]($available -and $ratio -ge 0.002)
        ChangedRatio = $ratio
        Samples = $samples
    }
}

function Test-LivehimePreviewFreshness {
    [CmdletBinding()]
    param(
        [ValidateRange(250, 5000)][int]$SampleDelayMilliseconds = 1500,
        [string]$LogPath = $script:DefaultLogPath
    )
    $window = Get-LivehimeWindow
    if (-not $window) {
        return [pscustomobject]@{ Available = $false; Fresh = $false; ChangedRatio = 0.0; Samples = 0; Reason = "window_missing" }
    }
    $first = Get-LivehimePrintedWindowBitmap -WindowHandle $window.MainWindowHandle
    if (-not $first) {
        return [pscustomobject]@{ Available = $false; Fresh = $false; ChangedRatio = 0.0; Samples = 0; Reason = "print_failed" }
    }
    $second = $null
    try {
        Start-Sleep -Milliseconds $SampleDelayMilliseconds
        if ((Get-LivehimeStreamingState -LogPath $LogPath) -ne "Streaming") {
            return [pscustomobject]@{ Available = $false; Fresh = $false; ChangedRatio = 0.0; Samples = 0; Reason = "state_changed" }
        }
        $second = Get-LivehimePrintedWindowBitmap -WindowHandle $window.MainWindowHandle
        if (-not $second) {
            return [pscustomobject]@{ Available = $false; Fresh = $false; ChangedRatio = 0.0; Samples = 0; Reason = "print_failed" }
        }
        $motion = Measure-LivehimePreviewMotion -First $first -Second $second
        return [pscustomobject]@{
            Available = [bool]$motion.Available
            Fresh = [bool]$motion.Fresh
            ChangedRatio = [double]$motion.ChangedRatio
            Samples = [int]$motion.Samples
            Reason = if ($motion.Fresh) { "fresh" } elseif ($motion.Available) { "stale" } else { "blank" }
        }
    }
    finally {
        $first.Dispose()
        if ($second) { $second.Dispose() }
    }
}

function Get-BilibiliCaptureHealthDecision {
    <#
    Classify one capture-health observation and advance the two independent
    failure counters.  A low-motion preview is not, by itself, proof that
    display capture froze: reward, map and rest screens can legitimately remain
    almost static while an Agent action is being reconciled.  Fast shutdown is
    therefore reserved for low motion corroborated by a new burst of Livehime
    desktop-duplication errors.  Uncorroborated low motion still fails closed,
    but only after a much longer continuous grace window.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][bool]$CaptureBurst,
        [Parameter(Mandatory = $true)][bool]$PreviewAvailable,
        [Parameter(Mandatory = $true)][bool]$PreviewFresh,
        [ValidateRange(0, 100000)][int]$CorroboratedFailureCount = 0,
        [ValidateRange(0, 100000)][int]$LowMotionOnlyCount = 0,
        [ValidateRange(2, 6)][int]$CorroboratedFailureLimit = 3,
        [ValidateRange(12, 360)][int]$LowMotionOnlyLimit = 46
    )

    if ($PreviewAvailable -and $PreviewFresh) {
        return [pscustomobject]@{
            Signal = "Healthy"
            Reason = if ($CaptureBurst) {
                "preview_fresh_despite_capture_errors"
            }
            else {
                "preview_fresh"
            }
            CorroboratedFailureCount = 0
            LowMotionOnlyCount = 0
            ShouldStop = $false
            StopReason = ""
        }
    }

    $previewReason = if ($PreviewAvailable) { "stale" } else { "unavailable" }
    if ($CaptureBurst) {
        $nextCorroborated = $CorroboratedFailureCount + 1
        $shouldStop = $nextCorroborated -ge $CorroboratedFailureLimit
        return [pscustomobject]@{
            Signal = "CorroboratedFailure"
            Reason = "capture_errors_with_$previewReason`_preview"
            CorroboratedFailureCount = $nextCorroborated
            LowMotionOnlyCount = 0
            ShouldStop = $shouldStop
            StopReason = if ($shouldStop) { "corroborated_frozen_capture" } else { "" }
        }
    }

    $nextLowMotion = $LowMotionOnlyCount + 1
    $shouldStop = $nextLowMotion -ge $LowMotionOnlyLimit
    return [pscustomobject]@{
        Signal = "LowMotionOnly"
        Reason = "$previewReason`_preview_without_capture_errors"
        CorroboratedFailureCount = 0
        LowMotionOnlyCount = $nextLowMotion
        ShouldStop = $shouldStop
        StopReason = if ($shouldStop) { "prolonged_low_motion" } else { "" }
    }
}

function Get-BilibiliDataProperty {
    param(
        [AllowNull()][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($null -eq $Object) { return $null }
    if ($Object -is [Collections.IDictionary]) {
        if ($Object.Contains($Name)) {
            Write-Output -NoEnumerate $Object[$Name]
        }
        return
    }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) {
        # Do not let PowerShell flatten one-element action arrays into strings.
        Write-Output -NoEnumerate $property.Value
    }
}

function ConvertTo-BilibiliText {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) {
        Write-Output -NoEnumerate ([string]::Empty)
        return
    }
    return ([string]$Value).Trim()
}

function Test-BilibiliRunId {
    param([AllowNull()][object]$Value)
    $text = ConvertTo-BilibiliText $Value
    return (-not [string]::IsNullOrWhiteSpace($text) -and
        $text -notmatch '^(?i:run_unknown|unknown|none|demo)$')
}

function ConvertTo-BilibiliUtcTimestamp {
    param([AllowNull()][object]$Value)
    $text = ConvertTo-BilibiliText $Value
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    try { return ([DateTimeOffset]::Parse($text)).ToUniversalTime() }
    catch { return $null }
}

function New-BilibiliGameplayEvidence {
    param(
        [bool]$ContextValid,
        [bool]$HasAppliedReceipt,
        [string]$Reason,
        [bool]$HardFailure = $false,
        [bool]$CrossRunTransition = $false,
        [string]$SessionId = "",
        [string]$RunId = "",
        [string]$Screen = "",
        [int]$ApiPort = 0,
        [string]$DecisionId = "",
        [string]$Action = "",
        [string]$OutcomeAt = "",
        [string]$ReceiptSource = "",
        [string]$StateVersion = ""
    )
    return [pscustomobject]@{
        ContextValid = [bool]$ContextValid
        HasAppliedReceipt = [bool]$HasAppliedReceipt
        Reason = [string]$Reason
        HardFailure = [bool]$HardFailure
        CrossRunTransition = [bool]$CrossRunTransition
        SessionId = [string]$SessionId
        RunId = [string]$RunId
        Screen = [string]$Screen
        ApiPort = [int]$ApiPort
        DecisionId = [string]$DecisionId
        Action = [string]$Action
        OutcomeAt = [string]$OutcomeAt
        ReceiptSource = [string]$ReceiptSource
        StateVersion = [string]$StateVersion
    }
}

function Test-BilibiliGameplayEvidence {
    <#
    Validate one local session/API/dashboard observation.  Heartbeats, preview
    motion and state_version only establish that the observation is current;
    they never constitute gameplay progress.  The returned receipt is the
    newest terminal `applied` decision visible in the dashboard.  History row
    `at` is the terminal outcome timestamp emitted by live_dashboard.py.
    #>
    [CmdletBinding()]
    param(
        [AllowNull()][object]$Session,
        [AllowNull()][object]$ApiState,
        [AllowNull()][object]$Dashboard,
        [Parameter(Mandatory = $true)][DateTimeOffset]$NowUtc,
        [ValidateRange(5, 300)][int]$MaxAgeSeconds = 15
    )

    $sessionId = ConvertTo-BilibiliText (Get-BilibiliDataProperty $Session "session_id")
    if ($sessionId -notmatch '^[A-Za-z0-9_-]{8,128}$') {
        return New-BilibiliGameplayEvidence $false $false "session_id_invalid"
    }
    if ((ConvertTo-BilibiliText (Get-BilibiliDataProperty $Session "state")).ToLowerInvariant() -ne "running") {
        return New-BilibiliGameplayEvidence $false $false "session_not_running" `
            -HardFailure $true -SessionId $sessionId
    }

    $api = Get-BilibiliDataProperty $ApiState "Data"
    if ($null -eq $api) {
        return New-BilibiliGameplayEvidence $false $false "api_state_unavailable" -SessionId $sessionId
    }
    $stateVersion = ConvertTo-BilibiliText (Get-BilibiliDataProperty $api "state_version")
    if ($stateVersion -notmatch '^\d+$') {
        return New-BilibiliGameplayEvidence $false $false "state_version_invalid" -SessionId $sessionId
    }
    $screen = (ConvertTo-BilibiliText (Get-BilibiliDataProperty $api "screen")).ToUpperInvariant()
    $apiRunId = ConvertTo-BilibiliText (Get-BilibiliDataProperty $api "run_id")
    $crossRunScreens = @(
        "MAIN_MENU", "CHARACTER_SELECT", "GAME_OVER", "VICTORY", "RUN_COMPLETE"
    )
    if ($crossRunScreens -contains $screen) {
        return New-BilibiliGameplayEvidence $false $false "cross_run_transition" `
            -CrossRunTransition $true -SessionId $sessionId -RunId $apiRunId `
            -Screen $screen -StateVersion $stateVersion
    }
    # The game briefly reports UNKNOWN/WAITING while tearing down GAME_OVER and
    # constructing the next menu/run.  Treat those samples as unverifiable so
    # an already-open cross-run window keeps its original deadline.  They do
    # not establish progress and, outside a transition, still time out after
    # the normal bounded evidence grace.
    $transientScreens = @("", "UNKNOWN", "WAITING")
    if ($transientScreens -contains $screen) {
        return New-BilibiliGameplayEvidence $false $false "transient_screen_unverifiable" `
            -SessionId $sessionId -RunId $apiRunId -Screen $screen -StateVersion $stateVersion
    }
    $hardPassiveScreens = @("TITLE", "PROFILE_SELECT", "RUN_HISTORY", "CREDITS")
    if ($hardPassiveScreens -contains $screen) {
        return New-BilibiliGameplayEvidence $false $false "passive_or_unknown_screen" `
            -HardFailure $true `
            -SessionId $sessionId -Screen $screen -StateVersion $stateVersion
    }
    $apiRun = Get-BilibiliDataProperty $api "run"
    $runCharacterId = ConvertTo-BilibiliText (Get-BilibiliDataProperty $apiRun "character_id")
    $runFloor = Get-BilibiliDataProperty $apiRun "floor"
    if (-not (Test-BilibiliRunId $apiRunId) -or $null -eq $apiRun -or
        $apiRun -is [string] -or $apiRun -is [array] -or
        ([string]::IsNullOrWhiteSpace($runCharacterId) -and $null -eq $runFloor)) {
        return New-BilibiliGameplayEvidence $false $false "active_run_unverifiable" `
            -HardFailure $true `
            -SessionId $sessionId -Screen $screen -StateVersion $stateVersion
    }
    $actions = Get-BilibiliDataProperty $api "available_actions"
    $actionValues = @($actions | ForEach-Object { ([string]$_).Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($null -eq $actions -or $actions -is [string] -or $actionValues.Count -le 0) {
        return New-BilibiliGameplayEvidence $false $false "no_executable_actions" `
            -SessionId $sessionId -RunId $apiRunId -Screen $screen -StateVersion $stateVersion
    }

    if ([string](Get-BilibiliDataProperty $Dashboard "schema") -ne "sts2.ascend-live/v1" -or
        (ConvertTo-BilibiliText (Get-BilibiliDataProperty $Dashboard "session_id")) -ne $sessionId) {
        return New-BilibiliGameplayEvidence $false $false "dashboard_identity_invalid" `
            -SessionId $sessionId -RunId $apiRunId -Screen $screen -StateVersion $stateVersion
    }
    $connection = Get-BilibiliDataProperty $Dashboard "connection"
    if ((ConvertTo-BilibiliText (Get-BilibiliDataProperty $connection "status")).ToLowerInvariant() -ne "connected") {
        return New-BilibiliGameplayEvidence $false $false "dashboard_disconnected" `
            -SessionId $sessionId -RunId $apiRunId -Screen $screen -StateVersion $stateVersion
    }
    $connectionAt = ConvertTo-BilibiliUtcTimestamp (Get-BilibiliDataProperty $connection "at")
    $heartbeatAt = ConvertTo-BilibiliUtcTimestamp (Get-BilibiliDataProperty $Dashboard "heartbeat")
    if ($null -eq $connectionAt -or $null -eq $heartbeatAt) {
        return New-BilibiliGameplayEvidence $false $false "dashboard_timestamp_invalid" `
            -SessionId $sessionId -RunId $apiRunId -Screen $screen -StateVersion $stateVersion
    }
    $connectionAge = ($NowUtc.ToUniversalTime() - $connectionAt).TotalSeconds
    $heartbeatAge = ($NowUtc.ToUniversalTime() - $heartbeatAt).TotalSeconds
    if ($connectionAge -lt -5 -or $connectionAge -gt $MaxAgeSeconds -or
        $heartbeatAge -lt -5 -or $heartbeatAge -gt $MaxAgeSeconds) {
        return New-BilibiliGameplayEvidence $false $false "dashboard_stale" `
            -SessionId $sessionId -RunId $apiRunId -Screen $screen -StateVersion $stateVersion
    }
    $dashRun = Get-BilibiliDataProperty $Dashboard "run"
    $dashRunId = ConvertTo-BilibiliText (Get-BilibiliDataProperty $dashRun "run_id")
    $dashScreen = (ConvertTo-BilibiliText (Get-BilibiliDataProperty $dashRun "screen")).ToUpperInvariant()
    if ($dashRunId -ne $apiRunId -or $dashScreen -ne $screen) {
        return New-BilibiliGameplayEvidence $false $false "api_dashboard_run_mismatch" `
            -SessionId $sessionId -RunId $apiRunId -Screen $screen -StateVersion $stateVersion
    }

    $receipts = @()
    $decision = Get-BilibiliDataProperty $Dashboard "decision"
    $outcome = Get-BilibiliDataProperty $decision "outcome"
    $decisionStatus = (ConvertTo-BilibiliText (Get-BilibiliDataProperty $decision "status")).ToLowerInvariant()
    $outcomeStatus = (ConvertTo-BilibiliText (Get-BilibiliDataProperty $outcome "status")).ToLowerInvariant()
    if ($decisionStatus -eq "applied" -and $outcomeStatus -eq "applied") {
        $selected = Get-BilibiliDataProperty $decision "selected"
        $action = ConvertTo-BilibiliText (Get-BilibiliDataProperty $selected "action")
        if ([string]::IsNullOrWhiteSpace($action)) {
            $action = ConvertTo-BilibiliText (Get-BilibiliDataProperty $decision "action")
        }
        $timestamp = ConvertTo-BilibiliUtcTimestamp (Get-BilibiliDataProperty $outcome "at")
        $decisionId = ConvertTo-BilibiliText (Get-BilibiliDataProperty $decision "decision_id")
        if ($null -ne $timestamp -and -not [string]::IsNullOrWhiteSpace($decisionId) -and
            -not [string]::IsNullOrWhiteSpace($action)) {
            $receipts += [pscustomobject]@{
                DecisionId = $decisionId; Action = $action; Timestamp = $timestamp; Source = "decision.outcome"
            }
        }
    }
    $historyRows = Get-BilibiliDataProperty $Dashboard "history"
    foreach ($row in @($historyRows)) {
        if ((ConvertTo-BilibiliText (Get-BilibiliDataProperty $row "status")).ToLowerInvariant() -ne "applied") {
            continue
        }
        $timestamp = ConvertTo-BilibiliUtcTimestamp (Get-BilibiliDataProperty $row "at")
        $decisionId = ConvertTo-BilibiliText (Get-BilibiliDataProperty $row "decision_id")
        $action = ConvertTo-BilibiliText (Get-BilibiliDataProperty $row "action")
        if ($null -ne $timestamp -and -not [string]::IsNullOrWhiteSpace($decisionId) -and
            -not [string]::IsNullOrWhiteSpace($action)) {
            $receipts += [pscustomobject]@{
                DecisionId = $decisionId; Action = $action; Timestamp = $timestamp; Source = "history.outcome"
            }
        }
    }
    if ($receipts.Count -le 0) {
        return New-BilibiliGameplayEvidence $true $false "no_applied_receipt_visible" `
            -SessionId $sessionId -RunId $apiRunId -Screen $screen `
            -ApiPort ([int](Get-BilibiliDataProperty $ApiState "Port")) -StateVersion $stateVersion
    }
    $latest = @($receipts | Sort-Object -Property Timestamp -Descending)[0]
    return New-BilibiliGameplayEvidence $true $true "applied_receipt_visible" `
        -SessionId $sessionId -RunId $apiRunId -Screen $screen `
        -ApiPort ([int](Get-BilibiliDataProperty $ApiState "Port")) `
        -DecisionId $latest.DecisionId -Action $latest.Action `
        -OutcomeAt $latest.Timestamp.ToString("o") -ReceiptSource $latest.Source `
        -StateVersion $stateVersion
}

function Get-BilibiliGameplayProgressSnapshot {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [int[]]$Ports = (8080..8084),
        [ValidateRange(200, 5000)][int]$TimeoutMilliseconds = 800,
        [ValidateRange(5, 300)][int]$MaxAgeSeconds = 15
    )

    $runtime = Join-Path $ProjectRoot ".runtime"
    $sessionPath = Join-Path $runtime "session.json"
    try {
        $session = Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8 -ErrorAction Stop |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        return New-BilibiliGameplayEvidence $false $false "session_unreadable"
    }
    $sessionId = ConvertTo-BilibiliText (Get-BilibiliDataProperty $session "session_id")
    if ($sessionId -notmatch '^[A-Za-z0-9_-]{8,128}$') {
        return New-BilibiliGameplayEvidence $false $false "session_id_invalid"
    }
    $dashboardPath = Join-Path $runtime ("live_dashboard.{0}.json" -f $sessionId)
    try {
        $dashboardItem = Get-Item -LiteralPath $dashboardPath -ErrorAction Stop
        if (((Get-Date).ToUniversalTime() - $dashboardItem.LastWriteTimeUtc).TotalSeconds -gt $MaxAgeSeconds) {
            return New-BilibiliGameplayEvidence $false $false "dashboard_file_stale" -SessionId $sessionId
        }
        $dashboard = Get-Content -LiteralPath $dashboardPath -Raw -Encoding UTF8 -ErrorAction Stop |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        return New-BilibiliGameplayEvidence $false $false "dashboard_unreadable" -SessionId $sessionId
    }

    $apiState = $null
    foreach ($port in $Ports) {
        $response = $null
        $reader = $null
        try {
            $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$port/state")
            $request.Timeout = $TimeoutMilliseconds
            $request.ReadWriteTimeout = $TimeoutMilliseconds
            $request.Method = "GET"
            $request.Accept = "application/json"
            $response = $request.GetResponse()
            $reader = New-Object IO.StreamReader($response.GetResponseStream())
            $envelope = $reader.ReadToEnd() | ConvertFrom-Json -ErrorAction Stop
            if ((Get-BilibiliDataProperty $envelope "ok") -eq $true -and
                $null -ne (Get-BilibiliDataProperty $envelope "data")) {
                $apiState = [pscustomobject]@{
                    Port = [int]$port
                    Data = Get-BilibiliDataProperty $envelope "data"
                }
                break
            }
        }
        catch { $null = $_ }
        finally {
            if ($reader) { $reader.Dispose() }
            if ($response) { $response.Close() }
        }
    }
    if ($null -eq $apiState) {
        return New-BilibiliGameplayEvidence $false $false "api_state_unavailable" -SessionId $sessionId
    }
    return Test-BilibiliGameplayEvidence -Session $session -ApiState $apiState `
        -Dashboard $dashboard -NowUtc ([DateTimeOffset]::UtcNow) -MaxAgeSeconds $MaxAgeSeconds
}

function Test-BilibiliAppliedActionProgress {
    param(
        [string]$PreviousRunId,
        [string]$PreviousDecisionId,
        [string]$PreviousOutcomeAt,
        [string]$CurrentRunId,
        [string]$CurrentDecisionId,
        [string]$CurrentOutcomeAt
    )
    if (-not (Test-BilibiliRunId $PreviousRunId) -or $CurrentRunId -ne $PreviousRunId -or
        [string]::IsNullOrWhiteSpace($PreviousDecisionId) -or
        [string]::IsNullOrWhiteSpace($CurrentDecisionId) -or
        $CurrentDecisionId -eq $PreviousDecisionId) {
        return $false
    }
    $previousAt = ConvertTo-BilibiliUtcTimestamp $PreviousOutcomeAt
    $currentAt = ConvertTo-BilibiliUtcTimestamp $CurrentOutcomeAt
    return ($null -ne $previousAt -and $null -ne $currentAt -and $currentAt -gt $previousAt)
}

function Get-BilibiliGameplayHealthDecision {
    <#
    Advance the independent semantic-progress clock.  A preview becoming fresh
    is intentionally absent from this API: pixels must never reset evidence of
    a Brain/game livelock.  Natural end-of-run/menu screens start a bounded
    transition window.  The next run's first applied receipt establishes its
    baseline and starts a shorter proof window; only a later, distinct applied
    receipt in that run ends the transition and resets the normal stall clock.
    #>
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][object]$Evidence,
        [AllowEmptyString()][string]$PreviousRunId = "",
        [AllowEmptyString()][string]$PreviousDecisionId = "",
        [AllowEmptyString()][string]$PreviousOutcomeAt = "",
        [AllowEmptyString()][string]$PreviousTransitionStartedAt = "",
        [AllowEmptyString()][string]$PreviousTransitionProofStartedAt = "",
        [Parameter(Mandatory = $true)][DateTimeOffset]$LastProgressAtUtc,
        [Parameter(Mandatory = $true)][DateTimeOffset]$NowUtc,
        [ValidateRange(30, 600)][int]$StallTimeoutSeconds = 90,
        [ValidateRange(60, 600)][int]$CrossRunTimeoutSeconds = 120,
        [ValidateRange(10, 120)][int]$CrossRunProofTimeoutSeconds = 30
    )

    $state = "Waiting"
    $reason = [string](Get-BilibiliDataProperty $Evidence "Reason")
    $contextValid = (Get-BilibiliDataProperty $Evidence "ContextValid") -eq $true
    $hasReceipt = (Get-BilibiliDataProperty $Evidence "HasAppliedReceipt") -eq $true
    $hardFailure = (Get-BilibiliDataProperty $Evidence "HardFailure") -eq $true
    $crossRunTransition = (Get-BilibiliDataProperty $Evidence "CrossRunTransition") -eq $true
    $nextRunId = $PreviousRunId
    $nextDecisionId = $PreviousDecisionId
    $nextOutcomeAt = $PreviousOutcomeAt
    $nextProgressAt = $LastProgressAtUtc.ToUniversalTime()
    $transitionStartedAt = ConvertTo-BilibiliUtcTimestamp $PreviousTransitionStartedAt
    $transitionProofStartedAt = ConvertTo-BilibiliUtcTimestamp $PreviousTransitionProofStartedAt
    $nowUniversal = $NowUtc.ToUniversalTime()
    $transitionEntryExpired = ($null -ne $transitionStartedAt -and
        $null -eq $transitionProofStartedAt -and
        ($nowUniversal - $transitionStartedAt.ToUniversalTime()).TotalSeconds -ge $CrossRunTimeoutSeconds)
    $transitionProofExpired = ($null -ne $transitionProofStartedAt -and
        ($nowUniversal - $transitionProofStartedAt.ToUniversalTime()).TotalSeconds -ge $CrossRunProofTimeoutSeconds)

    if ($hardFailure) {
        $state = "HardFailure"
    }
    elseif ($crossRunTransition) {
        $state = "Transition"
        if ($null -eq $transitionStartedAt) {
            $transitionStartedAt = $NowUtc.ToUniversalTime()
        }
    }
    elseif (-not $contextValid -and $null -ne $transitionStartedAt) {
        $state = "Transition"
        $reason = "cross_run_evidence_pending"
    }
    elseif (-not $contextValid) {
        $state = "Unverifiable"
    }
    elseif (-not $hasReceipt -and $null -ne $transitionStartedAt) {
        $state = "Transition"
        $reason = "cross_run_applied_receipt_pending"
    }
    elseif (-not $hasReceipt) {
        $state = "Waiting"
    }
    else {
        $currentRunId = ConvertTo-BilibiliText (Get-BilibiliDataProperty $Evidence "RunId")
        $currentDecisionId = ConvertTo-BilibiliText (Get-BilibiliDataProperty $Evidence "DecisionId")
        $currentOutcomeAt = ConvertTo-BilibiliText (Get-BilibiliDataProperty $Evidence "OutcomeAt")
        if (-not (Test-BilibiliRunId $PreviousRunId) -or $currentRunId -ne $PreviousRunId) {
            if ($transitionEntryExpired) {
                $state = "Transition"
                $reason = "cross_run_first_applied_receipt_too_late"
            }
            elseif ($null -ne $transitionStartedAt) {
                $state = "Transition"
                $reason = "cross_run_baseline_established"
                if ($null -eq $transitionProofStartedAt) {
                    $transitionProofStartedAt = $nowUniversal
                }
                $nextRunId = $currentRunId
                $nextDecisionId = $currentDecisionId
                $nextOutcomeAt = $currentOutcomeAt
            }
            else {
                $state = "Baseline"
                $reason = "applied_baseline_established"
                $nextProgressAt = $nowUniversal
                $nextRunId = $currentRunId
                $nextDecisionId = $currentDecisionId
                $nextOutcomeAt = $currentOutcomeAt
            }
        }
        elseif (Test-BilibiliAppliedActionProgress `
                -PreviousRunId $PreviousRunId -PreviousDecisionId $PreviousDecisionId `
                -PreviousOutcomeAt $PreviousOutcomeAt -CurrentRunId $currentRunId `
                -CurrentDecisionId $currentDecisionId -CurrentOutcomeAt $currentOutcomeAt) {
            if ($transitionProofExpired) {
                $state = "Transition"
                $reason = "cross_run_second_applied_receipt_too_late"
            }
            else {
                $state = "Progressed"
                $reason = "new_applied_receipt"
                $nextRunId = $currentRunId
                $nextDecisionId = $currentDecisionId
                $nextOutcomeAt = $currentOutcomeAt
                $nextProgressAt = $nowUniversal
                $transitionStartedAt = $null
                $transitionProofStartedAt = $null
            }
        }
        elseif ($null -ne $transitionStartedAt) {
            $state = "Transition"
            $reason = "cross_run_second_applied_receipt_pending"
        }
    }

    $effectiveTimeoutSeconds = $StallTimeoutSeconds
    $elapsedFrom = if ($state -eq "Transition" -and $null -ne $transitionProofStartedAt) {
        $effectiveTimeoutSeconds = $CrossRunProofTimeoutSeconds
        $transitionProofStartedAt
    }
    elseif ($state -eq "Transition" -and $null -ne $transitionStartedAt) {
        $effectiveTimeoutSeconds = $CrossRunTimeoutSeconds
        $transitionStartedAt
    }
    else {
        $nextProgressAt
    }
    $elapsed = [Math]::Max(0.0,
        ($NowUtc.ToUniversalTime() - $elapsedFrom.ToUniversalTime()).TotalSeconds)
    $shouldStop = $hardFailure -or $elapsed -ge $effectiveTimeoutSeconds
    $stopReason = ""
    if ($shouldStop) {
        $stopReason = if ($state -eq "HardFailure") {
            "unsafe_gameplay_state"
        }
        elseif ($state -eq "Transition") {
            "cross_run_transition_timeout"
        }
        elseif ($state -eq "Unverifiable") {
            "gameplay_evidence_unavailable"
        }
        else {
            "semantic_gameplay_stall"
        }
    }
    return [pscustomobject]@{
        State = $state
        Reason = $reason
        PreviousRunId = $nextRunId
        PreviousDecisionId = $nextDecisionId
        PreviousOutcomeAt = $nextOutcomeAt
        TransitionStartedAt = if ($null -eq $transitionStartedAt) { "" } else { $transitionStartedAt.ToString("o") }
        TransitionProofStartedAt = if ($null -eq $transitionProofStartedAt) { "" } else { $transitionProofStartedAt.ToString("o") }
        LastProgressAtUtc = $nextProgressAt
        ElapsedSeconds = [double]$elapsed
        TimeoutSeconds = [int]$effectiveTimeoutSeconds
        ShouldStop = [bool]$shouldStop
        StopReason = $stopReason
    }
}

function Restart-LivehimeIdle {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$LivehimeExe,
        [ValidateRange(5, 60)][int]$TimeoutSeconds = 15,
        [string]$LogPath = $script:DefaultLogPath,
        [switch]$DisableSynchronizedRecording,
        [switch]$RemoveDuplicateBrowserSource
    )

    $state = Get-LivehimeStreamingState -LogPath $LogPath
    if ($state -notin @("Idle", "NotRunning")) {
        throw "Refusing to restart Livehime while its streaming state is '$state'."
    }
    $window = Get-LivehimeWindow
    if ($window) {
        $processId = [int]$window.Id
        $closeRequested = $window.CloseMainWindow()
        if (-not $closeRequested) {
            $closeRequested = [BilibiliLiveNative]::PostMessage(
                $window.MainWindowHandle, $script:WmClose, [IntPtr]::Zero, [IntPtr]::Zero)
        }
        if (-not $closeRequested) {
            throw "Livehime rejected its normal close request; no process was terminated."
        }
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        do {
            Start-Sleep -Milliseconds 250
            $sameProcess = Get-Process -Id $processId -ErrorAction SilentlyContinue
        } while ($sameProcess -and (Get-Date) -lt $deadline)
        if ($sameProcess) {
            throw "Livehime process did not exit after its normal close request; no process was terminated."
        }
    }
    if (-not (Test-Path -LiteralPath $LivehimeExe)) {
        throw "Bilibili Livehime executable not found: $LivehimeExe"
    }
    if ($DisableSynchronizedRecording) {
        [void](Disable-LivehimeSynchronizedRecording)
    }
    if ($RemoveDuplicateBrowserSource) {
        [void](Remove-LivehimeDuplicateBrowserSource)
    }
    Start-Process -FilePath $LivehimeExe -WorkingDirectory (Split-Path $LivehimeExe -Parent) | Out-Null
    return Wait-LivehimeWindow -LivehimeExe $LivehimeExe -TimeoutSeconds $TimeoutSeconds
}

function Wait-LivehimeStreamingState {
    param(
        [Parameter(Mandatory = $true)][string[]]$DesiredState,
        [ValidateRange(2, 120)][int]$TimeoutSeconds = 25,
        [string]$LogPath = $script:DefaultLogPath
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $state = Get-LivehimeStreamingState -LogPath $LogPath
        if ($DesiredState -contains $state) { return $state }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "Bilibili Livehime state did not become [$($DesiredState -join ', ')] within $TimeoutSeconds seconds; current state is $state."
}

function Get-WindowSnapshot {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)
    $client = New-Object BilibiliLiveNative+RECT
    if (-not [BilibiliLiveNative]::GetClientRect($WindowHandle, [ref]$client)) {
        throw "GetClientRect failed for window $WindowHandle."
    }
    $origin = New-Object BilibiliLiveNative+POINT
    if (-not [BilibiliLiveNative]::ClientToScreen($WindowHandle, [ref]$origin)) {
        throw "ClientToScreen failed for window $WindowHandle."
    }
    $width = $client.Right - $client.Left
    $height = $client.Bottom - $client.Top
    if ($width -lt 1000 -or $height -lt 650) {
        throw "Bilibili Livehime window is too small for calibrated automation: ${width}x${height}."
    }
    $dpi = [BilibiliLiveNative]::GetDpiForWindow($WindowHandle)
    if ($dpi -le 0) { $dpi = 96 }
    return [pscustomobject]@{
        X = $origin.X
        Y = $origin.Y
        Width = $width
        Height = $height
        Scale = ([double]$dpi / 96.0)
    }
}

function Invoke-WindowProcessActivation {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)

    [uint32]$targetPid = 0
    [void][BilibiliLiveNative]::GetWindowThreadProcessId($WindowHandle, [ref]$targetPid)
    if ($targetPid -le 0) { return $false }

    $automationShell = $null
    try {
        # SetForegroundWindow is routinely denied when the public entrypoint is
        # launched from Codex/Task Scheduler instead of the foreground process.
        # WScript.AppActivate asks Windows to activate the exact owning process;
        # the caller still verifies the exact HWND before accepting success.
        $automationShell = New-Object -ComObject WScript.Shell
        return [bool]$automationShell.AppActivate([int]$targetPid)
    }
    catch {
        Write-Verbose "WScript.AppActivate failed for window $WindowHandle (pid $targetPid): $($_.Exception.Message)"
        return $false
    }
    finally {
        if ($null -ne $automationShell) {
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($automationShell)
        }
    }
}

function Set-WindowAutomationForeground {
    param(
        [Parameter(Mandatory = $true)][IntPtr]$WindowHandle,
        [switch]$TopMost
    )
    if ([BilibiliLiveNative]::IsIconic($WindowHandle)) {
        [void][BilibiliLiveNative]::ShowWindowAsync($WindowHandle, $script:SwRestore)
        Start-Sleep -Milliseconds 250
    }
    if ($TopMost) {
        $flags = $script:SwpNoMove -bor $script:SwpNoSize -bor $script:SwpShowWindow
        if (-not [BilibiliLiveNative]::SetWindowPos($WindowHandle, $script:HwndTopMost, 0, 0, 0, 0, $flags)) {
            throw "SetWindowPos(HWND_TOPMOST) failed for window $WindowHandle."
        }
    }
    [void][BilibiliLiveNative]::BringWindowToTop($WindowHandle)
    [void][BilibiliLiveNative]::SetForegroundWindow($WindowHandle)
    Start-Sleep -Milliseconds 200
    if ([BilibiliLiveNative]::GetForegroundWindow() -ne $WindowHandle) {
        [BilibiliLiveNative]::keybd_event($script:VkMenu, 0, 0, [UIntPtr]::Zero)
        try {
            [void][BilibiliLiveNative]::BringWindowToTop($WindowHandle)
            [void][BilibiliLiveNative]::SetForegroundWindow($WindowHandle)
        }
        finally {
            [BilibiliLiveNative]::keybd_event($script:VkMenu, 0, $script:KeyUp, [UIntPtr]::Zero)
        }
        Start-Sleep -Milliseconds 200
    }
    if ([BilibiliLiveNative]::GetForegroundWindow() -ne $WindowHandle) {
        [void](Invoke-WindowProcessActivation -WindowHandle $WindowHandle)
        Start-Sleep -Milliseconds 250
    }
    if ([BilibiliLiveNative]::GetForegroundWindow() -ne $WindowHandle) {
        throw "Could not make window $WindowHandle the foreground window. Run from an interactive desktop session."
    }
    if ($TopMost) {
        # Activation can reorder or clear the TOPMOST band (the game does this
        # during its own focus transition), so make TOPMOST the final mutation.
        $flags = $script:SwpNoMove -bor $script:SwpNoSize -bor $script:SwpShowWindow
        if (-not [BilibiliLiveNative]::SetWindowPos(
                $WindowHandle, $script:HwndTopMost, 0, 0, 0, 0, $flags)) {
            throw "SetWindowPos(HWND_TOPMOST) failed after activating window $WindowHandle."
        }
    }
}

function Set-WindowNotTopMost {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)
    $flags = $script:SwpNoMove -bor $script:SwpNoSize -bor $script:SwpShowWindow
    [void][BilibiliLiveNative]::SetWindowPos($WindowHandle, $script:HwndNoTopMost, 0, 0, 0, 0, $flags)
}

function Assert-LivehimePoint {
    param([Parameter(Mandatory = $true)][int]$X, [Parameter(Mandatory = $true)][int]$Y)
    $point = New-Object BilibiliLiveNative+POINT
    $point.X = $X
    $point.Y = $Y
    $target = [BilibiliLiveNative]::WindowFromPoint($point)
    if ($target -eq [IntPtr]::Zero) { throw "No window exists at Livehime automation point ($X,$Y)." }
    [uint32]$targetPid = 0
    [void][BilibiliLiveNative]::GetWindowThreadProcessId($target, [ref]$targetPid)
    $targetProcess = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
    if (-not $targetProcess -or $targetProcess.ProcessName -ne "livehime") {
        $name = if ($targetProcess) { $targetProcess.ProcessName } else { "unknown" }
        throw "Livehime automation point ($X,$Y) is covered by process '$name' (pid $targetPid)."
    }
}

function Invoke-LivehimeClick {
    param([Parameter(Mandatory = $true)][int]$X, [Parameter(Mandatory = $true)][int]$Y)
    Assert-LivehimePoint -X $X -Y $Y
    $previous = New-Object BilibiliLiveNative+POINT
    [void][BilibiliLiveNative]::GetCursorPos([ref]$previous)
    try {
        if (-not [BilibiliLiveNative]::SetCursorPos($X, $Y)) { throw "SetCursorPos failed." }
        Start-Sleep -Milliseconds 100
        [BilibiliLiveNative]::mouse_event($script:MouseLeftDown, 0, 0, 0, [UIntPtr]::Zero)
        Start-Sleep -Milliseconds 80
        [BilibiliLiveNative]::mouse_event($script:MouseLeftUp, 0, 0, 0, [UIntPtr]::Zero)
    }
    finally {
        Start-Sleep -Milliseconds 100
        [void][BilibiliLiveNative]::SetCursorPos($previous.X, $previous.Y)
    }
}

function Invoke-WinRtAsync {
    param(
        [Parameter(Mandatory = $true)]$Operation,
        [Parameter(Mandatory = $true)][Type]$ResultType,
        [ValidateRange(1, 30)][int]$TimeoutSeconds = 5
    )
    $method = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object { $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    if (-not $task.Wait([TimeSpan]::FromSeconds($TimeoutSeconds))) {
        throw "WinRT operation timed out after $TimeoutSeconds seconds."
    }
    return $task.Result
}

function Get-LivehimeScreenText {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)
    $snapshot = Get-WindowSnapshot -WindowHandle $WindowHandle
    $tempPath = Join-Path ([IO.Path]::GetTempPath()) ("sts2-bilibili-" + [Guid]::NewGuid().ToString("N") + ".png")
    Add-Type -AssemblyName System.Drawing, System.Windows.Forms
    $bitmap = New-Object Drawing.Bitmap $snapshot.Width, $snapshot.Height
    $graphics = [Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($snapshot.X, $snapshot.Y, 0, 0, $bitmap.Size)
        $bitmap.Save($tempPath, [Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
    $stream = $null
    try {
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
        $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType=WindowsRuntime]
        $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
        $null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
        $file = Invoke-WinRtAsync ([Windows.Storage.StorageFile]::GetFileFromPathAsync($tempPath)) ([Windows.Storage.StorageFile])
        $stream = Invoke-WinRtAsync ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Invoke-WinRtAsync ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $softwareBitmap = Invoke-WinRtAsync ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $language = New-Object Windows.Globalization.Language "zh-Hans"
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
        if (-not $engine) { return "" }
        $result = Invoke-WinRtAsync ($engine.RecognizeAsync($softwareBitmap)) ([Windows.Media.Ocr.OcrResult])
        return ([string]$result.Text -replace '\s', '')
    }
    catch {
        Write-Verbose "Livehime OCR unavailable: $($_.Exception.Message)"
        return ""
    }
    finally {
        if ($stream) { $stream.Dispose() }
        Remove-Item -LiteralPath $tempPath -Force -ErrorAction SilentlyContinue
    }
}

function Test-LivehimeCloseGlyph {
    param(
        [Parameter(Mandatory = $true)][Drawing.Bitmap]$Bitmap,
        [Parameter(Mandatory = $true)][int]$CenterX,
        [Parameter(Mandatory = $true)][int]$CenterY,
        [ValidateRange(0.5, 4.0)][double]$Scale = 1.0
    )

    function Get-LuminanceAt {
        param([int]$Dx, [int]$Dy)
        $x = $CenterX + [int][Math]::Round($Dx * $Scale)
        $y = $CenterY + [int][Math]::Round($Dy * $Scale)
        if ($x -lt 0 -or $y -lt 0 -or $x -ge $Bitmap.Width -or $y -ge $Bitmap.Height) {
            throw "Close-glyph sample falls outside the bitmap."
        }
        $color = $Bitmap.GetPixel($x, $y)
        return ($color.R + $color.G + $color.B) / 3.0
    }

    $backgroundOffsets = @(
        @(-10, 0), @(10, 0), @(0, -10), @(0, 10),
        @(-9, -9), @(9, -9), @(-9, 9), @(9, 9)
    )
    $background = ($backgroundOffsets | ForEach-Object {
        Get-LuminanceAt -Dx $_[0] -Dy $_[1]
    } | Measure-Object -Average).Average
    $arms = @(
        @(@(-6, -6), @(-4, -4), @(-2, -2)),
        @(@(2, 2), @(4, 4), @(6, 6)),
        @(@(6, -6), @(4, -4), @(2, -2)),
        @(@(-2, 2), @(-4, 4), @(-6, 6))
    )
    foreach ($arm in $arms) {
        $average = ($arm | ForEach-Object {
            Get-LuminanceAt -Dx $_[0] -Dy $_[1]
        } | Measure-Object -Average).Average
        if ($average -lt $background + 20) { return $false }
    }
    return $true
}

function Test-LivehimeCloseGlyphNear {
    param(
        [Parameter(Mandatory = $true)][Drawing.Bitmap]$Bitmap,
        [Parameter(Mandatory = $true)][int]$CenterX,
        [Parameter(Mandatory = $true)][int]$CenterY,
        [ValidateRange(0.5, 4.0)][double]$Scale = 1.0
    )
    foreach ($dy in -2..2) {
        foreach ($dx in -2..2) {
            $sampleX = $CenterX + [int][Math]::Round($dx * $Scale)
            $sampleY = $CenterY + [int][Math]::Round($dy * $Scale)
            if (Test-LivehimeCloseGlyph -Bitmap $Bitmap -CenterX $sampleX `
                    -CenterY $sampleY -Scale $Scale) {
                return $true
            }
        }
    }
    return $false
}

function Test-LivehimeWideEndedDialogExpected {
    param([string]$LogPath = $script:DefaultLogPath)
    if (-not (Test-Path -LiteralPath $LogPath)) { return $false }
    try {
        $tail = [string]::Join("`n", @(Get-Content -LiteralPath $LogPath -Tail 6000 -Encoding UTF8 `
            -ErrorAction Stop))
        $startupIndex = $tail.LastIndexOf("--- Application Startup ---", [StringComparison]::Ordinal)
        $dialogIndex = $tail.LastIndexOf("LiveStopDialog::ShowWindow", [StringComparison]::Ordinal)
        return $startupIndex -ge 0 -and $dialogIndex -gt $startupIndex
    }
    catch {
        Write-Verbose "Livehime ended-dialog log check unavailable: $($_.Exception.Message)"
        return $false
    }
}

function Get-LivehimeEndedDialogClosePoint {
    param(
        [Parameter(Mandatory = $true)][IntPtr]$WindowHandle,
        [switch]$AllowWide
    )
    $snapshot = Get-WindowSnapshot -WindowHandle $WindowHandle
    # LiveStopDialog has shipped in two widths on this host.  The compact
    # result dialog closes near center+318; the current wide result dialog
    # closes near center+615.  Search only small calibrated header boxes and
    # still require the complete four-arm X, so unrelated red controls can
    # never authorize a click.
    $candidates = @(
        [pscustomobject]@{
            X = $snapshot.X + [int]($snapshot.Width * 0.5 + 318 * $snapshot.Scale)
            Y = $snapshot.Y + [int](132 * $snapshot.Scale)
            SearchRadius = [int][Math]::Ceiling(4 * $snapshot.Scale)
        }
    )
    if ($AllowWide) {
        $candidates += [pscustomobject]@{
            X = $snapshot.X + [int]($snapshot.Width * 0.5 + 615 * $snapshot.Scale)
            Y = $snapshot.Y + [int](136 * $snapshot.Scale)
            SearchRadius = [int][Math]::Ceiling(20 * $snapshot.Scale)
        }
    }
    Add-Type -AssemblyName System.Drawing
    foreach ($candidate in $candidates) {
        $glyphRadius = [int][Math]::Ceiling(11 * $snapshot.Scale)
        $captureRadius = $candidate.SearchRadius + $glyphRadius
        if ($candidate.X - $captureRadius -lt $snapshot.X -or
            $candidate.Y - $captureRadius -lt $snapshot.Y -or
            $candidate.X + $captureRadius -ge $snapshot.X + $snapshot.Width -or
            $candidate.Y + $captureRadius -ge $snapshot.Y + $snapshot.Height) {
            continue
        }
        $size = 2 * $captureRadius + 1
        $bitmap = New-Object Drawing.Bitmap $size, $size
        $graphics = [Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.CopyFromScreen(
                $candidate.X - $captureRadius, $candidate.Y - $captureRadius,
                0, 0, $bitmap.Size)
            for ($dy = -$candidate.SearchRadius; $dy -le $candidate.SearchRadius; $dy++) {
                for ($dx = -$candidate.SearchRadius; $dx -le $candidate.SearchRadius; $dx++) {
                    if (Test-LivehimeCloseGlyph -Bitmap $bitmap `
                            -CenterX ($captureRadius + $dx) `
                            -CenterY ($captureRadius + $dy) -Scale $snapshot.Scale) {
                        return [pscustomobject]@{
                            X = [int]($candidate.X + $dx)
                            Y = [int]($candidate.Y + $dy)
                        }
                    }
                }
            }
        }
        catch {
            Write-Verbose "Livehime ended-dialog pixel check unavailable: $($_.Exception.Message)"
        }
        finally {
            $graphics.Dispose()
            $bitmap.Dispose()
        }
    }
    return $null
}

function Test-LivehimeEndedDialogCloseButton {
    param(
        [Parameter(Mandatory = $true)][IntPtr]$WindowHandle,
        [string]$LogPath = $script:DefaultLogPath
    )
    $allowWide = Test-LivehimeWideEndedDialogExpected -LogPath $LogPath
    return ($null -ne (Get-LivehimeEndedDialogClosePoint -WindowHandle $WindowHandle `
        -AllowWide:$allowWide))
}

function Close-LivehimeIdleDialogs {
    param(
        [Parameter(Mandatory = $true)][IntPtr]$WindowHandle,
        [string]$LogPath = $script:DefaultLogPath
    )
    $snapshot = Get-WindowSnapshot -WindowHandle $WindowHandle
    $endedText = [string]([char]0x76F4) + [char]0x64AD + [char]0x5DF2 + [char]0x7ED3 + [char]0x675F
    # The ended/violation dialog has a stable close glyph.  Check it before
    # invoking WinRT OCR so a broken OCR broker can never block the Start path.
    $allowWide = Test-LivehimeWideEndedDialogExpected -LogPath $LogPath
    $closePoint = Get-LivehimeEndedDialogClosePoint -WindowHandle $WindowHandle `
        -AllowWide:$allowWide
    if ($null -ne $closePoint) {
        Invoke-LivehimeClick -X $closePoint.X -Y $closePoint.Y
        Start-Sleep -Milliseconds 600
        return
    }
    $text = Get-LivehimeScreenText -WindowHandle $WindowHandle
    if ($text -match $endedText) {
        $closeX = $snapshot.X + [int]($snapshot.Width * 0.5 + 318 * $snapshot.Scale)
        $closeY = $snapshot.Y + [int](130 * $snapshot.Scale)
        Invoke-LivehimeClick -X $closeX -Y $closeY
        Start-Sleep -Milliseconds 600
        return
    }
    if ($text -match [string]([char]0x5904) + [char]0x7F5A + [char]0x7ED3 + [char]0x679C -or
        $text -match [string]([char]0x5904) + [char]0x7F5A + [char]0x65F6 + [char]0x95F4 -or
        $text -match [string]([char]0x5904) + [char]0x7F5A + [char]0x4E2D + [char]0x5FC3) {
        $ackX = $snapshot.X + [int]($snapshot.Width * 0.5)
        $ackY = $snapshot.Y + [int]($snapshot.Height * 0.625)
        Invoke-LivehimeClick -X $ackX -Y $ackY
        Start-Sleep -Milliseconds 600
        $text = Get-LivehimeScreenText -WindowHandle $WindowHandle
    }
    if ($text -match $endedText) {
        $closeX = $snapshot.X + [int]($snapshot.Width * 0.5 + 318 * $snapshot.Scale)
        $closeY = $snapshot.Y + [int](130 * $snapshot.Scale)
        Invoke-LivehimeClick -X $closeX -Y $closeY
        Start-Sleep -Milliseconds 600
    }
}

function Get-LivehimeTogglePoint {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)
    $snapshot = Get-WindowSnapshot -WindowHandle $WindowHandle
    return [pscustomobject]@{
        X = $snapshot.X + $snapshot.Width - [int](351 * $snapshot.Scale)
        Y = $snapshot.Y + $snapshot.Height - [int](69 * $snapshot.Scale)
    }
}

function Test-LivehimeStartButton {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)
    $point = Get-LivehimeTogglePoint -WindowHandle $WindowHandle
    Add-Type -AssemblyName System.Drawing
    foreach ($dx in @(-40, -20, 0, 20, 40)) {
        foreach ($dy in @(-10, 10)) {
            $bitmap = New-Object Drawing.Bitmap 1, 1
            $graphics = [Drawing.Graphics]::FromImage($bitmap)
            try {
                $graphics.CopyFromScreen($point.X + $dx, $point.Y + $dy, 0, 0, $bitmap.Size)
                $color = $bitmap.GetPixel(0, 0)
                if ($color.R -lt 230 -or $color.G -lt 60 -or $color.G -gt 170 -or
                    $color.B -lt 100 -or $color.B -gt 210 -or ($color.R - $color.G) -lt 70) {
                    return $false
                }
            }
            finally {
                $graphics.Dispose()
                $bitmap.Dispose()
            }
        }
    }
    return $true
}

function Invoke-LivehimeStart {
    param(
        [Parameter(Mandatory = $true)][string]$LivehimeExe,
        [ValidateRange(5, 120)][int]$TimeoutSeconds = 25,
        [string]$LogPath = $script:DefaultLogPath
    )
    $window = Wait-LivehimeWindow -LivehimeExe $LivehimeExe
    $state = Get-LivehimeStreamingState -LogPath $LogPath
    if ($state -eq "Streaming") {
        Write-Host "Bilibili Livehime is already streaming."
        return
    }
    if ($state -eq "Starting") {
        [void](Wait-LivehimeStreamingState -DesiredState "Streaming" -TimeoutSeconds $TimeoutSeconds -LogPath $LogPath)
        return
    }
    if ($state -eq "Stopping") {
        [void](Wait-LivehimeStreamingState -DesiredState "Idle" -TimeoutSeconds $TimeoutSeconds -LogPath $LogPath)
    }
    elseif ($state -notin @("Idle", "NotRunning", "Unknown")) {
        throw "Refusing to click Livehime while its streaming state is '$state'."
    }
    Set-WindowAutomationForeground -WindowHandle $window.MainWindowHandle -TopMost
    try {
        Close-LivehimeIdleDialogs -WindowHandle $window.MainWindowHandle -LogPath $LogPath
        if (-not (Test-LivehimeStartButton -WindowHandle $window.MainWindowHandle)) {
            throw "The calibrated Livehime start button was not detected. No click was sent."
        }
        $point = Get-LivehimeTogglePoint -WindowHandle $window.MainWindowHandle
        Invoke-LivehimeClick -X $point.X -Y $point.Y
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        $dialogCheckNotBefore = (Get-Date).AddSeconds(3)
        $observedState = Get-LivehimeStreamingState -LogPath $LogPath
        while ($observedState -ne "Streaming" -and (Get-Date) -lt $deadline) {
            if ($observedState -eq "Idle" -and (Get-Date) -ge $dialogCheckNotBefore -and
                (Test-LivehimeEndedDialogCloseButton -WindowHandle $window.MainWindowHandle `
                    -LogPath $LogPath)) {
                throw "Livehime reopened the ended/violation dialog after Start; streaming was rejected."
            }
            Start-Sleep -Milliseconds 250
            $observedState = Get-LivehimeStreamingState -LogPath $LogPath
        }
        if ($observedState -ne "Streaming") {
            throw "Bilibili Livehime state did not become [Streaming] within $TimeoutSeconds seconds; current state is $observedState."
        }
        Write-Host "Bilibili Livehime is streaming."
    }
    finally {
        Set-WindowNotTopMost -WindowHandle $window.MainWindowHandle
        [void](Set-AscendViewerTopMost)
    }
}

function Invoke-LivehimeStop {
    param(
        [Parameter(Mandatory = $true)][string]$LivehimeExe,
        [ValidateRange(5, 120)][int]$TimeoutSeconds = 25,
        [string]$LogPath = $script:DefaultLogPath,
        [DateTimeOffset]$StopBeforeUtc = [DateTimeOffset]::MaxValue
    )
    $deadlineUtc = $StopBeforeUtc.ToUniversalTime()
    $state = Get-LivehimeStreamingState -LogPath $LogPath
    if ($state -in @("Idle", "NotRunning")) {
        Write-Host "Bilibili Livehime is already idle."
        return
    }
    if ([DateTimeOffset]::UtcNow -ge $deadlineUtc) {
        throw "Bilibili stop deadline has passed; no Livehime click was sent."
    }
    $window = Wait-LivehimeWindow -LivehimeExe $LivehimeExe
    if ($state -eq "Stopping") {
        [void](Wait-LivehimeStreamingState -DesiredState "Idle" -TimeoutSeconds $TimeoutSeconds -LogPath $LogPath)
        return
    }
    if ($state -eq "Starting") {
        $state = Wait-LivehimeStreamingState -DesiredState @("Streaming", "Idle") -TimeoutSeconds $TimeoutSeconds -LogPath $LogPath
        if ($state -eq "Idle") { return }
    }
    if ($state -ne "Streaming") {
        throw "Refusing to click Livehime while its streaming state is '$state'."
    }
    if ([DateTimeOffset]::UtcNow -ge $deadlineUtc) {
        throw "Bilibili stop deadline has passed; no Livehime click was sent."
    }
    Set-WindowAutomationForeground -WindowHandle $window.MainWindowHandle -TopMost
    try {
        if ([DateTimeOffset]::UtcNow -ge $deadlineUtc) {
            throw "Bilibili stop deadline has passed; no Livehime click was sent."
        }
        $point = Get-LivehimeTogglePoint -WindowHandle $window.MainWindowHandle
        Invoke-LivehimeClick -X $point.X -Y $point.Y
        [void](Wait-LivehimeStreamingState -DesiredState "Idle" -TimeoutSeconds $TimeoutSeconds -LogPath $LogPath)
        Write-Host "Bilibili Livehime is idle."
    }
    finally {
        Set-WindowNotTopMost -WindowHandle $window.MainWindowHandle
        [void](Set-AscendViewerTopMost)
    }
}

function Get-AscendIndexTtsHealth {
    param([ValidateRange(100, 5000)][int]$TimeoutMilliseconds = 800)
    $response = $null
    $reader = $null
    try {
        $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:17952/health")
        $request.Timeout = $TimeoutMilliseconds
        $request.ReadWriteTimeout = $TimeoutMilliseconds
        $request.Method = "GET"
        $request.Accept = "application/json"
        $response = $request.GetResponse()
        $reader = New-Object IO.StreamReader($response.GetResponseStream(), [Text.Encoding]::UTF8)
        return ($reader.ReadToEnd() | ConvertFrom-Json)
    }
    catch {
        return $null
    }
    finally {
        if ($reader) { $reader.Dispose() }
        if ($response) { $response.Close() }
    }
}

function Get-AscendIndexTtsSession {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [switch]$AllowNotRunning
    )
    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $runtime = Join-Path $root ".runtime"
    $sessionPath = Join-Path $runtime "session.json"
    if (-not (Test-Path -LiteralPath $sessionPath -PathType Leaf)) {
        if ($AllowNotRunning) { return $null }
        throw "Cannot read the active sts2-ascend session at '$sessionPath'."
    }
    try {
        $session = Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8 |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Cannot read the active sts2-ascend session at '$sessionPath'."
    }
    $sessionRoot = [IO.Path]::GetFullPath([string]$session.root).TrimEnd('\')
    if (-not [string]::Equals($sessionRoot, $root, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The active sts2-ascend session belongs to a different project root."
    }
    $sessionId = ([string]$session.session_id).Trim().ToLowerInvariant()
    if ($sessionId -notmatch '^[0-9a-f]{32}$') {
        throw "The sts2-ascend session has an invalid GUID identity."
    }
    if (([string]$session.state).Trim().ToLowerInvariant() -ne "running") {
        if ($AllowNotRunning) { return $null }
        throw "The sts2-ascend session is not running."
    }
    $stopFile = [IO.Path]::GetFullPath([string]$session.stop_file)
    if (Test-Path -LiteralPath $stopFile) {
        if ($AllowNotRunning) { return $null }
        throw "The sts2-ascend session is stopping; IndexTTS cannot be leased or restored."
    }
    return [pscustomobject]@{
        Root = $root
        Runtime = $runtime
        SessionId = $sessionId
        StopFile = $stopFile
    }
}

function Test-AscendExactProcessAlive {
    param(
        [int]$ProcessId,
        [long]$CreationFileTime
    )
    if ($ProcessId -le 0) { return $false }
    if ($CreationFileTime -le 0) { return $false }
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { return $false }
    try {
        return [long]$process.StartTime.ToUniversalTime().ToFileTimeUtc() -eq $CreationFileTime
    }
    catch {
        # An unreadable process is not proof that the exact owner remains.
        return $false
    }
}

function Get-AscendIndexTtsLaunchCandidates {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)
    $root = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $quipper = Join-Path $root "tts\quipper.py"
    return @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match '^(python(?:w|\d+(?:\.\d+)*)?|uv)\.exe$' -and
            -not [string]::IsNullOrWhiteSpace([string]$_.CommandLine) -and
            ([string]$_.CommandLine).IndexOf(
                $quipper, [StringComparison]::OrdinalIgnoreCase) -ge 0
        })
}

function Wait-AscendIndexTtsBroadcastReady {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [ValidateRange(10, 300)][int]$TimeoutSeconds = 300,
        [ValidateRange(1024, 4096)][int]$MaximumAllocatorMiB = 3328
    )
    $session = Get-AscendIndexTtsSession -ProjectRoot $ProjectRoot
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $absentSince = $null
    do {
        $status = Get-AscendIndexTtsHealth -TimeoutMilliseconds 800
        if ($status) {
            if ([string]$status.session_id -ne $session.SessionId) {
                throw "IndexTTS port 17952 belongs to another sts2-ascend session."
            }
            $ownerPid = [int]$status.owner_pid
            $ownerFileTime = [long]$status.owner_creation_filetime
            if ($ownerPid -le 0 -or $ownerFileTime -le 0 -or
                -not (Test-AscendExactProcessAlive -ProcessId $ownerPid `
                    -CreationFileTime $ownerFileTime)) {
                throw "IndexTTS health did not identify one exact live owner process."
            }
            $allocatorMiB = [int]$status.cuda_allocator_limit_mib
            if (-not [bool]$status.ready -or
                -not [bool]$status.broadcast_coexistence_ready -or
                [string]$status.vocoder_device -notin @("cpu", "staged_cuda") -or
                $allocatorMiB -le 0 -or $allocatorMiB -gt $MaximumAllocatorMiB) {
                throw ("IndexTTS owner is not the bounded broadcast-coexistence build " +
                       "(ready=$($status.ready), allocator=${allocatorMiB}MiB, " +
                       "vocoder=$($status.vocoder_device)); stream remains closed.")
            }
            return [pscustomobject]@{
                State = "Ready"
                OwnerPid = $ownerPid
                AllocatorMiB = $allocatorMiB
                VocoderDevice = [string]$status.vocoder_device
                Busy = [bool]$status.busy
            }
        }

        $launching = @(Get-AscendIndexTtsLaunchCandidates -ProjectRoot $session.Root)
        if ($launching.Count -gt 0) {
            $absentSince = $null
        }
        elseif ($null -eq $absentSince) {
            $absentSince = Get-Date
        }
        elseif (((Get-Date) - $absentSince).TotalSeconds -ge 3) {
            throw "Required Quipper/IndexTTS owner is absent; stream remains closed."
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw ("IndexTTS launch candidate did not expose a bounded broadcast-ready owner " +
           "within $TimeoutSeconds seconds; stream remains closed.")
}

function Suspend-AscendIndexTtsForBroadcast {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [ValidateRange(10, 300)][int]$TimeoutSeconds = 300
    )
    $session = Get-AscendIndexTtsSession -ProjectRoot $ProjectRoot
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $status = Get-AscendIndexTtsHealth
    $absentSince = $null
    while ($null -eq $status) {
        $launching = @(Get-AscendIndexTtsLaunchCandidates -ProjectRoot $session.Root)
        if ($launching.Count -gt 0) {
            $absentSince = $null
        }
        elseif ($null -eq $absentSince) {
            $absentSince = Get-Date
        }
        elseif (((Get-Date) - $absentSince).TotalSeconds -ge 3) {
            return [pscustomobject]@{ State = "NotRunning"; OwnerPid = 0; Released = $true }
        }
        if ((Get-Date) -ge $deadline) {
            throw ("IndexTTS launch candidate did not expose an exact controllable owner " +
                   "within $TimeoutSeconds seconds; stream remains closed.")
        }
        Start-Sleep -Milliseconds 250
        $status = Get-AscendIndexTtsHealth -TimeoutMilliseconds 500
    }
    if ([string]$status.session_id -ne $session.SessionId) {
        throw "IndexTTS port 17952 belongs to another sts2-ascend session; refusing a broad stop."
    }
    $ownerPid = [int]$status.owner_pid
    $ownerFileTime = [long]$status.owner_creation_filetime
    if ($ownerPid -le 0 -or $ownerFileTime -le 0 -or
        [string]::IsNullOrWhiteSpace([string]$status.owner_code_epoch)) {
        throw "IndexTTS health did not provide an exact owner identity."
    }

    $alreadySuspending = ($null -ne $status.PSObject.Properties["broadcast_suspend_requested"] -and
        [bool]$status.broadcast_suspend_requested)
    if (-not $alreadySuspending) {
        $payload = @{
            session_id = $session.SessionId
            owner_pid = $ownerPid
            owner_created_unix = [double]$status.owner_created_unix
            owner_creation_filetime = $ownerFileTime
            owner_code_epoch = [string]$status.owner_code_epoch
            reason = "bilibili_stream"
        } | ConvertTo-Json -Compress
        try {
            $result = Invoke-RestMethod -Uri "http://127.0.0.1:17952/suspend" `
                -Method Post -ContentType "application/json; charset=utf-8" `
                -Body ([Text.Encoding]::UTF8.GetBytes($payload)) -TimeoutSec 8
        }
        catch {
            throw ("IndexTTS owner does not support the maintenance-only emergency suspend, " +
                   "or rejected its exact identity: " + $_.Exception.Message)
        }
        if (-not $result.ok -or -not $result.accepted) {
            throw "IndexTTS owner rejected the maintenance-only emergency suspend."
        }
    }

    do {
        $current = Get-AscendIndexTtsHealth -TimeoutMilliseconds 300
        $sameOwner = $current -and [string]$current.session_id -eq $session.SessionId -and
            [int]$current.owner_pid -eq $ownerPid -and
            [long]$current.owner_creation_filetime -eq $ownerFileTime
        $processAlive = Test-AscendExactProcessAlive -ProcessId $ownerPid `
            -CreationFileTime $ownerFileTime
        if (-not $sameOwner -and -not $processAlive) {
            return [pscustomobject]@{
                State = "Suspended"
                OwnerPid = $ownerPid
                Released = $true
            }
        }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw "IndexTTS owner did not drain and release CUDA within $TimeoutSeconds seconds."
}

function Restore-AscendIndexTtsAfterBroadcast {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [ValidateRange(0, 300)][int]$WaitReadySeconds = 0
    )
    $state = Get-LivehimeStreamingState
    if ($state -notin @("Idle", "NotRunning")) {
        throw "Refusing to restore the IndexTTS CUDA owner while Livehime state is '$state'."
    }
    $session = Get-AscendIndexTtsSession -ProjectRoot $ProjectRoot -AllowNotRunning
    if ($null -eq $session) {
        return [pscustomobject]@{
            State = "NoRunningSession"
            OwnerPid = 0
            Ready = $false
        }
    }
    $status = Get-AscendIndexTtsHealth
    if ($status) {
        if ([string]$status.session_id -eq $session.SessionId -and [bool]$status.ready) {
            return [pscustomobject]@{
                State = "AlreadyRunning"
                OwnerPid = [int]$status.owner_pid
                Ready = $true
            }
        }
        throw "An IndexTTS owner is still present; refusing to launch a second CUDA model."
    }

    $quipper = Join-Path $session.Root "tts\quipper.py"
    $indexRoot = Join-Path $session.Root "third_party\index-tts"
    if (-not (Test-Path -LiteralPath $quipper -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $indexRoot "checkpoints\config.yaml") -PathType Leaf)) {
        return [pscustomobject]@{ State = "ModelUnavailable"; OwnerPid = 0; Ready = $false }
    }
    $launching = @(Get-AscendIndexTtsLaunchCandidates -ProjectRoot $session.Root)
    if ($launching.Count -gt 0) {
        return [pscustomobject]@{
            State = "Starting"
            OwnerPid = [int]$launching[0].ProcessId
            Ready = $false
        }
    }
    $uvCommand = Get-Command uv.exe -CommandType Application -ErrorAction SilentlyContinue
    if (-not $uvCommand) {
        $uvCommand = Get-Command uv -CommandType Application -ErrorAction SilentlyContinue
    }
    if (-not $uvCommand) { throw "uv is unavailable; IndexTTS owner was not restored." }

    $names = @(
        "STS2_ASCEND_ROOT", "STS2_ASCEND_RUNTIME_DIR", "STS2_ASCEND_SESSION_ID",
        "STS2_ASCEND_STOP_FILE", "PYTHONHOME", "PYTHONPATH"
    )
    $saved = @{}
    foreach ($name in $names) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    try {
        [Environment]::SetEnvironmentVariable("STS2_ASCEND_ROOT", $session.Root, "Process")
        [Environment]::SetEnvironmentVariable("STS2_ASCEND_RUNTIME_DIR", $session.Runtime, "Process")
        [Environment]::SetEnvironmentVariable("STS2_ASCEND_SESSION_ID", $session.SessionId, "Process")
        [Environment]::SetEnvironmentVariable("STS2_ASCEND_STOP_FILE", $session.StopFile, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONHOME", $null, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process")
        $arguments = @(
            "run", "--project", ('"{0}"' -f $indexRoot),
            "python", ('"{0}"' -f $quipper)
        )
        $candidate = Start-Process -FilePath $uvCommand.Source -ArgumentList $arguments `
            -WorkingDirectory $session.Root -WindowStyle Hidden -PassThru
    }
    finally {
        foreach ($name in $names) {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process")
        }
    }

    if ($WaitReadySeconds -gt 0) {
        $deadline = (Get-Date).AddSeconds($WaitReadySeconds)
        do {
            $status = Get-AscendIndexTtsHealth -TimeoutMilliseconds 500
            if ($status -and [string]$status.session_id -eq $session.SessionId -and
                [bool]$status.ready) {
                return [pscustomobject]@{
                    State = "Restored"
                    OwnerPid = [int]$status.owner_pid
                    Ready = $true
                }
            }
            Start-Sleep -Milliseconds 500
        } while ((Get-Date) -lt $deadline)
    }
    return [pscustomobject]@{
        State = "Starting"
        OwnerPid = [int]$candidate.Id
        Ready = $false
    }
}

function Invoke-LivehimeBridge {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("Start", "Stop")]
        [string]$Action,
        [ValidateRange(5, 120)][int]$TimeoutSeconds = 30,
        [string]$TaskPath = "\Vivhite\"
    )

    $desiredState = if ($Action -eq "Start") { "Streaming" } else { "Idle" }
    $state = Get-LivehimeStreamingState
    $alreadyDesired = $state -eq $desiredState -or
        ($Action -eq "Stop" -and $state -eq "NotRunning")
    if ($alreadyDesired) {
        Write-Host "Bilibili Livehime is already $($desiredState.ToLowerInvariant())."
    }

    $taskName = "BilibiliLive-$Action"
    $task = Get-ScheduledTask -TaskName $taskName -TaskPath $TaskPath `
        -ErrorAction SilentlyContinue
    if (-not $task) {
        $installer = Join-Path $PSScriptRoot "Install-BilibiliLiveBridge.ps1"
        throw "The protected Livehime bridge task '$TaskPath$taskName' is not installed. Run '$installer' once from an elevated PowerShell window."
    }

    $before = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath $TaskPath `
        -ErrorAction SilentlyContinue
    $previousLastRunTime = if ($before) { $before.LastRunTime } else { [DateTime]::MinValue }
    Start-ScheduledTask -TaskName $taskName -TaskPath $TaskPath
    if (-not $alreadyDesired) {
        try {
            [void](Wait-LivehimeStreamingState -DesiredState $desiredState `
                -TimeoutSeconds $TimeoutSeconds)
        }
        catch {
            $info = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath $TaskPath `
                -ErrorAction SilentlyContinue
            if ($info -and $info.LastTaskResult -ne 0 -and $info.LastTaskResult -ne 267009) {
                throw "Protected Livehime bridge '$TaskPath$taskName' failed with result $($info.LastTaskResult). $($_.Exception.Message)"
            }
            throw
        }
    }

    $taskDeadline = (Get-Date).AddSeconds($TimeoutSeconds + 20)
    $currentRunObserved = $false
    do {
        $task = Get-ScheduledTask -TaskName $taskName -TaskPath $TaskPath `
            -ErrorAction SilentlyContinue
        $info = Get-ScheduledTaskInfo -TaskName $taskName -TaskPath $TaskPath `
            -ErrorAction SilentlyContinue
        if ($task -and [string]$task.State -eq "Running") {
            $currentRunObserved = $true
        }
        if ($info -and $info.LastRunTime -gt $previousLastRunTime) {
            $currentRunObserved = $true
        }
        if ($currentRunObserved -and $task -and [string]$task.State -ne "Running") {
            if (-not $info -or $info.LastTaskResult -ne 0) {
                $result = if ($info) { $info.LastTaskResult } else { "unknown" }
                throw "Protected Livehime bridge '$TaskPath$taskName' failed with result $result."
            }
            break
        }
        Start-Sleep -Milliseconds 100
    } while ((Get-Date) -lt $taskDeadline)
    if (-not $currentRunObserved -or -not $task -or [string]$task.State -eq "Running") {
        throw "Protected Livehime bridge '$TaskPath$taskName' did not complete within the restoration deadline."
    }

    $finalState = Get-LivehimeStreamingState
    if ($finalState -ne $desiredState -and
        -not ($Action -eq "Stop" -and $finalState -eq "NotRunning")) {
        throw "Protected Livehime bridge completed, but Livehime state is '$finalState' instead of '$desiredState'."
    }
}

function Get-SlayTheSpireWindow {
    param([Parameter(Mandatory = $true)][string]$GameDir)
    $gameExe = [IO.Path]::GetFullPath((Join-Path $GameDir "SlayTheSpire2.exe"))
    $processes = @(Get-CimInstance Win32_Process -Filter "Name='SlayTheSpire2.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ExecutablePath -and
            [string]::Equals([IO.Path]::GetFullPath([string]$_.ExecutablePath), $gameExe,
                [StringComparison]::OrdinalIgnoreCase)
        })
    foreach ($process in $processes) {
        $runtime = Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
        if ($runtime -and $runtime.MainWindowHandle -ne [IntPtr]::Zero) {
            return [pscustomobject]@{
                ProcessId = [int]$process.ProcessId
                ExecutablePath = $gameExe
                WindowHandle = $runtime.MainWindowHandle
            }
        }
    }
    return $null
}

function Wait-SlayTheSpireWindow {
    param(
        [Parameter(Mandatory = $true)][string]$GameDir,
        [ValidateRange(5, 300)][int]$TimeoutSeconds = 90
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $window = Get-SlayTheSpireWindow -GameDir $GameDir
        if ($window) { return $window }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Slay the Spire 2 did not expose a main window within $TimeoutSeconds seconds."
}

function Set-SlayTheSpireTopMost {
    param(
        [Parameter(Mandatory = $true)][string]$GameDir,
        [ValidateRange(5, 300)][int]$TimeoutSeconds = 90
    )
    $window = Wait-SlayTheSpireWindow -GameDir $GameDir -TimeoutSeconds $TimeoutSeconds
    Set-WindowAutomationForeground -WindowHandle $window.WindowHandle -TopMost
    $extendedStyle = [BilibiliLiveNative]::GetWindowLongPtrSafe($window.WindowHandle, $script:GwlExStyle).ToInt64()
    if (($extendedStyle -band $script:WsExTopMost) -eq 0) {
        throw "Slay the Spire 2 foreground succeeded, but WS_EX_TOPMOST verification failed."
    }
    # The game's foreground promotion moves it ahead of other TOPMOST windows.
    # Restore ASCEND-VISION without activating it so the game remains usable.
    [void](Set-AscendViewerTopMost)
    Write-Host "Slay the Spire 2 is foreground and TOPMOST (pid $($window.ProcessId))."
}

function Set-AscendViewerTopMost {
    param(
        [string]$ProjectRoot = (Split-Path $PSScriptRoot -Parent)
    )
    $viewerPath = [IO.Path]::GetFullPath((Join-Path $ProjectRoot "brain\review_viewer.py"))
    $viewerProcesses = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -in @("python.exe", "pythonw.exe") -and
            $_.CommandLine -and
            [string]$_.CommandLine -match [regex]::Escape($viewerPath)
        })
    foreach ($process in $viewerProcesses) {
        $runtime = Get-Process -Id $process.ProcessId -ErrorAction SilentlyContinue
        if (-not $runtime -or $runtime.MainWindowHandle -eq [IntPtr]::Zero) { continue }
        if ($runtime.MainWindowTitle -ne "ASCEND-VISION") { continue }
        $flags = $script:SwpNoMove -bor $script:SwpNoSize -bor
            $script:SwpNoActivate -bor $script:SwpShowWindow
        if (-not [BilibiliLiveNative]::SetWindowPos(
                $runtime.MainWindowHandle, $script:HwndTopMost, 0, 0, 0, 0, $flags)) {
            throw "Could not place ASCEND-VISION above the game."
        }
        Write-Host "ASCEND-VISION is visible above the game without taking focus."
        return $true
    }
    Write-Verbose "ASCEND-VISION is not active; it will appear when a review starts."
    return $false
}

Export-ModuleMember -Function Test-IsAdministrator, ConvertTo-LivehimeState,
    Get-LivehimeStreamingState, Get-BilibiliDailyStartWindow,
    Get-BilibiliDailyStartSchedule, Get-BilibiliDailyStopWindow,
    Get-BilibiliDailyStopSchedule, Test-BilibiliDailyStopRequired,
    Test-BilibiliBridgeInstallSafeState,
    Get-LivehimePreferencesPath, Disable-LivehimeSynchronizedRecording,
    Remove-LivehimeDuplicateBrowserSource,
    Get-LivehimeLogCheckpoint, Get-LivehimeLogTextAfter,
    Get-LivehimeLastRenderLagPercent, Test-LivehimeDisplayCaptureStale,
    Measure-LivehimePreviewMotion, Test-LivehimePreviewFreshness,
    Get-BilibiliCaptureHealthDecision,
    Test-BilibiliGameplayEvidence, Get-BilibiliGameplayProgressSnapshot,
    Test-BilibiliAppliedActionProgress, Get-BilibiliGameplayHealthDecision,
    Restart-LivehimeIdle,
    Invoke-LivehimeStart, Invoke-LivehimeStop,
    Get-AscendIndexTtsHealth, Suspend-AscendIndexTtsForBroadcast,
    Wait-AscendIndexTtsBroadcastReady, Restore-AscendIndexTtsAfterBroadcast,
    Invoke-LivehimeBridge, Get-SlayTheSpireWindow, Set-SlayTheSpireTopMost,
    Set-AscendViewerTopMost
