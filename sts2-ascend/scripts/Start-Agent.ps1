# Unified stack start: deploy (optional) -> game -> runner/brain -> on-demand announcers.
# Runner, not this wrapper, freezes Git HEAD + active review-marker epoch into each
# Brain child; Start must not precompute or reuse those generation-local values.
[CmdletBinding()]
param(
    [string]$Version = "0.9.1",
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [ValidateSet("auto", "fork", "release")][string]$Source = "auto",
    [ValidateSet("auto", "on", "off")][string]$SteamMode = "auto",
    # Steam Cloud writes are not reliable when the client/userdata volume is
    # nearly full.  Keep a conservative, explicit floor for unattended
    # training; callers may raise it (or lower it only within the documented
    # range) for a known environment.  SteamMode=off never uses this gate.
    [ValidateRange(1048576, 1099511627776)][long]$SteamMinFreeBytes = 1GB,
    [string]$GodotExe = "",
    [switch]$SkipDeploy,
    [switch]$Foreground,
    [ValidateRange(5, 600)][int]$ReadyTimeoutSeconds = 120
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$runtimeDir = Join-Path $root ".runtime"
$sessionFile = Join-Path $runtimeDir "session.json"
$runnerPath = [IO.Path]::GetFullPath((Join-Path $root "brain\runner.py"))
$gameExe = [IO.Path]::GetFullPath((Join-Path $GameDir "SlayTheSpire2.exe"))
$gameLauncher = [IO.Path]::GetFullPath((Join-Path $GameDir "launch_vulkan.bat"))
$utf8NoBom = New-Object Text.UTF8Encoding($false)
$lifecycleLock = $null

# Detached Brain/provider children only inherit the current process environment.
# Import the user-scoped AMD credential when this shell predates the credential;
# never print or serialize its value into session.json/logs.
if ([string]::IsNullOrWhiteSpace([string]$env:AMD_RADEON_API_KEY)) {
    $amdRadeonApiKey = [Environment]::GetEnvironmentVariable(
        "AMD_RADEON_API_KEY", [EnvironmentVariableTarget]::User)
    if (-not [string]::IsNullOrWhiteSpace([string]$amdRadeonApiKey)) {
        $env:AMD_RADEON_API_KEY = [string]$amdRadeonApiKey
    }
}

function Write-Utf8Json {
    param([string]$Path, [object]$Value)
    $json = $Value | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText($Path, $json, $utf8NoBom)
}

function Read-JsonFile {
    param([string]$Path)
    try {
        if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) { return $null }
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json)
    }
    catch { return $null }
}

function Get-ObjectProperty {
    param([object]$Value, [string]$Name, [object]$Default = $null)
    if ($Value -and $Value.PSObject.Properties[$Name]) { return $Value.$Name }
    return $Default
}

function Get-GameUserDataRoot {
    # Godot's Windows user:// root for Slay the Spire 2 is the per-user
    # application-data directory.  Prefer the process value (which is also
    # what the game receives) and use the known-folder API only when a caller
    # has not supplied APPDATA.  No directory is created by this resolver.
    $appData = [string]$env:APPDATA
    if ([string]::IsNullOrWhiteSpace($appData)) {
        try { $appData = [Environment]::GetFolderPath("ApplicationData") }
        catch { $appData = "" }
    }
    if ([string]::IsNullOrWhiteSpace($appData)) { return $null }
    try {
        return [IO.Path]::GetFullPath((Join-Path $appData "SlayTheSpire2"))
    }
    catch { return $null }
}

function Test-LocalModConsent {
    # NMainMenu creates the native mod-loading confirmation only while
    # SettingsSave.ModSettings is null.  Therefore a non-null marker in the
    # local profile is the narrow, persisted evidence that this profile has
    # completed that one-time consent.  Keep this probe strictly read-only:
    # never fall back to settings.save.backup, Steam's profile, or a GUI click.
    $result = [ordered]@{
        ready = $false
        settings_path = ""
        mod_settings_present = $false
        reason = ""
    }
    $userDataRoot = Get-GameUserDataRoot
    if ([string]::IsNullOrWhiteSpace([string]$userDataRoot)) {
        $result.reason = "APPDATA is unavailable; game user directory cannot be resolved."
        return [pscustomobject]$result
    }

    try {
        $settingsPath = [IO.Path]::GetFullPath((Join-Path $userDataRoot "default\1\settings.save"))
        $result.settings_path = $settingsPath
    }
    catch {
        $result.reason = "The local default/1 settings path could not be resolved."
        return [pscustomobject]$result
    }
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        $result.reason = "settings.save is missing for the local default/1 profile."
        return [pscustomobject]$result
    }

    try {
        $settings = Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 -ErrorAction Stop |
            ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        $result.reason = "settings.save is unreadable or is not valid JSON."
        return [pscustomobject]$result
    }
    if (-not $settings -or -not $settings.PSObject.Properties["mod_settings"] -or
        $null -eq $settings.mod_settings) {
        $result.reason = "native mod-loading consent is not recorded (mod_settings is null or absent)."
        return [pscustomobject]$result
    }

    $result.ready = $true
    $result.mod_settings_present = $true
    $result.reason = "native mod-loading consent marker is present."
    return [pscustomobject]$result
}

function Get-SteamInstallRoot {
    # Steam's userdata lives beside the client, not necessarily beside the
    # game's library (this machine has the game on G: and Steam on D:).
    # Read-only registry probes cover the normal per-user and machine installs;
    # if none can be resolved we fail closed for Steam-on rather than guessing
    # a drive and risking another cloud-save loss.
    $registryKeys = @(
        "Registry::HKEY_CURRENT_USER\Software\Valve\Steam",
        "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Valve\Steam",
        "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Valve\Steam"
    )
    $candidateValues = New-Object Collections.Generic.List[string]
    foreach ($registryKey in $registryKeys) {
        try {
            $properties = Get-ItemProperty -LiteralPath $registryKey -ErrorAction Stop
            foreach ($propertyName in @("SteamPath", "InstallPath", "SteamExe")) {
                if ($properties.PSObject.Properties[$propertyName]) {
                    $value = [string]$properties.$propertyName
                    if (-not [string]::IsNullOrWhiteSpace($value)) {
                        $candidateValues.Add($value)
                    }
                }
            }
        }
        catch { }
    }

    # A caller may expose a portable client through STEAM_PATH.  This is only
    # a read-only hint; it is accepted only when the directory actually
    # exists, and never creates or modifies anything.
    if (-not [string]::IsNullOrWhiteSpace([string]$env:STEAM_PATH)) {
        $candidateValues.Add([string]$env:STEAM_PATH)
    }

    foreach ($candidate in $candidateValues) {
        $trimmed = ([string]$candidate).Trim().Trim('"')
        if ([string]::IsNullOrWhiteSpace($trimmed)) { continue }
        try { $full = [IO.Path]::GetFullPath($trimmed) }
        catch { continue }

        # SteamExe points at the executable while SteamPath/InstallPath point
        # at the directory.  Normalize both to the client root.
        if (Test-Path -LiteralPath $full -PathType Leaf) {
            try {
                if ([string]::Equals([IO.Path]::GetFileName($full), "steam.exe",
                                     [StringComparison]::OrdinalIgnoreCase)) {
                    $full = [IO.Path]::GetDirectoryName($full)
                }
            }
            catch { continue }
        }
        if ([string]::IsNullOrWhiteSpace($full) -or
            -not (Test-Path -LiteralPath $full -PathType Container)) { continue }
        try {
            $normalized = [IO.Path]::GetFullPath($full)
            $normalizedRoot = [IO.Path]::GetPathRoot($normalized)
            if ([string]::Equals($normalized, $normalizedRoot,
                                 [StringComparison]::OrdinalIgnoreCase)) {
                return $normalizedRoot
            }
            return $normalized.TrimEnd('\')
        }
        catch { }
    }
    return $null
}

function Get-AvailableFreeBytes {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path)) { return $null }
    try {
        $fullPath = [IO.Path]::GetFullPath($Path)
        $driveRoot = [IO.Path]::GetPathRoot($fullPath)
        if ([string]::IsNullOrWhiteSpace($driveRoot)) { return $null }
        $drive = New-Object System.IO.DriveInfo($driveRoot)
        if (-not $drive.IsReady) { return $null }
        return [UInt64]$drive.AvailableFreeSpace
    }
    catch { return $null }
}

