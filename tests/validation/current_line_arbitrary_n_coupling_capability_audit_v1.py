"""Read-only arbitrary-N coupling capability audit.

Only in-process configuration, mapping and wire construction probes are run.
No preCICE, OpenFOAM, CFD, worker executable or ANCF numerical solver is
started.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "runtime" / "ANCF_validation"
HEAD = "29b364cdb87e0829c0c2b49ed727957240b40c1e"
PARENT = "7a953ef9349f99339329103fb1969ae022af21de"
TAG_TARGET = "dfb1a3e7e92220a2e4c9400317de372e637095eb"
PREFIX = "CURRENT_LINE_ARBITRARY_N_COUPLING_CAPABILITY_AUDIT_V1"

INVENTORY = [
    ("src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp", "kernel mechanics"),
    ("src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp", "kernel public API"),
    ("src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp", "worker and wire decode"),
    ("src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py", "Python wire encoder"),
    ("tools/precice_ancf_adapter_v1/ancf_case_config_v1.py", "case/config parser"),
    ("tools/precice_ancf_adapter_v1/ancf_generic_participant_v1.py", "generic participant"),
    ("tools/precice_ancf_adapter_v1/ancf_static_prestress_v1.py", "prestress artifact initializer"),
    ("tools/precice_ancf_adapter_v1/ancf_damping_preprocessor_v1.py", "Rayleigh damping preprocessor"),
    ("src/coupling/precice_adapter_v1/precice_backend.py", "pyprecice backend"),
    ("src/coupling/precice_adapter_v1/participant.py", "participant lifecycle wrapper"),
    ("src/coupling/precice_ancf_adapter_v1/worker_adapter.py", "single-slice worker adapter"),
    ("src/coupling/multi_slice_mapping/mapping.py", "manifest, H interpolation and mapping"),
    ("src/coupling/multi_slice_driver/contract.py", "multi-slice file contract"),
    ("src/coupling/multi_slice_driver/scheduler.py", "global multi-slice scheduler"),
    ("src/coupling/multi_slice_driver/ancf_adapter.py", "global ANCF adapter"),
    ("src/coupling/multi_slice_driver/real_process.py", "OpenFOAM bridge and force parser"),
    ("src/coupling/checkpoint/atomic_checkpoint.py", "N-aware checkpoint manager"),
    ("cases/openfoam/multi_slice_template/generate_case.py", "one-slice OpenFOAM generator"),
    ("cases/openfoam/multi_slice_template/template_config.json", "OpenFOAM template metadata"),
    ("tools/precice_adapter_v1/templates/single_slice_smoke/precice-config.xml", "single-slice XML"),
    ("tools/precice_adapter_v1/templates/single_slice_smoke_of10_v2/precice-config.xml", "single-slice OF10 XML"),
    ("tools/precice_ancf_adapter_v1/ancf_cpp_worker_single_slice_participant_v1.py", "single-slice launcher"),
    ("tools/precice_ancf_adapter_v1/ancf_cpp_worker_three_slice_participant_v1.py", "three-slice launcher"),
    ("tools/precice_ancf_adapter_v1/run_stage293_cpp_worker_precice_three_slice_smoke.py", "three-slice runner"),
    ("src/structure_ancf_matlab/ancf_build_mapping.m", "MATLAB H mapping"),
    ("src/structure_ancf_matlab/ancf_slice_motion.m", "MATLAB slice motion"),
    ("src/structure_ancf_matlab/ancf_external_load.m", "MATLAB legacy load"),
    ("src/structure_ancf_matlab/ancf_read_slice_loads_csv.m", "MATLAB load reader"),
    ("src/structure_ancf_matlab/ancf_save_checkpoint.m", "MATLAB checkpoint writer"),
    ("src/structure_ancf_matlab/ancf_load_checkpoint.m", "MATLAB checkpoint reader"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, check=True,
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return result.stdout.strip()


def write(name: str, value: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    path.write_text(value.rstrip() + "\n", encoding="utf-8")
    return path


def write_json(name: str, value: Any) -> Path:
    return write(name, json.dumps(value, ensure_ascii=False, indent=2,
                                  sort_keys=True, allow_nan=False))


def source_inventory() -> list[dict[str, Any]]:
    tracked = set(git("ls-files").splitlines())
    result = []
    for relative, role in INVENTORY:
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"missing source: {relative}")
        result.append({
            "relative_path": relative,
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "role": role,
            "tracked": relative in tracked,
        })
    return result


def offline_probe() -> dict[str, Any]:
    """Probe config, SLD1 payload shape and H interpolation without a solver."""
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    from tools.precice_ancf_adapter_v1.ancf_case_config_v1 import CaseConfig
    from tools.precice_ancf_adapter_v1.ancf_generic_participant_v1 import GenericANCFParticipant
    from coupling.multi_slice_mapping.mapping import (
        SliceDefinition, SliceManifest, build_H_for_manifest,
        map_integrated_slice_forces, motion_from_ancf_state,
    )

    fixture_path = ROOT / "tools/precice_ancf_adapter_v1/tests/fixtures/generic_case_config_v1.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    positions_by_n = {
        1: [5.0],
        2: [1.25, 8.75],
        3: [0.5, 5.0, 9.5],
        5: [0.4, 1.9, 4.1, 7.6, 9.8],
        8: [0.2, 1.0, 2.3, 3.7, 5.1, 6.8, 8.4, 9.9],
    }

    class Backend:
        vertex_count = 1
        def __init__(self) -> None:
            self.writes = 0
            self.advances = 0
        def initialize(self) -> None:
            return None
        def write_displacement(self, payload: dict[str, Any]) -> None:
            self.writes += 1
        def advance(self, dt_s: float) -> None:
            self.advances += 1
        def read_force(self) -> dict[str, Any]:
            return {"force_N": (2.0, 3.0, 0.0)}
        def finalize(self) -> None:
            return None

    class Worker:
        def __init__(self) -> None:
            self.requests: list[Any] = []
        def step(self, request: Any) -> dict[str, Any]:
            self.requests.append(request)
            return {"q": request.q, "qdot": request.qdot, "qddot": request.qddot}

    cases = []
    for n in (1, 2, 3, 5, 8):
        positions = positions_by_n[n]
        raw = copy.deepcopy(fixture)
        raw["case_identity"]["case_id"] = f"audit_n_{n}"
        raw["case_identity"]["run_id"] = f"audit_run_n_{n}"
        q: list[float] = []
        for node in range(3):
            q.extend([0.0, 0.0, 5.0 * node, 0.0, 0.0, 1.0])
        raw["initial_state"]["q"] = q
        raw["initial_state"]["qdot"] = [0.0] * len(q)
        raw["initial_state"]["qddot"] = [0.0] * len(q)
        raw["base_load"]["vector"] = [0.0] * len(q)
        raw["coupling"]["slices"] = [
            {"slice_id": i, "s_ref_m": s, "slice_length_m": 10.0 / n,
             "unit_span_m": 1.0}
            for i, s in enumerate(positions)
        ]
        raw["initial_state"]["reference_positions_m"] = [[0.0, 0.0, s] for s in positions]
        if n == 1:
            mode = "legacy_point_lumped"
            raw["coupling"].pop("spanwise_load_reconstruction", None)
            raw["coupling"]["force_representation"] = "integrated_slice_force_N"
        else:
            mode = "piecewise_linear_distributed"
            raw["coupling"]["spanwise_load_reconstruction"] = {
                "mode": mode, "endpoint_policy": "nearest_constant",
                "active_start_m": 0.0, "active_end_m": 10.0,
            }
            raw["coupling"]["force_representation"] = "sectional_line_force_Npm"
        config = CaseConfig.from_mapping(raw, base_dir=fixture_path.parent)
        worker = Worker()
        participant = GenericANCFParticipant(config, [Backend() for _ in range(n)], worker)
        participant.initialize()
        step = participant.step()
        participant.finalize()
        request = worker.requests[0]
        payload = request.payload()
        if mode == "legacy_point_lumped":
            legacy_len = len(request.slice_force)
            distributed_len = 0
        else:
            legacy_len = 0
            distributed_len = len(request.spanwise_line_force_Npm)
        if len(step.slices) != n or len(payload) == 0:
            raise AssertionError(f"offline N={n} probe failed")
        if mode != "legacy_point_lumped" and distributed_len != 3 * n:
            raise AssertionError(f"SLD1 N={n} length failed")
        cases.append({
            "Ns": n, "mode": mode, "positions_m": positions,
            "nonuniform_positions": any(
                abs((positions[i + 1] - positions[i]) -
                    (positions[-1] - positions[0]) / max(1, n - 1)) > 1.0e-12
                for i in range(n - 1)
            ),
            "motion_records": len(step.slices),
            "legacy_force_slots": legacy_len,
            "distributed_line_force_slots": distributed_len,
            "encoded_request_bytes": len(payload),
        })

    # N=1 is deliberately not a valid piecewise-linear sample set.
    raw_one = copy.deepcopy(fixture)
    raw_one["coupling"]["spanwise_load_reconstruction"] = {
        "mode": "piecewise_linear_distributed", "endpoint_policy": "nearest_constant",
        "active_start_m": 0.0, "active_end_m": 10.0,
    }
    raw_one["coupling"]["force_representation"] = "sectional_line_force_Npm"
    raw_one["coupling"]["slices"] = [{
        "slice_id": 0, "s_ref_m": 5.0, "slice_length_m": 10.0, "unit_span_m": 1.0,
    }]
    raw_one["initial_state"]["reference_positions_m"] = [[0.0, 0.0, 5.0]]
    try:
        config_one = CaseConfig.from_mapping(raw_one, base_dir=fixture_path.parent)
        worker_one = Worker()
        participant_one = GenericANCFParticipant(config_one, [Backend()], worker_one)
        participant_one.initialize(); participant_one.step(); participant_one.finalize()
        worker_one.requests[0].payload()
    except Exception as exc:
        n1_rejection = {
            "status": "EXPECTED_REJECT",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "source_contract": "KernelModel.validate requires slices >= 2 for PiecewiseLinearDistributed",
        }
    else:
        raise AssertionError("N=1 distributed mode was not rejected")

    positions = positions_by_n[5]
    manifest = SliceManifest(
        "0.2.1", "audit_h_n5", 10.0, 10.0,
        tuple(SliceDefinition(i, s, 2.0, 1.0) for i, s in enumerate(positions)),
    )
    mesh_nodes = (0.0, 1.3, 3.7, 6.2, 10.0)
    H = build_H_for_manifest(manifest, mesh_nodes)
    q: list[float] = []
    for node in mesh_nodes:
        q.extend([0.0, 0.0, node, 0.0, 0.0, 1.0])
    zero = [0.0] * len(q)
    motions = [motion_from_ancf_state(
        manifest, item.slice_id, H[item.slice_id], q, zero, zero,
        step=1, time_s=0.1, reference_position_m=(0.0, 0.0, item.s_ref_m),
    ) for item in manifest.slices]
    mapped = map_integrated_slice_forces(
        manifest, H, {item.slice_id: (1.0, 2.0, 3.0) for item in manifest.slices},
    )
    return {
        "cases": cases,
        "n1_distributed_contract": n1_rejection,
        "nonuniform_H_motion_force_probe": {
            "Ns": 5, "mesh_nodes_m": list(mesh_nodes), "slice_positions_m": positions,
            "H_shapes": {str(k): [len(row) for row in value] for k, value in H.items()},
            "motion_slice_ids": [item.slice_id for item in motions],
            "mapped_slice_ids": sorted(mapped.slice_contributions),
            "mapped_generalized_force_length": len(mapped.generalized_force),
            "slice_node_coincidence_required": False,
        },
        "preCICE_initialize_calls": 0,
        "OpenFOAM_process_starts": 0,
        "cpp_worker_process_starts": 0,
        "numerical_solver_calls": 0,
    }


def matrix() -> list[dict[str, str]]:
    rows = [
        ("kernel arbitrary-N force arrays", "IMPLEMENTED_AND_EVIDENCED", "NOT_APPLICABLE", "SMALL", "Model.slices plus vector contracts; payload probes N=1,2,3,5,8", "Distributed mode requires Ns>=2; legacy supports Ns=1."),
        ("worker arbitrary-N request", "IMPLEMENTED_AND_EVIDENCED", "NOT_APPLICABLE", "SMALL", "runtime slices, positions and 3*Ns values in worker decode", "Dimensions are fixed after the first worker request."),
        ("SLD1 arbitrary-N line-force samples", "PARTIAL", "PARTICIPANT_ONLY", "MEDIUM", "SLD1 and GenericANCFParticipant exist; live launchers do not use them", "Generic path is N/m; fixed launchers remain legacy N."),
        ("explicit arbitrary slice positions", "IMPLEMENTED_AND_EVIDENCED", "NOT_APPLICABLE", "SMALL", "CaseConfig/KernelModel ordered explicit positions; offline nonuniform probes", "No node-coincidence requirement in generic H mapping."),
        ("automatic uniform slice generation", "PARTIAL", "CONFIG_ONLY", "SMALL", "C++ legacy mapping_H3 fallback only", "No Ns+interval config/runner generator; distributed mode requires explicit positions."),
        ("nonuniform slice positions", "IMPLEMENTED_NOT_CURRENTLY_EVIDENCED", "PARTICIPANT_ONLY", "MEDIUM", "manifest/H mapping and offline N=5/N=8", "No real preCICE/OpenFOAM run authorized."),
        ("slice-to-element location", "IMPLEMENTED_AND_EVIDENCED", "NOT_APPLICABLE", "SMALL", "Python bisect_right H mapping and C++ element localization", "Python supports nonuniform ANCF nodes; C++ Model spacing is uniform."),
        ("displacement interpolation at arbitrary S_j", "PARTIAL", "PARTICIPANT_ONLY", "MEDIUM", "generic position_at_s/H motion code", "fixed live scripts use one/three hard-coded q projections."),
        ("force/motion ordering identity", "PARTIAL", "PARTICIPANT_ONLY", "MEDIUM", "manifest IDs and transaction validators; live loop order", "live identity contract is weak under silent permutation."),
        ("generic participant arbitrary-N", "IMPLEMENTED_AND_EVIDENCED", "NOT_APPLICABLE", "SMALL", "backend count equals configured slice count; offline N probes", "Component is not wired by a current generic live launcher."),
        ("preCICE XML arbitrary-N", "HARDCODED_1_3", "XML_GENERATOR_ONLY", "MEDIUM", "single XML templates and fixed three-pair stage XML", "No current Ns XML generator."),
        ("fluid participant topology arbitrary-N", "HARDCODED_1_3", "MULTI_LAYER", "MEDIUM", "single pair or Structure_0000..0002/Fluid_0000..0002", "No generic participant-count topology."),
        ("OpenFOAM case generation arbitrary-N", "PARTIAL", "RUNNER_ONLY", "SMALL", "one --slice-id generator invocation", "Per-slice generation exists, fan-out does not."),
        ("OpenFOAM launch arbitrary-N", "HARDCODED_1_3", "RUNNER_ONLY", "MEDIUM", "current launch evidence is single/three slice", "No generic Ns process lifecycle."),
        ("checkpoint arbitrary-N", "PARTIAL", "PARTICIPANT_ONLY", "MEDIUM", "AtomicCheckpointManager validates all manifest IDs", "direct preCICE backend has no checkpoint callbacks."),
        ("rollback arbitrary-N", "PARTIAL", "PARTICIPANT_ONLY", "MEDIUM", "file scheduler recovery restores all slices", "live direct preCICE lifecycle is not N-generic."),
        ("single global ANCF solve for all slices", "IMPLEMENTED_NOT_CURRENTLY_EVIDENCED", "PARTICIPANT_ONLY", "MEDIUM", "one structure.correct_all after all loads; one fixed three-slice worker", "No arbitrary-N live SLD1 end-to-end proof."),
        ("static-prestress startup", "PARTIAL", "MULTI_LAYER", "MEDIUM", "identity-checked CaseConfig state artifacts and initializer", "C++ prestress driver hard-codes slices=1."),
        ("configuration single-source-of-truth", "PARTIAL", "MULTI_LAYER", "MEDIUM", "manifest/config identities plus duplicated XML/runner/fixtures", "Cross-layer binding is incomplete."),
        ("2-D/3-D interface capability", "PARTIAL", "PARTICIPANT_ONLY", "MEDIUM", "3D kernel/wire but CaseConfig x,y and XML dimensions=2", "Current coupled interface is STRUCTURE_3D_INTERFACE_2D."),
    ]
    return [
        {"capability": a, "classification": b, "gap_layer": c, "scope": d, "evidence": e, "notes": f}
        for a, b, c, d, e, f in rows
    ]


def main() -> int:
    if git("rev-parse", "HEAD") != HEAD or git("rev-parse", "HEAD~1") != PARENT:
        raise RuntimeError("SOURCE_IDENTITY_CHANGED")
    if git("rev-list", "-n", "1", "ancf-coupling-baseline-v1") != TAG_TARGET:
        raise RuntimeError("baseline tag target mismatch")
    if subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode != 0:
        raise RuntimeError("STOPPED_DIRTY_TRACKED_STATE")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0:
        raise RuntimeError("STOPPED_DIRTY_INDEX_STATE")
    sources = source_inventory()
    probe = offline_probe()
    caps = matrix()

    protocol = f"""# {PREFIX}_PROTOCOL

