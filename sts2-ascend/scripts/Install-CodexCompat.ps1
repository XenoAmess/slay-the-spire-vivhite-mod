[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$version = '0.148.0'
$expectedSha256 = '2AD2CF8A732DA68B8F141634F92DB1A03016C5FAF533A7225FBC0FB740130410'
$cacheBase = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'OpenAI\CodexCliCompat'))
$installRoot = [IO.Path]::GetFullPath((Join-Path $cacheBase $version))
if (-not $installRoot.StartsWith($cacheBase + [IO.Path]::DirectorySeparatorChar,
        [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing Codex compatibility install outside the user cache: $installRoot"
}
$binary = Join-Path $installRoot 'node_modules\@openai\codex-win32-x64\vendor\x86_64-pc-windows-msvc\bin\codex.exe'

function Test-CompatibleBinary {
    if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) { return $false }
    if ((Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash -ne $expectedSha256) {
        return $false
    }
    $reported = (& $binary --version 2>&1 | Out-String).Trim()
    return ($LASTEXITCODE -eq 0 -and $reported -eq "codex-cli $version")
}

if (-not (Test-CompatibleBinary)) {
    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null
    $npm = Get-Command npm.cmd -ErrorAction Stop
    & $npm.Source install --prefix $installRoot --no-save --package-lock=false "@openai/codex@$version"
    if ($LASTEXITCODE -ne 0) {
        throw "npm failed to install the pinned Codex compatibility CLI (exit=$LASTEXITCODE)"
    }
    if (-not (Test-CompatibleBinary)) {
        throw "Pinned Codex CLI failed version/SHA256 validation: $binary"
    }
}

Write-Output $binary
