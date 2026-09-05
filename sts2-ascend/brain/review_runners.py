"""Provider-specific adapters for the sts2-ascend review worker.

The host owns evidence, isolation, validation, Git and retry transactions.  A
runner adapter is deliberately limited to selecting a configured backend,
building its command line and translating its event stream.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
from email.utils import parsedate_to_datetime
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import time
from typing import Any, Iterable


@dataclass(frozen=True)
class ProviderRateLimit:
    """A provider-side HTTP 429 signal extracted from a runner event.

    The review host deliberately receives a small, structured record instead of
    having to grep a provider's localized output.  ``retry_after_seconds`` is
    an advisory delay; the queue host must still apply its own upper bound before
    persisting it.  A missing header is represented by ``None`` and never means
    that the request is immediately safe to retry.
    """

    status_code: int = 429
    retry_after_seconds: float | None = None
    message: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status_code": self.status_code,
            "retry_after_seconds": self.retry_after_seconds,
            "message": self.message,
            "source": self.source,
        }


# A descriptive alias makes call sites read naturally while retaining one
# concrete type for JSONL translators and tests.
RateLimitSignal = ProviderRateLimit


@dataclass(frozen=True)
class ProviderUnavailable:
    """A structured provider account/billing failure with no model work.

    Catalog probes only prove that a model id exists.  Providers can still
    reject the paid request because the account has no remaining balance.  The
    host needs this signal to cool that backend and continue down the configured
    priority chain instead of retrying it every few minutes.
    """

    status_code: int
    reason: str
    message: str = ""
    source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status_code": self.status_code,
            "reason": self.reason,
            "message": self.message,
            "source": self.source,
        }


_RETRY_AFTER_KEYS = frozenset({
    "retry-after", "retry_after", "retryafter",
})
_STATUS_KEYS = frozenset({
    "status", "status_code", "status-code", "statuscode",
    "http_status", "http-status", "httpstatus", "http_code", "http-code",
    "httpcode", "response_status", "response-status", "responsestatus",
    "code", "error_code", "error-code", "errorcode",
})
_STATUS_CODE_RE = re.compile(
    r"(?i)\b(?:https?\s*/?\s*\d(?:\.\d)?\s*[:=]?\s*|"
    r"http(?:[_ -]?status|[_ -]?code)?\s*[:=]?\s*|"
    r"status(?:[_ -]?code)?\s*[:=]?\s*)429\b")
_429_PHRASE_RE = re.compile(
    r"(?i)\b(?:429\s*(?:[-:|]\s*)?(?:too\s+many\s+requests|"
    r"rate[_ -]?limit(?:ed|\s+exceeded)?)|"
    r"(?:too\s+many\s+requests|rate[_ -]?limit(?:ed|\s+exceeded)|"
    r"rate_limit_exceeded|too_many_requests)\s*(?:\(|\[|[-:|,]\s*)?"
    r"(?:http\s*)?429\b)")
_RATE_LIMIT_TOKEN_RE = re.compile(
    r"(?i)\b(?:rate_limit_exceeded|too_many_requests)\b")
_RETRY_AFTER_TEXT_RE = re.compile(
    r"(?im)\bretry[\s_-]*after\s*[:=]\s*([^\r\n;]+)")
_CREDIT_UNAVAILABLE_RE = re.compile(
    r"(?i)\b(?:insufficient\s+(?:account\s+)?(?:balance|credits?)|"
    r"(?:account\s+)?(?:balance|credits?)\s+(?:is\s+)?(?:exhausted|depleted)|"
    r"billing[_ -]?(?:quota|balance)\s+(?:is\s+)?(?:exhausted|depleted))\b")
_CREDIT_ERROR_TOKEN_RE = re.compile(
    r"(?i)\b(?:credits?error|insufficient[_-](?:balance|credits?)|"
    r"billing[_-](?:quota|balance)[_-](?:exhausted|depleted))\b")


def parse_retry_after(value: Any, *, now: float | None = None) -> float | None:
    """Parse a Retry-After delta or HTTP date into non-negative seconds.

    Provider payloads are untrusted.  Booleans, NaN/Infinity, negative values,
    and malformed dates are rejected.  Date values are evaluated against the
    supplied wall clock (or ``time.time``) so tests and callers can be
    deterministic.
    """

    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if number < 0 or number != number or number in (float("inf"), float("-inf")):
            return None
        return number
    text = str(value).strip()
    if not text:
        return None
    # Header deltas are decimal seconds in practice.  Do not accept arbitrary
    # text with a number embedded in it; that caused ordinary error messages to
    # become accidental retry delays in earlier host implementations.
    if re.fullmatch(r"\+?(?:\d+(?:\.\d*)?|\.\d+)", text):
        try:
            number = float(text.lstrip("+"))
        except (TypeError, ValueError, OverflowError):
            return None
        if number != number or number in (float("inf"), float("-inf")):
            return None
        return max(0.0, number)
    try:
        target = parsedate_to_datetime(text)
        if target is None:
            return None
        if target.tzinfo is None:
            # RFC 7231 dates are GMT; a naive parser result is therefore safest
            # when explicitly treated as UTC rather than local wall time.
            from datetime import timezone
            target = target.replace(tzinfo=timezone.utc)
        seconds = target.timestamp() - (time.time() if now is None else float(now))
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    if seconds != seconds or seconds in (float("inf"), float("-inf")):
        return None
    return max(0.0, seconds)


def _normalized_payload_key(value: Any) -> str:
    return str(value or "").strip().casefold().replace(" ", "_")


def _status_from_payload(value: Any, path: str = "") -> tuple[int | None, str]:
    """Find an explicit HTTP status field without trusting arbitrary text."""

    if isinstance(value, dict):
        for key, child in value.items():
            normalized = _normalized_payload_key(key).replace("_", "-")
            if normalized in _STATUS_KEYS:
                try:
                    if isinstance(child, bool):
                        continue
                    number = int(str(child).strip())
                except (TypeError, ValueError, OverflowError):
                    number = None
                if number is not None and 100 <= number <= 599:
                    return number, f"{path}.{key}" if path else str(key)
            found = _status_from_payload(
                child, f"{path}.{key}" if path else str(key))
            if found[0] is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            found = _status_from_payload(child, f"{path}[{index}]")
            if found[0] is not None:
                return found
    return None, ""


def _retry_after_from_payload(value: Any, *, now: float | None = None) -> float | None:
    """Find a case-insensitive Retry-After field or header line."""

    if isinstance(value, dict):
        # Prefer an explicit header over numbers mentioned in a message.
        for key, child in value.items():
            normalized = _normalized_payload_key(key).replace("_", "-")
            if normalized in _RETRY_AFTER_KEYS:
                parsed = parse_retry_after(child, now=now)
                if parsed is not None:
                    return parsed
        for key, child in value.items():
            parsed = _retry_after_from_payload(
                child, now=now)
            if parsed is not None:
                return parsed
    elif isinstance(value, (list, tuple)):
        for child in value:
            parsed = _retry_after_from_payload(child, now=now)
            if parsed is not None:
                return parsed
    elif isinstance(value, str):
        match = _RETRY_AFTER_TEXT_RE.search(value)
        if match:
            return parse_retry_after(match.group(1).strip(), now=now)
    return None


def _payload_text(value: Any, *, limit: int = 2000) -> str:
    """Produce bounded text solely for descriptive phrase matching."""

    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, dict):
        pieces: list[str] = []
        # Error/message fields carry the useful provider wording.  Include all
        # values as a fallback because different runner versions use different
        # field names, but cap the aggregate to avoid unbounded diagnostics.
        preferred = ("error", "message", "detail", "reason", "body", "output")
        ordered = [*(value.get(key) for key in preferred if key in value),
                   *(child for key, child in value.items() if key not in preferred)]
        for child in ordered:
            if child is None or isinstance(child, (dict, list, tuple)):
                if isinstance(child, (dict, list, tuple)):
                    pieces.append(_payload_text(child, limit=max(1, limit - sum(map(len, pieces)))))
            else:
                pieces.append(str(child))
            if sum(map(len, pieces)) >= limit:
                break
        return " ".join(pieces)[:limit]
    if isinstance(value, (list, tuple)):
        return " ".join(_payload_text(child, limit=limit) for child in value)[:limit]
    return str(value)[:limit]


def detect_provider_rate_limit(
    payload: Any, *, now: float | None = None,
    allow_bare_error_token: bool | None = None,
) -> ProviderRateLimit | None:
    """Return a 429 signal only for explicit status or unambiguous wording.

    Merely seeing the digits ``429`` in a normal model/tool message is not
    enough.  A structured status field, an HTTP/status-code phrase, or the
    canonical provider error tokens is required.  This keeps ordinary errors,
    source snippets and user text from triggering model-affinity recovery.
    """

    status, status_source = _status_from_payload(payload)
    text = _payload_text(payload)
    text_status = bool(_STATUS_CODE_RE.search(text) or _429_PHRASE_RE.search(text))
    if allow_bare_error_token is None:
        allow_bare_error_token = isinstance(payload, (dict, list, tuple))
    token_status = bool(
        allow_bare_error_token and _RATE_LIMIT_TOKEN_RE.search(text))
    if status != 429 and not text_status and not token_status:
        return None
    # An explicit non-429 status wins over an incidental phrase in its message.
    if status is not None and status != 429:
        return None
    retry_after = _retry_after_from_payload(payload, now=now)
    if status == 429:
        source = status_source or "status"
    elif text_status:
        source = "message"
    else:
        source = "error_code"
    message = " ".join(text.split())[:500]
    return ProviderRateLimit(
        status_code=429,
        retry_after_seconds=retry_after,
        message=message,
        source=source,
    )


def detect_provider_unavailable(payload: Any) -> ProviderUnavailable | None:
    """Return only explicit account-credit/billing unavailability signals.

    Ordinary authentication errors and prose mentioning a low balance are not
    enough.  The payload must carry an unambiguous credit marker and either a
    structured 401/402/403 status or a provider error token such as
    ``CreditsError``.
    """

    status, status_source = _status_from_payload(payload)
    text = _payload_text(payload)
    credit_phrase = bool(_CREDIT_UNAVAILABLE_RE.search(text))
    credit_token = bool(_CREDIT_ERROR_TOKEN_RE.search(text))
    if not (credit_phrase or credit_token):
        return None
    if status not in {401, 402, 403} and not credit_token:
        return None
    return ProviderUnavailable(
        status_code=int(status or 402),
        reason="insufficient_credits",
        message=" ".join(text.split())[:500],
        source=status_source or ("error_code" if credit_token else "message"),
    )


@dataclass(frozen=True)
class ReviewPlan:
    """One immutable entry in the configured review priority chain."""

    key: str
    priority: int
    runner: str
    model: str
    every_runs: int
    source: str
    variant: str | None = None
    reasoning_effort: str | None = None
    approve_for_me: bool = False
    sandbox: str = "workspace-write"
    available: bool = True
    unavailable_reason: str = ""

    @property
    def display_model(self) -> str:
        if self.runner == "opencode" and self.variant:
            return f"{self.model}@{self.variant}"
        if self.runner == "codex" and self.reasoning_effort:
            return f"{self.model}@{self.reasoning_effort}"
        return self.model

    @property
    def state_key(self) -> str:
        return self.key or f"{self.runner}:{self.display_model}"

    def as_queue_fields(self) -> dict:
        return {
            "backend_key": self.key,
            "priority": self.priority,
            "runner": self.runner,
            "model": self.model,
            "variant": self.variant or "",
            "reasoning_effort": self.reasoning_effort or "",
            "approve_for_me": self.approve_for_me,
            "sandbox": self.sandbox,
            "every": self.every_runs,
            "source": self.source,
        }

    def __iter__(self):
        """Keep legacy ``model, every, source = resolve_review_plan(...)`` callers."""
        yield self.display_model
        yield self.every_runs
        yield self.source


def _positive_int(value, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return max(1, int(default))


def _split_opencode_model(model: str, variant=None) -> tuple[str, str | None]:
    explicit_variant = str(variant or "").strip() or None
    if "@" in model:
        model_id, embedded = model.rsplit("@", 1)
        return model_id, explicit_variant or embedded or None
    return model, explicit_variant


def review_plans_from_config(cfg: dict) -> list[ReviewPlan]:
    """Normalize the new runner-aware chain, or synthesize the legacy chain."""
    raw_chain = cfg.get("review_model_chain")
    plans: list[ReviewPlan] = []
    if isinstance(raw_chain, list) and raw_chain:
        usable = [item for item in raw_chain
                  if isinstance(item, dict) and str(item.get("model") or "").strip()]
        for index, item in enumerate(usable):
            runner = str(item.get("runner") or "opencode").strip().lower()
            model = str(item.get("model") or "").strip()
            variant = str(item.get("variant") or "").strip() or None
            if runner == "opencode":
                model, variant = _split_opencode_model(model, variant)
            reasoning = str(item.get("reasoning_effort") or "").strip() or None
            priority = _positive_int(item.get("priority"), index + 1)
            key = str(item.get("key") or "").strip()
            if not key:
                suffix = variant if runner == "opencode" else reasoning
                key = f"{runner}:{model}" + (f"@{suffix}" if suffix else "")
            plans.append(ReviewPlan(
                key=key,
                priority=priority,
                runner=runner,
                model=model,
                variant=variant,
                reasoning_effort=reasoning,
                approve_for_me=bool(item.get("approve_for_me", False)),
                sandbox=str(item.get("sandbox") or "workspace-write"),
                every_runs=_positive_int(item.get("every_runs"), 1),
                source=str(item.get("source") or "auto"),
            ))
        if not plans:
            legacy_cfg = dict(cfg)
            legacy_cfg["review_model_chain"] = []
            return review_plans_from_config(legacy_cfg)
        ordered = sorted(plans, key=lambda plan: plan.priority)
        return [
            (replace(plan, source=("fallback" if index == len(ordered) - 1
                                   else "preferred"))
             if plan.source == "auto" else plan)
            for index, plan in enumerate(ordered)
        ]

    preferred = cfg.get("preferred_models")
    if not isinstance(preferred, list) or not preferred:
        single = cfg.get("preferred_model")
        preferred = [single] if single else []
    for index, entry in enumerate(str(value) for value in preferred if value):
        model, variant = _split_opencode_model(entry)
        plans.append(ReviewPlan(
            key=entry,
            priority=index + 1,
            runner="opencode",
            model=model,
            variant=variant,
            every_runs=_positive_int(cfg.get("preferred_every_runs"), 1),
            source="preferred",
        ))

    fallback_runner = str(cfg.get("runner") or "opencode").strip().lower()
    fallback_model = str(cfg.get("model") or "kimi-for-coding/k3").strip()
    fallback_variant = None
    if fallback_runner == "opencode":
        fallback_model, fallback_variant = _split_opencode_model(fallback_model)
    plans.append(ReviewPlan(
        key=f"{fallback_runner}:{fallback_model}"
            + (f"@{fallback_variant}" if fallback_variant else ""),
        priority=len(plans) + 1,
        runner=fallback_runner,
        model=fallback_model,
        variant=fallback_variant,
        every_runs=_positive_int(cfg.get("review_every_runs"), 5),
        source="fallback",
    ))
    return plans


def runner_binary(cfg: dict, runner: str) -> str | None:
    bins = cfg.get("runner_bins")
    configured = bins.get(runner) if isinstance(bins, dict) else None
    if not configured:
        configured = (cfg.get("opencode_bin", "opencode") if runner == "opencode"
                      else cfg.get("codex_bin", "codex") if runner == "codex"
                      else cfg.get(f"{runner}_bin", runner))
    # Runner paths may point at a pinned, non-global user cache.  Expanding the
    # placeholder keeps config independent of the Windows account name while
    # still resolving one exact executable.
    return shutil.which(os.path.expandvars(str(configured)))


def build_review_command(
    plan: ReviewPlan, binary: str, workdir: Path | str, prompt: str, *, title: str,
) -> list[str]:
    """Build a non-interactive command for one provider."""
    root = str(workdir)
    if plan.runner == "opencode":
        command = [
            binary, "run", "--model", plan.model, "--format", "json", "--thinking",
        ]
        if plan.variant:
            command += ["--variant", plan.variant]
        command += ["--title", title, "--dir", root, "--auto", prompt]
        return command
    if plan.runner == "codex":
        # ``-a`` is a global option and must precede ``exec``.  Keep both the
        # approval policy and custom permission profile explicit so a trusted
        # parent repository in the user's config cannot widen this invocation.
        command = [binary, "-a", "never", "exec", "--model", plan.model]
        if plan.reasoning_effort:
            command += ["-c", f'model_reasoning_effort="{plan.reasoning_effort}"']
        if plan.sandbox != "workspace-write":
            raise ValueError(
                "codex review requires workspace-write configuration semantics; "
                f"configured sandbox={plan.sandbox!r}")
        command += [
            "-c", 'windows.sandbox="unelevated"',
            "-c", (
                'permissions.luna_commit={extends=":workspace",'
                'filesystem={":workspace_roots"={".git"="write"}},'
                'network={enabled=false}}'),
            "-c", 'default_permissions="luna_commit"',
            "--json", "--ephemeral", "--ignore-user-config",
            "--color", "never", "-C", root, prompt,
        ]
        return command
    raise ValueError(f"unsupported review runner: {plan.runner}")


def bind_review_workdir(command: Iterable[str], runner: str, workdir: Path | str) -> list[str]:
    """Replace only the runner's explicit workspace argument."""
    bound = list(command)
    flags = ("--dir",) if runner == "opencode" else ("-C", "--cd") if runner == "codex" else ()
    for flag in flags:
        try:
            index = bound.index(flag)
        except ValueError:
            continue
        if index + 1 >= len(bound):
            break
        bound[index + 1] = str(workdir)
        return bound
    raise ValueError(f"review command for runner={runner} lacks a workspace argument")


