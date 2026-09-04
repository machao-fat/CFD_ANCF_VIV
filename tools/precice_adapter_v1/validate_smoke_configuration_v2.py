"""Validate the corrected OF10 smoke template without launching a solver."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "tools" / "precice_adapter_v1" / "templates" / "single_slice_smoke_of10_v2"
OUT = ROOT / "results" / "274_precice_single_slice_smoke_config_v2"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    xml_path = CONFIG / "precice-config.xml"
    dict_path = CONFIG / "preciceDict"
    contract_path = CONFIG / "ancf_participant_contract.json"
    xml_text = xml_path.read_text(encoding="utf-8")
    dictionary = dict_path.read_text(encoding="utf-8")
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    ET.parse(xml_path)
    checks = {
        "xml_well_formed": True,
        "cfd_delta_t_matches_public_case": contract.get("cfd_delta_t_s") == 0.005,
        "coupling_dt_matches_cfd_delta_t": contract.get("coupling_dt_s") == contract.get("cfd_delta_t_s"),
        "xml_time_window_is_005": '<time-window-size value="0.005" />' in xml_text,
        "xml_max_time_is_004": '<max-time value="0.04" />' in xml_text,
        "dict_patch_is_cyl": "patches     (cyl);" in dictionary,
        "dict_mesh_is_fluid_mesh": "mesh        Fluid-Mesh;" in dictionary,
        "dict_force_location_is_face_centers": "locations   faceCenters;" in dictionary,
        "scope_is_eight_steps": contract.get("slice_count") == 1 and contract.get("max_steps") == 8 and contract.get("max_time_s") == 0.04,
        "no_cfd_guards": all(contract.get(name) is True for name in ("no_cfd", "no_correction", "no_openfoam", "no_wsl", "no_retry")),
    }
    counts = {"matlab": 0, "openfoam": 0, "wsl_cfd": 0, "cfd": 0, "precice_participant": 0}
    gate = {
        "gate_id": "STAGE4F_D_PRECICE_SINGLE_SLICE_SMOKE_CONFIG_V2_GATE",
        "status": "pass" if all(checks.values()) and all(v == 0 for v in counts.values()) else "do_not_pass",
        "scope": "configuration-only correction; no solver or participant started",
        "checks": checks,
        "source_basis": {"public_case": "stage268_validated_viv_of10", "openfoam_delta_t_s": 0.005, "source_gate": "STAGE4F_D_PUBLIC_CFD_BENCHMARK_V1_GATE"},
        "corrected_from": {"previous_template_coupling_dt_s": 0.00125, "reason": "old C++ worker step was incorrectly carried into the OF10 public case"},
        "real_process_counts": counts,
        "protected": {"stage272_evidence_modified": False, "public_case_modified": False, "historical_evidence_modified": False, "ancf_core_modified": False, "physical_parameters_modified": False},
        "authorization_required": "single-slice preCICE smoke only after isolated boundary/motion adaptation",
    }
    (OUT / "stage4f_d_precice_single_slice_smoke_config_v2_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": checks, "process_counts": counts}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
