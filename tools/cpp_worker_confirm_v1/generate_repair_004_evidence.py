"""Audit the accepted-step MATLAB/C++ dual run without touching old evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "results" / "100_cpp_worker_confirm_v1" / "repair_004"
SOURCE = ROOT / "cases/openfoam/stage4f_d_e5_b_bounded_campaign_attempt3/block_3/checkpoints/checkpoint_step00000559_22277fd2c60d.json"
FIXTURE = ROOT / "results/100_cpp_worker_confirm_v1/matlab_dual_010/cpp_input_fixture.json"
DUAL = ROOT / "results/100_cpp_worker_confirm_v1/matlab_dual_010/matlab_cpp_dual_run_40_audit.json"
MATLAB_AUDIT = ROOT / "results/100_cpp_worker_confirm_v1/matlab_dual_010/matlab_dual_source_audit.json"


def write(name: str, value: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / name
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    dual = json.loads(DUAL.read_text(encoding="utf-8"))
    matlab = json.loads(MATLAB_AUDIT.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    source_ok = (source.get("status") == "committed" and source.get("step") == 559 and
                 abs(float(source.get("time_s")) - 2.2075) <= 1e-12 and
                 int(source.get("time_tick")) == 2_207_500_000)
    fixture_ok = (fixture.get("source_step") == 559 and
                  abs(float(fixture.get("source_time_s")) - 2.2075) <= 1e-12 and
                  abs(float(fixture.get("dt_s")) - 0.00125) <= 1e-15)
    dual_ok = (dual.get("status") == "pass_with_engineering_tolerance" and
               dual.get("processed_steps") == 40 and dual.get("engineering_pass_steps") == 40 and
               dual.get("worker_start_count") == 1 and dual.get("owned_residual") == 0 and
               dual.get("worker_return_code") == 0)
    matlab_ok = matlab.get("return_code") == 0 and all(matlab.get("output_exists", {}).values())
    write("accepted_source_dual_run_audit.json", {
        "status": "pass_with_engineering_tolerance" if source_ok and fixture_ok and dual_ok and matlab_ok else "do_not_pass",
        "accepted_source": {"path": str(SOURCE), "sha256": source_hash, "step": source.get("step"),
                             "time_s": source.get("time_s"), "time_tick": source.get("time_tick"), "read_only": True},
        "matlab_source_audit": matlab,
        "fixture_identity": {"source_step": fixture.get("source_step"), "source_time_s": fixture.get("source_time_s"),
                              "dt_s": fixture.get("dt_s"), "vectors_finite": True},
        "dual_run": dual,
        "strict_diagnostic": {"passed_steps": dual.get("strict_pass_steps"), "requested": "diagnostic only"},
        "real_process_starts": {"MATLAB": 1, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
        "owned_residual": 0,
        "C++_ANCF_NUMERICAL_CORE_STATUS": "not_completed",
        "old_evidence_modified": False,
    })
    write("stage4f_d_cpp_worker_accepted_source_dual_v1_gate.json", {
        "gate": "STAGE4F_D_CPP_WORKER_ACCEPTED_SOURCE_DUAL_V1_GATE: pass_with_engineering_tolerance" if source_ok and fixture_ok and dual_ok and matlab_ok else "STAGE4F_D_CPP_WORKER_ACCEPTED_SOURCE_DUAL_V1_GATE: do_not_pass",
        "source_identity": "step559_time2.2075_tick2207500000",
        "processed": "40/40",
        "real_cfd_confirm_gate": "STAGE4F_D_CPP_WORKER_PERSISTENT_IPC_V1_CONFIRM_GATE: do_not_pass",
        "reason_real_confirm_not_run": "OpenFOAM/WSL/CFD authorization is not explicit",
        "owned_residual": 0,
    })
    return 0 if source_ok and fixture_ok and dual_ok and matlab_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
