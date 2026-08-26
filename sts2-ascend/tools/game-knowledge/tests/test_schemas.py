from __future__ import annotations

import json
from pathlib import Path
import unittest

from game_knowledge.validate import _control_flow_mapping_errors, _schema_errors


class SchemaTests(unittest.TestCase):
    def test_all_json_schemas_parse_and_have_unique_ids(self) -> None:
        schema_dir = Path(__file__).resolve().parents[1] / "schemas"
        ids: set[str] = set()
        files = sorted(schema_dir.glob("*.schema.json"))
        self.assertTrue(files)
        for path in files:
            value = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(value["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertNotIn(value["$id"], ids)
            ids.add(value["$id"])

    def test_mechanics_schema_is_enforced_recursively(self) -> None:
        schema_path = Path(__file__).resolve().parents[1] / "schemas" / "mechanics-record.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        record = {
            "schema": "sts2.game-knowledge-mechanics-record/v4",
            "category": "monsters",
            "type_name": "MegaCrit.Sts2.Core.Models.Monsters.TestMonster",
            "name": "TestMonster",
            "entry_id": "TEST_MONSTER",
            "provenance": {
                "source": "fixture", "assembly_sha256": "a" * 64,
                "extractor_schema_version": 4,
            },
            "data": {
                "type_name": "MegaCrit.Sts2.Core.Models.Monsters.TestMonster",
                "name": "TestMonster", "category": "monsters",
                "entry_id": "TEST_MONSTER", "type_kind": "Class",
                "is_abstract": False, "is_nested": False,
                "declaring_type_name": None, "base_types": [], "fields": [],
                "properties": [], "constructors": [],
                "methods": [{
                    "name": "Move", "return_type": "Task", "parameters": [],
                    "calls": [], "creates": [], "assignments": [],
                    "conditions": [], "switches": [], "returns": [],
                    "loops": [], "throws": [], "yields": [], "awaits": [], "mutations": [],
                    "control_flow": [{
                        "kind": "switch", "expression": "phase", "children": [{
                            "kind": "case", "expression": "1", "children": [{
                                "kind": "expression", "expression": "await Revive()", "children": [],
                            }],
                        }],
                    }],
                }],
            },
        }
        self.assertEqual(_schema_errors(record, schema, schema), [])
        record["data"]["methods"][0]["calls"] = "not-an-array"
        errors = _schema_errors(record, schema, schema)
        self.assertTrue(any("methods[0].calls" in error for error in errors), errors)
        record["data"]["methods"][0]["calls"] = []
        record["data"]["methods"][0]["control_flow"][0]["children"][0]["children"][0][
            "expression"
        ] = 7
        errors = _schema_errors(record, schema, schema)
        self.assertTrue(any("control_flow[0].children[0].children[0].expression" in error
                            for error in errors), errors)

    def test_control_flow_must_map_flattened_branch_indexes(self) -> None:
        fact = {
            "conditions": ["phase == 1"],
            "switches": ["Respawns"],
            "control_flow": [{
                "kind": "if", "expression": "phase == 2", "children": [{
                    "kind": "then", "expression": None, "children": [],
                }],
            }],
        }
        errors = _control_flow_mapping_errors(fact, "$.method")
        self.assertTrue(any("missing if mapping" in error for error in errors), errors)
        self.assertTrue(any("missing switch mapping" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
