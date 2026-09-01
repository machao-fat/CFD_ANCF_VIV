"""Stage 370 wrapper: execute Stage 369 logic in a fresh, unique runtime."""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve()
SOURCE = HERE.parents[1] / "stage369_restart_point_binding_smoke_v1" / "run_stage369.py"
spec = importlib.util.spec_from_file_location("stage369_impl", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load {SOURCE}")
impl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(impl)
impl.RUNTIME = impl.ROOT / "runtime/stage370_restart_point_binding_smoke_v1"
impl.RESULTS = impl.ROOT / "results/370_restart_point_binding_smoke_v1"
impl.RUN_ID = "run370_restart_point_binding_smoke_v1"
impl.CASE_ID = "case370_restart_point_binding_smoke_v1"
impl.STAGE_ID = "stage4f_d_restart_point_binding_smoke_v2"
raise SystemExit(impl.main())
