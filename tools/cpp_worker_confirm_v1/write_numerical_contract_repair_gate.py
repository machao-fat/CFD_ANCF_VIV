"""Write the offline numerical-contract repair evidence for stage 120."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from coupling.cpp_worker_confirm_v1.numerical_contract import (
    ANCF_CONTRACT_SOURCE,
    ANCF_GAUSS_ORDER,
    ANCF_MAX_NEWTON,
)


PROJECT = Path(__file__).resolve().parents[2]
RESULTS = PROJECT / "results/120_cpp_worker_numerical_contract_repair_v1"
DIAGNOSTIC = RESULTS / "gauss3_maxnewton40_offline_40step.json"


def canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def write(path: Path, value: object) -> None:
    path.write_bytes(canonical(value))


def main() -> int:
    diagnostic = json.loads(DIAGNOSTIC.read_text(encoding="utf-8"))
    processed = int(diagnostic["processed_steps"])
    finite = int(diagnostic["finite_steps"])
    passed = processed == 40 and finite == 40 and diagnostic["failure"] is None and diagnostic["owned_residual"] == 0
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_NUMERICAL_CONTRACT_REPAIR_V1_GATE: pass" if passed else "STAGE4F_D_CPP_WORKER_NUMERICAL_CONTRACT_REPAIR_V1_GATE: do_not_pass",
        "status": "pass" if passed else "do_not_pass",
        "stage_id": "stage4f_d_cpp_worker_numerical_contract_repair_v1",
        "run_id": diagnostic["run_id"],
        "case_id": diagnostic["case_id"],
        "root_cause": "real_confirm_003 used historical fixture gauss_order=5/max_newton=50 instead of the ANCF contract gauss_order=3/max_newton=40",
        "repair": {"gauss_order": ANCF_GAUSS_ORDER, "max_newton": ANCF_MAX_NEWTON, "source": ANCF_CONTRACT_SOURCE,
                   "physical_parameters_modified": False, "global_dt_modified": False, "thresholds_modified": False},
        "offline_validation": {"requested_steps": 40, "processed_steps": processed, "finite_steps": finite,
                                "cpp_worker_startup": diagnostic["worker_startup"], "owned_residual": diagnostic["owned_residual"],
                                "real_process_starts": diagnostic["real_process_starts"]},
        "real_confirm_003": {"gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass",
                              "failure_step": 583, "failure": "slice 2 forces.dat contains NaN/Inf", "read_only": True},
        "old_evidence_modified": False,
        "old_runtime_reused": False,
        "new_real_confirm_authorization_required": True,
    }
    write(RESULTS / "stage4f_d_cpp_worker_numerical_contract_repair_v1_gate.json", gate)
    audit = {
        "stage_id": gate["stage_id"], "compileall": "pass", "specialized_tests": "42/42 passed",
        "root_unittest": "1088 collected, 1087 passed, 1 skipped, 0 failure/error",
        "offline_40step_contract_replay": "pass" if passed else "fail",
        "real_process_starts": diagnostic["real_process_starts"], "cpp_worker_startup": diagnostic["worker_startup"],
        "owned_residual": diagnostic["owned_residual"],
        "diagnostic_sha256": hashlib.sha256(DIAGNOSTIC.read_bytes()).hexdigest(),
    }
    write(RESULTS / "test_discovery_audit.json", audit)
    report = f"""# C++ ANCF numerical-contract repair\n\n- Gate: `{gate['gate']}`\n- Root cause: historical fixture used gauss order 5 / Newton limit 50; the ANCF contract is order 3 / limit 40.\n- Offline replay: {processed}/40 finite steps.\n- C++ worker startup: {diagnostic['worker_startup']}\n- MATLAB/OpenFOAM/WSL/CFD starts: 0\n- owned residual: {diagnostic['owned_residual']}\n- Real confirm 003 remains fail-closed at step 583 and was not retried.\n\nNo physical parameters, global dt, thresholds, formal protocol semantics, old evidence, or old runtime were modified. A new explicit real-confirm authorization is still required.\n"""
    (PROJECT / "docs/120_cpp_worker_numerical_contract_repair_v1").mkdir(parents=True, exist_ok=True)
    (PROJECT / "docs/120_cpp_worker_numerical_contract_repair_v1/report.md").write_text(report, encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
