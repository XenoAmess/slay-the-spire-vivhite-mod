# StS2 Mod 真机测试工具模块
# 用法: Import-Module <repo>\tools\test\GameTest.psm1 后调用各函数

Add-Type -AssemblyName System.Windows.Forms, System.Drawing

# ---------- 截图 ----------

# 截取整个虚拟屏幕（或指定区域）到 PNG。返回文件完整路径。
function Save-Screenshot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [int]$X = [int]::MinValue, [int]$Y = 0, [int]$Width = 0, [int]$Height = 0
    )
    $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
    if ($X -eq [int]::MinValue) { $X = $vs.Left; $Y = $vs.Top; $Width = $vs.Width; $Height = $vs.Height }
    $bmp = New-Object System.Drawing.Bitmap $Width, $Height
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    try {
        $g.CopyFromScreen($X, $Y, 0, 0, $bmp.Size)
        $dir = Split-Path $Path -Parent
        if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
        $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $g.Dispose(); $bmp.Dispose()
    }
    return (Resolve-Path $Path).Path
}

# ---------- 键鼠输入 ----------

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class GameInputNative {
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, int dwExtraInfo);
    [DllImport("user32.dll")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, int dwExtraInfo);
    [DllImport("user32.dll")] public static extern short VkKeyScanW(char ch);
    [DllImport("user32.dll")] public static extern uint MapVirtualKeyW(uint uCode, uint uMapType);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    [StructLayout(LayoutKind.Sequential)] public struct INPUT {
        public uint type;
        public INPUTUNION u;
    }
    [StructLayout(LayoutKind.Explicit)] public struct INPUTUNION {
        [FieldOffset(0)] public KEYBDINPUT ki;
        [FieldOffset(0)] public MOUSEINPUT mi;
    }
    [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT {
        public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo;
    }
    [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT {
        public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo;
    }

    public const uint INPUT_KEYBOARD = 1;
    public const uint KEYEVENTF_SCANCODE = 0x0008;
    public const uint KEYEVENTF_KEYUP = 0x0002;
    public const uint KEYEVENTF_EXTENDEDKEY = 0x0001;

    // 用扫描码发送一个虚拟键的按下/抬起，Godot 等引擎对扫描码兼容性最好
    public static void SendKeyScan(ushort vk) {
        ushort scan = (ushort)MapVirtualKeyW(vk, 0);
        INPUT[] down = new INPUT[1];
        down[0].type = INPUT_KEYBOARD;
        down[0].u.ki = new KEYBDINPUT { wVk = 0, wScan = scan, dwFlags = KEYEVENTF_SCANCODE, time = 0, dwExtraInfo = IntPtr.Zero };
        SendInput(1, down, Marshal.SizeOf(typeof(INPUT)));
        System.Threading.Thread.Sleep(50);
        INPUT[] up = new INPUT[1];
        up[0].type = INPUT_KEYBOARD;
        up[0].u.ki = new KEYBDINPUT { wVk = 0, wScan = scan, dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, time = 0, dwExtraInfo = IntPtr.Zero };
        SendInput(1, up, Marshal.SizeOf(typeof(INPUT)));
    }

    public const uint MOUSEEVENTF_LEFTDOWN = 0x0002, MOUSEEVENTF_LEFTUP = 0x0004;
    public const byte VK_SHIFT = 0x10, VK_CONTROL = 0x11, VK_MENU = 0x12, VK_RETURN = 0x0D, VK_BACK = 0x08, VK_SPACE = 0x20, VK_OEM_3 = 0xC0;
}
"@ -ErrorAction SilentlyContinue

# 鼠标左键点击屏幕坐标 (X, Y)
function Invoke-MouseClick {
    param([int]$X, [int]$Y, [int]$DelayMs = 80)
    [GameInputNative]::SetCursorPos($X, $Y) | Out-Null
    Start-Sleep -Milliseconds 60
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    Start-Sleep -Milliseconds $DelayMs
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
}

# 移动鼠标（用于悬停 tooltip）
function Move-Mouse {
    param([int]$X, [int]$Y)
    [GameInputNative]::SetCursorPos($X, $Y) | Out-Null
}

# 按虚拟键码发送按键（SendInput + 扫描码，兼容 Godot 游戏窗口）。$VkCode 例如 0xC0 是 `~ 键, 0x0D 是回车
function Send-Key {
    param([byte]$VkCode, [int]$HoldMs = 60)
    [GameInputNative]::SendKeyScan([uint16]$VkCode)
    Start-Sleep -Milliseconds $HoldMs
}

# 发送一段文本（逐字符，ASCII）。基于 VkKeyScanW + 扫描码，兼容游戏窗口。
function Send-Text {
    param([string]$Text, [int]$CharDelayMs = 60)
    foreach ($c in $Text.ToCharArray()) {
        $vk = [GameInputNative]::VkKeyScanW($c)
        if ($vk -lt 0) { continue }  # 无法映射的字符跳过
        $key = [byte]($vk -band 0xFF)
        $shift = ($vk -shr 8) -band 0x07
        if ($shift -band 1) { [GameInputNative]::keybd_event([GameInputNative]::VK_SHIFT, 0, 0, 0) }
        [GameInputNative]::SendKeyScan([uint16]$key)
        if ($shift -band 1) { [GameInputNative]::keybd_event([GameInputNative]::VK_SHIFT, 0, [GameInputNative]::KEYEVENTF_KEYUP, 0) }
        Start-Sleep -Milliseconds $CharDelayMs
    }
}

# 把指定进程的窗口置前
function Set-WindowForeground {
    param([int]$ProcessId)
    $p = Get-Process -Id $ProcessId -ErrorAction Stop
    if ($p.MainWindowHandle -ne [IntPtr]::Zero) {
        [GameInputNative]::ShowWindow($p.MainWindowHandle, 9) | Out-Null  # SW_RESTORE
        [GameInputNative]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
    }
}

# 获取窗口矩形
function Get-WindowRect {
    param([int]$ProcessId)
    $p = Get-Process -Id $ProcessId -ErrorAction Stop
    $r = New-Object GameInputNative+RECT
    [GameInputNative]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
    return $r
}

# ---------- OCR ----------

# 对 PNG 做 OCR。Language 例如 "zh-Hans-CN" / "en-US"。返回识别文本。
function Get-OcrText {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [string]$Language = "zh-Hans"
    )
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType=WindowsRuntime]
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]

    $asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

    $await = {
        param($op, $type)
        $m = $asTaskGeneric.MakeGenericMethod($type)
        $t = $m.Invoke($null, @($op))
        $t.Wait() | Out-Null
        return $t.Result
    }

    $fullPath = (Resolve-Path $Path).Path
    $file = & $await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($fullPath)) ([Windows.Storage.StorageFile])
    $stream = & $await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = & $await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = & $await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])

    $lang = New-Object Windows.Globalization.Language $Language
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
    if ($null -eq $engine) { throw "OCR engine not available for $Language" }
    $result = & $await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    $stream.Dispose()
    return $result.Text
}
