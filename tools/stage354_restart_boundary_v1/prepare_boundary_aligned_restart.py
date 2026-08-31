"""Generate a fresh boundary-aligned restart candidate offline."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_TOOL = ROOT / "tools/stage352_restart_boundary_v1/prepare_boundary_aligned_restart.py"
spec = importlib.util.spec_from_file_location("stage352_prepare", SOURCE_TOOL)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load preparation tool: {SOURCE_TOOL}")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Stage352 and the partial Stage353 candidates are preserved and never reused.
module.RUNTIME = ROOT / "runtime/stage354_restart_boundary_v1_fresh_candidate"
module.RESULTS = ROOT / "results/354_restart_boundary_v1"
module.STAGE_ID = "stage4f_d_restart_boundary_v1_fresh_candidate_v2"

if __name__ == "__main__":
    raise SystemExit(module.main())
