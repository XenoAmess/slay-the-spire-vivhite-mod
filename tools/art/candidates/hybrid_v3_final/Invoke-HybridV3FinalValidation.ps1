[CmdletBinding()]
param(
    [string]$GodotExe = "",
    [string]$Sts2Dir = "",
    [string]$ProjectDir = "",
    [string]$PythonExe = "",
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

$runtimeLayout = "v3-five-page"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../../../.."))
$authoringProject = Join-Path $repoRoot "tools/art"
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

function Resolve-PythonCommand {
    param([string]$RequestedPath)

    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        if ([IO.Path]::IsPathRooted($RequestedPath)) {
            $resolved = [IO.Path]::GetFullPath($RequestedPath)
            if (-not [IO.File]::Exists($resolved)) { throw "Python executable does not exist: $resolved" }
        }
        else {
            $command = Get-Command $RequestedPath -ErrorAction SilentlyContinue
            if ($null -eq $command) { throw "Python command does not exist: $RequestedPath" }
            $resolved = $command.Source
        }
    }
    else {
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($null -ne $launcher) {
            return [pscustomobject]@{ Path = $launcher.Source; Prefix = @("-3") }
        }
        $command = Get-Command python.exe -ErrorAction SilentlyContinue
        if ($null -eq $command) { throw "Python 3 is required to run publish_ironclad_skin.py." }
        $resolved = $command.Source
    }

    $prefix = @()
    if ([string]::Equals(
            [IO.Path]::GetFileNameWithoutExtension($resolved),
            "py",
            [StringComparison]::OrdinalIgnoreCase)) {
        $prefix = @("-3")
    }
    return [pscustomobject]@{ Path = $resolved; Prefix = $prefix }
}

function Invoke-HiddenGodot {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogStem
    )

    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($LogStem))
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
        if (-not [IO.File]::Exists($path)) { continue }
        foreach ($line in [IO.File]::ReadAllLines($path)) {
            if (-not [string]::IsNullOrWhiteSpace($line)) { Write-Host $line }
        }
    }
    if ($null -eq $process.ExitCode) {
        throw "Godot ended without an observable exit code. See '$stdout' and '$stderr'."
    }
    return [int]$process.ExitCode
}

function Invoke-HiddenPowerShellScript {
    param(
        [Parameter(Mandatory = $true)][string]$ScriptPath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$LogStem
    )

    $hostPath = (Get-Process -Id $PID).Path
    if (-not [IO.File]::Exists($hostPath)) { throw "Could not resolve the current PowerShell host." }
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($LogStem))
    $stdout = "$LogStem.stdout.log"
    $stderr = "$LogStem.stderr.log"
    $allArguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ScriptPath) + $Arguments
    $quoted = foreach ($argument in $allArguments) {
        if ($argument -match '[\s"]') { '"' + $argument.Replace('"', '\"') + '"' } else { $argument }
    }
    $process = Start-Process -FilePath $hostPath -ArgumentList ($quoted -join ' ') `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr `
        -Wait -PassThru
    $process.Refresh()
    foreach ($path in @($stdout, $stderr)) {
        if (-not [IO.File]::Exists($path)) { continue }
        foreach ($line in [IO.File]::ReadAllLines($path)) {
            if (-not [string]::IsNullOrWhiteSpace($line)) { Write-Host $line }
        }
    }
    if ($null -eq $process.ExitCode) {
        throw "PowerShell validator ended without an observable exit code. See '$stdout' and '$stderr'."
    }
    return [int]$process.ExitCode
}

function Copy-DirectoryContents {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not [IO.Directory]::Exists($Source)) { throw "Source directory does not exist: $Source" }
    [void][IO.Directory]::CreateDirectory($Destination)
    foreach ($item in Get-ChildItem -LiteralPath $Source -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $Destination -Recurse -Force
    }
}

function Copy-RequiredFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not [IO.File]::Exists($Source)) { throw "Required source file does not exist: $Source" }
    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Destination))
    [IO.File]::Copy($Source, $Destination, $true)
}

