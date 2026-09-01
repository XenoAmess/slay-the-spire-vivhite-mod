"""Contracts for the tracked Steam Workshop material pipeline.

These tests are intentionally local and deterministic: they do not contact
Steam, start the game, or invoke the uploader.  The publish script is the only
place allowed to turn these artifacts into a Workshop update.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ITEM = ROOT / "workshop" / "workshop-item.json"
DESCRIPTION = ROOT / "workshop" / "description.bbcode"
PREVIEW = ROOT / "workshop" / "preview.jpg"
PREVIEW_SCRIPT = ROOT / "tools" / "workshop" / "New-VivhiteWorkshopPreview.ps1"
PUBLISH_SCRIPT = ROOT / "tools" / "workshop" / "Publish-VivhiteWorkshop.ps1"


class WorkshopMaterialContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.item = json.loads(ITEM.read_text(encoding="utf-8"))
        cls.description = DESCRIPTION.read_text(encoding="utf-8")
        cls.preview_bytes = PREVIEW.read_bytes()
        cls.preview_hash = hashlib.sha256(cls.preview_bytes).hexdigest().upper()

    def test_metadata_and_preview_are_same_release(self) -> None:
        self.assertEqual(self.item["app_id"], 2868840)
        self.assertEqual(self.item["version"], "0.2.1")
        preview = self.item["preview"]
        self.assertEqual(preview["version"], self.item["version"])
        self.assertEqual(preview["sha256"], self.preview_hash)
        self.assertEqual(preview["bytes"], len(self.preview_bytes))
        self.assertEqual((preview["width"], preview["height"]), (1024, 1024))
        self.assertEqual(preview["history_dir"], "workshop/preview-history")

    def test_preview_history_names_and_sidecars_are_auditable(self) -> None:
        history = ROOT / self.item["preview"]["history_dir"]
        archives = sorted(history.glob("preview-v*-sha256-*.jpg"))
        self.assertTrue(archives, "the previous preview must be retained locally")
        pattern = re.compile(r"^preview-v(?P<version>.+)-sha256-(?P<sha>[0-9a-f]{64})\.jpg$")
        for archive in archives:
            match = pattern.match(archive.name)
            self.assertIsNotNone(match, archive.name)
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertEqual(digest, match.group("sha"))
            sidecar = archive.with_name(archive.name + ".json")
            self.assertTrue(sidecar.exists(), sidecar)
            record = json.loads(sidecar.read_text(encoding="utf-8"))
            self.assertEqual(record["version"], match.group("version"))
            self.assertEqual(record["sha256"].lower(), match.group("sha"))

    def test_description_has_bilingual_current_version_and_changelog(self) -> None:
        self.assertLessEqual(len(self.description.encode("utf-8")), 8000)
        self.assertEqual(
            len(re.findall(r"\[h2\](?:更新日志\s*/\s*Changelog|Changelog\s*/\s*更新日志)\[/h2\]", self.description)),
            2,
        )
        self.assertEqual(len(re.findall(r"\[h3\]\s*0\.2\.1(?:\s|[（(])", self.description)), 2)
        self.assertEqual(re.findall(r"\[b\]当前版本：\[/b\]\s*([^\s\[]+)", self.description), ["0.2.1"])
        self.assertEqual(re.findall(r"\[b\]Version:\[/b\]\s*([^\s\[]+)", self.description), ["0.2.1"])
        for term in ("钨合金棍", "Buffer", "事件循环", "public-beta", "Vulkan", "OpenGL3", "D3D12"):
            self.assertIn(term, self.description)
        for term in ("Tungsten Rod", "Event Loop"):
            self.assertIn(term, self.description)

    def test_publish_script_cannot_skip_material_gate(self) -> None:
        publish = PUBLISH_SCRIPT.read_text(encoding="utf-8")
        preview = PREVIEW_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("Assert-WorkshopPreviewContract", publish)
        self.assertIn("Assert-WorkshopDescriptionContract", publish)
        self.assertIn("Get-ChangelogForUpload", publish)
        self.assertIn('"--change-note-file", $changeNotePath', publish)
        self.assertIn("-MetadataPath $configPath", publish)
        self.assertIn("$previewEvidence = Assert-WorkshopPreviewContract", publish)
        self.assertIn("$SkipPreview", publish)
        self.assertIn("$version", preview)
        self.assertNotIn('"V0.2.0"', preview)
        self.assertIn("history_dir", preview)
        self.assertIn("Existing preview hash does not match", preview)

    def test_preview_script_can_render_an_explicit_nonproduction_output(self) -> None:
        # This exercises the metadata-driven version path without touching the
        # tracked preview or workshop-item.json.  It is still entirely local.
        powershell = "powershell.exe"
        with tempfile.TemporaryDirectory(prefix="vivhite-workshop-preview-") as temporary:
            output = Path(temporary) / "preview.jpg"
            result = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(PREVIEW_SCRIPT),
                    "-RepoRoot",
                    str(ROOT),
                    "-OutputPath",
                    str(output),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(output.exists())
            self.assertLess(output.stat().st_size, 1_000_000)
            self.assertIn("Version                : 0.2.1", result.stdout)


if __name__ == "__main__":
    unittest.main()
