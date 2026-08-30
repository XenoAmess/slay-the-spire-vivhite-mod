"""Non-blocking, session-scoped telemetry publisher for ASCEND-VISION."""
from __future__ import annotations

import copy
import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any

from lifecycle import RUNTIME_DIR, SESSION_ID


SCHEMA = "sts2.ascend-live/v1"
MAX_BYTES = 128 * 1024
MAX_STRING = 1000
TERMINAL_STATUSES = frozenset({"applied", "retrying", "rejected", "failed"})
PROFILE_LABELS = {"IRONCLAD": "Ironclad", "VIVHITE": "Vivhite"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _safe(value: Any, *, depth: int = 0) -> Any:
    if depth >= 7:
        return "…"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and abs(value) != float("inf") else None
    if isinstance(value, str):
        return value.replace("\x00", " ")[:MAX_STRING]
    if isinstance(value, dict):
        result = {}
        for pos, (key, item) in enumerate(value.items()):
            if pos >= 48:
                break
            result[str(key)[:80]] = _safe(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe(item, depth=depth + 1) for item in value[:48]]
    return str(value)[:MAX_STRING]


def _profile_id(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip().upper()
    if "VIVHITE" in text:
        return "VIVHITE"
    if "IRONCLAD" in text:
        return "IRONCLAD"
    return text or None


def _run_view(state: dict, run_number: int = 0) -> dict:
    run = state.get("run") or {}
    combat = state.get("combat") or {}
    player = combat.get("player") or {}
    character_id = run.get("character_id")
    profile_id = _profile_id(character_id)
    return {
        "run_id": state.get("run_id") or run.get("run_id"),
        "run_number": int(run_number or 0),
        "character_id": character_id,
        "profile_id": profile_id,
        "profile_label": PROFILE_LABELS.get(profile_id),
        "ascension": run.get("ascension", 0),
        "floor": run.get("floor", 0),
        "turn": state.get("turn", 0),
        "hp": run.get("current_hp", player.get("current_hp")),
        "max_hp": run.get("max_hp", player.get("max_hp")),
        "gold": run.get("gold", 0),
        "screen": state.get("screen", "UNKNOWN"),
    }


class LiveDashboardPublisher:
    """Serialize dashboard events off the decision thread.

    The producer only extracts a tiny state view and performs ``put_nowait``.
    When saturated, the oldest visual update is discarded in favour of the latest;
    gameplay and persistence are never blocked by the overlay.
    """

    def __init__(self, runtime_dir: Path | None = None, session_id: str | None = None,
                 *, queue_size: int = 16, autostart: bool = True):
        self.runtime_dir = Path(runtime_dir) if runtime_dir is not None else RUNTIME_DIR
        self.session_id = str(session_id or SESSION_ID or "legacy")
        self.path = self.runtime_dir / f"live_dashboard.{self.session_id}.json"
        self._queue: queue.Queue = queue.Queue(maxsize=max(2, int(queue_size)))
        self._closed = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_state: dict = {}
        self._last_wait_fingerprint = ""
        self._current_decision_id = ""
        self._decision_counter = 0
        if autostart:
            self.start()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._closed.clear()
        self._thread = threading.Thread(target=self._worker,
                                        name="ascend-live-dashboard", daemon=True)
        self._thread.start()

    def _offer(self, event: dict) -> None:
        if self._closed.is_set():
            return
        try:
            self._queue.put_nowait(event)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(event)
        except queue.Full:
            pass

    @staticmethod
    def _fingerprint(run: dict, decision) -> str:
        material = {
            "screen": run.get("screen"), "run_id": run.get("run_id"),
            "profile_id": run.get("profile_id"),
            "floor": run.get("floor"), "turn": run.get("turn"),
            "action": getattr(decision, "action", None),
            "params": getattr(decision, "params", {}) or {},
            "reason": getattr(decision, "reason", "") or "",
        }
        return json.dumps(material, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), default=str)

    def observe(self, state: dict, *, run_number: int = 0,
                connection: str = "connected", message: str = "") -> None:
        self._offer({"kind": "observe", "run": _run_view(state, run_number),
                     "connection": {"status": connection, "message": str(message)[:240],
                                    "at": _now()}, "at": _now()})

    def connection(self, status: str, message: str = "") -> None:
        self._offer({"kind": "connection",
                     "connection": {"status": str(status),
                                    "message": str(message)[:240], "at": _now()},
                     "at": _now()})

    def propose(self, state: dict, decision, *, run_number: int = 0,
                watchdog: bool = False) -> str:
        run = _run_view(state, run_number)
        waiting = not bool(getattr(decision, "action", None))
        fingerprint = self._fingerprint(run, decision)
        repeated = waiting and fingerprint == self._last_wait_fingerprint
        if not repeated:
            self._decision_counter += 1
            self._current_decision_id = f"{self.session_id}-{self._decision_counter}"
        self._last_wait_fingerprint = fingerprint if waiting else ""
        trace = copy.deepcopy(getattr(decision, "trace", {}) or {})
        selected = trace.get("selected") if isinstance(trace, dict) else None
        event = {
            "kind": "decision", "run": run,
            "decision_id": self._current_decision_id,
            "status": "waiting" if waiting else "proposed",
            "repeat": repeated,
            "trace": trace,
            "action": getattr(decision, "action", None),
            "label": (selected or {}).get("label") if isinstance(selected, dict)
                     else getattr(decision, "action", None),
            "reason": getattr(decision, "reason", "") or "",
            "watchdog": bool(watchdog), "at": _now(),
        }
        self._offer(event)
        return self._current_decision_id

    def outcome(self, status: str, message: str = "", *,
                decision_id: str | None = None) -> None:
        self._offer({"kind": "outcome", "decision_id": decision_id or self._current_decision_id,
                     "status": str(status), "message": str(message)[:500], "at": _now()})

    def close(self, timeout: float = 1.0) -> None:
        if self._closed.is_set():
            return
        self._offer({"kind": "close"})
        thread = self._thread
        if thread is not None:
            thread.join(max(0.0, timeout))
        self._closed.set()

    def _base_snapshot(self) -> dict:
        return {
            "schema": SCHEMA,
            "session_id": self.session_id,
            "seq": 0,
            "revision": 1,
            "heartbeat": _now(),
            "connection": {"status": "starting", "message": "", "at": _now()},
            "run": {}, "decision": {}, "history": [],
        }

    def _apply(self, snapshot: dict, event: dict) -> None:
        kind = event.get("kind")
        if kind == "observe":
            snapshot["run"] = event.get("run") or snapshot.get("run") or {}
            snapshot["connection"] = event.get("connection") or snapshot["connection"]
        elif kind == "connection":
            snapshot["connection"] = event.get("connection") or snapshot["connection"]
        elif kind == "decision":
            snapshot["run"] = event.get("run") or snapshot.get("run") or {}
            trace = event.get("trace") if isinstance(event.get("trace"), dict) else {}
            old = snapshot.get("decision") or {}
            repeats = int(old.get("repeat_count", 0)) + 1 if event.get("repeat") else 1
            snapshot["decision"] = {
                "decision_id": event.get("decision_id"),
                "status": event.get("status"),
                "repeat_count": repeats,
                "observation": trace.get("observation", {}),
                "gates": list(trace.get("gates") or [])[:32],
                "candidates": list(trace.get("candidates") or [])[:8],
                "selected": trace.get("selected") or {
                    "action": event.get("action"), "label": event.get("label"),
                    "params": {}, "reason": event.get("reason")},
                "explanation": trace.get("explanation") or [event.get("reason") or ""],
                "outcome": {"status": event.get("status"),
                            "message": "看门狗介入" if event.get("watchdog") else "",
                            "at": event.get("at")},
            }
        elif kind == "outcome":
            decision = snapshot.get("decision") or {}
            if event.get("decision_id") and event.get("decision_id") != decision.get("decision_id"):
                return
            decision["status"] = event.get("status")
            decision["outcome"] = {"status": event.get("status"),
                                   "message": event.get("message") or "",
                                   "at": event.get("at")}
            if event.get("status") in TERMINAL_STATUSES:
                selected = decision.get("selected") or {}
                entry = {
                    "decision_id": decision.get("decision_id"),
                    "status": event.get("status"),
                    "action": selected.get("action"),
                    "label": selected.get("label"),
                    "reason": selected.get("reason", ""),
                    "at": event.get("at"),
                }
                history = [row for row in (snapshot.get("history") or [])
                           if row.get("decision_id") != entry["decision_id"]]
                snapshot["history"] = (history + [entry])[-3:]
        snapshot["heartbeat"] = event.get("at") or _now()
        snapshot["seq"] = int(snapshot.get("seq", 0)) + 1

    def _encode(self, snapshot: dict) -> bytes:
        safe = _safe(snapshot)
        raw = json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) <= MAX_BYTES:
            return raw
        decision = safe.get("decision") or {}
        decision["candidates"] = list(decision.get("candidates") or [])[:3]
        decision["gates"] = list(decision.get("gates") or [])[:8]
        decision["explanation"] = list(decision.get("explanation") or [])[:1]
        safe["history"] = list(safe.get("history") or [])[-1:]
        raw = json.dumps(safe, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(raw) <= MAX_BYTES:
            return raw
        # A future custom trace may still be pathological after pruning.  Emit a
        # small valid snapshot rather than byte-slicing JSON into an unreadable file.
        compact = {
            "schema": safe.get("schema", SCHEMA),
            "session_id": safe.get("session_id"),
            "seq": safe.get("seq", 0),
            "revision": safe.get("revision", 1),
            "heartbeat": safe.get("heartbeat"),
            "connection": safe.get("connection", {}),
            "run": safe.get("run", {}),
            "decision": {
                "decision_id": decision.get("decision_id"),
                "status": decision.get("status"),
                "repeat_count": decision.get("repeat_count", 1),
                "selected": decision.get("selected", {}),
                "outcome": decision.get("outcome", {}),
                "observation": {"title": "遥测过大，已安全压缩"},
                "gates": [], "candidates": [], "explanation": [],
            },
            "history": [],
        }
        return json.dumps(compact, ensure_ascii=False,
                          separators=(",", ":")).encode("utf-8")

    def _write(self, snapshot: dict) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        raw = self._encode(snapshot)
        temp = self.runtime_dir / f"{self.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        try:
            temp.write_bytes(raw)
            temp.replace(self.path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def _worker(self) -> None:
        snapshot = self._base_snapshot()
        while True:
            try:
                event = self._queue.get(timeout=1.0)
            except queue.Empty:
                # Heartbeat while connected, even when the game produces no state.
                snapshot["heartbeat"] = _now()
                snapshot["seq"] = int(snapshot.get("seq", 0)) + 1
                try:
                    self._write(snapshot)
                except OSError:
                    pass
                continue
            if event.get("kind") == "close":
                try:
                    self._write(snapshot)
                except OSError:
                    pass
                self._closed.set()
                return
            self._apply(snapshot, event)
            # Coalesce bursts so one action lifecycle causes at most one disk write.
            while True:
                try:
                    extra = self._queue.get_nowait()
                except queue.Empty:
                    break
                if extra.get("kind") == "close":
                    self._closed.set()
                    break
                self._apply(snapshot, extra)
            try:
                self._write(snapshot)
            except OSError:
                pass
            if self._closed.is_set():
                return
