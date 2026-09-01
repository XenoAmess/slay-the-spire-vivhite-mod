from __future__ import annotations

import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
START_AGENT = ROOT / "sts2-ascend" / "scripts" / "Start-Agent.ps1"


def function_source(name: str, next_name: str) -> str:
    source = START_AGENT.read_text(encoding="utf-8")
    start = source.index(f"function {name}")
    end = source.index(f"function {next_name}", start)
    return source[start:end]


def ps_literal(value: pathlib.Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def run_powershell(script: str) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix="sts2-steam-consent-") as root:
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


class StartAgentSteamConsentTests(unittest.TestCase):
    def test_consent_helper_uses_game_user_profile_and_has_no_writes(self) -> None:
        source = function_source("Get-GameUserDataRoot", "Get-GameLaunchArguments")
        self.assertIn("$env:APPDATA", source)
        self.assertIn("SlayTheSpire2", source)
        self.assertIn("default\\1", source)
        self.assertIn("settings.save", source)
        self.assertNotRegex(
            source,
            r"(?i)\b(?:Set-Content|Out-File|Add-Content|Copy-Item|Move-Item|Remove-Item|Start-Process)\b",
        )

    def test_missing_null_and_malformed_settings_fail_closed_without_creating_files(self) -> None:
        functions = function_source("Get-GameUserDataRoot", "Get-GameLaunchArguments")
        functions += "\n" + function_source("Test-LocalModConsent", "Normalize-SessionId")
        with tempfile.TemporaryDirectory(prefix="sts2-consent-fixture-") as root:
            app_data = pathlib.Path(root)
            profile = app_data / "SlayTheSpire2" / "default" / "1"
            profile.mkdir(parents=True)

            for payload in (None, '{"mod_settings": null}', "not-json"):
                settings = profile / "settings.save"
                if payload is None:
                    settings.unlink(missing_ok=True)
                else:
                    settings.write_text(payload, encoding="utf-8")
                before = sorted(p.relative_to(app_data).as_posix() for p in app_data.rglob("*"))
                result = run_powershell(
                    f"""
$ErrorActionPreference = 'Stop'
$env:APPDATA = {ps_literal(app_data)}
{functions}
$probe = Test-LocalModConsent
$probe | ConvertTo-Json -Depth 6 -Compress
"""
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                probe = json.loads(result.stdout.strip().splitlines()[-1])
                self.assertFalse(probe["ready"], payload)
                after = sorted(p.relative_to(app_data).as_posix() for p in app_data.rglob("*"))
                self.assertEqual(before, after, payload)

    def test_non_null_mod_settings_is_accepted_as_native_consent_marker(self) -> None:
        functions = function_source("Get-GameUserDataRoot", "Get-GameLaunchArguments")
        functions += "\n" + function_source("Test-LocalModConsent", "Normalize-SessionId")
        with tempfile.TemporaryDirectory(prefix="sts2-consent-fixture-") as root:
            app_data = pathlib.Path(root)
            settings = app_data / "SlayTheSpire2" / "default" / "1" / "settings.save"
            settings.parent.mkdir(parents=True)
            settings.write_text(
                json.dumps(
                    {
                        "schema_version": 8,
                        "mod_settings": {
                            "mods_enabled": True,
                            "mod_list": [{"id": "STS2AIAgent", "is_enabled": True}],
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = run_powershell(
                f"""
$ErrorActionPreference = 'Stop'
$env:APPDATA = {ps_literal(app_data)}
{functions}
$probe = Test-LocalModConsent
$probe | ConvertTo-Json -Depth 6 -Compress
"""
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            probe = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(probe["ready"])
            self.assertTrue(probe["mod_settings_present"])
            self.assertEqual(
                pathlib.Path(probe["settings_path"]).resolve(), settings.resolve()
            )

    def test_off_preflight_precedes_deploy_and_game_launch(self) -> None:
        source = START_AGENT.read_text(encoding="utf-8")
        game_probe = source.index("$game = @(Get-GameProcesses)")
        preflight = source.index("Test-LocalModConsent", game_probe)
        deploy = source.index("if (-not $SkipDeploy)", game_probe)
        launch = source.index("Start-Process -FilePath $gameLauncher", game_probe)
        self.assertLess(preflight, deploy)
        self.assertLess(preflight, launch)
        preflight_block = source[preflight:deploy]
        self.assertRegex(preflight_block, r"(?i)(人工|manual)")
        self.assertRegex(preflight_block, r"(?i)(UAC|GUI)")


if __name__ == "__main__":
    unittest.main()
