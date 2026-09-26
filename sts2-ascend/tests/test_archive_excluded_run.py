"""Exact-byte recovery of historical excluded runs, never synthetic completion."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import nullcontext
from pathlib import Path
from unittest import mock


STACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STACK / "brain"))
sys.path.insert(0, str(STACK / "scripts"))

import archive_excluded_run as archive  # noqa: E402
import autogit  # noqa: E402
import compact_knowledge as compact  # noqa: E402
import knowledge  # noqa: E402


class ExcludedRunArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-excluded-archive-")
        self.root = Path(self.temp.name)
        self.runtime = self.root / ".runtime"
        self.runtime.mkdir()
        (self.runtime / "lifecycle.lock").touch()
        (self.root / "runs").mkdir()
        self.source = self.root / "runs" / "20260918-010416_OLD.json"
        self.payload = {
            "run_id": "OLD", "run_number": 1300, "profile_id": "vivhite",
            "started_at": "2026-09-18 01:04:16", "in_progress": True,
            "human_assisted": True, "excluded_from_learning": True,
            "decisions": [{"screen": "REWARDS", "floor": 13,
                           "action": "skip_reward_cards", "reason": "跳过"}] * 16,
        }
        self.source.write_bytes((json.dumps(self.payload, ensure_ascii=False, indent=2)
                                 + "\r\n").encode("utf-8"))
        self.raw = self.source.read_bytes()
        self.state = {"run_id": "CURRENT", "run": {"run_id": "CURRENT"},
                      "state_version": 123, "native_profile_id": 1, "screen": "COMBAT"}
        self.patches = [
            mock.patch.object(archive, "_observe_current_run", return_value=self.state),
            mock.patch.object(compact, "_active_reasons", return_value=[]),
            mock.patch.object(autogit, "repository_lock", side_effect=lambda **kw: nullcontext()),
            mock.patch.object(archive, "_runtime_dir", return_value=self.runtime),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.temp.cleanup()

    def apply(self, **kwargs):
        return archive.archive_excluded_run(self.root, filename=self.source.name,
                                            run_id="OLD", current_run_id="CURRENT",
                                            apply=kwargs.pop("apply", True), **kwargs)

    def test_stopped_persisted_review_queue_is_allowed_without_editing_it(self):
        session = "1" * 32
        queue = self.root / "review_queue.json"
        queue.write_bytes(b'{"reviewing": true}\r\n')
        (self.runtime / f"stop.{session}.request").write_text(json.dumps({
            "session_id": session, "source": "Stop-Agent.ps1", "requested_at": "2026-09-26"}),
            encoding="utf-8")
        with mock.patch.object(compact, "_active_reasons", return_value=[
                "review_queue.json has an active reviewing batch"]):
            with self.assertRaisesRegex(RuntimeError, "active stack"):
                self.apply()
            self.assertTrue(self.apply(stopped_session_id=session)["source_removed"])
        self.assertEqual(queue.read_bytes(), b'{"reviewing": true}\r\n')

    def test_stop_exemption_never_waives_live_pid_flag_session_or_bad_marker(self):
        session = "1" * 32
        (self.runtime / f"stop.{session}.request").write_text(json.dumps({
            "session_id": session, "source": "Stop-Agent.ps1", "requested_at": "2026-09-26"}),
            encoding="utf-8")
        queue_reason = "review_queue.json has an active reviewing batch"
        for blocker in ("knowledge/review_active.flag exists", "live lifecycle pid 17 (brain.pid)"):
            with mock.patch.object(compact, "_active_reasons", return_value=[queue_reason, blocker]):
                with self.assertRaisesRegex(RuntimeError, "active stack"):
                    self.apply(stopped_session_id=session)
        for name, raw in (("session.json", b"{}"), ("brain.pid", b"malformed"),
                          ("brain.pid", b'{"pid":17}')):
            path = self.runtime / name
            path.write_bytes(raw)
            with (mock.patch.object(compact, "_active_reasons", return_value=[queue_reason]),
                  mock.patch.object(compact, "_pid_alive", return_value=True)):
                with self.assertRaisesRegex(RuntimeError, "active stack"):
                    self.apply(stopped_session_id=session)
            path.unlink()
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_dry_run_leaves_every_byte_untouched(self):
        result = self.apply(apply=False)
        self.assertEqual(result["mode"], "dry-run")
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertFalse((self.root / "archive").exists())

    def test_round_trip_retains_excluded_in_progress_bytes_and_preserves_learning(self):
        learning = self.root / "stats.json"
        learning.write_bytes(b'{"do_not_change": 17}\r\n')
        result = self.apply()
        self.assertTrue(result["source_removed"])
        self.assertFalse(self.source.exists())
        self.assertEqual(compact.read_run_evidence(self.root, self.source.name), self.raw)
        self.assertEqual(learning.read_bytes(), b'{"do_not_change": 17}\r\n')
        with zipfile.ZipFile(result["archive"]) as zf:
            self.assertEqual(set(zf.namelist()), {
                f"runs/{self.source.name}", "metadata/selection.json"})
        row = next(json.loads(line) for line in (self.root / compact.CATALOG_REL)
                   .read_text("utf-8").splitlines() if '"file"' in line)
        self.assertTrue(row["in_progress"])
        self.assertTrue(row["human_assisted"])
        self.assertTrue(row["excluded_from_learning"])
        self.assertEqual(compact.read_catalog_storage_evidence(self.root, row), self.raw)
        self.assertFalse(self.apply()["changed"])

    def test_current_run_or_missing_exclusion_is_rejected(self):
        for change in ({"run_id": "DIFFERENT"}, {"human_assisted": False},
                       {"excluded_from_learning": False}):
            self.source.write_text(json.dumps({**self.payload, **change}), encoding="utf-8")
            with self.assertRaises(RuntimeError):
                self.apply()
            self.assertTrue(self.source.exists())
            self.assertFalse((self.root / compact.MANIFEST_REL).exists())

    def test_live_stack_does_not_mutate(self):
        with mock.patch.object(compact, "_active_reasons", return_value=["live brain"]):
            with self.assertRaisesRegex(RuntimeError, "active stack"):
                self.apply()
        self.assertEqual(self.source.read_bytes(), self.raw)
        self.assertFalse((self.root / compact.MANIFEST_REL).exists())

    def test_source_changed_while_compressing_is_not_removed_or_published(self):
        build = archive._build_archive

        def changing_build(*args):
            result = build(*args)
            self.source.write_bytes(self.raw + b" ")
            return result

        with mock.patch.object(archive, "_build_archive", side_effect=changing_build):
            with self.assertRaisesRegex(RuntimeError, "run changed"):
                self.apply()
        self.assertTrue(self.source.exists())
        self.assertFalse((self.root / compact.MANIFEST_REL).exists())

    def test_catalog_failure_preserves_source_and_retry_reuses_verified_archive(self):
        with mock.patch.object(compact, "_write_if_changed", side_effect=OSError("catalog busy")):
            with self.assertRaisesRegex(OSError, "catalog busy"):
                self.apply()
        self.assertTrue(self.source.exists())
        with mock.patch.object(archive, "_build_archive", side_effect=AssertionError("must reuse")):
            self.assertTrue(self.apply()["source_removed"])
        self.assertEqual(compact.read_run_evidence(self.root, self.source.name), self.raw)

    def test_corrupt_archive_never_releases_source_or_becomes_missing_history(self):
        result = self.apply()
        Path(result["archive"]).write_bytes(b"not a zip")
        know = object.__new__(knowledge.Knowledge)
        know.root = self.root
        with self.assertRaises(RuntimeError):
            know.load_run_log("OLD")
        self.source.write_bytes(self.raw)
        with self.assertRaises(RuntimeError):
            self.apply()
        self.assertEqual(self.source.read_bytes(), self.raw)

    def test_source_change_after_catalog_publication_is_preserved(self):
        publish = compact._write_if_changed

        def changing_publish(path, raw):
            result = publish(path, raw)
            if path == self.root / compact.CATALOG_REL:
                self.source.write_bytes(self.raw + b" ")
            return result

        with mock.patch.object(compact, "_write_if_changed", side_effect=changing_publish):
            with self.assertRaisesRegex(RuntimeError, "run changed before removal"):
                self.apply()
        self.assertEqual(self.source.read_bytes(), self.raw + b" ")
        self.assertEqual(compact.read_archived_run(self.root, "OLD"), self.payload)

    def test_knowledge_load_fallback_preserves_identity_and_active_priority(self):
        self.apply()
        know = object.__new__(knowledge.Knowledge)
        know.root = self.root
        self.assertEqual(know.load_run_log("OLD"), self.payload)
        self.assertIsNone(know.load_run_log("DIFFERENT"))
        current = {**self.payload, "resumed_marker": True}
        self.source.write_text(json.dumps(current), encoding="utf-8")
        self.assertEqual(know.load_run_log("OLD"), current)

    def test_manifest_identity_cannot_substitute_other_raw_run(self):
        self.apply()
        path = self.root / compact.MANIFEST_REL
        manifest = json.loads(path.read_text("utf-8"))
        manifest["batches"][0]["runs"][0]["run_id"] = "FORGED"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "identity verification"):
            compact.read_archived_run(self.root, "FORGED")


class CurrentRunObservationTests(unittest.TestCase):
    def observe(self, state, **kwargs):
        envelope = kwargs.get("envelope", {"ok": True, "data": state})
        with mock.patch.object(archive.urllib.request, "urlopen", return_value=io.BytesIO(
                json.dumps(envelope).encode("utf-8"))):
            return archive._observe_current_run(kwargs.get("api_url", "http://127.0.0.1:8080"),
                                                "OLD", kwargs.get("current_run_id", "CURRENT"))

    def test_real_current_run_is_verified_against_api(self):
        state = {"run": {"run_id": "CURRENT"}, "state_version": 31}
        self.assertEqual(self.observe(state)["run_id"], "CURRENT")
        for changed in ({"run": None}, {"state_version": "31"}, {"state_version": True},
                        {"state_version": float("nan")}, {"state_version": -1},
                        {"run_id": "OLD"}, {"run_id": "OTHER"}):
            with self.assertRaises(RuntimeError):
                self.observe({**state, **changed})
        for kwargs in ({"current_run_id": "OLD"}, {"current_run_id": "run_unknown"},
                       {"api_url": "https://example.com"}):
            with self.assertRaises(ValueError):
                self.observe(state, **kwargs)

    def test_failed_or_malformed_api_envelope_never_counts_as_current_run(self):
        state = {"run": {"run_id": "CURRENT"}, "state_version": 31}
        for envelope in ({"ok": False, "error": {"code": "waiting"}, "data": state},
                         {"ok": "true", "data": state}, {"ok": 1, "data": state},
                         {"ok": True, "data": None}, state):
            with self.assertRaises(RuntimeError):
                self.observe(state, envelope=envelope)


if __name__ == "__main__":
    unittest.main()
