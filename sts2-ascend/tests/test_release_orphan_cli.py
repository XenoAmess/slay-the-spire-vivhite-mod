"""Operator CLI stays read-only by default and never crosses the action API."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import io
import importlib.util
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_orphan_run.py"
SPEC = importlib.util.spec_from_file_location("release_orphan_run_cli", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


RUN_ID = "orphan-cli-v"
CHARACTER_ID = "VIVHITE_CHARACTER_VIVHITE_CHARACTER"


def _evidence(run_id: str = RUN_ID) -> dict:
    return {
        "version": cli.ORPHAN_EVIDENCE_VERSION,
        "reason": cli.ORPHAN_RELEASE_REASON,
        "run_id": run_id,
        "character_id": CHARACTER_ID,
        "observed_at": "2026-09-01T15:50:00Z",
        "api": {
            "consecutive": True,
            "samples": [
                {
                    "sequence": 1,
                    "observed_at": "2026-09-01T15:50:01Z",
                    "state_version": 13,
                    "screen": "MAIN_MENU",
                    "run_id": "run_unknown",
                    "run_empty": True,
                    "continue_run": False,
                },
                {
                    "sequence": 2,
                    "observed_at": "2026-09-01T15:50:02Z",
                    "state_version": 13,
                    "screen": "MAIN_MENU",
                    "run_id": "run_unknown",
                    "run_empty": True,
                    "continue_run": False,
                },
            ],
        },
        "native": {
            "probe_complete": True,
            "save": {"status": "no_matching_run"},
            "save_backup": {"status": "absent"},
            "history": {"status": "empty"},
            "stmp": {"status": "zero_byte"},
            "save_match": False,
            "history_match": False,
            "read_errors": [],
            "checked_paths": [
                {"kind": "progress.save", "status": "no_matching_run",
                 "path": "profile1/saves/progress.save", "bytes": 12},
                {"kind": "current_run.save.backup", "status": "absent",
                 "path": "profile1/saves/current_run.save.backup", "bytes": 0},
                {"kind": "history", "status": "empty",
                 "path": "profile1/saves/history", "bytes": 0, "files": 0},
                {"kind": "stmp", "status": "zero_byte",
                 "path": "profile1/saves/history/old.stmp", "bytes": 0},
            ],
        },
    }


def _rotation(root: Path, *, active: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    runtime = root.parent / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "lifecycle.lock").touch()
    state = {
        "version": 2,
        "next_character": "VIVHITE",
        "schedule_mode": "catchup_4_to_1",
        "catchup_index": 2,
        "catchup_completed": False,
        "last_completed_character": "VIVHITE",
        "active_run": ({
            "run_id": RUN_ID,
            "character": "VIVHITE",
            "character_id": CHARACTER_ID,
            "scheduled_character": "VIVHITE",
        } if active else None),
        "finalized_runs": {},
        "orphaned_runs": {} if active else {
            RUN_ID: {
                "run_id": RUN_ID,
                "character": "VIVHITE",
                "character_id": CHARACTER_ID,
                "reason": cli.ORPHAN_RELEASE_REASON,
                "released_at": "2026-09-01T15:51:00Z",
                "evidence": _evidence(),
            },
        },
    }
    path = root / "character_rotation.json"
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _bound_capture(evidence: dict, runtime: Path, *, session_id: str = "a" * 32) -> dict:
    """Attach a fresh-looking capture and matching Stop-Agent sentinel."""
    now = time.time() - 1.0
    captured_at = datetime.fromtimestamp(now, timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")
    stop = runtime / f"stop.{session_id}.request"
    evidence = copy.deepcopy(evidence)
    evidence["capture"] = {
        "schema": cli.CAPTURE_SCHEMA,
        "mode": "api-native-readonly",
        "captured_at": captured_at,
        "captured_unix": now,
        "stack_stopped": False,
        "session_id": session_id,
        "stop_file": str(stop),
    }
    stop.write_text(json.dumps({
        "session_id": session_id,
        "requested_at": datetime.now(timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z"),
        "source": "Stop-Agent.ps1",
    }), encoding="utf-8")
    return evidence


class ReleaseOrphanCliTests(unittest.TestCase):
    def test_stack_guard_rejects_live_session_without_touching_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orphan-cli-guard-") as raw:
            runtime = Path(raw) / ".runtime"
            runtime.mkdir()
            (runtime / "lifecycle.lock").touch()
            session = runtime / "session.json"
            session.write_text('{"session_id":"test"}', encoding="utf-8")
            with self.assertRaises(cli.OrphanCliError):
                cli.assert_stack_stopped(runtime)
            self.assertTrue(session.exists())

    def test_preview_validates_and_does_not_write_rotation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orphan-cli-preview-") as raw:
            root = Path(raw)
            knowledge = root / "knowledge"
            rotation_path = _rotation(knowledge)
            before = rotation_path.read_bytes()
            evidence_path = root / "evidence.json"
            evidence_path.write_text(
                json.dumps(_evidence(), ensure_ascii=False), encoding="utf-8")
            args = cli.build_parser().parse_args([
                "--stack-root", str(root),
                "--runtime-dir", str(root / ".runtime"),
                "--knowledge-root", str(knowledge),
                "--evidence-file", str(evidence_path),
            ])
            code, payload = cli.run_once(args)
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["applied"])
            self.assertEqual(rotation_path.read_bytes(), before)

    def test_apply_rejects_unbound_file_evidence_for_active_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orphan-cli-apply-") as raw:
            root = Path(raw)
            knowledge = root / "knowledge"
            _rotation(knowledge)
            evidence_path = root / "evidence.json"
            evidence_path.write_text(
                json.dumps(_evidence(), ensure_ascii=False), encoding="utf-8")
            args = cli.build_parser().parse_args([
                "--stack-root", str(root),
                "--runtime-dir", str(root / ".runtime"),
                "--knowledge-root", str(knowledge),
                "--evidence-file", str(evidence_path),
                "--run-id", RUN_ID,
                "--apply",
            ])
            with mock.patch.object(cli, "release_orphan_run_once",
                                   side_effect=AssertionError("must reject stale evidence")) as apply:
                code, payload = cli.run_once(args)
            self.assertEqual(code, 2)
            self.assertFalse(payload["applied"])
            self.assertIn("session-bound", payload["error"]["message"])
            apply.assert_not_called()

    def test_auto_probe_uses_get_state_only_and_rejects_noisy_binary(self) -> None:
        class FakeClient:
            calls: list[str] = []

            def __init__(self, *args, **kwargs):
                self.calls.append("init")

            def discover(self):
                self.calls.append("discover")
                return "http://127.0.0.1:8080"

            def state(self):
                self.calls.append("state")
                return {
                    "screen": "MAIN_MENU",
                    "run_id": "run_unknown",
                    "run": None,
                    "state_version": 13,
                    "available_actions": ["open_character_select"],
                }

            def available_actions(self):
                self.calls.append("available_actions")
                return [{"name": "open_character_select"}]

            def act(self, *args, **kwargs):  # pragma: no cover - must not run
                raise AssertionError("automatic orphan probe must never POST /action")

        with tempfile.TemporaryDirectory(prefix="orphan-cli-probe-") as raw:
            root = Path(raw)
            save_root = root / "profile1" / "saves"
            save_root.mkdir(parents=True)
            save = save_root / "current_run.save"
            save.write_text("{}", encoding="utf-8")
            backup = save_root / "current_run.save.backup"
            history = save_root / "history"
            history.mkdir()
            (history / "old.run").write_text("{}", encoding="utf-8")
            with mock.patch.object(cli, "Sts2Client", FakeClient), \
                    mock.patch.object(cli.time, "sleep"):
                evidence, url = cli.collect_api_evidence(
                    RUN_ID, CHARACTER_ID, ports=(8080,), delay=1.0,
                    save_path=save, history_path=history)
            self.assertEqual(url, "http://127.0.0.1:8080")
            self.assertEqual(FakeClient.calls.count("state"), 2)
            self.assertNotIn("act", FakeClient.calls)
            self.assertFalse(evidence["native"]["probe_complete"])
            self.assertFalse(evidence["native"]["save_match"])

            binary = root / "opaque.save"
            binary.write_bytes(b"\x00\xff\x00\x81")
            native = cli.collect_native_evidence(
                RUN_ID, save_path=binary, history_path=history)
            self.assertFalse(native["probe_complete"])
            self.assertTrue(native["read_errors"])

    def test_missing_lifecycle_lock_fails_closed_without_creating_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orphan-cli-lock-") as raw:
            runtime = Path(raw) / ".runtime"
            runtime.mkdir()
            with self.assertRaises(cli.OrphanCliError):
                with cli.lifecycle_lock(runtime):
                    pass
            self.assertFalse((runtime / "lifecycle.lock").exists())

    def test_lifecycle_lock_is_not_reentrant_across_operations(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orphan-cli-lock-held-") as raw:
            runtime = Path(raw) / ".runtime"
            runtime.mkdir()
            (runtime / "lifecycle.lock").touch()
            with cli.lifecycle_lock(runtime):
                with self.assertRaises(cli.OrphanCliError):
                    with cli.lifecycle_lock(runtime):
                        pass

    def test_state_probe_rejects_empty_object_and_endpoint_mismatch(self) -> None:
        class FakeClient:
            def __init__(self, *args, **kwargs):
                self.bad_endpoint = kwargs.pop("bad_endpoint", False)
                self.n = 0

            def discover(self):
                return "http://127.0.0.1:8080"

            def state(self):
                self.n += 1
                return {
                    "screen": "MAIN_MENU",
                    "run_id": "run_unknown",
                    "run": {},  # malformed: null is required
                    "state_version": self.n,
                    "available_actions": ["open_character_select"],
                }

            def available_actions(self):
                return [{"name": "open_character_select"}]

        with self.assertRaises(cli.OrphanCliError):
            with mock.patch.object(cli, "Sts2Client", FakeClient):
                cli.collect_api_evidence(
                    RUN_ID, CHARACTER_ID, ports=(8080,), delay=1.0,
                    save_path=Path("x"), history_path=Path("y"))

        class MismatchClient(FakeClient):
            def state(self):
                self.n += 1
                return {
                    "screen": "MAIN_MENU", "run_id": "run_unknown", "run": None,
                    "state_version": self.n,
                    "available_actions": ["open_character_select"],
                }

            def available_actions(self):
                return [{"name": "open_character_select"}, {"name": "open_timeline"}]

        with self.assertRaises(cli.OrphanCliError):
            with mock.patch.object(cli, "Sts2Client", MismatchClient):
                cli.collect_api_evidence(
                    RUN_ID, CHARACTER_ID, ports=(8080,), delay=1.0,
                    save_path=Path("x"), history_path=Path("y"))

    def test_strict_apply_shape_requires_four_exact_native_classes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orphan-cli-shape-") as raw:
            root = Path(raw)
            saves = root / "profile1" / "saves"
            (saves / "history").mkdir(parents=True)
            evidence = _evidence()
            for sample in evidence["api"]["samples"]:
                sample["run"] = None
            evidence["api"]["latest_state_version"] = 13
            evidence["native"]["probe_observed_at"] = "2026-09-01T15:50:03Z"
            evidence["native"]["api_state_version"] = 13
            evidence["native"]["checked_paths"] = [
                {"kind": "current_run.save", "status": "no_matching_run",
                 "path": str(saves / "current_run.save"), "bytes": 12},
                {"kind": "current_run.save.backup", "status": "absent",
                 "path": str(saves / "current_run.save.backup"), "bytes": 0},
                {"kind": "history", "status": "empty",
                 "path": str(saves / "history"), "bytes": 0, "files": 0},
                {"kind": "stmp", "status": "zero_byte",
                 "path": str(saves / "history" / "old.stmp"), "bytes": 0},
            ]
            cli._validate_probe_shape(evidence, require_capture=False)
            mutations = []
            missing_backup = copy.deepcopy(evidence)
            missing_backup["native"]["checked_paths"].pop(1)
            mutations.append(missing_backup)
            wrong_kind = copy.deepcopy(evidence)
            wrong_kind["native"]["checked_paths"][0]["kind"] = "progress.save"
            mutations.append(wrong_kind)
            wrong_status = copy.deepcopy(evidence)
            wrong_status["native"]["checked_paths"][3]["status"] = "matching_run"
            mutations.append(wrong_status)
            missing_stmp = copy.deepcopy(evidence)
            missing_stmp["native"]["checked_paths"] = missing_stmp["native"]["checked_paths"][:3]
            mutations.append(missing_stmp)
            for mutated in mutations:
                with self.assertRaises(cli.OrphanCliError):
                    cli._validate_probe_shape(mutated, require_capture=False)

    def test_capture_then_stopped_apply_is_session_bound(self) -> None:
        class FakeClient:
            calls: list[str] = []

            def __init__(self, *args, **kwargs):
                self.calls.append("init")

            def discover(self):
                self.calls.append("discover")
                return "http://127.0.0.1:8080"

            def state(self):
                self.calls.append("state")
                return {
                    "screen": "MAIN_MENU", "run_id": "run_unknown", "run": None,
                    "state_version": 13,
                    "available_actions": ["open_character_select"],
                }

            def available_actions(self):
                self.calls.append("available_actions")
                return [{"name": "open_character_select"}]

            def act(self, *args, **kwargs):  # pragma: no cover
                raise AssertionError("capture must not send actions")

        with tempfile.TemporaryDirectory(prefix="orphan-cli-capture-") as raw:
            root = Path(raw)
            knowledge = root / "knowledge"
            _rotation(knowledge)
            runtime = root / ".runtime"
            sid = "b" * 32
            session = {
                "session_id": sid,
                "state": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
                "root": str(root),
                "stop_file": str(runtime / f"stop.{sid}.request"),
            }
            (runtime / "session.json").write_text(
                json.dumps(session), encoding="utf-8")
            save_root = root / "profile1" / "saves"
            (save_root / "history").mkdir(parents=True)
            args = cli.build_parser().parse_args([
                "--stack-root", str(root), "--runtime-dir", str(runtime),
                "--knowledge-root", str(knowledge), "--capture", "--api-port", "8080",
                "--native-save-path", str(save_root / "current_run.save"),
                "--native-save-backup-path", str(save_root / "current_run.save.backup"),
                "--native-history-path", str(save_root / "history"),
                "--native-stmp-path", str(save_root / "history" / "*.stmp"),
            ])
            with mock.patch.object(cli, "Sts2Client", FakeClient), \
                    mock.patch.object(cli.time, "sleep"):
                code, payload = cli.run_once(args)
            self.assertEqual(code, 0)
            self.assertTrue(payload["captured"])
            self.assertFalse(payload["applied"])
            self.assertIn("evidence", payload)
            self.assertNotIn("act", FakeClient.calls)

            evidence_path = root / "capture.json"
            evidence_path.write_text(json.dumps(payload), encoding="utf-8")
            # Stop-Agent's sentinel is the binding boundary; session.json is
            # removed by the stop script before apply.
            (runtime / "session.json").unlink()
            stop = runtime / f"stop.{sid}.request"
            stop.write_text(json.dumps({
                "session_id": sid,
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "source": "Stop-Agent.ps1",
            }), encoding="utf-8")
            tampered = copy.deepcopy(payload)
            tampered["evidence"]["native"]["save"]["status"] = "matching_run"
            evidence_path.write_text(json.dumps(tampered), encoding="utf-8")
            tamper_args = cli.build_parser().parse_args([
                "--stack-root", str(root), "--runtime-dir", str(runtime),
                "--knowledge-root", str(knowledge),
                "--evidence-file", str(evidence_path), "--apply",
            ])
            with mock.patch.object(cli, "release_orphan_run_once",
                                   side_effect=AssertionError("tampered evidence must fail")) as tamper_apply:
                code, tamper_result = cli.run_once(tamper_args)
            self.assertEqual(code, 2)
            self.assertIn("sha256", tamper_result["error"]["message"])
            tamper_apply.assert_not_called()
            evidence_path.write_text(json.dumps(payload), encoding="utf-8")
            expected = mock.Mock(released=True)
            apply_args = cli.build_parser().parse_args([
                "--stack-root", str(root), "--runtime-dir", str(runtime),
                "--knowledge-root", str(knowledge),
                "--evidence-file", str(evidence_path), "--apply",
            ])
            with mock.patch.object(cli, "release_orphan_run_once",
                                   return_value=expected) as apply:
                code, result = cli.run_once(apply_args)
            self.assertEqual(code, 0)
            self.assertTrue(result["applied"])
            apply.assert_called_once()

    def test_preview_allows_exact_idempotent_orphan_replay_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orphan-cli-replay-") as raw:
            root = Path(raw)
            knowledge = root / "knowledge"
            _rotation(knowledge, active=False)
            evidence_path = root / "evidence.json"
            evidence_path.write_text(
                json.dumps(_evidence(), ensure_ascii=False), encoding="utf-8")
            args = cli.build_parser().parse_args([
                "--stack-root", str(root),
                "--runtime-dir", str(root / ".runtime"),
                "--knowledge-root", str(knowledge),
                "--evidence-file", str(evidence_path),
            ])
            code, payload = cli.run_once(args)
            self.assertEqual(code, 0)
            self.assertTrue(payload["idempotent_replay"])
            self.assertFalse(payload["would_apply"])

    def test_evidence_can_be_read_from_stdin_without_writing_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="orphan-cli-stdin-") as raw:
            root = Path(raw)
            knowledge = root / "knowledge"
            _rotation(knowledge)
            args = cli.build_parser().parse_args([
                "--stack-root", str(root),
                "--runtime-dir", str(root / ".runtime"),
                "--knowledge-root", str(knowledge),
                "--evidence-file", "-",
            ])
            with mock.patch.object(
                    cli.sys, "stdin",
                    io.StringIO(json.dumps(_evidence(), ensure_ascii=False))):
                code, payload = cli.run_once(args)
            self.assertEqual(code, 0)
            self.assertEqual(payload["evidence_source"], "stdin")
            self.assertFalse(payload["applied"])


if __name__ == "__main__":
    unittest.main()