class _TranslatorBase:
    def __init__(self) -> None:
        self.event_count = 0
        self.error_count = 0
        self.non_json_lines = 0
        self.model_work_started = False
        self.rate_limit: ProviderRateLimit | None = None
        self.provider_unavailable: ProviderUnavailable | None = None
        self.usage: dict[str, int] = {}
        self.started_monotonic = 0.0
        self.first_event_after_sec: float | None = None
        self.first_model_work_after_sec: float | None = None
        self.reset_clock()

    def reset_clock(self) -> None:
        """Start provider-latency timing immediately before the CLI stream."""
        self.started_monotonic = time.monotonic()
        self.first_event_after_sec = None
        self.first_model_work_after_sec = None

    def _mark_model_work(self) -> None:
        self.model_work_started = True
        if self.first_model_work_after_sec is None:
            self.first_model_work_after_sec = max(
                0.0, time.monotonic() - self.started_monotonic)

    def _event(self) -> None:
        self.event_count += 1
        if self.first_event_after_sec is None:
            self.first_event_after_sec = max(0.0, time.monotonic() - self.started_monotonic)

    def _record_rate_limit(self, payload: Any) -> bool:
        """Record one provider 429 without changing model-work accounting."""
        signal = detect_provider_rate_limit(payload)
        if signal is None:
            return False
        current = self.rate_limit
        # If a stream retries several times, retain the most conservative server
        # delay while preserving the first useful diagnostic/source.
        if current is None:
            self.rate_limit = signal
        else:
            current_delay = current.retry_after_seconds
            signal_delay = signal.retry_after_seconds
            if (current_delay is None and signal_delay is not None) or (
                    current_delay is not None and signal_delay is not None
                    and signal_delay > current_delay):
                self.rate_limit = ProviderRateLimit(
                    status_code=429,
                    retry_after_seconds=signal_delay,
                    message=current.message or signal.message,
                    source=current.source or signal.source,
                )
        return True

    def _record_provider_unavailable(self, payload: Any) -> bool:
        """Record a terminal account/billing error without claiming model work."""
        signal = detect_provider_unavailable(payload)
        if signal is None:
            return False
        if self.provider_unavailable is None:
            self.provider_unavailable = signal
        return True

    def metrics(self) -> dict:
        signal = self.rate_limit
        unavailable = self.provider_unavailable
        payload = {
            "event_count": self.event_count,
            "error_count": self.error_count,
            "non_json_lines": self.non_json_lines,
            "model_work_started": self.model_work_started,
            "first_event_after_sec": self.first_event_after_sec,
            "first_model_work_after_sec": self.first_model_work_after_sec,
            "usage": dict(self.usage),
            # Keep both the descriptive and compact keys stable for older host
            # callers while making the nested record the canonical form.
            "rate_limit_detected": signal is not None,
            "rate_limited": signal is not None,
            "rate_limit_status": signal.status_code if signal else None,
            "retry_after_seconds": (
                signal.retry_after_seconds if signal else None),
            "rate_limit_retry_after_seconds": (
                signal.retry_after_seconds if signal else None),
            "rate_limit_message": signal.message if signal else "",
            "rate_limit_source": signal.source if signal else "",
            "provider_unavailable_detected": unavailable is not None,
            "provider_unavailable_status": (
                unavailable.status_code if unavailable else None),
            "provider_unavailable_reason": (
                unavailable.reason if unavailable else ""),
            "provider_unavailable_message": (
                unavailable.message if unavailable else ""),
            "provider_unavailable_source": (
                unavailable.source if unavailable else ""),
        }
        if signal is not None:
            payload["rate_limit"] = signal.as_dict()
        if unavailable is not None:
            payload["provider_unavailable"] = unavailable.as_dict()
        return payload


