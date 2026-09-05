"""Pure offline tests for the 540-second director-v2 contract."""

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

from vivhite_promo import director_v2 as director  # noqa: E402


SHA = "A" * 64
DIRECTOR_BOUNDARIES = (0, 18, 28, 58, 78, 120, 168, 188, 232, 252, 306, 330, 382, 448, 496, 540)
TIMELINE_ORDER = (
    "S01-identity",
    "S02-loadout",
    "S03-cough",
    "S04-margin",
    # Director order intentionally differs from canonical numeric order.
    "S06-conservation-geometry",
    "S05-drain",
    "S07-recursive-star-calculus",
    "S08-crimson-integral",
    "S09-unified-field",
    "S10-finale",
)


def _evidence(take_id: str, *, bound: bool) -> list[dict[str, object]]:
    status = "verified" if bound else "pending"
    result: list[dict[str, object]] = []
    for role in (
        "state.before",
        "action.receipt",
        "state.after",
        "action.sequence",
        "frame.end",
    ):
        row: dict[str, object] = {
            "ref_id": f"{take_id}.{role}",
            "role": role,
            "status": status,
            "path": f"evidence/{take_id}/{role}.json" if bound else None,
        }
        if bound:
            row["sha256"] = SHA
        result.append(row)
    return result


def storyboard() -> dict[str, object]:
    takes: list[dict[str, object]] = []
    for index in range(1, 21):
        take_id = f"T{index:02d}"
        takes.append(
            {
                "take_id": take_id,
                "independent": True,
                "requirement": "conditional" if take_id == "T15" else "required",
                "asset_type": "combat" if index <= 10 else "support",
                "capture_status": "not_started",
                "staged_setup_allowed": True,
                "formal_display": {
                    "real_input": True,
                    "game_resolution": True,
                    "playback_speed": 1,
                    "uncut_action": True,
                },
                "source": {"artifact": None, "in_seconds": None, "out_seconds": None},
                "evidence_refs": _evidence(take_id, bound=False),
            }
        )

    shots: list[dict[str, object]] = []
    cursor = 0.0
    for index, shot_id in enumerate(TIMELINE_ORDER, 1):
        take_id = f"T{index:02d}"
        card_id = f"SS{index:02d}-card"
        action_id = f"SS{index:02d}-action"
        shots.append(
            {
                "shot_id": shot_id,
                "chapter_id": shot_id.split("-", 1)[1],
                "title": shot_id,
                "timeline": {
                    "start_seconds": cursor,
                    "end_seconds": cursor + 54,
                    "duration_seconds": 54,
                },
                "subshots": [
                    {
                        "subshot_id": card_id,
                        "asset_type": "title_card",
                        "take": {
                            "take_id": None,
                            "independent": False,
                            "generator": "xar.TitleCardSpec",
                        },
                        "timeline": {
                            "start_seconds": cursor,
                            "end_seconds": cursor + 2,
                            "duration_seconds": 2,
                        },
                        "source": {
                            "in_seconds": None,
                            "out_seconds": None,
                            "status": "capture_pending",
                        },
                        "cue": {
                            "cue_id": f"C{index:02d}-card",
                            "kind": "title",
                            "narration_zh": "机制关系",
                            "subtitle_zh": "机制关系",
                            "subtitle_en": "Mechanic relationship",
                            "voice_asset": None,
                        },
                        "provenance": "editorial_derived",
                        "evidence_refs": ["director.plan"],
                        "title_card": {
                            "factory": "vivhite_promo.title_cards_v2.create_title_card_spec_v2",
                            "chinese_title": "机制关系",
                            "english_subtitle": "Mechanic relationship",
                            "duration_seconds": 2,
                        },
                    },
                    {
                        "subshot_id": action_id,
                        "asset_type": "mechanism_action",
                        "take": {"take_id": take_id, "independent": True},
                        "timeline": {
                            "start_seconds": cursor + 2,
                            "end_seconds": cursor + 54,
                            "duration_seconds": 52,
                        },
                        "source": {
                            "in_seconds": None,
                            "out_seconds": None,
                            "status": "capture_pending",
                        },
                        "cue": {
                            "cue_id": f"C{index:02d}-action",
                            "kind": "narration",
                            "narration_zh": "观察结算。",
                            "subtitle_zh": "观察结算。",
                            "subtitle_en": "Watch the resolution.",
                            "voice_asset": None,
                        },
                        "provenance": "runtime_observed",
                        "evidence_refs": [
                            f"{take_id}.state.before",
                            f"{take_id}.action.receipt",
                            f"{take_id}.state.after",
                        ],
                    },
                ],
            }
        )
        cursor += 54

    director_sections = []
    for section_index, (start, end) in enumerate(
        zip(DIRECTOR_BOUNDARIES, DIRECTOR_BOUNDARIES[1:]), 1
    ):
        director_sections.append(
            {
                "section_id": director.DIRECTOR_SECTION_IDS[section_index - 1],
                "title": f"Section {section_index}",
                "timeline": {
                    "start_seconds": start,
                    "end_seconds": end,
                    "duration_seconds": end - start,
                    "start_frame": start * 60,
                    "end_frame": end * 60,
                    "duration_frames": (end - start) * 60,
                },
            }
        )

    return {
        "schema_version": 2,
        "kind": "vivhite_promo_storyboard_v2",
        "target_duration_seconds": 540,
        "timebase": {"frames_per_second": 60, "target_frames": 32400},
        "director_sections": director_sections,
        "status": "planning",
        "legacy_policy": {"a4_as_source": False, "a4_usage": "reference_only"},
        "master": {
            "duration_seconds": 540,
            "video": {
                "width": 1920,
                "height": 1080,
                "fps": 60,
                "codec": "h264",
                "pixel_format": "yuv420p",
            },
            "audio": {"codec": "aac", "sample_rate_hz": 48000, "channels": 2},
            "narration_voice": "zh-CN-XiaoxiaoNeural",
            "bgm": False,
        },
        "canonical_shot_ids": list(director.CANONICAL_SHOT_IDS),
        "take_policy": {
            "minimum_independent_takes": 19,
            "maximum_independent_takes": 20,
            "conditional_take_id": "T15",
        },
        "edit_policy": {"shorts_from_signed_master": False},
        "acceptance_gates": {},
        "variants": {
            "hero-60": {
                "duration_seconds": 60,
                "independent_edl": True,
                "source": "same_v2_take_batch",
                "from_signed_master": False,
            },
            "cut-30": {
                "duration_seconds": 30,
                "independent_edl": True,
                "source": "same_v2_take_batch",
                "from_signed_master": False,
            },
            "cut-15": {
                "duration_seconds": 15,
                "independent_edl": True,
                "source": "same_v2_take_batch",
                "from_signed_master": False,
            },
        },
        "takes": takes,
        "shots": shots,
    }


