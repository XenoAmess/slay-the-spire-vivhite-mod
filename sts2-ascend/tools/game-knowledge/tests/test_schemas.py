from __future__ import annotations

import json
from pathlib import Path
import unittest


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


if __name__ == "__main__":
    unittest.main()

