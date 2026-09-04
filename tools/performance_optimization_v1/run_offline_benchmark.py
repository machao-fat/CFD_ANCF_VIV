from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from coupling.performance_optimization_v1.config import audit_candidate, optimize_control_dict, optimize_fv_solution


STAGE_ID = "stage318_performance_optimization_v1"
RESULTS = ROOT / "results/318_performance_optimization_v1"
BASE_RUNTIME = ROOT / "runtime/stage317_moving_mesh_smoke_v1_fresh"


def main() -> int:
    source_case = BASE_RUNTIME / "slice_0000"
    fv = (source_case / "system/fvSolution").read_text(encoding="utf-8")
    control = (source_case / "system/controlDict").read_text(encoding="utf-8")
    candidate_fv = optimize_fv_solution(fv, update_mesh_once=False)
    candidate_control = optimize_control_dict(control)
    logs = BASE_RUNTIME / "logs"
    baseline_report = json.loads((ROOT / "results/317_moving_mesh_smoke_v1/stage308_smoke_report.json").read_text(encoding="utf-8"))
    fluid_log = (logs / "fluid_0000.stdout").read_text(encoding="utf-8", errors="replace")
    execution = re.findall(r"ExecutionTime = ([0-9.]+) s  ClockTime = ([0-9.]+) s", fluid_log)
    numeric_dirs = [p for p in source_case.iterdir() if p.is_dir() and re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", p.name) and p.name != "0"]
    baseline = {
        "source_stage": "stage317_moving_mesh_smoke_v1",
        "steps": 8,
        "dt_s": 0.005,
        "slice_count": 3,
        "wall_clock_s": baseline_report["wall_clock"]["elapsed_s"],
        "fluid_clock_s": float(execution[-1][1]) if execution else None,
        "pimple_outer_iterations": len(re.findall(r"PIMPLE: Iteration", fluid_log)),
        "mesh_motion_solves": len(re.findall(r"Solving for cellDisplacement[xy]", fluid_log)),
        "mesh_motion_solves_at_max_iter_1000": fluid_log.count("No Iterations 1000"),
        "retained_time_directories_per_slice": len(numeric_dirs),
        "write_events_expected_for_8_steps": 8,
        "runtime_bytes": sum(p.stat().st_size for p in BASE_RUNTIME.rglob("*") if p.is_file()),
    }
    candidate = {
        "cache_fix": True,
        "mesh_motion_updates_preserved": True,
        "mesh_motion_solves_expected_for_8_steps": baseline["mesh_motion_solves"],
        "mesh_motion_solve_reduction_fraction": 0.0,
        "write_events_expected_for_8_steps": 1,
        "write_event_reduction_fraction": 1 - 1 / baseline["write_events_expected_for_8_steps"],
        "measured_wall_clock_s": None,
        "measurement_status": "requires one separately authorized real smoke; offline report makes no speed claim",
    }
    aggressive = {
        "moveMeshOuterCorrectors": "no",
        "mesh_motion_solve_reduction_fraction": 1 - (8 * 2) / baseline["mesh_motion_solves"],
        "status": "rejected_by_stage319_smoke_because_mesh_did_not_move",
    }
    checks = audit_candidate(fv_solution=candidate_fv, control_dict=candidate_control, require_mesh_update_once=False)
    RESULTS.mkdir(parents=True, exist_ok=True)
    for index in range(3):
        (RESULTS / f"candidate_slice_{index:04d}_fvSolution").write_text(candidate_fv, encoding="utf-8")
        (RESULTS / f"candidate_slice_{index:04d}_controlDict").write_text(candidate_control, encoding="utf-8")
    report = {
        "schema_version": 1,
        "stage_id": STAGE_ID,
        "scope": "offline configuration candidate and measured Stage317 baseline; no solver launch",
        "baseline": baseline,
        "candidate": candidate,
        "aggressive_candidate": aggressive,
        "candidate_checks": checks,
        "real_process_starts": {"matlab": 0, "openfoam": 0, "wsl": 0, "cfd": 0},
        "owned_residual": 0,
        "protected": {"stage317_runtime_read_only": True, "physical_parameters_modified": False, "global_dt_modified": False, "slice_count_modified": False, "formal_protocol_modified": False},
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "next_authorization": "new explicit authorization required before measuring candidate wall-clock with a real smoke",
    }
    (RESULTS / "offline_performance_comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"stage_id": STAGE_ID, "status": "pass" if all(checks.values()) else "do_not_pass", "path": str(RESULTS / 'offline_performance_comparison.json')}, ensure_ascii=False))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
