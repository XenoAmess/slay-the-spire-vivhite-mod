from __future__ import annotations

import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "sts2-ascend" / "scripts"
MODULE = SCRIPTS / "BilibiliLive.psm1"
INSTALL = SCRIPTS / "Install-BilibiliLiveBridge.ps1"
WORKER = SCRIPTS / "Invoke-BilibiliLiveBridge.ps1"
START = SCRIPTS / "Start-BilibiliLive.ps1"
STOP = SCRIPTS / "Stop-BilibiliLive.ps1"
SMOKE = SCRIPTS / "Test-BilibiliLive.ps1"
SKILL = ROOT / ".agents" / "skills" / "bilibili-live" / "SKILL.md"


def run_powershell(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


class BilibiliLiveScriptTests(unittest.TestCase):
    def test_powershell_files_parse_under_windows_powershell(self) -> None:
        for path in (MODULE, INSTALL, WORKER, START, STOP, SMOKE):
            escaped = str(path).replace("'", "''")
            command = (
                "$tokens=$null;$errors=$null;"
                f"[Management.Automation.Language.Parser]::ParseFile('{escaped}',"
                "[ref]$tokens,[ref]$errors)|Out-Null;"
                "if($errors.Count){$errors|ForEach-Object{$_.Message};exit 1}"
            )
            result = run_powershell(command)
            self.assertEqual(result.returncode, 0, f"{path}: {result.stdout}\n{result.stderr}")

    def test_status_code_mapping(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "0,2,3,5,6,7,99|ForEach-Object{ConvertTo-LivehimeState $_}"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.split(),
            ["Idle", "Starting", "Starting", "Streaming", "Stopping", "Stopping", "Unknown"],
        )

    def test_whatif_paths_do_not_run_tasks_or_mutate(self) -> None:
        for script in (START, STOP, INSTALL):
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(script),
                    "-WhatIf",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("What if", result.stdout)

    def test_stop_script_cannot_stop_the_stack_or_processes(self) -> None:
        text = STOP.read_text(encoding="utf-8")
        for forbidden in ("Stop-Agent.ps1", "Stop-Process", "taskkill", ".runtime", "stop.request"):
            self.assertNotIn(forbidden, text)
        self.assertIn("Invoke-LivehimeBridge -Action Stop", text)

    def test_idle_stop_does_not_launch_livehime(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        self.assertIn('$state -in @(\"Idle\", \"NotRunning\")', text)
        self.assertIn('$Action -eq \"Stop\" -and $state -eq \"NotRunning\"', text)

    def test_smoke_always_has_immediate_livehime_cleanup(self) -> None:
        text = SMOKE.read_text(encoding="utf-8")
        self.assertIn("finally", text)
        self.assertIn("Invoke-LivehimeBridge -Action Stop", text)
        self.assertNotIn("Stop-Agent.ps1", text)
        self.assertNotIn("Stop-Process", text)

    def test_start_uses_unified_stack_before_livehime_and_topmost(self) -> None:
        text = START.read_text(encoding="utf-8")
        self.assertIn('Join-Path $PSScriptRoot "Start-Agent.ps1"', text)
        self.assertIn("-SkipDeploy", text)
        self.assertLess(text.index("& $startAgent"), text.index("Invoke-LivehimeBridge"))
        self.assertLess(text.index("Invoke-LivehimeBridge"), text.index("Set-SlayTheSpireTopMost"))

    def test_bridge_is_fixed_protected_and_current_user_only(self) -> None:
        installer = INSTALL.read_text(encoding="utf-8")
        worker = WORKER.read_text(encoding="utf-8")
        self.assertIn('"VivhiteBilibiliLiveBridge"', installer)
        self.assertIn('"\\Vivhite\\"', installer)
        self.assertIn("$identity.User.Value", installer)
        self.assertIn("-LogonType Interactive -RunLevel Highest", installer)
        self.assertIn('"BilibiliLive-$actionName"', installer)
        self.assertIn("$protectedWorker", installer)
        self.assertIn("Get-FileHash -Algorithm SHA256", installer)
        self.assertIn("Invoke-LivehimeStart", worker)
        self.assertIn("Invoke-LivehimeStop", worker)
        self.assertNotIn("Start-Agent.ps1", worker)

    def test_operational_path_has_no_web_api_or_obs_transport(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (MODULE, INSTALL, WORKER, START, STOP, SMOKE)
        ).lower()
        for forbidden in (
            "startlive",
            "stoplive",
            "api.live.bilibili.com",
            "bilibili_live_control.py",
            "obs64",
            "obs websocket",
        ):
            self.assertNotIn(forbidden, combined)

    def test_skill_preserves_start_and_stop_invariants(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("Start-BilibiliLive.ps1", text)
        self.assertIn("Stop-BilibiliLive.ps1", text)
        self.assertIn("TOPMOST", text)
        self.assertIn("Never substitute `Stop-Agent.ps1`", text)
        self.assertIn("Livehime GUI", text)


if __name__ == "__main__":
    unittest.main()
