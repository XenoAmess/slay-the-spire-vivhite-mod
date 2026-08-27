[CmdletBinding()]
param(
    [string]$GodotExe = "",

    [string]$Sts2Dir = "",

    [string]$ProjectDir = "",

    [string]$OutputDir = "",

    [ValidateRange(64, 8192)]
    [int]$Width = 1024,

    [ValidateRange(64, 8192)]
    [int]$Height = 1024,

    [ValidateSet("Strict", "CombatPartial")]
    [string]$RigMode = "Strict",

    [switch]$SkipSourceValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../.."))
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
        if ([string]::IsNullOrWhiteSpace($GodotExe)) {
            $GodotExe = [string]$propertyGroup.GodotExe
        }
        if ([string]::IsNullOrWhiteSpace($Sts2Dir)) {
            $Sts2Dir = [string]$propertyGroup.Sts2Dir
        }
    }
}

if ([string]::IsNullOrWhiteSpace($GodotExe)) {
    throw "GodotExe is required (pass -GodotExe or configure Vivhite/local.props)."
}
if ([string]::IsNullOrWhiteSpace($Sts2Dir)) {
    throw "Sts2Dir is required (pass -Sts2Dir or configure Vivhite/local.props)."
}
$GodotExe = [IO.Path]::GetFullPath($GodotExe)
$Sts2Dir = [IO.Path]::GetFullPath($Sts2Dir)
if (-not [IO.File]::Exists($GodotExe)) {
    throw "Godot executable does not exist: $GodotExe"
}

$godotName = [IO.Path]::GetFileNameWithoutExtension($GodotExe)
if (-not $godotName.EndsWith("_console", [StringComparison]::OrdinalIgnoreCase)) {
    $consoleCandidate = Join-Path ([IO.Path]::GetDirectoryName($GodotExe)) ($godotName + "_console.exe")
    if ([IO.File]::Exists($consoleCandidate)) {
        $GodotExe = $consoleCandidate
    }
}

