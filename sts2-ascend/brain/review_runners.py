"""Provider-specific adapters for the sts2-ascend review worker.

The host owns evidence, isolation, validation, Git and retry transactions.  A
runner adapter is deliberately limited to selecting a configured backend,
building its command line and translating its event stream.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import shutil
import time
from typing import Iterable


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
    return shutil.which(str(configured))


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
        command = [binary, "exec", "--model", plan.model]
        if plan.reasoning_effort:
            command += ["-c", f'model_reasoning_effort="{plan.reasoning_effort}"']
        if plan.approve_for_me:
            command.append("--approve-for-me")
        command += ["--sandbox", plan.sandbox]
        command += ["--json", "--ephemeral", "--color", "never", "-C", root, prompt]
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

    def metrics(self) -> dict:
        return {
            "event_count": self.event_count,
            "error_count": self.error_count,
            "non_json_lines": self.non_json_lines,
            "model_work_started": self.model_work_started,
            "first_event_after_sec": self.first_event_after_sec,
            "first_model_work_after_sec": self.first_model_work_after_sec,
            "usage": dict(self.usage),
        }


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
            return [text]
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            self.non_json_lines += 1
            return [text]
        if not isinstance(event, dict):
            self.non_json_lines += 1
            return [text]
        self._event()
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
        return []


class CodexJsonTranslator(_TranslatorBase):
    """Translate ``codex exec --json`` JSONL and retain evaluation metrics."""

    def __init__(self) -> None:
        super().__init__()
        self.thread_id = ""
        self.command_count = 0
        self.file_change_count = 0
        self.tool_count = 0
        self.blocked_tool_count = 0
        self.tool_access_error = ""
        self.final_message = ""

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
        contextual = tool_context or any(marker in lowered for marker in (
            "codex_core::tools", "tools::router", "createprocess", "exec_command",
            "apply_patch", "apply patch", "patch verifier",
        ))
        if "blocked by policy" not in lowered and not (denied and contextual):
            return False
        self.blocked_tool_count += 1
        self.tool_access_error = summary
        if not error_already_counted:
            self.error_count += 1
        return True

    def _non_json(self, text: str) -> list[str]:
        self.non_json_lines += 1
        self._record_tool_access_error(text)
        return [text]

    def feed(self, raw: str) -> list[str]:
        text = raw.strip()
        if not text:
            return []
        if not text.startswith("{"):
            return self._non_json(text)
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            return self._non_json(text)
        if not isinstance(event, dict):
            return self._non_json(text)
        self._event()
        event_type = str(event.get("type") or "")
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
        if event_type != "item.completed":
            if item_type == "command_execution" and event_type == "item.started":
                self.command_count += 1
                return ["⚙ shell " + self._brief(item.get("command") or "")]
            return []
        if item_type == "agent_message":
            value = str(item.get("text") or "")
            self.final_message = value
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
