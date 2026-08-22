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
import time
import urllib.error
import urllib.request


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

    def act(self, action: str, *, card_index=None, target_index=None, option_index=None, command=None) -> dict:
        payload = {
            "action": action,
            "card_index": card_index,
            "target_index": target_index,
            "option_index": option_index,
            "command": command,
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
            # maybe port changed / game restarted; rediscover once
            if self.discover():
                return self._raw_request(method, self.base_url + path, payload,
                                         timeout=self.action_timeout if is_action else self.read_timeout)
            raise

    def _raw_request(self, method: str, url: str, payload=None, timeout=10.0):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            url=url, method=method, data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return self._decode(resp.read())
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                err = json.loads(raw.decode("utf-8")).get("error", {})
                raise ApiError(err.get("code", "unknown"), err.get("message", "request failed"),
                               status=exc.code, retryable=bool(err.get("retryable", False)))
            except json.JSONDecodeError:
                raise ApiError("invalid_response", f"non-JSON error body (http={exc.code})", status=exc.code)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise ConnectionDown(f"cannot reach {url}: {exc}")

    @staticmethod
    def _decode(raw: bytes):
        payload = json.loads(raw.decode("utf-8"))
        if not payload.get("ok", False):
            err = payload.get("error", {})
            raise ApiError(err.get("code", "unknown"), err.get("message", "request failed"),
                           status=200, retryable=bool(err.get("retryable", False)))
        return payload.get("data")