function Replace-RequiredText {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$OldText,
        [Parameter(Mandatory = $true)][string]$NewText
    )

    $text = [IO.File]::ReadAllText($Path)
    if ($text.IndexOf($OldText, [StringComparison]::Ordinal) -lt 0) {
        throw "Staged candidate wrapper no longer contains the expected resource root '$OldText': $Path"
    }
    $rewritten = $text.Replace($OldText, $NewText)
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $rewritten, $utf8NoBom)
}

function Get-RelativeChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
    $pathFull = [IO.Path]::GetFullPath($Path)
    $prefix = $rootFull + [IO.Path]::DirectorySeparatorChar
    if (-not $pathFull.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Path '$pathFull' is not below '$rootFull'."
    }
    return $pathFull.Substring($prefix.Length).Replace('\', '/')
}

function Get-TreeSnapshot {
    param([Parameter(Mandatory = $true)][string]$Root)

    if (-not [IO.Directory]::Exists($Root)) { throw "Snapshot root does not exist: $Root" }
    return @(
        Get-ChildItem -LiteralPath $Root -File -Recurse -Force |
            ForEach-Object {
                $relative = Get-RelativeChildPath -Root $Root -Path $_.FullName
                "$relative|$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash)"
            } |
            Sort-Object
    )
}

function Assert-ExactRenderReport {
    param(
        [Parameter(Mandatory = $true)][string]$SummaryPath,
        [Parameter(Mandatory = $true)][string]$Animation
    )

    if (-not [IO.File]::Exists($SummaryPath)) {
        throw "Exact renderer did not write summary.json for '$Animation': $SummaryPath"
    }
    $summary = [IO.File]::ReadAllText($SummaryPath) | ConvertFrom-Json
    foreach ($property in @(
            "success",
            "frame_count_passed",
            "single_character_contract_passed",
            "attachment_contract_passed",
            "bbox_contract_passed",
            "character_only_contract_passed",
            "mix_contract_passed",
            "vfx_suppression_contract_passed"
        )) {
        if (@($summary.PSObject.Properties.Name) -notcontains $property -or $summary.$property -ne $true) {
            throw "Exact renderer report for '$Animation' did not pass '$property': $SummaryPath"
        }
    }
    $frames = @($summary.frames)
    $requestedTimes = @($summary.requested_times)
    if ($frames.Count -lt 1 -or $frames.Count -ne $requestedTimes.Count) {
        throw "Exact renderer returned $($frames.Count) frames for $($requestedTimes.Count) requested times in '$Animation': $SummaryPath"
    }
    foreach ($frame in $frames) {
        if ($frame.passed -ne $true -or [int]$frame.visible_character_attachment_count -ne 1 -or
            $frame.attachment_contract_passed -ne $true -or $frame.character_only.passed -ne $true -or
            $frame.character_only.touches_canvas_edge -ne $false) {
            throw "Exact renderer frame contract failed for '$Animation': $SummaryPath"
        }
    }
}

function Assert-TransitionReport {
    param([Parameter(Mandatory = $true)][string]$SummaryPath)

    if (-not [IO.File]::Exists($SummaryPath)) {
        throw "Transition renderer did not write transition_summary.json: $SummaryPath"
    }
    $summary = [IO.File]::ReadAllText($SummaryPath) | ConvertFrom-Json
    if ($summary.pass -ne $true -or $summary.success -ne $true -or
        [int]$summary.sequence_count -ne 25 -or [int]$summary.sample_count -ne 104 -or
        @($summary.sequences).Count -ne 25 -or $summary.coverage.passed -ne $true) {
        throw "Transition/VFX report did not pass its aggregate contract: $SummaryPath"
    }
    if ($null -eq $summary.consumer_fidelity) {
        throw "Transition/VFX report omitted consumer_fidelity: $SummaryPath"
    }
    $fidelity = $summary.consumer_fidelity
    $fidelityCount = [int]$fidelity.actual_nironclad_sequence_count + [int]$fidelity.simulation_sequence_count
    $fidelityProbe = $fidelity.first_sequence_probe
    if ($fidelityCount -ne 25 -or [string]::IsNullOrWhiteSpace([string]$fidelity.decompiled_contract_sha256) -or
        $fidelityProbe.formal_scene_exists_after_pck_mount -ne $true -or
        $fidelityProbe.formal_scene_loaded -ne $true) {
        throw "Transition/VFX report did not prove all 25 consumer-contract sequences: $SummaryPath"
    }
    if ([int]$fidelity.simulation_sequence_count -gt 0 -and
        $fidelity.simulation_is_not_claimed_as_real_csharp -ne $true) {
        throw "Transition/VFX fallback simulation was not labeled accurately: $SummaryPath"
    }
    foreach ($sequence in @($summary.sequences)) {
        $names = @($sequence.PSObject.Properties.Name)
        if ($names -contains "passed") {
            if ($sequence.passed -ne $true) {
                throw "Transition/VFX sequence '$($sequence.name)' did not pass: $SummaryPath"
            }
        }
        elseif ($names -contains "pass") {
            if ($sequence.pass -ne $true) {
                throw "Transition/VFX sequence '$($sequence.name)' did not pass: $SummaryPath"
            }
        }
        else {
            throw "Transition/VFX sequence '$($sequence.name)' did not pass: $SummaryPath"
        }
    }
}

