<#
.SYNOPSIS
Runs dependency-free behavioral tests for Verify-VivhitePck.ps1 on Windows PowerShell 5.1.

.DESCRIPTION
Builds a synthetic repository and a GUI-subsystem fake Godot executable. No real
game, PCK, Godot project, deployment, or network resource is used. The suite
proves explicit process waiting, UTF-8 Chinese round trips, retained evidence for
temporary creation failures, and retained evidence for real cleanup failures.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

$repoFullPath = [IO.Path]::GetFullPath($RepoRoot)
$target = Join-Path $repoFullPath "tools\test\Verify-VivhitePck.ps1"
$documentPath = Join-Path $repoFullPath "docs\2026-08-31-白绮PCK四层只读门禁.md"
$thisScriptPath = $MyInvocation.MyCommand.Path
$powershellExe = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
$failures = New-Object "System.Collections.Generic.List[string]"

function Assert-Test {
    param(
        [Parameter(Mandatory = $true)][bool]$Condition,
        [Parameter(Mandatory = $true)][string]$Message
    )
    if (-not $Condition) {
        throw $Message
    }
}

function Assert-TextContains {
    param(
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Text.IndexOf($Expected, [StringComparison]::Ordinal) -lt 0) {
        throw "$Label does not contain '$Expected'."
    }
}

function Invoke-TestCase {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Body
    )
    try {
        $Body.Invoke()
        Write-Host "[PASS] $Name"
    }
    catch {
        $failures.Add("$Name`: $($_.Exception.Message)")
        Write-Host "[FAIL] $Name`: $($_.Exception.Message)" -ForegroundColor Red
    }
}

function Write-TestUtf8 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Content,
        [bool]$WithBom = $false
    )
    $encoding = New-Object System.Text.UTF8Encoding($WithBom, $true)
    [IO.File]::WriteAllText($Path, $Content, $encoding)
}

function ConvertTo-TestCommandLineArgument {
    param([Parameter(Mandatory = $true)][AllowEmptyString()][string]$Value)
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

function Start-TestProcess {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [hashtable]$Environment = @{}
    )
    $startInfo = New-Object Diagnostics.ProcessStartInfo
    $startInfo.FileName = $FilePath
    $startInfo.Arguments = (@($ArgumentList | ForEach-Object {
        ConvertTo-TestCommandLineArgument -Value ([string]$_)
    }) -join ' ')
    $startInfo.WorkingDirectory = $WorkingDirectory
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $utf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $startInfo.StandardOutputEncoding = $utf8
    $startInfo.StandardErrorEncoding = $utf8
    foreach ($name in $Environment.Keys) {
        $startInfo.EnvironmentVariables[[string]$name] = [string]$Environment[$name]
    }
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $startInfo
    $stopwatch = [Diagnostics.Stopwatch]::StartNew()
    if (-not $process.Start()) {
        throw "Process.Start returned false for '$FilePath'."
    }
    return [pscustomobject]@{
        Process = $process
        StdOutTask = $process.StandardOutput.ReadToEndAsync()
        StdErrTask = $process.StandardError.ReadToEndAsync()
        Stopwatch = $stopwatch
    }
}

function Complete-TestProcess {
    param([Parameter(Mandatory = $true)]$Handle)
    try {
        $Handle.Process.WaitForExit()
        $stdout = $Handle.StdOutTask.GetAwaiter().GetResult()
        $stderr = $Handle.StdErrTask.GetAwaiter().GetResult()
        $Handle.Process.WaitForExit()
        $Handle.Stopwatch.Stop()
        return [pscustomobject]@{
            ExitCode = $Handle.Process.ExitCode
            StdOut = $stdout
            StdErr = $stderr
            DurationMilliseconds = $Handle.Stopwatch.ElapsedMilliseconds
        }
    }
    finally {
        $Handle.Process.Dispose()
    }
}

