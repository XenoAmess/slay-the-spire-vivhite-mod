<#
Captures the clean Act 2/3 RestSite portion for T10.

This is an operator recorder, not a native evidence generator.  The formal
segment starts on the already-staged RestSite choice screen (console closed),
then performs one real Rest click, holds the native healing result, clicks
Proceed, and holds the returned map.  Staging commands must happen before the
recording mark and are never part of the source span.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [Parameter(Mandatory=$true)][ValidatePattern('^a[0-9]+$')][string]$AttemptId,
    [int]$GameProcessId = 0,
    [int]$ObsProcessId = 0,
    [Parameter(Mandatory=$true)][ValidateRange(1,1919)][int]$RestX,
    [Parameter(Mandatory=$true)][ValidateRange(1,1079)][int]$RestY,
    [Parameter(Mandatory=$true)][ValidateRange(1,1919)][int]$ProceedX,
    [Parameter(Mandatory=$true)][ValidateRange(1,1079)][int]$ProceedY,
    [Parameter(Mandatory=$true)][ValidateRange(1,10000)][int]$ObsRecordButtonX,
    [Parameter(Mandatory=$true)][ValidateRange(1,10000)][int]$ObsRecordButtonY,
    [double]$PreRollSeconds = 2.0,
    [double]$RestHoverSeconds = 1.8,
    [double]$RestResultSeconds = 4.0,
    [double]$ProceedHoverSeconds = 0.9,
    [double]$MapReturnSeconds = 4.0,
    [double]$PostMapHoldSeconds = 3.2,
    [int]$ClickHoldMilliseconds = 90,
    [int]$FileCloseTimeoutSeconds = 8
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\..\test\GameTest.psm1') -Force

function Resolve-One($name, $id) {
    if ($id -gt 0) { $p=Get-Process -Id $id -ErrorAction Stop; if ($p.ProcessName -ne $name) { throw "PID $id is $($p.ProcessName), expected $name" }; return $p }
    $m=@(Get-Process -Name $name -ErrorAction SilentlyContinue); if ($m.Count -ne 1) { throw "Expected one $name; found $($m.Count)" }; return $m[0]
}
function Focus($p) { Set-WindowForeground -ProcessId $p.Id; Start-Sleep -Milliseconds 120 }
function Click($x,$y,$hover,$settle,$label) {
    Move-Mouse -X $x -Y $y; Start-Sleep -Milliseconds ([int]($hover*1000))
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN,0,0,0,0)
    Add-Content -LiteralPath $eventPath -Value (([ordered]@{event="${label}_down";utc=[DateTime]::UtcNow.ToString('o');x=$x;y=$y}|ConvertTo-Json -Compress))
    Start-Sleep -Milliseconds $ClickHoldMilliseconds
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP,0,0,0,0)
    Add-Content -LiteralPath $eventPath -Value (([ordered]@{event="${label}_up";utc=[DateTime]::UtcNow.ToString('o');x=$x;y=$y}|ConvertTo-Json -Compress))
    if ($settle -gt 0) { Start-Sleep -Milliseconds ([int]($settle*1000)) }
}
function ObsToggle($obs) { Focus $obs; Move-Mouse -X $ObsRecordButtonX -Y $ObsRecordButtonY; Start-Sleep -Milliseconds 100; [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN,0,0,0,0); Start-Sleep -Milliseconds $ClickHoldMilliseconds; [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP,0,0,0,0); Start-Sleep -Milliseconds 900 }

