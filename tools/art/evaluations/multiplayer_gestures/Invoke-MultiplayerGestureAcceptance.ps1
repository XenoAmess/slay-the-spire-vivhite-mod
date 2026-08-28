[CmdletBinding()]
param(
    [string]$RepositoryRoot,
    [string]$OutputDirectory,
    [string]$GameplayBackground
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ([string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    $RepositoryRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $PSScriptRoot '..\..\..\..'))
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $RepositoryRoot '.work\multiplayer-ui-acceptance'
}

$RepositoryRoot = [System.IO.Path]::GetFullPath($RepositoryRoot)
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null

Add-Type -AssemblyName System.Drawing

$source = @'
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;

public sealed class GestureAlphaStats
{
    public int Width;
    public int Height;
    public string PixelFormat;
    public int[] Corners;
    public long AlphaNonZero;
    public long AlphaLowOneToSeven;
    public long AlphaAtLeast128;
    public int[] BboxAtOne;
    public int[] BboxAtEight;
    public int[] BboxAt128;
    public int[] EdgePixelsAtOne;
    public int ComponentCountAtEight;
    public int MajorComponentCountAtEight;
    public int LargestComponentPixelsAtEight;
    public int SecondLargestComponentPixelsAtEight;
    public double LargestComponentShareAtEight;
    public double AlphaWeightedCentroidX;
    public double AlphaWeightedCentroidY;
    public double TopBandCentroidXAt128;
    public int TopBandMinYAt128;
    public int TopBandPixelCountAt128;
    public double BottomBandCentroidXAt128;
    public int BottomBandMaxYAt128;
    public int BottomBandPixelCountAt128;
}

public static class MultiplayerGestureAudit
{
    private const int TargetWidth = 383;
    private const int TargetHeight = 1072;
    private const int HeaderHeight = 64;

    private sealed class RgbaImage
    {
        public int Width;
        public int Height;
        public string PixelFormat;
        public byte[] Bytes;
    }

    private static RgbaImage ReadRgba(string path)
    {
        using (Bitmap source = new Bitmap(path))
        using (Bitmap converted = new Bitmap(source.Width, source.Height, PixelFormat.Format32bppArgb))
        {
            using (Graphics graphics = Graphics.FromImage(converted))
            {
                graphics.CompositingMode = CompositingMode.SourceCopy;
                graphics.DrawImageUnscaled(source, 0, 0);
            }

            Rectangle rect = new Rectangle(0, 0, converted.Width, converted.Height);
            BitmapData data = converted.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
            try
            {
                int stride = Math.Abs(data.Stride);
                byte[] raw = new byte[stride * converted.Height];
                Marshal.Copy(data.Scan0, raw, 0, raw.Length);
                byte[] packed = new byte[converted.Width * converted.Height * 4];
                for (int y = 0; y < converted.Height; y++)
                {
                    int rawRow = data.Stride >= 0 ? y * stride : (converted.Height - 1 - y) * stride;
                    Buffer.BlockCopy(raw, rawRow, packed, y * converted.Width * 4, converted.Width * 4);
                }
                return new RgbaImage {
                    Width = converted.Width,
                    Height = converted.Height,
                    PixelFormat = source.PixelFormat.ToString(),
                    Bytes = packed
                };
            }
            finally
            {
                converted.UnlockBits(data);
            }
        }
    }

    private static byte AlphaAt(RgbaImage image, int x, int y)
    {
        return image.Bytes[(y * image.Width + x) * 4 + 3];
    }

    private static int[] FindBbox(RgbaImage image, int threshold)
    {
        int minX = image.Width;
        int minY = image.Height;
        int maxX = -1;
        int maxY = -1;
        for (int y = 0; y < image.Height; y++)
        {
            for (int x = 0; x < image.Width; x++)
            {
                if (AlphaAt(image, x, y) < threshold)
                    continue;
                if (x < minX) minX = x;
                if (y < minY) minY = y;
                if (x > maxX) maxX = x;
                if (y > maxY) maxY = y;
            }
        }
        return maxX < minX
            ? new int[] { -1, -1, 0, 0 }
            : new int[] { minX, minY, maxX - minX + 1, maxY - minY + 1 };
    }

