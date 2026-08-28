[CmdletBinding(DefaultParameterSetName = "Compare")]
param(
    [Parameter(Mandatory = $true, ParameterSetName = "Compare")]
    [ValidateNotNullOrEmpty()]
    [string[]]$Candidate,

    [Parameter(ParameterSetName = "SelfTest")]
    [switch]$SelfTest,

    [string]$GodotExe = "",

    [string]$Sts2Dir = "",

    [string]$ProjectDir = "",

    [string]$OutputDir = "",

    [ValidateRange(64, 8192)]
    [int]$Width = 1280,

    [ValidateRange(64, 8192)]
    [int]$Height = 900,

    [ValidateRange(5, 21)]
    [int]$Samples = 5,

    [ValidateRange(0.01, 4.0)]
    [double]$SceneScale = 0.28,

    [ValidateRange(0.01, 4.0)]
    [double]$AuthoredCharacterScale = 0.70,

    [double]$OriginX = 320.0,

    [double]$OriginY = 700.0,

    [double]$SceneOffsetX = 5.0,

    [double]$SceneOffsetY = -19.0,

    [switch]$KeepStage
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../../../.."))
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = Join-Path $script:RepoRoot "Vivhite"
}
$ProjectDir = [IO.Path]::GetFullPath($ProjectDir)

$localPropsPath = Join-Path $ProjectDir "local.props"
if (([string]::IsNullOrWhiteSpace($GodotExe) -or [string]::IsNullOrWhiteSpace($Sts2Dir)) -and
    [IO.File]::Exists($localPropsPath)) {
    [xml]$localProps = [IO.File]::ReadAllText($localPropsPath)
    $propertyGroup = @($localProps.Project.PropertyGroup) | Select-Object -First 1
    if ($null -ne $propertyGroup) {
        if ([string]::IsNullOrWhiteSpace($GodotExe)) {
            $GodotExe = [string]$propertyGroup.GodotExe
        }
        if ([string]::IsNullOrWhiteSpace($Sts2Dir)) {
            $Sts2Dir = [string]$propertyGroup.Sts2Dir
        }
    }
}

function Resolve-GodotConsolePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not [IO.File]::Exists($fullPath)) {
        return $fullPath
    }
    $name = [IO.Path]::GetFileNameWithoutExtension($fullPath)
    if (-not $name.EndsWith("_console", [StringComparison]::OrdinalIgnoreCase)) {
        $candidate = Join-Path ([IO.Path]::GetDirectoryName($fullPath)) ($name + "_console.exe")
        if ([IO.File]::Exists($candidate)) {
            return $candidate
        }
    }
    return $fullPath
}

function Get-SafeSlug {
    param([Parameter(Mandatory = $true)][string]$Value)

    $slug = $Value.Trim().ToLowerInvariant() -replace '[^a-z0-9._-]+', '-'
    $slug = $slug.Trim('-', '.')
    if ([string]::IsNullOrWhiteSpace($slug)) {
        throw "Candidate name '$Value' has no filesystem-safe characters."
    }
    return $slug
}

function Get-PathBelow {
    param(
        [Parameter(Mandatory = $true)][string]$Base,
        [Parameter(Mandatory = $true)][string]$Relative
    )

    if ([IO.Path]::IsPathRooted($Relative)) {
        throw "Expected a relative path below '$Base', got '$Relative'."
    }
    $baseFull = [IO.Path]::GetFullPath($Base).TrimEnd('\', '/')
    $result = [IO.Path]::GetFullPath((Join-Path $baseFull $Relative))
    if (-not $result.StartsWith($baseFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path '$Relative' escapes '$baseFull'."
    }
    return $result
}

function ConvertTo-ResourcePath {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $projectFull = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\', '/')
    $pathFull = [IO.Path]::GetFullPath($Path)
    $prefix = $projectFull + [IO.Path]::DirectorySeparatorChar
    if (-not $pathFull.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path '$pathFull' is not below Godot project '$projectFull'."
    }
    return "res://" + $pathFull.Substring($prefix.Length).Replace('\', '/')
}

function Resolve-InputPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ($Path.StartsWith("res://", [StringComparison]::OrdinalIgnoreCase)) {
        return Get-PathBelow -Base $ProjectDir -Relative $Path.Substring(6)
    }
    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $script:RepoRoot $Path))
}

