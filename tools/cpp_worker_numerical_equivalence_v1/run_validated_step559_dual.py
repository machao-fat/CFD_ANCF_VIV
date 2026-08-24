"""Run the C++-only half of the step559 numerical audit after MATLAB export.

The MATLAB exporter is deliberately a separate, explicitly authorized step.
This entry point launches only the checked C++ worker and refuses missing or
invalid golden records before creating any worker process.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scipy.io import loadmat

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / "src"))

from coupling.cpp_worker_numerical_equivalence_v1.golden_validator import validate_jsonl
from tools.cpp_worker_persistent_ipc_v1.run_matlab_cpp_dual_run_40 import main as run_dual


SOURCE = PROJECT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
MATLAB_SEED = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/matlab_dual_011/accepted_step559_seed.mat"
TEMPLATE = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/dual_run_024/results/cpp_input_fixture.json"
WORKER = PROJECT / "runtime/cpp_worker_persistent_ipc_v1/build-release/cfd_ancf_ancf_kernel_worker.exe"


def _write_fixture(path: Path) -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    fixture = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    structure = source["structure"]
    matlab_state = loadmat(MATLAB_SEED, squeeze_me=True, struct_as_record=False)["state"]
    source_mass = matlab_state.model.mass_matrix
    fixture.update({
        "source_step": 559,
        "source_time_s": 2.2075,
        "q": structure["q"],
        "qdot": structure["qdot"],
        "qddot": structure["qddot"],
        "slice_force": [value for row in source["previous_slice_forces_N"] for value in row],
        "gauss_order": 5,
        "max_newton": 50,
        "mass_matrix": [float(value) for value in source_mass.reshape(-1)],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fixture, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--worker", type=Path, default=WORKER)
    args = parser.parse_args(argv)
    golden = args.golden.resolve()
    runtime = args.runtime.resolve()
    results = args.results.resolve()
    if not golden.is_file():
        raise SystemExit("golden JSONL is missing; MATLAB export is required first")
    worker = args.worker.resolve()
    if not SOURCE.is_file() or not TEMPLATE.is_file() or not worker.is_file():
        raise SystemExit("protected source, fixture template, or C++ worker is missing")
    if runtime.exists() or results.exists():
        raise SystemExit("runtime/results must be fresh; refusing retry or reuse")
    run_id = "cpp_worker_numerical_equivalence_before_cfd_001_matlab"
    case_id = "cpp_worker_numerical_equivalence_before_cfd_case_001_matlab"
    validation = validate_jsonl(golden, run_id=run_id, case_id=case_id)
    runtime.mkdir(parents=True)
    results.mkdir(parents=True)
    fixture = runtime / "cpp_input_fixture_step559.json"
    _write_fixture(fixture)
    audit_path = results / "matlab_cpp_step559_dual_audit.json"
    return_code = run_dual(str(fixture), str(golden), str(audit_path), str(worker))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    payload = {
        "stage_id": "stage4f_d_cpp_worker_numerical_equivalence_before_cfd_v1",
        "run_id": run_id, "case_id": case_id,
        "golden_validation": validation,
        "dual_audit": audit,
        "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0,
                                 "C++_worker": int(audit.get("worker_start_count", 0))},
        "owned_residual": int(audit.get("owned_residual", 1)),
        "old_evidence_modified": False, "old_runtime_reused": False,
        "cfd_started": False,
    }
    (results / "validated_step559_dual_summary.json").write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
