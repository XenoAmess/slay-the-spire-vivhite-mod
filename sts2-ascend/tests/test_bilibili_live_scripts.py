from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "sts2-ascend" / "scripts"
MODULE = SCRIPTS / "BilibiliLive.psm1"
INSTALL = SCRIPTS / "Install-BilibiliLiveBridge.ps1"
WORKER = SCRIPTS / "Invoke-BilibiliLiveBridge.ps1"
DAILY_START = SCRIPTS / "Invoke-BilibiliLiveDailyStart.ps1"
DAILY_STOP = SCRIPTS / "Invoke-BilibiliLiveDailyStopWatch.ps1"
HEALTH_WATCH = SCRIPTS / "Invoke-BilibiliLiveHealthWatch.ps1"
START = SCRIPTS / "Start-BilibiliLive.ps1"
STOP = SCRIPTS / "Stop-BilibiliLive.ps1"
SMOKE = SCRIPTS / "Test-BilibiliLive.ps1"
SKILL = ROOT / ".agents" / "skills" / "bilibili-live" / "SKILL.md"
PATROL = ROOT / "sts2-ascend" / "brain" / "broadcast_window_patrol.py"


def run_powershell(command: str) -> subprocess.CompletedProcess[str]:
    # Windows PowerShell inherits the system GBK code page when stdout is
    # redirected.  Force UTF-8 in the child before any command output so the
    # Chinese proof diagnostics cannot make the test reader fail during decode.
    command = "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;" + command
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=30,
        check=False,
    )


