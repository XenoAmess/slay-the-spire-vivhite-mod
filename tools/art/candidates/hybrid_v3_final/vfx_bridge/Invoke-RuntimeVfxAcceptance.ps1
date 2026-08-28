[CmdletBinding()]
param(
    [string]$GodotExe,
    [string]$GameDir,
    [string]$DotnetExe,
    [string]$OutputRoot
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$scriptDir = $PSScriptRoot
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $scriptDir '..\..\..\..\..'))
$workRoot = [IO.Path]::GetFullPath((Join-Path $workspaceRoot '.work'))
$vivhiteRoot = Join-Path $workspaceRoot 'Vivhite'
$localPropsPath = Join-Path $vivhiteRoot 'local.props'

if ((-not $GodotExe -or -not $GameDir) -and (Test-Path -LiteralPath $localPropsPath)) {
    [xml]$localProps = Get-Content -LiteralPath $localPropsPath -Raw
    $propertyGroup = @($localProps.Project.PropertyGroup)[0]
    if (-not $GameDir) {
        $GameDir = [string]$propertyGroup.Sts2Dir
    }
    if (-not $GodotExe) {
        $GodotExe = [string]$propertyGroup.GodotExe
    }
}

if (-not $DotnetExe) {
    $localDotnet = 'C:\Users\xenoa\AppData\Local\Microsoft\dotnet\dotnet.exe'
    if ($env:DOTNET_ROOT -and (Test-Path -LiteralPath (Join-Path $env:DOTNET_ROOT 'dotnet.exe'))) {
        $DotnetExe = Join-Path $env:DOTNET_ROOT 'dotnet.exe'
    }
    elseif (Test-Path -LiteralPath $localDotnet) {
        $DotnetExe = $localDotnet
    }
    else {
        $DotnetExe = (Get-Command dotnet -ErrorAction Stop).Source
    }
}

foreach ($required in @(
    @{ Label = 'GodotExe'; Path = $GodotExe },
    @{ Label = 'DotnetExe'; Path = $DotnetExe },
    @{ Label = 'GameDir'; Path = $GameDir }
)) {
    if (-not $required.Path -or -not (Test-Path -LiteralPath $required.Path)) {
        throw "$($required.Label) does not exist: '$($required.Path)'"
    }
}

$sts2DataDir = Join-Path $GameDir 'data_sts2_windows_x86_64'
$sts2Dll = Join-Path $sts2DataDir 'sts2.dll'
$basePck = Join-Path $GameDir 'SlayTheSpire2.pck'
if (-not (Test-Path -LiteralPath $sts2Dll)) {
    throw "Installed sts2.dll is missing: $sts2Dll"
}
if (-not (Test-Path -LiteralPath $basePck)) {
    throw "Installed base PCK is missing: $basePck"
}

if (-not $OutputRoot) {
    $OutputRoot = Join-Path $workRoot 'hybrid-v3-final-runtime-vfx'
}
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$workPrefix = $workRoot.TrimEnd('\') + '\'
if (-not $OutputRoot.StartsWith($workPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputRoot must remain below '$workRoot': '$OutputRoot'"
}

$runId = '{0}-{1}' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), ([Guid]::NewGuid().ToString('N').Substring(0, 8))
$runRoot = Join-Path $OutputRoot $runId
$projectRoot = Join-Path $runRoot 'project'
$evidenceRoot = Join-Path $runRoot 'evidence'
$binRoot = Join-Path $projectRoot '.godot\mono\temp\bin\Debug'
$objRoot = Join-Path $runRoot 'obj'
$candidateSource = Join-Path $vivhiteRoot 'tools\candidates\hybrid_v3_final'
$candidateTarget = Join-Path $projectRoot 'tools\candidates\hybrid_v3_final'

New-Item -ItemType Directory -Force -Path @(
    $projectRoot,
    $evidenceRoot,
    $binRoot,
    $objRoot,
    $candidateTarget,
    (Join-Path $projectRoot 'bin'),
    (Join-Path $projectRoot '.godot')
) | Out-Null

$projectFiles = @(
    'project.godot',
    'VivhiteVfxBridge.csproj',
    'RuntimeVfxHarness.cs',
    'run_runtime_vfx_interruptions.gd'
)
foreach ($name in $projectFiles) {
    $source = Join-Path $scriptDir $name
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Acceptance bridge source is missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $projectRoot $name) -Force
}