Read-only current-line audit for production commit `{HEAD}`. No production
source is modified and no G1, CFD, FSI, VIV, OpenFOAM or preCICE runtime is
started. Only offline parser, H-matrix, fake-backend and wire-payload probes
are allowed.

Arbitrary-N means runtime Ns, stable S_j identity, unambiguous force/motion
ordering, dynamic topology/runner creation, and N-aware checkpoint/rollback at
the same end-to-end path. A generic array in the kernel is not sufficient.

The old tag `ancf-coupling-baseline-v1` remains bound to `{TAG_TARGET}`.
`ANCF_SPANWISE_DISTRIBUTED_LOAD_RECONSTRUCTION_V1` and its convergence closure
remain PASS. G1 and independent structural validation remain NOT_CLOSED.

The PiecewiseLinearDistributed contract requires at least two samples. Ns=1
is therefore probed in preserved LegacyPointLumped mode; distributed Ns=1 is
expected to be rejected, not silently downgraded.
"""
    write(f"{PREFIX}_PROTOCOL.md", protocol)

    source_trace = f"""# Source trace

## Generic path

1. `tools/precice_ancf_adapter_v1/ancf_case_config_v1.py:240-285` reads an
   explicit `coupling.slices` list, validates IDs 0..N-1, ordered S_j,
   lengths/spans, force representation and distributed active interval.
