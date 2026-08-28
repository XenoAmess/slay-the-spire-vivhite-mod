[CmdletBinding()]
param(
    [ValidateSet("Source", "Pck", "All")]
    [string]$Phase = "Source",

    [string]$ProjectDir = "",

    [string]$ContractPath = "",

    [string]$RuntimeLayout = "",

    [string]$PckPath = "",

    [string]$GodotExe = "",

    [string]$Sts2Dir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = Split-Path -Parent $PSScriptRoot
}
if ([string]::IsNullOrWhiteSpace($ContractPath)) {
    $ContractPath = Join-Path $PSScriptRoot "ironclad-skin.contract.json"
}

$script:ValidationErrors = New-Object "System.Collections.Generic.List[string]"

function Add-ValidationError {
    param([Parameter(Mandatory = $true)][string]$Message)

    $script:ValidationErrors.Add($Message)
}

function Stop-Validation {
    param([Parameter(Mandatory = $true)][string]$Title)

    Write-Host "[ironclad-skin] $Title" -ForegroundColor Red
    foreach ($message in $script:ValidationErrors) {
        Write-Host "  - $message" -ForegroundColor Red
    }

    exit 1
}

function Get-SafeChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath) -or [IO.Path]::IsPathRooted($RelativePath)) {
        throw "Expected a non-empty relative path, got '$RelativePath'."
    }

    $normalized = $RelativePath.Replace('/', [IO.Path]::DirectorySeparatorChar)
    $baseFull = [IO.Path]::GetFullPath($BasePath).TrimEnd([IO.Path]::DirectorySeparatorChar)
    $full = [IO.Path]::GetFullPath((Join-Path $baseFull $normalized))
    $prefix = $baseFull + [IO.Path]::DirectorySeparatorChar
    if (-not $full.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path '$RelativePath' escapes '$baseFull'."
    }

    return $full
}

