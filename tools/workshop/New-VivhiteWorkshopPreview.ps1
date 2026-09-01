[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$OutputPath = "",
    [string]$MetadataPath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$repoFullPath = [IO.Path]::GetFullPath($RepoRoot)

function Read-StrictUtf8Json {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not [IO.File]::Exists($Path)) { throw "Workshop metadata is missing: $Path" }
    try {
        $encoding = [Text.UTF8Encoding]::new($false, $true)
        return [IO.File]::ReadAllText($Path, $encoding) | ConvertFrom-Json
    }
    catch {
        throw "Workshop metadata is not valid UTF-8 JSON: $Path. $($_.Exception.Message)"
    }
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not [IO.File]::Exists($Path)) { throw "Cannot hash missing file: $Path" }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Resolve-RepoPath {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$Root
    )
    if ([IO.Path]::IsPathRooted($Value)) { return [IO.Path]::GetFullPath($Value) }
    return [IO.Path]::GetFullPath((Join-Path $Root ($Value -replace '/', '\')))
}

function Assert-RepoChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $rootPrefix = $Root.TrimEnd('\') + '\'
    if (-not $Path.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label must stay inside the repository: $Path"
    }
    if ($Path.IndexOf('\.git\', [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
        $Path.IndexOf('\.runtime\', [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "$Label cannot use Git metadata or ignored runtime paths: $Path"
    }
}

function Set-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][object]$Value
    )
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        Add-Member -InputObject $Object -MemberType NoteProperty -Name $Name -Value $Value
    }
    else { $Object.$Name = $Value }
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Value
    )
    $parent = [IO.Path]::GetDirectoryName($Path)
    if (-not [string]::IsNullOrWhiteSpace($parent)) { [void][IO.Directory]::CreateDirectory($parent) }
    $temporary = "$Path.$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        $encoding = [Text.UTF8Encoding]::new($false, $true)
        [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 12), $encoding)
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if ([IO.File]::Exists($temporary)) { Remove-Item -LiteralPath $temporary -Force }
    }
}

if ([string]::IsNullOrWhiteSpace($MetadataPath)) {
    $MetadataPath = Join-Path $repoFullPath "workshop\workshop-item.json"
}
$metadataFullPath = [IO.Path]::GetFullPath($MetadataPath)
$config = Read-StrictUtf8Json -Path $metadataFullPath
if ([string]$config.app_id -ne "2868840") { throw "Workshop metadata App ID must be 2868840." }
$version = [string]$config.version
if ($version -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Workshop metadata version is not a SemVer-like value: '$version'."
}
if ($null -eq $config.preview) { throw "Workshop metadata must contain a preview object with the previous artifact hash." }
$previewMetadata = $config.preview
$previousVersion = [string]$previewMetadata.version
$previousHash = [string]$previewMetadata.sha256
if ($previousVersion -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Workshop preview metadata has an invalid previous version: '$previousVersion'."
}
if ($previousHash -notmatch '^[0-9A-Fa-f]{64}$') {
    throw "Workshop preview metadata must contain a 64-character SHA-256 hash."
}
$historyRelative = [string]$previewMetadata.history_dir
if ([string]::IsNullOrWhiteSpace($historyRelative)) { throw "Workshop preview metadata must declare history_dir." }
$historyFullPath = Resolve-RepoPath -Value $historyRelative -Root $repoFullPath
Assert-RepoChildPath -Path $historyFullPath -Root $repoFullPath -Label "preview.history_dir"

