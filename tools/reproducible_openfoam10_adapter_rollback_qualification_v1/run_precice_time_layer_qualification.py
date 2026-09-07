"""Run exactly one no-ANCF rollback window using the patch-0005 diagnostic library."""
from __future__ import annotations

import json
from pathlib import Path

import run_real_precice_rollback_qualification as base
from run_checkpoint_lifecycle_motion_qualification import AMPLITUDE_Y_M, participant_code, xml


RUN = "precice_time_layer_contract_different_input_rollback_closure_v1_run_001"
LIB_WSL = "/home/machao/OpenFOAM/reproducible_adapter_rollback_qualification_v1/diagnostic_build_006/lib"


def main() -> int:
    base.RUN = RUN
    base.RUNTIME, base.RESULTS = base.ROOT / "runtime" / RUN, base.ROOT / "results" / RUN
    base.DIAG_LIBRARY_WSL = LIB_WSL
    base.DIAG_LIBRARY = Path(LIB_WSL)
    base.DIAG_LIBRARY_FILE = base.DIAG_LIBRARY / "libpreciceAdapterFunctionObject.so"
    base.TRIAL_Y_M = (AMPLITUDE_Y_M, -AMPLITUDE_Y_M)
    base.xml = xml
    base.participant_code = participant_code
    case = base.prepare()
    contract = json.loads((base.RUNTIME / "contract.json").read_text(encoding="utf-8"))
    contract.update({
        "schema_version": "precice-time-layer-contract-and-different-input-rollback-closure-v1",
        "adapter_patch": "0005-precice-time-layer-and-different-input-rollback",
        "initial_displacement_y_m": AMPLITUDE_Y_M,
        "trial_input_schedule_y_m": [AMPLITUDE_Y_M, AMPLITUDE_Y_M, -AMPLITUDE_Y_M, -AMPLITUDE_Y_M],
        "post_advance_read_relative_time": 0.005,
        "physical_windows": 1,
        "qualification": "no-ANCF one physical window only",
    })
    base.write(base.RUNTIME / "contract.json", json.dumps(contract, indent=2) + "\n")
    code = base.run(case)
    trace_path = base.RUNTIME / "adapter_rollback_trace.jsonl"
    trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()] if trace_path.is_file() else []
    evidence_path = base.RUNTIME / "participant_evidence.json"
    participant = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.is_file() else {}
    base.RESULTS.mkdir(parents=True, exist_ok=True)
    base.write(base.RESULTS / "real_rollback_raw.json", json.dumps({
        "return_code": code,
        "adapter_trace": trace,
        "participant": participant,
        "runtime": str(base.RUNTIME),
        "diagnostic_library_sha256": base.sha256(base.DIAG_LIBRARY_FILE),
    }, indent=2) + "\n")
    print(json.dumps({"return_code": code, "events": [item.get("event") for item in trace], "iterations": participant.get("iterations")}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