$basePckPath = Join-Path $Sts2Dir "SlayTheSpire2.pck"
if (-not [IO.File]::Exists($basePckPath)) {
    throw "Base-game PCK does not exist: $basePckPath"
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot ".work/ironclad-render-acceptance"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$workRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot ".work")).TrimEnd('\', '/')
$workPrefix = $workRoot + [IO.Path]::DirectorySeparatorChar
if (-not $OutputDir.StartsWith($workPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must stay below '$workRoot', got '$OutputDir'."
}

$validator = Join-Path $ProjectDir "tools/Validate-IroncladSkin.ps1"
$runSourceValidation = -not $SkipSourceValidation -and $RigMode -eq "Strict"
if ($RigMode -eq "CombatPartial" -and -not $SkipSourceValidation) {
    Write-Warning (
        "CombatPartial mode skips the complete Source contract because rest/select may still be " +
        "legacy assets. This run cannot count as full acceptance."
    )
}
if ($runSourceValidation) {
    if (-not [IO.File]::Exists($validator)) {
        throw "Ironclad source validator does not exist: $validator"
    }
    Write-Host "[ironclad-render-acceptance] Preparing and validating the local Spine editor extension..."
    & $validator -Phase Source -ProjectDir $ProjectDir -GodotExe $GodotExe -Sts2Dir $Sts2Dir
    if ($LASTEXITCODE -ne 0) {
        throw "Ironclad source validation failed with exit code $LASTEXITCODE."
    }
}

$scriptPath = Join-Path $PSScriptRoot "render_ironclad_skin_acceptance.gd"
if (-not [IO.File]::Exists($scriptPath)) {
    throw "Batch render script does not exist: $scriptPath"
}
[void][IO.Directory]::CreateDirectory($OutputDir)
$reportPath = Join-Path $OutputDir "report.json"
foreach ($stalePath in @(
        $reportPath,
        (Join-Path $OutputDir "frames"),
        (Join-Path $OutputDir "analysis")
    )) {
    if ([IO.File]::Exists($stalePath)) {
        Remove-Item -LiteralPath $stalePath -Force
    }
    elseif ([IO.Directory]::Exists($stalePath)) {
        Remove-Item -LiteralPath $stalePath -Recurse -Force
    }
}

$previousBasePckPath = $env:VIVHITE_STS2_PCK_PATH
$rigModeArgument = if ($RigMode -eq "Strict") { "strict" } else { "combat_partial" }
try {
    $env:VIVHITE_STS2_PCK_PATH = $basePckPath
    Write-Host "[ironclad-render-acceptance] Starting one isolated Vulkan Godot render process..."
    & $GodotExe `
        --path $ProjectDir `
        --rendering-driver vulkan `
        --script $scriptPath `
        -- `
        --pck $basePckPath `
        --output $OutputDir `
        --rig-mode $rigModeArgument `
        --width $Width `
        --height $Height
    $renderExitCode = $LASTEXITCODE
}
finally {
    $env:VIVHITE_STS2_PCK_PATH = $previousBasePckPath
}

if ($renderExitCode -ne 0) {
    throw "Vulkan batch render failed with exit code $renderExitCode."
}

if (-not [IO.File]::Exists($reportPath)) {
    throw "Vulkan batch render exited successfully but did not create '$reportPath'."
}

try {
    $report = [IO.File]::ReadAllText($reportPath) | ConvertFrom-Json
}
catch {
    throw "Vulkan batch render created an invalid JSON report '$reportPath': $($_.Exception.Message)"
}

$reportProperties = @($report.PSObject.Properties.Name)
if (-not ($reportProperties -contains "success") -or $report.success -ne $true) {
    throw "Vulkan batch report did not declare success=true: $reportPath"
}
if (-not ($reportProperties -contains "animation_count") -or [int]$report.animation_count -ne 15) {
    throw "Vulkan batch report must declare exactly 15 animations: $reportPath"
}
if (-not ($reportProperties -contains "sets")) {
    throw "Vulkan batch report has no sets array: $reportPath"
}
if (-not ($reportProperties -contains "rig_summary")) {
    throw "Vulkan batch report has no rig migration summary: $reportPath"
}
$privateRigSets = @($report.rig_summary.private_spjson_sets)
$legacyRigSets = @($report.rig_summary.legacy_sets)
if ($privateRigSets -notcontains "combat") {
    throw "Vulkan batch report did not render combat from the private .spjson rig: $reportPath"
}
if ($legacyRigSets.Count -gt 0) {
    Write-Warning (
        "Rig migration is intentionally incomplete; these sets still load vanilla .skel resources: " +
        ($legacyRigSets -join ", ")
    )
}
if ($RigMode -eq "Strict" -and $legacyRigSets.Count -gt 0) {
    throw "Strict acceptance cannot pass while legacy rigs remain: $reportPath"
}
if ($RigMode -eq "CombatPartial" -and $report.acceptance_scope -ne "combat_only") {
    throw "CombatPartial renderer report has the wrong acceptance scope: $reportPath"
}

$animations = @()
foreach ($set in @($report.sets)) {
    if (-not (@($set.PSObject.Properties.Name) -contains "animations")) {
        throw "Vulkan batch report contains a set without an animations array: $reportPath"
    }
    $animations += @($set.animations)
}
if ($animations.Count -ne 15) {
    throw "Vulkan batch report contains $($animations.Count) animations; expected 15: $reportPath"
}

$frameCount = 0
foreach ($animation in $animations) {
    if (-not (@($animation.PSObject.Properties.Name) -contains "frames")) {
        throw "Vulkan batch report contains an animation without a frames array: $reportPath"
    }
    $animationFrames = @($animation.frames)
    if ($animationFrames.Count -ne 5) {
        $animationName = [string]$animation.name
        throw "Vulkan batch report animation '$animationName' contains $($animationFrames.Count) frames; expected 5: $reportPath"
    }
    $frameCount += $animationFrames.Count
}
if ($frameCount -ne 75) {
    throw "Vulkan batch report contains $frameCount frames; expected 75: $reportPath"
}

$analyzerScript = Join-Path $PSScriptRoot "analyze_ironclad_render_output.gd"
if (-not [IO.File]::Exists($analyzerScript)) {
    throw "Render analyzer does not exist: $analyzerScript"
}
$analysisDir = Join-Path $OutputDir "analysis"
Write-Host "[ironclad-render-acceptance] Analyzing PNGs and producing contact sheets..."
& $GodotExe `
    --headless `
    --path $PSScriptRoot `
    --script $analyzerScript `
    -- `
    --input $OutputDir `
    --output $analysisDir `
    --expected-frames 5
$analysisExitCode = $LASTEXITCODE
if ($analysisExitCode -ne 0) {
    throw "Render analysis failed with exit code $analysisExitCode. See '$analysisDir'."
}

$analysisReportPath = Join-Path $analysisDir "summary.json"
if (-not [IO.File]::Exists($analysisReportPath)) {
    throw "Render analyzer exited successfully but did not create '$analysisReportPath'."
}
$analysisReport = [IO.File]::ReadAllText($analysisReportPath) | ConvertFrom-Json
if ($analysisReport.passed -ne $true) {
    throw "Render analysis did not pass: $analysisReportPath"
}
if ($RigMode -eq "Strict" -and $analysisReport.full_acceptance_passed -ne $true) {
    throw "Strict full render acceptance did not pass: $analysisReportPath"
}
$analysisSummary = $analysisReport.summary
if ([int]$analysisSummary.animation_count -ne 15 -or [int]$analysisSummary.frame_count -ne 75) {
    throw "Render analysis has incomplete coverage; expected 15 animations and 75 frames: $analysisReportPath"
}
$contactSheets = @(Get-ChildItem -LiteralPath (Join-Path $analysisDir "contact-sheets") -Filter "*.png" -File)
if ($contactSheets.Count -ne 15) {
    throw "Render analysis created $($contactSheets.Count) contact sheets; expected 15: $analysisReportPath"
}

Write-Host "[ironclad-render-acceptance] Batch report: $reportPath" -ForegroundColor Green
Write-Host "[ironclad-render-acceptance] Analysis report: $analysisReportPath" -ForegroundColor Green
if ($RigMode -eq "CombatPartial") {
    Write-Warning "COMBAT-ONLY RENDER CHECK PASSED. Full four-set acceptance remains NOT PASSED."
}
