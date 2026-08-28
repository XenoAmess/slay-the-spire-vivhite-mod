[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ValidationOutputDir,

    [string]$OutputDir = "",
    [string]$ProjectDir = "",
    [string]$GodotExe = "",
    [string]$Sts2Dir = "",
    [string]$PythonExe = "",
    [string]$DotnetExe = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$runtimeLayout = "v3-five-page"
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../../../.."))
$workRoot = [IO.Path]::GetFullPath((Join-Path $repoRoot ".work"))
$pckWorkRoot = [IO.Path]::GetFullPath((Join-Path $workRoot "hybrid-v3-final"))
if ([string]::IsNullOrWhiteSpace($ProjectDir)) {
    $ProjectDir = Join-Path $repoRoot "Vivhite"
}
$ProjectDir = [IO.Path]::GetFullPath($ProjectDir)

function Test-IsStrictChildPath {
    param(
        [Parameter(Mandatory = $true)][string]$Parent,
        [Parameter(Mandatory = $true)][string]$Child
    )

    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    $childFull = [IO.Path]::GetFullPath($Child)
    return $childFull.StartsWith(
        $parentFull + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)
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

function Write-JsonFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )

    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($Path))
    $utf8NoBom = New-Object Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, ($Value | ConvertTo-Json -Depth 20) + "`n", $utf8NoBom)
}

function Resolve-PythonCommand {
    param([string]$RequestedPath)

    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        if ([IO.Path]::IsPathRooted($RequestedPath)) {
            $resolved = [IO.Path]::GetFullPath($RequestedPath)
            if (-not [IO.File]::Exists($resolved)) {
                throw "Python executable does not exist: $resolved"
            }
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
        if ($null -eq $command) { throw "Python 3 is required to run the Ironclad publisher." }
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

function Resolve-CommandPath {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$RequestedPath,
        [Parameter(Mandatory = $true)][string[]]$FallbackCommands
    )

    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        if ([IO.Path]::IsPathRooted($RequestedPath)) {
            $resolved = [IO.Path]::GetFullPath($RequestedPath)
            if (-not [IO.File]::Exists($resolved)) { throw "$Label executable does not exist: $resolved" }
            return $resolved
        }
        $requestedCommand = Get-Command $RequestedPath -ErrorAction SilentlyContinue
        if ($null -eq $requestedCommand) { throw "$Label command does not exist: $RequestedPath" }
        return $requestedCommand.Source
    }

    foreach ($commandName in $FallbackCommands) {
        $command = Get-Command $commandName -ErrorAction SilentlyContinue
        if ($null -ne $command) { return $command.Source }
    }
    throw "$Label executable could not be resolved."
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

function Invoke-LoggedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$LogStem
    )

    [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($LogStem))
    $stdoutPath = "$LogStem.stdout.log"
    $stderrPath = "$LogStem.stderr.log"
    $quotedArguments = foreach ($argument in $Arguments) {
        if ($argument -match '[\s"]') {
            '"' + $argument.Replace('"', '\"') + '"'
        }
        else {
            $argument
        }
    }
    $process = Start-Process -FilePath $FilePath -ArgumentList ($quotedArguments -join ' ') `
        -WorkingDirectory $WorkingDirectory -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath `
        -Wait -PassThru
    $process.Refresh()
    foreach ($path in @($stdoutPath, $stderrPath)) {
        if (-not [IO.File]::Exists($path)) { continue }
        foreach ($line in [IO.File]::ReadAllLines($path)) {
            if (-not [string]::IsNullOrWhiteSpace($line)) { Write-Host $line }
        }
    }
    if ($null -eq $process.ExitCode) {
        throw "Process ended without an observable exit code. See '$stdoutPath' and '$stderrPath'."
    }
    if ([int]$process.ExitCode -ne 0) {
        throw "Command '$FilePath' exited with code $($process.ExitCode). See '$stdoutPath' and '$stderrPath'."
    }
}

