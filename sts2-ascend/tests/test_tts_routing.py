from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
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
    def setUp(self) -> None:
        # Routing tests must not append mock events to the live narrator log.
        log_patch = mock.patch.object(edge_speaker, "log")
        log_patch.start()
        self.addCleanup(log_patch.stop)

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

    def test_idle_edge_player_never_ages_or_skips_a_future_sequence(self) -> None:
        clock = mock.Mock(side_effect=AssertionError(
            "idle playback must not start a synthesis deadline"))
        playback = edge_speaker._PlaybackBuffer(
            max_queue=4, result_timeout=0.0, wait_poll=0.0, clock=clock)
        stop_checks = 0

        def stop_after_idle_checks() -> bool:
            nonlocal stop_checks
            stop_checks += 1
            return stop_checks > 4

        self.assertIsNone(playback.wait_next(
            stop=stop_after_idle_checks, drained=lambda: False))
        self.assertEqual(playback.counters, {"put": 0, "played": 0})
        self.assertEqual(playback.done, {})
        clock.assert_not_called()

        # The first real sentence after any idle duration must still own seq 0.
        self.assertEqual(playback.enqueue("未来真正到达的第一句"), 0)
        self.assertEqual(playback.pending_texts, {0: "未来真正到达的第一句"})

    def test_ended_and_fully_played_edge_queue_exits_immediately(self) -> None:
        clock = mock.Mock(side_effect=AssertionError(
            "a drained ended queue must not start a deadline"))
        playback = edge_speaker._PlaybackBuffer(
            max_queue=4, result_timeout=90.0, wait_poll=0.0, clock=clock)
        engine = mock.Mock()

        edge_speaker._player_loop(
            playback, engine, is_ended=lambda: True, stop=lambda: False)

        self.assertTrue(playback.is_drained())
        self.assertEqual(playback.counters, {"put": 0, "played": 0})
        engine.say_fallback.assert_not_called()
        clock.assert_not_called()

    def test_unpicked_sentence_times_out_to_sapi_and_late_wav_is_discarded(self) -> None:
        ticks = iter((0.0, 1.0))
        playback = edge_speaker._PlaybackBuffer(
            max_queue=4, result_timeout=0.5, wait_poll=0.0,
            clock=lambda: next(ticks))
        text = "已入队但 worker 尚未取走"
        self.assertEqual(playback.enqueue(text), 0)
        engine = mock.Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            late_wav = Path(temp_dir) / "late.wav"
            late_publish_results: list[bool] = []

            def publish_while_falling_back(_text: str) -> None:
                late_wav.write_bytes(b"late synthesis")
                late_publish_results.append(
                    playback.publish_result(0, late_wav, text))

            engine.say_fallback.side_effect = publish_while_falling_back
            edge_speaker._player_loop(
                playback,
                engine,
                is_ended=lambda: False,
                stop=lambda: (
                    playback.counters["played"] >= playback.counters["put"]),
            )

            self.assertEqual(late_publish_results, [False])
            self.assertFalse(late_wav.exists())

        engine.say_fallback.assert_called_once_with(text)
        self.assertEqual(playback.counters, {"put": 1, "played": 1})
        self.assertEqual(playback.done, {})
        self.assertEqual(playback.pending_texts, {})

        # The stale queue entry is harmless when a worker eventually picks it up.
        stale_seq, stale_text = playback.work.get_nowait()
        self.assertEqual((stale_seq, stale_text), (0, text))
        self.assertFalse(playback.should_synthesize(stale_seq, stale_text))

    def test_late_old_instance_cleanup_cannot_delete_new_instances_same_seq_wav(self) -> None:
        ticks = iter((0.0, 1.0))
        old = edge_speaker._PlaybackBuffer(
            max_queue=4, result_timeout=0.5, wait_poll=0.0,
            clock=lambda: next(ticks), instance_nonce="old")
        new = edge_speaker._PlaybackBuffer(
            max_queue=4, instance_nonce="new")
        text = "两个 speaker 都从 seq 0 开始"
        old.enqueue(text)
        new.enqueue(text)

        timed_out = old.wait_next(stop=lambda: False, drained=lambda: False)
        self.assertEqual(timed_out, (0, None, text, True))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_wav = old.wav_path(root, 0)
            new_wav = new.wav_path(root, 0)
            self.assertNotEqual(old_wav, new_wav)
            old_wav.write_bytes(b"old late result")
            new_wav.write_bytes(b"new current result")

            self.assertFalse(old.publish_result(0, old_wav, text))
            self.assertFalse(old_wav.exists())
            self.assertTrue(new_wav.exists())
            self.assertEqual(new_wav.read_bytes(), b"new current result")

            self.assertTrue(new.publish_result(0, new_wav, text))
            self.assertEqual(new.done[0], (new_wav, text))

        self.assertEqual(old.done, {})

    def test_close_removes_an_accepted_but_unplayed_wav(self) -> None:
        playback = edge_speaker._PlaybackBuffer(
            max_queue=4, instance_nonce="accepted-stop")
        text = "已经合成但尚未播放"
        playback.enqueue(text)
        self.assertEqual(playback.work.get_nowait(), (0, text))

        with tempfile.TemporaryDirectory() as temp_dir:
            wav = playback.wav_path(Path(temp_dir), 0)
            wav.write_bytes(b"accepted wav")
            self.assertTrue(playback.publish_result(0, wav, text))
            self.assertEqual(playback.done[0], (wav, text))

            playback.close()

            self.assertFalse(wav.exists())

        self.assertTrue(playback.closed)
        self.assertEqual(playback.done, {})
        self.assertEqual(playback.pending_texts, {})
        self.assertEqual(playback.claimed, set())
        self.assertTrue(playback.work.empty())
        self.assertIsNone(playback.wait_next(
            stop=lambda: False, drained=lambda: False))

    def test_close_rejects_and_cleans_a_late_worker_publish(self) -> None:
        playback = edge_speaker._PlaybackBuffer(
            max_queue=4, instance_nonce="late-after-close")
        text = "关闭后才完成的 worker"
        playback.enqueue(text)
        self.assertEqual(playback.work.get_nowait(), (0, text))
        playback.close()

        with tempfile.TemporaryDirectory() as temp_dir:
            wav = playback.wav_path(Path(temp_dir), 0)
            wav.write_bytes(b"late after close")
            self.assertFalse(playback.publish_result(0, wav, text))
            self.assertFalse(wav.exists())

        self.assertEqual(playback.done, {})
        self.assertFalse(playback.should_synthesize(0, text))

    def test_shutdown_join_lets_claimed_player_finally_remove_current_wav(self) -> None:
        playback = edge_speaker._PlaybackBuffer(
            max_queue=4, instance_nonce="claimed-stop")
        text = "close 时正在播放"
        playback.enqueue(text)
        self.assertEqual(playback.work.get_nowait(), (0, text))
        playing = threading.Event()
        finish_playback = threading.Event()

        with tempfile.TemporaryDirectory() as temp_dir:
            wav = playback.wav_path(Path(temp_dir), 0)
            wav.write_bytes(b"claimed current wav")
            self.assertTrue(playback.publish_result(0, wav, text))

            def blocked_play(_wav: Path) -> None:
                playing.set()
                self.assertTrue(finish_playback.wait(2.0))

            with mock.patch.object(
                    edge_speaker, "_play_wav_with_gain", side_effect=blocked_play):
                player = threading.Thread(
                    target=edge_speaker._player_loop,
                    args=(playback, mock.Mock()),
                    kwargs={
                        "is_ended": lambda: False,
                        "stop": lambda: playback.closed,
                    },
                    daemon=False,
                )
                player.start()
                self.assertTrue(playing.wait(1.0))
                closer = threading.Thread(
                    target=edge_speaker._close_playback_before_unlock,
                    args=(playback, player),
                    kwargs={"join_timeout": 1.0},
                )
                closer.start()
                try:
                    self.assertTrue(wav.exists())
                    finish_playback.set()
                    closer.join(2.0)
                    player.join(2.0)
                finally:
                    finish_playback.set()
                    closer.join(2.0)
                    player.join(2.0)

            self.assertFalse(closer.is_alive())
            self.assertFalse(player.is_alive())
            self.assertFalse(wav.exists())

        self.assertTrue(playback.closed)
        self.assertEqual(playback.done, {})

    def test_shutdown_worker_join_is_bounded_and_late_files_are_cleaned(self) -> None:
        playback = edge_speaker._PlaybackBuffer(
            max_queue=4, instance_nonce="blocking-worker-stop")
        text = "stop during edge synthesis"
        playback.enqueue(text)
        seq, queued_text = playback.work.get_nowait()
        synthesis_blocked = threading.Event()
        release_synthesis = threading.Event()

        with tempfile.TemporaryDirectory() as temp_dir:
            wav = playback.wav_path(Path(temp_dir), seq)
            mp3 = wav.with_suffix(".mp3")
            engine = edge_speaker.EdgeEngine.__new__(edge_speaker.EdgeEngine)
            engine._ffmpeg = "fake-ffmpeg"

            def fake_run(command, **_kwargs):
                if "edge_tts" in command:
                    mp3.write_bytes(b"m" * 1200)
                    return mock.Mock(returncode=0, stderr=b"")
                wav.write_bytes(b"blocking wav")
                synthesis_blocked.set()
                self.assertTrue(release_synthesis.wait(2.0))
                return mock.Mock(returncode=0, stderr=b"")

            def synth_once() -> None:
                ok = engine.synth_to_wav(queued_text, wav)
                playback.publish_result(
                    seq, wav if ok else None, queued_text)

            worker = threading.Thread(target=synth_once, daemon=False)
            workers = [worker]
            with (mock.patch.object(
                    edge_speaker.subprocess, "run", side_effect=fake_run),
                  mock.patch.object(edge_speaker, "log"),
                  mock.patch.object(
                      edge_speaker, "_active_worker_threads", workers)):
                worker.start()
                try:
                    self.assertTrue(synthesis_blocked.wait(1.0))
                    started = time.monotonic()
                    edge_speaker._close_playback_before_unlock(
                        playback,
                        threading.Thread(),
                        workers,
                        join_timeout=0.0,
                        worker_join_timeout=0.02,
                    )
                    self.assertLess(time.monotonic() - started, 0.5)
                    self.assertTrue(worker.is_alive())
                    self.assertEqual(
                        edge_speaker._active_worker_threads, [worker])
                    self.assertTrue(mp3.exists())
                    self.assertTrue(wav.exists())
                finally:
                    release_synthesis.set()
                    worker.join(2.0)

                self.assertFalse(worker.is_alive())
                self.assertFalse(mp3.exists())
                self.assertFalse(wav.exists())

        self.assertTrue(playback.closed)
        self.assertEqual(playback.done, {})

    def test_edge_synthesis_always_removes_mp3_staging_file(self) -> None:
        for outcome in ("success", "failure", "exception"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp_dir:
                wav = Path(temp_dir) / "sentence.wav"
                mp3 = wav.with_suffix(".mp3")
                engine = edge_speaker.EdgeEngine.__new__(edge_speaker.EdgeEngine)
                engine._ffmpeg = "fake-ffmpeg"

                def fake_run(command, **_kwargs):
                    if "edge_tts" in command:
                        mp3.write_bytes(b"m" * 1200)
                        if outcome == "exception":
                            raise RuntimeError("offline synthesis exception")
                        return mock.Mock(
                            returncode=0 if outcome == "success" else 7,
                            stderr=b"offline failure",
                        )
                    wav.write_bytes(b"offline wav")
                    return mock.Mock(returncode=0, stderr=b"")

                with (mock.patch.object(
                        edge_speaker.subprocess, "run", side_effect=fake_run),
                      mock.patch.object(edge_speaker, "log")):
                    result = engine.synth_to_wav("离线测试", wav)

                self.assertEqual(result, outcome == "success")
                self.assertFalse(mp3.exists())

    def test_full_edge_queue_still_drops_the_oldest_half_without_waiting(self) -> None:
        clock = mock.Mock(side_effect=AssertionError(
            "drop markers must be immediately ready, not timed out"))
        playback = edge_speaker._PlaybackBuffer(
            max_queue=4, result_timeout=90.0, wait_poll=0.0, clock=clock)
        for index in range(5):
            self.assertEqual(playback.enqueue(f"sentence-{index}"), index)

        with playback.work.mutex:
            queued = list(playback.work.queue)
        self.assertEqual([seq for seq, _ in queued], [2, 3, 4])
        self.assertEqual(set(playback.done), {0, 1})
        self.assertEqual(set(playback.pending_texts), {2, 3, 4})

        for expected in (0, 1):
            item = playback.wait_next(stop=lambda: False, drained=lambda: False)
            self.assertEqual(item, (expected, None, None, False))
            playback.mark_played(expected)

        self.assertEqual(playback.counters, {"put": 5, "played": 2})
        self.assertEqual(playback.done, {})
        clock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
