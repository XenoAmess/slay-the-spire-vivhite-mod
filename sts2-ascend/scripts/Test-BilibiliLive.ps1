[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [ValidateRange(5, 600)][int]$ReadyTimeoutSeconds = 120,
    [ValidateRange(5, 120)][int]$LiveTimeoutSeconds = 30,
    [ValidateRange(0, 10)][int]$StreamingHoldSeconds = 2
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
$startAgent = Join-Path $PSScriptRoot "Start-Agent.ps1"
Import-Module $modulePath -Force

if (-not $PSCmdlet.ShouldProcess("Bilibili Livehime",
        "perform one real start/verify/immediate-stop smoke test while leaving sts2-ascend running")) {
    return
}

& $startAgent -GameDir $GameDir -SkipDeploy -ReadyTimeoutSeconds $ReadyTimeoutSeconds
$initialState = Get-LivehimeStreamingState
if ($initialState -ne "Idle") {
    throw "Smoke test requires Livehime to be Idle before it starts; current state is '$initialState'."
}

$stopError = $null
try {
    Invoke-LivehimeBridge -Action Start -TimeoutSeconds $LiveTimeoutSeconds
    if ((Get-LivehimeStreamingState) -ne "Streaming") {
        throw "Livehime did not remain in Streaming state for smoke verification."
    }
    Set-SlayTheSpireTopMost -GameDir $GameDir -TimeoutSeconds $ReadyTimeoutSeconds
    Write-Host "Smoke checkpoint passed: Livehime is Streaming and the game is TOPMOST."
    if ($StreamingHoldSeconds -gt 0) { Start-Sleep -Seconds $StreamingHoldSeconds }
}
finally {
    try {
        Invoke-LivehimeBridge -Action Stop -TimeoutSeconds $LiveTimeoutSeconds
    }
    catch {
        $stopError = $_
    }
    $gameWindow = Get-SlayTheSpireWindow -GameDir $GameDir
    if ($gameWindow) {
        Set-SlayTheSpireTopMost -GameDir $GameDir -TimeoutSeconds 10
    }
    if ($stopError) {
        throw "CRITICAL: smoke cleanup could not confirm Bilibili Idle: $($stopError.Exception.Message)"
    }
}

$finalState = Get-LivehimeStreamingState
if ($finalState -ne "Idle") {
    throw "CRITICAL: smoke ended with Livehime state '$finalState' instead of Idle."
}
Write-Host "Smoke cleanup passed: Bilibili is Idle. No sts2-ascend stop action was issued."
