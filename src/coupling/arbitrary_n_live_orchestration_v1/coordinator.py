"""Generic gather/advance/scatter coordinator and deterministic offline backends."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping, Protocol, Sequence

from ..multi_slice_mapping.mapping import ancf_hermite_H

from .manifest import ManifestError, OrchestrationSlice, SliceManifest


class OrchestrationError(RuntimeError):
    """A live-coupling identity, unit, lifecycle or gather violation."""


class CheckpointError(OrchestrationError):
    """Checkpoint identity or rollback violation."""


def _finite(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise OrchestrationError(f"{name} must be numeric") from exc
    if not math.isfinite(result):
        raise OrchestrationError(f"{name} is NaN/Inf")
    return result


def _vector3(value: Sequence[Any], name: str) -> tuple[float, float, float]:
    if isinstance(value, (str, bytes)) or len(value) != 3:
        raise OrchestrationError(f"{name} must have three components")
    return tuple(_finite(item, f"{name}[{index}]") for index, item in enumerate(value))  # type: ignore[return-value]


def _dot(matrix: Sequence[Sequence[float]], vector: Sequence[float]) -> tuple[float, ...]:
    return tuple(sum(float(a) * float(b) for a, b in zip(row, vector)) for row in matrix)


@dataclass(frozen=True)
class ForceSample:
    """One force sample normalized from OpenFOAM's integrated [N] output."""

    slice_id: str
    s_ref_m: float
    iteration: int
    time_s: float
    unit_span_m: float
    representation: str
    values: tuple[float, float, float]
    openfoam_force_N: tuple[float, float, float]

    @classmethod
    def from_openfoam_integrated(
        cls,
        manifest: SliceManifest,
        slice_id: str,
        *,
        iteration: int,
        time_s: float,
        force_N: Sequence[Any],
        unit_span_m: float,
    ) -> "ForceSample":
        item = manifest.by_id(slice_id)
        span = _finite(unit_span_m, "unit_span_m")
        if span <= 0.0 or abs(span - item.unit_span_m) > 1.0e-12 * max(1.0, abs(span), abs(item.unit_span_m)):
            raise OrchestrationError(f"slice {slice_id}: unit_span_m mismatch")
        raw = _vector3(force_N, "openfoam_force_N")
        line = tuple(value / span for value in raw)
        if manifest.reconstruction_mode == "PiecewiseLinearDistributed":
            values = line
            representation = "sectional_line_force_Npm"
        else:
            values = tuple(value * item.slice_length_m for value in line)
            representation = "integrated_slice_force_N"
        return cls(slice_id, item.s_ref_m, int(iteration), _finite(time_s, "time_s"), span,
                   representation, values, raw)

    @classmethod
    def from_line_force(
        cls, manifest: SliceManifest, slice_id: str, *, iteration: int,
        time_s: float, line_force_Npm: Sequence[Any], unit_span_m: float,
    ) -> "ForceSample":
        item = manifest.by_id(slice_id)
        span = _finite(unit_span_m, "unit_span_m")
        if manifest.reconstruction_mode != "PiecewiseLinearDistributed":
            raise OrchestrationError("line-force samples are not valid in legacy mode")
        if abs(span - item.unit_span_m) > 1.0e-12 * max(1.0, abs(span), abs(item.unit_span_m)):
            raise OrchestrationError(f"slice {slice_id}: unit_span_m mismatch")
        values = _vector3(line_force_Npm, "line_force_Npm")
        return cls(slice_id, item.s_ref_m, int(iteration), _finite(time_s, "time_s"), span,
                   "sectional_line_force_Npm", values,
                   tuple(value * span for value in values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "slice_id": self.slice_id, "s_ref_m": self.s_ref_m, "iteration": self.iteration,
            "time_s": self.time_s, "unit_span_m": self.unit_span_m,
            "representation": self.representation, "values": list(self.values),
            "openfoam_force_N": list(self.openfoam_force_N),
        }


@dataclass(frozen=True)
class WorkerRequest:
    """One global worker request assembled from every slice in manifest order."""

    case_id: str
    iteration: int
    time_s: float
    slice_ids: tuple[str, ...]
    slice_positions_m: tuple[float, ...]
    reconstruction_mode: str
    active_start_m: float
    active_end_m: float
    spanwise_line_force_Npm: tuple[float, ...]
    slice_force_N: tuple[float, ...]
    sld1: bool

    def to_payload(self) -> dict[str, Any]:
        result = {
            "case_id": self.case_id, "iteration": self.iteration, "time_s": self.time_s,
            "slice_ids": list(self.slice_ids), "slice_positions_m": list(self.slice_positions_m),
            "reconstruction_mode": self.reconstruction_mode,
            "active_start_m": self.active_start_m, "active_end_m": self.active_end_m,
        }
        if self.sld1:
            result.update({
                "wire_extension": "SLD1",
                "force_representation": "sectional_line_force_Npm",
                "spanwise_line_force_Npm": list(self.spanwise_line_force_Npm),
            })
        else:
            result.update({
                "force_representation": "integrated_slice_force_N",
                "slice_force": list(self.slice_force_N),
            })
        return result


def _gauss3() -> tuple[tuple[float, float], ...]:
    root = math.sqrt(3.0 / 5.0)
    return ((-root, 5.0 / 9.0), (0.0, 8.0 / 9.0), (root, 5.0 / 9.0))


def _line_force_at(s: float, positions: Sequence[float], forces: Sequence[Sequence[float]], start: float, end: float) -> tuple[float, float, float]:
    if s < start or s > end:
        return (0.0, 0.0, 0.0)
    if s <= positions[0]:
        return tuple(float(value) for value in forces[0])  # type: ignore[return-value]
    if s >= positions[-1]:
        return tuple(float(value) for value in forces[-1])  # type: ignore[return-value]
    for index, (left, right) in enumerate(zip(positions, positions[1:])):
        if left <= s <= right:
            weight = (s - left) / (right - left)
            return tuple((1.0 - weight) * forces[index][component] + weight * forces[index + 1][component] for component in range(3))  # type: ignore[return-value]
    raise OrchestrationError("sample interpolation interval not found")


def assemble_generalized_force(
    manifest: SliceManifest,
    mesh_nodes: Sequence[float],
    request: WorkerRequest,
) -> tuple[float, ...]:
    """Independent Gauss-3 reference of the request's global generalized load."""

    if tuple(request.slice_ids) != manifest.slice_ids:
        raise OrchestrationError("worker request slice order differs from manifest")
    ndof = 6 * len(mesh_nodes)
    result = [0.0] * ndof
    if request.sld1:
        if len(request.spanwise_line_force_Npm) != 3 * manifest.ns:
            raise OrchestrationError("SLD1 force length does not match Ns")
        positions = request.slice_positions_m
        forces = [request.spanwise_line_force_Npm[3 * i:3 * i + 3] for i in range(manifest.ns)]
        boundaries = [float(mesh_nodes[0]), *[float(value) for value in mesh_nodes[1:-1]], float(mesh_nodes[-1]), request.active_start_m, request.active_end_m, *positions]
        split = sorted(set(value for value in boundaries if mesh_nodes[0] <= value <= mesh_nodes[-1]))
        for left, right in zip(split, split[1:]):
            if right <= left:
                continue
            midpoint = 0.5 * (left + right)
            element_index = max(0, min(len(mesh_nodes) - 2, next((i for i in range(len(mesh_nodes) - 1) if mesh_nodes[i] <= midpoint <= mesh_nodes[i + 1]), len(mesh_nodes) - 2)))
            for xi, weight in _gauss3():
                s = 0.5 * (left + right) + 0.5 * (right - left) * xi
                H = ancf_hermite_H(s, mesh_nodes, ndof=ndof)
                force = _line_force_at(s, positions, forces, request.active_start_m, request.active_end_m)
                factor = 0.5 * (right - left) * weight
                for row in range(3):
                    for column in range(ndof):
                        result[column] += H[row][column] * force[row] * factor
            _ = element_index
    else:
        if len(request.slice_force_N) != 3 * manifest.ns:
            raise OrchestrationError("legacy force length does not match Ns")
        for index, item in enumerate(manifest.slices):
            H = ancf_hermite_H(item.s_ref_m, mesh_nodes, ndof=ndof)
            force = request.slice_force_N[3 * index:3 * index + 3]
            for row in range(3):
                for column in range(ndof):
                    result[column] += H[row][column] * force[row]
    return tuple(result)


class StructuralBackend(Protocol):
    def snapshot(self) -> Mapping[str, Any]: ...
    def restore(self, snapshot: Mapping[str, Any]) -> None: ...
    def advance(self, request: WorkerRequest) -> Mapping[str, Any]: ...
    def commit(self) -> None: ...
    def evaluate_position(self, s_ref_m: float) -> tuple[float, float, float]: ...


@dataclass
class InMemoryANCFBackend:
    """Deterministic non-CFD backend used only for orchestration qualification."""

    mesh_nodes: tuple[float, ...]
    q: list[float] | None = None
    qdot: list[float] | None = None
    qddot: list[float] | None = None
    elements: int | None = None
    attempted_advance_count: int = 0
    committed_advance_count: int = 0

    def __post_init__(self) -> None:
        if len(self.mesh_nodes) < 2 or any(right <= left for left, right in zip(self.mesh_nodes, self.mesh_nodes[1:])):
            raise OrchestrationError("mesh_nodes must be strictly increasing")
        ndof = 6 * len(self.mesh_nodes)
        if self.q is None:
            self.q = [0.0] * ndof
            for index, node in enumerate(self.mesh_nodes):
                self.q[6 * index + 2] = float(node)
                self.q[6 * index + 5] = 1.0
        if self.qdot is None:
            self.qdot = [0.0] * ndof
        if self.qddot is None:
            self.qddot = [0.0] * ndof
        if any(len(vector) != ndof for vector in (self.q, self.qdot, self.qddot)):
            raise OrchestrationError("in-memory ANCF state dimensions are inconsistent")
        self.elements = len(self.mesh_nodes) - 1
        self._pending = False

    @property
    def ndof(self) -> int:
        return len(self.q or ())

    def snapshot(self) -> Mapping[str, Any]:
        return {
            "q": list(self.q or ()), "qdot": list(self.qdot or ()),
            "qddot": list(self.qddot or ()),
            "attempted_advance_count": self.attempted_advance_count,
            "committed_advance_count": self.committed_advance_count,
            "pending": bool(self._pending),
        }

    def restore(self, snapshot: Mapping[str, Any]) -> None:
        for key in ("q", "qdot", "qddot"):
            values = [float(value) for value in snapshot[key]]
            if len(values) != self.ndof or any(not math.isfinite(value) for value in values):
                raise OrchestrationError(f"invalid backend snapshot {key}")
            setattr(self, key, values)
        self.attempted_advance_count = int(snapshot["attempted_advance_count"])
        self.committed_advance_count = int(snapshot["committed_advance_count"])
        self._pending = bool(snapshot.get("pending", False))

    def advance(self, request: WorkerRequest) -> Mapping[str, Any]:
        if self._pending:
            raise OrchestrationError("backend has an uncommitted tentative advance")
        generalized = assemble_generalized_force(
            _manifest_for_request(request), self.mesh_nodes, request)
        self.attempted_advance_count += 1
        self.q = [value + 1.0e-6 * generalized[index] for index, value in enumerate(self.q or ())]
        self.qdot = [1.0e-3 * value for value in generalized]
        self.qddot = [0.0] * self.ndof
        self._pending = True
        return {"generalized_force": list(generalized), "attempted_advance_count": self.attempted_advance_count}

    def commit(self) -> None:
        if not self._pending:
            raise OrchestrationError("no tentative backend state to commit")
        self.committed_advance_count += 1
        self._pending = False

    def evaluate_motion(self, s_ref_m: float) -> tuple[float, float, float]:
        """Compatibility alias returning the current position, not a load."""
        return self.evaluate_position(s_ref_m)

    def evaluate_position(self, s_ref_m: float) -> tuple[float, float, float]:
        H = ancf_hermite_H(s_ref_m, self.mesh_nodes, ndof=self.ndof)
        return _dot(H, self.q or ())  # type: ignore[return-value]


def _manifest_for_request(request: WorkerRequest) -> SliceManifest:
    slices = tuple(
        # Only the fields used by the independent integration helper are
        # reconstructed here.  The coordinator has already validated the
        # authoritative manifest before a backend sees the request.
        OrchestrationSlice(
            slice_id=sid, ordinal=index, s_ref_m=request.slice_positions_m[index],
            slice_length_m=1.0, unit_span_m=1.0,
            fluid_participant="Fluid_" + sid, structure_participant="StructureCoordinator",
            structure_mesh="Structure-Mesh-" + sid, fluid_mesh="Fluid-Mesh-" + sid,
            force_data="Force", motion_data="Displacement", openfoam_case_id=sid,
            force_slot=index, motion_slot=index,
        ) for index, sid in enumerate(request.slice_ids)
    )
    return SliceManifest(
        "arbitrary-n-live-coupling-v1", request.case_id,
        max(request.active_end_m, request.slice_positions_m[-1] + 1.0),
        request.active_start_m, request.active_end_m, request.reconstruction_mode,
        "NearestConstant", "StructureCoordinator", slices,
    )


@dataclass(frozen=True)
class CouplingCheckpoint:
    checkpoint_id: str
    manifest_sha256: str
    iteration: int | None
    time_s: float | None
    backend_state: Mapping[str, Any]
    gathered_slice_ids: tuple[str, ...]
    committed_step: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id, "manifest_sha256": self.manifest_sha256,
            "iteration": self.iteration, "time_s": self.time_s,
            "backend_state": deepcopy(dict(self.backend_state)),
            "gathered_slice_ids": list(self.gathered_slice_ids),
            "committed_step": self.committed_step,
        }


