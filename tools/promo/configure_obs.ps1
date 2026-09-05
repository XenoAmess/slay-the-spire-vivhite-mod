<#
.SYNOPSIS
  Safely applies the Vivhite promo OBS capture policy.

.DESCRIPTION
  This project-side helper changes only the active OBS scene collection and
  profile.  It never enables the OBS WebSocket server, starts a stream, starts
  a game, or touches credentials.  A timestamped backup is made before an
  apply.  Without -Apply the script is a read-only diagnostic.

  The active OBS process must be closed before -Apply.  Refusing to edit an
  open profile is intentional: OBS can overwrite a hand-edited scene file on
  exit.
#>
[CmdletBinding()]
param(
    [string]$ObsRoot = "",
    [string]$ProjectRoot = "",
    [string]$GameWindow = "Slay the Spire 2:Engine:SlayTheSpire2.exe",
    [string]$RecordingPath = "G:\OBS_VIDEOS",
    [ValidateRange(1, 240)][int]$Fps = 60,
    [switch]$Apply,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ObsRoot)) {
    $ObsRoot = Join-Path ([Environment]::GetFolderPath("ApplicationData")) "obs-studio"
}
if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$ObsRoot = [IO.Path]::GetFullPath($ObsRoot)
$ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot)

function Read-Utf8 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [IO.File]::ReadAllText($Path, [Text.UTF8Encoding]::new($false, $true))
}

function Write-Utf8Atomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $temporary = "$Path.codex-$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        [IO.File]::WriteAllText($temporary, $Content, [Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $temporary -Destination $Path -Force
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Set-ObjectProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)]$Value
    )
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        $Object | Add-Member -MemberType NoteProperty -Name $Name -Value $Value
    }
    else {
        $property.Value = $Value
    }
}

function Get-IniActiveValue {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Section,
        [Parameter(Mandatory = $true)][string]$Key
    )
    $active = $false
    foreach ($line in ($Text -split "`r?`n")) {
        if ($line -match '^\s*\[([^]]+)\]\s*$') {
            $active = $Matches[1] -eq $Section
            continue
        }
        if ($active -and $line -match ('^' + [regex]::Escape($Key) + '=(.*)$')) {
            return $Matches[1]
        }
    }
    return $null
}

function Set-IniActiveKeys {
    param(
        [Parameter(Mandatory = $true)][string]$Text,
        [Parameter(Mandatory = $true)][string]$Section,
        [Parameter(Mandatory = $true)][hashtable]$Values
    )
    $lines = New-Object "System.Collections.Generic.List[string]"
    foreach ($line in ($Text -split "`r?`n")) { [void]$lines.Add($line) }
    $active = $false
    $seen = @{}
    for ($index = 0; $index -lt $lines.Count; $index++) {
        $line = $lines[$index]
        if ($line -match '^\s*\[([^]]+)\]\s*$') {
            if ($active) {
                foreach ($key in $Values.Keys) {
                    if (-not $seen.ContainsKey($key)) {
                        $lines.Insert($index, "$key=$($Values[$key])")
                        $index++
                    }
                }
            }
            $active = $Matches[1] -eq $Section
            continue
        }
        if ($active) {
            foreach ($key in $Values.Keys) {
                if ($line -match ('^' + [regex]::Escape([string]$key) + '=') ) {
                    $lines[$index] = "$key=$($Values[$key])"
                    $seen[$key] = $true
                    break
                }
            }
        }
    }
    if ($active) {
        foreach ($key in $Values.Keys) {
            if (-not $seen.ContainsKey($key)) {
                [void]$lines.Add("$key=$($Values[$key])")
            }
        }
    }
    return ($lines -join "`r`n").TrimEnd("`r", "`n") + "`r`n"
}

function Get-GlobalIniValue {
    param([Parameter(Mandatory = $true)][string]$Text, [Parameter(Mandatory = $true)][string]$Key)
    return Get-IniActiveValue -Text $Text -Section "Basic" -Key $Key
}

