"""Write the required no-rerun evidence after the mesh preflight gate fails."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

TASK = "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def put(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def main() -> int:
    repo = Path(__file__).resolve().parents[2]
    run = repo / "runtime" / "coupling_validation" / TASK / "attempt_001"
    out = repo / "runtime" / "ANCF_validation"
    base = out / TASK
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    checkmesh = run / "logs" / "checkMesh.log"
    files: dict[str, str] = {
        "_PROTOCOL.md": "# REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1 protocol\n\nFrozen start commit: `f7dee49abd1510ce90d6163561a2d3155e49be65` (parent `29b364cdb87e0829c0c2b49ed727957240b40c1e`). The SUT is the committed generic path: SliceManifest -> generated topology/XML -> generated launch descriptor -> PreciceStructureFleetBackend -> GenericStructuralCoordinator -> persistent ANCF worker. Case: Ns=1, slice_0000, S=5 m, LegacyPointLumped, integrated slice force [N], unit span 1 m, SLD1=false. Planned run: three 0.005 s windows.\n\nThe one bounded OpenFOAM 10 `checkMesh -allTopology -allGeometry` pre-run gate reported `Failed 1 mesh checks` (604 concave cells). This is the first hard pre-run failure. No participant, pimpleFoam, preCICE runtime, worker smoke process, or numerical coupled window was started. No historical launcher substitution, mesh edit, retry, parameter change, or production patch is authorized.\n",
        "_ENVIRONMENT.md": "# Environment preflight\n\n- WSL Ubuntu-22.04; OpenFOAM 10 (`10-c4cf895ad8fa`); pimpleFoam/checkMesh resolved after sourcing `/opt/openfoam10/etc/bashrc`.\n- preCICE shared library 3.4.1; pyprecice 3.4.0 from the existing repository dependency directory.\n- Worker compiled from current production with LLVM clang 22.1.8, C++17, -O2, -DNOMINMAX; SHA256 `EDBBD0B7E5086665A9D4E35498C016B1893CA990C7C3D2B404D68D033250A322`. Startup handshake probe passed, but it was not launched in the smoke after the mesh gate failed.\n- Planned adapter: `/home/machao/OpenFOAM/machao-10/platforms/linux64GccDPInt32Opt/lib/libpreciceAdapterFunctionObject.so`; SHA256 `26ad8529822f96ca8ddfb3370f85257b0d19b56958538d6073cf8af897aac572`.\n\nThe fresh case check reported 604 concave cells and ended with `Failed 1 mesh checks`; its complete log is retained in the runtime case.\n",
        "_REPORT.md": "# REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1 report\n\n`REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1 = FAIL / MESH_PRE_RUN_CHECK_FAIL`.\n\nThe generic Ns=1 manifest, XML and launch plan were generated successfully. The historical cylinder case was used only as a template, not as a launcher. The generated identities are `StructureCoordinator` and `Fluid_slice_0000`. OpenFOAM 10 checkMesh found 604 concave cells and reported one failed mesh check. The frozen protocol requires stop before coupled participant launch.\n\nExecution counts: checkMesh=1; StructureCoordinator=0; Fluid/pimpleFoam=0; persistent ANCF worker in smoke=0; preCICE initialize=0; accepted windows=0; ANCF advances=0; force/motion transfers=0; G1=0; multi-slice=0; CFD/FSI coupled execution=0. Header-only traces preserve that no fabricated exchange evidence exists. SLD1 distributed real runtime remains NOT_YET_TESTED; arbitrary-N real runtime remains NOT_YET_ESTABLISHED. G1 and independent structural validation remain NOT_CLOSED.\n",
    }
    for suffix, content in files.items():
        put(base.with_name(base.name + suffix), content)
    put(base.with_name(base.name + "_MANIFEST.json"), json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    put(base.with_name(base.name + "_PRECISE_CONFIG.xml"), (run / "precice-config.xml").read_text(encoding="utf-8"))
    process = {"task": TASK, "real_coupled_processes_started": 0, "processes": [{"role": "OpenFOAM mesh preflight", "command": "checkMesh -allTopology -allGeometry", "pid": 602, "cwd": str(run / "case" / "smoke_slice_0000"), "log": str(checkmesh), "result": "FAILED_1_MESH_CHECK"}], "not_started": ["StructureCoordinator", "Fluid_slice_0000/pimpleFoam", "persistent ANCF worker", "preCICE runtime"]}
    put(base.with_name(base.name + "_PROCESS_TABLE.json"), json.dumps(process, ensure_ascii=False, indent=2) + "\n")
    for name, header in {
        "_FORCE_TRACE.csv": ["window", "slice_id", "openfoam_integrated_force_N", "unit_span_m", "normalized_line_force_Npm", "legacy_integrated_force_N", "note"],
        "_MOTION_TRACE.csv": ["window", "slice_id", "motion_xyz_m", "source_global_ancf_state", "note"],
        "_TIME_IDENTITY.csv": ["window", "openfoam_time_s", "precice_time_s", "structural_time_s", "global_step", "note"],
    }.items():
        with base.with_name(base.name + name).open("w", encoding="utf-8", newline="\n") as stream:
            csv.writer(stream).writerow(header)
    state = {"task": TASK, "status": "NO_COUPLED_STATE_CREATED", "q": None, "qdot": None, "qddot": None, "finite": "NOT_APPLICABLE", "reason": "mesh pre-run gate failed before worker participant launch"}
    put(base.with_name(base.name + "_STATE_TRACE.json"), json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    result = {"task": TASK, "status": "FAIL", "first_failure": "MESH_PRE_RUN_CHECK_FAIL", "underlying": "OpenFOAM 10 checkMesh: Failed 1 mesh checks; 604 concave cells", "start_head": "f7dee49abd1510ce90d6163561a2d3155e49be65", "parent": "29b364cdb87e0829c0c2b49ed727957240b40c1e", "baseline_tag_target": "dfb1a3e7e92220a2e4c9400317de372e637095eb", "manifest_sha256": manifest["manifest_sha256"], "generated_xml_sha256": digest(run / "precice-config.xml"), "generic_path_under_test": True, "historical_launcher_used": False, "sld1_present": False, "production_modifications": 0, "execution_counts": {"structure_coordinator": 0, "fluid": 0, "worker": 0, "precice_initialize": 0, "accepted_windows": 0, "ancf_advances": 0, "g1": 0, "multi_slice": 0, "cfd_fsi": 0}, "G1_CURRENT_LINE_VALIDATION": "NOT_CLOSED", "ANCF_INDEPENDENT_STRUCTURAL_VALIDATION": "NOT_CLOSED"}
    put(base.with_name(base.name + "_RESULT.json"), json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    targets = [base.with_name(base.name + suffix) for suffix in ("_PROTOCOL.md", "_ENVIRONMENT.md", "_MANIFEST.json", "_PRECISE_CONFIG.xml", "_PROCESS_TABLE.json", "_FORCE_TRACE.csv", "_MOTION_TRACE.csv", "_TIME_IDENTITY.csv", "_STATE_TRACE.json", "_RESULT.json", "_REPORT.md")]
    lines = [f"{digest(path)}  {path.relative_to(repo).as_posix()}" for path in targets]
    lines.append(f"{digest(checkmesh)}  {checkmesh.relative_to(repo).as_posix()}")
    put(base.with_name(base.name + "_SHA256_MANIFEST.txt"), "\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
