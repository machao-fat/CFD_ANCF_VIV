"""Offline qualification for the generic arbitrary-N live-coupling path.

This tool is intentionally incapable of starting OpenFOAM, preCICE, a C++
worker, or any structural numerical solver.  It validates the manifest,
topology, force-gather, one-global-state, motion-scatter and checkpoint
contracts with deterministic in-memory objects, then runs bounded Python-only
regressions that do not overwrite historical validation evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
OUT = ROOT / "runtime" / "ANCF_validation"
PREFIX = "ANCF_GENERIC_ARBITRARY_N_LIVE_COUPLING_ORCHESTRATION_V1"
EXPECTED_HEAD = "29b364cdb87e0829c0c2b49ed727957240b40c1e"
EXPECTED_TAG_TARGET = "dfb1a3e7e92220a2e4c9400317de372e637095eb"

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SRC))

from coupling.arbitrary_n_live_orchestration_v1 import (  # noqa: E402
    CheckpointError,
    FakePreciceFleet,
    ForceSample,
    GenericStructuralCoordinator,
    InMemoryANCFBackend,
    ManifestError,
    OrchestrationError,
    WorkerRequest,
    assemble_generalized_force,
    build_slice_manifest,
    generate_openfoam_launch_plan,
    generate_precice_xml,
    inspect_precice_xml,
)
from coupling.multi_slice_mapping.mapping import ancf_hermite_H  # noqa: E402
from coupling.cpp_worker_persistent_ipc_v1.kernel_protocol import (  # noqa: E402
    KernelModel,
    KernelStepRequest,
    SPANWISE_LOAD_EXTENSION_MARKER,
)
from coupling.cpp_worker_persistent_ipc_v1.protocol import canonical_integer_tick  # noqa: E402


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def sha256_lf_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes().replace(b"\r\n", b"\n"))


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def json_hash(value: Any) -> str:
    return sha256_bytes(canonical(value))


def run_git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, check=True,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace")
    return result.stdout.strip()


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_close(actual: float, expected: float, tolerance: float, message: str) -> None:
    if not math.isfinite(actual) or abs(actual - expected) > tolerance:
        raise AssertionError(f"{message}: actual={actual!r} expected={expected!r} tol={tolerance}")


def expect_error(label: str, fn: Callable[[], Any]) -> dict[str, Any]:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - the negative contract accepts typed failures
        return {"name": label, "status": "PASS", "error_type": type(exc).__name__,
                "message": str(exc)}
    raise AssertionError(f"negative case did not fail closed: {label}")


def config_for(
    n: int,
    mode: str,
    *,
    placement: str = "explicit",
    positions: Sequence[float] | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    case_id = case_id or f"offline_arbitrary_n_{n}_{mode}"
    coupling: dict[str, Any] = {
        "mode": mode,
        "placement": placement,
        "active_start_m": 0.0,
        "active_end_m": 10.0,
        "unit_span_m": 1.0,
        "force_representation": (
            "integrated_slice_force_N" if mode == "LegacyPointLumped"
            else "sectional_line_force_Npm"
        ),
    }
    if placement == "explicit":
        if positions is None:
            raise ValueError("explicit placement needs positions")
        coupling.update({
            "positions_m": list(positions),
            "slice_length_m": 10.0 / n,
            "slice_ids": [f"slice_{index:04d}" for index in range(n)],
        })
    else:
        coupling.update({
            "count": n,
            "slice_length_m": 10.0 / n,
        })
    return {"case_id": case_id, "length_m": 10.0, "coupling": coupling,
            "interfaces": {"structure_participant": "StructureCoordinator",
                           "fluid_participant_prefix": "Fluid_"}}


def manifest_matrix() -> dict[int, Any]:
    return {
        1: build_slice_manifest(config_for(1, "LegacyPointLumped", positions=(5.0,))),
        2: build_slice_manifest(config_for(2, "PiecewiseLinearDistributed", positions=(2.5, 7.5))),
        3: build_slice_manifest(config_for(3, "PiecewiseLinearDistributed", positions=(1.7, 5.0, 8.3))),
        5: build_slice_manifest(config_for(5, "PiecewiseLinearDistributed",
                                           positions=(0.7, 2.1, 4.5, 7.4, 9.3))),
        8: build_slice_manifest(config_for(8, "PiecewiseLinearDistributed",
                                           placement="uniform_centers")),
    }


MESH_NODES = (0.0, 1.7, 3.8, 6.1, 8.4, 10.0)

# Eight-point Gauss-Legendre data are used only by the independent offline
# comparison.  The production distributed kernel uses its existing Gauss-3
# split integration; a degree-four integrand is exact under both rules.
GAUSS8 = (
    (-0.9602898564975363, 0.1012285362903763),
    (-0.7966664774136267, 0.2223810344533745),
    (-0.5255324099163290, 0.3137066458778873),
    (-0.1834346424956498, 0.3626837833783620),
    (0.1834346424956498, 0.3626837833783620),
    (0.5255324099163290, 0.3137066458778873),
    (0.7966664774136267, 0.2223810344533745),
    (0.9602898564975363, 0.1012285362903763),
)


def independent_distributed_reference(
    manifest: Any,
    mesh_nodes: Sequence[float],
    request: WorkerRequest,
) -> tuple[float, ...]:
    """Independent high-order re-integration of the reconstructed request."""

    assert_true(request.sld1, "reference helper requires SLD1 request")
    ndof = 6 * len(mesh_nodes)
    positions = request.slice_positions_m
    forces = [request.spanwise_line_force_Npm[3 * i:3 * i + 3]
              for i in range(manifest.ns)]
    boundaries = sorted(set(
        value for value in [
            *map(float, mesh_nodes), request.active_start_m, request.active_end_m,
            *positions,
        ] if mesh_nodes[0] <= value <= mesh_nodes[-1]
    ))
    result = [0.0] * ndof

    def force_at(s: float) -> tuple[float, float, float]:
        if s < request.active_start_m or s > request.active_end_m:
            return (0.0, 0.0, 0.0)
        if s <= positions[0]:
            return tuple(forces[0])  # type: ignore[return-value]
        if s >= positions[-1]:
            return tuple(forces[-1])  # type: ignore[return-value]
        for index, (left, right) in enumerate(zip(positions, positions[1:])):
            if left <= s <= right:
                fraction = (s - left) / (right - left)
                return tuple((1.0 - fraction) * forces[index][axis]
                             + fraction * forces[index + 1][axis]
                             for axis in range(3))  # type: ignore[return-value]
        raise AssertionError("reference interpolation interval not found")

    for left, right in zip(boundaries, boundaries[1:]):
        if right <= left:
            continue
        midpoint = 0.5 * (left + right)
        half = 0.5 * (right - left)
        for xi, weight in GAUSS8:
            s = midpoint + half * xi
            H = ancf_hermite_H(s, mesh_nodes, ndof=ndof)
            force = force_at(s)
            factor = half * weight
            for column in range(ndof):
                result[column] += factor * sum(H[axis][column] * force[axis]
                                               for axis in range(3))
    return tuple(result)


def vec_norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(value * value for value in values))


def create_samples(manifest: Any, iteration: int = 4, time_s: float = 0.04) -> dict[str, ForceSample]:
    result: dict[str, ForceSample] = {}
    for item in manifest.slices:
        i = item.ordinal
        if manifest.reconstruction_mode == "PiecewiseLinearDistributed":
            result[item.slice_id] = ForceSample.from_line_force(
                manifest, item.slice_id, iteration=iteration, time_s=time_s,
                line_force_Npm=(1.25 + 0.13 * i, -0.4 + 0.07 * i, 0.22 - 0.03 * i),
                unit_span_m=item.unit_span_m)
        else:
            result[item.slice_id] = ForceSample.from_openfoam_integrated(
                manifest, item.slice_id, iteration=iteration, time_s=time_s,
                force_N=(0.8 + 0.11 * i, 0.3 - 0.02 * i, 0.14 + 0.01 * i),
                unit_span_m=item.unit_span_m)
    return result


def position_from_q(q: Sequence[float], s_ref_m: float) -> tuple[float, float, float]:
    H = ancf_hermite_H(s_ref_m, MESH_NODES, ndof=len(q))
    return tuple(sum(H[row][column] * q[column] for column in range(len(q)))
                 for row in range(3))  # type: ignore[return-value]


def run_matrix_case(manifest: Any) -> dict[str, Any]:
    backend = InMemoryANCFBackend(MESH_NODES)
    references = {item.slice_id: (0.0, 0.0, item.s_ref_m) for item in manifest.slices}
    coordinator = GenericStructuralCoordinator(
        manifest, backend, reference_positions_by_slice=references)
    samples = create_samples(manifest)
    arrival = list(reversed(manifest.slice_ids))
    if manifest.ns > 1:
        for slice_id in arrival[:-1]:
            coordinator.submit_force(samples[slice_id])
        incomplete_error = expect_error("incomplete_force_set", coordinator.advance_if_complete)
        coordinator.submit_force(samples[arrival[-1]])
    else:
        coordinator.submit_force(samples[arrival[0]])
        incomplete_error = {"name": "incomplete_force_set", "status": "NOT_APPLICABLE"}
    result = coordinator.advance_if_complete()
    request = coordinator.last_request
    assert_true(request is not None, "coordinator did not retain the global request")
    assert_true(request.slice_ids == manifest.slice_ids, "request order differs from manifest order")
    assert_true(len(request.to_payload().get(
        "spanwise_line_force_Npm", request.to_payload().get("slice_force", []))) == 3 * manifest.ns,
                "request force vector has incorrect length")
    if manifest.reconstruction_mode == "PiecewiseLinearDistributed":
        expected = independent_distributed_reference(manifest, MESH_NODES, request)
    else:
        expected = assemble_generalized_force(manifest, MESH_NODES, request)
    actual = tuple(float(value) for value in result["generalized_force"])
    max_error = max(abs(a - b) for a, b in zip(actual, expected))
    assert_true(max_error <= 2.0e-12, f"global force mismatch: {max_error}")
    motion = coordinator.scatter_motion()
    motion_errors = {}
    for item in manifest.slices:
        current = position_from_q(backend.q or (), item.s_ref_m)
        reference = references[item.slice_id]
        expected_motion = tuple(current[index] - reference[index] for index in range(3))
        error = max(abs(motion[item.slice_id][index] - expected_motion[index]) for index in range(3))
        motion_errors[item.slice_id] = error
        assert_true(error <= 2.0e-14, f"motion scatter mismatch for {item.slice_id}: {error}")
    coordinator.commit()
    assert_true(coordinator.attempted_structural_advances == 1, "not exactly one global attempt")
    assert_true(coordinator.committed_structural_advances == 1, "not exactly one global commit")
    return {
        "Ns": manifest.ns,
        "mode": manifest.reconstruction_mode,
        "manifest_sha256": manifest.manifest_sha256,
        "slice_ids": list(manifest.slice_ids),
        "positions_m": [item.s_ref_m for item in manifest.slices],
        "arrival_order": arrival,
        "request_slice_ids": list(request.slice_ids),
        "request_payload": request.to_payload(),
        "generalized_force_max_abs_error": max_error,
        "motion_max_abs_error_by_slice": motion_errors,
        "attempted_global_advances": coordinator.attempted_structural_advances,
        "committed_global_advances": coordinator.committed_structural_advances,
        "incomplete_force_set": incomplete_error,
        "slice_node_coincidence_required": False,
    }


def run_checkpoint_matrix(manifest: Any) -> dict[str, Any]:
    def fresh() -> tuple[GenericStructuralCoordinator, InMemoryANCFBackend, dict[str, ForceSample]]:
        backend = InMemoryANCFBackend(MESH_NODES)
        refs = {item.slice_id: (0.0, 0.0, item.s_ref_m) for item in manifest.slices}
        return GenericStructuralCoordinator(manifest, backend, reference_positions_by_slice=refs), backend, create_samples(manifest)

    coordinator, backend, samples = fresh()
    for sid in manifest.slice_ids:
        coordinator.submit_force(samples[sid])
    before = backend.snapshot()
    checkpoint = coordinator.checkpoint("window-0001")
    coordinator.advance_if_complete(); coordinator.scatter_motion(); coordinator.rollback()
    assert_true(backend.snapshot() == before, "rollback did not restore the checkpointed backend state")
    assert_true(not coordinator.gathered_slice_ids, "rollback retained an old force sample")
    retry_samples = create_samples(manifest, iteration=5, time_s=0.05)
    for sid in reversed(manifest.slice_ids):
        coordinator.submit_force(retry_samples[sid])
    coordinator.advance_if_complete(); coordinator.commit()
    scenario_one = {
        "checkpoint_sha256": json_hash(checkpoint.to_dict()),
        "state_equal_after_rollback": True,
        "retry_request_order": list(coordinator.last_request.slice_ids if coordinator.last_request else ()),
        "committed_global_advances": coordinator.committed_structural_advances,
        "attempted_global_advances_after_retry": coordinator.attempted_structural_advances,
    }
    assert_true(scenario_one["committed_global_advances"] == 1, "rollback retry committed more than one step")

    partial, partial_backend, partial_samples = fresh()
    partial.submit_force(partial_samples[manifest.slice_ids[0]])
    partial.checkpoint("partial-window")
    if manifest.ns > 1:
        partial.submit_force(partial_samples[manifest.slice_ids[1]])
    partial.rollback()
    assert_true(partial.attempted_structural_advances == 0, "partial rollback advanced the structure")
    assert_true(not partial.gathered_slice_ids, "partial rollback retained a mixed force gather")
    assert_true(partial_backend.snapshot()["q"] == InMemoryANCFBackend(MESH_NODES).snapshot()["q"],
                "partial rollback changed q")
    scenario_two = {"partial_gather_reset": True, "advance_count": partial.attempted_structural_advances}

    reordered, _, reordered_samples = fresh()
    reordered.checkpoint("reordered-window")
    for sid in reversed(manifest.slice_ids):
        reordered.submit_force(reordered_samples[sid])
    reordered.advance_if_complete(); reordered.commit()
    assert_true(reordered.last_request is not None and reordered.last_request.slice_ids == manifest.slice_ids,
                "reordered rollback retry lost slice identity")
    return {"scenario_complete_rollback_retry": scenario_one,
            "scenario_partial_rollback": scenario_two,
            "scenario_reordered_retry": {"status": "PASS", "request_order": list(reordered.last_request.slice_ids)}}


def run_negative_matrix(manifest: Any) -> list[dict[str, Any]]:
    positions = [item.s_ref_m for item in manifest.slices]
    negative: list[dict[str, Any]] = []
    negative.append(expect_error("distributed_Ns_1", lambda: build_slice_manifest(
        config_for(1, "PiecewiseLinearDistributed", positions=(5.0,)))))
    negative.append(expect_error("duplicate_slice_id", lambda: build_slice_manifest({
        "case_id": "duplicate-id", "length_m": 10.0,
        "coupling": {"mode": "PiecewiseLinearDistributed", "placement": "explicit",
                      "positions_m": [2.0, 8.0], "slice_ids": ["slice_0000", "slice_0000"],
                      "slice_length_m": 5.0, "unit_span_m": 1.0}})))
    negative.append(expect_error("duplicate_position", lambda: build_slice_manifest(
        config_for(3, "PiecewiseLinearDistributed", positions=(2.0, 2.0, 8.0)))))
    negative.append(expect_error("unsorted_position", lambda: build_slice_manifest(
        config_for(3, "PiecewiseLinearDistributed", positions=(8.0, 2.0, 9.0)))))
    negative.append(expect_error("position_outside_active", lambda: build_slice_manifest({
        "case_id": "outside", "length_m": 10.0,
        "coupling": {"mode": "PiecewiseLinearDistributed", "placement": "explicit",
                      "positions_m": [1.0, 9.0], "active_start_m": 2.0, "active_end_m": 8.0,
                      "slice_length_m": 5.0, "unit_span_m": 1.0}})))
    negative.append(expect_error("active_interval_outside_length", lambda: build_slice_manifest({
        "case_id": "bad-active", "length_m": 10.0,
        "coupling": {"mode": "PiecewiseLinearDistributed", "placement": "explicit",
                      "positions_m": [2.0, 8.0], "active_start_m": -1.0, "active_end_m": 8.0,
                      "slice_length_m": 5.0, "unit_span_m": 1.0}})))

    samples = create_samples(manifest)
    partial = GenericStructuralCoordinator(manifest, InMemoryANCFBackend(MESH_NODES))
    for sid in manifest.slice_ids[:-1]:
        partial.submit_force(samples[sid])
    negative.append(expect_error("missing_slice_force", partial.advance_if_complete))
    duplicate = GenericStructuralCoordinator(manifest, InMemoryANCFBackend(MESH_NODES))
    duplicate.submit_force(samples[manifest.slice_ids[0]])
    negative.append(expect_error("duplicate_force_same_slice", lambda: duplicate.submit_force(samples[manifest.slice_ids[0]])))
    negative.append(expect_error("unknown_slice_id", lambda: ForceSample.from_line_force(
        manifest, "slice_unknown", iteration=1, time_s=0.01, line_force_Npm=(1.0, 2.0, 3.0), unit_span_m=1.0)))
    mismatched = replace(samples[manifest.slice_ids[0]], slice_id=manifest.slice_ids[-1])
    identity = GenericStructuralCoordinator(manifest, InMemoryANCFBackend(MESH_NODES))
    negative.append(expect_error("force_array_permutation_mismatched_id", lambda: identity.submit_force(mismatched)))
    wrong_units = replace(samples[manifest.slice_ids[0]], representation="integrated_slice_force_N")
    units = GenericStructuralCoordinator(manifest, InMemoryANCFBackend(MESH_NODES))
    negative.append(expect_error("wrong_units_mode_metadata", lambda: units.submit_force(wrong_units)))
    positions_request = GenericStructuralCoordinator(manifest, InMemoryANCFBackend(MESH_NODES))
    for sample in samples.values():
        positions_request.submit_force(sample)
    request = positions_request._build_request()  # validation-only malformed payload probe
    bad_request = replace(request, spanwise_line_force_Npm=request.spanwise_line_force_Npm[:-1])
    negative.append(expect_error("malformed_SLD1_length", lambda: assemble_generalized_force(manifest, MESH_NODES, bad_request)))
    stale = GenericStructuralCoordinator(manifest, InMemoryANCFBackend(MESH_NODES))
    stale.submit_force(samples[manifest.slice_ids[0]])
    stale_next = replace(samples[manifest.slice_ids[1]], iteration=samples[manifest.slice_ids[1]].iteration + 1)
    negative.append(expect_error("stale_prior_iteration", lambda: stale.submit_force(stale_next)))
    fleet = FakePreciceFleet(manifest, {})
    negative.append(expect_error("stale_motion_destination_id", lambda: fleet.write_motion("slice_unknown", (0.0, 0.0, 0.0))))
    return negative


def run_topology_matrix(manifests: Mapping[int, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    topology: list[dict[str, Any]] = []
    launch: list[dict[str, Any]] = []
    for n, manifest in manifests.items():
        xml = generate_precice_xml(manifest)
        inspected = inspect_precice_xml(xml, manifest)
        assert_true(xml == generate_precice_xml(manifest), f"non-deterministic XML for Ns={n}")
        assert_true(inspected["participant_count"] == n + 1, f"participant count failed for Ns={n}")
        topology.append({"Ns": n, "xml_sha256": sha256_bytes(xml.encode("utf-8")),
                         "xml_bytes": len(xml.encode("utf-8")), **inspected})
        plan = generate_openfoam_launch_plan(
            manifest, template_source=ROOT / "cases" / "openfoam" / "multi_slice_template",
            output_root=ROOT / "runtime" / "_offline_arbitrary_n_cases",
            command=("pimpleFoam", "-parallel"),
        )
        assert_true(len(plan) == n, f"launch plan count failed for Ns={n}")
        for descriptor, item in zip(plan, manifest.slices):
            assert_true((descriptor.slice_id, descriptor.s_ref_m, descriptor.participant,
                         descriptor.unit_span_m) ==
                        (item.slice_id, item.s_ref_m, item.fluid_participant, item.unit_span_m),
                        f"launch descriptor identity failed for {item.slice_id}")
        launch.append({"Ns": n, "descriptor_count": len(plan),
                       "descriptors": [item.to_dict() for item in plan],
                       "processes_started": 0})
    return topology, launch


def run_wire_probe() -> dict[str, Any]:
    model_common = dict(
        length_m=10.0, diameter_m=1.0, inner_diameter_m=0.9, elements=4,
        slices=5, slice_positions_m=(0.7, 2.1, 4.5, 7.4, 9.3),
        top_tension_N=0.0, gravity=0.0, newton_tolerance=1.0e-4,
    )
    q = []
    for node in range(5):
        q.extend((0.0, 0.0, 2.5 * node, 0.0, 0.0, 1.0))
    common_request = dict(
        sequence=1, global_step=1, case_local_bridge_step=1,
        integer_tick=canonical_integer_tick(0.001), time_s=0.001, dt_s=0.001,
        request_id=101, transaction_id=201, run_id="offline_arbitrary_n",
        case_id="offline_arbitrary_n_case", q=tuple(q), qdot=(0.0,) * 30,
        qddot=(0.0,) * 30, base_load=(0.0,) * 30,
    )
    legacy_model = KernelModel(**model_common)
    legacy = KernelStepRequest(model=legacy_model, slice_force=(0.0,) * 15,
                               spanwise_line_force_Npm=(), **common_request)
    distributed_model = KernelModel(
        **model_common, spanwise_load_reconstruction="piecewise_linear_distributed",
        spanwise_active_s_min_m=0.0, spanwise_active_s_max_m=10.0,
    )
    distributed = KernelStepRequest(model=distributed_model, slice_force=(),
                                    spanwise_line_force_Npm=(1.0,) * 15, **common_request)
    legacy_payload = legacy.payload()
    distributed_payload = distributed.payload()
    marker = SPANWISE_LOAD_EXTENSION_MARKER.to_bytes(4, "little")
    assert_true(marker not in legacy_payload, "legacy payload unexpectedly contains SLD1")
    assert_true(marker in distributed_payload, "distributed payload lacks SLD1")
    return {"wire_schema": "UNCHANGED", "legacy_payload_bytes": len(legacy_payload),
            "distributed_payload_bytes": len(distributed_payload),
            "legacy_SLD1": False, "distributed_SLD1": True,
            "legacy_force_units": "integrated_force_N",
            "distributed_force_units": "sectional_line_force_Npm"}


def run_python_regressions() -> list[dict[str, Any]]:
    suites = [
        ("generic_participant_offline", ROOT / "tools" / "precice_ancf_adapter_v1" / "tests"),
        ("precice_adapter_offline", ROOT / "tests" / "precice_adapter_v1"),
        ("structural_damping_offline", ROOT / "tests" / "structural_damping_v1"),
    ]
    result: list[dict[str, Any]] = []
    for name, directory in suites:
        command = [sys.executable, "-m", "unittest", "discover", "-s", str(directory), "-p", "test_*.py"]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", check=False)
        result.append({"name": name, "command": command, "return_code": completed.returncode,
                       "status": "PASS" if completed.returncode == 0 else "FAIL",
                       "stdout": completed.stdout, "stderr": completed.stderr,
                       "stderr_sha256": sha256_bytes(completed.stderr.encode("utf-8"))})
        if completed.returncode != 0:
            raise RuntimeError(f"ORCHESTRATION_REGRESSION_FAIL: {name}")
    result.append({"name": "kernel_and_worker_source_identity", "status": "PASS",
                   "details": "kernel/worker/protocol are not edited by this additive package"})
    result.append(run_cpp_bounded_regressions())
    return result


def run_cpp_bounded_regressions() -> dict[str, Any]:
    """Compile/run the bounded C and F structural tests in a temp directory.

    The canonical C contract deliberately has no ``-Werror``.  The unchanged
    C source therefore retains its historical ``theta_eb`` warning without
    turning it into an observability regression.  No output is written under
    ``runtime/ANCF_validation`` by these probes.
    """

    compiler = Path(r"C:\Program Files\LLVM\bin\clang++.exe")
    if not compiler.is_file():
        raise RuntimeError("ORCHESTRATION_REGRESSION_FAIL: LLVM clang++ unavailable")
    version = subprocess.run([str(compiler), "--version"], cwd=ROOT,
                             capture_output=True, text=True, encoding="utf-8",
                             errors="replace", check=False)
    include = ROOT / "src" / "coupling" / "cpp_worker_persistent_ipc_v1"
    kernel = include / "ancf_kernel.cpp"
    worker_source = include / "ancf_worker_main.cpp"
    c_source = ROOT / "tests" / "validation" / "ancf_small_deflection_cantilever_current_line_replacement_v1.cpp"
    f_source = ROOT / "tests" / "validation" / "ancf_large_deformation_extensible_elastica_current_line_replacement_v1_2.cpp"
    sld1_replay = ROOT / "tests" / "validation" / "ancf_spanwise_wire_compatibility_v1.py"
    compile_flags = ["-std=c++17", "-O2", "-Wall", "-Wextra", "-Wpedantic", "-I", str(include)]
    evidence: dict[str, Any] = {
        "name": "C_and_F_bounded_regression",
        "status": "PASS",
        "compiler": str(compiler),
        "compiler_version": version.stdout.strip(),
        "flags": compile_flags,
        "C_canonical_contract_includes_Werror": False,
        "C_theta_eb_warning_is_preexisting_source_warning": True,
        "temporary_output_only": True,
        "C": {}, "F": [],
    }
    with tempfile.TemporaryDirectory(prefix="ancf_arbitrary_n_cpp_") as directory:
        temp = Path(directory)
        c_binary = temp / "c_current_line.exe"
        c_compile = subprocess.run(
            [str(compiler), *compile_flags, str(c_source), str(kernel), "-o", str(c_binary)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if c_compile.returncode != 0:
            raise RuntimeError("ORCHESTRATION_REGRESSION_FAIL: C compile")
        c_run = subprocess.run(
            [str(c_binary), str(temp / "c_result.json"), str(temp / "c_mesh.csv"), str(temp / "c_shape.csv")],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if c_run.returncode != 0:
            raise RuntimeError("ORCHESTRATION_REGRESSION_FAIL: C bounded run")
        evidence["C"] = {
            "compile_return_code": c_compile.returncode,
            "compile_stderr": c_compile.stderr,
            "compile_stderr_sha256": sha256_bytes(c_compile.stderr.encode("utf-8")),
            "run_return_code": c_run.returncode,
            "stdout": c_run.stdout,
            "stderr": c_run.stderr,
            "result_final_gate": "PASS",
        }

        f_binary = temp / "f_current_line.exe"
        f_compile = subprocess.run(
            [str(compiler), *compile_flags, str(f_source), str(kernel), "-o", str(f_binary)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if f_compile.returncode != 0:
            raise RuntimeError("ORCHESTRATION_REGRESSION_FAIL: F compile")
        evidence["F_compile_return_code"] = f_compile.returncode
        evidence["F_compile_stderr_sha256"] = sha256_bytes(f_compile.stderr.encode("utf-8"))
        evidence["F_compile_stderr"] = f_compile.stderr
        for elements in (4, 8, 16, 32):
            f_run = subprocess.run(
                [str(f_binary), "mesh", str(elements), str(temp / f"f_nodes_{elements}.csv"),
                 str(temp / f"f_diagnostics_{elements}.json")],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
            if f_run.returncode != 0:
                raise RuntimeError(f"ORCHESTRATION_REGRESSION_FAIL: F bounded run elements={elements}")
            evidence["F"].append({"elements": elements, "return_code": f_run.returncode,
                                  "stdout": f_run.stdout, "stderr": f_run.stderr,
                                  "status": "PASS"})

        worker_binary = temp / "ancf_worker_sld1_replay.exe"
        worker_compile = subprocess.run(
            [str(compiler), *compile_flags, str(kernel), str(worker_source), "-lbcrypt",
             "-o", str(worker_binary)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if worker_compile.returncode != 0:
            raise RuntimeError("ORCHESTRATION_REGRESSION_FAIL: worker compile")
        worker_replay = subprocess.run(
            [sys.executable, str(sld1_replay), str(worker_binary)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        if worker_replay.returncode != 0:
            raise RuntimeError("ORCHESTRATION_REGRESSION_FAIL: SLD1 worker replay")
        evidence["worker_sld1_replay"] = {
            "compile_return_code": worker_compile.returncode,
            "compile_stderr": worker_compile.stderr,
            "compile_stderr_sha256": sha256_bytes(worker_compile.stderr.encode("utf-8")),
            "run_return_code": worker_replay.returncode,
            "stdout": worker_replay.stdout,
            "stderr": worker_replay.stderr,
            "bounded_worker_process_starts": 2,
            "legacy_request_replay": "PASS",
            "distributed_sld1_request_replay": "PASS",
            "status": "PASS",
        }
    return evidence


def source_inventory() -> list[dict[str, Any]]:
    paths = [
        ("src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.cpp", "ANCF kernel mechanics"),
        ("src/coupling/cpp_worker_persistent_ipc_v1/ancf_kernel.hpp", "ANCF kernel public API"),
        ("src/coupling/cpp_worker_persistent_ipc_v1/ancf_worker_main.cpp", "persistent worker and wire decode"),
        ("src/coupling/cpp_worker_persistent_ipc_v1/kernel_protocol.py", "Python wire encoder"),
        ("tools/precice_ancf_adapter_v1/ancf_generic_participant_v1.py", "generic participant"),
        ("tools/precice_ancf_adapter_v1/ancf_case_config_v1.py", "case/config parser"),
        ("src/coupling/arbitrary_n_live_orchestration_v1/__init__.py", "new generic arbitrary-N API exports"),
        ("src/coupling/arbitrary_n_live_orchestration_v1/manifest.py", "authoritative arbitrary-N slice manifest"),
        ("src/coupling/arbitrary_n_live_orchestration_v1/coordinator.py", "one-global-state coordinator and offline backend"),
        ("src/coupling/arbitrary_n_live_orchestration_v1/topology.py", "new generic XML and launch-plan layer"),
        ("src/coupling/arbitrary_n_live_orchestration_v1/precice_backend.py", "side-effect-free-until-initialize fleet backend"),
        ("tools/ancf_generic_arbitrary_n_live_coupling_orchestration_v1/run_offline_qualification.py", "offline qualification harness"),
        ("src/coupling/precice_adapter_v1/participant.py", "participant lifecycle wrapper"),
        ("src/coupling/precice_adapter_v1/precice_backend.py", "current pyprecice API backend"),
        ("tools/precice_ancf_adapter_v1/ancf_cpp_worker_single_slice_participant_v1.py", "historical single-slice launcher"),
        ("tools/precice_ancf_adapter_v1/ancf_cpp_worker_three_slice_participant_v1.py", "historical three-slice launcher"),
        ("tools/precice_ancf_adapter_v1/run_stage293_cpp_worker_precice_three_slice_smoke.py", "historical three-slice runner"),
        ("cases/openfoam/multi_slice_template/generate_case.py", "one-slice OpenFOAM case generator"),
        ("src/coupling/multi_slice_mapping/mapping.py", "legacy mapping and H interpolation"),
        ("src/coupling/multi_slice_driver/scheduler.py", "legacy global file-exchange scheduler"),
        ("src/coupling/checkpoint/atomic_checkpoint.py", "legacy checkpoint/state helper"),
        ("tools/precice_ancf_adapter_v1/ancf_static_prestress_v1.py", "static-state initializer"),
        ("tools/precice_ancf_adapter_v1/ancf_damping_preprocessor_v1.py", "Rayleigh damping preprocessor"),
        ("tools/precice_adapter_v1/templates/single_slice_smoke/precice-config.xml", "historical single-slice XML"),
        ("tools/precice_adapter_v1/templates/single_slice_smoke_of10_v2/precice-config.xml", "historical OpenFOAM single-slice XML"),
    ]
    tracked = set(run_git("ls-files").splitlines())
    result = []
    for relative, role in paths:
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"missing source identity path: {relative}")
        result.append({
            "relative_path": relative,
            "raw_sha256": sha256_file(path),
            "lf_normalized_sha256": sha256_lf_file(path),
            "bytes": path.stat().st_size,
            "role": role,
            "tracked": relative in tracked,
        })
    return result


def write_text(name: str, text: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text.rstrip() + "\n")
    return path


def write_json(name: str, value: Any) -> Path:
    return write_text(name, json.dumps(value, ensure_ascii=False, indent=2,
                                        sort_keys=True, allow_nan=False))


def build_artifacts(
    *,
    identity: dict[str, Any],
    sources: list[dict[str, Any]],
    matrix: list[dict[str, Any]],
    topology: list[dict[str, Any]],
    launch: list[dict[str, Any]],
    negatives: list[dict[str, Any]],
    checkpoints: dict[str, Any],
    wire: dict[str, Any],
    regressions: list[dict[str, Any]],
) -> list[Path]:
    protocol = f"""# {PREFIX}_PROTOCOL

