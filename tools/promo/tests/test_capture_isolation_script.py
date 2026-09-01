"""Static safety checks for the reversible capture-mod isolation helper.

The helper is intentionally a PowerShell production script rather than a
Python library.  These checks therefore stay offline and inspect its source:
they make the narrow target list, literal-path operations, stop-the-game gate,
and rollback/audit protocol difficult to accidentally weaken during edits.
"""

from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools" / "promo" / "isolate_capture_mods.ps1"


class CaptureIsolationScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.lines = cls.source.splitlines()

    def test_script_exists_and_has_explicit_target_contract(self) -> None:
        self.assertIn("function New-TargetDefinitions", self.source)
        for target_id in (
            "sts2-ai-agent-manifest",
            "sts2-ai-agent-dll",
            "sts2-ai-agent-pck",
            "workshop-lieren-tvmod",
        ):
            self.assertIn(f'id = "{target_id}"', self.source)
        # The script must not grow a wildcard target scan or an implicit list
        # of every installed mod.
        self.assertNotRegex(self.source, r"Get-ChildItem\s+-LiteralPath\s+\$modsRoot\s+-Recurse")
        self.assertNotRegex(self.source, r"Get-ChildItem\s+[^\r\n]*\*[^\r\n]*mods")

    def test_mutation_commands_are_literal_and_narrow(self) -> None:
        move_lines = [
            line.strip()
            for line in self.lines
            if re.search(r"\bMove-Item\b", line) and not line.lstrip().startswith("#")
        ]
        self.assertGreaterEqual(len(move_lines), 3)
        for line in move_lines:
            self.assertIn("-LiteralPath", line, line)
            self.assertNotIn("-Path", line.replace("-LiteralPath", ""), line)
        remove_lines = [
            line.strip()
            for line in self.lines
            if re.search(r"\bRemove-Item\b", line) and not line.lstrip().startswith("#")
        ]
        self.assertTrue(remove_lines)
        for line in remove_lines:
            self.assertIn("-LiteralPath", line, line)
            self.assertNotIn("-Recurse", line, line)
        for forbidden in ("Start-Process", "Stop-Process", "Copy-Item", "Clear-Item", "Format-Volume"):
            self.assertNotIn(forbidden, self.source)

    def test_stop_gate_and_transactional_rollback_are_present(self) -> None:
        self.assertIn("function Assert-GameStopped", self.source)
        self.assertIn("Assert-GameStopped", self.source)
        self.assertIn("function Assert-TargetShape", self.source)
        self.assertRegex(self.source, r"foreach\s*\(\$target in \$targets\)\s*\{\s*Assert-TargetShape")
        self.assertIn("$movePlan", self.source)
        self.assertIn("$markerWritten", self.source)
        self.assertIn("$restoreCommitted", self.source)
        self.assertIn("rollback", self.source.lower())
        self.assertIn("game and project roots must be on the same volume", self.source)

    def test_marker_is_hash_bound_and_path_guarded(self) -> None:
        self.assertIn("Assert-TargetDefinitions", self.source)
        self.assertIn("Assert-ActiveState", self.source)
        self.assertIn("Assert-PathUnder", self.source)
        self.assertIn("Test-EntryHashAtPath", self.source)
        self.assertIn("Get-FileManifest", self.source)
        self.assertIn("sha256", self.source)
        self.assertIn("active.json", self.source)
        # Restore must refuse an occupied destination; overwriting a newly
        # created mod/save while capture is isolated would be unsafe.
        self.assertIn("refusing to overwrite a path that appeared while isolated", self.source)


if __name__ == "__main__":
    unittest.main()
