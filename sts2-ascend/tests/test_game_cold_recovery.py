"""Session-preserving recovery with mocked Windows launch and disk probes."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT / "brain"))
import agent as agent_module
import lifecycle


def ps_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


class BrainGameRecoveryTests(unittest.TestCase):
    def instance(self, count: int | None):
        instance = object.__new__(agent_module.Agent)
        instance.client = SimpleNamespace(discover=mock.Mock(return_value=False))
        instance._game_process_count = mock.Mock(return_value=count)
        instance._wait_for_game_api = mock.Mock(return_value=False)
        return instance

    def test_existing_uncertain_and_duplicate_game_never_invoke_recovery(self):
        for count in (None, 1, 2):
            with self.subTest(count=count):
                instance = self.instance(count)
                with (mock.patch.object(agent_module, "stop_requested", return_value=False),
                      mock.patch.object(agent_module, "log"),
                      mock.patch.object(agent_module.subprocess, "run") as run,
                      mock.patch.object(agent_module.subprocess, "Popen") as popen):
                    self.assertFalse(instance.ensure_game())
                run.assert_not_called()
                popen.assert_not_called()
                instance._wait_for_game_api.assert_called_once()

    def test_zero_process_uses_game_only_tool_bound_to_current_session(self):
        instance = self.instance(0)
        result = SimpleNamespace(returncode=0, stdout='{"Launched":true}', stderr="")
        with (mock.patch.object(agent_module, "stop_requested", return_value=False),
              mock.patch.object(agent_module, "log"),
              mock.patch.object(lifecycle, "STACK_ROOT", Path("C:/fixture-stack")),
              mock.patch.object(lifecycle, "RUNTIME_DIR", Path("C:/fixture-runtime")),
              mock.patch.object(lifecycle, "SESSION_ID", "a" * 32),
              mock.patch.dict(os.environ, {"STS2_ASCEND_GAME_LAUNCHER": "wrong-launcher"}),
              mock.patch.object(agent_module.subprocess, "run", return_value=result) as run,
              mock.patch.object(agent_module.subprocess, "Popen") as popen):
            self.assertFalse(instance.ensure_game())
        command = run.call_args.args[0]
        self.assertTrue(command[command.index("-File") + 1].endswith("Invoke-GameRecovery.ps1"))
        self.assertEqual(command[command.index("-SessionId") + 1], "a" * 32)
        self.assertEqual(Path(command[command.index("-SessionFile") + 1]),
                         Path("C:/fixture-runtime/session.json"))
        self.assertNotIn("wrong-launcher", command)
        self.assertNotIn("Start-Agent.ps1", " ".join(command))
        popen.assert_not_called()

    def test_failed_or_timed_out_tool_has_no_direct_launch_fallback(self):
        for result in (SimpleNamespace(returncode=1, stdout="", stderr="low disk"),
                       subprocess.TimeoutExpired("powershell.exe", 30)):
            with self.subTest(result=type(result).__name__):
                instance = self.instance(0)
                with (mock.patch.object(agent_module, "stop_requested", return_value=False),
                      mock.patch.object(agent_module, "log") as log,
                      mock.patch.object(agent_module.subprocess, "run") as run,
                      mock.patch.object(agent_module.subprocess, "Popen") as popen):
                    if isinstance(result, Exception):
                        run.side_effect = result
                    else:
                        run.return_value = result
                    self.assertFalse(instance.ensure_game())
                log.assert_called()
                popen.assert_not_called()

    def test_probe_failure_or_timeout_is_uncertain(self):
        instance = self.instance(0)
        del instance._game_process_count
        for result in (SimpleNamespace(returncode=1, stdout=""),
                       subprocess.TimeoutExpired("tasklist", 10)):
            with self.subTest(result=type(result).__name__), mock.patch.object(
                    agent_module.subprocess, "run") as run:
                if isinstance(result, Exception):
                    run.side_effect = result
                else:
                    run.return_value = result
                self.assertIsNone(instance._game_process_count())


class PowerShellGameColdRecoveryTests(unittest.TestCase):
    def run_fixture(self, *, mode="auto", count=0, free=2 * 1024**3,
                    consent=False, applied=True, overrides=None, probe_error=False,
                    stop=False, require_cold_off=False, recovery=True, late_count=None,
                    stop_during_probe=False):
        with tempfile.TemporaryDirectory(prefix="sts2-game-recovery-") as directory:
            fixture = Path(directory)
            game = fixture / "game"
            game.mkdir()
            (game / "launch_vulkan.bat").write_text("@exit /b 99", encoding="ascii")
            (game / "SlayTheSpire2.exe").write_bytes(b"not an executable")
            steam = fixture / "Steam"
            (steam / "userdata").mkdir(parents=True)
            appdata = fixture / "AppData"
            if consent:
                settings = appdata / "SlayTheSpire2/default/1/settings.save"
                settings.parent.mkdir(parents=True)
                settings.write_text('{"mod_settings": {}}', encoding="utf-8")
            sentinel = fixture / "stop.request"
            if stop:
                sentinel.write_text("stop", encoding="utf-8")
            session = {
                "session_id": "a" * 32, "state": "running",
                "game_dir": str(game), "stop_file": str(sentinel),
                "steam_mode": mode, "steam_mode_applied": applied,
                "steam_launch_arguments": ["--force-steam", "off"] if mode == "off" else [],
                "steam_min_free_bytes": 1024**3,
            }
            session.update(overrides or {})
            session_path = fixture / "session.json"
            session_path.write_text(json.dumps(session), encoding="utf-8")
            before = session_path.read_bytes()
            # Execute the production recovery body against the production common
            # functions; acquisition and Start-Process are replaced with fixtures.
            body = (SCRIPTS / "Invoke-GameRecovery.ps1").read_text(encoding="utf-8-sig")
            body = body[body.index("$session = Get-Content"):]
            if not recovery:
                cold_flag = " -RequireColdOff" if require_cold_off else ""
                body = f"Invoke-AscendGameLaunch -GameDir {ps_literal(game)} -Mode {mode}{cold_flag} | Out-Null"
            games = "; ".join("[pscustomobject]@{ProcessId=" + str(i + 1) + "}" for i in range(count))
            probe = "throw 'CIM unavailable'" if probe_error else "return @(" + games + ")"
            if stop_during_probe:
                probe = f"[IO.File]::WriteAllText({ps_literal(sentinel)}, 'stop'); " + probe
            if late_count is not None:
                late_games = "; ".join("[pscustomobject]@{ProcessId=" + str(i + 1) + "}" for i in range(late_count))
                probe = ("$script:probeCalls++; if ($script:probeCalls -gt 1) { return @("
                         + late_games + ") }; " + probe)
            free_value = "$null" if free is None else f"[UInt64]{free}"
            script = f"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
. {ps_literal(SCRIPTS / 'GameColdStart.ps1')}
$env:APPDATA = {ps_literal(appdata)}
$SessionFile = {ps_literal(session_path)}
$SessionId = {'a' * 32!r}
$script:launches = @()
$script:probeCalls = 0
function Get-CimInstance {{ [CmdletBinding()]param([Parameter(Position=0)][string]$ClassName, [string]$Filter); {probe} }}
function Get-SteamInstallRoot {{ return {ps_literal(steam)} }}
function Get-AvailableFreeBytes {{ param([string]$Path); return {free_value} }}
function Start-Process {{
    param([string]$FilePath, [string]$WorkingDirectory, [string]$WindowStyle, [object[]]$ArgumentList)
    $launchArguments = @()
    if ($null -ne $ArgumentList) {{ $launchArguments = @($ArgumentList) }}
    $script:launches += ,@{{path=$FilePath;cwd=$WorkingDirectory;style=$WindowStyle;args=$launchArguments}}
}}
$errorText = ''
$outputs = @()
try {{ $outputs = @(& {{ {body} }}) }} catch {{ $errorText = $_.Exception.Message }}
@{{error=$errorText; launches=@($script:launches); outputs=@($outputs)}} | ConvertTo-Json -Depth 8 -Compress
"""
            check = fixture / "check.ps1"
            check.write_text(script, encoding="utf-8-sig")
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(check)],
                capture_output=True, text=True, cwd=ROOT, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(session_path.read_bytes(), before)
            return json.loads(result.stdout.strip().splitlines()[-1])

    def test_off_recovery_keeps_arguments_and_native_consent(self):
        result = self.run_fixture(mode="off", consent=True)
        self.assertEqual(result["error"], "")
        self.assertEqual(len(result["launches"]), 1)
        launch = result["launches"][0]
        self.assertEqual(launch["args"], ["--force-steam", "off"])
        self.assertEqual(launch["style"], "Hidden")
        self.assertTrue(launch["path"].endswith("launch_vulkan.bat"))
        status = json.loads(result["outputs"][0])
        self.assertFalse(status["DiskStatus"]["required"])

    def test_off_without_native_consent_never_launches(self):
        result = self.run_fixture(mode="off")
        self.assertIn("consent", result["error"])
        self.assertEqual(result["launches"], [])

    def test_auto_reused_session_with_applied_false_remains_valid(self):
        result = self.run_fixture(mode="auto", applied=False)
        self.assertEqual(result["error"], "")
        self.assertEqual(len(result["launches"]), 1)
        self.assertEqual(result["launches"][0]["args"], [])

    def test_on_keeps_defaults_and_session_disk_minimum_is_retained(self):
        result = self.run_fixture(mode="on")
        self.assertEqual(result["error"], "")
        self.assertEqual(result["launches"][0]["args"], [])
        result = self.run_fixture(overrides={"steam_min_free_bytes": 3 * 1024**3})
        self.assertIn("below", result["error"])
        self.assertEqual(result["launches"], [])

    def test_auto_and_on_low_or_unreadable_userdata_space_never_launch(self):
        for mode in ("auto", "on"):
            for free in (0, 1024**3 - 1, None):
                with self.subTest(mode=mode, free=free):
                    result = self.run_fixture(mode=mode, free=free)
                    self.assertNotEqual(result["error"], "")
                    self.assertEqual(result["launches"], [])

    def test_probe_failure_duplicates_stop_and_contract_mismatch_never_launch(self):
        cases = (
            ({"probe_error": True}, "CIM unavailable"),
            ({"count": 2}, "Multiple game instances"),
            ({"stop": True}, "stop was requested"),
            ({"stop_during_probe": True}, "stop was requested"),
            ({"overrides": {"session_id": "b" * 32}}, "no longer the running"),
            ({"overrides": {"state": "stopping"}}, "no longer the running"),
            ({"overrides": {"steam_launch_arguments": ["--force-steam", "off"]}}, "inconsistent"),
            ({"mode": "off", "consent": True, "applied": False}, "was not applied"),
            ({"overrides": {"steam_min_free_bytes": 0}}, "invalid Steam disk-space minimum"),
        )
        for case, error in cases:
            with self.subTest(case=case):
                result = self.run_fixture(**case)
                self.assertIn(error, result["error"])
                self.assertEqual(result["launches"], [])

    def test_game_appearing_before_recovery_does_not_change_mode(self):
        for mode in ("auto", "on", "off"):
            with self.subTest(mode=mode):
                result = self.run_fixture(mode=mode, count=1, free=0)
                self.assertEqual(result["error"], "")
                self.assertEqual(result["launches"], [])
                status = json.loads(result["outputs"][0])
                self.assertFalse(status["Launched"])
                self.assertFalse(status["DiskStatus"]["required"])

    def test_explicit_start_off_still_requires_cold_game(self):
        result = self.run_fixture(mode="off", count=1, recovery=False, require_cold_off=True)
        self.assertIn("cannot be switched retroactively", result["error"])
        self.assertEqual(result["launches"], [])

    def test_game_appearing_during_preflight_is_reused(self):
        result = self.run_fixture(late_count=1)
        self.assertEqual(result["error"], "")
        self.assertEqual(result["launches"], [])
        self.assertFalse(json.loads(result["outputs"][0])["Launched"])
        result = self.run_fixture(late_count=2)
        self.assertIn("Multiple game instances", result["error"])
        self.assertEqual(result["launches"], [])


if __name__ == "__main__":
    unittest.main()