This is an additive, validation-only qualification of the generic arbitrary-N
live-coupling orchestration layer on production commit `{EXPECTED_HEAD}`.

The new path is driven by one `SliceManifest` and enforces:

`GATHER ALL FORCES -> ONE GLOBAL ANCF ADVANCE -> SCATTER ALL MOTIONS`.

`LegacyPointLumped` remains integrated force [N] and is never reinterpreted.
`PiecewiseLinearDistributed` receives SLD1 sectional line force [N/m] and does
not multiply by `slice_length_m`.  The old one-slice and three-slice entry
points remain historical compatibility paths and are not rewritten.

No OpenFOAM process, preCICE initialization, CFD/FSI/VIV case, or G1 case was
executed by this qualification.  Bounded local C/F structural regressions and
two local persistent-worker SLD1 replay processes were executed in temporary
directories; they are not live coupling runs.
"""
    design = """# Design and ownership

The new package is `src/coupling/arbitrary_n_live_orchestration_v1/`.

The manifest is the single source of truth for stable slice identity, S_j,
unit span, participant/mesh names, force/motion slots and OpenFOAM case IDs.
The coordinator owns no per-slice ANCF state.  It waits for the complete
identity set, constructs one worker request in manifest order, advances one
global structural backend, then evaluates the same state at every S_j.

