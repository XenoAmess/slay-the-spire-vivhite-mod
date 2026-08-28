[CmdletBinding()]
param(
    [string]$GodotExe = "",
    [switch]$SkipRender
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../../../.."))
$projectDir = Join-Path $repoRoot "tools/art"
$workDir = Join-Path $repoRoot ".work/semantic-right-arm"
[void][IO.Directory]::CreateDirectory($workDir)

if ([string]::IsNullOrWhiteSpace($GodotExe)) {
    $localPropsPath = Join-Path $repoRoot "Vivhite/local.props"
    if ([IO.File]::Exists($localPropsPath)) {
        [xml]$localProps = [IO.File]::ReadAllText($localPropsPath)
        $propertyGroup = @($localProps.Project.PropertyGroup) | Select-Object -First 1
        if ($null -ne $propertyGroup) {
            $GodotExe = [string]$propertyGroup.GodotExe
        }
    }
}
if ([string]::IsNullOrWhiteSpace($GodotExe) -or -not [IO.File]::Exists($GodotExe)) {
    throw "Godot 4.5.1 executable is required (pass -GodotExe or configure Vivhite/local.props)."
}
$GodotExe = [IO.Path]::GetFullPath($GodotExe)
$godotName = [IO.Path]::GetFileNameWithoutExtension($GodotExe)
if (-not $godotName.EndsWith("_console", [StringComparison]::OrdinalIgnoreCase)) {
    $consoleCandidate = Join-Path ([IO.Path]::GetDirectoryName($GodotExe)) ($godotName + "_console.exe")
    if ([IO.File]::Exists($consoleCandidate)) {
        $GodotExe = $consoleCandidate
    }
}

function Invoke-HiddenGodotStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $stdout = Join-Path $workDir "$Name.stdout.log"
    $stderr = Join-Path $workDir "$Name.stderr.log"
    $process = Start-Process `
        -FilePath $GodotExe `
        -ArgumentList $Arguments `
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
        throw "$Name ended without an observable exit code."
    }
    if ([int]$process.ExitCode -ne 0) {
        throw "$Name failed with exit code $($process.ExitCode)."
    }
}

Invoke-HiddenGodotStep -Name "build" -Arguments @(
    "--headless",
    "--path", $projectDir,
    "--script", "res://candidates/semantic_right_arm/build_semantic_right_arm_graybox.gd",
    "--", "build-semantic-right-arm-graybox"
)
Invoke-HiddenGodotStep -Name "validate" -Arguments @(
    "--headless",
    "--path", $projectDir,
    "--script", "res://candidates/semantic_right_arm/validate_semantic_right_arm_graybox.gd",
    "--", "validate-semantic-right-arm-graybox"
)
if (-not $SkipRender) {
    Invoke-HiddenGodotStep -Name "render" -Arguments @(
        "--rendering-driver", "vulkan",
        "--path", $projectDir,
        "--script", "res://candidates/semantic_right_arm/render_semantic_right_arm_extremes.gd",
        "--", "render-semantic-right-arm-extremes"
    )
}

Write-Host "Semantic screen-right/near arm graybox completed without touching the game or runtime skin."
