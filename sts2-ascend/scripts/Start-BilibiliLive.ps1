[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "Medium")]
param(
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [ValidateRange(5, 600)][int]$ReadyTimeoutSeconds = 120,
    [ValidateRange(5, 120)][int]$LiveTimeoutSeconds = 30,
    [ValidateRange(5, 300)][int]$GameplayReadyTimeoutSeconds = 30
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$modulePath = Join-Path $PSScriptRoot "BilibiliLive.psm1"
$startAgent = Join-Path $PSScriptRoot "Start-Agent.ps1"
Import-Module $modulePath -Force

# A stack/API health response only proves that the process is alive.  Before a
# broadcast click, require an authoritative non-menu game state *and* a fresh
# Brain decision that is actually executable.  Keep this gate local and
# read-only: it never clicks Livehime, sends a game action, or starts a second
# monitor.  A failed preflight therefore leaves the already-started stack
# available for repair.  It never starts Livehime; if an earlier stream is
# already active, the failure path stops that stream instead of leaving it idle.
$script:GameplayPassiveScreens = @(
    "", "UNKNOWN", "WAITING", "TITLE", "MAIN_MENU", "CHARACTER_SELECT",
    "PROFILE_SELECT", "RUN_HISTORY", "CREDITS", "GAME_OVER", "VICTORY",
    "RUN_COMPLETE"
)
$script:GameplayDecisionStatuses = @(
    "applied"
)

function Get-AscendProperty {
    param(
        [AllowNull()][object]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) { return $null }
    # Preserve one-element arrays (for example available_actions) instead of
    # letting PowerShell's pipeline enumerate them into a scalar string.
    Write-Output -NoEnumerate $property.Value
}

function Test-AscendRunId {
    param([AllowNull()][object]$Value)
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return $false }
    return $text.Trim() -notmatch '^(?i:run_unknown|unknown|none|demo)$'
}

function Get-AscendApiState {
    param(
        [int[]]$Ports = (8080..8084),
        [ValidateRange(200, 5000)][int]$TimeoutMilliseconds = 800
    )
    foreach ($port in $Ports) {
        $response = $null
        $reader = $null
        try {
            $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$port/state")
            $request.Timeout = $TimeoutMilliseconds
            $request.ReadWriteTimeout = $TimeoutMilliseconds
            $request.Method = "GET"
            $request.Accept = "application/json"
            $response = $request.GetResponse()
            $reader = New-Object IO.StreamReader($response.GetResponseStream())
            $envelope = $reader.ReadToEnd() | ConvertFrom-Json
            $ok = Get-AscendProperty -Object $envelope -Name "ok"
            $data = Get-AscendProperty -Object $envelope -Name "data"
            if ($ok -is [bool] -and $ok -and $null -ne $data) {
                return [pscustomobject]@{ Port = [int]$port; Data = $data }
            }
        }
        catch {
            # Probe the next local port.  All failures are intentionally
            # fail-closed in the caller rather than falling back to health.
            $null = $_
        }
        finally {
            if ($reader) { $reader.Dispose() }
            if ($response) { $response.Close() }
        }
    }
    return $null
}

function ConvertTo-AscendUtcTimestamp {
    param([AllowNull()][object]$Value)
    $text = [string]$Value
    if ([string]::IsNullOrWhiteSpace($text)) { return $null }
    try {
        return ([DateTimeOffset]::Parse($text)).ToUniversalTime()
    }
    catch {
        return $null
    }
}

function New-AscendGameplayProof {
    param(
        [bool]$Ready,
        [string]$Reason,
        [string]$Signature = "",
        [string]$ProgressSignature = "",
        [string]$SessionId = "",
        [string]$RunId = "",
        [string]$Screen = "",
        [int]$ApiPort = 0,
        [string]$DecisionId = "",
        [string]$StateVersion = ""
    )
    return [pscustomobject]@{
        Ready = [bool]$Ready
        Reason = [string]$Reason
        Signature = [string]$Signature
        ProgressSignature = [string]$ProgressSignature
        SessionId = [string]$SessionId
        RunId = [string]$RunId
        Screen = [string]$Screen
        ApiPort = [int]$ApiPort
        DecisionId = [string]$DecisionId
        StateVersion = [string]$StateVersion
    }
}

