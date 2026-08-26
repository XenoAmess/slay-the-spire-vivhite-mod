"""Focused coverage for policy traces and non-blocking live telemetry."""
from __future__ import annotations

import ast
from contextlib import contextmanager
import json
from pathlib import Path
import random
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from decision_trace import DecisionTraceBuilder, ensure_decision_trace  # noqa: E402
from live_dashboard import LiveDashboardPublisher, MAX_BYTES, SCHEMA  # noqa: E402
from policy import Decision, Policy  # noqa: E402
import agent as agent_module  # noqa: E402


def reward_state() -> dict:
    return {
        "screen": "REWARD",
        "run_id": "run-a",
        "available_actions": ["choose_reward_card", "skip_reward_cards"],
        "run": {"floor": 17, "current_hp": 41, "max_hp": 80,
                "gold": 99, "ascension": 3},
        "reward": {
            "pending_card_choice": True,
            "card_options": [
                {"index": 2, "name": "Alpha", "card_id": "A"},
                {"index": 5, "name": "Beta", "card_id": "B"},
            ],
        },
    }


class DecisionTraceTests(unittest.TestCase):
    def test_trace_preserves_decision_and_rng_state(self) -> None:
        rng = random.Random(9001)
        before_rng = rng.getstate()
        decision = Decision("choose_reward_card", {"option_index": 5},
                            "奖励选牌：Beta（价值 7.0）；候选：Alpha=2.5 / Beta=7.0",
                            tags=[("card_pick", "B")], wait=0.8)
        before = (decision.action, dict(decision.params), decision.reason,
                  list(decision.tags), decision.wait)

        returned = ensure_decision_trace(reward_state(), decision)

        self.assertIs(returned, decision)
        self.assertEqual(before, (decision.action, decision.params, decision.reason,
                                  decision.tags, decision.wait))
        self.assertEqual(before_rng, rng.getstate())
        self.assertEqual(decision.trace["selected"]["label"], "Beta")
        scores = {row["label"]: row["score"]
                  for row in decision.trace["candidates"]}
        self.assertEqual(scores["Beta"], 7.0)
        self.assertEqual(scores["Alpha"], 2.5)

    def test_native_builder_uses_only_supplied_scores_and_preserves_rng(self) -> None:
        state = reward_state()
        rng = random.Random(73)
        rng_before = rng.getstate()
        decision = Decision("choose_reward_card", {"option_index": 5},
                            "fallback-only-noise=999")
        original = (decision.action, dict(decision.params), decision.reason,
                    list(decision.tags), decision.wait)
        builder = DecisionTraceBuilder(state)
        builder.gate("GATE 动态拾取门槛", "pass", "7.0 >= 4.0")
        builder.candidate("Alpha", 2.5, index=2, action="choose_reward_card",
                          why="already computed")
        builder.candidate("Beta", 7.0, index=5, action="choose_reward_card",
                          why="already computed")

        trace = builder.finish(decision)

        self.assertEqual(rng_before, rng.getstate())
        self.assertEqual(original, (decision.action, decision.params, decision.reason,
                                    decision.tags, decision.wait))
        self.assertEqual(trace["selected"]["label"], "Beta")
        self.assertEqual(trace["selected"]["score"], 7.0)
        self.assertEqual([row["label"] for row in trace["candidates"]],
                         ["Beta", "Alpha"])
        self.assertNotIn("fallback-only-noise", {row["label"]
                                                  for row in trace["candidates"]})
        self.assertTrue(any(gate["label"] == "GATE 动态拾取门槛"
                            for gate in trace["gates"]))

    def test_telemetry_modules_have_no_llm_network_or_process_dependency(self) -> None:
        allowed_imports = {
            "decision_trace.py": {"__future__", "re", "typing"},
            "live_dashboard.py": {
                "__future__", "copy", "json", "os", "queue", "threading",
                "time", "pathlib", "typing", "lifecycle",
            },
        }
        banned_roots = {
            "llm_review", "opencode", "minimax", "openrouter", "openai",
            "requests", "urllib", "http", "socket", "subprocess", "aiohttp",
            "websocket", "anthropic",
        }
        for filename, allowed in allowed_imports.items():
            with self.subTest(filename=filename):
                tree = ast.parse((BRAIN / filename).read_text(encoding="utf-8"),
                                 filename=filename)
                imported = set()
                called_roots = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name.split(".", 1)[0]
                                        for alias in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imported.add((node.module or "").split(".", 1)[0])
                    elif isinstance(node, ast.Call):
                        func = node.func
                        while isinstance(func, ast.Attribute):
                            func = func.value
                        if isinstance(func, ast.Name):
                            called_roots.add(func.id.casefold())
                self.assertEqual(imported - allowed, set())
                self.assertFalse({name.casefold() for name in imported} & banned_roots)
                self.assertFalse(called_roots & banned_roots)

    def test_reward_handler_exports_native_scores_without_rescoring(self) -> None:
        know = SimpleNamespace(game_knowledge=None, policy={})
        policy = Policy(know, random.Random(11))
        score_calls = []
        values = {"A": 2.5, "B": 7.0}

        def score(card, _deck, **_kwargs):
            score_calls.append(card["card_id"])
            return values[card["card_id"]]

        policy.eval_reward_card = score
        policy._pick_threshold = lambda *_args, **_kwargs: 4.0
        policy._thin_deck_must_pick = lambda *_args, **_kwargs: False
        policy._record_card_offer = lambda *_args, **_kwargs: None
        policy._reward_card_choice = lambda scored, *_args, **_kwargs: (
            scored[0][0], scored[0][1], "", None)
        builder = DecisionTraceBuilder(reward_state())
        policy._active_trace_builder = builder
        rng_before = policy.rng.getstate()

        decision = policy._reward(reward_state(), SimpleNamespace())
        trace = builder.finish(decision)

        self.assertEqual(score_calls, ["A", "B"])
        self.assertEqual(rng_before, policy.rng.getstate())
        self.assertEqual(decision.action, "choose_reward_card")
        self.assertEqual(trace["selected"]["label"], "Beta")
        self.assertEqual(trace["selected"]["score"], 7.0)
        self.assertTrue(any(gate["label"] == "GATE 动态拾取门槛"
                            for gate in trace["gates"]))

    def test_every_screen_gets_truthful_generic_trace(self) -> None:
        for screen in ("MAIN_MENU", "COMBAT", "MAP", "REWARD", "CARD_SELECTION",
                       "SHOP", "REST", "CHEST", "EVENT", "CRYSTAL_SPHERE",
                       "MODAL", "GAME_OVER", "UNLOCK", "UNKNOWN"):
            with self.subTest(screen=screen):
                state = {"screen": screen, "run": {"floor": 2},
                         "available_actions": []}
                decision = Decision(None, {}, "等待")
                ensure_decision_trace(state, decision)
                self.assertEqual(decision.trace["observation"]["title"], f"{screen} · F2")
                self.assertEqual(decision.trace["selected"]["action"], None)
                self.assertTrue(decision.trace["gates"])


