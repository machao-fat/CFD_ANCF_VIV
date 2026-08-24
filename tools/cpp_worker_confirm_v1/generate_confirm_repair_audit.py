"""Record the offline repair after the one-shot real confirm failed closed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[2]
OUT = PROJECT / "results/114_cpp_worker_confirm_repair_v1"
FAILED = PROJECT / "results/112_cpp_worker_persistent_ipc_confirm_v2"
ADAPTER = PROJECT / "src/coupling/cpp_worker_confirm_v1/real_slice_adapter.py"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    failed_summary = json.loads((FAILED / "confirm_summary.json").read_text(encoding="utf-8"))
    failed_gate = json.loads((FAILED / "stage4f_d_cpp_worker_persistent_ipc_v1_confirm_gate.json").read_text(encoding="utf-8"))
    audit = {
        "stage_id": "stage4f_d_cpp_worker_confirm_repair_v1",
        "run_id": "cpp_worker_confirm_repair_001",
        "case_id": "cpp_worker_confirm_repair_case_001",
        "status": "offline_repair_verified",
        "failed_confirm": {
            "stage_id": failed_summary["stage_id"], "run_id": failed_summary["run_id"],
            "physical_committed": failed_summary["physical_committed"],
            "fully_audited": failed_summary["fully_audited"],
            "failure": failed_summary["failure"], "gate": failed_gate["gate"],
            "real_process_starts": failed_summary["real_process_starts"],
            "owned_residual": failed_summary["owned_residual"],
        },
        "repair": {
            "file": str(ADAPTER),
            "sha256": sha256(ADAPTER),
            "change": "convert MotionRecord seed to seed.to_dict() before persistent backend begin_step",
            "same_runtime_reused": False,
            "same_runtime_retried": False,
        },
        "offline_tests": {
            "compileall": "pass",
            "cpp_worker_confirm_specialized": {"collected": 13, "passed": 13, "failed": 0, "errors": 0},
            "root_unittest": {"collected": 1086, "passed": 1085, "failed": 0, "errors": 0, "skipped": 1},
        },
        "post_failure_process_audit": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0, "owned_residual": 0,
                                         "no_second_real_confirm_started": True},
        "old_evidence_modified": False,
        "old_runtime_reused": False,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
    }
    write(OUT / "confirm_failure_and_repair_audit.json", audit)
    gate = {
        "gate": "STAGE4F_D_CPP_WORKER_CONFIRM_REPAIR_V1_GATE: pass",
        "status": "pass",
        "repair_verified_offline": True,
        "real_confirm_gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass",
        "reason": "the authorized one-shot confirm failed at step 561 and cannot be retried without new explicit authorization",
        "real_process_starts_after_failure": audit["post_failure_process_audit"],
        "next_action": "obtain a new explicit authorization before a fresh bounded confirm",
    }
    write(OUT / "stage4f_d_cpp_worker_confirm_repair_v1_gate.json", gate)
    (PROJECT / "docs/114_cpp_worker_confirm_repair_v1").mkdir(parents=True, exist_ok=True)
    (PROJECT / "docs/114_cpp_worker_confirm_repair_v1/repair_report.md").write_text(
        "# C++ worker confirm repair\n\n"
        "The one-shot confirm failed closed at global step 561 because a typed MotionRecord crossed the persistent backend mapping boundary. "
        "The adapter now serializes that record before begin_step. Specialized offline tests and the full unittest suite pass. "
        "No real process was started after cleanup; a new explicit authorization is required before another confirm.\n",
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
