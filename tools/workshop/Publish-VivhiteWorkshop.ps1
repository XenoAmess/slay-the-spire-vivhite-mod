[CmdletBinding()]
param(
    [ValidateSet("public", "friends", "private", "unlisted")]
    [string]$Visibility = "",
    [UInt64]$PublishedFileId = 0,
    [switch]$SkipBuild,
    [switch]$SkipPreview,
    [switch]$PrepareOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$repoRoot = [IO.Path]::GetFullPath($repoRoot)
$configPath = Join-Path $repoRoot "workshop\workshop-item.json"
$descriptionPath = Join-Path $repoRoot "workshop\description.bbcode"
$previewPath = Join-Path $repoRoot "workshop\preview.jpg"
$runtimeRoot = Join-Path $repoRoot "workshop\.runtime"
$contentDir = Join-Path $runtimeRoot "content\Vivhite"
$resultPath = Join-Path $runtimeRoot "publish-result.json"
$uploadLogPath = Join-Path $runtimeRoot "upload.log"
$propsPath = Join-Path $repoRoot "Vivhite\local.props"

foreach ($required in @($configPath, $descriptionPath, $propsPath)) {
    if (-not [IO.File]::Exists($required)) { throw "Required Workshop input is missing: $required" }
}
[void][IO.Directory]::CreateDirectory($runtimeRoot)

[xml]$props = [IO.File]::ReadAllText($propsPath)
function Get-LocalProperty([string]$Name) {
    $node = $props.SelectSingleNode("//*[local-name()='$Name']")
    if ($null -eq $node -or [string]::IsNullOrWhiteSpace($node.InnerText)) {
        throw "local.props is missing $Name."
    }
    return [Environment]::ExpandEnvironmentVariables($node.InnerText.Trim())
}

$gameDir = Get-LocalProperty "Sts2Dir"
$dataDir = Get-LocalProperty "Sts2DataDir"
$godotExe = Get-LocalProperty "GodotExe"
$dataDir = $dataDir.Replace('$(Sts2Dir)', $gameDir)
foreach ($required in @(
    (Join-Path $dataDir "Steamworks.NET.dll"),
    (Join-Path $dataDir "steam_api64.dll"),
    $godotExe
)) {
    if (-not [IO.File]::Exists($required)) { throw "Required local release dependency is missing: $required" }
}

$dotnetCommand = Get-Command dotnet -CommandType Application -ErrorAction SilentlyContinue
$dotnetCandidates = @(
    $(if (-not [string]::IsNullOrWhiteSpace($env:DOTNET_ROOT)) { Join-Path $env:DOTNET_ROOT "dotnet.exe" }),
    $(if ($null -ne $dotnetCommand) { $dotnetCommand.Source }),
    (Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)) "Microsoft\dotnet\dotnet.exe")
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and [IO.File]::Exists($_) }
if ($dotnetCandidates.Count -eq 0) { throw "A .NET 9 SDK dotnet.exe was not found." }
$dotnetExe = [IO.Path]::GetFullPath($dotnetCandidates[0])
$dotnetRoot = Split-Path -Parent $dotnetExe
$env:DOTNET_ROOT = $dotnetRoot
$env:PATH = $dotnetRoot + ";" + $env:PATH

