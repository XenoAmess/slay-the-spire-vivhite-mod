# Unified stack stop: cooperative sentinel -> exact process-tree fallback -> game window close.
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [ValidateRange(5, 300)][int]$GraceSeconds = 40,
    [ValidateRange(5, 120)][int]$GameGraceSeconds = 20,
    [switch]$KeepGame
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
$runtimeDir = Join-Path $root ".runtime"
$sessionFile = Join-Path $runtimeDir "session.json"
$defaultGameExe = [IO.Path]::GetFullPath((Join-Path $GameDir "SlayTheSpire2.exe"))
$utf8NoBom = New-Object Text.UTF8Encoding($false)
$lifecycleLock = $null

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) }
    catch { return $null }
}

function Get-ObjectProperty {
    param([object]$Value, [string]$Name, [object]$Default = $null)
    if ($Value -and $Value.PSObject.Properties[$Name]) { return $Value.$Name }
    return $Default
}

function Read-PidRecord {
    param([string]$Path)
    try {
        if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) { return $null }
        $raw = (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop).Trim()
        if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
        try { return ($raw | ConvertFrom-Json) }
        catch {
            $number = 0
            if ([int]::TryParse($raw, [ref]$number)) {
                return [pscustomobject]@{ pid = $number; session_id = "legacy"; created_unix = 0 }
            }
            return $null
        }
    } catch {
        # Components remove their own PID records on a clean exit.
        return $null
    }
}

function Normalize-SessionId {
    param([object]$Value)
    $candidate = [string]$Value
    if ($candidate -match '^[0-9a-fA-F]{32}$') { return $candidate.ToLowerInvariant() }
    return "legacy"
}