2. `tools/precice_ancf_adapter_v1/ancf_generic_participant_v1.py:98-230`
   checks one backend per configured slice, evaluates motion at each S_j,
   reads force, performs the N -> N/m conversion and builds one request.
3. `src/coupling/multi_slice_mapping/mapping.py:544-735` defines the old
   OpenFOAM [N] -> [N/m] -> integrated [N] conversion. `:821-857` validates
   complete transactions by slice_id.
4. `src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py:250-330`
   appends SLD1; `:360-385` rejects mixing legacy N and distributed N/m.
5. `src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp:371-420`
   reads runtime slices/positions/trailer; `:657-704` creates samples at those
   positions and calls the distributed load path.
6. `src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp:436-522`
   applies zero/nearest-constant/piecewise-linear reconstruction and split
   Gauss-3 H^T f integration.
7. `src/coupling/multi_slice_driver/scheduler.py:397-535` reads all slice
   loads and invokes one structure correction. `src/coupling/checkpoint/
   atomic_checkpoint.py:207-418` stores every manifest slice plus structure.

## Live-path limitation

`src/coupling/precice_adapter_v1/precice_backend.py:14-95` is only a generic
one-participant backend and has no unit/manifest/checkpoint orchestration.
The tracked single-slice launcher maps one force to worker slot 0. The tracked
three-slice launcher hard-codes `slices=3`, `range(3)`, three participant names
and q[1]/q[7]/q[13], and sends legacy integrated `slice_force`. The OpenFOAM
generator accepts one slice per invocation and has no Ns fan-out.

