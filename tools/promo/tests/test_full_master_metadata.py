from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


PROMO_ROOT = Path(__file__).resolve().parents[1]
if str(PROMO_ROOT) not in sys.path:
    sys.path.insert(0, str(PROMO_ROOT))

from vivhite_promo.run_metadata import (  # noqa: E402
    RunMetadataError,
    SHOT_IDS,
    finalize_run_metadata,
)


class FullMasterMetadataTests(unittest.TestCase):
    def _run(self, root: Path, *, semantic_pass: bool = False) -> Path:
        run_root = root / "run-test-full-master-a1"
        (run_root / "notes").mkdir(parents=True)
        (run_root / "raw").mkdir()
        (run_root / "renders").mkdir()
        (run_root / "evidence").mkdir()
        (run_root / "review").mkdir()
        (run_root / "raw" / "capture.mkv").write_bytes(b"real capture bytes")
        (run_root / "renders" / "master.mp4").write_bytes(b"real deliverable bytes")
        (run_root / "renders" / "master.mp4.probe.json").write_text(
            json.dumps({"streams": [], "format": {"duration": "600.0"}}),
            encoding="utf-8",
        )
        (run_root / "evidence" / "frame.png").write_bytes(b"real frame bytes")
        (run_root / "review" / "probe.json").write_text(
            json.dumps({"status": "pass", "passed": True}), encoding="utf-8"
        )
        artifacts = [
            {
                "artifact_id": "raw.capture",
                "path": "raw/capture.mkv",
                "media_type": "video/x-matroska",
                "category": "raw-media",
            },
            {
                "artifact_id": "deliverable.full-master",
                "path": "renders/master.mp4",
                "media_type": "video/mp4",
                "category": "deliverable",
            },
            {
                "artifact_id": "probe.full-master",
                "path": "renders/master.mp4.probe.json",
                "media_type": "application/json",
                "category": "technical-probe",
            },
            {
                "artifact_id": "evidence.frame",
                "path": "evidence/frame.png",
                "media_type": "image/png",
                "category": "runtime-observation",
            },
            {
                "artifact_id": "report.technical",
                "path": "review/probe.json",
                "media_type": "application/json",
                "category": "technical-audit",
            },
        ]
        reports = {"technical_audit": "report.technical"}
        if semantic_pass:
            (run_root / "review" / "semantic.json").write_text(
                json.dumps({"status": "passed", "passed": True}), encoding="utf-8"
            )
            artifacts.append(
                {
                    "artifact_id": "report.semantic",
                    "path": "review/semantic.json",
                    "media_type": "application/json",
                    "category": "semantic-audit",
                }
            )
            reports["semantic_audit"] = "report.semantic"
        spec = {
            "schema_version": 1,
            "kind": "vivhite_promo_full_master_metadata_spec",
            "run_id": run_root.name,
            "attempt": 1,
            "stage": "master-draft",
            "raw_capture_artifact_id": "raw.capture",
            "deliverable_artifact_id": "deliverable.full-master",
            "deliverable_probe_artifact_id": "probe.full-master",
            "editorial": {
                "width": 1920,
                "height": 1080,
                "fps": 60,
                "target_duration_seconds": 600,
                "voice": "zh-CN-XiaoxiaoNeural",
                "external_bgm": False,
            },
            "artifacts": artifacts,
            "reports": reports,
            "shots": [
                {
                    "shot_id": shot_id,
                    "capture_status": "hash-bound-observation",
                    "semantic_status": "passed" if semantic_pass else "pending",
                    "evidence_artifact_ids": ["evidence.frame"],
                    "observation": "A visual observation only; no API receipt is implied.",
                }
                for shot_id in SHOT_IDS
            ],
            "human_review": {
                "mode": "user-delegated-assumed-pass",
                "instruction": "Proceed without a separate review pause.",
                "independent_1x_observation": False,
            },
            "signoff": False,
            "export": False,
        }
        spec_path = run_root / "notes" / "full-master-metadata-spec.json"
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        return spec_path

    def test_finalizes_content_addressed_sidecars_without_signoff(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-full-master-") as raw:
            spec = self._run(Path(raw))
            manifest = finalize_run_metadata(spec)
            run_root = spec.parent.parent
            self.assertTrue((run_root / "run-manifest.json").is_file())
            self.assertTrue(
                (run_root / "review" / "full-master-artifact-index.json").is_file()
            )
            self.assertTrue(
                (run_root / "review" / "full-master-evidence-coverage.json").is_file()
            )
            self.assertEqual(manifest["gates"]["technical_audit"], "passed")
            self.assertEqual(manifest["gates"]["semantic_audit"], "pending")
            self.assertFalse(manifest["gates"]["signoff"])
            self.assertFalse(manifest["gates"]["export"])
            self.assertFalse(
                manifest["gates"]["human_review"]["independent_1x_observation"]
            )

    def test_refuses_to_overwrite_a_finalized_attempt(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-full-master-") as raw:
            spec = self._run(Path(raw))
            finalize_run_metadata(spec)
            with self.assertRaisesRegex(RunMetadataError, "overwrite"):
                finalize_run_metadata(spec)

    def test_rejects_path_escape_before_hashing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-full-master-") as raw:
            spec = self._run(Path(raw))
            payload = json.loads(spec.read_text(encoding="utf-8"))
            payload["artifacts"][0]["path"] = "../capture.mkv"
            spec.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RunMetadataError, "normalized relative path"):
                finalize_run_metadata(spec)

    def test_semantic_pass_requires_a_passing_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-full-master-") as raw:
            spec = self._run(Path(raw))
            payload = json.loads(spec.read_text(encoding="utf-8"))
            for shot in payload["shots"]:
                shot["semantic_status"] = "passed"
            spec.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RunMetadataError, "passing semantic audit"):
                finalize_run_metadata(spec)

    def test_accepts_semantic_pass_only_with_bound_passing_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-full-master-") as raw:
            spec = self._run(Path(raw), semantic_pass=True)
            manifest = finalize_run_metadata(spec)
            self.assertEqual(manifest["gates"]["semantic_audit"], "passed")


if __name__ == "__main__":
    unittest.main()
