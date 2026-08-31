"""Durable character identity across active logs, catalogs, and ZIP archives."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import compact_knowledge  # noqa: E402
from floor_stats import FloorStatsProvider  # noqa: E402


VIVHITE_CHARACTER_ID = "VIVHITE_CHARACTER_VIVHITE_CHARACTER"


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _run(run_id: str, floor: int, **identity: str) -> dict:
    return {
        "run_id": run_id,
        "run_number": floor,
        "started_at": f"2026-08-31 14:{floor:02d}:00",
        "ascension": 0,
        "victory": False,
        "in_progress": False,
        "floor": floor,
        "decisions": [
            {"screen": "COMBAT", "floor": floor, "action": "end_turn"},
            {"screen": "GAME_OVER", "floor": floor, "reason": "defeat"},
        ],
        **identity,
    }


def _options() -> compact_knowledge.CompactionOptions:
    return compact_knowledge.CompactionOptions(
        keep_recent=0,
        deep_floor=999,
        keep_longest=0,
        keep_largest=0,
        keep_floor_representatives=False,
        keep_lessons=0,
        keep_meta_reviews=0,
    )


def _catalog_rows(profile_root: Path) -> list[dict]:
    lines = (profile_root / compact_knowledge.CATALOG_REL).read_text(
        encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines[1:] if line.strip()]


def _remove_catalog_identity(profile_root: Path) -> None:
    path = profile_root / compact_knowledge.CATALOG_REL
    rows = [json.loads(line) for line in path.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    for row in rows[1:]:
        row.pop("profile_id", None)
        row.pop("character_id", None)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


class ProfileIdentityCompactionTests(unittest.TestCase):
    @staticmethod
    def _profile_root(root: Path) -> Path:
        profile_root = root / "profiles" / "vivhite"
        _write_json(profile_root / "policy.json", {})
        return profile_root

    def test_new_catalog_preserves_ids_and_archived_vivhite_stays_vivhite(
            self) -> None:
        with tempfile.TemporaryDirectory(
                prefix="ascend-profile-identity-new-") as temp:
            root = Path(temp) / "knowledge"
            profile_root = self._profile_root(root)
            fixtures = (
                _run("V-BOTH", 15, profile_id="vivhite",
                     character_id=VIVHITE_CHARACTER_ID),
                _run("V-PROFILE-ONLY", 25, profile_id="vivhite"),
                _run("V-CHARACTER-ONLY", 35,
                     character_id=VIVHITE_CHARACTER_ID),
            )
            for row in fixtures:
                _write_json(profile_root / "runs" / f"{row['run_id']}.json", row)

            result = compact_knowledge.apply_compaction(root, _options())

            # The deepest trace per ascension stays active by compactor policy;
            # the explicitly identified V-BOTH run must still be truly archived.
            self.assertEqual(result["archived_runs"], 2)
            self.assertFalse(
                (profile_root / "runs" / "V-BOTH.json").exists())
            self.assertTrue(
                (profile_root / "runs" / "V-CHARACTER-ONLY.json").exists())
            catalog = {row["run_id"]: row for row in _catalog_rows(profile_root)}
            self.assertEqual(catalog["V-BOTH"]["profile_id"], "vivhite")
            self.assertEqual(
                catalog["V-BOTH"]["character_id"], VIVHITE_CHARACTER_ID)
            self.assertEqual(
                catalog["V-PROFILE-ONLY"]["profile_id"], "vivhite")
            self.assertNotIn("character_id", catalog["V-PROFILE-ONLY"])
            self.assertNotIn("profile_id", catalog["V-CHARACTER-ONLY"])
            self.assertEqual(
                catalog["V-CHARACTER-ONLY"]["character_id"],
                VIVHITE_CHARACTER_ID,
            )

            snapshot = FloorStatsProvider(
                root, refresh_interval=0, rolling_window=3).snapshot()
            vivhite = snapshot["profiles"]["vivhite"]
            self.assertEqual(vivhite["lifetime"]["runs"], 3)
            self.assertEqual(vivhite["lifetime"]["mean_floor"], 25.0)
            self.assertEqual(
                [row["run_id"] for row in vivhite["trend"]],
                ["V-BOTH", "V-PROFILE-ONLY", "V-CHARACTER-ONLY"],
            )

    def test_legacy_zip_catalog_recovers_vivhite_from_raw_json(self) -> None:
        with tempfile.TemporaryDirectory(
                prefix="ascend-profile-identity-legacy-") as temp:
            root = Path(temp) / "knowledge"
            profile_root = self._profile_root(root)
            row = _run("V-LEGACY-ZIP", 21, profile_id="vivhite",
                       character_id=VIVHITE_CHARACTER_ID)
            active = profile_root / "runs" / "v-legacy.json"
            _write_json(active, row)
            _write_json(
                profile_root / "runs" / "anchor.json",
                _run("V-ANCHOR", 50, profile_id="vivhite",
                     character_id=VIVHITE_CHARACTER_ID,
                     human_assisted=True),
            )
            compact_knowledge.apply_compaction(root, _options())
            self.assertFalse(active.exists())
            _remove_catalog_identity(profile_root)
            catalog = _catalog_rows(profile_root)
            self.assertNotIn("profile_id", catalog[0])
            self.assertNotIn("character_id", catalog[0])

            snapshot = FloorStatsProvider(root, refresh_interval=0).snapshot()
            vivhite = snapshot["profiles"]["vivhite"]
            self.assertEqual(vivhite["lifetime"]["runs"], 1)
            self.assertEqual(vivhite["lifetime"]["mean_floor"], 21.0)
            self.assertEqual(
                [item["run_id"] for item in vivhite["trend"]],
                ["V-LEGACY-ZIP"],
            )

    def test_legacy_zip_and_raw_without_ids_are_ironclad(self) -> None:
        with tempfile.TemporaryDirectory(
                prefix="ascend-profile-identity-untagged-") as temp:
            root = Path(temp) / "knowledge"
            profile_root = self._profile_root(root)
            _write_json(
                profile_root / "runs" / "misplaced-old.json",
                _run("MISPLACED-OLD", 17),
            )
            _write_json(
                profile_root / "runs" / "anchor.json",
                _run("V-ANCHOR", 50, profile_id="vivhite",
                     character_id=VIVHITE_CHARACTER_ID,
                     human_assisted=True),
            )
            compact_knowledge.apply_compaction(root, _options())
            _remove_catalog_identity(profile_root)

            snapshot = FloorStatsProvider(
                profile_root,
                refresh_interval=0,
                profile_id="vivhite",
                _discover_profiles=False,
            ).snapshot()
            self.assertEqual(
                snapshot["profiles"]["ironclad"]["lifetime"]["runs"], 1)
            self.assertEqual(
                snapshot["profiles"]["ironclad"]["lifetime"]["mean_floor"],
                17.0,
            )
            self.assertIsNone(
                snapshot["profiles"]["vivhite"]["lifetime"]["runs"])
            self.assertEqual(
                snapshot["profiles"]["vivhite"]["recent"]["count"], 0)

    def test_active_identity_never_comes_from_the_physical_profile_root(self) -> None:
        cases = (
            (_run("ROOT-OLD", 7), "ironclad"),
            (_run("MISPLACED-OLD", 8), "ironclad"),
            (_run("PROFILE-ONLY", 9, profile_id="vivhite"), "vivhite"),
            (_run("CHARACTER-ONLY", 10,
                  character_id=VIVHITE_CHARACTER_ID), "vivhite"),
        )
        paths = (
            Path("knowledge/runs/root-old.json"),
            Path("knowledge/profiles/vivhite/runs/misplaced-old.json"),
            Path("knowledge/profiles/vivhite/runs/profile-only.json"),
            Path("knowledge/profiles/vivhite/runs/character-only.json"),
        )
        for path, (data, expected) in zip(paths, cases):
            with self.subTest(path=path, expected=expected):
                record = FloorStatsProvider._active_record(path, data)
                self.assertEqual(record.profile_id, expected)

    def test_unreadable_legacy_zip_never_silently_defaults_to_ironclad(self) -> None:
        with tempfile.TemporaryDirectory(
                prefix="ascend-profile-identity-missing-zip-") as temp:
            profile_root = Path(temp) / "knowledge" / "profiles" / "vivhite"
            catalog_path = profile_root / compact_knowledge.CATALOG_REL
            catalog_path.parent.mkdir(parents=True, exist_ok=True)
            rows = [
                {"schema_version": 1, "description": "legacy test"},
                {
                    "file": "unknown.json",
                    "run_id": "UNKNOWN",
                    "floor": 12,
                    "decisions": 1,
                    "last_screen": "GAME_OVER",
                    "bytes": 123,
                    "sha256": "0" * 64,
                    "storage": {
                        "kind": "zip",
                        "archive": "archive/missing.zip",
                        "member": "runs/unknown.json",
                    },
                },
            ]
            catalog_path.write_text(
                "\n".join(json.dumps(row) for row in rows) + "\n",
                encoding="utf-8",
            )

            snapshot = FloorStatsProvider(
                profile_root,
                refresh_interval=0,
                profile_id="vivhite",
                _discover_profiles=False,
            ).snapshot()

            self.assertTrue(snapshot["stale"])
            self.assertIn(
                "cannot recover archived profile identity",
                "\n".join(snapshot["quality"]["errors"]),
            )
            self.assertIsNone(
                snapshot["profiles"]["ironclad"]["lifetime"]["runs"])


if __name__ == "__main__":
    unittest.main()
