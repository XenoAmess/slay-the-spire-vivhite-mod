"""Pure offline contract tests for Vivhite v2 title-card specifications.

The tests construct and inspect xAR value objects only.  They never invoke an
image renderer, media tool, game process, recorder, or network service.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PROMO_ROOT = ROOT / "tools" / "promo"


def _add_local_import_paths() -> None:
    source_override = os.environ.get("XAR_PROMO_TOOLCHAIN_SOURCE")
    xar_candidates = []
    if source_override:
        xar_candidates.append(Path(source_override).expanduser().resolve() / "src")
    xar_candidates.extend(
        (
            Path(r"G:\workspace\xar_promo_toolchain-v0.2.1-tag") / "src",
            Path(r"G:\workspace\xar_promo_toolchain") / "src",
        )
    )
    xar_source = next((path for path in xar_candidates if path.is_dir()), None)
    candidates = [PROMO_ROOT]
    if xar_source is not None:
        candidates.append(xar_source)
    for candidate in reversed(candidates):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


_add_local_import_paths()

import xar_promo  # noqa: E402
from xar_promo.visuals import TitleCardSpec  # noqa: E402

title_cards = importlib.import_module("vivhite_promo.title_cards_v2")


class VivhiteTitleCardV2Tests(unittest.TestCase):
    def test_factory_uses_pinned_xar_public_types_without_spawning(self) -> None:
        self.assertEqual("0.2.1", xar_promo.__version__)
        forbidden = mock.Mock(side_effect=AssertionError("external process started"))
        process_functions = ("run", "Popen", "call", "check_call", "check_output")
        with mock.patch.multiple(
            subprocess,
            **{name: forbidden for name in process_functions},
        ):
            cue = title_cards.create_mechanism_title_card_v2(
                "mechanism.qingke",
                "謦欬：先支付，再结算",
                "Qingke: Pay First, Resolve After",
            )

        self.assertIsInstance(cue.title_card, TitleCardSpec)
        self.assertEqual(2.5, cue.duration_seconds)
        self.assertEqual([], forbidden.call_args_list)

    def test_canvas_palette_and_all_layers_obey_full_hd_safe_area(self) -> None:
        card = title_cards.create_title_card_spec_v2(
            "余裕：把代价变成防线",
            "Leeway: Turn the Cost into Defense",
        )
        canvas = card.canvas
        self.assertEqual((1920, 1080), (canvas.width, canvas.height))
        self.assertEqual(
            (120, 90, 1800, 990),
            (
                canvas.safe_area.left,
                canvas.safe_area.top,
                canvas.safe_area.right,
                canvas.safe_area.bottom,
            ),
        )
        self.assertEqual("solid", canvas.background.kind)
        self.assertEqual("deep_indigo", canvas.background.color_role)
        self.assertEqual(
            title_cards.DEEP_INDIGO_RGBA,
            canvas.palette.resolve("deep_indigo"),
        )
        self.assertEqual(title_cards.GOLD_RGBA, canvas.palette.resolve("gold"))

        boxes = [element.box for element in card.layers.panels]
        boxes.extend(element.box for element in card.layers.images)
        boxes.extend(element.box for element in card.layers.texts)
        self.assertGreater(len(boxes), 0)
        for box in boxes:
            with self.subTest(box=box):
                self.assertGreaterEqual(box.left, canvas.safe_area.left)
                self.assertGreaterEqual(box.top, canvas.safe_area.top)
                self.assertLessEqual(box.right, canvas.safe_area.right)
                self.assertLessEqual(box.bottom, canvas.safe_area.bottom)

    def test_visual_hierarchy_is_centered_gold_and_blue_butterfly_accented(self) -> None:
        asset_key = "approved_blue_butterfly"
        card = title_cards.create_title_card_spec_v2(
            "汲取：只认实际掉血",
            "Drain: Count Only Health Actually Lost",
            butterfly_asset_key=asset_key,
        )

        self.assertGreaterEqual(
            sum(panel.fill_role == "gold" for panel in card.layers.panels),
            8,
        )
        self.assertEqual(2, len(card.layers.images))
        self.assertTrue(
            all(image.asset_key == asset_key for image in card.layers.images)
        )
        self.assertTrue(
            all(image.contain_color_role == "transparent" for image in card.layers.images)
        )

        chinese, english = card.layers.texts
        self.assertEqual("汲取：只认实际掉血", chinese.text)
        self.assertEqual("Drain: Count Only Health Actually Lost", english.text)
        self.assertEqual("center", chinese.style.alignment)
        self.assertEqual("center", english.style.alignment)
        self.assertEqual("center", chinese.style.vertical_alignment)
        self.assertGreater(chinese.style.line_height_px, english.style.line_height_px)
        self.assertGreater(english.box.top, chinese.box.top)
        self.assertEqual(title_cards.CHINESE_TITLE_FONT_KEY, chinese.style.font_key)
        self.assertEqual(title_cards.ENGLISH_SUBTITLE_FONT_KEY, english.style.font_key)

    def test_mechanism_duration_is_a_caller_side_three_second_gate(self) -> None:
        card = title_cards.create_mechanism_title_card_v2(
            "mechanism.recursion",
            "递归星算：死亡成为下一步输入",
            "Recursive Astrology: Death Becomes the Next Input",
            duration_seconds=3,
        )
        self.assertEqual(3.0, card.duration_seconds)
        self.assertFalse(hasattr(card.title_card, "duration_seconds"))

        for invalid in (0, -0.1, 3.001, float("inf"), float("nan")):
            with self.subTest(duration=invalid):
                with self.assertRaises(ValueError):
                    title_cards.create_mechanism_title_card_v2(
                        "mechanism.invalid",
                        "说明页",
                        "Explainer",
                        duration_seconds=invalid,
                    )
        with self.assertRaises(TypeError):
            title_cards.create_mechanism_title_card_v2(
                "mechanism.invalid",
                "说明页",
                "Explainer",
                duration_seconds=True,
            )

    def test_factory_rejects_blank_or_untrimmed_resource_contracts(self) -> None:
        for kwargs in (
            {"chinese_title": "", "english_subtitle": "Explainer"},
            {"chinese_title": "说明页", "english_subtitle": " Explainer"},
            {
                "chinese_title": "说明页",
                "english_subtitle": "Explainer",
                "butterfly_asset_key": " ",
            },
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    title_cards.create_title_card_spec_v2(**kwargs)


if __name__ == "__main__":
    unittest.main()