$candidateFiles = @(
    'vivhite_combat.png',
    'vivhite_combat_death.png',
    'vivhite_combat_attack.png',
    'vivhite_combat_attack_heavy.png',
    'vivhite_combat_cast.png',
    'vivhite_combat.spjson',
    'vivhite_combat.spatlas',
    'vivhite_combat_skeleton_data.tres'
)
foreach ($name in $candidateFiles) {
    $source = Join-Path $candidateSource $name
    if (-not (Test-Path -LiteralPath $source)) {
        throw "Final candidate file is missing: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $candidateTarget $name) -Force
}

$extensionList = Join-Path $vivhiteRoot '.godot\extension_list.cfg'
$spineContract = Join-Path $vivhiteRoot 'bin\spine_contract'
if (-not (Test-Path -LiteralPath $extensionList)) {
    throw "Spine extension list is missing: $extensionList"
}
if (-not (Test-Path -LiteralPath $spineContract)) {
    throw "Spine contract binaries are missing: $spineContract"
}
Copy-Item -LiteralPath $extensionList -Destination (Join-Path $projectRoot '.godot\extension_list.cfg') -Force
Copy-Item -LiteralPath $spineContract -Destination (Join-Path $projectRoot 'bin\spine_contract') -Recurse

$dotnetRoot = Split-Path -Parent $DotnetExe
$env:DOTNET_ROOT = $dotnetRoot
$env:PATH = "$dotnetRoot;$env:PATH"
$buildArgs = @(
    'build',
    (Join-Path $projectRoot 'VivhiteVfxBridge.csproj'),
    '-c', 'Debug',
    '--nologo',
    "/p:Sts2DataDir=$sts2DataDir",
    "/p:BridgeOutputPath=$binRoot\",
    "/p:BridgeIntermediateOutputPath=$objRoot\"
)
& $DotnetExe @buildArgs 1> (Join-Path $runRoot 'build.stdout.log') 2> (Join-Path $runRoot 'build.stderr.log')
if ($LASTEXITCODE -ne 0) {
    throw "Acceptance bridge build failed; see '$runRoot\build.stderr.log'."
}

$godotRunner = $GodotExe
$consoleCandidate = Join-Path (
    Split-Path -Parent $GodotExe
) ('{0}_console.exe' -f [IO.Path]::GetFileNameWithoutExtension($GodotExe))
if (Test-Path -LiteralPath $consoleCandidate) {
    $godotRunner = $consoleCandidate
}

$importArgs = @(
    '--headless',
    '--editor',
    '--path', $projectRoot,
    '--import',
    '--quit-after', '2'
)
& $godotRunner @importArgs 1> (Join-Path $runRoot 'import.stdout.log') 2> (Join-Path $runRoot 'import.stderr.log')
if ($LASTEXITCODE -ne 0) {
    throw "Candidate import failed; see '$runRoot\import.stderr.log'."
}

$runArgs = @(
    '--path', $projectRoot,
    '--rendering-driver', 'vulkan',
    '--audio-driver', 'Dummy',
    '--script', 'res://run_runtime_vfx_interruptions.gd',
    '--',
    '--pck', $basePck,
    '--sts2-dll', $sts2Dll,
    '--output', $evidenceRoot
)
& $godotRunner @runArgs 1> (Join-Path $runRoot 'run.stdout.log') 2> (Join-Path $runRoot 'run.stderr.log')
$runtimeExitCode = $LASTEXITCODE
$summaryPath = Join-Path $evidenceRoot 'summary.json'
if (-not (Test-Path -LiteralPath $summaryPath)) {
    throw "Runtime VFX bridge produced no summary; exit=$runtimeExitCode, see '$runRoot\run.stderr.log'."
}
$summary = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json

Write-Output "Runtime VFX bridge run: $runRoot"
Write-Output "Summary: $summaryPath"
Write-Output "consumer_executed=$($summary.consumer_executed) matrix_passed=$($summary.matrix_passed) success=$($summary.success)"
if (-not [bool]$summary.success) {
    exit 1
}
if ($runtimeExitCode -ne 0) {
    throw "Godot reported exit $runtimeExitCode despite a successful summary; see '$runRoot\run.stderr.log'."
}
exit 0
