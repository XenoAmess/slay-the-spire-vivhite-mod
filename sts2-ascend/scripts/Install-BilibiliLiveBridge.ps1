[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param()

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
$workerPath = Join-Path $PSScriptRoot "Invoke-BilibiliLiveBridge.ps1"
$dailyStopWatchPath = Join-Path $PSScriptRoot "Invoke-BilibiliLiveDailyStopWatch.ps1"
Import-Module $modulePath -Force

$installDir = Join-Path ([Environment]::GetFolderPath("ProgramFiles")) "VivhiteBilibiliLiveBridge"
$taskPath = "\Vivhite\"
$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$gameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$userSid = $identity.User.Value

if (-not $PSCmdlet.ShouldProcess(
        "$installDir and Task Scheduler $taskPath",
        "install three fixed, current-user, interactive, highest-privilege Livehime tasks")) {
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
Copy-Item -LiteralPath $dailyStopWatchPath `
    -Destination (Join-Path $installDir "Invoke-BilibiliLiveDailyStopWatch.ps1") -Force

$protectedWorker = Join-Path $installDir "Invoke-BilibiliLiveBridge.ps1"
$protectedDailyStopWatch = Join-Path $installDir "Invoke-BilibiliLiveDailyStopWatch.ps1"
$sourceHashes = @{
    Module = (Get-FileHash -Algorithm SHA256 -LiteralPath $modulePath).Hash
    Worker = (Get-FileHash -Algorithm SHA256 -LiteralPath $workerPath).Hash
    DailyStopWatch = (Get-FileHash -Algorithm SHA256 -LiteralPath $dailyStopWatchPath).Hash
}
$installedHashes = @{
    Module = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $installDir "BilibiliLive.psm1")).Hash
    Worker = (Get-FileHash -Algorithm SHA256 -LiteralPath $protectedWorker).Hash
    DailyStopWatch = (Get-FileHash -Algorithm SHA256 -LiteralPath $protectedDailyStopWatch).Hash
}
if ($sourceHashes.Module -ne $installedHashes.Module -or
    $sourceHashes.Worker -ne $installedHashes.Worker -or
    $sourceHashes.DailyStopWatch -ne $installedHashes.DailyStopWatch) {
    throw "Protected Livehime bridge hash verification failed."
}

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

$beijingTimeZone = [TimeZoneInfo]::FindSystemTimeZoneById("China Standard Time")
$utcNow = [DateTime]::UtcNow
$beijingNow = [TimeZoneInfo]::ConvertTimeFromUtc($utcNow, $beijingTimeZone)
$todayStartWallClock = [DateTime]::SpecifyKind(
    $beijingNow.Date.AddHours(16).AddMinutes(20),
    [DateTimeKind]::Unspecified)
$todayEndWallClock = $todayStartWallClock.AddMinutes(20)
$startDailyTaskNow = $beijingNow.DateTime -ge $todayStartWallClock -and `
    $beijingNow.DateTime -lt $todayEndWallClock
$nextStartWallClock = $todayStartWallClock
if ($beijingNow.DateTime -ge $todayEndWallClock) {
    $nextStartWallClock = $todayStartWallClock.AddDays(1)
}
$nextStartUtc = [TimeZoneInfo]::ConvertTimeToUtc($nextStartWallClock, $beijingTimeZone)
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At $nextStartUtc
$repetitionTemplate = New-ScheduledTaskTrigger -Once -At $nextStartUtc `
    -RepetitionInterval (New-TimeSpan -Minutes 1) `
    -RepetitionDuration (New-TimeSpan -Minutes 19)
$repetitionTemplate.Repetition.StopAtDurationEnd = $false
$dailyTrigger.Repetition = $repetitionTemplate.Repetition
$dailySettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) -MultipleInstances IgnoreNew
$dailyArguments = "-NoLogo -NonInteractive -NoProfile -WindowStyle Hidden " +
    "-ExecutionPolicy Bypass -File `"$protectedDailyStopWatch`" " +
    "-ProjectRoot `"$projectRoot`" -GameDir `"$gameDir`""
$dailyAction = New-ScheduledTaskAction -Execute $powerShell -Argument $dailyArguments `
    -WorkingDirectory $installDir
Register-ScheduledTask -TaskName "BilibiliLive-DailyStopWatch" -TaskPath $taskPath `
    -Action $dailyAction -Trigger $dailyTrigger -Principal $principal -Settings $dailySettings `
    -Description "At 16:20 Beijing time, check Livehime once per minute until 16:40 and stop only actual streaming." `
    -Force | Out-Null
if ($startDailyTaskNow) {
    Start-ScheduledTask -TaskName "BilibiliLive-DailyStopWatch" -TaskPath $taskPath
}

Write-Host "Installed protected tasks: ${taskPath}BilibiliLive-Start, ${taskPath}BilibiliLive-Stop, and ${taskPath}BilibiliLive-DailyStopWatch."
