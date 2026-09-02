"""Offline checks for the candidate-cut subtitle producer.

These tests import only the project-side helper and never invoke FFmpeg,
ffprobe, xAR execution, or a game process.  A rendered candidate is an
immutable run artifact; changing subtitle timing must be caught before a new
run is produced.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest


PROMO_ROOT = Path(__file__).resolve().parents[1]
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

import render_capture_candidate as candidate  # noqa: E402


class CandidateRenderSubtitleTests(unittest.TestCase):
    def test_ass_is_utf8_bilingual_and_has_five_frame_guard(self) -> None:
        cues = [
            (0.0, "S01-identity", "白绮，以魔法书写几何与星算。", "Vivhite: geometry as magic."),
            (1.0, "S03-cough", "謦欬先支付生命。", "Cough pays life first."),
        ]
        with tempfile.TemporaryDirectory(prefix="vivhite-candidate-ass-") as raw:
            path = Path(raw) / "candidate.ass"
            candidate.write_ass(path, cues, duration=2.0)

            text = path.read_text(encoding="utf-8")
            self.assertIn("白绮，以魔法书写几何与星算。", text)
            self.assertIn("謦欬先支付生命。", text)
            self.assertIn("Vivhite: geometry as magic.", text)
            self.assertNotIn("�", text)

            dialogue = [line for line in text.splitlines() if line.startswith("Dialogue:")]
            self.assertEqual(2, len(dialogue))
            # 1.0 - 5/60 = 0.9166..., represented at ASS centisecond
            # precision as 0.92.  The final cue receives the same guard.
            self.assertIn(",0:00:00.00,0:00:00.92,", dialogue[0])
            self.assertIn(",0:00:01.00,0:00:01.92,", dialogue[1])

    def test_ass_escape_keeps_override_text_literal(self) -> None:
        self.assertEqual(r"a\\b\{c\}\\N", candidate.ass_escape(r"a\b{c}\N"))

    def test_candidate_policy_is_pinned(self) -> None:
        self.assertEqual("zh-CN-XiaoxiaoNeural", candidate.VOICE)
        self.assertEqual(
            {"hero-60", "cut-30", "cut-15"},
            set(candidate.VARIANTS),
        )
        self.assertTrue(all("cues" in spec for spec in candidate.VARIANTS.values()))
        self.assertFalse(any("bgm" in str(spec).casefold() for spec in candidate.VARIANTS.values()))

    def test_capture_contract_path_is_inferred_and_ambiguity_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-candidate-contract-") as raw:
            run_root = Path(raw) / "run-test"
            media_dir = run_root / "raw"
            media_dir.mkdir(parents=True)
            media = media_dir / "capture.mkv"
            media.write_bytes(b"raw")
            partial = run_root / "partial-candidate-contract.json"
            partial.write_text("{}", encoding="utf-8")
            self.assertEqual(partial.resolve(), candidate.infer_capture_contract_path(media))

            canonical = run_root / "capture" / "contract.json"
            canonical.parent.mkdir()
            canonical.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "multiple capture contracts"):
                candidate.infer_capture_contract_path(media)

    def test_edit_window_must_be_inside_a_clean_span(self) -> None:
        contract = SimpleNamespace(
            clean_spans=(
                SimpleNamespace(
                    span_id="wide",
                    begin_seconds=10.0,
                    end_seconds=20.0,
                    provenance="natural",
                ),
                SimpleNamespace(
                    span_id="narrow",
                    begin_seconds=11.0,
                    end_seconds=19.0,
                    provenance="staged",
                ),
            )
        )
        selected = candidate.containing_capture_span(contract, 11.0, 8.0)
        self.assertEqual("narrow", selected.span_id)
        with self.assertRaisesRegex(RuntimeError, "not contained"):
            candidate.containing_capture_span(contract, 19.0, 2.0)

    def test_output_root_must_be_a_fresh_sibling_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-candidate-output-") as raw:
            source_run = Path(raw) / "run-source"
            media = source_run / "raw" / "capture.mkv"
            media.parent.mkdir(parents=True)
            media.write_bytes(b"raw")

            with self.assertRaisesRegex(RuntimeError, "source capture run"):
                candidate.validate_output_root(media, source_run / "nested")

            sibling = Path(raw) / "run-candidate"
            candidate.validate_output_root(media, sibling)
            sibling.mkdir()
            (sibling / "batch-manifest.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "reuse an existing"):
                candidate.validate_output_root(media, sibling)

    def test_capture_identity_gate_rejects_non_vulkan_fixture(self) -> None:
        fixture = PROMO_ROOT / "fixtures" / "minimal_capture"
        contract_path = fixture / "contract.json"
        payload = contract_path.read_text(encoding="utf-8")
        modified = payload.replace('"renderer": "vulkan"', '"renderer": "opengl"')
        self.assertNotEqual(payload, modified)
        # Keep the fixture artifacts in their original location and only
        # assert the adapter's identity gate directly; no media is copied or
        # mutated by this offline test.
        import json

        data = json.loads(payload)
        data["project_context"]["renderer"] = "opengl"
        from vivhite_promo.adapter import VivhiteAdapter, VivhiteAdapterError

        with self.assertRaises(VivhiteAdapterError):
            VivhiteAdapter().validate_identity(data["project_context"])

    def test_render_inputs_reject_mutated_sidecar(self) -> None:
        class StableCapture:
            def verify_unchanged(self) -> None:
                return None

        with tempfile.TemporaryDirectory(prefix="vivhite-candidate-input-") as raw:
            contract_path = Path(raw) / "contract.json"
            contract_path.write_bytes(b"contract")
            contract_record = candidate.file_record(contract_path)
            path = Path(raw) / "narration.mp3"
            path.write_bytes(b"before")
            record = candidate.file_record(path)
            path.write_bytes(b"after")
            with self.assertRaisesRegex(RuntimeError, "narration input changed"):
                candidate.verify_render_inputs(
                    capture_contract=StableCapture(),
                    contract_path=contract_path,
                    capture_provenance={"contract": contract_record},
                    narration_inputs=(record,),
                    tool_inputs={},
                )

    def test_capture_binding_checks_fixture_hash_and_provenance(self) -> None:
        fixture = PROMO_ROOT / "fixtures" / "minimal_capture"
        raw = fixture / "media" / "raw-gameplay.mp4"
        contract_path = fixture / "contract.json"
        contract, provenance = candidate.load_capture_binding(raw, contract_path)
        self.assertEqual("minimal-capture-fixture", contract.run_id)
        self.assertEqual("contract.json", provenance["contract"]["relative_path"])
        self.assertEqual(
            candidate.sha256_file(raw),
            provenance["raw_binding"]["sha256"],
        )
        self.assertEqual({"hero-60", "cut-30", "cut-15"}, set(candidate.VARIANTS))


if __name__ == "__main__":
    unittest.main()
