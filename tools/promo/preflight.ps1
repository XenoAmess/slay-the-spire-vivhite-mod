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
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
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
$gameRoot = [IO.Path]::GetFullPath($GameDir)
$promoRoot = Join-Path $root "tools\promo"
$schemaPath = Join-Path $promoRoot "schemas\vivhite-promo-capture-v1.schema.json"
$fixtureRoot = Join-Path $promoRoot "fixtures\minimal_capture"
$projectPath = Join-Path $promoRoot "project.json"
$presetPath = Join-Path $promoRoot "preset.json"
$claimsPath = Join-Path $promoRoot "claims\claims.json"
$ffmpegLockPath = Join-Path $promoRoot "ffmpeg-lock.json"
$captureSettingsPath = Join-Path $promoRoot "capture-settings.json"
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

function Get-NodeProperty {
    param(
        [Parameter(Mandatory = $true)]$Node,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($null -eq $Node) {
        return $null
    }
    $property = $Node.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Test-Sha256Text {
    param([Parameter(Mandatory = $true)][string]$Value)
    return $Value -match "^[A-Fa-f0-9]{64}$"
}

function Resolve-WindowsLockDirectory {
    param([Parameter(Mandatory = $true)][string]$Directory)
    # The lock is intentionally a Windows installation contract.  Normalize
    # slash style before comparing it, but do not resolve symlinks or scan for
    # another directory: the selected bytes must come from this exact path.
    $normalized = $Directory.Replace("/", "\")
    if (-not [IO.Path]::IsPathRooted($normalized)) {
        throw "FFmpeg lock directory must be absolute: $Directory"
    }
    $full = [IO.Path]::GetFullPath($normalized).TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    if (-not $full.Equals("C:\ffmpeg\bin", [StringComparison]::OrdinalIgnoreCase)) {
        throw "FFmpeg lock directory must be C:/ffmpeg/bin after the in-place replacement"
    }
    return $full
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

    # A project-only checkout may be validated without the game installed, so
    # keep this diagnostic a warning by default.  The production gate must not
    # report a clean overlay state merely because a typo/nonexistent GameDir
    # made every pollution target appear absent.
    $gameRootExists = Test-Path -LiteralPath $gameRoot -PathType Container
    if (-not $gameRootExists) {
        $message = "game directory does not exist: $gameRoot"
        if ($RequireExternalTools) {
            Add-Result -Name "game:directory" -Status fail -Message $message
        }
        else {
            Add-Result -Name "game:directory" -Status warn -Message $message
        }
    }
    else {
        Add-Result -Name "game:directory" -Status pass -Message $gameRoot
        $gameRequiredPaths = @(
            (Join-Path $gameRoot "SlayTheSpire2.exe"),
            (Join-Path $gameRoot "mods")
        )
        foreach ($gameRequired in $gameRequiredPaths) {
            $kind = if ($gameRequired.EndsWith(".exe", [StringComparison]::OrdinalIgnoreCase)) { "file" } else { "directory" }
            $checkName = "game:{0}:{1}" -f $kind, ([IO.Path]::GetFileName($gameRequired))
            $exists = if ($kind -eq "file") {
                Test-Path -LiteralPath $gameRequired -PathType Leaf
            }
            else {
                Test-Path -LiteralPath $gameRequired -PathType Container
            }
            if ($exists) {
                Add-Result -Name $checkName -Status pass -Message $gameRequired
            }
            elseif ($RequireExternalTools) {
                Add-Result -Name $checkName -Status fail -Message "missing: $gameRequired"
            }
            else {
                Add-Result -Name $checkName -Status warn -Message "missing: $gameRequired"
            }
        }
    }

    # A clean Game Capture cannot be established while the known in-game
    # overlay/Workshop payloads are installed.  This check is deliberately
    # deny-only and read-only: isolation is performed by the reversible
    # isolate_capture_mods.ps1 helper, never by preflight itself.
    $pollutionTargets = @(
        (Join-Path $gameRoot "mods\mod_id.json"),
        (Join-Path $gameRoot "mods\STS2AIAgent.dll"),
        (Join-Path $gameRoot "mods\STS2AIAgent.pck"),
        (Join-Path $gameRoot "..\..\workshop\content\2868840\3787753911")
    )
    if (-not $gameRootExists) {
        $message = "cannot evaluate overlay payloads because the game directory is missing: $gameRoot"
        if ($RequireExternalTools) {
            Add-Result -Name "capture:overlay-mods" -Status fail -Message $message
        }
        else {
            Add-Result -Name "capture:overlay-mods" -Status warn -Message $message
        }
    }
    else {
        $presentPollution = @($pollutionTargets | Where-Object { Test-Path -LiteralPath $_ })
    }
    if ($gameRootExists -and $presentPollution.Count -eq 0) {
        Add-Result -Name "capture:overlay-mods" -Status pass -Message "known STS2AIAgent/LieRenTVmod payloads are absent"
    }
    elseif ($gameRootExists) {
        $pollutionMessage = "known in-game overlay payload(s) present; run isolate_capture_mods.ps1 -Apply before production capture: " + ($presentPollution -join "; ")
        if ($RequireExternalTools) {
            Add-Result -Name "capture:overlay-mods" -Status fail -Message $pollutionMessage
        }
        else {
            Add-Result -Name "capture:overlay-mods" -Status warn -Message $pollutionMessage
        }
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
            "tools\promo\preset.json",
            "tools\promo\storyboard.json",
            "tools\promo\claims\claims.json",
            "tools\promo\variants\hero-60.json",
            "tools\promo\variants\cut-30.json",
            "tools\promo\variants\cut-15.json",
            "tools\promo\pyproject.toml",
            "tools\promo\configure_obs.ps1",
            "tools\promo\isolate_capture_mods.ps1",
            "tools\promo\ffmpeg-lock.json",
            "tools\promo\capture-settings.json"
        )) {
        $path = Join-Path $root $required
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Add-Result -Name "file:$required" -Status pass -Message "present"
        }
        else {
            Add-Result -Name "file:$required" -Status fail -Message "missing"
        }
    }

    # Project policy is intentionally checked separately from the generic xAR
    # project schema.  The generic layer does not know which voice or soundtrack
    # an individual project has selected; this adapter must fail closed when a
    # stale preset silently changes either decision.
    try {
        $project = Get-JsonDocument -Path $projectPath
        $preset = Get-JsonDocument -Path $presetPath
        $projectIdentityOk = (Get-NodeProperty -Node $project -Name "format_version") -eq 1 -and
            (Get-NodeProperty -Node $project -Name "kind") -eq "xar_promo_project_config" -and
            (Get-NodeProperty -Node (Get-NodeProperty -Node $project -Name "project") -Name "id") -eq "vivhite-player-promo" -and
            (Get-NodeProperty -Node (Get-NodeProperty -Node $project -Name "pipeline") -Name "adapter") -eq "vivhite" -and
            (Get-NodeProperty -Node (Get-NodeProperty -Node $project -Name "pipeline") -Name "preset") -eq "vivhite-player-10m"
        if ($projectIdentityOk) {
            Add-Result -Name "project:identity" -Status pass -Message "Vivhite project identity and xAR pipeline binding are declared"
        }
        else {
            Add-Result -Name "project:identity" -Status fail -Message "project.json identity or adapter/preset binding is not canonical"
        }

        $voice = [string](Get-NodeProperty -Node $preset -Name "voice")
        if ($voice -ceq "zh-CN-XiaoxiaoNeural") {
            Add-Result -Name "policy:voice" -Status pass -Message "narration voice is pinned to zh-CN-XiaoxiaoNeural"
        }
        else {
            Add-Result -Name "policy:voice" -Status fail -Message "preset voice must be zh-CN-XiaoxiaoNeural (ZhongGuo phase-one voice); got '$voice'"
        }

        $includeBgm = Get-NodeProperty -Node $preset -Name "include_bgm"
        if ($includeBgm -is [bool] -and $includeBgm -eq $false) {
            Add-Result -Name "policy:bgm" -Status pass -Message "BGM is explicitly disabled for the first cut"
        }
        else {
            Add-Result -Name "policy:bgm" -Status fail -Message "preset.include_bgm must be boolean false; no BGM is authorized for this cut"
        }

        $subtitleLocales = Get-NodeProperty -Node $preset -Name "subtitle_locales"
        $policyShapeOk = (Get-NodeProperty -Node $preset -Name "project_id") -eq "vivhite-player-promo" -and
            (Get-NodeProperty -Node $preset -Name "adapter_id") -eq "vivhite" -and
            (Get-NodeProperty -Node $preset -Name "preset_id") -eq "vivhite-player-10m" -and
            (Get-NodeProperty -Node $preset -Name "narration_locale") -eq "zh-CN" -and
            (@($subtitleLocales).Count -eq 2) -and
            ([string]$subtitleLocales[0] -eq "zh-CN") -and
            ([string]$subtitleLocales[1] -eq "en") -and
            ([int](Get-NodeProperty -Node $preset -Name "target_duration_seconds") -eq 600) -and
            ([int](Get-NodeProperty -Node $preset -Name "duration_limit_seconds") -eq 1200) -and
            ([int](Get-NodeProperty -Node $preset -Name "width") -eq 1920) -and
            ([int](Get-NodeProperty -Node $preset -Name "height") -eq 1080) -and
            ([int](Get-NodeProperty -Node $preset -Name "fps") -eq 60)
        if ($policyShapeOk) {
            Add-Result -Name "policy:shape" -Status pass -Message "voice, locale, duration, and 1920x1080@60 policy fields are consistent"
        }
        else {
            Add-Result -Name "policy:shape" -Status fail -Message "preset identity, locale, duration, or render geometry is inconsistent"
        }

        foreach ($policyFile in @($projectPath, $presetPath, (Join-Path $promoRoot "storyboard.json"), (Join-Path $promoRoot "claims\claims.json"))) {
            $policyText = Get-Content -LiteralPath $policyFile -Raw -Encoding UTF8
            if ($policyText.Contains([char]0xFFFD)) {
                Add-Result -Name "encoding:$([IO.Path]::GetFileName($policyFile))" -Status fail -Message "file contains Unicode replacement characters"
            }
            else {
                Add-Result -Name "encoding:$([IO.Path]::GetFileName($policyFile))" -Status pass -Message "UTF-8 text has no replacement characters"
            }
        }

        # Source references are structural audit inputs, not prose.  Resolve
        # them against this checkout now so a pending claim cannot reach a
        # production run with a typo or an escaping path.  Directories are
        # accepted for intentionally broad catalog references; semantic
        # validators still decide which files inside them prove a claim.
        try {
            $claims = Get-JsonDocument -Path $claimsPath
            $claimRows = @((Get-NodeProperty -Node $claims -Name "claims"))
            $claimIssues = New-Object "System.Collections.Generic.List[string]"
            if ($claimRows.Count -eq 0 -or ($claimRows.Count -eq 1 -and $null -eq $claimRows[0])) {
                $claimIssues.Add("claims document has no claims array")
            }
            foreach ($claim in $claimRows) {
                if ($null -eq $claim) { continue }
                $claimId = [string](Get-NodeProperty -Node $claim -Name "claim_id")
                $refs = Get-NodeProperty -Node $claim -Name "source_refs"
                if ($null -eq $refs) {
                    $claimIssues.Add("$claimId has no source_refs")
                    continue
                }
                foreach ($reference in @($refs)) {
                    $refText = [string]$reference
                    $segments = $refText -split "/"
                    if ([string]::IsNullOrWhiteSpace($refText) -or
                        $refText -match "\\" -or
                        [IO.Path]::IsPathRooted($refText) -or
                        $refText -match "^[A-Za-z]:" -or
                        (@($segments | Where-Object { $_ -in @("", ".", "..") }).Count -gt 0)) {
                        $claimIssues.Add("$claimId source_ref is not a normalized relative path: $refText")
                        continue
                    }
                    try {
                        $resolvedReference = Resolve-InRoot -Path $refText -Base $root
                        if (-not (Test-Path -LiteralPath $resolvedReference -PathType Leaf) -and
                            -not (Test-Path -LiteralPath $resolvedReference -PathType Container)) {
                            $claimIssues.Add("$claimId source_ref does not exist: $refText")
                        }
                    }
                    catch {
                        $claimIssues.Add("$claimId source_ref is invalid: $refText ($($_.Exception.Message))")
                    }
                }
            }
            if ($claimIssues.Count -eq 0) {
                Add-Result -Name "claims:source-refs" -Status pass -Message "all claim source_refs resolve inside the project root"
            }
            else {
                Add-Result -Name "claims:source-refs" -Status fail -Message ($claimIssues -join "; ")
            }
        }
        catch {
            Add-Result -Name "claims:source-refs" -Status fail -Message $_.Exception.Message
        }
    }
    catch {
        Add-Result -Name "project-policy" -Status fail -Message $_.Exception.Message
    }

    # The lock records both the exact install location and the executable
    # digests.  A capability-only check is insufficient because an older or
    # modified binary can expose a misleading subset of filters.
    $lockValid = $false
    $requiredFilters = @()
    $lockedTools = @{}
    try {
        $lock = Get-JsonDocument -Path $ffmpegLockPath
        if ((Get-NodeProperty -Node $lock -Name "format_version") -ne 1 -or
            (Get-NodeProperty -Node $lock -Name "kind") -ne "vivhite_promo_ffmpeg_lock") {
            throw "FFmpeg lock has the wrong format or kind"
        }
        $requiredFilters = @()
        $rawRequiredFilters = Get-NodeProperty -Node $lock -Name "required_filters"
        if ($rawRequiredFilters -is [System.Collections.IEnumerable] -and $rawRequiredFilters -isnot [string]) {
            foreach ($requiredFilter in $rawRequiredFilters) {
                $requiredFilters += [string]$requiredFilter
            }
        }
        elseif ($null -ne $rawRequiredFilters) {
            $requiredFilters += [string]$rawRequiredFilters
        }
        if ($requiredFilters.Count -eq 0 -or $requiredFilters -notcontains "tpad") {
            throw "FFmpeg lock must require the tpad filter"
        }
        $install = Get-NodeProperty -Node $lock -Name "windows_install"
        $lockDirectory = Resolve-WindowsLockDirectory -Directory ([string](Get-NodeProperty -Node $install -Name "directory"))
        foreach ($lockedTool in @("ffmpeg", "ffprobe")) {
            $entry = Get-NodeProperty -Node $install -Name $lockedTool
            $fileName = [string](Get-NodeProperty -Node $entry -Name "file")
            $digest = ([string](Get-NodeProperty -Node $entry -Name "sha256")).ToUpperInvariant()
            if ([string]::IsNullOrWhiteSpace($fileName) -or $fileName -match "[\\/]" -or -not (Test-Sha256Text -Value $digest)) {
                throw "FFmpeg lock has an invalid $lockedTool file or SHA-256"
            }
            $lockedTools[$lockedTool] = [pscustomobject]@{
                path = Join-Path $lockDirectory $fileName
                sha256 = $digest
            }
        }
        $lockValid = $true
        Add-Result -Name "ffmpeg-lock" -Status pass -Message "FFmpeg/ffprobe lock points to C:/ffmpeg/bin with pinned SHA-256"
    }
    catch {
        Add-Result -Name "ffmpeg-lock" -Status fail -Message $_.Exception.Message
    }

    if (Test-Path -LiteralPath $schemaPath -PathType Leaf) {
        $schema = Get-JsonDocument -Path $schemaPath
        $required = @($schema.required)
        $requiredNames = @("kind", "contract_version", "project_context")
        $missing = @($requiredNames | Where-Object { $_ -notin $required })
        $directReceiptFields = @("media", "marks", "clean_spans", "evidence")
        $hasReceiptShape = ("capture_receipt" -in $required) -or
            (@($directReceiptFields | Where-Object { $_ -in $required }).Count -eq 4)
        if ($missing.Count -eq 0 -and $hasReceiptShape -and $schema.type -eq "object" -and
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
            $fixtureEvidenceRoles = @(
                @($contract.capture_receipt.clean_spans) |
                    ForEach-Object { @($_.evidence) } |
                    ForEach-Object { [string]$_.role }
            )
            # overlays_absent covers third-party/mod overlays only.  Native
            # STS2 release/version/MODDED labels are asserted separately.
            $safeContext = ($context.mod_id -eq "Vivhite") -and
                (-not [string]::IsNullOrWhiteSpace([string]$context.game_version)) -and
                (-not [string]::IsNullOrWhiteSpace([string]$context.mod_version)) -and
                ($context.pck_name -eq "Vivhite") -and
                (-not [string]::IsNullOrWhiteSpace([string]$context.pck_version)) -and
                ($context.ritsu_lib_id -eq "STS2-RitsuLib") -and
                ($context.ritsu_lib_version -eq "0.5.14") -and
                ([string]$context.renderer).ToLowerInvariant() -eq "vulkan" -and
                (@($context.resolution).Count -eq 2) -and
                ([int]$context.resolution[0] -eq 1920) -and
                ([int]$context.resolution[1] -eq 1080) -and
                ([int]$context.fps -eq 60) -and
                ($context.overlays_absent -eq $true) -and
                ($context.native_debug_surface_hidden -eq $true) -and
                ($context.native_debug_surface_method -eq "vivhite-promo-capture-surface-v1") -and
                (-not [string]::IsNullOrWhiteSpace([string]$context.native_debug_surface_evidence_role)) -and
                ($fixtureEvidenceRoles -contains [string]$context.native_debug_surface_evidence_role) -and
                ($context.loading_absent -eq $true) -and
                ($context.console_absent -eq $true)
            if ($safeContext) {
                Add-Result -Name "fixture:capture-policy" -Status pass -Message "Vulkan/1080p60, third-party overlay absence, and a separately hidden native debug surface are asserted"
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

    try {
        $captureSettings = Get-JsonDocument -Path $captureSettingsPath
        $nativeSurface = $captureSettings.native_debug_surface
        $obsSettings = $captureSettings.obs
        $videoSettings = $obsSettings.video
        $audioSettings = $obsSettings.audio
        $settingsValid =
            ($captureSettings.kind -eq "vivhite_promo_capture_settings") -and
            ([int]$captureSettings.schema_version -eq 1) -and
            ($nativeSurface.required -eq $true) -and
            ($nativeSurface.method -eq "vivhite-promo-capture-surface-v1") -and
            ($nativeSurface.environment_variable -eq "VIVHITE_PROMO_CAPTURE") -and
            ($nativeSurface.enabled_value -eq "1") -and
            ($obsSettings.version -eq "32.2.2") -and
            ($obsSettings.game_capture_window -eq "Slay the Spire 2:Engine:SlayTheSpire2.exe") -and
            ($obsSettings.capture_cursor -eq $false) -and
            ($obsSettings.capture_overlays -eq $false) -and
            ($obsSettings.capture_audio -eq $false) -and
            ($obsSettings.anti_cheat_hook -eq $true) -and
            ([int]$obsSettings.hook_rate -eq 1) -and
            ($obsSettings.monitor_capture_in_active_scene -eq $false) -and
            ($obsSettings.audio_source -eq "global-wasapi-output") -and
            ($obsSettings.microphone -eq "disabled") -and
            ($obsSettings.use_device_timing -eq $false) -and
            ([int]$videoSettings.width -eq 1920) -and
            ([int]$videoSettings.height -eq 1080) -and
            ([int]$videoSettings.fps -eq 60) -and
            ($videoSettings.encoder -eq "nvenc") -and
            ($videoSettings.container -eq "mkv") -and
            ($audioSettings.codec -eq "aac") -and
            ([int]$audioSettings.bitrate_kbps -eq 192) -and
            ([int]$audioSettings.sample_rate_hz -eq 48000) -and
            ([int]$audioSettings.channels -eq 2) -and
            ([int]$audioSettings.tracks -eq 1) -and
            ($captureSettings.ffmpeg.directory -eq "C:/ffmpeg/bin") -and
            (@($captureSettings.ffmpeg.required_filters) -contains "tpad") -and
            ($captureSettings.soundtrack.bgm -eq "disabled") -and
            ($captureSettings.soundtrack.narration_voice -eq "zh-CN-XiaoxiaoNeural")
        if ($settingsValid) {
            Add-Result -Name "capture-settings" -Status pass -Message "PromoCaptureSurface, OBS 32.2.2, FFmpeg lock path, voice, and BGM policy are recorded"
        }
        else {
            Add-Result -Name "capture-settings" -Status fail -Message "capture-settings.json does not match the pinned production capture policy"
        }
    }
    catch {
        Add-Result -Name "capture-settings" -Status fail -Message $_.Exception.Message
    }

    $pyprojectPath = Join-Path $promoRoot "pyproject.toml"
    if (Test-Path -LiteralPath $pyprojectPath -PathType Leaf) {
        $toml = Get-Content -LiteralPath $pyprojectPath -Raw -Encoding UTF8
        $hasAdapter = $toml -match '(?m)^\s*\[project\.entry-points\."xar_promo\.adapters"\]' -and
            $toml -match '(?m)^\s*vivhite\s*=\s*"[^"]+:[^"]+"'
        $hasPreset = $toml -match '(?m)^\s*\[project\.entry-points\."xar_promo\.presets"\]' -and
            $toml -match '(?m)^\s*vivhite-player-10m\s*=\s*"[^"]+:[^"]+"'
        $hasComposer = $toml -match '(?m)^\s*\[project\.entry-points\."xar_promo\.composers"\]' -and
            $toml -match '(?m)^\s*vivhite-player-10m\s*=\s*"[^"]+:[^"]+"'
        if ($hasAdapter -and $hasPreset -and $hasComposer) {
            Add-Result -Name "entry-points" -Status pass -Message "adapter, preset, and composer are declared"
        }
        else {
            Add-Result -Name "entry-points" -Status fail -Message "required xAR adapter/preset/composer entry points are missing"
        }
    }

    foreach ($tool in @("ffmpeg", "ffprobe", "obs64")) {
        $command = $null
        $overrideVariable = switch ($tool) {
            "ffmpeg" { "XAR_PROMO_FFMPEG" }
            "ffprobe" { "XAR_PROMO_FFPROBE" }
            default { $null }
        }
        $overridePath = if ($null -ne $overrideVariable) {
            [Environment]::GetEnvironmentVariable($overrideVariable)
        }
        else {
            $null
        }
        if (-not [string]::IsNullOrWhiteSpace($overridePath)) {
            if (Test-Path -LiteralPath $overridePath -PathType Leaf) {
                $command = Get-Item -LiteralPath $overridePath
            }
            else {
                $message = "$overrideVariable points to a missing file: $overridePath"
                if ($RequireExternalTools) {
                    Add-Result -Name "tool:$tool" -Status fail -Message $message
                }
                else {
                    Add-Result -Name "tool:$tool" -Status warn -Message $message
                }
                continue
            }
        }
        if ($null -eq $command) {
            # Prefer the user's established in-place installation.  The
            # versioned side-by-side path remains a migration fallback only;
            # the hash gate below prevents it from silently replacing the
            # locked production binary.
            $knownPaths = switch ($tool) {
                "ffmpeg"  { @(
                        "C:\ffmpeg\bin\ffmpeg.exe",
                        "C:\ffmpeg\promo-9.0.1\bin\ffmpeg.exe"
                    ) }
                "ffprobe" { @(
                        "C:\ffmpeg\bin\ffprobe.exe",
                        "C:\ffmpeg\promo-9.0.1\bin\ffprobe.exe"
                    ) }
                "obs64"   { @("C:\Program Files\obs-studio\bin\64bit\obs64.exe") }
                default   { @() }
            }
            foreach ($knownPath in $knownPaths) {
                if (Test-Path -LiteralPath $knownPath -PathType Leaf) {
                    $command = Get-Item -LiteralPath $knownPath
                    break
                }
            }
        }
        if ($null -eq $command) {
            # PATH is a deliberate fallback for clean-room/CI hosts.  It is
            # still subject to the capability and SHA-256 checks below, so a
            # mutable PATH cannot silently become a production approval.
            $pathCommand = Get-Command $tool -CommandType Application -ErrorAction SilentlyContinue |
                Select-Object -First 1
            if ($null -ne $pathCommand) {
                $command = $pathCommand
            }
        }
        if ($null -eq $command) {
            # A repository-local, versioned FFmpeg bundle is acceptable for
            # diagnostics only.  Keep the search scoped to .tools/bin; never
            # scan or execute arbitrary binaries elsewhere in the workspace.
            $toolsRoot = Join-Path $root ".tools"
            if (Test-Path -LiteralPath $toolsRoot -PathType Container) {
                $bundled = Get-ChildItem -LiteralPath $toolsRoot -Recurse -File -Filter "$tool.exe" -ErrorAction SilentlyContinue |
                    Where-Object { $_.FullName -match "[\\/]bin[\\/]" } |
                    Sort-Object FullName |
                    Select-Object -First 1
                if ($null -ne $bundled) {
                    $command = $bundled
                }
            }
        }
        if ($null -eq $command) {
            if ($RequireExternalTools) {
                Add-Result -Name "tool:$tool" -Status fail -Message "not found; required for a real capture"
            }
            else {
                Add-Result -Name "tool:$tool" -Status warn -Message "not found (use -RequireExternalTools before recording)"
            }
            continue
        }

        $toolPath = if ($command.PSObject.Properties.Name -contains "Source" -and -not [string]::IsNullOrWhiteSpace([string]$command.Source)) {
            [string]$command.Source
        }
        else {
            [string]$command.FullName
        }
        $capabilityFailure = $false
        if ($tool -eq "ffmpeg") {
            # xAR's deterministic video graph uses every filter in the lock.
            # A binary that merely exists but cannot parse that graph must not
            # pass the production gate.
            $filterOutput = @(& $toolPath -hide_banner -filters 2>&1)
            $filterExit = $LASTEXITCODE
            $filterText = $filterOutput -join "`n"
            $missingFilters = @()
            if ($lockValid) {
                foreach ($requiredFilter in $requiredFilters) {
                    if ($filterText -notmatch "(?m)\b$([regex]::Escape([string]$requiredFilter))\b") {
                        $missingFilters += [string]$requiredFilter
                    }
                }
            }
            elseif ($filterExit -ne 0 -or $filterText -notmatch "(?m)\btpad\b") {
                $missingFilters += "tpad"
            }
            if ($filterExit -ne 0 -or $missingFilters.Count -gt 0) {
                $capabilityFailure = $true
                $missingText = if ($missingFilters.Count -gt 0) { $missingFilters -join ", " } else { "filter probe failed" }
                $message = "$toolPath (missing required FFmpeg filter(s): $missingText)"
                if ($RequireExternalTools) {
                    Add-Result -Name "tool:$tool" -Status fail -Message $message
                }
                else {
                    Add-Result -Name "tool:$tool" -Status warn -Message $message
                }
            }
        }

        if (-not $capabilityFailure) {
            Add-Result -Name "tool:$tool" -Status pass -Message $toolPath
        }

        if ($tool -in @("ffmpeg", "ffprobe") -and $lockValid) {
            try {
                $selectedFullPath = [IO.Path]::GetFullPath($toolPath)
                $lockedFullPath = [IO.Path]::GetFullPath([string]$lockedTools[$tool].path)
                if (-not $selectedFullPath.Equals($lockedFullPath, [StringComparison]::OrdinalIgnoreCase)) {
                    $locationMessage = "$toolPath is outside the locked install location $lockedFullPath"
                    # An explicit override is useful for diagnostics, but it
                    # must never be mistaken for the in-place production
                    # installation.  RequireExternalTools therefore keeps the
                    # gate closed unless the exact locked path is selected.
                    if ($RequireExternalTools) {
                        Add-Result -Name "tool:${tool}:location" -Status fail -Message $locationMessage
                    }
                    else {
                        Add-Result -Name "tool:${tool}:location" -Status warn -Message $locationMessage
                    }
                }
                else {
                    Add-Result -Name "tool:${tool}:location" -Status pass -Message "matches ffmpeg-lock.json install location"
                }
                $actualHash = (Get-FileHash -LiteralPath $toolPath -Algorithm SHA256).Hash.ToUpperInvariant()
                $expectedHash = [string]$lockedTools[$tool].sha256
                if ($actualHash -eq $expectedHash) {
                    Add-Result -Name "tool:${tool}:sha256" -Status pass -Message "matches ffmpeg-lock.json"
                }
                else {
                    $message = "$toolPath SHA-256 $actualHash does not match locked $expectedHash"
                    if ($RequireExternalTools) {
                        Add-Result -Name "tool:${tool}:sha256" -Status fail -Message $message
                    }
                    else {
                        Add-Result -Name "tool:${tool}:sha256" -Status warn -Message $message
                    }
                }
            }
            catch {
                if ($RequireExternalTools) {
                    Add-Result -Name "tool:${tool}:sha256" -Status fail -Message $_.Exception.Message
                }
                else {
                    Add-Result -Name "tool:${tool}:sha256" -Status warn -Message $_.Exception.Message
                }
            }
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
            $savedErrorAction = $ErrorActionPreference
            try {
                # PowerShell 5.1 promotes native stderr (for example Python's
                # harmless ``Could not find platform independent libraries``
                # notice) to an ErrorRecord when Stop is active.  Capture it
                # as diagnostic text and make the process exit code the sole
                # pass/fail signal.
                $ErrorActionPreference = "Continue"
                $testOutput = @(& $python -B -m unittest discover -s (Join-Path $promoRoot "tests") -p "test_*.py" -v 2>&1)
                $exitCode = $LASTEXITCODE
            }
            finally {
                $ErrorActionPreference = $savedErrorAction
            }
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
