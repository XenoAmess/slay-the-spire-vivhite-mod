from __future__ import annotations

import contextlib
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ASCEND_DIR = Path(__file__).resolve().parent.parent
TTS_DIR = ASCEND_DIR / "tts"
sys.path.insert(0, str(TTS_DIR))

import indextts_client as client  # noqa: E402
import indextts_gpu as gpu  # noqa: E402


class _FakeEngine:
    device = "cuda:0"
    gpu_name = "fake-gpu"
    precision = "fp32"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def synthesize(self, text: str, output_path: Path) -> float:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.03)
            output_path.write_bytes(b"fake-wave")
            self.calls.append(text)
        finally:
            with self.lock:
                self.active -= 1
        return 0.03


class _BlockingEngine(_FakeEngine):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def synthesize(self, text: str, output_path: Path) -> float:
        self.calls.append(text)
        self.started.set()
        self.release.wait(2.0)
        output_path.write_bytes(b"fake-wave")
        return 0.03


class SpeechServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _FakeEngine()
        self.played: list[bytes] = []
        self.busy_events: list[str | None] = []
        self.service = gpu.SpeechService(
            self.engine,
            session_id="test-session",
            play=lambda path: self.played.append(path.read_bytes()),
            log=lambda _message: None,
            on_busy=self.busy_events.append,
        )
        self.service.start_http(0)
        self.port = int(self.service.server.server_address[1])

    def tearDown(self) -> None:
        self.service.close()

    def test_client_health_and_speech_use_the_owner(self) -> None:
        with (mock.patch.object(client, "_url", lambda path: f"http://127.0.0.1:{self.port}{path}"),
              mock.patch.dict(os.environ, {"STS2_ASCEND_SESSION_ID": "test-session"})):
            status = client.health()
            self.assertTrue(status["ready"])
            self.assertEqual(status["device"], "cuda:0")
            result = client.speak("白绮测试", source="conclusion", timeout=10)
        self.assertTrue(result["ok"])
        self.assertEqual(self.engine.calls, ["白绮测试"])
        self.assertEqual(self.played, [b"fake-wave"])

    def test_wrong_session_is_rejected(self) -> None:
        with (mock.patch.object(client, "_url", lambda path: f"http://127.0.0.1:{self.port}{path}"),
              mock.patch.dict(os.environ, {"STS2_ASCEND_SESSION_ID": "other-session"})):
            with self.assertRaises(client.IndexTTSServiceError):
                client.speak("不会播放", source="quip", timeout=10)
        self.assertEqual(self.engine.calls, [])

    def test_concurrent_callers_are_serialized(self) -> None:
        errors: list[Exception] = []

        def submit(text: str) -> None:
            try:
                self.service.submit(text, "review", timeout=10)
            except Exception as exc:  # pragma: no cover - assertion reports it
                errors.append(exc)

        threads = [threading.Thread(target=submit, args=(f"line-{index}",)) for index in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(self.engine.max_active, 1)
        self.assertEqual(len(self.engine.calls), 4)

    def test_long_conclusion_is_fed_to_the_engine_in_short_atomic_segments(self) -> None:
        text = (
            "第632局满血硬啃死亡率54%的盛碗虫组合，"
            "七回合内攻防摇摆五次白白多掉血，残血过精英阵亡。"
            "已给战斗引擎上竞速迟滞锁，判了全攻就不再翻来覆去。"
        )
        result = self.service.submit(text, "conclusion", timeout=10)

        self.assertGreater(len(self.engine.calls), 1)
        self.assertTrue(all(1 <= len(chunk) <= gpu.CONCLUSION_MAX_CHARS
                            for chunk in self.engine.calls))
        self.assertEqual("".join(self.engine.calls), text)
        self.assertEqual(len(self.played), len(self.engine.calls))
        self.assertEqual(result["segments"], len(self.engine.calls))
        self.assertEqual(result["segment_lengths"], [len(chunk) for chunk in self.engine.calls])
        self.assertEqual(self.service.completed, 1)
        self.assertEqual(self.busy_events, ["conclusion", None])

    def test_unpunctuated_conclusion_balances_around_ten_without_losing_text(self) -> None:
        text = "一" * 41
        chunks = gpu.split_conclusion_text(text)

        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(1 <= len(chunk) <= gpu.CONCLUSION_TARGET_CHARS
                            for chunk in chunks))
        self.assertEqual(max(len(chunk) for chunk in chunks), 9)

    def test_unpunctuated_tail_between_target_and_limit_is_balanced(self) -> None:
        for length in (11, 19, 20):
            with self.subTest(length=length):
                text = "甲" * length
                chunks = gpu.split_conclusion_text(text)
                self.assertEqual("".join(chunks), text)
                self.assertTrue(all(len(chunk) <= gpu.CONCLUSION_TARGET_CHARS
                                    for chunk in chunks))

    def test_repeated_terminators_and_closing_quotes_stay_with_the_clause(self) -> None:
        text = "甲" * 9 + "？！她说“先拿群攻！”然后稳住。"
        chunks = gpu.split_conclusion_text(text)

        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= gpu.CONCLUSION_MAX_CHARS for chunk in chunks))
        self.assertFalse(any(chunk in "？！。””" for chunk in chunks))
        self.assertFalse(any(chunk.startswith("”") for chunk in chunks))

    def test_tiny_tail_is_merged_without_crossing_the_hard_limit(self) -> None:
        text = "甲" * 9 + "，乙"
        chunks = gpu.split_conclusion_text(text)

        self.assertEqual(chunks, [text])
        self.assertEqual(len(chunks[0]), 11)

    def test_tail_rebalancing_never_moves_punctuation_to_the_next_segment(self) -> None:
        text = "甲" * 16 + "。" + "乙" * 4
        chunks = gpu.split_conclusion_text(text)

        self.assertEqual("".join(chunks), text)
        self.assertTrue(all(len(chunk) <= gpu.CONCLUSION_MAX_CHARS for chunk in chunks))
        self.assertFalse(any(chunk[0] in gpu._CONCLUSION_BREAKS for chunk in chunks))
        self.assertTrue(chunks[0].endswith("。"))

    def test_whitespace_is_normalized_without_losing_spoken_characters(self) -> None:
        text = "  第一段，\n\n  第二段   继续。  "
        chunks = gpu.split_conclusion_text(text)
        expected = "".join(gpu._normalize_speech_text(text).split())

        self.assertEqual("".join("".join(chunks).split()), expected)
        self.assertTrue(all(chunks))
        self.assertTrue(all(len(chunk) <= gpu.CONCLUSION_MAX_CHARS for chunk in chunks))

    def test_blank_conclusion_has_no_segments(self) -> None:
        self.assertEqual(gpu.split_conclusion_text(" \r\n\t "), [])

    def test_natural_clause_may_exceed_target_but_never_hard_limit(self) -> None:
        text = "七回合内攻防摇摆五次白白多掉血，残血过精英阵亡。"
        chunks = gpu.split_conclusion_text(text)

        self.assertEqual(
            chunks,
            ["七回合内攻防摇摆五次白白多掉血，", "残血过精英阵亡。"],
        )
        self.assertTrue(any(len(chunk) > gpu.CONCLUSION_TARGET_CHARS for chunk in chunks))
        self.assertTrue(all(len(chunk) <= gpu.CONCLUSION_MAX_CHARS for chunk in chunks))

    def test_non_conclusion_sources_keep_one_logical_model_call(self) -> None:
        text = "实时复盘正文不会套用最终结论的十字分段规则。" * 2
        self.service.submit(text, "review", timeout=10)
        self.assertEqual(self.engine.calls, [text])

    def test_stopping_during_a_segment_reports_failure_and_skips_the_rest(self) -> None:
        blocking = _BlockingEngine()
        self.service.engine = blocking
        errors: list[Exception] = []

        def submit() -> None:
            try:
                self.service.submit("第一段要播放，第二段不能播放。", "conclusion", timeout=10)
            except Exception as exc:  # pragma: no branch - the error is the assertion
                errors.append(exc)

        thread = threading.Thread(target=submit)
        thread.start()
        self.assertTrue(blocking.started.wait(2.0))
        self.service._stopping.set()
        blocking.release.set()
        thread.join(2.0)

        self.assertEqual(len(errors), 1)
        self.assertIn("服务停止", str(errors[0]))
        self.assertEqual(len(blocking.calls), 1)
        self.assertEqual(self.played, [])


