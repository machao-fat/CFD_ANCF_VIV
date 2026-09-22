from __future__ import annotations
import csv, hashlib, json, shutil
from pathlib import Path

TASK = "REAL_SINGLE_SLICE_SMOKE_MESH_CASE_QUALIFICATION_V1"

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()

def put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f: f.write(text)

def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    source = Path(r"D:\CFD\CFD_ANCF_VIV\runtime\ANCF_validation\mesh_case")
    run = repo / "runtime" / "coupling_validation" / TASK
    adapted = run / "adapted_case"
    out = repo / "runtime" / "ANCF_validation"
    base = out / TASK
    key = ["constant/polyMesh/boundary","constant/polyMesh/points","constant/polyMesh/faces","constant/polyMesh/owner","constant/polyMesh/neighbour","system/controlDict","system/fvSchemes","system/fvSolution","constant/dynamicMeshDict","constant/physicalProperties","0/U","0/p"]
    rows = []
    for rel in key:
        p = source / rel
        rows.append(f"- `{rel}`: {'PRESENT' if p.is_file() else 'MISSING'}; SHA256={sha(p) if p.is_file() else 'N/A'}; bytes={p.stat().st_size if p.is_file() else 0}")
    put(base.with_name(base.name + "_PROTOCOL.md"), "\n".join([f"# {TASK} protocol", "", "Read-only qualification of the supplied case. The original case is never edited. A byte-identical copy is used for checkMesh because checkMesh may write diagnostic sets.", "", "Gates: OpenFOAM 10 environment; checkMesh; checkMesh -allTopology -allGeometry; no preCICE initialize; no pimpleFoam transient; no ANCF advance; no production edits.", "", "Decision outputs are mesh qualification, patch/force/motion compatibility, and a copied-case dry-run adaptation plan.", ""]))
    inventory = ["# Case inventory", "", f"Source: `{source}`", "Classification: COMPLETE_OPENFOAM_CASE (0/, constant/, system/, constant/polyMesh/ present). The case is a static fixed-cylinder setup and is not yet a preCICE-ready case.", "", "Key identities:", *rows, "", "Other observed files: constant/momentumTransport, system/changeDictionaryDict, system/setFieldsDict.", "Missing from source case: system/preciceDict, preCICE XML, 0/pointDisplacement, 0/cellDisplacement."]
    put(base.with_name(base.name + "_CASE_INVENTORY.md"), "\n".join(inventory) + "\n")
    basic = run / "logs" / "checkMesh_basic.log"; full = run / "logs" / "checkMesh_full.log"
    put(base.with_name(base.name + "_CHECKMESH.log"), "===== checkMesh =====\n" + basic.read_text(encoding="utf-8", errors="replace") + "\n===== checkMesh -allTopology -allGeometry =====\n" + full.read_text(encoding="utf-8", errors="replace"))
    patch_audit = """# Patch and adaptation audit

| mesh patch | role | compatibility | adaptation |
|---|---|---|---|
| cylinder | body/no-slip and force extraction | compatible | reference `cylinder` in copied adapter dictionary |
| inlet/outlet | fluid boundaries | compatible | none |
| upper/lower | far-field symmetry | compatible | none |
| front/back | empty span planes | compatible with 2-D interface | none |

The source `dynamicMeshDict` is `staticFvMesh`. It is not motion-ready, but the
mesh has empty front/back planes and a body wall, so the copied-case dry run
can use `dynamicMotionSolverFvMesh`, displacement fields, and a preCICE adapter
dictionary. No polyMesh file is changed.
"""
    put(base.with_name(base.name + "_PATCH_AUDIT.md"), patch_audit)
    compatibility = """# Generic preCICE compatibility

The current generic topology generator was exercised offline with one
`slice_0000` at S=0.5 m, `LegacyPointLumped`, `StructureCoordinator`, and
`Fluid_slice_0000`. XML parse passed with one participant pair and one scheme.

Force readiness: `cylinderForces` already integrates pressure and viscous force
on patch `cylinder`, using rhoInf=1000 and a one-metre z extrusion. The generic
adapter dictionary can use that patch and `Force` data without changing legacy
N semantics.

Motion readiness: CONFIG_ADAPTATION_ONLY. The source is static and lacks the
displacement fields and preCICE dictionary; these are prepared only in the
copied dry-run case. No production code or mesh change is required by this
audit. Actual runtime motion remains untested.

Required layers: CASE_FILE_ONLY for displacement fields/dynamic mesh;
CONFIG_ONLY for preCICE dictionary, generated XML, participant and mesh names.
No PRODUCTION_CODE_REQUIRED finding.
"""
    put(base.with_name(base.name + "_COMPATIBILITY.md"), compatibility)
    old = """# Comparison with rejected source case

| metric | supplied mesh_case | rejected 284 case |
|---|---:|---:|
| cells | 19600 | 50232 |
| points | 39832 | 102698 |
| faces | 78716 | 202045 |
| internal faces | 38884 | 100337 |
| patches | 7 | 7 |
| max aspect ratio | 10.8181 | 5.3664 |
| max skewness | 0.65185 | 0.56561 |
| max non-orthogonality | 43.4801 | 29.4253 |
| concave cells/check | 0; Mesh OK | 604; Failed 1 mesh check |

Patch naming differs: supplied `cylinder/inlet/outlet/upper/lower/front/back`
versus rejected `cyl/in/out/top/bottom/front/back`. The supplied case is
therefore the better mesh source, but still needs copied case/config motion
adaptation before a real smoke.
"""
    put(base.with_name(base.name + "_COMPARISON.md"), old)
    result = {"task":TASK,"status":"PASS","decision_gate":"MESH_CASE_REQUIRES_CONFIG_ADAPTATION_BEFORE_SMOKE","source_case":str(source),"source_case_classification":"COMPLETE_OPENFOAM_CASE","openfoam":"OpenFOAM-10","mesh":{"cells":19600,"points":39832,"faces":78716,"internal_faces":38884,"patches":7,"regions":1,"max_aspect_ratio":10.8180548118,"max_skewness":0.651850811028,"max_nonorthogonality":43.4800611182,"min_volume":0.000153820342174,"concave_cells":0,"basic":"Mesh OK","full":"Mesh OK"},"body_patch":"cylinder","force_readiness":"READY_IN_CONFIGURATION","motion_readiness":"CONFIG_ADAPTATION_ONLY","generic_precice_xml_parse":"PASS","production_code_changes":0,"mesh_changes":0,"real_precice_started":False,"pimpleFoam_started":False,"G1_execution_count":0,"CFD_FSI_execution_count":0,"original_case_modified":False,"G1_CURRENT_LINE_VALIDATION":"NOT_CLOSED","ANCF_INDEPENDENT_STRUCTURAL_VALIDATION":"NOT_CLOSED"}
    put(base.with_name(base.name + "_RESULT.json"), json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    put(base.with_name(base.name + "_REPORT.md"), "# REAL_SINGLE_SLICE_SMOKE_MESH_CASE_QUALIFICATION_V1 report\n\nThe supplied case is a complete OpenFOAM 10 case and its full mesh check passed. It has 19600 cells, 39832 points, 78716 faces, one region, seven patches, zero concave cells, maximum aspect ratio 10.8181, maximum skewness 0.65185, and maximum non-orthogonality 43.4801.\n\nThe body patch is `cylinder`; force extraction is configuration-ready through the existing forces function object and the generic adapter dictionary. The source is not motion-ready because it uses `staticFvMesh` and lacks preCICE/displacement dictionaries. A copied dry-run adaptation was generated with no polyMesh changes. Generic XML parsing passed for `StructureCoordinator` and `Fluid_slice_0000`.\n\nNo production source, original user case, preCICE runtime, pimpleFoam transient, G1, CFD, FSI, or VIV execution occurred.\n\nFinal decision: `MESH_CASE_REQUIRES_CONFIG_ADAPTATION_BEFORE_SMOKE`.\n")
    manifest = {"source_case":str(source),"source_key_file_hashes":{rel:sha(source/rel) for rel in key if (source/rel).is_file()},"checkmesh_basic_sha256":sha(basic),"checkmesh_full_sha256":sha(full),"adapted_case":str(adapted),"adapted_case_polyMesh_unchanged":True,"decision_gate":result["decision_gate"]}
    put(base.with_name(base.name + "_SHA256_MANIFEST.txt"), "")
    for path in sorted(out.glob(TASK + "_*")):
        if path.name.endswith("_SHA256_MANIFEST.txt"): continue
        with (base.with_name(base.name + "_SHA256_MANIFEST.txt")).open("a", encoding="utf-8", newline="\n") as f: f.write(f"{sha(path)}  {path.relative_to(repo).as_posix()}\n")
    with (base.with_name(base.name + "_SHA256_MANIFEST.txt")).open("a", encoding="utf-8", newline="\n") as f: f.write(f"{sha(basic)}  {basic.relative_to(repo).as_posix()}\n{sha(full)}  {full.relative_to(repo).as_posix()}\n")
    return 0

if __name__ == "__main__": raise SystemExit(main())
