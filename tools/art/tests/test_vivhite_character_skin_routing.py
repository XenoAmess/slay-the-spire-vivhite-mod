from __future__ import annotations

import json
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
CODE_ROOT = REPO_ROOT / "Vivhite" / "VivhiteCode"
ENTRY_PATH = CODE_ROOT / "Entry.cs"
CHARACTER_PATH = CODE_ROOT / "Characters" / "VivhiteCharacter.cs"
ASSETS_PATH = CODE_ROOT / "Characters" / "VivhiteCharacterAssets.cs"
LEGACY_REPLACEMENT_PATH = (
    CODE_ROOT / "Characters" / "IroncladReplacementAssets.cs"
)
SKIN_ROOT = REPO_ROOT / "Vivhite" / "Vivhite" / "skins" / "ironclad"
CONTRACT_PATH = REPO_ROOT / "Vivhite" / "tools" / "ironclad-skin.contract.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class VivhiteCharacterSkinRoutingTests(unittest.TestCase):
    def test_vivhite_never_registers_an_ironclad_asset_replacement(self) -> None:
        sources = "\n".join(
            _read(path) for path in sorted(CODE_ROOT.rglob("*.cs"))
        )

        self.assertNotIn("VanillaCharacterIds.Ironclad", sources)
        self.assertNotIn("IroncladReplacementAssets", sources)
        self.assertNotIn("PrefixIroncladCharacterSelectSfx", sources)
        self.assertNotIn("PrefixIroncladCharacterTransitionSfx", sources)
        self.assertNotIn("EnsureIroncladVirtualAudioOverrides", sources)
        self.assertNotIn("_activeIroncladAudio", sources)
        self.assertNotIn("IroncladReplacementAssets.TryRegister()", _read(ENTRY_PATH))
        self.assertFalse(LEGACY_REPLACEMENT_PATH.exists())

    def test_independent_vivhite_owns_the_validated_v3_profile(self) -> None:
        character = _read(CHARACTER_PATH)
        assets = _read(ASSETS_PATH)

        self.assertIn(
            "VivhiteCharacterAssets.GetValidatedV3Profile()", character
        )
        self.assertIn("EnergyCounterPath = EnergyCounterScenePath", character)
        self.assertIn("TrailPath: CardTrailScenePath", character)
        self.assertIn(
            'private const string SkinRoot = $"{Entry.ResPath}/skins/ironclad";',
            assets,
        )
        self.assertIn("new CharacterSceneAssetSet(", assets)
        self.assertIn("new CharacterUiAssetSet(", assets)
        self.assertIn("new CharacterSpineAssetSet(", assets)
        self.assertIn("new CharacterAudioAssetSet(", assets)
        self.assertIn("new CharacterMultiplayerAssetSet(", assets)

    def test_vivhite_profile_keeps_the_exact_v3_five_page_resources(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        layouts = {
            layout["name"]: layout for layout in contract["combatRuntimeLayouts"]
        }
        v3 = layouts["v3-five-page"]
        expected_pages = [
            "spine/combat/vivhite_combat.png",
            "spine/combat/vivhite_combat_death.png",
            "spine/combat/vivhite_combat_attack.png",
            "spine/combat/vivhite_combat_attack_heavy.png",
            "spine/combat/vivhite_combat_cast.png",
        ]

        self.assertEqual([page["path"] for page in v3["pages"]], expected_pages)
        for relative in expected_pages:
            self.assertTrue((SKIN_ROOT / relative).is_file(), relative)

        for relative in (
            "scenes/combat.tscn",
            "scenes/merchant.tscn",
            "scenes/rest_site.tscn",
            "scenes/character_select.tscn",
            "ui/icon.png",
            "ui/icon_outline.png",
            "ui/select.png",
            "ui/select_locked.png",
            "ui/map_marker.png",
            "multiplayer/point.png",
            "multiplayer/rock.png",
            "multiplayer/paper.png",
            "multiplayer/scissors.png",
        ):
            self.assertTrue((SKIN_ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
