"""Create a fresh, offline step-0 initialization package."""
from __future__ import annotations
import hashlib
import json
import re
import shutil
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
MESH_TEMPLATE = PROJECT / "cases/openfoam/stage4f_lowre_three_slice_preflight/run_20260817/cases/slice_0000"
DICT_TEMPLATE = PROJECT / "cases/openfoam/stage4f_c_case_initialization_repair_v1/C/cases/slice_0000"
CASE_ROOT = PROJECT / "cases/openfoam/stage4f_d_fresh_initialization_v2/run_20260827_retry1/cases"
RUNTIME_ROOT = PROJECT / "runtime/stage4f_d_fresh_initialization_v2/run_20260827_retry1"
RESULT_ROOT = PROJECT / "results/236_cpp_worker_to70s_fresh_initialization_v2"
DOC_ROOT = PROJECT / "docs/236_cpp_worker_to70s_fresh_initialization_v2"

CONTRACT = {
    "schema_version": "0.2.1",
    "stage_id": "stage4f_d_cpp_worker_to70s_fresh_initialization_v2",
    "run_id": "fresh_init_20260827_retry1",
    "case_id": "stage4f_lowre_v2_1_fresh_3slice",
    "step": 0, "time_s": 0.0, "integer_tick": 0,
    "delta_t_s": 0.00125, "slices": 3,
    "s_ref_m": [8.333333333333334, 25.0, 41.66666666666667],
    "slice_length_m": 16.666666666666668,
    "cfd": {"diameter_m": 1.0, "freestream_mps": 1.0, "rho_kgpm3": 1000.0, "nu_m2ps": 0.01},
    "ancf": {"length_m": 50.0, "outer_diameter_m": 1.0, "inner_diameter_m": 0.9,
             "youngs_modulus_pa": 3227125779.2218256, "top_tension_n": 2179104.0029808935,
             "n_elem": 16, "beta": 0.01},
    "initialization_policy": "uniform_freestream_plus_ancf_static_equilibrium",
    "required_fields": ["U", "Uf", "meshPhi", "p", "phi"],
    "real_process_starts": {"MATLAB": 0, "OpenFOAM": 0, "WSL": 0, "CFD": 0},
}

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))

def patch_dictionary(text: str, *, start: str = "0", end: str = "0.00125") -> str:
    text = re.sub(r"(?m)^\s*startTime\s+[^;]+;", f"startTime      {start};", text)
    text = re.sub(r"(?m)^\s*endTime\s+[^;]+;", f"endTime         {end};", text)
    text = re.sub(r"(?m)^\s*stepOffset\s+[^;]+;", "stepOffset     0;", text)
    text = re.sub(r"(?m)^\s*couplingDeltaT\s+[^;]+;", "        couplingDeltaT 0.00125;", text)
    return text

def surface_field(name: str, dimensions: str, value: str) -> str:
    field_class = "surfaceVectorField" if name == "Uf" else "surfaceScalarField"
    return f"""/*--------------------------------*- C++ -*----------------------------------*\\
  Fresh offline step-0 seed; derived fields are recomputed by OpenFOAM.
\\*---------------------------------------------------------------------------*/
FoamFile
{{
    format      ascii;
    class       {field_class};
    location    "0";
    object      {name};
}}

dimensions      {dimensions};
internalField   uniform {value};

boundaryField
{{
    front     {{ type empty; }}
    back      {{ type empty; }}
    lower     {{ type symmetryPlane; }}
    outlet    {{ type calculated; }}
    upper     {{ type symmetryPlane; }}
    inlet     {{ type calculated; }}
    cylinder  {{ type calculated; }}
}}
"""

def reference_q() -> tuple[list[float], list[float], list[float]]:
    q: list[float] = []
    for node in range(17):
        q.extend([0.0, 0.0, 50.0 * node / 16.0, 0.0, 0.0, 1.0])
    return q, [0.0] * len(q), [0.0] * len(q)

