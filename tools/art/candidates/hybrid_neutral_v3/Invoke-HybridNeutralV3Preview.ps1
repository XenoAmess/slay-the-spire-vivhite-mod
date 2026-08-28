[CmdletBinding()]
param(
    [string]$GodotExe = "",
    [string]$Sts2Dir = "",
    [string]$ProjectDir = "",
    [string]$OutputDir = "",
    [ValidateRange(64, 8192)][int]$Width = 1280,
    [ValidateRange(64, 8192)][int]$Height = 900,
    [ValidateRange(0.01, 4.0)][double]$SceneScale = 0.28,
    [double]$OriginX = 320.0,
    [double]$OriginY = 700.0,
    [double]$SceneOffsetX = 5.0,
    [double]$SceneOffsetY = -19.0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../../../.."))
if ([string]::IsNullOrWhiteSpace($ProjectDir)) { $ProjectDir = Join-Path $repoRoot "Vivhite" }
$ProjectDir = [IO.Path]::GetFullPath($ProjectDir)
$localPropsPath = Join-Path $ProjectDir "local.props"
if (([string]::IsNullOrWhiteSpace($GodotExe) -or [string]::IsNullOrWhiteSpace($Sts2Dir)) -and [IO.File]::Exists($localPropsPath)) {
    [xml]$localProps = [IO.File]::ReadAllText($localPropsPath)
    $propertyGroup = @($localProps.Project.PropertyGroup) | Select-Object -First 1
    if ($null -ne $propertyGroup) {
        if ([string]::IsNullOrWhiteSpace($GodotExe)) { $GodotExe = [string]$propertyGroup.GodotExe }
        if ([string]::IsNullOrWhiteSpace($Sts2Dir)) { $Sts2Dir = [string]$propertyGroup.Sts2Dir }
    }
}

function Resolve-GodotConsolePath {
    param([Parameter(Mandatory = $true)][string]$Path)
    $fullPath = [IO.Path]::GetFullPath($Path)
    if (-not [IO.File]::Exists($fullPath)) { return $fullPath }
    $name = [IO.Path]::GetFileNameWithoutExtension($fullPath)
    if (-not $name.EndsWith("_console", [StringComparison]::OrdinalIgnoreCase)) {
        $candidate = Join-Path ([IO.Path]::GetDirectoryName($fullPath)) ($name + "_console.exe")
        if ([IO.File]::Exists($candidate)) { return $candidate }
    }
    return $fullPath
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
        if ($argument -match '[\s"]') { '"' + $argument.Replace('"', '\"') + '"' } else { $argument }
    }
    $process = Start-Process -FilePath $GodotExe -ArgumentList ($quoted -join ' ') -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -Wait -PassThru
    foreach ($path in @($stdout, $stderr)) {
        if ([IO.File]::Exists($path)) {
            foreach ($line in [IO.File]::ReadAllLines($path)) {
                if (-not [string]::IsNullOrWhiteSpace($line)) { Write-Host $line }
            }
        }
    }
    if ($null -eq $process.ExitCode) { throw "Godot ended without an exit code. See $LogStem.*.log" }
    return [int]$process.ExitCode
}

if ([string]::IsNullOrWhiteSpace($GodotExe)) { throw "GodotExe is required." }
$GodotExe = Resolve-GodotConsolePath -Path $GodotExe
if (-not [IO.File]::Exists($GodotExe)) { throw "Godot executable does not exist: $GodotExe" }
if ([string]::IsNullOrWhiteSpace($Sts2Dir)) { throw "Sts2Dir is required." }
$Sts2Dir = [IO.Path]::GetFullPath($Sts2Dir)
$basePck = Join-Path $Sts2Dir "SlayTheSpire2.pck"
if (-not [IO.File]::Exists($basePck)) { throw "Base-game PCK does not exist: $basePck" }

$builder = Join-Path $PSScriptRoot "build_hybrid_neutral_v3_candidate.gd"
$validator = Join-Path $PSScriptRoot "validate_hybrid_neutral_v3_candidate.gd"
$renderer = Join-Path $PSScriptRoot "render_hybrid_neutral_v3_exact.gd"
foreach ($required in @($builder, $validator, $renderer)) {
    if (-not [IO.File]::Exists($required)) { throw "Required neutral tool does not exist: $required" }
}

