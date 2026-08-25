"""Regression tests for the read-only native game knowledge query layer."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from native_knowledge import (  # noqa: E402
    CORE_CATEGORIES,
    MANIFEST_SCHEMA,
    MECHANICS_SCHEMA,
    RUNTIME_SCHEMA,
    NativeGameKnowledge,
)


class NativeKnowledgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-native-knowledge-")
        self.knowledge = Path(self.temp.name) / "knowledge"
        self.snapshot = self.knowledge / "game" / "v0.111.0"
        (self.snapshot / "runtime").mkdir(parents=True)
        (self.snapshot / "mechanics").mkdir()
        (self.snapshot / "catalog").mkdir()
        (self.snapshot / "localization" / "eng").mkdir(parents=True)
        (self.snapshot / "localization" / "zhs").mkdir(parents=True)
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "game": {"version": "v0.111.0", "commit": "fixture"},
            "sources": {"assembly": {"sha256": "abc"}},
            "runtime": {"collections": {
                category: {"status": "captured", "record_count": 0}
                for category in CORE_CATEGORIES
            }},
            "mechanics": {"record_count": 1, "extractor_failures": []},
        }
        (self.snapshot / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        (self.snapshot / "validation.json").write_text(
            json.dumps({"counts": {"pass": 1, "warning": 0, "fail": 0}}),
            encoding="utf-8")
        for category in CORE_CATEGORIES:
            (self.snapshot / "runtime" / f"{category}.jsonl").write_text("", encoding="utf-8")
            (self.snapshot / "mechanics" / f"{category}.jsonl").write_text("", encoding="utf-8")

        runtime = {
            "schema": RUNTIME_SCHEMA, "category": "cards", "id": "TEST_CARD",
            "data": {"id": "TEST_CARD", "name": "测试牌", "description": "造成 7 点伤害。",
                     "type": "Attack", "rarity": "Common", "cost": 1,
                     "vars": [{"name": "Damage", "current_value": 7}]},
        }
        mechanics = {
            "schema": MECHANICS_SCHEMA, "category": "cards", "entry_id": "TEST_CARD",
            "type_name": "MegaCrit.Sts2.Core.Models.Cards.TestCard",
            "data": {"entry_id": "TEST_CARD", "properties": [
                {"name": "Damage", "expressions": ["7"]}], "fields": [], "methods": [
                {"name": "OnPlay", "calls": ["DamageCmd.Attack (Damage)"]}]},
        }
        (self.snapshot / "runtime" / "cards.jsonl").write_text(
            json.dumps(runtime, ensure_ascii=False) + "\n", encoding="utf-8")
        (self.snapshot / "mechanics" / "cards.jsonl").write_text(
            json.dumps(mechanics, ensure_ascii=False) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_lookup_enrichment_and_bounded_review_digest(self) -> None:
        index = NativeGameKnowledge.from_knowledge_root(self.knowledge)
        self.assertTrue(index.available, index.error)
        self.assertEqual(index.version, "v0.111.0")
        fact = index.lookup("cards", "test_card+")
        self.assertEqual(fact["runtime"]["type"], "Attack")
        self.assertEqual(fact["mechanics"]["properties"][0]["name"], "Damage")

        live = {"card_id": "TEST_CARD", "playable": True, "energy_cost": 1}
        enriched = index.enrich_card(live)
        self.assertIsNot(enriched, live)
        self.assertEqual(enriched["card_type"], "Attack")
        self.assertEqual(enriched["resolved_rules_text"], "造成 7 点伤害。")
        self.assertEqual(enriched["dynamic_values"][0]["current_value"], 7)

        digest = index.review_digest(
            {"cards": {"TEST_CARD": {"picked": 5, "plays": 0, "bias": -2}},
             "enemies": {}, "events": {}, "relics": {}},
            ["本局反复跳过测试牌"],
        )
        self.assertEqual(digest["snapshot"]["version"], "v0.111.0")
        self.assertEqual(digest["entities"]["cards"][0]["id"], "TEST_CARD")
        self.assertIn("DamageCmd", json.dumps(digest, ensure_ascii=False))
        self.assertIn("<category>.jsonl", digest["corpus_paths"]["mechanics"])

    def test_validation_failure_is_explicit_and_non_throwing(self) -> None:
        (self.snapshot / "validation.json").write_text(
            json.dumps({"counts": {"fail": 1}}), encoding="utf-8")
        index = NativeGameKnowledge.from_knowledge_root(self.knowledge)
        self.assertFalse(index.available)
        self.assertIn("validation has failures", index.error)


if __name__ == "__main__":
    unittest.main()
