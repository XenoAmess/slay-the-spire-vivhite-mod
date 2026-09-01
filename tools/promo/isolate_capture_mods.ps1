<#
.SYNOPSIS
Temporarily removes known in-game overlay mods for a clean Vivhite capture.

.DESCRIPTION
This is a narrowly scoped, reversible production helper.  It does not delete
or modify a mod: it moves the exact STS2AIAgent files and the exact subscribed
LieRenTVmod Workshop directory into a timestamped, hash-recorded project
backup.  The game must be stopped before either action.  No other mod, Steam
file, save, or user data is scanned or touched.

Use -Apply before a capture session and -Restore after the session.  The
active.json marker is retained in the project's ignored .work tree while the
isolation is active; successful restoration renames it to a timestamped
restored record instead of erasing the audit trail.
#>
[CmdletBinding(DefaultParameterSetName = "Inspect")]
param(
    [string]$GameDir = "G:\SteamLibrary\steamapps\common\Slay the Spire 2",
    [string]$ProjectRoot = "",
    [Parameter(ParameterSetName = "Apply", Mandatory = $true)][switch]$Apply,
    [Parameter(ParameterSetName = "Restore", Mandatory = $true)][switch]$Restore,
    [switch]$Json
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$gameRoot = [IO.Path]::GetFullPath($GameDir)
$projectRootFull = [IO.Path]::GetFullPath($ProjectRoot)
$modsRoot = [IO.Path]::GetFullPath((Join-Path $gameRoot "mods"))
$workRoot = [IO.Path]::GetFullPath((Join-Path $projectRootFull ".work\promo-capture-isolation"))
$activePath = Join-Path $workRoot "active.json"
$gameExe = [IO.Path]::GetFullPath((Join-Path $gameRoot "SlayTheSpire2.exe"))

# Move-Item is intentionally used instead of copy/delete so an isolation run
# is reversible.  Across volumes PowerShell may emulate a move as a copy plus
# delete; fail closed rather than silently changing that safety property.
$gameVolume = [IO.Path]::GetPathRoot($gameRoot)
$projectVolume = [IO.Path]::GetPathRoot($projectRootFull)
if (-not $gameVolume.Equals($projectVolume, [StringComparison]::OrdinalIgnoreCase)) {
    throw "game and project roots must be on the same volume for a reversible isolation: $gameVolume vs $projectVolume"
}

function Write-JsonAtomic {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Value
    )
    $temporary = "$Path.codex-$([Guid]::NewGuid().ToString('N')).tmp"
    try {
        $text = $Value | ConvertTo-Json -Depth 20
        [IO.File]::WriteAllText($temporary, $text + "`r`n", [Text.UTF8Encoding]::new($false))
        # The destination is always a newly allocated marker/record.  Do not
        # force an overwrite if a concurrent invocation (or a tampered marker)
        # managed to occupy it between validation and the move.
        Move-Item -LiteralPath $temporary -Destination $Path
    }
    finally {
        if (Test-Path -LiteralPath $temporary -PathType Leaf) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}

function Get-CanonicalPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [IO.Path]::GetFullPath($Path)
}

function Test-PathUnder {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Candidate
    )
    $rootFull = (Get-CanonicalPath -Path $Root).TrimEnd('\', '/')
    $candidateFull = Get-CanonicalPath -Path $Candidate
    $prefix = $rootFull + [IO.Path]::DirectorySeparatorChar
    return $candidateFull.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-PathUnder {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Candidate,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if (-not (Test-PathUnder -Root $Root -Candidate $Candidate)) {
        throw "$Label escapes its allowed root: $Candidate"
    }
}

function Assert-NoReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path)
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "refusing to move a reparse point: $Path"
    }
    if ($item.PSIsContainer) {
        foreach ($child in (Get-ChildItem -LiteralPath $Path -Recurse -Force -ErrorAction Stop)) {
            if (($child.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw "refusing to move a tree containing a reparse point: $($child.FullName)"
            }
        }
    }
}

