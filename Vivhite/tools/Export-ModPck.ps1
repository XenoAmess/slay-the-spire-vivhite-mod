[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$GodotExe,

    [Parameter(Mandatory = $true)]
    [string]$ProjectDir,

    [Parameter(Mandatory = $true)]
    [string]$Preset,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [string]$ValidatorPath,

    [Parameter(Mandatory = $true)]
    [string]$AssemblyPath,

    [Parameter(Mandatory = $true)]
    [string]$ManifestPath,

    [Parameter(Mandatory = $true)]
    [string]$ModOutputDir,

    [Parameter(Mandatory = $true)]
    [string]$RitsuLibVersion,

    [string]$IroncladSkinRuntimeLayout = "legacy-single-page",

    [string]$PowerShellExe = "",

    [string]$DotnetRoot = "",

    [string]$FailurePoint = "",

    [ValidateRange(1, 600)]
    [int]$LockTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-NormalizedDirectoryPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $fullPath = [IO.Path]::GetFullPath($Path)
    $root = [IO.Path]::GetPathRoot($fullPath)
    if ($fullPath.Length -gt $root.Length) {
        return $fullPath.TrimEnd([IO.Path]::DirectorySeparatorChar, [IO.Path]::AltDirectorySeparatorChar)
    }
    return $fullPath
}

function Test-PathInsideDirectory {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Directory
    )

    $pathFull = [IO.Path]::GetFullPath($Path)
    $directoryFull = (Get-NormalizedDirectoryPath $Directory) + [IO.Path]::DirectorySeparatorChar
    return $pathFull.StartsWith($directoryFull, [StringComparison]::OrdinalIgnoreCase)
}

function Invoke-InjectedFailure {
    param([Parameter(Mandatory = $true)][string]$Point)

    if ([string]::Equals($FailurePoint, $Point, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Injected Vivhite deployment failure at '$Point'."
    }
}

function Get-FileDigest {
    param([Parameter(Mandatory = $true)][string]$Path)

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Get-DirectorySnapshot {
    param([Parameter(Mandatory = $true)][string]$Path)

    $snapshot = [ordered]@{}
    if (-not [IO.Directory]::Exists($Path)) {
        return $snapshot
    }

    $prefix = (Get-NormalizedDirectoryPath $Path) + [IO.Path]::DirectorySeparatorChar
    foreach ($file in Get-ChildItem -LiteralPath $Path -File -Recurse -Force | Sort-Object FullName) {
        $relativePath = $file.FullName.Substring($prefix.Length).Replace('\', '/')
        $snapshot[$relativePath] = Get-FileDigest $file.FullName
    }
    return $snapshot
}

function Assert-DirectorySnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)]$Expected,
        [Parameter(Mandatory = $true)][string]$Subject
    )

    $actual = Get-DirectorySnapshot $Path
    $expectedKeys = @($Expected.Keys)
    $actualKeys = @($actual.Keys)
    if ($expectedKeys.Count -ne $actualKeys.Count) {
        throw "$Subject file count changed: expected $($expectedKeys.Count), found $($actualKeys.Count)."
    }
    foreach ($key in $expectedKeys) {
        if (-not $actual.Contains($key) -or
            -not [string]::Equals([string]$Expected[$key], [string]$actual[$key], [StringComparison]::OrdinalIgnoreCase)) {
            throw "$Subject changed at '$key'."
        }
    }
}

function Remove-OwnedDirectory {
    param([string]$Path)

    if (-not [string]::IsNullOrWhiteSpace($Path) -and [IO.Directory]::Exists($Path)) {
        [IO.Directory]::Delete($Path, $true)
    }
}

function Assert-ExactTriplet {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][hashtable]$ExpectedHashes,
        [Parameter(Mandatory = $true)][string]$Subject
    )

    $files = @(Get-ChildItem -LiteralPath $Directory -File)
    $directories = @(Get-ChildItem -LiteralPath $Directory -Directory)
    if ($files.Count -ne 3 -or $directories.Count -ne 0) {
        throw "$Subject must contain exactly three files and no subdirectories."
    }
    foreach ($fileName in $ExpectedHashes.Keys) {
        $path = Join-Path $Directory $fileName
        if (-not [IO.File]::Exists($path)) {
            throw "$Subject is missing '$fileName'."
        }
        $actualHash = Get-FileDigest $path
        if (-not [string]::Equals($actualHash, [string]$ExpectedHashes[$fileName], [StringComparison]::OrdinalIgnoreCase)) {
            throw "$Subject hash mismatch for '$fileName'."
        }
    }
}

