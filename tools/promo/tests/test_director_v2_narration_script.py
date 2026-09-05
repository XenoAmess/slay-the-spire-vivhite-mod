"""Contract checks for director-v2 narration script materialization."""

from __future__ import annotations

from pathlib import Path
import importlib.util
import sys
import unittest


PROMO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROMO_ROOT / "v2" / "build_narration_script.py"
SPEC = importlib.util.spec_from_file_location("build_narration_script_v2", MODULE_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)


class DirectorV2NarrationScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = builder.build(PROMO_ROOT / "v2" / "storyboard.json")

    def test_policy_is_540_seconds_xiaoxiao_and_no_bgm(self) -> None:
        self.assertEqual("director-v2", self.result["revision_id"])
        self.assertEqual(540, self.result["target_duration_seconds"])
        self.assertEqual(
            "zh-CN-XiaoxiaoNeural", self.result["audio_policy"]["voice"]
        )
        self.assertFalse(self.result["audio_policy"]["include_bgm"])

    def test_each_nonempty_narration_is_one_bilingual_cue(self) -> None:
        cues = [
            cue
            for chapter in self.result["chapters"]
            for cue in chapter["cues"]
        ]
        self.assertEqual(30, len(cues))
        self.assertEqual(30, len({cue["cue_id"] for cue in cues}))
        for cue in cues:
            self.assertTrue(cue["narration_zh"])
            self.assertTrue(cue["subtitle_zh"])
            self.assertTrue(cue["subtitle_en"])
            self.assertGreater(cue["subtitle_window_seconds"], 0)

    def test_fixed_opening_and_closing_lines_are_preserved(self) -> None:
        by_id = {
            cue["cue_id"]: cue
            for chapter in self.result["chapters"]
            for cue in chapter["cues"]
        }
        self.assertEqual(
            "生命也好，希望也罢，这些无趣的东西，你们尽管拿去。",
            by_id["C007A"]["narration_zh"],
        )
        self.assertEqual("+15%", by_id["C007A"]["tts_rate"])
        self.assertEqual(
            "我只是……想要成为我自己。", by_id["C008A"]["narration_zh"]
        )
        self.assertEqual(26.5, by_id["C008A"]["anchor_seconds"])
        self.assertEqual(
            "这就是白绮：用生命支付，用余裕周转，让每一次回转成为未来的基石。",
            by_id["C047"]["narration_zh"],
        )
        self.assertEqual(
            "和白绮一同走进尖塔，看看你的公式能走多远。",
            by_id["C048"]["narration_zh"],
        )

    def test_silent_game_and_title_cues_are_explicitly_accounted_for(self) -> None:
        selection = self.result["selection"]
        self.assertEqual(21, selection["intentionally_silent_cue_count"])
        self.assertIn("C001", selection["intentionally_silent_cue_ids"])
        self.assertIn("C049", selection["intentionally_silent_cue_ids"])

    def test_runtime_pending_numbers_are_not_baked_into_voice_or_subtitles(self) -> None:
        cues = [
            cue
            for chapter in self.result["chapters"]
            for cue in chapter["cues"]
        ]
        by_id = {cue["cue_id"]: cue for cue in cues}
        for cue_id in ("C008B", "C038", "C048"):
            cue = by_id[cue_id]
            combined = " ".join(
                (cue["narration_zh"], cue["subtitle_zh"], cue["subtitle_en"])
            )
            self.assertNotIn("78/78", combined)
            self.assertNotIn("99", combined)
            self.assertNotIn("61", combined)
            self.assertEqual("pending", cue["runtime_binding"]["status"])
            self.assertTrue(
                cue["runtime_binding"]["must_not_bake_into_tts_or_subtitle"]
            )


if __name__ == "__main__":
    unittest.main()
