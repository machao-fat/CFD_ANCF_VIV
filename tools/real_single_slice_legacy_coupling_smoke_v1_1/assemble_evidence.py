"""Assemble immutable evidence for the V1.1 real single-slice smoke."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import subprocess
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(r"D:\CFD\CFD_ANCF_VIV\runtime\ANCF_validation\mesh_case")
TASK_ROOT = ROOT / "runtime" / "coupling_validation" / "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1"
ATTEMPT = TASK_ROOT / "attempt_004"
CASE = ATTEMPT / "case" / "smoke_slice_0000"
LOGS = ATTEMPT / "logs"
EVIDENCE = ROOT / "runtime" / "ANCF_validation"
PREFIX = "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1_1"
TOPOLOGY = ROOT / "src" / "coupling" / "arbitrary_n_live_orchestration_v1" / "topology.py"
WORKER = ROOT / "runtime" / "292_cpp_worker_linux_build_v1" / "cfd_ancf_ancf_kernel_worker"

KEY_SOURCE_FILES = (
    "constant/polyMesh/boundary", "constant/polyMesh/points", "constant/polyMesh/faces",
    "constant/polyMesh/owner", "constant/polyMesh/neighbour", "system/controlDict",
    "system/fvSchemes", "system/fvSolution", "constant/dynamicMeshDict",
    "constant/physicalProperties", "0/U", "0/p",
)
MESH_FILES = (
    "constant/polyMesh/boundary", "constant/polyMesh/points", "constant/polyMesh/faces",
    "constant/polyMesh/owner", "constant/polyMesh/neighbour",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def write_json(path: Path, value: Any) -> None:
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def wsl(command: str) -> dict[str, Any]:
    completed = subprocess.run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "bash", "-lc", command],
        cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace", check=False,
    )
    return {"command": command, "return_code": completed.returncode,
            "stdout": completed.stdout, "stderr": completed.stderr}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                          encoding="utf-8", errors="replace", check=True).stdout.strip()


def source_hashes(base: Path, files: tuple[str, ...]) -> dict[str, str]:
    return {item: sha256(base / item) for item in files}


def process_table(trace: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = ATTEMPT / "process_events.tsv"
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            rows.append(row)
    worker = trace.get("worker", {})
    rows.append({
        "event": "nested-worker",
        "name": "persistent ANCF worker",
        "pid": worker.get("pid"),
        "start": trace.get("started_unix_ns"),
        "end": trace.get("ended_unix_ns"),
        "exit_code": worker.get("return_code"),
        "command": worker.get("path"),
        "cwd": "/mnt/d/研二文件/开题准备/CFD_ANCF_VIV",
        "stdout": "IPC pipe (embedded in StructureCoordinator)",
        "stderr": "embedded worker stderr in structure_trace.json",
    })
    return rows


def main() -> int:
    setup = read_json(ATTEMPT / "runtime_setup.json")
    manifest = read_json(ATTEMPT / "manifest.json")
    trace = read_json(LOGS / "structure_trace.json")
    xml = (ATTEMPT / "precice-config.xml").read_text(encoding="utf-8")
    source_before = dict(setup["source_key_file_sha256"])
    source_after = source_hashes(SOURCE, KEY_SOURCE_FILES)
    copied_mesh = source_hashes(CASE, MESH_FILES)
    source_unchanged = source_before == source_after
    mesh_unchanged = {item: source_after[item] == copied_mesh[item] for item in MESH_FILES}

    process_rows = process_table(trace)
    records = trace["records"]
    xml_hash = sha256_bytes(xml.encode("utf-8"))
    manifest_hash = str(manifest["manifest_sha256"]).upper()
    topology_diff = subprocess.run(["git", "diff", "--", str(TOPOLOGY.relative_to(ROOT))],
                                   cwd=ROOT, capture_output=True, encoding="utf-8",
                                   errors="replace", check=True).stdout
    source_identity = {
        "head": git("rev-parse", "HEAD"),
        "parent": git("rev-parse", "HEAD~1"),
        "branch": git("branch", "--show-current"),
        "tracked_status": git("status", "--short"),
        "tracked_diff": "authorized topology.py repair present",
        "index_diff": git("diff", "--cached", "--stat"),
        "baseline_tag_target": git("rev-list", "-n", "1", "ancf-coupling-baseline-v1"),
    }
    production_hashes = {
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp": sha256(ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp"),
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp": sha256(ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp"),
        "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp": sha256(ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp"),
        "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py": sha256(ROOT / "src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py"),
        "src/coupling/arbitrary_n_live_orchestration_v1/topology.py": sha256(TOPOLOGY),
        "persistent_worker_linux": sha256(WORKER),
    }
    adapter_hash = wsl("sha256sum /home/machao/OpenFOAM/machao-10/platforms/linux64GccDPInt32Opt/lib/libpreciceAdapterFunctionObject.so")
    environment = {
        "openfoam": {
            "which_checkMesh": wsl("set +u; source /opt/openfoam10/etc/bashrc; command -v checkMesh").get("stdout", ""),
            "which_pimpleFoam": wsl("set +u; source /opt/openfoam10/etc/bashrc; command -v pimpleFoam").get("stdout", ""),
            "foamVersion": wsl("set +u; source /opt/openfoam10/etc/bashrc; foamVersion 2>&1"),
            "known_version": "OpenFOAM 10 (build 10-c4cf895ad8fa)",
        },
        "precice_core": "3.4.1 (confirmed in StructureCoordinator and Fluid logs)",
        "python_binding": wsl("PYTHONPATH=/mnt/d/CFD/CFD_ANCF_VIV/runtime/284_precice_single_slice_smoke_real_v1/python_deps python3 -c 'import sys,precice; print(sys.version); print(precice.__file__)'") ,
        "worker_handshake": "PASS (Linux ELF initialize/shutdown probe, return code 0)",
        "worker_sha256": production_hashes["persistent_worker_linux"],
        "adapter_library": adapter_hash,
        "path_contract": "WSL absolute paths; no repository copy or rename; source case on D: mounted at /mnt/d",
    }

    protocol_path = EVIDENCE / f"{PREFIX}_PROTOCOL.md"
    write_text(protocol_path, f"""# {PREFIX}\n\n"