function Assert-MerchantReport {
    param([Parameter(Mandatory = $true)][string]$SummaryPath)

    if (-not [IO.File]::Exists($SummaryPath)) {
        throw "Merchant renderer did not write merchant_summary.json: $SummaryPath"
    }
    $summary = [IO.File]::ReadAllText($SummaryPath) | ConvertFrom-Json
    foreach ($property in @(
            "success",
            "frame_count_passed",
            "frames_passed",
            "real_scene_layout_passed"
        )) {
        if (@($summary.PSObject.Properties.Name) -notcontains $property -or $summary.$property -ne $true) {
            throw "Merchant renderer report did not pass '$property': $SummaryPath"
        }
    }
    $frames = @($summary.frames)
    if ($frames.Count -ne 10) {
        throw "Merchant renderer returned $($frames.Count) frames; expected exactly 10: $SummaryPath"
    }
    foreach ($frame in $frames) {
        if ($frame.passed -ne $true -or $frame.body_only_contract_passed -ne $true -or
            $frame.single_character_contract_passed -ne $true -or $frame.size_contract_passed -ne $true -or
            [int]$frame.visible_character_attachment_count -ne 1 -or
            [int]$frame.visible_total_attachment_count -ne 1 -or
            $frame.alpha.touches_canvas_edge -ne $false) {
            throw "Merchant renderer frame contract failed: $SummaryPath"
        }
    }
    $consumerStatus = [string]$summary.consumer_fidelity.status
    if ($consumerStatus -notin @("production_csharp_bound", "production_layout_csharp_unbound")) {
        throw "Merchant renderer reported an unknown consumer fidelity '$consumerStatus': $SummaryPath"
    }
}

