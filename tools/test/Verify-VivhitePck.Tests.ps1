<#
.SYNOPSIS
Runs dependency-free behavioral tests for Verify-VivhitePck.ps1 on Windows PowerShell 5.1.

.DESCRIPTION
Builds a synthetic repository, a controllable archive-backed PCK view, and a
GUI-subsystem fake Godot executable whose mounted phase performs the production-
equivalent localization validation against actual package bytes. No real game,
Godot project, deployment, or network resource is used. The suite proves the
exact 92/30/34 contract, all three named VFX imports, the six-file / 314-key
localization contract including ancients, explicit process waiting, UTF-8
Chinese round trips, and retained failure evidence.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression -ErrorAction Stop

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

function Write-IsolatedPckView {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$LocalizationRoot,
        [string]$MissingEntry = "",
        [string]$TamperedEntry = ""
    )

    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::Create,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None)
    $archive = $null
    try {
        $archive = New-Object IO.Compression.ZipArchive(
            $stream,
            [IO.Compression.ZipArchiveMode]::Create,
            $true)
        foreach ($locale in @("eng", "zhs")) {
            $localeDirectory = Join-Path $LocalizationRoot $locale
            foreach ($sourcePath in [IO.Directory]::GetFiles($localeDirectory, "*.json")) {
                $entryName = "Vivhite/localization/$locale/$([IO.Path]::GetFileName($sourcePath))"
                if ($entryName -eq $MissingEntry) {
                    continue
                }

                [byte[]]$bytes = [IO.File]::ReadAllBytes($sourcePath)
                if ($entryName -eq $TamperedEntry) {
                    $changedBytes = New-Object byte[] ($bytes.Length + 1)
                    [Array]::Copy($bytes, $changedBytes, $bytes.Length)
                    $changedBytes[$bytes.Length] = 0x0A
                    $bytes = $changedBytes
                }

                $entry = $archive.CreateEntry(
                    $entryName,
                    [IO.Compression.CompressionLevel]::NoCompression)
                $entryStream = $entry.Open()
                try {
                    $entryStream.Write($bytes, 0, $bytes.Length)
                }
                finally {
                    $entryStream.Dispose()
                }
            }
        }
    }
    finally {
        if ($null -ne $archive) { $archive.Dispose() }
        $stream.Dispose()
    }
}

function Get-IsolatedPckEntryState {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$EntryName
    )

    $stream = [IO.File]::Open(
        $Path,
        [IO.FileMode]::Open,
        [IO.FileAccess]::Read,
        [IO.FileShare]::Read)
    $archive = $null
    try {
        $archive = New-Object IO.Compression.ZipArchive(
            $stream,
            [IO.Compression.ZipArchiveMode]::Read,
            $true)
        $entry = $archive.GetEntry($EntryName)
        if ($null -eq $entry) {
            return [pscustomobject]@{ Exists = $false; Length = 0; Sha256 = "" }
        }

        $entryStream = $entry.Open()
        $memory = New-Object IO.MemoryStream
        try {
            $entryStream.CopyTo($memory)
            [byte[]]$bytes = $memory.ToArray()
        }
        finally {
            $memory.Dispose()
            $entryStream.Dispose()
        }

        $sha = [Security.Cryptography.SHA256]::Create()
        try {
            $hash = -join @($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString("x2") })
        }
        finally {
            $sha.Dispose()
        }
        return [pscustomobject]@{
            Exists = $true
            Length = $bytes.Length
            Sha256 = $hash
        }
    }
    finally {
        if ($null -ne $archive) { $archive.Dispose() }
        $stream.Dispose()
    }
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
$fixtureSkinContract = Join-Path $fixtureSkinTools "ironclad-skin.contract.json"
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
    Write-TestUtf8 -Path (Join-Path $fixtureVivhite "project.godot") -Content "config_version=5"

    $skinContract = [ordered]@{
        expectedRuntimeFileCount = 30
        combatRuntimeLayouts = @(
            [ordered]@{ name = "legacy-single-page"; expectedRuntimeFileCount = 30 },
            [ordered]@{ name = "v3-five-page"; expectedRuntimeFileCount = 34 }
        )
    }
    Write-TestUtf8 -Path $fixtureSkinContract -Content ($skinContract | ConvertTo-Json -Depth 4)

    $skinValidator = @'
[CmdletBinding()]
param([string]$ProjectDir, [string]$Phase, [string]$PckPath, [string]$RuntimeLayout)
$contract = Get-Content -LiteralPath (Join-Path $ProjectDir "tools\ironclad-skin.contract.json") -Raw |
    ConvertFrom-Json
