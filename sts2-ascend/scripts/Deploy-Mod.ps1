# Deploy the STS2-Agent mod into the game mods folder.
# -Source auto（默认）：我方 fork 克隆存在（third_party/STS2-Agent）时优先从其当前 checkout 构建
#   （正常应为与上游对齐的 main，见 third_party/README.md）；否则回退到官方 release zip。
# 注意：游戏运行时 dll 被锁定，部署会失败——请先关游戏再部署。
param(
    [string]$Version = "0.9.1",
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [ValidateSet("auto", "fork", "release")][string]$Source = "auto",
    [string]$GodotExe = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$forkDir = Join-Path $root "third_party\STS2-Agent"

function Resolve-GodotExe {
    if (-not [string]::IsNullOrWhiteSpace($GodotExe) -and (Test-Path $GodotExe)) { return $GodotExe }
    if (-not [string]::IsNullOrWhiteSpace($env:GODOT_BIN) -and (Test-Path $env:GODOT_BIN)) { return $env:GODOT_BIN }
    $cfgPath = Join-Path $root "brain\config.json"
    if (Test-Path $cfgPath) {
        try {
            $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
            if ($cfg.godot_exe -and (Test-Path $cfg.godot_exe)) { return $cfg.godot_exe }
        } catch { }
    }
    $vivhiteProps = Join-Path $root "..\Vivhite\local.props"
    if (Test-Path $vivhiteProps) {
        $m = [regex]::Match((Get-Content $vivhiteProps -Raw), '<GodotExe>([^<]+)</GodotExe>')
        if ($m.Success -and (Test-Path $m.Groups[1].Value)) { return $m.Groups[1].Value }
    }
    return $null
}

$useFork = ($Source -eq "fork") -or ($Source -eq "auto" -and (Test-Path (Join-Path $forkDir ".git")))

if ($useFork) {
    $godot = Resolve-GodotExe
    if (-not $godot) { throw "从 fork 构建需要 Godot（4.5.1 mono）；请用 -GodotExe 指定或配置 brain/config.json 的 godot_exe" }
    Write-Host "Building mod from local fork checkout ($forkDir)..."
    $env:STS2_DATA_DIR = Join-Path $GameDir "data_sts2_windows_x86_64"
    & (Join-Path $forkDir "scripts\build-mod.ps1") -Configuration Release -GameRoot $GameDir -GodotExe $godot
    if ($LASTEXITCODE -ne 0) { throw "fork build-mod failed (exit $LASTEXITCODE)" }
    Write-Host "Deployed fork build to $(Join-Path $GameDir 'mods')"
    return
}

# ---- 官方 release zip（无补丁的原版，仅作对照/回退） ----
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
Write-Host "Deployed STS2-Agent v$Version (official release, unpatched) to $mods"
Get-ChildItem $mods -Filter "STS2AIAgent.*" | ForEach-Object { Write-Host "  $($_.Name)" }
