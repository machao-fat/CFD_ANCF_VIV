"""One isolated resume after the attempt1 MATLAB 5006 environment failure."""
from __future__ import annotations

import json
from pathlib import Path

from ..multi_slice_mapping.mapping import atomic_write_json
from ..stage4f_c_restart_identity_v1.compare import RestartIdentityTolerances, compare_checkpoint_files
from .real_runner import BASELINE_SUMMARY, PROJECT_ROOT, _run_segment

ATTEMPT1_RESULTS = PROJECT_ROOT / "results" / "16_stage4f_c_restart_extended_v1_attempt1"
CASE_ROOT = PROJECT_ROOT / "cases" / "openfoam" / "stage4f_c_restart_extended_v1_attempt2_after_5006"
RESULT_ROOT = PROJECT_ROOT / "results" / "16_stage4f_c_restart_extended_v1_attempt2_after_5006"


def run():
    if CASE_ROOT.exists() or (RESULT_ROOT.exists() and any(RESULT_ROOT.iterdir())):
        raise FileExistsError("attempt2 repair roots must be new")
    RESULT_ROOT.mkdir(parents=True)
    first = json.loads((ATTEMPT1_RESULTS / "first_leg_summary.json").read_text(encoding="utf-8"))
    baseline = json.loads(BASELINE_SUMMARY.read_text(encoding="utf-8"))
    restart = _run_segment(name="restart_leg_repair", parent=Path(first["final_checkpoint"]), start_step=1, end_step=3, case_root=CASE_ROOT / "restart_leg", result_root=RESULT_ROOT)
    comparisons = []
    if restart["status"] == "passed":
        candidates = [Path(first["steps"][0]["checkpoint"])] + [Path(row["checkpoint"]) for row in restart["steps"]]
        references = [Path(row["checkpoint"]) for row in baseline["steps"]]
        tolerance = RestartIdentityTolerances(structure_relative_linf=1e-11, previous_force_relative_linf=1e-11, time_absolute_s=1e-12)
        comparisons = [compare_checkpoint_files(ref, cand, tolerances=tolerance) for ref, cand in zip(references, candidates)]
    identity = restart["status"] == "passed" and len(comparisons) == 3 and all(row["passed"] for row in comparisons) and restart["processes"]["residual"] == 0
    atomic_write_json(RESULT_ROOT / "restart_identity_comparison.json", {"passed": identity, "comparisons": comparisons})
    extension = None
    if identity:
        extension = _run_segment(name="extension", parent=Path(restart["final_checkpoint"]), start_step=3, end_step=10, case_root=CASE_ROOT / "extension", result_root=RESULT_ROOT)
    summary = {"schema": "stage4f-c-restart-extended-v1-resume-after-5006-1.0.0", "status": "passed" if identity and extension and extension["status"] == "passed" else "failed", "attempt1_first_leg_reused_readonly": True, "attempt1_first_leg": first, "restart_leg": restart, "restart_identity_passed": identity, "restart_comparisons": comparisons, "extension": extension}
    atomic_write_json(RESULT_ROOT / "real_execution_summary.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
