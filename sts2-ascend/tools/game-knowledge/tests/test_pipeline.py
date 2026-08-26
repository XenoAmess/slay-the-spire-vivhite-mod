from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from game_knowledge.extract import extract_game_resources
from game_knowledge.mechanics import import_mechanics, model_entry_id
from game_knowledge.runtime import import_runtime_response_dir
from game_knowledge.validate import _check_localization, validate_snapshot
from tests.helpers import build_pck


LOCALIZATION_IDS = {
    "cards.json": "STRIKE.title",
    "relics.json": "STARTER_RELIC.title",
    "monsters.json": "TEST_MONSTER.name",
    "potions.json": "TEST_POTION.title",
    "events.json": "TEST_EVENT.title",
    "powers.json": "TEST_POWER.title",
    "characters.json": "IRONCLAD.name",
}


def _runtime_payloads() -> dict[str, list[dict]]:
    return {
        "cards": [
            {
                "id": "STRIKE",
                "name": "Strike",
                "description": "Deal 6 damage.",
                "type": "Attack",
                "rarity": "Basic",
                "target": "AnyEnemy",
                "cost": 1,
                "upgrade": {"description": "Deal 9 damage."},
            },
            {
                "id": "MOD_CARD",
                "name": "Mod Card",
                "description": "Not in the base PCK.",
                "type": "Skill",
                "rarity": "Common",
                "target": "Self",
                "cost": 0,
                "upgrade": None,
            },
        ],
        "relics": [
            {
                "id": "STARTER_RELIC",
                "name": "Starter Relic",
                "description": "A relic.",
                "rarity": "Starter",
                "pool": "ironclad",
            }
        ],
        "monsters": [
            {
                "id": "TEST_MONSTER",
                "name": "Test Monster",
                "type": "Normal",
                "min_hp": 10,
                "max_hp": 12,
                "moves": [],
            }
        ],
        "potions": [
            {
                "id": "TEST_POTION",
                "name": "Test Potion",
                "description": "A potion.",
                "rarity": "Common",
                "pool": "shared",
                "usage": "CombatOnly",
                "target_type": "Self",
            }
        ],
        "events": [
            {
                "id": "TEST_EVENT",
                "name": "Test Event",
                "description": "An event.",
                "type": "Event",
                "options": [],
            }
        ],
        "powers": [
            {
                "id": "TEST_POWER",
                "name": "Test Power",
                "description": "A power.",
                "type": "Buff",
                "stack_type": "Counter",
            },
            {
                "id": "INTERNAL_POWER",
                "name": "Internal Power",
                "description": "Native, intentionally has no localization.",
                "type": "Buff",
                "stack_type": "Counter",
            },
            {
                "id": "MOD_POWER",
                "name": "Mod Power",
                "description": "Not in the base PCK.",
                "type": "Buff",
                "stack_type": "Counter",
            },
        ],
        "characters": [
            {
                "id": "IRONCLAD",
                "name": "Ironclad",
                "starting_hp": 80,
                "starting_gold": 99,
                "max_energy": 3,
                "starting_deck": ["STRIKE"],
                "starting_relics": ["STARTER_RELIC"],
                "starting_potions": ["TEST_POTION"],
            },
            {
                "id": "MOD_CHARACTER",
                "name": "Mod Character",
                "starting_hp": 1,
                "starting_gold": 0,
                "max_energy": 1,
                "starting_deck": ["MOD_CARD"],
                "starting_relics": [],
                "starting_potions": [],
            },
        ],
    }