## Source identities

{json.dumps(sources, ensure_ascii=False, indent=2)}
"""
    write(f"{PREFIX}_SOURCE_TRACE.md", source_trace)

    slice_identity = """# Slice identity audit

`slice_id` is required to be exactly 0..Ns-1. `s_ref_m` is strictly ordered,
unique and bounded. `SliceManifest` hashes the complete slice table. Motion
and load records carry slice_id, S_j, slice length, unit span, step/time and
manifest/config hashes. `validate_record_transaction` rejects duplicates and
missing IDs and restores ID order.

Ns=5 example:

| j | id | S_j | fluid source | live preCICE entity | force slot | H evaluation | motion destination |
|---:|---:|---:|---|---|---|---|---|
|0|0|0.4|slice_0000|Structure_0000 in fixed 3-slice pattern|0..2|H(S_0)|slice_0000|
|1|1|1.9|slice_0001|Structure_0001 in fixed 3-slice pattern|3..5|H(S_1)|slice_0001|
|2|2|4.1|slice_0002|Structure_0002 in fixed 3-slice pattern|6..8|H(S_2)|slice_0002|
|3|3|7.6|slice_0003|no current generated entity|9..11|H(S_3)|slice_0003|
|4|4|9.8|slice_0004|no current generated entity|12..14|H(S_4)|slice_0004|