class GenericStructuralCoordinator:
    """One global ANCF state with fail-closed all-slice gather semantics."""

    def __init__(
        self,
        manifest: SliceManifest,
        backend: StructuralBackend,
        *,
        reference_positions_by_slice: Mapping[str, Sequence[Any]] | None = None,
    ) -> None:
        self.manifest = manifest
        self.backend = backend
        references = reference_positions_by_slice or {
            item.slice_id: (0.0, 0.0, item.s_ref_m) for item in manifest.slices
        }
        if set(references) != set(manifest.slice_ids):
            raise OrchestrationError("reference positions must cover exactly the manifest slice IDs")
        self._reference_positions = {
            sid: _vector3(value, f"reference_positions_by_slice[{sid}]")
            for sid, value in references.items()
        }
        self._gather: dict[str, ForceSample] = {}
        self._iteration: int | None = None
        self._time_s: float | None = None
        self._pending_advance = False
        self._last_request: WorkerRequest | None = None
        self._last_motion: dict[str, tuple[float, float, float]] = {}
        self._checkpoint: CouplingCheckpoint | None = None
        self.committed_step = 0
        self.attempted_structural_advances = 0
        self.committed_structural_advances = 0

    @property
    def expected_slice_ids(self) -> frozenset[str]:
        return frozenset(self.manifest.slice_ids)

    @property
    def gathered_slice_ids(self) -> frozenset[str]:
        return frozenset(self._gather)

    @property
    def last_request(self) -> WorkerRequest | None:
        return self._last_request

    @property
    def last_motion(self) -> Mapping[str, tuple[float, float, float]]:
        return dict(self._last_motion)

    def submit_force(self, sample: ForceSample) -> None:
        if sample.slice_id not in self.expected_slice_ids:
            raise OrchestrationError(f"unknown slice_id: {sample.slice_id}")
        if sample.slice_id in self._gather:
            raise OrchestrationError(f"duplicate force for {sample.slice_id}")
        if sample.iteration < 0 or not math.isfinite(sample.time_s):
            raise OrchestrationError("invalid force iteration/time")
        expected_position = self.manifest.by_id(sample.slice_id).s_ref_m
        if abs(sample.s_ref_m - expected_position) > 1.0e-12 * max(1.0, abs(expected_position)):
            raise OrchestrationError("slice identity/position mismatch")
        if self._iteration is None:
            self._iteration, self._time_s = sample.iteration, sample.time_s
        elif sample.iteration != self._iteration or abs(sample.time_s - float(self._time_s)) > 1.0e-12:
            raise OrchestrationError("stale or mixed-iteration force sample")
        expected_repr = "sectional_line_force_Npm" if self.manifest.reconstruction_mode == "PiecewiseLinearDistributed" else "integrated_slice_force_N"
        if sample.representation != expected_repr:
            raise OrchestrationError("force units/manifest mode mismatch")
        self._gather[sample.slice_id] = sample

    def _build_request(self) -> WorkerRequest:
        if self._iteration is None or self._time_s is None:
            raise OrchestrationError("force gather has no iteration")
        if set(self._gather) != set(self.expected_slice_ids):
            missing = sorted(self.expected_slice_ids.difference(self._gather))
            extra = sorted(set(self._gather).difference(self.expected_slice_ids))
            raise OrchestrationError(f"force gather incomplete; missing={missing}, extra={extra}")
        ordered = [self._gather[item.slice_id] for item in self.manifest.slices]
        distributed = self.manifest.reconstruction_mode == "PiecewiseLinearDistributed"
        values = tuple(component for sample in ordered for component in sample.values)
        return WorkerRequest(
            case_id=self.manifest.case_id, iteration=self._iteration, time_s=self._time_s,
            slice_ids=self.manifest.slice_ids,
            slice_positions_m=tuple(item.s_ref_m for item in self.manifest.slices),
            reconstruction_mode=self.manifest.reconstruction_mode,
            active_start_m=self.manifest.active_start_m, active_end_m=self.manifest.active_end_m,
            spanwise_line_force_Npm=values if distributed else (),
            slice_force_N=() if distributed else values,
            sld1=distributed,
        )

    def advance_if_complete(self) -> Mapping[str, Any]:
        if self._pending_advance:
            raise OrchestrationError("a tentative global advance is already pending")
        request = self._build_request()
        result = self.backend.advance(request)
        self._last_request = request
        self._pending_advance = True
        self.attempted_structural_advances += 1
        return dict(result)

    def scatter_motion(self) -> dict[str, tuple[float, float, float]]:
        if not self._pending_advance:
            raise OrchestrationError("motion scatter requires a tentative global advance")
        position_evaluator = getattr(self.backend, "evaluate_position", None)
        if not callable(position_evaluator):
            raise OrchestrationError("structural backend must expose evaluate_position")
        result = {}
        for item in self.manifest.slices:
            position = _vector3(position_evaluator(item.s_ref_m), f"position[{item.slice_id}]")
            reference = self._reference_positions[item.slice_id]
            result[item.slice_id] = tuple(position[index] - reference[index] for index in range(3))
        if set(result) != set(self.expected_slice_ids):
            raise OrchestrationError("motion scatter did not cover the manifest")
        self._last_motion = result
        return dict(result)

    def commit(self) -> None:
        if not self._pending_advance:
            raise OrchestrationError("no tentative global advance to commit")
        self.backend.commit()
        self.committed_step += 1
        self.committed_structural_advances += 1
        self._pending_advance = False
        self._gather.clear()
        self._iteration = None
        self._time_s = None
        self._checkpoint = None

    def checkpoint(self, checkpoint_id: str) -> CouplingCheckpoint:
        if not checkpoint_id or self._checkpoint is not None:
            raise CheckpointError("checkpoint id is empty or a checkpoint is already active")
        if self._pending_advance:
            raise CheckpointError("checkpoint must be taken before a tentative global advance")
        state = CouplingCheckpoint(
            checkpoint_id=checkpoint_id, manifest_sha256=str(self.manifest.manifest_sha256),
            iteration=self._iteration, time_s=self._time_s,
            backend_state=deepcopy(self.backend.snapshot()),
            gathered_slice_ids=tuple(sorted(self._gather)),
            committed_step=self.committed_step,
        )
        self._checkpoint = state
        return state

    def rollback(self) -> None:
        """Restore the active physical checkpoint for a retry.

        A preCICE parallel-implicit time window may request more than one
        rollback before the window is accepted.  The checkpoint therefore
        remains active across retries and is cleared only by :meth:`commit`.
        Backend snapshots contain physical/solver state only; transport
        counters are intentionally owned by the backend and remain monotonic.
        """
        checkpoint = self._checkpoint
        if checkpoint is None:
            raise CheckpointError("no active checkpoint")
        if checkpoint.manifest_sha256 != self.manifest.manifest_sha256:
            raise CheckpointError("checkpoint manifest identity mismatch")
        self.backend.restore(checkpoint.backend_state)
        self._gather.clear()
        self._iteration = None
        self._time_s = None
        self._last_request = None
        self._last_motion = {}
        self._pending_advance = False
        self.committed_step = checkpoint.committed_step
        # Keep the same window checkpoint alive.  It is cleared only after an
        # accepted window in commit(), allowing repeated rollback/retry cycles.

    def reset_iteration(self) -> None:
        if self._pending_advance:
            raise OrchestrationError("cannot reset with a pending advance")
        self._gather.clear()
        self._iteration = None
        self._time_s = None