$globalPath = Join-Path $ObsRoot "global.ini"
if (-not (Test-Path -LiteralPath $globalPath -PathType Leaf)) {
    throw "OBS global.ini was not found: $globalPath"
}
$globalText = Read-Utf8 -Path $globalPath
$sceneCollection = Get-GlobalIniValue -Text $globalText -Key "SceneCollection"
$sceneFileName = Get-GlobalIniValue -Text $globalText -Key "SceneCollectionFile"
$profileName = Get-GlobalIniValue -Text $globalText -Key "Profile"
$profileDir = Get-GlobalIniValue -Text $globalText -Key "ProfileDir"
if ([string]::IsNullOrWhiteSpace($sceneFileName)) { $sceneFileName = $sceneCollection }
if ([string]::IsNullOrWhiteSpace($profileDir)) { $profileDir = $profileName }
if ([string]::IsNullOrWhiteSpace($sceneFileName) -or [string]::IsNullOrWhiteSpace($profileDir)) {
    throw "OBS global.ini does not identify the active scene collection/profile"
}

$scenePath = Join-Path (Join-Path $ObsRoot "basic\scenes") ($sceneFileName + ".json")
$profilePath = Join-Path (Join-Path $ObsRoot "basic\profiles") (Join-Path $profileDir "basic.ini")
foreach ($requiredPath in @($scenePath, $profilePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "OBS active configuration file was not found: $requiredPath"
    }
}

$sceneText = Read-Utf8 -Path $scenePath
$profileText = Read-Utf8 -Path $profilePath
$scene = $sceneText | ConvertFrom-Json
$sources = @($scene.sources)
$sceneOrderName = [string]$scene.current_scene
$activeScene = $sources | Where-Object { $_.id -eq "scene" -and $_.name -eq $sceneOrderName } | Select-Object -First 1
if ($null -eq $activeScene) {
    throw "active OBS scene '$sceneOrderName' was not found in $scenePath"
}
$items = @($activeScene.settings.items)
# Resolve the source UUID explicitly; nested ``Where-Object`` pipelines have
# different ``$_`` bindings in Windows PowerShell 5.1.
$gameItem = $null
foreach ($item in $items) {
    $sourceUuid = [string]$item.source_uuid
    $match = $sources | Where-Object { [string]$_.uuid -eq $sourceUuid -and [string]$_.id -eq "game_capture" } | Select-Object -First 1
    if ($null -ne $match) { $gameItem = $item; break }
}
if ($null -eq $gameItem) {
    throw "active OBS scene has no game_capture source; refusing to invent a source schema"
}
$gameSource = $sources | Where-Object { [string]$_.uuid -eq [string]$gameItem.source_uuid } | Select-Object -First 1
if ($null -eq $gameSource) { throw "game_capture item references a missing source" }
if ($null -eq $gameSource.settings) { Set-ObjectProperty -Object $gameSource -Name "settings" -Value ([pscustomobject]@{}) }

$monitorInActiveScene = @()
foreach ($item in $items) {
    $sourceUuid = [string]$item.source_uuid
    $match = $sources | Where-Object { [string]$_.uuid -eq $sourceUuid -and [string]$_.id -in @("monitor_capture", "display_capture") } | Select-Object -First 1
    if ($null -ne $match) { $monitorInActiveScene += $match.name }
}
if ($monitorInActiveScene.Count -gt 0) {
    throw "active OBS scene still contains display/monitor capture source(s): $($monitorInActiveScene -join ', '); remove them in OBS UI and rerun"
}

$before = [ordered]@{
    scene = $scenePath
    profile = $profilePath
    scene_collection = $sceneCollection
    profile_name = $profileName
    game_source = [string]$gameSource.name
    game_window = [string]$gameSource.settings.window
    fps_common = Get-IniActiveValue -Text $profileText -Section "Video" -Key "FPSCommon"
    output = ((Get-IniActiveValue -Text $profileText -Section "Video" -Key "OutputCX") + "x" + (Get-IniActiveValue -Text $profileText -Section "Video" -Key "OutputCY"))
}

