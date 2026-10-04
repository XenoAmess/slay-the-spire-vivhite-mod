"""Repair one evidenced OpenCode session's empty retry steps without model calls.

Export/serve and the local part API are the only OpenCode operations used. The
original export is retained before any deletion, and every surviving part is
verified afterward. This is an explicit compatibility tool, not a review gate.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


SOURCE_URLS = [
    "https://raw.githubusercontent.com/anomalyco/opencode/v1.18.21/packages/opencode/src/session/processor.ts",
    "https://raw.githubusercontent.com/anomalyco/opencode/v1.18.21/packages/opencode/src/session/message-v2.ts",
    "https://raw.githubusercontent.com/anomalyco/opencode/v1.18.21/packages/opencode/src/server/routes/instance/httpapi/groups/session.ts",
    "https://raw.githubusercontent.com/vercel/ai/ai@6.0.168/packages/ai/src/ui/convert-to-model-messages.ts",
]


def _empty_assistant_error(error: object) -> bool:
    if not isinstance(error, dict):
        return False
    data = error.get("data") or error
    if not isinstance(data, dict) or data.get("statusCode") != 400:
        return False
    message = str(data.get("message") or "").lower()
    return all(token in message for token in ("position", "assistant", "empty"))


def select_empty_retry_parts(messages: list[dict]) -> list[dict]:
    """Select only an empty prefix step followed by a completed useful step."""
    selected = []
    for row in messages:
        info = row.get("info") or {}
        if info.get("role") != "assistant" or info.get("error"):
            continue
        parts = row.get("parts") or []
        starts = [i for i, part in enumerate(parts) if part.get("type") == "step-start"]
        if len(starts) < 2:
            continue
        block = parts[starts[0]:starts[1]]
        if (len(block) != 2 or block[1].get("type") != "reasoning"
                or block[1].get("text") != ""):
            continue
        tail = parts[starts[1]:]
        completed = any(part.get("type") == "step-finish" for part in tail)
        useful = any(
            (part.get("type") == "text" and bool(part.get("text")))
            or (part.get("type") == "tool"
                and (part.get("state") or {}).get("status") == "completed")
            for part in tail)
        if not completed or not useful:
            continue
        ids = [part.get("id") for part in block]
        if not info.get("id") or not all(isinstance(value, str) and value for value in ids):
            continue
        selected.append({"message_id": info["id"], "part_ids": ids})
    return selected


def shape(messages: list[dict]) -> list[dict]:
    return [{"message_id": row["info"]["id"], "parts": [
        {"part_id": part.get("id"), "type": part.get("type"),
         "text_length": len(part.get("text") or "")
         if part.get("type") in {"text", "reasoning"} else None}
        for part in row.get("parts") or []]} for row in messages]


def verify_only_selected_removed(before: list[dict], after: list[dict], selected: list[dict]) -> None:
    removed = {(row["message_id"], part_id) for row in selected for part_id in row["part_ids"]}
    def by_id(rows, omit):
        result = {}
        for row in rows:
            message_id = row["info"]["id"]
            parts = {part["id"]: part for part in row.get("parts") or []}
            if message_id in result or len(parts) != len(row.get("parts") or []):
                raise RuntimeError("Session contains duplicate message or part IDs")
            result[message_id] = {"info": row["info"], "parts": {
                key: part for key, part in parts.items() if (message_id, key) not in omit}}
        return result
    expected = by_id(before, removed)
    actual = by_id(after, set())
    if expected != actual:
        raise RuntimeError("Session verification failed: an unselected part or message changed")


def verify_selected_identity(export_rows: list[dict], api_rows: list[dict], selected: list[dict]) -> None:
    """Check deletion targets across transports without equating tool serialization."""
    def targets(rows):
        messages = {row["info"]["id"]: row for row in rows}
        result = {}
        for selection in selected:
            message_id = selection["message_id"]
            row = messages[message_id]
            parts = {part["id"]: part for part in row.get("parts") or []}
            for part_id in selection["part_ids"]:
                part = parts[part_id]
                result[message_id, part_id] = (row["info"]["role"], part.get("type"),
                                               part.get("text") if part.get("type") == "reasoning" else None)
        return result
    if targets(export_rows) != targets(api_rows):
        raise RuntimeError("REST deletion targets differ from the evidenced export")


def _write_new(path: Path, raw: bytes) -> None:
    if path.exists():
        raise FileExistsError("Evidence already exists; use a new output directory")
    temporary = path.with_name(path.name + ".append-" + uuid.uuid4().hex)
    with temporary.open("xb") as handle:
        handle.write(raw)
    temporary.rename(path)


def _json_new(path: Path, value: object) -> None:
    _write_new(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _export(binary: str, session: str, workdir: Path, output: Path, name: str) -> dict:
    with (output / f"{name}.stderr.log").open("xb") as errors:
        result = subprocess.run([binary, "export", session, "--pure"], cwd=workdir,
                                stdout=subprocess.PIPE, stderr=errors, timeout=45,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    _write_new(output / f"{name}.export.json", result.stdout)
    if result.returncode:
        raise RuntimeError(f"OpenCode export failed with exit code {result.returncode}")
    exported = json.loads(result.stdout.decode("utf-8-sig"))
    if (exported.get("info") or {}).get("id") != session:
        raise RuntimeError("OpenCode exported a different session")
    _json_new(output / f"{name}.shape.json", shape(exported.get("messages") or []))
    return exported


def _creation_identity(process: subprocess.Popen) -> dict:
    identity = {"pid": process.pid, "created_at_unix": time.time()}
    if os.name == "nt":
        created, ended, kernel, user = (wintypes.FILETIME() for _ in range(4))
        get_times = ctypes.windll.kernel32.GetProcessTimes
        get_times.argtypes = [wintypes.HANDLE, *(ctypes.POINTER(wintypes.FILETIME) for _ in range(4))]
        get_times.restype = wintypes.BOOL
        if not get_times(int(process._handle), ctypes.byref(created), ctypes.byref(ended),
                         ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError()
        identity["creation_filetime"] = (created.dwHighDateTime << 32) | created.dwLowDateTime
    return identity


def repair(*, binary: str, session: str, workdir: Path, evidence: Path,
           output: Path, apply: bool) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    result = {"session_id": session, "applied": False, "selected": [], "status": "started"}
    process = None
    server_log = None
    try:
        result["phase"] = "export_before"
        before = _export(binary, session, workdir, output, "before")
        rows = before.get("messages") or []
        if not any(_empty_assistant_error((row.get("info") or {}).get("error")) for row in rows):
            raise RuntimeError("Export has no evidenced HTTP 400 empty-assistant error")
        event_rows = []
        for line in evidence.read_text(encoding="utf-8-sig", errors="replace").splitlines():
            try:
                event_rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        if not any(isinstance(row, dict) and row.get("type") == "error"
                   and _empty_assistant_error(row.get("error")) for row in event_rows):
            raise RuntimeError("Provider events have no evidenced HTTP 400 empty-assistant error")
        selected = select_empty_retry_parts(rows)
        result["selected"] = selected
        result["evidence_events_sha256"] = hashlib.sha256(evidence.read_bytes()).hexdigest()
        _json_new(output / "selection.json", selected)
        _write_new(output / "official_source_urls.txt", ("\n".join(SOURCE_URLS) + "\n").encode())
        if not selected:
            result["status"] = "no_matching_empty_retry_block"
            return result
        if not apply:
            result["status"] = "preview"
            return result
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        command = [binary, "serve", "--hostname", "127.0.0.1", "--port", str(port), "--pure"]
        server_log = (output / "serve.log").open("xb")
        process = subprocess.Popen(command, cwd=workdir, stdin=subprocess.DEVNULL,
                                   stdout=server_log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        _json_new(output / "serve_identity.json", {
            **_creation_identity(process), "command": command, "cwd": str(workdir)})
        base = f"http://127.0.0.1:{port}"
        headers = {}
        password = os.environ.get("OPENCODE_SERVER_PASSWORD")
        if password:
            username = os.environ.get("OPENCODE_SERVER_USERNAME") or "opencode"
            headers["Authorization"] = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def request(path: str, method: str = "GET", timeout: float = 10):
            req = urllib.request.Request(base + path, headers=headers, method=method)
            with opener.open(req, timeout=timeout) as response:
                return json.load(response)

        deadline = time.monotonic() + 30
        result["phase"] = "serve_health"
        health_observations = []
        api_root = ""
        while True:
            healthy = False
            for health_path in ("/global/health", "/api/global/health"):
                observation = {"path": health_path}
                try:
                    response = request(health_path, timeout=2)
                    observation["keys"] = list(response) if isinstance(response, dict) else []
                    if isinstance(response, dict) and response.get("healthy"):
                        healthy = True
                        api_root = health_path.removesuffix("/global/health")
                except urllib.error.HTTPError as exc:
                    observation["status"] = exc.code
                except json.JSONDecodeError:
                    observation["error_type"] = "non_json_response"
                except (OSError, urllib.error.URLError) as exc:
                    observation["error_type"] = type(exc).__name__
                    observation["errno"] = getattr(exc, "errno", None)
                health_observations.append(observation)
                if healthy:
                    break
            result["health_observations"] = health_observations[-4:]
            if healthy:
                break
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Temporary OpenCode server did not become healthy")
            time.sleep(0.2)
        query = "?" + urllib.parse.urlencode({"directory": str(workdir)})
        message_query = "?" + urllib.parse.urlencode({"directory": str(workdir), "limit": 0})
        prefix = api_root + "/session/" + urllib.parse.quote(session, safe="")
        result["phase"] = "verify_before"
        current = request(prefix + "/message" + message_query)
        _json_new(output / "api_before.json", current)
        _json_new(output / "api_before.shape.json", shape(current))
        result["api_before_count"] = len(current)
        verify_selected_identity(rows, current, selected)
        api_before = current
        deleted = []
        for selection in selected:
            # Removing empty reasoning first also leaves a harmless empty
            # separator if execution stops before its step-start is removed.
            for part_id in reversed(selection["part_ids"]):
                result["phase"] = "delete_and_verify"
                path = prefix + "/message/" + urllib.parse.quote(selection["message_id"], safe="")
                path += "/part/" + urllib.parse.quote(part_id, safe="") + query
                if request(path, "DELETE") is not True:
                    raise RuntimeError("Local part DELETE did not return true")
                deleted.append({"message_id": selection["message_id"], "part_ids": [part_id]})
                result["deleted"] = list(deleted)
                current = request(prefix + "/message" + message_query)
                _json_new(output / f"api_after_delete_{len(deleted)}.json", current)
                _json_new(output / f"api_after_delete_{len(deleted)}.shape.json", shape(current))
                verify_only_selected_removed(api_before, current, deleted)
        result["phase"] = "export_after"
        after = _export(binary, session, workdir, output, "after")
        verify_only_selected_removed(rows, after.get("messages") or [], selected)
        result.update({"applied": True, "status": "repaired", "removed_parts": len(deleted)})
        return result
    except Exception as exc:
        result.update({"status": "failed", "error_type": type(exc).__name__})
        if isinstance(exc, urllib.error.HTTPError):
            result["error_http_status"] = exc.code
        if process is not None:
            try:
                _export(binary, session, workdir, output, "after_failure")
            except Exception as export_error:
                result["after_failure_export_error_type"] = type(export_error).__name__
        raise
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()  # Exact Popen handle; never enumerate or kill other processes.
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            result["serve_stopped"] = process.poll() is not None
        if server_log is not None:
            server_log.close()
        _json_new(output / "result.json", result)
        hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in output.iterdir() if path.is_file()}
        _json_new(output / "hashes.json", hashes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opencode", default="opencode")
    parser.add_argument("--session", required=True)
    parser.add_argument("--workdir", type=Path, required=True)
    parser.add_argument("--evidence-events", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = repair(binary=args.opencode, session=args.session,
                        workdir=args.workdir.resolve(strict=True), evidence=args.evidence_events,
                        output=args.output_dir, apply=args.apply)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__,
                          "evidence_directory": str(args.output_dir)}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