The file-exchange path has a strong ID contract. The live preCICE scripts bind
participant names and force slots by fixed loop order, so a silent permutation
is not rejected by a shared current-line manifest. Live classification:
`SLICE_IDENTITY_CONTRACT_WEAK`.
"""
    write(f"{PREFIX}_SLICE_IDENTITY.md", slice_identity)

    topology = """# Precise topology and runner audit

- Single-slice XML: one Structure/Fluid pair, fixed Structure-Mesh and
  Fluid-Mesh, 2-D Displacement/Force data.
- Three-slice launcher: three separate Structure_i/Fluid_i pairs and one
  persistent C++ worker. Source has fixed `nargs=3`, `slices=3` and `range(3)`.
- Generic participant: accepts an arbitrary sequence of injected backends and
  emits one global worker request, but no current live launcher connects this
  generic object to generated arbitrary-N preCICE XML and OpenFOAM processes.
- OpenFOAM generator: one `--slice-id`, `--s-ref-m`, `--slice-length-m` and
  `--unit-span-m` per call; no Ns+interval/fan-out process runner.

The current live topology is therefore fixture-based 1 or 3 pairs, not a
parameterized arbitrary-N topology. The SLD1 line-force path is implemented in
the generic request path but is not used by those fixed live launchers.
"""
    write(f"{PREFIX}_PRECISE_TOPOLOGY.md", topology)

    ownership = """# Configuration ownership audit