$config = [IO.File]::ReadAllText($configPath, [Text.UTF8Encoding]::new($false, $true)) | ConvertFrom-Json
if ($config.app_id -ne 2868840) { throw "Workshop config App ID must be 2868840." }
$configVersion = [string]$config.version
if ($configVersion -notmatch '^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$') {
    throw "Workshop config version is not a SemVer-like value: '$configVersion'."
}
$previewPath = [IO.Path]::GetFullPath((Join-Path $repoRoot ([string]$config.preview_file -replace '/', '\')))
if ([string]::IsNullOrWhiteSpace($Visibility)) { $Visibility = [string]$config.visibility }
if ($PublishedFileId -eq 0 -and [UInt64]::TryParse([string]$config.published_file_id, [ref]$PublishedFileId) -eq $false) {
    throw "workshop-item.json has an invalid published_file_id."
}

function Read-StrictUtf8Text {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        return [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false, $true))
    }
    catch {
        throw "Workshop text is not valid UTF-8: $Path. $($_.Exception.Message)"
    }
}

function Get-Sha256Hex {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not [IO.File]::Exists($Path)) { throw "Cannot hash missing Workshop artifact: $Path" }
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Resolve-WorkshopPath {
    param([Parameter(Mandatory = $true)][string]$Value)
    if ([IO.Path]::IsPathRooted($Value)) { return [IO.Path]::GetFullPath($Value) }
    return [IO.Path]::GetFullPath((Join-Path $repoRoot ($Value -replace '/', '\')))
}

function Assert-RepoChild {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )
    $prefix = $repoRoot.TrimEnd('\') + '\'
    if (-not $Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase) -or
        $Path.IndexOf('\.git\', [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
        $Path.IndexOf('\.runtime\', [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        throw "$Label must be a tracked repository path (not Git metadata/runtime): $Path"
    }
}

function Assert-WorkshopDescriptionContract {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Version
    )
    $description = Read-StrictUtf8Text -Path $Path
    if ([string]::IsNullOrWhiteSpace($description) -or $description.IndexOf([char]0) -ge 0) {
        throw "Workshop description must be non-empty and must not contain NUL characters."
    }
    $descriptionBytes = [Text.UTF8Encoding]::new($false, $true).GetByteCount($description)
    if ($description.Length -gt 8000 -or $descriptionBytes -gt 8000) {
        throw "Workshop description must be at most 8000 UTF-8 bytes/characters; found $descriptionBytes bytes and $($description.Length) characters."
    }

    $zhVersion = [Text.RegularExpressions.Regex]::Match($description, '(?m)\[b\]当前版本：\[/b\]\s*(?<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)')
    $enVersion = [Text.RegularExpressions.Regex]::Match($description, '(?m)\[b\]Version:\[/b\]\s*(?<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)')
    if (-not $zhVersion.Success -or -not $enVersion.Success -or
        $zhVersion.Groups['version'].Value -ne $Version -or $enVersion.Groups['version'].Value -ne $Version) {
        throw "Chinese and English current-version lines must both match metadata version $Version."
    }

    $headingPattern = '\[h2\](?:更新日志\s*/\s*Changelog|Changelog\s*/\s*更新日志)\[/h2\]'
    $headingCount = [Text.RegularExpressions.Regex]::Matches($description, $headingPattern).Count
    if ($headingCount -ne 2) { throw "Workshop description must contain exactly one bilingual changelog heading per language (found $headingCount)." }
    $releaseCount = [Text.RegularExpressions.Regex]::Matches($description, "\[h3\]\s*$([Text.RegularExpressions.Regex]::Escape($Version))(?:\s|[（(])").Count
    if ($releaseCount -ne 2) { throw "Workshop description must contain changelog release $Version in both languages (found $releaseCount)." }

    $englishMarker = '[h1]English[/h1]'
    $englishIndex = $description.IndexOf($englishMarker, [StringComparison]::Ordinal)
    if ($englishIndex -lt 0) { throw "Workshop description is missing the English section marker." }
    $zh = $description.Substring(0, $englishIndex)
    $en = $description.Substring($englishIndex)
    foreach ($term in @('钨合金棍', 'Buffer', '事件循环', 'public-beta', 'Vulkan', 'OpenGL3', 'D3D12')) {
        if ($zh.IndexOf($term, [StringComparison]::OrdinalIgnoreCase) -lt 0) { throw "Chinese changelog/description is missing required term '$term'." }
    }
    foreach ($term in @('Tungsten Rod', 'Buffer', 'Event Loop', 'public-beta', 'Vulkan', 'OpenGL3', 'D3D12')) {
        if ($en.IndexOf($term, [StringComparison]::OrdinalIgnoreCase) -lt 0) { throw "English changelog/description is missing required term '$term'." }
    }
    return $description
}

function Assert-WorkshopPreviewContract {
    param(
        [Parameter(Mandatory = $true)][object]$Config,
        [Parameter(Mandatory = $true)][string]$PreviewFullPath
    )
    if ($null -eq $Config.preview) { throw "workshop-item.json must contain preview artifact metadata." }
    if (-not [IO.File]::Exists($PreviewFullPath)) { throw "Workshop preview is missing: $PreviewFullPath" }
    $preview = $Config.preview
    $version = [string]$Config.version
    if ([string]$preview.version -ne $version) {
        throw "Preview metadata version $($preview.version) is stale; expected $version. Do not use -SkipPreview to bypass regeneration."
    }
    $actualHash = Get-Sha256Hex -Path $PreviewFullPath
    if (-not [string]::Equals($actualHash, [string]$preview.sha256, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Preview SHA-256 does not match workshop-item.json; refusing stale/untracked preview publication."
    }
    $fileInfo = [IO.FileInfo]::new($PreviewFullPath)
    if ($fileInfo.Length -lt 16 -or $fileInfo.Length -ge 1000000) {
        throw "Workshop preview must be at least 16 bytes and less than 1 MB; found $($fileInfo.Length) bytes."
    }
    if ([int64]$preview.bytes -ne $fileInfo.Length -or [int]$preview.width -ne 1024 -or [int]$preview.height -ne 1024) {
        throw "Preview dimensions/byte metadata do not match the actual 1024x1024 artifact."
    }

    $historyValue = [string]$preview.history_dir
    if ([string]::IsNullOrWhiteSpace($historyValue)) { throw "Preview metadata must declare history_dir." }
    $historyPath = Resolve-WorkshopPath -Value $historyValue
    Assert-RepoChild -Path $historyPath -Label "preview.history_dir"
    if (-not [IO.Directory]::Exists($historyPath)) { throw "Preview history directory is missing: $historyPath" }
    foreach ($archive in @(Get-ChildItem -LiteralPath $historyPath -File -Filter 'preview-v*-sha256-*.jpg')) {
        $match = [Text.RegularExpressions.Regex]::Match($archive.Name, '^preview-v(?<version>.+?)-sha256-(?<sha>[0-9a-fA-F]{64})\.jpg$')
        if (-not $match.Success) { throw "Preview history file has an unauditable name: $($archive.FullName)" }
        $archiveHash = Get-Sha256Hex -Path $archive.FullName
        if (-not [string]::Equals($archiveHash, $match.Groups['sha'].Value, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Preview history hash does not match its filename: $($archive.Name)"
        }
        $sidecar = "$($archive.FullName).json"
        if (-not [IO.File]::Exists($sidecar)) { throw "Preview history sidecar is missing: $sidecar" }
        $record = Read-StrictUtf8Text -Path $sidecar | ConvertFrom-Json
        if ([string]$record.version -ne $match.Groups['version'].Value -or
            -not [string]::Equals([string]$record.sha256, $match.Groups['sha'].Value, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Preview history sidecar does not match its image: $sidecar"
        }
    }

    $heroPath = Join-Path $repoRoot 'assets\vivhite-ironclad\custom\character_select\sources\vivhite-character-select-hero-master-v1.png'
    $transitionPath = Join-Path $repoRoot 'Vivhite\Vivhite\skins\ironclad\transitions\vivhite_character_select_transition.png'
    if ([string]$preview.hero_source_sha256 -ne (Get-Sha256Hex -Path $heroPath) -or
        [string]$preview.transition_source_sha256 -ne (Get-Sha256Hex -Path $transitionPath)) {
        throw "Preview source hashes are stale; regenerate preview before publishing."
    }
    return [ordered]@{
        bytes = $fileInfo.Length
        sha256 = $actualHash
        width = [int]$preview.width
        height = [int]$preview.height
        history_dir = $historyValue
    }
}

function Get-ChangelogForUpload {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][string]$Version,
        [Parameter(Mandatory = $true)][string]$OutputPath
    )
    $pattern = '(?is)\[h2\](?:更新日志\s*/\s*Changelog|Changelog\s*/\s*更新日志)\[/h2\].*?(?=\[h1\]|\z)'
    $sections = [Text.RegularExpressions.Regex]::Matches($Description, $pattern)
    if ($sections.Count -ne 2) { throw "Cannot derive a bilingual changelog note: expected 2 sections, found $($sections.Count)." }
    $note = "Vivhite $Version changelog`r`n`r`n" + (($sections | ForEach-Object { $_.Value.Trim() }) -join "`r`n`r`n")
    $noteBytes = [Text.UTF8Encoding]::new($false, $true).GetByteCount($note)
    if ($noteBytes -gt 8000) { throw "Derived Workshop change note exceeds 8000 UTF-8 bytes: $noteBytes" }
    $parent = [IO.Path]::GetDirectoryName($OutputPath)
    if (-not [string]::IsNullOrWhiteSpace($parent)) { [void][IO.Directory]::CreateDirectory($parent) }
    [IO.File]::WriteAllText($OutputPath, $note, [Text.UTF8Encoding]::new($false, $true))
    return $noteBytes
}

$descriptionText = Assert-WorkshopDescriptionContract -Path $descriptionPath -Version $configVersion

if (-not $SkipBuild) {
    Write-Host "[workshop] Building an isolated same-batch Release triplet."
    & $dotnetExe build (Join-Path $repoRoot "Vivhite\Vivhite.csproj") -c Release `
        "/p:ModOutputDir=$contentDir" "/p:GodotExe=$godotExe" "/p:RitsuLibAutoCopy=false"
    if ($LASTEXITCODE -ne 0) { throw "The isolated Vivhite Release build failed with exit code $LASTEXITCODE." }
}

$pckPath = Join-Path $contentDir "Vivhite.pck"
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "tools\test\Verify-VivhitePck.ps1") `
    -RepoRoot $repoRoot -PckPath $pckPath -GodotExe $godotExe
if ($LASTEXITCODE -ne 0) { throw "The final Vivhite PCK gate failed with exit code $LASTEXITCODE." }

if (-not $SkipPreview) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repoRoot "tools\workshop\New-VivhiteWorkshopPreview.ps1") `
        -RepoRoot $repoRoot -OutputPath $previewPath -MetadataPath $configPath
    if ($LASTEXITCODE -ne 0) { throw "Workshop preview generation failed with exit code $LASTEXITCODE." }
}

# The preview generator updates the artifact metadata atomically. Reload the
# authoritative item file before every subsequent gate so -SkipPreview cannot
# hide a stale image or a version drift.
$config = [IO.File]::ReadAllText($configPath, [Text.UTF8Encoding]::new($false, $true)) | ConvertFrom-Json
if ([string]$config.version -ne $configVersion) {
    throw "Workshop metadata version changed unexpectedly while preparing the release."
}
$previewPath = [IO.Path]::GetFullPath((Join-Path $repoRoot ([string]$config.preview_file -replace '/', '\')))
$descriptionText = Assert-WorkshopDescriptionContract -Path $descriptionPath -Version ([string]$config.version)
$previewEvidence = Assert-WorkshopPreviewContract -Config $config -PreviewFullPath $previewPath
$changeNotePath = Join-Path $runtimeRoot ("change-note-v{0}.txt" -f [string]$config.version)
$changeNoteBytes = Get-ChangelogForUpload -Description $descriptionText -Version ([string]$config.version) -OutputPath $changeNotePath
Write-Host "[workshop] Material gate passed: version=$($config.version) preview_sha256=$($previewEvidence.sha256) change_note_bytes=$changeNoteBytes"

$manifestPath = Join-Path $contentDir "Vivhite.json"
$manifest = [IO.File]::ReadAllText($manifestPath, [Text.UTF8Encoding]::new($false, $true)) | ConvertFrom-Json
if ($manifest.id -ne "Vivhite" -or $manifest.version -ne [string]$config.version -or
    $manifest.min_game_version -ne "0.111.0" -or -not $manifest.has_dll -or -not $manifest.has_pck) {
    throw "The staged manifest does not match the Workshop release contract."
}
$dependency = @($manifest.dependencies | Where-Object { $_.id -eq "STS2-RitsuLib" })
if ($dependency.Count -ne 1 -or $dependency[0].version -ne "0.5.14") {
    throw "The staged manifest must require exactly STS2-RitsuLib 0.5.14."
}
$triplet = @(Get-ChildItem -LiteralPath $contentDir -File | Sort-Object Name)
if ($triplet.Count -ne 3 -or @(Get-ChildItem -LiteralPath $contentDir -Directory).Count -ne 0) {
    throw "Workshop content must contain exactly the three Vivhite release files."
}
$preflight = [ordered]@{
    schema = 1
    recorded_utc = [DateTime]::UtcNow.ToString("O")
    git_head = (& git -C $repoRoot rev-parse HEAD).Trim()
    app_id = 2868840
    version = [string]$manifest.version
    min_game_version = [string]$manifest.min_game_version
    dependency_id = [string]$config.dependency_id
    dependency_version = [string]$dependency[0].version
    visibility = $Visibility
    preview = $previewEvidence
    changelog = [ordered]@{
        version = [string]$config.version
        file = $changeNotePath
        bytes = $changeNoteBytes
        sha256 = (Get-FileHash -LiteralPath $changeNotePath -Algorithm SHA256).Hash
    }
    files = @($triplet | ForEach-Object {
        [ordered]@{ name = $_.Name; bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    })
}
$preflightPath = Join-Path $runtimeRoot "preflight.json"
[IO.File]::WriteAllText($preflightPath, ($preflight | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
Write-Host "[workshop] Preflight evidence: $preflightPath"

if ($PrepareOnly) {
    Write-Host "[workshop] PrepareOnly requested; no Steam mutation was attempted."
    return
}
if ((Get-Process -Name steam -ErrorAction SilentlyContinue | Measure-Object).Count -eq 0) {
    throw "Steam is not running. Start and sign in to the trusted Steam client before publishing."
}

$uploaderProject = Join-Path $repoRoot "tools\workshop\SteamWorkshopUploader\SteamWorkshopUploader.csproj"
$uploaderOutput = Join-Path $runtimeRoot "uploader"
& $dotnetExe build $uploaderProject -c Release -o $uploaderOutput "/p:SteamworksDir=$dataDir"
if ($LASTEXITCODE -ne 0) { throw "Steam Workshop uploader build failed with exit code $LASTEXITCODE." }
$uploaderDll = Join-Path $uploaderOutput "SteamWorkshopUploader.dll"
$title = [string]$config.title
$uploaderArgs = @(
    $uploaderDll,
    "--app-id", "2868840",
    "--published-file-id", [string]$PublishedFileId,
    "--content", $contentDir,
    "--preview", $previewPath,
    "--title", $title,
    "--description-file", $descriptionPath,
    "--change-note-file", $changeNotePath,
    "--visibility", $Visibility,
    "--tags", "English,Simplified Chinese",
    "--dependency-id", [string]$config.dependency_id,
    "--version", [string]$config.version,
    "--result", $resultPath,
    "--timeout-seconds", "1800"
)
Write-Host "[workshop] Publishing through the logged-in Steam client; no credentials are read or stored."
$previousErrorAction = $ErrorActionPreference
try {
    # Steam's native library writes harmless initialization diagnostics to stderr.
    # Keep those lines in the upload log without converting them into a terminating
    # PowerShell NativeCommandError.
    $ErrorActionPreference = "Continue"
    & $dotnetExe @uploaderArgs 2>&1 | Tee-Object -LiteralPath $uploadLogPath
    $uploadExitCode = $LASTEXITCODE
}
finally { $ErrorActionPreference = $previousErrorAction }
if ($uploadExitCode -ne 0) {
    throw "Steam Workshop publication failed with exit code $uploadExitCode. Receipt: $resultPath; log: $uploadLogPath"
}
$result = [IO.File]::ReadAllText($resultPath, [Text.UTF8Encoding]::new($false, $true)) | ConvertFrom-Json
if ($result.status -ne "published" -or -not $result.upload_complete -or -not $result.dependency_complete) {
    throw "Steam returned success, but the publish receipt is incomplete: $resultPath"
}
Write-Host "[workshop] COMPLETE item=$($result.published_file_id) url=$($result.url)"
Write-Host "[workshop] Upload log: $uploadLogPath"
