[CmdletBinding()]
param(
    [string]$GodotExe,
    [string]$ProjectDirectory,
    [string]$OutputDirectory,
    [string]$GameplayBackground = 'C:\Users\xenoa\AppData\Local\Temp\paseo-attachments-iYpx7L\89710a694def22a6e28e7875791f261f33921d9cc8bc89b45d27b64f53b77f5f.png'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..\..'))
if ([string]::IsNullOrWhiteSpace($ProjectDirectory)) {
    $ProjectDirectory = Join-Path $repositoryRoot 'Vivhite'
}
$ProjectDirectory = [System.IO.Path]::GetFullPath($ProjectDirectory)
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $stamp = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss')
    $OutputDirectory = Join-Path $repositoryRoot ".work\multiplayer-ui-acceptance\vulkan-$stamp"
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)

$localProps = Join-Path $ProjectDirectory 'local.props'
if ([string]::IsNullOrWhiteSpace($GodotExe) -and (Test-Path -LiteralPath $localProps -PathType Leaf)) {
    [xml]$props = [System.IO.File]::ReadAllText($localProps)
    $GodotExe = [string](@($props.Project.PropertyGroup) | Select-Object -First 1).GodotExe
}
if ([string]::IsNullOrWhiteSpace($GodotExe) -or -not (Test-Path -LiteralPath $GodotExe -PathType Leaf)) {
    throw "Godot 4.5.1 executable is missing: $GodotExe"
}
if (-not (Test-Path -LiteralPath $GameplayBackground -PathType Leaf)) {
    throw "Actual gameplay screenshot is missing: $GameplayBackground"
}
[System.IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
if (@(Get-ChildItem -LiteralPath $OutputDirectory -Force).Count -gt 0) {
    throw "OutputDirectory must be new or empty to prevent a stale report from passing: $OutputDirectory"
}

$projectHashBytes = [System.Text.Encoding]::UTF8.GetBytes($ProjectDirectory.ToLowerInvariant())
$sha256 = [System.Security.Cryptography.SHA256]::Create()
try {
    $projectHash = ([System.BitConverter]::ToString($sha256.ComputeHash($projectHashBytes))).Replace('-', '').Substring(0, 24)
}
finally {
    $sha256.Dispose()
}
$mutex = [System.Threading.Mutex]::new($false, "Local\VivhiteIroncladSpine-$projectHash")
$acquired = $false
try {
    try {
        $acquired = $mutex.WaitOne([TimeSpan]::FromMinutes(10))
    }
    catch [System.Threading.AbandonedMutexException] {
        $acquired = $true
    }
    if (-not $acquired) {
        throw 'Timed out waiting for exclusive offline Godot preview access.'
    }

    $script = Join-Path $PSScriptRoot 'render_multiplayer_gestures_actual.gd'
    $stdout = Join-Path $OutputDirectory 'render.stdout.log'
    $stderr = Join-Path $OutputDirectory 'render.stderr.log'
    $arguments = @(
        '--path', $ProjectDirectory,
        '--display-driver', 'windows',
        '--rendering-driver', 'vulkan',
        '--resolution', '64x64',
        '--position', '-32000,-32000',
        '--script', $script,
        '--',
        '--output', $OutputDirectory,
        '--gameplay-background', ([System.IO.Path]::GetFullPath($GameplayBackground))
    )
    $quoted = foreach ($argument in $arguments) {
        if ($argument -match '[\s"]') { '"' + $argument.Replace('"', '\"') + '"' } else { $argument }
    }
    $process = Start-Process -FilePath $GodotExe -ArgumentList ($quoted -join ' ') `
        -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -Wait -PassThru
    $process.Refresh()
    foreach ($path in @($stdout, $stderr)) {
        if (Test-Path -LiteralPath $path -PathType Leaf) {
            Get-Content -LiteralPath $path | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Write-Host
        }
    }
    if ($process.ExitCode -ne 0) {
        throw "Hidden Vulkan gesture renderer failed with exit code $($process.ExitCode)."
    }
    $reportPath = Join-Path $OutputDirectory 'report.json'
    if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
        throw "Renderer did not produce $reportPath"
    }
    $report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
    if ($report.success -ne $true -or $report.display_server -ne 'Windows' -or $report.rendering_driver -ne 'vulkan') {
        throw "Vulkan report did not pass: $reportPath"
    }
    Write-Host "[multiplayer-gesture-vulkan] PASS: $reportPath" -ForegroundColor Green
}
finally {
    if ($acquired) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
