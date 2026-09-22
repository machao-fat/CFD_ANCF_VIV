"""Offline HH06 moving-mesh replay.

This diagnostic deliberately runs OpenFOAM ``moveMesh`` only.  It does not
start pimpleFoam, preCICE, or a structural coupling.  The displacement table
is generated through the production HH06 ANCF backend so that the mesh test
uses the same section interpolation and force conversion as the real wrapper.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASE = Path("/home/machao/OpenFOAM/coupling/singal_slice/slice0000")
WORK = Path("/tmp/hh06_mesh_only_replay_retry7")
DT = 0.0002
STEPS = 22
RAW_FORCE = (0.0644, 0.0599, 0.0)


def field(name: str, table: str) -> str:
    cls = "pointVectorField" if name == "pointDisplacement" else "volVectorField"
    return f"""FoamFile
{{
    format ascii;
    class {cls};
    location \"0\";
    object {name};
}}
dimensions [0 1 0 0 0 0 0];
internalField uniform (0 0 0);
boundaryField
{{
    front {{ type empty; }}
    back {{ type empty; }}
    inlet {{ type fixedValue; value uniform (0 0 0); }}
    outlet {{ type fixedValue; value uniform (0 0 0); }}
    upper {{ type symmetryPlane; }}
    lower {{ type symmetryPlane; }}
    cylinder {{ type uniformFixedValue; uniformValue table ({table}); }}
}}
"""


def main() -> int:
    if WORK.exists():
        raise RuntimeError(f"refusing to reuse diagnostic path: {WORK}")
    WORK.mkdir(parents=True)

    # Import the exact production backend, not a toy structural integrator.
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT / "tools" / "hh06_single_slice_structure_0000_participant_v1"))
    import structure_0000_participant as hh06
    bundle = hh06.load_contract_bundle(CASE)
    manifest = hh06.build_manifest(bundle)
    item = manifest.slices[0]
    worker_path = CASE / "cfd_ancf_ancf_kernel_worker_shm1_lineage_qualified"
    backend = hh06.PersistentHH06KernelBackend(bundle, manifest, worker_path)
    backend.start()
    motions = [(0.0, 0.0, 0.0)]
    try:
        from coupling.arbitrary_n_live_orchestration_v1.coordinator import ForceSample, GenericStructuralCoordinator
        coordinator = GenericStructuralCoordinator(
            manifest, backend,
            reference_positions_by_slice={item.slice_id: (0.0, 0.0, item.s_ref_m)},
        )
        for step in range(1, STEPS + 1):
            sample = ForceSample.from_openfoam_integrated(
                manifest, item.slice_id, iteration=step, time_s=step * DT,
                force_N=RAW_FORCE, unit_span_m=bundle.unit_span_m,
            )
            coordinator.submit_force(sample)
            coordinator.advance_if_complete()
            motion = coordinator.scatter_motion()[item.slice_id]
            motions.append(tuple(float(value) for value in motion))
            coordinator.commit()
    finally:
        backend.close()

    table = " ".join(
        f"({index * DT:.12g} ({x:.17g} {y:.17g} 0))"
        for index, (x, y, _z) in enumerate(motions)
    )
    # The production case is a restart-only case and intentionally has no
    # numeric ``0`` directory.  Use its accepted 30 s field as the mesh-only
    # initial state, while writing the diagnostic fields under time ``0``.
    shutil.copytree(CASE / "30", WORK / "0")
    for name in ("constant", "system"):
        shutil.copytree(CASE / name, WORK / name)
    (WORK / "0" / "pointDisplacement").write_text(field("pointDisplacement", table), encoding="utf-8")
    (WORK / "0" / "cellDisplacement").write_text(field("cellDisplacement", table), encoding="utf-8")
    (WORK / "system" / "controlDict").write_text(
        """FoamFile { format ascii; class dictionary; object controlDict; }
application moveMesh;
startFrom startTime;
startTime 0;
stopAt endTime;
endTime 0.0044;
deltaT 0.0002;
writeControl timeStep;
writeInterval 1;
purgeWrite 0;
writeFormat ascii;
writePrecision 16;
timeFormat general;
timePrecision 16;
runTimeModifiable false;
""", encoding="utf-8")

    command = "source /opt/openfoam10/etc/bashrc && cd %s && moveMesh > moveMesh.stdout 2> moveMesh.stderr" % WORK
    run = subprocess.run(["bash", "-lc", command], capture_output=True, text=True, timeout=300)
    (WORK / "launcher.stdout").write_text(run.stdout, encoding="utf-8", errors="replace")
    (WORK / "launcher.stderr").write_text(run.stderr, encoding="utf-8", errors="replace")
    result = {
        "status": "PASS" if run.returncode == 0 else "FAIL",
        "return_code": run.returncode,
        "steps": STEPS,
        "dt_s": DT,
        "duration_s": STEPS * DT,
        "raw_force_N_per_unit_span": list(RAW_FORCE),
        "max_abs_motion_m": max(max(abs(x), abs(y)) for x, y, _z in motions),
        "motions": [list(item) for item in motions],
        "work": str(WORK),
        "equations_run": False,
        "pimpleFoam_run": False,
        "precice_run": False,
        "negative_volume_mentions": (WORK / "moveMesh.stderr").read_text(errors="replace").lower().count("negative volume"),
    }
    (WORK / "result.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return run.returncode


if __name__ == "__main__":
    raise SystemExit(main())
