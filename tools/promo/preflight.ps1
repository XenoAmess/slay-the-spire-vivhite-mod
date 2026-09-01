<#
.SYNOPSIS
Performs a read-only preflight for the Vivhite promotional-video adapter.

.DESCRIPTION
This script checks the project contract, synthetic capture fixture, entry-point
declarations, path/hash bindings, and the no-overlay capture policy.  It never
starts Slay the Spire 2, Steam, OBS, a recorder, or a live/Brain stack.  The
optional test pass runs only the offline unittest suite and uses synthetic
bytes.

The script intentionally reports FFmpeg/ffprobe/OBS as warnings by default:
they are production recording dependencies, not reasons for a source-contract
checkout to fail.  Use -RequireExternalTools before a real capture session.
#>
[CmdletBinding()]
param(
    [string]$RepoRoot = "",
    [switch]$RunTests,
    [switch]$RequireExternalTools,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}

$root = [IO.Path]::GetFullPath($RepoRoot)
$promoRoot = Join-Path $root "tools\promo"
$schemaPath = Join-Path $promoRoot "schemas\vivhite-promo-capture-v1.schema.json"
$fixtureRoot = Join-Path $promoRoot "fixtures\minimal_capture"
$results = New-Object "System.Collections.Generic.List[object]"

function Add-Result {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][ValidateSet("pass", "warn", "fail")][string]$Status,
        [Parameter(Mandatory = $true)][string]$Message
    )
    $results.Add([pscustomobject]@{
            name = $Name
            status = $Status
            message = $Message
        })
}

function Resolve-InRoot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Base
    )
    $candidate = [IO.Path]::GetFullPath((Join-Path $Base $Path))
    $baseFull = [IO.Path]::GetFullPath($Base).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
    if (-not $candidate.StartsWith($baseFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "path escapes root: $Path"
    }
    return $candidate
}

function Get-JsonDocument {
    param([Parameter(Mandatory = $true)][string]$Path)
    try {
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json)
    }
    catch {
        throw "invalid JSON in '$Path': $($_.Exception.Message)"
    }
}

function Get-ContractPath {
    $candidates = @(Get-ChildItem -LiteralPath $fixtureRoot -Filter "*.json" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notin @("manifest.json", "metadata.json") } |
        Sort-Object Name)
    if ($candidates.Count -eq 0) {
        throw "no capture contract JSON found below $fixtureRoot"
    }
    foreach ($preferred in @("capture.json", "contract.json", "capture_contract.json")) {
        $match = $candidates | Where-Object { $_.Name -ieq $preferred } | Select-Object -First 1
        if ($null -ne $match) {
            return $match.FullName
        }
    }
    return $candidates[0].FullName
}

function Get-ArtifactRecords {
    param([Parameter(Mandatory = $true)]$Node)
    $records = New-Object "System.Collections.Generic.List[object]"
    if ($null -eq $Node) {
        return $records
    }
    if ($Node -is [System.Collections.IEnumerable] -and $Node -isnot [string] -and $Node -isnot [pscustomobject]) {
        foreach ($item in $Node) {
            foreach ($record in (Get-ArtifactRecords -Node $item)) {
                $records.Add($record)
            }
        }
        return $records
    }
    if ($Node -is [pscustomobject]) {
        $properties = @($Node.PSObject.Properties)
        $hasBinding = ($null -ne ($properties | Where-Object Name -eq "path")) -and
            ($null -ne ($properties | Where-Object Name -eq "bytes")) -and
            ($null -ne ($properties | Where-Object Name -eq "sha256"))
        if ($hasBinding) {
            $records.Add($Node)
        }
        foreach ($property in $properties) {
            foreach ($record in (Get-ArtifactRecords -Node $property.Value)) {
                $records.Add($record)
            }
        }
    }
    return $records
}

function Test-JsonPathValues {
    param(
        [Parameter(Mandatory = $true)]$Node,
        [string]$Key = ""
    )
    $issues = New-Object "System.Collections.Generic.List[string]"
    if ($null -eq $Node) {
        return $issues
    }
    if ($Node -is [string]) {
        $looksLikePath = $Key -match "(?i)(path|file|source|artifact|output)"
        if ($looksLikePath -and ([IO.Path]::IsPathRooted($Node) -or $Node -match "(^|[\\/])\.\.([\\/]|$)")) {
            $issues.Add("$Key contains an absolute or escaping path: $Node")
        }
        return $issues
    }
    if ($Node -is [System.Collections.IEnumerable] -and $Node -isnot [string] -and $Node -isnot [pscustomobject]) {
        foreach ($item in $Node) {
            foreach ($issue in (Test-JsonPathValues -Node $item -Key $Key)) {
                $issues.Add($issue)
            }
        }
        return $issues
    }
    if ($Node -is [pscustomobject]) {
        foreach ($property in @($Node.PSObject.Properties)) {
            foreach ($issue in (Test-JsonPathValues -Node $property.Value -Key $property.Name)) {
                $issues.Add($issue)
            }
        }
    }
    return $issues
}

