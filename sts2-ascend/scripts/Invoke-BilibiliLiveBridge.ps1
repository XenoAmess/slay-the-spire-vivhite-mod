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
if ($Action -eq "Start") {
    Invoke-LivehimeStart -LivehimeExe $livehimeExe -TimeoutSeconds 30
}
else {
    Invoke-LivehimeStop -LivehimeExe $livehimeExe -TimeoutSeconds 30
}
