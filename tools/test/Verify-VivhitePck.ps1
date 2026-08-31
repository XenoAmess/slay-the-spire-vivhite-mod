<#
.SYNOPSIS
Performs the final read-only Vivhite PCK content gate.

.DESCRIPTION
Validates a completed Vivhite PCK without building, deploying, starting the game,
or modifying the PCK. The gate verifies the existing V3 Ironclad skin contract,
the exact 314 player-facing localization keys across six files per language,
current Cough/Margin terminology, and all 92 runtime art imports. It mounts the PCK in an empty
temporary Godot project so repository source files cannot mask missing packed
resources.

Success removes both per-run directories below RepoRoot/.tmp while retaining the
append-only lifecycle journal. Failure preserves/reconstructs the evidence
directory and prints its absolute path. Once the input PCK is readable, its
SHA-256 is checked before and after validation.

.PARAMETER RepoRoot
Repository root. Defaults to the root containing this tools/test directory.

.PARAMETER PckPath
PCK to verify. When omitted, the script reads Sts2Dir from Vivhite/local.props
and selects mods/Vivhite/Vivhite.pck. The known local G: installation is the
last fallback.

.PARAMETER GodotExe
Godot 4.5.1 Mono executable. When omitted, the script reads GodotExe from
Vivhite/local.props and then tries the known local Codex cache path.

.PARAMETER PowerShellExe
Windows PowerShell executable used to isolate the existing skin validator,
whose failure path calls exit. Defaults to the current PowerShell host or
powershell.exe.

.PARAMETER EvidenceRunId
Optional stable identifier for correlating the persistent lifecycle journal and
the per-run evidence directory. Normal runs should omit it; the behavioral test
suite supplies a unique value so it can inspect one run without racing others.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\test\Verify-VivhitePck.ps1

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\test\Verify-VivhitePck.ps1 `
  -PckPath 'G:\staging\Vivhite.pck' `
  -GodotExe 'C:\tools\Godot_v4.5.1-stable_mono_win64.exe'
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [string]$PckPath = "",
    [string]$GodotExe = "",
    [string]$PowerShellExe = "",
    [ValidatePattern('^[A-Za-z0-9-]{8,64}$')]
    [string]$EvidenceRunId = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Windows PowerShell 5.1 otherwise chooses a legacy code page when this script's
# own output is redirected by CI or the behavioral harness. Child process streams
# are decoded separately by Invoke-CapturedProcess.
try {
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false, $true)
}
catch {
    # Some non-console hosts expose no writable standard handle. Evidence files
    # remain explicitly encoded even in that host; do not make the gate unusable.
}

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($false, $true)
    [IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Write-Utf8Bom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Content
    )

    $encoding = New-Object System.Text.UTF8Encoding($true, $true)
    [IO.File]::WriteAllText($Path, $Content, $encoding)
}

function ConvertTo-WindowsCommandLineArgument {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value
    )

    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') {
        return $Value
    }

    $builder = New-Object Text.StringBuilder
    [void]$builder.Append('"')
    $backslashes = 0
    foreach ($character in $Value.ToCharArray()) {
        if ($character -eq '\') {
            $backslashes += 1
            continue
        }
        if ($character -eq '"') {
            [void]$builder.Append(('\' * (($backslashes * 2) + 1)))
            [void]$builder.Append('"')
            $backslashes = 0
            continue
        }
        if ($backslashes -gt 0) {
            [void]$builder.Append(('\' * $backslashes))
            $backslashes = 0
        }
        [void]$builder.Append($character)
    }
    if ($backslashes -gt 0) {
        [void]$builder.Append(('\' * ($backslashes * 2)))
    }
    [void]$builder.Append('"')
    return $builder.ToString()
}

function Write-GateEvent {
    param(
        [Parameter(Mandatory = $true)][string]$JournalPath,
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][string]$Operation,
        [Parameter(Mandatory = $true)][string]$Status,
        [string]$Target = "",
        [string]$Message = ""
    )

    $record = [ordered]@{
        schema = 1
        run_id = $RunId
        recorded_utc = [DateTime]::UtcNow.ToString("O")
        operation = $Operation
        status = $Status
        target = $Target
        message = $Message
    }
    $line = ($record | ConvertTo-Json -Compress) + [Environment]::NewLine
    try {
        $encoding = New-Object System.Text.UTF8Encoding($true, $true)
        [IO.File]::AppendAllText($JournalPath, $line, $encoding)
    }
    catch {
        # The console record is the last-resort evidence if the journal itself
        # cannot be created or appended. Never hide the original gate failure.
        [Console]::Error.WriteLine(
            "[EVIDENCE-FAIL] run=$RunId operation=$Operation target=$Target " +
            "journal=$JournalPath error=$($_.Exception.Message)")
    }
}

function Write-TrackedUtf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Content,
        [Parameter(Mandatory = $true)][bool]$WithBom,
        [Parameter(Mandatory = $true)][string]$JournalPath,
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][string]$Operation
    )

    try {
        if ($WithBom) {
            Write-Utf8Bom -Path $Path -Content $Content
        }
        else {
            Write-Utf8NoBom -Path $Path -Content $Content
        }
        Write-GateEvent -JournalPath $JournalPath -RunId $RunId `
            -Operation $Operation -Status "success" -Target $Path
    }
    catch {
        Write-GateEvent -JournalPath $JournalPath -RunId $RunId `
            -Operation $Operation -Status "failure" -Target $Path `
            -Message $_.Exception.Message
        throw
    }
}

function New-TrackedDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$JournalPath,
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][string]$Operation
    )

    try {
        [void][IO.Directory]::CreateDirectory($Path)
        Write-GateEvent -JournalPath $JournalPath -RunId $RunId `
            -Operation $Operation -Status "success" -Target $Path
    }
    catch {
        Write-GateEvent -JournalPath $JournalPath -RunId $RunId `
            -Operation $Operation -Status "failure" -Target $Path `
            -Message $_.Exception.Message
        throw
    }
}

function Remove-TrackedPath {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$JournalPath,
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][string]$Operation
    )

    if (-not [IO.File]::Exists($Path) -and -not [IO.Directory]::Exists($Path)) {
        Write-GateEvent -JournalPath $JournalPath -RunId $RunId `
            -Operation $Operation -Status "not_present" -Target $Path
        return
    }

    try {
        Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
        Write-GateEvent -JournalPath $JournalPath -RunId $RunId `
            -Operation $Operation -Status "success" -Target $Path
    }
    catch {
        Write-GateEvent -JournalPath $JournalPath -RunId $RunId `
            -Operation $Operation -Status "failure" -Target $Path `
            -Message $_.Exception.Message
        throw
    }
}