function Get-TreeHashSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $rootFull = [IO.Path]::GetFullPath($Root)
    $records = @()
    if ([IO.Directory]::Exists($rootFull)) {
        $records = @(
            Get-ChildItem -LiteralPath $rootFull -File -Recurse -Force |
                ForEach-Object {
                    [pscustomobject]@{
                        path = Get-RelativeChildPath -Root $rootFull -Path $_.FullName
                        length = [long]$_.Length
                        sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                    }
                } |
                Sort-Object path
        )
    }
    $signatureLines = @(
        "exists=$([IO.Directory]::Exists($rootFull))"
        foreach ($record in $records) {
            "$($record.path)|$($record.length)|$($record.sha256)"
        }
    )
    $signatureBytes = [Text.Encoding]::UTF8.GetBytes($signatureLines -join "`n")
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $signature = ([BitConverter]::ToString($sha256.ComputeHash($signatureBytes))).Replace('-', '').ToLowerInvariant()
    }
    finally {
        $sha256.Dispose()
    }
    return [pscustomobject]@{
        label = $Label
        root = $rootFull
        exists = [IO.Directory]::Exists($rootFull)
        file_count = $records.Count
        tree_sha256 = $signature
        files = $records
    }
}

function Get-ProtectedSnapshots {
    param(
        [Parameter(Mandatory = $true)][string]$FormalRuntime,
        [Parameter(Mandatory = $true)][string]$GameVivhite,
        [Parameter(Mandatory = $true)][string]$GameRitsuLib
    )

    return [pscustomobject]@{
        captured_utc = [DateTime]::UtcNow.ToString('O')
        targets = @(
            Get-TreeHashSnapshot -Label "formal_runtime" -Root $FormalRuntime
            Get-TreeHashSnapshot -Label "game_mod_vivhite" -Root $GameVivhite
            Get-TreeHashSnapshot -Label "game_mod_ritsulib" -Root $GameRitsuLib
        )
    }
}

function Assert-ProtectedSnapshotsEqual {
    param(
        [Parameter(Mandatory = $true)]$Before,
        [Parameter(Mandatory = $true)]$After
    )

    $beforeTargets = @($Before.targets)
    $afterTargets = @($After.targets)
    if ($beforeTargets.Count -ne $afterTargets.Count) {
        throw "Protected snapshot target count changed during no-deploy PCK validation."
    }
    for ($index = 0; $index -lt $beforeTargets.Count; $index++) {
        $beforeTarget = $beforeTargets[$index]
        $afterTarget = $afterTargets[$index]
        if (-not [string]::Equals([string]$beforeTarget.label, [string]$afterTarget.label, [StringComparison]::Ordinal) -or
            -not [string]::Equals([string]$beforeTarget.root, [string]$afterTarget.root, [StringComparison]::OrdinalIgnoreCase) -or
            [bool]$beforeTarget.exists -ne [bool]$afterTarget.exists -or
            [int]$beforeTarget.file_count -ne [int]$afterTarget.file_count -or
            -not [string]::Equals(
                [string]$beforeTarget.tree_sha256,
                [string]$afterTarget.tree_sha256,
                [StringComparison]::OrdinalIgnoreCase)) {
            throw "Protected target '$($beforeTarget.label)' changed during no-deploy PCK validation."
        }
    }
}

function Copy-IsolatedProject {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    if (-not [IO.Directory]::Exists($Source)) { throw "Vivhite project does not exist: $Source" }
    [void][IO.Directory]::CreateDirectory($Destination)
    foreach ($file in Get-ChildItem -LiteralPath $Source -File -Recurse -Force) {
        $relative = Get-RelativeChildPath -Root $Source -Path $file.FullName
        $parts = $relative.Split('/')
        $excludedDirectory = $false
        for ($index = 0; $index -lt ($parts.Count - 1); $index++) {
            if ($parts[$index] -in @('.godot', 'bin', 'obj')) {
                $excludedDirectory = $true
                break
            }
        }
        if ($excludedDirectory) { continue }
        if ($relative.StartsWith("Vivhite/skins/ironclad/", [StringComparison]::OrdinalIgnoreCase)) {
            continue
        }
        $target = Join-Path $Destination $relative.Replace('/', [IO.Path]::DirectorySeparatorChar)
        [void][IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target))
        [IO.File]::Copy($file.FullName, $target, $false)
    }
}

