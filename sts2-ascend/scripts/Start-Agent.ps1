# Unified stack start: deploy (optional) -> game -> runner/brain -> on-demand announcers.
# Runner, not this wrapper, freezes Git HEAD + active review-marker epoch into each
# Brain child; Start must not precompute or reuse those generation-local values.
[CmdletBinding()]
param(
    [string]$Version = "0.9.1",
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [ValidateSet("auto", "fork", "release")][string]$Source = "auto",
    [string]$GodotExe = "",
    [switch]$SkipDeploy,
    [switch]$Foreground,
    [ValidateRange(5, 600)][int]$ReadyTimeoutSeconds = 120
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$runtimeDir = Join-Path $root ".runtime"
$sessionFile = Join-Path $runtimeDir "session.json"
$runnerPath = [IO.Path]::GetFullPath((Join-Path $root "brain\runner.py"))
$gameExe = [IO.Path]::GetFullPath((Join-Path $GameDir "SlayTheSpire2.exe"))
$gameLauncher = [IO.Path]::GetFullPath((Join-Path $GameDir "launch_vulkan.bat"))
$utf8NoBom = New-Object Text.UTF8Encoding($false)
$lifecycleLock = $null

function Write-Utf8Json {
    param([string]$Path, [object]$Value)
    $json = $Value | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText($Path, $json, $utf8NoBom)
}

function Read-JsonFile {
    param([string]$Path)
    try {
        if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) { return $null }
        return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json)
    }
    catch { return $null }
}

function Get-ObjectProperty {
    param([object]$Value, [string]$Name, [object]$Default = $null)
    if ($Value -and $Value.PSObject.Properties[$Name]) { return $Value.$Name }
    return $Default
}

function Normalize-SessionId {
    param([object]$Value)
    $candidate = [string]$Value
    if ($candidate -match '^[0-9a-fA-F]{32}$') { return $candidate.ToLowerInvariant() }
    return "legacy"
}

