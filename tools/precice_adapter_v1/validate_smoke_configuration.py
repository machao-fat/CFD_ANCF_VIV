"""Validate the isolated single-slice preCICE smoke configuration without running it."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "tools" / "precice_adapter_v1" / "templates" / "single_slice_smoke"
OUT = ROOT / "results" / "272_precice_single_slice_smoke_config_v1"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    xml_path = CONFIG / "precice-config.xml"
    dict_path = CONFIG / "preciceDict"
    contract_path = CONFIG / "ancf_participant_contract.json"
    root = ET.parse(xml_path).getroot()
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    dictionary = dict_path.read_text(encoding="utf-8")
    required_xml = ["Displacement", "Force", "Structure", "Fluid", "Structure-Mesh", "Fluid-Mesh", "nearest-neighbor", "0.00125"]
    required_dict = ["preciceConfig", "participant", "interfaces", "readData", "writeData", "Displacement", "Force"]
    checks = {
        "xml_well_formed": root.tag == "precice-configuration",
        "xml_required_tokens": all(token in xml_path.read_text(encoding="utf-8") for token in required_xml),
        "openfoam_dict_required_tokens": all(token in dictionary for token in required_dict),
        "contract_schema": contract.get("schema_version") == 1,
        "contract_no_cfd": all(contract.get(name) is True for name in ("no_cfd", "no_correction", "no_openfoam", "no_wsl")),
        "contract_scope": contract.get("slice_count") == 1 and contract.get("max_steps") == 8,
        "contract_dt": contract.get("coupling_dt_s") == 0.00125,
    }
    process_counts = {"matlab": 0, "openfoam": 0, "wsl_cfd": 0, "cfd": 0, "precice_participant": 0}
    gate = {
        "gate_id": "STAGE4F_D_PRECICE_SINGLE_SLICE_SMOKE_CONFIG_V1_GATE",
        "status": "pass" if all(checks.values()) and all(v == 0 for v in process_counts.values()) else "do_not_pass",
        "scope": "configuration-only; templates are not solver inputs until explicitly copied into a fresh authorized runtime",
        "checks": checks,
        "files": {name: str(CONFIG / name) for name in ("precice-config.xml", "preciceDict", "ancf_participant_contract.json")},
        "real_process_counts": process_counts,
        "authorization_required": "single-slice fixed/prescribed-motion smoke",
        "forbidden": ["three-slice", "long-time VIV", "E5-C", "formal statistics"],
    }
    (OUT / "stage4f_d_precice_single_slice_smoke_config_v1_gate.json").write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"gate": gate["status"], "checks": checks, "process_counts": process_counts}, ensure_ascii=False))
    return 0 if gate["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
