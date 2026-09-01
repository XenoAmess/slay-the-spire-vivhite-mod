"""Regression coverage for the Steam userdata-volume startup guard.

The production incident that motivated this check had a Steam userdata drive
with zero bytes available.  These tests exercise the PowerShell helper with
mocked drive readings, so they never inspect or mutate the real Steam client,
userdata, or runtime files.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
START_AGENT = ROOT / "sts2-ascend" / "scripts" / "Start-Agent.ps1"


def helper_source() -> str:
    source = START_AGENT.read_text(encoding="utf-8")
    start = source.index("function Get-SteamInstallRoot")
    end = source.index("function Get-GameLaunchArguments", start)
    return source[start:end]


def ps_literal(value: pathlib.Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="sts2-steam-disk-space-") as root:
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


def last_json(stdout: str) -> dict:
    return json.loads(stdout.strip().splitlines()[-1])


class StartAgentSteamDiskSpaceTests(unittest.TestCase):
    def test_parameter_and_session_diagnostics_are_explicit(self) -> None:
        source = START_AGENT.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"\[ValidateRange\(1048576,\s*1099511627776\)\]\[long\]\$SteamMinFreeBytes\s*=\s*1GB",
        )
        for field in (
            "steam_disk_required",
            "steam_disk_ready",
            "steam_min_free_bytes",
            "steam_free_bytes",
            "steam_userdata_root",
            "steam_userdata_drive",
            "steam_disk_reason",
        ):
            self.assertIn(field, source)

        status_call = source.index("$steamDiskStatus = Get-SteamDiskSpaceStatus")
        deploy = source.index("if (-not $SkipDeploy)", status_call)
        launch = source.index("Start-Process -FilePath $gameLauncher", status_call)
        self.assertLess(status_call, deploy)
        self.assertLess(status_call, launch)

    def test_zero_free_bytes_fails_closed_for_steam_on(self) -> None:
        functions = helper_source()
        with tempfile.TemporaryDirectory(prefix="sts2-steam-fixture-") as root:
            steam_root = pathlib.Path(root)
            (steam_root / "userdata").mkdir()
            result = run_powershell(
                f"""
$ErrorActionPreference = 'Stop'
{functions}
function Get-SteamInstallRoot {{ return {ps_literal(steam_root)} }}
function Get-AvailableFreeBytes {{ param([string]$Path); return [UInt64]0 }}
$probe = Get-SteamDiskSpaceStatus -Mode on -ColdLaunch $true -MinimumFreeBytes 1073741824
$probe | ConvertTo-Json -Depth 6 -Compress
"""
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            probe = last_json(result.stdout)
            self.assertTrue(probe["required"])
            self.assertFalse(probe["ready"])
            self.assertEqual(probe["free_bytes"], 0)
            self.assertEqual(probe["drive_root"], "C:\\")
            self.assertIn("below", probe["reason"])
            self.assertIn("cloud", probe["reason"])

    def test_sufficient_space_passes_and_records_userdata_volume(self) -> None:
        functions = helper_source()
        with tempfile.TemporaryDirectory(prefix="sts2-steam-fixture-") as root:
            steam_root = pathlib.Path(root)
            (steam_root / "userdata").mkdir()
            result = run_powershell(
                f"""
$ErrorActionPreference = 'Stop'
{functions}
function Get-SteamInstallRoot {{ return {ps_literal(steam_root)} }}
function Get-AvailableFreeBytes {{ param([string]$Path); return [UInt64]2147483648 }}
$probe = Get-SteamDiskSpaceStatus -Mode auto -ColdLaunch $true -MinimumFreeBytes 1073741824
$probe | ConvertTo-Json -Depth 6 -Compress
"""
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            probe = last_json(result.stdout)
            self.assertTrue(probe["required"])
            self.assertTrue(probe["ready"])
            self.assertEqual(probe["free_bytes"], 2147483648)
            self.assertTrue(probe["userdata_root"].lower().endswith("\\userdata"))
            self.assertEqual(probe["drive_root"], "C:\\")

    def test_registry_steam_executable_is_normalized_to_client_root(self) -> None:
        functions = helper_source()
        with tempfile.TemporaryDirectory(prefix="sts2-steam-fixture-") as root:
            steam_root = pathlib.Path(root) / "Steam"
            steam_root.mkdir()
            steam_exe = steam_root / "steam.exe"
            steam_exe.write_bytes(b"fixture")
            result = run_powershell(
                f"""
