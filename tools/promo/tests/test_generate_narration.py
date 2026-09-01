"""Offline checks for the project-owned narration producer.

The tests deliberately stop before importing a TTS provider or invoking
ffprobe.  They cover the checked-in authoring contract, subtitle materializer,
and append-only run guard without making network or process calls.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
import tempfile
import unittest


PROMO_ROOT = Path(__file__).resolve().parents[1]
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

import generate_narration as narration  # noqa: E402


class NarrationProducerTests(unittest.TestCase):
    def test_project_and_storyboard_close_over_ten_cues(self) -> None:
        project, chapters = narration.load_project(PROMO_ROOT / "project.json")
        shots = narration.load_storyboard(PROMO_ROOT / "storyboard.json", chapters)

        self.assertEqual("zh-CN", project["locales"]["narration"])
        self.assertEqual(10, len(chapters))
        self.assertEqual(10, len(shots))
        self.assertEqual(
            [f"S{index:02d}" for index in range(1, 11)],
            [str(row["shot_id"]).split("-", 1)[0] for row in shots],
        )
        self.assertTrue(all(row["zh"].strip() for row in shots))
        self.assertTrue(all(row["en_subtitle"].strip() for row in shots))
        self.assertEqual("zh-CN-XiaoxiaoNeural", narration.VOICE)

    def test_subtitle_materializer_writes_hash_bound_bilingual_files(self) -> None:
        rows = [
            {
                "shot_id": "S01-identity",
                "chapter_id": "identity",
                "cue_id": "identity-001",
                "zh": "她是白绮。",
                "zh_subtitle": "白绮：把数学写成魔法",
                "en_subtitle": "Vivhite: mathematics as magic",
                "duration_seconds": 1.25,
            }
        ]
        with tempfile.TemporaryDirectory(prefix="vivhite-narration-test-") as raw:
            root = Path(raw)
            report = narration.write_subtitles(root, rows)

            self.assertEqual(1.25, report["total_duration_seconds"])
            self.assertEqual(4, len(report["files"]))
            for record in report["files"].values():
                path = root / str(record["path"])
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_size, record["bytes"])
                self.assertEqual(
                    hashlib.sha256(path.read_bytes()).hexdigest().upper(),
                    record["sha256"],
                )

            ass = (root / "subtitles" / "vivhite-narration-bilingual.ass").read_text(
                encoding="utf-8"
            )
            self.assertIn("白绮：把数学写成魔法", ass)
            self.assertIn("Vivhite: mathematics as magic", ass)
            srt = (root / "subtitles" / "vivhite-narration-bilingual.srt").read_text(
                encoding="utf-8"
            )
            self.assertIn("00:00:00,000 --> 00:00:01,250", srt)

    def test_generate_refuses_to_overwrite_nonempty_run_before_provider_use(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-narration-existing-") as raw:
            root = Path(raw)
            (root / "existing.txt").write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "refusing to overwrite"):
                narration.generate(
                    PROMO_ROOT / "project.json",
                    root,
                    Path(r"C:\does-not-need-to-exist\ffprobe.exe"),
                )
            self.assertEqual("keep", (root / "existing.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