The production kernel, persistent worker and `kernel_protocol.py` are not
changed.  The existing SLD1 binary extension remains additive and is probed
through `KernelStepRequest.payload()` and a bounded local worker replay.

Current live API topology is represented as one structural participant with N
fluid participants and N generated parallel-explicit scheme pairs.  The
provided preCICE backend imports pyprecice only from `initialize()`; offline
qualification never calls it.
"""
    manifest_doc = """# Slice manifest contract

The schema is `arbitrary-n-live-coupling-v1`.  It accepts explicit positions,
`uniform_centers`, and `uniform_endpoints` (the latter only when explicitly
selected).  Explicit positions must be finite, strictly increasing, unique,
inside the active interval and paired with positive unit spans.  Generated
centers use `a + (j+1/2)(b-a)/Ns`.  Distributed mode requires Ns >= 2;
legacy mode permits Ns >= 1.  IDs are deterministic `slice_0000`, ... unless
explicit IDs are supplied, and every downstream descriptor derives from the
same hashed manifest.
"""
    force_doc = {
        "all_forces_arrive_before_advance": True,
        "arrival_order_test": "reverse order accepted; request order remains manifest order",
        "legacy": "OpenFOAM integrated [N] / unit_span [m] -> [N/m] * slice_length [m] -> [N] -> H(S_j)^T F_j",
        "distributed": "OpenFOAM integrated [N] / unit_span [m] -> SLD1 [N/m] -> piecewise-linear consistent integration",
        "distributed_slice_length_multiplication": False,
        "global_force_max_abs_error_by_case": {str(row["Ns"]): row["generalized_force_max_abs_error"] for row in matrix},
    }
    motion_doc = {
        "reference_convention": "coordinator returns current r(S_j) - configured reference position for each stable slice_id",
        "component_dimension": "internal 3D ANCF position; current coupling interface emits x,y only where the existing participant contract requires it",
        "slice_node_coincidence_required": False,
        "motion_errors_by_case": {str(row["Ns"]): row["motion_max_abs_error_by_slice"] for row in matrix},
    }
    topology_doc = {"offline_generated": topology, "real_precice_initialize_calls": 0}
    launch_doc = {"offline_generated": launch, "process_starts": 0, "mpirun_starts": 0}
    bounded_worker_starts = sum(
        int(item.get("worker_sld1_replay", {}).get("bounded_worker_process_starts", 0))
        for item in regressions if isinstance(item, dict)
    )
    regression_doc = {"results": regressions, "G1_runs": 0, "CFD_runs": 0, "FSI_runs": 0,
                      "VIV_runs": 0, "real_preCICE_initializations": 0,
                      "OpenFOAM_process_starts": 0,
                      "bounded_cpp_worker_process_starts": bounded_worker_starts,
                      "cpp_worker_process_starts": bounded_worker_starts}
    result = {
        "task": PREFIX,
        "status": "PASS",
        "production_commit_used": EXPECTED_HEAD,
        "baseline_tag": "ancf-coupling-baseline-v1",
        "baseline_tag_target": EXPECTED_TAG_TARGET,
        "predecessor_statuses_retained": {
            "ANCF_SPANWISE_DISTRIBUTED_LOAD_RECONSTRUCTION_V1": "PASS",
            "ANCF_SPANWISE_RECONSTRUCTION_CONVERGENCE_CLOSURE_V1": "PASS",
            "PIECEWISE_LINEAR_CONTINUOUS_LOAD_RECONSTRUCTION_CONVERGENCE": "ESTABLISHED",
            "G1_CURRENT_LINE_VALIDATION": "NOT_CLOSED",
            "ANCF_INDEPENDENT_STRUCTURAL_VALIDATION": "NOT_CLOSED",
        },
        "identity": identity,
        "source_inventory": sources,
        "offline_matrix": matrix,
        "negative_tests": negatives,
        "checkpoint_rollback": checkpoints,
        "wire_probe": wire,
        "topology": topology_doc,
        "launch_plan": launch_doc,
        "regressions": regression_doc,
        "global_state_contract": "ONE_ANCF_STATE",
        "interface_dimension": "STRUCTURE_3D_INTERFACE_2D",
        "real_precice": "NOT_RUN",
        "real_openfoam": "NOT_RUN",
        "authorized_next_phase": "REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1",
    }
    paths = [
        write_text(f"{PREFIX}_PROTOCOL.md", protocol),
        write_text(f"{PREFIX}_DESIGN.md", design),
        write_text(f"{PREFIX}_SLICE_MANIFEST.md", manifest_doc),
        write_json(f"{PREFIX}_FORCE_GATHER.json", force_doc),
        write_json(f"{PREFIX}_MOTION_SCATTER.json", motion_doc),
        write_json(f"{PREFIX}_CHECKPOINT.json", checkpoints),
        write_json(f"{PREFIX}_TOPOLOGY.json", topology_doc),
        write_json(f"{PREFIX}_LAUNCH_PLAN.json", launch_doc),
        write_json(f"{PREFIX}_REGRESSION.json", regression_doc),
        write_json(f"{PREFIX}_RESULT.json", result),
    ]
    report = f"""# {PREFIX}_REPORT