class LiveDashboardPublisherTests(unittest.TestCase):
    def test_atomic_snapshot_lifecycle_history_and_bounds(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-dashboard-") as root:
            publisher = LiveDashboardPublisher(Path(root), "session-test")
            state = reward_state()
            decision = ensure_decision_trace(
                state, Decision("choose_reward_card", {"option_index": 5},
                                "候选：Alpha=2.5 / Beta=7.0"))
            publisher.observe(state, run_number=42)
            decision_id = publisher.propose(state, decision, run_number=42)
            publisher.outcome("pending", "服务端排队", decision_id=decision_id)
            publisher.outcome("applied", "状态确认", decision_id=decision_id)
            publisher.close(timeout=2.0)

            raw = publisher.path.read_bytes()
            self.assertLessEqual(len(raw), MAX_BYTES)
            payload = json.loads(raw.decode("utf-8"))
            self.assertEqual(payload["schema"], SCHEMA)
            self.assertEqual(payload["session_id"], "session-test")
            self.assertEqual(payload["run"]["run_number"], 42)
            self.assertEqual(payload["decision"]["status"], "applied")
            self.assertEqual(payload["decision"]["outcome"]["message"], "状态确认")
            self.assertEqual(payload["history"][-1]["decision_id"], decision_id)
            self.assertEqual(payload["history"][-1]["status"], "applied")
            self.assertFalse(list(Path(root).glob("*.tmp")))

    def test_identical_wait_reuses_id_and_increments_repeat(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-dashboard-wait-") as root:
            publisher = LiveDashboardPublisher(Path(root), "wait-test")
            state = {"screen": "COMBAT", "run_id": "same",
                     "run": {"floor": 9}, "turn": 3}
            first = ensure_decision_trace(state, Decision(None, {}, "动画中，等待"))
            first_id = publisher.propose(state, first)
            second = ensure_decision_trace(state, Decision(None, {}, "动画中，等待"))
            second_id = publisher.propose(state, second)
            publisher.close(timeout=2.0)

            payload = json.loads(publisher.path.read_text(encoding="utf-8"))
            self.assertEqual(first_id, second_id)
            self.assertEqual(payload["decision"]["repeat_count"], 2)
            self.assertEqual(payload["decision"]["status"], "waiting")

    def test_publish_is_nonblocking_when_queue_is_saturated(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ascend-dashboard-queue-") as root:
            publisher = LiveDashboardPublisher(
                Path(root), "queue-test", queue_size=2, autostart=False)
            started = time.perf_counter()
            for pos in range(1000):
                publisher.connection("connected", str(pos))
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.5)
            self.assertLessEqual(publisher._queue.qsize(), 2)


class DashboardStartupTests(unittest.TestCase):
    def test_busy_git_lock_cannot_delay_gameplay_startup(self) -> None:
        calls = []

        @contextmanager
        def busy_lock(*, timeout):
            calls.append(timeout)
            raise TimeoutError("fixture busy lock")
            yield  # pragma: no cover - keeps this a context manager

        fake_autogit = SimpleNamespace(
            repository_lock=busy_lock,
            head=lambda: self.fail("head must not run without the lock"),
        )
        instance = object.__new__(agent_module.Agent)
        instance._boot_head = "old"
        with mock.patch.object(agent_module, "autogit", fake_autogit), \
                mock.patch.object(agent_module, "log"):
            instance._capture_boot_head()

        self.assertEqual(calls, [5.0])
        self.assertEqual(instance._boot_head, "")


if __name__ == "__main__":
    unittest.main()