function Get-LogicalRuntimeFiles {
    param([Parameter(Mandatory = $true)][string]$Root)

    if (-not [IO.Directory]::Exists($Root)) { throw "Runtime root does not exist: $Root" }
    return @(
        Get-ChildItem -LiteralPath $Root -File -Recurse -Force |
            Where-Object {
                -not $_.Name.EndsWith('.import', [StringComparison]::OrdinalIgnoreCase) -and
                -not $_.Name.EndsWith('.uid', [StringComparison]::OrdinalIgnoreCase)
            } |
            ForEach-Object { Get-RelativeChildPath -Root $Root -Path $_.FullName } |
            Sort-Object
    )
}

if (-not [IO.File]::Exists((Join-Path $ProjectDir "Vivhite.csproj")) -or
    -not [IO.File]::Exists((Join-Path $ProjectDir "project.godot"))) {
    throw "Vivhite project is incomplete: $ProjectDir"
}

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

if ([string]::IsNullOrWhiteSpace($GodotExe)) {
    throw "GodotExe is required (pass -GodotExe or configure Vivhite/local.props)."
}
$GodotExe = Resolve-GodotConsolePath -Path $GodotExe
if (-not [IO.File]::Exists($GodotExe)) { throw "Godot executable does not exist: $GodotExe" }
if ([string]::IsNullOrWhiteSpace($Sts2Dir)) {
    throw "Sts2Dir is required (pass -Sts2Dir or configure Vivhite/local.props)."
}
$Sts2Dir = [IO.Path]::GetFullPath($Sts2Dir)
if (-not [IO.File]::Exists((Join-Path $Sts2Dir "SlayTheSpire2.pck"))) {
    throw "Base-game PCK does not exist below: $Sts2Dir"
}

$python = Resolve-PythonCommand -RequestedPath $PythonExe
if ([string]::IsNullOrWhiteSpace($DotnetExe)) {
    $knownDotnet = "C:\Users\xenoa\AppData\Local\Microsoft\dotnet\dotnet.exe"
    if ([IO.File]::Exists($knownDotnet)) { $DotnetExe = $knownDotnet }
}
$DotnetExe = Resolve-CommandPath -Label "dotnet" -RequestedPath $DotnetExe -FallbackCommands @("dotnet.exe", "dotnet")
$powerShellExe = (Get-Process -Id $PID).Path
if (-not [IO.File]::Exists($powerShellExe)) { throw "Could not resolve the current PowerShell host." }

$ValidationOutputDir = [IO.Path]::GetFullPath($ValidationOutputDir)
if (-not [IO.Directory]::Exists($ValidationOutputDir)) {
    throw "V3 validation output does not exist: $ValidationOutputDir"
}
if (-not (Test-IsStrictChildPath -Parent $pckWorkRoot -Child $ValidationOutputDir)) {
    throw "ValidationOutputDir must stay below '$pckWorkRoot': $ValidationOutputDir"
}
$validationSummaryPath = Join-Path $ValidationOutputDir "validation_summary.json"
if (-not [IO.File]::Exists($validationSummaryPath)) {
    throw "ValidationOutputDir has no completed validation_summary.json: $validationSummaryPath"
}
$validationSummary = [IO.File]::ReadAllText($validationSummaryPath) | ConvertFrom-Json
if ($validationSummary.success -ne $true -or
    -not [string]::Equals([string]$validationSummary.runtime_layout, $runtimeLayout, [StringComparison]::Ordinal) -or
    [int]$validationSummary.logical_file_count -ne 30 -or
    $validationSummary.formal_runtime_unchanged -ne $true -or
    $validationSummary.pck_exported -ne $false -or
    $validationSummary.deployed_to_game -ne $false) {
    throw "Input validation summary is not a successful, isolated 30-file V3 result: $validationSummaryPath"
}

