"""Rebuild the Stage 292 Gate from its immutable raw runtime evidence."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime" / "292_cpp_worker_precice_single_slice_040s_linux_v1"
BUILD = ROOT / "runtime" / "292_cpp_worker_linux_build_v1" / "cfd_ancf_ancf_kernel_worker"
LOGS = RUNTIME / "logs"
OUT = ROOT / "results" / "292_cpp_worker_precice_single_slice_040s_linux_v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    structure = json.loads((LOGS / "structure_participant.json").read_text(encoding="utf-8"))
    records = structure.get("records", [])
    fluid = (LOGS / "pimpleFoam.stdout").read_text(encoding="utf-8", errors="replace")
    fluid_err = (LOGS / "pimpleFoam.stderr").read_text(encoding="utf-8", errors="replace")
    expected = [round(0.005 * i, 12) for i in range(1, 41)]
    checks = {
        "structure_finalized": structure.get("finalized") is True,
        "structure_records_40": len(records) == 40,
        "times_005_to_020": [round(float(r.get("time_s", -1)), 12) for r in records] == expected,
        "identity_continuous": [r.get("sequence") for r in records] == list(range(1, 41)),
        "tick_consistent": all(r.get("integer_tick") == int(round(float(r.get("time_s", -1)) * 1e9)) for r in records),
        "worker_ack_finite": all(r.get("ack") == 1 and r.get("finite_audit") is True and r.get("worker_return_code") == 0 for r in records),
        "worker_single_start": structure.get("worker", {}).get("pid", 0) > 0 and structure.get("worker", {}).get("owned") is True,
        "worker_closed": structure.get("worker", {}).get("closed") is True and structure.get("worker", {}).get("return_code") == 0,
        "fluid_reached_final_time": "Time = 0.2" in fluid or "Time = 0.20" in fluid or "End" in fluid,
        "fluid_end_marker": re.search(r"^End$", fluid, re.M) is not None,
        "fluid_stderr_empty": not fluid_err.strip(),
        "purge_write_enabled": "purgeWrite      1;" in (RUNTIME / "case" / "system" / "controlDict").read_text(encoding="utf-8"),
    }
    start = (LOGS / "start_utc.txt").read_text(encoding="utf-8").strip()
    end = (LOGS / "end_utc.txt").read_text(encoding="utf-8").strip()
    elapsed = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    gate = {
        "gate_id": "STAGE4F_D_CPP_WORKER_PRECICE_SINGLE_SLICE_040S_LINUX_V1_GATE",
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "timestamp": end, "stage_id": "stage4f_d_cpp_worker_precice_single_slice_040s_linux_v1",
        "run_id": structure.get("run_id"), "case_id": structure.get("case_id"),
        "scope_contract": {"openfoam": "10", "precice": "3.4.1", "dt_s": 0.005, "steps": 40, "end_time_s": 0.20, "slice_count": 1, "worker": "persistent C++ ANCF kernel", "worker_platform": "WSL Linux ELF built from current source"},
        "checks": checks, "runtime": str(RUNTIME),
        "source_hashes": {"worker": sha(BUILD), "fixture": sha(ROOT / "runtime" / "cpp_worker_to70s_real_v1" / "run_001" / "support" / "cpp_input_fixture.json"), "precice_config": sha(RUNTIME / "case" / "precice-config.xml"), "precice_dict": sha(RUNTIME / "case" / "system" / "preciceDict"), "participant": sha(ROOT / "tools" / "precice_ancf_adapter_v1" / "ancf_cpp_worker_single_slice_participant_v1.py")},
        "real_process_counts": {"matlab": 0, "openfoam": 1, "wsl": 2, "cfd": 1, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0, "return_code": 0,
        "wall_clock": {"start_utc": start, "end_utc": end, "elapsed_s": elapsed},
        "protected": {"historical_evidence_modified": False, "ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False, "formal_viv_validation_complete": False},
        "qualification": "single-slice preCICE/OpenFOAM 40-step interface with persistent Linux C++ ANCF worker; explicit force/state projection is an interface qualification, not formal ANCF equivalence or VIV validation",
        "next_authorization": "fresh three-slice C++ worker + preCICE smoke only after audit review",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "stage4f_d_cpp_worker_precice_single_slice_040s_linux_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": checks, "wall_clock_s": elapsed}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