class _FakeCuda:
    def reset_peak_memory_stats(self, _device: str) -> None:
        pass

    def synchronize(self, _device: str) -> None:
        pass

    def max_memory_allocated(self, _device: str) -> int:
        return 0

    def empty_cache(self) -> None:
        pass


class _FakeTorch:
    cuda = _FakeCuda()

    @staticmethod
    def inference_mode():
        return contextlib.nullcontext()


class _RecordingTts:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def infer(self, **kwargs) -> None:
        self.calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"fake-wave")


class EngineGenerationLimitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = gpu.IndexTTSGpuEngine.__new__(gpu.IndexTTSGpuEngine)
        self.engine.torch = _FakeTorch()
        self.engine.tts = _RecordingTts()
        self.engine.device = "cuda:0"
        self.engine.duration_factor = 0.9
        self.engine.num_beams = 1

    def test_short_text_has_bounded_semantic_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "short.wav"
            self.engine.synthesize("十字以内的短句", output)
        self.assertEqual(
            self.engine.tts.calls[-1]["max_mel_tokens"],
            gpu.SHORT_TEXT_MAX_MEL_TOKENS,
        )

    def test_short_text_limit_uses_whitespace_normalized_length(self) -> None:
        text = "短" + " " * 30 + "句"
        self.assertGreater(len(text), gpu.CONCLUSION_MAX_CHARS)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "normalized-short.wav"
            self.engine.synthesize(text, output)
        self.assertEqual(
            self.engine.tts.calls[-1]["max_mel_tokens"],
            gpu.SHORT_TEXT_MAX_MEL_TOKENS,
        )

    def test_long_text_keeps_upstream_generation_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "long.wav"
            self.engine.synthesize("长" * (gpu.CONCLUSION_MAX_CHARS + 1), output)
        self.assertNotIn("max_mel_tokens", self.engine.tts.calls[-1])


if __name__ == "__main__":
    unittest.main()