function Invoke-CapturedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$ConsoleLogPath,
        [Parameter(Mandatory = $true)][string]$JournalPath,
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][string]$Stage
    )

    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (@(
        $ArgumentList | ForEach-Object {
            ConvertTo-WindowsCommandLineArgument -Value ([string]$_)
        }
    ) -join ' ')
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $startInfo.StandardOutputEncoding = $utf8
    $startInfo.StandardErrorEncoding = $utf8

    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    try {
        Write-GateEvent -JournalPath $JournalPath -RunId $RunId `
            -Operation "process_$Stage" -Status "starting" -Target $FilePath
        if (-not $process.Start()) {
            throw "Process.Start returned false for '$FilePath'."
        }

        # Read both redirected streams asynchronously before the explicit wait,
        # otherwise a full pipe can deadlock. WaitForExit is mandatory here:
        # Windows PowerShell 5.1 does not reliably wait when a GUI-subsystem
        # Godot executable is invoked with the call operator.
        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        $stdout = $stdoutTask.GetAwaiter().GetResult()
        $stderr = $stderrTask.GetAwaiter().GetResult()
        $process.WaitForExit()
        $stopwatch.Stop()

        $log = @(
            "[process] $FilePath"
            "[arguments] $($startInfo.Arguments)"
            "[exit_code] $($process.ExitCode)"
            "[duration_ms] $($stopwatch.ElapsedMilliseconds)"
            "[stdout]"
            $stdout.TrimEnd("`r", "`n")
            "[stderr]"
            $stderr.TrimEnd("`r", "`n")
            ""
        ) -join [Environment]::NewLine
        Write-TrackedUtf8File -Path $ConsoleLogPath -Content $log -WithBom $true `
            -JournalPath $JournalPath -RunId $RunId `
            -Operation "temporary_file_create_$Stage-console"

        if (-not [string]::IsNullOrEmpty($stdout)) {
            Write-Host ($stdout.TrimEnd("`r", "`n"))
        }
        if (-not [string]::IsNullOrEmpty($stderr)) {
            [Console]::Error.WriteLine($stderr.TrimEnd("`r", "`n"))
        }

        Write-GateEvent -JournalPath $JournalPath -RunId $RunId `
            -Operation "process_$Stage" -Status "exited" -Target $FilePath `
            -Message "exit=$($process.ExitCode); duration_ms=$($stopwatch.ElapsedMilliseconds)"
        return [pscustomobject]@{
            ExitCode = $process.ExitCode
            StdOut = $stdout
            StdErr = $stderr
            Combined = $stdout + [Environment]::NewLine + $stderr
            DurationMilliseconds = $stopwatch.ElapsedMilliseconds
        }
    }
    catch {
        $stopwatch.Stop()
        Write-GateEvent -JournalPath $JournalPath -RunId $RunId `
            -Operation "process_$Stage" -Status "failure" -Target $FilePath `
            -Message $_.Exception.Message
        throw
    }
    finally {
        $process.Dispose()
    }
}

function Get-LocalProperty {
    param(
        [Parameter(Mandatory = $true)][string]$PropsPath,
        [Parameter(Mandatory = $true)][string]$Name
    )

    if (-not [IO.File]::Exists($PropsPath)) {
        return ""
    }

    try {
        [xml]$document = [IO.File]::ReadAllText($PropsPath)
        $node = $document.SelectSingleNode("//*[local-name()='$Name']")
        if ($null -eq $node -or [string]::IsNullOrWhiteSpace($node.InnerText)) {
            return ""
        }
        return [Environment]::ExpandEnvironmentVariables($node.InnerText.Trim())
    }
    catch {
        throw "Could not read '$Name' from '$PropsPath': $($_.Exception.Message)"
    }
}

function Get-AuditNames {
    param(
        [Parameter(Mandatory = $true)][string]$AuditText,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $pattern = 'const\s+' + [regex]::Escape($Name) + '\s*:=\s*\[(?<body>.*?)\]'
    $match = [regex]::Match(
        $AuditText,
        $pattern,
        [Text.RegularExpressions.RegexOptions]::Singleline)
    if (-not $match.Success) {
        throw "Could not read $Name from the runtime-art audit."
    }

    return @(
        [regex]::Matches($match.Groups['body'].Value, '"(?<value>[^"]+)"') |
            ForEach-Object { $_.Groups['value'].Value }
    )
}

function Assert-FileExists {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not [IO.File]::Exists($Path)) {
        throw "$Label does not exist: $Path"
    }
}

$repoFullPath = [IO.Path]::GetFullPath($RepoRoot)
$localPropsPath = Join-Path $repoFullPath "Vivhite\local.props"

if ([string]::IsNullOrWhiteSpace($PckPath)) {
    $configuredGameDir = Get-LocalProperty -PropsPath $localPropsPath -Name "Sts2Dir"
    if (-not [string]::IsNullOrWhiteSpace($configuredGameDir)) {
        $PckPath = Join-Path $configuredGameDir "mods\Vivhite\Vivhite.pck"
    }
    else {
        $PckPath = "G:\SteamLibrary\steamapps\common\Slay the Spire 2\mods\Vivhite\Vivhite.pck"
    }
}

if ([string]::IsNullOrWhiteSpace($GodotExe)) {
    $GodotExe = Get-LocalProperty -PropsPath $localPropsPath -Name "GodotExe"
    if ([string]::IsNullOrWhiteSpace($GodotExe)) {
        $GodotExe = "C:\Users\xenoa\AppData\Local\Temp\opencode\godot\Godot_v4.5.1-stable_mono_win64\Godot_v4.5.1-stable_mono_win64.exe"
    }
}

if ([string]::IsNullOrWhiteSpace($PowerShellExe)) {
    try {
        $PowerShellExe = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
    }
    catch {
        $PowerShellExe = "powershell.exe"
    }
}

$pckFullPath = [IO.Path]::GetFullPath($PckPath)
$godotFullPath = [IO.Path]::GetFullPath($GodotExe)
$skinValidator = Join-Path $repoFullPath "Vivhite\tools\Validate-IroncladSkin.ps1"
$skinContract = Join-Path $repoFullPath "Vivhite\tools\ironclad-skin.contract.json"
$artAudit = Join-Path $repoFullPath "tools\art\audit_vivhite_runtime_art.gd"
$godotProject = Join-Path $repoFullPath "Vivhite"
$tempBase = [IO.Path]::GetFullPath((Join-Path $repoFullPath ".tmp")).TrimEnd('\', '/')
$runId = if ([string]::IsNullOrWhiteSpace($EvidenceRunId)) {
    [Guid]::NewGuid().ToString("N")
}
else {
    $EvidenceRunId
}

try {
    [void][IO.Directory]::CreateDirectory($tempBase)
}
catch {
    [Console]::Error.WriteLine(
        "[EVIDENCE-FAIL] run=$runId operation=temporary_base_create " +
        "target=$tempBase error=$($_.Exception.Message)")
    throw
}

$journalPath = Join-Path $tempBase "vivhite-pck-gate-events.jsonl"
$gateRoot = [IO.Path]::GetFullPath((Join-Path $tempBase ("vivhite-pck-gate-" + $runId)))
$workRoot = [IO.Path]::GetFullPath((Join-Path $tempBase ("vivhite-pck-work-" + $runId)))
$tempPrefix = $tempBase + [IO.Path]::DirectorySeparatorChar
foreach ($temporaryPath in @($gateRoot, $workRoot)) {
    if (-not $temporaryPath.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        Write-GateEvent -JournalPath $journalPath -RunId $runId `
            -Operation "temporary_path_validation" -Status "failure" `
            -Target $temporaryPath -Message "Path is outside repository temp root."
        throw "Refusing unsafe temporary path outside the repository temp root: $temporaryPath"
    }
}

$manifestPath = Join-Path $workRoot "expected.json"
$temporaryProjectPath = Join-Path $workRoot "project.godot"
$runtimeValidatorPath = Join-Path $workRoot "verify_pck.gd"
$validationError = $null
$immutabilityError = $null
$cleanupError = $null
$validationSucceeded = $false
$pckHashBefore = $null
$failureRecords = New-Object "System.Collections.Generic.List[object]"

function Save-FailureEvidence {
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][Management.Automation.ErrorRecord]$ErrorRecord
    )

    $record = [ordered]@{
        stage = $Stage
        recorded_utc = [DateTime]::UtcNow.ToString("O")
        message = $ErrorRecord.Exception.Message
        category = [string]$ErrorRecord.CategoryInfo.Category
        fully_qualified_error_id = [string]$ErrorRecord.FullyQualifiedErrorId
        script_stack_trace = [string]$ErrorRecord.ScriptStackTrace
    }
    $failureRecords.Add([pscustomobject]$record)
    Write-GateEvent -JournalPath $journalPath -RunId $runId `
        -Operation $Stage -Status "failure" -Target $gateRoot `
        -Message $ErrorRecord.Exception.Message

    try {
        if (-not [IO.Directory]::Exists($gateRoot)) {
            New-TrackedDirectory -Path $gateRoot -JournalPath $journalPath `
                -RunId $runId -Operation "temporary_evidence_recovery_create"
        }
        $failureDocument = [ordered]@{
            schema = 1
            run_id = $runId
            evidence_root = $gateRoot
            work_root = $workRoot
            failures = [object[]]$failureRecords.ToArray()
        }
        Write-TrackedUtf8File -Path (Join-Path $gateRoot "failure.json") `
            -Content ($failureDocument | ConvertTo-Json -Depth 8) -WithBom $true `
            -JournalPath $journalPath -RunId $runId `
            -Operation "temporary_failure_evidence_create"
    }
    catch {
        [Console]::Error.WriteLine(
            "[EVIDENCE-FAIL] run=$runId operation=temporary_failure_evidence_create " +
            "target=$gateRoot error=$($_.Exception.Message)")
        Write-GateEvent -JournalPath $journalPath -RunId $runId `
            -Operation "temporary_failure_evidence_create" -Status "failure" `
            -Target $gateRoot -Message $_.Exception.Message
    }
}

try {
    if ([IO.File]::Exists($gateRoot) -or [IO.Directory]::Exists($gateRoot)) {
        throw "Evidence directory already exists; refusing to overwrite it: $gateRoot"
    }
    New-TrackedDirectory -Path $gateRoot -JournalPath $journalPath `
        -RunId $runId -Operation "temporary_evidence_directory_create"
    New-TrackedDirectory -Path $workRoot -JournalPath $journalPath `
        -RunId $runId -Operation "temporary_work_directory_create"

    Assert-FileExists -Path (Join-Path $repoFullPath "AGENTS.md") -Label "Repository marker"
    Assert-FileExists -Path $pckFullPath -Label "PCK"
    Assert-FileExists -Path $godotFullPath -Label "Godot executable"
    Assert-FileExists -Path $skinValidator -Label "Skin validator"
    Assert-FileExists -Path $skinContract -Label "Skin contract"
    Assert-FileExists -Path $artAudit -Label "Runtime-art audit"
    Assert-FileExists -Path (Join-Path $godotProject "project.godot") -Label "Godot project"

    $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)

    $pckHashBefore = (Get-FileHash -LiteralPath $pckFullPath -Algorithm SHA256).Hash
    $inputEvidence = [ordered]@{
        run_id = $runId
        repo_root = $repoFullPath
        pck_path = $pckFullPath
        pck_sha256_before = $pckHashBefore
        godot_exe = $godotFullPath
        evidence_root = $gateRoot
        work_root = $workRoot
        lifecycle_journal = $journalPath
        started_utc = [DateTime]::UtcNow.ToString("O")
    }
    Write-TrackedUtf8File -Path (Join-Path $gateRoot "inputs.json") `
        -Content ($inputEvidence | ConvertTo-Json -Depth 4) -WithBom $true `
        -JournalPath $journalPath -RunId $runId `
        -Operation "temporary_input_evidence_create"

    # Run both Godot phases from an empty temporary project. Source files are
    # addressed by absolute path, so the repository's .godot state stays read-only.
    Write-TrackedUtf8File -Path $temporaryProjectPath -WithBom $false `
        -JournalPath $journalPath -RunId $runId `
        -Operation "temporary_project_create" -Content @'
