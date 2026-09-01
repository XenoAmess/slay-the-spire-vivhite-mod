from __future__ import annotations

import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
START_AGENT = ROOT / "sts2-ascend" / "scripts" / "Start-Agent.ps1"


def helper_source() -> str:
    source = START_AGENT.read_text(encoding="utf-8")
    start = source.index("function Get-GameLaunchArguments")
    end = source.index("function Normalize-SessionId", start)
    return source[start:end]


def run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="sts2-steam-mode-") as root:
        path = pathlib.Path(root) / "check.ps1"
        path.write_text(script, encoding="utf-8-sig")
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )


class StartAgentSteamModeTests(unittest.TestCase):
    def test_parameter_and_audit_fields_are_present(self) -> None:
        source = START_AGENT.read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r'\[ValidateSet\("auto", "on", "off"\)\]\[string\]\$SteamMode\s*=\s*"auto"',
        )
        self.assertIn(
            "$gameLaunchArguments = @(Get-GameLaunchArguments -Mode $SteamMode)",
            source,
        )
        self.assertIn("steam_mode = $SteamMode.ToLowerInvariant()", source)
        self.assertIn("steam_launch_arguments = @($gameLaunchArguments)", source)
        self.assertIn("steam_mode_applied = $steamModeApplied", source)

    def test_only_explicit_off_produces_force_steam_argument(self) -> None:
        helper = helper_source()
        self.assertIn("OrdinalIgnoreCase", helper)
        self.assertIn('return @("--force-steam", "off")', helper)
        self.assertNotIn('"--force-steam", "on"', helper)

        result = run_powershell(
            """
$ErrorActionPreference = 'Stop'
{helper}
foreach ($mode in @('auto', 'on', 'off')) {{
    $args = @(Get-GameLaunchArguments -Mode $mode)
    Write-Output ($mode + '|' + ($args -join ','))
}}
""".format(helper=helper)
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = [line.strip() for line in result.stdout.splitlines() if "|" in line]
        self.assertEqual(rows, ["auto|", "on|", "off|--force-steam,off"])

    def test_cold_launch_branch_is_the_only_argument_forwarding_branch(self) -> None:
        source = START_AGENT.read_text(encoding="utf-8")
        launch = source[source.index("if ($game.Count -eq 0)") :]
        self.assertIn(
            "Start-Process -FilePath $gameLauncher -ArgumentList $gameLaunchArguments",
            launch,
        )
        self.assertIn(
            "Start-Process -FilePath $gameLauncher -WorkingDirectory $GameDir",
            launch,
        )
        self.assertLess(
            launch.index("if ($gameLaunchArguments.Count -gt 0)"),
            launch.index("Start-Process -FilePath $gameLauncher -ArgumentList"),
        )
        self.assertNotIn("steam_appid.txt", launch)
        self.assertNotRegex(launch, r"(?i)(Set-Content|Out-File|Copy-Item).*Steam")

    def test_docs_explain_local_save_use_without_claiming_file_mutation(self) -> None:
        readme = (ROOT / "sts2-ascend" / "README.md").read_text(encoding="utf-8")
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        for text in (readme, agents):
            self.assertIn("SteamMode", text)
            self.assertIn("--force-steam off", text)
            self.assertIn("current_run.save", text)
        self.assertRegex(readme, r"(?i)Steam Cloud|云存档")
        self.assertRegex(agents, r"(?i)Steam Cloud|云存档")
        self.assertIn("user has not yet seen the mods warning", readme)
        self.assertIn("user has not yet seen the mods warning", agents)
        self.assertIn("fail-closed", readme)
        self.assertIn("fail-closed", agents)


if __name__ == "__main__":
    unittest.main()