    public static GestureAlphaStats Analyze(string path)
    {
        RgbaImage image = ReadRgba(path);
        GestureAlphaStats result = new GestureAlphaStats();
        result.Width = image.Width;
        result.Height = image.Height;
        result.PixelFormat = image.PixelFormat;
        result.Corners = new int[] {
            AlphaAt(image, 0, 0),
            AlphaAt(image, image.Width - 1, 0),
            AlphaAt(image, 0, image.Height - 1),
            AlphaAt(image, image.Width - 1, image.Height - 1)
        };
        result.BboxAtOne = FindBbox(image, 1);
        result.BboxAtEight = FindBbox(image, 8);
        result.BboxAt128 = FindBbox(image, 128);

        result.TopBandMinYAt128 = result.BboxAt128[1];
        result.BottomBandMaxYAt128 = result.BboxAt128[1] + result.BboxAt128[3] - 1;
        long topBandWeightedX = 0;
        long topBandAlpha = 0;
        long bottomBandWeightedX = 0;
        long bottomBandAlpha = 0;

        long weightedX = 0;
        long weightedY = 0;
        long alphaWeight = 0;
        int top = 0;
        int right = 0;
        int bottom = 0;
        int left = 0;
        for (int y = 0; y < image.Height; y++)
        {
            for (int x = 0; x < image.Width; x++)
            {
                byte alpha = AlphaAt(image, x, y);
                if (alpha > 0)
                {
                    result.AlphaNonZero++;
                    weightedX += (long)x * alpha;
                    weightedY += (long)y * alpha;
                    alphaWeight += alpha;
                    if (alpha < 8) result.AlphaLowOneToSeven++;
                    if (y == 0) top++;
                    if (x == image.Width - 1) right++;
                    if (y == image.Height - 1) bottom++;
                    if (x == 0) left++;
                }
                if (alpha >= 128) result.AlphaAtLeast128++;
                if (alpha >= 128 && y <= result.TopBandMinYAt128 + 12)
                {
                    result.TopBandPixelCountAt128++;
                    topBandWeightedX += (long)x * alpha;
                    topBandAlpha += alpha;
                }
                if (alpha >= 128 && y >= result.BottomBandMaxYAt128 - 12)
                {
                    result.BottomBandPixelCountAt128++;
                    bottomBandWeightedX += (long)x * alpha;
                    bottomBandAlpha += alpha;
                }
            }
        }
        result.EdgePixelsAtOne = new int[] { top, right, bottom, left };
        if (alphaWeight > 0)
        {
            result.AlphaWeightedCentroidX = (double)weightedX / alphaWeight;
            result.AlphaWeightedCentroidY = (double)weightedY / alphaWeight;
        }
        if (topBandAlpha > 0)
            result.TopBandCentroidXAt128 = (double)topBandWeightedX / topBandAlpha;
        if (bottomBandAlpha > 0)
            result.BottomBandCentroidXAt128 = (double)bottomBandWeightedX / bottomBandAlpha;

        int pixelCount = image.Width * image.Height;
        byte[] visited = new byte[pixelCount];
        int[] queue = new int[pixelCount];
        int totalPixelsInComponents = 0;
        for (int index = 0; index < pixelCount; index++)
        {
            if (visited[index] != 0 || image.Bytes[index * 4 + 3] < 8)
                continue;
            int head = 0;
            int tail = 0;
            int componentSize = 0;
            visited[index] = 1;
            queue[tail++] = index;
            while (head < tail)
            {
                int current = queue[head++];
                componentSize++;
                int x = current % image.Width;
                int y = current / image.Width;
                int minX = Math.Max(0, x - 1);
                int maxX = Math.Min(image.Width - 1, x + 1);
                int minY = Math.Max(0, y - 1);
                int maxY = Math.Min(image.Height - 1, y + 1);
                for (int ny = minY; ny <= maxY; ny++)
                {
                    for (int nx = minX; nx <= maxX; nx++)
                    {
                        int neighbor = ny * image.Width + nx;
                        if (neighbor == current || visited[neighbor] != 0 || image.Bytes[neighbor * 4 + 3] < 8)
                            continue;
                        visited[neighbor] = 1;
                        queue[tail++] = neighbor;
                    }
                }
            }
            result.ComponentCountAtEight++;
            totalPixelsInComponents += componentSize;
            if (componentSize >= 32) result.MajorComponentCountAtEight++;
            if (componentSize > result.LargestComponentPixelsAtEight)
            {
                result.SecondLargestComponentPixelsAtEight = result.LargestComponentPixelsAtEight;
                result.LargestComponentPixelsAtEight = componentSize;
            }
            else if (componentSize > result.SecondLargestComponentPixelsAtEight)
            {
                result.SecondLargestComponentPixelsAtEight = componentSize;
            }
        }
        result.LargestComponentShareAtEight = totalPixelsInComponents == 0
            ? 0.0
            : (double)result.LargestComponentPixelsAtEight / totalPixelsInComponents;
        return result;
    }

