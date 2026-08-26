[CmdletBinding()]
param(
    [ValidateSet("Source", "Pck", "All")]
    [string]$Phase = "Source",

    [string]$ProjectDir = "",

    [string]$ContractPath = "",

    [string]$PckPath = "",

    [string]$GodotExe = "",

    [string]$Sts2Dir = "",

    [switch]$AllowExtractedTemplateVersions
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
    foreach ($spineSet in @($Contract.spineSets)) {
        Add-RequiredPath -Set $required -RelativePath ([string]$spineSet.skeletonData)
        Add-RequiredPath -Set $required -RelativePath ([string]$spineSet.skeleton)
        Add-RequiredPath -Set $required -RelativePath ([string]$spineSet.atlas)
        foreach ($page in @($spineSet.pages)) {
            Add-RequiredPath -Set $required -RelativePath ([string]$page)
        }
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

function Test-PngSignature {
    param([Parameter(Mandatory = $true)][string]$Path)

    $expected = [byte[]](137, 80, 78, 71, 13, 10, 26, 10)
    $stream = [IO.File]::OpenRead($Path)
    try {
        if ($stream.Length -lt $expected.Length) {
            return $false
        }
        for ($i = 0; $i -lt $expected.Length; $i++) {
            if ($stream.ReadByte() -ne $expected[$i]) {
                return $false
            }
        }
        return $true
    }
    finally {
        $stream.Dispose()
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
    elseif ((Get-Item -LiteralPath $extensionPath).Length -ne (Get-Item -LiteralPath $template).Length) {
        throw "Content-addressed Spine GDExtension manifest has an unexpected size: $extensionPath"
    }
    if (-not [IO.File]::Exists($destinationDll)) {
        [IO.File]::Copy($sourceDll, $destinationDll, $false)
    }
    elseif ((Get-Item -LiteralPath $destinationDll).Length -ne (Get-Item -LiteralPath $sourceDll).Length) {
        throw "Content-addressed Spine GDExtension DLL has an unexpected size: $destinationDll"
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
        [switch]$AllowExtractedTemplateVersions
    )

    if ([string]::IsNullOrWhiteSpace($GodotPath)) {
        Add-ValidationError "GodotExe is required when the Ironclad skin bundle is active."
        return
    }
    if ([string]::IsNullOrWhiteSpace($GameRoot)) {
        Add-ValidationError "Sts2Dir is required when the Ironclad skin bundle is active."
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
        $previousTemplateVersions = $env:VIVHITE_ALLOW_EXTRACTED_TEMPLATE_VERSIONS
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
            if ($AllowExtractedTemplateVersions) {
                $env:VIVHITE_ALLOW_EXTRACTED_TEMPLATE_VERSIONS = "1"
            }
            else {
                $env:VIVHITE_ALLOW_EXTRACTED_TEMPLATE_VERSIONS = $null
            }
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
            $env:VIVHITE_ALLOW_EXTRACTED_TEMPLATE_VERSIONS = $previousTemplateVersions
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

    if ($script:ValidationErrors.Count -gt 0) {
        Write-Host "[ironclad-skin] Spine animation/slot/event checks skipped until the complete asset set exists."
        Stop-Validation "Source asset completeness check failed."
    }

    Write-Host "[ironclad-skin] Asset set is complete; checking bindings, PNGs, and Spine wrapper metadata..."
    foreach ($relativePath in $required) {
        if ($relativePath.EndsWith(".png", [StringComparison]::OrdinalIgnoreCase)) {
            $fullPath = Get-SafeChildPath -BasePath $Activation.AssetRoot -RelativePath $relativePath
            if (-not (Test-PngSignature -Path $fullPath)) {
                Add-ValidationError "Expected a real PNG file, but the PNG signature is invalid: $resourceRoot/$relativePath"
            }
        }
    }

    foreach ($spineSet in @($Contract.spineSets)) {
        $setName = [string]$spineSet.name
        $skeletonDataRelative = [string]$spineSet.skeletonData
        $skeletonRelative = [string]$spineSet.skeleton
        $atlasRelative = [string]$spineSet.atlas
        $atlasSourceRelative = [string]$spineSet.atlasSourcePath
        $skeletonDataPath = Get-SafeChildPath -BasePath $Activation.AssetRoot -RelativePath $skeletonDataRelative
        $skeletonPath = Get-SafeChildPath -BasePath $Activation.AssetRoot -RelativePath $skeletonRelative
        $atlasPath = Get-SafeChildPath -BasePath $Activation.AssetRoot -RelativePath $atlasRelative
        $skeletonDataText = [IO.File]::ReadAllText($skeletonDataPath)
        $expectedSkeletonReference = Get-ResourcePath -ResourceRoot $resourceRoot -RelativePath $skeletonRelative
        $expectedAtlasReference = Get-ResourcePath -ResourceRoot $resourceRoot -RelativePath $atlasRelative

        if ($skeletonDataText.IndexOf($expectedSkeletonReference, [StringComparison]::Ordinal) -lt 0) {
            Add-ValidationError "Spine set '$setName' skeleton data must reference '$expectedSkeletonReference'."
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
            foreach ($page in @($spineSet.pages)) {
                $pageName = [IO.Path]::GetFileName([string]$page)
                $pageFound = $false
                foreach ($line in ($atlasData -split "`r?`n")) {
                    if ([string]::Equals($line.Trim(), $pageName, [StringComparison]::Ordinal)) {
                        $pageFound = $true
                        break
                    }
                }
                if (-not $pageFound) {
                    Add-ValidationError "Spine set '$setName' .spatlas atlas_data does not declare page '$pageName'."
                }
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
    }

    $textExtensions = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
    foreach ($extension in @(".tres", ".tscn", ".spatlas", ".import", ".remap")) {
        [void]$textExtensions.Add($extension)
    }
    foreach ($file in Get-ChildItem -LiteralPath $Activation.AssetRoot -File -Recurse) {
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

    Invoke-GodotSpineContract -ProjectRoot $ProjectRoot -GodotPath $GodotExe -GameRoot $Sts2Dir -AllowExtractedTemplateVersions:$AllowExtractedTemplateVersions
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
    }

    $segmentAlternation = (@($Contract.forbiddenPckSegments) | ForEach-Object {
            [Text.RegularExpressions.Regex]::Escape([string]$_)
        }) -join "|"
    $segmentRegex = "(?i)(^|/)($segmentAlternation)(/|$)"
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
    }

    $resourceRoot = ([string]$Contract.resourceRoot).Replace('\', '/').Trim('/')
    if ($Activation.Active) {
        foreach ($relativePath in (Get-ExpectedLogicalAssets -Contract $Contract)) {
            $logicalPath = "$resourceRoot/$relativePath"
            $candidates = @($logicalPath, "$logicalPath.import", "$logicalPath.remap")
            $found = $false
            foreach ($candidate in $candidates) {
                if ($entryByPath.ContainsKey($candidate) -and (($entryByPath[$candidate].Flags -band 2) -eq 0)) {
                    $found = $true
                    break
                }
            }
            if (-not $found) {
                Add-ValidationError "Exported PCK has no logical resource entry for: res://$logicalPath"
            }
        }
    }
    else {
        $privatePrefix = $resourceRoot + "/"
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