function Get-SteamDiskSpaceStatus {
    param(
        [string]$Mode = "auto",
        [bool]$ColdLaunch = $true,
        [long]$MinimumFreeBytes = 1GB
    )

    $normalizedMode = ([string]$Mode).ToLowerInvariant()
    $result = [ordered]@{
        required = $false
        ready = $true
        mode = $normalizedMode
        cold_launch = $ColdLaunch
        minimum_free_bytes = [UInt64][math]::Max(0, $MinimumFreeBytes)
        free_bytes = $null
        steam_root = ""
        userdata_root = ""
        drive_root = ""
        reason = ""
    }

    # Explicit local mode has a separate user:// namespace and must not be
    # blocked by Steam's drive.  An already-running game also needs no new
    # Steam launch, so Start-Agent can attach its runner without this check.
    if ($normalizedMode -eq "off") {
        $result.reason = "SteamMode off uses the independent local profile; Steam userdata was not checked."
        return [pscustomobject]$result
    }
    if (-not $ColdLaunch) {
        $result.reason = "An existing game process will be reused; no Steam cold launch was requested."
        return [pscustomobject]$result
    }

    $result.required = $true
    if ($MinimumFreeBytes -lt 1MB) {
        $result.ready = $false
        $result.reason = "SteamMinFreeBytes must be at least 1 MiB."
        return [pscustomobject]$result
    }

    $steamRoot = Get-SteamInstallRoot
    if ([string]::IsNullOrWhiteSpace([string]$steamRoot)) {
        $result.ready = $false
        $result.reason = "Steam install root could not be resolved from the read-only registry probes."
        return [pscustomobject]$result
    }
    $result.steam_root = [string]$steamRoot
    try { $userdataRoot = [IO.Path]::GetFullPath((Join-Path $steamRoot "userdata")) }
    catch {
        $result.ready = $false
        $result.reason = "Steam userdata path could not be resolved."
        return [pscustomobject]$result
    }
    $result.userdata_root = $userdataRoot
    if (-not (Test-Path -LiteralPath $userdataRoot -PathType Container)) {
        $result.ready = $false
        $result.reason = "Steam userdata directory is missing; refusing to guess a cloud volume."
        return [pscustomobject]$result
    }

    try { $result.drive_root = [IO.Path]::GetPathRoot($userdataRoot) }
    catch { $result.drive_root = "" }
    $freeBytes = Get-AvailableFreeBytes -Path $userdataRoot
    if ($null -eq $freeBytes) {
        $result.ready = $false
        $result.reason = "Available free space for the Steam userdata volume could not be read."
        return [pscustomobject]$result
    }
    $result.free_bytes = [UInt64]$freeBytes
    if ([UInt64]$freeBytes -lt [UInt64]$MinimumFreeBytes) {
        $result.ready = $false
        $result.reason = ("Steam userdata volume has {0} bytes free, below the {1}-byte " +
                          "minimum; cloud save writes are blocked until space is reclaimed.") -f
                         [UInt64]$freeBytes, [UInt64]$MinimumFreeBytes
        return [pscustomobject]$result
    }

    $result.reason = "Steam userdata volume has enough free space for an unattended cold launch."
    return [pscustomobject]$result
}

function Get-GameLaunchArguments {
    param([string]$Mode)

    # The game's normal path (auto/on) initializes Steam as usual.  Only an
    # explicit off request is allowed to override platform initialization;
    # this keeps the local-save choice visible in the Start-Agent invocation
    # without changing the game directory or Steam client files.
    if ([string]::Equals($Mode, "off", [StringComparison]::OrdinalIgnoreCase)) {
        return @("--force-steam", "off")
    }
    return @()
}

function Normalize-SessionId {
    param([object]$Value)
    $candidate = [string]$Value
    if ($candidate -match '^[0-9a-fA-F]{32}$') { return $candidate.ToLowerInvariant() }
    return "legacy"
}

