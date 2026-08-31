from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLISHER_PATH = REPO_ROOT / "tools" / "art" / "publish_ironclad_skin.py"
CONTRACT_PATH = REPO_ROOT / "Vivhite" / "tools" / "ironclad-skin.contract.json"

SPEC = importlib.util.spec_from_file_location("publish_ironclad_skin", PUBLISHER_PATH)
assert SPEC is not None and SPEC.loader is not None
publisher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)


def _atlas_text(pages: tuple[object, ...]) -> str:
    blocks: list[str] = []
    for page in pages:
        lines = [
            page.name,
            f"size:{page.width},{page.height}",
            "filter:Linear,Linear",
            "pma:false",
            "repeat:none",
        ]
        for region in page.regions:
            lines.extend(
                [
                    region.name,
                    "bounds:" + ",".join(str(value) for value in region.bounds),
                ]
            )
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


class PublishIroncladSkinContractTests(unittest.TestCase):
    def test_python_and_json_runtime_layouts_are_identical(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        json_layouts = {
            layout["name"]: layout for layout in contract["combatRuntimeLayouts"]
        }
        self.assertEqual(set(json_layouts), set(publisher.RUNTIME_LAYOUTS))

        for name, layout in publisher.RUNTIME_LAYOUTS.items():
            json_layout = json_layouts[name]
            self.assertEqual(
                json_layout["expectedRuntimeFileCount"],
                layout.expected_runtime_file_count,
            )
            actual_pages = [
                {
                    "path": page.path,
                    "width": page.width,
                    "height": page.height,
                    "regions": [
                        {"name": region.name, "bounds": list(region.bounds)}
                        for region in page.regions
                    ],
                }
                for page in layout.combat_pages
            ]
            self.assertEqual(json_layout["pages"], actual_pages)
            self.assertEqual(
                len(publisher._expected_output_paths(layout)),
                layout.expected_runtime_file_count,
            )

    def test_cli_can_publish_legacy_but_active_contract_remains_v3(self) -> None:
        args = publisher._parse_args([])
        self.assertEqual(args.runtime_layout, "legacy-single-page")

        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(contract["runtimeLayout"], "v3-five-page")
        self.assertEqual(contract["expectedRuntimeFileCount"], 30)
        v3_layout = next(
            layout
            for layout in contract["combatRuntimeLayouts"]
            if layout["name"] == "v3-five-page"
        )
        self.assertEqual(v3_layout["expectedRuntimeFileCount"], 34)
        self.assertEqual(
            [page["path"] for page in v3_layout["pages"]],
            [
                "spine/combat/vivhite_combat.png",
                "spine/combat/vivhite_combat_death.png",
                "spine/combat/vivhite_combat_attack.png",
                "spine/combat/vivhite_combat_attack_heavy.png",
                "spine/combat/vivhite_combat_cast.png",
            ],
        )
        # spineSets is the single-page base template. The PowerShell validator
        # resolves runtimeLayout and replaces these page lists from the selected
        # combatRuntimeLayouts profile before validating Source or PCK contents.
        for spine_set in contract["spineSets"]:
            if spine_set["name"] in {"combat", "merchant"}:
                self.assertTrue(spine_set["exactPages"])
                self.assertEqual(
                    spine_set["pages"], ["spine/combat/vivhite_combat.png"]
                )

    def test_eye_vfx_and_transition_round_trip_preserve_all_four_resources(self) -> None:
        script_relative = publisher.COMBAT_VFX_SCRIPT
        eye_relative = publisher.EYE_LENS_GLINT_TEXTURE
        texture_relative = publisher.CHARACTER_SELECT_TRANSITION_TEXTURE
        material_relative = publisher.CHARACTER_SELECT_TRANSITION_MATERIAL
        runtime_root = REPO_ROOT / "Vivhite" / "Vivhite" / "skins" / "ironclad"
        script_data = (runtime_root / script_relative).read_bytes()
        eye_data = (runtime_root / eye_relative).read_bytes()
        texture_data = (runtime_root / texture_relative).read_bytes()
        material_data = (runtime_root / material_relative).read_bytes()
        preserved = {
            script_relative: script_data,
            eye_relative: eye_data,
            texture_relative: texture_data,
            material_relative: material_data,
        }

        for layout in publisher.RUNTIME_LAYOUTS.values():
            expected = publisher._expected_output_paths(layout)
            for relative, original in preserved.items():
                self.assertIn(relative, expected)

        outputs = publisher._load_private_runtime_outputs(
            runtime_root,
            publisher.RUNTIME_LAYOUTS["v3-five-page"],
        )
        for relative, original in preserved.items():
            self.assertEqual(outputs[relative], original)

        decoded = publisher._decode_rgba8_png(
            texture_data,
            texture_relative,
            expected_color_type=2,
            bytes_per_pixel=3,
        )
        self.assertEqual((decoded.width, decoded.height), (2560, 1200))
        self.assertTrue(publisher._rgb8_png_is_strict_grayscale(decoded))

        changed_shader = material_data.replace(
            b"texture(transitionTex, UV).r",
            b"texture(transitionTex, UV).g",
        )
        self.assertNotEqual(changed_shader, material_data)
        with self.assertRaisesRegex(publisher.PublishError, "missing"):
            publisher._validate_private_runtime_file(
                material_relative,
                changed_shader,
                publisher.RUNTIME_LAYOUTS["v3-five-page"],
            )

        combat_scene_relative = "scenes/combat.tscn"
        combat_scene = (runtime_root / combat_scene_relative).read_bytes()
        legacy_scene = combat_scene + b'\n[node name="EyeFire" type="TextureRect"]\n'
        with self.assertRaisesRegex(publisher.PublishError, "forbidden legacy VFX"):
            publisher._validate_private_runtime_file(
                combat_scene_relative,
                legacy_scene,
                publisher.RUNTIME_LAYOUTS["v3-five-page"],
            )

    def test_v3_atlas_requires_exact_five_page_order_and_regions(self) -> None:
        layout = publisher.RUNTIME_LAYOUTS["v3-five-page"]
        atlas_text = _atlas_text(layout.combat_pages)
        publisher._validate_combat_atlas_layout(atlas_text, layout, "fixture")

        reordered = (
            layout.combat_pages[0],
            layout.combat_pages[2],
            layout.combat_pages[1],
            *layout.combat_pages[3:],
        )
        with self.assertRaisesRegex(publisher.PublishError, "page order/count"):
            publisher._validate_combat_atlas_layout(
                _atlas_text(reordered), layout, "reordered fixture"
            )

        missing_region_page = publisher.AtlasPageContract(
            layout.combat_pages[0].path,
            layout.combat_pages[0].width,
            layout.combat_pages[0].height,
            layout.combat_pages[0].regions[:-1],
        )
        with self.assertRaisesRegex(publisher.PublishError, "region order/bounds"):
            publisher._validate_combat_atlas_layout(
                _atlas_text((missing_region_page, *layout.combat_pages[1:])),
                layout,
                "missing-region fixture",
            )

        wrong_size_page = publisher.AtlasPageContract(
            layout.combat_pages[0].path,
            layout.combat_pages[0].width - 1,
            layout.combat_pages[0].height,
            layout.combat_pages[0].regions,
        )
        with self.assertRaisesRegex(publisher.PublishError, "must declare"):
            publisher._validate_combat_atlas_layout(
                _atlas_text((wrong_size_page, *layout.combat_pages[1:])),
                layout,
                "wrong-size fixture",
            )

    def test_forbidden_pck_and_private_extension_contract_is_retained(self) -> None:
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(
            set(contract["forbiddenPckSegments"]),
            {"bin", ".work", "vanilla", "tools"},
        )
        self.assertEqual(
            set(contract["forbiddenPrivateExtensions"]), {".skel", ".spskel"}
        )


if __name__ == "__main__":
    unittest.main()
