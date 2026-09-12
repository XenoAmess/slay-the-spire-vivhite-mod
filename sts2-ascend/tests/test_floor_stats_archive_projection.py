"""Archive projections keep dashboard refreshes independent of old raw traces."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "brain"))

from floor_stats import FloorStatsProvider  # noqa: E402


def _row(name: str, **fields) -> dict:
    return {
        "file": name,
        "run_id": name.removesuffix(".json"),
        "run_number": 1,
        "started_at": "2026-09-01T00:00:00",
        "floor": 12,
        "victory": False,
        "in_progress": False,
        "decisions": 1,
        "last_screen": "GAME_OVER",
        "storage": {"kind": "zip", "archive": "archive/runs.zip",
                    "member": f"runs/{name}"},
        **fields,
    }


def _catalog(root: Path, rows: list[dict]) -> None:
    path = root / "archive" / "run_catalog.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row) for row in [
        {"schema_version": 1}, *rows]) + "\n", encoding="utf-8")


def _archive(root: Path, data_by_name: dict[str, dict]) -> list[dict]:
    path = root / "archive" / "runs.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in data_by_name.items():
            raw = json.dumps(data).encode("utf-8")
            archive.writestr(f"runs/{name}", raw)
            rows.append(_row(name, bytes=len(raw),
                             sha256=hashlib.sha256(raw).hexdigest()))
    return rows


class ArchiveProjectionTests(unittest.TestCase):
    def test_complete_explicit_projection_does_not_open_zip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _catalog(root, [_row(
                "complete.json", profile_id="ironclad",
                card_picks=["BASH", "BASH"],
                final_deck=[{"card_id": "BASH", "upgraded": True}])])
            with patch("floor_stats.zipfile.ZipFile") as archive:
                snapshot = FloorStatsProvider(root).snapshot()
            archive.assert_not_called()
            self.assertFalse(snapshot["stale"])
            self.assertEqual(snapshot["recent"]["mean_floor"], 12)
            self.assertEqual(snapshot["card_choices"]["evidence_runs"], 1)
            self.assertIn("BASH", snapshot["final_deck_evidence"]["cards"])

    def test_versioned_missing_evidence_stays_distinct_from_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _catalog(root, [
                _row("missing.json", catalog_projection_version=1),
                _row("empty.json", catalog_projection_version=1,
                     card_picks=[], final_deck=[]),
            ])
            with patch("floor_stats.zipfile.ZipFile") as archive:
                snapshot = FloorStatsProvider(root).snapshot()
            archive.assert_not_called()
            self.assertEqual(snapshot["lifetime"]["runs"], 2)
            self.assertEqual(snapshot["card_choices"]["evidence_runs"], 1)
            self.assertEqual(snapshot["card_choices"]["missing_evidence_runs"], 1)
            self.assertEqual(snapshot["final_deck_evidence"]["evidence_runs"], 1)
            self.assertEqual(
                snapshot["final_deck_evidence"]["missing_evidence_runs"], 1)
            self.assertFalse(snapshot["stale"])

    def test_legacy_identity_and_cards_share_one_decode_and_zip_handle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payloads = {
                "vivhite.json": {
                    "profile_id": "vivhite", "attribution_tags": [["card_pick", "BASH"]],
                    "final_deck": [{"card_id": "BASH", "upgraded": True}],
                },
                "ironclad.json": {"attribution_tags": [], "final_deck": []},
            }
            _catalog(root, _archive(root, payloads))
            zip_class = zipfile.ZipFile
            original_read = zip_class.read
            reads = []

            def read(archive, member, *args, **kwargs):
                reads.append(member)
                return original_read(archive, member, *args, **kwargs)

            original_loads = json.loads
            with patch("floor_stats.zipfile.ZipFile", wraps=zip_class) as archives, \
                    patch.object(zip_class, "read", read), \
                    patch("floor_stats.json.loads", wraps=original_loads) as loads:
                provider = FloorStatsProvider(root, _discover_profiles=False)
                snapshot = provider.snapshot()
                provider.snapshot(force=True)
            self.assertEqual(archives.call_count, 1)
            self.assertEqual(reads, ["runs/vivhite.json", "runs/ironclad.json"])
            decoded = [call.args[0] for call in loads.call_args_list]
            for data in payloads.values():
                self.assertEqual(decoded.count(json.dumps(data)), 1)
            vivhite = snapshot["profiles"]["vivhite"]
            self.assertEqual(vivhite["lifetime"]["runs"], 1)
            self.assertIn("BASH", vivhite["card_choices"]["cards"])
            self.assertIn("BASH", vivhite["final_deck_evidence"]["cards"])
            self.assertEqual(snapshot["profiles"]["ironclad"]["lifetime"]["runs"], 1)

    def test_unknown_projection_version_still_hydrates_legacy_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rows = _archive(root, {"unknown.json": {
                "attribution_tags": [["card_pick", "BASH"]], "final_deck": [],
            }})
            rows[0]["catalog_projection_version"] = 99
            _catalog(root, rows)
            snapshot = FloorStatsProvider(root).snapshot()
            self.assertIn("BASH", snapshot["card_choices"]["cards"])
            self.assertEqual(snapshot["final_deck_evidence"]["evidence_runs"], 1)

    def test_failed_legacy_identity_verification_preserves_last_snapshot(self) -> None:
        for corruption in ("bytes", "sha256", "missing_sha256"):
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                rows = _archive(root, {"legacy.json": {
                    "attribution_tags": [], "final_deck": [],
                }})
                _catalog(root, rows)
                provider = FloorStatsProvider(root)
                before = provider.snapshot()
                if corruption == "missing_sha256":
                    rows[0].pop("sha256")
                elif corruption == "sha256":
                    rows[0]["sha256"] = "bad-hash"
                else:
                    rows[0]["bytes"] += 1
                _catalog(root, rows)
                after = provider.snapshot(force=True)
                self.assertEqual(after["lifetime"], before["lifetime"])
                self.assertTrue(after["stale"])
                self.assertIn("cannot recover archived profile identity",
                              " ".join(after["quality"]["errors"]))


if __name__ == "__main__":
    unittest.main()