Set-ObjectProperty -Object $gameSource.settings -Name "capture_mode" -Value "window"
Set-ObjectProperty -Object $gameSource.settings -Name "window" -Value $GameWindow
Set-ObjectProperty -Object $gameSource.settings -Name "priority" -Value 2
Set-ObjectProperty -Object $gameSource.settings -Name "capture_cursor" -Value $false
Set-ObjectProperty -Object $gameSource.settings -Name "capture_overlays" -Value $false
# OBS 32.2.2 on this machine does not ship the process-audio source that the
# newer Game Capture ``capture_audio`` flag needs (the startup log reports
# ``wasapi_process_output_capture`` missing).  Keep the flag explicitly off
# and use one global WASAPI output source as the auditable fallback; otherwise
# OBS would show a broken, silent audio source in the scene.
Set-ObjectProperty -Object $gameSource.settings -Name "capture_audio" -Value $false
Set-ObjectProperty -Object $gameSource.settings -Name "limit_framerate" -Value $false
Set-ObjectProperty -Object $gameSource.settings -Name "allow_transparency" -Value $false
Set-ObjectProperty -Object $gameSource.settings -Name "anti_cheat_hook" -Value $true
Set-ObjectProperty -Object $gameSource.settings -Name "hook_rate" -Value 1