def take_manifest() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for index in range(1, 21):
        take_id = f"T{index:02d}"
        spans: list[dict[str, object]] = []
        if index <= 10:
            spans.append(
                {
                    "subshot_id": f"SS{index:02d}-action",
                    "in_seconds": 3,
                    "out_seconds": 55,
                }
            )
        rows.append(
            {
                "take_id": take_id,
                "independent": True,
                "source": {
                    "artifact": f"raw/takes/{take_id}/attempt-001.mkv",
                    "duration_seconds": 60,
                    "bytes": 10_000 + index,
                    "sha256": f"{index:064X}",
                },
                "evidence_refs": _evidence(take_id, bound=True),
                "spans": spans,
            }
        )
    return {
        "schema_version": 2,
        "kind": "vivhite_promo_take_manifest_v2",
        "batch_id": "batch-v2-001",
        "source_strategy": "independent_take_files",
        "from_legacy_a4": False,
        "takes": rows,
    }


def conditional_fallback_case(
    *, omit_t15: bool = True
) -> tuple[dict[str, object], dict[str, object], str, str]:
    """Build a T15 action with an honest T14 result-continuation fallback."""

    board = storyboard()
    manifest = take_manifest()
    action = board["shots"][0]["subshots"][1]
    predecessor_id = str(action["subshot_id"])
    action["take"] = {"take_id": "T14", "independent": True}
    action["timeline"] = {
        "start_seconds": 2,
        "end_seconds": 28,
        "duration_seconds": 26,
    }
    action["evidence_refs"] = [
        "T14.state.before",
        "T14.action.receipt",
        "T14.state.after",
    ]

    conditional = copy.deepcopy(action)
    subshot_id = f"{predecessor_id}-conditional"
    conditional["subshot_id"] = subshot_id
    conditional["timeline"] = {
        "start_seconds": 28,
        "end_seconds": 54,
        "duration_seconds": 26,
    }
    conditional["cue"]["cue_id"] = "C01-action-conditional"
    conditional["take"] = {
        "take_id": "T15",
        "independent": True,
        "requirement": "conditional",
        "fallback_take_id": "T14",
    }
    conditional["evidence_refs"] = [
        "T15.state.before",
        "T15.action.receipt",
        "T15.state.after",
    ]
    conditional["conditional_edit"] = {
        "fallback_take_id": "T14",
        "fallback_mode": "result_event_continuation",
        "continuation_of_subshot_id": predecessor_id,
        "must_be_source_contiguous": True,
        "must_not_overlap_source": True,
        "fallback_has_formal_input": False,
    }
    conditional["fallback_evidence_refs"] = [
        "T14.action.sequence",
        "T14.state.after",
        "T14.frame.end",
    ]
    board["shots"][0]["subshots"].append(conditional)

    t01 = next(row for row in manifest["takes"] if row["take_id"] == "T01")
    t14 = next(row for row in manifest["takes"] if row["take_id"] == "T14")
    t01["spans"].pop()
    t14["spans"].append(
        {"subshot_id": predecessor_id, "in_seconds": 3, "out_seconds": 29}
    )
    if omit_t15:
        t14["spans"].append(
            {"subshot_id": subshot_id, "in_seconds": 29, "out_seconds": 55}
        )
        manifest["takes"] = [
            row for row in manifest["takes"] if row["take_id"] != "T15"
        ]
    else:
        t15 = next(row for row in manifest["takes"] if row["take_id"] == "T15")
        t15["spans"].append(
            {"subshot_id": subshot_id, "in_seconds": 3, "out_seconds": 29}
        )
    return board, manifest, subshot_id, predecessor_id