try {
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "repository root does not exist: $root"
    }

    foreach ($required in @(
            "tools\promo\vivhite_promo\__init__.py",
            "tools\promo\vivhite_promo\capture_contract.py",
            "tools\promo\vivhite_promo\adapter.py",
            "tools\promo\vivhite_promo\preset.py",
            "tools\promo\vivhite_promo\pipeline.py",
            "tools\promo\vivhite_promo\claims.py",
            "tools\promo\schemas\vivhite-promo-capture-v1.schema.json",
            "tools\promo\project.json",
            "tools\promo\storyboard.json",
            "tools\promo\claims\claims.json",
            "tools\promo\pyproject.toml"
        )) {
        $path = Join-Path $root $required
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Add-Result -Name "file:$required" -Status pass -Message "present"
        }
        else {
            Add-Result -Name "file:$required" -Status fail -Message "missing"
        }
    }

    if (Test-Path -LiteralPath $schemaPath -PathType Leaf) {
        $schema = Get-JsonDocument -Path $schemaPath
        $required = @($schema.required)
        $requiredNames = @("kind", "contract_version", "mode", "producer_id", "run_id", "media", "marks", "clean_spans", "evidence", "project_context")
        $missing = @($requiredNames | Where-Object { $_ -notin $required })
        if ($missing.Count -eq 0 -and $schema.type -eq "object" -and
            $schema.properties.kind.const -eq "vivhite_promo_capture" -and
            [int]$schema.properties.contract_version.const -eq 1) {
            Add-Result -Name "schema" -Status pass -Message "v1 identity and required fields are present"
        }
        else {
            Add-Result -Name "schema" -Status fail -Message "schema identity/required fields are incomplete: $($missing -join ', ')"
        }
    }

    $contractPath = $null
    if (Test-Path -LiteralPath $fixtureRoot -PathType Container) {
        try {
            $contractPath = Get-ContractPath
            $contract = Get-JsonDocument -Path $contractPath
            if ($contract.kind -ne "vivhite_promo_capture" -or [int]$contract.contract_version -ne 1 -or $contract.mode -ne "vivhite-promo") {
                Add-Result -Name "fixture:identity" -Status fail -Message "fixture has the wrong contract identity"
            }
            else {
                Add-Result -Name "fixture:identity" -Status pass -Message "fixture identity is vivhite-promo v1"
            }

            $context = $contract.project_context
            $safeContext = ($context.mod_id -eq "Vivhite") -and
                (-not [string]::IsNullOrWhiteSpace([string]$context.game_version)) -and
                (-not [string]::IsNullOrWhiteSpace([string]$context.mod_version)) -and
                ([string]$context.renderer).ToLowerInvariant() -eq "vulkan" -and
                (@($context.resolution).Count -eq 2) -and
                ([int]$context.resolution[0] -eq 1920) -and
                ([int]$context.resolution[1] -eq 1080) -and
                ([int]$context.fps -eq 60) -and
                ($context.overlays_absent -eq $true) -and
                ($context.loading_absent -eq $true) -and
                ($context.console_absent -eq $true)
            if ($safeContext) {
                Add-Result -Name "fixture:capture-policy" -Status pass -Message "Vulkan/1080p60 and overlay/loading/console absence are asserted"
            }
            else {
                Add-Result -Name "fixture:capture-policy" -Status fail -Message "fixture does not prove a clean 1080p60 capture"
            }

            $pathIssues = @(Test-JsonPathValues -Node $contract)
            if ($pathIssues.Count -eq 0) {
                Add-Result -Name "fixture:paths" -Status pass -Message "no absolute or escaping path values"
            }
            else {
                Add-Result -Name "fixture:paths" -Status fail -Message ($pathIssues -join "; ")
            }

            $artifactIssues = New-Object "System.Collections.Generic.List[string]"
            foreach ($record in (Get-ArtifactRecords -Node $contract)) {
                try {
                    $relative = [string]$record.path
                    $artifactPath = Resolve-InRoot -Path $relative -Base $fixtureRoot
                    if (-not (Test-Path -LiteralPath $artifactPath -PathType Leaf)) {
                        $artifactIssues.Add("missing artifact: $relative")
                        continue
                    }
                    $actualBytes = (Get-Item -LiteralPath $artifactPath).Length
                    if ([int64]$record.bytes -ne $actualBytes) {
                        $artifactIssues.Add("byte count mismatch: $relative")
                    }
                    $actualHash = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
                    if ([string]$record.sha256 -ne $actualHash) {
                        $artifactIssues.Add("SHA-256 mismatch: $relative")
                    }
                }
                catch {
                    $artifactIssues.Add($_.Exception.Message)
                }
            }
            if ($artifactIssues.Count -eq 0) {
                Add-Result -Name "fixture:artifacts" -Status pass -Message "all bound artifacts exist and match bytes/SHA-256"
            }
            else {
                Add-Result -Name "fixture:artifacts" -Status fail -Message ($artifactIssues -join "; ")
            }

            $rawText = Get-Content -LiteralPath $contractPath -Raw -Encoding UTF8
            if ($rawText -match "(?i)(EVOLINK_API_KEY|Authorization\s*[:=]|Bearer\s+[A-Za-z0-9._-]+|[A-Z]:[\\/]+Users[\\/])") {
                Add-Result -Name "fixture:secrets" -Status fail -Message "fixture contains a credential or absolute user path"
            }
            else {
                Add-Result -Name "fixture:secrets" -Status pass -Message "no credential-like values"
            }
        }
        catch {
            Add-Result -Name "fixture" -Status fail -Message $_.Exception.Message
        }
    }
    else {
        Add-Result -Name "fixture" -Status fail -Message "minimal_capture fixture directory is missing"
    }

    $pyprojectPath = Join-Path $promoRoot "pyproject.toml"
    if (Test-Path -LiteralPath $pyprojectPath -PathType Leaf) {
        $toml = Get-Content -LiteralPath $pyprojectPath -Raw -Encoding UTF8
        $hasAdapter = $toml -match '(?m)^\s*\[project\.entry-points\."xar_promo\.adapters"\]' -and
            $toml -match '(?m)^\s*vivhite\s*=\s*"[^"]+:[^"]+"'
        $hasPreset = $toml -match '(?m)^\s*\[project\.entry-points\."xar_promo\.presets"\]' -and
            $toml -match '(?m)^\s*vivhite-player-10m\s*=\s*"[^"]+:[^"]+"'
        if ($hasAdapter -and $hasPreset) {
            Add-Result -Name "entry-points" -Status pass -Message "vivhite adapter and vivhite-player-10m preset are declared"
        }
        else {
            Add-Result -Name "entry-points" -Status fail -Message "required xAR entry points are missing"
        }
    }

    foreach ($tool in @("ffmpeg", "ffprobe", "obs64")) {
        $command = Get-Command $tool -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            Add-Result -Name "tool:$tool" -Status pass -Message $command.Source
        }
        elseif ($RequireExternalTools) {
            Add-Result -Name "tool:$tool" -Status fail -Message "not found; required for a real capture"
        }
        else {
            Add-Result -Name "tool:$tool" -Status warn -Message "not found (use -RequireExternalTools before recording)"
        }
    }

    if ($RunTests) {
        $python = $null
        foreach ($candidate in @(
                (Get-Command py -ErrorAction SilentlyContinue),
                (Get-Command python -ErrorAction SilentlyContinue),
                (Get-Command python3 -ErrorAction SilentlyContinue)
            )) {
            if ($null -ne $candidate) {
                $python = $candidate.Source
                break
            }
        }
        if ($null -eq $python) {
            Add-Result -Name "offline-tests" -Status fail -Message "no Python interpreter found"
        }
        else {
            # The unittest suite is intentionally offline and contains a
            # process-spawn tripwire for validate_only.  It never starts the
            # game, OBS, Steam, or the Brain stack.
            $testOutput = & $python -B -m unittest discover -s (Join-Path $promoRoot "tests") -p "test_*.py" -v 2>&1
            $exitCode = $LASTEXITCODE
            if ($exitCode -eq 0) {
                Add-Result -Name "offline-tests" -Status pass -Message "unittest suite passed"
            }
            else {
                Add-Result -Name "offline-tests" -Status fail -Message ("unittest exit code {0}: {1}" -f $exitCode, (($testOutput | Out-String).Trim()))
            }
        }
    }
}
catch {
    Add-Result -Name "preflight" -Status fail -Message $_.Exception.Message
}