function Assert-GameStopped {
    # Query the exact executable name first, then resolve each process path.
    # Silently ignoring an inaccessible ``Path`` would make a live game look
    # stopped and permit moving a DLL underneath it, so inability to prove the
    # identity is itself a fail-closed error.
    $running = @(Get-Process -Name "SlayTheSpire2" -ErrorAction SilentlyContinue)
    foreach ($process in $running) {
        try {
            $processPath = $process.Path
        }
        catch {
            throw "cannot verify SlayTheSpire2.exe process identity (PID $($process.Id)); stop it before changing capture mods"
        }
        if ([string]::IsNullOrWhiteSpace([string]$processPath)) {
            throw "cannot verify SlayTheSpire2.exe process path (PID $($process.Id)); stop it before changing capture mods"
        }
        if ([IO.Path]::GetFullPath([string]$processPath).Equals($gameExe, [StringComparison]::OrdinalIgnoreCase)) {
            throw "SlayTheSpire2.exe is running (PID $($process.Id)); stop the game before changing capture mods"
        }
    }
}

function Hash-File {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToUpperInvariant()
}

function Get-FileManifest {
    param([Parameter(Mandatory = $true)][string]$Root)
    $rootFull = [IO.Path]::GetFullPath($Root)
    $items = New-Object "System.Collections.Generic.List[object]"
    foreach ($item in (Get-ChildItem -LiteralPath $rootFull -Recurse -File -Force | Sort-Object FullName)) {
        $relative = $item.FullName.Substring($rootFull.Length).TrimStart('\', '/')
        $items.Add([pscustomobject]@{
                path = $relative.Replace('\', '/')
                bytes = [int64]$item.Length
                sha256 = Hash-File -Path $item.FullName
            })
    }
    # PowerShell 5.1 cannot reliably enumerate a generic List inside an
    # array-subexpression (it raises "Argument types do not match").  Return a
    # real object array so the helper works on the supported Windows shell.
    return $items.ToArray()
}

function Test-EntryHashAtPath {
    param(
        [Parameter(Mandatory = $true)]$Entry,
        [Parameter(Mandatory = $true)][string]$Path
    )
    if ($Entry.kind -eq "file") {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
        $item = Get-Item -LiteralPath $Path -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { return $false }
        return ([int64]$item.Length -eq [int64]$Entry.bytes) -and ((Hash-File -Path $item.FullName) -eq [string]$Entry.sha256)
    }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return $false }
    try { Assert-NoReparsePoint -Path $Path } catch { return $false }
    $actual = @(Get-FileManifest -Root $Path)
    $expected = @($Entry.files)
    if ($actual.Count -ne $expected.Count) { return $false }
    for ($index = 0; $index -lt $actual.Count; $index++) {
        if ($actual[$index].path -ne $expected[$index].path -or
            [int64]$actual[$index].bytes -ne [int64]$expected[$index].bytes -or
            $actual[$index].sha256 -ne $expected[$index].sha256) { return $false }
    }
    return $true
}

function Test-EntryHash {
    param([Parameter(Mandatory = $true)]$Entry)
    return Test-EntryHashAtPath -Entry $Entry -Path ([string]$Entry.original_path)
}

function New-TargetDefinitions {
    return @(
        [pscustomobject]@{
            id = "sts2-ai-agent-manifest"
            kind = "file"
            original_path = [IO.Path]::GetFullPath((Join-Path $modsRoot "mod_id.json"))
            relative = "mods/mod_id.json"
        },
        [pscustomobject]@{
            id = "sts2-ai-agent-dll"
            kind = "file"
            original_path = [IO.Path]::GetFullPath((Join-Path $modsRoot "STS2AIAgent.dll"))
            relative = "mods/STS2AIAgent.dll"
        },
        [pscustomobject]@{
            id = "sts2-ai-agent-pck"
            kind = "file"
            original_path = [IO.Path]::GetFullPath((Join-Path $modsRoot "STS2AIAgent.pck"))
            relative = "mods/STS2AIAgent.pck"
        },
        [pscustomobject]@{
            id = "workshop-lieren-tvmod"
            kind = "directory"
            original_path = [IO.Path]::GetFullPath((Join-Path $gameRoot "..\..\workshop\content\2868840\3787753911"))
            relative = "workshop/content/2868840/3787753911"
        }
    )
}

function Assert-TargetDefinitions {
    param([Parameter(Mandatory = $true)][object[]]$Definitions)

    # Keep the move set deny-only and explicit.  The marker is an audit input,
    # not permission to accept arbitrary paths from a hand-edited JSON file.
    $expected = @{
        "sts2-ai-agent-manifest" = [IO.Path]::GetFullPath((Join-Path $modsRoot "mod_id.json"))
        "sts2-ai-agent-dll"      = [IO.Path]::GetFullPath((Join-Path $modsRoot "STS2AIAgent.dll"))
        "sts2-ai-agent-pck"      = [IO.Path]::GetFullPath((Join-Path $modsRoot "STS2AIAgent.pck"))
        "workshop-lieren-tvmod"  = [IO.Path]::GetFullPath((Join-Path $gameRoot "..\..\workshop\content\2868840\3787753911"))
    }
    $expectedKinds = @{
        "sts2-ai-agent-manifest" = "file"
        "sts2-ai-agent-dll"      = "file"
        "sts2-ai-agent-pck"      = "file"
        "workshop-lieren-tvmod"  = "directory"
    }
    $expectedRelative = @{
        "sts2-ai-agent-manifest" = "mods/mod_id.json"
        "sts2-ai-agent-dll"      = "mods/STS2AIAgent.dll"
        "sts2-ai-agent-pck"      = "mods/STS2AIAgent.pck"
        "workshop-lieren-tvmod"  = "workshop/content/2868840/3787753911"
    }
    $seen = @{}
    foreach ($definition in $Definitions) {
        $id = [string]$definition.id
        if (-not $expected.ContainsKey($id) -or $seen.ContainsKey($id)) {
            throw "capture isolation target definition is not canonical: $id"
        }
        $seen[$id] = $true
        $actual = [IO.Path]::GetFullPath([string]$definition.original_path)
        if (-not $actual.Equals($expected[$id], [StringComparison]::OrdinalIgnoreCase)) {
            throw "capture isolation target path is not canonical for ${id}: $actual"
        }
        if (-not ([string]$definition.kind).Equals($expectedKinds[$id], [StringComparison]::Ordinal) -or
            -not ([string]$definition.relative).Equals($expectedRelative[$id], [StringComparison]::Ordinal)) {
            throw "capture isolation target shape is not canonical for ${id}"
        }
        if ($id -eq "workshop-lieren-tvmod") {
            Assert-PathUnder -Root (Join-Path $gameRoot "..\..\workshop\content\2868840") -Candidate $actual -Label $id
        }
        else {
            Assert-PathUnder -Root $modsRoot -Candidate $actual -Label $id
        }
    }
    if ($seen.Count -ne $expected.Count) {
        throw "capture isolation target definitions are incomplete"
    }
}

function Assert-ActiveState {
    param([Parameter(Mandatory = $true)]$State, [Parameter(Mandatory = $true)][object[]]$Definitions)

    if ($State.kind -ne "vivhite-capture-mod-isolation" -or [int]$State.format_version -ne 1) {
        throw "active isolation marker has an unsupported format"
    }
    if ($State.status -ne "active") { throw "active isolation marker is not active" }
    if ((Get-CanonicalPath -Path ([string]$State.game_root)) -ine $gameRoot -or
        (Get-CanonicalPath -Path ([string]$State.mods_root)) -ine $modsRoot) {
        throw "active isolation marker belongs to a different game or mods root"
    }
    $backupRoot = Get-CanonicalPath -Path ([string]$State.backup_root)
    Assert-PathUnder -Root $workRoot -Candidate $backupRoot -Label "active backup_root"
    if (-not (Test-Path -LiteralPath $backupRoot -PathType Container)) {
        throw "isolation backup root is missing: $backupRoot"
    }
    $byId = @{}
    foreach ($definition in $Definitions) { $byId[[string]$definition.id] = $definition }
    $entries = @($State.entries)
    if ($entries.Count -ne $Definitions.Count) {
        throw "active isolation marker has an unexpected entry count"
    }
    $seen = @{}
    foreach ($entry in $entries) {
        $id = [string]$entry.id
        if (-not $byId.ContainsKey($id) -or $seen.ContainsKey($id)) {
            throw "active isolation marker contains a non-canonical or duplicate entry: $id"
        }
        $seen[$id] = $true
        $definition = $byId[$id]
        if (-not ([string]$entry.kind).Equals([string]$definition.kind, [StringComparison]::Ordinal)) {
            throw "active isolation marker kind mismatch for $id"
        }
        $original = Get-CanonicalPath -Path ([string]$entry.original_path)
        $expectedOriginal = Get-CanonicalPath -Path ([string]$definition.original_path)
        if (-not $original.Equals($expectedOriginal, [StringComparison]::OrdinalIgnoreCase)) {
            throw "active isolation marker original path mismatch for $id"
        }
        if ([string]$entry.relative -ne [string]$definition.relative) {
            throw "active isolation marker relative path mismatch for $id"
        }
        $expectedBackup = Get-ExpectedBackupPath -BackupRoot $backupRoot -Target $definition
        if (-not (Get-CanonicalPath -Path ([string]$entry.backup_path)).Equals($expectedBackup, [StringComparison]::OrdinalIgnoreCase)) {
            throw "active isolation marker backup path mismatch for $id"
        }
        Assert-PathUnder -Root $backupRoot -Candidate ([string]$entry.backup_path) -Label "active backup_path for $id"
        if (-not (Test-Path -LiteralPath $entry.backup_path)) {
            throw "isolation backup is missing: $($entry.backup_path)"
        }
        $backupItem = Get-Item -LiteralPath $entry.backup_path -Force
        if ($definition.kind -eq "file" -and $backupItem.PSIsContainer) {
            throw "file capture backup has directory shape: $($entry.backup_path)"
        }
        if ($definition.kind -eq "directory" -and (-not $backupItem.PSIsContainer)) {
            throw "directory capture backup has file shape: $($entry.backup_path)"
        }
        Assert-NoReparsePoint -Path $entry.backup_path
        if (-not (Test-EntryHashAtPath -Entry $entry -Path ([string]$entry.backup_path))) {
            throw "isolation backup failed its recorded hash check: $($entry.backup_path)"
        }
    }
    if ($seen.Count -ne $Definitions.Count) {
        throw "active isolation marker entries are incomplete"
    }
    return $entries
}

function Assert-TargetShape {
    param([Parameter(Mandatory = $true)]$Target)
    $isFile = Test-Path -LiteralPath $Target.original_path -PathType Leaf
    $isDirectory = Test-Path -LiteralPath $Target.original_path -PathType Container
    if ($Target.kind -eq "file" -and (-not $isFile -or $isDirectory)) {
        throw "capture target is not the expected regular file: $($Target.original_path)"
    }
    if ($Target.kind -eq "directory" -and (-not $isDirectory -or $isFile)) {
        throw "capture target is not the expected directory: $($Target.original_path)"
    }
    Assert-NoReparsePoint -Path $Target.original_path
}

function Get-ExpectedBackupPath {
    param(
        [Parameter(Mandatory = $true)][string]$BackupRoot,
        [Parameter(Mandatory = $true)]$Target
    )
    if ($Target.kind -eq "directory") {
        return [IO.Path]::GetFullPath((Join-Path $BackupRoot $Target.id))
    }
    return [IO.Path]::GetFullPath((Join-Path $BackupRoot ($Target.id + [IO.Path]::GetExtension($Target.original_path))))
}

function Emit-Result {
    param([Parameter(Mandatory = $true)]$Value)
    if ($Json) { $Value | ConvertTo-Json -Depth 20 }
    else {
        $Value.PSObject.Properties | ForEach-Object { "{0}: {1}" -f $_.Name, $_.Value }
    }
}

if (-not (Test-Path -LiteralPath $gameRoot -PathType Container)) { throw "game directory does not exist: $gameRoot" }
if (-not (Test-Path -LiteralPath $modsRoot -PathType Container)) { throw "game mods directory does not exist: $modsRoot" }
if (-not (Test-Path -LiteralPath $projectRootFull -PathType Container)) { throw "project root does not exist: $projectRootFull" }
if (Test-Path -LiteralPath $workRoot) {
    if (Test-Path -LiteralPath $workRoot -PathType Leaf) {
        throw "capture isolation work root is a file, not a directory: $workRoot"
    }
    Assert-NoReparsePoint -Path $workRoot
}
else {
    New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
}
$targets = @(New-TargetDefinitions)
Assert-TargetDefinitions -Definitions $targets

if ($Restore) {
    Assert-GameStopped
    if (-not (Test-Path -LiteralPath $activePath -PathType Leaf)) {
        throw "no active capture isolation marker was found: $activePath"
    }
    Assert-NoReparsePoint -Path $activePath
    $state = Get-Content -LiteralPath $activePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $entries = @(Assert-ActiveState -State $state -Definitions $targets)
    foreach ($entry in $entries) {
        if ((Test-Path -LiteralPath $entry.original_path -PathType Leaf) -or
            (Test-Path -LiteralPath $entry.original_path -PathType Container)) {
            throw "refusing to overwrite a path that appeared while isolated: $($entry.original_path)"
        }
    }

    $movedEntries = New-Object "System.Collections.Generic.List[object]"
    $restoreCommitted = $false
    try {
        foreach ($entry in $entries) {
            $parent = Split-Path -Parent $entry.original_path
            New-Item -ItemType Directory -Path $parent -Force | Out-Null
            $movedEntries.Add([pscustomobject]@{
                    original_path = [string]$entry.original_path
                    backup_path = [string]$entry.backup_path
                    entry = $entry
                    moved = $false
                })
            Move-Item -LiteralPath $entry.backup_path -Destination $entry.original_path
            $movedEntries[$movedEntries.Count - 1].moved = $true
        }
        foreach ($entry in $entries) {
            if (-not (Test-EntryHash -Entry $entry)) {
                throw "restored capture-mod target failed its recorded hash check: $($entry.original_path)"
            }
        }
        $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
        $restoredPath = Join-Path $workRoot ("restored-{0}-{1}.json" -f $stamp, ([Guid]::NewGuid().ToString("N")))
        $state.status = "restored"
        $state | Add-Member -MemberType NoteProperty -Name restored_at_utc -Value ((Get-Date).ToUniversalTime().ToString("o")) -Force
        Write-JsonAtomic -Path $restoredPath -Value $state
        $restoreCommitted = $true
        Remove-Item -LiteralPath $activePath -Force
        Emit-Result -Value ([pscustomobject]@{ status = "restored"; record = $restoredPath; entries = $entries.Count })
        exit 0
    }
    catch {
        $failure = $_
        if (-not $restoreCommitted) {
            $rollbackFailures = New-Object "System.Collections.Generic.List[string]"
            $rollbackOrder = @($movedEntries | Where-Object { $_.moved })
            [Array]::Reverse($rollbackOrder)
            foreach ($moved in $rollbackOrder) {
                try {
                    if ((Test-Path -LiteralPath $moved.backup_path -PathType Leaf) -or
                        (Test-Path -LiteralPath $moved.backup_path -PathType Container)) {
                        throw "backup path is no longer empty during restore rollback"
                    }
                    if (-not (Test-Path -LiteralPath $moved.original_path -PathType Leaf) -and
                        -not (Test-Path -LiteralPath $moved.original_path -PathType Container)) {
                        throw "restored path disappeared during restore rollback"
                    }
                    if (-not (Test-EntryHashAtPath -Entry $moved.entry -Path $moved.original_path)) {
                        throw "restored path changed during restore rollback"
                    }
                    Move-Item -LiteralPath $moved.original_path -Destination $moved.backup_path
                }
                catch {
                    $rollbackFailures.Add("$($moved.original_path): $($_.Exception.Message)")
                }
            }
            if ($rollbackFailures.Count -gt 0) {
                throw "restore failed and rollback was incomplete: $($rollbackFailures -join '; '); original error: $($failure.Exception.Message)"
            }
        }
        throw $failure
    }
}

if ($Apply) {
    Assert-GameStopped
    if ((Test-Path -LiteralPath $activePath -PathType Leaf) -or
        (Test-Path -LiteralPath $activePath -PathType Container)) {
        throw "capture mod isolation is already active; restore it before applying a new isolation"
    }
    foreach ($target in $targets) { Assert-TargetShape -Target $target }
    $stamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssfffZ")
    $backupRoot = [IO.Path]::GetFullPath((Join-Path $workRoot ("backup-{0}-{1}" -f $stamp, ([Guid]::NewGuid().ToString("N").Substring(0, 8)))))
    Assert-PathUnder -Root $workRoot -Candidate $backupRoot -Label "backup_root"
    if (Test-Path -LiteralPath $backupRoot) {
        throw "generated isolation backup root already exists: $backupRoot"
    }
    New-Item -ItemType Directory -Path $backupRoot | Out-Null
    $entries = New-Object "System.Collections.Generic.List[object]"
    $movePlan = New-Object "System.Collections.Generic.List[object]"
    $markerWritten = $false
    try {
        foreach ($target in $targets) {
            $backupPath = Get-ExpectedBackupPath -BackupRoot $backupRoot -Target $target
            Assert-PathUnder -Root $backupRoot -Candidate $backupPath -Label "backup_path for $($target.id)"
            if (Test-Path -LiteralPath $backupPath) {
                throw "generated isolation backup path already exists: $backupPath"
            }
            if ($target.kind -eq "directory") {
                $files = @(Get-FileManifest -Root $target.original_path)
                $entry = [pscustomobject]@{ id=$target.id; kind=$target.kind; relative=$target.relative; original_path=$target.original_path; backup_path=$backupPath; files=$files }
            }
            else {
                $item = Get-Item -LiteralPath $target.original_path -Force
                $entry = [pscustomobject]@{ id=$target.id; kind=$target.kind; relative=$target.relative; original_path=$target.original_path; backup_path=$backupPath; bytes=[int64]$item.Length; sha256=(Hash-File -Path $item.FullName) }
            }
            $entries.Add($entry)
            $movePlan.Add([pscustomobject]@{ original_path=[string]$target.original_path; backup_path=$backupPath; entry=$entry; moved=$false })
            Move-Item -LiteralPath $target.original_path -Destination $backupPath
            $movePlan[$movePlan.Count - 1].moved = $true
        }
        foreach ($entry in $entries) {
            if ((Test-Path -LiteralPath $entry.original_path -PathType Leaf) -or
                (Test-Path -LiteralPath $entry.original_path -PathType Container)) {
                throw "isolation verification failed; target still exists: $($entry.original_path)"
            }
            if (-not (Test-EntryHashAtPath -Entry $entry -Path ([string]$entry.backup_path))) {
                throw "isolation backup failed its recorded hash check: $($entry.backup_path)"
            }
        }
        $state = [pscustomobject]@{
            format_version = 1
            kind = "vivhite-capture-mod-isolation"
            status = "active"
            applied_at_utc = (Get-Date).ToUniversalTime().ToString("o")
            game_root = $gameRoot
            mods_root = $modsRoot
            backup_root = $backupRoot
            entries = $entries.ToArray()
            policy = "STS2AIAgent and LieRenTVmod are absent from the capture process; no other files are changed"
        }
        Write-JsonAtomic -Path $activePath -Value $state
        $markerWritten = $true
        Emit-Result -Value ([pscustomobject]@{ status = "applied"; marker = $activePath; backup_root = $backupRoot; entries = $entries.Count })
        exit 0
    }
    catch {
        $failure = $_
        if (-not $markerWritten) {
            $rollbackFailures = New-Object "System.Collections.Generic.List[string]"
            $rollbackOrder = @($movePlan | Where-Object { $_.moved })
            [Array]::Reverse($rollbackOrder)
            foreach ($moved in $rollbackOrder) {
                try {
                    if ((Test-Path -LiteralPath $moved.original_path -PathType Leaf) -or
                        (Test-Path -LiteralPath $moved.original_path -PathType Container)) {
                        throw "original path appeared during apply rollback"
                    }
                    if (-not (Test-EntryHashAtPath -Entry $moved.entry -Path $moved.backup_path)) {
                        throw "backup changed during apply rollback"
                    }
                    Move-Item -LiteralPath $moved.backup_path -Destination $moved.original_path
                }
                catch {
                    $rollbackFailures.Add("$($moved.original_path): $($_.Exception.Message)")
                }
            }
            if ($rollbackFailures.Count -gt 0) {
                throw "apply failed and rollback was incomplete: $($rollbackFailures -join '; '); original error: $($failure.Exception.Message)"
            }
        }
        throw $failure
    }
}

$present = @($targets | ForEach-Object {
        [pscustomobject]@{ id=$_.id; path=$_.original_path; present=(Test-Path -LiteralPath $_.original_path) }
    })
Emit-Result -Value ([pscustomobject]@{ status = "inspect"; game_root=$gameRoot; active=(Test-Path -LiteralPath $activePath -PathType Leaf); targets=$present })
