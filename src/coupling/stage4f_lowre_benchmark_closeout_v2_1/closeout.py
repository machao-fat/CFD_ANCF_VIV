"""Close the low-Re benchmark after candidate-local static rejection.

This module never changes the stopped v2 evidence.  It promotes only the
independently passing m*=5, beta=0.01 candidate and materializes new 0.2.1
mapping identities for the later real three-slice preflight.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ..multi_slice_mapping.mapping import (
    IDENTITY_R_GL,
    SCHEMA_VERSION,
    RuntimeConfig,
    SliceDefinition,
    SliceManifest,
)
from ..stage4f_lowre_benchmark_design_v2.benchmark import (
    LowReContract,
    combined_record_hash,
    hash_records,
    uniform_slice_geometry,
    write_json,
)
from ..stage4f_lowre_benchmark_design_v2.mapping_audit import generate_mapping_evidence


SELECTED = {"mass_ratio": 5, "beta": 0.01}
REJECTED = {"mass_ratio": 10, "beta": 0.05}
COUNTS = ((3, "three"), (5, "five"), (9, "nine"))


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _result(root: Path) -> Path:
    result = root / "results" / "11_stage4f_lowre_benchmark_design_v2_1"
    result.mkdir(parents=True, exist_ok=True)
    return result


def _v2_paths(root: Path) -> list[Path]:
    folder = root / "results" / "11_stage4f_lowre_benchmark_design_v2"
    return [item for item in folder.rglob("*") if item.is_file()]


def _find(candidates: list[dict[str, Any]], identity: dict[str, Any]) -> dict[str, Any]:
    return next(item for item in candidates if item["mass_ratio"] == identity["mass_ratio"] and item["beta"] == identity["beta"])


def _manifest(count: int, contract: LowReContract) -> SliceManifest:
    _, centers = uniform_slice_geometry(count, contract.L_m)
    width = contract.L_m / count
    return SliceManifest(
        schema_version=SCHEMA_VERSION,
        case_id=f"stage4f_lowre_v2_1_uniform_{count}slice",
        reference_length_m=contract.L_m,
        represented_length_m=contract.L_m,
        R_GL=IDENTITY_R_GL,
        slices=tuple(SliceDefinition(i, center, width, 1.0) for i, center in enumerate(centers)),
    )


def run(root: Path) -> dict[str, Any]:
    root = root.resolve()
    v2 = root / "results" / "11_stage4f_lowre_benchmark_design_v2"
    result = _result(root)
    before = hash_records(_v2_paths(root), root)
    inverse = _read(v2 / "inverse_structure_design.json")
    static = _read(v2 / "static_initialization.json")
    selected = _find(inverse["candidates"], SELECTED)
    rejected = _find(inverse["candidates"], REJECTED)
    rejected_static = next(item for item in static["candidates"] if item["mass_ratio"] == 10 and item["beta"] == 0.05)
    selected_static = next(item for item in static["candidates"] if item["mass_ratio"] == 5 and item["beta"] == 0.01)
    selected_32 = next(item["audit"] for item in selected_static["meshes"] if item["nElem"] == 32)
    rejected_32 = next(item["audit"] for item in rejected_static["meshes"] if item["nElem"] == 32)
    if not selected["production_candidate_passed"] or not selected_32["passes"]:
        raise RuntimeError("selected candidate is not admissible")
    if not rejected_static or not rejected_32["large_range_negative_tension"]:
        raise RuntimeError("expected rejected-candidate evidence is absent")
    contract = LowReContract()
    selection = {
        "status": "selected_candidate_admissible",
        "stop_rule_correction": "large_range_negative_tension rejects only the affected candidate; global stop occurs only when no admissible candidate remains or the selected candidate fails",
        "selected_candidate": selected,
        "rejected_candidates": [{
            "mass_ratio": 10, "beta": 0.05,
            "reason": "large_range_negative_tension",
            "minimum_tension_N": rejected_32["minimum_tension_N"],
            "negative_tension_fraction": rejected_32["negative_tension_fraction"],
        }],
        "selected_static_nElem32": selected_32,
        "structure_mesh_role": {"nElem_8": "diagnostic", "nElem_16": "production", "nElem_32": "reference"},
        "openfoam_started": False,
    }
    write_json(result / "selected_structure_candidate_v2_1.json", selection)
    manifests: dict[str, Any] = {}
    for count, label in COUNTS:
        manifest = _manifest(count, contract)
        config = RuntimeConfig(
            schema_version=SCHEMA_VERSION, case_id=manifest.case_id, dt_s=0.0025,
            timeout_s=30.0, start_time_s=0.0, coupling_iteration=0,
            coupling_scheme="explicit_weak", slice_manifest_sha256=manifest.slice_manifest_sha256,
        )
        payload = {"manifest": manifest.to_dict(), "runtime_config": config.to_dict(),
                   "flow_contract": {"U_i_mps": 1.0, "Re_i": 100.0, "unit_span_m": 1.0,
                                     "R_GL": [list(row) for row in IDENTITY_R_GL]},
                   "not_a_CFD_or_VIV_result": True}
        write_json(result / f"{label}_slice_protocol_0_2_1.json", payload)
        manifests[label] = payload
    mapping = generate_mapping_evidence(result)
    after = hash_records(_v2_paths(root), root)
    audit = {"status": "passed" if before == after else "failed", "v2_file_count": len(before),
             "combined_sha256_before": combined_record_hash(before), "combined_sha256_after": combined_record_hash(after),
             "mismatches": [item for item in before if item not in after] + [item for item in after if item not in before]}
    write_json(result / "v2_evidence_readonly_hash_audit.json", audit)
    gate = {
        "status": "passed" if audit["status"] == "passed" and mapping["virtual_work"]["status"] == "passed" else "failed",
        "gate_passed": audit["status"] == "passed" and mapping["virtual_work"]["status"] == "passed",
        "selected_candidate": SELECTED, "rejected_candidate": REJECTED,
        "negative_tension_stop_semantics": "candidate_local_rejection",
        "mapping_virtual_work_max": mapping["virtual_work"]["maximum_absolute_or_relative_error"],
        "real_three_slice_low_re_fsi_entry_recommendation": "建议进入",
        "real_five_slice_entry_recommendation": "建议不进入",
        "real_nine_slice_entry_recommendation": "建议不进入",
        "openfoam_started": False,
        "free_viv_claim": False,
    }
    write_json(result / "stage4f_a_v2_1_gate_candidate.json", gate)
    docs = root / "docs"
    docs.joinpath("11_stage4f_a_v2_1_candidate_resolution.md").write_text(
        "# Stage 4F-A-v2.1 Candidate Resolution\n\n"
        "`m*=10, beta=0.05` is rejected because its static solution has a 9.78% negative-tension region. "
        "This is a candidate-level failure. The independently admissible `m*=5, beta=0.01` candidate is selected for the low-Re method benchmark. "
        "No OpenFOAM case was started.\n", encoding="utf-8")
    docs.joinpath("11_stage4f_a_v2_1_mapping_closeout.md").write_text(
        "# Stage 4F-A-v2.1 Mapping Closeout\n\n"
        "New 0.2.1 3/5/9-slice manifests and runtime configurations use a 50 m vertical reference line, `U=1 m/s`, `Re=100`, `unit_span=1 m`, and `R_GL=I`. "
        "The production mapping functions perform H interpolation and H-transpose load mapping. The evidence is synthetic only; it is not CFD, free-VIV, or experimental validation.\n", encoding="utf-8")
    return gate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.root), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
