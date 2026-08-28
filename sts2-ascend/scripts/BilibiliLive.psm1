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

function Get-LivehimeStreamingState {
    param([string]$LogPath = $script:DefaultLogPath)
    if (-not (Get-Process -Name livehime -ErrorAction SilentlyContinue)) {
        return "NotRunning"
    }
    if (-not (Test-Path -LiteralPath $LogPath)) { return "Unknown" }
    $latestCode = $null
    foreach ($line in @(Get-Content -LiteralPath $LogPath -Tail 50000 -Encoding UTF8 -ErrorAction SilentlyContinue)) {
        if ([string]$line -match 'set_streaming_status:\s+last_status:\d+\s+set_status:(\d+)') {
            $latestCode = [int]$matches[1]
        }
    }
    if ($null -eq $latestCode) { return "Unknown" }
    return ConvertTo-LivehimeState -StatusCode $latestCode
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
    param([Parameter(Mandatory = $true)]$Operation, [Parameter(Mandatory = $true)][Type]$ResultType)
    $method = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object { $_.Name -eq "AsTask" -and $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
    $task = $method.MakeGenericMethod($ResultType).Invoke($null, @($Operation))
    $task.Wait()
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

function Close-LivehimeIdleDialogs {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)
    $snapshot = Get-WindowSnapshot -WindowHandle $WindowHandle
    $text = Get-LivehimeScreenText -WindowHandle $WindowHandle
    if ($text -match [string]([char]0x5904) + [char]0x7F5A + [char]0x7ED3 + [char]0x679C -or
        $text -match [string]([char]0x5904) + [char]0x7F5A + [char]0x65F6 + [char]0x95F4 -or
        $text -match [string]([char]0x5904) + [char]0x7F5A + [char]0x4E2D + [char]0x5FC3) {
        $ackX = $snapshot.X + [int]($snapshot.Width * 0.5)
        $ackY = $snapshot.Y + [int]($snapshot.Height * 0.625)
        Invoke-LivehimeClick -X $ackX -Y $ackY
        Start-Sleep -Milliseconds 600
        $text = Get-LivehimeScreenText -WindowHandle $WindowHandle
    }
    $endedText = [string]([char]0x76F4) + [char]0x64AD + [char]0x5DF2 + [char]0x7ED3 + [char]0x675F
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
    elseif ($state -notin @("Idle", "NotRunning")) {
        throw "Refusing to click Livehime while its streaming state is '$state'."
    }
    Set-WindowAutomationForeground -WindowHandle $window.MainWindowHandle -TopMost
    try {
        Close-LivehimeIdleDialogs -WindowHandle $window.MainWindowHandle
        if (-not (Test-LivehimeStartButton -WindowHandle $window.MainWindowHandle)) {
            throw "The calibrated Livehime start button was not detected. No click was sent."
        }
        $point = Get-LivehimeTogglePoint -WindowHandle $window.MainWindowHandle
        Invoke-LivehimeClick -X $point.X -Y $point.Y
        [void](Wait-LivehimeStreamingState -DesiredState "Streaming" -TimeoutSeconds $TimeoutSeconds -LogPath $LogPath)
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
        [string]$LogPath = $script:DefaultLogPath
    )
    $state = Get-LivehimeStreamingState -LogPath $LogPath
    if ($state -in @("Idle", "NotRunning")) {
        Write-Host "Bilibili Livehime is already idle."
        return
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
    Set-WindowAutomationForeground -WindowHandle $window.MainWindowHandle -TopMost
    try {
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
    if ($state -eq $desiredState -or ($Action -eq "Stop" -and $state -eq "NotRunning")) {
        Write-Host "Bilibili Livehime is already $($desiredState.ToLowerInvariant())."
        return
    }

    $taskName = "BilibiliLive-$Action"
    $task = Get-ScheduledTask -TaskName $taskName -TaskPath $TaskPath `
        -ErrorAction SilentlyContinue
    if (-not $task) {
        $installer = Join-Path $PSScriptRoot "Install-BilibiliLiveBridge.ps1"
        throw "The protected Livehime bridge task '$TaskPath$taskName' is not installed. Run '$installer' once from an elevated PowerShell window."
    }

    Start-ScheduledTask -TaskName $taskName -TaskPath $TaskPath
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
    Get-LivehimeStreamingState, Invoke-LivehimeStart, Invoke-LivehimeStop,
    Invoke-LivehimeBridge, Get-SlayTheSpireWindow, Set-SlayTheSpireTopMost,
    Set-AscendViewerTopMost
