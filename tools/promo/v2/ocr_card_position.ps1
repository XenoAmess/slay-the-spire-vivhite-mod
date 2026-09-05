[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ImagePath,
    [ValidateSet('luminous','ritual')][string]$Card = 'luminous'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics,ContentType=WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language,Windows,ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await-WinRt {
    param($Operation, $Type)
    $method = $asTask.MakeGenericMethod($Type)
    $task = $method.Invoke($null, @($Operation))
    $task.Wait() | Out-Null
    return $task.Result
}

$path = (Resolve-Path -LiteralPath $ImagePath).Path
$file = Await-WinRt ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
$stream = Await-WinRt ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
try {
    $decoder = Await-WinRt ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await-WinRt ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('zh-Hans'))
    $result = Await-WinRt ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
    # Keep this helper ASCII-only: Windows PowerShell may parse a UTF-8 file
    # without a BOM as the local code page.  Build the CJK needles by codepoint.
    $needles = if ($Card -eq 'ritual') {
        @([char]0x7329,[char]0x7EA2,[char]0x8F6C,[char]0x5316,[char]0x4EEA,[char]0x5F0F)
    } else {
        @([char]0x5F26,[char]0x5149,[char]0x6295,[char]0x5F71)
    }
    $hits = @()
    foreach ($line in $result.Lines) {
        $words = @($line.Words)
        $lineText = ($line.Text -replace '\s','')
        $lineY = if ($words.Count) { $words[0].BoundingRect.Y } else { 0 }
        if ($lineY -lt 820 -or $lineY -gt 1010) { continue }
        $matched = @($words | Where-Object { $needles -contains $_.Text -or ($_.Text.Length -gt 1 -and ($_.Text -match ($needles -join '|'))) })
        $pattern = if ($Card -eq 'ritual') {
            ([char]0x7329) + '.*' + ([char]0x7EA2) + '.*' + ([char]0x5316)
        } else {
            ([char]0x5F26) + '.*' + ([char]0x5149) + '.*' + ([char]0x6295) + '.*' + ([char]0x5F71)
        }
        if ($lineText -match $pattern -or $matched.Count -ge 3) {
            $rects = if ($matched.Count -gt 0) { $matched | ForEach-Object { $_.BoundingRect } } else { $words | ForEach-Object { $_.BoundingRect } }
            $left = ($rects | Measure-Object X -Minimum).Minimum
            $right = ($rects | ForEach-Object { $_.X + $_.Width } | Measure-Object -Maximum).Maximum
            $top = ($rects | Measure-Object Y -Minimum).Minimum
            $bottom = ($rects | ForEach-Object { $_.Y + $_.Height } | Measure-Object -Maximum).Maximum
            $hits += [pscustomobject]@{ text=$line.Text; x=[int](($left+$right)/2); y=[int](($top+$bottom)/2); count=$matched.Count }
        }
    }
    $hits | Sort-Object -Property @{Expression='count';Descending=$true}, @{Expression='x';Descending=$false} | ConvertTo-Json -Compress
}
finally { $stream.Dispose() }