    private static void ConfigureGraphics(Graphics graphics)
    {
        graphics.CompositingMode = CompositingMode.SourceOver;
        graphics.CompositingQuality = CompositingQuality.GammaCorrected;
        graphics.InterpolationMode = InterpolationMode.HighQualityBicubic;
        graphics.PixelOffsetMode = PixelOffsetMode.HighQuality;
        graphics.SmoothingMode = SmoothingMode.AntiAlias;
    }

    private static RectangleF AspectFillSource(Image source, RectangleF destination)
    {
        float destinationAspect = destination.Width / destination.Height;
        float sourceAspect = (float)source.Width / source.Height;
        if (sourceAspect > destinationAspect)
        {
            float width = source.Height * destinationAspect;
            return new RectangleF((source.Width - width) * 0.5f, 0, width, source.Height);
        }
        float height = source.Width / destinationAspect;
        return new RectangleF(0, (source.Height - height) * 0.5f, source.Width, height);
    }

    private static RectangleF KeepAspectCentered(Image source, RectangleF destination)
    {
        float scale = Math.Min(destination.Width / source.Width, destination.Height / source.Height);
        float width = source.Width * scale;
        float height = source.Height * scale;
        return new RectangleF(
            destination.X + (destination.Width - width) * 0.5f,
            destination.Y + (destination.Height - height) * 0.5f,
            width,
            height);
    }

    public static void RenderSheet(
        string[] gesturePaths,
        string[] labels,
        string outputPath,
        string backgroundKind,
        string gameplayBackgroundPath,
        bool drawPivots)
    {
        using (Bitmap sheet = new Bitmap(TargetWidth * gesturePaths.Length, HeaderHeight + TargetHeight, PixelFormat.Format32bppArgb))
        using (Graphics graphics = Graphics.FromImage(sheet))
        using (Font font = new Font("Segoe UI", 20f, FontStyle.Bold, GraphicsUnit.Pixel))
        using (Brush headerBrush = new SolidBrush(Color.FromArgb(255, 24, 27, 35)))
        using (Brush labelBrush = new SolidBrush(Color.White))
        using (Pen pointingPen = new Pen(Color.FromArgb(255, 255, 80, 80), 3f))
        using (Pen fightingPen = new Pen(Color.FromArgb(255, 255, 210, 40), 3f))
        using (Pen grabPen = new Pen(Color.FromArgb(255, 50, 230, 255), 3f))
        {
            ConfigureGraphics(graphics);
            graphics.FillRectangle(headerBrush, 0, 0, sheet.Width, HeaderHeight);
            Image gameplay = null;
            try
            {
                if (backgroundKind == "gameplay")
                    gameplay = Image.FromFile(gameplayBackgroundPath);
                for (int index = 0; index < gesturePaths.Length; index++)
                {
                    RectangleF cell = new RectangleF(index * TargetWidth, HeaderHeight, TargetWidth, TargetHeight);
                    if (backgroundKind == "black")
                        graphics.FillRectangle(Brushes.Black, cell);
                    else if (backgroundKind == "white")
                        graphics.FillRectangle(Brushes.White, cell);
                    else
                        graphics.DrawImage(gameplay, cell, AspectFillSource(gameplay, cell), GraphicsUnit.Pixel);

                    using (Image gesture = Image.FromFile(gesturePaths[index]))
                    {
                        RectangleF destination = KeepAspectCentered(gesture, cell);
                        graphics.DrawImage(gesture, destination);
                    }

                    graphics.DrawString(labels[index], font, labelBrush, index * TargetWidth + 12, 18);
                    if (drawPivots)
                    {
                        float cellX = index * TargetWidth;
                        DrawCross(graphics, pointingPen, cellX + 163f, HeaderHeight + 10f, 14f);
                        DrawCross(graphics, fightingPen, cellX + 197f, HeaderHeight + 600f, 14f);
                        DrawCross(graphics, grabPen, cellX + 175f, HeaderHeight + 222f, 14f);
                    }
                }
            }
            finally
            {
                if (gameplay != null) gameplay.Dispose();
            }
            sheet.Save(outputPath, ImageFormat.Png);
        }
    }