function Get-ProcessCim {
    param([int]$ProcessId)
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Test-CommandContainsPath {
    param([object]$Process, [string]$Path)
    if (-not $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    return ([string]$Process.CommandLine).IndexOf($Path, [StringComparison]::OrdinalIgnoreCase) -ge 0
}

function Get-ScriptArgumentPattern {
    param([string]$Path)
    return '(^|[\s"])' + [regex]::Escape([IO.Path]::GetFullPath($Path)) + '(?=$|[\s"])'
}

function Test-CommandHasScriptArgument {
    param([object]$Process, [string]$Path)
    if (-not $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    if ([string]$Process.CommandLine -match '(^|\s)-m\s+py_compile(\s|$)') { return $false }
    return [regex]::IsMatch([string]$Process.CommandLine, (Get-ScriptArgumentPattern $Path),
                            [Text.RegularExpressions.RegexOptions]::IgnoreCase)
}

function Test-IsOpenCodeReviewProcess {
    param([object]$Process, [string]$WorkspaceRoot)
    if (-not $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    if ($Process.Name -notmatch '^opencode(\.exe)?$') { return $false }
    $cmd = [string]$Process.CommandLine
    $reviewRoot = Join-Path $WorkspaceRoot "knowledge\code_backups\review_work"
    $reviewRepoPattern = '(?i)(?:^|\s)--dir\s+"?' +
        [regex]::Escape($reviewRoot) +
        '[\\/]+sts2-review-sandbox-[^\\/"\s]+[\\/]+repo"?(?=$|\s)'
    return [regex]::IsMatch($cmd, $reviewRepoPattern,
                            [Text.RegularExpressions.RegexOptions]::IgnoreCase) -and
           $cmd -match '(?i)(^|\s)run(?=\s)' -and
           $cmd -match '(?i)--format\s+json(?=$|\s)' -and
           $cmd -match '(?i)--auto(?=$|\s)'
}

function Test-IsCodexReviewProcess {
    param([object]$Process, [string]$WorkspaceRoot)
    if (-not $Process -or [string]::IsNullOrWhiteSpace([string]$Process.CommandLine)) { return $false }
    if ($Process.Name -notmatch '^(codex|node|cmd)\.exe$') { return $false }
    $cmd = [string]$Process.CommandLine
    $reviewRoot = Join-Path $WorkspaceRoot "knowledge\code_backups\review_work"
    $reviewRepoPattern = '(?i)(?:^|\s)(?:-C|--cd)\s+"?' +
        [regex]::Escape($reviewRoot) +
        '[\\/]+sts2-review-sandbox-[^\\/"\s]+[\\/]+repo"?(?=$|\s)'
    return [regex]::IsMatch($cmd, $reviewRepoPattern,
                            [Text.RegularExpressions.RegexOptions]::IgnoreCase) -and
           $cmd -match '(?i)(^|\s)exec(?=\s)' -and
           $cmd -match '(?i)--json' -and $cmd -match '(?i)--ephemeral'
}

function Get-CreationKey {
    param([object]$Process)
    if (-not $Process -or -not $Process.CreationDate) { return 0L }
    return ([datetime]$Process.CreationDate).ToUniversalTime().Ticks
}

function Test-PidRecord {
    param([object]$Record, [object]$Process, [string]$ExpectedSession, [string]$CommandPattern)
    if (-not $Record -or -not $Process) { return $false }
    $recordPid = [int](Get-ObjectProperty $Record "pid" 0)
    if ($recordPid -le 0 -or $recordPid -ne [int]$Process.ProcessId) { return $false }
    if ([string](Get-ObjectProperty $Record "session_id" "legacy") -ne $ExpectedSession) { return $false }
    if ([string]$Process.CommandLine -notmatch $CommandPattern) { return $false }
    $recordExe = [string](Get-ObjectProperty $Record "executable" "")
    if (-not [string]::IsNullOrWhiteSpace($recordExe)) {
        if ([string]::IsNullOrWhiteSpace([string]$Process.ExecutablePath)) { return $false }
        try {
            $sameExe = [string]::Equals([IO.Path]::GetFullPath($recordExe),
                [IO.Path]::GetFullPath([string]$Process.ExecutablePath), [StringComparison]::OrdinalIgnoreCase)
        } catch { return $false }
        if (-not $sameExe) { return $false }
    }
    $creationFiletime = [long](Get-ObjectProperty $Record "creation_filetime" 0)
    if ($creationFiletime -gt 0 -and $Process.CreationDate) {
        $actualFiletime = ([datetime]$Process.CreationDate).ToUniversalTime().ToFileTimeUtc()
        if ([math]::Abs($actualFiletime - $creationFiletime) -gt 10000) { return $false }
        return $true
    }
    $createdUnix = [double](Get-ObjectProperty $Record "created_unix" 0)
    if ($createdUnix -gt 0 -and $Process.CreationDate) {
        $epoch = [datetime]::SpecifyKind([datetime]"1970-01-01", [DateTimeKind]::Utc)
        $actualUnix = ([datetime]$Process.CreationDate).ToUniversalTime().Subtract($epoch).TotalSeconds
        if ([math]::Abs($actualUnix - $createdUnix) -gt 1) { return $false }
    }
    return $true
}

function Get-GameProcesses {
    return @(Get-CimInstance Win32_Process -Filter "Name='SlayTheSpire2.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ExecutablePath -and
            [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath), $gameExe,
                             [StringComparison]::OrdinalIgnoreCase)
        })
}

function Get-ReadyApiPort {
    foreach ($port in 8080..8084) {
        $response = $null
        try {
            $request = [Net.HttpWebRequest]::Create("http://127.0.0.1:$port/health")
            $request.Timeout = 700
            $request.ReadWriteTimeout = 700
            $response = $request.GetResponse()
            if ([int]$response.StatusCode -eq 200) {
                $reader = New-Object IO.StreamReader($response.GetResponseStream())
                try {
                    $payload = $reader.ReadToEnd() | ConvertFrom-Json
                    if ($payload -and $payload.data -and $payload.data.status -eq "ready") { return $port }
                } finally { $reader.Dispose() }
            }
        } catch { }
        finally { if ($response) { $response.Close() } }
    }
    return $null
}

function Get-PythonExe {
    $launcher = Get-Command py.exe -CommandType Application -ErrorAction SilentlyContinue
    if (-not $launcher) {
        throw "Python 3 launcher unavailable: expected 'py -3'."
    }
    $lines = @()
    $pythonExit = -1
    $savedPreference = $ErrorActionPreference
    try {
        # Some valid Windows Python installs print a harmless prefix warning to
        # stderr. Probe by exit code/stdout instead of promoting native stderr.
        $ErrorActionPreference = "SilentlyContinue"
        $lines = @(& $launcher.Source -3 -c "import sys; print(sys.executable)" 2>$null)
        $pythonExit = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $savedPreference
    }
    if ($pythonExit -ne 0 -or $lines.Count -eq 0) {
        throw "Python 3 launcher unavailable: expected 'py -3'."
    }
    $resolved = ([string]$lines[-1]).Trim()
    if (-not (Test-Path -LiteralPath $resolved)) {
        throw "Resolved Python executable does not exist: $resolved"
    }
    return [IO.Path]::GetFullPath($resolved)
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
try {
    $lockPath = Join-Path $runtimeDir "lifecycle.lock"
    try {
        $lifecycleLock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate,
                                        [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    } catch {
        throw "Another Start-Agent/Stop-Agent operation is in progress."
    }

    # Idempotency: reuse only the runner recorded for this workspace/session.
    $existingSession = Read-JsonFile $sessionFile
    $existingSessionId = Normalize-SessionId (Get-ObjectProperty $existingSession "session_id" "legacy")
    $existingRunnerId = [int](Get-ObjectProperty $existingSession "runner_pid" 0)
    $existingRunnerPidFile = if ($existingSessionId -eq "legacy") {
        Join-Path $runtimeDir "runner.pid"
    } else { Join-Path $runtimeDir "runner.$existingSessionId.pid" }
    $existingRunnerRecord = Read-JsonFile $existingRunnerPidFile
    if ($existingRunnerRecord -and
        [string](Get-ObjectProperty $existingRunnerRecord "session_id" "legacy") -eq $existingSessionId) {
        $existingRunnerId = [int](Get-ObjectProperty $existingRunnerRecord "pid" $existingRunnerId)
    }
    if ($existingSession -and $existingRunnerId -gt 0) {
        $existingRunner = Get-ProcessCim $existingRunnerId
        $expectedCreation = [long](Get-ObjectProperty $existingSession "runner_creation_key" 0)
        $runnerArgPattern = Get-ScriptArgumentPattern $runnerPath
        $recordValid = $existingRunnerRecord -and
            (Test-PidRecord $existingRunnerRecord $existingRunner $existingSessionId $runnerArgPattern)
        if ($existingRunner -and (Test-CommandHasScriptArgument $existingRunner $runnerPath) -and
            ($recordValid -or ($expectedCreation -gt 0 -and
             (Get-CreationKey $existingRunner) -eq $expectedCreation))) {
            $existingStopFile = if ($existingSessionId -eq "legacy") {
                Join-Path $runtimeDir "stop.request"
            } else { Join-Path $runtimeDir "stop.$existingSessionId.request" }
            if (Test-Path -LiteralPath $existingStopFile) {
                throw "Session $existingSessionId is already stopping (runner pid $existingRunnerId). Wait briefly or run Stop-Agent.ps1 again."
            }
            $game = @(Get-GameProcesses)
            Write-Host "sts2-ascend is already running (session $existingSessionId, runner pid $existingRunnerId, game count $($game.Count))."
            return
        }
    }

    # A crashed supervisor can leave its brain child alive. Its argv is only
    # "-m brain", so use the session-scoped PID record rather than a broad Python scan.
    $existingBrainPidFile = if ($existingSessionId -eq "legacy") {
        Join-Path $runtimeDir "brain.pid"
    } else { Join-Path $runtimeDir "brain.$existingSessionId.pid" }
    $existingBrainRecord = Read-JsonFile $existingBrainPidFile
    $existingBrainId = [int](Get-ObjectProperty $existingBrainRecord "pid" 0)
    if ($existingBrainId -gt 0) {
        $existingBrain = Get-ProcessCim $existingBrainId
        if (Test-PidRecord $existingBrainRecord $existingBrain $existingSessionId '(^|\s)-m\s+brain(\s|$)') {
            throw "A brain process from session $existingSessionId is still alive (pid $existingBrainId) without its recorded runner. Run Stop-Agent.ps1 first."
        }
    }

    # Recover orphan brains even if session.json is missing/corrupt.
    foreach ($brainPidFile in @(Get-ChildItem -LiteralPath $runtimeDir -Filter "brain*.pid" -File -ErrorAction SilentlyContinue)) {
        $record = Read-JsonFile $brainPidFile.FullName
        $recordId = [int](Get-ObjectProperty $record "pid" 0)
        if ($recordId -le 0) { continue }
        $hasCreationIdentity = [long](Get-ObjectProperty $record "creation_filetime" 0) -gt 0 -or
                               [double](Get-ObjectProperty $record "created_unix" 0) -gt 0
        if (-not $hasCreationIdentity) { continue }
        $recordSession = Normalize-SessionId (Get-ObjectProperty $record "session_id" "legacy")
        $recordProcess = Get-ProcessCim $recordId
        if (Test-PidRecord $record $recordProcess $recordSession '(^|\s)-m\s+brain(\s|$)') {
            throw "Residual brain process exists (session $recordSession, pid $recordId). Run Stop-Agent.ps1 before starting a new session."
        }
    }

    # Refuse to replace an older session while scoped detached components still live.
    $componentPaths = @(
        (Join-Path $root "brain\runner.py"), (Join-Path $root "brain\review_viewer.py"),
        (Join-Path $root "brain\llm_review.py"), (Join-Path $root "tts\quipper.py"),
        (Join-Path $root "tts\edge_speaker.py"), (Join-Path $root "tts\nano_speaker.py"),
        (Join-Path $root "tts\speaker.py"), (Join-Path $root "tts\speak_once.py")
    )
    $scoped = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $process = $_
        $cmd = [string]$process.CommandLine
        $scriptMatch = $false
        if ($process.Name -match '^(python(?:w|\d+(?:\.\d+)*)?|py|uv)\.exe$') {
            foreach ($path in $componentPaths) {
                if (Test-CommandHasScriptArgument $process $path) { $scriptMatch = $true; break }
            }
        }
        $reviewMatch = (($process.Name -match '^opencode(\.exe)?$' -and $cmd -and
            (Test-CommandHasScriptArgument $process (Split-Path $root -Parent)) -and
            $cmd -match '--auto' -and $cmd -match 'sts2-ascend') -or
            (Test-IsCodexReviewProcess $process $root))
        $reviewMatch = ((Test-IsOpenCodeReviewProcess $process $root) -or
                        (Test-IsCodexReviewProcess $process $root))
        $legacyRunnerMatch = $process.Name -match '^(python(?:w|\d+(?:\.\d+)*)?|py)\.exe$' -and
            $cmd -match '(?i)(^|[\s"''])brain[\\/]runner\.py(?=$|[\s"''])' -and
            $cmd -notmatch '(^|\s)-m\s+py_compile(\s|$)'
        $scriptMatch -or $reviewMatch -or $legacyRunnerMatch
    })
    if ($scoped.Count -gt 0) {
        $ids = ($scoped | ForEach-Object { $_.ProcessId }) -join ","
        throw "Residual sts2-ascend processes exist (pid $ids). Run Stop-Agent.ps1 before starting a new session."
    }

    # Luna is pinned to a non-global Codex CLI whose Windows filesystem helper
    # can read ordinary drive paths.  Cold starts repair/validate the
    # user cache before Brain loads config.  Failure does not block game/live
    # recovery: the exact configured binary remains absent, so Luna is reported
    # unavailable and no incompatible Codex process can consume model tokens.
    $codexCompatInstaller = Join-Path $PSScriptRoot "Install-CodexCompat.ps1"
    try {
        $codexCompatBinary = & $codexCompatInstaller | Select-Object -Last 1
        Write-Host "Pinned Codex compatibility CLI ready: $codexCompatBinary"
    }
    catch {
        Write-Warning ("Pinned Codex compatibility CLI unavailable; Luna will remain unavailable " +
                       "without starting a provider: " + $_.Exception.Message)
    }

    $game = @(Get-GameProcesses)
    if (-not $SkipDeploy) {
        if ($game.Count -gt 0) {
            throw "The game is already running, so its mod DLL may be locked. Close it or use -SkipDeploy."
        }
        $deployArgs = @{
            Version = $Version
            GameDir = $GameDir
            Source = $Source
        }
        if (-not [string]::IsNullOrWhiteSpace($GodotExe)) { $deployArgs.GodotExe = $GodotExe }
        & (Join-Path $PSScriptRoot "Deploy-Mod.ps1") @deployArgs
    }

    if (-not (Test-Path -LiteralPath $gameLauncher)) {
        throw "Vulkan launcher not found: $gameLauncher"
    }
    if (-not (Test-Path -LiteralPath $gameExe)) {
        throw "Game executable not found: $gameExe"
    }
    $pythonExe = Get-PythonExe
    $sessionId = [Guid]::NewGuid().ToString("N")
    $stopFile = Join-Path $runtimeDir "stop.$sessionId.request"
    $runnerPidFile = Join-Path $runtimeDir "runner.$sessionId.pid"
    $brainPidFile = Join-Path $runtimeDir "brain.$sessionId.pid"
    $runnerOut = Join-Path $runtimeDir "runner.$sessionId.out.log"
    $runnerErr = Join-Path $runtimeDir "runner.$sessionId.err.log"

    # A GUID-scoped sentinel prevents a late old process from being revived by a new start (ABA).
    Remove-Item -LiteralPath $stopFile -Force -ErrorAction SilentlyContinue

    if ($game.Count -eq 0) {
        Write-Host "Launching Slay the Spire 2 (Vulkan)..."
        Start-Process -FilePath $gameLauncher -WorkingDirectory $GameDir -WindowStyle Hidden | Out-Null
    } else {
        Write-Host "Game already running (pid $($game[0].ProcessId))."
    }

    $previousEnv = @{
        Session = $env:STS2_ASCEND_SESSION_ID
        Runtime = $env:STS2_ASCEND_RUNTIME_DIR
        Stop = $env:STS2_ASCEND_STOP_FILE
        GameLauncher = $env:STS2_ASCEND_GAME_LAUNCHER
    }
    $env:STS2_ASCEND_SESSION_ID = $sessionId
    $env:STS2_ASCEND_RUNTIME_DIR = $runtimeDir
    $env:STS2_ASCEND_STOP_FILE = $stopFile
    $env:STS2_ASCEND_GAME_LAUNCHER = $gameLauncher

    $session = [ordered]@{
        session_id = $sessionId
        state = "starting"
        started_at = (Get-Date).ToString("o")
        root = $root
        game_dir = [IO.Path]::GetFullPath($GameDir)
        game_exe = $gameExe
        python_exe = $pythonExe
        runner_path = $runnerPath
        runner_pid = 0
        runner_creation_key = 0
        runner_pid_file = $runnerPidFile
        brain_pid_file = $brainPidFile
        stop_file = $stopFile
    }
    Write-Utf8Json $sessionFile $session

    try {
        if ($Foreground) {
            $session.state = "foreground"
            Write-Utf8Json $sessionFile $session
            $lifecycleLock.Dispose()
            $lifecycleLock = $null
            Write-Host "Starting runner in foreground. Use Stop-Agent.ps1 for a complete stack stop."
            & $pythonExe -u $runnerPath
            exit $LASTEXITCODE
        }

        $quotedRunner = '"' + $runnerPath + '"'
        $runner = Start-Process -FilePath $pythonExe -ArgumentList @("-u", $quotedRunner) `
            -WorkingDirectory $root -WindowStyle Hidden `
            -RedirectStandardOutput $runnerOut -RedirectStandardError $runnerErr -PassThru
        $session.runner_pid = $runner.Id
        $runnerCim = $null
        $runnerIdentityDeadline = (Get-Date).AddSeconds(5)
        do {
            $runnerCim = Get-ProcessCim $runner.Id
            if ($runnerCim) { break }
            Start-Sleep -Milliseconds 100
        } while ((Get-Date) -lt $runnerIdentityDeadline)
        $session.runner_creation_key = Get-CreationKey $runnerCim
        $session.state = "running"
        Write-Utf8Json $sessionFile $session
        Write-Host "Runner started in background (pid $($runner.Id), session $sessionId)."
        # Session metadata is now durable; release the mutex so Stop-Agent can cancel a slow boot.
        $lifecycleLock.Dispose()
        $lifecycleLock = $null

        $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
        $brainReady = $false
        $apiPort = $null
        do {
            $brainReady = $false
            $runner.Refresh()
            if (Test-Path -LiteralPath $stopFile) {
                Write-Host "Startup was cancelled by Stop-Agent.ps1."
                return
            }
            if ($runner.HasExited) {
                $tail = ""
                if (Test-Path -LiteralPath $runnerErr) {
                    $tail = (Get-Content -LiteralPath $runnerErr -Tail 20 -Encoding UTF8) -join [Environment]::NewLine
                }
                throw "Runner exited during startup (code $($runner.ExitCode)). $tail"
            }
            $brainRecord = Read-JsonFile $brainPidFile
            $brainRecordId = [int](Get-ObjectProperty $brainRecord "pid" 0)
            if ($brainRecordId -gt 0) {
                $brainProcess = Get-ProcessCim $brainRecordId
                $brainStage = [string](Get-ObjectProperty $brainRecord "stage" "")
                $brainReady = (Test-PidRecord $brainRecord $brainProcess $sessionId '(^|\s)-m\s+brain(\s|$)') -and
                    ($brainStage -eq "ready")
            }
            $apiPort = Get-ReadyApiPort
            if ($brainReady -and $apiPort) { break }
            Start-Sleep -Milliseconds 500
        } while ((Get-Date) -lt $deadline)

        if ($brainReady -and $apiPort) {
            Write-Host "Stack ready: brain active, API http://127.0.0.1:$apiPort."
        } else {
            Write-Warning "Runner is active but readiness timed out (brain=$brainReady, api=$apiPort). It will keep self-healing in the background."
        }
        Write-Host "ASCEND-VISION starts with brain and is supervised for self-healing; Quipper starts when its voice model is available; review OpenCode/speaker remain on demand."
        Write-Host "Brain hotkeys (global): Ctrl+Alt+F9 = stop / hand control to player; Ctrl+Alt+F10 = start / resume."
        Write-Host "Stop the complete stack with: powershell -NoProfile -ExecutionPolicy Bypass -File .\sts2-ascend\scripts\Stop-Agent.ps1"
    } finally {
        if ($null -eq $previousEnv.Session) { Remove-Item Env:STS2_ASCEND_SESSION_ID -ErrorAction SilentlyContinue }
        else { $env:STS2_ASCEND_SESSION_ID = $previousEnv.Session }
        if ($null -eq $previousEnv.Runtime) { Remove-Item Env:STS2_ASCEND_RUNTIME_DIR -ErrorAction SilentlyContinue }
        else { $env:STS2_ASCEND_RUNTIME_DIR = $previousEnv.Runtime }
        if ($null -eq $previousEnv.Stop) { Remove-Item Env:STS2_ASCEND_STOP_FILE -ErrorAction SilentlyContinue }
        else { $env:STS2_ASCEND_STOP_FILE = $previousEnv.Stop }
        if ($null -eq $previousEnv.GameLauncher) { Remove-Item Env:STS2_ASCEND_GAME_LAUNCHER -ErrorAction SilentlyContinue }
        else { $env:STS2_ASCEND_GAME_LAUNCHER = $previousEnv.GameLauncher }
    }
} finally {
    if ($lifecycleLock) { $lifecycleLock.Dispose() }
}