$recordingPathResolved = [IO.Path]::GetFullPath($RecordingPath)
# OBS config strings use C-style escaping.  Writing a raw Windows path makes
# sequences such as `\r` and `\a` parse as control characters, which OBS then
# rejects as a bad output path.  Keep the filesystem path raw for validation
# and the run manifest, but escape every separator in basic.ini.
$recordingPathIni = $recordingPathResolved.Replace('\', '\\')
$updatedProfile = Set-IniActiveKeys -Text $profileText -Section "Video" -Values @{
    BaseCX = 1920
    BaseCY = 1080
    OutputCX = 1920
    OutputCY = 1080
    FPSCommon = $Fps
    FPSInt = $Fps
    FPSNum = $Fps
    FPSDen = 1
}
$updatedProfile = Set-IniActiveKeys -Text $updatedProfile -Section "SimpleOutput" -Values @{
    RecEncoder = "nvenc"
    RecQuality = "Small"
    FilePath = $recordingPathIni
    RecFormat = "mkv"
    RecFormat2 = "mkv"
    RecAudioEncoder = "aac"
    ABitrate = 192
    RecTracks = 1
    UseAdvanced = "false"
}
$sceneJson = $scene | ConvertTo-Json -Depth 100
$result = [ordered]@{
    status = if ($Apply) { "ready-to-apply" } else { "dry-run" }
    active_scene = $sceneOrderName
    scene_path = $scenePath
    profile_path = $profilePath
    game_source = [string]$gameSource.name
    game_window = $GameWindow
    capture_cursor = $false
    capture_overlays = $false
    capture_audio = $false
    audio_capture_mode = "global-wasapi-output"
    desktop_audio = "enabled-single-source"
    microphone = "disabled"
    recording_encoder = "nvenc"
    recording_format = "mkv"
    recording_path = $recordingPathResolved
    output = "1920x1080"
    fps = $Fps
}

if ($Apply) {
    $running = @(Get-Process -Name obs64, obs32 -ErrorAction SilentlyContinue)
    if ($running.Count -gt 0) {
        throw "OBS is running; close OBS before applying this profile change (no files were written)"
    }
    # Include milliseconds and a short GUID suffix so two attempts in the
    # same second can never overwrite one another's evidence backup.
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
    $backupRoot = Join-Path $ProjectRoot (Join-Path ".work\obs-backups" ("{0}-{1}" -f $stamp, ([Guid]::NewGuid().ToString("N").Substring(0, 8))))
    New-Item -ItemType Directory -Path $backupRoot -ErrorAction Stop | Out-Null
    # Preserve the exact on-disk configuration before changing *any* nested
    # object.  The scene object was prepared in memory above for both dry-run
    # and apply, and the desktop-audio settings below are also mutable; taking
    # this snapshot after those mutations would make the "backup" unusable as
    # a rollback point.
    Copy-Item -LiteralPath $scenePath -Destination (Join-Path $backupRoot "scene.json") -ErrorAction Stop
    Copy-Item -LiteralPath $profilePath -Destination (Join-Path $backupRoot "basic.ini") -ErrorAction Stop
    Copy-Item -LiteralPath $globalPath -Destination (Join-Path $backupRoot "global.ini") -ErrorAction Stop
    if (-not (Test-Path -LiteralPath $recordingPathResolved -PathType Container)) {
        New-Item -ItemType Directory -Path $recordingPathResolved -Force -ErrorAction Stop | Out-Null
    }
    # This OBS build cannot instantiate process-audio capture.  Use exactly one
    # global WASAPI output source for the game stem and keep the microphone off.
    # The source's device timing is disabled to avoid the large drift observed
    # in old sessions; a short recording still has to be listened to before a
    # production take.
    $desktopSource = $scene.PSObject.Properties["DesktopAudioDevice1"]
    if ($null -eq $desktopSource -or $null -eq $desktopSource.Value) {
        throw "OBS scene has no DesktopAudioDevice1 WASAPI output source"
    }
    Set-ObjectProperty -Object $desktopSource.Value -Name "enabled" -Value $true
    Set-ObjectProperty -Object $desktopSource.Value -Name "muted" -Value $false
    if ($null -ne $desktopSource.Value.settings) {
        Set-ObjectProperty -Object $desktopSource.Value.settings -Name "use_device_timing" -Value $false
    }
    foreach ($globalSourceName in @("AuxAudioDevice1")) {
        $globalSource = $scene.PSObject.Properties[$globalSourceName]
        if ($null -ne $globalSource -and $null -ne $globalSource.Value) {
            Set-ObjectProperty -Object $globalSource.Value -Name "enabled" -Value $false
            Set-ObjectProperty -Object $globalSource.Value -Name "muted" -Value $true
        }
    }
    $sceneJson = $scene | ConvertTo-Json -Depth 100
    Write-Utf8Atomic -Path $scenePath -Content ($sceneJson + "`r`n")
    Write-Utf8Atomic -Path $profilePath -Content $updatedProfile
    # Re-read both files before reporting success.  A malformed scene must be
    # caught while the backup is still adjacent and easy to restore.
    $null = (Read-Utf8 -Path $scenePath | ConvertFrom-Json)
    $checkProfile = Read-Utf8 -Path $profilePath
    if ((Get-IniActiveValue -Text $checkProfile -Section "Video" -Key "FPSCommon") -ne [string]$Fps) {
        throw "OBS profile verification failed for FPSCommon"
    }
    $checkScene = Read-Utf8 -Path $scenePath | ConvertFrom-Json
    $checkGame = @($checkScene.sources) | Where-Object { [string]$_.uuid -eq [string]$gameSource.uuid } | Select-Object -First 1
    if ($null -eq $checkGame -or $checkGame.settings.capture_audio -ne $false) {
        throw "OBS scene verification failed for disabled unsupported capture_audio"
    }
    if ((Get-IniActiveValue -Text $checkProfile -Section "SimpleOutput" -Key "RecEncoder") -ne "nvenc") {
        throw "OBS profile verification failed for NVENC recording encoder"
    }
    if ((Get-IniActiveValue -Text $checkProfile -Section "SimpleOutput" -Key "RecFormat2") -ne "mkv") {
        throw "OBS profile verification failed for MKV recording format"
    }
    $result.status = "applied"
    $result.backup_root = $backupRoot
}

if ($Json) {
    $result | ConvertTo-Json -Depth 8
}
else {
    $result.GetEnumerator() | ForEach-Object { "{0}: {1}" -f $_.Key, $_.Value }
}
