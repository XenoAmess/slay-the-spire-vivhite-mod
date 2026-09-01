from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
START_AGENT = ROOT / "sts2-ascend" / "scripts" / "Start-Agent.ps1"


def function_source(name: str) -> str:
    source = START_AGENT.read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^function {re.escape(name)} \{{.*?^\}}\r?$", source)
    if match is None:
        raise AssertionError(f"PowerShell function not found: {name}")
    return match.group(0)


def source_between(start: str, end: str) -> str:
    source = START_AGENT.read_text(encoding="utf-8")
    begin = source.index(start)
    finish = source.index(end, begin)
    return source[begin:finish]


def run_powershell(script: str, *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="sts2-python-preflight-") as root:
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
            timeout=timeout,
            check=False,
        )


class StartAgentPythonPreflightTests(unittest.TestCase):
    def test_probe_is_stdlib_bound_and_runtime_fails_closed(self) -> None:
        source = START_AGENT.read_text(encoding="utf-8")
        probe = source_between(
            "function Invoke-PythonRuntimeProbe", "function Test-PythonPathWithin"
        )
        runtime = source_between("function Get-PythonRuntime", "function Get-PythonExe")

        for module in ("encodings", "json", "pathlib", "sysconfig"):
            self.assertIn(f"import {module}", probe)
        self.assertIn("PYTHONHOME", probe)
        self.assertIn("PYTHONPATH", probe)
        self.assertIn("ToBase64String", probe)
        self.assertIn("Test-PythonPathWithin", runtime)
        self.assertIn("No complete Python 3.10+ runtime was found", runtime)
        self.assertIn("refusing to start runner/brain", runtime)
        self.assertNotRegex(source, r"(?i)[A-Z]:\\Users\\[^\\\"']+")

    def test_runtime_probe_restores_parent_environment(self) -> None:
        if shutil.which("powershell.exe") is None or shutil.which("py.exe") is None:
            self.skipTest("Windows Python launcher is unavailable")
        # The probe contains a nested Python here-string and nested PowerShell
        # blocks, so use the contiguous helper region instead of a regex that
        # would stop at its first closing brace.
        defs = source_between(
            "function Add-UniquePath", "function Get-PythonExe"
        )
        script = f"""
$ErrorActionPreference = 'Stop'
$oldHome = [Environment]::GetEnvironmentVariable('PYTHONHOME', 'Process')
$oldPath = [Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process')
[Environment]::SetEnvironmentVariable('PYTHONHOME', 'sentinel-home', 'Process')
[Environment]::SetEnvironmentVariable('PYTHONPATH', 'sentinel-path', 'Process')
{defs}
$runtime = Get-PythonRuntime
if (-not $runtime.Executable -or -not $runtime.Home -or -not $runtime.Stdlib) {{ exit 11 }}
if (-not (Test-Path -LiteralPath $runtime.Home -PathType Container)) {{ exit 12 }}
if (-not (Test-Path -LiteralPath $runtime.Stdlib -PathType Container)) {{ exit 13 }}
if ([Environment]::GetEnvironmentVariable('PYTHONHOME', 'Process') -ne 'sentinel-home') {{ exit 14 }}
if ([Environment]::GetEnvironmentVariable('PYTHONPATH', 'Process') -ne 'sentinel-path') {{ exit 15 }}
"""
        result = run_powershell(script, timeout=60.0)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_start_passes_resolved_home_to_runner_and_audits_it(self) -> None:
        source = START_AGENT.read_text(encoding="utf-8")
        resolve = source.index("$pythonRuntime = Get-PythonRuntime")
        launch = source.index("Start-Process -FilePath $pythonExe", resolve)
        env_home = source.index("$env:PYTHONHOME = $pythonHome", resolve)
        session_home = source.index("python_home = $pythonHome", resolve)
        self.assertLess(resolve, env_home)
        self.assertLess(env_home, launch)
        self.assertLess(env_home, session_home)
        self.assertIn("python_stdlib = $pythonStdlib", source)
        self.assertIn("python_runtime_source = [string]$pythonRuntime.Source", source)
        self.assertIn("Remove-Item Env:PYTHONPATH", source)


if __name__ == "__main__":
    unittest.main()
