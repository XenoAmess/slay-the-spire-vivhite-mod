[CmdletBinding()]
param(
    [string]$GodotExe = "",
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

if ([string]::IsNullOrWhiteSpace($GodotExe)) {
    $localPropsPath = Join-Path $ProjectDir "local.props"
    if ([IO.File]::Exists($localPropsPath)) {
        [xml]$localProps = [IO.File]::ReadAllText($localPropsPath)
        $group = @($localProps.Project.PropertyGroup) | Select-Object -First 1
        if ($null -ne $group) {
            $GodotExe = [string]$group.GodotExe
        }
    }
}
if ([string]::IsNullOrWhiteSpace($GodotExe) -or -not [IO.File]::Exists($GodotExe)) {
    throw "Godot 4.5.1 Mono executable is unavailable."
}
$consoleExe = $GodotExe
$baseName = [IO.Path]::GetFileNameWithoutExtension($GodotExe)
if (-not $baseName.EndsWith("_console", [StringComparison]::OrdinalIgnoreCase)) {
    $candidate = Join-Path ([IO.Path]::GetDirectoryName($GodotExe)) ($baseName + "_console.exe")
    if ([IO.File]::Exists($candidate)) {
        $consoleExe = $candidate
    }
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot ".work/semantic-torso-skirt-preview"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
[void][IO.Directory]::CreateDirectory($OutputDir)

$validator = Join-Path $PSScriptRoot "validate_semantic_torso_skirt_candidate.gd"
$renderer = Join-Path $PSScriptRoot "render_semantic_torso_skirt_graybox.gd"

function Invoke-HiddenGodot {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogStem
    )

    $stdout = "$LogStem.stdout.log"
    $stderr = "$LogStem.stderr.log"
    $quoted = foreach ($argument in $Arguments) {
        if ($argument -match '[\s"]') {
            '"' + $argument.Replace('"', '\"') + '"'
        }
        else {
            $argument
        }
    }
    $process = Start-Process `
        -FilePath $consoleExe `
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
    if ($null -eq $process.ExitCode) {
        throw "Godot ended without an observable exit code."
    }
    return [int]$process.ExitCode
}

$projectKeyBytes = [Text.Encoding]::UTF8.GetBytes($ProjectDir.ToLowerInvariant())
$projectHashBytes = [Security.Cryptography.SHA256]::Create().ComputeHash($projectKeyBytes)
$projectHash = ([BitConverter]::ToString($projectHashBytes)).Replace('-', '').Substring(0, 16)
$spineMutex = New-Object Threading.Mutex($false, "Local\VivhiteIroncladSpine-$projectHash")
$spineMutexAcquired = $false

try {
    try {
        $spineMutexAcquired = $spineMutex.WaitOne([TimeSpan]::FromMinutes(10))
    }
    catch [Threading.AbandonedMutexException] {
        $spineMutexAcquired = $true
    }
    if (-not $spineMutexAcquired) {
        throw "Timed out waiting for exclusive Godot Spine preview access."
    }

    $validateExit = Invoke-HiddenGodot -Arguments @(
        '--headless', '--path', $ProjectDir, '--script', $validator
    ) -LogStem (Join-Path $OutputDir 'validate')
    if ($validateExit -ne 0) {
        throw "Semantic torso/skirt static gate failed with exit code $validateExit."
    }

    $renderExit = Invoke-HiddenGodot -Arguments @(
        '--path', $ProjectDir,
        '--display-driver', 'windows',
        '--rendering-driver', 'vulkan',
        '--resolution', '64x64',
        '--position', '-32000,-32000',
        '--script', $renderer,
        '--', '--output-root', $OutputDir
    ) -LogStem (Join-Path $OutputDir 'render')
    if ($renderExit -ne 0) {
        throw "Semantic torso/skirt Vulkan graybox failed with exit code $renderExit."
    }

    $summaryPath = Join-Path $OutputDir "summary.json"
    if (-not [IO.File]::Exists($summaryPath)) {
        throw "Graybox renderer produced no summary: $summaryPath"
    }
    $summary = [IO.File]::ReadAllText($summaryPath) | ConvertFrom-Json
    if (@($summary.poses).Count -ne 3) {
        throw "Expected setup and two maximum-twist poses."
    }
    foreach ($pose in @($summary.poses)) {
        if ($pose.actual.touches_canvas -eq $true -or $pose.inspection.touches_canvas -eq $true) {
            throw "Graybox pose touches its canvas: $($pose.name)"
        }
    }

    Write-Host "[semantic-torso-skirt] Static gate + hidden Vulkan graybox passed." -ForegroundColor Green
    Write-Host "[semantic-torso-skirt] Actual-size sheet: $(Join-Path $OutputDir 'contact-sheet-actual-0.28.png')" -ForegroundColor Green
    Write-Host "[semantic-torso-skirt] Inspection sheet: $(Join-Path $OutputDir 'contact-sheet-inspection-0.70.png')" -ForegroundColor Green
}
finally {
    if ($spineMutexAcquired) {
        $spineMutex.ReleaseMutex()
    }
    $spineMutex.Dispose()
}
