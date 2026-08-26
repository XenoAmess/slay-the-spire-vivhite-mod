"""Persistence safety regressions for the online knowledge store."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import tempfile
import unittest


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

from knowledge import _save_json  # noqa: E402


class AtomicKnowledgeSaveTests(unittest.TestCase):
    def test_parallel_replacements_never_publish_torn_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sts2-knowledge-save-") as root:
            path = Path(root) / "stats.json"

            def write(writer: int) -> None:
                for iteration in range(12):
                    _save_json(path, {
                        "writer": writer,
                        "iteration": iteration,
                        "payload": [f"{writer}:{iteration}"] * 400,
                    })

            with ThreadPoolExecutor(max_workers=6) as pool:
                list(pool.map(write, range(6)))

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertIn(saved["writer"], range(6))
            self.assertEqual(len(saved["payload"]), 400)
            self.assertFalse(list(Path(root).glob(".stats.json.*.tmp")))


if __name__ == "__main__":
    unittest.main()
