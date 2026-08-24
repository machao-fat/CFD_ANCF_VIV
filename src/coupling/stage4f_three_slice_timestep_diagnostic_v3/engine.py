"""Fresh D2 engine using only the independently rebuilt precision bridge."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from . import engine_impl


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPAIRED_LIBRARY = (
    PROJECT_ROOT / "runtime" / "stage4f_three_slice_timestep_diagnostic_v3" / "lib" / "libancfFileMotion.so"
)


def factory(plan: Mapping[str, Any]):
    if str(plan.get("branch")) != "D2":
        raise ValueError("v3 authorizes only the fresh D2 diagnostic")
    library = Path(os.environ.get("STAGE4F_V3_MOTION_LIBRARY", DEFAULT_REPAIRED_LIBRARY)).resolve()
    if not library.is_file():
        raise FileNotFoundError(f"repaired motion library is missing: {library}")
    # The old engine imported this compatibility-library path as a module
    # constant. Override it only in this fresh Python process; old source,
    # cases, evidence, and the formal 0.2.1 protocol remain untouched.
    engine_impl.DEFAULT_LIBRARY = library
    engine = engine_impl.DiagnosticEngine(plan)
    return engine, engine.shutdown
