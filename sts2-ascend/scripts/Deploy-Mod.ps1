# Deploy the upstream STS2-Agent mod (CharTyr/STS2-Agent) into the game mods folder.
# Downloads the pinned release zip if not present locally.
param(
    [string]$Version = "0.9.0",
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2"
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$distDir = Join-Path $root "third_party\dist"
$zip = Join-Path $distDir "sts2-ai-agent-v$Version-windows.zip"
$extracted = Join-Path $distDir "v$Version"

if (-not (Test-Path $zip)) {
    New-Item -ItemType Directory -Force -Path $distDir | Out-Null
    $url = "https://github.com/CharTyr/STS2-Agent/releases/download/v$Version/sts2-ai-agent-v$Version-windows.zip"
    Write-Host "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $zip
}
if (-not (Test-Path (Join-Path $extracted "mod\STS2AIAgent.dll"))) {
    Expand-Archive -Path $zip -DestinationPath $extracted -Force
}

$mods = Join-Path $GameDir "mods"
Copy-Item (Join-Path $extracted "mod\*") $mods -Force
Write-Host "Deployed STS2-Agent v$Version to $mods"
Get-ChildItem $mods -Filter "STS2AIAgent.*" | ForEach-Object { Write-Host "  $($_.Name)" }