function Test-AscendLiveGameplayProof {
    <#
    Pure validation for one API/dashboard sample.  It is deliberately kept
    separate from file/network acquisition so tests can exercise the exact
    fail-closed rules with fixtures and no GUI/UAC side effects.
    #>
    param(
        [AllowNull()][object]$Session,
        [AllowNull()][object]$ApiState,
        [AllowNull()][object]$Dashboard,
        [Parameter(Mandatory = $true)][DateTimeOffset]$NowUtc,
        [ValidateRange(5, 300)][int]$MaxAgeSeconds = 5
    )

    $sessionId = ([string](Get-AscendProperty $Session "session_id")).Trim()
    if ([string]::IsNullOrWhiteSpace($sessionId)) {
        return New-AscendGameplayProof $false "session_id 缺失"
    }
    if ($sessionId -notmatch '^[A-Za-z0-9_-]{8,128}$') {
        return New-AscendGameplayProof $false "session_id 格式无效"
    }
    if (([string](Get-AscendProperty $Session "state")).Trim().ToLowerInvariant() -ne "running") {
        return New-AscendGameplayProof $false "sts2-ascend session 未处于 running"
    }

    $api = Get-AscendProperty $ApiState "Data"
    if ($null -eq $api) {
        return New-AscendGameplayProof $false "游戏 /state 不可用" -SessionId $sessionId
    }
    $apiScreen = ([string](Get-AscendProperty $api "screen")).Trim().ToUpperInvariant()
    $apiRunId = ([string](Get-AscendProperty $api "run_id")).Trim()
    $apiRun = Get-AscendProperty $api "run"
    $stateVersion = ([string](Get-AscendProperty $api "state_version")).Trim()
    if ([string]::IsNullOrWhiteSpace($stateVersion) -or $stateVersion -notmatch '^\d+$') {
        return New-AscendGameplayProof $false "游戏 state_version 缺失，无法证明状态在推进" -SessionId $sessionId
    }
    try {
        # Keep the progress token an actual non-negative integer.  Merely
        # alternating arbitrary strings would otherwise look like movement.
        $stateVersionNumber = [long]$stateVersion
    }
    catch {
        return New-AscendGameplayProof $false "游戏 state_version 无效，无法证明状态在推进" -SessionId $sessionId
    }
    if ([string]::IsNullOrWhiteSpace($apiScreen) -or
        $script:GameplayPassiveScreens -contains $apiScreen) {
        return New-AscendGameplayProof $false "游戏屏幕不是实际对局：$apiScreen" -SessionId $sessionId
    }
    $runCharacterId = ([string](Get-AscendProperty $apiRun "character_id")).Trim()
    $runFloor = Get-AscendProperty $apiRun "floor"
    if (-not (Test-AscendRunId $apiRunId) -or
        $null -eq $apiRun -or $apiRun -is [string] -or $apiRun -is [array] -or
        ([string]::IsNullOrWhiteSpace($runCharacterId) -and $null -eq $runFloor)) {
        return New-AscendGameplayProof $false "游戏没有可验证的有效 run_id/run" -SessionId $sessionId
    }
    $actions = Get-AscendProperty $api "available_actions"
    $actionValues = @($actions | ForEach-Object { ([string]$_).Trim() } |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
    if ($null -eq $actions -or $actions -is [string] -or $actionValues.Count -le 0) {
        return New-AscendGameplayProof $false "实际对局尚无可执行动作" -SessionId $sessionId -RunId $apiRunId -Screen $apiScreen
    }

    $dashSchema = [string](Get-AscendProperty $Dashboard "schema")
    if ($dashSchema -ne "sts2.ascend-live/v1") {
        return New-AscendGameplayProof $false "Brain 驾驶舱 schema 缺失或不匹配" -SessionId $sessionId
    }
    $dashSession = ([string](Get-AscendProperty $Dashboard "session_id")).Trim()
    if ($dashSession -ne $sessionId) {
        return New-AscendGameplayProof $false "Brain 驾驶舱 session_id 不匹配" -SessionId $sessionId
    }
    $connection = Get-AscendProperty $Dashboard "connection"
    $connectionStatus = ([string](Get-AscendProperty $connection "status")).Trim().ToLowerInvariant()
    if ($connectionStatus -ne "connected") {
        return New-AscendGameplayProof $false "Brain 驾驶舱连接状态不是 connected" -SessionId $sessionId
    }
    $connectionAt = ConvertTo-AscendUtcTimestamp (Get-AscendProperty $connection "at")
    if ($null -eq $connectionAt) {
        return New-AscendGameplayProof $false "Brain 驾驶舱 connection.at 无效" -SessionId $sessionId
    }
    $connectionAge = ($NowUtc.ToUniversalTime() - $connectionAt).TotalSeconds
    if ($connectionAge -lt -5 -or $connectionAge -gt $MaxAgeSeconds) {
        return New-AscendGameplayProof $false ("Brain 驾驶舱连接证据过期（{0:N1}s）" -f $connectionAge) -SessionId $sessionId
    }
    $dashRun = Get-AscendProperty $Dashboard "run"
    $dashDecision = Get-AscendProperty $Dashboard "decision"
    $dashScreen = ([string](Get-AscendProperty $dashRun "screen")).Trim().ToUpperInvariant()
    $dashRunId = ([string](Get-AscendProperty $dashRun "run_id")).Trim()
    $dashCharacterId = ([string](Get-AscendProperty $dashRun "character_id")).Trim()
    $dashFloor = Get-AscendProperty $dashRun "floor"
    if ($null -eq $dashRun -or $dashRun -is [string] -or $dashRun -is [array] -or
        ([string]::IsNullOrWhiteSpace($dashCharacterId) -and $null -eq $dashFloor)) {
        return New-AscendGameplayProof $false "Brain 驾驶舱没有完整对局状态" -SessionId $sessionId
    }
    if ($dashScreen -ne $apiScreen -or $dashRunId -ne $apiRunId) {
        return New-AscendGameplayProof $false "API 与 Brain 驾驶舱的对局身份/屏幕不一致" -SessionId $sessionId -RunId $apiRunId -Screen $apiScreen
    }
    if (-not (Test-AscendRunId $dashRunId) -or $null -eq $dashRun) {
        return New-AscendGameplayProof $false "Brain 驾驶舱没有有效对局身份" -SessionId $sessionId
    }

    $heartbeat = ConvertTo-AscendUtcTimestamp (Get-AscendProperty $Dashboard "heartbeat")
    if ($null -eq $heartbeat) {
        return New-AscendGameplayProof $false "Brain 驾驶舱 heartbeat 无效" -SessionId $sessionId
    }
    $age = ($NowUtc.ToUniversalTime() - $heartbeat).TotalSeconds
    if ($age -lt -5 -or $age -gt $MaxAgeSeconds) {
        return New-AscendGameplayProof $false ("Brain 驾驶舱数据过期（{0:N1}s）" -f $age) -SessionId $sessionId -RunId $apiRunId -Screen $apiScreen
    }

    $decisionId = ([string](Get-AscendProperty $dashDecision "decision_id")).Trim()
    $decisionStatus = ([string](Get-AscendProperty $dashDecision "status")).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($decisionId) -or
        $script:GameplayDecisionStatuses -notcontains $decisionStatus -or
        $decisionStatus -ne "applied") {
        return New-AscendGameplayProof $false "Brain 决策尚未确认 applied（可能处于等待/阻塞）" -SessionId $sessionId -RunId $apiRunId -Screen $apiScreen
    }
    $selected = Get-AscendProperty $dashDecision "selected"
    $action = ([string](Get-AscendProperty $selected "action")).Trim()
    if ([string]::IsNullOrWhiteSpace($action)) {
        $action = ([string](Get-AscendProperty $dashDecision "action")).Trim()
    }
    if ([string]::IsNullOrWhiteSpace($action)) {
        return New-AscendGameplayProof $false "Brain 决策没有可执行 action" -SessionId $sessionId -RunId $apiRunId -Screen $apiScreen
    }

    $outcome = Get-AscendProperty $dashDecision "outcome"
    $outcomeStatus = ([string](Get-AscendProperty $outcome "status")).Trim().ToLowerInvariant()
    $outcomeAt = ConvertTo-AscendUtcTimestamp (Get-AscendProperty $outcome "at")
    if ($outcomeStatus -ne "applied" -or $null -eq $outcomeAt) {
        return New-AscendGameplayProof $false "Brain action 尚未获得 applied 回执" -SessionId $sessionId -RunId $apiRunId -Screen $apiScreen
    }
    $outcomeAge = ($NowUtc.ToUniversalTime() - $outcomeAt).TotalSeconds
    if ($outcomeAge -lt -5 -or $outcomeAge -gt $MaxAgeSeconds) {
        return New-AscendGameplayProof $false ("Brain action 回执过期（{0:N1}s）" -f $outcomeAge) -SessionId $sessionId -RunId $apiRunId -Screen $apiScreen
    }

    # Exclude timestamps/revision from the signature: repeated heartbeat writes
    # without a new decision or state transition must not satisfy the progress
    # proof.  State fields plus decision/outcome identity are sufficient to show
    # that the game/Brain is moving rather than parked on a menu.
    $floor = Get-AscendProperty $apiRun "floor"
    $turn = Get-AscendProperty $api "turn"
    $hp = Get-AscendProperty $apiRun "current_hp"
    $gold = Get-AscendProperty $apiRun "gold"
    $actionSet = (@($actionValues | Sort-Object) -join ",")
    $signature = @(
        $sessionId, $apiRunId, $apiScreen, $stateVersion, $floor, $turn, $hp, $gold,
        $actionSet, $decisionId, $decisionStatus, $action, $outcomeStatus
    ) -join "|"
    $progressSignature = @(
        $sessionId, $apiRunId, $apiScreen, $stateVersion, $floor, $turn, $hp,
        $gold, $actionSet
    ) -join "|"
    return New-AscendGameplayProof $true "真实对局、Brain 决策和近期动作证据均通过" `
        -Signature $signature -ProgressSignature $progressSignature `
        -SessionId $sessionId -RunId $apiRunId -Screen $apiScreen `
        -ApiPort ([int](Get-AscendProperty $ApiState "Port")) `
        -DecisionId $decisionId -StateVersion $stateVersion
}

