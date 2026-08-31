"""Regression coverage for unittest/production log path isolation."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ASCEND_DIR = Path(__file__).resolve().parents[1]
PRODUCTION_KNOWLEDGE = ASCEND_DIR / "knowledge"
PRODUCTION_LOGS = (
    PRODUCTION_KNOWLEDGE / "brain.log",
    PRODUCTION_KNOWLEDGE / "tts_quipper.log",
)
TEST_KNOWLEDGE_ENV = "STS2_ASCEND_TEST_KNOWLEDGE_DIR"


def _file_metadata(path: Path) -> dict:
    if not path.exists():
        return {"exists": False}
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": digest.hexdigest(),
    }


def _production_log_metadata() -> dict:
    return {str(path): _file_metadata(path) for path in PRODUCTION_LOGS}


class TestLogIsolationTests(unittest.TestCase):
    def test_plain_unittest_subprocess_redirects_all_three_loggers(self) -> None:
        before = _production_log_metadata()
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            probe_result = temporary_path / "probe-result.json"
            probe = temporary_path / "test_log_probe.py"
            probe.write_text(textwrap.dedent("""
                import json
                import os
                from pathlib import Path
                import sys
                import unittest

                ascend = Path(os.environ["ASCEND_TEST_ROOT"])
                sys.path.insert(0, str(ascend / "brain"))
                sys.path.insert(0, str(ascend / "tts"))

                import agent
                import runner
                import quipper


                class LogProbe(unittest.TestCase):
                    def test_log_paths(self):
                        isolated = Path(os.environ[
                            "STS2_ASCEND_TEST_KNOWLEDGE_DIR"]).resolve()
                        production = (ascend / "knowledge").resolve()
                        self.assertNotEqual(isolated, production)
                        self.assertEqual(agent.KNOWLEDGE_DIR, isolated)
                        self.assertEqual(agent._LOG_PATH,
                                         isolated / "brain.log")
                        self.assertEqual(runner.KNOWLEDGE_DIR, isolated)
                        self.assertEqual(quipper.KNOWLEDGE_DIR, isolated)
                        self.assertEqual(quipper.LOG_FILE,
                                         isolated / "tts_quipper.log")

                        agent.log("agent unittest isolation probe")
                        runner.log("runner unittest isolation probe")
                        quipper.log("quipper unittest isolation probe")

                        brain_text = (isolated / "brain.log").read_text(
                            encoding="utf-8")
                        quipper_text = (isolated / "tts_quipper.log").read_text(
                            encoding="utf-8")
                        self.assertIn("agent unittest isolation probe", brain_text)
                        self.assertIn("runner unittest isolation probe", brain_text)
                        self.assertIn("quipper unittest isolation probe",
                                      quipper_text)
                        Path(os.environ["ASCEND_PROBE_RESULT"]).write_text(
                            json.dumps({"isolated": str(isolated)}),
                            encoding="utf-8")
            """), encoding="utf-8")

            environment = os.environ.copy()
            environment.pop(TEST_KNOWLEDGE_ENV, None)
            environment["ASCEND_TEST_ROOT"] = str(ASCEND_DIR)
            environment["ASCEND_PROBE_RESULT"] = str(probe_result)
            completed = subprocess.run(
                [sys.executable, "-m", "unittest", "discover", "-s",
                 str(temporary_path), "-p", probe.name],
                cwd=ASCEND_DIR,
                env=environment,
                capture_output=True,
                text=True,
                timeout=120,
            )

            after = _production_log_metadata()
            self.assertEqual(before, after)
            self.assertEqual(
                completed.returncode, 0,
                msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
            result = json.loads(probe_result.read_text(encoding="utf-8"))
            self.assertNotEqual(
                Path(result["isolated"]).resolve(), PRODUCTION_KNOWLEDGE.resolve())

    def test_non_test_process_keeps_the_production_knowledge_root(self) -> None:
        before = _production_log_metadata()
        environment = os.environ.copy()
        environment.pop(TEST_KNOWLEDGE_ENV, None)
        code = textwrap.dedent("""
            import json
            from pathlib import Path
            import sys

            ascend = Path(sys.argv[1]).resolve()
            sys.path.insert(0, str(ascend / "brain"))
            sys.path.insert(0, str(ascend / "tts"))
            import agent
            import runner
            import quipper
            print(json.dumps({
                "agent": str(agent.KNOWLEDGE_DIR),
                "agent_log": str(agent._LOG_PATH),
                "runner": str(runner.KNOWLEDGE_DIR),
                "quipper": str(quipper.KNOWLEDGE_DIR),
                "quipper_log": str(quipper.LOG_FILE),
            }))
        """)
        completed = subprocess.run(
            [sys.executable, "-c", code, str(ASCEND_DIR)],
            cwd=ASCEND_DIR,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        after = _production_log_metadata()
        self.assertEqual(before, after)
        paths = json.loads(completed.stdout.strip())
        production = PRODUCTION_KNOWLEDGE.resolve()
        self.assertEqual(Path(paths["agent"]).resolve(), production)
        self.assertEqual(Path(paths["runner"]).resolve(), production)
        self.assertEqual(Path(paths["quipper"]).resolve(), production)
        self.assertEqual(
            Path(paths["agent_log"]).resolve(), production / "brain.log")
        self.assertEqual(
            Path(paths["quipper_log"]).resolve(),
            production / "tts_quipper.log")


if __name__ == "__main__":
    unittest.main()
