[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [Parameter(Mandatory = $true)][int]$GameProcessId,
    [Parameter(Mandatory = $true)][int]$ObsProcessId,
    [string]$RunId = "run-20260903T0012-director-v2-a1",
    [Parameter(Mandatory = $true)][string]$AttemptId,
    [int]$AddCardX = 960,
    [int]$AddCardY = 515,
    [int]$CardChoiceX = 610,
    [int]$CardChoiceY = 590,
    [int]$SkipX = 1720,
    [int]$SkipY = 820,
    [int]$MapNodeX = 510,
    [int]$MapNodeY = 550,
    [int]$ObsControlX = 1260,
    [int]$ObsControlY = 657,
    [int]$NeutralX = 1800,
    [int]$NeutralY = 500
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "..\..\test\GameTest.psm1"
Import-Module $modulePath -ErrorAction Stop
. (Join-Path $PSScriptRoot "promo_capture_operator_common.ps1")

$out = Assert-NewOperatorAttempt -OutputDirectory $OutputDirectory -AttemptId $AttemptId
$game = Resolve-UniqueOperatorProcess -ProcessName "SlayTheSpire2" -ProcessId $GameProcessId
$obs = Resolve-UniqueOperatorProcess -ProcessName "obs64" -ProcessId $ObsProcessId
$events = New-Object "System.Collections.Generic.List[object]"
$baseTick = [Diagnostics.Stopwatch]::GetTimestamp()
$recordingStarted = $false
$recordingStopped = $false
$source = $null
$failure = $null

function Add-T07Mark {
    param([Parameter(Mandatory = $true)][string]$Name, [hashtable]$Details = $null)
    $tick = [Diagnostics.Stopwatch]::GetTimestamp()
    $entry = [ordered]@{
        name = $Name
        utc = [DateTimeOffset]::UtcNow.ToString("o")
        monotonic_tick = [int64]$tick
        elapsed_seconds = [Math]::Round((($tick - $baseTick) / [double][Diagnostics.Stopwatch]::Frequency), 6)
    }
    if ($null -ne $Details) { foreach ($k in $Details.Keys) { $entry[[string]$k] = $Details[$k] } }
    [void]$events.Add([pscustomobject]$entry)
    $entry | ConvertTo-Json -Depth 10 -Compress | Add-Content -LiteralPath (Join-Path $out "operator-events.ndjson") -Encoding UTF8
    $payload = [ordered]@{
        schema_version = 1; kind = "vivhite_promo_t07_card_reward_operator_marks";
        status = if ($failure) { "operator_sequence_failed" } elseif ($recordingStopped) { "completed_operator_sequence" } else { "recording_in_progress" };
        run_id = $RunId; take_id = "T07"; attempt_id = $AttemptId; output_directory = $out;
        game_process = Get-OperatorProcessRecord -Process $game; obs_process = Get-OperatorProcessRecord -Process $obs;
        coordinates = [ordered]@{ add_card = @{x=$AddCardX;y=$AddCardY}; card_choice=@{x=$CardChoiceX;y=$CardChoiceY}; skip=@{x=$SkipX;y=$SkipY}; map_node=@{x=$MapNodeX;y=$MapNodeY}; obs=@{x=$ObsControlX;y=$ObsControlY} };
        recording = [ordered]@{ started=$recordingStarted; stopped=$recordingStopped; source_file=if($source){$source.FullName}else{$null}; source_bytes=if($source){[int64]$source.Length}else{$null}; source_sha256=if($source){(Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash}else{$null}; operator_marks_not_native=$true };
        events = @($events | ForEach-Object { $_ }); error=$failure
    }
    Write-OperatorMarksAtomic -Marks $payload -PartialPath (Join-Path $out "operator-marks.partial.json")
}

function Wait-T07([double]$Seconds) { Sleep-OperatorSeconds -Seconds $Seconds }
function Focus-Game { Set-WindowForeground -ProcessId $GameProcessId; Wait-T07 0.12 }
function Focus-Obs { Set-WindowForeground -ProcessId $ObsProcessId; Wait-T07 0.25 }
function Hover-T07([string]$Name,[int]$X,[int]$Y,[double]$Seconds) {
    Add-T07Mark "$Name.hover_begin" @{x=$X;y=$Y}; Move-Mouse -X $X -Y $Y; Wait-T07 $Seconds; Add-T07Mark "$Name.hover_end" @{x=$X;y=$Y}
}
function Click-T07([string]$Name,[int]$X,[int]$Y) {
    Move-Mouse -X $X -Y $Y; Wait-T07 0.06
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTDOWN,0,0,0,0); Add-T07Mark "$Name.pointer_down" @{x=$X;y=$Y}
    Start-Sleep -Milliseconds 90
    [GameInputNative]::mouse_event([GameInputNative]::MOUSEEVENTF_LEFTUP,0,0,0,0); Add-T07Mark "$Name.pointer_up" @{x=$X;y=$Y}
}
function Start-ObsT07 {
    Add-T07Mark "recording.start_request" @{method="uia_stable_automation_id"}
    Invoke-ObsRecordToggle -Process $obs -ExpectedAction start
    if (-not (Wait-ObsRecordState -Process $obs -ExpectedState recording -TimeoutMilliseconds 5000)) {
        throw "OBS did not enter recording state"
    }
    $script:recordingStarted=$true
    Add-T07Mark "recording.start_returned" @{method="uia_stable_automation_id"}
    Wait-T07 0.9
    Focus-Game
}
function Stop-ObsT07 {
    if (-not $recordingStarted -or $recordingStopped) { return }
    Add-T07Mark "recording.stop_request" @{method="uia_stable_automation_id"}
    Invoke-ObsRecordToggle -Process $obs -ExpectedAction stop
    if (-not (Wait-ObsRecordState -Process $obs -ExpectedState stopped -TimeoutMilliseconds 5000)) {
        throw "OBS did not enter stopped state"
    }
    Wait-T07 0.8
    $script:recordingStopped=$true
    Add-T07Mark "recording.stop_returned" @{method="uia_stable_automation_id"}
    $deadline=[DateTime]::UtcNow.AddSeconds(8); do { $files=@(Get-ChildItem -LiteralPath $out -Filter *.mkv -File -ErrorAction SilentlyContinue); if($files.Count -gt 0){$script:source=$files | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1; break}; Start-Sleep -Milliseconds 250 } while([DateTime]::UtcNow -lt $deadline)
    if($null -eq $source){throw "OBS did not write an MKV under $out"}; Add-T07Mark "recording.file_closed" @{path=$source.FullName;bytes=[int64]$source.Length;sha256=(Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash}
}

try {
    Focus-Game; Add-T07Mark "formal_sequence.ready"
    Start-ObsT07
    Add-T07Mark "formal_sequence.clean_preroll_begin"; Wait-T07 2.0; Add-T07Mark "formal_sequence.clean_preroll_end"
    Hover-T07 "reward_add_card" $AddCardX $AddCardY 1.5; Click-T07 "choose_reward_add_card" $AddCardX $AddCardY; Wait-T07 1.0
    Hover-T07 "reward_card" $CardChoiceX $CardChoiceY 1.5; Click-T07 "choose_reward_card" $CardChoiceX $CardChoiceY; Wait-T07 1.2
    Hover-T07 "reward_skip" $SkipX $SkipY 0.6; Click-T07 "open_map" $SkipX $SkipY; Wait-T07 1.2
    Hover-T07 "map_node" $MapNodeX $MapNodeY 1.5; Click-T07 "choose_map_node" $MapNodeX $MapNodeY; Wait-T07 2.2
    Move-Mouse -X $NeutralX -Y $NeutralY; Add-T07Mark "formal_sequence.clean_result_hold_begin"; Wait-T07 3.2; Add-T07Mark "formal_sequence.clean_result_hold_end"
}
catch { $failure=$_.Exception.Message; try { Add-T07Mark "formal_sequence.error" @{message=$failure} } catch {} }
finally { try { Stop-ObsT07 } catch { $failure=if($failure){$failure}else{$_.Exception.Message}; try{Add-T07Mark "recording.stop_error" @{message=$failure}}catch{} } }

$final=[ordered]@{schema_version=1;kind="vivhite_promo_t07_card_reward_operator_marks";status=if($failure){"failed"}else{"completed"};run_id=$RunId;take_id="T07";attempt_id=$AttemptId;output_directory=$out;operator_marks=(Join-Path $out "operator-marks.json");partial_marks=(Join-Path $out "operator-marks.partial.json");event_log=(Join-Path $out "operator-events.ndjson");recording_started=$recordingStarted;recording_stopped=$recordingStopped;source_file=if($source){$source.FullName}else{$null};source_bytes=if($source){[int64]$source.Length}else{$null};source_sha256=if($source){(Get-FileHash -LiteralPath $source.FullName -Algorithm SHA256).Hash}else{$null};error=$failure}
$json=$final|ConvertTo-Json -Depth 12; [IO.File]::WriteAllText((Join-Path $out "operator-marks.json"),$json,[Text.UTF8Encoding]::new($false)); $final|ConvertTo-Json -Depth 8 -Compress; if($failure){exit 1}