function Resolve-ContainedPath {
    param([object]$Value, [string]$BaseDirectory, [string]$Fallback)
    $candidate = [string]$Value
    if ([string]::IsNullOrWhiteSpace($candidate)) { return [IO.Path]::GetFullPath($Fallback) }
    try {
        $full = [IO.Path]::GetFullPath($candidate)
        $base = [IO.Path]::GetFullPath($BaseDirectory).TrimEnd('\') + '\'
        if ($full.StartsWith($base, [StringComparison]::OrdinalIgnoreCase)) { return $full }
    } catch { }
    Write-Warning "Ignoring lifecycle path outside its managed directory: $candidate"
    return [IO.Path]::GetFullPath($Fallback)
}

function Get-ProcessCim {
    param([int]$ProcessId)
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Get-CreationKey {
    param([object]$Process)
    if (-not $Process -or -not $Process.CreationDate) { return 0L }
    return ([datetime]$Process.CreationDate).ToUniversalTime().Ticks
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

function Test-SameProcess {
    param([object]$Identity)
    $current = Get-ProcessCim ([int]$Identity.ProcessId)
    if (-not $current) { return $false }
    if ([string]$current.Name -ne [string]$Identity.Name) { return $false }
    if ((Get-CreationKey $current) -ne [long]$Identity.CreationKey) { return $false }
    if ([string]$current.ExecutablePath -ne [string]$Identity.ExecutablePath) { return $false }
    if ([string]$current.CommandLine -ne [string]$Identity.CommandLine) { return $false }
    return $true
}

function Test-PidRecord {
    param([object]$Record, [object]$Process, [string]$ExpectedSession, [string]$CommandPattern)
    if (-not $Record -or -not $Process) { return $false }
    $recordPid = [int](Get-ObjectProperty $Record "pid" 0)
    if ($recordPid -le 0 -or $recordPid -ne [int]$Process.ProcessId) { return $false }
    $recordSession = [string](Get-ObjectProperty $Record "session_id" "legacy")
    if ($recordSession -ne $ExpectedSession) { return $false }
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
    param([string]$ExpectedExe)
    return @(Get-CimInstance Win32_Process -Filter "Name='SlayTheSpire2.exe'" -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ExecutablePath -and
            [string]::Equals([IO.Path]::GetFullPath($_.ExecutablePath), $ExpectedExe,
                             [StringComparison]::OrdinalIgnoreCase)
        })
}

function Add-Identity {
    param([hashtable]$Map, [object]$Process, [string]$Role, [int]$Depth = 0)
    if (-not $Process) { return }
    $processId = [int]$Process.ProcessId
    if ($processId -eq $PID) { return }
    $incoming = [pscustomobject]@{
        ProcessId = $processId
        ParentProcessId = [int]$Process.ParentProcessId
        Name = [string]$Process.Name
        CreationKey = Get-CreationKey $Process
        ExecutablePath = [string]$Process.ExecutablePath
        CommandLine = [string]$Process.CommandLine
        Role = $Role
        Depth = $Depth
    }
    if (-not $Map.ContainsKey($processId)) {
        $Map[$processId] = $incoming
        return
    }
    $existing = $Map[$processId]
    $sameIdentity = ([long]$existing.CreationKey -eq [long]$incoming.CreationKey) -and
                    ([string]$existing.Name -eq [string]$incoming.Name) -and
                    ([string]$existing.ExecutablePath -eq [string]$incoming.ExecutablePath) -and
                    ([string]$existing.CommandLine -eq [string]$incoming.CommandLine)
    # A PID may be reused during the graceful wait. Replace an expired identity only
    # when fresh discovery has found the new scoped process occupying that PID.
    if (-not $sameIdentity -and -not (Test-SameProcess $existing)) {
        $Map[$processId] = $incoming
    }
}

function Add-DescendantIdentities {
    param([hashtable]$Map, [object[]]$Snapshot)
    $queue = New-Object Collections.Generic.Queue[object]
    $visited = @{}
    foreach ($processId in @($Map.Keys)) { $queue.Enqueue($Map[$processId]) }
    while ($queue.Count -gt 0) {
        $parent = $queue.Dequeue()
        $parentId = [int]$parent.ProcessId
        $visitKey = "$parentId`:$([long]$parent.CreationKey)"
        if ($visited.ContainsKey($visitKey)) { continue }
        $visited[$visitKey] = $true
        $snapshotParent = @($Snapshot | Where-Object { [int]$_.ProcessId -eq $parentId }) | Select-Object -First 1
        # Only expand a parent that is present with the same creation identity in
        # this coherent snapshot. Never infer descendants from a dead/reused PID.
        if (-not $snapshotParent -or (Get-CreationKey $snapshotParent) -ne [long]$parent.CreationKey) { continue }
        foreach ($child in @($Snapshot | Where-Object { [int]$_.ParentProcessId -eq $parentId })) {
            # A child cannot predate its alleged parent; this filters parent-PID reuse artifacts.
            $childCreation = Get-CreationKey $child
            if ($childCreation -lt [long]$parent.CreationKey) { continue }
            $childId = [int]$child.ProcessId
            Add-Identity $Map $child ("descendant-of-" + $parent.Role) ($parent.Depth + 1)
            $added = $Map[$childId]
            if ($added -and [long]$added.CreationKey -eq $childCreation) {
                $queue.Enqueue($added)
            }
        }
    }
}

function Add-ScopedProcessIdentities {
    param([hashtable]$Map, [object[]]$Snapshot, [string]$WorkspaceRoot)
    foreach ($process in $Snapshot) {
        $cmd = [string]$process.CommandLine
        if ([string]::IsNullOrWhiteSpace($cmd)) { continue }
        $scriptHost = $process.Name -match '^(python(?:w|\d+(?:\.\d+)*)?|py|uv)\.exe$'
        $matchedPath = ""
        if ($scriptHost) {
            foreach ($relative in @("brain\runner.py", "brain\review_viewer.py", "brain\llm_review.py",
                                    "tts\quipper.py", "tts\edge_speaker.py", "tts\nano_speaker.py",
                                    "tts\speaker.py", "tts\speak_once.py")) {
                $candidate = Join-Path $WorkspaceRoot $relative
                if (Test-CommandHasScriptArgument $process $candidate) { $matchedPath = $candidate; break }
            }
        }
        if (-not [string]::IsNullOrWhiteSpace($matchedPath)) {
            $role = if ([string]::Equals($matchedPath, (Join-Path $WorkspaceRoot "brain\runner.py"),
                                        [StringComparison]::OrdinalIgnoreCase)) { "runner" } else { "detached-component" }
            Add-Identity $Map $process $role 0
        } elseif ($process.Name -match '^opencode(\.exe)?$' -and
                  (Test-CommandHasScriptArgument $process (Split-Path $WorkspaceRoot -Parent)) -and
                  $cmd -match 'sts2-ascend' -and $cmd -match '--auto') {
            Add-Identity $Map $process "review-opencode" 0
        }
    }
}

function Add-PidFileIdentities {
    param([hashtable]$Map, [object[]]$Snapshot, [string]$RuntimeDirectory,
          [string]$ExpectedRunnerPath, [hashtable]$StopFileMap = $null)
    foreach ($pidFile in @(Get-ChildItem -LiteralPath $RuntimeDirectory -Filter "*.pid" -File -ErrorAction SilentlyContinue)) {
        $record = Read-PidRecord $pidFile.FullName
        $recordId = [int](Get-ObjectProperty $record "pid" 0)
        $recordSession = Normalize-SessionId (Get-ObjectProperty $record "session_id" "legacy")
        if ($StopFileMap -and $recordSession -ne "legacy") {
            $StopFileMap[(Join-Path $RuntimeDirectory "stop.$recordSession.request")] = $true
        }
        if ($recordId -le 0) { continue }
        $recordProcess = @($Snapshot | Where-Object { [int]$_.ProcessId -eq $recordId }) | Select-Object -First 1
        if ($pidFile.Name -like "runner*.pid") {
            $pattern = Get-ScriptArgumentPattern $ExpectedRunnerPath
            if ($recordProcess -and (Test-PidRecord $record $recordProcess $recordSession $pattern)) {
                Add-Identity $Map $recordProcess "runner" 0
            }
        } elseif ($pidFile.Name -like "brain*.pid") {
            $hasCreationIdentity = [long](Get-ObjectProperty $record "creation_filetime" 0) -gt 0 -or
                                   [double](Get-ObjectProperty $record "created_unix" 0) -gt 0
            if ($hasCreationIdentity -and $recordProcess -and
                (Test-PidRecord $record $recordProcess $recordSession '(^|\s)-m\s+brain(\s|$)')) {
                Add-Identity $Map $recordProcess "brain" 1
            }
        }
    }
}

function Find-LegacyRunnerIdentities {
    param([hashtable]$VerifiedMap, [hashtable]$AmbiguousMap,
          [object[]]$Snapshot, [string]$WorkspaceRoot)
    foreach ($process in $Snapshot) {
        $cmd = [string]$process.CommandLine
        if ($process.Name -notmatch '^(python(?:w|\d+(?:\.\d+)*)?|py)\.exe$' -or
            $cmd -notmatch '(?i)(^|[\s"''])brain[\\/]runner\.py([\s"'']|$)' -or
            $cmd.IndexOf($WorkspaceRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
            continue
        }
        $verified = $false
        $ancestorId = [int]$process.ParentProcessId
        $childCreation = Get-CreationKey $process
        for ($depth = 0; $depth -lt 6 -and $ancestorId -gt 0; $depth++) {
            $ancestor = @($Snapshot | Where-Object { [int]$_.ProcessId -eq $ancestorId }) | Select-Object -First 1
            if (-not $ancestor) { break }
            $ancestorCreation = Get-CreationKey $ancestor
            if ($ancestorCreation -gt $childCreation) { break }
            $ancestorCmd = [string]$ancestor.CommandLine
            if ($ancestorCmd.IndexOf($WorkspaceRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                $ancestorCmd -match 'scripts[\\/]Start-Agent\.ps1') {
                $verified = $true
                break
            }
            $ancestorId = [int]$ancestor.ParentProcessId
            $childCreation = $ancestorCreation
        }
        if ($verified) {
            Add-Identity $VerifiedMap $process "runner" 0
        } else {
            Add-Identity $AmbiguousMap $process "ambiguous-legacy-runner" 0
        }
    }
}

function Get-AliveIdentities {
    param([hashtable]$Map)
    return @($Map.Values | Where-Object { Test-SameProcess $_ })
}

function Stop-Identity {
    param([object]$Identity, [string]$Reason)
    if (-not (Test-SameProcess $Identity)) { return }
    if ($PSCmdlet.ShouldProcess("pid $($Identity.ProcessId) $($Identity.Name)", $Reason)) {
        Stop-Process -Id ([int]$Identity.ProcessId) -Force -ErrorAction SilentlyContinue
    }
}

function Remove-DeadOwnerFile {
    param([string]$Path, [hashtable]$KnownIdentities, [string]$CommandPattern = "",
          [string[]]$OwnerScripts = @())
    if (-not (Test-Path -LiteralPath $Path)) { return }
    $ownerId = 0
    try {
        $raw = (Get-Content -LiteralPath $Path -Raw -Encoding UTF8).Trim()
        if ($raw.StartsWith("{")) {
            $record = $raw | ConvertFrom-Json
            $ownerId = [int](Get-ObjectProperty $record "pid" 0)
        } else {
            [void][int]::TryParse($raw, [ref]$ownerId)
        }
    } catch { $ownerId = 0 }
    if ($ownerId -gt 0) {
        $owner = Get-ProcessCim $ownerId
        if ($owner) {
            $knownOwner = $KnownIdentities.ContainsKey($ownerId) -and
                          (Test-SameProcess $KnownIdentities[$ownerId])
            $scopedOwner = $false
            if ($OwnerScripts.Count -gt 0 -and
                $owner.Name -match '^(python(?:w|\d+(?:\.\d+)*)?|py|uv)\.exe$') {
                foreach ($script in $OwnerScripts) {
                    if (Test-CommandHasScriptArgument $owner $script) { $scopedOwner = $true; break }
                }
            } elseif (-not [string]::IsNullOrWhiteSpace($CommandPattern)) {
                $scopedOwner = ([string]$owner.CommandLine -match $CommandPattern) -and
                               (([string]$owner.CommandLine).IndexOf($root, [StringComparison]::OrdinalIgnoreCase) -ge 0)
            }
            if ($knownOwner -or $scopedOwner) {
                Write-Warning "Keeping runtime marker owned by a verified live stack process: $Path (pid $ownerId)"
                return
            }
            Write-Warning "Removing stale marker whose PID was reused by an unrelated process: $Path (pid $ownerId)"
        }
    }
    if ($PSCmdlet.ShouldProcess($Path, "remove stale runtime marker")) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
}

try {
    if (-not $WhatIfPreference) {
        New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
        $lockPath = Join-Path $runtimeDir "lifecycle.lock"
        try {
            $lifecycleLock = [IO.File]::Open($lockPath, [IO.FileMode]::OpenOrCreate,
                                            [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        } catch {
            throw "Another Start-Agent/Stop-Agent operation is in progress."
        }
    }

    $session = Read-JsonFile $sessionFile
    $sessionId = Normalize-SessionId (Get-ObjectProperty $session "session_id" "legacy")
    $defaultStopFile = if ($sessionId -eq "legacy") { Join-Path $runtimeDir "stop.request" } else {
        Join-Path $runtimeDir "stop.$sessionId.request"
    }
    $defaultRunnerPidFile = if ($sessionId -eq "legacy") { Join-Path $runtimeDir "runner.pid" } else {
        Join-Path $runtimeDir "runner.$sessionId.pid"
    }
    $defaultBrainPidFile = if ($sessionId -eq "legacy") { Join-Path $runtimeDir "brain.pid" } else {
        Join-Path $runtimeDir "brain.$sessionId.pid"
    }
    $stopFile = Resolve-ContainedPath (Get-ObjectProperty $session "stop_file" "") $runtimeDir $defaultStopFile
    $runnerPath = [IO.Path]::GetFullPath((Join-Path $root "brain\runner.py"))
    $sessionGameExe = [string](Get-ObjectProperty $session "game_exe" "")
    try {
        $gameExe = if ([string]::IsNullOrWhiteSpace($sessionGameExe)) { $defaultGameExe } else {
            [IO.Path]::GetFullPath($sessionGameExe)
        }
    } catch { $gameExe = $defaultGameExe }
    if ([IO.Path]::GetFileName($gameExe) -ne "SlayTheSpire2.exe") {
        Write-Warning "Ignoring invalid game executable in session metadata: $gameExe"
        $gameExe = $defaultGameExe
    }
    $runnerPidFile = Resolve-ContainedPath (Get-ObjectProperty $session "runner_pid_file" "") $runtimeDir $defaultRunnerPidFile
    $brainPidFile = Resolve-ContainedPath (Get-ObjectProperty $session "brain_pid_file" "") $runtimeDir $defaultBrainPidFile

    # Snapshot descendants before parents see the sentinel and orphan their children.
    $snapshot = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    $identities = @{}
    $stopFiles = @{}
    $stopFiles[$stopFile] = $true
    $stopFiles[(Join-Path $runtimeDir "stop.request")] = $true

    $runnerRecord = Read-PidRecord $runnerPidFile
    $runnerId = [int](Get-ObjectProperty $runnerRecord "pid" (Get-ObjectProperty $session "runner_pid" 0))
    if ($runnerId -gt 0) {
        $runnerProcess = @($snapshot | Where-Object { [int]$_.ProcessId -eq $runnerId }) | Select-Object -First 1
        $runnerPattern = Get-ScriptArgumentPattern $runnerPath
        $sessionCreation = [long](Get-ObjectProperty $session "runner_creation_key" 0)
        if ($runnerProcess -and (($runnerRecord -and (Test-PidRecord $runnerRecord $runnerProcess $sessionId $runnerPattern)) -or
                                ((-not $runnerRecord) -and [string]$runnerProcess.CommandLine -match $runnerPattern -and
                                 ($sessionCreation -gt 0 -and (Get-CreationKey $runnerProcess) -eq $sessionCreation)))) {
            Add-Identity $identities $runnerProcess "runner" 0
        } elseif ($runnerProcess) {
            Write-Warning "Runner PID record failed identity validation; refusing to target pid $runnerId."
        }
    }

    $brainRecord = Read-PidRecord $brainPidFile
    $brainId = [int](Get-ObjectProperty $brainRecord "pid" 0)
    if ($brainId -gt 0) {
        $brainProcess = @($snapshot | Where-Object { [int]$_.ProcessId -eq $brainId }) | Select-Object -First 1
        $brainHasCreation = [long](Get-ObjectProperty $brainRecord "creation_filetime" 0) -gt 0 -or
                            [double](Get-ObjectProperty $brainRecord "created_unix" 0) -gt 0
        if ($brainHasCreation -and $brainProcess -and
            (Test-PidRecord $brainRecord $brainProcess $sessionId '(^|\s)-m\s+brain(\s|$)')) {
            Add-Identity $identities $brainProcess "brain" 1
        } elseif ($brainProcess) {
            Write-Warning "Brain PID record failed identity validation; refusing to target pid $brainId."
        }
    }

    # Recover every GUID session still represented by a PID file, not only session.json.
    Add-PidFileIdentities $identities $snapshot $runtimeDir $runnerPath $stopFiles

    # Detached components carry absolute script paths; only this workspace is in scope.
    Add-ScopedProcessIdentities $identities $snapshot $root
    $ambiguousLegacy = @{}
    Find-LegacyRunnerIdentities $identities $ambiguousLegacy $snapshot $root

    # Plain-PID locks support old sessions; command lines still have to match this workspace.
    $lockSpecs = @(
        @{ Path = (Join-Path $root "knowledge\voice_quipper.lock");
           Scripts = @((Join-Path $root "tts\quipper.py")) },
        @{ Path = (Join-Path $root "knowledge\voice_speaker.lock");
           Scripts = @((Join-Path $root "tts\edge_speaker.py"), (Join-Path $root "tts\nano_speaker.py"),
                       (Join-Path $root "tts\speaker.py")) },
        @{ Path = (Join-Path $root "knowledge\viewer.lock");
           Scripts = @((Join-Path $root "brain\review_viewer.py")) }
    )
    foreach ($spec in $lockSpecs) {
        $record = Read-PidRecord $spec.Path
        $ownerId = [int](Get-ObjectProperty $record "pid" 0)
        $ownerSession = Normalize-SessionId (Get-ObjectProperty $record "session_id" "legacy")
        if ($ownerSession -ne "legacy") {
            $stopFiles[(Join-Path $runtimeDir "stop.$ownerSession.request")] = $true
        }
        if ($ownerId -le 0) { continue }
        $owner = @($snapshot | Where-Object { [int]$_.ProcessId -eq $ownerId }) | Select-Object -First 1
        $validOwner = $false
        if ($owner -and $owner.Name -match '^(python(?:w|\d+(?:\.\d+)*)?|py|uv)\.exe$') {
            foreach ($script in $spec.Scripts) {
                if (Test-CommandHasScriptArgument $owner $script) { $validOwner = $true; break }
            }
        }
        if ($validOwner) {
            Add-Identity $identities $owner "lock-owner" 0
        }
    }
    Add-DescendantIdentities $identities $snapshot
    $hadScopedTargets = $identities.Count -gt 0

    if ($WhatIfPreference) {
        [void]$PSCmdlet.ShouldProcess("sts2-ascend session $sessionId", "publish cooperative stop request")
        foreach ($identity in $identities.Values) {
            [void]$PSCmdlet.ShouldProcess("pid $($identity.ProcessId) $($identity.Name)", "stop scoped stack process if grace expires")
        }
        $ambiguous = @(Get-AliveIdentities $ambiguousLegacy)
        if ($ambiguous.Count -gt 0) {
            Write-Warning "$($ambiguous.Count) relative-path legacy runner(s) could not be tied safely to this workspace; actual Stop would keep the sentinel and report incomplete."
        }
        if (-not $KeepGame) {
            foreach ($game in (Get-GameProcesses $gameExe)) {
                [void]$PSCmdlet.ShouldProcess("pid $($game.ProcessId) $gameExe", "close game window")
            }
        }
        Write-Host "WhatIf complete: scoped processes=$($identities.Count)."
        return
    }

    if ($PSCmdlet.ShouldProcess("sts2-ascend session $sessionId", "publish cooperative stop request")) {
        $payload = [ordered]@{
            session_id = $sessionId
            requested_at = (Get-Date).ToString("o")
            source = "Stop-Agent.ps1"
            pid = $PID
        } | ConvertTo-Json -Compress
        foreach ($path in $stopFiles.Keys) {
            [IO.File]::WriteAllText([string]$path, $payload, $utf8NoBom)
        }
        Write-Host "Stop requested for $($stopFiles.Count) session sentinel(s); waiting up to $GraceSeconds seconds for clean shutdown..."
    }

    $deadline = (Get-Date).AddSeconds($GraceSeconds)
    do {
        $alive = @(Get-AliveIdentities $identities)
        if ($alive.Count -eq 0) { break }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)

    $alive = @(Get-AliveIdentities $identities)
    if ($alive.Count -gt 0) {
        Write-Warning "$($alive.Count) scoped process(es) exceeded the graceful timeout; applying identity-checked fallback."
        # A legacy runner must die first or it can respawn brain between fallback operations.
        foreach ($identity in @($alive | Where-Object { $_.Role -eq "runner" })) {
            Stop-Identity $identity "stop supervisor after graceful timeout"
        }
        Start-Sleep -Milliseconds 500
        $alive = @(Get-AliveIdentities $identities)
        foreach ($identity in @($alive | Sort-Object Depth -Descending)) {
            Stop-Identity $identity "stop scoped descendant after graceful timeout"
        }
        Start-Sleep -Seconds 1
    }

    # Close the narrow race where an active component spawned a child after the
    # first snapshot. An already-empty/idempotent stop needs no extra full CIM pass.
    if ($hadScopedTargets) {
        $freshSnapshot = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
        Add-PidFileIdentities $identities $freshSnapshot $runtimeDir $runnerPath $stopFiles
        Add-ScopedProcessIdentities $identities $freshSnapshot $root
        Find-LegacyRunnerIdentities $identities $ambiguousLegacy $freshSnapshot $root
        Add-DescendantIdentities $identities $freshSnapshot
        $lateAlive = @(Get-AliveIdentities $identities)
        if ($lateAlive.Count -gt 0) {
            Write-Warning "Found $($lateAlive.Count) late/residual scoped process(es); applying identity-checked fallback."
            foreach ($identity in @($lateAlive | Where-Object { $_.Role -eq "runner" })) {
                Stop-Identity $identity "stop late supervisor"
            }
            Start-Sleep -Milliseconds 300
            foreach ($identity in @((Get-AliveIdentities $identities) | Sort-Object Depth -Descending)) {
                Stop-Identity $identity "stop late scoped descendant"
            }
            Start-Sleep -Seconds 1
        }
    }

    $ambiguousAlive = @(Get-AliveIdentities $ambiguousLegacy)
    if ($ambiguousAlive.Count -gt 0) {
        $ids = ($ambiguousAlive | ForEach-Object { $_.ProcessId }) -join ","
        throw "Stack stop found relative-path legacy runner pid(s) $ids but cannot tie them safely to this workspace. The game and stop sentinel were retained; close that old foreground terminal, then run Stop-Agent.ps1 again."
    }

    if (-not $KeepGame) {
        $games = @(Get-GameProcesses $gameExe)
        foreach ($game in $games) {
            $identity = @{}
            Add-Identity $identity $game "game" 0
            $gameIdentity = $identity[[int]$game.ProcessId]
            if (-not (Test-SameProcess $gameIdentity)) { continue }
            if ($PSCmdlet.ShouldProcess("pid $($game.ProcessId) $gameExe", "close game window")) {
                $gameProcess = Get-Process -Id ([int]$game.ProcessId) -ErrorAction SilentlyContinue
                $requested = $false
                if ($gameProcess) { $requested = $gameProcess.CloseMainWindow() }
                Write-Host "Game close requested (pid $($game.ProcessId), accepted=$requested)."
            }
            $gameDeadline = (Get-Date).AddSeconds($GameGraceSeconds)
            while ((Test-SameProcess $gameIdentity) -and (Get-Date) -lt $gameDeadline) {
                Start-Sleep -Milliseconds 300
            }
            if (Test-SameProcess $gameIdentity) {
                Write-Warning "Game exceeded its close timeout; applying exact-PID fallback."
                Stop-Identity $gameIdentity "stop game after window-close timeout"
            }
        }
    }

    # Require a short quiet window after game closure. This catches a supervisor
    # that respawned brain (or a detached review/TTS child) during the first pass.
    if ($hadScopedTargets) {
        $quietSince = Get-Date
        $verificationDeadline = (Get-Date).AddSeconds(5)
        do {
            $verifySnapshot = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
            Add-PidFileIdentities $identities $verifySnapshot $runtimeDir $runnerPath $stopFiles
            Add-ScopedProcessIdentities $identities $verifySnapshot $root
            Find-LegacyRunnerIdentities $identities $ambiguousLegacy $verifySnapshot $root
            Add-DescendantIdentities $identities $verifySnapshot
            $verifyAlive = @(Get-AliveIdentities $identities)
            $ambiguousAlive = @(Get-AliveIdentities $ambiguousLegacy)
            if ($verifyAlive.Count -gt 0) {
                $quietSince = Get-Date
                foreach ($identity in @($verifyAlive | Where-Object { $_.Role -eq "runner" })) {
                    Stop-Identity $identity "stop supervisor found during final verification"
                }
                Start-Sleep -Milliseconds 200
                foreach ($identity in @((Get-AliveIdentities $identities) | Sort-Object Depth -Descending)) {
                    Stop-Identity $identity "stop scoped process found during final verification"
                }
            } elseif ($ambiguousAlive.Count -gt 0) {
                $quietSince = Get-Date
            } elseif (((Get-Date) - $quietSince).TotalMilliseconds -ge 1000) {
                break
            }
            Start-Sleep -Milliseconds 250
        } while ((Get-Date) -lt $verificationDeadline)
    }

    $ambiguousAlive = @(Get-AliveIdentities $ambiguousLegacy)
    if ($ambiguousAlive.Count -gt 0) {
        $ids = ($ambiguousAlive | ForEach-Object { $_.ProcessId }) -join ","
        throw "Stack stop cannot safely target relative-path legacy runner pid(s) $ids. The stop sentinel was retained; close that old foreground terminal, then run Stop-Agent.ps1 again."
    }

    $markerSpecs = @(
        @{ Path = (Join-Path $root "knowledge\viewer.lock"); Scripts = @((Join-Path $root "brain\review_viewer.py")) },
        @{ Path = (Join-Path $root "knowledge\voice_quipper.lock"); Scripts = @((Join-Path $root "tts\quipper.py")) },
        @{ Path = (Join-Path $root "knowledge\voice_speaker.lock"); Scripts = @((Join-Path $root "tts\edge_speaker.py"), (Join-Path $root "tts\nano_speaker.py"), (Join-Path $root "tts\speaker.py")) },
        @{ Path = (Join-Path $root "knowledge\voice_nano.lock"); Scripts = @((Join-Path $root "tts\nano_speaker.py")) },
        @{ Path = (Join-Path $root "knowledge\voice_quip_speaking.flag"); Scripts = @((Join-Path $root "tts\quipper.py")) },
        @{ Path = (Join-Path $root "knowledge\voice_clone_busy.flag"); Scripts = @((Join-Path $root "tts\quipper.py")) },
        @{ Path = (Join-Path $root "knowledge\review_active.flag"); Pattern = '(^|\s)-m\s+brain(\s|$)' },
        @{ Path = $runnerPidFile; Scripts = @($runnerPath) },
        @{ Path = $brainPidFile; Pattern = '(^|\s)-m\s+brain(\s|$)' }
    )
    foreach ($pidFile in @(Get-ChildItem -LiteralPath $runtimeDir -Filter "*.pid" -File -ErrorAction SilentlyContinue)) {
        if ($pidFile.Name -like "runner*.pid") {
            $markerSpecs += @{ Path = $pidFile.FullName; Scripts = @($runnerPath) }
        } else {
            $markerSpecs += @{ Path = $pidFile.FullName; Pattern = '(^|\s)-m\s+brain(\s|$)' }
        }
    }
    foreach ($marker in $markerSpecs) {
        $pattern = if ($marker.ContainsKey("Pattern")) { [string]$marker["Pattern"] } else { "" }
        $scripts = if ($marker.ContainsKey("Scripts")) { @($marker["Scripts"]) } else { @() }
        Remove-DeadOwnerFile $marker.Path $identities $pattern $scripts
    }

    $remaining = @(Get-AliveIdentities $identities)
    $remainingGames = @(if ($KeepGame) { @() } else { Get-GameProcesses $gameExe })
    if ($remaining.Count -eq 0 -and $remainingGames.Count -eq 0) {
        $currentSession = Read-JsonFile $sessionFile
        if ($currentSession -and [string](Get-ObjectProperty $currentSession "session_id" "") -eq $sessionId -and
            $PSCmdlet.ShouldProcess($sessionFile, "clear completed session metadata")) {
            Remove-Item -LiteralPath $sessionFile -Force -ErrorAction SilentlyContinue
        }
        # The GUID sentinel remains as an ABA guard for delayed old processes. The
        # legacy sentinel is safe to clear after a zero-process verification so
        # standalone viewer/demo diagnostics keep working after a unified stop.
        $legacyStopFile = Join-Path $runtimeDir "stop.request"
        if (Test-Path -LiteralPath $legacyStopFile) {
            Remove-Item -LiteralPath $legacyStopFile -Force -ErrorAction SilentlyContinue
        }
        Write-Host "sts2-ascend stack stopped (scoped processes=0, game=$(if ($KeepGame) {'kept'} else {'stopped'}))."
    } else {
        throw "Stack stop incomplete: scoped processes=$($remaining.Count), game processes=$($remainingGames.Count)."
    }

    if (-not $KeepGame) {
        $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalPort -ge 8080 -and $_.LocalPort -le 8084 })
        if ($listeners.Count -gt 0) {
            Write-Warning "Ports 8080-8084 still have $($listeners.Count) listener(s); Stop-Agent does not kill by port ownership."
        }
    }
} finally {
    if ($lifecycleLock) { $lifecycleLock.Dispose() }
}
