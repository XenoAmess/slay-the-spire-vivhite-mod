"""Regression checks for the renderer/version claims exposed to players.

The game provides more than one Godot rendering driver, but this repository has
only accepted the Vulkan path in-game.  Keep the public instructions honest:
Vulkan remains the default while alternate drivers are explicitly unverified.
"""

from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


class RendererCompatibilityDocumentationTests(unittest.TestCase):
    def _read(self, relative: str) -> str:
        return (REPO_ROOT / relative).read_text(encoding="utf-8")

    def test_vivhite_readmes_state_the_verified_scope(self) -> None:
        for relative in ("Vivhite/README.md", "Vivhite/README.en.md"):
            with self.subTest(relative=relative):
                text = self._read(relative)
                self.assertIn("v0.111.0", text)
                self.assertIn("public-beta", text)
                self.assertIn("Vulkan", text)
                self.assertIn("OpenGL3", text)
                if relative.endswith("README.md") and not relative.endswith("README.en.md"):
                    self.assertIn("尚未完成", text)
                else:
                    self.assertRegex(text, r"(?i)not (?:completed|constitute|compatib|verified)")
                self.assertNotIn("启动游戏必须使用 Vulkan", text)
                self.assertNotIn("The game must be started with Vulkan", text)

    def test_workshop_description_discloses_fallback_limits(self) -> None:
        text = self._read("workshop/description.bbcode")
        self.assertIn("public-beta", text)
        self.assertIn("v0.111.0", text)
        self.assertIn("--rendering-driver vulkan", text)
        self.assertIn("--rendering-driver opengl3", text)
        self.assertIn("尚未完成", text)
        self.assertIn("has not completed", text)
        self.assertNotIn("使用 Vulkan 启动游戏；", text)
        self.assertNotIn("Launch with Vulkan using", text)

    def test_training_stack_keeps_vulkan_as_the_default(self) -> None:
        launcher = self._read("sts2-ascend/scripts/Start-Agent.ps1")
        config = self._read("sts2-ascend/brain/config.json")
        self.assertIn('launch_vulkan.bat', launcher)
        self.assertIn('launch_vulkan.bat', config)


if __name__ == "__main__":
    unittest.main()