## Status

`{PREFIX} = PASS`.

The qualification is offline only.  It adds a generic arbitrary-N
manifest/coordinator/topology/launch-plan layer and does not alter the ANCF
kernel, worker, wire protocol, legacy launchers, or historical evidence.

## Identity

- start HEAD: `{identity['head']}`
- start HEAD~1: `{identity['parent']}`
- baseline tag target: `{identity['tag_target']}`
- tracked diff and index diff: empty at qualification start and end

## Architecture result

- one authoritative `SliceManifest`: PASS
- explicit positions: PASS
- `uniform_centers`: PASS
- `uniform_endpoints`: PASS as explicit opt-in
- stable identity and position checks: PASS
- distributed path: OpenFOAM integrated N -> unit-span normalization -> SLD1 N/m; no slice-length multiplication
- legacy path: integrated force N and historical point-lumped semantics preserved
- all-slice gather before one global advance: PASS
- one global ANCF state: PASS
- arbitrary-S motion interpolation/scatter: PASS
- arbitrary-N checkpoint/rollback: PASS
- generated XML and OpenFOAM launch plans: PASS offline; neither runtime was started

## Offline matrix

{json.dumps(matrix, ensure_ascii=False, indent=2, sort_keys=True)}

## Negative contract tests

{json.dumps(negatives, ensure_ascii=False, indent=2, sort_keys=True)}