class OpencodeJsonTranslator(_TranslatorBase):
    """Translate OpenCode incremental JSON events into bounded live text."""

    def __init__(self) -> None:
        super().__init__()
        self._seen: OrderedDict[str, int] = OrderedDict()
        self._seen_limit = 4096

    def feed(self, raw: str) -> list[str]:
        text = raw.strip()
        if not text:
            return []
        if not text.startswith("{"):
            self.non_json_lines += 1
            self._record_rate_limit(text)
            self._record_provider_unavailable(text)
            return [text]
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            self.non_json_lines += 1
            self._record_rate_limit(text)
            self._record_provider_unavailable(text)
            return [text]
        if not isinstance(event, dict):
            self.non_json_lines += 1
            return [text]
        self._event()
        # Only error-shaped events are allowed to contribute text-based 429
        # signals.  Explicit nested status fields remain safe regardless of the
        # event type and are handled by the same structured parser.
        error_payload = (
            event if (str(event.get("type") or "").casefold() in {
                "error", "failed", "failure", "provider_error"}
                or isinstance(event.get("error"), (dict, list, str))
                or event.get("status") == 429)
            else {key: event[key] for key in (
                "status", "status_code", "http_status", "headers",
                "response", "error") if key in event})
        self._record_rate_limit(error_payload)
        self._record_provider_unavailable(error_payload)
        raw_part = event.get("part")
        if raw_part is not None and not isinstance(raw_part, dict):
            self.non_json_lines += 1
            return [text]
        part = raw_part if isinstance(raw_part, dict) else {}
        part_type = part.get("type") or event.get("type") or ""
        raw_id = str(part.get("id") or "")
        part_id = hashlib.blake2s(
            raw_id.encode("utf-8", errors="replace"), digest_size=16).hexdigest()
        if part_type in ("text", "reasoning"):
            self._mark_model_work()
            value = part.get("text") or ""
            if not isinstance(value, str):
                value = str(value)
            previous = self._seen.get(part_id, 0)
            if len(value) <= previous:
                if part_id in self._seen:
                    self._seen.move_to_end(part_id)
                return []
            self._seen[part_id] = len(value)
            self._seen.move_to_end(part_id)
            while len(self._seen) > self._seen_limit:
                self._seen.popitem(last=False)
            prefix = "💭 " if part_type == "reasoning" and previous == 0 else ""
            return [prefix + value[previous:]]
        if part_type in ("tool", "tool-call", "tool_call", "tool-use", "tool-result", "tool_result"):
            self._mark_model_work()
            name = part.get("tool") or part.get("name") or "tool"
            brief = json.dumps(part.get("input") or part.get("args") or {},
                               ensure_ascii=False)[:160]
            return [f"⚙ {name} {brief}"]
        if part_type == "patch":
            self._mark_model_work()
            files = part.get("files") or []
            return ["📦 修改 " + ", ".join(str(path).split("/")[-1] for path in files)]
        if part_type == "step-finish":
            raw_tokens = part.get("tokens")
            tokens = raw_tokens if isinstance(raw_tokens, dict) else {}
            total = tokens.get("total")
            if isinstance(total, int):
                self.usage["total_tokens"] = total
            return [f"· tokens {total} ·"] if total else []
        if part_type == "error" or event.get("type") == "error":
            self.error_count += 1
            self._record_rate_limit(part)
            self._record_provider_unavailable(part)
        return []


