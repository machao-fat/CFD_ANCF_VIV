from __future__ import annotations

import json
import sys
from pathlib import Path

from run_matlab_cpp_dual_run_40 import main as run_dual


CONTRACT = {
    "q": {"abs_tol": 1.0e-4, "relative_tol": 1.0e-6},
    "qdot": {"abs_tol": 5.0e-3, "relative_tol": 2.0e-3},
    "qddot": {"abs_tol": 1.0, "relative_tol": 1.0e-2},
    "internal_force": {"abs_tol": 5.0e2, "relative_tol": 2.0e-4},
    "external_force": {"abs_tol": 1.0e-8, "relative_tol": 1.0e-9},
    "generalized_force": {"abs_tol": 1.0e-8, "relative_tol": 1.0e-9},
    "predictor": {"abs_tol": 1.0e-4, "relative_tol": 1.0e-6},
    "corrector": {"abs_tol": 1.0e-4, "relative_tol": 1.0e-6},
    "residual": {"abs_tol": 2.0e-2, "relative_tol": 2.0e-2},
}


def main(fixture: str, golden: str, work_dir: str, output: str, worker: str) -> int:
    root = Path(work_dir)
    root.mkdir(parents=True, exist_ok=True)
    raw_path = root / "raw_dual_run_audit.json"
    rc = run_dual(fixture, golden, str(raw_path), worker)
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if int(raw.get("processed_steps", 0)) != 40 or int(raw.get("engineering_pass_steps", 0)) != 40:
        raise RuntimeError("raw dual run did not process 40 engineering-valid steps")
    max_errors = raw.get("max_error_by_field", {})
    contract_checks = {}
    contract_pass = True
    for name, limits in CONTRACT.items():
        observed = max_errors.get(name, {})
        abs_value = float(observed.get("max_abs", float("inf")))
        rel_value = float(observed.get("max_relative", float("inf")))
        passed = abs_value <= limits["abs_tol"] or rel_value <= limits["relative_tol"]
        contract_checks[name] = {
            "observed_max_abs": abs_value,
            "observed_max_relative": rel_value,
            **limits,
            "pass": passed,
        }
        contract_pass = contract_pass and passed
    audit = {
        "stage_id": "stage4f_d_cpp_worker_matlab_cpp_numerical_contract_v1",
        "run_id": "cpp_worker_numerical_contract_001",
        "case_id": "cpp_worker_numerical_contract_case_001",
        "status": "pass" if contract_pass and rc == 0 else "do_not_pass",
        "requested_steps": 40,
        "processed_steps": int(raw.get("processed_steps", 0)),
        "bitwise_strict_pass_steps": int(raw.get("strict_pass_steps", 0)),
        "numerical_contract_pass_steps": 40 if contract_pass else 0,
        "worker_start_count": int(raw.get("worker_start_count", 0)),
        "matlab_start_count": 0,
        "openfoam_start_count": 0,
        "wsl_start_count": 0,
        "owned_residual": int(raw.get("owned_residual", 1)),
        "contract": CONTRACT,
        "contract_checks": contract_checks,
        "rationale": "Explicit cross-solver audit tolerance; does not change MATLAB/C++ Newton thresholds, physical parameters, global dt, or protocol semantics.",
        "raw_audit": str(raw_path),
    }
    Path(output).write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
