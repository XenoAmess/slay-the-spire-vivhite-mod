"""Allows `py -m brain` from the sts2-ascend directory."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import main  # noqa: E402

if __name__ == "__main__":
    main()
