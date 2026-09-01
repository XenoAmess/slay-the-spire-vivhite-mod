[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$OutputPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$repoFullPath = [IO.Path]::GetFullPath($RepoRoot)
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $repoFullPath "workshop\preview.jpg"
}
$outputFullPath = [IO.Path]::GetFullPath($OutputPath)
$heroPath = Join-Path $repoFullPath "assets\vivhite-ironclad\custom\character_select\sources\vivhite-character-select-hero-master-v1.png"
$transitionPath = Join-Path $repoFullPath "Vivhite\Vivhite\skins\ironclad\transitions\vivhite_character_select_transition.png"
foreach ($sourcePath in @($heroPath, $transitionPath)) {
    if (-not [IO.File]::Exists($sourcePath)) {
        throw "Required approved preview source is missing: $sourcePath"
    }
}

Add-Type -AssemblyName System.Drawing
$canvas = [Drawing.Bitmap]::new(1024, 1024, [Drawing.Imaging.PixelFormat]::Format24bppRgb)
$graphics = [Drawing.Graphics]::FromImage($canvas)
$hero = $null
$transition = $null
$attributes = $null
try {
    $graphics.SmoothingMode = [Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.InterpolationMode = [Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.PixelOffsetMode = [Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $graphics.TextRenderingHint = [Drawing.Text.TextRenderingHint]::AntiAliasGridFit

    $backgroundRect = [Drawing.Rectangle]::new(0, 0, 1024, 1024)
    $background = [Drawing.Drawing2D.LinearGradientBrush]::new(
        $backgroundRect,
        [Drawing.Color]::FromArgb(255, 7, 10, 35),
        [Drawing.Color]::FromArgb(255, 67, 22, 95),
        55.0)
    try { $graphics.FillRectangle($background, $backgroundRect) } finally { $background.Dispose() }

    $transition = [Drawing.Image]::FromFile($transitionPath)
    $matrix = [Drawing.Imaging.ColorMatrix]::new()
    $matrix.Matrix33 = 0.30
    $attributes = [Drawing.Imaging.ImageAttributes]::new()
    $attributes.SetColorMatrix($matrix)
    $graphics.DrawImage(
        $transition,
        $backgroundRect,
        0,
        0,
        $transition.Width,
        $transition.Height,
        [Drawing.GraphicsUnit]::Pixel,
        $attributes)

    foreach ($ring in @(
        @{ X = 85; Y = 118; Size = 540; Alpha = 58; Width = 4 },
        @{ X = 28; Y = 63; Size = 650; Alpha = 40; Width = 3 },
        @{ X = 455; Y = 115; Size = 620; Alpha = 35; Width = 3 }
    )) {
        $pen = [Drawing.Pen]::new(
            [Drawing.Color]::FromArgb($ring.Alpha, 245, 207, 99),
            [single]$ring.Width)
        try { $graphics.DrawEllipse($pen, $ring.X, $ring.Y, $ring.Size, $ring.Size) } finally { $pen.Dispose() }
    }

    $panel = [Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(168, 5, 7, 28))
    try { $graphics.FillRectangle($panel, 0, 0, 462, 1024) } finally { $panel.Dispose() }

    $hero = [Drawing.Image]::FromFile($heroPath)
    $heroWidth = 668
    $heroHeight = 999
    $graphics.DrawImage($hero, 355, 16, $heroWidth, $heroHeight)

    $gold = [Drawing.Color]::FromArgb(255, 247, 210, 111)
    $white = [Drawing.Color]::FromArgb(255, 246, 244, 255)
    $lavender = [Drawing.Color]::FromArgb(255, 197, 185, 255)
    $fontZh = [Drawing.Font]::new("Microsoft YaHei UI", 82, [Drawing.FontStyle]::Bold, [Drawing.GraphicsUnit]::Pixel)
    $fontName = [Drawing.Font]::new("Segoe UI", 59, [Drawing.FontStyle]::Bold, [Drawing.GraphicsUnit]::Pixel)
    $fontSub = [Drawing.Font]::new("Segoe UI", 27, [Drawing.FontStyle]::Regular, [Drawing.GraphicsUnit]::Pixel)
    $fontChip = [Drawing.Font]::new("Segoe UI", 20, [Drawing.FontStyle]::Bold, [Drawing.GraphicsUnit]::Pixel)
    $brushGold = [Drawing.SolidBrush]::new($gold)
    $brushWhite = [Drawing.SolidBrush]::new($white)
    $brushLavender = [Drawing.SolidBrush]::new($lavender)
    try {
        $zhTitle = ([char]0x767D).ToString() + [char]0x7EEE
        $graphics.DrawString($zhTitle, $fontZh, $brushWhite, 52, 112)
        $graphics.DrawString("VIVHITE", $fontName, $brushGold, 49, 220)
        $graphics.DrawString("CUSTOM CHARACTER", $fontSub, $brushLavender, 54, 300)

        $linePen = [Drawing.Pen]::new([Drawing.Color]::FromArgb(210, 247, 210, 111), 3)
        try { $graphics.DrawLine($linePen, 54, 354, 386, 354) } finally { $linePen.Dispose() }

        $chipY = 404
        foreach ($chip in @("61 CARDS", "3 BUILDS", "V0.2.0")) {
            $chipBrush = [Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(130, 78, 57, 145))
            try { $graphics.FillRectangle($chipBrush, [Drawing.RectangleF]::new(52, $chipY, 210, 52)) } finally { $chipBrush.Dispose() }
            $graphics.DrawString($chip, $fontChip, $brushWhite, 72, $chipY + 11)
            $chipY += 72
        }

        $graphics.DrawString("MATHEMATICS / MAGIC / ART", $fontSub, $brushLavender, 53, 667)
        $graphics.DrawString("Slay the Spire 2", $fontSub, $brushWhite, 53, 932)
    }
    finally {
        $fontZh.Dispose(); $fontName.Dispose(); $fontSub.Dispose(); $fontChip.Dispose()
        $brushGold.Dispose(); $brushWhite.Dispose(); $brushLavender.Dispose()
    }

    $parent = [IO.Path]::GetDirectoryName($outputFullPath)
    if (-not [string]::IsNullOrEmpty($parent)) { [void][IO.Directory]::CreateDirectory($parent) }
    $jpegCodec = [Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object MimeType -eq "image/jpeg" | Select-Object -First 1
    if ($null -eq $jpegCodec) { throw "System.Drawing did not expose a JPEG encoder." }
    $quality = [Drawing.Imaging.EncoderParameter]::new([Drawing.Imaging.Encoder]::Quality, [long]92)
    $parameters = [Drawing.Imaging.EncoderParameters]::new(1)
    try {
        $parameters.Param[0] = $quality
        $canvas.Save($outputFullPath, $jpegCodec, $parameters)
    }
    finally { $parameters.Dispose(); $quality.Dispose() }
}
finally {
    if ($null -ne $attributes) { $attributes.Dispose() }
    if ($null -ne $transition) { $transition.Dispose() }
    if ($null -ne $hero) { $hero.Dispose() }
    $graphics.Dispose()
    $canvas.Dispose()
}

$file = [IO.FileInfo]::new($outputFullPath)
if ($file.Length -ge 1000000) {
    throw "Workshop preview exceeds Steam's 1 MB limit: $($file.Length) bytes."
}
[pscustomobject]@{
    Path = $outputFullPath
    Width = 1024
    Height = 1024
    Bytes = $file.Length
    SHA256 = (Get-FileHash -LiteralPath $outputFullPath -Algorithm SHA256).Hash
    HeroSourceSHA256 = (Get-FileHash -LiteralPath $heroPath -Algorithm SHA256).Hash
    TransitionSourceSHA256 = (Get-FileHash -LiteralPath $transitionPath -Algorithm SHA256).Hash
} | Format-List
