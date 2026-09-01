"""Contract and preflight tests for the Steam Workshop change-note bridge.

The uploader must receive a release-note file, validate it before touching the
Steam client, and pass the exact validated UTF-8 text to SubmitItemUpdate.
These tests intentionally never submit a Workshop update.  When a locally
built uploader is available, a few tests exercise its input-error path; the
source-contract checks remain runnable in a clean checkout without Steamworks.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import tempfile
import unittest
import os


ROOT = pathlib.Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "tools" / "workshop" / "SteamWorkshopUploader" / "Program.cs"
UPLOADER_DLL = (
    ROOT
    / "tools"
    / "workshop"
    / "SteamWorkshopUploader"
    / "bin"
    / "Release"
    / "net9.0"
    / "SteamWorkshopUploader.dll"
)


def find_dotnet() -> str | None:
    candidates = []
    dotnet_root = pathlib.Path(os.environ.get("DOTNET_ROOT", ""))
    if str(dotnet_root):
        candidates.append(dotnet_root / "dotnet.exe")
    candidates.append(pathlib.Path(shutil.which("dotnet") or ""))
    candidates.append(
        pathlib.Path(r"C:\Users\xenoa\AppData\Local\Microsoft\dotnet\dotnet.exe")
    )
    for candidate in candidates:
        if str(candidate) and candidate.is_file():
            return str(candidate)
    return None


class WorkshopUploaderChangeNoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = PROGRAM.read_text(encoding="utf-8")

    def test_file_flag_is_required_and_wired_to_submit(self) -> None:
        self.assertIn('Required("change-note-file")', self.source)
        self.assertIn("string ChangeNoteFile", self.source)
        self.assertIn("ReadChangeNote(options.ChangeNoteFile)", self.source)
        self.assertIn("SteamUGC.SubmitItemUpdate(handle, validatedInputs.ChangeNote)", self.source)
        self.assertNotIn("initial Steam Workshop release", self.source)
        self.assertNotIn("package and metadata refresh", self.source)

    def test_validation_is_strict_and_happens_before_steam_init(self) -> None:
        self.assertIn("MaxWorkshopChangeNoteBytes = 8000", self.source)
        self.assertIn("new(encoderShouldEmitUTF8Identifier: false, throwOnInvalidBytes: true)", self.source)
        self.assertIn("Workshop change note must be valid UTF-8", self.source)
        self.assertIn("Workshop change note must not be empty or whitespace-only", self.source)
        self.assertIn("Workshop change note must not contain NUL characters", self.source)
        validation = self.source.index("validatedInputs = ValidateInputs(options)")
        steam_init = self.source.index("SteamAPI.InitEx")
        self.assertLess(validation, steam_init)

    def test_oversize_and_invalid_utf8_notes_fail_without_a_receipt(self) -> None:
        if find_dotnet() is None or not UPLOADER_DLL.is_file():
            self.skipTest("requires a locally built uploader and dotnet runtime")

        with tempfile.TemporaryDirectory(prefix="vivhite-uploader-note-") as raw_root:
            root = pathlib.Path(raw_root)
            content = root / "content"
            content.mkdir()
            for name in ("Vivhite.dll", "Vivhite.json", "Vivhite.pck"):
                (content / name).write_bytes(b"fixture")
            preview = root / "preview.jpg"
            preview.write_bytes(b"0123456789abcdef")
            description = root / "description.bbcode"
            description.write_text("[h2]Vivhite[/h2]", encoding="utf-8")
            result = root / "receipt.json"

            for label, payload, expected in (
                ("invalid", b"\xff", "valid UTF-8"),
                ("oversize", b"A" * 8001, "at most 8000"),
            ):
                note = root / f"{label}.txt"
                note.write_bytes(payload)
                completed = subprocess.run(
                    [
                        find_dotnet(),
                        str(UPLOADER_DLL),
                        "--app-id",
                        "2868840",
                        "--content",
                        str(content),
                        "--preview",
                        str(preview),
                        "--title",
                        "Vivhite test",
                        "--description-file",
                        str(description),
                        "--change-note-file",
                        str(note),
                        "--version",
                        "0.0.0-test",
                        "--result",
                        str(result),
                        "--timeout-seconds",
                        "30",
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(completed.returncode, 2, completed.stdout + completed.stderr)
                self.assertIn(expected, completed.stderr)
                self.assertFalse(result.exists(), "input rejection must precede receipt/Steam side effects")


if __name__ == "__main__":
    unittest.main()