class DirectorV2StoryboardTests(unittest.TestCase):
    def test_checked_in_storyboard_v2_passes_the_repository_gate(self) -> None:
        path = PROMO_ROOT / "v2" / "storyboard.json"
        self.assertTrue(path.is_file(), path)
        payload = director.load_storyboard_v2(path)
        self.assertEqual(540, payload["master"]["duration_seconds"])
        self.assertEqual(20, len(payload["takes"]))
        self.assertEqual(10, len(payload["shots"]))
        self.assertEqual(
            51,
            sum(len(shot["subshots"]) for shot in payload["shots"]),
        )

    def test_valid_plan_accepts_canonical_order_separate_from_timeline_order(self) -> None:
        payload = storyboard()
        validated = director.load_storyboard_v2(payload)
        self.assertEqual(540, validated["master"]["duration_seconds"])
        self.assertEqual(list(TIMELINE_ORDER), [row["shot_id"] for row in validated["shots"]])

        with tempfile.TemporaryDirectory(prefix="vivhite-director-v2-") as raw:
            path = Path(raw) / "storyboard.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(
                list(director.CANONICAL_SHOT_IDS),
                director.load_storyboard_v2(path)["canonical_shot_ids"],
            )

    def test_master_duration_and_subshot_continuity_are_hard_gates(self) -> None:
        payload = storyboard()
        payload["master"]["duration_seconds"] = 539
        with self.assertRaisesRegex(director.DirectorV2Error, "exactly 540"):
            director.validate_storyboard_v2(payload)

        payload = storyboard()
        payload["shots"][1]["subshots"][0]["timeline"]["start_seconds"] += 0.5
        payload["shots"][1]["subshots"][0]["timeline"]["end_seconds"] += 0.5
        with self.assertRaisesRegex(director.DirectorV2Error, "gap"):
            director.validate_storyboard_v2(payload)

    def test_director_section_report_boundaries_are_exact(self) -> None:
        payload = storyboard()
        director.validate_storyboard_v2(payload)
        section = payload["director_sections"][6]
        section["timeline"]["end_seconds"] = 189
        section["timeline"]["duration_seconds"] = 21
        section["timeline"]["end_frame"] = 189 * 60
        section["timeline"]["duration_frames"] = 21 * 60
        with self.assertRaisesRegex(director.DirectorV2Error, "report boundary"):
            director.validate_storyboard_v2(payload)

    def test_canonical_ids_and_nineteen_or_twenty_take_policy_are_enforced(self) -> None:
        payload = storyboard()
        payload["canonical_shot_ids"][0] = "S01-ironclad"
        with self.assertRaisesRegex(director.DirectorV2Error, "canonical_shot_ids"):
            director.validate_storyboard_v2(payload)

        payload = storyboard()
        payload["takes"] = [row for row in payload["takes"] if row["take_id"] != "T15"]
        director.validate_storyboard_v2(payload)

        payload["takes"].pop()
        with self.assertRaisesRegex(director.DirectorV2Error, "19 or 20"):
            director.validate_storyboard_v2(payload)

    def test_mechanism_action_requires_three_part_evidence(self) -> None:
        payload = storyboard()
        action = payload["shots"][0]["subshots"][1]
        action["evidence_refs"].pop()
        with self.assertRaisesRegex(director.DirectorV2Error, "state.after"):
            director.validate_storyboard_v2(payload)

    def test_montage_lineage_cannot_reuse_a_formal_action_receipt(self) -> None:
        payload = storyboard()
        action = payload["shots"][0]["subshots"][1]
        action["timeline"] = {
            "start_seconds": 2,
            "end_seconds": 28,
            "duration_seconds": 26,
        }
        montage = copy.deepcopy(action)
        montage.update(
            {
                "subshot_id": "SS01-montage",
                "asset_type": "montage",
                "timeline": {
                    "start_seconds": 28,
                    "end_seconds": 54,
                    "duration_seconds": 26,
                },
                "montage_lineage": {
                    "source_subshot_id": "SS01-action",
                    "reuse_kind": "editorial_excerpt",
                    "formal_action_claimed": False,
                },
                "evidence_refs": [
                    "T01.action.sequence",
                    "T01.frame.end",
                ],
            }
        )
        montage["cue"]["cue_id"] = "C01-montage"
        payload["shots"][0]["subshots"].append(montage)
        director.validate_storyboard_v2(payload)

        montage["evidence_refs"].append("T01.action.receipt")
        with self.assertRaisesRegex(
            director.DirectorV2Error, "forbidden roles: action.receipt"
        ):
            director.validate_storyboard_v2(payload)

    def test_checked_in_character_select_j_cut_crosses_visual_boundary(self) -> None:
        path = PROMO_ROOT / "v2" / "storyboard.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        cues = {
            subshot["cue"]["cue_id"]: subshot["cue"]
            for shot in payload["shots"]
            for subshot in shot["subshots"]
        }
        c008a = cues["C008A"]
        self.assertLessEqual(
            cues["C007A"]["audio_timeline"]["end_seconds"],
            cues["C007B"]["audio_timeline"]["start_seconds"],
        )
        self.assertLessEqual(
            cues["C007B"]["audio_timeline"]["end_seconds"],
            c008a["audio_timeline"]["start_seconds"],
        )
        self.assertLess(c008a["audio_timeline"]["start_seconds"], 28)
        self.assertGreater(c008a["audio_timeline"]["end_seconds"], 28)
        c008a["audio_timeline"]["start_seconds"] = 28
        c008a["audio_timeline"]["duration_seconds"] = 5
        with self.assertRaisesRegex(director.DirectorV2Error, "start before"):
            director.validate_storyboard_v2(payload)

        payload = json.loads(path.read_text(encoding="utf-8"))
        cues = {
            subshot["cue"]["cue_id"]: subshot["cue"]
            for shot in payload["shots"]
            for subshot in shot["subshots"]
        }
        cues["C007B"]["audio_timeline"]["end_seconds"] = 27
        cues["C007B"]["audio_timeline"]["duration_seconds"] = 4
        with self.assertRaisesRegex(director.DirectorV2Error, "must end before"):
            director.validate_storyboard_v2(payload)

    def test_title_card_audio_and_short_edit_policies_are_enforced(self) -> None:
        payload = storyboard()
        del payload["shots"][0]["subshots"][0]["title_card"]
        with self.assertRaisesRegex(director.DirectorV2Error, "title_card must be"):
            director.validate_storyboard_v2(payload)

        payload = storyboard()
        card = payload["shots"][0]["subshots"][0]
        action = payload["shots"][0]["subshots"][1]
        card["timeline"]["end_seconds"] = 3.1
        card["timeline"]["duration_seconds"] = 3.1
        card["title_card"]["duration_seconds"] = 3.1
        action["timeline"]["start_seconds"] = 3.1
        action["timeline"]["duration_seconds"] = 50.9
        with self.assertRaisesRegex(director.DirectorV2Error, "3s duration limit"):
            director.validate_storyboard_v2(payload)

        payload = storyboard()
        payload["master"]["bgm"] = True
        with self.assertRaisesRegex(director.DirectorV2Error, "bgm=false"):
            director.validate_storyboard_v2(payload)

        payload = storyboard()
        payload["master"]["narration_voice"] = "another-voice"
        with self.assertRaisesRegex(director.DirectorV2Error, "Xiaoxiao"):
            director.validate_storyboard_v2(payload)

        payload = storyboard()
        payload["variants"]["cut-15"]["from_signed_master"] = True
        with self.assertRaisesRegex(director.DirectorV2Error, "signed master"):
            director.validate_storyboard_v2(payload)


