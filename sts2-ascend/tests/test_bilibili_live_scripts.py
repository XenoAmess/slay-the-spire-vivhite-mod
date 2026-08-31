from __future__ import annotations

import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "sts2-ascend" / "scripts"
MODULE = SCRIPTS / "BilibiliLive.psm1"
INSTALL = SCRIPTS / "Install-BilibiliLiveBridge.ps1"
WORKER = SCRIPTS / "Invoke-BilibiliLiveBridge.ps1"
DAILY_STOP_WATCH = SCRIPTS / "Invoke-BilibiliLiveDailyStopWatch.ps1"
START = SCRIPTS / "Start-BilibiliLive.ps1"
STOP = SCRIPTS / "Stop-BilibiliLive.ps1"
SMOKE = SCRIPTS / "Test-BilibiliLive.ps1"
SKILL = ROOT / ".agents" / "skills" / "bilibili-live" / "SKILL.md"
PATROL = ROOT / "sts2-ascend" / "brain" / "broadcast_window_patrol.py"


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
        for path in (MODULE, INSTALL, WORKER, DAILY_STOP_WATCH, START, STOP, SMOKE):
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

    def test_daily_stop_window_is_exact_beijing_half_open_interval(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$base=[DateTimeOffset]::Parse('2026-08-28T08:20:00Z');"
            "$w=Get-BilibiliDailyStopWindow -UtcNow $base.AddSeconds(-1);"
            "'{0}:{1}' -f $w.InWindow,$w.Slot;"
            "0..19|ForEach-Object{$w=Get-BilibiliDailyStopWindow "
            "-UtcNow $base.AddMinutes($_);'{0}:{1}:{2}' -f "
            "$w.InWindow,$w.Slot,$w.CheckCount};"
            "$w=Get-BilibiliDailyStopWindow -UtcNow $base.AddMinutes(20);"
            "'{0}:{1}' -f $w.InWindow,$w.Slot"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.split(),
            ["False:-1"]
            + [f"True:{slot}:20" for slot in range(20)]
            + ["False:-1"],
        )

    def test_daily_stop_state_gate_is_exact_streaming_only(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "@('Streaming','Idle','NotRunning','Starting','Stopping','Unknown','')|"
            "ForEach-Object{'{0}:{1}' -f $_,(Test-BilibiliDailyStopRequired -State $_)}"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.split(),
            [
                "Streaming:True",
                "Idle:False",
                "NotRunning:False",
                "Starting:False",
                "Stopping:False",
                "Unknown:False",
                ":False",
            ],
        )

    def test_daily_watch_only_stops_exact_streaming_and_never_stops_services(self) -> None:
        text = DAILY_STOP_WATCH.read_text(encoding="utf-8")
        self.assertIn("Test-BilibiliDailyStopRequired -State $state", text)
        self.assertLess(
            text.index("Test-BilibiliDailyStopRequired -State $state"),
            text.index("Invoke-LivehimeStop"),
        )
        self.assertIn("Get-BilibiliDailyStopWindow", text)
        self.assertIn("Get-LivehimeStreamingState", text)
        self.assertIn("Set-SlayTheSpireTopMost -GameDir $GameDir", text)
        self.assertIn("Set-AscendViewerTopMost -ProjectRoot $ProjectRoot", text)
        for forbidden in (
            "Stop-Agent.ps1",
            "Stop-Process",
            "taskkill",
            ".runtime",
            "startlive",
            "stoplive",
            "api.live.bilibili.com",
            "http://",
            "https://",
        ):
            self.assertNotIn(forbidden.lower(), text.lower())

    def test_installer_registers_fixed_beijing_daily_stop_task(self) -> None:
        text = INSTALL.read_text(encoding="utf-8")
        self.assertIn('"BilibiliLive-DailyStopWatch"', text)
        self.assertIn('"China Standard Time"', text)
        self.assertIn("ConvertTimeToUtc", text)
        self.assertIn("New-ScheduledTaskTrigger -Daily -At $nextStartUtc", text)
        self.assertIn("New-TimeSpan -Minutes 1", text)
        self.assertIn("New-TimeSpan -Minutes 19", text)
        self.assertIn("StopAtDurationEnd = $false", text)
        self.assertIn("-StartWhenAvailable", text)
        self.assertIn("New-TimeSpan -Minutes 2", text)
        self.assertIn("$protectedDailyStopWatch", text)
        self.assertIn("$sourceHashes.DailyStopWatch", text)
        self.assertIn('-ProjectRoot `"$projectRoot`"', text)
        self.assertIn('-GameDir `"$gameDir`"', text)
        self.assertLess(text.index("$sourceHashes = @{"), text.index("Register-ScheduledTask"))
        self.assertLess(
            text.index('throw "Protected Livehime bridge hash verification failed."'),
            text.index("Start-ScheduledTask"),
        )

    def test_daily_stop_rechecks_window_and_deadline_before_click(self) -> None:
        daily = DAILY_STOP_WATCH.read_text(encoding="utf-8")
        module = MODULE.read_text(encoding="utf-8")
        self.assertGreaterEqual(daily.count("Get-BilibiliDailyStopWindow"), 3)
        self.assertIn("-StopBeforeUtc $preStopWindow.WindowEnd", daily)
        stop_start = module.index("function Invoke-LivehimeStop")
        stop_end = module.index("function Invoke-LivehimeBridge", stop_start)
        stop_body = module[stop_start:stop_end]
        deadline_check = "[DateTimeOffset]::UtcNow -ge $deadlineUtc"
        self.assertGreaterEqual(stop_body.count(deadline_check), 3)
        self.assertLess(stop_body.rindex(deadline_check), stop_body.index("Invoke-LivehimeClick"))

    def test_expired_daily_stop_deadline_fails_before_window_access(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "& (Get-Module BilibiliLive) {"
            "function Get-LivehimeStreamingState { 'Streaming' };"
            "function Wait-LivehimeWindow { throw 'WINDOW_TOUCHED' };"
            "try { Invoke-LivehimeStop -LivehimeExe 'unused.exe' "
            "-StopBeforeUtc ([DateTimeOffset]::UtcNow.AddSeconds(-1)) } "
            "catch { $_.Exception.Message }}"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Bilibili stop deadline has passed; no Livehime click was sent.",
        )
        self.assertNotIn("WINDOW_TOUCHED", result.stdout)

    def test_daily_worker_restores_windows_after_failed_stop_attempt(self) -> None:
        text = DAILY_STOP_WATCH.read_text(encoding="utf-8")
        self.assertIn("$stopAttempted = $true", text)
        self.assertIn("if ($stopAttempted) {", text)
        self.assertLess(text.index("$stopAttempted = $true"), text.index("Invoke-LivehimeStop"))
        self.assertLess(text.index("Invoke-LivehimeStop"), text.index("Set-SlayTheSpireTopMost"))
        self.assertLess(
            text.index("Set-SlayTheSpireTopMost"),
            text.index("Set-AscendViewerTopMost -ProjectRoot $ProjectRoot"),
        )
        self.assertIn("game_window_restore_error", text)
        self.assertIn("viewer_restore_error", text)
        self.assertLess(text.index("Set-AscendViewerTopMost"), text.index("ReleaseMutex()"))

    def test_windows_daily_trigger_accepts_exact_twenty_slot_repetition(self) -> None:
        command = (
            "$at=[DateTime]::SpecifyKind([DateTime]'2026-08-28 08:20:00',"
            "[DateTimeKind]::Utc);"
            "$daily=New-ScheduledTaskTrigger -Daily -At $at;"
            "$template=New-ScheduledTaskTrigger -Once -At $at "
            "-RepetitionInterval (New-TimeSpan -Minutes 1) "
            "-RepetitionDuration (New-TimeSpan -Minutes 19);"
            "$template.Repetition.StopAtDurationEnd=$false;"
            "$daily.Repetition=$template.Repetition;"
            "'{0}:{1}:{2}' -f $daily.Repetition.Interval,"
            "$daily.Repetition.Duration,$daily.Repetition.StopAtDurationEnd"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.split(), ["PT1M:PT19M:False"])

    def test_protected_workers_share_livehime_gui_mutex(self) -> None:
        manual = WORKER.read_text(encoding="utf-8")
        daily = DAILY_STOP_WATCH.read_text(encoding="utf-8")
        mutex_name = "Global\\VivhiteBilibiliLiveBridge"
        self.assertIn(mutex_name, manual)
        self.assertIn(mutex_name, daily)
        self.assertIn("WaitOne(0)", daily)
        self.assertIn("ReleaseMutex()", manual)
        self.assertIn("ReleaseMutex()", daily)

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
        self.assertLess(text.index("Set-SlayTheSpireTopMost"), text.index("Set-AscendViewerTopMost"))

    def test_viewer_reorder_does_not_take_focus(self) -> None:
        module = MODULE.read_text(encoding="utf-8")
        self.assertIn("Set-AscendViewerTopMost", module)
        self.assertIn("SwpNoActivate", module)
        self.assertIn('"ASCEND-VISION"', module)

    def test_game_foreground_has_exact_process_activation_fallback(self) -> None:
        module = MODULE.read_text(encoding="utf-8")
        self.assertIn("function Invoke-WindowProcessActivation", module)
        self.assertIn("GetWindowThreadProcessId($WindowHandle, [ref]$targetPid)", module)
        self.assertIn("New-Object -ComObject WScript.Shell", module)
        self.assertIn("AppActivate([int]$targetPid)", module)
        self.assertIn(
            "[void](Invoke-WindowProcessActivation -WindowHandle $WindowHandle)",
            module,
        )
        self.assertLess(
            module.index("[void](Invoke-WindowProcessActivation -WindowHandle $WindowHandle)"),
            module.index('throw "Could not make window $WindowHandle the foreground window.'),
        )

    def test_topmost_is_reasserted_after_foreground_activation(self) -> None:
        module = MODULE.read_text(encoding="utf-8")
        function_start = module.index("function Set-WindowAutomationForeground")
        function_end = module.index("function Set-WindowNotTopMost", function_start)
        function_body = module[function_start:function_end]
        activation = function_body.index("Invoke-WindowProcessActivation")
        final_topmost = function_body.rindex("SetWindowPos(")
        self.assertLess(activation, final_topmost)
        self.assertIn("make TOPMOST the final mutation", function_body)

    def test_every_game_topmost_entrypoint_reorders_viewer(self) -> None:
        module = MODULE.read_text(encoding="utf-8")
        smoke = SMOKE.read_text(encoding="utf-8")
        self.assertIn(
            "[void](Set-AscendViewerTopMost)\n    Write-Host \"Slay the Spire 2 is foreground",
            module,
        )
        self.assertGreaterEqual(smoke.count("[void](Set-AscendViewerTopMost)"), 2)

    def test_game_click_fallback_reorders_viewer_in_finally(self) -> None:
        policy = (ROOT / "sts2-ascend" / "brain" / "policy.py").read_text(encoding="utf-8")
        self.assertIn("from window_layers import reassert_viewer_topmost", policy)
        self.assertIn("finally:\n            # This fallback must focus the game", policy)
        self.assertIn("reassert_viewer_topmost()", policy)

    def test_viewer_has_periodic_nonactivating_z_order_watchdog(self) -> None:
        viewer = (ROOT / "sts2-ascend" / "brain" / "review_viewer.py").read_text(encoding="utf-8")
        self.assertIn("VIEWER_Z_ORDER_INTERVAL_SEC = 0.5", viewer)
        self.assertIn("self._reassert_viewer_topmost()", viewer)
        self.assertIn("force=True", viewer)
        self.assertIn("from window_layers import reassert_viewer_topmost", viewer)
        self.assertIn("before Tk maps the", viewer)
        self.assertIn('if not getattr(self, "_hwnd_prev", 0):', viewer)

    def test_broadcast_game_patrol_is_local_token_free_and_streaming_gated(self) -> None:
        patrol = PATROL.read_text(encoding="utf-8")
        viewer = (ROOT / "sts2-ascend" / "brain" / "review_viewer.py").read_text(
            encoding="utf-8")
        self.assertIn("BROADCAST_WINDOW_PATROL_INTERVAL_SEC = 60.0", patrol)
        self.assertIn('if state != "Streaming":', patrol)
        self.assertIn("process_name_running", patrol)
        self.assertIn("current_session_game_executable", patrol)
        self.assertIn("set_topmost_no_activate", patrol)
        self.assertIn("BroadcastWindowPatrol", viewer)
        self.assertIn("self._reassert_viewer_topmost()", viewer)
        for forbidden in (
            "openai", "minimax", "openrouter", "subprocess", "http://", "https://"
        ):
            self.assertNotIn(forbidden, patrol.lower())

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
        self.assertIn("BilibiliLive-DailyStopWatch", installer)
        self.assertIn("Invoke-BilibiliLiveDailyStopWatch.ps1", installer)

    def test_operational_path_has_no_web_api_or_obs_transport(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (MODULE, INSTALL, WORKER, DAILY_STOP_WATCH, START, STOP, SMOKE)
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
        self.assertIn("reorders it above the game", text)
        self.assertIn("every 500ms", text)
        self.assertIn("once every 60 seconds", text)
        self.assertIn('actual `Streaming`', text)
        self.assertIn("regardless of broadcast state", text)
        self.assertIn("16:20", text)
        self.assertIn("16:40", text)
        self.assertIn("20 checks", text)


if __name__ == "__main__":
    unittest.main()
