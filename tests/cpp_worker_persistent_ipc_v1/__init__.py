"""Stage97 tests are importable from both local and root unittest discovery."""

from pathlib import Path
import sys

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
