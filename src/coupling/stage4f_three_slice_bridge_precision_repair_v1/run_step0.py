"""独立 D2 step-0 技术验证入口；不授权后续步骤。"""
from __future__ import annotations
import json
import os
from pathlib import Path
from ..stage4f_three_slice_timestep_diagnostic_v3.engine import factory

ROOT = Path(__file__).resolve().parents[3]
CASE = ROOT / "cases" / "openfoam" / "stage4f_three_slice_bridge_precision_repair_v1" / "branch_D2"
RESULT = ROOT / "results" / "13_stage4f_three_slice_bridge_precision_repair_v1"
PARENT = ROOT / "cases" / "openfoam" / "stage4f_lowre_three_slice_fixed_point_v5" / "formal_preflight_attempt3" / "checkpoints" / "checkpoint_step00000002_d4def62051c1.json"
LIB = ROOT / "runtime" / "stage4f_three_slice_bridge_precision_repair_v1" / "lib" / "libancfFileMotion.so"

def main() -> int:
    plan = {"branch":"D2", "case_root":str(CASE), "results_root":str(RESULT),
            "runtime_root":str(ROOT / "runtime" / "stage4f_three_slice_bridge_precision_repair_v1"),
            "source_checkpoint":str(PARENT), "dt_s":0.000625, "start_time_s":1.5075,
            "end_time_s":1.508125, "steps":1, "slice_ids":[0,1,2], "diagnostic_mode":True}
    os.environ["STAGE4F_V3_MOTION_LIBRARY"] = str(LIB)
    RESULT.mkdir(parents=True, exist_ok=True)
    engine = shutdown = None
    try:
        engine, shutdown = factory(plan)
        row = engine(0, 1.508125)
        payload = {"status":"completed", "steps_completed":1, "step":0, "time_s":1.508125, "engine_result":row}
    except Exception as exc:
        payload = {"status":"failed", "steps_completed":0, "step":0, "time_s":1.508125,
                   "error_type":type(exc).__name__, "error":str(exc)}
    finally:
        if shutdown is not None:
            try: shutdown()
            except Exception as exc: payload["shutdown_error"] = repr(exc)
    (RESULT / "d2_step0_execution.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str)+"\n", encoding="utf-8")
    return 0 if payload["status"] == "completed" else 2

if __name__ == "__main__": raise SystemExit(main())