$v3 = @($contract.combatRuntimeLayouts | Where-Object { $_.name -eq "v3-five-page" })
if ([int]$contract.expectedRuntimeFileCount -ne 30 -or $v3.Count -ne 1 -or
    [int]$v3[0].expectedRuntimeFileCount -ne 34) {
    Write-Error "Synthetic skin contract is not source=30, published=34."
    exit 24
}
if ($Phase -ne "Pck" -or $RuntimeLayout -ne "v3-five-page") {
    Write-Error "Synthetic skin validator received the wrong phase or runtime layout."
    exit 25
}
Write-Output "[PASS] skin source=30, published=34; Godot 4.5.1, pack format 3"
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
        "characters.json" = 20
        "card_keywords.json" = 10
        "relics.json" = 3
        "ancients.json" = 24
    }
    foreach ($locale in @("eng", "zhs")) {
        $localeDirectory = Join-Path $fixtureLocalization $locale
        [void][IO.Directory]::CreateDirectory($localeDirectory)
        foreach ($fileName in $fileCounts.Keys) {
            $document = [ordered]@{}
            for ($index = 0; $index -lt [int]$fileCounts[$fileName]; $index += 1) {
                $key = ("TEST_{0}_{1}_{2:D3}" -f $locale, $fileName.Replace('.', '_'), $index)
                $value = "Synthetic value $index"
                if ($fileName -eq "ancients.json" -and $index -lt 18) {
                    $value = ""
                }
                elseif ($fileName -eq "cards.json" -and $index -eq 0) {
                    $value = if ($locale -eq "eng") { "Cough Margin" } else { "謦欬 余裕" }
                }
                $document[$key] = $value
            }
            Write-TestUtf8 -Path (Join-Path $localeDirectory $fileName) `
                -Content ($document | ConvertTo-Json -Depth 4)
        }
    }
    Write-IsolatedPckView -Path $pckPath -LocalizationRoot $fixtureLocalization

    Write-TestUtf8 -Path $fakeGodotSource -Content @'
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

public sealed class LocalizationManifestEntry
{
    public string locale { get; set; }
    public string path { get; set; }
    public int keys { get; set; }
    public int intentional_empty_values { get; set; }
    public string sha256 { get; set; }
}

public sealed class ArtManifestEntry
{
    public string category { get; set; }
    public string path { get; set; }
    public int width { get; set; }
    public int height { get; set; }
}

public sealed class GateManifest
{
    public LocalizationManifestEntry[] localization { get; set; }
    public ArtManifestEntry[] art { get; set; }
}

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

    private static string ComputeSha256(byte[] bytes)
    {
        using (SHA256 sha = SHA256.Create())
        {
            byte[] digest = sha.ComputeHash(bytes);
            StringBuilder text = new StringBuilder(digest.Length * 2);
            foreach (byte value in digest) text.Append(value.ToString("x2"));
            return text.ToString();
        }
    }

    private static bool IsSha256(string value)
    {
        if (String.IsNullOrEmpty(value) || value.Length != 64) return false;
        foreach (char character in value)
        {
            bool digit = character >= '0' && character <= '9';
            bool lowerHex = character >= 'a' && character <= 'f';
            if (!digit && !lowerHex) return false;
        }
        return true;
    }

    private static byte[] ReadEntryBytes(ZipArchiveEntry entry)
    {
        using (Stream source = entry.Open())
        using (MemoryStream target = new MemoryStream())
        {
            source.CopyTo(target);
            return target.ToArray();
        }
    }

    private static int ValidateMountedPackage(
        string packagePath,
        string manifestPath)
    {
        if (String.IsNullOrEmpty(packagePath) || !File.Exists(packagePath))
        {
            WriteUtf8(-12, "fake mounted validator did not receive a package");
            return 27;
        }
        if (String.IsNullOrEmpty(manifestPath) || !File.Exists(manifestPath))
        {
            WriteUtf8(-12, "fake mounted validator did not receive a manifest");
            return 27;
        }

        JavaScriptSerializer serializer = new JavaScriptSerializer();
        serializer.MaxJsonLength = Int32.MaxValue;
        GateManifest manifest;
        try
        {
            string manifestText = File.ReadAllText(manifestPath, new UTF8Encoding(false, true));
            manifest = serializer.Deserialize<GateManifest>(manifestText);
        }
        catch (Exception error)
        {
            WriteUtf8(-12, "[FAIL] invalid expected manifest: " + error.Message);
            return 3;
        }

        List<string> errors = new List<string>();
        if (manifest == null || manifest.localization == null || manifest.localization.Length != 12)
            errors.Add("mounted manifest is not exactly 12 localization entries");
        if (manifest == null || manifest.art == null || manifest.art.Length != 92)
            errors.Add("mounted manifest is not exactly 92 art entries");

        string[] requiredVfxPaths = new string[]
        {
            "res://Vivhite/skins/ironclad/scenes/vfx/vivhite_eye_lens_glint.png",
            "res://Vivhite/skins/ironclad/transitions/vivhite_character_select_transition.png",
            "res://Vivhite/images/vfx/vivhite_card_trail_mathematical_star_0194.png"
        };
        int[] requiredVfxWidths = new int[] { 512, 2560, 256 };
        int[] requiredVfxHeights = new int[] { 512, 1200, 256 };
        if (manifest != null && manifest.art != null)
        {
            for (int requiredIndex = 0; requiredIndex < requiredVfxPaths.Length; requiredIndex += 1)
            {
                int matches = 0;
                foreach (ArtManifestEntry entry in manifest.art)
                {
                    if (entry != null && String.Equals(entry.path, requiredVfxPaths[requiredIndex],
                        StringComparison.Ordinal))
                    {
                        matches += 1;
                        if (!String.Equals(entry.category, "vfx", StringComparison.Ordinal) ||
                            entry.width != requiredVfxWidths[requiredIndex] ||
                            entry.height != requiredVfxHeights[requiredIndex])
                            errors.Add("mounted VFX contract is wrong: " + entry.path);
                    }
                }
                if (matches != 1)
                    errors.Add("mounted manifest does not contain exactly one " +
                        requiredVfxPaths[requiredIndex]);
            }
        }

        if (manifest == null || manifest.localization == null)
        {
            foreach (string message in errors) WriteUtf8(-12, "[FAIL] " + message);
            return 4;
        }

        string[] locales = new string[] { "eng", "zhs" };
        string[] localizationFiles = new string[]
        {
            "cards.json", "powers.json", "characters.json",
            "card_keywords.json", "relics.json", "ancients.json"
        };
        int[] localizationKeys = new int[] { 188, 69, 20, 10, 3, 24 };
        int[] intentionalEmptyValues = new int[] { 0, 0, 0, 0, 0, 18 };
        Dictionary<string, int> localeCounts = new Dictionary<string, int>();
        Dictionary<string, int> localeFiles = new Dictionary<string, int>();
        Dictionary<string, StringBuilder> localeText = new Dictionary<string, StringBuilder>();
        foreach (string locale in locales)
        {
            localeCounts[locale] = 0;
            localeFiles[locale] = 0;
            localeText[locale] = new StringBuilder();
        }

        try
        {
            using (FileStream packageStream = File.Open(
                packagePath, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (ZipArchive package = new ZipArchive(packageStream, ZipArchiveMode.Read, false))
            {
                foreach (string locale in locales)
                {
                    for (int fileIndex = 0; fileIndex < localizationFiles.Length; fileIndex += 1)
                    {
                        string fileName = localizationFiles[fileIndex];
                        string resourcePath = "res://Vivhite/localization/" + locale + "/" + fileName;
                        LocalizationManifestEntry contract = null;
                        int contractMatches = 0;
                        foreach (LocalizationManifestEntry candidate in manifest.localization)
                        {
                            if (candidate != null && String.Equals(candidate.locale, locale,
                                StringComparison.Ordinal) && String.Equals(candidate.path, resourcePath,
                                StringComparison.Ordinal))
                            {
                                contract = candidate;
                                contractMatches += 1;
                            }
                        }
                        if (contractMatches != 1 || contract == null)
                        {
                            errors.Add("missing or duplicate localization manifest entry: " + resourcePath);
                            continue;
                        }
                        if (contract.keys != localizationKeys[fileIndex])
                            errors.Add("manifest key contract is wrong: " + resourcePath);
                        if (contract.intentional_empty_values != intentionalEmptyValues[fileIndex])
                            errors.Add("manifest intentional-empty contract is wrong: " + resourcePath);
                        if (!IsSha256(contract.sha256))
                            errors.Add("manifest source SHA-256 is malformed: " + resourcePath);

                        string entryName = "Vivhite/localization/" + locale + "/" + fileName;
                        ZipArchiveEntry packedEntry = package.GetEntry(entryName);
                        if (packedEntry == null)
                        {
                            errors.Add("missing localization file: " + resourcePath);
                            continue;
                        }

                        byte[] packedBytes = ReadEntryBytes(packedEntry);
                        string actualHash = ComputeSha256(packedBytes);
                        string expectedHash = contract.sha256 == null ? "" : contract.sha256.ToLowerInvariant();
                        if (!String.Equals(actualHash, expectedHash, StringComparison.Ordinal))
                            errors.Add("localization bytes differ from source: " + resourcePath +
                                " (" + actualHash + " != " + expectedHash + ")");

                        Dictionary<string, string> document;
                        try
                        {
                            string raw = new UTF8Encoding(false, true).GetString(packedBytes);
                            document = serializer.Deserialize<Dictionary<string, string>>(raw);
                        }
                        catch (Exception error)
                        {
                            errors.Add("invalid localization JSON: " + resourcePath + " (" +
                                error.Message + ")");
                            continue;
                        }
                        if (document == null)
                        {
                            errors.Add("invalid localization JSON: " + resourcePath);
                            continue;
                        }
                        if (document.Count != contract.keys)
                            errors.Add("wrong key count: " + resourcePath + " has " + document.Count +
                                ", expected " + contract.keys);

                        int actualEmptyValues = 0;
                        foreach (KeyValuePair<string, string> pair in document)
                        {
                            string value = pair.Value == null ? "<null>" : pair.Value;
                            if (value.Length == 0) actualEmptyValues += 1;
                            localeText[locale].Append('\n').Append(value);
                            if (String.Equals(value.Trim(), pair.Key, StringComparison.Ordinal))
                                errors.Add("raw localization key echo: " + pair.Key);
                            if (value.IndexOf("NOPE", StringComparison.OrdinalIgnoreCase) >= 0)
                                errors.Add("NOPE text found in localization value: " + pair.Key);
                        }
                        if (actualEmptyValues != contract.intentional_empty_values)
                            errors.Add("wrong intentional-empty count: " + resourcePath + " has " +
                                actualEmptyValues + ", expected " + contract.intentional_empty_values);
                        localeCounts[locale] += document.Count;
                        localeFiles[locale] += 1;
                    }
                }
            }
        }
        catch (Exception error)
        {
            errors.Add("could not mount isolated PCK view: " + error.Message);
        }

        if (localeCounts["eng"] != 314 || localeFiles["eng"] != 6)
            errors.Add("English localization is not 314 keys across 6 files");
        if (localeCounts["zhs"] != 314 || localeFiles["zhs"] != 6)
            errors.Add("Chinese localization is not 314 keys across 6 files");
        string english = localeText["eng"].ToString();
        string chinese = localeText["zhs"].ToString();
        if (!english.Contains("Cough") || !english.Contains("Margin"))
            errors.Add("English Cough/Margin terminology is missing");
        if (english.Contains("Life Calculation"))
            errors.Add("retired English term Life Calculation remains");
        if (!chinese.Contains("\u8B26\u6B2C") || !chinese.Contains("\u4F59\u88D5"))
            errors.Add("Chinese Cough/Margin terminology is missing");
        foreach (string retired in new string[] { "\u751F\u547D\u6F14\u7B97", "\u4F59\u91CF", "\u54B3\u8840" })
            if (chinese.Contains(retired)) errors.Add("retired Chinese term remains: " + retired);

        if (errors.Count != 0)
        {
            foreach (string message in errors) WriteUtf8(-12, "[FAIL] " + message);
            return 4;
        }
        return 0;
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
        bool sourceAudit = false;
        bool mounted = false;
        string reportPath = null;
        for (int index = 0; index < args.Length; index += 1)
        {
            string argument = args[index];
            if (argument.EndsWith("audit_vivhite_runtime_art.gd", StringComparison.OrdinalIgnoreCase))
                sourceAudit = true;
            if (argument.EndsWith("verify_pck.gd", StringComparison.OrdinalIgnoreCase)) mounted = true;
            if (String.Equals(argument, "--report", StringComparison.Ordinal) && index + 1 < args.Length)
                reportPath = args[index + 1];
        }
        if (sourceAudit)
        {
            int artCount = 92;
            Int32.TryParse(Environment.GetEnvironmentVariable("VIVHITE_FAKE_ART_COUNT"), out artCount);
            if (artCount <= 0) artCount = 92;
            if (String.IsNullOrEmpty(reportPath))
            {
                WriteUtf8(-12, "fake source audit did not receive --report");
                return 26;
            }
            File.WriteAllText(
                reportPath,
                "{\"expected\":" + artCount + ",\"accepted\":" + artCount + ",\"errors\":[]}",
                new UTF8Encoding(false));
        }
        if (mounted)
        {
            string packagePath = args.Length < 2 ? null : args[args.Length - 2];
            string manifestPath = args.Length == 0 ? null : args[args.Length - 1];
            int validationResult = ValidateMountedPackage(packagePath, manifestPath);
            if (validationResult != 0) return validationResult;
        }
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
Add-Type -Path $SourcePath -OutputAssembly $OutputPath -OutputType WindowsApplication `
    -ReferencedAssemblies @(
        "System.dll",
        "System.Core.dll",
        "System.IO.Compression.dll",
        "System.Web.Extensions.dll"
    )
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
        $testSourceText = [IO.File]::ReadAllText($thisScriptPath, $strictUtf8)
        $forbiddenAncientsSwitch = "VIVHITE_FAKE_" + "ANCIENTS_FAILURE"
        Assert-TextContains -Text $targetText -Expected "謦欬" -Label "Verifier source"
        Assert-TextContains -Text $targetText -Expected "余裕" -Label "Verifier source"
        Assert-Test -Condition (
            $testSourceText.IndexOf($forbiddenAncientsSwitch, [StringComparison]::Ordinal) -lt 0) `
            -Message "Ancients negative tests still use a preset fake-Godot failure switch."
        foreach ($requiredContractText in @(
            "required exactly 92/92 with zero errors",
            "expected source=30, published=34",
            '"characters.json" = 20',
            '"ancients.json" = 24',
            '$localeTotal -ne 314',
            "res://Vivhite/skins/ironclad/scenes/vfx/vivhite_eye_lens_glint.png",
            "res://Vivhite/skins/ironclad/transitions/vivhite_character_select_transition.png",
            "res://Vivhite/images/vfx/vivhite_card_trail_mathematical_star_0194.png"
        )) {
            Assert-TextContains -Text $targetText -Expected $requiredContractText `
                -Label "Verifier 92/30/34 source"
        }
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

    Invoke-TestCase -Name "Legacy 89-item runtime-art report is rejected" -Body {
        $runId = "legacyart" + [Guid]::NewGuid().ToString("N")
        $handle = Start-TestProcess -FilePath $powershellExe `
            -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot `
            -Environment @{ VIVHITE_FAKE_ART_COUNT = "89" }
        $result = Complete-TestProcess -Handle $handle
        Assert-Test -Condition ($result.ExitCode -ne 0) `
            -Message "Legacy 89-item source audit unexpectedly passed."
        $evidenceRoot = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-gate-" -RunId $runId
        $failurePath = Join-Path $evidenceRoot "failure.json"
        Assert-Test -Condition ([IO.File]::Exists($failurePath)) `
            -Message "Legacy runtime-art rejection did not retain failure evidence."
        $failureText = [IO.File]::ReadAllText(
            $failurePath,
            (New-Object System.Text.UTF8Encoding($false, $true)))
        Assert-TextContains -Text $failureText -Expected "required exactly 92/92 with zero errors" `
            -Label "Legacy runtime-art rejection"
    }

    Invoke-TestCase -Name "Legacy 26/30 skin resource contract is rejected" -Body {
        $currentContractText = [IO.File]::ReadAllText(
            $fixtureSkinContract,
            (New-Object System.Text.UTF8Encoding($false, $true)))
        try {
            $legacyContract = [ordered]@{
                expectedRuntimeFileCount = 26
                combatRuntimeLayouts = @(
                    [ordered]@{ name = "legacy-single-page"; expectedRuntimeFileCount = 26 },
                    [ordered]@{ name = "v3-five-page"; expectedRuntimeFileCount = 30 }
                )
            }
            Write-TestUtf8 -Path $fixtureSkinContract `
                -Content ($legacyContract | ConvertTo-Json -Depth 4)
            $runId = "legacyskin" + [Guid]::NewGuid().ToString("N")
            $handle = Start-TestProcess -FilePath $powershellExe `
                -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                    -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot
            $result = Complete-TestProcess -Handle $handle
            Assert-Test -Condition ($result.ExitCode -ne 0) `
                -Message "Legacy 26/30 skin contract unexpectedly passed."
            $evidenceRoot = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-gate-" -RunId $runId
            $failurePath = Join-Path $evidenceRoot "failure.json"
            Assert-Test -Condition ([IO.File]::Exists($failurePath)) `
                -Message "Legacy skin-contract rejection did not retain failure evidence."
            $failureText = [IO.File]::ReadAllText(
                $failurePath,
                (New-Object System.Text.UTF8Encoding($false, $true)))
            Assert-TextContains -Text $failureText -Expected "expected source=30, published=34" `
                -Label "Legacy skin-contract rejection"
        }
        finally {
            Write-TestUtf8 -Path $fixtureSkinContract -Content $currentContractText
        }
    }

    Invoke-TestCase -Name "Source localization gate rejects missing ancients" -Body {
        $ancientsPath = Join-Path $fixtureLocalization "eng\ancients.json"
        $ancientsBytes = [IO.File]::ReadAllBytes($ancientsPath)
        try {
            [IO.File]::Delete($ancientsPath)
            $runId = "sourceancients" + [Guid]::NewGuid().ToString("N")
            $handle = Start-TestProcess -FilePath $powershellExe `
                -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                    -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot
            $result = Complete-TestProcess -Handle $handle
            Assert-Test -Condition ($result.ExitCode -ne 0) `
                -Message "Missing source ancients.json unexpectedly passed."
            $evidenceRoot = Get-RunPath -FixtureRoot $fixtureRoot `
                -Prefix "vivhite-pck-gate-" -RunId $runId
            $failurePath = Join-Path $evidenceRoot "failure.json"
            Assert-Test -Condition ([IO.File]::Exists($failurePath)) `
                -Message "Missing source ancients.json did not retain failure evidence."
            $failureText = [IO.File]::ReadAllText(
                $failurePath,
                (New-Object System.Text.UTF8Encoding($false, $true)))
            Assert-TextContains -Text $failureText -Expected "eng localization does not exist" `
                -Label "Missing source ancients rejection"
            Assert-TextContains -Text $failureText -Expected "ancients.json" `
                -Label "Missing source ancients rejection"
        }
        finally {
            [IO.File]::WriteAllBytes($ancientsPath, $ancientsBytes)
        }
    }

    Invoke-TestCase -Name "Mounted manifest contains 92 assets, 3 VFX, and 6-file localization" -Body {
        $runId = "manifest" + [Guid]::NewGuid().ToString("N")
        $handle = Start-TestProcess -FilePath $powershellExe `
            -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot `
            -Environment @{ VIVHITE_FAKE_GODOT_FAIL_PHASE = "mounted" }
        $result = Complete-TestProcess -Handle $handle
        Assert-Test -Condition ($result.ExitCode -ne 0) `
            -Message "Synthetic mounted failure unexpectedly passed."
        $workRoot = Get-RunPath -FixtureRoot $fixtureRoot -Prefix "vivhite-pck-work-" -RunId $runId
        $manifestPath = Join-Path $workRoot "expected.json"
        $validatorPath = Join-Path $workRoot "verify_pck.gd"
        foreach ($path in @($manifestPath, $validatorPath)) {
            Assert-Test -Condition ([IO.File]::Exists($path)) `
                -Message "Mounted-manifest evidence is missing: $path"
        }
        $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
        $manifest = [IO.File]::ReadAllText($manifestPath, $strictUtf8) | ConvertFrom-Json
        $localization = @($manifest.localization)
        Assert-Test -Condition ($localization.Count -eq 12) `
            -Message "Mounted manifest contains $($localization.Count) localization entries instead of 12."
        $expectedLocalization = [ordered]@{
            "cards.json" = @(188, 0)
            "powers.json" = @(69, 0)
            "characters.json" = @(20, 0)
            "card_keywords.json" = @(10, 0)
            "relics.json" = @(3, 0)
            "ancients.json" = @(24, 18)
        }
        foreach ($locale in @("eng", "zhs")) {
            $localeEntries = @($localization | Where-Object { $_.locale -eq $locale })
            Assert-Test -Condition ($localeEntries.Count -eq 6) `
                -Message "$locale manifest contains $($localeEntries.Count) localization files instead of 6."
            $localeTotal = @($localeEntries | ForEach-Object { [int]$_.keys } |
                Measure-Object -Sum).Sum
            Assert-Test -Condition ([int]$localeTotal -eq 314) `
                -Message "$locale manifest contains $localeTotal localization keys instead of 314."
            foreach ($fileName in $expectedLocalization.Keys) {
                $resourcePath = "res://Vivhite/localization/$locale/$fileName"
                $matches = @($localeEntries | Where-Object { $_.path -eq $resourcePath })
                Assert-Test -Condition ($matches.Count -eq 1) `
                    -Message "Expected exactly one localization entry for $resourcePath."
                Assert-Test -Condition ([int]$matches[0].keys -eq [int]$expectedLocalization[$fileName][0]) `
                    -Message "Mounted localization key count is wrong for $resourcePath."
                Assert-Test -Condition (
                    [int]$matches[0].intentional_empty_values -eq
                        [int]$expectedLocalization[$fileName][1]) `
                    -Message "Mounted intentional-empty count is wrong for $resourcePath."
                Assert-Test -Condition ([string]$matches[0].sha256 -match '^[0-9a-f]{64}$') `
                    -Message "Mounted source hash is missing or malformed for $resourcePath."
            }
        }
        $art = @($manifest.art)
        Assert-Test -Condition ($art.Count -eq 92) `
            -Message "Mounted manifest contains $($art.Count) art entries instead of 92."
        $vfx = @($art | Where-Object { $_.category -eq "vfx" })
        Assert-Test -Condition ($vfx.Count -eq 3) `
            -Message "Mounted manifest contains $($vfx.Count) VFX entries instead of 3."
        $expectedVfx = [ordered]@{
            "res://Vivhite/skins/ironclad/scenes/vfx/vivhite_eye_lens_glint.png" = @(512, 512)
            "res://Vivhite/skins/ironclad/transitions/vivhite_character_select_transition.png" = @(2560, 1200)
            "res://Vivhite/images/vfx/vivhite_card_trail_mathematical_star_0194.png" = @(256, 256)
        }
        foreach ($resourcePath in $expectedVfx.Keys) {
            $matches = @($vfx | Where-Object { $_.path -eq $resourcePath })
            Assert-Test -Condition ($matches.Count -eq 1) `
                -Message "Expected exactly one mounted VFX entry for $resourcePath."
            Assert-Test -Condition (
                [int]$matches[0].width -eq [int]$expectedVfx[$resourcePath][0] -and
                [int]$matches[0].height -eq [int]$expectedVfx[$resourcePath][1]) `
                -Message "Mounted VFX dimensions are wrong for $resourcePath."
        }
        $distinctPaths = @($art | ForEach-Object { [string]$_.path } | Sort-Object -Unique)
        Assert-Test -Condition ($distinctPaths.Count -eq 92) `
            -Message "Mounted manifest has duplicate runtime-art paths."
        $validatorText = [IO.File]::ReadAllText($validatorPath, $strictUtf8)
        Assert-TextContains -Text $validatorText `
            -Expected '{"card": 61, "power": 19, "crown": 2, "energy": 7, "vfx": 3}' `
            -Label "Generated mounted validator"
        foreach ($localizationContractText in @(
            '"ancients.json": 24',
            '"ancients.json": 18',
            "English localization is not 314 keys across 6 files",
            "Chinese localization is not 314 keys across 6 files",
            "localization bytes differ from source",
            "missing localization manifest entry",
            "wrong intentional-empty count"
        )) {
            Assert-TextContains -Text $validatorText -Expected $localizationContractText `
                -Label "Generated mounted localization validator"
        }
        Assert-TextContains -Text $validatorText -Expected "runtime art: 92/92" `
            -Label "Generated mounted validator"
    }

    Invoke-TestCase -Name "Mounted PCK gate accepts byte-identical packed ancients" -Body {
        $entryName = "Vivhite/localization/eng/ancients.json"
        $sourcePath = Join-Path $fixtureLocalization "eng\ancients.json"
        $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
        $packedState = Get-IsolatedPckEntryState -Path $pckPath -EntryName $entryName
        Assert-Test -Condition $packedState.Exists `
            -Message "Clean isolated PCK view is missing eng/ancients.json."
        Assert-Test -Condition ($packedState.Sha256 -eq $sourceHash) `
            -Message "Clean isolated PCK Ancients bytes do not match the source."

        $runId = "packedancientsequal" + [Guid]::NewGuid().ToString("N")
        $handle = Start-TestProcess -FilePath $powershellExe `
            -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot
        $result = Complete-TestProcess -Handle $handle
        Assert-Test -Condition ($result.ExitCode -eq 0) `
            -Message "Byte-identical isolated PCK Ancients unexpectedly failed: $($result.StdErr)"
    }

    Invoke-TestCase -Name "Mounted PCK gate rejects missing ancients" -Body {
        $entryName = "Vivhite/localization/eng/ancients.json"
        try {
            Write-IsolatedPckView -Path $pckPath -LocalizationRoot $fixtureLocalization `
                -MissingEntry $entryName
            $packedState = Get-IsolatedPckEntryState -Path $pckPath -EntryName $entryName
            Assert-Test -Condition (-not $packedState.Exists) `
                -Message "Missing-Ancients fixture still contains the packed entry."

            $runId = "packedancientsmissing" + [Guid]::NewGuid().ToString("N")
            $handle = Start-TestProcess -FilePath $powershellExe `
                -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                    -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot
            $result = Complete-TestProcess -Handle $handle
            Assert-Test -Condition ($result.ExitCode -ne 0) `
                -Message "Mounted PCK with a genuinely missing ancients.json unexpectedly passed."
            $evidenceRoot = Get-RunPath -FixtureRoot $fixtureRoot `
                -Prefix "vivhite-pck-gate-" -RunId $runId
            $consolePath = Join-Path $evidenceRoot "mounted-pck.console.log"
            Assert-Test -Condition ([IO.File]::Exists($consolePath)) `
                -Message "Missing packed ancients rejection did not retain mounted console evidence."
            $consoleText = [IO.File]::ReadAllText(
                $consolePath,
                (New-Object System.Text.UTF8Encoding($false, $true)))
            Assert-TextContains -Text $consoleText -Expected "missing localization file" `
                -Label "Missing packed ancients rejection"
            Assert-TextContains -Text $consoleText -Expected "eng/ancients.json" `
                -Label "Missing packed ancients rejection"
        }
        finally {
            Write-IsolatedPckView -Path $pckPath -LocalizationRoot $fixtureLocalization
        }
    }

    Invoke-TestCase -Name "Mounted PCK gate rejects tampered ancients bytes" -Body {
        $entryName = "Vivhite/localization/eng/ancients.json"
        $sourcePath = Join-Path $fixtureLocalization "eng\ancients.json"
        $sourceHashBefore = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
        $sourceLength = (Get-Item -LiteralPath $sourcePath).Length
        try {
            Write-IsolatedPckView -Path $pckPath -LocalizationRoot $fixtureLocalization `
                -TamperedEntry $entryName
            $packedState = Get-IsolatedPckEntryState -Path $pckPath -EntryName $entryName
            Assert-Test -Condition $packedState.Exists `
                -Message "Tampered-Ancients fixture removed the entry instead of changing its bytes."
            Assert-Test -Condition ($packedState.Sha256 -ne $sourceHashBefore) `
                -Message "Tampered-Ancients fixture bytes still match the source SHA-256."
            Assert-Test -Condition ($packedState.Length -eq $sourceLength + 1) `
                -Message "Tampered-Ancients fixture did not rewrite exactly one package byte."

            $runId = "packedancientstampered" + [Guid]::NewGuid().ToString("N")
            $handle = Start-TestProcess -FilePath $powershellExe `
                -ArgumentList (Get-VerifierArguments -RunId $runId -FixtureRoot $fixtureRoot `
                    -PckPath $pckPath -FakeGodot $fakeGodot) -WorkingDirectory $fixtureRoot
            $result = Complete-TestProcess -Handle $handle
            Assert-Test -Condition ($result.ExitCode -ne 0) `
                -Message "Mounted PCK with genuinely tampered ancients.json bytes unexpectedly passed."
            Assert-Test -Condition (
                (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant() -eq
                    $sourceHashBefore) `
                -Message "Tampered package test unexpectedly changed the source ancients.json."

            $evidenceRoot = Get-RunPath -FixtureRoot $fixtureRoot `
                -Prefix "vivhite-pck-gate-" -RunId $runId
            $workRoot = Get-RunPath -FixtureRoot $fixtureRoot `
                -Prefix "vivhite-pck-work-" -RunId $runId
            $consolePath = Join-Path $evidenceRoot "mounted-pck.console.log"
            $manifestPath = Join-Path $workRoot "expected.json"
            foreach ($path in @($consolePath, $manifestPath)) {
                Assert-Test -Condition ([IO.File]::Exists($path)) `
                    -Message "Tampered packed ancients evidence is missing: $path"
            }
            $strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
            $consoleText = [IO.File]::ReadAllText($consolePath, $strictUtf8)
            $manifest = [IO.File]::ReadAllText($manifestPath, $strictUtf8) | ConvertFrom-Json
            $expectedEntries = @($manifest.localization | Where-Object {
                $_.path -eq "res://Vivhite/localization/eng/ancients.json"
            })
            Assert-Test -Condition ($expectedEntries.Count -eq 1) `
                -Message "Tampered package manifest lost its source Ancients expectation."
            Assert-Test -Condition ([string]$expectedEntries[0].sha256 -eq $sourceHashBefore) `
                -Message "Tampered package test changed the manifest/source expected SHA-256."
            Assert-Test -Condition ([int]$expectedEntries[0].keys -eq 24) `
                -Message "Tampered package manifest no longer expects 24 Ancients keys."
            Assert-Test -Condition ([int]$expectedEntries[0].intentional_empty_values -eq 18) `
                -Message "Tampered package manifest no longer expects 18 intentional empty values."
            Assert-TextContains -Text $consoleText -Expected "localization bytes differ from source" `
                -Label "Tampered packed ancients rejection"
            Assert-TextContains -Text $consoleText -Expected "eng/ancients.json" `
                -Label "Tampered packed ancients rejection"
            Assert-TextContains -Text $consoleText -Expected $packedState.Sha256 `
                -Label "Tampered packed ancients actual hash"
            Assert-TextContains -Text $consoleText -Expected $sourceHashBefore `
                -Label "Tampered packed ancients expected hash"
            foreach ($unexpectedFailure in @(
                "invalid localization JSON",
                "wrong key count: res://Vivhite/localization/eng/ancients.json",
                "wrong intentional-empty count: res://Vivhite/localization/eng/ancients.json"
            )) {
                Assert-Test -Condition (
                    $consoleText.IndexOf($unexpectedFailure, [StringComparison]::Ordinal) -lt 0) `
                    -Message "Byte-only tamper triggered an unintended failure: $unexpectedFailure"
            }
        }
        finally {
            Write-IsolatedPckView -Path $pckPath -LocalizationRoot $fixtureLocalization
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