function New-GdArray {
    param(
        [Parameter(Mandatory = $true)][string]$Prefix,
        [Parameter(Mandatory = $true)][int]$Count
    )
    return (@(0..($Count - 1) | ForEach-Object { '"' + $Prefix + $_ + '"' }) -join ', ')
}

function Get-VerifierArguments {
    param(
        [Parameter(Mandatory = $true)][string]$RunId,
        [Parameter(Mandatory = $true)][string]$FixtureRoot,
        [Parameter(Mandatory = $true)][string]$PckPath,
        [Parameter(Mandatory = $true)][string]$FakeGodot
    )
    return @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $target,
        "-RepoRoot", $FixtureRoot, "-PckPath", $PckPath,
        "-GodotExe", $FakeGodot, "-PowerShellExe", $powershellExe,
        "-EvidenceRunId", $RunId
    )
}

function Read-JournalRecords {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$RunId
    )
    $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
    $text = [IO.File]::ReadAllText($Path, $strictUtf8)
    return @($text -split "`r?`n" |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) } |
        ForEach-Object { $_ | ConvertFrom-Json } |
        Where-Object { $_.run_id -eq $RunId })
}

function Get-RunPath {
    param(
        [Parameter(Mandatory = $true)][string]$FixtureRoot,
        [Parameter(Mandatory = $true)][string]$Prefix,
        [Parameter(Mandatory = $true)][string]$RunId
    )
    return Join-Path $FixtureRoot (".tmp\" + $Prefix + $RunId)
}

Assert-Test -Condition ([IO.File]::Exists($target)) -Message "Verification script is missing: $target"
$repoTemp = [IO.Path]::GetFullPath((Join-Path $repoFullPath ".tmp")).TrimEnd('\', '/')
[void][IO.Directory]::CreateDirectory($repoTemp)
$testRoot = [IO.Path]::GetFullPath((Join-Path $repoTemp ("vivhite-pck-tests-" + [Guid]::NewGuid().ToString("N"))))
$repoTempPrefix = $repoTemp + [IO.Path]::DirectorySeparatorChar
Assert-Test -Condition $testRoot.StartsWith($repoTempPrefix, [StringComparison]::OrdinalIgnoreCase) `
    -Message "Unsafe test root: $testRoot"
[void][IO.Directory]::CreateDirectory($testRoot)

$fixtureRoot = Join-Path $testRoot "synthetic repo with spaces"
$fixtureTemp = Join-Path $fixtureRoot ".tmp"
$fixtureVivhite = Join-Path $fixtureRoot "Vivhite"
$fixtureLocalization = Join-Path $fixtureVivhite "Vivhite\localization"
$fixtureSkinTools = Join-Path $fixtureVivhite "tools"
$fixtureArtTools = Join-Path $fixtureRoot "tools\art"
$fixtureBuild = Join-Path $testRoot "fake-godot-build"
foreach ($directory in @($fixtureRoot, $fixtureTemp, $fixtureVivhite, $fixtureLocalization,
    $fixtureSkinTools, $fixtureArtTools, $fixtureBuild)) {
    [void][IO.Directory]::CreateDirectory($directory)
}

$pckPath = Join-Path $fixtureRoot "Vivhite synthetic.pck"
$fakeGodot = Join-Path $fixtureBuild "Fake Godot 4.5.1.exe"
$fakeGodotSource = Join-Path $fixtureBuild "FakeGodot.cs"
$fakeCompiler = Join-Path $fixtureBuild "CompileFakeGodot.ps1"
$markerPath = Join-Path $fixtureRoot "fake-godot-marker.txt"
$journalPath = Join-Path $fixtureTemp "vivhite-pck-gate-events.jsonl"

try {
    Write-TestUtf8 -Path (Join-Path $fixtureRoot "AGENTS.md") -Content "synthetic test repository"
    [IO.File]::WriteAllBytes($pckPath, [byte[]](0..63))
    Write-TestUtf8 -Path (Join-Path $fixtureVivhite "project.godot") -Content "config_version=5"

    $skinValidator = @'
[CmdletBinding()]
param([string]$ProjectDir, [string]$Phase, [string]$PckPath, [string]$RuntimeLayout)
Write-Output "[PASS] Godot 4.5.1, pack format 3"
exit 0
'@
    Write-TestUtf8 -Path (Join-Path $fixtureSkinTools "Validate-IroncladSkin.ps1") `
        -Content $skinValidator -WithBom $true

    $auditText = @"
const CARD_NAMES := [$(New-GdArray -Prefix "Card" -Count 61)]
const POWER_NAMES := [$(New-GdArray -Prefix "Power" -Count 19)]
const RELIC_NAMES := [$(New-GdArray -Prefix "Crown" -Count 2)]
const ENERGY_NAMES := [$(New-GdArray -Prefix "Energy" -Count 6)]
"@
    Write-TestUtf8 -Path (Join-Path $fixtureArtTools "audit_vivhite_runtime_art.gd") -Content $auditText

    $fileCounts = [ordered]@{
        "cards.json" = 188
        "powers.json" = 69
        "characters.json" = 19
        "card_keywords.json" = 10
        "relics.json" = 3
    }
    foreach ($locale in @("eng", "zhs")) {
        $localeDirectory = Join-Path $fixtureLocalization $locale
        [void][IO.Directory]::CreateDirectory($localeDirectory)
        foreach ($fileName in $fileCounts.Keys) {
            $document = [ordered]@{}
            for ($index = 0; $index -lt [int]$fileCounts[$fileName]; $index += 1) {
                $key = ("TEST_{0}_{1}_{2:D3}" -f $locale, $fileName.Replace('.', '_'), $index)
                $value = "Synthetic value $index"
                if ($fileName -eq "cards.json" -and $index -eq 0) {
                    $value = if ($locale -eq "eng") { "Cough Margin" } else { "謦欬 余裕" }
                }
                $document[$key] = $value
            }
            Write-TestUtf8 -Path (Join-Path $localeDirectory $fileName) `
                -Content ($document | ConvertTo-Json -Depth 4)
        }
    }

    Write-TestUtf8 -Path $fakeGodotSource -Content @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
public static class FakeGodot
{
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int handleKind);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool WriteFile(
        IntPtr handle,
        byte[] buffer,
        uint bytesToWrite,
        out uint bytesWritten,
        IntPtr overlapped);

    private static void WriteUtf8(int handleKind, string value)
    {
        byte[] bytes = new UTF8Encoding(false).GetBytes(value + Environment.NewLine);
        uint written;
        WriteFile(GetStdHandle(handleKind), bytes, (uint)bytes.Length, out written, IntPtr.Zero);
    }

    [STAThread]
    public static int Main(string[] args)
    {
        int delay = 0;
        Int32.TryParse(Environment.GetEnvironmentVariable("VIVHITE_FAKE_GODOT_DELAY_MS"), out delay);
        if (delay > 0) Thread.Sleep(delay);
        string marker = Environment.GetEnvironmentVariable("VIVHITE_FAKE_GODOT_MARKER");
        if (!String.IsNullOrEmpty(marker))
            File.AppendAllText(marker, String.Join("|", args) + Environment.NewLine, new UTF8Encoding(false));
        WriteUtf8(-11, "\u4F2A Godot \u5DF2\u5B8C\u6210\uFF1A\u8B26\u6B2C / \u4F59\u88D5");
        bool mounted = false;
        foreach (string argument in args)
            if (argument.EndsWith("verify_pck.gd", StringComparison.OrdinalIgnoreCase)) mounted = true;
        if (mounted && String.Equals(Environment.GetEnvironmentVariable("VIVHITE_FAKE_GODOT_FAIL_PHASE"),
            "mounted", StringComparison.OrdinalIgnoreCase))
        {
            WriteUtf8(-12, "\u4F2A Godot \u6302\u8F7D\u5931\u8D25\u8BC1\u636E\uFF1A\u8B26\u6B2C / \u4F59\u88D5");
            return 23;
        }
        return 0;
    }
}
'@
    Write-TestUtf8 -Path $fakeCompiler -WithBom $true -Content @'
[CmdletBinding()]
param([string]$SourcePath, [string]$OutputPath)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -Path $SourcePath -OutputAssembly $OutputPath -OutputType WindowsApplication
'@
    $compileHandle = Start-TestProcess -FilePath $powershellExe `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $fakeCompiler,
            "-SourcePath", $fakeGodotSource, "-OutputPath", $fakeGodot) `
        -WorkingDirectory $fixtureBuild
    $compileResult = Complete-TestProcess -Handle $compileHandle
    Assert-Test -Condition ($compileResult.ExitCode -eq 0) `
        -Message "Could not compile fake Godot: $($compileResult.StdErr)"
    Assert-Test -Condition ([IO.File]::Exists($fakeGodot)) -Message "Fake Godot executable is missing."

    Invoke-TestCase -Name "UTF-8 BOM and Windows PowerShell parsing" -Body {
        $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
        foreach ($path in @($target, $thisScriptPath, $documentPath)) {
            Assert-Test -Condition ([IO.File]::Exists($path)) -Message "Expected file is missing: $path"
            $bytes = [IO.File]::ReadAllBytes($path)
            $hasBom = $bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and
                $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF
            Assert-Test -Condition $hasBom -Message "UTF-8 BOM is missing: $path"
            [void][IO.File]::ReadAllText($path, $strictUtf8)
        }
        $targetText = [IO.File]::ReadAllText($target, $strictUtf8)
        Assert-TextContains -Text $targetText -Expected "謦欬" -Label "Verifier source"
        Assert-TextContains -Text $targetText -Expected "余裕" -Label "Verifier source"
        $tokens = $null
        $parseErrors = $null
        $ast = [Management.Automation.Language.Parser]::ParseFile($target, [ref]$tokens, [ref]$parseErrors)
        Assert-Test -Condition (@($parseErrors).Count -eq 0) `
            -Message "Verifier has PowerShell parse errors: $(@($parseErrors | ForEach-Object { $_.Message }) -join '; ')"
        $ampersandCommands = @($ast.FindAll({
            param($node)
            $node -is [Management.Automation.Language.CommandAst] -and
                $node.InvocationOperator -eq [Management.Automation.Language.TokenKind]::Ampersand
        }, $true))
        Assert-Test -Condition ($ampersandCommands.Count -eq 0) `
            -Message "Verifier still contains call-operator process invocation."
        $help = Get-Help -Name $target -Full
        foreach ($requiredParameter in @("RepoRoot", "PckPath", "GodotExe", "EvidenceRunId")) {
            Assert-Test -Condition (@($help.parameters.parameter |
                Where-Object Name -eq $requiredParameter).Count -eq 1) `
                -Message "Get-Help does not expose parameter: $requiredParameter"
        }
    }

    Invoke-TestCase -Name "GUI Godot process is actually awaited" -Body {
        $runId = "wait" + [Guid]::NewGuid().ToString("N")
        if ([IO.File]::Exists($markerPath)) { Remove-Item -LiteralPath $markerPath -Force }
        $handle = Start-TestProcess -FilePath $powershellExe `
            -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot `
            -Environment @{ VIVHITE_FAKE_GODOT_DELAY_MS = "650"; VIVHITE_FAKE_GODOT_MARKER = $markerPath }
        $result = Complete-TestProcess -Handle $handle
        Assert-Test -Condition ($result.ExitCode -eq 0) `
            -Message "Successful synthetic gate exited $($result.ExitCode): $($result.StdErr)"
        Assert-Test -Condition ($result.DurationMilliseconds -ge 1100) `
            -Message "Verifier returned before both delayed GUI processes exited: $($result.DurationMilliseconds) ms"
        $markerLines = @([IO.File]::ReadAllLines($markerPath))
        Assert-Test -Condition ($markerLines.Count -eq 2) `
            -Message "Expected two completed fake Godot phases, found $($markerLines.Count)."
        $evidenceRoot = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-gate-" -RunId $runId
        $workRoot = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-work-" -RunId $runId
        Assert-Test -Condition (-not [IO.Directory]::Exists($evidenceRoot)) `
            -Message "Successful run retained evidence directory: $evidenceRoot"
        Assert-Test -Condition (-not [IO.Directory]::Exists($workRoot)) `
            -Message "Successful run retained work directory: $workRoot"
        $events = @(Read-JournalRecords -Path $journalPath -RunId $runId)
        Assert-Test -Condition (@($events | Where-Object {
            $_.operation -eq "process_source_art" -and $_.status -eq "exited"
        }).Count -eq 1) -Message "Source-art process exit was not journaled."
        Assert-Test -Condition (@($events | Where-Object {
            $_.operation -eq "process_mounted_pck" -and $_.status -eq "exited"
        }).Count -eq 1) -Message "Mounted-PCK process exit was not journaled."
    }

    Invoke-TestCase -Name "Chinese survives PS5.1, process capture, and generated GDScript" -Body {
        $runId = "utf8" + [Guid]::NewGuid().ToString("N")
        $handle = Start-TestProcess -FilePath $powershellExe `
            -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot `
            -Environment @{ VIVHITE_FAKE_GODOT_DELAY_MS = "20"; VIVHITE_FAKE_GODOT_MARKER = $markerPath;
                VIVHITE_FAKE_GODOT_FAIL_PHASE = "mounted" }
        $result = Complete-TestProcess -Handle $handle
        Assert-Test -Condition ($result.ExitCode -ne 0) -Message "Mounted-phase failure unexpectedly passed."
        $evidenceRoot = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-gate-" -RunId $runId
        $workRoot = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-work-" -RunId $runId
        $validatorPath = Join-Path $workRoot "verify_pck.gd"
        $consolePath = Join-Path $evidenceRoot "mounted-pck.console.log"
        $failurePath = Join-Path $evidenceRoot "failure.json"
        foreach ($path in @($validatorPath, $consolePath, $failurePath)) {
            Assert-Test -Condition ([IO.File]::Exists($path)) -Message "Failure evidence is missing: $path"
        }
        $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
        $validatorText = [IO.File]::ReadAllText($validatorPath, $strictUtf8)
        $consoleText = [IO.File]::ReadAllText($consolePath, $strictUtf8)
        $failureText = [IO.File]::ReadAllText($failurePath, $strictUtf8)
        foreach ($expected in @("謦欬", "余裕")) {
            Assert-TextContains -Text $validatorText -Expected $expected -Label "Generated GDScript"
            Assert-TextContains -Text $consoleText -Expected $expected -Label "Captured process log"
        }
        Assert-TextContains -Text $failureText -Expected "Mounted-PCK runtime validation failed" `
            -Label "Failure JSON"
        foreach ($mojibake in @("璎︽", "浣欒", "鐢熷")) {
            Assert-Test -Condition ($validatorText.IndexOf($mojibake, [StringComparison]::Ordinal) -lt 0) `
                -Message "Generated GDScript contains mojibake: $mojibake"
        }
        $consoleBytes = [IO.File]::ReadAllBytes($consolePath)
        Assert-Test -Condition ($consoleBytes[0] -eq 0xEF -and $consoleBytes[1] -eq 0xBB -and
            $consoleBytes[2] -eq 0xBF) -Message "Captured process evidence is not UTF-8 with BOM."
    }

    Invoke-TestCase -Name "Temporary directory creation failure is retained as evidence" -Body {
        $runId = "create" + [Guid]::NewGuid().ToString("N")
        $blockedWorkPath = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-work-" -RunId $runId
        Write-TestUtf8 -Path $blockedWorkPath -Content "blocks Directory.CreateDirectory"
        $handle = Start-TestProcess -FilePath $powershellExe `
            -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot
        $result = Complete-TestProcess -Handle $handle
        Assert-Test -Condition ($result.ExitCode -ne 0) -Message "Blocked work directory unexpectedly passed."
        $evidenceRoot = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-gate-" -RunId $runId
        Assert-Test -Condition ([IO.File]::Exists((Join-Path $evidenceRoot "failure.json"))) `
            -Message ("Creation failure did not retain failure.json. stdout={0} stderr={1}" -f
                $result.StdOut, $result.StdErr)
        $events = @(Read-JournalRecords -Path $journalPath -RunId $runId)
        Assert-Test -Condition (@($events | Where-Object {
            $_.operation -eq "temporary_work_directory_create" -and $_.status -eq "failure"
        }).Count -eq 1) -Message "Creation failure was not written to the lifecycle journal."
    }

    Invoke-TestCase -Name "Real locked-file cleanup failure is retained as evidence" -Body {
        $runId = "cleanup" + [Guid]::NewGuid().ToString("N")
        $workRoot = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-work-" -RunId $runId
        $projectPath = Join-Path $workRoot "project.godot"
        $lockStream = $null
        $handle = $null
        try {
            $handle = Start-TestProcess -FilePath $powershellExe `
                -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                    -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot `
                -Environment @{ VIVHITE_FAKE_GODOT_DELAY_MS = "500"; VIVHITE_FAKE_GODOT_MARKER = $markerPath }
            $deadline = [DateTime]::UtcNow.AddSeconds(10)
            while (-not [IO.File]::Exists($projectPath) -and [DateTime]::UtcNow -lt $deadline -and
                -not $handle.Process.HasExited) { Start-Sleep -Milliseconds 20 }
            Assert-Test -Condition ([IO.File]::Exists($projectPath)) `
                -Message "Verifier did not create the temporary project before timeout."
            $lockStream = [IO.File]::Open($projectPath, [IO.FileMode]::Open,
                [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
            $completionHandle = $handle
            $handle = $null
            $result = Complete-TestProcess -Handle $completionHandle
            Assert-Test -Condition ($result.ExitCode -ne 0) `
                -Message "Locked work file did not cause cleanup failure."
            $evidenceRoot = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-gate-" -RunId $runId
            $failurePath = Join-Path $evidenceRoot "failure.json"
            Assert-Test -Condition ([IO.File]::Exists($failurePath)) `
                -Message "Cleanup failure did not retain failure.json."
            $events = @(Read-JournalRecords -Path $journalPath -RunId $runId)
            Assert-Test -Condition (@($events | Where-Object {
                $_.operation -eq "temporary_work_cleanup" -and $_.status -eq "failure"
            }).Count -eq 1) -Message "Cleanup failure was not written to the lifecycle journal."
            $failureText = [IO.File]::ReadAllText($failurePath,
                (New-Object System.Text.UTF8Encoding($false, $true)))
            Assert-TextContains -Text $failureText -Expected "temporary_cleanup" -Label "Cleanup failure JSON"
        }
        finally {
            if ($null -ne $lockStream) { $lockStream.Dispose() }
            if ($null -ne $handle) {
                if (-not $handle.Process.HasExited) { $handle.Process.Kill() }
                [void](Complete-TestProcess -Handle $handle)
            }
        }
    }
}
finally {
    if ([IO.Directory]::Exists($testRoot)) {
        $resolvedTestRoot = [IO.Path]::GetFullPath($testRoot)
        if (-not $resolvedTestRoot.StartsWith($repoTempPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing unsafe test cleanup outside repository temp root: $resolvedTestRoot"
        }
        Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force -ErrorAction Stop
    }
}

if ($failures.Count -gt 0) {
    foreach ($failure in $failures) { Write-Host "[FAIL] $failure" -ForegroundColor Red }
    exit 1
}
Write-Host "[PASS] Verify-VivhitePck.ps1 behavioral contract"