function Get-AscendLiveGameplayProof {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [ValidateRange(5, 300)][int]$MaxAgeSeconds = 5
    )
    $runtime = Join-Path $ProjectRoot ".runtime"
    $sessionPath = Join-Path $runtime "session.json"
    try {
        $session = Get-Content -LiteralPath $sessionPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return New-AscendGameplayProof $false "无法读取当前 sts2-ascend session.json"
    }
    $sessionId = ([string](Get-AscendProperty $session "session_id")).Trim()
    if ([string]::IsNullOrWhiteSpace($sessionId) -or
        $sessionId -notmatch '^[A-Za-z0-9_-]{8,128}$') {
        return New-AscendGameplayProof $false "session_id 缺失或格式无效"
    }
    $dashboardPath = Join-Path $runtime ("live_dashboard.{0}.json" -f $sessionId)
    try {
        $dashboardItem = Get-Item -LiteralPath $dashboardPath -ErrorAction Stop
        if (((Get-Date).ToUniversalTime() - $dashboardItem.LastWriteTimeUtc).TotalSeconds -gt $MaxAgeSeconds) {
            return New-AscendGameplayProof $false "Brain 驾驶舱文件已过期" -SessionId $sessionId
        }
        $dashboard = Get-Content -LiteralPath $dashboardPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    catch {
        return New-AscendGameplayProof $false "无法读取当前 session 的 Brain 驾驶舱快照" -SessionId $sessionId
    }
    $apiState = Get-AscendApiState
    return Test-AscendLiveGameplayProof -Session $session -ApiState $apiState `
        -Dashboard $dashboard -NowUtc ([DateTimeOffset]::UtcNow) -MaxAgeSeconds $MaxAgeSeconds
}

function Wait-AscendLiveGameplayReady {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [ValidateRange(5, 300)][int]$TimeoutSeconds = 30,
        [ValidateRange(5, 300)][int]$MaxAgeSeconds = 5
    )
    $deadline = (Get-Date).ToUniversalTime().AddSeconds($TimeoutSeconds)
    $previousSignature = ""
    $previousProgressSignature = ""
    $previousStateVersion = -1L
    $previousRunId = ""
    $validSampleSeen = $false
    $last = New-AscendGameplayProof $false "尚未取得真实对局证据"
    do {
        $last = Get-AscendLiveGameplayProof -ProjectRoot $ProjectRoot -MaxAgeSeconds $MaxAgeSeconds
        if ($last.Ready) {
            # A fresh heartbeat or a newly-issued decision ID is not enough:
            # require both an identity change and a state/material change so a
            # static action cannot be re-proposed to satisfy the preflight.
            $currentStateVersion = [long]$last.StateVersion
            if ($validSampleSeen -and
                $last.RunId -eq $previousRunId -and
                $last.Signature -ne $previousSignature -and
                $last.ProgressSignature -ne $previousProgressSignature -and
                $currentStateVersion -gt $previousStateVersion) {
                return $last
            }
            $validSampleSeen = $true
            $previousSignature = $last.Signature
            $previousProgressSignature = $last.ProgressSignature
            $previousStateVersion = $currentStateVersion
            $previousRunId = $last.RunId
        }
        else {
            # A menu/blocked sample invalidates the continuity proof; require two
            # fresh, progressing samples after it recovers.
            $validSampleSeen = $false
            $previousSignature = ""
            $previousProgressSignature = ""
            $previousStateVersion = -1L
            $previousRunId = ""
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date).ToUniversalTime() -lt $deadline)
    if ($last.Ready) {
        $last = New-AscendGameplayProof $false "真实对局证据未显示持续的新决策/动作进展" `
            -ProgressSignature $last.ProgressSignature -SessionId $last.SessionId `
            -RunId $last.RunId -Screen $last.Screen -ApiPort $last.ApiPort `
            -DecisionId $last.DecisionId -StateVersion $last.StateVersion
    }
    return $last
}