$runtimeInputCandidates = New-Object "System.Collections.Generic.List[string]"
if (@($validationSummary.PSObject.Properties.Name) -contains "temporary_runtime") {
    $reportedRuntime = [string]$validationSummary.temporary_runtime
    if (-not [string]::IsNullOrWhiteSpace($reportedRuntime)) {
        if (-not [IO.Path]::IsPathRooted($reportedRuntime)) {
            $reportedRuntime = Join-Path $ValidationOutputDir $reportedRuntime
        }
        $runtimeInputCandidates.Add([IO.Path]::GetFullPath($reportedRuntime))
    }
}
$runtimeInputCandidates.Add([IO.Path]::GetFullPath((Join-Path $ValidationOutputDir "private-runtime-input")))
$privateRuntimeInput = $null
foreach ($candidate in $runtimeInputCandidates) {
    if ([IO.Directory]::Exists($candidate) -and
        (Test-IsStrictChildPath -Parent $ValidationOutputDir -Child $candidate)) {
        $privateRuntimeInput = $candidate
        break
    }
}
if ($null -eq $privateRuntimeInput) {
    throw "Passed V3 output has neither an available temporary runtime nor private-runtime-input below '$ValidationOutputDir'."
}
$inputLogicalFiles = @(Get-LogicalRuntimeFiles -Root $privateRuntimeInput)
if ($inputLogicalFiles.Count -ne 30) {
    throw "Selected V3 runtime input contains $($inputLogicalFiles.Count) logical files; expected exactly 30: $privateRuntimeInput"
}
$reportedLogicalFiles = @(
    @($validationSummary.logical_files) |
        ForEach-Object { ([string]$_).Replace('\', '/') } |
        Sort-Object
)
if (($reportedLogicalFiles -join "`n") -cne ($inputLogicalFiles -join "`n")) {
    throw "Selected V3 runtime input no longer has the exact logical file list recorded by validation_summary.json."
}

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $stamp = [DateTime]::UtcNow.ToString("yyyyMMdd-HHmmss-fffffff")
    $OutputDir = Join-Path $pckWorkRoot "pck-$stamp"
}
$OutputDir = [IO.Path]::GetFullPath($OutputDir)
$outputParent = [IO.Path]::GetDirectoryName($OutputDir).TrimEnd('\', '/')
if (-not [string]::Equals($outputParent, $pckWorkRoot.TrimEnd('\', '/'), [StringComparison]::OrdinalIgnoreCase) -or
    -not [IO.Path]::GetFileName($OutputDir).StartsWith("pck-", [StringComparison]::OrdinalIgnoreCase)) {
    throw "OutputDir must be a direct 'pck-*' child of '$pckWorkRoot': $OutputDir"
}
if ([IO.Directory]::Exists($OutputDir) -and @(Get-ChildItem -LiteralPath $OutputDir -Force).Count -gt 0) {
    throw "OutputDir must be new or empty; this wrapper never cleans previous evidence: $OutputDir"
}
[void][IO.Directory]::CreateDirectory($OutputDir)

$stageProject = Join-Path $OutputDir "project"
$stageRuntime = Join-Path $stageProject "Vivhite/skins/ironclad"
$artifactRoot = Join-Path $OutputDir "artifacts"
$pckPath = Join-Path $artifactRoot "Vivhite.pck"
$modOutputDir = Join-Path $artifactRoot "mod-output/Vivhite"
$ritsuLibDeployDir = Join-Path $artifactRoot "ritsulib-deploy/STS2-RitsuLib"
$logsRoot = Join-Path $OutputDir "logs"
$publisher = Join-Path $repoRoot "tools/art/publish_ironclad_skin.py"
$formalRuntime = Join-Path $repoRoot "Vivhite/Vivhite/skins/ironclad"
$gameVivhite = Join-Path $Sts2Dir "mods/Vivhite"
$gameRitsuLib = Join-Path $Sts2Dir "mods/STS2-RitsuLib"
$protectedBeforePath = Join-Path $OutputDir "protected_before.json"
$protectedAfterPath = Join-Path $OutputDir "protected_after.json"

foreach ($requiredPath in @(
        $publisher,
        (Join-Path $ProjectDir "tools/Validate-IroncladSkin.ps1"),
        (Join-Path $ProjectDir "tools/ironclad-skin.contract.json"),
        (Join-Path $ProjectDir "tools/Export-ModPck.ps1"))) {
    if (-not [IO.File]::Exists($requiredPath)) { throw "Required PCK validation dependency is missing: $requiredPath" }
}

$protectedBefore = Get-ProtectedSnapshots `
    -FormalRuntime $formalRuntime -GameVivhite $gameVivhite -GameRitsuLib $gameRitsuLib
Write-JsonFile -Path $protectedBeforePath -Value $protectedBefore
$protectedAfter = $null
$previousDotnetRoot = $env:DOTNET_ROOT
$previousDotnetRootX64 = $env:DOTNET_ROOT_X64
$previousPath = $env:PATH
$previousSkipExport = $env:STS2_SKIP_PCK_EXPORT
$previousCopyMod = $env:CopyModOnBuild
$previousRitsuCopy = $env:RitsuLibAutoCopy
$previousPck = $env:VIVHITE_STS2_PCK_PATH
$previousRuntimeLayout = $env:VIVHITE_IRONCLAD_RUNTIME_LAYOUT
$summary = $null
try {
    # Godot --import may invoke the Godot .NET build implicitly. Establish the no-copy
    # environment before the first staged Godot/validator process, not only before the
    # explicit dotnet build below.
    $dotnetRoot = [IO.Path]::GetDirectoryName($DotnetExe).TrimEnd('\', '/')
    $env:DOTNET_ROOT = $dotnetRoot
    $env:DOTNET_ROOT_X64 = $dotnetRoot
    $dotnetPrefix = $dotnetRoot + [IO.Path]::PathSeparator
    if (-not $env:PATH.StartsWith($dotnetPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        $env:PATH = $dotnetPrefix + $env:PATH
    }
    $env:STS2_SKIP_PCK_EXPORT = "1"
    $env:CopyModOnBuild = "false"
    $env:RitsuLibAutoCopy = "false"
    $env:VIVHITE_STS2_PCK_PATH = Join-Path $Sts2Dir "SlayTheSpire2.pck"
    $env:VIVHITE_IRONCLAD_RUNTIME_LAYOUT = $runtimeLayout

    Write-Host "[hybrid-v3-final-pck] Copying a complete isolated Vivhite project (excluding .godot/bin/obj and the formal runtime)..."
    Copy-IsolatedProject -Source $ProjectDir -Destination $stageProject
    if ([IO.Directory]::Exists($stageRuntime)) {
        throw "Isolated project copy unexpectedly included the formal Ironclad runtime: $stageRuntime"
    }

    Write-Host "[hybrid-v3-final-pck] Publishing the strict 30-file V3 runtime into the isolated project..."
    $publisherArguments = @($python.Prefix) + @(
        '-B', $publisher,
        '--template-root', (Join-Path $repoRoot "assets/ironclad-v0.111.0"),
        '--art-root', (Join-Path $repoRoot "assets/vivhite-ironclad/custom"),
        '--approved-root', (Join-Path $repoRoot "assets/vivhite-ironclad/approved"),
        '--private-runtime-root', $privateRuntimeInput,
        '--runtime-layout', $runtimeLayout,
        '--destination', $stageRuntime
    )
    Invoke-LoggedCommand -FilePath $python.Path -Arguments $publisherArguments `
        -WorkingDirectory $repoRoot -LogStem (Join-Path $logsRoot "01-publisher")
    $publishedLogicalFiles = @(Get-LogicalRuntimeFiles -Root $stageRuntime)
    if ($publishedLogicalFiles.Count -ne 30) {
        throw "Isolated project runtime contains $($publishedLogicalFiles.Count) logical files after publish; expected exactly 30."
    }
    Write-JsonFile -Path (Join-Path $OutputDir "published_runtime.json") -Value ([ordered]@{
        runtime_layout = $runtimeLayout
        logical_file_count = $publishedLogicalFiles.Count
        logical_files = $publishedLogicalFiles
    })

    $stageValidator = Join-Path $stageProject "tools/Validate-IroncladSkin.ps1"
    $stageContract = Join-Path $stageProject "tools/ironclad-skin.contract.json"
    Write-Host "[hybrid-v3-final-pck] Running isolated Source + Godot/Spine validation..."
    Invoke-LoggedCommand -FilePath $powerShellExe -Arguments @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $stageValidator,
        '-ProjectDir', $stageProject,
        '-ContractPath', $stageContract,
        '-Phase', 'Source',
        '-RuntimeLayout', $runtimeLayout,
        '-GodotExe', $GodotExe,
        '-Sts2Dir', $Sts2Dir
    ) -WorkingDirectory $stageProject -LogStem (Join-Path $logsRoot "02-source-godot")

    $env:STS2_SKIP_PCK_EXPORT = "0"

    [void][IO.Directory]::CreateDirectory($artifactRoot)
    $modOutputProperty = $modOutputDir.TrimEnd('\', '/')
    $ritsuOutputProperty = $ritsuLibDeployDir.TrimEnd('\', '/')
    Write-Host "[hybrid-v3-final-pck] Building C# and exporting/validating a no-deploy PCK..."
    Invoke-LoggedCommand -FilePath $DotnetExe -Arguments @(
        'build', (Join-Path $stageProject "Vivhite.csproj"),
        '-c', 'Debug',
        "/p:UseSharedCompilation=false",
        "/p:RunPckExport=true",
        "/p:CopyModOnBuild=false",
        "/p:RitsuLibAutoCopy=false",
        "/p:IroncladSkinRuntimeLayout=$runtimeLayout",
        "/p:GodotExe=$GodotExe",
        "/p:Sts2Dir=$Sts2Dir",
        "/p:Sts2DataDir=$(Join-Path $Sts2Dir 'data_sts2_windows_x86_64')",
        "/p:ModPckPath=$pckPath",
        "/p:ModOutputDir=$modOutputProperty",
        "/p:RitsuLibDeployDir=$ritsuOutputProperty"
    ) -WorkingDirectory $stageProject -LogStem (Join-Path $logsRoot "03-dotnet-build-export")

    if (-not [IO.File]::Exists($pckPath) -or (Get-Item -LiteralPath $pckPath).Length -le 0) {
        throw "C# build/export did not create a non-empty isolated PCK: $pckPath"
    }
    $expectedBuiltDll = Join-Path $stageProject ".godot/mono/temp/bin/Debug/Vivhite.dll"
    if (-not [IO.File]::Exists($expectedBuiltDll) -or (Get-Item -LiteralPath $expectedBuiltDll).Length -le 0) {
        throw "C# build did not produce a non-empty Godot .NET assembly: $expectedBuiltDll"
    }
    $builtDlls = @((Get-Item -LiteralPath $expectedBuiltDll))
    if ([IO.Directory]::Exists($modOutputDir) -and @(Get-ChildItem -LiteralPath $modOutputDir -Force).Count -gt 0) {
        throw "CopyModOnBuild=false was violated; isolated ModOutputDir is not empty: $modOutputDir"
    }
    if ([IO.Directory]::Exists($ritsuLibDeployDir) -and @(Get-ChildItem -LiteralPath $ritsuLibDeployDir -Force).Count -gt 0) {
        throw "RitsuLibAutoCopy=false was violated; isolated RitsuLibDeployDir is not empty: $ritsuLibDeployDir"
    }

    Write-Host "[hybrid-v3-final-pck] Re-running the PCK gate against the installed isolated artifact..."
    Invoke-LoggedCommand -FilePath $powerShellExe -Arguments @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $stageValidator,
        '-ProjectDir', $stageProject,
        '-ContractPath', $stageContract,
        '-Phase', 'Pck',
        '-PckPath', $pckPath,
        '-RuntimeLayout', $runtimeLayout
    ) -WorkingDirectory $stageProject -LogStem (Join-Path $logsRoot "04-final-pck-gate")

    $pckInfo = Get-Item -LiteralPath $pckPath
    $summary = [ordered]@{
        success = $true
        runtime_layout = $runtimeLayout
        validation_input = $ValidationOutputDir
        private_runtime_input = $privateRuntimeInput
        input_logical_file_count = $inputLogicalFiles.Count
        isolated_project = $stageProject
        isolated_runtime = $stageRuntime
        published_logical_file_count = $publishedLogicalFiles.Count
        pck_path = $pckInfo.FullName
        pck_size_bytes = [long]$pckInfo.Length
        pck_sha256 = (Get-FileHash -LiteralPath $pckInfo.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        vivhite_dll_paths = @($builtDlls | ForEach-Object { $_.FullName })
        properties = [ordered]@{
            RunPckExport = $true
            CopyModOnBuild = $false
            RitsuLibAutoCopy = $false
            IroncladSkinRuntimeLayout = $runtimeLayout
            ModPckPath = $pckPath
            ModOutputDir = $modOutputProperty
            RitsuLibDeployDir = $ritsuOutputProperty
        }
        source_godot_gate_passed = $true
        csharp_build_passed = $true
        export_pck_gate_passed = $true
        final_pck_gate_passed = $true
        formal_runtime_unchanged = $true
        game_mod_vivhite_unchanged = $true
        game_mod_ritsulib_unchanged = $true
        deployed_to_game = $false
        logs = [ordered]@{
            publisher = Join-Path $logsRoot "01-publisher.stdout.log"
            source_godot = Join-Path $logsRoot "02-source-godot.stdout.log"
            build_export = Join-Path $logsRoot "03-dotnet-build-export.stdout.log"
            final_pck_gate = Join-Path $logsRoot "04-final-pck-gate.stdout.log"
        }
    }
}
finally {
    $env:DOTNET_ROOT = $previousDotnetRoot
    $env:DOTNET_ROOT_X64 = $previousDotnetRootX64
    $env:PATH = $previousPath
    $env:STS2_SKIP_PCK_EXPORT = $previousSkipExport
    $env:CopyModOnBuild = $previousCopyMod
    $env:RitsuLibAutoCopy = $previousRitsuCopy
    $env:VIVHITE_STS2_PCK_PATH = $previousPck
    $env:VIVHITE_IRONCLAD_RUNTIME_LAYOUT = $previousRuntimeLayout

    $protectedAfter = Get-ProtectedSnapshots `
        -FormalRuntime $formalRuntime -GameVivhite $gameVivhite -GameRitsuLib $gameRitsuLib
    Write-JsonFile -Path $protectedAfterPath -Value $protectedAfter
    Assert-ProtectedSnapshotsEqual -Before $protectedBefore -After $protectedAfter
}

if ($null -eq $summary) { throw "PCK validation ended without producing its success summary." }
Write-JsonFile -Path (Join-Path $OutputDir "pck_validation_summary.json") -Value $summary
Write-Host "[hybrid-v3-final-pck] PASS: full C# build + validated V3 PCK completed without deployment." -ForegroundColor Green
Write-Host "[hybrid-v3-final-pck] PCK: $pckPath" -ForegroundColor Green
Write-Host "[hybrid-v3-final-pck] Report: $(Join-Path $OutputDir 'pck_validation_summary.json')" -ForegroundColor Green