$configuredOutputPath = Resolve-RepoPath -Value ([string]$config.preview_file) -Root $repoFullPath
if ([string]::IsNullOrWhiteSpace($OutputPath)) { $OutputPath = $configuredOutputPath }
$outputFullPath = [IO.Path]::GetFullPath($OutputPath)
$metadataOwnsOutput = [string]::Equals($outputFullPath, $configuredOutputPath, [StringComparison]::OrdinalIgnoreCase)
$heroPath = Join-Path $repoFullPath "assets\vivhite-ironclad\custom\character_select\sources\vivhite-character-select-hero-master-v1.png"
$transitionPath = Join-Path $repoFullPath "Vivhite\Vivhite\skins\ironclad\transitions\vivhite_character_select_transition.png"
foreach ($sourcePath in @($heroPath, $transitionPath)) {
    if (-not [IO.File]::Exists($sourcePath)) {
        throw "Required approved preview source is missing: $sourcePath"
    }
}
$heroHash = Get-Sha256Hex -Path $heroPath
$transitionHash = Get-Sha256Hex -Path $transitionPath
$outputExisted = [IO.File]::Exists($outputFullPath)
$oldOutputHash = ""
if ($outputExisted) {
    $oldOutputHash = Get-Sha256Hex -Path $outputFullPath
    if ($metadataOwnsOutput -and -not [string]::Equals($oldOutputHash, $previousHash, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Existing preview hash does not match workshop-item.json preview.sha256; refusing to overwrite an untracked artifact."
    }
}

Add-Type -AssemblyName System.Drawing
$canvas = [Drawing.Bitmap]::new(1024, 1024, [Drawing.Imaging.PixelFormat]::Format24bppRgb)
$graphics = [Drawing.Graphics]::FromImage($canvas)
$hero = $null
$transition = $null
$attributes = $null
$temporaryOutput = "$outputFullPath.$([Guid]::NewGuid().ToString('N')).tmp.jpg"
$archivedPath = ""
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
        foreach ($chip in @("61 CARDS", "3 BUILDS", "V$version")) {
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
        $canvas.Save($temporaryOutput, $jpegCodec, $parameters)
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

$newFile = [IO.FileInfo]::new($temporaryOutput)
if ($newFile.Length -ge 1000000) {
    Remove-Item -LiteralPath $temporaryOutput -Force -ErrorAction SilentlyContinue
    throw "Workshop preview exceeds Steam's 1 MB limit: $($newFile.Length) bytes."
}
$newHash = Get-Sha256Hex -Path $temporaryOutput

try {
    if ($metadataOwnsOutput) {
        [void][IO.Directory]::CreateDirectory($historyFullPath)
        $needsArchive = $outputExisted -and (
            -not [string]::Equals($oldOutputHash, $newHash, [StringComparison]::OrdinalIgnoreCase) -or
            -not [string]::Equals($previousVersion, $version, [StringComparison]::Ordinal))
        if ($needsArchive) {
            $archiveStem = "preview-v$previousVersion-sha256-$($oldOutputHash.ToLowerInvariant())"
            $archivedPath = Join-Path $historyFullPath "$archiveStem.jpg"
            if ([IO.File]::Exists($archivedPath)) {
                $existingArchiveHash = Get-Sha256Hex -Path $archivedPath
                if (-not [string]::Equals($existingArchiveHash, $oldOutputHash, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Preview history name collision has a different hash: $archivedPath"
                }
            }
            else { Copy-Item -LiteralPath $outputFullPath -Destination $archivedPath }
            $archiveRecord = [ordered]@{
                schema = 1
                artifact = "workshop/preview.jpg"
                version = $previousVersion
                sha256 = $oldOutputHash
                bytes = ([IO.FileInfo]::new($outputFullPath)).Length
                archived_utc = [DateTime]::UtcNow.ToString("O")
                hero_source_sha256 = [string]$previewMetadata.hero_source_sha256
                transition_source_sha256 = [string]$previewMetadata.transition_source_sha256
            }
            $archiveSidecar = "$archivedPath.json"
            if ([IO.File]::Exists($archiveSidecar)) {
                try {
                    $existingRecord = Read-StrictUtf8Json -Path $archiveSidecar
                    if ([string]$existingRecord.version -ne $previousVersion -or
                        -not [string]::Equals([string]$existingRecord.sha256, $oldOutputHash, [StringComparison]::OrdinalIgnoreCase) -or
                        [string]$existingRecord.hero_source_sha256 -ne [string]$archiveRecord.hero_source_sha256 -or
                        [string]$existingRecord.transition_source_sha256 -ne [string]$archiveRecord.transition_source_sha256) {
                        throw "Preview history sidecar collision has different provenance: $archiveSidecar"
                    }
                }
                catch {
                    throw "Preview history sidecar is invalid or conflicting: $archiveSidecar. $($_.Exception.Message)"
                }
            }
            else { Write-JsonAtomic -Path $archiveSidecar -Value $archiveRecord }
        }

        Move-Item -LiteralPath $temporaryOutput -Destination $outputFullPath -Force
        $newFile = [IO.FileInfo]::new($outputFullPath)
        $previewRecord = [ordered]@{
            version = $version
            sha256 = $newHash
            bytes = $newFile.Length
            width = 1024
            height = 1024
            history_dir = $historyRelative
            hero_source_sha256 = $heroHash
            transition_source_sha256 = $transitionHash
        }
        Set-ObjectProperty -Object $config -Name "preview" -Value ([pscustomobject]$previewRecord)
        Write-JsonAtomic -Path $metadataFullPath -Value $config
    }
    else {
        Move-Item -LiteralPath $temporaryOutput -Destination $outputFullPath -Force
        $newFile = [IO.FileInfo]::new($outputFullPath)
    }
}
catch {
    if ([IO.File]::Exists($temporaryOutput)) { Remove-Item -LiteralPath $temporaryOutput -Force -ErrorAction SilentlyContinue }
    throw
}

[pscustomobject]@{
    Path = $outputFullPath
    Version = $version
    Width = 1024
    Height = 1024
    Bytes = $newFile.Length
    SHA256 = $newHash
    ArchivedPath = $archivedPath
    MetadataPath = $metadataFullPath
    HeroSourceSHA256 = $heroHash
    TransitionSourceSHA256 = $transitionHash
} | Format-List
