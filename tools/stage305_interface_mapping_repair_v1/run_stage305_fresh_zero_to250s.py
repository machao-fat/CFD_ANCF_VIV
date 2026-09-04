"""Stage 305: fresh 0 -> 250 s corrected-mapping three-slice run."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

BASE_PATH = Path(__file__).parents[1] / "stage304_interface_mapping_repair_v1" / "run_stage304_fresh_zero_to80s.py"
SPEC = importlib.util.spec_from_file_location("stage304_base_for_stage305", BASE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Stage304 base launcher unavailable")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

BASE.RUNTIME = BASE.ROOT / "runtime/stage305_interface_mapping_repair_v1_fresh_zero_to250s"
BASE.RESULTS = BASE.ROOT / "results/305_interface_mapping_repair_v1"
BASE.PARTICIPANT = BASE.ROOT / "tools/stage304_interface_mapping_repair_v1/ancf_cpp_worker_three_slice_mapped_v1.py"
BASE.RUN_ID = "s305_fresh_zero_to250s_mapping_diag_v1"
BASE.CASE_ID = "c305_fresh_zero_to250s_mapping_diag_v1"
BASE.STEPS = 50000


def main() -> int:
    result = BASE.main()
    gate_path = BASE.RESULTS / "stage4f_d_interface_mapping_repair_v1_fresh_zero_to80s_gate.json"
    if not gate_path.is_file():
        return result
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    gate["gate_id"] = "STAGE4F_D_INTERFACE_MAPPING_REPAIR_V1_FRESH_ZERO_TO250S_GATE"
    gate["stage_id"] = "stage4f_d_interface_mapping_repair_v1_fresh_zero_to250s"
    gate["run_id"] = BASE.RUN_ID
    gate["case_id"] = BASE.CASE_ID
    gate["scope_contract"]["target_step"] = BASE.STEPS
    gate["scope_contract"]["target_time_s"] = BASE.STEPS * BASE.DT
    gate["scope_contract"]["storage"] = "rolling fields + scalar convergence and mapping diagnostics"
    gate["checks"]["committed_50000"] = gate["checks"].pop("committed_16000")
    gate["checks"]["slice_counts_50000"] = gate["checks"].pop("slice_counts_16000")
    gate["checks"]["mapping_diagnostics_50000"] = gate["checks"].pop("mapping_diagnostics_16000")
    gate["qualification"] = "fresh 0-250 s corrected interface mapping with scalar convergence observability; formal convergence determined by the recorded statistical and CFD-quality gates"
    gate["runtime"] = str(BASE.RUNTIME)
    gate_path = BASE.RESULTS / "stage4f_d_interface_mapping_repair_v1_fresh_zero_to250s_gate.json"
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "target_time_s": BASE.STEPS * BASE.DT, "wall_clock_s": gate["wall_clock"].get("elapsed_s"), "checks": gate["checks"]}, ensure_ascii=False))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
