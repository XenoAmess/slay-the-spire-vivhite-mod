[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param([switch]$Elevated)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
$workerPath = Join-Path $PSScriptRoot "Invoke-BilibiliLiveBridge.ps1"
$healthWatchPath = Join-Path $PSScriptRoot "Invoke-BilibiliLiveHealthWatch.ps1"
$dailyStartPath = Join-Path $PSScriptRoot "Invoke-BilibiliLiveDailyStart.ps1"
$dailyStopPath = Join-Path $PSScriptRoot "Invoke-BilibiliLiveDailyStopWatch.ps1"
Import-Module $modulePath -Force

$installDir = Join-Path ([Environment]::GetFolderPath("ProgramFiles")) "VivhiteBilibiliLiveBridge"
$taskPath = "\Vivhite\"
$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$gameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$userSid = $identity.User.Value
$powerShell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
$targetDescription = "$installDir and Task Scheduler $taskPath"

if ($WhatIfPreference) {
    Write-Host "What if: Would install three protected Livehime tasks plus limited 23:00-23:20 start and 11:00-11:20 stop coordinators at $targetDescription."
    return
}

$livehimeState = Get-LivehimeStreamingState
if (-not (Test-BilibiliBridgeInstallSafeState -State $livehimeState)) {
    throw ("Refusing to install the protected Livehime bridge while Livehime state is " +
           "'$livehimeState'. No UAC prompt was requested. Stop the broadcast and " +
           "confirm Livehime Idle before installing; display capture must never expose " +
           "the UAC secure desktop or a frozen full-screen frame.")
}

if (-not (Test-IsAdministrator)) {
    if ($Elevated) {
        throw "The elevated installer process does not have administrator rights."
    }

    $elevationArguments = @(
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-Elevated"
    )
    try {
        $elevatedProcess = Start-Process -FilePath $powerShell -Verb RunAs `
            -ArgumentList $elevationArguments -Wait -PassThru
    }
    catch {
        throw "UAC elevation for the protected Livehime bridge was cancelled or failed: $($_.Exception.Message)"
    }
    if ($elevatedProcess.ExitCode -ne 0) {
        throw "The elevated protected Livehime bridge installer failed with exit code $($elevatedProcess.ExitCode)."
    }
    Write-Host "The protected Livehime bridge was installed by the elevated process."
    return
}

if (-not (Test-Path -LiteralPath $installDir)) {
    New-Item -ItemType Directory -Path $installDir | Out-Null
}
Copy-Item -LiteralPath $modulePath -Destination (Join-Path $installDir "BilibiliLive.psm1") -Force
Copy-Item -LiteralPath $workerPath -Destination (Join-Path $installDir "Invoke-BilibiliLiveBridge.ps1") -Force
Copy-Item -LiteralPath $healthWatchPath `
    -Destination (Join-Path $installDir "Invoke-BilibiliLiveHealthWatch.ps1") -Force
Copy-Item -LiteralPath $dailyStartPath `
    -Destination (Join-Path $installDir "Invoke-BilibiliLiveDailyStart.ps1") -Force
Copy-Item -LiteralPath $dailyStopPath `
    -Destination (Join-Path $installDir "Invoke-BilibiliLiveDailyStopWatch.ps1") -Force

$protectedWorker = Join-Path $installDir "Invoke-BilibiliLiveBridge.ps1"
$protectedHealthWatch = Join-Path $installDir "Invoke-BilibiliLiveHealthWatch.ps1"
$installedDailyStart = Join-Path $installDir "Invoke-BilibiliLiveDailyStart.ps1"
$installedDailyStop = Join-Path $installDir "Invoke-BilibiliLiveDailyStopWatch.ps1"
$sourceHashes = @{
    Module = (Get-FileHash -Algorithm SHA256 -LiteralPath $modulePath).Hash
    Worker = (Get-FileHash -Algorithm SHA256 -LiteralPath $workerPath).Hash
    HealthWatch = (Get-FileHash -Algorithm SHA256 -LiteralPath $healthWatchPath).Hash
    DailyStart = (Get-FileHash -Algorithm SHA256 -LiteralPath $dailyStartPath).Hash
    DailyStop = (Get-FileHash -Algorithm SHA256 -LiteralPath $dailyStopPath).Hash
}
$installedHashes = @{
    Module = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $installDir "BilibiliLive.psm1")).Hash
    Worker = (Get-FileHash -Algorithm SHA256 -LiteralPath $protectedWorker).Hash
    HealthWatch = (Get-FileHash -Algorithm SHA256 -LiteralPath $protectedHealthWatch).Hash
    DailyStart = (Get-FileHash -Algorithm SHA256 -LiteralPath $installedDailyStart).Hash
    DailyStop = (Get-FileHash -Algorithm SHA256 -LiteralPath $installedDailyStop).Hash
}
if ($sourceHashes.Module -ne $installedHashes.Module -or
    $sourceHashes.Worker -ne $installedHashes.Worker -or
    $sourceHashes.HealthWatch -ne $installedHashes.HealthWatch -or
    $sourceHashes.DailyStart -ne $installedHashes.DailyStart -or
    $sourceHashes.DailyStop -ne $installedHashes.DailyStop) {
    throw "Protected Livehime bridge hash verification failed."
}

$principal = New-ScheduledTaskPrincipal -UserId $userSid -LogonType Interactive -RunLevel Highest
$dailyCoordinatorPrincipal = New-ScheduledTaskPrincipal -UserId $userSid `
    -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew

foreach ($actionName in @("Start", "Stop")) {
    $taskName = "BilibiliLive-$actionName"
    $arguments = "-NoLogo -NonInteractive -NoProfile -WindowStyle Hidden " +
        "-ExecutionPolicy Bypass -File `"$protectedWorker`" -Action $actionName " +
        "-ProjectRoot `"$projectRoot`" -GameDir `"$gameDir`""
    $action = New-ScheduledTaskAction -Execute $powerShell -Argument $arguments `
        -WorkingDirectory $installDir
    Register-ScheduledTask -TaskName $taskName -TaskPath $taskPath -Action $action `
        -Principal $principal -Settings $settings `
        -Description "Fixed protected worker: control Bilibili only through the elevated Livehime GUI." `
        -Force | Out-Null
}

$healthSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew
$healthArguments = "-NoLogo -NonInteractive -NoProfile -WindowStyle Hidden " +
    "-ExecutionPolicy Bypass -File `"$protectedHealthWatch`" " +
    "-ProjectRoot `"$projectRoot`" -GameDir `"$gameDir`""
$healthAction = New-ScheduledTaskAction -Execute $powerShell -Argument $healthArguments `
    -WorkingDirectory $installDir
Register-ScheduledTask -TaskName "BilibiliLive-HealthWatch" -TaskPath $taskPath `
    -Action $healthAction -Principal $principal -Settings $healthSettings `
    -Description "Protected local capture and semantic gameplay watch; stop Bilibili on frozen capture or stalled play." `
    -Force | Out-Null

function New-BilibiliWindowTrigger {
    param([Parameter(Mandatory = $true)][DateTime]$At)
    $trigger = New-ScheduledTaskTrigger -Daily -At $At
    $repetitionTemplate = New-ScheduledTaskTrigger -Once -At $At `
        -RepetitionInterval (New-TimeSpan -Minutes 1) `
        -RepetitionDuration (New-TimeSpan -Minutes 19)
    $repetitionTemplate.Repetition.StopAtDurationEnd = $false
    $trigger.Repetition = $repetitionTemplate.Repetition
    return $trigger
}

function Assert-BilibiliWindowTask {
    param(
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][DateTimeOffset]$ExpectedStartUtc
    )
    $registeredTask = Get-ScheduledTask -TaskName $TaskName -TaskPath $taskPath
    $registeredTriggers = @($registeredTask.Triggers)
    if ($registeredTriggers.Count -ne 1) {
        throw "$TaskName trigger verification failed: expected exactly one trigger."
    }
    $registeredTrigger = $registeredTriggers[0]
    $registeredBoundary = [DateTimeOffset]::Parse($registeredTrigger.StartBoundary)
    if ([Math]::Abs(($registeredBoundary.ToUniversalTime() - $ExpectedStartUtc).TotalSeconds) -gt 1 -or
        [int]$registeredTrigger.DaysInterval -ne 1 -or
        [string]$registeredTrigger.Repetition.Interval -ne "PT1M" -or
        [string]$registeredTrigger.Repetition.Duration -ne "PT19M") {
        throw "$TaskName trigger verification failed: daily boundary or 20-check repetition is not exact."
    }
    $registeredInfo = Get-ScheduledTaskInfo -TaskName $TaskName -TaskPath $taskPath
    if ($registeredInfo.NextRunTime -eq [DateTime]::MinValue -or
        [Math]::Abs(($registeredInfo.NextRunTime.ToUniversalTime() -
                    $ExpectedStartUtc.UtcDateTime).TotalSeconds) -gt 1) {
        throw "$TaskName next-run verification failed: Task Scheduler did not preserve the calculated date."
    }
    return $registeredInfo
}

