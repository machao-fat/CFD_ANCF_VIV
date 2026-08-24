"""Prepare, but never execute, a fresh stage-local OpenFOAM library build."""

from __future__ import annotations

import json
from pathlib import Path

from coupling.cpp_worker_confirm_v1.library_build_guard import prepare_fresh_library_build


PROJECT = Path(__file__).resolve().parents[2]
RUNTIME = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/fresh_library_build_004"
RESULTS = PROJECT / "results/110_cpp_worker_library_build_v1"
SOURCE = PROJECT / "src/openfoam/ancfFileMotion"


def main() -> int:
    plan = prepare_fresh_library_build(project_root=PROJECT, runtime=RUNTIME,
                                       results=RESULTS, source_tree=SOURCE)
    report = {
        "stage_id": "stage4f_d_cpp_worker_library_build_v1",
        "run_id": "cpp_worker_library_build_001",
        "case_id": "cpp_worker_library_build_case_001",
        "status": "prepared_only",
        "plan": plan,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "authorization_consumed": False,
    }
    (RESULTS / "fresh_library_build_audit.json").write_text(
        json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (RESULTS / "stage4f_d_cpp_worker_library_build_v1_gate.json").write_text(
        json.dumps({
            "gate": "STAGE4F_D_CPP_WORKER_LIBRARY_BUILD_V1_GATE: do_not_pass",
            "status": "do_not_pass", "reason": "build not executed; explicit OpenFOAM/WSL/CFD authorization required",
            "real_process_starts": report["real_process_starts"], "owned_residual": 0,
        }, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
