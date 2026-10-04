# Shared read-only preflights and the game-only Vulkan launch.
# Dot-sourcing this file never starts any component.
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
        minimum_free_bytes = [UInt64][math]::Max([long]0, $MinimumFreeBytes)
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

function Get-AscendGameProcesses {
    # A failed CIM query must throw rather than become a zero-process result.
    # Count every game instance, including one launched from another directory.
    return @(Get-CimInstance Win32_Process -Filter "Name='SlayTheSpire2.exe'" -ErrorAction Stop)
}

function Get-AscendGameStartupPlan {
    param(
        [ValidateSet("auto", "on", "off")][string]$Mode = "auto",
        [AllowEmptyCollection()][object[]]$GameProcesses = @(),
        [ValidateRange(1048576, 1099511627776)][long]$MinimumFreeBytes = 1GB,
        [switch]$RequireColdOff
    )
    if ($GameProcesses.Count -gt 1) {
        throw "Multiple game instances exist; use the unified Stop-Agent.ps1 before restarting."
    }
    $coldLaunch = $GameProcesses.Count -eq 0
    if ($Mode -eq "off" -and -not $coldLaunch -and $RequireColdOff) {
        throw ("SteamMode off requires a cold game launch; the existing game process " +
               "cannot be switched retroactively. Run the unified Stop-Agent.ps1, then retry.")
    }
    if ($Mode -eq "off" -and $coldLaunch) {
        $consent = Test-LocalModConsent
        if (-not $consent.ready) {
            throw (("SteamMode off refused before game launch: native mod-loading consent " +
                   "is not recorded at {0} ({1}). Manual human confirmation is required; " +
                   "no GUI/UAC or settings/save mutation will be performed.") -f
                   $consent.settings_path, $consent.reason)
        }
    }
    $disk = Get-SteamDiskSpaceStatus -Mode $Mode -ColdLaunch:$coldLaunch `
        -MinimumFreeBytes $MinimumFreeBytes
    if (-not $disk.ready) {
        throw (("SteamMode {0} startup refused before deploy/game launch: {1} " +
               "(userdata={2}, drive={3}, minimum_free_bytes={4}). " +
               "Reclaim space and retry; this preflight will not delete files, alter Steam, " +
               "invoke GUI, or request UAC.") -f
               $Mode, $disk.reason, $disk.userdata_root, $disk.drive_root, $MinimumFreeBytes)
    }
    return [pscustomobject]@{
        ColdLaunch = $coldLaunch
        LaunchArguments = @(Get-GameLaunchArguments -Mode $Mode)
        DiskStatus = $disk
    }
}

function Invoke-AscendGameLaunch {
    param(
        [Parameter(Mandatory = $true)][string]$GameDir,
        [ValidateSet("auto", "on", "off")][string]$Mode = "auto",
        [ValidateRange(1048576, 1099511627776)][long]$MinimumFreeBytes = 1GB,
        [string]$StopFile = "",
        [switch]$RequireColdOff
    )
    # Start-Agent and Brain recovery use the same launch lock and re-probe.
    # This function starts only the game; it never starts a runner or Brain.
    $launchMutex = New-Object Threading.Mutex($false, "Local\STS2AscendGameColdStart")
    $locked = $false
    try {
        try { $locked = $launchMutex.WaitOne([TimeSpan]::FromSeconds(10)) }
        catch [Threading.AbandonedMutexException] { $locked = $true }
        if (-not $locked) { throw "Timed out waiting for the game cold-start lock." }
        if ($StopFile -and (Test-Path -LiteralPath $StopFile)) {
            throw "Stack stop was requested; game recovery was cancelled."
        }
        $games = @(Get-AscendGameProcesses)
        $plan = Get-AscendGameStartupPlan -Mode $Mode -GameProcesses $games `
            -MinimumFreeBytes $MinimumFreeBytes -RequireColdOff:$RequireColdOff
        $launched = $false
        if ($plan.ColdLaunch) {
            $launcher = [IO.Path]::GetFullPath((Join-Path $GameDir "launch_vulkan.bat"))
            $executable = [IO.Path]::GetFullPath((Join-Path $GameDir "SlayTheSpire2.exe"))
            if (-not (Test-Path -LiteralPath $launcher -PathType Leaf) -or
                -not (Test-Path -LiteralPath $executable -PathType Leaf)) {
                throw "Vulkan launcher or game executable is missing from $GameDir."
            }
            if ($StopFile -and (Test-Path -LiteralPath $StopFile)) {
                throw "Stack stop was requested; game recovery was cancelled."
            }
            # Recheck after the disk/consent work: a game that appeared during
            # those probes must be reused rather than launched a second time.
            $games = @(Get-AscendGameProcesses)
            if ($games.Count -gt 0) {
                $plan = Get-AscendGameStartupPlan -Mode $Mode -GameProcesses $games `
                    -MinimumFreeBytes $MinimumFreeBytes -RequireColdOff:$RequireColdOff
            }
            else {
                if ($StopFile -and (Test-Path -LiteralPath $StopFile)) {
                    throw "Stack stop was requested; game recovery was cancelled."
                }
                $launchParams = @{
                    FilePath = $launcher
                    WorkingDirectory = $GameDir
                    WindowStyle = "Hidden"
                }
                if ($plan.LaunchArguments.Count -gt 0) {
                    $launchParams.ArgumentList = $plan.LaunchArguments
                }
                Start-Process @launchParams | Out-Null
                $launched = $true
            }
        }
        return [pscustomobject]@{
            Launched = $launched
            ProcessCount = $games.Count
            Mode = $Mode.ToLowerInvariant()
            LaunchArguments = @($plan.LaunchArguments)
            DiskStatus = $plan.DiskStatus
        }
    }
    finally {
        if ($locked) { $launchMutex.ReleaseMutex() }
        $launchMutex.Dispose()
    }
}