$failed = @($results | Where-Object status -eq "fail")
$warnings = @($results | Where-Object status -eq "warn")
if ($Json) {
    # Materialize the generic list before serialization.  Windows PowerShell
    # 5.1 can otherwise throw "Argument types do not match" while reflecting
    # a generic List[object] nested in a PSCustomObject.
    $checkArray = @($results | ForEach-Object {
            [pscustomobject]@{
                name = [string]$_.name
                status = [string]$_.status
                message = [string]$_.message
            }
        })
    [pscustomobject]@{
        repo_root = $root
        promo_root = $promoRoot
        passed = ($failed.Count -eq 0)
        failures = $failed.Count
        warnings = $warnings.Count
        checks = $checkArray
    } | ConvertTo-Json -Depth 8
}
else {
    foreach ($result in $results) {
        $prefix = switch ($result.status) {
            "pass" { "[PASS]" }
            "warn" { "[WARN]" }
            default { "[FAIL]" }
        }
        $color = switch ($result.status) {
            "pass" { "Green" }
            "warn" { "Yellow" }
            default { "Red" }
        }
        Write-Host "$prefix $($result.name): $($result.message)" -ForegroundColor $color
    }
    if ($failed.Count -eq 0) {
        Write-Host ("Promo preflight passed with {0} warning(s)." -f $warnings.Count) -ForegroundColor Green
    }
    else {
        Write-Host ("Promo preflight failed: {0} check(s) failed." -f $failed.Count) -ForegroundColor Red
    }
}

if ($failed.Count -gt 0) {
    exit 1
}
exit 0
