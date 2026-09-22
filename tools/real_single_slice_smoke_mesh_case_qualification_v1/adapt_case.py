from __future__ import annotations
import argparse, json, shutil
from pathlib import Path
from coupling.arbitrary_n_live_orchestration_v1 import build_slice_manifest, generate_precice_xml, inspect_precice_xml

def put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream: stream.write(text)

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--source", required=True); parser.add_argument("--target", required=True); args = parser.parse_args()
    source, target = Path(args.source).resolve(), Path(args.target).resolve()
    if target.exists(): raise SystemExit(f"target exists: {target}")
    shutil.copytree(source, target)
    config = {"case_id":"mesh_case_legacy_single_slice_dry_run","length_m":1.0,"coupling":{"mode":"LegacyPointLumped","placement":"explicit","positions_m":[0.5],"slice_ids":["slice_0000"],"slice_length_m":[1.0],"unit_span_m":[1.0],"active_start_m":0.0,"active_end_m":1.0,"force_representation":"integrated_slice_force_N"},"interfaces":{"structure_participant":"StructureCoordinator","fluid_participant_prefix":"Fluid_","structure_mesh_prefix":"Structure-Mesh-","fluid_mesh_prefix":"Fluid-Mesh-","openfoam_case_prefix":"smoke_","force_data":"Force","motion_data":"Displacement"}}
    manifest = build_slice_manifest(config); item = manifest.slices[0]
    exchange = str((target / "precice-sockets").resolve()).replace("\\", "/")
    xml = generate_precice_xml(manifest, time_window_s=0.005, max_time_s=0.015, exchange_directory=exchange)
    topology = inspect_precice_xml(xml, manifest)
    put(target / "precice-config.xml", xml + "\n")
    put(target / "system" / "preciceDict", "\n".join(['FoamFile { format ascii; class dictionary; location "system"; object preciceDict; }', 'preciceConfig "precice-config.xml";', f"participant {item.fluid_participant};", "modules (FSI);", "FSI { solverType incompressible; rho rho [1 -3 0 0 0 0 0] 1; nu nu [0 2 -1 0 0 0 0] 0.01; namePointDisplacement pointDisplacement; nameCellDisplacement cellDisplacement; nameForce Force; }", f"interfaces {{ Interface1 {{ mesh {item.fluid_mesh}; patches (cylinder); locations faceCenters; readData (Displacement); writeData (Force); }} }}", ""]))
    put(target / "constant" / "dynamicMeshDict", "\n".join(["FoamFile", "{", "    format ascii;", "    class dictionary;", '    location "constant";', "    object dynamicMeshDict;", "}", "dynamicFvMesh dynamicMotionSolverFvMesh;", 'motionSolverLibs ("libfvMotionSolvers.so");', "solver displacementLaplacian;", ""]))
    control = (target / "system" / "controlDict").read_text(encoding="utf-8")
    if "libpreciceAdapterFunctionObject.so" not in control: control = control.replace("application     pimpleFoam;", 'application     pimpleFoam;\nlibs            ("libpreciceAdapterFunctionObject.so");')
    if "preCICE_Adapter" not in control: control = control.replace("functions\n{", "functions\n{\n    preCICE_Adapter\n    {\n        type preciceAdapterFunctionObject;\n    }")
    put(target / "system" / "controlDict", control)
    def field(name: str, kind: str, side: str) -> str:
        lines = ["FoamFile", "{", "    format ascii;", f"    class {kind};", '    location "0";', f"    object {name};", "}", "dimensions [0 1 0 0 0 0 0];", "internalField uniform (0 0 0);", "boundaryField", "{"]
        for patch in ("front", "back"): lines.append(f"    {patch} {{ type empty; }}")
        for patch in ("inlet", "outlet", "upper", "lower"): lines.append(f"    {patch} {{ type {side}; value uniform (0 0 0); }}")
        lines += ["    cylinder { type fixedValue; value uniform (0 0 0); }", "}", ""]
        return "\n".join(lines)
    put(target / "0" / "pointDisplacement", field("pointDisplacement", "pointVectorField", "fixedValue"))
    put(target / "0" / "cellDisplacement", field("cellDisplacement", "volVectorField", "zeroGradient"))
    audit = {"source":str(source),"target":str(target),"polyMesh_changed":False,"manifest":manifest.to_dict(),"topology":topology,"adaptation_files":["precice-config.xml","system/preciceDict","constant/dynamicMeshDict","system/controlDict","0/pointDisplacement","0/cellDisplacement"],"real_coupling_started":False}
    put(target / "qualification_dry_run.json", json.dumps(audit, ensure_ascii=False, indent=2) + "\n")
    return 0

if __name__ == "__main__": raise SystemExit(main())