function Get-ObsConfiguredRecordingPath {
    <#
      Read the active profile without touching OBS.  OBS stores Windows path
      separators escaped as ``\\`` in basic.ini; decode only that representation
      before comparing with the requested attempt directory.  This preflight is
      deliberately fail-closed so a stale OBS profile cannot silently write a
      take into the previous attempt's folder.
    #>
    $obsRoot = Join-Path ([Environment]::GetFolderPath('ApplicationData')) 'obs-studio'
    $globalPath = Join-Path $obsRoot 'global.ini'
    if (-not (Test-Path -LiteralPath $globalPath -PathType Leaf)) { throw "OBS global.ini was not found: $globalPath" }
    $globalText = [IO.File]::ReadAllText($globalPath, [Text.UTF8Encoding]::new($false, $true))
    $profileDir = $null
    $active = $false
    foreach ($line in ($globalText -split "`r?`n")) {
        if ($line -match '^\s*\[([^]]+)\]\s*$') { $active = $Matches[1] -eq 'Basic'; continue }
        if ($active -and $line -match '^ProfileDir=(.*)$') { $profileDir = $Matches[1].Trim(); break }
    }
    if ([string]::IsNullOrWhiteSpace($profileDir)) { throw 'OBS global.ini has no active ProfileDir' }
    $profilePath = Join-Path (Join-Path $obsRoot 'basic\profiles') (Join-Path $profileDir 'basic.ini')
    if (-not (Test-Path -LiteralPath $profilePath -PathType Leaf)) { throw "OBS active profile was not found: $profilePath" }
    $profileText = [IO.File]::ReadAllText($profilePath, [Text.UTF8Encoding]::new($false, $true))
    $bodyMatch = [regex]::Match($profileText, '(?ms)^\[SimpleOutput\]\s*(?<body>.*?)(?=^\[|\z)')
    if (-not $bodyMatch.Success) { throw "OBS profile has no [SimpleOutput] section: $profilePath" }
    $pathMatch = [regex]::Match($bodyMatch.Groups['body'].Value, '(?m)^FilePath=(.*)$')
    if (-not $pathMatch.Success) { throw "OBS profile has no SimpleOutput FilePath: $profilePath" }
    $configured = $pathMatch.Groups[1].Value.Trim()
    while ($configured.Contains('\\')) { $configured = $configured.Replace('\\', '\') }
    return [IO.Path]::GetFullPath($configured)
}

$out=[IO.Path]::GetFullPath($OutputDirectory)
$game=Resolve-One 'SlayTheSpire2' $GameProcessId; $obs=Resolve-One 'obs64' $ObsProcessId
$configuredOutput = Get-ObsConfiguredRecordingPath
if ([string]::Compare($configuredOutput.TrimEnd('\'), $out.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase) -ne 0) {
    throw "OBS recording path mismatch: configured '$configuredOutput' but requested '$out'. Close OBS and run tools/promo/configure_obs.ps1 -Apply before recording. No recording was started."
}
if (Test-Path -LiteralPath $out) { if (@(Get-ChildItem -LiteralPath $out -Force).Count -gt 0) { throw "OutputDirectory must be new or empty: $out" } } else { New-Item -ItemType Directory -Force -Path $out | Out-Null }
$eventPath=Join-Path $out 'operator-events.ndjson'; New-Item -ItemType File -Force -Path $eventPath | Out-Null
$gameRect=Get-WindowRect -ProcessId $game.Id; if (($gameRect.Right-$gameRect.Left)-lt 1920 -or ($gameRect.Bottom-$gameRect.Top)-lt 1080) { throw 'Game window is smaller than 1920x1080' }
foreach($pair in @(@('rest',$RestX,$RestY),@('proceed',$ProceedX,$ProceedY))) { if($pair[1]-lt $gameRect.Left -or $pair[1]-ge $gameRect.Right -or $pair[2]-lt $gameRect.Top -or $pair[2]-ge $gameRect.Bottom){throw "$($pair[0]) point outside game window"} }
$started=Get-Date; $recording=$false; $stopped=$false
try {
    Add-Content -LiteralPath $eventPath -Value (([ordered]@{event='preflight_restsite_clean_screen';utc=[DateTime]::UtcNow.ToString('o');note='Operator confirmed Act 2/3 RestSite, injured HP, console closed'}|ConvertTo-Json -Compress))
    ObsToggle $obs; $recording=$true; Add-Content -LiteralPath $eventPath -Value (([ordered]@{event='recording_mark';utc=[DateTime]::UtcNow.ToString('o');pre_roll_seconds=$PreRollSeconds}|ConvertTo-Json -Compress))
    Focus $game; Start-Sleep -Milliseconds ([int]($PreRollSeconds*1000))
    Click $RestX $RestY $RestHoverSeconds $RestResultSeconds 'rest'
    Add-Content -LiteralPath $eventPath -Value (([ordered]@{event='rest_result_hold';utc=[DateTime]::UtcNow.ToString('o');expected='native HP increase and fire extinguished'}|ConvertTo-Json -Compress))
    Click $ProceedX $ProceedY $ProceedHoverSeconds $MapReturnSeconds 'proceed'
    Move-Mouse -X 1800 -Y 500; Start-Sleep -Milliseconds ([int]($PostMapHoldSeconds*1000))
    Focus $obs; Move-Mouse -X $ObsRecordButtonX -Y $ObsRecordButtonY; Start-Sleep -Milliseconds 100; [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN,0,0,0,0); Start-Sleep -Milliseconds $ClickHoldMilliseconds; [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP,0,0,0,0); $stopped=$true; Start-Sleep -Milliseconds 900
    $files=@(Get-ChildItem -LiteralPath $out -File -Filter '*.mkv' | Where-Object {$_.LastWriteTime -ge $started.AddSeconds(-2)} | Sort-Object LastWriteTime -Descending)
    if($files.Count -eq 0){throw 'OBS stopped but no new MKV was found'}
    $f=$files[0]; [ordered]@{status='completed';take_id='T10';attempt_id=$AttemptId;source_file=$f.FullName;bytes=$f.Length;sha256=(Get-FileHash $f.FullName -Algorithm SHA256).Hash;operator_marks_not_native=$true}|ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $out 'capture-summary.json') -Encoding UTF8
    Write-Output $f.FullName
}
finally {
    if($recording -and -not $stopped){ try { ObsToggle $obs } catch {} }
}
