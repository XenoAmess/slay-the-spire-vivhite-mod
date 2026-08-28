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
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = Join-Path $repoRoot "Vivhite"
}
$ProjectDir = [IO.Path]::GetFullPath($ProjectDir)
$localPropsPath = Join-Path $ProjectDir "local.props"
if (([string]::IsNullOrWhiteSpace($GodotExe) -or [string]::IsNullOrWhiteSpace($Sts2Dir)) -and
    [IO.File]::Exists($localPropsPath)) {
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
    $quoted = foreach ($argument in $Arguments) {
        if ($argument -match '[\s"]') { '"' + $argument.Replace('"', '\"') + '"' } else { $argument }
    }
    $process = Start-Process -FilePath $GodotExe -ArgumentList ($quoted -join ' ') `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -Wait -PassThru
    $process.Refresh()
    foreach ($path in @($stdout, $stderr)) {
        if ([IO.File]::Exists($path)) {
            foreach ($line in [IO.File]::ReadAllLines($path)) {
                if (-not [string]::IsNullOrWhiteSpace($line)) { Write-Host $line }
            }
        }
    }
    if ($null -eq $process.ExitCode) {
        throw "Godot ended without an observable exit code. See '$stdout' and '$stderr'."
    }
    return [int]$process.ExitCode
}

if ([string]::IsNullOrWhiteSpace($GodotExe)) {
    throw "GodotExe is required (pass -GodotExe or configure Vivhite/local.props)."
}
$GodotExe = Resolve-GodotConsolePath -Path $GodotExe
if (-not [IO.File]::Exists($GodotExe)) { throw "Godot executable does not exist: $GodotExe" }
if ([string]::IsNullOrWhiteSpace($Sts2Dir)) {
    throw "Sts2Dir is required (pass -Sts2Dir or configure Vivhite/local.props)."
}
$Sts2Dir = [IO.Path]::GetFullPath($Sts2Dir)
$basePck = Join-Path $Sts2Dir "SlayTheSpire2.pck"
if (-not [IO.File]::Exists($basePck)) { throw "Base-game PCK does not exist: $basePck" }

$candidateTres = Join-Path $ProjectDir "tools/candidates/hybrid_cast_set/vivhite_combat_skeleton_data.tres"
$renderScript = Join-Path $PSScriptRoot "render_cast_exact.gd"
if (-not [IO.File]::Exists($candidateTres)) { throw "Hybrid cast candidate .tres does not exist: $candidateTres" }
if (-not [IO.File]::Exists($renderScript)) { throw "Exact cast renderer does not exist: $renderScript" }

$gameSpineDll = Join-Path $Sts2Dir "libspine_godot.windows.template_release.x86_64.dll"
$extensionManifests = @(Get-ChildItem -LiteralPath (Join-Path $ProjectDir "bin/spine_contract") `
    -Filter 'spine_godot_extension.gdextension' -File -Recurse -Force -ErrorAction SilentlyContinue)
if ($extensionManifests.Count -ne 1) {
    throw "Expected exactly one prepared local Spine GDExtension; found $($extensionManifests.Count)."
}
$editorSpineDll = Join-Path $extensionManifests[0].DirectoryName "windows/libspine_godot.windows.editor.x86_64.dll"
if (-not [IO.File]::Exists($gameSpineDll) -or -not [IO.File]::Exists($editorSpineDll)) {
    throw "The game-matching local Spine GDExtension is incomplete."
}
if ((Get-FileHash -LiteralPath $gameSpineDll -Algorithm SHA256).Hash -ne
    (Get-FileHash -LiteralPath $editorSpineDll -Algorithm SHA256).Hash) {
    throw "Prepared Spine GDExtension does not match the game DLL."
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss")
    $OutputDir = Join-Path $repoRoot ".work/combat-rig-compare-preview/hybrid-cast-exact-$stamp"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$workRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot ".work")).TrimEnd('\', '/')
if (-not $OutputDir.StartsWith($workRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must stay below '$workRoot', got '$OutputDir'."
}
if ([IO.Directory]::Exists($OutputDir) -and @(Get-ChildItem -LiteralPath $OutputDir -Force).Count -gt 0) {
    throw "OutputDir must be new or empty so prior acceptance evidence is never overwritten: $OutputDir"
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
    Write-Host "[hybrid-cast-exact] Rendering candidate in hidden off-screen Vulkan..."
    $exitCode = Invoke-HiddenGodot -Arguments @(
        '--path', $ProjectDir, '--display-driver', 'windows', '--rendering-driver', 'vulkan',
        '--resolution', '64x64', '--position', '-32000,-32000', '--script', $renderScript, '--',
        '--pck', $basePck, '--output', $OutputDir, '--width', [string]$Width, '--height', [string]$Height,
        '--scene-scale', $SceneScale.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--origin-x', $OriginX.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--origin-y', $OriginY.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--scene-offset-x', $SceneOffsetX.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
        '--scene-offset-y', $SceneOffsetY.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture)
    ) -LogStem (Join-Path $OutputDir "render")
    if ($exitCode -ne 0) { throw "Hidden Vulkan cast acceptance failed with exit code $exitCode. See '$OutputDir'." }
    $summaryPath = Join-Path $OutputDir "summary.json"
    if (-not [IO.File]::Exists($summaryPath)) { throw "Renderer exited without summary.json: $OutputDir" }
    $summary = [IO.File]::ReadAllText($summaryPath) | ConvertFrom-Json
    if ($summary.success -ne $true -or @($summary.frames).Count -ne 14 -or
        $summary.character_only_contract_passed -ne $true -or
        $summary.eye_only_contract_passed -ne $true -or
        $summary.mix_contract_passed -ne $true) {
        throw "Renderer report did not pass all 14 exact cast samples: $summaryPath"
    }
    foreach ($frame in @($summary.frames)) {
        if ($frame.composite.passed -ne $true -or $frame.character_only.passed -ne $true -or
            @($frame.suppressed_runtime_vfx.slots).Count -ne 3 -or
            $frame.suppressed_runtime_vfx.external_eye_fire_hidden -ne $true) {
            throw "Composite, character-only, or VFX isolation failed at t=$($frame.requested_time)."
        }
    }
    Write-Host "[hybrid-cast-exact] Report: $summaryPath" -ForegroundColor Green
    Write-Host "[hybrid-cast-exact] Composite: $(Join-Path $OutputDir $summary.contact_sheets.composite)" -ForegroundColor Green
    Write-Host "[hybrid-cast-exact] Character-only: $(Join-Path $OutputDir $summary.contact_sheets.character_only)" -ForegroundColor Green
    Write-Host "[hybrid-cast-exact] Eye-only: $(Join-Path $OutputDir $summary.contact_sheets.eye_only)" -ForegroundColor Green
    Write-Host "[hybrid-cast-exact] Eye alignment: $(Join-Path $OutputDir $summary.contact_sheets.eye_alignment)" -ForegroundColor Green
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