function Assert-RuntimeVfxReport {
    param([Parameter(Mandatory = $true)][string]$SummaryPath)

    if (-not [IO.File]::Exists($SummaryPath)) {
        throw "Runtime VFX bridge did not write summary.json: $SummaryPath"
    }
    $summary = [IO.File]::ReadAllText($SummaryPath) | ConvertFrom-Json
    if ($summary.success -ne $true -or $summary.consumer_executed -ne $true -or
        $summary.matrix_passed -ne $true) {
        throw "Runtime VFX bridge did not execute and pass the real C# consumer matrix: $SummaryPath"
    }
    $scenarios = @($summary.scenarios)
    if ($scenarios.Count -ne 8) {
        throw "Runtime VFX bridge returned $($scenarios.Count) scenarios; expected exactly 8: $SummaryPath"
    }
    foreach ($scenario in $scenarios) {
        if ($scenario.passed -ne $true -or
            $scenario.source_active_contract_passed -ne $true -or
            $scenario.signal_contract_passed -ne $true -or
            $scenario.destination_t0_isolated -ne $true -or
            $scenario.destination_settled_isolated -ne $true -or
            $scenario.destination_lifecycle_passed -ne $true) {
            throw "Runtime VFX bridge scenario '$($scenario.name)' failed its consumer contract: $SummaryPath"
        }
    }
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
if (-not [IO.File]::Exists((Join-Path $ProjectDir "project.godot"))) {
    throw "Vivhite Godot project does not exist: $ProjectDir"
}
$python = Resolve-PythonCommand -RequestedPath $PythonExe

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss-fffffff")
    $OutputDir = Join-Path $repoRoot ".work/hybrid-v3-final/$stamp"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$workRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot ".work")).TrimEnd('\', '/')
$workPrefix = $workRoot + [IO.Path]::DirectorySeparatorChar
if (-not $OutputDir.StartsWith($workPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must stay below '$workRoot', got '$OutputDir'."
}
if ([IO.Directory]::Exists($OutputDir) -and @(Get-ChildItem -LiteralPath $OutputDir -Force).Count -gt 0) {
    throw "OutputDir must be new or empty so previous evidence is never overwritten: $OutputDir"
}

$builder = Join-Path $PSScriptRoot "build_hybrid_v3_final_candidate.gd"
$candidateValidator = Join-Path $PSScriptRoot "validate_hybrid_v3_final_candidate.gd"
$exactRenderer = Join-Path $PSScriptRoot "render_hybrid_v3_final_exact.gd"
$transitionRenderer = Join-Path $PSScriptRoot "render_hybrid_v3_final_transitions.gd"
$merchantRenderer = Join-Path $PSScriptRoot "render_hybrid_v3_final_merchant.gd"
$vfxBridgeRoot = Join-Path $PSScriptRoot "vfx_bridge"
$vfxBridge = Join-Path $vfxBridgeRoot "Invoke-RuntimeVfxAcceptance.ps1"
$renderBase = Join-Path $repoRoot "tools/art/compare/preview/render_combat_rig_compare.gd"
$decompiledConsumer = Join-Path $repoRoot ".work/sts2-decompiled-v0.111.0/MegaCrit/sts2/Core/Nodes/Vfx/NIroncladVfx.cs"
$publisher = Join-Path $repoRoot "tools/art/publish_ironclad_skin.py"
$sourceValidator = Join-Path $ProjectDir "tools/Validate-IroncladSkin.ps1"
$contract = Join-Path $ProjectDir "tools/ironclad-skin.contract.json"
$spineValidator = Join-Path $ProjectDir "tools/Validate-IroncladSpine.gd"
$spineTemplate = Join-Path $ProjectDir "tools/spine_godot_extension.gdextension.template"
$formalRuntime = Join-Path $ProjectDir "Vivhite/skins/ironclad"
$candidateRoot = Join-Path $ProjectDir "tools/candidates/hybrid_v3_final"
$requiredDependencies = @(
    $builder,
    $candidateValidator,
    $exactRenderer,
    $transitionRenderer,
    $merchantRenderer,
    $vfxBridge,
    (Join-Path $vfxBridgeRoot "project.godot"),
    (Join-Path $vfxBridgeRoot "VivhiteVfxBridge.csproj"),
    (Join-Path $vfxBridgeRoot "RuntimeVfxHarness.cs"),
    (Join-Path $vfxBridgeRoot "run_runtime_vfx_interruptions.gd"),
    $renderBase,
    $decompiledConsumer,
    $publisher,
    $sourceValidator,
    $contract,
    $spineValidator,
    $spineTemplate,
    (Join-Path $authoringProject "project.godot"),
    (Join-Path $ProjectDir "project.godot")
)
$missingDependencies = @($requiredDependencies | Where-Object { -not [IO.File]::Exists($_) })
if ($missingDependencies.Count -gt 0) {
    throw "Hybrid V3 final validation dependencies are not ready:`n  - $($missingDependencies -join "`n  - ")"
}
if (-not [IO.Directory]::Exists($formalRuntime)) { throw "Formal runtime root does not exist: $formalRuntime" }
[void][IO.Directory]::CreateDirectory($OutputDir)

$gameSpineDll = Join-Path $Sts2Dir "libspine_godot.windows.template_release.x86_64.dll"
$extensionManifests = @(Get-ChildItem -LiteralPath (Join-Path $ProjectDir "bin/spine_contract") `
        -Filter "spine_godot_extension.gdextension" -File -Recurse -Force -ErrorAction SilentlyContinue)
if ($extensionManifests.Count -ne 1) {
    throw "Expected exactly one prepared local Spine GDExtension for candidate import/validation; found $($extensionManifests.Count)."
}
$editorSpineDll = Join-Path $extensionManifests[0].DirectoryName "windows/libspine_godot.windows.editor.x86_64.dll"
if (-not [IO.File]::Exists($gameSpineDll) -or -not [IO.File]::Exists($editorSpineDll)) {
    throw "The game-matching local Spine GDExtension is incomplete."
}
if (-not [string]::Equals(
        (Get-FileHash -LiteralPath $gameSpineDll -Algorithm SHA256).Hash,
        (Get-FileHash -LiteralPath $editorSpineDll -Algorithm SHA256).Hash,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw "Prepared Spine GDExtension does not match the game DLL."
}

$authoredFiles = @(
    "vivhite_combat.spjson",
    "vivhite_combat.spatlas",
    "vivhite_combat_skeleton_data.tres",
    "vivhite_combat.png",
    "vivhite_combat_death.png",
    "vivhite_combat_attack.png",
    "vivhite_combat_attack_heavy.png",
    "vivhite_combat_cast.png"
)
$animations = @(
    "idle_loop",
    "low_health_loop",
    "relaxed_loop",
    "attack",
    "attack_heavy",
    "cast",
    "hurt",
    "die"
)

$formalBefore = Get-TreeSnapshot -Root $formalRuntime
$stageSeed = Join-Path $OutputDir "private-runtime-input"
$stageProject = Join-Path $OutputDir "project"
$stageRuntime = Join-Path $stageProject "Vivhite/skins/ironclad"
$stageTools = Join-Path $stageProject "tools"
$stageCandidate = Join-Path $stageTools "candidates/hybrid_v3_final"
# The inherited exact-render base intentionally resolves its repository root
# as the parent of the active Godot project. Keep these captures below that
# synthetic root's own .work directory when running from the staged project.
$exactRoot = Join-Path $OutputDir ".work/exact"
$transitionRoot = Join-Path $stageProject ".work/transitions"
$merchantRoot = Join-Path $OutputDir "merchant"
$runtimeVfxRoot = Join-Path $OutputDir "runtime-vfx"
[void][IO.Directory]::CreateDirectory($stageSeed)
[void][IO.Directory]::CreateDirectory($stageProject)
[void][IO.Directory]::CreateDirectory($stageTools)
[void][IO.Directory]::CreateDirectory($stageCandidate)
[void][IO.Directory]::CreateDirectory($exactRoot)
[void][IO.Directory]::CreateDirectory($transitionRoot)
[void][IO.Directory]::CreateDirectory($merchantRoot)

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
$previousRuntimeLayout = $env:VIVHITE_IRONCLAD_RUNTIME_LAYOUT
try {
    $dotnetRoot = $env:DOTNET_ROOT
    if ([string]::IsNullOrWhiteSpace($dotnetRoot)) {
        $knownDotnet = "C:\Users\xenoa\AppData\Local\Microsoft\dotnet"
        if ([IO.Directory]::Exists($knownDotnet)) { $dotnetRoot = $knownDotnet }
    }
    if (-not [string]::IsNullOrWhiteSpace($dotnetRoot)) {
        $env:DOTNET_ROOT = $dotnetRoot
        $env:DOTNET_ROOT_X64 = $dotnetRoot
        $dotnetPrefix = $dotnetRoot.TrimEnd('\', '/') + [IO.Path]::PathSeparator
        if (-not $env:PATH.StartsWith($dotnetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            $env:PATH = $dotnetPrefix + $env:PATH
        }
    }
    $env:STS2_SKIP_PCK_EXPORT = "1"
    $env:VIVHITE_STS2_PCK_PATH = $basePck
    $env:VIVHITE_IRONCLAD_RUNTIME_LAYOUT = $runtimeLayout

    try { $spineMutexAcquired = $spineMutex.WaitOne([TimeSpan]::FromMinutes(10)) }
    catch [Threading.AbandonedMutexException] { $spineMutexAcquired = $true }
    if (-not $spineMutexAcquired) { throw "Timed out waiting for exclusive Godot Spine candidate access." }

    Write-Host "[hybrid-v3-final] Assembling the isolated five-page candidate..."
    if ((Invoke-HiddenGodot -Arguments @(
                '--headless', '--path', $authoringProject, '--script', $builder, '--',
                'assemble-hybrid-v3-final'
            ) -LogStem (Join-Path $OutputDir "candidate-build")) -ne 0) {
        throw "Hybrid V3 final candidate build failed."
    }
    foreach ($fileName in $authoredFiles) {
        if (-not [IO.File]::Exists((Join-Path $candidateRoot $fileName))) {
            throw "Candidate builder omitted required authored file: $fileName"
        }
    }

    Write-Host "[hybrid-v3-final] Importing candidate resources in the Vivhite authoring project..."
    if ((Invoke-HiddenGodot -Arguments @('--headless', '--path', $ProjectDir, '--import') `
            -LogStem (Join-Path $OutputDir "candidate-import")) -ne 0) {
        throw "Hybrid V3 final candidate import failed."
    }
    Write-Host "[hybrid-v3-final] Running the candidate-specific merge/layout validator..."
    if ((Invoke-HiddenGodot -Arguments @(
                '--headless', '--path', $ProjectDir, '--script', $candidateValidator
            ) -LogStem (Join-Path $OutputDir "candidate-validate")) -ne 0) {
        throw "Hybrid V3 final candidate validation failed."
    }

    [void]$spineMutex.ReleaseMutex()
    $spineMutexAcquired = $false

    Write-Host "[hybrid-v3-final] Exercising the candidate through the real C# NIroncladVfx consumer..."
    $runtimeVfxArguments = @(
        '-GodotExe', $GodotExe,
        '-GameDir', $Sts2Dir,
        '-OutputRoot', $runtimeVfxRoot
    )
    if ((Invoke-HiddenPowerShellScript -ScriptPath $vfxBridge `
            -Arguments $runtimeVfxArguments `
            -LogStem (Join-Path $OutputDir "logs/runtime-vfx")) -ne 0) {
        throw "Runtime VFX consumer bridge failed."
    }
    $runtimeVfxSummaries = @(
        Get-ChildItem -LiteralPath $runtimeVfxRoot -Filter "summary.json" -File -Recurse -Force
    )
    if ($runtimeVfxSummaries.Count -ne 1) {
        throw "Runtime VFX bridge produced $($runtimeVfxSummaries.Count) summary files; expected exactly one below '$runtimeVfxRoot'."
    }
    $runtimeVfxSummary = $runtimeVfxSummaries[0].FullName
    Assert-RuntimeVfxReport -SummaryPath $runtimeVfxSummary

    Write-Host "[hybrid-v3-final] Preparing an isolated runtime input from the frozen formal baseline..."
    Copy-DirectoryContents -Source $formalRuntime -Destination $stageSeed
    $seedCombat = Join-Path $stageSeed "spine/combat"
    foreach ($fileName in $authoredFiles) {
        Copy-RequiredFile -Source (Join-Path $candidateRoot $fileName) -Destination (Join-Path $seedCombat $fileName)
    }
    $candidateResourceRoot = "res://tools/candidates/hybrid_v3_final"
    $formalCombatResourceRoot = "res://Vivhite/skins/ironclad/spine/combat"
    Replace-RequiredText -Path (Join-Path $seedCombat "vivhite_combat.spatlas") `
        -OldText $candidateResourceRoot -NewText $formalCombatResourceRoot
    Replace-RequiredText -Path (Join-Path $seedCombat "vivhite_combat_skeleton_data.tres") `
        -OldText $candidateResourceRoot -NewText $formalCombatResourceRoot

    Copy-RequiredFile -Source (Join-Path $ProjectDir "project.godot") `
        -Destination (Join-Path $stageProject "project.godot")
    Copy-RequiredFile -Source $contract -Destination (Join-Path $stageTools "ironclad-skin.contract.json")
    Copy-RequiredFile -Source $spineValidator -Destination (Join-Path $stageTools "Validate-IroncladSpine.gd")
    foreach ($fileName in $authoredFiles) {
        Copy-RequiredFile -Source (Join-Path $candidateRoot $fileName) -Destination (Join-Path $stageCandidate $fileName)
    }
    foreach ($toolPath in @($candidateValidator, $exactRenderer, $transitionRenderer, $merchantRenderer)) {
        Copy-RequiredFile -Source $toolPath -Destination (Join-Path $stageCandidate ([IO.Path]::GetFileName($toolPath)))
    }
    Copy-RequiredFile -Source $renderBase `
        -Destination (Join-Path $stageProject "tools/compare/preview/render_combat_rig_compare.gd")
    Copy-RequiredFile -Source $decompiledConsumer `
        -Destination (Join-Path $stageProject ".work/sts2-decompiled-v0.111.0/MegaCrit/sts2/Core/Nodes/Vfx/NIroncladVfx.cs")

    Write-Host "[hybrid-v3-final] Publishing the strict 30-file V3 runtime only into the temporary project..."
    $publisherArguments = @($python.Prefix) + @(
        '-B', $publisher,
        '--template-root', (Join-Path $repoRoot "assets/ironclad-v0.111.0"),
        '--art-root', (Join-Path $repoRoot "assets/vivhite-ironclad/custom"),
        '--approved-root', (Join-Path $repoRoot "assets/vivhite-ironclad/approved"),
        '--private-runtime-root', $stageSeed,
        '--runtime-layout', $runtimeLayout,
        '--destination', $stageRuntime
    )
    & $python.Path @publisherArguments
    if ($LASTEXITCODE -ne 0) {
        throw "V3 publisher failed with exit code $LASTEXITCODE."
    }
    $publishedFiles = @(Get-ChildItem -LiteralPath $stageRuntime -File -Recurse -Force)
    if ($publishedFiles.Count -ne 30) {
        throw "Temporary V3 runtime contains $($publishedFiles.Count) logical files immediately after publish; expected exactly 30."
    }
    $publishedLogicalFiles = @(
        $publishedFiles |
            ForEach-Object { Get-RelativeChildPath -Root $stageRuntime -Path $_.FullName } |
            Sort-Object
    )

    Write-Host "[hybrid-v3-final] Running complete Source + Godot/Spine validation against the temporary formal paths..."
    $sourceValidationArguments = @(
        '-Phase', 'Source',
        '-ProjectDir', $stageProject,
        '-ContractPath', $contract,
        '-RuntimeLayout', $runtimeLayout,
        '-GodotExe', $GodotExe,
        '-Sts2Dir', $Sts2Dir
    )
    $sourceExitCode = Invoke-HiddenPowerShellScript `
        -ScriptPath $sourceValidator `
        -Arguments $sourceValidationArguments `
        -LogStem (Join-Path $OutputDir "source-godot-validate")
    if ($sourceExitCode -ne 0) {
        throw "Temporary V3 Source/Godot validation failed with exit code $sourceExitCode."
    }

    Write-Host "[hybrid-v3-final] Rendering all eight animations in hidden off-screen Vulkan..."
    $exactFrameCount = 0
    foreach ($animation in $animations) {
        $animationOutput = Join-Path $exactRoot $animation
        [void][IO.Directory]::CreateDirectory($animationOutput)
        $arguments = @(
            '--path', $stageProject,
            '--display-driver', 'windows',
            '--rendering-driver', 'vulkan',
            '--resolution', '64x64',
            '--position', '-32000,-32000',
            '--script', (Join-Path $stageCandidate "render_hybrid_v3_final_exact.gd"),
            '--',
            '--pck', $basePck,
            '--output', $animationOutput,
            '--animation', $animation,
            '--width', [string]$Width,
            '--height', [string]$Height,
            '--scene-scale', $SceneScale.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
            '--origin-x', $OriginX.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
            '--origin-y', $OriginY.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
            '--scene-offset-x', $SceneOffsetX.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture),
            '--scene-offset-y', $SceneOffsetY.ToString('0.########', [Globalization.CultureInfo]::InvariantCulture)
        )
        if ((Invoke-HiddenGodot -Arguments $arguments `
                -LogStem (Join-Path $OutputDir "logs/exact-$animation")) -ne 0) {
            throw "Hidden Vulkan exact renderer failed for '$animation'."
        }
        $exactSummaryPath = Join-Path $animationOutput "summary.json"
        Assert-ExactRenderReport -SummaryPath $exactSummaryPath -Animation $animation
        $exactSummary = [IO.File]::ReadAllText($exactSummaryPath) | ConvertFrom-Json
        $exactFrameCount += @($exactSummary.frames).Count
    }
    if ($exactFrameCount -ne 84) {
        throw "Exact Vulkan suite rendered $exactFrameCount frames; expected exactly 84."
    }

    Write-Host "[hybrid-v3-final] Rendering cross-animation and VFX sequences in hidden Vulkan..."
    $transitionArguments = @(
        '--path', $stageProject,
        '--display-driver', 'windows',
        '--rendering-driver', 'vulkan',
        '--resolution', '64x64',
        '--position', '-32000,-32000',
        '--script', (Join-Path $stageCandidate "render_hybrid_v3_final_transitions.gd"),
        '--',
        'render-transitions',
        $transitionRoot
    )
    if ((Invoke-HiddenGodot -Arguments $transitionArguments `
            -LogStem (Join-Path $OutputDir "logs/transitions")) -ne 0) {
        throw "Hidden Vulkan transition/VFX renderer failed."
    }
    $transitionSummary = Join-Path $transitionRoot "transition_summary.json"
    Assert-TransitionReport -SummaryPath $transitionSummary

    Write-Host "[hybrid-v3-final] Rendering the staged production merchant scene at deterministic seeks..."
    $merchantArguments = @(
        '--path', $stageProject,
        '--display-driver', 'windows',
        '--rendering-driver', 'vulkan',
        '--resolution', '64x64',
        '--position', '-32000,-32000',
        '--script', (Join-Path $stageCandidate "render_hybrid_v3_final_merchant.gd"),
        '--',
        'render-merchant',
        $merchantRoot
    )
    if ((Invoke-HiddenGodot -Arguments $merchantArguments `
            -LogStem (Join-Path $OutputDir "logs/merchant")) -ne 0) {
        throw "Hidden Vulkan merchant renderer failed."
    }
    $merchantSummary = Join-Path $merchantRoot "merchant_summary.json"
    Assert-MerchantReport -SummaryPath $merchantSummary

    $formalAfter = Get-TreeSnapshot -Root $formalRuntime
    if (($formalBefore -join "`n") -cne ($formalAfter -join "`n")) {
        throw "Formal Vivhite/Vivhite/skins/ironclad changed during isolated validation."
    }

    $summary = [ordered]@{
        success = $true
        runtime_layout = $runtimeLayout
        candidate_root = $candidateRoot
        temporary_project = $stageProject
        temporary_runtime = $stageRuntime
        logical_file_count = $publishedLogicalFiles.Count
        logical_files = $publishedLogicalFiles
        exact_frame_count = $exactFrameCount
        exact_animation_reports = @($animations | ForEach-Object { Join-Path (Join-Path $exactRoot $_) "summary.json" })
        runtime_vfx_scenario_count = 8
        runtime_vfx_report = $runtimeVfxSummary
        transition_sequence_count = 25
        transition_sample_count = 104
        transition_report = $transitionSummary
        merchant_frame_count = 10
        merchant_report = $merchantSummary
        formal_runtime_unchanged = $true
        pck_exported = $false
        deployed_to_game = $false
    }
    $summaryPath = Join-Path $OutputDir "validation_summary.json"
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($summaryPath, ($summary | ConvertTo-Json -Depth 8) + "`n", $utf8NoBom)
    Write-Host "[hybrid-v3-final] PASS: candidate + 30-file Source/Godot + Vulkan gates." -ForegroundColor Green
    Write-Host "[hybrid-v3-final] Report: $summaryPath" -ForegroundColor Green
    Write-Host "[hybrid-v3-final] No PCK was exported and no game mod was deployed." -ForegroundColor Green
}
finally {
    $env:DOTNET_ROOT = $previousDotnetRoot
    $env:DOTNET_ROOT_X64 = $previousDotnetRootX64
    $env:PATH = $previousPath
    $env:STS2_SKIP_PCK_EXPORT = $previousSkipExport
    $env:VIVHITE_STS2_PCK_PATH = $previousPck
    $env:VIVHITE_IRONCLAD_RUNTIME_LAYOUT = $previousRuntimeLayout
    if ($spineMutexAcquired) { [void]$spineMutex.ReleaseMutex() }
    $spineMutex.Dispose()
}