$dailyStartSchedule = Get-BilibiliDailyStartSchedule
$nextDailyStartUtc = $dailyStartSchedule.NextStartUtc
$dailyStartTrigger = New-BilibiliWindowTrigger -At $dailyStartSchedule.NextStartLocal
$generatedStartBoundary = [DateTimeOffset]::Parse($dailyStartTrigger.StartBoundary)
if ([Math]::Abs(($generatedStartBoundary.ToUniversalTime() - $nextDailyStartUtc).TotalSeconds) -gt 1) {
    throw "Generated daily start trigger does not match the calculated Beijing-time start."
}
$dailyStartSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew
$dailyStartArguments = "-NoLogo -NonInteractive -NoProfile -WindowStyle Hidden " +
    "-ExecutionPolicy Bypass -File `"$installedDailyStart`" " +
    "-ProjectRoot `"$projectRoot`" -GameDir `"$gameDir`""
$dailyStartAction = New-ScheduledTaskAction -Execute $powerShell -Argument $dailyStartArguments `
    -WorkingDirectory $installDir
Register-ScheduledTask -TaskName "BilibiliLive-DailyStart" -TaskPath $taskPath `
    -Action $dailyStartAction -Trigger $dailyStartTrigger -Principal $dailyCoordinatorPrincipal `
    -Settings $dailyStartSettings `
    -Description "From 23:00 through 23:19 Beijing time, check once per minute and invoke the unified fail-closed start until Streaming is confirmed." `
    -Force | Out-Null
$registeredStartInfo = Assert-BilibiliWindowTask -TaskName "BilibiliLive-DailyStart" `
    -ExpectedStartUtc $nextDailyStartUtc
Write-Host ("Verified daily start: Beijing boundary {0}; Task Scheduler next run {1}." -f
    $dailyStartSchedule.NextStart.ToString("yyyy-MM-dd HH:mm:ss zzz"),
    $registeredStartInfo.NextRunTime.ToString("yyyy-MM-dd HH:mm:ss zzz"))

$dailyStopSchedule = Get-BilibiliDailyStopSchedule
$nextDailyStopUtc = $dailyStopSchedule.NextStartUtc
$dailyStopTrigger = New-BilibiliWindowTrigger -At $dailyStopSchedule.NextStartLocal
$generatedStopBoundary = [DateTimeOffset]::Parse($dailyStopTrigger.StartBoundary)
if ([Math]::Abs(($generatedStopBoundary.ToUniversalTime() - $nextDailyStopUtc).TotalSeconds) -gt 1) {
    throw "Generated daily stop trigger does not match the calculated Beijing-time start."
}
$dailyStopSettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew
$dailyStopArguments = "-NoLogo -NonInteractive -NoProfile -WindowStyle Hidden " +
    "-ExecutionPolicy Bypass -File `"$installedDailyStop`" " +
    "-ProjectRoot `"$projectRoot`" -GameDir `"$gameDir`""
$dailyStopAction = New-ScheduledTaskAction -Execute $powerShell -Argument $dailyStopArguments `
    -WorkingDirectory $installDir
Register-ScheduledTask -TaskName "BilibiliLive-DailyStopWatch" -TaskPath $taskPath `
    -Action $dailyStopAction -Trigger $dailyStopTrigger -Principal $dailyCoordinatorPrincipal `
    -Settings $dailyStopSettings `
    -Description "From 11:00 through 11:19 Beijing time, check once per minute and stop only exact Streaming through the unified stop entrypoint." `
    -Force | Out-Null
$registeredStopInfo = Assert-BilibiliWindowTask -TaskName "BilibiliLive-DailyStopWatch" `
    -ExpectedStartUtc $nextDailyStopUtc
Write-Host ("Verified daily stop: Beijing boundary {0}; Task Scheduler next run {1}." -f
    $dailyStopSchedule.NextStart.ToString("yyyy-MM-dd HH:mm:ss zzz"),
    $registeredStopInfo.NextRunTime.ToString("yyyy-MM-dd HH:mm:ss zzz"))

if ($dailyStartSchedule.InWindow) {
    Start-ScheduledTask -TaskName "BilibiliLive-DailyStart" -TaskPath $taskPath
}
if ($dailyStopSchedule.InWindow) {
    Start-ScheduledTask -TaskName "BilibiliLive-DailyStopWatch" -TaskPath $taskPath
}

Write-Host "Installed tasks: ${taskPath}BilibiliLive-Start, ${taskPath}BilibiliLive-Stop, ${taskPath}BilibiliLive-HealthWatch, ${taskPath}BilibiliLive-DailyStart, and ${taskPath}BilibiliLive-DailyStopWatch."