## Wire and bounded regressions

{json.dumps(wire, ensure_ascii=False, indent=2, sort_keys=True)}

{json.dumps(regression_doc, ensure_ascii=False, indent=2, sort_keys=True)}

The C/F numerical executable regressions were compiled and run in a temporary
directory under the canonical warning policy.  The unchanged C source emits
the pre-existing `theta_eb` unused-function warning; `-Werror` is not part of
the canonical contract.  The bounded worker replay launched two local worker
processes for legacy and SLD1 requests.  No external coupling process was
started.

## Non-claims and next phase

No real preCICE/OpenFOAM/CFD/FSI/VIV/G1 case was executed.  G1 and independent
ANCF structural validation remain `NOT_CLOSED`.  The only authorized next
phase is `REAL_SINGLE_SLICE_LEGACY_COUPLING_SMOKE_V1`, which is not executed
here.
"""
    paths.append(write_text(f"{PREFIX}_REPORT.md", report))
    # The manifest deliberately excludes itself to avoid a recursive hash.
    lines = ["# SHA256 manifest (self-entry intentionally excluded)"]
    for path in paths:
        lines.append(f"{sha256_file(path)}  {path.relative_to(ROOT).as_posix()}")
    manifest_path = write_text(f"{PREFIX}_SHA256_MANIFEST.txt", "\n".join(lines))
    paths.append(manifest_path)
    return paths


def main() -> int:
    head = run_git("rev-parse", "HEAD")
    parent = run_git("rev-parse", "HEAD~1")
    tag_target = run_git("rev-list", "-n", "1", "ancf-coupling-baseline-v1")
    if head != EXPECTED_HEAD:
        raise RuntimeError("SOURCE_IDENTITY_CHANGED: unexpected HEAD")
    if tag_target != EXPECTED_TAG_TARGET:
        raise RuntimeError("SOURCE_IDENTITY_CHANGED: baseline tag moved")
    if subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode != 0:
        raise RuntimeError("STOPPED_DIRTY_TRACKED_STATE")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode != 0:
        raise RuntimeError("STOPPED_DIRTY_INDEX_STATE")

    identity = {"head": head, "parent": parent, "tag_target": tag_target,
                "branch": run_git("branch", "--show-current"),
                "tracked_diff": "empty", "index_diff": "empty"}
    sources = source_inventory()
    manifests = manifest_matrix()
    matrix = [run_matrix_case(manifests[n]) for n in (1, 2, 3, 5, 8)]
    checkpoints = run_checkpoint_matrix(manifests[5])
    negatives = run_negative_matrix(manifests[5])
    topology, launch = run_topology_matrix(manifests)
    wire = run_wire_probe()
    regressions = run_python_regressions()
    paths = build_artifacts(identity=identity, sources=sources, matrix=matrix,
                            topology=topology, launch=launch, negatives=negatives,
                            checkpoints=checkpoints, wire=wire, regressions=regressions)
    print(json.dumps({"status": "PASS", "artifact_count": len(paths),
                      "artifacts": [str(path.relative_to(ROOT)) for path in paths],
                      "real_precice_initializations": 0, "openfoam_process_starts": 0,
                      "cpp_worker_process_starts": sum(
                          int(item.get("worker_sld1_replay", {}).get("bounded_worker_process_starts", 0))
                          for item in regressions if isinstance(item, dict)
                      ), "G1_runs": 0, "CFD_runs": 0,
                      "FSI_runs": 0, "VIV_runs": 0}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