function Select-SingleCandidateFile {
    param(
        [Parameter(Mandatory = $true)][IO.FileInfo[]]$Files,
        [Parameter(Mandatory = $true)][string]$Kind,
        [string]$PreferredPattern = "combat"
    )

    if ($Files.Count -eq 0) {
        throw "Candidate bundle contains no $Kind."
    }
    if ($Files.Count -eq 1) {
        return $Files[0]
    }
    $preferred = @($Files | Where-Object { $_.BaseName.IndexOf($PreferredPattern, [StringComparison]::OrdinalIgnoreCase) -ge 0 })
    if ($preferred.Count -eq 1) {
        return $preferred[0]
    }
    $paths = ($Files | ForEach-Object FullName) -join "', '"
    throw "Candidate bundle has ambiguous $Kind files: '$paths'. Pass the intended .tres directly."
}

function Resolve-ResourceReference {
    param(
        [Parameter(Mandatory = $true)][string]$Reference,
        [Parameter(Mandatory = $true)][string]$SearchRoot
    )

    if ($Reference.StartsWith("res://", [StringComparison]::OrdinalIgnoreCase)) {
        $projectPath = Get-PathBelow -Base $ProjectDir -Relative $Reference.Substring(6)
        if ([IO.File]::Exists($projectPath)) {
            return Get-Item -LiteralPath $projectPath
        }
    }
    else {
        $relativePath = [IO.Path]::GetFullPath((Join-Path $SearchRoot $Reference))
        if ([IO.File]::Exists($relativePath)) {
            return Get-Item -LiteralPath $relativePath
        }
    }

    $leaf = [IO.Path]::GetFileName($Reference.Replace('/', '\'))
    $matches = @(Get-ChildItem -LiteralPath $SearchRoot -File -Recurse -Force | Where-Object {
            [string]::Equals($_.Name, $leaf, [StringComparison]::OrdinalIgnoreCase)
        })
    if ($matches.Count -eq 1) {
        return $matches[0]
    }
    if ($matches.Count -eq 0) {
        throw "Could not resolve resource reference '$Reference' below '$SearchRoot'."
    }
    throw "Resource reference '$Reference' is ambiguous below '$SearchRoot'."
}

function Get-AtlasPageNames {
    param([Parameter(Mandatory = $true)][string]$AtlasPath)

    try {
        $wrapper = [IO.File]::ReadAllText($AtlasPath) | ConvertFrom-Json
    }
    catch {
        throw "Spine atlas wrapper is invalid JSON '$AtlasPath': $($_.Exception.Message)"
    }
    if ($null -eq $wrapper.PSObject.Properties['atlas_data']) {
        throw "Spine atlas wrapper has no atlas_data: $AtlasPath"
    }
    $lines = @(([string]$wrapper.atlas_data).Replace("`r", "") -split "`n")
    $pages = New-Object "System.Collections.Generic.List[string]"
    for ($index = 0; $index -lt $lines.Count; $index++) {
        $line = ([string]$lines[$index]).Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or ($index + 1) -ge $lines.Count) {
            continue
        }
        $startsBlock = $index -eq 0 -or [string]::IsNullOrWhiteSpace(([string]$lines[$index - 1]).Trim())
        if ($startsBlock -and ([string]$lines[$index + 1]).Trim() -match '^size:\s*[0-9]+\s*,\s*[0-9]+\s*$') {
            $pages.Add($line)
        }
    }
    if ($pages.Count -eq 0) {
        throw "Spine atlas wrapper declares no pages: $AtlasPath"
    }
    return @($pages)
}

function Resolve-CandidateBundle {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$InputPath
    )

    $resolvedInput = Resolve-InputPath -Path $InputPath
    if (-not [IO.File]::Exists($resolvedInput) -and -not [IO.Directory]::Exists($resolvedInput)) {
        throw "Candidate '$Name' path does not exist: $resolvedInput"
    }
    $sourceRoot = if ([IO.Directory]::Exists($resolvedInput)) {
        $resolvedInput
    }
    else {
        [IO.Path]::GetDirectoryName($resolvedInput)
    }

    $tres = $null
    $skeleton = $null
    $atlas = $null
    if ([IO.File]::Exists($resolvedInput)) {
        $file = Get-Item -LiteralPath $resolvedInput
        switch ($file.Extension.ToLowerInvariant()) {
            ".tres" { $tres = $file }
            ".spjson" { $skeleton = $file }
            ".spatlas" { $atlas = $file }
            default { throw "Candidate '$Name' must be a directory, .tres, .spjson, or .spatlas; got '$resolvedInput'." }
        }
    }
    else {
        $tresFiles = @(Get-ChildItem -LiteralPath $sourceRoot -Filter '*.tres' -File -Recurse -Force | Where-Object {
                [IO.File]::ReadAllText($_.FullName).IndexOf('type="SpineSkeletonDataResource"', [StringComparison]::Ordinal) -ge 0
            })
        if ($tresFiles.Count -gt 0) {
            $tres = Select-SingleCandidateFile -Files $tresFiles -Kind "SpineSkeletonDataResource .tres"
        }
    }

    if ($null -ne $tres) {
        $text = [IO.File]::ReadAllText($tres.FullName)
        $atlasMatch = [Text.RegularExpressions.Regex]::Match(
            $text,
            '\[ext_resource\s+type="SpineAtlasResource"\s+path="([^"]+)"',
            [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        $skeletonMatch = [Text.RegularExpressions.Regex]::Match(
            $text,
            '\[ext_resource\s+type="SpineSkeletonFileResource"\s+path="([^"]+)"',
            [Text.RegularExpressions.RegexOptions]::IgnoreCase)
        if (-not $atlasMatch.Success -or -not $skeletonMatch.Success) {
            throw "Candidate '$Name' .tres does not declare Spine atlas and skeleton resources: $($tres.FullName)"
        }
        $atlas = Resolve-ResourceReference -Reference $atlasMatch.Groups[1].Value -SearchRoot $sourceRoot
        $skeleton = Resolve-ResourceReference -Reference $skeletonMatch.Groups[1].Value -SearchRoot $sourceRoot
    }

    if ($null -eq $skeleton) {
        $skeleton = Select-SingleCandidateFile `
            -Files @(Get-ChildItem -LiteralPath $sourceRoot -Filter '*.spjson' -File -Recurse -Force) `
            -Kind ".spjson"
    }
    if ($null -eq $atlas) {
        $atlas = Select-SingleCandidateFile `
            -Files @(Get-ChildItem -LiteralPath $sourceRoot -Filter '*.spatlas' -File -Recurse -Force) `
            -Kind ".spatlas"
    }
    if (-not $skeleton.Extension.Equals(".spjson", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Candidate '$Name' must use a private .spjson skeleton; got '$($skeleton.FullName)'."
    }
    if (-not $atlas.Extension.Equals(".spatlas", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Candidate '$Name' must use a .spatlas wrapper; got '$($atlas.FullName)'."
    }

    $pages = @()
    foreach ($pageName in (Get-AtlasPageNames -AtlasPath $atlas.FullName)) {
        if ([IO.Path]::IsPathRooted($pageName) -or $pageName.Replace('\', '/').Contains('../')) {
            throw "Candidate '$Name' atlas page path is not local: '$pageName'."
        }
        $pagePath = [IO.Path]::GetFullPath((Join-Path $atlas.DirectoryName $pageName.Replace('/', '\')))
        if ([IO.File]::Exists($pagePath)) {
            $pages += (Get-Item -LiteralPath $pagePath)
            continue
        }
        $pages += (Resolve-ResourceReference -Reference $pageName -SearchRoot $sourceRoot)
    }

    return [pscustomobject]@{
        Name = $Name
        Slug = Get-SafeSlug -Value $Name
        Input = $resolvedInput
        SourceRoot = $sourceRoot
        Tres = $tres
        Skeleton = $skeleton
        Atlas = $atlas
        Pages = $pages
    }
}

function Copy-CandidateToStage {
    param(
        [Parameter(Mandatory = $true)]$Bundle,
        [Parameter(Mandatory = $true)][string]$StageRoot
    )

    $candidateDir = Get-PathBelow -Base $StageRoot -Relative $Bundle.Slug
    [void][IO.Directory]::CreateDirectory($candidateDir)
    $candidateResourceDir = ConvertTo-ResourcePath -ProjectRoot $ProjectDir -Path $candidateDir
    $stagedSkeleton = Join-Path $candidateDir "candidate.spjson"
    $stagedAtlas = Join-Path $candidateDir "candidate.spatlas"
    [IO.File]::Copy($Bundle.Skeleton.FullName, $stagedSkeleton, $false)
    try {
        $stagedAtlasWrapper = [IO.File]::ReadAllText($Bundle.Atlas.FullName) | ConvertFrom-Json
    }
    catch {
        throw "Candidate '$($Bundle.Name)' atlas wrapper is invalid JSON: $($_.Exception.Message)"
    }
    # The Spine GDExtension resolves atlas page names relative to source_path,
    # not necessarily relative to the loaded .spatlas wrapper. Point only the
    # isolated staged copy at its staged pages; the candidate source is never
    # edited.
    $stagedAtlasWrapper.source_path = "$candidateResourceDir/candidate.atlas"
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText(
        $stagedAtlas,
        (($stagedAtlasWrapper | ConvertTo-Json -Depth 12 -Compress) + "`n"),
        $utf8NoBom)

    $pageRecords = @()
    $pageNames = @(Get-AtlasPageNames -AtlasPath $Bundle.Atlas.FullName)
    if ($pageNames.Count -ne @($Bundle.Pages).Count) {
        throw "Candidate '$($Bundle.Name)' atlas page resolution is inconsistent."
    }
    for ($index = 0; $index -lt $pageNames.Count; $index++) {
        $pageName = ([string]$pageNames[$index]).Replace('/', [IO.Path]::DirectorySeparatorChar)
        $destination = Get-PathBelow -Base $candidateDir -Relative $pageName
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($destination))
        [IO.File]::Copy($Bundle.Pages[$index].FullName, $destination, $false)
        $pageRecords += [ordered]@{
                atlas_name = ([string]$pageNames[$index]).Replace('\', '/')
                source_path = $Bundle.Pages[$index].FullName.Replace('\', '/')
                sha256 = (Get-FileHash -LiteralPath $Bundle.Pages[$index].FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
    }

    $wrapper = Join-Path $candidateDir "candidate_skeleton_data.tres"
    $wrapperText = @"
[gd_resource type="SpineSkeletonDataResource" load_steps=3 format=3]

[ext_resource type="SpineAtlasResource" path="$candidateResourceDir/candidate.spatlas" id="1_atlas"]
[ext_resource type="SpineSkeletonFileResource" path="$candidateResourceDir/candidate.spjson" id="2_skeleton"]

[resource]
atlas_res = ExtResource("1_atlas")
skeleton_file_res = ExtResource("2_skeleton")
"@
    [IO.File]::WriteAllText($wrapper, $wrapperText.Replace("`r`n", "`n") + "`n", $utf8NoBom)

    $wrapperResource = ConvertTo-ResourcePath -ProjectRoot $ProjectDir -Path $wrapper
    $tresRecord = if ($null -ne $Bundle.Tres) { $Bundle.Tres.FullName.Replace('\', '/') } else { $null }
    return [ordered]@{
        name = $Bundle.Name
        slug = $Bundle.Slug
        resource = $wrapperResource
        source = [ordered]@{
            input_path = $Bundle.Input.Replace('\', '/')
            skeleton = [ordered]@{
                path = $Bundle.Skeleton.FullName.Replace('\', '/')
                sha256 = (Get-FileHash -LiteralPath $Bundle.Skeleton.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
            atlas = [ordered]@{
                path = $Bundle.Atlas.FullName.Replace('\', '/')
                sha256 = (Get-FileHash -LiteralPath $Bundle.Atlas.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
            }
            pages = $pageRecords
            tres_path = $tresRecord
        }
    }
}

function Get-SpineExtensionInfo {
    $gameDll = Join-Path $Sts2Dir "libspine_godot.windows.template_release.x86_64.dll"
    if (-not [IO.File]::Exists($gameDll)) {
        throw "Game Spine GDExtension DLL does not exist: $gameDll"
    }
    $manifests = @(Get-ChildItem -LiteralPath (Join-Path $ProjectDir "bin/spine_contract") `
            -Filter 'spine_godot_extension.gdextension' -File -Recurse -Force -ErrorAction SilentlyContinue)
    if ($manifests.Count -ne 1) {
        return $null
    }
    $dll = Join-Path $manifests[0].DirectoryName "windows/libspine_godot.windows.editor.x86_64.dll"
    if (-not [IO.File]::Exists($dll)) {
        return $null
    }
    $gameHash = (Get-FileHash -LiteralPath $gameDll -Algorithm SHA256).Hash.ToLowerInvariant()
    $editorHash = (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not [string]::Equals($gameHash, $editorHash, [StringComparison]::OrdinalIgnoreCase)) {
        return $null
    }
    return [ordered]@{
        manifest = $manifests[0].FullName.Replace('\', '/')
        dll = $dll.Replace('\', '/')
        sha256 = $editorHash
    }
}

function Initialize-SpineExtensionIfNeeded {
    $extension = Get-SpineExtensionInfo
    if ($null -ne $extension) {
        return $extension
    }
    $validator = Join-Path $ProjectDir "tools/Validate-IroncladSkin.ps1"
    if (-not [IO.File]::Exists($validator)) {
        throw "Spine extension is not prepared and validator is missing: $validator"
    }
    Write-Host "[combat-rig-compare] Preparing the game's actual Spine GDExtension..."
    & $validator -Phase Source -ProjectDir $ProjectDir -GodotExe $GodotExe -Sts2Dir $Sts2Dir
    if ($LASTEXITCODE -ne 0) {
        throw "Spine extension preparation failed with exit code $LASTEXITCODE."
    }
    $extension = Get-SpineExtensionInfo
    if ($null -eq $extension) {
        throw "Spine validator completed but the prepared DLL does not match the game DLL."
    }
    return $extension
}

function Invoke-HiddenGodot {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogStem
    )

    $stdout = "$LogStem.stdout.log"
    $stderr = "$LogStem.stderr.log"
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($stdout))
    $quoted = foreach ($argument in $Arguments) {
        if ($argument -match '[\s"]') {
            '"' + $argument.Replace('\', '\').Replace('"', '\"') + '"'
        }
        else {
            $argument
        }
    }
    $process = Start-Process `
        -FilePath $GodotExe `
        -ArgumentList ($quoted -join ' ') `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -Wait `
        -PassThru
    $process.Refresh()
    foreach ($path in @($stdout, $stderr)) {
        if ([IO.File]::Exists($path)) {
            foreach ($line in [IO.File]::ReadAllLines($path)) {
                if (-not [string]::IsNullOrWhiteSpace($line)) {
                    Write-Host $line
                }
            }
        }
    }
    $exitCode = $process.ExitCode
    if ($null -eq $exitCode) {
        throw "Godot process ended without an observable exit code. See '$stdout' and '$stderr'."
    }
    return [int]$exitCode
}

if ([string]::IsNullOrWhiteSpace($GodotExe)) {
    throw "GodotExe is required (pass -GodotExe or configure Vivhite/local.props)."
}
$GodotExe = Resolve-GodotConsolePath -Path $GodotExe
if (-not [IO.File]::Exists($GodotExe)) {
    throw "Godot executable does not exist: $GodotExe"
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $OutputDir = Join-Path $script:RepoRoot ".work/combat-rig-compare-preview/$stamp"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$workRoot = [IO.Path]::GetFullPath((Join-Path $script:RepoRoot ".work")).TrimEnd('\', '/')
if (-not $OutputDir.StartsWith($workRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must stay below '$workRoot', got '$OutputDir'."
}
[void][IO.Directory]::CreateDirectory($OutputDir)

$renderScript = Join-Path $PSScriptRoot "render_combat_rig_compare.gd"
if (-not [IO.File]::Exists($renderScript)) {
    throw "Renderer script does not exist: $renderScript"
}

if ($SelfTest) {
    $exitCode = Invoke-HiddenGodot -Arguments @(
        '--headless', '--path', $ProjectDir, '--script', $renderScript, '--',
        '--output', $OutputDir, '--samples', [string]$Samples, '--self-test', 'true'
    ) -LogStem (Join-Path $OutputDir "self-test")
    if ($exitCode -ne 0) {
        throw "Combat comparison self-test failed with exit code $exitCode."
    }
    Write-Host "[combat-rig-compare] Self-test report: $(Join-Path $OutputDir 'self-test.json')" -ForegroundColor Green
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Sts2Dir)) {
    throw "Sts2Dir is required (pass -Sts2Dir or configure Vivhite/local.props)."
}
$Sts2Dir = [IO.Path]::GetFullPath($Sts2Dir)
$basePck = Join-Path $Sts2Dir "SlayTheSpire2.pck"
if (-not [IO.File]::Exists($basePck)) {
    throw "Base-game PCK does not exist: $basePck"
}
if ([Math]::Abs($AuthoredCharacterScale - 0.70) -gt 0.00001) {
    throw "This comparison is intentionally fixed to the approved 70% authored scale; got $AuthoredCharacterScale."
}

$specs = @()
$names = New-Object "System.Collections.Generic.HashSet[string]" ([StringComparer]::OrdinalIgnoreCase)
foreach ($value in $Candidate) {
    $separator = $value.IndexOf('=')
    if ($separator -le 0 -or $separator -eq ($value.Length - 1)) {
        throw "Candidate must use Name=Path syntax, got '$value'."
    }
    $name = $value.Substring(0, $separator).Trim()
    $path = $value.Substring($separator + 1).Trim()
    if (-not $names.Add($name)) {
        throw "Candidate name is duplicated: '$name'."
    }
    $specs += (Resolve-CandidateBundle -Name $name -InputPath $path)
}
if ($specs.Count -lt 2) {
    throw "At least two -Candidate Name=Path values are required."
}

$extensionInfo = Initialize-SpineExtensionIfNeeded

# Godot copies the loaded GDExtension to a fixed '~libspine...' sibling. Two
# concurrent import/render processes for the same project race on that file and
# can crash inside the extension loader. Use the same project-scoped mutex as
# the source validator and hold it across both candidate import and rendering.
$projectPathBytes = [Text.Encoding]::UTF8.GetBytes($ProjectDir.ToLowerInvariant())
$sha256 = [Security.Cryptography.SHA256]::Create()
try {
    $projectHash = ([BitConverter]::ToString($sha256.ComputeHash($projectPathBytes))).Replace('-', '').Substring(0, 24)
}
finally {
    $sha256.Dispose()
}
$spineMutex = New-Object Threading.Mutex($false, "Local\VivhiteIroncladSpine-$projectHash")
$spineMutexAcquired = $false
Write-Host "[combat-rig-compare] Waiting for exclusive Godot Spine preview access..."
try {
    try {
        $spineMutexAcquired = $spineMutex.WaitOne([TimeSpan]::FromMinutes(10))
    }
    catch [Threading.AbandonedMutexException] {
        $spineMutexAcquired = $true
    }
    if (-not $spineMutexAcquired) {
        throw "Timed out waiting for another Godot Spine import/render process to finish."
    }
}
catch {
    $spineMutex.Dispose()
    throw
}

$stageBase = [IO.Path]::GetFullPath((Join-Path $ProjectDir "bin/combat_compare_preview/stage"))
$runId = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + [Guid]::NewGuid().ToString("N").Substring(0, 8)
$stageRoot = Get-PathBelow -Base $stageBase -Relative $runId
[void][IO.Directory]::CreateDirectory($stageRoot)

$previousDotnetRoot = $env:DOTNET_ROOT
$previousDotnetRootX64 = $env:DOTNET_ROOT_X64
$previousPath = $env:PATH
$previousSkipExport = $env:STS2_SKIP_PCK_EXPORT
$previousPck = $env:VIVHITE_STS2_PCK_PATH
try {
    $candidateRecords = @()
    foreach ($spec in $specs) {
        $candidateRecords += (Copy-CandidateToStage -Bundle $spec -StageRoot $stageRoot)
    }
    $manifest = [ordered]@{
        schema_version = 1
        generated_utc = [DateTime]::UtcNow.ToString("o")
        authored_character_scale = $AuthoredCharacterScale
        scene_scale = $SceneScale
        candidates = $candidateRecords
        spine_extension = $extensionInfo
        base_pck = [ordered]@{
            path = $basePck.Replace('\', '/')
            sha256 = (Get-FileHash -LiteralPath $basePck -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
    $manifestPath = Join-Path $stageRoot "candidates.json"
    $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    $manifest | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $OutputDir "candidate-manifest.json") -Encoding UTF8

    $dotnetRoot = $env:DOTNET_ROOT
    if ([string]::IsNullOrWhiteSpace($dotnetRoot)) {
        $knownDotnet = "C:\Users\xenoa\AppData\Local\Microsoft\dotnet"
        if ([IO.Directory]::Exists($knownDotnet)) {
            $dotnetRoot = $knownDotnet
        }
        else {
            $dotnetCommand = Get-Command dotnet.exe -ErrorAction SilentlyContinue
            if ($null -ne $dotnetCommand) {
                $dotnetRoot = Split-Path -Parent $dotnetCommand.Source
            }
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($dotnetRoot)) {
        $env:DOTNET_ROOT = $dotnetRoot
        $env:DOTNET_ROOT_X64 = $dotnetRoot
        if (-not $env:PATH.StartsWith($dotnetRoot + [IO.Path]::PathSeparator, [StringComparison]::OrdinalIgnoreCase)) {
            $env:PATH = $dotnetRoot + [IO.Path]::PathSeparator + $env:PATH
        }
    }
    $env:STS2_SKIP_PCK_EXPORT = "1"
    $env:VIVHITE_STS2_PCK_PATH = $basePck

    Write-Host "[combat-rig-compare] Importing isolated candidate copies (headless; no game interaction)..."
    $importExit = Invoke-HiddenGodot -Arguments @(
        '--headless', '--path', $ProjectDir, '--import'
    ) -LogStem (Join-Path $OutputDir "import")
    if ($importExit -ne 0) {
        throw "Godot candidate import failed with exit code $importExit."
    }

    Write-Host "[combat-rig-compare] Rendering in an independent hidden Vulkan process..."
    $renderExit = Invoke-HiddenGodot -Arguments @(
        '--path', $ProjectDir,
        '--display-driver', 'windows',
        '--rendering-driver', 'vulkan',
        '--resolution', '64x64',
        '--position', '-32000,-32000',
        '--script', $renderScript,
        '--',
        '--manifest', $manifestPath,
        '--pck', $basePck,
        '--output', $OutputDir,
        '--width', [string]$Width,
        '--height', [string]$Height,
        '--samples', [string]$Samples,
        '--scene-scale', $SceneScale.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--authored-character-scale', $AuthoredCharacterScale.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--origin-x', $OriginX.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--origin-y', $OriginY.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--scene-offset-x', $SceneOffsetX.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--scene-offset-y', $SceneOffsetY.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture)
    ) -LogStem (Join-Path $OutputDir "render")
    if ($renderExit -ne 0) {
        throw "Hidden Vulkan combat comparison failed with exit code $renderExit. See '$OutputDir'."
    }

    $summaryPath = Join-Path $OutputDir "summary.json"
    if (-not [IO.File]::Exists($summaryPath)) {
        throw "Renderer exited successfully without summary.json: $OutputDir"
    }
    $summary = [IO.File]::ReadAllText($summaryPath) | ConvertFrom-Json
    if ($summary.success -ne $true) {
        throw "Renderer report did not pass: $summaryPath"
    }
    $candidateReports = @($summary.candidates)
    if ($candidateReports.Count -ne $specs.Count) {
        throw "Renderer reported $($candidateReports.Count) candidates; expected $($specs.Count)."
    }
    foreach ($candidateReport in $candidateReports) {
        if (@($candidateReport.animations).Count -ne 8) {
            throw "Candidate '$($candidateReport.name)' did not report all eight combat animations."
        }
        foreach ($animation in @($candidateReport.animations)) {
            if (@($animation.frames).Count -ne $Samples) {
                throw "Candidate '$($candidateReport.name)' animation '$($animation.name)' has incomplete frames."
            }
        }
    }
    Write-Host "[combat-rig-compare] Report: $summaryPath" -ForegroundColor Green
    Write-Host "[combat-rig-compare] Visual index: $(Join-Path $OutputDir 'index.html')" -ForegroundColor Green
}
finally {
    $env:DOTNET_ROOT = $previousDotnetRoot
    $env:DOTNET_ROOT_X64 = $previousDotnetRootX64
    $env:PATH = $previousPath
    $env:STS2_SKIP_PCK_EXPORT = $previousSkipExport
    $env:VIVHITE_STS2_PCK_PATH = $previousPck
    if (-not $KeepStage -and -not [string]::IsNullOrWhiteSpace($stageRoot)) {
        $resolvedStageRoot = [IO.Path]::GetFullPath($stageRoot)
        $requiredPrefix = $stageBase.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
        if (-not $resolvedStageRoot.StartsWith($requiredPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean an unexpected stage path: $resolvedStageRoot"
        }
        if ([IO.Directory]::Exists($resolvedStageRoot)) {
            Remove-Item -LiteralPath $resolvedStageRoot -Recurse -Force
        }
    }
    if ($spineMutexAcquired) {
        $spineMutex.ReleaseMutex()
    }
    $spineMutex.Dispose()
}
