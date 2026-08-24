"""Focused validator for Stage 4F-B-A synthetic transient evidence."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "results" / "12_stage4f_transient_certification" / "stage4f_b_a_transient_certification.json"

def main():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    assert data["classification"] == "synthetic_load_diagnostic_only"
    assert data["openfoam_started"] is False and data["viv_claim"] is False
    assert data["parameters"]["nSlices"] == 3
    assert data["parameters"]["nElem_production"] == 16
    assert data["parameters"]["nElem_reference"] == 32
    assert data["restart"]["steps"] == 10
    assert data["coarse"]["steps"] == 10 and data["fine"]["steps"] == 20
    assert data["restart_relative_error"] <= 1e-11
    assert max(data["coarse"]["energy_relative_residual"], data["fine"]["energy_relative_residual"]) <= 1e-3
    assert data["passed"] is True and not any(data["stop_conditions"].values())
    print("stage4f transient certification evidence: PASS")

if __name__ == "__main__":
    main()