| Field | Current classification | Evidence/risk |
|---|---|---|
| L, elements, section, environment | DUPLICATED_WITH_VALIDATION | CaseConfig, KernelModel, fixtures and OpenFOAM CLI each carry values |
| Ns | DUPLICATED_UNCHECKED | config is dynamic; fixed live launchers independently fix 1 or 3 |
| S_j | DUPLICATED_WITH_VALIDATION | manifest/config/worker/OpenFOAM case carry values; live XML is not bound to manifest |
| unit_span/slice_length | DUPLICATED_WITH_VALIDATION | generic conversion validates; XML has no dimensional metadata |
| mapping mode/active interval | SINGLE_SOURCE_OF_TRUTH in generic config | fixed live launchers do not expose SLD1 |
| participant/mesh/data names | HARDCODED | XML templates and stage scripts |
| initial state/boundary/damping/prestress | DUPLICATED_WITH_VALIDATION | identity checks exist, but current live fixtures are separate |
| checkpoint/run identity | DUPLICATED_WITH_VALIDATION | N-aware file scheduler versus fixed direct preCICE scripts |

Smallest safe repair layer: a bounded config/participant/XML/runner
integration, not a kernel rewrite.
"""
    write(f"{PREFIX}_CONFIG_OWNERSHIP.md", ownership)

    checkpoint = """# Checkpoint and rollback audit

