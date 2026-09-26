[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [ValidateRange(5, 120)][int]$LiveTimeoutSeconds = 30
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
Import-Module $modulePath -Force

if (-not $PSCmdlet.ShouldProcess("Bilibili Livehime", "stop Bilibili streaming only")) {
    return
}

Invoke-LivehimeBridge -Action Stop -TimeoutSeconds $LiveTimeoutSeconds
$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$ttsRestore = Restore-AscendIndexTtsAfterBroadcast -ProjectRoot $projectRoot
$gameWindow = Get-SlayTheSpireWindow -GameDir $GameDir
if ($gameWindow) {
    Set-SlayTheSpireTopMost -GameDir $GameDir -TimeoutSeconds 10
    Set-AscendViewerTopMost
}
Write-Host ("Bilibili streaming stopped through Livehime. No service or game process was stopped; " +
    "IndexTTS restore state=$($ttsRestore.State), owner_pid=$($ttsRestore.OwnerPid).")