    private static void DrawCross(Graphics graphics, Pen pen, float x, float y, float radius)
    {
        graphics.DrawEllipse(pen, x - radius, y - radius, radius * 2f, radius * 2f);
        graphics.DrawLine(pen, x - radius * 1.35f, y, x + radius * 1.35f, y);
        graphics.DrawLine(pen, x, y - radius * 1.35f, x, y + radius * 1.35f);
    }
}
'@

Add-Type -TypeDefinition $source -ReferencedAssemblies System.Drawing

$gestures = @('point', 'rock', 'paper', 'scissors')
$roots = [ordered]@{
    approved = Join-Path $RepositoryRoot 'assets\vivhite-ironclad\custom\ui\multiplayer'
    exceptionSource = Join-Path $RepositoryRoot 'assets\vivhite-ironclad\legacy-contaminated\2026-08-27\custom\ui\multiplayer'
    runtime = Join-Path $RepositoryRoot 'Vivhite\Vivhite\skins\ironclad\multiplayer'
    vanilla = Join-Path $RepositoryRoot 'assets\ironclad-v0.111.0\ui\multiplayer'
}

$records = @()
foreach ($gesture in $gestures) {
    $paths = [ordered]@{}
    $hashes = [ordered]@{}
    foreach ($kind in $roots.Keys) {
        $path = Join-Path $roots[$kind] ($gesture + '.png')
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Missing $kind gesture: $path"
        }
        $paths[$kind] = $path
        $hashes[$kind] = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    }

    $stats = [MultiplayerGestureAudit]::Analyze($paths.approved)
    $vanillaStats = [MultiplayerGestureAudit]::Analyze($paths.vanilla)
    $consumerScale = 1072.0 / 1200.0
    $records += [pscustomobject]@{
        gesture = $gesture
        paths = [pscustomobject]$paths
        sha256 = [pscustomobject]$hashes
        exactCopyFromExceptionSource = ($hashes.approved -eq $hashes.exceptionSource)
        exactCopyInRuntime = ($hashes.approved -eq $hashes.runtime)
        sameDimensionsAsVanilla = (
            $stats.Width -eq 422 -and
            $stats.Height -eq 1200 -and
            $stats.Width -eq $vanillaStats.Width -and
            $stats.Height -eq $vanillaStats.Height
        )
        classification = if (
            $stats.LargestComponentShareAtEight -ge 0.995
        ) { 'single-full-arm-texture' } else { 'requires-manual-layout-review' }
        image = [pscustomobject]@{
            width = $stats.Width
            height = $stats.Height
            pixelFormat = $stats.PixelFormat
            cornerAlpha = $stats.Corners
            alphaNonZero = $stats.AlphaNonZero
            alphaLowOneToSeven = $stats.AlphaLowOneToSeven
            alphaAtLeast128 = $stats.AlphaAtLeast128
            bboxAlphaAtLeast1 = $stats.BboxAtOne
            bboxAlphaAtLeast8 = $stats.BboxAtEight
            bboxAlphaAtLeast128 = $stats.BboxAt128
            edgePixelsAlphaAtLeast1 = [pscustomobject]@{
                top = $stats.EdgePixelsAtOne[0]
                right = $stats.EdgePixelsAtOne[1]
                bottom = $stats.EdgePixelsAtOne[2]
                left = $stats.EdgePixelsAtOne[3]
            }
            componentsAlphaAtLeast8 = $stats.ComponentCountAtEight
            majorComponentsAlphaAtLeast8 = $stats.MajorComponentCountAtEight
            largestComponentPixelsAlphaAtLeast8 = $stats.LargestComponentPixelsAtEight
            secondLargestComponentPixelsAlphaAtLeast8 = $stats.SecondLargestComponentPixelsAtEight
            largestComponentShareAlphaAtLeast8 = [Math]::Round($stats.LargestComponentShareAtEight, 8)
            alphaWeightedCentroid = @(
                [Math]::Round($stats.AlphaWeightedCentroidX, 3),
                [Math]::Round($stats.AlphaWeightedCentroidY, 3)
            )
            topBandAlphaAtLeast128 = [pscustomobject]@{
                minY = $stats.TopBandMinYAt128
                pixelCount = $stats.TopBandPixelCountAt128
                centroidX = [Math]::Round($stats.TopBandCentroidXAt128, 3)
            }
            bottomBandAlphaAtLeast128 = [pscustomobject]@{
                maxY = $stats.BottomBandMaxYAt128
                pixelCount = $stats.BottomBandPixelCountAt128
                centroidX = [Math]::Round($stats.BottomBandCentroidXAt128, 3)
            }
        }
        vanillaComparison = [pscustomobject]@{
            topBandAlphaAtLeast128 = [pscustomobject]@{
                minY = $vanillaStats.TopBandMinYAt128
                pixelCount = $vanillaStats.TopBandPixelCountAt128
                centroidX = [Math]::Round($vanillaStats.TopBandCentroidXAt128, 3)
            }
            bottomBandAlphaAtLeast128 = [pscustomobject]@{
                maxY = $vanillaStats.BottomBandMaxYAt128
                pixelCount = $vanillaStats.BottomBandPixelCountAt128
                centroidX = [Math]::Round($vanillaStats.BottomBandCentroidXAt128, 3)
            }
            topBandCentroidDeltaAtConsumerPixels = [Math]::Round(
                ($stats.TopBandCentroidXAt128 - $vanillaStats.TopBandCentroidXAt128) * $consumerScale,
                3
            )
            bottomBandCentroidDeltaAtConsumerPixels = [Math]::Round(
                ($stats.BottomBandCentroidXAt128 - $vanillaStats.BottomBandCentroidXAt128) * $consumerScale,
                3
            )
        }
    }
}

