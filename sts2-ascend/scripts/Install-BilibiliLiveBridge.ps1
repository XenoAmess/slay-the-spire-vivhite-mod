[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
$workerPath = Join-Path $PSScriptRoot "Invoke-BilibiliLiveBridge.ps1"
Import-Module $modulePath -Force

$installDir = Join-Path ([Environment]::GetFolderPath("ProgramFiles")) "VivhiteBilibiliLiveBridge"
$taskPath = "\Vivhite\"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$userSid = $identity.User.Value

if (-not $PSCmdlet.ShouldProcess(
        "$installDir and Task Scheduler $taskPath",
        "install two fixed, current-user, interactive, highest-privilege Livehime tasks")) {
    return
}

if (-not (Test-IsAdministrator)) {
    throw "Run this installer once from an elevated PowerShell window."
}

if (-not (Test-Path -LiteralPath $installDir)) {
    New-Item -ItemType Directory -Path $installDir | Out-Null
}
Copy-Item -LiteralPath $modulePath -Destination (Join-Path $installDir "BilibiliLive.psm1") -Force
Copy-Item -LiteralPath $workerPath -Destination (Join-Path $installDir "Invoke-BilibiliLiveBridge.ps1") -Force

$protectedWorker = Join-Path $installDir "Invoke-BilibiliLiveBridge.ps1"
$powerShell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$principal = New-ScheduledTaskPrincipal -UserId $userSid -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew

foreach ($actionName in @("Start", "Stop")) {
    $taskName = "BilibiliLive-$actionName"
    $arguments = "-NoLogo -NonInteractive -NoProfile -WindowStyle Hidden " +
        "-ExecutionPolicy Bypass -File `"$protectedWorker`" -Action $actionName"
    $action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments `
        -WorkingDirectory $installDir
    Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Action $action `
        -Principal $principal -Settings $settings `
        -Description "Fixed protected worker: control Bilibili only through the elevated Livehime GUI." `
        -Force | Out-Null
}

$sourceHashes = @{
    Module = (Get-FileHash -Algorithm SHA256 -LiteralPath $modulePath).Hash
    Worker = (Get-FileHash -Algorithm SHA256 -LiteralPath $workerPath).Hash
}
$installedHashes = @{
    Module = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $installDir "BilibiliLive.psm1")).Hash
    Worker = (Get-FileHash -Algorithm SHA256 -LiteralPath $protectedWorker).Hash
}
if ($sourceHashes.Module -ne $installedHashes.Module -or
    $sourceHashes.Worker -ne $installedHashes.Worker) {
    throw "Protected Livehime bridge hash verification failed."
}

Write-Host "Installed protected tasks: ${taskPath}BilibiliLive-Start and ${taskPath}BilibiliLive-Stop."