class FakePreciceFleet:
    """Offline fleet-shaped mock; no preCICE import or process is performed."""

    def __init__(self, manifest: SliceManifest, force_batches: Mapping[int, Mapping[str, ForceSample]]) -> None:
        self.manifest = manifest
        self.force_batches = {int(key): dict(value) for key, value in force_batches.items()}
        self.initialize_calls = 0
        self.advance_calls = 0
        self.finalize_calls = 0
        self.write_calls: list[dict[str, Any]] = []
        self.read_calls: list[str] = []

    def initialize(self) -> None:
        self.initialize_calls += 1

    def write_motion(self, slice_id: str, motion: Sequence[float]) -> None:
        self.manifest.by_id(slice_id)
        self.write_calls.append({"slice_id": slice_id, "motion": list(motion)})

    def advance(self, dt_s: float) -> None:
        if dt_s <= 0.0:
            raise OrchestrationError("fake preCICE dt must be positive")
        self.advance_calls += 1

    def read_force(self, iteration: int, slice_id: str) -> ForceSample:
        if iteration not in self.force_batches or slice_id not in self.force_batches[iteration]:
            raise OrchestrationError("fake preCICE force batch is incomplete")
        self.manifest.by_id(slice_id)
        self.read_calls.append(slice_id)
        return self.force_batches[iteration][slice_id]

    def finalize(self) -> None:
        self.finalize_calls += 1

    def requires_writing_checkpoint(self) -> bool:
        return False

    def requires_reading_checkpoint(self) -> bool:
        return False


def checkpoint_sha256(checkpoint: CouplingCheckpoint) -> str:
    raw = json.dumps(checkpoint.to_dict(), ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