class ExtractionPipelineTests(unittest.TestCase):
    def test_model_entry_id_matches_game_acronym_behavior(self) -> None:
        self.assertEqual(model_entry_id("Strike"), "STRIKE")
        self.assertEqual(model_entry_id("ABCMonster"), "A_B_C_MONSTER")
        self.assertEqual(model_entry_id("CultistA"), "CULTIST_A")

    def test_extract_import_filter_and_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            game = root / "game"
            data_dir = game / "data_sts2_windows_x86_64"
            data_dir.mkdir(parents=True)
            (game / "release_info.json").write_text(
                json.dumps(
                    {
                        "commit": "abc123",
                        "version": "v0.111.0",
                        "date": "2026-08-13T17:39:18-07:00",
                        "branch": "v0.111.0",
                        "main_assembly_hash": 123,
                    }
                ),
                encoding="utf-8",
            )
            (data_dir / "sts2.dll").write_bytes(b"synthetic assembly")
            pck_files: dict[str, bytes] = {}
            for filename, key in LOCALIZATION_IDS.items():
                for locale in ("eng", "zhs"):
                    pck_files[f"localization/{locale}/{filename}"] = json.dumps(
                        {key: f"{locale}:{key}"}, ensure_ascii=False
                    ).encode("utf-8")
            pck_files["src/Core/Models/Cards/Strike.cs"] = b"\n"
            pck_files["src/Core/Models/Powers/TestPower.cs"] = b"\n"
            pck_files["src/Core/Models/Powers/InternalPower.cs"] = b"\n"
            build_pck(game / "SlayTheSpire2.pck", pck_files)

            output_dir, manifest = extract_game_resources(
                game_dir=game,
                output_root=root / "knowledge" / "game",
            )
            self.assertEqual(output_dir.name, "v0.111.0")
            self.assertEqual(manifest["sources"]["pck"]["header"]["entry_count"], len(pck_files))
            self.assertTrue((output_dir / "catalog" / "pck-index.jsonl").is_file())
            self.assertTrue((output_dir / "catalog" / "localization-bilingual.jsonl").is_file())
            self.assertTrue((output_dir / "localization" / "zhs" / "cards.json").is_file())
            self.assertEqual(manifest["localization"]["bilingual_status_counts"], {"bilingual": 7})

            responses = root / "responses"
            responses.mkdir()
            for collection, items in _runtime_payloads().items():
                (responses / f"{collection}.response.json").write_text(
                    json.dumps({"ok": True, "data": items}), encoding="utf-8"
                )
            runtime = import_runtime_response_dir(output_dir=output_dir, response_dir=responses)
            self.assertEqual(runtime["base_game_filter"], "available")
            self.assertEqual(runtime["collections"]["cards"]["raw_count"], 2)
            self.assertEqual(runtime["collections"]["cards"]["record_count"], 1)
            self.assertEqual(runtime["collections"]["cards"]["filtered_not_in_pck_ids"], ["MOD_CARD"])
            self.assertEqual(runtime["collections"]["characters"]["record_count"], 1)
            self.assertEqual(runtime["collections"]["powers"]["record_count"], 2)
            self.assertEqual(
                runtime["collections"]["powers"]["filtered_not_in_pck_ids"], ["MOD_POWER"]
            )

            mechanics_input = root / "mechanics-input"
            mechanics_input.mkdir()
            mechanics_record = {
                "type_name": "MegaCrit.Sts2.Core.Models.Cards.Strike",
                "name": "Strike",
                "category": "cards",
                "entry_id": "STRIKE",
                "type_kind": "Class",
                "is_abstract": False,
                "is_nested": False,
                "declaring_type_name": None,
                "base_types": ["MegaCrit.Sts2.Core.Models.CardModel"],
                "fields": [],
                "properties": [],
                "constructors": [],
                "methods": [],
            }
            nested_record = {
                "type_name": "MegaCrit.Sts2.Core.Models.Cards.Strike+Mode",
                "name": "Mode",
                "category": "cards",
                "entry_id": None,
                "type_kind": "Enum",
                "is_abstract": False,
                "is_nested": True,
                "declaring_type_name": "MegaCrit.Sts2.Core.Models.Cards.Strike",
                "base_types": [],
                "fields": [{"name": "Normal", "type": "enum", "value": "0", "is_const": True}],
                "properties": [],
                "constructors": [],
                "methods": [],
            }
            monster_record = {
                "type_name": "MegaCrit.Sts2.Core.Models.Monsters.TestMonster",
                "name": "TestMonster",
                "category": "monsters",
                "entry_id": "TEST_MONSTER",
                "type_kind": "Class",
                "is_abstract": False,
                "is_nested": False,
                "declaring_type_name": None,
                "base_types": ["MegaCrit.Sts2.Core.Models.MonsterModel"],
                "fields": [],
                "properties": [],
                "constructors": [],
                "methods": [{
                    "name": "GenerateMoveStateMachine",
                    "return_type": "MonsterMoveStateMachine",
                    "parameters": [],
                    "calls": [],
                    "creates": ["new MoveState (\"ATTACK\", AttackMove)"],
                    "assignments": [],
                    "conditions": [],
                    "switches": [],
                    "returns": ["new MonsterMoveStateMachine (states, attack)"],
                    "loops": [], "throws": [], "yields": [], "awaits": [], "mutations": [],
                    "control_flow": [{
                        "kind": "return",
                        "expression": "new MonsterMoveStateMachine (states, attack)",
                        "children": [],
                    }],
                }],
            }
            body = (
                json.dumps(mechanics_record, separators=(",", ":"))
                + "\n"
                + json.dumps(nested_record, separators=(",", ":"))
                + "\n"
            ).encode()
            (mechanics_input / "cards.jsonl").write_bytes(body)
            monster_body = (json.dumps(monster_record, separators=(",", ":")) + "\n").encode()
            (mechanics_input / "monsters.jsonl").write_bytes(monster_body)
            power_records = []
            for name, entry_id in (("TestPower", "TEST_POWER"),
                                   ("InternalPower", "INTERNAL_POWER")):
                power_records.append({
                    "type_name": f"MegaCrit.Sts2.Core.Models.Powers.{name}",
                    "name": name, "category": "powers", "entry_id": entry_id,
                    "type_kind": "Class", "is_abstract": False, "is_nested": False,
                    "declaring_type_name": None,
                    "base_types": ["MegaCrit.Sts2.Core.Models.PowerModel"],
                    "fields": [], "properties": [], "constructors": [], "methods": [],
                })
            powers_body = ("\n".join(
                json.dumps(record, separators=(",", ":")) for record in power_records
            ) + "\n").encode()
            (mechanics_input / "powers.jsonl").write_bytes(powers_body)
            assembly_hash = manifest["sources"]["assembly"]["sha256"]
            (mechanics_input / "mechanics-manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 4,
                        "source": {"assembly": "sts2.dll", "assembly_sha256": assembly_hash},
                        "generated_at_utc": "2026-08-26T00:00:00Z",
                        "extraction": "synthetic test facts",
                        "counts": {"cards": 2, "monsters": 1, "powers": 2},
                        "output_sha256": {
                            "cards.jsonl": hashlib.sha256(body).hexdigest(),
                            "monsters.jsonl": hashlib.sha256(monster_body).hexdigest(),
                            "powers.jsonl": hashlib.sha256(powers_body).hexdigest(),
                        },
                        "failures": [],
                    }
                ),
                encoding="utf-8",
            )
            mechanics = import_mechanics(output_dir=output_dir, mechanics_dir=mechanics_input)
            self.assertEqual(mechanics["record_count"], 5)
            self.assertEqual(mechanics["joins"]["cards"]["status"], "complete")
            self.assertEqual(mechanics["joins"]["cards"]["matched_count"], 1)

            report = validate_snapshot(output_dir=output_dir, game_dir=game)
            self.assertNotEqual(report["overall"], "fail", report)
            self.assertEqual(report["counts"]["fail"], 0)

            bilingual_path = output_dir / "catalog" / "localization-bilingual.jsonl"
            bilingual_rows = [json.loads(line) for line in bilingual_path.read_text(
                encoding="utf-8").splitlines() if line]
            bilingual_rows[0]["zhs_or_eng"] = "tampered-value"
            bilingual_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in bilingual_rows) + "\n",
                encoding="utf-8",
            )
            localization_checks = _check_localization(output_dir, manifest)
            self.assertTrue(any(
                check.name == "localization.bilingual_catalog" and check.status == "fail"
                for check in localization_checks
            ))


if __name__ == "__main__":
    unittest.main()