function Get-ProcessCim {
    param([int]$ProcessId)
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Test-CommandContainsPath {
    param([object]$Process, [string]$Path)
    if (-not $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    return ([string]$Process.CommandLine).IndexOf($Path, [StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Get-ScriptArgumentPattern {
    param([string]$Path)
    return '(^|[\s"])' + [regex]::Escape([IO.Path]::GetFullPath($Path)) + '(?=$|[\s"])'
}

function Test-CommandHasScriptArgument {
    param([object]$Process, [string]$Path)
    if (-not $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    if ([string]$Process.CommandLine -match '(^|\s)-m\s+py_compile(\s|$)') { return $false }
    return [regex]::IsMatch([string]$Process.CommandLine, (Get-ScriptArgumentPattern $Path),
                            [Text.RegularExpressions.RegexOptions]::IgnoreCase)
}

function Test-IsOpenCodeReviewProcess {
    param([object]$Process, [string]$WorkspaceRoot)
    if (-not $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    if ($Process.Name -notmatch '^opencode(\.exe)?$') { return $false }
    $cmd = [string]$Process.CommandLine
    $reviewRoot = Join-Path $WorkspaceRoot "knowledge\code_backups\review_work"
    $reviewRepoPattern = '(?i)(?:^|\s)--dir\s+"?' +
        [regex]::Escape($reviewRoot) +
        '[\\/]+sts2-review-sandbox-[^\\/"\s]+[\\/]+repo"?(?=$|\s)'
    return [regex]::IsMatch($cmd, $reviewRepoPattern,
                            [Text.RegularExpressions.RegexOptions]::IgnoreCase) -and
           $cmd -match '(?i)(^|\s)run(?=\s)' -and
           $cmd -match '(?i)--format\s+json(?=$|\s)' -and
           $cmd -match '(?i)--auto(?=$|\s)'
}

function Test-IsCodexReviewProcess {
    param([object]$Process, [string]$WorkspaceRoot)
    if (-not $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    if ($Process.Name -notmatch '^(codex|node|cmd)\.exe$') { return $false }
    $cmd = [string]$Process.CommandLine
    $reviewRoot = Join-Path $WorkspaceRoot "knowledge\code_backups\review_work"
    $reviewRepoPattern = '(?i)(?:^|\s)(?:-C|--cd)\s+"?' +
        [regex]::Escape($reviewRoot) +
        '[\\/]+sts2-review-sandbox-[^\\/"\s]+[\\/]+repo"?(?=$|\s)'
    return [regex]::IsMatch($cmd, $reviewRepoPattern,
                            [Text.RegularExpressions.RegexOptions]::IgnoreCase) -and
           $cmd -match '(?i)(^|\s)exec(?=\s)' -and
           $cmd -match '(?i)--json' -and $cmd -match '(?i)--ephemeral'
}

function Get-CreationKey {
    param([object]$Process)
    if (-not $Process -or -not $Process.CreationDate) { return 0L }
    return ([datetime]$Process.CreationDate).ToUniversalTime().Ticks
}

function Test-PidRecord {
    param([object]$Record, [object]$Process, [string]$ExpectedSession, [string]$CommandPattern)
    if (-not $Record -or -not $Process) { return $false }
    $recordPid = [int](Get-ObjectProperty $Record "pid" 0)
    if ($recordPid -le 0 -or $recordPid -ne [int]$Process.ProcessId) { return $false }
    if ([string](Get-ObjectProperty $Record "session_id" "legacy") -ne $ExpectedSession) { return $false }
    if ([string]$Process.CommandLine -notmatch $CommandPattern) { return $false }
    $recordExe = [string](Get-ObjectProperty $Record "executable" "")
    if (-not [string]::IsNullOrWhiteSpace($recordExe)) {
        if ([string]::IsNullOrWhiteSpace([string]$Process.ExecutablePath)) { return $false }
        try {
            $sameExe = [string]::Equals([IO.Path]::GetFullPath($recordExe),
                [IO.Path]::GetFullPath([string]$Process.ExecutablePath), [StringComparison]::OrdinalIgnoreCase)
        } catch { return $false }
        if (-not $sameExe) { return $false }
    }
    $creationFiletime = [long](Get-ObjectProperty $Record "creation_filetime" 0)
    if ($creationFiletime -gt 0 -and $Process.CreationDate) {
        $actualFiletime = ([datetime]$Process.CreationDate).ToUniversalTime().ToFileTimeUtc()
        if ([math]::Abs($actualFiletime - $creationFiletime) -gt 10000) { return $false }
        return $true
    }
    $createdUnix = [double](Get-ObjectProperty $Record "created_unix" 0)
    if ($createdUnix -gt 0 -and $Process.CreationDate) {
        $epoch = [datetime]::SpecifyKind([datetime]"1970-01-01", [DateTimeKind]::Utc)
        $actualUnix = ([datetime]$Process.CreationDate).ToUniversalTime().Subtract($epoch).TotalSeconds
        if ([math]::Abs($actualUnix - $createdUnix) -gt 1) { return $false }
    }
    return $true
}

function Get-GameProcesses {
    return @(Get-CimInstance Win32_Process -Filter "Name='SlayTheSpire2.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ExecutablePath -and
            [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath), $gameExe,
                             [StringComparison]::OrdinalIgnoreCase)
        })
}

function Get-ReadyApiPort {
    foreach ($port in 8080..8084) {
        $response = $null
        try {
            $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$port/health")
            $request.Timeout = 700
            $request.ReadWriteTimeout = 700
            $response = $request.GetResponse()
            if ([int]$response.StatusCode -eq 200) {
                $reader = New-Object IO.StreamReader($response.GetResponseStream())
                try {
                    $payload = $reader.ReadToEnd() | ConvertFrom-Json
                    if ($payload -and $payload.data -and $payload.data.status -eq "ready") { return $port }
                } finally { $reader.Dispose() }
            }
        } catch { }
        finally { if ($response) { $response.Close() } }
    }
    return $null
}

function Add-UniquePath {
    param(
        [Collections.Generic.List[string]]$List,
        [string]$Value,
        [switch]$Directory
    )
    if ($null -eq $List -or [string]::IsNullOrWhiteSpace($Value)) { return }
    $candidate = $Value.Trim().Trim('"')
    if ([string]::IsNullOrWhiteSpace($candidate) -or $candidate -match '^(?i)registry::') {
        return
    }
    try { $candidate = [IO.Path]::GetFullPath($candidate) } catch { return }
    if ($Directory) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Container)) { return }
    } elseif (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        return
    }
    foreach ($existing in $List) {
        if ([string]::Equals($existing, $candidate, [StringComparison]::OrdinalIgnoreCase)) {
            return
        }
    }
    $List.Add($candidate)
}

function Invoke-PythonRuntimeProbe {
    param(
        [string]$PythonExe,
        [string]$PythonHome = ""
    )

    # Do not trust sys.prefix alone: a copied/embeddable python.exe can exit 0
    # while pointing at the current working directory and still emit the
    # "platform independent libraries <prefix>" warning.  Import encodings,
    # json and pathlib, then return their actual origins for a path-bound check.
    $probeCode = @'
import encodings
import json
import pathlib
import sys
import sysconfig

stdlib = pathlib.Path(sysconfig.get_path("stdlib")).resolve()
encoding_file = pathlib.Path(encodings.__file__).resolve()
if not stdlib.is_dir() or not encoding_file.is_file():
    raise RuntimeError("stdlib probe did not resolve to files")
payload = {
    "executable": str(pathlib.Path(sys.executable).resolve()),
    "prefix": str(pathlib.Path(sys.prefix).resolve()),
    "base_prefix": str(pathlib.Path(sys.base_prefix).resolve()),
    "stdlib": str(stdlib),
    "encodings": str(encoding_file),
    "version": [int(sys.version_info[0]), int(sys.version_info[1])],
    "path": [str(pathlib.Path(item).resolve()) for item in sys.path if item],
}
print(json.dumps(payload, separators=(",", ":")))
'@
    # PowerShell's native argument conversion can strip quotes from a
    # multi-line -c payload.  Encode the probe so the exact Python source
    # reaches the child on Windows PowerShell 5.1 as well as pwsh.
    $probeEncoded = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($probeCode))
    $probeShim = "exec(__import__('base64').b64decode('$probeEncoded'))"
    $oldHome = [Environment]::GetEnvironmentVariable("PYTHONHOME", "Process")
    $oldPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    $lines = @()
    $pythonExit = -1
    try {
        if ([string]::IsNullOrWhiteSpace($PythonHome)) {
            [Environment]::SetEnvironmentVariable("PYTHONHOME", $null, "Process")
        } else {
            [Environment]::SetEnvironmentVariable("PYTHONHOME", $PythonHome, "Process")
        }
        # PYTHONPATH can make a broken interpreter appear healthy by importing
        # project-local shims.  The production child inherits the caller's
        # value only after the selected home has passed this clean probe.
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $null, "Process")
        $savedPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "SilentlyContinue"
            $lines = @(& $PythonExe -S -c $probeShim 2>$null)
            $pythonExit = $LASTEXITCODE
        } finally {
            $ErrorActionPreference = $savedPreference
        }
    } catch {
        $lines = @()
        $pythonExit = -1
    } finally {
        [Environment]::SetEnvironmentVariable("PYTHONHOME", $oldHome, "Process")
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $oldPath, "Process")
    }
    if ($pythonExit -ne 0 -or $lines.Count -eq 0) { return $null }
    for ($index = $lines.Count - 1; $index -ge 0; $index--) {
        try {
            $payload = ([string]$lines[$index]).Trim() | ConvertFrom-Json -ErrorAction Stop
            if ($payload -and $payload.stdlib -and $payload.encodings) { return $payload }
        } catch { }
    }
    return $null
}