$ErrorActionPreference = 'Stop'
{functions}
function Get-ItemProperty {{ param([string]$LiteralPath); return [pscustomobject]@{{ SteamExe = {ps_literal(steam_exe)} }} }}
$env:STEAM_PATH = ''
$resolved = Get-SteamInstallRoot
$resolved
"""
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(
                pathlib.Path(result.stdout.strip().splitlines()[-1]).resolve(),
                steam_root.resolve(),
            )

    def test_missing_root_or_unreadable_space_fails_closed(self) -> None:
        functions = helper_source()
        result = run_powershell(
            f"""
$ErrorActionPreference = 'Stop'
{functions}
function Get-SteamInstallRoot {{ return $null }}
$missing = Get-SteamDiskSpaceStatus -Mode on -ColdLaunch $true -MinimumFreeBytes 1073741824
$missing | ConvertTo-Json -Depth 6 -Compress
"""
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        probe = last_json(result.stdout)
        self.assertTrue(probe["required"])
        self.assertFalse(probe["ready"])
        self.assertIn("could not be resolved", probe["reason"])

        with tempfile.TemporaryDirectory(prefix="sts2-steam-fixture-") as root:
            steam_root = pathlib.Path(root)
            (steam_root / "userdata").mkdir()
            result = run_powershell(
                f"""
$ErrorActionPreference = 'Stop'
{functions}
function Get-SteamInstallRoot {{ return {ps_literal(steam_root)} }}
function Get-AvailableFreeBytes {{ param([string]$Path); return $null }}
$probe = Get-SteamDiskSpaceStatus -Mode on -ColdLaunch $true -MinimumFreeBytes 1073741824
$probe | ConvertTo-Json -Depth 6 -Compress
"""
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            probe = last_json(result.stdout)
            self.assertFalse(probe["ready"])
            self.assertIn("could not be read", probe["reason"])

    def test_off_and_existing_game_skip_steam_probe(self) -> None:
        functions = helper_source()
        result = run_powershell(
            f"""
$ErrorActionPreference = 'Stop'
{functions}
function Get-SteamInstallRoot {{ throw 'Steam probe must not run' }}
$off = Get-SteamDiskSpaceStatus -Mode off -ColdLaunch $true -MinimumFreeBytes 1073741824
$running = Get-SteamDiskSpaceStatus -Mode on -ColdLaunch $false -MinimumFreeBytes 1073741824
($off.ready -and -not $off.required -and $running.ready -and -not $running.required) | Write-Output
"""
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1].lower(), "true")

    def test_helper_is_read_only_and_never_requests_uac_or_gui(self) -> None:
        source = helper_source()
        self.assertNotRegex(
            source,
            r"(?i)\b(?:Set-Content|Out-File|Add-Content|Copy-Item|Move-Item|Remove-Item|Start-Process|Invoke-MouseClick|UAC)\b",
        )
        gate = START_AGENT.read_text(encoding="utf-8")
        gate_start = gate.index("$steamDiskStatus = Get-SteamDiskSpaceStatus")
        gate_end = gate.index("if (-not $SkipDeploy)", gate_start)
        gate_block = gate[gate_start:gate_end]
        self.assertRegex(gate_block, r"(?i)delete files")
        self.assertRegex(gate_block, r"(?i)UAC")
        self.assertRegex(gate_block, r"(?i)GUI")


if __name__ == "__main__":
    unittest.main()
