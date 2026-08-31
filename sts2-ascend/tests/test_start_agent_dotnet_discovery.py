from __future__ import annotations

import pathlib
import re
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
        set_path = initialize.index("$env:PATH = if")
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
