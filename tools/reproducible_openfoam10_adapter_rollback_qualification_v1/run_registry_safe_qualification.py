"""One fresh no-ANCF OF10 registry-safe rollback qualification (one 0.005 s window)."""
from __future__ import annotations

import json
from pathlib import Path

import run_real_precice_rollback_qualification as base
from run_checkpoint_lifecycle_motion_qualification import AMPLITUDE_Y_M, participant_code, xml


def main() -> int:
    run = "of10_registry_safe_rollback_nonzero_motion_qualification_v1_run_001"
    library_wsl = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_005/lib"
    base.RUN = run
    base.RUNTIME, base.RESULTS = base.ROOT / "runtime" / run, base.ROOT / "results" / run
    base.DIAG_LIBRARY_WSL = library_wsl
    base.DIAG_LIBRARY = Path(library_wsl)
    base.DIAG_LIBRARY_FILE = base.DIAG_LIBRARY / "libpreciceAdapterFunctionObject.so"
    base.TRIAL_Y_M = (AMPLITUDE_Y_M, -AMPLITUDE_Y_M)
    base.xml = xml
    base.participant_code = participant_code
    case = base.prepare()
    contract_path = base.RUNTIME / "contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract.update({
        "schema_version": "of10-registry-safe-rollback-nonzero-motion-qualification-v1",
        "registry_safe_meshPhi_policy": "DERIVED_RECONSTRUCTED_AFTER_MOVEPOINTS",
        "oldTime_policy": "NATURAL_OF10_LAZY_HISTORY_RECONSTRUCTED_BY_NEXT_SOLVE",
        "initial_displacement_y_m": AMPLITUDE_Y_M,
        "trial_input_schedule_y_m": [AMPLITUDE_Y_M, AMPLITUDE_Y_M, -AMPLITUDE_Y_M, -AMPLITUDE_Y_M],
        "fixture_convergence_abs_limit_m": 0.0001,
        "displacement_semantics": "total_displacement",
        "physical_windows": 1,
    })
    base.write(contract_path, json.dumps(contract, indent=2) + "\n")
    code = base.run(case)
    trace_path = base.RUNTIME / "adapter_rollback_trace.jsonl"
    trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()] if trace_path.is_file() else []
    participant_path = base.RUNTIME / "participant_evidence.json"
    participant = json.loads(participant_path.read_text(encoding="utf-8")) if participant_path.is_file() else {}
    base.RESULTS.mkdir(parents=True, exist_ok=True)
    base.write(base.RESULTS / "real_rollback_raw.json", json.dumps({
        "return_code": code, "adapter_trace": trace, "participant": participant,
        "runtime": str(base.RUNTIME), "diagnostic_library_sha256": base.sha256(base.DIAG_LIBRARY_FILE),
    }, indent=2) + "\n")
    print(json.dumps({"return_code": code, "events": [row.get("event") for row in trace], "iterations": participant.get("iterations")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