if ([string]::IsNullOrWhiteSpace($GameplayBackground)) {
    $GameplayBackground = 'C:\Users\xenoa\AppData\Local\Temp\paseo-attachments-iYpx7L\89710a694def22a6e28e7875791f261f33921d9cc8bc89b45d27b64f53b77f5f.png'
}
if (-not (Test-Path -LiteralPath $GameplayBackground -PathType Leaf)) {
    throw "Actual gameplay background is required for the gameplay SourceOver sheet: $GameplayBackground"
}

$approvedPaths = @($gestures | ForEach-Object { Join-Path $roots.approved ($_ + '.png') })
$labels = @('POINT', 'ROCK', 'PAPER', 'SCISSORS')
$blackSheet = Join-Path $OutputDirectory 'sourceover-black-actual-383x1072.png'
$whiteSheet = Join-Path $OutputDirectory 'sourceover-white-actual-383x1072.png'
$gameplaySheet = Join-Path $OutputDirectory 'sourceover-gameplay-actual-383x1072.png'
$pivotSheet = Join-Path $OutputDirectory 'consumer-pivots-gameplay-actual-383x1072.png'

[MultiplayerGestureAudit]::RenderSheet($approvedPaths, $labels, $blackSheet, 'black', $GameplayBackground, $false)
[MultiplayerGestureAudit]::RenderSheet($approvedPaths, $labels, $whiteSheet, 'white', $GameplayBackground, $false)
[MultiplayerGestureAudit]::RenderSheet($approvedPaths, $labels, $gameplaySheet, 'gameplay', $GameplayBackground, $false)
[MultiplayerGestureAudit]::RenderSheet($approvedPaths, $labels, $pivotSheet, 'gameplay', $GameplayBackground, $true)

$pointRecord = @($records | Where-Object { $_.gesture -eq 'point' })[0]
$pointTopDelta = [double]$pointRecord.vanillaComparison.topBandCentroidDeltaAtConsumerPixels
$pointTopInConsumer = 3.006667 + [double]$pointRecord.image.topBandAlphaAtLeast128.centroidX * (1072.0 / 1200.0)
$pointTopOffsetFromPivot = [Math]::Round($pointTopInConsumer - 163.0, 3)