function Stop-UnsafeExistingLivehime {
    <#
    A preflight failure must never leave an already-active broadcast running
    while the game/Brain is idle.  Restrict this helper to the exact
    Streaming state: Unknown/Starting/Stopping are not safe click targets and
    are reported to the caller without guessing.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$Reason,
        [ValidateRange(5, 120)][int]$TimeoutSeconds = 30
    )
    $state = Get-LivehimeStreamingState
    if ($state -ne "Streaming") { return $state }
    try {
        Invoke-LivehimeBridge -Action Stop -TimeoutSeconds $TimeoutSeconds
    }
    catch {
        throw ("CRITICAL: gameplay proof failed ({0}); the existing Bilibili " -f $Reason +
               "stream could not be stopped: " + $_.Exception.Message)
    }
    $state = Get-LivehimeStreamingState
    if ($state -ne "Idle") {
        throw ("CRITICAL: gameplay proof failed ({0}) and the existing Bilibili " -f $Reason +
               "stream could not be confirmed Idle; current state is '$state'.")
    }
    return $state
}

if (-not $PSCmdlet.ShouldProcess("sts2-ascend, Bilibili Livehime, and Slay the Spire 2",
        "start the full stack, start Bilibili streaming, and make the game TOPMOST")) {
    return
}

$projectRoot = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
# If a caller is trying to recover/restart while Livehime is already
# Streaming, perform a read-only proof before touching the stack.  An invalid
# proof is stopped and confirmed Idle *first*, so a slow stack startup cannot
# extend an empty broadcast.  Idle remains untouched, which preserves the
# user's explicit down/off state when this entrypoint is not used.
$liveState = Get-LivehimeStreamingState
if ($liveState -eq "Streaming") {
    $existingProof = Get-AscendLiveGameplayProof -ProjectRoot $projectRoot -MaxAgeSeconds 5
    if (-not $existingProof.Ready) {
        $liveState = Stop-UnsafeExistingLivehime -Reason $existingProof.Reason `
            -TimeoutSeconds $LiveTimeoutSeconds
    }
}

& $startAgent -GameDir $GameDir -SkipDeploy -ReadyTimeoutSeconds $ReadyTimeoutSeconds
$gameplayProof = Wait-AscendLiveGameplayReady -ProjectRoot $projectRoot `
    -TimeoutSeconds $GameplayReadyTimeoutSeconds -MaxAgeSeconds 5
if (-not $gameplayProof.Ready) {
    $liveState = Stop-UnsafeExistingLivehime -Reason $gameplayProof.Reason `
        -TimeoutSeconds $LiveTimeoutSeconds
    throw ("Refusing to start Bilibili streaming: {0}. " -f $gameplayProof.Reason +
           "No stream was started; current Livehime state is '$liveState'. " +
           "Keep it Idle and repair/prove real gameplay first.")
}
Write-Host ("Gameplay preflight passed: run={0}, screen={1}, api_port={2}; " -f
    $gameplayProof.RunId, $gameplayProof.Screen, $gameplayProof.ApiPort +
    "two progressing Brain/game samples observed.")
Invoke-LivehimeBridge -Action Start -TimeoutSeconds $LiveTimeoutSeconds
Set-SlayTheSpireTopMost -GameDir $GameDir -TimeoutSeconds $ReadyTimeoutSeconds
Set-AscendViewerTopMost
Write-Host "Bilibili streaming started through Livehime; Slay the Spire 2 is TOPMOST."
