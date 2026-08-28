[CmdletBinding()]
param(
    [string]$GodotExe = "",
    [string]$Sts2Dir = "",
    [string]$OutputDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../../../.."))
$projectDir = Join-Path $repoRoot "Vivhite"
$localPropsPath = Join-Path $projectDir "local.props"
if (([string]::IsNullOrWhiteSpace($GodotExe) -or [string]::IsNullOrWhiteSpace($Sts2Dir)) -and
    [IO.File]::Exists($localPropsPath)) {
    [xml]$props = [IO.File]::ReadAllText($localPropsPath)
    $group = @($props.Project.PropertyGroup) | Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($GodotExe)) { $GodotExe = [string]$group.GodotExe }
    if ([string]::IsNullOrWhiteSpace($Sts2Dir)) { $Sts2Dir = [string]$group.Sts2Dir }
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot ".work/rest-site-acceptance/current"
}

$GodotExe = [IO.Path]::GetFullPath($GodotExe)
$Sts2Dir = [IO.Path]::GetFullPath($Sts2Dir)
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$workRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot ".work")).TrimEnd('\', '/')
if (-not $OutputDir.StartsWith($workRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must stay below '$workRoot': $OutputDir"
}
$pckPath = Join-Path $Sts2Dir "SlayTheSpire2.pck"
foreach ($required in @($GodotExe, $pckPath)) {
    if (-not [IO.File]::Exists($required)) { throw "Required file does not exist: $required" }
}

$godotName = [IO.Path]::GetFileNameWithoutExtension($GodotExe)
if (-not $godotName.EndsWith("_console", [StringComparison]::OrdinalIgnoreCase)) {
    $consoleCandidate = Join-Path ([IO.Path]::GetDirectoryName($GodotExe)) ($godotName + "_console.exe")
    if ([IO.File]::Exists($consoleCandidate)) { $GodotExe = $consoleCandidate }
}

if ([IO.Directory]::Exists($OutputDir)) {
    Remove-Item -LiteralPath $OutputDir -Recurse -Force
}
[void][IO.Directory]::CreateDirectory($OutputDir)
$scriptPath = Join-Path $PSScriptRoot "rest_site_acceptance.gd"

Write-Host "[rest-site-acceptance] Starting isolated Windows Vulkan renderer..."
& $GodotExe `
    --path $projectDir `
    --rendering-driver vulkan `
    --script $scriptPath `
    -- `
    --pck $pckPath `
    --output $OutputDir
if ($LASTEXITCODE -ne 0) {
    throw "Rest-site Vulkan acceptance failed with exit code $LASTEXITCODE."
}

$reportPath = Join-Path $OutputDir "report.json"
if (-not [IO.File]::Exists($reportPath)) { throw "Missing report: $reportPath" }
$report = [IO.File]::ReadAllText($reportPath) | ConvertFrom-Json
if ($report.success -ne $true) { throw "Rest-site report did not pass: $reportPath" }
if ($report.display_server -ne "Windows" -or $report.rendering_driver -ne "vulkan") {
    throw "Rest-site acceptance did not use Windows Vulkan: $reportPath"
}
if ($report.vivhite_render.light_states_distinct -ne $true) {
    throw "Rest-site light_on/light_off were not visually distinct: $reportPath"
}
if ([int]$report.evidence.total_render_frames -ne 73 -or
    [int]$report.evidence.source_over_composites -ne 219 -or
    [int]$report.evidence.contact_sheet_count -ne 11) {
    throw "Rest-site evidence counts are incomplete: $reportPath"
}
$contactSheets = @(Get-ChildItem -LiteralPath (Join-Path $OutputDir "contact-sheets") -Filter "*.png" -File)
if ($contactSheets.Count -ne 11) {
    throw "Expected exactly 11 contact sheets, found $($contactSheets.Count): $reportPath"
}
foreach ($animation in @("overgrowth_loop", "hive_loop", "glory_loop")) {
    if ($report.vivhite_render.loops.$animation.motion.passed -ne $true) {
        throw "Rest-site loop failed: $animation"
    }
    if ($report.vivhite_render.flipped.$animation.motion.passed -ne $true) {
        throw "Rest-site flipped loop failed: $animation"
    }
}

Write-Host "[rest-site-acceptance] PASS: $reportPath" -ForegroundColor Green