function Get-ResourcePath {
    param(
        [Parameter(Mandatory = $true)][string]$ResourceRoot,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    return "res://$($ResourceRoot.Trim('/'))/$($RelativePath.TrimStart('/'))"
}

function Get-PrivateResourceRelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$ResourceRoot,
        [Parameter(Mandatory = $true)][string]$ResourcePath,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $normalizedRoot = $ResourceRoot.Replace('\', '/').Trim('/')
    $normalizedPath = $ResourcePath.Replace('\', '/')
    $privatePrefix = "res://$normalizedRoot/"
    if (-not $normalizedPath.StartsWith($privatePrefix, [StringComparison]::Ordinal)) {
        throw "$Label must be private below '$privatePrefix', got '$ResourcePath'."
    }

    $relativePath = $normalizedPath.Substring($privatePrefix.Length)
    if ([string]::IsNullOrWhiteSpace($relativePath) -or
        $relativePath.StartsWith('/', [StringComparison]::Ordinal) -or
        $relativePath.StartsWith('../', [StringComparison]::Ordinal) -or
        [string]::Equals($relativePath, '..', [StringComparison]::Ordinal) -or
        $relativePath.Contains("../") -or
        $relativePath.Contains("/..")) {
        throw "$Label has an invalid private resource path: '$ResourcePath'."
    }

    return $relativePath
}

function Add-RequiredPath {
    param(
        [Parameter(Mandatory = $true)]$Set,
        [Parameter(Mandatory = $true)][string]$RelativePath
    )

    if ([string]::IsNullOrWhiteSpace($RelativePath)) {
        Add-ValidationError "The contract contains an empty asset path."
        return
    }

    [void]$Set.Add($RelativePath.Replace('\', '/').TrimStart('/'))
}

function Get-ExpectedLogicalAssets {
    param([Parameter(Mandatory = $true)]$Contract)

    $required = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    foreach ($relativePath in @($Contract.requiredResources)) {
        Add-RequiredPath -Set $required -RelativePath ([string]$relativePath)
    }
    foreach ($binding in @($Contract.sceneBindings)) {
        Add-RequiredPath -Set $required -RelativePath ([string]$binding.scene)
        Add-RequiredPath -Set $required -RelativePath ([string]$binding.skeletonData)
    }
    $resourceRoot = ([string]$Contract.resourceRoot).Replace('\', '/').Trim('/')
    foreach ($spineSet in @($Contract.spineSets)) {
        Add-RequiredPath -Set $required -RelativePath ([string]$spineSet.skeletonData)
        Add-RequiredPath -Set $required -RelativePath ([string]$spineSet.atlas)
        try {
            $skeletonRelative = Get-PrivateResourceRelativePath `
                -ResourceRoot $resourceRoot `
                -ResourcePath ([string]$spineSet.skeletonResource) `
                -Label "Spine set '$([string]$spineSet.name)' skeletonResource"
            Add-RequiredPath -Set $required -RelativePath $skeletonRelative
        }
        catch {
            Add-ValidationError $_.Exception.Message
        }
        foreach ($page in @($spineSet.pages)) {
            Add-RequiredPath -Set $required -RelativePath ([string]$page)
        }
    }

    $expectedCountValue = Get-JsonPropertyValue -Object $Contract -Name "expectedRuntimeFileCount"
    if ($null -eq $expectedCountValue -or [int]$expectedCountValue -le 0) {
        Add-ValidationError "The contract must declare a positive expectedRuntimeFileCount."
    }
    elseif ($required.Count -ne [int]$expectedCountValue) {
        Add-ValidationError (
            "Runtime layout '$([string]$Contract.runtimeLayout)' resolves to $($required.Count) files; " +
            "expected exactly $([int]$expectedCountValue).")
    }

    return $required
}

function Get-SkinActivationState {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)]$Contract
    )

    $resourceRoot = ([string]$Contract.resourceRoot).Replace('\', '/').Trim('/')
    $assetRoot = Get-SafeChildPath -BasePath $ProjectRoot -RelativePath $resourceRoot
    if (-not [IO.Directory]::Exists($assetRoot)) {
        return [pscustomobject]@{
            Active = $false
            AssetRoot = $assetRoot
            Reason = "resource root does not exist"
        }
    }

    $activationMarker = ([string]$Contract.activationMarker).Replace('\', '/').TrimStart('/')
    $ignored = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    foreach ($relativePath in @($Contract.inactiveDocumentationFiles)) {
        [void]$ignored.Add(([string]$relativePath).Replace('\', '/').TrimStart('/'))
    }

    $markerPath = Get-SafeChildPath -BasePath $assetRoot -RelativePath $activationMarker
    if ([IO.File]::Exists($markerPath)) {
        return [pscustomobject]@{
            Active = $true
            AssetRoot = $assetRoot
            Reason = "activation marker '$activationMarker' exists"
        }
    }

    foreach ($file in Get-ChildItem -LiteralPath $assetRoot -File -Recurse -Force) {
        $relative = $file.FullName.Substring($assetRoot.Length).TrimStart('\', '/').Replace('\', '/')
        if (-not $ignored.Contains($relative)) {
            return [pscustomobject]@{
                Active = $true
                AssetRoot = $assetRoot
                Reason = "asset '$relative' exists"
            }
        }
    }

    return [pscustomobject]@{
        Active = $false
        AssetRoot = $assetRoot
        Reason = "only inactive documentation files exist"
    }
}

function Get-BigEndianUInt32 {
    param(
        [Parameter(Mandatory = $true)][byte[]]$Bytes,
        [Parameter(Mandatory = $true)][int]$Offset
    )

    if ($Offset -lt 0 -or ($Offset + 4) -gt $Bytes.Length) {
        throw "Cannot read a big-endian UInt32 at offset $Offset from $($Bytes.Length) bytes."
    }

    return [uint32]((([uint32]$Bytes[$Offset]) -shl 24) -bor
        (([uint32]$Bytes[$Offset + 1]) -shl 16) -bor
        (([uint32]$Bytes[$Offset + 2]) -shl 8) -bor
        ([uint32]$Bytes[$Offset + 3]))
}

function Get-PngDimensions {
    param([Parameter(Mandatory = $true)][string]$Path)

    $expected = [byte[]](137, 80, 78, 71, 13, 10, 26, 10)
    $stream = [IO.File]::OpenRead($Path)
    try {
        # PNG signature + IHDR length/type/data/CRC. Dimensions are the first
        # two big-endian UInt32 values in the mandatory 13-byte IHDR payload.
        if ($stream.Length -lt 33) {
            throw "PNG is too small to contain a complete IHDR chunk."
        }
        $header = $null
        $header = [byte[]]::new(33)
        $totalRead = 0
        while ($totalRead -lt $header.Length) {
            $read = $stream.Read($header, $totalRead, $header.Length - $totalRead)
            if ($read -eq 0) {
                throw "Unexpected end of PNG while reading IHDR."
            }
            $totalRead += $read
        }

        for ($i = 0; $i -lt $expected.Length; $i++) {
            if ($header[$i] -ne $expected[$i]) {
                throw "PNG signature is invalid."
            }
        }
        if ((Get-BigEndianUInt32 -Bytes $header -Offset 8) -ne 13) {
            throw "The first PNG chunk is not a 13-byte IHDR chunk."
        }
        $chunkType = [Text.Encoding]::ASCII.GetString($header, 12, 4)
        if (-not [string]::Equals($chunkType, "IHDR", [StringComparison]::Ordinal)) {
            throw "The first PNG chunk is '$chunkType', expected 'IHDR'."
        }

        $width = Get-BigEndianUInt32 -Bytes $header -Offset 16
        $height = Get-BigEndianUInt32 -Bytes $header -Offset 20
        if ($width -eq 0 -or $height -eq 0 -or $width -gt [int]::MaxValue -or $height -gt [int]::MaxValue) {
            throw "PNG IHDR dimensions are invalid: ${width}x${height}."
        }

        return [pscustomobject]@{
            Width = [int]$width
            Height = [int]$height
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Get-ExpectedPngDimensions {
    param(
        [Parameter(Mandatory = $true)]$Contract,
        [Parameter(Mandatory = $true)]$ExpectedAssets
    )

    $dimensions = New-Object "System.Collections.Generic.Dictionary[string,object]" ([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in @($Contract.pngDimensions)) {
        $relativePath = ([string]$entry.path).Replace('\', '/').TrimStart('/')
        $width = [int64]$entry.width
        $height = [int64]$entry.height
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            Add-ValidationError "The PNG dimension contract contains an empty path."
            continue
        }
        if (-not $relativePath.EndsWith(".png", [StringComparison]::OrdinalIgnoreCase)) {
            Add-ValidationError "PNG dimension contract path is not a PNG: $relativePath"
            continue
        }
        if (-not $ExpectedAssets.Contains($relativePath)) {
            Add-ValidationError "PNG dimension contract references a non-runtime asset: $relativePath"
        }
        if ($width -le 0 -or $height -le 0 -or $width -gt [int]::MaxValue -or $height -gt [int]::MaxValue) {
            Add-ValidationError "PNG dimension contract has invalid dimensions for '$relativePath': ${width}x${height}."
            continue
        }
        if ($dimensions.ContainsKey($relativePath)) {
            Add-ValidationError "PNG dimension contract contains a duplicate path: $relativePath"
            continue
        }
        $dimensions.Add($relativePath, [pscustomobject]@{
                Width = [int]$width
                Height = [int]$height
            })
    }

    foreach ($relativePath in $ExpectedAssets) {
        if ($relativePath.EndsWith(".png", [StringComparison]::OrdinalIgnoreCase) -and
            -not $dimensions.ContainsKey($relativePath)) {
            Add-ValidationError "PNG dimension contract is missing runtime asset: $relativePath"
        }
    }

    return $dimensions
}

function Test-SpineAtlasLayout {
    param(
        [Parameter(Mandatory = $true)][string]$SetName,
        [Parameter(Mandatory = $true)][string]$AtlasData,
        [Parameter(Mandatory = $true)]$SpineSet,
        [Parameter(Mandatory = $true)]$PngDimensions
    )

    $expectedPages = New-Object "System.Collections.Generic.Dictionary[string,string]" ([StringComparer]::Ordinal)
    $expectedPageOrder = New-Object "System.Collections.Generic.List[string]"
    foreach ($page in @($SpineSet.pages)) {
        $relativePath = ([string]$page).Replace('\', '/').TrimStart('/')
        $pageName = [IO.Path]::GetFileName($relativePath)
        if ($expectedPages.ContainsKey($pageName)) {
            Add-ValidationError "Spine set '$SetName' declares duplicate atlas page name '$pageName'."
            continue
        }
        $expectedPages.Add($pageName, $relativePath)
        $expectedPageOrder.Add($pageName)
    }

    $pageLayoutsValue = Get-JsonPropertyValue -Object $SpineSet -Name "pageLayouts"
    $pageLayouts = @()
    if ($null -ne $pageLayoutsValue) {
        $pageLayouts = @($pageLayoutsValue)
    }
    $expectedLayouts = New-Object "System.Collections.Generic.Dictionary[string,object]" ([StringComparer]::Ordinal)
    foreach ($layout in $pageLayouts) {
        $layoutPath = ([string]$layout.path).Replace('\', '/').TrimStart('/')
        $layoutPageName = [IO.Path]::GetFileName($layoutPath)
        if (-not $expectedPages.ContainsKey($layoutPageName) -or
            -not [string]::Equals($expectedPages[$layoutPageName], $layoutPath, [StringComparison]::Ordinal)) {
            Add-ValidationError "Spine set '$SetName' pageLayouts contains non-page '$layoutPath'."
            continue
        }
        if ($expectedLayouts.ContainsKey($layoutPageName)) {
            Add-ValidationError "Spine set '$SetName' pageLayouts duplicates '$layoutPageName'."
            continue
        }
        $expectedLayouts.Add($layoutPageName, $layout)
    }
    if ($pageLayouts.Count -gt 0 -and $expectedLayouts.Count -ne $expectedPages.Count) {
        Add-ValidationError (
            "Spine set '$SetName' pageLayouts must cover every page exactly once; " +
            "layouts=$($expectedLayouts.Count), pages=$($expectedPages.Count).")
    }

    $declaredPages = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::Ordinal)
    $declaredPageOrder = New-Object "System.Collections.Generic.List[string]"
    $declaredRegions = New-Object "System.Collections.Generic.Dictionary[string,object]" ([StringComparer]::Ordinal)
    $lines = @($AtlasData.Replace("`r", "") -split "`n")
    $currentPage = $null
    $currentRegion = $null
    for ($index = 0; $index -lt $lines.Count; $index++) {
        $line = [string]$lines[$index]
        $trimmed = $line.Trim()
        $startsBlock = $index -eq 0 -or [string]::IsNullOrWhiteSpace([string]$lines[$index - 1])
        if ($startsBlock -and -not [string]::IsNullOrWhiteSpace($trimmed) -and
            ($index + 1) -lt $lines.Count -and
            ([string]$lines[$index + 1]).Trim() -match '^size:\s*([0-9]+)\s*,\s*([0-9]+)\s*$') {
            $pageName = $trimmed
            $pageWidth = [int64]$Matches[1]
            $pageHeight = [int64]$Matches[2]
            if (-not $expectedPages.ContainsKey($pageName)) {
                Add-ValidationError "Spine set '$SetName' atlas_data declares unexpected page '$pageName'."
                $currentPage = [pscustomobject]@{ Name = $pageName; Width = $pageWidth; Height = $pageHeight }
                $currentRegion = $null
                continue
            }
            if (-not $declaredPages.Add($pageName)) {
                Add-ValidationError "Spine set '$SetName' atlas_data declares page '$pageName' more than once."
            }
            else {
                $declaredPageOrder.Add($pageName)
                $declaredRegions.Add(
                    $pageName,
                    (New-Object "System.Collections.Generic.List[object]"))
            }

            $relativePath = $expectedPages[$pageName]
            if (-not $PngDimensions.ContainsKey($relativePath)) {
                Add-ValidationError "Spine set '$SetName' page '$pageName' has no PNG dimension contract."
            }
            else {
                $expected = $PngDimensions[$relativePath]
                if ($pageWidth -ne $expected.Width -or $pageHeight -ne $expected.Height) {
                    Add-ValidationError (
                        "Spine set '$SetName' atlas page '$pageName' declares ${pageWidth}x${pageHeight}, " +
                        "expected $($expected.Width)x$($expected.Height).")
                }
            }
            $currentPage = [pscustomobject]@{ Name = $pageName; Width = $pageWidth; Height = $pageHeight }
            $currentRegion = $null
            continue
        }

        if (-not [string]::IsNullOrWhiteSpace($trimmed) -and
            $trimmed.IndexOf(':') -lt 0 -and $null -ne $currentPage) {
            $currentRegion = $trimmed
            continue
        }

        if ($trimmed.StartsWith("bounds:", [StringComparison]::Ordinal)) {
            if ($null -eq $currentPage) {
                Add-ValidationError "Spine set '$SetName' atlas_data contains bounds before any page declaration."
                continue
            }
            if ($trimmed -notmatch '^bounds:\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*,\s*([0-9]+)\s*$') {
                Add-ValidationError "Spine set '$SetName' page '$($currentPage.Name)' has malformed bounds '$trimmed'."
                continue
            }
            $x = [int64]$Matches[1]
            $y = [int64]$Matches[2]
            $width = [int64]$Matches[3]
            $height = [int64]$Matches[4]
            if ([string]::IsNullOrWhiteSpace([string]$currentRegion)) {
                Add-ValidationError "Spine set '$SetName' page '$($currentPage.Name)' has bounds without a region name."
            }
            elseif ($declaredRegions.ContainsKey([string]$currentPage.Name)) {
                $declaredRegions[[string]$currentPage.Name].Add([pscustomobject]@{
                    Name = [string]$currentRegion
                    Bounds = @($x, $y, $width, $height)
                })
            }
            $currentRegion = $null
            $packedWidth = $width
            $packedHeight = $height
            # Spine's atlas stores unrotated bounds and puts rotate:90 after the
            # bounds/offset directives. The physical rectangle on the page has
            # its width and height exchanged in that case.
            for ($probe = $index + 1; $probe -lt $lines.Count; $probe++) {
                $directive = ([string]$lines[$probe]).Trim()
                if ([string]::IsNullOrWhiteSpace($directive)) {
                    break
                }
                if ($directive -match '^rotate:\s*(90|270|true)\s*$') {
                    $packedWidth = $height
                    $packedHeight = $width
                    continue
                }
                if ($directive -match '^(offsets|rotate|index|split|pad):') {
                    continue
                }
                break
            }
            if ($packedWidth -le 0 -or $packedHeight -le 0 -or
                ($x + $packedWidth) -gt $currentPage.Width -or ($y + $packedHeight) -gt $currentPage.Height) {
                Add-ValidationError (
                    "Spine set '$SetName' packed region ${x},${y},${packedWidth},${packedHeight} " +
                    "(source bounds ${width}x${height}) exceeds " +
                    "page '$($currentPage.Name)' ($($currentPage.Width)x$($currentPage.Height)).")
            }
        }
    }

    foreach ($pageName in $expectedPages.Keys) {
        if (-not $declaredPages.Contains($pageName)) {
            Add-ValidationError "Spine set '$SetName' atlas_data does not declare page '$pageName'."
        }
    }

    $exactPagesValue = Get-JsonPropertyValue -Object $SpineSet -Name "exactPages"
    if ($exactPagesValue -eq $true) {
        $actualOrder = @($declaredPageOrder)
        if ($actualOrder.Count -ne $expectedPageOrder.Count) {
            Add-ValidationError (
                "Spine set '$SetName' atlas page count is $($actualOrder.Count); " +
                "expected exactly $($expectedPageOrder.Count).")
        }
        else {
            for ($pageIndex = 0; $pageIndex -lt $expectedPageOrder.Count; $pageIndex++) {
                if (-not [string]::Equals(
                    $actualOrder[$pageIndex],
                    $expectedPageOrder[$pageIndex],
                    [StringComparison]::Ordinal)) {
                    Add-ValidationError (
                        "Spine set '$SetName' atlas page $pageIndex is '$($actualOrder[$pageIndex])'; " +
                        "expected '$($expectedPageOrder[$pageIndex])'.")
                }
            }
        }
    }

    foreach ($pageName in $expectedLayouts.Keys) {
        if (-not $declaredRegions.ContainsKey($pageName)) {
            continue
        }
        $expectedRegions = @($expectedLayouts[$pageName].regions)
        $actualRegions = @($declaredRegions[$pageName])
        if ($actualRegions.Count -ne $expectedRegions.Count) {
            Add-ValidationError (
                "Spine set '$SetName' page '$pageName' declares $($actualRegions.Count) regions; " +
                "expected exactly $($expectedRegions.Count).")
            continue
        }
        for ($regionIndex = 0; $regionIndex -lt $expectedRegions.Count; $regionIndex++) {
            $expectedRegion = $expectedRegions[$regionIndex]
            $actualRegion = $actualRegions[$regionIndex]
            if (-not [string]::Equals(
                [string]$actualRegion.Name,
                [string]$expectedRegion.name,
                [StringComparison]::Ordinal)) {
                Add-ValidationError (
                    "Spine set '$SetName' page '$pageName' region $regionIndex is " +
                    "'$([string]$actualRegion.Name)'; expected '$([string]$expectedRegion.name)'.")
                continue
            }
            $expectedBounds = @($expectedRegion.bounds | ForEach-Object { [int64]$_ })
            $actualBounds = @($actualRegion.Bounds | ForEach-Object { [int64]$_ })
            if ($expectedBounds.Count -ne 4 -or $actualBounds.Count -ne 4 -or
                ($actualBounds -join ',') -ne ($expectedBounds -join ',')) {
                Add-ValidationError (
                    "Spine set '$SetName' page '$pageName' region '$([string]$actualRegion.Name)' " +
                    "bounds are $($actualBounds -join ','); expected $($expectedBounds -join ',').")
            }
        }
    }
}

function Get-JsonPropertyValue {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    foreach ($property in $Object.PSObject.Properties) {
        if ([string]::Equals($property.Name, $Name, [StringComparison]::Ordinal)) {
            return $property.Value
        }
    }

    return $null
}

function Resolve-RuntimeLayoutContract {
    param(
        [Parameter(Mandatory = $true)]$Contract,
        [string]$RequestedLayout = ""
    )

    $layoutName = $RequestedLayout
    if ([string]::IsNullOrWhiteSpace($layoutName)) {
        $layoutName = [string](Get-JsonPropertyValue -Object $Contract -Name "runtimeLayout")
    }
    if ([string]::IsNullOrWhiteSpace($layoutName)) {
        throw "The contract does not select a runtimeLayout and no -RuntimeLayout override was supplied."
    }

    $profiles = @(Get-JsonPropertyValue -Object $Contract -Name "combatRuntimeLayouts")
    $matches = @($profiles | Where-Object {
        [string]::Equals([string]$_.name, $layoutName, [StringComparison]::Ordinal)
    })
    if ($matches.Count -ne 1) {
        $available = @($profiles | ForEach-Object { [string]$_.name }) -join ", "
        throw "Runtime layout '$layoutName' must resolve to exactly one combat profile; available: $available"
    }
    $profile = $matches[0]
    $profilePages = @($profile.pages)
    if ($profilePages.Count -lt 1) {
        throw "Runtime layout '$layoutName' declares no combat atlas pages."
    }

    $pagePaths = @($profilePages | ForEach-Object { [string]$_.path })
    $profileDimensions = @($profilePages | ForEach-Object {
        [pscustomobject]@{
            path = [string]$_.path
            width = [int64]$_.width
            height = [int64]$_.height
        }
    })
    $nonCombatDimensions = @($Contract.pngDimensions | Where-Object {
        -not ([string]$_.path).StartsWith("spine/combat/", [StringComparison]::Ordinal)
    })

    $Contract.runtimeLayout = $layoutName
    $Contract.expectedRuntimeFileCount = [int]$profile.expectedRuntimeFileCount
    $Contract.pngDimensions = @($profileDimensions + $nonCombatDimensions)

    foreach ($spineSet in @($Contract.spineSets)) {
        $setName = [string]$spineSet.name
        if ($setName -notin @("combat", "merchant")) {
            continue
        }
        $spineSet.pages = @($pagePaths)
        if ($null -eq (Get-JsonPropertyValue -Object $spineSet -Name "exactPages")) {
            $spineSet | Add-Member -NotePropertyName exactPages -NotePropertyValue $true
        }
        else {
            $spineSet.exactPages = $true
        }
        if ($null -eq (Get-JsonPropertyValue -Object $spineSet -Name "pageLayouts")) {
            $spineSet | Add-Member -NotePropertyName pageLayouts -NotePropertyValue @($profilePages)
        }
        else {
            $spineSet.pageLayouts = @($profilePages)
        }
    }

    return $Contract
}

function Resolve-GodotConsolePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not [IO.File]::Exists($fullPath)) {
        return $fullPath
    }

    $name = [IO.Path]::GetFileNameWithoutExtension($fullPath)
    if (-not $name.EndsWith("_console", [StringComparison]::OrdinalIgnoreCase)) {
        $consolePath = Join-Path ([IO.Path]::GetDirectoryName($fullPath)) ($name + "_console.exe")
        if ([IO.File]::Exists($consolePath)) {
            return $consolePath
        }
    }

    return $fullPath
}

function Initialize-SpineGodotExtension {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$GameRoot
    )

    $sourceDll = Join-Path $GameRoot "libspine_godot.windows.template_release.x86_64.dll"
    if (-not [IO.File]::Exists($sourceDll)) {
        throw "Game Spine GDExtension DLL does not exist: $sourceDll"
    }

    $template = Join-Path $PSScriptRoot "spine_godot_extension.gdextension.template"
    if (-not [IO.File]::Exists($template)) {
        throw "Spine GDExtension template does not exist: $template"
    }

    # A loaded GDExtension DLL is locked on Windows. Use an immutable, content-addressed
    # directory so validation never needs to overwrite a DLL held by another Godot process.
    $sourceHash = (Get-FileHash -LiteralPath $sourceDll -Algorithm SHA256).Hash.ToLowerInvariant()
    $templateHash = (Get-FileHash -LiteralPath $template -Algorithm SHA256).Hash.ToLowerInvariant()
    $extensionKey = "$($sourceHash.Substring(0, 12))-$($templateHash.Substring(0, 8))"
    $extensionRelativeDir = "bin/spine_contract/$extensionKey"
    $extensionDir = Get-SafeChildPath -BasePath $ProjectRoot -RelativePath $extensionRelativeDir
    $windowsDir = Join-Path $extensionDir "windows"
    [void][IO.Directory]::CreateDirectory($windowsDir)

    $extensionPath = Join-Path $extensionDir "spine_godot_extension.gdextension"
    $destinationDll = Join-Path $windowsDir "libspine_godot.windows.editor.x86_64.dll"

    # Godot discovers every *.gdextension below the project, independently of the
    # extension_list cache. Quarantine only validator-owned stale manifests so two
    # copies of the Spine library can never register the same classes in one process.
    $binDir = Get-SafeChildPath -BasePath $ProjectRoot -RelativePath "bin"
    $candidateManifests = New-Object "System.Collections.Generic.List[IO.FileInfo]"
    $legacyManifest = Join-Path $binDir "spine_godot_extension.gdextension"
    if ([IO.File]::Exists($legacyManifest)) {
        $candidateManifests.Add((Get-Item -LiteralPath $legacyManifest))
    }
    $contractExtensionRoot = Join-Path $binDir "spine_contract"
    if ([IO.Directory]::Exists($contractExtensionRoot)) {
        foreach ($candidate in Get-ChildItem -LiteralPath $contractExtensionRoot -Filter "spine_godot_extension.gdextension" -File -Recurse -Force) {
            $candidateManifests.Add($candidate)
        }
    }
    foreach ($candidate in $candidateManifests) {
            if ([string]::Equals($candidate.FullName, $extensionPath, [StringComparison]::OrdinalIgnoreCase)) {
                continue
            }

            $disabledPath = $candidate.FullName + ".inactive"
            $suffix = 1
            while ([IO.File]::Exists($disabledPath)) {
                $disabledPath = $candidate.FullName + ".inactive.$suffix"
                $suffix++
            }
            [IO.File]::Move($candidate.FullName, $disabledPath)
            Write-Host "[ironclad-skin] Quarantined stale validator GDExtension manifest '$($candidate.FullName)'."
    }

    if (-not [IO.File]::Exists($extensionPath)) {
        [IO.File]::Copy($template, $extensionPath, $false)
    }
    elseif (-not [string]::Equals(
            (Get-FileHash -LiteralPath $extensionPath -Algorithm SHA256).Hash,
            $templateHash,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "Content-addressed Spine GDExtension manifest has an unexpected SHA-256: $extensionPath"
    }
    if (-not [IO.File]::Exists($destinationDll)) {
        [IO.File]::Copy($sourceDll, $destinationDll, $false)
    }
    elseif (-not [string]::Equals(
            (Get-FileHash -LiteralPath $destinationDll -Algorithm SHA256).Hash,
            $sourceHash,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "Content-addressed Spine GDExtension DLL has an unexpected SHA-256: $destinationDll"
    }

    $godotMetadataDir = Get-SafeChildPath -BasePath $ProjectRoot -RelativePath ".godot"
    [void][IO.Directory]::CreateDirectory($godotMetadataDir)
    $extensionListPath = Join-Path $godotMetadataDir "extension_list.cfg"
    $extensionResourcePath = "res://$extensionRelativeDir/spine_godot_extension.gdextension"
    $extensionLines = New-Object "System.Collections.Generic.List[string]"
    if ([IO.File]::Exists($extensionListPath)) {
        foreach ($line in [IO.File]::ReadAllLines($extensionListPath)) {
            $trimmed = $line.Trim()
            if ([string]::IsNullOrWhiteSpace($trimmed)) {
                continue
            }
            if ([string]::Equals($trimmed, "res://bin/spine_godot_extension.gdextension", [StringComparison]::OrdinalIgnoreCase) -or
                $trimmed.StartsWith("res://bin/spine_contract/", [StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            if (-not $extensionLines.Contains($trimmed)) {
                $extensionLines.Add($trimmed)
            }
        }
    }
    $extensionLines.Add($extensionResourcePath)

    $newExtensionList = ($extensionLines -join [Environment]::NewLine) + [Environment]::NewLine
    $oldExtensionList = ""
    if ([IO.File]::Exists($extensionListPath)) {
        $oldExtensionList = [IO.File]::ReadAllText($extensionListPath)
    }
    if (-not [string]::Equals($oldExtensionList, $newExtensionList, [StringComparison]::Ordinal)) {
        $utf8NoBom = New-Object Text.UTF8Encoding($false)
        [IO.File]::WriteAllText($extensionListPath, $newExtensionList, $utf8NoBom)
    }

    return $extensionResourcePath
}

function Invoke-GodotSpineContract {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$GodotPath,
        [Parameter(Mandatory = $true)][string]$GameRoot,
        [Parameter(Mandatory = $true)][string]$RuntimeLayout
    )

    if ([string]::IsNullOrWhiteSpace($GodotPath)) {
        Add-ValidationError "GodotExe is required when the Ironclad skin bundle is active."
        return
    }
    if ([string]::IsNullOrWhiteSpace($GameRoot)) {
        Add-ValidationError "Sts2Dir is required when the Ironclad skin bundle is active."
        return
    }

    $basePckPath = Join-Path ([IO.Path]::GetFullPath($GameRoot)) "SlayTheSpire2.pck"
    if (-not [IO.File]::Exists($basePckPath)) {
        Add-ValidationError "Base game PCK does not exist: $basePckPath"
        return
    }

    $consoleExe = Resolve-GodotConsolePath -Path $GodotPath
    if (-not [IO.File]::Exists($consoleExe)) {
        Add-ValidationError "Godot executable does not exist: $consoleExe"
        return
    }

    $pathBytes = [Text.Encoding]::UTF8.GetBytes($ProjectRoot.ToLowerInvariant())
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $projectHash = ([BitConverter]::ToString($sha256.ComputeHash($pathBytes))).Replace("-", "").Substring(0, 24)
    }
    finally {
        $sha256.Dispose()
    }
    $mutex = New-Object Threading.Mutex($false, "Local\VivhiteIroncladSpine-$projectHash")
    $mutexAcquired = $false
    Write-Host "[ironclad-skin] Waiting for exclusive Godot Spine validation access..."
    try {
        try {
            $mutexAcquired = $mutex.WaitOne([TimeSpan]::FromSeconds(60))
        }
        catch [Threading.AbandonedMutexException] {
            $mutexAcquired = $true
        }
        if (-not $mutexAcquired) {
            Add-ValidationError "Timed out waiting for another Godot Spine validation process to finish."
            return
        }

        try {
            $extensionResourcePath = Initialize-SpineGodotExtension -ProjectRoot $ProjectRoot -GameRoot ([IO.Path]::GetFullPath($GameRoot))
        }
        catch {
            Add-ValidationError $_.Exception.Message
            return
        }

        Write-Host "[ironclad-skin] Using Spine GDExtension '$extensionResourcePath'."
        Write-Host "[ironclad-skin] Importing runtime assets before loading Spine resources..."
        $previousErrorActionPreference = $ErrorActionPreference
        $previousDotnetRoot = $env:DOTNET_ROOT
        $previousDotnetRootX64 = $env:DOTNET_ROOT_X64
        $previousPath = $env:PATH
        $previousSkipExport = $env:STS2_SKIP_PCK_EXPORT
        $previousBasePckPath = $env:VIVHITE_STS2_PCK_PATH
        $previousRuntimeLayout = $env:VIVHITE_IRONCLAD_RUNTIME_LAYOUT
        try {
            $dotnetRoot = $env:DOTNET_ROOT
            if ([string]::IsNullOrWhiteSpace($dotnetRoot)) {
                $dotnetCommand = Get-Command dotnet.exe -ErrorAction SilentlyContinue
                if ($null -ne $dotnetCommand) {
                    $dotnetRoot = Split-Path -Parent $dotnetCommand.Source
                }
            }
            if (-not [string]::IsNullOrWhiteSpace($dotnetRoot)) {
                $env:DOTNET_ROOT = $dotnetRoot
                $env:DOTNET_ROOT_X64 = $dotnetRoot
                $dotnetPrefix = $dotnetRoot.TrimEnd('\', '/') + [IO.Path]::PathSeparator
                if (-not $env:PATH.StartsWith($dotnetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                    $env:PATH = $dotnetPrefix + $env:PATH
                }
            }
            $env:STS2_SKIP_PCK_EXPORT = "1"
            $env:VIVHITE_STS2_PCK_PATH = $basePckPath
            $env:VIVHITE_IRONCLAD_RUNTIME_LAYOUT = $RuntimeLayout
            $ErrorActionPreference = "Continue"
            $importOutput = @()
            $importExitCode = -1
            $importOutput = & $consoleExe --headless --path $ProjectRoot --import 2>&1
            $importExitCode = $LASTEXITCODE
            foreach ($line in @($importOutput)) {
                Write-Host $line
            }
            if ($importExitCode -ne 0) {
                Add-ValidationError "Godot asset import exited with code $importExitCode."
                return
            }

            Write-Host "[ironclad-skin] Loading Spine resources through Godot and the game's Spine GDExtension..."
            $output = @()
            $exitCode = -1
            $output = & $consoleExe --headless --path $ProjectRoot --script "res://tools/Validate-IroncladSpine.gd" 2>&1
            $exitCode = $LASTEXITCODE
            foreach ($line in @($output)) {
                Write-Host $line
            }
            if ($exitCode -ne 0) {
                Add-ValidationError "Godot Spine contract validator exited with code $exitCode."
            }
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
            $env:DOTNET_ROOT = $previousDotnetRoot
            $env:DOTNET_ROOT_X64 = $previousDotnetRootX64
            $env:PATH = $previousPath
            $env:STS2_SKIP_PCK_EXPORT = $previousSkipExport
            $env:VIVHITE_STS2_PCK_PATH = $previousBasePckPath
            $env:VIVHITE_IRONCLAD_RUNTIME_LAYOUT = $previousRuntimeLayout
        }
    }
    finally {
        if ($mutexAcquired) {
            [void]$mutex.ReleaseMutex()
        }
        $mutex.Dispose()
    }
}

function Test-SourceAssets {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)]$Contract,
        [Parameter(Mandatory = $true)]$Activation
    )

    if (-not $Activation.Active) {
        Write-Host "[ironclad-skin] Optional skin bundle is inactive ($($Activation.Reason)); source contract skipped." -ForegroundColor Green
        return
    }

    Write-Host "[ironclad-skin] Skin bundle is active because $($Activation.Reason)."
    Write-Host "[ironclad-skin] Checking complete runtime asset set before loading any Spine resource..."

    $resourceRoot = ([string]$Contract.resourceRoot).Replace('\', '/').Trim('/')
    $required = Get-ExpectedLogicalAssets -Contract $Contract
    foreach ($relativePath in $required) {
        try {
            $fullPath = Get-SafeChildPath -BasePath $Activation.AssetRoot -RelativePath $relativePath
        }
        catch {
            Add-ValidationError $_.Exception.Message
            continue
        }

        if (-not [IO.File]::Exists($fullPath)) {
            Add-ValidationError "Missing asset: $resourceRoot/$relativePath"
        }
        elseif ((Get-Item -LiteralPath $fullPath).Length -eq 0) {
            Add-ValidationError "Asset is empty: $resourceRoot/$relativePath"
        }
    }

    foreach ($file in Get-ChildItem -LiteralPath $Activation.AssetRoot -File -Recurse -Force) {
        $relative = $file.FullName.Substring($Activation.AssetRoot.Length).TrimStart('\', '/').Replace('\', '/')
        if ($required.Contains($relative)) {
            continue
        }

        $generatedSource = $null
        foreach ($generatedSuffix in @(".import", ".uid")) {
            if ($relative.EndsWith($generatedSuffix, [StringComparison]::OrdinalIgnoreCase)) {
                $generatedSource = $relative.Substring(0, $relative.Length - $generatedSuffix.Length)
                break
            }
        }
        if ($null -ne $generatedSource -and $required.Contains($generatedSource)) {
            continue
        }

        Add-ValidationError "Unexpected private skin source file outside the declared contract: $resourceRoot/$relative"
    }

    if ($script:ValidationErrors.Count -gt 0) {
        Write-Host "[ironclad-skin] Spine animation/slot/event checks skipped until the complete asset set exists."
        Stop-Validation "Source asset completeness check failed."
    }

    Write-Host "[ironclad-skin] Asset set is complete; checking bindings, PNGs, and Spine wrapper metadata..."
    $pngDimensions = Get-ExpectedPngDimensions -Contract $Contract -ExpectedAssets $required
    foreach ($relativePath in $pngDimensions.Keys) {
        $fullPath = Get-SafeChildPath -BasePath $Activation.AssetRoot -RelativePath $relativePath
        try {
            $actual = Get-PngDimensions -Path $fullPath
            $expected = $pngDimensions[$relativePath]
            if ($actual.Width -ne $expected.Width -or $actual.Height -ne $expected.Height) {
                Add-ValidationError (
                    "PNG dimensions do not match for '$resourceRoot/$relativePath': " +
                    "got $($actual.Width)x$($actual.Height), expected $($expected.Width)x$($expected.Height).")
            }
        }
        catch {
            Add-ValidationError "Invalid PNG '$resourceRoot/$relativePath': $($_.Exception.Message)"
        }
    }

    $requiredSkeletonExtension = [string]$Contract.requiredPrivateSkeletonExtension
    if ([string]::IsNullOrWhiteSpace($requiredSkeletonExtension) -or
        -not $requiredSkeletonExtension.StartsWith('.', [StringComparison]::Ordinal)) {
        Add-ValidationError "requiredPrivateSkeletonExtension must be a dot-prefixed extension."
        $requiredSkeletonExtension = ".spjson"
    }

    foreach ($spineSet in @($Contract.spineSets)) {
        $setName = [string]$spineSet.name
        $skeletonDataRelative = [string]$spineSet.skeletonData
        $skeletonResource = [string]$spineSet.skeletonResource
        $atlasRelative = [string]$spineSet.atlas
        $atlasSourceRelative = [string]$spineSet.atlasSourcePath
        $skeletonDataPath = Get-SafeChildPath -BasePath $Activation.AssetRoot -RelativePath $skeletonDataRelative
        $atlasPath = Get-SafeChildPath -BasePath $Activation.AssetRoot -RelativePath $atlasRelative
        $skeletonDataText = [IO.File]::ReadAllText($skeletonDataPath)
        $expectedAtlasReference = Get-ResourcePath -ResourceRoot $resourceRoot -RelativePath $atlasRelative

        try {
            $skeletonRelative = Get-PrivateResourceRelativePath `
                -ResourceRoot $resourceRoot `
                -ResourcePath $skeletonResource `
                -Label "Spine set '$setName' skeletonResource"
            $skeletonFilePath = Get-SafeChildPath -BasePath $Activation.AssetRoot -RelativePath $skeletonRelative
        }
        catch {
            Add-ValidationError $_.Exception.Message
            continue
        }
        if (-not $skeletonResource.EndsWith($requiredSkeletonExtension, [StringComparison]::OrdinalIgnoreCase)) {
            Add-ValidationError (
                "Spine set '$setName' skeletonResource must use the private " +
                "'$requiredSkeletonExtension' runtime format: $skeletonResource")
        }
        if ($skeletonDataText.IndexOf($skeletonResource, [StringComparison]::Ordinal) -lt 0) {
            Add-ValidationError "Spine set '$setName' skeleton data must reference '$skeletonResource'."
        }
        if ($skeletonDataText.IndexOf($expectedAtlasReference, [StringComparison]::Ordinal) -lt 0) {
            Add-ValidationError "Spine set '$setName' skeleton data must reference '$expectedAtlasReference'."
        }
        if ($skeletonDataText.IndexOf('type="SpineSkeletonDataResource"', [StringComparison]::Ordinal) -lt 0 -or
            $skeletonDataText.IndexOf('type="SpineSkeletonFileResource"', [StringComparison]::Ordinal) -lt 0 -or
            $skeletonDataText.IndexOf('type="SpineAtlasResource"', [StringComparison]::Ordinal) -lt 0) {
            Add-ValidationError "Spine set '$setName' skeleton data has the wrong Godot resource contract."
        }

        try {
            $skeletonJson = [IO.File]::ReadAllText($skeletonFilePath) | ConvertFrom-Json
            $skeletonHeader = Get-JsonPropertyValue -Object $skeletonJson -Name "skeleton"
            if ($null -eq $skeletonHeader) {
                throw "missing top-level skeleton metadata"
            }
            $actualVersion = [string](Get-JsonPropertyValue -Object $skeletonHeader -Name "spine")
            $expectedVersion = [string]$spineSet.expectedSpineVersion
            if (-not [string]::Equals($actualVersion, $expectedVersion, [StringComparison]::Ordinal)) {
                Add-ValidationError (
                    "Spine set '$setName' private JSON declares version '$actualVersion'; " +
                    "expected '$expectedVersion'.")
            }
        }
        catch {
            Add-ValidationError "Spine set '$setName' private .spjson is invalid: $($_.Exception.Message)"
        }

        try {
            $atlasWrapper = [IO.File]::ReadAllText($atlasPath) | ConvertFrom-Json
            $atlasData = [string](Get-JsonPropertyValue -Object $atlasWrapper -Name "atlas_data")
            $sourcePath = [string](Get-JsonPropertyValue -Object $atlasWrapper -Name "source_path")
            $expectedSourcePath = Get-ResourcePath -ResourceRoot $resourceRoot -RelativePath $atlasSourceRelative
            if ([string]::IsNullOrWhiteSpace($atlasData)) {
                Add-ValidationError "Spine set '$setName' .spatlas has no atlas_data."
            }
            if (-not [string]::Equals($sourcePath, $expectedSourcePath, [StringComparison]::Ordinal)) {
                Add-ValidationError "Spine set '$setName' .spatlas source_path must be '$expectedSourcePath', got '$sourcePath'."
            }
            if (-not [string]::IsNullOrWhiteSpace($atlasData)) {
                Test-SpineAtlasLayout -SetName $setName -AtlasData $atlasData -SpineSet $spineSet -PngDimensions $pngDimensions
            }
        }
        catch {
            Add-ValidationError "Spine set '$setName' .spatlas is not valid JSON: $($_.Exception.Message)"
        }

    }

    foreach ($binding in @($Contract.sceneBindings)) {
        $sceneRelative = [string]$binding.scene
        $skeletonDataRelative = [string]$binding.skeletonData
        $scenePath = Get-SafeChildPath -BasePath $Activation.AssetRoot -RelativePath $sceneRelative
        $sceneText = [IO.File]::ReadAllText($scenePath)
        $expectedReference = Get-ResourcePath -ResourceRoot $resourceRoot -RelativePath $skeletonDataRelative
        if ($sceneText.IndexOf($expectedReference, [StringComparison]::Ordinal) -lt 0) {
            Add-ValidationError "Scene '$sceneRelative' must reference '$expectedReference'."
        }
        $requiredSceneTexts = Get-JsonPropertyValue -Object $binding -Name "requiredText"
        foreach ($requiredText in @($requiredSceneTexts)) {
            $requiredSceneText = [string]$requiredText
            if (-not [string]::IsNullOrEmpty($requiredSceneText) -and
                $sceneText.IndexOf($requiredSceneText, [StringComparison]::Ordinal) -lt 0) {
                Add-ValidationError "Scene '$sceneRelative' is missing required contract text '$requiredSceneText'."
            }
        }
        foreach ($nodeType in @($Contract.forbiddenSerializedSceneNodeTypes)) {
            $forbiddenNodeType = "type=`"$([string]$nodeType)`""
            if ($sceneText.IndexOf($forbiddenNodeType, [StringComparison]::Ordinal) -ge 0) {
                Add-ValidationError (
                    "Scene '$sceneRelative' contains serialized '$([string]$nodeType)' " +
                    "preview geometry; meshes must come only from the private Spine JSON.")
            }
        }
    }

    $textExtensions = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    foreach ($extension in @(".tres", ".tscn", ".spatlas", ".spjson", ".import", ".remap")) {
        [void]$textExtensions.Add($extension)
    }
    foreach ($file in Get-ChildItem -LiteralPath $Activation.AssetRoot -File -Recurse) {
        foreach ($forbiddenExtension in @($Contract.forbiddenPrivateExtensions)) {
            if ($file.Extension.Equals([string]$forbiddenExtension, [StringComparison]::OrdinalIgnoreCase)) {
                Add-ValidationError "Private skin contains a forbidden runtime extension: $($file.FullName)"
            }
        }
        if (-not $textExtensions.Contains($file.Extension)) {
            continue
        }
        $text = [IO.File]::ReadAllText($file.FullName)
        foreach ($prefix in @($Contract.forbiddenVanillaPrefixes)) {
            $forbiddenReference = "res://$([string]$prefix)"
            if ($text.IndexOf($forbiddenReference, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                Add-ValidationError "Private skin resource '$($file.FullName)' still references vanilla replacement path '$forbiddenReference'."
            }
        }
    }

    if ($script:ValidationErrors.Count -gt 0) {
        Write-Host "[ironclad-skin] Godot Spine checks skipped because static resource checks failed."
        Stop-Validation "Source asset contract check failed."
    }

    Invoke-GodotSpineContract `
        -ProjectRoot $ProjectRoot `
        -GodotPath $GodotExe `
        -GameRoot $Sts2Dir `
        -RuntimeLayout ([string]$Contract.runtimeLayout)
    if ($script:ValidationErrors.Count -gt 0) {
        Stop-Validation "Godot Spine contract check failed."
    }

    Write-Host "[ironclad-skin] Source asset contract passed ($($required.Count) files, $(@($Contract.spineSets).Count) Spine sets)." -ForegroundColor Green
}

function Read-PckIndex {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $reader = New-Object IO.BinaryReader($stream, [Text.Encoding]::UTF8, $true)
    try {
        if ($stream.Length -lt 44) {
            throw "PCK is too small to contain a Godot header."
        }
        $magic = [Text.Encoding]::ASCII.GetString($reader.ReadBytes(4))
        if ($magic -ne "GDPC") {
            throw "Not a Godot PCK: expected GDPC, got '$magic'."
        }
        $formatVersion = $reader.ReadUInt32()
        if ($formatVersion -ne 2 -and $formatVersion -ne 3) {
            throw "Unsupported Godot PCK format $formatVersion."
        }
        $engineMajor = $reader.ReadUInt32()
        $engineMinor = $reader.ReadUInt32()
        $enginePatch = $reader.ReadUInt32()
        $flags = $reader.ReadUInt32()
        $fileBase = $reader.ReadUInt64()
        $directoryOffset = $reader.ReadUInt64()
        if (($flags -band 1) -ne 0) {
            throw "Encrypted PCK directories cannot be validated."
        }
        if ($directoryOffset -gt ($stream.Length - 4)) {
            throw "PCK directory offset $directoryOffset is outside the file."
        }

        $stream.Position = [int64]$directoryOffset
        $fileCount = $reader.ReadUInt32()
        if ($fileCount -gt 1000000) {
            throw "Implausible PCK entry count: $fileCount."
        }

        $entries = New-Object "System.Collections.Generic.List[object]"
        for ($index = 0; $index -lt $fileCount; $index++) {
            $pathLength = $reader.ReadUInt32()
            if ($pathLength -eq 0 -or $pathLength -gt 1048576) {
                throw "Invalid path length $pathLength at PCK entry $index."
            }
            $rawPath = $reader.ReadBytes([int]$pathLength)
            if ($rawPath.Length -ne $pathLength) {
                throw "Unexpected end of PCK while reading path $index."
            }
            $entryPath = [Text.Encoding]::UTF8.GetString($rawPath).TrimEnd([char]0).Replace('\', '/')
            if ($entryPath.StartsWith("res://", [StringComparison]::OrdinalIgnoreCase)) {
                $entryPath = $entryPath.Substring(6)
            }
            $offset = $reader.ReadUInt64()
            $size = $reader.ReadUInt64()
            [void]$reader.ReadBytes(16)
            $entryFlags = $reader.ReadUInt32()
            $absoluteOffset = $offset
            if (($flags -band 2) -ne 0) {
                $absoluteOffset = $fileBase + $offset
            }
            if (($entryFlags -band 2) -eq 0 -and ($absoluteOffset + $size) -gt $stream.Length) {
                throw "PCK payload for '$entryPath' is outside the file."
            }
            $entries.Add([pscustomobject]@{
                    Path = $entryPath
                    Flags = [uint32]$entryFlags
                    AbsoluteOffset = [uint64]$absoluteOffset
                    Size = [uint64]$size
                })
        }

        return [pscustomobject]@{
            FormatVersion = $formatVersion
            EngineVersion = "$engineMajor.$engineMinor.$enginePatch"
            Entries = $entries
        }
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}

function Read-PckTextEntry {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Entry
    )

    if (($Entry.Flags -band 1) -ne 0) {
        throw "PCK entry '$($Entry.Path)' is encrypted; its text contract cannot be inspected."
    }
    if (($Entry.Flags -band 2) -ne 0) {
        throw "PCK entry '$($Entry.Path)' is a removal entry and has no readable payload."
    }
    if ($Entry.Size -gt 16777216) {
        throw "PCK text entry '$($Entry.Path)' is implausibly large ($($Entry.Size) bytes)."
    }

    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    try {
        $stream.Position = [int64]$Entry.AbsoluteOffset
        $bytes = [byte[]]::new([int]$Entry.Size)
        $totalRead = 0
        while ($totalRead -lt $bytes.Length) {
            $read = $stream.Read($bytes, $totalRead, $bytes.Length - $totalRead)
            if ($read -eq 0) {
                throw "Unexpected end of PCK while reading '$($Entry.Path)'."
            }
            $totalRead += $read
        }

        return [Text.Encoding]::UTF8.GetString($bytes).TrimStart([char]0xFEFF)
    }
    finally {
        $stream.Dispose()
    }
}

function Test-PckContents {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Contract,
        [Parameter(Mandatory = $true)]$Activation
    )

    Write-Host "[ironclad-skin] Checking exported PCK '$Path'..."
    if (-not [IO.File]::Exists($Path)) {
        Add-ValidationError "Exported PCK does not exist: $Path"
        Stop-Validation "PCK contract check failed."
    }
    try {
        $index = Read-PckIndex -Path $Path
    }
    catch {
        Add-ValidationError $_.Exception.Message
        Stop-Validation "PCK contract check failed."
    }

    $entryByPath = New-Object "System.Collections.Generic.Dictionary[string,object]" ([StringComparer]::OrdinalIgnoreCase)
    foreach ($entry in $index.Entries) {
        if (-not $entryByPath.ContainsKey($entry.Path)) {
            $entryByPath.Add($entry.Path, $entry)
        }
        else {
            Add-ValidationError "Exported PCK contains duplicate entry path: $($entry.Path)"
        }
    }

    $segmentAlternation = (@($Contract.forbiddenPckSegments) | ForEach-Object {
            [Text.RegularExpressions.Regex]::Escape([string]$_)
        }) -join "|"
    $segmentRegex = "(?i)(^|/)($segmentAlternation)(/|$)"
    $resourceRoot = ([string]$Contract.resourceRoot).Replace('\', '/').Trim('/')
    $privatePrefix = $resourceRoot + "/"
    $allowedPrivateEntries = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    if ($Activation.Active) {
        foreach ($relativePath in (Get-ExpectedLogicalAssets -Contract $Contract)) {
            $logicalPath = "$resourceRoot/$relativePath"
            if ($relativePath.EndsWith(".png", [StringComparison]::OrdinalIgnoreCase)) {
                [void]$allowedPrivateEntries.Add("$logicalPath.import")
            }
            else {
                [void]$allowedPrivateEntries.Add($logicalPath)
            }
        }
    }
    foreach ($entry in $index.Entries) {
        $entryPath = [string]$entry.Path
        if ($entryPath -match $segmentRegex) {
            Add-ValidationError "Forbidden build/staging path leaked into PCK: $entryPath"
        }
        foreach ($prefix in @($Contract.forbiddenVanillaPrefixes)) {
            if ($entryPath.StartsWith([string]$prefix, [StringComparison]::OrdinalIgnoreCase)) {
                Add-ValidationError "Vanilla Ironclad replacement path leaked into PCK: $entryPath"
            }
        }
        if ($entryPath.StartsWith($privatePrefix, [StringComparison]::OrdinalIgnoreCase)) {
            if ($Activation.Active -and -not $allowedPrivateEntries.Contains($entryPath)) {
                Add-ValidationError "Unexpected private skin entry outside the declared PCK contract: $entryPath"
            }
            foreach ($forbiddenExtension in @($Contract.forbiddenPrivateExtensions)) {
                $extension = [string]$forbiddenExtension
                if ($entryPath.EndsWith($extension, [StringComparison]::OrdinalIgnoreCase) -or
                    $entryPath.EndsWith("$extension.import", [StringComparison]::OrdinalIgnoreCase) -or
                    $entryPath.EndsWith("$extension.remap", [StringComparison]::OrdinalIgnoreCase)) {
                    Add-ValidationError "Forbidden private skeleton binary leaked into PCK: $entryPath"
                }
            }
        }
    }

    if ($Activation.Active) {
        foreach ($relativePath in (Get-ExpectedLogicalAssets -Contract $Contract)) {
            $logicalPath = "$resourceRoot/$relativePath"
            if ($relativePath.EndsWith(".png", [StringComparison]::OrdinalIgnoreCase)) {
                $expectedEntry = "$logicalPath.import"
            }
            else {
                # Private Spine JSON, wrappers, and scenes remain readable source
                # text so their runtime references can be inspected exactly.
                $expectedEntry = $logicalPath
            }
            if (-not $entryByPath.ContainsKey($expectedEntry) -or
                (($entryByPath[$expectedEntry].Flags -band 2) -ne 0)) {
                Add-ValidationError "Exported PCK is missing exact private entry '$expectedEntry' for res://$logicalPath."
            }
        }

        $requiredSkeletonExtension = [string]$Contract.requiredPrivateSkeletonExtension
        if ([string]::IsNullOrWhiteSpace($requiredSkeletonExtension) -or
            -not $requiredSkeletonExtension.StartsWith('.', [StringComparison]::Ordinal)) {
            Add-ValidationError "requiredPrivateSkeletonExtension must be a dot-prefixed extension."
            $requiredSkeletonExtension = ".spjson"
        }
        $validatedSkeletonEntries = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
        $validatedAtlasEntries = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
        $pckPngDimensions = Get-ExpectedPngDimensions `
            -Contract $Contract `
            -ExpectedAssets (Get-ExpectedLogicalAssets -Contract $Contract)
        foreach ($spineSet in @($Contract.spineSets)) {
            $setName = [string]$spineSet.name
            $skeletonDataPath = "$resourceRoot/$([string]$spineSet.skeletonData)"
            $skeletonResource = [string]$spineSet.skeletonResource
            $atlasRelative = [string]$spineSet.atlas
            $atlasEntryPath = "$resourceRoot/$atlasRelative"
            try {
                $skeletonRelative = Get-PrivateResourceRelativePath `
                    -ResourceRoot $resourceRoot `
                    -ResourcePath $skeletonResource `
                    -Label "Spine set '$setName' skeletonResource"
                $skeletonEntryPath = "$resourceRoot/$skeletonRelative"
            }
            catch {
                Add-ValidationError $_.Exception.Message
                continue
            }
            if (-not $skeletonResource.EndsWith($requiredSkeletonExtension, [StringComparison]::OrdinalIgnoreCase)) {
                Add-ValidationError (
                    "Exported Spine set '$setName' skeletonResource must use " +
                    "'$requiredSkeletonExtension': $skeletonResource")
            }
            if ($validatedSkeletonEntries.Add($skeletonEntryPath) -and
                $entryByPath.ContainsKey($skeletonEntryPath)) {
                try {
                    $skeletonText = Read-PckTextEntry -Path $Path -Entry $entryByPath[$skeletonEntryPath]
                    $skeletonJson = $skeletonText | ConvertFrom-Json
                    $skeletonHeader = Get-JsonPropertyValue -Object $skeletonJson -Name "skeleton"
                    if ($null -eq $skeletonHeader) {
                        throw "missing top-level skeleton metadata"
                    }
                    $actualVersion = [string](Get-JsonPropertyValue -Object $skeletonHeader -Name "spine")
                    $expectedVersion = [string]$spineSet.expectedSpineVersion
                    if (-not [string]::Equals($actualVersion, $expectedVersion, [StringComparison]::Ordinal)) {
                        Add-ValidationError (
                            "Exported Spine set '$setName' private JSON declares version " +
                            "'$actualVersion'; expected '$expectedVersion'.")
                    }
                }
                catch {
                    Add-ValidationError "Exported private Spine JSON is invalid at res://${skeletonEntryPath}: $($_.Exception.Message)"
                }
            }
            if ($validatedAtlasEntries.Add($atlasEntryPath) -and
                $entryByPath.ContainsKey($atlasEntryPath)) {
                try {
                    $atlasText = Read-PckTextEntry -Path $Path -Entry $entryByPath[$atlasEntryPath]
                    $atlasWrapper = $atlasText | ConvertFrom-Json
                    $atlasData = [string](Get-JsonPropertyValue -Object $atlasWrapper -Name "atlas_data")
                    $sourcePath = [string](Get-JsonPropertyValue -Object $atlasWrapper -Name "source_path")
                    $expectedSourcePath = Get-ResourcePath `
                        -ResourceRoot $resourceRoot `
                        -RelativePath ([string]$spineSet.atlasSourcePath)
                    if ([string]::IsNullOrWhiteSpace($atlasData)) {
                        Add-ValidationError "Exported Spine set '$setName' .spatlas has no atlas_data."
                    }
                    if (-not [string]::Equals($sourcePath, $expectedSourcePath, [StringComparison]::Ordinal)) {
                        Add-ValidationError (
                            "Exported Spine set '$setName' .spatlas source_path must be " +
                            "'$expectedSourcePath', got '$sourcePath'.")
                    }
                    if (-not [string]::IsNullOrWhiteSpace($atlasData)) {
                        Test-SpineAtlasLayout `
                            -SetName "exported $setName" `
                            -AtlasData $atlasData `
                            -SpineSet $spineSet `
                            -PngDimensions $pckPngDimensions
                    }
                }
                catch {
                    Add-ValidationError "Exported Spine atlas is invalid at res://${atlasEntryPath}: $($_.Exception.Message)"
                }
            }
            if (-not $entryByPath.ContainsKey($skeletonDataPath)) {
                continue
            }

            try {
                $text = Read-PckTextEntry -Path $Path -Entry $entryByPath[$skeletonDataPath]
                $atlasResource = Get-ResourcePath -ResourceRoot $resourceRoot -RelativePath ([string]$spineSet.atlas)
                if ($text.IndexOf('[gd_resource', [StringComparison]::Ordinal) -ne 0) {
                    Add-ValidationError "Exported Spine set '$setName' skeleton data is not a text Godot resource: res://$skeletonDataPath"
                }
                if ($text.IndexOf($skeletonResource, [StringComparison]::Ordinal) -lt 0) {
                    Add-ValidationError "Exported Spine set '$setName' lost its private skeleton reference '$skeletonResource'."
                }
                if ($text.IndexOf($atlasResource, [StringComparison]::Ordinal) -lt 0) {
                    Add-ValidationError "Exported Spine set '$setName' lost its private atlas reference '$atlasResource'."
                }
            }
            catch {
                Add-ValidationError $_.Exception.Message
            }
        }

        $inspectableExtensions = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
        foreach ($extension in @(".tres", ".tscn", ".spatlas", ".spjson")) {
            [void]$inspectableExtensions.Add($extension)
        }
        foreach ($entry in $index.Entries) {
            $entryPath = [string]$entry.Path
            if (-not $entryPath.StartsWith($privatePrefix, [StringComparison]::OrdinalIgnoreCase) -or
                -not $inspectableExtensions.Contains([IO.Path]::GetExtension($entryPath))) {
                continue
            }
            try {
                $text = Read-PckTextEntry -Path $Path -Entry $entry
                foreach ($prefix in @($Contract.forbiddenVanillaPrefixes)) {
                    $forbiddenReference = "res://$([string]$prefix)"
                    if ($text.IndexOf($forbiddenReference, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                        Add-ValidationError (
                            "Exported private resource 'res://$entryPath' still references " +
                            "vanilla replacement path '$forbiddenReference'.")
                    }
                }
            }
            catch {
                Add-ValidationError $_.Exception.Message
            }
        }

        foreach ($binding in @($Contract.sceneBindings)) {
            $sceneRelative = [string]$binding.scene
            $scenePath = "$resourceRoot/$sceneRelative"
            if (-not $entryByPath.ContainsKey($scenePath)) {
                continue
            }

            try {
                $text = Read-PckTextEntry -Path $Path -Entry $entryByPath[$scenePath]
                $skeletonDataResource = Get-ResourcePath -ResourceRoot $resourceRoot -RelativePath ([string]$binding.skeletonData)
                if ($text.IndexOf('[gd_scene', [StringComparison]::Ordinal) -ne 0) {
                    Add-ValidationError "Exported scene is not a text Godot scene: res://$scenePath"
                }
                if ($text.IndexOf($skeletonDataResource, [StringComparison]::Ordinal) -lt 0) {
                    Add-ValidationError "Exported scene '$sceneRelative' lost its private skeleton-data reference '$skeletonDataResource'."
                }
                $requiredSceneTexts = Get-JsonPropertyValue -Object $binding -Name "requiredText"
                foreach ($requiredText in @($requiredSceneTexts)) {
                    $requiredSceneText = [string]$requiredText
                    if (-not [string]::IsNullOrEmpty($requiredSceneText) -and
                        $text.IndexOf($requiredSceneText, [StringComparison]::Ordinal) -lt 0) {
                        Add-ValidationError "Exported scene '$sceneRelative' lost required contract text '$requiredSceneText'."
                    }
                }
                foreach ($nodeType in @($Contract.forbiddenSerializedSceneNodeTypes)) {
                    $forbiddenNodeType = "type=`"$([string]$nodeType)`""
                    if ($text.IndexOf($forbiddenNodeType, [StringComparison]::Ordinal) -ge 0) {
                        Add-ValidationError (
                            "Exported scene '$sceneRelative' contains serialized " +
                            "'$([string]$nodeType)' preview geometry.")
                    }
                }
            }
            catch {
                Add-ValidationError $_.Exception.Message
            }
        }
    }
    else {
        foreach ($entry in $index.Entries) {
            if ([string]$entry.Path -like "$privatePrefix*") {
                Add-ValidationError "Inactive skin unexpectedly leaked a private resource into PCK: $($entry.Path)"
            }
        }
    }

    if ($script:ValidationErrors.Count -gt 0) {
        Stop-Validation "PCK contract check failed."
    }
    Write-Host "[ironclad-skin] PCK contract passed ($($index.Entries.Count) entries, Godot $($index.EngineVersion), pack format $($index.FormatVersion))." -ForegroundColor Green
}

try {
    $projectRoot = [IO.Path]::GetFullPath($ProjectDir)
    $contractFullPath = [IO.Path]::GetFullPath($ContractPath)
    if (-not [IO.File]::Exists($contractFullPath)) {
        throw "Contract file does not exist: $contractFullPath"
    }
    $contract = [IO.File]::ReadAllText($contractFullPath) | ConvertFrom-Json
    $contract = Resolve-RuntimeLayoutContract -Contract $contract -RequestedLayout $RuntimeLayout
    $activation = Get-SkinActivationState -ProjectRoot $projectRoot -Contract $contract
}
catch {
    Add-ValidationError $_.Exception.Message
    Stop-Validation "Unable to load the asset contract."
}

if ($Phase -eq "Source" -or $Phase -eq "All") {
    Test-SourceAssets -ProjectRoot $projectRoot -Contract $contract -Activation $activation
}

if ($Phase -eq "Pck" -or $Phase -eq "All") {
    if ([string]::IsNullOrWhiteSpace($PckPath)) {
        Add-ValidationError "-PckPath is required for phase '$Phase'."
        Stop-Validation "PCK contract check failed."
    }
    Test-PckContents -Path ([IO.Path]::GetFullPath($PckPath)) -Contract $contract -Activation $activation
}
