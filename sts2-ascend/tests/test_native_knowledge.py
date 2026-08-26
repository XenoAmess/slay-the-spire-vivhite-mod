"""Regression tests for the read-only native game knowledge query layer."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from native_knowledge import (  # noqa: E402
    CORE_CATEGORIES,
    MANIFEST_SCHEMA,
    MECHANICS_SCHEMA,
    RUNTIME_SCHEMA,
    VALIDATION_SCHEMA,
    VALIDATOR_VERSION,
    NativeGameKnowledge,
    _artifact_set_sha256,
)
from policy import Policy  # noqa: E402


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
        manifest["artifacts"] = [
            {"path": f"runtime/{category}.jsonl"} for category in CORE_CATEGORIES
        ] + [
            {"path": f"mechanics/{category}.jsonl"} for category in CORE_CATEGORIES
        ]
        manifest_path = self.snapshot / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        (self.snapshot / "validation.json").write_text(json.dumps({
            "schema": VALIDATION_SCHEMA,
            "validated_snapshot": {
                "binding_version": 1,
                "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "artifact_set_sha256": _artifact_set_sha256(self.snapshot, manifest),
                "validator": VALIDATOR_VERSION,
            },
            "counts": {"pass": 1, "warning": 0, "fail": 0},
        }), encoding="utf-8")

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

        policy = Policy(SimpleNamespace(game_knowledge=index))
        policy_card = policy._enrich_cards([live])[0]
        self.assertEqual(policy_card["card_type"], "Attack")
        self.assertEqual(policy_card["resolved_rules_text"], "造成 7 点伤害。")

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

    def test_stale_validation_rejects_manifest_change(self) -> None:
        path = self.snapshot / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["game"]["commit"] = "tampered"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        index = NativeGameKnowledge.from_knowledge_root(self.knowledge)
        self.assertFalse(index.available)
        self.assertIn("stale for manifest", index.error)

    def test_stale_validation_rejects_artifact_change(self) -> None:
        path = self.snapshot / "runtime" / "cards.jsonl"
        path.write_text(path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")
        index = NativeGameKnowledge.from_knowledge_root(self.knowledge)
        self.assertFalse(index.available)
        self.assertIn("stale for artifacts", index.error)

    def test_obsolete_validator_binding_is_rejected(self) -> None:
        path = self.snapshot / "validation.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        report["validated_snapshot"]["validator"] = "game_knowledge.validate/v2"
        path.write_text(json.dumps(report), encoding="utf-8")
        index = NativeGameKnowledge.from_knowledge_root(self.knowledge)
        self.assertFalse(index.available)
        self.assertIn("missing a trusted binding", index.error)

    def test_monster_digest_prioritizes_moves_and_preserves_behavior(self) -> None:
        mechanics = {
            "properties": [],
            "fields": [],
            "constructors": [],
            "methods": [
                {"name": "DamageCalculation", "calls": ["DamageCmd.Calculate()"]},
                {"name": "EbbMove", "calls": [
                    "DamageCmd.Attack(target, 10)",
                    "DamageCmd.Attack(target, 10).WithHitEffect(HitEffect.Heavy)",
                    "DamageCmd.Attack(target, 10).WithHitEffect(HitEffect.Heavy).WithHitVfx(vfx)",
                    "CreatureCmd.GainBlock(self, 33)",
                ]},
                {"name": "GenerateMoveStateMachine", "returns": ["new MonsterMoveStateMachine(...)"],
                 "yields": ["yield return IntroMove"]},
                {"name": "IncreasingIntensityMove", "loops": ["foreach: target.AllCards"],
                 "awaits": ["PowerCmd.Apply(...)"],
                 "mutations": ["WitherUpgradeCount++", "AdditionalStrength++"]},
                {"name": "TidalMove", "calls": ["DamageCmd.Attack(target, 20)"]},
            ],
        }

        digest = NativeGameKnowledge._mechanics_highlights("monsters", mechanics)
        methods = {method["name"]: method for method in digest["methods"]}
        self.assertEqual(
            list(methods),
            ["GenerateMoveStateMachine", "IncreasingIntensityMove", "EbbMove"],
        )
        self.assertEqual(methods["IncreasingIntensityMove"]["mutations"],
                         ["WitherUpgradeCount++", "AdditionalStrength++"])
        self.assertIn("foreach: target.AllCards", methods["IncreasingIntensityMove"]["loops"])
        self.assertIn("PowerCmd.Apply(...)", methods["IncreasingIntensityMove"]["awaits"])
        self.assertEqual(len(methods["EbbMove"]["calls"]), 2)
        self.assertTrue(any("GainBlock" in call for call in methods["EbbMove"]["calls"]))

    def test_monster_digest_surfaces_bounded_branch_effect_mapping(self) -> None:
        switch = {
            "kind": "switch", "expression": "Respawns", "children": [
                {"kind": "case", "expression": "1", "children": [
                    {"kind": "expression", "expression": "await Revive(SecondFormHp)",
                     "children": []},
                    {"kind": "expression", "expression": "await PowerCmd.Apply<PainfulStabsPower>()",
                     "children": []},
                    {"kind": "break", "expression": None, "children": []},
                ]},
                {"kind": "case", "expression": "2", "children": [
                    {"kind": "expression", "expression": "await Revive(ThirdFormHp)",
                     "children": []},
                    {"kind": "expression", "expression": "await PowerCmd.Apply<NemesisPower>()",
                     "children": []},
                    {"kind": "break", "expression": None, "children": []},
                ]},
            ],
        }
        mechanics = {
            "properties": [], "fields": [], "constructors": [],
            "methods": [
                {"name": "BiteMove", "calls": ["DamageCmd.Attack(20)"], "control_flow": []},
                {"name": "GenerateMoveStateMachine", "returns": ["new MonsterMoveStateMachine()"],
                 "control_flow": []},
                {"name": "MultiClawMove", "mutations": ["ExtraMultiClawCount++"],
                 "control_flow": []},
                {"name": "RespawnMove", "switches": ["Respawns"],
                 "control_flow": [
                     {"kind": "expression", "expression": "Respawns++", "children": []},
                     switch,
                 ]},
            ],
        }

        digest = NativeGameKnowledge._mechanics_highlights("monsters", mechanics)
        methods = {method["name"]: method for method in digest["methods"]}
        self.assertEqual(
            list(methods),
            ["GenerateMoveStateMachine", "MultiClawMove", "RespawnMove"],
        )
        flow_text = json.dumps(methods["RespawnMove"]["control_flow"], ensure_ascii=False)
        self.assertIn('"expression": "1"', flow_text)
        self.assertIn("SecondFormHp", flow_text)
        self.assertIn('"expression": "2"', flow_text)
        self.assertIn("NemesisPower", flow_text)

        def count_nodes(nodes):
            return sum(1 + count_nodes(node.get("children", [])) for node in nodes)

        self.assertLessEqual(count_nodes(methods["RespawnMove"]["control_flow"]), 32)


if __name__ == "__main__":
    unittest.main()
