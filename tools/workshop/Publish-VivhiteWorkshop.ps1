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
if ([string]::IsNullOrWhiteSpace($Visibility)) { $Visibility = [string]$config.visibility }
if ($PublishedFileId -eq 0 -and [UInt64]::TryParse([string]$config.published_file_id, [ref]$PublishedFileId) -eq $false) {
    throw "workshop-item.json has an invalid published_file_id."
}

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
        -RepoRoot $repoRoot -OutputPath $previewPath
    if ($LASTEXITCODE -ne 0) { throw "Workshop preview generation failed with exit code $LASTEXITCODE." }
}

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
    preview = [ordered]@{
        bytes = ([IO.FileInfo]::new($previewPath)).Length
        sha256 = (Get-FileHash -LiteralPath $previewPath -Algorithm SHA256).Hash
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
