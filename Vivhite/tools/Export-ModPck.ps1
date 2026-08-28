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

    [string]$IroncladSkinRuntimeLayout = "legacy-single-page",

    [string]$PowerShellExe = "",

    [string]$DotnetRoot = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$godotPath = [IO.Path]::GetFullPath($GodotExe)
$projectPath = [IO.Path]::GetFullPath($ProjectDir)
$outputFullPath = [IO.Path]::GetFullPath($OutputPath)
$validatorFullPath = [IO.Path]::GetFullPath($ValidatorPath)

if (-not [IO.File]::Exists($godotPath)) {
    throw "Godot executable does not exist: $godotPath"
}
if (-not [IO.Directory]::Exists($projectPath)) {
    throw "Godot project directory does not exist: $projectPath"
}
if (-not [IO.File]::Exists($validatorFullPath)) {
    throw "PCK validator does not exist: $validatorFullPath"
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

$env:STS2_SKIP_PCK_EXPORT = "1"
$env:CopyModOnBuild = "false"

$outputDirectory = [IO.Path]::GetDirectoryName($outputFullPath)
[void][IO.Directory]::CreateDirectory($outputDirectory)

do {
    $transactionId = [Guid]::NewGuid().ToString("N")
    $temporaryName = "{0}.staging.{1}.pck" -f [IO.Path]::GetFileNameWithoutExtension($outputFullPath), $transactionId
    $temporaryPckPath = [IO.Path]::GetFullPath((Join-Path $outputDirectory $temporaryName))
    $backupPath = [IO.Path]::GetFullPath((Join-Path $outputDirectory ("{0}.previous.{1}" -f [IO.Path]::GetFileName($outputFullPath), $transactionId)))
} while ([IO.File]::Exists($temporaryPckPath) -or [IO.File]::Exists($backupPath))

$exportStartedUtc = [DateTime]::UtcNow

try {
    Write-Host "[pck-export] Exporting a fresh staging pack: $temporaryPckPath"
    & $godotLaunchPath --headless --path $projectPath --export-pack $Preset $temporaryPckPath
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Godot PCK export exited with code $exitCode."
    }

    $stagedPck = [IO.FileInfo]::new($temporaryPckPath)
    $stagedPck.Refresh()
    if (-not $stagedPck.Exists) {
        throw "Godot reported success but did not create the staging PCK: $temporaryPckPath"
    }
    if ($stagedPck.Length -le 0) {
        throw "Godot created an empty staging PCK: $temporaryPckPath"
    }
    if ($stagedPck.LastWriteTimeUtc -lt $exportStartedUtc.AddSeconds(-2)) {
        throw "The staging PCK is not fresh (last write $($stagedPck.LastWriteTimeUtc.ToString('O')), export started $($exportStartedUtc.ToString('O'))): $temporaryPckPath"
    }

    Write-Host "[pck-export] Validating staging pack before deployment."
    & $PowerShellExe -NoProfile -ExecutionPolicy Bypass -File $validatorFullPath -ProjectDir $projectPath -Phase Pck -PckPath $temporaryPckPath -RuntimeLayout $IroncladSkinRuntimeLayout
    $validatorExitCode = $LASTEXITCODE
    if ($validatorExitCode -ne 0) {
        throw "PCK validation exited with code $validatorExitCode."
    }

    if ([IO.File]::Exists($outputFullPath)) {
        try {
            [IO.File]::Replace($temporaryPckPath, $outputFullPath, $backupPath)
        }
        catch {
            if (-not [IO.File]::Exists($outputFullPath) -and [IO.File]::Exists($backupPath)) {
                [IO.File]::Move($backupPath, $outputFullPath)
            }
            throw
        }
    }
    else {
        [IO.File]::Move($temporaryPckPath, $outputFullPath)
    }

    Write-Host "[pck-export] Validated PCK installed atomically: $outputFullPath"
}
finally {
    if ([IO.File]::Exists($temporaryPckPath)) {
        [IO.File]::Delete($temporaryPckPath)
    }
    if ([IO.File]::Exists($backupPath) -and [IO.File]::Exists($outputFullPath)) {
        try {
            [IO.File]::Delete($backupPath)
        }
        catch {
            Write-Warning "Unable to remove the previous-PCK backup '$backupPath': $($_.Exception.Message)"
        }
    }
}
