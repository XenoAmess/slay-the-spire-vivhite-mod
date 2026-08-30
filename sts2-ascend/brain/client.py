"""STS2-Agent mod HTTP API client (stdlib only).

Wraps the local API exposed by the STS2AIAgent mod (CharTyr/STS2-Agent):
  GET  /health
  GET  /state
  GET  /actions/available
  GET  /data/{collection}
  POST /action
"""
from __future__ import annotations

import json
import http.client
import time
import urllib.error
import urllib.request

from manual_control import ensure_action_allowed


class ApiError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 0, retryable: bool = False):
        super().__init__(f"{code}: {message} (http={status})")
        self.code = code
        self.status = status
        self.retryable = retryable


class ConnectionDown(RuntimeError):
    pass


class Sts2Client:
    def __init__(self, ports=(8080, 8081, 8082, 8083, 8084), read_timeout=10.0, action_timeout=30.0):
        self.ports = list(ports)
        self.read_timeout = read_timeout
        self.action_timeout = action_timeout
        self.base_url: str | None = None

    # ---------- discovery ----------

    def discover(self) -> str | None:
        """Probe known ports, remember the first healthy one."""
        for port in self.ports:
            url = f"http://127.0.0.1:{port}"
            try:
                data = self._raw_request("GET", url + "/health", timeout=3.0)
                # _decode() strips the envelope; /health data carries {"status": "ready", ...}
                if isinstance(data, dict) and data.get("status") == "ready":
                    self.base_url = url
                    return url
            except (ApiError, ConnectionDown):
                continue
        self.base_url = None
        return None

    def wait_until_ready(self, timeout_s: float = 180.0, poll_s: float = 3.0) -> str:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            url = self.discover()
            if url:
                return url
            time.sleep(poll_s)
        raise ConnectionDown(f"STS2-Agent API not reachable on ports {self.ports} within {timeout_s}s")

    # ---------- API ----------

    def health(self) -> dict:
        return self._request("GET", "/health")

    def state(self) -> dict:
        return self._request("GET", "/state")

    def available_actions(self) -> list[dict]:
        return self._request("GET", "/actions/available").get("actions", [])

    def data(self, collection: str):
        return self._request("GET", f"/data/{collection}")

    def act(self, action: str, *, card_index=None, target_index=None, option_index=None, command=None,
            x=None, y=None, tool=None) -> dict:
        # This is the final boundary before any gameplay POST.  Agent also gates
        # its decision loop, but keeping the check here covers every future caller
        # and narrows a hotkey race to an already in-flight request.
        ensure_action_allowed()
        payload = {
            "action": action,
            "card_index": card_index,
            "target_index": target_index,
            "option_index": option_index,
            "command": command,
            "x": x,
            "y": y,
            "tool": tool,
            "client_context": {"source": "sts2-ascend-brain"},
        }
        return self._request("POST", "/action", payload, is_action=True)

    # ---------- internals ----------

    def _request(self, method: str, path: str, payload=None, is_action: bool = False):
        if not self.base_url:
            if not self.discover():
                raise ConnectionDown("API base url unknown and discovery failed")
        url = self.base_url + path
        try:
            return self._raw_request(method, url, payload, timeout=self.action_timeout if is_action else self.read_timeout)
        except ConnectionDown:
            # A POST may have reached the game even when its response was lost.
            # Transparently replaying it after rediscovery can play a second card,
            # toggle a selection back off, or submit an event choice twice.  Probe
            # health so the next GET can recover quickly, but surface the ambiguous
            # action to Agent for state-based reconciliation.
            if is_action:
                self.discover()
                raise
            # Read-only requests are safe to retry once after a port change/restart.
            if self.discover():
                return self._raw_request(method, self.base_url + path, payload,
                                         timeout=self.action_timeout if is_action else self.read_timeout)
            raise

    def _raw_request(self, method: str, url: str, payload=None, timeout=10.0):
        try:
            body = json.dumps(payload).encode("utf-8") if payload is not None else None
        except (TypeError, ValueError) as exc:
            # Serialization happens before urllib can send a byte.  Unlike response
            # decoding failures, this is a definitive local request error and must
            # not enter the unknown-success reconciliation path.
            raise ApiError("invalid_request", f"payload is not JSON serializable: {exc}") from exc
        req = urllib.request.Request(
            url=url, method=method, data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return self._decode(resp.read())
        except urllib.error.HTTPError as exc:
            try:
                raw = exc.read()
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError,
                    http.client.HTTPException) as read_exc:
                # The server may already have executed a POST before the HTTP error
                # body was truncated.  This is an unknown receipt, not a definitive
                # gameplay rejection.
                raise ConnectionDown(
                    f"truncated HTTP error response from {url}: {read_exc}") from read_exc
            try:
                envelope = json.loads(raw.decode("utf-8"))
                if not isinstance(envelope, dict):
                    raise ValueError("HTTP error envelope is not an object")
                err = envelope.get("error")
                if not isinstance(err, dict):
                    raise ValueError("HTTP error envelope has no error object")
                raise ApiError(err.get("code", "unknown"), err.get("message", "request failed"),
                               status=exc.code, retryable=bool(err.get("retryable", False)))
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as decode_exc:
                # A malformed HTTP error body is not a trustworthy rejection.  For
                # POST the game may already have acted; let Agent reconcile it from
                # the next state rather than permanently suppressing the resource.
                raise ConnectionDown(
                    f"invalid/truncated HTTP error body (http={exc.code}): "
                    f"{decode_exc}") from decode_exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError,
                http.client.HTTPException) as exc:
            raise ConnectionDown(f"cannot reach {url}: {exc}")

    @staticmethod
    def _decode(raw: bytes):
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            # For POST this is an unknown-success receipt, not proof of failure.
            # Raising ConnectionDown routes it through Agent's next-state semantic
            # reconciliation; GET remains safe for the client's one read retry.
            raise ConnectionDown(f"invalid/truncated JSON response: {exc}") from exc
        if not isinstance(payload, dict):
            raise ConnectionDown("invalid API response envelope")
        # Never use truthiness here: ``1``, ``"true"`` and a missing key are
        # malformed protocol receipts.  A POST may already have been applied, so
        # treating any of them as a definitive rejection can suppress a real card,
        # reward, or UI action without reconciliation.
        ok = payload.get("ok")
        if type(ok) is not bool:
            raise ConnectionDown("invalid API response envelope: ok must be boolean")
        if not ok:
            err = payload.get("error")
            if not isinstance(err, dict):
                raise ConnectionDown("invalid API error envelope: error must be an object")
            raise ApiError(err.get("code", "unknown"), err.get("message", "request failed"),
                           status=200, retryable=bool(err.get("retryable", False)))
        return payload.get("data")
