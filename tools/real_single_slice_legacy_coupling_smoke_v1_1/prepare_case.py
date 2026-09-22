"""Prepare the isolated V1.1 Ns=1 case; never edits the source case."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import xml.etree.ElementTree as ET

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from coupling.arbitrary_n_live_orchestration_v1 import (  # noqa: E402
    build_slice_manifest,
    generate_openfoam_launch_plan,
    generate_precice_xml,
    inspect_precice_xml,
)

DT_S = 0.005
MAX_TIME_S = 0.015
KEY_FILES = (
    "constant/polyMesh/boundary",
    "constant/polyMesh/points",
    "constant/polyMesh/faces",
    "constant/polyMesh/owner",
    "constant/polyMesh/neighbour",
    "system/controlDict",
    "system/fvSchemes",
    "system/fvSolution",
    "constant/dynamicMeshDict",
    "constant/physicalProperties",
    "0/U",
    "0/p",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def precice_dict(participant: str, mesh: str) -> str:
    return f'''FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    location    "system";
    object      preciceDict;
}}

preciceConfig "precice-config.xml";
participant {participant};
modules (FSI);

FSI
{{
    solverType              incompressible;
    rho                     rho [1 -3 0 0 0 0 0] 1000;
    nu                      nu [0 2 -1 0 0 0 0] 0.01;
    namePointDisplacement   unused;
    nameCellDisplacement    cellDisplacement;
    nameForce               Force;
}}

interfaces
{{
    Interface1
    {{
        mesh        {mesh};
        patches     (cylinder);
        locations   faceCenters;
        readData    (Displacement);
        writeData   (Force);
    }}
}}
'''


def dynamic_mesh_dict() -> str:
    return '''FoamFile
{
    format      ascii;
    class       dictionary;
    object      dynamicMeshDict;
}

dynamicFvMesh       dynamicMotionSolverFvMesh;
motionSolverLibs    ("libfvMotionSolvers.so");
solver              displacementLaplacian;
'''


def displacement_field(name: str, cls: str, outer_type: str) -> str:
    lines = [
        "FoamFile", "{", "    version     2.0;", "    format      ascii;",
        f"    class       {cls};", '    location    "0";', f"    object      {name};", "}",
        "", "dimensions      [0 1 0 0 0 0 0];", "", "internalField   uniform (0 0 0);", "",
        "boundaryField", "{",
    ]
    for patch in ("front", "back"):
        lines += [f"    {patch}", "    {", "        type            empty;", "    }"]
    for patch in ("inlet", "outlet", "upper", "lower"):
        lines += [f"    {patch}", "    {", f"        type            {outer_type};"]
        if outer_type == "fixedValue":
            lines.append("        value           uniform (0 0 0);")
        lines.append("    }")
    lines += [
        "    cylinder", "    {", "        type            fixedValue;",
        "        value           uniform (0 0 0);", "    }", "}", "",
    ]
    return "\n".join(lines)


def adapted_control_dict(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^startFrom\s+latestTime\s*;", "startFrom       startTime;", text)
    text = re.sub(r"(?m)^endTime\s+[^;]+;", f"endTime         {MAX_TIME_S:.3f};", text)
    text = re.sub(r"(?m)^deltaT\s+[^;]+;", f"deltaT          {DT_S:.3f};", text)
    if "libpreciceAdapterFunctionObject.so" not in text:
        text = text.replace(
            "application     pimpleFoam;",
            'application     pimpleFoam;\n\nlibs            ("libpreciceAdapterFunctionObject.so");',
            1,
        )
    if "preCICE_Adapter" not in text:
        marker = "functions\n{"
        replacement = (
            "functions\n{\n"
            "    preCICE_Adapter\n"
            "    {\n"
            "        type            preciceAdapterFunctionObject;\n"
            "    }\n"
        )
        if marker not in text:
            raise RuntimeError("source controlDict lacks a functions dictionary")
        text = text.replace(marker, replacement, 1)
    return text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-case", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--exchange-directory-wsl", required=True)
    args = parser.parse_args()
    source = Path(args.source_case).resolve()
    runtime = Path(args.runtime_root).resolve()
    target = runtime / "case" / "smoke_slice_0000"
    if not source.is_dir():
        raise SystemExit(f"source case does not exist: {source}")
    if runtime.exists():
        if not target.is_dir() or (runtime / "manifest.json").exists():
            raise SystemExit(f"V1.1 runtime already exists; refusing overwrite: {runtime}")
    else:
        runtime.mkdir(parents=True)
    source_hashes = {rel: sha256(source / rel) for rel in KEY_FILES}
    if not target.exists():
        shutil.copytree(source, target)

    config = {
        "case_id": "real_single_slice_legacy_coupling_smoke_v1_1",
        "length_m": 10.0,
        "coupling": {
            "mode": "LegacyPointLumped",
            "placement": "explicit",
            "positions_m": [5.0],
            "slice_ids": ["slice_0000"],
            "slice_length_m": [1.0],
            "unit_span_m": [1.0],
            "active_start_m": 0.0,
            "active_end_m": 10.0,
            "force_representation": "integrated_slice_force_N",
            "endpoint_policy": "NearestConstant",
        },
        "interfaces": {
            "structure_participant": "StructureCoordinator",
            "fluid_participant_prefix": "Fluid_",
            "structure_mesh_prefix": "Structure-Mesh-",
            "fluid_mesh_prefix": "Fluid-Mesh-",
            "openfoam_case_prefix": "smoke_",
            "force_data": "Force",
            "motion_data": "Displacement",
        },
    }
    manifest = build_slice_manifest(config)
    item = manifest.slices[0]
    exchange = args.exchange_directory_wsl.replace("\\", "/")
    xml = generate_precice_xml(
        manifest, time_window_s=DT_S, max_time_s=MAX_TIME_S,
        exchange_directory=exchange,
    )
    topology = inspect_precice_xml(xml, manifest)
    ET.fromstring(xml)
    plan = generate_openfoam_launch_plan(
        manifest, template_source=source, output_root=target.parent,
        command=("pimpleFoam",), log_directory=runtime / "logs",
    )

    write(runtime / "manifest.json", json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n")
    write(runtime / "precice-config.xml", xml + "\n")
    write(target / "precice-config.xml", xml + "\n")
    write(target / "system" / "preciceDict", precice_dict(item.fluid_participant, item.fluid_mesh))
    write(target / "constant" / "dynamicMeshDict", dynamic_mesh_dict())
    write(target / "system" / "controlDict", adapted_control_dict(source / "system/controlDict"))
    write(target / "0" / "pointDisplacement", displacement_field("pointDisplacement", "pointVectorField", "fixedValue"))
    write(target / "0" / "cellDisplacement", displacement_field("cellDisplacement", "volVectorField", "zeroGradient"))
    setup = {
        "task": "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1",
        "generic_path": [
            "SliceManifest", "generate_precice_xml", "generate_openfoam_launch_plan",
            "StructureCoordinator", "real preCICE", "OpenFOAM", "persistent ANCF worker",
        ],
        "source_case": str(source),
        "generated_case": str(target),
        "manifest": manifest.to_dict(),
        "topology": topology,
        "launch_plan": [entry.to_dict() for entry in plan],
        "exchange_directory_wsl": exchange,
        "dt_s": DT_S,
        "max_time_s": MAX_TIME_S,
        "target_accepted_windows": 3,
        "hard_max_accepted_windows": 5,
        "sld1_present": False,
        "adaptation_scope": [
            "system/preciceDict", "precice-config.xml", "constant/dynamicMeshDict",
            "system/controlDict", "0/pointDisplacement", "0/cellDisplacement",
        ],
        "source_key_file_sha256": source_hashes,
        "copied_poly_mesh_sha256": {
            rel: sha256(target / rel) for rel in KEY_FILES if rel.startswith("constant/polyMesh/")
        },
        "source_case_modified": False,
        "production_modified": False,
        "real_coupling_started": False,
    }
    write(runtime / "runtime_setup.json", json.dumps(setup, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"runtime": str(runtime), "case": str(target), "manifest_sha256": manifest.manifest_sha256, "topology": topology}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
