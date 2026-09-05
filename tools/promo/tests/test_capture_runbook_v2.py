"""Offline tests for the director-v2 per-take capture runbook."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PROMO_ROOT = ROOT / "tools" / "promo"
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

from vivhite_promo import capture_runbook_v2 as runbook_module  # noqa: E402


class VivhiteCaptureRunbookV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runbook = runbook_module.load_capture_runbook()
        cls.storyboard = json.loads(
            runbook_module.DEFAULT_STORYBOARD_PATH.read_text(encoding="utf-8")
        )
        cls.takes = {take["take_id"]: take for take in cls.runbook["takes"]}
        cls.storyboard_takes = {
            take["take_id"]: take for take in cls.storyboard["takes"]
        }

    def test_runbook_covers_all_twenty_slots_and_only_t15_is_conditional(self) -> None:
        self.assertEqual(set(runbook_module.EXPECTED_TAKE_IDS), set(self.takes))
        self.assertEqual(20, len(self.takes))
        self.assertEqual(
            {"T15"},
            {
                take_id
                for take_id, take in self.takes.items()
                if take["requirement"] == "conditional"
            },
        )
        batched = [
            take_id
            for batch in self.runbook["batches"]
            for take_id in batch["take_ids"]
        ]
        self.assertCountEqual(runbook_module.EXPECTED_TAKE_IDS, batched)
        self.assertEqual(len(batched), len(set(batched)))

    def test_storyboard_reflects_the_explicit_four_part_media_gate_lift(self) -> None:
        scope = self.storyboard["round_scope"]
        self.assertEqual("production_authorized", scope["mode"])
        for capability in (
            "game_launch_allowed",
            "obs_allowed",
            "capture_allowed",
            "render_allowed",
        ):
            with self.subTest(capability=capability):
                self.assertIs(True, scope[capability])
        self.assertIs(False, scope["network_tts_allowed"])

    def test_every_take_is_an_independent_clean_recording_recipe(self) -> None:
        contract = self.runbook["recording_contract"]
        self.assertTrue(contract["one_independent_source_per_take"])
        self.assertEqual("before_recording_mark_only", contract["setup_phase"])
        self.assertEqual(2, contract["pre_roll_seconds"])
        self.assertEqual({"minimum": 3, "maximum": 4}, contract["post_result_seconds"])
        self.assertTrue(contract["formal_action_to_settlement_uncut"])

        for take_id, take in self.takes.items():
            with self.subTest(take_id=take_id):
                self.assertTrue(take["setup_before_mark"])
                self.assertTrue(take["clean_frame_gate"])
                self.assertTrue(take["formal_sequence"])
                self.assertEqual(2, take["pre_roll_seconds"])
                self.assertEqual(
                    {"minimum": 3, "maximum": 4},
                    take["post_result_seconds"],
                )
                self.assertEqual(
                    f"raw/takes/{take_id}/{{attempt_id}}.mkv",
                    take["source_file_template"],
                )
                self.assertTrue(
                    all(operation["continuous"] for operation in take["formal_sequence"])
                )
                self.assertFalse(
                    {
                        "console",
                        "direct_api",
                        "debug_action",
                        "system_mouse",
                    }
                    & {
                        operation["input"] for operation in take["formal_sequence"]
                    }
                )

    def test_t06_is_bound_to_a_current_registered_reward_card(self) -> None:
        card = runbook_module.resolve_t06_reward_card()
        binding = self.runbook["t06_source_binding"]
        self.assertEqual("VIVHITE_CARD_TANGENT_STARLIGHT", card.card_id)
        self.assertEqual("TangentStarlight", card.class_name)
        self.assertEqual("ConservationCard", card.base_class)
        self.assertEqual("Common", card.rarity)
        self.assertEqual("切线星光", card.localized_title)
        self.assertEqual(card.card_id, binding["card_id"])
        self.assertEqual(
            card.card_id,
            self.takes["T06"]["formal_sequence"][0]["target"],
        )
        self.assertNotIn(
            card.card_id,
            {"VIVHITE_CARD_AXIOM_RING", "VIVHITE_CARD_CLOSED_PROJECTION"},
        )

        storyboard_t06 = self.storyboard_takes["T06"]
        self.assertEqual("bound_from_current_source", storyboard_t06["card_selection_status"])
        self.assertEqual(card.card_id, storyboard_t06["card_selection_binding"]["card_id"])
        self.assertEqual(
            card.card_id,
            storyboard_t06["formal_action_chain"]["steps"][0]["card_id"],
        )

    def test_t06_fails_closed_if_the_card_stops_being_reward_eligible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_root = Path(temporary_directory)
            source_root = temporary_root / "Conservation"
            shutil.copytree(runbook_module.DEFAULT_CARD_SOURCE_ROOT, source_root)
            localization_path = temporary_root / "cards.json"
            shutil.copyfile(runbook_module.DEFAULT_LOCALIZATION_PATH, localization_path)
            source_path = source_root / "ConservationCommonCards.cs"
            source = source_path.read_text(encoding="utf-8")
            class_start = source.index("public sealed class TangentStarlight")
            next_card = source.index("[RegisterCard", class_start)
            card_source = source[class_start:next_card]
            changed_card_source = card_source.replace(
                "CardRarity.Common", "CardRarity.Basic", 1
            )
            self.assertNotEqual(card_source, changed_card_source)
            source_path.write_text(
                source[:class_start] + changed_card_source + source[next_card:],
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                runbook_module.CaptureRunbookV2Error,
                "T06 requires exactly one current",
            ):
                runbook_module.resolve_t06_reward_card(
                    source_root=source_root,
                    localization_path=localization_path,
                )

    def test_t14_and_t15_require_real_crown_healing_not_just_the_icon(self) -> None:
        expected = {
            "starter_relic_is_solitary_crown",
            "actual_crown_healing_greater_than_zero",
            "actual_drain_healing_greater_than_zero",
            "actual_draw_delta_greater_than_zero",
            "actual_energy_gain_greater_than_zero",
        }
        for take_id in ("T14", "T15"):
            with self.subTest(take_id=take_id):
                self.assertEqual(expected, set(self.takes[take_id]["critical_assertions"]))
                setup = "\n".join(self.takes[take_id]["setup_before_mark"])
                self.assertIn("孤高冠冕", setup)
                self.assertIn("actual_crown_healing>0", setup)

    def test_t16_has_no_setup_or_source_break_between_both_card_actions(self) -> None:
        take = self.takes["T16"]
        self.assertTrue(take["single_continuous_source"])
        self.assertFalse(take["setup_between_formal_actions_allowed"])
        self.assertEqual(
            [
                "VIVHITE_CARD_VIVHITES_CRIMSON_TRANSFORMATION_RITUAL",
                "end_turn_button",
                "VIVHITE_CARD_LUMINOUS_PROJECTION",
            ],
            [operation["target"] for operation in take["formal_sequence"]],
        )

    def test_t18_locks_the_complete_visible_feedback_chain(self) -> None:
        take = self.takes["T18"]
        self.assertTrue(take["single_continuous_source"])
        self.assertEqual(
            [
                "VIVHITE_CARD_CLOSED_DOMAIN_MAPPING",
                "VIVHITE_CARD_TRICHROMATIC_WALTZ",
            ],
            [operation["target"] for operation in take["formal_sequence"]],
        )
        self.assertEqual(
            [
                "margin_decreases_after_cough",
                "drain_percent_increases_after_margin_offset",
                "drain_attack_actual_damage_greater_than_zero",
                "actual_healing_at_least_runtime_divisor",
                "final_margin_greater_than_post_cough_margin",
            ],
            take["critical_assertions"],
        )

    def test_single_take_formatter_is_directly_usable_and_does_not_claim_capture(self) -> None:
        rendered = runbook_module.format_take_checklist(self.runbook, "T18")
        self.assertIn("T18 — 统一场论完整资源闭环", rendered)
        self.assertIn("录制标记前", rendered)
        self.assertIn("正式动作（同一原始文件、1×、不中断）", rendered)
        self.assertIn("raw/takes/T18/{attempt_id}.mkv", rendered)
        self.assertNotIn("已完成", rendered)


if __name__ == "__main__":
    unittest.main()
