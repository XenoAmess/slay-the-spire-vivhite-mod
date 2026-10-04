# Internal game-only recovery for the already-running Brain session.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SessionFile,
    [Parameter(Mandatory = $true)][string]$SessionId
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "GameColdStart.ps1")

$session = Get-Content -LiteralPath $SessionFile -Raw -Encoding UTF8 | ConvertFrom-Json
if ([string]$session.session_id -ne $SessionId -or
    [string]$session.state -notin @("running", "foreground")) {
    throw "Game recovery session is no longer the running Brain session."
}
$mode = [string]$session.steam_mode
if ($mode -notin @("auto", "on", "off")) {
    throw "Game recovery session has no valid SteamMode; refusing a mode fallback."
}
$expectedArguments = @(Get-GameLaunchArguments -Mode $mode)
if ($session.steam_launch_arguments -isnot [array] -or
    (@($session.steam_launch_arguments) -join "`n") -cne ($expectedArguments -join "`n") -or
    $session.steam_mode_applied -isnot [bool]) {
    throw "Game recovery session Steam launch contract is inconsistent."
}
# auto/on can legitimately have applied=false when Start reused a running game.
# An off session is created only after its explicitly requested cold launch.
if ($mode -eq "off" -and -not $session.steam_mode_applied) {
    throw "SteamMode off was not applied to this session; refusing to change its namespace."
}
$minimumFreeBytes = 1GB
if ($session.PSObject.Properties["steam_min_free_bytes"]) {
    $minimumFreeBytes = [long]$session.steam_min_free_bytes
}
if ($minimumFreeBytes -lt 1MB -or $minimumFreeBytes -gt 1TB) {
    throw "Game recovery session has an invalid Steam disk-space minimum."
}
if ([string]::IsNullOrWhiteSpace([string]$session.game_dir) -or
    [string]::IsNullOrWhiteSpace([string]$session.stop_file)) {
    throw "Game recovery session is missing game_dir or stop_file."
}
$result = Invoke-AscendGameLaunch -GameDir ([string]$session.game_dir) -Mode $mode `
    -MinimumFreeBytes $minimumFreeBytes -StopFile ([string]$session.stop_file)
$result | ConvertTo-Json -Depth 5 -Compress
