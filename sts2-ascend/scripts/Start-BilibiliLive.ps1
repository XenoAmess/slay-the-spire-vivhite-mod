[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [ValidateRange(5, 600)][int]$ReadyTimeoutSeconds = 120,
    [ValidateRange(5, 120)][int]$LiveTimeoutSeconds = 30
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
$startAgent = Join-Path $PSScriptRoot "Start-Agent.ps1"
Import-Module $modulePath -Force

if (-not $PSCmdlet.ShouldProcess("sts2-ascend, Bilibili Livehime, and Slay the Spire 2",
        "start the full stack, start Bilibili streaming, and make the game TOPMOST")) {
    return
}

& $startAgent -GameDir $GameDir -SkipDeploy -ReadyTimeoutSeconds $ReadyTimeoutSeconds
Invoke-LivehimeBridge -Action Start -TimeoutSeconds $LiveTimeoutSeconds
Set-SlayTheSpireTopMost -GameDir $GameDir -TimeoutSeconds $ReadyTimeoutSeconds
Write-Host "Bilibili streaming started through Livehime; Slay the Spire 2 is TOPMOST."
