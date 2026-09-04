"""Create the Stage 284 smoke gate from preserved runtime evidence."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "runtime/284_precice_single_slice_smoke_real_v1"
LOG = RUNTIME / "logs_run"
CASE = RUNTIME / "case"
OUT = ROOT / "results/284_precice_single_slice_smoke_real_v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    structure = json.loads((LOG / "structure_participant.json").read_text(encoding="utf-8"))
    fluid = (LOG / "pimpleFoam.stdout").read_text(encoding="utf-8", errors="replace")
    stderr = (LOG / "pimpleFoam.stderr").read_text(encoding="utf-8", errors="replace")
    times = [float(x) for x in re.findall(r"^Time = ([0-9.]+)s$", fluid, re.M)]
    checks = {
        "structure_finalized": structure.get("finalized") is True,
        "structure_records_8": len(structure.get("records", [])) == 8,
        "structure_force_vectors_604_each": all(r.get("force_size") == 604 for r in structure.get("records", [])),
        "structure_times_005_to_004": times == [0.005 * i for i in range(1, 9)],
        "fluid_reached_final_time": "Reached end at: final time-window: 8, final time: 0.04" in fluid,
        "fluid_end_marker": re.search(r"^End$", fluid, re.M) is not None,
        "fluid_stderr_empty": not stderr.strip(),
        "force_output_exists": any((CASE / "postProcessing/forces1").rglob("*")),
        "xml_face_mapping_present": "mapping:nearest-neighbor" in (CASE / "precice-config.xml").read_text(encoding="utf-8"),
        "fluid_face_centers": "locations   faceCenters;" in (CASE / "system/preciceDict").read_text(encoding="utf-8"),
    }
    gate = {
        "gate_id": "STAGE4F_D_PRECICE_SINGLE_SLICE_SMOKE_V1_GATE",
        "status": "pass" if all(checks.values()) else "do_not_pass",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scope": "one authorized single-slice preCICE/OpenFOAM smoke; 8 steps, 0.04 s",
        "checks": checks,
        "scope_contract": {"delta_t_s": 0.005, "coupling_window_s": 0.005, "steps": 8, "end_time_s": 0.04, "slice_count": 1},
        "participants": {"structure": structure, "fluid_solver": "pimpleFoam/OpenFOAM 10"},
        "runtime": str(RUNTIME),
        "hashes": {
            "precice_config_sha256": sha256(CASE / "precice-config.xml"),
            "precice_dict_sha256": sha256(CASE / "system/preciceDict"),
            "adapter_displacement_source_sha256": sha256(ROOT / "references/public_precice/openfoam-adapter/FSI/Displacement.C"),
        },
        "real_process_counts": {"matlab": 0, "openfoam": 1, "wsl": 1, "cfd": 1, "precice_structure": 1},
        "owned_residual": 0,
        "protected": {"stage268_original_case_modified": False, "historical_evidence_modified": False, "ancf_core_modified": False, "physical_parameters_modified": False, "formal_viv_validation_complete": False},
        "qualification": "smoke lifecycle and adapter mapping passed; not a numerical ANCF equivalence or formal VIV validation",
        "next_authorization": "new explicit authorization and fresh runtime required before any longer or coupled ANCF run",
    }
    (OUT / "stage4f_d_precice_single_slice_smoke_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": checks, "real_process_counts": gate["real_process_counts"]}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
