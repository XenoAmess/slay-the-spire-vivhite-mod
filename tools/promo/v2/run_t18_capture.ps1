[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [int]$GameProcessId = 0,
    [int]$ObsProcessId = 0,
    [int]$ClosedX = 1280,
    [int]$WaltzX = 1450
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
Import-Module (Join-Path $PSScriptRoot '..\..\test\GameTest.psm1')

if ($GameProcessId -le 0) { $GameProcessId = (Get-Process SlayTheSpire2 | Select-Object -First 1).Id }
if ($ObsProcessId -le 0) { $ObsProcessId = (Get-Process obs64 | Select-Object -First 1).Id }

function Drag-Card([int]$x, [int]$targetX, [int]$targetY) {
    Move-Mouse -X $x -Y 950
    Start-Sleep -Milliseconds 2500
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    Start-Sleep -Milliseconds 120
    [GameInputNative]::SetCursorPos($x, 840)
    Start-Sleep -Milliseconds 120
    [GameInputNative]::SetCursorPos($x, 720)
    Start-Sleep -Milliseconds 120
    [GameInputNative]::SetCursorPos($targetX, $targetY)
    Start-Sleep -Milliseconds 120
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
}

function Set-Mark([hashtable]$table, [string]$name) {
    $table[$name] = [DateTime]::UtcNow.ToString('o')
}

$marks = [ordered]@{
    schema = 'vivhite-promo-t18-operator-marks-v1'
    output_directory = $OutputDirectory
    game_process_id = $GameProcessId
    obs_process_id = $ObsProcessId
    start_request_utc = $null
    closed_hover_start_utc = $null
    closed_release_utc = $null
    waltz_hover_start_utc = $null
    waltz_release_utc = $null
    stop_request_utc = $null
}

Set-WindowForeground -ProcessId $ObsProcessId
Start-Sleep -Milliseconds 450
Invoke-MouseClick -X 1260 -Y 657
Start-Sleep -Milliseconds 900
Set-WindowForeground -ProcessId $GameProcessId
Start-Sleep -Seconds 5

$marks.start_request_utc = [DateTime]::UtcNow.ToString('o')
$marks.closed_hover_start_utc = [DateTime]::UtcNow.ToString('o')
Drag-Card -x $ClosedX -targetX $ClosedX -targetY 580
$marks.closed_release_utc = [DateTime]::UtcNow.ToString('o')
Start-Sleep -Seconds 4
Move-Mouse -X 380 -Y 782
Start-Sleep -Seconds 3

$marks.waltz_hover_start_utc = [DateTime]::UtcNow.ToString('o')
Drag-Card -x $WaltzX -targetX 1200 -targetY 620
$marks.waltz_release_utc = [DateTime]::UtcNow.ToString('o')
Start-Sleep -Seconds 8
Move-Mouse -X 1800 -Y 500
Start-Sleep -Seconds 5

$marks.stop_request_utc = [DateTime]::UtcNow.ToString('o')
Set-WindowForeground -ProcessId $ObsProcessId
Start-Sleep -Milliseconds 350
Invoke-MouseClick -X 1260 -Y 657
Start-Sleep -Seconds 3

$dir = Split-Path -Parent $OutputDirectory
if ($dir -and -not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
$marks | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'operator-marks.json') -Encoding utf8
$marks | ConvertTo-Json -Compress