config_version=5

[application]
config/name="VivhitePckGate"

[rendering]
renderer/rendering_method="gl_compatibility"
'@

    # Layer 1: source art must match the exact 92-item canonical runtime set.
    $sourceArtReportPath = Join-Path $gateRoot "source-art-report.json"
    $sourceArtResult = Invoke-CapturedProcess -FilePath $godotFullPath `
        -ArgumentList @(
            "--headless",
            "--path", $workRoot,
            "--log-file", (Join-Path $gateRoot "source-art.godot.log"),
            "--script", $artAudit,
            "--",
            "--repo-root", $repoFullPath,
            "--report", $sourceArtReportPath
        ) `
        -WorkingDirectory $workRoot `
        -ConsoleLogPath (Join-Path $gateRoot "source-art.console.log") `
        -JournalPath $journalPath -RunId $runId -Stage "source_art"
    if ($sourceArtResult.ExitCode -ne 0) {
        throw "Source runtime-art audit failed with exit code $($sourceArtResult.ExitCode)."
    }
    Assert-FileExists -Path $sourceArtReportPath -Label "Source runtime-art report"
    $sourceArtReport = [IO.File]::ReadAllText($sourceArtReportPath, $strictUtf8) | ConvertFrom-Json
    $sourceExpectedProperty = $sourceArtReport.PSObject.Properties["expected"]
    $sourceAcceptedProperty = $sourceArtReport.PSObject.Properties["accepted"]
    $sourceErrorsProperty = $sourceArtReport.PSObject.Properties["errors"]
    if ($null -eq $sourceExpectedProperty -or $null -eq $sourceAcceptedProperty -or
        $null -eq $sourceErrorsProperty) {
        throw "Source runtime-art report is missing expected, accepted, or errors."
    }
    $sourceExpected = [int]$sourceExpectedProperty.Value
    $sourceAccepted = [int]$sourceAcceptedProperty.Value
    $sourceErrors = @($sourceErrorsProperty.Value)
    if ($sourceExpected -ne 92 -or $sourceAccepted -ne 92 -or $sourceErrors.Count -ne 0) {
        throw (
            "Source runtime-art report is expected=$sourceExpected, accepted=$sourceAccepted, " +
            "errors=$($sourceErrors.Count); required exactly 92/92 with zero errors.")
    }

    # Layer 2: pin the source/published skin contract to 30/34, then isolate the
    # existing PCK validator because its error path calls exit.
    $skinContractDocument = [IO.File]::ReadAllText($skinContract, $strictUtf8) | ConvertFrom-Json
    $skinSourceCountProperty = $skinContractDocument.PSObject.Properties["expectedRuntimeFileCount"]
    $skinLayoutsProperty = $skinContractDocument.PSObject.Properties["combatRuntimeLayouts"]
    if ($null -eq $skinSourceCountProperty -or $null -eq $skinLayoutsProperty) {
        throw "Skin contract is missing expectedRuntimeFileCount or combatRuntimeLayouts."
    }
    $v3Layouts = @($skinLayoutsProperty.Value | Where-Object {
        [string]$_.name -eq "v3-five-page"
    })
    if ($v3Layouts.Count -ne 1) {
        throw "Skin contract must declare exactly one v3-five-page layout; found $($v3Layouts.Count)."
    }
    $skinPublishedCountProperty = $v3Layouts[0].PSObject.Properties["expectedRuntimeFileCount"]
    if ($null -eq $skinPublishedCountProperty) {
        throw "The v3-five-page skin contract is missing expectedRuntimeFileCount."
    }
    $skinSourceCount = [int]$skinSourceCountProperty.Value
    $skinPublishedCount = [int]$skinPublishedCountProperty.Value
    if ($skinSourceCount -ne 30 -or $skinPublishedCount -ne 34) {
        throw (
            "Skin resource contract is source=$skinSourceCount, published=$skinPublishedCount; " +
            "expected source=30, published=34.")
    }

    $skinResult = Invoke-CapturedProcess -FilePath $PowerShellExe `
        -ArgumentList @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $skinValidator,
            "-ProjectDir", $godotProject,
            "-Phase", "Pck",
            "-PckPath", $pckFullPath,
            "-RuntimeLayout", "v3-five-page"
        ) `
        -WorkingDirectory $workRoot `
        -ConsoleLogPath (Join-Path $gateRoot "skin-validator.console.log") `
        -JournalPath $journalPath -RunId $runId -Stage "skin_validator"
    if ($skinResult.ExitCode -ne 0) {
        throw "PCK skin contract failed with exit code $($skinResult.ExitCode)."
    }
    if ($skinResult.Combined -notmatch 'Godot 4\.5\.1, pack format 3') {
        throw "PCK header is not Godot 4.5.1 / pack format 3."
    }

    # Layer 3: build an exact manifest from the current localization and art facts.
    $localization = @()
    $expectedFileCounts = [ordered]@{
        "cards.json" = 188
        "powers.json" = 69
        "characters.json" = 20
        "card_keywords.json" = 10
        "relics.json" = 3
        "ancients.json" = 24
    }

    foreach ($locale in @("eng", "zhs")) {
        $localeTotal = 0
        foreach ($fileName in $expectedFileCounts.Keys) {
            $sourcePath = Join-Path $repoFullPath "Vivhite\Vivhite\localization\$locale\$fileName"
            Assert-FileExists -Path $sourcePath -Label "$locale localization"
            $sourceText = [IO.File]::ReadAllText($sourcePath, $strictUtf8)
            $document = $sourceText | ConvertFrom-Json
            $keyCount = @($document.PSObject.Properties).Count
            $expectedCount = [int]$expectedFileCounts[$fileName]
            if ($keyCount -ne $expectedCount) {
                throw "$locale/$fileName source count is $keyCount; expected $expectedCount."
            }
            $expectedEmptyValues = if ($fileName -eq "ancients.json") { 18 } else { 0 }
            $actualEmptyValues = @($document.PSObject.Properties | Where-Object {
                $_.Value -is [string] -and ([string]$_.Value).Length -eq 0
            }).Count
            if ($actualEmptyValues -ne $expectedEmptyValues) {
                throw (
                    "$locale/$fileName source intentional-empty count is $actualEmptyValues; " +
                    "expected $expectedEmptyValues.")
            }

            $localeTotal += $keyCount
            $localization += [ordered]@{
                locale = $locale
                path = "res://Vivhite/localization/$locale/$fileName"
                keys = $expectedCount
                intentional_empty_values = $expectedEmptyValues
                sha256 = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
            }
        }

        if ($localeTotal -ne 314) {
            throw "$locale source localization total is $localeTotal; expected 314."
        }
    }

    $auditText = [IO.File]::ReadAllText($artAudit, $strictUtf8)
    $cards = @(Get-AuditNames -AuditText $auditText -Name "CARD_NAMES")
    $powers = @(Get-AuditNames -AuditText $auditText -Name "POWER_NAMES")
    $relics = @(Get-AuditNames -AuditText $auditText -Name "RELIC_NAMES")
    $energy = @(Get-AuditNames -AuditText $auditText -Name "ENERGY_NAMES")
    if ($cards.Count -ne 61 -or $powers.Count -ne 19 -or $relics.Count -ne 2 -or $energy.Count -ne 6) {
        throw (
            "Unexpected art catalog: cards=$($cards.Count), powers=$($powers.Count), " +
            "relics=$($relics.Count), energy=$($energy.Count).")
    }

    $art = @()
    foreach ($name in $cards) {
        $art += [ordered]@{
            category = "card"
            path = "res://Vivhite/images/cards/$name.png"
            width = 1000
            height = 760
        }
    }
    foreach ($name in $powers) {
        $art += [ordered]@{
            category = "power"
            path = "res://Vivhite/images/powers/$name.png"
            width = 256
            height = 256
        }
    }
    foreach ($name in $relics) {
        $art += [ordered]@{
            category = "crown"
            path = "res://Vivhite/images/relics/$name.png"
            width = 256
            height = 256
        }
    }
    foreach ($name in $energy) {
        $art += [ordered]@{
            category = "energy"
            path = "res://Vivhite/images/characters/$name.png"
            width = 256
            height = 256
        }
    }
    $art += [ordered]@{
        category = "energy"
        path = "res://Vivhite/images/characters/energy_text.png"
        width = 24
        height = 24
    }
    $art += [ordered]@{
        category = "vfx"
        path = "res://Vivhite/skins/ironclad/scenes/vfx/vivhite_eye_lens_glint.png"
        width = 512
        height = 512
    }
    $art += [ordered]@{
        category = "vfx"
        path = "res://Vivhite/skins/ironclad/transitions/vivhite_character_select_transition.png"
        width = 2560
        height = 1200
    }
    $art += [ordered]@{
        category = "vfx"
        path = "res://Vivhite/images/vfx/vivhite_card_trail_mathematical_star_0194.png"
        width = 256
        height = 256
    }
    if ($art.Count -ne 92) {
        throw "Runtime art manifest contains $($art.Count) entries; expected 92."
    }

    $manifest = [ordered]@{
        localization = $localization
        art = $art
    }
    Write-TrackedUtf8File -Path $manifestPath `
        -Content ($manifest | ConvertTo-Json -Depth 8) -WithBom $false `
        -JournalPath $journalPath -RunId $runId `
        -Operation "temporary_manifest_create"

    Write-TrackedUtf8File -Path $runtimeValidatorPath -WithBom $false `
        -JournalPath $journalPath -RunId $runId `
        -Operation "temporary_runtime_validator_create" -Content @'
extends SceneTree


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	if args.size() != 2:
		printerr("[FAIL] expected: <pck> <manifest>")
		quit(2)
		return

	var pck_path := args[0]
	var manifest_path := args[1]
	if not ProjectSettings.load_resource_pack(pck_path, true):
		printerr("[FAIL] could not mount PCK: %s" % pck_path)
		quit(3)
		return

	var manifest_text := FileAccess.get_file_as_string(manifest_path)
	var manifest = JSON.parse_string(manifest_text)
	if typeof(manifest) != TYPE_DICTIONARY:
		printerr("[FAIL] invalid expected manifest")
		quit(3)
		return

	var errors: Array[String] = []
	var expected_locale_keys := {
		"cards.json": 188,
		"powers.json": 69,
		"characters.json": 20,
		"card_keywords.json": 10,
		"relics.json": 3,
		"ancients.json": 24,
	}
	var expected_locale_empty_values := {
		"cards.json": 0,
		"powers.json": 0,
		"characters.json": 0,
		"card_keywords.json": 0,
		"relics.json": 0,
		"ancients.json": 18,
	}
	var locale_counts := {"eng": 0, "zhs": 0}
	var locale_files := {"eng": 0, "zhs": 0}
	var locale_text := {"eng": "", "zhs": ""}
	var seen_locale_files := {"eng": {}, "zhs": {}}

	for entry_value in manifest["localization"]:
		var entry: Dictionary = entry_value
		var locale := str(entry["locale"])
		var resource_path := str(entry["path"])
		if not locale_counts.has(locale):
			errors.append("unexpected localization locale: %s" % locale)
			continue
		var file_name := resource_path.get_file()
		if not expected_locale_keys.has(file_name):
			errors.append("unexpected localization file: %s" % resource_path)
			continue
		var expected_keys := int(entry["keys"])
		if expected_keys != int(expected_locale_keys[file_name]):
			errors.append(
				"manifest key contract is wrong: %s has %d, expected %d"
				% [resource_path, expected_keys, int(expected_locale_keys[file_name])]
			)
		var expected_empty_values := int(entry.get("intentional_empty_values", -1))
		if expected_empty_values != int(expected_locale_empty_values[file_name]):
			errors.append(
				"manifest intentional-empty contract is wrong: %s has %d, expected %d"
				% [
					resource_path,
					expected_empty_values,
					int(expected_locale_empty_values[file_name]),
				]
			)
		var locale_seen: Dictionary = seen_locale_files[locale]
		if locale_seen.has(file_name):
			errors.append("duplicate localization file: %s" % resource_path)
			continue
		locale_seen[file_name] = true
		if not FileAccess.file_exists(resource_path):
			errors.append("missing localization file: %s" % resource_path)
			continue

		var actual_hash := FileAccess.get_sha256(resource_path).to_lower()
		var expected_hash := str(entry["sha256"]).to_lower()
		if actual_hash != expected_hash:
			errors.append(
				"localization bytes differ from source: %s (%s != %s)"
				% [resource_path, actual_hash, expected_hash]
			)

		var raw := FileAccess.get_file_as_string(resource_path)
		var parsed = JSON.parse_string(raw)
		if typeof(parsed) != TYPE_DICTIONARY:
			errors.append("invalid localization JSON: %s" % resource_path)
			continue

		if parsed.size() != expected_keys:
			errors.append(
				"wrong key count: %s has %d, expected %d"
				% [resource_path, parsed.size(), expected_keys]
			)

		locale_counts[locale] = int(locale_counts.get(locale, 0)) + parsed.size()
		locale_files[locale] = int(locale_files.get(locale, 0)) + 1
		var actual_empty_values := 0
		for key_value in parsed.keys():
			var key := str(key_value)
			var value := str(parsed[key_value])
			if value.is_empty():
				actual_empty_values += 1
			locale_text[locale] = str(locale_text.get(locale, "")) + "\n" + value
			if value.strip_edges() == key:
				errors.append("raw localization key echo: %s" % key)
			if value.to_upper().contains("NOPE"):
				errors.append("NOPE text found in localization value: %s" % key)
		if actual_empty_values != expected_empty_values:
			errors.append(
				"wrong intentional-empty count: %s has %d, expected %d"
				% [resource_path, actual_empty_values, expected_empty_values]
			)

	for locale_value in seen_locale_files.keys():
		var locale := str(locale_value)
		var locale_seen: Dictionary = seen_locale_files[locale]
		for file_name_value in expected_locale_keys.keys():
			var file_name := str(file_name_value)
			if not locale_seen.has(file_name):
				errors.append(
					"missing localization manifest entry: %s/%s" % [locale, file_name]
				)

	var eng_text := str(locale_text["eng"])
	var zhs_text := str(locale_text["zhs"])
	if int(locale_counts["eng"]) != 314 or int(locale_files["eng"]) != 6:
		errors.append("English localization is not 314 keys across 6 files")
	if int(locale_counts["zhs"]) != 314 or int(locale_files["zhs"]) != 6:
		errors.append("Chinese localization is not 314 keys across 6 files")
	if not eng_text.contains("Cough") or not eng_text.contains("Margin"):
		errors.append("English Cough/Margin terminology is missing")
	if eng_text.contains("Life Calculation"):
		errors.append("retired English term Life Calculation remains")
	if not zhs_text.contains("謦欬") or not zhs_text.contains("余裕"):
		errors.append("Chinese 謦欬/余裕 terminology is missing")
	for retired in ["生命演算", "余量", "咳血"]:
		if zhs_text.contains(retired):
			errors.append("retired Chinese term remains: %s" % retired)

	var loaded_counts := {"card": 0, "power": 0, "crown": 0, "energy": 0, "vfx": 0}
	for entry_value in manifest["art"]:
		var entry: Dictionary = entry_value
		var category := str(entry["category"])
		var resource_path := str(entry["path"])
		var import_path := resource_path + ".import"
		if not FileAccess.file_exists(import_path):
			errors.append("missing packed import metadata: %s" % import_path)
			continue

		var import_text := FileAccess.get_file_as_string(import_path)
		var expected_target_token := resource_path.get_file() + "-"
		if not import_text.contains("type=\"CompressedTexture2D\""):
			errors.append("wrong import type: %s" % import_path)
		if not import_text.contains(expected_target_token):
			errors.append(
				"import target is not dedicated to %s: %s"
				% [resource_path, import_path]
			)
		if import_text.to_upper().contains("NOPE"):
			errors.append("NOPE import target found: %s" % import_path)

		if not ResourceLoader.exists(resource_path):
			errors.append("runtime texture does not resolve: %s" % resource_path)
			continue
		var resource := ResourceLoader.load(
			resource_path,
			"Texture2D",
			ResourceLoader.CACHE_MODE_IGNORE
		)
		if resource == null or not (resource is Texture2D):
			errors.append("runtime texture failed to load: %s" % resource_path)
			continue

		var texture := resource as Texture2D
		var expected_width := int(entry["width"])
		var expected_height := int(entry["height"])
		if texture.get_width() != expected_width or texture.get_height() != expected_height:
			errors.append(
				"wrong runtime size: %s is %dx%d, expected %dx%d"
				% [
					resource_path,
					texture.get_width(),
					texture.get_height(),
					expected_width,
					expected_height,
				]
			)
			continue

		var image := texture.get_image()
		if image == null or image.is_empty():
			errors.append("runtime texture is undecodable: %s" % resource_path)
			continue
		if image.is_compressed():
			var decompress_error := image.decompress()
			if decompress_error != OK:
				errors.append(
					"runtime texture decompression failed: %s (%s)"
					% [resource_path, error_string(decompress_error)]
				)
				continue
		loaded_counts[category] = int(loaded_counts.get(category, 0)) + 1

	var expected_counts := {"card": 61, "power": 19, "crown": 2, "energy": 7, "vfx": 3}
	for category in expected_counts:
		if int(loaded_counts.get(category, 0)) != int(expected_counts[category]):
			errors.append(
				"%s runtime count is %d, expected %d"
				% [
					category,
					int(loaded_counts.get(category, 0)),
					int(expected_counts[category]),
				]
			)

	if not errors.is_empty():
		for message in errors:
			printerr("[FAIL] %s" % message)
		quit(4)
		return

	print("[PASS] localization eng: 314/314 keys; 6/6 files byte-identical; ancients 24 keys / 18 intentional empty overrides; Cough/Margin present")
	print("[PASS] localization zhs: 314/314 keys; 6/6 files byte-identical; ancients 24 keys / 18 intentional empty overrides; 謦欬/余裕 present")
	print("[PASS] cards: 61/61 packed imports resolve and decode")
	print("[PASS] powers: 19/19 packed imports resolve and decode")
	print("[PASS] crown: 2/2 packed imports resolve and decode")
	print("[PASS] energy: 7/7 packed imports resolve and decode")
	print("[PASS] VFX: 3/3 eye, character-select transition, and Vivhite-only card trail")
	print("[PASS] runtime art: 92/92")
	print("[PASS] NOPE fallback guard: 0 missing, 0 undecodable, 0 generic/NOPE import targets")
	quit(0)
'@

    # Layer 4: mount only the PCK into an otherwise empty Godot project.
    $mountedResult = Invoke-CapturedProcess -FilePath $godotFullPath `
        -ArgumentList @(
            "--headless",
            "--path", $workRoot,
            "--log-file", (Join-Path $gateRoot "mounted-pck.godot.log"),
            "--script", $runtimeValidatorPath,
            "--",
            $pckFullPath,
            $manifestPath
        ) `
        -WorkingDirectory $workRoot `
        -ConsoleLogPath (Join-Path $gateRoot "mounted-pck.console.log") `
        -JournalPath $journalPath -RunId $runId -Stage "mounted_pck"
    if ($mountedResult.ExitCode -ne 0) {
        throw "Mounted-PCK runtime validation failed with exit code $($mountedResult.ExitCode)."
    }

    $validationSucceeded = $true
}
catch {
    $validationError = $_
    Save-FailureEvidence -Stage "validation" -ErrorRecord $_
}
finally {
    if ($null -ne $pckHashBefore) {
        try {
            Assert-FileExists -Path $pckFullPath -Label "PCK after validation"
            $pckHashAfter = (Get-FileHash -LiteralPath $pckFullPath -Algorithm SHA256).Hash
            $hashEvidence = [ordered]@{
                run_id = $runId
                pck_path = $pckFullPath
                sha256_before = $pckHashBefore
                sha256_after = $pckHashAfter
                unchanged = ($pckHashBefore -eq $pckHashAfter)
                finished_utc = [DateTime]::UtcNow.ToString("O")
            }
            Write-TrackedUtf8File -Path (Join-Path $gateRoot "pck-immutability.json") `
                -Content ($hashEvidence | ConvertTo-Json -Depth 3) -WithBom $true `
                -JournalPath $journalPath -RunId $runId `
                -Operation "temporary_immutability_evidence_create"
            if ($pckHashBefore -ne $pckHashAfter) {
                throw "PCK changed during read-only validation: $pckHashBefore -> $pckHashAfter"
            }
            Write-Host "[PASS] PCK remained immutable: SHA256=$pckHashAfter"
        }
        catch {
            $immutabilityError = $_
            Save-FailureEvidence -Stage "immutability" -ErrorRecord $_
        }
    }

    if ($validationSucceeded -and $null -eq $validationError -and $null -eq $immutabilityError) {
        try {
            foreach ($temporaryPath in @($workRoot, $gateRoot)) {
                if (-not $temporaryPath.StartsWith($tempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Refusing unsafe cleanup outside repository temp root: $temporaryPath"
                }
            }
            Remove-TrackedPath -Path $workRoot -JournalPath $journalPath `
                -RunId $runId -Operation "temporary_work_cleanup"
            Remove-TrackedPath -Path $gateRoot -JournalPath $journalPath `
                -RunId $runId -Operation "temporary_evidence_cleanup"
        }
        catch {
            $cleanupError = $_
            Save-FailureEvidence -Stage "temporary_cleanup" -ErrorRecord $_
        }
    }

    if ($validationSucceeded -and $null -eq $validationError -and
        $null -eq $immutabilityError -and $null -eq $cleanupError) {
        Write-GateEvent -JournalPath $journalPath -RunId $runId `
            -Operation "gate" -Status "success" -Target $pckFullPath
        Write-Host "[PASS] FINAL VIVHITE PCK CONTENT GATE"
    }
    else {
        Write-GateEvent -JournalPath $journalPath -RunId $runId `
            -Operation "gate" -Status "failure" -Target $pckFullPath `
            -Message "Evidence retained at $gateRoot; work retained at $workRoot"
        Write-Warning (
            "Vivhite PCK verification failed; evidence retained at: $gateRoot; " +
            "work directory: $workRoot")
    }
}

if ($null -ne $validationError) {
    throw $validationError
}
if ($null -ne $immutabilityError) {
    throw $immutabilityError
}
if ($null -ne $cleanupError) {
    throw $cleanupError
}
