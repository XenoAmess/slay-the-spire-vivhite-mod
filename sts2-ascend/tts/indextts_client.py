"""Standard-library client for the single local IndexTTS GPU owner.

The owner lives inside ``quipper.py`` so quips and review narration never load
two copies of the model.  This module intentionally has no torch dependency;
``speaker.py`` runs in the brain's lightweight Python environment.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "brain" / "config.json"
DEFAULT_PORT = 17952


class IndexTTSServiceError(RuntimeError):
    """The local GPU TTS owner rejected or could not complete a request."""


def _settings() -> tuple[int, float]:
    port = DEFAULT_PORT
    timeout = 900.0
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        tts = cfg.get("tts") or {}
        port = int(tts.get("worker_port", port))
        timeout = float(tts.get("request_timeout_sec", timeout))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    if not 1024 <= port <= 65535:
        port = DEFAULT_PORT
    return port, max(10.0, timeout)


def _url(path: str) -> str:
    port, _ = _settings()
    return f"http://127.0.0.1:{port}{path}"


def _decode_response(response) -> dict:
    raw = response.read().decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IndexTTSServiceError(f"IndexTTS 服务返回了无效响应：{raw[:160]}") from exc
    if not isinstance(payload, dict):
        raise IndexTTSServiceError("IndexTTS 服务响应不是 JSON 对象")
    return payload


def health(timeout: float = 1.0) -> dict | None:
    """Return service status, or ``None`` while the owner is unavailable."""
    try:
        with urllib.request.urlopen(_url("/health"), timeout=max(0.1, timeout)) as response:
            return _decode_response(response)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return None


def wait_ready(
    timeout: float,
    *,
    stop_requested: Callable[[], bool] | None = None,
    poll: float = 0.5,
) -> dict | None:
    """Wait for the current session's CUDA owner without starting another model."""
    deadline = time.monotonic() + max(0.0, timeout)
    expected_session = os.environ.get("STS2_ASCEND_SESSION_ID", "legacy")
    while time.monotonic() < deadline:
        if stop_requested is not None and stop_requested():
            return None
        status = health(timeout=min(1.0, max(0.1, deadline - time.monotonic())))
        if (status and status.get("ready") is True
                and str(status.get("session_id", "legacy")) == expected_session):
            return status
        time.sleep(min(poll, max(0.0, deadline - time.monotonic())))
    return None


def speak(
    text: str,
    *,
    source: str,
    timeout: float | None = None,
) -> dict:
    """Synchronously enqueue, synthesize and play one utterance on the GPU owner."""
    text = str(text or "").strip()
    if not text:
        return {"ok": True, "skipped": "empty"}
    _, configured_timeout = _settings()
    request_timeout = configured_timeout if timeout is None else max(10.0, float(timeout))
    payload = json.dumps({
        "session_id": os.environ.get("STS2_ASCEND_SESSION_ID", "legacy"),
        "source": source,
        "text": text,
        "timeout_sec": request_timeout,
    }, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _url("/speak"), data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=request_timeout + 5.0) as response:
            result = _decode_response(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = _decode_response(exc)
            message = str(detail.get("error") or detail)
        except Exception:
            message = str(exc)
        finally:
            exc.close()
        raise IndexTTSServiceError(message) from exc
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise IndexTTSServiceError(f"IndexTTS GPU 服务不可用：{exc}") from exc
    if not result.get("ok"):
        raise IndexTTSServiceError(str(result.get("error") or "IndexTTS 合成失败"))
    return result
