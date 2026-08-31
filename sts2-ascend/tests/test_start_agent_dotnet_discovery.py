from __future__ import annotations

import pathlib
import re
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
START_AGENT = ROOT / "sts2-ascend" / "scripts" / "Start-Agent.ps1"


def function_source(name: str) -> str:
    source = START_AGENT.read_text(encoding="utf-8")
    match = re.search(
        rf"(?ms)^function {re.escape(name)} \{{.*?^\}}\r?$", source
    )
    if match is None:
        raise AssertionError(f"PowerShell function not found: {name}")
    return match.group(0)


def ps_literal(value: pathlib.Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_isolated_powershell(script: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="sts2-dotnet-discovery-script-") as root:
        path = pathlib.Path(root) / "check.ps1"
        path.write_text(script, encoding="utf-8-sig")
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )


class StartAgentDotnetDiscoveryTests(unittest.TestCase):
    def test_path_missing_uses_validated_localappdata_fallback(self) -> None:
        probe = function_source("Test-DotnetSdkAvailable")
        initialize = function_source("Initialize-DotnetSdkEnvironment")

        self.assertIn("--list-sdks", probe)
        self.assertIn("$dotnetExit -ne 0", probe)
        self.assertIn(r"^\d+\.\d+\.\d+[^\s]*\s+\[[^\]]+\]$", probe)
        self.assertIn(
            'Join-Path $env:LOCALAPPDATA "Microsoft\\dotnet\\dotnet.exe"',
            initialize,
        )
        fallback = initialize.index("$env:LOCALAPPDATA")
        validation = initialize.index("Test-DotnetSdkAvailable $candidate")
        set_root = initialize.index("$env:DOTNET_ROOT = $candidateRoot")
        set_path = initialize.index(
            "$env:PATH = (@($candidateRoot) + $remainingPath) -join ';'"
        )
        self.assertLess(fallback, validation)
        self.assertLess(validation, set_root)
        self.assertLess(set_root, set_path)
        self.assertNotRegex(initialize, r"(?i)[A-Z]:\\Users\\[^\\]+")

    def test_working_path_dotnet_returns_before_environment_mutation(self) -> None:
        initialize = function_source("Initialize-DotnetSdkEnvironment")
        path_branch = initialize.index("$pathDotnet -and")
        path_return = initialize.index("return [IO.Path]::GetFullPath($pathDotnet.Source)")
        first_environment_write = initialize.index("$env:DOTNET_ROOT = $candidateRoot")

        self.assertLess(path_branch, path_return)
        self.assertLess(path_return, first_environment_write)
        self.assertNotIn("$env:DOTNET_ROOT =", initialize[:path_return])
        self.assertNotIn("$env:PATH =", initialize[:path_return])

    def test_fallback_moves_existing_candidate_ahead_of_bad_dotnet(self) -> None:
        initialize = function_source("Initialize-DotnetSdkEnvironment")
        with tempfile.TemporaryDirectory(prefix="sts2-dotnet-path-") as root:
            root_path = pathlib.Path(root)
            bad_root = root_path / "bad-runtime"
            local_app_data = root_path / "local-app-data"
            candidate_root = local_app_data / "Microsoft" / "dotnet"
            bad_root.mkdir()
            candidate_root.mkdir(parents=True)
            (bad_root / "dotnet.exe").write_bytes(b"")
            candidate_exe = candidate_root / "dotnet.exe"
            candidate_exe.write_bytes(b"")

            script = f"""
$ErrorActionPreference = 'Stop'
function Test-DotnetSdkAvailable {{
    param([string]$DotnetExe)
    return [string]::Equals(
        [IO.Path]::GetFullPath($DotnetExe),
        [IO.Path]::GetFullPath({ps_literal(candidate_exe)}),
        [StringComparison]::OrdinalIgnoreCase)
}}
{initialize}
$env:DOTNET_ROOT = $null
$env:LOCALAPPDATA = {ps_literal(local_app_data)}
$env:PATH = {ps_literal(f'{bad_root};{candidate_root};{candidate_root}')}
$selected = Initialize-DotnetSdkEnvironment
$parts = @($env:PATH -split ';')
if (-not [string]::Equals($parts[0], {ps_literal(candidate_root)},
                         [StringComparison]::OrdinalIgnoreCase)) {{ exit 11 }}
$candidateCount = @($parts | Where-Object {{
    [string]::Equals([IO.Path]::GetFullPath($_),
                     [IO.Path]::GetFullPath({ps_literal(candidate_root)}),
                     [StringComparison]::OrdinalIgnoreCase)
}}).Count
if ($candidateCount -ne 1) {{ exit 12 }}
$bareDotnet = Get-Command dotnet.exe -CommandType Application | Select-Object -First 1
if (-not [string]::Equals([IO.Path]::GetFullPath($bareDotnet.Source),
                         [IO.Path]::GetFullPath({ps_literal(candidate_exe)}),
                         [StringComparison]::OrdinalIgnoreCase)) {{ exit 13 }}
"""
            result = run_isolated_powershell(script)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_candidates_without_sdks_fail_with_existing_error_semantics(self) -> None:
        initialize = function_source("Initialize-DotnetSdkEnvironment")
        failed_probe = initialize.index("-not (Test-DotnetSdkAvailable $candidate)")
        continue_candidate = initialize.index("continue", failed_probe)
        failure = initialize.index(
            "It was not possible to find any installed .NET SDKs"
        )

        self.assertLess(failed_probe, continue_candidate)
        self.assertLess(continue_candidate, failure)
        self.assertIn("local fork deployment", initialize[failure:])

    def test_sdk_discovery_only_guards_local_fork_deployment(self) -> None:
        source = START_AGENT.read_text(encoding="utf-8")
        deploy_block = source.index("if (-not $SkipDeploy)")
        uses_fork = source.index('$usesLocalFork = ($Source -eq "fork")', deploy_block)
        initialize = source.index(
            "Initialize-DotnetSdkEnvironment | Out-Null", uses_fork
        )
        deploy = source.index(
            '& (Join-Path $PSScriptRoot "Deploy-Mod.ps1")', initialize
        )

        self.assertLess(deploy_block, uses_fork)
        self.assertLess(uses_fork, initialize)
        self.assertLess(initialize, deploy)
        self.assertIn('$Source -eq "auto"', source[uses_fork:initialize])
        self.assertIn("third_party\\STS2-Agent\\.git", source[uses_fork:initialize])


if __name__ == "__main__":
    unittest.main()
