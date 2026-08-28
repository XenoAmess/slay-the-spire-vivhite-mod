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
$artProject = Join-Path $repoRoot "tools/art"
$candidateRoot = Join-Path $projectDir "tools/candidates/semantic_split_v3"
$localPropsPath = Join-Path $projectDir "local.props"

if (([string]::IsNullOrWhiteSpace($GodotExe) -or [string]::IsNullOrWhiteSpace($Sts2Dir)) -and
    [IO.File]::Exists($localPropsPath)) {
    [xml]$localProps = [IO.File]::ReadAllText($localPropsPath)
    $group = @($localProps.Project.PropertyGroup) | Select-Object -First 1
    if ($null -ne $group) {
        if ([string]::IsNullOrWhiteSpace($GodotExe)) { $GodotExe = [string]$group.GodotExe }
        if ([string]::IsNullOrWhiteSpace($Sts2Dir)) { $Sts2Dir = [string]$group.Sts2Dir }
    }
}
if ([string]::IsNullOrWhiteSpace($GodotExe) -or -not [IO.File]::Exists($GodotExe)) {
    throw "Godot 4.5.1 is required."
}
$GodotExe = [IO.Path]::GetFullPath($GodotExe)
$baseName = [IO.Path]::GetFileNameWithoutExtension($GodotExe)
if (-not $baseName.EndsWith("_console", [StringComparison]::OrdinalIgnoreCase)) {
    $consoleCandidate = Join-Path ([IO.Path]::GetDirectoryName($GodotExe)) ($baseName + "_console.exe")
    if ([IO.File]::Exists($consoleCandidate)) { $GodotExe = $consoleCandidate }
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot ".work/combat-rig-compare-preview/semantic-split-v3-ab"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$workRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot ".work")).TrimEnd('\', '/')
if (-not $OutputDir.StartsWith($workRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must remain below $workRoot"
}
[void][IO.Directory]::CreateDirectory($OutputDir)

function Invoke-HeadlessGodot {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogStem
    )
    $stdout = Join-Path $OutputDir ($LogStem + ".stdout.log")
    $stderr = Join-Path $OutputDir ($LogStem + ".stderr.log")
    $allArgs = @('--headless', '--path', $artProject, '--script', $Script, '--') + $Arguments
    $quoted = foreach ($argument in $allArgs) {
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
    if ($process.ExitCode -ne 0) {
        throw "$LogStem failed with exit code $($process.ExitCode)."
    }
}

$builder = Join-Path $PSScriptRoot "build_semantic_split_v3_candidate.gd"
$validator = Join-Path $PSScriptRoot "validate_semantic_split_v3_candidate.gd"
$assembler = Join-Path $PSScriptRoot "assemble_semantic_split_v3_ab.gd"
Invoke-HeadlessGodot -Script $builder -Arguments @('build-semantic-split-v3') -LogStem 'build'
Invoke-HeadlessGodot -Script $validator -Arguments @('validate-semantic-split-v3') -LogStem 'validate'

$compare = Join-Path $repoRoot "tools/art/compare/preview/Invoke-CombatRigComparePreview.ps1"
$legacy = Join-Path $repoRoot "assets/vivhite-ironclad/candidates/split_mesh/combat/vivhite_combat_split_mesh_skeleton_data.tres"
$semantic = Join-Path $candidateRoot "semantic_split_v3_skeleton_data.tres"
& $compare `
    -Candidate @("LegacySplit=$legacy", "SemanticSplitV3=$semantic") `
    -GodotExe $GodotExe `
    -Sts2Dir $Sts2Dir `
    -OutputDir $OutputDir `
    -Samples 21 `
    -SceneScale 0.28 `
    -AuthoredCharacterScale 0.70

Invoke-HeadlessGodot -Script $assembler -Arguments @(
    '--summary', (Join-Path $OutputDir 'summary.json'),
    '--preview-root', $OutputDir,
    '--publish-root', $candidateRoot
) -LogStem 'assemble-ab'

Write-Host "[semantic-split-v3] Static contract and 8-animation Vulkan A/B passed." -ForegroundColor Green
Write-Host "[semantic-split-v3] Overview: $(Join-Path $candidateRoot 'semantic-split-v3-ab-overview.png')" -ForegroundColor Green
Write-Host "[semantic-split-v3] This result is fail-closed and not deployable." -ForegroundColor Yellow