The generic file scheduler executes one barrier: all motions, all CFD slice
advances, all loads, one global ANCF correction, then one checkpoint commit.
`AtomicCheckpointManager` requires the exact manifest ID set and persists every
slice process plus the structure state; restart validates hashes, IDs, time and
state dimensions. This path is N-aware.

`PrecicePythonBackend` exposes initialize/write/advance/read/finalize only and
`ParticipantSession` has no checkpoint callback. Historical direct scripts
contain checkpoint calls only in fixed single/three-slice fixtures. Therefore
arbitrary-N preCICE time-window checkpoint/rollback is not current-line
evidenced.

One global ANCF state is proven in the file scheduler and fixed three-slice
worker coordinator. The arbitrary-N live SLD1 path is not yet wired.
"""
    write(f"{PREFIX}_CHECKPOINT_AUDIT.md", checkpoint)

    caps = matrix()
    csv_name = f"{PREFIX}_CAPABILITY_MATRIX.csv"
    csv_path = OUT / csv_name
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["capability", "classification", "gap_layer", "scope", "evidence", "notes"])
        writer.writeheader(); writer.writerows(caps)

    result = {
        "schema_version": 1,
        "audit": PREFIX,
        "status": "PASS",
        "decision_gate": "ARBITRARY_N_SMALL_REFACTOR_REQUIRED_BEFORE_REAL_SMOKE",
        "decision_reason": "Generic kernel/wire/config and offline global scheduler are coherent; live preCICE/OpenFOAM topology, runner, SLD1 binding and checkpoint lifecycle are not unified for arbitrary N.",
        "repository": {"head": HEAD, "parent": PARENT, "branch": git("branch", "--show-current"), "tracked_diff_clean": True, "index_clean": True, "tag": "ancf-coupling-baseline-v1", "tag_target": TAG_TARGET},
        "production_modifications": 0,
        "validation_status": {"G1_CURRENT_LINE_VALIDATION": "NOT_CLOSED", "ANCF_INDEPENDENT_STRUCTURAL_VALIDATION": "NOT_CLOSED", "ANCF_SPANWISE_DISTRIBUTED_LOAD_RECONSTRUCTION_V1": "PASS retained", "ANCF_SPANWISE_RECONSTRUCTION_CONVERGENCE_CLOSURE_V1": "PASS retained"},
        "source_inventory": sources,
        "offline_probe": probe,
        "capability_matrix": caps,
        "gaps": [
            {"item": "Ns+interval slice generator", "layer": "CONFIG_ONLY", "scope": "SMALL"},
            {"item": "arbitrary-N preCICE XML/participant/runner", "layer": "MULTI_LAYER", "scope": "MEDIUM"},
            {"item": "live SLD1 participant binding", "layer": "PARTICIPANT_ONLY", "scope": "MEDIUM"},
            {"item": "live arbitrary-N checkpoint/rollback", "layer": "PARTICIPANT_ONLY", "scope": "MEDIUM"},
            {"item": "full 3-D coupled interface", "layer": "PARTICIPANT_ONLY", "scope": "MEDIUM"},
        ],
        "execution_counts": {"offline_topology_cases": 5, "preCICE_initialize": 0, "OpenFOAM": 0, "CFD": 0, "FSI": 0, "VIV": 0, "G1": 0, "numerical_solver": 0},
        "wire_units": {"legacy": "OpenFOAM integrated [N] -> unit-span divide [N/m] -> slice-length multiply [N] -> H(S_j)^T F_j", "distributed": "OpenFOAM integrated [N] -> unit-span divide [N/m] -> SLD1 -> split Gauss-3 integral H^T f_h(s)", "silent_unit_reinterpretation": False},
    }
    write_json(f"{PREFIX}_RESULT.json", result)

    report = f"""# {PREFIX} report