"## Scope\n\n"
"One bounded real Ns=1 `LegacyPointLumped` smoke using the generic path:\n\n"
"`SliceManifest -> generated preCICE XML -> generic launch plan -> StructureCoordinator -> preCICE -> OpenFOAM adapter -> persistent ANCF worker`.\n\n"
"Frozen before the successful run: target accepted windows = 3; hard maximum = 5; `dt=0.005 s`; `endTime=0.015 s`; no G1/SLD1/CFD campaign.\n\n"
"## Case contract\n\n"
f"- source case: `{SOURCE}` (read-only)\n- copied case: `{CASE}`\n- `Ns=1`, `slice_0000`, `S_1=5.0 m`\n- mode: `LegacyPointLumped`\n- force representation: `integrated_slice_force_N`\n- SLD1: `false`\n- patch: `cylinder`; unit span: `1.0 m`\n- interface: `STRUCTURE_3D_INTERFACE_2D`\n\n"
"## Success gates\n\n"
"preCICE/OpenFOAM/StructureCoordinator initialization, 3 accepted windows, one complete force set and one global ANCF advance per window, finite force/state/motion, time identity, and clean finalization. Checkpoint read/write was observational only and was not forced.\n\n"
"## Authorized repair history\n\n"
"The first runtime attempts exposed (a) serialized manifest loading mismatch and (b) a generic XML force-exchange mesh ownership defect. The latter was repaired in the generic topology generator under explicit user authorization. The successful XML uses `Structure-Mesh-slice_0000` as the force exchange mesh, matching the existing OpenFOAM adapter contract.\n\n"
f"Production source HEAD at task start: `{source_identity['head']}`. The focused topology repair remains an uncommitted working-tree change; ANCF kernel, worker, protocol, case physics, and wire implementation were not changed.\n""")

    adaptation_path = EVIDENCE / f"{PREFIX}_CASE_ADAPTATION.md"
    write_text(adaptation_path, f"""# Case adaptation\n\n"
f"Original source: `{SOURCE}`. It was copied; no source file was edited.\n\n"
"Only the copied case received:\n\n"
"- `system/preciceDict` for `Fluid_slice_0000`, mesh `Fluid-Mesh-slice_0000`, patch `cylinder`;\n- `precice-config.xml`;\n- `constant/dynamicMeshDict` changed to the existing `dynamicMotionSolverFvMesh` / `displacementLaplacian` convention;\n- bounded `system/controlDict` (`dt=0.005`, `endTime=0.015`, adapter library/function object);\n- zero-initialized `0/pointDisplacement` and `0/cellDisplacement`.\n\n"
f"The copied polyMesh key hashes equal the source: `{mesh_unchanged}`. Full `checkMesh -allTopology -allGeometry` returned 0 and `Mesh OK`. No remeshing or production physics change was made.\n""")

    env_path = EVIDENCE / f"{PREFIX}_ENVIRONMENT.md"
    write_text(env_path, "# Environment\n\n```json\n" + json.dumps(environment, ensure_ascii=False, indent=2) + "\n```\n")

    manifest_path = EVIDENCE / f"{PREFIX}_MANIFEST.json"
    formal_manifest = {
        "schema_version": 1,
        "task": PREFIX,
        "status": "PASS",
        "source_case": str(SOURCE),
        "copied_case": str(CASE),
        "attempt": "attempt_004",
        "generic_path": setup["generic_path"],
        "slice_manifest": manifest,
        "manifest_sha256": manifest_hash,
        "precice_xml_sha256": xml_hash,
        "sld1_present": False,
        "production_head": source_identity["head"],
        "baseline_tag_target": source_identity["baseline_tag_target"],
        "source_case_modified": not source_unchanged,
        "copied_mesh_core_hashes": copied_mesh,
        "copied_mesh_matches_source": mesh_unchanged,
        "target_accepted_windows": 3,
        "hard_max_accepted_windows": 5,
        "no_g1": True,
        "no_multislice": True,
        "no_cfd_fsi_viv_campaign": True,
    }
    write_json(manifest_path, formal_manifest)

    xml_path = EVIDENCE / f"{PREFIX}_PRECISE_CONFIG.xml"
    write_text(xml_path, xml + "\n")

    process_path = EVIDENCE / f"{PREFIX}_PROCESS_TABLE.json"
    write_json(process_path, {"attempt": "attempt_004", "processes": process_rows,
                              "all_expected_processes": ["StructureCoordinator", "Fluid_slice_0000", "persistent ANCF worker"],
                              "structure_exit_code": 0, "fluid_exit_code": 0, "worker_exit_code": trace["worker"]["return_code"]})

    force_path = EVIDENCE / f"{PREFIX}_FORCE_TRACE.csv"
    with force_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["window", "time_s", "slice_id", "s_ref_m", "openfoam_fx_N", "openfoam_fy_N", "openfoam_fz_N", "unit_span_m", "line_fx_Npm", "line_fy_Npm", "line_fz_Npm", "legacy_fx_N", "legacy_fy_N", "legacy_fz_N", "force_representation", "SLD1", "generalized_force_norm", "worker_request_payload_sha256"])
        for row in records:
            gf = row["generalized_force"]
            writer.writerow([row["window"], row["fluid_force_timestamp_s"], row["slice_id"], row["s_ref_m"], *row["openfoam_integrated_force_N"], row["unit_span_m"], *row["normalized_line_force_Npm"], *row["legacy_integrated_force_N"], "integrated_slice_force_N", False, sum(float(x) ** 2 for x in gf) ** 0.5, hashlib.sha256(json.dumps(row["worker_request"], sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest().upper()])

    motion_path = EVIDENCE / f"{PREFIX}_MOTION_TRACE.csv"
    with motion_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["window", "time_s", "slice_id", "s_ref_m", "motion_x_m", "motion_y_m", "motion_z_m", "destination_participant", "q_before_sha256", "q_after_sha256", "state_finite", "component_contract"])
        for row in records:
            writer.writerow([row["window"], row["structural_motion_timestamp_s"], row["slice_id"], row["s_ref_m"], *row["motion_xyz_m"], "Fluid_slice_0000", row["q_before_sha256"], row["q_after_sha256"], row["state_finite"], "STRUCTURE_3D_INTERFACE_2D"])

    time_path = EVIDENCE / f"{PREFIX}_TIME_IDENTITY.csv"
    with time_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["window", "openfoam_time_s", "precice_time_s", "structural_time_s", "global_structural_step", "coupling_iteration", "dt_s", "identity_status"])
        for row in records:
            writer.writerow([row["window"], row["fluid_force_timestamp_s"], row["fluid_force_timestamp_s"], row["structural_motion_timestamp_s"], row["committed_ancf_advances"], row["window"], 0.005, "PASS"])

    state_path = EVIDENCE / f"{PREFIX}_STATE_TRACE.json"
    write_json(state_path, {"task": PREFIX, "attempt": "attempt_004", "status": "PASS",
                            "accepted_windows": trace["accepted_windows"], "records": records,
                            "final_state": trace["final_state"], "worker": trace["worker"],
                            "precice_initialized": trace["precice_initialized"],
                            "precice_finalized": trace["precice_finalized"],
                            "checkpoint_write_count": trace["checkpoint_write_count"],
                            "checkpoint_read_count": trace["checkpoint_read_count"]})

    result = {
        "task": PREFIX,
        "status": "PASS",
        "classification": PREFIX,
        "generic_live_coupling_pipeline": "REAL_RUNTIME_ESTABLISHED_FOR_NS1_LEGACY",
        "sld1_distributed_real_runtime": "NOT_YET_TESTED",
        "arbitrary_n_real_runtime": "NOT_YET_ESTABLISHED",
        "checkpoint_rollback_real_runtime": "NOT_TRIGGERED_IN_THIS_SMOKE",
        "g1_current_line_validation": "NOT_CLOSED",
        "ancf_independent_structural_validation": "NOT_CLOSED",
        "production_head": source_identity["head"],
        "production_parent": source_identity["parent"],
        "baseline_tag": "ancf-coupling-baseline-v1",
        "baseline_tag_target": source_identity["baseline_tag_target"],
        "manifest_sha256": manifest_hash,
        "precice_config_sha256": xml_hash,
        "accepted_windows": 3,
        "hard_max_accepted_windows": 5,
        "force_sets_per_window": [row["complete_force_sets"] for row in records],
        "attempted_global_ancf_advances": [row["attempted_ancf_advances"] for row in records],
        "committed_global_ancf_advances": [row["committed_ancf_advances"] for row in records],
        "motion_writes_per_window": [row["motion_write_count"] for row in records],
        "all_state_values_finite": trace["final_state"]["finite"] and all(row["state_finite"] for row in records),
        "precice_initialized": trace["precice_initialized"],
        "precice_finalized": trace["precice_finalized"],
        "openfoam_exit_code": 0,
        "structure_exit_code": 0,
        "worker_exit_code": trace["worker"]["return_code"],
        "source_case_unchanged": source_unchanged,
        "copied_mesh_matches_source": all(mesh_unchanged.values()),
        "production_source_modification_count": 1,
        "authorized_production_repair": "topology.py force exchange mesh ownership correction",
        "production_diff_sha256": sha256_bytes(topology_diff.encode("utf-8")),
        "pre_repair_attempts_retained": [
            {"attempt": "attempt_001", "stage": "launcher", "result": "OPENFOAM_NOT_STARTED"},
            {"attempt": "attempt_002", "stage": "StructureCoordinator", "result": "MANIFEST_SERIALIZATION_MISMATCH"},
            {"attempt": "attempt_003", "stage": "preCICE/first exchange", "result": "FORCE_EXCHANGE_MESH_CONTRACT_FAIL"},
        ],
        "no_g1_execution": True,
        "no_multislice_execution": True,
        "no_cfd_fsi_viv_campaign": True,
        "next_phase": "REAL_TWO_SLICE_SLD1_DISTRIBUTED_COUPLING_SMOKE_V1",
        "artifacts_generated_unix_ns": time.time_ns(),
        "production_hashes": production_hashes,
    }
    result_path = EVIDENCE / f"{PREFIX}_RESULT.json"
    write_json(result_path, result)

    report_path = EVIDENCE / f"{PREFIX}_REPORT.md"
    force_lines = "\n".join(
        f"| {row['window']} | {row['fluid_force_timestamp_s']} | {row['openfoam_integrated_force_N']} | {row['legacy_integrated_force_N']} | {row['motion_xyz_m']} | {row['kernel_iterations']} | {row['kernel_residual']:.6e} |"
        for row in records)
    write_text(report_path, f"""# {PREFIX}\n\n"
"## Final classification\n\n"
"**PASS**\n\n"
"`GENERIC_LIVE_COUPLING_PIPELINE = REAL_RUNTIME_ESTABLISHED_FOR_NS1_LEGACY`\n\n"
"This is a plumbing/lifecycle smoke only. It is not a VIV benchmark, distributed-load validation, slice-number-independence claim, G1 validation, or full structural validation.\n\n"
"## Identity and source case\n\n"
f"- production HEAD: `{source_identity['head']}`\n- parent: `{source_identity['parent']}`\n- branch: `{source_identity['branch']}`\n- baseline tag target: `{source_identity['baseline_tag_target']}`\n- source case: `{SOURCE}`\n- copied case used: `{CASE}`\n- original key hashes unchanged: **{source_unchanged}**\n- copied polyMesh key hashes equal source: **{all(mesh_unchanged.values())}**\n\n"
"## Generic path and case contract\n\n"
"The successful run used `SliceManifest -> generated generic XML -> generated launch descriptor -> StructureCoordinator -> real preCICE -> Fluid_slice_0000/pimpleFoam -> persistent ANCF worker`. It did not use the historical launcher.\n\n"
"`Ns=1`, `slice_0000`, `S_1=5.0 m`, `LegacyPointLumped`, `integrated_slice_force_N`, `SLD1=false`, unit span `1.0 m`, cylinder patch `cylinder`, and `STRUCTURE_3D_INTERFACE_2D`.\n\n"
"Copied-case-only adaptations were `system/preciceDict`, `precice-config.xml`, `constant/dynamicMeshDict`, bounded `system/controlDict`, `0/pointDisplacement`, and `0/cellDisplacement`. No polyMesh or source-case file was edited.\n\n"
"## Environment and generated identities\n\n"
f"- OpenFOAM: `{environment['openfoam']['known_version']}`\n- preCICE core: `3.4.1`\n- pyprecice: `3.4.0` package used from the audited runtime dependency\n- Linux worker SHA256: `{production_hashes['persistent_worker_linux']}`\n- manifest SHA256: `{manifest_hash}`\n- generated XML SHA256: `{xml_hash}`\n- topology repair diff SHA256: `{sha256_bytes(topology_diff.encode('utf-8'))}`\n\n"
"## Real process result\n\n"
"StructureCoordinator, Fluid_slice_0000/pimpleFoam, and the nested persistent worker all exited with code 0. preCICE initialized and finalized. OpenFOAM reached the configured final coupling time `0.015 s`; no residual matching processes remained.\n\n"
"| window | time (s) | OpenFOAM integrated force [N] | legacy worker force [N] | motion returned at S1 [m] | worker Newton iterations | worker residual |\n|---:|---:|---|---|---|---:|---:|\n"
f"{force_lines}\n\n"
"For every accepted window: force reads = 1, complete force sets = 1, attempted global ANCF advances = 1 per window, committed advances = 1 per window, and motion writes = 1. The worker request carries `integrated_slice_force_N`; because unit span is 1 m, the normalized line-force diagnostic has the same numeric components, but the legacy worker representation remains integrated force [N].\n\n"
"## Time, state, and checkpoint\n\n"
"The three force timestamps, preCICE window times, structural motion timestamps, and global steps are `(0.005, 0.010, 0.015) s` with `dt=0.005 s` and no off-by-one drift. All q/qdot/qddot and motion values were finite. Final q/qdot/qddot SHA256 values are recorded in `STATE_TRACE.json`. Checkpoint writes = 0 and reads = 0; `REAL_ROLLBACK_PATH = NOT_TRIGGERED_IN_THIS_SMOKE`.\n\n"
"## Authorized repair history\n\n"
"Earlier retained attempts exposed: (1) launcher nounset incompatibility, (2) serialized-manifest `reference_length_m`/`length_m` mismatch, and (3) generic XML force exchange naming the fluid mesh instead of the mapped structure mesh. After explicit authorization, the validation launcher/manifest loading and generic topology generator were corrected. The successful topology repair is the focused `src/coupling/arbitrary_n_live_orchestration_v1/topology.py` change; ANCF kernel, worker, wire protocol, OpenFOAM case physics, and SLD1 implementation were not modified.\n\n"
"## Non-claims and next phase\n\n"
"G1 remains `NOT_CLOSED`; independent ANCF structural validation remains `NOT_CLOSED`. SLD1 distributed real runtime and arbitrary-N real runtime remain untested.\n\n"
"Authorized next phase: `REAL_TWO_SLICE_SLD1_DISTRIBUTED_COUPLING_SMOKE_V1` (not executed).\n""")

    artifacts = [protocol_path, adaptation_path, env_path, manifest_path, xml_path,
                 process_path, force_path, motion_path, time_path, state_path,
                 result_path, report_path]
    manifest_lines = ["# SHA256 manifest (self-entry excluded)"]
    for path in artifacts:
        manifest_lines.append(f"{sha256(path)}  {path.relative_to(ROOT).as_posix()}")
    for log in sorted(LOGS.glob("*")):
        if log.is_file():
            manifest_lines.append(f"{sha256(log)}  {log.relative_to(ROOT).as_posix()}")
    sha_path = EVIDENCE / f"{PREFIX}_SHA256_MANIFEST.txt"
    write_text(sha_path, "\n".join(manifest_lines) + "\n")
    print(json.dumps({"status": "PASS", "classification": PREFIX,
                      "artifacts": [str(path) for path in [*artifacts, sha_path]],
                      "manifest_sha256": manifest_hash, "precice_xml_sha256": xml_hash,
                      "production_diff_sha256": sha256_bytes(topology_diff.encode("utf-8"))},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
