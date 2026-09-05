"""Checks for the checked-in Vivhite director-v2 storyboard.

The suite is deliberately data-only: it parses JSON and invokes the offline
validator, but never starts the game, OBS, TTS, xAR, or a media encoder.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


PROMO_ROOT = Path(__file__).resolve().parents[1]
STORYBOARD_PATH = PROMO_ROOT / "v2" / "storyboard.json"
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

from vivhite_promo import director_v2 as director  # noqa: E402


class CheckedInDirectorStoryboardV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.storyboard = json.loads(STORYBOARD_PATH.read_text(encoding="utf-8"))
        cls.takes = {
            take["take_id"]: take for take in cls.storyboard["takes"]
        }
        cls.subshots = [
            subshot
            for shot in cls.storyboard["shots"]
            for subshot in shot["subshots"]
        ]
        cls.subshots_by_id = {
            subshot["subshot_id"]: subshot for subshot in cls.subshots
        }
        cls.cues_by_id = {
            subshot["cue"]["cue_id"]: subshot["cue"] for subshot in cls.subshots
        }

    def test_offline_validator_accepts_checked_in_storyboard(self) -> None:
        validated = director.load_storyboard_v2(STORYBOARD_PATH)
        self.assertEqual("director-v2", validated["revision_id"])
        self.assertEqual(540, validated["master"]["duration_seconds"])

    def test_utf8_identity_and_fixed_voice_lines_are_intact(self) -> None:
        self.assertEqual("白绮：把生命写成魔法", self.storyboard["title"])
        fixed_lines = (
            "生命也好，希望也罢，这些无趣的东西，你们尽管拿去。",
            "我的魔法，从来不需要被理解。",
            "我只是……想要成为我自己。",
        )
        occurrences = {
            line: [
                item["timeline"]["start_seconds"]
                for item in self.subshots
                if item["cue"]["narration_zh"] == line
            ]
            for line in fixed_lines
        }
        self.assertEqual([18], occurrences[fixed_lines[0]])
        self.assertEqual([23], occurrences[fixed_lines[1]])
        self.assertEqual([28], occurrences[fixed_lines[2]])
        cold_open_text = " ".join(
            item["cue"]["narration_zh"]
            for item in self.subshots
            if item["timeline"]["start_seconds"] < 18
        )
        self.assertNotIn("生命也好", cold_open_text)
        self.assertEqual("", self.subshots[0]["cue"]["narration_zh"])

    def test_canonical_abi_and_nineteen_plus_one_take_plan(self) -> None:
        self.assertEqual(
            list(director.CANONICAL_SHOT_IDS),
            self.storyboard["canonical_shot_ids"],
        )
        takes = {item["take_id"]: item for item in self.storyboard["takes"]}
        self.assertEqual({f"T{index:02d}" for index in range(1, 21)}, set(takes))
        self.assertEqual(
            19,
            sum(item["requirement"] == "required" for item in takes.values()),
        )
        self.assertEqual("conditional", takes["T15"]["requirement"])
        self.assertEqual("T15", self.storyboard["take_policy"]["conditional_take_id"])

    def test_timeline_is_exactly_540_seconds_and_frame_aligned(self) -> None:
        ordered = sorted(self.subshots, key=lambda item: item["timeline"]["start_seconds"])
        cursor = 0.0
        for item in ordered:
            timeline = item["timeline"]
            self.assertAlmostEqual(cursor, timeline["start_seconds"])
            self.assertAlmostEqual(
                timeline["duration_seconds"],
                timeline["end_seconds"] - timeline["start_seconds"],
            )
            for key in ("start_seconds", "end_seconds", "duration_seconds"):
                self.assertAlmostEqual(round(timeline[key] * 60), timeline[key] * 60)
            cursor = timeline["end_seconds"]
        self.assertEqual(540, cursor)
        self.assertEqual(32400, self.storyboard["timebase"]["target_frames"])

    def test_fifteen_director_sections_cover_the_master_in_integer_frames(self) -> None:
        sections = self.storyboard["director_sections"]
        self.assertEqual(15, len(sections))
        second_cursor = 0
        frame_cursor = 0
        for section in sections:
            timeline = section["timeline"]
            self.assertEqual(second_cursor, timeline["start_seconds"])
            self.assertEqual(frame_cursor, timeline["start_frame"])
            self.assertEqual(
                timeline["end_seconds"] - timeline["start_seconds"],
                timeline["duration_seconds"],
            )
            self.assertEqual(
                timeline["end_frame"] - timeline["start_frame"],
                timeline["duration_frames"],
            )
            self.assertEqual(timeline["start_seconds"] * 60, timeline["start_frame"])
            self.assertEqual(timeline["end_seconds"] * 60, timeline["end_frame"])
            second_cursor = timeline["end_seconds"]
            frame_cursor = timeline["end_frame"]
        self.assertEqual((540, 32400), (second_cursor, frame_cursor))

    def test_every_subshot_has_pending_source_cue_provenance_and_evidence(self) -> None:
        cue_ids: list[str] = []
        for item in self.subshots:
            self.assertIn(item["asset_type"], director.ASSET_TYPES)
            self.assertIn("take", item)
            self.assertIsNone(item["source"]["in_seconds"])
            self.assertIsNone(item["source"]["out_seconds"])
            self.assertTrue(item["source"]["status"].endswith("pending"))
            self.assertIn(item["provenance"], director.PROVENANCE_VALUES)
            if item["asset_type"] in director.CAPTURE_ASSET_TYPES:
                self.assertEqual("runtime_observed", item["provenance"])
                self.assertEqual("pending", item["observation_status"])
            self.assertTrue(item["evidence_refs"])
            cue = item["cue"]
            cue_ids.append(cue["cue_id"])
            for field in ("narration_zh", "subtitle_zh", "subtitle_en"):
                self.assertIsInstance(cue[field], str)
            self.assertIsNone(cue["voice_asset"])
        self.assertEqual(len(cue_ids), len(set(cue_ids)))

    def test_mechanism_actions_reference_before_receipt_and_after(self) -> None:
        for item in self.subshots:
            if item["asset_type"] != "mechanism_action":
                continue
            take_id = item["take"]["take_id"]
            catalog = {
                ref["ref_id"]: ref["role"] for ref in self.takes[take_id]["evidence_refs"]
            }
            roles = {catalog[ref_id] for ref_id in item["evidence_refs"]}
            self.assertTrue(director.MECHANISM_EVIDENCE_ROLES <= roles)

    def test_t03_receipt_has_one_formal_owner_and_montages_use_lineage(self) -> None:
        receipt_ref = "T03-action-receipt"
        owners = [
            item["subshot_id"]
            for item in self.subshots
            if receipt_ref in item["evidence_refs"]
        ]
        self.assertEqual(["S03-02-basic-payment"], owners)

        catalog = {
            ref["ref_id"]: ref["role"] for ref in self.takes["T03"]["evidence_refs"]
        }
        for subshot_id in ("S01-01-cough-highlight", "S10-05-finale-cough"):
            montage = self.subshots_by_id[subshot_id]
            self.assertEqual(
                {
                    "source_subshot_id": "S03-02-basic-payment",
                    "reuse_kind": "editorial_excerpt",
                    "formal_action_claimed": False,
                },
                montage["montage_lineage"],
            )
            roles = {catalog[ref_id] for ref_id in montage["evidence_refs"]}
            self.assertTrue(roles <= director.MONTAGE_LINEAGE_EVIDENCE_ROLES)
            self.assertTrue(roles & director.MONTAGE_VISUAL_EVIDENCE_ROLES)
            self.assertIn("action.sequence", roles)
            self.assertNotIn("action.receipt", roles)

    def test_every_mechanism_action_has_the_director_action_window(self) -> None:
        mechanism_actions = [
            item for item in self.subshots if item["asset_type"] == "mechanism_action"
        ]
        self.assertGreater(len(mechanism_actions), 0)
        for item in mechanism_actions:
            window = item["action_window"]
            self.assertTrue(window["full_view_before"])
            self.assertEqual(
                {"minimum": 1.5, "maximum": 2}, window["hover_seconds"]
            )
            self.assertTrue(window["formal_action_to_settlement_uncut"])
            self.assertEqual(1, window["playback_speed"])
            self.assertEqual(
                {"minimum": 2, "maximum": 4}, window["result_hold_seconds"]
            )
            self.assertEqual(4, window["max_no_visible_change_seconds"])
            self.assertLessEqual(
                window["max_no_visible_change_seconds"],
                self.storyboard["edit_policy"]["static_gameplay_max_seconds"],
            )

    def test_mechanism_takes_have_formal_chains_or_a_fail_closed_selection_gate(self) -> None:
        mechanism_take_ids = {
            item["take"]["take_id"]
            for item in self.subshots
            if item["asset_type"] == "mechanism_action"
        }
        for take_id in mechanism_take_ids:
            take = self.takes[take_id]
            if "formal_action_chain" in take:
                self.assertTrue(take["formal_action_chain"]["steps"], take_id)
                continue
            self.assertEqual("T06", take_id)
            self.assertEqual("pending", take["card_selection_status"])
            gate = take["card_selection_gate"]
            self.assertTrue(gate["must_bind_specific_card_id_before_recording_mark"])
            self.assertTrue(gate["cannot_transition_to_observed_while_status_pending"])
            self.assertEqual("conservation", gate["required_card_family"])
            self.assertEqual(
                {"VIVHITE_CARD_AXIOM_RING", "VIVHITE_CARD_CLOSED_PROJECTION"},
                set(gate["must_not_duplicate_card_ids"]),
            )

    def test_basic_growth_fatal_and_drain_takes_lock_cards_and_results(self) -> None:
        expected = {
            "T03": "VIVHITE_CARD_LUMINOUS_PROJECTION",
            "T04": "VIVHITE_CARD_VIVHITE_TRANSFORMATION",
            "T08": "VIVHITE_CARD_TOPOLOGICAL_GROWTH",
            "T09": "VIVHITE_CARD_SCALE_TRANSFORMATION",
            "T11": "VIVHITE_CARD_TRICHROMATIC_WALTZ",
        }
        for take_id, card_id in expected.items():
            chain = self.takes[take_id]["formal_action_chain"]
            self.assertEqual(card_id, chain["steps"][0]["card_id"])
            self.assertTrue(chain["steps"][0]["required_observations"])

        for take_id in ("T03", "T04"):
            state = self.takes[take_id]["recording_mark_setup"]["required_state"]
            self.assertEqual(0, state["initial_margin"])
            self.assertTrue(state["player_hp_strictly_greater_than_runtime_life_cost"])
            self.assertEqual(expected[take_id], state["card_id"])

        self.assertEqual(
            "enemy_damage",
            self.takes["T03"]["formal_action_chain"][
                "expected_post_payment_resolution"
            ],
        )
        t04_observations = self.takes["T04"]["formal_action_chain"]["steps"][0][
            "required_observations"
        ]
        self.assertTrue(any("Strength" in item for item in t04_observations))
        self.assertTrue(any("Dexterity" in item for item in t04_observations))
        t11_observations = self.takes["T11"]["formal_action_chain"]["steps"][0][
            "required_observations"
        ]
        self.assertIn("all three attack hits resolve", t11_observations)
        self.assertIn(
            "one actual healing event resolves after all attacks", t11_observations
        )

    def test_required_staged_setups_are_machine_readable(self) -> None:
        t05_state = self.takes["T05"]["recording_mark_setup"]["required_state"]
        self.assertEqual(
            ["VIVHITE_CARD_AXIOM_RING", "VIVHITE_CARD_CLOSED_PROJECTION"],
            t05_state["cards_unupgraded"],
        )
        self.assertEqual(0, t05_state["initial_margin"])
        self.assertEqual(0, t05_state["dexterity"])
        self.assertFalse(t05_state["frail"])
        self.assertGreaterEqual(
            self.takes["T08"]["recording_mark_setup"]["required_state"][
                "margin_minimum"
            ],
            8,
        )
        t09_state = self.takes["T09"]["recording_mark_setup"]["required_state"]
        self.assertTrue(t09_state["formal_target_is_low_hp_and_lethal"])
        self.assertTrue(t09_state["another_enemy_survives_formal_action"])
        t11_state = self.takes["T11"]["recording_mark_setup"]["required_state"]
        self.assertTrue(t11_state["player_missing_hp"])
        self.assertTrue(t11_state["target_survives_all_three_hits"])
        for take_id in ("T05", "T08", "T09", "T11"):
            setup = self.takes[take_id]["recording_mark_setup"]
            self.assertEqual("staged_setup", setup["provenance"])
            self.assertTrue(setup["must_finish_before_recording_mark"])
            self.assertTrue(setup["excluded_from_display"])

    def test_multiaction_takes_have_ordered_receipts_and_intermediate_states(self) -> None:
        t05 = self.takes["T05"]
        self.assertEqual(
            ["play_axiom_ring", "play_closed_projection"],
            [step["step_id"] for step in t05["formal_action_chain"]["steps"]],
        )
        self.assertEqual(
            ["T05-axiom-ring-receipt", "T05-closed-projection-receipt"],
            [step["receipt_ref"] for step in t05["formal_action_chain"]["steps"]],
        )
        self.assertEqual(
            "T05-state-after-axiom-ring",
            t05["formal_action_chain"]["steps"][1]["state_before_ref"],
        )

        t18 = self.takes["T18"]
        self.assertEqual(
            "VIVHITE_POWER_UNIFIED_FIELD_THEORY_POWER",
            t18["recording_mark_setup"]["required_state"]["power_active"],
        )
        self.assertTrue(t18["recording_mark_setup"]["excluded_from_display"])
        self.assertEqual(
            ["consume_margin_with_cough_skill", "play_drain_attack"],
            [step["step_id"] for step in t18["formal_action_chain"]["steps"]],
        )
        self.assertEqual(
            "T18-state-after-cough",
            t18["formal_action_chain"]["steps"][1]["state_before_ref"],
        )
        unified = next(
            item for item in self.subshots
            if item["subshot_id"] == "S09-02-unified-field-chain"
        )
        self.assertIn("T18-event-sequence", unified["evidence_refs"])

    def test_t18_runtime_divisor_and_margin_return_are_fail_closed(self) -> None:
        t18 = self.takes["T18"]
        state = t18["recording_mark_setup"]["required_state"]
        divisor = state["runtime_healing_divisor"]
        self.assertEqual(3, divisor["unupgraded"])
        self.assertEqual(2, divisor["upgraded"])
        self.assertEqual(
            "bind_from_current_runtime_tooltip", divisor["selected_value"]
        )
        for field in (
            "actual_healing_at_least_selected_divisor",
            "missing_hp_at_least_selected_divisor",
            "drain_attack_actual_damage_greater_than_zero",
            "drain_rate_sufficient_for_selected_divisor",
        ):
            self.assertTrue(state[field])
        assertion = t18["formal_action_chain"]["margin_return_assertion"]
        self.assertEqual("current_runtime_tooltip", assertion["healing_divisor_source"])
        self.assertEqual("floor(actual_healing / 3)", assertion["unupgraded_formula"])
        self.assertEqual("floor(actual_healing / 2)", assertion["upgraded_formula"])
        self.assertTrue(assertion["actual_healing_must_be_at_least_selected_divisor"])
        self.assertTrue(assertion["final_margin_strictly_greater_than_after_cough"])
        observations = t18["formal_action_chain"]["steps"][1][
            "required_observations"
        ]
        self.assertIn(
            "actual healing is at least the current runtime tooltip divisor",
            observations,
        )
        self.assertIn(
            "final margin is strictly greater than margin after the Cough action",
            observations,
        )

    def test_crimson_chain_is_one_contiguous_t16_take(self) -> None:
        t16 = self.takes["T16"]
        self.assertEqual(
            [
                "play_crimson_transformation_ritual",
                "end_turn",
                "play_phase1_attack",
            ],
            [step["step_id"] for step in t16["formal_action_chain"]["steps"]],
        )
        self.assertTrue(t16["formal_action_chain"]["single_continuous_source"])
        crimson = [
            item for item in self.subshots
            if item["subshot_id"] in {
                "S08-02-crimson-phase-zero",
                "S08-03-crimson-phase-one",
            }
        ]
        self.assertEqual(2, len(crimson))
        self.assertEqual({"T16"}, {item["take"]["take_id"] for item in crimson})
        self.assertEqual(
            {"T16-crimson-phase0-to-phase1"},
            {item["continuity_group"] for item in crimson},
        )
        self.assertTrue(all(item["must_be_source_contiguous"] for item in crimson))
        self.assertEqual("montage", self.takes["T17"]["asset_type"])

    def test_t12_t14_and_conditional_narration_encode_runtime_semantics(self) -> None:
        t12 = self.takes["T12"]
        setup = t12["recording_mark_setup"]
        self.assertEqual(
            "VIVHITE_POWER_COLOR_CONSERVATION_POWER",
            setup["required_state"]["power_active"],
        )
        self.assertTrue(setup["required_state"]["player_missing_hp"])
        self.assertTrue(setup["required_state"]["all_targets_survive_formal_attack"])
        self.assertIn(
            "actual_healing is greater than 0",
            t12["formal_action_chain"]["required_event_order"],
        )

        t14 = self.takes["T14"]
        self.assertEqual(
            {"minimum": 2, "maximum": 3},
            t14["formal_action_chain"]["kill_count"],
        )
        termination = next(
            item for item in self.subshots
            if item["subshot_id"] == "S07-02-termination-chain-a"
        )
        self.assertIn("T14-event-sequence", termination["evidence_refs"])
        conditional = next(
            item for item in self.subshots
            if item["subshot_id"] == "S07-03-termination-chain-b"
        )
        self.assertTrue(conditional["conditional_edit"]["split_is_editorial_metadata_only"])
        branch = conditional["conditional_edit"]
        self.assertEqual("T14", branch["fallback_take_id"])
        self.assertEqual("result_event_continuation", branch["fallback_mode"])
        self.assertEqual(
            "S07-02-termination-chain-a", branch["continuation_of_subshot_id"]
        )
        self.assertTrue(branch["must_be_source_contiguous"])
        self.assertTrue(branch["must_not_overlap_source"])
        self.assertFalse(branch["fallback_has_formal_input"])
        self.assertEqual(
            ["T14-event-sequence", "T14-state-after", "T14-frame-end"],
            conditional["fallback_evidence_refs"],
        )
        self.assertTrue(
            {"T15-state-before", "T15-action-receipt", "T15-state-after"}
            <= set(conditional["evidence_refs"])
        )
        self.assertNotIn("take", conditional["cue"]["narration_zh"].casefold())
        self.assertNotIn("事件太密", conditional["cue"]["narration_zh"])

    def test_death_chain_event_roles_drain_and_draw_requirements_are_precise(self) -> None:
        for take_id in ("T11", "T14", "T15"):
            roles = {
                item["ref_id"]: item["role"]
                for item in self.takes[take_id]["evidence_refs"]
            }
            self.assertEqual("action.sequence", roles[f"{take_id}-event-sequence"])
        t09_roles = {
            item["ref_id"]: item["role"]
            for item in self.takes["T09"]["evidence_refs"]
        }
        self.assertEqual("action.receipt", t09_roles["T09-death-receipt"])

        t14_chain = self.takes["T14"]["formal_action_chain"]
        self.assertEqual(
            ["Drain resolves before deferred death rewards"],
            t14_chain["required_event_order"],
        )
        self.assertEqual(
            {
                "Solitary Crown recovery resolves",
                "card draw resolves",
                "energy gain resolves",
            },
            set(t14_chain["unordered_required_events"]),
        )
        self.assertEqual("pending", t14_chain["runtime_order_status"])

        for take_id in ("T14", "T15"):
            take = self.takes[take_id]
            state = take["recording_mark_setup"]["required_state"]
            self.assertEqual(
                "VIVHITE_POWER_ASTRAL_PURSUIT_POWER", state["power_active"]
            )
            self.assertTrue(state["player_missing_hp"])
            self.assertTrue(
                state["missing_hp_sufficient_for_visible_actual_drain_healing"]
            )
            self.assertTrue(
                state["effective_global_or_turn_drain_percent_greater_than_zero"]
            )
            self.assertTrue(state["hand_has_room_for_visible_draws"])
            self.assertTrue(state["draw_pile_has_cards_for_visible_draws"])
            draw = take["formal_action_chain"]["draw_observation"]
            self.assertGreater(draw["actual_draw_delta_minimum"], 0)
            self.assertTrue(draw["must_not_assume_all_requested_draws_enter_hand"])
            observations = take["formal_action_chain"]["steps"][0][
                "required_observations"
            ]
            self.assertIn("actual_drain_healing is greater than 0", observations)
            self.assertIn("actual_draw_delta is greater than 0", observations)

    def test_opening_line_has_real_j_cut_audio_timing(self) -> None:
        subshot = self.subshots_by_id["S01-09-character-selection-j-cut"]
        self.assertEqual(28, subshot["timeline"]["start_seconds"])
        audio = subshot["cue"]["audio_timeline"]
        cut = subshot["cue"]["j_cut"]
        c007a_audio = self.cues_by_id["C007A"]["audio_timeline"]
        c007b_audio = self.cues_by_id["C007B"]["audio_timeline"]
        self.assertLessEqual(
            c007a_audio["end_seconds"], c007b_audio["start_seconds"]
        )
        self.assertLessEqual(c007b_audio["end_seconds"], audio["start_seconds"])
        self.assertLess(audio["start_seconds"], cut["visual_cut_seconds"])
        self.assertGreater(audio["end_seconds"], cut["visual_cut_seconds"])
        self.assertEqual(28, cut["visual_cut_seconds"])
        self.assertTrue(cut["audio_starts_before_visual"])
        self.assertTrue(cut["audio_crosses_visual_cut"])
        self.assertEqual(
            audio["duration_seconds"],
            audio["end_seconds"] - audio["start_seconds"],
        )

    def test_audience_narration_contains_no_production_instructions(self) -> None:
        forbidden = (
            "控制台",
            "这次实录",
            "HUD",
            "点击后",
            "一倍速",
            "不中断",
            "事件太密",
        )
        for cue_id in ("C015", "C021", "C030", "C031", "C034"):
            narration = self.cues_by_id[cue_id]["narration_zh"]
            for token in forbidden:
                self.assertNotIn(token, narration, (cue_id, token, narration))

    def test_t20_is_not_used_for_build_routes(self) -> None:
        route_bindings = {
            item["subshot_id"]: item["take"]["take_id"]
            for item in self.subshots
            if item["subshot_id"] in {
                "S10-02-conservation-route",
                "S10-03-recursive-route",
                "S10-04-crimson-route",
            }
        }
        self.assertEqual(
            {
                "S10-02-conservation-route": "T05",
                "S10-03-recursive-route": "T14",
                "S10-04-crimson-route": "T17",
            },
            route_bindings,
        )
        self.assertIn("build_route_montage", self.takes["T20"]["forbidden_uses"])

    def test_finale_version_and_workshop_status_use_distinct_authorities(self) -> None:
        subshot = self.subshots_by_id["S10-11-version-and-workshop-status"]
        cue = subshot["cue"]
        self.assertEqual(
            ["runtime_version", "workshop_status"], cue["template_fields"]
        )
        self.assertEqual(
            "T20-runtime-manifest", cue["template_evidence"]["runtime_version"]
        )
        self.assertEqual(
            "T20-workshop-status-receipt",
            cue["template_evidence"]["workshop_status"],
        )
        self.assertNotEqual(
            cue["template_evidence"]["runtime_version"],
            cue["template_evidence"]["workshop_status"],
        )
        self.assertEqual(
            {"T20-runtime-manifest", "T20-workshop-status-receipt"},
            set(subshot["evidence_refs"]),
        )
        roles = {
            item["ref_id"]: item["role"]
            for item in self.takes["T20"]["evidence_refs"]
        }
        self.assertEqual("runtime.manifest", roles["T20-runtime-manifest"])
        self.assertEqual(
            "workshop.readonly_metadata", roles["T20-workshop-status-receipt"]
        )

    def test_generated_cards_have_complete_factory_inputs(self) -> None:
        generated_types = {"title_card", "tower_title_card", "end_card"}
        generated = [
            item for item in self.subshots if item["asset_type"] in generated_types
        ]
        self.assertGreater(len(generated), 0)
        for item in generated:
            spec = item["title_card"]
            self.assertEqual(
                "vivhite_promo.title_cards_v2.create_title_card_spec_v2",
                spec["factory"],
            )
            self.assertTrue(spec["chinese_title"].strip())
            self.assertTrue(spec["english_subtitle"].strip())
            self.assertEqual(item["timeline"]["duration_seconds"], spec["duration_seconds"])
            self.assertNotIn("｜", spec["chinese_title"])
            self.assertNotEqual(spec["chinese_title"], spec["english_subtitle"])

    def test_audio_delivery_and_short_edit_policies_match_director_report(self) -> None:
        master = self.storyboard["master"]
        self.assertEqual((1920, 1080, 60), tuple(master["video"][key] for key in ("width", "height", "fps")))
        self.assertEqual(("h264", "yuv420p"), (master["video"]["codec"], master["video"]["pixel_format"]))
        self.assertEqual(("aac", 48000, 2), (master["audio"]["codec"], master["audio"]["sample_rate_hz"], master["audio"]["channels"]))
        self.assertFalse(master["bgm"])
        self.assertEqual("zh-CN-XiaoxiaoNeural", master["narration_voice"])
        mix = master["audio"]["mix_policy"]
        self.assertTrue(mix["duck_game_ambience_during_narration"])
        self.assertTrue(mix["keep_game_sfx_audible_during_narration"])
        self.assertEqual(
            {"attack", "healing", "card_draw", "map_node_click"},
            set(mix["foreground_sfx_events"]),
        )
        self.assertEqual(
            [{"kind": "character_selection_animation", "minimum_seconds": 6, "maximum_seconds": 8}],
            self.storyboard["edit_policy"]["static_gameplay_exceptions"],
        )
        for variant_id, duration in (("hero-60", 60), ("cut-30", 30), ("cut-15", 15)):
            variant = self.storyboard["variants"][variant_id]
            self.assertEqual(duration, variant["duration_seconds"])
            self.assertTrue(variant["independent_edl"])
            self.assertEqual("same_v2_take_batch", variant["source"])
            self.assertFalse(variant["from_signed_master"])
            self.assertEqual("not_started", variant["edl_status"])
            self.assertEqual(
                f"tools/promo/v2/edl/{variant_id}.json",
                variant["planned_edl_path"],
            )

    def test_main_title_identity_campfire_and_shop_requirements_are_explicit(self) -> None:
        by_id = {item["subshot_id"]: item for item in self.subshots}
        title = by_id["S01-07-main-title"]["visual_requirements"]
        self.assertTrue(title["start_from_black"])
        self.assertTrue(title["vivhite_silhouette_reveals_from_black"])
        self.assertEqual(["白绮 VIVHITE", "把生命写成魔法"], title["title_lines"])

        selection = by_id["S01-10-character-selection"]["selection_requirements"]
        self.assertEqual({"minimum": 6, "maximum": 8}, selection["portrait_animation_hold_seconds"])
        self.assertTrue(selection["must_not_crop_name_or_attributes"])
        self.assertIn("角色描述", selection["required_visible"])
        self.assertTrue(selection["confirm_and_enter_game"])

        campfire = by_id["S06-05-campfire-rest"]["tower_life_requirements"]
        self.assertEqual([2, 3], campfire["act"])
        self.assertTrue(campfire["return_to_map"])
        self.assertIn("T10-return-map-receipt", by_id["S06-05-campfire-rest"]["evidence_refs"])

        shop = by_id["S05-05-shop-purchase"]["tower_life_requirements"]
        self.assertTrue(shop["vivhite_and_merchant_wide_shot"])
        self.assertTrue(shop["close_inventory"])
        self.assertTrue(shop["leave_shop"])
        self.assertIn("T13-leave-shop-receipt", by_id["S05-05-shop-purchase"]["evidence_refs"])


if __name__ == "__main__":
    unittest.main()