## Final classification

`{PREFIX} = PASS` (complete read-only classification).

**Decision gate:** `ARBITRARY_N_SMALL_REFACTOR_REQUIRED_BEFORE_REAL_SMOKE`.

The kernel, worker wire, CaseConfig, generic participant and offline global
scheduler have explicit-N capabilities. The current real preCICE/OpenFOAM
surface remains single-slice or fixed three-slice: there is no one authoritative
Ns manifest driving XML, participant construction, OpenFOAM fan-out, SLD1
requests, motion outputs and checkpoint callbacks.

## Answers to the core questions

- True end-to-end arbitrary Ns: **not established**.
- Explicit nonuniform S_j: **implemented in generic/config/file layers and
  offline evidenced**.
- Ns + interval automatic positions: **not implemented in current coupling
  config/runner**; only a legacy C++ fallback exists.
- Force identity: strong `slice_id`/manifest contract in file path, weak
  loop-order binding in live preCICE fixtures.
- PiecewiseLinearDistributed: generic participant can emit N/m SLD1, but fixed
  live launchers still send legacy integrated N.
- Motion: generic H/position interpolation exists; live scripts hard-code one
  or three q projections.
- preCICE/XML/runner: current fixture topology is 1 or 3, not arbitrary N.
- Checkpoint/rollback: N-aware in generic file scheduler, not in generic live
  preCICE lifecycle.
- Global ANCF state: one global correction is used by file scheduler and fixed
  three-slice worker; arbitrary-N live SLD1 is not wired.

## Offline probe

Ns=1,2,3,5,8 were constructed. Ns=5 and Ns=8 used nonuniform explicit
positions. N=1 used LegacyPointLumped; N=1 distributed was rejected as the
expected two-sample contract. H interpolation with nonuniform ANCF nodes and
non-node S_j passed. No external runtime or numerical solver was invoked.

## Protected claims

Production modifications = 0; no commit and no push. G1 and independent
structural validation remain NOT_CLOSED. Prior distributed-load PASS and
reconstruction-closure PASS remain unchanged.
"""
    write(f"{PREFIX}_REPORT.md", report)

    manifest_names = [
        f"{PREFIX}_PROTOCOL.md", f"{PREFIX}_SOURCE_TRACE.md",
        f"{PREFIX}_SLICE_IDENTITY.md", f"{PREFIX}_PRECISE_TOPOLOGY.md",
        f"{PREFIX}_CONFIG_OWNERSHIP.md", f"{PREFIX}_CHECKPOINT_AUDIT.md",
        csv_name, f"{PREFIX}_RESULT.json", f"{PREFIX}_REPORT.md",
    ]
    lines = [f"# SHA256 manifest for {PREFIX}", f"production_head {HEAD}", f"baseline_tag_target {TAG_TARGET}", ""]
    for name in manifest_names:
        lines.append(f"{sha256(OUT / name)}  runtime/ANCF_validation/{name}")
    for item in sources:
        lines.append(f"{item['sha256']}  {item['relative_path']}")
    write(f"{PREFIX}_SHA256_MANIFEST.txt", "\n".join(lines))

    print(json.dumps({"status": "PASS", "decision_gate": result["decision_gate"], "head": HEAD, "offline_N": [1, 2, 3, 5, 8], "external_runs": result["execution_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
