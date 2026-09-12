"""Online history publication, retention, byte preservation and crash recovery."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock


STACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(STACK / "brain"))
sys.path.insert(0, str(STACK / "scripts"))

import autogit  # noqa: E402
import compact_knowledge as compact  # noqa: E402
import compact_run_history as online  # noqa: E402


class OnlineRunArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-online-archive-")
        self.root = Path(self.temp.name)
        (self.root / "runs").mkdir()
        self.locked = False

        @contextmanager
        def publication_lock(**kwargs):
            self.assertFalse(self.locked)
            self.locked = True
            try:
                yield
            finally:
                self.locked = False

        self.lock_patch = mock.patch.object(autogit, "repository_lock", publication_lock)
        self.lock_patch.start()

    def tearDown(self) -> None:
        self.lock_patch.stop()
        self.temp.cleanup()

    def write_run(self, name="20260801-old.json", **changes) -> Path:
        payload = {
            "run_id": name, "run_number": 1, "started_at": "2026-08-01 12:00:00",
            "in_progress": False, "victory": True, "floor": 49,
            "decisions": [{"screen": "GAME_OVER", "floor": 49}],
        }
        payload.update(changes)
        path = self.root / "runs" / name
        path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\r\n").encode("utf-8"))
        return path

    def apply(self, **kwargs) -> dict:
        return online.apply_run_archive(self.root, archive_before="2026-09-01",
                                        keep_recent=kwargs.pop("keep_recent", 0), **kwargs)

    def catalog(self) -> dict:
        return {row["file"]: row
                for line in (self.root / compact.CATALOG_REL).read_text(encoding="utf-8").splitlines()
                if "file" in (row := json.loads(line))}

    def test_selection_is_date_bounded_and_preserves_recent_active_and_anomalies(self):
        old = self.write_run()
        kept = [
            self.write_run("20260802-active.json", in_progress=True),
            self.write_run("20260803-human.json", human_assisted=True),
            self.write_run("20260804-excluded.json", excluded_from_learning=True),
            self.write_run("20260805-orphan.json", orphaned=True),
            self.write_run("20260806-empty.json", decisions=[]),
            self.write_run("20260807-undated.json", started_at=None),
            self.write_run("20260901-boundary.json", started_at="2026-09-01T00:00:00"),
            self.write_run("zz-recent.json"),
        ]
        malformed = self.root / "runs" / "invalid.json"
        malformed.write_bytes(b"{malformed")
        plan = online.plan_run_archive(self.root, archive_before="2026-09-01", keep_recent=1)
        self.assertEqual([r.path for r in plan.archive_new], [old])
        self.assertTrue(all(path.name in plan.keep_reasons for path in [*kept, malformed]))
        self.assertEqual(plan.markdown, [])
        self.assertEqual(plan.profile_plans, [])

    def test_apply_stays_online_and_publishes_catalog_before_deletion(self):
        old = self.write_run()
        original = old.read_bytes()
        active = self.write_run("20260912-active.json", started_at="2026-09-12", in_progress=True)
        preserved = {}
        for name in ("stats.json", "policy.json", "progression.json", "lessons.md",
                     "meta_review.md", "review_queue.json", ".runtime/session.json",
                     "profile_reset_archives/old/runs/frozen.json"):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"untouched original bytes\r\n")
            preserved[path] = path.read_bytes()
        original_build = online._build_archive
        original_unlink = Path.unlink

        def build(plan):
            self.assertFalse(self.locked, "compression must not hold repository lock")
            return original_build(plan)

        def unlink(path, *args, **kwargs):
            if path == old:
                self.assertTrue(self.locked)
                row = self.catalog()[old.name]
                self.assertEqual(row["storage"]["kind"], "zip")
                self.assertEqual(compact.read_catalog_storage_evidence(self.root, row), original)
                self.assertTrue((self.root / compact.MANIFEST_REL).exists())
            return original_unlink(path, *args, **kwargs)

        with (mock.patch.object(online, "_build_archive", side_effect=build),
              mock.patch.object(Path, "unlink", unlink),
              mock.patch.object(compact, "_active_reasons", side_effect=AssertionError("no PID gate"))):
            result = self.apply()
        self.assertEqual(result["archived_runs"], 1)
        self.assertFalse(old.exists())
        self.assertTrue(active.exists())
        self.assertEqual(compact.read_run_evidence(self.root, old.name), original)
        for path, raw in preserved.items():
            self.assertEqual(path.read_bytes(), raw)
        with zipfile.ZipFile(result["archive"]) as archive:
            self.assertEqual(set(archive.namelist()), {f"runs/{old.name}", "metadata/selection.json"})
        self.assertIn("2026-08-01", (self.root / online.SUMMARY_REL).read_text(encoding="utf-8"))
        self.assertTrue(self.apply()["idempotent_noop"])

    def test_run_change_during_compression_preserves_source_and_verified_zip(self):
        old = self.write_run()
        original_build = online._build_archive

        def build(plan):
            result = original_build(plan)
            old.write_bytes(b'{"in_progress": true}')
            return result

        with mock.patch.object(online, "_build_archive", side_effect=build):
            with self.assertRaisesRegex(RuntimeError, "run changed"):
                self.apply()
        self.assertEqual(old.read_bytes(), b'{"in_progress": true}')
        self.assertEqual(len(list((self.root / "archive").glob("*.zip"))), 1)
        self.assertFalse((self.root / compact.MANIFEST_REL).exists())
        self.assertFalse((self.root / compact.LOCK_NAME).exists())

    def test_manifest_change_aborts_publication_without_removing_runs(self):
        old = self.write_run()
        original_build = online._build_archive
        other_manifest = {"schema_version": 1, "batches": [], "other_writer": True}

        def build(plan):
            result = original_build(plan)
            compact._atomic_write(self.root / compact.MANIFEST_REL, compact._json_bytes(other_manifest))
            return result

        with mock.patch.object(online, "_build_archive", side_effect=build):
            with self.assertRaisesRegex(RuntimeError, "manifest changed"):
                self.apply()
        self.assertTrue(old.exists())
        self.assertEqual(compact._load_manifest(self.root), other_manifest)

    def test_catalog_failure_is_recoverable_from_published_manifest(self):
        old = self.write_run()
        original = old.read_bytes()
        with mock.patch.object(compact, "_write_if_changed", side_effect=OSError("catalog unavailable")):
            with self.assertRaisesRegex(OSError, "catalog unavailable"):
                self.apply()
        self.assertTrue(old.exists())
        self.assertTrue((self.root / compact.MANIFEST_REL).exists())
        with mock.patch.object(online, "_build_archive", side_effect=AssertionError("reuse evidence")):
            result = self.apply()
        self.assertEqual(result["removed_duplicate_runs"], 1)
        self.assertEqual(result["archived_runs"], 0)
        self.assertFalse(old.exists())
        self.assertEqual(compact.read_run_evidence(self.root, old.name), original)
        self.assertEqual(self.catalog()[old.name]["storage"]["kind"], "zip")

    def test_concurrent_current_run_and_stats_changes_do_not_abort_old_archive(self):
        self.write_run()
        stats = self.root / "stats.json"
        stats.write_text("old state", encoding="utf-8")
        original_build = online._build_archive

        def build(plan):
            result = original_build(plan)
            stats.write_text("new state", encoding="utf-8")
            self.write_run("20260912-new.json", started_at="2026-09-12", in_progress=True)
            return result

        with mock.patch.object(online, "_build_archive", side_effect=build):
            self.assertEqual(self.apply()["archived_runs"], 1)
        self.assertEqual(stats.read_text(encoding="utf-8"), "new state")
        self.assertTrue((self.root / "runs" / "20260912-new.json").exists())

    def test_source_changed_after_catalog_publication_is_not_removed(self):
        old = self.write_run()
        original_write = compact._write_if_changed

        def publish(path, raw):
            result = original_write(path, raw)
            if path == self.root / compact.CATALOG_REL:
                old.write_bytes(b'{"updated_after_publication": true}')
            return result

        with mock.patch.object(compact, "_write_if_changed", side_effect=publish):
            with self.assertRaisesRegex(RuntimeError, "run changed before removal"):
                self.apply()
        self.assertEqual(old.read_bytes(), b'{"updated_after_publication": true}')
        self.assertEqual(self.catalog()[old.name]["storage"]["kind"], "zip")

    def test_corrupt_zip_duplicate_is_never_used_to_remove_source(self):
        old = self.write_run()
        with mock.patch.object(compact, "_write_if_changed", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.apply()
        archive = next((self.root / "archive").glob("*.zip"))
        archive.write_bytes(b"damaged archive")
        with self.assertRaises(zipfile.BadZipFile):
            self.apply()
        self.assertTrue(old.exists())

    def test_default_cli_dry_run_writes_nothing(self):
        self.write_run()
        before = {str(p.relative_to(self.root)): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        with mock.patch("builtins.print"):
            self.assertEqual(online.main([
                "--knowledge-dir", str(self.root), "--archive-before", "2026-09-01",
                "--keep-recent", "0"]), 0)
        after = {str(p.relative_to(self.root)): p.read_bytes()
                 for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_history_summary_preserves_unknowns_and_raw_floors(self):
        rows = [
            {"file": "old.json", "started_at": "2026-08-01", "floor": 49,
             "victory": True, "in_progress": False, "run_number": 7,
             "storage": {"kind": "zip"}},
            {"file": "unknown.json", "started_at": None},
        ]
        catalog = b"".join(compact._json_bytes(row, indent=None) for row in rows)
        first = online._history_summary(catalog, archive_before="2026-09-01")
        self.assertEqual(first, online._history_summary(catalog, archive_before="2026-09-01"))
        text = first.decode("utf-8")
        self.assertIn("| 2026-08-01 | 1 | 1 | 1 | 0 | 0 | 1 | 49 | 7–7 |", text)
        self.assertIn("| unknown | 1 | 0 | 0 | 0 | 0 | 0 | unknown | unknown |", text)
        self.assertIn("--show-run", text)


if __name__ == "__main__":
    unittest.main()
