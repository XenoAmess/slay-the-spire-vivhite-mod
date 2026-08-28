"""Regressions for complete failed-package evidence passed back to GLM."""
from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


BRAIN = Path(__file__).resolve().parents[1] / "brain"
sys.path.insert(0, str(BRAIN))

import llm_review  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True,
        text=True, encoding="utf-8", errors="replace")
    return completed.stdout.strip()


class FailedReviewEvidenceMountTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="sts2-replay-evidence-")
        self.root = Path(self.temp.name)
        self.salvage = self.root / "salvage"
        self.salvage.mkdir()
        self.old_salvage = llm_review.SALVAGE_ROOT
        llm_review.SALVAGE_ROOT = self.salvage

    def tearDown(self) -> None:
        llm_review.SALVAGE_ROOT = self.old_salvage
        self.temp.cleanup()

    def _package(self, name: str, marker: bytes) -> Path:
        package = self.salvage / name
        raw_repo = package / "raw_sandbox" / "repo"
        (raw_repo / ".git").mkdir(parents=True)
        changed = raw_repo / "sts2-ascend" / "brain" / "policy.py"
        changed.parent.mkdir(parents=True)
        changed.write_bytes(marker)
        binary = raw_repo / "sts2-ascend" / "scratch.bin"
        binary.write_bytes(b"\x00\xff" + marker)
        captured = package / "files" / "sts2-ascend" / "notes.txt"
        captured.parent.mkdir(parents=True)
        captured.write_text("captured", encoding="utf-8")
        manifest = {
            "pre_head": "a" * 40,
            "snapshot_deferred": False,
            "raw_sandbox_deferred": False,
            "retry_evidence_ready": True,
            "retry_evidence_schema": llm_review._RETRY_EVIDENCE_SCHEMA,
        }
        (package / "manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8")
        (package / "report.md").write_text(
            f"report {name}", encoding="utf-8")
        (package / "file_states.json").write_text(
            json.dumps([{"path": "sts2-ascend/notes.txt", "kind": "file"}]),
            encoding="utf-8")
        inventory = {
            "schema": llm_review._RETRY_EVIDENCE_SCHEMA,
            "package": name,
            "paths": [
                "sts2-ascend/brain/policy.py",
                "sts2-ascend/scratch.bin",
                "sts2-ascend/deleted.py",
            ],
            "sources": [{"kind": "worktree", "paths": [
                "sts2-ascend/brain/policy.py",
                "sts2-ascend/scratch.bin",
                "sts2-ascend/deleted.py",
            ]}],
        }
        (package / "retry_candidate_inventory.json").write_text(
            json.dumps(inventory), encoding="utf-8")
        # Larger than the old per-attempt prompt excerpt, so exact equality proves
        # that the model-facing file is not the 256 KiB prompt summary.
        (package / "retry_candidate.patch").write_bytes(marker * 180_000)
        (package / "wip.patch").write_bytes(b"wip-" + marker)
        (package / "model_output_tail.txt").write_text(
            "model tail", encoding="utf-8")
        return package

    def test_mount_contains_target_and_all_attempt_files_with_integrity(self) -> None:
        target = self._package("pkg-target", b"T")
        attempt = self._package("pkg-attempt", b"A")
        sandbox = self.root / "sandbox"
        sandbox.mkdir()
        manifests = {
            path.name: json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            for path in (target, attempt)
        }
        with (mock.patch.object(
                llm_review, "_materialize_retry_evidence",
                side_effect=lambda package, log=print: manifests[package.name]),
              mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
            mount = llm_review._mount_failed_review_evidence(
                sandbox, ["pkg-target"], ["pkg-attempt"],
                log=lambda _message: None)

        index = json.loads(Path(mount["index_path"]).read_text(encoding="utf-8"))
        self.assertTrue(index["complete"])
        self.assertEqual(index["requested_packages"], ["pkg-target"])
        self.assertEqual(index["attempt_packages"], ["pkg-attempt"])
        self.assertEqual([item["role"] for item in index["packages"]],
                         ["target", "attempt_evidence"])
        mounted_root = Path(mount["root"])
        for name, marker in (("pkg-target", b"T"), ("pkg-attempt", b"A")):
            package_root = mounted_root / "packages" / name
            self.assertEqual(
                (package_root / "retry_candidate.patch").read_bytes(),
                marker * 180_000)
            self.assertEqual(
                (package_root / "changed_files" / "raw_worktree"
                 / "sts2-ascend" / "brain" / "policy.py").read_bytes(), marker)
            self.assertEqual(
                (package_root / "changed_files" / "raw_worktree"
                 / "sts2-ascend" / "scratch.bin").read_bytes(),
                b"\x00\xff" + marker)
            self.assertEqual(
                (package_root / "captured_files" / "sts2-ascend"
                 / "notes.txt").read_text(encoding="utf-8"), "captured")
            states = index["packages"][0 if name == "pkg-target" else 1][
                "changed_file_states"]
            self.assertEqual(states[-1]["state"], "deleted_or_source_only")
        llm_review._verify_failed_review_evidence(sandbox, mount)
        self.assertTrue(llm_review._remove_failed_review_evidence(
            sandbox, log=lambda _message: None))
        self.assertFalse(mounted_root.exists())
        self.assertTrue(target.is_dir())
        self.assertTrue(attempt.is_dir())

    def test_modified_mount_fails_closed_and_original_package_remains(self) -> None:
        package = self._package("pkg-target", b"X")
        sandbox = self.root / "sandbox-modified"
        sandbox.mkdir()
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        with (mock.patch.object(llm_review, "_materialize_retry_evidence",
                               return_value=manifest),
              mock.patch.object(llm_review, "_review_stop_requested", return_value=False)):
            mount = llm_review._mount_failed_review_evidence(
                sandbox, ["pkg-target"], log=lambda _message: None)
        candidate = (Path(mount["root"]) / "packages" / "pkg-target"
                     / "retry_candidate.patch")
        candidate.chmod(stat.S_IWRITE | stat.S_IREAD)
        candidate.write_bytes(b"modified")
        with self.assertRaises(llm_review._RetryEvidenceUnavailable):
            llm_review._verify_failed_review_evidence(sandbox, mount)
        rejected = llm_review.SandboxReviewResult(
            diagnostic_report="retry_resolution: pkg-target no_valid_change",
            replay_evidence_requested=True,
            replay_evidence_complete=False,
            replay_evidence_error="hash mismatch",
        )
        self.assertEqual(llm_review._validated_retry_resolutions(
            rejected, ["pkg-target"], log=lambda _message: None), {})
        self.assertTrue(package.is_dir())
        self.assertTrue(llm_review._remove_failed_review_evidence(
            sandbox, log=lambda _message: None))

    def test_missing_required_evidence_never_starts_model_or_consumes_target(self) -> None:
        package = self._package("pkg-target", b"M")
        (package / "report.md").unlink()
        repo = self.root / "repo"
        (repo / "sts2-ascend" / "brain").mkdir(parents=True)
        (repo / "sts2-ascend" / "brain" / "base.py").write_text(
            "READY = True\n", encoding="utf-8")
        (repo / ".gitignore").write_text(
            "sts2-ascend/knowledge/\n", encoding="utf-8")
        _git(repo, "init", "--quiet")
        _git(repo, "config", "user.email", "test@example.invalid")
        _git(repo, "config", "user.name", "test")
        _git(repo, "add", ".")
        _git(repo, "commit", "--quiet", "-m", "base")
        head = _git(repo, "rev-parse", "HEAD")
        old_values = (
            llm_review.REPO_DIR, llm_review.BASE_DIR, llm_review.KNOWLEDGE_DIR,
            llm_review.PROMPT_FILE,
        )
        llm_review.REPO_DIR = repo
        llm_review.BASE_DIR = repo / "sts2-ascend"
        llm_review.KNOWLEDGE_DIR = llm_review.BASE_DIR / "knowledge"
        llm_review.PROMPT_FILE = llm_review.KNOWLEDGE_DIR / "review_prompt_latest.md"
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        try:
            with (mock.patch.object(llm_review, "_materialize_retry_evidence",
                                   return_value=manifest),
                  mock.patch.object(llm_review, "_review_stop_requested",
                                    return_value=False),
                  mock.patch.object(
                      llm_review, "_stream_run",
                      side_effect=AssertionError("model must not start"))):
                result = llm_review._run_review_sandbox(
                    ["opencode", "run", "--dir", str(repo)], "prompt", head, 30,
                    llm_review.OpencodeJsonTranslator(),
                    replay_packages=["pkg-target"], log=lambda _message: None)
        finally:
            (llm_review.REPO_DIR, llm_review.BASE_DIR, llm_review.KNOWLEDGE_DIR,
             llm_review.PROMPT_FILE) = old_values
        self.assertIn("完整证据不可用", result.error)
        self.assertFalse(result.replay_evidence_complete)
        self.assertFalse(result.replay_evidence_model_started)
        self.assertEqual(llm_review._validated_retry_resolutions(
            result, ["pkg-target"], log=lambda _message: None), {})
        self.assertTrue(package.is_dir())


if __name__ == "__main__":
    unittest.main()
