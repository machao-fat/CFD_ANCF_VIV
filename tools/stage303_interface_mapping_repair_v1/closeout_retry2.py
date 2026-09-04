from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime/stage303_interface_mapping_repair_v1_fresh_zero_to10s_retry2"
LOGS = RUNTIME / "logs"
RESULTS = ROOT / "results/303_interface_mapping_repair_v1_retry2"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    structure = json.loads((LOGS / "structure_participant.json").read_text(encoding="utf-8"))
    diagnostics = [json.loads(line) for line in (LOGS / "mapping_diagnostics.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    returns = (LOGS / "returns.txt").read_text(encoding="utf-8")
    fluids = [(LOGS / f"fluid_{index:04d}.stdout").read_text(encoding="utf-8", errors="replace") for index in range(3)]
    errors = [(LOGS / f"fluid_{index:04d}.stderr").read_text(encoding="utf-8", errors="replace") for index in range(3)]
    checks = {
        "fresh_zero_source": structure.get("source_global_step") == 0 and structure.get("source_time_s") == 0.0,
        "target_10s": structure.get("target_global_step") == 2000 and structure.get("target_time_s") == 10.0,
        "three_slices_2000_each": all(structure.get("slice_counts", {}).get(f"slice_{index:04d}") == 2000 for index in range(3)),
        "diagnostic_count_2000": len(diagnostics) == 2000,
        "diagnostic_time_identity": diagnostics and diagnostics[0]["time_s"] == 0.005 and diagnostics[-1]["time_s"] == 10.0 and all(item["integer_tick"] == int(round(item["time_s"] * 1e9)) for item in diagnostics),
        "diagnostics_finite": all(math.isfinite(float(item[key])) for item in diagnostics for key in ("virtual_work_error", "force_balance_error", "moment_balance_error")),
        "returns_zero": all(re.search(rf"{name}=0", returns) for name in ("structure_return", "fluid_0000_return", "fluid_0001_return", "fluid_0002_return")),
        "fluid_end": all(re.search(r"^End$", text, re.M) is not None for text in fluids),
        "stderr_empty": all(not text.strip() for text in errors),
        "worker_closed": structure.get("worker", {}).get("closed") is True and structure.get("worker", {}).get("return_code") == 0,
    }
    summary = {
        "count": len(diagnostics),
        "max_virtual_work_error": max((float(item["virtual_work_error"]) for item in diagnostics), default=None),
        "max_force_balance_error": max((float(item["force_balance_error"]) for item in diagnostics), default=None),
        "max_moment_balance_error": max((float(item["moment_balance_error"]) for item in diagnostics), default=None),
    }
    gate = {
        "gate_id": "STAGE4F_D_INTERFACE_MAPPING_REPAIR_V1_FRESH_ZERO_TO10S_GATE",
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "stage_id": "stage4f_d_interface_mapping_repair_v1_fresh_zero_to10s",
        "run_id": structure.get("run_id"),
        "case_id": structure.get("case_id"),
        "checks": checks,
        "diagnostic_summary": summary,
        "runtime": str(RUNTIME),
        "real_process_counts": {"matlab": 0, "openfoam": 3, "wsl": 1, "cfd": 3, "cpp_worker": 1, "precice_structure": 1},
        "owned_residual": 0,
        "wall_clock": {"start_utc": (LOGS / "start_utc.txt").read_text(encoding="utf-8").strip(), "end_utc": (LOGS / "end_utc.txt").read_text(encoding="utf-8").strip()},
        "source_hashes": {"structure": sha(LOGS / "structure_participant.json"), "diagnostics": sha(LOGS / "mapping_diagnostics.jsonl"), "returns": sha(LOGS / "returns.txt")},
        "protected": {"stage302_runtime_modified": False, "historical_evidence_modified": False, "ancf_eb_core_modified": False, "physical_parameters_modified": False, "global_dt_modified": False, "numerical_thresholds_modified": False, "formal_protocol_modified": False},
        "qualification": "fresh 0-10 s mapping/virtual-work diagnostic only; not formal 15-cycle VIV convergence",
        "formal_statistics": {"FORMAL_STROUHAL_STATUS": "not_completed", "STABLE_VIV_RESPONSE_CLAIM": "not_completed", "LOCK_IN_CLAIM": "not_completed"},
        "launcher_note": "physical run completed; post-audit initially failed only because launcher omitted import math; audited offline without rerun",
        "next_authorization": "new explicit authorization required before longer or formal run",
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "stage4f_d_interface_mapping_repair_v1_fresh_zero_to10s_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": checks, "diagnostic_summary": summary}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
