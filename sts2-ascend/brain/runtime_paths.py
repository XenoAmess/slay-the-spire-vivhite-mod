"""Runtime path selection shared by production processes and unit tests.

Production keeps the historical ``sts2-ascend/knowledge`` root.  A unittest
process instead receives one process-scoped temporary knowledge directory.  The
directory is published through the environment so subprocesses launched by a
test inherit the same isolation without per-test monkeypatches.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


TEST_KNOWLEDGE_ENV = "STS2_ASCEND_TEST_KNOWLEDGE_DIR"
_owned_test_directory: tempfile.TemporaryDirectory[str] | None = None


def _running_under_unittest() -> bool:
    """Recognize standard unittest entrypoints without affecting production."""
    if "unittest" not in sys.modules:
        return False

    main_spec = getattr(sys.modules.get("__main__"), "__spec__", None)
    if getattr(main_spec, "name", "") == "unittest.__main__":
        return True

    arguments = [str(argument).casefold() for argument in sys.argv]
    if "discover" in arguments[1:]:
        return True
    if arguments:
        return Path(arguments[0]).name.casefold().startswith("test_")
    return False


def _temporary_test_knowledge_dir() -> Path:
    global _owned_test_directory
    if _owned_test_directory is None:
        _owned_test_directory = tempfile.TemporaryDirectory(
            prefix="sts2-ascend-unittest-")
    knowledge_dir = Path(_owned_test_directory.name) / "knowledge"
    os.environ[TEST_KNOWLEDGE_ENV] = str(knowledge_dir)
    return knowledge_dir


def resolve_knowledge_dir(base_dir: Path) -> Path:
    """Return the production knowledge root or the inherited unittest root."""
    inherited_test_dir = os.environ.get(TEST_KNOWLEDGE_ENV, "").strip()
    if inherited_test_dir:
        path = Path(inherited_test_dir).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve()
    if _running_under_unittest():
        return _temporary_test_knowledge_dir().resolve()
    return Path(base_dir).resolve() / "knowledge"