function Get-RequiredBatchSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][string[]]$RequiredNames,
        [Parameter(Mandatory = $true)][string]$Subject,
        [switch]$RequireExactTriplet
    )

    if (-not [IO.Directory]::Exists($Directory)) {
        throw "$Subject directory does not exist: $Directory"
    }
    foreach ($fileName in $RequiredNames) {
        $path = Join-Path $Directory $fileName
        if (-not [IO.File]::Exists($path)) {
            throw "$Subject is incomplete: missing '$fileName'."
        }
        $file = [IO.FileInfo]::new($path)
        $file.Refresh()
        if ($file.Length -le 0) {
            throw "$Subject is incomplete: '$fileName' is empty."
        }
    }
    if ($RequireExactTriplet) {
        $files = @(Get-ChildItem -LiteralPath $Directory -File -Force)
        $directories = @(Get-ChildItem -LiteralPath $Directory -Directory -Force)
        if ($files.Count -ne $RequiredNames.Count -or $directories.Count -ne 0) {
            throw "$Subject is not a complete staged triplet: expected exactly $($RequiredNames.Count) files and no subdirectories."
        }
    }
    $snapshot = Get-DirectorySnapshot $Directory
    if ($snapshot.Count -lt $RequiredNames.Count) {
        throw "$Subject could not be hashed as a complete batch."
    }
    return $snapshot
}

