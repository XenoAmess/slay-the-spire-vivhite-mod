"""Offline tests for full-master-derived preview EDLs.

The tests intentionally do not invoke FFmpeg, ffprobe, a game, OBS, OCR, or
TTS.  They exercise only deterministic editorial derivation and fail-closed
source binding.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


PROMO_ROOT = Path(__file__).resolve().parents[1]
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

import render_preview_variants as previews  # noqa: E402


class PreviewVariantEdlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Keep the unit tests independent of ignored real capture runs.  The
        # production command consumes the hash-bound delivery-a2 EDL; this
        # fixture exercises the same structural fields without reading media.
        shots = (
            ("S01-identity", 45.0),
            ("S02-loadout", 50.0),
            ("S03-cough", 60.0),
            ("S04-margin", 55.0),
            ("S05-drain", 65.0),
            ("S06-conservation-geometry", 60.0),
            ("S07-recursive-star-calculus", 60.0),
            ("S08-crimson-integral", 60.0),
            ("S09-unified-field", 75.0),
            ("S10-finale", 70.0),
        )
        source_starts = {
            "S01-identity": 240.0,
            "S02-loadout": 300.0,
            "S03-cough": 360.0,
            "S04-margin": 900.0,
            "S05-drain": 1500.0,
            "S06-conservation-geometry": 2100.0,
            "S07-recursive-star-calculus": 2700.0,
            "S08-crimson-integral": 3300.0,
            "S09-unified-field": 3900.0,
            "S10-finale": 4500.0,
        }
        segments = [
            {
                "segment_id": f"seg-{index:02d}",
                "shot_id": shot,
                "source_start_seconds": source_starts[shot],
                "duration_seconds": duration,
                "provenance": "staged",
                "span_id": f"staged-{shot[4:].replace('-', '_')}",
            }
            for index, (shot, duration) in enumerate(shots, 1)
        ]
        cues = []
        for shot, _duration in shots:
            cue_id = {"S01-identity": "S01-01", "S03-cough": "S03-01", "S05-drain": "S05-01", "S09-unified-field": "S09-01", "S10-finale": "S10-01"}.get(shot)
            if cue_id is None:
                continue
            segment = next(row for row in segments if row["shot_id"] == shot)
            cues.append(
                {
                    "cue_id": cue_id,
                    "segment_id": segment["segment_id"],
                    "offset_seconds": 0.0,
                    "file": f"{cue_id}.mp3",
                    "subtitle_zh": f"{shot} 中文",
                    "subtitle_en": f"{shot} English",
                    "subtitle_duration_seconds": 14.0,
                }
            )
        cls.source = {
            "schema_version": 1,
            "kind": "vivhite_promo_full_master_edl",
            "source_label": "fixture",
            "target_duration_seconds": 600.0,
            "segments": segments,
            "cues": cues,
        }

    def test_all_variants_have_exact_duration_and_explicit_spans(self) -> None:
        expected = {"hero-60": 60.0, "cut-30": 30.0, "cut-15": 15.0}
        for variant_id, duration in expected.items():
            payload = previews.derive_variant_edl(
                self.source,
                variant_id=variant_id,
                narration_root_label="tts-a4/narration",
            )
            self.assertEqual(duration, payload["target_duration_seconds"])
            self.assertAlmostEqual(
                duration,
                sum(float(row["duration_seconds"]) for row in payload["segments"]),
            )
            self.assertTrue(all(row.get("span_id") for row in payload["segments"]))
            self.assertTrue(all(row.get("provenance") in {"natural", "staged"} for row in payload["segments"]))
            self.assertEqual("zh-CN-XiaoxiaoNeural", payload["authoring"]["narration_voice"])
            self.assertFalse(payload["authoring"]["include_bgm"])

    def test_derivation_keeps_source_cue_file_and_bilingual_text(self) -> None:
        payload = previews.derive_variant_edl(
            self.source,
            variant_id="hero-60",
            narration_root_label="run-tts-a4/narration",
        )
        source_cues = {row["cue_id"]: row for row in self.source["cues"]}
        selected = payload["authoring"]["selected_source_cues"]
        self.assertEqual(["S01-01", "S03-01", "S05-01", "S09-01", "S10-01"], selected)
        for row, source_id in zip(payload["cues"], selected):
            source = source_cues[source_id]
            self.assertEqual(source["file"], row["file"])
            self.assertEqual(source["subtitle_zh"], row["subtitle_zh"])
            self.assertEqual(source["subtitle_en"], row["subtitle_en"])

    def test_cut15_has_a_deliberate_silent_finale_tail(self) -> None:
        payload = previews.derive_variant_edl(
            self.source,
            variant_id="cut-15",
            narration_root_label="tts-a4/narration",
        )
        self.assertEqual(["S01-identity", "S10-finale"], [row["shot_id"] for row in payload["segments"]])
        self.assertEqual(1, len(payload["cues"]))
        self.assertIn("S01-01", payload["authoring"]["selected_source_cues"])

    def test_missing_source_cue_is_rejected_without_guessing(self) -> None:
        broken = copy.deepcopy(self.source)
        broken["cues"] = [row for row in broken["cues"] if row["cue_id"] != "S03-01"]
        with self.assertRaisesRegex(previews.PreviewVariantError, "lacks cue 'S03-01'"):
            previews.derive_variant_edl(
                broken,
                variant_id="hero-60",
                narration_root_label="tts-a4/narration",
            )

    def test_source_cue_path_escape_is_rejected(self) -> None:
        broken = copy.deepcopy(self.source)
        broken["cues"][0]["file"] = "../outside.mp3"
        with self.assertRaisesRegex(previews.PreviewVariantError, "normalized relative path"):
            previews.derive_variant_edl(
                broken,
                variant_id="hero-60",
                narration_root_label="tts-a4/narration",
            )

    def test_source_batch_label_is_not_hardcoded(self) -> None:
        payload = previews.derive_variant_edl(
            self.source,
            variant_id="cut-30",
            narration_root_label="tts-a4/narration",
            source_batch_label="run-custom-source-a7",
        )
        self.assertTrue(payload["source_label"].startswith("run-custom-source-a7-derived-cut-30"))

    def test_narration_manifest_requires_xiaoxiao_and_no_bgm(self) -> None:
        class Recorder:
            @staticmethod
            def file_record(path: Path) -> dict[str, object]:
                return {"path": str(path), "bytes": path.stat().st_size, "sha256": "x"}

        with tempfile.TemporaryDirectory(prefix="vivhite-preview-tts-") as raw:
            root = Path(raw)
            batch_root = root / "tts-a4"
            narration = batch_root / "narration"
            narration.mkdir(parents=True)
            logs = batch_root / "logs"
            logs.mkdir()
            manifest = logs / "full-master-narration-manifest.json"
            manifest.write_text(
                json.dumps({"run_id": "tts-a4", "policy": {"voice": "zh-CN-XiaoxiaoNeural", "include_bgm": False}}),
                encoding="utf-8",
            )
            record = previews._narration_batch_record(Recorder(), narration)
            self.assertEqual("tts-a4", record["run_id"])
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["policy"]["include_bgm"] = True
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(previews.PreviewVariantError, "include_bgm=false"):
                previews._narration_batch_record(Recorder(), narration)
            data["policy"]["include_bgm"] = False
            data["run_id"] = "other-batch"
            manifest.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(previews.PreviewVariantError, "run_id does not match"):
                previews._narration_batch_record(Recorder(), narration)

    def test_existing_edl_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-preview-edl-") as raw:
            path = Path(raw) / "variant.edl.json"
            path.write_text("old\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                previews._write_json_new(path, {"new": True})
            self.assertEqual("old\n", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
