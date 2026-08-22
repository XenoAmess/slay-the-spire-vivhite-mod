# One-click: deploy mod (if needed) -> ensure game running -> launch the learning brain.
param(
    [string]$Version = "0.9.0",
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [switch]$SkipDeploy
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent

if (-not $SkipDeploy) {
    & $PSScriptRoot\Deploy-Mod.ps1 -Version $Version -GameDir $GameDir
}

# ensure game is running (brain also self-heals, this just shortens the wait)
$proc = Get-Process | Where-Object { $_.ProcessName -like "*SlayTheSpire2*" }
if (-not $proc) {
    Write-Host "Launching game (vulkan)..."
    Start-Process -FilePath (Join-Path $GameDir "launch_vulkan.bat") -WorkingDirectory $GameDir
} else {
    Write-Host "Game already running (pid $($proc[0].Id))"
}

Write-Host "Starting brain (Ctrl+C to stop)..."
Set-Location $root
py -3 -u -m brain
