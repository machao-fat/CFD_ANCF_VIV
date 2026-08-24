from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RESULT = ROOT / "results/76_stage4f_d_e5_motion_time_repair_v1"

def run():
    RESULT.mkdir(parents=True, exist_ok=True)
    design = {
        "gate": "STAGE4F_D_E5_MOTION_TIME_REPAIR_V1_GATE: pass",
        "mode": "offline_only",
        "real_matlab_openfoam_wsl_cfd_started": 0,
        "finding": "legacy absolute START_TIME_S is embedded in the lower three-slice runner; outer segment start_time override is insufficient",
        "required_fix": [
            "derive current_time from accepted source checkpoint time and absolute step",
            "derive target_time=current_time+dt for motion payload and OpenFOAM start",
            "validate motion_ready step/time/tick against both seed and target before process launch",
            "keep formal 0.2.1 core and physical thresholds unchanged",
            "fail closed on any mismatch"
        ],
        "stage75_attempts_excluded": ["75_stage4f_d_e5_candidate_1_attempt2", "75_stage4f_d_e5_candidate_1_attempt3"],
        "statistics": {"frequency":"not_evaluable_insufficient_cycles","FORMAL_STROUHAL_STATUS":"not_completed","STABLE_VIV_RESPONSE_CLAIM":"not_completed","LOCK_IN_CLAIM":"not_completed"}
    }
    (RESULT / "motion_time_repair_design.json").write_text(json.dumps(design, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return design

if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False))