def main() -> int:
    for required in (MESH_TEMPLATE, DICT_TEMPLATE):
        if not required.is_dir():
            raise RuntimeError(f"missing template: {required}")
    if any(path.exists() for path in (CASE_ROOT, RUNTIME_ROOT, RESULT_ROOT, DOC_ROOT)):
        raise RuntimeError("refusing to overwrite an existing Stage 236 destination")
    copied: list[str] = []
    for sid in range(3):
        target = CASE_ROOT / f"slice_{sid:04d}"
        target.mkdir(parents=True)
        shutil.copytree(MESH_TEMPLATE / "constant", target / "constant")
        shutil.copytree(DICT_TEMPLATE / "system", target / "system")
        (target / "0").mkdir()
        for name in ("U", "p", "motionScale"):
            shutil.copy2(MESH_TEMPLATE / ("0/" + name), target / ("0/" + name))
        for rel in ("system/controlDict", "constant/dynamicMeshDict"):
            path = target / rel
            path.write_text(patch_dictionary(path.read_text(encoding="utf-8")), encoding="utf-8")
        (target / "0/phi").write_text(surface_field("phi", "[0 3 -1 0 0 0 0]", "0"), encoding="utf-8")
        (target / "0/meshPhi").write_text(surface_field("meshPhi", "[0 3 -1 0 0 0 0]", "0"), encoding="utf-8")
        (target / "0/Uf").write_text(surface_field("Uf", "[0 1 -1 0 0 0 0]", "(1 0 0)"), encoding="utf-8")
        config = dict(CONTRACT)
        config.update({"slice_id": sid, "case_id": f"{CONTRACT['case_id']}_slice_{sid:04d}",
                       "s_ref_m": CONTRACT["s_ref_m"][sid], "case_root": str(target)})
        write_json(target / "multi_slice_case_config.json", config)
        copied.extend(str(path.relative_to(target)).replace("\\", "/") for path in target.rglob("*") if path.is_file())
    q, qdot, qddot = reference_q()
    RUNTIME_ROOT.mkdir(parents=True)
    write_json(RUNTIME_ROOT / "ancf_t0_reference_state.json", {
        "schema_version": "ancf-t0-reference-v1", "step": 0, "time_s": 0.0, "integer_tick": 0,
        "q": q, "qdot": qdot, "qddot": qddot, "equilibrated": False,
        "note": "Straight reference only; authoritative MATLAB static equilibrium is still required.",
    })
    # The legacy Stage 236 package is retained as read-only evidence.  New
    # initialization must use the standalone C++ kernel initializer; do not
    # emit a MATLAB script or imply that a MATLAB state is authoritative.
    write_json(RUNTIME_ROOT / "cpp_initializer_contract.json", {
        "initializer": "cfd_ancf_cpp_state_initializer",
        "source": "src/coupling/cpp_worker_persistent_ipc_v1/ancf_state_initializer.cpp",
        "output": "ancf_t0_state_cpp.json",
        "step": 0, "time_s": 0.0, "integer_tick": 0,
        "equilibrated": False,
        "note": "Reference state only until a C++ static-equilibrium entry is explicitly qualified.",
    })
    manifest = {
        "stage_id": CONTRACT["stage_id"], "run_id": CONTRACT["run_id"], "contract": CONTRACT,
        "case_root": str(CASE_ROOT), "runtime_root": str(RUNTIME_ROOT),
        "copied_files": sorted(copied),
        "field_status": {f"slice_{sid:04d}": {field: True for field in CONTRACT["required_fields"]} for sid in range(3)},
        "ancf_state": {"reference_present": True, "authoritative_equilibrium_present": False},
        "gate": "STAGE4F_D_FRESH_INITIALIZATION_PACKAGE_V1_GATE: do_not_pass",
        "reason": "C++ reference state is available, but no C++ static-equilibrium state has been qualified; no solver was started.",
        "real_process_starts": CONTRACT["real_process_starts"], "owned_residual": 0, "old_artifacts_modified": False,
    }
    write_json(RUNTIME_ROOT / "initialization_manifest.json", manifest)
    write_json(RESULT_ROOT / "fresh_initialization_package.json", {
        **manifest, "file_sha256": {
            str(path.relative_to(PROJECT)).replace("\\", "/"): sha256(path)
            for path in CASE_ROOT.rglob("*") if path.is_file()
        },
    })
    DOC_ROOT.mkdir(parents=True)
    (DOC_ROOT / "fresh_initialization_report.md").write_text(
        "# Stage 236 fresh initialization package\n\n"
        "- Three new cases were materialized from the matching mesh and uniform U/p template.\n"
        "- phi, Uf, and meshPhi are explicit zero-time seed files for solver-side derivation.\n"
        "- A straight ANCF reference vector must be generated by the standalone C++ initializer; it is audit-only until static equilibrium is qualified.\n"
        "- No MATLAB, OpenFOAM, WSL, or CFD process was started.\n"
        "- Gate: STAGE4F_D_FRESH_INITIALIZATION_PACKAGE_V1_GATE: do_not_pass until ancf_t0_state.mat is produced and audited.\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "generated", "case_root": str(CASE_ROOT), "runtime_root": str(RUNTIME_ROOT), "gate": manifest["gate"]}, ensure_ascii=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