class BilibiliLiveScriptTests(unittest.TestCase):
    def test_powershell_files_parse_under_windows_powershell(self) -> None:
        for path in (
            MODULE, INSTALL, WORKER, DAILY_START, DAILY_STOP, HEALTH_WATCH,
            START, STOP, SMOKE
        ):
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
                encoding="utf-8",
                errors="replace",
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

    def test_broadcast_requires_bounded_quipper_without_suspending_it(self) -> None:
        module = MODULE.read_text(encoding="utf-8")
        start = START.read_text(encoding="utf-8")
        self.assertIn("function Wait-AscendIndexTtsBroadcastReady", module)
        self.assertIn("broadcast_coexistence_ready", module)
        self.assertIn('vocoder_device -notin @("cpu", "staged_cuda")', module)
        self.assertIn("MaximumAllocatorMiB = 3328", module)
        self.assertIn("function Suspend-AscendIndexTtsForBroadcast", module)
        self.assertIn('reason = "bilibili_stream"', module)
        self.assertIn("owner_creation_filetime", module)
        self.assertIn("Test-AscendExactProcessAlive", module)
        self.assertIn("Get-AscendIndexTtsLaunchCandidates", module)
        self.assertIn("$ownerFileTime -le 0", module)
        self.assertIn("if ($CreationFileTime -le 0) { return $false }", module)
        self.assertNotIn("Stop-Process", module)
        self.assertNotIn("taskkill", module.lower())
        self.assertLess(
            start.index("Wait-AscendIndexTtsBroadcastReady"),
            start.index("Invoke-LivehimeBridge -Action Start"),
        )
        self.assertNotIn("Suspend-AscendIndexTtsForBroadcast", start)
        self.assertNotIn("Restore-AscendIndexTtsAfterBroadcast", start)
        self.assertIn("LiveTimeoutSeconds = 120", start)
        self.assertIn("IndexTtsReadyTimeoutSeconds = 300", start)
        self.assertIn("Quipper remains online", start)

    def test_browser_dedupe_skips_unrelated_json_without_scene_fields(self) -> None:
        module = MODULE.read_text(encoding="utf-8")
        self.assertIn('if ($null -eq $payload -or $payload -is [Array]) { continue }', module)
        self.assertIn(
            '$payloadProperties = @($payload.PSObject.Properties | ForEach-Object { $_.Name })',
            module,
        )
        self.assertIn(
            'if ("sources" -notin $payloadProperties -or "current_scene" -notin $payloadProperties)',
            module,
        )

    def test_every_idle_stop_path_restores_the_single_index_owner(self) -> None:
        module = MODULE.read_text(encoding="utf-8")
        worker = WORKER.read_text(encoding="utf-8")
        health = HEALTH_WATCH.read_text(encoding="utf-8")
        stop = STOP.read_text(encoding="utf-8")
        self.assertIn("function Restore-AscendIndexTtsAfterBroadcast", module)
        self.assertIn("refusing to launch a second CUDA model", module)
        self.assertIn("Start-Process", module)
        self.assertIn("-WindowStyle Hidden", module)
        self.assertIn("-AllowNotRunning", module)
        self.assertNotIn("catch {\n        return [pscustomobject]@{\n            State = \"NoRunningSession\"", module)
        self.assertIn("Restore-AscendIndexTtsAfterBroadcast", worker)
        self.assertIn("Restore-AscendIndexTtsAfterBroadcast", health)
        self.assertIn("Restore-AscendIndexTtsAfterBroadcast", stop)

    def test_health_watch_audits_stop_and_tts_restore_failures_separately(self) -> None:
        health = HEALTH_WATCH.read_text(encoding="utf-8")
        installer = INSTALL.read_text(encoding="utf-8")
        self.assertIn('watch=safety_stop error=', health)
        self.assertIn('watch=indextts_restore error=', health)
        self.assertNotIn("MaximumRuntimeMinutes", health)
        self.assertNotIn("watch=exit maximum_runtime", health)
        self.assertIn("while ($true)", health)
        self.assertIn("runtime_limit=none", health)
        health_settings = installer[installer.index("$healthSettings"):]
        health_settings = health_settings[:health_settings.index("$healthArguments")]
        self.assertIn("-ExecutionTimeLimit ([TimeSpan]::Zero)", health_settings)
        self.assertNotIn("New-TimeSpan -Hours 12", health_settings)

    def test_health_watch_does_not_fast_stop_on_low_motion_alone(self) -> None:
        """Replay the three uncorroborated observations from the 04:57 incident."""
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$state=$null;1..3|ForEach-Object{"
            "$strong=if($null -eq $state){0}else{$state.CorroboratedFailureCount};"
            "$weak=if($null -eq $state){0}else{$state.LowMotionOnlyCount};"
            "$state=Get-BilibiliCaptureHealthDecision -CaptureBurst $false "
            "-PreviewAvailable $true -PreviewFresh $false "
            "-CorroboratedFailureCount $strong -LowMotionOnlyCount $weak};"
            "'{0}:{1}:{2}:{3}' -f $state.Signal,$state.CorroboratedFailureCount,"
            "$state.LowMotionOnlyCount,$state.ShouldStop"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "LowMotionOnly:0:3:False")

    def test_health_watch_fast_stop_requires_corroborated_capture_errors(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$state=$null;1..3|ForEach-Object{"
            "$strong=if($null -eq $state){0}else{$state.CorroboratedFailureCount};"
            "$weak=if($null -eq $state){0}else{$state.LowMotionOnlyCount};"
            "$state=Get-BilibiliCaptureHealthDecision -CaptureBurst $true "
            "-PreviewAvailable $true -PreviewFresh $false "
            "-CorroboratedFailureCount $strong -LowMotionOnlyCount $weak};"
            "'{0}:{1}:{2}:{3}' -f $state.Signal,$state.CorroboratedFailureCount,"
            "$state.ShouldStop,$state.StopReason"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "CorroboratedFailure:3:True:corroborated_frozen_capture",
        )

    def test_health_watch_prolonged_low_motion_still_fails_closed(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$state=Get-BilibiliCaptureHealthDecision -CaptureBurst $false "
            "-PreviewAvailable $true -PreviewFresh $false "
            "-LowMotionOnlyCount 45;"
            "'{0}:{1}:{2}' -f $state.LowMotionOnlyCount,$state.ShouldStop,"
            "$state.StopReason"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "46:True:prolonged_low_motion")

    def test_health_watch_fresh_preview_resets_both_failure_counters(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$state=Get-BilibiliCaptureHealthDecision -CaptureBurst $false "
            "-PreviewAvailable $true -PreviewFresh $true "
            "-CorroboratedFailureCount 2 -LowMotionOnlyCount 45;"
            "'{0}:{1}:{2}:{3}' -f $state.Signal,$state.CorroboratedFailureCount,"
            "$state.LowMotionOnlyCount,$state.ShouldStop"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "Healthy:0:0:False")

    def test_health_watch_gameplay_evidence_requires_applied_receipt(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$now=[DateTimeOffset]::Parse('2026-09-12T08:00:10Z');"
            "$session=[pscustomobject]@{session_id='session_1234';state='running'};"
            "$api=[pscustomobject]@{Port=8080;Data=[pscustomobject]@{"
            "state_version=16;screen='COMBAT';run_id='RUN-1';"
            "run=[pscustomobject]@{floor=1};available_actions=@('end_turn')}};"
            "$dash=[pscustomobject]@{schema='sts2.ascend-live/v1';"
            "session_id='session_1234';heartbeat='2026-09-12T08:00:10Z';"
            "connection=[pscustomobject]@{status='connected';at='2026-09-12T08:00:10Z'};"
            "run=[pscustomobject]@{run_id='RUN-1';screen='COMBAT'};"
            "decision=[pscustomobject]@{decision_id='d2';status='waiting';"
            "outcome=[pscustomobject]@{status='waiting';at='2026-09-12T08:00:10Z'}};"
            "history=@()};"
            "$pending=Test-BilibiliGameplayEvidence -Session $session -ApiState $api "
            "-Dashboard $dash -NowUtc $now;"
            "$dash.history=@([pscustomobject]@{decision_id='d1';status='applied';"
            "action='end_turn';at='2026-09-12T08:00:09Z'});"
            "$applied=Test-BilibiliGameplayEvidence -Session $session -ApiState $api "
            "-Dashboard $dash -NowUtc $now;"
            "'{0}:{1}:{2}:{3}:{4}' -f $pending.ContextValid,"
            "$pending.HasAppliedReceipt,$applied.HasAppliedReceipt,"
            "$applied.DecisionId,$applied.ReceiptSource"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "True:False:True:d1:history.outcome",
        )

    def test_health_watch_semantic_clock_only_resets_on_new_applied_action(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$t0=[DateTimeOffset]::Parse('2026-09-12T08:00:00Z');"
            "$first=[pscustomobject]@{ContextValid=$true;HardFailure=$false;"
            "HasAppliedReceipt=$true;Reason='ok';RunId='RUN-1';"
            "DecisionId='d1';OutcomeAt='2026-09-12T08:00:00Z'};"
            "$second=[pscustomobject]@{ContextValid=$true;HardFailure=$false;"
            "HasAppliedReceipt=$true;Reason='ok';RunId='RUN-1';"
            "DecisionId='d2';OutcomeAt='2026-09-12T08:00:10Z'};"
            "$baseline=Get-BilibiliGameplayHealthDecision -Evidence $first "
            "-LastProgressAtUtc $t0 -NowUtc $t0 -StallTimeoutSeconds 90;"
            "$same=Get-BilibiliGameplayHealthDecision -Evidence $first "
            "-PreviousRunId $baseline.PreviousRunId "
            "-PreviousDecisionId $baseline.PreviousDecisionId "
            "-PreviousOutcomeAt $baseline.PreviousOutcomeAt "
            "-LastProgressAtUtc $baseline.LastProgressAtUtc "
            "-NowUtc $t0.AddSeconds(90) -StallTimeoutSeconds 90;"
            "$progress=Get-BilibiliGameplayHealthDecision -Evidence $second "
            "-PreviousRunId $baseline.PreviousRunId "
            "-PreviousDecisionId $baseline.PreviousDecisionId "
            "-PreviousOutcomeAt $baseline.PreviousOutcomeAt "
            "-LastProgressAtUtc $baseline.LastProgressAtUtc "
            "-NowUtc $t0.AddSeconds(10) -StallTimeoutSeconds 90;"
            "'{0}:{1}:{2}:{3}:{4}:{5}' -f $baseline.State,$same.State,"
            "$same.ShouldStop,$same.StopReason,$progress.State,$progress.ShouldStop"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Baseline:Waiting:True:semantic_gameplay_stall:Progressed:False",
        )

    def test_health_watch_cross_run_transition_requires_two_new_run_receipts(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$now=[DateTimeOffset]::Parse('2026-09-12T08:00:10Z');"
            "$session=[pscustomobject]@{session_id='session_1234';state='running'};"
            "$api=[pscustomobject]@{Port=8080;Data=[pscustomobject]@{"
            "state_version=16;screen='MAIN_MENU';run_id='run_unknown';"
            "run=$null;available_actions=@('start_run')}};"
            "$dash=[pscustomobject]@{};"
            "$menu=Test-BilibiliGameplayEvidence -Session $session -ApiState $api "
            "-Dashboard $dash -NowUtc $now;"
            "$early=Get-BilibiliGameplayHealthDecision -Evidence $menu "
            "-PreviousRunId 'RUN-1' -PreviousDecisionId 'old' "
            "-PreviousOutcomeAt '2026-09-12T08:00:00Z' "
            "-LastProgressAtUtc $now -NowUtc $now -StallTimeoutSeconds 90;"
            "$api.Data.screen='UNKNOWN';"
            "$unknown=Test-BilibiliGameplayEvidence -Session $session -ApiState $api "
            "-Dashboard $dash -NowUtc $now.AddSeconds(10);"
            "$duringUnknown=Get-BilibiliGameplayHealthDecision -Evidence $unknown "
            "-PreviousRunId $early.PreviousRunId -PreviousDecisionId $early.PreviousDecisionId "
            "-PreviousOutcomeAt $early.PreviousOutcomeAt "
            "-PreviousTransitionStartedAt $early.TransitionStartedAt "
            "-LastProgressAtUtc $early.LastProgressAtUtc "
            "-NowUtc $now.AddSeconds(10) -StallTimeoutSeconds 90;"
            "$late=Get-BilibiliGameplayHealthDecision -Evidence $menu "
            "-PreviousRunId $early.PreviousRunId -PreviousDecisionId $early.PreviousDecisionId "
            "-PreviousOutcomeAt $early.PreviousOutcomeAt "
            "-PreviousTransitionStartedAt $early.TransitionStartedAt "
            "-LastProgressAtUtc $early.LastProgressAtUtc "
            "-NowUtc $now.AddSeconds(120) -StallTimeoutSeconds 90;"
            "$first=[pscustomobject]@{ContextValid=$true;HardFailure=$false;"
            "CrossRunTransition=$false;HasAppliedReceipt=$true;Reason='ok';RunId='RUN-2';"
            "DecisionId='d1';OutcomeAt='2026-09-12T08:00:30Z'};"
            "$baseline=Get-BilibiliGameplayHealthDecision -Evidence $first "
            "-PreviousRunId $early.PreviousRunId -PreviousDecisionId $early.PreviousDecisionId "
            "-PreviousOutcomeAt $early.PreviousOutcomeAt "
            "-PreviousTransitionStartedAt $early.TransitionStartedAt "
            "-LastProgressAtUtc $early.LastProgressAtUtc "
            "-NowUtc $now.AddSeconds(20) -StallTimeoutSeconds 90;"
            "$second=[pscustomobject]@{ContextValid=$true;HardFailure=$false;"
            "CrossRunTransition=$false;HasAppliedReceipt=$true;Reason='ok';RunId='RUN-2';"
            "DecisionId='d2';OutcomeAt='2026-09-12T08:00:35Z'};"
            "$progress=Get-BilibiliGameplayHealthDecision -Evidence $second "
            "-PreviousRunId $baseline.PreviousRunId -PreviousDecisionId $baseline.PreviousDecisionId "
            "-PreviousOutcomeAt $baseline.PreviousOutcomeAt "
            "-PreviousTransitionStartedAt $baseline.TransitionStartedAt "
            "-PreviousTransitionProofStartedAt $baseline.TransitionProofStartedAt "
            "-LastProgressAtUtc $baseline.LastProgressAtUtc "
            "-NowUtc $now.AddSeconds(25) -StallTimeoutSeconds 90;"
            "'{0}:{1}:{2}:{3}:{4}:{5}:{6}:{7}:{8}:{9}' -f $menu.HardFailure,"
            "$menu.CrossRunTransition,$early.State,$early.ShouldStop,$unknown.HardFailure,"
            "$duringUnknown.State,$duringUnknown.ShouldStop,$late.StopReason,"
            "$baseline.State,$progress.State"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "False:True:Transition:False:False:Transition:False:"
            "cross_run_transition_timeout:Transition:Progressed",
        )

    def test_cross_run_receipt_at_old_90_second_boundary_starts_fresh_proof_window(self) -> None:
        """Replay the 06:39 race: first new-run proof arrived after the old 90s deadline."""
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$t0=[DateTimeOffset]::Parse('2026-09-14T22:37:41Z');"
            "$menu=[pscustomobject]@{ContextValid=$false;HardFailure=$false;"
            "CrossRunTransition=$true;HasAppliedReceipt=$false;Reason='cross_run_transition'};"
            "$started=Get-BilibiliGameplayHealthDecision -Evidence $menu "
            "-PreviousRunId 'OLD-RUN' -PreviousDecisionId 'old' "
            "-PreviousOutcomeAt '2026-09-14T22:37:39Z' "
            "-LastProgressAtUtc $t0 -NowUtc $t0;"
            "$unknown=[pscustomobject]@{ContextValid=$false;HardFailure=$false;"
            "CrossRunTransition=$false;HasAppliedReceipt=$false;Reason='transient_screen_unverifiable'};"
            "$pending=Get-BilibiliGameplayHealthDecision -Evidence $unknown "
            "-PreviousRunId $started.PreviousRunId "
            "-PreviousDecisionId $started.PreviousDecisionId "
            "-PreviousOutcomeAt $started.PreviousOutcomeAt "
            "-PreviousTransitionStartedAt $started.TransitionStartedAt "
            "-LastProgressAtUtc $started.LastProgressAtUtc "
            "-NowUtc $t0.AddSeconds(84.9);"
            "$first=[pscustomobject]@{ContextValid=$true;HardFailure=$false;"
            "CrossRunTransition=$false;HasAppliedReceipt=$true;Reason='ok';"
            "RunId='RNM3MWDHFAUL';DecisionId='d1';OutcomeAt='2026-09-14T22:39:12Z'};"
            "$baseline=Get-BilibiliGameplayHealthDecision -Evidence $first "
            "-PreviousRunId $pending.PreviousRunId "
            "-PreviousDecisionId $pending.PreviousDecisionId "
            "-PreviousOutcomeAt $pending.PreviousOutcomeAt "
            "-PreviousTransitionStartedAt $pending.TransitionStartedAt "
            "-LastProgressAtUtc $pending.LastProgressAtUtc "
            "-NowUtc $t0.AddSeconds(91.6);"
            "$second=[pscustomobject]@{ContextValid=$true;HardFailure=$false;"
            "CrossRunTransition=$false;HasAppliedReceipt=$true;Reason='ok';"
            "RunId='RNM3MWDHFAUL';DecisionId='d2';OutcomeAt='2026-09-14T22:39:15Z'};"
            "$progress=Get-BilibiliGameplayHealthDecision -Evidence $second "
            "-PreviousRunId $baseline.PreviousRunId "
            "-PreviousDecisionId $baseline.PreviousDecisionId "
            "-PreviousOutcomeAt $baseline.PreviousOutcomeAt "
            "-PreviousTransitionStartedAt $baseline.TransitionStartedAt "
            "-PreviousTransitionProofStartedAt $baseline.TransitionProofStartedAt "
            "-LastProgressAtUtc $baseline.LastProgressAtUtc "
            "-NowUtc $t0.AddSeconds(98.3);"
            "'{0}:{1}:{2}:{3}:{4}:{5}:{6}:{7}:{8}' -f "
            "$pending.State,$pending.ShouldStop,$pending.TimeoutSeconds,"
            "$baseline.State,$baseline.ShouldStop,$baseline.TimeoutSeconds,"
            "$progress.State,$progress.ShouldStop,"
            "[string]::IsNullOrWhiteSpace($progress.TransitionProofStartedAt)"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Transition:False:120:Transition:False:30:Progressed:False:True",
        )

    def test_cross_run_repeated_baseline_times_out_in_proof_phase(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$t0=[DateTimeOffset]::Parse('2026-09-14T22:37:41Z');"
            "$first=[pscustomobject]@{ContextValid=$true;HardFailure=$false;"
            "CrossRunTransition=$false;HasAppliedReceipt=$true;Reason='ok';"
            "RunId='NEW-RUN';DecisionId='d1';OutcomeAt='2026-09-14T22:39:12Z'};"
            "$baseline=Get-BilibiliGameplayHealthDecision -Evidence $first "
            "-PreviousRunId 'OLD-RUN' -PreviousDecisionId 'old' "
            "-PreviousOutcomeAt '2026-09-14T22:37:39Z' "
            "-PreviousTransitionStartedAt $t0.ToString('o') "
            "-LastProgressAtUtc $t0 -NowUtc $t0.AddSeconds(91.6);"
            "$late=Get-BilibiliGameplayHealthDecision -Evidence $first "
            "-PreviousRunId $baseline.PreviousRunId "
            "-PreviousDecisionId $baseline.PreviousDecisionId "
            "-PreviousOutcomeAt $baseline.PreviousOutcomeAt "
            "-PreviousTransitionStartedAt $baseline.TransitionStartedAt "
            "-PreviousTransitionProofStartedAt $baseline.TransitionProofStartedAt "
            "-LastProgressAtUtc $baseline.LastProgressAtUtc "
            "-NowUtc $t0.AddSeconds(121.6);"
            "'{0}:{1}:{2}:{3}:{4}' -f $late.State,$late.Reason,"
            "$late.TimeoutSeconds,$late.ShouldStop,$late.StopReason"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Transition:cross_run_second_applied_receipt_pending:30:True:"
            "cross_run_transition_timeout",
        )

    def test_cross_run_receipts_cannot_arrive_after_either_deadline(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$t0=[DateTimeOffset]::Parse('2026-09-14T22:37:41Z');"
            "$first=[pscustomobject]@{ContextValid=$true;HardFailure=$false;"
            "CrossRunTransition=$false;HasAppliedReceipt=$true;Reason='ok';"
            "RunId='NEW-RUN';DecisionId='d1';OutcomeAt='2026-09-14T22:39:42Z'};"
            "$lateFirst=Get-BilibiliGameplayHealthDecision -Evidence $first "
            "-PreviousRunId 'OLD-RUN' -PreviousDecisionId 'old' "
            "-PreviousOutcomeAt '2026-09-14T22:37:39Z' "
            "-PreviousTransitionStartedAt $t0.ToString('o') "
            "-LastProgressAtUtc $t0 -NowUtc $t0.AddSeconds(121);"
            "$onTimeFirst=Get-BilibiliGameplayHealthDecision -Evidence $first "
            "-PreviousRunId 'OLD-RUN' -PreviousDecisionId 'old' "
            "-PreviousOutcomeAt '2026-09-14T22:37:39Z' "
            "-PreviousTransitionStartedAt $t0.ToString('o') "
            "-LastProgressAtUtc $t0 -NowUtc $t0.AddSeconds(100);"
            "$second=[pscustomobject]@{ContextValid=$true;HardFailure=$false;"
            "CrossRunTransition=$false;HasAppliedReceipt=$true;Reason='ok';"
            "RunId='NEW-RUN';DecisionId='d2';OutcomeAt='2026-09-14T22:39:45Z'};"
            "$lateSecond=Get-BilibiliGameplayHealthDecision -Evidence $second "
            "-PreviousRunId $onTimeFirst.PreviousRunId "
            "-PreviousDecisionId $onTimeFirst.PreviousDecisionId "
            "-PreviousOutcomeAt $onTimeFirst.PreviousOutcomeAt "
            "-PreviousTransitionStartedAt $onTimeFirst.TransitionStartedAt "
            "-PreviousTransitionProofStartedAt $onTimeFirst.TransitionProofStartedAt "
            "-LastProgressAtUtc $onTimeFirst.LastProgressAtUtc "
            "-NowUtc $t0.AddSeconds(131);"
            "'{0}:{1}:{2}:{3}:{4}:{5}' -f $lateFirst.State,$lateFirst.Reason,"
            "$lateFirst.ShouldStop,$lateSecond.State,$lateSecond.Reason,$lateSecond.ShouldStop"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Transition:cross_run_first_applied_receipt_too_late:True:"
            "Transition:cross_run_second_applied_receipt_too_late:True",
        )

    def test_health_watch_unknown_screen_outside_transition_gets_bounded_grace(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$t0=[DateTimeOffset]::Parse('2026-09-12T08:00:00Z');"
            "$session=[pscustomobject]@{session_id='session_1234';state='running'};"
            "$api=[pscustomobject]@{Port=8080;Data=[pscustomobject]@{"
            "state_version=16;screen='UNKNOWN';run_id='run_unknown';"
            "run=$null;available_actions=@()}};"
            "$unknown=Test-BilibiliGameplayEvidence -Session $session -ApiState $api "
            "-Dashboard ([pscustomobject]@{}) -NowUtc $t0;"
            "$early=Get-BilibiliGameplayHealthDecision -Evidence $unknown "
            "-LastProgressAtUtc $t0 -NowUtc $t0.AddSeconds(89) -StallTimeoutSeconds 90;"
            "$late=Get-BilibiliGameplayHealthDecision -Evidence $unknown "
            "-LastProgressAtUtc $t0 -NowUtc $t0.AddSeconds(90) -StallTimeoutSeconds 90;"
            "'{0}:{1}:{2}:{3}:{4}:{5}' -f $unknown.HardFailure,$unknown.Reason,"
            "$early.State,$early.ShouldStop,$late.ShouldStop,$late.StopReason"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "False:transient_screen_unverifiable:Unverifiable:False:True:"
            "gameplay_evidence_unavailable",
        )

    def test_health_watch_hard_invalid_gameplay_state_stops_immediately(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$now=[DateTimeOffset]::Parse('2026-09-12T08:00:10Z');"
            "$session=[pscustomobject]@{session_id='session_1234';state='stopped'};"
            "$api=[pscustomobject]@{Port=8080;Data=[pscustomobject]@{"
            "state_version=16;screen='COMBAT';run_id='run_unknown';"
            "run=$null;available_actions=@('end_turn')}};"
            "$dash=[pscustomobject]@{};"
            "$stopped=Test-BilibiliGameplayEvidence -Session $session -ApiState $api "
            "-Dashboard $dash -NowUtc $now;"
            "$session.state='running';"
            "$unknownRun=Test-BilibiliGameplayEvidence -Session $session -ApiState $api "
            "-Dashboard $dash -NowUtc $now;"
            "'{0}:{1}:{2}:{3}' -f $stopped.HardFailure,$stopped.Reason,"
            "$unknownRun.HardFailure,$unknownRun.Reason"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "True:session_not_running:True:active_run_unverifiable",
        )

    def test_health_watch_transient_unverifiable_state_gets_bounded_grace(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$t0=[DateTimeOffset]::Parse('2026-09-12T08:00:00Z');"
            "$missing=[pscustomobject]@{ContextValid=$false;HardFailure=$false;"
            "HasAppliedReceipt=$false;Reason='api_state_unavailable'};"
            "$early=Get-BilibiliGameplayHealthDecision -Evidence $missing "
            "-LastProgressAtUtc $t0 -NowUtc $t0.AddSeconds(89) -StallTimeoutSeconds 90;"
            "$late=Get-BilibiliGameplayHealthDecision -Evidence $missing "
            "-LastProgressAtUtc $t0 -NowUtc $t0.AddSeconds(90) -StallTimeoutSeconds 90;"
            "'{0}:{1}:{2}:{3}' -f $early.State,$early.ShouldStop,"
            "$late.ShouldStop,$late.StopReason"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip(),
            "Unverifiable:False:True:gameplay_evidence_unavailable",
        )

    def test_health_watch_keeps_capture_and_semantic_clocks_independent(self) -> None:
        health = HEALTH_WATCH.read_text(encoding="utf-8")
        self.assertIn("GameplayStallSeconds = 90", health)
        self.assertIn("CrossRunTimeoutSeconds = 120", health)
        self.assertIn("CrossRunProofTimeoutSeconds = 30", health)
        self.assertIn("PreviousTransitionProofStartedAt", health)
        self.assertIn("limit_seconds=$($gameplayDecision.TimeoutSeconds)", health)
        self.assertIn("Get-BilibiliGameplayProgressSnapshot", health)
        self.assertIn("Get-BilibiliGameplayHealthDecision", health)
        self.assertIn("watch=gameplay_hard_failure", health)
        self.assertIn("watch=gameplay_transition", health)
        self.assertIn("watch=gameplay_unverifiable", health)
        self.assertIn("gameplay_elapsed_seconds", health)
        semantic_call = health.index("Get-BilibiliGameplayHealthDecision")
        semantic_window = health[semantic_call:semantic_call + 700]
        self.assertNotIn("PreviewFresh", semantic_window)
        self.assertNotIn("ChangedRatio", semantic_window)

    def test_daily_start_is_exactly_2300_beijing_and_schedules_forward(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$base=[DateTimeOffset]::Parse('2026-09-06T15:00:00Z');"
            "$w=Get-BilibiliDailyStartWindow -UtcNow $base;"
            "'{0}:{1}:{2}' -f $w.InWindow,$w.Slot,$w.CheckCount;"
            "$samples=@($base.AddSeconds(-1),$base,$base.AddSeconds(1));"
            "$samples|ForEach-Object{$s=Get-BilibiliDailyStartSchedule -UtcNow $_;"
            "$s.NextStartUtc.ToString('o')}"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip().splitlines(),
            [
                "True:0:20",
                "2026-09-06T15:00:00.0000000+00:00",
                "2026-09-06T15:00:00.0000000+00:00",
                "2026-09-07T15:00:00.0000000+00:00",
            ],
        )

    def test_daily_stop_is_exactly_1100_beijing_and_schedules_forward(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$base=[DateTimeOffset]::Parse('2026-09-06T03:00:00Z');"
            "$w=Get-BilibiliDailyStopWindow -UtcNow $base;"
            "'{0}:{1}:{2}' -f $w.InWindow,$w.Slot,$w.CheckCount;"
            "$samples=@($base.AddSeconds(-1),$base,$base.AddSeconds(1));"
            "$samples|ForEach-Object{$s=Get-BilibiliDailyStopSchedule -UtcNow $_;"
            "$s.NextStartUtc.ToString('o')}"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip().splitlines(),
            [
                "True:0:20",
                "2026-09-06T03:00:00.0000000+00:00",
                "2026-09-06T03:00:00.0000000+00:00",
                "2026-09-07T03:00:00.0000000+00:00",
            ],
        )

    def test_daily_stop_requires_exact_streaming_state(self) -> None:
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
                "Streaming:True", "Idle:False", "NotRunning:False",
                "Starting:False", "Stopping:False", "Unknown:False", ":False",
            ],
        )

    def test_daily_windows_are_half_open_twenty_minute_windows(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "$start=[DateTimeOffset]::Parse('2026-09-06T15:00:00Z');"
            "$stop=[DateTimeOffset]::Parse('2026-09-06T03:00:00Z');"
            "@($start,$stop)|ForEach-Object{"
            "$kind=if($_ -eq $start){'start'}else{'stop'};"
            "$fn=if($kind -eq 'start'){'Get-BilibiliDailyStartWindow'}"
            "else{'Get-BilibiliDailyStopWindow'};"
            "$before=& $fn -UtcNow $_.AddSeconds(-1);"
            "$first=& $fn -UtcNow $_;"
            "$last=& $fn -UtcNow $_.AddMinutes(19).AddSeconds(59);"
            "$after=& $fn -UtcNow $_.AddMinutes(20);"
            "'{0}:{1}:{2}:{3}:{4}:{5}' -f $kind,$before.InWindow,"
            "$first.Slot,$last.InWindow,$last.Slot,$after.InWindow}"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.strip().splitlines(),
            ["start:False:0:True:19:False", "stop:False:0:True:19:False"],
        )

    def test_bridge_install_gate_allows_only_idle_or_not_running(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "@('Idle','NotRunning','Streaming','Starting','Stopping','Unknown','')|"
            "ForEach-Object{'{0}:{1}' -f $_,"
            "(Test-BilibiliBridgeInstallSafeState -State $_)}"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.split(),
            [
                "Idle:True",
                "NotRunning:True",
                "Streaming:False",
                "Starting:False",
                "Stopping:False",
                "Unknown:False",
                ":False",
            ],
        )

    def test_streaming_state_reverse_scan_survives_error_log_flood(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = pathlib.Path(temp_dir) / "bililive_debug.log"
            log_path.write_text(
                "set_streaming_status: last_status:7 set_status:0\n"
                + "gs_duplicator_update_frame: Failed to update frame (887A0001)\n" * 50100,
                encoding="utf-8",
            )
            module_path = str(MODULE).replace("'", "''")
            escaped_log = str(log_path).replace("'", "''")
            command = (
                "$tokens=$null;$errors=$null;"
                f"$ast=[Management.Automation.Language.Parser]::ParseFile('{module_path}',"
                "[ref]$tokens,[ref]$errors);"
                "$fn=$ast.Find({param($n)$n -is "
                "[Management.Automation.Language.FunctionDefinitionAst] -and "
                "$n.Name -eq 'Get-LivehimeLatestStatusCode'},$true);"
                ". ([scriptblock]::Create($fn.Extent.Text));"
                f"Get-LivehimeLatestStatusCode -LogPath '{escaped_log}'"
            )
            result = run_powershell(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "0")

    def test_display_capture_stale_detector_is_specific(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        self.assertIn("function Test-LivehimeDisplayCaptureStale", text)
        self.assertIn("gs_duplicator_update_frame", text)
        self.assertIn("887A0001", text)
        self.assertIn("$failures.Count -ge $MinimumFailures", text)

    def test_fresh_livehime_unknown_start_requires_calibrated_button(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        start = text.index("function Invoke-LivehimeStart")
        end = text.index("function Invoke-LivehimeStop", start)
        body = text[start:end]
        self.assertIn('$state -notin @("Idle", "NotRunning", "Unknown")', body)
        self.assertIn("Test-LivehimeStartButton", body)
        self.assertLess(
            body.index('$state -notin @("Idle", "NotRunning", "Unknown")'),
            body.index("Test-LivehimeStartButton"),
        )
        stop = text[end:text.index("function Invoke-LivehimeBridge", end)]
        self.assertIn('$state -ne "Streaming"', stop)

    def test_ended_dialog_close_glyph_requires_all_four_diagonal_arms(self) -> None:
        escaped = str(MODULE).replace("'", "''")
        command = (
            f"Import-Module '{escaped}' -Force;"
            "& (Get-Module BilibiliLive) {"
            "Add-Type -AssemblyName System.Drawing;"
            "$bg=[Drawing.Color]::FromArgb(24,24,24);"
            "$fg=[Drawing.Color]::FromArgb(150,150,150);"
            "$blank=New-Object Drawing.Bitmap 31,31;"
            "$xglyph=New-Object Drawing.Bitmap 31,31;"
            "$slash=New-Object Drawing.Bitmap 31,31;"
            "$gb=[Drawing.Graphics]::FromImage($blank);"
            "$gx=[Drawing.Graphics]::FromImage($xglyph);"
            "$gs=[Drawing.Graphics]::FromImage($slash);"
            "$pen=New-Object Drawing.Pen $fg,2;"
            "try{$gb.Clear($bg);$gx.Clear($bg);$gs.Clear($bg);"
            "$gx.DrawLine($pen,9,9,21,21);$gx.DrawLine($pen,21,9,9,21);"
            "$gs.DrawLine($pen,9,9,21,21);"
            "'{0}:{1}:{2}:{3}' -f "
            "(Test-LivehimeCloseGlyph $xglyph 15 15),"
            "(Test-LivehimeCloseGlyph $blank 15 15),"
            "(Test-LivehimeCloseGlyph $slash 15 15),"
            "(Test-LivehimeCloseGlyphNear $xglyph 17 15)}"
            "finally{$pen.Dispose();$gb.Dispose();$gx.Dispose();$gs.Dispose();"
            "$blank.Dispose();$xglyph.Dispose();$slash.Dispose()}}"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True:False:False:True")
        text = MODULE.read_text(encoding="utf-8")
        start = text.index("function Invoke-LivehimeStart")
        end = text.index("function Invoke-LivehimeStop", start)
        body = text[start:end]
        self.assertLess(
            body.index("Close-LivehimeIdleDialogs"),
            body.index("Test-LivehimeStartButton"),
        )

    def test_ended_dialog_pixel_gate_precedes_bounded_ocr(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        async_start = text.index("function Invoke-WinRtAsync")
        async_end = text.index("function Get-LivehimeScreenText", async_start)
        async_body = text[async_start:async_end]
        self.assertIn("[ValidateRange(1, 30)][int]$TimeoutSeconds = 5", async_body)
        self.assertIn("$task.Wait([TimeSpan]::FromSeconds($TimeoutSeconds))", async_body)
        self.assertNotIn("$task.Wait()", async_body)

        close_start = text.index("function Close-LivehimeIdleDialogs")
        close_end = text.index("function Get-LivehimeTogglePoint", close_start)
        close_body = text[close_start:close_end]
        self.assertLess(
            close_body.index("Get-LivehimeEndedDialogClosePoint"),
            close_body.index("Get-LivehimeScreenText"),
        )

        start_begin = text.index("function Invoke-LivehimeStart")
        start_end = text.index("function Invoke-LivehimeStop", start_begin)
        start_body = text[start_begin:start_end]
        self.assertIn("Livehime reopened the ended/violation dialog after Start", start_body)
        self.assertIn("Test-LivehimeEndedDialogCloseButton", start_body)
        self.assertIn("$dialogCheckNotBefore", start_body)

        worker = WORKER.read_text(encoding="utf-8")
        self.assertIn("$endedDialogRejected", worker)
        self.assertIn("$startProducedNoTransition", worker)
        self.assertIn("ended_or_violation_dialog_reopened", worker)
        self.assertIn("start_produced_no_livehime_transition", worker)
        self.assertIn("Restart-LivehimeIdle", worker)

    def test_ended_dialog_supports_compact_and_wide_calibrated_close_points(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        point_start = text.index("function Get-LivehimeEndedDialogClosePoint")
        point_end = text.index("function Test-LivehimeEndedDialogCloseButton", point_start)
        point_body = text[point_start:point_end]
        self.assertIn("318 * $snapshot.Scale", point_body)
        self.assertIn("615 * $snapshot.Scale", point_body)
        self.assertIn("Test-LivehimeCloseGlyph", point_body)
        self.assertIn("if ($AllowWide)", point_body)

        expected_start = text.index("function Test-LivehimeWideEndedDialogExpected")
        expected_end = text.index("function Get-LivehimeEndedDialogClosePoint", expected_start)
        expected_body = text[expected_start:expected_end]
        self.assertIn("LiveStopDialog::ShowWindow", expected_body)
        self.assertIn("--- Application Startup ---", expected_body)

        close_start = text.index("function Close-LivehimeIdleDialogs")
        close_end = text.index("function Get-LivehimeTogglePoint", close_start)
        close_body = text[close_start:close_end]
        self.assertIn("Get-LivehimeEndedDialogClosePoint", close_body)
        self.assertIn("Invoke-LivehimeClick -X $closePoint.X -Y $closePoint.Y", close_body)

    def test_livehime_restart_is_idle_only_and_never_force_kills(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        start = text.index("function Restart-LivehimeIdle")
        end = text.index("function Wait-LivehimeStreamingState", start)
        body = text[start:end]
        self.assertIn('$state -notin @("Idle", "NotRunning")', body)
        self.assertIn("CloseMainWindow()", body)
        self.assertIn("PostMessage(", body)
        self.assertIn("if ($sameProcess)", body)
        self.assertNotIn("$mainWindowClosed", body)
        self.assertIn("no process was terminated", body)
        self.assertNotIn("Stop-Process", body)
        self.assertNotIn("taskkill", body.lower())

    def test_installer_registers_daily_stop_window_through_unified_entrypoint(self) -> None:
        text = INSTALL.read_text(encoding="utf-8")
        module = MODULE.read_text(encoding="utf-8")
        daily_stop = DAILY_STOP.read_text(encoding="utf-8")
        self.assertTrue(DAILY_STOP.exists())
        self.assertIn("function Get-BilibiliDailyStopWindow", module)
        self.assertIn("function Get-BilibiliDailyStopSchedule", module)
        self.assertIn("function Test-BilibiliDailyStopRequired", module)
        self.assertIn('Register-ScheduledTask -TaskName "BilibiliLive-DailyStopWatch"', text)
        self.assertIn("Get-BilibiliDailyStopSchedule", text)
        self.assertIn("$sourceHashes.DailyStop", text)
        self.assertIn("-LogonType Interactive -RunLevel Limited", text)
        self.assertIn("Get-BilibiliDailyStopWindow", daily_stop)
        self.assertIn('Join-Path $ProjectRoot "scripts\\Stop-BilibiliLive.ps1"', daily_stop)
        self.assertIn("& $stopScript -GameDir $GameDir", daily_stop)
        self.assertIn('if ($state -in @("Idle", "NotRunning"))', daily_stop)
        self.assertIn("Test-BilibiliDailyStopRequired -State $state", daily_stop)
        for forbidden in (
            "Invoke-LivehimeStop",
            "Stop-Agent.ps1",
            "Start-ScheduledTask",
            "api.live.bilibili.com",
            "http://",
            "https://",
        ):
            self.assertNotIn(forbidden.lower(), daily_stop.lower())

    def test_installer_registers_twenty_limited_fail_closed_start_checks(self) -> None:
        installer = INSTALL.read_text(encoding="utf-8")
        daily_start = DAILY_START.read_text(encoding="utf-8")
        self.assertIn('"BilibiliLive-DailyStart"', installer)
        self.assertIn("Get-BilibiliDailyStartSchedule", installer)
        self.assertIn("function New-BilibiliWindowTrigger", installer)
        self.assertIn("New-ScheduledTaskTrigger -Daily -At $At", installer)
        self.assertIn("-RepetitionInterval (New-TimeSpan -Minutes 1)", installer)
        self.assertIn("-RepetitionDuration (New-TimeSpan -Minutes 19)", installer)
        self.assertIn('Repetition.Interval -ne "PT1M"', installer)
        self.assertIn('Repetition.Duration -ne "PT19M"', installer)
        self.assertIn("-LogonType Interactive -RunLevel Limited", installer)
        self.assertIn("$sourceHashes.DailyStart", installer)
        self.assertIn("$registeredTrigger.StartBoundary", installer)
        self.assertIn("$registeredInfo.NextRunTime.ToUniversalTime()", installer)
        self.assertIn('Start-ScheduledTask -TaskName "BilibiliLive-DailyStart"', installer)

        self.assertIn("Get-BilibiliDailyStartWindow", daily_start)
        self.assertGreaterEqual(daily_start.count("Get-BilibiliDailyStartWindow"), 2)
        self.assertIn("daily-start.success", daily_start)
        self.assertIn("already_confirmed_streaming", daily_start)
        self.assertIn('"BilibiliLive-HealthWatch"', daily_start)
        self.assertIn('$healthTask.State -eq "Running"', daily_start)
        self.assertIn('Join-Path $ProjectRoot "scripts\\Start-BilibiliLive.ps1"', daily_start)
        self.assertIn('& $startScript -GameDir $GameDir', daily_start)
        for forbidden in (
            "Invoke-LivehimeStart",
            "Start-Agent.ps1",
            "Start-ScheduledTask",
            "api.live.bilibili.com",
            "http://",
            "https://",
        ):
            self.assertNotIn(forbidden.lower(), daily_start.lower())

    def test_installer_requests_uac_before_admin_only_mutation(self) -> None:
        text = INSTALL.read_text(encoding="utf-8")
        admin_gate = text.index("if (-not (Test-IsAdministrator))")
        live_state_gate = text.index("Test-BilibiliBridgeInstallSafeState")
        uac = text.index("-Verb RunAs")
        self.assertIn("-Verb RunAs", text)
        self.assertIn('"-Elevated"', text)
        self.assertIn("No UAC prompt was requested", text)
        self.assertNotIn('"-Confirm:`$false"', text)
        self.assertNotIn("$PSCmdlet.ShouldProcess", text)
        self.assertLess(live_state_gate, uac)
        self.assertLess(admin_gate, text.index("New-Item -ItemType Directory"))

    def test_protected_worker_serializes_livehime_gui(self) -> None:
        manual = WORKER.read_text(encoding="utf-8")
        mutex_name = "Global\\VivhiteBilibiliLiveBridge"
        self.assertIn(mutex_name, manual)
        self.assertIn("ReleaseMutex()", manual)

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
        # The fail-closed recovery helper contains a Stop bridge call before
        # startup by design; assert ordering against the actual Start action.
        self.assertLess(text.index("& $startAgent"), text.index("Invoke-LivehimeBridge -Action Start"))
        self.assertLess(text.index("Invoke-LivehimeBridge -Action Start"), text.index("Set-SlayTheSpireTopMost"))
        self.assertLess(text.index("Set-SlayTheSpireTopMost"), text.index("Set-AscendViewerTopMost"))

    def test_start_has_fail_closed_gameplay_preflight_before_livehime_click(self) -> None:
        text = START.read_text(encoding="utf-8")
        self.assertIn("Wait-AscendLiveGameplayReady", text)
        self.assertIn("Test-AscendLiveGameplayProof", text)
        self.assertIn("GameplayPassiveScreens", text)
        self.assertIn("run_unknown", text)
        self.assertIn("available_actions", text)
        self.assertIn("two distinct applied Brain actions", text)
        self.assertIn('connectionStatus -ne "connected"', text)
        self.assertIn('outcomeStatus -ne "applied"', text)
        self.assertIn("stateVersion -notmatch '^\\d+$'", text)
        self.assertIn("Test-AscendAppliedActionProgress", text)
        self.assertIn("$currentDecisionId -eq $previousDecisionId", text)
        self.assertIn("return $currentOutcomeAt -gt $previousOutcomeAt", text)
        self.assertNotIn("currentStateVersion -gt $previousStateVersion", text)
        gate = text.index("Wait-AscendLiveGameplayReady -ProjectRoot")
        bridge = text.index("Invoke-LivehimeBridge -Action Start")
        self.assertLess(gate, bridge)
        self.assertIn("No stream was started", text)
        failed_gate = text.index("if (-not $gameplayProof.Ready)")
        stop_existing = text.index("Stop-UnsafeExistingLivehime -Reason $gameplayProof.Reason", failed_gate)
        self.assertLess(failed_gate, stop_existing)
        self.assertLess(stop_existing, bridge)
        helper = text.index("function Stop-UnsafeExistingLivehime")
        helper_stop = text.index("Invoke-LivehimeBridge -Action Stop", helper)
        self.assertLess(helper, helper_stop)
        self.assertIn('if ($liveState -eq "Streaming")', text)
        self.assertIn('if ($state -ne "Idle")', text)
        # A pre-existing stream is checked and, when unsafe, stopped before the
        # unified stack startup can take any time.
        early_probe = text.index("$existingProof = Get-AscendLiveGameplayProof")
        early_stop = text.index("Stop-UnsafeExistingLivehime -Reason $existingProof.Reason", early_probe)
        self.assertLess(early_probe, early_stop)
        self.assertLess(early_stop, text.index("& $startAgent"))
        state_read = text.index("$liveState = Get-LivehimeStreamingState")
        should_process = text.index("$PSCmdlet.ShouldProcess")
        self.assertLess(should_process, state_read)
        self.assertLess(state_read, text.index("& $startAgent"))

    def test_gameplay_proof_rejects_menu_and_accepts_progressing_fixture(self) -> None:
        """Exercise the pure validator through PowerShell AST extraction.

        Extracting only the function keeps this test read-only: no Start-Agent,
        Livehime task, game process, or UAC path is invoked.
        """
        import json
        import tempfile

        escaped = str(START).replace("'", "''")
        with tempfile.TemporaryDirectory(prefix="bilibili-gameplay-proof-") as raw:
            root = pathlib.Path(raw)
            session = {"session_id": "a" * 32, "state": "running"}
            api = {
                "Port": 8080,
                "Data": {
                    "screen": "COMBAT", "run_id": "RUN-42", "turn": 2,
                    "state_version": 12,
                    "available_actions": ["play_card"],
                    "run": {"floor": 3, "current_hp": 40, "gold": 99,
                            "character_id": "IRONCLAD"},
                },
            }
            now = "2026-09-01T08:00:10Z"
            dashboard = {
                "schema": "sts2.ascend-live/v1", "session_id": "a" * 32,
                "heartbeat": "2026-09-01T08:00:09Z",
                "connection": {
                    "status": "connected", "at": "2026-09-01T08:00:09Z",
                },
                "run": {
                    "run_id": "RUN-42", "screen": "COMBAT", "floor": 3,
                    "character_id": "IRONCLAD",
                },
                "decision": {
                    "decision_id": "d-1", "status": "applied",
                    "selected": {"action": "play_card"},
                    "outcome": {"status": "applied", "at": "2026-09-01T08:00:09Z"},
                },
            }
            proposed_dashboard = json.loads(json.dumps(dashboard))
            proposed_dashboard["decision"]["status"] = "proposed"
            proposed_dashboard["decision"]["outcome"] = {
                "status": "proposed", "at": "2026-09-01T08:00:09Z",
            }
            disconnected_dashboard = json.loads(json.dumps(dashboard))
            disconnected_dashboard["connection"]["status"] = "disconnected"
            menu_api = json.loads(json.dumps(api))
            menu_api["Data"]["screen"] = "MAIN_MENU"
            menu_api["Data"]["run_id"] = "run_unknown"
            menu_api["Data"]["run"] = None
            fixtures = {
                "session": session, "api": api, "menu": menu_api,
                "dashboard": dashboard, "proposed": proposed_dashboard,
                "disconnected": disconnected_dashboard,
            }
            paths = {}
            for name, value in fixtures.items():
                path = root / f"{name}.json"
                path.write_text(json.dumps(value), encoding="utf-8")
                paths[name] = str(path).replace("'", "''")
            command = (
                "$tokens=$null;$errors=$null;"
                f"$ast=[Management.Automation.Language.Parser]::ParseFile('{escaped}',"
                "[ref]$tokens,[ref]$errors);"
                "$defs=@('$script:GameplayPassiveScreens=@(\"\", \"UNKNOWN\", "
                "\"WAITING\", \"TITLE\", \"MAIN_MENU\", \"CHARACTER_SELECT\", "
                "\"PROFILE_SELECT\", \"RUN_HISTORY\", \"CREDITS\", \"GAME_OVER\", "
                "\"VICTORY\", \"RUN_COMPLETE\");',"
                "'$script:GameplayDecisionStatuses=@(\"applied\");');"
                "$names=@('Get-AscendProperty','Test-AscendRunId',"
                "'ConvertTo-AscendUtcTimestamp','New-AscendGameplayProof',"
                "'Test-AscendLiveGameplayProof');"
                "foreach($name in $names){"
                "$fn=$ast.Find({param($n)$n -is "
                "[Management.Automation.Language.FunctionDefinitionAst] "
                "-and $n.Name -eq $name},$true);"
                "if($null -eq $fn){throw ('missing function: '+$name)};"
                "$defs += $fn.Extent.Text};"
                ". ([scriptblock]::Create(($defs -join [Environment]::NewLine)));"
                f"$s=Get-Content -Raw -LiteralPath '{paths['session']}'|ConvertFrom-Json;"
                f"$a=Get-Content -Raw -LiteralPath '{paths['api']}'|ConvertFrom-Json;"
                f"$d=Get-Content -Raw -LiteralPath '{paths['dashboard']}'|ConvertFrom-Json;"
                "$ok=Test-AscendLiveGameplayProof -Session $s -ApiState $a -Dashboard $d "
                f"-NowUtc ([DateTimeOffset]::Parse('{now}'));"
                "$m=Get-Content -Raw -LiteralPath '" + paths["menu"] + "'|ConvertFrom-Json;"
                "$bad=Test-AscendLiveGameplayProof -Session $s -ApiState $m -Dashboard $d "
                f"-NowUtc ([DateTimeOffset]::Parse('{now}'));"
                f"$p=Get-Content -Raw -LiteralPath '{paths['proposed']}'|ConvertFrom-Json;"
                "$stalled=Test-AscendLiveGameplayProof -Session $s -ApiState $a -Dashboard $p "
                f"-NowUtc ([DateTimeOffset]::Parse('{now}'));"
                f"$c=Get-Content -Raw -LiteralPath '{paths['disconnected']}'|ConvertFrom-Json;"
                "$disconnected=Test-AscendLiveGameplayProof -Session $s -ApiState $a -Dashboard $c "
                f"-NowUtc ([DateTimeOffset]::Parse('{now}'));"
                "'{0}:{1}:{2}:{3}:{4}' -f $ok.Ready,$bad.Ready,$stalled.Ready,"
                "$disconnected.Ready,$bad.Reason"
            )
            result = run_powershell(command)
            self.assertEqual(result.returncode, 0, result.stderr)
            fields = result.stdout.strip().split(":", 4)
            self.assertEqual(fields[0:4], ["True", "False", "False", "False"])
            self.assertIn("不是实际对局", fields[4])

    def test_progress_uses_distinct_applied_receipts_not_state_version_increment(self) -> None:
        escaped = str(START).replace("'", "''")
        command = (
            "$tokens=$null;$errors=$null;"
            f"$ast=[Management.Automation.Language.Parser]::ParseFile('{escaped}',"
            "[ref]$tokens,[ref]$errors);"
            "$names=@('Get-AscendProperty','Test-AscendRunId',"
            "'ConvertTo-AscendUtcTimestamp','New-AscendGameplayProof',"
            "'Test-AscendAppliedActionProgress');"
            "$defs=@();foreach($name in $names){"
            "$fn=$ast.Find({param($n)$n -is "
            "[Management.Automation.Language.FunctionDefinitionAst] "
            "-and $n.Name -eq $name},$true);"
            "if($null -eq $fn){throw ('missing function: '+$name)};"
            "$defs += $fn.Extent.Text};"
            ". ([scriptblock]::Create(($defs -join [Environment]::NewLine)));"
            "$common=@{Ready=$true;Reason='ok';SessionId=('a'*32);RunId='RUN-42';"
            "Screen='COMBAT';ApiPort=8080;Action='play_card';StateVersion='15'};"
            "$first=New-AscendGameplayProof @common -DecisionId 'd-1' "
            "-OutcomeAt '2026-09-01T08:00:09Z';"
            "$same=New-AscendGameplayProof @common -DecisionId 'd-1' "
            "-OutcomeAt '2026-09-01T08:00:10Z';"
            "$new=New-AscendGameplayProof @common -DecisionId 'd-2' "
            "-OutcomeAt '2026-09-01T08:00:10Z';"
            "$sameTime=New-AscendGameplayProof @common -DecisionId 'd-2' "
            "-OutcomeAt '2026-09-01T08:00:09Z';"
            "$otherRun=New-AscendGameplayProof @common -RunId 'RUN-43' "
            "-DecisionId 'd-2' -OutcomeAt '2026-09-01T08:00:10Z';"
            "'{0}:{1}:{2}:{3}' -f "
            "(Test-AscendAppliedActionProgress $first $new),"
            "(Test-AscendAppliedActionProgress $first $same),"
            "(Test-AscendAppliedActionProgress $first $sameTime),"
            "(Test-AscendAppliedActionProgress $first $otherRun)"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True:False:False:False")

    def test_wait_preserves_first_applied_receipt_across_transient_states(self) -> None:
        escaped = str(START).replace("'", "''")
        command = (
            "$tokens=$null;$errors=$null;"
            f"$ast=[Management.Automation.Language.Parser]::ParseFile('{escaped}',"
            "[ref]$tokens,[ref]$errors);"
            "$names=@('Get-AscendProperty','Test-AscendRunId',"
            "'ConvertTo-AscendUtcTimestamp','New-AscendGameplayProof',"
            "'Test-AscendAppliedActionProgress','Wait-AscendLiveGameplayReady');"
            "$defs=@();foreach($name in $names){"
            "$fn=$ast.Find({param($n)$n -is "
            "[Management.Automation.Language.FunctionDefinitionAst] "
            "-and $n.Name -eq $name},$true);"
            "if($null -eq $fn){throw ('missing function: '+$name)};"
            "$defs += $fn.Extent.Text};"
            ". ([scriptblock]::Create(($defs -join [Environment]::NewLine)));"
            "$common=@{Ready=$true;Reason='ok';SessionId=('a'*32);RunId='RUN-42';"
            "Screen='COMBAT';ApiPort=8080;Action='play_card';StateVersion='15'};"
            "$first=New-AscendGameplayProof @common -DecisionId 'd-1' "
            "-OutcomeAt '2026-09-01T08:00:09Z';"
            "$transient=New-AscendGameplayProof -Ready $false -Reason 'proposed';"
            "$second=New-AscendGameplayProof @common -DecisionId 'd-2' "
            "-OutcomeAt '2026-09-01T08:00:10Z';"
            "$script:proofs=@($first,$transient,$second);$script:proofIndex=0;"
            "function Get-AscendLiveGameplayProof {param($ProjectRoot,$MaxAgeSeconds);"
            "$i=[Math]::Min($script:proofIndex,$script:proofs.Count-1);"
            "$script:proofIndex++;return $script:proofs[$i]};"
            "$result=Wait-AscendLiveGameplayReady -ProjectRoot '.' -TimeoutSeconds 5;"
            "'{0}:{1}' -f $result.Ready,$result.DecisionId"
        )
        result = run_powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "True:d-2")

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
        self.assertIn("Set-SlayTheSpireTopMost", worker)
        self.assertIn("Set-AscendViewerTopMost -ProjectRoot $ProjectRoot", worker)
        self.assertIn('"bridge-worker.log"', worker)
        self.assertIn("action_error=", worker)
        self.assertIn("restoration_error=", worker)
        self.assertIn("Length -gt 1048576", worker)
        self.assertIn("Test-LivehimeDisplayCaptureStale", worker)
        self.assertIn("Restart-LivehimeIdle", worker)
        self.assertLess(worker.index("Invoke-LivehimeStart"), worker.index("Set-SlayTheSpireTopMost"))
        self.assertLess(worker.index("Set-SlayTheSpireTopMost"), worker.index("ReleaseMutex"))
        self.assertNotIn("Start-Agent.ps1", worker)
        self.assertIn("BilibiliLive-DailyStart", installer)
        self.assertIn("Invoke-BilibiliLiveDailyStart.ps1", installer)
        self.assertIn("BilibiliLive-DailyStopWatch", installer)
        self.assertIn("Invoke-BilibiliLiveDailyStopWatch.ps1", installer)

    def test_operational_path_has_no_web_api_or_obs_transport(self) -> None:
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                MODULE, INSTALL, WORKER, DAILY_START, DAILY_STOP, HEALTH_WATCH,
                START, STOP, SMOKE
            )
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
        self.assertIn("23:00", text)
        self.assertIn("23:20", text)
        self.assertIn("11:00", text)
        self.assertIn("11:20", text)
        self.assertNotIn("16:00", text)
        self.assertIn("BilibiliLive-DailyStopWatch", text)
        self.assertIn("display/monitor capture", text)
        self.assertIn("Never replace it with game/window capture", text)
        self.assertIn("Before causing the UAC prompt", text)
        self.assertIn("One requested install attempt means one UAC prompt", text)
        self.assertIn("full `StartBoundary` date", text)
        self.assertIn("Never install or repair the protected bridge during a broadcast", text)

    def test_public_bridge_waits_for_protected_restoration(self) -> None:
        text = MODULE.read_text(encoding="utf-8")
        start = text.index("function Invoke-LivehimeBridge")
        end = text.index("function Get-SlayTheSpireWindow", start)
        body = text[start:end]
        self.assertIn("$alreadyDesired", body)
        self.assertNotIn('already $($desiredState.ToLowerInvariant())."\n        return', body)
        self.assertIn("$previousLastRunTime", body)
        self.assertIn("$currentRunObserved", body)
        self.assertIn("$info.LastTaskResult -ne 0", body)
        self.assertLess(body.index("Start-ScheduledTask"), body.index("$currentRunObserved"))


if __name__ == "__main__":
    unittest.main()
