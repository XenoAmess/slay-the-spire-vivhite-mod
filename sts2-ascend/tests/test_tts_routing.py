from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ASCEND_DIR = Path(__file__).resolve().parent.parent
BRAIN_DIR = ASCEND_DIR / "brain"
TTS_DIR = ASCEND_DIR / "tts"
sys.path.insert(0, str(BRAIN_DIR))
sys.path.insert(0, str(TTS_DIR))

import edge_speaker  # noqa: E402
import llm_review  # noqa: E402


class TtsRoutingTests(unittest.TestCase):
    def test_production_config_launches_edge_narrator(self) -> None:
        config = json.loads((BRAIN_DIR / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["llm"]["tts_mode"], "edge")
        self.assertEqual(config["tts"]["clone_engine"], "indextts")
        self.assertEqual(config["tts"]["device"], "cuda:0")

        with (mock.patch.object(llm_review, "_review_stop_requested", return_value=False),
              mock.patch.object(llm_review.shutil, "which", return_value=sys.executable),
              mock.patch.object(llm_review.subprocess, "Popen") as popen):
            llm_review._launch_speaker({"tts_mode": "edge"}, lambda _message: None)

        command = popen.call_args.args[0]
        self.assertEqual(Path(command[-1]).name, "edge_speaker.py")
        self.assertNotIn("indextts", command)

    def test_live_end_carries_only_this_reviews_conclusion(self) -> None:
        modern, review_id, conclusion = edge_speaker._conclusion_from_live_end(
            '[LIVE-END] {"review_id": "r-42", "exit": 0, '
            '"conclusion": "  本场 要 稳住  "}')
        self.assertTrue(modern)
        self.assertEqual(review_id, "r-42")
        self.assertEqual(conclusion, "本场 要 稳住")

        modern, review_id, conclusion = edge_speaker._conclusion_from_live_end(
            '[LIVE-END] {"exit": 1, "conclusion": ""}')
        self.assertTrue(modern)
        self.assertEqual(review_id, "")
        self.assertEqual(conclusion, "")

        self.assertEqual(
            edge_speaker._conclusion_from_live_end('[LIVE-END] {"exit": 0}'),
            (False, "", ""),
        )
        self.assertEqual(
            edge_speaker._review_id_from_live_start(
                '[LIVE-START] {"review_id": "r-43"}'),
            "r-43",
        )

    def test_live_markers_keep_the_same_review_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            stream = Path(temp_dir) / "review_live.stream"
            with mock.patch.object(llm_review, "LIVE_STREAM", stream):
                llm_review._stream_begin({"review_id": "review-7", "run": [7]})
                llm_review._stream_end({
                    "review_id": "review-7",
                    "exit": 0,
                    "conclusion": "这一场稳住了",
                })
            lines = stream.read_text(encoding="utf-8").splitlines()

        self.assertEqual(edge_speaker._review_id_from_live_start(lines[0]), "review-7")
        modern, review_id, conclusion = edge_speaker._conclusion_from_live_end(lines[1])
        self.assertTrue(modern)
        self.assertEqual(review_id, "review-7")
        self.assertEqual(conclusion, "这一场稳住了")

    def test_stale_conclusion_file_is_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "review_conclusion.txt"
            started_at = time.time()
            path.write_text("上一场旧结论", encoding="utf-8")
            os.utime(path, (started_at - 10, started_at - 10))
            self.assertEqual(
                edge_speaker._fresh_conclusion_file(started_at, path), "")

            path.write_text("  本场\n新结论  ", encoding="utf-8")
            os.utime(path, (started_at + 1, started_at + 1))
            self.assertEqual(
                edge_speaker._fresh_conclusion_file(started_at, path), "本场 新结论")

    def test_edge_submits_conclusion_to_existing_index_gpu_owner(self) -> None:
        status = {"device": "cuda:0", "precision": "fp16"}
        with (mock.patch.object(edge_speaker, "stop_requested", return_value=False),
              mock.patch.object(edge_speaker, "wait_index_ready", return_value=status),
              mock.patch.object(
                  edge_speaker, "index_speak",
                  return_value={"ok": True, "synthesis_seconds": 1.25},
              ) as speak):
            self.assertTrue(edge_speaker._speak_conclusion_indextts("白绮结论"))

        speak.assert_called_once_with("白绮结论", source="conclusion")

    def test_missing_index_owner_does_not_fall_back_or_block_edge(self) -> None:
        with (mock.patch.object(edge_speaker, "stop_requested", return_value=False),
              mock.patch.object(edge_speaker, "wait_index_ready", return_value=None),
              mock.patch.object(edge_speaker, "index_speak") as speak):
            self.assertFalse(edge_speaker._speak_conclusion_indextts("不会走 CPU"))
        speak.assert_not_called()


if __name__ == "__main__":
    unittest.main()