function Enter-DeploymentLock {
    param(
        [Parameter(Mandatory = $true)][string]$LockPath,
        [Parameter(Mandatory = $true)][string]$CanonicalLivePath,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastError = $null
    do {
        try {
            $stream = [IO.File]::Open(
                $LockPath,
                [IO.FileMode]::OpenOrCreate,
                [IO.FileAccess]::ReadWrite,
                [IO.FileShare]::None)
            $bytes = [Text.UTF8Encoding]::new($false).GetBytes($CanonicalLivePath)
            $stream.SetLength(0)
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
            return $stream
        }
        catch [IO.IOException] {
            $lastError = $_.Exception.Message
            Start-Sleep -Milliseconds 50
        }
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "Timed out after $TimeoutSeconds seconds waiting for the Vivhite deployment lock for '$CanonicalLivePath'. Last error: $lastError"
}

function Get-OwnedTransactionResidues {
    param(
        [Parameter(Mandatory = $true)][string]$ParentDirectory,
        [Parameter(Mandatory = $true)][string]$LiveDirectoryName
    )

    $prefixes = [ordered]@{
        previous = ".$LiveDirectoryName.previous."
        staging = ".$LiveDirectoryName.staging."
        failed = ".$LiveDirectoryName.failed."
    }
    $owned = @()
    foreach ($entry in Get-ChildItem -LiteralPath $ParentDirectory -Force) {
        foreach ($kind in $prefixes.Keys) {
            $prefix = [string]$prefixes[$kind]
            if (-not $entry.Name.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                continue
            }
            $suffix = $entry.Name.Substring($prefix.Length)
            if ([string]::IsNullOrWhiteSpace($suffix) -or -not $entry.PSIsContainer) {
                throw "Malformed owned Vivhite transaction residue '$($entry.FullName)'; refusing to publish."
            }
            $actualParent = Get-NormalizedDirectoryPath ([IO.Path]::GetDirectoryName($entry.FullName))
            if (-not [string]::Equals($actualParent, $ParentDirectory, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Owned Vivhite transaction residue escaped the normalized live parent: $($entry.FullName)"
            }
            $owned += [pscustomobject]@{
                Kind = [string]$kind
                Path = Get-NormalizedDirectoryPath $entry.FullName
                Name = $entry.Name
            }
            break
        }
    }
    return @($owned)
}

function Get-QuarantineModRoot {
    param(
        [Parameter(Mandatory = $true)][string]$LiveParentDirectory,
        [Parameter(Mandatory = $true)][string]$LiveDirectoryName
    )

    $scannerParent = [IO.Path]::GetDirectoryName($LiveParentDirectory)
    if ([string]::IsNullOrWhiteSpace($scannerParent)) {
        throw "Cannot place Vivhite rollback quarantine outside the Mod scanner for '$LiveParentDirectory'."
    }
    $quarantineRoot = Get-NormalizedDirectoryPath (Join-Path $scannerParent ".vivhite-deploy-quarantine")
    if (-not [string]::Equals(
            [IO.Path]::GetPathRoot($quarantineRoot),
            [IO.Path]::GetPathRoot($LiveParentDirectory),
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "Vivhite rollback quarantine must be on the same volume as the live Mod directory."
    }
    return Get-NormalizedDirectoryPath (Join-Path $quarantineRoot $LiveDirectoryName)
}

function Assert-RecoveryArchive {
    param(
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        $ExpectedSnapshot = $null
    )

    Add-Type -AssemblyName System.IO.Compression
    $stream = $null
    $archive = $null
    try {
        $stream = [IO.File]::Open($ArchivePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $archive = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Read, $false)
        $manifestEntry = $archive.GetEntry("vivhite-recovery-manifest.json")
        if ($null -eq $manifestEntry) {
            throw "Recovery archive has no embedded manifest."
        }
        $manifestStream = $manifestEntry.Open()
        try {
            $reader = [IO.StreamReader]::new($manifestStream, [Text.Encoding]::UTF8, $true, 4096, $true)
            try {
                $manifest = $reader.ReadToEnd() | ConvertFrom-Json -ErrorAction Stop
            }
            finally {
                $reader.Dispose()
            }
        }
        finally {
            $manifestStream.Dispose()
        }
        if (-not [string]::Equals([string]$manifest.format, "VivhiteDeploymentRecovery/v1", [StringComparison]::Ordinal)) {
            throw "Recovery archive has an unknown manifest format."
        }
        $records = @($manifest.files)
        if ($records.Count -le 0 -or $archive.Entries.Count -ne ($records.Count + 1)) {
            throw "Recovery archive membership does not match its embedded manifest."
        }
        $snapshot = [ordered]@{}
        foreach ($record in $records) {
            $relativePath = [string]$record.path
            if ([string]::IsNullOrWhiteSpace($relativePath) -or $snapshot.Contains($relativePath)) {
                throw "Recovery archive contains an invalid or duplicate relative path."
            }
            $entry = $archive.GetEntry("batch/$relativePath")
            if ($null -eq $entry -or $entry.Length -ne [long]$record.length) {
                throw "Recovery archive entry metadata mismatch for '$relativePath'."
            }
            $entryStream = $entry.Open()
            $sha = [Security.Cryptography.SHA256]::Create()
            try {
                $hash = [BitConverter]::ToString($sha.ComputeHash($entryStream)).Replace("-", "")
            }
            finally {
                $sha.Dispose()
                $entryStream.Dispose()
            }
            if (-not [string]::Equals($hash, [string]$record.sha256, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Recovery archive hash mismatch for '$relativePath'."
            }
            $snapshot[$relativePath] = $hash
        }
        if ($null -ne $ExpectedSnapshot) {
            $expectedKeys = @($ExpectedSnapshot.Keys)
            $actualKeys = @($snapshot.Keys)
            if ($expectedKeys.Count -ne $actualKeys.Count) {
                throw "Recovery archive snapshot count mismatch."
            }
            foreach ($key in $expectedKeys) {
                if (-not $snapshot.Contains($key) -or
                    -not [string]::Equals([string]$snapshot[$key], [string]$ExpectedSnapshot[$key], [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Recovery archive does not preserve '$key'."
                }
            }
        }
        return $snapshot
    }
    finally {
        if ($null -ne $archive) {
            $archive.Dispose()
        }
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}

function New-VerifiedRecoveryArchive {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDirectory,
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)]$ExpectedSnapshot
    )

    Add-Type -AssemblyName System.IO.Compression
    Assert-DirectorySnapshot $SourceDirectory $ExpectedSnapshot "The rollback source before recovery archival"
    $temporaryArchive = "$ArchivePath.tmp.$([Guid]::NewGuid().ToString('N'))"
    $stream = $null
    $archive = $null
    try {
        $stream = [IO.File]::Open($temporaryArchive, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
        $archive = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create, $true)
        $records = @()
        foreach ($relativePath in @($ExpectedSnapshot.Keys)) {
            $sourcePath = Join-Path $SourceDirectory ($relativePath.Replace('/', [IO.Path]::DirectorySeparatorChar))
            $sourceInfo = [IO.FileInfo]::new($sourcePath)
            $entry = $archive.CreateEntry("batch/$relativePath", [IO.Compression.CompressionLevel]::NoCompression)
            $entryStream = $entry.Open()
            $sourceStream = $null
            try {
                $sourceStream = [IO.File]::Open($sourcePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
                $sourceStream.CopyTo($entryStream)
            }
            finally {
                if ($null -ne $sourceStream) {
                    $sourceStream.Dispose()
                }
                $entryStream.Dispose()
            }
            $records += [ordered]@{
                path = $relativePath
                sha256 = [string]$ExpectedSnapshot[$relativePath]
                length = [long]$sourceInfo.Length
            }
        }
        $manifest = [ordered]@{
            format = "VivhiteDeploymentRecovery/v1"
            files = $records
        } | ConvertTo-Json -Depth 6 -Compress
        $manifestEntry = $archive.CreateEntry("vivhite-recovery-manifest.json", [IO.Compression.CompressionLevel]::NoCompression)
        $manifestStream = $manifestEntry.Open()
        try {
            $bytes = [Text.UTF8Encoding]::new($false).GetBytes($manifest)
            $manifestStream.Write($bytes, 0, $bytes.Length)
        }
        finally {
            $manifestStream.Dispose()
        }
        $archive.Dispose()
        $archive = $null
        $stream.Dispose()
        $stream = $null
        [IO.File]::Move($temporaryArchive, $ArchivePath)
        $null = Assert-RecoveryArchive $ArchivePath $ExpectedSnapshot
        return $ArchivePath
    }
    finally {
        if ($null -ne $archive) {
            $archive.Dispose()
        }
        if ($null -ne $stream) {
            $stream.Dispose()
        }
        if ([IO.File]::Exists($temporaryArchive)) {
            [IO.File]::Delete($temporaryArchive)
        }
    }
}

function Remove-DirectoryIncrementally {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [switch]$InjectBackupCleanupFailure
    )

    $deletedFileCount = 0
    foreach ($file in Get-ChildItem -LiteralPath $Directory -File -Recurse -Force | Sort-Object FullName) {
        [IO.File]::Delete($file.FullName)
        $deletedFileCount++
        if ($InjectBackupCleanupFailure -and $deletedFileCount -eq 1) {
            Invoke-InjectedFailure "BackupCleanup"
        }
    }
    foreach ($child in Get-ChildItem -LiteralPath $Directory -Directory -Recurse -Force |
        Sort-Object { $_.FullName.Length } -Descending) {
        [IO.Directory]::Delete($child.FullName, $false)
    }
    [IO.Directory]::Delete($Directory, $false)
}

function Invoke-ProtectedDirectoryCleanup {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDirectory,
        [Parameter(Mandatory = $true)][string]$LiveParentDirectory,
        [Parameter(Mandatory = $true)][string]$LiveDirectoryName,
        [Parameter(Mandatory = $true)][string]$CleanupId,
        [Parameter(Mandatory = $true)]$ExpectedSnapshot,
        [switch]$InjectBackupCleanupFailure
    )

    $sourceParent = Get-NormalizedDirectoryPath ([IO.Path]::GetDirectoryName($SourceDirectory))
    if (-not [string]::Equals($sourceParent, $LiveParentDirectory, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to quarantine a directory outside the normalized live parent: $SourceDirectory"
    }
    $quarantineModRoot = Get-QuarantineModRoot $LiveParentDirectory $LiveDirectoryName
    [void][IO.Directory]::CreateDirectory($quarantineModRoot)
    $workDirectory = Join-Path $quarantineModRoot ("work.$CleanupId")
    $recoveryArchive = Join-Path $quarantineModRoot ("recovery.$CleanupId.zip")
    if ([IO.Directory]::Exists($workDirectory) -or [IO.File]::Exists($recoveryArchive)) {
        throw "Quarantine transaction '$CleanupId' already exists; refusing to overwrite recovery evidence."
    }

    [IO.Directory]::Move($SourceDirectory, $workDirectory)
    try {
        Assert-DirectorySnapshot $workDirectory $ExpectedSnapshot "The quarantined rollback batch"
        $null = New-VerifiedRecoveryArchive $workDirectory $recoveryArchive $ExpectedSnapshot
        Remove-DirectoryIncrementally $workDirectory -InjectBackupCleanupFailure:$InjectBackupCleanupFailure
        [IO.File]::Delete($recoveryArchive)
        if ([IO.Directory]::Exists($workDirectory) -or [IO.File]::Exists($recoveryArchive)) {
            throw "Protected cleanup did not remove all quarantine artifacts for '$CleanupId'."
        }
        if (@(Get-ChildItem -LiteralPath $quarantineModRoot -Force).Count -eq 0) {
            [IO.Directory]::Delete($quarantineModRoot, $false)
        }
    }
    catch {
        $archiveState = if ([IO.File]::Exists($recoveryArchive)) { "verified recovery archive retained at '$recoveryArchive'" } else { "full quarantine work directory retained at '$workDirectory'" }
        throw "Protected Vivhite cleanup failed for '$SourceDirectory'; $archiveState. $($_.Exception.Message)"
    }
}

function Invoke-QuarantineReconciliation {
    param(
        [Parameter(Mandatory = $true)][string]$LiveParentDirectory,
        [Parameter(Mandatory = $true)][string]$LiveDirectoryName,
        [Parameter(Mandatory = $true)][string[]]$RequiredNames
    )

    $quarantineModRoot = Get-QuarantineModRoot $LiveParentDirectory $LiveDirectoryName
    if (-not [IO.Directory]::Exists($quarantineModRoot)) {
        return
    }
    $entries = @(Get-ChildItem -LiteralPath $quarantineModRoot -Force)
    if ($entries.Count -eq 0) {
        [IO.Directory]::Delete($quarantineModRoot, $false)
        return
    }
    $states = @{}
    foreach ($entry in $entries) {
        $id = $null
        $kind = $null
        if ($entry.PSIsContainer -and $entry.Name -match '^work\.(?<id>[0-9a-fA-F]{32})$') {
            $id = $Matches.id.ToLowerInvariant()
            $kind = "work"
        }
        elseif (-not $entry.PSIsContainer -and $entry.Name -match '^recovery\.(?<id>[0-9a-fA-F]{32})\.zip$') {
            $id = $Matches.id.ToLowerInvariant()
            $kind = "archive"
        }
        else {
            throw "Unknown Vivhite quarantine artifact '$($entry.FullName)'; refusing to publish."
        }
        if (-not $states.ContainsKey($id)) {
            $states[$id] = @{}
        }
        if ($states[$id].ContainsKey($kind)) {
            throw "Duplicate Vivhite quarantine artifact for transaction '$id'."
        }
        $states[$id][$kind] = $entry.FullName
    }
    if ($states.Count -ne 1) {
        throw "Ambiguous Vivhite quarantine state contains $($states.Count) transactions; refusing to publish."
    }

    $cleanupId = @($states.Keys)[0]
    $state = $states[$cleanupId]
    $workDirectory = if ($state.ContainsKey("work")) { [string]$state["work"] } else { "" }
    $recoveryArchive = if ($state.ContainsKey("archive")) { [string]$state["archive"] } else { "" }
    if (-not [string]::IsNullOrWhiteSpace($recoveryArchive)) {
        $null = Assert-RecoveryArchive $recoveryArchive
    }
    elseif (-not [string]::IsNullOrWhiteSpace($workDirectory)) {
        $snapshot = Get-RequiredBatchSnapshot $workDirectory $RequiredNames "The pending quarantine batch"
        $recoveryArchive = Join-Path $quarantineModRoot ("recovery.$cleanupId.zip")
        $null = New-VerifiedRecoveryArchive $workDirectory $recoveryArchive $snapshot
    }
    else {
        throw "Vivhite quarantine transaction '$cleanupId' has no recoverable content."
    }

    if (-not [string]::IsNullOrWhiteSpace($workDirectory) -and [IO.Directory]::Exists($workDirectory)) {
        Remove-DirectoryIncrementally $workDirectory
    }
    [IO.File]::Delete($recoveryArchive)
    if ([IO.Directory]::Exists($workDirectory) -or [IO.File]::Exists($recoveryArchive)) {
        throw "Vivhite quarantine transaction '$cleanupId' could not be fully reconciled."
    }
    [IO.Directory]::Delete($quarantineModRoot, $false)
}

function Invoke-HistoricalResidueReconciliation {
    param(
        [Parameter(Mandatory = $true)][string]$LiveDirectory,
        [Parameter(Mandatory = $true)][string]$LiveParentDirectory,
        [Parameter(Mandatory = $true)][string]$LiveDirectoryName,
        [Parameter(Mandatory = $true)][string[]]$RequiredNames
    )

    $residues = @(Get-OwnedTransactionResidues $LiveParentDirectory $LiveDirectoryName)
    $liveExists = [IO.Directory]::Exists($LiveDirectory)
    if ($liveExists) {
        $null = Get-RequiredBatchSnapshot $LiveDirectory $RequiredNames "The existing live Vivhite batch"
        if ($residues.Count -gt 1) {
            throw "Ambiguous Vivhite transaction history: live is present with $($residues.Count) owned residues."
        }
        if ($residues.Count -eq 1) {
            $residue = $residues[0]
            $exact = -not [string]::Equals($residue.Kind, "previous", [StringComparison]::OrdinalIgnoreCase)
            $snapshot = Get-RequiredBatchSnapshot $residue.Path $RequiredNames "Historical $($residue.Kind) residue '$($residue.Name)'" -RequireExactTriplet:$exact
            $cleanupId = [Guid]::NewGuid().ToString("N")
            Invoke-ProtectedDirectoryCleanup $residue.Path $LiveParentDirectory $LiveDirectoryName $cleanupId $snapshot
            Write-Host "[vivhite-deploy] Safely reconciled complete historical residue '$($residue.Name)'."
        }
        return
    }

    if ($residues.Count -eq 0) {
        return
    }
    if ($residues.Count -ne 1) {
        throw "Cannot recover missing live Vivhite batch from $($residues.Count) ambiguous owned residues."
    }
    $previous = $residues[0]
    if (-not [string]::Equals($previous.Kind, "previous", [StringComparison]::OrdinalIgnoreCase)) {
        throw "Live Vivhite batch is missing, but the only residue is '$($previous.Kind)' rather than a previous batch."
    }
    $snapshot = Get-RequiredBatchSnapshot $previous.Path $RequiredNames "The sole previous Vivhite batch"
    [IO.Directory]::Move($previous.Path, $LiveDirectory)
    Assert-DirectorySnapshot $LiveDirectory $snapshot "The recovered live Vivhite batch"
    Write-Host "[vivhite-deploy] Recovered the unique complete previous batch before publishing."
}

$godotPath = [IO.Path]::GetFullPath($GodotExe)
$projectPath = Get-NormalizedDirectoryPath $ProjectDir
$outputFullPath = [IO.Path]::GetFullPath($OutputPath)
$validatorFullPath = [IO.Path]::GetFullPath($ValidatorPath)
$assemblyFullPath = [IO.Path]::GetFullPath($AssemblyPath)
$manifestFullPath = [IO.Path]::GetFullPath($ManifestPath)
$liveDirectory = Get-NormalizedDirectoryPath $ModOutputDir
$candidateDirectory = Get-NormalizedDirectoryPath ([IO.Path]::GetDirectoryName($outputFullPath))
$liveParentDirectory = [IO.Path]::GetDirectoryName($liveDirectory)
$liveDirectoryName = [IO.Path]::GetFileName($liveDirectory)

if (-not [IO.File]::Exists($godotPath)) {
    throw "Godot executable does not exist: $godotPath"
}
if (-not [IO.Directory]::Exists($projectPath)) {
    throw "Godot project directory does not exist: $projectPath"
}
if (-not [IO.File]::Exists($validatorFullPath)) {
    throw "PCK validator does not exist: $validatorFullPath"
}
if (-not [IO.File]::Exists($assemblyFullPath)) {
    throw "Compiled Vivhite assembly does not exist: $assemblyFullPath"
}
if (-not [IO.File]::Exists($manifestFullPath)) {
    throw "Vivhite source manifest does not exist: $manifestFullPath"
}
if ([string]::IsNullOrWhiteSpace($RitsuLibVersion)) {
    throw "RitsuLibVersion is required to produce the synchronized candidate manifest."
}
if ([string]::IsNullOrWhiteSpace($liveParentDirectory) -or [string]::IsNullOrWhiteSpace($liveDirectoryName)) {
    throw "ModOutputDir must name a non-root live Mod directory: $liveDirectory"
}
if ([IO.File]::Exists($liveDirectory)) {
    throw "The live Mod path is a file, not a directory: $liveDirectory"
}
if (Test-PathInsideDirectory $outputFullPath $liveDirectory) {
    throw "The PCK candidate must be produced outside the live Mod directory: $outputFullPath"
}
if ([IO.Directory]::Exists($candidateDirectory)) {
    throw "The deployment candidate directory must be fresh and transaction-specific: $candidateDirectory"
}

$modName = [IO.Path]::GetFileNameWithoutExtension($outputFullPath)
$candidateDllName = [IO.Path]::GetFileName($assemblyFullPath)
$candidateJsonName = [IO.Path]::GetFileName($manifestFullPath)
$candidatePckName = [IO.Path]::GetFileName($outputFullPath)
if (-not [string]::Equals([IO.Path]::GetFileNameWithoutExtension($candidateDllName), $modName, [StringComparison]::OrdinalIgnoreCase) -or
    -not [string]::Equals([IO.Path]::GetFileNameWithoutExtension($candidateJsonName), $modName, [StringComparison]::OrdinalIgnoreCase)) {
    throw "DLL, PCK, and JSON candidate names must share one Mod batch name."
}

if ([string]::IsNullOrWhiteSpace($PowerShellExe)) {
    $PowerShellExe = [Diagnostics.Process]::GetCurrentProcess().MainModule.FileName
}

$godotLaunchPath = $godotPath
$godotName = [IO.Path]::GetFileNameWithoutExtension($godotPath)
if (-not $godotName.EndsWith("_console", [StringComparison]::OrdinalIgnoreCase)) {
    $consoleCandidate = Join-Path ([IO.Path]::GetDirectoryName($godotPath)) ($godotName + "_console.exe")
    if ([IO.File]::Exists($consoleCandidate)) {
        $godotLaunchPath = $consoleCandidate
    }
}

if ([string]::IsNullOrWhiteSpace($DotnetRoot)) {
    $DotnetRoot = $env:DOTNET_ROOT
}
if ([string]::IsNullOrWhiteSpace($DotnetRoot)) {
    $dotnetCommand = Get-Command dotnet.exe -ErrorAction SilentlyContinue
    if ($null -ne $dotnetCommand) {
        $DotnetRoot = Split-Path -Parent $dotnetCommand.Source
    }
}
if (-not [string]::IsNullOrWhiteSpace($DotnetRoot)) {
    $resolvedDotnetRoot = [IO.Path]::GetFullPath($DotnetRoot).TrimEnd('\', '/')
    $env:DOTNET_ROOT = $resolvedDotnetRoot
    $env:DOTNET_ROOT_X64 = $resolvedDotnetRoot
    $pathPrefix = $resolvedDotnetRoot + [IO.Path]::PathSeparator
    if (-not $env:PATH.StartsWith($pathPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        $env:PATH = $pathPrefix + $env:PATH
    }
}

# Nested builds launched by Godot must never recurse into this deployment transaction.
$env:STS2_SKIP_PCK_EXPORT = "1"
$env:CopyModOnBuild = "false"

$transactionId = [Guid]::NewGuid().ToString("N")
$temporaryPckPath = Join-Path $candidateDirectory ("{0}.export.{1}.pck" -f $modName, $transactionId)
$candidateDllPath = Join-Path $candidateDirectory $candidateDllName
$candidateJsonPath = Join-Path $candidateDirectory $candidateJsonName
$siblingStagingDirectory = Join-Path $liveParentDirectory (".{0}.staging.{1}" -f $liveDirectoryName, $transactionId)
$backupDirectory = Join-Path $liveParentDirectory (".{0}.previous.{1}" -f $liveDirectoryName, $transactionId)
$failedDirectory = Join-Path $liveParentDirectory (".{0}.failed.{1}" -f $liveDirectoryName, $transactionId)
$requiredBatchNames = @($candidateDllName, $candidatePckName, $candidateJsonName)
$deploymentLock = $null

try {
    if (-not [IO.Directory]::Exists($liveParentDirectory)) {
        [void][IO.Directory]::CreateDirectory($liveParentDirectory)
    }
    $lockPath = Join-Path $liveParentDirectory (".{0}.deploy.lock" -f $liveDirectoryName)
    $deploymentLock = Enter-DeploymentLock $lockPath $liveDirectory $LockTimeoutSeconds
    Write-Host "[vivhite-deploy] Acquired normalized deployment lock: $liveDirectory"

    $quarantineModRoot = Get-QuarantineModRoot $liveParentDirectory $liveDirectoryName
    if (-not [IO.Directory]::Exists($liveDirectory) -and [IO.Directory]::Exists($quarantineModRoot)) {
        throw "Live Vivhite batch is missing while rollback quarantine exists at '$quarantineModRoot'; refusing an ambiguous recovery."
    }
    Invoke-QuarantineReconciliation $liveParentDirectory $liveDirectoryName $requiredBatchNames
    Invoke-HistoricalResidueReconciliation $liveDirectory $liveParentDirectory $liveDirectoryName $requiredBatchNames

    $liveExisted = [IO.Directory]::Exists($liveDirectory)
    $liveSnapshot = Get-DirectorySnapshot $liveDirectory
    $switchStarted = $false
    $backupCreated = $false
    $stagePromoted = $false
    $committed = $false
    $rollbackFailed = $false

    try {
    [void][IO.Directory]::CreateDirectory($candidateDirectory)
    $exportStartedUtc = [DateTime]::UtcNow

    Invoke-InjectedFailure "PckExport"
    Write-Host "[vivhite-deploy] Exporting non-live PCK candidate: $temporaryPckPath"
    & $godotLaunchPath --headless --path $projectPath --export-pack $Preset $temporaryPckPath
    if ($LASTEXITCODE -ne 0) {
        throw "Godot PCK export exited with code $LASTEXITCODE."
    }

    $stagedPck = [IO.FileInfo]::new($temporaryPckPath)
    $stagedPck.Refresh()
    if (-not $stagedPck.Exists -or $stagedPck.Length -le 0) {
        throw "Godot did not create a non-empty staging PCK: $temporaryPckPath"
    }
    if ($stagedPck.LastWriteTimeUtc -lt $exportStartedUtc.AddSeconds(-2)) {
        throw "The staging PCK is not fresh: $temporaryPckPath"
    }

    Invoke-InjectedFailure "PckValidation"
    Write-Host "[vivhite-deploy] Validating the non-live PCK candidate."
    & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $validatorFullPath -ProjectDir $projectPath -Phase Pck -PckPath $temporaryPckPath -RuntimeLayout $IroncladSkinRuntimeLayout
    if ($LASTEXITCODE -ne 0) {
        throw "PCK validation exited with code $LASTEXITCODE."
    }
    [IO.File]::Move($temporaryPckPath, $outputFullPath)

    Invoke-InjectedFailure "ManifestSync"
    $manifestText = [IO.File]::ReadAllText($manifestFullPath)
    $versionPattern = '(?s)"id"\s*:\s*"STS2-RitsuLib".*?"version"\s*:\s*"(?<version>[^"]+)"'
    $versionMatches = [Text.RegularExpressions.Regex]::Matches($manifestText, $versionPattern)
    if ($versionMatches.Count -ne 1) {
        throw "Expected exactly one dependencies[STS2-RitsuLib].version entry in '$manifestFullPath'; found $($versionMatches.Count)."
    }
    $versionGroup = $versionMatches[0].Groups["version"]
    $candidateManifest = $manifestText.Substring(0, $versionGroup.Index) +
        $RitsuLibVersion +
        $manifestText.Substring($versionGroup.Index + $versionGroup.Length)
    try {
        $null = $candidateManifest | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "The synchronized candidate manifest is invalid JSON: $($_.Exception.Message)"
    }

    Invoke-InjectedFailure "CandidateJson"
    [IO.File]::WriteAllText($candidateJsonPath, $candidateManifest, [Text.UTF8Encoding]::new($false))
    Invoke-InjectedFailure "CandidateDll"
    [IO.File]::Copy($assemblyFullPath, $candidateDllPath, $false)

    Invoke-InjectedFailure "CandidateVerification"
    $candidateHashes = @{
        $candidatePckName = Get-FileDigest $outputFullPath
        $candidateDllName = Get-FileDigest $candidateDllPath
        $candidateJsonName = Get-FileDigest $candidateJsonPath
    }
    Assert-ExactTriplet $candidateDirectory $candidateHashes "The non-live deployment candidate"

    Invoke-InjectedFailure "SiblingCreate"
    [void][IO.Directory]::CreateDirectory($siblingStagingDirectory)

    Invoke-InjectedFailure "SiblingPck"
    [IO.File]::Copy($outputFullPath, (Join-Path $siblingStagingDirectory $candidatePckName), $false)
    Invoke-InjectedFailure "SiblingDll"
    [IO.File]::Copy($candidateDllPath, (Join-Path $siblingStagingDirectory $candidateDllName), $false)
    Invoke-InjectedFailure "SiblingJson"
    [IO.File]::Copy($candidateJsonPath, (Join-Path $siblingStagingDirectory $candidateJsonName), $false)

    Invoke-InjectedFailure "SiblingVerification"
    Assert-ExactTriplet $siblingStagingDirectory $candidateHashes "The same-volume sibling staging batch"
    Invoke-InjectedFailure "BeforeSwitch"

    $switchStarted = $true
    if ($liveExisted) {
        [IO.Directory]::Move($liveDirectory, $backupDirectory)
        $backupCreated = $true
    }
    Invoke-InjectedFailure "AfterLiveBackup"

    [IO.Directory]::Move($siblingStagingDirectory, $liveDirectory)
    $stagePromoted = $true
    Invoke-InjectedFailure "AfterStagePromotion"

    Assert-ExactTriplet $liveDirectory $candidateHashes "The promoted live Vivhite batch"
    Invoke-InjectedFailure "LiveVerification"

    # From this point onward B is a complete committed batch. A is moved outside the
    # Mod scanner and archived before any item is deleted. A cleanup fault therefore
    # returns non-zero without ever treating a half-deleted directory as success.
    $committed = $true
    if ($backupCreated) {
        $backupSnapshot = Get-DirectorySnapshot $backupDirectory
        Assert-DirectorySnapshot $backupDirectory $liveSnapshot "The complete previous batch before protected cleanup"
        $backupCreated = $false
        Invoke-ProtectedDirectoryCleanup `
            $backupDirectory `
            $liveParentDirectory `
            $liveDirectoryName `
            $transactionId `
            $backupSnapshot `
            -InjectBackupCleanupFailure
    }
    Write-Host "[vivhite-deploy] Committed one directory batch: $liveDirectory"
    }
    catch {
    $primaryFailure = $_
    if (-not $committed -and $switchStarted) {
        try {
            if ($stagePromoted -and [IO.Directory]::Exists($liveDirectory)) {
                [IO.Directory]::Move($liveDirectory, $failedDirectory)
                $stagePromoted = $false
            }
            if ($backupCreated -and [IO.Directory]::Exists($backupDirectory)) {
                if ([IO.Directory]::Exists($liveDirectory)) {
                    throw "Cannot restore the previous batch because the live path is occupied: $liveDirectory"
                }
                [IO.Directory]::Move($backupDirectory, $liveDirectory)
                $backupCreated = $false
            }
            elseif ($liveExisted -and -not [IO.Directory]::Exists($liveDirectory)) {
                throw "The previous live batch is unavailable for rollback."
            }
            if ([IO.Directory]::Exists($failedDirectory)) {
                Remove-OwnedDirectory $failedDirectory
            }
            if ($liveExisted) {
                Assert-DirectorySnapshot $liveDirectory $liveSnapshot "The rolled-back live Vivhite batch"
            }
            elseif ([IO.Directory]::Exists($liveDirectory)) {
                throw "Rollback should have restored the original absence of the live directory."
            }
        }
        catch {
            $rollbackFailed = $true
            throw "Vivhite deployment failed at '$FailurePoint' and rollback also failed. Primary: $($primaryFailure.Exception.Message) Rollback: $($_.Exception.Message)"
        }
    }
    throw $primaryFailure
    }
    finally {
    if ([IO.File]::Exists($temporaryPckPath)) {
        [IO.File]::Delete($temporaryPckPath)
    }
    if ([IO.Directory]::Exists($candidateDirectory)) {
        Remove-OwnedDirectory $candidateDirectory
    }
    if ([IO.Directory]::Exists($siblingStagingDirectory)) {
        Remove-OwnedDirectory $siblingStagingDirectory
    }
    if (-not $rollbackFailed -and [IO.Directory]::Exists($failedDirectory)) {
        Remove-OwnedDirectory $failedDirectory
    }
        # A committed cleanup failure deliberately leaves either one complete previous
        # sibling or a verified out-of-scanner recovery archive for the next locked run.
    }
}
finally {
    if ($null -ne $deploymentLock) {
        $deploymentLock.Dispose()
        Write-Host "[vivhite-deploy] Released normalized deployment lock: $liveDirectory"
    }
}