class DirectorV2EdlTests(unittest.TestCase):
    def test_bound_independent_takes_build_a_sorted_multi_segment_edl(self) -> None:
        board = storyboard()
        j_cut_cue = board["shots"][0]["subshots"][1]["cue"]
        j_cut_cue["audio_timeline"] = {
            "start_seconds": 1,
            "end_seconds": 3,
            "duration_seconds": 2,
        }
        j_cut_cue["j_cut"] = {
            "visual_cut_seconds": 2,
            "audio_starts_before_visual": True,
            "audio_crosses_visual_cut": True,
        }
        result = director.build_multitake_edl(board, take_manifest())
        self.assertEqual("vivhite_promo_multi_take_edl_v2", result["kind"])
        self.assertEqual(540, result["target_duration_seconds"])
        self.assertEqual(20, result["authoring"]["independent_take_count"])
        self.assertEqual(20, len(result["segments"]))
        self.assertEqual(20, len(result["cues"]))
        self.assertEqual(
            list(range(0, 540, 54)),
            [item["timeline"]["start_seconds"] for item in result["segments"][::2]],
        )
        self.assertEqual("generated_title_card", result["segments"][0]["source"]["kind"])
        self.assertEqual(
            "vivhite_promo.title_cards_v2.create_title_card_spec_v2",
            result["segments"][0]["source"]["spec"]["factory"],
        )
        self.assertEqual("video_take", result["segments"][1]["source"]["kind"])
        self.assertEqual("T01", result["segments"][1]["source"]["take_id"])
        self.assertFalse(result["from_signed_master"])
        self.assertFalse(result["audio"]["bgm"])
        self.assertEqual("draft_unverified", result["authoring"]["status"])
        self.assertTrue(result["authoring"]["production_file_verification_required"])
        self.assertEqual(10_001, result["segments"][1]["source"]["bytes"])
        emitted_cue = next(
            cue for cue in result["cues"] if cue["cue_id"] == "C01-action"
        )
        self.assertEqual(j_cut_cue["audio_timeline"], emitted_cue["audio_timeline"])
        self.assertEqual(j_cut_cue["j_cut"], emitted_cue["j_cut"])

    def test_manifest_may_omit_only_conditional_t15(self) -> None:
        manifest = take_manifest()
        manifest["takes"] = [row for row in manifest["takes"] if row["take_id"] != "T15"]
        result = director.build_edl(storyboard(), manifest)
        self.assertEqual(19, result["authoring"]["independent_take_count"])

    def test_t15_omission_switches_to_t14_fallback_evidence(self) -> None:
        board, manifest, subshot_id, predecessor_id = conditional_fallback_case()
        result = director.build_edl(board, manifest)
        segment = next(
            row for row in result["segments"] if row["subshot_id"] == subshot_id
        )
        self.assertEqual("T14", segment["source"]["take_id"])
        self.assertTrue(segment["source"]["fallback_used"])
        self.assertEqual("T15", segment["source"]["requested_take_id"])
        self.assertEqual(
            [
                "T14.action.sequence",
                "T14.state.after",
                "T14.frame.end",
            ],
            segment["evidence_refs"],
        )
        self.assertEqual(
            "result_event_continuation", segment["source"]["resolved_semantics"]
        )
        self.assertFalse(segment["formal_action_claimed"])
        self.assertEqual(predecessor_id, segment["continuation_of_subshot_id"])

        # This would pass if validate_take_manifest incorrectly kept checking
        # the unused T15 refs after resolving the T14 source binding.
        t14 = next(row for row in manifest["takes"] if row["take_id"] == "T14")
        t14["evidence_refs"] = [
            row
            for row in t14["evidence_refs"]
            if row["role"] != "state.after"
        ]
        with self.assertRaisesRegex(
            director.DirectorV2Error, "T14 lacks bound evidence"
        ):
            director.validate_take_manifest(board, manifest)

    def test_t15_present_is_a_full_independent_mechanism_action(self) -> None:
        board, manifest, subshot_id, _predecessor_id = conditional_fallback_case(
            omit_t15=False
        )
        result = director.build_edl(board, manifest)
        segment = next(
            row for row in result["segments"] if row["subshot_id"] == subshot_id
        )
        self.assertEqual("T15", segment["source"]["take_id"])
        self.assertFalse(segment["source"]["fallback_used"])
        self.assertEqual("formal_action", segment["source"]["resolved_semantics"])
        self.assertTrue(segment["formal_action_claimed"])
        self.assertEqual(
            [
                "T15.state.before",
                "T15.action.receipt",
                "T15.state.after",
            ],
            segment["evidence_refs"],
        )

    def test_t14_continuation_fallback_rejects_gap_and_overlap(self) -> None:
        for bad_in, bad_out, expected in (
            (30, 56, "gap"),
            (28, 54, "overlaps"),
        ):
            with self.subTest(bad_in=bad_in):
                board, manifest, subshot_id, _predecessor_id = conditional_fallback_case()
                t14 = next(
                    row for row in manifest["takes"] if row["take_id"] == "T14"
                )
                span = next(
                    row for row in t14["spans"] if row["subshot_id"] == subshot_id
                )
                span["in_seconds"] = bad_in
                span["out_seconds"] = bad_out
                with self.assertRaisesRegex(director.DirectorV2Error, expected):
                    director.validate_take_manifest(board, manifest)

    def test_continuation_fallback_cannot_claim_second_action_evidence(self) -> None:
        board, _manifest, _subshot_id, _predecessor_id = conditional_fallback_case()
        conditional = board["shots"][0]["subshots"][2]
        conditional["fallback_evidence_refs"] = [
            "T14.state.before",
            "T14.action.receipt",
            "T14.state.after",
        ]
        with self.assertRaisesRegex(director.DirectorV2Error, "action.sequence"):
            director.validate_storyboard_v2(board)

    def test_manifest_rejects_a4_lineage_and_non_independent_files(self) -> None:
        manifest = take_manifest()
        manifest["takes"][0]["source"]["artifact"] = (
            "runs/run-20260902T-full-master-tts-a4/raw.mp4"
        )
        with self.assertRaisesRegex(director.DirectorV2Error, "legacy a4"):
            director.validate_take_manifest(storyboard(), manifest)

        manifest = take_manifest()
        manifest["takes"][1]["source"]["artifact"] = manifest["takes"][0]["source"]["artifact"]
        with self.assertRaisesRegex(director.DirectorV2Error, "distinct media files"):
            director.validate_take_manifest(storyboard(), manifest)

        manifest = take_manifest()
        manifest["takes"][1]["source"]["sha256"] = manifest["takes"][0]["source"]["sha256"]
        with self.assertRaisesRegex(director.DirectorV2Error, "distinct source SHA-256"):
            director.validate_take_manifest(storyboard(), manifest)

        manifest = take_manifest()
        manifest["takes"][0]["source"]["bytes"] = 0
        with self.assertRaisesRegex(director.DirectorV2Error, "bytes must be an integer >= 1"):
            director.validate_take_manifest(storyboard(), manifest)

    def test_manifest_requires_hash_bound_mechanism_evidence(self) -> None:
        manifest = take_manifest()
        manifest["takes"][0]["evidence_refs"][2]["status"] = "pending"
        with self.assertRaisesRegex(director.DirectorV2Error, "verified or bound"):
            director.build_multitake_edl(storyboard(), manifest)

    def test_manifest_span_boundaries_must_land_on_sixty_fps_frames(self) -> None:
        manifest = take_manifest()
        span = manifest["takes"][0]["spans"][0]
        # Preserve the exact 52-second duration so the frame-alignment gate,
        # rather than the duration comparison, is what rejects this binding.
        span["in_seconds"] = 3.001
        span["out_seconds"] = 55.001
        with self.assertRaisesRegex(director.DirectorV2Error, "integer frame"):
            director.validate_take_manifest(storyboard(), manifest)


if __name__ == "__main__":
    unittest.main()
