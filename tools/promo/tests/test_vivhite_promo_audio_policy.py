"""Fail-closed audio-policy regression tests for the Vivhite adapter."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PROMO_ROOT = ROOT / "tools" / "promo"
FIXTURE_ROOT = PROMO_ROOT / "fixtures" / "minimal_capture"
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))


class VivhiteAudioPolicyTests(unittest.TestCase):
    def test_bgm_stem_is_rejected_before_build_dependencies_are_resolved(self) -> None:
        from vivhite_promo.adapter import VivhiteAdapter, VivhiteAdapterError

        payload = json.loads(
            (FIXTURE_ROOT / "contract.json").read_text(encoding="utf-8")
        )
        # Reuse an already hash-bound synthetic file: this test is about the
        # preset policy, not audio decoding or a second media fixture.
        payload["audio_stems"].append(
            {
                "stem_id": "bgm",
                "artifact": copy.deepcopy(payload["audio_stems"][0]["artifact"]),
            }
        )
        with tempfile.TemporaryDirectory(prefix="vivhite-promo-bgm-") as raw:
            isolated = Path(raw)
            for source in FIXTURE_ROOT.rglob("*"):
                if source.is_file():
                    target = isolated / source.relative_to(FIXTURE_ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
            contract_path = isolated / "contract.json"
            contract_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            adapter = VivhiteAdapter(
                project_root=PROMO_ROOT,
                storyboard_path=PROMO_ROOT / "storyboard.json",
                claims_path=PROMO_ROOT / "claims" / "claims.json",
            )
            with self.assertRaisesRegex(VivhiteAdapterError, "include_bgm=false"):
                adapter.load_capture(contract_path, artifact_root=isolated)

    def test_runtime_dependency_identity_is_fail_closed(self) -> None:
        from vivhite_promo.adapter import VivhiteAdapter, VivhiteAdapterError

        payload = json.loads(
            (FIXTURE_ROOT / "contract.json").read_text(encoding="utf-8")
        )
        payload["project_context"]["ritsu_lib_version"] = "0.5.13"
        with tempfile.TemporaryDirectory(prefix="vivhite-promo-runtime-id-") as raw:
            isolated = Path(raw)
            for source in FIXTURE_ROOT.rglob("*"):
                if source.is_file():
                    target = isolated / source.relative_to(FIXTURE_ROOT)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
            contract_path = isolated / "contract.json"
            contract_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            adapter = VivhiteAdapter(
                project_root=PROMO_ROOT,
                storyboard_path=PROMO_ROOT / "storyboard.json",
                claims_path=PROMO_ROOT / "claims" / "claims.json",
            )
            with self.assertRaisesRegex(VivhiteAdapterError, "ritsu_lib_version"):
                adapter.load_capture(contract_path, artifact_root=isolated)


if __name__ == "__main__":
    unittest.main()
