[CmdletBinding()]
param(
    [string]$GodotExe = "",
    [string]$Sts2Dir = "",
    [string]$ProjectDir = "",
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../../../.."))
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = Join-Path $repoRoot "Vivhite"
}
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
    $name = [IO.Path]::GetFileNameWithoutExtension($fullPath)
    if (-not $name.EndsWith("_console", [StringComparison]::OrdinalIgnoreCase)) {
        $candidate = Join-Path ([IO.Path]::GetDirectoryName($fullPath)) ($name + "_console.exe")
        if ([IO.File]::Exists($candidate)) { return $candidate }
    }
    return $fullPath
}

function Invoke-HiddenGodot {
    param([string[]]$Arguments, [string]$LogStem)
    $stdout = "$LogStem.stdout.log"
    $stderr = "$LogStem.stderr.log"
    $quoted = foreach ($argument in $Arguments) {
        if ($argument -match '[\s"]') { '"' + $argument.Replace('"', '\"') + '"' } else { $argument }
    }
    $process = Start-Process -FilePath $GodotExe -ArgumentList ($quoted -join ' ') -WindowStyle Hidden `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr -Wait -PassThru
    $process.Refresh()
    foreach ($path in @($stdout, $stderr)) {
        if ([IO.File]::Exists($path)) {
            foreach ($line in [IO.File]::ReadAllLines($path)) {
                if (-not [string]::IsNullOrWhiteSpace($line)) { Write-Host $line }
            }
        }
    }
    if ($null -eq $process.ExitCode) { throw "Godot ended without an observable exit code." }
    return [int]$process.ExitCode
}

if ([string]::IsNullOrWhiteSpace($GodotExe)) { throw "GodotExe is required." }
$GodotExe = Resolve-GodotConsolePath $GodotExe
if (-not [IO.File]::Exists($GodotExe)) { throw "Godot executable does not exist: $GodotExe" }
if ([string]::IsNullOrWhiteSpace($Sts2Dir)) { throw "Sts2Dir is required." }
$basePck = Join-Path ([IO.Path]::GetFullPath($Sts2Dir)) "SlayTheSpire2.pck"
if (-not [IO.File]::Exists($basePck)) { throw "Base-game PCK does not exist: $basePck" }

$candidateTres = Join-Path $ProjectDir "tools/candidates/semantic_butterfly/semantic_butterfly_skeleton_data.tres"
if (-not [IO.File]::Exists($candidateTres)) { throw "Semantic butterfly candidate has not been built." }
$renderScript = Join-Path $PSScriptRoot "render_semantic_butterfly_exact.gd"

$gameSpineDll = Join-Path $Sts2Dir "libspine_godot.windows.template_release.x86_64.dll"
$extensionManifests = @(Get-ChildItem -LiteralPath (Join-Path $ProjectDir "bin/spine_contract") `
    -Filter 'spine_godot_extension.gdextension' -File -Recurse -Force -ErrorAction SilentlyContinue)
if ($extensionManifests.Count -ne 1) { throw "Expected exactly one prepared local Spine GDExtension." }
$editorSpineDll = Join-Path $extensionManifests[0].DirectoryName "windows/libspine_godot.windows.editor.x86_64.dll"
if ((Get-FileHash $gameSpineDll -Algorithm SHA256).Hash -ne (Get-FileHash $editorSpineDll -Algorithm SHA256).Hash) {
    throw "Prepared Spine GDExtension does not match the game DLL."
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot (".work/semantic-butterfly-vulkan-" + [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss"))
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$workRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot ".work")).TrimEnd('\', '/')
if (-not $OutputDir.StartsWith($workRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must stay below $workRoot."
}
if ([IO.Directory]::Exists($OutputDir) -and @(Get-ChildItem -LiteralPath $OutputDir -Force).Count -gt 0) {
    throw "OutputDir must be new or empty."
}
[void][IO.Directory]::CreateDirectory($OutputDir)

$projectBytes = [Text.Encoding]::UTF8.GetBytes($ProjectDir.ToLowerInvariant())
$sha = [Security.Cryptography.SHA256]::Create()
try { $projectHash = ([BitConverter]::ToString($sha.ComputeHash($projectBytes))).Replace('-', '').Substring(0, 24) }
finally { $sha.Dispose() }
$mutex = New-Object Threading.Mutex($false, "Local\VivhiteIroncladSpine-$projectHash")
$acquired = $false
$previousPck = $env:VIVHITE_STS2_PCK_PATH
$previousDotnetRoot = $env:DOTNET_ROOT
$previousDotnetRootX64 = $env:DOTNET_ROOT_X64
$previousPath = $env:PATH
try {
    try { $acquired = $mutex.WaitOne([TimeSpan]::FromMinutes(10)) }
    catch [Threading.AbandonedMutexException] { $acquired = $true }
    if (-not $acquired) { throw "Timed out waiting for exclusive Spine preview access." }
    $dotnetRoot = "C:\Users\xenoa\AppData\Local\Microsoft\dotnet"
    if ([IO.Directory]::Exists($dotnetRoot)) {
        $env:DOTNET_ROOT = $dotnetRoot
        $env:DOTNET_ROOT_X64 = $dotnetRoot
        if (-not $env:PATH.StartsWith($dotnetRoot + [IO.Path]::PathSeparator, [StringComparison]::OrdinalIgnoreCase)) {
            $env:PATH = $dotnetRoot + [IO.Path]::PathSeparator + $env:PATH
        }
    }
    $env:VIVHITE_STS2_PCK_PATH = $basePck
    $exitCode = Invoke-HiddenGodot -Arguments @(
        '--path', $ProjectDir,
        '--display-driver', 'windows',
        '--rendering-driver', 'vulkan',
        '--resolution', '64x64',
        '--position', '-32000,-32000',
        '--script', $renderScript,
        '--', '--pck', $basePck, '--output', $OutputDir
    ) -LogStem (Join-Path $OutputDir "render")
    if ($exitCode -ne 0) { throw "Semantic butterfly Vulkan probe failed with exit code $exitCode." }
    $summaryPath = Join-Path $OutputDir "summary.json"
    $summary = [IO.File]::ReadAllText($summaryPath) | ConvertFrom-Json
    if ($summary.success -ne $true -or @($summary.samples).Count -ne 16) {
        throw "Semantic butterfly summary did not pass all 16 samples: $summaryPath"
    }
    Write-Host "[semantic-butterfly] Report: $summaryPath" -ForegroundColor Green
    Write-Host "[semantic-butterfly] Contact sheet: $(Join-Path $OutputDir $summary.contact_sheet)" -ForegroundColor Green
}
finally {
    $env:VIVHITE_STS2_PCK_PATH = $previousPck
    $env:DOTNET_ROOT = $previousDotnetRoot
    $env:DOTNET_ROOT_X64 = $previousDotnetRootX64
    $env:PATH = $previousPath
    if ($acquired) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