$gameSpineDll = Join-Path $Sts2Dir "libspine_godot.windows.template_release.x86_64.dll"
$extensionManifests = @(Get-ChildItem -LiteralPath (Join-Path $ProjectDir "bin/spine_contract") `
        -Filter 'spine_godot_extension.gdextension' -File -Recurse -Force -ErrorAction SilentlyContinue)
if ($extensionManifests.Count -ne 1) { throw "Expected one prepared Spine GDExtension; found $($extensionManifests.Count)." }
$editorSpineDll = Join-Path $extensionManifests[0].DirectoryName "windows/libspine_godot.windows.editor.x86_64.dll"
if (-not [IO.File]::Exists($gameSpineDll) -or -not [IO.File]::Exists($editorSpineDll)) {
    throw "The game-matching Spine GDExtension is incomplete."
}
if (-not [string]::Equals(
        (Get-FileHash -LiteralPath $gameSpineDll -Algorithm SHA256).Hash,
        (Get-FileHash -LiteralPath $editorSpineDll -Algorithm SHA256).Hash,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw "Prepared Spine GDExtension does not match the game DLL."
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $OutputDir = Join-Path $repoRoot ".work/combat-rig-compare-preview/hybrid-neutral-v3-exact-$stamp"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$workRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot ".work")).TrimEnd('\', '/')
if (-not $OutputDir.StartsWith($workRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must stay below $workRoot."
}
if ([IO.Directory]::Exists($OutputDir) -and @(Get-ChildItem -LiteralPath $OutputDir -Force).Count -gt 0) {
    throw "OutputDir must be new or empty: $OutputDir"
}
[void][IO.Directory]::CreateDirectory($OutputDir)

$projectPathBytes = [Text.Encoding]::UTF8.GetBytes($ProjectDir.ToLowerInvariant())
$sha256 = [Security.Cryptography.SHA256]::Create()
try { $projectHash = ([BitConverter]::ToString($sha256.ComputeHash($projectPathBytes))).Replace('-', '').Substring(0, 24) }
finally { $sha256.Dispose() }
$spineMutex = New-Object Threading.Mutex($false, "Local\VivhiteIroncladSpine-$projectHash")
$spineMutexAcquired = $false
$previousDotnetRoot = $env:DOTNET_ROOT
$previousDotnetRootX64 = $env:DOTNET_ROOT_X64
$previousPath = $env:PATH
$previousSkipExport = $env:STS2_SKIP_PCK_EXPORT
$previousPck = $env:VIVHITE_STS2_PCK_PATH
try {
    try { $spineMutexAcquired = $spineMutex.WaitOne([TimeSpan]::FromMinutes(10)) }
    catch [Threading.AbandonedMutexException] { $spineMutexAcquired = $true }
    if (-not $spineMutexAcquired) { throw "Timed out waiting for exclusive Godot Spine preview access." }

    $dotnetRoot = $env:DOTNET_ROOT
    if ([string]::IsNullOrWhiteSpace($dotnetRoot)) {
        $knownDotnet = "C:\Users\xenoa\AppData\Local\Microsoft\dotnet"
        if ([IO.Directory]::Exists($knownDotnet)) { $dotnetRoot = $knownDotnet }
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

    Write-Host "[hybrid-neutral-v3] Building isolated candidate..."
    if ((Invoke-HiddenGodot -Arguments @('--headless', '--path', $ProjectDir, '--script', $builder, '--', 'build-neutral-v3') `
            -LogStem (Join-Path $OutputDir 'build')) -ne 0) {
        throw "Neutral candidate build failed."
    }
    if ((Invoke-HiddenGodot -Arguments @('--headless', '--path', $ProjectDir, '--import') `
            -LogStem (Join-Path $OutputDir 'import')) -ne 0) {
        throw "Neutral candidate import failed."
    }
    Write-Host "[hybrid-neutral-v3] Running read-only static/runtime gate..."
    if ((Invoke-HiddenGodot -Arguments @('--headless', '--path', $ProjectDir, '--script', $validator) `
            -LogStem (Join-Path $OutputDir 'validate')) -ne 0) {
        throw "Neutral static/runtime validation failed."
    }

    Write-Host "[hybrid-neutral-v3] Rendering in an independent hidden Vulkan process..."
    $renderArguments = @(
        '--path', $ProjectDir, '--display-driver', 'windows', '--rendering-driver', 'vulkan',
        '--resolution', '64x64', '--position', '-32000,-32000', '--script', $renderer, '--',
        '--pck', $basePck, '--output', $OutputDir, '--width', [string]$Width, '--height', [string]$Height,
        '--scene-scale', $SceneScale.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--origin-x', $OriginX.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--origin-y', $OriginY.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--scene-offset-x', $SceneOffsetX.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--scene-offset-y', $SceneOffsetY.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture)
    )
    if ((Invoke-HiddenGodot -Arguments $renderArguments -LogStem (Join-Path $OutputDir 'render')) -ne 0) {
        throw "Hidden Vulkan neutral acceptance failed. See $OutputDir."
    }
    $summaryPath = Join-Path $OutputDir "summary.json"
    if (-not [IO.File]::Exists($summaryPath)) { throw "Renderer did not write summary.json." }
    $summary = [IO.File]::ReadAllText($summaryPath) | ConvertFrom-Json
    if ($summary.success -ne $true -or @($summary.frames).Count -ne 19) {
        throw "Neutral exact report did not pass all 19 samples: $summaryPath"
    }
    Write-Host "[hybrid-neutral-v3] Report: $summaryPath" -ForegroundColor Green
    Write-Host "[hybrid-neutral-v3] Game-green sheet: $(Join-Path $OutputDir $summary.contact_sheets.all_game_green)" -ForegroundColor Green
}
finally {
    $env:DOTNET_ROOT = $previousDotnetRoot
    $env:DOTNET_ROOT_X64 = $previousDotnetRootX64
    $env:PATH = $previousPath
    $env:STS2_SKIP_PCK_EXPORT = $previousSkipExport
    $env:VIVHITE_STS2_PCK_PATH = $previousPck
    if ($spineMutexAcquired) { $spineMutex.ReleaseMutex() }
    $spineMutex.Dispose()
}
