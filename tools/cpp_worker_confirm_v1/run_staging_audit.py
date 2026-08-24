"""Run the read-only C++ confirm staging audit."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from coupling.cpp_worker_confirm_v1.staging import main


if __name__ == "__main__":
    raise SystemExit(main())