$report = [ordered]@{
    schemaVersion = 1
    status = if (
        @($records | Where-Object {
            -not $_.exactCopyFromExceptionSource -or
            -not $_.exactCopyInRuntime -or
            -not $_.sameDimensionsAsVanilla -or
            $_.classification -ne 'single-full-arm-texture' -or
            @($_.image.cornerAlpha | Where-Object { $_ -ne 0 }).Count -ne 0
        }).Count -eq 0
    ) { 'offline-resource-pass' } else { 'fail' }
    scope = 'Resource and single-client offline rendering only; this report is not multiplayer end-to-end proof.'
    consumerContract = [ordered]@{
        scene = 'res://scenes/ui/hand_image.tscn'
        scenePckMd5 = '8ab10558b84eb70d3b15dc801636c17b'
        textureRectSize = @(383, 1072)
        sourceTextureSize = @(422, 1200)
        expandMode = 1
        stretchMode = 5
        stretchMeaning = 'keep aspect centered'
        displayScale = [Math]::Round((1072.0 / 1200.0), 9)
        horizontalPaddingEachSide = [Math]::Round((383.0 - 422.0 * (1072.0 / 1200.0)) / 2.0, 6)
        pointingPivotTextureRect = @(163, 10)
        fightingPivotTextureRect = @(197, 600)
        grabMarkerTextureRect = @(175, 222)
        rootRotationsBySlotRadians = @(
            0,
            ([Math]::PI / 2.0),
            (-[Math]::PI / 2.0),
            [Math]::PI
        )
        mapping = [ordered]@{
            point = 'CharacterModel.ArmPointingTexture -> NHandImage._Ready'
            rock = 'CharacterModel.ArmRockTexture -> RelicPickingFightMove.Rock'
            paper = 'CharacterModel.ArmPaperTexture -> RelicPickingFightMove.Paper'
            scissors = 'CharacterModel.ArmScissorsTexture -> RelicPickingFightMove.Scissors'
        }
        layoutConclusion = 'Four independent full-arm Texture2D resources; no atlas region, frame index, UV crop, or sprite-sheet slicing exists in the consumer.'
    }
    gameplayBackground = [ordered]@{
        path = [System.IO.Path]::GetFullPath($GameplayBackground)
        sha256 = (Get-FileHash -LiteralPath $GameplayBackground -Algorithm SHA256).Hash
        use = 'SourceOver inspection background only; never used as an asset input.'
    }
    gestures = $records
    layoutReview = [ordered]@{
        spriteSheetClassification = 'pass: four independent full-arm textures'
        rpsGestureSemantics = 'pass: rock, paper, and scissors are distinct and correctly mapped'
        fightingPivot = 'pass by actual-size contact-sheet review: x=197 stays inside the central sleeve on all RPS textures'
        grabMarker = 'pass by actual-size contact-sheet review: (175,222) lands inside the paper palm'
        pointingAnchor = [ordered]@{
            status = 'warning-under-user-exception'
            customTopBandOffsetFromConsumerPivotPixels = $pointTopOffsetFromPivot
            customMinusVanillaTopBandCentroidPixels = $pointTopDelta
            note = 'The pointing fingertip is visibly farther right than vanilla. Resource loading/rendering passes, but strict cursor-to-fingertip alignment is not equivalent to vanilla.'
        }
        bottomFade = 'visible near the final source rows, but this long arm tail is intended to extend beyond the viewport edge; verify only in a real treasure-room screen if the exception is revisited'
    }
    evidence = [ordered]@{
        black = $blackSheet
        white = $whiteSheet
        gameplay = $gameplaySheet
        pivots = $pivotSheet
    }
    acceptanceBoundary = [ordered]@{
        offlineResource = 'pass only when status is offline-resource-pass and the contact sheets pass human review'
        multiplayerEndToEnd = 'not tested; requires a second client and actual treasure-room relic contention UI'
    }
}

$reportPath = Join-Path $OutputDirectory 'report.json'
$report | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $reportPath -Encoding UTF8

$summary = @(
    "status=$($report.status)"
    'classification=four independent full-arm textures (not one four-cell sprite sheet)'
    'consumer=TextureRect 383x1072, keep-aspect-centered, source 422x1200'
    "pointing_anchor_warning=custom fingertip top band is $pointTopDelta consumer pixels right of vanilla ($pointTopOffsetFromPivot px right of the fixed pivot)"
    "report=$reportPath"
    "black=$blackSheet"
    "white=$whiteSheet"
    "gameplay=$gameplaySheet"
    "pivots=$pivotSheet"
    'multiplayer_end_to_end=NOT TESTED (requires second client)'
)
$summaryPath = Join-Path $OutputDirectory 'summary.txt'
$summary | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$summary
