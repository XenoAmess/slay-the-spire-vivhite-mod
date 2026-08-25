from __future__ import annotations

import os
import sys
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


class SpeechServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = _FakeEngine()
        self.played: list[bytes] = []
        self.service = gpu.SpeechService(
            self.engine,
            session_id="test-session",
            play=lambda path: self.played.append(path.read_bytes()),
            log=lambda _message: None,
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
            result = client.speak("白绮测试", source="review", timeout=10)
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


if __name__ == "__main__":
    unittest.main()
