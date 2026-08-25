from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from game_knowledge.pck import PckError, PckReader
from tests.helpers import build_pck


class PckReaderTests(unittest.TestCase):
    def test_reads_inventory_payload_and_directory_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sample.pck"
            files = {
                "localization/eng/cards.json": b'{"STRIKE.title":"Strike"}',
                "src/Core/Models/Cards/Strike.cs": b"\n",
            }
            build_pck(path, files)

            with PckReader(path) as reader:
                self.assertEqual(reader.header.engine_version, "4.5.1")
                self.assertEqual(len(reader.entries), 2)
                self.assertEqual(reader.read_bytes("res://localization/eng/cards.json"), files["localization/eng/cards.json"])
                self.assertEqual(reader.extension_counts(), {".json": 1, ".cs": 1})
                self.assertEqual(len(reader.directory_sha256()), 64)

    def test_supports_absolute_entry_offsets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "absolute.pck"
            build_pck(path, {"data.json": b"{}"}, relative_offsets=False)
            with PckReader(path) as reader:
                self.assertEqual(reader.read_bytes("data.json"), b"{}")

    def test_rejects_payload_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "corrupt.pck"
            build_pck(path, {"data.json": b"{}"}, corrupt_path="data.json")
            with PckReader(path) as reader:
                with self.assertRaisesRegex(PckError, "checksum mismatch"):
                    reader.read_bytes("data.json")

    def test_rejects_unsafe_directory_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "unsafe.pck"
            build_pck(path, {"../escape.json": b"{}"})
            with self.assertRaisesRegex(PckError, "unsafe path"):
                with PckReader(path):
                    pass


if __name__ == "__main__":
    unittest.main()
