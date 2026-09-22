"""Create the fresh, bounded Ns=1 smoke runtime from committed generic APIs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from coupling.arbitrary_n_live_orchestration_v1 import (
    build_slice_manifest,
    generate_openfoam_launch_plan,
    generate_precice_xml,
    inspect_precice_xml,
)


DT_S = 0.005
MAX_TIME_S = 0.015


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def _precice_dict(participant: str, mesh: str) -> str:
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
    rho                     rho [1 -3 0 0 0 0 0] 1;
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
        patches     (cyl);
        locations   faceCenters;
        readData    (Displacement);
        writeData   (Force);
    }}
}}
'''


def _control_dict() -> str:
    return f'''FoamFile
{{
    version     2.0;
    format      ascii;
    class       dictionary;
    object      controlDict;
}}

application     pimpleFoam;
libs            ("libpreciceAdapterFunctionObject.so");
startFrom       startTime;
startTime       0;
stopAt          endTime;
endTime         {MAX_TIME_S:.3f};
deltaT          {DT_S:.3f};
writeControl    timeStep;
writeInterval   100;
purgeWrite      0;
writeFormat     ascii;
writePrecision  8;
writeCompression off;
timeFormat      general;
timePrecision   8;
runTimeModifiable no;
adjustTimeStep  no;

functions
{{
    preCICE_Adapter
    {{
        type preciceAdapterFunctionObject;
    }}
}}
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--template-case", required=True)
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    runtime = Path(args.runtime_root).resolve()
    template = Path(args.template_case).resolve()
    case_root = runtime / "case"
    if not template.is_dir():
        raise SystemExit(f"template case does not exist: {template}")
    config = {
        "case_id": "real_single_slice_legacy_coupling_smoke_v1",
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
    exchange = str((runtime / "precice-sockets").resolve()).replace("\\", "/")
    xml = generate_precice_xml(manifest, time_window_s=DT_S, max_time_s=MAX_TIME_S,
                               exchange_directory=exchange)
    topology = inspect_precice_xml(xml, manifest)
    plan = generate_openfoam_launch_plan(
        manifest, template_source=template, output_root=case_root,
        command=("pimpleFoam",), log_directory=runtime / "logs")
    item = manifest.slices[0]
    target = case_root / item.openfoam_case_id
    if target.exists():
        raise SystemExit(f"fresh runtime target already exists: {target}")
    ignored = shutil.ignore_patterns("postProcessing", "precice-profiling", "precice-sockets", "save")
    shutil.copytree(template, target, ignore=ignored)
    _write(runtime / "manifest.json", json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n")
    _write(runtime / "precice-config.xml", xml + "\n")
    _write(target / "precice-config.xml", xml + "\n")
    _write(target / "system" / "preciceDict", _precice_dict(item.fluid_participant, item.fluid_mesh))
    _write(target / "system" / "controlDict", _control_dict())
    setup = {
        "task": "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1",
        "generic_path": ["build_slice_manifest", "generate_precice_xml", "generate_openfoam_launch_plan"],
        "manifest": manifest.to_dict(), "topology": topology,
        "launch_plan": [entry.to_dict() for entry in plan],
        "runtime_root": str(runtime), "template_case": str(template),
        "generated_case": str(target), "exchange_directory": exchange,
        "dt_s": DT_S, "max_time_s": MAX_TIME_S, "planned_windows": 3,
        "sld1_present": False,
    }
    _write(runtime / "runtime_setup.json", json.dumps(setup, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
