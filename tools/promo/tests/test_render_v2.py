"""Execution-boundary tests for the Vivhite director-v2 renderer."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
PROMO_ROOT = ROOT / "tools" / "promo"
import sys

if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

from vivhite_promo import render_v2 as render  # noqa: E402


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def _binding(path: str, payload: bytes) -> dict[str, object]:
    return {"path": path, "bytes": len(payload), "sha256": _digest(payload)}


def _authoring() -> dict[str, object]:
    return {
        "status": "production_verified",
        "offline_only": False,
        "source_verification": "bytes_sha256_ffprobe_verified",
        "action_evidence_verification": "path_loaded_and_hash_bound",
        "production_file_verification_required": False,
    }


def _probe(duration: float) -> dict[str, object]:
    return {
        "duration_seconds": duration,
        "width": 1920,
        "height": 1080,
        "fps": 60,
        "frame_count": round(duration * 60),
        "has_audio": True,
        "audio_sample_rate_hz": 48000,
        "audio_channels": 2,
    }


def _edl(files: dict[str, bytes]) -> dict[str, object]:
    segments = [
        {
            "segment_id": "seg-1",
            "shot_id": "S01-identity",
            "subshot_id": "sub-1",
            "asset_type": "montage",
            "timeline": {"start_seconds": 0, "end_seconds": 5, "duration_seconds": 5},
            "duration_seconds": 5,
            "source": {
                "kind": "video_take",
                "take_id": "T01",
                **_binding("takes/T01.mp4", files["takes/T01.mp4"]),
                "in_seconds": 1,
                "out_seconds": 6,
                "verification": "production_verified",
                "probe": _probe(10),
            },
            "cue_id": "C001",
        },
        {
            "segment_id": "seg-2",
            "shot_id": "S03-cough",
            "subshot_id": "sub-2",
            "asset_type": "mechanism_action",
            "timeline": {"start_seconds": 5, "end_seconds": 10, "duration_seconds": 5},
            "duration_seconds": 5,
            "source": {
                "kind": "video_take",
                "take_id": "T02",
                **_binding("takes/T02.mp4", files["takes/T02.mp4"]),
                "in_seconds": 2,
                "out_seconds": 7,
                "verification": "production_verified",
                "probe": _probe(10),
            },
            "cue_id": "C002",
            "formal_action_claimed": True,
        },
        {
            "segment_id": "seg-3",
            "shot_id": "S10-finale",
            "subshot_id": "sub-3",
            "asset_type": "end_card",
            "timeline": {"start_seconds": 10, "end_seconds": 15, "duration_seconds": 5},
            "duration_seconds": 5,
            "source": {
                "kind": "generated_title_card",
                "generator": "xar.TitleCardSpec",
                "spec": {
                    "factory": "vivhite_promo.title_cards_v2.create_title_card_spec_v2",
                    "chinese_title": "白绮",
                    "english_subtitle": "VIVHITE",
                    "duration_seconds": 5,
                },
            },
            "cue_id": "C003",
        },
    ]
    cues = [
        {
            "cue_id": "C001",
            "segment_id": "seg-1",
            "kind": "game_audio_only",
            "timeline_start_seconds": 0,
            "narration_zh": "",
            "subtitle_zh": "",
            "subtitle_en": "",
            "voice_asset": None,
        },
        {
            "cue_id": "C002",
            "segment_id": "seg-2",
            "kind": "narration",
            "timeline_start_seconds": 5,
            "narration_zh": "我只是想要成为我自己。",
            "subtitle_zh": "我只是想要成为我自己。",
            "subtitle_en": "I only want to become myself.",
            "voice_asset": None,
            "audio_timeline": {
                "start_seconds": 4,
                "end_seconds": 7,
                "duration_seconds": 3,
            },
            "j_cut": {
                "visual_cut_seconds": 5,
                "audio_starts_before_visual": True,
                "audio_crosses_visual_cut": True,
            },
        },
        {
            "cue_id": "C003",
            "segment_id": "seg-3",
            "kind": "end_card",
            "timeline_start_seconds": 10,
            "narration_zh": "",
            "subtitle_zh": "白绮",
            "subtitle_en": "VIVHITE",
            "voice_asset": None,
        },
    ]
    return {
        "schema_version": 2,
        "kind": "vivhite_promo_multi_take_edl_v2",
        "edit_id": "cut-15",
        "source_strategy": "independent_take_manifest",
        "take_batch_id": "run-test-v2",
        "from_signed_master": False,
        "target_duration_seconds": 15,
        "canvas": {"width": 1920, "height": 1080, "fps": 60},
        "audio": {
            "bgm": False,
            "narration_voice": "zh-CN-XiaoxiaoNeural",
            "sample_rate_hz": 48000,
            "channels": 2,
        },
        "canonical_shot_ids": [f"S{i:02d}" for i in range(1, 11)],
        "segments": segments,
        "cues": cues,
        "authoring": _authoring(),
    }


def _narration(files: dict[str, bytes]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "vivhite_promo_narration_manifest_v2",
        "revision_id": "director-v2",
        "run_id": "run-test-v2",
        "take_batch_id": "run-test-v2",
        "path_base": "run_root",
        "voice": "zh-CN-XiaoxiaoNeural",
        "bgm": False,
        "status": "production_verified",
        "cues": [
            {
                "cue_id": "C002",
                "chapter_id": "cough",
                "shot_id": "S03-cough",
                "subshot_id": "sub-2",
                "status": "production_verified",
                "voice": "zh-CN-XiaoxiaoNeural",
                "narration_zh": "我只是想要成为我自己。",
                "subtitle_zh": "我只是想要成为我自己。",
                "subtitle_en": "I only want to become myself.",
                "audio": {
                    **_binding("audio/C002.wav", files["audio/C002.wav"]),
                    "duration_seconds": 2.5,
                },
            }
        ],
    }


def _title_resources(files: dict[str, bytes]) -> dict[str, object]:
    return {
        "schema_version": 2,
        "kind": "vivhite_promo_title_resources_v2",
        "status": "production_verified",
        "path_base": "run_root",
        "fonts": {
            "vivhite_title_zh_v2": {
                **_binding("resources/title.ttf", files["resources/title.ttf"]),
                "size_px": 96,
            },
            "vivhite_subtitle_en_v2": {
                **_binding("resources/subtitle.ttf", files["resources/subtitle.ttf"]),
                "size_px": 40,
            },
        },
        "assets": {
            "vivhite_blue_butterfly_v2": _binding(
                "resources/butterfly.png", files["resources/butterfly.png"]
            )
        },
    }


def _lock() -> dict[str, object]:
    return {
        "kind": "vivhite_promo_ffmpeg_lock",
        "windows_install": {
            "ffmpeg": {"sha256": "A" * 64},
            "ffprobe": {"sha256": "B" * 64},
        },
    }


class RenderV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = {
            "takes/T01.mp4": b"take-one",
            "takes/T02.mp4": b"take-two",
            "audio/C002.wav": b"narration",
            "resources/title.ttf": b"title-font",
            "resources/subtitle.ttf": b"subtitle-font",
            "resources/butterfly.png": b"butterfly",
        }
        for relative, payload in self.files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self.lock_path = self.root / "ffmpeg-lock.json"
        self.lock_path.write_text(json.dumps(_lock()), encoding="utf-8")
        self.edl = _edl(self.files)
        self.narration = _narration(self.files)
        self.resources = _title_resources(self.files)

    def plan(self, *, suffix: str = "attempt") -> render.RenderPlanV2:
        return render.build_render_plan_v2(
            self.edl,
            self.narration,
            self.resources,
            artifact_root=self.root,
            output_root=self.root / suffix,
            ffmpeg=self.root / "ffmpeg.exe",
            ffprobe=self.root / "ffprobe.exe",
            ffmpeg_lock=self.lock_path,
            verify_files=True,
            verify_tools=False,
        )

    def test_plan_uses_independent_take_paths_and_exact_windows(self) -> None:
        plan = self.plan().to_mapping()
        self.assertEqual(15, plan["target_duration_seconds"])
        self.assertEqual("independent_take_files", plan["source_strategy"])
        self.assertFalse(plan["from_signed_master"])
        takes = [item for item in plan["segments"] if item["source_kind"] == "video_take"]
        self.assertEqual(["T01", "T02"], [item["take_id"] for item in takes])
        self.assertEqual([(1.0, 6.0), (2.0, 7.0)], [(item["in_seconds"], item["out_seconds"]) for item in takes])
        argv = plan["argv"]
        self.assertIn((self.root / "takes/T01.mp4").as_posix(), argv)
        self.assertIn((self.root / "takes/T02.mp4").as_posix(), argv)
        self.assertNotIn("master-540.mp4", " ".join(argv))

        invalid = copy.deepcopy(self.edl)
        invalid["segments"][1]["source"]["in_seconds"] = 8
        invalid["segments"][1]["source"]["out_seconds"] = 13
        with self.assertRaisesRegex(render.RenderV2Error, "exceeds probed"):
            render.validate_production_edl_v2(invalid)

    def test_jcut_and_upper_safe_subtitles_use_absolute_audio_time(self) -> None:
        plan = self.plan().to_mapping()
        window = plan["narration"][0]
        self.assertEqual(4.0, window["start_seconds"])
        self.assertEqual(6.5, window["end_seconds"])
        self.assertIn("adelay=delays=4000:all=1", plan["filtergraph"])
        subtitles = [
            item for item in plan["subtitle_and_overlay_events"] if item["cue_id"] == "C002"
        ]
        self.assertEqual({"ChineseUpper", "EnglishUpper"}, {item["style"] for item in subtitles})
        self.assertTrue(all(item["start_seconds"] == 4 for item in subtitles))
        self.assertNotIn("Style: Chinese,", plan["ass_content"])

        too_short = copy.deepcopy(self.narration)
        too_short["cues"][0]["audio"]["duration_seconds"] = 0.5
        with self.assertRaisesRegex(render.RenderV2Error, "no longer crosses"):
            render.build_render_plan_v2(
                self.edl,
                too_short,
                self.resources,
                artifact_root=self.root,
                output_root=self.root / "short-jcut",
                ffmpeg=self.root / "ffmpeg.exe",
                ffprobe=self.root / "ffprobe.exe",
                ffmpeg_lock=self.lock_path,
                verify_tools=False,
            )

    def test_audio_mix_contains_game_and_per_cue_narration_but_no_bgm(self) -> None:
        plan = self.plan().to_mapping()
        self.assertFalse(plan["bgm"])
        self.assertEqual(1, len(plan["narration"]))
        self.assertIn("amix=inputs=2", plan["filtergraph"])
        self.assertNotIn("bgm", " ".join(plan["argv"]).casefold())
        invalid = copy.deepcopy(self.edl)
        invalid["audio"]["bgm"] = True
        with self.assertRaisesRegex(render.RenderV2Error, "no-BGM"):
            render.validate_production_edl_v2(invalid)

    def test_missing_title_resource_and_unverified_inputs_fail_before_process(self) -> None:
        invalid_resources = copy.deepcopy(self.resources)
        del invalid_resources["assets"]["vivhite_blue_butterfly_v2"]
        with mock.patch("subprocess.run", side_effect=AssertionError("process started")) as run:
            with self.assertRaises(render.RenderV2Error):
                render.build_render_plan_v2(
                    self.edl,
                    self.narration,
                    invalid_resources,
                    artifact_root=self.root,
                    output_root=self.root / "missing-resource",
                    ffmpeg=self.root / "ffmpeg.exe",
                    ffprobe=self.root / "ffprobe.exe",
                    ffmpeg_lock=self.lock_path,
                    verify_tools=False,
                )
            run.assert_not_called()

        draft = copy.deepcopy(self.edl)
        draft["authoring"]["status"] = "draft_unverified"
        with self.assertRaisesRegex(render.RenderV2Error, "production_verified"):
            render.validate_production_edl_v2(draft)
        changed = copy.deepcopy(self.narration)
        changed["cues"][0]["audio"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(render.RenderV2Error, "SHA-256 changed"):
            render.build_render_plan_v2(
                self.edl,
                changed,
                self.resources,
                artifact_root=self.root,
                output_root=self.root / "changed-audio",
                ffmpeg=self.root / "ffmpeg.exe",
                ffprobe=self.root / "ffprobe.exe",
                ffmpeg_lock=self.lock_path,
                verify_tools=False,
            )

    def test_pre_rendered_xar_cards_and_safe_runtime_copy_are_consumed_directly(self) -> None:
        # A valid IHDR is sufficient for the renderer's dependency-free PNG
        # geometry check; xAR's producer owns full PNG decoding/inspection.
        png = (
            b"\x89PNG\r\n\x1a\n"
            + struct.pack(">I", 13)
            + b"IHDR"
            + struct.pack(">II", 1920, 1080)
            + bytes((8, 6, 0, 0, 0))
            + b"\x00\x00\x00\x00"
        )
        card_path = self.root / "title-cards/end.png"
        card_path.parent.mkdir(parents=True, exist_ok=True)
        card_path.write_bytes(png)
        asset_manifest = {
            "schema": "vivhite-promo-title-card-assets-v2",
            "status": "rendered_pending_editorial_review",
            "renderer": {
                "public_api": "xar_promo.visuals.render_title_card",
                "xar_version": "0.2.1",
                "pillow_version": "12.3.0",
                "canvas": {"width": 1920, "height": 1080, "fps": 60},
            },
            "title_cards": [
                {
                    "subshot_id": "sub-3",
                    "chinese_title": "白绮",
                    "english_subtitle": "VIVHITE",
                    "duration_seconds": 5,
                    "artifact": _binding("title-cards/end.png", png),
                    "inspection": {"width": 1920, "height": 1080, "mode": "RGBA"},
                }
            ],
        }
        manifest_path = self.root / "title-cards/manifest.json"
        manifest_path.write_text(json.dumps(asset_manifest), encoding="utf-8")
        narration = copy.deepcopy(self.narration)
        narration["cues"][0].update(
            {
                "narration_zh": "让当前状态替她完成自我介绍。",
                "subtitle_zh": "生命与金币以当前 HUD 为准",
                "subtitle_en": "Use the current HUD values",
                "runtime_binding": {
                    "status": "pending",
                    "must_not_bake_into_tts_or_subtitle": True,
                    "deferred_fields": ["initial_hp", "initial_gold"],
                },
            }
        )
        plan = render.build_render_plan_v2(
            self.edl,
            narration,
            manifest_path,
            artifact_root=self.root,
            output_root=self.root / "pre-rendered",
            ffmpeg=self.root / "ffmpeg.exe",
            ffprobe=self.root / "ffprobe.exe",
            ffmpeg_lock=self.lock_path,
            verify_tools=False,
        ).to_mapping()
        title = next(item for item in plan["segments"] if item["asset_type"] == "end_card")
        self.assertEqual("pre_rendered_title_card", title["source_kind"])
        self.assertEqual(card_path.as_posix(), title["path"])
        self.assertEqual([], plan["title_card_tasks"])
        self.assertIn("生命与金币以当前 HUD 为准", plan["ass_content"])
        self.assertNotIn("我只是想要成为我自己", plan["ass_content"])

    def test_short_variants_are_independent_edls_from_same_take_batch(self) -> None:
        payload = b"long-take"
        long_binding = _binding("takes/T99.mp4", payload)
        (self.root / "takes/T99.mp4").write_bytes(payload)
        master = copy.deepcopy(self.edl)
        master["edit_id"] = "master-540"
        master["target_duration_seconds"] = 540
        master["segments"] = [
            {
                "segment_id": "master-segment",
                "shot_id": "S01-identity",
                "subshot_id": "master-source",
                "asset_type": "montage",
                "timeline": {"start_seconds": 0, "end_seconds": 540, "duration_seconds": 540},
                "duration_seconds": 540,
                "source": {
                    "kind": "video_take",
                    "take_id": "T99",
                    **long_binding,
                    "in_seconds": 0,
                    "out_seconds": 540,
                    "verification": "production_verified",
                    "probe": _probe(540),
                },
                "cue_id": "C000",
            }
        ]
        master["cues"] = []
        for variant_id, duration in render.SHORT_VARIANTS.items():
            recipe = {
                "schema_version": 2,
                "kind": "vivhite_promo_variant_recipe_v2",
                "variant_id": variant_id,
                "target_duration_seconds": duration,
                "source": "same_v2_take_batch",
                "from_signed_master": False,
                "clips": [
                    {
                        "clip_id": "direct-take-window",
                        "source_subshot_id": "master-source",
                        "in_offset_seconds": 10,
                        "duration_seconds": duration,
                    }
                ],
                "cue_ids": [],
            }
            result = render.build_variant_edl_v2(master, recipe)
            self.assertEqual(duration, result["target_duration_seconds"])
            self.assertEqual("run-test-v2", result["take_batch_id"])
            self.assertFalse(result["from_signed_master"])
            self.assertEqual("takes/T99.mp4", result["segments"][0]["source"]["path"])
            self.assertEqual(10, result["segments"][0]["source"]["in_seconds"])

    def test_checked_in_variant_recipes_build_against_director_subshots(self) -> None:
        board = json.loads(
            (PROMO_ROOT / "v2" / "storyboard.json").read_text(encoding="utf-8")
        )
        segments = []
        cues = []
        index = 0
        for shot in board["shots"]:
            for subshot in shot["subshots"]:
                index += 1
                duration = float(subshot["timeline"]["duration_seconds"])
                if subshot["asset_type"] in render.CAPTURE_TYPES:
                    source = {
                        "kind": "video_take",
                        "take_id": subshot["take"]["take_id"],
                        "path": f"takes/{subshot['subshot_id']}.mp4",
                        "bytes": index,
                        "sha256": f"{index:064X}",
                        "in_seconds": 0,
                        "out_seconds": duration,
                        "verification": "production_verified",
                        "probe": _probe(duration),
                    }
                else:
                    source = {
                        "kind": "generated_title_card",
                        "generator": "xar.TitleCardSpec",
                        "spec": copy.deepcopy(subshot["title_card"]),
                    }
                segment_id = f"seg-{index:03d}"
                segment = {
                    "segment_id": segment_id,
                    "shot_id": shot["shot_id"],
                    "subshot_id": subshot["subshot_id"],
                    "asset_type": subshot["asset_type"],
                    "timeline": copy.deepcopy(subshot["timeline"]),
                    "duration_seconds": duration,
                    "source": source,
                    "cue_id": subshot["cue"]["cue_id"],
                }
                if "visual_requirements" in subshot:
                    segment["visual_requirements"] = copy.deepcopy(
                        subshot["visual_requirements"]
                    )
                segments.append(segment)
                cue = copy.deepcopy(subshot["cue"])
                cue["segment_id"] = segment_id
                cue["timeline_start_seconds"] = float(
                    subshot["timeline"]["start_seconds"]
                )
                if "template_fields" in cue:
                    cue["template_values"] = {
                        field: f"observed-{field}" for field in cue["template_fields"]
                    }
                cues.append(cue)
        master = {
            "schema_version": 2,
            "kind": "vivhite_promo_multi_take_edl_v2",
            "edit_id": "master-540",
            "source_strategy": "independent_take_manifest",
            "take_batch_id": "checked-in-recipe-test",
            "from_signed_master": False,
            "target_duration_seconds": 540,
            "canvas": {"width": 1920, "height": 1080, "fps": 60},
            "audio": {
                "bgm": False,
                "narration_voice": "zh-CN-XiaoxiaoNeural",
                "sample_rate_hz": 48000,
                "channels": 2,
            },
            "segments": segments,
            "cues": cues,
            "authoring": _authoring(),
        }
        for variant_id, expected in render.SHORT_VARIANTS.items():
            recipe_path = PROMO_ROOT / "v2" / "edl" / f"{variant_id}.recipe.json"
            result = render.build_variant_edl_v2(master, recipe_path)
            self.assertEqual(expected, result["target_duration_seconds"])
            self.assertFalse(result["from_signed_master"])
            self.assertTrue(result["authoring"]["same_take_batch_as_master"])
            self.assertTrue(
                all(
                    segment["source"]["kind"]
                    in {"video_take", "generated_title_card"}
                    for segment in result["segments"]
                )
            )

    def test_executor_starts_one_xar_command_with_locked_output_abi(self) -> None:
        plan = self.plan(suffix="execute")
        calls: list[object] = []

        class FakeSpec:
            @classmethod
            def create(cls, argv, **kwargs):
                return {"argv": tuple(argv), **kwargs}

        def fake_run(spec, *, audit_directory):
            calls.append((spec, audit_directory))
            plan.partial_path.write_bytes(b"real-render-placeholder-from-mocked-ffmpeg")

        probe = {
            "result": {
                "format": {"duration": "15.000000"},
                "streams": [
                    {
                        "codec_type": "video",
                        "codec_name": "h264",
                        "width": 1920,
                        "height": 1080,
                        "pix_fmt": "yuv420p",
                        "r_frame_rate": "60/1",
                        "avg_frame_rate": "60/1",
                        "nb_frames": "900",
                    },
                    {
                        "codec_type": "audio",
                        "codec_name": "aac",
                        "sample_rate": "48000",
                        "channels": 2,
                        "channel_layout": "stereo",
                    },
                ],
            }
        }
        with (
            mock.patch.object(
                render,
                "_load_xar_runtime",
                return_value=(FakeSpec, fake_run, object(), self.root),
            ),
            mock.patch.object(render, "_materialize_title_cards", return_value=[]),
            mock.patch.object(render, "_probe_json", return_value=probe),
        ):
            receipt = render.execute_render_plan_v2(plan)
        self.assertEqual(1, len(calls))
        self.assertEqual("technically_verified", receipt["status"])
        argv = plan.argv
        self.assertIn("libx264", argv)
        self.assertIn("yuv420p", argv)
        self.assertIn("aac", argv)
        self.assertIn("48000", argv)
        self.assertIn("2", argv)


if __name__ == "__main__":
    unittest.main()
