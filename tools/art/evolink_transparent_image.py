#!/usr/bin/env python3
"""Generate one EvoLink GPT Image asset without persisting the API key.

The EvoLink GPT Image 2 route returns PNG automatically when
``background=transparent``.  Its documented request schema does not expose an
``output_format`` field, so this client verifies the downloaded PNG signature
instead of sending an unsupported field.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


GENERATIONS_URL = "https://api.evolink.ai/v1/images/generations"
TASK_URL = "https://api.evolink.ai/v1/tasks/{task_id}"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ACTIVE_STATES = {"pending", "queued", "processing", "running"}
SUCCESS_STATES = {"completed", "succeeded", "success"}
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PAID_OUTPUT_ROOT = (
    REPOSITORY_ROOT / "assets" / "vivhite-ironclad" / "generated" / "evolink-paid"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and download one GPT Image 2 transparent PNG via EvoLink."
    )
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Raw PNG path below assets/vivhite-ironclad/generated/evolink-paid/.",
    )
    parser.add_argument(
        "--task-id",
        help="Resume an existing task without creating or billing another generation.",
    )
    parser.add_argument("--image-url", action="append", default=[])
    parser.add_argument("--size", default="2:3")
    parser.add_argument("--resolution", choices=("1K", "2K", "4K"), default="2K")
    parser.add_argument("--quality", choices=("low", "medium", "high"), default="high")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    return parser.parse_args()


def read_windows_user_environment(name: str) -> str:
    """Read a user-scoped Windows environment value without printing it."""

    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _value_type = winreg.QueryValueEx(key, name)
    except (ImportError, OSError):
        return ""
    return value.strip() if isinstance(value, str) else ""


def require_api_key() -> str:
    api_key = os.environ.get("EVOLINK_API_KEY", "").strip()
    if not api_key:
        api_key = read_windows_user_environment("EVOLINK_API_KEY")
    if not api_key:
        api_key = getpass.getpass("EvoLink API key (hidden): ").strip()
    if not api_key:
        raise RuntimeError("EVOLINK_API_KEY is empty")
    return api_key


def require_paid_output_path(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(PAID_OUTPUT_ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError(
            f"Paid EvoLink output must stay below {PAID_OUTPUT_ROOT}"
        ) from exc
    if resolved.suffix.lower() != ".png":
        raise RuntimeError("Paid EvoLink output must use a .png filename")
    return resolved


def validate_public_reference_urls(urls: list[str]) -> None:
    for url in urls:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise RuntimeError(f"Reference image URL must be public HTTPS: {url!r}")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RuntimeError(
                "Reference image URLs must not contain credentials, query strings, "
                "fragments, or temporary signatures"
            )


def generation_record_paths(output: Path) -> tuple[Path, Path, Path]:
    return (
        output.with_name(f"{output.stem}.prompt.txt"),
        output.with_name(f"{output.stem}.request.json"),
        output.with_name(f"{output.stem}.task.json"),
    )


def write_generation_record(
    output: Path,
    prompt: str,
    payload: dict[str, Any],
) -> None:
    prompt_path, request_path, task_path = generation_record_paths(output)
    conflicts = [
        path for path in (output, prompt_path, request_path, task_path) if path.exists()
    ]
    if conflicts:
        joined = ", ".join(str(path) for path in conflicts)
        raise RuntimeError(f"Refusing to overwrite paid generation record: {joined}")

    output.parent.mkdir(parents=True, exist_ok=True)
    # The sidecar must be byte-for-byte equivalent to the string sent in the
    # JSON payload. Do not add a newline that was not part of the actual prompt.
    prompt_path.write_text(prompt, encoding="utf-8")
    request_record = {"endpoint": GENERATIONS_URL, **payload}
    request_path.write_text(
        json.dumps(request_record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_or_validate_task_record(output: Path, task_id: str) -> None:
    _prompt_path, _request_path, task_path = generation_record_paths(output)
    # The opaque task id is enough to resume with the fixed TASK_URL template.
    # Do not persist result/download URLs, which may be temporary or signed.
    record = {"task_id": task_id}
    if task_path.exists():
        try:
            existing = json.loads(task_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Unreadable EvoLink task record: {task_path}") from exc
        if existing != record:
            raise RuntimeError(
                f"Task id does not match archived generation record: {task_path}"
            )
        return
    task_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def require_resume_record(output: Path, task_id: str) -> None:
    prompt_path, request_path, _task_path = generation_record_paths(output)
    missing = [path for path in (prompt_path, request_path) if not path.is_file()]
    if missing:
        joined = ", ".join(str(path) for path in missing)
        raise RuntimeError(
            "Refusing to resume a paid task without its archived prompt and "
            f"sanitized request record: {joined}"
        )
    if not prompt_path.read_text(encoding="utf-8").strip():
        raise RuntimeError(f"Archived prompt is empty: {prompt_path}")
    try:
        request_record = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unreadable archived request record: {request_path}") from exc
    if not isinstance(request_record, dict):
        raise RuntimeError(f"Archived request record is not an object: {request_path}")
    expected = {
        "endpoint": GENERATIONS_URL,
        "model": "gpt-image-2",
        "background": "transparent",
        "n": 1,
    }
    for field, value in expected.items():
        if request_record.get(field) != value:
            raise RuntimeError(
                f"Archived request record has invalid {field!r}: {request_path}"
            )
    for field in ("size", "resolution", "quality", "image_urls"):
        if field not in request_record:
            raise RuntimeError(
                f"Archived request record is missing {field!r}: {request_path}"
            )
    if "output_format" in request_record or "response_format" in request_record:
        raise RuntimeError(
            f"Archived request uses an unsupported output-format field: {request_path}"
        )
    write_or_validate_task_record(output, task_id)


def http_json(
    request: Request,
    operation: str,
    timeout: float = 60,
) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            raw_data = response.read()
    except HTTPError as exc:
        raw_error = exc.read()
        try:
            error_data = json.loads(raw_error.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            error_data = raw_error.decode("utf-8", errors="replace")
        raise RuntimeError(f"{operation} failed with HTTP {exc.code}: {error_data}") from exc
    except URLError as exc:
        raise RuntimeError(f"{operation} failed: {exc.reason}") from exc

    try:
        data = json.loads(raw_data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{operation} returned HTTP {status} with non-JSON content") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{operation} returned a non-object JSON response")
    return data


def find_task_id(data: dict[str, Any]) -> str:
    task_id = data.get("id")
    if not task_id and isinstance(data.get("data"), dict):
        task_id = data["data"].get("task_id") or data["data"].get("id")
    if not isinstance(task_id, str) or not task_id:
        raise RuntimeError("EvoLink response did not contain a task id")
    return task_id


def find_result_urls(data: dict[str, Any]) -> list[str]:
    candidates: Any = data.get("results")
    if candidates is None and isinstance(data.get("data"), dict):
        candidates = data["data"].get("results") or data["data"].get("images")
    if not isinstance(candidates, list):
        return []

    urls: list[str] = []
    for candidate in candidates:
        if isinstance(candidate, str):
            urls.append(candidate)
        elif isinstance(candidate, dict):
            url = candidate.get("url") or candidate.get("image_url")
            if isinstance(url, str):
                urls.append(url)
    return urls


def main() -> int:
    args = parse_args()
    args.output = require_paid_output_path(args.output)
    validate_public_reference_urls(args.image_url)
    if args.output.exists():
        raise RuntimeError(f"Refusing to overwrite existing output: {args.output}")

    api_key = require_api_key()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if args.task_id:
        task_id = args.task_id
        require_resume_record(args.output, task_id)
        task = {}
        print(f"Resuming task {task_id}", flush=True)
    else:
        if args.prompt_file is None:
            raise RuntimeError("--prompt-file is required when creating a task")
        prompt = args.prompt_file.read_text(encoding="utf-8").strip()
        if not prompt:
            raise RuntimeError(f"Prompt file is empty: {args.prompt_file}")
        payload = {
            "model": "gpt-image-2",
            "prompt": prompt,
            "size": args.size,
            "resolution": args.resolution,
            "quality": args.quality,
            "background": "transparent",
            "n": 1,
            "image_urls": args.image_url,
        }
        write_generation_record(args.output, prompt, payload)

        create_request = Request(
            GENERATIONS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        task = http_json(create_request, "generation request")
        task_id = find_task_id(task)
        write_or_validate_task_record(args.output, task_id)
        print(f"Created task {task_id}", flush=True)

    deadline = time.monotonic() + args.timeout_seconds
    last_status = ""
    result = task
    while time.monotonic() < deadline:
        status = str(result.get("status", "")).lower()
        urls = find_result_urls(result)
        if urls:
            break
        if status and status not in ACTIVE_STATES and status not in SUCCESS_STATES:
            message = result.get("message") or result.get("error") or result.get("detail")
            raise RuntimeError(f"Generation stopped with status {status!r}: {message}")
        if status != last_status:
            print(f"Task status: {status or 'unknown'}", flush=True)
            last_status = status
        time.sleep(args.poll_seconds)
        poll_request = Request(
            TASK_URL.format(task_id=task_id),
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        result = http_json(poll_request, "task poll")
    else:
        raise TimeoutError(f"Generation did not finish within {args.timeout_seconds:g} seconds")

    urls = find_result_urls(result)
    if not urls:
        raise RuntimeError("Generation completed without a result URL")

    try:
        download_request = Request(
            urls[0],
            headers={
                "Accept": "image/avif,image/webp,image/png,*/*;q=0.8",
                "Referer": "https://evolink.ai/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                ),
            },
            method="GET",
        )
        with urlopen(download_request, timeout=120) as download:
            image_bytes = download.read()
            content_type = download.headers.get("Content-Type", "unknown")
    except HTTPError as exc:
        body = exc.read(512).decode("utf-8", errors="replace")
        raise RuntimeError(f"image download failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"image download failed: {exc.reason}") from exc
    if not image_bytes.startswith(PNG_SIGNATURE):
        unexpected_path = args.output.with_name(f"{args.output.stem}.unexpected-response.bin")
        if not unexpected_path.exists():
            unexpected_path.write_bytes(image_bytes)
        raise RuntimeError(
            f"Transparent result is not a PNG (Content-Type: {content_type})"
        )

    args.output.write_bytes(image_bytes)
    print(f"Saved PNG: {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, TimeoutError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
