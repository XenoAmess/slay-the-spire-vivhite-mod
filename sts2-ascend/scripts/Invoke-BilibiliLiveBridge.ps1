[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Start", "Stop")]
    [string]$Action
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
Import-Module $modulePath -Force

if (-not (Test-IsAdministrator)) {
    throw "The protected Bilibili Livehime worker must run at high integrity."
}

$livehimeExe = "C:\Program Files\bililive\livehime\livehime.exe"
$bridgeMutex = New-Object Threading.Mutex($false, "Global\VivhiteBilibiliLiveBridge")
$bridgeLockAcquired = $false
try {
    try {
        $bridgeLockAcquired = $bridgeMutex.WaitOne([TimeSpan]::FromSeconds(45))
    }
    catch [Threading.AbandonedMutexException] {
        $bridgeLockAcquired = $true
    }
    if (-not $bridgeLockAcquired) {
        throw "Timed out waiting for another protected Livehime action to finish."
    }

    if ($Action -eq "Start") {
        Invoke-LivehimeStart -LivehimeExe $livehimeExe -TimeoutSeconds 30
    }
    else {
        Invoke-LivehimeStop -LivehimeExe $livehimeExe -TimeoutSeconds 30
    }
}
finally {
    if ($bridgeLockAcquired) { $bridgeMutex.ReleaseMutex() }
    $bridgeMutex.Dispose()
}