class RunnerToolPathEscape(RuntimeError):
    """Fatal tripwire for reported ``file_change`` paths outside the clone.

    This JSONL guard terminates and preserves a suspicious run.  It is not the
    write barrier; the explicit OS custom permissions profile owns that role.
    """


class CodexJsonTranslator(_TranslatorBase):
    """Translate ``codex exec --json`` JSONL and retain evaluation metrics."""

    def __init__(self, expected_clone_root: Path | str | None = None) -> None:
        super().__init__()
        self.thread_id = ""
        self.command_count = 0
        self.file_change_count = 0
        self.tool_count = 0
        self.blocked_tool_count = 0
        self.tool_access_error = ""
        self.tool_access_failure_code = ""
        self.final_message = ""
        self.tool_path_escape_count = 0
        self.tool_path_escape = ""
        self._expected_clone_root_absolute: Path | None = None
        self._expected_clone_root_resolved: Path | None = None
        if expected_clone_root is not None:
            self.bind_expected_clone_root(expected_clone_root)

    def bind_expected_clone_root(self, root: Path | str) -> None:
        """Bind file-change telemetry to the exact disposable clone root."""
        absolute = Path(root).absolute()
        resolved = absolute.resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError(f"expected Codex clone root is not a directory: {root}")
        self._expected_clone_root_absolute = absolute
        self._expected_clone_root_resolved = resolved

    def _reported_file_change_paths(self, item: dict) -> list[str]:
        changes = item.get("changes")
        if not isinstance(changes, list) or not changes:
            self._raise_tool_path_escape(
                self._brief(changes), "malformed Codex file_change changes")
        paths: list[str] = []
        for entry in changes:
            value = entry.get("path") if isinstance(entry, dict) else None
            if not isinstance(value, str) or not value.strip():
                self._raise_tool_path_escape(
                    self._brief(entry), "malformed Codex file_change path")
            paths.append(value)
        return paths

    def _raise_tool_path_escape(self, raw_path: str, detail: str) -> None:
        summary = self._brief(raw_path, 500)
        self.tool_path_escape_count += 1
        self.tool_path_escape = summary
        self.tool_access_error = f"{detail}: {summary}"
        self.tool_access_failure_code = "runner_tool_path_escape"
        self.error_count += 1
        raise RunnerToolPathEscape(self.tool_access_error)

    def _guard_reported_file_change_paths(self, item: dict) -> None:
        for raw_path in self._reported_file_change_paths(item):
            if (self._expected_clone_root_absolute is None
                    or self._expected_clone_root_resolved is None):
                self._raise_tool_path_escape(
                    raw_path, "Codex file_change received without expected clone root")
            if "\x00" in raw_path:
                self._raise_tool_path_escape(raw_path, "invalid Codex file_change path")

            # A Windows drive-qualified path is absolute only with a root.  A
            # drive-relative form such as C:foo is ambiguous and cannot be
            # proven to belong to the clone, so fail closed.
            windows_path = PureWindowsPath(raw_path)
            if windows_path.drive and not windows_path.is_absolute():
                self._raise_tool_path_escape(
                    raw_path, "ambiguous drive-relative Codex file_change path")
            if os.name != "nt" and windows_path.is_absolute():
                self._raise_tool_path_escape(
                    raw_path, "foreign absolute Codex file_change path")

            try:
                candidate = Path(raw_path)
                if not candidate.is_absolute():
                    candidate = self._expected_clone_root_absolute / candidate
                lexical = candidate.absolute()
                resolved = candidate.resolve(strict=False)
                lexical_inside = lexical.is_relative_to(
                    self._expected_clone_root_absolute)
                resolved_inside = resolved.is_relative_to(
                    self._expected_clone_root_resolved)
            except (OSError, RuntimeError, ValueError) as exc:
                self._raise_tool_path_escape(
                    raw_path, f"unresolvable Codex file_change path ({exc})")
            if not lexical_inside or not resolved_inside:
                self._raise_tool_path_escape(
                    raw_path, "Codex file_change escaped expected clone root")

    @staticmethod
    def _brief(value, limit: int = 200) -> str:
        if isinstance(value, str):
            return " ".join(value.split())[:limit]
        return json.dumps(value, ensure_ascii=False)[:limit]

    def metrics(self) -> dict:
        payload = super().metrics()
        payload.update({
            "thread_id": self.thread_id,
            "command_count": self.command_count,
            "file_change_count": self.file_change_count,
            "tool_count": self.tool_count,
            "blocked_tool_count": self.blocked_tool_count,
            "tool_access_error": self.tool_access_error,
            "tool_access_failure_code": self.tool_access_failure_code,
            "tool_path_escape_count": self.tool_path_escape_count,
            "tool_path_escape": self.tool_path_escape,
            "final_message_chars": len(self.final_message),
        })
        return payload

    def _record_tool_access_error(
        self, value, *, error_already_counted: bool = False,
        tool_context: bool = False,
    ) -> bool:
        searchable = (value if isinstance(value, str)
                      else json.dumps(value, ensure_ascii=False))
        summary = self._brief(value, 500)
        lowered = searchable.lower()
        denied = "access is denied" in lowered or "access denied" in lowered
        policy_blocked = "blocked by policy" in lowered
        reparse = "path contains a reparse point" in lowered
        contextual = tool_context or any(marker in lowered for marker in (
            "codex_core::tools", "tools::router", "createprocess", "exec_command",
            "apply_patch", "apply patch", "patch verifier",
        ))
        # The reparse wording may also occur in an ordinary subprocess
        # traceback (including a filename such as apply_patch_worker.py).  Only
        # Codex's native router signature or Luna's explicit blocked-tool final
        # is sufficient to attribute it to the host filesystem helper.
        reparse_contextual = (
            "codex_core::tools::router:" in lowered
            or (tool_context and "blocked_tool_capability" in lowered)
        )
        policy_contextual = (
            "codex_core::tools::router:" in lowered
            or (tool_context and "blocked_tool_capability" in lowered)
        )
        if (not (policy_blocked and policy_contextual)
                and not (denied and contextual)
                and not (reparse and reparse_contextual)):
            return False
        self.blocked_tool_count += 1
        self.tool_access_error = summary
        self.tool_access_failure_code = (
            "runner_tool_path_capability" if reparse
            else "runner_tool_access_denied")
        if not error_already_counted:
            self.error_count += 1
        return True

    def _non_json(self, text: str) -> list[str]:
        self.non_json_lines += 1
        self._record_tool_access_error(text)
        self._record_provider_unavailable(text)
        return [text]

    def feed(self, raw: str) -> list[str]:
        text = raw.strip()
        if not text:
            return []
        if not text.startswith("{"):
            self._record_rate_limit(text)
            return self._non_json(text)
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            self._record_rate_limit(text)
            return self._non_json(text)
        if not isinstance(event, dict):
            return self._non_json(text)
        self._event()
        event_type = str(event.get("type") or "")
        if event_type.casefold() in {
                "error", "turn.failed", "turn.error", "provider_error",
        } or isinstance(event.get("error"), (dict, list, str)):
            self._record_rate_limit(event)
            self._record_provider_unavailable(event)
        if event_type == "thread.started":
            self.thread_id = str(event.get("thread_id") or "")[:128]
            return [f"· Codex thread {self.thread_id[:12]} ·"] if self.thread_id else []
        if event_type == "turn.completed":
            raw_usage = event.get("usage")
            usage = raw_usage if isinstance(raw_usage, dict) else {}
            self.usage = {
                key: int(value) for key, value in usage.items()
                if isinstance(value, int) and not isinstance(value, bool)
            }
            total = self.usage.get("input_tokens", 0) + self.usage.get("output_tokens", 0)
            return [f"· tokens {total} ·"] if total else []
        if event_type in ("turn.failed", "error"):
            self.error_count += 1
            raw_error = event.get("error")
            error_message = (raw_error.get("message")
                             if isinstance(raw_error, dict) else raw_error)
            message = event.get("message") or error_message or event
            self._record_tool_access_error(message, error_already_counted=True)
            return ["⚠ Codex " + self._brief(message)]
        if not event_type.startswith("item."):
            return []
        raw_item = event.get("item")
        if not isinstance(raw_item, dict):
            return self._non_json(text)
        item = raw_item
        item_type = str(item.get("type") or "")
        if item_type in {
            "agent_message", "reasoning", "command_execution", "file_change",
            "mcp_tool_call", "web_search", "plan_update",
        }:
            self._mark_model_work()
        if item_type == "file_change":
            self._guard_reported_file_change_paths(item)
        if event_type != "item.completed":
            if item_type == "command_execution" and event_type == "item.started":
                self.command_count += 1
                return ["⚙ shell " + self._brief(item.get("command") or "")]
            return []
        if item_type == "agent_message":
            value = str(item.get("text") or "")
            self.final_message = value
            # Luna's explicit blocked-tool contract is one of the two accepted
            # reparse signatures; the other is Codex's native router error.
            if "BLOCKED_TOOL_CAPABILITY" in value:
                self._record_tool_access_error(value, tool_context=True)
            return [value] if value else []
        if item_type == "reasoning":
            value = item.get("text") or item.get("summary") or ""
            return ["💭 " + self._brief(value, 1000)] if value else []
        if item_type == "command_execution":
            status = str(item.get("status") or "completed")
            raw_output = item.get("aggregated_output") or item.get("output") or ""
            if status.lower() in {"failed", "error", "rejected"}:
                self._record_tool_access_error(raw_output, tool_context=True)
            output = self._brief(raw_output, 300)
            return [f"⚙ shell {status}" + (f" · {output}" if output else "")]
        if item_type == "file_change":
            self.file_change_count += 1
            changes = item.get("changes") or item.get("files") or []
            return ["📦 修改 " + self._brief(changes, 300)]
        if item_type in ("mcp_tool_call", "web_search"):
            self.tool_count += 1
            name = item.get("server") or item.get("name") or item_type
            return [f"⚙ {name} {self._brief(item.get('arguments') or item.get('query') or '')}"]
        if item_type == "plan_update":
            return ["· 计划更新 ·"]
        return []


def translator_for_runner(runner: str):
    if runner == "opencode":
        return OpencodeJsonTranslator()
    if runner == "codex":
        return CodexJsonTranslator()
    raise ValueError(f"unsupported review runner: {runner}")