function Test-PythonPathWithin {
    param([string]$Child, [string]$Parent)
    if ([string]::IsNullOrWhiteSpace($Child) -or [string]::IsNullOrWhiteSpace($Parent)) {
        return $false
    }
    try {
        $childFull = [IO.Path]::GetFullPath($Child).TrimEnd('\')
        $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\')
    } catch { return $false }
    if ([string]::Equals($childFull, $parentFull, [StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $childFull.StartsWith($parentFull + '\', [StringComparison]::OrdinalIgnoreCase)
}

function Get-PythonRegistryPaths {
    $roots = @(
        "Registry::HKEY_CURRENT_USER\Software\Python\PythonCore",
        "Registry::HKEY_LOCAL_MACHINE\Software\Python\PythonCore",
        "Registry::HKEY_CURRENT_USER\Software\WOW6432Node\Python\PythonCore",
        "Registry::HKEY_LOCAL_MACHINE\Software\WOW6432Node\Python\PythonCore"
    )
    $paths = New-Object Collections.Generic.List[string]
    foreach ($registryRoot in $roots) {
        $versions = @(Get-ChildItem -LiteralPath $registryRoot -ErrorAction SilentlyContinue)
        foreach ($version in $versions) {
            $installKey = Join-Path $version.PSPath "InstallPath"
            $install = Get-ItemProperty -LiteralPath $installKey -ErrorAction SilentlyContinue
            if ($install) {
                foreach ($propertyName in @("ExecutablePath", "(default)")) {
                    if ($install.PSObject.Properties[$propertyName]) {
                        $paths.Add([string]$install.$propertyName)
                    }
                }
            }
            $pythonPathKey = Join-Path $version.PSPath "PythonPath"
            $pythonPath = Get-ItemProperty -LiteralPath $pythonPathKey -ErrorAction SilentlyContinue
            if ($pythonPath -and $pythonPath.PSObject.Properties["(default)"]) {
                foreach ($entry in ([string]$pythonPath."(default)" -split ';')) {
                    $paths.Add($entry)
                }
            }
        }
    }
    return @($paths)
}

function Get-PythonRuntime {
    $launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue
    if (-not $launcher) {
        throw "Python 3 launcher unavailable: expected 'py -3'."
    }

    $exeCandidates = New-Object Collections.Generic.List[string]
    $homeCandidates = New-Object Collections.Generic.List[string]
    $registryPaths = @(Get-PythonRegistryPaths)

    # Keep a caller-provided home as a candidate, but accept it only after the
    # executable proves that its standard library actually comes from there.
    Add-UniquePath $homeCandidates ([Environment]::GetEnvironmentVariable("PYTHONHOME", "Process")) -Directory

    $launcherExeLines = @()
    $launcherExit = -1
    $savedPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        $launcherExeLines = @(& $launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null)
        $launcherExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $savedPreference }
    if ($launcherExit -eq 0 -and $launcherExeLines.Count -gt 0) {
        Add-UniquePath $exeCandidates ([string]$launcherExeLines[-1])
    }
    # py -0p exposes installations the default launcher selection may hide.
    $allLauncherLines = @()
    try {
        $ErrorActionPreference = "SilentlyContinue"
        $allLauncherLines = @(& $launcher.Source -0p 2>$null)
    } finally { $ErrorActionPreference = $savedPreference }
    foreach ($line in $allLauncherLines) {
        if ([string]$line -match '(?i)([A-Z]:\\.*?\.exe)\s*$') {
            Add-UniquePath $exeCandidates $Matches[1]
        }
    }
    foreach ($registryPath in $registryPaths) {
        if ([string]$registryPath -match '(?i)\.exe\s*$') {
            Add-UniquePath $exeCandidates $registryPath
        }
        foreach ($entry in ([string]$registryPath -split ';')) {
            Add-UniquePath $homeCandidates $entry -Directory
        }
    }
    $pathPython = Get-Command python.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($pathPython) { Add-UniquePath $exeCandidates $pathPython.Source }

    # A complete install is normally adjacent to the executable.  Dynamic
    # environment roots cover per-user and machine installs without embedding
    # an account name or assuming a drive letter.
    $dynamicRoots = @()
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $dynamicRoots += Join-Path $env:LOCALAPPDATA "Programs\Python"
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $dynamicRoots += Join-Path $env:ProgramFiles "Python"
    }
    if (-not [string]::IsNullOrWhiteSpace(${env:ProgramFiles(x86)})) {
        $dynamicRoots += Join-Path ${env:ProgramFiles(x86)} "Python"
    }
    foreach ($dynamicRoot in $dynamicRoots) {
        foreach ($installDir in @(Get-ChildItem -LiteralPath $dynamicRoot -Directory -ErrorAction SilentlyContinue)) {
            Add-UniquePath $homeCandidates $installDir.FullName -Directory
            Add-UniquePath $exeCandidates (Join-Path $installDir.FullName "python.exe")
        }
    }

    if ($exeCandidates.Count -eq 0) {
        throw "Python 3 executable discovery returned no candidates."
    }

    # First collect each executable's own adjacent home and the paths emitted
    # by an unconfigured probe.  This handles a registry entry whose
    # ExecutablePath points at a copied binary while PythonPath points at the
    # complete installation.
    $probeCache = @{}
    foreach ($pythonExe in @($exeCandidates)) {
        $exeParent = Split-Path $pythonExe -Parent
        Add-UniquePath $homeCandidates $exeParent -Directory
        $probe = Invoke-PythonRuntimeProbe $pythonExe
        if ($probe) {
            $probeCache[$pythonExe] = $probe
            foreach ($pathEntry in @($probe.path)) {
                $entry = [string]$pathEntry
                if ($entry -match '(?i)[\\/]Lib$' -or $entry -match '(?i)[\\/]DLLs$') {
                    Add-UniquePath $homeCandidates (Split-Path $entry -Parent) -Directory
                }
            }
            Add-UniquePath $homeCandidates ([string]$probe.prefix) -Directory
            Add-UniquePath $homeCandidates ([string]$probe.base_prefix) -Directory
            Add-UniquePath $homeCandidates (Split-Path ([string]$probe.stdlib) -Parent) -Directory
        }
    }

    foreach ($pythonExe in @($exeCandidates)) {
        $homesForExe = New-Object Collections.Generic.List[string]
        foreach ($homeCandidate in $homeCandidates) {
            Add-UniquePath $homesForExe $homeCandidate -Directory
        }
        # Empty home means “use the executable's own compiled search path” and
        # is intentionally tested last for a deterministic self-contained exe.
        $homesForExe.Add("")
        foreach ($pythonHome in $homesForExe) {
            $probe = if ($pythonHome -eq "" -and $probeCache.ContainsKey($pythonExe)) {
                $probeCache[$pythonExe]
            } else { Invoke-PythonRuntimeProbe $pythonExe $pythonHome }
            if (-not $probe) { continue }
            $version = @($probe.version)
            if ($version.Count -lt 2 -or [int]$version[0] -ne 3 -or [int]$version[1] -lt 10) {
                continue
            }
            $stdlib = [string]$probe.stdlib
            $encodings = [string]$probe.encodings
            if (-not (Test-Path -LiteralPath $stdlib -PathType Container) -or
                -not (Test-Path -LiteralPath $encodings -PathType Leaf) -or
                -not (Test-PythonPathWithin $encodings $stdlib)) {
                continue
            }
            $resolvedHome = if ([string]::IsNullOrWhiteSpace($pythonHome)) {
                [string]$probe.prefix
            } else { $pythonHome }
            if (-not (Test-PythonPathWithin $stdlib $resolvedHome)) { continue }
            return [pscustomobject]@{
                Executable = [IO.Path]::GetFullPath($pythonExe)
                Home = [IO.Path]::GetFullPath($resolvedHome)
                Stdlib = [IO.Path]::GetFullPath($stdlib)
                Version = ((@($version[0], $version[1]) -join "."))
                Source = if ($pythonHome -eq "") { "executable" } else { "resolved_home" }
            }
        }
    }
    throw ("No complete Python 3.10+ runtime was found. Every candidate failed " +
           "the encodings/json/pathlib stdlib probe; refusing to start runner/brain.")
}

function Get-PythonExe {
    param([object]$Runtime = $null)
    # Compatibility wrapper for callers/tests that only need the executable.
    if ($Runtime -and $Runtime.Executable) { return [string]$Runtime.Executable }
    return (Get-PythonRuntime).Executable
}

function Test-DotnetSdkAvailable {
    param([string]$DotnetExe)
    if ([string]::IsNullOrWhiteSpace($DotnetExe) -or
        -not (Test-Path -LiteralPath $DotnetExe -PathType Leaf)) {
        return $false
    }

    $sdkLines = @()
    $dotnetExit = -1
    $savedPreference = $ErrorActionPreference
    try {
        # A runtime-only dotnet host exits successfully but returns no SDKs.
        # Probe the concrete executable so an unusable PATH entry cannot mask
        # the per-user SDK installation.
        $ErrorActionPreference = "SilentlyContinue"
        $sdkLines = @(& $DotnetExe --list-sdks 2>$null)
        $dotnetExit = $LASTEXITCODE
    }
    catch { return $false }
    finally { $ErrorActionPreference = $savedPreference }

    if ($dotnetExit -ne 0) { return $false }
    return @($sdkLines | Where-Object {
        ([string]$_).Trim() -match '^\d+\.\d+\.\d+[^\s]*\s+\[[^\]]+\]$'
    }).Count -gt 0
}

function Initialize-DotnetSdkEnvironment {
    $pathDotnet = Get-Command dotnet.exe -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($pathDotnet -and (Test-DotnetSdkAvailable $pathDotnet.Source)) {
        # A working PATH is authoritative. Do not rewrite an environment the
        # caller has already configured successfully.
        return [IO.Path]::GetFullPath($pathDotnet.Source)
    }

    $candidates = New-Object Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($env:DOTNET_ROOT)) {
        $candidates.Add((Join-Path $env:DOTNET_ROOT "dotnet.exe"))
    }
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $candidates.Add((Join-Path $env:LOCALAPPDATA "Microsoft\dotnet\dotnet.exe"))
    }

    $seen = @{}
    foreach ($candidate in $candidates) {
        try { $candidate = [IO.Path]::GetFullPath($candidate) }
        catch { continue }
        if ($seen.ContainsKey($candidate)) { continue }
        $seen[$candidate] = $true
        if (-not (Test-DotnetSdkAvailable $candidate)) { continue }

        $candidateRoot = [IO.Path]::GetFullPath((Split-Path $candidate -Parent))
        $env:DOTNET_ROOT = $candidateRoot
        $remainingPath = @(([string]$env:PATH) -split ';' | Where-Object {
            $isCandidateRoot = $false
            if (-not [string]::IsNullOrWhiteSpace($_)) {
                try {
                    $isCandidateRoot = [string]::Equals(
                        [IO.Path]::GetFullPath($_), $candidateRoot,
                        [StringComparison]::OrdinalIgnoreCase)
                }
                catch { $isCandidateRoot = $false }
            }
            return -not $isCandidateRoot
        })
        # The fork build invokes bare `dotnet`.  A validated root that merely
        # appears later in PATH still loses to an earlier runtime-only host, so
        # always move it to the first position and remove every later duplicate.
        $env:PATH = (@($candidateRoot) + $remainingPath) -join ';'
        Write-Host "Using .NET SDK from $candidateRoot"
        return $candidate
    }

    throw ("It was not possible to find any installed .NET SDKs for local fork deployment. " +
           "Install an SDK, expose a working dotnet on PATH, or install it under " +
           "LOCALAPPDATA\Microsoft\dotnet.")
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
try {
    $lockPath = Join-Path $runtimeDir "lifecycle.lock"
    try {
        $lifecycleLock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate,
                                        [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch {
        throw "Another Start-Agent/Stop-Agent operation is in progress."
    }

    # Idempotency: reuse only the runner recorded for this workspace/session.
    $existingSession = Read-JsonFile $sessionFile
    $existingSessionId = Normalize-SessionId (Get-ObjectProperty $existingSession "session_id" "legacy")
    $existingRunnerId = [int](Get-ObjectProperty $existingSession "runner_pid" 0)
    $existingRunnerPidFile = if ($existingSessionId -eq "legacy") {
        Join-Path $runtimeDir "runner.pid"
    } else { Join-Path $runtimeDir "runner.$existingSessionId.pid" }
    $existingRunnerRecord = Read-JsonFile $existingRunnerPidFile
    if ($existingRunnerRecord -and
        [string](Get-ObjectProperty $existingRunnerRecord "session_id" "legacy") -eq $existingSessionId) {
        $existingRunnerId = [int](Get-ObjectProperty $existingRunnerRecord "pid" $existingRunnerId)
    }
    if ($existingSession -and $existingRunnerId -gt 0) {
        $existingRunner = Get-ProcessCim $existingRunnerId
        $expectedCreation = [long](Get-ObjectProperty $existingSession "runner_creation_key" 0)
        $runnerArgPattern = Get-ScriptArgumentPattern $runnerPath
        $recordValid = $existingRunnerRecord -and
            (Test-PidRecord $existingRunnerRecord $existingRunner $existingSessionId $runnerArgPattern)
        if ($existingRunner -and (Test-CommandHasScriptArgument $existingRunner $runnerPath) -and
            ($recordValid -or ($expectedCreation -gt 0 -and
             (Get-CreationKey $existingRunner) -eq $expectedCreation))) {
            $existingStopFile = if ($existingSessionId -eq "legacy") {
                Join-Path $runtimeDir "stop.request"
            } else { Join-Path $runtimeDir "stop.$existingSessionId.request" }
            if (Test-Path -LiteralPath $existingStopFile) {
                throw "Session $existingSessionId is already stopping (runner pid $existingRunnerId). Wait briefly or run Stop-Agent.ps1 again."
            }
            $game = @(Get-GameProcesses)
            Write-Host "sts2-ascend is already running (session $existingSessionId, runner pid $existingRunnerId, game count $($game.Count))."
            return
        }
    }

    # A crashed supervisor can leave its brain child alive. Its argv is only
    # "-m brain", so use the session-scoped PID record rather than a broad Python scan.
    $existingBrainPidFile = if ($existingSessionId -eq "legacy") {
        Join-Path $runtimeDir "brain.pid"
    } else { Join-Path $runtimeDir "brain.$existingSessionId.pid" }
    $existingBrainRecord = Read-JsonFile $existingBrainPidFile
    $existingBrainId = [int](Get-ObjectProperty $existingBrainRecord "pid" 0)
    if ($existingBrainId -gt 0) {
        $existingBrain = Get-ProcessCim $existingBrainId
        if (Test-PidRecord $existingBrainRecord $existingBrain $existingSessionId '(^|\s)-m\s+brain(\s|$)') {
            throw "A brain process from session $existingSessionId is still alive (pid $existingBrainId) without its recorded runner. Run Stop-Agent.ps1 first."
        }
    }

    # Recover orphan brains even if session.json is missing/corrupt.
    foreach ($brainPidFile in @(Get-ChildItem -LiteralPath $runtimeDir -Filter "brain*.pid" -File -ErrorAction SilentlyContinue)) {
        $record = Read-JsonFile $brainPidFile.FullName
        $recordId = [int](Get-ObjectProperty $record "pid" 0)
        if ($recordId -le 0) { continue }
        $hasCreationIdentity = [long](Get-ObjectProperty $record "creation_filetime" 0) -gt 0 -or
                               [double](Get-ObjectProperty $record "created_unix" 0) -gt 0
        if (-not $hasCreationIdentity) { continue }
        $recordSession = Normalize-SessionId (Get-ObjectProperty $record "session_id" "legacy")
        $recordProcess = Get-ProcessCim $recordId
        if (Test-PidRecord $record $recordProcess $recordSession '(^|\s)-m\s+brain(\s|$)') {
            throw "Residual brain process exists (session $recordSession, pid $recordId). Run Stop-Agent.ps1 before starting a new session."
        }
    }

    # Refuse to replace an older session while scoped detached components still live.
    $componentPaths = @(
        (Join-Path $root "brain\runner.py"), (Join-Path $root "brain\review_viewer.py"),
        (Join-Path $root "brain\llm_review.py"), (Join-Path $root "tts\quipper.py"),
        (Join-Path $root "tts\edge_speaker.py"), (Join-Path $root "tts\nano_speaker.py"),
        (Join-Path $root "tts\speaker.py"), (Join-Path $root "tts\speak_once.py")
    )
    $scoped = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $process = $_
        $cmd = [string]$process.CommandLine
        $scriptMatch = $false
        if ($process.Name -match '^(python(?:w|\d+(?:\.\d+)*)?|py|uv)\.exe$') {
            foreach ($path in $componentPaths) {
                if (Test-CommandHasScriptArgument $process $path) { $scriptMatch = $true; break }
            }
        }
        $reviewMatch = (($process.Name -match '^opencode(\.exe)?$' -and $cmd -and
            (Test-CommandHasScriptArgument $process (Split-Path $root -Parent)) -and
            $cmd -match '--auto' -and $cmd -match 'sts2-ascend') -or
            (Test-IsCodexReviewProcess $process $root))
        $reviewMatch = ((Test-IsOpenCodeReviewProcess $process $root) -or
                        (Test-IsCodexReviewProcess $process $root))
        $legacyRunnerMatch = $process.Name -match '^(python(?:w|\d+(?:\.\d+)*)?|py)\.exe$' -and
            $cmd -match '(?i)(^|[\s"''])brain[\\/]runner\.py(?=$|[\s"''])' -and
            $cmd -notmatch '(^|\s)-m\s+py_compile(\s|$)'
        $scriptMatch -or $reviewMatch -or $legacyRunnerMatch
    })
    if ($scoped.Count -gt 0) {
        $ids = ($scoped | ForEach-Object { $_.ProcessId }) -join ","
        throw "Residual sts2-ascend processes exist (pid $ids). Run Stop-Agent.ps1 before starting a new session."
    }

    # Luna is pinned to a non-global Codex CLI whose Windows filesystem helper
    # can read ordinary drive paths.  Cold starts repair/validate the
    # user cache before Brain loads config.  Failure does not block game/live
    # recovery: the exact configured binary remains absent, so Luna is reported
    # unavailable and no incompatible Codex process can consume model tokens.
    $codexCompatInstaller = Join-Path $PSScriptRoot "Install-CodexCompat.ps1"
    try {
        $codexCompatBinary = & $codexCompatInstaller | Select-Object -Last 1
        Write-Host "Pinned Codex compatibility CLI ready: $codexCompatBinary"
    }
    catch {
        Write-Warning ("Pinned Codex compatibility CLI unavailable; Luna will remain unavailable " +
                       "without starting a provider: " + $_.Exception.Message)
    }

    # Resolve and validate the interpreter before deployment or game launch.
    # In particular, the Windows launcher may return a copied python.exe whose
    # compiled prefix is missing; Get-PythonRuntime binds it to a probed,
    # complete home or fails closed without starting the stack.
    $pythonRuntime = Get-PythonRuntime
    $pythonExe = Get-PythonExe -Runtime $pythonRuntime
    $pythonHome = [string]$pythonRuntime.Home
    $pythonStdlib = [string]$pythonRuntime.Stdlib

    $game = @(Get-GameProcesses)
    $steamModeIsOff = [string]::Equals($SteamMode, "off", [StringComparison]::OrdinalIgnoreCase)
    if ($steamModeIsOff -and $game.Count -gt 0) {
        throw ("SteamMode off requires a cold game launch; the existing game process " +
               "cannot be switched retroactively. Run the unified Stop-Agent.ps1, " +
               "then retry so the local profile and --force-steam off are applied together.")
    }
    if ($steamModeIsOff) {
        $localConsent = Test-LocalModConsent
        if (-not $localConsent.ready) {
            $consentPath = [string]$localConsent.settings_path
            if ([string]::IsNullOrWhiteSpace($consentPath)) { $consentPath = "<unresolved>" }
            $consentReason = [string]$localConsent.reason
            throw ("SteamMode off refused before game launch: native mod-loading consent " +
                   "is not recorded at {0} ({1}). Manual human confirmation is required: " +
                   "launch this local profile " +
                   "once and accept the native mod confirmation, then exit and retry. " +
                   "Start-Agent will not click GUI/UAC, write settings, or copy Steam saves." -f
                   $consentPath, $consentReason)
        }
        Write-Host ("SteamMode off consent preflight passed (read-only marker: {0})." -f
                    [string]$localConsent.settings_path)
    }
    $steamDiskStatus = Get-SteamDiskSpaceStatus -Mode $SteamMode `
        -ColdLaunch:($game.Count -eq 0) -MinimumFreeBytes $SteamMinFreeBytes
    if (-not $steamDiskStatus.ready) {
        $diskRoot = [string](Get-ObjectProperty $steamDiskStatus "drive_root" "<unknown>")
        $userdataRoot = [string](Get-ObjectProperty $steamDiskStatus "userdata_root" "<unknown>")
        $diskReason = [string](Get-ObjectProperty $steamDiskStatus "reason" "unknown disk-space error")
        throw ("SteamMode {0} startup refused before deploy/game launch: {1} " +
               "(userdata={2}, drive={3}, minimum_free_bytes={4}). " +
               "Reclaim space on the Steam userdata volume and retry; " +
               "Start-Agent will not delete files, alter Steam, invoke GUI, or request UAC." -f
               $SteamMode.ToLowerInvariant(), $diskReason, $userdataRoot, $diskRoot,
               $SteamMinFreeBytes)
    }
    if ($steamDiskStatus.required) {
        Write-Host ("Steam userdata disk preflight passed (drive={0}, free_bytes={1}, minimum_free_bytes={2})." -f
                    [string]$steamDiskStatus.drive_root,
                    [string]$steamDiskStatus.free_bytes,
                    [string]$steamDiskStatus.minimum_free_bytes)
    }
    if (-not $SkipDeploy) {
        if ($game.Count -gt 0) {
            throw "The game is already running, so its mod DLL may be locked. Close it or use -SkipDeploy."
        }
        $deployArgs = @{
            Version = $Version
            GameDir = $GameDir
            Source = $Source
        }
        if (-not [string]::IsNullOrWhiteSpace($GodotExe)) { $deployArgs.GodotExe = $GodotExe }
        $usesLocalFork = ($Source -eq "fork") -or
            ($Source -eq "auto" -and
             (Test-Path -LiteralPath (Join-Path $root "third_party\STS2-Agent\.git")))
        if ($usesLocalFork) { Initialize-DotnetSdkEnvironment | Out-Null }
        & (Join-Path $PSScriptRoot "Deploy-Mod.ps1") @deployArgs
    }

    if (-not (Test-Path -LiteralPath $gameLauncher)) {
        throw "Vulkan launcher not found: $gameLauncher"
    }
    if (-not (Test-Path -LiteralPath $gameExe)) {
        throw "Game executable not found: $gameExe"
    }
    $gameLaunchArguments = @(Get-GameLaunchArguments -Mode $SteamMode)
    $steamModeApplied = ($game.Count -eq 0)
    $steamLaunchDescription = if ($gameLaunchArguments.Count -eq 0) {
        "<game default>"
    } else {
        $gameLaunchArguments -join " "
    }
    $sessionId = [Guid]::NewGuid().ToString("N")
    $stopFile = Join-Path $runtimeDir "stop.$sessionId.request"
    $runnerPidFile = Join-Path $runtimeDir "runner.$sessionId.pid"
    $brainPidFile = Join-Path $runtimeDir "brain.$sessionId.pid"
    $runnerOut = Join-Path $runtimeDir "runner.$sessionId.out.log"
    $runnerErr = Join-Path $runtimeDir "runner.$sessionId.err.log"

    # A GUID-scoped sentinel prevents a late old process from being revived by a new start (ABA).
    Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue

    $previousEnv = @{
        Session = $env:STS2_ASCEND_SESSION_ID
        Runtime = $env:STS2_ASCEND_RUNTIME_DIR
        Stop = $env:STS2_ASCEND_STOP_FILE
        GameLauncher = $env:STS2_ASCEND_GAME_LAUNCHER
        PythonHome = [Environment]::GetEnvironmentVariable("PYTHONHOME", "Process")
        PythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    }
    $env:STS2_ASCEND_SESSION_ID = $sessionId
    $env:STS2_ASCEND_RUNTIME_DIR = $runtimeDir
    $env:STS2_ASCEND_STOP_FILE = $stopFile
    $env:STS2_ASCEND_GAME_LAUNCHER = $gameLauncher
    # Runner uses this process environment for its child Brain generations.
    # A validated home is mandatory; clear PYTHONPATH so a stale project/user
    # shim cannot shadow the standard library that just passed the probe.
    $env:PYTHONHOME = $pythonHome
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

    if ($game.Count -eq 0) {
        Write-Host ("Launching Slay the Spire 2 (Vulkan; SteamMode={0}; args={1})..." -f
                    $SteamMode.ToLowerInvariant(), $steamLaunchDescription)
        if ($gameLaunchArguments.Count -gt 0) {
            Start-Process -FilePath $gameLauncher -ArgumentList $gameLaunchArguments `
                -WorkingDirectory $GameDir -WindowStyle Hidden | Out-Null
        } else {
            Start-Process -FilePath $gameLauncher -WorkingDirectory $GameDir -WindowStyle Hidden | Out-Null
        }
    } else {
        Write-Host ("Game already running (pid {0}); SteamMode={1} was not applied to the existing process." -f
                    $game[0].ProcessId, $SteamMode.ToLowerInvariant())
    }

    $session = [ordered]@{
        session_id = $sessionId
        state = "starting"
        started_at = (Get-Date).ToString("o")
        root = $root
        game_dir = [IO.Path]::GetFullPath($GameDir)
        game_exe = $gameExe
        python_exe = $pythonExe
        python_home = $pythonHome
        python_stdlib = $pythonStdlib
        python_version = [string]$pythonRuntime.Version
        python_runtime_source = [string]$pythonRuntime.Source
        runner_path = $runnerPath
        steam_mode = $SteamMode.ToLowerInvariant()
        steam_launch_arguments = @($gameLaunchArguments)
        steam_mode_applied = $steamModeApplied
        steam_disk_required = [bool]$steamDiskStatus.required
        steam_disk_ready = [bool]$steamDiskStatus.ready
        steam_min_free_bytes = [UInt64]$steamDiskStatus.minimum_free_bytes
        steam_free_bytes = if ($null -eq $steamDiskStatus.free_bytes) { $null } else { [UInt64]$steamDiskStatus.free_bytes }
        steam_userdata_root = [string]$steamDiskStatus.userdata_root
        steam_userdata_drive = [string]$steamDiskStatus.drive_root
        steam_disk_reason = [string]$steamDiskStatus.reason
        runner_pid = 0
        runner_creation_key = 0
        runner_pid_file = $runnerPidFile
        brain_pid_file = $brainPidFile
        stop_file = $stopFile
    }
    Write-Utf8Json $sessionFile $session

    try {
        if ($Foreground) {
            $session.state = "foreground"
            Write-Utf8Json $sessionFile $session
            $lifecycleLock.Dispose()
            $lifecycleLock = $null
            Write-Host "Starting runner in foreground. Use Stop-Agent.ps1 for a complete stack stop."
            & $pythonExe -u $runnerPath
            exit $LASTEXITCODE
        }

        $quotedRunner = '"' + $runnerPath + '"'
        $runner = Start-Process -FilePath $pythonExe -ArgumentList @("-u", $quotedRunner) `
            -WorkingDirectory $root -WindowStyle Hidden `
            -RedirectStandardOutput $runnerOut -RedirectStandardError $runnerErr -PassThru
        $session.runner_pid = $runner.Id
        $runnerCim = $null
        $runnerIdentityDeadline = (Get-Date).AddSeconds(5)
        do {
            $runnerCim = Get-ProcessCim $runner.Id
            if ($runnerCim) { break }
            Start-Sleep -Milliseconds 100
        } while ((Get-Date) -lt $runnerIdentityDeadline)
        $session.runner_creation_key = Get-CreationKey $runnerCim
        $session.state = "running"
        Write-Utf8Json $sessionFile $session
        Write-Host "Runner started in background (pid $($runner.Id), session $sessionId)."
        # Session metadata is now durable; release the mutex so Stop-Agent can cancel a slow boot.
        $lifecycleLock.Dispose()
        $lifecycleLock = $null

        $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
        $brainReady = $false
        $apiPort = $null
        do {
            $brainReady = $false
            $runner.Refresh()
            if (Test-Path -LiteralPath $stopFile) {
                Write-Host "Startup was cancelled by Stop-Agent.ps1."
                return
            }
            if ($runner.HasExited) {
                $tail = ""
                if (Test-Path -LiteralPath $runnerErr) {
                    $tail = (Get-Content -LiteralPath $runnerErr -Tail 20 -Encoding UTF8) -join [Environment]::NewLine
                }
                throw "Runner exited during startup (code $($runner.ExitCode)). $tail"
            }
            $brainRecord = Read-JsonFile $brainPidFile
            $brainRecordId = [int](Get-ObjectProperty $brainRecord "pid" 0)
            if ($brainRecordId -gt 0) {
                $brainProcess = Get-ProcessCim $brainRecordId
                $brainStage = [string](Get-ObjectProperty $brainRecord "stage" "")
                $brainReady = (Test-PidRecord $brainRecord $brainProcess $sessionId '(^|\s)-m\s+brain(\s|$)') -and
                    ($brainStage -eq "ready")
            }
            $apiPort = Get-ReadyApiPort
            if ($brainReady -and $apiPort) { break }
            Start-Sleep -Milliseconds 500
        } while ((Get-Date) -lt $deadline)

        if ($brainReady -and $apiPort) {
            Write-Host "Stack ready: brain active, API http://127.0.0.1:$apiPort."
        } else {
            Write-Warning "Runner is active but readiness timed out (brain=$brainReady, api=$apiPort). It will keep self-healing in the background."
        }
        Write-Host "ASCEND-VISION starts with brain and is supervised for self-healing; Quipper starts when its voice model is available; review OpenCode/speaker remain on demand."
        Write-Host "Brain hotkeys (global): Ctrl+Alt+F9 = stop / hand control to player; Ctrl+Alt+F10 = start / resume."
        Write-Host "Stop the complete stack with: powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1"
    } finally {
        if ($null -eq $previousEnv.Session) { Remove-Item Env:STS2_ASCEND_SESSION_ID -ErrorAction SilentlyContinue }
        else { $env:STS2_ASCEND_SESSION_ID = $previousEnv.Session }
        if ($null -eq $previousEnv.Runtime) { Remove-Item Env:STS2_ASCEND_RUNTIME_DIR -ErrorAction SilentlyContinue }
        else { $env:STS2_ASCEND_RUNTIME_DIR = $previousEnv.Runtime }
        if ($null -eq $previousEnv.Stop) { Remove-Item Env:STS2_ASCEND_STOP_FILE -ErrorAction SilentlyContinue }
        else { $env:STS2_ASCEND_STOP_FILE = $previousEnv.Stop }
        if ($null -eq $previousEnv.GameLauncher) { Remove-Item Env:STS2_ASCEND_GAME_LAUNCHER -ErrorAction SilentlyContinue }
        else { $env:STS2_ASCEND_GAME_LAUNCHER = $previousEnv.GameLauncher }
        if ($null -eq $previousEnv.PythonHome) { Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue }
        else { $env:PYTHONHOME = $previousEnv.PythonHome }
        if ($null -eq $previousEnv.PythonPath) { Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue }
        else { $env:PYTHONPATH = $previousEnv.PythonPath }
    }
} finally {
    if ($lifecycleLock) { $lifecycleLock.Dispose() }
}
